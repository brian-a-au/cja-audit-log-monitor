#!/usr/bin/env python3
"""Make the README slideshow (docs/showcase.gif and docs/showcase.png).

Every slide is a screenshot of the real TUI, run headless with the synthetic data from
capture_screenshots.py. No Adobe API, credential or customer data is used. Needs Google
Chrome and FFmpeg on this computer.

Usage:
    uv run python scripts/make_showcase.py [--out docs]
"""

import argparse
import asyncio
import html
import importlib.util
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SIZE = (140, 42)  # terminal columns and rows, the same as docs/screenshots
SECONDS = 4  # how long each slide shows
FPS = 8
FRAME_WIDTH = 1786  # the 1726 pixel screenshot plus a 30 pixel margin on each side
FRAME_HEIGHT = 1200
GIF_WIDTH = 1200
ACCENT = "0x6db0d6"  # $primary in tui/styles.tcss
CHROME_PATHS = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "google-chrome",
    "chromium",
]

# (key presses, title, description). Each slide starts from the previous one.
SLIDES = [
    (["d"], "Dashboard", "Totals, actions and the most active users for the last 7 days."),
    (["l"], "Log browser", "Every entry, newest first, with filters and paging."),
    (["down", "down", "enter"], "Entry details", "Press enter to see every field of an entry."),
    (["escape", "m"], "Live monitor", "New events appear as they happen."),
    (["s"], "Statistics", "Actions, components, and activity by hour and by day."),
    (["a"], "Alerts", "Rules flag bulk deletes, bulk exports and activity at night."),
    (["question_mark"], "Keyboard shortcuts", "Press ? to see every key."),
]

FRAME = """<!doctype html>
<html><head><meta charset="utf-8"><style>
  html, body {{ margin: 0; background: #0f1115; }}
  body {{ width: {width}px; height: {height}px; box-sizing: border-box; padding: 30px;
         font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif; color: #c8ccd4; }}
  .head {{ display: flex; align-items: baseline; gap: 18px; height: 66px; }}
  .step {{ color: #6db0d6; font-size: 26px; font-weight: 600; }}
  .title {{ color: #e8e8e8; font-size: 34px; font-weight: 700; }}
  .desc {{ font-size: 26px; }}
  .shot svg {{ display: block; width: 1726px; height: auto; }}
</style></head><body>
  <div class="head">
    <span class="step">{step:02d} / {count:02d}</span>
    <span class="title">{title}</span>
    <span class="desc">{desc}</span>
  </div>
  <div class="shot">{svg}</div>
</body></html>
"""


def _load_capture():
    """Import capture_screenshots.py, which holds the synthetic data and the mocked client."""
    spec = importlib.util.spec_from_file_location(
        "capture_screenshots", ROOT / "scripts" / "capture_screenshots.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def chrome() -> str:
    """Path to Google Chrome or Chromium."""
    for path in CHROME_PATHS:
        if Path(path).exists() or shutil.which(path):
            return path
    raise RuntimeError("Google Chrome or Chromium is required")


async def capture_slides(work: Path) -> list[Path]:
    """Drive the app through SLIDES and save one SVG screenshot per slide."""
    from cja_audit_log_monitor.tui import CJAAuditApp

    capture = _load_capture()
    app = CJAAuditApp()
    capture.setup_mock_state(app, capture.generate_mock_entries(150))
    svgs = []
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause(delay=1.0)
        for i, (keys, _title, _desc) in enumerate(SLIDES):
            for key in keys:
                await pilot.press(key)
                await pilot.pause(delay=0.3)
            if "m" in keys:
                # Start a live session so the stream shows entries.
                app._screens["monitor"]._start_monitoring()
            await pilot.pause(delay=1.2)
            svg = work / f"slide{i}.svg"
            app.save_screenshot(str(svg))
            svgs.append(svg)
        app._screens["monitor"]._stop_monitoring()
    return svgs


def frame_html(i: int, svg: Path) -> str:
    """The slide for SLIDES[i]: a caption line above the screenshot."""
    _keys, title, desc = SLIDES[i]
    return FRAME.format(
        width=FRAME_WIDTH,
        height=FRAME_HEIGHT,
        step=i + 1,
        count=len(SLIDES),
        title=html.escape(title),
        desc=html.escape(desc),
        svg=svg.read_text(encoding="utf-8"),
    )


def screenshot(browser: str, page: Path, out: Path) -> None:
    """Save a PNG of ``page`` at the frame size."""
    cmd = [
        browser,
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        # Its own profile, so a Chrome that is already open does not get in the way.
        f"--user-data-dir={out.parent / 'profile'}",
        "--hide-scrollbars",
        "--force-device-scale-factor=1",
        f"--window-size={FRAME_WIDTH},{FRAME_HEIGHT}",
        # Time for the terminal font in the SVG to load from its CDN.
        "--virtual-time-budget=5000",
        f"--screenshot={out}",
        page.as_uri(),
    ]
    # Chrome sometimes fails to take a screenshot, e.g., while the screen is locked. Try again.
    for _ in range(3):
        done = subprocess.run(cmd, check=False, capture_output=True)
        if done.returncode == 0 and out.exists():
            return
    raise RuntimeError(f"Chrome could not take the screenshot {out.name} (exit {done.returncode})")


def make(out_dir: Path) -> None:
    """Write showcase.gif and showcase.png into ``out_dir``."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg is required")
    browser = chrome()
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="cja-showcase-") as tmp:
        work = Path(tmp)
        svgs = asyncio.run(capture_slides(work))
        stills = []
        for i, svg in enumerate(svgs):
            page = work / f"frame{i}.html"
            page.write_text(frame_html(i, svg), encoding="utf-8")
            still = work / f"frame{i}.png"
            screenshot(browser, page, still)
            stills.append(still)
        shutil.copyfile(stills[0], out_dir / "showcase.png")
        listing = work / "slides.txt"
        listing.write_text(
            "".join(f"file '{s}'\nduration {SECONDS}\n" for s in stills) + f"file '{stills[-1]}'\n",
            encoding="utf-8",
        )
        total = SECONDS * len(stills)
        # A thin progress line along the bottom edge, moving left to right over the loop.
        graph = (
            f"[0:v]fps={FPS},scale={GIF_WIDTH}:-1:flags=lanczos,format=rgb24[v];"
            f"color=c={ACCENT}:s={GIF_WIDTH}x3:r={FPS}[bar];"
            f"[v][bar]overlay=x='-{GIF_WIDTH}+{GIF_WIDTH}*t/{total}':y=H-3:shortest=1[o];"
            "[o]split[a][b];[a]palettegen=stats_mode=full[p];"
            "[b][p]paletteuse=dither=none:diff_mode=rectangle"
        )
        subprocess.run(
            [
                ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                "-f", "concat", "-safe", "0", "-i", str(listing),
                "-filter_complex", graph,
                "-t", str(total), "-loop", "0",
                str(out_dir / "showcase.gif"),
            ],
            check=True,
        )
    print(f"Wrote {out_dir / 'showcase.gif'} ({total}s) and {out_dir / 'showcase.png'}")


def main() -> None:
    """Parse arguments and make the slideshow."""
    # Show times in UTC, whatever the local zone of this computer is.
    os.environ["TZ"] = "UTC"
    time.tzset()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ROOT / "docs")
    make(parser.parse_args().out)


if __name__ == "__main__":
    main()
