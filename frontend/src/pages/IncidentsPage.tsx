import { Link } from 'react-router-dom'
import { IncidentTable } from '../components/IncidentTable'
import { PageHeader } from '../components/PageHeader'
import { NewInvestigationDialog } from '../components/NewInvestigationDialog'
import { useCases } from '../context/CaseContext'
import { useState } from 'react'

export function IncidentsPage() {
  const [dialogOpen, setDialogOpen] = useState(false)
  const { cases, loading, error, refreshing } = useCases()
  return (
    <div className="page-shell">
      <PageHeader title="Cases" subtitle="Persisted agent failures and investigation runs from the local Faultline API." actions={<button type="button" className="btn btn-primary" onClick={() => setDialogOpen(true)}>New investigation</button>} />
      {refreshing ? <p className="muted">Refreshing case store…</p> : null}
      {loading ? <div className="panel empty-state">Loading cases…</div> : null}
      {!loading && error ? <div className="panel empty-state"><strong>Unable to load cases.</strong><br />{error}</div> : null}
      {!loading && !error && cases.length === 0 ? <div className="panel empty-state">No cases are available. Use New investigation above or from Home to start one.</div> : null}
      {!loading && !error && cases.length > 0 ? <IncidentTable incidents={cases} /> : null}
      <p className="muted page-footnote"><Link to="/settings">Read-only workspace</Link> · case evidence is read-only after launch.</p>
      <NewInvestigationDialog open={dialogOpen} onClose={() => setDialogOpen(false)} />
    </div>
  )
}
