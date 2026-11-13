import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2, Wand2 } from 'lucide-react'
import { clsx } from 'clsx'
import { addResume, analyzeResume, deleteResume, listResumes, profileFromResume, putResume } from '../api'
import { useToast } from '../lib/toast'
import { errorMessage } from '../lib/tasks'
import { Button, Chip, Dialog, Spinner } from './ui'
import ResumeCard from './ResumeCard'
import ResumeDetails from './ResumeDetails'

/** Every resume as a tab (the first is the default), with the selected one open. `?resume=` keeps the choice. */
export default function ResumeTabs() {
  const qc = useQueryClient()
  const toast = useToast()
  const [params, setParams] = useSearchParams()
  const resumes = useQuery({ queryKey: ['resumes'], queryFn: listResumes })
  const list = resumes.data ?? []
  const current = list.find((r) => r.id === Number(params.get('resume'))) ?? list[0]
  const [name, setName] = useState('')
  const [dirty, setDirty] = useState(false)
  const [pending, setPending] = useState<(() => void) | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [gen, setGen] = useState(0)          // bumped when the default slot gets another resume: its panels start afresh
  const fileRef = useRef<HTMLInputElement>(null)
  useEffect(() => { if (current) setName(current.name) }, [current?.id, current?.name]) // eslint-disable-line react-hooks/exhaustive-deps

  const refresh = () => {
    for (const k of ['resumes', 'resume', 'profile', 'profiles', 'today', 'stale-resume']) qc.invalidateQueries({ queryKey: [k] })
  }
  const show = (id: number) => setParams((p) => {
    const n = new URLSearchParams(p)
    if (id === list[0]?.id) n.delete('resume'); else n.set('resume', String(id))
    return n
  }, { replace: true })
  // Unsaved edits in the details below are lost when another resume opens: ask first, as the profile tabs do.
  const guard = (fn: () => void) => (dirty ? setPending(() => fn) : fn())

  const analyze = useMutation({
    mutationFn: (id: number) => analyzeResume(id),
    onSuccess: () => { toast.success('Resume analyzed', 'Use it in a search profile, or make a new profile from it.'); refresh() },
    onError: (e) => toast.error('Analysis failed', errorMessage(e)),
  })
  const add = useMutation({
    mutationFn: (f: File) => addResume(f),
    onSuccess: (p) => { toast.success('Resume added', 'Analyzing it now (1 AI call).'); refresh(); show(p.id); analyze.mutate(p.id) },
    onError: (e) => toast.error('Upload failed', errorMessage(e)),
  })
  const rename = useMutation({
    mutationFn: () => putResume(current!.id, { name: name.trim() }),
    onSuccess: () => { toast.success('Renamed'); refresh() },
    onError: (e) => toast.error('Rename failed', errorMessage(e)),
  })
  const del = useMutation({
    mutationFn: (id: number) => deleteResume(id),
    onSuccess: (r, id) => {
      toast.info('Resume deleted', id !== 1 ? 'Profiles that used it now use the default resume.'
        : r.default ? `“${r.default}” is your default resume now.` : 'No resume left. Add one when you are ready.')
      if (id === 1) setGen((g) => g + 1)
      // Refresh everything except the row that went: asking for it again would only fail.
      qc.invalidateQueries({ queryKey: ['resume'], predicate: (q) => q.queryKey[1] !== r.removed })
      for (const k of ['resumes', 'profile', 'profiles', 'today', 'stale-resume', 'applications', 'application']) qc.invalidateQueries({ queryKey: [k] })
    },
    onError: (e) => toast.error('Delete failed', errorMessage(e)),
  })
  // Open the default resume first, so the one being deleted is no longer on screen when it goes.
  const remove = () => { const id = current!.id; setConfirmDelete(false); show(list[0].id); del.mutate(id) }
  // Deleting the default moves the next resume (one with a file first) into its place, as the server does.
  const heir = [...list.filter((r) => !r.is_default && r.has_text), ...list.filter((r) => !r.is_default && !r.has_text)][0]
  const makeProfile = useMutation({
    mutationFn: () => profileFromResume(current!.id),
    onSuccess: (r) => { toast.success('Search profile created', `"${r.name}" uses this resume. Check its titles and places below, then save.`); refresh(); qc.invalidateQueries({ queryKey: ['jobs'] }) },
    onError: (e) => toast.error('Could not create it', errorMessage(e)),
  })

  if (resumes.isLoading) return <div className="flex justify-center py-8"><Spinner /></div>
  if (!current) return null
  const analyzed = !!current.headline
  const used = current.used_by.map((u) => `“${u.name}”`).join(', ')      // names may hold commas themselves
  const deletable = !current.is_default || current.has_text || !!current.resume_filename
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <div role="tablist" aria-label="Resumes" className="flex flex-wrap gap-2">
          {list.map((r) => (
            <button key={r.id} type="button" role="tab" aria-selected={r.id === current.id} onClick={() => r.id !== current.id && guard(() => show(r.id))}
              className={clsx('h-9 rounded-full border px-3.5 text-[13px] font-semibold transition-colors',
                r.id === current.id ? 'border-[var(--ink)] bg-ink text-[var(--bg)]' : 'border-[var(--baseline)] bg-surface hover:bg-surface-2')}>
              {r.name}{r.is_default && <span className="font-normal opacity-70"> · default</span>}
            </button>
          ))}
        </div>
        <div className="ml-auto">
          <input ref={fileRef} type="file" accept=".pdf,.docx,.txt,.md" className="hidden" aria-label="Add a resume file"
            onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ''; if (f) guard(() => add.mutate(f)) }} />
          <Button size="sm" variant="outline" icon={Plus} onClick={() => fileRef.current?.click()} loading={add.isPending}>Add resume</Button>
        </div>
      </div>

      <div className="flex flex-wrap items-end gap-3 rounded-xl border border-line p-4">
        <label className="flex min-w-[220px] flex-1 flex-col gap-1.5">
          <span className="text-xs font-medium text-ink-2">Name</span>
          <input className="input" value={name} maxLength={120} onChange={(e) => setName(e.target.value)}
            onBlur={() => name.trim() && name.trim() !== current.name && rename.mutate()}
            onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }} />
        </label>
        <div className="flex min-w-[220px] flex-[2] flex-col gap-1.5 text-[13px]">
          <span className="text-xs font-medium text-ink-2">Used by</span>
          <span className="flex flex-wrap items-center gap-1.5">
            {current.used_by.length ? current.used_by.map((u) => <Chip key={u.id} tone="accent">{u.name}</Chip>)
              : <span className="text-ink-2">{current.is_default ? 'Profiles that don’t pick a resume. None right now.' : 'No profile yet. Pick it in a search profile below.'}</span>}
          </span>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="outline" icon={Wand2} onClick={() => makeProfile.mutate()} loading={makeProfile.isPending}
            disabled={!analyzed} title={analyzed ? 'Titles, keywords and skills come from this resume’s analysis. No AI call.' : 'Analyze this resume first'}>New search profile from it</Button>
          {deletable && <Button size="sm" variant="ghost" icon={Trash2} onClick={() => setConfirmDelete(true)} loading={del.isPending}>Delete resume</Button>}
        </div>
      </div>

      <ResumeCard key={`card-${current.id}-${gen}`} resumeId={current.id} />
      <ResumeDetails key={`details-${current.id}-${gen}`} resumeId={current.id} onDirtyChange={setDirty} />

      <Dialog open={!!pending} onClose={() => setPending(null)} title="Discard unsaved changes?"
        footer={<><Button variant="ghost" onClick={() => setPending(null)}>Keep editing</Button>
          <Button variant="danger" onClick={() => { const fn = pending; setPending(null); setDirty(false); fn?.() }}>Discard</Button></>}>
        <p>The details of <strong>{current.name}</strong> have changes that are not saved yet. Discard them, or keep editing and press Save.</p>
      </Dialog>
      <Dialog open={confirmDelete} onClose={() => setConfirmDelete(false)} title={`Delete the resume "${current.name}"?`}
        footer={<><Button variant="ghost" onClick={() => setConfirmDelete(false)}>Cancel</Button>
          <Button variant="danger" icon={Trash2} onClick={remove} loading={del.isPending}>Delete resume</Button></>}>
        {!current.is_default ? (
          <p>{used ? <>{used} will use the default resume, <strong>{list[0].name}</strong>, instead. </> : null}Applications not sent yet switch to the default resume too.</p>
        ) : heir ? (
          <p><strong>{heir.name}</strong> becomes your default resume. {used ? <>{used} will use it, and so will applications not sent yet.</> : 'Applications not sent yet will use it.'}</p>
        ) : (
          <p>It is your only resume, so you will have none. Jobs can&rsquo;t be scored against your resume and applications have no file to upload until you add one.</p>
        )}
        <p className="mt-2 text-xs text-ink-2">Sent applications keep the file they were sent with. {used && (!current.is_default || heir) ? 'Scores and cover letters made with this resume can be redone with the new one from the Refresh banner above.' : ''}</p>
      </Dialog>
    </div>
  )
}
