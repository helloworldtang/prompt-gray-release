# prompt-gray-release

AI 应用 Prompt 灰度发布工具包：离线评测门槛 → 1% A/B → 渐进放量 + 自动熔断，三层防线阻止一次 Prompt 改动引发的线上事故。

**事故背景**（本项目重演的真实剧本）：改了个产品描述 Prompt，离线测试没问题直接全量，第二天转化率掉 15%。根因是真实用户的问法千奇百怪——"多少钱"、"贵不贵"、"有什么优惠"——新版 Prompt 对长尾问法的处理明显退化，而过期评测集里根本没有这些问法；且因为直接全量，回滚时都无法定位是哪次改动导致。

AI 应用的灰度比传统软件更关键：**Prompt 的改动不可预测，用户的反馈是滞后的**。所以需要更快的反馈、更细的监控、更狠的回滚。

## 快速开始

```bash
# 环境：Python 3.10+，uv（或 pip）
uv venv .venv && uv pip install --python .venv/bin/python -e ".[dev]"

# 15 秒重演整个事故 + 三层防线（确定性，无随机）
.venv/bin/python -m gray_release demo

# 测试 / 质量门槛（ruff + mypy strict + 58 测试）
.venv/bin/python -m pytest
.venv/bin/ruff check . && .venv/bin/mypy gray_release
```

demo 会依次输出：

1. **第 0 幕**：v2 在过期评测集上三道门槛全过 → 全量上线 → 事故发生
2. **第 1 层**：换成每周更新的评测集（含长尾问法），回归门槛当场拦截
3. **第 2 层**：1% A/B（0.5% 新 + 0.5% 旧），小样本通过——展示"反馈滞后"如何放过问题
4. **第 3 层**：5% → 20% → 50% 放量，长尾问法占 35% 的真实流量涌入，20% 处触发熔断自动回滚，生成 Post-mortem

## 架构

```
                         ┌──────────────────────────────────────────┐
                         │            prompts/product_desc_v*.txt   │
                         └───────────────┬──────────────────────────┘
                                         │
   第 1 层 · 离线评测（15 分钟）          ▼
   ┌─────────────────────────────────────────────────────────────┐
   │ regression(500) / edge(200) / new_feature 评测集             │
   │ 门槛：回归集 avg 降 ≤3% · 边界集失败率 ≤5% · 新功能 avg ≥0.7 │
   └───────────────────────────┬─────────────────────────────────┘
                               │ 全过
   第 2 层 · 1% A/B（24 小时）   ▼
   ┌─────────────────────────────────────────────────────────────┐
   │ A=0.5% 新 / B=0.5% 旧，md5(user_id) 一致性哈希分组            │
   │ 通过标准：满意度 + 完成率 提升 ≥5%，响应时间恶化 ≤10%         │
   └───────────────────────────┬─────────────────────────────────┘
                               │ 通过
   第 3 层 · 渐进放量 + 熔断     ▼
   ┌─────────────────────────────────────────────────────────────┐
   │ 5% → 20% → 50% → 100%，每步观察 4h，control 组为基线          │
   │ 熔断：满意度/完成率 < 基线×0.95 · 响应时间 > 基线×1.5        │
   │       · 错误率 >5%      → 回滚稳定版 + 冷却 24h + Post-mortem │
   └─────────────────────────────────────────────────────────────┘
                               │
                               ▼
   监控：Prometheus(+Alertmanager 四条熔断告警) + Grafana 面板 + ELK 日志
```

## 起监控面板

```bash
docker compose up -d          # gateway + prometheus + alertmanager + grafana

# 打一批模拟流量（长尾问法占 35%）
.venv/bin/python -m gray_release traffic --count 1000

# 打开 http://localhost:3000 —— 「Prompt 灰度发布监控」面板已自动加载
# 切换放量比例（也是 canary 循环调用的同一个入口）：
curl -X POST localhost:8080/release/plan -H 'Content-Type: application/json' \
     -d '{"mode": "rollout", "treatment_permille": 200}'
```

面板包含：当前放量百分比、新版满意度/完成率/错误率 stat、新旧版本满意度与完成率对比曲线（熔断阈值线）、P95 响应时间、各分组 QPS、熔断告警列表。Alertmanager 的四条告警与进程内熔断条件一一对应（`monitoring/alerts.yml`）。

## 流量分配：一致性哈希

`gray_release/traffic/router.py` —— 单一 `md5(user_id) % 1000` 桶决定一切分组：

- **无泄露（坑 2）**：一个桶一个分组，同一用户永远只会在 A 或 B 之一
- **单调扩张（坑 3）**：`bucket < treatment_permille` 判定 treatment，提高比例只会加入用户，不会把已见到新 Prompt 的用户踢回旧版
- **确定性**：无随机数，重启/扩容后分组不变

```python
from gray_release.traffic.router import ReleaseMode, TrafficPlan

plan = TrafficPlan(mode=ReleaseMode.ROLLOUT, treatment_permille=200)  # 新版 20%
plan.group_for("user-000001")  # "treatment" 或 "control"
plan.version_label_for("treatment")  # "new"
```

## 门槛与阈值速查

所有数字都在 `config/release_config.yaml`，代码零硬编码：

| 层 | 规则 | 默认值 |
|---|---|---|
| 1 | 回归集平均分下降 | ≤ 3% |
| 1 | 边界集失败率（score < 0.7） | ≤ 5% |
| 1 | 新功能集平均分 | ≥ 0.70 |
| 2 | A/B 满意度 + 完成率提升 | ≥ 5%（两项都要） |
| 2 | A/B 响应时间恶化 | ≤ 10% |
| 2 | 每组最小样本 | 30 条 |
| 3 | 满意度 / 完成率跌破基线 | × 0.95 |
| 3 | 响应时间超基线 | × 1.5 |
| 3 | 错误率 | > 5% |
| 3 | 熔断后冷却 | 24h |

## 四个坑 → 代码位置

| 坑 | 对策 | 位置 |
|---|---|---|
| 1. 评测集过期 | 每周从线上日志抽样，保留 80% 旧 + 20% 新；`regression.jsonl` vs `regression_stale.jsonl` 即两种命运的对照 | `config/release_config.yaml: dataset_refresh`，`datasets/` |
| 2. A/B 流量泄露 | md5 一致性哈希，同用户恒定同组（有测试锁定互斥性） | `gray_release/traffic/router.py`，`tests/test_router.py` |
| 3. 放量太快 | 严格按 5→20→50→100 步进不跳步，每步观察 + 熔断判定 | `gray_release/release/canary.py`，steps 配置 |
| 4. 回滚后忘分析 | 熔断自动生成 Post-mortem（触发条件、流量比例、低分对话样本、TODO 根因） | `gray_release/release/postmortem.py`，`postmortems/` |

## 一键回滚

```bash
./scripts/rollback.sh v1.4.2
# 1. git 恢复 prompts/ 并部署  2. 重启服务 + 网关切回 stable
# 3. 健康检查（失败即报错退出）4. Slack 通知（$SLACK_WEBHOOK_URL 可选）
```

进程内熔断回滚是同一语义：`on_step(0)` → 网关 plan 切 `OFF` → 100% 稳定版，Grafana 放量百分比同步归零。

## 项目结构

```
gray_release/
├── config.py                  # 三个层的全部阈值（yaml → pydantic）
├── intents.py                 # 意图分类 + 每意图答案要点表（离线/线上同一把尺）
├── llm.py                     # LLMClient 协议 + MockLLMClient（校准的事故机制）
├── evaluation/                # 第 1 层：comparator 打分 / datasets 加载 / runner / gates
├── traffic/                   # 流量：router 一致性哈希 / satisfaction 模拟 / gateway FastAPI
├── release/                   # 第 2、3 层：metrics 双后端 / ab_test 判定 / canary 熔断 / postmortem
├── replay.py                  # 确定性流量重放（意图配比交错分布，无随机）
├── demo.py                    # 事故重演入口
└── __main__.py                # CLI：demo | eval | serve | traffic
datasets/                      # regression / regression_stale / edge_cases / new_feature
prompts/                       # product_desc_v1.txt（稳定）/ v2.txt（候选）
monitoring/                    # prometheus / alerts / alertmanager / grafana 面板
scripts/rollback.sh            # 一键回滚
```

## 接入真实系统

Demo 用 `MockLLMClient` + 要点覆盖率模拟满意度，两者都有明确的替换点：

1. **真实 LLM**：实现 `LLMClient` 协议（`complete(prompt, user_input) -> LLMResponse`），传入 `build_default_state`
2. **真实满意度**：线上用对话结束的 1-5 星打分、任务完成事件（下单/解决）替换 `simulate_satisfaction`；人工每天抽 100 条
3. **生产熔断数据源**：`PrometheusQueryClient` 从 Prometheus HTTP API 聚合 `bot_*` 指标，直接作为 canary 的 `stats_source`
4. **评测集更新**：每周从线上日志抽样（80% 旧 + 20% 新），长尾问法进回归集——这是第 1 层能否拦住事故的生命线

## 经验教训

不要相信"测试过了没问题"，用户总能找到你没想到的 case。灰度不是可选，是必须：**快**（问题暴露要快，实时监控）、**狠**（回滚要果断，自动熔断）、**稳**（每一步都要验证，三层灰度）。整个流程最少 2 天（离线 15 分钟 + 1% A/B 24 小时 + 每步 4-6 小时放量），但比上线后翻车、全量回滚排查一周强太多。
