"""Hasjob (HasGeek's India job board) through its public Atom feed, which carries the whole live board (~15 posts)."""

from __future__ import annotations

from collections.abc import Iterable

from bs4 import BeautifulSoup

from ..utils.feeds import parse_feed
from ..utils.http import get, make_client
from ..utils.text import html_to_text, parse_date
from .base import RawJob, Source, SourceContext, register, skill_hit, title_passes

FEED = "https://hasjob.co/feed"


@register
class Hasjob(Source):
    name = "hasjob"
    label = "Hasjob (HasGeek)"
    kind = "board"
    priority = 2
    description = ("Public Atom feed of hasjob.co, the Indian community board (about 15 live posts); kept when the title "
                   "or the posting mentions your keywords or skills.")

    def fetch(self, ctx: SourceContext) -> Iterable[RawJob]:
        if "in" not in {c.lower() for c in ctx.search.countries}:
            ctx.log("Hasjob skipped: 'in' is not in your countries")
            return
        with make_client(timeout=ctx.settings.source_timeout_s) as client:
            r = get(client, FEED)
        for e in parse_feed(r.text):
            html = e.content or e.summary
            text = html_to_text(html)
            if not e.link or (not title_passes(ctx, e.title) and not skill_hit(ctx, text[:2000])):
                continue
            # content starts with <p><strong><a href="COMPANY_SITE">COMPANY</a></strong><br/>LOCATION</p>
            strong = BeautifulSoup(html, "lxml").find("strong") if html else None
            parts = e.link.rstrip("/").split("/")
            company = strong.get_text(" ", strip=True) if strong else (parts[-2] if len(parts) >= 2 else "")
            website = strong.a.get("href") if strong is not None and strong.a is not None else None
            location = e.extra.get("location") or None
            yield RawJob(
                source=self.name, external_id=parts[-1] or e.guid, title=e.title, company_name=company, url=e.link,
                apply_url=e.link, location=location, remote=(location.lower() == "anywhere") if location else None,
                description=text or None, posted_at=parse_date(e.published), company_website=website,
            )
