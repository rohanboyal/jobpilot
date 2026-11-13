"""Database tables."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def local_midnight_utc() -> datetime:
    """Start of today on this Mac's clock, as naive UTC like the rest of the database."""
    midnight = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight.astimezone(UTC).replace(tzinfo=None)


class JobStatus:
    NEW = "new"                      # just ingested, not yet prefiltered
    FILTERED_OUT = "filtered_out"    # failed the cheap prefilter; never sent to the AI
    QUEUED = "queued"                # waiting for AI scoring
    SCORED = "scored"                # scored but below shortlist threshold
    SHORTLISTED = "shortlisted"      # scored at/above threshold (or user shortlisted)
    REJECTED = "rejected"            # user said no
    APPLYING = "applying"            # an Application row exists and is in progress
    APPLIED = "applied"              # submitted
    EXPIRED = "expired"              # not seen on source for a while / closed

    ALL = (NEW, FILTERED_OUT, QUEUED, SCORED, SHORTLISTED, REJECTED, APPLYING, APPLIED, EXPIRED)


class ApplicationStatus:
    DRAFT = "draft"                  # being prepared (cover letter, answers)
    NEEDS_REVIEW = "needs_review"    # prepared; waiting for the user to approve
    APPROVED = "approved"            # user approved; will be submitted on next apply run
    SUBMITTING = "submitting"
    SUBMITTED = "submitted"
    FAILED = "failed"
    MANUAL = "manual"                # cannot be automated; user applies by hand with prepared material
    WITHDRAWN = "withdrawn"

    ALL = (DRAFT, NEEDS_REVIEW, APPROVED, SUBMITTING, SUBMITTED, FAILED, MANUAL, WITHDRAWN)


class Outcome:
    AWAITING = "awaiting"            # submitted, nothing heard yet
    RESPONDED = "responded"          # heard back (recruiter call, assessment, ...)
    INTERVIEW = "interview"
    OFFER = "offer"
    REJECTED = "rejected"
    NO_RESPONSE = "no_response"      # gave up waiting

    ALL = (AWAITING, RESPONDED, INTERVIEW, OFFER, REJECTED, NO_RESPONSE)
    OPEN = (AWAITING, RESPONDED, INTERVIEW)


def mark_submitted(app: Application, follow_up_days: int = 10) -> None:
    """Start tracking an application once it is sent (by JobPilot or by hand)."""
    from datetime import timedelta

    when = app.submitted_at or utcnow()
    if not app.outcome:
        app.outcome, app.outcome_at = Outcome.AWAITING, when
    if app.follow_up_at is None and app.outcome in Outcome.OPEN:
        app.follow_up_at = when + timedelta(days=follow_up_days)


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    domain: Mapped[str | None] = mapped_column(String(200), index=True)
    website: Mapped[str | None] = mapped_column(String(500))
    careers_url: Mapped[str | None] = mapped_column(String(500))
    ats_type: Mapped[str] = mapped_column(String(40), default="unknown", index=True)
    ats_slug: Mapped[str | None] = mapped_column(String(200))
    origin: Mapped[str] = mapped_column(String(40), default="seed")   # seed | discovered | user | job
    trust_score: Mapped[int] = mapped_column(Integer, default=50)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text)
    last_crawled_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    jobs: Mapped[list[Job]] = relationship(back_populates="company")

    __table_args__ = (Index("ix_companies_ats", "ats_type", "ats_slug", unique=False),)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    dedup_key: Mapped[str | None] = mapped_column(String(64), index=True)   # same role across sources
    duplicate_of: Mapped[int | None] = mapped_column(Integer)              # job id this one duplicates
    source: Mapped[str] = mapped_column(String(40), index=True)
    external_id: Mapped[str | None] = mapped_column(String(200))
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), index=True)
    company_name: Mapped[str] = mapped_column(String(200), index=True)

    title: Mapped[str] = mapped_column(String(300), index=True)
    location: Mapped[str | None] = mapped_column(String(300))
    remote: Mapped[bool | None] = mapped_column(Boolean)
    employment_type: Mapped[str | None] = mapped_column(String(60))
    salary_text: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str] = mapped_column(String(1000))
    apply_url: Mapped[str | None] = mapped_column(String(1000))

    posted_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    status: Mapped[str] = mapped_column(String(30), default=JobStatus.NEW, index=True)
    prefilter_score: Mapped[int | None] = mapped_column(Integer)
    prefilter_reasons: Mapped[list[str] | None] = mapped_column(JSON)

    fit_score: Mapped[int | None] = mapped_column(Integer, index=True)
    fit: Mapped[dict[str, Any] | None] = mapped_column(JSON)          # full AI assessment
    scored_at: Mapped[datetime | None] = mapped_column(DateTime)

    trust_score: Mapped[int | None] = mapped_column(Integer)
    trust_flags: Mapped[list[str] | None] = mapped_column(JSON)

    tags: Mapped[list[str] | None] = mapped_column(JSON)
    notes: Mapped[str | None] = mapped_column(Text)
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    profile_ids: Mapped[list[int] | None] = mapped_column(JSON)       # search profiles this job matched in the prefilter
    # read from the posting by utils/jobinfo.annotate (None = the posting does not say)
    exp_min: Mapped[float | None] = mapped_column(Float)              # years of experience required
    exp_max: Mapped[float | None] = mapped_column(Float)
    work_mode: Mapped[str | None] = mapped_column(String(10))        # remote | hybrid | onsite
    job_type: Mapped[str | None] = mapped_column(String(12))         # full_time | part_time | contract | internship | freelance
    salary_currency: Mapped[str | None] = mapped_column(String(3))
    salary_min: Mapped[float | None] = mapped_column(Float)          # annual
    salary_max: Mapped[float | None] = mapped_column(Float)
    expired_from: Mapped[str | None] = mapped_column(String(20))    # status before it expired, restored if it returns

    company: Mapped[Company | None] = relationship(back_populates="jobs")
    applications: Mapped[list[Application]] = relationship(back_populates="job", cascade="all, delete-orphan")


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    status: Mapped[str] = mapped_column(String(30), default=ApplicationStatus.DRAFT, index=True)
    method: Mapped[str] = mapped_column(String(30), default="browser")   # browser | manual
    ats_type: Mapped[str | None] = mapped_column(String(40))

    cover_letter: Mapped[str | None] = mapped_column(Text)
    answers: Mapped[dict[str, Any] | None] = mapped_column(JSON)     # question -> answer used in the form
    form_plan: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)  # field plan produced by the AI
    unanswered: Mapped[list[str] | None] = mapped_column(JSON)        # questions the agent refused to guess
    resume_path: Mapped[str | None] = mapped_column(String(500))
    screenshot_path: Mapped[str | None] = mapped_column(String(500))

    log: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    confirmation: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime)
    # what happened after applying (tracked by the user): awaiting | responded | interview | offer | rejected | no_response
    outcome: Mapped[str | None] = mapped_column(String(20))
    outcome_at: Mapped[datetime | None] = mapped_column(DateTime)
    outcome_notes: Mapped[str | None] = mapped_column(Text)
    follow_up_at: Mapped[datetime | None] = mapped_column(DateTime)
    drafted_at: Mapped[datetime | None] = mapped_column(DateTime)       # last time the letter/answers were prepared
    worker_pid: Mapped[int | None] = mapped_column(Integer)             # process filling/submitting it (server or CLI)
    resume_id: Mapped[int | None] = mapped_column(Integer)              # the resume uploaded with it (None = row 1)

    job: Mapped[Job] = relationship(back_populates="applications")


class SearchProfileRow(Base):
    """One kind of job the user wants ("Python backend · India"). `data` holds a config.SearchProfile as JSON."""

    __tablename__ = "search_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    resume_id: Mapped[int | None] = mapped_column(Integer)       # which resume this kind of job uses; None = row 1
    # When it last started using another resume (picked one, or its resume was deleted): scores and letters made
    # before then were judged with the old one, so Refresh redoes them.
    resume_changed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Profile(Base):
    """One resume. Row 1 is the default resume; search profiles may each pick another one. Resume text lives here so
    the AI never needs the PDF."""

    __tablename__ = "profile"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str | None] = mapped_column(String(120))
    headline: Mapped[str | None] = mapped_column(String(300))
    summary: Mapped[str | None] = mapped_column(Text)
    resume_text: Mapped[str | None] = mapped_column(Text)
    resume_path: Mapped[str | None] = mapped_column(String(500))
    resume_filename: Mapped[str | None] = mapped_column(String(300))
    skills: Mapped[list[str] | None] = mapped_column(JSON)
    years_experience: Mapped[float | None] = mapped_column(Float)
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Run(Base):
    """One execution of a pipeline stage (crawl of one source, a scoring batch, an apply attempt...)."""

    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(30), index=True)       # crawl | discover | score | prepare | apply
    source: Mapped[str | None] = mapped_column(String(60), index=True)
    status: Mapped[str] = mapped_column(String(20), default="running", index=True)  # running | ok | error | partial
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    stats: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    log: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    worker_pid: Mapped[int | None] = mapped_column(Integer, default=os.getpid)   # the process doing the run


class LlmCall(Base):
    """Every AI call (main provider or local fallback), for budgeting against your plan or API limits."""

    __tablename__ = "llm_calls"

    id: Mapped[int] = mapped_column(primary_key=True)
    purpose: Mapped[str] = mapped_column(String(40), index=True)
    model: Mapped[str | None] = mapped_column(String(40))
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    input_chars: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class Setting(Base):
    """Small key/value store for UI-editable runtime toggles (e.g. which sources are enabled)."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
