from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class FetchRequest:
    """Input needed by a fetcher adapter."""

    location: str
    params: dict[str, Any] | None = None


@dataclass(frozen=True)
class RawDocument:
    """Raw data returned by a fetcher before parsing."""

    content: str
    source: str
    media_type: str = "text/html"


@dataclass(frozen=True)
class ExportTarget:
    """Destination for an exporter adapter."""

    location: str


@dataclass(frozen=True)
class ScrapeRequest:
    """Input needed by a scraper adapter to discover fetchable records."""

    location: str | None = None
    filters: dict[str, Any] | None = None
    limit: int | None = None


class Fetcher(Protocol):
    def requires_network(self, request: FetchRequest) -> bool:
        """Declare whether fetching this request needs network access, without I/O."""

    def fetch(self, request: FetchRequest) -> RawDocument:
        """Fetch raw content from an external source."""


class Parser(Protocol):
    def parse(self, document: RawDocument) -> dict[str, Any]:
        """Parse raw content into structured data."""


class Exporter(Protocol):
    def export(self, data: Any, target: ExportTarget) -> None:
        """Export structured data to a target destination."""


class Scraper(Protocol):
    def discover(self, request: ScrapeRequest) -> Iterable[FetchRequest]:
        """Discover fetch requests for a bulk scrape."""


@dataclass(frozen=True)
class PipelineSpec:
    fetcher: Fetcher
    parser: Parser
    exporter: Exporter


@dataclass(frozen=True)
class ScrapePipelineSpec:
    scraper: Scraper
    fetcher: Fetcher
    parser: Parser
    exporter: Exporter
