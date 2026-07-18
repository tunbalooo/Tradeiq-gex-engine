import asyncio
import logging
import threading
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from backend.core.config import settings
from backend.models.schemas import GexSummary
from engine.gex import OptionPosition, derive_gex_summary_from_positions
from backend.services.market_data import available_dataset_end

logger = logging.getLogger(__name__)

NANO = 1_000_000_000
OPEN_INTEREST = 9
VOLATILITY = 14


@dataclass(slots=True)
class OptionDefinition:
    instrument_id: int
    symbol: str
    strike: float
    option_type: str
    expiration: datetime
    multiplier: int
    underlying_id: int | None = None


def _char(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "value"):
        value = value.value
    text = str(value)
    if text.endswith("CALL"):
        return "C"
    if text.endswith("PUT"):
        return "P"
    return text[-1:] if text else ""


def _pretty_price(record: Any, field: str = "price") -> float | None:
    pretty_name = f"pretty_{field}"
    value = getattr(record, pretty_name, None)
    if value is not None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    raw = getattr(record, field, None)
    if raw is None or int(raw) == 9223372036854775807:
        return None
    return float(raw) / NANO


def _to_datetime_ns(value: int) -> datetime:
    return datetime.fromtimestamp(int(value) / NANO, tz=timezone.utc)


class DatabentoGexService:
    def __init__(self):
        self._lock = threading.RLock()
        self._positions: list[OptionPosition] = []
        self.updated_at: datetime | None = None
        self.last_error: str | None = None
        self.refreshing = False
        self._task: asyncio.Task | None = None
        self.source = "databento-native-nq" if settings.use_databento else "simulated"

    async def start(self) -> None:
        if not settings.use_databento:
            return
        await self.refresh()
        self._task = asyncio.create_task(self._refresh_loop(), name="databento-gex-refresh")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _refresh_loop(self) -> None:
        while True:
            await asyncio.sleep(max(settings.gex_refresh_seconds, 60))
            await self.refresh()

    async def refresh(self) -> bool:
        if not settings.use_databento or self.refreshing:
            return False
        self.refreshing = True
        try:
            positions = await asyncio.to_thread(self._load_positions)
            if not positions:
                raise RuntimeError("No eligible NQ option positions were returned.")
            with self._lock:
                self._positions = positions
                self.updated_at = datetime.now(timezone.utc)
                self.last_error = None
            logger.info("Loaded %s native NQ option positions for GEX", len(positions))
            return True
        except Exception as exc:
            self.last_error = str(exc)
            logger.exception("Databento native NQ GEX refresh failed")
            return False
        finally:
            self.refreshing = False

    def _import_db(self):
        try:
            import databento as db
        except ImportError as exc:
            raise RuntimeError(
                "The databento package is not installed. Run: python -m pip install -U databento"
            ) from exc
        return db

    def _load_definitions(self, client: Any, day: date, futures_price: float) -> list[OptionDefinition]:
        start = datetime.combine(day, time.min, tzinfo=timezone.utc)
        requested_end = start + timedelta(days=1)
        end = available_dataset_end(client, settings.databento_dataset, "definition", requested_end)
        if end <= start:
            return []
        store = client.timeseries.get_range(
            dataset=settings.databento_dataset,
            schema="definition",
            stype_in="parent",
            symbols=[settings.databento_options_parent],
            start=start.isoformat(),
            end=end.isoformat(),
        )

        now = datetime.now(timezone.utc)
        maximum_expiry = now + timedelta(days=settings.gex_max_dte)
        definitions: dict[int, OptionDefinition] = {}

        for record in store:
            if not hasattr(record, "instrument_class") or not hasattr(record, "strike_price"):
                continue
            instrument_class = _char(record.instrument_class)
            if instrument_class not in {"C", "P"}:
                continue

            strike = _pretty_price(record, "strike_price")
            if strike is None or strike <= 0:
                continue
            expiration = _to_datetime_ns(record.expiration)
            if expiration <= now or expiration > maximum_expiry:
                continue
            if abs(strike - futures_price) > settings.gex_strike_range_points:
                continue

            symbol = str(record.raw_symbol)
            definitions[int(record.instrument_id)] = OptionDefinition(
                instrument_id=int(record.instrument_id),
                symbol=symbol,
                strike=float(strike),
                option_type="CALL" if instrument_class == "C" else "PUT",
                expiration=expiration,
                multiplier=settings.nq_contract_multiplier,
                underlying_id=int(getattr(record, "underlying_id", 0)) or None,
            )

        expirations = sorted({definition.expiration for definition in definitions.values()})
        allowed = set(expirations[: settings.gex_expiry_count])
        selected = [definition for definition in definitions.values() if definition.expiration in allowed]
        # NQ.OPT can contain contracts tied to more than one futures month. Select
        # the dominant underlying_id group to avoid mixing multiple futures books
        # against one continuous NQ price. If the feed omits underlying_id, retain
        # the filtered chain and expose the estimate label in the dashboard.
        groups: dict[int, list[OptionDefinition]] = {}
        for definition in selected:
            if definition.underlying_id:
                groups.setdefault(definition.underlying_id, []).append(definition)
        if groups:
            selected = max(groups.values(), key=len)
        return selected

    def _load_stats(
        self,
        client: Any,
        day: date,
        definitions: list[OptionDefinition],
    ) -> tuple[dict[int, int], dict[int, float]]:
        if not definitions:
            return {}, {}

        start = datetime.combine(day, time.min, tzinfo=timezone.utc)
        requested_end = min(datetime.now(timezone.utc) + timedelta(minutes=1), start + timedelta(days=1))
        end = available_dataset_end(client, settings.databento_dataset, "statistics", requested_end)
        if end <= start:
            return {}, {}
        symbols = [definition.symbol for definition in definitions]
        oi: dict[int, int] = {}
        iv: dict[int, float] = {}

        for offset in range(0, len(symbols), 1800):
            chunk = symbols[offset: offset + 1800]
            store = client.timeseries.get_range(
                dataset=settings.databento_dataset,
                schema="statistics",
                stype_in="raw_symbol",
                symbols=chunk,
                start=start.isoformat(),
                end=end.isoformat(),
            )
            for record in store:
                instrument_id = int(record.instrument_id)
                stat_type = int(record.stat_type)
                if stat_type == OPEN_INTEREST:
                    quantity = int(getattr(record, "quantity", 0))
                    if quantity >= 0 and quantity < 9_000_000_000_000_000_000:
                        oi[instrument_id] = quantity
                elif stat_type == VOLATILITY:
                    value = _pretty_price(record, "price")
                    if value is None:
                        continue
                    if value > 3:
                        value /= 100
                    if 0.01 <= value <= 5:
                        iv[instrument_id] = float(value)
        return oi, iv

    def _load_positions(self) -> list[OptionPosition]:
        from backend.services.market_data import market_data_service

        db = self._import_db()
        client = db.Historical(key=settings.databento_api_key)
        futures_price = float(market_data_service.current_price)
        today = datetime.now(timezone.utc).date()

        definitions = self._load_definitions(client, today, futures_price)
        oi, iv = self._load_stats(client, today, definitions)

        if not oi:
            for back in range(1, 5):
                candidate = today - timedelta(days=back)
                if candidate.weekday() >= 5:
                    continue
                candidate_defs = self._load_definitions(client, candidate, futures_price)
                candidate_oi, candidate_iv = self._load_stats(client, candidate, candidate_defs)
                if candidate_oi:
                    definitions, oi, iv = candidate_defs, candidate_oi, candidate_iv
                    break

        now = datetime.now(timezone.utc)
        positions: list[OptionPosition] = []
        for definition in definitions:
            open_interest = oi.get(definition.instrument_id, 0)
            if open_interest <= 0:
                continue
            expiry_years = max((definition.expiration - now).total_seconds() / (365.0 * 86400.0), 1 / 3650)
            implied_volatility = iv.get(definition.instrument_id)
            if implied_volatility is None:
                moneyness = abs(definition.strike - futures_price) / max(futures_price, 1)
                skew = 0.03 if definition.option_type == "PUT" else 0.0
                implied_volatility = settings.gex_default_iv + moneyness * 1.8 + skew

            positions.append(
                OptionPosition(
                    strike=definition.strike,
                    expiry_years=expiry_years,
                    option_type=definition.option_type,
                    open_interest=open_interest,
                    implied_volatility=float(implied_volatility),
                    rate=settings.gex_risk_free_rate,
                    contract_multiplier=definition.multiplier,
                    symbol=definition.symbol,
                    expiration_ns=int(definition.expiration.timestamp() * NANO),
                )
            )
        return positions

    def get_summary(self, futures_price: float) -> GexSummary | None:
        with self._lock:
            positions = list(self._positions)
            updated_at = self.updated_at

        if not positions:
            return None
        raw = derive_gex_summary_from_positions(
            futures_price,
            positions,
            flip_range_points=settings.gex_strike_range_points,
        )
        raw.update(
            {
                "source": self.source,
                "updated_at": updated_at,
                "contract_count": len(positions),
                "expiry_count": len({position.expiration_ns for position in positions}),
                "is_estimate": True,
            }
        )
        return GexSummary(**raw)

    def health(self) -> dict:
        with self._lock:
            position_count = len(self._positions)
        return {
            "source": self.source,
            "ready": position_count > 0,
            "position_count": position_count,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "refreshing": self.refreshing,
            "last_error": self.last_error,
        }


gex_service = DatabentoGexService()
