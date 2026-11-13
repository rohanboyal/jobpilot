import type { AnswerBank, Application, ApplicationWithJob, Company, Health, Job, JobDetail, Page, Profile, ProfileAnalysis, ResumeInfo, Run, RunEstimate, RunOptions, ScheduleUpdate, SchedulerInfo, SearchProfile, SearchProfileRow, SettingsAll, Site, SourceInfo, SourcePreset, Stats, Task, TasksResponse, Today } from './types'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

type Params = Record<string, string | number | boolean | null | undefined>

function qs(params?: Params): string {
  if (!params) return ''
  const sp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === '') continue
    sp.set(k, String(v))
  }
  const s = sp.toString()
  return s ? `?${s}` : ''
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: init?.body instanceof FormData
      ? init?.headers
      : { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = (await res.json()) as { detail?: unknown }
      if (typeof body.detail === 'string') detail = body.detail
      else if (body.detail) detail = JSON.stringify(body.detail)
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail || `HTTP ${res.status}`)
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

const post = <T,>(path: string, body?: unknown) =>
  request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })
const put = <T,>(path: string, body: unknown) => request<T>(path, { method: 'PUT', body: JSON.stringify(body) })
const patch = <T,>(path: string, body: unknown) => request<T>(path, { method: 'PATCH', body: JSON.stringify(body) })
const del = <T,>(path: string) => request<T>(path, { method: 'DELETE' })

// stats / health
export const getStats = () => request<Stats>('/stats')
export const getHealth = () => request<Health>('/pipeline/health')

// jobs
export interface JobListParams extends Params {
  status?: string
  source?: string
  source_kind?: string
  q?: string
  where?: string
  unscored?: boolean
  autofill?: boolean
  not_applied?: boolean
  in_progress?: boolean
  applied?: boolean
  include_unstated?: boolean
  posted_within_days?: number
  found_today?: boolean
  found_within_days?: number
  profile_id?: number
  max_experience?: number
  work_mode?: string
  job_type?: string
  min_salary_inr?: number
  salary_shown?: boolean
  min_fit?: number
  min_trust?: number
  remote?: boolean
  company_id?: number
  include_duplicates?: boolean
  sort?: 'fit' | 'newest' | 'posted' | 'prefilter' | 'trust'
  page?: number
  page_size?: number
}
export const listJobs = (params: JobListParams) => request<Page<Job>>(`/jobs${qs(params)}`)
export const listJobSources = (params: { status?: string; include_duplicates?: boolean }) =>
  request<Array<{ source: string; label: string; kind: string; count: number }>>(`/jobs/sources${qs(params)}`)
export const getJob = (id: number) => request<JobDetail>(`/jobs/${id}`)
export const patchJob = (id: number, body: { notes?: string; tags?: string[] }) => patch<Job>(`/jobs/${id}`, body)
export const setJobStatus = (id: number, status: string) => post<Job>(`/jobs/${id}/status`, { status })
export const scoreJob = (id: number) => post<Job>(`/jobs/${id}/score`)
/** cover: 'auto' drafts a letter only when fit is at or above the Prepare threshold; 'always' / 'never' override that. */
export const prepareJob = (id: number, force = false, cover: 'auto' | 'always' | 'never' = 'auto', resumeId?: number) =>
  post<Application>(`/jobs/${id}/prepare${qs({ force, cover, resume_id: resumeId })}`)
export const bulkJobs = (ids: number[], action: 'analyze' | 'prepare' | 'reject' | 'requeue') => post<Task | { updated: number }>('/jobs/bulk', { ids, action })
export const directApply = (id: number, mode: 'ai' | 'direct', resumeId?: number) => post<Task>(`/jobs/${id}/apply`, { mode, resume_id: resumeId ?? null })

// applications
export const listApplications = (params: { status?: string; page?: number; page_size?: number }) =>
  request<Page<ApplicationWithJob>>(`/applications${qs(params)}`)
export const getApplication = (id: number) => request<ApplicationWithJob>(`/applications/${id}`)
export const patchApplication = (id: number, body: { cover_letter?: string; answers?: Record<string, string>; status?: string; outcome?: string; outcome_notes?: string | null; follow_up_at?: string | null; clear_submit_click?: boolean; resume_id?: number }) =>
  patch<Application>(`/applications/${id}`, body)
export const approveApplication = (id: number) => post<Application>(`/applications/${id}/approve`)
/** Writes only the cover letter (one AI call); answers and status stay as they are. */
export const writeCoverLetter = (id: number) => post<Application>(`/applications/${id}/cover`)
export const fillApplication = (id: number) => post<Task>(`/applications/${id}/fill`)
export const submitApplication = (id: number) => post<Task>(`/applications/${id}/submit`)
export const screenshotUrl = (id: number, bust: string | number) => `/api/applications/${id}/screenshot?t=${bust}`

// companies
export const listCompanies = (params: { q?: string; ats?: string; origin?: string; active?: boolean; page?: number; page_size?: number }) =>
  request<Page<Company>>(`/companies${qs(params)}`)
export const createCompany = (body: { name: string; website?: string; careers_url?: string; ats_type?: string; ats_slug?: string; notes?: string }) =>
  post<Company>('/companies', body)
export const detectAts = (url: string) => post<{ ats_type: string | null; ats_slug: string | null }>(`/companies/detect${qs({ url })}`)
export const patchCompany = (id: number, body: Partial<Pick<Company, 'name' | 'website' | 'careers_url' | 'ats_type' | 'ats_slug' | 'is_active' | 'notes'>>) =>
  patch<Company>(`/companies/${id}`, body)
export const deleteCompany = (id: number) => del<{ ok: boolean }>(`/companies/${id}`)
export const crawlCompany = (id: number) => post<Task>(`/companies/${id}/crawl`)

// profile
export const getProfile = () => request<Profile>('/profile')
export const putProfile = (body: Partial<Pick<Profile, 'headline' | 'summary' | 'resume_text' | 'skills' | 'years_experience'>> & { extra?: Record<string, unknown> }) =>
  put<Profile>('/profile', body)
export const uploadResume = (file: File) => {
  const fd = new FormData()
  fd.append('file', file)
  return request<Profile>('/profile/resume', { method: 'POST', body: fd })
}
export const analyzeProfile = () => post<ProfileAnalysis>('/profile/analyze')
export const getStaleResume = () => request<{ since: string | null; jobs: number; drafts: number }>('/profile/stale')
export const refreshWithResume = () => post<Task>('/profile/refresh')
export const getContactSuggestions = () => request<Record<string, string>>('/profile/contact')

// resumes (id 1 is the default)
type ResumeEdit = Partial<Pick<Profile, 'name' | 'headline' | 'summary' | 'resume_text' | 'skills' | 'years_experience'>> & { extra?: Record<string, unknown> }
const withFile = (file: File, extra: Record<string, string> = {}) => {
  const fd = new FormData()
  fd.append('file', file)
  for (const [k, v] of Object.entries(extra)) fd.append(k, v)
  return fd
}
export const listResumes = () => request<ResumeInfo[]>('/resumes')
export const addResume = (file: File) => request<Profile>('/resumes', { method: 'POST', body: withFile(file) })
export const getResume = (id: number) => request<Profile>(`/resumes/${id}`)
export const putResume = (id: number, body: ResumeEdit) => put<Profile>(`/resumes/${id}`, body)
export const replaceResumeFile = (id: number, file: File) => request<Profile>(`/resumes/${id}/file`, { method: 'POST', body: withFile(file) })
export const analyzeResume = (id: number) => post<ProfileAnalysis>(`/resumes/${id}/analyze`)
/** Deletes any resume. The default one is replaced by the next resume, or emptied when it is the only one.
 *  `removed` is the row that went (null when none did). */
export const deleteResume = (id: number) => del<{ ok: boolean; removed: number | null; default: string | null }>(`/resumes/${id}`)

// settings
export const getSettings = () => request<SettingsAll>('/settings')
export const putSearch = (body: SearchProfile) => put<SearchProfile>('/settings/search', body)
export const putAnswerBank = (body: AnswerBank) => put<AnswerBank>('/settings/answer_bank', body)
export const getSources = () => request<SourceInfo[]>('/settings/sources')
export const putSources = (body: Record<string, boolean>) => put<Record<string, boolean>>('/settings/sources', body)
export const putRuntime = (body: Record<string, unknown>) => put<Record<string, unknown>>('/settings/runtime', body)
export const getSites = () => request<Site[]>('/settings/sites')
export const putSites = (sites: Site[]) => put<Site[]>('/settings/sites', sites)
export const addSite = (site: Site) => post<Site[]>('/settings/sites', site)
export const deleteSite = (key: string) => del<Site[]>(`/settings/sites/${encodeURIComponent(key)}`)
export const getSchedule = () => request<SchedulerInfo>('/settings/schedule')
export const putSchedule = (body: ScheduleUpdate) => put<SchedulerInfo>('/settings/schedule', body)
export const applyPlan = (plan: 'light' | 'active' | 'manual') => post<SchedulerInfo>(`/settings/schedule/plan/${plan}`)
export const getSourcePresets = () => request<SourcePreset[]>('/settings/source-presets')
export const applySourcePreset = (id: string) => post<SourcePreset[]>(`/settings/source-presets/${id}`)
export const addCustomAnswer = (q: string, a: string) => post<AnswerBank>('/settings/answer_bank/custom', { q, a })
/** Model ids the chosen AI provider offers (its own free model list; empty when it can't list them). */
export const getLlmModels = () => request<{ models: string[] }>('/settings/llm/models')
export const testLlm = () => post<{ ok: boolean; reply: string; seconds: number }>('/settings/llm/test')

// today
export const getToday = () => request<Today>('/today')

// search profiles
export const listProfiles = () => request<SearchProfileRow[]>('/profiles')
export const createProfile = (body: { name: string; enabled: boolean; search: SearchProfile; resume_id?: number | null }) => post<SearchProfileRow>('/profiles', body)
export const updateProfile = (id: number, body: { name: string; enabled: boolean; search: SearchProfile; resume_id?: number | null }) => put<SearchProfileRow>(`/profiles/${id}`, body)
export const deleteProfile = (id: number) => del<{ ok: boolean }>(`/profiles/${id}`)
/** A new search profile from a resume's analysis, using that resume. */
export const profileFromResume = (resumeId = 1) => post<SearchProfileRow>(`/profiles/from-resume${qs({ resume_id: resumeId })}`)

// runs
export const listRuns = (params: { kind?: string; source?: string; limit?: number }) => request<Run[]>(`/runs${qs(params)}`)
export const getRun = (id: number) => request<Run>(`/runs/${id}`)

// pipeline
export const getTasks = () => request<TasksResponse>('/pipeline/tasks')
export const getTask = (id: string) => request<Task>(`/pipeline/tasks/${id}`)
export const startCrawl = (sources?: string[]) => post<Task>('/pipeline/crawl', { sources: sources ?? null })
export const startScore = (limit?: number) => post<Task>('/pipeline/score', { limit: limit ?? null })
export const startPrepare = (limit?: number) => post<Task>('/pipeline/prepare', { limit: limit ?? null })
export const startDiscover = () => post<Task>('/pipeline/discover')
export const startCollect = (opts: RunOptions = {}) => post<Task>('/pipeline/collect', opts)
export const startAnalyze = (opts: RunOptions = {}) => post<Task>('/pipeline/analyze', { limit: null, ...opts })
export const startCycle = (opts: RunOptions = {}) => post<Task>('/pipeline/cycle', opts)
export const getRunEstimate = (stage: 'cycle' | 'collect' | 'analyze', profileIds: number[] | null, oneByOne: boolean) =>
  request<RunEstimate>(`/pipeline/estimate${qs({ stage, profile_ids: profileIds?.join(','), one_by_one: oneByOne })}`)
export const startSubmitApproved = (limit?: number) => post<Task>('/pipeline/submit-approved', { limit: limit ?? null })
export const stopTasks = (taskId?: string) => post<{ stopping: string[] }>(`/pipeline/stop${qs({ task_id: taskId })}`)
export const browserLogin = (site: string) => post<{ ok: boolean; url: string; note: string }>(`/pipeline/browser-login${qs({ site })}`)
export const forgetBrowserLogin = (site: string) => del<{ ok: boolean }>(`/pipeline/browser-login${qs({ site })}`)
