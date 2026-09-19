import { Link } from 'react-router-dom'
import { PageHeader } from '../components/PageHeader'
import { StatusBadge } from '../components/StatusBadge'
import { displayValue, useCase, useCases } from '../context/CaseContext'

export function ExperimentsPage() {
  const { cases, loading: listLoading } = useCases()
  const selected = cases[cases.length - 1]?.caseid
  const { caseFile, loading, error } = useCase(selected)
  const experiments = Array.isArray(caseFile?.experiment_results) ? caseFile.experiment_results : []
  return <div>
    <PageHeader title="Experiments" subtitle="Persisted experiment results; execution is intentionally read-only in this UI." />
    {listLoading || loading ? <div className="panel empty-state">Loading experiment evidence…</div> : null}
    {!listLoading && !loading && error ? <div className="panel empty-state">{error}</div> : null}
    {!listLoading && !loading && !error && !selected ? <div className="panel empty-state">No cases are available.</div> : null}
    {!listLoading && !loading && !error && selected ? <div className="panel"><div className="section-head"><h2 className="section-title" style={{ margin: 0 }}>Case <span className="mono">{selected}</span></h2><Link className="btn btn-secondary" to={`/investigations/${selected}`}>Open case</Link></div>{experiments.length === 0 ? <p className="muted">This case has no experiment results.</p> : <div className="table-wrap"><table className="table"><thead><tr><th>Trial</th><th>Operator</th><th>Status</th><th>Observed violation</th><th>Details</th></tr></thead><tbody>{experiments.map((item) => { const record = item as Record<string, unknown>; const status = String(record.status ?? 'unknown'); return <tr key={String(record.trial_id)}><td className="mono">{String(record.trial_id)}</td><td>{String((record.activation as Record<string, unknown> | undefined)?.operator ?? '—')}</td><td><StatusBadge label={status} tone={status === 'completed' ? 'success' : status === 'infrastructure_error' ? 'failure' : 'info'} /></td><td>{record.observed_violation === true ? 'Yes' : record.observed_violation === false ? 'No' : 'Unknown'}</td><td><details><summary>JSON</summary><pre className="raw-json">{displayValue(record)}</pre></details></td></tr> })}</tbody></table></div>}</div> : null}
  </div>
}
