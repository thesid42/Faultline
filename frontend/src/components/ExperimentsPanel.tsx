import { ExperimentCard } from './ExperimentCard'
import { ExperimentChart } from './ExperimentChart'
import { ConfidenceIndicator } from './ConfidenceIndicator'
import type { Experiment } from '../data/mockData'
import { experimentChartData, experimentKeyFinding } from '../data/mockData'

interface ExperimentsPanelProps {
  filter: 'all' | 'causal' | 'control'
  setFilter: (v: 'all' | 'causal' | 'control') => void
  experiments: Experiment[]
  onRun: () => void
  standalone: boolean
}

export function ExperimentsPanel({
  filter,
  setFilter,
  experiments: list,
  onRun,
  standalone,
}: ExperimentsPanelProps) {
  return (
    <div>
      {standalone ? null : (
        <div className="exp-header-row">
          <div>
            <h2 className="section-title" style={{ marginBottom: 4 }}>
              Experiments
            </h2>
            <p className="page-subtitle" style={{ margin: 0 }}>
              Test hypotheses with controlled interventions.
            </p>
          </div>
          <button type="button" className="btn btn-primary" onClick={onRun}>
            + Run experiment
          </button>
        </div>
      )}

      <div className="tabs">
        <button type="button" className={`tab${filter === 'all' ? ' active' : ''}`} onClick={() => setFilter('all')}>
          All Experiments
        </button>
        <button
          type="button"
          className={`tab${filter === 'causal' ? ' active' : ''}`}
          onClick={() => setFilter('causal')}
        >
          Causal Tests
        </button>
        <button
          type="button"
          className={`tab${filter === 'control' ? ' active' : ''}`}
          onClick={() => setFilter('control')}
        >
          Control Tests
        </button>
      </div>

      <div className="exp-cards">
        {list.slice(0, 2).map((exp) => (
          <ExperimentCard key={exp.id} experiment={exp} />
        ))}
      </div>

      <div className="viz-row">
        <ExperimentChart data={experimentChartData} />
        <div className="panel">
          <h2 className="section-title">Key Finding</h2>
          <ConfidenceIndicator value={experimentKeyFinding.confidence} large />
          <p style={{ margin: '18px 0 8px', fontWeight: 600, fontSize: 16 }}>{experimentKeyFinding.title}</p>
          <p className="muted" style={{ margin: 0, fontSize: 13.5 }}>
            {experimentKeyFinding.subtext}
          </p>
        </div>
      </div>
    </div>
  )
}
