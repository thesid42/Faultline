interface RunExperimentDialogProps {
  open: boolean
  onClose: () => void
  onConfirm: () => void
}

export function RunExperimentDialog({ open, onClose, onConfirm }: RunExperimentDialogProps) {
  if (!open) return null

  return (
    <div className="dialog-backdrop" onClick={onClose} role="presentation">
      <div
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="run-exp-title"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 id="run-exp-title">Run experiment</h3>
        <p>
          This is a UI prototype. No real experiment will execute. Confirm to simulate a queued causal test against
          the current hypothesis.
        </p>
        <div className="dialog-actions">
          <button type="button" className="btn btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => {
              // TODO: Connect Faultline backend — schedule experiment trial
              onConfirm()
            }}
          >
            Queue mock run
          </button>
        </div>
      </div>
    </div>
  )
}
