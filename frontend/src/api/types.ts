/* De vorm van wat de backend teruggeeft.
   Bedragen komen binnen als tekst, niet als getal: een float zou bij optellen centen
   laten verdwijnen. Rekenen doet de backend; hier tonen we alleen. */

export type Tier = 1 | 2 | 3 | 4 | null;  // null = wel bekend, geen toegang

export interface Subtask {
  id: number
  title: string
  sort_order: number
  completed: boolean
}

export interface TodoTask {
  id: number
  title: string
  description: string | null
  category: string | null
  priority: string
  recurrence: string
  scheduled_time: string | null
  sort_order: number
  active: boolean
  subtasks: Subtask[]
}

export interface TodoDayTask extends TodoTask {
  completed: boolean
  completed_at: string | null
}

export interface TodoDay {
  date: string
  total: number
  completed: number
  tasks: TodoDayTask[]
}

export interface FinanceBreakdownRow {
  account_type: string
  total_eur: string
}

export interface FinanceOverview {
  total_eur: string
  connected_accounts: number
  counted_accounts: number
  excluded_accounts: { name: string; reason: string }[]
  breakdown: FinanceBreakdownRow[]
  last_updated: string | null
  stale: boolean
  trend_pct: number | null
  server_time: string
}

export interface FinancialAccount {
  id: number
  provider: string
  account_type: string
  name: string
  currency: string
  current_value: string | null
  current_value_eur: string | null
  last_synced_at: string | null
  status: string
  status_detail: string | null
  active: boolean
}

export interface PlatformTotals {
  platform: string
  channels: number
  followers: number | null
  views: number | null
  likes: number | null
  comments: number | null
  posts: number | null
}

export interface SocialOverview {
  followers: number | null
  views: number | null
  likes: number | null
  comments: number | null
  posts: number | null
  growth_pct: number | null
  revenue: string | null
  revenue_currency: string | null
  revenue_available: boolean
  channels_total: number
  channels_counted: number
  platforms: PlatformTotals[]
  attention: { id: number; platform: string; channel_name: string; status: string; detail: string | null }[]
  last_updated: string | null
  server_time: string
}

export interface SocialChannel {
  id: number
  platform: string
  channel_name: string
  external_channel_id: string | null
  active: boolean
  status: string
  status_detail: string | null
  last_synced_at: string | null
}

export interface Upload {
  id: number
  channel_id: number
  title: string | null
  content_type: string
  status: string
  status_detail: string | null
  recurrence: string
  timezone: string
  scheduled_at: string
  effective_at: string | null
  seconds_until: number | null
  overdue: boolean
  channel_name?: string | null
  platform?: string | null
}

export interface ChannelScheduleRow {
  channel_id: number
  platform: string
  channel_name: string
  channel_status: string
  channel_active: boolean
  needs_reauth: boolean
  next_upload: Upload | null
}

export interface ScheduleOverview {
  server_time: string
  channels: ChannelScheduleRow[]
}

export interface SystemSample {
  cpu_pct: number
  ram_pct: number
  disk_pct: number
  measured_at: string
}

export interface SystemStatus extends SystemSample {
  status: string
  status_detail: string
  history: SystemSample[]
  boot_time: string
}

export interface CoreStatus {
  core_status: string
  core_detail: string
  voice_status: string
  skills_count: number
  integrations_total: number
  integrations_connected: number
  system_status: string
  system_detail: string
}

export interface Mission {
  id: number
  title: string
  status: string
  scheduled_for: string | null
  completed_at: string | null
  is_done: boolean
}

export interface LlmStatus {
  provider: string
  model: string | null
  status: string
  latency_ms: number | null
  detail: string | null
  checked_at: string | null
}

export interface FeedItem {
  id: number
  action: string
  message: string
  created_at: string
}

export interface Dashboard {
  server_time: string
  user: { id: number; display_name: string; tier: Tier; permissions: string[] }
  core: CoreStatus
  todo: TodoDay | null
  missions: Mission[] | null
  finance: FinanceOverview | null
  social: SocialOverview | null
  uploads: ScheduleOverview | null
  system: SystemStatus | null
  memory: { memories: number; sessions: number } | null
  llm: LlmStatus[]
  feed: FeedItem[]
}

export interface Integration {
  id: number
  key: string
  name: string
  category: string | null
  status: string
  status_detail: string | null
  last_checked_at: string | null
}
