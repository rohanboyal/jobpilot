"""Data-driven browser sources: one Source per entry in config/sites.yaml.

The page is opened in the shared Chromium profile (so logins persist), listings are read with the site's CSS
selectors when provided, otherwise the AI extracts them from the page text and links.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import quote_plus

import yaml

from ..browser import dismiss_cookie_banners, launch_context, looks_blocked, new_page
from ..config import get_settings
from ..utils.text import detect_remote, normalize_ws, slugify
from ._extract import extract_listings, read_job_page, scroll_a_bit
from .base import _REGISTRY, RawJob, Source, SourceContext, title_passes

SITES_FILE = "sites.yaml"


def sites_path() -> Path:
    return get_settings().config_dir / SITES_FILE


def load_sites() -> list[dict[str, Any]]:
    p = sites_path()
    if not p.exists():
        return []
    with p.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    out = []
    for s in data.get("sites", []):
        if not s.get("key") or not s.get("search_url"):
            continue
        s["key"] = re.sub(r"[^a-z0-9_]", "_", str(s["key"]).lower())
        out.append(s)
    return out


def save_sites(sites: list[dict[str, Any]]) -> None:
    p = sites_path()
    with p.open("w", encoding="utf-8") as fh:
        yaml.safe_dump({"sites": sites}, fh, sort_keys=False, allow_unicode=True)
    register_sites(force=True)


def fill_template(url: str, role: str, location: str, days: int) -> str:
    return (url.replace("{role_slug}", slugify(role)).replace("{role_plus}", quote_plus(role)).replace("{role}", quote_plus(role))
            .replace("{location_slug}", slugify(location)).replace("{location_plus}", quote_plus(location))
            .replace("{location}", quote_plus(location)).replace("{days}", str(days)))


class GenericSite(Source):
    kind: ClassVar[str] = "browser"
    priority: ClassVar[int] = 3
    needs_browser: ClassVar[bool] = True
    uses_ai: ClassVar[bool] = True
    fragile: ClassVar[bool] = True
    site: ClassVar[dict[str, Any]] = {}

    def fetch(self, ctx: SourceContext) -> Iterable[RawJob]:
        site = self.site
        wanted = [c.lower() for c in (site.get("countries") or [])]
        if wanted and not set(wanted) & {c.lower() for c in ctx.search.countries}:
            ctx.log(f"{self.label}: skipped (country filter {wanted})")
            return
        pages = int(site.get("pages") or 1)
        details_left = ctx.settings.max_detail_fetches_per_run
        extract_left = ctx.settings.max_company_pages_per_run
        seen: set[str] = set()
        read_details = bool(site.get("read_details", True))   # false when robots.txt disallows the job pages
        needs_loc = "{location" in site["search_url"]
        locations = self.location_terms(ctx, 2) if needs_loc else [""]
        with launch_context() as bctx:
            page = new_page(bctx)
            for term in self.search_terms(ctx, 2):
                for where in locations:
                    url = fill_template(site["search_url"], term, where or "", ctx.search.max_age_days)
                    for n in range(pages):
                        page_url = url if n == 0 else _next_page(url, n)
                        try:
                            cards = self._cards(ctx, page, page_url)
                        except Exception as e:
                            if "HTTP 404" in str(e):      # the site has no page for that title in that place
                                ctx.log(f"{self.label}: no '{term}' page for {where or 'anywhere'} on this site, skipped")
                            else:
                                ctx.log(f"{self.label} {term}/{where}: {e}")
                            break
                        if cards is None:   # blocked
                            ctx.log(f"{self.label}: bot check or login wall. Run `jobagent browser-login {site['key']}`.")
                            return
                        if not cards and extract_left > 0:
                            res = extract_listings(ctx, page, page_url)
                            extract_left -= 1
                            if res.get("page_kind") == "blocked":
                                ctx.bump("blocked")
                                ctx.log(f"{self.label}: blocked. Run `jobagent browser-login {site['key']}`.")
                                return
                            cards = [{"href": j["url"], "title": j.get("title", ""), "company": j.get("department") or "",
                                      "location": j.get("location", "")} for j in res.get("jobs", [])]
                        ctx.log(f"{self.label} {term}/{where} p{n + 1}: {len(cards)} listings")
                        if not cards:
                            break
                        for c in cards:
                            href = c.get("href")
                            if not href or href in seen:
                                continue
                            seen.add(href)
                            desc = c.get("snippet") or None
                            if details_left > 0 and read_details and title_passes(ctx, c.get("title")) and ctx.wants_details(href):
                                try:
                                    desc = read_job_page(page, href) or desc
                                    details_left -= 1
                                except Exception:
                                    pass
                            yield RawJob(
                                source=self.name, title=normalize_ws(c.get("title")), company_name=normalize_ws(c.get("company")),
                                url=href, apply_url=href, location=normalize_ws(c.get("location")) or None,
                                remote=detect_remote(c.get("title"), c.get("location")),   # page text includes site menus ('Remote jobs')
                                description=desc,
                                raw={"site": site["key"]},
                            )
                        page.wait_for_timeout(1200)

    def _cards(self, ctx: SourceContext, page, url: str) -> list[dict] | None:
        """Return cards via CSS selectors, [] when no selectors/matches, None when blocked."""
        resp = page.goto(url, wait_until="domcontentloaded")
        if resp is not None and resp.status >= 400:
            raise RuntimeError(f"HTTP {resp.status} for {url}")   # a 404 search page must not cost a AI call
        page.wait_for_timeout(2500)
        dismiss_cookie_banners(page)
        if looks_blocked(page):
            ctx.bump("blocked")
            return None
        if self.site.get("needs_login") and _looks_like_login(page):
            ctx.bump("login_required")
            return None
        card_sel = self.site.get("card_selector")
        if not card_sel:
            return []
        scroll_a_bit(page, 2)
        js = """
        (cfg) => Array.from(document.querySelectorAll(cfg.card)).map(c => {
          const q = s => s ? c.querySelector(s) : null;
          // the link may be the card itself, or a non-anchor element carrying an href attribute
          const a = q(cfg.link) || (c.matches('a[href]') ? c : c.querySelector('a[href]'));
          if (!a) return null;
          let href = a.href || a.getAttribute('href') || '';
          try { href = new URL(href, location.href).href; } catch (e) {}
          const t = q(cfg.title) || a;
          return href ? { href, title: t ? t.textContent.trim() : '',
                          company: q(cfg.company) ? q(cfg.company).textContent.trim() : '',
                          location: q(cfg.location) ? q(cfg.location).textContent.trim() : '' } : null;
        }).filter(Boolean)
        """
        cfg = {"card": card_sel, "link": self.site.get("link_selector"), "title": self.site.get("title_selector"),
               "company": self.site.get("company_selector"), "location": self.site.get("location_selector")}
        return page.evaluate(js, cfg)


def _looks_like_login(page) -> bool:
    try:
        url = page.url.lower()
        if any(k in url for k in ("login", "signin", "sign-in", "auth")):
            return True
        pw = page.locator("input[type=password]")
        return pw.count() > 0 and pw.first.is_visible()
    except Exception:
        return False


def _next_page(url: str, n: int) -> str:
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}page={n + 1}"


_registered_keys: set[str] = set()


def register_sites(force: bool = False) -> None:
    """Create and register a Source subclass per configured site."""
    global _registered_keys
    sites = load_sites()
    if force:
        for k in list(_registered_keys):
            _REGISTRY.pop(k, None)
        _registered_keys = set()
    for s in sites:
        name = f"site_{s['key']}"
        if name in _REGISTRY:
            continue
        cls = type(
            f"Site_{s['key']}",
            (GenericSite,),
            {
                "name": name,
                "label": s.get("label") or s["key"],
                "description": s.get("notes") or f"Browser search on {s['key']}" + (" (needs login)" if s.get("needs_login") else ""),
                "default_enabled": bool(s.get("enabled", False)),
                "site": s,
                "login_url": s.get("login_url"),
            },
        )
        _REGISTRY[name] = cls
        _registered_keys.add(name)


register_sites()
