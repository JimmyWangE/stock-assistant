<script setup lang="ts">
import { DataLine, Document, Lock, Reading, TrendCharts, User } from '@element-plus/icons-vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { api, type MarketIndex } from '../api'
import { setUser } from '../auth'
import BrandMark from '../components/BrandMark.vue'
import { signed, todayLabel, trend } from '../market'

const route = useRoute()
const router = useRouter()

const mode = ref<'login' | 'register'>('login')
const isRegister = computed(() => mode.value === 'register')
const submitting = ref(false)
const formRef = ref<FormInstance>()
const form = reactive({ username: '', password: '', confirm: '' })

const rules = computed<FormRules>(() => ({
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 2, max: 32, message: '用户名长度为 2–32 个字符', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, max: 128, message: '密码至少 6 位', trigger: 'blur' },
  ],
  confirm: isRegister.value
    ? [
        { required: true, message: '请再次输入密码', trigger: 'blur' },
        {
          validator: (_rule, value, callback) =>
            value === form.password ? callback() : callback(new Error('两次输入的密码不一致')),
          trigger: 'blur',
        },
      ]
    : [],
}))

function switchMode(): void {
  mode.value = isRegister.value ? 'login' : 'register'
  form.confirm = ''
  formRef.value?.clearValidate()
}

async function submit(): Promise<void> {
  if (submitting.value || !(await formRef.value?.validate().catch(() => false))) return
  submitting.value = true
  try {
    const call = isRegister.value ? api.register : api.login
    setUser(await call(form.username.trim(), form.password))
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/'
    // 只接受站内路径，避免被带参数的链接引到别的网站
    await router.replace(redirect.startsWith('/') && !redirect.startsWith('//') ? redirect : '/')
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '操作失败，请重试')
  } finally {
    submitting.value = false
  }
}

// 登录页的指数行情：公开数据，不需要登录。取不到就不显示
const ticker = ref<{ indices: MarketIndex[]; as_of: string; session: string } | null>(null)
let tickerTimer: ReturnType<typeof setInterval> | undefined
async function loadTicker(): Promise<void> {
  if (document.hidden) return
  try {
    ticker.value = await api.ticker()
  } catch {
    // 不影响登录
  }
}
onMounted(() => {
  loadTicker()
  tickerTimer = setInterval(loadTicker, 10_000)
})
onBeforeUnmount(() => clearInterval(tickerTimer))

const features = [
  { icon: TrendCharts, title: '实时行情与 K 线', desc: '个股与指数行情到秒，分钟至月线随问随看' },
  { icon: DataLine, title: '市场全景', desc: '涨跌分布、行业热力图、资金流向一屏掌握' },
  { icon: Document, title: '财报解读', desc: '主要财务指标逐期对比，AI 提炼要点' },
  { icon: Reading, title: '新闻与政策', desc: '财经快讯与部委官网原文，附来源链接' },
]
</script>

<template>
  <div class="page">
    <!-- 背景：淡淡的网格与走势线，只做装饰 -->
    <svg class="backdrop" viewBox="0 0 1440 900" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
      <defs>
        <pattern id="grid" width="48" height="48" patternUnits="userSpaceOnUse">
          <path d="M48 0H0V48" fill="none" stroke="rgba(255,255,255,0.05)" />
        </pattern>
      </defs>
      <rect width="1440" height="900" fill="url(#grid)" />
      <polyline
        points="0,700 90,660 160,690 240,610 320,640 400,560 480,590 560,500 640,540 720,450 800,480 880,400 960,430 1040,350 1120,380 1200,300 1280,330 1360,260 1440,280"
        fill="none"
        stroke="rgba(194,160,99,0.35)"
        stroke-width="2"
      />
      <polyline
        points="0,780 120,760 220,790 330,730 440,750 560,690 680,720 800,650 920,680 1040,610 1160,640 1280,580 1440,600"
        fill="none"
        stroke="rgba(255,255,255,0.08)"
        stroke-width="1.5"
      />
    </svg>

    <header class="top">
      <div class="brand">
        <BrandMark :size="32" />
        <div>
          <div class="brand-name">A股投研助手</div>
          <div class="brand-sub">EQUITY RESEARCH</div>
        </div>
      </div>
      <span class="date">{{ todayLabel() }}<template v-if="ticker?.session"> · {{ ticker.session }}</template></span>
    </header>

    <main class="main">
      <section class="intro">
        <p class="eyebrow">对话式 A 股投研工作台</p>
        <h1>用一句话提问，<br />获得有数据、有来源的研究回答</h1>
        <p class="lead">
          实时行情、财务数据、财经新闻与部委政策原文统一接入，由投研大模型调用、分析并给出可追溯的结论。
        </p>

        <ul v-if="ticker?.indices.length" class="ticker">
          <li v-for="item in ticker.indices" :key="item.code" :class="trend(item.change)">
            <span class="t-name">{{ item.name }}</span>
            <span class="t-price">{{ item.price.toFixed(2) }}</span>
            <span class="t-change">{{ signed(item.percent) }}%</span>
          </li>
        </ul>

        <div class="features">
          <div v-for="f in features" :key="f.title" class="feature">
            <span class="f-icon"><el-icon><component :is="f.icon" /></el-icon></span>
            <div>
              <div class="f-title">{{ f.title }}</div>
              <div class="f-desc">{{ f.desc }}</div>
            </div>
          </div>
        </div>
      </section>

      <section class="card">
        <div class="mode-tabs" role="tablist">
          <button type="button" role="tab" :aria-selected="!isRegister" :class="{ active: !isRegister }" @click="isRegister && switchMode()">账号登录</button>
          <button type="button" role="tab" :aria-selected="isRegister" :class="{ active: isRegister }" @click="!isRegister && switchMode()">注册新账号</button>
        </div>
        <p class="subtitle">{{ isRegister ? '注册后即可使用全部功能' : '欢迎回来，请登录后开始使用' }}</p>

        <el-form ref="formRef" :model="form" :rules="rules" size="large" @submit.prevent="submit">
          <el-form-item prop="username">
            <el-input v-model="form.username" :prefix-icon="User" placeholder="用户名" autocomplete="username" autofocus />
          </el-form-item>
          <el-form-item prop="password">
            <el-input
              v-model="form.password"
              :prefix-icon="Lock"
              type="password"
              placeholder="密码"
              show-password
              :autocomplete="isRegister ? 'new-password' : 'current-password'"
            />
          </el-form-item>
          <el-form-item v-if="isRegister" prop="confirm">
            <el-input v-model="form.confirm" :prefix-icon="Lock" type="password" placeholder="再次输入密码" show-password autocomplete="new-password" />
          </el-form-item>
          <el-button type="primary" native-type="submit" :loading="submitting" class="submit">
            {{ isRegister ? '注册并登录' : '登录' }}
          </el-button>
        </el-form>

        <p class="switch">
          {{ isRegister ? '已有账号？' : '还没有账号？' }}
          <el-link type="primary" underline="never" @click="switchMode">{{ isRegister ? '去登录' : '注册一个' }}</el-link>
        </p>
        <div class="notice">
          <el-icon><Lock /></el-icon>
          内部系统，仅限授权人员使用。登录状态保持 7 天，对话记录仅本人可见。
        </div>
      </section>
    </main>

    <footer class="foot">
      <span>数据来源：腾讯财经 · 新浪财经 · 东方财富 · 同花顺 · 国务院、证监会、人民银行、财政部、发改委官网</span>
      <span>内容由 AI 生成，仅供内部研究参考，不构成投资建议</span>
    </footer>
  </div>
</template>

<style scoped>
.page {
  position: relative;
  display: flex;
  flex-direction: column;
  min-height: 100%;
  overflow: hidden;
  background: radial-gradient(1200px 700px at 20% 10%, #183a66 0%, transparent 60%),
    linear-gradient(160deg, var(--navy) 0%, #0f2847 55%, #0b1d33 100%);
  color: var(--on-navy);
}
.backdrop {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
}
.top,
.main,
.foot {
  position: relative;
}
.top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 24px 48px 0;
}
.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  color: #fff;
}
.brand-name {
  font-size: 18px;
  font-weight: 600;
  line-height: 1.3;
  letter-spacing: 0.5px;
}
.brand-sub {
  color: var(--gold);
  font-size: 11px;
  letter-spacing: 2px;
}
.date {
  color: var(--on-navy-muted);
  font-size: 13px;
}

.main {
  display: flex;
  flex: 1;
  align-items: center;
  justify-content: center;
  gap: 72px;
  padding: 32px 48px;
}
.intro {
  flex: 1;
  max-width: 620px;
}
.eyebrow {
  margin: 0 0 12px;
  color: var(--gold);
  font-size: 13px;
  letter-spacing: 2px;
}
h1 {
  margin: 0;
  color: #fff;
  font-size: 34px;
  line-height: 1.35;
  letter-spacing: 1px;
}
.lead {
  margin: 14px 0 24px;
  color: var(--on-navy-muted);
  font-size: 15px;
}
.ticker {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  margin: 0 0 24px;
  padding: 0;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.04);
  list-style: none;
  font-variant-numeric: tabular-nums;
}
.ticker li {
  display: flex;
  flex-direction: column;
  padding: 10px 12px;
  border-left: 1px solid rgba(255, 255, 255, 0.08);
}
.ticker li:first-child {
  border-left: none;
}
.t-name {
  color: var(--on-navy-muted);
  font-size: 12px;
}
.t-price {
  color: #fff;
  font-size: 16px;
  font-weight: 600;
}
.t-change {
  font-size: 12px;
  font-weight: 600;
}
.up .t-change {
  color: #ff6b6b;
}
.down .t-change {
  color: #3ecf8e;
}
.features {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px 24px;
}
.feature {
  display: flex;
  gap: 12px;
}
.f-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  flex-shrink: 0;
  border: 1px solid rgba(194, 160, 99, 0.4);
  border-radius: 8px;
  color: var(--gold);
  font-size: 18px;
}
.f-title {
  color: #fff;
  font-size: 14px;
  font-weight: 600;
}
.f-desc {
  color: var(--on-navy-muted);
  font-size: 13px;
  line-height: 1.5;
}

.card {
  width: 400px;
  flex-shrink: 0;
  padding: 28px 32px 22px;
  box-sizing: border-box;
  border-radius: 12px;
  background: var(--surface);
  box-shadow: 0 24px 60px rgba(0, 0, 0, 0.35);
  color: var(--text);
}
.mode-tabs {
  display: flex;
  gap: 24px;
  border-bottom: 1px solid var(--line);
}
.mode-tabs button {
  margin-bottom: -1px;
  padding: 0 0 10px;
  border: 0;
  border-bottom: 2px solid transparent;
  background: none;
  color: var(--text-muted);
  font: inherit;
  font-size: 16px;
  font-weight: 600;
  cursor: pointer;
}
.mode-tabs button.active {
  border-bottom-color: var(--gold);
  color: var(--navy);
}
.subtitle {
  margin: 14px 0 20px;
  color: var(--text-muted);
  font-size: 13px;
}
.submit {
  width: 100%;
  margin-top: 2px;
}
.switch {
  margin: 16px 0 0;
  text-align: center;
  color: var(--text-muted);
  font-size: 13px;
}
.switch .el-link {
  vertical-align: baseline;
}
.notice {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  margin-top: 18px;
  padding: 10px 12px;
  border-radius: 6px;
  background: var(--surface-alt);
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.6;
}
.notice .el-icon {
  margin-top: 3px;
  flex-shrink: 0;
}

.foot {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 6px 24px;
  padding: 14px 48px 18px;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  color: var(--on-navy-muted);
  font-size: 12px;
}

/* 窗口窄时只留表单 */
@media (max-width: 1000px) {
  .intro {
    display: none;
  }
}
@media (max-width: 480px) {
  .top,
  .main,
  .foot {
    padding-left: 16px;
    padding-right: 16px;
  }
  .card {
    width: 100%;
  }
}
</style>
