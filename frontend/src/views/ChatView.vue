<script setup lang="ts">
import {
  DataAnalysis,
  DocumentCopy,
  Filter,
  MoreFilled,
  Notebook,
  Plus,
  Promotion,
  Reading,
  Search,
  TrendCharts,
  Wallet,
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { api, ApiError, streamChat, type ChatMessage, type ConversationSummary } from '../api'
import { currentUser, setUser } from '../auth'
import BrandMark from '../components/BrandMark.vue'
import DataTable from '../components/DataTable.vue'
import KlineChart from '../components/KlineChart.vue'
import MarketPanel from '../components/MarketPanel.vue'
import QuoteCard from '../components/QuoteCard.vue'
import { renderMarkdown } from '../markdown'

const route = useRoute()
const router = useRouter()

const conversations = ref<ConversationSummary[]>([])
const keyword = ref('')
const currentId = ref<string | null>(null)
const messages = ref<ChatMessage[]>([])
const input = ref('')
const streaming = ref(false)
const status = ref('')
const scroller = ref<HTMLElement>()
let controller: AbortController | null = null

// 首页的能力卡片：点一下直接用示例提问。条件选股尚未上线，只展示不可点
const abilities = [
  { icon: TrendCharts, name: '行情查询', desc: '最新价、涨跌幅、成交，数据到秒', ask: '比亚迪现在的股价和今天的涨跌幅是多少' },
  { icon: DataAnalysis, name: 'K 线走势', desc: '分钟、日、周、月线与均线解读', ask: '看一下宁德时代的日K线，分析近期走势' },
  { icon: Wallet, name: '财报解读', desc: '营收、利润、毛利率、ROE 逐期对比', ask: '解读一下贵州茅台最近的财报' },
  { icon: Notebook, name: '个股分析', desc: '行情、财务、新闻多维度综合', ask: '从基本面和走势两方面分析一下比亚迪' },
  { icon: Reading, name: '政策与新闻', desc: '部委官网原文与财经快讯', ask: '今天有哪些影响 A 股的重要政策和新闻' },
  { icon: Filter, name: '条件选股', desc: '按估值、财务、行情、技术、行业概念筛选', ask: '筛选市盈率低于 15、近三年 ROE 都高于 15% 的股票' },
]

const greeting = computed(() => {
  // 按北京时间问候，和行情时间保持一致，不随用户电脑的时区变化
  const hour = (new Date().getUTCHours() + 8) % 24
  const part = hour < 6 ? '夜深了' : hour < 12 ? '上午好' : hour < 18 ? '下午好' : '晚上好'
  return `${part}，${currentUser.value?.username ?? ''}`
})

/** 复制回答原文。页面可能通过 http 访问，那时浏览器不提供剪贴板接口，退回到旧办法。 */
async function copyText(text: string): Promise<void> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text)
    } else {
      const area = document.createElement('textarea')
      area.value = text
      area.style.position = 'fixed'
      area.style.opacity = '0'
      document.body.appendChild(area)
      area.select()
      const ok = document.execCommand('copy')
      area.remove()
      if (!ok) throw new Error('copy failed')
    }
    ElMessage.success('已复制')
  } catch {
    ElMessage.error('复制失败，请手动选择文字复制')
  }
}

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
  const asked = keyword.value.trim()
  try {
    const list = await api.listConversations(asked)
    // 输入得快时，先发的请求可能后返回；只采用与当前关键词一致的结果
    if (asked === keyword.value.trim()) conversations.value = list
  } catch (e) {
    handleError(e)
  }
}

// 停止输入 300 毫秒后再搜索，不必每敲一个字就请求一次
let searchTimer: ReturnType<typeof setTimeout> | undefined
watch(keyword, () => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(loadConversations, 300)
})

async function rename(c: ConversationSummary): Promise<void> {
  let title: string
  try {
    const result = await ElMessageBox.prompt('', '重命名会话', {
      inputValue: c.title,
      inputValidator: (v) => {
        const length = (v ?? '').trim().length
        return (length >= 1 && length <= 100) || '名称需要 1 到 100 个字'
      },
      confirmButtonText: '保存',
      cancelButtonText: '取消',
    })
    title = result.value.trim()
  } catch {
    return // 用户取消
  }
  try {
    c.title = (await api.renameConversation(c.id, title)).title
  } catch (e) {
    handleError(e)
  }
}

async function remove(c: ConversationSummary): Promise<void> {
  try {
    await ElMessageBox.confirm(`删除后无法恢复：${c.title}`, '删除会话', {
      type: 'warning',
      confirmButtonText: '删除',
      confirmButtonClass: 'el-button--danger',
      cancelButtonText: '取消',
    })
  } catch {
    return // 用户取消
  }
  try {
    await api.deleteConversation(c.id)
    conversations.value = conversations.value.filter((x) => x.id !== c.id)
    if (c.id === currentId.value) {
      // 正在看的会话被删了：停掉还在生成的回答，回到新对话
      controller?.abort()
      router.replace('/chat')
    }
  } catch (e) {
    handleError(e)
  }
}

function onCommand(command: string, c: ConversationSummary): void {
  if (command === 'rename') rename(c)
  else if (command === 'delete') remove(c)
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
    if (!(e instanceof ApiError && e.status === 401)) router.replace('/chat')
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
            // 搜索中的列表只放匹配项，新会话等回答结束后重新查询再决定是否出现
            if (!keyword.value.trim()) {
              conversations.value.unshift({
                id: data.conversation_id,
                title: data.title,
                updated_at: new Date().toISOString(),
              })
            }
            router.replace(`/c/${data.conversation_id}`)
          }
        } else if (event === 'status') {
          status.value = data.text
        } else if (event === 'delta') {
          status.value = ''
          reply.content += data.text
          scrollToBottom()
        } else if (event === 'block') {
          ;(reply.blocks ??= []).push(data)
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
    if (signal.aborted && !reply.content && !reply.blocks?.length) reply.content = '（已停止）'
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


onMounted(() => {
  loadConversations()
  // 从概览页或指数详情带着问题跳过来：自动提问，并把问题从网址里去掉，刷新时不会重复提问
  const q = route.query.q
  if (route.name === 'new-chat' && typeof q === 'string' && q.trim()) {
    router.replace({ name: 'new-chat' })
    send(q)
  }
})
onBeforeUnmount(() => {
  controller?.abort()
  clearTimeout(searchTimer)
})
</script>

<template>
  <div class="layout">
    <div class="body">
      <aside class="sidebar">
        <el-button class="new-chat" type="primary" :icon="Plus" @click="router.push('/chat')">
          新对话
        </el-button>
        <el-input
          v-model="keyword"
          class="search"
          :prefix-icon="Search"
          placeholder="搜索标题或内容"
          maxlength="100"
          clearable
        />

        <div class="history-label">历史对话</div>
        <nav class="history">
          <p v-if="!conversations.length" class="history-empty">
            {{ keyword.trim() ? '没有找到相关对话' : '还没有历史对话' }}
          </p>
          <div
            v-for="c in conversations"
            :key="c.id"
            class="history-item"
            :class="{ active: c.id === currentId }"
          >
            <router-link :to="`/c/${c.id}`" class="history-title" :title="c.title">
              {{ c.title }}
            </router-link>
            <el-dropdown trigger="click" @command="(cmd: string) => onCommand(cmd, c)">
              <button type="button" class="history-more" :aria-label="`${c.title} 的更多操作`">
                <el-icon><MoreFilled /></el-icon>
              </button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="rename">重命名</el-dropdown-item>
                  <el-dropdown-item command="delete" class="danger-item">删除</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </nav>
        <p class="sidebar-foot">会话在最后一次对话 30 天后自动删除</p>
      </aside>

      <main class="main">
        <div ref="scroller" class="scroller">
          <div class="column">
            <section v-if="!messages.length" class="welcome">
              <p class="greeting">{{ greeting }}</p>
              <h1>今天想研究什么？</h1>
              <p class="lead">行情、K 线、财报、新闻与官方政策均取自实时数据，并附来源链接。</p>
              <div class="abilities">
                <button
                  v-for="a in abilities"
                  :key="a.name"
                  type="button"
                  :disabled="!a.ask"
                  @click="send(a.ask)"
                >
                  <span class="ability-icon"><el-icon><component :is="a.icon" /></el-icon></span>
                  <span class="ability-name">
                    {{ a.name }}
                    <span v-if="!a.ask" class="soon">即将上线</span>
                  </span>
                  <span class="ability-desc">{{ a.desc }}</span>
                  <span v-if="a.ask" class="ability-ask">“{{ a.ask }}”</span>
                </button>
              </div>
            </section>

            <template v-for="(m, i) in messages" :key="i">
              <div v-if="m.role === 'user'" class="message user">
                <div class="bubble">{{ m.content }}</div>
              </div>
              <div v-else class="message assistant" :class="{ failed: m.failed }">
                <div class="assistant-head">
                  <BrandMark :size="18" />投研助手
                  <button
                    v-if="m.content && !(streaming && i === messages.length - 1)"
                    type="button"
                    class="copy"
                    @click="copyText(m.content)"
                  >
                    <el-icon><DocumentCopy /></el-icon>复制
                  </button>
                </div>
                <template v-for="(block, bi) in m.blocks ?? []" :key="bi">
                  <QuoteCard v-if="block.type === 'quote'" :block="block" />
                  <KlineChart v-else-if="block.type === 'kline'" :block="block" />
                  <DataTable v-else-if="block.type === 'table'" :block="block" />
                </template>
                <!-- renderMarkdown 的输出已经过净化，可以安全插入 -->
                <div v-if="m.content" class="markdown" v-html="renderMarkdown(m.content)" />
                <!-- 最后一条回答在等待时显示当前状态：发送中、排队、思考、查询数据 -->
                <p
                  v-if="streaming && i === messages.length - 1 && (status || !m.content)"
                  class="status"
                >
                  <span class="dot" />{{ status || '正在思考…' }}
                </p>
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
                placeholder="输入股票名称、代码或问题，回车发送，Shift + 回车换行"
                @keydown.enter="onEnter"
              />
              <el-button v-if="streaming" class="action" @click="controller?.abort()">
                停止
              </el-button>
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

      <!-- 右侧市场看板；点"AI 解读"直接就这条内容提问 -->
      <MarketPanel class="board" @ask="send" />
    </div>
  </div>
</template>

<style scoped>
.layout {
  display: flex;
  flex-direction: column;
  height: 100%;
}
.body {
  display: flex;
  flex: 1;
  min-height: 0;
}

/* 左侧：历史会话 */
.sidebar {
  display: flex;
  flex-direction: column;
  width: 248px;
  flex-shrink: 0;
  padding: 14px 12px 10px;
  box-sizing: border-box;
  border-right: 1px solid var(--line);
  background: var(--surface);
}
.new-chat {
  width: 100%;
  height: 36px;
  margin-bottom: 10px;
}
.search {
  margin-bottom: 14px;
}
.history-label {
  padding: 0 10px 6px;
  color: var(--text-muted);
  font-size: 12px;
  letter-spacing: 1px;
}
.history {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}
.history-empty {
  margin: 8px 10px;
  color: var(--text-muted);
  font-size: 13px;
}
.history-item {
  display: flex;
  align-items: center;
  margin-bottom: 1px;
  border-radius: 6px;
  font-size: 14px;
}
.history-title {
  flex: 1;
  min-width: 0;
  padding: 7px 4px 7px 10px;
  color: var(--text);
  text-decoration: none;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.history-more {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  margin-right: 4px;
  padding: 0;
  border: 0;
  border-radius: 4px;
  background: none;
  color: var(--text-muted);
  cursor: pointer;
  /* 平时隐藏，悬停、当前会话或键盘聚焦时出现 */
  opacity: 0;
}
.history-item:hover .history-more,
.history-item.active .history-more,
.history-more:focus-visible {
  opacity: 1;
}
.history-more:hover {
  background: rgba(11, 29, 51, 0.08);
  color: var(--text);
}
.history-item:hover {
  background: var(--surface-alt);
}
.history-item.active {
  background: var(--brand-soft);
  box-shadow: inset 2px 0 0 var(--brand);
}
.history-item.active .history-title {
  color: var(--brand);
  font-weight: 500;
}
.sidebar-foot {
  margin: 8px 10px 0;
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.5;
}

/* 中间：对话 */
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
  max-width: 860px;
  margin: 0 auto;
  padding: 0 24px;
}
.scroller .column {
  padding-top: 20px;
  padding-bottom: 16px;
}

/* 右侧看板：窗口不够宽时让位给对话 */
@media (max-width: 1240px) {
  .board {
    display: none;
  }
}

/* 首页工作台 */
.welcome {
  padding-top: 4vh;
}
.greeting {
  margin: 0 0 2px;
  color: var(--text-muted);
  font-size: 14px;
}
.welcome h1 {
  margin: 0;
  color: var(--navy);
  font-size: 26px;
  line-height: 1.3;
  letter-spacing: 0.5px;
}
.lead {
  margin: 6px 0 22px;
  color: var(--text-muted);
}
.abilities {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}
@media (max-width: 1040px) {
  .abilities {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
.abilities button {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 3px;
  padding: 14px 16px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
  color: var(--text);
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition:
    border-color 0.15s,
    box-shadow 0.15s;
}
.abilities button:hover:not(:disabled),
.abilities button:focus-visible {
  border-color: var(--brand);
  box-shadow: 0 4px 14px rgba(11, 29, 51, 0.08);
  outline: none;
}
.abilities button:disabled {
  background: transparent;
  cursor: default;
}
.ability-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  margin-bottom: 6px;
  border-radius: 8px;
  background: var(--brand-soft);
  color: var(--brand);
  font-size: 18px;
}
.ability-name {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--navy);
  font-size: 15px;
  font-weight: 600;
}
.soon {
  padding: 0 6px;
  border-radius: 3px;
  background: var(--surface-alt);
  color: var(--text-muted);
  font-size: 11px;
  font-weight: 400;
}
.ability-desc {
  color: var(--text-muted);
  font-size: 13px;
  line-height: 1.5;
}
.ability-ask {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed var(--line);
  width: 100%;
  color: var(--brand);
  font-size: 13px;
  line-height: 1.5;
}

.message {
  margin-bottom: 18px;
}
.message.user {
  display: flex;
  justify-content: flex-end;
}
.bubble {
  max-width: 80%;
  padding: 9px 14px;
  border-radius: 10px 10px 2px 10px;
  background: var(--navy);
  color: #fff;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
/* 回答做成一张"报告卡片" */
.message.assistant {
  padding: 14px 20px 18px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--surface);
  box-shadow: 0 1px 2px rgba(11, 29, 51, 0.04);
  overflow-wrap: anywhere;
}
.assistant-head {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-bottom: 12px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--line);
  color: var(--navy);
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.5px;
}
.copy {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-left: auto;
  padding: 2px 8px;
  border: 0;
  border-radius: 4px;
  background: none;
  color: var(--text-muted);
  font: inherit;
  font-size: 12px;
  font-weight: 400;
  letter-spacing: 0;
  cursor: pointer;
}
.copy:hover,
.copy:focus-visible {
  background: var(--surface-alt);
  color: var(--brand);
  outline: none;
}
.message.failed .markdown {
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
  background: var(--gold);
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
  padding: 4px 0 10px;
}
.input-row {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  padding: 8px 8px 8px 6px;
  border: 1px solid var(--line-strong);
  border-radius: 10px;
  background: var(--surface);
  box-shadow: 0 2px 12px rgba(11, 29, 51, 0.06);
  transition: border-color 0.15s;
}
.input-row:focus-within {
  border-color: var(--brand);
}
/* 输入框自身不再画边框，由外层容器统一画 */
.input-row :deep(.el-textarea__inner) {
  padding: 7px 10px;
  box-shadow: none;
  background: transparent;
  font-size: 15px;
  line-height: 1.6;
}
.action {
  height: 38px;
  flex-shrink: 0;
}
.disclaimer {
  margin: 8px 0 0;
  color: var(--text-muted);
  font-size: 12px;
  text-align: center;
}
</style>
