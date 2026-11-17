<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'

import { api, type MarketIndex } from '../api'

const indices = ref<MarketIndex[]>([])
const asOf = ref('')
let timer: ReturnType<typeof setInterval> | undefined

async function refresh(): Promise<void> {
  // 页面在后台时不刷新，省请求
  if (document.hidden) return
  try {
    const data = await api.indices()
    indices.value = data.indices
    asOf.value = data.as_of
  } catch {
    // 指数条只是辅助信息：取不到就保持上一次的内容，不打扰用户
  }
}

function trend(value: number): 'up' | 'down' | 'flat' {
  return value > 0 ? 'up' : value < 0 ? 'down' : 'flat'
}

function signed(value: number): string {
  return `${value > 0 ? '+' : ''}${value.toFixed(2)}`
}

onMounted(() => {
  refresh()
  timer = setInterval(refresh, 10_000)
  document.addEventListener('visibilitychange', refresh)
})
onBeforeUnmount(() => {
  clearInterval(timer)
  document.removeEventListener('visibilitychange', refresh)
})
</script>

<template>
  <header class="market-bar">
    <ul v-if="indices.length" class="indices">
      <li v-for="item in indices" :key="item.name" :class="trend(item.change)">
        <span class="name">{{ item.name }}</span>
        <span class="price">{{ item.price.toFixed(2) }}</span>
        <!-- 涨跌同时用符号和颜色表示，不只靠颜色 -->
        <span class="change">{{ signed(item.change) }}</span>
        <span class="change">{{ signed(item.percent) }}%</span>
      </li>
    </ul>
    <span v-else class="placeholder">A 股投研工作台</span>
    <span v-if="asOf" class="as-of">行情时间 {{ asOf.slice(5, 16) }} · 腾讯财经</span>
  </header>
</template>

<style scoped>
.market-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  height: 44px;
  flex-shrink: 0;
  padding: 0 20px;
  border-bottom: 1px solid var(--line);
  background: var(--surface);
  font-size: 13px;
  white-space: nowrap;
  overflow: hidden;
}
/* 放不下的指数会折到第二行，而容器只有一行高，所以它们整个不显示，不会出现截断一半的数字 */
.indices {
  display: flex;
  flex-wrap: wrap;
  height: 44px;
  min-width: 0;
  margin: 0;
  padding: 0;
  list-style: none;
  overflow: hidden;
}
.indices li {
  display: flex;
  align-items: baseline;
  gap: 7px;
  height: 44px;
  padding-right: 22px;
  line-height: 44px;
  font-variant-numeric: tabular-nums;
}
.name {
  color: var(--text-muted);
}
.price {
  font-weight: 600;
}
.change {
  font-size: 12px;
}
.up .price,
.up .change {
  color: var(--up);
}
.down .price,
.down .change {
  color: var(--down);
}
.placeholder,
.as-of {
  color: var(--text-muted);
  font-size: 12px;
}
.as-of {
  flex-shrink: 0;
}
</style>
