from __future__ import annotations
from .base import DataProvider, Provider
from .ingestible import IngestibleDataProvider
from .fetchable import FetchableDataProvider

__all__ = ["DataProvider", "Provider", "IngestibleDataProvider", "FetchableDataProvider"]
