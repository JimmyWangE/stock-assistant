<script setup lang="ts">
import type { DiagnosisBlock } from '../api'
import { signed, trend } from '../market'

defineProps<{ block: DiagnosisBlock; hideHead?: boolean }>()

/** 分数条的宽度；没有数据时为 0。 */
function width(score: number | null): string {
  return `${score ?? 0}%`
}

function deltaText(delta: number): string {
  return delta > 0 ? `+${delta}` : delta < 0 ? `${delta}` : '参考'
}
</script>

<template>
  <figure class="diagnosis">
    <header v-if="!hideHead" class="head">
      <div>
        <router-link :to="`/stock/${block.code}`" class="name">{{ block.name }}</router-link>
        <span class="code">{{ block.code }}</span>
        <span v-if="block.industry" class="tag">{{ block.industry }}</span>
      </div>
      <div v-if="block.price != null && block.percent != null" class="price" :class="trend(block.percent)">
        {{ block.price.toFixed(2) }} <span>{{ signed(block.percent) }}%</span>
      </div>
    </header>

    <div class="overall">
      <div class="total">
        <b>{{ block.score ?? '—' }}</b>
        <span>综合评分 · {{ block.level }}</span>
      </div>
      <ul class="bars" aria-label="五项评分">
        <li v-for="d in block.dimensions" :key="d.name">
          <span class="dim">{{ d.name }}</span>
          <span class="track" :title="`50 分为中性`">
            <i class="fill" :style="{ width: width(d.score) }" />
            <i class="mid" />
          </span>
          <span class="score">{{ d.score ?? '—' }}</span>
          <span class="level">{{ d.level }}</span>
        </li>
      </ul>
    </div>

    <div class="details">
      <section v-for="d in block.dimensions" :key="d.name" class="dim-block">
        <h4>{{ d.name }}<span>{{ d.score ?? '暂无数据' }}</span></h4>
        <ul>
          <li v-for="(item, i) in d.items" :key="i">
            <span class="delta" :class="trend(item.delta)">{{ deltaText(item.delta) }}</span>
            <span>{{ item.text }}</span>
          </li>
        </ul>
        <p v-if="d.note" class="note">{{ d.note }}</p>
      </section>
    </div>

    <figcaption class="foot">
      行情时间 {{ block.as_of }} · 50 分为中性，满分 100 · {{ block.disclaimer }}
    </figcaption>
  </figure>
</template>

<style scoped>
.diagnosis {
  margin: 0 0 16px;
  padding: 14px 16px 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
}
.head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}
.name {
  color: var(--text);
  font-size: 16px;
  font-weight: 600;
  text-decoration: none;
}
.name:hover {
  color: var(--brand);
  text-decoration: underline;
}
.code {
  margin-left: 6px;
  color: var(--text-muted);
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}
.tag {
  margin-left: 8px;
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--brand-soft);
  color: var(--brand);
  font-size: 12px;
}
.price {
  font-size: 16px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.price span {
  margin-left: 4px;
  font-size: 13px;
}
.overall {
  display: flex;
  gap: 20px;
  align-items: center;
  padding: 10px 0 14px;
  border-bottom: 1px solid var(--line);
}
.total {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  width: 108px;
  height: 108px;
  flex-shrink: 0;
  border: 6px solid var(--brand-soft);
  border-radius: 50%;
}
.total b {
  color: var(--brand);
  font-size: 34px;
  line-height: 1.1;
  font-variant-numeric: tabular-nums;
}
.total span {
  color: var(--text-muted);
  font-size: 12px;
}
.bars {
  flex: 1;
  min-width: 0;
  margin: 0;
  padding: 0;
  list-style: none;
}
.bars li {
  display: grid;
  grid-template-columns: 52px 1fr 30px 56px;
  align-items: center;
  gap: 10px;
  font-size: 13px;
  line-height: 26px;
}
.dim {
  color: var(--text-muted);
}
.track {
  position: relative;
  height: 8px;
  border-radius: 4px;
  background: var(--surface-alt);
}
.fill {
  position: absolute;
  inset: 0 auto 0 0;
  border-radius: 4px;
  background: var(--brand);
}
.mid {
  position: absolute;
  top: -3px;
  bottom: -3px;
  left: 50%;
  width: 2px;
  background: var(--line-strong);
}
.score {
  text-align: right;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.level {
  color: var(--text-muted);
}
.details {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 4px 20px;
  padding-top: 8px;
}
.dim-block h4 {
  display: flex;
  justify-content: space-between;
  margin: 8px 0 4px;
  font-size: 14px;
}
.dim-block h4 span {
  color: var(--brand);
  font-variant-numeric: tabular-nums;
}
.dim-block ul {
  margin: 0;
  padding: 0;
  list-style: none;
}
.dim-block li {
  display: flex;
  gap: 8px;
  font-size: 13px;
  line-height: 1.6;
  padding: 2px 0;
}
.delta {
  flex-shrink: 0;
  min-width: 34px;
  height: 20px;
  margin-top: 1px;
  border-radius: 4px;
  background: var(--surface-alt);
  color: var(--text-muted);
  font-size: 12px;
  line-height: 20px;
  text-align: center;
  font-variant-numeric: tabular-nums;
}
.delta.up {
  background: #fbeaea;
  color: var(--up);
}
.delta.down {
  background: #e6f4ee;
  color: var(--down);
}
.note {
  margin: 2px 0 0;
  color: var(--text-muted);
  font-size: 12px;
}
.foot {
  margin-top: 10px;
  color: var(--text-muted);
  font-size: 12px;
}
</style>
