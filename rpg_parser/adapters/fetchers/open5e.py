import json
import threading

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from rpg_parser.core.ports import FetchRequest, RawDocument

# Identify the client honestly rather than spoofing a browser, so Open5e can
# recognize (and if needed, contact) this tool's traffic.
OPEN5E_USER_AGENT = "rpg-parser/0.1 (+https://github.com/BurcinSayin/rpg_parser)"


class Open5eJsonFetcher:
    """Fetches a single Open5e spell as raw JSON.

    Two paths feed this fetcher:

    * Single-record ``fetch`` — the request carries only a detail-page URL
      (e.g. ``https://api.open5e.com/v2/spells/srd-2024_fireball/``), which we GET.
    * Bulk ``scrape`` — the scraper already pulled the full spell object from the
      list endpoint and embeds it in ``request.params['record']``. We serialize
      that record instead of re-requesting it, so a 339-spell scrape costs only the
      handful of paginated list requests, not 339 extra detail GETs.
    """

    def __init__(self, session: requests.Session | None = None, timeout: float = 30.0):
        self._injected_session = session
        self._local = threading.local()
        self.timeout = timeout

    @property
    def session(self) -> requests.Session:
        """Return a per-thread requests.Session.

        requests.Session is not thread-safe, and a bulk scrape fans this fetcher
        out across a ThreadPoolExecutor, so each worker thread lazily builds and
        reuses its own Session. (Most ``dnd5e`` scrape records short-circuit on
        the embedded-record path before touching the session, but the networked
        detail-fetch path still needs it.) A session injected via the constructor
        (a DI/testing hook) is returned as-is and is the caller's responsibility
        to use safely across threads.
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
        record = (request.params or {}).get("record")
        if record is not None:
            return RawDocument(
                content=json.dumps(record, ensure_ascii=False),
                source=request.location,
                media_type="application/json",
            )

        response = self.session.get(
            request.location,
            headers={"User-Agent": OPEN5E_USER_AGENT, "Accept": "application/json"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return RawDocument(
            content=response.text,
            source=request.location,
            media_type="application/json",
        )
