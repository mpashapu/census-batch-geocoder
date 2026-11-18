import csv
import json

from conftest import FakeCensusSession

from censusgeo.cli import main
from censusgeo.client import CensusBatchClient
from censusgeo.models import AddressRecord, GeocodeResult, MatchStatus
from censusgeo.writers import build_report, summarize, to_geojson


def _results():
    return [
        GeocodeResult("1", "a", MatchStatus.MATCH, "Exact", "A", -80.1, 25.7),
        GeocodeResult("2", "b", MatchStatus.MATCH, "Non_Exact", "B", -80.2, 25.8),
        GeocodeResult("3", "c", MatchStatus.NO_MATCH),
        GeocodeResult("4", "d", MatchStatus.TIE),
        GeocodeResult("5", "e", MatchStatus.NOT_SUBMITTED, note="missing street"),
    ]


def test_summary_counts():
    s = summarize(_results())
    assert (s.total, s.matched, s.exact, s.non_exact, s.ties, s.no_match, s.not_submitted) == (5, 2, 1, 1, 1, 1, 1)
    assert s.match_rate == 0.4 and s.exact_rate == 0.5


def test_geojson_has_only_matches_in_lon_lat_order():
    recs = [AddressRecord(str(i), "x", extra={"name": f"n{i}"}) for i in range(1, 6)]
    fc = to_geojson(recs, _results())
    assert fc["type"] == "FeatureCollection"
    assert [f["id"] for f in fc["features"]] == ["1", "2"]
    assert fc["features"][0]["geometry"] == {"type": "Point", "coordinates": [-80.1, 25.7]}
    assert fc["features"][0]["properties"]["name"] == "n1"


def test_report_lists_items_needing_review():
    report = build_report(
        _results(), input_name="in.csv", benchmark="Public_AR_Current", return_type="locations", elapsed_seconds=1.2
    )
    assert "| Matched | 2 | 40.0% |" in report
    assert "## Needs review (4)" in report
    assert "missing street" in report


def test_cli_end_to_end(sample_csv, tmp_path, no_sleep):
    sleep, _ = no_sleep
    client = CensusBatchClient(session=FakeCensusSession(), sleep=sleep)
    prefix = tmp_path / "out" / "result"
    assert main([str(sample_csv), "-o", str(prefix)], client=client) == 0

    with open(prefix.with_suffix(".csv"), newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    # One output row per input row, original order and columns kept
    assert [r["permit_id"] for r in rows] == ["P-1", "P-2", "P-3", "P-4", "P-5"]
    assert rows[0]["notes"] == "library"
    assert [r["geo_status"] for r in rows] == ["Match", "Match", "No_Match", "Not_Submitted", "Tie"]
    assert rows[3]["geo_note"] == "street has no house number"
    assert rows[0]["geo_longitude"].startswith("-80.")

    geojson = json.loads(prefix.with_suffix(".geojson").read_text())
    assert len(geojson["features"]) == 2

    report = (prefix.parent / "result_report.md").read_text()
    assert "| **Total records** | **5** | |" in report


def test_cli_dry_run_makes_no_calls(sample_csv):
    session = FakeCensusSession()
    assert main([str(sample_csv), "--dry-run"], client=CensusBatchClient(session=session)) == 0
    assert session.calls == []


def test_cli_missing_file(tmp_path):
    assert main([str(tmp_path / "nope.csv")]) == 2


def test_cli_reports_api_failure(sample_csv, no_sleep):
    sleep, _ = no_sleep
    import requests

    session = FakeCensusSession(script=[requests.ConnectionError("down")] * 2)
    client = CensusBatchClient(session=session, sleep=sleep, max_retries=1)
    assert main([str(sample_csv)], client=client) == 1
