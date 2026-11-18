"""HTTP client for the Census Geocoder batch endpoint."""

from __future__ import annotations

import csv
import io
import logging
import time
from collections.abc import Callable, Iterable, Iterator, Sequence

import requests

from .models import AddressRecord, GeocodeResult, MatchStatus
from .parser import parse_batch_response

log = logging.getLogger(__name__)

BASE_URL = "https://geocoding.geo.census.gov/geocoder"
MAX_RECORDS_PER_BATCH = 10_000  # Census limit
MAX_BYTES_PER_BATCH = 5 * 1024 * 1024  # Census limit (5 MB)
RETRY_STATUS = {429, 500, 502, 503, 504}


class CensusGeocoderError(RuntimeError):
    """Raised when a batch can't be geocoded after retries."""


def to_batch_csv(records: Sequence[AddressRecord]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    for record in records:
        writer.writerow(record.as_batch_row())
    return buffer.getvalue().encode("utf-8")


def make_batches(
    records: Iterable[AddressRecord],
    max_records: int = MAX_RECORDS_PER_BATCH,
    max_bytes: int = MAX_BYTES_PER_BATCH,
) -> Iterator[list[AddressRecord]]:
    """Split records into batches that respect both the record and size limits."""
    if not 1 <= max_records <= MAX_RECORDS_PER_BATCH:
        raise ValueError(f"max_records must be between 1 and {MAX_RECORDS_PER_BATCH}")

    batch: list[AddressRecord] = []
    batch_bytes = 0
    for record in records:
        row_bytes = len(to_batch_csv([record]))
        if batch and (len(batch) >= max_records or batch_bytes + row_bytes > max_bytes):
            yield batch
            batch, batch_bytes = [], 0
        batch.append(record)
        batch_bytes += row_bytes
    if batch:
        yield batch


class CensusBatchClient:
    """Geocode addresses with the Census batch API.

    return_type="locations" gives coordinates; "geographies" also returns
    state/county FIPS, tract and block (requires a vintage).
    """

    def __init__(
        self,
        *,
        return_type: str = "locations",
        benchmark: str = "Public_AR_Current",
        vintage: str = "Current_Current",
        timeout: float = 600,
        max_retries: int = 3,
        backoff_seconds: float = 5,
        pause_seconds: float = 1,
        session: requests.Session | None = None,
        base_url: str = BASE_URL,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if return_type not in {"locations", "geographies"}:
            raise ValueError("return_type must be 'locations' or 'geographies'")
        self.return_type = return_type
        self.benchmark = benchmark
        self.vintage = vintage
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self.pause_seconds = pause_seconds
        self.session = session or requests.Session()
        self.base_url = base_url.rstrip("/")
        self._sleep = sleep

    @property
    def url(self) -> str:
        return f"{self.base_url}/{self.return_type}/addressbatch"

    def _form_data(self) -> dict[str, str]:
        data = {"benchmark": self.benchmark}
        if self.return_type == "geographies":
            data["vintage"] = self.vintage
        return data

    def geocode_batch(self, records: Sequence[AddressRecord]) -> list[GeocodeResult]:
        """Send one batch (at most 10,000 records) and return results in input order."""
        if not records:
            return []
        if len(records) > MAX_RECORDS_PER_BATCH:
            raise ValueError(f"A batch can hold at most {MAX_RECORDS_PER_BATCH} records")

        payload = to_batch_csv(records)
        last_error: Exception | None = None

        for attempt in range(1, self.max_retries + 2):
            try:
                response = self.session.post(
                    self.url,
                    data=self._form_data(),
                    files={"addressFile": ("addresses.csv", payload, "text/csv")},
                    timeout=self.timeout,
                )
                if response.status_code in RETRY_STATUS:
                    raise requests.HTTPError(f"HTTP {response.status_code}", response=response)
                if response.status_code >= 400:
                    # Client errors won't succeed on retry
                    raise CensusGeocoderError(f"Census API returned HTTP {response.status_code}: {response.text[:300]}")
                return self._align(records, parse_batch_response(response.text))
            except CensusGeocoderError:
                raise
            except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as error:
                last_error = error
                if attempt > self.max_retries:
                    break
                wait = self.backoff_seconds * 2 ** (attempt - 1)
                log.warning("Batch attempt %d failed (%s); retrying in %.0fs", attempt, error, wait)
                self._sleep(wait)

        raise CensusGeocoderError(f"Batch failed after {self.max_retries + 1} attempts: {last_error}")

    @staticmethod
    def _align(records: Sequence[AddressRecord], parsed: list[GeocodeResult]) -> list[GeocodeResult]:
        """Return one result per input record, in input order."""
        by_id = {result.id: result for result in parsed}
        aligned = []
        for record in records:
            result = by_id.get(record.id)
            if result is None:
                result = GeocodeResult(
                    id=record.id,
                    input_address=record.one_line,
                    status=MatchStatus.NO_MATCH,
                    note="no row returned by the API",
                )
            aligned.append(result)
        return aligned

    def geocode(
        self,
        records: Sequence[AddressRecord],
        *,
        batch_size: int = MAX_RECORDS_PER_BATCH,
        on_batch: Callable[[int, int, int], None] | None = None,
    ) -> list[GeocodeResult]:
        """Geocode any number of records, splitting into batches as needed.

        on_batch(batch_number, batch_count, records_done) is called after each batch.
        """
        batches = list(make_batches(records, max_records=batch_size))
        results: list[GeocodeResult] = []
        for number, batch in enumerate(batches, start=1):
            if number > 1 and self.pause_seconds:
                self._sleep(self.pause_seconds)  # be polite to a free public service
            log.info("Geocoding batch %d of %d (%d records)", number, len(batches), len(batch))
            results.extend(self.geocode_batch(batch))
            if on_batch:
                on_batch(number, len(batches), len(results))
        return results
