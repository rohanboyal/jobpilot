import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, ExternalLink, Loader2, Sparkles, X, Zap } from 'lucide-react'
import { ApiError, addCustomAnswer, directApply, getApplication, getTask, listProfiles, listResumes, patchApplication, submitApplication } from '../api'
import type { DirectApplyResult, Job } from '../types'
import { useToast } from '../lib/toast'
import { errorMessage } from '../lib/tasks'
import { Button, CopyButton, LogView, useModal } from './ui'
import { FitBadge } from './status'

type Step = 'choose' | 'working' | 'review' | 'sent'

export default function ApplyDialog({ job, onClose }: { job: Job | null; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [step, setStep] = useState<Step>('choose')
  const [taskId, setTaskId] = useState<string | null>(null)
  const [appId, setAppId] = useState<number | null>(null)
  const [extra, setExtra] = useState<Record<string, string>>({})
  const [remember, setRemember] = useState<Record<string, boolean>>({})
  const [resumeId, setResumeId] = useState<number | null>(null)      // null: the resume of the job's own profile
  const resumes = useQuery({ queryKey: ['resumes'], queryFn: listResumes, enabled: !!job, staleTime: 60_000 })
  const profiles = useQuery({ queryKey: ['profiles'], queryFn: listProfiles, enabled: !!job, staleTime: 60_000 })
  const usable = useMemo(() => (resumes.data ?? []).filter((r) => r.has_text), [resumes.data])
  // What the server would pick: the resume of the first active profile the job matched, else the default.
  const autoResume = useMemo(() => {
    const on = (profiles.data ?? []).filter((p) => p.enabled)
    const pid = (job?.profile_ids ?? []).find((i) => on.some((p) => p.id === i))
    const rid = on.find((p) => p.id === pid)?.resume_id ?? 1
    return usable.some((r) => r.id === rid) ? rid : 1
  }, [profiles.data, usable, job?.profile_ids])

  useEffect(() => {
    setStep(job?.application_id && job.application_status === 'needs_review' ? 'review' : 'choose')
    setAppId(job?.application_id ?? null)
    setTaskId(null); setExtra({}); setRemember({}); setResumeId(null)
  }, [job?.id]) // eslint-disable-line react-hooks/exhaustive-deps
  const ref = useRef<HTMLDivElement>(null)
  useModal(!!job, ref, onClose)

  const start = useMutation({
    mutationFn: (mode: 'ai' | 'direct') => directApply(job!.id, mode, resumeId ?? undefined),
    onSuccess: (t) => { setTaskId(t.id); setStep('working'); qc.invalidateQueries({ queryKey: ['tasks'] }) },
    onError: (e) => (e instanceof ApiError && e.status === 409 ? toast.info('Busy', 'Another run is in progress. Try again when it finishes.') : toast.error('Could not start', errorMessage(e))),
  })
  const task = useQuery({
    queryKey: ['task', taskId], queryFn: () => getTask(taskId!), enabled: !!taskId && step === 'working',
    refetchInterval: (q) => (q.state.data?.status === 'running' ? 1500 : false),
  })
  // The task list lives in server memory, so after a restart the task is gone (404): stop waiting and say where to look.
  const lost = task.isError && !task.isFetching
  useEffect(() => {
    const t = task.data
    if (!t || t.status === 'running') return
    if (t.status === 'ok') {
      const r = t.result as DirectApplyResult
      setAppId(r.application_id)
      setStep('review')
      qc.invalidateQueries({ queryKey: ['jobs'] }); qc.invalidateQueries({ queryKey: ['today'] })
    }
  }, [task.data, qc])

  const app = useQuery({ queryKey: ['application', appId], queryFn: () => getApplication(appId!), enabled: !!appId && step === 'review' })
  const a = app.data
  const missing = a?.unanswered ?? []
  const allAnswered = missing.every((q) => (extra[q] ?? '').trim())

  const submit = useMutation({
    mutationFn: async () => {
      if (missing.length) {
        await patchApplication(a!.id, { answers: { ...(a!.answers ?? {}), ...Object.fromEntries(missing.map((q) => [q, extra[q].trim()])) } })
        for (const q of missing) if (remember[q]) await addCustomAnswer(q, extra[q].trim())
      }
      return submitApplication(a!.id)
    },
    onSuccess: () => { setStep('sent'); qc.invalidateQueries({ queryKey: ['tasks'] }); qc.invalidateQueries({ queryKey: ['today'] }) },
    onError: (e) => toast.error('Could not submit', errorMessage(e)),
  })

  if (!job) return null
  const working = step === 'working'
  const ended = task.data?.status === 'error' || task.data?.status === 'cancelled' || lost
  return (
    <div className="fixed inset-0 z-[90] flex items-start justify-center overflow-y-auto bg-black/45 px-4 py-16" onMouseDown={onClose}>
      <div ref={ref} role="dialog" aria-modal aria-labelledby="apply-title" tabIndex={-1} className="card w-full max-w-[580px] p-6 shadow-[var(--shadow)] outline-none" onMouseDown={(e) => e.stopPropagation()}>
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <h2 id="apply-title" className="text-[19px] font-extrabold leading-snug">Apply to {job.title}</h2>
            <div className="mt-1 text-[13px] text-ink-2">{job.company_name}{job.location ? ` · ${job.location}` : ''} · {job.apply_method === 'autofill' ? 'form can be auto-filled' : job.apply_method === 'manual' ? 'you apply on the site' : 'opens the job site'}</div>
          </div>
          <button type="button" aria-label="Close" onClick={onClose} className="rounded-lg bg-surface-2 p-2 text-ink-2 hover:text-ink"><X size={16} /></button>
        </div>

        {step === 'choose' && (
          <div className="mt-5 flex flex-col gap-2.5">
            {usable.length > 1 && (
              <label className="mb-1 flex flex-wrap items-center gap-2 text-[13px]">
                <span className="font-semibold">Resume</span>
                <select className="input !h-9 min-w-0 flex-1" value={resumeId ?? autoResume} aria-label="Resume to apply with"
                  onChange={(e) => setResumeId(Number(e.target.value))}>
                  {usable.map((r) => <option key={r.id} value={r.id}>{r.name}{r.id === autoResume ? ' (this job’s profile)' : ''}</option>)}
                </select>
              </label>
            )}
            <button type="button" onClick={() => start.mutate('ai')} disabled={start.isPending}
              className="rounded-xl border-2 border-[var(--accent)] p-4 text-left transition-colors hover:bg-[color-mix(in_oklab,var(--accent)_8%,transparent)]" style={{ background: 'color-mix(in oklab, var(--accent) 5%, transparent)' }}>
              <span className="flex items-center justify-between gap-2"><span className="flex items-center gap-2 text-[15px] font-bold"><Sparkles size={16} />Check fit and draft answers</span><span className="text-xs font-semibold text-accent-ink">Recommended · {job.fit_score === null ? '2–3' : '1–2'} AI calls</span></span>
              <span className="mt-1 block text-[13px] leading-relaxed text-ink-2">{job.fit_score === null ? 'Scores the job, ' : ''}writes a cover letter if it is a strong match, and maps your answers to the form. Nothing is sent yet.</span>
            </button>
            <button type="button" onClick={() => start.mutate('direct')} disabled={start.isPending}
              className="rounded-xl border border-[var(--baseline)] bg-surface p-4 text-left transition-colors hover:bg-surface-2">
              <span className="flex items-center justify-between gap-2"><span className="flex items-center gap-2 text-[15px] font-bold"><Zap size={16} />Skip AI, fill from my answers</span><span className="text-xs font-semibold text-ink-2">1 AI call for the form</span></span>
              <span className="mt-1 block text-[13px] leading-relaxed text-ink-2">No fit check and no cover letter. Fastest when you already know you want it.</span>
            </button>
          </div>
        )}

        {working && (
          <div className="mt-5 flex flex-col gap-3">
            {ended ? (
              <>
                <div className={`text-sm font-semibold ${task.data?.status === 'error' ? 'text-bad-ink' : 'text-warn-ink'}`}>
                  {lost ? 'Lost track of this run' : task.data?.status === 'cancelled' ? 'Stopped before the application was ready' : 'Could not get the application ready'}
                </div>
                <div className="text-[13px] text-ink-2">
                  {lost ? <>The server may have restarted. Nothing was submitted. Anything it prepared is under <Link to="/applications?status=all">Applications</Link>.</>
                    : task.data?.status === 'cancelled' ? <>Nothing was submitted. Anything it prepared is under <Link to="/applications?status=all">Applications</Link>.</>
                      : task.data?.error}
                </div>
                <div className="flex justify-end"><Button onClick={onClose}>Close</Button></div>
              </>
            ) : (
              <>
                <div className="flex items-center gap-2 text-sm font-semibold"><Loader2 size={16} className="spin text-accent-ink" />Getting the application ready… nothing is submitted</div>
                <LogView lines={task.data?.log_tail ?? []} maxHeight={150} />
                <p className="text-xs text-ink-2">This usually takes under a minute: it opens the form in a hidden browser, fills it and takes a screenshot.
                  You can close this window: it keeps running in the background and the result appears under <Link to="/applications?status=all">Applications</Link>.</p>
              </>
            )}
          </div>
        )}

        {step === 'review' && (
          <div className="mt-5 flex flex-col gap-4">
            {!a ? <div className="flex justify-center py-6"><Loader2 className="spin text-muted" /></div> : a.method === 'manual' ? (
              <>
                <p className="text-sm text-ink-2">This site needs you to apply yourself. Your cover letter and answers are ready to copy.</p>
                <div className="flex flex-wrap gap-2">
                  <a href={a.job.apply_url || a.job.url} target="_blank" rel="noreferrer" className="inline-flex h-10 items-center gap-1.5 rounded-[9px] bg-accent px-4 text-sm font-semibold text-on-accent no-underline"><ExternalLink size={15} />Open the job site</a>
                  {a.cover_letter && <CopyButton text={a.cover_letter} label="Copy cover letter" />}
                  <Link to={`/applications/${a.id}`} className="inline-flex h-8 items-center text-sm font-semibold">All prepared answers →</Link>
                </div>
              </>
            ) : (
              <>
                <div className="flex items-center gap-3">
                  <FitBadge score={a.job.fit_score} />
                  <div className="text-sm text-ink-2">{a.job.fit?.one_liner ?? 'Filled from your answer bank. No fit check was made.'}</div>
                </div>
                <dl className="grid grid-cols-[150px_1fr] gap-x-3 gap-y-2 rounded-[10px] bg-surface-2 p-3.5 text-sm">
                  <dt className="text-ink-2">Cover letter</dt>
                  <dd>{a.cover_letter ? <Link to={`/applications/${a.id}`}>Drafted · {a.cover_letter.split(/\s+/).length} words · edit</Link> : 'None'}</dd>
                  <dt className="text-ink-2">Form</dt>
                  <dd>{a.form_plan ? `${a.form_plan.filter((f) => f.action !== 'skip').length} fields filled` : 'Not checked yet'}{a.screenshot_path ? <> · <Link to={`/applications/${a.id}`}>see screenshot</Link></> : null}</dd>
                  {a.error && <><dt className="text-bad-ink">Problem</dt><dd className="text-bad-ink">{a.error}</dd></>}
                </dl>
                {missing.length > 0 && (
                  <div className="flex flex-col gap-3">
                    <div className="text-sm font-semibold text-warn-ink">{missing.length} question{missing.length > 1 ? 's are' : ' is'} not in your answers. Fill {missing.length > 1 ? 'them' : 'it'} in to submit; nothing is guessed.</div>
                    {missing.map((q) => (
                      <div key={q} className="flex flex-col gap-1.5">
                        <label className="text-[13px] font-semibold" htmlFor={`ans-${q}`}>{q.replace(/\s*\*$/, '')}</label>
                        <input id={`ans-${q}`} className="input" value={extra[q] ?? ''} onChange={(e) => setExtra({ ...extra, [q]: e.target.value })} />
                        <label className="flex items-center gap-2 text-xs text-ink-2">
                          <input type="checkbox" className="accent-[var(--accent)]" checked={!!remember[q]} onChange={(e) => setRemember({ ...remember, [q]: e.target.checked })} />
                          Save to my answers for next time
                        </label>
                      </div>
                    ))}
                  </div>
                )}
                <div className="flex flex-wrap justify-end gap-2">
                  <Button variant="outline" onClick={onClose}>Save for later</Button>
                  <Button variant="primary" onClick={() => submit.mutate()} loading={submit.isPending} disabled={!allAnswered}>Submit application</Button>
                </div>
              </>
            )}
          </div>
        )}

        {step === 'sent' && (
          <div className="mt-5 flex flex-col items-start gap-3">
            <div className="flex items-center gap-2 text-[15px] font-bold text-good-ink"><CheckCircle2 size={18} />Submitting in the background</div>
            <p className="text-sm leading-relaxed text-ink-2">The form is filled in a hidden browser and a screenshot is saved. If the site asks something new, the application comes back to Today for you.</p>
            <Button variant="primary" onClick={onClose}>Done</Button>
          </div>
        )}
      </div>
    </div>
  )
}
