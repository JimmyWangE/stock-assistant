<script setup lang="ts">
import { computed } from 'vue'

import { renderCached, splitBlocks } from '../markdown'

// 回答正文。生成中按段渲染：已完成的段落 HTML 不变，页面只更新最后一段；
// 生成结束后整篇渲染一次（列表、表格等跨段结构以整篇为准）。
const props = defineProps<{ content: string; streaming?: boolean }>()

const parts = computed(() =>
  props.streaming ? splitBlocks(props.content).map(renderCached) : [renderCached(props.content)],
)
</script>

<template>
  <!-- renderMarkdown 的输出已经过净化，可以安全插入 -->
  <div class="markdown">
    <div v-for="(html, i) in parts" :key="i" class="md-part" v-html="html" />
  </div>
</template>

<style scoped>
/* 段落之间的间距由各段内部元素的外边距决定，这里把每段当成普通块 */
.md-part > :deep(:first-child) {
  margin-top: 0;
}
.md-part:not(:last-child) {
  margin-bottom: 12px;
}
.md-part > :deep(:last-child) {
  margin-bottom: 0;
}
</style>
