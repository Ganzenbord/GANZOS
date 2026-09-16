import { useCallback, useEffect, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { FinanceOverview, FinancialAccount } from '../api/types'
import {
  ACCOUNT_TYPE_LABEL,
  STATUS_LABEL,
  money,
  moneyIn,
  relativeSince,
} from '../lib/format'
import { Panel } from '../components/ui/Panel'
import { EmptyState } from '../components/ui/EmptyState'
import { ConfirmDialog } from '../components/ui/ConfirmDialog'
import { StatusDot, toneFor } from '../components/ui/StatusDot'
import { IconPlus, IconRefresh, IconTrash } from '../components/ui/Icons'

interface Provider {
  key: string
  display_name: string
  read_only: boolean
}

const EMPTY = {
  provider: 'manual',
  account_type: 'bank',
  name: '',
  currency: 'EUR',
  value: '',
  asset_id: '',
  amount: '',
}

/** Financiële accounts beheren. Elke wijziging vraagt om het wachtwoord. */
export function FinancePage() {
  const [overview, setOverview] = useState<FinanceOverview | null>(null)
  const [accounts, setAccounts] = useState<FinancialAccount[]>([])
  const [providers, setProviders] = useState<Provider[]>([])
  const [form, setForm] = useState(EMPTY)
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState<(() => Promise<void>) | null>(null)
  const [confirmLabel, setConfirmLabel] = useState('Deze wijziging')

  const load = useCallback(async () => {
    try {
      const [summary, list, provs] = await Promise.all([
        api<FinanceOverview>('/finance/overview'),
        api<FinancialAccount[]>('/finance/accounts'),
        api<Provider[]>('/finance/providers'),
      ])
      setOverview(summary)
      setAccounts(list)
      setProviders(provs)
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Finance ophalen lukte niet')
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  /** Voert uit; vraagt eerst om bevestiging als de backend daarom vraagt. */
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

  function credentialsFor() {
    if (form.provider === 'crypto_price') {
      return { asset_id: form.asset_id.trim(), amount: form.amount.trim(), currency: form.currency }
    }
    return { value: form.value.trim(), currency: form.currency }
  }

  async function addAccount(event: React.FormEvent) {
    event.preventDefault()
    await guarded('Een account koppelen', async () => {
      await api('/finance/accounts', {
        method: 'POST',
        confirm: true,
        body: {
          provider: form.provider,
          account_type: form.account_type,
          name: form.name.trim(),
          currency: form.currency,
          credentials: credentialsFor(),
        },
      })
      setForm(EMPTY)
    })
  }

  return (
    <div className="page">
      {error ? <div className="notice notice--error">{error}</div> : null}

      <div className="row" style={{ gridTemplateColumns: '1fr 1.2fr' }}>
        <Panel
          title="Totaal vermogen"
          meta={
            overview ? (
              <StatusDot tone={overview.stale ? 'warn' : 'ok'} label={overview.stale ? 'Verouderd' : 'Live'} />
            ) : undefined
          }
          footer={
            <button
              className="btn"
              type="button"
              onClick={() => void guarded('Handmatig bijwerken', () => api('/finance/sync', { method: 'POST', confirm: true }))}
            >
              <IconRefresh size={14} /> Nu bijwerken
            </button>
          }
        >
          <div className="bignum bignum--amber">{money(overview?.total_eur ?? '0')}</div>
          <div className="numlabel">
            {overview
              ? `${overview.counted_accounts} van ${overview.connected_accounts} accounts geteld · bijgewerkt ${relativeSince(overview.last_updated)}`
              : 'Laden…'}
          </div>
          <div className="legend">
            {(overview?.breakdown ?? []).map((row) => (
              <div className="legend__row" key={row.account_type}>
                <span className="dot dot--idle" aria-hidden />
                <span className="legend__name">
                  {ACCOUNT_TYPE_LABEL[row.account_type] ?? row.account_type}
                </span>
                <span className="legend__value">{money(row.total_eur)}</span>
              </div>
            ))}
          </div>
        </Panel>

        <Panel title="Account koppelen">
          <form onSubmit={addAccount} style={{ display: 'grid', gap: 12 }}>
            <div className="formgrid">
              <label className="field">
                <span className="field__label">Provider</span>
                <select
                  className="select"
                  value={form.provider}
                  onChange={(e) => setForm({ ...form, provider: e.target.value })}
                >
                  {providers.map((provider) => (
                    <option key={provider.key} value={provider.key}>
                      {provider.display_name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span className="field__label">Soort</span>
                <select
                  className="select"
                  value={form.account_type}
                  onChange={(e) => setForm({ ...form, account_type: e.target.value })}
                >
                  {Object.entries(ACCOUNT_TYPE_LABEL).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span className="field__label">Naam</span>
                <input
                  className="input"
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  placeholder="Betaalrekening"
                  required
                />
              </label>
              <label className="field">
                <span className="field__label">Valuta</span>
                <input
                  className="input"
                  value={form.currency}
                  onChange={(e) => setForm({ ...form, currency: e.target.value.toUpperCase() })}
                  maxLength={3}
                />
              </label>

              {form.provider === 'crypto_price' ? (
                <>
                  <label className="field">
                    <span className="field__label">Munt (CoinGecko-id)</span>
                    <input
                      className="input"
                      value={form.asset_id}
                      onChange={(e) => setForm({ ...form, asset_id: e.target.value })}
                      placeholder="bitcoin"
                      required
                    />
                  </label>
                  <label className="field">
                    <span className="field__label">Aantal</span>
                    <input
                      className="input"
                      value={form.amount}
                      onChange={(e) => setForm({ ...form, amount: e.target.value })}
                      placeholder="0.25"
                      required
                    />
                  </label>
                </>
              ) : (
                <label className="field">
                  <span className="field__label">Huidig bedrag</span>
                  <input
                    className="input"
                    value={form.value}
                    onChange={(e) => setForm({ ...form, value: e.target.value })}
                    placeholder="12420.00"
                    required
                  />
                </label>
              )}
            </div>
            <p style={{ margin: 0, fontSize: 12, color: 'var(--text-dim)' }}>
              Gegevens gaan versleuteld de database in en verlaten de server niet.
            </p>
            <div>
              <button className="btn btn--primary" type="submit">
                <IconPlus size={14} /> Koppelen
              </button>
            </div>
          </form>
        </Panel>
      </div>

      <Panel title="Gekoppelde accounts">
        {accounts.length === 0 ? (
          <EmptyState title="Nog geen financiële accounts gekoppeld" />
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Naam</th>
                <th>Soort</th>
                <th>Provider</th>
                <th>Waarde</th>
                <th>In euro</th>
                <th>Status</th>
                <th>Bijgewerkt</th>
                <th aria-label="Acties" />
              </tr>
            </thead>
            <tbody>
              {accounts.map((account) => (
                <tr key={account.id}>
                  <td>{account.name}</td>
                  <td>{ACCOUNT_TYPE_LABEL[account.account_type] ?? account.account_type}</td>
                  <td>{account.provider}</td>
                  <td>{moneyIn(account.current_value, account.currency)}</td>
                  <td>{money(account.current_value_eur)}</td>
                  <td>
                    <StatusDot
                      tone={toneFor(account.status)}
                      label={STATUS_LABEL[account.status] ?? account.status}
                    />
                    {account.status_detail ? (
                      <div className="todo__sub">{account.status_detail}</div>
                    ) : null}
                  </td>
                  <td>{relativeSince(account.last_synced_at)}</td>
                  <td>
                    <button
                      className="btn btn--danger"
                      style={{ padding: '3px 8px' }}
                      type="button"
                      onClick={() => {
                        if (!window.confirm(`"${account.name}" loskoppelen?`)) return
                        void guarded('Een account loskoppelen', () =>
                          api(`/finance/accounts/${account.id}`, { method: 'DELETE', confirm: true }),
                        )
                      }}
                      aria-label="Loskoppelen"
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
