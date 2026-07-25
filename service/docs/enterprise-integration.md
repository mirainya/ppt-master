# 企业接入指南（B2B API）

面向在自家系统中集成 PPT Master 生成能力的第三方企业。终端用户无需感知本服务；企业后端用组织凭证调用，并可按终端用户单独计量。

设计背景见 [`billing-design.md`](./billing-design.md)。

## 1. 开通（由服务方管理员完成）

企业无需自助注册。服务方管理员为每家企业开户、签发组织 API Key、充值：

```bash
# 建组织（返回 org id）
curl -X POST https://<host>/v1/admin/orgs \
  -H 'Content-Type: application/json' -b admin_session \
  -d '{"name":"Acme Inc","slug":"acme"}'

# 签发组织 API Key（明文仅返回一次，请妥善保存）
curl -X POST https://<host>/v1/admin/orgs/<org_id>/keys \
  -H 'Content-Type: application/json' -b admin_session \
  -d '{"name":"prod"}'

# 预付充值
curl -X POST https://<host>/v1/admin/orgs/<org_id>/credits \
  -H 'Content-Type: application/json' -b admin_session \
  -d '{"amount":1000}'
```

组织 Key 形如 `pptm_org_xxxxx`，企业将其保存在自己后端，切勿下发到浏览器或客户端。

## 2. 认证与终端用户透传

企业后端调用业务接口时：

- `Authorization: Bearer pptm_org_xxxxx` — 组织凭证
- `X-End-User-Id: <企业侧用户ID>` — 可选，透传企业自己的终端用户标识

同一 `X-End-User-Id` 会稳定映射到一条隔离的用户空间：不同终端用户互相看不到对方的任务，用量分别计量。不带该头时，任务归属组织的默认服务账号。

## 3. 借用工作台（一次性 SSO 票据）

第三方终端用户可以直接进入 PPT Master 工作台，无需再次输入用户名和密码。组织 API Key
始终保存在第三方后端，不发送到浏览器。

第三方后端先为当前终端用户申请一次性票据：

```bash
curl -X POST https://<host>/v1/auth/org-tickets \
  -H 'Authorization: Bearer pptm_org_xxxxx' \
  -H 'X-End-User-Id: cust-42'
```

返回：

```json
{"ticket":"<one-time-ticket>","expires_in":60}
```

第三方前端随后跳转到：

```text
https://<host>/#sso_ticket=<one-time-ticket>
```

票据放在 URL Fragment 中，不会随首页请求进入服务器访问日志。工作台会调用
`POST /v1/auth/org-tickets/consume` 原子消费票据，并设置现有 HttpOnly Session Cookie。
票据有效期为 60 秒且只能使用一次；登录身份继续绑定原
`org_id + X-End-User-Id`，任务隔离、预扣和用量统计均保持不变。组织被停用后，已有
工作台 Session 也会立即失效。

## 4. 生成 PPT

```bash
curl -X POST https://<host>/v1/jobs \
  -H 'Authorization: Bearer pptm_org_xxxxx' \
  -H 'X-End-User-Id: cust-42' \
  -F 'prompt=用这份材料做一份 PPT' \
  -F 'route=generate_pptx' \
  -F 'files=@report.pdf'
# → 202 {"id":"<job_id>","status":"queued", ...}
```

任务是异步的。建任务时会按 `hold_amount` 预扣组织余额；余额不足返回 `402`。
提交确认或再次修订也会为下一轮按同一 `hold_amount` 预扣；余额不足时请求返回 `402`，原确认状态不变。

### 查询进度

- 轮询：`GET /v1/jobs/<job_id>`（返回 `status`/`progress`）
- 实时：`GET /v1/jobs/<job_id>/events`（SSE，支持 `Last-Event-ID` 断点续传）

关键状态：`queued → intake → awaiting_confirmation → planning → executing → succeeded`（或 `failed`）。`generate_pptx` 在 `awaiting_confirmation` 处会阻塞等待确认。

### 确认方案 / 修订

```bash
# 确认（approved=true）或要求修改（approved=false + message）
curl -X POST https://<host>/v1/jobs/<job_id>/confirmation \
  -H 'Authorization: Bearer pptm_org_xxxxx' -H 'X-End-User-Id: cust-42' \
  -H 'Content-Type: application/json' \
  -d '{"approved":true,"message":""}'
```

### 下载产物

```bash
curl https://<host>/v1/jobs/<job_id>/artifacts \
  -H 'Authorization: Bearer pptm_org_xxxxx' -H 'X-End-User-Id: cust-42'
# 逐个下载
curl -OJ https://<host>/v1/jobs/<job_id>/artifacts/<artifact_id>/download \
  -H 'Authorization: Bearer pptm_org_xxxxx' -H 'X-End-User-Id: cust-42'
```

## 5. 计量与计费

本服务按 **token + 生图** 的真实成本扣组织预付余额（第 1 层）。企业按下面的用量凭证，用自己的定价向终端用户计费（第 2 层，本服务不参与）。

### 单任务用量凭证

```bash
curl https://<host>/v1/jobs/<job_id>/usage \
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

- `status`：`partial`（任务或修订进行中）/ `final`（彻底完成）。**请在 `final` 后再对终端用户结账**——修订会追加用量。
- `usage`：原始计量维度，企业按需定价。
- `our_charge.credits`：本服务对该任务扣组织的真实成本，供对账参考。

### 各计量维度的累计口径

修订会重跑部分页面，各维度的累加方式并不相同，按页定价前请先读这一节。

| 维度 | 口径 | 修订重做 3 页时 |
|---|---|---|
| `input_tokens` / `output_tokens` | 每轮实际消耗**逐轮累加** | 追加该轮 token |
| `images` | 磁盘生图数的**增量**累加 | 重新生图才追加 |
| `pages` | 磁盘当前页数的**最高水位** | 不变 |

`pages` 取的是产出目录里页文件的数量，写入时只记 `max(0, 当前页数 - 已记录总和)`。
所以 9 页的稿子重做第 4/5/6 页，`pages` 仍是 **9**，不是 12；页数减少（9 页删到 7 页）
时 `pages` 也**不会回退**，仍是 9。要按最终交付页数计费，请在任务终态时自行读产物页数。

`pages` **不参与**本服务扣费，第 1 层只按 token + 生图结算。因此修订虽然不涨 `pages`，
`our_charge.credits` 仍会上升。按页向终端用户定价意味着**修订对用户免费而成本由企业承担**；
若希望修订计费，请改用 `our_charge.credits` 乘系数，或自行统计修订轮次。

### 按终端用户聚合（出账）

```bash
curl 'https://<host>/v1/orgs/usage?end_user_id=cust-42&since=2026-07-01T00:00:00Z' \
  -H 'Authorization: Bearer pptm_org_xxxxx'
```

返回该组织每个终端用户的用量与成本汇总，用于周期性出账。

**鉴权范围**：只有携带组织 API Key 才能读取整个组织的汇总。工作台 Session（含 SSO 票据登录）
调用该接口时会被强制限定为**调用者自己**的终端用户；显式传入他人的 `end_user_id` 返回 `403`。
出账请始终在第三方后端用组织 Key 调用。

## 6. 用量回调（Webhook）

上一节的接口是 Pull，最快也只能轮询。若需要实时管住企业内部某个终端用户的消耗，用回调：
服务方在**每轮结算后立刻**把用量推给企业接口，企业自行累计，超限时调 cancel 停任务。

### 开通

回调地址与签名密钥由**服务方管理员**代配（不开放企业自助，回调地址是服务端的出站目标）：

```bash
curl -X PUT https://<host>/v1/admin/orgs/<org_id>/webhook \
  -H 'Content-Type: application/json' -b admin_session \
  -d '{"callback_url":"https://acme.example.com/pptm/usage","enabled":true}'
# → 返回配置，并在首次创建或 rotate_secret=true 时带一次性明文 secret

# 录入后立刻验证连通性（该测试事件不进投递记录）
curl -X POST https://<host>/v1/admin/orgs/<org_id>/webhook/test -b admin_session
```

回调地址必须是**公网 HTTPS**。服务端在每次发送前重新解析域名，拒绝环回、私有、链路本地
（含 `169.254.169.254`）等地址，并把连接钉在已校验的 IP 上，因此内网地址一律发不出去。
重定向不跟随，3xx 视为失败。

企业侧可只读自查（组织 API Key，工作台 Session 无权访问）：

```bash
curl https://<host>/v1/orgs/webhook -H 'Authorization: Bearer pptm_org_xxxxx'
curl 'https://<host>/v1/orgs/webhook/deliveries?limit=20' \
  -H 'Authorization: Bearer pptm_org_xxxxx'
```

### 事件

| 事件 | 何时发出 | `delta` | `usage_status` |
|---|---|---|---|
| `usage.turn` | 每轮 agent turn 计费落库后 | 本轮增量 | `partial` |
| `usage.final` | 任务进入 succeeded/failed/cancelled | `null` | `final` |

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

`delta.*` 与 `job_total.*` 的字段名与 `GET /v1/jobs/{id}/usage` 完全一致，§5 的累计口径表
（尤其 `pages` 是最高水位）直接适用。**`job_total` 是权威值，不要靠累加 `delta` 求总量** ——
投递是至少一次且不保证顺序。`usage.final` 的 `delta` 是 `null` 而非全零：终态事件是完成标记，
不是一轮零消耗。

任务终态后若被 resume 续做，再次终态会发出**新的** `usage.final`（幂等键含已计费轮数），
`job_total` 是续做后的新总量。

### 验签

请求头：

| Header | 说明 |
|---|---|
| `X-PPTM-Event-Id` | 事件 id，跨重试不变 —— **用它做幂等去重** |
| `X-PPTM-Timestamp` | Unix 秒，每次尝试都变 |
| `X-PPTM-Signature` | `sha256=<hex>` |

签名是 `HMAC-SHA256(secret, f"{timestamp}." + body)`。务必对**收到的原始 body 字节**验签，
不要反序列化再重新序列化：

```python
import hashlib, hmac, time

def verify(secret: str, timestamp: str, signature: str, body: bytes) -> bool:
    if abs(time.time() - int(timestamp)) > 300:   # 防重放
        return False
    expected = hmac.new(
        secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)
```

### 重试与死信

返回 2xx 视为成功。5xx、429、408、网络错误按 `10s → 30s → 2m → 10m → 1h → 6h`（其后维持 6h）
退避，共 8 次；其余 4xx 与回调地址校验失败**立即死信**不再重试。死信保留在投递记录里，
`dead_at` 有值、`last_error` 记明原因。

### 超限闭环

```bash
# 累计超限时用组织 Key 停掉该任务
curl -X POST https://<host>/v1/jobs/<job_id>/cancel \
  -H 'Authorization: Bearer pptm_org_xxxxx' -H 'X-End-User-Id: cust-42'
```

**坑**：`end_user_id` 为 `__service__` 时（企业建任务未带 `X-End-User-Id`）**不要**回传该值，
它是保留字会返回 `400`；此时省略该头即命中默认服务账号。

注意 cancel 只停当前任务，该终端用户仍可再建新任务（工作台 Session 有效期内）。

## 7. 数据隔离说明

- 逻辑隔离：企业之间、企业内终端用户之间的任务与产物互相不可见（基于所有者鉴权）。
- 物理存储未按组织分目录（同一运行目录混放），仅靠接口鉴权隔离。对物理隔离有合规要求的场景需另行约定。

## 8. Python 示例

```python
import httpx

BASE = "https://<host>"
HEADERS = {"Authorization": "Bearer pptm_org_xxxxx", "X-End-User-Id": "cust-42"}

with httpx.Client(base_url=BASE, headers=HEADERS) as client:
    job = client.post(
        "/v1/jobs",
        data={"prompt": "用这份材料做一份 PPT", "route": "generate_pptx"},
        files={"files": open("report.pdf", "rb")},
    ).json()
    job_id = job["id"]

    # 轮询到完成（省略确认阶段处理）
    # ...

    usage = client.get(f"/v1/jobs/{job_id}/usage").json()
    print(usage["usage"], usage["our_charge"])
```
