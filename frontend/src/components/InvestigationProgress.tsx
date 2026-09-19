import type { ProgressStep } from '../data/mockData'

export function InvestigationProgress({ steps }: { steps: ProgressStep[] }) {
  return (
    <div className="panel">
      <h2 className="section-title">Investigation Progress</h2>
      <div className="progress-pipeline">
        {steps.map((step) => (
          <div key={step.label} className="progress-step">
            <div className="progress-marker">
              <div className={`progress-dot ${step.state}`} />
              <div className="progress-connector" />
            </div>
            <div className={`progress-label ${step.state}`}>{step.label}</div>
          </div>
        ))}
      </div>
    </div>
  )
}
