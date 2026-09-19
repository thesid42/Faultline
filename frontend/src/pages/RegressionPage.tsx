import { PageHeader } from '../components/PageHeader'
import { RegressionProposal } from '../components/RegressionProposal'
import { regressionProposal } from '../data/mockData'

export function RegressionPage() {
  return (
    <div>
      <PageHeader title="Regression Proposal" subtitle="Human review gate before adding tests to the eval suite." />
      {/* TODO: Connect Faultline backend — proposal artifacts + approve-export */}
      <RegressionProposal proposal={regressionProposal} />
    </div>
  )
}
