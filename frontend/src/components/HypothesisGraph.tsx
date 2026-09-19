import type { Hypothesis } from '../data/mockData'
import { ConfidenceIndicator } from './ConfidenceIndicator'
import { HypothesisCard } from './HypothesisCard'
import { StatusBadge } from './StatusBadge'

interface HypothesisGraphProps {
  incidentTitle: string
  hypotheses: Hypothesis[]
  selectedId: string
  onSelect: (id: string) => void
}

export function HypothesisGraph({ incidentTitle, hypotheses, selectedId, onSelect }: HypothesisGraphProps) {
  const selected = hypotheses.find((h) => h.id === selectedId) ?? hypotheses[0]
  const ordered = [
    hypotheses.find((h) => h.title === 'Policy mismatch')!,
    hypotheses.find((h) => h.title === 'Memory Conflict')!,
    hypotheses.find((h) => h.title === 'Execution/tool failure')!,
  ].filter(Boolean)

  return (
    <div className="hyp-layout">
      <div className="panel hyp-graph">
        <div className="hyp-incident">
          <span className="label">INCIDENT</span>
          <strong>{incidentTitle}</strong>
        </div>
        <div className="hyp-branches">
          {ordered.map((hypothesis) => (
            <HypothesisCard
              key={hypothesis.id}
              hypothesis={hypothesis}
              selected={selected.id === hypothesis.id}
              onSelect={onSelect}
              showLinks={hypothesis.status === 'Supported'}
            />
          ))}
        </div>
      </div>

      <div className="panel hyp-detail tab-panel" key={selected.id}>
        <div className="label">{selected.id}</div>
        <h2 className="section-title" style={{ marginTop: 4 }}>
          {selected.title}
        </h2>
        <p style={{ margin: '0 0 14px', fontSize: 14 }}>{selected.statement}</p>
        <div style={{ display: 'flex', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
          <StatusBadge
            label={selected.status}
            tone={selected.status === 'Supported' ? 'purple' : selected.status === 'Rejected' ? 'failure' : 'warning'}
          />
          <StatusBadge label={selected.evidence} tone="info" />
        </div>
        <ConfidenceIndicator value={selected.confidence} />
        <div style={{ marginTop: 16 }}>
          <div className="label" style={{ marginBottom: 6 }}>
            Evidence
          </div>
          <div style={{ fontSize: 14, fontWeight: 500 }}>{selected.evidence}</div>
        </div>
      </div>
    </div>
  )
}
