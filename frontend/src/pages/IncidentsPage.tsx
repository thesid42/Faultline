import { Link } from 'react-router-dom'
import { IncidentTable } from '../components/IncidentTable'
import { PageHeader } from '../components/PageHeader'
import { useCases } from '../context/CaseContext'

export function IncidentsPage() {
  const { cases, loading, error, refreshing } = useCases()
  return (
    <div>
      <PageHeader title="Cases" subtitle="Persisted agent failures and investigation runs from the local Faultline API." />
      {refreshing ? <p className="muted">Refreshing case store…</p> : null}
      {loading ? <div className="panel empty-state">Loading cases…</div> : null}
      {!loading && error ? <div className="panel empty-state"><strong>Unable to load cases.</strong><br />{error}</div> : null}
      {!loading && !error && cases.length === 0 ? <div className="panel empty-state">No cases are available. Run the CLI to create a case file.</div> : null}
      {!loading && !error && cases.length > 0 ? <IncidentTable incidents={cases} /> : null}
      <p className="muted" style={{ marginTop: 16 }}><Link to="/settings">Read-only workspace</Link> · mutations run through the CLI.</p>
    </div>
  )
}
