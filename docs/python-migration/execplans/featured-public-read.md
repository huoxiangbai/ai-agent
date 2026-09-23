# Featured conversations 公共只读垂直切片（Phase 3A）

本 ExecPlan 遵循 `docs/python-migration/PLANS.md`，执行期间必须保持自包含并持续更新。

## Purpose / Big Picture

在 `backend-python/` 实现首个真正无身份写副作用的垂直切片：3 条 public featured GET。保存的 Java golden（`backend-python/tests/contract/golden/java-initial.json`）与 Python 响应必须零未解释差异。它是 Phase 3B（Nginx 精确切流 + 回滚演练）的前置。

成功可直接观察：`uv run reactor-contract … --golden … --response …` 报告 3/3 `matched: true`，且 Python 在只读账号 `reactor_py_ro` 下能服务三接口。

## Scope

**路由（全 GET）：**

- `GET /api/agent/featured-conversations/home`
- `GET /api/agent/featured-conversations`
- `GET /api/agent/featured-conversations/{featuredId}`

**包含：** Python 实现（SQLAlchemy Core/显式 SQL 复刻 MyBatis 语义，含 execution-ledger replay 投影）；unit + repository integration 测试；Java stub characterization 测试；只读账号运行验证 + compose 切 `reactor_py_ro`；契约对比（3 例零差异）；前端 consumer tests 运行；文档同步。

**不包含：** Nginx 修改（切流步骤只写在本文 Cutover and Rollback，Phase 3B 执行）；admin 写接口；`VisitorIdentityFilter` 相关路由；schema 变更/Alembic；Java/Python 双写；React UI / `reactor-tool` / `reactor-sandbox` / `runtime/skills` 行为变更；真实 provider 调用；启动 Java/重录 golden。

**工作区用户资产（禁触碰）：** `?? .workbuddy/`、`M docs/python-migration/database-ownership.md`、`M docs/python-migration/risk-register.md`（可增量追加，不得回退现有内容）、`?? db/migrations/20260923_provision_phase3_readonly_account.sql`、`reactor-tool/.env`（绝不读取）、`/usr/local/var/mysql`（绝不触碰）。

## Progress

- [x] (2026-09-23) 归档 `git status --short`；建立本 ExecPlan。
- [x] (2026-09-23) domain 纯层 + unit 测试。
- [x] (2026-09-23) application 用例 + 端口 + fake 单测。
- [x] (2026-09-23) infrastructure SQL + integration（含 RO 拒写，4 例 `ERROR 1142`）。
- [x] (2026-09-23) api 路由 + `main.py` 接线 + 路由测试。
- [x] (2026-09-23) 契约对比 3/3 零差异 + 4 个前端 vitest 文件。
- [x] (2026-09-23) compose 切 `reactor_py_ro`（`docker compose config --quiet` exit 0）。
- [x] (2026-09-23) Java characterization 测试（本类 13/13）。
- [x] (2026-09-23) tool 帧族 10/10 逐字节移植（推翻原 deferred 决策）+ 仓库层 3 处修复 + `test_tool_projectors.py` 50 例。
- [x] (2026-09-23) 文档同步 + 最终门禁 + `git diff` 自审。
- [ ] (blocked) repository integration 重跑（edge seed 覆盖本轮改过的 `_output_file_refs`/`_FILE_REF_TOOLS`；需 `reactor_py_ro` 口令）。
- [ ] (blocked) contract 重录 + R-28 复查（需 `reactor_py_ro` 口令 + 只灌 `contract-seed.sql` 的库）。

## Surprises & Discoveries

- Observation: `GptProcessResult` 的 `response/responseAll/responseType/packageType` 在 builder 路径下序列化为 **null**，不是字段初始化器的 `""`/`"markdown"`/`"result"`。
  Evidence: Lombok `@Builder` 无 `@Builder.Default` 会忽略字段初始化器；`tests/contract/golden/java-initial.json` 的两帧均发 null。
- Observation: golden 第 2 帧来自 `ReplayProjector.appendRunSummaryFallback`（`messageId=<reqId>:summary`、`taskOrder=2`、随机 `taskId`），不是 `HistoryReplayPrinter.buildFallbackConclusion`（`taskId=<reqId>-summary`、`taskOrder=1`、会写 `response`）。fixture 下 printer 是 no-op。
  Evidence: `ReplayProjector.java:381-419` vs `HistoryReplayPrinter.java:52-88`；golden 帧 2 的 `taskId` 是随机 UUID（已 allowlist）且 `messageOrder=1`（key 为 `taskId+":result"`）。
- Observation: LLM-only 回放路径把 `response_text` **无条件**投为过程帧；只有 mixed 路径受 `shouldProjectResponseTextAsProcess` 约束。fixture 走 LLM-only 所以出现 `tool_thought` 帧尽管 `tool_call_count=0`。
  Evidence: `ReplayProjector.projectLlmHistory:90-105` vs `projectMixedHistory:159-181`。
- Observation: 本切片按用户决策不启动 Java，Spring 查询参数强转失败的 400 错误体是推导值而非实测值。
  Evidence: 用户 2026-09-23 证据决策（Python 测试 + Java stub characterization，不录 golden）；已在 `api-contracts.md` 登记为未探测项。
- Observation: `ai_agent_tool_invocation` 的列名是 **`llm_oberserve`**（schema 拼写错误，MyBatis 映射成 `llmObservation`）。照 `llm_observation` 写 SELECT 会直接 `Unknown column`。
  Evidence: `tool_invocation_ledger_mapper.xml` resultMap；`Reactor-agent-app/src/main/resources/db/schema.sql`。Python 侧 `_tool_view` 已按 `llm_oberserve` 读。
- Observation: `ai_agent_tool_invocation` **没有** `request_id` / `session_id` 列——两者挂在 run 上，由 `ToolInvocationViewMap` 的 join 补齐。Python 侧在 `query_run_detail` 里从 owning run 赋值。
  Evidence: `db/schema.sql`；`Reactor-agent-app/.../ExecutionLedgerRepositoryTest.java` 的 view-map 断言。
- Observation: `ai_agent_featured_conversation.session_id` 上有 **UNIQUE** 约束 `uk_featured_conversation_session_id`。多条 featured 不能共享一个 session，否则 `ERROR 1062`。
  Evidence: `db/schema.sql`；edge seed 首次灌入即报 1062，改为每条 featured 一个 session 后通过。
- Observation: `ai_agent_llm_invocation.call_kind` 是 `VARCHAR(16)`，装不下常量 `internalDigitalEmployee`（23 字符）。fixture 只能用 `internalCompact`（15 字符）走 SQL 路径；`internalDigitalEmployee` 的跳过逻辑由 unit 测试覆盖。
  Evidence: `db/schema.sql` 列定义；插入报 `Data too long`。
- Observation: **`explain` 是 MySQL 保留字**。`ai_agent_tool_output_code_interpreter.explain` 不加反引号直接 `ERROR 1064`。
  Evidence: `_read_tool_output` 首版 3 例 integration 失败；改为每个列名 `` `name` `` 后全绿。
- Observation: MySQL 9.3 **移除了 `mysql_native_password`**，`caching_sha2_password` 走 TCP 需要 `cryptography` 包做 RSA 交换，否则 asyncmy 直接 `RuntimeError`。
  Evidence: 后端启动 503/500；`uv add cryptography` 后正常（`cryptography==50.0.1`）。已加入 `pyproject.toml`。
- Observation: 本 Starlette 的 `JSONResponse.__init__()` **没有 `ensure_ascii` 形参**；`render()` 内部已硬编码 `ensure_ascii=False`。传该 kwarg 直接 `TypeError`。
  Evidence: 9 例路由测试失败；去掉 kwarg 后通过，非 ASCII 正文仍不 `\u` 转义。
- Observation: **契约录制与 edge-case integration 套件绝不能共享同一个已灌库。** edge seed 的 ONLINE 行（sort 500/400/200/150）会插到 contract fixture 前面，home/list 两例立刻从 2 行变 6 行，16–17 处差异。
  Evidence: 先拿到 3/3 零差异，灌 edge seed 后 `featured-home-default` / `featured-list-first-page` 回归；清掉 edge 行再录即恢复 3/3。R-28 复查（重灌重录 cmp）在干净 contract-seed 上 **0 处差异**，连 allowlist 的 `taskId` 都一致（录制时已置哨兵）。
- Observation: surefire 2.6 在 `-Dtest='FeaturedConversation*'` 下会把 **嵌套 stub 类** 当测试跑，每个报 `initializationError`。这是既有噪音（`FeaturedConversationPublicControllerTest$Stub…` / `FeaturedConversationRepositoryTest$InMemory…` 同样中招），不是本切片引入。
  Evidence: `mvn -Dtest='FeaturedConversation*'` 输出 28 run / 7 error，其中 `FeaturedConversationPublicQueryApplicationServiceTest` 本类 **13 run / 0 error**。按 R-02/R-18 只看本类结果。
- Observation: `-Dtest=…` 会先在无测试的上游模块（`Reactor-agent-api` 等）上因 "No tests matching pattern" 直接失败。必须加 `-Dsurefire.failIfNoSpecifiedTests=false`。
  Evidence: 首次 `mvn` 在 `Reactor-agent-api` 即 FAILURE；加参后 8 模块全部编译通过。
- Observation: `reactor-contract` 在**比较阶段也会重新做 `${CONTRACT_*}` 环境变量替换**；变量缺失的用例进报告的 `skipped` 数组（如 `"featured-detail-fixture: missing CONTRACT_FEATURED_ID"`），**不进** `cases`，且进程仍 **exit 0**。只看 exit code 会把 2/3 误报成通过。
  Evidence: 首次离线比较只导出 golden/response 路径、未导出 `CONTRACT_*`，报告 `cases:2, skipped:1` 但 exit 0；补上三个变量后 `cases:3, skipped:[]`，3/3 `matched:true`、`differences:[]`。
- Observation: 报告里差异字段名是 **`differences`**（不是 `diffs`），空差异为 `[]` 而非缺席。用 `c.get('diffs') or c.get('differences') or []` 取值会把空列表误读成 `None`。
  Evidence: `build/contract-report-offline.json` 每例键为 `['name','matched','java','python','differences']`。
- Observation: `contract-seed.sql` **不插入**任何 `ai_agent_tool_*` / `ai_agent_artifact` 行（只 DELETE 清空），所以 3 条 featured golden 走不到 tool 注水路径；`featured_read_edge_seed.sql` 则**会**插 `ai_agent_tool_invocation` + `ai_agent_tool_output_code_interpreter` + `ai_agent_artifact`，正是本轮改过的 `_output_file_refs` / `_FILE_REF_TOOLS` 所覆盖的路径。
  Evidence: 两份 seed 的 `INSERT INTO` 清单比对。结论：离线契约对比对本轮仓库改动仍有效，但 **edge integration 套件必须重跑**才算覆盖当前代码。deep_search 的 `_rebuild_chapters` 两份 seed 都不覆盖。

## Decision Log

- Decision: 边界行为用 Python unit + repository integration 钉死，同时补 Java stub JUnit characterization（不起服务、不录 golden）；端到端仅对比已保存的 3 条 featured golden。
  Rationale: 避开 R-31（Java/mysqld 启动脆弱），同时保留 PLANS.md 要求的 Java characterization 证据。
  Date/Author: 2026-09-23 / user + Codex
- Decision: 契约对比用 3 例 manifest `phase3-featured.json` + 从 `java-initial.json` 原样导出的 `java-featured.json`。
  Rationale: 7 例 golden 里另外 4 例本切片不实现，混跑会把"缺实现"误报成"缺字段"。快照字节不动，只做子集导出。
  Date/Author: 2026-09-23 / Codex
- Decision: `DatabaseProtocol` 保持 `{start,ping,close}` 不扩展；业务 SQL 走独立 `ConnectionProvider`。
  Rationale: `tests/unit/test_health.py::FakeDatabase` 依赖该协议形状，扩展协议会破坏无关测试。
  Date/Author: 2026-09-23 / Codex
- Decision: query 参数声明 `str | None`，由 `api/coercion.py` 复刻 Spring `StringToNumberConverter`（missing/空/空白→默认；不可解析→400 非 422）。
  Rationale: FastAPI 的 `int` 声明会在非法值上返回 422 + `0002`，与 Java 的 400 + BasicErrorController 形状不符。
  Date/Author: 2026-09-23 / Codex
- Decision: **契约录制库与 edge-case integration 库必须物理隔离**——同一 throwaway 库上只能二选一存在 seed。录制前清 edge 行（或只灌 `contract-seed.sql`），integration 前再灌 `featured_read_edge_seed.sql`。
  Rationale: edge 行按 `sort_order DESC` 会把 fixture 行挤出 home/list 首屏，直接污染 golden 比对。这不是实现缺陷，是 fixture 污染。
  Date/Author: 2026-09-23 / Codex
- Decision: 契约录制与 R-28 复查都在**只灌 `contract-seed.sql`** 的库上做；integration 套件独占 `contract-seed.sql` + `featured_read_edge_seed.sql`。
  Rationale: 两者对库内容的期望不同，共用必然互相破坏；文档里写死顺序比每次口头提醒可靠。
  Date/Author: 2026-09-23 / Codex
- Decision: Python 依赖显式新增 `cryptography`（连带 `cffi` / `pycparser`）。
  Rationale: MySQL 9.3 无 `mysql_native_password`，asyncmy 走 `caching_sha2_password` TCP 必须有它；这是运行硬依赖，不是可选工具。
  Date/Author: 2026-09-23 / Codex
- Decision: `docker-compose.yml` 里 Python 服务改用独立的 `REACTOR_PY_MYSQL_USER`（默认 `reactor_py_ro`）/ `REACTOR_PY_MYSQL_PASSWORD`（必填），**不再复用** `MYSQL_USER`/`MYSQL_PASSWORD`。Java 服务保持原样。
  Rationale: R-22 单写者要求 Python 侧只有 SELECT；复用写账号等于没有技术强制。两个环境变量名不同，避免误配到写账号。
  Date/Author: 2026-09-23 / Codex
- ~~Decision: tool 帧族的 resultMap 内层形状（CanvasPublish / DataAnalysis / ImageGeneration / DeepSearch / GenUi / AskUserQuestion）**显式 deferred** 到后续切片；CodeInterpreter 与 default/`tool_result` 已对齐。~~
  Rationale: 3 条 golden 用例只走 LLM-only + summary fallback 路径，不产生 tool 帧，这些形状**未被 golden 覆盖**。在没有 Java 实测对照的情况下照源码猜内层键序，风险是产出"看起来对但契约错"的帧。
  Date/Author: 2026-09-23 / Codex
  **Superseded 2026-09-23（同日）——见下条。**
- Decision: 10 个 tool 投影帧族全部按 Java 源码**逐字节移植**（含 `ArtifactRelativePath` / `ToolArtifactFormatter.normalizeWorkspacePath` / `mergeFileRefs` 三分支 / `markMissingLinks` 的 `String.valueOf(null)=="null"` 语义），**不再 deferred**；`domain/gen_ui_schema.py` 同步移植 `GenUiSchema` + `GenUiCatalog.ALLOWED_KINDS`。形状由 `tests/unit/test_tool_projectors.py`（50 例）按**内层键序**钉死，而非靠 golden。
  Rationale: 与其登记"猜的形状"，不如把 Java 源码当规格直接移植并用键序断言锁住。逐条核对源码后推翻了三处直觉：`toToolFileInfo` 会**丢弃** null/空白 URL（所以 `String.valueOf(null)` 语义只经 `enrichFromArtifacts.putIfAbsent` 才会咬人）；`originFileName` 原样返回而只有 `description` 剥 `workspace:` 前缀；`normalizeWorkspacePath` **不合并**中间重复斜杠。`fileName` 兜底会恒定产出 `relativePath`+`originFileName` 键对。
  Date/Author: 2026-09-23 / Codex
- Decision: `_output_file_refs` 补上 `visibility == "visible"` 谓词；deep_search 注水改为 `stages` + `_rebuild_chapters(stages)`（复刻 `ToolOutputReaderImpl.rebuildChapters`）；`fileRefs` 只挂在 `_FILE_REF_TOOLS` 五类输出上。
  Rationale: 三处都是仓库层真实缺陷，不是风格问题。`queryOutputArtifactsByToolInvocationId` 明确要 `artifact_role='output' AND visibility='visible'`；chapters 在 `ai_agent_tool_output_deep_search` 上**没有列**，只能从 `chapter_summary` 阶段重建；Java 的 deep_search / emit_ui_* 输出类型**不声明** `fileRefs` 字段，多挂就多字段（比较器里算差异）。
  Date/Author: 2026-09-23 / Codex

## Outcomes & Retrospective

**达成（2026-09-23）：**

- 3 条 public featured GET 在 `backend-python/` 落地，只读 SQL、无身份写副作用、无应用层双写。
- 契约对比 **3/3 `matched: true`，0 未解释差异，exit 0**（`build/contract-report.json`）。tool 帧族重写后复跑离线对比（`build/contract-report-offline.json`）仍 3/3 零差异——但用的是**重写前录制**的 `build/python-responses.json`；`contract-seed.sql` 不插 tool/artifact 行，故重写碰不到该 3 例的产出路径（推论，非重录实测）。
- R-28 可重复性：重灌 `contract-seed.sql` 重录，与首次录制 **0 处差异**（`taskId` 录制时即置哨兵）。
- Python 单测 **183** 通过（tool 帧族重写后：133 → 183）；integration 23 通过（含 4 例 `reactor_py_ro` 下 `ERROR 1142` 拒写）——**该 23 例跑在重写前的仓库代码上**，重写后的重跑见下方 blocked 项；4 个前端 vitest 文件 6 测试通过。
- Java characterization `FeaturedConversationPublicQueryApplicationServiceTest` **13/13**（钳制、offset、空白 id、非 ONLINE、`session_history_missing`、空表、排序透传、`contentLastActiveAt` 来源）。同轮 `FeaturedConversationRepositoryTest` 2/2、`FeaturedConversationAdminControllerTest` 3/3 亦绿；`mvn` 总计 28 run / 7 error 全是嵌套 stub 的 `initializationError` 噪音（R-02/R-18 只看本类结果）。
- Python 在只读账号 `reactor_py_ro` 下实际服务了三接口（contract 录制 + integration 即运行证据）。
- `docker-compose.yml` 切 `reactor_py_ro`，`docker compose config --quiet` exit 0（重跑确认）。
- tool 帧族 10/10 逐字节移植 + `gen_ui_schema.py`；仓库层 3 处缺陷修复（visibility 谓词 / `_rebuild_chapters` / `_FILE_REF_TOOLS`）。门禁：ruff 全绿、mypy 48 文件全绿、`pytest -m "not integration"` **183 passed / 23 deselected**。

**明确 deferred（不是"已完成"）：**

1. ~~**tool 帧族 resultMap 内层形状**（6/10）~~ **已闭合 2026-09-23**：10/10 帧族全部按 Java 源码逐字节移植，形状由 `tests/unit/test_tool_projectors.py`（50 例）按内层键序钉死。**仍未被 golden 验证**（3 条 featured golden 不产生 tool 帧），也**未被 integration 验证**——`_rebuild_chapters` 两份 seed 都不覆盖。残余缺口见下。
   - 残余：`UserQuestionReader` 只移植为默认 `None` 的 Protocol（对齐 Java 默认构造传 null repo 的路径），**尚未绑定 DB 适配器**；带持久化 question 的 `ask_user_question` 帧只能由 fake 驱动。
   - 残余：deep_search `_rebuild_chapters` 无 fixture 覆盖（两份 seed 都不插 `ai_agent_tool_output_deep_search`）。
2. **Spring BasicErrorController 400 错误体**（查询参数强转失败）为推导值，未实测（本切片不启 Java）。
3. **Nginx 切流**：本文 Cutover and Rollback 只是草案，Phase 3B 才落地 `docker/nginx-featured-python.conf`。本切片未改 Nginx。
4. **admin 写接口**、`VisitorIdentityFilter` 相关路由：按 Scope 明确不做。
5. **`reactor_py_ro` 口令不在仓库内**（设计如此）。integration 与 contract 重录需要用户提供该口令；本轮已跑的离线契约对比用的是**重写前录制**的 `build/python-responses.json`。由于 `contract-seed.sql` 不插 tool/artifact 行，本轮仓库改动碰不到那 3 条 golden 的产出路径，故该证据仍成立——但这属于**推论**，不是重录实测。

**回滚方法：** 纯读切片，无数据库状态需要恢复。Phase 3B 切流后回滚 = 注释/删除 `include docker/nginx-featured-python.conf` + `nginx -t && nginx -s reload`（或 `docker compose restart frontend`），流量即回 Java。

**Retrospective：**

- 做对了：先录/比 golden 再动实现，把 Lombok `@Builder`、Jackson 时间格式、LLM-only vs mixed 不对称这三类"照抄默认值就契约失败"的坑提前钉死；RO 账号 + 1142 拒写测试把"只读"从口头约束变成可执行断言。
- 做错了：把 edge seed 与 contract seed 灌进同一个库，导致一次真实的契约回归（16–17 处差异）。教训已写入 Decision Log——**fixture 隔离是契约测试的前提，不是可选项**。
- 下次改进：契约/集成双套件各用独立 throwaway schema（`ai_agent_station_contract` / `ai_agent_station_edge`），而不是靠执行顺序保证干净。Phase 3B 落地时一并做。

## Context and Orientation

- Java 入口：`Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/agent/AgentFeaturedConversationController.java`
- Java 用例：`Reactor-agent-case/src/main/java/org/wwz/ai/application/agent/featured/FeaturedConversationPublicQueryApplicationService.java`
- 回放链：`Reactor-agent-domain/.../ledger/replay/{ConversationHistoryReplayService,ReplayProjector,HistoryReplayPrinter,SummaryReplayResultResolver}.java` + `projector/impl/*`
- SQL：`Reactor-agent-app/src/main/resources/mybatis/mapper/featured_conversation_mapper.xml` + `dialogue_{session,run}_ledger_mapper.xml` + `llm_invocation_ledger_mapper.xml` + `tool_invocation_ledger_mapper.xml` + `artifact_ledger_mapper.xml` + 8 张 `tool_output_*`
- 前端消费者：`ui/src/services/featuredConversation.ts`、`ui/src/pages/{FeaturedConversations,FeaturedConversationDetail,Home}`
- Python 目标：`backend-python/src/reactor_backend/`（`api/` `application/` `domain/` `infrastructure/`）
- 部署路由：`docker/nginx.conf` 的 `location /api/` 整体打到 Java `:8100`；Python `:8200` 尚无 upstream（Phase 3B 才切）
- 相关文档：`docs/python-migration/{api-contracts,database-ownership,risk-register,progress,inventory}.md`

## Contract and Invariants

见 `docs/python-migration/api-contracts.md` 与 golden。要点：

- 信封 `{"code":"0000","info":"成功","data":...}`；not-found/非法输入 **不走** 0001/0002 —— HTTP 200 + `data:null` 或钳制值。
- `/home`：`limit` 默认 6，`Math.max(1,limit)` 无上限；`data` 为裸 list（空 → `[]`）。
- 列表：`pageNo`/`pageSize` 默认 1/20，均下限钳制；`offset=(pageNo-1)*pageSize`；`total` 与分页无关。
- detail：空白 id / 行缺失 / 非 ONLINE（`equalsIgnoreCase(trim())`）→ `data:null`；`contentUnavailableReason="session_history_missing"` 精确串。
- SQL 全部 `deleted=0`；`ORDER BY sort_order DESC, id DESC LIMIT :offset,:limit`。
- 时间 JSON：零毫秒省略小数（`"2026-01-02T10:00:00"`），非零毫秒 3 位；禁 `datetime.isoformat()`。
- 帧信封 builder 路径下 `response/responseAll/responseType/packageType` 必须为 null（Lombok `@Builder` 陷阱）。
- `messageTime` 为 `LocalDateTime.atZone(systemDefault)` 的 epoch 毫秒 **字符串**；Python 进程须 `TZ=Asia/Shanghai`（R-07）。
- `summary_text` 保留含 `$$$` 的原文；`artifactKeys` = 首个 `$$$` 后按 `[、,，\r\n]+` 切分。
- 非确定字段只允许按 case 的 JSON Pointer 放行（本切片仅 `/body/data/historyDetail/runs/*/replayFrames/*/resultMap/eventData/taskId`）；禁全局忽略；golden 缺字段永远算差异。

## Plan of Work

### 文件布局（`backend-python/src/reactor_backend/`）

依赖方向 `api → application → domain`，`infrastructure` 实现端口。SQL 只在 `infrastructure/`。

- `domain/execution_ledger_constants.py` — 状态常量、call_kind、entry_agent、artifact role/visibility
- `domain/time_format.py` — Jackson LocalDateTime 字符串 + epoch 毫秒串（`ZoneId.systemDefault` 语义）
- `domain/summary_resolver.py` — `SummaryReplayResultResolver` 移植
- `domain/context_usage.py` — `ContextUsagePayload` 组装（不含模型目录，走端口）
- `domain/featured_conversation.py` — 钳制/offset/tags/is_online/卡片与 detail 组装
- `domain/ledger_types.py` — 视图 dataclass（session/run/llm/tool/artifact）+ `EventResult` 移植
- `domain/replay_projector.py` — `projectHistory` 全分支 + `toFrame`
- `domain/tool_projectors.py` — registry + 帧族 + 共享 envelope/`build_artifact_refs`/`merge_file_refs`
- `domain/history_replay.py` — `HistoryReplayPrinter` + 会话头组装 + 状态标签 + deepThink + restore_title
- `application/featured_conversation_query.py` — `FeaturedConversationReader` / `ExecutionLedgerReader` / `ModelWindowResolver` 端口 + 用例
- `infrastructure/database/engine.py` — 保持 `DatabaseProtocol` 不变；新增 `ConnectionProvider`
- `infrastructure/repositories/featured_conversation_repository.py`、`execution_ledger_repository.py`、`llm_model_window.py`
- `api/routers/featured_conversations.py`、`api/coercion.py`、`api/presenters.py`
- `main.py` — `redirect_slashes=False`；挂载路由
- `docker-compose.yml` — 仅 Python 服务切 `reactor_py_ro`

### 测试先行

unit（`tests/unit/`）：`test_featured_conversation.py`、`test_time_format.py`、`test_summary_resolver.py`、`test_context_usage.py`、`test_replay_projector.py`、`test_tool_projectors.py`、`test_history_replay_printer.py`、`test_featured_routes.py`。
integration（`tests/integration/`）：`test_featured_read_repository.py`、`test_readonly_account_denies_writes.py`、`fixtures/featured_read_edge_seed.sql`。
contract：`tests/contract/cases/phase3-featured.json` + `tests/contract/golden/java-featured.json`（原样导出）。
Java：`Reactor-agent-app/src/test/java/org/wwz/ai/test/domain/FeaturedConversationPublicQueryApplicationServiceTest.java`。

## Concrete Steps

```bash
# 0) 状态归档
git status --short

# 1) Python 门禁
cd backend-python
uv sync --all-groups
uv run ruff check .
uv run mypy src
uv run pytest -m "not integration"

# 2) integration（throwaway mysqld，端口 3307，datadir 在 build/ 下）
#    mysqld --no-defaults --datadir=build/contract-mysql/data \
#      --socket=build/contract-mysql/mysql.sock --port=3307
#    （绝不碰 /usr/local/var/mysql；zsh 下带 [] 的参数要整体加引号 —— R-31）
#    !! 实例上的库名是 ai_agent_station_contract，不是 ai-agent-station !!
TEST_MYSQL_URL='mysql+asyncmy://reactor_py_ro:<secret>@127.0.0.1:3307/ai_agent_station_contract?charset=utf8mb4' \
  uv run pytest -m integration

# 3) 契约对比（TZ 必须 Asia/Shanghai；throwaway 库**只灌 contract-seed.sql**）
#    !! 契约录制与 edge integration 绝不能共享已灌库 —— 见 Decision Log !!
#    integration 跑完后必须清掉 edge 行（或重灌 contract-seed.sql）再录契约。
cd backend-python
mysql ... ai_agent_station_contract < tests/contract/fixtures/contract-seed.sql
TZ=Asia/Shanghai CONTRACT_VISITOR_TOKEN=fixture-raw-token \
  CONTRACT_SESSION_ID=fixture-session CONTRACT_FEATURED_ID=fixture-featured \
  PYTHON_BASE_URL=http://127.0.0.1:8200 \
  uv run reactor-contract tests/contract/cases/phase3-featured.json \
  --record-python --output build/python-responses.json
#    !! 比较时也必须导出同组 CONTRACT_* 变量；缺 CONTRACT_FEATURED_ID 会把 detail
#       例静默 skip（报告 `skipped:["…: missing CONTRACT_FEATURED_ID"]`，只出 2/3）!!
CONTRACT_VISITOR_TOKEN=fixture-raw-token CONTRACT_SESSION_ID=fixture-session \
CONTRACT_FEATURED_ID=fixture-featured \
  uv run reactor-contract tests/contract/cases/phase3-featured.json \
  --golden tests/contract/golden/java-featured.json \
  --response build/python-responses.json --output build/contract-report.json

# 3b) R-28 可重复性：重灌 contract-seed.sql、重录、与上一次录制比对
#     期望 0 处差异（taskId 录制时已置哨兵）

# 3c) integration 前再灌 edge seed（此后再录契约会污染，见上）
mysql ... ai_agent_station_contract < tests/integration/fixtures/featured_read_edge_seed.sql

# 4) 前端 consumer tests（不改 ui/）
cd ui && npx vitest run src/services/featuredConversation.test.ts \
  src/pages/FeaturedConversations/view.test.tsx \
  src/pages/FeaturedConversationDetail/view.test.tsx \
  src/pages/Home/WelcomeView.test.tsx

# 5) Java characterization（只看本类结果；app 基线本身红 —— R-02/R-18）
#    failIfNoSpecifiedTests=false：上游模块无匹配测试时不要直接失败
mvn -B -pl Reactor-agent-app -am -Dtest='FeaturedConversation*' -DskipTests=false \
  -Dsurefire.failIfNoSpecifiedTests=false test

# 6) compose 语法
MYSQL_PASSWORD=test-only MYSQL_ROOT_PASSWORD=test-only REACTOR_PY_MYSQL_PASSWORD=test-only-ro \
  docker compose config --quiet
```

## Validation and Acceptance

- `uv run ruff check .` / `uv run mypy src` / `uv run pytest -m "not integration"` 全绿。
- `TEST_MYSQL_URL=… uv run pytest -m integration` 全绿，含 `reactor_py_ro` 下 INSERT/UPDATE/DELETE 报 `ERROR 1142`。
- 契约对比 exit 0、3/3 `matched:true`、零未解释差异（仅 allowlist 的 `taskId` 哨兵）。
- 4 个前端 vitest 文件全绿。
- `mvn -Dtest='FeaturedConversation*'` 本类全绿。
- `docker compose config --quiet` 通过。
- 只读账号下三接口可服务（integration + contract 录制即证据）。
- 边界覆盖：默认分页、下限钳制、空列表、not-found/null、ONLINE 过滤、排序、tags、时间、状态标签。
- `git status --short` + `git diff` 自审：无范围外改动、无秘密、`.workbuddy/` 未触碰、用户文档改动仅增量。

## Cutover and Rollback

本切片 **不改 Nginx**。Phase 3B 目标（`docker/nginx.conf` 现状：`location /api/` → `reactor_backend:8100`，Python 无 upstream）：

```nginx
upstream reactor_backend_python { server reactor-backend-python:8200; keepalive 32; }

# 三块单独文件 docker/nginx-featured-python.conf，由 nginx.conf include
location = /api/agent/featured-conversations/home {
    proxy_pass http://reactor_backend_python;
    # 与 /api/ 同款 proxy 头与超时
}
location = /api/agent/featured-conversations {
    proxy_pass http://reactor_backend_python;
    ...
}
location ~ ^/api/agent/featured-conversations/[^/]+$ {
    proxy_pass http://reactor_backend_python;
    ...
}
```

`=` 精确优先于前缀/正则；正则只吃单段 `{featuredId}`；多段/尾斜杠仍落 Java→404，与 Java 一致。

**切换顺序：** Python 带 `reactor_py_ro` 部署 → smoke/contract/vitest → 加三块 + `nginx -t && nginx -s reload` → 对 :80 重跑同组检查 → 更新 `database-ownership.md`。

**一键回滚：** 注释/删除该 `include` + `nginx -t && nginx -s reload`（或 `docker compose restart frontend`），流量即回 Java。纯读切片、无写、无活跃 run，**无数据库状态需恢复**。

## Idempotence and Recovery

- 实现与测试全部幂等：测试固定键 DELETE+INSERT；契约对比离线可重跑。
- 中断后从 `Progress` 未勾项继续；已跑门禁可直接复跑（无副作用）。
- 契约对比失败一半时：看 `build/contract-report.json` 的 diff 列表，修 Python 侧，**禁止**改 `java-initial.json` / `java-featured.json` 消差异。
- 切流失败一半时（Phase 3B）：nginx reload 回滚即可，无数据恢复步骤。

## Interfaces and Dependencies

**公共 HTTP：** 3 条 GET（见 Scope）。

**端口（`application/featured_conversation_query.py`）：**

- `FeaturedConversationReader.query_by_featured_id / query_online_list / count_online`
- `ExecutionLedgerReader.query_session / query_session_runs / query_run_detail`
- `ModelWindowResolver.max_input_tokens(model_name) -> int`

**适配器（`infrastructure/`）：** `FeaturedConversationRepository`、`ExecutionLedgerRepository`、`LlmModelWindowResolver`（读 `ai_client_model`）。

**第三方依赖：** 新增 `cryptography`（连带 `cffi` / `pycparser`）——MySQL 9.3 无 `mysql_native_password`，asyncmy 走 `caching_sha2_password` TCP 必须有它，否则运行期 `RuntimeError`。其余仍用已有的 `sqlalchemy[asyncio]`、`asyncmy`、`fastapi`、`pydantic`。

## Artifacts and Evidence

- 契约报告：`backend-python/build/contract-report.json`
- Python 录制：`backend-python/build/python-responses.json`
- golden：`backend-python/tests/contract/golden/java-featured.json`（从 `java-initial.json` 原样导出）
- 测试输出：见最终报告；不粘贴大段日志
- 切流配置草案：本文 Cutover and Rollback（Phase 3B 落地为 `docker/nginx-featured-python.conf`）
