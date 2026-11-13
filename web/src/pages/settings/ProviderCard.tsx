import { useEffect, useState } from 'react'
import { useQuery, type UseMutationResult } from '@tanstack/react-query'
import { clsx } from 'clsx'
import { Zap } from 'lucide-react'
import type { ProviderKey, SettingsAll } from '../../types'
import { getLlmModels } from '../../api'
import { Button, Card, Chip, Field, KV } from '../../components/ui'
import { Meter } from '../../components/charts'

/** OpenAI-compatible servers people commonly use. "Other" takes any address. */
const SERVERS: Array<[string, string]> = [
  ['OpenAI', 'https://api.openai.com/v1'],
  ['OpenRouter', 'https://openrouter.ai/api/v1'],
  ['Groq', 'https://api.groq.com/openai/v1'],
  ['DeepSeek', 'https://api.deepseek.com/v1'],
  ['Mistral', 'https://api.mistral.ai/v1'],
  ['LM Studio (this computer)', 'http://localhost:1234/v1'],
]
const KIND: Record<string, { label: string; tone: 'good' | 'warn' | 'muted' }> = {
  plan: { label: 'your subscription', tone: 'good' }, api: { label: 'pay per use', tone: 'warn' }, local: { label: 'free · offline', tone: 'muted' },
}
const MODEL_HINT: Record<ProviderKey, { placeholder: string; options?: string[]; hint: string }> = {
  codex: { placeholder: 'Codex default', hint: 'Leave empty for the model your ChatGPT plan uses by default.' },
  claude: { placeholder: 'Claude Code default', options: ['opus', 'sonnet', 'haiku'], hint: 'Empty, or opus / sonnet / haiku, or a full model id.' },
  openai: { placeholder: 'model id from your provider', hint: 'Pick from the list, or type it exactly as your provider names it.' },
  gemini: { placeholder: 'pick a Gemini model', hint: 'The list comes from Google once your key is in .env. Flash models are faster and cheaper; Pro models think harder.' },
  anthropic: { placeholder: 'claude-opus-5-5', options: ['claude-opus-5-5', 'claude-sonnet-5-5', 'claude-haiku-5-5'], hint: 'Empty = claude-opus-5-5. Sonnet and Haiku cost less per call.' },
  ollama: { placeholder: 'qwen3.5:4b', hint: 'A model you pulled with `ollama pull`.' },
}

type Update = UseMutationResult<unknown, Error, Record<string, unknown>>
type Test = UseMutationResult<{ ok: boolean; reply: string; seconds: number }, Error, void>

/** Which AI JobPilot uses: a CLI signed in with a subscription, an API with a key, or a local model. */
export default function ProviderCard({ settings, update, test }: { settings: SettingsAll; update: Update; test: Test }) {
  const llm = settings.llm
  const b = llm.budget
  // While a new choice saves, show it at once (it is what the settings will say when they come back).
  const pendingProvider = update.isPending ? update.variables?.['llm.provider'] as ProviderKey | undefined : undefined
  const current = pendingProvider ?? llm.provider
  const hint = MODEL_HINT[current]
  const savedModel = String(settings.runtime['llm.model'] ?? '')
  const savedBase = llm.base_url || SERVERS[0][1]
  const [model, setModel] = useState(savedModel)
  const [base, setBase] = useState(savedBase)
  useEffect(() => setModel(savedModel), [savedModel])
  useEffect(() => setBase(savedBase), [savedBase])
  const preset = SERVERS.find(([, url]) => url === base)
  const [custom, setCustom] = useState(!preset)
  useEffect(() => setCustom(!SERVERS.some(([, url]) => url === savedBase)), [savedBase])

  // Another provider: start from its own default model (a model name rarely means anything to the next one).
  const choose = (key: ProviderKey) => key !== llm.provider && update.mutate({ 'llm.provider': key, 'llm.model': '' })
  const saveModel = () => { const m = model.trim(); if (m !== savedModel) update.mutate({ 'llm.model': m }) }
  const saveBase = (url: string) => { const u = url.trim().replace(/\/+$/, ''); if (u && u !== savedBase) update.mutate({ 'llm.base_url': u }) }
  const free = current === 'ollama'
  // The provider's own list (free to ask; needs the key for APIs), plus the usual names when it can't say.
  const listed = useQuery({ queryKey: ['llm-models', llm.provider, llm.base_url], queryFn: getLlmModels, enabled: ['openai', 'gemini', 'anthropic', 'ollama'].includes(llm.provider), staleTime: 300_000 })
  const models = [...new Set([...(listed.data?.models ?? []), ...(hint.options ?? [])])]

  return (
    <Card title={<span className="inline-flex items-center gap-2"><Zap size={16} /> AI provider</span>}
      subtitle="Use the AI you already have. Every provider gets the same prompts with no tools, so job text can't make it act on your computer."
      actions={<Button size="sm" variant="outline" onClick={() => test.mutate()} loading={test.isPending} title="Makes one small AI call">Test connection</Button>}>
      <fieldset className="flex min-w-0 flex-col gap-1.5" disabled={update.isPending}>
        <legend className="sr-only">AI provider</legend>
        {llm.providers.map((p) => (
          <label key={p.key} className={clsx('flex cursor-pointer items-start gap-3 rounded-lg border px-3 py-2.5 transition-colors hover:bg-surface-2',
            p.key === current ? 'border-[var(--accent)] bg-[color-mix(in_oklab,var(--accent)_6%,transparent)]' : 'border-[var(--baseline)]')}>
            <input type="radio" name="ai-provider" className="mt-1 h-4 w-4 shrink-0 accent-[var(--accent)]" checked={p.key === current} onChange={() => choose(p.key)} />
            <span className="min-w-0 flex-1">
              <span className="flex flex-wrap items-center gap-2 text-sm font-semibold">{p.label}<Chip tone={KIND[p.kind].tone}>{KIND[p.kind].label}</Chip></span>
              <span className="block text-xs leading-relaxed text-ink-2">{p.needs}</span>
            </span>
          </label>
        ))}
      </fieldset>

      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        {current === 'openai' && (
          <Field label="Server" className="sm:col-span-2" hint="The key for it goes in .env as JOBAGENT_OPENAI_API_KEY (not needed for LM Studio).">
            <select className="input" aria-label="AI server" value={custom ? 'other' : base}
              onChange={(e) => { if (e.target.value === 'other') setCustom(true); else { setCustom(false); setBase(e.target.value); saveBase(e.target.value) } }}>
              {SERVERS.map(([name, url]) => <option key={url} value={url}>{name}</option>)}
              <option value="other">Other address…</option>
            </select>
            {custom && <input className="input mt-2" aria-label="Server address" placeholder="https://your-server/v1" value={base}
              onChange={(e) => setBase(e.target.value)} onBlur={() => saveBase(base)} onKeyDown={(e) => { if (e.key === 'Enter') e.currentTarget.blur() }} />}
          </Field>
        )}
        <Field label="Model" className="sm:col-span-2" hint={hint.hint}>
          <input className="input" aria-label="AI model" list="ai-models" placeholder={hint.placeholder} value={model}
            onChange={(e) => setModel(e.target.value)} onBlur={saveModel} onKeyDown={(e) => { if (e.key === 'Enter') e.currentTarget.blur() }} />
          <datalist id="ai-models">{models.map((m) => <option key={m} value={m} />)}</datalist>
        </Field>
      </div>

      <div className="mt-4">
        <KV rows={[
          ['Status', llm.primary.ok ? <Chip tone="good" dot>ready</Chip> : <span className="text-bad-ink">{llm.primary.error ?? 'not available'}</span>],
          ...(llm.primary.version ? [['Version', <span className="mono text-xs">{llm.primary.version}</span>] as [string, React.ReactNode]] : []),
          ['Model / effort', `${b.model} / ${b.effort}`],
          ['5h window', free ? 'free: no cap' : <div><span className="num">{b.window_5h.used} / {b.window_5h.max} calls</span><Meter used={b.window_5h.used} max={b.window_5h.max} className="mt-1 w-48" /></div>],
          ['Today', free ? 'free: no cap' : <span className="num">{b.day.used} / {b.day.max} calls</span>],
        ]} />
      </div>
      <div className="mt-3 text-xs text-muted">
        {llm.providers.find((p) => p.key === current)?.kind === 'api'
          ? 'Every call is billed to your API account. The caps (JOBAGENT_LLM_MAX_CALLS_* in .env) stop a run before it spends more.'
          : free ? 'Runs on this computer: free and private. A small model scores less accurately and writes weaker letters.'
            : 'Uses your subscription, which JobPilot shares with your own use. The caps (JOBAGENT_LLM_MAX_CALLS_* in .env) are a safety net below your plan’s own limit.'}
      </div>
    </Card>
  )
}
