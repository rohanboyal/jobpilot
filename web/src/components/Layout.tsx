import { useEffect, useState } from 'react'
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Briefcase, CalendarClock, ChartColumn, History, House, Inbox, Menu, Monitor, Moon, Play, Send, SlidersHorizontal, Square, Sun, UserRound, X } from 'lucide-react'
import { clsx } from 'clsx'
import { getHealth } from '../api'
import { useTheme } from '../lib/theme'
import { fmtRelative } from '../lib/format'
import { useRunControl } from '../lib/runControl'
import { Button } from './ui'
import RunDialog, { type RunStage } from './RunDialog'

const NAV = [
  { to: '/', label: 'Today', icon: House, end: true },
  { to: '/jobs', label: 'Jobs', icon: Briefcase },
  { to: '/applications', label: 'Applications', icon: Inbox },
  { to: '/profiles', label: 'Profiles & resumes', icon: UserRound },
  { to: '/schedule', label: 'Schedule', icon: CalendarClock },
  { to: '/settings', label: 'Settings', icon: SlidersHorizontal },
]
// Pages you check now and then rather than act on: smaller, below a divider.
const NAV_SECONDARY = [
  { to: '/insights', label: 'Insights', icon: ChartColumn },
  { to: '/activity', label: 'Activity log', icon: History },
]
const TITLES: Array<[string, string]> = [['/setup', 'Setup']]

export default function Layout() {
  const [theme, setTheme] = useTheme()
  const loc = useLocation()
  const [menuOpen, setMenuOpen] = useState(false)
  const [run, setRun] = useState<RunStage | null>(null)
  const rc = useRunControl()
  const health = useQuery({ queryKey: ['health'], queryFn: getHealth, refetchInterval: 30_000 })
  const current = [...NAV, ...NAV_SECONDARY].find((n) => ('end' in n && n.end ? loc.pathname === n.to : loc.pathname.startsWith(n.to)))
  const title = current?.label ?? TITLES.find(([p]) => loc.pathname.startsWith(p))?.[1] ?? 'JobPilot'
  const budget = health.data?.budget
  const ai = health.data?.llm
  const aiName = ai ? ai.label.replace(/ \(.*\)$/, '') : 'AI'      // "Claude Code CLI (Claude plan)" -> "Claude Code CLI"
  const sched = rc.scheduler
  const nextTheme = theme === 'light' ? 'dark' : theme === 'dark' ? 'system' : 'light'
  const ThemeIcon = theme === 'light' ? Sun : theme === 'dark' ? Moon : Monitor
  useEffect(() => setMenuOpen(false), [loc.pathname])
  useEffect(() => { document.title = title === 'JobPilot' ? 'JobPilot' : `${title} · JobPilot` }, [title])
  useEffect(() => {
    if (!menuOpen) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setMenuOpen(false) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [menuOpen])

  const scheduleText = !sched ? '' : !sched.available ? 'Scheduler not running' : sched.paused ? 'Scheduled runs paused'
    : sched.next_run_at ? `Next run ${fmtRelative(sched.next_run_at)}` : 'Nothing scheduled'

  const sidebar = (
    <aside className="side flex h-full w-[236px] shrink-0 flex-col px-3 py-5">
      <div className="flex items-center gap-2.5 px-2.5 pb-6">
        <Link to="/" aria-label="JobPilot home: Today" className="flex min-w-0 flex-1 items-center gap-2.5 rounded-[10px] no-underline focus-ring">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[10px]" style={{ background: '#14a394' }}>
            <Send size={18} color="#0b1a18" strokeWidth={2.2} />
          </span>
          <span className="min-w-0">
            <span className="block text-[16px] font-extrabold tracking-tight text-[#f4f2ec]">JobPilot</span>
            <span className="block text-xs" style={{ color: 'var(--side-muted)' }}>{aiName} · on this computer</span>
          </span>
        </Link>
        <button className="rounded-md p-1 md:hidden" style={{ color: 'var(--side-ink)' }} onClick={() => setMenuOpen(false)} aria-label="Close menu"><X size={16} /></button>
      </div>
      <nav aria-label="Main" className="flex flex-col gap-1">
        {NAV.map((n) => (
          <NavLink key={n.to} to={n.to} end={n.end}
            className={({ isActive }) => clsx('side-link flex items-center gap-3 rounded-[10px] px-3 py-2.5 text-sm no-underline transition-colors', isActive && 'active')}>
            <n.icon size={17} />
            {n.label}
          </NavLink>
        ))}
        <div className="mx-3 my-3 border-t" style={{ borderColor: 'var(--side-line)' }} />
        {NAV_SECONDARY.map((n) => (
          <NavLink key={n.to} to={n.to}
            className={({ isActive }) => clsx('side-link flex items-center gap-3 rounded-[10px] px-3 py-2 text-[13px] no-underline transition-colors', isActive && 'active')}>
            <n.icon size={15} />
            {n.label}
          </NavLink>
        ))}
      </nav>
      <Link to="/settings?tab=ai" className="mt-auto flex flex-col gap-2 border-t px-3 pt-4 text-xs no-underline" style={{ borderColor: 'var(--side-line)', color: 'var(--side-muted)' }}>
        <div className="flex justify-between"><span>AI calls today</span><span className="num font-bold text-[#f4f2ec]">{budget ? `${budget.day.used} / ${budget.day.max}` : '—'}</span></div>
        <div className="h-1.5 rounded-full" style={{ background: 'var(--side-line)' }}>
          <div className="h-1.5 rounded-full" style={{ width: `${budget ? Math.min(100, (budget.day.used / Math.max(1, budget.day.max)) * 100) : 0}%`, background: '#2bb3a3' }} />
        </div>
        <div className="flex items-center gap-2" title={ai?.primary.error ?? ai?.model} style={{ color: ai?.primary.ok ? '#6ee7b7' : '#fca5a5' }}>
          <span className="h-2 w-2 rounded-full" style={{ background: ai?.primary.ok ? '#34d399' : '#f87171' }} />
          {ai ? `${aiName} ${ai.primary.ok ? 'ready' : 'not ready'}` : 'Checking the AI…'}
        </div>
      </Link>
    </aside>
  )

  return (
    <div className="flex h-full">
      <div className="hidden md:flex">{sidebar}</div>
      {menuOpen && (
        <div className="fixed inset-0 z-40 flex md:hidden" role="dialog" aria-modal="true" aria-label="Menu"
          onClickCapture={(e) => { if ((e.target as HTMLElement).closest('a')) setMenuOpen(false) }}>
          {sidebar}
          <button className="flex-1 bg-black/40" aria-label="Close menu" onClick={() => setMenuOpen(false)} />
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center gap-3 border-b border-line bg-surface px-3 md:px-6">
          <button className="rounded-md p-1.5 text-ink-2 hover:bg-surface-2 md:hidden" onClick={() => setMenuOpen(true)} aria-label="Open menu"><Menu size={18} /></button>
          <h1 className="text-[15px] font-bold">{title}</h1>
          <div className="ml-auto flex min-w-0 items-center gap-3 text-xs text-ink-2">
            {rc.running ? (
              <span className="hidden items-center gap-2 font-medium text-accent-ink sm:inline-flex">
                <span className="pulse inline-block h-2 w-2 rounded-full bg-accent" />
                {rc.stopping ? 'Stopping…' : rc.runningTasks[0]?.label}
              </span>
            ) : (
              <Link to="/schedule" className="hidden min-w-0 items-center gap-1.5 truncate text-ink-2 no-underline hover:text-ink lg:inline-flex" title="Open the schedule">
                <CalendarClock size={14} className="shrink-0" />
                <span className="truncate">{scheduleText}</span>
              </Link>
            )}
            {rc.running
              ? <Button size="sm" variant="outline" icon={Square} onClick={() => rc.stop.mutate()} loading={rc.stop.isPending} disabled={rc.stopping}>Stop</Button>
              : <Button size="sm" variant="primary" icon={Play} onClick={() => setRun('cycle')} loading={rc.start.isPending}>Run now</Button>}
            <button onClick={() => setTheme(nextTheme)} title={`Theme: ${theme} (click to switch)`} aria-label="Switch theme" className="rounded-md p-1.5 text-ink-2 hover:bg-surface-2 hover:text-ink">
              <ThemeIcon size={16} />
            </button>
          </div>
        </header>
        <main className="scroll-thin min-h-0 flex-1 overflow-y-auto bg-bg px-3 py-5 md:px-8 md:py-7">
          <Outlet />
        </main>
        <RunDialog stage={run} onClose={() => setRun(null)} />
      </div>
    </div>
  )
}
