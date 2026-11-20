<script setup lang="ts">
import { MagicStick, Promotion } from '@element-plus/icons-vue'
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { reportApi, type NewsRow, type Report, type SectorRow, type StockRow } from '../api'
import DistributionChart from '../components/DistributionChart.vue'
import MarkdownView from '../components/MarkdownView.vue'
import Sparkline from '../components/Sparkline.vue'
import { board, openIndex, signed, todayLabel, trend, yi } from '../market'

const router = useRouter()
const question = ref('')

/** 带着问题进入智能投研，自动提问。 */
function ask(q: string): void {
  const text = q.trim()
  if (text) router.push({ name: 'new-chat', query: { q: text } })
}

const breadth = computed(() => board.value?.breadth ?? null)
const market = computed(() => board.value?.market ?? null)
const sectors = computed(() => board.value?.sectors ?? null)

const share = computed(() => {
  const b = breadth.value
  if (!b) return null
  const total = b.up + b.down + b.flat || 1
  return { up: (b.up / total) * 100, flat: (b.flat / total) * 100, down: (b.down / total) * 100 }
})

/** 一句话描述市场情绪，只基于上涨家数占比，规则写死、可核对。 */
const mood = computed(() => {
  const s = share.value
  if (!s) return ''
  if (s.up >= 70) return '普涨'
  if (s.up >= 55) return '偏强'
  if (s.up >= 45) return '分化'
  if (s.up >= 30) return '偏弱'
  return '普跌'
})

/** 行业资金流向：净流入前 6、净流出前 6。 */
const flows = computed(() => {
  const all = sectors.value?.all ?? []
  const sorted = [...all].sort((a, b) => b.inflow_yi - a.inflow_yi)
  const max = Math.max(...all.map((s) => Math.abs(s.inflow_yi)), 1)
  return { inflow: sorted.slice(0, 6), outflow: sorted.slice(-6).reverse(), max }
})

/**
 * 行业热力图的底色：涨红跌绿，中间是中性灰，涨跌幅越大颜色越深（±4% 封顶）。
 * 方块里同时写着涨跌幅数字，不只靠颜色。
 */
function heat(p: number): { background: string; color: string } {
  const t = Math.min(Math.abs(p) / 4, 1)
  const [r, g, b] = p >= 0 ? [216, 58, 58] : [18, 145, 90]
  const base = [238, 240, 243]
  const mix = base.map((c, i) => Math.round(c + ([r, g, b][i] - c) * t))
  return { background: `rgb(${mix.join(',')})`, color: t > 0.5 ? '#fff' : '#17202e' }
}

const heatmap = computed<SectorRow[]>(() => sectors.value?.all ?? [])

const ranks = computed(() => [
  { key: 'gainers', title: '涨幅榜', rows: market.value?.gainers ?? [] },
  { key: 'losers', title: '跌幅榜', rows: market.value?.losers ?? [] },
  { key: 'active', title: '成交额榜', rows: market.value?.active ?? [] },
])

function openStock(row: StockRow): void {
  router.push(`/stock/${row.code}`)
}

/** 最近一份 AI 报告（早报或收盘复盘），首页只展示第一部分（看点/要点）。 */
const report = ref<Report | null>(null)
onMounted(async () => {
  try {
    report.value = (await reportApi.latest()).report
  } catch {
    // 报告只是辅助信息
  }
})
const highlight = computed(() => {
  const sections = (report.value?.content ?? '').split(/\n(?=## )/)
  const first = sections.find((p) => p.startsWith('## ')) ?? sections[0] ?? ''
  const [heading, ...rest] = first.split('\n')
  return { title: heading.replace(/^##\s*/, ''), body: rest.join('\n').trim() }
})

function askNews(item: NewsRow, kind: 'news' | 'policy'): void {
  ask(
    kind === 'policy'
      ? `解读这条${item.source ?? ''}发布的政策对 A 股的影响：《${item.title}》`
      : `解读这条新闻对 A 股的影响：《${item.title}》`,
  )
}

function review(): void {
  ask('结合今天的大盘指数、涨跌家数、行业板块与资金流向，以及重要新闻和政策，做一份今日 A 股市场复盘')
}
</script>

<template>
  <div class="dashboard">
    <div class="page">
      <!-- 页头：日期、交易状态、AI 复盘、快速提问 -->
      <header class="page-head">
        <div>
          <h1>市场概览</h1>
          <p class="sub">
            {{ todayLabel() }}
            <template v-if="board?.as_of">
              <span class="sep">·</span>{{ board.session }}
              <span class="sep">·</span>行情时间 {{ board.as_of.slice(11) }}
            </template>
          </p>
        </div>
        <div class="head-actions">
          <form class="quick-ask" @submit.prevent="ask(question)">
            <input
              v-model="question"
              maxlength="4000"
              placeholder="输入股票名称、代码或问题，直接向 AI 提问"
              aria-label="向 AI 提问"
            />
            <button type="submit" :disabled="!question.trim()" aria-label="提问">
              <el-icon><Promotion /></el-icon>
            </button>
          </form>
          <el-button type="primary" :icon="MagicStick" @click="review">AI 今日复盘</el-button>
        </div>
      </header>

      <p v-if="!board" class="loading">正在加载市场数据…</p>

      <!-- 指数卡片：点击打开分时与日 K -->
      <section v-if="board?.indices.length" class="indices">
        <button
          v-for="item in board.indices"
          :key="item.code"
          type="button"
          class="index-card"
          :class="trend(item.change)"
          @click="openIndex(item.code)"
        >
          <span class="ic-name">{{ item.name }}</span>
          <span class="ic-price">{{ item.price.toFixed(2) }}</span>
          <span class="ic-change">{{ signed(item.change) }} {{ signed(item.percent) }}%</span>
          <Sparkline
            class="ic-spark"
            :points="board.sparks[item.code] ?? []"
            :base="item.prev_close"
            :width="150"
            :height="36"
          />
          <span class="ic-amount">成交 {{ yi(item.amount_yi) }}</span>
        </button>
      </section>

      <!-- 最近一份 AI 报告 -->
      <section v-if="report" class="card report-card">
        <h2>
          <span>
            <span class="kind" :class="report.kind">{{ report.kind === 'morning' ? '早报' : '复盘' }}</span>
            {{ report.title }} · {{ highlight.title }}
          </span>
          <router-link :to="`/reports/${report.date}/${report.kind}`" class="more">阅读全文 ›</router-link>
        </h2>
        <!-- 只展示第一部分；模型没按结构输出时内容可能很长，限高并渐隐 -->
        <MarkdownView :content="highlight.body" class="report-body" />
      </section>

      <div class="grid-3">
        <!-- 市场情绪 -->
        <section v-if="breadth && share" class="card">
          <h2>
            市场情绪<span class="mood" :class="share.up >= 50 ? 'up' : 'down'">{{ mood }}</span>
            <span class="meta">{{ breadth.as_of.slice(11) }}</span>
          </h2>
          <div class="big-nums">
            <div class="up"><b>{{ breadth.up }}</b><span>上涨</span></div>
            <div class="flat"><b>{{ breadth.flat }}</b><span>平盘</span></div>
            <div class="down"><b>{{ breadth.down }}</b><span>下跌</span></div>
          </div>
          <div class="ratio-bar" aria-hidden="true">
            <span class="seg up" :style="{ width: share.up + '%' }" />
            <span class="seg flat" :style="{ width: share.flat + '%' }" />
            <span class="seg down" :style="{ width: share.down + '%' }" />
          </div>
          <dl class="kv">
            <div><dt>涨停</dt><dd class="up">{{ breadth.limit_up }}</dd></div>
            <div><dt>跌停</dt><dd class="down">{{ breadth.limit_down }}</dd></div>
            <div v-if="market"><dt>三市成交额</dt><dd>{{ yi(market.turnover_yi) }}</dd></div>
            <div v-if="market"><dt>统计股票</dt><dd>{{ market.count }} 只</dd></div>
          </dl>
          <p class="foot">含沪深京三市；停牌及无成交股票不计入</p>
        </section>

        <!-- 涨跌分布 -->
        <section v-if="market" class="card">
          <h2>涨跌分布<span class="meta">只数</span></h2>
          <DistributionChart :data="market.distribution" />
        </section>

        <!-- 行业资金流向 -->
        <section v-if="sectors" class="card">
          <h2>行业资金流向<span class="meta">净流入，亿元</span></h2>
          <div class="flows">
            <ul>
              <li v-for="s in flows.inflow" :key="s.name">
                <span class="flow-name">{{ s.name }}</span>
                <span class="flow-bar"><i class="up-bg" :style="{ width: (Math.abs(s.inflow_yi) / flows.max) * 100 + '%' }" /></span>
                <span class="flow-num up">{{ signed(s.inflow_yi) }}</span>
              </li>
            </ul>
            <ul>
              <li v-for="s in flows.outflow" :key="s.name">
                <span class="flow-name">{{ s.name }}</span>
                <span class="flow-bar"><i class="down-bg" :style="{ width: (Math.abs(s.inflow_yi) / flows.max) * 100 + '%' }" /></span>
                <span class="flow-num down">{{ signed(s.inflow_yi) }}</span>
              </li>
            </ul>
          </div>
        </section>
      </div>

      <!-- 行业热力图 -->
      <section v-if="heatmap.length" class="card">
        <h2>
          行业热力图<span class="meta">同花顺行业 {{ heatmap.length }} 个 · 按涨跌幅排列 · 点击可让 AI 分析</span>
        </h2>
        <div class="heatmap">
          <button
            v-for="s in heatmap"
            :key="s.name"
            type="button"
            class="tile"
            :style="heat(s.percent)"
            :title="`${s.name} ${signed(s.percent)}%｜上涨 ${s.up} 家 / 下跌 ${s.down} 家｜领涨 ${s.leader} ${signed(s.leader_percent)}%｜净流入 ${signed(s.inflow_yi)} 亿`"
            @click="ask(`分析一下今天${s.name}板块的表现和原因`)"
          >
            <span class="tile-name">{{ s.name }}</span>
            <span class="tile-pct">{{ signed(s.percent) }}%</span>
          </button>
        </div>
      </section>

      <!-- 个股排行 -->
      <div v-if="market" class="grid-3">
        <section v-for="r in ranks" :key="r.key" class="card">
          <h2>{{ r.title }}<span class="meta">点击查看个股详情</span></h2>
          <table class="rank">
            <thead>
              <tr><th>名称</th><th>最新价</th><th>涨跌幅</th><th>成交额</th></tr>
            </thead>
            <tbody>
              <tr v-for="row in r.rows" :key="row.code" tabindex="0" @click="openStock(row)" @keydown.enter="openStock(row)">
                <td><span class="stock-name">{{ row.name }}</span><span class="stock-code">{{ row.code }}</span></td>
                <td>{{ row.price.toFixed(2) }}</td>
                <td :class="trend(row.percent)">{{ signed(row.percent) }}%</td>
                <td>{{ row.amount_yi.toFixed(2) }} 亿</td>
              </tr>
            </tbody>
          </table>
        </section>
      </div>

      <!-- 新闻与政策 -->
      <div class="grid-2">
        <section class="card">
          <h2>财经快讯<span class="meta">东方财富</span></h2>
          <ul class="news">
            <li v-for="n in board?.headlines ?? []" :key="n.url">
              <span class="news-time">{{ n.time.slice(6) }}</span>
              <a :href="n.url" target="_blank" rel="noopener noreferrer">{{ n.title }}</a>
              <button type="button" class="ai" @click="askNews(n, 'news')">AI 解读</button>
            </li>
          </ul>
        </section>
        <section class="card">
          <h2>官方政策<span class="meta">国务院 · 证监会 · 人民银行 · 财政部 · 发改委</span></h2>
          <ul class="news">
            <li v-for="n in board?.policies ?? []" :key="n.url">
              <span class="news-time">{{ n.time }}</span>
              <span class="tag">{{ n.source }}</span>
              <a :href="n.url" target="_blank" rel="noopener noreferrer">{{ n.title }}</a>
              <button type="button" class="ai" @click="askNews(n, 'policy')">AI 解读</button>
            </li>
          </ul>
        </section>
      </div>

      <p class="disclaimer">
        数据来源：腾讯财经（指数、个股行情与全市场统计）、同花顺（行业板块）、东方财富（快讯）、各部委官网（政策）。内容仅供内部研究参考，不构成投资建议。
      </p>
    </div>
  </div>
</template>

<style scoped>
.dashboard {
  overflow-y: auto;
  font-variant-numeric: tabular-nums;
}
.page {
  max-width: 1480px;
  margin: 0 auto;
  padding: 18px 24px 24px;
}
.report-card h2 {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.report-card .kind {
  margin-right: 6px;
  padding: 0 6px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 400;
  line-height: 20px;
}
.report-card .kind.morning {
  background: #fdf3e1;
  color: #9a6b14;
}
.report-card .kind.close {
  background: var(--brand-soft);
  color: var(--brand);
}
.report-card .more {
  color: var(--brand);
  font-size: 13px;
  font-weight: 400;
  text-decoration: none;
}
.report-body {
  max-height: 220px;
  overflow: hidden;
  font-size: 14px;
  mask-image: linear-gradient(to bottom, #000 170px, transparent 220px);
}
.page-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 20px;
  margin-bottom: 16px;
}
h1 {
  margin: 0;
  color: var(--navy);
  font-size: 22px;
  line-height: 1.3;
}
.sub {
  margin: 2px 0 0;
  color: var(--text-muted);
  font-size: 13px;
}
.sep {
  margin: 0 8px;
}
.head-actions {
  display: flex;
  gap: 10px;
}
.quick-ask {
  display: flex;
  align-items: center;
  width: 380px;
  height: 32px;
  border: 1px solid var(--line-strong);
  border-radius: 6px;
  background: var(--surface);
}
.quick-ask:focus-within {
  border-color: var(--brand);
}
.quick-ask input {
  flex: 1;
  min-width: 0;
  padding: 0 12px;
  border: 0;
  background: none;
  color: var(--text);
  font: inherit;
  font-size: 13px;
  outline: none;
}
.quick-ask button {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 30px;
  border: 0;
  background: none;
  color: var(--brand);
  cursor: pointer;
}
.quick-ask button:disabled {
  color: var(--line-strong);
  cursor: default;
}
.loading {
  color: var(--text-muted);
}

/* 9 个指数一行排开；窗口窄时分两行（5 + 4），不留单独一个在第二行 */
.indices {
  display: grid;
  grid-template-columns: repeat(9, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 14px;
}
@media (max-width: 1360px) {
  .indices {
    grid-template-columns: repeat(5, minmax(0, 1fr));
  }
}
.index-card {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 1px;
  padding: 10px 12px 8px;
  border: 1px solid var(--line);
  border-top: 3px solid var(--line-strong);
  border-radius: 6px;
  background: var(--surface);
  color: var(--text);
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: box-shadow 0.15s;
}
.index-card:hover,
.index-card:focus-visible {
  box-shadow: 0 4px 14px rgba(11, 29, 51, 0.1);
  outline: none;
}
.index-card.up {
  border-top-color: var(--up);
  color: var(--up);
}
.index-card.down {
  border-top-color: var(--down);
  color: var(--down);
}
.ic-name {
  color: var(--text);
  font-size: 13px;
}
.ic-price {
  font-size: 20px;
  font-weight: 700;
  line-height: 1.3;
}
.ic-change {
  font-size: 12px;
  font-weight: 600;
}
.ic-spark {
  width: 100%;
  height: 36px;
  margin: 4px 0 2px;
}
.ic-amount {
  color: var(--text-muted);
  font-size: 12px;
}

.grid-3 {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
  margin-bottom: 14px;
}
.grid-2 {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
  margin-bottom: 14px;
}
@media (max-width: 1100px) {
  .grid-3 {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
.card {
  min-width: 0;
  padding: 12px 16px 14px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
}
.grid-3 > .card,
.grid-2 > .card {
  margin: 0;
}
section.card:not(.grid-3 > .card):not(.grid-2 > .card) {
  margin-bottom: 14px;
}
h2 {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin: 0 0 10px;
  padding-left: 8px;
  border-left: 3px solid var(--gold);
  color: var(--navy);
  font-size: 15px;
  font-weight: 600;
  line-height: 1.2;
}
.meta {
  margin-left: auto;
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 400;
}
.up {
  color: var(--up);
}
.down {
  color: var(--down);
}
.flat {
  color: var(--text-muted);
}
.mood {
  padding: 1px 8px;
  border-radius: 3px;
  color: #fff;
  font-size: 12px;
}
.mood.up {
  background: var(--up);
}
.mood.down {
  background: var(--down);
}

.big-nums {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  text-align: center;
}
.big-nums b {
  display: block;
  font-size: 26px;
  line-height: 1.2;
}
.big-nums span {
  color: var(--text-muted);
  font-size: 12px;
}
.ratio-bar {
  display: flex;
  gap: 2px;
  height: 8px;
  margin: 10px 0 12px;
}
.seg {
  min-width: 2px;
  border-radius: 2px;
}
.seg.up {
  background: var(--up);
}
.seg.flat {
  background: var(--line-strong);
}
.seg.down {
  background: var(--down);
}
.kv {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px 20px;
  margin: 0;
  font-size: 13px;
}
.kv div {
  display: flex;
  justify-content: space-between;
}
.kv dt {
  color: var(--text-muted);
}
.kv dd {
  margin: 0;
  font-weight: 600;
}
.foot {
  margin: 10px 0 0;
  color: var(--text-muted);
  font-size: 12px;
}

.flows {
  display: grid;
  grid-template-columns: 1fr;
  gap: 8px;
}
.flows ul {
  margin: 0;
  padding: 0;
  list-style: none;
}
.flows li {
  display: grid;
  grid-template-columns: 76px 1fr 56px;
  align-items: center;
  gap: 8px;
  height: 20px;
  font-size: 12px;
}
.flow-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.flow-bar {
  height: 8px;
  border-radius: 2px;
  background: var(--surface-alt);
}
.flow-bar i {
  display: block;
  height: 100%;
  border-radius: 2px;
}
.up-bg {
  background: var(--up);
}
.down-bg {
  background: var(--down);
}
.flow-num {
  font-weight: 600;
  text-align: right;
}

.heatmap {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(96px, 1fr));
  gap: 2px;
}
.tile {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 46px;
  padding: 0 4px;
  border: 0;
  border-radius: 3px;
  font: inherit;
  cursor: pointer;
}
.tile:hover,
.tile:focus-visible {
  outline: 2px solid var(--navy);
  outline-offset: -2px;
}
.tile-name {
  max-width: 100%;
  overflow: hidden;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tile-pct {
  font-size: 12px;
  font-weight: 700;
}

.rank {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.rank th {
  padding: 4px 6px;
  border-top: 2px solid var(--navy);
  border-bottom: 1px solid var(--navy);
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 500;
  text-align: right;
}
.rank td {
  padding: 5px 6px;
  border-bottom: 1px solid var(--line);
  text-align: right;
  white-space: nowrap;
}
.rank th:first-child,
.rank td:first-child {
  text-align: left;
}
.rank tbody tr {
  cursor: pointer;
}
.rank tbody tr:hover,
.rank tbody tr:focus-visible {
  background: var(--brand-soft);
  outline: none;
}
.stock-name {
  font-weight: 500;
}
.stock-code {
  margin-left: 6px;
  color: var(--text-muted);
  font-size: 11px;
}

.news {
  margin: 0;
  padding: 0;
  list-style: none;
  font-size: 13px;
}
.news li {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 30px;
  border-bottom: 1px dashed var(--line);
}
.news li:last-child {
  border-bottom: none;
}
.news-time {
  flex-shrink: 0;
  width: 42px;
  color: var(--text-muted);
  font-size: 12px;
}
.tag {
  flex-shrink: 0;
  padding: 0 6px;
  border-radius: 3px;
  background: var(--brand-soft);
  color: var(--brand);
  font-size: 12px;
}
.news a {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  color: var(--text);
  text-decoration: none;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.news a:hover {
  color: var(--brand);
}
.ai {
  flex-shrink: 0;
  padding: 0 6px;
  border: 1px solid var(--line);
  border-radius: 4px;
  background: var(--surface);
  color: var(--brand);
  font: inherit;
  font-size: 12px;
  line-height: 18px;
  cursor: pointer;
  opacity: 0;
}
.news li:hover .ai,
.ai:focus-visible {
  opacity: 1;
}
.disclaimer {
  margin: 4px 0 0;
  color: var(--text-muted);
  font-size: 12px;
  text-align: center;
}
</style>
