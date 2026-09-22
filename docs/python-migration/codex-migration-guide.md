# 使用 Codex 迁移 Reactor Java 后端

本指南是 Reactor Java → Python 迁移的入口文档。它把 OpenAI 对 Codex 的通用建议落实为本仓库可执行的阶段、提示词、验收门槛和回滚规则。

## 结论

本项目应采用绞杀式双栈迁移：Java 与 Python 并行运行，以固定契约和数据不变量为准，一次迁移一个可独立验证的垂直切片，按精确路由切换并保留回滚路径。不要一次性重写，也不要按 Java 类逐文件翻译。

迁移范围是 Java Agent Backend。以下组件默认保留：

- React 19 前端 `ui/`；
- 已经是 Python 的 `reactor-tool/` 和 `reactor-sandbox` 独立服务；
- `runtime/skills/` 与共享 workspace；
- 当前 MySQL schema 和公共 HTTP/SSE 路径。

目标实现是现有 `backend-python/`，不再建立另一套 Python 工程。

## 当前状态

以 [progress.md](progress.md) 为准：

- Phase 0 审计与基线：已完成。
- Phase 1 Python 共存骨架：已完成。
- Phase 2 契约实验室：进行中。
- Phase 3 及以后：尚未开始业务迁移。

仓库当前有约 816 个生产 Java 文件、108 条方法路由、33 张 MySQL 表和 29 个 MyBatis Mapper XML（外加 1 个 `mybatis-config.xml`）。SSE 口径有两种：6 个 handler 声明 `produces=text/event-stream`，其中 **5 条是真实 `SseEmitter` 流**（`/web/health` 只声明了媒体类型，返回单次普通 `ok` 响应体）。Python 主后端目前只有健康检查、配置、日志、数据库生命周期和契约工具，没有公共业务路由。

当前 Python 基线为 15 个非 integration 测试通过，Ruff 与 strict mypy 通过。Java 全量 app 基线存在 12 个 failure 和 53 个 error，这些是已登记债务，不能把全量 Java 测试误称为绿色，也不能用它们掩盖迁移新增回归。

## 文档地图

- [仓库 Codex 规则](../../AGENTS.md)：每次任务自动适用的持久约束。
- [ExecPlan 规范](PLANS.md)：长任务计划的格式、维护和完成定义。
- [分阶段提示词](staged-prompts.md)：可以直接复制给 Codex 的阶段任务。
- [系统盘点](inventory.md)：模块、路由、运行时和外部依赖。
- [HTTP/SSE 契约](api-contracts.md)：协议兼容要求。
- [数据库所有权](database-ownership.md)：表、事务和 writer 切换。
- [风险登记](risk-register.md)：已知风险、缓解和阻塞。
- [迁移进度](progress.md)：真实状态、验证证据和阶段出口。

事实发生变化时更新对应事实文档；不要把历史证据只留在聊天记录中。

## OpenAI 建议如何映射到本仓库

OpenAI 的 Codex 最佳实践建议：把长期适用的仓库规则写入 `AGENTS.md`；复杂工作先规划；提示词明确 Goal、Context、Constraints 和 Done when；让 Codex 运行测试、检查 diff 并进行代码审查。OpenAI 的代码现代化示例进一步建议先选一个边界清晰的 pilot，分别维护 overview、target design、validation 与 ExecPlan，再做并行实现和 parity 验证。

本仓库采用以下映射：

| OpenAI 工作方式 | Reactor 落地 |
|---|---|
| 持久指导 | 根目录 `AGENTS.md` |
| 多小时任务计划 | 每个垂直切片一个 ExecPlan，遵循 `PLANS.md` |
| 小范围 pilot | public featured-conversations 三个 GET |
| 参考行为 | Java characterization、净化 golden、固定数据库 fixture |
| parity-first | HTTP/SSE diff、数据库 before/after、文件 checksum、前端 consumer tests |
| 小步执行 | 一个聊天/分支/worktree 只处理一个切片 |
| 独立复核 | 新会话或独立 worktree 运行验收提示词与 `/review` |
| 反馈固化 | 发现重复错误时更新 `AGENTS.md`、ExecPlan 与风险登记 |

官方参考：

- [Codex best practices](https://developers.openai.com/es-419/guides/best-practices)
- [使用 AGENTS.md 自定义指令](https://developers.openai.com/zh-Hans/docs/agent-configuration/agents-md)
- [Using PLANS.md for multi-hour problem solving](https://developers.openai.com/cookbook/articles/codex_exec_plans)
- [Modernizing your Codebase with Codex](https://developers.openai.com/cookbook/examples/codex/code_modernization)
- [Run code migrations](https://developers.openai.com/es-419/use-cases/code-migrations)

## 每个切片的 Codex 工作流

### 1. 保护和定位

开始时运行 `git status --short` 与相关 `git diff`。当前工作树已有迁移成果，Codex 不得 reset、checkout、clean 或重写无关文件。准备并行工作前先由人工审阅并建立 checkpoint，再为不同切片使用独立 worktree。

### 2. 计划

在 Plan mode 中发送 [staged-prompts.md](staged-prompts.md) 的通用前缀和当前阶段提示词。Codex 先研究 Java controller → application → domain → repository/mapper、前端消费者、测试与 Nginx，再在 `docs/python-migration/execplans/` 创建一个自包含 ExecPlan。

### 3. 冻结参考行为

为切片准备确定性 fixture，先增加 Java characterization test 或录制净化 golden。明确哪些字段可以按 case 归一化；不得使用全局忽略。写操作用同一快照克隆的两份测试库分别执行 Java 和 Python，不能对同一库做 live 双写。

### 4. 最小实现

在 `backend-python/src/reactor_backend/` 按 `api → application → domain/runtime ports ← infrastructure` 实现。第一版优先保持 SQL 和行为等价，不同时重构 schema、API 或前端。外部模型、工具和 MCP 使用 fake/录制。

### 5. 分层验证

从最窄验证开始，完成后再扩大：

```bash
cd backend-python
uv run ruff check .
uv run mypy src
uv run pytest -m "not integration"
```

按范围增加 MySQL integration、Java 稳定基线、HTTP/SSE contract、前端 consumer、并发/故障和 Compose smoke。测试结果、不能运行的检查及原因必须进入 ExecPlan。

### 6. 独立审查

使用新 Codex 会话或独立 worktree，运行 staged prompts 中的“独立验收 / 代码审查提示词”。审查者应亲自运行验证并优先寻找契约、所有权、取消、回滚和安全问题，而不是只做格式审查。

### 7. 切流与回滚

只有阶段出口通过才改路由。纯读使用最窄的 exact path 切换；写路由先明确唯一 owner；有状态 Agent 路由按原子族和 visitor sticky cohort 切换。每次发布前实际演练回滚。

### 8. 更新活文档

结束时更新 ExecPlan 的 Progress、Discoveries、Decision Log、Outcomes，并同步 `progress.md`、`risk-register.md`、`database-ownership.md` 或契约文档。没有实际证据时不得把阶段标记为完成。

## 修正版迁移阶段

| 阶段 | 范围 | 出口条件 |
|---|---|---|
| P0 基线与治理 | 路由、表、后台任务、外部依赖、测试债务 | 全部能力被分配阶段、owner、验证和回滚；无未分类写入 |
| P1 Python 共存骨架 | FastAPI、配置、日志、DB、health、Docker、CI | Ruff、mypy、单测、MySQL readiness、镜像和双栈启动通过 |
| P2 契约实验室 | 固定 fixture、Java golden、HTTP/SSE diff、provider fake | 真实净化 golden 可重复录制；每个路由 covered 或 explicitly deferred |
| P3 无副作用查询 | public featured 和经证明无身份写入的查询 | 只读 DB 账号可运行；契约零未解释差异；exact-path 回滚通过 |
| P4 身份与 CRUD | visitor、capability、admin/model/MCP 写域 | 一个 operation 一个 writer；事务/并发/回滚和 cloned-DB parity 通过 |
| P5 SSE/run-control 内核 | 事件队列、投影、heartbeat、follow/stop/inject、取消 | fake 下断连/恢复/取消/backpressure 无泄漏；暂不单独公开切流 |
| P6 Tool/Skill/MCP/文件 | reactor-tool adapter、workspace、上传/导出、Skill、MCP | fake-backed parity 与路径/进程安全测试通过 |
| P7 核心 Agent | ReAct、Plan-Solve、model/tool、ledger/replay | fake 下状态机和 DB 精确等价；有界并发、故障、重放通过 |
| P8 高级能力 | HITL、memory、sub-agent/background、Data Agent | CAS、重启、幂等、恢复、多数据源安全分别通过 |
| P9 灰度与退役 | sticky canary、drain、100%、Java retire | Python 全量 14 天满足 SLO；停 Java 后再观察 14 天并完成对账 |

P0/P1 已基本完成，当前必须先完成 P2，而不是直接大量生成 Python 业务代码。

## 首个 pilot

首个实现切片应是：

- `GET /api/agent/featured-conversations/home`
- `GET /api/agent/featured-conversations`
- `GET /api/agent/featured-conversations/{featuredId}`

选择理由：它们是前端可观察的完整查询族，不经过 `VisitorIdentityFilter` 的身份创建/刷新路径，能用只读数据库权限验证，并能用 exact-path 路由独立切回 Java。

不应首先迁移 `/api/agent/visitor/bootstrap`、conversation session GET 或 capability GET。虽然 HTTP 方法是 GET，Java 的访客过滤器仍可能：

- 对有效 Cookie 更新 `last_seen_at`、IP 和 User-Agent；
- 对缺失/失效 Cookie 插入 visitor 并返回 `Set-Cookie`。

因此这些接口属于身份写入所有权问题，应进入 P4 或先设计可信内部身份边界。（口径已于 2026-09-22 定案：**这三组 GET 全部归 P4**，`inventory.md` 与 `database-ownership.md` 已对齐。补充事实：`/api/agent/session/{id}/capabilities` GET **不受** `VisitorIdentityFilter` 保护，且是纯读；它离开 P3 是保守归组，不是身份写入要求，后续若需可单独论证提级。）

## 不能拆分的原子族

以下路由共同依赖进程内 run owner，公开切换时必须保持相同上游。**按整族处理，不只按「与活跃 run 相关的操作」子集**——`/pending`、`/cancel` 等看似独立的端点同样依赖同一个 pending registry 与 run owner：

- `/web/api/v1/gpt/queryAgentStreamIncr`
- `/api/agent/run/*`（`stop`、`inject`、`follow`）
- `/api/agent/ask-user/*`（`answer`、`resume`、`pending`、`cancel`）
- `/api/agent/plan-approval/*`（`approve`、`reject`、`resume`、`pending`、`cancel`）

随机按请求做百分比分流会使控制请求找不到 run。P9 必须按 `ai_agent_visitor_token` 做稳定 cohort；Python 发起的活跃 run 在回滚时应先 drain，紧急情况下显式失败并让用户重试，不能伪装成 Java 已无损接管。

## 验收体系

### 静态与单元

- Ruff、strict mypy、Python unit tests。
- Java 受影响模块的 characterization tests。
- 前端相关 consumer tests。

### 数据库集成

- 固定 MySQL 8.4 fixture 与 `Asia/Shanghai` 时间行为。
- generated key、NULL/default、排序、分页、soft delete、rowcount、事务回滚。
- 写操作在克隆库分别运行，比较所有受影响表。

### 协议契约

- HTTP status/media type、`{code, info, data}`、字段/类型/null/顺序、Cookie/CORS。
- multipart、ZIP/PDF/DOCX headers 与 checksum。
- SSE 有序帧、ID、心跳、UTF-8、EOF/timeout/error、断连/follow/终态。

### 运行时与安全

- 有界并发、busy/rejection、取消传播、慢消费者、重启、无孤儿 task/连接。
- workspace traversal、symlink escape、Zip Slip、子进程组取消。
- 日志与 golden 不含 Cookie、密钥、完整 prompt 或数据库 URL。

### 性能与发布

先在相同机器、fixture 和 fake provider 上锁定 Java 基准，再定义 Python 的 p95/p99、吞吐、SSE TTFB、错误率、资源与 soak 阈值。灰度建议为 1% → 5% → 25% → 50% → 100%，但每一级必须由预先锁定的自动回滚条件控制。

## 发布否决条件

以下任一存在，不得切流：

- 没有可重复的 Java fixture/golden；
- Python 路由没有对应契约和前端消费证据；
- 写操作会在 Java/Python 双写；
- 把 visitor 相关 GET 错当纯读；
- 把主 stream 与 follow/stop/inject/HITL resume 拆到不同 owner；
- SSE 只验证“最终有响应”，未验证断连、恢复、取消和持久化；
- 普通 CI 会触发 live/paid provider；
- 通过扩大 ignore、篡改 golden 或修改前端来掩盖不兼容；
- 没有可执行并已演练的回滚步骤。

## 下一步

1. 使用 [阶段 2 提示词](staged-prompts.md#阶段-2完成契约实验室当前下一步) 完成确定性 fixture、Java golden 和离线差分能力。
2. 用 [阶段 3A 提示词](staged-prompts.md#阶段-3a首个业务试点公共精选会话查询) 实现 public featured pilot。
3. 独立验收通过后，再执行阶段 3B 的 exact-path 切流与回滚演练。
