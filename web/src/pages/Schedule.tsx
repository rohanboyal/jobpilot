import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Minus, Play, Plus, Sparkles, Square } from 'lucide-react'
import { clsx } from 'clsx'
import { getSchedule } from '../api'
import type { ApplyMode, SchedulerInfo, ScheduleUpdate } from '../types'
import { errorMessage } from '../lib/tasks'
import { fmtDateTime, fmtRelative } from '../lib/format'
import { DAY_SHORT, useRunControl } from '../lib/runControl'
import { Button, EmptyState, Spinner, Switch } from '../components/ui'
import TaskBanner from '../components/TaskBanner'
import RunDialog, { type RunStage } from '../components/RunDialog'

const WEEKLY_GUARD = 300

export default function Schedule() {
  const q = useQuery({ queryKey: ['schedule'], queryFn: getSchedule, refetchInterval: 60_000 })
  if (q.isLoading) return <div className="flex justify-center py-20"><Spinner size={24} /></div>
  if (q.isError || !q.data) return <EmptyState title="Could not load the schedule" hint={errorMessage(q.error)} />
  return <ScheduleView info={q.data} />
}

function ScheduleView({ info }: { info: SchedulerInfo }) {
  const rc = useRunControl()
  const [run, setRun] = useState<RunStage | null>(null)
  const [s, setS] = useState(info)
  useEffect(() => setS(info), [info])
  const save = (body: ScheduleUpdate) => rc.schedule.mutate(body)
  const busy = rc.schedule.isPending

  const est = useMemo(() => {
    const off = s.paused
    const aRuns = !off && s.stages.analyze.enabled ? s.stages.analyze.days.length : 0
    const analyze = aRuns * (s.stages.analyze.limit ?? 30)
    const prepare = s.prepare.enabled ? aRuns * s.prepare.limit : 0
    const collect = !off && s.stages.collect.enabled ? s.stages.collect.days.length * s.collect_ai_per_run : 0
    return { analyze, prepare, collect, total: analyze + prepare + collect }
  }, [s])

  const toggleDay = (stage: 'collect' | 'analyze', d: number) => {
    const cur = s.stages[stage].days
    const days = cur.includes(d) ? cur.filter((x) => x !== d) : [...cur, d].sort()
    setS({ ...s, stages: { ...s.stages, [stage]: { ...s.stages[stage], days } } })
    save({ [stage]: { days } })
  }
  const setLimit = (stage: 'analyze' | 'prepare', v: number) => {
    if (stage === 'analyze') setS({ ...s, stages: { ...s.stages, analyze: { ...s.stages.analyze, limit: v } } })
    else setS({ ...s, prepare: { ...s.prepare, limit: v } })
    save(stage === 'analyze' ? { analyze: { limit: v } } : { prepare: { limit: v } })
  }

  return (
    <div className="mx-auto flex max-w-[1120px] flex-col gap-5">
      <TaskBanner />
      <header className="flex flex-wrap items-end gap-4">
        <div>
          <h2 className="page-title">Schedule</h2>
          <p className="mt-1.5 max-w-[640px] text-sm leading-relaxed text-ink-2">
            Each stage runs on its own days. {s.collect_ai_per_run > 0 ? 'Collecting is mostly free; ' : 'Collecting is free; '}analyzing and drafting use AI calls from your ChatGPT plan. Times are in {s.timezone}.</p>
        </div>
        <label className="ml-auto inline-flex cursor-pointer items-center gap-2 text-sm font-semibold">
          <input type="checkbox" className="h-[18px] w-[18px] accent-[var(--accent)]" checked={s.paused} disabled={busy || !s.available}
            onChange={(e) => { setS({ ...s, paused: e.target.checked }); save({ paused: e.target.checked }) }} />
          Pause all scheduled runs
        </label>
      </header>
      {!s.available && <div className="card p-3 text-[13px] text-warn-ink">The scheduler is not running in this server (JOBAGENT_SCHEDULER_ENABLED=false), so nothing runs on its own. Run now still works.</div>}

      <div className="flex flex-wrap items-start gap-5">
        <div className="flex min-w-0 flex-col gap-3.5" style={{ flex: '999 1 560px' }}>
          <StageCard name="1 · Collect jobs" desc="Crawl your enabled sources, remove duplicates, keep jobs that match a profile."
            cost={s.collect_ai_per_run > 0 ? `About ${s.collect_ai_per_run} AI calls per run` : 'Free · no AI'} free={s.collect_ai_per_run === 0}
            on={s.stages.collect.enabled} paused={s.paused} next={s.stages.collect.next_run_at}
            onToggle={(v) => { setS({ ...s, stages: { ...s.stages, collect: { ...s.stages.collect, enabled: v } } }); save({ collect: { enabled: v } }) }}>
            <DaysRow stage="Collect" days={s.stages.collect.days} time={s.stages.collect.time} disabled={busy}
              onDay={(d) => toggleDay('collect', d)} onTime={(t) => save({ collect: { time: t } })} />
            {s.collect_ai_per_run > 0 && <p className="text-[13px] text-ink-2">The AI reads the results pages of job sites that have no CSS selectors set (Settings › Job sites). Everything else is free.</p>}
          </StageCard>

          <StageCard name="2 · Analyze matches" desc="Score the best new matches against your resume and flag fake postings. Best match first, then newest." cost="1 AI call per job"
            on={s.stages.analyze.enabled} paused={s.paused} next={s.stages.analyze.next_run_at}
            onToggle={(v) => { setS({ ...s, stages: { ...s.stages, analyze: { ...s.stages.analyze, enabled: v } } }); save({ analyze: { enabled: v } }) }}>
            <DaysRow stage="Analyze" days={s.stages.analyze.days} time={s.stages.analyze.time} disabled={busy}
              onDay={(d) => toggleDay('analyze', d)} onTime={(t) => save({ analyze: { time: t } })} />
            <Stepper label="Jobs per run" value={s.stages.analyze.limit ?? 30} min={5} max={100} step={5} hint="the rest wait for the next run"
              onChange={(v) => setLimit('analyze', v)} disabled={busy} />
          </StageCard>

          <StageCard name="3 · Prepare applications" desc="Draft a cover letter and gather your answers for the top matches." cost="1 AI call per letter"
            on={s.prepare.enabled} paused={s.paused}
            onToggle={(v) => { setS({ ...s, prepare: { ...s.prepare, enabled: v } }); save({ prepare: { enabled: v } }) }}>
            <p className="text-[13px] text-ink-2">Runs right after each Analyze, for jobs scoring {s.prepare.min_fit} or higher.</p>
            <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
              <Stepper label="Cover letters per run" value={s.prepare.limit} min={0} max={20} step={1} hint="highest fit first"
                onChange={(v) => setLimit('prepare', v)} disabled={busy} />
              <Stepper label="Minimum fit" value={s.prepare.min_fit} min={50} max={95} step={5}
                onChange={(v) => { setS({ ...s, prepare: { ...s.prepare, min_fit: v } }); save({ prepare: { min_fit: v } }) }} disabled={busy} />
            </div>
          </StageCard>

          <section className="card flex flex-col gap-3.5 p-[18px]">
            <div>
              <h3 className="text-[17px] font-bold">4 · Apply</h3>
              <p className="mt-0.5 text-[13px] text-ink-2">Fill the application form in the browser and submit. 1 AI call per form.</p>
            </div>
            <fieldset className="flex flex-col gap-2.5">
              <legend className="mb-1.5 text-[13px] text-ink-2">When an application is ready</legend>
              {([
                ['approve', 'Wait for my approval', 'Recommended. Nothing is sent until you approve it and press Submit.'],
                ['auto', 'Submit approved jobs on Greenhouse, Lever and Ashby automatically', s.auto_submit_allowed ? 'Other sites still wait for you.' : 'Needs JOBAGENT_AUTO_SUBMIT=true in .env first.'],
                ['manual', 'I apply myself', 'JobPilot prepares the letter and answers for you to copy.'],
              ] as Array<[ApplyMode, string, string]>).map(([id, label, hint]) => (
                <label key={id} className={clsx('flex cursor-pointer items-start gap-2.5 text-sm', id === 'auto' && !s.auto_submit_allowed && 'opacity-60')}>
                  <input type="radio" name="apply-mode" className="mt-1 h-4 w-4 accent-[var(--accent)]" checked={s.apply_mode === id}
                    disabled={busy || (id === 'auto' && !s.auto_submit_allowed)}
                    onChange={() => { setS({ ...s, apply_mode: id }); save({ apply_mode: id }) }} />
                  <span><span className="font-semibold">{label}</span><span className="block text-[13px] text-ink-2">{hint}</span></span>
                </label>
              ))}
            </fieldset>
          </section>
        </div>

        <aside className="flex flex-col gap-3.5" style={{ flex: '1 1 300px' }}>
          <section className="card flex flex-col gap-2.5 p-[18px]">
            <h3 className="text-[15px] font-bold">Estimated AI use per week</h3>
            <div className="num text-[34px] font-extrabold tracking-tight">{est.total}<span className="text-[15px] font-medium text-ink-2"> calls</span></div>
            <div className="h-2 rounded-full" style={{ background: 'var(--accent-soft)' }}>
              <div className="h-2 rounded-full transition-[width]" style={{ width: `${Math.min(100, (est.total / WEEKLY_GUARD) * 100)}%`, background: est.total > WEEKLY_GUARD ? 'var(--bad)' : 'var(--accent)' }} />
            </div>
            <p className="text-[13px] leading-relaxed text-ink-2">
              {s.paused ? 'Scheduled runs are paused. Run now still works.'
                : est.total > WEEKLY_GUARD ? 'Above a comfortable 300 calls a week. Fewer days or a lower per-run limit leaves room for your own use of the same AI plan.'
                  : 'Comfortably inside a typical AI subscription (ChatGPT Plus or Claude Pro), with room left for your own use.'}
            </p>
            <dl className="mt-1 grid grid-cols-[1fr_auto] gap-x-3 gap-y-1.5 text-[13px]">
              <dt className="text-ink-2">Analyze</dt><dd className="num text-right font-semibold">{est.analyze}</dd>
              <dt className="text-ink-2">Cover letters</dt><dd className="num text-right font-semibold">{est.prepare}</dd>
              <dt className="text-ink-2">Reading job sites</dt><dd className="num text-right font-semibold">{est.collect}</dd>
            </dl>
          </section>
          <section className="card flex flex-col gap-2.5 p-[18px]">
            <h3 className="text-[15px] font-bold">Run a stage now</h3>
            {rc.running ? (
              <Button variant="outline" icon={Square} onClick={() => rc.stop.mutate()} loading={rc.stop.isPending} disabled={rc.stopping}>{rc.stopping ? 'Stopping…' : 'Stop current run'}</Button>
            ) : (
              <div className="flex flex-wrap gap-2">
                <Button variant="outline" icon={Play} onClick={() => setRun('collect')} loading={rc.collect.isPending}>Collect</Button>
                <Button variant="outline" icon={Sparkles} onClick={() => setRun('analyze')} loading={rc.analyze.isPending}>Analyze</Button>
                <Button variant="primary" icon={Play} onClick={() => setRun('cycle')} loading={rc.start.isPending}>Both</Button>
              </div>
            )}
            <RunDialog stage={run} onClose={() => setRun(null)} />
            <p className="text-[13px] text-ink-2">Stop finishes the job or form in progress first, so nothing is left half-done.</p>
          </section>
          <section className="card flex flex-col gap-2 p-[18px] text-[13px] leading-relaxed text-ink-2">
            <h3 className="text-[15px] font-bold text-ink">If the Mac is asleep</h3>
            <p>A missed run starts when the Mac wakes, if it is within 2 hours. Older missed runs wait for the next scheduled time. Runs only happen while JobPilot is running.</p>
            <h3 className="mt-1 text-[15px] font-bold text-ink">If the AI hits its limit</h3>
            <p>Scoring can switch to your local model when the fallback is on (Settings › AI). Cover letters wait for the next run.</p>
          </section>
        </aside>
      </div>
    </div>
  )
}

function StageCard({ name, desc, cost, free, on, paused, next, onToggle, children }: {
  name: string; desc: string; cost: string; free?: boolean; on: boolean; paused: boolean; next?: string | null; onToggle: (v: boolean) => void; children: React.ReactNode
}) {
  return (
    <section className={clsx('card flex flex-col gap-3.5 p-[18px] transition-opacity', (!on || paused) && 'opacity-70')}>
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-[220px] flex-1">
          <h3 className="text-[17px] font-bold">{name}</h3>
          <p className="mt-0.5 text-[13px] leading-snug text-ink-2">{desc}</p>
        </div>
        <span className="rounded-md px-2 py-1 text-xs font-semibold" style={free
          ? { background: 'color-mix(in oklab, var(--good) 14%, transparent)', color: 'var(--good-ink)' }
          : { background: 'color-mix(in oklab, var(--accent) 14%, transparent)', color: 'var(--accent-ink)' }}>{cost}</span>
        <Switch checked={on} onChange={onToggle} ariaLabel={`${name.replace(/^\d+ · /, '')} on schedule`} />
      </div>
      {children}
      {on && !paused && next && <p className="text-xs text-ink-2">Next run {fmtDateTime(next)} ({fmtRelative(next)})</p>}
    </section>
  )
}

const DAY_LONG = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

function DaysRow({ stage, days, time, disabled, onDay, onTime }: { stage: string; days: number[]; time: string; disabled: boolean; onDay: (d: number) => void; onTime: (t: string) => void }) {
  const [t, setT] = useState(time)
  useEffect(() => setT(time), [time])
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="w-11 text-[13px] text-ink-2">Days</span>
      {DAY_SHORT.map((label, i) => {
        const on = days.includes(i)
        return (
          <button key={label} type="button" aria-pressed={on} aria-label={`${stage} on ${DAY_LONG[i]}`} disabled={disabled} onClick={() => onDay(i)}
            className={clsx('h-[38px] min-w-[50px] rounded-lg border px-2.5 text-[13px] font-semibold transition-colors',
              on ? 'border-[var(--accent)] bg-accent text-on-accent' : 'border-[var(--baseline)] bg-surface text-ink-2 hover:text-ink')}>{label}</button>
        )
      })}
      <span className="ml-2 text-[13px] text-ink-2">at</span>
      <input type="time" aria-label={`${stage} time`} className="input !h-[38px] !w-[130px]" value={t} disabled={disabled}
        onChange={(e) => setT(e.target.value)} onBlur={() => t && t !== time && onTime(t)} />
    </div>
  )
}

function Stepper({ label, value, min, max, step, hint, disabled, onChange }: {
  label: string; value: number; min: number; max: number; step: number; hint?: string; disabled?: boolean; onChange: (v: number) => void
}) {
  return (
    <div className="flex flex-wrap items-center gap-2.5 text-[13px]">
      <span>{label}</span>
      <Button size="sm" variant="outline" icon={Minus} aria-label={`Less: ${label}`} disabled={disabled || value <= min} onClick={() => onChange(Math.max(min, value - step))} />
      <span className="num min-w-8 text-center text-[15px] font-bold">{value}</span>
      <Button size="sm" variant="outline" icon={Plus} aria-label={`More: ${label}`} disabled={disabled || value >= max} onClick={() => onChange(Math.min(max, value + step))} />
      {hint && <span className="text-ink-2">{hint}</span>}
    </div>
  )
}
