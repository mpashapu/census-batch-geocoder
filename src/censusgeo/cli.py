"""Command-line interface: census-geocode input.csv -o output"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from . import __version__
from .client import MAX_RECORDS_PER_BATCH, CensusBatchClient, CensusGeocoderError
from .models import GeocodeResult, MatchStatus
from .reader import read_addresses
from .writers import build_report, summarize, write_csv, write_geojson

log = logging.getLogger("censusgeo")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="census-geocode",
        description="Batch geocode a CSV of U.S. addresses with the free U.S. Census Geocoder.",
    )
    parser.add_argument("input", type=Path, help="CSV with a header row (street, city, state, zip)")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output path prefix (default: <input>_geocoded). Writes .csv, .geojson and _report.md",
    )
    parser.add_argument("--geographies", action="store_true", help="Also return state/county FIPS, tract and block")
    parser.add_argument("--benchmark", default="Public_AR_Current", help="Census benchmark (default: %(default)s)")
    parser.add_argument(
        "--vintage", default="Current_Current", help="Census vintage for --geographies (default: %(default)s)"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=MAX_RECORDS_PER_BATCH,
        help=f"Records per request, max {MAX_RECORDS_PER_BATCH} (default: %(default)s)",
    )
    parser.add_argument("--timeout", type=float, default=600, help="Seconds per request (default: %(default)s)")
    parser.add_argument("--retries", type=int, default=3, help="Retries per batch (default: %(default)s)")
    parser.add_argument("--no-geojson", action="store_true", help="Skip the GeoJSON output")
    parser.add_argument("--dry-run", action="store_true", help="Validate the input and stop before calling the API")

    columns = parser.add_argument_group("column mapping (detected automatically when omitted)")
    for role in ("id", "street", "city", "state", "zip"):
        columns.add_argument(f"--{role}-col", metavar="NAME", help=f"Column holding the {role}")

    parser.add_argument("-v", "--verbose", action="store_true", help="Show debug logging")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: list[str] | None = None, client: CensusBatchClient | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    if not args.input.is_file():
        log.error("Input file not found: %s", args.input)
        return 2

    try:
        read = read_addresses(
            args.input,
            id_col=args.id_col,
            street_col=args.street_col,
            city_col=args.city_col,
            state_col=args.state_col,
            zip_col=args.zip_col,
        )
    except (ValueError, UnicodeDecodeError) as error:
        log.error("Could not read %s: %s", args.input, error)
        return 2

    mapped = ", ".join(f"{role}={col or '-'}" for role, col in read.columns.items())
    log.info("Columns: %s", mapped)
    for record, reason in read.rejected[:10]:
        log.warning("Row %s skipped: %s", record.id, reason)
    if len(read.rejected) > 10:
        log.warning("...and %d more skipped rows (listed in the report)", len(read.rejected) - 10)

    if args.dry_run:
        log.info("Dry run: %d valid, %d rejected. No API calls made.", len(read.records), len(read.rejected))
        return 0
    if not read.records and not read.rejected:
        log.error("No rows found in %s", args.input)
        return 2

    client = client or CensusBatchClient(
        return_type="geographies" if args.geographies else "locations",
        benchmark=args.benchmark,
        vintage=args.vintage,
        timeout=args.timeout,
        max_retries=args.retries,
    )

    started = time.monotonic()
    try:
        geocoded = client.geocode(
            read.records,
            batch_size=args.batch_size,
            on_batch=lambda n, total, done: log.info("Batch %d/%d done (%d records)", n, total, done),
        )
    except (CensusGeocoderError, ValueError) as error:
        log.error("%s", error)
        return 1
    elapsed = time.monotonic() - started

    # Put rejected rows back so the output has one row per input row
    rejected_results = [
        GeocodeResult(id=r.id, input_address=r.one_line, status=MatchStatus.NOT_SUBMITTED, note=reason)
        for r, reason in read.rejected
    ]
    paired = sorted(
        zip(list(read.records) + [r for r, _ in read.rejected], geocoded + rejected_results, strict=True),
        key=lambda pair: pair[0].row_number,
    )
    all_records = [record for record, _ in paired]
    all_results = [result for _, result in paired]

    prefix = args.output or args.input.with_name(f"{args.input.stem}_geocoded")
    prefix.parent.mkdir(parents=True, exist_ok=True)
    csv_path = prefix.with_suffix(".csv")
    write_csv(csv_path, all_records, all_results, read.fieldnames)
    log.info("Wrote %s", csv_path)

    if not args.no_geojson:
        geojson_path = prefix.with_suffix(".geojson")
        count = write_geojson(geojson_path, all_records, all_results)
        log.info("Wrote %s (%d points)", geojson_path, count)

    report_path = prefix.with_name(f"{prefix.name}_report.md")
    report_path.write_text(
        build_report(
            all_results,
            input_name=args.input.name,
            benchmark=args.benchmark,
            return_type=client.return_type,
            elapsed_seconds=elapsed,
        ),
        encoding="utf-8",
    )
    log.info("Wrote %s", report_path)

    s = summarize(all_results)
    log.info(
        "Matched %d of %d (%.1f%%); %d exact, %d need review",
        s.matched,
        s.total,
        s.match_rate * 100,
        s.exact,
        s.total - s.exact,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
