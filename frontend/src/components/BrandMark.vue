<script setup lang="ts">
// 产品标识：三根 K 线。颜色跟随文字颜色，深色和浅色背景上都能用。
defineProps<{ size?: number }>()
</script>

<template>
  <svg
    :width="size ?? 28"
    :height="size ?? 28"
    viewBox="0 0 28 28"
    fill="none"
    aria-hidden="true"
  >
    <rect x="0.5" y="0.5" width="27" height="27" rx="6" stroke="currentColor" opacity="0.35" />
    <g stroke="currentColor" stroke-width="1.5" stroke-linecap="round">
      <path d="M8 8v12M14 6v14M20 9v13" />
    </g>
    <rect x="6" y="11" width="4" height="6" rx="1" fill="currentColor" />
    <rect x="12" y="9" width="4" height="7" rx="1" fill="var(--gold)" />
    <rect x="18" y="12" width="4" height="7" rx="1" fill="currentColor" />
  </svg>
</template>
