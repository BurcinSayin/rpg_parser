import time
import unittest
from unittest.mock import Mock, call, patch

from rpg_parser.adapters.fetchers.open5e import Open5eJsonFetcher
from rpg_parser.core.pipeline import run_scrape_pipeline
from rpg_parser.core.ports import (
    ExportTarget,
    FetchRequest,
    RawDocument,
    ScrapePipelineSpec,
    ScrapeRequest,
)


class FakeScraper:
    def discover(self, _request: ScrapeRequest):
        yield FetchRequest(location="https://example.test/one")
        yield FetchRequest(location="https://example.test/two")


class FakeFetcher:
    def requires_network(self, request: FetchRequest) -> bool:
        return True

    def fetch(self, request: FetchRequest) -> RawDocument:
        return RawDocument(content=request.location, source=request.location)


class FakeParser:
    def parse(self, document: RawDocument) -> dict:
        return {"Name": document.content.rsplit("/", 1)[-1]}


class FakeExporter:
    def __init__(self):
        self.calls = []

    def export(self, data: dict, target: ExportTarget) -> None:
        self.calls.append((data, target))


class TestScrapePipeline(unittest.TestCase):
    def test_pacing_depends_on_network_fetches_in_both_modes(self):
        # Includes leading/trailing local records and local records between GETs.
        for workers in (1, 3):
            for network_flags in ((), (False,), (True,), (False,) * 339,
                                  (True, True, True), (False, True, False, True, False)):
                for delay in (None, 0, 0.5):
                    with self.subTest(workers=workers, flags=network_flags, delay=delay):
                        requests = [
                            FetchRequest(
                                location=f"https://example.test/{index}",
                                params=None if network else {"record": {}},
                            )
                            for index, network in enumerate(network_flags)
                        ]
                        scraper = Mock()
                        scraper.discover.return_value = iter(requests)
                        session = Mock()
                        session.get.return_value.text = "{}"
                        exporter = FakeExporter()
                        spec = ScrapePipelineSpec(
                            scraper=scraper,
                            fetcher=Open5eJsonFetcher(session=session),
                            parser=FakeParser(),
                            exporter=exporter,
                        )
                        with patch("rpg_parser.core.pipeline.time.sleep") as sleep:
                            records = run_scrape_pipeline(
                                spec, ScrapeRequest(), delay_seconds=delay,
                                max_workers=workers,
                                target_factory=lambda data, index, request: ExportTarget(request.location),
                            )
                        effective_delay = 1.0 if delay is None else delay
                        expected_sleeps = max(sum(network_flags) - 1, 0) if effective_delay else 0
                        self.assertEqual(sleep.call_args_list, [call(effective_delay)] * expected_sleeps)
                        self.assertEqual(session.get.call_count, sum(network_flags))
                        self.assertEqual(len(records), len(requests))
                        self.assertEqual(
                            [target.location for _, target in exporter.calls],
                            [request.location for request in requests],
                        )

    def test_run_scrape_pipeline_discovers_fetches_parses_and_exports_many(self):
        exporter = FakeExporter()
        spec = ScrapePipelineSpec(
            scraper=FakeScraper(),
            fetcher=FakeFetcher(),
            parser=FakeParser(),
            exporter=exporter,
        )

        records = run_scrape_pipeline(
            spec,
            ScrapeRequest(limit=2),
            target_factory=lambda data, index, _request: ExportTarget(location=f"{index}-{data['Name']}.json"),
            delay_seconds=0,
        )

        self.assertEqual(records, [{"Name": "one"}, {"Name": "two"}])
        self.assertEqual(exporter.calls[0][1].location, "1-one.json")
        self.assertEqual(exporter.calls[1][1].location, "2-two.json")

    def test_run_scrape_pipeline_sleeps_between_records(self):
        spec = ScrapePipelineSpec(
            scraper=FakeScraper(),
            fetcher=FakeFetcher(),
            parser=FakeParser(),
            exporter=FakeExporter(),
        )

        with patch("rpg_parser.core.pipeline.time.sleep") as mock_sleep:
            run_scrape_pipeline(spec, ScrapeRequest(limit=2), delay_seconds=0.5)

        self.assertEqual(mock_sleep.call_count, 1)
        mock_sleep.assert_called_once_with(0.5)

    def test_run_scrape_pipeline_preserves_order_with_workers(self):
        class SlowFetcher(FakeFetcher):
            def fetch(self, request: FetchRequest) -> RawDocument:
                if request.location.endswith("one"):
                    time.sleep(0.01)
                return RawDocument(content=request.location, source=request.location)

        spec = ScrapePipelineSpec(
            scraper=FakeScraper(),
            fetcher=SlowFetcher(),
            parser=FakeParser(),
            exporter=FakeExporter(),
        )

        records = run_scrape_pipeline(
            spec,
            ScrapeRequest(limit=2),
            delay_seconds=0,
            max_workers=2,
        )

        self.assertEqual(records, [{"Name": "one"}, {"Name": "two"}])


if __name__ == "__main__":
    unittest.main()
