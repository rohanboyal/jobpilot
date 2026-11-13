import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Camera, Check, ExternalLink, Eye, Plus, RotateCcw, Send, Sparkles, Trash2 } from 'lucide-react'
import { ApiError, approveApplication, fillApplication, getApplication, getSchedule, getStats, listApplications, listResumes, patchApplication, screenshotUrl, submitApplication, writeCoverLetter } from '../api'
import type { AppStatus, Application, ApplicationWithJob } from '../types'
import { useToast } from '../lib/toast'
import { errorMessage, useTasks } from '../lib/tasks'
import { fmtDateTime, fmtRelative, hostOf, titleCase } from '../lib/format'
import { Button, Card, Chip, CopyButton, Dialog, EmptyState, KV, LogView, SectionTitle, Spinner, Tabs } from '../components/ui'
import { AppStatusChip, FitBadge, SourceChip } from '../components/status'
import TaskBanner from '../components/TaskBanner'
import OutcomeTracker from '../components/OutcomeTracker'

const TABS: Array<{ value: AppStatus | 'all'; label: string }> = [
  { value: 'needs_review', label: 'Needs review' }, { value: 'approved', label: 'Approved' }, { value: 'submitted', label: 'Submitted' },
  { value: 'manual', label: 'Manual' }, { value: 'failed', label: 'Failed' }, { value: 'withdrawn', label: 'Withdrawn' }, { value: 'all', label: 'All' },
]

export default function Applications() {
  const { id } = useParams()
  const nav = useNavigate()
  const [sp, setSp] = useSearchParams()
  const selectedId = id ? Number(id) : null
  // A link to one application opens the tab it is in, so the list beside it matches.
  const selected = useQuery({ queryKey: ['application', selectedId], queryFn: () => getApplication(selectedId!), enabled: selectedId !== null && !sp.get('status') })
  const own = selected.data?.status
  const tab = (sp.get('status') ?? (own ? (TABS.some((t) => t.value === own) ? own : 'all') : 'needs_review')) as AppStatus | 'all'
  const stats = useQuery({ queryKey: ['stats'], queryFn: getStats, staleTime: 15_000 })
  const list = useQuery({
    queryKey: ['applications', tab],
    queryFn: () => listApplications({ status: tab === 'all' ? undefined : tab, page_size: 100 }),
    placeholderData: (prev) => prev,
  })
  const counts = stats.data?.applications.by_status ?? {}

  return (
    <div className="mx-auto max-w-[1500px]">
      <TaskBanner />
      <header className="mb-4">
        <h2 className="page-title">Applications</h2>
        <p className="mt-1.5 text-sm text-ink-2">Letters and answers waiting for your review, what you sent and what happened next, and jobs to apply to by hand.</p>
      </header>
      <div className="mb-3">
        <Tabs value={tab} onChange={(v) => { const n = new URLSearchParams(sp); n.set('status', v); setSp(n, { replace: true }) }}
          items={TABS.map((t) => ({ value: t.value, label: t.label, count: t.value === 'all' ? Object.values(counts).reduce((a, b) => a + b, 0) : (counts[t.value] ?? 0) }))} />
      </div>
      <div className="grid gap-4 lg:grid-cols-[380px_1fr]">
        <div className="card overflow-hidden self-start">
          {list.isLoading ? <div className="flex justify-center py-10"><Spinner /></div>
            : !list.data?.items.length ? (
              <EmptyState icon={Send} title={tab === 'needs_review' ? 'Nothing to review' : 'No applications'}
                hint={tab === 'needs_review' ? 'When the AI shortlists a job and drafts a cover letter it lands here for your approval.' : undefined} />
            ) : (
              <ul className="scroll-thin max-h-[calc(100vh-200px)] divide-y divide-line overflow-y-auto">
                {list.data.items.map((a) => (
                  <li key={a.id}>
                    <button onClick={() => nav(`/applications/${a.id}?status=${tab}`)}
                      className={`flex w-full items-start gap-3 px-4 py-3 text-left hover:bg-surface-2 ${selectedId === a.id ? 'bg-surface-2' : ''}`}>
                      <FitBadge score={a.job.fit_score} size="sm" />
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-sm font-medium">{a.job.title}</div>
                        <div className="truncate text-xs text-ink-2">{a.job.company_name}</div>
                        <div className="mt-1 flex items-center gap-1.5"><AppStatusChip status={a.status} /><span className="text-[11px] text-muted">{fmtRelative(a.updated_at)}</span></div>
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
            )}
        </div>
        <div>
          {selectedId ? <ApplicationDetail id={selectedId} /> : (
            <div className="card"><EmptyState icon={Eye} title="Select an application" hint="Review the cover letter and answers, fill the form in the browser to check it, then submit." /></div>
          )}
        </div>
      </div>
    </div>
  )
}

function ApplicationDetail({ id }: { id: number }) {
  const qc = useQueryClient()
  const toast = useToast()
  const nav = useNavigate()
  const tasks = useTasks()
  const app = useQuery({ queryKey: ['application', id], queryFn: () => getApplication(id) })
  const [cover, setCover] = useState('')
  const [answers, setAnswers] = useState<Row[]>([])
  const [confirmSubmit, setConfirmSubmit] = useState(false)
  const [confirmManual, setConfirmManual] = useState(false)
  const [confirmResend, setConfirmResend] = useState(false)
  const schedule = useQuery({ queryKey: ['schedule'], queryFn: getSchedule, staleTime: 60_000 })
  const minFit = schedule.data?.prepare.min_fit ?? 75
  const [shotKey, setShotKey] = useState(() => Date.now())
  // Take the server's letter and answers only when nothing local is unsaved. Any finished background task refetches
  // every query, and that must never wipe what the user is typing.
  const synced = useRef<{ id: number; cover: string; answers: string } | null>(null)
  useEffect(() => {
    const d = app.data
    if (!d) return
    const server = { id: d.id, cover: d.cover_letter ?? '', answers: JSON.stringify(d.answers ?? {}) }
    const prev = synced.current
    const untouched = prev !== null && cover === prev.cover && JSON.stringify(toAnswers(answers)) === prev.answers
    if (!prev || prev.id !== d.id || untouched) {
      setCover(server.cover)
      setAnswers(Object.entries(d.answers ?? {}).map(([k, v]) => ({ k, v, isNew: false })))
    }
    synced.current = server
  }, [app.data]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => setShotKey(Date.now()), [app.data?.id, app.data?.screenshot_path, app.data?.updated_at])

  const applying = (tasks.data?.running ?? []).includes('apply')
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['application', id] })
    qc.invalidateQueries({ queryKey: ['applications'] })
    qc.invalidateQueries({ queryKey: ['stats'] })
    qc.invalidateQueries({ queryKey: ['jobs'] })
  }
  const onErr = (title: string) => (e: unknown) =>
    (e instanceof ApiError && e.status === 409 ? toast.info("Can't do that right now", e.message) : toast.error(title, errorMessage(e)))
  // Pass the new rows when saving right after changing them: the state update has not rendered yet.
  const save = useMutation({
    mutationFn: (rows: Row[] | void) => patchApplication(id, { cover_letter: cover, answers: toAnswers(rows || answers) }),
    onSuccess: () => refresh(), onError: onErr('Save failed'),
  })
  const setStatus = useMutation({
    mutationFn: (status: string) => patchApplication(id, { status }),
    onSuccess: (_d, s) => { toast.success(`Marked ${titleCase(s)}`); refresh() }, onError: onErr('Update failed'),
  })
  const approve = useMutation({ mutationFn: () => approveApplication(id), onSuccess: () => { toast.success('Approved', 'Press Submit to send it. It is only sent on its own when Schedule › Apply is automatic.'); refresh() }, onError: onErr('Approve failed') })
  const fill = useMutation({ mutationFn: () => fillApplication(id), onSuccess: () => { toast.success('Filling the form in the browser', 'A screenshot will appear here when done. Nothing is submitted.'); qc.invalidateQueries({ queryKey: ['tasks'] }) }, onError: onErr('Could not start') })
  const submit = useMutation({ mutationFn: () => submitApplication(id), onSuccess: () => { setConfirmSubmit(false); toast.success('Submitting…', 'The agent is filling and submitting the form now.'); qc.invalidateQueries({ queryKey: ['tasks'] }) }, onError: onErr('Could not start') })
  const writeCover = useMutation({
    mutationFn: async () => { await saveFirst(); return writeCoverLetter(id) },
    onSuccess: (r) => {
      if (r.cover_letter) toast.success('Cover letter written', 'Read it through and edit anything that is not quite you.')
      else toast.error('No letter came back', 'The AI did not return a cover letter. The log below may say why; you can also write one yourself.')
      refresh(); qc.invalidateQueries({ queryKey: ['job', app.data?.job_id] })
    },
    onError: onErr('Could not write a cover letter'),
  })
  const allowResend = useMutation({
    mutationFn: () => patchApplication(id, { clear_submit_click: true }),
    onSuccess: () => { setConfirmResend(false); toast.success('It can be sent again', 'Check the letter and answers, then submit when you are ready.'); refresh() },
    onError: (e) => { setConfirmResend(false); onErr('Could not change it')(e) },
  })

  const a = app.data
  const dirty = useMemo(() => a ? (cover !== (a.cover_letter ?? '') || JSON.stringify(toAnswers(answers)) !== JSON.stringify(a.answers ?? {})) : false, [a, cover, answers])
  // Edits save when a field loses focus; closing the tab with unsaved edits asks first.
  const saveIfDirty = () => { if (dirty && !save.isPending) save.mutate() }
  const saveFirst = async () => { if (dirty) await save.mutateAsync() }
  const removeRow = (i: number) => { const rows = answers.filter((_, yi) => yi !== i); setAnswers(rows); save.mutate(rows) }
  useEffect(() => {
    if (!dirty) return
    const warn = (e: BeforeUnloadEvent) => { e.preventDefault() }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])
  const answered = (question: string) => answers.some((r) => r.k.trim().toLowerCase() === question.trim().toLowerCase() && r.v.trim())
  const answerHere = (question: string) => {
    if (!answers.some((r) => r.k.trim().toLowerCase() === question.trim().toLowerCase())) setAnswers((x) => [...x, { k: question, v: '', isNew: false }])
    setTimeout(() => document.getElementById(`answer-${question}`)?.focus(), 50)
  }

  if (app.isLoading) return <div className="card flex justify-center py-16"><Spinner size={22} /></div>
  if (app.isError || !a) return <div className="card"><EmptyState title="Could not load application" hint={errorMessage(app.error)} /></div>
  const j = a.job
  const link = j.apply_url || j.url
  const canAct = a.status !== 'submitted' && a.status !== 'withdrawn' && a.status !== 'submitting'
  // Submit was clicked but the outcome is unclear: nothing is filled or sent again until the user says it failed.
  const unclear = !!a.submitted_at && a.status !== 'submitted'
  const lockedTitle = unclear ? 'Submit was already clicked once. See the note above.' : undefined

  return (
    <div className="flex flex-col gap-4">
      <Card padded={false}>
        <div className="flex items-start gap-4 p-4">
          <FitBadge score={j.fit_score} size="lg" />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-base font-semibold">{j.title}</h2>
              <AppStatusChip status={a.status} />
              {a.ats_type && <Chip tone="accent">{a.ats_type}</Chip>}
              {a.method === 'manual' && <Chip tone="violet">apply by hand</Chip>}
            </div>
            <div className="mt-0.5 text-sm text-ink-2">{j.company_name}{j.location ? ` · ${j.location}` : ''} · <SourceChip source={j.source} /></div>
            <div className="mt-2 flex flex-wrap items-center gap-3 text-xs">
              <a href={link} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1">{hostOf(link)} <ExternalLink size={11} /></a>
              <button className="text-accent-ink hover:underline" onClick={() => nav(`/jobs?job=${j.id}`)}>Job details</button>
              {a.submitted_at && (a.status === 'submitted'
                ? <span className="text-good-ink">Submitted {fmtDateTime(a.submitted_at)}</span>
                : <span className="text-warn-ink">Submit clicked {fmtDateTime(a.submitted_at)}, result unclear</span>)}
            </div>
          </div>
        </div>
        {(a.error || a.confirmation) && (
          <div className={`border-t border-line px-4 py-2 text-xs ${a.error ? 'text-bad-ink' : 'text-good-ink'}`}>{a.error ?? a.confirmation}</div>
        )}
        <div className="flex flex-wrap items-center gap-2 border-t border-line px-4 py-3">
          {canAct && a.method === 'browser' && (
            <>
              <Button icon={Camera} onClick={async () => { await saveFirst(); fill.mutate() }} loading={fill.isPending || (applying && a.status !== 'submitting')} disabled={applying || unclear}
                title={lockedTitle ?? 'Opens the form, fills it, takes a screenshot. Does not submit.'}>Fill in browser (no submit)</Button>
              {a.status !== 'approved' && <Button icon={Check} onClick={async () => { await saveFirst(); approve.mutate() }} loading={approve.isPending} disabled={unclear} title={lockedTitle}>Approve</Button>}
              <Button variant="primary" icon={Send} onClick={() => setConfirmSubmit(true)} disabled={applying || unclear} title={lockedTitle ?? 'Fills and submits the application'}>Submit application</Button>
            </>
          )}
          {canAct && <Button variant="outline" icon={Check} onClick={() => setConfirmManual(true)} loading={setStatus.isPending && setStatus.variables === 'submitted'}>I applied myself</Button>}
          {canAct && <Button variant="ghost" icon={Trash2} onClick={() => setStatus.mutate('withdrawn')} loading={setStatus.isPending && setStatus.variables === 'withdrawn'}>Withdraw</Button>}
          {a.status === 'withdrawn' && <Button variant="outline" onClick={() => setStatus.mutate('needs_review')}>Reopen</Button>}
          <span className="ml-auto text-[11px] text-muted" aria-live="polite">{save.isPending ? 'Saving…' : dirty ? 'Unsaved changes' : `Saved · updated ${fmtRelative(a.updated_at)}`}</span>
        </div>
      </Card>

      {a.status === 'submitted' && <OutcomeTracker a={a} />}

      {unclear && (a.status === 'needs_review' || a.status === 'failed') && (
        <div className="rounded-xl border p-3 text-sm" style={{ borderColor: 'color-mix(in oklab, var(--warn) 50%, var(--line))', background: 'color-mix(in oklab, var(--warn) 10%, transparent)' }}>
          <div className="mb-1 font-medium text-warn-ink">Submit was clicked, but it is not clear the application went through</div>
          <p className="mb-2 text-xs text-ink-2">
            JobPilot pressed Submit on {fmtDateTime(a.submitted_at)} and could not confirm the result. So that {j.company_name} never gets the same application twice,
            it will not fill or submit this one again. Check your email for a confirmation, or your account on {hostOf(link)}.
          </p>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="outline" icon={Check} onClick={() => setStatus.mutate('submitted')} loading={setStatus.isPending && setStatus.variables === 'submitted'}>It went through</Button>
            <Button size="sm" variant="outline" icon={RotateCcw} onClick={() => setConfirmResend(true)}>It didn't go through, allow sending again</Button>
          </div>
        </div>
      )}

      {(a.unanswered ?? []).length > 0 && (
        <div className="rounded-xl border p-3 text-sm" style={{ borderColor: 'color-mix(in oklab, var(--warn) 50%, var(--line))', background: 'color-mix(in oklab, var(--warn) 10%, transparent)' }}>
          <div className="mb-1 font-medium text-warn-ink">Questions the agent would not answer for you</div>
          <p className="mb-2 text-xs text-ink-2">It never guesses personal facts. Answer them for this application below, or once for every application in <Link to="/settings?tab=answers">Settings › Your answers</Link>.</p>
          <ul className="flex flex-col gap-1.5">{(a.unanswered ?? []).map((u, i) => (
            <li key={i} className="flex flex-wrap items-center gap-2 text-ink">
              <span className="min-w-0 flex-1">{u}</span>
              {answered(u)
                ? <span className="inline-flex items-center gap-1 text-xs font-semibold text-good-ink"><Check size={13} />Answered below</span>
                : canAct && <Button size="sm" variant="outline" icon={Plus} onClick={() => answerHere(u)}>Answer here</Button>}
            </li>
          ))}</ul>
        </div>
      )}

      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="Cover letter" subtitle={a.method === 'manual' ? 'Copy this into the application' : 'Used for cover letter / additional information fields'}
          actions={<>{a.cover_letter && <CopyButton text={a.cover_letter} />}<Button size="sm" variant="primary" onClick={() => save.mutate()} loading={save.isPending} disabled={!dirty}>Save</Button></>}>
          <textarea className="input" rows={14} aria-label="Cover letter" value={cover} onChange={(e) => setCover(e.target.value)} onBlur={saveIfDirty}
            placeholder={`No cover letter yet. Letters are drafted automatically only for strong matches (fit ${minFit} or higher). Write one here, or ask the AI for one.`} />
          {!a.cover_letter && !cover.trim() && (
            <div className="mt-3 flex flex-wrap items-center gap-3 rounded-lg bg-surface-2 p-3 text-[13px] text-ink-2">
              <span className="min-w-[200px] flex-1">The AI writes one from your resume and this job posting. Only the letter changes; your answers stay as they are.</span>
              <Button size="sm" variant="outline" icon={Sparkles} onClick={() => writeCover.mutate()} loading={writeCover.isPending}
                disabled={!canAct || unclear || applying} title={lockedTitle}>Write a cover letter · 1 AI call</Button>
            </div>
          )}
          {j.fit?.pitch && (
            <div className="mt-3 rounded-lg bg-surface-2 p-3 text-sm">
              <div className="mb-1 flex items-center justify-between text-[11px] uppercase tracking-wide text-muted"><span>Short pitch</span><CopyButton text={j.fit.pitch} label="Copy pitch" /></div>
              {j.fit.pitch}
            </div>
          )}
        </Card>
        <Card title="Answers" subtitle="What the agent may type into form fields. Edits save when you leave a field." padded={false}
          actions={<Button size="sm" variant="outline" icon={Plus} onClick={() => setAnswers((x) => [...x, { k: '', v: '', isNew: true }])}>Add answer</Button>}>
          {answers.length ? (
            <ul className="divide-y divide-line">
              {answers.map((r, i) => (
                <li key={i} className="flex flex-col gap-1.5 px-4 py-3">
                  <div className="flex items-center gap-2">
                    {r.isNew
                      ? <input className="input !py-1 text-[13px] font-semibold" aria-label="Question or field" placeholder="Question or field, e.g. Notice period" autoFocus value={r.k}
                          onChange={(e) => setAnswers((x) => x.map((y, yi) => yi === i ? { ...y, k: e.target.value } : y))} onBlur={saveIfDirty} />
                      : <label htmlFor={`answer-${r.k}`} className="min-w-0 flex-1 text-[13px] font-semibold" title={r.k}>{fieldLabel(r.k)}</label>}
                    <button type="button" className="ml-auto rounded p-1 text-muted hover:text-bad-ink" aria-label={`Remove ${fieldLabel(r.k) || 'answer'}`}
                      onClick={() => removeRow(i)}><Trash2 size={14} /></button>
                  </div>
                  <textarea id={`answer-${r.k}`} className="input !min-h-0 text-[13px]" rows={Math.min(6, Math.max(1, Math.ceil(r.v.length / 70)))} value={r.v}
                    aria-label={r.isNew ? 'Answer' : undefined} placeholder="Your answer"
                    onChange={(e) => setAnswers((x) => x.map((y, yi) => yi === i ? { ...y, v: e.target.value } : y))} onBlur={saveIfDirty} />
                </li>
              ))}
            </ul>
          ) : <div className="px-4 py-6 text-center text-xs text-muted">No answers yet. Add them here, or once for every application in <Link to="/settings?tab=answers">Settings › Your answers</Link>.</div>}
        </Card>
      </div>

      {a.screenshot_path && (
        <Card title="Last browser screenshot" subtitle={a.status === 'submitted' ? 'Taken after submit' : 'Taken after filling, before any submit'}>
          <a href={screenshotUrl(a.id, shotKey)} target="_blank" rel="noreferrer">
            <img src={screenshotUrl(a.id, shotKey)} alt="Application form screenshot" className="max-h-[720px] w-full rounded-lg border border-line object-contain object-top bg-surface-2" />
          </a>
        </Card>
      )}

      {(a.form_plan ?? []).length > 0 && (
        <Card title="Form plan" subtitle="How the AI mapped the form fields" padded={false}>
          <table className="tbl text-xs">
            <thead><tr><th>Field</th><th>Action</th><th>Value</th><th>Confidence</th></tr></thead>
            <tbody>
              {(a.form_plan ?? []).map((p, i) => (
                <tr key={i}>
                  <td className="mono">{String(p.field_id ?? '')}</td>
                  <td>{String(p.action ?? '')}</td>
                  <td className="max-w-[420px] truncate" title={String(p.value ?? '')}>{String(p.value ?? '')}</td>
                  <td className="num">{String(p.confidence ?? '')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      <Card title="Log">
        <LogView text={a.log} maxHeight={260} />
        <div className="mt-3"><SectionTitle>Record</SectionTitle>
          <KV rows={[['Created', fmtDateTime(a.created_at)], ['Resume', <ResumeChoice a={a} />],
            ['How it is sent', a.method === 'manual' ? 'You apply on the site yourself' : 'JobPilot fills the form in a browser']]} />
        </div>
      </Card>

      <Dialog open={confirmSubmit} onClose={() => setConfirmSubmit(false)} title="Submit this application?"
        footer={<><Button variant="ghost" onClick={() => setConfirmSubmit(false)}>Cancel</Button><Button variant="primary" icon={Send} onClick={async () => { await saveFirst(); submit.mutate() }} loading={submit.isPending || save.isPending}>Yes, submit</Button></>}>
        <p>The agent will open <strong>{hostOf(link)}</strong>, fill the form with the cover letter and answers shown here, upload your resume, and click <strong>Submit</strong>. This sends a real application to {j.company_name}.</p>
        <p className="mt-2 text-xs text-ink-2">If a required question has no truthful answer, it stops before submitting and asks you instead.{dirty ? ' Your unsaved edits are saved first.' : ''}</p>
      </Dialog>
      <Dialog open={confirmManual} onClose={() => setConfirmManual(false)} title="Record this as applied?"
        footer={<><Button variant="ghost" onClick={() => setConfirmManual(false)}>Cancel</Button>
          <Button variant="primary" icon={Check} loading={setStatus.isPending} onClick={() => setStatus.mutate('submitted', { onSuccess: () => setConfirmManual(false) })}>Yes, I applied</Button></>}>
        <p>Use this when you sent the application to {j.company_name} yourself, outside JobPilot. It moves to Submitted, JobPilot will never submit it again, and you can track replies and a follow-up date.</p>
        <p className="mt-2 text-xs text-ink-2">This can't be undone from here.</p>
      </Dialog>
      <Dialog open={confirmResend} onClose={() => setConfirmResend(false)} title="Allow sending this application again?"
        footer={<><Button variant="ghost" onClick={() => setConfirmResend(false)}>Cancel</Button>
          <Button variant="primary" icon={RotateCcw} loading={allowResend.isPending} onClick={() => allowResend.mutate()}>Yes, it didn't go through</Button></>}>
        <p>Only do this after checking that {j.company_name} did not get it: no confirmation email and nothing in your account on {hostOf(link)}.</p>
        <p className="mt-2 text-xs text-ink-2">It goes back to review, and you can fill and submit it again. If the first one did arrive, they would receive it twice.</p>
      </Dialog>
    </div>
  )
}

type Row = { k: string; v: string; isNew: boolean }

const toAnswers = (rows: Row[]) => Object.fromEntries(rows.filter((r) => r.k.trim()).map((r) => [r.k.trim(), r.v]))

/** "how_did_you_hear" -> "How did you hear"; question text stays as written. */
/** The resume uploaded with this application. It can be switched until the application is sent. */
function ResumeChoice({ a }: { a: Application }) {
  const qc = useQueryClient()
  const toast = useToast()
  const resumes = useQuery({ queryKey: ['resumes'], queryFn: listResumes, staleTime: 60_000 })
  const usable = (resumes.data ?? []).filter((r) => r.has_text && r.resume_filename)
  const locked = a.submitted_at !== null || ['submitting', 'submitted', 'withdrawn'].includes(a.status)
  const change = useMutation({
    mutationFn: (rid: number) => patchApplication(a.id, { resume_id: rid }),
    onSuccess: () => { toast.success('Resume changed', 'This file is uploaded when the form is filled.'); qc.invalidateQueries({ queryKey: ['application', a.id] }); qc.invalidateQueries({ queryKey: ['applications'] }) },
    onError: (e) => toast.error('Could not change it', errorMessage(e)),
  })
  const file = a.resume_path ? a.resume_path.split('/').pop() : null
  if (!file) return <span className="text-warn-ink">None uploaded. Add one in <Link to="/profiles">Profiles &amp; resumes</Link>.</span>
  if (locked || usable.length < 2) return <>{file}</>
  return (
    <select className="input !h-8 max-w-[340px]" aria-label="Resume uploaded with this application" value={a.resume_id ?? 1}
      disabled={change.isPending} onChange={(e) => change.mutate(Number(e.target.value))}>
      {usable.map((r) => <option key={r.id} value={r.id}>{r.name} ({r.resume_filename})</option>)}
    </select>
  )
}

function fieldLabel(key: string): string {
  const t = key.replace(/_/g, ' ').trim()
  return t ? t[0].toUpperCase() + t.slice(1) : ''
}

export type { ApplicationWithJob }
