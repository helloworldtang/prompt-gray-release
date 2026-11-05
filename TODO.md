# TODO — prompt-gray-release

> 定位：把 Prompt 当生产代码发布的轻量发布工程库（版本化 → 评测门禁 → 灰度放量 → 一键回滚 → 事故确定性重演）。
> 所有变更遵守协作规则：版本只增不改 / 写与发分离 / 唯一写入口 / 上行要门禁下行永远畅通 / fail-closed / 确定性优先 / 单飞行版本（详见 README「设计原则」）。

## 路线总览

项目目标见 [README「项目目标」](README.md#项目目标)。四个阶段的逻辑：**先让项目存在（0），再兑现核心卖点（1），再降门槛扩传播（2），最后发布与自证（3）**。

| 阶段 | 目标 | 完成标志（DoD） | 状态 |
|---|---|---|---|
| Phase 0 仓库上线 | 让项目「存在」：代码公开、CI 跑绿 | GitHub 可访问 + Actions 矩阵全绿 + Topics 就位 | ☐ |
| Phase 1 核心价值闭环 | 独特性卖点（CI 重演门禁）+ first-run 体验（真实模型 5 分钟跑通） | 改一行模板 CI 变红；新用户凭 key 全流程跑通 | ☐ |
| Phase 2 运维与传播 | 不写 Python 也能用；英文世界能看到 | CLI 全流程 + 回滚均有审计；README.en + 两个集成示例 | ☐ |
| Phase 3 发布与自证 | 可 `pip install` + 生产在用 + 有文章 | PyPI v0.1.0 + tag + 生产接入 + 复盘文 | ☐ |

## 开工前（目录迁移后一次性）

- [ ] 重建虚拟环境：`rm -rf .venv && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"`，然后 `pytest`（86 个测试应全绿）

## Phase 0 — 仓库上线（让项目「存在」）

**目标：代码公开、CI 跑绿，项目有了可以被点开、被引用、被验证的实体。**

- [ ] 推送到 GitHub：`git remote add origin git@github.com:helloworldtang/prompt-gray-release.git && git push -u origin main`
- [ ] 确认 GitHub Actions 上 CI 跑绿（Python 3.9–3.12 矩阵）
- [ ] 仓库 About / Topics：`prompt-engineering` `llm` `canary-release` `prompt-versioning` `llmops`

## Phase 1 — P0：核心价值闭环（优先做这两个）

**目标：把 README 里宣称的两个差异化卖点变成可跑的事实——「CI 重演门禁」别人没有，「真实模型 first-run」别人做得不够顺。**

### P0-1 `prompt-gray check`：CI 重演门禁（独特性最强，无直接竞品）

- [ ] CLI 子命令 `check`：读 cassette + registry，逐条重演；模板漂移 / 渲染不一致 / 版本缺失 → 退出码非 0
- [ ] 参数：`--cassette <path>`（可多条）`--registry <path>` `--strict`
- [ ] 输出人话报告：每条 record 的 matches、首个失败详情、汇总统计
- [ ] 提供 GitHub Action 用法（action.yml 或 README 中 pip + check 的标准写法）
- [ ] 文档：最小 CI 示例——"改一行模板 → CI 红；还原 → CI 绿"

**验收**：演示仓库里改一行模板，CI 拦截合并；还原后 CI 恢复绿色。

### P0-2 OpenAI 兼容接入示例（first-run 体验是开源生死线）

- [ ] `examples/openai_demo.py`：真实模型调用（OpenAI SDK 兼容端点，`base_url` 可配）+ 灰度路由 + 评测门禁 + JSONL 审计全流程
- [ ] README 增补"用真实模型跑通"一节（环境变量：`OPENAI_API_KEY` / `OPENAI_BASE_URL`）
- [ ] 约束：库本身不引入 openai 依赖，示例单独安装

**验收**：新用户凭自己的 key，按 README 在 5 分钟内用真实模型跑通全流程。

## Phase 2 — P1：运维手感与传播面

**目标：把使用门槛降到「不写 Python 也能用」，同时让英文世界能发现这个项目。**

### P1-1 CLI 骨架（entry point：`prompt-gray`）

- [ ] 子命令：`status <key>` / `set-stable` / `start-rollout` / `set-percent` / `promote-full` / `rollback` / `check`
- [ ] 全部走 `RolloutController` 唯一写入口，动作自动审计
- [ ] 全局参数 `--state <path>`；输出表格化

**验收**：不写一行 Python 也能完成一次完整灰度 + 回滚，并有审计记录。

### P1-2 传播面

- [ ] README.en（英文版，与中文版互链）
- [ ] FastAPI 集成示例（10 行级：`router.render` 进请求处理）
- [ ] pytest 集成示例（`gray_router` / `cassette` fixtures）

## Phase 3 — 发布与自证

**目标：可安装、生产在用、有公开文章——三者凑齐，这个项目才算立住。**

- [ ] `python -m build` + Twine 发 PyPI（v0.1.0），打 annotated tag
- [ ] 在生产项目里真实接入（三个接入点：渲染 → `router.render`；模型调用 → `recorder.wrap`；发布 → `rollout`）——生产自证
- [ ] 事故复盘文章（掘金 / 知乎）：问题 → 归因 → 框架设计 → 开源

## 不做清单（防摊薄）

- ~~Web 控制台~~、~~统计显著性检验~~、~~多模型竞价路由（LiteLLM 领域）~~、~~Prompt 分享 Hub~~、~~托管服务版~~
