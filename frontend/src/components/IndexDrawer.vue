<script setup lang="ts">
import { MagicStick } from '@element-plus/icons-vue'
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import { api, type IndexDetail, type KlineBlock } from '../api'
import { openedIndex, signed, trend } from '../market'
import IntradayChart from './IntradayChart.vue'
import KlineChart from './KlineChart.vue'

const router = useRouter()
const detail = ref<IndexDetail | null>(null)
const error = ref('')
const loading = ref(false)
const tab = ref<'minute' | 'day'>('minute')

const visible = computed({
  get: () => openedIndex.value !== null,
  set: (v: boolean) => {
    if (!v) openedIndex.value = null
  },
})

async function load(code: string): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const data = await api.indexDetail(code)
    // 加载期间用户可能已经换了别的指数
    if (openedIndex.value === code) detail.value = data
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}

watch(openedIndex, (code) => {
  if (!code) return
  if (detail.value?.code !== code) {
    detail.value = null
    tab.value = 'minute'
  }
  load(code)
})

const kline = computed<KlineBlock | null>(() =>
  detail.value && detail.value.bars.length > 1
    ? {
        type: 'kline',
        title: `${detail.value.name} 日K`,
        as_of: detail.value.bars[detail.value.bars.length - 1][0],
        source: detail.value.source,
        bars: detail.value.bars,
      }
    : null,
)

const amplitude = computed(() => {
  const d = detail.value
  return d ? ((d.high - d.low) / d.prev_close) * 100 : 0
})

function askAi(): void {
  if (!detail.value) return
  const q = `分析一下今天${detail.value.name}的走势和市场情绪`
  openedIndex.value = null
  router.push({ name: 'new-chat', query: { q } })
}
</script>

<template>
  <el-drawer v-model="visible" size="720px" :with-header="false" class="index-drawer">
    <div v-if="detail" class="wrap">
      <header class="head">
        <div>
          <div class="title">
            {{ detail.name }}<span class="code">{{ detail.code.slice(2) }}</span>
          </div>
          <div class="price-row" :class="trend(detail.change)">
            <span class="price">{{ detail.price.toFixed(2) }}</span>
            <span>{{ signed(detail.change) }}</span>
            <span>{{ signed(detail.percent) }}%</span>
          </div>
          <div class="as-of">{{ detail.as_of }} · 来源 {{ detail.source.name }}</div>
        </div>
        <el-button type="primary" :icon="MagicStick" @click="askAi">AI 解读今日走势</el-button>
      </header>

      <dl class="stats">
        <div><dt>今开</dt><dd :class="trend(detail.open - detail.prev_close)">{{ detail.open.toFixed(2) }}</dd></div>
        <div><dt>最高</dt><dd :class="trend(detail.high - detail.prev_close)">{{ detail.high.toFixed(2) }}</dd></div>
        <div><dt>最低</dt><dd :class="trend(detail.low - detail.prev_close)">{{ detail.low.toFixed(2) }}</dd></div>
        <div><dt>昨收</dt><dd>{{ detail.prev_close.toFixed(2) }}</dd></div>
        <div><dt>振幅</dt><dd>{{ amplitude.toFixed(2) }}%</dd></div>
        <div><dt>成交额</dt><dd>{{ detail.amount_yi.toFixed(0) }} 亿</dd></div>
      </dl>

      <div class="tabs" role="tablist">
        <button type="button" role="tab" :aria-selected="tab === 'minute'" :class="{ active: tab === 'minute' }" @click="tab = 'minute'">
          分时 · {{ detail.date }}
        </button>
        <button type="button" role="tab" :aria-selected="tab === 'day'" :class="{ active: tab === 'day' }" :disabled="!kline" @click="tab = 'day'">
          日 K{{ kline ? '' : '（暂无）' }}
        </button>
      </div>
      <IntradayChart v-if="tab === 'minute'" :minutes="detail.minutes" :prev-close="detail.prev_close" />
      <KlineChart v-else-if="kline" :key="detail.code" :block="kline" />
    </div>
    <div v-else class="placeholder">
      <p v-if="error">{{ error }}</p>
      <p v-else-if="loading">正在加载…</p>
    </div>
  </el-drawer>
</template>

<style scoped>
.wrap {
  font-variant-numeric: tabular-nums;
}
.head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--line);
}
.title {
  color: var(--navy);
  font-size: 20px;
  font-weight: 600;
}
.code {
  margin-left: 8px;
  color: var(--text-muted);
  font-size: 13px;
  font-weight: 400;
}
.price-row {
  display: flex;
  align-items: baseline;
  gap: 12px;
  margin-top: 2px;
  font-size: 16px;
  font-weight: 600;
}
.price {
  font-size: 32px;
  font-weight: 700;
}
.as-of {
  color: var(--text-muted);
  font-size: 12px;
}
.stats {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 8px;
  margin: 14px 0;
}
.stats div {
  padding: 8px 10px;
  border-radius: 6px;
  background: var(--surface-alt);
}
.stats dt {
  color: var(--text-muted);
  font-size: 12px;
}
.stats dd {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
}
.up {
  color: var(--up);
}
.down {
  color: var(--down);
}
.tabs {
  display: flex;
  gap: 20px;
  margin-bottom: 10px;
  border-bottom: 1px solid var(--line);
}
.tabs button {
  margin-bottom: -1px;
  padding: 0 0 8px;
  border: 0;
  border-bottom: 2px solid transparent;
  background: none;
  color: var(--text-muted);
  font: inherit;
  font-weight: 600;
  cursor: pointer;
}
.tabs button:disabled {
  cursor: default;
  opacity: 0.6;
}
.tabs button.active {
  border-bottom-color: var(--gold);
  color: var(--navy);
}
.placeholder {
  padding-top: 40px;
  color: var(--text-muted);
  text-align: center;
}
</style>
