import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, LogIn } from 'lucide-react'
import { clsx } from 'clsx'
import { applyPlan, applySourcePreset, browserLogin, getContactSuggestions, getSchedule, getSettings, getSourcePresets, putAnswerBank, putRuntime } from '../api'
import type { AnswerBank } from '../types'
import { useToast } from '../lib/toast'
import { errorMessage } from '../lib/tasks'
import { Button, Spinner } from '../components/ui'
import ResumeCard from '../components/ResumeCard'
import ProfileTabs from '../components/ProfileTabs'

const STEPS = ['Resume', 'Profiles', 'Your answers', 'Sources', 'Schedule']

// Applying a plan sets Analyze to 30 jobs per run (backend scheduler.PLANS).
const PLAN_LIMIT = 30

export default function Setup() {
  const [step, setStep] = useState(0)
  const nav = useNavigate()
  const qc = useQueryClient()
  const toast = useToast()
  const [plan, setPlan] = useState<'light' | 'active' | 'manual'>('light')
  const settings = useQuery({ queryKey: ['settings'], queryFn: getSettings })
  const schedule = useQuery({ queryKey: ['schedule'], queryFn: getSchedule })
  // The answers draft lives here so it survives switching steps; it is saved whenever the answers step is left.
  const [bank, setBank] = useState<AnswerBank | null>(null)
  const savedBank = useRef<string | null>(null)
  useEffect(() => {
    if (settings.data && !bank) { setBank(settings.data.answer_bank); savedBank.current = JSON.stringify(settings.data.answer_bank) }
  }, [settings.data, bank])
  const saveBank = async () => {
    if (!bank || JSON.stringify(bank) === savedBank.current) return
    const full = (bank.identity.full_name ?? '').trim()
    const identity = { ...bank.identity }
    if (full && !identity.first_name && !identity.last_name && full.includes(' ')) {   // derived from what you typed, not guessed
      identity.first_name = full.split(/\s+/)[0]
      identity.last_name = full.split(/\s+/).slice(1).join(' ')
    }
    const saved = await putAnswerBank({ ...bank, identity })
    setBank(saved); savedBank.current = JSON.stringify(saved)
    qc.invalidateQueries({ queryKey: ['settings'] }); qc.invalidateQueries({ queryKey: ['today'] })
  }
  // Leaving Setup some other way (sidebar, a link) while on the answers step still keeps what was typed.
  const onLeave = useRef<() => void>(() => {})
  useEffect(() => { onLeave.current = () => { if (step === 2) saveBank().catch((e) => toast.error('Could not save your answers', errorMessage(e))) } })
  useEffect(() => () => onLeave.current(), [])
  const go = useMutation({
    mutationFn: async (to: number | 'today') => { if (step === 2) await saveBank(); return to },
    onSuccess: (to) => (to === 'today' ? nav('/') : setStep(to)),
    onError: (e) => toast.error('Could not save your answers', errorMessage(e)),
  })
  const finish = useMutation({
    mutationFn: async () => { await applyPlan(plan); await putRuntime({ 'setup.completed': true }) },
    onSuccess: () => { qc.invalidateQueries(); toast.success('All set', plan === 'manual' ? 'Nothing runs on its own. Use Run now when you want.' : 'Your schedule is on.'); nav('/') },
    onError: (e) => toast.error('Could not finish', errorMessage(e)),
  })
  const collectAi = schedule.data?.collect_ai_per_run ?? 0
  const weekly = (analyzeDays: number, letters: number) => {
    const n = 7 * collectAi + analyzeDays * PLAN_LIMIT + letters
    return `About ${n} AI calls a week${collectAi ? `, ${7 * collectAi} of them reading job sites` : ''}`
  }

  return (
    <div className="mx-auto flex max-w-[940px] flex-col gap-5">
      <header className="flex flex-wrap items-center gap-3">
        <div>
          <h2 className="page-title">Set up JobPilot</h2>
          <p className="mt-1 text-sm text-ink-2">About 10 minutes. You can change anything later.</p>
        </div>
        <Link to="/" className="ml-auto text-sm font-semibold" onClick={(e) => { if (step === 2) { e.preventDefault(); go.mutate('today') } }}>Skip to Today</Link>
      </header>

      <ol aria-label="Steps" className="grid gap-2" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))' }}>
        {STEPS.map((label, i) => {
          const cur = i === step
          const done = i < step
          return (
            <li key={label}>
              <button type="button" onClick={() => i !== step && go.mutate(i)} disabled={go.isPending} aria-current={cur ? 'step' : undefined}
                className={clsx('flex h-12 w-full items-center gap-2.5 rounded-[10px] border bg-surface px-3 text-left text-sm font-semibold disabled:cursor-wait',
                  cur ? 'border-[var(--accent)] text-accent-ink' : done ? 'border-line text-ink' : 'border-line text-ink-2')}>
                <span className={clsx('flex h-[26px] w-[26px] shrink-0 items-center justify-center rounded-full text-[13px]',
                  cur ? 'bg-accent text-on-accent' : done ? 'text-good-ink' : 'bg-surface-2 text-ink-2')}
                  style={done ? { background: 'color-mix(in oklab, var(--good) 16%, transparent)' } : undefined}>{done ? <Check size={14} /> : i + 1}</span>
                {label}
              </button>
            </li>
          )
        })}
      </ol>

      <section className="card flex flex-col gap-5 p-6 md:p-7">
        {step === 0 && (
          <>
            <StepHead title="Your resume" text="JobPilot scores every job against it and uploads the file with your applications." />
            <ResumeCard compact />
          </>
        )}
        {step === 1 && (
          <>
            <StepHead title="Search profiles" text="Each profile is one kind of job you want. Start from your resume, then adjust titles, places and keywords." />
            <ProfileTabs />
          </>
        )}
        {step === 2 && (bank ? <AnswersStep bank={bank} setBank={setBank} />
          : settings.isError ? <p className="text-sm text-bad-ink">{errorMessage(settings.error)}</p> : <div className="flex justify-center py-8"><Spinner /></div>)}
        {step === 3 && <SourcesStep />}
        {step === 4 && (
          <>
            <StepHead title="How often should it run?" text="Start with a plan; fine-tune days and times on the Schedule page." />
            <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(230px, 1fr))' }}>
              {([
                ['light', 'Light (recommended)', 'Collect jobs every day at 8:00 AM.\nAnalyze and draft on Monday and Thursday.', weekly(2, 15)],
                ['active', 'Active', 'Collect jobs every day at 8:00 AM.\nAnalyze and draft every weekday.', weekly(5, 30)],
                ['manual', 'Only when I press Run', 'Nothing runs on its own.\nUse Run now whenever you want.', 'Only what you run'],
              ] as const).map(([id, name, desc, cost]) => (
                <OptionCard key={id} on={plan === id} onClick={() => setPlan(id)} title={name} desc={desc} foot={cost} />
              ))}
            </div>
          </>
        )}

        <div className="flex flex-wrap gap-2.5 border-t border-line pt-5">
          {step > 0 && <Button variant="outline" size="lg" onClick={() => go.mutate(step - 1)} disabled={go.isPending}>Back</Button>}
          {step < STEPS.length - 1
            ? <Button variant="primary" size="lg" className="ml-auto" onClick={() => go.mutate(step + 1)} loading={go.isPending}>Continue</Button>
            : <Button variant="primary" size="lg" className="ml-auto" onClick={() => finish.mutate()} loading={finish.isPending}>Finish and go to Today</Button>}
        </div>
      </section>
    </div>
  )
}

function StepHead({ title, text }: { title: string; text: string }) {
  return (
    <div>
      <h3 className="text-[21px] font-extrabold tracking-tight">{title}</h3>
      <p className="mt-1.5 text-sm leading-relaxed text-ink-2">{text}</p>
    </div>
  )
}

function OptionCard({ on, onClick, title, desc, foot }: { on: boolean; onClick: () => void; title: string; desc: string; foot: string }) {
  return (
    <button type="button" aria-pressed={on} onClick={onClick}
      className={clsx('rounded-xl p-4 text-left transition-colors', on ? 'border-2 border-[var(--accent)]' : 'border border-[var(--baseline)] bg-surface hover:bg-surface-2')}
      style={on ? { background: 'color-mix(in oklab, var(--accent) 6%, transparent)' } : undefined}>
      <span className="block text-[15px] font-bold">{title}</span>
      <span className="mt-1.5 block whitespace-pre-line text-[13px] leading-relaxed text-ink-2">{desc}</span>
      <span className="mt-2.5 block text-xs font-semibold text-accent-ink">{foot}</span>
    </button>
  )
}

type Key = { section: 'identity' | 'eligibility'; key: string; label: string; type?: string; placeholder?: string; options?: string[]; hint?: string }
const KEYS: Key[] = [
  { section: 'identity', key: 'full_name', label: 'Full name' },
  { section: 'identity', key: 'email', label: 'Email', type: 'email' },
  { section: 'identity', key: 'phone', label: 'Phone, with country code', type: 'tel', placeholder: '+1 555 010 0000' },
  { section: 'identity', key: 'current_location', label: 'Current city', placeholder: 'City, Country' },
  { section: 'eligibility', key: 'work_authorization', label: 'Work authorization', placeholder: 'Citizen, authorized to work in <country>' },
  { section: 'eligibility', key: 'needs_visa_sponsorship', label: 'Need visa sponsorship?', options: ['', 'no', 'yes'] },
  { section: 'eligibility', key: 'notice_period', label: 'Notice period', placeholder: 'e.g. 30 days or immediate' },
  { section: 'eligibility', key: 'years_of_experience', label: 'Years of experience', placeholder: 'e.g. 2' },
  { section: 'eligibility', key: 'expected_compensation', label: 'Expected salary', hint: 'Optional. Blank means you are asked each time.' },
  { section: 'identity', key: 'linkedin_url', label: 'LinkedIn URL', type: 'url' },
  { section: 'identity', key: 'github_url', label: 'GitHub URL', type: 'url' },
]

function AnswersStep({ bank, setBank }: { bank: AnswerBank; setBank: (b: AnswerBank) => void }) {
  const toast = useToast()
  const fromResume = useMutation({
    mutationFn: getContactSuggestions,
    onSuccess: (sugg) => {
      let n = 0
      const fill = (section: Record<string, string>) => {
        const out = { ...section }
        for (const [k, v] of Object.entries(sugg)) if (k in out && !(out[k] ?? '').trim()) { out[k] = v; n++ }
        return out
      }
      setBank({ ...bank, identity: fill(bank.identity), eligibility: fill(bank.eligibility) })
      if (n) toast.success(`${n} answer${n === 1 ? '' : 's'} filled from your resume`, 'Check them; they are saved when you leave this step.')
      else toast.info('Nothing new to fill', Object.keys(sugg).length ? 'Every answer your resume covers is already filled.' : 'No contact details were read from your resume yet. Upload and analyze it first.')
    },
    onError: (e) => toast.error('Could not read your resume details', errorMessage(e)),
  })
  const set = (k: Key, v: string) => setBank({ ...bank, [k.section]: { ...bank[k.section], [k.key]: v } })
  return (
    <>
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-[260px] flex-1"><StepHead title="Your answers for application forms" text="Only these answers are ever typed into forms. Anything left blank is never guessed: the application waits and asks you." /></div>
        <Button variant="outline" onClick={() => fromResume.mutate()} loading={fromResume.isPending}>Fill empty ones from my resume</Button>
      </div>
      <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))' }}>
        {KEYS.map((k) => {
          const cur = bank[k.section][k.key] ?? ''
          // Saved answers may be typed freely in Settings ("Yes", "No, not now"): match case-insensitively, keep anything else.
          const match = k.options?.find((o) => o && o === cur.trim().toLowerCase())
          return (
            <label key={k.key} className="flex flex-col gap-1.5 text-[13px] font-semibold">
              {k.label}
              {k.options ? (
                <select className="input font-normal" value={match ?? cur} onChange={(e) => set(k, e.target.value)}>
                  {k.options.map((o) => <option key={o} value={o}>{o === '' ? 'Choose…' : o === 'no' ? 'No' : 'Yes'}</option>)}
                  {cur.trim() && !match && <option value={cur}>{cur}</option>}
                </select>
              ) : (
                <input className="input font-normal" type={k.type ?? 'text'} placeholder={k.placeholder} value={cur} onChange={(e) => set(k, e.target.value)} />
              )}
              {k.hint && <span className="text-xs font-normal text-ink-2">{k.hint}</span>}
            </label>
          )
        })}
      </div>
      <p className="text-[13px] text-ink-2">More fields and your own questions are in <Link to="/settings?tab=answers">Settings › Your answers</Link>. Saved when you leave this step.</p>
    </>
  )
}

const SIGN_IN: Array<[string, string, string]> = [
  ['naukri', 'Naukri', 'more results when signed in'],
  ['site_instahyre', 'Instahyre', 'listings need an account'],
  ['site_wellfound', 'Wellfound', 'one-click apply after signing in'],
  ['indeed', 'Indeed', 'its terms forbid automated reading; stays off unless you turn it on'],
]

function SourcesStep() {
  const qc = useQueryClient()
  const toast = useToast()
  const presets = useQuery({ queryKey: ['source-presets'], queryFn: getSourcePresets })
  const use = useMutation({
    mutationFn: (id: string) => applySourcePreset(id),
    onSuccess: (r) => { qc.setQueryData(['source-presets'], r); qc.invalidateQueries({ queryKey: ['settings'] }); qc.invalidateQueries({ queryKey: ['sources'] }) },
    onError: (e) => toast.error('Could not apply', errorMessage(e)),
  })
  const login = useMutation({
    mutationFn: (site: string) => browserLogin(site),
    onSuccess: (r) => toast.success('A browser window opened on your Mac', `${r.url}: sign in, then close the window.`),
    onError: (e) => toast.error('Could not open the browser', errorMessage(e)),
  })
  return (
    <>
      <StepHead title="Where to look" text="Pick a starting set. You can switch single sources on or off later under Settings." />
      {presets.isLoading ? <Spinner /> : (
        <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))' }}>
          {presets.data?.map((p) => (
            <OptionCard key={p.id} on={p.active} onClick={() => use.mutate(p.id)} title={p.name} desc={p.desc} foot={`${p.count} sources`} />
          ))}
          <OptionCard on={!presets.data?.some((p) => p.active)} onClick={() => toast.info('Custom', 'Choose each source under Settings › Sources.')} title="Custom" desc="Choose every source yourself." foot="Pick in Settings" />
        </div>
      )}
      <div className="overflow-hidden rounded-xl border border-line">
        <div className="bg-surface-2 px-4 py-3 text-[13px] font-semibold">Sites that work better after you sign in once</div>
        {SIGN_IN.map(([key, name, note]) => (
          <div key={key} className="flex flex-wrap items-center gap-2.5 border-t border-line px-4 py-3 text-sm">
            <span className="min-w-[200px] flex-1">{name} <span className={clsx('text-[13px]', key === 'indeed' ? 'text-warn-ink' : 'text-ink-2')}>· {note}</span></span>
            <Button size="sm" variant="outline" icon={LogIn} onClick={() => login.mutate(key)} loading={login.isPending && login.variables === key}>Sign in</Button>
          </div>
        ))}
      </div>
    </>
  )
}
