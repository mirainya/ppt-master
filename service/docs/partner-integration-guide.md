# PPT Master 企业对接文档

面向在自家系统中集成 PPT Master 生成能力的第三方企业。终端用户无需感知本服务；企业后端用组织凭证调用，可按终端用户单独计量。

服务地址：`https://ppt.mirainya.icu`

---

## 1. 开通

企业无需自助注册，由服务方管理员开户、签发组织 API Key、预付充值，并交付：

- **组织 API Key**：形如 `pptm_org_xxxxx`，**只保存在企业后端**，切勿下发浏览器或客户端。
- **回调签名密钥**（可选，用了用量回调才需要）：形如随机串，一次性交付，请妥善保存。

## 2. 认证与终端用户透传

企业后端调用业务接口时带两个头：

| 头 | 必填 | 说明 |
|---|---|---|
| `Authorization: Bearer pptm_org_xxxxx` | 是 | 组织凭证 |
| `X-End-User-Id: <企业侧用户ID>` | 否 | 企业自己的终端用户标识 |

同一 `X-End-User-Id` 稳定映射到一条隔离的用户空间：不同终端用户互相看不到对方的任务，用量分别计量。不带该头时，任务归属组织的默认服务账号（内部标识为 `__service__`）。

`X-End-User-Id` 只允许字母数字与 `-` `_`，且不能是保留值 `__service__`（会返回 `400`）。

## 3. 借用工作台（一次性 SSO 票据）

终端用户可直接进入 PPT Master 工作台，无需再输用户名密码。组织 API Key 始终留在企业后端。

```bash
# 企业后端为当前终端用户申请票据
curl -X POST https://ppt.mirainya.icu/v1/auth/org-tickets \
  -H 'Authorization: Bearer pptm_org_xxxxx' \
  -H 'X-End-User-Id: cust-42'
# → {"ticket":"<one-time-ticket>","expires_in":60}
```

企业前端随后跳转：

```text
https://ppt.mirainya.icu/#sso_ticket=<one-time-ticket>
```

票据放在 URL Fragment，不会进入服务器访问日志。工作台自动调 `POST /v1/auth/org-tickets/consume` 原子消费票据并设置 HttpOnly Session Cookie。票据 **60 秒有效、只能用一次**；登录身份继续绑定原 `org_id + X-End-User-Id`。组织被停用后，已有工作台 Session 立即失效。

> **重要**：终端用户在工作台里建任务是**浏览器直连本服务**，不经过企业后端。所以企业**无法在自己的网关做额度准入** —— 想实时管住某个员工的消耗，必须用第 6 节的用量回调。

## 4. 生成 PPT

```bash
curl -X POST https://ppt.mirainya.icu/v1/jobs \
  -H 'Authorization: Bearer pptm_org_xxxxx' \
  -H 'X-End-User-Id: cust-42' \
  -F 'prompt=用这份材料做一份 PPT' \
  -F 'route=generate_pptx' \
  -F 'files=@report.pdf'
# → 202 {"id":"<job_id>","status":"queued", ...}
```

任务异步。建任务时按 `hold_amount` 预扣组织余额，不足返回 `402`；提交确认或再次修订也会为下一轮预扣同额，不足同样 `402` 且原状态不变。

组织还有两道并发闸：活跃任务数与每日任务数，超限返回 `429`。

### 查询进度

- 轮询：`GET /v1/jobs/<job_id>`（返回 `status` / `progress`）
- 实时：`GET /v1/jobs/<job_id>/events`（SSE，支持 `Last-Event-ID` 断点续传）

状态流：`queued → intake → awaiting_confirmation → planning → executing → succeeded`（或 `failed` / `cancelled`）。

### 确认方案 / 修订

```bash
curl -X POST https://ppt.mirainya.icu/v1/jobs/<job_id>/confirmation \
  -H 'Authorization: Bearer pptm_org_xxxxx' -H 'X-End-User-Id: cust-42' \
  -H 'Content-Type: application/json' \
  -d '{"approved":true,"message":""}'
```

`generate_pptx` 在 `awaiting_confirmation` 处阻塞等待确认。**未确认的任务不会自动结束**，会一直占着一份预扣额度 —— 建议企业侧给挂单设超时，超过 N 天未确认就主动取消（见第 7 节）。

### 下载产物

```bash
curl https://ppt.mirainya.icu/v1/jobs/<job_id>/artifacts \
  -H 'Authorization: Bearer pptm_org_xxxxx' -H 'X-End-User-Id: cust-42'
curl -OJ https://ppt.mirainya.icu/v1/jobs/<job_id>/artifacts/<artifact_id>/download \
  -H 'Authorization: Bearer pptm_org_xxxxx' -H 'X-End-User-Id: cust-42'
```

产物文件默认保留 30 天，到期清理但任务记录与计费流水保留（此后下载返回 `410`）。

---

## 5. 取消耗：三条路

本服务按 **token + 生图** 的真实成本扣组织预付余额（第 1 层）。企业用下面的用量凭证，按自己的定价向终端用户计费（第 2 层，本服务不参与）。

| 方式 | 时效 | 用途 |
|---|---|---|
| 单任务凭证 | 请求即时 | 单笔结账、对账 |
| 按用户聚合 | 请求即时 | 周期出账 |
| 用量回调 | 每轮结算后秒级 | **实时管控、防超支** |

### 5.1 单任务用量凭证

```bash
curl https://ppt.mirainya.icu/v1/jobs/<job_id>/usage \
  -H 'Authorization: Bearer pptm_org_xxxxx' -H 'X-End-User-Id: cust-42'
```

```json
{
  "job_id": "...",
  "end_user_id": "cust-42",
  "status": "final",
  "usage": {"input_tokens": 12000, "output_tokens": 3400, "images": 5, "pages": 9, "jobs": 1},
  "our_charge": {"credits": 0.2736}
}
```

- `status`：`partial`（任务或修订进行中）/ `final`（彻底完成）。**必须等 `final` 再对终端用户结账** —— 修订会追加用量。
- `usage`：原始计量维度，企业按需定价。
- `our_charge.credits`：本服务对该任务扣组织的真实成本，供对账参考，不是给终端用户的报价。

### 5.2 按终端用户聚合（出账）

```bash
curl 'https://ppt.mirainya.icu/v1/orgs/usage?end_user_id=cust-42&since=2026-07-01T00:00:00Z&until=2026-08-01T00:00:00Z' \
  -H 'Authorization: Bearer pptm_org_xxxxx'
```

返回该组织每个终端用户的用量与成本汇总。参数均可选：`end_user_id` 不传则返回全部终端用户，`since` 含、`until` 不含。

**鉴权范围**：只有组织 API Key 能读整个组织的汇总。工作台 Session（含 SSO 登录）调此接口会被强制限定为**调用者自己**那一条，传别人的 `end_user_id` 返回 `403`。出账请始终在企业后端用组织 Key 调用。

### 5.3 各计量维度的累计口径

修订会重跑部分页面，各维度累加方式并不相同。按页定价前请先读这一节。

| 维度 | 口径 | 修订重做 3 页时 |
|---|---|---|
| `input_tokens` / `output_tokens` | 每轮实际消耗**逐轮累加** | 追加该轮 token |
| `images` | 磁盘生图数的**增量**累加 | 重新生图才追加 |
| `pages` | 磁盘当前页数的**最高水位** | 不变 |

`pages` 取产出目录里页文件的数量，写入时只记 `max(0, 当前页数 - 已记录总和)`。所以 9 页的稿子重做第 4/5/6 页，`pages` 仍是 **9**，不是 12；页数减少（9 页删到 7 页）时 `pages` 也**不会回退**。要按最终交付页数计费，请在任务终态时自行读产物页数。

`pages` **不参与**本服务扣费，第 1 层只按 token + 生图结算。因此修订不涨 `pages` 但 `our_charge.credits` 仍会上升。按页向终端用户定价意味着**修订对用户免费而成本由企业承担**；若希望修订计费，请改用 `our_charge.credits` 乘系数，或自行统计修订轮次。

### 5.4 跨月任务

用量按**每轮发生的时刻**落库，聚合接口按该时刻过滤。所以一个 6/28 开始、7/5 才完成的任务，6 月账期只含 6 月那几轮、7 月账期只含 7 月那几轮，两个月加总等于真实总量，不重不漏。

**但 `jobs` 字段是去重任务数，跨月任务会在两个月各算一次。** 若按「任务数 × 单价」收费，跨月任务会被收两遍 —— 请改按 token / 生图 / `our_charge` 计费，或自行维护已结算的 `job_id` 集合。

---

## 6. 用量回调（Webhook）

第 5.1、5.2 是 Pull，最快只能轮询。要在任务**执行途中**发现某个员工超支，用回调：服务方在**每轮结算后立刻**把用量推给企业接口，企业自行累计，超限时调 cancel 停任务。

### 6.1 开通

回调地址与签名密钥由**服务方管理员**代配（不开放企业自助，因为回调地址是服务端的出站目标）。请向服务方提供：

- 一个**公网 HTTPS** 回调地址，例如 `https://acme.example.com/pptm/usage`

服务方录入后会做一次连通性测试，并把一次性明文签名密钥交给你。之后企业可用组织 Key 自查配置：

```bash
curl https://ppt.mirainya.icu/v1/orgs/webhook \
  -H 'Authorization: Bearer pptm_org_xxxxx'
# → {"org_id":"...","callback_url":"https://acme.example.com/pptm/usage",
#    "enabled":true,"secret_configured":true}
```

**地址约束**（服务端在每次发送前重新校验，不只是录入时）：

- 必须 `https`，不能带 URL 内嵌的用户名密码
- 域名不能解析到环回、私有、链路本地（含 `169.254.169.254`）等非公网地址
- **不跟随重定向**，任何 3xx 视为失败

### 6.2 事件

| 事件 | 何时发出 | `delta` | `usage_status` |
|---|---|---|---|
| `usage.turn` | 每轮 agent turn 计费落库后 | 本轮增量 | `partial` |
| `usage.final` | 任务进入 succeeded / failed / cancelled | `null` | `final` |

```json
{
  "event_id": "9f1c0f2e-4b7a-4c31-9d55-2a7e6b0c1f88",
  "event_type": "usage.turn",
  "occurred_at": "2026-07-25T09:12:03.114203Z",
  "org_id": "3a8f...",
  "end_user_id": "cust-42",
  "job_id": "7c21...",
  "job_status": "executing",
  "usage_status": "partial",
  "turn": {"index": 3, "turn_id": "01JZQ8..."},
  "delta": {
    "input_tokens": 4200, "output_tokens": 1100, "images": 2, "pages": 3,
    "our_charge": {"credits": 0.1084}
  },
  "job_total": {
    "input_tokens": 12000, "output_tokens": 3400, "images": 5, "pages": 9,
    "turns": 3, "our_charge": {"credits": 0.2736}
  }
}
```

`delta.*` 与 `job_total.*` 的字段名与第 5.1 完全一致，5.3 的累计口径直接适用。

**三条必须遵守的约定**：

1. **`job_total` 是权威值，不要靠累加 `delta` 求总量。** 投递是至少一次且不保证顺序 —— 对同一 `job_id` 取 `job_total` 的最大值即与顺序无关。
2. **`usage.final` 的 `delta` 是 `null`**，不是全零。终态事件是完成标记，不是一轮零消耗。
3. 任务终态后若被继续修订（resume），会再发出**新的** `usage.final`，`job_total` 是续做后的新总量。别假设一个任务只有一条 final。

### 6.3 验签

| 请求头 | 说明 |
|---|---|
| `X-PPTM-Event-Id` | 事件 id，**跨重试不变** —— 用它做幂等去重 |
| `X-PPTM-Timestamp` | Unix 秒，每次尝试都变 |
| `X-PPTM-Signature` | `sha256=<hex>` |

签名是 `HMAC-SHA256(secret, f"{timestamp}." + body)`。务必对**收到的原始 body 字节**验签，不要反序列化再重新序列化。

```python
import hashlib
import hmac
import time


def verify(secret: str, timestamp: str, signature: str, body: bytes) -> bool:
    """Reject stale or unsigned callbacks before trusting the payload."""
    if abs(time.time() - int(timestamp)) > 300:   # 防重放
        return False
    expected = hmac.new(
        secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)
```

```javascript
const crypto = require("crypto");

function verify(secret, timestamp, signature, rawBody) {
  if (Math.abs(Date.now() / 1000 - Number(timestamp)) > 300) return false;
  const expected =
    "sha256=" +
    crypto
      .createHmac("sha256", secret)
      .update(Buffer.concat([Buffer.from(`${timestamp}.`), rawBody]))
      .digest("hex");
  return crypto.timingSafeEqual(Buffer.from(expected), Buffer.from(signature));
}
```

### 6.4 重试与死信

返回 **2xx** 视为成功。

- **会重试**：5xx、429、408、网络错误 —— 按 `10s → 30s → 2m → 10m → 1h → 6h`（其后维持 6h）退避，共 8 次
- **立即死信**：其余 4xx、3xx、回调地址校验失败 —— 重试无益，不浪费尝试

死信不再重试，`dead_at` 有值、`last_error` 记明原因。企业可自查投递记录：

```bash
curl 'https://ppt.mirainya.icu/v1/orgs/webhook/deliveries?limit=20' \
  -H 'Authorization: Bearer pptm_org_xxxxx'
```

返回每条投递的 `attempts` / `next_attempt_at` / `delivered_at` / `dead_at` / `response_status` / `last_error` 与完整 `payload`，用于核对漏收。已完成（含死信）的记录保留 30 天，**待投递的永不删除**。

### 6.5 超限闭环

```bash
# 累计超限时用组织 Key 停掉该任务
curl -X POST https://ppt.mirainya.icu/v1/jobs/<job_id>/cancel \
  -H 'Authorization: Bearer pptm_org_xxxxx' -H 'X-End-User-Id: cust-42'
```

取消是实时的：排队中或等确认的任务直接转 `cancelled`，正在跑的 agent 最迟 1 秒被中断。已消耗的那一轮仍会计费。

**两个坑**：

- `end_user_id` 为 `__service__` 时（企业建任务未带 `X-End-User-Id`）**不要**回传该值，它是保留字会返回 `400`；此时省略该头即命中默认服务账号。
- cancel 只停**当前这一个任务**。该终端用户的工作台 Session 仍有效，可以立刻再建一个新任务。若需要彻底拦住某个员工，请联系服务方。

---

## 7. 数据隔离说明

- 逻辑隔离：企业之间、企业内终端用户之间的任务与产物互相不可见（基于所有者鉴权）。
- 物理存储未按组织分目录（同一运行目录混放），仅靠接口鉴权隔离。对物理隔离有合规要求的场景需另行约定。

## 8. Python 最小示例

```python
import httpx

BASE = "https://ppt.mirainya.icu"
HEADERS = {"Authorization": "Bearer pptm_org_xxxxx", "X-End-User-Id": "cust-42"}

with httpx.Client(base_url=BASE, headers=HEADERS, timeout=30) as client:
    job = client.post(
        "/v1/jobs",
        data={"prompt": "用这份材料做一份 PPT", "route": "generate_pptx"},
        files={"files": open("report.pdf", "rb")},
    ).json()
    job_id = job["id"]

    # 轮询到终态（确认阶段的处理省略）
    # ...

    usage = client.get(f"/v1/jobs/{job_id}/usage").json()
    assert usage["status"] == "final", "等 final 再结账"
    print(usage["usage"], usage["our_charge"])
```

## 9. 接入检查清单

- [ ] 组织 API Key 只在后端，不出现在前端代码、URL、日志里
- [ ] `X-End-User-Id` 用稳定的企业侧用户 ID，不用会变的昵称
- [ ] 结账前校验 `status == "final"` / `usage_status == "final"`
- [ ] 按 `job_id` 幂等，同一任务不重复计费
- [ ] 不按「任务数 × 单价」计费（跨月任务会重复计数）
- [ ] 回调按 `X-PPTM-Event-Id` 幂等去重
- [ ] 回调用 `job_total` 取最大值，不累加 `delta`
- [ ] 回调验签用原始字节 + 常量时间比较 + 时间戳窗口
- [ ] 给挂单设超时并主动 cancel，避免预扣额度被长期占用
- [ ] 周期性调 `/v1/orgs/usage` 与内部流水对账，兜住回调漏收
