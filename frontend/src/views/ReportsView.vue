<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { reportApi, type Report, type ReportSummary } from '../api'
import MarkdownView from '../components/MarkdownView.vue'
import { beijingTime } from '../market'

const route = useRoute()
const router = useRouter()
const list = ref<ReportSummary[]>([])
const report = ref<Report | null>(null)
const loading = ref(true)
const error = ref('')
const showFacts = ref(false)

const selected = computed(() =>
  route.params.date ? { date: String(route.params.date), kind: String(route.params.kind) } : null,
)

async function loadReport(): Promise<void> {
  error.value = ''
  showFacts.value = false
  const target = selected.value ?? list.value[0]
  if (!target) {
    report.value = null
    return
  }
  try {
    report.value = await reportApi.get(target.date, target.kind)
  } catch (e) {
    report.value = null
    error.value = e instanceof Error ? e.message : '加载失败'
  }
}

onMounted(async () => {
  try {
    list.value = await reportApi.list()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
  await loadReport()
})
watch(selected, loadReport)

function isActive(r: ReportSummary): boolean {
  return report.value?.date === r.date && report.value?.kind === r.kind
}

</script>

<template>
  <div class="reports-page">
    <div class="page">
      <header class="page-head">
        <h1>每日报告</h1>
        <p class="sub">
          交易日 8:45 起生成早报、15:30 起生成收盘复盘，全站共用。报告由 AI 根据当时取到的数据撰写，可展开「数据原文」核对。
        </p>
      </header>

      <div class="grid">
        <nav class="card list" aria-label="报告列表">
          <p v-if="loading" class="placeholder">正在加载…</p>
          <p v-else-if="!list.length" class="placeholder">还没有报告。下一个交易日 8:45 后会生成第一份早报。</p>
          <button
            v-for="r in list"
            :key="`${r.date}-${r.kind}`"
            type="button"
            class="item"
            :class="{ active: isActive(r) }"
            @click="router.push({ name: 'report', params: { date: r.date, kind: r.kind } })"
          >
            <span class="item-head">
              <span class="kind" :class="r.kind">{{ r.kind === 'morning' ? '早报' : '复盘' }}</span>
              <b>{{ r.title }}</b>
            </span>
            <span class="summary">{{ r.summary }}</span>
          </button>
        </nav>

        <article class="card content">
          <p v-if="error" class="placeholder error">{{ error }}</p>
          <template v-else-if="report">
            <header class="report-head">
              <h2>{{ report.title }}</h2>
              <span class="meta">生成于 {{ beijingTime(report.created_at, true) }}</span>
            </header>
            <MarkdownView :content="report.content" />
            <div class="facts">
              <el-button link type="primary" @click="showFacts = !showFacts">
                {{ showFacts ? '收起数据原文' : '查看数据原文（生成报告时交给 AI 的全部数据）' }}
              </el-button>
              <pre v-if="showFacts">{{ report.facts }}</pre>
            </div>
            <p class="disclaimer">本报告由 AI 根据公开数据自动生成，可能存在错误，仅供内部研究参考，不构成投资建议。</p>
          </template>
        </article>
      </div>
    </div>
  </div>
</template>

<style scoped>
.reports-page {
  overflow-y: auto;
}
.page {
  max-width: 1280px;
  margin: 0 auto;
  padding: 18px 24px 40px;
}
.page-head {
  margin-bottom: 14px;
}
h1 {
  margin: 0;
  color: var(--navy);
  font-size: 22px;
}
.sub {
  margin: 2px 0 0;
  color: var(--text-muted);
  font-size: 13px;
}
.grid {
  display: grid;
  grid-template-columns: 300px minmax(0, 1fr);
  gap: 14px;
  align-items: start;
}
.card {
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
}
.list {
  position: sticky;
  top: 0;
  max-height: calc(100vh - 160px);
  overflow-y: auto;
  padding: 6px;
}
.item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  width: 100%;
  padding: 10px;
  border: 0;
  border-radius: 6px;
  background: none;
  color: var(--text);
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.item:hover {
  background: var(--surface-alt);
}
.item.active {
  background: var(--brand-soft);
}
.item-head {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
}
.kind {
  padding: 0 6px;
  border-radius: 4px;
  font-size: 12px;
  line-height: 20px;
}
.kind.morning {
  background: #fdf3e1;
  color: #9a6b14;
}
.kind.close {
  background: var(--brand-soft);
  color: var(--brand);
}
.summary {
  display: -webkit-box;
  overflow: hidden;
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.5;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}
.content {
  padding: 20px 28px;
}
.report-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 14px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--line);
}
.report-head h2 {
  margin: 0;
  color: var(--navy);
  font-size: 20px;
}
.meta {
  color: var(--text-muted);
  font-size: 12px;
}
.facts {
  margin-top: 20px;
  padding-top: 10px;
  border-top: 1px dashed var(--line);
}
.facts pre {
  max-height: 480px;
  overflow: auto;
  padding: 12px;
  border-radius: 6px;
  background: var(--surface-alt);
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
}
.disclaimer {
  margin: 12px 0 0;
  color: var(--text-muted);
  font-size: 12px;
}
.placeholder {
  padding: 24px 12px;
  color: var(--text-muted);
  font-size: 13px;
  text-align: center;
}
.error {
  color: var(--danger);
}
</style>
