import type { Hypothesis } from '../data/mockData'
import { StatusBadge } from './StatusBadge'

interface HypothesisCardProps {
  hypothesis: Hypothesis
  selected: boolean
  onSelect: (id: string) => void
  showLinks?: boolean
}

export function HypothesisCard({ hypothesis, selected, onSelect, showLinks }: HypothesisCardProps) {
  const tone =
    hypothesis.status === 'Supported' ? 'purple' : hypothesis.status === 'Rejected' ? 'failure' : 'warning'

  return (
    <div
      className={`hyp-card${selected ? ' selected' : ''}${hypothesis.status === 'Supported' ? ' supported' : ''}`}
      onClick={() => onSelect(hypothesis.id)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') onSelect(hypothesis.id)
      }}
    >
      <h4>{hypothesis.title}</h4>
      <StatusBadge label={hypothesis.status} tone={tone} />
      {showLinks && hypothesis.experiments.length > 0 ? (
        <div className="hyp-links">
          {hypothesis.experiments.map((link) => (
            <div key={link.label} className={`hyp-link ${link.kind}`}>
              {link.label}
              <div style={{ fontWeight: 500 }}>{link.result}</div>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  )
}
