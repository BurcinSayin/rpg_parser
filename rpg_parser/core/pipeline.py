import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from rpg_parser.core.ports import (
    ExportTarget,
    FetchRequest,
    PipelineSpec,
    ScrapePipelineSpec,
    ScrapeRequest,
)

SCRAPE_REQUEST_DELAY_SECONDS = 1.0


def run_pipeline(
    spec: PipelineSpec,
    request: FetchRequest,
    target: ExportTarget | None = None,
) -> dict[str, Any]:
    raw_document = spec.fetcher.fetch(request)
    data = spec.parser.parse(raw_document)

    if target is not None:
        spec.exporter.export(data, target)

    return data


def run_scrape_pipeline(
    spec: ScrapePipelineSpec,
    request: ScrapeRequest,
    target_factory: Callable[[dict[str, Any], int, FetchRequest], ExportTarget | None] | None = None,
    delay_seconds: float | None = None,
    max_workers: int = 1,
) -> list[dict[str, Any]]:
    if max_workers < 1:
        raise ValueError("max_workers must be at least 1")

    delay = SCRAPE_REQUEST_DELAY_SECONDS if delay_seconds is None else delay_seconds
    if delay < 0:
        raise ValueError("delay_seconds must be non-negative")

    network_fetch_seen = False

    def pace_fetch(fetch_request: FetchRequest) -> None:
        # Called by the submitting thread in both modes. Local records neither
        # incur a delay nor reset pacing between network-backed fetches.
        nonlocal network_fetch_seen
        if spec.fetcher.requires_network(fetch_request):
            if network_fetch_seen and delay:
                time.sleep(delay)
            network_fetch_seen = True

    def fetch_and_parse(fetch_request: FetchRequest) -> dict[str, Any]:
        raw_document = spec.fetcher.fetch(fetch_request)
        return spec.parser.parse(raw_document)

    def add_record(
        records: list[dict[str, Any]],
        index: int,
        fetch_request: FetchRequest,
        data: dict[str, Any],
    ) -> None:
        records.append(data)

        if target_factory is not None:
            target = target_factory(data, index, fetch_request)
            if target is not None:
                spec.exporter.export(data, target)

    if max_workers == 1:
        records = []
        for index, fetch_request in enumerate(spec.scraper.discover(request), start=1):
            pace_fetch(fetch_request)
            data = fetch_and_parse(fetch_request)
            add_record(records, index, fetch_request, data)
        return records

    indexed_records: list[tuple[int, FetchRequest, dict[str, Any]]] = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_request = {}
        for index, fetch_request in enumerate(spec.scraper.discover(request), start=1):
            pace_fetch(fetch_request)
            future = executor.submit(fetch_and_parse, fetch_request)
            future_to_request[future] = (index, fetch_request)

        for future in as_completed(future_to_request):
            index, fetch_request = future_to_request[future]
            indexed_records.append((index, fetch_request, future.result()))

    indexed_records.sort(key=lambda item: item[0])
    records = []

    for index, fetch_request, data in indexed_records:
        add_record(records, index, fetch_request, data)

    return records
