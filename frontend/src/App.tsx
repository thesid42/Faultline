import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { ToastProvider } from './context/ToastContext'
import { CaseProvider } from './context/CaseContext'
import { AppLayout } from './layouts/AppLayout'
import { CoveragePage } from './pages/CoveragePage'
import { ExperimentsPage } from './pages/ExperimentsPage'
import { HomePage } from './pages/HomePage'
import { IncidentsPage } from './pages/IncidentsPage'
import { InvestigationPage } from './pages/InvestigationPage'
import { RegressionPage } from './pages/RegressionPage'
import { SettingsPage } from './pages/SettingsPage'

export default function App() {
  return (
    <ToastProvider>
      <BrowserRouter>
        <CaseProvider>
          <Routes>
            <Route element={<AppLayout />}>
              <Route index element={<HomePage />} />
              <Route path="incidents" element={<IncidentsPage />} />
              <Route path="investigations" element={<Navigate to="/incidents" replace />} />
              <Route path="investigations/:id" element={<InvestigationPage />} />
              <Route path="experiments" element={<ExperimentsPage />} />
              <Route path="coverage" element={<CoveragePage />} />
              <Route path="regression" element={<RegressionPage />} />
              <Route path="settings" element={<SettingsPage />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Routes>
        </CaseProvider>
      </BrowserRouter>
    </ToastProvider>
  )
}
