import threading
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from rpg_parser.core.ports import FetchRequest, RawDocument

# Identify the client honestly rather than spoofing a browser, so Archives of
# Nethys can recognize (and if needed, contact) this tool's traffic.
AON_USER_AGENT = "rpg-parser/0.1 (+https://github.com/BurcinSayin/rpg_parser)"


class AoNHtmlFetcher:
    """Fetches raw Archives of Nethys HTML pages."""

    def __init__(self, session: requests.Session | None = None, timeout: float = 30.0):
        self._injected_session = session
        self._local = threading.local()
        self.timeout = timeout

    @property
    def session(self) -> requests.Session:
        """Return a per-thread requests.Session.

        requests.Session is not thread-safe, and a bulk scrape fans this fetcher
        out across a ThreadPoolExecutor, so each worker thread lazily builds and
        reuses its own Session. A session injected via the constructor (a DI/
        testing hook) is returned as-is and is the caller's responsibility to use
        safely across threads.
        """
        if self._injected_session is not None:
            return self._injected_session
        session = getattr(self._local, "session", None)
        if session is None:
            session = self._build_session()
            self._local.session = session
        return session

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        retries = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        adapter = HTTPAdapter(max_retries=retries)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def fetch(self, request: FetchRequest) -> RawDocument:
        response = self.session.get(
            request.location,
            headers={"User-Agent": AON_USER_AGENT},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return RawDocument(
            content=response.text,
            source=request.location,
            media_type="text/html",
        )


class AoNElasticsearchClient:
    """Client for the Archives of Nethys Elasticsearch endpoint."""

    url = "https://elasticsearch.aonprd.com/aon/_search?stats=search"
    # AoN's index enforces index.max_result_window=10000; a larger `size`
    # (with no `from`) is rejected with a 400 "Result window is too large".
    MAX_RESULT_WINDOW = 10000

    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Content-Type": "application/json",
            "User-Agent": AON_USER_AGENT,
        }
        response = requests.post(
            self.url,
            json=payload,
            headers=headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def fetch_spells_bulk(self, tradition: str | None = "primal", size: int = 5000) -> list[dict[str, Any]]:
        size = min(size, self.MAX_RESULT_WINDOW)
        filters = [{"term": {"type": {"value": "spell"}}}]
        if tradition:
            filters.insert(0, {"term": {"tradition": {"value": tradition.lower()}}})

        payload = {
            "query": {
                "bool": {
                    "filter": filters
                }
            },
            "size": size,
            "_source": True,
        }

        data = self._post(payload)
        hits = data.get("hits", {}).get("hits", [])
        return [hit.get("_source", {}) for hit in hits]

    def fetch_spell_by_name(self, name: str) -> dict[str, Any]:
        payload = {
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"name.keyword": {"value": name}}},
                        {"term": {"type": {"value": "spell"}}},
                    ]
                }
            },
            "size": 1,
            "_source": True,
        }

        data = self._post(payload)
        hits = data.get("hits", {}).get("hits", [])

        if not hits:
            raise ValueError(f"Spell not found: {name}")

        return hits[0].get("_source", {})
