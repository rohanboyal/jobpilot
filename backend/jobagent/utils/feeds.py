"""Minimal RSS 2.0 / Atom reader for job feeds (BeautifulSoup + lxml; no feedparser dependency)."""

from __future__ import annotations

from dataclasses import dataclass, field

from bs4 import BeautifulSoup
from bs4.element import Tag


@dataclass
class FeedItem:
    title: str
    link: str
    guid: str | None = None
    published: str | None = None          # raw date text; parse with utils.text.parse_date
    summary: str = ""                     # <description> / <summary> (usually escaped HTML)
    content: str = ""                     # <content:encoded> / Atom <content> (HTML)
    extra: dict[str, str] = field(default_factory=dict)   # every direct child as "prefix:name" -> text


def _child(item: Tag, name: str) -> Tag | None:
    for ch in item.find_all(recursive=False):
        if ch.name == name:
            return ch
    return None


def _text(item: Tag, name: str) -> str:
    el = _child(item, name)
    return el.get_text().strip() if el is not None else ""


def _link(item: Tag) -> str:
    """RSS puts the URL in <link>text</link>; Atom in <link href=".." rel="alternate"/>."""
    first_href = ""
    for ch in item.find_all("link", recursive=False):
        href = (ch.get("href") or "").strip()
        if href:
            if (ch.get("rel") or "alternate") == "alternate":
                return href
            first_href = first_href or href
        else:
            txt = ch.get_text().strip()
            if txt:
                return txt
    return first_href


def parse_feed(xml_text: str) -> list[FeedItem]:
    """Return every <item> (RSS) or <entry> (Atom) of a feed with the common fields normalized."""
    soup = BeautifulSoup(xml_text or "", "xml")
    out: list[FeedItem] = []
    for it in soup.find_all(["item", "entry"]):
        extra: dict[str, str] = {}
        for ch in it.find_all(recursive=False):
            key = f"{ch.prefix}:{ch.name}" if ch.prefix else ch.name
            if key not in extra:
                extra[key] = ch.get_text().strip()
        out.append(FeedItem(
            title=_text(it, "title"),
            link=_link(it),
            guid=_text(it, "guid") or _text(it, "id") or None,
            published=_text(it, "pubDate") or _text(it, "published") or _text(it, "updated") or extra.get("dc:date") or None,
            summary=_text(it, "description") or _text(it, "summary"),
            content=extra.get("content:encoded") or _text(it, "content"),
            extra=extra,
        ))
    return out
