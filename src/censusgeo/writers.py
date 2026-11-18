"""Write results as CSV, GeoJSON and a match-quality report."""

from __future__ import annotations

import csv
import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .models import AddressRecord, GeocodeResult, MatchStatus

RESULT_COLUMNS = [
    "geo_status",
    "geo_match_type",
    "geo_matched_address",
    "geo_longitude",
    "geo_latitude",
    "geo_tiger_line_id",
    "geo_side",
    "geo_state_fips",
    "geo_county_fips",
    "geo_tract",
    "geo_block",
    "geo_tract_geoid",
    "geo_block_geoid",
    "geo_note",
]


def _result_values(result: GeocodeResult) -> dict[str, str]:
    return {
        "geo_status": result.status.value,
        "geo_match_type": result.match_type,
        "geo_matched_address": result.matched_address,
        "geo_longitude": "" if result.longitude is None else f"{result.longitude:.6f}",
        "geo_latitude": "" if result.latitude is None else f"{result.latitude:.6f}",
        "geo_tiger_line_id": result.tiger_line_id,
        "geo_side": result.side,
        "geo_state_fips": result.state_fips,
        "geo_county_fips": result.county_fips,
        "geo_tract": result.tract,
        "geo_block": result.block,
        "geo_tract_geoid": result.tract_geoid,
        "geo_block_geoid": result.block_geoid,
        "geo_note": result.note,
    }


def write_csv(
    path: str | Path,
    records: Sequence[AddressRecord],
    results: Sequence[GeocodeResult],
    input_fieldnames: Sequence[str],
) -> None:
    """Original columns plus geo_* result columns, one row per input record."""
    if len(records) != len(results):
        raise ValueError("records and results must be the same length")
    fieldnames = list(input_fieldnames) + [c for c in RESULT_COLUMNS if c not in input_fieldnames]
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for record, result in zip(records, results, strict=True):
            writer.writerow({**record.extra, **_result_values(result)})


def to_geojson(records: Sequence[AddressRecord], results: Sequence[GeocodeResult]) -> dict:
    """FeatureCollection of matched points (WGS84, [lon, lat] per RFC 7946)."""
    features = []
    for record, result in zip(records, results, strict=True):
        if not result.is_match or result.longitude is None:
            continue
        properties = dict(record.extra)
        properties.update(
            {
                "id": record.id,
                "match_type": result.match_type,
                "matched_address": result.matched_address,
                "tract_geoid": result.tract_geoid or None,
                "block_geoid": result.block_geoid or None,
            }
        )
        features.append(
            {
                "type": "Feature",
                "id": record.id,
                "geometry": {"type": "Point", "coordinates": [result.longitude, result.latitude]},
                "properties": properties,
            }
        )
    return {"type": "FeatureCollection", "features": features}


def write_geojson(path: str | Path, records: Sequence[AddressRecord], results: Sequence[GeocodeResult]) -> int:
    collection = to_geojson(records, results)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(collection, handle, indent=2)
    return len(collection["features"])


@dataclass
class Summary:
    total: int
    submitted: int
    matched: int
    exact: int
    non_exact: int
    ties: int
    no_match: int
    not_submitted: int

    @property
    def match_rate(self) -> float:
        return self.matched / self.total if self.total else 0.0

    @property
    def exact_rate(self) -> float:
        return self.exact / self.matched if self.matched else 0.0


def summarize(results: Sequence[GeocodeResult]) -> Summary:
    statuses = Counter(r.status for r in results)
    match_types = Counter(r.match_type for r in results if r.is_match)
    not_submitted = statuses[MatchStatus.NOT_SUBMITTED]
    return Summary(
        total=len(results),
        submitted=len(results) - not_submitted,
        matched=statuses[MatchStatus.MATCH],
        exact=match_types["Exact"],
        non_exact=match_types["Non_Exact"],
        ties=statuses[MatchStatus.TIE],
        no_match=statuses[MatchStatus.NO_MATCH],
        not_submitted=not_submitted,
    )


def build_report(
    results: Sequence[GeocodeResult],
    *,
    input_name: str,
    benchmark: str,
    return_type: str,
    elapsed_seconds: float,
    max_listed: int = 25,
) -> str:
    """Markdown report a reviewer can read without opening the CSV."""
    s = summarize(results)
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"# Geocoding report: {input_name}",
        "",
        f"Generated {generated} | benchmark `{benchmark}` | return type `{return_type}` | {elapsed_seconds:.1f}s",
        "",
        "| Result | Count | Share |",
        "|---|---:|---:|",
        f"| Matched | {s.matched} | {s.match_rate:.1%} |",
        f"| &nbsp;&nbsp;Exact | {s.exact} | {s.exact_rate:.1%} of matches |",
        f"| &nbsp;&nbsp;Non-exact | {s.non_exact} | |",
        f"| Tie (multiple candidates) | {s.ties} | |",
        f"| No match | {s.no_match} | |",
        f"| Not submitted (failed validation) | {s.not_submitted} | |",
        f"| **Total records** | **{s.total}** | |",
        "",
    ]

    needs_review = [r for r in results if not r.is_match or r.match_type == "Non_Exact"]
    if needs_review:
        lines += [
            f"## Needs review ({len(needs_review)})",
            "",
            "Non-exact matches, ties and failures. Common fixes: add a ZIP code, "
            "remove unit numbers or PO boxes, and check spelling of street names.",
            "",
            "| ID | Status | Input address | Note / matched address |",
            "|---|---|---|---|",
        ]
        for r in needs_review[:max_listed]:
            detail = r.note or r.matched_address
            lines.append(f"| {r.id} | {r.status.value} {r.match_type} | {r.input_address} | {detail} |")
        if len(needs_review) > max_listed:
            lines.append(f"| ... | | {len(needs_review) - max_listed} more in the output CSV | |")
        lines.append("")

    return "\n".join(lines)
