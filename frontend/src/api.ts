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
  change: number
  percent: number
  amount_yi: number
}

export interface SectorRow {
  name: string
  percent: number
  leader: string
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
  sectors: { top: SectorRow[]; bottom: SectorRow[] } | null
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

/** 随回答展示、不经过模型的内容块。 */
export type Block = KlineBlock | TableBlock | QuoteBlock

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
