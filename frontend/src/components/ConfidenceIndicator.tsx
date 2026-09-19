interface ConfidenceIndicatorProps {
  value: number
  large?: boolean
}

export function ConfidenceIndicator({ value, large }: ConfidenceIndicatorProps) {
  if (large) {
    return (
      <div className="confidence-gauge">
        <div className="big">{value}%</div>
        <div className="confidence-bar">
          <span className="progress-fill" style={{ width: `${value}%` }} />
        </div>
        <div className="label">Confidence</div>
      </div>
    )
  }

  return (
    <div className="confidence-row">
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
        <span className="label">Confidence</span>
        <span style={{ fontWeight: 600, fontSize: 13 }}>{value}%</span>
      </div>
      <div className="confidence-bar">
        <span className="progress-fill" style={{ width: `${value}%` }} />
      </div>
    </div>
  )
}
