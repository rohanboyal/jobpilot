export function parseUTC(iso: string | null | undefined): Date | null {
  if (!iso) return null
  const hasTz = /[zZ]$|[+-]\d{2}:?\d{2}$/.test(iso)
  const d = new Date(hasTz ? iso : `${iso}Z`)
  return Number.isNaN(d.getTime()) ? null : d
}

export function fmtDate(iso: string | null | undefined, opts: Intl.DateTimeFormatOptions = { dateStyle: 'medium' }): string {
  const d = parseUTC(iso)
  return d ? new Intl.DateTimeFormat(undefined, opts).format(d) : '—'
}

export function fmtDateTime(iso: string | null | undefined): string {
  return fmtDate(iso, { dateStyle: 'medium', timeStyle: 'short' })
}

export function fmtRelative(iso: string | null | undefined): string {
  const d = parseUTC(iso)
  if (!d) return '—'
  const diff = (Date.now() - d.getTime()) / 1000
  const abs = Math.abs(diff)
  const future = diff < 0
  const units: Array<[number, string]> = [[60, 's'], [3600, 'm'], [86400, 'h'], [604800, 'd'], [2629800, 'w'], [31557600, 'mo'], [Infinity, 'y']]
  let prev = 1
  for (const [limit, label] of units) {
    if (abs < limit) {
      const n = Math.max(1, Math.floor(abs / prev))
      return future ? `in ${n}${label}` : `${n}${label} ago`
    }
    prev = limit
  }
  return fmtDate(iso)
}

export function fmtDuration(start: string | null | undefined, end: string | null | undefined): string {
  const a = parseUTC(start)
  const b = end ? parseUTC(end) : new Date()
  if (!a || !b) return '—'
  const s = Math.max(0, Math.round((b.getTime() - a.getTime()) / 1000))
  if (s < 60) return `${s}s`
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`
}

export function compact(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—'
  return new Intl.NumberFormat(undefined, { notation: n >= 10000 ? 'compact' : 'standard', maximumFractionDigits: 1 }).format(n)
}

export function titleCase(s: string | null | undefined): string {
  if (!s) return ''
  return s.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

// Counters in run stats and task results, in plain words. Unknown keys fall back to "some_key" -> "some key".
const STAT_LABELS: Record<string, string> = {
  fetched: 'fetched', new: 'new', updated: 'updated', duplicates: 'duplicates', companies_ok: 'companies read', checked: 'checked',
  queued: 'queued for scoring', filtered_out: 'filtered out', retagged: 're-tagged', scored: 'scored', shortlisted: 'shortlisted',
  errors: 'errors', remaining: 'still waiting', prepared: 'prepared', expired_stale: 'expired', cancelled: 'stopped early',
  submitted: 'submitted', failed: 'failed', queries: 'searches', candidates: 'candidates', added_ats: 'boards added',
  added_custom: 'career pages added', known: 'already known', probe_failed: 'checks failed',
}
export const statLabel = (key: string) => STAT_LABELS[key] ?? key.replace(/_/g, ' ')

/** {fetched: 785, new: 785, companies_ok: 6} -> "785 fetched · 785 new · 6 companies read". Nested counters are added up. */
export function summarizeStats(stats: unknown, max = 6): string {
  if (stats === null || stats === undefined) return ''
  if (typeof stats !== 'object') return String(stats)
  const totals = new Map<string, number>()
  const notes: string[] = []
  const walk = (o: Record<string, unknown>, top: boolean) => {
    for (const [k, v] of Object.entries(o)) {
      if (typeof v === 'number') { if (!k.endsWith('_id')) totals.set(k, (totals.get(k) ?? 0) + v) }
      else if (v && typeof v === 'object' && !Array.isArray(v)) walk(v as Record<string, unknown>, false)
      else if (top && typeof v === 'string' && v && k !== 'status') notes.push(`${statLabel(k)}: ${v}`)
    }
  }
  walk(stats as Record<string, unknown>, true)
  const counts = [...totals].filter(([, n]) => n).slice(0, max).map(([k, n]) => `${n.toLocaleString()} ${statLabel(k)}`)
  return [...counts, ...notes].join(' · ')
}

export function hostOf(url: string | null | undefined): string {
  if (!url) return ''
  try {
    return new URL(url).host.replace(/^www\./, '')
  } catch {
    return url
  }
}

export function pct(a: number, b: number): string {
  if (!b) return '—'
  return `${Math.round((a / b) * 100)}%`
}

/** When JobPilot found a job, in words: "found today", "found yesterday", "found 3 days ago" (by calendar day). */
export function foundAgo(iso: string | null | undefined): string {
  const d = parseUTC(iso)
  if (!d) return ''
  const day = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime()
  const days = Math.round((day(new Date()) - day(d)) / 86_400_000)
  return days <= 0 ? 'found today' : days === 1 ? 'found yesterday' : `found ${days} days ago`
}
