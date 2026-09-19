import { Link } from 'react-router-dom'
import { PageHeader } from '../components/PageHeader'
import { StatusBadge } from '../components/StatusBadge'
import { CaseEvidenceSummary } from '../components/CaseEvidenceSummary'
import { CaseSelector, useCaseSelection } from '../components/CaseSelector'
import { displayValue, useCase, useCases } from '../context/CaseContext'

function operationLabel(value: unknown) {
  const labels: Record<string, string> = {
    baseline: 'Baseline check',
    remove_note: 'Remove a note',
    unrelated_note: 'Change an unrelated note',
    refund_api_unit: 'Check refund amount units',
    delivery_attempts: 'Check delivery attempts',
  }
  return labels[String(value)] ?? 'Recorded operation'
}

function runStatusLabel(value: unknown) {
  if (value === 'completed') return 'Finished'
  if (value === 'infrastructure_error') return 'Needs attention'
  if (value === 'excluded') return 'Not used as evidence'
  return String(value ?? 'unknown').replace(/[-_]+/g, ' ')
}

export function ExperimentsPage() {
  const { cases, loading: listLoading, error: listError } = useCases()
  const { selectedId, unknownId, selectCase } = useCaseSelection(cases)
  const { caseFile, loading, error } = useCase(selectedId)
  const experiments = Array.isArray(caseFile?.experiment_results) ? caseFile.experiment_results : []
  return (
    <div className="page-shell">
      <PageHeader title="Test runs" subtitle="Each row is a saved check. These results are evidence, not a diagnosis." actions={selectedId ? <Link className="btn btn-secondary" to={`/investigations/${selectedId}`}>Back to results</Link> : null} />
      {!listLoading && listError ? <div className="panel empty-state"><strong>Unable to load cases.</strong><br />{listError}</div> : null}
      {!listLoading && !listError ? <CaseSelector cases={cases} selectedId={selectedId} unknownId={unknownId} onChange={selectCase} /> : null}
      {listLoading || loading ? <div className="panel empty-state">Loading experiment evidence…</div> : null}
      {!listLoading && !loading && error ? <div className="panel empty-state">{error}</div> : null}
      {!listLoading && !listError && !loading && !error && !selectedId && !unknownId && cases.length === 0 ? <div className="panel empty-state">No investigations yet. Use Start an investigation from Investigations.</div> : null}
      {!listLoading && !listError && !loading && !error && selectedId && caseFile ? (
        <>
          <CaseEvidenceSummary caseFile={caseFile} />
          <div className="panel">
            <div className="section-head">
              <h2 className="section-title" style={{ margin: 0 }}>Recorded test runs</h2>
            </div>
            {experiments.length === 0 ? (
              <p className="muted">This case has no experiment results.</p>
            ) : (
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>What was checked</th>
                      <th>Status</th>
                      <th>What the checker found</th>
                      <th>Technical details</th>
                    </tr>
                  </thead>
                  <tbody>
                    {experiments.map((item, index) => {
                      const record = item as Record<string, unknown>
                      const status = String(record.status ?? 'unknown')
                      return (
                        <tr key={String(record.trial_id ?? `${status}-${index}`)}>
                          <td>{operationLabel((record.activation as Record<string, unknown> | undefined)?.operator)}</td>
                          <td><StatusBadge label={runStatusLabel(status)} tone={status === 'completed' ? 'success' : status === 'infrastructure_error' ? 'failure' : 'info'} /></td>
                          <td>{record.observed_violation === true ? 'Problem observed' : record.observed_violation === false ? 'No problem observed' : 'Not determined'}</td>
                          <td>
                            <details>
                              <summary>Show IDs and saved data</summary>
                              <pre className="raw-json">{displayValue(record)}</pre>
                            </details>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      ) : null}
    </div>
  )
}
