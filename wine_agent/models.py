"""Data models for Wine Cellar Management and Drinking Window Engine."""

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional, List, Dict, Any
from datetime import datetime


class WineType(str, Enum):
    RED = "Red"
    WHITE = "White"
    SPARKLING = "Sparkling"
    ROSE = "Rosé"
    DESSERT = "Dessert / Sweet"
    FORTIFIED = "Fortified"


class DrinkingStatus(str, Enum):
    TOO_YOUNG = "Hold (Too Young)"
    EARLY_WINDOW = "Approaching Peak"
    PEAK = "In Peak Window"
    LATE_PEAK = "Drink Soon (Late Peak)"
    PAST_PEAK = "Past Peak (Decline)"


class BottleFormat(str, Enum):
    HALF = "Half (375ml)"
    STANDARD = "Standard (750ml)"
    MAGNUM = "Magnum (1.5L)"
    DOUBLE_MAGNUM = "Double Magnum (3.0L)"
    IMPERIAL = "Imperial / Methuselah (6.0L)"


@dataclass
class DrinkingWindow:
    window_start: int          # First year ready to drink (approachable)
    peak_start: int            # Start of prime maturity
    peak_end: int              # End of prime maturity
    window_end: int            # Year after which wine noticeably declines
    status: DrinkingStatus     # Current status relative to reference year
    progress_pct: float        # 0% = early window, 50% = mid-peak, 100% = end of window
    rationale: str             # Enological explanation of the window
    decant_hours: float        # Recommended decanting duration in hours (0.0 = none)
    serving_temp_c: int        # Recommended serving temperature in Celsius
    serving_temp_f: int        # Recommended serving temperature in Fahrenheit
    aging_tier: str            # e.g., "Long-Aging Collector (15-30 years)"

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d


@dataclass
class WineBottle:
    id: Optional[int] = None
    producer: str = ""
    wine_name: str = ""
    vintage: Optional[int] = None  # None for Non-Vintage (NV)
    varietal: str = ""
    region: str = ""
    sub_region: str = ""
    country: str = ""
    wine_type: WineType = WineType.RED
    format: BottleFormat = BottleFormat.STANDARD
    quantity: int = 1
    location_rack: str = ""
    location_bin: str = ""
    purchase_date: Optional[str] = None
    purchase_price: Optional[float] = None
    market_value: Optional[float] = None
    critic_score: Optional[int] = None
    user_rating: Optional[float] = None
    personal_notes: str = ""
    critic_reviews: List[Dict[str, Any]] = field(default_factory=list)
    food_pairings: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    drinking_window: Optional[DrinkingWindow] = None

    def to_dict(self) -> Dict[str, Any]:
        res = asdict(self)
        res["wine_type"] = self.wine_type.value if isinstance(self.wine_type, WineType) else self.wine_type
        res["format"] = self.format.value if isinstance(self.format, BottleFormat) else self.format
        if self.drinking_window:
            res["drinking_window"] = self.drinking_window.to_dict()
        return res

    @property
    def display_name(self) -> str:
        yr = str(self.vintage) if self.vintage else "NV"
        parts = [yr, self.producer]
        if self.wine_name and self.wine_name.lower() != self.producer.lower():
            parts.append(self.wine_name)
        return " ".join(p for p in parts if p)


@dataclass
class ConsumptionRecord:
    id: Optional[int] = None
    bottle_id: int = 0
    wine_display_name: str = ""
    date_opened: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))
    rating: Optional[float] = None
    tasting_notes: str = ""
    pairing_notes: str = ""
    bottles_consumed: int = 1
    aging_curve_stage: str = ""
    action_type: str = "opened"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
