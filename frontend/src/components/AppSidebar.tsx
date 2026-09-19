import { NavLink } from 'react-router-dom'
import {
  Activity,
  Beaker,
  FileCheck2,
  FlaskConical,
  Home,
  Settings,
  ShieldAlert,
} from 'lucide-react'
import { currentUser } from '../data/mockData'

const navItems = [
  { to: '/', label: 'Home', icon: Home, end: true },
  { to: '/incidents', label: 'Incidents', icon: ShieldAlert },
  { to: '/investigations/021', label: 'Investigations', icon: Activity },
  { to: '/experiments', label: 'Experiments', icon: FlaskConical },
  { to: '/coverage', label: 'Coverage', icon: Beaker },
  { to: '/regression', label: 'Regression', icon: FileCheck2 },
  { to: '/settings', label: 'Settings', icon: Settings },
]

export function AppSidebar() {
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
        {navItems.map(({ to, label, icon: Icon, end }) => (
          <NavLink key={to} to={to} end={end} className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}>
            <Icon strokeWidth={1.75} />
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>

      <div className="sidebar-footer">
        <button type="button" className="avatar-btn" title={currentUser.name} aria-label="User menu">
          {currentUser.initials}
        </button>
      </div>
    </aside>
  )
}
