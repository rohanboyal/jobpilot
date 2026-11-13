import { Navigate, Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import Today from './pages/Today'
import Jobs from './pages/Jobs'
import Applications from './pages/Applications'
import Profiles from './pages/Profiles'
import Schedule from './pages/Schedule'
import Settings from './pages/Settings'
import Setup from './pages/Setup'
import Insights from './pages/Insights'
import Activity from './pages/Activity'

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Today />} />
        <Route path="jobs" element={<Jobs />} />
        <Route path="applications/:id?" element={<Applications />} />
        <Route path="profiles" element={<Profiles />} />
        <Route path="schedule" element={<Schedule />} />
        <Route path="settings" element={<Settings />} />
        <Route path="setup" element={<Setup />} />
        <Route path="insights" element={<Insights />} />
        <Route path="profile" element={<Navigate to="/profiles" replace />} />
        <Route path="companies" element={<Navigate to="/settings?tab=companies" replace />} />
        <Route path="activity" element={<Activity />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
