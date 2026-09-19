import { PageHeader } from '../components/PageHeader'
import { IncidentTable } from '../components/IncidentTable'
import { incidents } from '../data/mockData'

export function IncidentsPage() {
  return (
    <div>
      <PageHeader title="Incidents" subtitle="Browse agent failures awaiting or undergoing investigation." />
      {/* TODO: Connect Faultline backend — list incidents from ArtifactStore */}
      <IncidentTable incidents={incidents} />
    </div>
  )
}
