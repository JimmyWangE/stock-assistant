import { ref } from 'vue'

import { watchApi } from './api'

/** 当前用户自选股的代码，详情页的"加自选"按钮和各处的星标共用。 */
export const watchedCodes = ref<Set<string>>(new Set())
let loaded: Promise<void> | null = null

export function loadWatched(force = false): Promise<void> {
  if (!loaded || force) {
    loaded = watchApi
      .list()
      .then((items) => {
        watchedCodes.value = new Set(items.map((i) => i.code))
      })
      .catch(() => {
        loaded = null
      })
  }
  return loaded
}

export async function toggleWatch(code: string): Promise<boolean> {
  const next = new Set(watchedCodes.value)
  if (next.has(code)) {
    await watchApi.remove(code)
    next.delete(code)
  } else {
    await watchApi.add(code)
    next.add(code)
  }
  watchedCodes.value = next
  return next.has(code)
}
