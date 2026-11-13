import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Building2, Plus, RefreshCw } from 'lucide-react'
import { ApiError, crawlCompany, createCompany, detectAts, listCompanies, patchCompany } from '../api'
import { useToast } from '../lib/toast'
import { errorMessage } from '../lib/tasks'
import { fmtRelative, hostOf } from '../lib/format'
import { Button, Card, Chip, EmptyState, Field, Pagination, Spinner, Switch } from '../components/ui'

const ATS = ['greenhouse', 'lever', 'ashby', 'workable', 'smartrecruiters', 'custom', 'unknown']

export default function Companies() {
  const qc = useQueryClient()
  const toast = useToast()
  const [q, setQ] = useState('')
  const [ats, setAts] = useState('')
  const [origin, setOrigin] = useState('')
  const [page, setPage] = useState(1)
  const [showAdd, setShowAdd] = useState(false)
  const list = useQuery({ queryKey: ['companies', q, ats, origin, page], queryFn: () => listCompanies({ q: q || undefined, ats: ats || undefined, origin: origin || undefined, page, page_size: 50 }), placeholderData: (p) => p })
  const refresh = () => qc.invalidateQueries({ queryKey: ['companies'] })
  const toggle = useMutation({ mutationFn: ({ id, on }: { id: number; on: boolean }) => patchCompany(id, { is_active: on }), onSuccess: refresh, onError: (e) => toast.error('Update failed', errorMessage(e)) })
  const crawl = useMutation({
    mutationFn: (id: number) => crawlCompany(id),
    onSuccess: () => { toast.success('Crawl started'); qc.invalidateQueries({ queryKey: ['tasks'] }) },
    onError: (e) => (e instanceof ApiError && e.status === 409 ? toast.info('A crawl is already running') : toast.error('Could not start crawl', errorMessage(e))),
  })

  return (
    <div className="mx-auto w-full min-w-0 max-w-[1400px]">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <input className="input !w-[260px] max-w-full" aria-label="Search companies" placeholder="Search name, domain, slug" value={q} onChange={(e) => { setQ(e.target.value); setPage(1) }} />
        <select className="input !w-auto" aria-label="ATS" value={ats} onChange={(e) => { setAts(e.target.value); setPage(1) }}>
          <option value="">All ATS</option>{ATS.map((a) => <option key={a} value={a}>{a}</option>)}
        </select>
        <select className="input !w-auto" aria-label="Origin" value={origin} onChange={(e) => { setOrigin(e.target.value); setPage(1) }}>
          <option value="">Any origin</option><option value="seed">Seed list</option><option value="discovered">Discovered</option><option value="user">Added by you</option><option value="job">From job listings</option>
        </select>
        <span className="num text-xs text-muted">{list.data ? `${list.data.total} companies` : ''}</span>
        <Button className="ml-auto" variant="primary" icon={Plus} onClick={() => setShowAdd((s) => !s)}>Add company</Button>
      </div>

      {showAdd && <AddCompany onDone={() => { setShowAdd(false); refresh() }} />}

      <div className="card overflow-hidden">
        {list.isLoading ? <div className="flex justify-center py-16"><Spinner size={22} /></div>
          : !list.data?.items.length ? <EmptyState icon={Building2} title="No companies" hint={<>Add one, or run Discover companies on <Link to="/insights">Insights</Link>.</>} />
            : (
              <div className="scroll-thin overflow-x-auto">
                <table className="tbl">
                  <thead><tr><th>Company</th><th>ATS</th><th>Origin</th><th className="text-right">Jobs</th><th>Last crawled</th><th>Status</th><th>Active</th><th></th></tr></thead>
                  <tbody>
                    {list.data.items.map((c) => (
                      <tr key={c.id} className={c.is_active ? '' : 'opacity-60'}>
                        <td>
                          <div className="font-medium">{c.name}</div>
                          <div className="text-xs text-ink-2">
                            {c.website ? <a href={c.website} target="_blank" rel="noreferrer">{hostOf(c.website)}</a> : c.careers_url ? <a href={c.careers_url} target="_blank" rel="noreferrer">{hostOf(c.careers_url)}</a> : <span className="text-muted">no website</span>}
                          </div>
                        </td>
                        <td><Chip tone={c.ats_type === 'custom' || c.ats_type === 'unknown' ? 'neutral' : 'accent'}>{c.ats_type}{c.ats_slug ? ` · ${c.ats_slug}` : ''}</Chip></td>
                        <td className="text-xs text-ink-2">{c.origin}</td>
                        <td className="num text-right">{c.job_count}</td>
                        <td className="text-xs text-ink-2">{c.last_crawled_at ? fmtRelative(c.last_crawled_at) : <span className="text-muted">never</span>}</td>
                        <td className="max-w-[260px] truncate text-xs" title={c.last_error ?? ''}>{c.last_error ? <span className="text-bad-ink">{c.last_error}</span> : c.last_crawled_at ? <span className="text-good-ink">ok</span> : <span className="text-muted">—</span>}</td>
                        <td><Switch checked={c.is_active} onChange={(on) => toggle.mutate({ id: c.id, on })} ariaLabel={`Track ${c.name}`} /></td>
                        <td>
                          {(c.ats_type !== 'unknown' || c.careers_url) && c.is_active && (
                            <Button size="sm" variant="ghost" icon={RefreshCw} onClick={() => crawl.mutate(c.id)} loading={crawl.isPending && crawl.variables === c.id}>Crawl</Button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
        {list.data && list.data.total > 50 && <div className="border-t border-line px-4 py-2"><Pagination page={page} pageSize={50} total={list.data.total} onChange={setPage} /></div>}
      </div>
    </div>
  )
}

function AddCompany({ onDone }: { onDone: () => void }) {
  const toast = useToast()
  const [form, setForm] = useState({ name: '', website: '', careers_url: '', ats_type: 'custom', ats_slug: '', notes: '' })
  const [detected, setDetected] = useState<string | null>(null)
  const detect = async (url: string) => {
    if (!url) return
    try {
      const d = await detectAts(url)
      if (d.ats_type && d.ats_slug) {
        setForm((f) => ({ ...f, ats_type: d.ats_type!, ats_slug: d.ats_slug! }))
        setDetected(`${d.ats_type} board "${d.ats_slug}" detected: the fast API crawler will be used.`)
      } else {
        setDetected('No known ATS in that URL. The careers page will be read in the browser and parsed by the AI.')
      }
    } catch { /* detection is best effort */ }
  }
  const create = useMutation({
    mutationFn: () => createCompany({ name: form.name, website: form.website || undefined, careers_url: form.careers_url || undefined, ats_type: form.ats_type, ats_slug: form.ats_slug || undefined, notes: form.notes || undefined }),
    onSuccess: () => { toast.success('Company added'); onDone() },
    onError: (e) => toast.error('Could not add', errorMessage(e)),
  })
  const needsCareers = (form.ats_type === 'custom' || form.ats_type === 'unknown') && !form.careers_url
  return (
    <Card title="Add a company" subtitle="Paste its careers or job-board URL; the ATS is detected automatically." className="mb-4">
      <div className="grid gap-3 md:grid-cols-3">
        <Field label="Name"><input className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Acme Corp" /></Field>
        <Field label="Website"><input className="input" value={form.website} onChange={(e) => setForm({ ...form, website: e.target.value })} onBlur={(e) => detect(e.target.value)} placeholder="https://acme.com" /></Field>
        <Field label="Careers / job board URL" hint={detected ?? 'e.g. https://boards.greenhouse.io/acme or https://acme.com/careers'}>
          <input className="input" value={form.careers_url} onChange={(e) => setForm({ ...form, careers_url: e.target.value })} onBlur={(e) => detect(e.target.value)} placeholder="https://jobs.lever.co/acme" />
        </Field>
        <Field label="ATS"><select className="input" value={form.ats_type} onChange={(e) => setForm({ ...form, ats_type: e.target.value })}>{ATS.filter((a) => a !== 'unknown').map((a) => <option key={a} value={a}>{a}</option>)}</select></Field>
        <Field label="Board slug" hint="Required for a known ATS"><input className="input" value={form.ats_slug} onChange={(e) => setForm({ ...form, ats_slug: e.target.value })} placeholder="acme" /></Field>
        <Field label="Notes"><input className="input" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} /></Field>
      </div>
      <div className="mt-3 flex justify-end gap-2">
        <Button variant="ghost" onClick={onDone}>Cancel</Button>
        <Button variant="primary" onClick={() => create.mutate()} loading={create.isPending} disabled={!form.name.trim() || needsCareers || (form.ats_type !== 'custom' && !form.ats_slug)}>Add company</Button>
      </div>
    </Card>
  )
}
