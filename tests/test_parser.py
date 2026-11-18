from conftest import FIXTURES

from censusgeo.models import MatchStatus
from censusgeo.parser import parse_batch_response


def test_parses_locations_response():
    results = {r.id: r for r in parse_batch_response((FIXTURES / "locations_response.csv").read_text())}
    assert set(results) == {"1", "2", "3", "4"}

    exact = results["2"]
    assert exact.status is MatchStatus.MATCH
    assert exact.match_type == "Exact"
    assert exact.matched_address == "111 NW 1ST ST, MIAMI, FL, 33128"
    assert (exact.longitude, exact.latitude) == (-80.19536, 25.77501)  # lon first
    assert exact.tiger_line_id == "123456789"
    assert exact.side == "L"
    assert exact.tract_geoid == ""  # locations return type has no geographies

    assert results["1"].match_type == "Non_Exact"
    assert results["3"].status is MatchStatus.NO_MATCH
    assert results["3"].longitude is None
    assert results["4"].status is MatchStatus.TIE


def test_parses_geographies_response_and_builds_geoids():
    results = {r.id: r for r in parse_batch_response((FIXTURES / "geographies_response.csv").read_text())}
    match = results["7"]
    assert (match.state_fips, match.county_fips, match.tract, match.block) == ("24", "033", "802405", "1084")
    assert match.tract_geoid == "24033802405"
    assert match.block_geoid == "240338024051084"
    assert results["8"].status is MatchStatus.NO_MATCH


def test_skips_blank_and_unrecognized_lines(caplog):
    text = '\n"1","x","Match","Exact","X","-80.1,25.7","1","L"\n\n"2","y","Garbage"\n'
    results = parse_batch_response(text)
    assert [r.id for r in results] == ["1"]
    assert "unrecognized" in caplog.text


def test_out_of_range_coordinates_are_flagged_not_trusted():
    # Latitude 95 is impossible; keep the match status but don't emit a bad point
    text = '"1","x","Match","Exact","X","-80.1,95.0","1","L"\n'
    (result,) = parse_batch_response(text)
    assert result.status is MatchStatus.MATCH
    assert result.longitude is None and result.latitude is None
    assert "coordinates" in result.note


def test_handles_commas_inside_quoted_addresses():
    text = (
        '"1","1 Main St, Apt 2, Miami, FL, 33130","Match","Exact","1 MAIN ST, MIAMI, FL, 33130","-80.2,25.7","9","R"\n'
    )
    (result,) = parse_batch_response(text)
    assert result.input_address == "1 Main St, Apt 2, Miami, FL, 33130"
    assert result.latitude == 25.7
