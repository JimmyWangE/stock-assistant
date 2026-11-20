import { ref } from 'vue'

import { api, type MarketBoard } from './api'

/** 市场看板的最新快照，顶栏、概览页和右侧看板共用；还没取到时为 null。 */
export const board = ref<MarketBoard | null>(null)

/** 当前打开详情的指数代码；null 表示详情抽屉关闭。 */
export const openedIndex = ref<string | null>(null)

export function openIndex(code: string): void {
  openedIndex.value = code
}

let timer: ReturnType<typeof setInterval> | undefined

async function refresh(): Promise<void> {
  // 页面在后台时不刷新，省请求
  if (document.hidden) return
  try {
    board.value = await api.board()
  } catch {
    // 看板只是辅助信息：取不到就保持上一次的内容，不打扰用户
  }
}

/** 开始定时刷新看板。后端每 5 秒更新一次指数，这里同样 5 秒取一次。 */
export function startBoard(): void {
  if (timer) return
  refresh()
  timer = setInterval(refresh, 5000)
  document.addEventListener('visibilitychange', refresh)
}

export function stopBoard(): void {
  clearInterval(timer)
  timer = undefined
  document.removeEventListener('visibilitychange', refresh)
}

export function trend(value: number): 'up' | 'down' | 'flat' {
  return value > 0 ? 'up' : value < 0 ? 'down' : 'flat'
}

/** 带正负号的两位小数，涨跌同时用符号和颜色表示。 */
export function signed(value: number): string {
  return `${value > 0 ? '+' : ''}${value.toFixed(2)}`
}

/** 亿元金额：一万亿以上显示为"万亿"。 */
export function yi(value: number): string {
  return value >= 10000 ? `${(value / 10000).toFixed(2)} 万亿` : `${value.toFixed(0)} 亿`
}

/** 今天的日期和星期，北京时间。 */
export function todayLabel(): string {
  const now = new Date(Date.now() + 8 * 3600_000)
  const week = '日一二三四五六'[now.getUTCDay()]
  return `${now.getUTCFullYear()}年${now.getUTCMonth() + 1}月${now.getUTCDate()}日 星期${week}`
}

/** ISO 时间按北京时间显示：今天的只显示时分，否则显示"月-日 时:分"。不随用户电脑的时区变化。 */
export function beijingTime(iso: string, withDate = false): string {
  const shift = (t: number) => new Date(t + 8 * 3600_000)
  const d = shift(new Date(iso).getTime())
  const today = shift(Date.now())
  const pad = (n: number) => String(n).padStart(2, '0')
  const hm = `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`
  const sameDay = d.toISOString().slice(0, 10) === today.toISOString().slice(0, 10)
  return sameDay && !withDate ? hm : `${d.getUTCMonth() + 1}月${d.getUTCDate()}日 ${hm}`
}
