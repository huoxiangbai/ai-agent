# Phase 2：Java/Python 契约实验室（可重复 golden 采集 + 离线比较）

本 ExecPlan 遵循 `docs/python-migration/PLANS.md`，执行期间必须保持自包含并持续更新。

## Purpose / Big Picture

Phase 0/1 治理复核（commit `c71605e3`）把文档与代码对齐了，但迁移仍**没有可信基线**：`tests/contract/golden/` 不存在、没有确定性数据库 fixture、比较只能 live 双跑、`fake-agent-request.json` 缺失、multipart/binary/SSE 未覆盖能力无 deferred 登记。Phase 3A（3 条 public featured GET）要求「保存的 Java golden 与 Python 响应零未解释差异」，没有本切片就无法验收。

本切片交付的是**测量能力**，不是业务行为：一条明确命令能在本地 Java + 测试 MySQL 上录制首批 7 条净化 golden；runner 能把 Python 响应与已存 Java golden **离线**比较并产出机器可读 diff；契约工具单测覆盖九个维度；additive field 政策文档与比较器一致；未覆盖能力显式 deferred。用户看不到新产品行为，看到的是「现在能证明等价了」。

## Scope

**包含：** `backend-python/src/reactor_backend/contracts/`（`models`/`normalize`/`http`/`sse`/`cli`/`sse_cli`）、`backend-python/tests/contract/`（`cases/`、`fixtures/`、`golden/`）、`backend-python/tests/unit/test_contract_*.py`、新建本 ExecPlan、同步 `docs/python-migration/{api-contracts,progress,risk-register}.md` 与 `tests/contract/README.md`。

**不包含：** 任何业务路由（Python 侧仍只有 `/internal/health/*`）；Nginx 切流；React UI / `reactor-tool` / `reactor-sandbox` / `runtime/skills`；`db/schema.sql` / `db/data.sql`；Java/Python 应用层双写；真实 LLM/MCP/搜索/图片 provider；生产凭证读取或打印；全局 ignore 扩大；SSE `event_id` 跨块语义变更。

**工作区用户资产（禁止触碰）：** `?? .workbuddy/` 不读取、不修改、不删除。`reactor-tool/.env` 存在（可能含真实凭证），**绝不读取或打印**。用户既有 Homebrew MySQL datadir `/usr/local/var/mysql` 存在但已停止，**全程不触碰**。

## Progress

- [x] (2026-09-23) M2 快照往返：`CookieSnapshot`/`HttpSnapshot`/`SseEvent`/`SseCapture` 补 `from_dict()`；`HttpSnapshot.as_dict()`/`SseCapture.as_dict()` 改为显式列表输出（`dataclasses.asdict` 保留 tuple，tuple 不是 `JsonValue`，allowlist walker 会炸）；`dump_snapshot`/`load_snapshot`/`load_capture_file`/`save_capture_file` 接通，不再是死代码。
- [x] (2026-09-23) M3 additive 机制：`normalize.drop_additive` 新增（仅删候选侧声明的增量键）；`compare_http`/`compare_sse` 接受 `ignored_json_pointers`；**一个 allowlist 两处语义**（采集期 `normalize_json` 哨兵替换 + 比较期 `drop_additive`）。
- [x] (2026-09-23) M3 加固：`normalize.py` 坏指针/结构错误抛 `ValueError`，不再静默 no-op。**计划内更正**：原定「未知键 ⇒ ValueError」与 additive 决策冲突（增量字段按定义单侧缺失），改为「**终末** dict 键缺失 = no-op；**中间** dict 键缺失 = `ValueError`」。
- [x] (2026-09-23) M4 确定性 fixture：`tests/contract/fixtures/contract-seed.sql`（7 张表，显式 `id` + ORDER-BY 列，`Asia/Shanghai`，DELETE-then-INSERT 幂等）+ `fixtures/skills/{contract-fixture-alpha,contract-fixture-beta}/SKILL.md`（钉死 `skills[]`，与仓库 `runtime/skills/` 解耦）。
- [x] (2026-09-23) M5 一条录制命令实跑：throwaway `mysqld`（3307 / 独立 datadir）+ Java（`prod` + test-only 覆盖）→ `tests/contract/golden/java-initial.json`，**7/7 case、`skipped: []`、15613 bytes、0 secret hit、7 个 `<contract-ignored>` 哨兵**。
- [x] (2026-09-23) M5 可重复性自检：fixture 重灌后重录，两份 golden **逐字节一致**。
- [x] (2026-09-23) M6 离线比较 CLI：`--record-java` / `--record-python` / `--golden` / `--response` 四模式共用同一 capture 形态；`--golden`+`--response` **完全离线**（无任何服务）；报告形态保持 `{"mode":"comparison","cases":[...],"skipped":[]}`。
- [x] (2026-09-23) M6 离线自证：golden vs 自身副本 ⇒ 7/7 `matched=true`、exit 0；六类对抗性变异 ⇒ exit 1，差异落在**恰好预期的路径与 reason**（见 Artifacts and Evidence）。
- [x] (2026-09-23) M7 SSE fake fixture + 范围声明：`fake-agent-request.json`（最小合法请求骨架，无密钥/无真实 prompt）；SSE 已覆盖/deferred 两栏写入 `tests/contract/README.md` 与 `api-contracts.md`。
- [x] (2026-09-23) M8 九维单测补齐：基线从 **15 passed / 1 deselected** 涨到 **44 passed / 1 deselected**（2 warnings）。
- [x] (2026-09-23) M9 能力级 deferred registry：multipart / 二进制导出 / 流式 ZIP Zip Slip / SSE 语料库 / 跨块 last-event-ID 五项，与路由级 registry 分开登记。
- [x] (2026-09-23) 门禁全绿：`uv run ruff check .` → All checks passed!；`uv run mypy src` → Success: no issues found in 29 source files；`uv run pytest -m "not integration"` → 44 passed, 1 deselected。
- [ ] (待用户批准提交) 本切片 diff 尚未 commit；`git status --short` 保持改动可见。

## Surprises & Discoveries

- Observation: `HttpSnapshot`/`SseCapture`/`CookieSnapshot` **只有 `as_dict()`，全仓库无 `from_dict`**；`cli.py` 只会 live 双跑；`http.dump_snapshot` 是死代码 —— 「离线比较」原本**结构上不可能**，不只是缺个 flag。
  Evidence: `contracts/models.py`、`contracts/cli.py`、`contracts/http.py`（本切片前）
- Observation: `normalize.json` 的「替换值但保留键」压不掉 `java_keys != python_keys` 的 key-set diff，「声明后放行增量」原本做不到。
  Evidence: `contracts/normalize.py`、`contracts/http.py::_compare`
- Observation: **计划内设计更正**——原定「未知键 ⇒ `ValueError`」与 additive 决策 1 直接冲突（增量字段按定义在单侧缺失）。实测/推演后定为：**终末** dict 键缺失 = no-op（allowlist 同时声明增量），**中间** dict 键缺失 = `ValueError`（打错路径不能假绿）；结构错误（非 int 列表下标、越界、降到标量）永远抛。
  Evidence: `contracts/normalize.py:10-21` docstring；`tests/unit/test_contract_normalize.py` 8 例
- Observation: **指针根必须是采集文档**（`HttpSnapshot.as_dict()`），不能只是 body。cookie 属性 `expires` 由 `max-age` + 服务器时钟派生（实测两次录制分别为 `Wed, 22 Sep 2027 20:23:35 GMT` 等），无法全局丢弃（禁止全局 ignore），必须能写成 `/cookies/*/attributes/expires`。因此 body 字段是 `/body/data/visitorId`、cookie 属性是 `/cookies/*/attributes/expires`，**共用一个命名空间**。SSE 的指针根仍是事件的 `data` 值。
  Evidence: `tests/unit/test_contract_http.py::test_allowlist_pointer_can_address_a_cookie_attribute`；`initial.json` case 1
- Observation: `dataclasses.asdict` 会把 `cookies`/`events` 留成 **tuple**，而 tuple 不是 `JsonValue` —— `*` 扇出会 `ValueError: cannot descend into tuple with pointer token '*'`。根因在 `as_dict`，不在 walker。
  Evidence: `contracts/models.py::HttpSnapshot.as_dict` 注释；`contracts/normalize.py::_replace`
- Observation: **`useTimes` 这个 allowlist 猜测是错的**。计划里假设 #4/#6 的非确定字段是 `replayFrames/*/useTimes`（`ReplayProjector` 缺时间戳时回退 `System.currentTimeMillis()`），实测录制中 `useTimes` **从未出现**，真正漂移的是 `resultMap/eventData/taskId` —— 一个回放期现铸的随机 UUID，不在 DB 里。两次录制分别为 `2d546ca0-…` 与 `e1c6af8f-…`。
  Evidence: 两次录制 diff；`initial.json` case 4/6 的 `ignored_json_pointers`
- Observation: **「cookie 无 `Secure`」在 prod profile 下是错的**。`application.yml` 默认 `visitor-cookie.secure: false`，但 `application-prod.yml` 在 `spring.config.activate.on-profile: prod` 下覆盖为 `secure: true`。我们用 `--spring.profiles.active=prod` 启动 ⇒ golden 里的 cookie **带 `Secure`**。录制环境与 profile 必须一并钉死，否则 golden 不可比。
  Evidence: `Reactor-agent-app/src/main/resources/application-prod.yml:155-235`；`tests/contract/golden/java-initial.json` 的 `secure: true`
- Observation: **macOS 系统级代理会劫持 `127.0.0.1`**。`urllib.request.getproxies()` 返回 `http://127.0.0.1:1082`（http 与 https 均是），`NO_PROXY` 未设置；httpx 默认 `trust_env=True` 会把本地请求也送进该代理，症状是 `RemoteProtocolError: Server disconnected without sending a response` 或裸 disconnect。**无任何 proxy 环境变量**，所以在 shell 里 `env | grep -i proxy` 查不出来。修复：契约工具所有 `httpx.AsyncClient` 一律 `trust_env=False`。
  Evidence: `contracts/cli.py`（3 处）、`contracts/sse_cli.py`（2 处）、`tests/unit/test_contract_sse.py` 真 socket 测试
- Observation: zsh 把 `--autobots.autoagent.skill.directories[0]=...` 当 glob 展开（`no matches found`），整条参数必须加引号。复现者必踩。
  Evidence: Java 首次启动失败日志
- Observation: MySQL 9.3 已移除 `mysql_native_password=ON` 变量，带该 flag 启动直接 `[ERROR] [MY-000067] unknown variable`。
  Evidence: `mysqld` 首次启动日志
- Observation: `api-contracts.md` 对 additive field 有**三处互相矛盾**表述（`:85` 容忍 / `:98` 容忍 / `:106` 差异），而实现走 `:106` 口径。本切片改文档，不改判定口径。
  Evidence: `api-contracts.md:85,98,106`
- Observation: `_compare` 对 dict 用 `sorted(java_keys & python_keys)` 递归 ⇒ **对象键序无关**，`SessionCapabilityService.itemMap` 的 `HashMap` 键序不是问题（省掉一整类 allowlist）。
  Evidence: `contracts/http.py::_compare`；`tests/unit/test_contract_http.py::test_http_comparator_ignores_object_key_order`
- Observation: fixture 列清单与 `schema.sql` 逐列核对一致；行数 `visitor_identity 1 / dialogue_session 2 / featured_conversation 2 / dialogue_run 1 / llm_invocation 1 / tool_invocation 0 / artifact 0 / session_capability 0 / client_tool_mcp 0`。空集合形态本身即契约。
  Evidence: `tests/contract/fixtures/contract-seed.sql` vs `Reactor-agent-app/src/main/resources/db/schema.sql`
- Observation: `db/migrations/` 在**仓库根**（1 个文件），不在 `Reactor-agent-app/src/main/resources/db/` 下。
  Evidence: `find . -type d -name migrations` → `./db/migrations`

## Decision Log

- Decision: additive field 采用「未声明即差异；按 case JSON Pointer 显式放行；**删除永不放行**」。
  Rationale: 与 `AGENTS.md`「非确定字段只能按 case 精确放行、禁止全局忽略」同口径；`api-contracts.md:106` 与现实现同向；`:85`/`:98` 是「消费者容忍」语义，须与「迁移比较器判定」拆开。用户 2026-09-22 确认。
  Date/Author: 2026-09-22 / 本切片执行者
- Decision: 录制运行时 = 本地 throwaway `mysqld`（独立 datadir + 3307）+ Java（`prod` profile + test-only 覆盖），不用 Docker。
  Rationale: Docker daemon 未运行；独立 datadir 保证不触碰 `/usr/local/var/mysql`；`application-test.yml` 被 gitignore（R-18），不新建它。用户 2026-09-22 确认。
  Date/Author: 2026-09-22 / 本切片执行者
- Decision: 首批 golden 覆盖 `initial.json` 全部 7 条（含 filter-protected 的 #1/#5/#6）。
  Rationale: manifest 本就声明为 initial safe manifest；顺带覆盖 Cookie 写副作用与 `Set-Cookie` 属性比较。用户 2026-09-22 确认。
  Date/Author: 2026-09-22 / 本切片执行者
- Decision: 离线比较的验收自证用「golden vs 自身副本」+「对抗性变异副本」，并在文档明写**这是比较器自证，不是 Python parity**。
  Rationale: Python 本阶段无业务路由，拿不到真实 Python 响应；伪造响应等于伪造覆盖率。真正的 Java/Python 端到端比较是 `progress.md` Phase 2 第 4 项，明确 gated 在 P3。
  Date/Author: 2026-09-22 / 本切片执行者
- Decision: `ignored_json_pointers` 单一列表同时承担「取值放行」与「增量放行」。
  Rationale: 用户选项原文是「在该 case 的 JSON Pointer allowlist 里显式放行」（单数）。代价：被声明的指针若双侧都有，取值也不再比较——这类字段本就声明为非确定，可接受，已写进 `models.py::NormalizationRules` docstring。
  Date/Author: 2026-09-22 / 本切片执行者
- Decision: **指针根从「body」扩为「采集文档」**（`HttpSnapshot.as_dict()`），SSE 仍以事件 `data` 为根。
  Rationale: cookie `expires` 是 `max-age` + 服务器时钟派生，属端点级非确定，但禁止全局忽略 ⇒ 必须可按 case 声明。只放宽这一处（根扩大），判定口径不变。
  Date/Author: 2026-09-23 / 本切片执行者
- Decision: normalize 加固采用**分裂规则**：终末 dict 键缺失 = no-op，中间 dict 键缺失 = `ValueError`。
  Rationale: 原定「未知键 ⇒ ValueError」会让 `drop_additive` 的合法增量声明直接抛错（增量字段按定义单侧缺失）。分裂规则同时满足「增量可声明」与「打错路径不能假绿」。计划内更正，非放松。
  Date/Author: 2026-09-23 / 本切片执行者
- Decision: 契约工具全部 `httpx.AsyncClient` 固定 `trust_env=False`。
  Rationale: 本机系统级代理会劫持 `127.0.0.1`；契约工具**只**与本地 Java/Python 服务通信，从不需要代理。这是工具配置，不改任何业务行为。
  Date/Author: 2026-09-23 / 本切片执行者
- Decision: `skills[]` 用 `tests/contract/fixtures/skills/` 钉死，录制时覆盖 `autobots.autoagent.skill.directories`，不读仓库 `runtime/skills/`。
  Rationale: 契约基线要钉**全部输入**，不只 DB。`runtime/skills/` 会随仓库演进导致 golden 过期。
  Date/Author: 2026-09-22 / 本切片执行者
- Decision: 本切片**不修** SSE `event_id` 跨块 last-event-ID 语义，登记 deferred。
  Rationale: 那是 SSE 语义变更，会改变比较结果，需单独批准。
  Date/Author: 2026-09-22 / 本切片执行者

## Outcomes & Retrospective

**已达成：** Phase 2 出口四条里的前三条全部落地且有实测证据——(1) 一条命令录制 7 条净化 golden，可逐字节重复；(2) `--golden`+`--response` 完全离线比较并产出机器可读 diff，自证通过且对抗性变异能被抓到预期路径；(3) `fake-agent-request.json` 补齐、`tests/contract/golden/` 有内容、SSE 范围两栏写清。第 4 条（真实 Java/Python 端到端比较）按 `progress.md` 明确 gated 在 P3，本切片不勾、也不假装。九维单测齐备，门禁全绿（44 passed / 1 deselected）。

**与初始目标的偏差（均为收紧，非放松）：**
1. normalize 加固从「未知键一律抛」改为分裂规则——原设计会让合法增量声明直接失败，是计划内错误。
2. 指针根从 body 扩为采集文档——原设计无法声明 cookie 属性级非确定字段。
3. allowlist 猜测 `useTimes` 被实测推翻，真实漂移是 `resultMap/eventData/taskId`。
4. 「cookie 无 `Secure`」被 prod profile 推翻，实为 `Secure: true`。

**遗留缺口：** P3 业务路由未实现，故无真实 Python 响应可比；`java-initial.json` 只覆盖 7/108 方法路由；multipart / 二进制 / SSE 语料库 / 跨块 event-ID 无比较能力；本切片 diff 未提交。

**下一切片（P3A，3 条 public featured GET）需继承：**
- 录制序列与 `trust_env=False` 是硬前置，照 `Concrete Steps` 复现即可。
- 新 case 若冒出非确定字段，**逐条按 case 声明**，不得扩大为全局规则；先查是不是 `taskId` 这类回放期现铸值。
- `secured` cookie 属性依赖 `prod` profile —— 若 P3 用别的 profile 起 Java，golden 必须重录，不能沿用。
- 离线比较器已可用；P3A 的验收形态就是 `--golden java-initial.json --response <python-capture>` ⇒ 零未解释差异。

## Context and Orientation

**Java 参考实现：** `Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/`。7 条 case 分属 3 个 controller：
- `agent/AgentVisitorController.java` → `GET /api/agent/visitor/bootstrap`
- `agent/AgentFeaturedConversationController.java` → featured home / list / detail
- `agent/AgentConversationHistoryController.java` → conversation sessions list / detail
- `agent/AgentSessionCapabilityController.java` → `GET /api/agent/session/{sessionId}/capabilities`

**信封：** `Reactor-agent-api/src/main/java/org/wwz/ai/api/response/Response.java` + `ResponseCode.java` → 成功恰为 `{"code":"0000","info":"成功","data":<payload>}`，`code` 是 **String**（`"0000"`/`"0001"`/`"0002"`/`"0003"`）。`ui/src/utils/request.ts` 仅在 `code === '0000'` 时解包 `data`。

**前端消费者（load-bearing 字段来源）：** `ui/src/services/{agentConversation,featuredConversation,sessionCapability}.ts`；消费点 `ui/src/pages/Home/index.tsx`、`ui/src/components/FeaturedConversationCard.tsx`、`ui/src/utils/conversationHistory.ts`、`ui/src/components/GeneralInput/CapabilityPicker.tsx`。

**Python 目标：** `backend-python/src/reactor_backend/contracts/{cli,http,manifest,models,normalize,sse,sse_cli}.py`。CLI 入口 `backend-python/pyproject.toml`：`reactor-contract = reactor_backend.contracts.cli:main`、`reactor-sse-contract = reactor_backend.contracts.sse_cli:main`。

**数据表：** `Reactor-agent-app/src/main/resources/db/schema.sql`（33 张）。7 条 case 触及 `ai_agent_visitor_identity`、`ai_agent_featured_conversation`、`ai_agent_dialogue_session`、`ai_agent_dialogue_run`、`ai_agent_llm_invocation`、`ai_agent_tool_invocation`、`ai_agent_artifact`、`ai_agent_tool_output_*`、`ai_agent_session_capability`、`ai_client_tool_mcp`。

**部署路由：** `docker/nginx.conf` 的 `location /api/` → Java 8100，`proxy_pass` 无 URI 重写 ⇒ **公共路径 == controller 路径**。本切片不切 Nginx。

**相关迁移文档：** `docs/python-migration/{PLANS,inventory,api-contracts,database-ownership,risk-register,progress,codex-migration-guide,staged-prompts}.md`、根 `AGENTS.md`。

**7 条 case 事实矩阵（实测）：**

| # | name | path | 访客过滤器 | 写表 | allowlist |
|---|---|---|---|---|---|
| 1 | `visitor-bootstrap` | `/api/agent/visitor/bootstrap` | 是 | `ai_agent_visitor_identity` | `/body/data/visitorId`、`/cookies/*/attributes/expires`、cookie 值 `ai_agent_visitor_token` |
| 2 | `featured-home-default` | `/api/agent/featured-conversations/home` | 否 | 无 | 无 |
| 3 | `featured-list-first-page` | `/api/agent/featured-conversations?pageNo=1&pageSize=20` | 否 | 无 | 无 |
| 4 | `featured-detail-fixture` | `/api/agent/featured-conversations/${CONTRACT_FEATURED_ID}` | 否 | 无 | `/body/data/historyDetail/runs/*/replayFrames/*/resultMap/eventData/taskId` |
| 5 | `conversation-session-list` | `/api/agent/conversation/sessions?limit=20` + Cookie | 是 | 过滤器 | 无 |
| 6 | `conversation-session-detail` | `/api/agent/conversation/sessions/${CONTRACT_SESSION_ID}` + Cookie | 是 | 过滤器 | `/body/data/runs/*/replayFrames/*/resultMap/eventData/taskId` |
| 7 | `session-capabilities` | `/api/agent/session/${CONTRACT_SESSION_ID}/capabilities` | 否 | 无 | 无 |

**固定标识：** `CONTRACT_VISITOR_TOKEN=fixture-raw-token`（`token_digest = SHA256("fixture-raw-token")` hex，SQL 内写死字面量，复算命令在 seed 文件头注释）；`visitor_id=fixture-visitor-0001`；`CONTRACT_SESSION_ID=fixture-session`；`CONTRACT_FEATURED_ID=fixture-featured`。时区固定 `Asia/Shanghai`（seed 首行 `SET time_zone = '+08:00'`）。

## Contract and Invariants

**必须保持（本切片不改任何公共业务行为，只建立测量能力）：**
- 公共 HTTP 路径、方法、状态码、媒体类型、`{"code","info","data"}` 信封、字段类型、`null`、空集合、排序、Cookie 属性、二进制响应一律不变。
- 成功信封恰为 `{"code":"0000","info":"成功","data":<payload>}`，`code` 为 **String**。
- Cookie `ai_agent_visitor_token` 属性在 `prod` profile 下为 `Path=/; Max-Age=31536000; HttpOnly; Secure; SameSite=Lax`，仅在 `isNewlyCreated()` 时发出。cookie **值**永不写入 golden（`sha256[:16]` 指纹或 `"<contract-ignored>"`），**名与属性**参与比较。
- `VisitorIdentityFilter` 的 9 个保护前缀不变；filter-protected GET **不是纯读**（会写 `ai_agent_visitor_identity`）。
- 时区固定 `Asia/Shanghai`；visitor/session/featured ID、数据库 seed、排序全部固定。

**nondeterministic 字段政策（仅按 case 精确 JSON Pointer，禁止全局忽略）：**
- 指针根 = 采集文档（HTTP：`HttpSnapshot.as_dict()`；SSE：事件 `data` 值）。
- 一个列表两处语义：采集期 `normalize_json` 哨兵替换（取值放行）+ 比较期 `drop_additive` 删候选侧增量键（增量放行）。
- 候选侧**多出**字段 ⇒ `field mismatch`；写进该 case allowlist 后 ⇒ 通过。
- 候选侧**缺失**字段（golden 有、候选无）⇒ **始终**报差异，allowlist **不得**放行（删除是 breaking）。
- 双侧都有但取值非确定 ⇒ 哨兵替换。
- `*` 通配沿用（dict 扇出所有键 / list 扇出所有元素）；**列表长度是契约数据，永不删元素**。
- 结构错误永远抛 `ValueError`：非 `/` 开头指针、非 int 列表下标、下标越界、降到标量/元组、`*` 打到标量。中间 dict 键缺失抛；**终末** dict 键缺失是 no-op（服务增量声明）。

**禁止改变的业务不变量：** 不实现业务路由；不切 Nginx；不改 schema；无 Java/Python 应用层双写；不调用付费/live provider；golden 不得含原始 Cookie、API key、完整用户 prompt 或 provider 响应；不隐藏失败；不扩大全局 ignore。

## Plan of Work

按依赖顺序（已全部实施）：

1. **M2 快照往返** — `models.py` 给 `CookieSnapshot`/`HttpSnapshot`/`SseEvent`/`SseCapture` 补 `from_dict()`；`HttpSnapshot.as_dict()`/`SseCapture.as_dict()` 改显式列表输出（避开 `dataclasses.asdict` 的 tuple 陷阱）；`http.py` 接通 `load_snapshot`/`save_snapshot`/`load_capture_file`/`save_capture_file`，`dump_snapshot` 参与 golden 写出，不再是死代码。
2. **M3 additive 机制** — `normalize.py` 新增 `drop_additive(golden, candidate, pointers)`（仅改写候选侧，复用 `_parse_pointer` 与 `*` 扇出）；`http.py::compare_http` / `sse.py::compare_sse` 增 `ignored_json_pointers` 形参；`cli.py` 传 `case.normalization.ignored_json_pointers`。
3. **M3 加固** — `normalize.py::_replace`/`::_drop` 结构错误抛错；终末 dict 键缺失 no-op、中间键缺失抛（分裂规则，见 Decision Log）。
4. **M4 确定性 fixture** — `tests/contract/fixtures/contract-seed.sql`（DELETE-then-INSERT 幂等；显式 `id` + 全部 ORDER-BY 列；`ai_client_tool_mcp` 显式清空；回放链子表留空使空集合形态入契约）+ `fixtures/skills/` 两个最小技能。
5. **M5 一条录制命令** — 见 Concrete Steps；产出 `tests/contract/golden/java-initial.json`；可重复性自检 = 重灌重录逐字节比对。
6. **M6 离线比较 CLI** — `--record-java` / `--record-python` 对称写同一 capture 形态 `{"mode","base_url","cases":[{"name","snapshot"}|{"name","error"}],"skipped":[]}`；`--golden`+`--response` 完全离线；`--golden` 单独 = live Python vs 已存 golden；两者都没有 = live 双跑。报告形态不变 `{"mode":"comparison","cases":[{"name","matched","java","python","differences":[{"path","java","python","reason"}]}],"skipped":[]}`；golden 内 `base_url` 仅供审计，比较报告不重复。
7. **M7 SSE fake fixture + 范围声明** — `fake-agent-request.json`；SSE 已覆盖/deferred 表写入 `tests/contract/README.md` 与 `api-contracts.md`。
8. **M8 九维单测** — 见 Validation and Acceptance 的维度表。
9. **M9 能力级 deferred registry** — `api-contracts.md` 新增独立小节（multipart / 二进制导出 / 流式 ZIP Zip Slip / SSE 语料库 / 跨块 last-event-ID），与既有**路由级** registry 分开。
10. **文档同步** — `api-contracts.md`（`:85` 拆两句、`:98` 改为「未 pin 的 eventType 报差异」、`:106` 保持）；`progress.md`（勾前三项、**第 4 项不勾**）；`risk-register.md`（blocker 4 处置、fixtures/goldens 条目更新、新增 5 条风险）；`tests/contract/README.md`（真实命令序列 + SSE 范围表 + 指针根约定）。

## Concrete Steps

工作目录：`/Users/cuimingkai/Documents/agent-2/ai-agent`（Python 门禁在 `backend-python/`）。

```bash
# --- 准备独立测试 MySQL（不触碰 /usr/local/var/mysql）---
RECDIR=build/contract-recording
mkdir -p "$RECDIR"
mysqld --no-defaults --initialize-insecure --datadir="$PWD/$RECDIR/mysql-data"
mysqld --no-defaults --datadir="$PWD/$RECDIR/mysql-data" --port=3307 \
       --socket="$PWD/$RECDIR/mysql.sock" --pid-file="$PWD/$RECDIR/mysqld.pid" \
       --log-error="$PWD/$RECDIR/mysqld.log" &
# --no-defaults 必须有：Homebrew my.cnf 与编译内置默认都指向被禁止的 /usr/local/var/mysql

mysql --no-defaults --socket="$RECDIR/mysql.sock" -u root \
  -e "CREATE DATABASE ai_agent_station_contract CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
      CREATE USER 'contract'@'127.0.0.1' IDENTIFIED BY 'test-only';
      GRANT ALL ON ai_agent_station_contract.* TO 'contract'@'127.0.0.1';"
mysql --no-defaults --socket="$RECDIR/mysql.sock" -u root ai_agent_station_contract \
  < Reactor-agent-app/src/main/resources/db/schema.sql
mysql --no-defaults --socket="$RECDIR/mysql.sock" -u root ai_agent_station_contract \
  < backend-python/tests/contract/fixtures/contract-seed.sql

# --- 起 Java（prod profile + test-only 覆盖；整条 [0] 参数必须加引号，zsh 会 glob）---
mvn -pl Reactor-agent-app -am package '-Dmaven.test.skip=true'
java -jar Reactor-agent-app/target/Reactor-agent-app.jar --spring.profiles.active=prod \
  --spring.datasource.mysql.driver-class-name=com.mysql.cj.jdbc.Driver \
  "--spring.datasource.mysql.url=jdbc:mysql://127.0.0.1:3307/ai_agent_station_contract?useUnicode=true&characterEncoding=utf8&autoReconnect=true&zeroDateTimeBehavior=convertToNull&serverTimezone=Asia/Shanghai" \
  --spring.datasource.mysql.username=contract \
  --spring.datasource.mysql.password=test-only \
  "--autobots.autoagent.skill.directories[0]=$PWD/backend-python/tests/contract/fixtures/skills" \
  > "$RECDIR/java.log" 2>&1 &
echo $! > "$RECDIR/java.pid"
curl -fsS --retry 30 --retry-delay 2 --retry-all-errors http://127.0.0.1:8100/web/health

# --- 录制（一条命令）---
cd backend-python
JAVA_BASE_URL=http://127.0.0.1:8100 \
CONTRACT_VISITOR_TOKEN=fixture-raw-token \
CONTRACT_SESSION_ID=fixture-session \
CONTRACT_FEATURED_ID=fixture-featured \
uv run reactor-contract tests/contract/cases/initial.json \
  --record-java --output tests/contract/golden/java-initial.json

# --- 可重复性自检：重灌 fixture 重录，逐字节比对 ---
mysql --no-defaults --socket=../$RECDIR/mysql.sock -u root ai_agent_station_contract \
  < tests/contract/fixtures/contract-seed.sql
JAVA_BASE_URL=http://127.0.0.1:8100 \
CONTRACT_VISITOR_TOKEN=fixture-raw-token CONTRACT_SESSION_ID=fixture-session \
CONTRACT_FEATURED_ID=fixture-featured \
uv run reactor-contract tests/contract/cases/initial.json \
  --record-java --output /tmp/golden-repeat.json
cmp tests/contract/golden/java-initial.json /tmp/golden-repeat.json && echo REPEATABLE

# --- 离线比较自证（完全离线，无需任何服务）---
uv run reactor-contract tests/contract/cases/initial.json \
  --golden tests/contract/golden/java-initial.json \
  --response /tmp/golden-repeat.json \
  --output /tmp/contract-self-check.json    # 预期 7/7 matched，exit 0

# --- 对抗性变异（改值/改类型/删字段/加字段/改 cookie 属性/allowlist 路径）---
# 逐个变异后重跑上面的离线命令，预期 exit 1 且差异落在预期 (path, reason)

# --- P3 起用（本阶段登记不实跑）---
uv run reactor-contract tests/contract/cases/initial.json \
  --record-python --output build/python-responses.json
PYTHON_BASE_URL=http://127.0.0.1:8200 \
uv run reactor-contract tests/contract/cases/initial.json \
  --golden tests/contract/golden/java-initial.json --output build/contract-report.json

# --- SSE（本地 fake 请求，不调真实 Agent/LLM）---
uv run reactor-sse-contract /local/fake-agent-stream --method POST \
  --body tests/contract/fixtures/fake-agent-request.json \
  --ignore-pointer /requestId --output build/sse-contract-report.json

# --- 门禁 ---
cd backend-python
uv sync --all-groups
uv run ruff check .
uv run mypy src
uv run pytest -m "not integration"

# --- 清理 ---
kill "$(cat ../build/contract-recording/java.pid)"
mysqladmin --no-defaults --socket=../build/contract-recording/mysql.sock -uroot shutdown
rm -rf ../build/contract-recording
```

## Validation and Acceptance

| # | 通过条件 | 实测结果 |
|---|---|---|
| 1 | 一条明确命令录制首批净化 golden，7/7 case、`skipped: []`，无原始 Cookie / API key / 完整 prompt / provider 响应 | ✅ `java-initial.json` 15613 bytes，`skipped: []`，secret 扫描 **0 hit**，7 个 `<contract-ignored>` 哨兵 |
| 1b | 录制可重复 | ✅ fixture 重灌重录，`cmp` 逐字节一致 |
| 2 | 离线比较 + 机器可读 diff，**无任何服务** | ✅ `--golden`+`--response` 产出 `{"mode":"comparison","cases":[...],"skipped":[]}`，7/7 matched，exit 0 |
| 2b | 对抗性变异能被抓到 | ✅ 六类变异 ⇒ exit 1，差异落在恰好预期的 `(path, reason)`；allowlist 路径正确放行 |
| 3 | `fake-agent-request.json` 补齐、`golden/` 有内容、SSE 范围清楚 | ✅ 三者齐备；SSE 已覆盖/deferred 两栏写入 README 与 `api-contracts.md` |
| 4 | 单测覆盖 status / 类型 / null / 排序 / Cookie / UTF-8 / EOF / timeout / error | ✅ 44 passed / 1 deselected（见下表） |
| 5 | additive 政策文档与比较器一致 | ✅ `api-contracts.md` 三处矛盾消解；有单测证明「未声明即差异 / 声明后放行 / 删除永不放行」 |
| 6 | 能力级 deferred 已登记 | ✅ 5 项独立小节，与路由级 registry 分开 |
| 7 | 门禁全绿 + `progress.md` 真实命令/结果/剩余阻塞 + `git diff` 自审 | ✅ ruff / mypy(29 files) / pytest 全绿；progress 前三项勾、**第 4 项不勾** |

**九维单测映射：**

| 维度 | 具名测试 |
|---|---|
| status | `test_http_comparator_reports_status_code_drift`、`test_sse_compare_reports_status_drift` |
| 类型 | `test_http_comparator_reports_bool_integer_type_drift` |
| null | `test_http_comparator_reports_null_versus_missing_and_value` |
| 排序 | `test_http_comparator_reports_list_order_drift`、`test_http_comparator_ignores_object_key_order` |
| Cookie | `test_http_cookie_fingerprint_is_stable_and_mismatch_is_detected`、`test_http_comparator_reports_cookie_name_drift`、`test_http_comparator_reports_cookie_attribute_drift`、`test_allowlist_pointer_can_address_a_cookie_attribute` |
| UTF-8 | `test_http_capture_round_trips_utf8_body` |
| EOF | `test_capture_sse_records_content_type_utf8_and_normal_eof` |
| timeout | `test_capture_sse_times_out_and_records_termination`（真 socket，`asyncio.start_server` 不吐 EOF） |
| error | `test_capture_sse_records_transport_error`、`test_capture_sse_records_http_error`、`test_capture_sse_records_size_limit` |
| additive | `test_undeclared_additive_field_is_a_difference`、`test_declared_additive_field_passes_but_removal_never_does`、`test_compare_sse_additive_field_policy_matches_http` |
| golden 往返 / 离线 CLI | `test_contract_golden.py` 4 例 |
| normalize 加固 | `test_contract_normalize.py` 8 例 |

**明确不作为本切片验收：** `progress.md` Phase 2 第 4 项「Execute initial Java/Python comparisons after the corresponding phase 3 routes are implemented」——gated 在 P3。本切片的离线比较**自证**（golden vs 自身副本 + 对抗性变异）是**比较器自证，不是 Python parity**，已在 `progress.md` 明写。

## Cutover and Rollback

- **无流量切换、无写所有权切换、无 schema 变更。** fixture 只写独立测试库 `ai_agent_station_contract`，不碰任何共享/生产库。`/usr/local/var/mysql` 全程未触碰。
- 回滚：还原本切片 diff（`backend-python/src/reactor_backend/contracts/`、`backend-python/tests/{contract,unit}/`、`docs/python-migration/`）并删除新建的 `docs/python-migration/execplans/contract-lab.md` 与 `backend-python/tests/contract/{fixtures,golden}/`；再杀 Java、`mysqladmin ... shutdown`、`rm -rf build/contract-recording`。不影响运行中服务、数据库或工作树其他改动。
- 回滚所有者：本切片执行者。无活跃 run。

## Idempotence and Recovery

- **fixture** 可重复执行（按固定键 `DELETE` 后 `INSERT`），任意时刻重灌得到同一状态。
- **录制**可重复：重跑 `--record-java` 覆盖写出同一份 golden（已实测逐字节一致）。
- **中断恢复：** `mysqld` 用独立 datadir，删目录即净；Java 独立进程，杀掉即净；无共享状态。录制到一半失败 ⇒ capture 含 `{"name":<case>,"error":...}` 条目且 exit 1，**不会写出半份「看起来成功」的 golden**。
- **坏 allowlist：** 加固后 `normalize` 抛 `ValueError` 而不是静默通过，避免「写错路径 → 假绿」。终末键缺失是 no-op，服务增量声明，已在 docstring 说明。
- **系统代理回归：** 若录制突然出现裸 disconnect，先查 `urllib.request.getproxies()`；契约工具已固定 `trust_env=False`，新写的 HTTP 客户端必须沿用。

## Interfaces and Dependencies

- **公共接口：** 无新增生产 HTTP 路由。仅 CLI 扩展：`reactor-contract` 新增 `--record-python` / `--golden` / `--response`（既有 argv 兼容）；`reactor-sse-contract` 参数面不变，仅新增 fixture 输入文件。
- **port/adapter：** 无新增生产依赖。`contracts/` 增加 `from_dict` / `load_*` / `save_*` / `drop_additive` / `compare_http(ignored_json_pointers=)` / `compare_sse(..., ignored_json_pointers=)`。
- **数据访问边界：** fixture 只经 `mysql` 客户端灌独立测试库；Python 生产代码仍零 DML。
- **第三方依赖：** 无新增（`httpx` 已有）。测试用 `pytest` + `httpx.MockTransport` + 本地 asyncio 假服务器，**不联网、不调付费 provider**。
- **工具配置（非业务）：** 全部 `httpx.AsyncClient` 固定 `trust_env=False`，理由见 Decision Log。

## Artifacts and Evidence

**入库产物：**
- `backend-python/tests/contract/golden/java-initial.json` — 首批 7 条净化 golden，15613 bytes，`mode: java-baseline`，`skipped: []`，secret 扫描 0 hit，7 个 `<contract-ignored>` 哨兵。
- `backend-python/tests/contract/fixtures/contract-seed.sql` — 确定性 seed（幂等、显式排序列、`Asia/Shanghai`）。
- `backend-python/tests/contract/fixtures/fake-agent-request.json` — SSE 用最小合法请求骨架（占位符字段，无密钥、无真实 prompt）。
- `backend-python/tests/contract/fixtures/skills/contract-fixture-{alpha,beta}/SKILL.md` — 钉死的 `skills[]`。
- `backend-python/tests/unit/test_contract_{http,normalize,sse,golden}.py` — 44 passed / 1 deselected。

**实测命令与结果：**
```
uv run ruff check .            → All checks passed!
uv run mypy src                → Success: no issues found in 29 source files
uv run pytest -m "not integration" → 44 passed, 1 deselected, 2 warnings
```

**离线自证 A（golden vs 自身副本）：**
```
visitor-bootstrap: matched=True diffs=0
featured-home-default: matched=True diffs=0
featured-list-first-page: matched=True diffs=0
featured-detail-fixture: matched=True diffs=0
conversation-session-list: matched=True diffs=0
conversation-session-detail: matched=True diffs=0
session-capabilities: matched=True diffs=0
secret scan: 0 hits / sentinels: 7
exit=0
```

**可重复性自检：** `REPEATABLE: goldens are byte-identical across a fixture re-seed`

**离线自证 B（六类对抗性变异）：**
```
mutations: value, type, removal, additive, cookie-attr, allowlisted-sentinel
exit=1  (expect 1)
  DIFF  visitor-bootstrap
        /cookies/0/attributes/httponly                           value mismatch
  DIFF  featured-home-default
        /body/data/0/title                                       value mismatch
  DIFF  featured-list-first-page
        /body/data/total                                         type mismatch
  DIFF  featured-detail-fixture
        /body/data/<keys>                                        field mismatch
  DIFF  conversation-session-list
        /body/data/0/<keys>                                      field mismatch
  PASS  conversation-session-detail
  PASS  session-capabilities
```
五类变异各落在**恰好预期**的 `(path, reason)`；第 6 类（落在 allowlist 声明路径上的哨兵改写）正确放行 —— 证明 allowlist 不是全局压制。

**不入库：** `build/contract-recording/`（临时 datadir、`mysqld.log`、`java.log`、pid）、`/tmp/golden-repeat.json`、`/tmp/contract-self-check.json`、任何 Java 日志（可能含配置值）、`reactor-tool/.env`。
