# 生图模型后台下拉选择（capabilities 自动拉取）设计

- 日期：2026-07-24
- 状态：待确认
- 相关：`service/app.py`、`service/schemas.py`、`frontend/src/components/RuntimeConfigPanel.tsx`、`frontend/src/hooks/useRuntimeConfig.ts`、`frontend/src/api.ts`、`frontend/src/types.ts`

## 背景与目标

生图配置**早已是后台可配**（`RuntimeConfig` 存库、`/v1/admin/runtime-config` 读写、worker 热重载、`RuntimeConfigPanel` 有「模型」框）。但「模型」是**自由文本框**——管理员不知道 prism 后面有哪些生图模型，只能手输猜。

已探明：prism 的生图模型清单在 `GET {image_base_url}/capabilities`（不是标准 `/models`，后者只返回文本模型）。生图路由认的是 capabilities 条目的 **`code`** 字段（实测当前 `image_model=gpt_image2` 正好等于某条 `code`）。

**目标**：把「模型」框升级为**下拉选择（从 capabilities 拉取可用生图模型）+ 手输兜底**，支持逗号降级链多选。

## 决策汇总（已确认）

1. **筛选**：只列 `type=="image"` 且 `channels` 非空的条目（过滤 video 和未配好的）。
2. **手输兜底**：下拉为主，保留手动输入。capabilities 拉取失败 / prism 新模型未被识别时，管理员仍能手填。
3. **降级链**：`image_model` 仍是逗号分隔字符串（第一个主力）；下拉支持挑多个拼成链，顺序即优先级。

## capabilities 响应结构（实测）

```json
{ "code": 0, "message": "success", "data": [
  { "type": "image", "code": "gpt_image2", "name": "...",
    "channels": [ { "model": "gpt-image-2-[1.5k]", ... } ], "param_schema": {...} },
  { "type": "video", "code": "sora2", ... }
] }
```
- 提取字段：`code`（填入 image_model 的值）、`name`（下拉显示的友好名）、`channels`（判空）。
- 当前可用 image 模型：`gpt_image2`、`doubao_img`、`duomiapi-gpt画图`、`grok-imagine-image`、`NanoBanana`。

## 后端设计

**新接口** `GET /v1/admin/image-capabilities`（admin-only，仿 `admin_get_runtime_config`）：

1. 从 `runtime_config_repository.get()` 拿 `image_base_url` + `image_api_key`（复用已解密的运行时配置，不碰 .env）。
2. 无凭据 → 返回 `{ "available": false, "error": "生图渠道未配置", "models": [] }`。
3. 有凭据 → 请求 `{image_base_url}/capabilities`（Bearer image_api_key，超时 15s）。
4. 过滤 `entry.type == "image" and entry.channels`（channels 非空）→ 映射为 `{ "code": ..., "label": entry.name or entry.code }`。
5. 任何异常（网络/非 200/JSON 坏）→ `{ "available": false, "error": "<简短原因>", "models": [] }`，**不抛 500**（让前端优雅回落手输）。

**schema**（`schemas.py`）：新增 `ImageCapabilityItem { code: str, label: str }` 和 `ImageCapabilitiesRead { available: bool, error: str | None, models: list[ImageCapabilityItem] }`。

**安全**：绝不返回密钥；只回 code+label。接口走 `AdminUser` 守卫。

## 前端设计

`RuntimeConfigPanel` 的「生图渠道 → 模型」字段升级（`image_model` 仍是逗号串，作单一数据源）：

- 面板加载时调 `GET /v1/admin/image-capabilities`（经 `useRuntimeConfig` 或独立小 hook）。
- **可用模型区**：把返回的 models 渲染成一组可点 chip/checkbox。点击 = 把该 `code` 加入/移出当前 `image_model` 逗号链（保持顺序，第一个是主力）。已在链中的高亮。
- **手输框**：保留现有文本框作为 source-of-truth，可直接编辑（手输兜底 + 调整顺序 + 去重）。chip 只是往这个框里加/减 code。
- `available == false`：只显示文本框 + 一行提示「无法自动获取模型列表（<error>），可手动输入」。
- 不改保存逻辑：最终提交的仍是 `image_model` 字符串，走现有 `/v1/admin/runtime-config` PUT。

**新增**：`api.ts` 加 `getImageCapabilities()`；`types.ts` 加 `ImageCapability` / `ImageCapabilitiesResponse`；mockBackend 补桩。

## 不做（YAGNI）

- 不解析 `param_schema`（尺寸/质量等）——本次只解决"模型名单可选"，尺寸仍手填。
- 不缓存 capabilities（每次开面板实时拉，prism 改了立刻反映）。
- 不动 video 类型。
