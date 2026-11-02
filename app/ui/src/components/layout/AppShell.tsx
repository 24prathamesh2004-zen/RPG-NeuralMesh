import { NavLink } from 'react-router-dom'
import { Activity, Bell, Boxes, CircleHelp, LayoutDashboard, LogOut, Network, ShieldCheck, UsersRound } from 'lucide-react'
import type { ReactNode } from 'react'
import { useAuth } from '../../auth/AuthContext'
import { DEFAULT_MESH_SCOPE, MeshScopeProvider } from '../../context/MeshScopeContext'
import type { CompanyId } from '../../services/api'
import { useState } from 'react'

const NAV = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/ask', label: 'Ask NeuralMesh', icon: Network },
  { to: '/experts', label: 'Expert Finder', icon: UsersRound },
  { to: '/nodes', label: 'Mesh Nodes', icon: Boxes },
  { to: '/governance', label: 'Governance', icon: ShieldCheck },
  { to: '/admin', label: 'Admin', icon: Activity },
]

const SCOPES: { id: string; label: string; nodes: CompanyId[] }[] = [
  { id: 'all', label: 'All connected companies', nodes: DEFAULT_MESH_SCOPE },
  { id: 'ceat-kec', label: 'CEAT + KEC', nodes: ['ceat', 'kec'] },
  { id: 'zensar', label: 'Zensar only', nodes: ['zensar'] },
  { id: 'ceat-harrisons', label: 'CEAT + Harrisons', nodes: ['ceat', 'harrisons'] },
]

export default function AppShell({ children }: { children: ReactNode }) {
  const { user, signOut } = useAuth()
  const [selectedNodes, setSelectedNodes] = useState<CompanyId[]>(DEFAULT_MESH_SCOPE)
  const scopeId = SCOPES.find((scope) => scope.nodes.length === selectedNodes.length && scope.nodes.every((node) => selectedNodes.includes(node)))?.id ?? 'custom'
  const initials = user?.display_name.split(/\s+/).map((part) => part[0]).slice(0, 2).join('').toUpperCase() ?? 'GS'

  return (
    <MeshScopeProvider value={{ selectedNodes, setSelectedNodes }}>
      <div className="mesh-app min-h-screen">
        <aside className="mesh-sidebar">
          <NavLink to="/" className="mesh-brand" aria-label="RPG NeuralMesh dashboard">
            <span className="mesh-brand-mark"><Network size={18} /></span>
            <span>RPG NeuralMesh</span>
          </NavLink>
          <nav className="mesh-nav" aria-label="Main navigation">
            {NAV.map(({ to, label, icon: Icon }) => (
              <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) => `mesh-nav-link ${isActive ? 'active' : ''}`}>
                <Icon size={17} strokeWidth={1.8} />
                <span>{label}</span>
                {to === '/governance' && <span className="mesh-nav-mark" aria-label="Approvals" />}
              </NavLink>
            ))}
          </nav>
          <div className="mesh-sidebar-foot"><span className="mesh-status-dot" />Synthetic data pilot</div>
        </aside>

        <div className="mesh-main">
          <header className="mesh-topbar">
            <label className="mesh-scope-control">
              <span>Scope</span>
              <select
                aria-label="Company scope"
                value={scopeId}
                onChange={(event) => {
                  const scope = SCOPES.find((item) => item.id === event.target.value)
                  if (scope) setSelectedNodes(scope.nodes)
                }}
              >
                {SCOPES.map((scope) => <option key={scope.id} value={scope.id}>{scope.label}</option>)}
                <option value="custom">Custom selection</option>
              </select>
            </label>
            <div className="mesh-topbar-actions">
              <NavLink to="/governance" className="mesh-icon-button" title="Approvals and governance" aria-label="Approvals and governance"><Bell size={17} /></NavLink>
              <div className="mesh-user-avatar" aria-hidden="true">{initials}</div>
              <div className="mesh-user-copy"><strong>{user?.display_name}</strong><span>{user?.company_name}</span></div>
              <button type="button" title="Sign out" aria-label="Sign out" onClick={signOut} className="mesh-icon-button"><LogOut size={16} /></button>
              <button type="button" title="Help" aria-label="Help" className="mesh-icon-button mesh-help"><CircleHelp size={17} /></button>
            </div>
          </header>
          <main className="mesh-content">{children}</main>
        </div>
      </div>
    </MeshScopeProvider>
  )
}
