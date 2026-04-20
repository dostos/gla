"""Structural tests for the ``tests/eval-browser/r21_tile_id_overflow`` pilot.

These assert that the scenario has the files + markers the runner depends
on. They don't actually launch Chromium.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
SCENARIO_DIR = REPO_ROOT / "tests" / "eval-browser" / "r21_tile_id_overflow"


def test_r21_scenario_files_present():
    assert SCENARIO_DIR.is_dir(), f"scenario dir missing: {SCENARIO_DIR}"
    assert (SCENARIO_DIR / "index.html").exists()
    assert (SCENARIO_DIR / "scenario.md").exists()
    assert (SCENARIO_DIR / "README.md").exists()


def test_r21_scenario_md_has_required_sections():
    md = (SCENARIO_DIR / "scenario.md").read_text()
    # User Report / Ground Truth are the harness-parseable headers.
    assert re.search(r"^##\s+User Report", md, re.MULTILINE)
    assert re.search(r"^##\s+Ground Truth", md, re.MULTILINE)
    # Tier: browser (case-insensitive for the value).
    assert re.search(r"\*\*Tier:\*\*\s*browser", md, re.IGNORECASE)
    # Framework + API markers for harness dispatch.
    assert re.search(r"\*\*Framework:\*\*\s*mapbox-gl-js", md, re.IGNORECASE)
    assert re.search(r"\*\*API:\*\*\s*webgl", md, re.IGNORECASE)


class _HTMLProbe(HTMLParser):
    def __init__(self):
        super().__init__()
        self.has_script = False
        self.script_text = []
        self._in_script = False

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.has_script = True
            self._in_script = True

    def handle_endtag(self, tag):
        if tag == "script":
            self._in_script = False

    def handle_data(self, data):
        if self._in_script:
            self.script_text.append(data)


def test_r21_index_html_structure():
    html = (SCENARIO_DIR / "index.html").read_text()

    # Parses cleanly.
    probe = _HTMLProbe()
    probe.feed(html)
    assert probe.has_script, "expected a <script> tag in index.html"

    script = "\n".join(probe.script_text)

    # Reads token + port query params.
    assert "URLSearchParams" in script
    assert "token" in script
    assert "port" in script

    # Issues the expected fetch() POST to the engine.
    assert "fetch(" in script
    assert "/api/v1/frames/0/drawcalls/0/sources" in script
    assert "POST" in script

    # Sets the gpa_done sentinel.
    assert "__gpa_done" in script
    assert "true" in script.lower()


def test_r21_readme_marks_phase_1_stub():
    txt = (SCENARIO_DIR / "README.md").read_text().lower()
    assert "phase 1" in txt
    assert "phase 2" in txt
    assert "stub" in txt or "mvp" in txt
