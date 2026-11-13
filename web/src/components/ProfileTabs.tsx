import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Wand2 } from 'lucide-react'
import { clsx } from 'clsx'
import { createProfile, listProfiles, listResumes, profileFromResume } from '../api'
import { useToast } from '../lib/toast'
import { errorMessage } from '../lib/tasks'
import { Button, Dialog, Spinner } from './ui'
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

  if (profiles.isLoading) return <div className="flex justify-center py-8"><Spinner /></div>
  const current = list.find((p) => p.id === sel)
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <div role="tablist" aria-label="Profiles" className="flex flex-wrap gap-2">
          {list.map((p) => (
            <button key={p.id} type="button" role="tab" aria-selected={p.id === sel} onClick={() => p.id !== sel && guard(() => setSel(p.id))}
              className={clsx('h-9 rounded-full border px-3.5 text-[13px] font-semibold transition-colors',
                p.id === sel ? 'border-[var(--ink)] bg-ink text-[var(--bg)]' : 'border-[var(--baseline)] bg-surface hover:bg-surface-2',
                !p.enabled && p.id !== sel && 'opacity-60')}>{p.name}</button>
          ))}
        </div>
        <div className="ml-auto flex gap-2">
          {oneResume && <Button size="sm" variant="outline" icon={Wand2} onClick={() => guard(() => fromResume.mutate())} loading={fromResume.isPending}>From my resume</Button>}
          <Button size="sm" variant="outline" icon={Plus} onClick={() => guard(() => add.mutate())} loading={add.isPending}>Add profile</Button>
        </div>
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
