import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Play, Sparkles } from 'lucide-react'
import { clsx } from 'clsx'
import { getRunEstimate, listProfiles, listResumes } from '../api'
import type { SearchProfileRow } from '../types'
import { useRunControl } from '../lib/runControl'
import { Button, Dialog, Spinner } from './ui'

export type RunStage = 'cycle' | 'collect' | 'analyze'

const META: Record<RunStage, { title: string; start: string; desc: string }> = {
  cycle: { title: 'Run now', start: 'Start run', desc: 'Collect new jobs, then analyze the best matches and draft applications for the top ones.' },
  collect: { title: 'Collect jobs', start: 'Start collecting', desc: 'Search your sources for new jobs. Free, except sites the AI reads.' },
  analyze: { title: 'Analyze matches', start: 'Start analyzing', desc: 'Score the best waiting matches with the AI and draft applications for the top ones.' },
}

/** A profile a run can use: turned on and with something to search for (the server applies the same rule). */
export const canRun = (p: SearchProfileRow) => p.enabled && [...p.search.roles, ...p.search.title_keywords].some((x) => x.trim())

const LAST = 'jobpilot.run'      // the last choice, remembered in this browser only

function lastChoice(): { ids?: number[]; oneByOne?: boolean } {
  try { return JSON.parse(localStorage.getItem(LAST) ?? '{}') ?? {} } catch { return {} }
}

/** Pick the search profiles a run covers, and whether they run together or one after another. */
export default function RunDialog({ stage, onClose }: { stage: RunStage | null; onClose: () => void }) {
  const rc = useRunControl()
  const open = stage !== null
  const profiles = useQuery({ queryKey: ['profiles'], queryFn: listProfiles, enabled: open })
  const resumes = useQuery({ queryKey: ['resumes'], queryFn: listResumes, enabled: open, staleTime: 60_000 })
  const list = profiles.data ?? []
  const ready = list.filter(canRun)
  const [ids, setIds] = useState<number[]>([])
  const [oneByOne, setOneByOne] = useState(false)
  // Each time it opens: the last choice that still applies, else every active profile.
  useEffect(() => {
    if (!open || !profiles.data) return
    const last = lastChoice()
    const keep = (last.ids ?? []).filter((i) => ready.some((p) => p.id === i))
    setIds(keep.length ? keep : ready.map((p) => p.id))
    setOneByOne(!!last.oneByOne)
  }, [open, profiles.data]) // eslint-disable-line react-hooks/exhaustive-deps

  const all = ready.length > 0 && ready.every((p) => ids.includes(p.id))
  const separate = oneByOne && ids.length > 1
  // Every active profile together is the same run the schedule makes: send no list, so it reads as one.
  const chosen = all && !separate ? null : ids
  const estimate = useQuery({
    queryKey: ['run-estimate', stage, chosen, separate],
    queryFn: () => getRunEstimate(stage!, chosen, separate),
    enabled: open && ids.length > 0,
  })
  const mutation = stage === 'collect' ? rc.collect : stage === 'analyze' ? rc.analyze : rc.start
  // Kept in the profiles' own order, which is the order "one after another" runs them in.
  const toggle = (id: number) => setIds((x) => ready.map((p) => p.id).filter((i) => (i === id ? !x.includes(id) : x.includes(i))))
  const resumeName = (p: SearchProfileRow) => resumes.data?.find((r) => r.id === (p.resume_id ?? 1))?.name

  const go = () => {
    try { localStorage.setItem(LAST, JSON.stringify({ ids, oneByOne })) } catch { /* private window: nothing to remember */ }
    mutation.mutate({ profile_ids: chosen, one_by_one: separate }, { onSuccess: onClose })
  }

  if (!stage) return null
  const meta = META[stage]
  const e = estimate.data
  return (
    <Dialog open={open} onClose={onClose} title={meta.title}
      footer={<>
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button variant="primary" icon={stage === 'analyze' ? Sparkles : Play} onClick={go} loading={mutation.isPending}
          disabled={!ids.length || rc.running}>{meta.start}</Button>
      </>}>
      <p className="text-[13px] leading-relaxed text-ink-2">{meta.desc}</p>

      {profiles.isLoading ? <div className="flex justify-center py-6"><Spinner /></div> : (
        <fieldset className="mt-4 min-w-0">
          <legend className="mb-2 flex w-full items-center justify-between text-xs font-semibold text-ink-2">
            <span>Profiles to run</span>
            {ready.length > 1 && <button type="button" className="font-semibold text-accent-ink hover:underline"
              onClick={() => setIds(all ? [] : ready.map((p) => p.id))}>{all ? 'Clear' : 'Select all'}</button>}
          </legend>
          <div className="flex flex-col gap-1.5">
            {list.map((p) => {
              const ok = canRun(p)
              return (
                <label key={p.id} className={clsx('flex items-start gap-3 rounded-lg border px-3 py-2.5 transition-colors',
                  ok ? 'cursor-pointer border-[var(--baseline)] hover:bg-surface-2' : 'border-line opacity-60',
                  ok && ids.includes(p.id) && 'border-[var(--accent)] bg-[color-mix(in_oklab,var(--accent)_6%,transparent)]')}>
                  <input type="checkbox" className="mt-0.5 h-[18px] w-[18px] shrink-0 accent-[var(--accent)]" disabled={!ok}
                    checked={ok && ids.includes(p.id)} onChange={() => toggle(p.id)} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-semibold">{p.name}</span>
                    <span className="block text-xs text-ink-2">
                      {ok ? <>{p.matching} job{p.matching === 1 ? '' : 's'} waiting or analyzed{resumeName(p) ? <> · resume: {resumeName(p)}</> : null}</>
                        : !p.enabled ? 'Turned off' : 'No job titles yet'}
                    </span>
                  </span>
                </label>
              )
            })}
          </div>
          {list.some((p) => !canRun(p)) && <p className="mt-2 text-xs text-ink-2">Greyed-out profiles are off or have no job titles. Change them in <Link to="/profiles" onClick={onClose}>Profiles &amp; resumes</Link>.</p>}
          {!ready.length && <p className="mt-2 text-xs text-warn-ink">No profile can run yet. Add job titles to one in <Link to="/profiles" onClick={onClose}>Profiles &amp; resumes</Link>.</p>}
        </fieldset>
      )}

      {ids.length > 1 && (
        <fieldset className="mt-4 min-w-0">
          <legend className="mb-2 text-xs font-semibold text-ink-2">How to run them</legend>
          <div className="flex flex-col gap-1.5">
            <Choice checked={!oneByOne} onChange={() => setOneByOne(false)} title="Together"
              hint="One pass: each site is read once and searches every profile's top job title. The best matches across them are analyzed first." />
            <Choice checked={oneByOne} onChange={() => setOneByOne(true)} title="One after another"
              hint="A full pass per profile: more job titles searched for each, and each gets its own Analyze limit. Takes longer and uses more AI calls." />
          </div>
        </fieldset>
      )}

      {ids.length > 0 && (
        <p className="mt-4 text-xs text-ink-2">
          {!e ? 'Working out the AI calls…' : e.total_ai === 0 ? 'No AI calls.' : <>
            Up to <strong className="text-ink">{e.total_ai} AI call{e.total_ai === 1 ? '' : 's'}</strong> · {e.left} left in your limits now.
            {e.total_ai > e.left && <span className="text-warn-ink"> It stops when the limit is reached and continues on the next run.</span>}
          </>}
        </p>
      )}
      {rc.running && <p className="mt-2 text-xs text-warn-ink">Another run is going. Wait for it to finish or stop it first.</p>}
    </Dialog>
  )
}

function Choice({ checked, onChange, title, hint }: { checked: boolean; onChange: () => void; title: string; hint: string }) {
  return (
    <label className={clsx('flex cursor-pointer items-start gap-3 rounded-lg border px-3 py-2.5 transition-colors hover:bg-surface-2',
      checked ? 'border-[var(--accent)] bg-[color-mix(in_oklab,var(--accent)_6%,transparent)]' : 'border-[var(--baseline)]')}>
      <input type="radio" name="run-how" className="mt-0.5 h-4 w-4 shrink-0 accent-[var(--accent)]" checked={checked} onChange={onChange} />
      <span><span className="block text-sm font-semibold">{title}</span><span className="block text-xs leading-relaxed text-ink-2">{hint}</span></span>
    </label>
  )
}
