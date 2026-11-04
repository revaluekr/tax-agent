# -*- coding: utf-8 -*-
"""통합고용세액공제 패키지 초기화 및 하위 모듈 자동 핫리로드(Hot-Reload) 브릿지"""
from __future__ import annotations

import importlib
import os
import sys

_SUBMODULES = [
    "employment_credit.rules",
    "employment_credit.hc_eligibility",
    "employment_credit.hc_row_engine",
    "employment_credit.hc_credit_calc",
    "employment_credit.hc_review",
    "employment_credit.headcount",
    "employment_credit.parsers",
    "employment_credit.backup",
    "employment_credit.ui_common",
    "employment_credit.ui_sidebar",
    "employment_credit.ui_step1",
    "employment_credit.ui_step2",
    "employment_credit.ui_step3",
    "employment_credit.ui_step4",
    "employment_credit.ui",
]
_MTIMES: dict[str, float] = {}


def _ensure_fresh_submodules() -> None:
    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    need_reload = False
    for mod_name in _SUBMODULES:
        short_nm = mod_name.split(".")[-1]
        fpath = os.path.join(pkg_dir, f"{short_nm}.py")
        if os.path.exists(fpath):
            mtime = os.path.getmtime(fpath)
            if _MTIMES.get(mod_name) is not None and _MTIMES[mod_name] != mtime:
                need_reload = True
            _MTIMES[mod_name] = mtime
    if need_reload:
        for mod_name in _SUBMODULES:
            if mod_name in sys.modules:
                try:
                    importlib.reload(sys.modules[mod_name])
                except Exception:
                    pass


def render_credit_sidebar(*args, **kwargs):
    _ensure_fresh_submodules()
    from . import ui as _ui_mod
    return _ui_mod.render_credit_sidebar(*args, **kwargs)


def render_credit_wizard(*args, **kwargs):
    _ensure_fresh_submodules()
    from . import ui as _ui_mod
    return _ui_mod.render_credit_wizard(*args, **kwargs)


def reset_credit_all_state(*args, **kwargs):
    _ensure_fresh_submodules()
    from . import ui_common as _uc_mod
    return _uc_mod.reset_credit_all_state(*args, **kwargs)


__all__ = [
    "render_credit_sidebar",
    "render_credit_wizard",
    "reset_credit_all_state",
]