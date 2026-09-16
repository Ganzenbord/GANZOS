/* Eenvoudige lijniconen. Bewust geen icoonbibliotheek: dit zijn er een stuk of
   twintig en het scheelt een afhankelijkheid die bij elke update meeverandert. */

interface IconProps {
  size?: number
  className?: string
}

function svg(path: JSX.Element, { size = 16, className }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden
    >
      {path}
    </svg>
  )
}

export const IconHome = (p: IconProps) =>
  svg(<><path d="M3 10.5 12 3l9 7.5" /><path d="M5 9.5V21h14V9.5" /></>, p)
export const IconCore = (p: IconProps) =>
  svg(<><circle cx="12" cy="12" r="9" /><circle cx="12" cy="12" r="3" /></>, p)
export const IconSkills = (p: IconProps) =>
  svg(<><circle cx="12" cy="5" r="2.2" /><circle cx="5" cy="18" r="2.2" /><circle cx="19" cy="18" r="2.2" /><path d="M12 7.2v4M10.2 13 6.6 16M13.8 13l3.6 3" /></>, p)
export const IconCalendar = (p: IconProps) =>
  svg(<><rect x="3" y="5" width="18" height="16" rx="2" /><path d="M3 10h18M8 3v4M16 3v4" /></>, p)
export const IconMemory = (p: IconProps) =>
  svg(<><path d="M12 4a4 4 0 0 0-4 4v1a3 3 0 0 0 0 6v1a4 4 0 0 0 8 0v-1a3 3 0 0 0 0-6V8a4 4 0 0 0-4-4Z" /></>, p)
export const IconChat = (p: IconProps) =>
  svg(<><path d="M20 15a2 2 0 0 1-2 2H8l-4 4V6a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2Z" /></>, p)
export const IconPlay = (p: IconProps) =>
  svg(<><rect x="2.5" y="5" width="19" height="14" rx="3" /><path d="M10.5 9.5 15 12l-4.5 2.5Z" /></>, p)
export const IconUsers = (p: IconProps) =>
  svg(<><circle cx="9" cy="8" r="3" /><path d="M3 20a6 6 0 0 1 12 0M17 11a3 3 0 1 0-2-5.2M18 20a5.5 5.5 0 0 0-2.5-4.6" /></>, p)
export const IconLink = (p: IconProps) =>
  svg(<><path d="M10 14a4 4 0 0 0 5.7 0l2.8-2.8a4 4 0 0 0-5.7-5.7L11.5 6.9" /><path d="M14 10a4 4 0 0 0-5.7 0L5.5 12.8a4 4 0 0 0 5.7 5.7l1.3-1.3" /></>, p)
export const IconLog = (p: IconProps) =>
  svg(<><rect x="4" y="3" width="16" height="18" rx="2" /><path d="M8 8h8M8 12h8M8 16h5" /></>, p)
export const IconFlow = (p: IconProps) =>
  svg(<><rect x="3" y="3" width="6" height="6" rx="1.5" /><rect x="15" y="15" width="6" height="6" rx="1.5" /><path d="M9 6h4a2 2 0 0 1 2 2v10" /></>, p)
export const IconWallet = (p: IconProps) =>
  svg(<><path d="M3 7a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v1" /><rect x="3" y="7" width="18" height="12" rx="2" /><circle cx="16.5" cy="13" r="1.1" fill="currentColor" /></>, p)
export const IconChart = (p: IconProps) =>
  svg(<><path d="M4 19V5M4 19h16" /><path d="M8 16v-4M12 16V8M16 16v-6" /></>, p)
export const IconUpload = (p: IconProps) =>
  svg(<><path d="M12 16V5" /><path d="m8 9 4-4 4 4" /><path d="M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" /></>, p)
export const IconCpu = (p: IconProps) =>
  svg(<><rect x="6" y="6" width="12" height="12" rx="2" /><path d="M9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3" /></>, p)
export const IconBell = (p: IconProps) =>
  svg(<><path d="M18 15V10a6 6 0 0 0-12 0v5l-1.5 2.5h15Z" /><path d="M10 20a2 2 0 0 0 4 0" /></>, p)
export const IconSettings = (p: IconProps) =>
  svg(<><circle cx="12" cy="12" r="3" /><path d="M19.4 14a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-2.9 1.2V20a2 2 0 1 1-4 0v-.1A1.7 1.7 0 0 0 7 18.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0-1.2-2.9H3a2 2 0 1 1 0-4h.1A1.7 1.7 0 0 0 4.3 7l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 2.9-1.2V3a2 2 0 1 1 4 0v.1A1.7 1.7 0 0 0 17 4.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0 1.2 2.9H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z" /></>, p)
export const IconSearch = (p: IconProps) =>
  svg(<><circle cx="11" cy="11" r="6.5" /><path d="m20 20-4.2-4.2" /></>, p)
export const IconMic = (p: IconProps) =>
  svg(<><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" /></>, p)
export const IconPlus = (p: IconProps) => svg(<><path d="M12 5v14M5 12h14" /></>, p)
export const IconMail = (p: IconProps) =>
  svg(<><rect x="3" y="5" width="18" height="14" rx="2" /><path d="m3 7 9 6 9-6" /></>, p)
export const IconRefresh = (p: IconProps) =>
  svg(<><path d="M20 11a8 8 0 1 0-1.6 5.4" /><path d="M20 5v6h-6" /></>, p)
export const IconTrash = (p: IconProps) =>
  svg(<><path d="M4 7h16M9 7V5h6v2M6 7l1 13h10l1-13" /></>, p)
