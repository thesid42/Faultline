import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import {
  Activity,
  Beaker,
  FileCheck2,
  FlaskConical,
  Home,
  Settings,
  ShieldAlert,
} from 'lucide-react'
import { useCases } from '../context/CaseContext'

const navItems = [
  { to: '/', label: 'Home', icon: Home, end: true },
  { to: '/incidents', label: 'Cases', icon: ShieldAlert },
  { to: '/experiments', label: 'Experiments', icon: FlaskConical },
  { to: '/coverage', label: 'Coverage', icon: Beaker },
  { to: '/regression', label: 'Regression', icon: FileCheck2 },
  { to: '/settings', label: 'Settings', icon: Settings },
] as const

export function AppSidebar() {
  const navigate = useNavigate()
  const location = useLocation()
  const { cases } = useCases()
  const latestCaseId = cases[cases.length - 1]?.caseid
  const investigationsActive = location.pathname.startsWith('/investigations/')

  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <div className="sidebar-logo" aria-hidden>
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <path
              d="M1 9.5L4.5 4.5L7 7.5L10 2.5L13 6"
              stroke="white"
              strokeWidth="1.6"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </div>
        <span className="sidebar-brand-text">Faultline</span>
      </div>

      <nav className="sidebar-nav">
        {navItems.slice(0, 2).map((item) => (
          <NavLink key={item.to} to={item.to} end={'end' in item ? item.end : false} className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}>
            <item.icon strokeWidth={1.75} />
            <span>{item.label}</span>
          </NavLink>
        ))}

        <button
          type="button"
          className={`nav-item${investigationsActive ? ' active' : ''}`}
          onClick={() => navigate(latestCaseId ? `/investigations/${latestCaseId}` : '/incidents')}
        >
          <Activity strokeWidth={1.75} />
          <span>Investigations</span>
        </button>

        {navItems.slice(2).map((item) => (
          <NavLink key={item.to} to={item.to} className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}>
            <item.icon strokeWidth={1.75} />
            <span>{item.label}</span>
          </NavLink>
        ))}
      </nav>

      <div className="sidebar-footer">
        <button type="button" className="avatar-btn" title="Faultline workspace" aria-label="Faultline workspace">
          FL
        </button>
      </div>
    </aside>
  )
}
