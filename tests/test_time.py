"""Time zones, daylight saving changes and timestamps in the future."""

import time
from datetime import UTC, datetime, timedelta

import pytest

from cja_audit_log_monitor.alerts import AlertEngine, analyze_for_anomalies
from cja_audit_log_monitor.models import AlertRule, AuditLogEntry
from cja_audit_log_monitor.stats import get_daily_distribution, get_hourly_distribution
from cja_audit_log_monitor.utils import local_tz_name, zone_label


@pytest.fixture
def local_zone(monkeypatch):
    """Set the local time zone for one test: ``local_zone("Pacific/Kiritimati")``."""

    def set_zone(name: str) -> None:
        monkeypatch.setenv("TZ", name)
        time.tzset()

    yield set_zone
    monkeypatch.undo()
    time.tzset()


def _entry(ts: datetime, action: str = "EDIT", user: str = "u1") -> AuditLogEntry:
    return AuditLogEntry(timestamp=ts, action=action, user_id=user, component_type="PROJECT")


# ---------------------------------------------------------------------------
# zone_label


class TestZoneLabel:
    def test_no_timestamps_gives_the_current_zone(self, local_zone) -> None:
        local_zone("America/St_Johns")
        assert zone_label([]) == local_tz_name()
        assert zone_label([None]) == local_tz_name()

    def test_names_both_zones_across_a_change(self, local_zone) -> None:
        local_zone("America/St_Johns")
        winter = datetime(2026, 1, 15, 12, tzinfo=UTC)
        summer = datetime(2026, 7, 15, 12, tzinfo=UTC)
        assert zone_label([summer, winter, summer]) == "NST/NDT"

    def test_one_zone_is_named_once(self, local_zone) -> None:
        local_zone("Pacific/Kiritimati")
        stamps = [datetime(2026, m, 1, tzinfo=UTC) for m in range(1, 13)]
        assert zone_label(stamps) == "+14"


# ---------------------------------------------------------------------------
# Hour and day buckets far from UTC


class TestBucketsFarFromUtc:
    def test_kiritimati_moves_events_to_the_next_day(self, local_zone) -> None:
        local_zone("Pacific/Kiritimati")  # UTC+14
        entries = [_entry(datetime(2026, 1, 1, 10, 30, tzinfo=UTC))]
        assert get_hourly_distribution(entries, local=True)[0] == 1
        assert get_daily_distribution(entries, local=True) == {"2026-01-02": 1}
        # The UTC view is unchanged.
        assert get_hourly_distribution(entries)[10] == 1
        assert get_daily_distribution(entries) == {"2026-01-01": 1}

    def test_st_johns_half_hour_offset_moves_events_to_the_day_before(self, local_zone) -> None:
        local_zone("America/St_Johns")  # UTC-3:30 in winter
        entries = [_entry(datetime(2026, 1, 2, 3, 15, tzinfo=UTC))]
        assert get_hourly_distribution(entries, local=True)[23] == 1
        assert get_daily_distribution(entries, local=True) == {"2026-01-01": 1}


# ---------------------------------------------------------------------------
# The midnight to 5am check across a daylight saving change


class TestOffHoursAcrossDst:
    @staticmethod
    def _steady(start: datetime, hours: int, per_hour: int) -> list[AuditLogEntry]:
        return [
            _entry(start + timedelta(hours=h, minutes=60 * i // per_hour))
            for h in range(hours)
            for i in range(per_hour)
        ]

    @pytest.mark.parametrize(
        "zone,start",
        [
            # US clocks fall back at 02:00 EDT (06:00 UTC) on 2026-11-01: 01:00 happens twice.
            ("America/New_York", datetime(2026, 10, 31, 16, tzinfo=UTC)),
            # US clocks spring forward at 02:00 EST (07:00 UTC) on 2026-03-08: 02:00 is skipped.
            ("America/New_York", datetime(2026, 3, 7, 17, tzinfo=UTC)),
            # Newfoundland changes on the same days, with a half-hour offset.
            ("America/St_Johns", datetime(2026, 10, 31, 16, tzinfo=UTC)),
        ],
    )
    def test_steady_activity_is_not_an_off_hours_burst(self, local_zone, zone, start) -> None:
        local_zone(zone)
        entries = self._steady(start, hours=24, per_hour=6)
        anomalies = analyze_for_anomalies(entries, lookback_hours=24, local=True)
        assert [a for a in anomalies if a["type"] == "off_hours_activity"] == []

    def test_a_burst_in_the_repeated_hour_names_both_zones(self, local_zone) -> None:
        local_zone("America/New_York")
        quiet = self._steady(datetime(2026, 10, 31, 16, tzinfo=UTC), hours=24, per_hour=1)
        # 01:30 EDT and 01:30 EST: the same local hour, an hour apart in real time.
        burst = [_entry(datetime(2026, 11, 1, 5, 30, tzinfo=UTC))] * 4 + [
            _entry(datetime(2026, 11, 1, 6, 30, tzinfo=UTC))
        ] * 4
        anomalies = analyze_for_anomalies(quiet + burst, lookback_hours=24, local=True)
        off_hours = [a for a in anomalies if a["type"] == "off_hours_activity"]
        assert len(off_hours) == 1
        assert off_hours[0]["hour"] == 1
        assert "01:00 EDT/EST" in off_hours[0]["description"]

    def test_utc_mode_is_not_moved_by_the_local_zone(self, local_zone) -> None:
        local_zone("Pacific/Kiritimati")
        quiet = self._steady(datetime(2026, 1, 1, tzinfo=UTC), hours=24, per_hour=1)
        burst = [_entry(datetime(2026, 1, 1, 2, 10, tzinfo=UTC))] * 8
        anomalies = analyze_for_anomalies(quiet + burst, lookback_hours=24)
        off_hours = [a for a in anomalies if a["type"] == "off_hours_activity"]
        assert [a["hour"] for a in off_hours] == [2]
        assert off_hours[0]["description"].endswith("02:00 UTC (9 actions)")


# ---------------------------------------------------------------------------
# Timestamps in the future


class TestFutureTimestamps:
    def test_buckets_and_anomalies_accept_future_entries(self, local_zone) -> None:
        local_zone("Pacific/Kiritimati")
        future = datetime.now(UTC) + timedelta(days=400)
        entries = [_entry(future, action="DELETE")] * 12
        assert sum(get_hourly_distribution(entries, local=True).values()) == 12
        assert sum(get_daily_distribution(entries, local=True).values()) == 12
        anomalies = analyze_for_anomalies(entries, local=True)
        assert any(a["type"] == "bulk_delete_single_user" for a in anomalies)

    def test_a_far_future_event_ages_out_of_the_alert_window(self) -> None:
        rule = AlertRule(
            name="deletes",
            actions=["DELETE"],
            threshold_count=2,
            threshold_window_minutes=5,
        )
        engine = AlertEngine([rule])
        future = datetime.now(UTC) + timedelta(days=365)
        assert engine.check_entry(_entry(future, action="DELETE")) == []
        # One real event later, outside the window, must not pair with the future one.
        fake_now = datetime.now(UTC) + timedelta(minutes=10)

        class _Clock(datetime):
            @classmethod
            def now(cls, tz=None):  # noqa: D102
                return fake_now if tz else fake_now.replace(tzinfo=None)

        import cja_audit_log_monitor.alerts as alerts_module

        original = alerts_module.datetime
        alerts_module.datetime = _Clock
        try:
            assert engine.check_entry(_entry(fake_now, action="DELETE")) == []
        finally:
            alerts_module.datetime = original


# ---------------------------------------------------------------------------
# Zone labels in the TUI: each time is labelled with the zone in effect at that moment

_WINTER = datetime(2026, 1, 15, 20, tzinfo=UTC)
_SUMMER = datetime(2026, 7, 15, 20, tzinfo=UTC)


def _render_text(renderable) -> str:
    from rich.console import Console

    console = Console(width=120, record=True)
    console.print(renderable)
    return console.export_text()


class TestTuiZoneLabels:
    @pytest.mark.parametrize("ts,zone", [(_WINTER, "PST"), (_SUMMER, "PDT")])
    def test_entry_detail_names_the_zone_of_that_entry(self, local_zone, ts, zone) -> None:
        from cja_audit_log_monitor.tui.modals.entry_detail import build_detail_table

        local_zone("America/Los_Angeles")
        text = _render_text(build_detail_table(_entry(ts)))
        line = next(line for line in text.splitlines() if line.startswith("timestamp"))
        assert line.rstrip().endswith(zone), line

    def test_entry_detail_without_a_timestamp_names_no_zone(self, local_zone) -> None:
        from cja_audit_log_monitor.tui.modals.entry_detail import build_detail_table

        local_zone("America/Los_Angeles")
        text = _render_text(build_detail_table(AuditLogEntry(id="x")))
        line = next(line for line in text.splitlines() if line.startswith("timestamp"))
        assert line.split()[1:] == ["-"]

    @staticmethod
    def _state_with(mock_app_state, entries):
        from cja_audit_log_monitor.models import AuditLogResponse

        client = mock_app_state.client
        client.get_logs_sample.return_value = (entries, len(entries))
        client.get_all_logs.return_value = entries
        client.get_logs.return_value = AuditLogResponse(
            content=entries, total_elements=len(entries), total_pages=1, last=True
        )
        return mock_app_state

    async def test_log_table_header_names_both_zones(self, mock_app_state, local_zone) -> None:
        from cja_audit_log_monitor.tui.app import CJAAuditApp
        from cja_audit_log_monitor.tui.widgets.log_table import LogTable

        local_zone("America/Los_Angeles")
        entries = [_entry(_SUMMER), _entry(_WINTER, user="u2")]
        table = LogTable()
        app = CJAAuditApp()
        app.state = self._state_with(mock_app_state, entries)
        async with app.run_test(size=(140, 40)) as pilot:
            await app.screen.mount(table)
            table.load_entries(entries)
            await pilot.pause()
            assert str(table.columns["timestamp"].label) == "time (PST/PDT)"
            table.load_entries([_entry(_SUMMER)])
            assert str(table.columns["timestamp"].label) == "time (PDT)"

    async def test_monitor_rows_header_names_both_zones(self, mock_app_state, local_zone) -> None:
        from cja_audit_log_monitor.tui.app import CJAAuditApp
        from cja_audit_log_monitor.tui.widgets.log_table import LogTable

        local_zone("America/Los_Angeles")
        table = LogTable()
        app = CJAAuditApp()
        app.state = mock_app_state
        async with app.run_test(size=(140, 40)) as pilot:
            await app.screen.mount(table)
            table.append_entries([_entry(_WINTER)], 1000)
            table.append_entries([_entry(_SUMMER, user="u2")], 1000)
            await pilot.pause()
            assert str(table.columns["timestamp"].label) == "time (PST/PDT)"

    async def test_dashboard_and_stats_hourly_labels_name_both_zones(
        self, mock_app_state, local_zone
    ) -> None:
        from textual.widgets import Static

        from cja_audit_log_monitor.tui.app import CJAAuditApp

        local_zone("America/Los_Angeles")
        entries = [_entry(_WINTER), _entry(_SUMMER, user="u2")]
        app = CJAAuditApp()
        app.state = self._state_with(mock_app_state, entries)
        async with app.run_test(size=(140, 42)) as pilot:
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            label = app.query_one("#dashboard-hourly-label", Static)
            assert str(label.render()) == "HOURLY ACTIVITY · PST/PDT"
            await pilot.press("s")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            for name in ("#stats-hourly-label", "#stats-daily-label"):
                assert str(app.query_one(name, Static).render()).endswith("· PST/PDT"), name


# ---------------------------------------------------------------------------
# The CLI works in UTC, and its headings say so


class TestCliSaysUtc:
    @staticmethod
    def _run(args: list[str], entries: list[AuditLogEntry]):
        from unittest.mock import MagicMock, patch

        from click.testing import CliRunner

        from cja_audit_log_monitor.cli import main

        client = MagicMock()
        client.get_all_logs.return_value = entries
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        with patch("cja_audit_log_monitor.cli.get_client", return_value=(client, MagicMock())):
            return CliRunner().invoke(main, ["cli", *args])

    def test_timeline_headings_name_utc(self, local_zone) -> None:
        local_zone("Pacific/Kiritimati")
        result = self._run(["timeline", "--days", "1"], [_entry(_WINTER)])
        assert result.exit_code == 0, result.output
        assert "Daily Activity (UTC)" in result.output
        assert "Hourly Distribution (UTC)" in result.output

    @pytest.mark.parametrize("preset,label", [("--today", "today"), ("--yesterday", "yesterday")])
    def test_query_presets_say_the_day_is_utc(self, local_zone, preset, label) -> None:
        local_zone("Pacific/Kiritimati")
        result = self._run(["query", preset], [])
        assert result.exit_code == 0, result.output
        assert f"Querying {label} (UTC)" in result.output
