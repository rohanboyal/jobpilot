import { useEffect, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { clsx } from 'clsx'
import { patchApplication } from '../api'
import type { Application, Outcome } from '../types'
import { useToast } from '../lib/toast'
import { errorMessage } from '../lib/tasks'
import { fmtDate, parseUTC } from '../lib/format'
import { Button, Chip, type Tone } from './ui'

export const OUTCOMES: Array<{ id: Outcome; label: string; tone: Tone }> = [
  { id: 'awaiting', label: 'Waiting to hear', tone: 'neutral' },
  { id: 'responded', label: 'Heard back', tone: 'accent' },
  { id: 'interview', label: 'Interviewing', tone: 'violet' },
  { id: 'offer', label: 'Offer', tone: 'good' },
  { id: 'rejected', label: 'Rejected', tone: 'bad' },
  { id: 'no_response', label: 'No response', tone: 'muted' },
]

export function OutcomeChip({ outcome }: { outcome: Outcome | null | undefined }) {
  const o = OUTCOMES.find((x) => x.id === (outcome ?? 'awaiting'))!
  return <Chip tone={o.tone}>{o.label}</Chip>
}

function isoDate(d: Date): string {
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10)
}

export function useOutcomeUpdate(id: number) {
  const qc = useQueryClient()
  const toast = useToast()
  return useMutation({
    mutationFn: (body: { outcome?: Outcome; outcome_notes?: string | null; follow_up_at?: string | null }) => patchApplication(id, body),
    onSuccess: () => {
      for (const k of ['application', 'applications', 'today', 'jobs', 'stats']) qc.invalidateQueries({ queryKey: [k] })
    },
    onError: (e) => toast.error('Could not update', errorMessage(e)),
  })
}

/** "Remind me again in N days" as an ISO timestamp the API stores. */
export function inDays(n: number): string {
  const d = new Date()
  d.setDate(d.getDate() + n)
  d.setHours(9, 0, 0, 0)
  return d.toISOString()
}

/** What happened after applying: stage buttons, notes and the follow-up reminder. Only for submitted applications. */
export default function OutcomeTracker({ a }: { a: Application }) {
  const toast = useToast()
  const update = useOutcomeUpdate(a.id)
  const [notes, setNotes] = useState(a.outcome_notes ?? '')
  const due = parseUTC(a.follow_up_at)
  const [follow, setFollow] = useState(due ? isoDate(due) : '')
  useEffect(() => { setNotes(a.outcome_notes ?? ''); const d = parseUTC(a.follow_up_at); setFollow(d ? isoDate(d) : '') }, [a.id, a.outcome_notes, a.follow_up_at])
  const current = a.outcome ?? 'awaiting'
  const open = current === 'awaiting' || current === 'responded' || current === 'interview'

  return (
    <section className="card flex flex-col gap-4 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-[15px] font-bold">After applying</h3>
        {a.submitted_at && <span className="text-xs text-ink-2">Applied {fmtDate(a.submitted_at)}{a.outcome_at && current !== 'awaiting' ? ` · updated ${fmtDate(a.outcome_at)}` : ''}</span>}
      </div>
      <div role="radiogroup" aria-label="Outcome" className="flex flex-wrap gap-2">
        {OUTCOMES.map((o) => (
          <button key={o.id} type="button" role="radio" aria-checked={current === o.id} disabled={update.isPending}
            onClick={() => current !== o.id && update.mutate({ outcome: o.id }, { onSuccess: () => toast.success(`Marked: ${o.label}`) })}
            className={clsx('h-9 rounded-lg border px-3 text-[13px] font-semibold transition-colors',
              current === o.id ? 'border-[var(--accent)] bg-accent text-on-accent' : 'border-[var(--baseline)] bg-surface text-ink-2 hover:text-ink')}>{o.label}</button>
        ))}
      </div>
      <div className="grid gap-3 md:grid-cols-[1fr_220px]">
        <label className="flex flex-col gap-1.5 text-xs font-medium text-ink-2">Notes
          <textarea className="input text-sm" rows={2} value={notes} placeholder="Recruiter name, interview dates, what was asked…" onChange={(e) => setNotes(e.target.value)}
            onBlur={() => notes !== (a.outcome_notes ?? '') && update.mutate({ outcome_notes: notes || null })} />
        </label>
        <label className="flex flex-col gap-1.5 text-xs font-medium text-ink-2">Follow up on
          <input type="date" className="input text-sm" value={follow} disabled={!open} onChange={(e) => setFollow(e.target.value)}
            onBlur={() => update.mutate({ follow_up_at: follow ? new Date(follow + 'T09:00:00').toISOString() : null })} />
          <span className="font-normal">{open ? 'Shows on Today when it is due.' : 'No reminder once it is closed.'}</span>
        </label>
      </div>
      {open && (
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="ghost" onClick={() => update.mutate({ follow_up_at: inDays(7) })}>Remind me in a week</Button>
          <Button size="sm" variant="ghost" onClick={() => update.mutate({ follow_up_at: null })}>No reminder</Button>
        </div>
      )}
    </section>
  )
}
