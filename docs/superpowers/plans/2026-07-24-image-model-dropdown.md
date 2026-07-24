# 生图模型后台下拉选择 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 后台「生图渠道 → 模型」字段从自由文本框升级为「从 prism `/capabilities` 拉取的可用生图模型下拉 + 手输兜底」，支持逗号降级链多选。

**Architecture:** 新增后端 admin 接口 `GET /v1/admin/image-capabilities`，用 runtime_config 的生图凭据查 prism `/capabilities`、过滤 `type=image 且 channels 非空`、返回 `{code,label}` 清单（失败返回 available:false 不抛 500）。前端把「模型」文本框旁加一排可点 chip（点击加/移出 image_model 逗号链），文本框仍是数据源+手输兜底。保存逻辑不变。

**Tech Stack:** Python 3.12 / FastAPI / pytest（`service/tests/`）；React + TypeScript / Vite（`tsc -b` 构建校验）。

**Backward compat:** `image_model` 仍是逗号串走现有 PUT；capabilities 拉取失败时面板回落纯文本框，不阻塞保存。

---

## 文件结构

- Modify: `service/app.py` — 新增 `_fetch_image_capabilities()` helper + `GET /v1/admin/image-capabilities` 路由
- Modify: `service/schemas.py:266` 附近 — 新增 `ImageCapabilityItem` + `ImageCapabilitiesRead`
- Test: `service/tests/test_image_capabilities.py` — capabilities 过滤逻辑纯单测（mock 响应）
- Modify: `frontend/src/types.ts` — 新增 `ImageCapability` / `ImageCapabilitiesResponse`
- Modify: `frontend/src/api.ts:147` 附近 — 新增 `getImageCapabilities()`
- Modify: `frontend/src/lib/mockBackend.ts` — 补 `/v1/admin/image-capabilities` 桩
- Modify: `frontend/src/components/RuntimeConfigPanel.tsx` — 「模型」字段加 chip 选择区
- Modify: `frontend/src/hooks/useRuntimeConfig.ts` — 加载 capabilities

---

## Task 1: 后端 schema + 纯过滤函数

**Files:**
- Modify: `service/schemas.py`（RuntimeConfigRead 之前或之后加两个类）
- Modify: `service/app.py`（新增 `_filter_image_capabilities` 纯函数）
- Test: `service/tests/test_image_capabilities.py`

- [ ] **Step 1: 写失败测试**

创建 `service/tests/test_image_capabilities.py`（从仓库根目录跑，service/queue.py 会遮蔽标准库）：

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from service.app import _filter_image_capabilities


def _caps(*entries):
    return {"code": 0, "message": "success", "data": list(entries)}


def test_filters_image_type_with_channels():
    payload = _caps(
        {"type": "image", "code": "gpt_image2", "name": "GPT 画图",
         "channels": [{"model": "gpt-image-2"}]},
        {"type": "video", "code": "sora2", "name": "Sora", "channels": [{"model": "sora2"}]},
        {"type": "image", "code": "empty_one", "name": "空的", "channels": []},
    )
    result = _filter_image_capabilities(payload)
    assert result == [{"code": "gpt_image2", "label": "GPT 画图"}]


def test_label_falls_back_to_code():
    payload = _caps(
        {"type": "image", "code": "doubao_img", "name": "", "channels": [{"model": "x"}]},
    )
    assert _filter_image_capabilities(payload) == [{"code": "doubao_img", "label": "doubao_img"}]


def test_bad_shape_returns_empty():
    assert _filter_image_capabilities({}) == []
    assert _filter_image_capabilities({"data": "nope"}) == []
    assert _filter_image_capabilities(None) == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd F:/free/PythonProject/ppt-master && python -m pytest service/tests/test_image_capabilities.py -v`
Expected: FAIL — `cannot import name '_filter_image_capabilities'`

- [ ] **Step 3: 加 schema**

在 `service/schemas.py` 的 `RuntimeConfigRead` 类**之前**（约 266 行前）加：

```python
class ImageCapabilityItem(BaseModel):
    """One selectable image-generation model from the relay's capabilities."""

    code: str
    label: str


class ImageCapabilitiesRead(BaseModel):
    """Available image models for the admin model picker; degrades gracefully."""

    available: bool
    error: str | None = None
    models: list[ImageCapabilityItem] = []
```

- [ ] **Step 4: 加纯过滤函数**

在 `service/app.py` 的 `_runtime_config_read` 函数（约 1341 行）**之前**加：

```python
def _filter_image_capabilities(payload: object) -> list[dict[str, str]]:
    """Extract selectable image models from a relay /capabilities payload.

    Keeps only entries with type == "image" and at least one channel. Label
    falls back to the code when name is blank. Any unexpected shape yields [].
    """
    if not isinstance(payload, dict):
        return []
    entries = payload.get("data")
    if not isinstance(entries, list):
        return []
    models: list[dict[str, str]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("type") != "image":
            continue
        channels = entry.get("channels")
        if not isinstance(channels, list) or not channels:
            continue
        code = entry.get("code")
        if not isinstance(code, str) or not code.strip():
            continue
        name = entry.get("name")
        label = name.strip() if isinstance(name, str) and name.strip() else code
        models.append({"code": code, "label": label})
    return models
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd F:/free/PythonProject/ppt-master && python -m pytest service/tests/test_image_capabilities.py -v`
Expected: PASS（3 passed）

- [ ] **Step 6: 提交**

```bash
git add service/schemas.py service/app.py service/tests/test_image_capabilities.py
git commit -m "feat(images): add image capabilities filter and schema"
```

---

## Task 2: 后端接口 `GET /v1/admin/image-capabilities`

**Files:**
- Modify: `service/app.py`（新增路由，紧跟 `admin_get_runtime_config` 之后，约 1360 行）

用 runtime_config 的生图凭据查 prism `/capabilities`，任何失败返回 `available:false` 不抛 500。

- [ ] **Step 1: 确认 app.py 顶部已 import**

检查 `service/app.py` 顶部 import 区是否有 `import urllib.request` / `import urllib.error` / `import json`。若缺，补上（`json` 大概率已有；`urllib` 可能没有）。用：

```bash
cd F:/free/PythonProject/ppt-master && grep -n "^import json\|^import urllib\|^from urllib" service/app.py
```

缺什么在 import 区补什么。同时确认 `ImageCapabilitiesRead` 已从 schemas 导入——在 app.py 现有的 `from service.schemas import (...)` 块里加 `ImageCapabilitiesRead`（`RuntimeConfigRead` 已在该块，紧邻加）。

- [ ] **Step 2: 加接口**

在 `service/app.py` 的 `admin_get_runtime_config` 路由函数（约 1355-1360 行）**之后**加：

```python
@app.get("/v1/admin/image-capabilities", response_model=ImageCapabilitiesRead)
async def admin_get_image_capabilities(request: Request, admin: AdminUser) -> dict:
    """List selectable image models from the relay's /capabilities endpoint.

    Uses the runtime-config image credentials (never .env). Any failure degrades
    to available:false so the admin panel falls back to manual model entry.
    """
    config = await request.app.state.runtime_config_repository.get()
    base = (config.image_base_url or "").rstrip("/")
    key = config.image_api_key or ""
    if not base or not key:
        return {"available": False, "error": "生图渠道未配置", "models": []}
    url = base + "/capabilities"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            payload = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return {"available": False, "error": f"渠道返回 {exc.code}", "models": []}
    except Exception:  # noqa: BLE001 — network/JSON errors all degrade the same way
        return {"available": False, "error": "无法连接生图渠道", "models": []}
    models = _filter_image_capabilities(payload)
    return {"available": True, "error": None, "models": models}
```

- [ ] **Step 3: 语法自检**

Run: `cd F:/free/PythonProject/ppt-master && python -c "import ast; ast.parse(open('service/app.py',encoding='utf-8').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 4: 跑现有单测确认没破坏**

Run: `cd F:/free/PythonProject/ppt-master && python -m pytest service/tests/ -q`
Expected: PASS（含 test_image_capabilities 与既有测试）

- [ ] **Step 5: 提交**

```bash
git add service/app.py
git commit -m "feat(images): add admin image-capabilities endpoint"
```

---

## Task 3: 前端 types + api + mock

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/api.ts`（约 147 行，`updateRuntimeConfig` 之后）
- Modify: `frontend/src/lib/mockBackend.ts`

- [ ] **Step 1: 加类型**

在 `frontend/src/types.ts` 的 `RuntimeConfigUpdate` 附近（约 140 行后）加：

```typescript
export interface ImageCapability {
  code: string;
  label: string;
}

export interface ImageCapabilitiesResponse {
  available: boolean;
  error: string | null;
  models: ImageCapability[];
}
```

- [ ] **Step 2: 加 api 方法**

在 `frontend/src/api.ts` 的 `updateRuntimeConfig`（约 142-147 行）**之后**加。先确认文件顶部 import 的类型里加上 `ImageCapabilitiesResponse`（`RuntimeConfig` / `RuntimeConfigUpdate` 已 import，在同一处加）：

```typescript
  getImageCapabilities(): Promise<ImageCapabilitiesResponse> {
    return this.request<ImageCapabilitiesResponse>(
      "/v1/admin/image-capabilities",
    );
  }
```

- [ ] **Step 3: 补 mock 桩**

在 `frontend/src/lib/mockBackend.ts` 里，找到 `if (path === "/v1/admin/runtime-config") return json(runtimeConfig);` 那行（约 332 行），在其后加：

```typescript
  if (path === "/v1/admin/image-capabilities")
    return json({
      available: true,
      error: null,
      models: [
        { code: "gpt_image2", label: "GPT 画图" },
        { code: "doubao_img", label: "豆包画图" },
      ],
    });
```

- [ ] **Step 4: 构建校验**

Run: `cd frontend && npx tsc -b`
Expected: exit 0（无类型错误）

- [ ] **Step 5: 提交**

```bash
git add frontend/src/types.ts frontend/src/api.ts frontend/src/lib/mockBackend.ts
git commit -m "feat(frontend): add image capabilities api client and types"
```

---

## Task 4: 前端 hook 加载 capabilities

**Files:**
- Modify: `frontend/src/hooks/useRuntimeConfig.ts`

在现有 hook 里加载可用生图模型，暴露给面板。

- [ ] **Step 1: 加 state + 加载**

在 `useRuntimeConfig` 里：

顶部 import 加 `ImageCapability`：把第 4 行改为
```typescript
import type { ImageCapability, RuntimeConfig, RuntimeConfigUpdate } from "../types";
```

在 `const [saved, setSaved] = useState(false);`（约 15 行）之后加：
```typescript
  const [imageModels, setImageModels] = useState<ImageCapability[]>([]);
```

在 `load` 的 `try` 块里，把 `setConfig(await apiClient.getRuntimeConfig());` 改为：
```typescript
      setConfig(await apiClient.getRuntimeConfig());
      try {
        const caps = await apiClient.getImageCapabilities();
        setImageModels(caps.available ? caps.models : []);
      } catch {
        setImageModels([]); // capabilities are optional; panel falls back to manual entry
      }
```

- [ ] **Step 2: 暴露 imageModels**

在 return 对象里（约 79-95 行）加一行 `imageModels,`（放在 `config,` 附近即可）。

- [ ] **Step 3: 构建校验**

Run: `cd frontend && npx tsc -b`
Expected: exit 0

- [ ] **Step 4: 提交**

```bash
git add frontend/src/hooks/useRuntimeConfig.ts
git commit -m "feat(frontend): load image capabilities in runtime config hook"
```

---

## Task 5: 前端面板加 chip 选择区

**Files:**
- Modify: `frontend/src/components/RuntimeConfigPanel.tsx`

「生图渠道 → 模型」文本框下方加一排可点 chip：点击把 code 加/移出 `image_model` 逗号链。文本框仍是数据源+手输兜底。

- [ ] **Step 1: 加 chip 交互 + 渲染**

在 `RuntimeConfigPanel` 组件里，把 `const config = rc.config;`（约 90 行）之后加一个辅助：

```typescript
  const chain = config.image_model
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean);

  const toggleModel = (code: string) => {
    const next = chain.includes(code)
      ? chain.filter((item) => item !== code)
      : [...chain, code];
    rc.setConfig({ ...config, image_model: next.join(",") });
  };
```

然后在「生图渠道」section 的「模型」`<label>`（约 158-167 行，含 `value={config.image_model}` 的那个）**之后**加 chip 区：

```tsx
          {rc.imageModels.length > 0 && (
            <div className="model-chips">
              {rc.imageModels.map((model) => (
                <button
                  type="button"
                  key={model.code}
                  className={
                    chain.includes(model.code)
                      ? "model-chip model-chip-active"
                      : "model-chip"
                  }
                  onClick={() => toggleModel(model.code)}
                  title={model.code}
                >
                  {chain.includes(model.code) && <Check size={13} />}
                  <span>{model.label}</span>
                </button>
              ))}
            </div>
          )}
```

`Check` 已从 lucide-react 导入（文件顶部已有）。model-chips / model-chip 是新 CSS 类——见 Step 2。

- [ ] **Step 2: 加 CSS**

在 `frontend/src/styles.css` 末尾加（复用现有配色变量，参考已有 `.user-row-actions` 等的风格；若不确定变量名，用中性值）：

```css
.model-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 6px;
}

.model-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border: 1px solid var(--border, #d0d7de);
  border-radius: 14px;
  background: transparent;
  cursor: pointer;
  font-size: 13px;
}

.model-chip-active {
  border-color: var(--accent, #1a3a6b);
  background: var(--secondary-bg, #f4f6f8);
}
```

- [ ] **Step 3: 更新「模型」标签提示手输兜底**

把「模型」`<label>` 里的 `<span>模型</span>` 改为 `<span>模型（可点选或手输，逗号分隔为降级链）</span>`。

- [ ] **Step 4: 构建校验**

Run: `cd frontend && npx tsc -b`
Expected: exit 0

- [ ] **Step 5: 提交**

```bash
git add frontend/src/components/RuntimeConfigPanel.tsx frontend/src/styles.css
git commit -m "feat(frontend): add clickable image model chips to runtime config panel"
```

---

## Task 6: 部署 + 验证

**Files:** 无代码改动（部署操作）

- [ ] **Step 1: 本地构建前端**

Run: `cd frontend && npm run build`（记录新 js hash）

- [ ] **Step 2: 传后端 + 前端 dist 到生产 `/opt/ppt-master`**

paramiko scp `service/app.py`、`service/schemas.py` 到 `/opt/ppt-master/service/`；前端 dist 打包传到 `/www/wwwroot/ppt.mirainya.icu`（保留 .user.ini）。先备份到 `/var/backups/ppt-master/predeploy_<ts>`。

- [ ] **Step 3: 重建容器**

```bash
cd /opt/ppt-master && docker compose -f compose.linux-4g.yaml up -d --build api worker
```
Expected: 双 healthy。

- [ ] **Step 4: 线上验证**

管理员登录，打开运行时配置面板：确认「生图渠道 → 模型」下方出现可点 chip（gpt_image2 / doubao_img / NanoBanana 等真实模型），点选拼成逗号链、保存成功。或用容器内 curl 打 `/v1/admin/image-capabilities` 确认返回真实模型清单。

---

## 自检结果

- **Spec 覆盖**：新接口(T1/T2)、过滤 image+channels 非空(T1)、失败 available:false 不抛 500(T2)、前端 chip 多选+手输兜底(T5)、hook 加载(T4)、api/types/mock(T3)、数据源仍 image_model 串走现有 PUT(T5 不改保存)、部署(T6)——全覆盖。
- **占位符扫描**：无 TBD；每步含真实代码/命令。
- **类型一致**：`_filter_image_capabilities`、`ImageCapabilitiesRead`/`ImageCapabilityItem`（后端）、`ImageCapability`/`ImageCapabilitiesResponse`（前端）、`getImageCapabilities`、`imageModels`、`toggleModel` 跨任务命名一致。
