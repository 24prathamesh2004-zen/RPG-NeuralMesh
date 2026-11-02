import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider, useAuth } from './auth/AuthContext'
import AppShell from './components/layout/AppShell'
import AskPage from './pages/AskPage'
import AuthPage from './pages/AuthPage'
import DashboardPage from './pages/DashboardPage'
import AdminPage from './pages/AdminPage'
import ExpertFinderPage from './pages/ExpertFinderPage'
import GovernancePage from './pages/GovernancePage'
import MeshNodesPage from './pages/MeshNodesPage'
import PlaygroundPage from './pages/PlaygroundPage'
import SettingsPage from './pages/SettingsPage'

function AuthenticatedApp() {
  const { user, loading } = useAuth()
  if (loading) return <div className="grid min-h-screen place-items-center text-sm text-stone-600">Loading your workspace…</div>
  if (!user) return <Navigate to="/auth" replace />

  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/ask" element={<AskPage />} />
        <Route path="/experts" element={<ExpertFinderPage />} />
        <Route path="/nodes" element={<MeshNodesPage />} />
        <Route path="/governance" element={<GovernancePage />} />
        <Route path="/admin" element={<AdminPage />} />
        <Route path="/playground" element={<PlaygroundPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/ask" replace />} />
      </Routes>
    </AppShell>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/auth" element={<AuthPage />} />
          <Route path="*" element={<AuthenticatedApp />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}
