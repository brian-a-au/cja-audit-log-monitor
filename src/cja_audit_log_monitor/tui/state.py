"""Application state management for the TUI."""

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ..alerts import AlertEngine, FiredAlert
from ..auth import TokenManager
from ..client import AuditLogsClient, ClientClosedError
from ..config import CJASettings, ConfigError, get_config_path, load_config
from ..models import ActionType, AuditLogEntry, AuditLogQuery, ComponentType
from ..notifications import NotificationManager

logger = logging.getLogger(__name__)


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
    # The last poll's error, or None when the last poll worked.
    last_error: str | None = None


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
        self._client_lock = threading.Lock()
        self._token_manager: TokenManager | None = None
        self._alert_engine: AlertEngine | None = None
        self._notification_manager: NotificationManager | None = None

        # Data state
        self.entries: list[AuditLogEntry] = []
        self.total_entries: int = 0
        # True once the log browser has loaded a page; until then entries/total are unknown.
        self.page_loaded: bool = False

        # Filter state
        self.filters = FilterState()

        # Monitor state
        self.monitor = MonitorState()

        # Days the statistics view looks back; starts at the configured default_days.
        self.stats_days: int = 7

        # Connection state
        self.is_connected: bool = False
        self.connection_error: str | None = None
        self.config_error: str | None = None
        self.config_error_summary: str | None = None
        # Set by close(): no client is built after that.
        self._closed = False
        # Names of rules turned off this session; kept across a settings reload.
        self._disabled_rules: set[str] = set()
        self.last_refresh: datetime | None = None

    @property
    def settings(self) -> CJASettings:
        """Get settings, loading if necessary."""
        if self._settings is None:
            try:
                self._settings = load_config(self.config_path)
            except ConfigError as e:
                # Keep the app usable: fall back to env-only settings and
                # let the header show what is wrong with the file.
                self.config_error = str(e)
                self.config_error_summary = e.summary
                try:
                    self._settings = load_config(use_file=False)
                except ConfigError as env_error:
                    # Env/.env values are invalid too: start on plain defaults.
                    self._settings = CJASettings.model_construct()
                    self.config_error = f"{self.config_error}\n{env_error}"
                    self.config_error_summary = f"{e.summary}; {env_error.summary}"
        return self._settings

    @property
    def config_path(self) -> Path:
        """Get effective config path."""
        return self._config_path or get_config_path()

    @property
    def client(self) -> AuditLogsClient:
        """Get API client, creating if necessary."""
        with self._client_lock:
            if self._closed:
                raise ClientClosedError()
            if self._client is None:
                self._token_manager = TokenManager(self.settings)
                self._client = AuditLogsClient(self.settings, self._token_manager)
            return self._client

    @property
    def alert_engine(self) -> AlertEngine:
        """Get alert engine, creating if necessary."""
        if self._alert_engine is None:
            engine = AlertEngine(self.settings.alert_rules or None)
            for rule in engine.rules:  # toggles from before a reload stay as they were
                if rule.name in self._disabled_rules:
                    rule.enabled = False
            self._alert_engine = engine
        return self._alert_engine

    def new_test_engine(self) -> AlertEngine:
        """Build a throwaway engine with the live rules' current enabled flags.

        "Test rules" runs on this so it never adds to the live engine's event history.
        """
        return AlertEngine(self.alert_engine.rules)

    def reset_alert_rules(self) -> None:
        """Rebuild the live engine from settings (or built-in defaults when none).

        The new engine is built first and then swapped in with one assignment, so a
        monitor worker mid-``check_alerts`` finishes on the old engine and the next
        call picks up the new one. Nothing is mutated in place, so nothing can crash.
        """
        self._disabled_rules = set()
        self._alert_engine = AlertEngine(self.settings.alert_rules or None)

    @property
    def notification_manager(self) -> NotificationManager:
        """Get notification manager, creating if necessary."""
        if self._notification_manager is None:
            self._notification_manager = NotificationManager(self.settings.notifications)
        return self._notification_manager

    def refresh_client(self) -> None:
        """Refresh the API client connection."""
        with self._client_lock:
            if self._client:
                self._client.close()
                self._client = None
            self._token_manager = None

    def reload_settings(self) -> None:
        """Re-read the config file and drop everything built from the old settings.

        The file is read first. If it is broken, nothing changes: the working settings,
        client and rules stay, the header shows the problem, and ConfigError is raised.
        Otherwise the alert engine, the notification manager and the client are rebuilt
        lazily from the new settings, and rules turned off in this session stay off.

        Raises:
            RuntimeError: While the monitor runs. Closing the client would break its
                in-flight request, and a new engine would drop its event history.
            ConfigError: The config file is broken; the current settings are kept.
        """
        if self.monitor.is_running:
            raise RuntimeError("stop the monitor first")
        try:
            new_settings = load_config(self._config_path)
        except ConfigError as e:
            self.config_error = str(e)
            self.config_error_summary = e.summary
            raise
        if self._alert_engine is not None:
            self._disabled_rules = {r.name for r in self._alert_engine.rules if not r.enabled}
        self._settings = new_settings
        self.config_error = None
        self.config_error_summary = None
        self.is_connected = False
        self.connection_error = None
        self._alert_engine = None
        if self._notification_manager:
            self._notification_manager.close()
            self._notification_manager = None
        self.refresh_client()
        self.apply_settings_defaults()

    def apply_settings_defaults(self) -> None:
        """Start the page size, monitor interval and stats days from the settings.

        Called at startup and after a reload. It resets the log page to the first, since
        the page size may have changed. Views read these values when they are built or told
        the settings were reloaded.
        """
        settings = self.settings
        self.filters.page_size = settings.default_page_size
        self.filters.page = 0
        self.monitor.interval = settings.monitor_interval
        self.stats_days = settings.default_days

    def verify_connection(self) -> dict:
        """Verify API connection and authentication.

        Returns:
            Dictionary with connection status and details.
        """
        try:
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

    def fetch_logs_page(self) -> tuple[list[AuditLogEntry], int]:
        """Fetch the page the filters select, without storing it.

        Runs in worker threads, so it leaves ``entries`` alone: the log browser
        stores a page only once it is the newest load.

        Returns:
            Tuple of (entries list, total count).
        """
        response = self.client.get_logs(self.filters.to_query())
        return response.content, response.total_elements

    def check_alerts(self, entries: list[AuditLogEntry]) -> list[FiredAlert]:
        """Check entries against alert rules and dispatch to notification channels.

        Args:
            entries: List of audit log entries to check.

        Returns:
            List of FiredAlert objects for triggered rules.
        """
        fired = self.alert_engine.check_batch(entries)
        # Best-effort dispatch: never let a notification bug block alert display
        nm = self.notification_manager
        if nm.is_configured():
            for fa in fired:
                try:
                    nm.notify_alert(fa.rule_name, fa.message, fa.entry)
                except Exception as e:
                    logger.error(
                        "Notification dispatch failed for rule %s: %s",
                        fa.rule_name,
                        type(e).__name__,
                    )
        return fired

    def close(self, wait: bool = True) -> None:
        """Clean up resources. Nothing is sent after this, not even a retry.

        ``wait=False`` returns at once (quitting): a request in progress is left to end.
        """
        with self._client_lock:
            self._closed = True
            if self._client:
                self._client.close(wait=wait)
        if self._notification_manager:
            self._notification_manager.close(wait=wait)
