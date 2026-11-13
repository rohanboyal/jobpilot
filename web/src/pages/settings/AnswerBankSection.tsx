import { useEffect, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2 } from 'lucide-react'
import { putAnswerBank } from '../../api'
import type { AnswerBank } from '../../types'
import { useToast } from '../../lib/toast'
import { errorMessage } from '../../lib/tasks'
import { Button, Card, Field } from '../../components/ui'
import { titleCase } from '../../lib/format'

const HINTS: Record<string, string> = {
  phone: 'Include the country code', needs_visa_sponsorship: 'yes / no', willing_to_relocate: 'yes / no / within my country',
  notice_period: 'e.g. 30 days or immediate', current_compensation: 'Leave blank to always review these questions yourself',
  expected_compensation: 'Leave blank to always review these questions yourself', work_authorization: 'e.g. Citizen, authorized to work in <country>',
}

export default function AnswerBankSection({ initial }: { initial: AnswerBank }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [b, setB] = useState<AnswerBank>(initial)
  useEffect(() => setB(initial), [initial])
  const save = useMutation({
    mutationFn: () => putAnswerBank(b),
    onSuccess: () => { toast.success('Answer bank saved'); qc.invalidateQueries({ queryKey: ['settings'] }) },
    onError: (e) => toast.error('Save failed', errorMessage(e)),
  })
  const dirty = JSON.stringify(b) !== JSON.stringify(initial)
  const section = (name: 'identity' | 'eligibility' | 'preferences', title: string, subtitle: string) => (
    <Card title={title} subtitle={subtitle}>
      <div className="grid gap-3 md:grid-cols-2">
        {Object.entries(b[name]).map(([k, v]) => (
          <Field key={k} label={titleCase(k)} hint={HINTS[k]}>
            <input className="input" value={v} onChange={(e) => setB({ ...b, [name]: { ...b[name], [k]: e.target.value } })} />
          </Field>
        ))}
      </div>
    </Card>
  )
  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-xl border border-line bg-surface-2 px-4 py-3 text-sm text-ink-2">
        These are the only personal facts the agent may type into a form. An empty value means it will <strong>not</strong> answer that question and will flag the application for your review instead. Never put anything here you would not say yourself.
      </div>
      {section('identity', 'Identity & contact', 'Name, contact details and links used on every application.')}
      {section('eligibility', 'Eligibility', 'Work authorization, notice period, compensation. Blank means "ask me".')}
      {section('preferences', 'Preferences', 'Optional details some forms ask for.')}
      <Card title="Custom questions" subtitle="Matched to form questions by meaning, not exact wording."
        actions={<Button size="sm" icon={Plus} onClick={() => setB({ ...b, custom: [...b.custom, { q: '', a: '' }] })}>Add</Button>}>
        <div className="flex flex-col gap-3">
          {b.custom.map((qa, i) => (
            <div key={i} className="grid gap-2 md:grid-cols-[1fr_2fr_auto]">
              <input className="input" value={qa.q} placeholder="Question, e.g. Why do you want to work here?" onChange={(e) => setB({ ...b, custom: b.custom.map((x, xi) => (xi === i ? { ...x, q: e.target.value } : x)) })} />
              <textarea className="input !min-h-[40px]" rows={2} value={qa.a} placeholder="Your answer" onChange={(e) => setB({ ...b, custom: b.custom.map((x, xi) => (xi === i ? { ...x, a: e.target.value } : x)) })} />
              <button className="self-start p-2 text-muted hover:text-bad-ink" onClick={() => setB({ ...b, custom: b.custom.filter((_, xi) => xi !== i) })} aria-label="Remove"><Trash2 size={14} /></button>
            </div>
          ))}
          {!b.custom.length && <div className="text-xs text-muted">No custom answers yet.</div>}
        </div>
      </Card>
      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={() => setB(initial)} disabled={!dirty}>Reset</Button>
        <Button variant="primary" onClick={() => save.mutate()} loading={save.isPending} disabled={!dirty}>Save answer bank</Button>
      </div>
    </div>
  )
}
