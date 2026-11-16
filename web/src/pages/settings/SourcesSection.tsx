import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Bot, CheckCircle2, Globe, LogIn, LogOut, Play, Shield } from 'lucide-react'
import { ApiError, browserLogin, forgetBrowserLogin, putSources, startCrawl } from '../../api'
import type { SourceInfo } from '../../types'
import { useToast } from '../../lib/toast'
import { errorMessage } from '../../lib/tasks'
import { fmtRelative } from '../../lib/format'
import { Button, Card, Chip, Switch } from '../../components/ui'
import { RunStatusChip } from '../../components/status'

const HEALTH: Partial<Record<SourceInfo['health'], { label: string; tone: 'warn' | 'bad' | 'neutral' }>> = {
  failing: { label: 'failing', tone: 'bad' }, blocked: { label: 'needs sign-in', tone: 'warn' }, empty: { label: 'finding nothing', tone: 'warn' },
  idle: { label: 'idle', tone: 'neutral' },
}

function HealthChip({ health, note }: { health: SourceInfo['health']; note: string }) {
  const h = HEALTH[health]
  return h ? <Chip tone={h.tone} title={note}>{h.label}</Chip> : null
}

const KIND_META: Record<SourceInfo['kind'], { title: string; blurb: string }> = {
  ats: { title: 'Company job boards (API)', blurb: 'Official JSON endpoints of the ATSs your tracked companies use. Reliable, no login, free.' },
  board: { title: 'Job boards (public)', blurb: 'Public APIs and public search pages. No account involved.' },
  browser: { title: 'Browser sources', blurb: 'Read in a saved Chromium profile. Sign in once where needed; the session is reused. Sites you sign in to are read slowly, about once a day, to protect your account. Sites without CSS selectors use one AI call per results page.' },
}

export default function SourcesSection({ sources }: { sources: SourceInfo[] }) {
  const qc = useQueryClient()
  const toast = useToast()
  const toggle = useMutation({
    mutationFn: ({ name, on }: { name: string; on: boolean }) => putSources({ [name]: on }),
    onSuccess: (r) => {
      toast.success('Signed out', r.domain ? `JobPilot's browser is no longer signed in to ${r.domain}. Your own browsers are untouched.` : undefined)
      qc.invalidateQueries({ queryKey: ['settings'] }); qc.invalidateQueries({ queryKey: ['sources'] })
    },
    onError: (e) => toast.error('Could not sign out', errorMessage(e)),
  })
  const run = useMutation({
    mutationFn: (name: string) => startCrawl([name]),
    onSuccess: () => { toast.success('Crawl started'); qc.invalidateQueries({ queryKey: ['tasks'] }) },
    onError: (e) => (e instanceof ApiError && e.status === 409 ? toast.info('A crawl is already running') : toast.error('Could not start', errorMessage(e))),
  })
  const login = useMutation({
    mutationFn: (site: string) => browserLogin(site),
    onSuccess: (r) => {
      toast.success(`${r.browser} opened`, r.note)
      qc.invalidateQueries({ queryKey: ['settings'] })
      qc.invalidateQueries({ queryKey: ['sources'] })
    },
    onError: (e) => toast.error('Could not open the sign-in window', errorMessage(e)),
  })
  const forget = useMutation({
    mutationFn: (site: string) => forgetBrowserLogin(site),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['settings'] }); qc.invalidateQueries({ queryKey: ['sources'] }) },
    onError: (e) => toast.error('Update failed', errorMessage(e)),
  })
  const groups = (['ats', 'board', 'browser'] as const).map((k) => ({ kind: k, items: sources.filter((s) => s.kind === k) }))
  return (
    <div className="flex flex-col gap-4">
      {groups.map((g) => (
        <Card key={g.kind} title={KIND_META[g.kind].title} subtitle={KIND_META[g.kind].blurb} padded={false}>
          <ul className="divide-y divide-line">
            {g.items.map((s) => (
              <li key={s.name} className="flex items-center gap-4 px-4 py-3">
                <Switch checked={s.enabled} onChange={(on) => toggle.mutate({ name: s.name, on })} ariaLabel={`Use ${s.label}`} />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="text-sm font-medium">{s.label}</span>
                    {s.needs_browser && <Chip tone="neutral"><Globe size={11} /> browser</Chip>}
                    {s.uses_ai && <Chip tone="violet"><Bot size={11} /> uses AI</Chip>}
                    {s.fragile && <Chip tone="warn"><Shield size={11} /> best effort</Chip>}
                    {s.signed_in
                      ? <Chip tone="good" title="JobPilot's browser is signed in to this site, so it is read slowly: pauses between pages, few job pages per run, about once a day, and a rest if the site refuses a visit."><CheckCircle2 size={11} /> Signed in · careful pace</Chip>
                      : s.login_url && <Chip tone="aqua"><LogIn size={11} /> login available</Chip>}
                    {s.enabled && <HealthChip health={s.health} note={s.health_note} />}
                  </div>
                  <div className="mt-0.5 text-xs text-ink-2">{s.description}</div>
                  {s.enabled && s.health_note && s.health !== 'ok' && <div className={`mt-1 text-xs ${s.health === 'idle' || s.health === 'never' ? 'text-muted' : 'text-warn-ink'}`}>{s.health_note}</div>}
                  <div className="mt-1 flex items-center gap-2 text-[11px] text-muted">
                    <span className="num">{s.job_count} jobs</span>
                    {s.last_run && <><span>·</span><RunStatusChip status={s.last_run.status} /><span>{fmtRelative(s.last_run.started_at)}</span>
                      {s.last_run.error && <span className="truncate text-bad-ink" title={s.last_run.error}>{s.last_run.error}</span>}</>}
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  {s.signed_in
                    ? <Button size="sm" variant="ghost" icon={LogOut} onClick={() => forget.mutate(s.name)} loading={forget.isPending && forget.variables === s.name}
                        title="Signs JobPilot's browser out of this site (deletes its saved login there). Your own browsers are untouched.">Sign out</Button>
                    : (s.login_url || s.needs_browser) && <Button size="sm" variant="ghost" icon={LogIn} onClick={() => login.mutate(s.name)} loading={login.isPending && login.variables === s.name} title="Opens a browser window on this site so you can sign in once">Sign in</Button>}
                  <Button size="sm" variant="outline" icon={Play} onClick={() => run.mutate(s.name)} loading={run.isPending && run.variables === s.name}>Run now</Button>
                </div>
              </li>
            ))}
          </ul>
        </Card>
      ))}
    </div>
  )
}
