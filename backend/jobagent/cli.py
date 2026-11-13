"""Command line entry point: `uv run jobagent --help`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer
from rich import print as rprint
from rich.console import Console
from rich.table import Table

from .config import get_settings, load_answer_bank

app = typer.Typer(no_args_is_help=True, help="JobPilot: personal job-hunting agent (runs locally, with the AI you choose).")
console = Console()


def _echo(msg: str) -> None:
    console.print(msg, highlight=False, markup=False, soft_wrap=True)


@app.command()
def init() -> None:
    """Create the database and seed companies from config/companies.yaml."""
    from .bootstrap import bootstrap

    stats = bootstrap()
    rprint(f"[green]ok[/green] database at {get_settings().db_path}; companies seeded: {stats}")


@app.command()
def serve(port: int = typer.Option(None), host: str = typer.Option(None), reload: bool = False,
          no_scheduler: bool = typer.Option(False, "--no-scheduler")) -> None:
    """Start the API (and the UI if web/dist exists)."""
    import os

    import uvicorn

    s = get_settings()
    if no_scheduler:
        os.environ["JOBAGENT_SCHEDULER_ENABLED"] = "false"
        get_settings.cache_clear()
    uvicorn.run("jobagent.main:app", host=host or s.host, port=port or s.port, reload=reload)


@app.command()
def sources() -> None:
    """List sources and whether they are enabled."""
    from .db import session_scope
    from .settings_store import enabled_sources
    from .sources.base import all_sources

    with session_scope() as db:
        enabled = enabled_sources(db)
    t = Table("name", "kind", "enabled", "browser", "ai", "description")
    for n, c in sorted(all_sources().items(), key=lambda kv: (kv[1].kind, kv[0])):
        t.add_row(n, c.kind, "yes" if enabled.get(n) else "no", "yes" if c.needs_browser else "", "yes" if c.uses_ai else "",
                  c.description[:70])
    console.print(t)


@app.command()
def crawl(source: list[str] = typer.Option(None, "--source", "-s", help="run only these sources")) -> None:
    """Crawl enabled sources (or the given ones), then prefilter new jobs."""
    from .bootstrap import bootstrap
    from .db import session_scope
    from .pipeline.ingest import crawl_all
    from .pipeline.prefilter import prefilter_new

    bootstrap()
    with session_scope() as db:
        runs = crawl_all(db, only=list(source) if source else None, log=_echo)
        for r in runs:
            rprint(f"[bold]{r.source}[/bold]: {r.status} {r.stats}")
        rprint(f"prefilter: {prefilter_new(db)}")


@app.command()
def prefilter() -> None:
    """Re-run the cheap prefilter on jobs in status 'new'."""
    from .db import session_scope
    from .pipeline.prefilter import prefilter_new

    with session_scope() as db:
        rprint(prefilter_new(db))


@app.command()
def score(limit: int = typer.Option(None, help="max AI calls this run")) -> None:
    """Score queued jobs with the AI."""
    from .db import session_scope
    from .pipeline.scoring import score_queued

    with session_scope() as db:
        rprint(score_queued(db, limit=limit, log=_echo))


@app.command()
def prepare(job_id: int = typer.Argument(None), limit: int = typer.Option(None)) -> None:
    """Draft cover letter + answers for one job, or for the top shortlisted jobs."""
    from .db import session_scope
    from .pipeline.prepare import prepare_application, prepare_shortlisted

    with session_scope() as db:
        if job_id:
            a = prepare_application(db, job_id, force=True)
            rprint(f"application #{a.id} status={a.status}\n\n{a.cover_letter}")
        else:
            rprint(prepare_shortlisted(db, limit=limit, log=_echo))


@app.command("apply")
def apply_cmd(application_id: int, submit: bool = typer.Option(False, help="actually click submit")) -> None:
    """Fill the application form in the browser (and submit with --submit)."""
    from .db import session_scope
    from .pipeline.apply.runner import apply_application

    with session_scope() as db:
        a = apply_application(db, application_id, submit=submit, log=_echo)
        rprint(f"status={a.status} error={a.error} screenshot={a.screenshot_path}")


@app.command()
def cycle(source: list[str] = typer.Option(None, "--source", "-s")) -> None:
    """crawl → prefilter → score → prepare (what the scheduler runs)."""
    from . import tasks
    from .bootstrap import bootstrap
    from .db import session_scope

    bootstrap()
    with session_scope() as db:
        rprint(json.dumps(tasks.full_cycle(db, _echo, sources=list(source) if source else None), indent=1, default=str))


@app.command()
def discover() -> None:
    """Search the web for more company boards / careers pages matching your roles."""
    from .db import session_scope
    from .pipeline.discover import discover_companies

    with session_scope() as db:
        rprint(discover_companies(db, log=_echo))


@app.command("browser-login")
def browser_login(site_or_url: str) -> None:
    """Open a visible browser on a site's login page using the shared profile. Sign in, then close the window."""
    from . import pacing
    from .browser import launch_context, new_page
    from .db import session_scope
    from .sources.base import all_sources

    url = site_or_url
    if not url.startswith("http"):
        defaults = {"indeed": "https://secure.indeed.com/account/login", "naukri": "https://www.naukri.com/nlogin/login",
                    "linkedin": "https://www.linkedin.com/login", "shine": "https://www.shine.com/myshine/login/"}
        url = defaults.get(site_or_url) or ""
        for name, cls in all_sources().items():
            if name in (site_or_url, f"site_{site_or_url}") and getattr(cls, "login_url", None):
                url = cls.login_url
            if name in (site_or_url, f"site_{site_or_url}"):
                with session_scope() as db:
                    pacing.mark_signed_in(db, name)
        if not url:
            raise typer.BadParameter(f"no login url known for {site_or_url}; pass a URL")
    rprint(f"Opening {url}. Sign in, then close the browser window to save the session.")
    with launch_context(headless=False) as ctx:
        page = ctx.pages[0] if ctx.pages else new_page(ctx)
        page.set_default_timeout(25_000)
        page.goto(url)
        # Closing the last tab does not emit the context "close" event for a persistent context (Chromium keeps
        # running with zero windows), so wait until no pages remain; launch_context then quits Chromium.
        while ctx.pages:
            try:
                ctx.pages[0].wait_for_event("close", timeout=0)
            except Exception:   # browser quit (Cmd+Q) or target gone
                break


@app.command("resume-import")
def resume_import(path: Path, analyze: bool = True, new: bool = typer.Option(False, help="add it as another resume"),
                  name: str | None = None) -> None:
    """Load a resume (pdf/docx/txt/md) and summarize it with the AI. It replaces the default resume unless --new."""
    from .bootstrap import bootstrap
    from .db import session_scope
    from .pipeline.profile import analyze_profile, import_resume

    bootstrap()
    with session_scope() as db:
        p = import_resume(db, path, resume_id=None if new else 1, name=name)
        rprint(f"[green]ok[/green] resume #{p.id} ({p.name}): {len(p.resume_text or '')} characters of text stored")
        if analyze:
            rprint(analyze_profile(db, p.id))


@app.command()
def budget() -> None:
    """Show AI call budget usage and provider status."""
    from .db import session_scope
    from .llm.client import budget_status, provider_status

    with session_scope() as db:
        rprint(provider_status())
        rprint(budget_status(db))


def readiness() -> list[dict[str, Any]]:
    """What a working setup needs, in order, each with the way to fix it. Never includes personal values."""
    import shutil
    import subprocess

    from sqlalchemy import select

    from .db import session_scope
    from .llm.client import provider_status
    from .models import Profile
    from .profiles import rows
    from .settings_store import get_setting

    s = get_settings()
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str, fix: str, needs_you: bool = False) -> None:
        checks.append({"check": name, "ok": ok, "detail": detail, "fix": "" if ok else fix, "needs_you": needs_you and not ok})

    node = shutil.which("node")
    version = ""
    if node:
        try:
            version = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=10).stdout.strip()
        except Exception:
            pass
    major = int(version.lstrip("v").split(".")[0]) if version.lstrip("v").split(".")[0].isdigit() else 0
    add("Node.js 20+", major >= 20, version or "not found", "Install Node 20 or newer (macOS: `brew install node`).")
    caches = (Path.home() / "Library/Caches/ms-playwright", Path.home() / ".cache/ms-playwright")
    chromium = bool(shutil.which("chromium")) or any(any(c.glob("chromium*")) for c in caches if c.exists())
    add("Browser for form filling", chromium, "Playwright Chromium" if chromium else "missing",
        "Run `uv run playwright install chromium`.")
    add("Database", s.db_path.exists(), "data/jobagent.db" if s.db_path.exists() else "not created",
        "Run `uv run jobagent init`.")
    add("Web app built", s.web_dist.exists(), "web/dist" if s.web_dist.exists() else "not built",
        "Run `make build` (or use `make dev`, which doesn't need it).")
    if not s.db_path.exists():
        return checks
    ai = provider_status()
    add(f"AI: {ai['label']}", bool(ai["primary"].get("ok")), ai["model"] if ai["primary"].get("ok") else
        str(ai["primary"].get("error") or "not ready"),
        "Pick and set up an AI in Settings → AI (see SETUP.md, step 4), then press Test connection.", needs_you=True)
    bank = load_answer_bank(s)
    basics = {k: bank.identity.get(k, "") for k in ("full_name", "email", "phone")}
    filled = sum(1 for v in basics.values() if str(v or "").strip())
    add("Your answers (name, email, phone)", filled == len(basics), f"{filled} of {len(basics)} filled",
        "Fill them in Setup → Your answers (saved to config/answer_bank.yaml, never committed).", needs_you=True)
    with session_scope() as db:
        has_resume = any((p.resume_text or "").strip() for p in db.scalars(select(Profile)).all())
        profiles = [r for r in rows(db) if r.enabled and ((r.data or {}).get("roles") or (r.data or {}).get("title_keywords"))]
        setup_done = bool(get_setting(db, "setup.completed"))
        paused = bool(get_setting(db, "schedule.paused"))
    add("Resume", has_resume, "uploaded" if has_resume else "none yet",
        "Upload it in Setup → Resume (PDF, Word, TXT or Markdown).", needs_you=True)
    add("Search profile", bool(profiles), f"{len(profiles)} active" if profiles else "none with job titles",
        "Set job titles and places in Profiles & resumes (\"New search profile from it\" uses your resume).", needs_you=True)
    add("Setup finished", setup_done, "yes" if setup_done else "not yet",
        "Finish the Setup wizard in the app (it also picks a schedule).", needs_you=True)
    add("Schedule", not paused, "running on its days" if not paused else "paused (Run now still works)",
        "Choose a plan on the Schedule page when you want runs to happen by themselves.", needs_you=True)
    return checks


@app.command()
def doctor(as_json: bool = typer.Option(False, "--json", help="machine-readable, for setup scripts and AI assistants")) -> None:
    """Check the setup: tools, browser, database, AI provider, and what you still need to do. Free: no AI call."""
    checks = readiness()
    if as_json:
        print(json.dumps({"ready": all(c["ok"] for c in checks), "checks": checks}, indent=2))
        return
    for c in checks:
        mark = "[green]✔[/green]" if c["ok"] else ("[yellow]•[/yellow]" if c["needs_you"] else "[red]✘[/red]")
        rprint(f"{mark} {c['check']}: {c['detail']}" + ("" if c["ok"] else f"\n    → {c['fix']}"))
    todo = [c for c in checks if not c["ok"]]
    rprint("\n[bold]All set.[/bold] Open http://127.0.0.1:8000" if not todo else
           f"\n[bold]{len(todo)} left.[/bold] [red]✘[/red] = install step, [yellow]•[/yellow] = something only you can do (in the app).")

if __name__ == "__main__":
    app()
