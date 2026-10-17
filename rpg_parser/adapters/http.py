import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Identify the client honestly rather than spoofing a browser, so upstream
# services (Archives of Nethys, Open5e) can recognize and, if needed, contact
# this tool's traffic.
USER_AGENT = "rpg-parser/0.1 (+https://github.com/BurcinSayin/rpg_parser)"

RETRY_TOTAL = 3
RETRY_BACKOFF_FACTOR = 0.5
RETRY_STATUS_FORCELIST = (429, 500, 502, 503, 504)
RETRY_ALLOWED_METHODS = ("GET",)


def build_retry_session() -> requests.Session:
    """Build a requests.Session mounted with bounded GET retries for 429 and transient 5xx."""
    session = requests.Session()
    retries = Retry(
        total=RETRY_TOTAL,
        backoff_factor=RETRY_BACKOFF_FACTOR,
        status_forcelist=list(RETRY_STATUS_FORCELIST),
        allowed_methods=list(RETRY_ALLOWED_METHODS),
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

