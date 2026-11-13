import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Activity as ActivityIcon } from 'lucide-react'
import { getRun, listRuns } from '../api'
import { useTasks } from '../lib/tasks'
import { fmtDateTime, fmtDuration, fmtRelative, statLabel, summarizeStats, titleCase } from '../lib/format'
import { Card, Chip, Drawer, EmptyState, KV, LogView, Spinner, Tabs } from '../components/ui'
import { RunStatusChip } from '../components/status'

export default function Activity() {
  // The run kind and the open run live in the URL, so a run can be linked to and Back closes it.
  const [sp, setSp] = useSearchParams()
  const loc = useLocation()
  const nav = useNavigate()
  const kind = sp.get('kind') ?? ''
  const runId = sp.get('run') ? Number(sp.get('run')) : null
  const setKind = (k: string) => setSp(k ? { kind: k } : {}, { replace: true })
  const openRun = (id: number) => { const n = new URLSearchParams(sp); n.set('run', String(id)); setSp(n, { state: { drawer: true } }) }
  const closeRun = () => {
    if ((loc.state as { drawer?: boolean } | null)?.drawer) nav(-1)
    else { const n = new URLSearchParams(sp); n.delete('run'); setSp(n, { replace: true }) }
  }
  const runs = useQuery({ queryKey: ['runs', kind], queryFn: () => listRuns({ kind: kind || undefined, limit: 200 }), refetchInterval: 15_000 })
  const run = useQuery({ queryKey: ['run', runId], queryFn: () => getRun(runId!), enabled: runId !== null })
  const tasks = useTasks()
  const live = tasks.data?.tasks ?? []

  return (
    <div className="mx-auto max-w-[1200px]">
      <header className="mb-5">
        <h2 className="page-title">Activity log</h2>
        <p className="mt-1.5 text-sm text-ink-2">Every crawl, analysis and application attempt, with its log.</p>
      </header>
      {live.length > 0 && (
        <Card title="Background tasks" subtitle="What the server is doing right now and what it finished recently" className="mb-4" padded={false}>
          <ul className="divide-y divide-line">
            {live.slice(0, 8).map((t) => (
              <li key={t.id} className="px-4 py-3">
                <div className="flex items-center gap-2 text-sm">
                  <RunStatusChip status={t.status} />
                  <span className="font-medium">{sentence(t.label)}</span>
                  <span className="ml-auto text-xs text-muted">{fmtRelative(t.started_at)} · {fmtDuration(t.started_at, t.finished_at)}</span>
                </div>
                {t.error && <div className="mt-1 text-xs text-bad-ink">{t.error}</div>}
                {t.status === 'running' && t.log_tail.length > 0 && <div className="mt-2"><LogView lines={t.log_tail} maxHeight={140} /></div>}
                {t.status !== 'running' && t.result !== null && t.result !== undefined && (
                  <div className="mt-1 text-xs text-ink-2">
                    {summarizeStats(t.result) || 'Nothing to report.'}
                    <details className="mt-1"><summary className="cursor-pointer text-muted">Details</summary><pre className="mono mt-1 whitespace-pre-wrap">{JSON.stringify(t.result, null, 1)}</pre></details>
                  </div>
                )}
              </li>
            ))}
          </ul>
        </Card>
      )}

      <div className="mb-3 flex items-center gap-3">
        <Tabs value={kind} onChange={setKind} items={[{ value: '', label: 'All runs' }, { value: 'crawl', label: 'Crawl' }, { value: 'score', label: 'Score' }, { value: 'prepare', label: 'Prepare' }, { value: 'apply', label: 'Apply' }, { value: 'discover', label: 'Discover' }]} />
      </div>
      <div className="card overflow-hidden">
        {runs.isLoading ? <div className="flex justify-center py-16"><Spinner size={22} /></div>
          : !runs.data?.length ? <EmptyState icon={ActivityIcon} title="No runs yet" hint="Every crawl, scoring batch and application attempt is recorded here." />
            : (
              <div className="scroll-thin overflow-x-auto">
                <table className="tbl">
                  <thead><tr><th>Status</th><th>Kind</th><th>Source</th><th>Started</th><th>Duration</th><th>Summary</th></tr></thead>
                  <tbody>
                    {runs.data.map((r) => (
                      <tr key={r.id} className="row-click" tabIndex={0} aria-label={`Open ${titleCase(r.kind)} run ${r.id}`} onClick={() => openRun(r.id)}
                        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openRun(r.id) } }}>
                        <td><RunStatusChip status={r.status} /></td>
                        <td className="font-medium">{titleCase(r.kind)}</td>
                        <td className="text-xs text-ink-2">{r.source ?? '—'}</td>
                        <td className="num text-xs text-ink-2" title={fmtDateTime(r.started_at)}>{fmtRelative(r.started_at)}</td>
                        <td className="num text-xs text-ink-2">{fmtDuration(r.started_at, r.finished_at)}</td>
                        <td className="max-w-[520px] truncate text-xs text-ink-2" title={r.error ?? summarizeStats(r.stats)}>{r.error ? <span className="text-bad-ink">{r.error}</span> : summarizeStats(r.stats)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
      </div>

      <Drawer open={runId !== null} onClose={closeRun} title={run.data ? `${titleCase(run.data.kind)}${run.data.source ? ` · ${run.data.source}` : ''}` : 'Run'} width={820}>
        {run.data && (
          <div className="flex flex-col gap-4 p-5">
            <KV rows={[['Status', <RunStatusChip status={run.data.status} />], ['Started', fmtDateTime(run.data.started_at)], ['Duration', fmtDuration(run.data.started_at, run.data.finished_at)], ['Error', run.data.error]]} />
            {run.data.stats && (
              <div className="flex flex-wrap gap-1.5">{Object.entries(run.data.stats).map(([k, v]) => <Chip key={k}>{sentence(statLabel(k))}: {typeof v === 'object' ? summarizeStats(v) || JSON.stringify(v) : String(v)}</Chip>)}</div>
            )}
            <LogView text={run.data.log} maxHeight={600} />
          </div>
        )}
      </Drawer>
    </div>
  )
}

/** "collect jobs" -> "Collect jobs" */
const sentence = (s: string) => (s ? s[0].toUpperCase() + s.slice(1) : s)
