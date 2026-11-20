<script setup lang="ts">
import type { TableBlock } from '../api'

defineProps<{ block: TableBlock }>()

/** 选股结果等表格的行名形如"贵州茅台（600519）"，取出代码做成个股详情链接。 */
function stockCode(cell: string): string | null {
  return /（(\d{6})）$/.exec(cell)?.[1] ?? null
}
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
            <th scope="row">
              <router-link v-if="stockCode(row[0])" :to="`/stock/${stockCode(row[0])}`" class="stock-link">{{
                row[0]
              }}</router-link>
              <template v-else>{{ row[0] }}</template>
            </th>
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
.stock-link {
  color: inherit;
  text-decoration: none;
}
.stock-link:hover {
  color: var(--brand);
  text-decoration: underline;
}
.data-table {
  margin: 0 0 16px;
  padding: 14px 16px 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
}
.title {
  margin-bottom: 10px;
  padding-left: 10px;
  border-left: 3px solid var(--gold);
  color: var(--navy);
  font-weight: 600;
  line-height: 1.3;
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
  border-top: 2px solid var(--navy);
  border-bottom: 1px solid var(--navy);
  color: var(--text-muted);
  font-size: 13px;
  font-weight: 500;
  text-align: right;
}
tbody tr:hover {
  background: var(--surface-alt);
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
