import threading
import unittest
from unittest.mock import Mock

import requests

from rpg_parser.adapters.fetchers.aon import AON_USER_AGENT, AoNHtmlFetcher
from rpg_parser.adapters.fetchers.open5e import OPEN5E_USER_AGENT, Open5eJsonFetcher
from rpg_parser.adapters.http import (
    RETRY_ALLOWED_METHODS,
    RETRY_BACKOFF_FACTOR,
    RETRY_STATUS_FORCELIST,
    RETRY_TOTAL,
    USER_AGENT,
    build_retry_session,
)
from rpg_parser.adapters.scrapers.open5e import (
    OPEN5E_RETRY_STATUS_FORCELIST,
    Dnd5eOpen5eSpellScraper,
)
from rpg_parser.core.pipeline import run_scrape_pipeline
from rpg_parser.core.ports import (
    ExportTarget,
    FetchRequest,
    RawDocument,
    ScrapePipelineSpec,
    ScrapeRequest,
)

FETCHER_CLASSES = (AoNHtmlFetcher, Open5eJsonFetcher)


class TestSharedHttpHelper(unittest.TestCase):
    def test_user_agent_and_retry_constants_are_shared(self):
        self.assertIs(AON_USER_AGENT, USER_AGENT)
        self.assertIs(OPEN5E_USER_AGENT, USER_AGENT)
        self.assertEqual(OPEN5E_RETRY_STATUS_FORCELIST, RETRY_STATUS_FORCELIST)

    def test_build_retry_session_mounts_retry_adapters_consistently(self):
        sessions = (
            ("helper", build_retry_session()),
            ("AoNHtmlFetcher", AoNHtmlFetcher()._build_session()),
            ("Open5eJsonFetcher", Open5eJsonFetcher()._build_session()),
            ("Dnd5eOpen5eSpellScraper", Dnd5eOpen5eSpellScraper()._build_session()),
        )
        for label, session in sessions:
            with self.subTest(source=label):
                try:
                    for prefix in ("http://", "https://"):
                        adapter = session.get_adapter(f"{prefix}example.test")
                        retries = adapter.max_retries
                        self.assertEqual(retries.total, RETRY_TOTAL)
                        self.assertEqual(retries.backoff_factor, RETRY_BACKOFF_FACTOR)
                        self.assertEqual(
                            tuple(retries.status_forcelist),
                            RETRY_STATUS_FORCELIST,
                        )
                        self.assertEqual(
                            frozenset(retries.allowed_methods),
                            frozenset(RETRY_ALLOWED_METHODS),
                        )
                        self.assertTrue(retries.respect_retry_after_header)
                finally:
                    session.close()


class TestFetcherNetworkRequirement(unittest.TestCase):
    def test_declaration_matches_fetch_path_without_io(self):
        for params, needs_network in ((None, True), ({}, True), ({"record": None}, True),
                                      ({"record": {}}, False), ({"record": {"name": "Light"}}, False)):
            request = FetchRequest("https://example.test/spell", params=params)
            for cls in FETCHER_CLASSES:
                with self.subTest(cls=cls.__name__, params=params):
                    session = Mock()
                    session.get.return_value.text = "{}"
                    fetcher = cls(session=session)
                    expected = True if cls is AoNHtmlFetcher else needs_network
                    self.assertEqual(fetcher.requires_network(request), expected)
                    session.get.assert_not_called()
                    fetcher.fetch(request)
                    self.assertEqual(session.get.call_count, int(expected))


def collect_sessions_across_threads(fetcher, n=2):
    """Read ``fetcher.session`` twice from each of ``n`` threads held at a barrier.

    The barrier guarantees the threads are alive simultaneously, so a shared
    (non-thread-local) session would be observed as the same object across
    threads. Returns {thread_ident: (session_read_1, session_read_2)}.
    """
    barrier = threading.Barrier(n, timeout=5)
    results: dict[int, tuple] = {}
    errors: list[Exception] = []
    lock = threading.Lock()

    def worker():
        try:
            barrier.wait()
            first = fetcher.session
            second = fetcher.session
        except Exception as exc:  # surface worker failures to the main thread
            with lock:
                errors.append(exc)
            return
        with lock:
            results[threading.get_ident()] = (first, second)

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        if thread.is_alive():
            raise RuntimeError("worker thread did not finish within timeout")
    if errors:
        raise errors[0]
    return results


class TestFetcherThreadLocalSession(unittest.TestCase):
    def test_injected_session_is_returned_unchanged(self):
        sentinel = requests.Session()
        for cls in FETCHER_CLASSES:
            with self.subTest(cls=cls.__name__):
                fetcher = cls(session=sentinel)
                self.assertIs(fetcher.session, sentinel)

    def test_session_is_stable_within_a_thread(self):
        for cls in FETCHER_CLASSES:
            with self.subTest(cls=cls.__name__):
                fetcher = cls()
                first = fetcher.session
                second = fetcher.session
                self.assertIs(first, second)
                self.assertIsInstance(first, requests.Session)

    def test_each_thread_gets_a_distinct_session(self):
        for cls in FETCHER_CLASSES:
            with self.subTest(cls=cls.__name__):
                fetcher = cls()
                results = collect_sessions_across_threads(fetcher, n=2)

                self.assertEqual(len(results), 2, "expected two distinct threads")
                per_thread_sessions = []
                for first, second in results.values():
                    self.assertIs(first, second, "session not stable within a thread")
                    self.assertIsInstance(first, requests.Session)
                    per_thread_sessions.append(first)

                self.assertIsNot(
                    per_thread_sessions[0],
                    per_thread_sessions[1],
                    "threads shared a single Session",
                )


# One source of truth for the concurrency width: the barrier party count and
# max_workers are derived from this so they can't drift out of sync with the
# number of requests discovered.
REQUEST_LOCATIONS = (
    "https://example.test/one",
    "https://example.test/two",
)


class FakeScraper:
    def discover(self, _request: ScrapeRequest):
        for location in REQUEST_LOCATIONS:
            yield FetchRequest(location=location)


class FakeParser:
    def parse(self, document: RawDocument) -> dict:
        return {"Name": document.source.rsplit("/", 1)[-1]}


class FakeExporter:
    def export(self, data: dict, target: ExportTarget) -> None:  # pragma: no cover
        pass


class RecordingAoNFetcher(AoNHtmlFetcher):
    """Real thread-local session behaviour, but no network in ``fetch``."""

    def __init__(self, barrier: threading.Barrier):
        super().__init__()
        self._barrier = barrier
        self._lock = threading.Lock()
        self.seen: list[tuple[int, requests.Session]] = []

    def fetch(self, request: FetchRequest) -> RawDocument:
        self._barrier.wait()
        session = self.session  # exercises the real thread-local property
        with self._lock:
            self.seen.append((threading.get_ident(), session))
        return RawDocument(
            content="{}",
            source=request.location,
            media_type="application/json",
        )


class TestScrapePipelineSessionIsolation(unittest.TestCase):
    def test_concurrent_workers_use_distinct_sessions(self):
        worker_count = len(REQUEST_LOCATIONS)
        barrier = threading.Barrier(worker_count, timeout=5)
        fetcher = RecordingAoNFetcher(barrier)
        spec = ScrapePipelineSpec(
            scraper=FakeScraper(),
            fetcher=fetcher,
            parser=FakeParser(),
            exporter=FakeExporter(),
        )

        run_scrape_pipeline(
            spec,
            ScrapeRequest(limit=worker_count),
            delay_seconds=0,
            max_workers=worker_count,
        )

        self.assertEqual(len(fetcher.seen), worker_count)
        idents = {ident for ident, _ in fetcher.seen}
        session_ids = {id(session) for _, session in fetcher.seen}
        self.assertEqual(len(idents), worker_count, "fetches did not run on distinct threads")
        self.assertEqual(len(session_ids), worker_count, "workers shared a Session")


if __name__ == "__main__":
    unittest.main()
