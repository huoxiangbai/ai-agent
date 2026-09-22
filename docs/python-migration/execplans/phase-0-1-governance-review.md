# 阶段 0/1 治理与共存基线复核

本 ExecPlan 遵循 `docs/python-migration/PLANS.md`，执行期间必须保持自包含并持续更新。

## Purpose / Big Picture

在正式接手工作区里现有未提交的迁移成果（`backend-python/`、`.github/`、POM 与 docker-compose 修改）之前，把迁移治理文档与真实代码对齐一次。成功可直接观察为：`inventory.md` / `risk-register.md` / `database-ownership.md` / `progress.md` 的每一条陈述都能在代码里找到对应物；每条公共能力都写明迁移阶段、验证方法和回滚所有者；Ruff / strict mypy / 非 integration 单测有真实通过输出；MySQL integration 与 Compose smoke 有可重复命令；并附带缺口列表与下一切片建议。本切片**不实现任何业务路由**，因此用户看不到新的产品行为——看到的是"文档不再说谎"。

## Scope

**包含：** 迁移与治理文档（`docs/python-migration/*.md`、根 `AGENTS.md`、根 `README.md` 的部署段）、新建本 ExecPlan、测试治理命令的补齐与实测、`docs/python-migration/execplans/` 目录创建。

**不包含：** 业务路由、Nginx 切流、React UI、`reactor-tool`、`reactor-sandbox`、`runtime/skills`、数据库 schema、`backend-python/` 骨架重构、任何 Java/Python 应用层双写、付费/live provider 调用、凭证读取或打印。

**工作区用户资产（禁止触碰）：** `M` `Reactor-agent-app/pom.xml`、`Reactor-agent-domain/pom.xml`、`docker-compose.yml`、`pom.xml`、`reactor-tool/uv.lock`；`??` `.github/`、`.workbuddy/`、`INTERVIEW_STUDY_GUIDE.md`、`backend-python/`。

## Progress

- [x] (2026-09-22) 完成 Java HTTP/SSE 面逐项核对：20 controller / 108 方法路由 / 6 个声明 SSE 媒体类型（5 条真流）/ 33 张表，与文档基数一致。
- [x] (2026-09-22) 完成 backend-python 与数据库侧核对：33 表名称级一一对应；Python 零 DML；无双写路径。
- [x] (2026-09-22) 修复 `inventory.md`：SSE 双口径、`/web` 任意方法、`DEBUG` 事件类型、`/1/web/...` 遗留路径、handler 方法名碰撞、访客 Cookie 保护两栏、29+1 mapper 口径、幻影 UI 路由、运行时/外部系统治理列、CORS/无 ControllerAdvice/Python 配置事实。
- [x] (2026-09-22) 修复 `api-contracts.md`：method-unrestricted、`DEBUG`、受保护/不受保护路径、Python 信封映射、**explicitly deferred 登记表**。
- [x] (2026-09-22) 修复 `database-ownership.md`：操作粒度所有权、`sales_data` 无应用写入者、跨表 mapper、撤销 Alembic 虚假声明、只读账号护栏缺口。
- [x] (2026-09-22) 修复 `risk-register.md`：R-01/R-14 改为"工作树已修、未提交"、新增 R-17~R-24、落地四类事项分类、关闭 blocker 2。
- [x] (2026-09-22) 修复 `progress.md`：单测数定为 15、Phase 0 重核证据、Phase 2 出口对齐、新增 2026-09-22 核对日志。
- [x] (2026-09-22) 对齐 `AGENTS.md`（Alembic、`TEST_MYSQL_URL`、真 Compose smoke）、`codex-migration-guide.md`（原子族整族口径、SSE/mapper 口径、GET 阶段定案）、`README.md`（补 Python 服务）。
- [x] (2026-09-22) 实测 Python 门禁：Ruff 通过、mypy 29 文件无问题、pytest **15 passed / 1 deselected**。
- [x] (2026-09-22) 产出 108 条路由 × 33 张表 × 10 项运行时能力 × 9 项外部系统的治理矩阵（见文末附录）。
- [x] (2026-09-22) 实跑 Java 稳定基线：`mvn -B -pl Reactor-agent-case -am -DskipTests=false test` → **BUILD SUCCESS**，domain 178 tests 全过、case 2 tests 全过。并发现该门禁不编译 `trigger`/`infrastructure`（登记为 R-25）。
- [x] (2026-09-22) 残留旧口径全库扫描通过（"30 XML mappers"、"6 passed"、phase-3 read 归属均只剩"已更正"说明文字）。
- [x] (2026-09-22) `staged-prompts.md` 核对后**无需修改**（第 97 行本已正确；P3 只读账号与 R-22 一致；原子族表述为子集事实而非排除整族）。
- [x] (2026-09-22) `git diff` 自审通过：改动仅限迁移/治理文档与本 ExecPlan。
- [ ] MySQL integration 实跑（需专用测试库；命令已登记）。
- [ ] Compose smoke 实跑（需 tool-stack env 与镜像构建；命令已登记）。

## Surprises & Discoveries

- Observation: `/web/health` 被计为 SSE，但它返回单次普通 `ok` 响应体，不是事件流。
  Evidence: `Reactor-agent-trigger/.../AiAgentController.java:48-51`；`inventory.md` 原 57-59 行。
- Observation: `/web` 两个 handler 是 `@RequestMapping` 无 `method` 属性，接受任意 HTTP 方法；文档写 `GET/REQUEST`、`POST/REQUEST` 具误导性。
  Evidence: `AiAgentController.java:48,:61`。
- Observation: `EventTypeEnum` 有 5 个事件类型，文档只列 4 个，漏 `DEBUG`；且 `ChatDataMessage.ofStatus` 允许自由字符串。
  Evidence: `EventTypeEnum.java:12-24`、`ChatDataMessage.java:54`。
- Observation: `VisitorIdentityFilter` 匹配 `/1/web/api/v1/gpt/queryAgentStreamIncr`，但无任何 controller 映射 `/1/` → 走过滤器后 404，仍可能发 `Set-Cookie`。
  Evidence: `VisitorIdentityFilter.java:38`。
- Observation: `POST /data/queryModelInfo` 的 handler 方法名也叫 `vectorRecall`，与真实 `/data/vectorRecall` 重载。
  Evidence: `DataAgentController.java:44-45` vs `:50`。
- Observation: `/api/agent/session/{id}/capabilities` GET **不受** `VisitorIdentityFilter` 保护，且 `SessionCapabilityService.capabilities` 是纯读（写只在 `setEnabled` → `repository.upsert`）。它离开 P3 是保守归组，不是身份写入要求。
  Evidence: `VisitorIdentityFilter.java:37-49`、`SessionCapabilityService.java:35,74-82`。
- Observation: **108/108 路由无迁移 owner、0/108 无回滚所有者、仅 7/108 有验证用例**，而 `progress.md` 把 Phase 0 标为 "all discovered surfaces assigned"。
  Evidence: 四份事实文档通读；`codex-migration-guide.md:116` P0 出口条件。
- Observation: 四类事项分类（blocking / 基线债务 / live-paid / 未覆盖）是阶段 0/1 的硬约束，但从未在任何文档落地。
  Evidence: `staged-prompts.md:51` vs 全文档检索为空。
- Observation: `AGENTS.md:57` 与 `database-ownership.md:54` 声称 schema 变更用 Alembic，但仓库无 `alembic.ini`、无 `alembic/`、无依赖；真实实践是 `db/migrations/*.sql`。
  Evidence: 文件系统检索 + `backend-python/pyproject.toml:7-28`。
- Observation: `java-baseline.yml` 只 gate `Reactor-agent-case -am`（不含 app），app 套件在 `continue-on-error: true` 的 job 里 → 65 个已知失败永不阻塞，**`Reactor-agent-app` 新增回归也永不阻塞**。
  Evidence: `.github/workflows/java-baseline.yml:26,:30`。
- Observation: `.gitignore` 排除 `application-test.yml` 与两个生产 Java 源码目录 → 干净检出既无法复现 65 失败基线，也无法完整构建。
  Evidence: `.gitignore`。
- Observation: 15 个 live/外部测试类的 surefire 排除来自 commit `4bda2a39c`（2026-04），**早于迁移文档**，不是迁移期扩大 ignore；但它就是藏在构建配置里的 live/paid 分类，而 `risk-register.md` 仍写"待分类"。
  Evidence: `Reactor-agent-app/pom.xml:181-198`、`git blame`。
- Observation: Compose "smoke" 命令其实是 `docker compose config --quiet`（YAML 校验），不是冒烟；`tests/contract/README.md` 引用的 `fake-agent-request.json` 与 `golden/` 目录不存在。
  Evidence: `AGENTS.md` 原验证段、`tests/contract/README.md:18-19,26-28`。
- Observation: `ai_agent_artifact` 与 `ai_agent_tool_output_image_generation` 各有**两个写入者**（phase-6 上传/生成路由 + phase-7 run 内工具），按表粒度登记所有权必然冲突，必须按操作粒度。
  Evidence: `database-ownership.md` 原 29、33 行 vs `inventory.md` 原 40、42 行。
- Observation: 实测 pytest 为 **15 passed**，证实 `progress.md:69` 的 "6 passed" 过期、`:40` 的 15 正确。
  Evidence: 本次 `uv run pytest -m "not integration"` 输出。
- Observation: 文档里的 Java「稳定基线」命令 `mvn -B -pl Reactor-agent-case -am` 只构建 5 个模块（parent/api/types/domain/case），**不编译 `Reactor-agent-trigger`（全部 108 条路由）与 `Reactor-agent-infrastructure`（全部 mapper）**——它们不是 `case` 的依赖。HTTP 层的编译/类型错误对阻塞门禁完全不可见。
  Evidence: 本次完整 Maven 输出的 Reactor Summary（5 个模块）；`Reactor-agent-trigger`/`infrastructure` 未出现在构建列表。
- Observation: `Reactor-agent-domain` 178 tests 全过（与 2026-09-18 记录一致），`PlanApprovalResumeApplicationServiceTest` 已通过（2026-09-18 曾失败，Logback ABI 修复后）。
  Evidence: 本次 `Tests run: 178, Failures: 0, Errors: 0, Skipped: 0`。
- Observation: 第一次跑 Java 基线时我用 `tail -40` 截断了输出，导致 domain 的 test summary 丢失、差点误判为"未跑测试"。重跑保存完整输出后才拿到真实计数。
  Evidence: 前后两次 Maven 输出对比。

## Decision Log

- Decision: visitor / conversation session / capability 三组 GET 全部归 **P4 身份写**，P3 只保留 public featured 三条纯读 GET。
  Rationale: 与 `AGENTS.md`「访客 GET 有写副作用、必须先给 `ai_agent_visitor_identity` 的 resolve/create/refresh 分配唯一写入者」这一权威规则一致，也与 `codex-migration-guide.md`、`staged-prompts.md` 一致。补充：capability GET 实为纯读且不受过滤器保护，离开 P3 属保守归组，已在 `codex-migration-guide.md` 标注可另行论证提级。
  Date/Author: 2026-09-22 / 用户确认后由本次执行者落地。
- Decision: CI 隐藏失败通道（app 新增回归不阻塞）**只登记为已知盲区 + 风险**，不动 workflow。
  Rationale: 在 `application-test.yml` 被 gitignore 的前提下让 app 阻塞会永久红，等于毁掉 CI；而基线快照门禁属于行为变更，应另立任务。先如实登记（R-17）保住可见性。
  Date/Author: 2026-09-22 / 用户确认后由本次执行者落地。
- Decision: 治理文档全范围对齐，**包含**根 `AGENTS.md`、`codex-migration-guide.md`、`staged-prompts.md`。
  Rationale: 它们是同一套迁移治理，留着互相矛盾就达不到「文档与代码一致」的 Done when。仍不碰业务代码、UI、schema。
  Date/Author: 2026-09-22 / 用户确认后由本次执行者落地。
- Decision: "6 SSE" 采用**双口径并列**（声明媒体类型 6 / 真实流 5），不擅自改清单基数。
  Rationale: 基数变更需用户批准；双口径让 content-type 审计与流语义审计都可对账。
  Date/Author: 2026-09-22 / 本次执行者。
- Decision: `ai_agent_artifact`、`ai_agent_tool_output_image_generation` 的写所有权按**操作粒度**登记。
  Rationale: 两表各有两个写入者（phase-6 路由 + phase-7 run 内工具）；`AGENTS.md:54` 本就要求"记录到操作粒度的所有权"。按表粒度会人为制造矛盾。
  Date/Author: 2026-09-22 / 本次执行者。
- Decision: 原子族范围统一为 `AGENTS.md` 的**整族**口径（`/api/agent/ask-user/*`、`/api/agent/plan-approval/*` 全部），而非 `codex-migration-guide.md` 的"与活跃 run 相关的操作"子集。
  Rationale: `/pending`、`/cancel` 同样依赖同一个 pending registry 与 run owner；整族口径更保守、切流更安全。已回改 `codex-migration-guide.md`。
  Date/Author: 2026-09-22 / 本次执行者。
- Decision: 回滚所有者统一登记为角色 **cutover owner**（原子族为 cutover owner (whole family)），不虚构人名。
  Rationale: 仓库无具名 on-call 体系；角色是当前能达到的最细真实粒度。若后续有具名值班表，应替换为具体所有者。
  Date/Author: 2026-09-22 / 本次执行者。
- Decision: Compose smoke 以**文档化命令序列**落地，不新建 `scripts/`。
  Rationale: 满足"有可运行命令"的 Done when，同时避免引入新基础设施。若需要脚本可另行要求。
  Date/Author: 2026-09-22 / 本次执行者。

## Outcomes & Retrospective

已达成：四份事实文档 + 三份治理文档 + README 部署段与代码一致；108 路由 / 33 表 / 10 运行时能力 / 9 外部系统**每一项**都有迁移阶段、验证方法、回滚所有者；四类事项分类章节落地且关闭了 blocker 2；Python 门禁实测通过（15 passed）；MySQL integration 与 Compose smoke 有可重复命令；`execplans/` 从零建立。

与初始目标的差异：MySQL integration 与 Compose smoke **只有命令、未实跑**（分别缺专用测试库、tool-stack env 与镜像构建），Progress 里保持未勾选，不冒充通过。Java 稳定基线已实跑，但暴露出比预期更大的缺口（R-25：HTTP 层不在门禁内），已从"验证项"转为"新增风险"。

下一切片需继承的经验：(1) 基数口径冲突（6 vs 5、15 vs 6、30 vs 29）一律先实测再改文档，不要在两份文档之间"选一个看起来对的"；(2) 表级写所有权在多写入者场景下必须拆到操作粒度，否则阶段标注必然自相矛盾；(3) `continue-on-error` 类豁免必须写清边界，否则会与"禁止把红色测试标成非阻塞"正面冲突；(4) 文档声称的工具（Alembic）要验存在性，不能只看文字。

## Context and Orientation

Java 参考实现的 HTTP 面全部在 `Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/`（20 个 `@RestController`，108 个 handler）。过滤器链在 `.../config/BaseFilterConfig.java`：`CorsFilter` order 1 + `VisitorIdentityFilter` order 2。数据访问是 MyBatis Plus（非 JPA），mapper 在 `Reactor-agent-app/src/main/resources/mybatis/mapper/`（29 个 XML + 1 个 config），权威 schema 在 `Reactor-agent-app/src/main/resources/db/schema.sql`（33 张表）。

Python 目标是现有 `backend-python/src/reactor_backend/`，包边界 `api → application → domain/runtime 抽象 ← infrastructure`。今日只有 `api/routers/health.py` 两条健康路由与 `contracts/` 迁移期比较工具，无业务路由。入口 `src/reactor_backend/main.py`（`create_app()`）。

前端消费者在 `ui/src/services/*.ts`，通过 nginx `docker/nginx.conf` 的 `/web/`、`/api/`、`/data/` 前缀打到 Java 8100，`/tool/` 打到 `reactor-tool:1601`。**nginx 无 Python upstream**，Python 仅直连 `${PYTHON_BACKEND_PORT:-8200}` 可达。

相关迁移文档：`AGENTS.md`（持久约束）、`docs/python-migration/codex-migration-guide.md`（总入口与阶段）、`PLANS.md`（本文件规范）、`staged-prompts.md`（阶段提示词）、`inventory.md`、`api-contracts.md`、`database-ownership.md`、`risk-register.md`、`progress.md`。

## Contract and Invariants

必须保持：公共路径与 HTTP 方法（含 `/web` 的 method-unrestricted 事实）、`{code, info, data}` 信封与 `0000/0001/0002/0003`、null/空集合/排序/分页、Cookie 属性、二进制响应头、SSE 事件顺序与终止语义、数据库事务与 CAS 语义。

禁止改变：SSE 原子族的同上游约束、访客 GET 的写副作用语义、ledger start/finish 分离写、Asia/Shanghai 时区行为、零行 CAS = 冲突/幂等重复的语义。

本切片额外不变量：**不改任何业务行为**；`git diff` 只允许出现迁移/治理文档。

## Plan of Work

1. 建 `docs/python-migration/execplans/` 并写本文件（活文档）。
2. `inventory.md`：SSE 双口径、任意方法、`DEBUG`、`/1/` 遗留路径、方法名碰撞、访客保护两栏、29+1 mapper、幻影路由、运行时/外部系统治理列、CORS/异常/Python 配置事实。
3. `api-contracts.md`：method-unrestricted、`DEBUG`、路径清单、Python 信封映射、explicitly deferred 登记表。
4. `database-ownership.md`：操作粒度所有权、`sales_data`、跨表 mapper、撤销 Alembic、只读账号护栏缺口。
5. `risk-register.md`：R-01/R-14 未提交状态、R-17~R-24、四类分类、blocker 变更。
6. `progress.md` + `AGENTS.md` + `codex-migration-guide.md` + `README.md` 对齐。
7. 生成治理矩阵（本文件附录）。
8. 实测 Python 门禁并登记命令；输出缺口列表与下一切片建议。

## Concrete Steps

```bash
cd /Users/cuimingkai/Documents/agent-2/ai-agent
git status --short

cd backend-python
uv sync --all-groups
uv run ruff check .                    # All checks passed!
uv run mypy src                        # Success: no issues found in 29 source files
uv run pytest -m "not integration"     # 15 passed, 1 deselected

# MySQL integration（需专用测试库，test-only 凭证）
# TEST_MYSQL_URL='mysql+asyncmy://user:pass@127.0.0.1:3306/test-db?charset=utf8mb4' \
#   uv run pytest -m integration

cd ..
MYSQL_PASSWORD=test-only MYSQL_ROOT_PASSWORD=test-only docker compose config --quiet

# Compose smoke（可重复）
# docker compose up -d
# curl -fsS http://127.0.0.1:8200/internal/health/live
# curl -fsS http://127.0.0.1:8200/internal/health/ready
# docker compose down

# Java 稳定基线
# mvn -B -pl Reactor-agent-case -am -DskipTests=false test

git diff
git status --short
```

## Validation and Acceptance

通过条件（外部可观察）：
1. 四份事实文档每条陈述可溯源到代码；20/108/6/33 逐项有结论。
2. 治理矩阵每行都有阶段 + 验证方法 + 回滚所有者；缺失项进缺口列表而非留空。
3. Ruff / strict mypy / 非 integration 单测通过并有真实输出；MySQL integration 与 Compose smoke 有可重复命令。
4. 四类分类落地；失败未隐藏；全局 ignore 未扩大。
5. 本文件四个段落填实；A1–A7、D1–D10、G1–G11 全部处置。
6. `git diff` 自审：无业务行为变更、无 schema 变更、无双写、无凭证、未触碰用户资产。

边界/错误场景：文档与代码冲突时以代码为准并记入 Decision Log；无法实跑的门禁必须写明原因、已有证据与剩余风险，不得标通过。

## Cutover and Rollback

无流量切换、无写所有权切换、无 schema 变更、无活跃 run 影响。

回滚：`git checkout -- docs/python-migration/ AGENTS.md README.md` 并删除 `docs/python-migration/execplans/`，或整段 revert 提交。回滚所有者：本切片执行者（角色 cutover owner）。回滚不影响任何运行中服务或数据库状态。

## Idempotence and Recovery

本切片全部是文档编辑 + 只读核对 + 本地门禁，可安全重跑。中断后判断状态：`git status --short` 看哪些文档已改；重跑 Concrete Steps 的门禁即可确认基线未变。半途失败不会留下不一致的数据或路由状态；重新执行 Plan of Work 的剩余步骤即可。

## Interfaces and Dependencies

无新增生产接口、无新增 port/adapter、无新增第三方依赖。命中的既有接口：Python `/internal/health/live|ready`（读）、`reactor-contract` / `reactor-sse-contract` CLI（仅命令登记，本切片未调用）、MySQL `SELECT 1` ping。不依赖任何付费或 live provider。

## Artifacts and Evidence

- 本次门禁输出：Ruff `All checks passed!`；mypy `Success: no issues found in 29 source files`；pytest `15 passed, 1 deselected, 2 warnings in 0.66s`。
- Java 稳定基线输出：`BUILD SUCCESS`；`Reactor-agent-domain` `Tests run: 178, Failures: 0, Errors: 0, Skipped: 0`；`Reactor-agent-case` `Tests run: 2, Failures: 0, Errors: 0, Skipped: 0`；Reactor Summary 仅 5 个模块（parent/api/types/domain/case）。
- 计数证据：20 controller / 108 handler / 6 声明 SSE / 5 真流 / 33 表 / 29+1 mapper，核对方法见 `progress.md` 的 2026-09-22 日志。
- 已修改文件见最终报告；`git diff` 自审通过。
- 未产出契约报告（本切片不跑 `reactor-contract`，P2 范围）。

---

## Appendix — Capability governance matrix

Owner roles are the finest real granularity available (no named on-call roster exists in the repo). `cutover owner` = whoever executes the cutover/rollback task defined in the slice ExecPlan; for the SSE atomic family the whole family shares one cutover owner and one upstream. Verification values: `case:<id>` = covered by a contract case; `deferred:<phase>` = listed in the `api-contracts.md` deferred registry and blocking at that phase.

### HTTP routes (108)

| # | Method + path | Phase | Owner | Verification | Rollback owner |
|---|---|---|---|---|---|
| 1 | `ANY /web/health` | 0/1 | infra | live/ready probe | n/a |
| 2 | `ANY /web/api/v1/gpt/queryAgentStreamIncr` | 5, 7 | agent-runtime | deferred:5/7 | cutover owner (family) |
| 3 | `GET /api/agent/visitor/bootstrap` | 4 | identity | case:visitor-bootstrap | cutover owner |
| 4 | `POST /api/agent/visitor/naming` | 4 | identity | deferred:4 | cutover owner |
| 5 | `GET /api/agent/conversation/sessions` | 4 | identity + ledger | case:conversation-list | cutover owner |
| 6 | `GET /api/agent/conversation/sessions/{sessionId}` | 4 | identity + ledger | case:conversation-detail | cutover owner |
| 7 | `GET /api/agent/featured-conversations/home` | 3 | featured-read | case:featured-home | cutover owner |
| 8 | `GET /api/agent/featured-conversations` | 3 | featured-read | case:featured-list | cutover owner |
| 9 | `GET /api/agent/featured-conversations/{featuredId}` | 3 | featured-read | case:featured-detail | cutover owner |
| 10 | `GET /api/agent/session/{sessionId}/capabilities` | 4 | capability | case:capability-get | cutover owner |
| 11 | `PUT /api/agent/session/{sessionId}/capabilities` | 4 | capability | deferred:4 | cutover owner |
| 12 | `POST /api/agent/run/stop` | 5 | run-control | deferred:5 | cutover owner (family) |
| 13 | `POST /api/agent/run/inject` | 5 | run-control | deferred:5 | cutover owner (family) |
| 14 | `POST /api/agent/run/follow` | 5 | run-control | deferred:5 | cutover owner (family) |
| 15 | `POST /api/agent/ask-user/answer` | 8 | hitl-ask-user | deferred:8 | cutover owner (family) |
| 16 | `POST /api/agent/ask-user/resume` | 8 (P5 family) | hitl-ask-user | deferred:8 | cutover owner (family) |
| 17 | `GET /api/agent/ask-user/pending` | 8 | hitl-ask-user | deferred:8 | cutover owner (family) |
| 18 | `POST /api/agent/ask-user/cancel` | 8 | hitl-ask-user | deferred:8 | cutover owner (family) |
| 19 | `POST /api/agent/plan-approval/approve` | 8 | hitl-plan-approval | deferred:8 | cutover owner (family) |
| 20 | `POST /api/agent/plan-approval/reject` | 8 | hitl-plan-approval | deferred:8 | cutover owner (family) |
| 21 | `POST /api/agent/plan-approval/resume` | 8 (P5 family) | hitl-plan-approval | deferred:8 | cutover owner (family) |
| 22 | `GET /api/agent/plan-approval/pending` | 8 | hitl-plan-approval | deferred:8 | cutover owner (family) |
| 23 | `POST /api/agent/plan-approval/cancel` | 8 | hitl-plan-approval | deferred:8 | cutover owner (family) |
| 24 | `POST /api/agent/file/upload` | 6 | file-workspace | deferred:6 | cutover owner |
| 25 | `GET /api/agent/workspace/{sessionId}/archive` | 6 | file-workspace | deferred:6 | cutover owner |
| 26 | `POST /api/agent/image-generation/generate` | 6 | image-generation | deferred:6 | cutover owner |
| 27 | `GET /api/agent/image-generation/history` | 6 | image-generation | deferred:6 | cutover owner |
| 28 | `POST /api/agent/genui/export/pdf` | 6 | genui-export | deferred:6 | cutover owner |
| 29 | `POST /api/agent/genui/export/docx` | 6 | genui-export | deferred:6 | cutover owner |
| 30 | `POST /api/v1/admin/featured-conversations/create` | 4 | featured-admin | deferred:4 | cutover owner |
| 31 | `PUT /api/v1/admin/featured-conversations/update` | 4 | featured-admin | deferred:4 | cutover owner |
| 32 | `POST /api/v1/admin/featured-conversations/online/{featuredId}` | 4 | featured-admin | deferred:4 | cutover owner |
| 33 | `POST /api/v1/admin/featured-conversations/offline/{featuredId}` | 4 | featured-admin | deferred:4 | cutover owner |
| 34 | `POST /api/v1/admin/featured-conversations/query-list` | 3 | featured-admin | deferred:4 | cutover owner |
| 35 | `POST /api/v1/admin/ai-client-api/create` | 4 | ai-client-admin | deferred:4 | cutover owner |
| 36 | `PUT /api/v1/admin/ai-client-api/update-by-id` | 4 | ai-client-admin | deferred:4 | cutover owner |
| 37 | `PUT /api/v1/admin/ai-client-api/update-by-api-id` | 4 | ai-client-admin | deferred:4 | cutover owner |
| 38 | `DELETE /api/v1/admin/ai-client-api/delete-by-id/{id}` | 4 | ai-client-admin | deferred:4 | cutover owner |
| 39 | `DELETE /api/v1/admin/ai-client-api/delete-by-api-id/{apiId}` | 4 | ai-client-admin | deferred:4 | cutover owner |
| 40 | `GET /api/v1/admin/ai-client-api/query-by-id/{id}` | 3 | ai-client-admin | deferred:4 | cutover owner |
| 41 | `GET /api/v1/admin/ai-client-api/query-by-api-id/{apiId}` | 3 | ai-client-admin | deferred:4 | cutover owner |
| 42 | `GET /api/v1/admin/ai-client-api/query-enabled` | 3 | ai-client-admin | deferred:4 | cutover owner |
| 43 | `POST /api/v1/admin/ai-client-api/query-list` | 3 | ai-client-admin | deferred:4 | cutover owner |
| 44 | `GET /api/v1/admin/ai-client-api/query-all` | 3 | ai-client-admin | deferred:4 | cutover owner |
| 45 | `POST /api/v1/admin/ai-client-model/test/{modelId}` | 4 | ai-client-admin | deferred:4 (**live/manual**) | cutover owner |
| 46 | `POST /api/v1/admin/ai-client-model/test-by-id/{id}` | 4 | ai-client-admin | deferred:4 (**live/manual**) | cutover owner |
| 47 | `POST /api/v1/admin/ai-client-model/create` | 4 | ai-client-admin | deferred:4 | cutover owner |
| 48 | `PUT /api/v1/admin/ai-client-model/update-by-id` | 4 | ai-client-admin | deferred:4 | cutover owner |
| 49 | `PUT /api/v1/admin/ai-client-model/update-by-model-id` | 4 | ai-client-admin | deferred:4 | cutover owner |
| 50 | `DELETE /api/v1/admin/ai-client-model/delete-by-id/{id}` | 4 | ai-client-admin | deferred:4 | cutover owner |
| 51 | `DELETE /api/v1/admin/ai-client-model/delete-by-model-id/{modelId}` | 4 | ai-client-admin | deferred:4 | cutover owner |
| 52 | `GET /api/v1/admin/ai-client-model/query-by-id/{id}` | 3 | ai-client-admin | deferred:4 | cutover owner |
| 53 | `GET /api/v1/admin/ai-client-model/query-by-model-id/{modelId}` | 3 | ai-client-admin | deferred:4 | cutover owner |
| 54 | `GET /api/v1/admin/ai-client-model/query-by-api-id/{apiId}` | 3 | ai-client-admin | deferred:4 | cutover owner |
| 55 | `GET /api/v1/admin/ai-client-model/query-by-model-type/{modelType}` | 3 | ai-client-admin | deferred:4 | cutover owner |
| 56 | `GET /api/v1/admin/ai-client-model/query-enabled` | 3 | ai-client-admin | deferred:4 | cutover owner |
| 57 | `POST /api/v1/admin/ai-client-model/query-list` | 3 | ai-client-admin | deferred:4 | cutover owner |
| 58 | `GET /api/v1/admin/ai-client-model/query-all` | 3 | ai-client-admin | deferred:4 | cutover owner |
| 59 | `POST /api/v1/admin/ai-client-tool-mcp/create` | 4 | mcp-admin | deferred:4 | cutover owner |
| 60 | `PUT /api/v1/admin/ai-client-tool-mcp/update-by-id` | 4 | mcp-admin | deferred:4 | cutover owner |
| 61 | `PUT /api/v1/admin/ai-client-tool-mcp/update-by-mcp-id` | 4 | mcp-admin | deferred:4 | cutover owner |
| 62 | `DELETE /api/v1/admin/ai-client-tool-mcp/delete-by-id/{id}` | 4 | mcp-admin | deferred:4 | cutover owner |
| 63 | `DELETE /api/v1/admin/ai-client-tool-mcp/delete-by-mcp-id/{mcpId}` | 4 | mcp-admin | deferred:4 | cutover owner |
| 64 | `GET /api/v1/admin/ai-client-tool-mcp/query-by-id/{id}` | 3 | mcp-admin | deferred:4 | cutover owner |
| 65 | `GET /api/v1/admin/ai-client-tool-mcp/query-by-mcp-id/{mcpId}` | 3 | mcp-admin | deferred:4 | cutover owner |
| 66 | `GET /api/v1/admin/ai-client-tool-mcp/query-all` | 3 | mcp-admin | deferred:4 | cutover owner |
| 67 | `GET /api/v1/admin/ai-client-tool-mcp/query-by-status/{status}` | 3 | mcp-admin | deferred:4 | cutover owner |
| 68 | `GET /api/v1/admin/ai-client-tool-mcp/query-by-transport-type/{transportType}` | 3 | mcp-admin | deferred:4 | cutover owner |
| 69 | `GET /api/v1/admin/ai-client-tool-mcp/query-enabled` | 3 | mcp-admin | deferred:4 | cutover owner |
| 70 | `POST /api/v1/admin/ai-client-tool-mcp/query-list` | 3 | mcp-admin | deferred:4 | cutover owner |
| 71 | `POST /api/v1/admin/admin-user/create` | 4 | admin-user | deferred:4 | cutover owner |
| 72 | `PUT /api/v1/admin/admin-user/update-by-id` | 4 | admin-user | deferred:4 | cutover owner |
| 73 | `PUT /api/v1/admin/admin-user/update-by-user-id` | 4 | admin-user | deferred:4 | cutover owner |
| 74 | `DELETE /api/v1/admin/admin-user/delete-by-id/{id}` | 4 | admin-user | deferred:4 | cutover owner |
| 75 | `DELETE /api/v1/admin/admin-user/delete-by-user-id/{userId}` | 4 | admin-user | deferred:4 | cutover owner |
| 76 | `GET /api/v1/admin/admin-user/query-by-id/{id}` | 3 | admin-user | deferred:4 | cutover owner |
| 77 | `GET /api/v1/admin/admin-user/query-by-user-id/{userId}` | 3 | admin-user | deferred:4 | cutover owner |
| 78 | `GET /api/v1/admin/admin-user/query-by-username/{username}` | 3 | admin-user | deferred:4 | cutover owner |
| 79 | `GET /api/v1/admin/admin-user/query-enabled` | 3 | admin-user | deferred:4 | cutover owner |
| 80 | `GET /api/v1/admin/admin-user/query-by-status/{status}` | 3 | admin-user | deferred:4 | cutover owner |
| 81 | `POST /api/v1/admin/admin-user/query-list` | 3 | admin-user | deferred:4 | cutover owner |
| 82 | `GET /api/v1/admin/admin-user/query-all` | 3 | admin-user | deferred:4 | cutover owner |
| 83 | `POST /api/v1/admin/admin-user/login` | 4 | admin-user | deferred:4 | cutover owner |
| 84 | `POST /api/v1/admin/admin-user/validate-login` | 4 | admin-user | deferred:4 | cutover owner |
| 85 | `GET /api/v1/admin/skills/list` | 6 | skill-admin | deferred:6 | cutover owner |
| 86 | `POST /api/v1/admin/skills/parse-package` | 6 | skill-admin | deferred:6 | cutover owner |
| 87 | `POST /api/v1/admin/skills/upload` | 6 | skill-admin | deferred:6 | cutover owner |
| 88 | `POST /api/v1/admin/skills/create` | 6 | skill-admin | deferred:6 | cutover owner |
| 89 | `POST /api/v1/admin/skills/import-url` | 6 | skill-admin | deferred:6 | cutover owner |
| 90 | `DELETE /api/v1/admin/skills/{name}` | 6 | skill-admin | deferred:6 | cutover owner |
| 91 | `POST /api/v1/admin/skills/reload` | 6 | skill-admin | deferred:6 | cutover owner |
| 92 | `GET /api/v1/admin/sub-agent-definitions/query-list` | 8 | sub-agent-admin | deferred:8 | cutover owner |
| 93 | `GET /api/v1/admin/sub-agent-definitions/tool-catalog` | 8 | sub-agent-admin | deferred:8 | cutover owner |
| 94 | `GET /api/v1/admin/sub-agent-definitions/{agentKey}` | 8 | sub-agent-admin | deferred:8 | cutover owner |
| 95 | `POST /api/v1/admin/sub-agent-definitions/create` | 8 | sub-agent-admin | deferred:8 | cutover owner |
| 96 | `PUT /api/v1/admin/sub-agent-definitions/update` | 8 | sub-agent-admin | deferred:8 | cutover owner |
| 97 | `DELETE /api/v1/admin/sub-agent-definitions/{agentKey}` | 8 | sub-agent-admin | deferred:8 | cutover owner |
| 98 | `DELETE /api/v1/admin/sub-agent-definitions/delete` | 8 | sub-agent-admin | deferred:8 | cutover owner |
| 99 | `POST /api/v1/admin/sub-agent-definitions/reload` | 8 | sub-agent-admin | deferred:8 | cutover owner |
| 100 | `POST /data/queryModelInfo` | 8 | data-agent | deferred:8 | cutover owner |
| 101 | `POST /data/vectorRecall` | 8 | data-agent | deferred:8 | cutover owner |
| 102 | `POST /data/esRecall` | 8 | data-agent | deferred:8 | cutover owner |
| 103 | `POST /data/chatQuery` | 8 | data-agent | deferred:8 (SSE shape documented) | cutover owner |
| 104 | `POST /data/apiChatQuery` | 8 | data-agent | deferred:8 | cutover owner |
| 105 | `POST /data/testQuery` | 8 | data-agent | deferred:8 | cutover owner |
| 106 | `POST /data/getNl2SqlReq` | 8 | data-agent | deferred:8 | cutover owner |
| 107 | `GET /data/allModels` | 8 | data-agent | deferred:8 | cutover owner |
| 108 | `GET /data/previewData` | 8 | data-agent | deferred:8 | cutover owner |

Plus three frontend-only phantom calls with no Java implementation — `GET? /web/api/login`, `GET? /web/api/getWhiteList`, `GET? /web/api/reactor/apply` (`ui/src/services/agent.ts:4-6`). Phase: **open / pending determination**. Owner: ui-consumer (out of migration scope). Verification: none (uncovered). Rollback owner: n/a.

### Tables (33)

Ownership is operation-granular where a table has two writers. All rows: rollback owner = cutover owner.

| Table | Phase | Owner | Verification |
|---|---|---|---|
| `admin_user` | 4 | admin-user | cloned-DB parity (deferred:4) |
| `ai_client_api` | 4 | ai-client-admin | cloned-DB parity (deferred:4) |
| `ai_client_model` | 4 | ai-client-admin | cloned-DB parity + cache invalidation (deferred:4) |
| `ai_client_tool_mcp` | 4 | mcp-admin | cloned-DB parity + registry reload (deferred:4) |
| `ai_agent_session_capability` | 4 | capability | cloned-DB parity (deferred:4) |
| `ai_agent_sub_agent_definition` | 8 | sub-agent-admin | soft delete + registry reload (deferred:8) |
| `chat_model_info` | 8 | data-agent | atomic model+schema rebuild (deferred:8) |
| `chat_model_schema` | 8 | data-agent | atomic model+schema rebuild (deferred:8) |
| `sales_data` | 8 (seed-only, no app writer) | data-agent (read) | fixture queries (deferred:8) |
| `ai_agent_visitor_identity` | 4 (resolve/create/refresh + naming) | identity | concurrency first-visit + cookie attrs (deferred:4) |
| `ai_agent_dialogue_run` | 7 | agent-runtime | start/finish lifecycle (deferred:7) |
| `ai_agent_dialogue_session` | reads 4 / writes 7 | identity + agent-runtime | upsert + visitor scope (deferred:7) |
| `ai_agent_llm_invocation` | 7 | agent-runtime | start/finish lifecycle (deferred:7) |
| `ai_agent_tool_invocation` | 7 | agent-runtime | start/finish lifecycle (deferred:7) |
| `ai_agent_user_question` | 8 | hitl-ask-user | CAS + yield transaction (deferred:8) |
| `ai_agent_plan_approval` | 8 | hitl-plan-approval | CAS + yield transaction (deferred:8) |
| `ai_agent_tool_output_deep_search` | 7 | agent-runtime | append keyed parity (deferred:7) |
| `ai_agent_tool_output_code_interpreter` | 7 | agent-runtime | append keyed parity (deferred:7) |
| `ai_agent_tool_output_data_analysis` | 7 | agent-runtime | append keyed parity (deferred:7) |
| `ai_agent_tool_output_multimodal_agent` | 7 | agent-runtime | append keyed parity (deferred:7) |
| `ai_agent_tool_output_image_generation` | **op-granular:** generate route 6 / in-run tool 7 | image-generation / agent-runtime | batch atomicity + pagination (deferred:6,7) |
| `ai_agent_tool_output_canvas_publish` | 7 | agent-runtime | append keyed parity (deferred:7) |
| `ai_agent_tool_output_emit_ui_tree` | 7 | agent-runtime | append keyed parity (deferred:7) |
| `ai_agent_tool_output_emit_ui_patch` | 7 | agent-runtime | append keyed parity (deferred:7) |
| `ai_agent_artifact` | **op-granular:** upload route 6 / in-run tool 7 | file-workspace / agent-runtime | batch insert + checksum (deferred:6,7) |
| `ai_agent_featured_conversation` | reads 3 / writes 4 | featured-read / featured-admin | public GET cases + cloned-DB parity (deferred:4) |
| `ai_agent_ltm_curated_entry` | 8 | memory | soft delete + active selection (deferred:8) |
| `ai_agent_working_memory_turn` | 8 | memory | ordered turn allocation (deferred:8) |
| `ai_agent_working_memory_message` | interim ledger-backed reads / full ownership 8 | memory | no-dup/no-loss + compaction (deferred:8) |
| `ai_agent_working_memory_compaction` | 8 | memory | append-only audit (deferred:8) |
| `ai_agent_ltm_fork_execution` | 8 | memory | append-only audit (deferred:8) |
| `ai_agent_session_todo` | 8 | background-work | sequence allocation + soft delete (deferred:8) |
| `ai_agent_background_task` | 8 | background-work | restart orphan recovery (deferred:8) |

Cross-table mappers `working_memory_message_mapper.xml` and `tool_invocation_ledger_mapper.xml` each span three tables (incl. `ai_agent_dialogue_session`, `ai_agent_dialogue_run`, `ai_agent_artifact`) — cloned-DB parity must diff all of them.

### Runtime capabilities (10) and external systems (9)

Recorded with phase / verification / rollback owner in `inventory.md` ("Runtime capabilities", "External systems"). Every verification is currently `deferred` except the health probe. Test mode for external systems is fake / sanitized recording / dedicated test DB / fixture, except `AiClientModel` `/test*` which is **live/manual only**.

## Gap list (open items)

1. **MySQL integration not run** — needs a dedicated test database and `TEST_MYSQL_URL`. Command registered in `AGENTS.md`.
2. **Compose smoke not run** — needs the `reactor-tool/.env` tool-stack file and image build. Command registered in `AGENTS.md`.
3. **Java stable baseline ran and passed** (domain 178 tests, case 2 tests) but the gate **never compiles `Reactor-agent-trigger` or `Reactor-agent-infrastructure`** (R-25) — the HTTP layer and all mappers have no compile protection.
4. **R-17 residual:** new `Reactor-agent-app` regressions cannot block CI (accepted blind spot).
5. **R-18/R-19:** `application-test.yml` and two production Java source directories are gitignored → clean checkout is neither reproducible nor complete.
6. **R-01/R-14 fixes are uncommitted** — the migration must not depend on a dirty tree.
7. **No read-only MySQL account** → the single-writer rule has no technical enforcement (R-22).
8. **Contract fixtures/goldens absent** — `tests/contract/fixtures/fake-agent-request.json`, `tests/contract/golden/`.
9. **CI coverage gaps** — no MySQL service container, no integration job, no docker build/compose job, no contract job, no UI vitest job (R-24).
10. **101 of 108 routes have no verification case** — all are explicitly deferred with an owner phase, but P2/P3 cannot claim coverage until they exist.
11. **Phantom UI routes** `/web/api/login|getWhiteList|reactor/apply` — pending determination (R-20).
12. **Legacy `/1/web/...` alias** — pending determination (R-21).
13. **No per-test inventory of the 65 Java baseline failures** — only categories; "retire deliberately" has no tracker.
14. **Rollback owner is a role, not a named person** — replace once a named on-call roster exists.
15. **R-25:** the blocking Java gate does not compile `Reactor-agent-trigger` (108 routes) or `Reactor-agent-infrastructure` (mappers).
16. **MySQL integration and Compose smoke commands are registered but unverified by execution** — treat them as unproven until run.

## Next minimal vertical slice

**Phase 2 — complete the contract lab** (use the phase-2 prompt in `staged-prompts.md`). Do not start bulk business routes.

Rationale: `codex-migration-guide.md` states P0/P1 are done and P2 must complete before business code. The gaps above (8, 10) are exactly P2's deliverables: real sanitized Java goldens from a deterministic fixture, an offline Python-vs-golden comparison path, the missing `fake-agent-request.json` SSE fixture, and the multipart/binary deferred items. Phase 3A (the three public featured GETs) remains the first business pilot but follows P2.
