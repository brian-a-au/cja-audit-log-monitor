#!/usr/bin/env python3
"""Capture screenshots of all TUI screens using Textual's screenshot feature."""

import asyncio
from pathlib import Path

from cja_audit.tui import CJAAuditApp


async def capture_screenshots():
    """Capture screenshots of all TUI screens."""
    output_dir = Path(__file__).parent.parent / "docs" / "screenshots"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Screen configurations: (key to press, filename)
    screens = [
        ("d", "dashboard.svg"),
        ("l", "log-browser.svg"),
        ("m", "monitor.svg"),
        ("s", "statistics.svg"),
        ("a", "alerts.svg"),
        ("c", "settings.svg"),
    ]

    app = CJAAuditApp()

    async with app.run_test(size=(120, 40)) as pilot:
        # Wait for app to fully mount
        await pilot.pause(delay=0.5)

        for key, filename in screens:
            # Navigate to screen
            await pilot.press(key)
            # Allow time for screen to fully render
            await pilot.pause(delay=0.5)

            # Save screenshot
            filepath = output_dir / filename
            app.save_screenshot(str(filepath))
            print(f"Captured: {filepath}")

    print(f"\nAll screenshots saved to: {output_dir}")


if __name__ == "__main__":
    asyncio.run(capture_screenshots())
