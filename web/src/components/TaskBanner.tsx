import { useState } from 'react'
import { ChevronDown, ChevronUp, Loader2, Square } from 'lucide-react'
import { fmtDuration } from '../lib/format'
import { useRunControl } from '../lib/runControl'
import { Button, Chip, LogView } from './ui'

export default function TaskBanner() {
  const { runningTasks, stop, stopping } = useRunControl()
  const [open, setOpen] = useState(true)
  if (!runningTasks.length) return null
  const t = runningTasks[0]
  return (
    <div className="card mb-4 overflow-hidden" style={{ borderColor: 'color-mix(in oklab, var(--accent) 35%, var(--line))' }}>
      <div className="flex items-center gap-3 px-4 py-2.5 text-sm">
        <Loader2 size={15} className="spin shrink-0 text-accent-ink" />
        <button className="flex min-w-0 flex-1 items-center gap-2 text-left" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
          <span className="truncate font-medium">{runningTasks.map((x) => x.label).join(' · ')}</span>
          <span className="num shrink-0 text-xs text-muted">{fmtDuration(t.started_at, null)}</span>
          {stopping && <Chip tone="warn">stopping…</Chip>}
          {open ? <ChevronUp size={15} className="ml-auto shrink-0 text-muted" /> : <ChevronDown size={15} className="ml-auto shrink-0 text-muted" />}
        </button>
        <Button size="sm" variant="outline" icon={Square} onClick={() => stop.mutate()} loading={stop.isPending} disabled={stopping}
          title="Finish the current step, then stop">
          {stopping ? 'Stopping' : 'Stop'}
        </Button>
      </div>
      {open && (
        <div className="border-t border-line px-4 py-3">
          <LogView lines={t.log_tail} maxHeight={160} />
        </div>
      )}
    </div>
  )
}
