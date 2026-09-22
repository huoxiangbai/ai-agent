# Reactor Java → Python ExecPlan 规范

本文件定义 Codex 在 Reactor 后端迁移中如何编写和执行长任务计划（ExecPlan）。迁移任务只要跨越多个模块、需要契约对比、涉及数据库写入、SSE 生命周期或需要分阶段切流，就必须先创建 ExecPlan，再实现代码。

ExecPlan 是可执行、可恢复的活文档，不是一次性待办列表。后续执行者应当只依赖当前工作树、仓库内文档和该 ExecPlan 就能继续工作，不应依赖聊天记录。

## 使用方式

1. 在 `docs/python-migration/execplans/` 下为一个垂直切片创建一个文件，例如 `featured-public-read.md`。
2. 开始前完整阅读：
   - `AGENTS.md`
   - `docs/python-migration/inventory.md`
   - `docs/python-migration/api-contracts.md`
   - `docs/python-migration/database-ownership.md`
   - `docs/python-migration/risk-register.md`
   - `docs/python-migration/progress.md`
   - 本文件
3. 先研究 Java 参考实现、前端消费者、SQL/表、现有测试和部署路由，再填写计划。
4. 实现过程中持续更新 `Progress`、`Surprises & Discoveries`、`Decision Log` 和 `Outcomes & Retrospective`。
5. 每个里程碑结束时运行该里程碑的验证命令，记录简短证据；不得把“代码已写完”当作完成。
6. 如果发现计划假设错误，先更新 ExecPlan 并说明理由，再调整实现。

## 强制要求

- 计划必须自包含，并写出准确的仓库相对路径、入口、命令、预期结果和失败后的恢复方法。
- 一个 ExecPlan 只覆盖一个可独立验收的垂直切片；不要按 Java module 做机械翻译。
- 迁移保持行为兼容。公共路径、HTTP 方法、状态码、`{code, info, data}`、null、排序、时间、Cookie、二进制响应和 SSE 语义都属于契约。
- 使用现有 `backend-python/` 作为唯一 Python 主后端；保留 React 前端、`reactor-tool`、`reactor-sandbox`、`runtime/skills` 和现有 MySQL schema，除非任务明确改变范围。
- 不允许 Java/Python 应用层双写。写切片必须明确唯一 writer、切换顺序、所有受影响表和回滚顺序。
- 受 `VisitorIdentityFilter` 保护的 GET 不是天然只读：有效 Cookie 会更新 `last_seen`，缺少 Cookie 会创建访客。
- 主 Agent 与控制面是同一个运行时所有权单元。`queryAgentStreamIncr`、`stop`、`inject`、`follow`、Ask User/Plan Approval 的 resume 不能随机拆到不同上游。
- 外部模型、图片、搜索和 MCP 自动测试默认使用本地 fake 或净化录制；普通 CI 不得调用付费服务或读取生产凭证。
- 在开始和结束时检查 `git status --short`。不得 reset、checkout、覆盖或清理与本计划无关的用户改动。
- 优先做增量、可重复执行、可单独回滚的变更；删除 Java 路径必须等到全量 Python 稳定观察期结束。

## 里程碑规则

每个里程碑都必须说明：

1. 用户或调用方在完成后能观察到什么新行为。
2. 将修改或新增哪些准确路径，以及这些文件如何协作。
3. 使用哪些固定输入或数据库 fixture。
4. 运行哪些命令，预期看到什么结果。
5. 如何证明 Java/Python 行为相同，或为什么某个差异被明确接受。
6. 如何切换、如何回滚，以及回滚是否会影响活跃 run 或数据库状态。

可以使用原型里程碑降低风险，但原型必须可测试、标明保留/删除判据，并且不得悄悄进入生产路径。

## 验收证据

按切片风险选择证据，至少包括相关项：

- Python：Ruff、strict mypy、unit tests、MySQL integration tests。
- Java：受影响的稳定测试，以及新的 characterization test。
- HTTP：相同 fixture 下 Java/Python 契约差分无未解释差异。
- 写操作：从同一数据库快照分别执行 Java 与 Python，然后比较所有受影响表；不得在同一库上 live 双写。
- SSE：有序帧、事件 ID、心跳、UTF-8、终态、断连、follow、stop、timeout、backpressure 和任务清理。
- 文件：状态码、媒体类型、`Content-Disposition`、checksum、路径穿越和 symlink/Zip Slip 防护。
- 前端：相关 consumer test，以及必要的浏览器或手工 smoke。
- 运维：指标、日志脱敏、精确路由切换和回滚演练。

任何宽泛的全局字段忽略、把红色测试标成非阻塞、或只验证“接口返回了内容”都不是等价性证据。

## ExecPlan 模板

复制以下结构到 `docs/python-migration/execplans/<slice>.md`：

```md
# <简短、面向结果的标题>

本 ExecPlan 遵循 `docs/python-migration/PLANS.md`，执行期间必须保持自包含并持续更新。

## Purpose / Big Picture

说明这个垂直切片为什么迁移、用户或调用方将获得什么，以及如何直接观察成功。

## Scope

列出包含的路由、业务用例、表、外部服务和文件；明确列出不在本次范围内的内容。

## Progress

- [ ] (YYYY-MM-DD HH:MMZ) 待完成项。
- [ ] 部分完成项（已完成：…；剩余：…）。

## Surprises & Discoveries

- Observation: <发现>
  Evidence: <文件、测试输出或短日志>

## Decision Log

- Decision: <决定>
  Rationale: <为什么>
  Date/Author: <日期与执行者>

## Outcomes & Retrospective

总结已达成行为、遗留缺口、与初始目标的差异以及下一切片需要继承的经验。

## Context and Orientation

为不了解仓库的人说明 Java 入口、Python 目标、前端消费者、数据表、部署路由和相关迁移文档。使用完整仓库相对路径。

## Contract and Invariants

写出必须保持的 HTTP/SSE/数据库/文件行为、允许的端点级非确定字段，以及禁止改变的业务不变量。

## Plan of Work

按依赖顺序描述具体编辑。每一步写出文件、函数或类、预期行为和为何这样设计。

## Concrete Steps

写出工作目录、准确命令和简短预期输出。命令必须可重复执行，不调用生产或付费服务。

## Validation and Acceptance

以外部可观察行为描述通过条件。包括正常、边界、错误、并发或故障场景，以及契约差分结果。

## Cutover and Rollback

说明路由/owner 开关、切换顺序、活跃状态处理、回滚命令或操作，以及数据核对方式。

## Idempotence and Recovery

说明中断后如何判断当前状态、如何安全重跑，以及失败一半时如何恢复。

## Interfaces and Dependencies

列出最终应存在的公共接口、port/adapter、数据访问边界和第三方依赖。新增生产依赖必须说明必要性。

## Artifacts and Evidence

记录关键契约报告、测试结果、指标快照和精确路由配置的位置，不粘贴敏感信息或大段日志。
```

## 完成判定

只有同时满足以下条件，ExecPlan 才能标记完成：

- 计划中的用户可观察行为已经存在。
- 所有适用 gate 通过，没有未解释的契约差异。
- 数据库 writer 和路由所有权清晰，不存在双写窗口。
- 回滚已经在测试环境实际演练，而不是只写在文档中。
- `progress.md`、`risk-register.md`、`database-ownership.md` 等受影响文档已同步。
- 最终 diff 已独立审查，工作树中无本计划造成的意外改动。
