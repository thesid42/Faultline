import { PageHeader } from '../components/PageHeader'

export function SettingsPage() {
  return (
    <div>
      <PageHeader title="Settings" subtitle="Read-only workspace information." />
      <div className="panel empty-state">
        <p style={{ margin: 0 }}>
          Faultline configuration and approvals are managed by the CLI.
          <br />
          {/* TODO: Connect Faultline backend */}
        </p>
      </div>
    </div>
  )
}
