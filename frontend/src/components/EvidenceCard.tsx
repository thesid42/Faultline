interface EvidenceCardProps {
  title: string
  body: string
  meta?: Array<{ label: string; value: string }>
  variant?: 'default' | 'amber' | 'insight'
}

export function EvidenceCard({ title, body, meta, variant = 'default' }: EvidenceCardProps) {
  return (
    <div className={`evidence-card ${variant === 'default' ? '' : variant}`}>
      <h3 className="evidence-title">{title}</h3>
      <p className="evidence-body">{body}</p>
      {meta && meta.length > 0 ? (
        <div className="evidence-meta">
          {meta.map((item) => (
            <span key={item.label}>
              <strong style={{ fontWeight: 500 }}>{item.label}:</strong> {item.value}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  )
}
