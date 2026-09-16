import { useCallback, useEffect, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { ScheduleOverview, SocialChannel, SocialOverview, Upload } from '../api/types'
import {
  PLATFORM_LABEL,
  STATUS_LABEL,
  compactNumber,
  humanCountdown,
  moneyIn,
  percent,
  relativeSince,
  shortDateTime,
} from '../lib/format'
import { Panel } from '../components/ui/Panel'
import { EmptyState } from '../components/ui/EmptyState'
import { ConfirmDialog } from '../components/ui/ConfirmDialog'
import { StatusDot, toneFor } from '../components/ui/StatusDot'
import { IconPlus, IconRefresh, IconTrash } from '../components/ui/Icons'
import { useServerOffset } from '../hooks/useServerClock'
import { useCountdown } from '../hooks/useCountdown'

const CONTENT_TYPES = ['video', 'short', 'reel', 'post', 'story', 'other']
const RECURRENCES: Record<string, string> = {
  once: 'Eenmalig',
  daily: 'Elke dag',
  weekly: 'Wekelijks',
}

function Countdown({ upload, offset }: { upload: Upload; offset: number }) {
  const seconds = useCountdown(upload.effective_at, offset)
  if (seconds === null) return <span className="countdown countdown--none">—</span>
  if (seconds <= 0) return <span className="countdown countdown--overdue">Wacht op uitvoering</span>
  return <span className="countdown">{humanCountdown(seconds)}</span>
}

/** Kanalen beheren, statistieken bekijken en uploads inplannen.
 *  Bereikbaar via /social en /youtube; /youtube filtert op dat ene platform. */
export function ChannelsPage({ platform }: { platform?: string }) {
  const [channels, setChannels] = useState<SocialChannel[]>([])
  const [overview, setOverview] = useState<SocialOverview | null>(null)
  const [schedule, setSchedule] = useState<ScheduleOverview | null>(null)
  const [uploads, setUploads] = useState<Upload[]>([])
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState<(() => Promise<void>) | null>(null)
  const [confirmLabel, setConfirmLabel] = useState('Deze wijziging')

  const [channelForm, setChannelForm] = useState({
    platform: platform ?? 'youtube',
    channel_name: '',
    external_channel_id: '',
    api_key: '',
    access_token: '',
  })
  const [uploadForm, setUploadForm] = useState({
    channel_id: '',
    title: '',
    content_type: 'video',
    scheduled_at: '',
    recurrence: 'once',
  })

  const offset = useServerOffset(schedule?.server_time)

  const load = useCallback(async () => {
    try {
      const [list, summary, plan, items] = await Promise.all([
        api<SocialChannel[]>('/social/channels'),
        api<SocialOverview>('/social/overview'),
        api<ScheduleOverview>('/uploads/schedule'),
        api<Upload[]>('/uploads?limit=50'),
      ])
      setChannels(platform ? list.filter((row) => row.platform === platform) : list)
      setOverview(summary)
      setSchedule(
        platform ? { ...plan, channels: plan.channels.filter((r) => r.platform === platform) } : plan,
      )
      setUploads(items)
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Kanalen ophalen lukte niet')
    }
  }, [platform])

  useEffect(() => {
    void load()
  }, [load])

  async function guarded(label: string, work: () => Promise<unknown>) {
    const attempt = async () => {
      await work()
      await load()
    }
    try {
      await attempt()
      setError(null)
    } catch (err) {
      if (err instanceof ApiError && err.needsConfirmation) {
        setConfirmLabel(label)
        setPending(() => async () => {
          try {
            await attempt()
            setError(null)
          } catch (retryError) {
            setError(retryError instanceof ApiError ? retryError.message : 'Mislukt')
          }
        })
        return
      }
      setError(err instanceof ApiError ? err.message : 'Bewerking mislukt')
    }
  }

  function credentials() {
    const creds: Record<string, string> = {}
    if (channelForm.external_channel_id.trim()) {
      creds.channel_id = channelForm.external_channel_id.trim()
      creds.ig_user_id = channelForm.external_channel_id.trim()
    }
    if (channelForm.api_key.trim()) creds.api_key = channelForm.api_key.trim()
    if (channelForm.access_token.trim()) creds.access_token = channelForm.access_token.trim()
    return Object.keys(creds).length > 0 ? creds : null
  }

  async function addChannel(event: React.FormEvent) {
    event.preventDefault()
    await guarded('Een kanaal koppelen', async () => {
      await api('/social/channels', {
        method: 'POST',
        confirm: true,
        body: {
          platform: channelForm.platform,
          channel_name: channelForm.channel_name.trim(),
          external_channel_id: channelForm.external_channel_id.trim() || null,
          credentials: credentials(),
        },
      })
      setChannelForm({ ...channelForm, channel_name: '', external_channel_id: '', api_key: '', access_token: '' })
    })
  }

  async function planUpload(event: React.FormEvent) {
    event.preventDefault()
    if (!uploadForm.channel_id || !uploadForm.scheduled_at) return
    await guarded('Een upload inplannen', async () => {
      await api('/uploads', {
        method: 'POST',
        body: {
          channel_id: Number(uploadForm.channel_id),
          title: uploadForm.title.trim() || null,
          content_type: uploadForm.content_type,
          // De browser levert lokale tijd; naar UTC toe zodat de server niet hoeft te raden.
          scheduled_at: new Date(uploadForm.scheduled_at).toISOString(),
          recurrence: uploadForm.recurrence,
          timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        },
      })
      setUploadForm({ ...uploadForm, title: '', scheduled_at: '' })
    })
  }

  return (
    <div className="page">
      {error ? <div className="notice notice--error">{error}</div> : null}

      {overview && !platform ? (
        <Panel
          title="Gecombineerde statistieken"
          meta={`${overview.channels_counted} van ${overview.channels_total} kanalen geteld`}
          footer={
            <button
              className="btn"
              type="button"
              onClick={() => void guarded('Nu bijwerken', () => api('/social/sync', { method: 'POST', confirm: true }))}
            >
              <IconRefresh size={14} /> Nu bijwerken
            </button>
          }
        >
          <div className="stats">
            <div className="stat">
              <div className="stat__value">{compactNumber(overview.followers)}</div>
              <div className="stat__label">Volgers</div>
            </div>
            <div className="stat">
              <div className="stat__value">{compactNumber(overview.views)}</div>
              <div className="stat__label">Views</div>
            </div>
            <div className="stat">
              <div className="stat__value">{compactNumber(overview.likes)}</div>
              <div className="stat__label">Likes</div>
            </div>
            <div className="stat">
              <div className="stat__value">
                {overview.growth_pct === null ? '—' : percent(overview.growth_pct)}
              </div>
              <div className="stat__label">Groei (7 dagen)</div>
            </div>
            <div className="stat">
              <div className="stat__value">
                {overview.revenue_available
                  ? moneyIn(overview.revenue, overview.revenue_currency ?? 'EUR')
                  : '—'}
              </div>
              <div className="stat__label">
                {overview.revenue_available ? 'Deze maand' : 'Omzet niet beschikbaar'}
              </div>
            </div>
          </div>
        </Panel>
      ) : null}

      <Panel title="Kanaal koppelen">
        <form onSubmit={addChannel} style={{ display: 'grid', gap: 12 }}>
          <div className="formgrid">
            {!platform ? (
              <label className="field">
                <span className="field__label">Platform</span>
                <select
                  className="select"
                  value={channelForm.platform}
                  onChange={(e) => setChannelForm({ ...channelForm, platform: e.target.value })}
                >
                  {Object.entries(PLATFORM_LABEL).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
            <label className="field">
              <span className="field__label">Kanaalnaam</span>
              <input
                className="input"
                value={channelForm.channel_name}
                onChange={(e) => setChannelForm({ ...channelForm, channel_name: e.target.value })}
                required
              />
            </label>
            <label className="field">
              <span className="field__label">Kanaal-ID bij het platform</span>
              <input
                className="input"
                value={channelForm.external_channel_id}
                onChange={(e) =>
                  setChannelForm({ ...channelForm, external_channel_id: e.target.value })
                }
                placeholder="UC..."
              />
            </label>
            <label className="field">
              <span className="field__label">API-sleutel (YouTube)</span>
              <input
                className="input"
                type="password"
                value={channelForm.api_key}
                onChange={(e) => setChannelForm({ ...channelForm, api_key: e.target.value })}
              />
            </label>
            <label className="field">
              <span className="field__label">Toegangstoken (Instagram / TikTok)</span>
              <input
                className="input"
                type="password"
                value={channelForm.access_token}
                onChange={(e) => setChannelForm({ ...channelForm, access_token: e.target.value })}
              />
            </label>
          </div>
          <p style={{ margin: 0, fontSize: 12, color: 'var(--text-dim)' }}>
            Sleutels maak je zelf aan bij het platform; Ganz kan dat niet voor je doen.
            Ze worden versleuteld opgeslagen en nooit teruggestuurd naar het scherm.
          </p>
          <div>
            <button className="btn btn--primary" type="submit">
              <IconPlus size={14} /> Koppelen
            </button>
          </div>
        </form>
      </Panel>

      <Panel title="Kanalen">
        {channels.length === 0 ? (
          <EmptyState title="Nog geen social-kanalen gekoppeld" />
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Kanaal</th>
                <th>Platform</th>
                <th>Status</th>
                <th>Bijgewerkt</th>
                <th aria-label="Acties" />
              </tr>
            </thead>
            <tbody>
              {channels.map((channel) => (
                <tr key={channel.id}>
                  <td>{channel.channel_name}</td>
                  <td>{PLATFORM_LABEL[channel.platform] ?? channel.platform}</td>
                  <td>
                    <StatusDot
                      tone={toneFor(channel.status)}
                      label={STATUS_LABEL[channel.status] ?? channel.status}
                    />
                    {channel.status_detail ? (
                      <div className="todo__sub">{channel.status_detail}</div>
                    ) : null}
                  </td>
                  <td>{relativeSince(channel.last_synced_at)}</td>
                  <td>
                    <button
                      className="btn btn--danger"
                      style={{ padding: '3px 8px' }}
                      type="button"
                      onClick={() => {
                        if (!window.confirm(`"${channel.channel_name}" verwijderen?`)) return
                        void guarded('Een kanaal verwijderen', () =>
                          api(`/social/channels/${channel.id}`, { method: 'DELETE', confirm: true }),
                        )
                      }}
                      aria-label="Verwijderen"
                    >
                      <IconTrash size={13} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>

      <Panel title="Upload inplannen">
        <form onSubmit={planUpload} style={{ display: 'grid', gap: 12 }}>
          <div className="formgrid">
            <label className="field">
              <span className="field__label">Kanaal</span>
              <select
                className="select"
                value={uploadForm.channel_id}
                onChange={(e) => setUploadForm({ ...uploadForm, channel_id: e.target.value })}
                required
              >
                <option value="">Kies een kanaal…</option>
                {channels.map((channel) => (
                  <option key={channel.id} value={channel.id}>
                    {channel.channel_name}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span className="field__label">Titel</span>
              <input
                className="input"
                value={uploadForm.title}
                onChange={(e) => setUploadForm({ ...uploadForm, title: e.target.value })}
              />
            </label>
            <label className="field">
              <span className="field__label">Soort</span>
              <select
                className="select"
                value={uploadForm.content_type}
                onChange={(e) => setUploadForm({ ...uploadForm, content_type: e.target.value })}
              >
                {CONTENT_TYPES.map((type) => (
                  <option key={type} value={type}>
                    {type}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span className="field__label">Moment</span>
              <input
                className="input"
                type="datetime-local"
                value={uploadForm.scheduled_at}
                onChange={(e) => setUploadForm({ ...uploadForm, scheduled_at: e.target.value })}
                required
              />
            </label>
            <label className="field">
              <span className="field__label">Herhaling</span>
              <select
                className="select"
                value={uploadForm.recurrence}
                onChange={(e) => setUploadForm({ ...uploadForm, recurrence: e.target.value })}
              >
                {Object.entries(RECURRENCES).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div>
            <button className="btn btn--primary" type="submit">
              <IconPlus size={14} /> Inplannen
            </button>
          </div>
        </form>
      </Panel>

      <Panel title="Volgende uploads">
        {!schedule || schedule.channels.length === 0 ? (
          <EmptyState title="Geen uploads gepland" />
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Kanaal</th>
                <th>Volgende upload</th>
                <th>Moment</th>
                <th>Aftellen</th>
              </tr>
            </thead>
            <tbody>
              {schedule.channels.map((row) => (
                <tr key={row.channel_id}>
                  <td>{row.channel_name}</td>
                  <td>{row.next_upload?.title ?? '—'}</td>
                  <td>{shortDateTime(row.next_upload?.effective_at ?? null)}</td>
                  <td>
                    {row.needs_reauth ? (
                      <span className="countdown countdown--overdue">Opnieuw inloggen</span>
                    ) : row.next_upload ? (
                      <Countdown upload={row.next_upload} offset={offset} />
                    ) : (
                      <span className="countdown countdown--none">Geen upload gepland</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>

      <Panel title="Uploadgeschiedenis">
        {uploads.length === 0 ? (
          <EmptyState title="Nog geen uploads" />
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Kanaal</th>
                <th>Titel</th>
                <th>Soort</th>
                <th>Gepland</th>
                <th>Status</th>
                <th aria-label="Acties" />
              </tr>
            </thead>
            <tbody>
              {uploads.map((upload) => (
                <tr key={upload.id}>
                  <td>{upload.channel_name ?? '—'}</td>
                  <td>{upload.title ?? '—'}</td>
                  <td>{upload.content_type}</td>
                  <td>{shortDateTime(upload.scheduled_at)}</td>
                  <td>
                    <StatusDot
                      tone={toneFor(upload.status)}
                      label={STATUS_LABEL[upload.status] ?? upload.status}
                    />
                  </td>
                  <td>
                    {upload.status === 'scheduled' ? (
                      <button
                        className="btn btn--ghost"
                        style={{ padding: '3px 8px' }}
                        type="button"
                        onClick={() =>
                          void guarded('Een upload annuleren', () =>
                            api(`/uploads/${upload.id}/cancel`, { method: 'POST' }),
                          )
                        }
                      >
                        Annuleren
                      </button>
                    ) : (
                      '—'
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>

      {pending ? (
        <ConfirmDialog
          action={confirmLabel}
          onCancel={() => setPending(null)}
          onConfirmed={() => {
            const work = pending
            setPending(null)
            void work()
          }}
        />
      ) : null}
    </div>
  )
}
