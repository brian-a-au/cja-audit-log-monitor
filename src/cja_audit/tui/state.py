"""Application state management for the TUI."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from ..alerts import AlertEngine
from ..auth import TokenManager
from ..client import AuditLogsClient
from ..config import CJASettings, load_config
from ..models import ActionType, AuditLogEntry, AuditLogQuery, ComponentType

if TYPE_CHECKING:
    from rich.panel import Panel


@dataclass
class FilterState:
    """Current filter settings for log queries."""

    user: str = ""
    actions: list[ActionType] = field(default_factory=list)
    components: list[ComponentType] = field(default_factory=list)
    start_date: datetime | None = None
    end_date: datetime | None = None
    search_text: str = ""
    page: int = 0
    page_size: int = 50

    def to_query(self) -> AuditLogQuery:
        """Convert filter state to AuditLogQuery."""
        return AuditLogQuery(
            user_id=self.user if self.user else None,
            actions=self.actions if self.actions else None,
            components=self.components if self.components else None,
            start_date=self.start_date,
            end_date=self.end_date,
            description=self.search_text if self.search_text else None,
            page=self.page,
            page_size=self.page_size,
        )

    def reset(self) -> None:
        """Reset all filters to defaults."""
        self.user = ""
        self.actions = []
        self.components = []
        self.start_date = None
        self.end_date = None
        self.search_text = ""
        self.page = 0


@dataclass
class MonitorState:
    """State for real-time monitoring."""

    is_running: bool = False
    interval: int = 60
    last_check: datetime | None = None
    entries_since_start: int = 0
    alerts_triggered: int = 0


class AppState:
    """Centralized application state for the TUI."""

    def __init__(self, config_path: Path | None = None) -> None:
        """Initialize application state.

        Args:
            config_path: Optional path to config file.
        """
        self._config_path = config_path
        self._settings: CJASettings | None = None
        self._client: AuditLogsClient | None = None
        self._token_manager: TokenManager | None = None
        self._alert_engine: AlertEngine | None = None

        # Data state
        self.entries: list[AuditLogEntry] = []
        self.total_entries: int = 0
        self.selected_entry: AuditLogEntry | None = None

        # Filter state
        self.filters = FilterState()

        # Monitor state
        self.monitor = MonitorState()

        # Alerts
        self.recent_alerts: list[Panel] = []

        # Connection state
        self.is_connected: bool = False
        self.connection_error: str | None = None
        self.last_refresh: datetime | None = None

    @property
    def settings(self) -> CJASettings:
        """Get settings, loading if necessary."""
        if self._settings is None:
            self._settings = load_config(self._config_path)
        return self._settings

    @property
    def client(self) -> AuditLogsClient:
        """Get API client, creating if necessary."""
        if self._client is None:
            self._token_manager = TokenManager(self.settings)
            self._client = AuditLogsClient(self.settings, self._token_manager)
        return self._client

    @property
    def alert_engine(self) -> AlertEngine:
        """Get alert engine, creating if necessary."""
        if self._alert_engine is None:
            self._alert_engine = AlertEngine(self.settings.alert_rules or None)
        return self._alert_engine

    def refresh_client(self) -> None:
        """Refresh the API client connection."""
        if self._client:
            self._client.close()
            self._client = None
        self._token_manager = None

    async def verify_connection(self) -> dict:
        """Verify API connection and authentication.

        Returns:
            Dictionary with connection status and details.
        """
        try:
            with self.client:
                result = self.client.verify_connection()
            self.is_connected = result.get("connected", False)
            self.connection_error = result.get("error")
            return result
        except Exception as e:
            self.is_connected = False
            self.connection_error = str(e)
            return {
                "connected": False,
                "authenticated": False,
                "error": str(e),
            }

    def fetch_logs(self, max_entries: int | None = None) -> list[AuditLogEntry]:
        """Fetch audit logs based on current filters.

        Args:
            max_entries: Maximum number of entries to fetch.

        Returns:
            List of audit log entries.
        """
        query = self.filters.to_query()
        with self.client:
            self.entries = self.client.get_all_logs(query, max_entries=max_entries)
            self.last_refresh = datetime.now()
        return self.entries

    def fetch_logs_page(self) -> tuple[list[AuditLogEntry], int]:
        """Fetch a single page of logs.

        Returns:
            Tuple of (entries list, total count).
        """
        query = self.filters.to_query()
        with self.client:
            response = self.client.get_logs(query)
            self.entries = response.content
            self.total_entries = response.total_elements
            self.last_refresh = datetime.now()
        return self.entries, self.total_entries

    def check_alerts(self, entries: list[AuditLogEntry]) -> list["Panel"]:
        """Check entries against alert rules.

        Args:
            entries: List of audit log entries to check.

        Returns:
            List of triggered alert panels.
        """
        alerts = self.alert_engine.check_batch(entries)
        self.recent_alerts.extend(alerts)
        # Keep only last 50 alerts
        self.recent_alerts = self.recent_alerts[-50:]
        return alerts

    def close(self) -> None:
        """Clean up resources."""
        if self._client:
            self._client.close()
            self._client = None
