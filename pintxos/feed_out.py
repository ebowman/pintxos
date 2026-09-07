"""Render feed items as RSS 2.0 XML."""

from __future__ import annotations

import html
import sqlite3
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from datetime import datetime
from email.utils import format_datetime

from pintxos.stats import format_stats

_AUTH_NOTES = {
    "used": "<p><em>Read with your subscription.</em></p>",
    "missing": "<p><em>Login may be required; summarized from the feed excerpt.</em></p>",
    "failed": (
        "<p><em>Your saved login did not work (cookies expired?); "
        "summarized from the feed excerpt.</em></p>"
    ),
}

_FETCH_NOTES = {
    "teaser": (
        "<p><em>Only a teaser was available (paywall); "
        "summarized from the feed excerpt.</em></p>"
    ),
    "blocked": (
        "<p><em>The site blocked the fetch; "
        "summarized from the feed excerpt.</em></p>"
    ),
}

_TITLE_NORM_TABLE = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "“": '"',
        "”": '"',
        "–": "-",
        "—": "-",
    }
)


def _norm_title(s: str) -> str:
    """Normalize a title for loose comparison (whitespace, case, quotes, dashes)."""
    return " ".join(s.strip().translate(_TITLE_NORM_TABLE).split()).casefold()


def render_rss(
    feed: sqlite3.Row, items: Sequence[sqlite3.Row], *, full_text: bool = True
) -> bytes:
    """Render a feed and its items as RSS 2.0 XML bytes."""
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = f"{feed['title'] or feed['url']} · Pintxøs"
    ET.SubElement(channel, "link").text = feed["url"]
    ET.SubElement(channel, "description").text = "Factual summaries by Pintxøs"

    for item in items:
        entry = ET.SubElement(channel, "item")
        ET.SubElement(entry, "title").text = item["headline"]
        ET.SubElement(entry, "link").text = item["link"]
        guid = ET.SubElement(entry, "guid", {"isPermaLink": "false"})
        guid.text = item["guid"]
        pub_date = format_datetime(datetime.fromisoformat(item["published_at"]))
        ET.SubElement(entry, "pubDate").text = pub_date

        description = f"<p>{item['summary']}</p>"
        words = item["word_count"]
        if words:
            description += f"<p><em>{format_stats(words)}</em></p>"
        auth = item["auth"]
        fetch_status = item["fetch_status"]
        if auth == "used":
            description += _AUTH_NOTES["used"]
        elif auth == "failed":
            description += _AUTH_NOTES["failed"]
        elif fetch_status in _FETCH_NOTES:
            description += _FETCH_NOTES[fetch_status]
        elif item["fallback"]:
            if auth == "missing":
                description += _AUTH_NOTES["missing"]
            elif auth is None:
                description += (
                    "<p><em>Note: article fetch failed; summarized from feed excerpt.</em></p>"
                )
        description += f"<p>Original: {item['original_title']}</p>"
        if full_text and item["text"]:
            description += "<p>=== FULL TEXT BELOW ===</p>"
            norm_original_title = _norm_title(item["original_title"] or "")
            first_line_seen = False
            for line in item["text"].splitlines():
                if not line.strip():
                    continue
                if not first_line_seen:
                    first_line_seen = True
                    if norm_original_title and _norm_title(line) == norm_original_title:
                        continue
                description += f"<p>{html.escape(line)}</p>"
        ET.SubElement(entry, "description").text = description

    return ET.tostring(rss, encoding="utf-8", xml_declaration=True)
