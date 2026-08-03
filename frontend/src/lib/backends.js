const STORAGE_KEY = 'echomind.frontend.settings'

const DEFAULT_BACKEND = {
  id: 'python',
  label: 'Python',
  baseUrl: import.meta.env.VITE_PYTHON_API_URL || '/api/python',
  port: '8000'
}

export function createInitialSettings() {
  const saved = readSettings()
  return {
    backend: 'python',
    userId: saved.userId || 'u1001',
    conversationId: saved.conversationId || '',
    endpoints: {
      python: saved.endpoints?.python || DEFAULT_BACKEND.baseUrl
    }
  }
}

export function saveSettings(settings) {
  const normalized = {
    ...settings,
    backend: 'python',
    endpoints: {
      python: settings.endpoints?.python || DEFAULT_BACKEND.baseUrl
    }
  }
  localStorage.setItem(STORAGE_KEY, JSON.stringify(normalized))
}

export function backendMeta(_type, settings) {
  return {
    ...DEFAULT_BACKEND,
    baseUrl: normalizeBaseUrl(settings.endpoints?.python || DEFAULT_BACKEND.baseUrl)
  }
}

export async function requestHealth(_type, settings) {
  return requestJson(backendMeta('python', settings).baseUrl, '/health')
}

export async function requestMonitor(_type, settings) {
  return requestJson(backendMeta('python', settings).baseUrl, '/monitor')
}

export async function requestKnowledgeStats(_type, settings) {
  return requestJson(backendMeta('python', settings).baseUrl, '/knowledge/stats')
}

export async function requestSearch(_type, settings, query, topK = 5) {
  const params = new URLSearchParams({
    query,
    top_k: String(topK)
  })
  return requestJson(backendMeta('python', settings).baseUrl, `/search?${params}`, {
    method: 'POST'
  })
}

export async function requestChat(_type, settings, message) {
  const payload = {
    message,
    user_id: settings.userId || 'anonymous',
    conv_id: settings.conversationId || undefined
  }

  const raw = await requestJson(backendMeta('python', settings).baseUrl, '/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  })

  return normalizeChatResponse(raw)
}

export async function addKnowledge(_type, settings, documents) {
  return requestJson(backendMeta('python', settings).baseUrl, '/knowledge/add', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ documents })
  })
}

export async function uploadKnowledge(_type, settings, file) {
  const form = new FormData()
  form.append('file', file)
  return requestJson(backendMeta('python', settings).baseUrl, '/knowledge/upload', {
    method: 'POST',
    body: form
  })
}

function normalizeChatResponse(raw) {
  return {
    backend: 'python',
    conversationId: raw.conv_id || '',
    response: raw.response || '',
    intent: raw.intent || 'other',
    agentType: raw.agent_type || '',
    escalated: Boolean(raw.escalated),
    latencyMs: Number(raw.latency_ms ?? 0),
    knowledgeUsed: Boolean(raw.knowledge_used),
    verified: raw.verified,
    grounded: raw.grounded,
    raw
  }
}

async function requestJson(baseUrl, path, options = {}) {
  const url = `${normalizeBaseUrl(baseUrl)}${path}`
  const response = await fetch(url, options)
  const text = await response.text()

  let data = null
  try {
    data = text ? JSON.parse(text) : null
  } catch {
    data = text
  }

  if (!response.ok) {
    const detail = typeof data === 'string' ? data : JSON.stringify(data)
    throw new Error(`${response.status} ${response.statusText}: ${detail}`)
  }

  return data
}

function normalizeBaseUrl(value) {
  return String(value || '').replace(/\/+$/, '')
}

function readSettings() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}')
  } catch {
    return {}
  }
}
