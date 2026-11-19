<script setup lang="ts">
// 产品标识：三根逐级抬升的阳线，与网页图标（public/favicon.svg）同一造型。
// 外框和底线跟随文字颜色，深色和浅色背景上都能用。
defineProps<{ size?: number }>()
</script>

<template>
  <svg :width="size ?? 28" :height="size ?? 28" viewBox="0 0 32 32" fill="none" aria-hidden="true">
    <rect x="0.75" y="0.75" width="30.5" height="30.5" rx="7" stroke="currentColor" stroke-width="1.5" opacity="0.35" />
    <g stroke="var(--up)" stroke-width="1.6" stroke-linecap="round">
      <path d="M8 18.5v8M16 12v9M24 5v9.5" />
    </g>
    <g fill="var(--up)">
      <rect x="5.5" y="20" width="5" height="5" rx="1" />
      <rect x="13.5" y="13.5" width="5" height="6" rx="1" />
      <rect x="21.5" y="6.5" width="5" height="6.5" rx="1" />
    </g>
    <path d="M5 28.5h22" stroke="var(--gold)" stroke-width="1.4" stroke-linecap="round" />
  </svg>
</template>
