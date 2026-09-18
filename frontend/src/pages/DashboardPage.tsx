import { useNavigate } from 'react-router-dom'
import type { Dashboard } from '../api/types'
import { CoreOverview } from '../components/panels/CoreOverview'
import { GanzCircle } from '../components/panels/GanzCircle'
import { LiveFeed } from '../components/panels/LiveFeed'
import { TodoPanel } from '../components/panels/TodoPanel'
import { MissionPanel } from '../components/panels/MissionPanel'
import { QuickCommands, commandIcons } from '../components/panels/QuickCommands'
import { FinancePanel } from '../components/panels/FinancePanel'
import { SocialStatsPanel } from '../components/panels/SocialStatsPanel'
import { UploadSchedulePanel } from '../components/panels/UploadSchedulePanel'
import { SystemMonitor } from '../components/panels/SystemMonitor'
import { LlmStatusPanel, MemoryInsights } from '../components/panels/SmallPanels'
import { ActiveSkills } from '../components/panels/ActiveSkills'
import { TodayTasks } from '../components/panels/TodayTasks'

/** De indeling van het command center.
 *
 *  Rij 1: wie ben ik en wat gebeurt er.
 *  Rij 2: wat kan ik, wat staat er vandaag, en wat moet ik nog doen.
 *  Rij 3: hoeveel heb ik, hoe doen de kanalen het, wanneer gaat de volgende eruit.
 *  Rij 4: hoe staat de machine ervoor.
 *
 *  Finance en Social staan naast elkaar en zijn niet langer één groot blok. */
export function DashboardPage({
  data,
  refresh,
}: {
  data: Dashboard
  refresh: () => void
}) {
  const navigate = useNavigate()
  const can = (key: string) => data.user.permissions.includes(key)
  const busy = (data.missions ?? []).some((mission) => mission.status === 'running')

  return (
    <div className="page">
      <div className="row row--core">
        <CoreOverview core={data.core} />
        <GanzCircle core={data.core} busy={busy} />
        <LiveFeed items={data.feed} onOpen={() => navigate('/activity')} />
      </div>

      <div className="row row--work">
        {can('skills.read') ? <ActiveSkills onOpenAll={() => navigate('/skills')} /> : null}
        {can('tasks.read') ? <TodayTasks onOpenAll={() => navigate('/tasks')} /> : null}
        {data.todo ? (
          <TodoPanel
            todo={data.todo}
            canWrite={can('todo.write')}
            onChanged={refresh}
            onOpenAll={() => navigate('/todos')}
          />
        ) : null}
        {data.missions ? <MissionPanel missions={data.missions} /> : null}
        <QuickCommands
          commands={[
            { label: 'Nieuwe taak starten', icon: commandIcons.task, onClick: () => navigate('/todos') },
            { label: 'Agenda openen', icon: commandIcons.agenda, onClick: () => navigate('/agenda') },
            {
              label: 'Voice-chat starten',
              icon: commandIcons.voice,
              disabled: data.core.voice_status !== 'listening',
            },
            { label: 'Workflow uitvoeren', icon: commandIcons.workflow, onClick: () => navigate('/workflows') },
          ]}
        />
      </div>

      <div className="row row--money">
        {data.finance ? (
          <FinancePanel finance={data.finance} onOpen={() => navigate('/finance')} />
        ) : null}
        {data.social ? (
          <SocialStatsPanel social={data.social} onOpen={() => navigate('/social')} />
        ) : null}
        <LlmStatusPanel providers={data.llm} />
        {data.uploads ? (
          <UploadSchedulePanel
            uploads={data.uploads}
            onRefresh={refresh}
            onOpen={() => navigate('/uploads')}
          />
        ) : null}
      </div>

      <div className="row row--status">
        {data.system ? <SystemMonitor system={data.system} /> : null}
        {data.memory ? <MemoryInsights memory={data.memory} /> : null}
      </div>
    </div>
  )
}
