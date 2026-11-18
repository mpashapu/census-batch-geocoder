"""Data models for input addresses and geocoding results."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class MatchStatus(str, Enum):
    """Match indicator returned by the Census Geocoder."""

    MATCH = "Match"
    NO_MATCH = "No_Match"
    TIE = "Tie"
    NOT_SUBMITTED = "Not_Submitted"  # failed local validation, never sent


@dataclass(frozen=True)
class AddressRecord:
    """One address to geocode, in the structure the batch API expects."""

    id: str
    street: str
    city: str = ""
    state: str = ""
    zip: str = ""
    extra: dict[str, str] = field(default_factory=dict, compare=False)
    row_number: int = field(default=0, compare=False)  # 1-based position in the input file

    def as_batch_row(self) -> list[str]:
        """Row for the Census batch file: Unique ID, Street, City, State, ZIP."""
        return [self.id, self.street, self.city, self.state, self.zip]

    @property
    def one_line(self) -> str:
        parts = [self.street, self.city, " ".join(p for p in (self.state, self.zip) if p)]
        return ", ".join(p for p in parts if p)


@dataclass
class GeocodeResult:
    """Parsed result row for one address."""

    id: str
    input_address: str
    status: MatchStatus
    match_type: str = ""  # "Exact" or "Non_Exact" when matched
    matched_address: str = ""
    longitude: float | None = None
    latitude: float | None = None
    tiger_line_id: str = ""
    side: str = ""
    # Present only when using the "geographies" return type
    state_fips: str = ""
    county_fips: str = ""
    tract: str = ""
    block: str = ""
    note: str = ""  # local notes, e.g. why a record was not submitted

    @property
    def is_match(self) -> bool:
        return self.status is MatchStatus.MATCH

    @property
    def tract_geoid(self) -> str:
        """11-digit census tract GEOID (state + county + tract), if available."""
        if self.state_fips and self.county_fips and self.tract:
            return f"{self.state_fips}{self.county_fips}{self.tract}"
        return ""

    @property
    def block_geoid(self) -> str:
        """15-digit census block GEOID, if available."""
        tract = self.tract_geoid
        return f"{tract}{self.block}" if tract and self.block else ""
