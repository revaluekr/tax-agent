# -*- coding: utf-8 -*-
"""인건비 자동화 패키지 초기화 및 하위 모듈 자동 핫리로드(Hot-Reload) 브릿지"""
import importlib
import os
import sys

_SUBMODULES = [
    "payroll_automated.tax_table_data",
    "payroll_automated.tax_tables",
    "payroll_automated.parsers",
    "payroll_automated.calculators",
    "payroll_automated.exporters",
    "payroll_automated.backup",
    "payroll_automated.ai_tax_review",
    "payroll_automated.ui",
]
_MTIMES = {}

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

_ensure_fresh_submodules()

from .ui import (
    render_payroll_automated_main as _render_main,
    render_payroll_automated_sidebar as _render_sidebar,
)

def render_payroll_automated_sidebar(*args, **kwargs):
    _ensure_fresh_submodules()
    from . import ui as _ui_mod
    return _ui_mod.render_payroll_automated_sidebar(*args, **kwargs)

def render_payroll_automated_main(*args, **kwargs):
    _ensure_fresh_submodules()
    from . import ui as _ui_mod
    return _ui_mod.render_payroll_automated_main(*args, **kwargs)

__all__ = [
    "render_payroll_automated_sidebar",
    "render_payroll_automated_main",
]
