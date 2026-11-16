import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, BellRing, CalendarClock, Check, CircleAlert, FileText, Sparkles, TriangleAlert, X } from 'lucide-react'
import { ApiError, getToday, setJobStatus, submitApplication } from '../api'
import type { ApplicationWithJob, Outcome, Today as TodayData } from '../types'
import { useToast } from '../lib/toast'
import { errorMessage } from '../lib/tasks'
import { foundAgo, fmtRelative } from '../lib/format'
import { fmtClock, fmtDays, useRunControl } from '../lib/runControl'
import { Button, EmptyState, Spinner } from '../components/ui'
import RunDialog from '../components/RunDialog'
import { FitBadge } from '../components/status'
import TaskBanner from '../components/TaskBanner'
import ResumeRefreshBanner from '../components/ResumeRefreshBanner'
import { OutcomeChip, inDays, useOutcomeUpdate } from '../components/OutcomeTracker'
import { fmtDate } from '../lib/format'

function greeting(): string {
  const h = new Date().getHours()
  return h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening'
}

export default function Today() {
  const today = useQuery({ queryKey: ['today'], queryFn: getToday, refetchInterval: 30_000 })
  if (today.isLoading) return <div className="flex justify-center py-20"><Spinner size={24} /></div>
  if (today.isError || !today.data) return <EmptyState title="Could not load Today" hint={errorMessage(today.error)} />
  return <TodayView t={today.data} />
}

function TodayView({ t }: { t: TodayData }) {
  const rc = useRunControl()
  const [analyzing, setAnalyzing] = useState(false)
  const needs = t.approvals.filter((a) => a.status === 'needs_review').length
  const { collect: c, analyze: an, prepare: pr } = t.stages
  const dateText = new Date().toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long' })
  const setupLeft = !t.setup.has_resume || t.setup.answers_filled < t.setup.answers_needed
  // Collect is free unless some job sites are read by the AI; the number comes with the task poll's scheduler info.
  const collectAi = rc.scheduler?.collect_ai_per_run
  const collectCost = collectAi === undefined ? '' : collectAi > 0 ? ` · about ${collectAi} AI calls` : ' · free'

  return (
    <div className="mx-auto flex max-w-[1120px] flex-col gap-6">
      <TaskBanner />
      <header className="flex flex-wrap items-center gap-4">
        <div>
          <h2 className="page-title">{greeting()}</h2>
          <p className="mt-1.5 flex flex-wrap items-center gap-2.5 text-sm text-ink-2">
            {dateText}
            {needs > 0 && <span className="rounded-full px-2.5 py-0.5 text-[13px] font-bold" style={{ background: 'color-mix(in oklab, var(--warn) 20%, transparent)', color: 'var(--warn-ink)' }}>
              {needs} application{needs > 1 ? 's' : ''} need{needs > 1 ? '' : 's'} you</span>}
          </p>
        </div>
      </header>

      {setupLeft && (
        <Link to="/setup" className="card flex flex-wrap items-center gap-3 p-4 text-ink no-underline hover:border-[var(--accent)]">
          <CircleAlert size={20} className="text-warn-ink" />
          <div className="min-w-0 flex-1">
            <div className="text-sm font-bold">Finish setting up</div>
            <div className="text-[13px] text-ink-2">
              {!t.setup.has_resume ? 'Upload your resume so jobs can be scored against it. ' : ''}
              {t.setup.answers_filled < t.setup.answers_needed ? `${t.setup.answers_filled} of ${t.setup.answers_needed} key form answers filled.` : ''}
            </div>
          </div>
          <span className="inline-flex items-center gap-1 text-sm font-semibold text-accent-ink">Open setup <ArrowRight size={15} /></span>
        </Link>
      )}

      <ResumeRefreshBanner />

      <section aria-label="Pipeline stages" className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(230px, 1fr))' }}>
        <StageCard to="/jobs?found=today&sort=newest" step="1 · Collect" title={collectTitle(c.matched_today, c.new_today)}
          note={c.new_today > c.matched_today ? `${c.new_today.toLocaleString()} collected · ${(c.new_today - c.matched_today).toLocaleString()} didn't fit your profiles` : null}
          schedule={t.paused || !c.enabled ? 'Paused · Run now still works' : `${fmtDays(c.days)} at ${fmtClock(c.time)}${collectCost}`} />
        <StageCard to="/jobs?fit=unscored" step="2 · Analyze"
          title={`${an.waiting.toLocaleString()} waiting${!t.paused && an.next_run_at ? ` · next ${fmtRelative(an.next_run_at)}` : ''}`}
          note={`Best match first, up to ${an.limit ?? 30} per run`}
          schedule={t.paused || !an.enabled ? 'Paused' : `${fmtDays(an.days)} at ${fmtClock(an.time)}`} />
        <StageCard to="/applications?status=all" step="3 · Prepare" title={`${pr.drafted_7d} cover letter${pr.drafted_7d === 1 ? '' : 's'} this week`}
          note={pr.enabled ? `Only for fit ${pr.min_fit}+` : null}
          schedule={pr.enabled ? 'Right after Analyze' : 'Off'} />
        <StageCard to="/jobs?view=applied" step="4 · Apply" title={`${t.stages.apply.submitted_7d} submitted this week`}
          note={[(t.outcomes.interview ?? 0) ? `${t.outcomes.interview} interviewing` : '', (t.outcomes.offer ?? 0) ? `${t.outcomes.offer} offer${(t.outcomes.offer ?? 0) > 1 ? 's' : ''}` : ''].filter(Boolean).join(' · ') || null}
          schedule={t.stages.apply.mode === 'auto' ? 'Auto-submits approved ATS jobs' : t.stages.apply.mode === 'manual' ? 'You apply yourself' : 'Only when you approve'} />
      </section>

      <div className="flex flex-wrap items-start gap-6">
        <section aria-labelledby="needs-you" className="flex min-w-0 flex-col gap-3" style={{ flex: '999 1 520px' }}>
          <h3 id="needs-you" className="flex items-center gap-2 text-[17px] font-bold">
            <span className="h-2.5 w-2.5 rounded-full" style={{ background: 'var(--warn)' }} />Waiting for your approval
            <span className="text-xs font-normal text-muted">jobs found in the last {t.recent_days} days</span>
          </h3>
          {t.approvals.length ? t.approvals.map((a) => <ApprovalCard key={a.id} a={a} />) : (
            <div className="card">
              <EmptyState icon={Check} title="Nothing waiting for you"
                hint={t.stages.analyze.waiting ? `${t.stages.analyze.waiting} collected jobs are waiting to be analyzed.` : 'New matches show up here after Analyze runs.'} />
            </div>
          )}
          {t.older_approvals > 0 && (
            <Link to="/applications?status=needs_review" className="text-[13px] font-semibold">
              {t.older_approvals} older application{t.older_approvals === 1 ? '' : 's'} (jobs found more than {t.recent_days} days ago) in Applications →
            </Link>
          )}
          {t.follow_ups.length > 0 && (
            <>
              <h3 className="mt-3 flex items-center gap-2 text-[17px] font-bold"><BellRing size={17} className="text-accent-ink" />Time to follow up</h3>
              {t.follow_ups.map((a) => <FollowUpCard key={a.id} a={a} />)}
            </>
          )}
          {t.manual_count > 0 && (
            <Link to="/applications?status=manual" className="text-sm font-semibold">{t.manual_count} prepared for you to apply by hand →</Link>
          )}
        </section>

        <aside aria-label="Matches" className="flex min-w-0 flex-col gap-3" style={{ flex: '1 1 300px' }}>
          {t.sources_attention.length > 0 && (
            <Link to="/settings?tab=sources" className="card flex flex-col gap-1.5 p-4 text-ink no-underline hover:border-[var(--warn)]">
              <span className="flex items-center gap-2 text-sm font-bold"><TriangleAlert size={16} className="text-warn-ink" />{t.sources_attention.length} source{t.sources_attention.length > 1 ? 's need' : ' needs'} attention</span>
              {t.sources_attention.slice(0, 3).map((s) => <span key={s.source} className="truncate text-[13px] text-ink-2"><b className="font-semibold text-ink">{s.source.replace(/^site_/, '')}</b>: {s.note}</span>)}
            </Link>
          )}
          <h3 className="text-[17px] font-bold">Strong matches</h3>
          <div className="card overflow-hidden">
            {t.strong_matches.length ? t.strong_matches.map((j) => (
              <Link key={j.id} to={`/jobs?job=${j.id}`} className="flex items-center gap-3 border-b border-line px-4 py-3 text-ink no-underline hover:bg-surface-2">
                <FitBadge score={j.fit_score} />
                <span className="min-w-0">
                  <span className="block truncate text-sm font-semibold">{j.title}</span>
                  <span className="block truncate text-xs text-ink-2">{j.company_name}{j.location ? ` · ${j.location}` : ''}</span>
                  <span className="block text-[11px] text-muted">{foundAgo(j.discovered_at)}</span>
                </span>
              </Link>
            )) : <div className="px-4 py-5 text-[13px] text-ink-2">No shortlisted jobs yet. Jobs scoring {t.min_fit}+ appear here.</div>}
            <Link to="/jobs" className="block px-4 py-3 text-[13px] font-semibold">See all collected jobs →</Link>
          </div>
          <div className="card flex flex-col gap-2.5 p-4">
            <div className="text-sm font-bold">{t.stages.analyze.waiting} job{t.stages.analyze.waiting === 1 ? '' : 's'} waiting to be analyzed</div>
            <div className="text-[13px] leading-relaxed text-ink-2">
              {t.stages.analyze.next_run_at && !t.paused ? <>Scheduled {fmtRelative(t.stages.analyze.next_run_at)}. </> : null}
              Analyze now to get results today; it uses up to {Math.min(t.stages.analyze.waiting, t.stages.analyze.limit ?? 30)} AI calls.
            </div>
            <Button className="self-start" variant="outline" icon={Sparkles} onClick={() => setAnalyzing(true)} loading={rc.analyze.isPending}
              disabled={!t.stages.analyze.waiting || rc.running}>Analyze now</Button>
            <RunDialog stage={analyzing ? 'analyze' : null} onClose={() => setAnalyzing(false)} />
          </div>
          <div className="card grid grid-cols-2 gap-3 p-4 text-[13px]">
            <div className="col-span-2 flex items-baseline justify-between gap-2">
              <h4 className="text-sm font-bold">Last 7 days</h4>
              <Link to="/insights" className="text-[13px] font-semibold">See insights →</Link>
            </div>
            <Stat label="Collected" value={t.week.collected} />
            <Stat label="Analyzed" value={t.week.analyzed} />
            <Stat label="Submitted" value={t.week.submitted} />
            <Stat label="AI calls" value={t.week.ai_calls} />
          </div>
        </aside>
      </div>
    </div>
  )
}

/** The headline opens the list behind the number; the bottom line opens the stage's settings on Schedule. */
function StageCard({ to, step, title, note, schedule }: { to: string; step: string; title: string; note: string | null; schedule: string }) {
  return (
    <div className="card relative flex flex-col gap-1.5 px-4 py-4 transition-colors hover:border-[var(--accent)]">
      <span className="text-xs font-bold uppercase tracking-wider text-ink-2">{step}</span>
      <Link to={to} className="text-[17px] font-bold text-accent-ink no-underline after:absolute after:inset-0 after:rounded-[inherit] after:content-['']">{title}</Link>
      {note && <span className="text-[13px] text-ink-2">{note}</span>}
      <Link to="/schedule" title="Change this on Schedule"
        className="relative z-10 mt-auto inline-flex w-fit items-center gap-1.5 pt-1 text-[13px] !text-ink-2 no-underline hover:!text-ink hover:underline">
        <CalendarClock size={13} />{schedule}
      </Link>
    </div>
  )
}

function collectTitle(matched: number, collected: number): string {
  if (matched) return `${matched.toLocaleString()} new match${matched === 1 ? '' : 'es'} today`
  return collected ? 'No new matches today' : 'No new jobs today'
}

function Stat({ label, value }: { label: string; value: number }) {
  return <div><div className="text-ink-2">{label}</div><div className="num text-xl font-extrabold">{value}</div></div>
}

function ApprovalCard({ a }: { a: ApplicationWithJob }) {
  const qc = useQueryClient()
  const toast = useToast()
  const nav = useNavigate()
  const missing = a.unanswered?.length ?? 0
  const done = () => { qc.invalidateQueries({ queryKey: ['today'] }); qc.invalidateQueries({ queryKey: ['tasks'] }) }
  const submit = useMutation({
    mutationFn: () => submitApplication(a.id),
    onSuccess: () => { toast.success('Submitting', `${a.job.company_name}: the form is filled and sent in the background.`); done() },
    onError: (e) => (e instanceof ApiError && e.status === 409 ? toast.info('Busy', e.message) : toast.error('Could not submit', errorMessage(e))),
  })
  const skip = useMutation({
    mutationFn: () => setJobStatus(a.job_id, 'rejected'),
    onSuccess: () => { toast.info('Skipped', 'Moved out of your queue.'); done() },
    onError: (e) => toast.error('Could not skip', errorMessage(e)),
  })
  const why = a.job.fit?.one_liner
  return (
    <article className="card flex flex-col gap-3 p-[18px]">
      <div className="flex items-start gap-3.5">
        <FitBadge score={a.job.fit_score} size="lg" />
        <div className="min-w-0 flex-1">
          <div className="text-base font-bold">{a.job.title}</div>
          <div className="mt-0.5 text-[13px] text-ink-2">{a.job.company_name}{a.job.location ? ` · ${a.job.location}` : ''}
            <span className="whitespace-nowrap text-muted" title={`JobPilot found this job ${fmtRelative(a.job.discovered_at)}. The posting date is in the job's details.`}> · {foundAgo(a.job.discovered_at)}</span></div>
          {why && <p className="mt-2 text-sm leading-relaxed text-ink-2">{why}</p>}
        </div>
      </div>
      <div className="flex flex-wrap gap-2 text-xs">
        {a.cover_letter
          ? <span className="rounded-md px-2 py-1 font-medium" style={{ background: 'color-mix(in oklab, var(--good) 14%, transparent)', color: 'var(--good-ink)' }}>Cover letter ready</span>
          : <span className="rounded-md bg-surface-2 px-2 py-1 text-ink-2">No cover letter</span>}
        {missing
          ? <span className="rounded-md px-2 py-1 font-medium" style={{ background: 'color-mix(in oklab, var(--warn) 20%, transparent)', color: 'var(--warn-ink)' }}>{missing} question{missing > 1 ? 's' : ''} need your answer</span>
          : a.form_plan ? <span className="rounded-md px-2 py-1 font-medium" style={{ background: 'color-mix(in oklab, var(--good) 14%, transparent)', color: 'var(--good-ink)' }}>All form answers found</span>
            : <span className="rounded-md bg-surface-2 px-2 py-1 text-ink-2">Form not checked yet</span>}
        {a.status === 'approved' && <span className="rounded-md px-2 py-1 font-medium" style={{ background: 'color-mix(in oklab, var(--accent) 14%, transparent)', color: 'var(--accent-ink)' }}>Approved · waiting to submit</span>}
      </div>
      <div className="flex flex-wrap gap-2">
        <Button variant="primary" onClick={() => submit.mutate()} loading={submit.isPending} disabled={missing > 0 || a.job.apply_method === 'manual'}
          title={missing ? 'Answer the missing questions first' : undefined}>Approve &amp; submit</Button>
        <Button variant="outline" icon={FileText} onClick={() => nav(`/applications/${a.id}`)}>{missing ? 'Answer & review' : 'Review letter & answers'}</Button>
        <Button variant="ghost" icon={X} onClick={() => skip.mutate()} loading={skip.isPending}>Skip</Button>
      </div>
    </article>
  )
}

const QUICK: Array<[Outcome, string]> = [['responded', 'Heard back'], ['interview', 'Interviewing'], ['rejected', 'Rejected'], ['no_response', 'No response']]

function FollowUpCard({ a }: { a: ApplicationWithJob }) {
  const update = useOutcomeUpdate(a.id)
  const nav = useNavigate()
  return (
    <article className="card flex flex-col gap-3 p-4">
      <div className="flex flex-wrap items-start gap-2">
        <div className="min-w-0 flex-1">
          <button type="button" onClick={() => nav(`/applications/${a.id}`)} className="text-left text-[15px] font-bold hover:underline">{a.job.title}</button>
          <div className="text-[13px] text-ink-2">{a.job.company_name} · applied {fmtDate(a.submitted_at)}</div>
        </div>
        <OutcomeChip outcome={a.outcome} />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[13px] text-ink-2">Any news?</span>
        {QUICK.map(([id, label]) => <Button key={id} size="sm" variant="outline" onClick={() => update.mutate({ outcome: id })} disabled={update.isPending}>{label}</Button>)}
        <Button size="sm" variant="ghost" onClick={() => update.mutate({ follow_up_at: inDays(7) })} disabled={update.isPending}>Remind me in a week</Button>
      </div>
    </article>
  )
}
