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
  const proposalReviewed = Boolean(
    proposal?.reviewed === true &&
      typeof proposal.approval_digest === 'string' &&
      proposal.approval_digest &&
      proposal.approval_digest === proposal.digest,
  )
  return (
    <div className="page-shell">
      <PageHeader title="Suggested tests" subtitle="Review the saved test suggestion for this investigation. Approval and export stay in the review workflow." actions={selectedId ? <Link className="btn btn-secondary" to={`/investigations/${selectedId}`}>Back to results</Link> : null} />
      {!listLoading && listError ? <div className="panel empty-state"><strong>Unable to load cases.</strong><br />{listError}</div> : null}
      {!listLoading && !listError ? <CaseSelector cases={cases} selectedId={selectedId} unknownId={unknownId} onChange={selectCase} /> : null}
      {listLoading || loading ? <div className="panel empty-state">Loading proposal evidence…</div> : null}
      {!listLoading && !loading && error ? <div className="panel empty-state">{error}</div> : null}
      {!listLoading && !listError && !loading && !error && !selectedId && !unknownId && cases.length === 0 ? <div className="panel empty-state">No investigations yet. Use Start an investigation from Investigations.</div> : null}
      {!listLoading && !listError && !loading && !error && selectedId && caseFile ? (
        <>
          <CaseEvidenceSummary caseFile={caseFile} />
          <div className="panel">
            <div className="section-head">
              <h2 className="section-title" style={{ margin: 0 }}>Suggested regression test</h2>
            </div>
            {proposal ? (
              <>
                <StatusBadge label={proposalReviewed ? 'Reviewed' : 'Pending human review'} tone={proposalReviewed ? 'success' : 'warning'} />
                <p className="muted">
                  Review: {proposalReviewed ? `Approved by ${String(proposal.approved_by ?? 'recorded reviewer')} with a matching digest.` : 'Human approval is pending or the approval digest does not match.'}
                </p>
                <h3>{String(proposal.title ?? 'Regression proposal')}</h3>
                <p>{String(proposal.rationale ?? 'No rationale recorded.')}</p>
                <details>
                  <summary>Technical details</summary>
                  <p className="muted">Proposal ID: <span className="mono" title={String(proposal.proposal_id ?? '')}>{String(proposal.proposal_id ?? '—')}</span></p>
                  <p className="muted">Digest: <span className="mono" title={String(proposal.digest ?? '')}>{String(proposal.digest ?? '—')}</span></p>
                  <pre className="raw-json">{displayValue(proposal.tests)}</pre>
                </details>
              </>
            ) : (
              <p className="muted">No regression proposal has been persisted for this case.</p>
            )}
          </div>
        </>
      ) : null}
    </div>
  )
}
