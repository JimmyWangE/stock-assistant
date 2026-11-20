<script setup lang="ts">
import { Delete, MagicStick, Plus } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { stockApi, watchApi, type AlertItem, type WatchItem } from '../api'
import { board, signed, trend } from '../market'
import { loadWatched } from '../watchlist'

const router = useRouter()
const items = ref<WatchItem[]>([])
const alerts = ref<AlertItem[]>([])
const loading = ref(true)
const error = ref('')
const adding = ref('')

async function load(): Promise<void> {
  try {
    items.value = await watchApi.list()
    error.value = ''
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}

async function loadAlerts(): Promise<void> {
  try {
    alerts.value = (await watchApi.alerts()).items.slice(0, 12)
  } catch {
    // 提醒列表只是辅助信息
  }
}

async function suggest(query: string, done: (items: { value: string; code: string }[]) => void): Promise<void> {
  if (!query.trim()) return done([])
  try {
    const rows = await stockApi.search(query.trim())
    done(rows.map((r) => ({ value: `${r.name} ${r.code}`, code: r.code })))
  } catch {
    done([])
  }
}

async function add(code: string): Promise<void> {
  if (!code.trim()) return
  try {
    const item = await watchApi.add(code.trim())
    adding.value = ''
    ElMessage.success(`已加入 ${item.name}`)
    await Promise.all([load(), loadWatched(true)])
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '添加失败')
  }
}

async function remove(item: WatchItem): Promise<void> {
  await watchApi.remove(item.code)
  items.value = items.value.filter((i) => i.code !== item.code)
  loadWatched(true)
}

async function setThreshold(item: WatchItem, value: number | undefined): Promise<void> {
  if (!value) return
  try {
    await watchApi.setThreshold(item.code, value)
    item.alert_pct = value
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '保存失败')
  }
}

const summary = computed(() => {
  const quoted = items.value.filter((i) => i.quote?.percent != null)
  return {
    up: quoted.filter((i) => (i.quote!.percent ?? 0) > 0).length,
    down: quoted.filter((i) => (i.quote!.percent ?? 0) < 0).length,
  }
})

function num(value: number | null | undefined, digits = 2): string {
  return value == null ? '—' : value.toFixed(digits)
}

let timer: ReturnType<typeof setInterval> | undefined
onMounted(() => {
  load()
  loadAlerts()
  // 交易时段每 10 秒刷新行情
  timer = setInterval(() => {
    if (document.hidden) return
    if (board.value?.session === '交易中') load()
    loadAlerts()
  }, 10000)
})
onBeforeUnmount(() => clearInterval(timer))
</script>

<template>
  <div class="watch-page">
    <div class="page">
      <header class="page-head">
        <div>
          <h1>自选股</h1>
          <p class="sub">
            共 {{ items.length }} 只<template v-if="items.length">
              <span class="sep">·</span><span class="up">上涨 {{ summary.up }}</span>
              <span class="sep">·</span><span class="down">下跌 {{ summary.down }}</span></template
            >
          </p>
        </div>
        <form class="add" @submit.prevent="add(adding)">
          <el-autocomplete
            v-model="adding"
            :fetch-suggestions="suggest"
            :trigger-on-focus="false"
            :debounce="200"
            placeholder="输入代码或名称添加"
            highlight-first-item
            @select="(o: Record<string, any>) => add(o.code)"
          />
          <el-button type="primary" :icon="Plus" native-type="submit" :disabled="!adding.trim()">添加</el-button>
        </form>
      </header>

      <div class="grid">
        <section class="card">
          <p v-if="error" class="placeholder error">{{ error }}</p>
          <el-table
            v-else
            v-loading="loading"
            :data="items"
            class="table"
            :default-sort="{ prop: 'quote.percent', order: 'descending' }"
            empty-text="还没有自选股。在上方输入代码或名称添加，或在个股详情页点「加自选」。"
            @row-click="(row: WatchItem, col: any) => col?.property !== 'alert_pct' && col?.label !== '操作' && router.push(`/stock/${row.code}`)"
          >
            <el-table-column label="股票" min-width="130">
              <template #default="{ row }">
                <router-link :to="`/stock/${row.code}`" class="name" @click.stop>{{ row.name }}</router-link>
                <span class="code">{{ row.code }}</span>
              </template>
            </el-table-column>
            <el-table-column label="最新价" prop="quote.price" align="right" sortable>
              <template #default="{ row }">
                <span :class="trend(row.quote?.change ?? 0)">{{ num(row.quote?.price) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="涨跌幅" prop="quote.percent" align="right" sortable>
              <template #default="{ row }">
                <span :class="trend(row.quote?.percent ?? 0)">{{
                  row.quote?.percent == null ? '—' : `${signed(row.quote.percent)}%`
                }}</span>
              </template>
            </el-table-column>
            <el-table-column label="成交额(亿)" prop="quote.amount_yi" align="right" sortable>
              <template #default="{ row }">{{ num(row.quote?.amount_yi) }}</template>
            </el-table-column>
            <el-table-column label="换手率" prop="quote.turnover" align="right" sortable>
              <template #default="{ row }">{{ row.quote?.turnover == null ? '—' : `${num(row.quote.turnover)}%` }}</template>
            </el-table-column>
            <el-table-column label="市盈率TTM" prop="quote.pe_ttm" align="right" sortable>
              <template #default="{ row }">{{
                row.quote?.pe_ttm != null && row.quote.pe_ttm < 0 ? '亏损' : num(row.quote?.pe_ttm)
              }}</template>
            </el-table-column>
            <el-table-column label="总市值(亿)" prop="quote.mktcap" align="right" sortable>
              <template #default="{ row }">{{ num(row.quote?.mktcap, 0) }}</template>
            </el-table-column>
            <el-table-column label="涨跌提醒" prop="alert_pct" align="center" width="130">
              <template #default="{ row }">
                <el-input-number
                  :model-value="row.alert_pct"
                  :min="1"
                  :max="20"
                  :step="0.5"
                  size="small"
                  controls-position="right"
                  aria-label="涨跌幅提醒阈值（%）"
                  class="threshold"
                  @click.stop
                  @change="(v: number | undefined) => setThreshold(row, v)"
                />
                <span class="pct">%</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" align="center" width="120">
              <template #default="{ row }">
                <el-tooltip content="AI 诊股" placement="top">
                  <el-button
                    link
                    type="primary"
                    :icon="MagicStick"
                    aria-label="AI 诊股"
                    @click.stop="router.push({ name: 'new-chat', query: { q: `诊断一下${row.name}（${row.code}）` } })"
                  />
                </el-tooltip>
                <el-tooltip content="移出自选" placement="top">
                  <el-button link :icon="Delete" aria-label="移出自选" @click.stop="remove(row)" />
                </el-tooltip>
              </template>
            </el-table-column>
          </el-table>
          <p class="foot">
            行情来源：腾讯财经{{ items[0]?.quote ? ` · 行情时间 ${items[0].quote.as_of}` : '' }} · 点击行查看个股详情
          </p>
        </section>

        <aside class="card side">
          <h2>最近提醒</h2>
          <p v-if="!alerts.length" class="placeholder small">暂无提醒</p>
          <ul v-else class="alerts">
            <li v-for="a in alerts" :key="a.id">
              <span class="kind">{{ a.kind }}</span>
              <a v-if="a.url?.startsWith('http')" :href="a.url" target="_blank" rel="noopener noreferrer">{{ a.message }}</a>
              <router-link v-else :to="a.url || `/stock/${a.code}`">{{ a.message }}</router-link>
            </li>
          </ul>
          <h3>提醒规则</h3>
          <ul class="rules">
            <li>涨跌幅达到该股的提醒阈值（默认 ±5%）</li>
            <li>触及涨停价或跌停价</li>
            <li>发布新公告（标注利好类、风险类）</li>
            <li>入选当天的火眼金睛名单（9:35 定格）</li>
          </ul>
          <p class="note">每类事件每只股票每天最多提醒一次；行情在交易时段每 30 秒检查一次，公告每 5 分钟检查一次。提醒保留 30 天。</p>
        </aside>
      </div>
    </div>
  </div>
</template>

<style scoped>
.watch-page {
  overflow-y: auto;
}
.page {
  max-width: 1280px;
  margin: 0 auto;
  padding: 18px 24px 40px;
  font-variant-numeric: tabular-nums;
}
.page-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}
h1 {
  margin: 0;
  color: var(--navy);
  font-size: 22px;
}
.sub {
  margin: 2px 0 0;
  color: var(--text-muted);
  font-size: 13px;
}
.sep {
  margin: 0 6px;
}
.add {
  display: flex;
  gap: 8px;
}
.add .el-autocomplete {
  width: 220px;
}
.grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 300px;
  gap: 14px;
  align-items: start;
}
@media (max-width: 1100px) {
  .grid {
    grid-template-columns: 1fr;
  }
}
.card {
  padding: 14px 16px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
}
.table :deep(.el-table__row) {
  cursor: pointer;
}
.name {
  color: var(--text);
  font-weight: 600;
  text-decoration: none;
}
.name:hover {
  color: var(--brand);
}
.code {
  margin-left: 6px;
  color: var(--text-muted);
  font-size: 12px;
}
.threshold {
  width: 84px;
}
.pct {
  margin-left: 4px;
  color: var(--text-muted);
}
.up {
  color: var(--up);
}
.down {
  color: var(--down);
}
.foot,
.note {
  margin: 10px 0 0;
  color: var(--text-muted);
  font-size: 12px;
}
.side h2 {
  margin: 0 0 8px;
  font-size: 15px;
}
.side h3 {
  margin: 16px 0 6px;
  font-size: 14px;
}
.alerts {
  max-height: 320px;
  margin: 0;
  padding: 0;
  overflow-y: auto;
  list-style: none;
}
.alerts li {
  display: flex;
  gap: 8px;
  padding: 6px 0;
  border-bottom: 1px solid var(--line);
  font-size: 13px;
  line-height: 1.5;
}
.alerts a {
  color: var(--text);
  text-decoration: none;
}
.alerts a:hover {
  color: var(--brand);
}
.kind {
  flex-shrink: 0;
  height: 20px;
  padding: 0 6px;
  border-radius: 4px;
  background: var(--brand-soft);
  color: var(--brand);
  font-size: 12px;
  line-height: 20px;
}
.rules {
  margin: 0;
  padding-left: 18px;
  font-size: 13px;
  line-height: 1.8;
}
.placeholder {
  padding: 24px 0;
  color: var(--text-muted);
  text-align: center;
}
.placeholder.small {
  padding: 8px 0;
  text-align: left;
  font-size: 13px;
}
.error {
  color: var(--danger);
}
</style>
