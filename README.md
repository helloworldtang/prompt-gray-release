# prompt-gray-release

**把 Prompt 当生产代码发布。** 轻量、可嵌入、零平台依赖的 Prompt 发布工程库：
版本化 → 评测门禁 → 灰度放量 → 一键回滚 → 事故确定性重演。

> Prompt release engineering: versioning, canary rollout, eval gates,
> one-click rollback and deterministic incident replay. Lightweight, embeddable, no platform required.
>
> [English README](README.en.md)

## 为什么是它：与平台方案的根本差异

LangSmith / Langfuse 是**评测与观测平台**——它们管"效果好不好"，管不住**上线那一刻**。
prompt-gray-release 补的就是上线那一刻，并且不要求你搭建或迁移到任何平台：

| | LangSmith / Langfuse 等平台 | prompt-gray-release |
|---|---|---|
| 形态 | SaaS / 自托管服务，数据要出域或进它们的存储 | **纯库**，`pip install` 即用，数据不出你的进程 |
| 私有化与审计 | 自托管版要搭整套服务 | **JSONL 审计事件内建**，append-only，合规环境直接对接 |
| CI 门禁 | 依赖平台 CI 集成 | `prompt-gray check` 本地/CI 原生跑，**模板漂移直接挡合并** |
| 事故重演 | 数据集快照（要再调模型） | **确定性重演**：录下当时的响应，重放零调用、零成本、结果恒定 |
| 依赖 | 平台 SDK + 账号 + 网络 | **唯一依赖 PyYAML** |

一句话：**用平台看效果，用 prompt-gray-release 管上线。** 没有平台的小团队，它单独工作。

## 项目目标

**让任何团队——无需搭建平台——把 Prompt 变更纳入与代码同级的发布纪律。**

拆成三个可验收的子目标：

1. **安全上线**：Prompt 变更先过评测门禁，再按流量灰度，异常秒级回滚（对应 Registry / EvalGate / RolloutController）；
2. **行为可验证**：Prompt 的每次行为变化都能被确定性重演并自动检出（对应 Recorder / Replayer / `prompt-gray check`）；
3. **过程可审计**：谁、何时、把哪个版本、放了多少流量，全程 JSONL 可追溯。

**目标用户**：没有 MLOps 平台、也不打算搭平台的 LLM 应用团队；需要私有化与审计的强合规企业；个人开发者。
**非目标**：不做模型路由、不做评测平台、不做 Web 控制台——只做「发布链路」这一层。

## 为什么需要它

LLM 应用里，**Prompt 就是生产代码**——但它的变更方式却像在改配置：

- 改一句措辞就可能让格式崩坏、答非所问、成本飙升，而且是**全量瞬间生效**；
- 没有 diff 审查，没有回归测试，没有发布批次，出事了只能全网搜"刚才谁改的 Prompt"；
- 观测平台能告诉你效果好不好，但**管不住上线那一刻**。

prompt-gray-release 补的就是"上线那一刻"：**新 Prompt 先过评测门禁，再按 1% → 10% → 50% → 100% 灰度放量，出问题秒级回滚，历史事故随时确定性重演。**

## 安装

```bash
pip install prompt-gray-release
```

Python >= 3.10。唯一运行时依赖 PyYAML。

## 快速开始

完整可运行示例见 [examples/quickstart.py](examples/quickstart.py)（零 API key，
模拟模型 5 分钟跑通）与 [examples/openai_demo.py](examples/openai_demo.py)（真实模型全流程，
任意 OpenAI 兼容端点）。

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

评测函数可插拔：内置 `exact_match` / `contains`，也可以传自定义 `evaluator(output, expected) -> float`
（包括把真实模型当裁判——见 [examples/openai_demo.py](examples/openai_demo.py)）。
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

## CLI：不写 Python 也能用

安装后自带 `prompt-gray` 命令。运维子命令全部走唯一写入口，动作自动审计：

```bash
prompt-gray set-stable      support_reply v1               --state rollout.json
prompt-gray start-rollout   support_reply v2 --percent 10  --state rollout.json
prompt-gray status          support_reply                  --state rollout.json
prompt-gray set-percent     support_reply 50               --state rollout.json
prompt-gray rollback        support_reply                  --state rollout.json   # 秒级回滚
prompt-gray promote-full    support_reply                  --state rollout.json
```

## CI 重演门禁：改一行模板，CI 变红

`prompt-gray check` 把"确定性重演"变成 CI 门禁——拿录制的真实流量对当前注册表逐条重演，
模板漂移 / 版本缺失 / 渲染失败任一出现即退出码非 0：

```bash
prompt-gray check --cassette traffic.jsonl --registry prompts.yaml --strict
```

`--strict` 下空 cassette 也算失败（防止"没录制所以全过"的假绿）。GitHub Actions 用法：

```yaml
# .github/workflows/prompt-drift.yml
on: [pull_request]
jobs:
  prompt-drift:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install prompt-gray-release
      - run: prompt-gray check --cassette traffic.jsonl --registry prompts.yaml --strict
```

效果：**PR 里改一行模板 → CI 拦截合并；还原 → CI 恢复绿色。**
录制文件（traffic.jsonl）跟着仓库走，门禁在本地与 CI 行为完全一致，不依赖任何外部服务。

## 用真实模型 5 分钟跑通

```bash
pip install openai prompt-gray-release
export OPENAI_API_KEY=sk-...
export OPENAI_BASE_URL=https://...   # 可选：任意 OpenAI 兼容端点
python examples/openai_demo.py
```

示例覆盖：灰度路由选中候选 → 真实模型调用并录制 → 真实模型当裁判的评测门禁
（不达标自动回滚）→ 零成本确定性重演。库本身不引入 openai 依赖。

## 集成

- FastAPI：[examples/fastapi_app.py](examples/fastapi_app.py)——`router.render` 进请求处理，
  附带回滚端点；
- pytest：[examples/test_with_cassette.py](examples/test_with_cassette.py)——用 cassette
  的确定性假模型做下游逻辑回归；
- OpenTelemetry（可选 `[otel]` extra）：`traced(router)` / `traced_model(model)` 导出 span；
- 多环境：`RolloutController.for_env("rollout", "prod")` → `rollout.prod.json`，环境间状态天然隔离。

## 设计原则

1. **库，不是平台**：一个 `pip install` 就能嵌入现有业务，不要求你迁移到任何系统；
2. **fail-fast / fail-closed**：缺变量即报错、评测不达标即拦截、重演找不到即抛错——发布链路上不玩默认静默；
3. **确定性优先**：没有 user_key 不做随机灰度；重演靠录制响应而不是"再问一次模型"；
4. **审计内建**：状态每次变更原子落盘 + JSONL 事件流，合规环境可直接对接审计。

## 路线图

详细计划与进度见 [TODO.md](TODO.md)。

- [x] CLI：`prompt-gray status / set-stable / start-rollout / set-percent / promote-full / rollback / check`
- [x] 评测函数注册表（正则 / 关键词集合 / JSON 合法性 / JSON Schema）
- [x] 与 OpenTelemetry 对接的调用追踪导出（`traced` / `traced_model`，可选 extra）
- [x] 多环境（dev / staging / prod）状态隔离（`for_env`）

## 开发

```bash
pip install -e ".[dev]"
pytest          # 97 个测试
ruff check src tests examples && ruff format --check src tests examples
mypy src        # strict
```

## License

[MIT](LICENSE) © helloworldtang
