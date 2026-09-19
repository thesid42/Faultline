import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { PageHeader } from '../components/PageHeader'
import { StatusBadge } from '../components/StatusBadge'
import { CaseEvidenceSummary } from '../components/CaseEvidenceSummary'
import { RunningCaseLoader } from '../components/RunningCaseLoader'
import { displayValue, formatDate, shortCaseId, useCase, useCases } from '../context/CaseContext'
import { deleteCase, getCapabilities, InvestigationRequestError } from '../api/investigations'
import { friendlyCaseTitle, summarizeInvestigation, type InvestigationSummary } from '../lib/investigationSummary'

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

const familyTitles: Record<string, string> = {
  policy: 'Refund policy',
  policy_retrieval: 'Refund policy',
  memory: 'Customer notes',
  memory_conflict: 'Customer notes',
  amount_units: 'Dollars and cents',
  idempotency: 'Repeated refunds',
  execution: 'Refund execution',
}

function hypothesisFamily(hypothesis: Row): string {
  const family = String(row(hypothesis.predicates).family ?? '').toLowerCase()
  return familyTitles[family] ?? 'Possible explanation'
}

function hypothesisState(status: string, complete: boolean) {
  if (status === 'supported') return { label: complete ? 'Supported by tests' : 'Preliminary support', tone: complete ? 'success' as const : 'warning' as const, icon: '✓', className: complete ? 'supported' : 'preliminary' }
  if (status === 'unknown') return { label: 'Not confirmed', tone: 'warning' as const, icon: '?', className: 'unknown' }
  if (status === 'open') return { label: 'Not yet tested', tone: 'info' as const, icon: '○', className: 'open' }
  if (status === 'rejected' || status === 'refuted') return { label: 'Not supported', tone: 'failure' as const, icon: '×', className: 'rejected' }
  return { label: 'Unknown status', tone: 'info' as const, icon: '?', className: 'neutral' }
}

function hypothesisRationale(hypothesis: Row, status: string): string {
  const rationale = String(hypothesis.rationale ?? '').trim()
  if (status === 'unknown' && /(incomplete|contradictory)/i.test(rationale)) return 'The checks did not provide enough consistent evidence.'
  return rationale || 'No testing result has been recorded yet.'
}

function HypothesesPanel({ hypotheses, complete }: { hypotheses: Row[]; complete: boolean }) {
  const ordered = hypotheses.map((hypothesis, index) => ({ hypothesis, index })).sort((left, right) => {
    const leftSupported = String(left.hypothesis.status ?? '').toLowerCase() === 'supported' ? 0 : 1
    const rightSupported = String(right.hypothesis.status ?? '').toLowerCase() === 'supported' ? 0 : 1
    return leftSupported - rightSupported || left.index - right.index
  })
  return <div className="panel">
    <h2 className="section-title">Possible causes</h2>
    <p className="muted">These are ideas the investigation tested. Highlighted results are recorded evidence, not proof of a universal cause.</p>
    {ordered.length === 0 ? <p className="muted">No possible causes have been recorded yet.</p> : <div className="hypothesis-card-grid">{ordered.map(({ hypothesis }) => {
      const status = String(hypothesis.status ?? 'unknown').toLowerCase()
      const state = hypothesisState(status, complete)
      const statement = String(hypothesis.statement ?? 'No explanation recorded.')
      const rationale = hypothesisRationale(hypothesis, status)
      return <article className={`hypothesis-card ${state.className}`} key={String(hypothesis.hypothesis_id ?? statement)}>
        <div className="hypothesis-card-header">
          <span className="hypothesis-icon" aria-hidden="true">{state.icon}</span>
          <div className="hypothesis-card-heading"><h3>{hypothesisFamily(hypothesis)}</h3><span className="muted">Possible explanation</span></div>
          <StatusBadge label={state.label} tone={state.tone} />
        </div>
        <p className="hypothesis-statement">{statement}</p>
        <div className="hypothesis-testing"><strong>What testing showed</strong><p>{rationale}</p></div>
        <details className="hypothesis-technical"><summary>Technical evidence</summary><pre className="raw-json">{displayValue({ hypothesis_id: hypothesis.hypothesis_id, statement: hypothesis.statement, rationale: hypothesis.rationale, predicates: hypothesis.predicates })}</pre></details>
      </article>
    })}</div>}
  </div>
}

function ResultsView({ summary, onReviewProposal }: { summary: InvestigationSummary; onReviewProposal: () => void }) {
  return (
    <div className="overview-grid" aria-label="Investigation results">
      <div className="panel result-tile result-observation">
        <div className="result-tile-label"><span aria-hidden="true">◉</span> Observation</div>
        <h2 className="section-title">What happened?</h2>
        <p><strong>{summary.happened}</strong></p>
        <p className="muted" style={{ marginBottom: 0 }}>{summary.happenedDetail}</p>
      </div>
      <div className="panel result-tile result-finding">
        <div className="result-tile-label"><span aria-hidden="true">✦</span> Finding</div>
        <h2 className="section-title">What did we find?</h2>
        <div className="stack-list">
          {summary.findings.map((finding, index) => <div key={`${finding}-${index}`}>{finding}</div>)}
        </div>
      </div>
      <div className="panel result-tile result-next">
        <div className="result-tile-label"><span aria-hidden="true">→</span> Next step</div>
        <h2 className="section-title">What should I do next?</h2>
        <ol style={{ margin: 0, paddingLeft: 20 }}>
          {summary.nextSteps.map((step, index) => <li key={`${step}-${index}`} style={{ marginBottom: 8 }}>{step.startsWith('Review the suggested test') ? <><span>{step}</span> <button type="button" className="btn btn-secondary" onClick={onReviewProposal}>Review suggested test</button></> : step}</li>)}
        </ol>
      </div>
      <div className="panel result-tile result-status">
        <div className="result-tile-label"><span aria-hidden="true">◷</span> Run status</div>
        <h2 className="section-title">Progress</h2>
        <p>{summary.progress}</p>
        <p className="muted" style={{ marginBottom: 0 }}>{summary.evidenceNote}</p>
      </div>
    </div>
  )
}

export function InvestigationPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { refresh: refreshCases } = useCases()
  const { caseFile, loading, refreshing, error } = useCase(id)
  const [searchParams, setSearchParams] = useSearchParams()
  const [selectedEvent, setSelectedEvent] = useState(0)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const requestedTab = searchParams.get('tab')
  const activeTab: Tab = requestedTab && tabs.includes(requestedTab as Tab) ? requestedTab as Tab : 'overview'
  const [technicalOpen, setTechnicalOpen] = useState(Boolean(requestedTab))
  useEffect(() => {
    if (requestedTab) setTechnicalOpen(true)
  }, [requestedTab])

  const incident = row(caseFile?.incident)
  const runs = rows(caseFile?.runs)
  const incidentRunId = String(incident.run_id ?? '')
  const sourceRunId = String(caseFile?.source_run_id ?? incidentRunId)
  const sourceRun = sourceRunId ? runs.find((item) => item.run_id === sourceRunId) : undefined
  const events = rows(sourceRun?.events)
  const hypotheses = rows(caseFile?.hypotheses)
  const experiments = rows(caseFile?.experiment_results)
  const observations = rows(caseFile?.observations)
  const coverage = rows(caseFile?.coverage)
  const budget = row(caseFile?.budget)
  const proposal = caseFile?.proposal ? row(caseFile.proposal) : null
  const proposalReviewed = Boolean(proposal?.reviewed === true && typeof proposal.approval_digest === 'string' && proposal.approval_digest && proposal.approval_digest === proposal.digest)
  const summary = caseFile ? summarizeInvestigation(caseFile) : null
  const selectedEventRow = events[selectedEvent] ?? events[0]
  const status = String(caseFile?.status ?? 'unknown')
  const friendlyTitle = friendlyCaseTitle(caseFile?.demo_profile)
  const headerStatus = status === 'complete' ? 'Finished' : status === 'investigating' ? 'Running' : status === 'queued' ? 'Waiting' : status === 'inconclusive' ? 'Needs attention' : 'Status unavailable'
  const latestObservation = observations[observations.length - 1]
  const stage = typeof latestObservation?.stage === 'string' ? latestObservation.stage : typeof latestObservation?.kind === 'string' ? latestObservation.kind : 'not recorded'
  const stageStatus = typeof latestObservation?.status === 'string' ? latestObservation.status : null
  const canDelete = Boolean(id && caseFile && status !== 'queued' && status !== 'investigating')
  const isRunning = status === 'queued' || status === 'investigating'

  const experimentCounts = useMemo(() => {
    return experiments.reduce<Record<string, number>>((counts, item) => {
      const key = String(item.status ?? 'unknown')
      counts[key] = (counts[key] ?? 0) + 1
      return counts
    }, {})
  }, [experiments])

  const setTab = (tab: Tab) => {
    setTechnicalOpen(true)
    setSearchParams({ tab })
  }

  const onDelete = async () => {
    if (!id || !canDelete || deleting) return
    const confirmed = window.confirm(`Delete investigation ${shortCaseId(id)}? This removes the saved case and its evidence from the local database.`)
    if (!confirmed) return
    setDeleting(true)
    setDeleteError(null)
    try {
      const capabilities = await getCapabilities()
      if (!capabilities.csrf_token) throw new Error('Delete token unavailable')
      await deleteCase(id, capabilities.csrf_token)
      await refreshCases()
      navigate('/incidents')
    } catch (cause) {
      const message = cause instanceof InvestigationRequestError
        ? cause.message
        : cause instanceof Error
          ? cause.message
          : 'Unable to delete this investigation'
      setDeleteError(message)
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div className="page-shell">
      <PageHeader
        title={friendlyTitle}
        subtitle={headerStatus}
        actions={(
          <div className="page-header-actions">
            <StatusBadge label={headerStatus} tone={tone(status)} />
            {isRunning ? <span className="status-spinner" aria-hidden /> : null}
            <button
              type="button"
              className="btn btn-secondary"
              disabled={!canDelete || deleting}
              title={canDelete ? 'Delete this saved investigation' : 'Wait for the investigation to finish before deleting.'}
              onClick={() => void onDelete()}
            >
              {deleting ? 'Deleting…' : 'Delete'}
            </button>
          </div>
        )}
      >
        <div className="inv-header-meta">
          <span>{caseFile?.evidence_origin === 'simulated' ? 'Practice evidence' : caseFile?.evidence_origin === 'live' ? 'Live evidence' : 'Evidence origin unknown'}</span>
          <span>·</span>
          <span>{isRunning || refreshing ? 'refreshing…' : 'Updates automatically'}</span>
        </div>
      </PageHeader>

      <LoadingOrError loading={loading} error={error} />
      {deleteError ? <div className="panel empty-state" role="alert"><strong>Delete failed.</strong><br />{deleteError}</div> : null}
      {!loading && !error && !caseFile ? <div className="panel empty-state">This case was not found.</div> : null}
      {!loading && !error && caseFile ? <>
        {isRunning ? <RunningCaseLoader status={status} progress={summary?.progress} refreshing={refreshing} /> : null}
        {!isRunning && summary ? <ResultsView summary={summary} onReviewProposal={() => setTab('regression')} /> : null}
        {isRunning && summary ? (
          <div className="panel running-partial" style={{ marginTop: 16 }}>
            <h2 className="section-title">Evidence so far</h2>
            <p className="muted">{summary.progress}</p>
            <div className="case-meta-grid">
              <div><span className="metric-label">Runs recorded</span><strong>{runs.length}</strong></div>
              <div><span className="metric-label">Experiments</span><strong>{experiments.length}</strong></div>
              <div><span className="metric-label">Possible causes</span><strong>{hypotheses.length}</strong></div>
              <div><span className="metric-label">Latest stage</span><strong>{stage}{stageStatus ? ` · ${stageStatus}` : ''}</strong></div>
            </div>
          </div>
        ) : null}
        <details className="panel" open={technicalOpen} onToggle={(event) => setTechnicalOpen(event.currentTarget.open)} style={{ marginTop: 16 }}>
          <summary className="section-title" style={{ cursor: 'pointer' }}>Technical details</summary>
          <CaseEvidenceSummary caseFile={caseFile} />
          <div className="tabs">
            {tabs.map((tab) => <button key={tab} type="button" className={`tab${activeTab === tab ? ' active' : ''}`} onClick={() => setTab(tab)}>{tab === 'hypotheses' ? 'Possible causes' : tab.charAt(0).toUpperCase() + tab.slice(1)}</button>)}
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
            <div className="panel">
              <h2 className="section-title">Investigation progress</h2>
              <div className="stack-list">
                <div><span>Case status</span><strong>{status}</strong></div>
                <div><span>Latest recorded stage</span><strong>{stage}{stageStatus ? ` · ${stageStatus}` : ''}</strong></div>
                <div><span>Target trials</span><strong>{String(budget.target_trials ?? '—')}</strong></div>
                <div><span>Investigator calls</span><strong>{String(budget.investigator_calls ?? '—')}</strong></div>
                <div><span>Jev calls</span><strong>{String(budget.jev_calls ?? '—')}</strong></div>
              </div>
              <p className="muted" style={{ marginBottom: 0 }}>Background runs can continue after this tab closes. Stop reason: {caseFile.stop_reason || 'not recorded'}.</p>
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

          {activeTab === 'hypotheses' ? <HypothesesPanel hypotheses={hypotheses} complete={status === 'complete'} /> : null}

          {activeTab === 'experiments' ? <div className="panel">
            <div className="section-head"><h2 className="section-title" style={{ margin: 0 }}>Experiments</h2><button type="button" className="btn btn-secondary" disabled title="Run experiments from the Faultline CLI.">Run from CLI</button></div>
            {experiments.length === 0 ? <p className="muted">No experiment results recorded.</p> : <div className="table-wrap"><table className="table"><thead><tr><th>Trial</th><th>Configuration</th><th>Status</th><th>Violation</th><th>Origin</th></tr></thead><tbody>{experiments.map((experiment) => <tr key={String(experiment.trial_id)}><td><span className="mono cell-id" title={String(experiment.trial_id)}>{shortCaseId(String(experiment.trial_id), 10)}</span></td><td>{String(experiment.configuration_id ?? '—')}</td><td><StatusBadge label={String(experiment.status ?? 'unknown')} tone={tone(String(experiment.status ?? 'unknown'))} /></td><td>{experiment.observed_violation === true ? 'Yes' : experiment.observed_violation === false ? 'No' : 'Unknown'}</td><td>{String(experiment.evidence_origin ?? 'unknown')}</td></tr>)}</tbody></table></div>}
          </div> : null}

          {activeTab === 'coverage' ? <div className="panel"><h2 className="section-title">Coverage assessments</h2>{coverage.length === 0 ? <p className="muted">No coverage assessment recorded.</p> : <div className="card-grid">{coverage.map((item, index) => <article className="nested-card" key={String(item.assessment_id ?? index)}><div className="section-head"><strong>{String(item.condition ?? 'condition')}</strong><StatusBadge label={String(item.grader_observed ?? 'unknown')} tone={tone(String(item.grader_observed ?? 'unknown'))} /></div><p className="muted">Original suite: {String(item.original_suite ?? 'unknown')}</p><p>{String(item.notes ?? 'No notes recorded.')}</p><p className="mono">Detected {String(item.detected_count ?? 0)} · Missed {String(item.missed_count ?? 0)}</p></article>)}</div>}</div> : null}

          {activeTab === 'regression' ? <div className="panel"><h2 className="section-title">Regression proposal</h2>{proposal ? <><StatusBadge label={proposalReviewed ? 'Reviewed' : 'Pending human review'} tone={proposalReviewed ? 'success' : 'warning'} /><p>{String(proposal.rationale ?? 'No rationale recorded.')}</p><pre className="raw-json">{displayValue(proposal.tests)}</pre><p className="muted">Digest: {String(proposal.digest ?? 'not recorded')}</p><button type="button" className="btn btn-secondary" disabled title="Proposal approval is handled outside the read-only UI.">Approval via CLI / review workflow</button></> : <p className="muted">No regression proposal recorded for this case.</p>}</div> : null}
          </div>
        </details>
      </> : null}
    </div>
  )
}
