# EchoMind 企业级多Agent智能客服系统 — 项目讲解


## 1. 项目概述

**EchoMind** 是一个基于 **FastAPI + 大语言模型(LLM)+ 检索增强生成(RAG)+ 多级对话记忆** 构建的企业级智能客服 Agent 框架,面向行政、财务、IT、HR 等企业内部咨询场景,提供从对话接入、意图理解、知识检索、Agent 路由生成,到运行监控与效果评测的完整工程闭环。

区别于普通聊天 Demo,EchoMind 实现七大核心能力:

| # | 能力 | 说明 |
|---|------|------|
| 1 | **三路融合意图识别** | LLM 语义理解 + 本地 n-gram 向量兜底 + 关键词规则,加权投票合并 |
| 2 | **RAG 检索优化链路** | 查询改写 → 并行子查询召回 → 内容去重 → LLM 重排 → Top-K,并带缓存、校验、超时、熔断、降级 |
| 3 | **Redis + ChromaDB 三级记忆** | 工作记忆(Redis)+ 情景记忆(ChromaDB)+ 用户画像(ChromaDB) |
| 4 | **多Agent智能编排** | 通用 / 技术 / 账单三类 Agent,意图路由 + 复合问题并行协作 + 失败自动降级 |
| 5 | **热加载 Skills 技能** | 业务规则以 Markdown 编写,运行时注入 Agent 系统提示词,无需重启服务 |
| 6 | **在线监控闭环** | 周期性采集指标、Z-score 异常检测、对表现差的 Agent 自动追加路由惩罚、Prometheus 指标暴露 |
| 7 | **LLM-as-Judge 评测** | 批量意图评测 + 多轮对话仿真,按相关性/准确性/完整性/帮助性四维打分,与基线做回归检测 |

**技术栈:** Python 3.11/3.12 · FastAPI · asyncio · Anthropic SDK(兼容 DeepSeek 等第三方端点)· Redis · ChromaDB · Prometheus · Docker Compose · Nginx。

---

## 2. 总体架构

EchoMind 采用分层、事件驱动架构。一次 `POST /chat` 请求按固定流水线贯穿各层:

```
┌──────────────────────────────────────────────────────────────────────┐
│                         Client(HTTP / CLI)                           │
└──────────────────────────────────┬───────────────────────────────────┘
                                   │  POST /chat
┌──────────────────────────────────▼───────────────────────────────────┐
│  API 层(api/main.py — FastAPI)                                       │
│  lifespan 组件装配 · 路由 · 请求/响应模型 · CORS · 指标暴露            │
└──────────────────────────────────┬───────────────────────────────────┘
                                   │
        ┌──────────────────────────┼──────────────────────────┐
        ▼                          ▼                          ▼
┌───────────────┐        ┌──────────────────┐       ┌──────────────────┐
│ MemoryManager │        │  MCPToolManager  │       │ AgentOrchestrator│
│   (memory/)   │        │     (mcp/)       │       │   (agents/)      │
│               │        │                  │       │                  │
│ Redis 工作记忆 │        │ KnowledgeBase    │       │ IntentRecognizer │
│ Chroma 情景    │        │ (ChromaDB RAG)   │       │ General/Tech/    │
│ Chroma 画像    │        │ 查询改写·重排    │       │ Billing Agent    │
│               │        │ 熔断·缓存·降级   │       │ 路由·降级        │
└───────────────┘        └──────────────────┘       └────────┬─────────┘
                                                              │
                                                ┌─────────────▼─────────────┐
                                                │   SkillManager (core/)    │
                                                │   热加载 Markdown 规则    │
                                                └─────────────┬─────────────┘
                                                              │
                          ┌───────────────────────────────────┴──────────┐
                          ▼                                              ▼
                ┌──────────────────┐                          ┌──────────────────┐
                │ PerformanceMonitor│                          │  EndToEndEvaluator│
                │   (monitor/)      │                          │  (evaluation/)   │
                │ 采集·告警·惩罚    │  反馈闭环                 │ LLM-as-Judge     │
                │ penalty → 编排器  │ ───────────────────────▶ │ 回归检测         │
                └──────────────────┘                          └──────────────────┘
                          │
                ┌─────────▼─────────┐
                │   外部基础设施     │
                │ Redis · ChromaDB  │
                │ Prometheus · Nginx│
                └────────────────────┘
```

**架构原则:**

- **全异步 I/O**:LLM 调用、Redis、ChromaDB、HTTP 均通过 `asyncio` + `redis.asyncio` / `httpx` 以 `async/await` 方式执行。
- **lifespan 依赖注入**:全部全局组件在 FastAPI `lifespan` 上下文中构造一次,请求期间共享,关闭时统一回收。
- **反馈闭环**:监控模块读取请求处理期间产生的 Agent/工具统计,将路由惩罚写回编排器,无需额外埋点。
- **无外部 Embedding 模型依赖**:Embedding 全部在本地以字符 n-gram 哈希向量计算,系统不下载任何境外模型;LLM 端点可配置为任意 Anthropic 兼容 API(如 DeepSeek)。

---

## 3. 目录结构

```
EchoMind/
├── api/                        # FastAPI 入口:全部路由 /chat /eval /skills /monitor /knowledge /metrics
│   └── main.py
├── agents/                     # 多Agent实现
│   └── agent_orchestrator.py   # BaseAgent 子类 + AgentOrchestrator(路由/协作/降级)
├── core/                       # 通用核心模块
│   ├── intent_recognizer.py    # 三路融合意图识别
│   ├── skill_loader.py         # Skill 发现、解析、热加载、提示词注入
│   └── embedding_client.py     # (可选)远端 Embedding HTTP 客户端
├── memory/                     # 三级记忆
│   └── conversation_memory.py  # Redis 工作记忆 + Chroma 情景记忆 + 用户画像
├── mcp/                        # MCP 工具框架与 RAG 知识库(自研,非官方 MCP 协议)
│   ├── tool_manager.py         # 工具生命周期、查询改写、重排、熔断、缓存
│   └── knowledge_base.py       # ChromaDB 知识库 CRUD + 检索 handler
├── monitor/                    # 性能监控闭环
│   └── performance_monitor.py  # 指标采集、异常检测、路由惩罚
├── evaluation/                 # 端到端评测
│   └── evaluator.py            # LLMJudge、IntentEvaluator、EndToEndEvaluator
├── skills/                     # 生效中的业务技能(admin/finance/hr/it 四套 SKILL.md)
├── config/                     # 部署配置
│   ├── nginx/nginx.conf        # 反向代理 + 限流 + 安全头
│   └── prometheus.yml          # Prometheus 抓取配置
├── Dockerfile                  # 多阶段构建(base/dependencies/production/development)
├── docker-compose.yml          # 全栈编排(app + redis + chromadb + prometheus + nginx)
├── requirements.txt            # Python 依赖清单
└── .env.example                # 环境变量模板
```

---

## 4. 核心模块详解

### 4.1 API 层(`api/`)

**文件:** `api/main.py` — 唯一的 FastAPI 应用入口。

**职责:**

- **生命周期装配** — `lifespan` 异步上下文按固定顺序构造全部全局组件(顺序见 6.1 节):`IntentRecognizer` → `SkillManager`(加载 Skills)→ `AgentOrchestrator` → `MemoryManager` → `MCPToolManager` + `KnowledgeBase`(注册 `knowledge_search` 工具)→ `PerformanceMonitor`(启动后台采集循环)→ `EndToEndEvaluator`,关闭时停止监控循环。
- **路由暴露** — 提供 `/chat`、`/search`、`/knowledge/*`、`/skills/*`、`/monitor`、`/eval/run`、`/metrics`、`/health` 全部端点。
- **`/chat` 主流水线** — 按「记忆读取 → RAG 知识上下文 → 编排请求 → Agent 执行 → 记忆写入 → 异步画像更新」的固定顺序处理单次请求。
- **交互式 CLI** — `_cli()` 协程,通过 `python -m api.main --cli` 启动,用于本地免 HTTP 联调;CLI 的记忆读写与上下文拼接逻辑与 `/chat` 主链路一致。

**关键函数:**

| 函数 | 作用 |
|------|------|
| `_anthropic_cfg()` | 读取 `ANTHROPIC_API_KEY` / `ANTHROPIC_BASE_URL` / `ANTHROPIC_MODEL` 组装 LLM 配置;缺少 API Key 直接抛 `RuntimeError` |
| `_build_knowledge_context(message, top_k=3)` | 调用 `MCPToolManager.search_with_rewrite("knowledge_search", ...)`,将检索结果拼成 `[知识库检索结果]` 文本块注入 Agent 上下文;命中结果正文截断 600 字符 |
| `_should_use_knowledge(message)` | 寒暄整句命中(`你好/您好/嗨/hi/hello/hey/早上好/晚上好`)跳过 RAG;消息长度 ≥ 4 或命中业务关键词(退款/订单/物流/发票/登录/报错/崩溃/refund/order/error 等共 24 个)才触发检索 |

### 4.2 多Agent编排(`agents/`)

**文件:** `agents/agent_orchestrator.py` — 三层路由策略与并行协作。

**数据结构:**

- `AgentType`(Enum):`GENERAL` / `TECHNICAL` / `BILLING` / `ESCALATION`。
- `AgentStats`:单 Agent 运行时计数(`total`、`success`、`total_ms`、`monitor_penalty`),派生 `success_rate`、`avg_ms` 与 `routing_score()`。
- `Request` / `AgentResponse` / `OrchestratorResult`:贯穿流水线的数据类。

**Agent 类:**

- `BaseAgent`:封装 Anthropic LLM 调用、系统提示词构建(含 Skills 动态注入)、统计记账、升级关键词检测。LLM 调用 `max_tokens=1024`。
- `GeneralAgent`:通用客服;`TechnicalAgent`:故障诊断、报错排查、系统配置;`BillingAgent`:账单、退款、发票、订阅。

**AgentOrchestrator 关键方法:**

| 方法 | 作用 |
|------|------|
| `run(req)` | 主入口:意图识别(未预置时)→ 协作目标判断 → 路由 → 执行 → 升级判定 → 返回 `OrchestratorResult` |
| `run_parallel(req, agent_types)` | 复合问题时 `asyncio.gather` 并发调度多个 Agent,拼接成功响应 |
| `_route(intent, urgency)` | 三层路由:urgency 为 `CRITICAL` 直接转 `ESCALATION`,否则查 `_INTENT_ROUTING` 意图映射表,兜底 `GENERAL` |
| `_collaboration_targets(req)` | 基于「意图 + 领域关键词」检测复合问题(技术词:崩溃/报错/error/crash/无法登录/登录失败/500/401;账单词:退款/扣款/发票/账单/支付/订阅/refund/invoice) |
| `_best_agent(agent_type)` | 从池中挑选 `routing_score()` 最高的实例,支持水平扩展与按在线表现路由 |
| `_execute(req, agent_type)` | 执行选中的 Agent;专属 Agent 失败时降级为 `GeneralAgent` |
| `update_routing_penalties(penalties)` | 接收监控反馈,将每个 Agent 的 `monitor_penalty` 收敛到 `[0, 0.9]` |

**`_INTENT_ROUTING` 映射(静态):**

| 意图 | 路由到 Agent |
|------|-------------|
| `TECHNICAL` | `TECHNICAL` |
| `BILLING` / `ACCOUNT` | `BILLING` |
| `ESCALATION` | `ESCALATION` |
| `QUERY` / `COMPLAINT` / `GREETING` / `FEEDBACK` / `OTHER` 等 | `GENERAL` |

**`routing_score()` 公式:**

```
latency_score = 1.0 / (1.0 + avg_ms / 1000)
base_score    = success_rate * 0.7 + latency_score * 0.3
routing_score = base_score * max(0.0, 1.0 - monitor_penalty)
```

### 4.3 核心模块(`core/`)

#### 4.3.1 意图识别器(`core/intent_recognizer.py`)

**`IntentCategory` 枚举(10 类):** `QUERY` / `COMPLAINT` / `REQUEST` / `GREETING` / `ESCALATION` / `TECHNICAL` / `BILLING` / `ACCOUNT` / `FEEDBACK` / `OTHER`。

**`UrgencyLevel` 枚举(4 级):** `LOW=1` / `MEDIUM=2` / `HIGH=3` / `CRITICAL=4`。

**`IntentRecognizer` 三路融合策略:**

| 策略 | 权重 | 说明 |
|------|------|------|
| LLM 语义理解 | 70% | Few-shot 提示(每类取 1 条模板),结合最近 3 轮对话,要求 LLM 返回 JSON `{intent, confidence, reasoning}`;`max_tokens=256, temperature=0.1` |
| Embedding 相似度 | 20% | 消息向量与各类模板向量做余弦相似度取最高;`base_url` 非空(即使用 DeepSeek 等第三方端点)时**自动禁用**,因该类 API 通常无 embeddings 资源 |
| 关键词规则 | 10% | 零延迟关键词匹配,覆盖退款/升级/投诉/转人工等高频表达 |

- 当 Embedding 分支禁用时,投票权重自动变为 LLM 85% + 规则 15%。
- 投票结果置信度低于 `confidence_threshold=0.5` 时降级为 `OTHER`。
- 结果含 `intent`、`confidence`、`urgency`、提取实体、`reasoning`、`latency`。
- **LRU 缓存**:上限 1000 条,超限删除最旧 500 条;缓存键为清洗后消息前 200 字符。
- **`_local_embedding(text, dims=256)`**:确定性字符 1/2/3-gram 哈希向量 — 小写化 → 取 n-gram 去重集合 → 每个 token 以 `md5(token)` 前 4 字节大端取模定位索引、第 5 字节奇偶决定 `+1/-1` 符号,累加得 256 维向量。这是三路融合在无任何境外模型下载情况下保持可用的离线兜底。
- **`learn(message, correct)`**:在线学习 — 将人工纠正样本追加到对应类别模板(去重)并使该类别缓存向量失效,下次重新计算。

#### 4.3.2 技能加载器(`core/skill_loader.py`)

- `Skill` 数据类字段:`name` / `description` / `content` / `path` / `keywords` / `agents` / `enabled`。
- **文件发现规则**:优先 `SKILL.md`,其次 `.md/.txt/.json`;跳过点文件、`README.md`(大小写不敏感)及已被 `SKILL.md` 覆盖的目录。
- **front-matter 解析**:手写解析器(刻意不依赖 PyYAML),支持 `name` / `description` / `keywords` / `agents`(统一转小写)/ `enabled` 字段;`name` 缺失时以首个 `# 标题` 兜底,`SKILL.md` 再用父目录名兜底。
- **`matches(message, agent_type)` 注入判定**:
  - `enabled=False` → 不注入;
  - `agents` 非空且传入了 `agent_type` 且不包含该类型 → 不注入;
  - `keywords` 为空 → 全局注入;非空 → 消息小写后命中任一关键词子串才注入。
- **`prompt_for(message, agent_type)`**:聚合匹配到的 Skills 为提示词块,单块上限 `to_prompt_block(max_chars=3200)`,总量受 `max_prompt_chars`(默认 **5000**)预算约束,超限截断,预算耗尽即停止拼接,保护主上下文窗口。
- `load()` / `reload()`:扫描目录,单文件解析失败不阻塞其余文件;`summary()` 输出 `/skills` 端点用的可序列化状态。

#### 4.3.3 Embedding 客户端(`core/embedding_client.py`)

面向 DeepSeek `/embeddings` 端点的 `httpx` 异步客户端。当前版本由 `KnowledgeBase` 与 `MemoryManager` 实例化但**不实际调用**,两模块均通过 `_local_embedding` 本地计算向量以保证离线运行;该客户端保留给需要远端 Embedding 的场景。

### 4.4 三级记忆(`memory/`)

**文件:** `memory/conversation_memory.py` — `MemoryManager` 实现三级记忆:

| 层级 | 存储 | 用途 | 行为 |
|------|------|------|------|
| 工作记忆 | Redis(list) | 当前会话消息 | TTL 24 小时(`REDIS_TTL_SEC=86400`);消息数 ≥ `COMPRESS_AT=15` 时自动压缩 |
| 情景记忆 | ChromaDB `episodic` collection | 压缩后的长对话摘要 | 按 `user_id` 语义检索,返回 Top-`HISTORY_TOP_K=3` 条相关历史摘要 |
| 用户画像 | ChromaDB `user_profile` collection | 用户偏好与高频实体 | 每轮对话后异步 `upsert` 更新 |

**关键方法:**

| 方法 | 作用 |
|------|------|
| `get_memory_context(user_id, conv_id, query)` | 统一返回 `{working_memory, history_summary, user_profile}` 字典,是 `/chat` 流水线的唯一记忆入口 |
| `append_working_memory(...)` | `LPUSH` 写入 Redis 列表 + `EXPIRE` 24h;长度 ≥ 15 触发压缩 |
| `_compress_history(...)` | 保留最新 5 条,更早消息截取前 800 字符作为摘要存入情景记忆,再重写 Redis 列表 |
| `_store_episodic` / `_search_episodic` | 情景记忆写入/检索,统一按 `where={"user_id": user_id}` 过滤 |
| `update_user_profile(user_id, profile_text)` | 以固定 `doc_id = md5("profile_{user_id}")` 执行 `upsert` 覆盖写入画像,异常仅告警不抛出 |
| `get_user_profile(user_id)` | 读取用户画像文本 |

**实现要点:**

- `_init_chroma`:先尝试 `chromadb.HttpClient(host, port)` 并 `heartbeat()` 校验,失败自动回退 `PersistentClient(path)`,随后创建 `episodic` 与 `user_profile` 两个 collection。
- 模块级 `_local_embedding` 与意图识别器算法完全一致(256 维 n-gram 哈希),保证记忆与知识库向量空间统一。
- 类常量 `WORKING_MAX=20` 当前版本已定义但无引用点,实际压缩触发由 `COMPRESS_AT=15` 控制、保留 5 条。

### 4.5 MCP 工具框架与 RAG 知识库(`mcp/`)

> 说明:本项目的 `mcp/` 是**自研工具调用框架**,与官方 Model Context Protocol(MCP)协议无关,只是同名复用。

#### 4.5.1 工具管理器(`mcp/tool_manager.py`)

- `CircuitState`(Enum):`CLOSED` / `OPEN` / `HALF_OPEN`。
- `CircuitBreaker`:三态熔断器 — 连续失败 `failure_threshold=5` 次打开 `OPEN`;`OPEN` 超过 `recovery_s=60.0` 转 `HALF_OPEN` 放行探测请求;探测成功回 `CLOSED` 并清零计数。
- `Tool` 数据类:`name` / `description` / `handler` / JSON `schema` / `cache_ttl`(默认 `0.0` = 不缓存)/ `timeout_s`(默认 `30.0`)/ `supports_rerank` / `fallback`,并携带运行时 `stats` 与 `breaker`。

**`call(name, params, context, ...)` 执行链:**

```
工具不存在 → 直接 error
缓存命中 → 直接返回(cached=True)
熔断不通过 → 走 fallback
参数校验(_validate_params,手写 JSON Schema 校验:required 缺字段 + 类型不符 → ValueError)
asyncio.wait_for(handler, timeout=tool.timeout_s)
成功 → 更新 stats、记录成功、写缓存、可选 LLM 重排
超时/异常 → 失败计数 +1、连续失败 +1、breaker.record_failure() → 走 fallback
fallback 成功 → success=True 但携带原 error 信息
```

- **`rewrite_query(query, n=3)`**:LLM 将单一查询扩展为 3 个不同角度子查询(`max_tokens=256, temperature=0.3`),保留原查询并去重。
- **`search_with_rewrite(tool_name, query, top_k)` 完整检索流水线**:

```
1. 查询改写(rewrite_query, n=3)
2. 并行召回:recall_k = max(top_k, 5),各子查询 call() 后 asyncio.gather(return_exceptions=True)
3. 内容去重:按 str(item) 的 md5 哈希合并
4. 无任何结果 → 返回 error "所有子查询均无结果"
5. LLM 重排(_rerank)取 Top-K
```

- **缓存**:内存 TTL 缓存,上限 5000 条,超限淘汰最旧 1/4(1250 条);缓存键 = `"{tool_name}:{md5(json.dumps(params, sort_keys=True))}"`。
- **`_validate_params`**:手写 JSON Schema 校验(非第三方库),`_TYPE_MAP` 覆盖 string/number/integer/boolean/array/object 六种类型。

#### 4.5.2 知识库(`mcp/knowledge_base.py`)

- `KnowledgeBase` 使用 `chromadb.PersistentClient`,collection 名为 `knowledge_base`。
- `add_documents(documents)`:按约 500 字符切分(`_chunk_text` 以句号断句、语义切块),本地向量化后批量写入,元数据含 `title` / `chunk_index` / `total_chunks`。
- `search(query, top_k)`:查询向量化后 `query_embeddings` 检索,距离转相似度 — 分数 = `1/(1+dist)` 映射到 `(0, 1]`(ChromaDB 默认 L2 距离 ∈ [0, +∞),`1.0 - dist` 不构成相似度且可能为负,故采用单调映射)。
- `search_handler(params, context)`:注册为 `knowledge_search` MCP 工具的异步 handler;`main.py` 中该工具配置 `cache_ttl=300.0`、`supports_rerank=True`,并配有知识库降级 fallback(返回「知识库暂不可用」的兜底结果)。
- `doc_count`:知识库当前片段总数。
- `_load_default_docs`:内置 6 篇种子文档(退款政策/订单查询/账户安全/技术故障排查/会员与积分/配送说明),供首次运行演示;当前版本启动时不再自动导入,仅保留方法定义。

### 4.6 性能监控(`monitor/`)

**文件:** `monitor/performance_monitor.py` — 实现 Monitor → Orchestrator 反馈闭环。

- `AnomalyDetector`:滑动窗口 Z-score 检测 — 窗口 `window=60`、灵敏度 `sensitivity=2.5`;数据点少于 30 时不检测;`z > sensitivity` 判异常,`z > sensitivity*1.5` 级别为 `high`,否则 `medium`;标准差为 0 时不检测。
- `PerformanceMonitor` 阈值表(`THRESHOLDS`):

| 指标 | 阈值 | 级别 | 比较 |
|------|------|------|------|
| `agent_success_rate` | 0.90 | ERROR | 低于 |
| `tool_success_rate` | 0.95 | WARNING | 低于 |
| `agent_avg_ms` | 3000 | WARNING | 高于 |
| `tool_avg_ms` | 5000 | ERROR | 高于 |

- **`_routing_penalty(success_rate, avg_ms)` 公式**(返回范围 `[0, 0.9]`):

```
penalty = 0.0
success_rate < 0.90 → penalty += min(0.5, (0.90 - success_rate) * 2)
avg_ms > 3000      → penalty += min(0.4, (avg_ms - 3000) / 10000)
return min(penalty, 0.9)
```

- **采集闭环**:后台 `_loop` 每 `interval_s`(默认 10.0 秒)执行一次 `_collect()` — 拉取 `orchestrator.get_stats()` 与 `tool_manager.get_stats()` → 异常检测 → 阈值告警(可选 webhook,超时 5.0s)→ Prometheus 指标写入 → 计算路由惩罚 → `orchestrator.update_routing_penalties(...)` 写回。
- 建议生成:工具连续失败 ≥ 3 次、Agent 成功率 < 0.85 且调用总数 > 10 时给出路由调整建议;`summary()` 输出 `/monitor` 端点负载(Agent 统计、工具统计、活动告警、Top-5 建议)。

### 4.7 端到端评测(`evaluation/`)

**文件:** `evaluation/evaluator.py` — 实现 LLM-as-Judge 评测与回归测试。

- `QualityScores`:四维评分 `relevance` / `accuracy` / `completeness` / `helpfulness`(0.0–1.0),`overall = 四维均值`;评分失败时四维默认 0.5 并置 `judge_failed`。
- `LLMJudge.judge(question, response, context)`:结构化提示让 LLM 对「问题、回复、上下文」三元组打分;`max_tokens=256, temperature=0.0`;JSON 解析缺失字段默认 0.5。
- `IntentEvaluator.evaluate(cases)`:纯 Python 计算意图识别准确率、各类别精确率/召回率/F1 与宏平均 F1。
- `EndToEndEvaluator.run(intent_cases, dialog_cases)`:
  - 意图评测(内置 8 条用例:query/request/complaint/technical/billing/escalation/greeting/account 各 1);
  - 对话质量评测(内置 5 条用例:4 个单轮 + 1 个三轮回合多轮场景),驱动真实 orchestrator 产出回复后由 LLM 裁判打分;
  - 单用例通过线 `PASS_THRESHOLD=0.75`;多轮历史取最近 6 条;
  - **回归检测**:与基线报告比较,指标下降超过 5%(`delta < -0.05`)即判定为回归;
  - 规则化建议:意图准确率 < 0.90、relevance/completeness/helpfulness < 0.75 时给出针对性优化建议;
  - 基线持久化:报告以 JSON 读写到 `EVAL_BASELINE_PATH`。

### 4.8 Skills 业务规则(`skills/`)

Markdown 编写的业务话术,由 `SkillManager` 热加载并按规则注入 Agent 系统提示词。当前生效四套:

| Skill | 领域 | 关键词示例 |
|-------|------|-----------|
| `admin_agent` | 行政(会议室、办公用品、门禁、访客) | 会议室, 办公用品, 门禁, 访客 |
| `finance_agent` | 财务/账单(退款、发票、订阅) | 退款, 扣款, 发票, 订阅 |
| `hr_agent` | 人力资源 | 人力资源相关关键词 |
| `it_agent` | IT 运维(账号、网络、软件、WMS、ERP) | 账号, 权限, 登录报错, WMS, ERP |

**Skill 文件格式**(Markdown + 可选 front-matter):

```markdown
---
name: 账单退款处理规范
description: 账单退款类问题的处理规则
keywords: 退款,扣款,发票,订阅
agents: billing
enabled: true
---

# 账单退款处理规范
...业务规则正文...
```

`agents` 将技能限定到指定 Agent 类型(空 = 全部 Agent);`keywords` 限定到包含对应关键词的消息(空 = 始终注入)。

---

## 5. 关键类与函数参考

### `agents/agent_orchestrator.py`

| 符号 | 类型 | 用途 |
|------|------|------|
| `AgentType` | Enum | `GENERAL` / `TECHNICAL` / `BILLING` / `ESCALATION` |
| `AgentStats` | dataclass | 运行统计 + `routing_score()` |
| `BaseAgent` | class | LLM 调用、系统提示词 + Skills 构建、升级检测 |
| `GeneralAgent` / `TechnicalAgent` / `BillingAgent` | class | 带角色化系统提示词的专属 Agent |
| `AgentOrchestrator.run(req)` | async | 完整请求流水线(意图→路由→执行→升级) |
| `AgentOrchestrator.run_parallel(req, agent_types)` | async | 并行多 Agent 协作 |
| `AgentOrchestrator._route(intent, urgency)` | method | 三层路由决策 |
| `AgentOrchestrator._best_agent(agent_type)` | method | 按 `routing_score()` 选最优实例 |
| `AgentOrchestrator.update_routing_penalties(penalties)` | method | 接收监控反馈惩罚,clamp 到 [0, 0.9] |

### `core/intent_recognizer.py`

| 符号 | 类型 | 用途 |
|------|------|------|
| `IntentCategory` / `UrgencyLevel` | Enum | 意图与紧急度分类 |
| `IntentRecognizer.recognize(message, history)` | async | 三路融合识别入口(LLM/Embedding 并行 + 规则同步,加权投票) |
| `IntentRecognizer._llm_recognize` | async | LLM 策略(权重 70% / 85%) |
| `IntentRecognizer._embedding_recognize` | async | Embedding 策略(权重 20%,`base_url` 存在时禁用) |
| `IntentRecognizer._pattern_recognize` | method | 关键词策略(权重 10% / 15%) |
| `IntentRecognizer._vote(...)` | method | 加权投票合并,低于阈值 0.5 → OTHER |
| `IntentRecognizer._local_embedding(text, dims=256)` | staticmethod | 离线 n-gram 哈希向量 |
| `IntentRecognizer.learn(message, correct)` | method | 在线模板学习 |

### `core/skill_loader.py`

| 符号 | 类型 | 用途 |
|------|------|------|
| `Skill.matches(message, agent_type)` | method | 注入判定(agents 过滤 + keywords 过滤) |
| `Skill.to_prompt_block(max_chars=3200)` | method | 提示词块格式化 |
| `SkillManager.load()` / `reload()` | method | 发现并解析 Skills |
| `SkillManager.prompt_for(message, agent_type)` | method | 构建聚合 Skills 提示词(总预算 5000 字符) |

### `memory/conversation_memory.py`

| 符号 | 类型 | 用途 |
|------|------|------|
| `MsgRole` | Enum | user / assistant / system |
| `MemoryManager.get_memory_context(...)` | async | 三级记忆统一读取 |
| `MemoryManager.append_working_memory(...)` | async | 写入 + 自动压缩触发 |
| `MemoryManager._compress_history(...)` | async | 旧消息转摘要入情景记忆 |
| `MemoryManager.update_user_profile(...)` | async | 固定 doc_id 的 upsert 画像更新 |

### `mcp/tool_manager.py`

| 符号 | 类型 | 用途 |
|------|------|------|
| `CircuitBreaker` | class | 三态熔断(失败阈值 5,恢复 60s) |
| `MCPToolManager.call(...)` | async | 完整工具执行链 |
| `MCPToolManager.rewrite_query(query, n=3)` | async | LLM 查询扩展 |
| `MCPToolManager.search_with_rewrite(...)` | async | 改写→并行召回→去重→重排→Top-K |
| `MCPToolManager._rerank(...)` | async | LLM 相关性重排 |

### `mcp/knowledge_base.py`

| 符号 | 类型 | 用途 |
|------|------|------|
| `KnowledgeBase.add_documents(documents)` | async | 切块 + 向量化 + 写入 |
| `KnowledgeBase.search(query, top_k)` | async | 向量检索,`1/(1+dist)` 相似度 |
| `KnowledgeBase.search_handler(params, context)` | async | `knowledge_search` 工具 handler |

### `monitor/performance_monitor.py`

| 符号 | 类型 | 用途 |
|------|------|------|
| `AnomalyDetector.record(metric, value)` | method | Z-score 异常检测(窗口 60,灵敏度 2.5) |
| `PerformanceMonitor.start()` / `stop()` | async | 后台采集循环生命周期 |
| `PerformanceMonitor._collect()` | async | 采集 + 告警 + 惩罚反馈 |
| `PerformanceMonitor._routing_penalty(sr, ms)` | staticmethod | 性能 → 惩罚系数 [0, 0.9] |
| `PerformanceMonitor.summary()` | method | `/monitor` 负载 |

### `evaluation/evaluator.py`

| 符号 | 类型 | 用途 |
|------|------|------|
| `LLMJudge.judge(question, response, context)` | async | 四维 LLM 打分 |
| `IntentEvaluator.evaluate(cases)` | async | 准确率 + 各类 F1 |
| `EndToEndEvaluator.run(intent_cases, dialog_cases)` | async | 完整评测流水线 |
| `EndToEndEvaluator._detect_regressions(current)` | method | 与基线对比,下降 >5% 判回归 |

---

## 6. 依赖关系与技术栈协同

### 6.1 内部模块依赖

```
api/main.py
  ├─► agents/agent_orchestrator.py
  │     ├─► core/intent_recognizer.py(编排器内部自行创建)
  │     └─► core/skill_loader.py(可选注入)
  ├─► memory/conversation_memory.py
  │     └─► core/embedding_client.py(实例化;实际使用本地向量)
  ├─► mcp/tool_manager.py
  │     └─► 注册 mcp/knowledge_base.py
  │           └─► core/embedding_client.py(同上)
  ├─► monitor/performance_monitor.py ──(读统计/写惩罚)──► agents/agent_orchestrator.py
  └─► evaluation/evaluator.py
        ├─► agents/agent_orchestrator.py(驱动真实对话)
        └─► core/intent_recognizer.py(意图评测)
```

- `api/main.py` 是装配根:在 `lifespan` 中按「`IntentRecognizer` → `SkillManager` → `AgentOrchestrator` → `MemoryManager` → `MCPToolManager` → `KnowledgeBase`(注册 `knowledge_search`)→ `PerformanceMonitor`(start)→ `EndToEndEvaluator`」的顺序构造全部组件。
- `MemoryManager` 与 `KnowledgeBase` 都依赖 ChromaDB,共享同一套本地 256 维 n-gram 向量逻辑,保证记忆与知识库向量空间一致。
- `PerformanceMonitor` 同时持有 `orchestrator` 与 `tool_manager` 引用,读统计、写惩罚,构成**反馈闭环**。
- `EndToEndEvaluator` 驱动 orchestrator 产出真实回复,再由独立的 `LLMJudge` 打分。

### 6.2 外部第三方依赖(`requirements.txt`)

| 包 | 版本 | 角色 |
|----|------|------|
| `anthropic` | 0.40.0 | LLM 客户端(Claude / DeepSeek 兼容端点) |
| `fastapi` | 0.115.5 | Web 框架 |
| `uvicorn[standard]` | 0.32.1 | ASGI 服务器 |
| `pydantic` | 2.10.3 | 请求/响应校验与 OpenAPI 生成 |
| `python-multipart` | 0.0.12 | 文件上传支持 |
| `redis` | 5.2.1 | 工作记忆(`redis.asyncio`) |
| `chromadb` | 0.5.23 | 向量数据库(情景/画像/知识库) |
| `prometheus-client` | 0.21.1 | 指标导出 |
| `httpx` | 0.28.1 | 异步 HTTP(webhook 告警、可选远端 Embedding) |
| `python-dotenv` | 1.0.1 | `.env` 加载 |

### 6.3 基础设施服务(`docker-compose.yml`)

| 服务 | 镜像 | 端口 | 用途 |
|------|------|------|------|
| `echomind` | 由 `Dockerfile` 构建 | 8000 | FastAPI 主应用 |
| `redis` | `redis:7-alpine` | 6379 | 工作记忆 |
| `chromadb` | `chromadb/chroma:0.5.23` | 8001→8000 | 向量数据库 |
| `prometheus` | `prom/prometheus:latest` | 9090 | 指标抓取 |
| `nginx` | `nginx:alpine` | 80 | 反向代理 + 限流 |

所有服务共享 `echomind-network` 桥接网络,数据经命名卷持久化(`redis-data` / `chromadb-data` / `prometheus-data` / `nginx-logs`)。容器内通过环境变量覆盖本地路径:应用数据目录 `/app/data/chroma`、评测基线 `/app/data/eval/baseline.json`、Skills 目录 `/app/skills`。

### 6.4 技术栈协同逻辑

- **LLM 与 Embedding 解耦**:对话生成走 Anthropic 兼容端点(可配置 `ANTHROPIC_BASE_URL` 指向 DeepSeek 等);Embedding 全程本地 n-gram 哈希,不依赖任何外部 Embedding 服务,保证「模型可换、向量不离线」。
- **异步贯穿**:`redis.asyncio` 与 `httpx` 保证 Redis、ChromaDB、LLM、webhook 等 I/O 不阻塞事件循环;多 Agent 协作与多子查询召回均以 `asyncio.gather` 并发执行。
- **三库分工**:Redis 承担高频读写的工作记忆(毫秒级 list 操作 + TTL);ChromaDB 承担低频但需语义检索的情景记忆、用户画像与知识库,三组 collection(`episodic` / `user_profile` / `knowledge_base`)互不干扰。
- **闭环联动**:意图识别决定路由 → 路由结果与工具统计被监控采集 → 监控换算惩罚写回路由评分 → 路由评分影响下一次 Agent 选择,形成「运行数据反哺路由」的自适应机制;评测模块以相同链路输出可回归验证的质量基线。

---

## 7. 核心业务流程

### 7.1 单次 `/chat` 请求流水线

```
1. 接收 POST /chat {user_id, conv_id, message}
2. conv_id = req.conv_id 或新生成 UUID
3. mem_ctx = memory.get_memory_context(user_id, conv_id, message)
     ├─ working_memory   (Redis,最近消息)
     ├─ history_summary  (ChromaDB episodic,Top-3 摘要)
     └─ user_profile     (ChromaDB user_profile)
4. knowledge_text, knowledge_used = _build_knowledge_context(message, top_k=3)
     └─ tool_manager.search_with_rewrite("knowledge_search", message, top_k=3)
          ├─ rewrite_query → 3 个子查询
          ├─ 并行召回(asyncio.gather)
          ├─ 内容 md5 去重
          └─ LLM 重排 → Top-3
5. 拼接 full_context = [历史摘要] + [用户画像] + [当前对话] + [知识库结果]
6. orch_req = Request(message, user_id, conv_id, context, history)
7. result = orchestrator.run(orch_req)
     ├─ IntentRecognizer.recognize(message, history)  [LLM+Embedding 并行 + 规则]
     ├─ _collaboration_targets(req)  → 复合问题则并行
     ├─ _route(intent, urgency)      → 目标 Agent 类型
     ├─ _execute(req, agent_type)
     │     ├─ _best_agent(agent_type)   [按 routing_score()]
     │     ├─ agent.handle(req)
     │     │     ├─ _build_system_prompt [注入匹配的 Skills]
     │     │     └─ client.messages.create(...)
     │     └─ 失败 → 降级 GeneralAgent
     └─ 升级判定(CRITICAL / ESCALATION / escalate 标记)
8. memory.append_working_memory(USER 消息、ASSISTANT 回复)
9. asyncio.create_task(memory.update_user_profile(...))  [异步,不阻塞响应]
10. 返回 ChatResponse {conv_id, response, intent, agent_type, escalated, latency_ms, knowledge_used}
```

### 7.2 三级记忆运行逻辑

1. **工作记忆(Redis)** — 每条消息 `LPUSH` + `EXPIRE` 24h;列表长度 ≥ `COMPRESS_AT=15` 时触发 `_compress_history`:保留最新 5 条,更早消息截取 800 字符摘要写入情景记忆,重写 Redis 列表。
2. **情景记忆(ChromaDB `episodic`)** — 摘要按本地向量索引,查询时按 `user_id` 过滤取 Top-3 相关历史摘要。
3. **用户画像(ChromaDB `user_profile`)** — 每轮对话后异步以固定 `doc_id`(md5(`profile_{user_id}`))`upsert` 更新,下次对话读取注入上下文实现个性化。

### 7.3 Agent 路由规则

| 触发条件 | 路由目标 |
|---------|----------|
| urgency = `CRITICAL` | `ESCALATION`(升级) |
| 意图 `TECHNICAL` | `TECHNICAL` |
| 意图 `BILLING` / `ACCOUNT` | `BILLING` |
| 意图 `ESCALATION` | `ESCALATION` |
| 复合问题(技术 + 账单关键词同时命中) | 并行 `TECHNICAL` + `BILLING` |
| 专属 Agent 执行失败 | 降级 `GENERAL` |
| 其余意图 | `GENERAL` |

### 7.4 监控反馈闭环

```
每 MONITOR_INTERVAL(默认 10s):
  PerformanceMonitor._collect()
    ├─ 读取 orchestrator.get_stats()(请求期间实时更新)
    ├─ 读取 tool_manager.get_stats()
    ├─ AnomalyDetector Z-score 异常检测
    ├─ 阈值告警(+ 可选 webhook)
    ├─ Prometheus 指标写入
    ├─ _routing_penalty(success_rate, avg_ms) → penalty ∈ [0, 0.9]
    └─ orchestrator.update_routing_penalties(penalties)
          └─ 更新各 Agent 的 monitor_penalty
                └─ 影响下一次 _best_agent() 的 routing_score()
```

---

## 8. 配置参考

全部配置经环境变量注入(见 `.env.example` / `.env`):

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ANTHROPIC_API_KEY` | 必填 | LLM API 密钥,缺失抛 `RuntimeError` |
| `ANTHROPIC_BASE_URL` | 空 | Anthropic 兼容端点覆盖(如 `https://api.deepseek.com/anthropic`);非空时意图识别禁用 Embedding 分支 |
| `ANTHROPIC_MODEL` | `claude-3-5-sonnet-20241022` | 模型名(如 `deepseek-chat`) |
| `REDIS_URL` | `redis://redis:6379/0` | Redis 连接串 |
| `REDIS_PASSWORD` | `echomind123` | Redis 密码(compose 编排) |
| `CHROMA_HOST` | `chromadb` | ChromaDB 主机 |
| `CHROMA_PORT` | `8000` | ChromaDB 端口(容器内 8000;本地直跑经宿主映射时用 8001) |
| `CHROMA_PERSIST_DIRECTORY` | `/app/data/chroma` | 本地 Chroma 持久化路径 |
| `PROMETHEUS_PORT` | `0`(不启动) | 应用内 Prometheus 指标端口;`run-image.sh` 部署脚本显式设为 9090 |
| `MONITOR_INTERVAL` | `10` | 监控采集间隔(秒) |
| `ALERT_WEBHOOK_URL` | 空 | 可选告警 webhook |
| `EVAL_BASELINE_PATH` | `/app/data/eval/baseline.json` | 评测基线文件 |
| `ECHOMIND_SKILLS_DIR` | `<项目根>/skills` | Skills 根目录 |
| `ECHOMIND_SKILLS_MAX_PROMPT_CHARS` | `5000` | Skills 提示词总预算(字符) |
| `API_HOST` / `API_PORT` | `0.0.0.0` / `8000` | 服务绑定 |
| `LOG_LEVEL` | `INFO` | 日志级别 |
| `APP_ENV` | `production` | 设为 `development` 时启用 uvicorn `--reload` |

> **Embedding 行为说明**:设置 `ANTHROPIC_BASE_URL`(第三方端点)时,`IntentRecognizer._embedding_enabled=False`,三路投票退化为 LLM 85% + 规则 15%;`MemoryManager` 与 `KnowledgeBase` 始终使用本地 n-gram 向量,系统全程无需下载任何境外 Embedding 模型。

---

## 9. API 端点参考

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 服务就绪检查 + Agent 统计 |
| POST | `/chat` | 主对话端点(完整流水线) |
| GET | `/skills` | 列出已加载 Skills 与解析错误 |
| POST | `/skills/reload` | 运行时热加载 Skills,无需重启 |
| GET | `/monitor` | Agent/工具统计、告警、建议 |
| GET | `/metrics` | Prometheus 指标 |
| POST | `/search?query=...&top_k=N` | 独立 RAG 检索演示(改写→召回→重排) |
| POST | `/knowledge/add` | 批量导入 JSON 文档 |
| POST | `/knowledge/upload` | 上传 `.md` / `.txt` / `.json` 文件(≤10MB) |
| GET | `/knowledge/stats` | 知识库片段总数 |
| POST | `/eval/run` | 运行意图 + LLM-as-Judge 评测 |

**`/chat` 调用示例:**

```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "test001",
    "conv_id": "c001",
    "message": "退款多久审核完成"
  }'
```

**响应字段:** `conv_id`、`response`、`intent`、`agent_type`、`escalated`、`latency_ms`、`knowledge_used`。

---

## 10. 运行方式

### 10.1 Docker Compose 全栈一键启动

```bash
docker compose up -d --build   # 构建并启动 app + redis + chromadb + prometheus + nginx
docker compose logs -f echomind  # 查看日志
docker compose ps                # 查看状态
docker compose down              # 停止
docker compose down -v           # 停止并清空数据卷(慎用)
```

### 10.2 本地开发(免 Docker)

```bash
python3 -m venv .venv && source .venv/bin/activate   # 创建虚拟环境
pip install -r requirements.txt                       # 安装依赖
cp .env.example .env                                  # 配置环境(必填 ANTHROPIC_API_KEY)
uvicorn api.main:app --host 0.0.0.0 --port 8000       # 启动 API
python -m api.main --cli                              # 或启动交互式 CLI
```

需先确保本机 Redis 与 ChromaDB 服务可用(本地直跑时 `CHROMA_PORT` 使用宿主映射端口,compose 内使用容器端口 8000)。

### 10.3 部署辅助脚本

- `docker-deploy.sh`:全生命周期管理(`install` / `start` / `stop` / `restart` / `status` / `logs` / `health` / `build` / `cleanup` / `backup` / `restore`)。
- `run-image.sh`:单容器运行器,支持 `run` / `run-dev` / `run-test` / `run-prod` 模式及 `--detach`、`--env-file`、`--ports`、`--volume`、`--name`、`--restart` 选项。

---

## 11. 项目优化说明

本版本针对正确性缺陷完成了以下改进:

| 改进点 | 原实现问题 | 现实现 |
|--------|-----------|--------|
| 知识库文件上传 | `/knowledge/upload` 未 `await` 入库,`count` 为 coroutine | 改为 `count = await kb.add_documents(docs)` |
| 用户画像更新 | `delete(where={"user_id"})` 参数缺值且异常被静默吞掉,画像永不更新、记录无限累积 | 改为固定 `doc_id` 的 `collection.upsert` 覆盖写入,异常记 warning |
| 交互式 CLI | 调用 `MemoryManager` 不存在的 `get_context` / `add_message` / `to_prompt_text`,运行即 AttributeError | 改用 `get_memory_context` / `append_working_memory`,context 拼接与 `/chat` 主链路一致 |
| 检索相似度 | `1.0 - dist` 对 ChromaDB L2 距离不构成相似度且可能为负 | 改为 `1/(1+dist)` 单调映射到 `(0, 1]` |
| 配置示例 | `.env.example.env` 键名(`CLAUDE_MODEL` / `MONITORING_INTERVAL`)与代码实际读取键不一致,照配静默失效 | 键名对齐 `ANTHROPIC_MODEL` / `MONITOR_INTERVAL` 等,补齐缺失键并去除示例中的真实密钥 |

