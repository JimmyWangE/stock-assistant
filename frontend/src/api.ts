// 所有后端请求都从这里走。登录凭证在 httpOnly cookie 里，由浏览器自动携带。

export interface User {
  id: number
  username: string
}

/** 大盘指数。percent 是涨跌幅（百分数）。 */
export interface MarketIndex {
  code: string
  name: string
  price: number
  prev_close: number
  open: number
  high: number
  low: number
  change: number
  percent: number
  amount_yi: number
}

export interface SectorRow {
  name: string
  percent: number
  leader: string
  leader_percent: number
  /** 资金净流入，亿元 */
  inflow_yi: number
  up: number
  down: number
}

/** 排行榜里的一只股票。turnover 是换手率（%）。 */
export interface StockRow {
  code: string
  name: string
  price: number
  percent: number
  amount_yi: number
  turnover: number
}

/** 指数详情：当日分时 + 最近 120 日日 K。 */
export interface IndexDetail extends MarketIndex {
  as_of: string
  date: string
  /** 每分钟 [时间, 点位, 成交量（手）] */
  minutes: [string, number, number][]
  bars: KlineBlock['bars']
  source: { name: string; url: string }
}

export interface NewsRow {
  title: string
  url: string
  time: string
  source?: string
}

/** 市场看板快照。各板块取不到数据时为空数组或 null，页面据此隐藏。 */
export interface MarketBoard {
  indices: MarketIndex[]
  as_of: string
  session: string
  /** 各指数当天的分时价格，按指数代码取 */
  sparks: Record<string, number[]>
  breadth: {
    up: number
    down: number
    flat: number
    limit_up: number
    limit_down: number
    as_of: string
  } | null
  market: {
    distribution: { label: string; count: number }[]
    gainers: StockRow[]
    losers: StockRow[]
    active: StockRow[]
    turnover_yi: number
    count: number
    as_of: string
  } | null
  sectors: { top: SectorRow[]; bottom: SectorRow[]; all: SectorRow[] } | null
  headlines: NewsRow[]
  policies: NewsRow[]
}

export interface ConversationSummary {
  id: string
  title: string
  updated_at: string
}

/** K 线图数据。bars 每根为 [时间, 开, 收, 低, 高, 成交量（股）]。 */
export interface KlineBlock {
  type: 'kline'
  title: string
  as_of: string
  source: { name: string; url: string }
  bars: [string, number, number, number, number, number][]
}

/** 数据表格。每行第一格是行名，其余与 columns 一一对应。 */
export interface TableBlock {
  type: 'table'
  title: string
  columns: string[]
  rows: string[][]
  note?: string
  source: { name: string; url: string }
}

/** 行情卡片。 */
export interface QuoteBlock {
  type: 'quote'
  name: string
  code: string
  price: number
  prev_close: number
  open: number
  high: number
  low: number
  volume_lots: number
  amount_yi: number
  as_of: string
  source: { name: string; url: string }
}

/** 诊股评分的一项。delta 为该条依据的加减分，0 表示只作参考。score 为 null 表示没有数据。 */
export interface DiagnosisDimension {
  name: string
  score: number | null
  level: string
  items: { text: string; delta: number }[]
  note: string
}

/** 诊股评分卡。 */
export interface DiagnosisBlock {
  type: 'diagnosis'
  code: string
  name: string
  industry: string
  price: number | null
  percent: number | null
  as_of: string
  score: number | null
  level: string
  dimensions: DiagnosisDimension[]
  disclaimer: string
}

/** 随回答展示、不经过模型的内容块。 */
export type Block = KlineBlock | TableBlock | QuoteBlock | DiagnosisBlock

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  blocks?: Block[] | null
  failed?: boolean
}

export interface ConversationDetail extends ConversationSummary {
  messages: ChatMessage[]
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message)
  }
}

async function toError(resp: Response): Promise<ApiError> {
  let message = `请求失败（${resp.status}）`
  try {
    const body = await resp.json()
    // 后端主动抛出的错误 detail 是一句中文；参数校验失败时是数组，不直接展示
    if (typeof body.detail === 'string') message = body.detail
    else if (resp.status === 422) message = '输入内容不符合要求'
  } catch {
    // 响应不是 JSON（例如网关错误页），保留默认提示
  }
  return new ApiError(resp.status, message)
}

async function request<T>(method: string, url: string, body?: unknown): Promise<T> {
  const resp = await send(method, url, body)
  return resp.json() as Promise<T>
}

async function send(method: string, url: string, body?: unknown): Promise<Response> {
  let resp: Response
  try {
    resp = await fetch(url, {
      method,
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new ApiError(0, '无法连接服务器，请检查网络')
  }
  if (!resp.ok) throw await toError(resp)
  return resp
}

export const api = {
  me: () => request<User>('GET', '/api/auth/me'),
  login: (username: string, password: string) =>
    request<User>('POST', '/api/auth/login', { username, password }),
  register: (username: string, password: string) =>
    request<User>('POST', '/api/auth/register', { username, password }),
  logout: () => request<unknown>('POST', '/api/auth/logout'),
  board: () => request<MarketBoard>('GET', '/api/market/board'),
  /** 登录页用，不需要登录 */
  ticker: () =>
    request<{ indices: MarketIndex[]; as_of: string; session: string }>('GET', '/api/market/ticker'),
  indexDetail: (code: string) =>
    request<IndexDetail>('GET', `/api/market/index/${encodeURIComponent(code)}`),
  /** 带关键词时只返回标题或正文含该词的会话。 */
  listConversations: (keyword = '') =>
    request<ConversationSummary[]>(
      'GET',
      keyword ? `/api/conversations?q=${encodeURIComponent(keyword)}` : '/api/conversations',
    ),
  renameConversation: (id: string, title: string) =>
    request<ConversationSummary>('PATCH', `/api/conversations/${encodeURIComponent(id)}`, { title }),
  deleteConversation: (id: string) =>
    send('DELETE', `/api/conversations/${encodeURIComponent(id)}`),
  getConversation: (id: string) =>
    request<ConversationDetail>('GET', `/api/conversations/${encodeURIComponent(id)}`),
}

export type ChatEvent =
  | { event: 'meta'; data: { conversation_id: string; title: string } }
  | { event: 'status'; data: { text: string } }
  | { event: 'delta'; data: { text: string } }
  | { event: 'block'; data: Block }
  | { event: 'error'; data: { message: string } }
  | { event: 'done'; data: Record<string, never> }

/** 提问并逐个回调后端推来的事件；流结束时返回。 */
export async function streamChat(
  body: { conversation_id: string | null; content: string },
  onEvent: (e: ChatEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const resp = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })
  if (!resp.ok || !resp.body) throw await toError(resp)

  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    // 事件之间以空行分隔；最后一段可能不完整，留到下一轮
    let end: number
    while ((end = buffer.indexOf('\n\n')) >= 0) {
      const block = buffer.slice(0, end)
      buffer = buffer.slice(end + 2)
      let event = ''
      let data = ''
      for (const line of block.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim()
        else if (line.startsWith('data:')) data += line.slice(5).trim()
      }
      if (event && data) onEvent({ event, data: JSON.parse(data) } as ChatEvent)
    }
  }
}

/** 火眼金睛的一只候选股。 */
export interface HawkeyePick {
  code: string
  name: string
  score: number
  stars: number
  catalyst_score: number
  market_score: number
  catalysts: { kind: string; title: string; url: string; date: string }[]
  warnings: { title: string; url: string }[]
  reasons: string[]
  risks: string[]
  price: number
  prev_close: number
  open: number | null
  gap: number | null
  pct: number | null
  volume_ratio: number | null
  mktcap: number
}

export interface HawkeyeResult {
  phase: string
  preview: boolean
  as_of: string
  window: string
  scanned: number
  picks: HawkeyePick[]
}

export interface HawkeyeDay {
  date: string
  avg: number | null
  win_rate: number | null
  picks: { code: string; name: string; score: number; stars: number; kinds: string[]; price: number | null; since_open: number | null }[]
}

export const hawkeyeApi = {
  today: () => request<HawkeyeResult>('GET', '/api/hawkeye'),
  history: () => request<HawkeyeDay[]>('GET', '/api/hawkeye/history'),
}

/** 个股行情与估值。数值取不到时为 null。 */
export interface StockQuote {
  code: string
  name: string
  price: number | null
  prev_close: number | null
  open: number | null
  volume_lots: number | null
  change: number | null
  percent: number | null
  high: number | null
  low: number | null
  amount_yi: number
  turnover: number | null
  pe_ttm: number | null
  amplitude: number | null
  /** 亿元 */
  float_mktcap: number | null
  /** 亿元 */
  mktcap: number | null
  pb: number | null
  limit_up: number | null
  limit_down: number | null
  volume_ratio: number | null
  dividend_yield: number | null
  high_52w: number | null
  low_52w: number | null
  as_of: string
}

export interface StockProfile extends StockQuote {
  industry: string
  date: string
  /** 每分钟 [时间, 价格, 成交量（手）] */
  minutes: [string, number, number][]
  bars: KlineBlock['bars']
  source: { name: string; url: string }
}

export interface Announcement {
  code: string
  name: string
  id: string
  title: string
  date: string
  time: string
  type: string
  url: string
}

export interface StockNewsItem {
  title: string
  url: string
  time: string
  source: string
  summary: string
}

export const stockApi = {
  search: (q: string) =>
    request<{ code: string; name: string }[]>('GET', `/api/stock/search?q=${encodeURIComponent(q)}`),
  profile: (code: string) => request<StockProfile>('GET', `/api/stock/${encodeURIComponent(code)}`),
  financials: (code: string) =>
    request<TableBlock>('GET', `/api/stock/${encodeURIComponent(code)}/financials`),
  news: (code: string) =>
    request<{ announcements: Announcement[]; news: StockNewsItem[]; errors: string[] }>(
      'GET',
      `/api/stock/${encodeURIComponent(code)}/news`,
    ),
  diagnosis: (code: string) =>
    request<DiagnosisBlock>('GET', `/api/stock/${encodeURIComponent(code)}/diagnosis`),
}

export interface WatchItem {
  code: string
  name: string
  /** 涨跌幅提醒阈值（%） */
  alert_pct: number
  quote: StockQuote | null
}

export interface AlertItem {
  id: number
  code: string
  name: string
  kind: string
  message: string
  url: string | null
  read: boolean
  created_at: string
}

export const watchApi = {
  list: () => request<WatchItem[]>('GET', '/api/watchlist'),
  add: (symbol: string) => request<WatchItem>('POST', '/api/watchlist', { symbol }),
  remove: (code: string) => send('DELETE', `/api/watchlist/${encodeURIComponent(code)}`),
  setThreshold: (code: string, alertPct: number) =>
    request<WatchItem>('PATCH', `/api/watchlist/${encodeURIComponent(code)}`, { alert_pct: alertPct }),
  alerts: () => request<{ unread: number; items: AlertItem[] }>('GET', '/api/alerts'),
  markRead: () => request<unknown>('POST', '/api/alerts/read'),
}

export interface ReportSummary {
  date: string
  kind: 'morning' | 'close'
  title: string
  created_at: string
  summary?: string
}

export interface Report extends ReportSummary {
  content: string
  /** 生成报告时交给模型的数据原文 */
  facts: string
}

export const reportApi = {
  list: () => request<ReportSummary[]>('GET', '/api/reports'),
  latest: () => request<{ report: Report | null }>('GET', '/api/reports/latest'),
  get: (date: string, kind: string) =>
    request<Report>('GET', `/api/reports/${encodeURIComponent(date)}/${encodeURIComponent(kind)}`),
}
