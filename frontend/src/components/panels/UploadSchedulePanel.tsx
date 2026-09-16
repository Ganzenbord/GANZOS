import type { ChannelScheduleRow, ScheduleOverview } from '../../api/types'
import { PLATFORM_LABEL, humanCountdown, shortDateTime } from '../../lib/format'
import { useCountdown } from '../../hooks/useCountdown'
import { useServerOffset } from '../../hooks/useServerClock'
import { Panel } from '../ui/Panel'
import { EmptyState } from '../ui/EmptyState'
import { IconPlay, IconUpload, IconUsers } from '../ui/Icons'

function platformIcon(platform: string) {
  if (platform === 'youtube') return <IconPlay size={14} />
  if (platform === 'instagram') return <IconUsers size={14} />
  return <IconUpload size={14} />
}

/** Eén regel met een aftelling.
 *
 *  De teller rekent elke seconde opnieuw vanaf het opgeslagen moment, met het
 *  klokverschil van de server erin verwerkt. Zo loopt hij niet weg en klopt hij ook
 *  als de computer even heeft geslapen. */
function ChannelRow({
  row,
  offset,
  onReachedZero,
}: {
  row: ChannelScheduleRow
  offset: number
  onReachedZero: () => void
}) {
  const seconds = useCountdown(row.next_upload?.effective_at ?? null, offset, onReachedZero)

  let right: JSX.Element
  if (row.needs_reauth) {
    right = <span className="countdown countdown--overdue">Opnieuw inloggen</span>
  } else if (!row.next_upload) {
    right = <span className="countdown countdown--none">Geen upload gepland</span>
  } else if (seconds !== null && seconds <= 0) {
    right = (
      <span className="countdown countdown--overdue">
        {row.next_upload.status === 'uploading' ? 'Bezig met uploaden' : 'Wacht op uitvoering'}
      </span>
    )
  } else {
    right = <span className="countdown">Upload in {humanCountdown(seconds)}</span>
  }

  return (
    <div className="rowitem">
      <span className="icon-badge">{platformIcon(row.platform)}</span>
      <span style={{ minWidth: 0 }}>
        <span className="rowitem__label">{row.channel_name}</span>
        <br />
        <span className="rowitem__sub">
          {PLATFORM_LABEL[row.platform] ?? row.platform}
          {row.next_upload ? ` · ${shortDateTime(row.next_upload.effective_at)}` : ''}
        </span>
      </span>
      <span className="rowitem__right">{right}</span>
    </div>
  )
}

export function UploadSchedulePanel({
  uploads,
  onRefresh,
  onOpen,
}: {
  uploads: ScheduleOverview
  onRefresh: () => void
  onOpen?: () => void
}) {
  const offset = useServerOffset(uploads.server_time)

  return (
    <Panel title="Channel upload schedule" name="uploads" linkLabel="Alles bekijken" onLink={onOpen} tight>
      {uploads.channels.length === 0 ? (
        <EmptyState
          title="Nog geen kanalen"
          hint="Koppel een kanaal om uploads te kunnen inplannen."
          actionLabel="Kanaal koppelen"
          onAction={onOpen}
        />
      ) : (
        <div className="rows">
          {uploads.channels.map((row) => (
            <ChannelRow
              key={row.channel_id}
              row={row}
              offset={offset}
              onReachedZero={onRefresh}
            />
          ))}
        </div>
      )}
    </Panel>
  )
}
