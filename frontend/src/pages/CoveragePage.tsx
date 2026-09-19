import { CoverageBars } from '../components/CoverageBars'
import { CoverageMatrix } from '../components/CoverageMatrix'
import { PageHeader } from '../components/PageHeader'
import { coverageData } from '../data/mockData'

export function CoveragePage() {
  return (
    <div>
      <PageHeader title="Evaluation Coverage" subtitle="Where eval suites miss failure conditions." />
      {/* TODO: Connect Faultline backend — coverage artifacts */}
      <CoverageBars bars={coverageData.bars} />
      <div style={{ height: 16 }} />
      <CoverageMatrix data={coverageData} />
    </div>
  )
}
