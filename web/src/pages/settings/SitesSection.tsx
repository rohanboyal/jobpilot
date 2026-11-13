import { useEffect, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2 } from 'lucide-react'
import { putSites } from '../../api'
import type { Site } from '../../types'
import { useToast } from '../../lib/toast'
import { errorMessage } from '../../lib/tasks'
import { Button, Card, Field, Switch } from '../../components/ui'

const EMPTY: Site = { key: '', label: '', search_url: '', login_url: '', needs_login: false, enabled: true, countries: [], pages: 1, notes: '' }

export default function SitesSection({ initial }: { initial: Site[] }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [sites, setSites] = useState<Site[]>(initial)
  const [editing, setEditing] = useState<number | null>(null)
  useEffect(() => setSites(initial), [initial])
  const save = useMutation({
    mutationFn: () => putSites(sites.map((s) => ({ ...s, countries: (s.countries ?? []).filter(Boolean), pages: Number(s.pages) || 1 }))),
    onSuccess: () => { toast.success('Sites saved', 'New sites appear under Sources as site_<key>.'); setEditing(null); qc.invalidateQueries({ queryKey: ['settings'] }); qc.invalidateQueries({ queryKey: ['sources'] }) },
    onError: (e) => toast.error('Save failed', errorMessage(e)),
  })
  const dirty = JSON.stringify(sites) !== JSON.stringify(initial)
  const upd = (i: number, patch: Partial<Site>) => setSites((xs) => xs.map((s, si) => (si === i ? { ...s, ...patch } : s)))
  const valid = sites.every((s) => /^[a-z0-9_]+$/.test(s.key) && s.label.trim() && /^https?:\/\//.test(s.search_url)) && new Set(sites.map((s) => s.key)).size === sites.length

  return (
    <div className="flex flex-col gap-4">
      <Card title="Job sites crawled in the browser" padded={false}
        subtitle={<>Any site with a search page can be added. Placeholders: <code className="mono">{'{role}'}</code> <code className="mono">{'{role_slug}'}</code> <code className="mono">{'{role_plus}'}</code> <code className="mono">{'{location}'}</code> <code className="mono">{'{location_slug}'}</code> <code className="mono">{'{location_plus}'}</code> <code className="mono">{'{days}'}</code>. Without CSS selectors the AI reads listings from the page (one call per page); with selectors it is free.</>}
        actions={<><Button size="sm" icon={Plus} onClick={() => { setSites((xs) => [...xs, { ...EMPTY }]); setEditing(sites.length) }}>Add site</Button><Button size="sm" variant="primary" onClick={() => save.mutate()} loading={save.isPending} disabled={!dirty || !valid}>Save all</Button></>}>
        <div className="scroll-thin overflow-x-auto">
          <table className="tbl">
            <thead><tr><th>Enabled</th><th>Key</th><th>Label</th><th>Search URL</th><th>Login</th><th>Countries</th><th>Pages</th><th></th></tr></thead>
            <tbody>
              {sites.map((s, i) => (
                <tr key={i} className={editing === i ? 'row-active' : ''}>
                  <td><Switch checked={!!s.enabled} onChange={(v) => upd(i, { enabled: v })} ariaLabel={`Use ${s.label || s.key || 'this site'}`} /></td>
                  <td className="min-w-[130px]"><input className="input mono !py-1" aria-label="Key" value={s.key} onChange={(e) => upd(i, { key: e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, '_') })} placeholder="cutshort" /></td>
                  <td className="min-w-[150px]"><input className="input !py-1" aria-label="Label" value={s.label} onChange={(e) => upd(i, { label: e.target.value })} /></td>
                  <td className="min-w-[320px]"><input className="input mono !py-1" aria-label="Search URL" value={s.search_url} onChange={(e) => upd(i, { search_url: e.target.value })} placeholder="https://site.com/jobs?q={role_plus}&l={location_plus}" /></td>
                  <td>
                    <div className="flex items-center gap-2">
                      <Switch checked={!!s.needs_login} onChange={(v) => upd(i, { needs_login: v })} ariaLabel={`${s.label || s.key || 'This site'} needs sign-in`} />
                      <input className="input mono !w-[160px] !py-1" aria-label="Sign-in URL" value={s.login_url ?? ''} onChange={(e) => upd(i, { login_url: e.target.value })} placeholder="login url" />
                    </div>
                  </td>
                  <td><input className="input !w-[90px] !py-1" aria-label="Countries" value={(s.countries ?? []).join(',')} onChange={(e) => upd(i, { countries: e.target.value.split(',').map((x) => x.trim().toLowerCase()) })} placeholder="in,us" /></td>
                  <td><input className="input !w-[60px] !py-1" aria-label="Pages" type="number" min={1} max={5} value={s.pages ?? 1} onChange={(e) => upd(i, { pages: Number(e.target.value) })} /></td>
                  <td><button className="text-muted hover:text-bad-ink" onClick={() => setSites((xs) => xs.filter((_, si) => si !== i))} aria-label={`Remove ${s.label || s.key || 'site'}`}><Trash2 size={14} /></button></td>
                </tr>
              ))}
              {!sites.length && <tr><td colSpan={8} className="py-8 text-center text-xs text-muted">No sites configured.</td></tr>}
            </tbody>
          </table>
        </div>
        {!valid && sites.length > 0 && <div className="border-t border-line px-4 py-2 text-xs text-warn-ink">Each site needs a unique lowercase key, a label and an http(s) search URL.</div>}
      </Card>
      {editing !== null && sites[editing] && (
        <Card title={`Notes for ${sites[editing].label || sites[editing].key || 'new site'}`}>
          <Field label="Notes"><input className="input" value={sites[editing].notes ?? ''} onChange={(e) => upd(editing, { notes: e.target.value })} /></Field>
        </Card>
      )}
    </div>
  )
}
