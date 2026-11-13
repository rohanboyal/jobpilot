import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { BriefcaseBusiness, ChevronDown, ChevronUp, GraduationCap, Link2, Plus, Rocket, Trash2, UserRound } from 'lucide-react'
import { getContactSuggestions, getResume, getSettings, putAnswerBank, putResume } from '../api'
import type { Profile, ProfileExtra, ResumeContact, ResumeEducation, ResumeExperience, ResumeProject } from '../types'
import { useToast } from '../lib/toast'
import { errorMessage } from '../lib/tasks'
import { Button, Field, ListEditor, Spinner } from './ui'

interface Draft {
  headline: string; years: string; summary: string; skills: string[]; resume_text: string
  experience: ResumeExperience[]; education: ResumeEducation[]; projects: ResumeProject[]
  certifications: string[]; languages: string[]; contact: ResumeContact
}

function toDraft(p: Profile): Draft {
  const ex = (p.extra ?? {}) as ProfileExtra
  return {
    headline: p.headline ?? '', years: p.years_experience?.toString() ?? '', summary: p.summary ?? '', skills: p.skills ?? [],
    resume_text: p.resume_text ?? '', experience: ex.experience ?? [], education: ex.education ?? [], projects: ex.projects ?? [],
    certifications: ex.certifications ?? [], languages: ex.languages ?? [], contact: ex.contact ?? {},
  }
}

/** Everything read from the resume, editable. Saving changes what the AI sees when it scores and writes. */
export default function ResumeDetails({ resumeId = 1, onDirtyChange }: { resumeId?: number; onDirtyChange?: (dirty: boolean) => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const profile = useQuery({ queryKey: ['resume', resumeId], queryFn: () => getResume(resumeId) })
  const initial = useMemo<Draft | null>(() => (profile.data ? toDraft(profile.data) : null), [profile.data])
  const [d, setD] = useState<Draft | null>(initial)
  const [showText, setShowText] = useState(false)
  // Take the server's copy only when nothing here is unsaved: every finished background task refetches all queries,
  // and that must not wipe what the user is typing. Reset still loads the server's copy.
  const synced = useRef<string | null>(null)
  useEffect(() => {
    if (synced.current === null || JSON.stringify(d) === synced.current) setD(initial)
    synced.current = initial && JSON.stringify(initial)
  }, [initial]) // eslint-disable-line react-hooks/exhaustive-deps
  const dirty = JSON.stringify(d) !== JSON.stringify(initial)
  useEffect(() => { onDirtyChange?.(dirty) }, [dirty, onDirtyChange])
  useEffect(() => () => onDirtyChange?.(false), [onDirtyChange])

  const save = useMutation({
    mutationFn: () => putResume(resumeId, {
      headline: d!.headline || null, summary: d!.summary || null, skills: d!.skills, resume_text: d!.resume_text || null,
      years_experience: d!.years ? Number(d!.years) : null,
      extra: { experience: d!.experience.map((x) => ({ ...x, highlights: x.highlights.map((h) => h.trim()).filter(Boolean) })), education: d!.education, projects: d!.projects, certifications: d!.certifications, languages: d!.languages, contact: d!.contact },
    }),
    onSuccess: (p) => {
      toast.success('Resume details saved'); setD(toDraft(p)); qc.setQueryData(['resume', resumeId], p)
      for (const k of ['resume', 'resumes', 'profile']) qc.invalidateQueries({ queryKey: [k] })
    },
    onError: (e) => toast.error('Save failed', errorMessage(e)),
  })
  const fillAnswers = useMutation({
    mutationFn: async () => {
      const [sugg, settings] = await Promise.all([getContactSuggestions(), getSettings()])
      const bank = settings.answer_bank
      let n = 0
      const fill = (section: Record<string, string>) => {
        const out = { ...section }
        for (const [k, v] of Object.entries(sugg)) if (k in out && !(out[k] ?? '').trim()) { out[k] = v; n++ }
        return out
      }
      await putAnswerBank({ ...bank, identity: fill(bank.identity), eligibility: fill(bank.eligibility) })
      return n
    },
    onSuccess: (n) => { toast.success(n ? `${n} form answers filled from your resume` : 'Nothing new to fill', 'Only empty answers were filled. Check them in Settings › Your answers.'); qc.invalidateQueries({ queryKey: ['settings'] }); qc.invalidateQueries({ queryKey: ['today'] }) },
    onError: (e) => toast.error('Could not fill answers', errorMessage(e)),
  })

  if (profile.isLoading || !d) return <div className="flex justify-center py-8"><Spinner /></div>
  const set = (patch: Partial<Draft>) => setD({ ...d, ...patch })
  const setItem = <K extends 'experience' | 'education' | 'projects'>(k: K, i: number, patch: Partial<Draft[K][number]>) =>
    set({ [k]: d[k].map((x, xi) => (xi === i ? { ...x, ...patch } : x)) } as Partial<Draft>)
  const remove = (k: 'experience' | 'education' | 'projects', i: number) => set({ [k]: d[k].filter((_, xi) => xi !== i) } as Partial<Draft>)

  return (
    <div className="flex flex-col gap-4">
      <Block icon={UserRound} title="About you">
        <div className="grid gap-3 md:grid-cols-[1fr_160px]">
          <Field label="Headline"><input className="input" value={d.headline} onChange={(e) => set({ headline: e.target.value })} /></Field>
          <Field label="Years of experience"><input className="input" type="number" min={0} step={0.5} value={d.years} onChange={(e) => set({ years: e.target.value })} /></Field>
        </div>
        <Field label="Summary"><textarea className="input" rows={3} value={d.summary} onChange={(e) => set({ summary: e.target.value })} /></Field>
        <Field label="Skills"><ListEditor value={d.skills} onChange={(skills) => set({ skills })} /></Field>
      </Block>

      <Block icon={BriefcaseBusiness} title="Work experience" count={d.experience.length}
        action={<Button size="sm" variant="outline" icon={Plus} onClick={() => set({ experience: [...d.experience, { title: '', company: '', start: '', end: '', highlights: [] }] })}>Add role</Button>}>
        {d.experience.length ? d.experience.map((x, i) => (
          <Entry key={i} onRemove={() => remove('experience', i)}>
            <div className="grid gap-3 md:grid-cols-2">
              <Field label="Title"><input className="input" value={x.title} onChange={(e) => setItem('experience', i, { title: e.target.value })} /></Field>
              <Field label="Company"><input className="input" value={x.company} onChange={(e) => setItem('experience', i, { company: e.target.value })} /></Field>
            </div>
            <div className="grid gap-3 md:grid-cols-4">
              <Field label="Location"><input className="input" value={x.location ?? ''} onChange={(e) => setItem('experience', i, { location: e.target.value })} /></Field>
              <Field label="Type"><input className="input" placeholder="Full-time" value={x.employment_type ?? ''} onChange={(e) => setItem('experience', i, { employment_type: e.target.value })} /></Field>
              <Field label="From"><input className="input" placeholder="Jan 2024" value={x.start} onChange={(e) => setItem('experience', i, { start: e.target.value })} /></Field>
              <Field label="To"><input className="input" placeholder="Present" value={x.end} onChange={(e) => setItem('experience', i, { end: e.target.value })} /></Field>
            </div>
            <Field label="What you did" hint="One point per line.">
              <textarea className="input" rows={Math.min(8, Math.max(3, x.highlights.length + 1))} value={x.highlights.join('\n')}
                onChange={(e) => setItem('experience', i, { highlights: e.target.value.split('\n') })} />
            </Field>
          </Entry>
        )) : <Empty>No roles read yet. Analyze your resume, or add them here.</Empty>}
      </Block>

      <Block icon={GraduationCap} title="Education" count={d.education.length}
        action={<Button size="sm" variant="outline" icon={Plus} onClick={() => set({ education: [...d.education, { institution: '', degree: '' }] })}>Add</Button>}>
        {d.education.length ? d.education.map((x, i) => (
          <Entry key={i} onRemove={() => remove('education', i)}>
            <div className="grid gap-3 md:grid-cols-3">
              <Field label="Institution"><input className="input" value={x.institution} onChange={(e) => setItem('education', i, { institution: e.target.value })} /></Field>
              <Field label="Degree"><input className="input" value={x.degree} onChange={(e) => setItem('education', i, { degree: e.target.value })} /></Field>
              <Field label="Field"><input className="input" value={x.field ?? ''} onChange={(e) => setItem('education', i, { field: e.target.value })} /></Field>
              <Field label="From"><input className="input" value={x.start ?? ''} onChange={(e) => setItem('education', i, { start: e.target.value })} /></Field>
              <Field label="To"><input className="input" value={x.end ?? ''} onChange={(e) => setItem('education', i, { end: e.target.value })} /></Field>
              <Field label="Grade"><input className="input" value={x.grade ?? ''} onChange={(e) => setItem('education', i, { grade: e.target.value })} /></Field>
            </div>
          </Entry>
        )) : <Empty>No education read yet.</Empty>}
      </Block>

      <Block icon={Rocket} title="Projects" count={d.projects.length}
        action={<Button size="sm" variant="outline" icon={Plus} onClick={() => set({ projects: [...d.projects, { name: '', summary: '' }] })}>Add</Button>}>
        {d.projects.length ? d.projects.map((x, i) => (
          <Entry key={i} onRemove={() => remove('projects', i)}>
            <div className="grid gap-3 md:grid-cols-2">
              <Field label="Name"><input className="input" value={x.name} onChange={(e) => setItem('projects', i, { name: e.target.value })} /></Field>
              <Field label="Link"><input className="input" value={x.link ?? ''} onChange={(e) => setItem('projects', i, { link: e.target.value })} /></Field>
            </div>
            <Field label="Tech"><ListEditor value={x.tech ?? []} onChange={(tech) => setItem('projects', i, { tech })} /></Field>
            <Field label="Summary"><textarea className="input" rows={2} value={x.summary} onChange={(e) => setItem('projects', i, { summary: e.target.value })} /></Field>
          </Entry>
        )) : <Empty>No projects read yet.</Empty>}
      </Block>

      <Block icon={Link2} title="Contact, links and more">
        <div className="grid gap-3 md:grid-cols-3">
          {([['full_name', 'Full name'], ['email', 'Email'], ['phone', 'Phone'], ['location', 'Location'], ['linkedin', 'LinkedIn'], ['github', 'GitHub'], ['portfolio', 'Portfolio']] as Array<[keyof ResumeContact, string]>).map(([k, label]) => (
            <Field key={k} label={label}><input className="input" value={d.contact[k] ?? ''} onChange={(e) => set({ contact: { ...d.contact, [k]: e.target.value } })} /></Field>
          ))}
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          <Field label="Certifications"><ListEditor value={d.certifications} onChange={(certifications) => set({ certifications })} /></Field>
          <Field label="Languages"><ListEditor value={d.languages} onChange={(languages) => set({ languages })} /></Field>
        </div>
        <div className="flex flex-wrap items-center gap-3 rounded-lg bg-surface-2 p-3 text-[13px] text-ink-2">
          <span className="min-w-[220px] flex-1">Copy your name, contact details, links and years of experience into your form answers. Only empty answers are filled.</span>
          <Button size="sm" variant="outline" onClick={() => fillAnswers.mutate()} loading={fillAnswers.isPending} disabled={dirty}
            title={dirty ? 'Save your changes first' : undefined}>Use for my form answers</Button>
        </div>
      </Block>

      <section className="rounded-xl border border-line">
        <button type="button" className="flex w-full items-center justify-between px-4 py-3 text-left text-[15px] font-bold" onClick={() => setShowText((v) => !v)} aria-expanded={showText}>
          Resume text the AI reads {showText ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
        </button>
        {showText && (
          <div className="border-t border-line p-4">
            <textarea className="input mono" rows={14} value={d.resume_text} onChange={(e) => set({ resume_text: e.target.value })} />
          </div>
        )}
      </section>

      <div className="sticky bottom-0 flex justify-end gap-2 rounded-xl bg-[color-mix(in_oklab,var(--bg)_88%,transparent)] py-2 backdrop-blur">
        <Button variant="ghost" onClick={() => setD(initial)} disabled={!dirty}>Reset</Button>
        <Button variant="primary" onClick={() => save.mutate()} loading={save.isPending} disabled={!dirty}>Save resume details</Button>
      </div>
    </div>
  )
}

function Block({ icon: Icon, title, count, action, children }: { icon: typeof UserRound; title: string; count?: number; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3 rounded-xl border border-line p-4">
      <div className="flex items-center gap-2">
        <Icon size={17} className="text-accent-ink" />
        <h4 className="text-[15px] font-bold">{title}</h4>
        {count !== undefined && <span className="num text-xs text-ink-2">{count}</span>}
        <span className="ml-auto">{action}</span>
      </div>
      {children}
    </section>
  )
}

function Entry({ children, onRemove }: { children: ReactNode; onRemove: () => void }) {
  return (
    <div className="relative flex flex-col gap-3 rounded-lg bg-surface-2 p-3 pr-11">
      {children}
      <button type="button" aria-label="Remove" onClick={onRemove} className="absolute right-2 top-2 rounded-md p-1.5 text-muted hover:text-bad-ink"><Trash2 size={15} /></button>
    </div>
  )
}

function Empty({ children }: { children: ReactNode }) {
  return <p className="text-[13px] text-ink-2">{children}</p>
}
