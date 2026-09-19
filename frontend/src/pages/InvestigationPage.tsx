import { useMemo, useState } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { PageHeader } from '../components/PageHeader'
import { StatusBadge } from '../components/StatusBadge'
import { displayValue, formatCaseLabel, formatDate, useCase } from '../context/CaseContext'

const tabs = ['overview', 'trace', 'hypotheses', 'experiments', 'coverage', 'regression'] as const
type Tab = (typeof tabs)[number]
type Row = Record<string, unknown>

function rows(value: unknown): Row[] {
  return Array.isArray(value) ? value.filter((item): item is Row => Boolean(item && typeof item === 'object')) : []
}

function row(value: unknown): Row {
  return value && typeof value === 'object' ? value as Row : {}
}

function tone(status: string) {
  if (status === 'complete' || status === 'completed' || status === 'supported') return 'success' as const
  if (status === 'inconclusive' || status === 'failed' || status === 'invalid' || status === 'rejected') return 'failure' as const
  if (status === 'investigating' || status === 'infrastructure_error') return 'investigating' as const
  return 'info' as const
}

function LoadingOrError({ loading, error }: { loading: boolean; error: string | null }) {
  if (loading) return <div className="panel empty-state">Loading the persisted case file…</div>
  if (error) return <div className="panel empty-state"><strong>Unable to load this case.</strong><br />{error}</div>
  return null
}

export function InvestigationPage() {
  const { id } = useParams()
  const { caseFile, loading, refreshing, error } = useCase(id)
  const [searchParams, setSearchParams] = useSearchParams()
  const [selectedEvent, setSelectedEvent] = useState(0)
  const requestedTab = searchParams.get('tab')
  const activeTab: Tab = requestedTab && tabs.includes(requestedTab as Tab) ? requestedTab as Tab : 'overview'

  const incident = row(caseFile?.incident)
  const runs = rows(caseFile?.runs)
  const incidentRunId = String(incident.run_id ?? '')
  const sourceRunId = String(caseFile?.source_run_id ?? incidentRunId)
  const sourceRun = sourceRunId ? runs.find((item) => item.run_id === sourceRunId) : undefined
  const events = rows(sourceRun?.events)
  const hypotheses = rows(caseFile?.hypotheses)
  const experiments = rows(caseFile?.experiment_results)
  const coverage = rows(caseFile?.coverage)
  const proposal = caseFile?.proposal ? row(caseFile.proposal) : null
  const proposalReviewed = Boolean(proposal?.reviewed === true && typeof proposal.approval_digest === 'string' && proposal.approval_digest && proposal.approval_digest === proposal.digest)
  const selectedEventRow = events[selectedEvent] ?? events[0]
  const title = formatCaseLabel(caseFile?.demo_profile ?? id)
  const status = String(caseFile?.status ?? 'unknown')

  const experimentCounts = useMemo(() => {
    return experiments.reduce<Record<string, number>>((counts, item) => {
      const key = String(item.status ?? 'unknown')
      counts[key] = (counts[key] ?? 0) + 1
      return counts
    }, {})
  }, [experiments])

  const setTab = (tab: Tab) => setSearchParams({ tab })

  return (
    <div>
      <PageHeader title={`Case ${id ?? '—'}`} subtitle={title} actions={<StatusBadge label={status} tone={tone(status)} />}>
        <div className="inv-header-meta">
          <span>{caseFile?.evidence_origin ?? 'origin unknown'}</span><span>·</span>
          <span>{caseFile?.backend ?? 'backend unknown'}</span><span>·</span>
          <span>{refreshing ? 'refreshing…' : 'live API snapshot'}</span>
        </div>
      </PageHeader>

      <LoadingOrError loading={loading} error={error} />
      {!loading && !error && !caseFile ? <div className="panel empty-state">This case was not found.</div> : null}
      {!loading && !error && caseFile ? <>
        <div className="tabs">
          {tabs.map((tab) => <button key={tab} type="button" className={`tab${activeTab === tab ? ' active' : ''}`} onClick={() => setTab(tab)}>{tab.charAt(0).toUpperCase() + tab.slice(1)}</button>)}
        </div>

        <div className="tab-panel">
          {activeTab === 'overview' ? <div className="overview-grid">
            <div className="panel">
              <h2 className="section-title">Observed case</h2>
              <p className="muted">{String(incident.status ?? caseFile.stop_reason ?? 'No incident summary recorded.')}</p>
              <div className="case-meta-grid">
                <div><span className="metric-label">Source run</span><strong className="mono">{String(caseFile.source_run_id ?? '—')}</strong></div>
                <div><span className="metric-label">Runs</span><strong>{runs.length}</strong></div>
                <div><span className="metric-label">Hypotheses</span><strong>{hypotheses.length}</strong></div>
                <div><span className="metric-label">Experiments</span><strong>{experiments.length}</strong></div>
              </div>
              <p className="muted" style={{ marginBottom: 0 }}>Stop reason: {caseFile.stop_reason || 'not recorded'}</p>
            </div>
            <div className="panel">
              <h2 className="section-title">Evidence status</h2>
              <div className="stack-list">
                <div><span>Completed experiment results</span><strong>{experimentCounts.completed ?? 0}</strong></div>
                <div><span>Invalid / infrastructure results</span><strong>{(experimentCounts.invalid ?? 0) + (experimentCounts.infrastructure_error ?? 0)}</strong></div>
                <div><span>Coverage assessments</span><strong>{coverage.length}</strong></div>
                <div><span>Regression proposal</span><strong>{proposal ? 'Recorded' : 'Not recorded'}</strong></div>
              </div>
            </div>
          </div> : null}

          {activeTab === 'trace' ? <div className="split-38-62">
            <div className="panel">
              <h2 className="section-title">Execution trace</h2>
              {events.length === 0 ? <p className="muted">No trace events were persisted for the source run.</p> : <div className="stack-list">{events.map((event, index) => <button type="button" className={`trace-row${selectedEvent === index ? ' selected' : ''}`} key={String(event.event_id ?? index)} onClick={() => setSelectedEvent(index)}><span className="mono">{String(event.kind ?? 'event')}</span><span className="muted">{formatDate(event.at)}</span></button>)}</div>}
            </div>
            <div className="panel">
              <h2 className="section-title">Event details</h2>
              {selectedEventRow ? <pre className="raw-json">{displayValue(selectedEventRow)}</pre> : <p className="muted">Select a persisted event to inspect it.</p>}
            </div>
          </div> : null}

          {activeTab === 'hypotheses' ? <div className="panel">
            <h2 className="section-title">Hypotheses</h2>
            {hypotheses.length === 0 ? <p className="muted">No hypotheses recorded.</p> : <div className="card-grid">{hypotheses.map((hypothesis) => { const state = String(hypothesis.status ?? 'unknown'); return <article className="panel nested-card" key={String(hypothesis.hypothesis_id)}><div className="section-head"><strong>{String(hypothesis.hypothesis_id)}</strong><StatusBadge label={state} tone={tone(state)} /></div><p>{String(hypothesis.statement ?? 'No statement recorded.')}</p><p className="muted">{String(hypothesis.rationale ?? 'No rationale recorded.')}</p><div className="mono">Predicates: {displayValue(hypothesis.predicates)}</div></article> })}</div>}
          </div> : null}

          {activeTab === 'experiments' ? <div className="panel">
            <div className="section-head"><h2 className="section-title" style={{ margin: 0 }}>Experiments</h2><button type="button" className="btn btn-secondary" disabled title="Run experiments from the Faultline CLI.">Run from CLI</button></div>
            {experiments.length === 0 ? <p className="muted">No experiment results recorded.</p> : <div className="table-wrap"><table className="table"><thead><tr><th>Trial</th><th>Configuration</th><th>Status</th><th>Violation</th><th>Origin</th></tr></thead><tbody>{experiments.map((experiment) => <tr key={String(experiment.trial_id)}><td className="mono">{String(experiment.trial_id)}</td><td>{String(experiment.configuration_id ?? '—')}</td><td><StatusBadge label={String(experiment.status ?? 'unknown')} tone={tone(String(experiment.status ?? 'unknown'))} /></td><td>{experiment.observed_violation === true ? 'Yes' : experiment.observed_violation === false ? 'No' : 'Unknown'}</td><td>{String(experiment.evidence_origin ?? 'unknown')}</td></tr>)}</tbody></table></div>}
          </div> : null}

          {activeTab === 'coverage' ? <div className="panel"><h2 className="section-title">Coverage assessments</h2>{coverage.length === 0 ? <p className="muted">No coverage assessment recorded.</p> : <div className="card-grid">{coverage.map((item, index) => <article className="nested-card" key={String(item.assessment_id ?? index)}><div className="section-head"><strong>{String(item.condition ?? 'condition')}</strong><StatusBadge label={String(item.grader_observed ?? 'unknown')} tone={tone(String(item.grader_observed ?? 'unknown'))} /></div><p className="muted">Original suite: {String(item.original_suite ?? 'unknown')}</p><p>{String(item.notes ?? 'No notes recorded.')}</p><p className="mono">Detected {String(item.detected_count ?? 0)} · Missed {String(item.missed_count ?? 0)}</p></article>)}</div>}</div> : null}

          {activeTab === 'regression' ? <div className="panel"><h2 className="section-title">Regression proposal</h2>{proposal ? <><StatusBadge label={proposalReviewed ? 'Reviewed' : 'Pending human review'} tone={proposalReviewed ? 'success' : 'warning'} /><p>{String(proposal.rationale ?? 'No rationale recorded.')}</p><pre className="raw-json">{displayValue(proposal.tests)}</pre><p className="muted">Digest: {String(proposal.digest ?? 'not recorded')}</p><button type="button" className="btn btn-secondary" disabled title="Proposal approval is handled outside the read-only UI.">Approval via CLI / review workflow</button></> : <p className="muted">No regression proposal recorded for this case.</p>}</div> : null}
        </div>
      </> : null}
    </div>
  )
}
