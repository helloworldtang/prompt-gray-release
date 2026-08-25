"""Shared fixtures: repo paths and a mock client."""

from __future__ import annotations

from pathlib import Path

import pytest

from gray_release.config import REPO_ROOT
from gray_release.llm import MockLLMClient


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture
def mock_client() -> MockLLMClient:
    return MockLLMClient()


@pytest.fixture
def prompts(repo_root: Path) -> dict[str, str]:
    return {
        "v1": (repo_root / "prompts" / "product_desc_v1.txt").read_text(encoding="utf-8"),
        "v2": (repo_root / "prompts" / "product_desc_v2.txt").read_text(encoding="utf-8"),
    }
