"""Test helpers: a fake Census batch service so tests never touch the network."""

from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest
import requests

FIXTURES = Path(__file__).parent / "fixtures"


class FakeResponse:
    def __init__(self, status_code: int = 200, text: str = "") -> None:
        self.status_code = status_code
        self.text = text


class FakeCensusSession:
    """Mimics the batch endpoint.

    Streets containing "Flaglr" don't match, "Main St" ties, everything else
    matches. Rows come back in reverse order, like the real API (which does
    not preserve input order). Pass `script` to inject failures first.
    """

    def __init__(self, script: list | None = None, geographies: bool = False) -> None:
        self.script = list(script or [])
        self.geographies = geographies
        self.calls: list[dict] = []

    def post(self, url, data=None, files=None, timeout=None):
        filename, payload, content_type = files["addressFile"]
        self.calls.append(
            {
                "url": url,
                "data": dict(data),
                "filename": filename,
                "content_type": content_type,
                "timeout": timeout,
                "payload": payload,
            }
        )
        if self.script:
            step = self.script.pop(0)
            if isinstance(step, Exception):
                raise step
            if isinstance(step, FakeResponse):
                return step
        return FakeResponse(200, self._respond(payload.decode("utf-8")))

    def _respond(self, body: str) -> str:
        out = io.StringIO()
        writer = csv.writer(out, quoting=csv.QUOTE_ALL)
        rows = list(csv.reader(io.StringIO(body)))
        for index, (rid, street, city, state, zip_code) in enumerate(reversed(rows)):
            one_line = f"{street}, {city}, {state}, {zip_code}"
            if "Flaglr" in street:
                writer.writerow([rid, one_line, "No_Match"])
            elif "Main St" in street:
                writer.writerow([rid, one_line, "Tie"])
            else:
                row = [
                    rid,
                    one_line,
                    "Match",
                    "Exact",
                    one_line.upper(),
                    f"{-80.19 - index * 0.001:.6f},{25.77 + index * 0.001:.6f}",
                    "1000" + rid,
                    "L",
                ]
                if self.geographies:
                    row += ["12", "086", "003700", "1001"]
                writer.writerow(row)
        return out.getvalue()


@pytest.fixture
def fake_session():
    return FakeCensusSession()


@pytest.fixture
def no_sleep():
    waits: list[float] = []
    return waits.append, waits


@pytest.fixture
def sample_csv(tmp_path: Path) -> Path:
    path = tmp_path / "addresses.csv"
    path.write_text(
        "permit_id,Site_Address,City,State,Zip,notes\n"
        "P-1,101 W Flagler St,Miami,fl,33130,library\n"
        "P-2,111 NW 1st St,,,33128,zip only\n"
        "P-3,101 W Flaglr St,Miami,FL,33130,typo\n"
        "P-4,Main Street,Miami,FL,33130,no number\n"
        "P-5,12 Main St,Springfield,MA,1103,leading zero lost\n",
        encoding="utf-8",
    )
    return path


__all__ = ["FakeResponse", "FakeCensusSession", "FIXTURES", "requests"]
