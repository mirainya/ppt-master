# 生图多模型降级（prism 单模型挂掉自动切换）设计

- 日期：2026-07-24
- 状态：已确认，待拆实现计划
- 相关：`service/image_mcp.py`、`service/config.py`、`compose.yaml` / `compose.linux-4g.yaml`、`.env.example`

## 背景与目标

叙卷生产环境生图走 service 侧 MCP：`image_mcp.py generate_image_manifest` → 读 `PPT_IMAGE_*` 环境变量 →
塞入 `OPENAI_*` → 调 skill 的 `image_gen._run_manifest` → `backend_openai.generate()`。

**问题**：`PPT_IMAGE_MODEL` 是**单模型硬编码**（`image_mcp.py:129` 甚至拒绝 item 覆盖 model）。prism 中转后面挂多个生图模型，
但某个模型返回 503 时，现状只会用**同一个模型**重试，全挂后整个 manifest 报错，生图任务失败。

**目标**：`PPT_IMAGE_MODEL` 支持逗号分隔的降级链；主力模型遇到 429/5xx/超时时自动切换到下一个备选模型，
而不是直接报错。全部模型都失败才最终报错。

## 决策汇总（已与用户确认）

1. **配置形态**：`PPT_IMAGE_MODEL` 支持逗号列表 `model-a,model-b,model-c`，第一个是主力。只填一个 = 现状，完全向后兼容。
2. **触发切换的错误**：限流(429) + 5xx(503/502/500) + 连接失败/超时，全部触发切换。400 坏请求 / 内容审查拒绝不因换模型而改变，但也一并交给下一个模型（切了不成本项照样失败）。
3. **落点**：降级逻辑全在 `service/image_mcp.py`（service 层），**不碰上游 skill 代码**，避免 merge upstream 冲突。
4. **限流处理**：**0 重试直接切**——每个模型碰到任何错误（含 429）立即切下一个，不在单模型上等待重试。
5. **可见性**：降级过程写进现有 `control/image_generation.json` audit（记录每项最终用的模型 + 降级轨迹）。

## 关键技术约束

**不复用 `image_gen._run_manifest`**：它对限流是「本轮内重排 + 降并发 + 等 10s 重试」，会把限流吞在单模型内部、不外抛，
因此无法满足「限流也 0 重试切模型」。B 方案在 `image_mcp.py` 内实现自己的并发循环，直接调
`backend.generate(model=<当前模型>, max_retries=0)`，任何异常都当本项失败并交给下一个模型。

`backend_openai.generate()` 已支持 `max_retries` 参数（默认 3），传 `0` 即可关闭单模型内重试。
