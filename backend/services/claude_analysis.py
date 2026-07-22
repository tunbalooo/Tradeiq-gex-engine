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
from backend.services.storage_service import storage_service
from backend.services.trade_engine import trade_engine_service

try:
    from anthropic import AsyncAnthropic
except ImportError:  # pragma: no cover - surfaced by status endpoint
    AsyncAnthropic = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are the read-only lifecycle analyst inside TradeIQ for NQ, MNQ, ES, MES, GC, and MGC.
The deterministic TradeIQ engine is the only source of truth. Never invent or change confidence, direction, entry, stop,
targets, confluences, session state, actionability, order state, transition reason, or GEX. Never promise profits.

Your main job is to explain WHY the engine is in its current lifecycle state and WHAT must happen next.
Use setup.last_transition_* and lifecycle_event as the authoritative reason for a state change.
Use lifecycle_timeline only as historical context. Never rewrite or contradict the latest deterministic transition.

State rules:
- PREVIEW_ONLY is not a forecast, scheduled trade, or guarantee. Explain that no plan exists yet and name the strongest present and missing confirmations.
- WATCHING/MONITORING: the watch_trigger is NOT an entry and no limit is armed. Explain precisely which confirmations are
  present, which mandatory confirmations are still missing, and what would allow the engine to produce a locked limit plan.
  If watch_phase is TRIGGER_TOUCHED, state that price reached the monitoring level, no fill occurred, and the engine is waiting
  inside a finite confirmation window. For WATCHING → WATCHING, use last_transition_reason to distinguish a trigger touch
  from a primary-entry-model switch; never assume that every same-state transition is a model switch.
- WAITING_FOR_LIMIT: explain why the plan qualified, why the entry area was selected, what invalidates the idea at the
  supplied stop, and what market structures/sources justify TP1 and TP2. State that all levels are locked.
- FILLED: explain that the locked limit was touched, then explain the supplied protective stop and both targets.
- TP1_HIT: explain that TP1 was reached, the recorded partial percentage, whether the active stop moved to break-even,
  and what remains for the runner. Distinguish the immutable initial stop from active_stop_loss.
- TP2_HIT: explain why the plan is complete.
- INVALIDATED, EXPIRED, UNCONFIRMED_TOUCH, or a transition back to PREVIEW_ONLY: explain the exact cancellation reason
  from last_transition_reason. Never replace it with a generic explanation.
- STOPPED: explain the supplied deterministic stop event without hindsight or blame. If outcome is
  BREAKEVEN_AFTER_TP1, state that partial profit had already been secured before the runner exited at break-even.
- Market closed or DATA_SYNCING: say execution is unavailable and do not imply a live order can be used.
- Fallback GEX is an estimate. Fallback or simulated GEX is a reliability limitation only; it does not independently block order arming.
- Never say an order must wait for GEX to become live unless the supplied deterministic engine state explicitly requires it.
- The session gate and supplied actionable/order_state fields control execution permission.
- setup.market_map is location context only. Explain active/opposing clusters when relevant, but never treat a cluster touch as an entry unless the deterministic model and execution fields are already actionable.

Do not repeat entry, stop, TP1, or TP2 in PREVIEW_ONLY or WATCHING. You MAY repeat them in WAITING_FOR_LIMIT, FILLED,
or TP1_HIT because the user wants a lifecycle explanation of the full locked plan.

The primary_entry_model and model_selection_reason are deterministic. Explain them, but never change their scores or rank.
Legacy guidance: no more than 130 words.
Use this exact compact format, no more than 150 words:
EVENT: current lifecycle event in one sentence
WHY: specific engine reason in one or two sentences
CONFIRMED:
- up to 3 short bullets
MISSING/NEXT:
- up to 2 short bullets
LEVELS: explain supplied trigger or locked entry/SL/TP values only when relevant
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

        lifecycle_timeline = storage_service.setup_timeline(setup.setup_id, limit=12)

        lifecycle_event = {
            "setup_id": setup_data.get("setup_id"),
            "previous_state": setup_data.get("last_transition_from"),
            "current_state": setup_data.get("order_state"),
            "transition_to": setup_data.get("last_transition_to"),
            "reason": setup_data.get("last_transition_reason"),
            "occurred_at": setup_data.get("last_transition_at"),
            "transition_price": setup_data.get("last_transition_price"),
            "watch_trigger": setup_data.get("watch_trigger"),
            "watch_invalidation": setup_data.get("watch_invalidation"),
            "watch_phase": setup_data.get("watch_phase"),
            "watch_touch_at": setup_data.get("watch_touch_at"),
            "watch_touch_price": setup_data.get("watch_touch_price"),
            "watch_confirmation_expires_at": setup_data.get("watch_confirmation_expires_at"),
            "watch_expires_at": setup_data.get("watch_expires_at"),
            "armed_at": setup_data.get("armed_at"),
            "filled_at": setup_data.get("filled_at"),
            "closed_at": setup_data.get("closed_at"),
            "outcome": setup_data.get("outcome"),
            "entry": setup_data.get("entry"),
            "stop_loss": setup_data.get("stop_loss"),
            "active_stop_loss": setup_data.get("active_stop_loss"),
            "take_profit_1": setup_data.get("take_profit_1"),
            "take_profit_2": setup_data.get("take_profit_2"),
            "target_sources": setup_data.get("target_sources") or {},
            "primary_entry_model": setup_data.get("primary_entry_model"),
            "primary_model_score": setup_data.get("primary_model_score"),
            "alternative_entry_models": setup_data.get("alternative_entry_models") or [],
            "model_selection_reason": setup_data.get("model_selection_reason"),
            "confidence_grade": setup_data.get("confidence_grade"),
            "management_state": setup_data.get("management_state"),
            "partial_exit_percent": setup_data.get("partial_exit_percent"),
            "runner_active": setup_data.get("runner_active"),
            "management_actions": setup_data.get("management_actions") or [],
        }

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
            "lifecycle_event": lifecycle_event,
            "lifecycle_timeline": lifecycle_timeline,
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
        lifecycle = snapshot.get("lifecycle_event") or {}
        important = {
            "symbol": snapshot.get("market", {}).get("symbol"),
            "setup_id": setup.get("setup_id"),
            "direction": setup.get("direction"),
            "state": setup.get("order_state"),
            "actionable": setup.get("actionable"),
            "confidence_bucket": round(float(setup.get("confidence", 0)) / 5) * 5,
            "watch_trigger": setup.get("watch_trigger"),
            "watch_phase": setup.get("watch_phase"),
            "watch_touch_at": setup.get("watch_touch_at"),
            "watch_confirmation_expires_at": setup.get("watch_confirmation_expires_at"),
            "entry": setup.get("entry"),
            "stop": setup.get("stop_loss"),
            "active_stop": setup.get("active_stop_loss"),
            "primary_model": setup.get("primary_entry_model"),
            "primary_model_score": setup.get("primary_model_score"),
            "management_state": setup.get("management_state"),
            "tp1": setup.get("take_profit_1"),
            "tp2": setup.get("take_profit_2"),
            "signals": setup.get("signals"),
            "gex_source": gex.get("source"),
            "gex_ready": snapshot["gex_health"].get("ready"),
            "session_open": session.get("is_open"),
            "session": session.get("session_name"),
            "transition_from": lifecycle.get("previous_state"),
            "transition_to": lifecycle.get("transition_to"),
            "transition_at": lifecycle.get("occurred_at"),
            "transition_reason": lifecycle.get("reason"),
            "outcome": lifecycle.get("outcome"),
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
                        "content": (
                            "Explain the current TradeIQ lifecycle event, why the engine is in this state, "
                            "and what happens next. Use the deterministic transition reason exactly.\n"
                            + json.dumps(snapshot, separators=(",", ":"), default=str)
                        ),
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
