<script setup lang="ts">
import { BarChart, CandlestickChart } from 'echarts/charts'
import {
  AxisPointerComponent,
  DataZoomComponent,
  GridComponent,
  TooltipComponent,
} from 'echarts/components'
import { init, use, type ECharts } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { onBeforeUnmount, onMounted, ref } from 'vue'

import type { KlineBlock } from '../api'

use([
  CandlestickChart,
  BarChart,
  GridComponent,
  TooltipComponent,
  AxisPointerComponent,
  DataZoomComponent,
  CanvasRenderer,
])

const props = defineProps<{ block: KlineBlock }>()

// A 股惯例红涨绿跌。红绿对色觉障碍者不易区分，所以再加一层形状：上涨空心、下跌实心。
const UP = '#d83a3a'
const DOWN = '#12915a'
const SURFACE = '#ffffff'
const INK_MUTED = '#6b7385'
const GRID_LINE = '#e4e7ee'

const el = ref<HTMLElement>()
let chart: ECharts | null = null
let observer: ResizeObserver | null = null

/** 成交量原始单位是股，按 A 股习惯显示为手。 */
function formatVolume(shares: number): string {
  const lots = shares / 100
  if (lots >= 1e8) return `${(lots / 1e8).toFixed(2)} 亿手`
  if (lots >= 1e4) return `${(lots / 1e4).toFixed(2)} 万手`
  return `${Math.round(lots)} 手`
}

function render(): void {
  if (!el.value) return
  // 每根：[时间, 开, 收, 低, 高, 成交量]
  const bars = props.block.bars
  const times = bars.map((b) => b[0])
  const rising = (i: number) => bars[i][2] >= bars[i][1]

  chart = init(el.value)
  chart.setOption({
    animation: false,
    // 价格和成交量量纲不同，各用一个坐标区上下排列、共用时间轴，而不是挤进同一个双轴图
    grid: [
      { left: 56, right: 12, top: 10, height: '62%' },
      { left: 56, right: 12, top: '76%', height: '16%' },
    ],
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross', label: { show: false } },
      borderColor: GRID_LINE,
      textStyle: { color: '#1d2433', fontSize: 13 },
      formatter: (params: unknown) => {
        const i = (params as { dataIndex: number }[])[0].dataIndex
        const [time, open, close, low, high, volume] = bars[i]
        // 涨跌幅相对前一根收盘；第一根没有前一根，退而相对自身开盘
        const base = i > 0 ? bars[i - 1][2] : open
        const pct = ((close - base) / base) * 100
        const row = (k: string, v: string) =>
          `<div style="display:flex;justify-content:space-between;gap:20px"><span style="color:${INK_MUTED}">${k}</span><span style="font-variant-numeric:tabular-nums">${v}</span></div>`
        return (
          `<div style="font-weight:600;margin-bottom:2px">${time}</div>` +
          row('开盘', open.toFixed(2)) +
          row('收盘', close.toFixed(2)) +
          row('最高', high.toFixed(2)) +
          row('最低', low.toFixed(2)) +
          row('涨跌幅', `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`) +
          row('成交量', formatVolume(volume))
        )
      },
    },
    xAxis: [
      {
        type: 'category',
        data: times,
        gridIndex: 0,
        axisLine: { lineStyle: { color: GRID_LINE } },
        axisTick: { show: false },
        axisLabel: { show: false },
      },
      {
        type: 'category',
        data: times,
        gridIndex: 1,
        axisLine: { lineStyle: { color: GRID_LINE } },
        axisTick: { show: false },
        axisLabel: { color: INK_MUTED, fontSize: 11, hideOverlap: true },
      },
    ],
    yAxis: [
      {
        scale: true, // 股价不从 0 起，否则蜡烛会被压成一条线
        gridIndex: 0,
        splitNumber: 4,
        axisLabel: { color: INK_MUTED, fontSize: 11 },
        splitLine: { lineStyle: { color: GRID_LINE } },
      },
      {
        gridIndex: 1,
        splitNumber: 2,
        axisLabel: { show: false },
        splitLine: { show: false },
      },
    ],
    dataZoom: [{ type: 'inside', xAxisIndex: [0, 1] }],
    series: [
      {
        type: 'candlestick',
        data: bars.map(([, open, close, low, high]) => [open, close, low, high]),
        itemStyle: { color: SURFACE, borderColor: UP, color0: DOWN, borderColor0: DOWN },
      },
      {
        type: 'bar',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: bars.map((b, i) => ({
          value: b[5],
          itemStyle: rising(i)
            ? { color: SURFACE, borderColor: UP, borderWidth: 1 }
            : { color: DOWN },
        })),
      },
    ],
  })

  observer = new ResizeObserver(() => chart?.resize())
  observer.observe(el.value)
}

onMounted(render)
onBeforeUnmount(() => {
  observer?.disconnect()
  chart?.dispose()
})
</script>

<template>
  <figure class="kline">
    <figcaption class="title">{{ block.title }}</figcaption>
    <div
      ref="el"
      class="canvas"
      role="img"
      :aria-label="`${block.title}，共 ${block.bars.length} 根，截至 ${block.as_of}`"
    />
    <p class="note">
      <span class="key"><i class="swatch up" />涨（空心）</span>
      <span class="key"><i class="swatch down" />跌（实心）</span>
      <span>数据截至 {{ block.as_of }}</span>
      <span>
        来源：<a :href="block.source.url" target="_blank" rel="noopener noreferrer">{{
          block.source.name
        }}</a>
      </span>
    </p>
  </figure>
</template>

<style scoped>
.kline {
  margin: 0 0 16px;
  padding: 14px 16px 12px;
  border: 1px solid var(--line);
  border-radius: 10px;
}
.title {
  margin-bottom: 6px;
  font-weight: 600;
}
.canvas {
  width: 100%;
  height: 340px;
}
.note {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 16px;
  margin: 8px 0 0;
  color: var(--text-muted);
  font-size: 12px;
}
.note a {
  color: var(--brand);
}
.key {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}
.swatch {
  width: 8px;
  height: 12px;
  box-sizing: border-box;
}
.swatch.up {
  border: 1.5px solid #d83a3a;
}
.swatch.down {
  background: #12915a;
}
</style>
