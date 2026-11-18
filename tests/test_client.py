import pytest
import requests
from conftest import FakeCensusSession, FakeResponse

from censusgeo.client import CensusBatchClient, CensusGeocoderError, make_batches, to_batch_csv
from censusgeo.models import AddressRecord, MatchStatus


def records(n, street="1 Main Ave"):
    return [AddressRecord(str(i), street, "Miami", "FL", "33130") for i in range(1, n + 1)]


def test_batch_csv_format():
    payload = to_batch_csv([AddressRecord("7", "1 Main St, Apt 2", "Miami", "FL", "33130")])
    assert payload == b'7,"1 Main St, Apt 2",Miami,FL,33130\n'


def test_make_batches_respects_record_limit():
    sizes = [len(b) for b in make_batches(records(25), max_records=10)]
    assert sizes == [10, 10, 5]


def test_make_batches_respects_byte_limit():
    one_row = len(to_batch_csv(records(1)))
    sizes = [len(b) for b in make_batches(records(10), max_records=100, max_bytes=one_row * 4)]
    assert sizes == [4, 4, 2]


def test_make_batches_rejects_invalid_size():
    with pytest.raises(ValueError):
        list(make_batches(records(1), max_records=10_001))


def test_posts_expected_form_for_locations(fake_session, no_sleep):
    sleep, _ = no_sleep
    client = CensusBatchClient(session=fake_session, sleep=sleep, timeout=30)
    client.geocode_batch(records(2))
    call = fake_session.calls[0]
    assert call["url"] == "https://geocoding.geo.census.gov/geocoder/locations/addressbatch"
    assert call["data"] == {"benchmark": "Public_AR_Current"}  # no vintage for locations
    assert call["filename"] == "addresses.csv"
    assert call["timeout"] == 30


def test_geographies_sends_vintage_and_returns_fips(no_sleep):
    sleep, _ = no_sleep
    session = FakeCensusSession(geographies=True)
    client = CensusBatchClient(return_type="geographies", session=session, sleep=sleep)
    (result,) = client.geocode_batch(records(1))
    assert session.calls[0]["url"].endswith("/geographies/addressbatch")
    assert session.calls[0]["data"] == {"benchmark": "Public_AR_Current", "vintage": "Current_Current"}
    assert result.tract_geoid == "12086003700"


def test_results_come_back_in_input_order_even_if_api_reorders(fake_session, no_sleep):
    sleep, _ = no_sleep
    results = CensusBatchClient(session=fake_session, sleep=sleep).geocode_batch(records(5))
    assert [r.id for r in results] == ["1", "2", "3", "4", "5"]


def test_maps_no_match_and_tie(fake_session, no_sleep):
    sleep, _ = no_sleep
    batch = [AddressRecord("a", "101 W Flaglr St", zip="33130"), AddressRecord("b", "1 Main St", zip="33130")]
    results = CensusBatchClient(session=fake_session, sleep=sleep).geocode_batch(batch)
    assert [r.status for r in results] == [MatchStatus.NO_MATCH, MatchStatus.TIE]


def test_retries_transient_errors_with_backoff(no_sleep):
    sleep, waits = no_sleep
    session = FakeCensusSession(script=[FakeResponse(503), requests.Timeout("slow")])
    client = CensusBatchClient(session=session, sleep=sleep, backoff_seconds=2, max_retries=3)
    results = client.geocode_batch(records(1))
    assert results[0].is_match
    assert waits == [2, 4]  # exponential backoff
    assert len(session.calls) == 3


def test_gives_up_after_max_retries(no_sleep):
    sleep, _ = no_sleep
    session = FakeCensusSession(script=[requests.ConnectionError("down")] * 3)
    client = CensusBatchClient(session=session, sleep=sleep, max_retries=2)
    with pytest.raises(CensusGeocoderError, match="after 3 attempts"):
        client.geocode_batch(records(1))


def test_client_errors_are_not_retried(no_sleep):
    sleep, waits = no_sleep
    session = FakeCensusSession(script=[FakeResponse(400, "bad benchmark")])
    with pytest.raises(CensusGeocoderError, match="HTTP 400"):
        CensusBatchClient(session=session, sleep=sleep).geocode_batch(records(1))
    assert waits == [] and len(session.calls) == 1


def test_missing_rows_become_no_match(no_sleep):
    sleep, _ = no_sleep
    session = FakeCensusSession(script=[FakeResponse(200, '"1","x","Match","Exact","X","-80.1,25.7","1","L"\n')])
    results = CensusBatchClient(session=session, sleep=sleep).geocode_batch(records(2))
    assert results[1].status is MatchStatus.NO_MATCH
    assert "no row returned" in results[1].note


def test_geocode_splits_batches_and_pauses_between(fake_session, no_sleep):
    sleep, waits = no_sleep
    progress = []
    client = CensusBatchClient(session=fake_session, sleep=sleep, pause_seconds=1)
    results = client.geocode(records(7), batch_size=3, on_batch=lambda *a: progress.append(a))
    assert len(results) == 7 and len(fake_session.calls) == 3
    assert waits == [1, 1]
    assert progress == [(1, 3, 3), (2, 3, 6), (3, 3, 7)]


def test_invalid_return_type():
    with pytest.raises(ValueError):
        CensusBatchClient(return_type="parcels")
