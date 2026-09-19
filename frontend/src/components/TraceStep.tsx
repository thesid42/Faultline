import type { TraceStep as TraceStepType } from '../data/mockData'

interface TraceStepProps {
  step: TraceStepType
  selected: boolean
  onSelect: (id: string) => void
  isLast: boolean
}

export function TraceStep({ step, selected, onSelect, isLast }: TraceStepProps) {
  return (
    <div
      className={`trace-step ${step.status}${selected ? ' selected' : ''}`}
      onClick={() => onSelect(step.id)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') onSelect(step.id)
      }}
    >
      <div className="trace-rail">
        <div className={`trace-dot ${step.status}`} />
        {!isLast ? <div className="trace-line" /> : null}
      </div>
      <div>
        <div className="trace-step-body">
          <span className="trace-step-name">
            {step.order} {step.name}
          </span>
          <span className="trace-step-meta">{step.duration}</span>
        </div>
        <div className="trace-step-meta" style={{ textTransform: 'capitalize' }}>
          {step.status === 'failed' ? 'FAILED' : step.status}
        </div>
      </div>
    </div>
  )
}
