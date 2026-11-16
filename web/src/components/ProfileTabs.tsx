import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Wand2 } from 'lucide-react'
import { clsx } from 'clsx'
import { createProfile, listProfiles, listResumes, profileFromResume } from '../api'
import type { SearchProfileRow } from '../types'
import { useToast } from '../lib/toast'
import { errorMessage } from '../lib/tasks'
import { Button, Chip, Dialog, Spinner } from './ui'
import { canRun } from './RunDialog'
import ProfileEditor from './ProfileEditor'

/** All search profiles as tabs, with the selected one open for editing. */
export default function ProfileTabs() {
  const qc = useQueryClient()
  const toast = useToast()
  const profiles = useQuery({ queryKey: ['profiles'], queryFn: listProfiles })
  // With several resumes, each resume has its own "New search profile from it" button.
  const resumes = useQuery({ queryKey: ['resumes'], queryFn: listResumes, staleTime: 60_000 })
  const oneResume = (resumes.data ?? []).length <= 1
  const [sel, setSel] = useState<number | null>(null)
  const [dirty, setDirty] = useState(false)
  const [pending, setPending] = useState<(() => void) | null>(null)
  // Anything that opens another profile asks first when the open one has unsaved edits.
  const guard = (fn: () => void) => (dirty ? setPending(() => fn) : fn())
  const list = profiles.data ?? []
  useEffect(() => { if (list.length && !list.some((p) => p.id === sel)) setSel(list[0].id) }, [list, sel])

  const add = useMutation({
    mutationFn: () => {
      const base = list.find((p) => p.id === sel)?.search ?? list[0].search
      return createProfile({ name: 'New profile', enabled: true, search: { ...base, roles: [], title_keywords: [] } })
    },
    onSuccess: (r) => { qc.invalidateQueries({ queryKey: ['profiles'] }); setSel(r.id); toast.success('Profile added', 'Give it a name, titles and keywords, then save.') },
    onError: (e) => toast.error('Could not add', errorMessage(e)),
  })
  const fromResume = useMutation({
    mutationFn: () => profileFromResume(1),
    onSuccess: (r) => { qc.invalidateQueries({ queryKey: ['profiles'] }); qc.invalidateQueries({ queryKey: ['jobs'] }); setSel(r.id); toast.success('Profile created from your resume', 'Check the titles and places, then save.') },
    onError: (e) => toast.error('Could not create it', errorMessage(e)),
  })

  // Active profiles first; then each card shows what it searches, with which resume, and whether another card does the same.
  const rank = (p: SearchProfileRow) => (p.enabled && canRun(p) ? 0 : p.enabled ? 1 : 2)     // running, then empty, then off
  const ordered = [...list].sort((a, b) => rank(a) - rank(b))
  const active = list.filter((p) => p.enabled && canRun(p))
  const resumeName = (p: SearchProfileRow) => {
    const r = (resumes.data ?? []).find((x) => x.id === (p.resume_id ?? 1))
    return r ? `Resume: ${r.name}` : 'Resume: default'
  }
  const key = (p: SearchProfileRow) => JSON.stringify([p.resume_id ?? 1, [...p.search.roles].map((x) => x.trim().toLowerCase()).sort()])
  // The first card (in the order shown) with the same titles and resume is the one to keep; later ones say so.
  const twinOf = (p: SearchProfileRow) => (p.search.roles.length ? ordered.slice(0, ordered.indexOf(p)).find((o) => key(o) === key(p)) : undefined)

  if (profiles.isLoading) return <div className="flex justify-center py-8"><Spinner /></div>
  const current = list.find((p) => p.id === sel)
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[13px] text-ink-2">{active.length} active of {list.length}. Pick one to edit it below.</p>
        <div className="flex gap-2">
          {oneResume && <Button size="sm" variant="outline" icon={Wand2} onClick={() => guard(() => fromResume.mutate())} loading={fromResume.isPending}>From my resume</Button>}
          <Button size="sm" variant="outline" icon={Plus} onClick={() => guard(() => add.mutate())} loading={add.isPending}>Add profile</Button>
        </div>
      </div>
      <div role="tablist" aria-label="Profiles" className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
        {ordered.map((p) => {
          const runs = canRun(p)
          const twin = twinOf(p)
          const titles = p.search.roles.length ? p.search.roles : p.search.title_keywords
          return (
            <button key={p.id} type="button" role="tab" aria-selected={p.id === sel} onClick={() => p.id !== sel && guard(() => setSel(p.id))}
              className={clsx('flex min-w-0 flex-col gap-1.5 rounded-xl border p-3.5 text-left transition-colors',
                p.id === sel ? 'border-[var(--accent)] bg-[color-mix(in_oklab,var(--accent)_7%,transparent)] ring-1 ring-[var(--accent)]'
                  : 'border-[var(--baseline)] bg-surface hover:bg-surface-2', !p.enabled && p.id !== sel && 'opacity-70')}>
              <span className="flex items-center gap-2">
                <span className="min-w-0 flex-1 truncate text-sm font-semibold" title={p.name}>{p.name}</span>
                {!p.enabled ? <Chip tone="muted">Off</Chip> : runs ? <Chip tone="good" dot>Active</Chip> : <Chip tone="warn">No job titles yet</Chip>}
              </span>
              <span className="truncate text-xs text-ink-2" title={titles.join(', ')}>
                {titles.length ? titles.slice(0, 3).join(' · ') + (titles.length > 3 ? ` +${titles.length - 3}` : '') : 'Add job titles to start searching'}
              </span>
              <span className="flex items-center gap-2 text-[11px] text-muted">
                <span className="truncate" title="The resume this profile scores jobs against and uploads">{resumeName(p)}</span>
                <span className="ml-auto shrink-0 num">{p.matching} job{p.matching === 1 ? '' : 's'}</span>
              </span>
              {twin && <span className="text-[11px] font-medium text-warn-ink">Same search as &ldquo;{twin.name}&rdquo;. You can delete one.</span>}
            </button>
          )
        })}
      </div>
      {current && <ProfileEditor row={current} onDeleted={() => setSel(null)} onDirtyChange={setDirty} canDelete={list.length > 1} />}
      <Dialog open={!!pending} onClose={() => setPending(null)} title="Discard unsaved changes?"
        footer={<><Button variant="ghost" onClick={() => setPending(null)}>Keep editing</Button>
          <Button variant="danger" onClick={() => { const fn = pending; setPending(null); fn?.() }}>Discard</Button></>}>
        <p>{current ? <>The profile <strong>{current.name}</strong> has</> : 'This profile has'} changes that are not saved yet. Discard them, or keep editing and press Save profile.</p>
      </Dialog>
    </div>
  )
}
