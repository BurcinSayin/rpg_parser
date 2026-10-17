import io
import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import requests
from urllib3.response import HTTPResponse

from rpg_parser.adapters.fetchers.open5e import OPEN5E_USER_AGENT
from rpg_parser.adapters.scrapers.open5e import (
    OPEN5E_PAGE_DELAY_SECONDS,
    Dnd5eOpen5eSpellScraper,
)
from rpg_parser.core.ports import ScrapeRequest


def _response(payload: dict) -> MagicMock:
    response = MagicMock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


def _urllib3_response(
    status: int,
    payload: dict | None = None,
    headers: dict[str, str] | None = None,
) -> HTTPResponse:
    body = json.dumps(payload or {}).encode("utf-8")
    return HTTPResponse(
        body=io.BytesIO(body),
        headers=headers or {"Content-Type": "application/json"},
        status=status,
        preload_content=False,
    )


class TestDnd5eOpen5eSpellScraper(unittest.TestCase):
    def setUp(self):
        samples_dir = Path(__file__).parent.parent / "samples"
        with open(samples_dir / "sample_dnd5e_open5e_list.json", "r", encoding="utf-8") as f:
            self.list_payload = json.load(f)  # 3 results, next=None

    def test_discover_yields_requests_with_embedded_records(self):
        session = MagicMock()
        session.get.return_value = _response(self.list_payload)

        with patch("rpg_parser.adapters.scrapers.open5e.time.sleep") as mock_sleep:
            scraper = Dnd5eOpen5eSpellScraper(session=session)
            results = list(scraper.discover(ScrapeRequest()))

        self.assertEqual(len(results), 3)
        self.assertEqual(
            results[0].location,
            "https://api.open5e.com/v2/spells/srd-2024_acid-arrow/",
        )
        # Each request embeds the full spell record so the fetcher skips a detail GET.
        self.assertEqual(results[0].params["record"]["name"], "Acid Arrow")
        self.assertEqual(results[0].params["record"]["key"], "srd-2024_acid-arrow")

        # The default discovery URL filters to the 2024 SRD.
        session.get.assert_called_once_with(
            "https://api.open5e.com/v2/spells/?document__key=srd-2024&limit=50",
            headers={"User-Agent": OPEN5E_USER_AGENT, "Accept": "application/json"},
            timeout=30.0,
        )
        # A one-page scrape makes no pagination sleeps.
        mock_sleep.assert_not_called()

    def test_three_page_scrape_sleeps_twice_between_pages(self):
        pages = [
            {
                "next": "https://api.open5e.com/v2/spells/?page=2",
                "results": [{"key": "srd-2024_a", "name": "A"}],
            },
            {
                "next": "https://api.open5e.com/v2/spells/?page=3",
                "results": [{"key": "srd-2024_b", "name": "B"}],
            },
            {
                "next": None,
                "results": [{"key": "srd-2024_c", "name": "C"}],
            },
        ]

        for configured_delay, filter_delay, expected_delay in (
            (None, None, OPEN5E_PAGE_DELAY_SECONDS),
            (0.25, None, 0.25),
            (1.0, 0.4, 0.4),
        ):
            with self.subTest(configured_delay=configured_delay, filter_delay=filter_delay):
                session = MagicMock()
                session.get.side_effect = [_response(page) for page in pages]
                scraper = Dnd5eOpen5eSpellScraper(
                    page_delay_seconds=configured_delay,
                    session=session,
                )
                filters = (
                    {"page_delay_seconds": filter_delay}
                    if filter_delay is not None
                    else None
                )

                with patch("rpg_parser.adapters.scrapers.open5e.time.sleep") as mock_sleep:
                    results = list(scraper.discover(ScrapeRequest(filters=filters)))

                self.assertEqual(session.get.call_count, 3)
                self.assertEqual(
                    mock_sleep.call_args_list,
                    [call(expected_delay), call(expected_delay)],
                )
                self.assertEqual(
                    [r.params["record"]["key"] for r in results],
                    ["srd-2024_a", "srd-2024_b", "srd-2024_c"],
                )

    def test_339_spells_at_50_per_page_requires_six_inter_page_pauses(self):
        pages = []
        total_spells = 339
        page_size = 50
        page_count = (total_spells + page_size - 1) // page_size  # 7 pages
        for page_index in range(page_count):
            start = page_index * page_size
            end = min(start + page_size, total_spells)
            next_url = (
                f"https://api.open5e.com/v2/spells/?page={page_index + 2}"
                if page_index + 1 < page_count
                else None
            )
            pages.append(
                {
                    "next": next_url,
                    "results": [
                        {"key": f"srd-2024_spell-{i}", "name": f"Spell {i}"}
                        for i in range(start, end)
                    ],
                }
            )

        session = MagicMock()
        session.get.side_effect = [_response(page) for page in pages]
        scraper = Dnd5eOpen5eSpellScraper(session=session)

        with patch("rpg_parser.adapters.scrapers.open5e.time.sleep") as mock_sleep:
            results = list(scraper.discover(ScrapeRequest()))

        self.assertEqual(len(results), 339)
        self.assertEqual(session.get.call_count, 7)
        self.assertEqual(
            mock_sleep.call_args_list,
            [call(OPEN5E_PAGE_DELAY_SECONDS)] * 6,
        )

    def test_zero_page_delay_disables_pagination_sleeps(self):
        pages = [
            {
                "next": "https://api.open5e.com/v2/spells/?page=2",
                "results": [{"key": "srd-2024_a", "name": "A"}],
            },
            {
                "next": "https://api.open5e.com/v2/spells/?page=3",
                "results": [{"key": "srd-2024_b", "name": "B"}],
            },
            {
                "next": None,
                "results": [{"key": "srd-2024_c", "name": "C"}],
            },
        ]

        for kwargs, filters in (
            ({"page_delay_seconds": 0}, None),
            ({}, {"page_delay_seconds": 0}),
        ):
            with self.subTest(kwargs=kwargs, filters=filters):
                session = MagicMock()
                session.get.side_effect = [_response(page) for page in pages]
                scraper = Dnd5eOpen5eSpellScraper(session=session, **kwargs)

                with patch("rpg_parser.adapters.scrapers.open5e.time.sleep") as mock_sleep:
                    results = list(scraper.discover(ScrapeRequest(filters=filters)))

                self.assertEqual(len(results), 3)
                self.assertEqual(session.get.call_count, 3)
                mock_sleep.assert_not_called()

    def test_negative_page_delay_raises_value_error(self):
        with self.assertRaises(ValueError):
            Dnd5eOpen5eSpellScraper(page_delay_seconds=-0.1)

        scraper = Dnd5eOpen5eSpellScraper(session=MagicMock())
        with self.assertRaises(ValueError):
            list(scraper.discover(ScrapeRequest(filters={"page_delay_seconds": -1})))

    def test_reaching_limit_does_not_fetch_or_wait_for_another_page(self):
        page1 = {
            "next": "https://api.open5e.com/v2/spells/?page=2",
            "results": [
                {"key": "srd-2024_a", "name": "A"},
                {"key": "srd-2024_b", "name": "B"},
            ],
        }
        page2 = {
            "next": "https://api.open5e.com/v2/spells/?page=3",
            "results": [
                {"key": "srd-2024_c", "name": "C"},
                {"key": "srd-2024_d", "name": "D"},
            ],
        }
        page3 = {
            "next": None,
            "results": [{"key": "srd-2024_e", "name": "E"}],
        }

        # Limit reached at the end of page 1: neither waits for nor fetches page 2.
        session = MagicMock()
        session.get.side_effect = [_response(page1), _response(page2), _response(page3)]
        scraper = Dnd5eOpen5eSpellScraper(page_delay_seconds=0.5, session=session)
        with patch("rpg_parser.adapters.scrapers.open5e.time.sleep") as mock_sleep:
            results = list(scraper.discover(ScrapeRequest(limit=2)))

        self.assertEqual([r.params["record"]["key"] for r in results], ["srd-2024_a", "srd-2024_b"])
        self.assertEqual(session.get.call_count, 1)
        mock_sleep.assert_not_called()

        # Limit reached mid-page 2: sleeps once before page 2, never waits for or fetches page 3.
        session = MagicMock()
        session.get.side_effect = [_response(page1), _response(page2), _response(page3)]
        scraper = Dnd5eOpen5eSpellScraper(page_delay_seconds=0.5, session=session)
        with patch("rpg_parser.adapters.scrapers.open5e.time.sleep") as mock_sleep:
            results = list(scraper.discover(ScrapeRequest(limit=3)))

        self.assertEqual(
            [r.params["record"]["key"] for r in results],
            ["srd-2024_a", "srd-2024_b", "srd-2024_c"],
        )
        self.assertEqual(session.get.call_count, 2)
        self.assertEqual(mock_sleep.call_args_list, [call(0.5)])

        # Zero limit: neither fetches page 1 nor sleeps.
        session = MagicMock()
        scraper = Dnd5eOpen5eSpellScraper(page_delay_seconds=0.5, session=session)
        with patch("rpg_parser.adapters.scrapers.open5e.time.sleep") as mock_sleep:
            results = list(scraper.discover(ScrapeRequest(limit=0)))

        self.assertEqual(results, [])
        session.get.assert_not_called()
        mock_sleep.assert_not_called()

    def test_discover_dedupes_by_key(self):
        payload = {
            "next": None,
            "results": [
                {"key": "srd-2024_a", "name": "A"},
                {"key": "srd-2024_a", "name": "A again"},
                {"name": "Missing key"},
                {"key": "srd-2024_b", "name": "B"},
            ],
        }
        session = MagicMock()
        session.get.return_value = _response(payload)

        scraper = Dnd5eOpen5eSpellScraper(page_delay_seconds=0, session=session)
        results = list(scraper.discover(ScrapeRequest()))

        self.assertEqual(len(results), 2)
        self.assertEqual([r.params["record"]["name"] for r in results], ["A", "B"])

    def test_document_key_override_via_filters(self):
        session = MagicMock()
        session.get.return_value = _response({"next": None, "results": []})

        scraper = Dnd5eOpen5eSpellScraper(page_delay_seconds=0, session=session)
        list(scraper.discover(ScrapeRequest(filters={"document_key": "srd-2014"})))

        called_url = session.get.call_args.args[0]
        self.assertIn("document__key=srd-2014", called_url)

    def test_session_ownership_and_cleanup(self):
        # Owned session is closed when discovery completes or stops early via limit.
        for limit in (None, 1):
            with self.subTest(owned=True, limit=limit):
                built_session = MagicMock()
                built_session.get.return_value = _response(self.list_payload)
                scraper = Dnd5eOpen5eSpellScraper(page_delay_seconds=0)

                with patch.object(scraper, "_build_session", return_value=built_session):
                    results = list(scraper.discover(ScrapeRequest(limit=limit)))

                self.assertEqual(len(results), 3 if limit is None else 1)
                built_session.close.assert_called_once_with()

        # Owned session is also closed when a request fails.
        failing_session = MagicMock()
        failing_response = MagicMock()
        failing_response.raise_for_status.side_effect = requests.exceptions.HTTPError("boom")
        failing_session.get.return_value = failing_response
        scraper = Dnd5eOpen5eSpellScraper(page_delay_seconds=0)
        with patch.object(scraper, "_build_session", return_value=failing_session):
            with self.assertRaises(requests.exceptions.HTTPError):
                list(scraper.discover(ScrapeRequest()))
        failing_session.close.assert_called_once_with()

        # Injected session is owned by the caller and is not closed by discover().
        injected_session = MagicMock()
        injected_session.get.return_value = _response(self.list_payload)
        scraper = Dnd5eOpen5eSpellScraper(page_delay_seconds=0, session=injected_session)
        results = list(scraper.discover(ScrapeRequest(limit=1)))
        self.assertEqual(len(results), 1)
        injected_session.close.assert_not_called()


class TestDnd5eOpen5eHttpRetries(unittest.TestCase):
    def setUp(self):
        # Proxy CONNECT happens before the mocked transport request.
        self.enterContext(patch.dict("os.environ", {"NO_PROXY": "*", "no_proxy": "*"}))

    def test_http_retries_for_429_and_transient_server_errors(self):
        page_payload = {
            "next": None,
            "results": [{"key": "srd-2024_fireball", "name": "Fireball"}],
        }
        for status_code in (429, 500, 502, 503, 504):
            with self.subTest(status_code=status_code):
                scraper = Dnd5eOpen5eSpellScraper(page_delay_seconds=0)
                responses = [
                    _urllib3_response(status_code),
                    _urllib3_response(status_code),
                    _urllib3_response(200, payload=page_payload),
                ]
                with (
                    patch(
                        "urllib3.connectionpool.HTTPConnectionPool._make_request",
                        side_effect=responses,
                    ) as mock_make_request,
                    patch("rpg_parser.adapters.scrapers.open5e.time.sleep") as mock_sleep,
                ):
                    results = list(scraper.discover(ScrapeRequest()))

                self.assertEqual(len(results), 1)
                self.assertEqual(results[0].params["record"]["key"], "srd-2024_fireball")
                self.assertEqual(mock_make_request.call_count, 3)
                # urllib3 skips backoff sleep on the 1st retry and sleeps backoff_factor * 2^1 = 1.0s on the 2nd.
                self.assertEqual(mock_sleep.call_args_list, [call(1.0)])

    def test_http_retry_respects_retry_after_with_zero_and_nonzero_page_delay(self):
        page1 = {
            "next": "https://api.open5e.com/v2/spells/?page=2",
            "results": [{"key": "srd-2024_a", "name": "A"}],
        }
        page2 = {
            "next": None,
            "results": [{"key": "srd-2024_b", "name": "B"}],
        }

        for page_delay, expected_sleeps in ((0, [call(3)]), (0.25, [call(3), call(0.25)])):
            with self.subTest(page_delay=page_delay):
                scraper = Dnd5eOpen5eSpellScraper(page_delay_seconds=page_delay)
                responses = [
                    _urllib3_response(429, headers={"Retry-After": "3"}),
                    _urllib3_response(200, payload=page1),
                    _urllib3_response(200, payload=page2),
                ]
                with (
                    patch(
                        "urllib3.connectionpool.HTTPConnectionPool._make_request",
                        side_effect=responses,
                    ) as mock_make_request,
                    patch("rpg_parser.adapters.scrapers.open5e.time.sleep") as mock_sleep,
                ):
                    results = list(scraper.discover(ScrapeRequest()))

                self.assertEqual(
                    [r.params["record"]["key"] for r in results],
                    ["srd-2024_a", "srd-2024_b"],
                )
                self.assertEqual(mock_make_request.call_count, 3)
                self.assertEqual(mock_sleep.call_args_list, expected_sleeps)

    def test_http_retry_bounded_exhaustion_raises_retry_error(self):
        for status_code in (429, 503):
            with self.subTest(status_code=status_code):
                scraper = Dnd5eOpen5eSpellScraper(page_delay_seconds=0)
                responses = [_urllib3_response(status_code) for _ in range(10)]
                with (
                    patch(
                        "urllib3.connectionpool.HTTPConnectionPool._make_request",
                        side_effect=responses,
                    ) as mock_make_request,
                    patch("rpg_parser.adapters.scrapers.open5e.time.sleep") as mock_sleep,
                ):
                    with self.assertRaises(requests.exceptions.RetryError):
                        list(scraper.discover(ScrapeRequest()))

                # 1 initial attempt + 3 configured retries = 4 total attempts.
                self.assertEqual(mock_make_request.call_count, 4)
                self.assertEqual(mock_sleep.call_args_list, [call(1.0), call(2.0)])

    def test_http_non_retryable_status_does_not_retry(self):
        for status_code in (400, 404):
            with self.subTest(status_code=status_code):
                scraper = Dnd5eOpen5eSpellScraper(page_delay_seconds=0)
                responses = [_urllib3_response(status_code)]
                with (
                    patch(
                        "urllib3.connectionpool.HTTPConnectionPool._make_request",
                        side_effect=responses,
                    ) as mock_make_request,
                    patch("rpg_parser.adapters.scrapers.open5e.time.sleep") as mock_sleep,
                ):
                    with self.assertRaises(requests.exceptions.HTTPError):
                        list(scraper.discover(ScrapeRequest()))

                self.assertEqual(mock_make_request.call_count, 1)
                mock_sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
