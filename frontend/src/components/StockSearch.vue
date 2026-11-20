<script setup lang="ts">
import { Search } from '@element-plus/icons-vue'
import { ref } from 'vue'
import { useRouter } from 'vue-router'

import { stockApi } from '../api'

const router = useRouter()
const text = ref('')

interface Option {
  value: string
  code: string
  name: string
}

async function suggest(query: string, done: (items: Option[]) => void): Promise<void> {
  if (!query.trim()) return done([])
  try {
    const rows = await stockApi.search(query.trim())
    done(rows.map((r) => ({ value: `${r.name} ${r.code}`, ...r })))
  } catch {
    done([])
  }
}

function open(item: Record<string, unknown>): void {
  text.value = ''
  router.push(`/stock/${item.code as string}`)
}
</script>

<template>
  <el-autocomplete
    v-model="text"
    class="stock-search"
    :fetch-suggestions="suggest"
    :trigger-on-focus="false"
    :debounce="200"
    placeholder="股票代码 / 名称"
    aria-label="搜索股票，查看个股详情"
    :prefix-icon="Search"
    highlight-first-item
    @select="open"
  >
    <template #default="{ item }">
      <span class="opt-name">{{ item.name }}</span><span class="opt-code">{{ item.code }}</span>
    </template>
  </el-autocomplete>
</template>

<style scoped>
.stock-search {
  width: 170px;
}
.stock-search :deep(.el-input__wrapper) {
  background: var(--navy-soft);
  box-shadow: 0 0 0 1px var(--navy-line) inset;
}
.stock-search :deep(.el-input__inner) {
  color: #fff;
}
.stock-search :deep(.el-input__inner::placeholder) {
  color: var(--on-navy-muted);
}
.opt-name {
  margin-right: 8px;
}
.opt-code {
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
}
</style>
