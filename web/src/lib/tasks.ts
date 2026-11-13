import { useEffect, useRef } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { getTasks } from '../api'
import type { TasksResponse } from '../types'

/** Polls /pipeline/tasks; fast while something runs. Invalidates data queries when a task finishes. */
export function useTasks() {
  const qc = useQueryClient()
  const query = useQuery<TasksResponse>({
    queryKey: ['tasks'],
    queryFn: getTasks,
    refetchInterval: (q) => ((q.state.data?.running.length ?? 0) > 0 ? 3000 : 15000),
    staleTime: 2000,
  })
  const prevRunning = useRef<string[]>([])
  useEffect(() => {
    const now = query.data?.running ?? []
    const finished = prevRunning.current.filter((k) => !now.includes(k))
    if (finished.length) {
      qc.invalidateQueries({ predicate: (q) => q.queryKey[0] !== 'tasks' })
    }
    prevRunning.current = now
  }, [query.data?.running, qc])
  return query
}

export function errorMessage(e: unknown): string {
  if (e instanceof Error) return e.message
  return String(e)
}
