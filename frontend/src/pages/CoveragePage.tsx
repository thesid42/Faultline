import { Link } from 'react-router-dom'
import { PageHeader } from '../components/PageHeader'
import { StatusBadge } from '../components/StatusBadge'
import { CaseEvidenceSummary } from '../components/CaseEvidenceSummary'
import { CaseSelector, useCaseSelection } from '../components/CaseSelector'
import { useCase, useCases } from '../context/CaseContext'

export function CoveragePage() {
  const { cases, loading: listLoading, error: listError } = useCases()
  const { selectedId, unknownId, selectCase } = useCaseSelection(cases)
  const { caseFile, loading, error } = useCase(selectedId)
  const coverage = Array.isArray(caseFile?.coverage) ? caseFile.coverage : []
  return (
    <div className="page-shell">
      <PageHeader title="Test coverage" subtitle="See which situations the saved tests cover. This page reports checks; it does not decide a root cause." actions={selectedId ? <Link className="btn btn-secondary" to={`/investigations/${selectedId}`}>Back to results</Link> : null} />
      {!listLoading && listError ? <div className="panel empty-state"><strong>Unable to load cases.</strong><br />{listError}</div> : null}
      {!listLoading && !listError ? <CaseSelector cases={cases} selectedId={selectedId} unknownId={unknownId} onChange={selectCase} /> : null}
      {listLoading || loading ? <div className="panel empty-state">Loading coverage evidence…</div> : null}
      {!listLoading && !loading && error ? <div className="panel empty-state">{error}</div> : null}
      {!listLoading && !listError && !loading && !error && !selectedId && !unknownId && cases.length === 0 ? <div className="panel empty-state">No investigations yet. Use Start an investigation from Investigations.</div> : null}
      {!listLoading && !listError && !loading && !error && selectedId && caseFile ? (
        <>
          <CaseEvidenceSummary caseFile={caseFile} />
          <div className="panel">
            <div className="section-head">
              <h2 className="section-title" style={{ margin: 0 }}>Saved test coverage</h2>
            </div>
            {coverage.length === 0 ? (
              <p className="muted">No coverage assessment has been persisted.</p>
            ) : (
              <div className="card-grid">
                {coverage.map((item, index) => {
                  const record = item as Record<string, unknown>
                      const observed = String(record.grader_observed ?? 'unknown')
                      const observedLabel = observed === 'detected' ? 'Checker saw a problem' : observed === 'missed' ? 'Checker did not see a problem' : 'Not determined'
                      return (
                        <article className="nested-card" key={String(record.assessment_id ?? index)}>
                          <div className="section-head">
                            <strong>{String(record.condition ?? 'condition')}</strong>
                            <StatusBadge label={observedLabel} tone={observed === 'detected' ? 'success' : observed === 'missed' ? 'failure' : 'info'} />
                          </div>
                          <p>{String(record.notes ?? 'This situation has a saved coverage assessment.')}</p>
                          <details>
                            <summary>Technical details</summary>
                            <p className="muted">Original suite: {String(record.original_suite ?? 'unknown')}</p>
                            <p className="muted">Checker result: {observed}</p>
                            <p className="mono">Suspect {String(record.suspect_count ?? 0)} · Reviewed {String(record.reviewed_good_count ?? 0)}</p>
                          </details>
                    </article>
                  )
                })}
              </div>
            )}
          </div>
        </>
      ) : null}
    </div>
  )
}
