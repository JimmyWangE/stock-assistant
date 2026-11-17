<script setup lang="ts">
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { computed, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { api } from '../api'
import { setUser } from '../auth'
import BrandMark from '../components/BrandMark.vue'

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
</script>

<template>
  <div class="page">
    <section class="intro">
      <div class="brand">
        <BrandMark :size="34" />
        <div>
          <div class="brand-name">A股投研助手</div>
          <div class="brand-sub">EQUITY RESEARCH</div>
        </div>
      </div>
      <div class="pitch">
        <h2>对话式投研工作台</h2>
        <p>用一句话提问，获得带数据、图表和来源的研究回答。</p>
        <ul>
          <li><b>实时行情与 K 线</b>分钟、日、周、月线随问随看</li>
          <li><b>财报解读</b>主要财务指标逐期对比</li>
          <li><b>新闻与政策</b>财经资讯与部委官网原文链接</li>
        </ul>
      </div>
      <p class="foot">仅供内部研究使用</p>
    </section>

    <div class="card">
      <h1>{{ isRegister ? '创建账号' : '登录' }}</h1>
      <p class="subtitle">{{ isRegister ? '注册后即可开始使用' : '欢迎回来，请登录后开始使用' }}</p>

      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-position="top"
        size="large"
        @submit.prevent="submit"
      >
        <el-form-item label="用户名" prop="username">
          <el-input v-model="form.username" autocomplete="username" autofocus />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input
            v-model="form.password"
            type="password"
            show-password
            :autocomplete="isRegister ? 'new-password' : 'current-password'"
          />
        </el-form-item>
        <el-form-item v-if="isRegister" label="确认密码" prop="confirm">
          <el-input
            v-model="form.confirm"
            type="password"
            show-password
            autocomplete="new-password"
          />
        </el-form-item>
        <el-button type="primary" native-type="submit" :loading="submitting" class="submit">
          {{ isRegister ? '注册并登录' : '登录' }}
        </el-button>
      </el-form>

      <p class="switch">
        {{ isRegister ? '已有账号？' : '还没有账号？' }}
        <el-link type="primary" underline="never" @click="switchMode">
          {{ isRegister ? '去登录' : '注册一个' }}
        </el-link>
      </p>
    </div>
  </div>
</template>

<style scoped>
.page {
  display: flex;
  min-height: 100%;
  background: var(--surface);
}

/* 左侧：品牌介绍。窗口窄时隐藏，只留表单 */
.intro {
  display: flex;
  flex: 1;
  flex-direction: column;
  justify-content: space-between;
  max-width: 560px;
  padding: 40px 48px;
  box-sizing: border-box;
  background: linear-gradient(160deg, var(--navy) 0%, #12305a 100%);
  color: var(--on-navy);
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
.pitch h2 {
  margin: 0 0 10px;
  color: #fff;
  font-size: 30px;
  line-height: 1.3;
  letter-spacing: 1px;
}
.pitch p {
  margin: 0 0 28px;
  color: var(--on-navy-muted);
}
.pitch ul {
  margin: 0;
  padding: 0;
  list-style: none;
}
.pitch li {
  padding: 12px 0 12px 14px;
  border-left: 2px solid var(--gold);
  color: var(--on-navy-muted);
  font-size: 14px;
}
.pitch li + li {
  margin-top: 12px;
}
.pitch b {
  display: block;
  color: #fff;
  font-size: 15px;
  font-weight: 600;
}
.foot {
  margin: 0;
  color: var(--on-navy-muted);
  font-size: 12px;
}
@media (max-width: 860px) {
  .intro {
    display: none;
  }
}

.card {
  width: 100%;
  max-width: 380px;
  margin: auto;
  padding: 32px 24px;
  box-sizing: border-box;
}
h1 {
  margin: 0;
  color: var(--navy);
  font-size: 24px;
  line-height: 1.3;
}
.subtitle {
  margin: 4px 0 28px;
  color: var(--text-muted);
}
.submit {
  width: 100%;
  margin-top: 4px;
}
.switch {
  margin: 20px 0 0;
  text-align: center;
  color: var(--text-muted);
  font-size: 14px;
}
.switch .el-link {
  vertical-align: baseline;
}
</style>
