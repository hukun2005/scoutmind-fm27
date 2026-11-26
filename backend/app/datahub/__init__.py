"""V3.3.0 Automatic Data Import Engine.

Public surface: :class:`AutomaticDataImportEngine`, :func:`detect_payload`, :func:`detect_game`.
"""

from .detection import Detection, DetectionError, detect_payload
from .engine import AutomaticDataImportEngine, EngineReport, run_dry_scan

__all__ = [
    "AutomaticDataImportEngine",
    "Detection",
    "DetectionError",
    "EngineReport",
    "detect_payload",
    "run_dry_scan",
]
