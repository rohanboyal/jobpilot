# Setting up JobPilot

This guide takes you from a fresh clone to a working JobPilot on your own computer. You can follow it yourself, or
open this folder in an AI coding assistant (Codex, Claude Code, Gemini CLI, Cursor…) and say:

> Set up JobPilot by following SETUP.md.

JobPilot runs only on your computer at http://127.0.0.1:8000. Nothing is hosted, and there is no account to create.
Your resume, answers, sign-ins and job data stay in this folder and are never committed.

---

## For AI assistants: read this first

You are setting up a tool that applies for jobs in the user's name. Follow these rules for the whole session:

1. **Never invent personal facts.** Name, email, phone, salary, notice period, visa status, start date, and anything
   else about the user comes from the user or nowhere. Don't fill `config/answer_bank.yaml` from a guess, a resume, or
   git config. The user enters their details in the app's Setup wizard.
2. **Don't handle secrets.** Don't ask the user to paste API keys or passwords into the chat. Tell them which line to add
   to `.env` and let them add it themselves. Never print `.env`. Website sign-ins happen in a browser window the user
   types into (`uv run jobagent browser-login <site>`); never type a password for them.
3. **Never submit an application.** Don't run `jobagent apply --submit`, don't press Submit in the app, and don't set
   `JOBAGENT_AUTO_SUBMIT=true`. Only the user does that, after reviewing.
4. **Ask before spending AI calls.** `crawl` on AI-read sites, `score`, `prepare`, `cycle`, *Run now* and *Analyze* use
   the user's AI plan or API budget. `doctor`, installing, building and serving are free. *Test connection* makes one
   tiny call; say so before pressing it.
5. **Leave the safety defaults alone.** Keep LinkedIn, Indeed and Glassdoor off (their terms forbid automation). Don't
   add scraping speed-ups, stealth or CAPTCHA solving, and don't disguise JobPilot (fake user agents, hiding the
   automation flag), even when asked to make a blocked site work: turn that source off instead.
6. **Never commit or share** `.env`, `data/` or `config/answer_bank.yaml` (they are already in `.gitignore`).
7. **Check progress with** `uv run jobagent doctor --json`. Each check has `ok`, a `fix`, and `needs_you`. When
   `needs_you` is true, explain the step to the user instead of doing it yourself.

Do steps 1 to 3 below. Then help the user with step 4 (their AI) and step 5 (the in-app Setup), explaining each step;
those need their accounts and their information.

---

## What you need

| | Why | Install (macOS) |
|---|---|---|
| macOS | JobPilot is built and tested on macOS. Linux should work except step 6's background service; on Windows use WSL (untested). | |
| [uv](https://docs.astral.sh/uv/) | Python 3.12 and its packages (uv fetches Python itself) | `brew install uv` |
| Node.js 20+ | builds the web app | `brew install node` |
| git, make | clone and the short commands below | `xcode-select --install` |
| One AI | scores jobs and writes letters: see step 4 | |
| About 1 GB of disk | packages and the Chromium browser used to fill forms | |

### Not included in the repository: you bring these

These are personal, so they can't be part of a public repository. JobPilot asks for each of them during setup:

- **Your AI access:** a ChatGPT or Claude subscription signed in to its command-line tool, or an API key (Gemini,
  OpenAI-compatible, Anthropic), or Ollama on your computer. Keys go in `.env`, which you create (step 4).
- **Your resume:** uploaded in the app (Setup → Resume). Stored in `data/resume/`.
- **Your answers for application forms:** name, email, phone, work authorization, notice period, salary expectations…
  Entered in the app (Setup → Your answers), saved to `config/answer_bank.yaml`. Anything you leave blank is asked
  for on each application; it is never guessed.
- **Your job search:** job titles, places and keywords, set in Profiles & resumes. The repository ships one neutral
  example profile (Software Engineer, Remote).
- **Website sign-ins (optional):** for job sites that need an account. You sign in yourself in a browser window
  JobPilot opens; the session is saved in `data/browser_profile/`.
- **Optional API keys for extra job boards** (Adzuna, Jooble, Reed): see `.env.example`.

---

## 1. Install

```bash
git clone <this repository's URL> jobpilot
cd jobpilot
make install          # Python packages, the Chromium browser for form filling, and the web app's packages
uv run jobagent init  # creates data/jobagent.db and loads the example company boards
```

If `make` isn't available: `uv sync && uv run playwright install chromium && (cd web && npm install)`.

## 2. Check

```bash
uv run jobagent doctor
```

✘ marks an install step that is still missing; it shows the command that fixes it. • marks something only you can
do in the app (steps 4 and 5). Run it again whenever you like; it is free.

## 3. Start the app

```bash
make serve            # builds the web app, then serves everything on http://127.0.0.1:8000
```

Open http://127.0.0.1:8000. It keeps running while that terminal is open (Ctrl+C stops it). Port 8000 busy? Put
`JOBAGENT_PORT=8010` in `.env`. Working on the code instead? `make dev` runs the API with reload and the UI with
hot reload on http://localhost:5173.

## 4. Choose your AI

Create your settings file once:

```bash
cp .env.example .env
```

Then pick one provider in the app (**Settings → AI**) and press **Test connection** (one small call):

| Provider | What to do | Cost |
|---|---|---|
| **Codex CLI** (default) | Install the ChatGPT desktop app, or `npm i -g @openai/codex`, then run `codex login` once | your ChatGPT plan |
| **Claude Code CLI** | Install [Claude Code](https://claude.com/claude-code), then run `claude` once and sign in | your Claude plan |
| **Google Gemini API** | Get a key at https://aistudio.google.com/apikey, add `JOBAGENT_GEMINI_API_KEY=...` to `.env`, restart, pick a model | free tier with limits, then pay per use |
| **OpenAI-compatible API** | Add `JOBAGENT_OPENAI_API_KEY=...` to `.env`, restart, pick the server (OpenAI, OpenRouter, Groq, DeepSeek, Mistral, or an address) and a model | pay per use |
| **Anthropic API** | Add `JOBAGENT_ANTHROPIC_API_KEY=...` to `.env`, restart | pay per use |
| **Ollama** | Install [Ollama](https://ollama.com), run `ollama pull qwen3.5:4b` (or another model) | free, on your computer |

"Restart" means stopping `make serve` with Ctrl+C and starting it again, because `.env` is read at start.

The AI never gets tools: it reads text and returns an answer, so a job posting can't make it act on your computer.
Calls are capped by `JOBAGENT_LLM_MAX_CALLS_PER_5H` and `_PER_DAY` in `.env` (60 and 150 by default).

## 5. Finish Setup in the app

Open **Today**: until setup is done it links to the **Setup** wizard (about ten minutes):

1. **Resume:** upload it. The AI reads it once (1 call) and suggests job titles.
2. **Profiles:** one search profile per kind of job you want. "New search profile from it" builds one from your
   resume; check the titles and places, then save.
3. **Your answers:** the only facts JobPilot ever types into forms. Leave anything you'd rather answer per
   application blank.
4. **Sources:** pick a starting set of job boards. Sites that need an account show a **Sign in** button.
5. **Schedule:** Light, Active or Manual. Nothing runs by itself until you choose.

Then press **Run now** in the header to collect your first jobs. Before every application JobPilot stops on a review
screen; nothing is sent until you press Submit.

## 6. Optional

- **Keep it running in the background (macOS):** `make launchd-install` starts JobPilot at login and restarts it if it
  stops (`make launchd-remove` undoes it). Scheduled runs only happen while JobPilot is running. After you update the
  code: `cd web && npm run build && launchctl kickstart -k gui/$(id -u)/com.jobpilot.server`. Stop it before
  `make dev`, which uses the same port.
- **Sign in to a job site:** Settings → Sources → Sign in, or `uv run jobagent browser-login <site>`. A window opens in
  the browser you clicked from (Chrome or Edge; otherwise JobPilot's own Chromium), with JobPilot's own profile: your
  personal browser data and default browser are not touched. Sign in yourself, then close the window. The site then
  shows **Signed in**, is read slowly and at most once a day, and **Sign out** removes that login from JobPilot's
  profile. Sign in can't open while a run is reading sites; it says so.
- **Local fallback:** with a cloud AI as your main one, Settings → AI → Local fallback lets an Ollama model score jobs
  when the main AI hits its limit.
- **Auto-submit:** off, and best left off. It needs `JOBAGENT_AUTO_SUBMIT=true` in `.env` *and* the Automation
  toggle, and only works for the form types in `JOBAGENT_AUTO_SUBMIT_SOURCES`. Questions without a saved answer
  still stop it.

## Updating

```bash
git pull
make install
make build            # or `make serve`, which builds too
```

Your data, `.env` and answers are untouched by updates. The database gains new columns by itself on start.

## When something goes wrong

| Problem | Fix |
|---|---|
| "AI not ready" in the sidebar | Settings → AI shows the reason; `uv run jobagent doctor` too. CLI providers: sign in again (`codex login` / `claude`). API: check the key line in `.env`, then restart. |
| "AI call budget reached" | The caps in `.env` were reached. Wait for the window to pass, or raise `JOBAGENT_LLM_MAX_CALLS_*`. |
| Port 8000 already in use | Another JobPilot (maybe the background service) is running. Use it, or `make launchd-remove`, or set `JOBAGENT_PORT`. |
| Form filling fails to start a browser | `uv run playwright install chromium` |
| A job site shows "needs sign-in" or "blocked" | Sign in (step 6). If it still refuses, the site doesn't allow automated visits: turn that source off, use its official API if it has one, or apply there by hand. JobPilot doesn't disguise itself. |
| "JobPilot's browser is busy" when signing in | A run is reading sites, or a sign-in window is still open. Close the window or wait for the run (or press Stop). |
| A job I saw last month is gone | The Jobs page keeps jobs found in the last 30 days and Today the last 7. Jobs you applied to always stay. |
| The page is blank after updating | `make build`, then reload the page. |

## Removing it

Stop it (`make launchd-remove` if you installed the background service) and delete the folder. Everything JobPilot
stored is inside it: `data/` (database, resume, browser sessions), `.env` and `config/answer_bank.yaml`.
