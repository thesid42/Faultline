import { PageHeader } from '../components/PageHeader'

export function SettingsPage() {
  return (
    <div>
      <PageHeader title="Settings" subtitle="Prototype settings — no persistence yet." />
      <div className="panel empty-state">
        <p style={{ margin: 0 }}>
          Settings will connect to Faultline configuration later.
          <br />
          {/* TODO: Connect Faultline backend */}
        </p>
      </div>
    </div>
  )
}
