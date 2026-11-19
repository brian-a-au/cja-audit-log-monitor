"""CLI commands for CJA Audit Log Monitor."""

import asyncio
import functools
import io
import json
import logging
import os
import re
import sys
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from datetime import UTC, datetime, timedelta
from itertools import islice
from pathlib import Path
from typing import Any, ParamSpec, TextIO, TypeVar

import click
from rich.console import Console
from rich.logging import RichHandler
from rich.markup import escape
from rich.text import Text

from . import __version__
from .alerts import AlertEngine, analyze_for_anomalies, engine_rules
from .auth import AuthenticationError, TokenManager
from .client import MAX_PAGE_SIZE, APIError, AuditLogsClient, RateLimitError
from .config import (
    MAX_DAYS,
    CJASettings,
    ConfigError,
    create_default_config,
    get_config_path,
    load_config,
)
from .export import atomic_write, check_export_path, export_entries
from .formatters import (
    format_action_stats_table,
    format_logs_table,
    format_single_entry,
    format_stats_panel,
    format_user_stats_table,
)
from .models import ActionType, AuditLogEntry, AuditLogQuery, ComponentType
from .monitor import AuditLogMonitor
from .notifications import AnomalyDedupFilter, NotificationManager
from .stats import build_date_range_query, calculate_stats, generate_report
from .utils import get_user_identifier

P = ParamSpec("P")
R = TypeVar("R")

# Shared validators: counts must be at least 1; polling intervals at least 5 seconds.
POSITIVE_INT = click.IntRange(min=1)
# A day count, up to about ten years, so a typo cannot overflow a date.
DAYS = click.IntRange(min=1, max=MAX_DAYS)
LOOKBACK_HOURS = click.IntRange(min=1, max=MAX_DAYS * 24)
INTERVAL_SECONDS = click.IntRange(min=5)


def days_option(what: str) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """The --days option. Left unset, the command uses the configured default_days."""
    return click.option(
        "--days", "-d", type=DAYS, default=None,
        help=f"{what} (default: from config (7))",
    )


def output_format_option(func: Callable[P, R]) -> Callable[P, R]:
    """The -F/--output-format option (table or json) shared by the read commands."""
    return click.option(
        "--output-format",
        "-F",
        type=click.Choice(["table", "json"], case_sensitive=False),
        default="table",
        help="Output format",
    )(func)


def require_text(ctx: click.Context, param: click.Parameter, value: str | None) -> str | None:
    """Reject an empty or blank ID, which would silently match everything."""
    if value is not None and not value.strip():
        raise click.BadParameter("must not be empty")
    return value


def days_or_default(days: int | None, settings: CJASettings) -> int:
    """The --days value, or the configured default_days when the flag was not given."""
    return settings.default_days if days is None else days

console = Console()
err_console = Console(stderr=True)


def emit_json(data: Any, compact: bool = False) -> None:
    """Write machine-readable JSON to stdout, bypassing Rich markup and wrapping.

    ``compact`` writes one object on a single line (for streams of documents).
    """
    if compact:
        click.echo(json.dumps(data, separators=(",", ":"), default=str))
        sys.stdout.flush()
    else:
        click.echo(json.dumps(data, indent=2, default=str))


def handle_cli_errors(func: Callable[P, R]) -> Callable[P, R]:
    """Report expected failures on stderr and exit 1.

    Click's own exceptions (usage errors, ``SystemExit``) and ``KeyboardInterrupt``
    are not caught here, so exit codes and Ctrl+C behave as usual. The message is
    escaped because it can echo API or config text that contains square brackets.
    """

    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return func(*args, **kwargs)
        except BrokenPipeError:
            # Reader closed the pipe (e.g. `| head`). Point stdout at devnull so the
            # interpreter's exit flush does not raise again, and leave quietly.
            try:
                devnull = os.open(os.devnull, os.O_WRONLY)
                try:
                    os.dup2(devnull, sys.stdout.fileno())
                finally:
                    os.close(devnull)
            except (OSError, ValueError):  # stdout has no real fd (e.g. under test)
                pass
            sys.exit(1)
        except ConfigError as e:
            label = "Configuration error"
            error: Exception = e
        except AuthenticationError as e:
            label = "Authentication error"
            error = e
        except APIError as e:
            label = "API error"
            error = e
        except OSError as e:
            label = "File error"
            error = e
        except (click.ClickException, click.exceptions.Abort, click.exceptions.Exit):
            raise  # usage errors and Ctrl+C keep Click's own handling and exit codes
        except Exception as e:
            # A bug or an odd answer the tool did not expect: one line, and the
            # traceback only with -v.
            logging.getLogger(__name__).debug("Unexpected error", exc_info=True)
            err_console.print(
                f"[red]Unexpected error:[/red] {escape(type(e).__name__)}: {escape(str(e))}",
                soft_wrap=True,
            )
            sys.exit(1)
        # soft_wrap: one logical line, however long the path, so the terminal wraps it.
        err_console.print(f"[red]{label}:[/red] {escape(str(error))}", soft_wrap=True)
        sys.exit(1)

    return wrapper


def check_output_path(output: Path | None, force: bool) -> Path | None:
    """Fail fast (before any API call) on an unusable output path; return it with ``~`` expanded.

    Refuses an existing file (a dangling symlink counts) unless ``--force`` was given, a
    folder, a missing or unwritable folder, and a name that is too long. ``-`` means stdout
    and is always allowed.
    """
    if output is None or str(output) == "-":
        return output
    path, problem, exists = check_export_path(str(output))
    if problem is not None or path is None:
        raise OSError(problem)
    if exists and not force:
        raise FileExistsError(f"{path} already exists; use --force to overwrite")
    return path


def _tolerate_narrow_encodings() -> None:
    """Print a character the console cannot encode as '?' instead of crashing.

    On Windows a pipe or redirect gets a narrow encoding such as cp1252, which has no
    place for the tool's icons and bars, or for a CJK name. Exports to stdout write
    UTF-8 bytes instead (see ``utf8_stdout``), so their data is never changed.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            with suppress(Exception):
                reconfigure(errors="replace")


@contextmanager
def utf8_stdout(newline: str | None = None) -> Iterator[TextIO]:
    """A text stream that writes UTF-8 to stdout, whatever the console encoding."""
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:  # e.g. a test runner's string stream: already text, any encoding
        yield sys.stdout
        return
    sys.stdout.flush()
    stream = io.TextIOWrapper(buffer, encoding="utf-8", newline=newline, write_through=True)
    try:
        yield stream
    finally:
        stream.flush()
        stream.detach()  # leave sys.stdout's buffer open


def setup_logging(verbose: bool) -> None:
    """Configure logging based on verbosity."""
    level = logging.DEBUG if verbose else logging.WARNING
    # httpcore's debug lines dump raw headers (a redirect target can hold a webhook
    # secret) and fill the screen; -v is for this tool's own lines.
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[RichHandler(console=err_console, show_time=False, show_path=False)],
    )


def get_client(config_path: Path | None = None) -> tuple[AuditLogsClient, CJASettings]:
    """Create and return configured API client.

    Raises ConfigError for unusable configuration; ``handle_cli_errors`` reports it.
    """
    settings = load_config(config_path)
    token_manager = TokenManager(settings)
    client = AuditLogsClient(settings, token_manager)
    return client, settings


_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date(date_str: str | None, end_of_day: bool = False) -> datetime | None:
    """Parse a date string to a timezone-aware datetime (UTC when no zone is given).

    A date-only value means midnight UTC, or 23:59:59 UTC with ``end_of_day=True`` so an
    end date covers the whole day. Values that carry a time are used as given.
    """
    if not date_str:
        return None

    normalized = date_str.strip()
    date_only = bool(_DATE_ONLY.match(normalized))
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"

    parsed: datetime | None = None
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S"):
            try:
                parsed = datetime.strptime(normalized, fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        raise click.BadParameter(f"Invalid date format: {date_str}")

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    if date_only and end_of_day:
        parsed = parsed.replace(hour=23, minute=59, second=59)
    return parsed


def parse_date_range(
    start_date: str | None, end_date: str | None
) -> tuple[datetime | None, datetime | None]:
    """Parse ``--start-date`` and ``--end-date``; reject a start that is after the end."""
    start = parse_date(start_date)
    end = parse_date(end_date, end_of_day=True)
    if start and end and start > end:
        raise click.BadParameter(
            f"--start-date ({start_date}) is after --end-date ({end_date})",
            param_hint="--start-date",
        )
    return start, end


def parse_actions(actions: tuple[str, ...] | None) -> list[ActionType] | None:
    """Parse action strings to ActionType enum."""
    if not actions:
        return None

    result = []
    for action in actions:
        try:
            result.append(ActionType(action.upper()))
        except ValueError:
            valid = ", ".join(a.value for a in ActionType)
            raise click.BadParameter(f"Invalid action: {action}. Valid actions: {valid}")
    return result


def parse_components(components: tuple[str, ...] | None) -> list[ComponentType] | None:
    """Parse component strings to ComponentType enum."""
    if not components:
        return None

    result = []
    for component in components:
        try:
            result.append(ComponentType(component.upper()))
        except ValueError:
            valid = ", ".join(c.value for c in ComponentType)
            raise click.BadParameter(f"Invalid component: {component}. Valid: {valid}")
    return result


@click.group(invoke_without_command=True, context_settings={"show_default": True})
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
@click.option(
    "--config",
    "-c",
    # readable=False: the config loader reports an unreadable file in its own one line form.
    type=click.Path(exists=False, readable=False, path_type=Path),
    help="Path to config file",
)
@click.version_option(version=__version__)
@click.pass_context
def main(ctx: click.Context, verbose: bool, config: Path | None) -> None:
    """CJA Audit Log Monitor - Query and analyze Adobe CJA audit logs.

    Running without a subcommand launches the TUI interface.
    Use 'cja-audit-log-monitor cli <command>' for traditional CLI commands.
    """
    setup_logging(verbose)
    _tolerate_narrow_encodings()
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    ctx.obj["config_path"] = config

    # If no subcommand is given, launch the TUI
    if ctx.invoked_subcommand is None:
        run_tui(config)


def run_tui(config_path: Path | None) -> None:
    """Run the TUI, then end the process without waiting for abandoned worker threads."""
    from .tui import CJAAuditApp

    app = CJAAuditApp(config_path)
    # A loop of our own: asyncio.run() would wait for every worker thread at the end,
    # including one still waiting on the network after the user quit.
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        app.run(loop=loop)
    finally:
        asyncio.set_event_loop(None)
        loop.close()
    exit_without_waiting_for_workers(app.return_code)


def exit_without_waiting_for_workers(code: int | None) -> None:
    """End the process now if a worker thread is still running.

    After quit, a worker can still wait on the network, e.g. a webhook the user quit
    during. Python would wait for that thread before the process ends, so quitting would
    look hung. Nothing is left to save at this point, so the process ends at once.
    """
    others = [
        t for t in threading.enumerate()
        if t is not threading.main_thread() and t.is_alive() and not t.daemon
    ]
    if not others:
        return
    sys.stdout.flush()
    sys.stderr.flush()
    logging.shutdown()
    os._exit(code or 0)


# CLI subcommand group for traditional CLI commands
@main.group()
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Traditional CLI commands for scripting and automation."""
    pass


@cli.command("list")
@click.option(
    "--limit", "-l", type=POSITIVE_INT, default=50,
    help="Maximum number of entries to show",
)
@click.option(
    "--component",
    "-C",
    multiple=True,
    help="Filter by component type (can specify multiple)",
)
@click.option("--details", "-D", is_flag=True, help="Show additional details")
@output_format_option
@click.pass_context
@handle_cli_errors
def cli_list(
    ctx: click.Context,
    limit: int,
    component: tuple[str, ...],
    details: bool,
    output_format: str,
) -> None:
    """List recent audit log entries."""
    config_path = ctx.obj.get("config_path")

    client, settings = get_client(config_path)

    query = AuditLogQuery(
        page_size=min(limit, 100),
        components=parse_components(component),
    )

    with client:
        entries = client.get_all_logs(query, max_entries=limit)

    if not entries:
        if output_format == "json":
            emit_json({"entries": [], "count": 0})
        else:
            console.print("[dim]No audit logs found.[/dim]")
        return

    if output_format == "json":

        from .export import entry_to_dict
        data = {"entries": [entry_to_dict(e) for e in entries], "count": len(entries)}
        emit_json(data)
    else:
        table = format_logs_table(entries, show_details=details)
        console.print(table)
        console.print(f"\n[dim]Showing {len(entries)} entries[/dim]")


@cli.command()
@click.option("--user", "-u", help="Filter by user ID or email")
@click.option(
    "--action",
    "-a",
    multiple=True,
    help="Filter by action type (can specify multiple)",
)
@click.option("--start-date", "-s", help="Start date (YYYY-MM-DD)")
@click.option("--end-date", "-e", help="End date (YYYY-MM-DD)")
@click.option(
    "--component",
    "-C",
    multiple=True,
    help="Filter by component type",
)
@click.option("--component-id", help="Filter by specific component ID")
@click.option("--description", "--desc", help="Search in description")
@click.option("--limit", "-l", type=POSITIVE_INT, default=100, help="Maximum entries to return")
@click.option("--details", "-D", is_flag=True, help="Show additional details")
@output_format_option
@click.pass_context
@handle_cli_errors
def search(
    ctx: click.Context,
    user: str | None,
    action: tuple[str, ...],
    start_date: str | None,
    end_date: str | None,
    component: tuple[str, ...],
    component_id: str | None,
    description: str | None,
    limit: int,
    details: bool,
    output_format: str,
) -> None:
    """Search audit logs with filters."""
    config_path = ctx.obj.get("config_path")

    start, end = parse_date_range(start_date, end_date)
    client, settings = get_client(config_path)

    query = AuditLogQuery(
        user_id=user,
        actions=parse_actions(action),
        start_date=start,
        end_date=end,
        components=parse_components(component),
        component_id=component_id,
        description=description,
        page_size=min(limit, 100),
    )

    with client:
        entries = client.get_all_logs(query, max_entries=limit)

    if not entries:
        if output_format == "json":
            emit_json({"entries": [], "count": 0})
        else:
            console.print("[dim]No matching audit logs found.[/dim]")
        return

    if output_format == "json":

        from .export import entry_to_dict
        data = {"entries": [entry_to_dict(e) for e in entries], "count": len(entries)}
        emit_json(data)
    else:
        table = format_logs_table(entries, show_details=details)
        console.print(table)
        console.print(f"\n[dim]Found {len(entries)} matching entries[/dim]")


@cli.command()
@click.option(
    "--dashboard-id", "-i", required=True, callback=require_text, help="Dashboard/Project ID"
)
@click.option("--limit", "-l", type=POSITIVE_INT, default=100, help="Maximum entries to return")
@output_format_option
@click.pass_context
@handle_cli_errors
def dashboard(ctx: click.Context, dashboard_id: str, limit: int, output_format: str) -> None:
    """Show all audit events for a specific dashboard/project."""
    config_path = ctx.obj.get("config_path")

    client, settings = get_client(config_path)

    with client:
        entries = client.get_component_logs(dashboard_id, "PROJECT")
        entries = entries[:limit]

    if output_format == "json":
        from .export import entry_to_dict

        emit_json({
            "dashboard_id": dashboard_id,
            "entries": [entry_to_dict(e) for e in entries],
            "count": len(entries),
        })
        return

    if not entries:
        console.print(f"[dim]No audit logs found for dashboard {escape(dashboard_id)}[/dim]")
        return

    console.print(f"[bold]Audit history for dashboard:[/bold] {escape(dashboard_id)}\n")
    table = format_logs_table(entries, show_details=True)
    console.print(table)
    console.print(f"\n[dim]Found {len(entries)} entries[/dim]")


@cli.command()
@click.option(
    "--user-id", "-u", required=True, callback=require_text, help="User ID or email address"
)
@days_option("Number of days to query")
@click.option("--limit", "-l", type=POSITIVE_INT, default=100, help="Maximum entries to return")
@output_format_option
@click.pass_context
@handle_cli_errors
def user(
    ctx: click.Context, user_id: str, days: int | None, limit: int, output_format: str
) -> None:
    """Show all audit events for a specific user."""
    config_path = ctx.obj.get("config_path")

    client, settings = get_client(config_path)
    days = days_or_default(days, settings)

    query = build_date_range_query(days)
    query.user_id = user_id

    with client:
        entries = client.get_all_logs(query, max_entries=limit)

    if not entries:
        if output_format == "json":
            emit_json({"user": user_id, "entries": [], "count": 0})
        else:
            console.print(f"[dim]No audit logs found for user {escape(user_id)}[/dim]")
        return

    if output_format == "json":

        from .export import entry_to_dict
        data = {
            "user": user_id,
            "entries": [entry_to_dict(e) for e in entries],
            "count": len(entries),
        }
        emit_json(data)
    else:
        console.print(f"[bold]Audit history for user:[/bold] {escape(user_id)}\n")
        table = format_logs_table(entries, show_details=True)
        console.print(table)
        console.print(f"\n[dim]Found {len(entries)} entries[/dim]")


@cli.command()
@click.option(
    "--id", "-i", "component_id", required=True, callback=require_text, help="Component ID"
)
@click.option(
    "--type",
    "-t",
    "component_type",
    type=click.Choice([c.value for c in ComponentType], case_sensitive=False),
    help="Component type (optional)",
)
@click.option("--limit", "-l", type=POSITIVE_INT, default=100, help="Maximum entries to return")
@output_format_option
@click.pass_context
@handle_cli_errors
def component(
    ctx: click.Context,
    component_id: str,
    component_type: str | None,
    limit: int,
    output_format: str,
) -> None:
    """Show all audit events for a specific component."""
    config_path = ctx.obj.get("config_path")

    client, settings = get_client(config_path)

    with client:
        entries = client.get_component_logs(component_id, component_type)
        entries = entries[:limit]

    if not entries:
        if output_format == "json":
            emit_json({
                "component_id": component_id,
                "component_type": component_type,
                "entries": [],
                "count": 0,
            })
        else:
            console.print(f"[dim]No audit logs found for component {escape(component_id)}[/dim]")
        return

    if output_format == "json":

        from .export import entry_to_dict
        data = {
            "component_id": component_id,
            "component_type": component_type,
            "entries": [entry_to_dict(e) for e in entries],
            "count": len(entries),
        }
        emit_json(data)
    else:
        type_str = f" ({component_type})" if component_type else ""
        header = f"[bold]Audit history for component:[/bold] {escape(component_id)}{type_str}"
        console.print(f"{header}\n")
        table = format_logs_table(entries, show_details=True)
        console.print(table)
        console.print(f"\n[dim]Found {len(entries)} entries[/dim]")


@cli.command()
@click.option(
    "--format",
    "-F",
    type=click.Choice(["json", "csv", "tsv"], case_sensitive=False),
    default="json",
    help="Export format (default: from the file suffix .json, .csv or .tsv, else json)",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    required=True,
    help="Output file path, or - for stdout",
)
@click.option("--start-date", "-s", help="Start date (YYYY-MM-DD)")
@click.option("--end-date", "-e", help="End date (YYYY-MM-DD)")
@days_option("Number of days (if no date range)")
@click.option(
    "--action",
    "-a",
    multiple=True,
    help="Filter by action type",
)
@click.option(
    "--component",
    "-C",
    multiple=True,
    help="Filter by component type",
)
@click.option("--pretty/--compact", default=True, help="Pretty print JSON")
@click.option(
    "--max-entries",
    type=POSITIVE_INT,
    help="Maximum number of entries to export",
)
@click.option("--force", is_flag=True, help="Overwrite the output file if it exists")
@click.pass_context
@handle_cli_errors
def export(
    ctx: click.Context,
    format: str,
    output: Path,
    start_date: str | None,
    end_date: str | None,
    days: int | None,
    action: tuple[str, ...],
    component: tuple[str, ...],
    pretty: bool,
    max_entries: int | None,
    force: bool,
) -> None:
    """Export audit logs to a file, or to stdout with -o -."""
    config_path = ctx.obj.get("config_path")
    output = check_output_path(output, force)
    to_stdout = str(output) == "-"
    if ctx.get_parameter_source("format") is click.core.ParameterSource.DEFAULT:
        suffix = Path(str(output)).suffix.lower().lstrip(".")
        if suffix in {"json", "csv", "tsv"}:
            format = suffix
    destination: Any = output

    start, end = parse_date_range(start_date, end_date)
    client, settings = get_client(config_path)
    days = days_or_default(days, settings)

    # Build query
    if start_date or end_date:
        query = AuditLogQuery(
            start_date=start,
            end_date=end,
            actions=parse_actions(action),
            components=parse_components(component),
        )
    else:
        query = build_date_range_query(days)
        query.actions = parse_actions(action)
        query.components = parse_components(component)

    err_console.print("[dim]Fetching audit logs...[/dim]")

    # One entry past --max-entries is read, to tell whether the limit cut the export.
    cut = {"value": False}

    def up_to_limit(entries: Iterator[AuditLogEntry]) -> Iterator[AuditLogEntry]:
        for index, entry in enumerate(entries):
            if max_entries is not None and index == max_entries:
                cut["value"] = True
                return
            yield entry

    with client:
        if format in {"csv", "tsv"}:
            query.page_size = MAX_PAGE_SIZE  # fewer requests for a long export
            source: Any = up_to_limit(client.get_logs_paginated(query))
        else:
            limit = None if max_entries is None else max_entries + 1
            source = list(up_to_limit(iter(client.get_all_logs(query, max_entries=limit))))
        # An empty result still writes an empty document, so a scheduled export never
        # leaves yesterday's file in place.
        try:
            if to_stdout:
                with utf8_stdout(newline="" if format != "json" else None) as stream:
                    count = export_entries(source, stream, output_format=format, pretty=pretty)
            else:
                count = export_entries(
                    source, destination, output_format=format, pretty=pretty, overwrite=force
                )
        except FileExistsError:
            raise FileExistsError(
                f"{output} appeared during the export; use --force to overwrite"
            ) from None

    target = "stdout" if to_stdout else escape(str(output))
    if count == 0:
        err_console.print(
            f"[yellow]No audit logs matched; wrote an empty file to {target}.[/yellow]"
        )
    else:
        err_console.print(f"[green]Exported {count} entries to {target}[/green]")
    if cut["value"]:
        err_console.print(
            f"[yellow]Stopped at --max-entries {max_entries}; more entries matched.[/yellow]"
        )


@cli.command()
@days_option("Number of days to analyze")
@click.option("--top", "-n", type=POSITIVE_INT, default=10, help="Number of top users to show")
@output_format_option
@click.pass_context
@handle_cli_errors
def stats(ctx: click.Context, days: int | None, top: int, output_format: str) -> None:
    """Display summary statistics for audit logs."""
    config_path = ctx.obj.get("config_path")

    client, settings = get_client(config_path)
    days = days_or_default(days, settings)

    query = build_date_range_query(days)
    if output_format != "json":
        err_console.print(f"[dim]Analyzing last {days} days of audit logs...[/dim]\n")

    with client:
        entries = client.get_all_logs(query)

    if not entries:
        if output_format == "json":
            emit_json({"days": days, "statistics": calculate_stats([]), "anomalies": []})
        else:
            console.print("[dim]No audit logs found for the specified period.[/dim]")
        return

    stats_data = calculate_stats(entries, top_n=top)
    anomalies = analyze_for_anomalies(entries)

    if output_format == "json":
        data = {
            "days": days,
            "statistics": stats_data,
            "anomalies": anomalies,
        }
        emit_json(data)
    else:
        # Show summary panel
        panel = format_stats_panel(
            stats_data,
            title=f"Audit Log Statistics (Last {days} Days)",
            include_top_users=False,  # the Most Active Users table below has them
        )
        console.print(panel)
        console.print()

        # Show user activity table
        if stats_data["top_users"]:
            user_table = format_user_stats_table(stats_data["top_users"])
            console.print(user_table)
            console.print()

        # Show action distribution
        if stats_data["action_counts"]:
            action_table = format_action_stats_table(stats_data["action_counts"])
            console.print(action_table)

        # Check for anomalies
        if anomalies:
            console.print("\n[yellow bold]Potential Anomalies Detected:[/yellow bold]")
            for anomaly in anomalies:
                console.print(f"  [yellow]•[/yellow] {escape(str(anomaly['description']))}")


@cli.command()
@click.option(
    "--interval",
    "-i",
    type=INTERVAL_SECONDS,
    default=None,
    help="Polling interval in seconds (minimum 5, default: from config (60))",
)
@click.option(
    "--duration", type=POSITIVE_INT,
    help="Duration in seconds (default: indefinite)",
)
@click.option("--alerts/--no-alerts", default=True, help="Enable alert detection")
@click.pass_context
@handle_cli_errors
def monitor(
    ctx: click.Context,
    interval: int | None,
    duration: int | None,
    alerts: bool,
) -> None:
    """Monitor audit logs in real-time."""
    config_path = ctx.obj.get("config_path")

    try:
        client, settings = get_client(config_path)
        if interval is None:
            interval = settings.monitor_interval

        alert_engine = None
        if alerts:
            alert_engine = AlertEngine(engine_rules(settings))
            rule_count = len(alert_engine.rules)
            err_console.print(f"[dim]Alert detection enabled with {rule_count} rules[/dim]")

        with NotificationManager(settings.notifications) as nm:
            if nm.is_configured() and settings.notifications.notify_on_alerts:
                channel_summary = []
                if settings.notifications.slack_webhook_url:
                    channel_summary.append("Slack")
                enabled_webhooks = settings.notifications.enabled_webhook_count
                if enabled_webhooks:
                    channel_summary.append(f"{enabled_webhooks} webhook(s)")
                err_console.print(
                    f"[dim]Notification channels: {', '.join(channel_summary)}[/dim]"
                )

            monitor_instance = AuditLogMonitor(
                client,
                console=console,
                interval=interval,
                alert_engine=alert_engine,
                notification_manager=nm,
            )
            with client:
                monitor_instance.start(duration=duration)

        if monitor_instance.successful_polls == 0 and not monitor_instance.stopped_by_user:
            err_console.print("[red]No poll succeeded; see the errors above.[/red]")
            sys.exit(1)

    except KeyboardInterrupt:
        err_console.print("\n[yellow]Monitor stopped.[/yellow]")


@cli.command()
@click.option("--watch", is_flag=True, help="Run continuously")
@click.option(
    "--interval",
    type=INTERVAL_SECONDS,
    default=300,
    help="Poll interval in seconds (--watch only, minimum 5)",
)
@click.option(
    "--lookback",
    type=LOOKBACK_HOURS,
    default=24,
    help="Hours of history to scan per cycle",
)
@output_format_option
@click.pass_context
@handle_cli_errors
def anomalies(
    ctx: click.Context,
    watch: bool,
    interval: int,
    lookback: int,
    output_format: str,
) -> None:
    """Detect anomalies and dispatch to configured notification channels.

    With -F json each scan prints one JSON document on stdout; with --watch, one JSON
    object per line (one per cycle). Status messages go to stderr.
    """
    config_path = ctx.obj.get("config_path")

    try:
        client, settings = get_client(config_path)

        with (
            client,
            NotificationManager(settings.notifications) as nm,
        ):
            if nm.is_configured() and settings.notifications.notify_on_anomalies:
                channel_summary = []
                if settings.notifications.slack_webhook_url:
                    channel_summary.append("Slack")
                enabled_webhooks = settings.notifications.enabled_webhook_count
                if enabled_webhooks:
                    channel_summary.append(f"{enabled_webhooks} webhook(s)")
                err_console.print(
                    f"[dim]Anomaly delivery enabled: {', '.join(channel_summary)}[/dim]"
                )
            elif nm.is_configured():
                err_console.print(
                    "[dim]Notifications configured but notify_on_anomalies is false.[/dim]"
                )

            dedup = AnomalyDedupFilter()
            if watch:
                _install_anomalies_signal_handlers()

            while True:
                cycle_delay = interval
                try:
                    _run_anomalies_cycle(client, nm, dedup, lookback, output_format, watch)
                except (APIError, AuthenticationError) as e:
                    if not watch or not _is_retryable_anomalies_error(e):
                        raise
                    if isinstance(e, RateLimitError):
                        cycle_delay = max(interval, e.retry_after)
                    # In --watch mode, transient upstream errors must not kill
                    # the daemon. Log and continue to the next cycle.
                    err_console.print(f"[yellow]API error this cycle:[/yellow] {escape(str(e))}")
                if not watch:
                    break
                time.sleep(cycle_delay)

    except KeyboardInterrupt:
        err_console.print("\n[yellow]Anomaly scan stopped.[/yellow]")


_RETRYABLE_ANOMALY_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})


def _is_retryable_anomalies_error(error: APIError | AuthenticationError) -> bool:
    """Return whether a watch cycle should retry an API or token failure."""
    if isinstance(error, AuthenticationError):
        return error.transient
    return error.status_code is None or error.status_code in _RETRYABLE_ANOMALY_STATUSES


def _install_anomalies_signal_handlers() -> None:
    """Install SIGINT and SIGTERM handlers that interrupt the watch loop.

    Replaces any prior handlers for the duration of the process. SIGTERM is
    handled the same as SIGINT so systemd's default `KillSignal=SIGTERM` shuts
    the daemon down cleanly. Intended for one-shot CLI invocations where the
    watch loop owns the process lifetime; not safe to call from longer-lived
    embedders. Raising KeyboardInterrupt unwinds in-flight API pagination and
    notification delivery through both context managers instead of waiting for
    the full cycle to complete.
    """
    import signal

    def _handler(signum, frame):  # noqa: ARG001
        raise KeyboardInterrupt

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _handler)
        except ValueError:
            # signal.signal raises if not in main thread (e.g., under CliRunner).
            pass


def _run_anomalies_cycle(
    client: AuditLogsClient,
    nm: NotificationManager,
    dedup: AnomalyDedupFilter,
    lookback: int,
    output_format: str = "table",
    watch: bool = False,
) -> None:
    """One scan cycle: fetch → detect → dedup → print + dispatch → drain warnings."""
    end = datetime.now(UTC)
    start = end - timedelta(hours=lookback)
    query = AuditLogQuery(start_date=start, end_date=end)
    # Wrap in list() so analyze_for_anomalies (which calls len()) works against
    # any iterable-of-entries the client/mock returns.
    entries = list(client.get_all_logs(query))

    raw_anomalies = analyze_for_anomalies(entries, lookback_hours=lookback)
    new_anomalies = dedup.suppress_seen(raw_anomalies)

    as_json = output_format == "json"
    if as_json:
        emit_json({"anomalies": new_anomalies, "count": len(new_anomalies)}, compact=watch)

    if not raw_anomalies and not as_json:
        unit = "hour" if lookback == 1 else "hours"
        console.print(f"[dim]No anomalies found in the last {lookback} {unit}.[/dim]")

    for anomaly in new_anomalies:
        # Escape the description: it's user-derived (component names, user
        # identifiers) and may contain `[` characters that would otherwise
        # be parsed as Rich markup.
        description = anomaly.get("description", anomaly.get("type", "anomaly"))
        if not as_json:
            console.print(f"[yellow]•[/yellow] {escape(description)}")

    # Each anomaly goes to each channel until that channel accepts it once.
    channels = set(nm.channels()) if nm.config.notify_on_anomalies else set()
    for anomaly, todo in dedup.pending(raw_anomalies, channels):
        try:
            dedup.mark_sent(anomaly, nm.notify_anomaly(anomaly, channels=todo))
        except Exception as e:
            # Network failures are surfaced via pop_failures; this catches
            # unexpected programming errors so one bad anomaly doesn't kill the cycle.
            # Log only the type: the message and traceback locals could hold a webhook URL.
            logging.getLogger(__name__).error(
                "notify_anomaly raised %s unexpectedly; continuing", type(e).__name__
            )
    dedup.forget_missing(raw_anomalies)

    for warning in nm.pop_failures():
        err_console.print(f"[yellow]⚠ {escape(str(warning))}[/yellow]")


@cli.command()
@click.pass_context
@handle_cli_errors
def init(ctx: click.Context) -> None:
    """Initialize configuration file."""
    config_path = ctx.obj.get("config_path") or get_config_path()

    if config_path.exists():
        if not click.confirm(f"Config file already exists at {config_path}. Overwrite?"):
            return

    create_default_config(config_path)
    console.print(f"[green]Created config file at:[/green] {escape(str(config_path))}")
    console.print("\n[dim]Set these environment variables for authentication:[/dim]")
    console.print("  ORG_ID=your_org_id@AdobeOrg")
    console.print("  CLIENT_ID=your_client_id")
    console.print("  SECRET=your_client_secret")
    console.print("\n[dim]Or add them to a .env file in the folder you run from.[/dim]")


@cli.command()
@click.pass_context
@handle_cli_errors
def config(ctx: click.Context) -> None:
    """Show current configuration (without secrets)."""
    config_path = ctx.obj.get("config_path")

    settings = load_config(config_path)

    console.print("[bold]Current Configuration[/bold]\n")
    effective_config_path = config_path or get_config_path()
    missing = "" if effective_config_path.exists() else " (not found)"
    console.print(f"Config file: {escape(str(effective_config_path))}{missing}")
    console.print(f"API base URL: {escape(str(settings.api_base_url))}")
    console.print(f"IMS base URL: {escape(str(settings.ims_base_url))}")
    console.print(f"Log browser page size (TUI): {settings.default_page_size}")
    console.print(f"Default days: {settings.default_days}")
    console.print(f"Monitor interval: {settings.monitor_interval}s")
    console.print(f"OAuth configured: {settings.is_oauth_configured()}")
    org_display = f"{settings.org_id[:8]}..." if settings.org_id else "(not set)"
    client_display = f"{settings.client_id[:8]}..." if settings.client_id else "(not set)"
    console.print(f"Org ID: {escape(org_display)}")
    console.print(f"Client ID: {escape(client_display)}")
    console.print(f"Alert rules: {len(settings.alert_rules)}")


@cli.command()
@click.pass_context
def actions(ctx: click.Context) -> None:
    """List available action types."""
    console.print("[bold]Available Action Types[/bold]\n")
    for action in ActionType:
        console.print(f"  {action.value}")


@cli.command()
@click.pass_context
def components(ctx: click.Context) -> None:
    """List available component types."""
    console.print("[bold]Available Component Types[/bold]\n")
    for comp in ComponentType:
        console.print(f"  {comp.value}")


@cli.command()
@output_format_option
@click.pass_context
@handle_cli_errors
def verify(ctx: click.Context, output_format: str) -> None:
    """Verify API connection and authentication."""
    config_path = ctx.obj.get("config_path")

    try:
        client, settings = get_client(config_path)

        if output_format != "json":
            err_console.print("[dim]Verifying connection...[/dim]\n")

        with client:
            result = client.verify_connection()

        if output_format == "json":
            emit_json(result)
        else:
            if result["connected"] and result["authenticated"]:
                console.print("[green]✓[/green] Connection successful")
                console.print(f"  Organization: {escape(str(result['org_id']))}")
                console.print(f"  API URL: {escape(str(result['api_url']))}")
                total_logs = result.get('total_logs_available', 'N/A')
                console.print(f"  Total logs available: {escape(str(total_logs))}")
            else:
                console.print("[red]✗[/red] Connection failed")
                if result["error"]:
                    console.print(f"  Error: {escape(str(result['error']))}")

        if not (result["connected"] and result["authenticated"]):
            sys.exit(1)

    except AuthenticationError as e:
        if output_format == "json":
            emit_json({"connected": False, "error": str(e)})
        else:
            console.print(f"[red]✗[/red] Authentication failed: {escape(str(e))}")
        sys.exit(1)
    except APIError as e:
        if output_format == "json":
            emit_json({"connected": False, "error": str(e)})
        else:
            console.print(f"[red]✗[/red] API error: {escape(str(e))}")
        sys.exit(1)


@cli.command()
@days_option("Number of days to analyze")
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    help="Output file path (default: stdout)",
)
@click.option("--pretty/--compact", default=True, help="Pretty print JSON")
@click.option(
    "--max-entries",
    type=POSITIVE_INT,
    default=10000,
    show_default=True,
    help="Maximum number of entries to process",
)
@click.option("--force", is_flag=True, help="Overwrite the output file if it exists")
@click.pass_context
@handle_cli_errors
def report(
    ctx: click.Context,
    days: int | None,
    output: Path | None,
    pretty: bool,
    max_entries: int,
    force: bool,
) -> None:
    """Generate a comprehensive audit log report."""
    config_path = ctx.obj.get("config_path")
    output = check_output_path(output, force)

    client, settings = get_client(config_path)
    days = days_or_default(days, settings)

    err_console.print(f"[dim]Generating report for the last {days} days...[/dim]\n")

    query = build_date_range_query(days)

    with client:
        # Fetch one extra entry so "truncated" means there really is more data.
        entries = client.get_all_logs(query, max_entries=max_entries + 1)

    if not entries:
        err_console.print("[yellow]No audit logs found for the specified period.[/yellow]")

    truncated = len(entries) > max_entries
    entries = entries[:max_entries]
    if truncated:
        err_console.print(
            f"[yellow]Reached --max-entries limit ({max_entries}); "
            "report is based on a subset of logs.[/yellow]"
        )

    report_data = generate_report(entries)
    report_data["generated_at"] = datetime.now(UTC).isoformat()
    report_data["days_analyzed"] = days
    report_data["anomalies"] = analyze_for_anomalies(entries)
    report_data["truncated"] = truncated

    indent = 2 if pretty else None
    json_output = json.dumps(report_data, indent=indent, default=str)

    if output and str(output) != "-":
        with atomic_write(output, overwrite=force) as f:
            f.write(json_output)
        err_console.print(f"[green]Report saved to {escape(str(output))}[/green]")
    else:
        click.echo(json_output)


@cli.command()
@click.option(
    "--interval",
    "-i",
    type=INTERVAL_SECONDS,
    default=5,
    help="Polling interval in seconds (minimum 5)",
)
@click.option("--user", "-u", help="Filter by user ID or email")
@click.option("--component-id", help="Filter by component ID")
@click.option(
    "--action",
    "-a",
    multiple=True,
    help="Filter by action type (can specify multiple)",
)
@click.option("--alerts/--no-alerts", default=True, help="Enable alert detection")
@click.pass_context
@handle_cli_errors
def tail(
    ctx: click.Context,
    interval: int,
    user: str | None,
    component_id: str | None,
    action: tuple[str, ...],
    alerts: bool,
) -> None:
    """Follow audit logs in real-time (like tail -f)."""
    config_path = ctx.obj.get("config_path")

    try:
        client, settings = get_client(config_path)

        alert_engine = None
        if alerts:
            alert_engine = AlertEngine(engine_rules(settings))

        with NotificationManager(settings.notifications) as nm:
            actions_filter = parse_actions(action) if action else None
            action_values = {item.value for item in actions_filter} if actions_filter else None

            def matches(entry: AuditLogEntry) -> bool:
                if user and user not in (
                    entry.user_id,
                    entry.user_email,
                    get_user_identifier(entry),
                ):
                    return False
                if component_id and entry.component_id != component_id:
                    return False
                return not action_values or entry.action in action_values

            monitor_instance = AuditLogMonitor(
                client,
                console=console,
                interval=interval,
                alert_engine=alert_engine,
                notification_manager=nm,
                entry_filter=matches if (user or component_id or action_values) else None,
            )

            filters_desc = []
            if user:
                filters_desc.append(f"user={user}")
            if component_id:
                filters_desc.append(f"component={component_id}")
            if action:
                filters_desc.append(f"actions={','.join(action)}")

            filter_str = (
                f" [dim]({escape(', '.join(filters_desc))})[/dim]" if filters_desc else ""
            )

            err_console.print(f"[green]Tailing audit logs{filter_str}[/green]")

            with client:
                monitor_instance.start()

        if monitor_instance.successful_polls == 0 and not monitor_instance.stopped_by_user:
            err_console.print("[red]No poll succeeded; see the errors above.[/red]")
            sys.exit(1)

    except KeyboardInterrupt:
        err_console.print("\n[yellow]Stopped.[/yellow]")


# Alert rules subcommand group under cli
@cli.group()
@click.pass_context
def alerts(ctx: click.Context) -> None:
    """Manage alert rules."""
    pass


@alerts.command("list")
@output_format_option
@click.pass_context
@handle_cli_errors
def alerts_list(ctx: click.Context, output_format: str) -> None:
    """List all alert rules."""
    config_path = ctx.obj.get("config_path")

    settings = load_config(config_path)
    engine = AlertEngine(engine_rules(settings))
    rules_status = engine.get_rule_status()

    if output_format == "json":
        emit_json(rules_status)
    else:
        from rich.table import Table

        # Narrow headers and tight padding keep the table inside 80 columns; the key
        # columns never wrap, and only the free-text columns give way.
        name_width = max((len(str(rule["name"])) for rule in rules_status), default=4)
        table = Table(title="Alert Rules", padding=(0, 1, 0, 0), pad_edge=False)
        table.add_column("Name", style="cyan", no_wrap=True, min_width=name_width)
        table.add_column("Description", min_width=11, overflow="fold")
        table.add_column("On", justify="center", no_wrap=True)
        table.add_column("Count", justify="right", no_wrap=True)
        table.add_column("Win", justify="right", no_wrap=True)
        table.add_column("Actions", no_wrap=True)
        table.add_column("Components", min_width=10, overflow="fold")

        for rule in rules_status:
            enabled = "[green]✓[/green]" if rule["enabled"] else "[red]✗[/red]"
            rule_actions = ", ".join(rule["actions"]) if rule["actions"] else "-"
            rule_components = ", ".join(rule["components"][:2]) if rule["components"] else "-"
            if rule["components"] and len(rule["components"]) > 2:
                rule_components += f" +{len(rule['components']) - 2}"

            table.add_row(
                Text(rule["name"]),
                Text(rule["description"] or "-"),
                enabled,
                str(rule["threshold_count"]),
                f"{rule['threshold_window_minutes']}m",
                Text(rule_actions),
                Text(rule_components),
            )

        console.print(table)


@alerts.command("test")
@click.option("--days", "-d", type=DAYS, default=1, help="Number of days to analyze")
@click.pass_context
@handle_cli_errors
def alerts_test(ctx: click.Context, days: int) -> None:
    """Test alert rules against recent logs."""
    config_path = ctx.obj.get("config_path")

    client, settings = get_client(config_path)
    engine = AlertEngine(engine_rules(settings))

    err_console.print(f"[dim]Testing alert rules against last {days} day(s) of logs...[/dim]\n")

    query = build_date_range_query(days)

    with client:
        entries = client.get_all_logs(query)

    if not entries:
        console.print("[yellow]No audit logs found.[/yellow]")
        return

    # Check all entries
    fired = engine.check_batch(entries)

    if fired:
        console.print(f"[yellow bold]Found {len(fired)} alerts:[/yellow bold]\n")
        for fa in fired:
            console.print(fa.panel)
    else:
        console.print("[green]No alerts triggered.[/green]")

    # Also run anomaly detection
    anomalies = analyze_for_anomalies(entries)
    if anomalies:
        console.print(f"\n[yellow bold]Detected {len(anomalies)} anomalies:[/yellow bold]")
        for anomaly in anomalies:
            console.print(f"  [yellow]•[/yellow] {escape(str(anomaly['description']))}")


@cli.command()
@click.option("--yesterday", is_flag=True, help="Query yesterday's logs")
@click.option("--last-week", is_flag=True, help="Query last 7 days")
@click.option("--last-month", is_flag=True, help="Query last 30 days")
@click.option("--today", is_flag=True, help="Query today's logs")
@click.option("--user", "-u", help="Filter by user ID or email")
@click.option(
    "--action",
    "-a",
    multiple=True,
    help="Filter by action type",
)
@click.option(
    "--component",
    "-C",
    multiple=True,
    help="Filter by component type",
)
@click.option("--limit", "-l", type=POSITIVE_INT, default=100, help="Maximum entries to return")
@output_format_option
@click.option("--quiet", "-q", is_flag=True, help="Minimal output (for scripting)")
@click.pass_context
@handle_cli_errors
def query(
    ctx: click.Context,
    yesterday: bool,
    last_week: bool,
    last_month: bool,
    today: bool,
    user: str | None,
    action: tuple[str, ...],
    component: tuple[str, ...],
    limit: int,
    output_format: str,
    quiet: bool,
) -> None:
    """Query audit logs with date presets (--today, --yesterday, --last-week, --last-month)."""
    presets = {
        "yesterday": yesterday,
        "last_week": last_week,
        "last_month": last_month,
        "today": today,
    }
    chosen = [name for name, on in presets.items() if on]
    if len(chosen) > 1:
        names = ", ".join("--" + name.replace("_", "-") for name in chosen)
        raise click.UsageError(f"{names} are mutually exclusive; pick one.")
    date_preset = chosen[0] if chosen else None
    config_path = ctx.obj.get("config_path")

    client, settings = get_client(config_path)

    # Build date range from preset
    now = datetime.now(UTC)
    if date_preset == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = now
        label = "today"
    elif date_preset == "yesterday":
        day_before = now - timedelta(days=1)
        start = day_before.replace(hour=0, minute=0, second=0, microsecond=0)
        end = day_before.replace(hour=23, minute=59, second=59, microsecond=999999)
        label = "yesterday"
    elif date_preset == "last_week":
        start = now - timedelta(days=7)
        end = now
        label = "last 7 days"
    elif date_preset == "last_month":
        start = now - timedelta(days=30)
        end = now
        label = "last 30 days"
    else:
        start = now - timedelta(days=7)
        end = now
        label = "last 7 days"

    query_obj = AuditLogQuery(
        start_date=start,
        end_date=end,
        user_id=user,
        actions=parse_actions(action),
        components=parse_components(component),
        page_size=min(limit, 100),
    )

    if not quiet and output_format != "json":
        err_console.print(f"[dim]Querying {label}...[/dim]")

    with client:
        entries = client.get_all_logs(query_obj, max_entries=limit)

    if not entries:
        if output_format == "json":
            emit_json({"entries": [], "count": 0})
        elif not quiet:
            console.print("[dim]No audit logs found.[/dim]")
        return

    if output_format == "json":

        from .export import entry_to_dict
        data = {"entries": [entry_to_dict(e) for e in entries], "count": len(entries)}
        emit_json(data)
    else:
        table = format_logs_table(entries, show_details=False)
        console.print(table)
        if not quiet:
            console.print(f"\n[dim]Found {len(entries)} entries ({label})[/dim]")


@cli.command()
@days_option("Number of days to analyze")
@click.option(
    "--action",
    "-a",
    multiple=True,
    help="Filter by action type",
)
@click.option(
    "--component",
    "-C",
    multiple=True,
    help="Filter by component type",
)
@click.option("--user", "-u", help="Filter by user")
@output_format_option
@click.pass_context
@handle_cli_errors
def timeline(
    ctx: click.Context,
    days: int | None,
    action: tuple[str, ...],
    component: tuple[str, ...],
    user: str | None,
    output_format: str,
) -> None:
    """Show activity timeline visualization."""
    config_path = ctx.obj.get("config_path")

    client, settings = get_client(config_path)
    days = days_or_default(days, settings)

    query = build_date_range_query(days)
    query.actions = parse_actions(action)
    query.components = parse_components(component)
    query.user_id = user

    err_console.print(f"[dim]Loading activity for the last {days} days...[/dim]\n")

    with client:
        entries = client.get_all_logs(query)

    from .stats import get_daily_distribution, get_hourly_distribution

    if not entries:
        if output_format == "json":
            emit_json({"days": days, "daily": {}, "hourly": {f"{h:02d}": 0 for h in range(24)}})
        else:
            console.print("[dim]No audit logs found.[/dim]")
        return

    daily = get_daily_distribution(entries)
    hourly = get_hourly_distribution(entries)

    if output_format == "json":
        emit_json({
            "days": days,
            "daily": dict(sorted(daily.items())),
            "hourly": {f"{hour:02d}": hourly.get(hour, 0) for hour in range(24)},
        })
        return

    # Display daily activity
    console.print("[bold]Daily Activity[/bold]")
    if daily:
        max_count = max(daily.values()) if daily else 1
        for date, count in sorted(daily.items()):
            bar_len = int((count / max_count) * 40) if max_count > 0 else 0
            bar = "█" * bar_len
            console.print(f"  {date} │ {bar} {count}")
    console.print()

    # Display hourly distribution
    console.print("[bold]Hourly Distribution[/bold]")
    max_hourly = max(hourly.values()) if hourly else 1
    for hour in range(24):
        count = hourly.get(hour, 0)
        bar_len = int((count / max_hourly) * 30) if max_hourly > 0 else 0
        bar = "█" * bar_len
        console.print(f"  {hour:02d}:00 │ {bar} {count}")


@cli.command()
@click.option(
    "--action",
    "-a",
    required=True,
    type=click.Choice([a.value for a in ActionType], case_sensitive=False),
    help="Action type to find",
)
@days_option("Number of days to search")
@click.option("--limit", "-l", type=POSITIVE_INT, default=50, help="Maximum entries to show")
@output_format_option
@click.pass_context
@handle_cli_errors
def find_action(
    ctx: click.Context, action: str, days: int | None, limit: int, output_format: str
) -> None:
    """Find all occurrences of a specific action type."""
    config_path = ctx.obj.get("config_path")

    client, settings = get_client(config_path)
    days = days_or_default(days, settings)

    query = build_date_range_query(days)
    query.actions = [ActionType(action)]

    err_console.print(f"[dim]Searching for {action} actions in the last {days} days...[/dim]\n")

    with client:
        entries = client.get_all_logs(query, max_entries=limit)

    if output_format == "json":
        from .export import entry_to_dict

        emit_json({
            "action": action,
            "days": days,
            "entries": [entry_to_dict(e) for e in entries],
            "count": len(entries),
        })
        return

    if not entries:
        console.print(f"[dim]No {action} actions found.[/dim]")
        return

    table = format_logs_table(entries, show_details=True)
    console.print(table)
    console.print(f"\n[dim]Found {len(entries)} {action} actions[/dim]")


@cli.command()
@days_option("Number of days to analyze")
@click.option("--top", "-n", type=POSITIVE_INT, default=10, help="Number of top users to show")
@output_format_option
@click.pass_context
@handle_cli_errors
def top_users(ctx: click.Context, days: int | None, top: int, output_format: str) -> None:
    """Show most active users."""
    config_path = ctx.obj.get("config_path")

    client, settings = get_client(config_path)
    days = days_or_default(days, settings)

    query = build_date_range_query(days)

    err_console.print(f"[dim]Analyzing user activity for the last {days} days...[/dim]\n")

    with client:
        entries = client.get_all_logs(query)

    from .stats import get_user_activity

    users = get_user_activity(entries)[:top] if entries else []

    if output_format == "json":
        emit_json({
            "days": days,
            "users": [{"user": name, "count": count} for name, count in users],
        })
        return

    if not entries:
        console.print("[dim]No audit logs found.[/dim]")
        return

    user_table = format_user_stats_table(users)
    console.print(user_table)


@cli.command()
@click.argument("entry_id")
@click.option(
    "--max-entries",
    type=POSITIVE_INT,
    default=10_000,
    show_default=True,
    help="Newest entries to search before giving up",
)
@click.pass_context
@handle_cli_errors
def show(ctx: click.Context, entry_id: str, max_entries: int) -> None:
    """Show detailed information for a specific audit log entry."""
    config_path = ctx.obj.get("config_path")

    client, settings = get_client(config_path)

    # The API has no lookup by id, so page through the newest entries until it turns up.
    query = AuditLogQuery(page_size=MAX_PAGE_SIZE)

    with client:
        found_entry = None
        searched = 0
        for entry in islice(client.get_logs_paginated(query), max_entries):
            searched += 1
            if entry.id == entry_id:
                found_entry = entry
                break

    if not found_entry:
        err_console.print(f"[yellow]Entry not found: {escape(entry_id)}[/yellow]")
        err_console.print(
            f"[dim]Searched {searched:,} entries; "
            "raise --max-entries to look further back.[/dim]"
        )
        sys.exit(1)

    panel = format_single_entry(found_entry)
    console.print(panel)


# Convenience command to launch TUI explicitly
@main.command()
@click.pass_context
def tui(ctx: click.Context) -> None:
    """Launch the TUI interface (same as running without arguments)."""
    run_tui(ctx.obj.get("config_path"))


if __name__ == "__main__":
    main()
