# B2B 组织接入与两层计费设计

> 状态：代码已实现，待部署环境验证
> 范围：remote service（`service/`），不改动 PPT 生成核心工作流

## 1. 目标与背景

让第三方企业项目**无感集成**本服务的 PPT 生成能力，并满足三条硬性要求：

1. **无感集成** — 企业后端对后端调用，终端用户无需感知本服务、看不到本服务界面。
2. **扣费单独计算** — 每个企业终端用户的用量可单独计量，供计费。
3. **数据隔离** — 企业之间、企业内终端用户之间的任务与产物互相隔离。

### 接入模式（已确认）

- **场景 B**：企业在自家系统集成本服务 API，企业后端已认证好自己的用户，用组织凭证调用本服务。
- **组织/租户模型**：引入 `organizations` 一等公民，用户归属组织。
- **组织级 API Key** + **终端用户身份透传**（`X-End-User-Id`）。

## 2. 两层计费模型

计费分两层，职责严格分离：

| 层 | 方向 | 谁扣费 | 依据 |
|---|---|---|---|
| 第 1 层 | 我们 → 企业 | 本服务扣企业**预付余额** | 真实成本：token + 生图 |
| 第 2 层 | 企业 → 终端用户 | **企业自己扣**它的用户 | 本服务返回的用量凭证 |

**核心原则：计量 ≠ 定价，两者分离。**

- **计量层**：只记原始数量（input/output token、生图张数、页数、任务数），永远全维度记录。
- **定价层**：把价格表套到原始数量上。本服务套自己的价（第 1 层），企业套企业的价（第 2 层）。

> 全维度计量的理由：计量成本极低，但定价随时会变。先全记原始数据，改价或换计费口径时无需重构数据库。

### 第 1 层：对企业扣费（预付扣余额）

- 口径：`input_tokens×单价 + output_tokens×单价 + images×单价`（贴合 COGS，不亏）。
- 模式：预付。企业充值余额，任务消耗时扣减，余额不足拒绝新任务。
- 授权-扣款：建任务时校验余额闸门；任务完成时按实际用量原子扣款。

### 第 2 层：给企业出用量凭证（Pull 拉取）

本服务不参与第 2 层扣费，只**返回用量明细**，企业按自己的定价扣它的用户。交付方式 v1 用 **Pull**（企业主动查），Webhook 作为后续增强。

## 3. 数据模型

新增 4 张表，改动 2 张表。现有个人用户/管理员 `org_id=NULL`，不受影响。

```sql
-- 新增：组织（租户）
CREATE TABLE organizations (
    id UUID PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    slug VARCHAR(100) NOT NULL UNIQUE,
    status VARCHAR(20) NOT NULL DEFAULT 'active',      -- active / suspended
    credit_balance NUMERIC(14,4) NOT NULL DEFAULT 0,   -- 预付余额
    daily_job_limit INT NOT NULL DEFAULT 100,          -- 防滥用闸门（配额仍保留）
    max_active_jobs INT NOT NULL DEFAULT 5,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 新增：组织级 API Key（独立表，不污染个人 user_api_keys）
CREATE TABLE org_api_keys (
    id UUID PRIMARY KEY,
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    key_prefix VARCHAR(20) NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    last_used_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 新增：全维度计量流水（第 2 层凭证的数据源）
CREATE TABLE usage_records (
    id UUID PRIMARY KEY,
    org_id UUID NOT NULL REFERENCES organizations(id),
    end_user_id UUID REFERENCES users(id),   -- 企业终端用户，可空
    job_id UUID NOT NULL REFERENCES jobs(id),
    turn_id TEXT NOT NULL DEFAULT '',        -- Codex turn.id，幂等键（崩溃重跑不重复计费）
    input_tokens INT NOT NULL DEFAULT 0,
    output_tokens INT NOT NULL DEFAULT 0,
    images INT NOT NULL DEFAULT 0,
    pages INT NOT NULL DEFAULT 0,
    charged_credits NUMERIC(14,4) NOT NULL DEFAULT 0,  -- 本轮真实成本，our_charge 求和源
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (job_id, turn_id)                 -- 防重复计费
);

-- 新增：充值/扣费流水（对账）
CREATE TABLE credit_transactions (
    id UUID PRIMARY KEY,
    org_id UUID NOT NULL REFERENCES organizations(id),
    amount NUMERIC(14,4) NOT NULL,           -- 正=充值，负=扣费
    reason VARCHAR(40) NOT NULL,             -- topup / job_charge / adjust
    job_id UUID REFERENCES jobs(id),
    balance_after NUMERIC(14,4) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 改造 users：支持企业终端用户
ALTER TABLE users ADD COLUMN org_id UUID REFERENCES organizations(id) ON DELETE CASCADE;
ALTER TABLE users ADD COLUMN external_id VARCHAR(200);
ALTER TABLE users ALTER COLUMN password_hash DROP NOT NULL;   -- 终端用户无密码
ALTER TABLE users ADD CONSTRAINT uq_org_external UNIQUE (org_id, external_id);

-- 改造 jobs：任务归属组织 + 计费轮次计数器 + 未结算预扣额
ALTER TABLE jobs ADD COLUMN org_id UUID REFERENCES organizations(id);
ALTER TABLE jobs ADD COLUMN billed_turns INT NOT NULL DEFAULT 0;  -- 已计费轮次（展示计数）
ALTER TABLE jobs ADD COLUMN held_amount NUMERIC(14,4) NOT NULL DEFAULT 0;  -- 未结算的预扣额（首轮结算或释放后清零）
```

> **约束说明**：
> - `organizations` 不支持硬删除（`jobs.org_id` 无级联，硬删会外键冲突）。停用组织用 `status='suspended'`，见 §4。
> - `credit_balance` 应用层保证非负（原子扣款 `WHERE balance >= amount`）；如需数据库兜底可加 `CHECK (credit_balance >= 0)`，但会与"允许失败任务扣成负债"策略冲突（见 §5.4），故默认不加 CHECK。
> - `users.external_id` 允许 NULL：现有个人用户 `org_id=NULL, external_id=NULL`，Postgres 视多个 NULL 为互不相等，不违反 `uq_org_external`。

## 4. 认证与数据隔离

### 4.1 认证：加第三条通道（不推翻已有）

```
require_user 里按顺序判定：
  Bearer pptm_xxx（命中 user_api_keys）  → 个人 API Key      （已有，不动）
  Bearer pptm_org_xxx（命中 org_api_keys）→ 组织凭证          （新增）
  Cookie session                         → 密码登录          （已有，不动）
```

组织凭证解析出 `org`（校验 `status='active'`），再读请求头 `X-End-User-Id`：

- **有** → 按 `(org_id, external_id)` 做 JIT provision：找到或新建一条 `users` 记录，任务挂该终端用户。
- **无** → 挂在组织的**默认服务账号**下。

> **默认服务账号**：建组织时（`POST /v1/admin/orgs`）在同一事务内创建一条 `users` 记录（`org_id=该组织, external_id='__service__', password_hash=NULL`）作为兜底所有者。迁移不预置，由建组织逻辑负责创建，避免"挂空账号"。

`AuthenticatedUser` 扩展一个 `org_id` 字段，向下传递。

> **停用组织**：`organizations.status='suspended'` 时，组织 Key 认证直接拒绝（403）。组织不做硬删除（见 §3 约束）。

### 4.2 数据隔离（复用现有 owner_id）

现有隔离完全靠 `jobs.owner_id`（见 `repository.py` 的 `get_job_for_user` / `list_jobs_for_user`）。

- 每个企业终端用户 JIT 成一条真实 `users` 记录，`owner_id` = 该终端用户 id。
- **现有 owner_id 隔离逻辑天然复用**：A 公司张三看不到李四的任务，产物访问经 `_require_job` 同样受控。

### 4.3 隔离的两个已知边界（需向客户说明）

- **文件物理层未隔离**：所有任务堆在 `runtime/jobs/<uuid>/`，仅靠接口 `owner_id` 鉴权挡住。逻辑隔离足够，物理为混放——合规敏感客户需提前告知。
- **组织级列表待补**：现有仅单用户列表。企业后端若需"查全公司所有任务"，需新增按 `org_id` 聚合的查询（见第 6 节管理/查询接口）。

## 5. 计量与扣费流程

### 5.1 计量数据源（均已核实可得）

| 维度 | 数据源 | 现状 |
|---|---|---|
| input/output token | `thread/tokenUsage/updated` 的 `token_usage.last` | 已接入 |
| 生图张数 | `control/image_generation.json` 的累计值 | 已接入 |
| 页数 | observed `page_count`（`storage.WorkspaceProgress`） | 已接入 |
| 任务数 | count | 已接入 |

> token 提取：`_run()` 按 `turn_id` 收集 `thread/tokenUsage/updated`，读取本轮 `last` 用量，并原子写入 `control/pending_turn_usage.json`。worker 结算成功后删除该记录；崩溃恢复、取消和失败路径会先补结算。

### 5.2 计费模型：预扣额度 + 实际结算（reserve then settle）

预付的限制：**任务跑完才知道花多少 token，事前无法精确冻结**。采用"预扣 + 结算"两段式，用一个可配的**预扣额度**限制风险。

```
建任务或确认/修订继续时（初次先建 job 行，再预扣，使 hold 关联 job）：
  1. 校验 org.status = 'active'（suspended 拒绝 403）
  2. 预扣额度 hold_amount（可配，见 §8），原子扣：
     UPDATE organizations SET credit_balance = credit_balance - :hold
       WHERE id = :org AND credit_balance >= :hold AND status='active'
       RETURNING credit_balance
     扣不到 → 402；扣到 → 写 jobs.held_amount = :hold + credit_transactions(reason='hold', job_id)
  （组织行锁、active/今日任务数检查与任务插入处于同一事务；配额调整接口仍待补充）

每轮 turn 结束时（结算，无论成败）：原子事务内完成（FOR UPDATE 锁 job 行）
  3. 读本轮真实用量 → 写 usage_records（UNIQUE(job_id,turn_id) 幂等，turn_id=Codex turn.id）
  4. 实际成本 actual = input_tokens×价 + output_tokens×价 + images×价
  5. held_amount>0 → 用 jobs.held_amount（本轮实际预扣额，非运行时定价）对冲：
       delta = held_amount - actual；退/补差额；然后 jobs.held_amount = 0
     仅旧任务恢复且没有预扣时 → 直接扣 actual（reason='settle_extra'）
  6. jobs.billed_turns += 1

任务未结算即终止（cancel / 入队失败 / 崩溃且从未结算）：
  7. release_hold(job_id)：FOR UPDATE，若 held_amount>0 则退回并清零（幂等，防重复退）
```

> **对账不变量**：预扣与结算/释放同源——都以 `jobs.held_amount`（本轮实际扣的值）为准，改价不影响在途 turn。每轮结算或释放二者必居其一消费掉 held_amount，不漏不重。

### 5.3 关键策略（钱的问题，不含糊）

- **失败/放弃也扣费**（硬伤①）：结算在**每轮 turn 结束就做，不论成败**。哪怕任务失败或用户在确认阶段放弃，已消耗的 token/图照扣——成本已真实发生，不能白嫖。
- **预扣防并发超支**（硬伤②）：建任务时先原子扣掉 `hold_amount`，并发建任务不会都通过（余额被逐笔扣减）。这才是真正的"授权"，替代原先"只 check 不冻结"的错误设计。
- **结算允许扣成负数**：`actual > hold` 时补扣可让余额为负（企业欠费），下次建任务时余额 < hold_amount 自然被拒。用 `hold_amount` 上限控制单次最大欠额风险。
- **原子性**：预扣和结算都用带 `WHERE` 条件的单条 UPDATE + 事务，防并发。
- **幂等**：`usage_records` 的 `UNIQUE(job_id, turn_id)`，turn_id 取 Codex `turn.id`；同一已完成 turn 的重复提交不重复结算。`pending_turn_usage.json` 保留数据库写入前的用量，供租约恢复补结算。`jobs.billed_turns` 仅作展示计数，不再充当幂等键；缺少 `turn_id` 时拒绝结算。
- **修订累加**：确认与 `/resume` 每次生成新 turn 前必须重新预扣，完成后结算并追加流水，不覆盖历史。

### 5.4 边界情形

- **确认阶段放弃**：第一轮 turn（intake→确认）结束即结算该轮 token 成本；用户不确认，任务终止，已扣不退。
- **预扣额度设置**：`hold_amount` 需覆盖绝大多数单轮任务的成本上限，太小则频繁扣成负数、风险敞口大；太大则占用企业余额。默认值与调优见 §8。

## 6. 接口设计

### 6.1 企业调用（业务接口，几乎复用现有）

现有 `/v1/jobs` 等接口签名不变，仅认证换成组织 Key + 可选 `X-End-User-Id`：

```
POST /v1/jobs
  Authorization: Bearer pptm_org_xxx
  X-End-User-Id: their-user-42        # 可选，透传企业终端用户
  → 建任务自动打上 org_id + owner_id(该终端用户)
```

### 6.2 第 2 层用量凭证（Pull 拉取）

```
GET /v1/jobs/{job_id}/usage           # 单任务用量
GET /v1/orgs/usage?end_user_id=&from=&to=   # 按终端用户聚合，供企业出账
```

单任务返回示例：

```json
{
  "job_id": "...",
  "end_user_id": "their-user-42",
  "status": "final",                  // partial(修订中) / final(彻底完成)
  "usage": {
    "input_tokens": 12000,
    "output_tokens": 3400,
    "images": 5,
    "pages": 12,
    "jobs": 1
  },
  "our_charge": { "credits": 8.5 }    // 第 1 层我们扣企业多少，透明
}
```

> `status` 语义：任务或其修订进行中为 `partial`，彻底完成才 `final`。企业应在 `final` 后再对其用户结账。

### 6.3 管理接口（管理员开户，BrowserUser + is_admin 守卫）

```
POST   /v1/admin/orgs                    建组织 + 设配额
POST   /v1/admin/orgs/{id}/keys          签发组织 Key（明文仅显示一次）
DELETE /v1/admin/orgs/{id}/keys/{key_id} 吊销 Key
POST   /v1/admin/orgs/{id}/credits       充值（写 credit_transactions）
GET    /v1/admin/orgs/{id}/usage         用量报表（按终端用户聚合）
```

## 7. 落地拆解（渐进式，每步可验证）

| 步 | 内容 | 规模 |
|---|---|---|
| 1 | DB 迁移：5 新表 + 2 改表（含 jobs.org_id / billed_turns / held_amount） | 5 SQL |
| 2 | 定价配置（`billing_config` 加载 3 个单价和预扣额） | 小 |
| 3 | token 用量提取（`thread/tokenUsage/updated` → RunnerResult + pending sidecar） | 小 |
| 4 | 认证第三通道（组织 Key）+ 终端用户 JIT + 默认服务账号 + `AuthenticatedUser.org_id` | 中 |
| 5 | 计量落库（每轮结算/生图/修订累加，幂等） | 中 |
| 6 | 第 1 层扣费（建任务预扣 + 每轮结算 + 交易流水，失败也扣） | 中 |
| 7 | 第 2 层凭证接口（单任务查 + 聚合查） | 中 |
| 8 | 管理接口（开户+建服务账号 / 发 Key / 充值 / 报表） | 中 |
| 9 | 企业接入文档 + curl/Python 示例 | 文档 |

## 8. 定价配置（入库，管理后端可配）

单价是第 1 层扣费和 `our_charge` 字段的前置依赖，**不能推后**。定价**存数据库**（不用环境变量），管理后端可动态改，无需重启服务。

```sql
CREATE TABLE billing_config (
    id INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),   -- 全局单行
    price_input_token NUMERIC(16,10) NOT NULL DEFAULT 0.000002,
    price_output_token NUMERIC(16,10) NOT NULL DEFAULT 0.000008,
    price_image NUMERIC(12,4) NOT NULL DEFAULT 0.05,
    hold_amount NUMERIC(14,4) NOT NULL DEFAULT 5.0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

- **读取**：服务运行时从 `billing_config` 读单价，带短 TTL 内存缓存（避免每任务查库）。扣费与 `our_charge` 统一从这里取，保证一致。
- **配置**：管理后端 `GET/PUT /v1/admin/billing-config`（`BrowserUser + is_admin`）读改单价与预扣额度。
- **调优 `hold_amount`**：观察 `usage_records` 单轮实际成本分布，取 P95 左右，平衡"占用余额"与"欠费敞口"。
- **后续增强**：按企业单独定价（per-org override）时，加一张 `org_billing_config` 覆盖全局默认。

## 9. 后续增强（真待定）

- **Webhook 推送**：第 2 层 Pull 之后的增强，任务完成回调企业 `callback_url`（含重试 + 签名）。
- **OAuth2 客户端凭证**：组织 API Key 之后的高级凭证选项（短期令牌 + 轮换）。
- **文件物理隔离**：合规敏感客户如需按 org 分目录存储，另行设计。
- **SAML 2.0**：若出现要求员工登录（场景 A）的大客户再评估。
