import { ref } from 'vue'

import { api, ApiError, type User } from './api'

/** 当前登录用户；null 表示未登录。 */
export const currentUser = ref<User | null>(null)

let checked = false

/** 向后端确认一次登录状态，之后直接用内存里的结果。 */
export async function ensureUserLoaded(): Promise<User | null> {
  if (checked) return currentUser.value
  try {
    currentUser.value = await api.me()
    checked = true
  } catch (e) {
    currentUser.value = null
    // 只有明确的"未登录"才记为已确认；网络故障下次还要重试
    checked = e instanceof ApiError && e.status === 401
  }
  return currentUser.value
}

export function setUser(user: User | null): void {
  currentUser.value = user
  checked = true
}
