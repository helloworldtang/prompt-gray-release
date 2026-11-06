"""prompt-gray CLI：不写 Python 也能完成灰度发布全流程。

子命令两类：

- 运维（全部走 :class:`RolloutController` 唯一写入口，动作自动审计）：
  ``status`` / ``set-stable`` / ``start-rollout`` / ``set-percent`` /
  ``promote-full`` / ``rollback``
- 门禁（CI 用）：``check``——重演 cassette，模板漂移即退出码非 0

退出码约定：``0`` 成功；``1`` 门禁失败（check 发现漂移）；``2`` 使用/状态错误。
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from . import __version__
from .exceptions import PromptGrayReleaseError
from .recorder import Cassette, Replayer
from .registry import PromptRegistry

# 退出码：与 argparse 的 2（参数错误）对齐，1 留给门禁失败
EXIT_OK = 0
EXIT_GATE_FAILED = 1
EXIT_USAGE = 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="prompt-gray",
        description="把 Prompt 当生产代码发布：灰度放量、评测门禁、回滚、事故重演。",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    # ---------- 运维 ----------
    def add_state_arg(p: argparse.ArgumentParser) -> None:
        p.add_argument("--state", required=True, help="状态文件路径（rollout state，JSON）")

    def add_key_arg(p: argparse.ArgumentParser) -> None:
        p.add_argument("key", help="prompt key")

    p = sub.add_parser("status", help="查看某 prompt 的灰度状态")
    add_key_arg(p)
    add_state_arg(p)

    p = sub.add_parser("set-stable", help="设置/切换 stable 版本")
    add_key_arg(p)
    p.add_argument("version", help="stable 版本号")
    add_state_arg(p)

    p = sub.add_parser("start-rollout", help="开始灰度（指定候选版本与初始放量）")
    add_key_arg(p)
    p.add_argument("candidate", help="候选版本号")
    p.add_argument("--percent", type=int, default=0, help="初始放量百分比 0-100（默认 0）")
    add_state_arg(p)

    p = sub.add_parser("set-percent", help="调整候选版本流量百分比")
    add_key_arg(p)
    p.add_argument("percent", type=int, help="百分比 0-100")
    add_state_arg(p)

    p = sub.add_parser("promote-full", help="全量：candidate 升级为 stable")
    add_key_arg(p)
    add_state_arg(p)

    p = sub.add_parser("rollback", help="回滚：放弃 candidate，流量回到 stable")
    add_key_arg(p)
    add_state_arg(p)

    # ---------- 门禁 ----------
    p = sub.add_parser("check", help="重演门禁：cassette vs 当前注册表，漂移即失败")
    p.add_argument(
        "--cassette",
        action="append",
        required=True,
        dest="cassettes",
        help="录制文件路径（JSONL，可多次传入）",
    )
    p.add_argument("--registry", required=True, help="Prompt 注册表路径（YAML 或 JSON）")
    p.add_argument(
        "--strict",
        action="store_true",
        help="严格模式：空 cassette 也算失败（防止'没录制所以全过'的假绿）",
    )
    return parser


def _load_registry(path: str) -> PromptRegistry:
    if path.endswith((".yaml", ".yml")):
        return PromptRegistry.from_yaml(path)
    return PromptRegistry.from_json(path)


def _cmd_check(args: argparse.Namespace) -> int:
    registry = _load_registry(args.registry)
    records = []
    for path in args.cassettes:
        records.extend(Cassette.load(path).records)
    if not records and args.strict:
        print("✗ 严格模式：cassette 为空，无事可验——先录制再门禁（fail-closed）", file=sys.stderr)
        return EXIT_GATE_FAILED

    replayer = Replayer(Cassette(records))
    results = replayer.replay_registry(registry)

    n_match = n_drift = n_missing = n_render_err = 0
    first_failure: str | None = None
    for i, r in enumerate(results, 1):
        where = f"#{i} {r.record.prompt_key}/{r.record.version}"
        if r.error == "version_missing":
            n_missing += 1
            line = f"✗ {where} 版本缺失（key 或 version 已不在注册表）"
        elif r.error == "render_error":
            n_render_err += 1
            line = f"✗ {where} 渲染失败（模板已无法用当时的变量渲染）"
        elif r.matches:
            n_match += 1
            line = f"✓ {where} 一致"
        else:
            n_drift += 1
            line = f"✗ {where} 模板漂移（当前渲染 ≠ 录制文本）"
        print(line)
        if not r.matches and first_failure is None:
            first_failure = line
            if r.rendered_now is not None and r.record.rendered_text is not None:
                print(f"    录制: {r.record.rendered_text!r}")
                print(f"    现在: {r.rendered_now!r}")

    total = len(results)
    print(
        f"\n重演 {total} 条：{n_match} 一致 / {n_drift} 漂移 / "
        f"{n_missing} 版本缺失 / {n_render_err} 渲染失败"
    )
    if n_match == total:  # 空带子在非严格模式下 0==0 直接通过
        print("✓ 门禁通过：注册表行为与录制一致")
        return EXIT_OK
    print("✗ 门禁拦截：Prompt 行为与录制发生漂移，禁止放量（先修复或重录 cassette）")
    return EXIT_GATE_FAILED


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    # check 不需要状态文件，单独走
    if args.command == "check":
        return _cmd_check(args)

    # 其余运维命令全部走 RolloutController 唯一写入口
    from .rollout import RolloutController

    ctl = RolloutController(state_path=args.state)
    try:
        if args.command == "status":
            st = ctl.state(args.key)
            print(f"{args.key}: stable={st.stable}")
            if st.candidate:
                print(f"  灰度中: candidate={st.candidate} percent={st.percent}%")
            else:
                print("  灰度中: 无")
        elif args.command == "set-stable":
            ctl.set_stable(args.key, args.version)
            print(f"✓ {args.key} stable -> {args.version}")
        elif args.command == "start-rollout":
            ctl.start_rollout(args.key, args.candidate, percent=args.percent)
            print(f"✓ {args.key} 开始灰度: {args.candidate} @ {args.percent}%")
        elif args.command == "set-percent":
            ctl.set_percent(args.key, args.percent)
            print(f"✓ {args.key} 放量 -> {args.percent}%")
        elif args.command == "promote-full":
            ctl.promote_full(args.key)
            print(f"✓ {args.key} 全量（candidate 升级为 stable）")
        elif args.command == "rollback":
            ctl.rollback(args.key)
            print(f"✓ {args.key} 已回滚（流量回到 stable）")
    except PromptGrayReleaseError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return EXIT_USAGE
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
