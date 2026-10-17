import json
import time
import unittest
from unittest.mock import Mock, call, patch

from rpg_parser.adapters.fetchers.open5e import Open5eJsonFetcher
from rpg_parser.adapters.parsers.dnd5e_open5e import Dnd5eOpen5eSpellParser
from rpg_parser.adapters.scrapers.open5e import Dnd5eOpen5eSpellScraper
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


class JsonParser:
    def parse(self, document: RawDocument) -> dict:
        return json.loads(document.content)


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
                        expected_records = [
                            {"id": index, "name": f"Spell {index}"}
                            for index in range(len(network_flags))
                        ]
                        requests = [
                            FetchRequest(
                                location=f"https://example.test/{index}",
                                params=None if network else {"record": expected_records[index]},
                            )
                            for index, network in enumerate(network_flags)
                        ]
                        scraper = Mock()
                        scraper.discover.return_value = iter(requests)
                        session = Mock()

                        def get_response(url, **kwargs):
                            # Match by URL so worker scheduling cannot change the payload.
                            index = int(url.rsplit("/", 1)[-1])
                            return Mock(text=json.dumps(expected_records[index]))

                        session.get.side_effect = get_response
                        exporter = FakeExporter()
                        spec = ScrapePipelineSpec(
                            scraper=scraper,
                            fetcher=Open5eJsonFetcher(session=session),
                            parser=JsonParser(),
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
                        self.assertEqual(records, expected_records)
                        self.assertEqual(
                            exporter.calls,
                            [
                                (data, ExportTarget(request.location))
                                for data, request in zip(expected_records, requests, strict=True)
                            ],
                        )

    def test_legacy_fetcher_retains_network_pacing_in_both_modes(self):
        class LegacyFetcher:
            def fetch(self, request: FetchRequest) -> RawDocument:
                return RawDocument(content=request.location, source=request.location)

        for workers in (1, 3):
            for delay in (None, 0, 0.5):
                with self.subTest(workers=workers, delay=delay):
                    exporter = FakeExporter()
                    spec = ScrapePipelineSpec(
                        scraper=FakeScraper(),
                        fetcher=LegacyFetcher(),
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
                    self.assertEqual(
                        sleep.call_args_list,
                        [call(effective_delay)] if effective_delay else [],
                    )
                    self.assertEqual(records, [{"Name": "one"}, {"Name": "two"}])
                    self.assertEqual(exporter.calls, [
                        ({"Name": "one"}, ExportTarget("https://example.test/one")),
                        ({"Name": "two"}, ExportTarget("https://example.test/two")),
                    ])

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

    def test_open5e_scrape_pipeline_paces_only_between_pages_in_both_modes(self):
        pages = [
            {
                "next": "https://api.open5e.com/v2/spells/?page=2",
                "results": [
                    {"key": "srd-2024_acid-arrow", "name": "Acid Arrow", "level": 2},
                    {"key": "srd-2024_aid", "name": "Aid", "level": 2},
                ],
            },
            {
                "next": "https://api.open5e.com/v2/spells/?page=3",
                "results": [
                    {"key": "srd-2024_alarm", "name": "Alarm", "level": 1},
                    {"key": "srd-2024_alter-self", "name": "Alter Self", "level": 2},
                ],
            },
            {
                "next": None,
                "results": [
                    {"key": "srd-2024_animal-friendship", "name": "Animal Friendship", "level": 1},
                ],
            },
        ]

        results_by_mode = {}
        for workers in (1, 4):
            for page_delay in (0.25, 0):
                with self.subTest(workers=workers, page_delay=page_delay):
                    scraper_session = Mock()
                    scraper_session.get.side_effect = [
                        Mock(json=Mock(return_value=page), raise_for_status=Mock(return_value=None))
                        for page in pages
                    ]
                    fetcher_session = Mock()
                    exporter = FakeExporter()
                    spec = ScrapePipelineSpec(
                        scraper=Dnd5eOpen5eSpellScraper(
                            page_delay_seconds=page_delay,
                            session=scraper_session,
                        ),
                        fetcher=Open5eJsonFetcher(session=fetcher_session),
                        parser=Dnd5eOpen5eSpellParser(),
                        exporter=exporter,
                    )

                    # Use a large pipeline delay_seconds=5.0 to verify embedded records never
                    # trigger detail-fetch sleeps; only the scraper's inter-page delay runs.
                    with patch("rpg_parser.core.pipeline.time.sleep") as mock_sleep:
                        records = run_scrape_pipeline(
                            spec,
                            ScrapeRequest(),
                            delay_seconds=5.0,
                            max_workers=workers,
                        )

                    self.assertEqual(scraper_session.get.call_count, 3)
                    fetcher_session.get.assert_not_called()
                    expected_sleeps = [call(page_delay), call(page_delay)] if page_delay else []
                    self.assertEqual(mock_sleep.call_args_list, expected_sleeps)
                    self.assertEqual(
                        [record["key"] for record in records],
                        [
                            "srd-2024_acid-arrow",
                            "srd-2024_aid",
                            "srd-2024_alarm",
                            "srd-2024_alter-self",
                            "srd-2024_animal-friendship",
                        ],
                    )
                    results_by_mode[workers] = records

        self.assertEqual(results_by_mode[1], results_by_mode[4])


if __name__ == "__main__":
    unittest.main()
