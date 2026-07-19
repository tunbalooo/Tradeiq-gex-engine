from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import AsyncIterator

from backend.core.config import settings
from backend.services.databento_gex import gex_service
from backend.services.market_data import market_data_service
from backend.services.session_service import get_session_status
from backend.services.trade_engine import trade_engine_service

try:
    from anthropic import AsyncAnthropic
except ImportError:  # pragma: no cover - surfaced by status endpoint
    AsyncAnthropic = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are the read-only market analyst inside TradeIQ for NQ, MNQ, ES, MES, GC, and MGC.
The deterministic TradeIQ engine is the only source of truth. Never change or invent confidence, entry, stop, targets,
confluences, session state, actionability, order state, or GEX. Never provide hidden chain-of-thought or promise profits.

Preview rules:
- PREVIEW_ONLY is a watch-only candidate, not a forecast, scheduled trade, or guarantee that price will reach the levels.
- When the market is closed, say the candidate uses the latest available closed data and must be recalculated after reopening.
- During DATA_SYNCING, say the temporary preview must not be traded.
- Fallback GEX is an estimate. Fallback or simulated GEX is a reliability limitation only; it does not independently block order arming.
- Never say an order must wait for GEX to become live unless the supplied engine state explicitly requires it.
- The session gate and supplied actionable/order_state fields control execution permission.
- Do not repeat entry, stop, TP1, or TP2 values already visible in the Trade Setup panel unless the ACTION line needs one level.

Use this exact compact format, no more than 130 words:
BIAS: direction · supplied confidence
STATUS: one short sentence
CONFIRMED:
- up to 3 short bullets
MISSING:
- up to 2 short bullets
ACTION: one short sentence
RISK: one short sentence
"""


class ClaudeAnalysisService:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._cached_text: str = ""
        self._cached_key: str | None = None
        self._cached_at: datetime | None = None
        self._last_request_at: datetime | None = None
        self._last_error: str | None = None
        self._model_used: str | None = None

    @property
    def enabled(self) -> bool:
        return bool(
            settings.claude_analysis_enabled
            and settings.anthropic_api_key
            and AsyncAnthropic is not None
        )

    def status(self) -> dict:
        return {
            "enabled": self.enabled,
            "configured": bool(settings.anthropic_api_key),
            "sdk_available": AsyncAnthropic is not None,
            "model": settings.anthropic_model,
            "cached": bool(self._cached_text),
            "cached_at": self._cached_at.isoformat() if self._cached_at else None,
            "last_error": self._last_error,
            "analysis_interval_seconds": settings.claude_analysis_interval_seconds,
        }


    def reset_cache(self) -> None:
        self._cached_text = ""
        self._cached_key = None
        self._cached_at = None
        self._last_error = None

    def _snapshot(self) -> dict:
        setup = trade_engine_service.current_setup()
        if setup is None:
            raise RuntimeError("Trade engine is still starting.")

        candles = market_data_service.snapshot(limit=8)
        recent = [candle.model_dump(mode="json") for candle in candles[-8:]]
        market_health = market_data_service.health()
        gex_health = gex_service.health()
        session = get_session_status()

        setup_data = setup.model_dump(mode="json")
        # Keep the request compact and deterministic. Claude does not need all zones or GEX strikes.
        setup_data["zones"] = setup_data.get("zones", [])[:8]
        if setup_data.get("gex"):
            setup_data["gex"]["levels"] = setup_data["gex"].get("levels", [])[:10]

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "market": {
                "symbol": market_health.get("symbol"),
                "mode": market_health.get("mode"),
                "data_source": market_health.get("data_source"),
                "connected": market_health.get("connected"),
                "warming": market_health.get("warming", False),
                "history_cached": market_health.get("history_cached", True),
                "current_price": market_data_service.current_price,
                "recent_candles": recent,
            },
            "session": session,
            "gex_health": gex_health,
            "execution_rules": {
                "session_gate_controls_market_open_permission": True,
                "fallback_gex_independently_blocks_arming": False,
                "engine_actionable": bool(setup_data.get("actionable")),
                "engine_order_state": setup_data.get("order_state"),
                "engine_status": setup_data.get("status"),
            },
            "setup": setup_data,
        }

    def _fingerprint(self, snapshot: dict) -> str:
        setup = snapshot["setup"]
        session = snapshot["session"]
        gex = setup.get("gex") or {}
        important = {
            "symbol": snapshot.get("market", {}).get("symbol"),
            "direction": setup.get("direction"),
            "state": setup.get("order_state"),
            "actionable": setup.get("actionable"),
            "confidence_bucket": round(float(setup.get("confidence", 0)) / 5) * 5,
            "entry": setup.get("entry"),
            "stop": setup.get("stop_loss"),
            "tp1": setup.get("take_profit_1"),
            "tp2": setup.get("take_profit_2"),
            "signals": setup.get("signals"),
            "gex_source": gex.get("source"),
            "gex_ready": snapshot["gex_health"].get("ready"),
            "session_open": session.get("is_open"),
            "session": session.get("session_name"),
        }
        raw = json.dumps(important, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def _cache_fresh(self, key: str) -> bool:
        if not self._cached_text or self._cached_key != key or not self._cached_at:
            return False
        age = (datetime.now(timezone.utc) - self._cached_at).total_seconds()
        return age < max(30, settings.claude_analysis_interval_seconds)

    def _force_allowed(self) -> bool:
        if not self._last_request_at:
            return True
        age = (datetime.now(timezone.utc) - self._last_request_at).total_seconds()
        return age >= max(15, settings.claude_force_min_interval_seconds)

    @staticmethod
    def _sse(event: str, payload: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    async def stream(self, force: bool = False) -> AsyncIterator[str]:
        if not settings.claude_analysis_enabled:
            yield self._sse("analysis_error", {"message": "Claude analysis is disabled. Set CLAUDE_ANALYSIS_ENABLED=true."})
            return
        if not settings.anthropic_api_key:
            yield self._sse("analysis_error", {"message": "ANTHROPIC_API_KEY is not configured on the server."})
            return
        if AsyncAnthropic is None:
            yield self._sse("analysis_error", {"message": "The anthropic Python package is not installed."})
            return

        try:
            snapshot = self._snapshot()
        except Exception as exc:
            yield self._sse("analysis_error", {"message": str(exc)})
            return

        key = self._fingerprint(snapshot)
        force = bool(force and self._force_allowed())

        async with self._lock:
            if not force and self._cache_fresh(key):
                yield self._sse("meta", {
                    "model": self._model_used or settings.anthropic_model,
                    "cached": True,
                    "generated_at": self._cached_at.isoformat() if self._cached_at else None,
                })
                yield self._sse("delta", {"text": self._cached_text})
                yield self._sse("done", {"cached": True})
                return

            self._last_request_at = datetime.now(timezone.utc)
            self._last_error = None
            chunks: list[str] = []
            client = AsyncAnthropic(
                api_key=settings.anthropic_api_key,
                timeout=settings.claude_request_timeout_seconds,
                max_retries=1,
            )
            yield self._sse("meta", {"model": settings.anthropic_model, "cached": False})

            try:
                async with client.messages.stream(
                    model=settings.anthropic_model,
                    max_tokens=settings.claude_max_output_tokens,
                    system=SYSTEM_PROMPT,
                    messages=[{
                        "role": "user",
                        "content": "Analyze this current TradeIQ snapshot:\n" + json.dumps(snapshot, separators=(",", ":"), default=str),
                    }],
                ) as stream:
                    async for text in stream.text_stream:
                        if not text:
                            continue
                        chunks.append(text)
                        yield self._sse("delta", {"text": text})
                    final_message = await stream.get_final_message()

                text = "".join(chunks).strip()
                if not text:
                    raise RuntimeError("Claude returned an empty analysis.")
                self._cached_text = text
                self._cached_key = key
                self._cached_at = datetime.now(timezone.utc)
                self._model_used = getattr(final_message, "model", settings.anthropic_model)
                yield self._sse("done", {
                    "cached": False,
                    "generated_at": self._cached_at.isoformat(),
                    "model": self._model_used,
                })
            except Exception as exc:
                self._last_error = str(exc)
                logger.exception("Claude market analysis failed")
                yield self._sse("analysis_error", {"message": "Claude analysis failed. Check the API key, model access, billing, and Railway logs."})
            finally:
                await client.close()


claude_analysis_service = ClaudeAnalysisService()
