<script setup lang="ts">
import { Plus, Promotion, SwitchButton } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { api, ApiError, streamChat, type ChatMessage, type ConversationSummary } from '../api'
import { currentUser, setUser } from '../auth'
import { renderMarkdown } from '../markdown'

const route = useRoute()
const router = useRouter()

const conversations = ref<ConversationSummary[]>([])
const currentId = ref<string | null>(null)
const messages = ref<ChatMessage[]>([])
const input = ref('')
const streaming = ref(false)
const status = ref('')
const scroller = ref<HTMLElement>()
let controller: AbortController | null = null

// 首版要支持的五类问题，各给一个示例，点一下直接提问
const examples = [
  { type: '个股分析', text: '从基本面和估值角度分析一下贵州茅台' },
  { type: '财报解读', text: '解读宁德时代最近一期财报的要点' },
  { type: '行情查询', text: '比亚迪现在的股价和今天的涨跌幅是多少' },
  { type: '条件选股', text: '筛选市盈率低于 15、近三年 ROE 都高于 15% 的股票' },
  { type: '政策与新闻', text: '今天有哪些影响 A 股的重要政策和新闻' },
]

function goLogin(): void {
  setUser(null)
  router.replace({ name: 'login', query: { redirect: route.fullPath } })
}

/** 统一处理接口错误：登录失效就回登录页，其余弹出提示。 */
function handleError(e: unknown): void {
  if (e instanceof ApiError && e.status === 401) goLogin()
  else ElMessage.error(e instanceof Error ? e.message : '操作失败，请重试')
}

async function loadConversations(): Promise<void> {
  try {
    conversations.value = await api.listConversations()
  } catch (e) {
    handleError(e)
  }
}

function scrollToBottom(force = false): void {
  const el = scroller.value
  if (!el) return
  // 用户往上翻看历史时不打扰；只有本来就在底部附近才跟随新内容
  const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 120
  if (force || nearBottom) nextTick(() => (el.scrollTop = el.scrollHeight))
}

async function openConversation(id: string | undefined): Promise<void> {
  if (!id) {
    currentId.value = null
    messages.value = []
    return
  }
  try {
    const detail = await api.getConversation(id)
    currentId.value = id
    messages.value = detail.messages
    scrollToBottom(true)
  } catch (e) {
    // 会话不存在或不属于当前用户时，后端的提示会原样显示，然后回到新对话
    handleError(e)
    if (!(e instanceof ApiError && e.status === 401)) router.replace('/')
  }
}

watch(
  () => route.params.id as string | undefined,
  (id) => {
    // 新会话拿到 id 后会改写网址，此时内容已在页面上，不需要重新加载，更不能打断回答
    if (id && id === currentId.value) return
    controller?.abort()
    openConversation(id)
  },
  { immediate: true },
)

async function send(text = input.value): Promise<void> {
  const content = text.trim()
  if (!content || streaming.value) return
  input.value = ''
  messages.value.push({ role: 'user', content }, { role: 'assistant', content: '' })
  const reply = messages.value[messages.value.length - 1]
  streaming.value = true
  status.value = '正在发送…'
  controller = new AbortController()
  const { signal } = controller
  scrollToBottom(true)

  try {
    await streamChat(
      { conversation_id: currentId.value, content },
      ({ event, data }) => {
        if (event === 'meta') {
          if (!currentId.value) {
            currentId.value = data.conversation_id
            conversations.value.unshift({
              id: data.conversation_id,
              title: data.title,
              updated_at: new Date().toISOString(),
            })
            router.replace(`/c/${data.conversation_id}`)
          }
        } else if (event === 'status') {
          status.value = data.text
        } else if (event === 'delta') {
          status.value = ''
          reply.content += data.text
          scrollToBottom()
        } else if (event === 'error') {
          reply.failed = true
          if (!reply.content) reply.content = data.message
          else ElMessage.error(data.message)
        }
      },
      signal,
    )
  } catch (e) {
    if (!signal.aborted) {
      reply.failed = true
      if (!reply.content) reply.content = e instanceof Error ? e.message : '发送失败，请重试'
      if (e instanceof ApiError && e.status === 401) goLogin()
    }
  } finally {
    if (signal.aborted && !reply.content) reply.content = '（已停止）'
    streaming.value = false
    status.value = ''
    controller = null
    loadConversations()
  }
}

function onEnter(e: Event): void {
  const ke = e as KeyboardEvent
  // 回车发送，Shift+回车换行；输入法选字时的回车不算
  if (ke.shiftKey || ke.isComposing) return
  ke.preventDefault()
  send()
}

async function logout(): Promise<void> {
  controller?.abort()
  try {
    await api.logout()
  } finally {
    setUser(null)
    router.replace({ name: 'login' })
  }
}

onMounted(loadConversations)
onBeforeUnmount(() => controller?.abort())
</script>

<template>
  <div class="layout">
    <aside class="sidebar">
      <div class="brand">A股投研助手</div>
      <el-button class="new-chat" :icon="Plus" @click="router.push('/')">新对话</el-button>

      <nav class="history">
        <p v-if="!conversations.length" class="history-empty">还没有历史对话</p>
        <router-link
          v-for="c in conversations"
          :key="c.id"
          :to="`/c/${c.id}`"
          class="history-item"
          :class="{ active: c.id === currentId }"
          :title="c.title"
        >
          {{ c.title }}
        </router-link>
      </nav>

      <div class="account">
        <span class="username" :title="currentUser?.username">{{ currentUser?.username }}</span>
        <el-button text :icon="SwitchButton" @click="logout">退出</el-button>
      </div>
    </aside>

    <main class="main">
      <div ref="scroller" class="scroller">
        <div class="column">
          <section v-if="!messages.length" class="welcome">
            <h1>想了解哪只股票？</h1>
            <p>可以直接提问，或从下面的示例开始。</p>
            <div class="examples">
              <button v-for="ex in examples" :key="ex.type" type="button" @click="send(ex.text)">
                <span class="example-type">{{ ex.type }}</span>
                <span>{{ ex.text }}</span>
              </button>
            </div>
          </section>

          <template v-for="(m, i) in messages" :key="i">
            <div v-if="m.role === 'user'" class="message user">
              <div class="bubble">{{ m.content }}</div>
            </div>
            <div v-else class="message assistant" :class="{ failed: m.failed }">
              <!-- 最后一条回答还没出字时，显示当前状态（发送中、排队、思考） -->
              <p v-if="!m.content && streaming && i === messages.length - 1" class="status">
                <span class="dot" />{{ status || '正在思考…' }}
              </p>
              <!-- renderMarkdown 的输出已经过净化，可以安全插入 -->
              <div v-else class="markdown" v-html="renderMarkdown(m.content)" />
            </div>
          </template>
        </div>
      </div>

      <footer class="composer">
        <div class="column">
          <div class="input-row">
            <el-input
              v-model="input"
              type="textarea"
              resize="none"
              :autosize="{ minRows: 1, maxRows: 6 }"
              :maxlength="4000"
              placeholder="输入问题，回车发送，Shift + 回车换行"
              @keydown.enter="onEnter"
            />
            <el-button v-if="streaming" class="action" @click="controller?.abort()">停止</el-button>
            <el-button
              v-else
              class="action"
              type="primary"
              :icon="Promotion"
              :disabled="!input.trim()"
              @click="send()"
            >
              发送
            </el-button>
          </div>
          <p class="disclaimer">内容由 AI 生成，仅供内部研究参考，不构成投资建议。</p>
        </div>
      </footer>
    </main>
  </div>
</template>

<style scoped>
.layout {
  display: flex;
  height: 100%;
  min-width: 720px;
}

/* 左侧：历史会话 */
.sidebar {
  display: flex;
  flex-direction: column;
  width: 260px;
  flex-shrink: 0;
  padding: 16px 12px 12px;
  box-sizing: border-box;
  border-right: 1px solid var(--line);
  background: var(--surface-alt);
}
.brand {
  padding: 0 8px 14px;
  font-size: 17px;
  font-weight: 600;
}
.new-chat {
  width: 100%;
  margin-bottom: 12px;
}
.history {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}
.history-empty {
  margin: 12px 8px;
  color: var(--text-muted);
  font-size: 13px;
}
.history-item {
  display: block;
  padding: 7px 10px;
  border-radius: 6px;
  color: var(--text);
  font-size: 14px;
  text-decoration: none;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.history-item:hover {
  background: #eceef3;
}
.history-item.active {
  background: var(--brand-soft);
  color: var(--brand);
  font-weight: 500;
}
.account {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 10px 0 0 8px;
  border-top: 1px solid var(--line);
}
.username {
  min-width: 0;
  font-size: 14px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 右侧：对话 */
.main {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-width: 0;
}
.scroller {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}
.column {
  max-width: 820px;
  margin: 0 auto;
  padding: 0 24px;
}
.scroller .column {
  padding-top: 28px;
  padding-bottom: 16px;
}

.welcome {
  padding-top: 10vh;
}
.welcome h1 {
  margin: 0;
  font-size: 26px;
  line-height: 1.3;
}
.welcome p {
  margin: 6px 0 24px;
  color: var(--text-muted);
}
.examples {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}
.examples button {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 12px 14px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--surface);
  color: var(--text);
  font: inherit;
  font-size: 14px;
  line-height: 1.5;
  text-align: left;
  cursor: pointer;
}
.examples button:hover {
  border-color: var(--brand);
  background: var(--brand-soft);
}
.example-type {
  color: var(--text-muted);
  font-size: 12px;
}

.message {
  margin-bottom: 22px;
}
.message.user {
  display: flex;
  justify-content: flex-end;
}
.bubble {
  max-width: 80%;
  padding: 9px 14px;
  border-radius: 12px;
  background: var(--brand-soft);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.message.assistant {
  overflow-wrap: anywhere;
}
.message.failed {
  color: var(--danger);
}
.status {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  color: var(--text-muted);
}
.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--brand);
  animation: pulse 1.2s ease-in-out infinite;
}
@keyframes pulse {
  0%,
  100% {
    opacity: 0.25;
  }
  50% {
    opacity: 1;
  }
}

.composer {
  padding: 12px 0 10px;
  border-top: 1px solid var(--line);
}
.input-row {
  display: flex;
  align-items: flex-end;
  gap: 10px;
}
.input-row :deep(.el-textarea__inner) {
  padding: 9px 12px;
  font-size: 15px;
  line-height: 1.6;
}
.action {
  height: 42px;
  flex-shrink: 0;
}
.disclaimer {
  margin: 8px 0 0;
  color: var(--text-muted);
  font-size: 12px;
  text-align: center;
}
</style>
