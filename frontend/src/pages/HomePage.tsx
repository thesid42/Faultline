import { useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { FaultlineHeroVisual } from '../components/FaultlineHeroVisual'
import { IncidentTable } from '../components/IncidentTable'
import { NewInvestigationDialog } from '../components/NewInvestigationDialog'
import { useCases, formatCaseLabel } from '../context/CaseContext'

function StateMessage({ children }: { children: ReactNode }) {
  return <div className="panel empty-state" style={{ padding: 32 }}>{children}</div>
}

export function HomePage() {
  const navigate = useNavigate()
  const [dialogOpen, setDialogOpen] = useState(false)
  const { cases, loading, error, refreshing } = useCases()
  const latest = cases[cases.length - 1]
  const activeCount = cases.filter((item) => item.status === 'queued' || item.status === 'investigating').length
  const completeCount = cases.filter((item) => item.status === 'complete').length
  const liveCount = cases.filter((item) => item.evidence_origin === 'live').length
  const recent = useMemo(() => [...cases].reverse(), [cases])

  return (
    <div className="tab-panel">
      <section className="hero-card">
        <FaultlineHeroVisual />
        <div className="hero-avatar" aria-hidden>FL</div>
        <div className="hero-content">
          <div className="hero-copy">
            <h1 className="greeting">Find the fault.<br />Fix the future.</h1>
            <p className="greeting-sub">Evidence-backed investigation for agents that fail in the wild.</p>
          </div>
          <div className="hero-actions">
            <button type="button" className="btn btn-primary" disabled={!latest} onClick={() => latest && navigate(`/investigations/${latest.caseid}`)}>
              {latest ? 'View latest case' : 'No cases available'}
            </button>
            <button type="button" className="btn btn-secondary hero-btn-secondary" onClick={() => setDialogOpen(true)}>
              New investigation
            </button>
          </div>
        </div>
      </section>

      {loading ? <StateMessage>Loading cases from the local API…</StateMessage> : null}
      {!loading && error ? <StateMessage><strong>Case API unavailable.</strong><br />{error}</StateMessage> : null}
      {!loading && !error && cases.length === 0 ? <StateMessage>No persisted case files yet. Run a Faultline investigation, then refresh this view.</StateMessage> : null}

      {!loading && !error && cases.length > 0 ? <>
        <div className="metrics-grid">
          <div className="metric-card accent-blue"><div className="metric-label">Cases in store</div><div className="metric-value">{cases.length}</div><div className="metric-footer"><span className="metric-delta">Current snapshot</span></div></div>
          <div className="metric-card accent-purple"><div className="metric-label">Active investigations</div><div className="metric-value">{activeCount}</div><div className="metric-footer"><span className="metric-delta">Queued or running</span></div></div>
          <div className="metric-card accent-green"><div className="metric-label">Completed cases</div><div className="metric-value">{completeCount}</div><div className="metric-footer"><span className="metric-delta">Persisted outcomes</span></div></div>
          <div className="metric-card accent-pink"><div className="metric-label">Live evidence</div><div className="metric-value">{liveCount}</div><div className="metric-footer"><span className="metric-delta">Origin recorded by API</span></div></div>
        </div>
        <div className="section-head"><h2 className="section-title" style={{ margin: 0 }}>Recent cases</h2><button type="button" className="link-btn" onClick={() => navigate('/incidents')}>View all →</button></div>
        <IncidentTable incidents={recent.slice(0, 3)} />
        {latest ? <p className="muted" style={{ marginTop: 14 }}>{refreshing ? 'Refreshing… ' : ''}Latest profile: {formatCaseLabel(latest.profile)}</p> : null}
      </> : null}
      <NewInvestigationDialog open={dialogOpen} onClose={() => setDialogOpen(false)} />
    </div>
  )
}
