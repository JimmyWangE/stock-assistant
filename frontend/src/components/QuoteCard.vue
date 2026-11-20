<script setup lang="ts">
import { computed } from 'vue'

import type { QuoteBlock } from '../api'
import { signed, trend } from '../market'

const props = defineProps<{ block: QuoteBlock }>()

const change = computed(() => props.block.price - props.block.prev_close)
const percent = computed(() =>
  props.block.prev_close ? (change.value / props.block.prev_close) * 100 : 0,
)

/** 相对昨收的涨跌方向，用来给开盘、最高、最低上色。 */
function side(value: number): string {
  return trend(value - props.block.prev_close)
}

const volume = computed(() => {
  const lots = props.block.volume_lots
  return lots >= 10000 ? `${(lots / 10000).toFixed(2)} 万手` : `${lots.toFixed(0)} 手`
})
</script>

<template>
  <figure class="quote">
    <div class="head">
      <div>
        <router-link :to="`/stock/${block.code}`" class="name">{{ block.name }}</router-link>
        <span class="code">{{ block.code }}</span>
      </div>
      <span class="as-of">{{ block.as_of }}</span>
    </div>
    <div class="body">
      <div class="main" :class="trend(change)">
        <span class="price">{{ block.price.toFixed(2) }}</span>
        <span class="delta">{{ signed(change) }}</span>
        <span class="delta">{{ signed(percent) }}%</span>
      </div>
      <dl class="stats">
        <div>
          <dt>今开</dt>
          <dd :class="side(block.open)">{{ block.open.toFixed(2) }}</dd>
        </div>
        <div>
          <dt>最高</dt>
          <dd :class="side(block.high)">{{ block.high.toFixed(2) }}</dd>
        </div>
        <div>
          <dt>成交量</dt>
          <dd>{{ volume }}</dd>
        </div>
        <div>
          <dt>昨收</dt>
          <dd>{{ block.prev_close.toFixed(2) }}</dd>
        </div>
        <div>
          <dt>最低</dt>
          <dd :class="side(block.low)">{{ block.low.toFixed(2) }}</dd>
        </div>
        <div>
          <dt>成交额</dt>
          <dd>{{ block.amount_yi.toFixed(2) }} 亿</dd>
        </div>
      </dl>
    </div>
    <p class="note">
      来源：<a :href="block.source.url" target="_blank" rel="noopener noreferrer">{{
        block.source.name
      }}</a>
    </p>
  </figure>
</template>

<style scoped>
.quote {
  margin: 0 0 16px;
  padding: 14px 16px 10px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
  font-variant-numeric: tabular-nums;
}
.head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
}
.name {
  color: var(--navy);
  font-size: 16px;
  font-weight: 600;
  text-decoration: none;
}
.name:hover {
  color: var(--brand);
  text-decoration: underline;
}
.code {
  margin-left: 8px;
  color: var(--text-muted);
  font-size: 13px;
}
.as-of {
  color: var(--text-muted);
  font-size: 12px;
}
.body {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px 36px;
  margin-top: 6px;
}
.main {
  display: flex;
  align-items: baseline;
  gap: 10px;
}
.price {
  font-size: 34px;
  font-weight: 700;
  line-height: 1.2;
}
.delta {
  font-size: 15px;
  font-weight: 600;
}
.stats {
  display: grid;
  flex: 1;
  grid-template-columns: repeat(3, minmax(110px, 1fr));
  gap: 4px 24px;
  min-width: 360px;
  margin: 0;
  font-size: 13px;
}
.stats div {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}
.stats dt {
  color: var(--text-muted);
}
.stats dd {
  margin: 0;
  font-weight: 500;
}
.up {
  color: var(--up);
}
.down {
  color: var(--down);
}
.note {
  margin: 10px 0 0;
  color: var(--text-muted);
  font-size: 12px;
}
.note a {
  color: var(--brand);
}
</style>
