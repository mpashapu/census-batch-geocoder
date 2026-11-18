"""Batch geocode U.S. addresses with the free U.S. Census Bureau Geocoder."""

from .client import CensusBatchClient, CensusGeocoderError
from .models import AddressRecord, GeocodeResult, MatchStatus
from .reader import read_addresses

__all__ = [
    "AddressRecord",
    "CensusBatchClient",
    "CensusGeocoderError",
    "GeocodeResult",
    "MatchStatus",
    "read_addresses",
]

__version__ = "1.0.0"
