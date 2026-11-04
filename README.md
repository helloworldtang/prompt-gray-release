# prompt-gray-release

**把 Prompt 当生产代码发布。** 轻量、可嵌入、零平台依赖的 Prompt 发布工程库：
版本化 → 评测门禁 → 灰度放量 → 一键回滚 → 事故确定性重演。

> Prompt release engineering: versioning, canary rollout, eval gates,
> one-click rollback and deterministic incident replay. Lightweight, embeddable, no platform required.

## 为什么需要它

LLM 应用里，**Prompt 就是生产代码**——但它的变更方式却像在改配置：

- 改一句措辞就可能让格式崩坏、答非所问、成本飙升，而且是**全量瞬间生效**；
- 没有 diff 审查，没有回归测试，没有发布批次，出事了只能全网搜"刚才谁改的 Prompt"；
- 观测平台（LangSmith / Langfuse）能告诉你效果好不好，但**管不住上线那一刻**。

prompt-gray-release 补的就是"上线那一刻"：**新 Prompt 先过评测门禁，再按 1% → 10% → 50% → 100% 灰度放量，出问题秒级回滚，历史事故随时确定性重演。**

## 核心特性

- **版本化注册表**：YAML / JSON 管理 Prompt 版本与元数据，git 友好；
- **灰度路由**：按用户稳定分桶放量（1% → 100%），同一用户永远同一版本，重启不变；
- **评测门禁**：候选版本先跑 golden 评测集，不达基线自动拦截（fail-closed）；
- **一键回滚**：放弃候选、流量瞬间回到 stable，全程 JSONL 审计；
- **录制与确定性重演**：录制线上真实调用（输入 + 模型响应），之后随时原样重放——同一批输入永远得到同一批输出，模板漂移自动检出；
- **轻量**：唯一依赖 PyYAML；无平台、无服务、`pip install` 即用；`$var` 占位符不与 Prompt 内的 JSON 花括号冲突。

## 安装

```bash
pip install prompt-gray-release
```

## 快速开始

完整可运行示例见 [examples/quickstart.py](examples/quickstart.py)。

### 1. 定义 Prompt 版本（prompts.yaml）

```yaml
prompts:
  support_reply:
    v1:
      template: |
        你好 $name，这是 v1 的回复模板。关于 $topic 的问题我们会尽快处理。
      metadata:
        model: gpt-4o-mini
        temperature: 0.2
    v2:
      template: |
        你好 $name！这是 v2 的全新回复模板，专治 $topic 相关问题。
```

### 2. 灰度路由：同一用户永远同一版本

```python
from prompt_gray_release import GrayRouter, PromptRegistry, RolloutController

registry = PromptRegistry.from_yaml("prompts.yaml")
rollout = RolloutController()
rollout.set_stable("support_reply", "v1")
router = GrayRouter(registry, rollout)

rollout.start_rollout("support_reply", "v2", percent=10)   # 先放 10% 流量
r = router.render("support_reply", {"name": "张三", "topic": "发票"}, user_key="user-42")
print(r.version, "->", r.text)   # user-42 落在哪个版本，以后就一直在哪个版本
```

规则：`percent >= 100` 全量走 candidate；`0 < percent < 100` 按稳定 hash 分桶；
**没有 user_key 时不猜**——非全量一律走 stable（宁可不灰度，不可不确定）。

### 3. 评测门禁：不达标就拦截

```python
from prompt_gray_release import EvalCase, EvalGate

gate = EvalGate(registry)
cases = [EvalCase({"name": "张三", "topic": "发票"}, "期望的标准答案……")]
report = gate.evaluate("support_reply", candidate="v2", baseline="v1", cases=cases)
print(report.summary())   # [support_reply] v2=0.000 vs 基线 v1=1.000（要求 >= +0.000）→ 拦截

if report.passed:
    rollout.set_percent("support_reply", 50)   # 过门禁才放量
else:
    rollout.rollback("support_reply")          # 秒级回滚
```

评测函数可插拔：内置 `exact_match` / `contains`，也可以传自定义 `evaluator(output, expected) -> float`。
`gate.enforce(...)` 在不达标时直接抛 `EvalGateBlocked`（fail-closed），适合放进 CI。

### 4. 放量、回滚与审计

```python
rollout.set_percent("support_reply", 10)   # 1% -> 10%
rollout.set_percent("support_reply", 50)   # 观察指标没问题，继续放大
rollout.promote_full("support_reply")      # 全量，candidate 升级为 stable
# 或发现异常：
rollout.rollback("support_reply")          # 秒级回到 stable
```

传入 `state_path` 时，每次变更都会**原子落盘**并追加 **JSONL 审计事件**
（谁在什么时候把哪个版本放到了多少流量），满足企业合规的可追溯要求。

### 5. 录制与确定性重演

```python
from prompt_gray_release import Cassette, Recorder, Replayer

recorder = Recorder("traffic.jsonl")
model = recorder.wrap(real_model)          # 调用即录制（输入 + 模型响应）

# 事后：确定性重演
cassette = Cassette.load("traffic.jsonl")
for item in Replayer(cassette).replay_registry(registry):
    print(item.matches, item.rendered_now) # False = 当前模板与事故时行为已漂移

fake_model = Replayer(cassette).deterministic_model("support_reply", "v2")
fake_model("任意文本", {"name": "张三", "topic": "发票"})  # 永远返回当时录制的响应
```

确定性重演的意义：LLM 输出不可复现，但把"输入 + 当时的响应"录下来之后，
**同一批输入永远得到同一批输出**——下游解析逻辑、路由逻辑、降级逻辑的回归测试从此有了稳定靶子；
`matches=False` 则直接告诉你"事故之后有人改过模板"。

## 设计原则

1. **库，不是平台**：一个 `pip install` 就能嵌入现有业务，不要求你迁移到任何系统；
2. **fail-fast / fail-closed**：缺变量即报错、评测不达标即拦截、重演找不到即抛错——发布链路上不玩默认静默；
3. **确定性优先**：没有 user_key 不做随机灰度；重演靠录制响应而不是"再问一次模型"；
4. **审计内建**：状态每次变更原子落盘 + JSONL 事件流，合规环境可直接对接审计。

## 与 LangSmith / Langfuse 的关系

不冲突，层次不同：它们是**评测与观测平台**（追踪、数据集、在线评测）；
prompt-gray-release 是**发布链路的一层**（版本化、灰度、回滚、重演），可与其搭配——
用它们看效果，用 prompt-gray-release 管上线。不需要平台的小团队，它可以单独工作。

## 路线图

- [ ] CLI：`prompt-gray promote / rollback / diff`
- [ ] 评测函数注册表（正则 / JSON Schema 校验 / 关键词集合）
- [ ] 与 OpenTelemetry 对接的调用追踪导出
- [ ] 多环境（dev / staging / prod）状态隔离

## 开发

```bash
pip install -e ".[dev]"
pytest
```

## License

[MIT](LICENSE) © helloworldtang
