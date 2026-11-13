"""Pydantic response/request models for the API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class CompanyOut(ORM):
    id: int
    name: str
    domain: str | None = None
    website: str | None = None
    careers_url: str | None = None
    ats_type: str
    ats_slug: str | None = None
    origin: str
    trust_score: int
    is_active: bool
    notes: str | None = None
    last_crawled_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime
    job_count: int = 0


class CompanyIn(BaseModel):
    name: str
    website: str | None = None
    careers_url: str | None = None
    ats_type: str = "custom"
    ats_slug: str | None = None
    notes: str | None = None


class CompanyPatch(BaseModel):
    name: str | None = None
    website: str | None = None
    careers_url: str | None = None
    ats_type: str | None = None
    ats_slug: str | None = None
    is_active: bool | None = None
    notes: str | None = None


class ApplicationOut(ORM):
    id: int
    job_id: int
    status: str
    method: str
    ats_type: str | None = None
    cover_letter: str | None = None
    answers: dict[str, Any] | None = None
    form_plan: list[dict[str, Any]] | None = None
    unanswered: list[str] | None = None
    resume_path: str | None = None
    resume_id: int | None = None
    screenshot_path: str | None = None
    log: str | None = None
    error: str | None = None
    confirmation: str | None = None
    created_at: datetime
    updated_at: datetime
    submitted_at: datetime | None = None
    outcome: str | None = None
    outcome_at: datetime | None = None
    outcome_notes: str | None = None
    follow_up_at: datetime | None = None


class ApplicationWithJob(ApplicationOut):
    job: JobOut


class ApplicationPatch(BaseModel):
    cover_letter: str | None = None
    answers: dict[str, Any] | None = None
    status: str | None = None
    outcome: str | None = None
    outcome_notes: str | None = None
    follow_up_at: datetime | None = None
    clear_submit_click: bool = False      # the user checked: an unclear submit did not go through
    resume_id: int | None = None          # upload this resume with it instead


class JobOut(ORM):
    id: int
    source: str
    company_id: int | None = None
    company_name: str
    title: str
    location: str | None = None
    remote: bool | None = None
    employment_type: str | None = None
    salary_text: str | None = None
    url: str
    apply_url: str | None = None
    posted_at: datetime | None = None
    discovered_at: datetime
    last_seen_at: datetime
    status: str
    prefilter_score: int | None = None
    prefilter_reasons: list[str] | None = None
    fit_score: int | None = None
    fit: dict[str, Any] | None = None
    scored_at: datetime | None = None
    trust_score: int | None = None
    trust_flags: list[str] | None = None
    tags: list[str] | None = None
    notes: str | None = None
    duplicate_of: int | None = None
    has_description: bool = False
    application_id: int | None = None
    application_status: str | None = None
    profile_ids: list[int] | None = None
    application_outcome: str | None = None
    apply_method: str = "site"
    exp_min: float | None = None
    exp_max: float | None = None
    work_mode: str | None = None
    job_type: str | None = None
    salary_currency: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None


class JobDetail(JobOut):
    description: str | None = None
    raw: dict[str, Any] | None = None
    company: CompanyOut | None = None
    applications: list[ApplicationOut] = Field(default_factory=list)


class JobPatch(BaseModel):
    notes: str | None = None
    tags: list[str] | None = None


class StatusChange(BaseModel):
    status: str


class Page(BaseModel):
    items: list[Any]
    total: int
    page: int
    page_size: int


class ProfileOut(ORM):
    id: int
    name: str | None = None
    headline: str | None = None
    summary: str | None = None
    resume_text: str | None = None
    resume_path: str | None = None
    resume_filename: str | None = None
    skills: list[str] | None = None
    years_experience: float | None = None
    extra: dict[str, Any] | None = None
    updated_at: datetime


class ProfileIn(BaseModel):
    name: str | None = None
    headline: str | None = None
    summary: str | None = None
    resume_text: str | None = None
    skills: list[str] | None = None
    years_experience: float | None = None
    extra: dict[str, Any] | None = None     # merged key by key (experience, education, projects, certifications, contact)


class RunOut(ORM):
    id: int
    kind: str
    source: str | None = None
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    stats: dict[str, Any] | None = None
    error: str | None = None


class RunDetail(RunOut):
    log: str | None = None


class SourceOut(BaseModel):
    name: str
    label: str
    kind: str
    description: str
    enabled: bool
    default_enabled: bool
    needs_browser: bool
    uses_ai: bool
    fragile: bool
    login_url: str | None = None
    signed_in: bool = False
    last_run: RunOut | None = None
    job_count: int = 0
    health: str = "never"
    health_note: str = ""


class SiteIn(BaseModel):
    key: str
    label: str
    search_url: str
    login_url: str | None = None
    needs_login: bool = False
    enabled: bool = True
    countries: list[str] = Field(default_factory=list)
    pages: int = 1
    read_details: bool = True
    notes: str | None = None
    card_selector: str | None = None
    title_selector: str | None = None
    company_selector: str | None = None
    location_selector: str | None = None
    link_selector: str | None = None


class PipelineRequest(BaseModel):
    sources: list[str] | None = None
    limit: int | None = None
    profile_ids: list[int] | None = None    # the profiles this run covers (None = every enabled one)
    one_by_one: bool = False                # a separate pass for each profile instead of one for all


ApplicationWithJob.model_rebuild()
