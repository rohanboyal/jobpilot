import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { Ban, Bookmark, Briefcase, MapPin, RotateCcw, Search, SlidersHorizontal, Sparkles, Wand2, X } from 'lucide-react'
import { clsx } from 'clsx'
import { ApiError, bulkJobs, getSettings, listJobSources, listJobs, listProfiles, putRuntime, type JobListParams } from '../api'
import type { Job, SavedView } from '../types'
import { useToast } from '../lib/toast'
import { errorMessage } from '../lib/tasks'
import { fmtRelative } from '../lib/format'
import { Button, Dialog, EmptyState, Pagination, Spinner } from '../components/ui'
import { AppStatusChip, FitBadge, SourceChip } from '../components/status'
import JobDrawer from '../components/JobDrawer'
import ApplyDialog from '../components/ApplyDialog'
import TaskBanner from '../components/TaskBanner'
import { OutcomeChip } from '../components/OutcomeTracker'

const OPEN = 'queued,scored,shortlisted'
type ViewId = 'new' | 'strong' | 'progress' | 'applied' | 'skipped' | 'filtered'
type Bulk = 'pick' | 'requeue' | 'none'
const VIEWS: Array<{ id: ViewId; label: string; params: JobListParams; bulk: Bulk; empty: string }> = [
  { id: 'new', label: 'All new', params: { status: OPEN, not_applied: true }, bulk: 'pick', empty: 'Run Collect from the header or wait for the next scheduled run.' },
  { id: 'strong', label: 'Strong matches', params: { status: 'scored,shortlisted', min_fit: 70, not_applied: true }, bulk: 'pick', empty: 'Strong matches appear after Analyze scores jobs at 70 or higher.' },
  { id: 'progress', label: 'In progress', params: { in_progress: true }, bulk: 'none', empty: 'Jobs you start applying to stay here until the application is sent.' },
  { id: 'applied', label: 'Applied', params: { applied: true }, bulk: 'none', empty: 'Jobs you applied to show here, with what happened next.' },
  { id: 'skipped', label: 'Not interested', params: { status: 'rejected' }, bulk: 'requeue', empty: 'Jobs you mark as not interested show here.' },
  { id: 'filtered', label: 'Filtered out', params: { status: 'filtered_out', include_duplicates: true }, bulk: 'requeue', empty: 'Jobs the free prefilter dropped show here, with the reason.' },
]
const PAGE = 50
// URL keys that narrow the list (view, page, job and saved are handled separately).
const FILTER_KEYS = ['q', 'where', 'profile', 'fit', 'posted', 'found', 'exp', 'mode', 'type', 'salary', 'src', 'autofill', 'unstated', 'sort'] as const

type Opt = [value: string, label: string]
const FIT: Opt[] = [['', 'Any fit'], ['scored', 'Analyzed'], ['unscored', 'Not analyzed yet'], ['50', 'Fit 50+'], ['70', 'Fit 70+'], ['85', 'Fit 85+']]
const POSTED: Opt[] = [['', 'Any date'], ['1', 'Posted in 24 hours'], ['3', 'Posted in 3 days'], ['7', 'Posted in 7 days'], ['14', 'Posted in 14 days'], ['30', 'Posted in 30 days']]
const FOUND: Opt[] = [['found:today', 'Found today'], ['found:3', 'Found in 3 days'], ['found:7', 'Found in 7 days']]
const EXP: Opt[] = [['', 'Any experience'], ['0', 'Fresher'], ['1', 'Up to 1 year'], ['2', 'Up to 2 years'], ['3', 'Up to 3 years'], ['5', 'Up to 5 years'], ['8', 'Up to 8 years']]
const MODE: Opt[] = [['', 'Any work mode'], ['remote', 'Remote'], ['hybrid', 'Hybrid'], ['onsite', 'On-site'], ['remote,hybrid', 'Remote or hybrid']]
const TYPE: Opt[] = [['', 'Any job type'], ['full_time', 'Full-time'], ['contract', 'Contract'], ['part_time', 'Part-time'], ['internship', 'Internship'], ['freelance', 'Freelance']]
const SALARY: Opt[] = [['', 'Any salary'], ['shown', 'Salary shown'], ['5', '₹5 LPA+'], ['10', '₹10 LPA+'], ['15', '₹15 LPA+'], ['20', '₹20 LPA+'], ['30', '₹30 LPA+']]
const KINDS: Opt[] = [['kind:ats', 'Company job boards'], ['kind:board', 'Job boards'], ['kind:browser', 'Browser sites']]
const SORT: Opt[] = [['fit', 'Best fit'], ['newest', 'Newest found'], ['posted', 'Recently posted']]
const labelOf = (opts: Opt[], v: string) => opts.find((o) => o[0] === v)?.[1] ?? v

/** API params for one view with the filters in the URL. */
function toParams(sp: URLSearchParams, view: ViewId, page = 1, pageSize = PAGE): JobListParams {
  const g = (k: string) => sp.get(k) ?? ''
  const p: JobListParams = { ...(VIEWS.find((v) => v.id === view) ?? VIEWS[0]).params, page, page_size: pageSize }
  p.sort = (g('sort') || 'fit') as JobListParams['sort']
  if (g('q')) p.q = g('q')
  if (g('where')) p.where = g('where')
  if (g('profile')) p.profile_id = Number(g('profile'))
  const fit = g('fit')
  if (fit === 'unscored') {
    p.unscored = true
    if (view === 'new') p.status = 'queued'      // the Analyze queue, the same jobs Today counts as waiting
  }
  else if (fit === 'scored') p.unscored = false
  else if (fit) p.min_fit = Math.max(Number(fit), p.min_fit ?? 0)
  if (g('posted')) p.posted_within_days = Number(g('posted'))
  if (g('found') === 'today') p.found_today = true
  else if (g('found')) p.found_within_days = Number(g('found'))
  if (g('exp')) p.max_experience = Number(g('exp'))
  if (g('mode')) p.work_mode = g('mode')
  if (g('type')) p.job_type = g('type')
  const salary = g('salary')
  if (salary === 'shown') p.salary_shown = true
  else if (salary) p.min_salary_inr = Number(salary) * 100_000
  const src = g('src')
  if (src.startsWith('kind:')) p.source_kind = src.slice(5)
  else if (src) p.source = src
  if (g('autofill')) p.autofill = true
  if (hidesUnstated(sp)) p.include_unstated = false
  return p
}

const liveParams = () => new URLSearchParams(window.location.search)

/** Experience, work mode, job type and salary filters hide jobs that don't say, unless the user asks to keep them. */
const usesStated = (sp: URLSearchParams) => ['exp', 'mode', 'type'].some((k) => sp.get(k)) || /^\d+$/.test(sp.get('salary') ?? '')
const hidesUnstated = (sp: URLSearchParams) => usesStated(sp) && !sp.get('unstated')

/** Links and bookmarks from before the redesign: ?view=remote, ?view=quick, ?kind=, ?salary=1, ?status=. */
function upgradeLegacy(sp: URLSearchParams): URLSearchParams | null {
  const next = new URLSearchParams(sp)
  const view = sp.get('view')
  if (view === 'remote') { next.set('view', 'new'); next.set('mode', 'remote') }
  if (view === 'quick') { next.set('view', 'new'); next.set('autofill', '1') }
  if (sp.get('kind')) { next.set('src', `kind:${sp.get('kind')}`); next.delete('kind') }
  if (sp.get('salary') === '1') next.set('salary', 'shown')
  if (sp.get('remote')) { next.set('mode', 'remote'); next.delete('remote') }
  if (sp.has('status')) { if (sp.get('status') === 'shortlisted') next.set('view', 'strong'); next.delete('status') }
  return next.toString() === sp.toString() ? null : next
}

export default function Jobs() {
  const qc = useQueryClient()
  const toast = useToast()
  const [sp, setSp] = useSearchParams()
  const loc = useLocation()
  const nav = useNavigate()
  const view = (VIEWS.some((v) => v.id === sp.get('view')) ? sp.get('view') : 'new') as ViewId
  const meta = VIEWS.find((v) => v.id === view)!
  const page = Number(sp.get('page') ?? '1')
  const jobId = sp.get('job') ? Number(sp.get('job')) : null
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [applying, setApplying] = useState<Job | null>(null)
  const [saveOpen, setSaveOpen] = useState(false)
  const [moreOpen, setMoreOpen] = useState(false)
  const [qDraft, setQDraft] = useState(sp.get('q') ?? '')
  const [whereDraft, setWhereDraft] = useState(sp.get('where') ?? '')
  useEffect(() => setQDraft(sp.get('q') ?? ''), [sp.get('q')]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => setWhereDraft(sp.get('where') ?? ''), [sp.get('where')]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { const up = upgradeLegacy(sp); if (up) setSp(up, { replace: true }) }, [sp, setSp])

  /** Change URL keys; any filter change resets the page and leaves the saved view it came from. Starts from the live
   * URL, not this render's copy, so quick successive changes (a debounced search, then a select) never undo each other. */
  const set = (patch: Record<string, string | null>) => {
    const next = liveParams()
    for (const [k, v] of Object.entries(patch)) { if (v === null || v === '') next.delete(k); else next.set(k, v) }
    if (!('page' in patch)) next.delete('page')
    if (Object.keys(patch).some((k) => (FILTER_KEYS as readonly string[]).includes(k))) next.delete('saved')
    setSp(next, { replace: true })
    if (!('job' in patch)) setSelected(new Set())
  }
  useEffect(() => {
    const t = setTimeout(() => {
      if (qDraft !== (sp.get('q') ?? '') || whereDraft !== (sp.get('where') ?? '')) set({ q: qDraft.trim(), where: whereDraft.trim() })
    }, 350)
    return () => clearTimeout(t)
  }, [qDraft, whereDraft]) // eslint-disable-line react-hooks/exhaustive-deps

  const filterKey = FILTER_KEYS.map((k) => `${k}=${sp.get(k) ?? ''}`).join('&')
  const countKey = filterKey.replace(/(^|&)sort=[^&]*/, '')       // the order never changes a count
  const params = useMemo(() => toParams(sp, view, page), [filterKey, view, page]) // eslint-disable-line react-hooks/exhaustive-deps
  const jobs = useQuery({ queryKey: ['jobs', params], queryFn: () => listJobs(params), placeholderData: (prev) => prev })
  const counts = useQueries({
    queries: VIEWS.map((v) => ({
      queryKey: ['jobs-count', v.id, countKey], staleTime: 30_000,
      queryFn: () => listJobs(toParams(sp, v.id, 1, 1)).then((r) => r.total),
    })),
  })
  // How many more jobs the list would show if it kept the ones that don't state experience, mode, type or salary.
  const lenient = useQuery({
    queryKey: ['jobs-count', 'lenient', view, countKey], enabled: hidesUnstated(sp), staleTime: 30_000,
    queryFn: () => listJobs({ ...toParams(sp, view, 1, 1), include_unstated: true }).then((r) => r.total),
  })
  const sources = useQuery({
    queryKey: ['job-sources', view], staleTime: 60_000,
    queryFn: () => listJobSources({ status: meta.params.status, include_duplicates: meta.params.include_duplicates }),
  })
  const profiles = useQuery({ queryKey: ['profiles'], queryFn: listProfiles, staleTime: 60_000 })
  const settings = useQuery({ queryKey: ['settings'], queryFn: getSettings, staleTime: 60_000 })
  const keepDays = Number(settings.data?.runtime['jobs.keep_days'] ?? settings.data?.runtime_defaults['jobs.keep_days'] ?? 30)
  // Last known tab counts, shown while new ones load so the tabs don't flicker on every filter change.
  const shownCounts = useRef<Array<number | undefined>>([])
  counts.forEach((c, i) => { if (c.data !== undefined) shownCounts.current[i] = c.data })
  const saved = ((settings.data?.runtime['jobs.saved_views'] as SavedView[] | undefined) ?? []).filter((v) => typeof v.query === 'string')
  const profileName = (id: number) => profiles.data?.find((p) => p.id === id)?.name

  const refresh = () => { for (const k of ['jobs', 'jobs-count', 'job-sources', 'tasks', 'today']) qc.invalidateQueries({ queryKey: [k] }) }
  const bulk = useMutation({
    mutationFn: (action: 'analyze' | 'prepare' | 'reject' | 'requeue') => bulkJobs([...selected], action),
    onSuccess: (_r, action) => {
      const n = selected.size
      toast.success(action === 'reject' ? `${n} marked not interested` : action === 'requeue' ? `${n} moved back to the queue`
        : action === 'analyze' ? `Analyzing ${n} jobs` : `Preparing ${n} applications`)
      setSelected(new Set()); refresh()
    },
    onError: (e) => (e instanceof ApiError && e.status === 409 ? toast.info('Busy', e.message) : toast.error('Action failed', errorMessage(e))),
  })
  const saveViews = useMutation({
    mutationFn: (views: SavedView[]) => putRuntime({ 'jobs.saved_views': views }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['settings'] }),
    onError: (e) => toast.error('Could not save the view', errorMessage(e)),
  })
  const currentQuery = () => {
    const q = new URLSearchParams({ view })
    for (const k of FILTER_KEYS) if (sp.get(k)) q.set(k, sp.get(k)!)
    return q.toString()
  }
  const openSaved = (v: SavedView) => { const next = new URLSearchParams(v.query); next.set('saved', v.id); setSp(next, { replace: true }); setSelected(new Set()) }
  const openView = (id: ViewId) => {
    const next = liveParams()
    next.set('view', id); next.delete('page'); next.delete('job'); next.delete('saved')
    setSp(next, { replace: true }); setSelected(new Set())
  }
  // Opening a job adds a history entry so Back closes the panel; filters replace the entry so they don't pile up.
  const openJob = (id: number) => { const next = liveParams(); next.set('job', String(id)); setSp(next, { state: { drawer: true } }) }
  const closeJob = () => { if ((loc.state as { drawer?: boolean } | null)?.drawer) nav(-1); else set({ job: null }) }
  const clearFilters = () => { setSp(new URLSearchParams({ view: liveParams().get('view') ?? 'new' }), { replace: true }); setSelected(new Set()) }

  // Active filters, in the order shown, each removable on its own.
  const srcLabel = (v: string) => (v.startsWith('kind:') ? labelOf(KINDS, v) : sources.data?.find((s) => s.source === v)?.label ?? v)
  const active: Array<{ key: string; label: string }> = [
    sp.get('q') && { key: 'q', label: `“${sp.get('q')}”` },
    sp.get('where') && { key: 'where', label: `In ${sp.get('where')}` },
    sp.get('profile') && { key: 'profile', label: profileName(Number(sp.get('profile'))) ?? 'Profile' },
    sp.get('fit') && { key: 'fit', label: labelOf(FIT, sp.get('fit')!) },
    sp.get('posted') && { key: 'posted', label: labelOf(POSTED, sp.get('posted')!) },
    sp.get('found') && { key: 'found', label: labelOf(FOUND, `found:${sp.get('found')}`) },
    sp.get('exp') && { key: 'exp', label: labelOf(EXP, sp.get('exp')!) },
    sp.get('mode') && { key: 'mode', label: labelOf(MODE, sp.get('mode')!) },
    sp.get('type') && { key: 'type', label: labelOf(TYPE, sp.get('type')!) },
    sp.get('salary') && { key: 'salary', label: labelOf(SALARY, sp.get('salary')!) },
    sp.get('src') && { key: 'src', label: srcLabel(sp.get('src')!) },
    sp.get('autofill') && { key: 'autofill', label: 'Can auto-fill' },
  ].filter(Boolean) as Array<{ key: string; label: string }>
  const moreCount = active.filter((a) => !['q', 'where', 'profile'].includes(a.key)).length

  const items = jobs.data?.items ?? []
  const selectable = meta.bulk !== 'none'
  const allSelected = items.length > 0 && items.every((j) => selected.has(j.id))
  const extra = lenient.data !== undefined && jobs.data ? Math.max(0, lenient.data - jobs.data.total) : 0
  const changePage = (p: number) => { set({ page: String(p) }); document.querySelector('main')?.scrollTo({ top: 0 }) }

  return (
    <div className="mx-auto flex max-w-[1120px] flex-col gap-4">
      <TaskBanner />
      <header>
        <h2 className="page-title">Jobs</h2>
        <p className="mt-1.5 text-sm text-ink-2">Everything collected for your profiles in the last {keepDays} days. Apply directly, or let the schedule analyze them. Jobs you applied to always stay.</p>
      </header>

      <div role="tablist" aria-label="Views" className="scroll-thin -mx-3 flex items-center gap-2 overflow-x-auto px-3 pb-1 md:mx-0 md:flex-wrap md:overflow-visible md:px-0 md:pb-0">
        {VIEWS.map((v, i) => {
          const on = view === v.id && !sp.get('saved')
          const c = counts[i]?.data ?? shownCounts.current[i]
          return (
            <button key={v.id} type="button" role="tab" aria-selected={on} onClick={() => openView(v.id)}
              className={clsx('inline-flex h-9 shrink-0 items-center gap-2 rounded-full border px-3.5 text-[13px] font-semibold transition-colors',
                on ? 'border-[var(--ink)] bg-ink text-[var(--bg)]' : 'border-[var(--baseline)] bg-surface text-ink hover:bg-surface-2')}>
              {v.label}{c !== undefined && <span className={clsx('num text-xs font-medium', on ? 'opacity-75' : 'text-ink-2')}>{c.toLocaleString()}</span>}
            </button>
          )
        })}
        {saved.map((v) => {
          const on = sp.get('saved') === v.id
          return (
            <span key={v.id} className={clsx('inline-flex h-9 shrink-0 items-center rounded-full border text-[13px] font-semibold',
              on ? 'border-[var(--accent)] bg-accent text-on-accent' : 'border-[var(--accent)] bg-surface text-accent-ink')}>
              <button type="button" className="inline-flex h-full items-center gap-1.5 pl-3.5 pr-2" onClick={() => openSaved(v)}><Bookmark size={13} />{v.name}</button>
              <button type="button" aria-label={`Delete view ${v.name}`} className="h-full pr-2.5 opacity-70 hover:opacity-100" onClick={() => saveViews.mutate(saved.filter((x) => x.id !== v.id))}><X size={13} /></button>
            </span>
          )
        })}
        {active.length > 0 && !sp.get('saved') && (
          <button type="button" onClick={() => setSaveOpen(true)}
            className="h-9 shrink-0 rounded-full border border-dashed border-[var(--baseline)] px-3.5 text-[13px] font-medium text-ink-2 hover:text-ink">+ Save these filters</button>
        )}
      </div>

      <section aria-label="Filters" className="card flex flex-col gap-2.5 p-3.5">
        <div className="flex flex-wrap gap-2">
          <span className="relative min-w-[200px] flex-[3_1_260px]">
            <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
            <input type="search" aria-label="Search jobs" className="input !pl-9" placeholder="Search title, company or location" value={qDraft} onChange={(e) => setQDraft(e.target.value)} />
          </span>
          <span className="relative min-w-[150px] flex-[1_1_170px]">
            <MapPin size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
            <input aria-label="City or country" className="input !pl-9" placeholder="City or country" value={whereDraft} onChange={(e) => setWhereDraft(e.target.value)} style={sp.get('where') ? ON : undefined} />
          </span>
          <Select label="Profile" className="flex-[1_1_170px]" value={sp.get('profile') ?? ''} onChange={(v) => set({ profile: v })}
            options={[['', 'All profiles'], ...(profiles.data ?? []).map((p): Opt => [String(p.id), `${p.name}${p.enabled ? '' : ' (off)'}`])]} />
          <Select label="Sort" className="flex-[1_1_150px]" value={sp.get('sort') ?? 'fit'} onChange={(v) => set({ sort: v === 'fit' ? null : v })} options={SORT} neutral />
          <Button className="md:hidden" icon={SlidersHorizontal} onClick={() => setMoreOpen(!moreOpen)} aria-expanded={moreOpen}>
            Filters{moreCount ? ` · ${moreCount}` : ''}
          </Button>
        </div>
        <div className={clsx('grid-cols-2 gap-2 sm:grid-cols-3 md:grid md:grid-cols-4 lg:grid-cols-7', moreOpen ? 'grid' : 'hidden')}>
          <Select label="Fit score" value={sp.get('fit') ?? ''} onChange={(v) => set({ fit: v })} options={FIT} />
          <select aria-label="Date" title="Date" className="input min-w-0 truncate"
            value={sp.get('found') ? `found:${sp.get('found')}` : sp.get('posted') ?? ''} style={sp.get('found') || sp.get('posted') ? ON : undefined}
            onChange={(e) => { const v = e.target.value; set(v.startsWith('found:') ? { found: v.slice(6), posted: null } : { posted: v, found: null }) }}>
            {POSTED.slice(0, 1).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            <optgroup label="Posted by the employer">{POSTED.slice(1).map(([v, l]) => <option key={v} value={v}>{l}</option>)}</optgroup>
            <optgroup label="Found by JobPilot">{FOUND.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</optgroup>
          </select>
          <Select label="Experience required" value={sp.get('exp') ?? ''} onChange={(v) => set({ exp: v })} options={EXP} />
          <Select label="Work mode" value={sp.get('mode') ?? ''} onChange={(v) => set({ mode: v })} options={MODE} />
          <Select label="Job type" value={sp.get('type') ?? ''} onChange={(v) => set({ type: v })} options={TYPE} />
          <Select label="Salary" value={sp.get('salary') ?? ''} onChange={(v) => set({ salary: v })} options={SALARY} />
          <select aria-label="Source" title="Source" className="input min-w-0 truncate" value={sp.get('src') ?? ''} onChange={(e) => set({ src: e.target.value })} style={sp.get('src') ? ON : undefined}>
            <option value="">All sources</option>
            <optgroup label="Type">{KINDS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</optgroup>
            {!!sources.data?.length && (
              <optgroup label="Source">{sources.data.map((s) => <option key={s.source} value={s.source}>{s.label} ({s.count.toLocaleString()})</option>)}</optgroup>
            )}
          </select>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Toggle on={!!sp.get('autofill')} onClick={() => set({ autofill: sp.get('autofill') ? null : '1' })}>Can auto-fill</Toggle>
          {usesStated(sp) && (
            <Toggle on={!!sp.get('unstated')} onClick={() => set({ unstated: sp.get('unstated') ? null : '1' })}
              title="Many postings don't state experience, work mode, job type or salary. Include them too?">
              Include jobs that don't say{!sp.get('unstated') && extra ? ` (+${extra.toLocaleString()})` : ''}
            </Toggle>
          )}
          <span className={clsx('flex flex-wrap gap-1.5', moreOpen && 'hidden', 'md:hidden')}>
            {active.filter((a) => !['q', 'where', 'profile'].includes(a.key)).map((a) => (
              <button key={a.key} type="button" onClick={() => set({ [a.key]: null })} aria-label={`Remove filter ${a.label}`}
                className="inline-flex h-[30px] items-center gap-1 rounded-full border border-[var(--accent)] px-2.5 text-xs font-medium text-accent-ink" style={ON}>
                {a.label}<X size={12} />
              </button>
            ))}
          </span>
          {active.length > 0 && <Button size="sm" variant="ghost" onClick={clearFilters}>Clear all</Button>}
          <span className="num ml-auto text-[13px] text-ink-2" aria-live="polite">
            {jobs.isFetching && !jobs.isLoading ? <Spinner size={13} className="mr-1.5 inline" /> : null}
            {jobs.data ? `${jobs.data.total.toLocaleString()} job${jobs.data.total === 1 ? '' : 's'}` : ''}
          </span>
        </div>
      </section>

      {selected.size > 0 && (
        <div role="region" aria-label="Selected jobs" className="sticky top-0 z-10 flex flex-wrap items-center gap-2.5 rounded-xl px-3.5 py-2.5 text-white shadow-[var(--shadow)]" style={{ background: '#1a1b1e' }}>
          <span className="text-sm font-semibold">{selected.size} selected</span>
          {meta.bulk === 'requeue' ? (
            <button type="button" className={BULK_PRIMARY} onClick={() => bulk.mutate('requeue')} disabled={bulk.isPending}>
              <RotateCcw size={14} />Move back to the queue</button>
          ) : (
            <>
              <button type="button" className={BULK_PRIMARY} onClick={() => bulk.mutate('analyze')} disabled={bulk.isPending}>
                <Sparkles size={14} />Analyze now · {selected.size} AI call{selected.size === 1 ? '' : 's'}</button>
              <button type="button" className={BULK} onClick={() => bulk.mutate('prepare')} disabled={bulk.isPending}><Wand2 size={14} />Prepare applications</button>
              <button type="button" className={BULK} onClick={() => bulk.mutate('reject')} disabled={bulk.isPending}><Ban size={14} />Not interested</button>
            </>
          )}
          <button type="button" className="ml-auto h-9 px-3 text-[13px] text-[#d7d9dc]" onClick={() => setSelected(new Set())}>Clear</button>
        </div>
      )}

      <section aria-label="Jobs" className="card overflow-hidden">
        {jobs.isLoading ? <div className="flex justify-center py-16"><Spinner size={22} /></div>
          : jobs.isError ? <EmptyState title="Could not load jobs" hint={errorMessage(jobs.error)} />
            : !items.length ? (
              active.length
                ? <EmptyState icon={Briefcase} title="No jobs match these filters" hint={meta.empty} action={<Button onClick={clearFilters}>Clear filters</Button>} />
                : <EmptyState icon={Briefcase} title="No jobs here" hint={meta.empty} />
            ) : (
              <>
                {selectable && (
                  <div className="flex items-center gap-3 border-b border-line px-4 py-2 text-xs text-ink-2">
                    <label className="flex items-center gap-2">
                      <input type="checkbox" className="h-4 w-4 accent-[var(--accent)]" checked={allSelected}
                        onChange={() => setSelected(allSelected ? new Set() : new Set(items.map((j) => j.id)))} />
                      Select all on this page
                    </label>
                  </div>
                )}
                {items.map((j) => (
                  <JobRow key={j.id} j={j} selectable={selectable} selected={selected.has(j.id)} active={jobId === j.id} profileName={profileName}
                    onSelect={() => { const n = new Set(selected); if (n.has(j.id)) n.delete(j.id); else n.add(j.id); setSelected(n) }}
                    onOpen={() => openJob(j.id)} onApply={() => setApplying(j)} />
                ))}
              </>
            )}
        {jobs.data && jobs.data.total > PAGE && (
          <div className="border-t border-line px-4 py-2"><Pagination page={page} pageSize={PAGE} total={jobs.data.total} onChange={changePage} /></div>
        )}
      </section>

      <JobDrawer jobId={jobId} onClose={closeJob} />
      <ApplyDialog job={applying} onClose={() => { setApplying(null); refresh() }} />
      <SaveViewDialog open={saveOpen} onClose={() => setSaveOpen(false)}
        onSave={(name) => {
          const id = `v${Date.now().toString(36)}`
          saveViews.mutate([...saved, { id, name, query: currentQuery() }], { onSuccess: () => set({ saved: id }) })
          setSaveOpen(false); toast.success('View saved', name)
        }} />
    </div>
  )
}

const ON = { borderColor: 'var(--accent)', background: 'color-mix(in oklab, var(--accent) 8%, var(--surface))' }
const BULK = 'inline-flex h-9 items-center gap-1.5 rounded-lg border border-[#6b6f76] px-3 text-[13px] font-semibold'
const BULK_PRIMARY = 'inline-flex h-9 items-center gap-1.5 rounded-lg bg-white px-3 text-[13px] font-semibold text-[#1a1b1e]'

/** A compact select whose first option names the filter; it turns teal while a value is chosen. */
function Select({ label, value, onChange, options, className, neutral }: {
  label: string; value: string; onChange: (v: string) => void; options: Opt[]; className?: string; neutral?: boolean
}) {
  return (
    <select aria-label={label} title={label} className={clsx('input min-w-0 truncate', className)} value={value}
      onChange={(e) => onChange(e.target.value)} style={value && !neutral ? ON : undefined}>
      {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
    </select>
  )
}

function Toggle({ on, onClick, children, title }: { on: boolean; onClick: () => void; children: React.ReactNode; title?: string }) {
  return (
    <button type="button" aria-pressed={on} onClick={onClick} title={title}
      className={clsx('h-[34px] rounded-full border px-3 text-[13px] font-medium transition-colors',
        on ? 'border-[var(--accent)] text-accent-ink' : 'border-[var(--baseline)] bg-surface text-ink-2 hover:text-ink')}
      style={on ? { background: 'color-mix(in oklab, var(--accent) 12%, transparent)' } : undefined}>{children}</button>
  )
}

function JobRow({ j, selectable, selected, active, profileName, onSelect, onOpen, onApply }: {
  j: Job; selectable: boolean; selected: boolean; active: boolean; profileName: (id: number) => string | undefined
  onSelect: () => void; onOpen: () => void; onApply: () => void
}) {
  const method = j.apply_method === 'autofill' ? 'Auto-fill form' : j.apply_method === 'manual' ? 'Apply by hand' : 'Apply on site'
  const inProgress = !!j.application_id && j.application_status !== 'withdrawn'
  const why = j.status === 'filtered_out' ? (j.duplicate_of ? `Same job as #${j.duplicate_of} from another source` : j.prefilter_reasons?.[0]) : null
  return (
    <div className={clsx('flex flex-wrap items-center gap-3.5 border-b border-line px-4 py-3.5 last:border-b-0', active && 'bg-surface-2')}>
      {selectable && <input type="checkbox" aria-label={`Select ${j.title}`} className="h-[18px] w-[18px] accent-[var(--accent)]" checked={selected} onChange={onSelect} />}
      {j.fit_score === null
        ? <span className="flex h-11 min-w-11 items-center justify-center rounded-[11px] bg-surface-2 px-1.5 text-center text-[11px] font-bold leading-tight text-ink-2">
          {j.status === 'queued' || j.status === 'new' ? 'New' : '—'}</span>
        : <FitBadge score={j.fit_score} size="lg" />}
      <button type="button" onClick={onOpen} className="min-w-0 flex-[1_1_200px] text-left">
        <span className="block text-[15px] font-bold leading-snug">{j.title}</span>
        <span className="mt-0.5 block text-[13px] text-ink-2">{j.company_name}{j.location ? ` · ${j.location}` : ''} · {j.posted_at ? `posted ${fmtRelative(j.posted_at)}` : `found ${fmtRelative(j.discovered_at)}`}</span>
        {why && <span className="mt-1 block truncate text-[13px] text-serious-ink">Filtered out: {why}</span>}
        {!why && j.fit?.one_liner && <span className="mt-1 block truncate text-[13px] text-ink-2">{j.fit.one_liner}</span>}
        <span className="mt-2 flex flex-wrap gap-1.5">
          <span className="rounded-md px-2 py-0.5 text-xs font-medium" style={j.apply_method === 'autofill'
            ? { background: 'color-mix(in oklab, var(--accent) 14%, transparent)', color: 'var(--accent-ink)' } : { background: 'var(--surface-2)', color: 'var(--ink-2)' }}>{method}</span>
          {facts(j).map((t) => <span key={t} className="rounded-md bg-surface-2 px-2 py-0.5 text-xs text-ink-2">{t}</span>)}
          <SourceChip source={j.source} />
          {(j.profile_ids ?? []).slice(0, 2).map((pid) => profileName(pid) && <span key={pid} className="rounded-md bg-surface-2 px-2 py-0.5 text-xs text-ink-2">{profileName(pid)}</span>)}
          {j.application_status === 'submitted' ? <OutcomeChip outcome={j.application_outcome} /> : j.application_status && <AppStatusChip status={j.application_status} />}
        </span>
      </button>
      <div className="flex items-center gap-2">
        {inProgress
          ? <Link to={`/applications/${j.application_id}`} className="inline-flex h-10 items-center rounded-[9px] border border-[var(--baseline)] bg-surface px-3.5 text-[13px] font-semibold text-ink no-underline hover:bg-surface-2">Open application</Link>
          : j.status === 'rejected' || j.status === 'applied' ? null
            : <Button variant="primary" onClick={onApply}>Apply</Button>}
      </div>
    </div>
  )
}

function SaveViewDialog({ open, onClose, onSave }: { open: boolean; onClose: () => void; onSave: (name: string) => void }) {
  const [name, setName] = useState('')
  useEffect(() => { if (open) setName('') }, [open])
  return (
    <Dialog open={open} onClose={onClose} title="Save these filters as a view"
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="primary" icon={Bookmark} disabled={!name.trim()} onClick={() => onSave(name.trim())}>Save view</Button></>}>
      <label className="flex flex-col gap-1.5 text-[13px] font-semibold">Name
        <input className="input" autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Fresh remote ATS jobs"
          onKeyDown={(e) => { if (e.key === 'Enter' && name.trim()) onSave(name.trim()) }} />
      </label>
    </Dialog>
  )
}

const TYPE_LABEL: Record<string, string> = { full_time: 'Full-time', part_time: 'Part-time', contract: 'Contract', internship: 'Internship', freelance: 'Freelance' }
const MODE_LABEL: Record<string, string> = { remote: 'Remote', hybrid: 'Hybrid', onsite: 'On-site' }

function money(v: number, cur: string): string {
  if (cur === 'INR') return `${(v / 100_000).toFixed(v % 100_000 ? 1 : 0)}`
  return v >= 1000 ? `${Math.round(v / 1000)}k` : String(Math.round(v))
}

/** Short facts read from the posting: "3–5 yrs", "Hybrid", "Full-time", "₹6–12 LPA". */
function facts(j: Job): string[] {
  const out: string[] = []
  if (j.exp_min !== null) out.push(j.exp_max !== null ? (j.exp_min === 0 && j.exp_max <= 1 ? 'Fresher' : `${j.exp_min}–${j.exp_max} yrs`) : `${j.exp_min}+ yrs`)
  if (j.work_mode) out.push(MODE_LABEL[j.work_mode] ?? j.work_mode)
  if (j.job_type) out.push(TYPE_LABEL[j.job_type] ?? j.job_type)
  if (j.salary_max !== null && j.salary_currency) {
    const sym = j.salary_currency === 'INR' ? '₹' : j.salary_currency === 'USD' ? '$' : j.salary_currency === 'EUR' ? '€' : j.salary_currency === 'GBP' ? '£' : ''
    const lo = j.salary_min ?? j.salary_max
    const range = lo !== j.salary_max ? `${money(lo, j.salary_currency)}–${money(j.salary_max, j.salary_currency)}` : money(j.salary_max, j.salary_currency)
    out.push(`${sym}${range}${j.salary_currency === 'INR' ? ' LPA' : '/yr'}`)
  }
  return out
}
