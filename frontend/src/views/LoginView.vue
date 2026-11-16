<script setup lang="ts">
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { computed, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { api } from '../api'
import { setUser } from '../auth'

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
    <div class="card">
      <h1>A股投研助手</h1>
      <p class="subtitle">{{ isRegister ? '创建账号' : '登录后开始使用' }}</p>

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
  min-height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px 16px;
  box-sizing: border-box;
  background: var(--surface-alt);
}
.card {
  width: 100%;
  max-width: 380px;
  padding: 36px 32px 28px;
  box-sizing: border-box;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--surface);
}
h1 {
  margin: 0;
  font-size: 24px;
  line-height: 1.3;
}
.subtitle {
  margin: 4px 0 24px;
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
