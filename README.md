# JobPilot

A personal job-hunting agent that runs on your own Mac. It crawls job sources, scores each posting against your
resume with the AI you already have (a ChatGPT or Claude subscription, an API key, or a local model), drafts cover letters and
screening answers, fills application forms in a browser, and submits only what you approve.

```
 sources ──► ingest + dedup ──► cheap prefilter ──► AI fit + trust score ──► shortlist
                                                                                   │
                       you approve ◄── review queue ◄── cover letter + answers ◄───┘
                            │
                            └──► browser fills the ATS form ──► submit ──► applied
```

## Requirements

- Windows 10/11, macOS or Linux. Every change is installed, tested, built and started on all three automatically.
  Windows uses `scripts\windows.ps1` where macOS and Linux use `make`; see [SETUP.md](SETUP.md).
- One AI (ChatGPT, Claude, Gemini, any OpenAI-compatible API, or a local model), chosen in **Settings → AI** (see [Choosing your AI](#choosing-your-ai)). The default is the Codex CLI with a
  ChatGPT plan: the ChatGPT desktop app ships it, or `npm i -g @openai/codex` and `codex login`.
- Optional: [Ollama](https://ollama.com) with a small model (e.g. `qwen3.5:4b`) as a fallback when your main AI hits its limit.
- [uv](https://docs.astral.sh/uv/) and Node 20+ (`brew install uv node`).

## Setup

**Full guide: [SETUP.md](SETUP.md).** It lists what you need, what isn't in the repository (your AI access, resume,
answers and sign-ins), and every step after cloning. Using an AI coding assistant? Open the folder and ask it to
"set up JobPilot by following SETUP.md"; the guide tells it what it may and may not do for you.

The short version:

```bash
make install            # python deps, Chromium for Playwright, node deps
cp .env.example .env    # optional: tweak model, budgets, auto-submit
uv run jobagent init    # creates data/jobagent.db and seeds companies from config/companies.yaml
make dev                # API on http://127.0.0.1:8000, UI on http://localhost:5173
```

For an always-on setup: `make serve` builds the UI and serves everything from port 8000, and
`make launchd-install` keeps that running in the background after login. Stages run on the days and times set on the
**Schedule** page (paused until you finish Setup). A run missed while the Mac slept starts on wake if it is within two
hours. *Run now* and *Stop* are in the header on every page; Stop finishes the job or form in progress, then halts.

## First things to do in the UI

Open **Setup** (linked from Today until it is done). Five steps, about ten minutes:

1. **Resume**: upload it; the AI reads it once and suggests roles.
2. **Profiles**: one search profile per kind of job you want (titles, places, keywords, seniority, fit threshold).
   "From my resume" builds one from the analysis.
3. **Your answers**: the only facts ever typed into forms. Blank means you are asked, never guessed.
4. **Sources**: a starting set (India + remote, Remote worldwide, India only) and sign-ins for sites that need one.
5. **Schedule**: Light (collect daily, analyze Mon and Thu), Active (analyze weekdays) or Manual.

## How a week runs

| Stage | When | Cost |
|---|---|---|
| Collect | your days and time, default daily 08:00 | free (AI only for sites without CSS selectors) |
| Analyze | your days, default Mon and Thu 09:00; best new matches first, capped per run | 1 AI call per job |
| Prepare | right after Analyze, for jobs at or above the prepare fit threshold | 1 AI call per cover letter |
| Apply | when you approve on Today or Jobs (or auto-submit, if enabled in `.env`) | 1 AI call per form |

The Schedule page shows the estimated AI calls per week as you change days and limits. **Jobs** has tabs (all new,
strong matches, in progress, applied, not interested, filtered out with the reason) and filters for text, city, profile,
fit, post date, experience, work mode, job type, salary (₹ LPA), source or source type, and auto-fillable forms. Filters
on experience, mode, type and salary hide postings that don't say unless *Include jobs that don't say* is on. Filter sets
can be saved as views. Select jobs to analyze, prepare or skip in bulk (or move filtered ones back to the queue), or
**Apply** directly: either let the AI check fit and draft answers, or skip AI and fill from your
answers. Both stop on a review screen; questions you have no saved answer for must be filled in there before submit.

## How jobs are found

| Kind | Sources | How |
|------|---------|-----|
| ATS boards | Greenhouse, Lever, Ashby, Workable, SmartRecruiters | public JSON APIs of the companies in **Companies** |
| Job boards | Remotive, RemoteOK, HN "Who is hiring", We Work Remotely, Himalayas, Jobicy, Working Nomads, Jobspresso, NoDesk, JustRemote, Arc, Jobgether, Levels.fyi (MCP), The Muse, 80,000 Hours, Hasjob, Geektrust, ZipRecruiter India (RSS), LinkedIn public search, WeAreDevelopers (EU/US), Arbeitnow (EU)\*, Dice (US, MCP)\*, Crossover\*, Reed (UK, key)\*, Adzuna (key)\*, Jooble (key)\* | public APIs, feeds and MCP servers the boards publish. LinkedIn's apply page needs your login, so those jobs (and any job whose apply link is LinkedIn) become *manual* applications |
| Browser sites | Weekday, Startup Jobs, Built In, Dynamite Jobs, AIJobs.ai, Wellfound, Cutshort, Hirist, Foundit, TimesJobs, YC; off by default: Indeed, Naukri, Glassdoor, Apna, SimplyHired, Talent.com, Instahyre, and others whose terms forbid automated reading | shared Chromium profile; listings read with CSS selectors, or extracted by the AI when a site has none |
| Company careers pages | any company with `ats: custom` and a `careers_url` | browser + AI extraction; auto-upgrades to the ATS adapter when it spots one |
| Discovery | `Discover companies` | web search for ATS boards / careers pages matching your roles, probes them, adds them to **Companies** |

\* off by default: needs a free key in `.env`, or targets another country.

Jobs from boards and sites that stop appearing for `jobs.stale_after_days` (21) days are marked expired after each
collect; ATS boards expire on their own when a full board read no longer lists them, and jobs with an application are
never expired. **Settings → Sources** shows a health badge per source (failing, needs sign-in, finding nothing, idle)
and **Today** lists the ones that need attention.

Add a site without code: **Settings → Job sites** (or `config/sites.yaml`): a key, a search URL template with
`{role_slug}` / `{location_slug}` / `{role_plus}` / `{location_plus}` / `{days}` placeholders, and optional CSS
selectors. Without selectors the page is parsed by the AI (about one call per results page).

## Choosing your AI

Pick one in **Settings → AI** and press *Test connection*. Whichever you choose, the model gets no tools (no shell,
files, browser or plugins), so text inside a job posting can't make it do anything on your computer.

| Provider | You need | Cost |
|---|---|---|
| **Codex CLI** (default) | ChatGPT Plus/Pro; the ChatGPT desktop app or `npm i -g @openai/codex`, then `codex login` | your subscription |
| **Claude Code CLI** | Claude Pro/Max; [Claude Code](https://claude.com/claude-code) installed, signed in once by running `claude` | your subscription |
| **Google Gemini API** | a key from [Google AI Studio](https://aistudio.google.com/apikey) in `.env` (`JOBAGENT_GEMINI_API_KEY`); pick a model from the list Settings loads from Google | free tier with limits, then pay per use |
| **OpenAI-compatible API** | a key in `.env` (`JOBAGENT_OPENAI_API_KEY`) and the server: OpenAI, OpenRouter, Groq, DeepSeek, Mistral, or any other address (LM Studio and vLLM on your own machine need no key) | pay per use |
| **Anthropic API** | a key in `.env` (`JOBAGENT_ANTHROPIC_API_KEY`); default model `claude-opus-5-5` | pay per use |
| **Ollama** | [Ollama](https://ollama.com) running with a model pulled (`ollama pull qwen3.5:4b`) | free, offline |

API keys only ever live in `.env`; the app never shows or stores them. Adding another provider is one file in
`backend/jobagent/llm/` with a `complete()` and a `check()` function, plus a line in `llm/providers.py`.

## AI usage and budget

Every AI call goes through one function with a strict JSON schema, is logged in `llm_calls`, and is capped by
`JOBAGENT_LLM_MAX_CALLS_PER_5H` / `_PER_DAY` so a run can never drain your plan or your API budget (a local Ollama
model is free and has no cap). If the main AI reports a usage limit and the local fallback is on
(*Settings → AI*), the allowed purposes (scoring and page reading by default) use the Ollama model instead.
The cheap prefilter (title keywords, location, age, skills) means only plausible jobs are scored.

| Purpose | When | Calls |
|---------|------|-------|
| score | each queued job | 1 |
| cover | each shortlisted job prepared | 1 |
| form | each application filled | 1 |
| extract | browser sites / careers pages without selectors | 1 per page |
| profile | *Analyze with AI* | 1 |

## Applying

- `prepare` creates an **Application** in `needs_review` with a cover letter, a short pitch and the answers from the
  answer bank. Postings with no form (e.g. Hacker News "email us") become `manual` with the material ready to copy.
- *Fill in browser* opens the form headlessly (Greenhouse forms are opened through the embedded board, which also
  works for companies hosting the board on their own site; forms inside iframes are found too), maps fields to
  answers with the AI, fills them, screenshots, and stops. Nothing is sent.
- *Submit application* does the same and clicks submit. The moment the click happens it is recorded, so an unclear
  confirmation page can never lead to a second submission; such cases land in *needs review* with a note. The
  scheduler only submits by itself when **both**
  `JOBAGENT_AUTO_SUBMIT=true` and *Automation → auto apply* are on, and only for ATSs in
  `JOBAGENT_AUTO_SUBMIT_SOURCES`; required fields without a truthful answer always block submission.
- After a submission the application tracks what happened next: waiting, heard back, interviewing, offer, rejected
  or no response, with notes. A follow-up reminder is set `applications.follow_up_days` (10) days out; due ones show
  on **Today** with one-click updates, and **Insights** shows the after-applying funnel.
- When you upload a new resume, **Today** and **Profiles** offer to re-score jobs scored with the old one and redraft
  unsent cover letters (one AI call per job, two per letter). Sent applications are never changed.
- Trust score: heuristics (fee requests, free-mail contacts, unnamed employers, MLM wording, …) blended with
  the AI's judgement. Jobs under the trust threshold are never auto-shortlisted.

## The UI

**Today** (approvals, follow-ups and strong matches from jobs found in the last 7 days, each saying when it was found;
sources needing attention, the week), **Jobs** (jobs found in the last 30 days; applied ones always stay; filters, saved views,
bulk analyze/prepare, direct apply), **Applications** (review queue, editable letter and answers, fill-only dry run with
screenshot, submit, outcome tracking), **Profiles & resume** (search profiles with standard filters, resume details),
**Schedule** (stage days, times, caps and the weekly AI estimate), **Settings** (sources with health and sign-in, job
sites editor, answer bank, AI, companies), plus **Insights** and the **Activity log**. Light and dark themes.

## CLI

```bash
uv run jobpilot --help   # `jobagent` works too
uv run jobagent crawl -s greenhouse -s linkedin   # crawl specific sources, then prefilter
uv run jobagent score --limit 20                  # score queued jobs
uv run jobagent prepare 123                       # cover letter + answers for job 123
uv run jobagent apply 7 --submit                  # fill (and submit) application 7
uv run jobagent cycle                             # crawl → prefilter → score → prepare
uv run jobagent discover                          # find more companies
uv run jobagent browser-login indeed              # sign in once in a visible window
uv run jobagent resume-import ~/Documents/resume.pdf
uv run jobagent budget | doctor | sources
```

## Layout

```
backend/jobagent/
  sources/        adapters (one file each) + generic_sites.py driven by config/sites.yaml
  pipeline/       ingest, prefilter, scoring, prepare, discover, apply/
  llm/            client.py (run_llm + budget), providers.py, one file per provider, prompts.py
  api/            FastAPI routers; main.py serves /api and web/dist
  cli.py          typer commands; tasks.py background runner; scheduler.py
config/           search.yaml, companies.yaml, answer_bank.yaml, sites.yaml (all user-editable)
data/             sqlite db, resume, browser profile, screenshots (git-ignored)
web/              React + Vite + Tailwind UI
```

## Notes on terms of use

API-based sources are used as intended by their operators. Browser sources read pages at low volume with your own
saved session; sites such as LinkedIn, Indeed and Glassdoor prohibit automated access in their terms, so those sources
are off by default and marked *fragile*. Use them at your own discretion.

JobPilot says what it is: plain requests identify as `JobPilot/0.1`, and the browser keeps its own user agent and
automation flag. It does not disguise itself, fake a browser fingerprint or solve CAPTCHAs, and it won't be changed to.
Some sites refuse automated visitors; when one does, Settings shows it as blocked. Turn that source off, use the site's
official API if it has one, or apply there by hand. Disguising a bot on your real account is how accounts get banned.

Everything runs on your own computer with your own accounts: your resume, answers, sign-ins and job data stay in
`data/` and `config/answer_bank.yaml`, which are never committed. You are responsible for what you send: review
applications before submitting, and respect each site's terms.

## License

MIT, see [LICENSE](LICENSE).
