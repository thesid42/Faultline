import type { Experiment } from '../data/mockData'
import { BeforeAfterComparison } from './BeforeAfterComparison'
import { StatusBadge } from './StatusBadge'

interface ExperimentCardProps {
  experiment: Experiment
}

export function ExperimentCard({ experiment }: ExperimentCardProps) {
  const pct = Math.round((experiment.runsPassed / experiment.runsTotal) * 100)

  return (
    <div className="panel">
      <div className="exp-card-top">
        <div>
          <div className="exp-code">{experiment.code}</div>
          <h3 className="exp-title">{experiment.title}</h3>
          <p className="exp-desc">{experiment.description}</p>
        </div>
        <StatusBadge label={experiment.kind} tone={experiment.kind === 'Causal Test' ? 'teal' : 'info'} />
      </div>

      <BeforeAfterComparison before={experiment.before} after={experiment.after} />

      <div className="exp-footer">
        <span style={{ fontWeight: 500 }}>
          {experiment.runsPassed} / {experiment.runsTotal} {experiment.signalPositive ? 'runs' : 'safe outcomes'}
        </span>
        <span style={{ color: experiment.signalPositive ? '#0f766e' : 'var(--failure)', fontWeight: 500 }}>
          {experiment.signal}
        </span>
      </div>
      <div className={`exp-progress${experiment.signalPositive ? '' : ' negative'}`}>
        <span className="progress-fill" style={{ width: `${Math.max(pct, experiment.signalPositive ? 100 : 12)}%` }} />
      </div>
    </div>
  )
}
