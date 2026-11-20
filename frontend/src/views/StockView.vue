<script setup lang="ts">
import { ChatLineSquare, MagicStick, Star, StarFilled } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import {
  stockApi,
  type Announcement,
  type DiagnosisBlock,
  type KlineBlock,
  type StockNewsItem,
  type StockProfile,
  type TableBlock,
} from '../api'
import DataTable from '../components/DataTable.vue'
import DiagnosisCard from '../components/DiagnosisCard.vue'
import IntradayChart from '../components/IntradayChart.vue'
import KlineChart from '../components/KlineChart.vue'
import { board, signed, trend } from '../market'
import { loadWatched, toggleWatch, watchedCodes } from '../watchlist'

const route = useRoute()
const router = useRouter()
const code = computed(() => String(route.params.code))

const profile = ref<StockProfile | null>(null)
const profileError = ref('')
const diagnosis = ref<DiagnosisBlock | null>(null)
const diagnosisError = ref('')
const financials = ref<TableBlock | null>(null)
const financialsError = ref('')
const announcements = ref<Announcement[]>([])
const news = ref<StockNewsItem[]>([])
const newsErrors = ref<string[]>([])
const newsLoading = ref(true)
const chartTab = ref<'minute' | 'day'>('minute')
const newsTab = ref<'announcements' | 'news'>('announcements')
const watching = computed(() => watchedCodes.value.has(code.value))
const busy = ref(false)

function message(e: unknown): string {
  return e instanceof Error ? e.message : '加载失败'
}

async function loadProfile(): Promise<void> {
  const target = code.value
  try {
    const data = await stockApi.profile(target)
    if (target === code.value) {
      profile.value = data
      profileError.value = ''
    }
  } catch (e) {
    if (target === code.value && !profile.value) profileError.value = message(e)
  }
}

async function loadAll(): Promise<void> {
  const target = code.value
  profile.value = null
  diagnosis.value = null
  financials.value = null
  profileError.value = diagnosisError.value = financialsError.value = ''
  announcements.value = []
  news.value = []
  newsLoading.value = true
  chartTab.value = 'minute'
  loadProfile()
  stockApi
    .diagnosis(target)
    .then((d) => target === code.value && (diagnosis.value = d))
    .catch((e) => target === code.value && (diagnosisError.value = message(e)))
  stockApi
    .financials(target)
    .then((d) => target === code.value && (financials.value = d))
    .catch((e) => target === code.value && (financialsError.value = message(e)))
  stockApi
    .news(target)
    .then((d) => {
      if (target !== code.value) return
      announcements.value = d.announcements
      news.value = d.news
      newsErrors.value = d.errors
    })
    .catch(() => target === code.value && (newsErrors.value = ['公告', '新闻']))
    .finally(() => target === code.value && (newsLoading.value = false))
}

watch(code, loadAll, { immediate: true })
loadWatched()

// 交易时段每 10 秒刷新一次行情和分时
const timer = setInterval(() => {
  if (!document.hidden && board.value?.session === '交易中') loadProfile()
}, 10000)
onBeforeUnmount(() => clearInterval(timer))

const kline = computed<KlineBlock | null>(() => {
  const p = profile.value
  if (!p || p.bars.length < 2) return null
  return {
    type: 'kline',
    title: `${p.name} 日K（前复权）`,
    as_of: p.bars[p.bars.length - 1][0],
    source: p.source,
    bars: p.bars,
  }
})

function num(value: number | null, digits = 2, suffix = ''): string {
  return value == null ? '—' : `${value.toFixed(digits)}${suffix}`
}

function side(value: number | null): string {
  const p = profile.value
  return value == null || !p?.prev_close ? '' : trend(value - p.prev_close)
}

const stats = computed(() => {
  const p = profile.value
  if (!p) return []
  return [
    { label: '今开', value: num(p.open), cls: side(p.open) },
    { label: '最高', value: num(p.high), cls: side(p.high) },
    { label: '最低', value: num(p.low), cls: side(p.low) },
    { label: '昨收', value: num(p.prev_close) },
    { label: '成交额', value: `${p.amount_yi.toFixed(2)} 亿` },
    { label: '换手率', value: num(p.turnover, 2, '%') },
    { label: '量比', value: num(p.volume_ratio) },
    { label: '振幅', value: num(p.amplitude, 2, '%') },
    { label: '市盈率 TTM', value: p.pe_ttm != null && p.pe_ttm < 0 ? '亏损' : num(p.pe_ttm) },
    { label: '市净率', value: num(p.pb) },
    { label: '总市值', value: num(p.mktcap, 0, ' 亿') },
    { label: '流通市值', value: num(p.float_mktcap, 0, ' 亿') },
    { label: '股息率', value: num(p.dividend_yield, 2, '%') },
    { label: '52 周最高', value: num(p.high_52w) },
    { label: '52 周最低', value: num(p.low_52w) },
    { label: '涨停 / 跌停', value: `${num(p.limit_up)} / ${num(p.limit_down)}` },
  ]
})

function ask(q: string): void {
  router.push({ name: 'new-chat', query: { q } })
}

function label(): string {
  const p = profile.value
  return p ? `${p.name}（${p.code}）` : code.value
}

async function toggle(): Promise<void> {
  busy.value = true
  try {
    const now = await toggleWatch(code.value)
    ElMessage.success(now ? '已加入自选，异动时会在右上角提醒' : '已移出自选')
  } catch (e) {
    ElMessage.error(message(e))
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="stock-page">
    <div class="page">
      <p v-if="profileError" class="error">{{ profileError }}</p>

      <header v-if="profile" class="head card">
        <div class="ident">
          <h1>
            {{ profile.name }}<span class="code">{{ profile.code }}</span>
            <span v-if="profile.industry" class="tag">{{ profile.industry }}</span>
          </h1>
          <div class="price-row" :class="trend(profile.change ?? 0)">
            <span class="price">{{ num(profile.price) }}</span>
            <span>{{ signed(profile.change ?? 0) }}</span>
            <span>{{ signed(profile.percent ?? 0) }}%</span>
          </div>
          <div class="as-of">
            行情时间 {{ profile.as_of }} · 来源
            <a :href="profile.source.url" target="_blank" rel="noopener noreferrer">{{ profile.source.name }}</a>
          </div>
        </div>
        <div class="actions">
          <el-button :icon="watching ? StarFilled : Star" :loading="busy" :class="{ watching }" @click="toggle">
            {{ watching ? '已自选' : '加自选' }}
          </el-button>
          <el-button :icon="ChatLineSquare" @click="ask(`分析一下${label()}今天的表现和原因`)">
            AI 分析今日走势
          </el-button>
          <el-button type="primary" :icon="MagicStick" @click="ask(`诊断一下${label()}`)">AI 诊股</el-button>
        </div>
      </header>
      <p v-else-if="!profileError" class="loading">正在加载行情…</p>

      <dl v-if="profile" class="stats card">
        <div v-for="s in stats" :key="s.label">
          <dt>{{ s.label }}</dt>
          <dd :class="s.cls">{{ s.value }}</dd>
        </div>
      </dl>

      <div class="grid">
        <section class="card chart-card">
          <div class="tabs" role="tablist">
            <button
              type="button"
              role="tab"
              :aria-selected="chartTab === 'minute'"
              :class="{ active: chartTab === 'minute' }"
              @click="chartTab = 'minute'"
            >
              分时{{ profile?.date ? ` · ${profile.date}` : '' }}
            </button>
            <button
              type="button"
              role="tab"
              :aria-selected="chartTab === 'day'"
              :class="{ active: chartTab === 'day' }"
              :disabled="!kline"
              @click="chartTab = 'day'"
            >
              日 K{{ profile && !kline ? '（暂无）' : '' }}
            </button>
          </div>
          <template v-if="profile">
            <IntradayChart
              v-if="chartTab === 'minute' && profile.minutes.length && profile.prev_close"
              :key="`m-${profile.code}`"
              :minutes="profile.minutes"
              :prev-close="profile.prev_close"
              price-label="价格"
            />
            <p v-else-if="chartTab === 'minute'" class="placeholder">今天还没有分时数据</p>
            <KlineChart v-else-if="kline" :key="`k-${profile.code}`" :block="kline" />
          </template>
        </section>

        <section class="card news-card">
          <div class="tabs" role="tablist">
            <button
              type="button"
              role="tab"
              :aria-selected="newsTab === 'announcements'"
              :class="{ active: newsTab === 'announcements' }"
              @click="newsTab = 'announcements'"
            >
              公告
            </button>
            <button
              type="button"
              role="tab"
              :aria-selected="newsTab === 'news'"
              :class="{ active: newsTab === 'news' }"
              @click="newsTab = 'news'"
            >
              新闻
            </button>
          </div>
          <p v-if="newsLoading" class="placeholder">正在加载…</p>
          <template v-else-if="newsTab === 'announcements'">
            <p v-if="newsErrors.includes('公告')" class="placeholder">公告暂时取不到</p>
            <p v-else-if="!announcements.length" class="placeholder">暂无公告</p>
            <ul v-else class="list">
              <li v-for="a in announcements" :key="a.id">
                <a :href="a.url" target="_blank" rel="noopener noreferrer">{{ a.title }}</a>
                <span class="meta">{{ a.date }}<template v-if="a.type"> · {{ a.type }}</template></span>
              </li>
            </ul>
            <p class="src">来源：东方财富 · 点击标题查看公告原文</p>
          </template>
          <template v-else>
            <p v-if="newsErrors.includes('新闻')" class="placeholder">新闻暂时取不到</p>
            <p v-else-if="!news.length" class="placeholder">暂无新闻</p>
            <ul v-else class="list">
              <li v-for="n in news" :key="n.url">
                <a :href="n.url" target="_blank" rel="noopener noreferrer">{{ n.title }}</a>
                <span class="meta">{{ n.time }}{{ n.source.replace('，', ' · ') }}</span>
              </li>
            </ul>
            <p class="src">来源：东方财富</p>
          </template>
        </section>
      </div>

      <section class="card">
        <h2>
          诊股评分
          <el-button v-if="diagnosis" link type="primary" :icon="MagicStick" @click="ask(`诊断一下${label()}`)">
            让 AI 解读评分
          </el-button>
        </h2>
        <DiagnosisCard v-if="diagnosis" :block="diagnosis" hide-head class="flat" />
        <p v-else-if="diagnosisError" class="placeholder">{{ diagnosisError }}</p>
        <p v-else class="placeholder">正在计算…</p>
      </section>

      <section class="card">
        <DataTable v-if="financials" :block="financials" class="flat" />
        <p v-else-if="financialsError" class="placeholder">{{ financialsError }}</p>
        <p v-else class="placeholder">正在加载财务指标…</p>
      </section>
    </div>
  </div>
</template>

<style scoped>
.stock-page {
  overflow-y: auto;
}
.page {
  max-width: 1280px;
  margin: 0 auto;
  padding: 18px 24px 40px;
  font-variant-numeric: tabular-nums;
}
.card {
  margin-bottom: 14px;
  padding: 16px 18px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
}
.card h2 {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 0 0 6px;
  font-size: 16px;
}
.flat {
  margin: 0;
  padding: 0;
  border: 0;
}
.head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}
h1 {
  margin: 0;
  color: var(--navy);
  font-size: 22px;
  line-height: 1.3;
}
.code {
  margin-left: 8px;
  color: var(--text-muted);
  font-size: 14px;
  font-weight: 400;
}
.tag {
  margin-left: 10px;
  padding: 2px 8px;
  border-radius: 4px;
  background: var(--brand-soft);
  color: var(--brand);
  font-size: 12px;
  font-weight: 400;
  vertical-align: middle;
}
.price-row {
  display: flex;
  align-items: baseline;
  gap: 12px;
  font-size: 17px;
  font-weight: 600;
}
.price {
  font-size: 34px;
  font-weight: 700;
}
.as-of {
  color: var(--text-muted);
  font-size: 12px;
}
.as-of a {
  color: inherit;
}
.actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}
.actions .el-button + .el-button {
  margin-left: 0;
}
.watching {
  color: var(--gold);
}
.stats {
  display: grid;
  grid-template-columns: repeat(8, 1fr);
  gap: 10px 8px;
  margin-top: 0;
}
.stats div {
  min-width: 0;
}
.stats dt {
  color: var(--text-muted);
  font-size: 12px;
}
.stats dd {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  white-space: nowrap;
}
@media (max-width: 1100px) {
  .stats {
    grid-template-columns: repeat(4, 1fr);
  }
}
.up {
  color: var(--up);
}
.down {
  color: var(--down);
}
.grid {
  display: grid;
  grid-template-columns: minmax(0, 3fr) minmax(0, 2fr);
  gap: 14px;
}
@media (max-width: 1000px) {
  .grid {
    grid-template-columns: 1fr;
  }
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
.news-card {
  display: flex;
  flex-direction: column;
}
.list {
  flex: 1;
  max-height: 380px;
  margin: 0;
  padding: 0;
  overflow-y: auto;
  list-style: none;
}
.list li {
  display: flex;
  flex-direction: column;
  padding: 7px 0;
  border-bottom: 1px solid var(--line);
  font-size: 14px;
  line-height: 1.5;
}
.list a {
  color: var(--text);
  text-decoration: none;
}
.list a:hover {
  color: var(--brand);
  text-decoration: underline;
}
.meta,
.src {
  color: var(--text-muted);
  font-size: 12px;
}
.src {
  margin: 8px 0 0;
}
.placeholder,
.loading,
.error {
  padding: 24px 0;
  color: var(--text-muted);
  text-align: center;
}
.error {
  color: var(--danger);
}
</style>
