# Codex 分阶段迁移提示词

本文档提供 Reactor Java → Python 迁移可直接复制给 Codex 的提示词。不要用一个“大提示词”要求一次性重写整个后端；每个聊天、分支或 worktree 只处理一个可独立验收的垂直切片。

当前建议从“阶段 2：完成契约实验室”开始。`backend-python/` 骨架已经存在，阶段 0/1 不应重新搭建。

## 使用方法

1. 人工确认当前未提交改动，建立可恢复的 checkpoint；并行任务使用不同 Git worktree。
2. 新会话先使用 Plan mode，让 Codex 研究并创建/更新一个 ExecPlan。
3. 把“通用前缀”和一个阶段提示词一起发送。
4. 实现完成后，在独立会话或独立 worktree 中使用“独立验收/审查提示词”。
5. 只有阶段出口通过，才进入下一阶段。失败证据写回 ExecPlan 和 `progress.md`，不要用忽略规则掩盖差异。

OpenAI 建议一个任务提示词至少明确 Goal、Context、Constraints 和 Done when。下面的提示词均按这四部分组织。

## 通用前缀

每个阶段都附上以下内容：

```text
你正在 Reactor 仓库中执行 Java → Python 渐进式迁移。先完整阅读根目录 AGENTS.md，以及：
- docs/python-migration/PLANS.md
- docs/python-migration/inventory.md
- docs/python-migration/api-contracts.md
- docs/python-migration/database-ownership.md
- docs/python-migration/risk-register.md
- docs/python-migration/progress.md

开始前运行 git status --short，把现有修改视为用户资产。不要 reset、checkout、清理或覆盖与本任务无关的文件。使用现有 backend-python/，不要另建第二套 Python 后端；保留 React UI、reactor-tool、reactor-sandbox、runtime/skills 和现有数据库 schema，除非本阶段明确要求。

一次只做本提示词指定的一个垂直切片。先研究 Java 参考实现、前端消费者、SQL/表、测试和 Nginx 路由；创建或更新 docs/python-migration/execplans/<slice>.md，然后实施。保持公共 HTTP/SSE/数据库/文件行为兼容。禁止 Java/Python 应用层双写。自动测试使用确定性 fixture、fake 或净化录制，不调用付费/live provider，不读取或打印生产凭证。

完成前运行与改动相称的测试、契约对比和 git diff 自审；同步更新 ExecPlan 的 Progress、Surprises & Discoveries、Decision Log、Outcomes & Retrospective，以及受影响的迁移文档。最终报告：修改文件、验证命令与结果、契约差异、风险、回滚方法和仍未完成的事项。不要仅因为代码已生成就声称完成。
```

## 阶段 0/1：复核治理和共存基线

仅在迁移资料丢失、明显过期或准备正式接手现有未提交成果时使用；不要重新生成已有骨架。

```text
Goal
复核现有 Java → Python 迁移治理和共存基线，找出文档与真实代码不一致之处，不实现业务路由。

Context
现有 Phase 0/1 已在 docs/python-migration/progress.md 标记完成；backend-python 已包含 FastAPI、配置、结构化日志、MySQL readiness、Docker 和 CI。Java 全量 app 测试有已知基线失败，不能把它误写成全绿。

Constraints
- 只读分析代码；只允许修改迁移文档、测试治理文件和明确缺失的基线配置。
- 对 20 个 controller、108 条方法路由、6 条 SSE、33 张表逐项核对 owner/阶段。
- 区分 blocking gate、已知基线债务、live/paid 测试和未覆盖区域。
- 不隐藏失败，不扩大全局 ignore，不改业务行为。

Done when
- inventory、risk-register、database-ownership、progress 与代码一致。
- 每条公共能力都有迁移阶段、验证方法和回滚所有者。
- Python 的 Ruff、strict mypy、非 integration 单测通过；MySQL integration 和 Compose smoke 有可运行命令。
- 输出缺口列表和下一个最小垂直切片建议。
```

## 阶段 2：完成契约实验室（当前下一步）

```text
Goal
完成可重复的 Java 参考行为采集和 Java/Python 契约实验室，为首个业务切片建立可信基线。

Context
契约代码位于 backend-python/src/reactor_backend/contracts/，初始清单位于 backend-python/tests/contract/cases/initial.json。目前缺少真实 Java golden、确定性数据库 fixture、可离线比较的 Python-vs-golden 路径，以及可执行的 SSE fake fixture。

Constraints
- 本阶段不实现业务路由，不切 Nginx，不调用真实 LLM/MCP/搜索/图片服务。
- 固定时区、visitor/session/featured ID、数据库 seed 和排序。
- golden 不得包含原始 Cookie、API key、完整用户 prompt 或 provider 响应。
- nondeterministic 字段只能按 case 使用精确 JSON Pointer allowlist；禁止全局忽略。
- 明确 additive field 的兼容政策，并让文档与比较器实现一致。
- 为 multipart/binary/SSE 尚未覆盖的能力登记明确 deferred 项，不伪造覆盖率。

Done when
- 在本地 Java + 测试 MySQL 上可以一条明确命令录制首批净化 golden。
- runner 可以把 Python 响应与保存的 Java golden 比较，并生成机器可读 diff。
- 缺失的 fake-agent-request fixture 已补齐，SSE recorder/compare 的范围清楚。
- 契约工具单测覆盖状态、类型、null、排序、Cookie、UTF-8、EOF/timeout/error。
- 所有 Python 静态检查和单测通过；progress.md 记录真实命令、结果和剩余阻塞。
```

## 阶段 3A：首个业务试点——公共精选会话查询

```text
Goal
在 backend-python 中实现首个真正无身份写副作用的垂直切片：
- GET /api/agent/featured-conversations/home
- GET /api/agent/featured-conversations
- GET /api/agent/featured-conversations/{featuredId}
保持 Java 行为和前端消费契约不变。

Context
Java 入口是 Reactor-agent-trigger/.../AgentFeaturedConversationController.java，应用服务是 Reactor-agent-case/.../FeaturedConversationPublicQueryApplicationService.java。相关响应、SQL、ledger/replay 和前端调用都必须一并追踪。不要把 /api/agent/visitor/bootstrap 或 conversation session GET 当成本阶段只读接口：VisitorIdentityFilter 会触发 visitor INSERT/UPDATE。

Constraints
- Python 第一版使用 SQLAlchemy Core 或显式 SQL复刻 MyBatis 语义，不顺便重设计表或 ORM。
- 使用只读数据库权限完成运行验证。
- 精确匹配默认分页、下限归一化、空列表、not-found/null、ONLINE 过滤、排序、标签、时间和状态标签。
- 先写 characterization/contract cases 和 Python tests，再接 router。
- 暂不修改 Nginx；不实现 admin 写接口。

Done when
- unit、repository integration、Java/Python contract 和相关前端 consumer tests 全部通过。
- 保存的 Java golden 与 Python 响应零未解释差异。
- Python 在只读 MySQL 账号下可提供三个接口。
- ExecPlan 包含精确路由切换与一键回 Java 的回滚步骤。
```

## 阶段 3B：首个只读切流与回滚演练

```text
Goal
只把已经通过契约验收的 public featured 三条精确路径切到 Python，并完成回滚演练。

Context
Java 和 Python 必须继续共存。docker/nginx.conf 当前把 /api/ 整体转到 Java，不能使用宽泛 prefix 一次切走其他路由。

Constraints
- 使用 exact-match 或不会吞掉其他 /api/ 路由的最窄配置。
- Python 继续使用只读数据库账号。
- 切流前后运行同一组 smoke/contract/frontend 检查。
- 不做随机 request-level 百分比；本切片不涉及 active run。
- 记录路由配置语法检查和实际回滚用时。

Done when
- 三条路径命中 Python，其余路径仍命中 Java。
- UI 首页/精选列表/详情正常，契约无差异，5xx 未增加。
- 已实际切回 Java、验证恢复，再切回 Python。
- 配置、证据和回滚步骤进入版本控制文档。
```

## 阶段 4：身份与 CRUD（一次一个写域）

把 `<slice>` 替换为一个域，例如 `visitor-identity`、`session-capability`、`featured-admin`、`ai-client-api`、`ai-client-model` 或 `ai-client-tool-mcp`；不要一次迁完全部 CRUD。

```text
Goal
迁移写域 <slice> 的一个完整垂直切片，包括 API、应用用例、repository、事务、缓存/registry 副作用和精确路由所有权。

Context
先从 database-ownership.md 找出所有受影响表和 Java writer。对于 visitor-identity，所有受保护 GET 都可能 touch 或 create visitor；它不是普通只读 middleware。对于 capability/admin/model/MCP，检查 generated key、business ID、soft delete、条件更新、分页和 reload 行为。

Constraints
- 先在 ExecPlan 写清唯一 writer fence、部署顺序和回滚顺序；没有明确 owner 不得实现切流。
- 禁止向同一数据库同时执行 Java/Python 写请求。用同一 snapshot 克隆出的两份测试库分别运行，然后比较响应和全部受影响表。
- 保持 Java 的 HTTP 200 + 业务 code 行为、null/default、唯一键错误和条件 update rowcount 语义。
- 缓存或 registry reload 是验收范围，不得只验证表数据。
- 新增 schema/Alembic 不在本阶段范围，除非单独批准。

Done when
- 正常、非法输入、不存在、重复、唯一键冲突、事务回滚、幂等/并发竞争均有测试。
- Java/Python 在克隆库上的 before/after 结果等价。
- 任意时刻只有一个 writer，owner fence fail closed。
- 精确切流和反向回滚均已演练，database-ownership.md 已更新。
```

## 阶段 5：SSE 与 run-control 内核（先 fake，不切公共流量）

```text
Goal
在 Python 中建立可测试的 SSE 事件模型、单 writer 投影队列、run registry、heartbeat、stop/inject/follow、取消和重连缓冲；先连接 scripted fake executor，不切真实 Agent 流量。

Context
主 SSE、follow、stop、inject 与 HITL resume 共享进程内 run owner。客户端断开不等于 run 取消，finished 业务事件也不等于传输立即关闭。事件 ID、messageOrder、taskOrder、messageId、taskId 和 tool-call ID 是稳定合并键。

Constraints
- 禁止无界 create_task、队列或并发；实现与 Java busy/rejection 对应的有界语义。
- 明确区分业务终态、传输终态、观察者断开和服务重启。
- 事件只能由一个 writer coroutine 排序/投影，其他任务通过有界队列提交。
- 使用 fake LLM/tool；不接生产 provider，不切 Nginx 的 run 路由。
- 初期保持单 Python worker，或证明所有相关请求具备同 owner affinity。

Done when
- 覆盖正常、模型失败、tool 失败、timeout、stop、inject、客户端断连继续运行、follow 不重不漏、慢消费者/backpressure、服务 shutdown。
- 有序帧、终止模式、ledger 预期和残留 asyncio task 都可断言。
- SSE contract 报告包含心跳、UTF-8、EOF/timeout/error；测试后无泄漏 task/连接。
- 公开切流仍保持关闭，直到阶段 7 核心 Agent 一起验收。
```

## 阶段 6：Tool、Skill、MCP 与文件能力

```text
Goal
按一个能力族迁移 reactor-tool adapter、workspace/file、Skill、MCP 或 GenUI export，并保持远程服务边界和安全约束。

Context
reactor-tool 已是独立 Python 服务，本阶段是复刻 Java 后端适配器和编排，不把 reactor-tool 合并进 backend-python。文件和 Skill 使用共享 workspace，包含 multipart、ZIP/PDF/DOCX、命令执行和远程 SSE/HTTP。

Constraints
- 一次只选择一个能力族，先冻结 request/response/error/timeout 契约。
- fake-backed 自动测试；真实外部服务只允许显式手工 suite。
- 验证 realpath containment、.. traversal、绝对路径、symlink escape、Zip Slip、大小限制、中文文件名和取消整个子进程组。
- retry 只用于被证明幂等的操作；会创建文件、远程 job 或 ledger 的调用不得通用重试。
- 保持 binary headers、media type、Content-Disposition 和 checksum。

Done when
- adapter contract、错误映射、timeout/cancel 和资源清理测试通过。
- 安全边界测试通过，且没有 workspace escape。
- Java/Python 对同一 fake 的 HTTP/SSE/文件副作用等价。
- 切换/回滚不破坏共享卷中的已有产物。
```

## 阶段 7：核心 Agent Runtime

```text
Goal
迁移 ReAct 与 Plan-Solve 主循环、模型选择/fallback、prompt/message 映射、tool call、usage、ledger/replay，并与阶段 5 的 SSE/run-control 内核整合。

Context
主要 Java 代码位于 Reactor-agent-domain 的 runtime/reactor/ledger 和 Reactor-agent-case 的 execute/dispatch/run。不要机械替换为某个 agent 框架；先定义项目内部 ModelPort、ToolPort、EventSink 和 repository ports，再写 provider adapter。

Constraints
- scripted fake 下做精确事件/数据库比较；真实 provider 只比较结构不变量，不比较自然语言逐字文本。
- 保持消息角色/顺序、tool-call ID、JSON Schema、finish reason、usage、最大轮次和 final projection。
- 流式重试只能发生在首个可见 chunk 之前；有副作用的 tool 不得透明重放。
- 保持有界并发、busy 响应、TaskGroup/cancellation 传播和 ledger start/finish 生命周期。
- 主 stream 与 stop/inject/follow/HITL resume 作为原子路由族设计切换。

Done when
- fake LLM/tool 下 Java/Python 的事件状态机、tool call/result 配对、ledger、replay 和终态等价。
- 并发上限、拒绝、timeout、cancel、fallback、最大轮次和中途故障测试通过。
- recorded sessions 可幂等 replay，无重复/丢失语义事件。
- 原子族的 sticky routing、drain 和紧急回滚方案已实际演练后才允许灰度。
```

## 阶段 8：HITL、记忆、子 Agent、后台任务与 Data Agent

一次只从下面选择一个子域，不要在同一 ExecPlan 中全部实现。

```text
Goal
迁移高级状态子域 <ask-user | plan-approval | memory | sub-agent | background-task | data-agent>，保持持久状态、恢复、并发竞争和外部数据源语义。

Context
Ask User/Plan Approval 使用条件 UPDATE/CAS 和 in-memory pending registry；memory 包含 working turns/messages、compaction 和 LTM；sub-agent/background 涉及父子取消与重启恢复；Data Agent 还依赖 ES7、Qdrant、ClickHouse/JDBC 和 SQL 安全。

Constraints
- CAS 必须使用带状态谓词的单条 SQL；0 row 是冲突或幂等重复，不得无条件当成功。
- 覆盖进程重启、孤儿 running 状态、重复请求、部分失败和恢复。
- memory/replay 验证语义事件不重不漏；compaction 不丢保护消息。
- Data Agent 最后迁移，按数据源分别使用 fixture，并加入只读/SQL 注入/方言安全测试。
- 外部 provider 全部 fake；任何 live 验证都必须显式、手工、可审计。

Done when
- 正常、竞争、重复、超时、取消、重启和恢复场景通过。
- CAS 竞争只有一个成功者，数据库和内存 registry 状态一致。
- 父子任务取消后无孤儿 task，后台任务重启状态可解释。
- 所选子域有独立契约、指标、切换和回滚证据。
```

## 阶段 9：粘性灰度、全量与 Java 退役

```text
Goal
按稳定 visitor cohort 把已完成的路由族从 Java 灰度到 Python，达到全量并在观察期后安全退役 Java。

Context
活跃 run、follow、stop、inject 和 HITL resume 必须始终命中创建该 run 的 owner。Python 创建的进程内 run 不能被 Java 无损接管。progress.md 规定全 Python 14 天后停止 Java，再观察 14 天。

Constraints
- 灰度按 ai_agent_visitor_token 一致性 hash，不按单请求随机分流。
- 建议 1% → 5% → 25% → 50% → 100%，每级都有最短观察窗口和自动回滚阈值。
- 监控 HTTP/SSE 错误、异常终止、p95/p99、队列拒绝、DB conflict、ledger/replay mismatch、task/连接/RSS 增长。
- 普通回滚先停止接收新 run，并让 Python cohort drain；紧急回滚显式终止/标失败并要求用户重试，不伪装无损接续。
- Java 删除是最后一步；全量前不引入 Java 无法读取的 Python-only enum/schema。

Done when
- 每一级灰度和回滚都已实际演练并留存证据。
- 100% Python 连续 14 天满足锁定 SLO；停止 Java 后再连续观察 14 天。
- 数据对账、活跃 run drain、告警、runbook 和灾难回滚通过评审。
- 最后才删除 Java 构建、镜像、路由和已被替代代码，并再次运行完整验收。
```

## 独立验收 / 代码审查提示词

在新的 Codex 会话或独立 worktree 中使用，不让实现者只审自己的结论：

```text
请作为独立迁移验收者审查当前 diff，不实现新功能。先读 AGENTS.md、对应 ExecPlan 和 docs/python-migration 下的契约、所有权、风险与进度文档。

按严重度报告问题，优先寻找行为回归而非格式问题：
1. Java/Python HTTP、SSE、数据库、文件或副作用不等价；
2. 双写窗口、错误 owner、不能实际执行的切换/回滚；
3. visitor GET 的隐藏写入、run/SSE 原子族被拆分；
4. null、时间、排序、分页、HTTP 200 + business code、FastAPI 307/422 漂移；
5. 并发、取消、重试、CAS、backpressure、task/连接泄漏；
6. 路径穿越、凭证/Prompt 泄漏、live/paid 测试误入 CI；
7. 测试只覆盖实现细节，未证明外部可观察行为。

亲自运行适用的静态检查、单元、集成、契约和前端测试。核对测试前后 git status，确认没有覆盖用户改动。不要因为现有 Java 全量基线有已知 12 failures/53 errors 就忽略新增回归；将已知基线与本次新增失败分开。

输出：findings（带准确文件/行号与复现证据）、已运行命令、通过项、未验证项、是否满足 ExecPlan 的 Done when、是否允许切流。若无问题，明确写出仍存在的残余风险。
```

## 快速修复提示词

当契约测试出现单个差异时使用：

```text
这是同一固定输入下的 Java 参考响应、Python 响应和契约 diff：<粘贴净化后的最小证据>。

请追踪 Java controller → application service → repository/mapper → serializer，以及 Python 对应路径，解释差异的最小根因。只修复导致该差异的 Python 行为，并添加一个会在修复前失败、修复后通过的回归测试。不要通过扩大 ignore/normalization、删除字段或修改 Java golden 来让测试变绿，除非你能证明参考行为本身录制错误。运行相关 tests、Ruff、mypy 和该 case 的 contract；更新 ExecPlan 的发现和决定记录。
```
