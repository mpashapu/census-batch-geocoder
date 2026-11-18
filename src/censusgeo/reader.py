"""Read and validate input address files."""

from __future__ import annotations

import csv
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from .models import AddressRecord

log = logging.getLogger(__name__)

# Header names recognized automatically (case-insensitive)
COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "id": ("id", "unique_id", "uid", "record_id", "objectid", "permit_id", "folio"),
    "street": ("street", "address", "street_address", "address1", "addr", "site_address"),
    "city": ("city", "town", "municipality"),
    "state": ("state", "st", "state_code"),
    "zip": ("zip", "zipcode", "zip_code", "postal_code", "postcode"),
}

ZIP_PATTERN = re.compile(r"^\d{5}(-?\d{4})?$")


@dataclass
class ReadResult:
    records: list[AddressRecord] = field(default_factory=list)
    rejected: list[tuple[AddressRecord, str]] = field(default_factory=list)
    columns: dict[str, str | None] = field(default_factory=dict)
    fieldnames: list[str] = field(default_factory=list)


def _resolve_columns(fieldnames: list[str], overrides: dict[str, str | None]) -> dict[str, str | None]:
    lower = {name.strip().lower(): name for name in fieldnames}
    resolved: dict[str, str | None] = {}
    for role, aliases in COLUMN_ALIASES.items():
        override = overrides.get(role)
        if override:
            if override not in fieldnames:
                raise ValueError(f"Column '{override}' for {role} not found. Columns: {', '.join(fieldnames)}")
            resolved[role] = override
            continue
        resolved[role] = next((lower[a] for a in aliases if a in lower), None)
    if not resolved["street"]:
        raise ValueError(f"Could not find a street column. Use --street-col. Columns found: {', '.join(fieldnames)}")
    return resolved


def _clean(value: str | None) -> str:
    # Collapse whitespace; the batch file is CSV so commas are fine once quoted
    return " ".join((value or "").split())


def validate(record: AddressRecord) -> str | None:
    """Return a reason the record can't be geocoded, or None if it looks usable."""
    if not record.street:
        return "missing street"
    if not any(ch.isdigit() for ch in record.street):
        return "street has no house number"
    if not (record.zip or (record.city and record.state)):
        return "needs ZIP or city + state"
    if record.zip and not ZIP_PATTERN.match(record.zip):
        return f"invalid ZIP '{record.zip}'"
    if record.state and len(record.state) != 2:
        return f"state should be a 2-letter code, got '{record.state}'"
    return None


def read_addresses(
    path: str | Path,
    *,
    id_col: str | None = None,
    street_col: str | None = None,
    city_col: str | None = None,
    state_col: str | None = None,
    zip_col: str | None = None,
    encoding: str = "utf-8-sig",
) -> ReadResult:
    """Read a CSV of addresses, map its columns, and validate each row.

    Rows without an id column get sequential ids. Duplicate ids are made
    unique, because the Census API joins results back to input by id.
    """
    overrides = {"id": id_col, "street": street_col, "city": city_col, "state": state_col, "zip": zip_col}
    result = ReadResult()

    with open(path, newline="", encoding=encoding) as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"{path} is empty or has no header row")
        result.fieldnames = list(reader.fieldnames)
        cols = _resolve_columns(result.fieldnames, overrides)
        result.columns = cols

        seen_ids: dict[str, int] = {}
        for row_number, row in enumerate(reader, start=1):
            raw_id = _clean(row.get(cols["id"])) if cols["id"] else ""
            record_id = raw_id or str(row_number)
            if record_id in seen_ids:
                seen_ids[record_id] += 1
                new_id = f"{record_id}_{seen_ids[record_id]}"
                log.warning("Duplicate id %s on row %d renamed to %s", record_id, row_number, new_id)
                record_id = new_id
            else:
                seen_ids[record_id] = 1

            zip_code = _clean(row.get(cols["zip"])) if cols["zip"] else ""
            if zip_code.isdigit() and len(zip_code) < 5:
                zip_code = zip_code.zfill(5)  # Excel drops leading zeros (e.g. 02108)

            record = AddressRecord(
                id=record_id,
                street=_clean(row.get(cols["street"])),
                city=_clean(row.get(cols["city"])) if cols["city"] else "",
                state=_clean(row.get(cols["state"])).upper() if cols["state"] else "",
                zip=zip_code,
                extra={k: (v or "") for k, v in row.items() if k is not None},
                row_number=row_number,
            )
            problem = validate(record)
            if problem:
                result.rejected.append((record, problem))
            else:
                result.records.append(record)

    log.info(
        "Read %d rows: %d valid, %d rejected",
        len(result.records) + len(result.rejected),
        len(result.records),
        len(result.rejected),
    )
    return result
