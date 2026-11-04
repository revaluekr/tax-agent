# -*- coding: utf-8 -*-
"""달력 스케줄러 및 카카오톡 백그라운드 자동화 To-Do 패키지 (하위 모듈 자동 핫리로드 브릿지 포함)"""
from __future__ import annotations

import importlib
import os
import sys

_SUBMODULES = [
    "calendar_scheduler.ui",
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


def render_calendar_sidebar(*args, **kwargs):
    _ensure_fresh_submodules()
    from . import ui as _ui_mod
    return _ui_mod.render_calendar_sidebar(*args, **kwargs)


def render_calendar_main(*args, **kwargs):
    _ensure_fresh_submodules()
    from . import ui as _ui_mod
    return _ui_mod.render_calendar_main(*args, **kwargs)


def render_floating_kakao_todo_overlay(*args, **kwargs):
    _ensure_fresh_submodules()
    from . import ui as _ui_mod
    return _ui_mod.render_floating_kakao_todo_overlay(*args, **kwargs)


__all__ = [
    "render_calendar_sidebar",
    "render_calendar_main",
    "render_floating_kakao_todo_overlay",
]
