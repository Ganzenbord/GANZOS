import { Panel } from '../ui/Panel'
import { IconCalendar, IconFlow, IconMic, IconPlus } from '../ui/Icons'

interface Command {
  label: string
  icon: JSX.Element
  onClick?: () => void
  disabled?: boolean
}

export function QuickCommands({ commands }: { commands: Command[] }) {
  return (
    <Panel title="Quick commands" name="quick">
      <div className="quick">
        {commands.map((command) => (
          <button
            type="button"
            className="quick__btn"
            key={command.label}
            onClick={command.onClick}
            disabled={command.disabled}
          >
            {command.icon}
            <span>{command.label}</span>
            <span className="quick__chev" aria-hidden>
              ›
            </span>
          </button>
        ))}
      </div>
    </Panel>
  )
}

export const commandIcons = {
  task: <IconPlus size={15} />,
  agenda: <IconCalendar size={15} />,
  voice: <IconMic size={15} />,
  workflow: <IconFlow size={15} />,
}
