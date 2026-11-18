# Census Batch Geocoder

![CI](https://github.com/mpashapu/census-batch-geocoder/actions/workflows/ci.yml/badge.svg)

A Python command-line tool that geocodes CSV address files with the free
**U.S. Census Bureau Geocoder**. Give it a spreadsheet of addresses and it
returns:

- **CSV**: your original columns plus coordinates, match quality and
  (optionally) census tract and block IDs
- **GeoJSON**: matched points, ready for ArcGIS Pro, QGIS or a web map
- **Report**: a Markdown summary of match rates and a list of addresses to review

No API key or account needed.

## Why

Geocoding is a routine step in permitting, inspections, code enforcement and
public-health work, and commercial geocoders charge per address. The Census
batch service is free but awkward to use: it caps files at 10,000 rows and
5 MB, has no header row, returns results out of order, and fails on messy
input. This tool handles that so the output can go straight into analysis.

## Features

- **Automatic column detection** (`address`, `site_address`, `zip_code`,
  `permit_id`, ...) with overrides for anything else
- **Input validation before upload**: catches missing house numbers, bad ZIPs
  and full state names, and restores leading zeros Excel strips from ZIP codes
  (`2108` → `02108`)
- **Automatic batching** under both Census limits (10,000 records and 5 MB)
- **Retries with exponential backoff** for timeouts and 5xx errors; no retries
  on client errors that won't succeed anyway
- **Results joined back by ID**, so output rows match input order even though
  the API reorders them
- **Census geographies** (`--geographies`): state and county FIPS, tract and
  block, plus ready-made 11-digit tract and 15-digit block GEOIDs for joining
  to ACS/census data
- **One output row per input row**, including rows rejected locally, so
  nothing silently disappears
- **Tested without the network**: the suite runs against a fake Census service

## Install

Requires Python 3.10+.

```bash
git clone https://github.com/mpashapu/census-batch-geocoder.git
cd census-batch-geocoder
pip install .
```

## Usage

```bash
census-geocode examples/sample_addresses.csv
```

This writes `sample_addresses_geocoded.csv`, `sample_addresses_geocoded.geojson`
and `sample_addresses_geocoded_report.md` next to the input.

More options:

```bash
# Include census tract and block IDs
census-geocode permits.csv --geographies -o output/permits

# Columns with non-standard names
census-geocode data.csv --street-col "SITE ADDR" --zip-col POSTAL --id-col FOLIO

# Check the input without calling the API
census-geocode data.csv --dry-run

# All options
census-geocode --help
```

### Input

A CSV with a header row. A street column is required, plus either a ZIP code
or city and state. An ID column is optional (row numbers are used if
missing). Any other columns are carried through to the output.

```csv
id,name,address,city,state,zip
1,Miami-Dade Main Library,101 W Flagler St,Miami,FL,33130
2,Stephen P. Clark Government Center,111 NW 1st St,Miami,FL,33128
```

### Output columns

| Column | Description |
|---|---|
| `geo_status` | `Match`, `No_Match`, `Tie` (several candidates) or `Not_Submitted` (failed validation) |
| `geo_match_type` | `Exact` or `Non_Exact` |
| `geo_matched_address` | Address as standardized by the Census Bureau |
| `geo_longitude`, `geo_latitude` | WGS84 coordinates |
| `geo_tiger_line_id`, `geo_side` | TIGER/Line edge and side of street |
| `geo_state_fips`, `geo_county_fips`, `geo_tract`, `geo_block` | With `--geographies` |
| `geo_tract_geoid`, `geo_block_geoid` | Joinable GEOIDs (with `--geographies`) |
| `geo_note` | Why a row wasn't geocoded |

### Use as a library

```python
from censusgeo import CensusBatchClient, read_addresses

addresses = read_addresses("permits.csv")
client = CensusBatchClient(return_type="geographies")
results = client.geocode(addresses.records)

for result in results:
    if result.is_match:
        print(result.id, result.longitude, result.latitude, result.tract_geoid)
```

## How it works

```
CSV ──► read + validate ──► batches (≤10,000 rows, ≤5 MB)
                               │
                               ▼
                  POST /geocoder/{locations|geographies}/addressbatch
                  (retry 429/5xx/timeouts with backoff)
                               │
                               ▼
          parse response ──► join to input by ID ──► CSV + GeoJSON + report
```

## Development

```bash
pip install -e ".[dev]"
pytest              # 40 tests, no network access needed
ruff check . && ruff format --check .
```

## Notes and limits

- The Census Geocoder covers U.S. addresses (including Puerto Rico and island
  areas) and matches against TIGER address ranges. Coordinates are
  interpolated along the street segment, not rooftop points.
- The service is free and shared. The tool pauses between batches; please
  don't run many jobs in parallel.
- `Public_AR_Current` and `Current_Current` are the default benchmark and
  vintage. See the
  [Census Geocoder API documentation](https://geocoding.geo.census.gov/geocoder/Geocoding_Services_API.html)
  for others.

## License

[MIT](LICENSE) © 2026 Malla Reddy Pashapu
