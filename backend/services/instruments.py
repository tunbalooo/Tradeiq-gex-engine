from __future__ import annotations

from dataclasses import asdict, dataclass
from threading import RLock

from backend.core.config import settings


@dataclass(frozen=True, slots=True)
class InstrumentProfile:
    symbol: str
    display_symbol: str
    name: str
    family: str
    futures_continuous: str
    options_parent: str
    gex_source_symbol: str
    gex_contract_multiplier: int
    tick_size: float
    price_precision: int
    simulation_start_price: float
    simulation_history_width: float
    simulation_wave_slow: float
    simulation_wave_fast: float
    simulation_noise: float
    gex_strike_range_points: float
    gex_flip_step: float
    option_strike_increment: float
    mock_option_width: float
    default_iv: float
    rth_start_hour: int
    rth_start_minute: int
    rth_end_hour: int
    rth_end_minute: int
    has_equity_halt: bool
    news_terms: tuple[str, ...]

    @property
    def uses_parent_gex(self) -> bool:
        return self.symbol != self.gex_source_symbol

    @property
    def gex_source_label(self) -> str:
        if self.family == "GOLD":
            base = "GC Gold options (OG)"
        else:
            base = f"{self.gex_source_symbol} options"
        return f"{base} applied to {self.symbol}" if self.uses_parent_gex else base

    def public_dict(self) -> dict:
        data = asdict(self)
        data.pop("news_terms", None)
        data.update(
            {
                "uses_parent_gex": self.uses_parent_gex,
                "gex_source_label": self.gex_source_label,
            }
        )
        return data


_COMMON_MACRO = (
    "federal reserve", "fed", "fomc", "inflation", "cpi", "ppi",
    "payroll", "jobs report", "treasury", "yield", "interest rate",
    "dollar", "usd", "recession", "gdp",
)

INSTRUMENTS: dict[str, InstrumentProfile] = {
    "NQ": InstrumentProfile(
        symbol="NQ", display_symbol="NQ1!", name="E-mini Nasdaq-100", family="NASDAQ",
        futures_continuous="NQ.v.0", options_parent="NQ.OPT", gex_source_symbol="NQ",
        gex_contract_multiplier=20, tick_size=0.25, price_precision=2,
        simulation_start_price=24892.25, simulation_history_width=115.0,
        simulation_wave_slow=24.0, simulation_wave_fast=11.0, simulation_noise=1.95,
        gex_strike_range_points=700.0, gex_flip_step=5.0,
        option_strike_increment=25.0, mock_option_width=300.0, default_iv=0.20,
        rth_start_hour=9, rth_start_minute=30, rth_end_hour=16, rth_end_minute=0,
        has_equity_halt=True,
        news_terms=("nasdaq", "nasdaq 100", "technology", "tech stocks", "semiconductor",
                    "nvidia", "nvda", "microsoft", "msft", "apple", "aapl", "amazon",
                    "amzn", "meta", "tesla", "tsla", "alphabet", "google", "ai") + _COMMON_MACRO,
    ),
    "MNQ": InstrumentProfile(
        symbol="MNQ", display_symbol="MNQ1!", name="Micro E-mini Nasdaq-100", family="NASDAQ",
        futures_continuous="MNQ.v.0", options_parent="NQ.OPT", gex_source_symbol="NQ",
        gex_contract_multiplier=20, tick_size=0.25, price_precision=2,
        simulation_start_price=24892.25, simulation_history_width=115.0,
        simulation_wave_slow=24.0, simulation_wave_fast=11.0, simulation_noise=1.95,
        gex_strike_range_points=700.0, gex_flip_step=5.0,
        option_strike_increment=25.0, mock_option_width=300.0, default_iv=0.20,
        rth_start_hour=9, rth_start_minute=30, rth_end_hour=16, rth_end_minute=0,
        has_equity_halt=True,
        news_terms=("nasdaq", "nasdaq 100", "technology", "tech stocks", "semiconductor",
                    "nvidia", "nvda", "microsoft", "msft", "apple", "aapl", "amazon",
                    "amzn", "meta", "tesla", "tsla", "alphabet", "google", "ai") + _COMMON_MACRO,
    ),
    "ES": InstrumentProfile(
        symbol="ES", display_symbol="ES1!", name="E-mini S&P 500", family="SP500",
        futures_continuous="ES.v.0", options_parent="ES.OPT", gex_source_symbol="ES",
        gex_contract_multiplier=50, tick_size=0.25, price_precision=2,
        simulation_start_price=6200.00, simulation_history_width=42.0,
        simulation_wave_slow=10.0, simulation_wave_fast=4.5, simulation_noise=0.85,
        gex_strike_range_points=260.0, gex_flip_step=1.0,
        option_strike_increment=5.0, mock_option_width=100.0, default_iv=0.18,
        rth_start_hour=9, rth_start_minute=30, rth_end_hour=16, rth_end_minute=0,
        has_equity_halt=True,
        news_terms=("s&p 500", "sp 500", "wall street", "us stocks", "equities", "earnings",
                    "banks", "energy stocks", "industrials") + _COMMON_MACRO,
    ),
    "MES": InstrumentProfile(
        symbol="MES", display_symbol="MES1!", name="Micro E-mini S&P 500", family="SP500",
        futures_continuous="MES.v.0", options_parent="ES.OPT", gex_source_symbol="ES",
        gex_contract_multiplier=50, tick_size=0.25, price_precision=2,
        simulation_start_price=6200.00, simulation_history_width=42.0,
        simulation_wave_slow=10.0, simulation_wave_fast=4.5, simulation_noise=0.85,
        gex_strike_range_points=260.0, gex_flip_step=1.0,
        option_strike_increment=5.0, mock_option_width=100.0, default_iv=0.18,
        rth_start_hour=9, rth_start_minute=30, rth_end_hour=16, rth_end_minute=0,
        has_equity_halt=True,
        news_terms=("s&p 500", "sp 500", "wall street", "us stocks", "equities", "earnings",
                    "banks", "energy stocks", "industrials") + _COMMON_MACRO,
    ),
    "GC": InstrumentProfile(
        symbol="GC", display_symbol="GC1!", name="COMEX Gold", family="GOLD",
        futures_continuous="GC.v.0", options_parent="OG.OPT", gex_source_symbol="GC",
        gex_contract_multiplier=100, tick_size=0.10, price_precision=1,
        simulation_start_price=3350.0, simulation_history_width=55.0,
        simulation_wave_slow=13.0, simulation_wave_fast=5.5, simulation_noise=1.10,
        gex_strike_range_points=300.0, gex_flip_step=1.0,
        option_strike_increment=10.0, mock_option_width=160.0, default_iv=0.17,
        rth_start_hour=8, rth_start_minute=20, rth_end_hour=13, rth_end_minute=30,
        has_equity_halt=False,
        news_terms=("gold", "bullion", "precious metals", "comex", "xau", "central bank",
                    "geopolitical", "safe haven", "real yields", "dollar index") + _COMMON_MACRO,
    ),
    "MGC": InstrumentProfile(
        symbol="MGC", display_symbol="MGC1!", name="Micro Gold", family="GOLD",
        futures_continuous="MGC.v.0", options_parent="OG.OPT", gex_source_symbol="GC",
        gex_contract_multiplier=100, tick_size=0.10, price_precision=1,
        simulation_start_price=3350.0, simulation_history_width=55.0,
        simulation_wave_slow=13.0, simulation_wave_fast=5.5, simulation_noise=1.10,
        gex_strike_range_points=300.0, gex_flip_step=1.0,
        option_strike_increment=10.0, mock_option_width=160.0, default_iv=0.17,
        rth_start_hour=8, rth_start_minute=20, rth_end_hour=13, rth_end_minute=30,
        has_equity_halt=False,
        news_terms=("gold", "bullion", "precious metals", "comex", "xau", "central bank",
                    "geopolitical", "safe haven", "real yields", "dollar index") + _COMMON_MACRO,
    ),
}


def normalize_symbol(symbol: str | None) -> str:
    value = str(symbol or "").strip().upper()
    if value not in INSTRUMENTS:
        supported = ", ".join(INSTRUMENTS)
        raise ValueError(f"Unsupported market symbol '{value}'. Supported symbols: {supported}.")
    return value


def get_instrument(symbol: str | None) -> InstrumentProfile:
    return INSTRUMENTS[normalize_symbol(symbol)]


class InstrumentRegistry:
    def __init__(self) -> None:
        self._lock = RLock()
        requested = settings.default_symbol or settings.simulation_symbol or "NQ"
        try:
            self._active_symbol = normalize_symbol(requested)
        except ValueError:
            self._active_symbol = "NQ"

    @property
    def active(self) -> InstrumentProfile:
        with self._lock:
            return INSTRUMENTS[self._active_symbol]

    def select(self, symbol: str) -> InstrumentProfile:
        normalized = normalize_symbol(symbol)
        with self._lock:
            self._active_symbol = normalized
        return INSTRUMENTS[normalized]

    def list_public(self) -> list[dict]:
        active = self.active.symbol
        return [profile.public_dict() | {"active": profile.symbol == active} for profile in INSTRUMENTS.values()]


instrument_registry = InstrumentRegistry()
