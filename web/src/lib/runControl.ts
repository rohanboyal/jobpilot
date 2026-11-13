import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ApiError, putSchedule, startAnalyze, startCollect, startCycle, stopTasks } from '../api'
import type { RunOptions, ScheduleUpdate } from '../types'
import { useToast } from './toast'
import { errorMessage, useTasks } from './tasks'

/** Start / stop pipeline runs and change the schedule from anywhere in the UI. */
export function useRunControl() {
  const qc = useQueryClient()
  const toast = useToast()
  const tasks = useTasks()
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['tasks'] })
    qc.invalidateQueries({ queryKey: ['schedule'] })
    qc.invalidateQueries({ queryKey: ['today'] })
  }
  const onStartError = (e: unknown) =>
    e instanceof ApiError && e.status === 409 ? toast.info('Already running', e.message) : toast.error('Could not start', errorMessage(e))

  const how = (o?: RunOptions) => (o?.one_by_one ? ' One profile at a time.' : '')
  const start = useMutation({
    mutationFn: (opts?: RunOptions) => startCycle(opts),
    onSuccess: (_, o) => { toast.success('Run started', `Collect, then analyze the best new matches.${how(o)} You can stop it at any time.`); refresh() },
    onError: onStartError,
  })
  const collect = useMutation({
    mutationFn: (opts?: RunOptions) => startCollect(opts),
    onSuccess: (_, o) => { toast.success('Collecting jobs', `Free: no AI calls except sites without selectors.${how(o)}`); refresh() },
    onError: onStartError,
  })
  const analyze = useMutation({
    mutationFn: (opts?: RunOptions) => startAnalyze(opts),
    onSuccess: (_, o) => { toast.success('Analyzing matches', `Best new matches first, then drafts for the top ones.${how(o)}`); refresh() },
    onError: onStartError,
  })
  const stop = useMutation({
    mutationFn: () => stopTasks(),
    onSuccess: () => { toast.info('Stopping', 'Finishing the current step, then stopping. Nothing is left half-done.'); refresh() },
    onError: (e) => (e instanceof ApiError && e.status === 404 ? toast.info('Nothing is running') : toast.error('Could not stop', errorMessage(e))),
  })
  const schedule = useMutation({
    mutationFn: (body: ScheduleUpdate) => putSchedule(body),
    onSuccess: (info, body) => {
      qc.setQueryData(['schedule'], info)
      if (body.paused !== undefined) toast.success(info.paused ? 'Scheduled runs paused' : 'Scheduled runs on', info.paused ? 'Run now still works.' : undefined)
      refresh()
    },
    onError: (e) => toast.error('Could not update the schedule', errorMessage(e)),
  })

  const data = tasks.data
  const runningTasks = data?.tasks.filter((t) => t.status === 'running') ?? []
  return {
    tasks,
    scheduler: data?.scheduler,
    running: runningTasks.length > 0,
    stopping: runningTasks.some((t) => t.stopping),
    runningTasks,
    start,
    collect,
    analyze,
    stop,
    schedule,
  }
}

export const DAY_SHORT = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

/** "09:00" -> "9:00 AM" in the user's locale. */
export function fmtClock(hhmm: string): string {
  const [h, m] = hhmm.split(':').map(Number)
  const d = new Date()
  d.setHours(h, m, 0, 0)
  return d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
}

/** [0,3] -> "Mon & Thu"; all 7 -> "Every day"; Mon–Fri -> "Weekdays". */
export function fmtDays(days: number[]): string {
  const d = [...days].sort()
  if (d.length === 7) return 'Every day'
  if (d.length === 5 && d.every((x, i) => x === i)) return 'Weekdays'
  if (!d.length) return 'No days'
  const names = d.map((x) => DAY_SHORT[x])
  return names.length <= 2 ? names.join(' & ') : `${names.slice(0, -1).join(', ')} & ${names[names.length - 1]}`
}
