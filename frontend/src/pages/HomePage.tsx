import { useMemo, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { FaultlineHeroVisual } from '../components/FaultlineHeroVisual'
import { IncidentTable } from '../components/IncidentTable'
import { NewInvestigationDialog } from '../components/NewInvestigationDialog'
import { useCases } from '../context/CaseContext'

function StateMessage({ children }: { children: ReactNode }) {
  return <div className="panel empty-state home-state-message" style={{ padding: 32 }}>{children}</div>
}

export function HomePage() {
  const navigate = useNavigate()
  const [dialogOpen, setDialogOpen] = useState(false)
  const { cases, loading, error, refreshing } = useCases()
  const latest = cases[cases.length - 1]
  const recent = useMemo(() => [...cases].reverse().slice(0, 3), [cases])

  return (
    <div className="page-shell beginner-home">
      <section className="hero-card beginner-hero">
        <FaultlineHeroVisual />
        <div className="hero-avatar" aria-hidden>FL</div>
        <div className="hero-content">
          <div className="hero-copy">
            <p className="eyebrow">Start here</p>
            <h1 className="greeting">Find out why<br />an AI agent failed.</h1>
            <p className="greeting-sub">See what went wrong, test a possible cause, and find the missing test.</p>
          </div>
          <div className="hero-actions">
            <button type="button" className="btn btn-primary" onClick={() => setDialogOpen(true)}>Start a guided demo</button>
            <button type="button" className="btn btn-secondary hero-btn-secondary" disabled={!latest} onClick={() => latest && navigate(`/investigations/${latest.caseid}`)}>{latest ? 'Review latest run' : 'No runs yet'}</button>
          </div>
        </div>
      </section>

      <section className="beginner-intro panel">
        <div><h2 className="section-title">What happens next?</h2><p className="muted">You choose a situation. Faultline investigates it. Then you read the result and the suggested test.</p></div>
        <ol className="guided-steps">
          <li><span>1</span><strong>Choose a situation</strong><small>Choose one of three refund scenarios.</small></li>
          <li><span>2</span><strong>Faultline investigates</strong><small>It checks the failure and tries controlled changes.</small></li>
          <li><span>3</span><strong>Read the result</strong><small>See the evidence and what the old tests missed.</small></li>
        </ol>
        <p className="beginner-note">Currently configured sample: a ReturnDesk refund agent. Free practice runs are local and make no model calls.</p>
      </section>

      {loading ? <StateMessage>Loading your saved runs…</StateMessage> : null}
      {!loading && error ? <StateMessage><strong>Saved runs are unavailable.</strong><br />{error}</StateMessage> : null}
      {!loading && !error && cases.length === 0 ? <StateMessage>No runs yet. Start a guided demo to create your first case.</StateMessage> : null}

      {!loading && !error && cases.length > 0 ? <section className="beginner-recent">
        <div className="section-head"><div><h2 className="section-title" style={{ margin: 0 }}>Recent runs</h2><p className="muted" style={{ margin: '4px 0 0' }}>{refreshing ? 'Refreshing…' : 'Your three most recent investigations.'}</p></div><button type="button" className="link-btn" onClick={() => navigate('/incidents')}>View all →</button></div>
        <IncidentTable incidents={recent} />
        {latest ? <p className="muted page-footnote">{refreshing ? 'Refreshing the saved runs…' : 'Select a run above to read its result.'}</p> : null}
      </section> : null}
      <NewInvestigationDialog open={dialogOpen} onClose={() => setDialogOpen(false)} />
    </div>
  )
}
