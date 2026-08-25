"""Command-line entry points.

Usage::

    python -m gray_release demo [--output-dir DIR]
    python -m gray_release eval --prompt prompts/product_desc_v2.txt \
        [--baseline baseline.json] [--save-baseline PATH]
    python -m gray_release serve [--host 0.0.0.0] [--port 8080]
    python -m gray_release traffic --count 500 [--long-tail 0.35] \
        [--target http://localhost:8080]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from gray_release.config import REPO_ROOT, load_config
from gray_release.evaluation.datasets import load_test_set
from gray_release.evaluation.gates import all_passed, check_gates
from gray_release.evaluation.runner import (
    evaluate_prompt,
    load_baseline,
    render_report,
    save_baseline,
)
from gray_release.llm import MockLLMClient


def _repo_path(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else REPO_ROOT / path


def _load_sets(regression_file: str) -> dict[str, list[Any]]:
    return {
        "regression": load_test_set(_repo_path(regression_file)),
        "edge": load_test_set(REPO_ROOT / "datasets" / "edge_cases.jsonl"),
        "new_feature": load_test_set(REPO_ROOT / "datasets" / "new_feature.jsonl"),
    }


def _cmd_eval(args: argparse.Namespace) -> int:
    config = load_config()
    client = MockLLMClient()
    prompt = _repo_path(args.prompt).read_text(encoding="utf-8")
    sets = _load_sets(args.regression_set)
    results = evaluate_prompt(prompt, sets, client, config.evaluation.fail_threshold)
    print(render_report(results, f"eval: {args.prompt}"))

    if args.save_baseline:
        save_baseline(results, _repo_path(args.save_baseline))
        print(f"baseline saved to {args.save_baseline}")
        return 0

    baseline_path = _repo_path(args.baseline) if args.baseline else REPO_ROOT / "baseline.json"
    if not baseline_path.exists():
        print("no baseline found; run once with --save-baseline on the stable prompt first")
        return 1
    baseline = load_baseline(baseline_path)
    outcomes = check_gates(results, baseline, config.evaluation)
    for outcome in outcomes:
        verdict = "PASS" if outcome.passed else "FAIL"
        print(f"[{verdict}] {outcome.name}: {outcome.detail}")
    print("gates:", "ALL PASSED - safe to enter 1% A/B" if all_passed(outcomes) else "BLOCKED - do not ship")
    return 0 if all_passed(outcomes) else 2


def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from gray_release.llm import MockLLMClient as _MockClient
    from gray_release.traffic.gateway import build_default_state, create_app

    state = build_default_state(REPO_ROOT / "prompts", _MockClient())
    app = create_app(state)
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


def _cmd_traffic(args: argparse.Namespace) -> int:
    import httpx

    from gray_release.intents import SAMPLE_MESSAGES, Intent

    ratios = {
        Intent.PRICE_STANDARD: 1 - args.long_tail - 0.2,
        Intent.PRICE_LONG_TAIL: args.long_tail,
        Intent.FEATURE: 0.15,
        Intent.POLICY: 0.05,
    }
    slots: list[Intent] = []
    for intent, weight in ratios.items():
        slots.extend([intent] * max(1, round(weight * 100)))
    failures = 0
    with httpx.Client(timeout=30.0) as http:
        for index in range(args.count):
            intent = slots[index % len(slots)]
            variants = SAMPLE_MESSAGES[intent]
            message = variants[(index // len(slots)) % len(variants)]
            response = http.post(
                f"{args.target}/chat",
                json={"user_id": f"load-{index:06d}", "message": message},
            )
            if response.status_code != 200:
                failures += 1
            if (index + 1) % 100 == 0:
                summary: dict[str, Any] = {"sent": index + 1}
                status = http.get(f"{args.target}/release/status").json()
                summary.update(status)
                print(json.dumps(summary, ensure_ascii=False))
    print(f"done: {args.count} dialogues, {failures} failures")
    return 0 if failures == 0 else 1


def _cmd_demo(args: argparse.Namespace) -> int:
    from gray_release.demo import run_demo

    run_demo(output_dir=Path(args.output_dir) if args.output_dir else None)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gray_release", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    demo = subparsers.add_parser("demo", help="replay the full incident + three-layer pipeline")
    demo.add_argument("--output-dir", default=None, help="directory for the generated post-mortem")
    demo.set_defaults(func=_cmd_demo)

    evaluate = subparsers.add_parser("eval", help="offline evaluation of a prompt against the gate rules")
    evaluate.add_argument("--prompt", required=True, help="path to the prompt file to evaluate")
    evaluate.add_argument("--baseline", default="baseline.json", help="baseline stats JSON to compare against")
    evaluate.add_argument("--save-baseline", default=None, help="write these results as the new baseline and exit")
    evaluate.add_argument("--regression-set", default="datasets/regression.jsonl", help="regression set to use")
    evaluate.set_defaults(func=_cmd_eval)

    serve = subparsers.add_parser("serve", help="run the gateway API server")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8080)
    serve.set_defaults(func=_cmd_serve)

    traffic = subparsers.add_parser("traffic", help="send synthetic traffic to a running gateway")
    traffic.add_argument("--count", type=int, default=500)
    traffic.add_argument("--long-tail", type=float, default=0.35, help="share of long-tail pricing questions")
    traffic.add_argument("--target", default="http://127.0.0.1:8080")
    traffic.set_defaults(func=_cmd_traffic)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = args.func(args)
    return int(result)


if __name__ == "__main__":
    raise SystemExit(main())
