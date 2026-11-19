"""The README slideshow from scripts/make_showcase.py still captures every slide.

The slideshow breaks without notice when a key press no longer reaches the view a slide
expects. These tests drive the app through the slides and check what each one shows. They
skip Chrome and FFmpeg, which only turn the screenshots into the GIF.
"""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "make_showcase.py"

pytestmark = pytest.mark.skipif(not SCRIPT.exists(), reason="scripts/ is not in the sdist")

# Text that only the intended view shows, one per slide in make_showcase.SLIDES.
EXPECTED = [
    "ACTION DISTRIBUTION",
    "page 1 of 2",
    "component name",
    "LIVE LOG STREAM",
    "USER RANKING",
    "bulk_delete",
    "keyboard shortcuts",
]


def _load():
    spec = importlib.util.spec_from_file_location("make_showcase", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_every_slide_shows_its_view(tmp_path):
    showcase = _load()
    svgs = await showcase.capture_slides(tmp_path)
    assert len(svgs) == len(showcase.SLIDES) == len(EXPECTED)
    for svg, text in zip(svgs, EXPECTED, strict=True):
        # Rich writes spaces in an SVG screenshot as non-breaking spaces.
        content = svg.read_text(encoding="utf-8").replace("&#160;", " ")
        assert text in content, f"{svg.name} does not show {text!r}"


def test_frame_has_caption_and_screenshot(tmp_path):
    showcase = _load()
    svg = tmp_path / "slide.svg"
    svg.write_text("<svg><text>hello</text></svg>", encoding="utf-8")
    page = showcase.frame_html(0, svg)
    assert "01 / 07" in page
    assert showcase.SLIDES[0][1] in page
    assert "<svg><text>hello</text></svg>" in page
