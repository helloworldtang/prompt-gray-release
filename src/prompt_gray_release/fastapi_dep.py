"""FastAPI 依赖注入：``Depends(prompt_dep(key, router))`` 一行把灰度路由接入端点。

可选能力：fastapi 未安装时本模块仍可导入，仅在调用 ``prompt_dep`` 时报错并
提示 ``pip install 'prompt-gray-release[fastapi]'``。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from .exceptions import TemplateRenderError
from .router import GrayRouter, RenderedPrompt

if TYPE_CHECKING:  # fastapi 仅在调用 prompt_dep 时才要求安装
    from fastapi import Request


def prompt_dep(key: str, router: GrayRouter) -> Callable[[Request], Awaitable[RenderedPrompt]]:
    """构造 FastAPI 依赖：请求体 ``{"user_key": ..., "variables": {...}}`` → RenderedPrompt。

    用法（每个端点一行接入）::

        from fastapi import Depends
        from prompt_gray_release import prompt_dep

        dep = prompt_dep("support_reply", router)

        @app.post("/reply")
        def reply(r: RenderedPrompt = Depends(dep)):
            return {"version": r.version, "prompt": r.text}

    路由语义与 ``router.render(key, variables, user_key)`` 完全一致（稳定分桶、
    无 user_key 不猜、fail-fast）。HTTP 映射：

    - 请求体不是 JSON / 不是对象 / 字段类型不对 → ``422``；
    - 模板缺变量 → ``400``（客户端提供的变量不足）；
    - prompt 未设置 stable 等 RolloutStateError → 不捕获（服务端配置问题，500）。
    """
    try:
        from fastapi import HTTPException, Request
    except ImportError as exc:  # pragma: no cover - 精简安装环境才会走到
        raise ImportError(
            "prompt_dep 需要 fastapi：pip install 'prompt-gray-release[fastapi]'"
        ) from exc

    async def dep(request: Request) -> RenderedPrompt:
        try:
            body = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=422, detail="请求体必须是 JSON 对象") from exc
        if not isinstance(body, dict):
            raise HTTPException(status_code=422, detail="请求体必须是 JSON 对象")
        user_key = body.get("user_key")
        variables = body.get("variables", {})
        if not isinstance(user_key, str | None) or not isinstance(variables, dict):
            raise HTTPException(
                status_code=422, detail="user_key 必须是字符串，variables 必须是对象"
            )
        try:
            return router.render(key, variables, user_key=user_key)
        except TemplateRenderError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    # fastapi 按参数注解的类身份识别 Request；future annotations 会把注解变成
    # 字符串，而 Request 是本函数局部导入、模块全局解析不到——显式写入真实
    # 类对象，避免被当成 query 参数。
    dep.__annotations__["request"] = Request

    return dep
