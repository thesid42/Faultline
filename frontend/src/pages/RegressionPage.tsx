import { Link } from 'react-router-dom'
import { PageHeader } from '../components/PageHeader'
import { StatusBadge } from '../components/StatusBadge'
import { displayValue, useCase, useCases } from '../context/CaseContext'

export function RegressionPage() {
  const { cases, loading: listLoading } = useCases()
  const selected = cases[cases.length - 1]?.caseid
  const { caseFile, loading, error } = useCase(selected)
  const proposal = caseFile?.proposal
  const proposalReviewed = Boolean(proposal?.reviewed === true && typeof proposal.approval_digest === 'string' && proposal.approval_digest && proposal.approval_digest === proposal.digest)
  return <div>
    <PageHeader title="Regression" subtitle="Proposals are displayed for review; approval and export remain CLI/repository operations." />
    {listLoading || loading ? <div className="panel empty-state">Loading proposal evidence…</div> : null}
    {!listLoading && !loading && error ? <div className="panel empty-state">{error}</div> : null}
    {!listLoading && !loading && !error && !selected ? <div className="panel empty-state">No cases are available.</div> : null}
    {!listLoading && !loading && !error && selected ? <div className="panel"><div className="section-head"><h2 className="section-title" style={{ margin: 0 }}>Case <span className="mono">{selected}</span></h2><Link className="btn btn-secondary" to={`/investigations/${selected}?tab=regression`}>Open case</Link></div>{proposal ? <><StatusBadge label={proposalReviewed ? 'Reviewed' : 'Pending human review'} tone={proposalReviewed ? 'success' : 'warning'} /><h3>{String(proposal.title ?? 'Regression proposal')}</h3><p>{String(proposal.rationale ?? 'No rationale recorded.')}</p><pre className="raw-json">{displayValue(proposal.tests)}</pre><button type="button" className="btn btn-secondary" disabled title="Approval is handled outside this read-only UI.">Approval via CLI / review workflow</button></> : <p className="muted">No regression proposal has been persisted for this case.</p>}</div> : null}
  </div>
}
