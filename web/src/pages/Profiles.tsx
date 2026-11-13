import { Link } from 'react-router-dom'
import ProfileTabs from '../components/ProfileTabs'
import ResumeTabs from '../components/ResumeTabs'
import ResumeRefreshBanner from '../components/ResumeRefreshBanner'

export default function Profiles() {
  return (
    <div className="mx-auto flex max-w-[1120px] flex-col gap-5">
      <header>
        <h2 className="page-title">Profiles &amp; resumes</h2>
        <p className="mt-1.5 max-w-[680px] text-sm leading-relaxed text-ink-2">
          Each search profile is one kind of job you want, and it can use its own resume: jobs are scored against it and it is uploaded with their applications. Collected jobs are tagged with every profile they match.
        </p>
      </header>
      <section className="card p-5">
        <h3 className="mb-1 text-[17px] font-bold">Resumes</h3>
        <p className="mb-4 text-[13px] text-ink-2">Add one per kind of job if you like (Data Scientist, Applied AI…). Profiles that don&rsquo;t pick one use the default. Form answers such as phone or notice period live in <Link to="/settings?tab=answers">Settings › Your answers</Link>.</p>
        <div className="mb-4"><ResumeRefreshBanner /></div>
        <ResumeTabs />
      </section>
      <section className="card p-5">
        <h3 className="mb-1 text-[17px] font-bold">Search profiles</h3>
        <p className="mb-4 text-[13px] text-ink-2">Saving a profile re-checks every collected job against it. That is free: no AI calls. Choose which profiles a run covers when you press Run now.</p>
        <ProfileTabs />
      </section>
    </div>
  )
}
