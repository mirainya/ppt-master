# 生图多模型降级 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `PPT_IMAGE_MODEL` 支持逗号分隔的降级链，主力模型遇 429/5xx/超时时自动切换到下一个备选模型，全部失败才报错。

**Architecture:** 降级逻辑全落在 `service/image_mcp.py`（service 层，不碰上游 skill，避免 merge 冲突）。不复用会吞限流的 `image_gen._run_manifest`，改在 image_mcp 内写自己的并发循环，逐模型调 `backend.generate(max_retries=0)`，任何异常都当本项失败并交给下一个模型。降级轨迹写进现有 `control/image_generation.json` audit。

**Tech Stack:** Python 3.12、pytest（`service/tests/`，`tmp_path` fixture）、`concurrent.futures`、FastMCP。

**Backward compat:** `PPT_IMAGE_MODEL` 只填一个值 = 现状不变；compose 白名单、config schema 不变结构，只是值可带逗号。

---

## 文件结构

- Modify: `service/image_mcp.py` — 解析模型列表、放宽 manifest 校验、新增降级并发循环 `_run_with_fallback`、audit 记录降级轨迹
- Modify: `service/config.py:122` — `image_model` 保持读取（消费方仍拿整串），`validate()` 校验列表非空
- Modify: `.env.example:245` — 文档说明逗号列表
- Test: `service/tests/test_image_fallback.py` — 降级循环纯逻辑单测（mock backend，不依赖网络）

**并发度**：复用现有 `PPT_IMAGE_CONCURRENCY` / `_image_concurrency()`，行为与现状一致。

---

## Task 1: 解析 PPT_IMAGE_MODEL 为模型列表

**Files:**
- Modify: `service/image_mcp.py`（新增 `_model_list()` helper）
- Test: `service/tests/test_image_fallback.py`

- [ ] **Step 1: 写失败测试**

```python
# service/tests/test_image_fallback.py
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import image_mcp


def test_model_list_splits_comma(monkeypatch):
    monkeypatch.setenv("PPT_IMAGE_MODEL", "model-a, model-b ,model-c")
    assert image_mcp._model_list() == ["model-a", "model-b", "model-c"]


def test_model_list_single(monkeypatch):
    monkeypatch.setenv("PPT_IMAGE_MODEL", "gpt_image2")
    assert image_mcp._model_list() == ["gpt_image2"]


def test_model_list_empty_raises(monkeypatch):
    monkeypatch.delenv("PPT_IMAGE_MODEL", raising=False)
    try:
        image_mcp._model_list()
        assert False, "should raise"
    except RuntimeError:
        pass
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd service && python -m pytest tests/test_image_fallback.py -v`
Expected: FAIL — `AttributeError: module 'image_mcp' has no attribute '_model_list'`

- [ ] **Step 3: 实现 `_model_list()`**

在 `service/image_mcp.py` 的 `_required_env` 之后加：

```python
def _model_list() -> list[str]:
    """Parse PPT_IMAGE_MODEL into an ordered fallback chain (first = primary)."""
    raw = _required_env("PPT_IMAGE_MODEL")
    models = [part.strip() for part in raw.split(",") if part.strip()]
    if not models:
        raise RuntimeError("Image generation is not configured: PPT_IMAGE_MODEL is empty")
    return models
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd service && python -m pytest tests/test_image_fallback.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 提交**

```bash
git add service/image_mcp.py service/tests/test_image_fallback.py
git commit -m "feat(images): parse PPT_IMAGE_MODEL as fallback chain"
```

---

## Task 2: 降级并发循环 `_run_with_fallback`

**Files:**
- Modify: `service/image_mcp.py`（新增 `_run_with_fallback()`）
- Test: `service/tests/test_image_fallback.py`

这是核心：逐模型跑，每模型并发处理 Pending/Failed 项，调 `backend.generate(max_retries=0)`；成功标 `Generated`，失败标 `Failed` 并记 `last_error` + `last_model`；换下一个模型时只重跑仍是 Failed 的项。返回 `(ok, failed, model_trace)`，`model_trace` 是 `{filename: 最终成功的模型}`。

- [ ] **Step 1: 写失败测试（用 fake backend 模拟主力挂、备选成功）**

```python
def _manifest(*names):
    return {"items": [
        {"filename": n, "prompt": "p", "aspect_ratio": "16:9",
         "image_size": "1K", "status": "Pending"} for n in names
    ]}


class _FakeBackend:
    """generate() fails for `failing_models`, succeeds otherwise."""
    def __init__(self, failing_models, exc):
        self.failing_models = set(failing_models)
        self.exc = exc
        self.calls = []

    def generate(self, *, prompt, aspect_ratio, image_size, output_dir,
                 filename, model, max_retries):
        self.calls.append((filename, model))
        if model in self.failing_models:
            raise self.exc
        return f"{output_dir}/{filename}.png"


def test_fallback_switches_model_on_failure(tmp_path):
    payload = _manifest("a.png", "b.png")
    backend = _FakeBackend(failing_models=["model-a"], exc=RuntimeError("503 Service Unavailable"))
    ok, failed, trace = image_mcp._run_with_fallback(
        payload, backend, models=["model-a", "model-b"],
        concurrency=2, output_dir=str(tmp_path),
    )
    assert ok == 2 and failed == 0
    assert trace == {"a.png": "model-b", "b.png": "model-b"}
    assert all(it["status"] == "Generated" for it in payload["items"])


def test_fallback_all_models_fail(tmp_path):
    payload = _manifest("a.png")
    backend = _FakeBackend(failing_models=["m1", "m2"], exc=RuntimeError("503"))
    ok, failed, trace = image_mcp._run_with_fallback(
        payload, backend, models=["m1", "m2"],
        concurrency=1, output_dir=str(tmp_path),
    )
    assert ok == 0 and failed == 1
    assert payload["items"][0]["status"] == "Failed"
    assert "503" in payload["items"][0]["last_error"]


def test_fallback_primary_success_skips_backups(tmp_path):
    payload = _manifest("a.png")
    backend = _FakeBackend(failing_models=[], exc=RuntimeError("x"))
    ok, failed, trace = image_mcp._run_with_fallback(
        payload, backend, models=["m1", "m2"],
        concurrency=1, output_dir=str(tmp_path),
    )
    assert ok == 1 and failed == 0
    # backup model never called
    assert all(model == "m1" for _, model in backend.calls)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd service && python -m pytest tests/test_image_fallback.py -v -k fallback`
Expected: FAIL — `no attribute '_run_with_fallback'`

- [ ] **Step 3: 实现 `_run_with_fallback()`**

在 `service/image_mcp.py` 顶部 import 区加 `import concurrent.futures` 和 `import threading`，然后加：

```python
def _run_with_fallback(
    payload: dict[str, Any],
    backend: Any,
    *,
    models: list[str],
    concurrency: int,
    output_dir: str,
) -> tuple[int, int, dict[str, str]]:
    """Try each model in order; any error on an item falls through to the next model.

    max_retries=0 means rate-limit/5xx/timeout all surface immediately so the
    outer model loop switches without waiting. Only items still Failed after the
    last model count as failures. Returns (ok, failed, {filename: winning_model}).
    """
    items = payload["items"]
    lock = threading.Lock()
    model_trace: dict[str, str] = {}

    def _one(idx: int, model: str):
        item = items[idx]
        try:
            backend.generate(
                prompt=item["prompt"],
                aspect_ratio=item["aspect_ratio"],
                image_size=item.get("image_size", "1K"),
                output_dir=output_dir,
                filename=Path(item["filename"]).stem,
                model=model,
                max_retries=0,
            )
            return idx, None
        except Exception as exc:  # noqa: BLE001 — backend raises arbitrary types
            return idx, exc

    for model in models:
        pending = [
            i for i, it in enumerate(items)
            if it["status"] in {"Pending", "Failed"}
        ]
        if not pending:
            break
        batch = max(1, min(concurrency, len(pending)))
        with concurrent.futures.ThreadPoolExecutor(max_workers=batch) as ex:
            futures = [ex.submit(_one, i, model) for i in pending]
            for fut in concurrent.futures.as_completed(futures):
                idx, exc = fut.result()
                item = items[idx]
                with lock:
                    if exc is None:
                        item["status"] = "Generated"
                        item.pop("last_error", None)
                        model_trace[item["filename"]] = model
                    else:
                        item["status"] = "Failed"
                        item["last_error"] = str(exc)[:500]
                        item["last_model"] = model

    ok = sum(1 for it in items if it["status"] == "Generated")
    failed = sum(1 for it in items if it["status"] == "Failed")
    return ok, failed, model_trace
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd service && python -m pytest tests/test_image_fallback.py -v`
Expected: PASS（全部通过）

- [ ] **Step 5: 提交**

```bash
git add service/image_mcp.py service/tests/test_image_fallback.py
git commit -m "feat(images): add per-item model fallback loop"
```

---

## Task 3: 放宽 manifest 校验（允许列表中任一模型）

**Files:**
- Modify: `service/image_mcp.py:93-131`（`_validate_manifest`）

现状 `_validate_manifest(path, model)` 在 `item_model != model` 时 raise。降级链下，item 默认不带 model（`item.get("model", model)` 回落到主力），所以现有 manifest 天然通过。只需把签名的单 `model` 换成 `models: list[str]`，允许 item 指定链中任一模型。

- [ ] **Step 1: 改签名与校验行**

把 `_validate_manifest` 的签名和最后那段模型校验改为：

```python
def _validate_manifest(path: Path, models: list[str]) -> dict[str, Any]:
```

并把原本的：

```python
        item_model = str(item.get("model", model)).strip()
        ...
        if item_model != model:
            raise ValueError(f"Image item {index} cannot override the configured model")
```

改为（`model` → `models[0]` 作为默认，允许链中任一值）：

```python
        item_model = str(item.get("model", models[0])).strip()
        ...
        if item_model not in models:
            raise ValueError(
                f"Image item {index} model must be one of the configured PPT_IMAGE_MODEL values"
            )
```

- [ ] **Step 2: 跑现有单测确认没破坏**

Run: `cd service && python -m pytest tests/ -v`
Expected: PASS（含 test_storage_purge 与新 fallback 测试）

- [ ] **Step 3: 提交**

```bash
git add service/image_mcp.py
git commit -m "fix(images): validate manifest model against fallback chain"
```

---

## Task 4: 接入 `_generate_image_manifest` + audit 降级轨迹

**Files:**
- Modify: `service/image_mcp.py:197-299`（`_generate_image_manifest`）

把单模型路径换成降级链：解析 `models`、校验用 `models`、跑 `_run_with_fallback` 取代 `_run_manifest`，audit 里记 `models` 链和 `model_trace`。

- [ ] **Step 1: 改 `_generate_image_manifest` 的模型解析与运行段**

把开头的：

```python
    model = _required_env("PPT_IMAGE_MODEL")
```

改为：

```python
    models = _model_list()
    model = models[0]  # primary, for audit/env defaults and result message
```

把 `payload = _validate_manifest(manifest, model)` 改为 `payload = _validate_manifest(manifest, models)`。

在 `audit_details` 字典里，`"model": model,` 那行下面加一行：

```python
        "models": models,
```

把 `os.environ.update({...})` 里的 `"OPENAI_MODEL": model,` 保留（作为默认），运行段替换为：

```python
    try:
        with redirect_stdout(sys.stderr):
            image_gen = _load_image_gen()
            backend, _ = image_gen._load_backend("openai")
            ok, failed, model_trace = _run_with_fallback(
                payload,
                backend,
                models=models,
                concurrency=concurrency,
                output_dir=str(manifest.parent),
            )
            image_gen.render_manifest_md_to_file(str(manifest), payload)
        if failed:
            raise RuntimeError(f"Image generation failed for {failed} manifest item(s)")
    except Exception as exc:
        failed_details = {
            **audit_details,
            "cumulative_total": prior_total + generated_this_call(),
        }
        _write_audit("failed", error=str(exc)[:500], **failed_details)
        raise
```

- [ ] **Step 2: 在成功 audit 里带上 model_trace**

把结尾 `_write_audit("succeeded", ...)` 调用加一个参数 `model_trace=model_trace,`：

```python
    _write_audit(
        "succeeded",
        generated_files=generated_files,
        generated_dimensions=generated_dimensions,
        model_trace=model_trace,
        **succeeded_details,
    )
```

同时把 result 的 message 改为反映降级链（可选但推荐）：

```python
        "message": f"Generated {len(generated_files)} image(s) with models {models}",
```

- [ ] **Step 3: 跑全部单测**

Run: `cd service && python -m pytest tests/ -v`
Expected: PASS

- [ ] **Step 4: 语法自检**

Run: `cd service && python -c "import ast; ast.parse(open('image_mcp.py',encoding='utf-8').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 5: 提交**

```bash
git add service/image_mcp.py
git commit -m "feat(images): wire model fallback into manifest generation with audit trace"
```

---

## Task 5: config 校验 + .env 文档

**Files:**
- Modify: `service/config.py:140-144`（`validate()`）
- Modify: `.env.example:245`

- [ ] **Step 1: config.validate 支持逗号列表非空校验**

`config.py` 的 `image_model` 仍读整串（消费方 image_mcp 自己 split），只需确保 `validate()` 里现有的
`if self.image_api_key and not (self.image_base_url and self.image_model)` 逻辑对逗号串同样成立——它已成立（非空串即通过），无需改逻辑。仅在该分支后追加一条：过滤后为空的纯逗号串要拒绝：

```python
        if self.image_api_key:
            parsed_models = [m.strip() for m in self.image_model.split(",") if m.strip()]
            if not parsed_models:
                raise RuntimeError(
                    "PPT_IMAGE_MODEL must list at least one model name"
                )
```

- [ ] **Step 2: 改 .env.example 说明**

把 `.env.example:245` 那行改为带注释：

```
# One model, or a comma-separated fallback chain (first = primary; on 429/5xx/timeout the next is tried)
PPT_IMAGE_MODEL=gpt_image2
```

- [ ] **Step 3: 语法自检**

Run: `cd service && python -c "import ast; ast.parse(open('config.py',encoding='utf-8').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 4: 提交**

```bash
git add service/config.py .env.example
git commit -m "feat(config): accept comma-separated PPT_IMAGE_MODEL fallback chain"
```

---

## Task 6: 部署 + 线上验证

**Files:** 无代码改动（部署操作）

- [ ] **Step 1: 传改动文件到生产 `/opt/ppt-master`**

scp `service/image_mcp.py`、`service/config.py` 到 `/opt/ppt-master/service/`（用 paramiko，参考本会话既有部署脚本；先备份到 `/var/backups/ppt-master/predeploy_<ts>`）。`.env.example` 不需上传（仅文档）。

- [ ] **Step 2: 在生产 .env 配置降级链**

跟主人确认 prism 后面可用的备选模型名单，把生产 `.env` 的 `PPT_IMAGE_MODEL` 改成逗号链，例如 `PPT_IMAGE_MODEL=gpt_image2,<备选1>,<备选2>`。`PPT_IMAGE_MODEL` 已在 compose 白名单，无需改 compose。

- [ ] **Step 3: 重建容器**

```bash
cd /opt/ppt-master && docker compose -f compose.linux-4g.yaml up -d --build api worker
```

Expected: 双容器 healthy。

- [ ] **Step 4: 线上验证**

跑一个含 AI 图的生成任务；观察 worker 日志 / `control/image_generation.json` audit 的 `model_trace`，确认主力模型正常时用主力、模拟主力挂时切备选。若无法轻易模拟 503，至少确认单模型行为回归正常（audit 记录了 `models` 链）。

- [ ] **Step 5: 提交部署记录（可选）**

无代码改动则跳过；如更新了部署文档再提交。

---

## 自检结果

- **Spec 覆盖**：配置逗号列表(T1/T5)、触发切换 429/5xx/超时(T2 `max_retries=0` + 逐模型)、落点 image_mcp 不碰上游(T2/T4)、限流0重试直接切(T2)、audit 记降级(T4)、向后兼容单模型(T1/T5)、部署(T6)——全覆盖。
- **占位符扫描**：无 TBD/TODO；每步含真实代码或命令。
- **类型一致**：`_model_list()→list[str]`、`_run_with_fallback(...)→(int,int,dict)`、`_validate_manifest(path, models)` 在 T2/T3/T4 命名一致。
