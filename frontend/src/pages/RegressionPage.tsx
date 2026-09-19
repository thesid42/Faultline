import { Link } from 'react-router-dom'
import { PageHeader } from '../components/PageHeader'
import { StatusBadge } from '../components/StatusBadge'
import { CaseEvidenceSummary } from '../components/CaseEvidenceSummary'
import { CaseSelector, useCaseSelection } from '../components/CaseSelector'
import { displayValue, useCase, useCases } from '../context/CaseContext'

export function RegressionPage() {
  const { cases, loading: listLoading, error: listError } = useCases()
  const { selectedId, unknownId, selectCase } = useCaseSelection(cases)
  const { caseFile, loading, error } = useCase(selectedId)
  const proposal = caseFile?.proposal
  const proposalReviewed = Boolean(proposal?.reviewed === true && typeof proposal.approval_digest === 'string' && proposal.approval_digest && proposal.approval_digest === proposal.digest)
  return <div>
    <PageHeader title="Regression" subtitle="Proposals are displayed for review; approval and export remain CLI/repository operations." />
    {!listLoading && listError ? <div className="panel empty-state"><strong>Unable to load cases.</strong><br />{listError}</div> : null}
    {!listLoading && !listError ? <CaseSelector cases={cases} selectedId={selectedId} unknownId={unknownId} onChange={selectCase} /> : null}
    {listLoading || loading ? <div className="panel empty-state">Loading proposal evidence…</div> : null}
    {!listLoading && !loading && error ? <div className="panel empty-state">{error}</div> : null}
    {!listLoading && !listError && !loading && !error && !selectedId ? <div className="panel empty-state">No cases are available. Use New investigation from Home or Cases to start one.</div> : null}
    {!listLoading && !listError && !loading && !error && selectedId && caseFile ? <><CaseEvidenceSummary caseFile={caseFile} /><div className="panel"><div className="section-head"><h2 className="section-title" style={{ margin: 0 }}>Case <span className="mono">{selectedId}</span></h2><Link className="btn btn-secondary" to={`/investigations/${selectedId}?tab=regression`}>Open case</Link></div>{proposal ? <><StatusBadge label={proposalReviewed ? 'Reviewed' : 'Pending human review'} tone={proposalReviewed ? 'success' : 'warning'} /><p className="muted">Proposal ID: <span className="mono">{String(proposal.proposal_id ?? '—')}</span></p><p className="muted">Digest: <span className="mono">{String(proposal.digest ?? '—')}</span></p><p className="muted">Review: {proposalReviewed ? `Approved by ${String(proposal.approved_by ?? 'recorded reviewer')} with a matching digest.` : 'Human approval is pending or the approval digest does not match.'}</p><h3>{String(proposal.title ?? 'Regression proposal')}</h3><p>{String(proposal.rationale ?? 'No rationale recorded.')}</p><pre className="raw-json">{displayValue(proposal.tests)}</pre></> : <p className="muted">No regression proposal has been persisted for this case.</p>}</div></> : null}
  </div>
}
