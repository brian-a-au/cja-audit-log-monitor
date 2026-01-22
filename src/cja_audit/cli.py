"""CLI commands for CJA Audit Log Monitor."""

import logging
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

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
                dt = dt.replace(tzinfo=UTC)
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


@click.group(invoke_without_command=True)
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
    """CJA Audit Log Monitor - Query and analyze Adobe CJA audit logs.

    Running without a subcommand launches the TUI interface.
    Use 'cja-audit cli <command>' for traditional CLI commands.
    """
    setup_logging(verbose)
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    ctx.obj["config_path"] = config

    # If no subcommand is given, launch the TUI
    if ctx.invoked_subcommand is None:
        from .tui import CJAAuditApp

        app = CJAAuditApp(config)
        app.run()


# CLI subcommand group for traditional CLI commands
@main.group()
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Traditional CLI commands for scripting and automation."""
    pass


@cli.command("list")
@click.option("--limit", "-l", default=50, help="Maximum number of entries to show")
@click.option(
    "--component",
    "-C",
    multiple=True,
    help="Filter by component type (can specify multiple)",
)
@click.option("--details", "-D", is_flag=True, help="Show additional details")
@click.option(
    "--output-format",
    "-F",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format",
)
@click.pass_context
def cli_list(
    ctx: click.Context,
    limit: int,
    component: tuple[str, ...],
    details: bool,
    output_format: str,
) -> None:
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
            if output_format == "json":
                import json
                console.print(json.dumps({"entries": [], "count": 0}))
            else:
                console.print("[dim]No audit logs found.[/dim]")
            return

        if output_format == "json":
            import json

            from .export import entry_to_dict
            data = {"entries": [entry_to_dict(e) for e in entries], "count": len(entries)}
            console.print(json.dumps(data, indent=2, default=str))
        else:
            table = format_logs_table(entries, show_details=details)
            console.print(table)
            console.print(f"\n[dim]Showing {len(entries)} entries[/dim]")

    except AuthenticationError as e:
        console.print(f"[red]Authentication error:[/red] {e}")
        sys.exit(1)
    except APIError as e:
        console.print(f"[red]API error:[/red] {e}")
        sys.exit(1)


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
@click.option("--limit", "-l", default=100, help="Maximum entries to return")
@click.option("--details", is_flag=True, help="Show additional details")
@click.option(
    "--output-format",
    "-F",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format",
)
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
    output_format: str,
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
            if output_format == "json":
                import json
                console.print(json.dumps({"entries": [], "count": 0}))
            else:
                console.print("[dim]No matching audit logs found.[/dim]")
            return

        if output_format == "json":
            import json

            from .export import entry_to_dict
            data = {"entries": [entry_to_dict(e) for e in entries], "count": len(entries)}
            console.print(json.dumps(data, indent=2, default=str))
        else:
            table = format_logs_table(entries, show_details=details)
            console.print(table)
            console.print(f"\n[dim]Found {len(entries)} matching entries[/dim]")

    except AuthenticationError as e:
        console.print(f"[red]Authentication error:[/red] {e}")
        sys.exit(1)
    except APIError as e:
        console.print(f"[red]API error:[/red] {e}")
        sys.exit(1)


@cli.command()
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


@cli.command()
@click.option("--user-id", "-u", required=True, help="User ID or email address")
@click.option("--days", "-d", default=7, help="Number of days to query")
@click.option("--limit", "-l", default=100, help="Maximum entries to return")
@click.option(
    "--output-format",
    "-F",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format",
)
@click.pass_context
def user(ctx: click.Context, user_id: str, days: int, limit: int, output_format: str) -> None:
    """Show all audit events for a specific user."""
    config_path = ctx.obj.get("config_path")

    try:
        client, settings = get_client(config_path)

        query = build_date_range_query(days)
        query.user_id = user_id

        with client:
            entries = client.get_all_logs(query, max_entries=limit)

        if not entries:
            if output_format == "json":
                import json
                console.print(json.dumps({"user": user_id, "entries": [], "count": 0}))
            else:
                console.print(f"[dim]No audit logs found for user {user_id}[/dim]")
            return

        if output_format == "json":
            import json

            from .export import entry_to_dict
            data = {
                "user": user_id,
                "entries": [entry_to_dict(e) for e in entries],
                "count": len(entries),
            }
            console.print(json.dumps(data, indent=2, default=str))
        else:
            console.print(f"[bold]Audit history for user:[/bold] {user_id}\n")
            table = format_logs_table(entries, show_details=True)
            console.print(table)
            console.print(f"\n[dim]Found {len(entries)} entries[/dim]")

    except AuthenticationError as e:
        console.print(f"[red]Authentication error:[/red] {e}")
        sys.exit(1)
    except APIError as e:
        console.print(f"[red]API error:[/red] {e}")
        sys.exit(1)


@cli.command()
@click.option("--id", "-i", "component_id", required=True, help="Component ID")
@click.option(
    "--type",
    "-t",
    "component_type",
    type=click.Choice([c.value for c in ComponentType]),
    help="Component type (optional)",
)
@click.option("--limit", "-l", default=100, help="Maximum entries to return")
@click.option(
    "--output-format",
    "-F",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format",
)
@click.pass_context
def component(
    ctx: click.Context,
    component_id: str,
    component_type: str | None,
    limit: int,
    output_format: str,
) -> None:
    """Show all audit events for a specific component."""
    config_path = ctx.obj.get("config_path")

    try:
        client, settings = get_client(config_path)

        with client:
            entries = client.get_component_logs(component_id, component_type)
            entries = entries[:limit]

        if not entries:
            if output_format == "json":
                import json
                console.print(json.dumps({
                    "component_id": component_id,
                    "component_type": component_type,
                    "entries": [],
                    "count": 0,
                }))
            else:
                console.print(f"[dim]No audit logs found for component {component_id}[/dim]")
            return

        if output_format == "json":
            import json

            from .export import entry_to_dict
            data = {
                "component_id": component_id,
                "component_type": component_type,
                "entries": [entry_to_dict(e) for e in entries],
                "count": len(entries),
            }
            console.print(json.dumps(data, indent=2, default=str))
        else:
            type_str = f" ({component_type})" if component_type else ""
            console.print(f"[bold]Audit history for component:[/bold] {component_id}{type_str}\n")
            table = format_logs_table(entries, show_details=True)
            console.print(table)
            console.print(f"\n[dim]Found {len(entries)} entries[/dim]")

    except AuthenticationError as e:
        console.print(f"[red]Authentication error:[/red] {e}")
        sys.exit(1)
    except APIError as e:
        console.print(f"[red]API error:[/red] {e}")
        sys.exit(1)


@cli.command()
@click.option(
    "--format",
    "-f",
    type=click.Choice(["json", "csv", "tsv"]),
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
    "-C",
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

        console.print("[dim]Fetching audit logs...[/dim]")

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


@cli.command()
@click.option("--days", "-d", default=7, help="Number of days to analyze")
@click.option("--top", "-t", default=10, help="Number of top users to show")
@click.option(
    "--output-format",
    "-F",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format",
)
@click.pass_context
def stats(ctx: click.Context, days: int, top: int, output_format: str) -> None:
    """Display summary statistics for audit logs."""
    config_path = ctx.obj.get("config_path")

    try:
        client, settings = get_client(config_path)

        query = build_date_range_query(days)
        if output_format != "json":
            console.print(f"[dim]Analyzing last {days} days of audit logs...[/dim]\n")

        with client:
            entries = client.get_all_logs(query)

        if not entries:
            if output_format == "json":
                import json
                console.print(json.dumps({"statistics": {}, "anomalies": []}))
            else:
                console.print("[dim]No audit logs found for the specified period.[/dim]")
            return

        stats_data = calculate_stats(entries)
        anomalies = analyze_for_anomalies(entries)

        if output_format == "json":
            import json
            data = {
                "days": days,
                "statistics": stats_data,
                "anomalies": anomalies,
            }
            console.print(json.dumps(data, indent=2, default=str))
        else:
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


@cli.command()
@click.option("--interval", "-i", default=60, help="Polling interval in seconds")
@click.option("--duration", "-D", type=int, help="Duration in seconds (default: indefinite)")
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
            rule_count = len(alert_engine.rules)
            console.print(f"[dim]Alert detection enabled with {rule_count} rules[/dim]")

        monitor_instance = AuditLogMonitor(
            client,
            console=console,
            interval=interval,
            alert_engine=alert_engine,
        )

        monitor_instance.start(duration=duration)

    except AuthenticationError as e:
        console.print(f"[red]Authentication error:[/red] {e}")
        sys.exit(1)
    except APIError as e:
        console.print(f"[red]API error:[/red] {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        console.print("\n[yellow]Monitor stopped.[/yellow]")


@cli.command()
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


@cli.command()
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
        org_display = f"{settings.org_id[:8]}..." if settings.org_id else "(not set)"
        client_display = f"{settings.client_id[:8]}..." if settings.client_id else "(not set)"
        console.print(f"Org ID: {org_display}")
        console.print(f"Client ID: {client_display}")
        console.print(f"Alert rules: {len(settings.alert_rules)}")

    except Exception as e:
        console.print(f"[red]Error loading config:[/red] {e}")
        sys.exit(1)


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
@click.option(
    "--output-format",
    "-F",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format",
)
@click.pass_context
def verify(ctx: click.Context, output_format: str) -> None:
    """Verify API connection and authentication."""
    config_path = ctx.obj.get("config_path")

    try:
        client, settings = get_client(config_path)

        if output_format != "json":
            console.print("[dim]Verifying connection...[/dim]\n")

        with client:
            result = client.verify_connection()

        if output_format == "json":
            import json
            console.print(json.dumps(result, indent=2, default=str))
        else:
            if result["connected"] and result["authenticated"]:
                console.print("[green]✓[/green] Connection successful")
                console.print(f"  Organization: {result['org_id']}")
                console.print(f"  API URL: {result['api_url']}")
                total_logs = result.get('total_logs_available', 'N/A')
                console.print(f"  Total logs available: {total_logs}")
            else:
                console.print("[red]✗[/red] Connection failed")
                if result["error"]:
                    console.print(f"  Error: {result['error']}")

    except AuthenticationError as e:
        if output_format == "json":
            import json
            console.print(json.dumps({"connected": False, "error": str(e)}))
        else:
            console.print(f"[red]✗[/red] Authentication failed: {e}")
        sys.exit(1)
    except APIError as e:
        if output_format == "json":
            import json
            console.print(json.dumps({"connected": False, "error": str(e)}))
        else:
            console.print(f"[red]✗[/red] API error: {e}")
        sys.exit(1)


@cli.command()
@click.option("--days", "-d", default=7, help="Number of days to analyze")
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    help="Output file path (default: stdout)",
)
@click.option("--pretty/--compact", default=True, help="Pretty print JSON")
@click.pass_context
def report(ctx: click.Context, days: int, output: Path | None, pretty: bool) -> None:
    """Generate a comprehensive audit log report."""
    config_path = ctx.obj.get("config_path")

    try:
        client, settings = get_client(config_path)

        console.print(f"[dim]Generating report for the last {days} days...[/dim]\n")

        query = build_date_range_query(days)

        with client:
            entries = client.get_all_logs(query)

        if not entries:
            console.print("[yellow]No audit logs found for the specified period.[/yellow]")
            return

        report_data = generate_report(entries)
        report_data["generated_at"] = datetime.now(UTC).isoformat()
        report_data["days_analyzed"] = days
        report_data["anomalies"] = analyze_for_anomalies(entries)

        import json
        indent = 2 if pretty else None
        json_output = json.dumps(report_data, indent=indent, default=str)

        if output:
            output.write_text(json_output)
            console.print(f"[green]Report saved to {output}[/green]")
        else:
            console.print(json_output)

    except AuthenticationError as e:
        console.print(f"[red]Authentication error:[/red] {e}")
        sys.exit(1)
    except APIError as e:
        console.print(f"[red]API error:[/red] {e}")
        sys.exit(1)


@cli.command()
@click.option("--interval", "-i", default=5, help="Polling interval in seconds")
@click.option("--user", "-u", help="Filter by user ID or email")
@click.option("--component-id", "-c", help="Filter by component ID")
@click.option(
    "--action",
    "-a",
    multiple=True,
    help="Filter by action type (can specify multiple)",
)
@click.option("--alerts/--no-alerts", default=True, help="Enable alert detection")
@click.pass_context
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
            alert_engine = AlertEngine(settings.alert_rules or None)

        monitor_instance = AuditLogMonitor(
            client,
            console=console,
            interval=interval,
            alert_engine=alert_engine,
        )

        # Set up filters
        actions_filter = parse_actions(action) if action else None

        # Override get_new_entries to apply filters
        original_get_new = monitor_instance._get_new_entries

        def filtered_get_new() -> list:
            entries = original_get_new()
            filtered = entries

            if user:
                from .utils import get_user_identifier
                filtered = [
                    e for e in filtered
                    if e.user_id == user or e.user_email == user
                    or get_user_identifier(e) == user
                ]

            if component_id:
                filtered = [e for e in filtered if e.component_id == component_id]

            if actions_filter:
                filtered = [
                    e for e in filtered
                    if e.action and ActionType(e.action) in actions_filter
                ]

            return filtered

        monitor_instance._get_new_entries = filtered_get_new  # type: ignore

        filters_desc = []
        if user:
            filters_desc.append(f"user={user}")
        if component_id:
            filters_desc.append(f"component={component_id}")
        if action:
            filters_desc.append(f"actions={','.join(action)}")

        filter_str = f" [dim]({', '.join(filters_desc)})[/dim]" if filters_desc else ""

        console.print(f"[green]Tailing audit logs{filter_str}[/green]")
        console.print(f"[dim]Polling every {interval}s, Ctrl+C to stop[/dim]\n")

        monitor_instance.start()

    except AuthenticationError as e:
        console.print(f"[red]Authentication error:[/red] {e}")
        sys.exit(1)
    except APIError as e:
        console.print(f"[red]API error:[/red] {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        console.print("\n[yellow]Stopped.[/yellow]")


# Alert rules subcommand group under cli
@cli.group()
@click.pass_context
def alerts(ctx: click.Context) -> None:
    """Manage alert rules."""
    pass


@alerts.command("list")
@click.option(
    "--output-format",
    "-F",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format",
)
@click.pass_context
def alerts_list(ctx: click.Context, output_format: str) -> None:
    """List all alert rules."""
    config_path = ctx.obj.get("config_path")

    try:
        settings = load_config(config_path)
        engine = AlertEngine(settings.alert_rules or None)
        rules_status = engine.get_rule_status()

        if output_format == "json":
            import json
            console.print(json.dumps(rules_status, indent=2))
        else:
            from rich.table import Table

            table = Table(title="Alert Rules")
            table.add_column("Name", style="cyan")
            table.add_column("Description")
            table.add_column("Enabled", justify="center")
            table.add_column("Threshold", justify="right")
            table.add_column("Window", justify="right")
            table.add_column("Actions")
            table.add_column("Components")

            for rule in rules_status:
                enabled = "[green]✓[/green]" if rule["enabled"] else "[red]✗[/red]"
                rule_actions = ", ".join(rule["actions"]) if rule["actions"] else "-"
                rule_components = ", ".join(rule["components"][:2]) if rule["components"] else "-"
                if rule["components"] and len(rule["components"]) > 2:
                    rule_components += f" +{len(rule['components']) - 2}"

                table.add_row(
                    rule["name"],
                    rule["description"] or "-",
                    enabled,
                    str(rule["threshold_count"]),
                    f"{rule['threshold_window_minutes']}m",
                    rule_actions,
                    rule_components,
                )

            console.print(table)

    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


@alerts.command("test")
@click.option("--days", "-d", default=1, help="Number of days to analyze")
@click.pass_context
def alerts_test(ctx: click.Context, days: int) -> None:
    """Test alert rules against recent logs."""
    config_path = ctx.obj.get("config_path")

    try:
        client, settings = get_client(config_path)
        engine = AlertEngine(settings.alert_rules or None)

        console.print(f"[dim]Testing alert rules against last {days} day(s) of logs...[/dim]\n")

        query = build_date_range_query(days)

        with client:
            entries = client.get_all_logs(query)

        if not entries:
            console.print("[yellow]No audit logs found.[/yellow]")
            return

        # Check all entries
        alert_panels = engine.check_batch(entries)

        if alert_panels:
            console.print(f"[yellow bold]Found {len(alert_panels)} alerts:[/yellow bold]\n")
            for panel in alert_panels:
                console.print(panel)
        else:
            console.print("[green]No alerts triggered.[/green]")

        # Also run anomaly detection
        anomalies = analyze_for_anomalies(entries)
        if anomalies:
            console.print(f"\n[yellow bold]Detected {len(anomalies)} anomalies:[/yellow bold]")
            for anomaly in anomalies:
                console.print(f"  [yellow]•[/yellow] {anomaly['description']}")

    except AuthenticationError as e:
        console.print(f"[red]Authentication error:[/red] {e}")
        sys.exit(1)
    except APIError as e:
        console.print(f"[red]API error:[/red] {e}")
        sys.exit(1)


@cli.command()
@click.option("--yesterday", "date_preset", flag_value="yesterday", help="Query yesterday's logs")
@click.option("--last-week", "date_preset", flag_value="last_week", help="Query last 7 days")
@click.option("--last-month", "date_preset", flag_value="last_month", help="Query last 30 days")
@click.option("--today", "date_preset", flag_value="today", help="Query today's logs")
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
@click.option("--limit", "-l", default=100, help="Maximum entries to return")
@click.option(
    "--output-format",
    "-F",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format",
)
@click.option("--quiet", "-q", is_flag=True, help="Minimal output (for scripting)")
@click.pass_context
def query(
    ctx: click.Context,
    date_preset: str | None,
    user: str | None,
    action: tuple[str, ...],
    component: tuple[str, ...],
    limit: int,
    output_format: str,
    quiet: bool,
) -> None:
    """Query audit logs with date presets."""
    config_path = ctx.obj.get("config_path")

    try:
        client, settings = get_client(config_path)

        # Build date range from preset
        now = datetime.now(UTC)
        if date_preset == "today":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = now
            label = "today"
        elif date_preset == "yesterday":
            yesterday = now - timedelta(days=1)
            start = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
            end = yesterday.replace(hour=23, minute=59, second=59, microsecond=999999)
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
            console.print(f"[dim]Querying {label}...[/dim]")

        with client:
            entries = client.get_all_logs(query_obj, max_entries=limit)

        if not entries:
            if output_format == "json":
                import json
                console.print(json.dumps({"entries": [], "count": 0}))
            elif not quiet:
                console.print("[dim]No audit logs found.[/dim]")
            return

        if output_format == "json":
            import json

            from .export import entry_to_dict
            data = {"entries": [entry_to_dict(e) for e in entries], "count": len(entries)}
            console.print(json.dumps(data, indent=2, default=str))
        else:
            table = format_logs_table(entries, show_details=False)
            console.print(table)
            if not quiet:
                console.print(f"\n[dim]Found {len(entries)} entries ({label})[/dim]")

    except AuthenticationError as e:
        console.print(f"[red]Authentication error:[/red] {e}")
        sys.exit(1)
    except APIError as e:
        console.print(f"[red]API error:[/red] {e}")
        sys.exit(1)


@cli.command()
@click.option("--days", "-d", default=7, help="Number of days to analyze")
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
@click.pass_context
def timeline(
    ctx: click.Context,
    days: int,
    action: tuple[str, ...],
    component: tuple[str, ...],
    user: str | None,
) -> None:
    """Show activity timeline visualization."""
    config_path = ctx.obj.get("config_path")

    try:
        client, settings = get_client(config_path)

        query = build_date_range_query(days)
        query.actions = parse_actions(action)
        query.components = parse_components(component)
        query.user_id = user

        console.print(f"[dim]Loading activity for the last {days} days...[/dim]\n")

        with client:
            entries = client.get_all_logs(query)

        if not entries:
            console.print("[dim]No audit logs found.[/dim]")
            return

        from .stats import get_daily_distribution, get_hourly_distribution

        daily = get_daily_distribution(entries)
        hourly = get_hourly_distribution(entries)

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

    except AuthenticationError as e:
        console.print(f"[red]Authentication error:[/red] {e}")
        sys.exit(1)
    except APIError as e:
        console.print(f"[red]API error:[/red] {e}")
        sys.exit(1)


@cli.command()
@click.option(
    "--action",
    "-a",
    required=True,
    type=click.Choice([a.value for a in ActionType]),
    help="Action type to find",
)
@click.option("--days", "-d", default=7, help="Number of days to search")
@click.option("--limit", "-l", default=50, help="Maximum entries to show")
@click.pass_context
def find_action(ctx: click.Context, action: str, days: int, limit: int) -> None:
    """Find all occurrences of a specific action type."""
    config_path = ctx.obj.get("config_path")

    try:
        client, settings = get_client(config_path)

        query = build_date_range_query(days)
        query.actions = [ActionType(action)]

        console.print(f"[dim]Searching for {action} actions in the last {days} days...[/dim]\n")

        with client:
            entries = client.get_all_logs(query, max_entries=limit)

        if not entries:
            console.print(f"[dim]No {action} actions found.[/dim]")
            return

        table = format_logs_table(entries, show_details=True)
        console.print(table)
        console.print(f"\n[dim]Found {len(entries)} {action} actions[/dim]")

    except AuthenticationError as e:
        console.print(f"[red]Authentication error:[/red] {e}")
        sys.exit(1)
    except APIError as e:
        console.print(f"[red]API error:[/red] {e}")
        sys.exit(1)


@cli.command()
@click.option("--days", "-d", default=7, help="Number of days to analyze")
@click.option("--top", "-t", default=10, help="Number of top items to show")
@click.pass_context
def top_users(ctx: click.Context, days: int, top: int) -> None:
    """Show most active users."""
    config_path = ctx.obj.get("config_path")

    try:
        client, settings = get_client(config_path)

        query = build_date_range_query(days)

        console.print(f"[dim]Analyzing user activity for the last {days} days...[/dim]\n")

        with client:
            entries = client.get_all_logs(query)

        if not entries:
            console.print("[dim]No audit logs found.[/dim]")
            return

        from .stats import get_user_activity

        users = get_user_activity(entries)[:top]

        user_table = format_user_stats_table(users)
        console.print(user_table)

    except AuthenticationError as e:
        console.print(f"[red]Authentication error:[/red] {e}")
        sys.exit(1)
    except APIError as e:
        console.print(f"[red]API error:[/red] {e}")
        sys.exit(1)


@cli.command()
@click.argument("entry_id")
@click.pass_context
def show(ctx: click.Context, entry_id: str) -> None:
    """Show detailed information for a specific audit log entry."""
    config_path = ctx.obj.get("config_path")

    try:
        client, settings = get_client(config_path)

        # Search for the entry by ID
        query = AuditLogQuery(page_size=100)

        with client:
            # We need to search through logs to find the entry
            found_entry = None
            for entry in client.get_logs_paginated(query, max_pages=10):
                if entry.id == entry_id:
                    found_entry = entry
                    break

        if not found_entry:
            console.print(f"[yellow]Entry not found: {entry_id}[/yellow]")
            console.print("[dim]Note: Only recent entries can be found this way.[/dim]")
            return

        panel = format_single_entry(found_entry)
        console.print(panel)

    except AuthenticationError as e:
        console.print(f"[red]Authentication error:[/red] {e}")
        sys.exit(1)
    except APIError as e:
        console.print(f"[red]API error:[/red] {e}")
        sys.exit(1)


# Convenience command to launch TUI explicitly
@main.command()
@click.pass_context
def tui(ctx: click.Context) -> None:
    """Launch the TUI interface (same as running without arguments)."""
    from .tui import CJAAuditApp

    config_path = ctx.obj.get("config_path")
    app = CJAAuditApp(config_path)
    app.run()


if __name__ == "__main__":
    main()
