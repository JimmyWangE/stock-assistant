<script setup lang="ts">
import { computed } from 'vue'

// 迷你走势线：只表达形状，不带坐标轴。虚线是昨收位置。
const props = defineProps<{ points: number[]; base: number; width?: number; height?: number }>()

const w = computed(() => props.width ?? 84)
const h = computed(() => props.height ?? 26)

const shape = computed(() => {
  const pts = props.points
  if (pts.length < 2) return null
  const low = Math.min(...pts, props.base)
  const high = Math.max(...pts, props.base)
  const span = high - low || 1
  const y = (v: number) => 1.5 + (1 - (v - low) / span) * (h.value - 3)
  // 横轴按全天 241 分钟的进度铺开：盘中只画到当前时刻，右侧留空
  const step = w.value / Math.max(pts.length - 1, 60)
  const line = pts.map((v, i) => `${(i * step).toFixed(1)},${y(v).toFixed(1)}`).join(' ')
  return { line, baseY: y(props.base) }
})
</script>

<template>
  <svg :width="w" :height="h" :viewBox="`0 0 ${w} ${h}`" aria-hidden="true">
    <template v-if="shape">
      <line :x1="0" :x2="w" :y1="shape.baseY" :y2="shape.baseY" class="base" />
      <polyline :points="shape.line" class="line" />
    </template>
  </svg>
</template>

<style scoped>
.base {
  stroke: var(--line-strong);
  stroke-width: 1;
  stroke-dasharray: 2 3;
}
.line {
  fill: none;
  stroke: currentColor;
  stroke-width: 1.5;
  stroke-linejoin: round;
  stroke-linecap: round;
}
</style>
