import { useEffect, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Cpu } from 'lucide-react'
import { putRuntime, testLlm } from '../../api'
import type { SettingsAll } from '../../types'
import { useToast } from '../../lib/toast'
import { errorMessage } from '../../lib/tasks'
import { Card, Chip, Field, KV, Switch } from '../../components/ui'
import ProviderCard from './ProviderCard'

const PURPOSES: Array<{ key: string; label: string; hint: string }> = [
  { key: 'score', label: 'Scoring jobs', hint: 'fit score and red flags' },
  { key: 'extract', label: 'Reading job pages', hint: 'listings from sites without selectors' },
  { key: 'profile', label: 'Resume analysis', hint: 'one call when you press Analyze' },
  { key: 'cover', label: 'Cover letters', hint: 'a small local model writes noticeably weaker letters' },
  { key: 'form', label: 'Form filling', hint: 'mapping form fields to your answers' },
]

export default function AiSection({ settings }: { settings: SettingsAll }) {
  const qc = useQueryClient()
  const toast = useToast()
  const rt = settings.runtime
  const num = (k: string) => Number(rt[k] ?? settings.runtime_defaults[k] ?? 0)
  const bool = (k: string) => Boolean(rt[k] ?? settings.runtime_defaults[k])
  const list = (k: string) => (rt[k] ?? settings.runtime_defaults[k] ?? []) as string[]
  const env = settings.env
  const ollama = settings.llm.ollama
  const localMain = settings.llm.provider === 'ollama'

  // Stays pending until the settings are fetched again, so the next change starts from fresh values.
  const update = useMutation({
    mutationFn: (body: Record<string, unknown>) => putRuntime(body),
    onSuccess: async () => { toast.success('Saved'); qc.invalidateQueries({ queryKey: ['health'] }); await qc.invalidateQueries({ queryKey: ['settings'] }) },
    onError: (e) => toast.error('Save failed', errorMessage(e)),
  })
  const test = useMutation({
    mutationFn: testLlm,
    onSuccess: (r) => { toast.success(`${settings.llm.label} answered in ${r.seconds}s`, r.reply); qc.invalidateQueries({ queryKey: ['health'] }) },
    onError: (e) => toast.error('AI test failed', errorMessage(e)),
  })

  const fallbackOn = bool('llm.fallback_enabled')
  const pendingPurposes = update.isPending ? (update.variables?.['llm.fallback_purposes'] as string[] | undefined) : undefined
  const purposes = pendingPurposes ?? list('llm.fallback_purposes')      // shows the click at once while it saves
  const minTrust = num('pipeline.min_trust_for_shortlist')
  const [trust, setTrust] = useState(String(minTrust))
  useEffect(() => setTrust(String(minTrust)), [minTrust])
  const saveTrust = () => {
    if (!trust.trim() || Number.isNaN(Number(trust))) { setTrust(String(minTrust)); return }   // blank or not a number: keep the saved value
    const v = Math.min(100, Math.max(0, Math.round(Number(trust))))
    setTrust(String(v))
    if (v !== minTrust) update.mutate({ 'pipeline.min_trust_for_shortlist': v })
  }
  const fbModel = String(rt['llm.fallback_model'] ?? settings.runtime_defaults['llm.fallback_model'] ?? '')

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <div className="flex flex-col gap-4">
        <ProviderCard settings={settings} update={update} test={test} />

        <Card title={<span className="inline-flex items-center gap-2"><Cpu size={16} /> Local fallback (Ollama)</span>}
          subtitle={localMain ? 'Your main AI is already Ollama, so there is nothing to fall back to.' : 'Used only when your main AI hits a limit or is unavailable. Free and private, but a small model is less accurate.'}>
          <div className="flex flex-col gap-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <Switch checked={fallbackOn} onChange={(v) => update.mutate({ 'llm.fallback_enabled': v })} disabled={localMain || (!ollama.running && !fallbackOn)}
                label={<span className="font-medium">{fallbackOn ? 'Fallback on' : 'Fallback off'}</span>} />
              {ollama.running
                ? (ollama.ok ? <Chip tone="good" dot>Ollama ready</Chip> : <Chip tone="warn">{ollama.error}</Chip>)
                : <Chip tone="muted">Ollama not running</Chip>}
            </div>
            <Field label="Model">
              <select className="input" value={fbModel} onChange={(e) => update.mutate({ 'llm.fallback_model': e.target.value })} disabled={!ollama.models.length}>
                {[...new Set([fbModel, ...ollama.models])].filter(Boolean).map((m) => <option key={m} value={m}>{m}</option>)}
              </select>
            </Field>
            <div>
              <div className="mb-2 text-xs font-medium text-ink-2">Allowed for</div>
              <div className="grid gap-2 sm:grid-cols-2">
                {PURPOSES.map((p) => (
                  <label key={p.key} className="flex cursor-pointer items-start gap-2 text-sm">
                    <input type="checkbox" className="mt-0.5" checked={purposes.includes(p.key)} disabled={update.isPending}
                      onChange={(e) => update.mutate({ 'llm.fallback_purposes': e.target.checked ? [...purposes, p.key] : purposes.filter((x) => x !== p.key) })} />
                    <span>{p.label}<span className="block text-xs text-muted">{p.hint}</span></span>
                  </label>
                ))}
              </div>
            </div>
          </div>
        </Card>

        <Card title="Shortlisting" subtitle="Jobs below this genuineness score are never shortlisted, whatever their fit.">
          <Field label="Minimum trust score" hint="0–100. Blends scam heuristics with the AI's judgement.">
            <input className="input !w-[140px]" type="number" min={0} max={100} value={trust} onChange={(e) => setTrust(e.target.value)} onBlur={saveTrust}
              onKeyDown={(e) => { if (e.key === 'Enter') e.currentTarget.blur() }} />
          </Field>
        </Card>
      </div>
      <div className="flex flex-col gap-4">
        <Card title="Environment (read-only)">
          <KV rows={Object.entries(env).map(([k, v]) => [k, <code key={k} className="mono">{Array.isArray(v) ? v.join(', ') : String(v)}</code>])} />
        </Card>
      </div>
    </div>
  )
}
