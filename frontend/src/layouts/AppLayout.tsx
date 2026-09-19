import { Outlet } from 'react-router-dom'
import { AppSidebar } from '../components/AppSidebar'

export function AppLayout() {
  return (
    <div className="app-shell">
      <AppSidebar />
      <main className="main-area">
        <div className="main-inner">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
