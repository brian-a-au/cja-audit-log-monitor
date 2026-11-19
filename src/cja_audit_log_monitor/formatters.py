"""Rich formatters for CLI output."""

import re
from datetime import datetime
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .models import ActionType, AuditLogEntry
from .utils import get_user_identifier, to_local

# Severity color tokens (matching tui/styles.tcss)
# - $danger:     destructive
# - $warning:    sensitive
# - $success:    safe
# - $text-muted: neutral / unknown

# tcss-token resolution rule:
# - Textual `Static.update` accepts tcss tokens (`[$success]…[/$success]`) natively.
# - Rich (used by the CLI and by `DataTable.default_cell_formatter`) does NOT.
# - For consistency and defense-in-depth, every markup string passed to either
#   path goes through `resolve_tcss_markup()` so callers don't have to remember
#   which renderer is downstream. The helper is a no-op on hex/named-color markup.

# Hex equivalents for tcss design tokens.
# Used to translate [$token] markup into Rich-parseable [#hex] markup.
TCSS_TOKEN_HEX: dict[str, str] = {
    "$danger": "#e07a7a",
    "$warning": "#e8c547",
    "$success": "#7fc896",
    "$text-muted": "#6e7480",
    "$text-strong": "#e8e8e8",
    "$text": "#c8ccd4",
    "$primary": "#6db0d6",
}


def resolve_tcss_markup(s: str) -> str:
    """Replace [$token] / [/$token] with hex equivalents so Rich can parse them."""
    out = s
    for token, hex_value in TCSS_TOKEN_HEX.items():
        # A backslash before the bracket marks escaped (literal) text: leave it alone.
        out = re.sub(rf"(?<!\\)\[{re.escape(token)}\]", f"[{hex_value}]", out)
        out = re.sub(rf"(?<!\\)\[/{re.escape(token)}\]", f"[/{hex_value}]", out)
    return out


def literal(text: str) -> str:
    """Make ``text`` safe to put inside a markup string so it shows exactly as written.

    ``textual.markup.escape`` misses an unclosed ``[/`` and a trailing backslash, either
    of which can swallow a later tag. Here every ``[`` is escaped, and a trailing backslash
    is followed by a zero-width space so it cannot escape the tag that comes after it.
    """
    out = text.replace("[", "\\[")
    return out + "\u200b" if out.endswith("\\") else out


ACTION_COLORS = {
    ActionType.DELETE.value: "$danger",
    ActionType.EMBARGO.value: "$danger",
    ActionType.EXPORT.value: "$warning",
    ActionType.SHARE.value: "$warning",
    ActionType.UNSHARE.value: "$warning",
    ActionType.TRANSFER.value: "$warning",
    ActionType.CREATE.value: "$success",
    ActionType.APPROVE.value: "$success",
    ActionType.EDIT.value: "$text-muted",
    ActionType.REFRESH.value: "$text-muted",
    ActionType.API_REQUEST.value: "$text-muted",
    ActionType.ORG_CHANGE.value: "$text-muted",
    ActionType.UNAPPROVE.value: "$text-muted",
}

ACTION_ICONS = {
    ActionType.DELETE.value: "✕",
    ActionType.EMBARGO.value: "✕",
    ActionType.EXPORT.value: "⚠",
    ActionType.SHARE.value: "⚠",
    ActionType.UNSHARE.value: "⚠",
    ActionType.TRANSFER.value: "⚠",
    ActionType.CREATE.value: "✓",
    ActionType.APPROVE.value: "✓",
    ActionType.EDIT.value: "·",
    ActionType.REFRESH.value: "·",
    ActionType.API_REQUEST.value: "·",
    ActionType.ORG_CHANGE.value: "·",
    ActionType.UNAPPROVE.value: "·",
}


_EIGHTHS = " ▏▎▍▌▋▊▉"


def render_bar(count: int, max_count: int, width: int) -> str:
    """Render a horizontal bar scaled to ``width`` cells, with eighth-cell precision.

    A nonzero count always renders at least ``▏`` so small values stay visible.
    """
    if max_count <= 0 or count <= 0:
        return ""
    cells = min(count / max_count, 1.0) * width
    full = int(cells)
    remainder = int((cells - full) * 8)
    bar = "█" * full + (_EIGHTHS[remainder] if remainder else "")
    return bar or "▏"


def get_action_color(action: str) -> str:
    """Get the action's severity color as a hex value, suitable for Rich and Textual.

    Rich (used by the CLI) does not understand Textual tcss variables, so we
    resolve the token to its hex value here. Textual's markup parser also
    accepts hex, so this works for both consumers.
    """
    token = ACTION_COLORS.get(action, "$text-muted")
    return TCSS_TOKEN_HEX.get(token, token)


def get_action_color_token(action: str) -> str:
    """Get the action's severity as a Textual tcss token (`$danger`, etc.)."""
    return ACTION_COLORS.get(action, "$text-muted")


def get_action_icon(action: str) -> str:
    """Get severity glyph for an action type."""
    return ACTION_ICONS.get(action, "·")


def format_timestamp(dt: datetime | None, local: bool = False) -> str:
    """Format timestamp for display, in local time when ``local`` is True."""
    if dt is None:
        return "-"
    if local:
        dt = to_local(dt)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def format_logs_table(
    entries: list[AuditLogEntry],
    console: Console | None = None,
    show_details: bool = False,
) -> Table:
    """Format audit log entries as a Rich table.

    Args:
        entries: List of audit log entries.
        console: Optional console for rendering.
        show_details: Whether to show additional columns.

    Returns:
        Rich Table object.
    """
    # Details add a text column, so padding is trimmed and the text columns get smaller
    # minimums to keep the whole table inside 80 columns.
    table = Table(
        title="Audit Logs",
        show_header=True,
        header_style="bold",
        show_lines=False,
        expand=True,
        padding=(0, 1, 0, 0) if show_details else (0, 1),
        pad_edge=not show_details,
    )

    # Core columns. Time and action never shrink or wrap; the text columns
    # give way (with an ellipsis) on narrow terminals.
    table.add_column("Time (UTC)", style="dim", no_wrap=True, min_width=19)
    table.add_column(
        "User", ratio=2, min_width=8 if show_details else 10, no_wrap=True, overflow="ellipsis"
    )
    table.add_column("Action", no_wrap=True, min_width=13)
    table.add_column(
        "Component",
        min_width=9 if show_details else 12,
        max_width=11 if show_details else 17,
        no_wrap=True,
        overflow="ellipsis",
    )
    table.add_column(
        "Name",
        ratio=3,
        min_width=6 if show_details else 8,
        no_wrap=True,
        overflow="ellipsis",
    )

    if show_details:
        # Free text folds onto more lines instead of widening the table; the IP rides
        # on the last line of the same cell so it keeps its place at 80 columns.
        table.add_column("Details", ratio=3, min_width=12, overflow="fold")

    for entry in entries:
        action_str = entry.action or "-"
        icon = get_action_icon(action_str)
        action_text = Text(f"{icon} {action_str}")
        action_text.stylize(get_action_color(action_str))

        row = [
            Text(format_timestamp(entry.timestamp)),
            Text(get_user_identifier(entry, default="-")),
            action_text,
            Text(entry.component_type or "-"),
            Text(entry.component_name or entry.component_id or "-"),
        ]

        if show_details:
            details = Text(entry.description or "-")
            if entry.ip_address:
                details.append(f"\nIP {entry.ip_address}", style="dim")
            row.append(details)

        table.add_row(*row)

    return table


def format_single_entry(entry: AuditLogEntry) -> Panel:
    """Format a single audit log entry as a detailed panel."""
    action_color = get_action_color(entry.action or "")

    icon = get_action_icon(entry.action or "")
    content = Text()
    content.append("Action: ", style="bold")
    content.append(f"{icon} {entry.action}\n", style=action_color)

    content.append("Timestamp: ", style="bold")
    content.append(f"{format_timestamp(entry.timestamp)} UTC\n")

    content.append("User: ", style="bold")
    content.append(f"{get_user_identifier(entry, default='-')}\n")

    content.append("Component Type: ", style="bold")
    content.append(f"{entry.component_type or '-'}\n")

    content.append("Component: ", style="bold")
    content.append(f"{entry.component_name or entry.component_id or '-'}\n")

    if entry.description:
        content.append("Description: ", style="bold")
        content.append(f"{entry.description}\n")

    if entry.ip_address:
        content.append("IP Address: ", style="bold")
        content.append(f"{entry.ip_address}\n")

    if entry.org_id:
        content.append("Org ID: ", style="bold")
        content.append(f"{entry.org_id}\n")

    title = Text()
    title.append(f"{entry.action}", style=action_color)
    title.append(f" - {entry.component_type}")
    return Panel(
        content,
        title=title,
        border_style=action_color,
    )


def format_stats_panel(
    stats: dict[str, Any],
    title: str = "Audit Log Statistics",
    include_top_users: bool = True,
) -> Panel:
    """Format statistics as a Rich panel.

    Set ``include_top_users`` to False when a user table is printed next to the panel.
    """
    content = Text()

    if "total_entries" in stats:
        content.append("Total Entries: ", style="bold")
        content.append(f"{stats['total_entries']:,}\n\n")

    if stats.get("date_range"):
        date_range = stats["date_range"]
        content.append("Date Range: ", style="bold")
        content.append(f"{date_range['start']} to {date_range['end']}\n\n")

    if include_top_users and "top_users" in stats:
        content.append("Top Users:\n", style="bold")
        for user, count in stats["top_users"][:5]:
            content.append(f"  {user}: {count:,}\n")
        content.append("\n")

    if "action_counts" in stats:
        content.append("Actions:\n", style="bold")
        for action, count in sorted(stats["action_counts"].items(), key=lambda x: -x[1]):
            color = get_action_color(action)
            content.append(f"  {action}: ", style=color)
            content.append(f"{count:,}\n")
        content.append("\n")

    if "component_counts" in stats:
        content.append("Components:\n", style="bold")
        for component, count in sorted(stats["component_counts"].items(), key=lambda x: -x[1])[:10]:
            content.append(f"  {component}: {count:,}\n")

    return Panel(content, title=Text(title), border_style="blue")


def format_user_stats_table(user_stats: list[tuple[str, int]]) -> Table:
    """Format user activity statistics as a table."""
    table = Table(
        title="Most Active Users",
        show_header=True,
        header_style="bold",
    )

    table.add_column("Rank", justify="right", width=6)
    table.add_column("User", width=40)
    table.add_column("Actions", justify="right", width=12)

    for rank, (user, count) in enumerate(user_stats, 1):
        table.add_row(str(rank), Text(user), f"{count:,}")

    return table


def format_action_stats_table(action_stats: dict[str, int]) -> Table:
    """Format action type statistics as a table."""
    table = Table(
        title="Action Distribution",
        show_header=True,
        header_style="bold",
    )

    table.add_column("Action", width=20)
    table.add_column("Count", justify="right", width=12)
    table.add_column("", width=30)  # Bar column

    total = sum(action_stats.values()) or 1
    max_count = max(action_stats.values()) if action_stats else 1

    for action, count in sorted(action_stats.items(), key=lambda x: -x[1]):
        color = get_action_color(action)
        icon = get_action_icon(action)
        pct = count / total * 100
        bar_width = int(count / max_count * 20)
        bar = "█" * bar_width

        action_text = Text(f"{icon} {action}", style=color)
        bar_text = Text(f"{bar} {pct:.1f}%", style=color)

        table.add_row(action_text, f"{count:,}", bar_text)

    return table


def format_alert(
    entry: AuditLogEntry,
    alert_name: str,
    message: str,
) -> Panel:
    """Format an alert notification."""
    content = Text()
    content.append(f"{message}\n\n", style="bold red")

    content.append("Time: ", style="bold")
    content.append(f"{format_timestamp(entry.timestamp)} UTC\n")

    content.append("User: ", style="bold")
    content.append(f"{get_user_identifier(entry)}\n")

    content.append("Action: ", style="bold")
    action_color = get_action_color(entry.action or "")
    action_icon = get_action_icon(entry.action or "")
    content.append(f"{action_icon} {entry.action}\n", style=action_color)

    content.append("Component: ", style="bold")
    content.append(f"{entry.component_type} - {entry.component_name or entry.component_id}\n")

    return Panel(
        content,
        title=Text(f"⚠️  ALERT: {alert_name}"),
        border_style="red",
    )


def print_logs(
    entries: list[AuditLogEntry],
    console: Console | None = None,
    show_details: bool = False,
) -> None:
    """Print audit logs to console."""
    if console is None:
        console = Console()

    if not entries:
        console.print("[dim]No audit logs found.[/dim]")
        return

    table = format_logs_table(entries, console, show_details)
    console.print(table)
    console.print(f"\n[dim]Showing {len(entries)} entries[/dim]")


def print_stats(stats: dict[str, Any], console: Console | None = None) -> None:
    """Print statistics to console."""
    if console is None:
        console = Console()

    panel = format_stats_panel(stats)
    console.print(panel)
