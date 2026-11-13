import { clsx } from 'clsx'
import { Chip, type Tone } from './ui'
import type { AppStatus, JobStatus, RunStatus } from '../types'
import { titleCase } from '../lib/format'

const JOB_TONES: Record<JobStatus, Tone> = {
  new: 'neutral', filtered_out: 'muted', queued: 'accent', scored: 'violet', shortlisted: 'good', rejected: 'bad',
  applying: 'warn', applied: 'good', expired: 'muted',
}
const JOB_LABELS: Partial<Record<JobStatus, string>> = { filtered_out: 'Filtered out', queued: 'Queued for scoring', applying: 'In progress' }

const APP_TONES: Record<AppStatus, Tone> = {
  draft: 'neutral', needs_review: 'warn', approved: 'accent', submitting: 'accent', submitted: 'good', failed: 'bad',
  manual: 'violet', withdrawn: 'muted',
}
const RUN_TONES: Record<RunStatus | 'cancelled', Tone> = { running: 'accent', ok: 'good', error: 'bad', partial: 'warn', cancelled: 'warn' }
const RUN_LABELS: Record<RunStatus | 'cancelled', string> = { running: 'Running', ok: 'Done', error: 'Failed', partial: 'Partly done', cancelled: 'Stopped' }

export function JobStatusChip({ status }: { status: JobStatus }) {
  return <Chip tone={JOB_TONES[status] ?? 'neutral'}>{JOB_LABELS[status] ?? titleCase(status)}</Chip>
}
export function AppStatusChip({ status }: { status: AppStatus }) {
  return <Chip tone={APP_TONES[status] ?? 'neutral'} dot={status === 'submitting'}>{titleCase(status)}</Chip>
}
/** Runs and background tasks: "ok" reads as Done, "error" as Failed, "cancelled" as Stopped. */
export function RunStatusChip({ status }: { status: RunStatus | 'cancelled' }) {
  return <Chip tone={RUN_TONES[status] ?? 'neutral'} dot={status === 'running'}>{RUN_LABELS[status] ?? titleCase(status)}</Chip>
}

export function fitTone(score: number | null | undefined): { tone: Tone; label: string } {
  if (score === null || score === undefined) return { tone: 'muted', label: 'Not scored' }
  if (score >= 85) return { tone: 'good', label: 'Strong match' }
  if (score >= 70) return { tone: 'accent', label: 'Good match' }
  if (score >= 50) return { tone: 'warn', label: 'Stretch' }
  return { tone: 'bad', label: 'Weak match' }
}

export function FitBadge({ score, size = 'md' }: { score: number | null | undefined; size?: 'sm' | 'md' | 'lg' }) {
  const { tone, label } = fitTone(score)
  const dims = size === 'lg' ? 'h-14 w-14 text-xl' : size === 'sm' ? 'h-7 w-7 text-[11px]' : 'h-9 w-9 text-sm'
  return (
    <span title={label} className={clsx('num inline-flex shrink-0 items-center justify-center rounded-lg font-semibold', dims)}
      style={{
        background: tone === 'muted' ? 'var(--surface-2)' : `color-mix(in oklab, var(--${tone}) 16%, transparent)`,
        color: tone === 'muted' ? 'var(--muted)' : `var(--${tone}-ink)`,
      }}>
      {score ?? '–'}
    </span>
  )
}

export function TrustChip({ score }: { score: number | null | undefined }) {
  if (score === null || score === undefined) return <span className="text-xs text-muted">—</span>
  const tone: Tone = score >= 70 ? 'good' : score >= 40 ? 'warn' : 'bad'
  return <Chip tone={tone} title="Genuineness score">Trust {score}</Chip>
}

export function SourceChip({ source }: { source: string }) {
  const label = source.startsWith('site_') ? source.slice(5) : source
  return <Chip tone="neutral" className="capitalize">{label.replace(/_/g, ' ')}</Chip>
}
