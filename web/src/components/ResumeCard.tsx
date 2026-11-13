import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FileText, Sparkles, Upload } from 'lucide-react'
import { clsx } from 'clsx'
import { analyzeResume, getResume, replaceResumeFile } from '../api'
import { useToast } from '../lib/toast'
import { errorMessage } from '../lib/tasks'
import { fmtDateTime } from '../lib/format'
import { Button, Chip, Spinner } from './ui'

/** Upload a resume's file and let the AI read it (one call). Shows what it found. resumeId 1 is the default resume. */
export default function ResumeCard({ compact = false, resumeId = 1 }: { compact?: boolean; resumeId?: number }) {
  const qc = useQueryClient()
  const toast = useToast()
  const profile = useQuery({ queryKey: ['resume', resumeId], queryFn: () => getResume(resumeId) })
  const [drag, setDrag] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const refresh = () => { for (const k of ['resume', 'resumes', 'profile', 'today']) qc.invalidateQueries({ queryKey: [k] }) }
  const analyze = useMutation({
    mutationFn: () => analyzeResume(resumeId),
    onSuccess: () => { toast.success('Resume analyzed', 'Use the suggestions to build a search profile.'); refresh() },
    onError: (e) => toast.error('Analysis failed', errorMessage(e)),
  })
  const upload = useMutation({
    mutationFn: (f: File) => replaceResumeFile(resumeId, f),
    onSuccess: (p) => {
      toast.success('Resume imported', `${(p.resume_text ?? '').length.toLocaleString()} characters read. Analyzing it now.`)
      refresh(); qc.invalidateQueries({ queryKey: ['stale-resume'] }); analyze.mutate()
    },
    onError: (e) => toast.error('Upload failed', errorMessage(e)),
  })
  const onFiles = (files: FileList | null) => { const f = files?.[0]; if (f) upload.mutate(f) }
  if (profile.isLoading) return <div className="flex justify-center py-8"><Spinner /></div>
  const p = profile.data
  const ex = (p?.extra ?? {}) as Record<string, unknown>
  const roles = (ex.suggested_roles as string[] | undefined) ?? []

  return (
    <div className="flex flex-col gap-4">
      <div className={clsx('flex flex-col items-center justify-center gap-2 rounded-[14px] border-2 border-dashed text-center transition-colors', compact ? 'p-5' : 'p-7',
        drag ? 'border-[var(--accent)] bg-[color-mix(in_oklab,var(--accent)_6%,transparent)]' : 'border-[var(--baseline)]')}
        onDragOver={(e) => { e.preventDefault(); setDrag(true) }} onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); onFiles(e.dataTransfer.files) }}>
        <Upload size={26} className="text-accent-ink" />
        <div className="text-[15px] font-semibold">{p?.resume_filename ? <>Current file: {p.resume_filename}</> : 'Drop your resume here, or choose a file'}</div>
        <div className="text-[13px] text-ink-2">PDF, Word, TXT or Markdown{p?.resume_filename && p.updated_at ? ` · updated ${fmtDateTime(p.updated_at)}` : ''}</div>
        <input ref={fileRef} type="file" accept=".pdf,.docx,.txt,.md" className="hidden" onChange={(e) => onFiles(e.target.files)} />
        <Button size="sm" variant="outline" icon={FileText} onClick={() => fileRef.current?.click()} loading={upload.isPending}>{p?.resume_filename ? 'Replace file' : 'Choose file'}</Button>
      </div>

      <div className="rounded-xl p-4" style={{ background: 'color-mix(in oklab, var(--accent) 7%, transparent)' }}>
        <div className="mb-2.5 flex items-center justify-between gap-2">
          <div className="text-sm font-bold">What the AI read from it</div>
          <Button size="sm" variant="ghost" icon={Sparkles} onClick={() => analyze.mutate()} loading={analyze.isPending} disabled={!(p?.resume_text ?? '').trim()}>
            {p?.headline ? 'Analyze again' : 'Analyze'} · 1 AI call</Button>
        </div>
        {p?.headline || roles.length ? (
          <dl className="grid grid-cols-[130px_1fr] gap-x-3 gap-y-2 text-sm">
            <dt className="text-ink-2">Headline</dt><dd>{p?.headline ?? '—'}</dd>
            <dt className="text-ink-2">Experience</dt><dd>{p?.years_experience != null ? `${p.years_experience} years` : '—'}{ex.seniority ? ` · ${String(ex.seniority)}` : ''}</dd>
            <dt className="text-ink-2">Key skills</dt><dd className="flex flex-wrap gap-1">{(p?.skills ?? []).slice(0, 12).map((s) => <Chip key={s}>{s}</Chip>)}</dd>
            <dt className="text-ink-2">Suggested roles</dt><dd className="flex flex-wrap gap-1">{roles.map((r) => <Chip key={r} tone="accent">{r}</Chip>)}</dd>
          </dl>
        ) : (
          <p className="text-[13px] text-ink-2">{(p?.resume_text ?? '').trim() ? 'Press Analyze to extract your headline, skills and suggested roles.' : 'Upload a resume first. It is analyzed automatically.'}</p>
        )}
      </div>
    </div>
  )
}
