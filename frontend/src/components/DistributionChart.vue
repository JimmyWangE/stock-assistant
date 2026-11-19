<script setup lang="ts">
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { init, use, type ECharts } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

use([BarChart, GridComponent, TooltipComponent, CanvasRenderer])

// 涨跌分布：每档股票只数。上涨档红、下跌档绿、平盘灰；每根柱顶写明只数，不只靠颜色
const props = defineProps<{ data: { label: string; count: number }[] }>()

const UP = '#d83a3a'
const DOWN = '#12915a'
const FLAT = '#98a2b3'
const INK_MUTED = '#667085'

const el = ref<HTMLElement>()
let chart: ECharts | null = null
let observer: ResizeObserver | null = null

function color(label: string): string {
  if (label === '平') return FLAT
  return label === '涨停' || !label.startsWith('-') && !label.startsWith('<') && label !== '跌停'
    ? UP
    : DOWN
}

function render(): void {
  if (!el.value) return
  chart ??= init(el.value)
  chart.setOption({
    animation: false,
    grid: { left: 4, right: 4, top: 22, bottom: 22, containLabel: false },
    tooltip: {
      trigger: 'item',
      formatter: (p: { name: string; value: number }) => `${p.name}：${p.value} 只`,
    },
    xAxis: {
      type: 'category',
      data: props.data.map((d) => d.label),
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: INK_MUTED, fontSize: 10, interval: 0 },
    },
    yAxis: { show: false },
    series: [
      {
        type: 'bar',
        barWidth: '62%',
        data: props.data.map((d) => ({
          value: d.count,
          itemStyle: { color: color(d.label), borderRadius: [3, 3, 0, 0] },
        })),
        label: { show: true, position: 'top', color: '#344054', fontSize: 11 },
      },
    ],
  })
}

onMounted(() => {
  render()
  observer = new ResizeObserver(() => chart?.resize())
  if (el.value) observer.observe(el.value)
})
watch(() => props.data, render)
onBeforeUnmount(() => {
  observer?.disconnect()
  chart?.dispose()
})
</script>

<template>
  <div ref="el" class="distribution" role="img" aria-label="全市场涨跌幅分布" />
</template>

<style scoped>
.distribution {
  width: 100%;
  height: 170px;
}
</style>
