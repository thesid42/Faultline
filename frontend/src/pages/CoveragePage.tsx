import { Link } from 'react-router-dom'
import { PageHeader } from '../components/PageHeader'
import { StatusBadge } from '../components/StatusBadge'
import { useCase, useCases } from '../context/CaseContext'

export function CoveragePage() {
  const { cases, loading: listLoading } = useCases()
  const selected = cases[cases.length - 1]?.caseid
  const { caseFile, loading, error } = useCase(selected)
  const coverage = Array.isArray(caseFile?.coverage) ? caseFile.coverage : []
  return <div>
    <PageHeader title="Coverage" subtitle="Coverage assessments recorded in the selected case file." />
    {listLoading || loading ? <div className="panel empty-state">Loading coverage evidence…</div> : null}
    {!listLoading && !loading && error ? <div className="panel empty-state">{error}</div> : null}
    {!listLoading && !loading && !error && !selected ? <div className="panel empty-state">No cases are available.</div> : null}
    {!listLoading && !loading && !error && selected ? <div className="panel"><div className="section-head"><h2 className="section-title" style={{ margin: 0 }}>Case <span className="mono">{selected}</span></h2><Link className="btn btn-secondary" to={`/investigations/${selected}?tab=coverage`}>Open case</Link></div>{coverage.length === 0 ? <p className="muted">No coverage assessment has been persisted.</p> : <div className="card-grid">{coverage.map((item, index) => { const record = item as Record<string, unknown>; const observed = String(record.grader_observed ?? 'unknown'); return <article className="nested-card" key={String(record.assessment_id ?? index)}><div className="section-head"><strong>{String(record.condition ?? 'condition')}</strong><StatusBadge label={observed} tone={observed === 'detected' ? 'success' : observed === 'missed' ? 'failure' : 'info'} /></div><p className="muted">Original suite: {String(record.original_suite ?? 'unknown')}</p><p>{String(record.notes ?? 'No notes recorded.')}</p><p className="mono">Suspect {String(record.suspect_count ?? 0)} · Reviewed {String(record.reviewed_good_count ?? 0)}</p></article> })}</div>}</div> : null}
  </div>
}
