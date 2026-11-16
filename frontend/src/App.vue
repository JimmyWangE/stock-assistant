<script setup lang="ts">
import { onMounted, ref } from 'vue'

// 骨架阶段的占位页：显示后端各依赖的连通状态，功能页面后续替换。
interface Check {
  status: string
  detail?: string
  models?: string[]
}

const labels: Record<string, string> = { database: '数据库', redis: '缓存', llm: '模型服务' }
const checks = ref<Record<string, Check>>({})
const error = ref('')

onMounted(async () => {
  try {
    const resp = await fetch('/api/health')
    const { status: _overall, ...rest } = await resp.json()
    checks.value = rest
  } catch {
    error.value = '无法连接后端'
  }
})
</script>

<template>
  <main>
    <h1>A股投研助手</h1>
    <p>项目骨架已启动，以下为各依赖的连通状态。</p>
    <p v-if="error" class="bad">{{ error }}</p>
    <ul>
      <li v-for="(check, name) in checks" :key="name">
        {{ labels[name] ?? name }}：
        <span :class="check.status === 'ok' ? 'good' : 'bad'">
          {{ check.status === 'ok' ? '正常' : '异常' }}
        </span>
        <small v-if="check.models?.length">（{{ check.models.join('、') }}）</small>
        <small v-if="check.detail">（{{ check.detail }}）</small>
      </li>
    </ul>
  </main>
</template>

<style scoped>
main {
  max-width: 640px;
  margin: 80px auto;
  padding: 0 16px;
  font-family: system-ui, sans-serif;
}
.good {
  color: #0a7d33;
}
.bad {
  color: #c0392b;
}
</style>
