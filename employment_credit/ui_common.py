# -*- coding: utf-8 -*-
"""통합고용세액공제 계산기 화면 — 공통 도구: 상태·저장·캐시·연도별 사원표 계산 연결·승계/양도 조정·PDF·CSS·표 서식 상수

(ui.py에서 나눈 파일. 함수 본문은 원래 ui.py와 같습니다.)
"""
from __future__ import annotations
from typing import Any
import io
import os
import re
import csv
import json
import copy
import hashlib
import time
import urllib.request
import streamlit as st
from st_aggrid import JsCode
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from . import rules as R
from . import headcount as H
from . import parsers as P



STEPS = ["자료 업로드", "사원정보", "공제액 계산", "보고서"]
MONTH_COLS = [f"M{m:02d}" for m in range(1, 13)]
INFO_COLS = ["사업장명", "성명", "생년월일", "입사일", "퇴사일"]
CLASS_COLS = ["고용유형", "제외사유", "청년등"]

STORAGE_DIR = ".workspace_storage"
os.makedirs(STORAGE_DIR, exist_ok=True)

_PERSIST_KEYS = (
    "step",
    "max_step_reached",
    "tax_year",
    "files",
    "uploader_ver",
    "ext",
    "ext_sig",
    "built_sig",
    "biz",
    "biz_confirmed",
    "sub_biz_list",
    "people",
    "year_recs",
    "prev_summary",
    "additional_inputs",
    "scheme_2026",
    "pm_basis",
    "assume_year_end",
    "include_unpaid_hire_month",
    "use_year_tabs",
    "show_all_4_blocks",
    "show_empty_pm_blocks",
    "manual_extra_years",
    "next_pid_seq",
    "_pm_basis_user_touched",
    "_tabs_user_touched",
    "fill_ver",
    "corp_size_default",
    "corp_size_by_year",
    "corp_size_user_set",
    "yr_sz_ver",
    "_last_sidebar_corp_size",
    "pro_audit_comment",
    "pro_audit_model",
    "pro_audit_sig",
)


# ══════════════════════════════════════════════════════════════════
# 0. 작업공간별 상태 보관 (메모리 + 디스크 `.workspace_storage` 자동 동기화)
# ══════════════════════════════════════════════════════════════════
_RRN_FULL_RE = re.compile(r"(?<!\d)(\d{6})\s*-\s*([1-8])\d{6}(?!\d)")


_ANON_WS_PREFIX = "__anon_session__:"      # app.py의 익명(코드 미입력) 작업공간 ID 접두어와 동일
_ANON_MAX_AGE_SEC = 86400                    # 익명 작업공간 계산기 파일 보관 기간: 24시간


def _ec_disk_path(ws_id: str) -> str:
    """작업공간 코드를 넣은 경우 ec_state_*.json, 코드 없이 쓴 임시 작업공간은 ec_anon_*.json으로 구분 저장"""
    ws = str(ws_id or "default_ec")
    safe_hash = hashlib.md5(ws.encode("utf-8")).hexdigest()[:16]
    prefix = "ec_anon_" if ws.startswith(_ANON_WS_PREFIX) else "ec_state_"
    return os.path.join(STORAGE_DIR, f"{prefix}{safe_hash}.json")


def _cleanup_stale_anon_ec_files(max_age_sec: int = _ANON_MAX_AGE_SEC) -> None:
    """
    코드 없이 쓴 임시 작업공간의 계산기 저장 파일(ec_anon_*.json) 중 마지막 저장 후 24시간이 지난 파일을 지웁니다.
    작업공간 코드를 넣은 파일(ec_state_*.json)은 건드리지 않습니다. (에이전트 대화방의 익명 파일 정리와 같은 방식)
    """
    now_ts = time.time()
    try:
        for fname in os.listdir(STORAGE_DIR):
            if fname.startswith("ec_anon_") and fname.endswith(".json"):
                fpath = os.path.join(STORAGE_DIR, fname)
                if (now_ts - os.path.getmtime(fpath)) > max_age_sec:
                    os.remove(fpath)
    except Exception:
        pass


def _load_ec_from_disk(ws_id: str) -> dict | None:
    path = _ec_disk_path(ws_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        # JSON 직렬화로 문자열이 된 year_recs의 연도 키를 int로 복원
        raw_yr = data.get("year_recs") or {}
        if isinstance(raw_yr, dict):
            data["year_recs"] = {
                (int(k) if str(k).isdigit() else k): v for k, v in raw_yr.items()
            }
        return data
    except Exception:
        return None


_SAVE_PENDING_KEY = "_ec_save_pending"
_SAVED_HASH_KEY = "_ec_saved_hash"


def _save_ec_to_disk(s: dict | None = None) -> None:
    """
    저장 요청만 기록합니다. 실제 쓰기는 화면을 다 그린 뒤 _flush_ec_save()에서 한 번만,
    그리고 저장할 내용이 직전 저장과 다를 때만 합니다.
    """
    st.session_state[_SAVE_PENDING_KEY] = True


def _flush_ec_save(force: bool = False) -> None:
    if not (force or st.session_state.pop(_SAVE_PENDING_KEY, False)):
        return
    _write_ec_to_disk()


def _write_ec_to_disk(s: dict | None = None) -> None:
    try:
        ws_id = st.session_state.get("loaded_workspace_id") or "default_ec"
        if s is None:
            store = st.session_state.get("ec_by_ws") or {}
            s = store.get(ws_id)
        if not isinstance(s, dict):
            return
        if ws_id == "default_ec":
            return          # 작업공간 없이 쓰는 경우 다른 사용자와 같은 파일을 공유하게 되므로 디스크에 저장하지 않음
        os.makedirs(STORAGE_DIR, exist_ok=True)
        payload = {k: s.get(k) for k in _PERSIST_KEYS if k in s}
        # 주민등록번호 뒷자리는 저장하지 않음 (계산에는 앞 7자리만 필요)
        if isinstance(payload.get("files"), dict):
            payload["files"] = {
                n: {**f, "text": _RRN_FULL_RE.sub(r"\1-\2******", str(f.get("text") or ""))}
                if isinstance(f, dict) else f
                for n, f in payload["files"].items()
            }
        text = json.dumps(payload, ensure_ascii=False, default=str)
        digest = hashlib.md5(text.encode("utf-8")).hexdigest()
        saved = st.session_state.setdefault(_SAVED_HASH_KEY, {})
        path = _ec_disk_path(ws_id)
        if saved.get(ws_id) == digest and os.path.exists(path):
            return                                   # 바뀐 내용이 없으면 쓰지 않음
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        saved[ws_id] = digest
    except Exception:
        pass


def _default_state_dict() -> dict:
    return {
        "step": 1,
        "max_step_reached": 1,
        "tax_year": R.DEFAULT_TAX_YEAR,
        "files": {},            # 파일명 → {"key": 서류종류, "text": 본문, "wp": 사업장명}
        "uploader_ver": 0,
        "ext": None,
        "ext_sig": None,
        "built_sig": None,
        "biz": {},
        "biz_confirmed": [],
        "sub_biz_list": [],     # 제2사업장 등 추가 합산 사업장 리스트 (본·지점 합산 / 양도·양수 사업장)
        "people": {},
        "year_recs": {},
        "prev_summary": {},     # 기신고 명세서(공제감면세액계산서) 또는 수기 입력 과거연도 인원·공제액·2차공제·이월액·기추징액
        "additional_inputs": {  # 육아휴직 복귀·정규직 전환·출산전후휴가 대체인력·당해 이월공제액
            "parental_return_count": 0,
            "regular_conversion_count": 0,
            "additional_clawback_count": 0,
            "maternity_replacement_count": 0.0,
            "maternity_prev_count": 0.0,
            "current_unclaimed_carryforward_won": 0,
        },
        "scheme_2026": "new_2026",
        "pm_basis": R.PM_BASIS_FILED,           # 사후관리 계산 기준: 기본값 'filed' (기신고 기준 원칙) / 선택 시 'recalc' (세법원칙 기준)
        "assume_year_end": True,                # 기중 자료 미도래 월 연말까지 재직 가정(1 자동 채움·하늘색 표시)
        "include_unpaid_hire_month": True,      # 입사월 급여 0원(익월 지급) 시 산입(1) + 살구색 표시 여부
        "use_year_tabs": False,                 # 2단계 연도별 표 표시 방식: False=전체 연속 펼쳐보기, True=연도별 탭 보기
        "show_all_4_blocks": True,              # 우측 사후관리 블록(자료 존재하는 연도) 표시 여부
        "show_empty_pm_blocks": False,          # 자료 없는 과거 사후관리 블록(예: 23년·22년) 강제 표시 여부 (기본 False = 자동 생략)
        "manual_extra_years": [],
        "grid_ver": {},
        "last_sent": {},
        "industry_alert_for": "",
        "next_pid_seq": 1,
        "corp_size_default": "중소기업",
        "corp_size_by_year": {},
        "corp_size_user_set": [],
        "yr_sz_ver": 0,
        "_last_sidebar_corp_size": "",
        "pro_audit_comment": "",
        "pro_audit_model": "",
        "pro_audit_sig": "",
    }


def _S() -> dict:
    ws_id = st.session_state.get("loaded_workspace_id") or "default_ec"
    if not st.session_state.get("_ec_anon_cleanup_done"):
        st.session_state["_ec_anon_cleanup_done"] = True     # 접속(세션)당 한 번만 정리
        _cleanup_stale_anon_ec_files()
    store = st.session_state.setdefault("ec_by_ws", {})
    if ws_id not in store:
        base = _default_state_dict()
        disk_loaded = _load_ec_from_disk(ws_id)
        if disk_loaded:
            for k, v in disk_loaded.items():
                if v is not None:
                    base[k] = v
        store[ws_id] = base
    s = store[ws_id]
    s.setdefault("sub_biz_list", [])
    s.setdefault("include_unpaid_hire_month", True)
    s.setdefault("use_year_tabs", False)
    s.setdefault("grid_ver", {})
    s.setdefault("last_sent", {})
    s.setdefault("industry_alert_for", "")
    s.setdefault("pro_audit_comment", "")
    s["max_step_reached"] = max(int(s.get("max_step_reached") or 1), int(s.get("step") or 1))
    s.setdefault("additional_inputs", {}).setdefault("maternity_prev_count", 0.0)
    b_init = s.setdefault("biz", {})
    def_sz_init = R.normalize_corp_size(
        s.get("corp_size_default") or b_init.get("기업구분") or "중소기업",
        "중소기업",
    )
    s["corp_size_default"] = def_sz_init
    b_init["기업구분"] = def_sz_init
    by_yr_init = s.setdefault("corp_size_by_year", {})
    if not isinstance(by_yr_init, dict):
        by_yr_init = {}
        s["corp_size_by_year"] = by_yr_init
    raw_uset = s.get("corp_size_user_set")
    if isinstance(raw_uset, (list, set, tuple)):
        s["corp_size_user_set"] = sorted({str(x).strip() for x in raw_uset if str(x).strip()})
    else:
        s["corp_size_user_set"] = []
    tax_yr_init = int(s.get("tax_year") or R.DEFAULT_TAX_YEAR)
    for yy_i in range(min(2021, tax_yr_init - 3), max(2030, tax_yr_init + 2)):
        by_yr_init.setdefault(str(yy_i), def_sz_init)
    if _prune_manual_without_hire(s) > 0:
        st.session_state.pop(_CALC_CACHE_KEY, None)
        _save_ec_to_disk(s)
    st.session_state.ec = s
    return s


def _prune_manual_without_hire(s: dict) -> int:
    """기존 저장 데이터에 입사일이 없는 _manual 사원이 남아 있으면 로드 시 제외하고 제외 인원수를 기록합니다."""
    people = s.get("people")
    if not isinstance(people, dict) or not people:
        return 0
    drop_pids = [
        pid
        for pid, p in list(people.items())
        if isinstance(p, dict)
        and (p.get("_manual") or str(pid).startswith("manual_"))
        and H.parse_date(p.get("입사일")) is None
    ]
    if not drop_pids:
        return 0
    for pid in drop_pids:
        people.pop(pid, None)
    year_recs = s.get("year_recs")
    if isinstance(year_recs, dict):
        for recs in year_recs.values():
            if isinstance(recs, dict):
                for pid in drop_pids:
                    recs.pop(pid, None)
    s["_pruned_manual_no_hire_count"] = int(s.get("_pruned_manual_no_hire_count") or 0) + len(drop_pids)
    return len(drop_pids)


def reset_credit_all_state() -> None:
    """
    [Feature B — 통합고용세액공제 전체 자료·내용 초기화]
    업로드된 서류, 사업자정보, 사원표, 기신고 기초값, 계산 스냅샷, 4단계 보고서 캐시 및 디스크 자동백업을
    모두 초기화하고 1단계(서류 업로드) 초기 상태로 되돌립니다.
    """
    ws_id = st.session_state.get("loaded_workspace_id") or "default_ec"
    old_s = st.session_state.get("ec") if isinstance(st.session_state.get("ec"), dict) else {}
    next_up_ver = int(old_s.get("uploader_ver") or 0) + 1
    next_yr_sz_ver = int(old_s.get("yr_sz_ver") or 0) + 1
    try:
        p_disk = _ec_disk_path(ws_id)
        if p_disk and os.path.exists(p_disk):
            os.remove(p_disk)
    except Exception:
        pass
    store = st.session_state.setdefault("ec_by_ws", {})
    store.pop(ws_id, None)
    saved_hashes = st.session_state.get(_SAVED_HASH_KEY)
    if isinstance(saved_hashes, dict):
        saved_hashes.pop(ws_id, None)
    for k in list(st.session_state.keys()):
        if str(k).startswith(("ec_biz_", "ec_sub_", "pf_", "calc_", "prev_sum_", "ec_grid_", "pm_basis")):
            del st.session_state[k]
    st.session_state.pop(_CALC_CACHE_KEY, None)
    st.session_state.pop("ec", None)
    new_s = _S()
    new_s["uploader_ver"] = next_up_ver
    new_s["yr_sz_ver"] = next_yr_sz_ver
    new_s["step"] = 1
    new_s["max_step_reached"] = 1
    _save_ec_to_disk(new_s)


def _cohort_corp_size(s: dict | None, year: int | str | None = None, default: str | None = None) -> str:
    """해당 연도의 기업규모를 돌려준다. 개별 설정 → 기본값 → 기존 biz['기업구분'] → '중소기업' 순서."""
    return R._cohort_corp_size(s, year, default=default)


def _default_workplace_label(s: dict) -> str:
    b = s.get("biz") or {}
    nm = (b.get("상호") or "").strip()
    if s.get("sub_biz_list"):
        return nm or "본점(1사업장)"
    return R.DEFAULT_WORKPLACE_NAME


def _uploaded_wht_years(s: dict, max_year: int | None = None) -> set[int]:
    """실제로 원천징수부 파일이 업로드된 연도 집합을 반환합니다 (`max_year` 지정 시 해당 연도 이하만 반환)."""
    yrs = set()
    for f in (s.get("files") or {}).values():
        fk = str(f.get("key") or "")
        if fk.startswith("wht_"):
            ys = fk.replace("wht_", "").strip()
            if ys.isdigit():
                yi = int(ys)
                if max_year is None or yi <= int(max_year):
                    yrs.add(yi)
    for y_str, rows in ((s.get("ext") or {}).get("wht") or {}).items():
        if str(y_str).isdigit() and rows:
            yi = int(y_str)
            if max_year is None or yi <= int(max_year):
                yrs.add(yi)
    return yrs


def _has_year_data(s: dict, year: int) -> bool:
    """
    특정 과세연도(예: 2024년, 2023년, 2022년)의 실제 원천징수부 급여 데이터 또는
    기신고/수기 요약 데이터가 존재하는지 확인합니다.
    """
    if year in _uploaded_wht_years(s):
        return True
    if year in (s.get("manual_extra_years") or []):
        return True
    for p in (s.get("people") or {}).values():
        if H._has_any_pay_record((p.get("월급여") or {}).get(str(year))):
            return True
    t = int(s.get("tax_year") or R.DEFAULT_TAX_YEAR)
    if year in (t, t - 1):
        if not _uploaded_wht_years(s) and any(H.worked_in_year(p, year) for p in (s.get("people") or {}).values()):
            return True
        if any(
            (p.get("_manual") or str(p.get("pid") or "").startswith("manual_")) and H.worked_in_year(p, year)
            for p in (s.get("people") or {}).values()
        ):
            return True
    ps_y = (s.get("prev_summary") or {}).get(str(year)) or {}
    if (ps_y.get("상시") or 0.0) > 0 or (ps_y.get("청년등") or 0.0) > 0 or (ps_y.get("공제세액") or 0) > 0:
        return True
    return False


def _years(s: dict) -> list[int]:
    """
    선택된 귀속사업연도(`tax_year`)를 기준으로 표시할 연도 목록을 내림차순 반환합니다.
    """
    t = int(s["tax_year"])
    active_years = {t}

    if _has_year_data(s, t - 1) or not _uploaded_wht_years(s):
        if (t - 1) >= 2022:
            active_years.add(t - 1)

    for wy in _uploaded_wht_years(s, max_year=t):
        if wy <= t:
            active_years.add(wy)

    for p in (s.get("people") or {}).values():
        for y_str, pay_obj in (p.get("월급여") or {}).items():
            if str(y_str).isdigit() and H._has_any_pay_record(pay_obj):
                yi = int(y_str)
                if yi <= t:
                    active_years.add(yi)

    for my in (s.get("manual_extra_years") or []):
        if isinstance(my, int) and my <= t:
            active_years.add(my)

    return sorted((y for y in active_years if y <= t), reverse=True)


def _all_possible_years(s: dict) -> list[int]:
    t = int(s["tax_year"])
    cands = {t - i for i in range(4)} | _uploaded_wht_years(s, max_year=t) | {
        int(my) for my in (s.get("manual_extra_years") or []) if isinstance(my, int) and int(my) <= t
    }
    return sorted((y for y in cands if y <= t), reverse=True)


def _workplace_close_month_map(s: dict, year: int) -> dict[str, int]:
    """
    합산 사유 구분이 '기중양도 사업장'이면서 해당 연도(year) 중 '폐업·양도일'이 입력된 사업장의 경우,
    양도월 이후에는 미도래 월 연말재직 가정(1 자동 채움)이 적용되지 않도록 {사업장명: 양도월} 매핑을 반환합니다.
    """
    out: dict[str, int] = {}
    for sb in (s.get("sub_biz_list") or []):
        wp_nm = str(sb.get("상호") or "").strip()
        tp = str(sb.get("구분") or "").strip()
        close_dt = H.parse_date(sb.get("폐업일"))
        if wp_nm and close_dt and close_dt.year == int(year) and ("양도" in tp or "폐업" in tp):
            out[wp_nm] = close_dt.month
    return out


def _succession_map(s: dict, year: int) -> dict[str, dict]:
    """
    포괄양수·합병·분할·법인전환 승계 사업장 중 해당 연도(year)에 승계한 사업장:
    {사업장명: {"month": 승계월, "date": 승계일, "keep_hire": 입사일 유지 여부}}
    승계일은 사이드바 '개업·양수일'을 쓰고, 비어 있으면 그 사업장 직원의 첫 급여월로 추정합니다.
    """
    out: dict[str, dict] = {}
    for sb in (s.get("sub_biz_list") or []):
        tp = str(sb.get("구분") or "")
        wp = str(sb.get("상호") or "").strip()
        if not wp or not any(k in tp for k in ("포괄양수", "승계", "합병", "분할", "법인전환")):
            continue
        d = H.parse_date(sb.get("개업일"))
        if d is None:
            first = []
            for p in (s.get("people") or {}).values():
                p_wp = str((p.get("연도별_사업장명") or {}).get(str(year)) or p.get("사업장명") or "").strip()
                p_wp_last = p_wp.split("→")[-1].strip() if "→" in p_wp else p_wp
                if p_wp != wp and p_wp_last != wp:
                    continue
                pay = (p.get("월급여") or {}).get(str(year))
                ms = [m for m in range(1, 13) if (H._get_month_pay(pay, m) or 0) > 0]
                if ms:
                    first.append(min(ms))
            if first:
                from datetime import date as _date
                d = _date(int(year), min(first), 1)
        if d is None or d.year != int(year):
            continue
        out[wp] = {"month": d.month, "date": d, "keep_hire": bool(sb.get("고용승계_입사일유지", True))}
    return out


def _transfer_out_map(s: dict, year: int) -> dict:
    """기중양도 사업장 중 '양수인이 근로자를 승계'로 표시하고 그해 양도일이 있는 사업장: {사업장명: 양도일}"""
    out = {}
    for sb in (s.get("sub_biz_list") or []):
        tp = str(sb.get("구분") or "")
        wp = str(sb.get("상호") or "").strip()
        d = H.parse_date(sb.get("폐업일"))
        if wp and "기중양도" in tp and sb.get("양도_고용승계") and d and d.year == int(year):
            out[wp] = d
    return out


def _adjusted_prev_totals(s: dict, prev_t: dict) -> tuple[dict, float, float]:
    """
    직전연도(tax_yr-1) 합계에 승계 조정을 적용한 사본을 돌려줍니다 (조특령 제23조 제13항 준용).
    - 승계한 기업: 사이드바에 입력한 피승계 사업장 직전연도 인원을 더함
    - 승계시킨 기업(기중양도·고용승계): 당해 양도로 넘어간 근로자의 직전연도 인원을 사원표에서 자동 계산해 뺌
    반환: (조정된 합계, 가산 인원, 차감 인원)
    """
    t = int(s["tax_year"])
    adj = dict(prev_t or {})
    if not adj:
        return adj, 0.0, 0.0
    m1 = int(adj.get("months_in_year") or 12)
    suc_reg, suc_yth = _succeeded_prev_headcount_sum(s)

    ded_reg = ded_yth = 0.0
    if _transfer_out_map(s, t):
        _, comp_cur, _ = _build_year_rows(s, t)
        out_pids = {pid for pid, c in comp_cur.items() if c.get("transferred_out")}
        if out_pids:
            _, comp_prev, _ = _build_year_rows(s, t - 1)
            if comp_prev:
                full = H.year_totals(list(comp_prev.values()), m1, year=t - 1)
                kept = H.year_totals([c for pid, c in comp_prev.items() if pid not in out_pids], m1, year=t - 1)
                ded_reg = round(full["상시_평균"] - kept["상시_평균"], 2)
                ded_yth = round(full["청년등_평균"] - kept["청년등_평균"], 2)

    if suc_reg or suc_yth or ded_reg or ded_yth:
        adj["상시_평균"] = round(float(adj.get("상시_평균") or 0.0) + suc_reg - ded_reg, 2)
        adj["청년등_평균"] = round(float(adj.get("청년등_평균") or 0.0) + suc_yth - ded_yth, 2)
        adj["청년외_평균"] = round(max(0.0, adj["상시_평균"] - adj["청년등_평균"]), 2)
        adj["b1_reg"], adj["b1_yth"], adj["b1_gen"] = adj["상시_평균"], adj["청년등_평균"], adj["청년외_평균"]
        adj["상시_합계"] = round(float(adj.get("상시_합계") or 0.0) + (suc_reg - ded_reg) * m1, 2)
        adj["청년등_합계"] = round(float(adj.get("청년등_합계") or 0.0) + (suc_yth - ded_yth) * m1, 2)
        adj["청년외_합계"] = round(max(0.0, adj["상시_합계"] - adj["청년등_합계"]), 2)
        if adj.get("nr_상시_평균") is not None:
            adj["nr_상시_평균"] = round(float(adj["nr_상시_평균"]) + suc_reg - ded_reg, 2)
            adj["nr_청년등_평균"] = round(float(adj.get("nr_청년등_평균") or 0.0) + suc_yth - ded_yth, 2)
            adj["nr_청년외_평균"] = round(max(0.0, adj["nr_상시_평균"] - adj["nr_청년등_평균"]), 2)
            if adj.get("nr_상시_합계") is not None:
                adj["nr_상시_합계"] = round(float(adj.get("nr_상시_합계") or 0.0) + (suc_reg - ded_reg) * m1, 2)
                adj["nr_청년등_합계"] = round(float(adj.get("nr_청년등_합계") or 0.0) + (suc_yth - ded_yth) * m1, 2)
                adj["nr_청년외_합계"] = round(max(0.0, adj["nr_상시_합계"] - adj["nr_청년등_합계"]), 2)
        adj["has_data"] = True
    return adj, suc_reg, ded_reg


def _succeeded_prev_headcount_sum(s: dict) -> tuple[float, float]:
    """
    합산 사유 구분이 '포괄양수 사업장(기중 양수)' 또는 '합병·분할·법인전환 승계'인 사업장에 입력된
    종전(피승계) 사업장 직전연도 상시·청년등 인원 합계를 반환합니다 (조특령 제26조의8 제10항).
    """
    reg_add = 0.0
    yth_add = 0.0
    for sb in (s.get("sub_biz_list") or []):
        tp = str(sb.get("구분") or "")
        if any(k in tp for k in ("포괄양수", "승계", "합병", "분할", "법인전환")):
            try:
                reg_add += float(sb.get("승계_직전상시") or 0.0)
            except (TypeError, ValueError):
                pass
            try:
                yth_add += float(sb.get("승계_직전청년") or 0.0)
            except (TypeError, ValueError):
                pass
    return round(reg_add, 2), round(yth_add, 2)


def _ctx(s: dict, year: int) -> dict:
    b = s["biz"]
    t = int(s["tax_year"])
    key = {t: "당해_월수", t - 1: "전년_월수", t - 2: "전전년_월수"}.get(year, "당해_월수")
    try:
        n = int(b.get(key, 12))
    except (TypeError, ValueError):
        n = 12
    last_m = H.detect_last_paid_month(s.get("people") or {}, year)
    yr_corp_size = _cohort_corp_size(s, year)
    return {
        "corp_size": yr_corp_size,
        "corp_size_by_year": R.get_corp_size_map(s),
        "months_in_year": n if n > 0 else 12,
        "assume_year_end": bool(s.get("assume_year_end", True)),
        "include_unpaid_hire_month": bool(s.get("include_unpaid_hire_month", True)),
        "last_paid_month": last_m,
        "workplace_close_month_map": _workplace_close_month_map(s, year),
        "wht_years": sorted(_uploaded_wht_years(s)),
        "succession_map": _succession_map(s, year),
        "transfer_out_map": _transfer_out_map(s, year),
        "old_tenure_rule": int(year) < H.NEW_TENURE_RULE_FROM,   # 2025년 이전 연도 표는 종전 규정(근로계약기간 1년 미만)
    }


# ══════════════════════════════════════════════════════════════════
# 계산 결과 재사용 (속도 개선)
# - 사원표 계산에 쓰이는 입력 전체로 '지문(fingerprint)'을 만들고, 지문이 같을 때만 이전 결과를 재사용합니다.
# - 사원·월별값·고용유형·사업자정보·추가 사업장·설정 중 하나라도 바뀌면 지문이 달라져 처음부터 다시 계산합니다.
# - 계산식은 그대로이며, 재사용할 때는 복사본을 돌려주어 화면 쪽에서 값을 고쳐도 원본이 오염되지 않습니다.
# ══════════════════════════════════════════════════════════════════
_CALC_CACHE_KEY = "_ec_calc_cache"


def _calc_fingerprint(s: dict) -> str | None:
    try:
        files_meta = sorted(
            (str(n), (f or {}).get("key"), (f or {}).get("wp", ""))
            for n, f in (s.get("files") or {}).items()
        )
        wht_years = sorted(str(k) for k, v in (((s.get("ext") or {}).get("wht")) or {}).items() if v)
        blob = json.dumps(
            {
                "people": s.get("people"),
                "year_recs": {str(k): v for k, v in (s.get("year_recs") or {}).items()},
                "biz": s.get("biz"),
                "corp_size_default": s.get("corp_size_default"),
                "corp_size_by_year": s.get("corp_size_by_year"),
                "corp_size_user_set": s.get("corp_size_user_set"),
                "sub_biz_list": s.get("sub_biz_list"),
                "tax_year": s.get("tax_year"),
                "assume_year_end": s.get("assume_year_end"),
                "include_unpaid_hire_month": s.get("include_unpaid_hire_month"),
                "manual_extra_years": s.get("manual_extra_years"),
                "files": files_meta,
                "wht_years": wht_years,
            },
            sort_keys=True, default=str, ensure_ascii=False,
        )
        return hashlib.md5(blob.encode("utf-8")).hexdigest()
    except Exception:
        return None          # 지문을 못 만들면 재사용하지 않고 항상 새로 계산


def _calc_cache(s: dict) -> tuple[dict | None, str | None]:
    fp = _calc_fingerprint(s)
    if fp is None:
        return None, None
    cache = st.session_state.get(_CALC_CACHE_KEY)
    if not isinstance(cache, dict) or cache.get("fp") != fp:
        cache = {"fp": fp, "rows": {}, "cohort": {}}
        st.session_state[_CALC_CACHE_KEY] = cache
    return cache, fp


def _cohort_youth_map(s: dict, cohort_year: int) -> dict[str, bool]:
    cache, _ = _calc_cache(s)
    if cache is not None and cohort_year in cache["cohort"]:
        return dict(cache["cohort"][cohort_year])
    out = _cohort_youth_map_uncached(s, cohort_year)
    cache, _ = _calc_cache(s)                      # 계산 중 상태가 바뀌었을 수 있으므로 다시 확인
    if cache is not None:
        cache["cohort"][cohort_year] = dict(out)
    return out


def _cohort_youth_map_uncached(s: dict, cohort_year: int) -> dict[str, bool]:
    """최초공제연도(cohort_year) 사원표 기준으로 그해 실제로 청년등이었던 사원 매핑."""
    ctx = _ctx(s, cohort_year)
    recs = (s.get("year_recs") or {}).get(cohort_year, {})
    out: dict[str, bool] = {}
    for pid, p in (s.get("people") or {}).items():
        if not H.worked_in_year(p, cohort_year):
            continue
        c = H.compute_row(p, recs.get(pid) or P.new_year_rec(), cohort_year, ctx)
        out[pid] = c["상시"] == "O" and any(c["youth_flags"])
    return out


def _compose_doc_texts_with_wp(s: dict, classified: dict[str, list[str]]) -> dict[str, str]:
    """파일별로 지정된 사업장명(`wp`)을 `<<<FILE_WP:...>>>` 마커로 감싸서 파서에 전달합니다."""
    texts: dict[str, str] = {}
    default_wp = _default_workplace_label(s)
    for k, names in classified.items():
        chunks = []
        for n in names:
            f_obj = s["files"].get(n) or {}
            raw_wp = str(f_obj.get("wp") or "").strip()
            clean_wp = _sanitize_workplace_label(raw_wp, "") or getattr(P, "infer_workplace_name", lambda nm, tx="": "")(n, f_obj.get("text", "")) or default_wp
            chunks.append(f"<<<FILE_WP:{clean_wp}>>>\n{f_obj.get('text', '')}")
        texts[k] = "\n\n".join(chunks)
    return texts


def _merge_ext_dicts(base_ext: dict | None, new_ext: dict | None) -> dict:
    """
    백업 복원(restored=True) 상태에서 새로운 파일(예: 23년 원천징수부, 24년 근로자고용현황/세액공제조정명세서 등)을 추가 업로드한 경우,
    기존 ext 데이터를 보존하면서 새로 추출된 new_ext 데이터를 병합합니다.
    """
    if not base_ext:
        return copy.deepcopy(new_ext or {})
    if not new_ext:
        return copy.deepcopy(base_ext)
    merged = copy.deepcopy(base_ext)
    for top_k in ("biz_reg", "corp_reg"):
        src = new_ext.get(top_k) or {}
        if isinstance(src, dict) and src:
            dst = merged.setdefault(top_k, {})
            for fk, fv in src.items():
                if fv:
                    dst[fk] = fv
    if new_ext.get("shareholder"):
        merged["shareholder"] = copy.deepcopy(new_ext["shareholder"])
    for yr_s, rows in ((new_ext.get("wht") or {}).items()):
        if rows:
            merged.setdefault("wht", {})[str(yr_s)] = copy.deepcopy(rows)
    if new_ext.get("credit_stmt"):
        dst_cs = merged.setdefault("credit_stmt", {})
        for k_cs, v_cs in new_ext["credit_stmt"].items():
            dst_cs[k_cs] = copy.deepcopy(v_cs)
    new_pf = ((new_ext.get("prev_filing") or {}).get("연도별")) or {}
    if isinstance(new_pf, dict) and new_pf:
        dst_pf = merged.setdefault("prev_filing", {}).setdefault("연도별", {})
        for y_s, y_vals in new_pf.items():
            if isinstance(y_vals, dict):
                cur_e = dst_pf.setdefault(str(y_s), {})
                for fk, fv in y_vals.items():
                    if fv is not None:
                        cur_e[fk] = fv
    return merged


def _carry_over_user_edits(s: dict, old_people: dict, old_recs: dict) -> None:
    """
    사원표를 다시 만들 때(귀속연도 변경·파일 추가 등) 2단계에서 직접 입력한 값을 이어 붙입니다.
    같은 사람 판정: 성명+생년월일(한쪽에만 생년월일이 있는 경우 성명 단독 매칭 지원). 서류 없이 직접 추가한 사원은 그대로 옮깁니다.
    """
    if not old_people:
        return
    key = lambda p: f"{p.get('성명', '')}|{p.get('생년월일', '')}"
    new_by_key = {key(p): pid for pid, p in s["people"].items()}
    new_by_name: dict[str, list[str]] = {}
    for pid, p in s["people"].items():
        nm = str(p.get("성명") or "").strip()
        if nm:
            new_by_name.setdefault(nm, []).append(pid)

    for opid, op in old_people.items():
        npid = new_by_key.get(key(op))
        if npid is None:
            nm = str(op.get("성명") or "").strip()
            cands = new_by_name.get(nm, [])
            if len(cands) == 1:
                npid = cands[0]
        if npid is None:
            if op.get("월급여"):
                continue  # 서류에서 온 사람인데 이번 자료 범위에 없으면 제외
            npid = opid if opid not in s["people"] else f"{opid}_m"
            s["people"][npid] = dict(op, pid=npid)  # 직접 추가한 사원
        else:
            np_ = s["people"][npid]
            for k in ("병역개월", "계약체결일"):
                if op.get(k):
                    np_[k] = op[k]
        for y, recs in old_recs.items():
            yi = int(y) if str(y).isdigit() else y
            if opid in recs and yi in s["year_recs"]:
                s["year_recs"][yi][npid] = recs[opid]


def _ensure_built_for_tax_year(s: dict):
    """
    2단계·3단계·4단계 진입 시 또는 좌측 사이드바에서 `귀속사업연도`를 변경했을 때,
    선택된 `tax_year` 이하의 자료만으로 `biz`, `sub_biz_list`, `people`, `year_recs`, `prev_summary`를 즉시 재구축합니다.
    """
    wp_sig = json.dumps(
        sorted((n, f.get("key"), f.get("wp", "")) for n, f in (s.get("files") or {}).items()),
        ensure_ascii=False,
    )
    sig = f"{s.get('ext_sig')}|{s['tax_year']}|{wp_sig}"
    if s.get("built_sig") != sig and (s.get("ext") is not None or s.get("files")):
        files_with_text: dict[str, list[str]] = {}
        for name, f in (s.get("files") or {}).items():
            if f.get("key") and f.get("text"):
                files_with_text.setdefault(f["key"], []).append(name)
        if s.get("ext") is None and files_with_text:
            texts = _compose_doc_texts_with_wp(s, files_with_text)
            s["ext"] = P.extract_all(texts, None, "")
            s["ext_sig"] = wp_sig
        elif s.get("ext") is not None and files_with_text and s.get("ext_sig") != wp_sig:
            texts = _compose_doc_texts_with_wp(s, files_with_text)
            new_ext = P.extract_all(texts, None, "")
            s["ext"] = _merge_ext_dicts(s.get("ext"), new_ext)
            s["ext_sig"] = wp_sig

        ext = s.get("ext") or {}
        tax_yr = int(s["tax_year"])
        s["biz"], s["biz_confirmed"] = P.build_biz_info(ext, tax_yr, existing_biz=s.get("biz"))
        if s.get("corp_size_default"):
            s["biz"]["기업구분"] = R.normalize_corp_size(s["corp_size_default"])
        else:
            s["corp_size_default"] = R.normalize_corp_size(s["biz"].get("기업구분", "중소기업"))
            s["biz"]["기업구분"] = s["corp_size_default"]
        s["sub_biz_list"] = P.build_sub_biz_list(ext, s["biz"], existing_sub_biz=s.get("sub_biz_list"))

        default_wp = _default_workplace_label(s)
        old_people, old_recs = s.get("people") or {}, s.get("year_recs") or {}
        s["people"], s["year_recs"] = P.build_people(
            ext,
            _all_possible_years(s),
            max_tax_year=tax_yr,
            default_workplace=default_wp,
        )
        _carry_over_user_edits(s, old_people, old_recs)
        _prune_manual_without_hire(s)

        # 인원수가 45명 이상이면 브라우저 렌더링 부하 방지를 위해 연도별 탭 뷰를 기본 활성화
        if len(s["people"]) >= 45 and not s.get("_tabs_user_touched"):
            s["use_year_tabs"] = True

        parsed_prev = P.build_prev_summary(ext, tax_yr, _cohort_corp_size(s, tax_yr), corp_size_by_year=R.get_corp_size_map(s))
        ps = s.setdefault("prev_summary", {})
        for y_str, vals in parsed_prev.items():
            if isinstance(vals, dict):
                old = ps.get(str(y_str)) or {}
                ps[str(y_str)] = {
                    "상시_총인원": vals.get("상시_총인원") if vals.get("상시_총인원") is not None else old.get("상시_총인원"),
                    "청년등_총인원": vals.get("청년등_총인원") if vals.get("청년등_총인원") is not None else old.get("청년등_총인원"),
                    "상시": vals.get("상시") if vals.get("상시") is not None else old.get("상시"),
                    "청년등": vals.get("청년등") if vals.get("청년등") is not None else old.get("청년등"),
                    "청년등외": vals.get("청년등외") if vals.get("청년등외") is not None else old.get("청년등외"),
                    "청년등_증가": vals.get("청년등_증가") if vals.get("청년등_증가") is not None else old.get("청년등_증가"),
                    "청년등외_증가": vals.get("청년등외_증가") if vals.get("청년등외_증가") is not None else old.get("청년등외_증가"),
                    "공제세액": int(vals.get("공제세액")) if vals.get("공제세액") is not None else old.get("공제세액"),
                    "2차_공제세액": int(vals.get("2차_공제세액")) if vals.get("2차_공제세액") is not None else old.get("2차_공제세액"),
                    "이월세액": int(vals.get("이월세액")) if vals.get("이월세액") is not None else old.get("이월세액"),
                    "기추징세액": int(vals.get("기추징세액")) if vals.get("기추징세액") is not None else old.get("기추징세액"),
                    "수도권": vals.get("수도권") if vals.get("수도권") is not None else old.get("수도권"),
                    "_증가_역산": bool(vals.get("_증가_역산") or old.get("_증가_역산")),
                    "_증가_추정": bool(vals.get("_증가_추정") or old.get("_증가_추정")),
                    "_2차_AI판독": bool(vals.get("_2차_AI판독")),
                    "_소재지_추정": bool(vals.get("_소재지_추정") or old.get("_소재지_추정")),
                    "_auto_filled": bool(vals.get("_auto_filled") if vals.get("상시") is None else False) or bool(old.get("_auto_filled") if vals.get("상시") is None else False),
                    "_needs_filing_check": bool(vals.get("_needs_filing_check") and old.get("공제세액") is None),
                    "_conflicts": vals.get("_conflicts") or old.get("_conflicts") or [],
                    "_conflict_selected_idx": old.get("_conflict_selected_idx", vals.get("_conflict_selected_idx", 0)),
                    "_conflict_selected_source": old.get("_conflict_selected_source") or vals.get("_conflict_selected_source"),
                }

        s["grid_ver"], s["last_sent"] = {}, {}
        s["built_sig"] = sig
        _save_ec_to_disk(s)


# ══════════════════════════════════════════════════════════════════
# 0-B. 상시근로자 명세서 A4 가로(Landscape) 정식 PDF 생성 엔진
# ══════════════════════════════════════════════════════════════════
_CACHED_PDF_FONT_PAIR: tuple[str, str] | None = None
_FONT_DOWNLOAD_ATTEMPTED: bool = False


def _ensure_korean_pdf_font() -> tuple[str, str]:
    """
    ReportLab PDF 한글 폰트 등록 및 폰트 패밀리(<b> 태그 매핑) 보장:
    - 모듈 전역 캐시(_CACHED_PDF_FONT_PAIR)를 통해 프로세스당 최초 1회만 탐색·등록하며,
      이후 _pdf_text() 수백 회 호출 시에도 0.001ms 이내에 즉시 반환합니다.
    """
    global _CACHED_PDF_FONT_PAIR, _FONT_DOWNLOAD_ATTEMPTED
    if _CACHED_PDF_FONT_PAIR is not None:
        return _CACHED_PDF_FONT_PAIR

    reg_name = "ECKoreanFont"
    bold_name = "ECKoreanFontBold"
    registered = pdfmetrics.getRegisteredFontNames()
    if reg_name in registered and bold_name in registered:
        _CACHED_PDF_FONT_PAIR = (reg_name, bold_name)
        return _CACHED_PDF_FONT_PAIR

    os.makedirs(STORAGE_DIR, exist_ok=True)
    reg_path = os.path.join(STORAGE_DIR, "NanumGothic.ttf")
    bold_path = os.path.join(STORAGE_DIR, "NanumGothicBold.ttf")

    # 후보 폰트 경로 탐색 (Windows -> 캐시 -> Linux/macOS 시스템 TrueType 한글 폰트)
    candidate_pairs = [
        ("C:/Windows/Fonts/malgun.ttf", "C:/Windows/Fonts/malgunbd.ttf"),
        (reg_path, bold_path),
        ("/usr/share/fonts/truetype/nanum/NanumGothic.ttf", "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"),
        ("/usr/share/fonts/truetype/unfonts-core/UnDotum.ttf", "/usr/share/fonts/truetype/unfonts-core/UnDotumBold.ttf"),
    ]

    chosen_reg, chosen_bold = None, None
    for rp, bp in candidate_pairs:
        if os.path.exists(rp):
            chosen_reg = rp
            chosen_bold = bp if os.path.exists(bp) else rp
            break

    if chosen_reg is None and not _FONT_DOWNLOAD_ATTEMPTED:
        _FONT_DOWNLOAD_ATTEMPTED = True
        try:
            with urllib.request.urlopen(
                "https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Regular.ttf",
                timeout=1.5,
            ) as _resp:
                with open(reg_path, "wb") as _out_f:
                    _out_f.write(_resp.read())
            with urllib.request.urlopen(
                "https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Bold.ttf",
                timeout=3,
            ) as _resp:
                with open(bold_path, "wb") as _out_f:
                    _out_f.write(_resp.read())
            if os.path.exists(reg_path):
                chosen_reg = reg_path
                chosen_bold = bold_path if os.path.exists(bold_path) else reg_path
        except Exception:
            pass

    if chosen_reg and os.path.exists(chosen_reg):
        try:
            pdfmetrics.registerFont(TTFont(reg_name, chosen_reg))
            pdfmetrics.registerFont(TTFont(bold_name, chosen_bold if (chosen_bold and os.path.exists(chosen_bold)) else chosen_reg))
            pdfmetrics.registerFontFamily(
                reg_name,
                normal=reg_name,
                bold=bold_name,
                italic=reg_name,
                boldItalic=bold_name,
            )
            _CACHED_PDF_FONT_PAIR = (reg_name, bold_name)
            return _CACHED_PDF_FONT_PAIR
        except Exception:
            pass

    if "KoreanFont" in registered:
        kf_bold = "KoreanFontBold" if "KoreanFontBold" in registered else "KoreanFont"
        try:
            pdfmetrics.registerFontFamily("KoreanFont", normal="KoreanFont", bold=kf_bold, italic="KoreanFont", boldItalic=kf_bold)
        except Exception:
            pass
        _CACHED_PDF_FONT_PAIR = ("KoreanFont", kf_bold)
        return _CACHED_PDF_FONT_PAIR

    try:
        pdfmetrics.registerFont(UnicodeCIDFont("HYGothic-Medium"))
        try:   # <b> 태그가 영문 Helvetica로 풀려 한글이 사라지지 않도록 같은 글꼴로 묶음
            pdfmetrics.registerFontFamily("HYGothic-Medium", normal="HYGothic-Medium", bold="HYGothic-Medium",
                                          italic="HYGothic-Medium", boldItalic="HYGothic-Medium")
        except Exception:
            pass
        _CACHED_PDF_FONT_PAIR = ("HYGothic-Medium", "HYGothic-Medium")
        return _CACHED_PDF_FONT_PAIR
    except Exception:
        _CACHED_PDF_FONT_PAIR = ("Helvetica", "Helvetica-Bold")
        return _CACHED_PDF_FONT_PAIR


_APP_PDF_CHAR_CAP = 150_000      # app.py 공용 읽기 함수의 글자 상한 (이 길이면 잘렸을 가능성)


def _pdf_text(t: str) -> str:
    """PDF 문단용: 특수문자 이스케이프 + 마크다운 굵게(**...**) 및 인라인 코드(`...`) 변환"""
    _, bold_font = _ensure_korean_pdf_font()
    t = str(t or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    t = re.sub(r"\*\*(.+?)\*\*", rf"<font name='{bold_font}'><b>\1</b></font>", t)
    t = re.sub(r"`([^`]+)`", rf"<font name='{bold_font}'><b>\1</b></font>", t)
    return t


def _clean_md_for_pdf(txt: str) -> str:
    return _pdf_text(txt)


def _build_review_pdf_bytes(s: dict, items: list[tuple[str, str]], pro_comment: str = "") -> bytes:
    """
    2단계 [🔍 오류 검토] 모달의 『법령·심판례·절세누락 12대 정밀 오류 검토』 결과 및
    『👑 Pro/Argon AI 심층 세무진단 코멘트』를 A4 세로(Portrait) 고해상도 정식 PDF로 생성합니다.
    (실제 TrueType 한글 폰트 임베딩으로 모든 브라우저·OS PDF 뷰어에서 한글 100% 선명 표시)
    """
    reg_font, bold_font = _ensure_korean_pdf_font()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=28,
        rightMargin=28,
        topMargin=28,
        bottomMargin=28,
    )

    styles = getSampleStyleSheet()
    st_title = ParagraphStyle(
        "ECRevTitle",
        parent=styles["Normal"],
        fontName=bold_font,
        fontSize=14,
        leading=19,
        textColor=colors.HexColor("#0f172a"),
        spaceAfter=4,
    )
    st_sub = ParagraphStyle(
        "ECRevSub",
        parent=styles["Normal"],
        fontName=reg_font,
        fontSize=9.2,
        leading=13.5,
        textColor=colors.HexColor("#334155"),
        spaceAfter=10,
    )
    st_sec = ParagraphStyle(
        "ECRevSec",
        parent=styles["Normal"],
        fontName=bold_font,
        fontSize=11,
        leading=15,
        textColor=colors.HexColor("#1e3a8a"),
        spaceBefore=10,
        spaceAfter=6,
    )
    st_item = ParagraphStyle(
        "ECRevItem",
        parent=styles["Normal"],
        fontName=reg_font,
        fontSize=9.3,
        leading=14.2,
        textColor=colors.HexColor("#1e293b"),
    )
    st_pro_body = ParagraphStyle(
        "ECRevProBody",
        parent=styles["Normal"],
        fontName=reg_font,
        fontSize=9.5,
        leading=14.8,
        textColor=colors.HexColor("#0f172a"),
        spaceAfter=4,
    )

    b = s.get("biz") or {}
    corp_nm = (b.get("상호") or "").strip()
    biz_no = (b.get("사업자번호") or "").strip()
    corp_sz = R.format_corp_size_summary_text(s)
    cap = H.is_capital_area(b.get("사업장소재지", ""))
    loc_str = "수도권" if cap is True else ("수도권 외(비수도권)" if cap is False else "")
    tax_yr = int(s.get("tax_year") or R.DEFAULT_TAX_YEAR)

    errs = [m for lv, m in (items or []) if lv == "오류"]
    savs = [m for lv, m in (items or []) if lv == "절세누락"]
    chks = [m for lv, m in (items or []) if lv not in ("오류", "절세누락")]

    story = []
    title_suffix = " (Pro/Argon 심층 세무진단 포함)" if pro_comment else ""
    story.append(
        Paragraph(
            _pdf_text((f"[{corp_nm}] " if corp_nm else "") + f"{tax_yr}년 귀속 통합고용세액공제 법령·심판례·절세누락 정밀 검토 보고서{title_suffix}"),
            st_title,
        )
    )
    story.append(
        Paragraph(
            _pdf_text(
                f"사업자등록번호: {biz_no}  |  기업규모·소재지: {corp_sz} · {loc_str}  |  "
                f"검토 요약: 필수 수정 오류 {len(errs)}건 · 절세누락 주의 {len(savs)}건 · 실무·심판례 확인 {len(chks)}건  |  "
                f"출력 {time.strftime('%Y-%m-%d %H:%M')}"
            ),
            st_sub,
        )
    )

    avail_w = A4[0] - 56

    def _add_group_table(sec_title: str, group_items: list[str], bg_hdr: str, fg_hdr: str, bg_row: str, border_c: str):
        story.append(Paragraph(_pdf_text(sec_title), st_sec))
        hdr_p = Paragraph(
            f"<font name='{bold_font}'><b>{_pdf_text(sec_title)} ({len(group_items)}건)</b></font>",
            ParagraphStyle("GH", parent=st_item, fontName=bold_font, textColor=colors.HexColor(fg_hdr)),
        )
        rows_data = [[hdr_p]]
        for idx, msg in enumerate(group_items, start=1):
            clean_m = _pdf_text(msg)
            rows_data.append([Paragraph(f"<font name='{bold_font}'><b>{idx}.</b></font> {clean_m}", st_item)])
        t = Table(rows_data, colWidths=[avail_w], repeatRows=1)
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(bg_hdr)),
                    ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor(bg_row)),
                    ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor(border_c)),
                    ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e2e8f0")),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ("LEFTPADDING", (0, 0), (-1, -1), 10),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ]
            )
        )
        story.append(t)
        story.append(Spacer(1, 8))

    if not items:
        _add_group_table(
            "1. 법령 및 조세심판례 12대 정밀 오류 검토 결과",
            ["법령 및 최신 조세심판례 12대 항목 검토 결과, 발견된 필수 수정 오류나 절세누락 사항이 없습니다."],
            "#f0fdf4", "#166534", "#ffffff", "#86efac",
        )
    else:
        if errs:
            _add_group_table(
                "1. 필수 수정 오류 (수정해야 정확한 상시근로자 수가 계산됩니다)",
                errs, "#fef2f2", "#991b1b", "#fffafa", "#fecaca",
            )
        if savs:
            _add_group_table(
                "2. 절세누락 주의 (청년·고령자·장애인·사후관리 간주 우대공제 점검)",
                savs, "#f0fdf4", "#166534", "#f7fee7", "#bbf7d0",
            )
        if chks:
            _add_group_table(
                "3. 실무·심판례 확인 사항 (사실관계가 맞다면 그대로 진행하셔도 됩니다)",
                chks, "#eff6ff", "#1e40af", "#f8fafc", "#bfdbfe",
            )

    if pro_comment and str(pro_comment).strip():
        story.append(Spacer(1, 6))
        story.append(Paragraph(_pdf_text("■ Pro/Argon AI 심층 세무진단 의견 (특수사례·판례·사후관리 리스크 점검)"), st_sec))
        pro_lines = []
        for raw_ln in str(pro_comment).splitlines():
            ln = raw_ln.strip()
            if not ln:
                continue
            ln = re.sub(r"^>+\s*", "", ln)
            ln = re.sub(r"^#{1,6}\s*", "", ln)
            clean_ln = _pdf_text(ln)
            pro_lines.append([Paragraph(clean_ln, st_pro_body)])
        if pro_lines:
            t_pro = Table(pro_lines, colWidths=[avail_w])
            t_pro.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
                        ("BOX", (0, 0), (-1, -1), 0.9, colors.HexColor("#93c5fd")),
                        ("TOPPADDING", (0, 0), (-1, -1), 5),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                        ("LEFTPADDING", (0, 0), (-1, -1), 10),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                    ]
                )
            )
            story.append(t_pro)

    doc.build(story)
    return buf.getvalue()


def _review_pdf_bytes(s: dict, items: list[tuple[str, str]]) -> bytes:
    return _build_review_pdf_bytes(s, items, pro_comment="")


def _pro_comment_pdf_bytes(s: dict, comment: str) -> bytes:
    return _build_review_pdf_bytes(s, [], pro_comment=comment)


# ══════════════════════════════════════════════════════════════════
# 1. "자율 에이전트AI" 100% 동일 톤앤매너 CSS + 고시인성 KPI 카드바 + 붉은색 PDF 버튼
# ══════════════════════════════════════════════════════════════════
CSS = """
<style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');

/* 🪟 모달(Dialog) 창 상·하단 잘림 방지, 내부 스크롤바 및 우측 하단 드래그 크기 조절(resize: both) */
div[data-testid="stDialog"] {
    display: flex !important;
    align-items: flex-start !important;
    justify-content: center !important;
    padding-top: 3vh !important;
    padding-bottom: 3vh !important;
    overflow-y: auto !important;
}
div[data-testid="stDialog"] > div[role="dialog"],
div[role="dialog"] {
    width: min(1100px, 90vw);
    min-width: 520px !important;
    max-width: 96vw !important;
    max-height: 86vh !important;
    overflow-y: auto !important;
    resize: both !important;
    margin: 0 auto !important;
    border-radius: 14px !important;
    box-shadow: 0 12px 36px rgba(15, 23, 42, 0.24) !important;
}
div[role="dialog"] li,
div[role="dialog"] p {
    font-family: 'Pretendard', 'Malgun Gothic', sans-serif !important;
    font-size: 1.12rem !important;
    line-height: 1.68 !important;
    color: #1e293b !important;
    word-break: keep-all !important;
}
/* 모달 내 법령 선택 탭: 하단 검정색 줄 + 검정 테두리 네모칸 + 좌측 상단만 타원형 + 선택 시 그린(#16a34a) */
div[role="dialog"] div[data-baseweb="tab-list"] {
    border-bottom: 2px solid #000000 !important;
    gap: 6px !important;
    padding-bottom: 0px !important;
    margin-bottom: 14px !important;
    background: transparent !important;
}
div[role="dialog"] div[data-baseweb="tab-highlight"],
div[role="dialog"] div[data-baseweb="tab-border"] {
    display: none !important;
    height: 0px !important;
    background: transparent !important;
}
div[role="dialog"] button[data-baseweb="tab"] {
    background-color: #ffffff !important;
    color: #0f172a !important;
    border: 1.5px solid #000000 !important;
    border-bottom: none !important;
    border-radius: 18px 0px 0px 0px !important;
    padding: 9px 18px !important;
    margin: 0 !important;
    min-height: 40px !important;
    font-family: 'Pretendard', 'Malgun Gothic', sans-serif !important;
    font-size: 0.96rem !important;
    font-weight: 700 !important;
    box-shadow: none !important;
    transition: all 0.12s ease-in-out !important;
}
div[role="dialog"] button[data-baseweb="tab"] p,
div[role="dialog"] button[data-baseweb="tab"] span,
div[role="dialog"] button[data-baseweb="tab"] div {
    color: #0f172a !important;
    font-weight: 700 !important;
    font-size: 0.96rem !important;
    margin: 0 !important;
}
div[role="dialog"] button[data-baseweb="tab"]:hover:not([aria-selected="true"]) {
    background-color: #f0fdf4 !important;
    color: #15803d !important;
}
div[role="dialog"] button[data-baseweb="tab"][aria-selected="true"] {
    background-color: #16a34a !important;
    color: #ffffff !important;
    border: 1.5px solid #000000 !important;
    border-bottom: none !important;
    border-radius: 18px 0px 0px 0px !important;
    font-weight: 800 !important;
}
div[role="dialog"] button[data-baseweb="tab"][aria-selected="true"] p,
div[role="dialog"] button[data-baseweb="tab"][aria-selected="true"] span,
div[role="dialog"] button[data-baseweb="tab"][aria-selected="true"] div {
    color: #ffffff !important;
    font-weight: 800 !important;
}
.ec-rev-scroll-wrap {
    max-height: 62vh;
    overflow-y: auto;
    padding-right: 6px;
}
.ec-rev-sec-hdr {
    font-size: 1.05rem;
    font-weight: 800;
    padding: 8px 14px;
    border-radius: 8px;
    margin: 10px 0 8px 0;
    display: flex;
    align-items: center;
    justify-content: space-between;
}
.ec-rev-sec-hdr.err {
    background: #fef2f2;
    color: #991b1b;
    border: 1px solid #fecaca;
}
.ec-rev-sec-hdr.sav {
    background: #f0fdf4;
    color: #166534;
    border: 1px solid #bbf7d0;
}
.ec-rev-sec-hdr.chk {
    background: #eff6ff;
    color: #1e40af;
    border: 1px solid #bfdbfe;
}
.ec-rev-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(460px, 1fr));
    gap: 8px;
    margin-bottom: 10px;
}
.ec-rev-card {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    padding: 9px 14px;
    font-size: 0.95rem;
    line-height: 1.56;
    color: #1e293b;
    word-break: keep-all;
    box-shadow: 0 1px 2px rgba(15,23,42,0.03);
}
.ec-rev-card.err {
    border-left: 4px solid #dc2626;
    background: #fffafa;
}
.ec-rev-card.sav {
    border-left: 4px solid #16a34a;
    background: #f7fee7;
}
.ec-rev-card.chk {
    border-left: 4px solid #2563eb;
    background: #f8fafc;
}

/* 🗑️ 입체감이 살아있는 [🔄 자료 초기화 (내용 비우기)] 3D 버튼 스타일 */
.st-key-btn_ec_sidebar_reset_ask button {
    background: linear-gradient(180deg, #ffffff 0%, #f1f5f9 100%) !important;
    border: 1px solid #94a3b8 !important;
    border-bottom: 2.5px solid #64748b !important;
    border-radius: 8px !important;
    min-height: 2.25rem !important;
    font-size: 0.86rem !important;
    font-weight: 700 !important;
    color: #1e293b !important;
    box-shadow: 0 2px 4px rgba(15, 23, 42, 0.08) !important;
    transition: all 0.12s ease !important;
}
.st-key-btn_ec_sidebar_reset_ask button:hover:not(:disabled) {
    background: linear-gradient(180deg, #fff1f2 0%, #ffe4e6 100%) !important;
    border-color: #f43f5e !important;
    border-bottom-color: #e11d48 !important;
    color: #be123c !important;
    transform: translateY(-1px) !important;
}
.st-key-btn_ec_sidebar_reset_ask button:active:not(:disabled) {
    transform: translateY(1px) !important;
    border-bottom-width: 1px !important;
}
.st-key-btn_ec_sidebar_reset_ask button:disabled {
    background: linear-gradient(180deg, #f8fafc 0%, #e2e8f0 100%) !important;
    border: 1px solid #cbd5e1 !important;
    border-bottom: 2.5px solid #94a3b8 !important;
    color: #64748b !important;
    opacity: 0.78 !important;
}

/* 📕 붉은색 PDF 다운로드 버튼 전용 스타일 (연도별 우측 상단 & 하단 전체 PDF 다운) */
div[class*="st-key-ec_btn_pdf_"] [data-testid="stDownloadButton"] > button,
div[class*="st-key-ec_btn_pdf_"] button {
    background: linear-gradient(135deg, #dc2626 0%, #b91c1c 100%) !important;
    color: #ffffff !important;
    border: 1px solid #991b1b !important;
    font-weight: 800 !important;
    font-size: 0.85rem !important;
    border-radius: 8px !important;
    padding: 6px 12px !important;
    min-height: 38px !important;
    box-shadow: 0 2px 5px rgba(220, 38, 38, 0.22) !important;
    transition: all 0.15s ease !important;
}
div[class*="st-key-ec_btn_pdf_"] [data-testid="stDownloadButton"] > button:hover,
div[class*="st-key-ec_btn_pdf_"] button:hover {
    background: linear-gradient(135deg, #b91c1c 0%, #991b1b 100%) !important;
    color: #ffffff !important;
    border-color: #7f1d1d !important;
    box-shadow: 0 4px 10px rgba(185, 28, 28, 0.32) !important;
    transform: translateY(-1px) !important;
}
div[class*="st-key-ec_btn_pdf_"] [data-testid="stDownloadButton"] > button p,
div[class*="st-key-ec_btn_pdf_"] button p {
    color: #ffffff !important;
    font-weight: 800 !important;
    font-size: 0.85rem !important;
}

/* 🧭 4단계 클릭형 스텝 진행바 — 완료(✓ 완료) 및 진행중 단계 클릭 즉시 이동 */
div[class*="st-key-ec_step_nav_"] [data-testid="stButton"] > button,
div[class*="st-key-ec_step_nav_"] button {
    width: 100% !important;
    min-height: 42px !important;
    padding: 8px 13px !important;
    border-radius: 9px !important;
    font-family: 'Pretendard', 'Malgun Gothic', sans-serif !important;
    font-size: 0.90rem !important;
    font-weight: 800 !important;
    letter-spacing: -0.3px !important;
    transition: all 0.15s ease !important;
    margin-bottom: 6px !important;
}
div[class*="st-key-ec_step_nav_now_"] [data-testid="stButton"] > button,
div[class*="st-key-ec_step_nav_now_"] button {
    background: linear-gradient(135deg, #16a34a 0%, #15803d 100%) !important;
    color: #ffffff !important;
    border: 1px solid #15803d !important;
    border-bottom: 3px solid #14532d !important;
    box-shadow: 0 3px 8px rgba(22, 163, 74, 0.22) !important;
}
div[class*="st-key-ec_step_nav_now_"] button p {
    color: #ffffff !important;
    font-weight: 800 !important;
}
div[class*="st-key-ec_step_nav_done_"] [data-testid="stButton"] > button,
div[class*="st-key-ec_step_nav_done_"] button {
    background: #f0fdf4 !important;
    color: #15803d !important;
    border: 1px solid #bbf7d0 !important;
    border-bottom: 3px solid #22c55e !important;
    cursor: pointer !important;
}
div[class*="st-key-ec_step_nav_done_"] button:hover {
    background: #dcfce7 !important;
    border-color: #16a34a !important;
    transform: translateY(-1px) !important;
    box-shadow: 0 2px 6px rgba(22, 163, 74, 0.16) !important;
}
div[class*="st-key-ec_step_nav_done_"] button p {
    color: #15803d !important;
    font-weight: 800 !important;
}
div[class*="st-key-ec_step_nav_wait_"] [data-testid="stButton"] > button,
div[class*="st-key-ec_step_nav_wait_"] button {
    background: #f8fafc !important;
    color: #64748b !important;
    border: 1px solid #e2e8f0 !important;
    border-bottom: 3px solid #cbd5e1 !important;
    opacity: 0.85 !important;
}
div[class*="st-key-ec_step_nav_wait_"] button p {
    color: #64748b !important;
    font-weight: 700 !important;
}

/* 4단계 자율 에이전트AI 스크린 글자크기(1.12rem) · 대제목/중제목/소제목/내용 위계 전용 스타일 */
.ec-agent-report-wrap {
    background: #ffffff;
    border: 1.5px solid #cbd5e1;
    border-top: 5px solid #1e3a8a;
    border-radius: 14px;
    padding: 30px 34px;
    margin: 10px 0 20px 0;
    box-shadow: 0 4px 16px rgba(15, 23, 42, 0.06);
    font-family: 'Pretendard', 'Malgun Gothic', sans-serif !important;
    font-size: 1.12rem !important;
    color: #0f172a !important;
    line-height: 1.78 !important;
}
/* 대제목 (H1) */
.ec-agent-report-wrap h1 {
    font-size: 1.68rem !important;
    font-weight: 900 !important;
    color: #0f172a !important;
    letter-spacing: -0.4px !important;
    padding-bottom: 14px !important;
    margin-top: 0 !important;
    margin-bottom: 18px !important;
    border-bottom: 2.5px solid #1e293b !important;
}
/* 중제목 (H2: Ⅰ. Ⅱ. Ⅲ. Ⅳ.) */
.ec-agent-report-wrap h2 {
    font-size: 1.35rem !important;
    font-weight: 900 !important;
    color: #1e3a8a !important;
    margin-top: 32px !important;
    margin-bottom: 16px !important;
    padding: 11px 18px !important;
    background: linear-gradient(90deg, #eff6ff 0%, #f8fafc 70%, #ffffff 100%) !important;
    border-left: 6px solid #1d4ed8 !important;
    border-radius: 8px !important;
    letter-spacing: -0.3px !important;
}
/* 소제목 (H3: (1) (2) (3) (4)) */
.ec-agent-report-wrap h3,
.ec-agent-report-wrap h4 {
    font-size: 1.18rem !important;
    font-weight: 800 !important;
    color: #0f172a !important;
    margin-top: 22px !important;
    margin-bottom: 10px !important;
    padding: 6px 12px !important;
    background: #f8fafc !important;
    border-left: 4px solid #2563eb !important;
    border-radius: 0 6px 6px 0 !important;
    line-height: 1.45 !important;
}
/* 본문 내용 (p, li, blockquote) */
.ec-agent-report-wrap p,
.ec-agent-report-wrap li {
    font-size: 1.12rem !important;
    line-height: 1.80 !important;
    color: #1e293b !important;
    font-weight: 500 !important;
    word-break: keep-all !important;
}
.ec-agent-report-wrap ul,
.ec-agent-report-wrap ol {
    margin-top: 6px !important;
    margin-bottom: 16px !important;
    padding-left: 22px !important;
}
.ec-agent-report-wrap li {
    margin-bottom: 8px !important;
}
.ec-agent-report-wrap del,
.ec-agent-report-wrap s {
    text-decoration: none !important;
    color: inherit !important;
}
.ec-agent-report-wrap strong,
.ec-agent-report-wrap b {
    font-weight: 800 !important;
    color: #0f172a !important;
}
.ec-agent-report-wrap a {
    display: inline-block;
    color: #1d4ed8 !important;
    background: #eff6ff !important;
    border: 1px solid #bfdbfe !important;
    border-radius: 6px !important;
    padding: 0px 7px !important;
    margin: 0 1px !important;
    font-size: 0.98rem !important;
    font-weight: 700 !important;
    line-height: 1.5 !important;
    text-decoration: none !important;
    transition: all 0.15s ease !important;
}
.ec-agent-report-wrap a:hover {
    background: #dbeafe !important;
    border-color: #60a5fa !important;
    color: #1e3a8a !important;
    text-decoration: underline !important;
}
/* 보고서 내 표 (th 내부 strong이 검은색으로 덮이지 않도록 #ffffff 강제 고정) */
.ec-agent-report-wrap table {
    width: 100% !important;
    border-collapse: collapse !important;
    margin: 10px 0 20px 0 !important;
    font-size: 1.08rem !important;
    border-top: 2px solid #1e293b !important;
    border-bottom: 2px solid #1e293b !important;
}
.ec-agent-report-wrap th,
.ec-agent-report-wrap th strong,
.ec-agent-report-wrap th b {
    background: #1e293b !important;
    color: #ffffff !important;
    font-weight: 800 !important;
    font-size: 1.08rem !important;
    padding: 12px 14px !important;
    border: 1px solid #334155 !important;
    text-align: center !important;
}
.ec-agent-report-wrap td {
    padding: 11px 14px !important;
    border: 1px solid #cbd5e1 !important;
    font-size: 1.08rem !important;
    color: #1e293b !important;
    font-weight: 600 !important;
    vertical-align: middle !important;
}
.ec-agent-report-wrap tr:nth-child(even) td {
    background: #f8fafc !important;
}
/* 보고서 내 산식/요약 카드 박스 */
.ec-rep-card {
    background: #f8fafc;
    border: 1px solid #cbd5e1;
    border-left: 4px solid #1e3a8a;
    border-radius: 10px;
    padding: 14px 18px;
    margin: 8px 0 16px 0;
}
.ec-rep-card.green {
    background: #f0fdf4;
    border-color: #bbf7d0;
    border-left: 4px solid #16a34a;
}
.ec-rep-fn-grid {
    display: flex;
    flex-direction: column;
    gap: 8px;
    margin: 8px 0 16px 0;
}
.ec-rep-fn-item {
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-left: 4px solid #475569;
    border-radius: 8px;
    padding: 11px 16px;
    font-size: 1.06rem !important;
    line-height: 1.72 !important;
    color: #1e293b;
}
.ec-rep-fn-badge {
    display: inline-block;
    background: #1e293b;
    color: #ffffff !important;
    font-size: 0.92rem;
    font-weight: 800;
    padding: 2px 8px;
    border-radius: 5px;
    margin-right: 6px;
}
.ec-model-footer-bar {
    background: #f8fafc;
    border: 1px solid #cbd5e1;
    border-left: 4px solid #1e3a8a;
    border-radius: 8px;
    padding: 10px 16px;
    margin: 8px 0 16px 0;
    font-size: 1.02rem;
    font-weight: 700;
    color: #334155;
    display: flex;
    align-items: center;
    justify-content: space-between;
}

/* 💬 1단계 하단 슬림 파일 업로드 바 */
.st-key-ec_drop {
    margin-top: 8px;
    margin-bottom: 4px;
}
.st-key-ec_drop [data-testid="stFileUploaderDropzone"] {
    min-height: 68px !important;
    padding: 10px 18px !important;
    border: 2px solid #cbd5e1 !important;
    border-left: 5px solid #16a34a !important;
    border-radius: 12px !important;
    background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%) !important;
    box-shadow: 0 2px 8px rgba(15, 23, 42, 0.06) !important;
    display: flex !important;
    align-items: center !important;
    justify-content: space-between !important;
    transition: all 0.18s ease;
}
.st-key-ec_drop [data-testid="stFileUploaderDropzone"]:hover {
    border-color: #16a34a !important;
    background: #f0fdf4 !important;
    box-shadow: 0 4px 12px rgba(22, 163, 74, 0.14) !important;
}
.ec-bottom-upload-label {
    font-size: 0.88rem;
    font-weight: 700;
    color: #1e293b;
    margin-top: 10px;
    margin-bottom: 4px;
    display: flex;
    align-items: center;
    justify-content: space-between;
}

/* 🏢 사이드바 사업자정보 입력칸 색상 구분 */
.st-key-ec_biz input:not(:disabled),
.st-key-ec_biz textarea:not(:disabled) {
    color: #1d4ed8 !important;
    background: #ffffff !important;
    font-weight: 600 !important;
}
.st-key-ec_biz input:disabled,
.st-key-ec_biz textarea:disabled {
    color: #0f172a !important;
    -webkit-text-fill-color: #0f172a !important;
    background: #e2e8f0 !important;
    font-weight: 600 !important;
}

/* 📋 1단계 서류 체크리스트 표 */
.ec-docs {
    width: 100%;
    border-collapse: collapse;
    margin: 6px 0 12px 0;
    font-size: 0.93rem;
    border-radius: 8px;
    overflow: hidden;
    box-shadow: 0 1px 3px rgba(15, 23, 42, 0.06);
    font-family: 'Pretendard', 'Malgun Gothic', sans-serif;
}
.ec-docs th {
    background-color: #1e293b !important;
    color: #ffffff !important;
    font-weight: 700 !important;
    text-align: left;
    padding: 9px 12px;
    border: 1px solid #334155;
    font-size: 0.89rem;
}
.ec-docs td {
    padding: 8px 12px;
    border: 1px solid #cbd5e1;
    color: #1e293b;
    background-color: #ffffff;
    vertical-align: middle;
    line-height: 1.45;
}
.ec-docs tr:nth-child(even) td {
    background-color: #f8fafc;
}
.ec-docs tr.on td {
    background-color: #f0fdf4 !important;
}
.ec-docs tr.extra td {
    background-color: #eff6ff !important;
}
.ec-docs td.led-cell, .ec-docs th.led-cell {
    width: 44px;
    text-align: center !important;
    padding-left: 4px;
    padding-right: 4px;
}
.ec-docs td.help {
    color: #475569;
    font-size: 0.85rem;
}
.ec-docs td.fname {
    color: #15803d;
    font-weight: 700;
    font-size: 0.85rem;
}
.ec-led {
    display: inline-block;
    width: 9px;
    height: 9px;
    border-radius: 50%;
    border: 1.5px solid #94a3b8;
    background: transparent;
}
.ec-led.on {
    border: none;
    width: 10px;
    height: 10px;
    background: #22c55e;
    box-shadow: 0 0 6px rgba(34, 197, 94, 0.65);
}
/* 🟢🟠🟡⚪ 사이드바 법령·예규 모니터링 3D 입체 원형 표시등 및 상태줄 */
.ec-law-status-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 6px 8px;
    margin-bottom: 5px;
    background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    box-shadow: inset 0 1px 0 #ffffff, 0 1px 2px rgba(15, 23, 42, 0.04);
}
.ec-law-status-left {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    font-size: 0.84rem;
    font-weight: 700;
    color: #0f172a;
    letter-spacing: -0.2px;
}
.ec-law-led-3d {
    display: inline-block;
    width: 12px;
    height: 12px;
    border-radius: 50%;
    flex-shrink: 0;
}
.ec-law-led-3d.green {
    background: radial-gradient(circle at 32% 32%, #86efac 0%, #22c55e 52%, #15803d 100%);
    border: 1px solid #15803d;
    box-shadow: inset 0 1px 2px rgba(255,255,255,0.75), 0 0 7px rgba(34, 197, 94, 0.65);
}
.ec-law-led-3d.orange {
    background: radial-gradient(circle at 32% 32%, #fdba74 0%, #f97316 52%, #c2410c 100%);
    border: 1px solid #c2410c;
    box-shadow: inset 0 1px 2px rgba(255,255,255,0.75), 0 0 8px rgba(249, 115, 22, 0.72);
}
.ec-law-led-3d.yellow {
    background: radial-gradient(circle at 32% 32%, #fef08a 0%, #facc15 52%, #b45309 100%);
    border: 1px solid #b45309;
    box-shadow: inset 0 1px 2px rgba(255,255,255,0.8), 0 0 7px rgba(250, 204, 21, 0.7);
}
.ec-law-led-3d.gray {
    background: radial-gradient(circle at 32% 32%, #f1f5f9 0%, #94a3b8 60%, #475569 100%);
    border: 1px solid #64748b;
    box-shadow: inset 0 1px 1px rgba(255,255,255,0.6);
}
.ec-law-badge-orange {
    background: #fff7ed;
    color: #c2410c;
    border: 1px solid #fdba74;
    font-size: 0.73rem;
    font-weight: 800;
    padding: 1px 7px;
    border-radius: 999px;
}
.ec-law-badge-green {
    background: #dcfce7;
    color: #15803d;
    border: 1px solid #86efac;
    font-size: 0.72rem;
    font-weight: 800;
    padding: 1px 7px;
    border-radius: 999px;
}
.st-key-btn_ec_sidebar_reset_ask button,
.st-key-btn_ec_law_detail_open button {
    background: linear-gradient(180deg, #ffffff 0%, #f1f5f9 100%) !important;
    border: 1px solid #94a3b8 !important;
    border-bottom: 3px solid #64748b !important;
    border-radius: 9px !important;
    min-height: 2.3rem !important;
    font-size: 0.86rem !important;
    font-weight: 800 !important;
    color: #0f172a !important;
    box-shadow: 0 2px 5px rgba(15, 23, 42, 0.10) !important;
    transition: all 0.12s ease !important;
}
.st-key-btn_ec_law_detail_open button:hover:not(:disabled) {
    background: linear-gradient(180deg, #eff6ff 0%, #dbeafe 100%) !important;
    border-color: #3b82f6 !important;
    border-bottom-color: #1d4ed8 !important;
    color: #1e3a8a !important;
    transform: translateY(-1px) !important;
}
.st-key-btn_ec_sidebar_reset_ask button:hover:not(:disabled) {
    background: linear-gradient(180deg, #fff1f2 0%, #ffe4e6 100%) !important;
    border-color: #f43f5e !important;
    border-bottom-color: #e11d48 !important;
    color: #be123c !important;
    transform: translateY(-1px) !important;
}
.ec-req-pill {
    display: inline-block;
    background-color: #fee2e2;
    color: #b91c1c;
    font-weight: 800;
    font-size: 0.72rem;
    padding: 1px 6px;
    border-radius: 999px;
    margin-left: 5px;
}
.ec-opt-pill {
    display: inline-block;
    background-color: #f1f5f9;
    color: #475569;
    font-weight: 700;
    font-size: 0.72rem;
    padding: 1px 6px;
    border-radius: 999px;
    margin-left: 5px;
}
.ec-extra-pill {
    display: inline-block;
    background-color: #dbeafe;
    color: #1d4ed8;
    font-weight: 800;
    font-size: 0.72rem;
    padding: 1px 6px;
    border-radius: 999px;
    margin-left: 5px;
}

/* 🎨 2단계 범례 칩 및 연도별 헤더·고시인성 대시보드 KPI 바 */
.ec-legend {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px;
    margin: 6px 0 10px 0;
    padding: 7px 12px;
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
}
.ec-legend span {
    display: inline-flex;
    align-items: center;
    padding: 3px 10px;
    border-radius: 6px;
    font-size: 0.81rem;
    font-weight: 700;
    letter-spacing: -0.2px;
}
.ec-year-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    background: linear-gradient(90deg, #eff6ff 0%, #f8fafc 65%, #ffffff 100%);
    border-left: 5px solid #1d4ed8;
    border-top: 1px solid #cbd5e1;
    border-right: 1px solid #cbd5e1;
    border-bottom: 1px solid #cbd5e1;
    padding: 8px 16px;
    border-radius: 0 8px 8px 0;
    min-height: 40px;
    margin-bottom: 4px;
    box-shadow: 0 1px 3px rgba(15, 23, 42, 0.04);
}
.ec-year-title {
    font-size: 1.08rem;
    font-weight: 900;
    color: #1e3a8a;
    white-space: nowrap;
    letter-spacing: -0.3px;
}
.ec-year-sub {
    font-size: 0.86rem;
    font-weight: 700;
    color: #334155;
    text-align: right;
}

/* ⭐ 사원 계산기 바로 밑 고시인성 KPI 요약 스트립 */
.ec-kpi-bar {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    background: linear-gradient(90deg, #f8fafc 0%, #ffffff 100%);
    border: 1.5px solid #cbd5e1;
    border-left: 6px solid #16a34a;
    border-radius: 10px;
    padding: 10px 14px;
    margin: 6px 0 26px 0;
    align-items: center;
    justify-content: space-between;
    box-shadow: 0 3px 8px rgba(15, 23, 42, 0.06);
    font-family: 'Pretendard', 'Malgun Gothic', sans-serif;
}
.ec-kpi-items {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
    align-items: center;
}
.ec-kpi-chip {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    padding: 6px 11px;
    border-radius: 8px;
    font-size: 0.91rem;
    font-weight: 700;
    color: #0f172a;
    box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}
.ec-kpi-chip.b3 {
    background: #f0fdf4;
    border: 1.5px solid #86efac;
}
.ec-kpi-chip.b4 {
    background: #eff6ff;
    border: 1.5px solid #93c5fd;
}
.ec-kpi-chip.b5 {
    background: #f5f3ff;
    border: 1.5px solid #c4b5fd;
}
.ec-kpi-chip .kpi-tag {
    font-size: 0.80rem;
    font-weight: 800;
    padding: 2px 8px;
    border-radius: 6px;
    color: #ffffff;
    letter-spacing: -0.2px;
}
.ec-kpi-chip.b3 .kpi-tag { background: #16a34a; }
.ec-kpi-chip.b4 .kpi-tag { background: #2563eb; }
.ec-kpi-chip.b5 .kpi-tag { background: #7c3aed; }
.ec-kpi-chip .kpi-main {
    font-size: 1.03rem;
    font-weight: 900;
    color: #0f172a;
}
.ec-kpi-chip.b3 .kpi-main { color: #15803d; }
.ec-kpi-chip.b4 .kpi-main { color: #1d4ed8; }
.ec-kpi-chip.b5 .kpi-main { color: #6d28d9; }
.ec-kpi-chip .kpi-sub {
    font-size: 0.86rem;
    font-weight: 700;
    color: #334155;
}
.ec-kpi-chip .kpi-sub b {
    font-size: 0.93rem;
    font-weight: 800;
    color: #0f172a;
}
.ec-kpi-total-pill {
    background: #1e293b;
    color: #ffffff;
    font-size: 0.84rem;
    font-weight: 800;
    padding: 6px 12px;
    border-radius: 8px;
    letter-spacing: -0.2px;
    white-space: nowrap;
}
.ec-kpi-total-pill b {
    color: #4ade80;
    font-size: 0.94rem;
}

.ec-law-banner {
    background-color: #f8fafc;
    border: 1px solid #e2e8f0;
    border-left: 4px solid #22c55e;
    padding: 8px 13px;
    border-radius: 7px;
    color: #334155;
    font-size: 0.88rem;
    margin-bottom: 8px;
    line-height: 1.5;
}
.ec-warn-banner {
    background-color: #fffbeb;
    border: 1px solid #fde68a;
    border-left: 5px solid #f59e0b;
    padding: 9px 13px;
    border-radius: 7px;
    color: #92400e;
    font-size: 0.88rem;
    margin-bottom: 10px;
    line-height: 1.5;
    font-weight: 600;
}
.ec-nav-divider {
    border-top: 1px dashed #cbd5e1;
    margin: 12px 0 10px 0;
}

/* 🏷️ 3단계 표 좌측 제목 + 우측 상단 사후관리 기준 배지 헤더 */
.ec-tbl-header-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    background: linear-gradient(90deg, #f8fafc 0%, #ffffff 100%);
    border-left: 5px solid #16a34a;
    padding: 8px 12px;
    border-radius: 0 8px 8px 0;
    margin-top: 10px;
    margin-bottom: 4px;
}
.ec-tbl-header-title {
    font-size: 1.05rem;
    font-weight: 800;
    color: #0f172a;
}
.ec-basis-pill-filed {
    display: inline-block;
    background-color: #dcfce7;
    color: #15803d;
    border: 1px solid #86efac;
    font-size: 0.78rem;
    font-weight: 800;
    padding: 2px 9px;
    border-radius: 999px;
    margin-left: 8px;
}
.ec-basis-pill-recalc {
    display: inline-block;
    background-color: #dbeafe;
    color: #1d4ed8;
    border: 1px solid #93c5fd;
    font-size: 0.78rem;
    font-weight: 800;
    padding: 2px 9px;
    border-radius: 999px;
    margin-left: 8px;
}

/* 📊 3단계 공제세액·사후관리 요약 카드 */
.ec-summary-card {
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-top: 4px solid #1e3a8a;
    border-radius: 10px;
    padding: 14px 16px;
    box-shadow: 0 1px 4px rgba(15, 23, 42, 0.05);
    margin-bottom: 12px;
}
.ec-summary-card.green {
    border-top-color: #16a34a;
    background: #f0fdf4;
}
.ec-summary-card.red {
    border-top-color: #dc2626;
    background: #fef2f2;
}
.ec-summary-card .card-lbl {
    font-size: 0.83rem;
    font-weight: 700;
    color: #475569;
    margin-bottom: 4px;
}
.ec-summary-card .card-val {
    font-size: 1.32rem;
    font-weight: 800;
    color: #0f172a;
}
.ec-summary-card.green .card-val {
    color: #15803d;
}
.ec-summary-card.red .card-val {
    color: #b91c1c;
}
.ec-summary-card .card-sub {
    font-size: 0.78rem;
    color: #64748b;
    margin-top: 4px;
}

/* ── 3단계 연도별 세액공제 요약 매트릭스 및 계산 구조 전용 스타일 (자율 에이전트AI 1.12rem=15.5px 폰트·시각 규격 100% 동기화) ── */
.ec-matrix-wrap {
  background:#ffffff; border:1.5px solid #cbd5e1; border-radius:14px;
  padding:20px 22px 22px 22px; margin:10px 0 22px 0;
  box-shadow:0 4px 14px rgba(15,23,42,.05);
}
.ec-matrix-title {
  font-size:1.30rem !important; font-weight:900; color:#0f172a; margin-bottom:14px;
  display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:10px;
}
.ec-matrix-tbl {
  width:100% !important; table-layout:fixed !important; border-collapse:collapse !important;
  font-size:1.12rem !important; text-align:right;
  border-top:2px solid #1e293b !important; border-bottom:2.5px solid #1e293b !important;
  border-left:1px solid #cbd5e1 !important; border-right:1px solid #cbd5e1 !important;
  margin-bottom:2px !important;
}
.ec-matrix-tbl th {
  background:#1e293b !important; color:#ffffff !important; font-weight:800 !important;
  font-size:1.12rem !important; padding:12px 14px !important;
  border:1px solid #334155 !important; text-align:center !important; white-space:nowrap;
}
.ec-matrix-tbl th.active-yr {
  background:#1d4ed8 !important; color:#ffffff !important;
  box-shadow:inset 0 -3px 0 #93c5fd;
}
.ec-matrix-tbl td {
  padding:12px 16px !important; border:1px solid #cbd5e1 !important; color:#1e293b; font-weight:700;
  font-size:1.12rem !important; font-variant-numeric:tabular-nums; white-space:nowrap;
  vertical-align:middle !important;
}
.ec-matrix-tbl td.lbl-col {
  background:#f8fafc !important; text-align:center !important; font-weight:800 !important;
  color:#1e293b !important; font-size:1.12rem !important;
}
.ec-matrix-tbl td.lbl-col[rowspan] {
  border-bottom:2.5px solid #1e293b !important;
}
.ec-matrix-tbl td.active-yr-cell {
  background:#f0f7ff !important;
}
.ec-matrix-tbl tr.ec-tot-row td {
  background:#f1f5f9 !important; font-weight:900 !important; font-size:1.20rem !important;
  border-top:2px solid #475569 !important; border-bottom:2.5px solid #1e293b !important;
  padding:13px 16px !important;
}
.ec-matrix-tbl tr.ec-tot-row td.active-yr-cell {
  background:#dbeafe !important;
}
.ec-neg-val {
  color:#dc2626 !important; font-weight:900 !important;
}
.ec-pos-val {
  color:#0f172a; font-weight:800;
}
.ec-tot-row .ec-pos-val {
  color:#1d4ed8; font-weight:900;
}
.ec-zero-val {
  color:#94a3b8; font-weight:600;
}
.ec-mat-dual {
  display:flex; align-items:center; justify-content:flex-end; gap:6px;
  line-height:1.45;
}
.ec-cell-tag {
  display:inline-block; font-size:0.84rem; font-weight:800;
  padding:1px 6px; border-radius:4px; line-height:1.3;
}
.ec-cell-tag.pos {
  background:#dcfce7; color:#15803d; border:1px solid #86efac;
}
.ec-cell-tag.neg {
  background:#fee2e2; color:#b91c1c; border:1px solid #fca5a5;
}
.ec-ctrl-bar {
  background:#f8fafc; border:1px solid #cbd5e1; border-radius:12px;
  padding:12px 18px; margin:6px 0 22px 0;
}
.ec-sec-header {
  font-size:1.32rem !important; font-weight:900; color:#1e3a8a;
  margin:24px 0 14px 0; padding:12px 18px;
  background:linear-gradient(90deg, #eff6ff 0%, #f8fafc 65%, #ffffff 100%);
  border-left:6px solid #1d4ed8; border-radius:8px;
  box-shadow:0 1px 3px rgba(15,23,42,.04);
}
.ec-sub-header {
  font-size:1.22rem !important; font-weight:800; color:#1e3a8a;
  margin:22px 0 10px 0; padding-left:2px;
  display:flex; align-items:center; gap:8px;
}
.ec-sub-num {
  display:inline-flex; align-items:center; justify-content:center;
  background:#1e3a8a; color:#ffffff; font-size:1.00rem; font-weight:800;
  padding:2px 10px; border-radius:6px;
}
.ec-inc-tbl {
  width:100%; border-collapse:collapse; font-size:1.12rem !important; margin:8px 0 18px 0;
  border-top:2px solid #1e293b !important; border-bottom:2.5px solid #1e293b !important;
  background:#ffffff;
}
.ec-inc-tbl th {
  background:#1e293b !important; color:#ffffff !important; font-weight:800 !important;
  font-size:1.12rem !important; padding:12px 18px !important;
  border:1px solid #334155 !important; text-align:center !important;
}
.ec-inc-tbl td {
  padding:12px 18px !important; border:1px solid #cbd5e1 !important; text-align:right;
  font-weight:700; font-size:1.12rem !important; color:#1e293b; font-variant-numeric:tabular-nums;
}
.ec-inc-tbl td.inc-lbl {
  text-align:center !important; font-weight:800; color:#0f172a; background:#f8fafc; width:34%;
  font-size:1.12rem !important;
}
.ec-inc-tbl td.inc-hi {
  font-weight:900; font-size:1.16rem !important; color:#1d4ed8; background:#f0f7ff;
}
/* 사후관리 요건 검토 (1차년도 대비 상시·청년 감소여부 여/부) 표시 바 */
.ec-pm-req-bar {
  display:grid; grid-template-columns:repeat(auto-fit, minmax(360px, 1fr)); gap:10px;
  background:#f8fafc; border:1.5px solid #cbd5e1; border-radius:10px;
  padding:12px 16px; margin:6px 0 10px 0;
}
.ec-pm-req-item {
  display:flex; align-items:center; justify-content:space-between; gap:10px;
  background:#ffffff; border:1px solid #e2e8f0; border-radius:8px;
  padding:9px 14px; font-size:1.10rem !important; color:#0f172a; font-weight:700;
}
.ec-pm-req-lbl {
  display:flex; flex-direction:column; gap:2px;
}
.ec-pm-req-title {
  font-size:1.10rem !important; font-weight:800; color:#0f172a;
}
.ec-pm-req-sub {
  font-size:0.96rem !important; font-weight:600; color:#475569;
}
.ec-yn-group {
  display:inline-flex; align-items:center; gap:6px; white-space:nowrap;
}
.ec-yn-pill {
  display:inline-flex; align-items:center; justify-content:center;
  padding:4px 12px; border-radius:999px; font-size:1.04rem !important; font-weight:800;
  border:1.5px solid #cbd5e1; background:#f1f5f9; color:#94a3b8;
}
.ec-yn-pill.active-no {
  background:#dcfce7 !important; color:#15803d !important; border-color:#22c55e !important;
  box-shadow:0 1px 4px rgba(22,163,74,.18);
}
.ec-yn-pill.active-yes {
  background:#fee2e2 !important; color:#dc2626 !important; border-color:#ef4444 !important;
  box-shadow:0 1px 4px rgba(220,38,38,.20);
}
.ec-yn-pill.active-na {
  background:#e2e8f0 !important; color:#475569 !important; border-color:#94a3b8 !important;
}
.ec-calc-box {
  background:#ffffff; border:1px solid #cbd5e1; border-left:5px solid #2563eb;
  border-radius:12px; padding:18px 22px; margin:8px 0 18px 0;
  display:flex; align-items:center; justify-content:space-between; gap:20px;
  box-shadow:0 2px 8px rgba(15,23,42,.04);
}
.ec-calc-box.pos-box {
  border-left:5px solid #16a34a;
}
.ec-calc-box.neg-box {
  border-left:5px solid #dc2626;
  background:#fffdfd;
}
.ec-calc-box.zero-box {
  border-left:5px solid #94a3b8;
}
.ec-calc-formula {
  flex:1; font-size:1.12rem !important; color:#1e293b; line-height:1.75;
}
.ec-calc-formula .f-title {
  font-size:1.20rem !important; font-weight:800; color:#0f172a; margin-bottom:6px;
}
.ec-calc-formula .f-line {
  font-family:'Pretendard', -apple-system, BlinkMacSystemFont, sans-serif;
  font-size:1.12rem !important; color:#1e293b; padding-left:6px; line-height:1.74;
}
.ec-calc-formula .f-sub {
  font-size:1.12rem !important; font-weight:700; color:#0f172a;
  background:#f8fafc; border:1px solid #e2e8f0; border-left:4px solid #2563eb;
  padding:8px 14px; margin-top:8px; border-radius:6px;
}
.ec-calc-amount {
  min-width:285px; text-align:right; padding:14px 20px;
  background:#f8fafc; border:1.5px solid #e2e8f0; border-radius:10px;
}
.ec-calc-amount.pos-amt {
  background:#f0fdf4; border-color:#bbf7d0;
}
.ec-calc-amount.neg-amt {
  background:#fef2f2; border-color:#fecaca;
}
.ec-calc-amount .a-lbl {
  font-size:1.02rem !important; font-weight:800; color:#475569; margin-bottom:4px;
}
.ec-calc-amount .a-val {
  font-size:1.52rem !important; font-weight:900; color:#0f172a; font-variant-numeric:tabular-nums;
  line-height:1.25;
}
.ec-calc-amount .a-val.neg {
  color:#dc2626 !important;
}
.ec-calc-amount .a-val.pos {
  color:#15803d;
}
.ec-calc-amount .a-sub-split {
  font-size:0.96rem !important; font-weight:700; color:#475569;
  margin-top:6px; padding-top:6px; border-top:1px dashed #cbd5e1;
}
.ec-law-ref-box {
  background:#f8fafc; border:1.5px solid #cbd5e1; border-left:5px solid #1e3a8a;
  border-radius:12px; padding:18px 22px; margin:24px 0 14px 0;
  font-size:1.10rem !important; color:#1e293b; line-height:1.78;
}
.ec-law-ref-box a {
  color:#1d4ed8; font-weight:800; text-decoration:none;
}
.ec-law-ref-box a:hover {
  text-decoration:underline;
}
/* 스크롤 제어용 0px iframe 컨테이너 여백 완전 제거 */
div[data-testid="stHtml"],
iframe[height="0"] {
    height: 0px !important;
    min-height: 0px !important;
    margin: 0px !important;
    padding: 0px !important;
    border: none !important;
    display: block !important;
}
</style>
"""


def _top_status_bar(s: dict):
    """자율 에이전트AI 상단과 동일한 디자인의 미니 상태바(.top-mini-status-bar)를 렌더링합니다."""
    b = s.get("biz") or {}
    corp_nm = (b.get("상호") or "").strip()
    sub_cnt = len(s.get("sub_biz_list") or [])
    if sub_cnt > 0:
        corp_nm = f"{corp_nm} 외 {sub_cnt}개 사업장 합산" if corp_nm else f"{sub_cnt + 1}개 사업장 합산"
    corp_sz = R.format_corp_size_summary_text(s)
    cap = H.is_capital_area(b.get("사업장소재지", ""))
    loc_str = "수도권" if cap is True else ("비수도권(수도권 외)" if cap is False else "")
    meta_parts = [p for p in (corp_sz, loc_str) if p]
    meta_str = " · ".join(meta_parts)
    if corp_nm:
        biz_disp = f"🏢 <b>{corp_nm}</b> ({meta_str})" if meta_str else f"🏢 <b>{corp_nm}</b>"
    else:
        biz_disp = f"🏢 <b>{meta_str}</b>"
    tax_yr = int(s.get("tax_year") or R.DEFAULT_TAX_YEAR)
    pm_lbl = R.PM_BASIS_LABELS.get(s.get("pm_basis", R.PM_BASIS_FILED), "기신고 기준")
    m_badge = R.calc_method_short_label(tax_yr, eval_year=tax_yr)
    law_ver = f"{tax_yr}귀속 ({m_badge} · 사후관리: {pm_lbl})"
    step_nm = STEPS[max(0, min(len(STEPS) - 1, int(s.get("step", 1)) - 1))]

    st.markdown(
        f"<div id='ec-page-top-anchor'></div>"
        f"<div class='top-mini-status-bar'>"
        f"<span>🧮 <b>통합고용세액공제 ({tax_yr}년 귀속)</b> &nbsp;|&nbsp; {biz_disp}</span>"
        f"<span>📌 현재 단계: <b>{s.get('step', 1)}단계 [{step_nm}]</b> &nbsp;·&nbsp; <span class='sb-badge-green'>💾 자동보관 ON · {law_ver}</span></span>"
        f"</div>",
        unsafe_allow_html=True,
    )
    pruned_n = int(s.pop("_pruned_manual_no_hire_count", 0) or 0)
    if pruned_n > 0:
        st.warning(f"ℹ️ 입사일 미입력 수기 사원 {pruned_n}명 제외")
        _save_ec_to_disk(s)




def _trigger_scroll_to_top(s: dict) -> None:
    """단계 이동(다음/이전/처음으로/상단 스텝바) 시 화면 최상단 스크롤 예약"""
    s["_force_scroll_top"] = True
    s["_scroll_top_seq"] = int(s.get("_scroll_top_seq") or 0) + 1


def _render_scroll_to_top_if_needed(s: dict) -> None:
    """
    단계(step)가 변경되었거나 하단 [다음]/[이전]/[처음으로] 버튼을 눌러 페이지가 전환된 경우,
    브라우저의 모든 Streamlit 메인 스크롤 컨테이너를 최상단(top: 0)으로 즉시 이동시킵니다.
    (AG Grid 등 대용량 컴포넌트 마운트 직후에도 최상단을 유지하도록 다중 타이밍 보정 적용)
    """
    cur_step = int(s.get("step") or 1)
    last_step = s.get("_last_rendered_step")
    force_flag = bool(s.pop("_force_scroll_top", False))

    if last_step != cur_step or force_flag:
        s["_last_rendered_step"] = cur_step
        seq = int(s.get("_scroll_top_seq") or 0) + 1
        s["_scroll_top_seq"] = seq
        st.iframe(
            f"""<!-- ec_scroll_top_{cur_step}_{seq} -->
            <script>
            (function() {{
                function scrollAllToTop() {{
                    try {{
                        var doc = window.parent.document;
                        var win = window.parent;
                        win.scrollTo({{top: 0, left: 0, behavior: 'instant'}});
                        var anchor = doc.getElementById('ec-page-top-anchor');
                        if (anchor && anchor.scrollIntoView) {{
                            anchor.scrollIntoView({{block: 'start', inline: 'nearest', behavior: 'instant'}});
                        }}
                        var selectors = [
                            '[data-testid="stAppViewContainer"]',
                            '[data-testid="stMain"]',
                            '[data-testid="stMainBlockContainer"]',
                            'section.main',
                            '.main',
                            'html',
                            'body'
                        ];
                        for (var i = 0; i < selectors.length; i++) {{
                            var nodes = doc.querySelectorAll(selectors[i]);
                            for (var j = 0; j < nodes.length; j++) {{
                                nodes[j].scrollTop = 0;
                                if (nodes[j].scrollTo) {{
                                    nodes[j].scrollTo({{top: 0, left: 0, behavior: 'instant'}});
                                }}
                            }}
                        }}
                        var allNodes = doc.querySelectorAll('div, section, main');
                        for (var k = 0; k < allNodes.length; k++) {{
                            var el = allNodes[k];
                            if (el.scrollTop > 0) {{
                                if (el.closest && (el.closest('[data-testid="stSidebar"]') || el.closest('.ag-root-wrapper'))) {{
                                    continue;
                                }}
                                el.scrollTop = 0;
                            }}
                        }}
                    }} catch (e) {{}}
                }}
                scrollAllToTop();
                setTimeout(scrollAllToTop, 25);
                setTimeout(scrollAllToTop, 90);
                setTimeout(scrollAllToTop, 200);
            }})();
            </script>
            """,
            height=1,  # st.iframe는 0을 허용하지 않음 (스크롤 스크립트 실행용 1px 숨김 프레임)
        )


def _progress(step: int):
    s = _S()
    has_data = bool(s.get("people") or s.get("files") or (s.get("biz") or {}).get("상호"))
    max_reached = max(int(s.get("max_step_reached") or 1), int(step or 1))
    if has_data and int(step or 1) >= 2:
        max_reached = max(max_reached, 4)
    s["max_step_reached"] = max_reached

    cols = st.columns(len(STEPS), gap="small")
    for i, name in enumerate(STEPS, start=1):
        unlocked = (i <= max_reached) or (i == 1)
        if i == step:
            state_cls = "now"
            btn_label = f"{i}. {name}   [진행중]"
        elif unlocked:
            state_cls = "done"
            btn_label = f"{i}. {name}   [✓ 완료]"
        else:
            state_cls = "wait"
            btn_label = f"{i}. {name}   [대기]"

        with cols[i - 1]:
            with st.container(key=f"ec_step_nav_{state_cls}_{i}"):
                if st.button(
                    btn_label,
                    key=f"btn_step_jump_{i}",
                    disabled=(not unlocked),
                    width="stretch",
                    help=(
                        f"{i}단계({name}) 화면으로 바로 이동합니다."
                        if unlocked
                        else "이전 단계를 완료하면 클릭하여 이동할 수 있습니다."
                    ),
                ):
                    if i != step:
                        if i >= 2:
                            _ensure_built_for_tax_year(s)
                        if i >= 3:
                            s["totals_snapshot"] = _ensure_totals_snapshot(s)
                        s["step"] = i
                        s["max_step_reached"] = max(int(s.get("max_step_reached") or 1), i)
                        _trigger_scroll_to_top(s)
                        _save_ec_to_disk(s)
                        st.rerun()


# ══════════════════════════════════════════════════════════════════
# 3-1. 작업 백업 (비밀번호 암호화 파일로 내 PC에 저장 / 다시 불러오기)
# ══════════════════════════════════════════════════════════════════
def _current_build_sig(s: dict) -> str:
    """_ensure_built_for_tax_year와 같은 방식의 작업 서명 (복원 후 불필요한 재구축 방지용 · 기업규모 설정 포함)"""
    wp_sig = json.dumps(
        sorted((n, f.get("key"), f.get("wp", "")) for n, f in (s.get("files") or {}).items()),
        ensure_ascii=False,
    )
    sz_sig = json.dumps(
        {
            "def": s.get("corp_size_default"),
            "by_yr": s.get("corp_size_by_year"),
            "uset": s.get("corp_size_user_set"),
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return f"{s.get('ext_sig')}|{s['tax_year']}|{wp_sig}|{sz_sig}"


# ══════════════════════════════════════════════════════════════════
# 5. 2단계: 사원정보 표 (5대 시각 개선 + 연도별 붉은 [📕 PDF 다운] + 하단 [📕 전체 PDF 다운])
# ══════════════════════════════════════════════════════════════════
JS_LOCKED = JsCode("""
function(p){
  if (p.node.rowPinned) return false;
  const L = (p.data._lock || '').split(',');
  return !L.includes(p.colDef.field);
}""")

JS_STYLE = JsCode("""
function(p){
  const baseFont = {fontFamily: 'Pretendard, Malgun Gothic, sans-serif', fontSize: '12.6px', paddingLeft: '3px', paddingRight: '3px', overflow: 'visible', textOverflow: 'clip'};
  if (p.node.rowPinned) return Object.assign(baseFont, {backgroundColor:'#dcfce7', color:'#14532d', fontWeight:'800'});
  if (p.data._class_diff === '1') return Object.assign(baseFont, {backgroundColor:'#ffedd5', color:'#9a3412', fontWeight:'800', borderBottom:'1.5px solid #f97316'});
  const L = (p.data._lock || '').split(',');
  if (L.includes(p.colDef.field)) return Object.assign(baseFont, {backgroundColor:'#e2e8f0', color:'#0f172a', fontWeight:'600'});
  return Object.assign(baseFont, {backgroundColor:'#ffffff', color:'#1d4ed8', fontWeight:'600'});
}""")

JS_STYLE_WORKPLACE = JsCode("""
function(p){
  const baseFont = {fontFamily: 'Pretendard, Malgun Gothic, sans-serif', fontSize: '12.4px', textAlign: 'center', paddingLeft: '3px', paddingRight: '3px', overflow: 'visible', textOverflow: 'clip'};
  if (p.node.rowPinned) return Object.assign(baseFont, {backgroundColor:'#dcfce7', color:'#14532d', fontWeight:'800'});
  const v = String(p.value || '');
  if (v.includes('→')) return Object.assign(baseFont, {backgroundColor:'#dbeafe', color:'#1e40af', fontWeight:'800'});
  return Object.assign(baseFont, {backgroundColor:'#f8fafc', color:'#334155', fontWeight:'700'});
}""")

JS_STYLE_CENTER = JsCode("""
function(p){
  const baseFont = {fontFamily: 'Pretendard, Malgun Gothic, sans-serif', fontSize: '12.6px', textAlign: 'center', paddingLeft: '3px', paddingRight: '3px', overflow: 'visible', textOverflow: 'clip'};
  if (p.node.rowPinned) return Object.assign(baseFont, {backgroundColor:'#dcfce7', color:'#14532d', fontWeight:'800'});
  const L = (p.data._lock || '').split(',');
  if (L.includes(p.colDef.field)) return Object.assign(baseFont, {backgroundColor:'#e2e8f0', color:'#0f172a', fontWeight:'600'});
  return Object.assign(baseFont, {backgroundColor:'#ffffff', color:'#1d4ed8', fontWeight:'600'});
}""")

JS_STYLE_EXCL = JsCode("""
function(p){
  const baseFont = {fontFamily: 'Pretendard, Malgun Gothic, sans-serif', fontSize: '12.4px', textAlign: 'center', paddingLeft: '3px', paddingRight: '3px', overflow: 'visible', textOverflow: 'clip'};
  if (p.node.rowPinned) return Object.assign(baseFont, {backgroundColor:'#dcfce7', color:'#14532d', fontWeight:'800'});
  const v = String(p.value || '');
  if (v && v !== '해당없음') return Object.assign(baseFont, {backgroundColor:'#fef2f2', color:'#b91c1c', fontWeight:'800'});
  const L = (p.data._lock || '').split(',');
  if (L.includes(p.colDef.field)) return Object.assign(baseFont, {backgroundColor:'#e2e8f0', color:'#64748b', fontWeight:'500'});
  return Object.assign(baseFont, {backgroundColor:'#ffffff', color:'#64748b', fontWeight:'500'});
}""")

JS_STYLE_YOUTH = JsCode("""
function(p){
  const baseFont = {fontFamily: 'Pretendard, Malgun Gothic, sans-serif', fontSize: '12.4px', textAlign: 'center', paddingLeft: '3px', paddingRight: '3px', overflow: 'visible', textOverflow: 'clip'};
  if (p.node.rowPinned) return Object.assign(baseFont, {backgroundColor:'#dcfce7', color:'#14532d', fontWeight:'800'});
  const v = String(p.value || '');
  if (v && !v.startsWith('해당없음')) return Object.assign(baseFont, {backgroundColor:'#f0fdf4', color:'#15803d', fontWeight:'800'});
  const L = (p.data._lock || '').split(',');
  if (L.includes(p.colDef.field)) return Object.assign(baseFont, {backgroundColor:'#e2e8f0', color:'#64748b', fontWeight:'500'});
  return Object.assign(baseFont, {backgroundColor:'#ffffff', color:'#64748b', fontWeight:'500'});
}""")

JS_STYLE_REGULAR = JsCode("""
function(p){
  const baseFont = {fontFamily: 'Pretendard, Malgun Gothic, sans-serif', fontSize: '12.8px', textAlign: 'center', paddingLeft: '2px', paddingRight: '2px', overflow: 'visible', textOverflow: 'clip'};
  if (p.node.rowPinned) return Object.assign(baseFont, {backgroundColor:'#dcfce7', color:'#14532d', fontWeight:'800'});
  const ovr = p.data._sovr === '1';
  const base = p.value === 'O'
    ? Object.assign(baseFont, {color:'#15803d', fontWeight:'800', backgroundColor:'#f0fdf4'})
    : Object.assign(baseFont, {color:'#b91c1c', fontWeight:'800', backgroundColor:'#fef2f2'});
  if (ovr) { base.border = '2px solid #f59e0b'; }
  return base;
}""")

JS_MONTH_EDITABLE = JsCode("""
function(p){
  if (p.node.rowPinned) return false;
  const i = parseInt(p.colDef.field.slice(1)) - 1;
  if ((p.data._inact || '')[i] === '1') return false;
  return !(p.data._lock || '').split(',').includes('M');
}""")

JS_MONTH_STYLE = JsCode("""
function(p){
  const s = {fontFamily: 'Pretendard, Malgun Gothic, sans-serif', fontSize: '12.6px', textAlign:'center', paddingLeft:'1px', paddingRight:'1px', overflow: 'visible', textOverflow: 'clip'};
  if (p.node.rowPinned) return Object.assign(s, {backgroundColor:'#dcfce7', color:'#14532d', fontWeight:'800'});
  const i = parseInt(p.colDef.field.slice(1)) - 1;
  if ((p.data._inact || '')[i] === '1') { s.backgroundColor = '#f1f5f9'; s.color = '#cbd5e1'; return s; }
  if ((p.data._lock || '').split(',').includes('M')) { s.backgroundColor = '#e2e8f0'; s.color = '#94a3b8'; return s; }
  s.color = '#0f172a';
  s.fontWeight = '700';
  s.backgroundColor = (p.data._ymask || '')[i] === '1' ? '#dcfce7' : '#ffffff';
  if ((p.data._proj || '')[i] === '1') { s.backgroundColor = '#e0f2fe'; s.color = '#0369a1'; }
  if ((p.data._nopay || '')[i] === '1') { s.backgroundColor = '#ffedd5'; s.color = '#c2410c'; }
  if ((p.data._movr || '')[i] === '1') { s.border = '2px solid #f59e0b'; s.fontWeight = '800'; }
  return s;
}""")

JS_YOUTH_PARAMS = JsCode("""
function(p){ return {values: (p.data._yopts || '').split('|')}; }""")

JS_NUM_FMT = JsCode("""
function(p){
  if (p.value === null || p.value === undefined || p.value === '') return '';
  const v = Number(p.value); if (isNaN(v)) return p.value;
  return (Math.round(v * 100) / 100).toString();
}""")

JS_DEC2_FMT = JsCode("""
function(p){
  if (p.value === null || p.value === undefined || p.value === '') return '';
  const v = Number(p.value); if (isNaN(v)) return p.value;
  return v.toFixed(2);
}""")

JS_DATE_FMT = JsCode("""
function(p){
  if (!p.value) return '';
  return String(p.value).replace(/-/g, '.');
}""")

JS_NAME_FMT = JsCode("""
function(p){
  if (!p.value) return '';
  if (p.node && p.node.rowPinned) return p.value;
  if (p.data && p.data._manual === '1') return p.value + ' [수기 추가]';
  return p.value;
}""")


def _block_titles_for_year(year: int, two_line: bool = False) -> tuple[str, str, str]:
    y0 = int(year)
    y1 = y0 - 1
    y2 = y0 - 2
    m0 = R.calc_method_short_label(y0, eval_year=y0)
    m1 = R.calc_method_short_label(y1, eval_year=y0)
    m2 = R.calc_method_short_label(y2, eval_year=y0)
    if two_line:
        return (
            f"3. {y0}년\n세액공제({m0})",
            f"4. {y1}년\n1차 사후관리({m1})",
            f"5. {y2}년\n2차 사후관리({m2})",
        )
    return (
        f"3. {y0 % 100:02d}년 세액공제({m0})",
        f"4. {y1 % 100:02d}년 1차 사후관리({m1})",
        f"5. {y2 % 100:02d}년 2차 사후관리({m2})",
    )


def _is_emp_id_token_safe(tok: str) -> bool:
    """parsers._is_employee_id_token이 없는 구버전 parsers.py와 함께 실행되더라도 AttributeError가 절대 나지 않도록 자체 내장한 안전 판별기."""
    fn = getattr(P, "_is_employee_id_token", None)
    if callable(fn):
        try:
            return bool(fn(tok))
        except Exception:
            pass
    s = (tok or "").strip()
    if not s or s.lower() in ("nan", "none", "-", "사번", "번호", "no", "년", "월", "일"):
        return True
    if any(noise in s for noise in ("첨부", "파일명", "엑셀", "시트명", "페이지", "Unnamed", "명:")):
        return True
    if s.isdigit():
        return True
    if re.match(r"^[A-Za-z0-9_\-.]+$", s):
        return True
    if re.match(r"^(?:사번?|사원|번호|일련번호|no\.?|id|emp)?[-_.\s]*\d+호?$", s, flags=re.IGNORECASE):
        return True
    if re.search(r"\d{2,}$", s):
        return True
    return False


def _sanitize_workplace_label(raw_wp: str, default_wp: str) -> str:
    """
    사번('사001' 등)이나 파일 헤더 노이즈('첨부 엑셀 명: 년' 등)가 이전 세션에 남아 있는 경우
    자동으로 깨끗한 사업장명('본점' 등)으로 교정합니다.
    """
    s = (raw_wp or "").strip()
    if not s:
        return default_wp
    noise_marks = ("첨부", "엑셀", "파일명", "명:", "시트", "원천징수", "급여대장", "사원대장", "공제감면", "계산서")
    if "→" in s:
        parts = []
        for pt in s.split("→"):
            pt_c = pt.strip()
            if not pt_c:
                continue
            if _is_emp_id_token_safe(pt_c) or any(k in pt_c for k in noise_marks) or pt_c in ("년", "월"):
                pt_c = default_wp
            if pt_c and pt_c not in parts:
                parts.append(pt_c)
        return "→".join(parts) if parts else default_wp
    if _is_emp_id_token_safe(s) or any(k in s for k in noise_marks) or s in ("년", "월", "귀속"):
        return default_wp
    return s


def _build_year_rows(s: dict, year: int) -> tuple[list[dict], dict, dict]:
    """연도별 사원표 계산 (같은 입력이면 이전 결과의 복사본을 돌려줌)"""
    s["year_recs"].setdefault(year, {})
    for pid in (s.get("people") or {}):          # 계산 전에 연도별 입력칸을 먼저 만들어 지문이 흔들리지 않게 함
        if H.worked_in_year(s["people"][pid], year):
            s["year_recs"][year].setdefault(pid, P.new_year_rec())
    cache, _ = _calc_cache(s)
    if cache is not None and year in cache["rows"]:
        return copy.deepcopy(cache["rows"][year])
    result = _build_year_rows_uncached(s, year)
    cache, _ = _calc_cache(s)
    if cache is not None:
        cache["rows"][year] = copy.deepcopy(result)
    return result


def _build_year_rows_uncached(s: dict, year: int) -> tuple[list[dict], dict, dict]:
    people, recs = s["people"], s["year_recs"].setdefault(year, {})
    ctx = _ctx(s, year)
    ctx["cohort_youth_map"] = {
        year - 1: _cohort_youth_map(s, year - 1),
        year - 2: _cohort_youth_map(s, year - 2),
    }
    default_wp = _default_workplace_label(s)
    computed, rows = {}, []
    for pid, p in people.items():
        if not H.worked_in_year(p, year):
            continue
        yrec = recs.setdefault(pid, P.new_year_rec())
        c = H.compute_row(p, yrec, year, ctx)
        computed[pid] = c

        unlocked = yrec.get("_unlocked")
        lock = []
        if not unlocked:
            lock += [f for f in ("성명", "생년월일", "입사일", "퇴사일") if f in (p.get("_confirmed") or [])]
            # 고용유형은 원천징수부만으로 확정할 수 없으므로 항상 열림 상태로 유지
            if p.get("주주관계") or p.get("외국인"):
                lock.append("제외사유")
        if c["excl_locked"]:
            lock.append("제외사유")
        if c["상시"] == "X":
            lock += ["청년등", "M"]
        if c["상시"] == "X" or (yrec.get("고용유형") or R.EMP_REGULAR) in R.EMP_NOT_YOUTH_REGULAR:
            lock.append("병역개월")

        ovr = {int(k) for k in (yrec.get("월_override") or {}) if str(k).isdigit()}
        yr_ret = (p.get("연도별_퇴사일") or {}).get(str(year))
        raw_retire = yr_ret if yr_ret is not None else p.get("퇴사일", "")
        ret_dt = H.parse_date(raw_retire)
        if ret_dt and ret_dt.year > int(year) and c["제외사유"] != R.EXCL_UNDER_1Y:
            disp_retire = ""
        else:
            disp_retire = raw_retire

        yr_wp = (p.get("연도별_사업장명") or {}).get(str(year))
        disp_wp = _sanitize_workplace_label(yr_wp or p.get("사업장명") or default_wp, default_wp)
        if not s.get("sub_biz_list") and "→" not in disp_wp and disp_wp == (s.get("biz", {}).get("상호") or "").strip():
            disp_wp = R.DEFAULT_WORKPLACE_NAME

        c_age = c.get("취업연령")
        age_str = f"{c_age}세" if c_age is not None else "-"

        row = {
            "pid": pid,
            "사업장명": disp_wp,
            "성명": p.get("성명", ""),
            "생년월일": p.get("생년월일", ""),
            "입사일": p.get("입사일", ""),
            "퇴사일": disp_retire,
            "취업연령": age_str,
            "고용유형": yrec.get("고용유형") or R.EMP_REGULAR,
            "제외사유": c["제외사유"],
            "병역개월": int(p.get("병역개월", 0) or 0),
            "청년등": c["청년등"],
            "상시": c["상시"],
            **{MONTH_COLS[i]: c["months"][i] for i in range(12)},
            "합계": float(c["row_sum"]),
            "b1_yth": c["b1_yth"],
            "b1_gen": c["b1_gen"],
            "b1_reg": c["b1_reg"],
            "b2_yth": c["b2_yth"],
            "b2_gen": c["b2_gen"],
            "b2_reg": c["b2_reg"],
            "b3_yth": c["b3_yth"],
            "b3_gen": c["b3_gen"],
            "b3_reg": c["b3_reg"],
            "b4_yth": c["b4_yth"],
            "b4_gen": c["b4_gen"],
            "b4_reg": c["b4_reg"],
            "_lock": ",".join(lock),
            "_yopts": "|".join(c["youth_options"]),
            "_ymask": "".join("1" if f else "0" for f in c["youth_flags"]),
            "_inact": "".join("1" if v is None else "0" for v in c["months"]),
            "_nopay": "".join(
                "1" if ((i + 1) in c["no_pay_months"] or (i + 1) in c.get("hire_month_nopay", [])) else "0"
                for i in range(12)
            ),
            "_proj": "".join("1" if (i + 1) in c.get("projected_months", []) else "0" for i in range(12)),
            "_movr": "".join("1" if (i + 1) in ovr else "0" for i in range(12)),
            "_manual": "1" if (p.get("_manual") or str(pid).startswith("manual_")) else "0",
            "_sovr": "1" if yrec.get("상시_override") else "0",
            "_sauto": c["상시_auto"],
            "_class_diff": "1" if (yrec.get("_class_diff") or p.get("_class_diff")) else "0",
            "_class_diff_msg": str(yrec.get("_class_diff_msg") or p.get("_class_diff_msg") or ""),
            "A_b1_yth": c.get("A_b1_yth", c["b1_yth"]),
            "A_b1_gen": c.get("A_b1_gen", c["b1_gen"]),
            "A_b1_reg": c.get("A_b1_reg", c["b1_reg"]),
            "B_b1_yth": c.get("B_b1_yth", c["b1_yth"]),
            "B_b1_gen": c.get("B_b1_gen", c["b1_gen"]),
            "B_b1_reg": c.get("B_b1_reg", c["b1_reg"]),
        }
        rows.append(row)
    totals = H.year_totals(list(computed.values()), ctx["months_in_year"], year=year)
    totals["has_data"] = len(rows) > 0
    _apply_tenure_transition(s, year, ctx, people, recs, computed, rows, totals)
    return rows, computed, totals


def _apply_tenure_transition(s, year, ctx, people, recs, computed, rows, totals) -> None:
    """
    1) 근로기간 1년 미만 경과조치(법률 제21223호 부칙 제34조 · 대통령령 제35999호 부칙 제2조):
       2024·2025년 최초공제분과 그 연속공제·사후관리 연도는 종전 규정(근로계약기간 1년 미만),
       2026년 이후 최초공제분은 개정 규정(실제 근로기간 1년 미만)을 적용합니다.
    2) 일관된 해석 기준 다년도 비교인원 자동 재산정(2026년 이후 신법 A·B·C):
       당해 과세연도(tax_yr >= 2026)의 신법 공제 계산 시 비교 대상이 되는 과거 과세연도(2025 <= y < tax_yr)는
       당해 공제 인원과 동일한 잣대(tax_yr 종료일까지 확정된 실제 근로기간 1년 미만 퇴사자 제외)로
       비교연도 인원(nr_상시_평균·nr_청년등_평균·nr_청년외_평균)을 재산정합니다.
    """
    NEW = H.NEW_TENURE_RULE_FROM
    y = int(year)
    tax_yr = int((s or {}).get("tax_year") or 0)

    # (1) 2026년 이후 연도 표에서 2024·2025년 귀속분 구법 사후관리 블록(b2·b3) 종전 규정 재산정
    if y >= NEW and ((y - 1) < NEW or (y - 2) < NEW):
        ctx_old = dict(ctx, old_tenure_rule=True, as_of_year=None)
        alt_old = {}
        for pid, c in computed.items():
            yrec = recs.get(pid) or {}
            if c["제외사유"] == R.EXCL_UNDER_1Y and "제외사유" not in (yrec.get("_user_set") or []):
                alt_old[pid] = H.compute_row(people[pid], yrec, y, ctx_old)
        if alt_old:
            t_old = H.year_totals([alt_old.get(pid, c) for pid, c in computed.items()], ctx["months_in_year"], year=y)
            for blk, cohort in (("b2", y - 1), ("b3", y - 2)):
                if cohort >= NEW:
                    continue
                for k in ("yth", "gen", "reg", "yth_act"):
                    totals[f"{blk}_{k}"] = t_old[f"{blk}_{k}"]
                    if f"A_{blk}_{k}" in t_old:
                        totals[f"A_{blk}_{k}"] = t_old[f"A_{blk}_{k}"]
                    if f"B_{blk}_{k}" in t_old:
                        totals[f"B_{blk}_{k}"] = t_old[f"B_{blk}_{k}"]
                for k in ("청년등_합계", "청년외_합계"):
                    totals[f"{blk}_{k}"] = t_old[f"{blk}_{k}"]
                for r in rows:
                    c_old = alt_old.get(r["pid"])
                    if c_old:
                        r[f"{blk}_yth"], r[f"{blk}_gen"], r[f"{blk}_reg"] = c_old[f"{blk}_yth"], c_old[f"{blk}_gen"], c_old[f"{blk}_reg"]
            totals["old_rule_pm_names"] = sorted(people[pid].get("성명", "") for pid in alt_old)

    # (2) 2026년 이후 신법(A·B·C) 비교 대상 연도(2025 <= y < tax_yr)의 일관된 해석 기준 재산정(nr_ — A·B 모두 보관)
    if tax_yr >= NEW and (NEW - 1) <= y < tax_yr:
        ctx_new = dict(ctx, old_tenure_rule=False, as_of_year=tax_yr)
        alt_new = {}
        for pid, c in computed.items():
            yrec = recs.get(pid) or {}
            if (
                c["상시"] == "O"
                and "제외사유" not in (yrec.get("_user_set") or [])
                and H.tenure_under_1y(people[pid], y, as_of_year=tax_yr)
            ):
                alt_new[pid] = H.compute_row(people[pid], yrec, y, ctx_new)
        t_new = H.year_totals([alt_new.get(pid, c) for pid, c in computed.items()], ctx["months_in_year"], year=y) if alt_new else totals
        # 신법 A·B·C 비교연도 인원은 calc_method_for(tax_yr) == 'B'가 정본이며, A·B 두 값을 모두 보관
        totals["nr_A_상시_평균"] = t_new.get("A_상시_평균", t_new["상시_평균"])
        totals["nr_A_청년등_평균"] = t_new.get("A_청년등_평균", t_new["청년등_평균"])
        totals["nr_A_청년외_평균"] = t_new.get("A_청년외_평균", t_new["청년외_평균"])
        totals["nr_B_상시_평균"] = t_new.get("B_상시_평균", t_new["상시_평균"])
        totals["nr_B_청년등_평균"] = t_new.get("B_청년등_평균", t_new["청년등_평균"])
        totals["nr_B_청년외_평균"] = t_new.get("B_청년외_평균", t_new["청년외_평균"])
        m_nr = R.calc_method_for(tax_yr, eval_year=tax_yr)
        totals["nr_상시_평균"] = totals[f"nr_{m_nr}_상시_평균"]
        totals["nr_청년등_평균"] = totals[f"nr_{m_nr}_청년등_평균"]
        totals["nr_청년외_평균"] = totals[f"nr_{m_nr}_청년외_평균"]
        totals["nr_상시_합계"] = t_new["상시_합계"]
        totals["nr_청년등_합계"] = t_new["청년등_합계"]
        totals["nr_청년외_합계"] = t_new["청년외_합계"]
        totals["nr_names"] = sorted(people[pid].get("성명", "") for pid in alt_new)


# ══════════════════════════════════════════════════════════════════
# 6. 3단계: 공제액 · 1·2차 사후관리(추가납부세액) 종합 계산
# ══════════════════════════════════════════════════════════════════
def _ensure_totals_snapshot(s: dict) -> dict[int, dict]:
    _ensure_built_for_tax_year(s)
    totals_all = {}
    for y in _all_possible_years(s):
        _, _, t = _build_year_rows(s, y)
        t["corp_size"] = _cohort_corp_size(s, y)
        totals_all[y] = t

    tax_yr = int(s["tax_year"])
    for past_y in (tax_yr - 1, tax_yr - 2, tax_yr - 3):
        t_cur = totals_all.get(past_y) or {}
        if not t_cur.get("has_data"):
            ps_y = (s.get("prev_summary") or {}).get(str(past_y)) or {}
            reg = float(ps_y.get("상시") or 0.0)
            yth = float(ps_y.get("청년등") or 0.0)
            gen = round(max(0.0, reg - yth), 2)
            reg_tot = float(ps_y.get("상시_총인원") if ps_y.get("상시_총인원") is not None else round(reg * 12, 2))
            yth_tot = float(ps_y.get("청년등_총인원") if ps_y.get("청년등_총인원") is not None else round(yth * 12, 2))
            gen_tot = round(max(0.0, reg_tot - yth_tot), 2)
            has_d = reg > 0 or yth > 0
            totals_all[past_y] = {
                "from_filed": True,
                "상시_합계": reg_tot,
                "청년등_합계": yth_tot,
                "청년외_합계": gen_tot,
                "b2_청년등_합계": yth_tot,
                "b2_청년외_합계": gen_tot,
                "b3_청년등_합계": yth_tot,
                "b3_청년외_합계": gen_tot,
                "상시_평균": reg,
                "청년등_평균": yth,
                "청년외_평균": gen,
                "b1_reg": reg,
                "b1_yth": yth,
                "b1_gen": gen,
                "b2_reg": reg,
                "b2_yth": yth,
                "b2_gen": gen,
                "b3_reg": reg,
                "b3_yth": yth,
                "b3_gen": gen,
                "b4_reg": reg,
                "b4_yth": yth,
                "b4_gen": gen,
                "months_in_year": 12,
                "has_data": has_d,
            }

    # 승계 조정(포괄양수 가산 / 기중양도 차감)을 직전연도 합계에 반영
    if (tax_yr - 1) in totals_all:
        totals_all[tax_yr - 1], _, _ = _adjusted_prev_totals(s, totals_all[tax_yr - 1])

    s["totals_snapshot"] = totals_all
    return totals_all


def _compute_historical_matrix_columns(
    s: dict,
    tax_yr: int,
    corp_size: str,
    is_capital: bool,
    totals_all: dict[int, dict],
    ps: dict,
    pkg_cur: dict,
    active_pm_basis: str,
) -> dict[int, dict[str, Any]]:
    """
    상단 요약표 [구분: 세액공제액 | 1차 / 2차 / 3차 / 합계] × [tax_yr-3, tax_yr-2, tax_yr-1, tax_yr] 4개 연도 열 산출.
    - 각 열(column Y)은 해당 과세연도(Y년 귀속) 신고 시점의:
      * 1차: Y년 귀속 신규 고용증가 세액공제액 (1차년도분)
      * 2차: Y-1년 귀속분의 Y년 1차 사후관리 (2차년도 연속공제액 또는 (-)추가납부세액)
      * 3차: Y-2년 귀속분의 Y년 2차 사후관리 (3차년도 연속공제액 또는 (-)추가납부세액)
      * 합계: 1차 + 2차 + 3차 순합계 (음수 시 붉은색 -금액)
    """
    def _cap(y: int) -> bool:
        """y년 귀속분의 최초공제연도 사업장 소재지(수도권 여부). 3단계에서 지정하지 않았으면 현재 소재지."""
        v = (ps.get(str(y)) or {}).get("수도권")
        return is_capital if v is None else bool(v)

    def _sz(y: int) -> str:
        return _cohort_corp_size(s, y, corp_size)

    def _rates(y: int) -> tuple[int, int]:
        r = H.get_unit_rates(_sz(y), _cap(y), scheme="legacy", retention_year=1)
        return r["청년등"], r["청년등외"]

    def _s_yr(y: int) -> dict:
        d = totals_all.get(y) or {}
        reg = float(d.get("상시_평균", d.get("regular", 0.0)) or 0.0)
        yth = float(d.get("청년등_평균", d.get("youth", 0.0)) or 0.0)
        b2_r = float(d.get("b2_reg", reg) or 0.0)
        b2_y = float(d.get("b2_yth", yth) or 0.0)
        b3_r = float(d.get("b3_reg", reg) or 0.0)
        b3_y = float(d.get("b3_yth", yth) or 0.0)
        b2_ya = float(d["b2_yth_act"]) if d.get("b2_yth_act") is not None else b2_y
        b3_ya = float(d["b3_yth_act"]) if d.get("b3_yth_act") is not None else b3_y
        has_d = bool(d.get("has_data", reg > 0 or yth > 0))
        return {
            "reg": round(reg, 2),
            "yth": round(yth, 2),
            "gen": round(max(0.0, reg - yth), 2),
            "b2_reg": round(b2_r, 2),
            "b2_yth": round(b2_y, 2),
            "b3_reg": round(b3_r, 2),
            "b3_yth": round(b3_y, 2),
            "b2_yth_act": round(b2_ya, 2),
            "b3_yth_act": round(b3_ya, 2),
            "has_data": has_d,
            "from_filed": bool(d.get("from_filed")),
        }

    def _cohort_1st_info(y_cohort: int) -> dict[str, Any]:
        """y_cohort 귀속분의 최초(1차년도) 상시·청년등·증가인원·1차공제세액 추정"""
        f_d = ps.get(str(y_cohort)) or {}
        yth_r, gen_r = _rates(y_cohort)
        sy = _s_yr(y_cohort)
        sy_prev = _s_yr(y_cohort - 1)
        use_recalc = (active_pm_basis == R.PM_BASIS_RECALC)

        # 1) 세법원칙(사원표 재계산) 우선 확인
        recalc_ok = sy["has_data"] and not sy["from_filed"] and sy_prev["has_data"] and not sy_prev["from_filed"]
        inc_recalc = (
            H.calc_increase_with_cap(sy["reg"], sy["yth"], sy_prev["reg"], sy_prev["yth"])
            if recalc_ok
            else None
        )
        cr_recalc = (
            int(round((inc_recalc["youth_inc"] * yth_r + inc_recalc["non_youth_inc"] * gen_r) * 10_000))
            if inc_recalc is not None
            else None
        )

        # 2) 기신고 입력값 확인
        f_reg = f_d.get("상시")
        f_yth = f_d.get("청년등")
        f_y_inc = f_d.get("청년등_증가")
        f_g_inc = f_d.get("청년등외_증가")
        f_clm = f_d.get("공제세액")

        if use_recalc and recalc_ok and inc_recalc is not None:
            return {
                "has": True,
                "reg": sy["reg"],
                "yth": sy["yth"],
                "yth_inc": inc_recalc["youth_inc"],
                "gen_inc": inc_recalc["non_youth_inc"],
                "credit_1st_won": int(cr_recalc or 0),
            }

        # [6-1, 6-4] 기신고 기준(PM_BASIS_FILED)에서는 재계산값이 섞이지 않도록 기신고 값만 사용하고,
        # 과거 연도 1차 공제액이 기신고서·세액공제조정명세서(부표3)에 없으면 추정복원하지 않고 빈칸(신고서 확인 필요)으로 표시
        if not use_recalc:
            if f_reg is not None or f_yth is not None or f_y_inc is not None or f_g_inc is not None or f_clm is not None:
                yi = float(f_y_inc or 0.0)
                gi = float(f_g_inc or 0.0)
                c1_won = int(f_clm) if f_clm is not None else 0
                needs_chk = (f_clm is None) or bool(f_d.get("_needs_filing_check"))
                return {
                    "has": True,
                    "reg": float(f_reg or 0.0),
                    "yth": float(f_yth or 0.0),
                    "yth_inc": yi,
                    "gen_inc": gi,
                    "credit_1st_won": c1_won,
                    "r1_needs_check": needs_chk,
                    "auto_filled": bool(f_d.get("_auto_filled")),
                }
            return {
                "has": False,
                "reg": 0.0,
                "yth": 0.0,
                "yth_inc": 0.0,
                "gen_inc": 0.0,
                "credit_1st_won": 0,
                "r1_needs_check": True,
                "auto_filled": False,
            }

        if recalc_ok and inc_recalc is not None:
            return {
                "has": True,
                "reg": sy["reg"],
                "yth": sy["yth"],
                "yth_inc": inc_recalc["youth_inc"],
                "gen_inc": inc_recalc["non_youth_inc"],
                "credit_1st_won": int(cr_recalc or 0),
                "r1_needs_check": False,
                "auto_filled": False,
            }

        if f_y_inc is not None or f_g_inc is not None or f_clm is not None:
            yi = float(f_y_inc or 0.0)
            gi = float(f_g_inc or 0.0)
            c1_won = int(f_clm) if f_clm is not None else int(round((yi * yth_r + gi * gen_r) * 10_000))
            return {
                "has": True,
                "reg": float(f_reg if f_reg is not None else sy["reg"]),
                "yth": float(f_yth if f_yth is not None else sy["yth"]),
                "yth_inc": yi,
                "gen_inc": gi,
                "credit_1st_won": c1_won,
                "r1_needs_check": (f_clm is None),
                "auto_filled": bool(f_d.get("_auto_filled")),
            }

        return {
            "has": False,
            "reg": sy["reg"],
            "yth": sy["yth"],
            "yth_inc": 0.0,
            "gen_inc": 0.0,
            "credit_1st_won": 0,
            "r1_needs_check": True,
            "auto_filled": False,
        }

    cols: dict[int, dict[str, Any]] = {}
    y_m3, y_m2, y_m1, y_0 = tax_yr - 3, tax_yr - 2, tax_yr - 1, tax_yr

    info_m3 = _cohort_1st_info(y_m3)
    info_m2 = _cohort_1st_info(y_m2)
    info_m1 = _cohort_1st_info(y_m1)

    # ── (A) tax_yr - 3 열 (예: 2023년) ──
    c_m3_1 = info_m3["credit_1st_won"]
    cols[y_m3] = {
        "r1_credit": c_m3_1, "r1_claw": 0,
        "r2_credit": 0, "r2_claw": 0,
        "r3_credit": 0, "r3_claw": 0,
        "net_total": c_m3_1,
        "r1_needs_check": bool(info_m3.get("r1_needs_check")),
        "auto_filled": bool(info_m3.get("auto_filled")),
        "calc_method": R.calc_method_for(y_m3, eval_year=y_m3),
    }

    # ── (B) tax_yr - 2 열 (예: 2024년) ──
    c_m2_1 = info_m2["credit_1st_won"]
    c_m2_2_cr, c_m2_2_cl = 0, 0
    s_m2 = _s_yr(y_m2)
    if info_m3["has"] and s_m2["has_data"] and (info_m3["yth_inc"] + info_m3["gen_inc"] > 0):
        pm_m3_in_m2 = H.calc_legacy_post_management(
            cohort_year=y_m3,
            eval_year=y_m2,
            corp_size=_sz(y_m3),
            is_capital=_cap(y_m3),
            init_reg=info_m3["reg"],
            init_yth=info_m3["yth"],
            init_yth_inc=info_m3["yth_inc"],
            init_gen_inc=info_m3["gen_inc"],
            cur_pm_reg=s_m2["b2_reg"],
            cur_pm_yth=s_m2["b2_yth"],
            cur_pm_yth_actual=s_m2["b2_yth_act"],
            init_credit_claimed_won=info_m3["credit_1st_won"],
        )
        c_m2_2_cr = int(pm_m3_in_m2.get("continued_credit_won") or 0)
        c_m2_2_cl = int(pm_m3_in_m2.get("clawback_net_payable_won") or 0)
    cols[y_m2] = {
        "r1_credit": c_m2_1, "r1_claw": 0,
        "r2_credit": c_m2_2_cr, "r2_claw": c_m2_2_cl,
        "r3_credit": 0, "r3_claw": 0,
        "net_total": c_m2_1 + c_m2_2_cr - c_m2_2_cl,
        "r1_needs_check": bool(info_m2.get("r1_needs_check")),
        "auto_filled": bool(info_m2.get("auto_filled")),
        "calc_method": R.calc_method_for(y_m2, eval_year=y_m2),
    }

    # ── (C) tax_yr - 1 열 (예: 2025년) ──
    c_m1_1 = info_m1["credit_1st_won"]
    c_m1_2_cr, c_m1_2_cl = 0, 0
    c_m1_3_cr, c_m1_3_cl = 0, 0
    s_m1 = _s_yr(y_m1)
    f_m2 = ps.get(str(y_m2)) or {}
    if active_pm_basis == R.PM_BASIS_FILED and (
        f_m2.get("2차_공제세액") is not None or f_m2.get("기추징세액") is not None
    ):
        c_m1_2_cr = int(f_m2.get("2차_공제세액") or 0)
        c_m1_2_cl = int(f_m2.get("기추징세액") or 0)
    elif info_m2["has"] and s_m1["has_data"] and (info_m2["yth_inc"] + info_m2["gen_inc"] > 0):
        pm_m2_in_m1 = H.calc_legacy_post_management(
            cohort_year=y_m2,
            eval_year=y_m1,
            corp_size=_sz(y_m2),
            is_capital=_cap(y_m2),
            init_reg=info_m2["reg"],
            init_yth=info_m2["yth"],
            init_yth_inc=info_m2["yth_inc"],
            init_gen_inc=info_m2["gen_inc"],
            cur_pm_reg=s_m1["b2_reg"],
            cur_pm_yth=s_m1["b2_yth"],
            cur_pm_yth_actual=s_m1["b2_yth_act"],
            init_credit_claimed_won=info_m2["credit_1st_won"],
        )
        c_m1_2_cr = int(pm_m2_in_m1.get("continued_credit_won") or 0)
        c_m1_2_cl = int(pm_m2_in_m1.get("clawback_net_payable_won") or 0)

    if info_m3["has"] and s_m1["has_data"] and (info_m3["yth_inc"] + info_m3["gen_inc"] > 0):
        pm_m3_in_m1 = H.calc_legacy_post_management(
            cohort_year=y_m3,
            eval_year=y_m1,
            corp_size=_sz(y_m3),
            is_capital=_cap(y_m3),
            init_reg=info_m3["reg"],
            init_yth=info_m3["yth"],
            init_yth_inc=info_m3["yth_inc"],
            init_gen_inc=info_m3["gen_inc"],
            cur_pm_reg=s_m1["b3_reg"],
            cur_pm_yth=s_m1["b3_yth"],
            cur_pm_yth_actual=s_m1["b3_yth_act"],
            init_credit_claimed_won=info_m3["credit_1st_won"],   # 2차 공제분은 계산 함수가 한도에 자동 합산
            prev_pm_reg=s_m2["b2_reg"] if s_m2["has_data"] else None,
            prev_pm_yth=s_m2["b2_yth"] if s_m2["has_data"] else None,
            prev_pm_yth_actual=s_m2["b2_yth_act"] if s_m2["has_data"] else None,
            prior_clawback_paid_won=c_m2_2_cl,
            y1_continued_credit_won=c_m2_2_cr,
        )
        c_m1_3_cr = int(pm_m3_in_m1.get("continued_credit_won") or 0)
        c_m1_3_cl = int(pm_m3_in_m1.get("clawback_net_payable_won") or 0)

    cols[y_m1] = {
        "r1_credit": c_m1_1, "r1_claw": 0,
        "r2_credit": c_m1_2_cr, "r2_claw": c_m1_2_cl,
        "r3_credit": c_m1_3_cr, "r3_claw": c_m1_3_cl,
        "net_total": (c_m1_1 + c_m1_2_cr + c_m1_3_cr) - (c_m1_2_cl + c_m1_3_cl),
        "r1_needs_check": bool(info_m1.get("r1_needs_check")),
        "auto_filled": bool(info_m1.get("auto_filled")),
        "calc_method": R.calc_method_for(y_m1, eval_year=y_m1),
    }

    # ── (D) 당해 과세연도(tax_yr) 열 (예: 2026년) ──
    if pkg_cur["active_scheme"] == "new_2026":
        c_0_1 = int(pkg_cur.get("cur_new_a_won") or 0)
    else:
        c_0_1 = int(pkg_cur.get("cur_legacy_total_won") or 0)
    pm1 = pkg_cur["pm_y1"]
    pm2 = pkg_cur["pm_y2"]
    c_0_2_cr = int(pm1.get("continued_credit_won") or 0)
    c_0_2_cl = int(pm1.get("clawback_net_payable_won") or 0)
    c_0_3_cr = int(pm2.get("continued_credit_won") or 0)
    c_0_3_cl = int(pm2.get("clawback_net_payable_won") or 0)
    if pkg_cur["active_scheme"] == "new_2026":
        # 2026년 이후 귀속분은 구법 사후관리가 아니라 신법 B(2년차)·C(3년차) 공제로 반영
        if (y_0 - 1) >= 2026:
            c_0_2_cr, c_0_2_cl = int(pkg_cur.get("cur_new_b_won") or 0), 0
        if (y_0 - 2) >= 2026:
            c_0_3_cr, c_0_3_cl = int(pkg_cur.get("cur_new_c_won") or 0), 0
    cols[y_0] = {
        "r1_credit": c_0_1, "r1_claw": 0,
        "r2_credit": c_0_2_cr, "r2_claw": c_0_2_cl,
        "r3_credit": c_0_3_cr, "r3_claw": c_0_3_cl,
        "net_total": (c_0_1 + c_0_2_cr + c_0_3_cr) - (c_0_2_cl + c_0_3_cl),
        "r1_needs_check": False,
        "auto_filled": False,
        "calc_method": R.calc_method_for(y_0, eval_year=y_0),
    }
    # 기신고 기준: 과거 연도 열은 세액공제조정명세서(코드 18S)에 실제 신고된 1차·2차·3차 금액을 그대로 표시
    #   (추정치 대신 신고 사실값 사용. 추가납부액은 18S에 없으므로 계산값 유지)
    if active_pm_basis == R.PM_BASIS_FILED:
        cs = {int(k): v for k, v in (((s.get("ext") or {}).get("credit_stmt")) or {}).items() if str(k).isdigit()}
        for y, col in cols.items():
            filed = cs.get(int(y))
            if not filed or int(y) >= int(y_0):
                continue
            col["r1_credit"] = int(filed.get("1차") or 0)
            col["r2_credit"] = int(filed.get("2차") or 0)
            col["r3_credit"] = int(filed.get("3차") or 0)
            col["net_total"] = (col["r1_credit"] + col["r2_credit"] + col["r3_credit"]) - (
                int(col.get("r2_claw") or 0) + int(col.get("r3_claw") or 0)
            )
            col["from_filed_stmt"] = True
    return cols


# ══════════════════════════════════════════════════════════════════
# 7. 4단계: 자율 에이전트AI 스타일 세무검토 보고서 (대·중·소제목 위계 · 무아이콘 · 심층진단 자동생성 · PDF 출력)
# ══════════════════════════════════════════════════════════════════
_REPORT_EMOJI_RE = re.compile(
    r"[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F]|👑|🔍|🛡️|📋|⚠️|📑|📊|💡|🚨|💰|✅|❌|⚖️|🔄|➕|🏢|📅|📌|🧮|💾|📥|📕|🔘|🌱|🟦|🟧|🔧|✏️|🔒"
)


def _build_csv_bytes(s: dict) -> bytes:
    _ensure_built_for_tax_year(s)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "귀속연도", "사업장명", "성명", "생년월일", "입사일", "퇴사일", "취업연령", "고용유형", "제외사유", "병역(월)", "청년등구분", "상시여부",
            *[f"{m}월" for m in range(1, 13)], "월합계",
            "3.세액공제[청년등]", "3.세액공제[청년외]", "3.세액공제[상시]",
            "4.1차사후관리[청년등]", "4.1차사후관리[청년외]", "4.1차사후관리[상시]",
            "5.2차사후관리[청년등]", "5.2차사후관리[청년외]", "5.2차사후관리[상시]",
        ]
    )
    for y in _years(s):
        rows, _, totals = _build_year_rows(s, y)
        has_y1 = _has_year_data(s, y - 1)
        has_y2 = _has_year_data(s, y - 2)
        trunc_mode = R.calc_method_short_label(y, eval_year=y)
        for r in rows:
            writer.writerow(
                [
                    y, r["사업장명"], r["성명"], r["생년월일"], r["입사일"], r["퇴사일"], r["취업연령"],
                    r["고용유형"], r["제외사유"], r["병역개월"], r["청년등"], r["상시"],
                    *[r[MONTH_COLS[i]] if r[MONTH_COLS[i]] is not None else "" for i in range(12)],
                    r["합계"],
                    f"{r['b1_yth']:.2f}", f"{r['b1_gen']:.2f}", f"{r['b1_reg']:.2f}",
                    f"{r['b2_yth']:.2f}" if has_y1 else "-", f"{r['b2_gen']:.2f}" if has_y1 else "-", f"{r['b2_reg']:.2f}" if has_y1 else "-",
                    f"{r['b3_yth']:.2f}" if has_y2 else "-", f"{r['b3_gen']:.2f}" if has_y2 else "-", f"{r['b3_reg']:.2f}" if has_y2 else "-",
                ]
            )
        writer.writerow(
            [
                f"{y}년 합계/평균", "합산합계", "전체 상시·청년 요약", "", "", "", "", f"÷{totals['months_in_year']}개월({trunc_mode})", "", "", "", "",
                *[totals["월별_상시"][i] if totals["월별_상시"][i] is not None else "" for i in range(12)],
                totals["상시_합계"],
                f"{totals['b1_yth']:.2f}", f"{totals['b1_gen']:.2f}", f"{totals['b1_reg']:.2f}",
                f"{totals['b2_yth']:.2f}" if has_y1 else "-", f"{totals['b2_gen']:.2f}" if has_y1 else "-", f"{totals['b2_reg']:.2f}" if has_y1 else "-",
                f"{totals['b3_yth']:.2f}" if has_y2 else "-", f"{totals['b3_gen']:.2f}" if has_y2 else "-", f"{totals['b3_reg']:.2f}" if has_y2 else "-",
            ]
        )
    return buf.getvalue().encode("utf-8-sig")