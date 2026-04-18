"""Stack Overflow discovery + fetch helpers.

Uses the Stack Exchange API at stackoverflow.com. Anonymous requests are
limited to ~300/day which is sufficient for our batch sizes. If rate
limiting becomes an issue, register for a Stack Apps API key and set
STACKAPPS_API_KEY env var.
"""
from __future__ import annotations

import html
import json
import os
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Optional


@dataclass
class SOQuestion:
    """A Stack Overflow question with enough metadata for the pipeline."""
    url: str          # e.g. "https://stackoverflow.com/questions/12345/title"
    title: str
    body_html: str    # raw HTML from SO (we'll strip tags for the LLM)
    tags: list[str]
    accepted_answer_id: Optional[int]
    creation_date: str   # ISO-8601


_API_BASE = "https://api.stackexchange.com/2.3"


def _http_get_json(url: str, timeout: int = 30) -> Optional[dict]:
    """GET a JSON endpoint; return parsed dict or None on failure."""
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def search_questions(tags: list[str], per_page: int = 30,
                     accepted_only: bool = True,
                     sort: str = "votes") -> list[SOQuestion]:
    """Search SO questions matching ALL given tags.

    Returns a list of SOQuestion. Empty list on API failure.
    """
    params = {
        "order": "desc",
        "sort": sort,
        "tagged": ";".join(tags),
        "site": "stackoverflow",
        "pagesize": str(per_page),
        "filter": "withbody",  # withbody + accepted answer info
    }
    if accepted_only:
        params["accepted"] = "True"

    key = os.environ.get("STACKAPPS_API_KEY")
    if key:
        params["key"] = key

    url = f"{_API_BASE}/search/advanced?" + urllib.parse.urlencode(params)
    data = _http_get_json(url)
    if not data:
        return []

    out: list[SOQuestion] = []
    for item in data.get("items", []):
        out.append(SOQuestion(
            url=item.get("link", ""),
            title=html.unescape(item.get("title", "")),
            body_html=item.get("body", "") or "",
            tags=item.get("tags") or [],
            accepted_answer_id=item.get("accepted_answer_id"),
            creation_date=_unix_to_iso(item.get("creation_date", 0)),
        ))
    return out


def fetch_stackoverflow_thread(url: str):
    """Fetch an SO question + its accepted answer as an IssueThread.

    Returns an IssueThread where:
    - body is the question's body (HTML-stripped)
    - comments[] contains the accepted answer's body (stripped) prefixed
      with "=== Accepted Answer (score: N) ==="

    Raises ValueError if the URL is not an SO question URL.
    """
    # Lazy import to avoid circular import
    from gla.eval.curation.triage import IssueThread

    m = re.search(r"stackoverflow\.com/questions/(\d+)", url)
    if not m:
        raise ValueError(f"Not a Stack Overflow question URL: {url}")
    qid = m.group(1)

    key = os.environ.get("STACKAPPS_API_KEY", "")
    key_param = f"&key={key}" if key else ""

    # Fetch the question (withbody)
    q_url = (
        f"{_API_BASE}/questions/{qid}"
        f"?site=stackoverflow&filter=withbody{key_param}"
    )
    q_data = _http_get_json(q_url) or {}
    items = q_data.get("items", [])
    if not items:
        raise ValueError(f"SO question {qid} not found or API failure")
    q = items[0]
    title = html.unescape(q.get("title", ""))
    body = _strip_html(q.get("body", "") or "")
    accepted_id = q.get("accepted_answer_id")

    # Fetch accepted answer if present
    comments: list[str] = []
    if accepted_id:
        a_url = (
            f"{_API_BASE}/answers/{accepted_id}"
            f"?site=stackoverflow&filter=withbody{key_param}"
        )
        a_data = _http_get_json(a_url) or {}
        a_items = a_data.get("items", [])
        if a_items:
            a = a_items[0]
            score = a.get("score", 0)
            body_a = _strip_html(a.get("body", "") or "")
            comments.append(f"=== Accepted Answer (score: {score}) ===\n{body_a}")

    return IssueThread(url=url, title=title, body=body, comments=comments)


def _strip_html(html_text: str) -> str:
    """Minimal HTML->plaintext: unescape entities, strip tags, preserve code."""
    # Keep <code>/<pre> contents distinctive with backticks so the LLM still
    # recognizes them as code blocks.
    text = re.sub(r"<pre><code>(.*?)</code></pre>",
                  lambda m: f"\n```\n{html.unescape(m.group(1))}\n```\n",
                  html_text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<code>(.*?)</code>",
                  lambda m: f"`{html.unescape(m.group(1))}`",
                  text, flags=re.DOTALL | re.IGNORECASE)
    # Strip all remaining tags
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


def _unix_to_iso(t: int) -> str:
    import datetime
    if not t:
        return ""
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).isoformat()
