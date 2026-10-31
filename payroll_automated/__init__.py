# -*- coding: utf-8 -*-
"""
인건비 자동화 패키지 (payroll_automated)
- 4대보험 가입 근로자 [급여명세서·급여대장] 및 3.3% 프리랜서 [사업소득명세서·사업소득지급대장] 통합 자동화
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "render_payroll_automated_main",
    "render_payroll_automated_sidebar",
]


def __getattr__(name: str) -> Any:
    if name in ("render_payroll_automated_main", "render_payroll_automated_sidebar"):
        from . import ui
        return getattr(ui, name)
    raise AttributeError(f"module 'payroll_automated' has no attribute {name!r}")
