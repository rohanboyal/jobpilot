import { useMemo, useState, type ReactNode } from 'react'
import { clsx } from 'clsx'
import { compact, pct } from '../lib/format'

/** Stat tile: label, compact value, optional sub line and meter. */
export function StatTile({ label, value, sub, meter, tone, className }: {
  label: string; value: ReactNode; sub?: ReactNode; meter?: { used: number; max: number }; tone?: 'accent' | 'warn' | 'bad' | 'good'; className?: string
}) {
  return (
    <div className={clsx('card flex flex-col gap-1 p-4', className)}>
      <div className="text-xs text-ink-2">{label}</div>
      <div className="text-[28px] font-semibold leading-none tracking-tight" style={tone ? { color: `var(--${tone}-ink)` } : undefined}>{value}</div>
      {sub && <div className="text-xs text-ink-2">{sub}</div>}
      {meter && <Meter used={meter.used} max={meter.max} className="mt-1" />}
    </div>
  )
}

/** Meter: fill severity changes with the ratio; the track is a lighter step of the same ramp. */
export function Meter({ used, max, className }: { used: number; max: number; className?: string }) {
  const ratio = max > 0 ? Math.min(1, used / max) : 0
  const fill = ratio >= 0.95 ? 'var(--bad)' : ratio >= 0.75 ? 'var(--warn)' : 'var(--accent)'
  const track = ratio >= 0.95 ? 'color-mix(in oklab, var(--bad) 18%, transparent)' : ratio >= 0.75 ? 'color-mix(in oklab, var(--warn) 22%, transparent)' : 'color-mix(in oklab, var(--accent) 18%, transparent)'
  return (
    <div className={clsx('h-1.5 w-full overflow-hidden rounded-full', className)} style={{ background: track }} role="meter" aria-valuenow={used} aria-valuemin={0} aria-valuemax={max}>
      <div className="h-full rounded-full transition-[width]" style={{ width: `${ratio * 100}%`, background: fill }} />
    </div>
  )
}

/** Funnel: ordinal single-hue ramp, bars anchored left, labels in text ink. */
export function Funnel({ stages }: { stages: Array<{ label: string; value: number }> }) {
  const max = Math.max(1, ...stages.map((s) => s.value))
  const steps = ['var(--f1)', 'var(--f2)', 'var(--f3)', 'var(--f4)', 'var(--f5)']
  return (
    <div className="flex flex-col gap-2">
      {stages.map((s, i) => {
        const prev = i > 0 ? stages[i - 1].value : null
        return (
          <div key={s.label} className="grid grid-cols-[120px_1fr_max-content] items-center gap-3 text-xs">
            <div className="text-ink-2">{s.label}</div>
            <div className="relative h-5 rounded-[4px] bg-surface-2">
              <div className="absolute inset-y-0 left-0 rounded-[4px]" style={{ width: `${Math.max(s.value > 0 ? 1.5 : 0, (s.value / max) * 100)}%`, background: steps[i % steps.length] }} title={`${s.label}: ${s.value}`} />
            </div>
            <div className="num flex items-baseline gap-2">
              <span className="font-semibold text-ink">{compact(s.value)}</span>
              <span className="w-9 text-right text-muted">{prev !== null ? pct(s.value, prev) : ''}</span>
            </div>
          </div>
        )
      })}
    </div>
  )
}

/** Daily bars: one series, hover tooltip, single direct label on the max bar. */
export function DailyBars({ data, days = 14, height = 120 }: { data: Array<{ day: string; count: number }>; days?: number; height?: number }) {
  const series = useMemo(() => {
    const byDay = new Map(data.map((d) => [d.day, d.count]))
    const out: Array<{ day: string; count: number; label: string }> = []
    const today = new Date()
    for (let i = days - 1; i >= 0; i--) {
      const d = new Date(today)
      d.setDate(today.getDate() - i)
      const key = d.toISOString().slice(0, 10)
      out.push({ day: key, count: byDay.get(key) ?? 0, label: d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) })
    }
    return out
  }, [data, days])
  const [hover, setHover] = useState<number | null>(null)
  const max = Math.max(1, ...series.map((s) => s.count))
  const maxIdx = series.findIndex((s) => s.count === max)
  const W = 100
  const padTop = 16
  const padBottom = 18
  const plotH = height - padTop - padBottom
  const slot = W / series.length
  const barW = slot * 0.62
  const ticks = [0.5, 1].map((f) => ({ y: padTop + plotH * (1 - f), v: Math.round(max * f) }))
  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} ${height}`} preserveAspectRatio="none" className="block h-[120px] w-full" style={{ height }}>
        {ticks.map((t) => (
          <line key={t.v} x1={0} x2={W} y1={t.y} y2={t.y} stroke="var(--line)" strokeWidth={0.3} vectorEffect="non-scaling-stroke" />
        ))}
        <line x1={0} x2={W} y1={padTop + plotH} y2={padTop + plotH} stroke="var(--baseline)" strokeWidth={0.4} vectorEffect="non-scaling-stroke" />
        {series.map((s, i) => {
          const h = (s.count / max) * plotH
          const x = i * slot + (slot - barW) / 2
          const y = padTop + plotH - h
          const active = hover === i
          return (
            <g key={s.day} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              <rect x={i * slot} y={padTop} width={slot} height={plotH} fill="transparent" />
              {s.count > 0 && (
                <rect x={x} y={y} width={barW} height={h} rx={0.8} fill={active ? 'var(--accent-ink)' : 'var(--accent)'} />
              )}
            </g>
          )
        })}
      </svg>
      {/* x labels + direct label in HTML so they never stretch */}
      <div className="pointer-events-none absolute inset-0">
        {series.map((s, i) => (
          (i === 0 || i === series.length - 1 || i === Math.floor(series.length / 2)) && (
            <span key={s.day} className="absolute text-[10px] text-muted whitespace-nowrap" style={{ left: i === series.length - 1 ? undefined : `${((i + 0.5) / series.length) * 100}%`, right: i === series.length - 1 ? 0 : undefined, bottom: 0, transform: i === 0 || i === series.length - 1 ? undefined : 'translateX(-50%)' }}>{s.label}</span>
          )
        ))}
        {max > 0 && maxIdx >= 0 && hover === null && (
          <span className="num absolute text-[10px] font-medium text-ink-2" style={{ left: `${((maxIdx + 0.5) / series.length) * 100}%`, top: `${((padTop + plotH * (1 - series[maxIdx].count / max) - 12) / height) * 100}%`, transform: 'translateX(-50%)' }}>{series[maxIdx].count}</span>
        )}
      </div>
      {hover !== null && (
        <div className="pointer-events-none absolute z-10 -translate-x-1/2 rounded-md border border-line bg-surface px-2 py-1 text-[11px] shadow-[var(--shadow)]"
          style={{ left: `${((hover + 0.5) / series.length) * 100}%`, top: 0 }}>
          <div className="text-ink-2">{series[hover].label}</div>
          <div className="num font-semibold">{series[hover].count} jobs</div>
        </div>
      )}
    </div>
  )
}
