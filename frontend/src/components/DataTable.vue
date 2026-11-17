<script setup lang="ts">
import type { TableBlock } from '../api'

defineProps<{ block: TableBlock }>()
</script>

<template>
  <figure class="data-table">
    <figcaption class="title">{{ block.title }}</figcaption>
    <!-- 列多时表格自己横向滚动，不撑破页面 -->
    <div class="scroll">
      <table>
        <thead>
          <tr>
            <th v-for="(col, i) in block.columns" :key="i" scope="col">{{ col }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, r) in block.rows" :key="r">
            <th scope="row">{{ row[0] }}</th>
            <td v-for="(cell, c) in row.slice(1)" :key="c">{{ cell }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <p class="note">
      <span v-if="block.note">{{ block.note }}</span>
      <span>
        来源：<a :href="block.source.url" target="_blank" rel="noopener noreferrer">{{
          block.source.name
        }}</a>
      </span>
    </p>
  </figure>
</template>

<style scoped>
.data-table {
  margin: 0 0 16px;
  padding: 14px 16px 12px;
  border: 1px solid var(--line);
  border-radius: 10px;
}
.title {
  margin-bottom: 8px;
  font-weight: 600;
}
.scroll {
  overflow-x: auto;
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 14px;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
th,
td {
  padding: 6px 12px;
  border-bottom: 1px solid var(--line);
}
thead th {
  color: var(--text-muted);
  font-weight: 500;
  text-align: right;
}
thead th:first-child,
tbody th {
  text-align: left;
  font-weight: 500;
}
td {
  text-align: right;
}
tbody tr:last-child th,
tbody tr:last-child td {
  border-bottom: none;
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
</style>
