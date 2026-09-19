import { useMemo, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { CoverageBars } from '../components/CoverageBars'
import { CoverageMatrix } from '../components/CoverageMatrix'
import { ExecutionTrace } from '../components/ExecutionTrace'
import { ExperimentsPanel } from '../components/ExperimentsPanel'
import { HypothesisGraph } from '../components/HypothesisGraph'
import { InvestigationProgress } from '../components/InvestigationProgress'
import { PageHeader } from '../components/PageHeader'
import { RegressionProposal } from '../components/RegressionProposal'
import { RunExperimentDialog } from '../components/RunExperimentDialog'
import { StepDetails } from '../components/StepDetails'
import { SeverityBadge, IncidentStatusBadge, StatusBadge } from '../components/StatusBadge'
import { useToast } from '../context/ToastContext'
import {
  coverageData,
  executionTrace,
  experiments,
  featuredIncident,
  getIncidentById,
  hypotheses,
  investigationProgress,
  regressionProposal,
} from '../data/mockData'

const tabs = ['overview', 'trace', 'hypotheses', 'experiments', 'coverage', 'regression'] as const
type Tab = (typeof tabs)[number]

export function InvestigationPage() {
  const { id = '021' } = useParams()
  const [searchParams, setSearchParams] = useSearchParams()
  const navigate = useNavigate()
  const { toast } = useToast()
  const incident = getIncidentById(id) ?? featuredIncident

  const tabParam = (searchParams.get('tab') as Tab) || 'overview'
  const activeTab: Tab = tabs.includes(tabParam) ? tabParam : 'overview'

  const failedStep = executionTrace.steps.find((s) => s.status === 'failed') ?? executionTrace.steps[0]
  const [selectedStepId, setSelectedStepId] = useState(failedStep.id)
  const [selectedHypothesisId, setSelectedHypothesisId] = useState(
    hypotheses.find((h) => h.status === 'Supported')?.id ?? hypotheses[0].id,
  )
  const [expFilter, setExpFilter] = useState<'all' | 'causal' | 'control'>('all')
  const [dialogOpen, setDialogOpen] = useState(false)

  const selectedStep = useMemo(
    () => executionTrace.steps.find((s) => s.id === selectedStepId) ?? failedStep,
    [selectedStepId, failedStep],
  )

  const filteredExperiments = experiments.filter((exp) => {
    if (expFilter === 'all') return true
    if (expFilter === 'causal') return exp.kind === 'Causal Test'
    return exp.kind === 'Control Test'
  })

  const setTab = (next: Tab) => {
    setSearchParams({ tab: next })
  }

  return (
    <div>
      <PageHeader
        title={`#${incident.id}`}
        subtitle={incident.title}
        actions={
          <div className="inv-badges">
            <SeverityBadge severity={incident.severity} />
            <IncidentStatusBadge status={incident.status} />
          </div>
        }
      >
        <div className="inv-header-meta">
          <span>{incident.model}</span>
          <span>·</span>
          <span>Sep 19, 2026 10:42 AM</span>
          <span>·</span>
          <StatusBadge label={incident.origin} tone="info" />
        </div>
      </PageHeader>

      <div className="tabs">
        {tabs.map((tab) => (
          <button
            key={tab}
            type="button"
            className={`tab${activeTab === tab ? ' active' : ''}`}
            onClick={() => setTab(tab)}
          >
            {tab.charAt(0).toUpperCase() + tab.slice(1)}
          </button>
        ))}
      </div>

      <div className="tab-panel" key={activeTab}>
        {activeTab === 'overview' ? (
          <div className="overview-grid">
            <div className="panel">
              <h2 className="section-title">Summary</h2>
              <p style={{ marginTop: 0, color: 'var(--text-secondary)', fontSize: 14 }}>
                Investigation of an unauthorized refund where a retrieved customer note conflicted with the current
                14-day refund policy. Causal experiments support a memory-conflict root cause.
              </p>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 16 }}>
                <StatusBadge label="Memory conflict" tone="purple" />
                <StatusBadge label="87% confidence" tone="info" />
                <StatusBadge label="Coverage gap open" tone="failure" />
              </div>
              <button type="button" className="btn btn-primary" onClick={() => setTab('trace')}>
                Open execution trace
              </button>
            </div>
            <InvestigationProgress steps={investigationProgress} />
          </div>
        ) : null}

        {activeTab === 'trace' ? (
          <div className="split-38-62">
            <ExecutionTrace trace={executionTrace} selectedId={selectedStepId} onSelect={setSelectedStepId} />
            <StepDetails key={selectedStep.id} step={selectedStep} />
          </div>
        ) : null}

        {activeTab === 'hypotheses' ? (
          <HypothesisGraph
            incidentTitle="Unauthorized refund"
            hypotheses={hypotheses}
            selectedId={selectedHypothesisId}
            onSelect={setSelectedHypothesisId}
          />
        ) : null}

        {activeTab === 'experiments' ? (
          <ExperimentsPanel
            filter={expFilter}
            setFilter={setExpFilter}
            experiments={filteredExperiments}
            onRun={() => setDialogOpen(true)}
            standalone={false}
          />
        ) : null}

        {activeTab === 'coverage' ? (
          <div>
            <CoverageBars bars={coverageData.bars} />
            <div style={{ height: 16 }} />
            <CoverageMatrix data={coverageData} />
          </div>
        ) : null}

        {activeTab === 'regression' ? <RegressionProposal proposal={regressionProposal} /> : null}
      </div>

      <RunExperimentDialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        onConfirm={() => {
          setDialogOpen(false)
          toast('Mock experiment queued.')
          navigate('/experiments')
        }}
      />
    </div>
  )
}
