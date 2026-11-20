<script setup lang="ts">
import { Bell } from '@element-plus/icons-vue'
import { ElNotification } from 'element-plus'
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { watchApi, type AlertItem } from '../api'
import { beijingTime } from '../market'

const router = useRouter()
const unread = ref(0)
const items = ref<AlertItem[]>([])
const open = ref(false)
let lastSeenId = 0
let timer: ReturnType<typeof setInterval> | undefined

/** 每 30 秒查一次提醒；有新提醒时在右上角弹出通知。 */
async function refresh(): Promise<void> {
  if (document.hidden) return
  try {
    const data = await watchApi.alerts()
    const fresh = lastSeenId ? data.items.filter((a) => a.id > lastSeenId && !a.read) : []
    // 一次最多弹 3 条，避免刷屏
    for (const a of fresh.slice(0, 3).reverse()) {
      ElNotification({ title: `${a.kind}提醒`, message: a.message, type: 'info', duration: 8000, offset: 60 })
    }
    lastSeenId = Math.max(lastSeenId, ...data.items.map((a) => a.id), 0) || -1
    unread.value = data.unread
    items.value = data.items
  } catch {
    // 提醒只是辅助信息，取不到就等下一轮
  }
}

async function readAll(): Promise<void> {
  await watchApi.markRead()
  unread.value = 0
  items.value = items.value.map((a) => ({ ...a, read: true }))
}

function go(a: AlertItem): void {
  open.value = false
  if (a.url?.startsWith('http')) window.open(a.url, '_blank', 'noopener')
  else router.push(a.url || `/stock/${a.code}`)
}

onMounted(() => {
  refresh()
  timer = setInterval(refresh, 30000)
  document.addEventListener('visibilitychange', refresh)
})
onBeforeUnmount(() => {
  clearInterval(timer)
  document.removeEventListener('visibilitychange', refresh)
})
</script>

<template>
  <el-popover v-model:visible="open" trigger="click" placement="bottom-end" :width="380">
    <template #reference>
      <button type="button" class="bell" :aria-label="`提醒，${unread} 条未读`">
        <el-badge :value="unread" :hidden="!unread" :max="99">
          <el-icon :size="18"><Bell /></el-icon>
        </el-badge>
      </button>
    </template>
    <div class="panel">
      <div class="panel-head">
        <b>自选股提醒</b>
        <el-button v-if="unread" link type="primary" @click="readAll">全部标为已读</el-button>
      </div>
      <p v-if="!items.length" class="empty">
        暂无提醒。把股票加入自选后，涨跌幅达到阈值、涨跌停、发布新公告或入选火眼金睛时会在这里提醒。
      </p>
      <ul v-else class="list">
        <li v-for="a in items" :key="a.id" :class="{ unread: !a.read }" @click="go(a)">
          <span class="kind">{{ a.kind }}</span>
          <span class="msg">{{ a.message }}</span>
          <span class="time">{{ beijingTime(a.created_at) }}</span>
        </li>
      </ul>
    </div>
  </el-popover>
</template>

<style scoped>
.bell {
  display: flex;
  align-items: center;
  height: 32px;
  padding: 0 6px;
  border: 0;
  background: none;
  color: var(--on-navy);
  cursor: pointer;
}
.bell:hover {
  color: #fff;
}
.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}
.empty {
  margin: 8px 0;
  color: var(--text-muted);
  font-size: 13px;
  line-height: 1.6;
}
.list {
  max-height: 420px;
  margin: 0;
  padding: 0;
  overflow-y: auto;
  list-style: none;
}
.list li {
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: 8px;
  padding: 8px 4px;
  border-top: 1px solid var(--line);
  font-size: 13px;
  line-height: 1.5;
  cursor: pointer;
}
.list li:hover {
  background: var(--surface-alt);
}
.list li.unread .msg {
  font-weight: 600;
}
.kind {
  height: 20px;
  padding: 0 6px;
  border-radius: 4px;
  background: var(--brand-soft);
  color: var(--brand);
  font-size: 12px;
  line-height: 20px;
}
.time {
  color: var(--text-muted);
  font-size: 12px;
  white-space: nowrap;
}
</style>
