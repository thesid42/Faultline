import type { ExperimentComparison } from '../data/mockData'

interface BeforeAfterComparisonProps {
  before: ExperimentComparison
  after: ExperimentComparison
}

function Panel({ data }: { data: ExperimentComparison }) {
  return (
    <div className={`ba-panel ${data.outcome}`}>
      <h5>{data.label}</h5>
      {data.orderAge ? (
        <div className="ba-row">
          <span>Order age</span>
          <span>{data.orderAge}</span>
        </div>
      ) : null}
      <div className="ba-row">
        <span>Memory</span>
        <span>{data.memory}</span>
      </div>
      <div className="ba-row">
        <span>Result</span>
        <span style={{ fontWeight: 600 }}>{data.result}</span>
      </div>
    </div>
  )
}

export function BeforeAfterComparison({ before, after }: BeforeAfterComparisonProps) {
  return (
    <div className="before-after">
      <Panel data={before} />
      <Panel data={after} />
    </div>
  )
}
