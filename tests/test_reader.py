import pytest

from censusgeo.models import AddressRecord
from censusgeo.reader import read_addresses, validate


def test_detects_columns_and_normalizes(sample_csv):
    result = read_addresses(sample_csv)
    assert result.columns == {
        "id": "permit_id",
        "street": "Site_Address",
        "city": "City",
        "state": "State",
        "zip": "Zip",
    }
    first = result.records[0]
    assert first.id == "P-1"
    assert first.state == "FL"  # upper-cased
    assert first.extra["notes"] == "library"
    assert first.row_number == 1


def test_restores_leading_zero_in_zip(sample_csv):
    records = {r.id: r for r in read_addresses(sample_csv).records}
    assert records["P-5"].zip == "01103"


def test_rejects_rows_that_cannot_geocode(sample_csv):
    rejected = {r.id: reason for r, reason in read_addresses(sample_csv).rejected}
    assert rejected == {"P-4": "street has no house number"}


def test_zip_only_rows_are_allowed(sample_csv):
    ids = [r.id for r in read_addresses(sample_csv).records]
    assert "P-2" in ids


def test_generates_ids_and_dedupes(tmp_path):
    path = tmp_path / "in.csv"
    path.write_text("id,street,zip\nA,1 Main St,33130\nA,2 Main St,33130\n,3 Main St,33130\n")
    ids = [r.id for r in read_addresses(path).records]
    assert ids == ["A", "A_2", "3"]


def test_column_override_and_bad_override(tmp_path):
    path = tmp_path / "in.csv"
    path.write_text("loc,postal\n10 Ocean Dr,33139\n")
    result = read_addresses(path, street_col="loc", zip_col="postal")
    assert result.records[0].street == "10 Ocean Dr"
    with pytest.raises(ValueError, match="not found"):
        read_addresses(path, street_col="nope")


def test_missing_street_column_has_helpful_error(tmp_path):
    path = tmp_path / "in.csv"
    path.write_text("foo,bar\n1,2\n")
    with pytest.raises(ValueError, match="--street-col"):
        read_addresses(path)


def test_handles_excel_utf8_bom(tmp_path):
    path = tmp_path / "in.csv"
    path.write_bytes("﻿street,zip\n5 Elm St,33101\n".encode())
    assert read_addresses(path).records[0].street == "5 Elm St"


@pytest.mark.parametrize(
    "record, reason",
    [
        (AddressRecord("1", ""), "missing street"),
        (AddressRecord("1", "1 Main St"), "needs ZIP or city + state"),
        (AddressRecord("1", "1 Main St", zip="3313"), "invalid ZIP '3313'"),
        (
            AddressRecord("1", "1 Main St", city="Miami", state="Florida"),
            "state should be a 2-letter code, got 'Florida'",
        ),
        (AddressRecord("1", "1 Main St", city="Miami", state="FL"), None),
        (AddressRecord("1", "1 Main St", zip="33130-1234"), None),
    ],
)
def test_validate(record, reason):
    assert validate(record) == reason
