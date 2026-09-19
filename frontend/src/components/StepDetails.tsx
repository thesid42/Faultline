import { useState } from 'react'
import type { TraceStep as TraceStepType } from '../data/mockData'
import { EvidenceCard } from './EvidenceCard'
import { StatusBadge } from './StatusBadge'

interface StepDetailsProps {
  step: TraceStepType
}

type DetailTab = 'input' | 'context' | 'output'

export function StepDetails({ step }: StepDetailsProps) {
  const defaultTab: DetailTab = step.retrievedContext ? 'context' : step.input ? 'input' : 'output'
  const [tab, setTab] = useState<DetailTab>(defaultTab)

  return (
    <div className="panel tab-panel" key={step.id}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
        <div>
          <h2 className="section-title" style={{ marginBottom: 4 }}>
            Step Details
          </h2>
          <div style={{ fontWeight: 600, fontSize: 15 }}>{step.name}</div>
        </div>
        <StatusBadge
          label={step.status === 'failed' ? 'Failed' : step.status === 'success' ? 'Success' : 'Downstream'}
          tone={step.status === 'failed' ? 'failure' : step.status === 'success' ? 'success' : 'info'}
        />
      </div>

      <div className="tabs" style={{ marginTop: 12 }}>
        <button type="button" className={`tab${tab === 'input' ? ' active' : ''}`} onClick={() => setTab('input')}>
          Input
        </button>
        <button type="button" className={`tab${tab === 'context' ? ' active' : ''}`} onClick={() => setTab('context')}>
          Retrieved Context
        </button>
        <button type="button" className={`tab${tab === 'output' ? ' active' : ''}`} onClick={() => setTab('output')}>
          Output
        </button>
      </div>

      <div className="tab-panel">
        {tab === 'input' ? (
          <EvidenceCard title="Input" body={step.input ?? 'No input payload for this step.'} />
        ) : null}

        {tab === 'context' ? (
          step.retrievedContext ? (
            <>
              <EvidenceCard
                title={step.retrievedContext.title}
                body={step.retrievedContext.body}
                meta={[
                  { label: 'Source', value: step.retrievedContext.source },
                  { label: 'Retrieved', value: step.retrievedContext.retrievedAt },
                ]}
              />
              {step.policy ? (
                <EvidenceCard
                  title={step.policy.title}
                  body={step.policy.body}
                  variant="amber"
                  meta={[
                    { label: 'Source', value: step.policy.source },
                    { label: 'Version', value: step.policy.version },
                  ]}
                />
              ) : null}
              {step.keyFinding ? (
                <EvidenceCard title="KEY FINDING" body={step.keyFinding} variant="insight" />
              ) : null}
            </>
          ) : (
            <EvidenceCard title="Retrieved Context" body="No retrieved context for this step." />
          )
        ) : null}

        {tab === 'output' ? (
          <EvidenceCard title="Output" body={step.output ?? 'No output payload for this step.'} />
        ) : null}
      </div>
    </div>
  )
}
