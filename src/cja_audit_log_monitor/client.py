"""API client for CJA audit logs endpoint."""

import logging
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx
from pydantic import ValidationError

from .auth import TokenManager
from .config import CJASettings
from .models import AuditLogEntry, AuditLogQuery, AuditLogResponse

logger = logging.getLogger(__name__)

# Largest pageSize the CJA Audit Logs API accepts (it rejects 2000 with a 400).
MAX_PAGE_SIZE = 1000

# Longest we will ever wait between retries, whatever the server asks for.
MAX_RETRY_WAIT = 60.0

# Server-side failures that are worth retrying.
RETRYABLE_STATUS = frozenset({500, 502, 503, 504})


def _retry_delay(header: str | None, attempt: int) -> float:
    """Seconds to wait before a retry, from a Retry-After header or exponential backoff."""
    delay: float | None = None
    if header is not None:
        try:
            delay = float(header)
        except ValueError:
            try:
                when = parsedate_to_datetime(header)
                if when.tzinfo is None:
                    when = when.replace(tzinfo=UTC)
                delay = (when - datetime.now(UTC)).total_seconds()
            except (TypeError, ValueError):
                delay = None
    if delay is None or delay != delay:  # missing, unparseable or NaN
        delay = float(2**attempt)
    return min(max(delay, 0.0), MAX_RETRY_WAIT)


def is_final_page(page: int, response: AuditLogResponse) -> bool:
    """True when ``page`` is the last page by the API's own page count."""
    return response.total_pages > 0 and page + 1 >= response.total_pages


class APIError(Exception):
    """Raised when API request fails."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        response: Any = None,
        network: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response = response
        # True when the API host could not be reached at all (DNS, refused, timed out).
        self.network = network


class ClientClosedError(APIError):
    """Raised for a request made after ``close()``; nothing is sent."""

    def __init__(self) -> None:
        super().__init__("the API client is closed")


class RateLimitError(APIError):
    """Raised when rate limited by API."""

    def __init__(self, retry_after: float | None = None) -> None:
        self.retry_after = 30 if retry_after is None else retry_after
        super().__init__(
            f"Rate limited by API; the server asked to wait {self.retry_after:g} seconds",
            status_code=429,
        )


# How many times one request is tried (rate limits, 5xx and network errors).
REQUEST_ATTEMPTS = 3


class AuditLogsClient:
    """Client for querying CJA audit logs API."""

    AUDIT_LOGS_PATH = "/auditlogs/api/v1/auditlogs"

    def __init__(
        self,
        settings: CJASettings,
        token_manager: TokenManager | None = None,
    ) -> None:
        self.settings = settings
        self.token_manager = token_manager or TokenManager(settings)
        self._client: httpx.Client | None = None
        self._client_lock = threading.Lock()
        self._closed = False
        # Requests in progress. A close without waiting leaves the connection to the last
        # one: closing a socket under a thread that reads it does not wake that thread.
        self._in_flight = 0

    @property
    def client(self) -> httpx.Client:
        """Get or create HTTP client."""
        with self._client_lock:
            if self._closed:
                raise ClientClosedError()
            if self._client is None:
                self._client = httpx.Client(
                    base_url=self.settings.api_base_url,
                    timeout=60.0,
                )
            return self._client

    def close(self, wait: bool = True) -> None:
        """Close the client. Later requests raise ClientClosedError and are never sent.

        With ``wait=False`` (quitting the TUI) this returns at once: a request in progress
        is left to finish, is not retried, and the last one to end closes the connection.
        """
        with self._client_lock:
            self._closed = True
            http = self._client
            if http is None or (not wait and self._in_flight):
                return
            self._client = None
        http.close()

    def _request_done(self) -> None:
        """Count a request as ended; after a close without waiting, the last one cleans up."""
        with self._client_lock:
            self._in_flight -= 1
            http = self._client if self._closed and self._in_flight == 0 else None
            if http is not None:
                self._client = None
        if http is not None:
            http.close()

    def __enter__(self) -> "AuditLogsClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make authenticated request with retry logic."""
        with self._client_lock:
            if self._closed:
                raise ClientClosedError()
            self._in_flight += 1
        try:
            return self._request_with_retries(method, path, params, REQUEST_ATTEMPTS)
        finally:
            self._request_done()

    def _request_with_retries(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None,
        retry_count: int,
    ) -> dict[str, Any]:
        """The body of ``_request``."""
        headers = self.token_manager.get_auth_headers()
        # A token refresh after a 401 happens once and does not use up a retry attempt.
        refreshed = False
        attempt = 0
        while attempt < retry_count:
            if self._closed:
                raise ClientClosedError()  # closed during a retry wait: send nothing more
            try:
                response = self.client.request(
                    method=method,
                    url=path,
                    headers=headers,
                    params=params,
                )

                if response.status_code == 429:
                    retry_after = _retry_delay(response.headers.get("Retry-After"), attempt)
                    if attempt < retry_count - 1:
                        logger.warning(
                            "Rate limited, waiting %g seconds (attempt %d/%d)",
                            retry_after,
                            attempt + 1,
                            retry_count,
                        )
                        time.sleep(retry_after)
                        attempt += 1
                        continue
                    raise RateLimitError(retry_after=retry_after)

                if response.status_code in RETRYABLE_STATUS and attempt < retry_count - 1:
                    delay = _retry_delay(response.headers.get("Retry-After"), attempt)
                    logger.warning(
                        "Server error %d, retrying in %g seconds (attempt %d/%d)",
                        response.status_code,
                        delay,
                        attempt + 1,
                        retry_count,
                    )
                    time.sleep(delay)
                    attempt += 1
                    continue

                if response.status_code == 401:
                    # Token might be expired: refresh it once and send again
                    if not refreshed:
                        refreshed = True
                        logger.debug("Got 401, refreshing token")
                        self.token_manager.invalidate_token()
                        headers = self.token_manager.get_auth_headers()
                        continue
                    raise APIError(
                        "Authentication failed (401). Check that ORG_ID, CLIENT_ID and "
                        "SECRET are current in the Developer Console.",
                        status_code=401,
                    )

                response.raise_for_status()
                try:
                    return response.json()
                except ValueError as e:
                    raise APIError(
                        "API returned a non-JSON response "
                        f"(HTTP {response.status_code}, {len(response.content)} bytes)",
                        status_code=response.status_code,
                    ) from e

            except httpx.HTTPStatusError as e:
                error_detail = ""
                try:
                    error_detail = e.response.json()
                except Exception:
                    error_detail = e.response.text

                detail_text = str(error_detail)
                if len(detail_text) > 300:
                    detail_text = detail_text[:299] + "\u2026"
                raise APIError(
                    f"API request failed: {e.response.status_code} - {detail_text}",
                    status_code=e.response.status_code,
                    response=error_detail,
                ) from e

            except RuntimeError as e:
                # httpx refuses a client closed between the lookup and the send.
                if self._closed or "closed" in str(e):
                    raise ClientClosedError() from None
                raise

            except httpx.RequestError as e:
                if self._closed:
                    raise ClientClosedError() from None
                if attempt < retry_count - 1:
                    logger.warning(
                        "Request failed, retrying (attempt %d/%d): %s",
                        attempt + 1,
                        retry_count,
                        e,
                    )
                    time.sleep(_retry_delay(None, attempt))  # Exponential backoff
                    attempt += 1
                    continue
                host = self.client.base_url.host or self.settings.api_base_url
                raise APIError(f"could not reach {host} ({type(e).__name__})", network=True) from e

        raise APIError("Max retries exceeded")  # pragma: no cover - last try returns or raises

    def get_logs(self, query: AuditLogQuery | None = None) -> AuditLogResponse:
        """Get audit logs with optional filtering.

        Args:
            query: Query parameters for filtering logs.

        Returns:
            AuditLogResponse containing logs and pagination info.
        """
        params = query.to_query_params() if query else {}

        logger.debug("Fetching audit logs with params: %s", params)
        data = self._request("GET", self.AUDIT_LOGS_PATH, params=params)
        if not isinstance(data, dict):
            raise APIError(
                f"API returned an unexpected response (expected a JSON object, "
                f"got {type(data).__name__})"
            )
        content = data.get("content")
        if not isinstance(content, list):
            raise APIError("API returned an unexpected response (no list of entries)")

        # Read each entry on its own, so one the tool cannot read does not lose the page.
        entries: list[AuditLogEntry] = []
        for raw in content:
            try:
                entries.append(AuditLogEntry.model_validate(raw))
            except ValidationError:
                pass
        skipped = len(content) - len(entries)
        if skipped:
            noun = "entry" if skipped == 1 else "entries"
            logger.warning("skipped %d %s the tool could not read", skipped, noun)
        return AuditLogResponse.model_validate({**data, "content": entries})

    def get_logs_paginated(
        self,
        query: AuditLogQuery | None = None,
    ) -> Iterator[AuditLogEntry]:
        """Iterate through all audit log entries across pages.

        Args:
            query: Base query parameters.

        Yields:
            Individual AuditLogEntry objects.
        """
        # Page on a copy so the caller's query keeps its own page number.
        query = query.model_copy() if query else AuditLogQuery()

        page = 0
        # New events shift newest-first pages while we read them, which can
        # repeat entries across a page boundary; skip ids already yielded.
        seen_ids: set[str] = set()

        while True:
            query.page = page
            response = self.get_logs(query)

            new_entries = 0
            for entry in response.content:
                if entry.id is not None:
                    if entry.id in seen_ids:
                        continue
                    seen_ids.add(entry.id)
                new_entries += 1
                yield entry

            # A page of entries already seen ends paging only when the API gives no page
            # count; otherwise late entries can still follow on later pages.
            more_pages = bool(response.total_pages) and page + 1 < response.total_pages
            if (
                response.last
                or (not new_entries and not more_pages)
                or is_final_page(page, response)
            ):
                break

            page += 1

    def get_all_logs(
        self,
        query: AuditLogQuery | None = None,
        max_entries: int | None = None,
    ) -> list[AuditLogEntry]:
        """Get all audit logs as a list.

        Args:
            query: Query parameters for filtering.
            max_entries: Maximum number of entries to return.

        Returns:
            List of AuditLogEntry objects.
        """
        # Ask for the largest page the API allows (or just the limit, if smaller),
        # without changing the caller's query.
        paged = query.model_copy() if query else AuditLogQuery()
        paged.page_size = min(MAX_PAGE_SIZE, max_entries) if max_entries else MAX_PAGE_SIZE

        entries = []
        for entry in self.get_logs_paginated(paged):
            entries.append(entry)
            if max_entries and len(entries) >= max_entries:
                break
        return entries

    def get_logs_sample(
        self,
        query: AuditLogQuery | None = None,
        max_entries: int = 1000,
    ) -> tuple[list[AuditLogEntry], int]:
        """Get up to ``max_entries`` of the newest matching entries, plus the true total.

        Fetches with the largest page size the API allows, so a sample of
        1,000 entries takes one request. The caller's query is not changed.

        Args:
            query: Query parameters for filtering.
            max_entries: Maximum number of entries to return.

        Returns:
            Tuple of (entries, total number of matching entries in the API).
        """
        base = query.model_copy() if query else AuditLogQuery()
        base.page_size = min(MAX_PAGE_SIZE, max_entries)
        entries: list[AuditLogEntry] = []
        seen_ids: set[str] = set()  # see get_logs_paginated
        total = 0
        page = 0
        while len(entries) < max_entries:
            base.page = page
            response = self.get_logs(base)
            total = response.total_elements
            before = len(entries)
            for entry in response.content:
                if entry.id is not None:
                    if entry.id in seen_ids:
                        continue
                    seen_ids.add(entry.id)
                entries.append(entry)
            # Stop on the last page, or on a page that added nothing new
            # (which also guards against a server that ignores paging).
            if response.last or len(entries) == before or is_final_page(page, response):
                break
            page += 1
        return entries[:max_entries], total

    def get_component_logs(
        self,
        component_id: str,
        component_type: str | None = None,
        max_entries: int | None = None,
    ) -> list[AuditLogEntry]:
        """Get all audit logs for a specific component (e.g., dashboard).

        Args:
            component_id: The component ID.
            component_type: Optional component type filter.

        Returns:
            List of audit log entries for the component.
        """
        query = AuditLogQuery(component_id=component_id)
        if component_type:
            from .models import ComponentType

            try:
                query.components = [ComponentType(component_type)]
            except ValueError:
                logger.warning("Unknown component type: %s", component_type)

        return self.get_all_logs(query, max_entries=max_entries)

    def verify_connection(self) -> dict[str, Any]:
        """Verify API connection and authentication.

        Returns:
            Dictionary with connection status and details.
        """
        result: dict[str, Any] = {
            "connected": False,
            "authenticated": False,
            "org_id": self.settings.org_id,
            "api_url": self.settings.api_base_url,
            "error": None,
        }

        try:
            # First check if we can get a token
            token = self.token_manager.get_token()
            result["authenticated"] = bool(token)

            # Try to fetch a single log entry to verify API access
            query = AuditLogQuery(page_size=1)
            response = self.get_logs(query)
            result["connected"] = True
            result["total_logs_available"] = response.total_elements

        except Exception as e:
            result["error"] = str(e)

        return result
