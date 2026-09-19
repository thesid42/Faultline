import { useState } from 'react'
import type { RegressionProposal as RegressionProposalType } from '../data/mockData'
import { useToast } from '../context/ToastContext'
import { StatusBadge } from './StatusBadge'

interface RegressionProposalProps {
  proposal: RegressionProposalType
}

export function RegressionProposal({ proposal }: RegressionProposalProps) {
  const { toast } = useToast()
  const [status, setStatus] = useState(proposal.status)
  const heldPct = Math.round((proposal.heldOutPassed / proposal.heldOutTotal) * 100)

  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <StatusBadge label={status} tone={status === 'Approved' ? 'success' : 'warning'} />
      </div>

      <div className="reg-split">
        {[proposal.failure, proposal.control].map((item) => (
          <div key={item.title} className={`panel reg-case ${item.accent}`}>
            <div className="label" style={{ marginBottom: 10 }}>
              {item.title}
            </div>
            <div className="ba-row">
              <span>Order age</span>
              <span>{item.orderAge}</span>
            </div>
            <div className="ba-row">
              <span>Memory</span>
              <span>{item.memory}</span>
            </div>
            <div className="ba-row">
              <span>Expected</span>
              <span style={{ fontWeight: 600 }}>{item.expected}</span>
            </div>
            <div className="ba-row">
              <span>{item.observedLabel}</span>
              <span style={{ fontWeight: 600 }}>{item.observed}</span>
            </div>
          </div>
        ))}
      </div>

      <div className="panel held-out">
        <h2 className="section-title">Held-out Validation</h2>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
          <span style={{ fontWeight: 500 }}>
            {proposal.heldOutPassed} / {proposal.heldOutTotal} passed
          </span>
          <span className="muted">{heldPct}%</span>
        </div>
        <div className="exp-progress">
          <span className="progress-fill" style={{ width: `${heldPct}%`, background: 'var(--success)' }} />
        </div>
      </div>

      <div className="reg-actions">
        <button
          type="button"
          className="btn btn-secondary"
          onClick={() => toast('Test details open in mock view only.')}
        >
          View test details
        </button>
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => {
            // TODO: Connect Faultline backend — call approve-export
            setStatus('Approved')
            toast('Regression approved and added to eval suite (mock).')
          }}
          disabled={status === 'Approved'}
        >
          Approve & Add to Eval Suite
        </button>
      </div>
    </div>
  )
}
