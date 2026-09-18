import { useEffect, useState, type ReactNode } from 'react'
import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import logo from '../../assets/logo.png'
import type { Dashboard } from '../../api/types'
import { clockTime, longDate } from '../../lib/format'
import { useServerNow, useServerOffset } from '../../hooks/useServerClock'
import { logout } from '../../api/client'
import { StatusDot, toneFor } from '../ui/StatusDot'
import {
  IconBell,
  IconCalendar,
  IconChart,
  IconChat,
  IconCore,
  IconFlow,
  IconHome,
  IconMore,
  IconLink,
  IconLog,
  IconMemory,
  IconPlay,
  IconSearch,
  IconSettings,
  IconSkills,
  IconUsers,
  IconWallet,
} from '../ui/Icons'

interface NavItem {
  to: string
  label: string
  icon: JSX.Element
  badge?: number
  /** Wat er onder de knop op een telefoon past. Zonder dit werd het label op het eerste
   *  woord afgekapt, en dan staat er "To" onder het takenlijstje. */
  short?: string
}

/** Wat je onderweg met je duim wilt bereiken.
 *
 *  Vier vaste plekken plus "Meer". Meer knoppen dan dit worden op 375 pixels te smal om
 *  raak te tikken, en alles wat hier niet past blijft bereikbaar via die vijfde knop —
 *  niets is op een telefoon onvindbaar. */
const MOBILE_ITEMS = ['/command-center', '/todos', '/tasks', '/finance']

export function Shell({ data, children }: { data: Dashboard | null; children: ReactNode }) {
  const navigate = useNavigate()
  const location = useLocation()
  const offset = useServerOffset(data?.server_time)
  const now = useServerNow(offset)

  const [meerOpen, setMeerOpen] = useState(false)

  const permissions = data?.user.permissions ?? []
  const can = (key: string) => permissions.includes(key)

  // Van scherm gewisseld? Dan hoort het menu dicht te gaan.
  useEffect(() => {
    setMeerOpen(false)
  }, [location.pathname])

  const primary: NavItem[] = [
    { to: '/command-center', label: 'Command center', icon: <IconHome size={17} />, short: 'Center' },
    { to: '/core', label: 'Ganz Core', icon: <IconCore size={17} /> },
    { to: '/skills', label: 'Skills', icon: <IconSkills size={17} /> },
    { to: '/tasks', label: 'Taken', icon: <IconFlow size={17} />, short: 'Taken' },
    {
      to: '/todos',
      label: 'To do & taken',
      short: 'To do',
      icon: <IconSkills size={17} />,
      badge: data?.todo ? data.todo.total - data.todo.completed : undefined,
    },
    { to: '/agenda', label: 'Agenda', icon: <IconCalendar size={17} /> },
    { to: '/memory', label: 'Geheugen', icon: <IconMemory size={17} /> },
    { to: '/conversations', label: 'Gesprekken', icon: <IconChat size={17} /> },
  ]

  const secondary: NavItem[] = [
    ...(can('finance.read')
      ? [{ to: '/finance', label: 'Finance', icon: <IconWallet size={17} />, short: 'Geld' }]
      : []),
    ...(can('social.read') ? [{ to: '/social', label: 'Social & kanalen', icon: <IconChart size={17} /> }] : []),
    ...(can('upload.read') ? [{ to: '/uploads', label: 'Uploadschema', icon: <IconPlay size={17} /> }] : []),
    { to: '/youtube', label: 'YouTube-kanalen', icon: <IconPlay size={17} /> },
    { to: '/access', label: 'Toegang & stemmen', icon: <IconUsers size={17} /> },
    {
      to: '/integrations',
      label: 'Integraties',
      icon: <IconLink size={17} />,
      badge: data?.core.integrations_total,
    },
    { to: '/activity', label: 'Activiteitenlog', icon: <IconLog size={17} /> },
    { to: '/workflows', label: 'Workflows', icon: <IconFlow size={17} /> },
  ]

  const allItems = [...primary, ...secondary]
  const mobileItems = MOBILE_ITEMS.map((to) => allItems.find((item) => item.to === to)).filter(
    (item): item is NavItem => Boolean(item),
  )

  async function signOut() {
    // Eerst de server laten weten dat dit apparaat eruit mag, dan pas wegnavigeren.
    await logout()
    navigate('/login', { replace: true })
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="sidebar__brand">
          <span className="sidebar__mark">
            <img src={logo} alt="" width={34} height={34} />
          </span>
          <span>
            <span className="sidebar__name">GANZ</span>
            <br />
            <span className="sidebar__sub">COMMAND CENTER</span>
          </span>
        </div>

        <nav className="sidebar__nav">
          {primary.map((item) => (
            <SideLink key={item.to} item={item} />
          ))}
          <div className="nav__sep" />
          {secondary.map((item) => (
            <SideLink key={item.to} item={item} />
          ))}
        </nav>

        <div className="sidebar__foot">
          <div className="rowitem" style={{ padding: '6px 4px' }}>
            <StatusDot tone={toneFor(data?.core.core_status)} />
            <span>
              <span className="rowitem__label">Server</span>
              <br />
              <span className="rowitem__sub">
                {data ? 'Online' : 'Verbinden…'} · {clockTime(now)}
              </span>
            </span>
          </div>
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <span className="topbar__mark">
            <img src={logo} alt="Ganz" width={30} height={30} />
          </span>
          <span className="pill">
            <StatusDot tone={toneFor(data?.core.core_status)} />
            Core — {data?.core.core_status === 'active' ? 'Actief' : 'Verbinden…'}
          </span>

          <div className="topbar__clock">
            <div className="topbar__date">{longDate(now)}</div>
            <div className="topbar__time">{clockTime(now)}</div>
          </div>

          <div className="topbar__right">
            <button className="iconbtn" type="button" aria-label="Zoeken">
              <IconSearch size={15} />
            </button>
            <button className="iconbtn" type="button" aria-label="Meldingen">
              <IconBell size={15} />
            </button>
            <button
              className="iconbtn"
              type="button"
              aria-label="Instellingen"
              onClick={() => navigate('/settings')}
            >
              <IconSettings size={15} />
            </button>
            <button className="avatar" type="button" onClick={() => void signOut()} title="Uitloggen">
              <span className="avatar__badge">
                {(data?.user.display_name ?? 'G').charAt(0).toUpperCase()}
              </span>
              {data
                ? `${data.user.display_name} · ${data.user.tier === null ? 'geen toegang' : `Tier ${data.user.tier}`}`
                : '—'}
            </button>
          </div>
        </header>

        <main>{children}</main>
      </div>

      {meerOpen ? (
        <div className="sheet" role="dialog" aria-label="Alle onderdelen">
          <button
            className="sheet__backdrop"
            type="button"
            aria-label="Sluiten"
            onClick={() => setMeerOpen(false)}
          />
          <div className="sheet__panel">
            <p className="sheet__title">Alle onderdelen</p>
            <div className="sheet__grid">
              {allItems.map((item) => (
                <button
                  key={item.to}
                  type="button"
                  className={
                    location.pathname === item.to ? 'sheet__item sheet__item--active' : 'sheet__item'
                  }
                  onClick={() => {
                    setMeerOpen(false)
                    navigate(item.to)
                  }}
                >
                  {item.icon}
                  <span>{item.label}</span>
                </button>
              ))}
            </div>
          </div>
        </div>
      ) : null}

      <nav className="bottomnav">
        {mobileItems.map((item) => (
          <button
            key={item.to}
            type="button"
            className={
              location.pathname === item.to ? 'bottomnav__item bottomnav__item--active' : 'bottomnav__item'
            }
            onClick={() => navigate(item.to)}
          >
            {item.icon}
            <span>{item.short ?? item.label}</span>
          </button>
        ))}
        <button
          type="button"
          className={meerOpen ? 'bottomnav__item bottomnav__item--active' : 'bottomnav__item'}
          aria-expanded={meerOpen}
          onClick={() => setMeerOpen((open) => !open)}
        >
          <IconMore size={17} />
          <span>Meer</span>
        </button>
      </nav>
    </div>
  )
}

function SideLink({ item }: { item: NavItem }) {
  return (
    <NavLink
      to={item.to}
      end={item.to === '/'}
      className={({ isActive }) => (isActive ? 'navlink navlink--active' : 'navlink')}
    >
      {item.icon}
      <span>{item.label}</span>
      {item.badge ? <span className="navlink__badge">{item.badge}</span> : null}
    </NavLink>
  )
}
