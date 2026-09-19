import { NavLink, useLocation } from 'react-router-dom'
import { Activity, Beaker, FileCheck2, FlaskConical, Home, Settings } from 'lucide-react'

const technicalViews = [
  { to: '/experiments', label: 'Test runs', icon: FlaskConical },
  { to: '/coverage', label: 'Test coverage', icon: Beaker },
  { to: '/regression', label: 'Suggested tests', icon: FileCheck2 },
]

export function AppSidebar() {
  const location = useLocation()
  const investigationActive = location.pathname.startsWith('/investigations/')

  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <div className="sidebar-logo" aria-hidden>
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M1 9.5L4.5 4.5L7 7.5L10 2.5L13 6" stroke="white" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" /></svg>
        </div>
        <span className="sidebar-brand-text">Faultline</span>
      </div>

      <nav className="sidebar-nav" aria-label="Main navigation">
        <NavLink to="/" end className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}><Home strokeWidth={1.75} /><span>Start</span></NavLink>
        <NavLink to="/incidents" className={({ isActive }) => `nav-item${isActive || investigationActive ? ' active' : ''}`}><Activity strokeWidth={1.75} /><span>Investigations</span></NavLink>
        <NavLink to="/settings" className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}><Settings strokeWidth={1.75} /><span>Connections</span></NavLink>

        <details className="sidebar-technical">
          <summary>Technical views</summary>
          <div className="sidebar-technical-list">
            {technicalViews.map(({ to, label, icon: Icon }) => <NavLink key={to} to={to} className={({ isActive }) => `nav-item nav-item-sub${isActive ? ' active' : ''}`}><Icon strokeWidth={1.75} /><span>{label}</span></NavLink>)}
          </div>
        </details>
      </nav>

      <div className="sidebar-footer"><div className="avatar-btn" title="Faultline workspace" aria-label="Faultline workspace">FL</div></div>
    </aside>
  )
}
