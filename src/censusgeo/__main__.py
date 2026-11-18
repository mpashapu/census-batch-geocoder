"""Allow `python -m censusgeo`."""

import sys

from .cli import main

sys.exit(main())
