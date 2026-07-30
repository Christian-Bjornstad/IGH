"""IGH Merge - lokal sammenslåing og QC av IGHV-SHM-data."""

from .models import MergeResult, MergedRow, RunManifest
from .service import MergeService

__all__ = ["MergeResult", "MergedRow", "RunManifest", "MergeService"]
__version__ = "0.2.0"
