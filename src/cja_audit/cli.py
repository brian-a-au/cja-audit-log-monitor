"""CLI commands for CJA Audit Log Monitor."""

import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.logging import RichHandler

from . import __version__
from .alerts import AlertEngine, analyze_for_anomalies
from .auth import AuthenticationError, TokenManager
from .client import APIError, AuditLogsClient
from .config import (
    CJASettings,
    create_default_config,
    get_config_path,
    load_config,
)
from .export import export_entries
from .formatters import (
    format_action_stats_table,
    format_logs_table,
    format_single_entry,
    format_stats_panel,
    format_user_stats_table,
    print_logs,
)
from .models import ActionType, AuditLogQuery, ComponentType
from .monitor import AuditLogMonitor
from .stats import build_date_range_query, calculate_stats, generate_report

console = Console()


def setup_logging(verbose: bool) -> None:
    """Configure logging based on verbosity."""
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[RichHandler(console=console, show_time=False, show_path=False)],
    )


def get_client(config_path: Path | None = None) -> tuple[AuditLogsClient, CJASettings]:
    """Create and return configured API client."""
    try:
        settings = load_config(config_path)
        token_manager = TokenManager(settings)
        client = AuditLogsClient(settings, token_manager)
        return client, settings
    except Exception as e:
        console.print(f"[red]Error loading configuration:[/red] {e}")
        sys.exit(1)


def parse_date(date_str: str | None) -> datetime | None:
    """Parse date string to datetime."""
    if not date_str:
        return None

    formats = [
        "%Y-%m-%d",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S",
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue

    raise click.BadParameter(f"Invalid date format: {date_str}")


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


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
@click.option(
    "--config",
    "-c",
    type=click.Path(exists=False, path_type=Path),
    help="Path to config file",
)
@click.version_option(version=__version__)
@click.pass_context
def main(ctx: click.Context, verbose: bool, config: Path | None) -> None:
    """CJA Audit Log Monitor - Query and analyze Adobe CJA audit logs."""
    setup_logging(verbose)
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    ctx.obj["config_path"] = config


@main.command()
@click.option("--limit", "-l", default=50, help="Maximum number of entries to show")
@click.option(
    "--component",
    "-t",
    multiple=True,
    help="Filter by component type (can specify multiple)",
)
@click.option("--details", "-d", is_flag=True, help="Show additional details")
@click.pass_context
def list(ctx: click.Context, limit: int, component: tuple[str, ...], details: bool) -> None:
    """List recent audit log entries."""
    config_path = ctx.obj.get("config_path")

    try:
        client, settings = get_client(config_path)

        query = AuditLogQuery(
            page_size=min(limit, 100),
            components=parse_components(component),
        )

        with client:
            entries = client.get_all_logs(query, max_entries=limit)

        if not entries:
            console.print("[dim]No audit logs found.[/dim]")
            return

        table = format_logs_table(entries, show_details=details)
        console.print(table)
        console.print(f"\n[dim]Showing {len(entries)} entries[/dim]")

    except AuthenticationError as e:
        console.print(f"[red]Authentication error:[/red] {e}")
        sys.exit(1)
    except APIError as e:
        console.print(f"[red]API error:[/red] {e}")
        sys.exit(1)


@main.command()
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
    "-t",
    multiple=True,
    help="Filter by component type",
)
@click.option("--component-id", help="Filter by specific component ID")
@click.option("--description", "-d", help="Search in description")
@click.option("--limit", "-l", default=100, help="Maximum entries to return")
@click.option("--details", is_flag=True, help="Show additional details")
@click.pass_context
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
) -> None:
    """Search audit logs with filters."""
    config_path = ctx.obj.get("config_path")

    try:
        client, settings = get_client(config_path)

        query = AuditLogQuery(
            user_id=user,
            actions=parse_actions(action),
            start_date=parse_date(start_date),
            end_date=parse_date(end_date),
            components=parse_components(component),
            component_id=component_id,
            description=description,
            page_size=min(limit, 100),
        )

        with client:
            entries = client.get_all_logs(query, max_entries=limit)

        if not entries:
            console.print("[dim]No matching audit logs found.[/dim]")
            return

        table = format_logs_table(entries, show_details=details)
        console.print(table)
        console.print(f"\n[dim]Found {len(entries)} matching entries[/dim]")

    except AuthenticationError as e:
        console.print(f"[red]Authentication error:[/red] {e}")
        sys.exit(1)
    except APIError as e:
        console.print(f"[red]API error:[/red] {e}")
        sys.exit(1)


@main.command()
@click.option("--dashboard-id", "-i", required=True, help="Dashboard/Project ID")
@click.option("--limit", "-l", default=100, help="Maximum entries to return")
@click.pass_context
def dashboard(ctx: click.Context, dashboard_id: str, limit: int) -> None:
    """Show all audit events for a specific dashboard/project."""
    config_path = ctx.obj.get("config_path")

    try:
        client, settings = get_client(config_path)

        with client:
            entries = client.get_component_logs(dashboard_id, "PROJECT")
            entries = entries[:limit]

        if not entries:
            console.print(f"[dim]No audit logs found for dashboard {dashboard_id}[/dim]")
            return

        console.print(f"[bold]Audit history for dashboard:[/bold] {dashboard_id}\n")
        table = format_logs_table(entries, show_details=True)
        console.print(table)
        console.print(f"\n[dim]Found {len(entries)} entries[/dim]")

    except AuthenticationError as e:
        console.print(f"[red]Authentication error:[/red] {e}")
        sys.exit(1)
    except APIError as e:
        console.print(f"[red]API error:[/red] {e}")
        sys.exit(1)


@main.command()
@click.option(
    "--format",
    "-f",
    type=click.Choice(["json", "csv"]),
    default="json",
    help="Export format",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    required=True,
    help="Output file path",
)
@click.option("--start-date", "-s", help="Start date (YYYY-MM-DD)")
@click.option("--end-date", "-e", help="End date (YYYY-MM-DD)")
@click.option("--days", "-d", default=7, help="Number of days (if no date range)")
@click.option(
    "--action",
    "-a",
    multiple=True,
    help="Filter by action type",
)
@click.option(
    "--component",
    "-t",
    multiple=True,
    help="Filter by component type",
)
@click.option("--pretty/--compact", default=True, help="Pretty print JSON")
@click.pass_context
def export(
    ctx: click.Context,
    format: str,
    output: Path,
    start_date: str | None,
    end_date: str | None,
    days: int,
    action: tuple[str, ...],
    component: tuple[str, ...],
    pretty: bool,
) -> None:
    """Export audit logs to file."""
    config_path = ctx.obj.get("config_path")

    try:
        client, settings = get_client(config_path)

        # Build query
        if start_date or end_date:
            query = AuditLogQuery(
                start_date=parse_date(start_date),
                end_date=parse_date(end_date),
                actions=parse_actions(action),
                components=parse_components(component),
            )
        else:
            query = build_date_range_query(days)
            query.actions = parse_actions(action)
            query.components = parse_components(component)

        console.print(f"[dim]Fetching audit logs...[/dim]")

        with client:
            entries = client.get_all_logs(query)

        if not entries:
            console.print("[yellow]No audit logs found to export.[/yellow]")
            return

        count = export_entries(entries, output, format=format, pretty=pretty)
        console.print(f"[green]Exported {count} entries to {output}[/green]")

    except AuthenticationError as e:
        console.print(f"[red]Authentication error:[/red] {e}")
        sys.exit(1)
    except APIError as e:
        console.print(f"[red]API error:[/red] {e}")
        sys.exit(1)


@main.command()
@click.option("--days", "-d", default=7, help="Number of days to analyze")
@click.option("--top", "-t", default=10, help="Number of top users to show")
@click.pass_context
def stats(ctx: click.Context, days: int, top: int) -> None:
    """Display summary statistics for audit logs."""
    config_path = ctx.obj.get("config_path")

    try:
        client, settings = get_client(config_path)

        query = build_date_range_query(days)
        console.print(f"[dim]Analyzing last {days} days of audit logs...[/dim]\n")

        with client:
            entries = client.get_all_logs(query)

        if not entries:
            console.print("[dim]No audit logs found for the specified period.[/dim]")
            return

        stats_data = calculate_stats(entries)

        # Show summary panel
        panel = format_stats_panel(stats_data, title=f"Audit Log Statistics (Last {days} Days)")
        console.print(panel)
        console.print()

        # Show user activity table
        if stats_data["top_users"]:
            user_table = format_user_stats_table(stats_data["top_users"][:top])
            console.print(user_table)
            console.print()

        # Show action distribution
        if stats_data["action_counts"]:
            action_table = format_action_stats_table(stats_data["action_counts"])
            console.print(action_table)

        # Check for anomalies
        anomalies = analyze_for_anomalies(entries)
        if anomalies:
            console.print("\n[yellow bold]Potential Anomalies Detected:[/yellow bold]")
            for anomaly in anomalies:
                console.print(f"  [yellow]•[/yellow] {anomaly['description']}")

    except AuthenticationError as e:
        console.print(f"[red]Authentication error:[/red] {e}")
        sys.exit(1)
    except APIError as e:
        console.print(f"[red]API error:[/red] {e}")
        sys.exit(1)


@main.command()
@click.option("--interval", "-i", default=60, help="Polling interval in seconds")
@click.option("--duration", "-d", type=int, help="Duration in seconds (default: indefinite)")
@click.option("--alerts/--no-alerts", default=True, help="Enable alert detection")
@click.pass_context
def monitor(
    ctx: click.Context,
    interval: int,
    duration: int | None,
    alerts: bool,
) -> None:
    """Monitor audit logs in real-time."""
    config_path = ctx.obj.get("config_path")

    try:
        client, settings = get_client(config_path)

        alert_engine = None
        if alerts:
            alert_engine = AlertEngine(settings.alert_rules or None)
            console.print(f"[dim]Alert detection enabled with {len(alert_engine.rules)} rules[/dim]")

        monitor = AuditLogMonitor(
            client,
            console=console,
            interval=interval,
            alert_engine=alert_engine,
        )

        monitor.start(duration=duration)

    except AuthenticationError as e:
        console.print(f"[red]Authentication error:[/red] {e}")
        sys.exit(1)
    except APIError as e:
        console.print(f"[red]API error:[/red] {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        console.print("\n[yellow]Monitor stopped.[/yellow]")


@main.command()
@click.pass_context
def init(ctx: click.Context) -> None:
    """Initialize configuration file."""
    config_path = ctx.obj.get("config_path") or get_config_path()

    if config_path.exists():
        if not click.confirm(f"Config file already exists at {config_path}. Overwrite?"):
            return

    create_default_config(config_path)
    console.print(f"[green]Created config file at:[/green] {config_path}")
    console.print("\n[dim]Set these environment variables for authentication:[/dim]")
    console.print("  CJA_CLIENT_ID=your_client_id")
    console.print("  CJA_CLIENT_SECRET=your_client_secret")
    console.print("  CJA_ORG_ID=your_org_id")
    console.print("\n[dim]Or add them to a .env file in your project directory.[/dim]")


@main.command()
@click.pass_context
def config(ctx: click.Context) -> None:
    """Show current configuration (without secrets)."""
    config_path = ctx.obj.get("config_path")

    try:
        settings = load_config(config_path)

        console.print("[bold]Current Configuration[/bold]\n")
        console.print(f"Config file: {get_config_path()}")
        console.print(f"API base URL: {settings.api_base_url}")
        console.print(f"IMS base URL: {settings.ims_base_url}")
        console.print(f"Default page size: {settings.default_page_size}")
        console.print(f"Default days: {settings.default_days}")
        console.print(f"Monitor interval: {settings.monitor_interval}s")
        console.print(f"OAuth configured: {settings.is_oauth_configured()}")
        console.print(f"JWT configured: {settings.is_jwt_configured()}")
        console.print(f"Org ID: {settings.org_id[:8]}..." if settings.org_id else "Org ID: (not set)")
        console.print(f"Client ID: {settings.client_id[:8]}..." if settings.client_id else "Client ID: (not set)")
        console.print(f"Alert rules: {len(settings.alert_rules)}")

    except Exception as e:
        console.print(f"[red]Error loading config:[/red] {e}")
        sys.exit(1)


@main.command()
@click.pass_context
def actions(ctx: click.Context) -> None:
    """List available action types."""
    console.print("[bold]Available Action Types[/bold]\n")
    for action in ActionType:
        console.print(f"  {action.value}")


@main.command()
@click.pass_context
def components(ctx: click.Context) -> None:
    """List available component types."""
    console.print("[bold]Available Component Types[/bold]\n")
    for component in ComponentType:
        console.print(f"  {component.value}")


if __name__ == "__main__":
    main()
