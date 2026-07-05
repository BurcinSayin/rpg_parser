import threading
import unittest

import requests

from rpg_parser.adapters.fetchers.aon import AoNHtmlFetcher
from rpg_parser.adapters.fetchers.open5e import Open5eJsonFetcher
from rpg_parser.core.pipeline import run_scrape_pipeline
from rpg_parser.core.ports import (
    ExportTarget,
    FetchRequest,
    RawDocument,
    ScrapePipelineSpec,
    ScrapeRequest,
)

FETCHER_CLASSES = (AoNHtmlFetcher, Open5eJsonFetcher)


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
