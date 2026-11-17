import { ref } from 'vue'

import { api, type MarketBoard } from './api'

/** 市场看板的最新快照，顶栏和右侧看板共用；还没取到时为 null。 */
export const board = ref<MarketBoard | null>(null)

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
