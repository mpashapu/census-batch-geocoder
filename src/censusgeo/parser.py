"""Parse the CSV returned by the Census batch geocoder.

The response has no header row. Columns:

  locations:   id, input address, match, match type, matched address,
               "lon,lat", TIGER line id, side
  geographies: the same, then state FIPS, county FIPS, tract, block

Unmatched and tied rows stop after the match column. Rows are not returned
in input order, so results are joined back to the input by id.
"""

from __future__ import annotations

import csv
import io
import logging

from .models import GeocodeResult, MatchStatus

log = logging.getLogger(__name__)

_STATUS = {s.value.lower(): s for s in MatchStatus}


def _status(value: str) -> MatchStatus | None:
    return _STATUS.get(value.strip().lower())


def _coordinates(value: str) -> tuple[float | None, float | None]:
    try:
        lon_text, lat_text = value.split(",")
        lon, lat = float(lon_text), float(lat_text)
    except (ValueError, AttributeError):
        return None, None
    # Census returns "longitude,latitude". Reject impossible values rather than
    # writing a bad point to the GeoJSON.
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        return None, None
    return lon, lat


def parse_batch_response(text: str) -> list[GeocodeResult]:
    """Parse response text into results. Malformed rows are logged and skipped."""
    results: list[GeocodeResult] = []
    for line_number, row in enumerate(csv.reader(io.StringIO(text)), start=1):
        if not row or all(not cell.strip() for cell in row):
            continue
        cells = [cell.strip() for cell in row] + [""] * 12
        status = _status(cells[2])
        if status is None:
            log.warning("Skipping unrecognized response line %d: %r", line_number, row[:3])
            continue

        result = GeocodeResult(id=cells[0], input_address=cells[1], status=status)
        if status is MatchStatus.MATCH:
            lon, lat = _coordinates(cells[5])
            result.match_type = cells[3]
            result.matched_address = cells[4]
            result.longitude, result.latitude = lon, lat
            result.tiger_line_id = cells[6]
            result.side = cells[7]
            result.state_fips = cells[8]
            result.county_fips = cells[9]
            result.tract = cells[10]
            result.block = cells[11]
            if lon is None:
                result.note = f"unparseable coordinates: {cells[5]!r}"
        results.append(result)
    return results
