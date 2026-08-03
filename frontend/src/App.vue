<template>
  <main class="app-shell">
    <aside class="sidebar">
      <section class="brand">
        <div class="brand-mark">EM</div>
        <div>
          <h1>EchoMind Console</h1>
          <p>EchoMind Python 智能客服后端</p>
        </div>
      </section>


      <section class="panel">
        <div class="panel-heading">
          <h2>后端</h2>
          <span class="pill">{{ currentBackend.label }}</span>
        </div>

        <label>
          <span>Python API</span>
          <input v-model="settings.endpoints.python" @change="persist" placeholder="/api/python" />
        </label>
        <label>
          <span>用户 ID</span>
          <input v-model="settings.userId" @change="persist" placeholder="u1001" />
        </label>
        <label>
          <span>会话 ID</span>
          <input v-model="settings.conversationId" @change="persist" placeholder="自动生成" />
        </label>

        <div class="actions">
          <button @click="checkHealth">健康检查</button>
          <button @click="loadStats">刷新状态</button>
        </div>
      </section>

      <section class="panel status-panel">
        <div class="panel-heading">
          <h2>状态</h2>
          <span :class="['status-dot', healthOk ? 'online' : 'offline']"></span>
        </div>
        <dl>
          <div>
            <dt>当前后端</dt>
            <dd>{{ currentBackend.label }}</dd>
          </div>
          <div>
            <dt>健康状态</dt>
            <dd :class="healthOk ? 'ok' : 'muted'">{{ healthLabel }}</dd>
          </div>
          <div>
            <dt>知识片段</dt>
            <dd>{{ knowledgeCount }}</dd>
          </div>
        </dl>
        <pre v-if="statusText">{{ statusText }}</pre>
      </section>
    </aside>

    <section class="workspace">
      <header class="workspace-header">
        <div>
          <span class="eyebrow">EchoMind Workspace</span>
          <h2>对话调试</h2>
          <p>{{ currentBackend.baseUrl }}</p>
        </div>
        <div class="header-actions">
          <a :href="docsUrl" target="_blank" rel="noreferrer">API 文档</a>
        </div>
      </header>

      <section class="chat-panel">
        <div class="messages" ref="messageList">
          <article v-for="item in messages" :key="item.id" :class="['message', item.role]">
            <div class="message-meta">
              <span>{{ item.role === 'user' ? '用户' : currentBackend.label }}</span>
              <small v-if="item.meta">{{ item.meta }}</small>
            </div>
            <p>{{ item.content }}</p>
          </article>
          <div v-if="messages.length === 0" class="empty-state">
            <h3>开始一次客服对话</h3>
            <p>当前连接 EchoMind Python 后端，可用于调试智能客服对话、知识库与监控接口。</p>
          </div>
        </div>

        <form class="composer" @submit.prevent="sendMessage">
          <textarea v-model="draft" rows="3" placeholder="输入问题，例如：我想申请退款，订单号是 #12345"></textarea>
          <button :disabled="busy || !draft.trim()">{{ busy ? '发送中' : '发送' }}</button>
        </form>
      </section>

      <section class="tools-grid">
        <article class="tool-panel">
          <div class="panel-heading">
            <h2>知识库检索</h2>
            <span class="pill soft">RAG</span>
          </div>
          <div class="inline-form">
            <input v-model="searchQuery" placeholder="退款多久能到账" />
            <button @click="searchKnowledge" :disabled="busy || !searchQuery.trim()">检索</button>
          </div>
          <div class="result-list">
            <article v-for="item in searchResults" :key="item.id || item.title" class="result-item">
              <strong>{{ item.title || '未命名结果' }}</strong>
              <span>score {{ item.score ?? '-' }}</span>
              <p>{{ item.content }}</p>
            </article>
          </div>
        </article>

        <article class="tool-panel">
          <div class="panel-heading">
            <h2>导入知识</h2>
            <span class="pill soft">Docs</span>
          </div>
          <label>
            <span>标题</span>
            <input v-model="docTitle" placeholder="退款补充政策" />
          </label>
          <label>
            <span>内容</span>
            <textarea v-model="docContent" rows="5" placeholder="输入知识库内容"></textarea>
          </label>
          <div class="actions">
            <button @click="submitKnowledge" :disabled="busy || !docTitle.trim() || !docContent.trim()">添加文档</button>
            <label class="file-button">
              上传文件
              <input type="file" accept=".txt,.md,.json" @change="handleUpload" />
            </label>
          </div>
        </article>
      </section>
    </section>
  </main>
</template>

<script setup>
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import {
  addKnowledge,
  backendMeta,
  createInitialSettings,
  requestChat,
  requestHealth,
  requestKnowledgeStats,
  requestMonitor,
  requestSearch,
  saveSettings,
  uploadKnowledge
} from './lib/backends'

const settings = reactive(createInitialSettings())
settings.backend = 'python'
settings.endpoints.python = settings.endpoints.python || '/api/python'
saveSettings(settings)
const messages = ref([])
const draft = ref('')
const busy = ref(false)
const healthOk = ref(false)
const healthLabel = ref('未检查')
const statusText = ref('')
const knowledgeCount = ref('-')
const searchQuery = ref('退款多久能到账')
const searchResults = ref([])
const docTitle = ref('退款补充政策')
const docContent = ref('大促期间退款审核时间可能延长到 3-5 个工作日。')
const messageList = ref(null)

const currentBackend = computed(() => backendMeta(settings.backend, settings))
const docsUrl = computed(() => `${currentBackend.value.baseUrl}/docs`)

watch(
  () => settings.conversationId,
  () => persist()
)

onMounted(() => {
  checkHealth()
  loadStats()
})

function createId() {
  if (globalThis.crypto?.randomUUID) {
    return globalThis.crypto.randomUUID()
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

function switchBackend(type) {
  settings.backend = type
  persist()
  healthOk.value = false
  healthLabel.value = '未检查'
  statusText.value = ''
  searchResults.value = []
  checkHealth()
}

function persist() {
  saveSettings(settings)
}

async function sendMessage() {
  const content = draft.value.trim()
  if (!content) return
  messages.value.push({ id: createId(), role: 'user', content })
  draft.value = ''
  busy.value = true
  try {
    const response = await requestChat(settings.backend, settings, content)
    if (response.conversationId && !settings.conversationId) {
      settings.conversationId = response.conversationId
      persist()
    }
    const meta = [
      response.intent,
      response.agentType,
      response.knowledgeUsed ? 'RAG' : '',
      response.escalated ? '转人工' : ''
    ].filter(Boolean).join(' · ')
    messages.value.push({
      id: createId(),
      role: 'assistant',
      content: response.response,
      meta
    })
  } catch (error) {
    messages.value.push({
      id: createId(),
      role: 'assistant',
      content: error.message,
      meta: '请求失败'
    })
  } finally {
    busy.value = false
    await nextTick()
    messageList.value?.scrollTo({ top: messageList.value.scrollHeight, behavior: 'smooth' })
  }
}

async function checkHealth() {
  try {
    const data = await requestHealth(settings.backend, settings)
    healthOk.value = data.status === 'ok'
    healthLabel.value = data.status || 'ok'
    statusText.value = JSON.stringify(data, null, 2)
  } catch (error) {
    healthOk.value = false
    healthLabel.value = '不可用'
    statusText.value = error.message
  }
}

async function loadStats() {
  try {
    const [stats, monitor] = await Promise.allSettled([
      requestKnowledgeStats(settings.backend, settings),
      requestMonitor(settings.backend, settings)
    ])
    if (stats.status === 'fulfilled') {
      knowledgeCount.value = stats.value.total_chunks ?? stats.value.totalChunks ?? '-'
    }
    if (monitor.status === 'fulfilled') {
      statusText.value = JSON.stringify(monitor.value, null, 2)
    }
  } catch (error) {
    statusText.value = error.message
  }
}

async function searchKnowledge() {
  busy.value = true
  try {
    const data = await requestSearch(settings.backend, settings, searchQuery.value, 5)
    searchResults.value = data.results || []
  } catch (error) {
    statusText.value = error.message
  } finally {
    busy.value = false
  }
}

async function submitKnowledge() {
  busy.value = true
  try {
    const data = await addKnowledge(settings.backend, settings, [
      { title: docTitle.value.trim(), content: docContent.value.trim() }
    ])
    statusText.value = JSON.stringify(data, null, 2)
    await loadStats()
  } catch (error) {
    statusText.value = error.message
  } finally {
    busy.value = false
  }
}

async function handleUpload(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  busy.value = true
  try {
    const data = await uploadKnowledge(settings.backend, settings, file)
    statusText.value = JSON.stringify(data, null, 2)
    await loadStats()
  } catch (error) {
    statusText.value = error.message
  } finally {
    busy.value = false
  }
}
</script>
