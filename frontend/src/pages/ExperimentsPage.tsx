import { useState } from 'react'
import { ExperimentsPanel } from '../components/ExperimentsPanel'
import { PageHeader } from '../components/PageHeader'
import { RunExperimentDialog } from '../components/RunExperimentDialog'
import { useToast } from '../context/ToastContext'
import { experiments } from '../data/mockData'

export function ExperimentsPage() {
  const { toast } = useToast()
  const [filter, setFilter] = useState<'all' | 'causal' | 'control'>('all')
  const [dialogOpen, setDialogOpen] = useState(false)

  const filtered = experiments.filter((exp) => {
    if (filter === 'all') return true
    if (filter === 'causal') return exp.kind === 'Causal Test'
    return exp.kind === 'Control Test'
  })

  return (
    <div>
      <PageHeader
        title="Experiments"
        subtitle="Test hypotheses with controlled interventions."
        actions={
          <button type="button" className="btn btn-primary" onClick={() => setDialogOpen(true)}>
            + Run experiment
          </button>
        }
      />
      {/* TODO: Connect Faultline backend — load experiment_result artifacts */}
      <ExperimentsPanel
        filter={filter}
        setFilter={setFilter}
        experiments={filtered}
        onRun={() => setDialogOpen(true)}
        standalone
      />
      <RunExperimentDialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        onConfirm={() => {
          setDialogOpen(false)
          toast('Mock experiment queued.')
        }}
      />
    </div>
  )
}
