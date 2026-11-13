"""Runtime settings (env / .env) and loaders for the editable YAML config files."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import AliasChoices, BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Environment-driven settings. Prefix every variable with JOBAGENT_ (see .env.example)."""

    model_config = SettingsConfigDict(env_prefix="JOBAGENT_", env_file=PROJECT_ROOT / ".env", extra="ignore")

    # paths
    data_dir: Path = PROJECT_ROOT / "data"
    config_dir: Path = PROJECT_ROOT / "config"
    web_dist: Path = PROJECT_ROOT / "web" / "dist"

    # server
    host: str = "127.0.0.1"
    port: int = 8000

    # AI. Which provider and model is picked in Settings -> AI (llm.provider); the default is the Codex CLI signed
    # in with a ChatGPT plan (no API key, no per-token bill). API keys live here, never in the database.
    llm_bin: str = ""                     # empty = find `codex` on PATH or inside the ChatGPT / Codex app
    llm_model: str = ""                   # Codex only, when Settings leaves the model empty; empty = Codex's default
    claude_bin: str = ""                  # empty = find `claude` (Claude Code) on PATH or in ~/.local/bin
    openai_api_key: str = Field("", validation_alias=AliasChoices("JOBAGENT_OPENAI_API_KEY", "OPENAI_API_KEY"))
    anthropic_api_key: str = Field("", validation_alias=AliasChoices("JOBAGENT_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"))
    gemini_api_key: str = Field("", validation_alias=AliasChoices("JOBAGENT_GEMINI_API_KEY", "GEMINI_API_KEY"))
    llm_effort: str = "low"               # reasoning effort: minimal | low | medium | high
    llm_timeout_s: int = 240
    llm_max_calls_per_5h: int = 60        # soft budget so JobPilot never drains your plan's 5-hour window
    llm_max_calls_per_day: int = 150

    # optional local fallback (only when the main AI hits a limit; enable it in Settings)
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3.5:4b"

    # browser automation
    browser_headless: bool = True
    browser_slow_mo_ms: int = 0

    # scheduler (only while the API server is running). Run times and the on/off switch live in Settings.
    scheduler_enabled: bool = True        # master switch; false = never start the scheduler at all

    # applying
    auto_submit: bool = False             # when False the agent fills forms but never clicks submit
    auto_submit_sources: str = "greenhouse,lever,ashby"  # comma list; applies only when auto_submit is True
    apply_pause_s: float = 1.5            # polite delay between form interactions

    # optional third-party keys (all free tiers); features stay off without them
    adzuna_app_id: str = ""
    adzuna_app_key: str = ""
    jooble_api_key: str = ""
    reed_api_key: str = ""                # free key: reed.co.uk/developers/jobseeker

    # per-source limits
    source_timeout_s: int = 40
    max_jobs_per_source_run: int = 1000   # paging cap for sources that page (whole-board payloads are never cut)
    max_detail_fetches_per_run: int = 100 # for sources needing a second request per job
    max_company_pages_per_run: int = 10   # custom careers pages extracted with the AI per run

    @property
    def db_path(self) -> Path:
        return self.data_dir / "jobagent.db"

    @property
    def browser_profile_dir(self) -> Path:
        return self.data_dir / "browser_profile"

    @property
    def resume_dir(self) -> Path:
        return self.data_dir / "resume"

    @property
    def screenshots_dir(self) -> Path:
        return self.data_dir / "screenshots"

    @property
    def llm_cwd(self) -> Path:
        return self.data_dir / "llm_cwd"

    @property
    def auto_submit_source_set(self) -> set[str]:
        return {s.strip() for s in self.auto_submit_sources.split(",") if s.strip()}

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.browser_profile_dir, self.resume_dir, self.screenshots_dir, self.llm_cwd):
            d.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    return s


# ---------------------------------------------------------------------------
# YAML config models
# ---------------------------------------------------------------------------


class SearchProfile(BaseModel):
    roles: list[str] = Field(default_factory=lambda: ["Software Engineer"])
    title_keywords: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    remote_ok: bool = True
    onsite_ok: bool = True
    countries: list[str] = Field(default_factory=list)
    seniority: list[str] = Field(default_factory=list)
    max_age_days: int = 14
    min_prefilter_score: int = 30
    min_fit_score: int = 70
    # Standard job-portal filters. A posting that does not state something always passes that filter.
    experience_min: float = 0              # hide jobs whose stated maximum experience is below this
    experience_max: float | None = None    # hide jobs requiring more years than this (None = no limit)
    hybrid_ok: bool = True
    job_types: list[str] = Field(default_factory=list)   # full_time, part_time, contract, internship, freelance; [] = any
    min_salary_inr: float | None = None    # annual INR (e.g. 600000 = 6 LPA); jobs stating less are hidden
    min_salary_usd: float | None = None    # annual USD
    exclude_companies: list[str] = Field(default_factory=list)
    must_mention: list[str] = Field(default_factory=list)       # description must contain one of these
    must_not_mention: list[str] = Field(default_factory=list)   # description must contain none of these


class CompanySeed(BaseModel):
    name: str
    ats: str = "custom"
    slug: str | None = None
    website: str | None = None
    careers_url: str | None = None


class AnswerBank(BaseModel):
    identity: dict[str, str] = Field(default_factory=dict)
    eligibility: dict[str, str] = Field(default_factory=dict)
    preferences: dict[str, str] = Field(default_factory=dict)
    custom: list[dict[str, str]] = Field(default_factory=list)

    def flat(self) -> dict[str, str]:
        """All filled answers as one key -> value map (empty values removed)."""
        out: dict[str, str] = {}
        for section in (self.identity, self.eligibility, self.preferences):
            out.update({k: v for k, v in section.items() if v})
        for i, qa in enumerate(self.custom):
            if qa.get("a"):
                out[f"custom_{i}: {qa.get('q', '')}"] = qa["a"]
        return out


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, sort_keys=False, allow_unicode=True)


def load_search_profile(settings: Settings | None = None) -> SearchProfile:
    settings = settings or get_settings()
    return SearchProfile.model_validate(_read_yaml(settings.config_dir / "search.yaml"))


def save_search_profile(profile: SearchProfile, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    _write_yaml(settings.config_dir / "search.yaml", profile.model_dump())


def load_company_seeds(settings: Settings | None = None) -> list[CompanySeed]:
    settings = settings or get_settings()
    raw = _read_yaml(settings.config_dir / "companies.yaml").get("companies", [])
    return [CompanySeed.model_validate(c) for c in raw]


def load_answer_bank(settings: Settings | None = None) -> AnswerBank:
    """Your answers (config/answer_bank.yaml, kept out of git) or, before the first save, the blank template."""
    settings = settings or get_settings()
    path = settings.config_dir / "answer_bank.yaml"
    if not path.exists():
        path = settings.config_dir / "answer_bank.example.yaml"
    return AnswerBank.model_validate(_read_yaml(path))


def save_answer_bank(bank: AnswerBank, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    _write_yaml(settings.config_dir / "answer_bank.yaml", bank.model_dump())
