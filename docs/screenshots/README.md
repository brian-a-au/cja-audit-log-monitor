# TUI Screenshots

This directory contains SVG screenshots of the CJA Audit Log Monitor TUI application, captured using Textual's built-in screenshot feature.

## Screenshots

| File | Screen | Shortcut |
|------|--------|----------|
| `dashboard.svg` | Dashboard | `d` |
| `log-browser.svg` | Log Browser | `l` |
| `monitor.svg` | Real-Time Monitor | `m` |
| `statistics.svg` | Statistics | `s` |
| `alerts.svg` | Alert Rules | `a` |
| `settings.svg` | Settings | `c` |

## Regenerating Screenshots

To regenerate all screenshots, run:

```bash
uv run python scripts/capture_screenshots.py            # 140x42, into docs/screenshots
uv run python scripts/capture_screenshots.py --size 100x30 --out /tmp/shots
```

This runs the real app headless (Textual's test mode) with only the API client mocked, so each SVG shows what a user actually sees.
