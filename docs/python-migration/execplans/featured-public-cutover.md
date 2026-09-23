# Public featured 三条精确路径切到 Python + 回滚演练（Phase 3B）

本 ExecPlan 遵循 `docs/python-migration/PLANS.md`，执行期间必须保持自包含并持续更新。

## Purpose / Big Picture

Phase 3A 已交付 `backend-python/` 中的 3 条 public featured GET，并证明它们与 Java golden 零未解释差异。但 Nginx 仍把 `/api/` **整体**打到 Java，Python 没有 upstream——用户看不到任何变化。

本切片只做一件事：把**已经通过契约验收**的这 3 条精确路径切到 Python，其余 `/api/` 路由继续命中 Java，并**实际演练**回滚（切回 Java → 验证恢复 → 再切回 Python）。这是迁移中第一次真实流量切换，必须以最窄路由、可计时回滚、同组检查前后对照的方式完成。

成功可直接观察：Nginx access log 中 `$upstream_addr` 显示三条路径进 `reactor_backend_python`、对照路径进 `reactor_backend`；UI 形态请求（首页/列表/详情）200 且契约零差异；回滚一次实测用时被记录，且回滚后对照组恢复。

## Scope

**路由（全 GET，均为 `AgentFeaturedConversationController`）：**

- `GET /api/agent/featured-conversations/home`
- `GET /api/agent/featured-conversations`
- `GET /api/agent/featured-conversations/{featuredId}`（仅单段 id）

**包含：**

- `docker/nginx-featured-python.d/featured-conversations.conf` —— 3 个 location 块（`=` ×2 + 单段正则 ×1），是切流/回滚的唯一开关。
- `docker/nginx.conf` —— 新增 `upstream reactor_backend_python` + `include /etc/nginx/featured-python.d/*.conf`。
- `Dockerfile` —— 把 fragment 拷进 frontend 镜像。
- `docker-compose.yml` —— bind-mount `docker/nginx-featured-python.d/`（回滚/再切流不需 rebuild，且状态可被 git 观测、容器重启后不回弹）+ frontend `depends_on` Python。
- **400/405 错误体对齐**：`api-contracts.md` 的 "Derived values that were never probed" 把 Spring `BasicErrorController` 400 体明确划给 3B 关闭。切流后 `?limit=abc` 会落到 Python，若不等于 Java 形状即真实回归。本切片起 Java 实测并让 Python 对齐。
- 回滚演练 harness：`backend-python/tests/cutover/`（本地 nginx drill 配置 + 脚本 + README）。
- 同组检查：smoke（UI 形态请求 + 对照路径 + 近失路径 + 5xx 计数）、contract（`phase3-featured.json` vs `java-featured.json`，走 nginx）、frontend（4 个 vitest 文件）。
- 文档同步：`progress.md`、`inventory.md`、`api-contracts.md`、`risk-register.md`、`database-ownership.md`（如需）。

**不包含：** 其它任何 `/api/`、`/web/`、`/data/` 路由；随机 request-level 百分比；active run / SSE 原子路由族；admin 写；`VisitorIdentityFilter` 相关路由；schema 变更；Java 代码改动；React UI / `reactor-tool` / `reactor-sandbox` / `runtime/skills` 行为变更；真实 provider；生产凭证；把 404（近失路径）也切到 Python。

**工作区用户资产（禁触碰）：** `?? .workbuddy/` 不读取、不修改、不删除。`reactor-tool/.env` **绝不读取或打印**。`/usr/local/var/mysql` **绝不触碰**。MySQL client credential stores（`~/.my.cnf`、`~/.mylogin.cnf`、`~/.config/mysql`）**绝不读取**（R-34）。

## Progress

- [x] (2026-09-23) 归档 `git status --short`（仅 `?? .workbuddy/`）；研究 Java 参考实现、前端消费者、Nginx 路由、契约工具与部署；建立本 ExecPlan。
- [x] (2026-09-23) M1 路由 fragment + `nginx.conf` include + `Dockerfile` COPY + compose bind-mount/`depends_on`；`nginx -t` 语法检查 exit=0。
- [x] (2026-09-23) M2 Java 实测 400/404/405/500 错误体 → Python 对齐（`spring_error_response`）+ 单测 + `phase3-featured-errors.json` 契约 case + `java-featured-errors.json` golden。
- [x] (2026-09-23) M3 bring-up：throwaway MySQL（R-33 清库重播 contract-seed）+ `reactor_py_ro` + Java :8100 + Python :8200 + 本地 nginx drill :18080。
- [x] (2026-09-23) M4 切流前同组检查：14 探针 0 5xx 0 路由违规、契约 3/3 + 4/4、前端 4 文件 6 用例。
- [x] (2026-09-23) M5 切流到 Python（**0.084s**）→ 同组检查全绿 + `$upstream_addr` 归属证明（三条 → python，近失/对照 → java）。
- [x] (2026-09-23) M6 **回滚到 Java**（生效 **0.074s**，端到端恢复验证 **0.488s**）→ 同组检查 on-java 全绿、归属反转。
- [x] (2026-09-23) M7 **再切回 Python**（0.082s）→ 终态检查全绿（终态停在 Python）。
- [x] (2026-09-23) M8 门禁（ruff / mypy 48 files / pytest 186 passed / `docker compose config --quiet`）+ 文档同步 + `git diff` 自审 + 最终报告。

## Surprises & Discoveries

- Observation: bring-up 后 Java 的 `/home` 与列表路由稳定 500，而 Python 200。
  Evidence: `build/cutover-drill/java.log` → `com.alibaba.fastjson.JSONException: field null expect '[', but {, pos 1, line 1, column 2{"not": "an array"}`；`backend-python/tests/integration/fixtures/featured_read_edge_seed.sql:82` 向 JSON 数组列插入了 `'{"not":"an array"}'`；3A 的 edge seed 仍留在 `ai_agent_station_contract` 里（连同 6 条 `edge-featured-*` 行）。这是 R-33 明令禁止的 fixture 混用。
  Impact: 不是切流缺陷，而是对照库被污染，会把 Java 假性 5xx 记成"5xx 增加"。处置：`DROP DATABASE` 后只重放 `schema.sql` + `contract-seed.sql`（**不**含 edge seed），`reactor_py_ro` 的 `GRANT SELECT` 跨库重建仍存活。
  Residual: 一个真实的 Java/Python 行为差异被顺带记录——**Java 遇到畸形 JSON 列会抛 JSONException 变 500，Python 容忍并降级为空 tags**。本切片两边都只读同一份干净种子，未触发；留给后续切片决策。

- Observation: Spring `BasicErrorController` 400/404/405/500 形状此前在 `api-contracts.md` 里登记为 "Derived values that were never probed"（owner=3B）。
  Evidence: 实测 2026-09-23（`--spring.profiles.active=prod`，无 `server.error.*` 覆盖）——恒为 4 键 `{"timestamp","status","error","path"}`，键序固定；`timestamp` 为 UTC 毫秒 + `+00:00`（非 `Z`）；`error` 是 HTTP reason phrase；`path` 是不含 query 的请求 URI；无 `message`/`requestId`。405 另带 `Allow: GET`（与 Python 已有的 `allow: GET` 一致）。证据已固化进 `tests/contract/golden/java-featured-errors.json`。
  Impact: 该项由 *unprobed* 转为 *measured*，见 `api-contracts.md`。

- Observation: 切流后三条路径的响应头与 Java 不一致（3 类差异）。
  Evidence: Java 无 `Server`、无 `X-Request-ID`，但带 `Vary: Origin` / `Vary: Access-Control-Request-Method` / `Vary: Access-Control-Request-Headers`（全局 `CorsFilter`，`/web/health` 上也有）；Python 有 `server: uvicorn`、`x-request-id`，无 `Vary`。
  Impact: 响应头属于公共 HTTP 行为，且 `Vary` 影响共享缓存的 key。已全部对齐（见 Decision Log），`probes.py` 现在把 `vary` 也纳入硬性比对。

- Observation: 仅靠 middleware 无法去掉 uvicorn 的 `Server` 头。
  Evidence: `uvicorn/config.py:498-499` 只在 `b"server" not in dict(encoded_headers)` 且 `self.server_header` 时才前置 `(b"server", b"uvicorn")`——即头在 app 返回**之后**才被拼上，middleware 既看不到也删不掉。
  Impact: 必须在启动处关闭：`backend-python/Dockerfile` 的 CMD 加 `--no-server-header`（带注释标明 load-bearing）。这是一处"忘了就静默漂移"的脆弱点，已写进 risk-register。

- Observation: 首轮 `on-python` 探针报 `ui-detail` body 不一致，两侧 `eventData.taskId` 是不同的随机 UUID。
  Evidence: `build/cutover-drill/checks/on-python/probes.json` 的 `differences_vs_reference`；Java 每次调用都新生成该 UUID。这正是 `phase3-featured.json` 中 `featured-detail-fixture` 已按 `/body/data/historyDetail/runs/*/replayFrames/*/resultMap/eventData/taskId` 放行的叶子。
  Impact: 探针原先的"整则 ISO 时间戳正则"归一化不够用，且过宽（会把确定性的 `publishedAt` 也抹掉，掩盖时间语义漂移）。已改为复用 `normalize_json` 的**逐探针精确 JSON Pointer**，无正则、无全局忽略。

- Observation: `normalize_json` 对打错的 pointer 会抛错，且同一份 pointer 列表无法同时命中两种 `data` 形态。
  Evidence: 单一 pointer `/data/historyDetail/...` 在 `/home` 上抛 `ValueError: list index token must be an integer: 'historyDetail'`（那里 `data` 是数组），在 `/{id}` 上才成立（`data` 是对象）。
  Impact: 归一化清单按探针声明（`BASE_POINTERS` + `EXTRA_POINTERS`），与 contract lab "按 case 声明" 同构。缺叶子是 no-op，打错会炸——这正是想要的失效方向。

- Observation: 门禁命令的 cwd 会改变结论。
  Evidence: 在仓库根跑 `uv run ruff/pytest` 会命中 `reactor-tool/` 的另一个 project（ruff 报 163 个无关错误、pytest 收集 56 个错误）；`docker compose config` 则**必须**给三个 test-only 口令，否则插值失败。
  Impact: 门禁一律在 `backend-python/` 下执行；compose 语法检查固定带 test-only 口令。

## Decision Log

- Decision: 路由 fragment 独立成 `docker/nginx-featured-python.d/*.conf`，由 `nginx.conf` 以 `include` 引入；回滚 = 移走该目录下的 `.conf` + `nginx -t` + `nginx -s reload`。
  Rationale: 切流/回滚是**一个文件的在位与否**，可计时、可审计、不需 rebuild；`include` glob 无匹配文件时是合法空包含，天然 fail-safe（缺文件 ⇒ 回 Java）。
  Date/Author: 2026-09-23 / Codex
- Decision: detail 路由用 `location ~ ^/api/agent/featured-conversations/[^/]+$`（单段），**不用**前缀 location。
  Rationale: 前缀 `location /api/agent/featured-conversations/` 会吞掉多段与尾斜杠；那些路径 Java 返回 `BasicErrorController` 404 体，Python 返回 Starlette `{"detail":"Not Found"}` —— 形状不同。窄正则让近失路径继续落 Java，404 体保持 Java 形状。多段/尾斜杠/嵌套仍走 `location /api/` → Java。
  Date/Author: 2026-09-23 / Codex
- Decision: compose 侧把 `docker/nginx-featured-python.d/` bind-mount 进 frontend 的 `/etc/nginx/featured-python.d/`。
  Rationale: 镜像内烤入的副本在容器重启后会**复活**（`restart: unless-stopped`）——"回滚后重启即偷偷切回 Python"是危险的回滚语义。bind-mount 让宿主机目录成为唯一开关，回滚可跨重启存活，且 `git status` 能看见开关状态。
  Date/Author: 2026-09-23 / Codex
- Decision: 本切片一并关闭 `api-contracts.md` 里 owner=3B 的 "Spring BasicErrorController 400 体" 探测项：起 Java 实测，Python 对齐，并补一个 contract case。
  Rationale: 切流后 `?limit=abc` 落到 Python；若体不同就是切流引入的真实公共 HTTP 回归，违反"保持公共行为兼容"与 Done-when 的"契约无差异"。Java 反正要起（回滚演练需要），探测成本≈0。
  Date/Author: 2026-09-23 / Codex
- Decision: 演练运行时 = 本地 throwaway `mysqld`（独立 datadir）+ 本地 Java + 本地 Python + **本地 nginx**（高位端口，自定义 prefix），不用 Docker。
  Rationale: 本机 Docker daemon 不可用；与 phase-2 contract-lab 同一既定路径（R-31 三条 quirk 已记录）。location 块字节与生产 fragment 相同（`cmp` 证明），upstream 主机名是环境差异（生产用容器名，drill 用 `127.0.0.1`），不影响 location 语义。
  Date/Author: 2026-09-23 / Codex
- Decision: throwaway MySQL 上用 `db/migrations/20260923_provision_phase3_readonly_account.sql` 自建 `reactor_py_ro`，口令为 test-only 会话变量（不进报告、不进仓库、不进命令行）。
  Rationale: R-34 禁止的是**共享/真实** `reactor_py_ro` 与生产 credential store，禁止"为了绕过秘密而 ALTER USER 改掉真实账号口令"。自初始化的 throwaway 实例 + 经审阅迁移脚本 + test-only 口令正是 AGENTS.md"只用 test-only 凭证"的测试路径；这不削弱任何真实账号。仍不读取任何 MySQL client credential store。
  Date/Author: 2026-09-23 / Codex
- Decision: 错误体对齐采用 Spring `BasicErrorController` 四键形状；`ApiError` 与 `RequestValidationError` **保留** `{code,info,data}` 信封，不改。
  Rationale: Java 没有 `@ControllerAdvice`，参数类型不匹配 / 方法不允许 / 未映射路径 / 未捕获异常一律走 `response.sendError` → `BasicErrorController`，所以"传输层错误"就长这样；而 `0000/0001/0002/0003` 信封是**业务** handler 的形状（含"未找到 = 200 + `data:null`"）。两类混用、或再造第三种（如 FastAPI 的 `{"detail": ...}`）都是切流会放大的漂移。`RequestValidationError` 的 422+`0002` 只可能由请求体校验触发，三条 GET 不经过，保持不动以免扩大改动面。
  Date/Author: 2026-09-23 / Codex
- Decision: 响应头三类差异全部**对齐**，不建 allowlist：(a) `Server` 用 `--no-server-header` 关掉；(b) `X-Request-ID` 改为**仅当客户端送来才回显**（不送则不出现），日志仍带 `request_id`；(c) 在 `RequestContextMiddleware` 里补 Java `CorsFilter` 的三条 `Vary`。
  Rationale: 约束是"保持公共 HTTP 行为兼容"、Done-when 是"契约无差异"。`Vary` 影响共享缓存 key，是实质差异；`Server: uvicorn` 是实现泄漏；`X-Request-ID` 无条件下发是纯增量差异。若改成"登记后放行"，探针的头比对就形同虚设，正好落在 AGENTS.md 禁止的"全局忽略契约差异"附近。回显制让正常流量（SPA/缓存/演练探针都不发该头）零差异，同时保住主动要关联号的客户端能力。
  Date/Author: 2026-09-23 / Codex
- Decision: 400/405 错误体契约 case 放进**独立清单** `tests/contract/cases/phase3-featured-errors.json` + `tests/contract/golden/java-featured-errors.json`，不并进 `phase3-featured.json`。
  Rationale: `phase3-featured.json` 是 3A 的验收集（3/3 已归档）；并进去会把既有验收结论波及。两份清单在 `drill.sh check` 里同时跑、同样以 `skipped == []` 和 case 数为门禁（R-32），证据强度不打折。
  Date/Author: 2026-09-23 / Codex
- Decision: 探针 body 归一化改为"按探针声明的精确 JSON Pointer"，复用 `reactor_backend.contracts.normalize.normalize_json`，废弃 ISO 时间戳正则。
  Rationale: 正则既漏（Java 每次生成的随机 `eventData.taskId`）又过宽（把确定性 `publishedAt` 一起抹掉，等于对"静默改变时间语义"开洞）。精确 pointer 与 contract lab 同一条规则、同一份实现，两个门禁不可能悄悄分叉。
  Date/Author: 2026-09-23 / Codex

## Outcomes & Retrospective

**结果：Done-when 全部达成，2026-09-23 实测。**

| 验收项 | 实测 |
|---|---|
| 三条路径命中 Python | `final` 阶段 `$upstream_addr`：3 条 featured GET → `python`（200） |
| 其余路径仍命中 Java | 5 条近失路径 → `java`（404）；2 条对照（`/web/health`、session capabilities）→ `java`（200）。零反例 |
| UI 首页/列表/详情正常 | 三条均 200 + `{"code":"0000","info":"成功",…}` |
| 契约无差异 | 四阶段均 `differences == []`：`phase3-featured.json` 3/3、`phase3-featured-errors.json` 4/4，`skipped == []`（R-32 双门禁） |
| 5xx 未增加 | 四阶段探针 5xx 计数恒为 0 |
| 实际切回 Java 并验证恢复 | `check on-java` 全绿，归属反转 |
| 再切回 Python | `check final` 全绿，终态停在 Python |
| 路由配置语法检查 | `nginx -t` 在 switch OFF / ON 各一次，均 `exit=0` |
| 实际回滚用时 | 配置生效 **0.074s**；含恢复验证的端到端 **0.488s**（`build/cutover-drill/timing.log`）。切流本身 0.084s / 再切 0.082s |
| 配置/证据/回滚步骤入版本库 | fragment + `nginx.conf` + `Dockerfile` + `compose` + 本 ExecPlan + `tests/cutover/README.md` 的 Cutover and Rollback 章节 |

**契约差异：** 无未解释差异。唯一一次探针告警（`ui-detail` 的 `eventData.taskId`）已定位为 Java 每次生成随机 UUID（R-28 同源），是 `phase3-featured.json` 已按精确 JSON Pointer 放行的叶子，不是切流缺陷。

**Retrospective：**

- 做对了：把 `$upstream_addr` 当作唯一归属证人——三条 URI 两边契约本就相同，任何 body 断言都证明不了谁在答。近失路径刻意留在 Java（单段正则而非前缀 location）让 404 体不被吞，这一条在探针里一次就验住了。
- 做对了：回滚开关做成"一个文件的在位与否"并 bind-mount 出镜像，使回滚可计时、可跨容器重启存活、可被 `git status` 观测。
- 走了弯路：探针 body 归一化先用 ISO 时间戳正则，既漏掉随机 `taskId` 又把确定性 `publishedAt` 一起抹掉。精确 JSON Pointer 才是正解，且应从一开始就复用 `normalize_json` 而不是自造正则。
- 走了弯路：试图在 middleware 里去掉 `Server` 头——uvicorn 在 app 返回之后才拼这个头，做不到。应在启动处关（现为 R-35）。
- 教训：对照库被 3A 的 edge seed 污染（R-33）会让 Java 假性 5xx，看起来像"切流导致 5xx 增加"。**跑任何前后对照前先证明种子纯净**，比事后排查便宜得多。
- 教训：门禁命令的 cwd 会改变结论（仓库根会命中 `reactor-tool/` 的另一个 project）。这类"跑错了但看起来像失败"的成本，值得在 README 里写死工作目录。

**仍未完成：**

- `api-contracts.md` 的 collation 探测项（`status='ONLINE'` 在 `utf8mb4_unicode_ci` 下的大小写折叠）仍未探测，已改派 phase 4。
- Java 对畸形 JSON 列会 500、Python 容忍降级——真实行为差异，本切片未触发也未决策，留给后续切片。
- R-35 的退出条件（app 自身固定 `server_header` 形状，而非依赖启动参数）未做。
- R-36 的残余（fragment 仍被 COPY 进镜像，只是被 bind-mount 盖住）未做。
- 生产 compose 环境未实跑（本机 Docker daemon 不可用）；`docker compose config --quiet` 通过，但生产切流/回滚命令只在本地 nginx drill 上实测过。location 块与生产 fragment 字节一致（`cmp` 断言），差异仅在 upstream 主机名。

## Context and Orientation

- Java 参考实现：`Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/agent/AgentFeaturedConversationController.java`
  （`@RequestMapping("/api/agent/featured-conversations")` + `@GetMapping("/home")` / `@GetMapping` / `@GetMapping("/{featuredId}")`）。
- Java 用例：`Reactor-agent-case/src/main/java/org/wwz/ai/application/agent/featured/FeaturedConversationPublicQueryApplicationService.java`。
- 前端消费者：`ui/src/services/featuredConversation.ts`
  （`GET /api/agent/featured-conversations/home?limit=6`、`GET /api/agent/featured-conversations?pageNo&pageSize`、`GET /api/agent/featured-conversations/{id}`）；
  页面 `ui/src/pages/{Home,FeaturedConversations,FeaturedConversationDetail}`。
- Python 实现：`backend-python/src/reactor_backend/api/routers/featured_conversations.py` + `application/featured_conversation_query.py` + `infrastructure/repositories/`。
- 部署路由：`docker/nginx.conf`（现状 `location /api/` → `reactor_backend:8100`）；frontend 镜像 `Dockerfile` 的 `frontend` stage 把它拷成 `/etc/nginx/conf.d/default.conf`。
- 数据表（只读）：`ai_agent_featured_conversation`、`ai_agent_dialogue_session`、`ai_agent_dialogue_run`、`ai_agent_llm_invocation`、`ai_agent_tool_invocation`、`ai_agent_artifact`、`ai_agent_tool_output_*`、`ai_client_model`。
- 相关迁移文档：`docs/python-migration/{PLANS,inventory,api-contracts,database-ownership,risk-register,progress}.md`、根 `AGENTS.md`、`docs/python-migration/execplans/{featured-public-read,contract-lab}.md`。

## Contract and Invariants

见 `docs/python-migration/api-contracts.md` 与 `tests/contract/golden/java-featured.json`。本切片新增的不变量：

- **路由不变量**：仅上列 3 条 URI 命中 Python。近失路径必须继续命中 Java 并保持 Java 的 404 体：
  - `/api/agent/featured-conversations/`（尾斜杠）
  - `/api/agent/featured-conversations/a/b`（多段）
  - `/api/agent/featured-conversations/home/`（尾斜杠）
  - `/api/agent/featured-conversations/home/extra`
  - `/api/agent/featured-conversations/fixture-featured/`（detail 尾斜杠）
  - `/api/agent/session/{id}/capabilities`、`/web/health` 等对照路径
  - `/api/v1/admin/featured-conversations/*`
- **方法不变量**：nginx location 匹配与方法无关，非 GET 也会进 Python；因此 Python 的 405 体必须等于 Java 的 405 体（否则切流即回归）。实测后对齐或显式登记差异。
- **400 体不变量**：`?limit=abc`、`?pageNo=x` 的 400 体必须等于 Java `BasicErrorController` 形状（实测后对齐）。
- 响应头不得引入新差异（重点核对 `Server` / `Allow` / `Content-Type`）。
- 5xx 数不得因切流增加（固定探针集上计数前后对照）。
- 禁止随机百分比分流；禁止动 SSE 原子路由族。
- Python 继续使用只读账号 `reactor_py_ro`；Java 保持原账号。二者不得互换。
- 非确定字段仍只按 case 的 JSON Pointer 放行；禁止全局忽略；golden 缺字段永远算差异。

## Plan of Work

1. **路由 fragment** — 新增 `docker/nginx-featured-python.d/featured-conversations.conf`：
   ```nginx
   location = /api/agent/featured-conversations/home { proxy_pass http://reactor_backend_python; … }
   location = /api/agent/featured-conversations     { proxy_pass http://reactor_backend_python; … }
   location ~ ^/api/agent/featured-conversations/[^/]+$ { proxy_pass http://reactor_backend_python; … }
   ```
   三块的 proxy 头/超时与 `location /api/` **逐字一致**（不加 `proxy_buffering off`，避免与 Java 侧 `/api/` 行为漂移）。`proxy_pass` 不带 URI 部分 ⇒ 原样透传请求 URI。
2. **nginx.conf** — 新增 `upstream reactor_backend_python { server reactor-backend-python:8200; keepalive 32; }`；在 `location /api/` 之前放 `include /etc/nginx/featured-python.d/*.conf;` 并注明回滚方法。
3. **Dockerfile** — `frontend` stage 增加 `COPY docker/nginx-featured-python.d/ /etc/nginx/featured-python.d/`。
4. **docker-compose.yml** — frontend 增加 bind-mount 与 `depends_on: reactor-backend-python`。
5. **错误体对齐** — 探测 Java 400/405 形状后，把 `api/coercion.py` 的 400 从 `0002` 信封改为 Spring 形状；为 `StarletteHTTPException`（404/405）加同样形状的 handler；同步单测。
6. **drill harness** — `backend-python/tests/cutover/`：`gen_config.py`（从生产 `docker/nginx.conf` 生成可运行的 drill 配置，仅做 6 处断言过的替换，location 块字节不变）、`probes.py`（固定 14 探针 + `$upstream_addr` 归属 + 阶段间 diff）、`drill.sh`（nginx 生命周期 + 同组检查 + 切流/回滚/再切流 + 计时）、`README.md`。
7. **响应头一致性** — 关 `Server`（`--no-server-header`）、`X-Request-ID` 改回显制、补 `Vary` 三条兼容垫片；`probes.py` 把 `vary` 纳入硬性比对。
8. **实跑演练** — M3–M7。
9. **文档与门禁** — M8。

## Concrete Steps

工作目录：`/Users/cuimingkai/Documents/agent-2/ai-agent`（Python 门禁在 `backend-python/`）。

```bash
# 0) 状态归档
git status --short

# 1) Python 门禁
cd backend-python
uv sync --all-groups
uv run ruff check .
uv run mypy src
uv run pytest -m "not integration"

# 2) 路由配置语法检查（drill 配置；生产 include 的是同一份 fragment 字节）
nginx -t -p "$PWD/../build/cutover-drill/nginx/" -c "$PWD/tests/cutover/nginx-drill.conf"

# 3) throwaway MySQL（独立 datadir，绝不碰 /usr/local/var/mysql；R-31 三条 quirk）
DRILL=$PWD/../build/cutover-drill
mkdir -p "$DRILL/mysql-data"
mysqld --no-defaults --initialize-insecure --datadir="$DRILL/mysql-data"
mysqld --no-defaults --datadir="$DRILL/mysql-data" --port=3307 \
       --socket="$DRILL/mysql.sock" --pid-file="$DRILL/mysqld.pid" \
       --log-error="$DRILL/mysqld.log" &
mysql --no-defaults --socket="$DRILL/mysql.sock" -u root <<'SQL'
CREATE DATABASE ai_agent_station_contract CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'contract'@'127.0.0.1' IDENTIFIED BY 'test-only';
GRANT ALL ON ai_agent_station_contract.* TO 'contract'@'127.0.0.1';
SQL
mysql --no-defaults --socket="$DRILL/mysql.sock" -u root ai_agent_station_contract \
  < Reactor-agent-app/src/main/resources/db/schema.sql
mysql --no-defaults --socket="$DRILL/mysql.sock" -u root ai_agent_station_contract \
  < backend-python/tests/contract/fixtures/contract-seed.sql
#    只读账号：口令走会话变量，绝不写命令行/仓库/报告（R-34）
mysql --no-defaults --socket="$DRILL/mysql.sock" -u root ai_agent_station_contract
#    交互里: SET @reactor_py_ro_password := '<test-only secret>'; SET @reactor_py_ro_database := 'ai_agent_station_contract'; SOURCE db/migrations/20260923_provision_phase3_readonly_account.sql;

# 4) 起 Java（prod + test-only 覆盖；整条 [0] 参数必须加引号 —— zsh glob，R-31）
java -jar Reactor-agent-app/target/Reactor-agent-app.jar --spring.profiles.active=prod \
  --spring.datasource.mysql.driver-class-name=com.mysql.cj.jdbc.Driver \
  "--spring.datasource.mysql.url=jdbc:mysql://127.0.0.1:3307/ai_agent_station_contract?useUnicode=true&characterEncoding=utf8&autoReconnect=true&zeroDateTimeBehavior=convertToNull&serverTimezone=Asia/Shanghai" \
  --spring.datasource.mysql.username=contract \
  --spring.datasource.mysql.password=test-only \
  "--autobots.autoagent.skill.directories[0]=$PWD/backend-python/tests/contract/fixtures/skills" \
  > "$DRILL/java.log" 2>&1 &
curl -fsS --retry 30 --retry-delay 2 --retry-all-errors http://127.0.0.1:8100/web/health

# 5) 起 Python（只读账号；TZ 必须 Asia/Shanghai，R-07；
#    --no-server-header 是响应头一致性的 load-bearing 项，R-35）
cd backend-python
TZ=Asia/Shanghai \
REACTOR_PY_MYSQL_HOST=127.0.0.1 REACTOR_PY_MYSQL_PORT=3307 \
REACTOR_PY_MYSQL_DATABASE=ai_agent_station_contract \
REACTOR_PY_MYSQL_USER=reactor_py_ro REACTOR_PY_MYSQL_PASSWORD='<test-only secret>' \
REACTOR_PY_ENVIRONMENT=prod \
  uv run uvicorn reactor_backend.main:app --host 127.0.0.1 --port 8200 --no-server-header &
curl -fsS --retry 30 --retry-delay 2 --retry-all-errors http://127.0.0.1:8200/internal/health/ready

# 6) 起本地 nginx drill（:18080）
backend-python/tests/cutover/drill.sh up

# 7) 切流前 / 切流后 / 回滚后 / 再切流 后各跑一次同组检查
backend-python/tests/cutover/drill.sh check pre
backend-python/tests/cutover/drill.sh cutover      # 移入 fragment + nginx -t + reload（计时）
backend-python/tests/cutover/drill.sh check on-python
backend-python/tests/cutover/drill.sh rollback    # 移出 fragment + nginx -t + reload（计时 + 恢复验证）
backend-python/tests/cutover/drill.sh check on-java
backend-python/tests/cutover/drill.sh cutover
backend-python/tests/cutover/drill.sh check final

# 8) 门禁复跑 + compose 语法
cd backend-python && uv run ruff check . && uv run mypy src && uv run pytest -m "not integration"
cd ui && npx vitest run src/services/featuredConversation.test.ts \
  src/pages/FeaturedConversations/view.test.tsx \
  src/pages/FeaturedConversationDetail/view.test.tsx \
  src/pages/Home/WelcomeView.test.tsx
MYSQL_PASSWORD=test-only MYSQL_ROOT_PASSWORD=test-only REACTOR_PY_MYSQL_PASSWORD=test-only-ro \
  docker compose config --quiet
```

## Validation and Acceptance

以外部可观察行为描述：

1. **路由归属**：nginx access log `$upstream_addr` 证明三条 URI → Python upstream、对照/近失 URI → Java upstream。零条反例。
2. **UI 形态请求**：`/home?limit=6`、`?pageNo=1&pageSize=20`、`/{fixture-featured}` 经 nginx 均 HTTP 200 + `{"code":"0000","info":"成功",...}`。
3. **契约**：两份清单 `tests/contract/cases/phase3-featured.json` → `golden/java-featured.json`（3 case）与 `phase3-featured-errors.json` → `golden/java-featured-errors.json`（4 case），`PYTHON_BASE_URL=http://127.0.0.1:18080`，在四个阶段（pre / on-python / on-java / final）都 `cases == 期望数`、`skipped == []`、全部 `matched: true`、`differences == []`（R-32：**不得只看 exit code**）。
4. **近失路径不被吞**：尾斜杠/多段/嵌套路径返回 Java 的 404 体（不是 Starlette `{"detail":"Not Found"}`）。
5. **对照路径仍在 Java**：`/web/health` 返回 `ok`；`/api/agent/session/{id}/capabilities` 返回 Java 信封（若命中 Python 会是 `{"detail":"Not Found"}`）。
6. **5xx 未增加**：固定探针集在四个阶段的 5xx 计数为 0。
7. **回滚演练（强制实测）**：
   - 已实际切回 Java，并验证恢复（同组检查 on-java 全绿、路由归属反转）。
   - 再切回 Python，终态检查全绿。
   - 记录**路由配置语法检查**结果（`nginx -t` exit code）与**实际回滚用时**（配置生效用时 + 到首条恢复验证通过的端到端用时）。
8. **Python 只读**：进程以 `reactor_py_ro` 连接（启动日志/连接串账号名），且 3A 的 1142 拒写断言未被削弱。
9. **前端**：4 个 vitest 文件全绿（unchanged `ui/`）。
10. **400/405 体**：与 Java 实测形状一致，或差异被显式登记并说明兼容/回滚影响（不得静默放过）。
11. **门禁**：`ruff` / `mypy` / `pytest -m "not integration"` 全绿；`docker compose config --quiet` exit 0。
12. **`git diff` 自审**：无范围外改动、无秘密、`.workbuddy/` 未触碰。

## Cutover and Rollback

**切流（生产，compose）：**

```bash
# 前置：目标库已应用 db/migrations/20260923_provision_phase3_readonly_account.sql
#       compose 的 MySQL initdb 不含该账号，必须先由运维按迁移脚本开通。
docker compose exec frontend nginx -t            # 语法检查
docker compose exec frontend nginx -s reload     # 生效；fragment 已在镜像/bind-mount 中
```

**一键回滚（生产）：**

```bash
mv docker/nginx-featured-python.d/featured-conversations.conf{,.disabled}
docker compose exec frontend nginx -t && docker compose exec frontend nginx -s reload
```

**再切流：**

```bash
mv docker/nginx-featured-python.d/featured-conversations.conf{.disabled,}
docker compose exec frontend nginx -t && docker compose exec frontend nginx -s reload
```

**为何不是"改 nginx.conf 注释 include"：** bind-mount 使开关落在宿主机目录，容器重启不回弹；`git status` 可见开关状态；回滚动作是 3 条 shell 命令。

**活跃状态处理：** 本切片**不涉及 active run**。三条路由均为无身份写副作用的 public GET，无 in-memory run owner、无 SSE、无百分比分流。回滚**无数据库状态需要恢复**，也不影响任何活跃 run（SSE 原子路由族完全未触碰）。

**数据核对：** 全程只读。核对项是响应体与 golden 的一致（契约报告）与 5xx 计数，不是行数 diff。

## Idempotence and Recovery

- 切流/回滚/再切流都是"文件在位与否 + `nginx -t` + reload"，可任意重复，无副作用。
- 中断后看 `Progress` 未勾项继续；`drill.sh check <phase>` 可随时重跑（只读探针）。
- 任一阶段检查失败：先看 `build/cutover-drill/checks/<phase>/` 下的探针输出与 `access.log` 的 `$upstream_addr`；若是路由归属错，检查 fragment 是否在位；若是契约差异，修 Python 侧，**禁止**改 `java-featured.json` / `java-initial.json` 消差异。
- 切流失败一半（nginx 拒绝 reload）：`nginx -t` 已拦在 reload 前，旧配置仍服务；修正 fragment 后重试，或直接执行一键回滚。
- 演练环境清理：`drill.sh down`（停 nginx/Java/Python/mysqld 并保留日志于 `build/cutover-drill/` 供审计）。

## Interfaces and Dependencies

**公共 HTTP（切流后由 Python 服务）：** 3 条 GET（见 Scope）。

**nginx location 契约（fragment 内部约定）：**
- `location = /api/agent/featured-conversations/home`
- `location = /api/agent/featured-conversations`
- `location ~ ^/api/agent/featured-conversations/[^/]+$`
- 三者 `proxy_pass http://reactor_backend_python;`（无 URI 重写）
- proxy 头集合 = `location /api/` 的 `Host` / `X-Real-IP` / `X-Forwarded-For` / `X-Forwarded-Host` / `X-Forwarded-Port` / `X-Forwarded-Proto` + `proxy_read_timeout 3600s` / `proxy_send_timeout 3600s`

**新增生产依赖：** 无。`docker/nginx-featured-python.d/` 只是配置。

**Python 侧（3A 已有，本切片只动错误体呈现）：** `api/coercion.py`、`api/presenters.py`、`api/routers/featured_conversations.py`、`api/exception_handlers.py`。

## Artifacts and Evidence

- 路由配置：`docker/nginx-featured-python.d/featured-conversations.conf`、`docker/nginx.conf`、`Dockerfile`、`docker-compose.yml`
- 错误体/响应头对齐：`backend-python/src/reactor_backend/api/{presenters,exception_handlers,middleware,coercion}.py`、`api/routers/featured_conversations.py`、`backend-python/Dockerfile`
- 契约证据：`backend-python/tests/contract/cases/phase3-featured-errors.json`、`backend-python/tests/contract/golden/java-featured-errors.json`
- 演练 harness：`backend-python/tests/cutover/{gen_config.py,probes.py,drill.sh,README.md}`
- 演练证据（不入版本库，路径记录在此）：`build/cutover-drill/`（`nginx/access.log`、`checks/<phase>/probes.json|contract-*.json|frontend.txt`、`timing.log`、`java.log`、`python.log`）
- 对照基线：`backend-python/tests/contract/golden/java-featured.json`（3A）
- 最终报告：修改文件、验证命令与结果、契约差异、风险、回滚方法、未完成事项
