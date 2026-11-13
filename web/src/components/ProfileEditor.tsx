import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Trash2 } from 'lucide-react'
import { clsx } from 'clsx'
import { ApiError, deleteProfile, getResume, listResumes, updateProfile } from '../api'
import type { SearchProfile, SearchProfileRow } from '../types'
import { useToast } from '../lib/toast'
import { errorMessage } from '../lib/tasks'
import { Button, Dialog, Field, ListEditor, Switch } from './ui'

const SENIORITY: Array<[string, string[]]> = [['Junior', ['junior']], ['Junior and mid-level', ['junior', 'mid']], ['Mid-level', ['mid']], ['Mid and senior', ['mid', 'senior']], ['Senior', ['senior']], ['Any', []]]
const JOB_TYPES: Array<[string, string]> = [['full_time', 'Full-time'], ['part_time', 'Part-time'], ['contract', 'Contract'], ['internship', 'Internship'], ['freelance', 'Freelance']]
const AGES = [1, 3, 7, 14, 21, 30, 60]

type Editable = Pick<SearchProfileRow, 'name' | 'enabled' | 'search' | 'resume_id'>
const snapshot = (r: Editable) => JSON.stringify([r.name, r.enabled, r.search, r.resume_id ?? null])

/** Edit one search profile. Saving re-checks collected jobs against all profiles (free, no AI). */
export default function ProfileEditor({ row, onDeleted, onDirtyChange, canDelete = true }: { row: SearchProfileRow; onDeleted?: () => void; onDirtyChange?: (dirty: boolean) => void; canDelete?: boolean }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [name, setName] = useState(row.name)
  const [enabled, setEnabled] = useState(row.enabled)
  const [s, setS] = useState<SearchProfile>(row.search)
  const [resumeId, setResumeId] = useState<number | null>(row.resume_id)
  const resumes = useQuery({ queryKey: ['resumes'], queryFn: listResumes, staleTime: 60_000 })
  const me = useQuery({ queryKey: ['resume', resumeId ?? 1], queryFn: () => getResume(resumeId ?? 1), staleTime: 60_000 })
  const [confirmDelete, setConfirmDelete] = useState(false)
  // Take the server's copy only for another profile or when nothing here is unsaved: every finished background task
  // refetches all queries, and that must not wipe what the user is typing.
  const synced = useRef({ id: row.id, snap: snapshot(row) })
  const take = (r: SearchProfileRow) => { setName(r.name); setEnabled(r.enabled); setS(r.search); setResumeId(r.resume_id); synced.current = { id: r.id, snap: snapshot(r) } }
  useEffect(() => {
    const untouched = snapshot({ name, enabled, search: s, resume_id: resumeId }) === synced.current.snap
    if (synced.current.id !== row.id || untouched) take(row)
    else synced.current = { id: row.id, snap: snapshot(row) }
  }, [row]) // eslint-disable-line react-hooks/exhaustive-deps
  const upd = <K extends keyof SearchProfile>(k: K, v: SearchProfile[K]) => setS((x) => ({ ...x, [k]: v }))
  const dirty = name !== row.name || enabled !== row.enabled || JSON.stringify(s) !== JSON.stringify(row.search)
    || (resumeId ?? null) !== (row.resume_id ?? null)
  useEffect(() => { onDirtyChange?.(dirty) }, [dirty, onDirtyChange])
  useEffect(() => () => onDirtyChange?.(false), [onDirtyChange])
  const refresh = () => { qc.invalidateQueries({ queryKey: ['profiles'] }); qc.invalidateQueries({ queryKey: ['jobs'] }); qc.invalidateQueries({ queryKey: ['jobs-count'] }); qc.invalidateQueries({ queryKey: ['today'] }) }

  const save = useMutation({
    mutationFn: () => updateProfile(row.id, { name, enabled, search: s, resume_id: resumeId }),
    onSuccess: (r) => {
      take(r)
      const m = (r as SearchProfileRow & { rematch?: { queued: number } }).rematch
      toast.success('Profile saved', m ? `${m.queued} collected jobs match your profiles now.` : undefined); refresh()
    },
    onError: (e) => toast.error('Save failed', errorMessage(e)),
  })
  const del = useMutation({
    mutationFn: () => deleteProfile(row.id),
    onSuccess: () => { setConfirmDelete(false); toast.info('Profile deleted'); refresh(); onDeleted?.() },
    onError: (e) => { setConfirmDelete(false); toast.error(e instanceof ApiError && e.status === 409 ? 'Keep at least one profile' : 'Delete failed', errorMessage(e)) },
  })
  const senKey = SENIORITY.find(([, v]) => JSON.stringify(v) === JSON.stringify(s.seniority))?.[0] ?? 'Any'
  const years = me.data?.years_experience
  const lpa = s.min_salary_inr ? s.min_salary_inr / 100_000 : ''
  const usdK = s.min_salary_usd ? s.min_salary_usd / 1000 : ''
  const toggleType = (t: string) => upd('job_types', s.job_types.includes(t) ? s.job_types.filter((x) => x !== t) : [...s.job_types, t])

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-end gap-4">
        <Field label="Profile name" className="min-w-[240px] flex-1"><input className="input" value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <Field label="Resume" className="min-w-[220px] flex-1">
          <select className="input" value={resumeId ?? 1} aria-label="Resume this profile uses"
            onChange={(e) => setResumeId(Number(e.target.value) === 1 ? null : Number(e.target.value))}>
            {(resumes.data ?? []).filter((r) => r.has_text || r.is_default).map((r) => (
              <option key={r.id} value={r.id}>{r.name}{r.is_default ? ' (default)' : ''}{r.resume_filename ? '' : ' · no file yet'}</option>
            ))}
          </select>
        </Field>
        <Switch checked={enabled} onChange={setEnabled} label={<span className="text-sm font-semibold">{enabled ? 'Active' : 'Off'}</span>} />
        <Button variant="ghost" icon={Trash2} className="ml-auto" onClick={() => setConfirmDelete(true)} loading={del.isPending} disabled={!canDelete}
          title={canDelete ? 'Delete this search profile' : 'Keep at least one profile. Turn this one off or change it instead.'}>Delete profile</Button>
      </div>

      <Group title="What you want">
        <div className="grid gap-4 md:grid-cols-2">
          <Field label="Job titles to search for" hint="Used as search terms on job boards."><ListEditor value={s.roles} onChange={(v) => upd('roles', v)} placeholder="Python Developer, Backend Engineer" /></Field>
          <Field label="Title must include one of" hint="Jobs without one of these words are skipped for free."><ListEditor value={s.title_keywords} onChange={(v) => upd('title_keywords', v)} placeholder="python, backend" /></Field>
          <Field label="Your key skills" hint="Ranks descriptions and is shown to the AI."><ListEditor value={s.skills} onChange={(v) => upd('skills', v)} placeholder="python, fastapi, postgres" /></Field>
          <Field label="Seniority" hint="Told to the AI when it scores. Use the title filters below to hide senior titles.">
            <select className="input" value={senKey} onChange={(e) => upd('seniority', SENIORITY.find(([k]) => k === e.target.value)?.[1] ?? [])}>
              {SENIORITY.map(([k]) => <option key={k}>{k}</option>)}
            </select>
          </Field>
        </div>
      </Group>

      <Group title="Where and how">
        <div className="grid gap-4 md:grid-cols-2">
          <Field label="Where" hint="Cities or countries matched against the job location. Empty means anywhere. Remote jobs open only in other places are skipped."><ListEditor value={s.locations} onChange={(v) => upd('locations', v)} placeholder="Berlin, London, Remote" /></Field>
          <Field label="Countries" hint="ISO codes such as in or us. Picks regional job boards."><ListEditor value={s.countries} onChange={(v) => upd('countries', v.map((c) => c.toLowerCase()))} placeholder="in" /></Field>
        </div>
        <div className="flex flex-col gap-2">
          <span className="text-xs font-medium text-ink-2">Work mode</span>
          <div className="flex flex-wrap gap-2">
            <Pill on={s.remote_ok} onClick={() => upd('remote_ok', !s.remote_ok)}>Remote</Pill>
            <Pill on={s.hybrid_ok} onClick={() => upd('hybrid_ok', !s.hybrid_ok)}>Hybrid</Pill>
            <Pill on={s.onsite_ok} onClick={() => upd('onsite_ok', !s.onsite_ok)}>Onsite</Pill>
          </div>
        </div>
        <div className="flex flex-col gap-2">
          <span className="text-xs font-medium text-ink-2">Job type <span className="font-normal">· none selected means any</span></span>
          <div className="flex flex-wrap gap-2">
            {JOB_TYPES.map(([id, label]) => <Pill key={id} on={s.job_types.includes(id)} onClick={() => toggleType(id)}>{label}</Pill>)}
          </div>
        </div>
      </Group>

      <Group title="Experience and pay" hint="Postings that do not state these are always kept.">
        <div className="grid gap-4 md:grid-cols-3">
          <Field label="Experience the job asks for" hint={years != null ? `Your resume says ${years} years.` : 'Years. Leave the maximum empty for no limit.'}>
            <div className="flex items-center gap-2">
              <input className="input" type="number" min={0} max={30} step={0.5} aria-label="Minimum years" value={s.experience_min}
                onChange={(e) => upd('experience_min', Number(e.target.value) || 0)} />
              <span className="text-ink-2">to</span>
              <input className="input" type="number" min={0} max={30} step={0.5} aria-label="Maximum years" placeholder="any" value={s.experience_max ?? ''}
                onChange={(e) => upd('experience_max', e.target.value === '' ? null : Number(e.target.value))} />
            </div>
          </Field>
          <Field label="Minimum salary in India" hint="Lakhs per year (LPA).">
            <div className="flex items-center gap-2"><span className="text-ink-2">₹</span>
              <input className="input" type="number" min={0} step={0.5} placeholder="any" value={lpa}
                onChange={(e) => upd('min_salary_inr', e.target.value === '' ? null : Number(e.target.value) * 100_000)} /><span className="text-ink-2">LPA</span></div>
          </Field>
          <Field label="Minimum salary in USD" hint="Thousands per year, for remote roles.">
            <div className="flex items-center gap-2"><span className="text-ink-2">$</span>
              <input className="input" type="number" min={0} step={5} placeholder="any" value={usdK}
                onChange={(e) => upd('min_salary_usd', e.target.value === '' ? null : Number(e.target.value) * 1000)} /><span className="text-ink-2">k</span></div>
          </Field>
          <Field label="Posted within">
            <select className="input" value={s.max_age_days} onChange={(e) => upd('max_age_days', Number(e.target.value))}>
              {AGES.map((d) => <option key={d} value={d}>{d === 1 ? 'Last 24 hours' : `Last ${d} days`}</option>)}
            </select>
          </Field>
          <Field label="Shortlist at fit score" hint="0–100. Strong matches start here.">
            <input className="input" type="number" min={0} max={100} value={s.min_fit_score} onChange={(e) => upd('min_fit_score', Number(e.target.value))} />
          </Field>
        </div>
      </Group>

      <Group title="Exclusions">
        <div className="grid gap-4 md:grid-cols-2">
          <Field label="Never show titles with"><ListEditor value={s.exclude_keywords} onChange={(v) => upd('exclude_keywords', v)} placeholder="intern, director, manager" /></Field>
          <Field label="Companies to hide" hint="Part of the name is enough."><ListEditor value={s.exclude_companies} onChange={(v) => upd('exclude_companies', v)} placeholder="Acme Staffing" /></Field>
          <Field label="Description must mention one of" hint="Empty means no requirement."><ListEditor value={s.must_mention} onChange={(v) => upd('must_mention', v)} placeholder="python" /></Field>
          <Field label="Hide if the description mentions"><ListEditor value={s.must_not_mention} onChange={(v) => upd('must_not_mention', v)} placeholder="c2c, unpaid, commission only" /></Field>
        </div>
      </Group>

      <div className="flex flex-wrap items-center gap-2 border-t border-line pt-4">
        <span className="text-[13px] text-ink-2">{row.matching} collected job{row.matching === 1 ? '' : 's'} match this profile</span>
        <span className="ml-auto" />
        <Button variant="ghost" onClick={() => take(row)} disabled={!dirty}>Reset</Button>
        <Button variant="primary" onClick={() => save.mutate()} loading={save.isPending} disabled={!dirty}>Save profile</Button>
      </div>
      <Dialog open={confirmDelete} onClose={() => setConfirmDelete(false)} title={`Delete the profile "${row.name}"?`}
        footer={<><Button variant="ghost" onClick={() => setConfirmDelete(false)}>Cancel</Button>
          <Button variant="danger" icon={Trash2} onClick={() => del.mutate()} loading={del.isPending}>Delete profile</Button></>}>
        <p>Jobs not analyzed yet that only this profile matched are filtered out. Analyzed jobs, applications and the resume it uses all stay. This can&rsquo;t be undone.</p>
      </Dialog>
    </div>
  )
}

function Group({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-4 rounded-xl border border-line p-4">
      <div><h4 className="text-[15px] font-bold">{title}</h4>{hint && <p className="mt-0.5 text-xs text-ink-2">{hint}</p>}</div>
      {children}
    </section>
  )
}

function Pill({ on, onClick, children }: { on: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button type="button" aria-pressed={on} onClick={onClick}
      className={clsx('h-9 rounded-lg border px-3.5 text-[13px] font-semibold transition-colors',
        on ? 'border-[var(--accent)] bg-accent text-on-accent' : 'border-[var(--baseline)] bg-surface text-ink-2 hover:text-ink')}>{children}</button>
  )
}
