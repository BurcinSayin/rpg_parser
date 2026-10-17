import time
from collections.abc import Iterable

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from rpg_parser.adapters.fetchers.open5e import OPEN5E_USER_AGENT
from rpg_parser.core.ports import FetchRequest, ScrapeRequest

OPEN5E_PAGE_DELAY_SECONDS = 1.0
OPEN5E_RETRY_STATUS_FORCELIST = (429, 500, 502, 503, 504)


class Dnd5eOpen5eSpellScraper:
    """Discovers D&D 5e SRD spells from the Open5e v2 list endpoint.

    The list endpoint returns complete spell objects (paginated via a ``next`` URL),
    so each discovered spell is embedded in ``FetchRequest.params['record']``. The
    Open5eJsonFetcher returns that embedded record directly, avoiding a redundant
    detail GET per spell.

    Discovery pagination is paced independently of the pipeline's detail-fetch
    ``delay_seconds`` (CLI ``--delay``) via ``page_delay_seconds`` (or
    ``ScrapeRequest.filters['page_delay_seconds']``), sleeping only between
    successive page requests. Page GETs use a ``requests.Session`` configured
    with bounded retries and exponential backoff for HTTP 429 and transient 5xx
    responses, honoring ``Retry-After``.
    """

    base_url = "https://api.open5e.com/v2/spells/"

    def __init__(
        self,
        document_key: str = "srd-2024",
        timeout: float = 30.0,
        page_delay_seconds: float | None = None,
        session: requests.Session | None = None,
    ):
        delay = OPEN5E_PAGE_DELAY_SECONDS if page_delay_seconds is None else page_delay_seconds
        if delay < 0:
            raise ValueError("page_delay_seconds must be non-negative")
        self.document_key = document_key
        self.timeout = timeout
        self.page_delay_seconds = delay
        self._injected_session = session

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        retries = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=list(OPEN5E_RETRY_STATUS_FORCELIST),
            allowed_methods=["GET"],
            respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(max_retries=retries)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def discover(self, request: ScrapeRequest) -> Iterable[FetchRequest]:
        limit = request.limit
        filters = request.filters or {}
        document_key = filters.get("document_key") or self.document_key
        raw_page_delay = filters.get("page_delay_seconds")
        page_delay = (
            self.page_delay_seconds if raw_page_delay is None else float(raw_page_delay)
        )
        if page_delay < 0:
            raise ValueError("page_delay_seconds must be non-negative")

        if limit is not None and limit <= 0:
            return

        url = request.location or f"{self.base_url}?document__key={document_key}&limit=50"

        headers = {"User-Agent": OPEN5E_USER_AGENT, "Accept": "application/json"}
        seen: set[str] = set()
        count = 0

        owns_session = self._injected_session is None
        session = self._build_session() if owns_session else self._injected_session
        assert session is not None

        try:
            page_fetched = False
            while url:
                if page_fetched and page_delay > 0:
                    time.sleep(page_delay)
                response = session.get(url, headers=headers, timeout=self.timeout)
                response.raise_for_status()
                page_fetched = True
                data = response.json()

                for spell in data.get("results", []):
                    key = spell.get("key")
                    if not key or key in seen:
                        continue
                    seen.add(key)

                    detail_url = f"{self.base_url}{key}/"
                    yield FetchRequest(location=detail_url, params={"record": spell})
                    count += 1

                    if limit is not None and count >= limit:
                        return

                url = data.get("next")
        finally:
            if owns_session:
                session.close()
