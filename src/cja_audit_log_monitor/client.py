"""API client for CJA audit logs endpoint."""

import logging
import time
from collections.abc import Iterator
from typing import Any

import httpx

from .auth import TokenManager
from .config import CJASettings
from .models import AuditLogEntry, AuditLogQuery, AuditLogResponse

logger = logging.getLogger(__name__)

# Largest pageSize the CJA Audit Logs API accepts (it rejects 2000 with a 400).
MAX_PAGE_SIZE = 1000


def _is_final_page(page: int, response: AuditLogResponse) -> bool:
    """True when ``page`` is the last page by the API's own page count."""
    return response.total_pages > 0 and page + 1 >= response.total_pages


class APIError(Exception):
    """Raised when API request fails."""

    def __init__(self, message: str, status_code: int | None = None, response: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response = response


class RateLimitError(APIError):
    """Raised when rate limited by API."""

    def __init__(self, retry_after: int | None = None) -> None:
        super().__init__("Rate limited by API", status_code=429)
        self.retry_after = retry_after or 30


class AuditLogsClient:
    """Client for querying CJA audit logs API."""

    AUDIT_LOGS_PATH = "/auditlogs/api/v1/auditlogs"
    SEARCH_PATH = "/auditlogs/api/v1/auditlogs/search"

    def __init__(
        self,
        settings: CJASettings,
        token_manager: TokenManager | None = None,
    ) -> None:
        self.settings = settings
        self.token_manager = token_manager or TokenManager(settings)
        self._client: httpx.Client | None = None

    @property
    def client(self) -> httpx.Client:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.Client(
                base_url=self.settings.api_base_url,
                timeout=60.0,
            )
        return self._client

    def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            self._client.close()
            self._client = None

    def __enter__(self) -> "AuditLogsClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        retry_count: int = 3,
    ) -> dict[str, Any]:
        """Make authenticated request with retry logic."""
        headers = self.token_manager.get_auth_headers()

        for attempt in range(retry_count):
            try:
                response = self.client.request(
                    method=method,
                    url=path,
                    headers=headers,
                    params=params,
                    json=json,
                )

                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 30))
                    if attempt < retry_count - 1:
                        logger.warning(
                            "Rate limited, waiting %d seconds (attempt %d/%d)",
                            retry_after,
                            attempt + 1,
                            retry_count,
                        )
                        time.sleep(retry_after)
                        continue
                    raise RateLimitError(retry_after=retry_after)

                if response.status_code == 401:
                    # Token might be expired, invalidate and retry
                    if attempt < retry_count - 1:
                        logger.debug("Got 401, refreshing token")
                        self.token_manager.invalidate_token()
                        headers = self.token_manager.get_auth_headers()
                        continue
                    raise APIError("Authentication failed", status_code=401)

                response.raise_for_status()
                return response.json()

            except httpx.HTTPStatusError as e:
                error_detail = ""
                try:
                    error_detail = e.response.json()
                except Exception:
                    error_detail = e.response.text

                raise APIError(
                    f"API request failed: {e.response.status_code} - {error_detail}",
                    status_code=e.response.status_code,
                    response=error_detail,
                ) from e

            except httpx.RequestError as e:
                if attempt < retry_count - 1:
                    logger.warning(
                        "Request failed, retrying (attempt %d/%d): %s",
                        attempt + 1,
                        retry_count,
                        e,
                    )
                    time.sleep(2**attempt)  # Exponential backoff
                    continue
                raise APIError(f"Request failed: {e}") from e

        raise APIError("Max retries exceeded")

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

        return AuditLogResponse.model_validate(data)

    def get_logs_paginated(
        self,
        query: AuditLogQuery | None = None,
        max_pages: int | None = None,
    ) -> Iterator[AuditLogEntry]:
        """Iterate through all audit log entries across pages.

        Args:
            query: Base query parameters.
            max_pages: Maximum number of pages to fetch (None for all).

        Yields:
            Individual AuditLogEntry objects.
        """
        if query is None:
            query = AuditLogQuery()

        page = 0
        pages_fetched = 0

        while True:
            query.page = page
            response = self.get_logs(query)

            yield from response.content

            pages_fetched += 1

            if (
                response.last
                or not response.content
                or _is_final_page(page, response)
                or (max_pages and pages_fetched >= max_pages)
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
        entries = []
        for entry in self.get_logs_paginated(query):
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
        total = 0
        page = 0
        while len(entries) < max_entries:
            base.page = page
            response = self.get_logs(base)
            total = response.total_elements
            entries.extend(response.content)
            if response.last or not response.content or _is_final_page(page, response):
                break
            page += 1
        return entries[:max_entries], total

    def search_logs(self, filters: list[dict[str, Any]]) -> AuditLogResponse:
        """Search audit logs using POST with complex filters.

        This endpoint supports OR logic between filters.

        Args:
            filters: List of filter conditions.

        Returns:
            AuditLogResponse containing matching logs.
        """
        payload = {"filters": filters}

        logger.debug("Searching audit logs with filters: %s", filters)
        data = self._request("POST", self.SEARCH_PATH, json=payload)

        return AuditLogResponse.model_validate(data)

    def get_component_logs(
        self,
        component_id: str,
        component_type: str | None = None,
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

        return self.get_all_logs(query)

    def get_user_logs(
        self,
        user_id: str,
        query: AuditLogQuery | None = None,
    ) -> list[AuditLogEntry]:
        """Get all audit logs for a specific user.

        Args:
            user_id: The user ID to filter by.
            query: Optional additional query parameters.

        Returns:
            List of audit log entries for the user.
        """
        if query is None:
            query = AuditLogQuery()
        query.user_id = user_id

        return self.get_all_logs(query)

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
