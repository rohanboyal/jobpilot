export type JobStatus =
  | 'new' | 'filtered_out' | 'queued' | 'scored' | 'shortlisted' | 'rejected' | 'applying' | 'applied' | 'expired'
export const JOB_STATUSES: JobStatus[] = ['new', 'filtered_out', 'queued', 'scored', 'shortlisted', 'rejected', 'applying', 'applied', 'expired']

export type AppStatus = 'draft' | 'needs_review' | 'approved' | 'submitting' | 'submitted' | 'failed' | 'manual' | 'withdrawn'
export const APP_STATUSES: AppStatus[] = ['needs_review', 'approved', 'submitted', 'manual', 'failed', 'withdrawn', 'draft', 'submitting']

export type RunStatus = 'running' | 'ok' | 'error' | 'partial'

export interface Fit {
  fit_score: number
  verdict: 'apply' | 'maybe' | 'skip'
  one_liner: string
  strengths: string[]
  gaps: string[]
  seniority_match: string
  location_match: string
  salary_note?: string
  pitch: string
  legit_confidence: number
  red_flags: string[]
  tags?: string[]
}

export interface Job {
  id: number
  source: string
  company_id: number | null
  company_name: string
  title: string
  location: string | null
  remote: boolean | null
  employment_type: string | null
  salary_text: string | null
  url: string
  apply_url: string | null
  posted_at: string | null
  discovered_at: string
  last_seen_at: string
  status: JobStatus
  prefilter_score: number | null
  prefilter_reasons: string[] | null
  fit_score: number | null
  fit: Fit | null
  scored_at: string | null
  trust_score: number | null
  trust_flags: string[] | null
  tags: string[] | null
  notes: string | null
  duplicate_of: number | null
  has_description: boolean
  application_id: number | null
  application_status: AppStatus | null
  application_outcome: Outcome | null
  profile_ids: number[] | null
  apply_method: 'autofill' | 'site' | 'manual'
  exp_min: number | null
  exp_max: number | null
  work_mode: 'remote' | 'hybrid' | 'onsite' | null
  job_type: 'full_time' | 'part_time' | 'contract' | 'internship' | 'freelance' | null
  salary_currency: string | null
  salary_min: number | null
  salary_max: number | null
}

export interface Company {
  id: number
  name: string
  domain: string | null
  website: string | null
  careers_url: string | null
  ats_type: string
  ats_slug: string | null
  origin: string
  trust_score: number
  is_active: boolean
  notes: string | null
  last_crawled_at: string | null
  last_error: string | null
  created_at: string
  job_count: number
}

export interface Application {
  id: number
  job_id: number
  status: AppStatus
  method: 'browser' | 'manual'
  ats_type: string | null
  cover_letter: string | null
  answers: Record<string, string> | null
  form_plan: Array<Record<string, unknown>> | null
  unanswered: string[] | null
  resume_path: string | null
  resume_id: number | null
  screenshot_path: string | null
  log: string | null
  error: string | null
  confirmation: string | null
  created_at: string
  updated_at: string
  submitted_at: string | null
  outcome: Outcome | null
  outcome_at: string | null
  outcome_notes: string | null
  follow_up_at: string | null
}

export type Outcome = 'awaiting' | 'responded' | 'interview' | 'offer' | 'rejected' | 'no_response'

export interface ApplicationWithJob extends Application {
  job: Job
}

export interface JobDetail extends Job {
  description: string | null
  raw: Record<string, unknown> | null
  company: Company | null
  applications: Application[]
}

export interface Profile {
  id: number
  name: string | null
  headline: string | null
  summary: string | null
  resume_text: string | null
  resume_path: string | null
  resume_filename: string | null
  skills: string[] | null
  years_experience: number | null
  extra: Record<string, unknown> | null
  updated_at: string
}

export interface ProfileAnalysis {
  headline: string
  summary: string
  skills: string[]
  years_experience: number
  suggested_title_keywords?: string[]
  suggested_roles: string[]
  seniority: string
}

export interface Run {
  id: number
  kind: 'crawl' | 'discover' | 'score' | 'prepare' | 'apply' | string
  source: string | null
  status: RunStatus
  started_at: string
  finished_at: string | null
  stats: Record<string, unknown> | null
  error: string | null
  log?: string | null
}

export interface SourceInfo {
  name: string
  label: string
  kind: 'ats' | 'board' | 'browser'
  description: string
  enabled: boolean
  default_enabled: boolean
  needs_browser: boolean
  uses_ai: boolean
  fragile: boolean
  login_url: string | null
  signed_in: boolean
  last_run: Run | null
  job_count: number
  health: 'ok' | 'idle' | 'empty' | 'blocked' | 'failing' | 'never'
  health_note: string
}

export interface Site {
  key: string
  label: string
  search_url: string
  login_url?: string | null
  needs_login?: boolean
  enabled?: boolean
  countries?: string[]
  pages?: number
  read_details?: boolean
  notes?: string | null
  card_selector?: string | null
  title_selector?: string | null
  company_selector?: string | null
  location_selector?: string | null
  link_selector?: string | null
}

export interface SearchProfile {
  roles: string[]
  title_keywords: string[]
  exclude_keywords: string[]
  skills: string[]
  locations: string[]
  remote_ok: boolean
  onsite_ok: boolean
  countries: string[]
  seniority: string[]
  max_age_days: number
  min_prefilter_score: number
  min_fit_score: number
  experience_min: number
  experience_max: number | null
  hybrid_ok: boolean
  job_types: string[]
  min_salary_inr: number | null
  min_salary_usd: number | null
  exclude_companies: string[]
  must_mention: string[]
  must_not_mention: string[]
}

export interface ResumeExperience { title: string; company: string; location?: string; start: string; end: string; employment_type?: string; highlights: string[] }
export interface ResumeEducation { institution: string; degree: string; field?: string; start?: string; end?: string; grade?: string }
export interface ResumeProject { name: string; summary: string; tech?: string[]; link?: string }
export interface ResumeContact { full_name?: string; email?: string; phone?: string; location?: string; linkedin?: string; github?: string; portfolio?: string }
export interface ProfileExtra {
  suggested_roles?: string[]
  suggested_title_keywords?: string[]
  seniority?: string
  experience?: ResumeExperience[]
  education?: ResumeEducation[]
  projects?: ResumeProject[]
  certifications?: string[]
  languages?: string[]
  contact?: ResumeContact
}

export interface AnswerBank {
  identity: Record<string, string>
  eligibility: Record<string, string>
  preferences: Record<string, string>
  custom: Array<{ q: string; a: string }>
}

export interface Budget {
  window_5h: { used: number; max: number }
  day: { used: number; max: number }
  provider: string
  provider_label?: string
  model: string
  effort: string
  ok: boolean
}

export interface StageConfig { enabled: boolean; days: number[]; time: string; limit?: number; next_run_at?: string | null }
export interface PrepareConfig { enabled: boolean; limit: number; min_fit: number }
export type ApplyMode = 'approve' | 'auto' | 'manual'

export interface SchedulerInfo {
  available: boolean
  paused: boolean
  timezone: string
  stages: { collect: StageConfig; analyze: StageConfig }
  prepare: PrepareConfig
  apply_mode: ApplyMode
  auto_submit_allowed: boolean
  next_run_at: string | null
  collect_ai_per_run: number
  running: string[]
}

export interface ScheduleUpdate {
  paused?: boolean
  collect?: Partial<StageConfig>
  analyze?: Partial<StageConfig>
  prepare?: Partial<PrepareConfig>
  apply_mode?: ApplyMode
}

export interface SearchProfileRow {
  id: number
  name: string
  enabled: boolean
  search: SearchProfile
  resume_id: number | null       // null = the default resume
  matching: number
  updated_at: string | null
}

/** One uploaded resume. The default one is used by profiles that don't pick another. */
export interface ResumeInfo {
  id: number
  name: string
  is_default: boolean
  resume_filename: string | null
  has_text: boolean
  uploaded_at: string | null
  updated_at: string
  headline: string | null
  skills: string[]
  years_experience: number | null
  used_by: Array<{ id: number; name: string }>
}

/** Which search profiles a run covers (none = every active one), and whether each gets its own pass. */
export interface RunOptions { profile_ids?: number[] | null; one_by_one?: boolean; limit?: number | null }
export interface RunEstimate { collect_ai: number; analyze_ai: number; total_ai: number; left: number }

export interface SourcePreset { id: string; name: string; desc: string; count: number; active: boolean }

/** A named set of Jobs page filters, stored as the page's URL query (view, q, fit, mode, …). */
export interface SavedView { id: string; name: string; query: string }

export interface Today {
  approvals: Array<ApplicationWithJob>
  manual_count: number
  recent_days: number
  older_approvals: number
  follow_ups: Array<ApplicationWithJob>
  outcomes: Partial<Record<Outcome, number>>
  sources_attention: Array<{ source: string; health: string; note: string }>
  stale_resume: { jobs: number; drafts: number }
  strong_matches: Job[]
  min_fit: number
  stages: {
    collect: StageConfig & { new_today: number; matched_today: number; last_run_at: string | null }
    analyze: StageConfig & { waiting: number; last_run_at: string | null }
    prepare: PrepareConfig & { drafted_7d: number }
    apply: { mode: ApplyMode; submitted_7d: number }
  }
  paused: boolean
  scheduler_available: boolean
  week: { collected: number; analyzed: number; submitted: number; ai_calls: number }
  budget: Budget
  setup: { completed: boolean; has_resume: boolean; answers_filled: number; answers_needed: number; profiles: number }
}

export interface DirectApplyResult { application_id: number; status: AppStatus; unanswered?: string[]; manual: boolean }

export type ProviderKey = 'codex' | 'claude' | 'openai' | 'gemini' | 'anthropic' | 'ollama'
/** The main AI's readiness, without spending a call. Fields depend on the provider. */
export interface PrimaryStatus { ok: boolean; error?: string; path?: string; version?: string; signed_in?: boolean; model?: string; base_url?: string; key?: string }
export interface OllamaStatus { ok: boolean; running: boolean; models: string[]; model?: string; error?: string }
export interface ProviderInfo { key: ProviderKey; label: string; kind: 'plan' | 'api' | 'local'; needs: string }
export interface ProviderStatus {
  provider: ProviderKey; label: string; model: string; base_url: string
  primary: PrimaryStatus; ollama: OllamaStatus; providers: ProviderInfo[]
}

export interface SettingsAll {
  search: SearchProfile
  answer_bank: AnswerBank
  sources: SourceInfo[]
  sites: Site[]
  runtime: Record<string, unknown>
  runtime_defaults: Record<string, unknown>
  env: Record<string, unknown>
  llm: ProviderStatus & { budget: Budget }
  scheduler: SchedulerInfo
}

export interface Task {
  id: string
  kind: string
  label: string
  status: 'running' | 'ok' | 'error' | 'cancelled'
  stopping?: boolean
  started_at: string
  finished_at: string | null
  result: unknown
  error: string | null
  log_tail: string[]
}

export interface TasksResponse {
  tasks: Task[]
  running: string[]
  scheduler: SchedulerInfo
}

export interface Stats {
  jobs: { total: number; new_7d: number; by_status: Record<string, number>; by_source: Record<string, number> }
  funnel: { discovered: number; passed_prefilter: number; scored: number; shortlisted: number; applied: number; heard_back: number; interviews: number; offers: number }
  applications: { by_status: Record<string, number>; needs_review: number; submitted: number }
  discovered_per_day: Array<{ day: string; count: number }>
  top_shortlisted: Job[]
  last_runs: Run[]
  budget: Budget
  llm_24h: Record<string, number>
  queued_for_scoring: number
}

export interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface Health {
  ok: boolean
  llm: ProviderStatus
  budget: Budget
  db: string
  scheduler: SchedulerInfo
  running: string[]
}
