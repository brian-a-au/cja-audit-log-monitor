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
python scripts/capture_screenshots.py
```

This uses Textual's test mode to capture SVG screenshots of each screen.
