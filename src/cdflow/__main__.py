"""Allow ``python -m cdflow``."""

from __future__ import annotations

from .cli import main

raise SystemExit(main())
