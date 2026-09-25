# Featured conversations admin 写域垂直切片（Phase 4 — featured-admin）

本 ExecPlan 遵循 `docs/python-migration/PLANS.md`，执行期间必须保持自包含并持续更新。

## Purpose / Big Picture

把 `ai_agent_featured_conversation` 的**写操作**（create / update / online / offline / query-list）从 Java 迁到 `backend-python/`，补齐 featured 垂直域的写侧。读侧已在 Phase 3A/3B 切到 Python，因此本切片的写入效果可以**直接从已切流的公共读接口观察**——上线一条精选后 `/api/agent/featured-conversations/home` 立刻能看到它，无需额外缓存探针。

成功可直接观察：在克隆库上，同一请求序列分别打到 Java 与 Python，HTTP 响应与 `ai_agent_featured_conversation` 全表内容等价；Nginx 五条 admin 路径可精确切到 Python 并反向回滚。

## Scope

**路由（5 条，全在 `/api/v1/admin/featured-conversations`）：**

| 方法 | 路径 | 输入 | 成功响应 |
|---|---|---|---|
| POST | `/create` | JSON `UpsertReqVO` | `{"code":"0000","info":"成功","data":true\|false}` |
| PUT | `/update` | JSON `UpsertReqVO` | 同上 |
| POST | `/online/{featuredId}` | query `operator`（**必填**） | 同上 |
| POST | `/offline/{featuredId}` | query `operator`（**必填**） | 同上 |
| POST | `/query-list` | JSON `QueryReqVO` | `data={"total":int,"list":[…]}` |

**包含：** domain 规则、application 用例 + writer fence、infrastructure 写 SQL（含 `FOUND_ROWS` rowcount 对齐）、api 路由、per-writer 数据库账号迁移 SQL、unit + integration 测试、克隆库 Java/Python 对比、Nginx admin 切流片段 + 切流/回滚演练、文档同步。

**不包含：** 其余 admin CRUD（`ai-client-api` / `ai-client-model` / `ai-client-tool-mcp` / `admin-user` / `sub-agent-definitions` / `skills`）；visitor identity 写；capability 写；任何 schema 变更（无 Alembic，改表不在本阶段）；Java 侧任何修改；React UI / `reactor-tool` / `reactor-sandbox` / `runtime/skills` 行为变更；真实 provider 调用；公共读路由的行为变更。

**工作区用户资产（禁触碰）：** `?? .workbuddy/`、既有 `M docs/python-migration/*` 中与本切片无关的改动（只增量追加）、`reactor-tool/.env`（绝不读取）、`/usr/local/var/mysql`（绝不触碰）、MySQL 客户端凭据存储（`~/.my.cnf` 等，绝不读取 — R-34）。

## Writer fence、部署顺序与回滚顺序（切流前必读）

**唯一 writer（操作粒度，表 `ai_agent_featured_conversation`）：**

| 操作 | 当前 owner | 本切片后 owner |
|---|---|---|
| create（含 upsert insert 分支） | Java | Python（切流后） |
| update（含 upsert update 分支） | Java | Python（切流后） |
| online / offline（`updateStatus`） | Java | Python（切流后） |
| query-list（管理端读） | Java | Python（切流后） |
| 公共读 home/list/detail | **Python（3B 已切）** | 不变 |
| `ai_agent_dialogue_session` 读（create 的存在性检查） | Java/Python 共享读 | 不变（只读） |

**两道 fence，都 fail closed：**

1. **数据库账号（技术强制，表粒度）**：新增 `reactor_py_featured_writer`（迁移 SQL `db/migrations/20260923_provision_phase4_featured_writer_account.sql`），权限为 `SELECT ON <db>.*` + `INSERT, UPDATE ON <db>.ai_agent_featured_conversation`——**没有 DELETE**（所有"删除"都是 `deleted=0` 更新），没有其它表的写权限。compose 默认仍指向 `reactor_py_ro`，写语句一律 `ERROR 1142`。
2. **应用层 owner fence**：`REACTOR_PY_FEATURED_ADMIN_WRITE_OWNER`，默认 `java`。不等于 `python` 时**四条写路由**（`create`/`update`/`online`/`offline`）在**执行任何 SQL 之前**拒绝（`ApiError` 0001 信封），不会产生数据写入。`query-list` 是只读操作，**不设 fence**（否则 owner=java 时管理端连查都查不了）；Nginx 片段仍然切它，因为它是同一族路径、同一响应形状。

**部署/切流顺序（正向）：**

1. 更新 `database-ownership.md`：create/update/online/offline 的 owner 记为 Java→Python 切换点。
2. 部署 Python 写代码，但 `REACTOR_PY_FEATURED_ADMIN_WRITE_OWNER=java`、`REACTOR_PY_MYSQL_USER=reactor_py_ro`（fence 双关）。
3. 开通 `reactor_py_featured_writer` 账号（迁移 SQL），把 `REACTOR_PY_MYSQL_USER` 指向它、`REACTOR_PY_FEATURED_ADMIN_WRITE_OWNER=python`——此刻 Python **可写但不收写流量**。
4. Nginx：放入 `docker/nginx-featured-python.d/featured-admin.conf`（五条 admin 路径）→ `nginx -t && nginx -s reload`。**此刻起 Python 是唯一活动写入者。**
5. 验证：克隆库对比 + 公共读可见性。

**回滚顺序（反向，必须先切路由再收回写权）：**

1. `mv docker/nginx-featured-python.d/featured-admin.conf featured-admin.conf.disabled` → `nginx -t && nginx -s reload`。写流量回到 Java。
2. `REACTOR_PY_FEATURED_ADMIN_WRITE_OWNER=java`、`REACTOR_PY_MYSQL_USER=reactor_py_ro`。
3. 核对 `ai_agent_featured_conversation`：回滚窗口内的写入都走 Java，无需数据修复；若需追溯，按 `updated_by`/`updated_at` 对账。

任意时刻只有一个活动写入者：**Nginx 精确路径是流量开关，账号是物理开关，owner 标志是应用开关**。三者按上面顺序翻转，不存在双写窗口。

## Progress

- [x] (2026-09-23) 归档 `git status --short`；研究 Java 参考实现 / 前端消费者 / SQL / mapper / 测试；建立本 ExecPlan。
- [x] domain 纯层 + unit 测试（校验、featuredId 生成、状态迁移、upsert PO 组装、admin 视图、Jackson 式分页钳制）。
- [x] application 用例 + writer fence + fake 单测。
- [x] infrastructure 写 SQL（upsert / updateStatus / queryAdminList / queryBySessionId）+ `FOUND_ROWS` 对齐。
- [x] api 路由 + `main.py` 接线 + 路由测试（含 500/400 four-key 形状）。
- [x] per-writer 账号迁移 SQL（`db/migrations/20260923_provision_phase4_featured_writer_account.sql`）。
- [x] integration 测试（ON DUPLICATE 列保持、唯一键、rowcount、软删、并发）—— **47 passed**。
- [x] Nginx admin 切流片段 + 切流/回滚演练（2026-09-25：cutover 0.087s、rollback 0.084s apply + 0.512s 验证）。
- [x] 克隆库 Java/Python before/after 对比 —— **`differences=0`**，32 cases，四个 failure bucket 全空。
- [x] 文档同步（`database-ownership.md` + `inventory.md` + `api-contracts.md` + `risk-register.md` + `progress.md`，2026-09-25 全部已更新）+ 最终门禁 + `git diff` 自审。
- [x] (2026-09-25 收尾复跑) ruff / mypy / 256 unit / 47 integration / contract `--record-java` 逐字节 + `--golden` 15/15 / parity `differences=0` / drill `down` 已停。
- [x] (2026-09-25) `reactor_py_ro` / `reactor_py_featured_writer` 口令均使用 bootstrap.sh 生成的 **test-only** 一次性口令；**没有**触碰生产口令或 `~/.my.cnf`。
- [ ] (blocked, R-34) 需操作者提供**生产**口令的门禁：生产栈端到端 1142 复验、`docker-compose` 真实 secret 注入。本切片不持有该口令。

## Surprises & Discoveries

- Observation: `FeaturedConversationAdminController` **没有 try/catch**，`IllegalArgumentException` 会逃逸成 HTTP 500 + Spring `BasicErrorController` four-key 体；而 `SubAgentDefinitionAdminController` 同样的异常被 catch 并映射为 0002 信封。两者的不一致是契约数据，不得"顺手统一"。
  Evidence: `Reactor-agent-trigger/.../FeaturedConversationAdminController.java`（无 catch）vs `SubAgentDefinitionAdminController.java:141-171`（catch + 0002）；全仓 `grep -r "ControllerAdvice\|@ExceptionHandler"` 零命中。
- ~~Observation (2026-09-23, **已被 2026-09-25 的实测推翻，保留以记录错误推理**)~~：曾断言 Lombok `@Builder.Default` 只搬进 `$default$` 静态方法、无参构造不赋值，因此缺省是 0/0。
  **Correction (2026-09-25)**：`javap -p -c` 的**无参构造**字节码是 `<init>` → `invokestatic $default$pageNo()` → `putfield pageNo` → `invokestatic $default$pageSize()` → `putfield pageSize`，`$default$pageNo()` 返回 **1**、`$default$pageSize()` 返回 **10**。所以 **key 缺失 → 1/10（构造器安装），key 存在且值为 JSON `null` → setter 写 0**（`FAIL_ON_NULL_FOR_PRIMITIVES` 关）。两者在 wire 上可区分，实测：`{}` → total=4/len=4；`{"pageSize":null}` → 4/1；`{"pageNo":2}` → 4/**0**（offset=(2−1)×10=10）。早先的 `0/0 → limit 1` 结论是错的，已连同测试与 parity case 一并改正。
  Evidence: `javap -p -c …/FeaturedConversationAdminQueryReqVO.class`；`backend-python/tests/parity/featured_admin_parity.py` 8 组分页探针 Java/Python 全等。
- Observation: MySQL Connector/J 默认 `useAffectedRows=false`（即设置 `CLIENT_FOUND_ROWS`），因此 `INSERT ... ON DUPLICATE KEY UPDATE` 的"无变化更新"返回 1、`UPDATE` 匹配但未改列也返回 1；asyncmy 默认 `CAPABILITIES` **不含** `FOUND_ROWS`（`3842565 & 2 == 0`），同类语句返回 0。Java 的 `upsert(po) > 0` / `updateStatus(...) > 0` 因此在 Python 侧若照抄会把"幂等重复"误判为失败。
  Evidence: `application-prod.yml` JDBC URL 无 `useAffectedRows`；`asyncmy.constants.CLIENT.CAPABILITIES & CLIENT.FOUND_ROWS == 0`。
- Observation: upsert 的 `ON DUPLICATE KEY UPDATE` **不更新** `session_id` / `featured_id` / `status` / `published_by` / `published_at`。所以 update 改 sessionId 会被静默忽略；靠 sessionId 唯一键触发的重复也不会改写 featuredId。
  Evidence: `featured_conversation_mapper.xml:30-48`。
- Observation: 表上有两个 UNIQUE 键（`featured_id`、`session_id`），所以"重复"有两个触发面；`create` 恒定生成 `featured_" + trim(sessionId)`，请求体里的 `featuredId` 被完全忽略。
  Evidence: `db/schema.sql:580-605`；`FeaturedConversationAdminApplicationService.create`。
- Observation: 该域**没有缓存/registry**。Java 写完直接落库，公共读也是直查；可观察副作用 = 已切流的公共读立即可见。
  Evidence: `FeaturedConversationAdminApplicationService` 只依赖 repository + `ExecutionLedgerQueryService`；无 cache/reload 调用。
- **(2026-09-25, parity 抓到的第一个真实缺陷)** `FeaturedConversationRepository.upsert` 入口有空值守卫：`command == null || StringUtils.isBlank(featuredId) || StringUtils.isBlank(sessionId)` → **直接返回 `false`，不发任何 SQL**。`create` 永远到不了（sessionId 已校验、featuredId 已生成），但 `update` 可以：带合法 `featuredId`、**不带 `sessionId`** 的请求会通过存在性预检，再在守卫处空转——HTTP 200 + `data:false`，行完全没动。Python 侧漏了这道守卫，于是同一请求在 Python 返回 `data:true` **且真的写了**（title 被改成 v3、`sortOrder` 归 0、`summary` 归 null）。更隐蔽的是：随后一个带 `sessionId` 的 `update-session-retarget` 让两边**最终表状态收敛**，所以**表 diff 是空的**——只有响应对比抓得到。前端不受影响：`FeaturedConversationAdminUpsertPayload.sessionId` 是必填且前端校验非空。
  Evidence: `FeaturedConversationRepository.java` 守卫；parity `update-s1` 响应 `java:false` vs `python:true`；`ui/src/pages/Home/featuredConversationAdminModel.ts:51` 非空校验。修复：`domain/featured_admin.py::upsert_guard_blocks` + 用例在 `_resolve_existing` **之前**调用（与 Java 守卫位于 resolve 查询之前的顺序一致）。
- **(2026-09-25)** Starlette 把 `@app.exception_handler(Exception)` 交给 **`ServerErrorMiddleware`**，它位于**用户 middleware 之外**——所以未经处理的异常产生的 500 响应**不会**经过 `RequestContextMiddleware`，`JAVA_COMPAT_VARY` 三元 `Vary` 因此缺失。Java 侧 `CorsFilter` 是 servlet filter、在 error dispatch 之下，照样盖章，于是 `create-null-title`（IntegrityError → 未处理异常）成为唯一一条 `Vary` 不一致的响应。其余 handler（`ApiError`/`HTTPException`/`RequestValidationError`）走 `ExceptionMiddleware`，在用户 middleware 之内，正常盖章。
  Evidence: `starlette/middleware/errors.py` vs `applications.py` 中间件栈顺序；parity 唯一的 `('server','vary')` 差异。修复：`handle_unexpected_error` 自行 append `JAVA_COMPAT_VARY`（该路径下方不会重复盖章）。
- **(2026-09-25)** `--no-server-header` 是 load-bearing（R-35）：Dockerfile 已带，但**本地手工起的 uvicorn 必须也带**，否则 30 条 case 会因 `Server: uvicorn` 全线不匹配。Java 不发 `Server` 头。
  Evidence: `backend-python/Dockerfile` `CMD [... "--no-server-header"]`；本地漏加时 parity 的 30 条 header 差异。
- **(2026-09-25) 工具链坑，三个都只在首次真跑时暴露**：
  1. macOS 是 **BSD xargs**，`command -v nginx | xargs -I{} {}` 会报 `xargs: {}: No such file or directory` 并**在调用 nginx 之前**失败；改用 `drill.sh` 的 `"$(nginx_bin)"` 形式。
  2. `tests/` 没有 `__init__.py`（phase-3B 的 `probes.py` 只 import `reactor_backend.*`）。把 `admin_probes.py` 当脚本跑会把**它自己的目录**塞进 `sys.path[0]`，`from tests.cutover.probes import …` 直接 `ModuleNotFoundError`。解决：调用时带 `PYTHONPATH=$BACKEND_PY`。
  3. `compare_to_reference` 在 `probes.py` 里调 `ProbeResult.normalized_body()`，那解析的是**phase-3B 的** `EXTRA_POINTERS`——我的 admin `updatedAt`/`publishedAt` allowlist 只在 `admin_probes._attach_normalized`（存档）生效，**跨 phase 对比里根本没生效**，于是把两边克隆库的时钟差误报成回归。解决：给 `compare_to_reference` 加 `normalizer=` 参数并由 `admin_probes` 传入自己的实现。
- **(2026-09-25)** 预期中的 5xx 必须被声明而不是被容忍。probe 集刻意构造"Java 会拒绝"的输入（空 sessionId、未知 featuredId），那 500 four-key **就是被测契约**；但 `main()` 原先用「任何 5xx 即失败」，导致 `check pre` 永远红。改成 `EXPECT_STATUS` 映射：列出的探针**必须**返回其预期状态（形状变了同样失败），未列出的 5xx 仍然是硬失败。
- Observation: `Database.connect()` 必须用 `engine.begin()`。SQLAlchemy 2.0 的 `connect()` **退出即回滚**；用它包 INSERT 会静默丢数据（实测：INSERT 消失）。`engine.begin()` 干净退出才 commit。Java 的 admin 服务无 `@Transactional`，因此每个 repository 方法**恰好一个** `connect()` 块。
  Evidence: `infrastructure/database/engine.py` 中 load-bearing 的 docstring 与对照实测。
- Observation: MySQL 9.3 对 `ON DUPLICATE KEY UPDATE ... VALUES(col)` 打 deprecation 警告。**SQL 与 Java 完全一致，这是 parity 的一部分，不许"修"**。
  Evidence: integration 运行日志 `'VALUES function' is deprecated ...`。
- **(2026-09-25)** 克隆库会**被测试自己污染**，而 parity 必须在写入前把它抓出来。收尾复跑 parity 首次 `differences=7`：Python 侧多出 `ro-denied` 行、`fixture-featured.summary='denied'`。根因是**我自己**先前一次 integration 误把 `TEST_MYSQL_URL` 指到「writer 账号 + `ai_agent_station_py`」——只读拒绝用例的 `INSERT`/`UPDATE` 于是成功（`DELETE`/`CREATE` 仍被 1142 拒绝，所以行留了下来）。这正是 R-33 描述的污染类，且**不是仓库缺陷**：脚本在写入前把漂移报成具名发现，而不是最后给出一个来历不明的 diff。修复 = 还原两列后复跑 → `cases=32 differences=0`。
  Evidence: `build/parity-rerun.log`（首次）与 `differences=0`（复跑）。

## Decision Log

- Decision: 切片选 `featured-admin`（featured 垂直域的写侧），不做 visitor-identity / capability / ai-client-*。
  Rationale: 读侧已在 3A/3B 落地并切流，写侧效果可直接从公共读观察；单表、边界清晰；prompt 要求一次只做一个写域。
  Date/Author: 2026-09-23 / Codex
- Decision: 复用并扩展 `infrastructure/repositories/featured_conversation_repository.py`，不新建第二个仓库类。
  Rationale: Java 的 `IFeaturedConversationRepository` 读写同口；拆成两个 Python 仓库会造成列清单与 `_row_to_entity` 双份、易漂移。
  Date/Author: 2026-09-23 / Codex
- Decision: 显式给 asyncmy 连接加 `FOUND_ROWS` client flag，而不是在仓库层把 rowcount 语义"翻译"掉。
  Rationale: prompt 要求保留"条件 update rowcount 语义"；对齐驱动 flag 让 `> 0` 的含义与 Java 逐条一致（含 CAS 竞争窗口里的 0 行），仓库层翻译会把"并发软删导致 0 行"和"无变化更新"混为一谈。
  Date/Author: 2026-09-23 / Codex
- Decision: writer fence 用「表粒度写账号 + 应用层 owner 标志」双开关，默认都是关（`reactor_py_ro` / `owner=java`）。
  Rationale: 账号是物理强制（R-22 的延续），owner 标志是显式所有权声明；两者都 fail closed，翻转顺序写死在本文，不存在双写窗口。
  Date/Author: 2026-09-23 / Codex
- Decision: 业务校验失败（`IllegalArgumentException`）复刻为 **500 four-key**，不"顺手"映射成 0002 信封。
  Rationale: 不要借迁移修正既有行为；该控制器确实没有 catch。`SubAgentDefinitionAdminController` 的 0002 是另一条路由的契约。
  Date/Author: 2026-09-23 / Codex
- Decision: 请求体不走 Pydantic `response_model`/自动 422，改为读原始 JSON + Jackson 式字段 coercion。
  Rationale: FastAPI 自动 422 + `{"detail":…}` 是明确禁止的漂移。
  Date/Author: 2026-09-23 / Codex
- Decision (revised 2026-09-25): `pageNo`/`pageSize` **区分"key 缺失"与"JSON null"**——缺失 → `ABSENT_PAGE_NO=1` / `ABSENT_PAGE_SIZE=10`（Lombok 无参构造安装），null → `0`（setter 写入）。`_query_condition` 用 `"pageNo" not in payload` 判缺失，而不是 `payload.get()`。
  Rationale: 2026-09-23 那版把两者都当成 0，是**错的**：`javap` 显示无参构造调用 `$default$` 访问器，且 8 组实测探针里 `{}`→len=10 宽、`{"pageSize":null}`→len=1 宽。合并二者会在切流后让管理端分页宽度从 10 跳到 1。
  Date/Author: 2026-09-25 / Codex
- Decision (2026-09-25): 空 `sessionId` 守卫放在**用例层**、`_resolve_existing` **之前**，而不是仓库 `upsert(po)` 里。
  Rationale: Java 的守卫在 `FeaturedConversationRepository.upsert` 入口，位于其内部 resolve 查询之前；Python 的 resolve 发生在用例里，所以守卫必须同样前移到 resolve 之前，才能保持"存在性预检 → 守卫 → resolve SELECT → 写入"的调用序列与竞态窗口一致（仓库层放守卫会多出一次 SELECT）。
  Date/Author: 2026-09-25 / Codex
- Decision (2026-09-25): parity 的 `query-list-lombok-defaults` **不设** `expect_list_length`，另加一条 `{"pageSize": null}` 探针钉 `expect_list_length=1`。
  Rationale: 不过滤列表的页宽上限是 10，而 replay 会不断加行——绝对长度不是 replay-stable 的。`{"pageSize":null}` 的 limit 恒为 1，与行数无关，才是稳定的绝对钉子；`{}` 那条靠 `mode="shape"` 的 Java↔Python 交叉对比来抓差异。
  Date/Author: 2026-09-25 / Codex
- Decision: `create`/`update` 的多条语句**不用**单一事务包裹。
  Rationale: Java 的服务层无 `@Transactional`，每条 mapper 调用各自 auto-commit；用单事务会改变隔离语义（并发下可见性不同）。
  Date/Author: 2026-09-23 / Codex

## Outcomes & Retrospective

**状态（2026-09-25）：切片完成，全部门禁通过；生产切流本身尚未执行（那是运维动作，不是本切片的交付物）。**

### 门禁与实测数字

| 门禁 | 结果 |
|---|---|
| `uv run ruff check src/ tests/` | All checks passed! |
| `uv run mypy src` | Success: no issues found in 52 source files |
| `uv run pytest -m "not integration"` | **256 passed** |
| `uv run pytest -m integration`（:13307） | **47 passed** |
| `reactor-contract --record-java` | 15 cases，`skipped=[]`，且与已提交 golden **逐字节相同** |
| `reactor-contract --golden`（live Python） | `cases=15 skipped=[] differing=[]` |
| parity（克隆库，32 cases） | `differences=0`；`failures={responses:[], tables:{}, stamps:{}, untouched:{}}`；`warnings.sort_order_guard=[]` |
| 分页 ground truth（8 组探针） | Java/Python 全等，`differences=0` |
| `admin_drill.sh` 切流 | **0.087s**（文件复制 + `nginx -t` + reload） |
| `admin_drill.sh` 回滚 | apply **0.084s**，端到端验证 **0.512s**（含恢复探针） |
| `check pre` / `on-python` / `on-java` | 各 17 probes、`routing_violations=0`、`diffs_vs_reference=0`；contract 15/`skipped=[]`；前端 11 tests passed |
| owner fence fail-closed（实机） | `owner=java` 四条写路由全部 `200 + code 0001`，`query-list` 与 `/internal/health/ready` 照常 200 |
| UI consumer（不改 `ui/`） | 11 passed |
| `docker compose config --quiet` | 通过 |

### 必须留档的教训

1. **`Database.connect()` 用 `connect()` 会静默丢数据。** SQLAlchemy 2.0 的 `connect()` 退出即回滚。改用 `engine.begin()`。这是本次最贵的一个坑——单测全绿、integration 全绿，只有真的去看行才发现在回滚。
2. **表 diff 为空 ≠ 行为等价。** `update-s1` 那个缺陷在**中间**产生了不同的行状态，随后一个操作让两边收敛，最终表 diff 是干净的。**只有响应对比抓得到它。** 这条要刻在后面每个写域的 parity 设计里。
3. **推翻自己之前"已确认"的结论。** 09-23 我用 `javap` 得出"缺省 0/0"，09-25 复看同一份字节码才发现无参构造**确实**调用了 `$default$` 访问器。差异在于上次只盯着字段声明、没读 `<init>`。**字节码要看构造器，不能只看字段。** 被推翻的旧结论保留在 Surprises 里而不是删掉。
4. **normalize 必须跟着探针集走。** `compare_to_reference` 放在共享模块里、却硬解析调用方自己的 `ProbeResult.normalized_body()`，结果 allowlist 静默失效、把克隆库的时钟差报成回归。跨模块复用"带配置的纯函数"时，配置必须作为参数传入。
5. **预期失败要显式声明。** 「任何 5xx 都失败」和「这三条必须 500」不能同时成立；`EXPECT_STATUS` 让两件事各自被断言。

### 未完成 / 移交

- **生产切流未执行。** 正向顺序见上文「部署/切流顺序」；本切片交付的是已演练的开关与顺序，不是生产上的翻转。
- **(R-34) 生产口令相关门禁仍阻塞**：`reactor_py_ro` 的生产口令不在仓库内、也不由本切片持有，因此"生产栈在 `reactor_py_ro` 下的端到端 1142 复验"未跑。测试侧用的是 `bootstrap.sh` 生成的一次性口令，且**没有**去 `~/.my.cnf` 等凭据库检索。
- **Java characterization（`mvn -Dtest='FeaturedConversation*'`）未在本轮重跑**：app 基线本身是红的（R-02/R-18），且 Java 侧行为已由 `--record-java` 逐字节复现 + parity 响应全等覆盖。若要留档单测结果，需单独跑一次。
- **`reactor_py_featured_writer` 尚未写入 `docker-compose.yml`**：compose 仍默认 `reactor_py_ro`（fail closed）。生产切流步骤 3 才改。
- **迁移文档已同步（2026-09-25）**：`database-ownership.md`（唯一 writer / 两层 fence / 开关与耗时）、`inventory.md`（路由表 + Python 侧路由清单 + phase-4 模块）、`api-contracts.md`（新增「Admin featured write contract」实测小节、deferred registry 该行改为 Covered、覆盖计数 29 cases）、`risk-register.md`（R-22 写侧闭环、R-31/R-32 补记，新增 R-37 normalizer 分派、R-38 absent≠null、R-39 预期 5xx）、`progress.md`（phase 4 首切片行 + 完整验证日志）。
- **`status='ONLINE'` collation 探针仍未做**（`api-contracts.md` 的 Derived 表 owner=4，本切片没有关掉它）。

## Context and Orientation

- Java 入口：`Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/FeaturedConversationAdminController.java`
- Java 用例：`Reactor-agent-case/src/main/java/org/wwz/ai/application/agent/featured/FeaturedConversationAdminApplicationService.java`
- Java 仓储：`Reactor-agent-infrastructure/src/main/java/org/wwz/ai/infrastructure/adapter/repository/FeaturedConversationRepository.java`
- Java DAO/PO：`Reactor-agent-infrastructure/src/main/java/org/wwz/ai/infrastructure/dao/reactor/IFeaturedConversationDao.java`、`…/dao/po/FeaturedConversationPO.java`
- SQL：`Reactor-agent-app/src/main/resources/mybatis/mapper/featured_conversation_mapper.xml`
- 表 DDL：`Reactor-agent-app/src/main/resources/db/schema.sql:580-605`
- 领域模型：`Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/ledger/model/FeaturedConversation{UpsertCommand,QueryCondition,AdminView,PageResult}.java`
- 前端消费者：`ui/src/services/featuredConversationAdmin.ts`、`ui/src/pages/Home/featuredConversationAdminModel.ts`、`ui/src/pages/Home/FeaturedConversationAdminPanel.tsx`、`ui/src/pages/Home/index.tsx`
- Python 目标：`backend-python/src/reactor_backend/`（`api/` `application/` `domain/` `infrastructure/`）
- 部署路由：`docker/nginx.conf`（`location /api/` → Java `:8100`）+ `docker/nginx-featured-python.d/`（3B 三条公共读已切）
- 相关文档：`docs/python-migration/{api-contracts,database-ownership,risk-register,progress,inventory,PLANS}.md`

## Contract and Invariants

- 信封 `{"code","info","data"}`；`Response` 字段序 `code, info, data`；`PageRespVO` 字段序 `total, list`。
- `FeaturedConversationAdminRespVO` 字段序：`featuredId, sessionId, title, summary, tags, coverUrl, sortOrder, status, publishedAt, updatedAt`（**无** `coverResourceKey`）。
- 时间 JSON 复用 `format_local_datetime`（零毫秒省略小数、非零 3 位；禁 `isoformat()`）。
- **业务校验失败 = HTTP 500 + four-key**（`{"timestamp","status":500,"error":"Internal Server Server Error","path":…}`），不是 0001/0002 信封。触发面：create 空 sessionId、create 会话不存在、update 空 featuredId、update featuredId 不存在、SQL NOT NULL 违例（如 title 为 null）、未被 ON DUPLICATE 吸收的唯一键冲突。
- **传输失败 = four-key 对应状态码**：缺 `operator` 查询参数 → 400；缺 body / JSON 非法 → 400；未映射路径/方法 → 404/405。
- online/offline 对空 featuredId 或行不存在返回 **200 + `data:false`**（不是 500）。
- `create` 生成 `featuredId = "featured_" + trim(sessionId)`；请求体 `featuredId` 被忽略。`update` 的 featuredId/sessionId **不 trim**。
- upsert 的 `ON DUPLICATE KEY UPDATE` 只更新 `title, summary, cover_resource_key, cover_url, tags_json, sort_order, updated_by, updated_at, deleted=0`。
- upsert 插入分支：`status='OFFLINE'`、`publishedBy=operator`、`publishedAt=null`；更新分支：`status/publishedBy/publishedAt` 取自 existing（status 空白→`OFFLINE`）。
- `sortOrder` null → 0；`tags` null → `[]`，fastjson 紧凑 JSON（`ensure_ascii=False`、无空格）。
- `query-list` 分页：`offset=(max(1,pageNo)-1)*max(1,pageSize)`、`limit=max(1,pageSize)`；**缺省 pageNo/pageSize = 0 → 钳到 1/1**（Lombok 陷阱）。过滤：`status`/`sessionId` 精确（null/`''` 跳过）、`title` `LIKE '%…%'`（null/`''` 跳过）；`deleted=0`；`ORDER BY sort_order DESC, id DESC`。
- rowcount 语义：`> 0` 在 Java 侧是 **found rows**（`CLIENT_FOUND_ROWS`）。Python 必须等价。
- 非确定字段（`updatedAt`/`publishedAt` 的时钟值）只按单 case 的 JSON Pointer 放行；禁全局忽略。

## Plan of Work

文件布局（`backend-python/src/reactor_backend/`）：

- `domain/featured_admin.py` — 命令校验、`featuredId` 生成、upsert PO 组装、状态迁移、admin 视图组装、Jackson 式分页钳制
- `application/featured_conversation_admin.py` — `FeaturedConversationAdminUseCase` + 端口 + writer fence
- `api/body_coercion.py` — 请求体 JSON 解析 + Jackson 式字段 coercion（替代 Pydantic 422）
- `api/routers/featured_admin.py` — 5 条路由
- `infrastructure/repositories/featured_conversation_repository.py` — 扩展写 SQL（`upsert` / `update_status` / `query_by_session_id` / `query_admin_list` / `count_admin_list`）
- `infrastructure/database/engine.py` — 连接加 `client_flag=FOUND_ROWS`
- `config.py` — `featured_admin_write_owner`
- `main.py` — 装配

测试：

- unit：`tests/unit/test_featured_admin.py`（规则）、`tests/unit/test_featured_admin_routes.py`（HTTP 形状/错误形状）、`tests/unit/test_body_coercion.py`
- integration：`tests/integration/test_featured_admin_write_repository.py`（ON DUPLICATE 列保持、双唯一键、rowcount/FOUND_ROWS、软删、并发）
- parity：`tests/parity/featured_admin_parity.py` + `tests/parity/README.md`（克隆库 before/after）
- cutover：`tests/cutover/featured-admin.conf`（Nginx 片段）+ `tests/cutover/admin_drill.sh` + `tests/cutover/admin_probes.py`
- 迁移 SQL：`db/migrations/20260923_provision_phase4_featured_writer_account.sql`

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

# 2) integration（throwaway mysqld。端口是 13307 —— 3307 被 phase-3 遗留实例占用；
#    datadir 在 build/ 下，绝不碰 /usr/local/var/mysql）
#    mysqld --no-defaults --datadir=build/admin-mysql/data \
#      --socket=build/admin-mysql/mysql.sock --port=13307
#    一键：build/admin-mysql/bootstrap.sh（建三库 + parity_admin + writer 账号 + 写 test.env）
#    加载 db/schema.sql + tests/contract/fixtures/contract-seed.sql
set -a && . build/admin-mysql/test.env && set +a
uv run pytest -m integration

# 3) 克隆库 before/after 对比（两套 schema 同 snapshot，分别打 Java / Python）
#    详见 tests/parity/README.md

# 4) 前端 consumer tests（不改 ui/）
cd ui && npx vitest run src/services/featuredConversationAdmin.test.ts \
  src/pages/Home/featuredConversationAdminModel.test.ts \
  src/pages/Home/FeaturedConversationAdminPanel.test.tsx

# 5) Java characterization（只看本类结果；app 基线本身红 —— R-02/R-18）
mvn -B -pl Reactor-agent-app -am -Dtest='FeaturedConversation*' -DskipTests=false \
  -Dsurefire.failIfNoSpecifiedTests=false test

# 6) 切流/回滚演练（backends 已起）
backend-python/tests/cutover/admin_drill.sh up
backend-python/tests/cutover/admin_drill.sh check pre
backend-python/tests/cutover/admin_drill.sh cutover
backend-python/tests/cutover/admin_drill.sh check on-python
backend-python/tests/cutover/admin_drill.sh rollback
backend-python/tests/cutover/admin_drill.sh check on-java

# 7) compose 语法
cd .. && MYSQL_PASSWORD=test-only MYSQL_ROOT_PASSWORD=test-only \
  REACTOR_PY_MYSQL_PASSWORD=test-only-ro docker compose config --quiet
```

## Validation and Acceptance

- 正常：create → 首次插入（OFFLINE）；update → 列更新且 `status/published_*` 保持；online/offline → 状态与 `published_at` 迁移；query-list → 过滤/分页/排序/字段序。
- 非法输入：create 空/空白 sessionId → 500 four-key；update 空 featuredId → 500 four-key；缺 `operator` → 400 four-key；缺 body / 非法 JSON → 400 four-key；`pageNo` 不可解析 → 400 four-key。
- 不存在：create 会话不存在 → 500 four-key；update featuredId 不存在 → 500 four-key；online/offline 行不存在 → 200 + `data:false`。
- 重复/唯一键：同 session 二次 create 走 ON DUPLICATE 更新且不改 `status/published_*`；两个 UNIQUE 键各自触发；未被吸收的冲突 → 500 four-key 且无部分写入。
- 事务回滚：单语句原子性（NOT NULL 违例不落行）；create 的多语句**非**单一事务（与 Java 一致），断言中途失败后各自可见性与 Java 相同。
- 幂等/并发：同值重复 upsert → Java/Python 同为 `data:true`（`FOUND_ROWS`）；并发 online/offline → 最终态一致、`published_at` 取最后写入者；并发同 session create → 一行且双方均返回 true。
- 缓存/registry 副作用：该域无缓存（已确证）；验收改为**写后公共读立即可见**（home/list/detail 三条已切流接口）。
- Java/Python 克隆库 before/after：同一 snapshot 两套 schema，同一请求序列，响应 + `ai_agent_featured_conversation` 全表等价（时间字段按允许的时钟差归一）。
- writer fence：`owner=java` 时写路由不触达 SQL；`reactor_py_ro` 账号下写语句 `ERROR 1142`。
- 切流/反向回滚均已演练并计时。

## Cutover and Rollback

见上文「Writer fence、部署顺序与回滚顺序」。开关是 `docker/nginx-featured-python.d/featured-admin.conf`（存在 = 切到 Python）。活跃 run 不受影响（本切片只动 admin 写路径，不碰 SSE 原子路由族）。数据核对：`SELECT id, featured_id, session_id, status, published_at, updated_at, deleted FROM ai_agent_featured_conversation ORDER BY id`。

## Idempotence and Recovery

- 迁移 SQL `CREATE USER IF NOT EXISTS` + 只 GRANT 不 REVOKE，可重复执行且不扩大权限；口令缺失/不合规时以缺失表名 fail loud。
- create 对同一 session 天然幂等（ON DUPLICATE）；update/online/offline 重放安全（无累积副作用）。
- 失败一半：create 的会话存在性检查与 upsert 是独立语句；检查失败不写库，upsert 失败不写行（单语句原子）。无跨语句补偿需求（与 Java 一致）。
- 中断后判断：查 `ai_agent_featured_conversation` 的目标行 + `updated_at`；重放同一请求序列安全。

## Interfaces and Dependencies

- `domain/featured_admin.py`：纯函数/值对象，无 I/O。
- `application/featured_conversation_admin.py`：端口 `FeaturedConversationAdminStore`（读写）、`SessionExistenceChecker`、`WriteOwnerFence`。
- `infrastructure/`：实现端口；SQL 只在此层。无新增生产依赖（`asyncmy`/`sqlalchemy` 已有）。
- 新增配置：`REACTOR_PY_FEATURED_ADMIN_WRITE_OWNER`（默认 `java`）。
- 新增账号：`reactor_py_featured_writer`（`SELECT` 全库 + `INSERT, UPDATE` 仅 `ai_agent_featured_conversation`）。

## Artifacts and Evidence

- 契约报告：`build/contract-report-featured-admin.json`
- 克隆库对比：`build/parity-featured-admin.json`
- 切流演练：`build/cutover-drill-admin/`（timing + 相位 diff）
- 迁移 SQL：`db/migrations/20260923_provision_phase4_featured_writer_account.sql`
- Nginx 片段：`docker/nginx-featured-python.d/featured-admin.conf`
