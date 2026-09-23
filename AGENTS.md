# Reactor 仓库协作规范

## 适用范围与目标

- 本文件适用于整个仓库；更深目录中的 `AGENTS.md` 可为其子树补充或收紧规则。
- 目标是把 **Java 后端**按可回滚的小批次迁移到 `backend-python/`，并保持现有外部行为兼容。Java 在完全退役前仍是行为基准，不做一次性重写。
- React 前端 `ui/` 与独立服务 `reactor-tool/`、`reactor-sandbox` 不是本次重构对象。除非任务明确要求，不重写、不合并、不搬迁，也不通过修改它们来掩盖后端不兼容。
- 默认端口与部署角色保持不变：Java `8100`、Python `8200`、`reactor-tool` `1601`、sandbox `1602`、前端 `3000`。

## 开始工作前

先按顺序阅读与任务有关的资料：

1. `docs/python-migration/codex-migration-guide.md`：迁移工作流、阶段顺序与验收总览。
2. `docs/python-migration/progress.md`：当前阶段、证据和出口条件。
3. `docs/python-migration/inventory.md`：Java 模块、路由、运行时与外部系统清单。
4. `docs/python-migration/api-contracts.md`：HTTP、Cookie、SSE 和兼容性规则。
5. `docs/python-migration/database-ownership.md`：表、事务边界和写入所有权。
6. `docs/python-migration/risk-register.md`：已知风险与当前阻塞项。
7. `docs/python-migration/PLANS.md`：复杂迁移切片的 ExecPlan 规范。
8. `backend-python/README.md` 以及将要修改模块的源码和测试。

准备新阶段时，从 `docs/python-migration/staged-prompts.md` 选择对应提示词；该文件是操作模板，不替代上述事实与契约文档。

执行 `git status --short` 和相关 `git diff` 后再编辑。工作区可能已有用户改动：只做任务所需的最小补丁，不覆盖、不格式化、不删除无关文件；遇到重叠修改时先理解并保留。禁止用 `git reset --hard`、`git checkout --`、`git clean` 或其他方式清理用户工作树。

## 迁移工作方式

### 契约优先

- 每次只迁移一个有清晰边界的路由族、用例或写操作。实现前先从 Java 源码、前端消费者和可重复夹具确定契约；能运行 Java 时，先记录脱敏 golden。
- 保持路径、HTTP 方法、状态码、媒体类型、`{code, info, data}` 信封、字段类型、`null`、空集合、排序、分页、Cookie 属性及二进制响应一致。不要借迁移“修正”既有行为。
- SSE 必须保持事件顺序、`id`/游标、心跳、UTF-8、多行 `data`、未知字段、恢复语义和 completed/stopped/failed/waiting 的终止差异。连接关闭本身不等于成功。
- 非确定字段只能在单个 contract case 中按 JSON Pointer 放行；不得添加全局忽略规则。未实现路由返回明确的 `501`，不得伪造成功数据。
- 自动化测试只用本地 fake、脱敏录制和专用测试库；不得调用付费模型或真实外部提供商。

### Python 包边界

`backend-python/src/reactor_backend/` 的职责如下：

- `api/`：FastAPI 路由、中间件、传输 schema、请求解析和响应映射；不放 SQL 或业务编排。
- `application/`：用例编排、事务协调和端口定义；不依赖 FastAPI 响应对象。
- `domain/`：业务规则、实体和值对象；不依赖 FastAPI、SQLAlchemy 或具体外部服务。
- `runtime/`：Agent 执行、流式生命周期、并发、取消与恢复；不得绕过 application 直接承担 HTTP 传输职责。
- `infrastructure/`：数据库和外部集成的实现；通过显式接口注入，不让 domain 反向依赖基础设施。
- `shared/`：稳定、通用且无业务归属的少量原语；不得成为杂物目录。
- `contracts/`：迁移期 HTTP/SSE 捕获与比较工具；生产业务代码不得依赖测试 golden 或比较逻辑。

依赖方向保持为 `api -> application -> domain/runtime 抽象`，由 `infrastructure` 实现端口并在启动层装配。避免循环依赖、跨层直连数据库和“大而全”的 service 模块。

### 数据与写入所有权

- 迁移期间允许 Java/Python 共享读取，但同一项操作只能有一个活动写入者；严禁应用层双写、影子写和“先写 Java 再写 Python”。
- 切换任何写路由前，先在 `database-ownership.md` 记录到操作粒度的所有权，再部署 Python 写入者，最后切换精确路由。回滚时先把路由切回 Java，再恢复 Java 写入。
- 保留现有事务语义、条件更新/CAS、生成键、空值和时区行为。零行 CAS 更新表示冲突或幂等重复，不得当作无条件成功。
- Ledger 的 start/finish 是两个生命周期写入；禁止让数据库事务跨越长时间 LLM、工具或网络调用。
- Schema 变更不属于常规迁移；未经明确批准不得改表。当前仓库的实际迁移实践是 `db/migrations/*.sql` 下的经审阅纯 SQL；**Alembic 尚未引入**（无配置、无依赖）。获批改表时，要么在独立任务中先引入 Alembic 并附上/下线与回滚方案，要么明确批准继续使用经审阅的纯 SQL 迁移。

### 访客 GET 的写副作用

- 不得把所有 `GET` 都视为纯读。`/api/agent/visitor/bootstrap` 以及需要访客身份的请求，在 Cookie 缺失或过期时可能创建身份、刷新 last-seen 并发送 `Set-Cookie`。
- 迁移这类 GET 前必须为 `ai_agent_visitor_identity` 的 resolve/create/refresh 操作分配唯一写入者，并验证并发首次访问、Cookie 属性、IP/User-Agent 记录以及请求结束后的上下文清理。
- 除已记录的兼容行为外，不给其他 GET 新增写副作用。

### SSE 原子路由族

- 以下有状态路由按同一原子路由族处理：主 Agent stream `/web/api/v1/gpt/queryAgentStreamIncr`、`/api/agent/run/*`、`/api/agent/ask-user/*` 和 `/api/agent/plan-approval/*`。
- 该路由族必须由同一后端实例/运行时拥有，并按现有访客 Cookie 保持亲和；禁止按单个端点独立灰度或让 stream 与 follow/stop/inject/resume 分流到不同后端。
- 切换前验证重连/回放、心跳、客户端断开、取消传播、等待人工输入、进程重启和无泄漏后台任务；必须具备整族回滚步骤。

## 验证命令

Python 的常规门禁在 `backend-python/` 中执行：

```bash
uv sync --all-groups
uv run pytest -m "not integration"
uv run ruff check .
uv run mypy src
```

仅在显式配置专用测试库后运行集成测试（`TEST_MYSQL_URL` 是必需的门控变量，缺失时测试自行 skip）：

```bash
TEST_MYSQL_URL='mysql+asyncmy://<test-user>:<test-password>@127.0.0.1:3306/<test-db>?charset=utf8mb4' \
  uv run pytest -m integration
```

不得把生产凭证写入该变量、命令历史或任何报告。

Java/Python HTTP 契约比较（需要两个服务和确定性测试夹具）：

```bash
cd backend-python
JAVA_BASE_URL=http://127.0.0.1:8100 \
PYTHON_BASE_URL=http://127.0.0.1:8200 \
uv run reactor-contract tests/contract/cases/initial.json \
  --output build/contract-report.json
```

SSE 使用 `uv run reactor-sse-contract ...` 单独比较，并使用已检入的本地 fake 请求。记录 Java golden 时使用 `--record-java`（记录 Python 响应用对称的 `--record-python`）；`--golden <file> --response <file>` 是**完全离线**的比较路径，不需要任何服务。非确定字段仍只能按单个 case 的 JSON Pointer 放行（指针根是采集文档，故 body 字段为 `/body/data/...`、cookie 属性为 `/cookies/*/attributes/...`）；不得把原始 Cookie、密钥、完整用户提示或付费提供商响应写入仓库。

涉及 Java 参考实现时，至少运行稳定基线：

```bash
mvn -B -pl Reactor-agent-case -am -DskipTests=false test
```

注意该命令只构建 parent/api/types/domain/case 五个模块，**不编译 `Reactor-agent-trigger`（全部 HTTP 路由）与 `Reactor-agent-infrastructure`（全部 mapper）**。改动这两个模块时必须另行编译验证（见 `risk-register.md` R-25）。

完整 Java app 套件当前存在已登记的历史失败；必须如实报告，不得重新跳过或把它误称为全绿。涉及 Compose 时先做语法校验：

```bash
MYSQL_PASSWORD=test-only MYSQL_ROOT_PASSWORD=test-only docker compose config --quiet
```

需要共存基线冒烟时（可重复执行的 Compose smoke；只用 test-only 凭证）：

```bash
docker compose up -d
curl -fsS http://127.0.0.1:8200/internal/health/live
curl -fsS http://127.0.0.1:8200/internal/health/ready
docker compose down
```

`config --quiet` 只校验 YAML，**不等于冒烟**。两条 health 都返回 200 才算 smoke 通过；`ready` 在 MySQL 就绪前返回 503 是预期的 fail-closed 行为。

根据改动范围补充单元、集成、契约、并发、故障和回滚测试；不能运行的门禁需说明原因、已运行证据和剩余风险。

## 阶段完成定义

`progress.md` 中各阶段的 exit gate 是权威标准。代码写完不等于阶段完成；只有同时满足以下条件才能标记 Complete：

- 范围内路由/操作已实现，且包边界与安全约束满足。
- 新增或更新的单元、集成、HTTP/SSE 契约测试通过；Java/Python 差异为零或有明确批准的端点级说明。
- 写入所有权、事务、并发、幂等、取消、重启和回滚已按该阶段风险验证。
- 精确切流和精确回滚方案可执行；SSE 原子路由族没有被拆分。
- `progress.md` 已记录日期、命令、结果和证据，相关迁移文档同步更新。
- 未引入秘密、真实付费调用、未登记 schema 变更或对用户工作树的破坏。

## 文档同步规则

迁移代码与对应文档必须在同一任务中保持一致：

- 路由、模块、外部依赖或运行时认识变化：更新 `inventory.md`。
- HTTP、Cookie、SSE、序列化或允许差异变化：更新 `api-contracts.md` 和相应 contract case。
- 任何写操作切换：**切流前**更新 `database-ownership.md`。
- 新风险、缓解措施、阻塞或风险关闭：更新 `risk-register.md`。
- 阶段状态与验收证据：更新 `progress.md`；没有证据时保持原状态。

使用实际日期和实际运行结果，不预写“已通过”。不要为让测试通过而篡改 golden、扩大忽略项或删除风险记录；契约的有意变化必须由用户明确批准并说明兼容/回滚影响。

## 禁止项

- 禁止一次性大爆炸重写或在无契约证据时删除 Java 实现。
- 禁止通过改 React 前端、`reactor-tool` 或公开 API 来迁就 Python 实现。
- 禁止双写、无所有权切流、拆分 SSE 原子路由族、对非幂等写入添加通用自动重试。
- 禁止吞掉取消、启动无界 asyncio 任务/并发、用 socket close 伪装成功终止。
- 禁止真实凭证进入代码、配置、日志、fixture、golden 或报告；禁止自动化测试产生付费外部调用。
- 禁止伪造成功占位响应、全局忽略契约差异、静默改变时间/空值/排序语义。
- 禁止未经批准改 schema、删除数据、清理工作树或修改任务范围外的文件。
