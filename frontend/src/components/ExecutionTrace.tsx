import type { ExecutionTrace as ExecutionTraceType } from '../data/mockData'
import { TraceStep } from './TraceStep'

interface ExecutionTraceProps {
  trace: ExecutionTraceType
  selectedId: string
  onSelect: (id: string) => void
}

export function ExecutionTrace({ trace, selectedId, onSelect }: ExecutionTraceProps) {
  return (
    <div className="panel">
      <h2 className="section-title">Execution Trace</h2>
      <div className="trace-list">
        {trace.steps.map((step, index) => (
          <TraceStep
            key={step.id}
            step={step}
            selected={selectedId === step.id}
            onSelect={onSelect}
            isLast={index === trace.steps.length - 1}
          />
        ))}
      </div>
      <div className="alert-card">
        <strong>Policy violation</strong>
        <p>{trace.policyViolation}</p>
      </div>
    </div>
  )
}
