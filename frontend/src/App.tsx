import { useCallback, useEffect, useState } from 'react'
import { BrowserRouter, HashRouter, Navigate, Route, Routes } from 'react-router-dom'
import { getToken } from './api/client'
import { useDashboard } from './hooks/useDashboard'
import { Shell } from './components/layout/Shell'
import { DashboardPage } from './pages/DashboardPage'
import { LoginPage } from './pages/LoginPage'
import { TodosPage } from './pages/TodosPage'
import { FinancePage } from './pages/FinancePage'
import { ChannelsPage } from './pages/ChannelsPage'
import { ModulePage } from './pages/ModulePage'
import { SkillsPage } from './pages/SkillsPage'
import { TasksPage } from './pages/TasksPage'
import { PinCard } from './components/panels/PinCard'
import { YouTubeCard } from './components/panels/YouTubeCard'
import { Panel } from './components/ui/Panel'

// Electron laadt de bestanden van schijf; daar werkt alleen een hash-router.
const Router = window.location.protocol === 'file:' ? HashRouter : BrowserRouter

function Loading() {
  return (
    <div className="page">
      <Panel title="Ganz">
        <p style={{ color: 'var(--text-dim)' }}>Verbinden met Ganz…</p>
      </Panel>
    </div>
  )
}

function Unreachable({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="page">
      <Panel title="Geen verbinding">
        <div className="notice notice--error">{message}</div>
        <button className="btn" type="button" style={{ marginTop: 12 }} onClick={onRetry}>
          Opnieuw proberen
        </button>
      </Panel>
    </div>
  )
}

export default function App() {
  const [authed, setAuthed] = useState(() => Boolean(getToken()))

  if (!authed) {
    return (
      <Router>
        <LoginPage onSuccess={() => setAuthed(true)} />
      </Router>
    )
  }

  return (
    <Router>
      <Authenticated onSignedOut={() => setAuthed(false)} />
    </Router>
  )
}

function Authenticated({ onSignedOut }: { onSignedOut: () => void }) {
  const { data, error, loading, refresh } = useDashboard()

  // Verlopen sessie: het token is al weggegooid, dus terug naar het inlogscherm.
  useEffect(() => {
    if (error && !getToken()) onSignedOut()
  }, [error, onSignedOut])

  const can = useCallback(
    (key: string) => data?.user.permissions.includes(key) ?? false,
    [data],
  )

  return (
    <Shell data={data}>
      {loading && !data ? (
        <Loading />
      ) : error && !data ? (
        <Unreachable message={error} onRetry={refresh} />
      ) : data ? (
        <Routes>
          {/* /command-center is het echte adres; / stuurt erheen. Een eigen route in
              plaats van een verborgen div, zodat de knop "terug" van de browser en de
              desktopschil doen wat je verwacht. */}
          <Route path="/" element={<Navigate to="/command-center" replace />} />
          <Route
            path="/command-center"
            element={<DashboardPage data={data} refresh={refresh} />}
          />
          <Route path="/skills" element={<SkillsPage canWrite={can('skills.write')} />} />
          <Route path="/tasks" element={<TasksPage canWrite={can('tasks.write')} />} />
          <Route path="/todos" element={<TodosPage canWrite={can('todo.write')} />} />
          <Route
            path="/finance"
            element={can('finance.read') ? <FinancePage /> : <Navigate to="/" replace />}
          />
          <Route
            path="/social"
            element={can('social.read') ? <ChannelsPage /> : <Navigate to="/" replace />}
          />
          <Route
            path="/uploads"
            element={can('upload.read') ? <ChannelsPage /> : <Navigate to="/" replace />}
          />
          <Route
            path="/youtube"
            element={
              can('social.read') ? (
                <ChannelsPage platform="youtube" intro={<YouTubeCard />} />
              ) : (
                <Navigate to="/" replace />
              )
            }
          />
          <Route
            path="/core"
            element={
              <ModulePage
                title="Ganz Core"
                endpoint="/llm"
                columns={[
                  { key: 'provider', label: 'Provider' },
                  { key: 'model', label: 'Model' },
                  { key: 'status', label: 'Status', kind: 'status' },
                  { key: 'latency_ms', label: 'Vertraging (ms)' },
                  { key: 'checked_at', label: 'Gemeten', kind: 'since' },
                ]}
                emptyTitle="Nog geen taalmodel gekoppeld"
              />
            }
          />
          <Route
            path="/agenda"
            element={
              <ModulePage
                title="Agenda"
                endpoint="/missions"
                columns={[
                  { key: 'title', label: 'Missie' },
                  { key: 'status', label: 'Status', kind: 'status' },
                  { key: 'scheduled_for', label: 'Gepland', kind: 'datetime' },
                  { key: 'completed_at', label: 'Afgerond', kind: 'datetime' },
                ]}
                emptyTitle="Niets in de agenda"
              />
            }
          />
          <Route
            path="/memory"
            element={
              <ModulePage
                title="Geheugen"
                endpoint="/memory"
                pick={(payload) =>
                  ((payload as { entries?: Record<string, unknown>[] }).entries ?? [])
                }
                columns={[
                  { key: 'title', label: 'Herinnering' },
                  { key: 'kind', label: 'Soort' },
                  { key: 'importance', label: 'Belang' },
                  { key: 'created_at', label: 'Bewaard', kind: 'since' },
                ]}
                emptyTitle="Nog niets onthouden"
              />
            }
          />
          <Route
            path="/conversations"
            element={
              <ModulePage
                title="Gesprekken"
                endpoint="/conversations"
                columns={[
                  { key: 'title', label: 'Gesprek' },
                  { key: 'last_message_at', label: 'Laatste bericht', kind: 'since' },
                  { key: 'created_at', label: 'Gestart', kind: 'datetime' },
                ]}
                emptyTitle="Nog geen gesprekken"
              />
            }
          />
          <Route
            path="/integrations"
            element={
              <ModulePage
                title="Integraties"
                endpoint="/integrations"
                columns={[
                  { key: 'name', label: 'Integratie' },
                  { key: 'category', label: 'Soort' },
                  { key: 'status', label: 'Status', kind: 'status' },
                  { key: 'status_detail', label: 'Toelichting' },
                  { key: 'last_checked_at', label: 'Gecontroleerd', kind: 'since' },
                ]}
                emptyTitle="Nog niets gekoppeld"
              />
            }
          />
          <Route
            path="/activity"
            element={
              <ModulePage
                title="Activiteitenlog"
                endpoint="/activity?limit=200"
                // /activity levert een pagina: de lijst zit in `items`, met het totaal ernaast.
                pick={(payload) =>
                  (payload as { items: Record<string, unknown>[] }).items ?? []
                }
                columns={[
                  { key: 'created_at', label: 'Wanneer', kind: 'datetime' },
                  { key: 'action', label: 'Gebeurtenis' },
                  { key: 'message', label: 'Omschrijving' },
                ]}
                emptyTitle="Nog geen activiteit"
              />
            }
          />
          <Route
            path="/workflows"
            element={
              <ModulePage
                title="Workflows"
                endpoint="/workflows"
                columns={[
                  { key: 'name', label: 'Workflow' },
                  { key: 'trigger', label: 'Start bij' },
                  { key: 'enabled', label: 'Aan' },
                  { key: 'run_count', label: 'Keer gedraaid' },
                  { key: 'last_run_at', label: 'Laatst', kind: 'since' },
                ]}
                emptyTitle="Nog geen workflows"
              />
            }
          />
          <Route
            path="/access"
            element={
              <ModulePage
                title="Toegang & stemmen"
                endpoint="/auth/permissions"
                columns={[
                  { key: 'key', label: 'Recht' },
                  { key: 'description', label: 'Wat het inhoudt' },
                  { key: 'max_tier', label: 'Vanaf tier' },
                  { key: 'sensitive', label: 'Extra bevestiging' },
                  { key: 'granted', label: 'Jij mag dit' },
                ]}
                emptyTitle="Geen rechten gevonden"
              />
            }
          />
          <Route
            path="/settings"
            element={
              <ModulePage
                title="Instellingen — rechten"
                endpoint="/auth/permissions"
                intro={<PinCard />}
                columns={[
                  { key: 'key', label: 'Recht' },
                  { key: 'granted', label: 'Jij mag dit' },
                ]}
                emptyTitle="Geen rechten gevonden"
              />
            }
          />
          <Route path="*" element={<Navigate to="/command-center" replace />} />
        </Routes>
      ) : null}
    </Shell>
  )
}
