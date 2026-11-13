import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { RefreshCw } from 'lucide-react'
import { ApiError, getStaleResume, refreshWithResume } from '../api'
import { useToast } from '../lib/toast'
import { errorMessage } from '../lib/tasks'
import { Button } from './ui'

/** Shown when scores or draft letters were made before the current resume was uploaded. */
export default function ResumeRefreshBanner() {
  const qc = useQueryClient()
  const toast = useToast()
  const stale = useQuery({ queryKey: ['stale-resume'], queryFn: getStaleResume, staleTime: 30_000 })
  const run = useMutation({
    mutationFn: refreshWithResume,
    onSuccess: () => { toast.success('Refreshing with your current resume', 'Re-scoring and redrafting in the background.'); qc.invalidateQueries({ queryKey: ['tasks'] }); qc.invalidateQueries({ queryKey: ['stale-resume'] }) },
    onError: (e) => (e instanceof ApiError && e.status === 409 ? toast.info('Busy', e.message) : toast.error('Could not start', errorMessage(e))),
  })
  const s = stale.data
  if (!s || (!s.jobs && !s.drafts)) return null
  const parts = [s.jobs ? `${s.jobs} job score${s.jobs === 1 ? '' : 's'}` : '', s.drafts ? `${s.drafts} draft cover letter${s.drafts === 1 ? '' : 's'}` : ''].filter(Boolean)
  return (
    <div className="card flex flex-wrap items-center gap-3 p-4" style={{ borderColor: 'color-mix(in oklab, var(--accent) 40%, var(--line))' }}>
      <RefreshCw size={19} className="text-accent-ink" />
      <div className="min-w-[240px] flex-1">
        <div className="text-sm font-bold">{parts.join(' and ')} {s.jobs + s.drafts === 1 ? 'was' : 'were'} made with an older resume</div>
        <div className="text-[13px] text-ink-2">Refresh them with your current resume: about {s.jobs + s.drafts * 2} AI calls. Applications you already sent are not touched.</div>
      </div>
      <Button variant="outline" icon={RefreshCw} onClick={() => run.mutate()} loading={run.isPending}>Refresh</Button>
    </div>
  )
}
