import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Ban, ExternalLink, FileText, RotateCcw, Sparkles, Star } from 'lucide-react'
import { ApiError, getJob, getSchedule, patchJob, prepareJob, scoreJob, setJobStatus } from '../api'
import { useToast } from '../lib/toast'
import { errorMessage } from '../lib/tasks'
import { fmtDateTime, fmtRelative, hostOf, titleCase } from '../lib/format'
import { Button, Chip, Dialog, Drawer, KV, SectionTitle } from './ui'
import { AppStatusChip, FitBadge, JobStatusChip, SourceChip, TrustChip, fitTone } from './status'

export default function JobDrawer({ jobId, onClose }: { jobId: number | null; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const nav = useNavigate()
  const job = useQuery({ queryKey: ['job', jobId], queryFn: () => getJob(jobId!), enabled: jobId !== null })
  const schedule = useQuery({ queryKey: ['schedule'], queryFn: getSchedule, staleTime: 60_000, enabled: jobId !== null })
  const minFit = schedule.data?.prepare.min_fit ?? 75
  const [notes, setNotes] = useState('')
  const [confirmPrepare, setConfirmPrepare] = useState(false)
  useEffect(() => setConfirmPrepare(false), [jobId])
  useEffect(() => setNotes(job.data?.notes ?? ''), [job.data?.id, job.data?.notes])

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['job', jobId] })
    qc.invalidateQueries({ queryKey: ['jobs'] })
    qc.invalidateQueries({ queryKey: ['stats'] })
  }
  const status = useMutation({
    mutationFn: (s: string) => setJobStatus(jobId!, s),
    onSuccess: (_d, s) => { toast.success(`Marked as ${titleCase(s)}`); refresh() },
    onError: (e) => toast.error('Update failed', errorMessage(e)),
  })
  const score = useMutation({
    mutationFn: () => scoreJob(jobId!),
    onSuccess: (j) => { toast.success(`Scored ${j.fit_score}/100`, j.fit?.one_liner); refresh() },
    onError: (e) => toast.error('Scoring failed', errorMessage(e)),
  })
  const prepare = useMutation({
    mutationFn: () => prepareJob(jobId!, !!job.data?.application_id),
    onSuccess: (a) => {
      setConfirmPrepare(false)
      toast.success(job.data?.application_id ? 'Application prepared again' : 'Application prepared',
        a.cover_letter ? 'Review the cover letter and answers before submitting.' : `Your answers are ready. Cover letters are drafted only for fit ${minFit} or higher; you can still ask for one on the application.`)
      refresh(); qc.invalidateQueries({ queryKey: ['applications'] }); qc.invalidateQueries({ queryKey: ['application', a.id] }); nav(`/applications/${a.id}`)
    },
    onError: (e) => {
      setConfirmPrepare(false)
      if (e instanceof ApiError && e.status === 409) toast.info('Already sent', e.message)
      else toast.error('Could not prepare', errorMessage(e))
    },
  })
  const saveNotes = useMutation({
    mutationFn: () => patchJob(jobId!, { notes }),
    onSuccess: () => { toast.success('Notes saved'); refresh() },
    onError: (e) => toast.error('Save failed', errorMessage(e)),
  })

  const j = job.data
  const open = jobId !== null
  const strong = j?.fit_score != null && j.fit_score >= minFit
  const coverNote = strong ? 'Drafts a cover letter with the AI (1 call)' : `No cover letter: those are drafted only for fit ${minFit} or higher`
  const canPrepare = j && j.status !== 'applied' && j.application_status !== 'submitting' && j.application_status !== 'submitted'
  return (
    <>
    <Drawer open={open} onClose={onClose} width={760}
      title={j ? <span className="flex items-center gap-2"><SourceChip source={j.source} /><span className="truncate">{j.company_name}</span></span> : 'Job'}
      actions={j && <a href={j.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs no-underline hover:underline"><ExternalLink size={13} /> Open posting</a>}>
      {job.isLoading && <div className="p-6 text-sm text-muted">Loading…</div>}
      {job.isError && <div className="p-6 text-sm text-bad-ink">{errorMessage(job.error)}</div>}
      {j && (
        <div className="flex flex-col gap-6 p-5">
          <div className="flex items-start gap-4">
            <FitBadge score={j.fit_score} size="lg" />
            <div className="min-w-0 flex-1">
              <h2 className="text-lg font-semibold leading-tight">{j.title}</h2>
              <div className="mt-1 text-sm text-ink-2">
                {j.company_name}{j.location ? ` · ${j.location}` : ''}{j.remote && !/remote/i.test(j.location ?? '') ? ' · Remote' : j.remote === false ? ' · Onsite/hybrid' : ''}
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-1.5">
                <JobStatusChip status={j.status} />
                {j.application_status && <AppStatusChip status={j.application_status} />}
                <TrustChip score={j.trust_score} />
                {j.fit && <Chip tone={fitTone(j.fit_score).tone}>{fitTone(j.fit_score).label} · verdict {j.fit.verdict}</Chip>}
                {j.employment_type && <Chip>{j.employment_type}</Chip>}
                {j.salary_text && <Chip tone="aqua">{j.salary_text}</Chip>}
                {(j.tags ?? []).map((t) => <Chip key={t} tone="muted">{t}</Chip>)}
              </div>
            </div>
          </div>

          <div className="flex flex-wrap gap-2">
            {!j.application_id && j.status !== 'shortlisted' && j.status !== 'applied' && <Button icon={Star} onClick={() => status.mutate('shortlisted')} loading={status.isPending}>Shortlist</Button>}
            {j.status !== 'rejected' && <Button icon={Ban} onClick={() => status.mutate('rejected')} loading={status.isPending}>Not interested</Button>}
            <Button icon={Sparkles} onClick={() => score.mutate()} loading={score.isPending} title="Uses one AI call">{j.fit_score === null ? 'Score now' : 'Re-score'}</Button>
            {canPrepare && (
              <Button variant="primary" icon={FileText} onClick={() => (j.application_id ? setConfirmPrepare(true) : prepare.mutate())} loading={prepare.isPending}
                title={`${j.application_id ? 'Refreshes your answers' : 'Gathers your answers for the form'}. ${coverNote}.`}>
                {j.application_id ? 'Re-prepare application' : 'Prepare application'}
              </Button>
            )}
            {j.application_id && <Button variant="outline" onClick={() => nav(`/applications/${j.application_id}`)}>Open application</Button>}
            {!j.application_id && (j.status === 'filtered_out' || j.status === 'expired' || j.status === 'rejected') && <Button variant="ghost" icon={RotateCcw} onClick={() => status.mutate('queued')} loading={status.isPending}>Re-queue for scoring</Button>}
          </div>

          {j.fit ? (
            <section>
              <SectionTitle>AI assessment</SectionTitle>
              <p className="text-sm">{j.fit.one_liner}</p>
              <div className="mt-3 grid gap-4 md:grid-cols-2">
                <div>
                  <div className="mb-1 text-xs font-medium text-good-ink">Strengths</div>
                  <ul className="list-disc space-y-0.5 pl-4 text-sm">{j.fit.strengths.map((s, i) => <li key={i}>{s}</li>)}</ul>
                </div>
                <div>
                  <div className="mb-1 text-xs font-medium text-serious-ink">Gaps</div>
                  <ul className="list-disc space-y-0.5 pl-4 text-sm">{j.fit.gaps.length ? j.fit.gaps.map((s, i) => <li key={i}>{s}</li>) : <li className="text-muted">None noted</li>}</ul>
                </div>
              </div>
              {j.fit.pitch && (
                <div className="mt-3 rounded-lg border border-line bg-surface-2 p-3 text-sm">
                  <div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-muted">Suggested pitch</div>
                  {j.fit.pitch}
                </div>
              )}
              <div className="mt-3">
                <KV rows={[
                  ['Seniority', SENIORITY[j.fit.seniority_match] ?? titleCase(j.fit.seniority_match)],
                  ['Location', LOCATION[j.fit.location_match] ?? titleCase(j.fit.location_match)],
                  ['Salary note', j.fit.salary_note || null],
                  ['Scored', j.scored_at ? fmtDateTime(j.scored_at) : null],
                ]} />
              </div>
            </section>
          ) : (
            <section className="rounded-lg border border-dashed border-line p-3 text-sm text-ink-2">
              Not scored yet. {j.status === 'queued' ? 'It is in the scoring queue.' : j.status === 'filtered_out' ? 'The prefilter dropped it; use Re-queue to score it anyway.' : 'Use Score now to assess it with the AI.'}
            </section>
          )}

          <section>
            <SectionTitle>Genuineness</SectionTitle>
            <div className="flex flex-wrap items-center gap-1.5 text-sm">
              <TrustChip score={j.trust_score} />
              {(j.trust_flags ?? []).length ? (j.trust_flags ?? []).map((f, i) => <Chip key={i} tone={/ATS|company/i.test(f) ? 'good' : 'serious'}>{f}</Chip>) : <span className="text-xs text-muted">No flags</span>}
              {j.fit && <span className="text-xs text-muted">· AI confidence {j.fit.legit_confidence}%</span>}
            </div>
          </section>

          <section>
            <SectionTitle>Prefilter</SectionTitle>
            <div className="flex flex-wrap items-center gap-1.5">
              <Chip tone={j.prefilter_score !== null && j.prefilter_score >= 30 ? 'accent' : 'muted'}>score {j.prefilter_score ?? '—'}</Chip>
              {(j.prefilter_reasons ?? []).map((r, i) => <Chip key={i} tone="neutral">{r}</Chip>)}
            </div>
          </section>

          <section>
            <SectionTitle>Details</SectionTitle>
            <KV rows={[
              ['Posted', j.posted_at ? `${fmtDateTime(j.posted_at)} (${fmtRelative(j.posted_at)})` : null],
              ['Found', `${fmtDateTime(j.discovered_at)} via ${j.source}`],
              ['Last seen', fmtRelative(j.last_seen_at)],
              ['Apply link', j.apply_url ? <a href={j.apply_url} target="_blank" rel="noreferrer">{hostOf(j.apply_url)} <ExternalLink size={11} className="inline" /></a> : null],
              ['Company', j.company ? <span>{j.company.name} · {j.company.ats_type}{j.company.website ? <> · <a href={j.company.website} target="_blank" rel="noreferrer">{hostOf(j.company.website)}</a></> : null}</span> : null],
              ['Duplicate of', j.duplicate_of ? `#${j.duplicate_of}` : null],
            ]} />
          </section>

          <section>
            <SectionTitle right={<Button size="sm" variant="outline" onClick={() => saveNotes.mutate()} loading={saveNotes.isPending} disabled={notes === (j.notes ?? '')}>Save notes</Button>}>Your notes</SectionTitle>
            <textarea className="input" rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Anything you want to remember about this role" />
          </section>

          <section>
            <SectionTitle>Description</SectionTitle>
            {j.description ? <div className="prewrap rounded-lg border border-line bg-surface p-4 text-sm leading-6">{j.description}</div>
              : <div className="text-sm text-muted">No description captured. Open the posting to read it.</div>}
          </section>
        </div>
      )}
    </Drawer>
    <Dialog open={confirmPrepare && !!j} onClose={() => setConfirmPrepare(false)} title="Prepare this application again?"
      footer={<><Button variant="ghost" onClick={() => setConfirmPrepare(false)}>Cancel</Button>
        <Button variant="primary" icon={FileText} onClick={() => prepare.mutate()} loading={prepare.isPending}>Prepare again</Button></>}>
      <ul className="flex list-disc flex-col gap-1.5 pl-4">
        <li>Answers that come from <strong>Your answers</strong> in Settings are refreshed with what is saved there now.</li>
        <li>Answers you typed for this application are kept.</li>
        <li>{strong ? 'A new cover letter is drafted and replaces any current one (1 AI call).'
          : `The cover letter stays as it is. New letters are drafted only for fit ${minFit} or higher${j?.fit_score != null ? `, and this job scored ${j.fit_score}` : ', and this job is not scored yet'}.`}</li>
        {j?.application_status === 'approved' && <li>It goes back to <strong>Needs review</strong>, so you approve it again before anything is sent.</li>}
      </ul>
    </Dialog>
    </>
  )
}

const SENIORITY: Record<string, string> = { under: 'Below the level you want', match: 'Matches your level', over: 'Above your level', unclear: 'Unclear' }
const LOCATION: Record<string, string> = { yes: 'Fits your locations', remote_ok: 'Remote, works for you', no: 'Does not fit your locations', unclear: 'Unclear' }
