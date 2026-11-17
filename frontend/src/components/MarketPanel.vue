<script setup lang="ts">
import { computed, ref } from 'vue'

import type { NewsRow } from '../api'
import { board, signed, trend } from '../market'
import Sparkline from './Sparkline.vue'

const emit = defineEmits<{ ask: [question: string] }>()

const tab = ref<'headlines' | 'policies'>('headlines')
const news = computed<NewsRow[]>(() => board.value?.[tab.value] ?? [])

/** 沪深两市成交额：上证指数与深证成指的成交额相加。 */
const turnover = computed(() => {
  const rows = board.value?.indices ?? []
  const sh = rows.find((r) => r.code === 'sh000001')
  const sz = rows.find((r) => r.code === 'sz399001')
  if (!sh || !sz) return ''
  const total = sh.amount_yi + sz.amount_yi
  return total >= 10000 ? `${(total / 10000).toFixed(2)} 万亿` : `${total.toFixed(0)} 亿`
})

const breadthShare = computed(() => {
  const b = board.value?.breadth
  if (!b) return null
  const total = b.up + b.down + b.flat || 1
  return { up: (b.up / total) * 100, flat: (b.flat / total) * 100, down: (b.down / total) * 100 }
})

function askAbout(item: NewsRow): void {
  const kind = tab.value === 'policies' ? `${item.source ?? ''}发布的政策` : '新闻'
  emit('ask', `解读这条${kind}对 A 股的影响：《${item.title}》`)
}
</script>

<template>
  <aside class="panel" aria-label="市场看板">
    <section v-if="board?.indices.length">
      <h2>
        大盘指数
        <span class="meta">{{ board.as_of.slice(5, 16) }}</span>
      </h2>
      <ul class="index-list">
        <li v-for="item in board.indices" :key="item.code" :class="trend(item.change)">
          <span class="index-name">{{ item.name }}</span>
          <Sparkline :points="board.sparks[item.code] ?? []" :base="item.prev_close" />
          <span class="index-price">{{ item.price.toFixed(2) }}</span>
          <span class="chip">{{ signed(item.percent) }}%</span>
        </li>
      </ul>
    </section>

    <section v-if="board?.breadth && breadthShare">
      <h2>
        市场情绪
        <span v-if="turnover" class="meta">两市成交 {{ turnover }}</span>
      </h2>
      <div class="breadth-nums">
        <span class="up">上涨 <b>{{ board.breadth.up }}</b></span>
        <span class="flat">平 {{ board.breadth.flat }}</span>
        <span class="down">下跌 <b>{{ board.breadth.down }}</b></span>
      </div>
      <!-- 涨跌家数比例条；具体数字在上面，不只靠颜色 -->
      <div class="breadth-bar" aria-hidden="true">
        <span class="seg up" :style="{ width: breadthShare.up + '%' }" />
        <span class="seg flat" :style="{ width: breadthShare.flat + '%' }" />
        <span class="seg down" :style="{ width: breadthShare.down + '%' }" />
      </div>
      <div class="limits">
        <span>涨停 <b class="up">{{ board.breadth.limit_up }}</b></span>
        <span>跌停 <b class="down">{{ board.breadth.limit_down }}</b></span>
      </div>
    </section>

    <section v-if="board?.sectors">
      <h2>行业板块</h2>
      <div class="sectors">
        <div>
          <div class="sector-head">领涨</div>
          <ul>
            <li v-for="s in board.sectors.top" :key="s.name" :title="`领涨股：${s.leader}`">
              <span class="sector-name">{{ s.name }}</span>
              <span :class="trend(s.percent)">{{ signed(s.percent) }}%</span>
            </li>
          </ul>
        </div>
        <div>
          <div class="sector-head">领跌</div>
          <ul>
            <li v-for="s in board.sectors.bottom" :key="s.name">
              <span class="sector-name">{{ s.name }}</span>
              <span :class="trend(s.percent)">{{ signed(s.percent) }}%</span>
            </li>
          </ul>
        </div>
      </div>
    </section>

    <section class="news">
      <h2 class="tabs" role="tablist">
        <button
          type="button"
          role="tab"
          :aria-selected="tab === 'headlines'"
          :class="{ active: tab === 'headlines' }"
          @click="tab = 'headlines'"
        >
          财经快讯
        </button>
        <button
          type="button"
          role="tab"
          :aria-selected="tab === 'policies'"
          :class="{ active: tab === 'policies' }"
          @click="tab = 'policies'"
        >
          官方政策
        </button>
      </h2>
      <p v-if="!news.length" class="empty">{{ board ? '暂无内容' : '正在加载…' }}</p>
      <ul class="news-list">
        <li v-for="item in news" :key="item.url">
          <div class="news-meta">
            <span>{{ item.time }}</span>
            <span v-if="item.source" class="source">{{ item.source }}</span>
            <button type="button" class="ask" @click="askAbout(item)">AI 解读</button>
          </div>
          <a :href="item.url" target="_blank" rel="noopener noreferrer">{{ item.title }}</a>
        </li>
      </ul>
    </section>
  </aside>
</template>

<style scoped>
.panel {
  width: 320px;
  flex-shrink: 0;
  padding: 4px 16px 16px;
  box-sizing: border-box;
  border-left: 1px solid var(--line);
  background: var(--surface);
  font-size: 13px;
  font-variant-numeric: tabular-nums;
  overflow-y: auto;
}
section {
  padding: 12px 0 14px;
  border-bottom: 1px solid var(--line);
}
section:last-child {
  border-bottom: none;
}
h2 {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin: 0 0 8px;
  padding-left: 8px;
  border-left: 3px solid var(--gold);
  color: var(--navy);
  font-size: 14px;
  font-weight: 600;
  line-height: 1.2;
}
.meta {
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 400;
}
ul {
  margin: 0;
  padding: 0;
  list-style: none;
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

.index-list li {
  display: grid;
  grid-template-columns: 62px 84px 1fr 64px;
  align-items: center;
  gap: 8px;
  height: 34px;
}
.index-name {
  color: var(--text);
}
.index-price {
  font-weight: 600;
  text-align: right;
}
.chip {
  padding: 1px 0;
  border-radius: 4px;
  color: #fff;
  font-size: 12px;
  font-weight: 600;
  text-align: center;
}
.up .chip {
  background: var(--up);
}
.down .chip {
  background: var(--down);
}
.flat .chip {
  background: var(--text-muted);
}

.breadth-nums {
  display: flex;
  justify-content: space-between;
}
.breadth-nums b {
  font-size: 15px;
}
.breadth-bar {
  display: flex;
  gap: 2px;
  height: 6px;
  margin: 6px 0 8px;
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
.limits {
  display: flex;
  gap: 20px;
  color: var(--text-muted);
}

.sectors {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0 20px;
}
.sector-head {
  margin-bottom: 2px;
  color: var(--text-muted);
  font-size: 12px;
}
.sectors li {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  line-height: 26px;
}
.sector-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tabs {
  justify-content: flex-start;
  gap: 16px;
  padding-left: 0;
  border-left: none;
  border-bottom: 1px solid var(--line);
}
.tabs button {
  margin-bottom: -1px;
  padding: 0 0 7px;
  border: 0;
  border-bottom: 2px solid transparent;
  background: none;
  color: var(--text-muted);
  font: inherit;
  font-weight: 600;
  cursor: pointer;
}
.tabs button.active {
  border-bottom-color: var(--gold);
  color: var(--navy);
}
.empty {
  margin: 8px 0;
  color: var(--text-muted);
}
.news-list li {
  padding: 8px 0;
  border-bottom: 1px dashed var(--line);
}
.news-list li:last-child {
  border-bottom: none;
}
.news-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--text-muted);
  font-size: 12px;
}
.source {
  padding: 0 6px;
  border-radius: 3px;
  background: var(--brand-soft);
  color: var(--brand);
}
.ask {
  margin-left: auto;
  padding: 0 6px;
  border: 1px solid var(--line);
  border-radius: 4px;
  background: var(--surface);
  color: var(--brand);
  font: inherit;
  font-size: 12px;
  line-height: 18px;
  cursor: pointer;
}
.ask:hover,
.ask:focus-visible {
  border-color: var(--brand);
  background: var(--brand-soft);
  outline: none;
}
.news-list a {
  display: -webkit-box;
  margin-top: 2px;
  color: var(--text);
  line-height: 1.5;
  text-decoration: none;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  line-clamp: 2;
}
.news-list a:hover {
  color: var(--brand);
}
</style>
