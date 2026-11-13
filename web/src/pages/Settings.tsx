import { useState, type ReactNode } from 'react'
import { Navigate, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { getSettings } from '../api'
import { Spinner, Tabs } from '../components/ui'
import { errorMessage } from '../lib/tasks'
import SourcesSection from './settings/SourcesSection'
import SitesSection from './settings/SitesSection'
import AnswerBankSection from './settings/AnswerBankSection'
import AiSection from './settings/AiSection'
import Companies from './Companies'

type Tab = 'sources' | 'sites' | 'answers' | 'ai' | 'companies'
const TABS: Tab[] = ['sources', 'sites', 'answers', 'ai', 'companies']

export default function Settings() {
  const [sp, setSp] = useSearchParams()
  const raw = sp.get('tab')
  const wanted = raw === 'automation' ? 'ai' : raw
  const tab: Tab = TABS.includes(wanted as Tab) ? (wanted as Tab) : 'sources'      // unknown or missing tab: Sources
  const settings = useQuery({ queryKey: ['settings'], queryFn: getSettings })
  // A visited tab stays mounted (hidden), so unsaved edits survive switching tabs.
  const [visited, setVisited] = useState<Tab[]>([tab])
  if (!visited.includes(tab)) setVisited([...visited, tab])
  const pane = (t: Tab, node: ReactNode) => visited.includes(t) && <div hidden={tab !== t}>{node}</div>
  if (raw === 'activity') return <Navigate to="/activity" replace />
  if (settings.isLoading) return <div className="flex justify-center py-20"><Spinner size={24} /></div>
  if (settings.isError || !settings.data) return <div className="text-sm text-bad-ink">{errorMessage(settings.error)}</div>
  const s = settings.data
  return (
    <div className="mx-auto flex max-w-[1200px] flex-col gap-5">
      <header>
        <h2 className="page-title">Settings</h2>
        <p className="mt-1.5 text-sm text-ink-2">Search profiles and the schedule have their own pages. Everything else lives here.</p>
      </header>
      <Tabs<Tab> value={tab} onChange={(v) => setSp({ tab: v }, { replace: true })} items={[
        { value: 'sources', label: 'Sources', count: s.sources.filter((x) => x.enabled).length },
        { value: 'sites', label: 'Job sites', count: s.sites.length },
        { value: 'answers', label: 'Your answers' },
        { value: 'ai', label: 'AI' },
        { value: 'companies', label: 'Companies' },
      ]} />
      {pane('sources', <SourcesSection sources={s.sources} />)}
      {pane('sites', <SitesSection initial={s.sites} />)}
      {pane('answers', <AnswerBankSection initial={s.answer_bank} />)}
      {pane('ai', <AiSection settings={s} />)}
      {pane('companies', <Companies />)}
    </div>
  )
}
