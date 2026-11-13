import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Compass, Play, RefreshCw, Sparkles, Briefcase } from 'lucide-react'
import { getSchedule, getStats, startCrawl, startCycle, startDiscover, startScore } from '../api'
import { ApiError } from '../api'
import { useToast } from '../lib/toast'
import { errorMessage } from '../lib/tasks'
import { compact, fmtDuration, fmtRelative, titleCase } from '../lib/format'
import { Button, Card, EmptyState, Spinner } from '../components/ui'
import { DailyBars, Funnel, StatTile } from '../components/charts'
import { FitBadge, RunStatusChip, SourceChip } from '../components/status'
import TaskBanner from '../components/TaskBanner'

export default function Insights() {
  const qc = useQueryClient()
  const toast = useToast()
  const stats = useQuery({ queryKey: ['stats'], queryFn: getStats, refetchInterval: 30_000 })
  const schedule = useQuery({ queryKey: ['schedule'], queryFn: getSchedule, staleTime: 60_000 })

  const useAction = (label: string, fn: () => Promise<unknown>) =>
    useMutation({
      mutationFn: fn,
      onSuccess: () => { toast.success(`${label} started`); qc.invalidateQueries({ queryKey: ['tasks'] }) },
      onError: (e) => (e instanceof ApiError && e.status === 409 ? toast.info('Already running', e.message) : toast.error(`${label} failed`, errorMessage(e))),
    })
  const cycle = useAction('Full cycle', () => startCycle())
  const crawl = useAction('Crawl', () => startCrawl())
  const score = useAction('Scoring', () => startScore())
  const discover = useAction('Discovery', () => startDiscover())

  if (stats.isLoading) return <div className="flex justify-center py-20"><Spinner size={24} /></div>
  if (stats.isError || !stats.data) return <EmptyState title="Could not load stats" hint={errorMessage(stats.error)} />
  const s = stats.data
  const b = s.budget
  // Scoring takes one Analyze run's worth: the per-run limit from Schedule, best match first.
  const perRun = schedule.data?.stages.analyze.limit ?? 30
  const toScore = Math.min(s.queued_for_scoring, perRun)

  return (
    <div className="mx-auto max-w-[1200px]">
      <TaskBanner />
      <h2 className="page-title mb-1.5">Insights</h2>
      <p className="mb-5 text-sm text-ink-2">The funnel, daily volume and recent runs.</p>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <span className="mr-1 text-xs font-medium text-ink-2">Single steps:</span>
        <Button icon={RefreshCw} loading={crawl.isPending} onClick={() => crawl.mutate()}>Crawl sources</Button>
        <Button icon={Sparkles} loading={score.isPending} onClick={() => score.mutate()} disabled={!toScore}
          title={`Scores up to ${perRun} queued jobs (the per-run limit on Schedule), best match first. 1 AI call each.`}>
          {toScore ? `Score next ${toScore}` : 'Score queued jobs'}
        </Button>
        <Button icon={Compass} loading={discover.isPending} onClick={() => discover.mutate()}>Discover companies</Button>
        <span className="ml-auto text-xs text-muted">AI: {b.provider_label ?? 'Codex'} · {b.model} · effort {b.effort}</span>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <StatTile label="Jobs tracked" value={compact(s.jobs.total)} sub={`+${s.jobs.new_7d} in the last 7 days`} />
        <StatTile label="Queued for scoring" value={compact(s.queued_for_scoring)} sub="Passed the prefilter, awaiting the AI" />
        <StatTile label="Needs your review" value={compact(s.applications.needs_review)} sub={<Link to="/applications?status=needs_review" className="underline-offset-2 hover:underline">Open the review queue</Link>} tone={s.applications.needs_review ? 'warn' : undefined} />
        <StatTile label="Applications submitted" value={compact(s.applications.submitted)} sub={`${s.funnel.shortlisted} shortlisted so far`} tone={s.applications.submitted ? 'good' : undefined} />
        <StatTile label="AI calls, 5h window" value={<span className="num">{b.window_5h.used}<span className="text-base text-muted"> / {b.window_5h.max}</span></span>} meter={b.window_5h} sub={`${b.day.used} of ${b.day.max} today`} />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <Card title="Pipeline funnel" subtitle="Where jobs are dropping out" className="lg:col-span-1">
          <Funnel stages={[
            { label: 'Discovered', value: s.funnel.discovered },
            { label: 'Passed prefilter', value: s.funnel.passed_prefilter },
            { label: 'Scored', value: s.funnel.scored },
            { label: 'Shortlisted', value: s.funnel.shortlisted },
            { label: 'Applied', value: s.funnel.applied },
          ]} />
          <div className="mt-5 border-t border-line pt-4">
            <div className="mb-2 text-xs font-semibold text-ink-2">After applying</div>
            <Funnel stages={[
              { label: 'Applied', value: s.funnel.applied },
              { label: 'Heard back', value: s.funnel.heard_back },
              { label: 'Interviews', value: s.funnel.interviews },
              { label: 'Offers', value: s.funnel.offers },
            ]} />
          </div>
        </Card>
        <Card title="Jobs discovered per day" subtitle="Last 14 days, duplicates included" className="lg:col-span-2">
          <DailyBars data={s.discovered_per_day} />
        </Card>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <Card title="Top shortlisted" subtitle="Highest fit, not yet applied" className="lg:col-span-2" padded={false}
          actions={<Link to="/jobs?view=strong" className="text-xs">Review queue →</Link>}>
          {s.top_shortlisted.length ? (
            <ul className="divide-y divide-line">
              {s.top_shortlisted.map((j) => (
                <li key={j.id}>
                  <Link to={`/jobs?job=${j.id}`} className="flex items-center gap-3 px-4 py-2.5 text-ink no-underline hover:bg-surface-2">
                    <FitBadge score={j.fit_score} />
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium">{j.title}</div>
                      <div className="truncate text-xs text-ink-2">{j.company_name}{j.location ? ` · ${j.location}` : ''}{j.fit?.one_liner ? ` — ${j.fit.one_liner}` : ''}</div>
                    </div>
                    <SourceChip source={j.source} />
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState icon={Briefcase} title="Nothing shortlisted yet"
              hint={s.jobs.total ? 'Jobs are tracked but none scored high enough. Upload your resume and run scoring.' : 'Run a crawl to get started. Scoring needs your resume in Profile.'}
              action={<Button variant="primary" icon={Play} onClick={() => cycle.mutate()} loading={cycle.isPending}>Run full cycle</Button>} />
          )}
        </Card>
        <Card title="Recent runs" padded={false} actions={<Link to="/activity" className="text-xs">All activity →</Link>}>
          {s.last_runs.length ? (
            <ul className="divide-y divide-line">
              {s.last_runs.slice(0, 8).map((r) => (
                <li key={r.id}>
                  <Link to={`/activity?run=${r.id}`} className="flex items-center gap-2 px-4 py-2 text-xs text-ink no-underline hover:bg-surface-2">
                    <RunStatusChip status={r.status} />
                    <span className="min-w-0 flex-1 truncate">{titleCase(r.kind)}{r.source ? ` · ${r.source}` : ''}</span>
                    <span className="num text-muted" title={fmtDuration(r.started_at, r.finished_at)}>{fmtRelative(r.started_at)}</span>
                  </Link>
                </li>
              ))}
            </ul>
          ) : <EmptyState title="No runs yet" hint="The first crawl will show up here." />}
          {Object.keys(s.llm_24h).length > 0 && (
            <div className="border-t border-line px-4 py-2 text-[11px] text-muted">
              AI calls today: {Object.entries(s.llm_24h).map(([k, v]) => `${k} ${v}`).join(' · ')}
            </div>
          )}
        </Card>
      </div>
    </div>
  )
}

