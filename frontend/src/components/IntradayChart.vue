<script setup lang="ts">
import { BarChart, LineChart } from 'echarts/charts'
import {
  AxisPointerComponent,
  GridComponent,
  MarkLineComponent,
  TooltipComponent,
} from 'echarts/components'
import { init, use, type ECharts } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

use([
  LineChart,
  BarChart,
  GridComponent,
  TooltipComponent,
  AxisPointerComponent,
  MarkLineComponent,
  CanvasRenderer,
])

// 分时图：点位一条线，下方成交量柱。虚线是昨收。
// priceLabel：指数叫"点位"，个股叫"价格"
const props = defineProps<{ minutes: [string, number, number][]; prevClose: number; priceLabel?: string }>()

/** 成交量（手）：按大小换成手、万手、亿手。 */
function lots(v: number, unit = '手'): string {
  if (v >= 1e8) return `${(v / 1e8).toFixed(1)}亿${unit}`
  if (v >= 1e4) return `${(v / 1e4).toFixed(1)}万${unit}`
  return `${Math.round(v)}${unit}`
}

const UP = '#d83a3a'
const DOWN = '#12915a'
const LINE = '#17457f'
const INK_MUTED = '#667085'
const GRID_LINE = '#e6e9ef'

/** 全天 242 个分钟刻度（09:30–11:30，13:00–15:00），盘中时线只画到当前时刻。 */
function tradingMinutes(): string[] {
  const out: string[] = []
  const push = (from: number, to: number) => {
    for (let m = from; m <= to; m++) {
      out.push(`${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`)
    }
  }
  push(9 * 60 + 30, 11 * 60 + 30)
  push(13 * 60, 15 * 60)
  return out
}

const el = ref<HTMLElement>()
let chart: ECharts | null = null
let observer: ResizeObserver | null = null

function render(): void {
  if (!el.value) return
  const axis = tradingMinutes()
  const byTime = new Map(props.minutes.map((m) => [m[0], m]))
  const prices = axis.map((t) => byTime.get(t)?.[1] ?? null)
  const volumes = axis.map((t, i) => {
    const row = byTime.get(t)
    if (!row) return null
    const before = i > 0 ? (prices[i - 1] ?? props.prevClose) : props.prevClose
    return { value: row[2], itemStyle: { color: row[1] >= before ? UP : DOWN } }
  })
  // 纵轴以昨收为中心上下对称，一眼看出涨跌幅度
  const known = props.minutes.map((m) => m[1])
  const span = Math.max(...known.map((p) => Math.abs(p - props.prevClose)), props.prevClose * 0.002)
  const pct = (v: number) => `${(((v - props.prevClose) / props.prevClose) * 100).toFixed(2)}%`

  chart ??= init(el.value)
  chart.setOption(
    {
      animation: false,
      grid: [
        { left: 60, right: 56, top: 10, height: '64%' },
        { left: 60, right: 56, top: '78%', height: '16%' },
      ],
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross', link: [{ xAxisIndex: 'all' }] },
        backgroundColor: '#fff',
        borderColor: GRID_LINE,
        textStyle: { color: '#17202e', fontSize: 12 },
        formatter: (params: { dataIndex: number }[]) => {
          const i = params[0]?.dataIndex ?? 0
          const price = prices[i]
          if (price == null) return axis[i]
          const vol = volumes[i]?.value ?? 0
          const row = (k: string, v: string) =>
            `<div style="display:flex;justify-content:space-between;gap:18px"><span style="color:${INK_MUTED}">${k}</span><span style="font-variant-numeric:tabular-nums">${v}</span></div>`
          return `<b>${axis[i]}</b>${row(props.priceLabel ?? '点位', price.toFixed(2))}${row('涨跌幅', pct(price))}${row('成交量', lots(vol))}`
        },
      },
      axisPointer: { link: [{ xAxisIndex: 'all' }] },
      xAxis: [
        {
          type: 'category',
          data: axis,
          boundaryGap: false,
          axisLine: { lineStyle: { color: GRID_LINE } },
          axisTick: { show: false },
          axisLabel: { show: false },
        },
        {
          type: 'category',
          gridIndex: 1,
          data: axis,
          axisLine: { lineStyle: { color: GRID_LINE } },
          axisTick: { show: false },
          axisLabel: {
            color: INK_MUTED,
            fontSize: 11,
            interval: (i: number) => [0, 60, 120, 181, 241].includes(i),
            formatter: (v: string) => (v === '11:30' ? '11:30/13:00' : v),
          },
        },
      ],
      yAxis: [
        {
          min: props.prevClose - span * 1.05,
          max: props.prevClose + span * 1.05,
          splitNumber: 4,
          // 上下边界是按昨收对称算出来的非整数，不标，避免和相邻刻度挤在一起
          axisLabel: {
            color: INK_MUTED,
            fontSize: 11,
            showMinLabel: false,
            showMaxLabel: false,
            // 低价股的刻度要保留小数，否则几个刻度都显示成同一个整数
            formatter: (v: number) => v.toFixed(props.prevClose < 100 ? 2 : 0),
          },
          splitLine: { lineStyle: { color: GRID_LINE } },
        },
        {
          gridIndex: 1,
          splitNumber: 2,
          axisLabel: { color: INK_MUTED, fontSize: 11, formatter: (v: number) => lots(v, '') },
          splitLine: { show: false },
        },
      ],
      series: [
        {
          type: 'line',
          data: prices,
          showSymbol: false,
          lineStyle: { color: LINE, width: 1.5 },
          areaStyle: { color: 'rgba(23, 69, 127, 0.06)', origin: 'start' },
          markLine: {
            silent: true,
            symbol: 'none',
            lineStyle: { color: '#c3cad6', type: 'dashed' },
            label: { color: INK_MUTED, fontSize: 11, formatter: `昨收 ${props.prevClose.toFixed(2)}` },
            data: [{ yAxis: props.prevClose }],
          },
        },
        { type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: volumes, barWidth: '60%' },
      ],
    },
    true,
  )
}

onMounted(() => {
  render()
  observer = new ResizeObserver(() => chart?.resize())
  if (el.value) observer.observe(el.value)
})
watch(() => props.minutes, render)
onBeforeUnmount(() => {
  observer?.disconnect()
  chart?.dispose()
})
</script>

<template>
  <div ref="el" class="intraday" role="img" aria-label="当日分时走势与成交量" />
</template>

<style scoped>
.intraday {
  width: 100%;
  height: 320px;
}
</style>
