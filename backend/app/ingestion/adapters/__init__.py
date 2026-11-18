"""Adapter package: every external data source has exactly one translator here.

The product rule is that ScoutMind's business code never depends on a third-party reader's internal format. Each
adapter reads one external artifact and returns a payload in the ScoutMind scan protocol plus a report describing
which fields were mapped, which were absent and which were ignored. The importer then validates and stores that
payload like any other scan.
"""

from __future__ import annotations

from .fmscout import ADAPTER_NAME, AdapterReport, convert_dump, detect

__all__ = ["ADAPTER_NAME", "AdapterReport", "convert_dump", "detect"]
