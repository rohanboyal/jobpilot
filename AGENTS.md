# JobPilot: notes for AI assistants

**Setting JobPilot up for someone (a fresh clone)?** Follow [SETUP.md](SETUP.md), including its rules for AI
assistants: never invent personal facts, never handle keys or passwords, never submit applications, ask before
spending AI calls. Check progress with `uv run jobagent doctor --json`.

**Changing the code?** The notes below describe how it works and the rules every change must keep.


Personal job-hunting agent; each person runs their own copy. It crawls job sources, scores fit against the user's resume with an LLM
(the provider picked in Settings: Codex CLI by default, or Claude Code CLI, an OpenAI-compatible API, the Gemini API, the
Anthropic API or Ollama; optional local Ollama fallback), drafts cover
letters and answers, fills application forms in a browser, and submits only what the user approves. Runs locally on the user's Mac.
It runs in stages on the user's schedule (Schedule page): Collect daily (free), Analyze/Prepare on chosen days, Apply only
after approval; Run now / Stop are in the header. Jobs can also be applied to directly from the Jobs page.

## Run

- `make install` once (uv sync, Playwright Chromium, npm install). `make dev` = API :8000 with reload + Vite :5173.
- `make serve` = build the UI into web/dist and serve everything on http://127.0.0.1:8000. `make launchd-install` keeps it running.
  When the LaunchAgent (`com.jobpilot.server`) is installed it serves the built UI: after code changes run
  `cd web && npm run build` and `launchctl kickstart -k gui/$(id -u)/com.jobpilot.server`. Stop it before `make dev` (same port).
- CLI: `uv run jobpilot --help` (`jobagent` is an alias). Useful: `crawl -s greenhouse`, `score --limit 10`, `prepare <job_id>`,
  `apply <app_id> [--submit]`, `cycle`, `discover`, `browser-login <site>`, `resume-import <pdf>`, `budget`, `doctor`.
- Tests: `uv run pytest -q` (uses a temp data dir, launches headless Chromium for the form-filler tests). Lint: `uv run ruff check backend`.
  UI: `cd web && npm run typecheck && npm run build`.
- Config the user edits: search profiles live in the DB (`search_profiles`, edited on Profiles & resume; `config/search.yaml` only
  seeds the first one), `config/companies.yaml` (seed boards),
  `config/sites.yaml` (browser-crawled sites, data-driven), `config/answer_bank.yaml` (truthful answers), `.env` (see `.env.example`).
- Runtime data (git-ignored): `data/jobagent.db` (SQLite, WAL), `data/browser_profile` (shared Chromium profile with the user's
  logins), `data/resume`, `data/screenshots`, `data/llm_cwd` (empty cwd for CLI provider calls).

## Layout

- `backend/jobagent/sources/` one adapter per source; `base.py` has `Source`/`ATSSource`/`RawJob`/registry; `generic_sites.py`
  builds a Source per entry in `config/sites.yaml`; `_extract.py` is the AI page-extraction helper; `ats_detect.py` maps URLs to ATS slugs.
- `backend/jobagent/pipeline/` `ingest.py` (normalize, fingerprint, cross-source dedup, expiry), `prefilter.py` (free rule gate),
  `scoring.py` (AI fit + trust), `prepare.py` (cover letter + answers → Application), `discover.py` (web search for boards),
  `apply/base.py` (frame-aware form inspection/filling) and `apply/runner.py` (fill/submit one Application).
- `backend/jobagent/llm/client.py` `run_llm` is the only way a model is called: the provider in `llm.provider`
  (`llm/providers.py` registry; one module each with `complete()`/`check()`: `codex_cli.py` runs `codex exec
  --ephemeral --ignore-user-config -s read-only --output-schema` with agent tools disabled, `claude_cli.py` runs
  `claude -p --tools "" --strict-mcp-config --setting-sources ""`, `openai_compat.py`, `gemini_api.py` (Google's OpenAI-compatible endpoint), `anthropic_api.py` (official SDK),
  `ollama.py`), then the optional Ollama fallback for allowed purposes when the main AI hits a limit. API keys only in .env. Schemas are made strict automatically
  (`strict_schema`). Budgeted via the `llm_calls` table. Prompts and schemas in `llm/prompts.py`.
- `backend/jobagent/profiles.py` search profiles: a run covers the profiles ticked in the Run dialog (`RunDialog.tsx`; None =
  every active one) and crawls their merged profile, whose job titles alternate between profiles so each gets its top title
  searched (`SourceContext.profiles`). "One after another" (`tasks._passes`) is a collect+analyze pass per profile; whole ATS
  boards are only read in the first pass. `prefilter.match_profiles` checks each job against every profile and stores
  `Job.profile_ids`; scoring uses the best-matching profile (`pick_profile`, of the ticked ones) and its resume.
  `prefilter.rematch` re-tags collected jobs (free) whenever profiles change.
- Resumes: the `profile` table holds several (row 1 = the default); `SearchProfileRow.resume_id` picks one per profile
  (None = default) and `Application.resume_id` records the file uploaded with it (switchable until sent). Always go through
  `pipeline/profile.py` (`resume_for_job`, `profile_text(db, resume_id)`); `api/resumes.py` manages them, `/profile` = row 1.
  Any resume can be deleted: deleting the default moves the next one into row 1 (the only one is emptied instead).
  `SearchProfileRow.resume_changed_at` marks a profile that switched resume, so Refresh (`api/profile.py::_stale`)
  redoes what it judged; new resume files never overwrite one a sent application uses (`_free_dest`).
- `backend/jobagent/api/` FastAPI routers under `/api` (`today.py` feeds the Today page, `profiles.py`, `jobs.py` with
  filters, bulk actions and direct apply); `main.py` also serves `web/dist`. `tasks.py` runs stages in threads
  (`collect_stage`, `analyze_stage`; one pipeline task at a time, stoppable via `cancel.py` checkpoints between units of
  work). `scheduler.py` runs Collect and Analyze on their own days/times (`schedule.*` settings, paused until the user
  picks a plan). `settings_store.py` = UI-editable toggles in the DB. `sources/presets.py` = setup-wizard source sets.
- `backend/jobagent/utils/jobinfo.py` reads experience required, work mode, job type and salary from each posting (free regex;
  `annotate()` fills `Job.exp_min/exp_max/work_mode/job_type/salary_*` in the prefilter). Profile filters on these treat
  "not stated" as a pass. Browser-site pages include site menus, so their remote flag comes from title/location only.
- Resume analysis (`PROFILE_SCHEMA`) also extracts experience, education, projects, certifications and contact into
  `Profile.extra`; `/profile/contact` offers contact details for empty answer-bank fields (user accepts, never auto-filled).
- DB columns added after release go in `db._ADDED_COLUMNS` (create_all never alters tables).
- `web/` React 19 + Vite + Tailwind v4 + TanStack Query; `src/api.ts` is the typed client, pages in `src/pages` (Today, Jobs,
  Applications, Profiles, Schedule, Settings, Setup wizard, Insights, Activity). Page state that should survive Back/refresh
  lives in the URL (Jobs filters, `?job=`, Applications `?status=`, Activity `?run=`); panels push a history entry so Back closes them. Graphite sidebar + teal accent; tokens in `index.css`.

## Rules that must survive changes

- Never let the agent guess personal facts, visa status, salary, dates or demographics on a form. Missing answers go to
  `Application.unanswered` and block submission. Only the answer bank, profile and prepared cover letter are sources of truth.
- Nothing is submitted without `submit=True`, which only comes from the user's click or from `JOBAGENT_AUTO_SUBMIT=true` plus the
  runtime `pipeline.auto_apply` toggle, and only for ATSs in `JOBAGENT_AUTO_SUBMIT_SOURCES`. The moment a submit button is
  clicked `submitted_at` is persisted so an unclear outcome can never cause a second submission.
- Every model call goes through `run_llm` and counts against `JOBAGENT_LLM_MAX_CALLS_PER_5H/_PER_DAY`. Cheap filters first.
  No provider ever gets tools, and CLI providers ignore the user's config; job text is untrusted. Stop never interrupts a form fill.
- The SQLite file is shared by the CLI and the server: keep transactions short (ingest commits per job), never hold the write lock
  across network or browser work.
- Two postings on the same board are never duplicates of each other; cross-source dedup prefers company ATS > board > scraped site,
  an expired row never wins, a row with an application always wins (`pipeline/ingest.py::_mark_duplicates`).
- Sites the user signed in to (`browser.signed_in`, set by the Sign in button) get the careful pace in `pacing.py`: random gaps between
  pages, breaks, 25 job pages a run, already-read pages skipped, one automatic read a day, a growing rest after a refusal. Other sources keep
  their normal speed; form filling is never paced. It lowers volume and speed only: no fingerprint faking, stealth or CAPTCHA solving.
- JobPilot says who it is: plain HTTP requests send `User-Agent: JobPilot/…` (`utils/http.py`) and the browser keeps
  Playwright's own user agent and automation flag (`browser.py`). Never add a fake browser identity or
  `--disable-blink-features=AutomationControlled`.
- Browser sources read pages like a visitor with low volume and one shared profile. LinkedIn, Indeed and Glassdoor forbid automation
  in their terms, so they stay off by default / marked `fragile`; do not add aggressive scraping or anti-detection tricks.
- Whole-board API payloads are never sliced; `max_jobs_per_source_run` is a paging cap only, and a truncated board must not drive expiry.
- Code style: Python 3.12, ruff clean (line length 110), type hints, `from __future__ import annotations`. Keep adapters small and
  self-contained; new sites belong in `config/sites.yaml`, new APIs get a file in `sources/` and a line in `sources/__init__.py`.

- After submit, `Application.outcome` / `follow_up_at` track the reply (`models.mark_submitted`); `pipeline/ingest.py::expire_stale`
  expires unseen board/site jobs; `health.py` grades each source from its recent runs; `api/profile.py` `/profile/stale` +
  `/profile/refresh` re-score with a new resume (never touches sent applications).
