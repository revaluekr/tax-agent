# -*- coding: utf-8 -*-
"""
통합고용세액공제 화면 — 1단계(자료 업로드) · 2단계(사원정보) · 3단계(공제액·사후관리 계산) · 4단계(보고서)

[클로드 14대 수정사항 + 추가 2건 + 제미나이 UI/UX 시각 최적화 · PDF 다운로드 · 디스크 자동보관 · Pro/Argon 심층진단 통합 최종본]
1. [자율 에이전트AI ↔ 통합고용세액공제 양방향 100% 자동 보관 (메모리 + 디스크 `.workspace_storage` 이중 영구저장)]
   - 통합고용세액공제 진행 도중 자율 에이전트AI로 넘어가서 세법 질의를 하고 다시 돌아오거나, 브라우저 새로고침(F5)을 해도
     작업공간별(`ws_id`)로 업로드 파일·사원표 수정내역·진행 단계가 100% 그대로 보존됩니다.
2. [2단계 시각적 완성도 5대 개선 반영]
   - ① `사업장명` 열 노이즈(`첨부 엑셀 명: 년` 등) 완전 제거 및 단일 사업장 시 `'본점'` 깔끔 표기 (`76px` 슬림화)
   - ② AG Grid 전체 열 폭 다이어트(말줄임표 `"..."` 0건 유지 + 가로 스크롤 최소화) 및 대량 인원(35명 이상) 탭 뷰 자동 보호
   - ③ `미도래 월 연말재직 가정(하늘색 #e0f2fe)` vs `급여 0원 월(살구색 #ffedd5)` 색상 명확 분리
   - ④ `청년등 구분`(청년·고령자 등 우대=초록 볼드 / 일반=슬레이트) 및 `제외사유`(제외대상=적색 볼드 / 해당없음=슬레이트) 시각 대비 강화
   - ⑤ 2단계 상단 옵션 박스 슬림화로 첫 번째 사원표가 화면 상단에서 즉시 시작되도록 개선
3. [연도별 우측 상단 `[📕 PDF 다운]` 및 하단 `[📕 전체 PDF 다운]` 붉은 버튼 탑재]
   - 각 연도 귀속 상시근로자 명세 라인 맨 오른쪽 옆에 붉은색 `[📕 PDF 다운]` 버튼을 배치하여 연도별 A4 가로(Landscape) 명세표를 즉시 다운로드합니다.
   - 하단 `[🔍 오류 검토]` 바로 왼쪽 옆에 동일한 디자인의 붉은색 `[📕 전체 PDF 다운]` 버튼을 배치하여 전 연도 통합 명세서 PDF를 원클릭으로 다운로드합니다.
4. [100% 성능 12대 결정론적 오류·절세누락 검토 + 부분적 Pro/Argon AI 심층 세무진단 연동]
"""
from __future__ import annotations

import io
import os
import re
import csv
import json
import uuid
import copy
import hashlib
import time
import urllib.request
import pandas as pd
import streamlit as st
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, JsCode

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.cidfonts import UnicodeCIDFont

from . import rules as R
from . import headcount as H
from . import parsers as P
from . import backup as B

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
    st.session_state.ec = s
    return s


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
    if not _uploaded_wht_years(s) and year in (t, t - 1):
        if any(H.worked_in_year(p, year) for p in (s.get("people") or {}).values()):
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
    return {
        "corp_size": b.get("기업구분", "중소기업"),
        "months_in_year": n if n > 0 else 12,
        "assume_year_end": bool(s.get("assume_year_end", True)),
        "include_unpaid_hire_month": bool(s.get("include_unpaid_hire_month", True)),
        "last_paid_month": last_m,
        "workplace_close_month_map": _workplace_close_month_map(s, year),
        "wht_years": sorted(_uploaded_wht_years(s)),
        "succession_map": _succession_map(s, year),
        "transfer_out_map": _transfer_out_map(s, year),
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

        # 인원수가 45명 이상이면 브라우저 렌더링 부하 방지를 위해 연도별 탭 뷰를 기본 활성화
        if len(s["people"]) >= 45 and not s.get("_tabs_user_touched"):
            s["use_year_tabs"] = True

        parsed_prev = P.build_prev_summary(ext, tax_yr, (s.get("biz") or {}).get("기업구분", "중소기업"))
        ps = s.setdefault("prev_summary", {})
        for y_str, vals in parsed_prev.items():
            if isinstance(vals, dict):
                old = ps.get(str(y_str)) or {}
                ps[str(y_str)] = {
                    "상시_총인원": vals.get("상시_총인원") if vals.get("상시_총인원") is not None else old.get("상시_총인원"),
                    "청년등_총인원": vals.get("청년등_총인원") if vals.get("청년등_총인원") is not None else old.get("청년등_총인원"),
                    "상시": vals.get("상시") if vals.get("상시") is not None else old.get("상시"),
                    "청년등": vals.get("청년등") if vals.get("청년등") is not None else old.get("청년등"),
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
                }

        s["grid_ver"], s["last_sent"] = {}, {}
        s["built_sig"] = sig
        _save_ec_to_disk(s)


# ══════════════════════════════════════════════════════════════════
# 0-B. 상시근로자 명세서 A4 가로(Landscape) 정식 PDF 생성 엔진
# ══════════════════════════════════════════════════════════════════
def _ensure_korean_pdf_font() -> tuple[str, str]:
    """
    ReportLab PDF 한글 폰트 등록 및 폰트 패밀리(<b> 태그 매핑) 보장:
    1) 이미 app.py에 등록된 KoreanFont/KoreanFontBold가 있으면 즉시 재사용하거나,
    2) Windows 맑은고딕(malgun.ttf), STORAGE_DIR 내 NanumGothic.ttf, Linux 시스템 한글 TrueType 폰트
       (/usr/share/fonts/truetype/nanum/NanumGothic.ttf, DroidSansFallbackFull.ttf, UnDotum.ttf 등)를 탐색하여
       실제 글리프가 임베딩되는 TTFont로 등록합니다(HYGothic-Medium CID 폰트 단독 사용 시 한글 투명 누락 방지).
    3) pdfmetrics.registerFontFamily를 호출하여 Paragraph 내 <b>...</b> 태그가 Helvetica로 풀리지 않도록 합니다.
    """
    reg_name = "ECKoreanFont"
    bold_name = "ECKoreanFontBold"
    registered = pdfmetrics.getRegisteredFontNames()
    if reg_name in registered and bold_name in registered:
        return reg_name, bold_name

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

    if chosen_reg is None:
        try:
            urllib.request.urlretrieve(
                "https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Regular.ttf",
                reg_path,
            )
            urllib.request.urlretrieve(
                "https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Bold.ttf",
                bold_path,
            )
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
            return reg_name, bold_name
        except Exception:
            pass

    if "KoreanFont" in registered:
        kf_bold = "KoreanFontBold" if "KoreanFontBold" in registered else "KoreanFont"
        try:
            pdfmetrics.registerFontFamily("KoreanFont", normal="KoreanFont", bold=kf_bold, italic="KoreanFont", boldItalic=kf_bold)
        except Exception:
            pass
        return "KoreanFont", kf_bold

    try:
        pdfmetrics.registerFont(UnicodeCIDFont("HYGothic-Medium"))
        try:   # <b> 태그가 영문 Helvetica로 풀려 한글이 사라지지 않도록 같은 글꼴로 묶음
            pdfmetrics.registerFontFamily("HYGothic-Medium", normal="HYGothic-Medium", bold="HYGothic-Medium",
                                          italic="HYGothic-Medium", boldItalic="HYGothic-Medium")
        except Exception:
            pass
        return "HYGothic-Medium", "HYGothic-Medium"
    except Exception:
        return "Helvetica", "Helvetica-Bold"


_APP_PDF_CHAR_CAP = 150_000      # app.py 공용 읽기 함수의 글자 상한 (이 길이면 잘렸을 가능성)


def _read_upload_text(u, extract_file_fn, room_key: str = "") -> str:
    """
    업로드 파일 → 글자.
    PDF는 계산기가 직접 '모든 쪽'을 읽습니다. app.py 공용 함수는 150쪽·150,000자에서 잘라
    직원 25명을 넘는 원천징수부(1인 3쪽)의 뒷부분이 조용히 빠지기 때문입니다.
    스캔 이미지 PDF처럼 글자가 거의 없으면 공용 함수(이미지 판독)로 넘깁니다.
    """
    name = str(getattr(u, "name", "") or "")
    if name.lower().endswith(".pdf"):
        # 1순위 pypdfium2: 글자 단위로 저장된 원천징수부도 빠르게 읽음 (300쪽 약 4초, pypdf는 약 60초)
        try:
            import pypdfium2 as pdfium
            doc = pdfium.PdfDocument(u.getvalue())
            parts = [f"[첨부 PDF 파일명: {name} (총 {len(doc)}페이지)]"]
            body = 0
            for i in range(len(doc)):
                tp = doc[i].get_textpage()
                t = (tp.get_text_range() or "").strip()
                tp.close()
                body += len(t)
                parts.append(f"\n--- {i + 1}페이지 ---\n{t}")
            doc.close()
            if body >= 40:
                return "\n".join(parts)
        except Exception:
            pass
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(u.getvalue()))
            parts = [f"[첨부 PDF 파일명: {name} (총 {len(reader.pages)}페이지)]"]
            body = 0
            for i, page in enumerate(reader.pages):
                t = (page.extract_text() or "").strip()
                body += len(t)
                parts.append(f"\n--- {i + 1}페이지 ---\n{t}")
            if body >= 40:
                return "\n".join(parts)
        except Exception:
            pass
    text = extract_file_fn(u, room_key) or ""
    if len(text) >= _APP_PDF_CHAR_CAP:
        text += "\n[[계산기 경고: 파일 글자가 공용 읽기 상한에 닿아 뒷부분이 잘렸을 수 있습니다]]"
    return text


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
    corp_sz = b.get("기업구분") or "중소기업"
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


def _build_schedule_pdf_bytes(s: dict, target_years: list[int], include_summary: bool = False) -> bytes:
    """
    선택된 연도(`target_years`)의 상시근로자 명세표(사원 계산기 + 1~12월 + 우측 3·4·5 블록 + 합산합계 행)를
    A4 가로(Landscape) 고해상도 정식 PDF로 생성합니다.
    """
    _ensure_built_for_tax_year(s)
    reg_font, bold_font = _ensure_korean_pdf_font()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        leftMargin=18,
        rightMargin=18,
        topMargin=20,
        bottomMargin=20,
    )

    styles = getSampleStyleSheet()
    st_title = ParagraphStyle(
        "ECTitle",
        parent=styles["Normal"],
        fontName=bold_font,
        fontSize=13,
        leading=17,
        textColor=colors.HexColor("#0f172a"),
        spaceAfter=4,
    )
    st_sub = ParagraphStyle(
        "ECSub",
        parent=styles["Normal"],
        fontName=reg_font,
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor("#334155"),
        spaceAfter=6,
    )
    st_yr_hdr = ParagraphStyle(
        "ECYrHdr",
        parent=styles["Normal"],
        fontName=bold_font,
        fontSize=10.5,
        leading=14,
        textColor=colors.HexColor("#1e3a8a"),
        spaceBefore=4,
        spaceAfter=4,
    )

    b = s.get("biz") or {}
    corp_nm = (b.get("상호") or "").strip()
    biz_no = (b.get("사업자번호") or "").strip()
    corp_sz = b.get("기업구분") or "중소기업"
    cap = H.is_capital_area(b.get("사업장소재지", ""))
    loc_str = "수도권" if cap is True else ("수도권 외(비수도권)" if cap is False else "")
    tax_yr = int(s.get("tax_year") or R.DEFAULT_TAX_YEAR)

    story = []
    if len(target_years) == 1:
        y_only = target_years[0]
        story.append(Paragraph((f"[{corp_nm}] " if corp_nm else "") + f"{y_only}년 귀속 상시근로자 명세서 (통합고용세액공제 · 사후관리 판정표)", st_title))
    else:
        story.append(Paragraph((f"[{corp_nm}] " if corp_nm else "") + f"{tax_yr}년 귀속 통합고용세액공제 전체 연도 상시근로자 명세서 ({', '.join(str(y)+'년' for y in target_years)})", st_title))

    story.append(
        Paragraph(
            f"사업자등록번호: {biz_no}  |  기업규모·소재지: {corp_sz} · {loc_str}  |  귀속사업연도: {tax_yr}년 귀속",
            st_sub,
        )
    )

    # 전체 연도 출력 시 모든 연도의 열 위치·간격이 수직으로 100% 일치하도록 동일한 우측 블록 구성을 유지합니다.
    multi_yr_mode = len(target_years) > 1
    any_has_y1 = any(
        (_has_year_data(s, yy - 1) or bool(s.get("show_empty_pm_blocks", False)))
        for yy in target_years
    )
    any_has_y2 = any(
        (_has_year_data(s, yy - 2) or bool(s.get("show_empty_pm_blocks", False)))
        for yy in target_years
    )

    totals_by_yr: dict[int, dict] = {}
    for idx_y, y in enumerate(target_years):
        if idx_y > 0:
            story.append(Spacer(1, 16))
        rows, _, totals = _build_year_rows(s, y)
        totals_by_yr[y] = totals
        role_desc = _year_role_description(s, tax_yr, y)
        trunc_mode = "합산 후 절사"
        b3_t, b4_t, b5_t = _block_titles_for_year(y, two_line=False)

        yr_has_y1 = _has_year_data(s, y - 1) or bool(s.get("show_empty_pm_blocks", False))
        yr_has_y2 = _has_year_data(s, y - 2) or bool(s.get("show_empty_pm_blocks", False))
        col_has_y1 = any_has_y1 if multi_yr_mode else yr_has_y1
        col_has_y2 = any_has_y2 if multi_yr_mode else yr_has_y2

        story.append(
            Paragraph(
                f"■ {y}년 귀속 상시근로자 명세 ({len(rows)}명) — {role_desc}",
                st_yr_hdr,
            )
        )
        kpi_line = (
            f"[{b3_t}] 상시 {totals['b1_reg']:.2f}명 (청년등 {totals['b1_yth']:.2f} · 청년외 {totals['b1_gen']:.2f})"
            + (f"   |   [{b4_t}] 상시 {totals['b2_reg']:.2f}명 (청년등 {totals['b2_yth']:.2f} · 청년외 {totals['b2_gen']:.2f})" if yr_has_y1 else "")
            + (f"   |   [{b5_t}] 상시 {totals['b3_reg']:.2f}명 (청년등 {totals['b3_yth']:.2f} · 청년외 {totals['b3_gen']:.2f})" if yr_has_y2 else "")
            + f"   |   총인원(연인원) {totals['상시_합계']:g}명 ÷ {totals['months_in_year']}개월 ({trunc_mode})"
        )
        story.append(Paragraph(kpi_line, st_sub))

        headers = [
            "사업장", "성명", "생년월일", "입사일", "퇴사일", "연령", "고용유형", "제외사유", "청년등 구분", "상시",
            *[f"{m}월" for m in range(1, 13)], "월합",
            f"{y%100:02d}공제\n청년", f"{y%100:02d}공제\n일반", f"{y%100:02d}공제\n상시",
        ]
        col_widths = [
            32, 34, 41, 41, 41, 21, 42, 60, 62, 18,
            *[16.0 for _ in range(12)], 21,
            23.5, 23.5, 23.5,
        ]
        if col_has_y1:
            headers.extend([f"{(y-1)%100:02d}사후\n청년", f"{(y-1)%100:02d}사후\n일반", f"{(y-1)%100:02d}사후\n상시"])
            col_widths.extend([23.5, 23.5, 23.5])
        if col_has_y2:
            headers.extend([f"{(y-2)%100:02d}사후\n청년", f"{(y-2)%100:02d}사후\n일반", f"{(y-2)%100:02d}사후\n상시"])
            col_widths.extend([23.5, 23.5, 23.5])

        # 폭 비율 자동 맞춤 (A4 가로 가용 폭 806pt)
        avail_w = landscape(A4)[0] - 36
        scale = avail_w / sum(col_widths)
        col_widths = [w * scale for w in col_widths]

        tbl_data = [headers]
        for r in rows:
            m_cells = []
            for i in range(12):
                mv = r[MONTH_COLS[i]]
                if mv is None:
                    m_cells.append("-")
                else:
                    m_cells.append(f"{mv:g}")
            row_cells = [
                str(r["사업장명"])[:7],
                str(r["성명"])[:7],
                str(r["생년월일"]).replace("-", "."),
                str(r["입사일"]).replace("-", "."),
                str(r["퇴사일"]).replace("-", "."),
                str(r["취업연령"]),
                str(r["고용유형"]).replace("근로자", ""),
                str(r["제외사유"])[:11],
                str(r["청년등"])[:11],
                str(r["상시"]),
                *m_cells,
                f"{r['합계']:g}",
                f"{r['b1_yth']:.2f}", f"{r['b1_gen']:.2f}", f"{r['b1_reg']:.2f}",
            ]
            if col_has_y1:
                if yr_has_y1:
                    row_cells.extend([f"{r['b2_yth']:.2f}", f"{r['b2_gen']:.2f}", f"{r['b2_reg']:.2f}"])
                else:
                    row_cells.extend(["-", "-", "-"])
            if col_has_y2:
                if yr_has_y2:
                    row_cells.extend([f"{r['b3_yth']:.2f}", f"{r['b3_gen']:.2f}", f"{r['b3_reg']:.2f}"])
                else:
                    row_cells.extend(["-", "-", "-"])
            tbl_data.append(row_cells)

        # 하단 요약 3행 추가 (2~9열 SPAN 병합으로 안내 문구가 이웃 열과 겹치지 않도록 정렬)
        sum_rows = [
            (
                "합산합계", "상시근로자", f"÷ {totals['months_in_year']}개월 ({trunc_mode})",
                [f"{v:g}" if v is not None else "-" for v in totals["월별_상시"]],
                f"{totals['상시_합계']:g}",
                [f"{totals['b1_yth']:.2f}", f"{totals['b1_gen']:.2f}", f"{totals['b1_reg']:.2f}"],
                [f"{totals['b2_yth']:.2f}", f"{totals['b2_gen']:.2f}", f"{totals['b2_reg']:.2f}"] if yr_has_y1 else ["-", "-", "-"],
                [f"{totals['b3_yth']:.2f}", f"{totals['b3_gen']:.2f}", f"{totals['b3_reg']:.2f}"] if yr_has_y2 else ["-", "-", "-"],
            ),
            (
                "합산합계", "청년등", "각 코호트 기준",
                [f"{v:g}" if v is not None else "-" for v in totals["월별_청년등"]],
                f"{totals['청년등_합계']:g}",
                [f"{totals['b1_yth']:.2f}", "-", "-"],
                [f"{totals['b2_yth']:.2f}", "-", "-"] if yr_has_y1 else ["-", "-", "-"],
                [f"{totals['b3_yth']:.2f}", "-", "-"] if yr_has_y2 else ["-", "-", "-"],
            ),
            (
                "합산합계", "청년등 외", "상시 - 청년등",
                [f"{v:g}" if v is not None else "-" for v in totals["월별_청년외"]],
                f"{totals['청년외_합계']:g}",
                ["-", f"{totals['b1_gen']:.2f}", "-"],
                ["-", f"{totals['b2_gen']:.2f}", "-"] if yr_has_y1 else ["-", "-", "-"],
                ["-", f"{totals['b3_gen']:.2f}", "-"] if yr_has_y2 else ["-", "-", "-"],
            ),
        ]
        for wp_l, nm_l, et_l, m_list, tot_s, b1_l, b2_l, b3_l in sum_rows:
            s_row = [wp_l, nm_l, et_l, "", "", "", "", "", "", "", *m_list, tot_s, *b1_l]
            if col_has_y1:
                s_row.extend(b2_l)
            if col_has_y2:
                s_row.extend(b3_l)
            tbl_data.append(s_row)

        t_obj = Table(tbl_data, colWidths=col_widths, repeatRows=1)
        n_data_end = len(tbl_data) - 3
        t_style = [
            ("FONTNAME", (0, 0), (-1, 0), bold_font),
            ("FONTNAME", (0, 1), (-1, -1), reg_font),
            ("FONTNAME", (0, n_data_end), (-1, -1), bold_font),
            ("FONTSIZE", (0, 0), (-1, -1), 6.4),
            ("LEADING", (0, 0), (-1, -1), 8.2),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("BACKGROUND", (0, n_data_end), (-1, -1), colors.HexColor("#dcfce7")),
            ("TEXTCOLOR", (0, n_data_end), (-1, -1), colors.HexColor("#14532d")),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#cbd5e1")),
            ("LINEABOVE", (0, n_data_end), (-1, n_data_end), 0.8, colors.HexColor("#15803d")),
            ("LINEBELOW", (0, -1), (-1, -1), 0.9, colors.HexColor("#14532d")),
            ("TOPPADDING", (0, 0), (-1, -1), 2.8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.8),
            ("LEFTPADDING", (0, 0), (-1, -1), 1.5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 1.5),
        ]
        for sum_r in range(n_data_end, len(tbl_data)):
            t_style.append(("SPAN", (2, sum_r), (9, sum_r)))
        for r_i in range(1, n_data_end):
            if r_i % 2 == 0:
                t_style.append(("BACKGROUND", (0, r_i), (-1, r_i), colors.HexColor("#f8fafc")))
        t_obj.setStyle(TableStyle(t_style))
        story.append(t_obj)

    if include_summary and tax_yr in totals_by_yr and (tax_yr - 1) in totals_by_yr:
        story.append(Spacer(1, 10))
        cur_t = totals_by_yr[tax_yr]
        adj_prv, _, _ = _adjusted_prev_totals(s, totals_by_yr[tax_yr - 1])
        eff_prv_reg = round(adj_prv["상시_평균"], 2)
        eff_prv_yth = round(adj_prv["청년등_평균"], 2)
        eff_prv_gen = round(max(0.0, eff_prv_reg - eff_prv_yth), 2)
        inc = H.calc_increase_with_cap(
            cur_t["상시_평균"], cur_t["청년등_평균"], cur_t["청년외_평균"], eff_prv_reg, eff_prv_yth, eff_prv_gen
        )
        story.append(
            Paragraph(
                f"■ [{tax_yr}년 vs {tax_yr-1}년 신규공제 고용증가 요약]  "
                f"전체 상시 증가: +{inc['전체_증가']:.2f}명  |  "
                f"청년등 인정 증가: +{inc['청년등_증가']:.2f}명  |  "
                f"청년등 외 인정 증가: +{inc['청년등외_증가']:.2f}명",
                st_yr_hdr,
            )
        )

    doc.build(story)
    return buf.getvalue()


# ══════════════════════════════════════════════════════════════════
# 1. "자율 에이전트AI" 100% 동일 톤앤매너 CSS + 고시인성 KPI 카드바 + 붉은색 PDF 버튼
# ══════════════════════════════════════════════════════════════════
CSS = """
<style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');

/* 🪟 모달(Dialog) 창 정중앙 배치 및 시인성 강화 */
div[data-testid="stDialog"] {
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
}
div[data-testid="stDialog"] > div[role="dialog"],
div[role="dialog"] {
    width: min(1160px, 92vw) !important;
    max-width: 92vw !important;
    margin: auto !important;
    border-radius: 14px !important;
}
div[role="dialog"] li,
div[role="dialog"] p {
    font-family: 'Pretendard', 'Malgun Gothic', sans-serif !important;
    font-size: 0.98rem !important;
    line-height: 1.62 !important;
    color: #1e293b !important;
    word-break: keep-all !important;
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
    corp_sz = b.get("기업구분") or "중소기업"
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
    law_ver = f"{tax_yr}귀속 (합산 후 절사 · 사후관리: {pm_lbl})"
    step_nm = STEPS[max(0, min(len(STEPS) - 1, int(s.get("step", 1)) - 1))]

    st.markdown(
        f"<div id='ec-page-top-anchor'></div>"
        f"<div class='top-mini-status-bar'>"
        f"<span>🧮 <b>통합고용세액공제 ({tax_yr}년 귀속)</b> &nbsp;|&nbsp; {biz_disp}</span>"
        f"<span>📌 현재 단계: <b>{s.get('step', 1)}단계 [{step_nm}]</b> &nbsp;·&nbsp; <span class='sb-badge-green'>💾 자동보관 ON · {law_ver}</span></span>"
        f"</div>",
        unsafe_allow_html=True,
    )




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
        import streamlit.components.v1 as components
        components.html(
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
            height=0,
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
                    use_container_width=True,
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
# 2. 별도 창(대화상자 — 12대 정밀 오류검토 + Pro/Argon 심층 세무진단 연동)
# ══════════════════════════════════════════════════════════════════
@st.dialog("📋 자료 확인 안내")
def _dlg_missing(msgs: list[str]):
    for m in msgs:
        st.markdown(f"- {m}")
    st.caption("확인을 누르면 현재까지 인식된 자료로 다음 단계로 넘어갑니다. 부족한 정보는 사원정보 화면과 사이드바에서 직접 입력·수정할 수 있습니다.")
    if st.button("✅ 확인 및 2단계(사원정보)로 이동", type="primary", use_container_width=True):
        s = _S()
        s["go_step2"] = True
        _save_ec_to_disk(s)
        st.rerun()


@st.dialog("🚫 통합고용세액공제 적용 불가 업종 안내")
def _dlg_industry(text: str):
    st.markdown(f"감지된 업태·종목: **{text}**")
    st.markdown(
        "소비성서비스업(호텔업·여관업[관광숙박업 제외], 일반유흥·무도유흥주점 및 단란주점[외국인전용·관광유흥음식점 제외], "
        "오락·유흥 목적 사업)은 통합고용세액공제를 적용받을 수 없습니다. "
        "(`조세특례제한법` 제29조의8 제1항, `같은 법 시행령` 제26조의8 제1항 및 제29조 제3항)"
    )
    st.caption("업종이 잘못 읽혔거나 겸업 중 공제 가능 사업부문이라면 좌측 사이드바에서 업태·종목을 수정한 뒤 진행하세요.")
    if st.button("확인", type="primary", use_container_width=True):
        st.rerun()


@st.dialog("🔍 법령·심판례·절세누락 12대 정밀 오류 검토", width="large")
def _dlg_review(items: list[tuple[str, str]], audit_payload: dict | None = None, log_tokens_fn=None, room_key: str = ""):
    s = _S()
    errs = [m for lv, m in items if lv == "오류"]
    savs = [m for lv, m in items if lv == "절세누락"]
    chks = [m for lv, m in items if lv == "확인"]

    st.markdown(
        f"<div style='display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:10px;flex-wrap:wrap;'>"
        f"<div style='display:flex;gap:8px;flex-wrap:wrap;'>"
        f"<span style='background:#fef2f2;color:#b91c1c;border:1px solid #fecaca;padding:5px 13px;border-radius:999px;font-weight:800;font-size:0.92rem;'>🚨 필수 수정 오류 {len(errs)}건</span>"
        f"<span style='background:#f0fdf4;color:#15803d;border:1px solid #86efac;padding:5px 13px;border-radius:999px;font-weight:800;font-size:0.92rem;'>💰 절세누락 주의 {len(savs)}건</span>"
        f"<span style='background:#eff6ff;color:#1d4ed8;border:1px solid #bfdbfe;padding:5px 13px;border-radius:999px;font-weight:800;font-size:0.92rem;'>💡 실무·심판례 확인 {len(chks)}건</span>"
        f"</div>"
        f"<span style='font-size:0.86rem;color:#64748b;font-weight:600;'>※ 반복 안내 항목은 연도별로 자동 묶음 요약됩니다.</span>"
        f"</div>",
        unsafe_allow_html=True,
    )

    if not items:
        st.success("✅ 법령 및 최신 조세심판례 12대 항목 검토 결과, 발견된 오류나 절세누락 사항이 없습니다.")
    else:
        sections_html = ["<div class='ec-rev-scroll-wrap'>"]
        if errs:
            sections_html.append(
                f"<div class='ec-rev-sec-hdr err'>"
                f"<span>🚨 필수 수정 오류 ({len(errs)}건) — 수정해야 정확한 상시근로자 수가 계산됩니다</span>"
                f"</div>"
                f"<div class='ec-rev-grid'>"
            )
            for m in errs:
                sections_html.append(f"<div class='ec-rev-card err'>• <b>{m}</b></div>")
            sections_html.append("</div>")

        if savs:
            sections_html.append(
                f"<div class='ec-rev-sec-hdr sav'>"
                f"<span>💰 절세누락 주의 ({len(savs)}건) — 청년·고령자·장애인 우대공제 추가 적용 가능 대상</span>"
                f"</div>"
                f"<div class='ec-rev-grid'>"
            )
            for m in savs:
                sections_html.append(f"<div class='ec-rev-card sav'>• <b>{m}</b></div>")
            sections_html.append("</div>")

        if chks:
            sections_html.append(
                f"<div class='ec-rev-sec-hdr chk'>"
                f"<span>💡 실무·심판례 확인 사항 ({len(chks)}건) — 사실관계가 맞다면 그대로 진행하셔도 됩니다</span>"
                f"</div>"
                f"<div class='ec-rev-grid'>"
            )
            for m in chks:
                sections_html.append(f"<div class='ec-rev-card chk'>• {m}</div>")
            sections_html.append("</div>")

        sections_html.append("</div>")
        st.markdown("".join(sections_html), unsafe_allow_html=True)

    corp_fn = re.sub(r'[\\/:*?"<>|\s]+', "_", str((s.get("biz") or {}).get("상호") or "사업장"))[:30]
    tax_yr = int(s.get("tax_year") or R.DEFAULT_TAX_YEAR)

    st.markdown("<div class='ec-nav-divider' style='margin:10px 0;'></div>", unsafe_allow_html=True)
    c_ai, c_pdf_rev, c_close = st.columns([2.15, 1.15, 0.85])
    with c_ai:
        if audit_payload:
            if st.button("👑 Pro/Argon AI 심층 세무진단 코멘트 생성 (특수사례·판례 정밀점검)", use_container_width=True, key="btn_run_pro_audit"):
                with st.spinner("👑 Pro/Argon 모델이 사원표·특례·사후관리 리스크를 심층 분석하고 있습니다..."):
                    s["pro_audit_comment"] = getattr(P, "call_pro_argon_audit_commentary", lambda *a, **kw: "Pro/Argon 심층 진단 함수를 찾을 수 없습니다. parsers.py를 최신 버전으로 업데이트해 주세요.")(
                        audit_payload, log_tokens_fn=log_tokens_fn, room_key=room_key
                    )
                    _save_ec_to_disk(s)
    with c_pdf_rev:
        with st.container(key="ec_btn_pdf_rev_only"):
            st.download_button(
                "📕 오류검토 PDF 다운",
                data=_build_review_pdf_bytes(s, items, pro_comment=""),
                file_name=f"통합고용_오류검토_{corp_fn}_{tax_yr}귀속.pdf",
                mime="application/pdf",
                use_container_width=True,
                key="btn_dl_review_pdf",
                help="현재 화면의 법령·심판례·절세누락 12대 정밀 오류 검토 내역을 A4 PDF로 다운로드합니다.",
            )
    with c_close:
        if st.button("닫기", type="primary", use_container_width=True, key="btn_close_dlg_review"):
            st.rerun()

    if s.get("pro_audit_comment"):
        with st.container(border=True):
            c_pro_hdr, c_pro_pdf = st.columns([3.0, 1.25])
            with c_pro_hdr:
                st.markdown("##### 👑 Pro/Argon AI 심층 세무진단 의견")
            with c_pro_pdf:
                if not str(s["pro_audit_comment"]).startswith("❌"):
                    with st.container(key="ec_btn_pdf_rev_pro"):
                        st.download_button(
                            "📕 심층진단 포함 PDF 다운",
                            data=_build_review_pdf_bytes(s, items, pro_comment=str(s.get("pro_audit_comment") or "")),
                            file_name=f"통합고용_심층진단_{corp_fn}_{tax_yr}귀속.pdf",
                            mime="application/pdf",
                            use_container_width=True,
                            key="btn_dl_pro_pdf",
                            help="12대 정밀 오류 검토 내역과 Pro/Argon AI 심층 세무진단 코멘트를 함께 A4 PDF로 다운로드합니다.",
                        )
            st.markdown(s["pro_audit_comment"])


# ══════════════════════════════════════════════════════════════════
# 3. 사이드바: 귀속사업연도(2024~2028) · 주사업장 정보 + 하단 추가 합산 사업장(본·지점 / 양도·양수)
# ══════════════════════════════════════════════════════════════════
def _int(v, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def render_credit_sidebar():
    s = _S()
    tax_yr = int(s.get("tax_year") or R.DEFAULT_TAX_YEAR)
    if tax_yr not in R.SUPPORTED_TAX_YEARS:
        tax_yr = R.DEFAULT_TAX_YEAR
        s["tax_year"] = tax_yr

    with st.container(border=True):
        yr_badge = (
            f"<span class='sb-badge-green'>{tax_yr}년 (합산 후 절사)</span>"
            if tax_yr >= 2025
            else f"<span class='sb-badge-amber'>{tax_yr}년 (합산 후 절사)</span>"
        )
        st.markdown(
            f"<div class='sb-card-title'><span>📅 귀속사업연도</span>{yr_badge}</div>",
            unsafe_allow_html=True,
        )
        new_year = st.selectbox(
            "통합고용세액공제 계산 기준 사업연도",
            options=R.SUPPORTED_TAX_YEARS,
            index=R.SUPPORTED_TAX_YEARS.index(tax_yr),
            format_func=lambda y: f"{y}년 귀속 ({'합산 후 절사'} · {(y-1)%100:02d}·{(y-2)%100:02d} 사후관리)",
            label_visibility="collapsed",
            key="ec_sb_tax_year_select",
        )
        if new_year != s["tax_year"]:
            s["tax_year"] = int(new_year)
            s["manual_extra_years"] = []
            s["built_sig"] = None
            _ensure_built_for_tax_year(s)
            _save_ec_to_disk(s)
            st.rerun()

    with st.container(border=True, key="ec_biz"):
        b, conf = s["biz"], set(s["biz_confirmed"])
        sub_list = s.setdefault("sub_biz_list", [])
        cap = H.is_capital_area(b.get("사업장소재지", ""))
        if cap is True:
            loc_pill = "<span class='sb-badge-amber'>수도권 사업장</span>"
        elif cap is False:
            loc_pill = "<span class='sb-badge-green'>수도권 외(비수도권)</span>"
        else:
            loc_pill = "<span class='sb-badge-pro'>직접입력/자동추출</span>"

        main_title_lbl = "🏢 주사업장(본점) 정보" if sub_list else "🏢 사업자정보"
        st.markdown(
            f"<div class='sb-card-title'><span>{main_title_lbl}</span>{loc_pill}</div>",
            unsafe_allow_html=True,
        )

        def txt(label, field, placeholder=""):
            v = st.text_input(
                label,
                value=str(b.get(field, "") or ""),
                disabled=field in conf,
                placeholder=placeholder,
                key=f"ec_biz_{field}",
            )
            b[field] = v

        txt("상호(법인명 · 주사업장명)", "상호", "예: (주)세무에이전트 본점 / 1번사업장")
        txt("설립일(개업일)", "설립일", "YYYY-MM-DD")
        txt("사업자등록번호", "사업자번호", "000-00-00000")
        c_u1, c_u2 = st.columns(2)
        with c_u1:
            b["업태"] = st.text_input("업태", value=str(b.get("업태", "") or ""), disabled="업태" in conf, key="ec_biz_업태")
        with c_u2:
            b["종목"] = st.text_input("종목", value=str(b.get("종목", "") or ""), disabled="종목" in conf, key="ec_biz_종목")
        txt("사업장 소재지", "사업장소재지", "예: 서울특별시 강남구... / 충청남도...")

        b["기업구분"] = st.selectbox(
            "기업 규모 구분",
            R.CORP_SIZES,
            index=R.CORP_SIZES.index(b.get("기업구분", "중소기업")) if b.get("기업구분") in R.CORP_SIZES else 0,
            key="ec_biz_size",
        )
        c1, c2 = st.columns(2)
        b["전년_월수"] = c1.number_input(
            f"직전({tax_yr-1}년) 월수",
            min_value=1,
            max_value=12,
            value=max(1, min(12, _int(b.get("전년_월수"), 12))),
            key="ec_biz_pm",
            help="1년 과세기간 상한이 12개월이므로 12개월일 때는 [+] 버튼이 비활성화됩니다. 기중 개업·폐업 시 [-] 버튼이나 직접 입력으로 월수를 줄일 수 있습니다.",
        )
        b["당해_월수"] = c2.number_input(
            f"당해({tax_yr}년) 월수",
            min_value=1,
            max_value=12,
            value=max(1, min(12, _int(b.get("당해_월수"), 12))),
            key="ec_biz_cm",
            help="1년 과세기간 상한이 12개월이므로 12개월일 때는 [+] 버튼이 비활성화됩니다. 기중 개업·폐업 시 [-] 버튼이나 직접 입력으로 월수를 줄일 수 있습니다.",
        )
        st.caption("💡 과세연도 월수 상한은 12개월입니다(12일 때 `+` 비활성 · 기중 개업/폐업 시 `-`로 조정).")

        if conf:
            if st.button("🔓 사업자정보 잠금 해제 (직접 수정)", use_container_width=True, key="btn_unlock_biz"):
                s["biz_confirmed"] = []
                _save_ec_to_disk(s)
                st.rerun()

        # ── 하단: 제2사업장 등 추가 합산 사업장 표시 영역 ──
        if sub_list:
            st.markdown(
                f"<div style='margin-top:8px; padding-top:8px; border-top:1px dashed #cbd5e1; "
                f"font-size:0.84rem; font-weight:800; color:#1e3a8a;'>"
                f"🔗 합산 대상 추가 사업장 ({len(sub_list)}곳)</div>",
                unsafe_allow_html=True,
            )
            remove_idx = None
            for idx, sb in enumerate(sub_list):
                with st.expander(
                    f"🏢 제{idx+2}사업장: {sb.get('상호') or f'추가사업장{idx+2}'} ({sb.get('구분', '합산')[:4]})",
                    expanded=True,
                ):
                    cur_t_opt = sb.get("구분") if sb.get("구분") in R.WORKPLACE_TYPES else R.WORKPLACE_TYPES[0]
                    sb["구분"] = st.selectbox(
                        "합산 사유 구분",
                        options=R.WORKPLACE_TYPES,
                        index=R.WORKPLACE_TYPES.index(cur_t_opt),
                        key=f"ec_sub_type_{idx}",
                    )
                    sb["상호"] = st.text_input(
                        f"제{idx+2}사업장명(상호)",
                        value=str(sb.get("상호", "") or ""),
                        placeholder="예: 강남지점 / 2번사업장(포괄양수)",
                        key=f"ec_sub_nm_{idx}",
                    )
                    sb["사업자번호"] = st.text_input(
                        "사업자등록번호",
                        value=str(sb.get("사업자번호", "") or ""),
                        placeholder="000-00-00000",
                        key=f"ec_sub_no_{idx}",
                    )
                    sb["사업장소재지"] = st.text_input(
                        "사업장 소재지",
                        value=str(sb.get("사업장소재지", "") or ""),
                        placeholder="예: 경기도 성남시...",
                        key=f"ec_sub_addr_{idx}",
                    )
                    cs1, cs2 = st.columns(2)
                    sb["개업일"] = cs1.text_input(
                        "개업·양수일",
                        value=str(sb.get("개업일", "") or ""),
                        placeholder="YYYY-MM-DD",
                        key=f"ec_sub_open_{idx}",
                    )
                    sb["폐업일"] = cs2.text_input(
                        "폐업·양도일",
                        value=str(sb.get("폐업일", "") or ""),
                        placeholder="YYYY-MM-DD",
                        key=f"ec_sub_close_{idx}",
                    )

                    tp_str = str(sb.get("구분") or "")
                    if any(k in tp_str for k in ("포괄양수", "승계", "합병", "분할", "법인전환")):
                        st.caption("⚖️ **승계한 기업 특례 (조특령 제23조 제13항 준용)**: 피승계 사업장의 직전연도 인원을 입력하면 직전연도 비교 인원에 더합니다. "
                                   "당해연도는 『개업·양수일』을 승계일로 보고 그 이전 달도 산입합니다(비워두면 이 사업장 직원의 첫 급여월로 추정).")
                        cp1, cp2 = st.columns(2)
                        sb["승계_직전상시"] = cp1.number_input(
                            f"피승계 직전({tax_yr-1}년) 상시",
                            min_value=0.0,
                            max_value=9999.0,
                            value=float(sb.get("승계_직전상시") or 0.0),
                            step=0.01,
                            format="%.2f",
                            key=f"ec_sub_prev_reg_{idx}",
                        )
                        sb["승계_직전청년"] = cp2.number_input(
                            f"피승계 직전({tax_yr-1}년) 청년등",
                            min_value=0.0,
                            max_value=9999.0,
                            value=float(sb.get("승계_직전청년") or 0.0),
                            step=0.01,
                            format="%.2f",
                            key=f"ec_sub_prev_yth_{idx}",
                        )
                        sb["고용승계_입사일유지"] = st.checkbox(
                            "승계 근로자 최초 입사일·계약일 유지 적용",
                            value=bool(sb.get("고용승계_입사일유지", True)),
                            key=f"ec_sub_keep_hire_{idx}",
                            help="포괄양수·법인전환 등으로 고용을 승계한 근로자는 종전 사업장 최초 근로계약 체결일 기준으로 청년 연령 및 1년 이상 근속 여부를 판정합니다.",
                        )
                    elif "기중양도" in tp_str:
                        sb["양도_고용승계"] = st.checkbox(
                            "양수인이 근로자를 승계함 (포괄양도)",
                            value=bool(sb.get("양도_고용승계", False)),
                            key=f"ec_sub_tr_succ_{idx}",
                            help="체크하면 조특령 제23조 제13항(준용)에 따라, 양도일 현재 이 사업장 근로자를 과세연도 개시일에 넘긴 것으로 보아 "
                                 "당해 인원에서 빼고 직전연도 인원에서도 자동으로 차감합니다.",
                        )
                        if sb.get("양도_고용승계"):
                            st.caption("⚖️ **승계시킨 기업 특례**: 『폐업·양도일』 현재 이 사업장 근로자는 당해 인원에서 제외되고, "
                                       "그 근로자들의 직전연도 인원은 사원표로 자동 계산해 직전연도 비교 인원에서 뺍니다.")
                        else:
                            st.caption("⚖️ **단순 폐업·양도(고용승계 없음)**: 『폐업·양도일』 이후 달은 0으로 처리하고, 그 전 달은 정상 산입합니다.")
                    else:
                        st.caption(
                            "⚖️ **법인 본·지점 합산 특례**: 본·지점 간 전출입(`본점→지점`) 근로자는 동일인으로 통합하여 월급여를 합산하며 중복 산입을 자동 방지합니다."
                        )

                    if st.button(f"🗑️ 제{idx+2}사업장 삭제", key=f"btn_del_sub_biz_{idx}", use_container_width=True):
                        remove_idx = idx
            if remove_idx is not None:
                sub_list.pop(remove_idx)
                _save_ec_to_disk(s)
                st.rerun()

        if st.button(
            "➕ 합산 사업장 추가 (지점 · 양도/양수)",
            use_container_width=True,
            key="btn_add_sub_biz",
            help="법인 본·지점 합산 또는 개인사업자 기중 사업 양도·포괄양수 시 두 번째(추가) 사업장 정보를 하단에 추가합니다.",
        ):
            next_no = len(sub_list) + 2
            sub_list.append(
                {
                    "구분": "지점(법인 본·지점 합산)",
                    "상호": f"제{next_no}사업장",
                    "사업자번호": "",
                    "사업장소재지": "",
                    "업태": "",
                    "종목": "",
                    "개업일": "",
                    "폐업일": "",
                    "승계_직전상시": 0.0,
                    "승계_직전청년": 0.0,
                    "고용승계_입사일유지": True,
                }
            )
            _save_ec_to_disk(s)
            st.rerun()

    _save_ec_to_disk(s)
    _render_backup_card(s)
    ind = f"{b.get('업태', '')} {b.get('종목', '')}".strip()
    if ind and H.is_excluded_industry(ind) and s["industry_alert_for"] != ind:
        s["industry_alert_for"] = ind
        _dlg_industry(ind)


# ══════════════════════════════════════════════════════════════════
# 3-1. 작업 백업 (비밀번호 암호화 파일로 내 PC에 저장 / 다시 불러오기)
# ══════════════════════════════════════════════════════════════════
def _current_build_sig(s: dict) -> str:
    """_ensure_built_for_tax_year와 같은 방식의 작업 서명 (복원 후 불필요한 재구축 방지용)"""
    wp_sig = json.dumps(
        sorted((n, f.get("key"), f.get("wp", "")) for n, f in (s.get("files") or {}).items()),
        ensure_ascii=False,
    )
    return f"{s.get('ext_sig')}|{s['tax_year']}|{wp_sig}"


def _restore_from_backup(inner: dict) -> None:
    """백업 내용으로 현재 작업공간의 계산기 상태를 통째로 바꿉니다."""
    ws_id = st.session_state.get("loaded_workspace_id") or "default_ec"
    store = st.session_state.setdefault("ec_by_ws", {})
    base = _default_state_dict()
    for k, v in (inner.get("state") or {}).items():
        if v is not None:
            base[k] = v
    if isinstance(base.get("year_recs"), dict):          # JSON 저장 시 문자열이 된 연도 키 복원
        base["year_recs"] = {(int(k) if str(k).isdigit() else k): v for k, v in base["year_recs"].items()}
    if isinstance(base.get("manual_extra_years"), list):
        base["manual_extra_years"] = [int(y) for y in base["manual_extra_years"] if str(y).isdigit()]
    base["grid_ver"], base["last_sent"] = {}, {}
    base["built_sig"] = _current_build_sig(base)          # 복원한 사원표를 그대로 쓰고 다시 만들지 않음
    if base.get("people"):
        base["step"] = max(2, int(base.get("step") or 2))
    store[ws_id] = base
    # 입력칸이 이전 값을 붙잡고 있지 않도록 계산기 위젯 상태 초기화
    for k in list(st.session_state.keys()):
        if str(k).startswith(("ec_biz_", "ec_sub_", "pf_", "calc_", "prev_sum_", "ec_grid_", "pm_basis")):
            del st.session_state[k]
    st.session_state.ec = base
    _save_ec_to_disk(base)


def _render_backup_card(s: dict) -> None:
    with st.container(border=True):
        st.markdown("<div class='sb-card-title'><span>💾 작업 백업 (내 PC)</span></div>", unsafe_allow_html=True)
        if not B.crypto_available():
            st.caption("백업 기능을 쓰려면 requirements.txt에 `cryptography`를 추가하고 앱을 재시작하세요.")
            return
        st.caption("앱을 재시작하면 서버의 작업 내용이 사라질 수 있습니다. 비밀번호를 건 파일로 PC에 보관했다가 다시 올려 이어서 작업하세요.")
        tab_save, tab_load = st.tabs(["⬇️ 내려받기", "⬆️ 불러오기"])

        with tab_save:
            pw1 = st.text_input("백업 비밀번호", type="password", key="ec_bk_pw1",
                                help=f"{B.MIN_PASSWORD_LEN}자 이상. 잊으면 이 백업은 복구할 수 없습니다.")
            pw2 = st.text_input("비밀번호 확인", type="password", key="ec_bk_pw2")
            if st.button("백업 파일 만들기", use_container_width=True, key="ec_bk_make"):
                if pw1 != pw2:
                    st.error("두 비밀번호가 다릅니다.")
                elif not (s.get("people") or s.get("biz", {}).get("상호")):
                    st.warning("백업할 작업 내용이 없습니다.")
                else:
                    try:
                        data, fname = B.make_backup_bytes(s, pw1)
                        st.session_state["ec_bk_ready"] = (data, fname)
                    except B.BackupError as e:
                        st.error(str(e))
            ready = st.session_state.get("ec_bk_ready")
            if ready:
                st.download_button("📥 백업 파일 내려받기", data=ready[0], file_name=ready[1],
                                   mime="application/octet-stream", use_container_width=True, key="ec_bk_dl",
                                   on_click=lambda: st.session_state.pop("ec_bk_ready", None))
                st.caption(f"`{ready[1]}`  \n고객 자료와 같은 보안 폴더에 보관하세요. 비밀번호는 파일과 따로 관리하세요.")

        with tab_load:
            up = st.file_uploader("백업 파일 (.ecbak)", type=[B.FILE_EXT], key="ec_bk_up")
            pw = st.text_input("백업 비밀번호", type="password", key="ec_bk_pw_in")
            if up is not None and st.button("파일 열기", use_container_width=True, key="ec_bk_open"):
                try:
                    st.session_state["ec_bk_loaded"] = B.read_backup_bytes(up.getvalue(), pw)
                except B.BackupError as e:
                    st.session_state.pop("ec_bk_loaded", None)
                    st.error(str(e))
            inner = st.session_state.get("ec_bk_loaded")
            if inner:
                st.info(f"**{inner.get('상호')} · {inner.get('tax_year')}년 귀속**  \n"
                        f"저장 시각 {inner.get('saved_at')} · 사원 {inner.get('people_count', 0)}명")
                st.warning("현재 작업 내용이 이 백업으로 모두 바뀝니다. 필요하면 먼저 지금 작업을 백업해 두세요.")
                c1, c2 = st.columns(2)
                if c1.button("이 백업으로 바꾸기", type="primary", use_container_width=True, key="ec_bk_apply"):
                    _restore_from_backup(inner)
                    st.session_state.pop("ec_bk_loaded", None)
                    st.rerun()
                if c2.button("취소", use_container_width=True, key="ec_bk_cancel"):
                    st.session_state.pop("ec_bk_loaded", None)
                    st.rerun()


# ══════════════════════════════════════════════════════════════════
# 4. 1단계: 자료 업로드
# ══════════════════════════════════════════════════════════════════
def _page_upload(extract_file_fn, log_tokens_fn, room_key):
    s = _S()
    tax_yr = int(s["tax_year"])
    if s.pop("go_step2", False):
        _enter_step2()
        st.rerun()

    st.markdown(f"### 📂 1. 자료 업로드 ({tax_yr}년 귀속 기준)")

    if tax_yr == 2026:
        st.markdown(
            "<div class='ec-law-banner'>"
            "💡 <b>[2026년 귀속 통합 계산 안내]</b> 2026년 귀속 신고 시에는 "
            "<b>① 26년 세액공제(합산 후 절사)</b>, <b>② 25년 1차 사후관리(2차년도 연속공제·추징)</b>, "
            "<b>③ 24년 2차 사후관리(3차년도 연속공제·추징)</b>를 함께 검토합니다. "
            "본점·지점 또는 기중 양도(1번)·포괄양수(2번) 복수 사업장 원천징수부를 함께 올리면 자동 합산됩니다."
            "</div>",
            unsafe_allow_html=True,
        )
    elif tax_yr in (2024, 2025):
        trunc_lbl = "합산 후 절사"
        st.markdown(
            f"<div class='ec-law-banner'>"
            f"💡 <b>[{tax_yr}년 귀속 세액공제({trunc_lbl}) 및 사후관리 안내]</b> 2단계 진입 시 <b>『{tax_yr}년 귀속 상시근로자 명세』</b>가 맨 위에 표시되며, "
            f"<b>{tax_yr}년 세액공제({trunc_lbl})</b>와 자료가 있는 <b>{tax_yr-1}년 1차 사후관리</b>·<b>{tax_yr-2}년 2차 사후관리</b>를 자동 구성합니다."
            f"</div>",
            unsafe_allow_html=True,
        )
    else:
        comp_map = H.valid_comparison_years_for_new_credit(tax_yr)
        active_comp = [f"{k}({v}년)" for k, v in comp_map.items() if v is not None]
        st.markdown(
            f"<div class='ec-law-banner'>"
            f"💡 <b>[{tax_yr}년 귀속 점증형 공제 안내]</b> 비교 대상 과세연도: <b>{', '.join(active_comp)}</b> "
            f"(2024.12.31. 이전 개시 과세연도 제외 규정 반영 · A+B+C 자동 합산)."
            f"</div>",
            unsafe_allow_html=True,
        )

    doc_types = R.get_doc_types(tax_yr)
    doc_help = R.get_doc_help(tax_yr)
    all_labels = R.get_all_selectable_doc_labels(tax_yr)
    base_keys = {k for k, *_ in doc_types}

    docs_table_slot = st.empty()
    uploaded_list_slot = st.container()

    st.markdown(
        "<div class='ec-bottom-upload-label'>"
        "<span>📥 <b>파일 추가 업로드</b> (본·지점 / 양도·양수 복수 사업장 파일도 한꺼번에 끌어다 놓으세요)</span>"
        f"<span style='color:#16a34a;font-size:0.80rem;'>{tax_yr-2}·{tax_yr-1}·{tax_yr}년 원천징수부(100% 자체 고속파싱) · 복수 사업장 합산 지원</span>"
        "</div>",
        unsafe_allow_html=True,
    )
    with st.container(key="ec_drop"):
        ups = st.file_uploader(
            "여기에 파일(PDF·엑셀·CSV·이미지)을 끌어다 놓으세요",
            accept_multiple_files=True,
            type=["pdf", "xlsx", "xls", "csv", "png", "jpg", "jpeg"],
            key=f"ec_up_{s['uploader_ver']}",
            label_visibility="collapsed",
        )

    new = [u for u in (ups or []) if u.name not in s["files"]]
    if new:
        with st.spinner(f"📄 {len(new)}개 파일에서 텍스트 및 표 데이터를 추출하고 있습니다..."):
            for u in new:
                text = _read_upload_text(u, extract_file_fn, room_key)
                auto_wp = _sanitize_workplace_label(getattr(P, "infer_workplace_name", lambda nm, tx="": "")(u.name, text), _default_workplace_label(s))
                s["files"][u.name] = {
                    "key": P.classify_file(u.name, text),
                    "text": text,
                    "wp": auto_wp,
                }
        s["uploader_ver"] += 1
        s["built_sig"] = None
        _save_ec_to_disk(s)
        st.rerun()

    with uploaded_list_slot:
        if s["files"]:
            with st.container(border=True):
                c_h1, c_h2 = st.columns([4, 1])
                with c_h1:
                    st.markdown(
                        f"**📎 업로드된 파일 목록 ({len(s['files'])}건)** — *본·지점 또는 1·2번 사업장 합산 시 가운데 칸에서 『사업장명』을 구분해 주시면 2단계 표 맨 앞에 자동 기록됩니다.*"
                    )
                with c_h2:
                    if st.button("🗑️ 전체 파일 비우기", use_container_width=True, key="ec_clear_all_files"):
                        s["files"] = {}
                        s["ext"] = None
                        s["ext_sig"] = None
                        s["built_sig"] = None
                        s["uploader_ver"] += 1
                        _save_ec_to_disk(s)
                        st.rerun()

                opts = [None] + list(all_labels.keys())
                for name, f in list(s["files"].items()):
                    c1, c_wp, c2, c3 = st.columns([3.4, 1.8, 3.8, 0.9])
                    c1.markdown(f"📄 **{name}**" + (" · <span style='color:#64748b;font-size:.8rem'>💾 백업 복원(원문 없음)</span>"
                                                     if f.get("restored") and not f.get("text") else ""),
                                unsafe_allow_html=True)
                    cur_wp = _sanitize_workplace_label(str(f.get("wp") or ""), _default_workplace_label(s))
                    new_wp = c_wp.text_input(
                        "사업장명",
                        value=cur_wp,
                        placeholder="예: 본점 / 지점 / 1사업장",
                        key=f"ec_wp_{name}",
                        label_visibility="collapsed",
                        help="이 파일에 속한 근로자들의 소속 사업장명(예: 본점, 강남지점, 1번사업장, 2번사업장)",
                    )
                    if new_wp.strip() != cur_wp:
                        f["wp"] = new_wp.strip()
                        s["built_sig"] = None
                        _save_ec_to_disk(s)

                    cur_k = f.get("key") if f.get("key") in opts else None
                    new_k = c2.selectbox(
                        "종류",
                        opts,
                        index=opts.index(cur_k),
                        key=f"ec_k_{name}",
                        format_func=lambda k: "⚠️ 서류 종류를 선택하세요 (미선택 시 분석 제외)"
                        if k is None
                        else all_labels.get(k, str(k)),
                        label_visibility="collapsed",
                    )
                    if new_k != f.get("key"):
                        f["key"] = new_k
                        s["built_sig"] = None
                        _save_ec_to_disk(s)

                    if c3.button("삭제", key=f"ec_del_{name}", use_container_width=True):
                        s["files"].pop(name, None)
                        s["built_sig"] = None
                        _save_ec_to_disk(s)
                        st.rerun()

    have: dict[str, list[str]] = {}
    for name, f in s["files"].items():
        if f.get("key"):
            wp_tag = _sanitize_workplace_label(str(f.get("wp") or ""), R.DEFAULT_WORKPLACE_NAME)
            disp_nm = f"{name} [{wp_tag}]" if wp_tag and wp_tag != R.DEFAULT_WORKPLACE_NAME else name
            have.setdefault(f["key"], []).append(disp_nm)

    trs = []
    for key, label, required, _ in doc_types:
        on = bool(have.get(key))
        pill = "<span class='ec-req-pill'>필수</span>" if required else "<span class='ec-opt-pill'>선택</span>"
        files_str = ", ".join(have.get(key, [])) or "-"
        trs.append(
            f"<tr class='{'on' if on else ''}'>"
            f"<td class='led-cell'><span class='ec-led{' on' if on else ''}'></span></td>"
            f"<td><b>{label}</b> {pill}</td>"
            f"<td class='help'>{doc_help.get(key, '')}</td>"
            f"<td class='fname'>{files_str}</td></tr>"
        )

    for extra_key, extra_files in have.items():
        if extra_key not in base_keys and extra_files:
            extra_lbl = all_labels.get(extra_key, extra_key)
            extra_help = doc_help.get(extra_key, "과거 연도 사원정보 표 생성 및 연속공제·사후관리 검증에 자동 반영됩니다.")
            trs.append(
                f"<tr class='extra'>"
                f"<td class='led-cell'><span class='ec-led on'></span></td>"
                f"<td><b>{extra_lbl}</b> <span class='ec-extra-pill'>➕ 추가 인식됨</span></td>"
                f"<td class='help'>{extra_help}</td>"
                f"<td class='fname'>{', '.join(extra_files)}</td></tr>"
            )

    docs_table_slot.markdown(
        "<table class='ec-docs'><thead><tr>"
        "<th class='led-cell'>상태</th><th>자료명</th><th>검토 용도 및 법령 기준</th><th>업로드된 파일</th>"
        "</tr></thead><tbody>" + "".join(trs) + "</tbody></table>",
        unsafe_allow_html=True,
    )

    st.markdown("<div class='ec-nav-divider'></div>", unsafe_allow_html=True)
    _, right = st.columns([5.8, 1.3])
    if right.button("다음(2단계)", type="primary", use_container_width=True):
        classified: dict[str, list[str]] = {}
        for name, f in s["files"].items():
            if f.get("key"):
                classified.setdefault(f["key"], []).append(name)
        sig = json.dumps(
            sorted((n, f.get("key"), f.get("wp", "")) for n, f in s["files"].items()),
            ensure_ascii=False,
        )
        restored_left = [n for n, f in s["files"].items() if f.get("restored") and not f.get("text")]
        classified_with_text: dict[str, list[str]] = {}
        for name, f in s["files"].items():
            if f.get("key") and f.get("text"):
                classified_with_text.setdefault(f["key"], []).append(name)

        if s["ext_sig"] != sig and restored_left and s.get("ext"):
            if classified_with_text:
                texts_new = _compose_doc_texts_with_wp(s, classified_with_text)
                with st.spinner("⚡ 새로 추가·변경된 서류를 추출하여 기존 복원 데이터에 병합하고 있습니다..."):
                    new_ext = P.extract_all(texts_new, log_tokens_fn, room_key)
                    s["ext"] = _merge_ext_dicts(s.get("ext"), new_ext)
                    msgs = P.check_missing(classified, s["ext"], tax_yr)
                s["ext_sig"] = sig
                s["built_sig"] = None
                s["pending_msgs"] = msgs
                _save_ec_to_disk(s)
            else:
                st.warning(
                    "백업에서 복원한 파일(" + ", ".join(restored_left[:3]) + (" 외" if len(restored_left) > 3 else "") + ")은 "
                    "원문이 없어 다시 읽을 수 없습니다. 지금 읽어둔 사원정보를 그대로 쓰고 다음 단계로 넘어갑니다. "
                    "서류를 새로 읽게 하려면 원본 서류를 추가로 끌어다 놓거나 복원 표시된 파일을 삭제 후 다시 올려주세요."
                )
                s["ext_sig"] = sig
                s["built_sig"] = _current_build_sig(s)
        if s["ext_sig"] != sig:
            texts = _compose_doc_texts_with_wp(s, classified_with_text or classified)
            if texts:
                with st.spinner("⚡ 자체 고속 파서(1순위) 및 하이브리드 Pro/Argon AI(2순위)로 사업자·복수사업장·사원 정보를 추출하고 있습니다..."):
                    s["ext"] = P.extract_all(texts, log_tokens_fn, room_key)
                    msgs = P.check_missing(classified, s["ext"], tax_yr)
            else:
                s["ext"] = {}
                msgs = P.check_missing(classified, None, tax_yr)
                msgs.append("올린 자료가 없어 사업자정보와 사원정보를 모두 직접 입력해야 합니다.")
            s["ext_sig"] = sig
            s["pending_msgs"] = msgs
            _save_ec_to_disk(s)
        msgs = s.get("pending_msgs") or []
        if msgs:
            _dlg_missing(msgs)
        else:
            _enter_step2()
            st.rerun()


def _enter_step2():
    s = _S()
    _ensure_built_for_tax_year(s)
    for k in list(st.session_state.keys()):
        if str(k).startswith("ec_biz_"):
            del st.session_state[k]
    s["step"] = 2
    s["max_step_reached"] = max(int(s.get("max_step_reached") or 1), 2)
    _trigger_scroll_to_top(s)
    _save_ec_to_disk(s)


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


def _block_titles_for_year(year: int, two_line: bool = False) -> tuple[str, str, str]:
    y0 = int(year)
    y1 = y0 - 1
    y2 = y0 - 2
    trunc_mode = "합산 후 절사"
    if two_line:
        return (
            f"3. {y0}년\n세액공제({trunc_mode})",
            f"4. {y1}년\n1차 사후관리",
            f"5. {y2}년\n2차 사후관리",
        )
    return (
        f"3. {y0 % 100:02d}년 세액공제({trunc_mode})",
        f"4. {y1 % 100:02d}년 1차 사후관리",
        f"5. {y2 % 100:02d}년 2차 사후관리",
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
            "_sovr": "1" if yrec.get("상시_override") else "0",
            "_sauto": c["상시_auto"],
        }
        rows.append(row)
    totals = H.year_totals(list(computed.values()), ctx["months_in_year"], year=year)
    totals["has_data"] = len(rows) > 0
    return rows, computed, totals


def _grid_options(
    df: pd.DataFrame,
    totals: dict,
    year: int = 2026,
    show_b2: bool = True,
    show_b3: bool = True,
) -> dict:
    gb = GridOptionsBuilder.from_dataframe(df)
    gb.configure_default_column(
        resizable=True,
        sortable=False,
        filter=False,
        suppressMenu=True,
        suppressHeaderMenuButton=True,
        suppressMovable=True,
        suppressSizeToFit=True,
        editable=JS_LOCKED,
        cellStyle=JS_STYLE,
    )
    gb.configure_grid_options(
        singleClickEdit=True,
        stopEditingWhenCellsLoseFocus=True,
        rowHeight=32,
        headerHeight=32,
        groupHeaderHeight=44,
        suppressMenuHide=True,
        suppressAutoSize=True,
        suppressRowVirtualisation=True,
        suppressColumnVirtualisation=True,
        alwaysShowHorizontalScroll=True,
    )
    go = gb.build()

    def _blk_style(bg_hex: str, fg_hex: str = "#0f172a", bold: bool = True) -> dict:
        return {
            "fontFamily": "Pretendard, Malgun Gothic, sans-serif",
            "fontSize": "12.5px",
            "backgroundColor": bg_hex,
            "color": fg_hex,
            "fontWeight": "800" if bold else "600",
            "textAlign": "center",
            "paddingLeft": "2px",
            "paddingRight": "2px",
            "overflow": "visible",
            "textOverflow": "clip",
        }

    b3_title_2l, b4_title_2l, b5_title_2l = _block_titles_for_year(year, two_line=True)

    grp_pinned_children = [
        {
            "field": "사업장명",
            "headerName": "사업장명",
            "pinned": "left",
            "width": 76,
            "minWidth": 76,
            "suppressSizeToFit": True,
            "editable": True,
            "cellStyle": JS_STYLE_WORKPLACE,
        },
        {
            "field": "성명",
            "headerName": "성명",
            "pinned": "left",
            "width": 78,
            "minWidth": 78,
            "suppressSizeToFit": True,
            "editable": JS_LOCKED,
            "cellStyle": JS_STYLE,
        },
    ]

    grp1_children = [
        {
            "field": "생년월일",
            "headerName": "생년월일",
            "width": 82,
            "minWidth": 82,
            "suppressSizeToFit": True,
            "editable": JS_LOCKED,
            "cellStyle": JS_STYLE_CENTER,
            "valueFormatter": JS_DATE_FMT,
        },
        {
            "field": "입사일",
            "headerName": "입사일",
            "width": 82,
            "minWidth": 82,
            "suppressSizeToFit": True,
            "editable": JS_LOCKED,
            "cellStyle": JS_STYLE_CENTER,
            "valueFormatter": JS_DATE_FMT,
        },
        {
            "field": "퇴사일",
            "headerName": "퇴사일",
            "width": 82,
            "minWidth": 82,
            "suppressSizeToFit": True,
            "editable": JS_LOCKED,
            "cellStyle": JS_STYLE_CENTER,
            "valueFormatter": JS_DATE_FMT,
        },
        {
            "field": "취업연령",
            "headerName": "취업연령",
            "width": 64,
            "minWidth": 64,
            "suppressSizeToFit": True,
            "editable": False,
            "cellStyle": _blk_style("#f8fafc", "#334155", bold=False),
        },
        {
            "field": "고용유형",
            "headerName": "고용유형",
            "width": 108,          # 셀은 컴팩트하게 유지하고 클릭 시 팝업(260px)으로 전체 표시
            "minWidth": 108,
            "suppressSizeToFit": True,
            "editable": JsCode("function(p){ return !p.node.rowPinned; }"),
            "cellStyle": JS_STYLE,
            "cellEditor": "agSelectCellEditor",
            "cellEditorPopup": True,
            "cellEditorParams": {"values": R.EMP_TYPES, "valueListMaxWidth": 260},
        },
        {
            "field": "제외사유",
            "headerName": "제외사유",
            "width": 132,
            "minWidth": 132,
            "suppressSizeToFit": True,
            "editable": JS_LOCKED,
            "cellStyle": JS_STYLE_EXCL,
            "cellEditor": "agSelectCellEditor",
            "cellEditorParams": {"values": R.EXCL_REASONS},
        },
        {
            "field": "병역개월",
            "headerName": "병역(월)",
            "width": 64,
            "minWidth": 64,
            "suppressSizeToFit": True,
            "editable": JS_LOCKED,
            "cellStyle": JS_STYLE_CENTER,
            "cellEditor": "agNumberCellEditor",
            "cellEditorParams": {"min": 0, "max": R.MILITARY_MAX_MONTHS, "precision": 0},
        },
        {
            "field": "청년등",
            "headerName": "청년등 구분",
            "width": 126,
            "minWidth": 126,
            "suppressSizeToFit": True,
            "editable": JS_LOCKED,
            "cellStyle": JS_STYLE_YOUTH,
            "cellEditor": "agSelectCellEditor",
            "cellEditorParams": JS_YOUTH_PARAMS,
        },
        {
            "field": "상시",
            "headerName": "상시",
            "width": 52,
            "minWidth": 52,
            "suppressSizeToFit": True,
            "editable": True,
            "cellStyle": JS_STYLE_REGULAR,
            "cellEditor": "agSelectCellEditor",
            "cellEditorParams": {"values": ["O", "X"]},
        },
    ]

    grp2_children = []
    for i, c in enumerate(MONTH_COLS, start=1):
        grp2_children.append(
            {
                "field": c,
                "headerName": f"{i}월",
                "width": 44,       # 클릭 시 팝업(90px)으로 표시되므로 셀 폭은 한 화면 수납을 위해 슬림화
                "minWidth": 44,
                "suppressSizeToFit": True,
                "suppressMenu": True,
                "suppressHeaderMenuButton": True,
                "editable": JS_MONTH_EDITABLE,
                "cellStyle": JS_MONTH_STYLE,
                "cellEditor": "agSelectCellEditor",
                "cellEditorPopup": True,
                "cellEditorParams": {"values": R.MONTH_CHOICES, "valueListMaxWidth": 90},
                "valueFormatter": JS_NUM_FMT,
            }
        )
    grp2_children.append(
        {
            "field": "합계",
            "headerName": "월합계",
            "width": 58,
            "minWidth": 58,
            "suppressSizeToFit": True,
            "editable": False,
            "valueFormatter": JS_NUM_FMT,
            "cellStyle": _blk_style("#f1f5f9", "#0f172a"),
        }
    )

    grp3_children = [
        {"field": "b1_yth", "headerName": "청년등", "width": 60, "minWidth": 60, "suppressSizeToFit": True, "editable": False, "valueFormatter": JS_DEC2_FMT, "cellStyle": _blk_style("#f0fdf4", "#15803d")},
        {"field": "b1_gen", "headerName": "청년외", "width": 60, "minWidth": 60, "suppressSizeToFit": True, "editable": False, "valueFormatter": JS_DEC2_FMT, "cellStyle": _blk_style("#f8fafc", "#334155")},
        {"field": "b1_reg", "headerName": "상시", "width": 60, "minWidth": 60, "suppressSizeToFit": True, "editable": False, "valueFormatter": JS_DEC2_FMT, "cellStyle": _blk_style("#e0f2fe", "#0369a1")},
    ]

    grp4_children = [
        {"field": "b2_yth", "headerName": "청년등", "width": 60, "minWidth": 60, "suppressSizeToFit": True, "editable": False, "valueFormatter": JS_DEC2_FMT, "cellStyle": _blk_style("#eff6ff", "#1d4ed8")},
        {"field": "b2_gen", "headerName": "청년외", "width": 60, "minWidth": 60, "suppressSizeToFit": True, "editable": False, "valueFormatter": JS_DEC2_FMT, "cellStyle": _blk_style("#f8fafc", "#475569")},
        {"field": "b2_reg", "headerName": "상시", "width": 60, "minWidth": 60, "suppressSizeToFit": True, "editable": False, "valueFormatter": JS_DEC2_FMT, "cellStyle": _blk_style("#eff6ff", "#1e3a8a")},
    ]

    grp5_children = [
        {"field": "b3_yth", "headerName": "청년등", "width": 60, "minWidth": 60, "suppressSizeToFit": True, "editable": False, "valueFormatter": JS_DEC2_FMT, "cellStyle": _blk_style("#f5f3ff", "#6d28d9")},
        {"field": "b3_gen", "headerName": "청년외", "width": 60, "minWidth": 60, "suppressSizeToFit": True, "editable": False, "valueFormatter": JS_DEC2_FMT, "cellStyle": _blk_style("#f8fafc", "#475569")},
        {"field": "b3_reg", "headerName": "상시", "width": 60, "minWidth": 60, "suppressSizeToFit": True, "editable": False, "valueFormatter": JS_DEC2_FMT, "cellStyle": _blk_style("#f5f3ff", "#4c1d95")},
    ]

    extra_hidden_fields = {"pid", "b4_yth", "b4_gen", "b4_reg"}
    if not show_b2:
        extra_hidden_fields.update({"b2_yth", "b2_gen", "b2_reg"})
    if not show_b3:
        extra_hidden_fields.update({"b3_yth", "b3_gen", "b3_reg"})

    hidden_cols = [
        {"field": c, "hide": True, "editable": False}
        for c in df.columns
        if c.startswith("_") or c in extra_hidden_fields
    ]

    col_defs = [
        {"headerName": "사업장 · 성명", "children": grp_pinned_children},
        {"headerName": "1. 사원 계산기 (생년월일 · 입퇴사 · 상시/청년 판정)", "children": grp1_children},
        {"headerName": "2. 매월 말 현재 상시근로자 수 (1월 ~ 12월)", "children": grp2_children},
        {"headerName": b3_title_2l, "children": grp3_children},
    ]
    if show_b2:
        col_defs.append({"headerName": b4_title_2l, "children": grp4_children})
    if show_b3:
        col_defs.append({"headerName": b5_title_2l, "children": grp5_children})
    col_defs.extend(hidden_cols)
    go["columnDefs"] = col_defs

    n = totals["months_in_year"]
    trunc_mode = "합산 후 절사"
    pinned = [
        {
            "사업장명": "합산합계",
            "성명": "상시근로자",
            "생년월일": "",
            "고용유형": f"÷ {n}개월 절사",
            **{MONTH_COLS[i]: totals["월별_상시"][i] for i in range(12)},
            "합계": totals["상시_합계"],
            "b1_yth": totals["b1_yth"],
            "b1_gen": totals["b1_gen"],
            "b1_reg": totals["b1_reg"],
            "b2_yth": totals["b2_yth"],
            "b2_gen": totals["b2_gen"],
            "b2_reg": totals["b2_reg"],
            "b3_yth": totals["b3_yth"],
            "b3_gen": totals["b3_gen"],
            "b3_reg": totals["b3_reg"],
            "b4_yth": totals["b4_yth"],
            "b4_gen": totals["b4_gen"],
            "b4_reg": totals["b4_reg"],
        },
        {
            "사업장명": "합산합계",
            "성명": "청년등",
            "생년월일": "",
            "고용유형": "각 코호트 기준",
            **{MONTH_COLS[i]: totals["월별_청년등"][i] for i in range(12)},
            "합계": totals["청년등_합계"],
            "b1_yth": totals["b1_yth"],
            "b1_gen": None,
            "b1_reg": None,
            "b2_yth": totals["b2_yth"],
            "b2_gen": None,
            "b2_reg": None,
            "b3_yth": totals["b3_yth"],
            "b3_gen": None,
            "b3_reg": None,
            "b4_yth": totals["b4_yth"],
            "b4_gen": None,
            "b4_reg": None,
        },
        {
            "사업장명": "합산합계",
            "성명": "청년등 외",
            "생년월일": "",
            "고용유형": "상시 - 청년등",
            **{MONTH_COLS[i]: totals["월별_청년외"][i] for i in range(12)},
            "합계": totals["청년외_합계"],
            "b1_yth": None,
            "b1_gen": totals["b1_gen"],
            "b1_reg": None,
            "b2_yth": None,
            "b2_gen": totals["b2_gen"],
            "b2_reg": None,
            "b3_yth": None,
            "b3_gen": totals["b3_gen"],
            "b3_reg": None,
            "b4_yth": None,
            "b4_gen": totals["b4_gen"],
            "b4_reg": None,
        },
    ]
    go["pinnedBottomRowData"] = pinned
    return go


def _norm(v) -> str:
    if v is None:
        return ""
    try:
        if pd.isna(v):
            return ""
    except (TypeError, ValueError):
        pass
    return str(v).strip()


def _apply_changes(s: dict, year: int, sent: list[dict], back: pd.DataFrame) -> bool:
    if back is None or back.empty or "pid" not in back.columns:
        return False
    before = {r["pid"]: r for r in sent}
    changed = False
    for _, nr in back.iterrows():
        pid = nr.get("pid")
        old = before.get(pid)
        if old is None or pid not in s["people"]:
            continue
        p, yrec = s["people"][pid], s["year_recs"][year][pid]
        us = yrec.setdefault("_user_set", [])

        nv_wp = _norm(nr.get("사업장명"))
        if nv_wp != _norm(old.get("사업장명")):
            p["사업장명"] = nv_wp
            p.setdefault("연도별_사업장명", {})[str(year)] = nv_wp
            changed = True

        for f in ("성명", "생년월일", "입사일", "퇴사일"):
            nv = _norm(nr.get(f))
            if nv != _norm(old.get(f)):
                d = H.parse_date(nv) if f != "성명" else None
                val_to_save = nv if f == "성명" else (d.isoformat() if d else nv)
                p[f] = val_to_save
                if f == "퇴사일":
                    p.setdefault("연도별_퇴사일", {})[str(year)] = val_to_save
                changed = True

        nv = _norm(nr.get("병역개월"))
        if nv != _norm(old.get("병역개월")) and not _same_num(nv or "0", _norm(old.get("병역개월")) or "0"):
            try:
                months = int(float(nv or 0))
            except ValueError:
                months = 0
            p["병역개월"] = max(0, min(months, R.MILITARY_MAX_MONTHS))
            changed = True

        nv = _norm(nr.get("고용유형"))
        if nv and nv != _norm(old.get("고용유형")):
            yrec["고용유형"] = nv
            yrec["_user_set"] = [x for x in us if x not in ("제외사유", "청년등")] + ["고용유형"]
            us = yrec["_user_set"]
            if nv not in R.EMP_AUTO_EXCLUDE and float(old.get("합계") or 0.0) == 0.0:
                yrec["월_override"] = {}
            changed = True

        nv = _norm(nr.get("제외사유"))
        if nv and nv != _norm(old.get("제외사유")):
            yrec["제외사유"] = nv
            yrec["_user_set"] = [x for x in us if x != "청년등"] + (["제외사유"] if "제외사유" not in us else [])
            us = yrec["_user_set"]
            changed = True

        nv = _norm(nr.get("청년등"))
        if nv and nv != _norm(old.get("청년등")):
            yrec["청년등"] = nv
            if "청년등" not in us:
                us.append("청년등")
            changed = True

        nv = _norm(nr.get("상시"))
        if nv in ("O", "X") and nv != _norm(old.get("상시")):
            if nv == old.get("_sauto"):
                yrec["상시_override"] = ""
            else:
                yrec["상시_override"] = nv
                yrec["_unlocked"] = True
            changed = True

        mo = yrec.setdefault("월_override", {})
        for i, c in enumerate(MONTH_COLS, start=1):
            nv, ov = _norm(nr.get(c)), _norm(old.get(c))
            if nv == ov or (nv and ov and _same_num(nv, ov)):
                continue
            if nv == R.MONTH_AUTO or nv == "":
                mo.pop(str(i), None)
            else:
                try:
                    mo[str(i)] = float(nv)
                except ValueError:
                    continue
            changed = True
    return changed


def _same_num(a: str, b: str) -> bool:
    try:
        return abs(float(a) - float(b)) < 1e-9
    except ValueError:
        return False


def _year_role_description(s: dict, tax_year: int, year: int) -> str:
    b3_title, b4_title, b5_title = _block_titles_for_year(year, two_line=False)
    has_y1 = _has_year_data(s, year - 1)
    has_y2 = _has_year_data(s, year - 2)
    active_parts = [b3_title]
    if has_y1:
        active_parts.append(b4_title)
    if has_y2:
        active_parts.append(b5_title)
    omitted = []
    if not has_y1:
        omitted.append(f"{(year-1)%100:02d}년 1차 사후관리")
    if not has_y2:
        omitted.append(f"{(year-2)%100:02d}년 2차 사후관리")
    omit_note = f" (미업로드 생략: {', '.join(omitted)})" if omitted else ""
    prefix = "당해 귀속" if year == tax_year else ("직전 귀속" if year == tax_year - 1 else "전전 귀속")
    return f"{prefix} [{ ' · '.join(active_parts) }]{omit_note}"


def _render_year(s: dict, year: int, room_key: str) -> tuple[dict, dict]:
    rows, computed, totals = _build_year_rows(s, year)
    tax_year = int(s["tax_year"])
    role_desc = _year_role_description(s, tax_year, year)
    last_m = H.detect_last_paid_month(s.get("people") or {}, year)
    mid_yr_badge = (
        f" &nbsp;·&nbsp; <span style='color:#0369a1;font-weight:700;'>⚡ {last_m}월 가결산 ({last_m+1}~12월 {'연말재직 자동가정' if s.get('assume_year_end', True) else '미도래 0 처리'})</span>"
        if last_m < 12
        else ""
    )

    corp_nm = (s.get("biz", {}).get("상호") or "상호미입력").strip()

    # ── 연도별 상시근로자 명세 헤더 라인 + 맨 오른쪽 붉은색 [📕 PDF 다운] 버튼 ──
    c_hdr, c_pdf = st.columns([6.15, 0.85])
    with c_hdr:
        st.markdown(
            f"<div class='ec-year-header'>"
            f"<span class='ec-year-title'>📅 {year}년 귀속 상시근로자 명세 ({len(rows)}명)</span>"
            f"<span class='ec-year-sub'>{role_desc}{mid_yr_badge}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
    with c_pdf:
        with st.container(key=f"ec_btn_pdf_yr_{year}"):
            st.download_button(
                "📕 PDF 다운",
                data=_build_schedule_pdf_bytes(s, [year], include_summary=False),
                file_name=f"{corp_nm}_{year}년귀속_상시근로자명세.pdf",
                mime="application/pdf",
                use_container_width=True,
                key=f"dl_pdf_yr_{year}",
                help=f"{year}년 귀속 상시근로자 명세 및 사후관리 판정표(A4 가로 PDF)를 다운로드합니다.",
            )

    if not rows:
        st.info(f"{year}년에 근무한 근로자가 없습니다. {year}년 원천징수부를 올렸는지 확인하거나 아래 [➕ 사원 추가]로 입력하세요.")
        return computed, totals

    df = pd.DataFrame(rows)
    for _mc in MONTH_COLS:
        if _mc in df.columns:
            df[_mc] = df[_mc].apply(lambda v: "" if (v is None or pd.isna(v) or v == "") else f"{float(v):g}")
    s["last_sent"][year] = rows
    ver = s["grid_ver"].get(year, 0)
    show_all_4 = bool(s.get("show_all_4_blocks", True))
    force_empty = bool(s.get("show_empty_pm_blocks", False))
    has_y1 = _has_year_data(s, year - 1)
    has_y2 = _has_year_data(s, year - 2)
    show_b2 = show_all_4 and (has_y1 or force_empty)
    show_b3 = show_all_4 and (has_y2 or force_empty)

    custom_ag_css = {
        ".ag-header": {"background-color": "#1e293b !important", "color": "#ffffff !important"},
        ".ag-header-group-cell": {
            "background-color": "#0f172a !important",
            "color": "#f8fafc !important",
            "font-weight": "800 !important",
            "font-family": "'Pretendard', 'Malgun Gothic', sans-serif !important",
            "font-size": "12.6px !important",
            "border-right": "1px solid #475569 !important",
            "justify-content": "center !important",
            "padding-left": "3px !important",
            "padding-right": "3px !important",
        },
        ".ag-header-group-cell-label": {
            "justify-content": "center !important",
            "align-items": "center !important",
            "text-align": "center !important",
            "width": "100% !important",
            "overflow": "visible !important",
            "text-overflow": "clip !important",
        },
        ".ag-header-group-text": {
            "white-space": "pre-line !important",
            "text-align": "center !important",
            "line-height": "1.25 !important",
            "overflow": "visible !important",
            "text-overflow": "clip !important",
            "font-weight": "800 !important",
            "color": "#f8fafc !important",
        },
        ".ag-header-cell": {
            "padding-left": "2px !important",
            "padding-right": "2px !important",
            "border-right": "1px solid #334155 !important",
        },
        ".ag-header-cell-label": {
            "justify-content": "center !important",
            "overflow": "visible !important",
            "text-overflow": "clip !important",
        },
        ".ag-header-cell-text": {
            "color": "#ffffff !important",
            "font-weight": "700 !important",
            "font-family": "'Pretendard', 'Malgun Gothic', sans-serif !important",
            "font-size": "12.4px !important",
            "overflow": "visible !important",
            "text-overflow": "clip !important",
            "white-space": "nowrap !important",
        },
        ".ag-header-cell-menu-button, .ag-header-icon": {
            "display": "none !important",
        },
        ".ag-cell": {
            "padding-left": "3px !important",
            "padding-right": "3px !important",
            "overflow": "visible !important",
            "text-overflow": "clip !important",
        },
        ".ag-root-wrapper": {"border-radius": "8px !important", "border": "1px solid #cbd5e1 !important"},
    }
    resp = AgGrid(
        df,
        gridOptions=_grid_options(df, totals, year=year, show_b2=show_b2, show_b3=show_b3),
        update_mode=GridUpdateMode.VALUE_CHANGED,
        allow_unsafe_jscode=True,
        theme="balham",
        custom_css=custom_ag_css,
        key=f"ec_grid_{year}_{ver}_{int(show_b2)}_{int(show_b3)}_{int(s.get('assume_year_end', True))}_{int(s.get('include_unpaid_hire_month', True))}",
        height=min(720, 128 + 32 * (len(rows) + 3)),
        fit_columns_on_grid_load=False,
    )
    back = getattr(resp, "data", None)
    if back is None:
        try:
            back = resp["data"]
        except Exception:
            back = None
    if isinstance(back, pd.DataFrame) and _apply_changes(s, year, rows, back):
        for y in _all_possible_years(s):
            s["grid_ver"][y] = s["grid_ver"].get(y, 0) + 1
        _save_ec_to_disk(s)
        st.rerun()

    b3_title, b4_title, b5_title = _block_titles_for_year(year, two_line=False)
    kpi_chips = [
        f"<div class='ec-kpi-chip b3'>"
        f"<span class='kpi-tag'>👥 {b3_title}</span>"
        f"<span class='kpi-main'>상시 {totals['b1_reg']:.2f}명</span>"
        f"<span class='kpi-sub'>(청년등 <b>{totals['b1_yth']:.2f}</b> · 청년외 <b>{totals['b1_gen']:.2f}</b>)</span>"
        f"</div>"
    ]
    if show_b2:
        kpi_chips.append(
            f"<div class='ec-kpi-chip b4'>"
            f"<span class='kpi-tag'>🔄 {b4_title}</span>"
            f"<span class='kpi-main'>상시 {totals['b2_reg']:.2f}명</span>"
            f"<span class='kpi-sub'>(청년등 <b>{totals['b2_yth']:.2f}</b> · 청년외 <b>{totals['b2_gen']:.2f}</b>)</span>"
            f"</div>"
        )
    if show_b3:
        kpi_chips.append(
            f"<div class='ec-kpi-chip b5'>"
            f"<span class='kpi-tag'>🛡️ {b5_title}</span>"
            f"<span class='kpi-main'>상시 {totals['b3_reg']:.2f}명</span>"
            f"<span class='kpi-sub'>(청년등 <b>{totals['b3_yth']:.2f}</b> · 청년외 <b>{totals['b3_gen']:.2f}</b>)</span>"
            f"</div>"
        )
    trunc_mode = "합산 후 절사"
    st.markdown(
        f"<div class='ec-kpi-bar'>"
        f"<div class='ec-kpi-items'>{''.join(kpi_chips)}</div>"
        f"<span class='ec-kpi-total-pill'>총인원(연인원) <b>{totals['상시_합계']:g}명</b> ÷ {totals['months_in_year']}개월 ({trunc_mode})</span>"
        f"</div>",
        unsafe_allow_html=True,
    )
    return computed, totals


def _render_prev_filing_summary_card(s: dict, shown_years: list[int]):
    tax_yr = int(s["tax_year"])
    t2_year = tax_yr - 2
    if t2_year in shown_years:
        return

    ps = s.setdefault("prev_summary", {})
    y_entry = ps.setdefault(
        str(t2_year),
        {
            "상시_총인원": None,
            "청년등_총인원": None,
            "상시": None,
            "청년등": None,
            "청년등_증가": None,
            "청년등외_증가": None,
            "공제세액": None,
            "2차_공제세액": None,
            "이월세액": None,
            "기추징세액": None,
        },
    )
    has_prev_doc = bool(((s.get("ext") or {}).get("prev_filing") or {}).get("연도별"))

    with st.expander(
        f"📋 {t2_year}년 귀속분(2차 사후관리 대상) 인원 확인 — 현재 {t2_year}년 원천징수부 미첨부로 표 생략됨 (기신고 숫자로 간편 입력 가능)",
        expanded=has_prev_doc,
    ):
        st.caption(
            f"💡 **{t2_year}년 귀속분 2차 사후관리(3차년도 연속공제 또는 추가납부세액)** 및 **{tax_yr-1}년 고용증가 인원 검증**을 위해 "
            f"{t2_year}년 기신고 상시·청년등 인원을 입력하거나 아래 버튼으로 {t2_year}년 사원표를 직접 열 수 있습니다."
        )
        c1, c2, c3 = st.columns([1.8, 1.8, 2.4])
        with c1:
            reg_val = st.number_input(
                f"{t2_year}년 기신고 전체 상시근로자 수",
                min_value=0.0,
                step=0.01,
                format="%.2f",
                value=None if y_entry.get("상시") is None else float(y_entry.get("상시")),
                placeholder="기신고 숫자",
                key=f"prev_sum_reg_{t2_year}",
            )
            y_entry["상시"] = reg_val
        with c2:
            yth_val = st.number_input(
                f"{t2_year}년 기신고 청년등 상시근로자 수",
                min_value=0.0,
                step=0.01,
                format="%.2f",
                value=None if y_entry.get("청년등") is None else float(y_entry.get("청년등")),
                placeholder="기신고 숫자",
                key=f"prev_sum_yth_{t2_year}",
            )
            y_entry["청년등"] = yth_val
        with c3:
            st.write("")
            if st.button(f"➕ {t2_year}년 사원정보 표 직접 열어서 계산하기", use_container_width=True, key=f"btn_open_yr_{t2_year}"):
                extra = s.setdefault("manual_extra_years", [])
                if t2_year not in extra:
                    extra.append(t2_year)
                for pid in s["people"]:
                    s["year_recs"].setdefault(t2_year, {}).setdefault(pid, P.new_year_rec())
                _save_ec_to_disk(s)
                st.rerun()


def _page_employees(room_key: str, log_tokens_fn=None):
    s = _S()
    _ensure_built_for_tax_year(s)
    tax_yr = int(s["tax_year"])
    shown_years = _years(s)

    # ── 상단 타이틀 + 슬림 옵션 바 (첫 번째 사원표가 화면 상단에서 즉시 시작되도록 최적화) ──
    c_ttl, c_opt_pop = st.columns([4.2, 1.8])
    with c_ttl:
        st.markdown(f"### 👥 2. 사원정보 및 상시근로자 판정 ({tax_yr}년 귀속)")
    with c_opt_pop:
        if len(s.get("people") or {}) >= 35 and not s.get("use_year_tabs", False):
            st.caption("💡 인원수가 많을 때는 아래 **『연도별 탭 보기』**를 켜면 브라우저가 훨씬 빠릅니다.")

    with st.container(border=True):
        co1, co2, co3, co4 = st.columns([1.5, 1.5, 1.5, 1.5])
        with co1:
            assume_on = st.toggle(
                "⏩ 미도래 월 연말재직 가정(1 채움)",
                value=bool(s.get("assume_year_end", True)),
                key="ec_toggle_assume_ye",
                help="기중(예: 9월 가결산) 원천징수부 업로드 시 미도래 월(10~12월)을 연말까지 재직 가정(1 자동 채움 · 하늘색 표시)합니다.",
            )
            if assume_on != s.get("assume_year_end", True):
                s["assume_year_end"] = assume_on
                _save_ec_to_disk(s)
                st.rerun()
        with co2:
            hm_on = st.toggle(
                "📅 입사월 무급 시 익월지급 산입(1)",
                value=bool(s.get("include_unpaid_hire_month", True)),
                key="ec_toggle_hire_month_nopay",
                help="입사월 급여가 다음 달에 지급되어 당월 원천징수부 급여가 0원인 경우에도 재직(1)으로 산입하고 살구색으로 표시합니다.",
            )
            if hm_on != s.get("include_unpaid_hire_month", True):
                s["include_unpaid_hire_month"] = hm_on
                _save_ec_to_disk(s)
                st.rerun()
        with co3:
            show_4 = st.toggle(
                "📊 우측 4·5번 사후관리 열 표시",
                value=bool(s.get("show_all_4_blocks", True)),
                key="ec_toggle_4blocks",
                help="우측 4번(1차 사후관리)·5번(2차 사후관리) 블록을 함께 표시합니다.",
            )
            if show_4 != s.get("show_all_4_blocks", True):
                s["show_all_4_blocks"] = show_4
                _save_ec_to_disk(s)
                st.rerun()
        with co4:
            use_tabs = st.toggle(
                "🗂️ 연도별 탭으로 나누어 보기",
                value=bool(s.get("use_year_tabs", False)),
                key="ec_toggle_year_tabs",
                help="기본은 전 연도 연속 펼쳐보기이며, 인원이 많을 때 탭 보기로 전환하면 한 연도씩 쾌적하게 볼 수 있습니다.",
            )
            if use_tabs != s.get("use_year_tabs", False):
                s["use_year_tabs"] = use_tabs
                s["_tabs_user_touched"] = True
                _save_ec_to_disk(s)
                st.rerun()

    st.markdown(
        "<div class='ec-legend'>"
        "<span style='background:#e2e8f0;color:#0f172a;border:1px solid #cbd5e1'>🔒 서류 확인값 (상시 O/X 전환 시 잠금해제)</span>"
        "<span style='background:#ffffff;color:#1d4ed8;border:1px solid #93c5fd'>✏️ 입력·선택 가능</span>"
        "<span style='background:#dbeafe;color:#1e40af;border:1px solid #93c5fd'>🏢 사업장 간 전출입·승계 합산(A→B)</span>"
        "<span style='background:#dcfce7;color:#14532d;border:1px solid #86efac'>🌱 청년등 인정 월</span>"
        "<span style='background:#e0f2fe;color:#0369a1;border:1px solid #7dd3fc'>🟦 미도래 월 연말재직 가정(자동 1)</span>"
        "<span style='background:#ffedd5;color:#c2410c;border:1px solid #fdba74'>🟧 급여 0원 월 (입사월 익월지급 산입 / 기중 무급 0 제외)</span>"
        "<span style='background:#ffffff;color:#0f172a;border:2px solid #f59e0b'>🔧 직접 수정한 값</span>"
        "</div>",
        unsafe_allow_html=True,
    )

    if not s["people"]:
        st.info("읽어온 근로자가 없습니다. 아래 [➕ 사원 추가] 버튼으로 직접 입력하시거나 [< 이전]을 눌러 원천징수부를 업로드하세요.")

    computed_all, totals_all, ctx_all = {}, {}, {}
    if s.get("use_year_tabs", False) and len(shown_years) > 1:
        tab_objs = st.tabs([f"📅 {y}년 귀속 명세" for y in shown_years])
        for tab_o, y in zip(tab_objs, shown_years):
            with tab_o:
                computed_all[y], totals_all[y] = _render_year(s, y, room_key)
                ctx_all[y] = _ctx(s, y)
    else:
        for y in shown_years:
            computed_all[y], totals_all[y] = _render_year(s, y, room_key)
            ctx_all[y] = _ctx(s, y)

    _render_prev_filing_summary_card(s, shown_years)

    if tax_yr in totals_all and (tax_yr - 1) in totals_all:
        cur_t = totals_all[tax_yr]
        adj_prv, suc_reg, ded_reg = _adjusted_prev_totals(s, totals_all[tax_yr - 1])
        eff_prv_reg = round(adj_prv["상시_평균"], 2)
        eff_prv_yth = round(adj_prv["청년등_평균"], 2)
        eff_prv_gen = round(max(0.0, eff_prv_reg - eff_prv_yth), 2)
        inc = H.calc_increase_with_cap(
            cur_t["상시_평균"],
            cur_t["청년등_평균"],
            cur_t["청년외_평균"],
            eff_prv_reg,
            eff_prv_yth,
            eff_prv_gen,
        )
        cap_note = ""
        if inc.get("청년등_한도적용전", 0) > inc["청년등_증가"] or inc.get("청년등외_한도적용전", 0) > inc["청년등외_증가"]:
            cap_note = " &nbsp;·&nbsp; ⚠️ <b>전체 상시근로자 증가인원 한도(Cap) 자동 적용됨</b>"
        suc_note = (f" (포괄양수·승계 직전인원 +{suc_reg:.2f}명 반영)" if suc_reg > 0 else "") + \
                   (f" (기중양도 승계 근로자 직전인원 −{ded_reg:.2f}명 차감)" if ded_reg > 0 else "")
        st.markdown(
            f"<div class='ec-law-banner'>"
            f"📊 <b>[{tax_yr}년 vs {tax_yr-1}년 신규공제 고용증가 요약{suc_note}]</b> &nbsp; "
            f"전체 상시 증가: <b>+{inc['전체_증가']:.2f}명</b> &nbsp;|&nbsp; "
            f"청년등 인정 증가: <b>+{inc['청년등_증가']:.2f}명</b> &nbsp;|&nbsp; "
            f"청년등 외 인정 증가: <b>+{inc['청년등외_증가']:.2f}명</b>{cap_note} &nbsp;&nbsp; "
            f"<span style='color:#1d4ed8'>({(tax_yr-1)%100:02d}년 1차 사후관리 청년등: <b>{cur_t['b2_yth']:.2f}명</b>"
            + (f" / {(tax_yr-2)%100:02d}년 2차 사후관리 청년등: <b>{cur_t['b3_yth']:.2f}명</b>" if _has_year_data(s, tax_yr - 2) else "")
            + ")</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

    c_add, _ = st.columns([1.3, 5.8])
    if c_add.button("➕ 사원 추가", use_container_width=True):
        seq = int(s.get("next_pid_seq", 1))
        s["next_pid_seq"] = seq + 1
        pid = f"manual_{seq}_{uuid.uuid4().hex[:6]}"
        s["people"][pid] = {
            "pid": pid,
            "사업장명": _default_workplace_label(s),
            "연도별_사업장명": {},
            "성명": f"신규사원{seq}",
            "생년월일": "",
            "입사일": "",
            "퇴사일": "",
            "계약체결일": "",
            "병역개월": 0,
            "월급여": {},
            "연도별_퇴사일": {},
            "_confirmed": [],
        }
        for y in _all_possible_years(s):
            s["year_recs"].setdefault(y, {})[pid] = P.new_year_rec()
            s["grid_ver"][y] = s["grid_ver"].get(y, 0) + 1
        _save_ec_to_disk(s)
        st.rerun()

    # ── 하단 네비게이션 바: [< 이전] ... [📕 전체 PDF 다운] [🔍 오류 검토] [다음(3단계)] ──
    corp_nm = (s.get("biz", {}).get("상호") or "상호미입력").strip()
    st.markdown("<div class='ec-nav-divider'></div>", unsafe_allow_html=True)
    c_prev, _, c_all_pdf, c_rev, c_next = st.columns([1.2, 2.3, 1.25, 1.15, 1.3])
    if c_prev.button("< 이전", use_container_width=True):
        s["step"] = 1
        _trigger_scroll_to_top(s)
        _save_ec_to_disk(s)
        st.rerun()

    with c_all_pdf:
        with st.container(key="ec_btn_pdf_all_wrap"):
            st.download_button(
                "📕 전체 PDF 다운",
                data=_build_schedule_pdf_bytes(s, shown_years, include_summary=True),
                file_name=f"{corp_nm}_{tax_yr}년귀속_전체연도_상시근로자명세.pdf",
                mime="application/pdf",
                use_container_width=True,
                key="dl_pdf_all_years",
                help=f"화면에 표시된 전체 연도({', '.join(str(y)+'년' for y in shown_years)})의 상시근로자 명세 및 고용증가 요약을 한 파일의 PDF로 다운로드합니다.",
            )

    if c_rev.button("🔍 오류 검토", use_container_width=True):
        prev = ((s.get("ext") or {}).get("prev_filing") or {}).get("연도별")
        review_items = H.review(
            s["people"],
            s["year_recs"],
            shown_years,
            ctx_all,
            computed_all,
            prev,
            sub_biz_list=s.get("sub_biz_list"),
        )
        audit_payload = {
            "귀속연도": tax_yr,
            "사업자정보": s.get("biz"),
            "합산사업장": s.get("sub_biz_list"),
            "연도별_요약": {
                str(y): {
                    "상시_평균": t.get("b1_reg"),
                    "청년등_평균": t.get("b1_yth"),
                    "1차사후_청년등": t.get("b2_yth"),
                    "2차사후_청년등": t.get("b3_yth"),
                }
                for y, t in totals_all.items()
            },
            "결정론적_검토항목": [{"구분": lv, "내용": msg} for lv, msg in review_items],
        }
        _dlg_review(review_items, audit_payload=audit_payload, log_tokens_fn=log_tokens_fn, room_key=room_key)

    if c_next.button("다음(3단계)", type="primary", use_container_width=True):
        s["totals_snapshot"] = totals_all
        s["step"] = 3
        s["max_step_reached"] = max(int(s.get("max_step_reached") or 1), 3)
        _trigger_scroll_to_top(s)
        _save_ec_to_disk(s)
        st.rerun()


# ══════════════════════════════════════════════════════════════════
# 6. 3단계: 공제액 · 1·2차 사후관리(추가납부세액) 종합 계산
# ══════════════════════════════════════════════════════════════════
def _ensure_totals_snapshot(s: dict) -> dict[int, dict]:
    _ensure_built_for_tax_year(s)
    totals_all = {}
    for y in _all_possible_years(s):
        _, _, t = _build_year_rows(s, y)
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


def _render_pm_basis_selector_right(s: dict, widget_key: str) -> str:
    cur_basis = s.get("pm_basis", R.PM_BASIS_FILED)
    if cur_basis not in (R.PM_BASIS_FILED, R.PM_BASIS_RECALC):
        cur_basis = R.PM_BASIS_FILED
        s["pm_basis"] = cur_basis

    opts = [R.PM_BASIS_RECALC, R.PM_BASIS_FILED]
    fmt_map = {
        R.PM_BASIS_RECALC: "⚖️ 2단계 사원표(세법원칙) 기준 계산",
        R.PM_BASIS_FILED: "📋 기신고 서식 숫자 기준 계산",
    }

    seg_fn = getattr(st, "segmented_control", None)
    if callable(seg_fn):
        try:
            chosen = seg_fn(
                "사후관리 및 공제액 계산 기준 선택",
                options=opts,
                default=cur_basis,
                format_func=lambda k: fmt_map.get(k, k),
                label_visibility="collapsed",
                key=widget_key,
            )
            if chosen in opts and chosen != cur_basis:
                s["pm_basis"] = chosen
                s["_pm_basis_user_touched"] = True
                _save_ec_to_disk(s)
                st.rerun()
            return s["pm_basis"]
        except Exception:
            pass

    chosen_r = st.radio(
        "사후관리 및 공제액 계산 기준 선택",
        options=opts,
        index=opts.index(cur_basis),
        format_func=lambda k: fmt_map.get(k, k),
        horizontal=True,
        label_visibility="collapsed",
        key=widget_key,
    )
    if chosen_r != cur_basis:
        s["pm_basis"] = chosen_r
        s["_pm_basis_user_touched"] = True
        _save_ec_to_disk(s)
        st.rerun()
    return s["pm_basis"]


def _fmt_matrix_won(credit_won: int | float | None, clawback_won: int | float | None = 0) -> str:
    """
    상단 4개년 요약 매트릭스 셀 포맷터:
    - 공제세액(양수)과 추가납부세액(음수, 붉은 글씨 '-')을 구분하여 HTML 문자열로 반환
    - 동일 차수에 연속공제와 추가납부가 동시에 발생하는 경우(예: 청년 감소 단가차액 추징 + 부분 연속공제)
      [공제] / [추징] 미니 배지를 함께 표시하여 시인성을 높입니다.
    """
    cr = int(round(float(credit_won or 0)))
    cl = int(round(float(clawback_won or 0)))
    if cr > 0 and cl > 0:
        return (
            f"<div class='ec-mat-dual'><span class='ec-cell-tag pos'>공제</span><span class='ec-pos-val'>{cr:,}</span></div>"
            f"<div class='ec-mat-dual'><span class='ec-cell-tag neg'>추징</span><span class='ec-neg-val'>-{cl:,}</span></div>"
        )
    if cl > 0:
        return f"<span class='ec-neg-val'>-{cl:,}</span>"
    if cr < 0:
        return f"<span class='ec-neg-val'>-{abs(cr):,}</span>"
    if cr > 0:
        return f"<span class='ec-pos-val'>{cr:,}</span>"
    return "<span class='ec-zero-val'>0</span>"


def _fmt_signed_total_won(net_won: int | float | None) -> str:
    v = int(round(float(net_won or 0)))
    if v < 0:
        return f"<span class='ec-neg-val'>-{abs(v):,}</span>"
    if v > 0:
        return f"<span class='ec-pos-val'>{v:,}</span>"
    return "<span class='ec-zero-val'>0</span>"


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

    def _rates(y: int) -> tuple[int, int]:
        r = H.get_unit_rates(corp_size, _cap(y), scheme="legacy", retention_year=1)
        return r["청년등"], r["청년등외"]

    is_large = corp_size in ("일반기업", "대기업")

    def _s_yr(y: int) -> dict:
        d = totals_all.get(y) or {}
        reg = float(d.get("상시_평균", d.get("regular", 0.0)) or 0.0)
        yth = float(d.get("청년등_평균", d.get("youth", 0.0)) or 0.0)
        b2_r = float(d.get("b2_reg", reg) or 0.0)
        b2_y = float(d.get("b2_yth", yth) or 0.0)
        b3_r = float(d.get("b3_reg", reg) or 0.0)
        b3_y = float(d.get("b3_yth", yth) or 0.0)
        has_d = bool(d.get("has_data", reg > 0 or yth > 0))
        return {
            "reg": round(reg, 2),
            "yth": round(yth, 2),
            "gen": round(max(0.0, reg - yth), 2),
            "b2_reg": round(b2_r, 2),
            "b2_yth": round(b2_y, 2),
            "b3_reg": round(b3_r, 2),
            "b3_yth": round(b3_y, 2),
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

        if f_y_inc is not None or f_g_inc is not None or f_clm is not None:
            yi = float(f_y_inc or 0.0)
            gi = float(f_g_inc or 0.0)
            calc_1st = int(round((yi * yth_r + gi * gen_r) * 10_000))
            if f_clm is not None and int(f_clm or 0) > 0:
                c1_won = int(f_clm)
            else:
                c1_won = calc_1st
            return {
                "has": True,
                "reg": float(f_reg if f_reg is not None else sy["reg"]),
                "yth": float(f_yth if f_yth is not None else sy["yth"]),
                "yth_inc": yi,
                "gen_inc": gi,
                "credit_1st_won": c1_won,
            }

        if recalc_ok and inc_recalc is not None:
            return {
                "has": True,
                "reg": sy["reg"],
                "yth": sy["yth"],
                "yth_inc": inc_recalc["youth_inc"],
                "gen_inc": inc_recalc["non_youth_inc"],
                "credit_1st_won": int(cr_recalc or 0),
            }

        return {
            "has": False,
            "reg": sy["reg"],
            "yth": sy["yth"],
            "yth_inc": 0.0,
            "gen_inc": 0.0,
            "credit_1st_won": 0,
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
    }

    # ── (B) tax_yr - 2 열 (예: 2024년) ──
    c_m2_1 = info_m2["credit_1st_won"]
    c_m2_2_cr, c_m2_2_cl = 0, 0
    s_m2 = _s_yr(y_m2)
    if info_m3["has"] and s_m2["has_data"] and (info_m3["yth_inc"] + info_m3["gen_inc"] > 0):
        pm_m3_in_m2 = H.calc_legacy_post_management(
            cohort_year=y_m3,
            eval_year=y_m2,
            corp_size=corp_size,
            is_capital=_cap(y_m3),
            init_reg=info_m3["reg"],
            init_yth=info_m3["yth"],
            init_yth_inc=info_m3["yth_inc"],
            init_gen_inc=info_m3["gen_inc"],
            cur_pm_reg=s_m2["b2_reg"],
            cur_pm_yth=s_m2["b2_yth"],
            init_credit_claimed_won=info_m3["credit_1st_won"],
        )
        c_m2_2_cr = int(pm_m3_in_m2.get("continued_credit_won") or 0)
        c_m2_2_cl = int(pm_m3_in_m2.get("clawback_net_payable_won") or 0)
    cols[y_m2] = {
        "r1_credit": c_m2_1, "r1_claw": 0,
        "r2_credit": c_m2_2_cr, "r2_claw": c_m2_2_cl,
        "r3_credit": 0, "r3_claw": 0,
        "net_total": c_m2_1 + c_m2_2_cr - c_m2_2_cl,
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
            corp_size=corp_size,
            is_capital=_cap(y_m2),
            init_reg=info_m2["reg"],
            init_yth=info_m2["yth"],
            init_yth_inc=info_m2["yth_inc"],
            init_gen_inc=info_m2["gen_inc"],
            cur_pm_reg=s_m1["b2_reg"],
            cur_pm_yth=s_m1["b2_yth"],
            init_credit_claimed_won=info_m2["credit_1st_won"],
        )
        c_m1_2_cr = int(pm_m2_in_m1.get("continued_credit_won") or 0)
        c_m1_2_cl = int(pm_m2_in_m1.get("clawback_net_payable_won") or 0)

    if info_m3["has"] and s_m1["has_data"] and (info_m3["yth_inc"] + info_m3["gen_inc"] > 0):
        cap_m3_2yr = info_m3["credit_1st_won"] + (c_m2_2_cr if not is_large else 0)
        pm_m3_in_m1 = H.calc_legacy_post_management(
            cohort_year=y_m3,
            eval_year=y_m1,
            corp_size=corp_size,
            is_capital=_cap(y_m3),
            init_reg=info_m3["reg"],
            init_yth=info_m3["yth"],
            init_yth_inc=info_m3["yth_inc"],
            init_gen_inc=info_m3["gen_inc"],
            cur_pm_reg=s_m1["b3_reg"],
            cur_pm_yth=s_m1["b3_yth"],
            init_credit_claimed_won=info_m3["credit_1st_won"],   # 2차 공제분은 계산 함수가 한도에 자동 합산
            prev_pm_reg=s_m2["b2_reg"] if s_m2["has_data"] else None,
            prev_pm_yth=s_m2["b2_yth"] if s_m2["has_data"] else None,
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
    }
    # 기신고 기준: 과거 연도 열은 세액공제조정명세서(코드 18S)에 실제 신고된 1차·2차·3차 금액을 그대로 표시
    #   (추정치 대신 신고 사실값 사용. 추가납부액은 18S에 없으므로 계산값 유지)
    if active_pm_basis == R.PM_BASIS_FILED:
        cs = {int(k): v for k, v in (((s.get("ext") or {}).get("credit_stmt")) or {}).items()}
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


def _cohort_capital(s: dict, cohort: int, default: bool) -> bool:
    v = ((s.get("prev_summary") or {}).get(str(cohort)) or {}).get("수도권")
    return default if v is None else bool(v)


def _build_pm_formula_lines(
    pm: dict,
    cohort_year: int,
    eval_year: int,
    elapsed: int,
    cur_pm_reg: float,
    cur_pm_yth: float,
    rates_legacy: dict[str, int],
) -> tuple[str, list[str], str, int, bool]:
    """
    (3) 2차년도 사후관리 계산 / (4) 3차년도 사후관리 계산 박스용 상세 산식 생성.
    반환: (제목 요약, 산식 줄 리스트, 우측 금액 라벨, 표시 금액(음수는 추징), 음수여부)
    """
    yth_r = int(rates_legacy["청년등"])
    gen_r = int(rates_legacy["청년등외"])
    diff_r = max(0, yth_r - gen_r)
    nth_label = f"{elapsed + 1}차년도"

    if pm.get("base_missing"):
        return (
            f"{cohort_year}년 귀속분 기초자료 미입력 ({pm.get('case_code', '기초값 없음')})",
            [
                f"• {cohort_year}년 최초공제연도의 상시·청년등 인원 또는 증가인원 기초값이 없습니다.",
                "• 상단 계산 기준을 『⚖️ 2단계 사원표(세법원칙) 기준 계산』으로 선택하거나 아래 기신고 기초값을 입력해 주세요.",
            ],
            "세액공제액 / 추가납부액",
            0,
            False,
        )

    if str(pm.get("case_code") or "").startswith("신법") and isinstance(pm.get("new_tier_info"), dict):
        ti = pm["new_tier_info"]
        t_rates = ti.get("rates") or {"청년등": 0, "청년등외": 0}
        y_u = int(t_rates.get("청년등", 0)) * 10_000
        g_u = int(t_rates.get("청년등외", 0)) * 10_000
        y_inc = float(ti.get("youth_inc") or 0.0)
        g_inc = float(ti.get("non_youth_inc") or 0.0)
        y_w = int(ti.get("item1_youth_won") or 0)
        g_w = int(ti.get("item2_non_youth_won") or 0)
        d_w = int(ti.get("item3_deduction_won") or 0)
        cr_w = int(ti.get("credit_won") or 0)
        new_lines = [
            f"• {cohort_year}년 이후 귀속분은 구법 사후관리(추징) 대상이 아니며, 2026 신법 {nth_label} 유지분 점증형 공제단가가 적용됩니다.",
            f"• 청년 등 유지 인원: <b>{y_inc:.2f}명</b> × {y_u:,}원 = <b>{y_w:,}원</b> / 청년 등 외 유지 인원: <b>{g_inc:.2f}명</b> × {g_u:,}원 = <b>{g_w:,}원</b>"
            + (f" (최소고용증가인원 차감 -{d_w:,}원)" if d_w > 0 else ""),
            f"• 산식 합계: ({y_inc:.2f} × {y_u:,}원) + ({g_inc:.2f} × {g_u:,}원)"
            + (f" - {d_w:,}원" if d_w > 0 else "")
            + f" = <b>{cr_w:,}원</b>",
        ]
        return (
            f"{cohort_year}년 귀속분 {nth_label} 유지 세액공제 — {pm.get('case_code')}",
            new_lines,
            f"{nth_label} 유지 세액공제액",
            cr_w,
            False,
        )

    if not pm.get("active"):
        return (
            f"{cohort_year}년 귀속분 — {pm.get('case_title', '사후관리 대상 아님')}",
            [
                f"• {cohort_year}년 귀속 최초 공제 대상 고용증가 인원이 없거나 사후관리 대상이 아닙니다.",
                f"• 산식: 공제대상 증가인원 0명 × 공제단가 = 0원",
            ],
            "세액공제액 / 추가납부액",
            0,
            False,
        )

    init_reg = float(pm.get("init_reg") or 0.0)
    init_yth = float(pm.get("init_yth") or 0.0)
    init_y_inc = float(pm.get("init_yth_inc") or 0.0)
    init_g_inc = float(pm.get("init_gen_inc") or 0.0)
    ret_y = float(pm.get("retained_yth_inc") or 0.0)
    ret_g = float(pm.get("retained_gen_inc") or 0.0)
    reg_dec = float(pm.get("reg_decrease") or 0.0)
    yth_dec = float(pm.get("yth_decrease") or 0.0)

    cont_won = int(pm.get("continued_credit_won") or 0)
    claw_net_won = int(pm.get("clawback_net_payable_won") or 0)
    claw_raw_won = int(pm.get("clawback_raw_cumulative_won") or 0)
    prior_ded_won = int(pm.get("prior_clawback_deducted_won") or 0)
    cf_off_won = int(pm.get("carryforward_offset_won") or 0)

    lines = [
        f"• 인원 비교 ({cohort_year}년 최초공제 대비 {eval_year}년 사후관리 기준): "
        f"전체 상시 {init_reg:.2f}명 → {cur_pm_reg:.2f}명 (증감 {cur_pm_reg - init_reg:+.2f}명) / "
        f"청년등 {init_yth:.2f}명 → {cur_pm_yth:.2f}명 (증감 {cur_pm_yth - init_yth:+.2f}명)",
        f"• {cohort_year}년 최초 공제받은 증가인원: 전체 {init_y_inc + init_g_inc:.2f}명 "
        f"(청년등 {init_y_inc:.2f}명 · 청년등 외 {init_g_inc:.2f}명)",
    ]

    if cont_won > 0 and claw_net_won == 0:
        lines.append(
            f"• {nth_label} 연속공제 산식: (유지 청년등 {ret_y:.2f}명 × {yth_r*10_000:,}원) + "
            f"(유지 청년등 외 {ret_g:.2f}명 × {gen_r*10_000:,}원) = {cont_won:,}원"
        )
        return (
            f"{cohort_year}년 귀속분 {nth_label} 사후관리 — {pm.get('case_code', '고용 유지')}",
            lines,
            f"{nth_label} 세액공제액",
            cont_won,
            False,
        )

    if claw_net_won > 0 and cont_won > 0:
        capped_y_dec = min(init_y_inc, yth_dec)
        lines.append(
            f"• {nth_label} 부분 연속공제 산식: (유지 청년등 {ret_y:.2f}명 × {yth_r*10_000:,}원) + "
            f"(대체포함 일반 {ret_g:.2f}명 × {gen_r*10_000:,}원) = {cont_won:,}원"
        )
        lines.append(
            f"• 청년등 감소분 단가차액 추가납부 산식: 감소 청년등 {capped_y_dec:.2f}명 × "
            f"({yth_r*10_000:,}원 - {gen_r*10_000:,}원 = {diff_r*10_000:,}원) → 추가납부 (-){claw_net_won:,}원"
        )
        net_v = cont_won - claw_net_won
        return (
            f"{cohort_year}년 귀속분 {nth_label} 사후관리 — {pm.get('case_code', '부분공제 + 추가납부')}",
            lines,
            f"{nth_label} 순세액 (공제 {cont_won:,} / 추징 -{claw_net_won:,})",
            net_v,
            net_v < 0,
        )

    if claw_net_won > 0 or claw_raw_won > 0:
        lines.append(f"• 사후관리 추징 산식: {pm.get('formula_note', '')}")
        if prior_ded_won > 0 or cf_off_won > 0:
            lines.append(
                f"• 차감 반영: 산출 추징액 {claw_raw_won:,}원 - 기추징 차감 {prior_ded_won:,}원 - "
                f"미공제 이월세액 차감 {cf_off_won:,}원 = 당기 추가납부세액 (-){claw_net_won:,}원"
            )
        return (
            f"{cohort_year}년 귀속분 {nth_label} 사후관리 — {pm.get('case_code', '고용 감소 추징')}",
            lines,
            f"{nth_label} 추가납부세액",
            -claw_net_won,
            claw_net_won > 0,
        )

    lines.append(f"• 검토 결과: {pm.get('formula_note', '연속공제 및 추가납부세액 0원')}")
    return (
        f"{cohort_year}년 귀속분 {nth_label} 사후관리 — {pm.get('case_code', '세액 없음')}",
        lines,
        "세액공제액 / 추가납부액",
        0,
        False,
    )



def _build_step3_calculation_pdf_bytes(
    s: dict,
    pkg: dict,
    matrix_cols: dict[int, dict[str, Any]],
) -> bytes:
    """
    3단계 『공제액 계산』 화면의:
    ① 4개년 통합고용세액공제 요약표 (1차 / 2차 / 3차 / 합계)
    ② (1) 평균 상시근로자 증가 인원 표
    ③ (2) 1차년도 세액공제액 계산 산식
    ④ (3) 2차년도 사후관리 요건 검토(여/부) 및 계산 산식
    ⑤ (4) 3차년도 사후관리 요건 검토(여/부) 및 계산 산식
    ⑥ 계산근거 관련 법령 조문
    을 A4 세로(Portrait) 고해상도 정식 PDF로 생성합니다.
    """
    reg_font, bold_font = _ensure_korean_pdf_font()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=26,
        rightMargin=26,
        topMargin=26,
        bottomMargin=26,
    )
    avail_w = A4[0] - 52

    styles = getSampleStyleSheet()
    st_title = ParagraphStyle(
        "ECStep3Title",
        parent=styles["Normal"],
        fontName=bold_font,
        fontSize=13.5,
        leading=18,
        textColor=colors.HexColor("#0f172a"),
        spaceAfter=3,
    )
    st_sub = ParagraphStyle(
        "ECStep3Sub",
        parent=styles["Normal"],
        fontName=reg_font,
        fontSize=8.8,
        leading=13,
        textColor=colors.HexColor("#334155"),
        spaceAfter=8,
    )
    st_sec = ParagraphStyle(
        "ECStep3Sec",
        parent=styles["Normal"],
        fontName=bold_font,
        fontSize=10.8,
        leading=15,
        textColor=colors.HexColor("#1e3a8a"),
        spaceBefore=8,
        spaceAfter=5,
    )
    st_body = ParagraphStyle(
        "ECStep3Body",
        parent=styles["Normal"],
        fontName=reg_font,
        fontSize=8.8,
        leading=13.5,
        textColor=colors.HexColor("#1e293b"),
    )

    b = s.get("biz") or {}
    corp_nm = (b.get("상호") or "").strip()
    biz_no = (b.get("사업자번호") or "").strip()
    corp_size = pkg.get("corp_size") or "중소기업"
    is_capital = bool(pkg.get("is_capital", True))
    loc_label = "수도권" if is_capital else "수도권 외(비수도권)"
    tax_yr = int(pkg.get("tax_year") or R.DEFAULT_TAX_YEAR)
    basis_lbl = pkg.get("pm_basis_label") or "기신고 기준"

    story = []
    story.append(
        Paragraph(
            _pdf_text((f"[{corp_nm}] " if corp_nm else "") + f"{tax_yr}년 귀속 통합고용세액공제 및 사후관리 계산서"),
            st_title,
        )
    )
    story.append(
        Paragraph(
            _pdf_text(
                f"사업자등록번호: {biz_no}  |  기업규모·소재지: {corp_size} · {loc_label}  |  "
                f"적용 기준: {basis_lbl}  |  단위: 원 (추가납부세액은 - 표시)"
            ),
            st_sub,
        )
    )

    # 1) 상단 4개년 요약 매트릭스 표
    yr_list = [tax_yr - 3, tax_yr - 2, tax_yr - 1, tax_yr]
    story.append(Paragraph(_pdf_text(f"■ 연도별 통합고용세액공제 요약표 ({corp_size} · {loc_label})"), st_sec))

    def _cell_str(cr: int, cl: int) -> str:
        cr_i, cl_i = int(cr or 0), int(cl or 0)
        if cr_i > 0 and cl_i > 0:
            return f"+{cr_i:,}\n(-{cl_i:,})"
        if cl_i > 0:
            return f"-{cl_i:,}"
        if cr_i < 0:
            return f"-{abs(cr_i):,}"
        return f"{cr_i:,}"

    mat_data = [
        ["구분", "차수", *[f"{y}년{' (당해)' if y == tax_yr else ''}" for y in yr_list]],
        ["세액공제액\n(추가납부세액)", "1차", *[_cell_str(matrix_cols[y]["r1_credit"], matrix_cols[y]["r1_claw"]) for y in yr_list]],
        ["", "2차", *[_cell_str(matrix_cols[y]["r2_credit"], matrix_cols[y]["r2_claw"]) for y in yr_list]],
        ["", "3차", *[_cell_str(matrix_cols[y]["r3_credit"], matrix_cols[y]["r3_claw"]) for y in yr_list]],
        ["", "합계", *[f"{int(matrix_cols[y]['net_total']):,}" for y in yr_list]],
    ]
    mat_widths = [avail_w * 0.16, avail_w * 0.08, avail_w * 0.19, avail_w * 0.19, avail_w * 0.19, avail_w * 0.19]
    t_mat = Table(mat_data, colWidths=mat_widths)
    t_mat.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), bold_font),
                ("FONTNAME", (0, 1), (1, -1), bold_font),
                ("FONTNAME", (2, 1), (-1, -2), reg_font),
                ("FONTNAME", (0, -1), (-1, -1), bold_font),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("LEADING", (0, 0), (-1, -1), 11.5),
                ("SPAN", (0, 0), (1, 0)),
                ("SPAN", (0, 1), (0, 4)),
                ("ALIGN", (0, 0), (1, -1), "CENTER"),
                ("ALIGN", (2, 0), (-1, 0), "CENTER"),
                ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("BACKGROUND", (-1, 0), (-1, 0), colors.HexColor("#1d4ed8")),
                ("BACKGROUND", (0, 1), (1, -1), colors.HexColor("#f8fafc")),
                ("BACKGROUND", (-1, 1), (-1, -2), colors.HexColor("#f0f7ff")),
                ("BACKGROUND", (1, -1), (-1, -1), colors.HexColor("#f1f5f9")),
                ("BACKGROUND", (-1, -1), (-1, -1), colors.HexColor("#dbeafe")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("BOX", (0, 0), (-1, -1), 1.0, colors.HexColor("#1e293b")),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(t_mat)
    story.append(Spacer(1, 6))

    # 2) (1) 평균 상시근로자 증가 인원 표
    cur_s = pkg["cur_s"]
    prev_s = pkg["prev_s"]
    cur_inc = pkg["cur_inc"]
    story.append(Paragraph(_pdf_text(f"1. {tax_yr}년 세액공제 — (1) 평균 상시근로자 증가 인원"), st_sec))
    inc_data = [
        ["구분", f"해당 과세연도 ({tax_yr}년)", f"직전 과세연도 ({tax_yr-1}년)", "증가인원"],
        ["상시근로자 증가", f"{cur_s['regular']:.2f}명", f"{prev_s['regular']:.2f}명", f"{cur_inc['total_inc']:.2f}명 (증감 {cur_inc['total_diff']:+.2f})"],
        ["청년 등 상시근로자 증가", f"{cur_s['youth']:.2f}명", f"{prev_s['youth']:.2f}명", f"{cur_inc['youth_inc']:.2f}명"],
        ["이 외 상시근로자 증가", f"{cur_s['non_youth']:.2f}명", f"{prev_s['non_youth']:.2f}명", f"{cur_inc['non_youth_inc']:.2f}명"],
    ]
    t_inc = Table(inc_data, colWidths=[avail_w * 0.30, avail_w * 0.23, avail_w * 0.23, avail_w * 0.24])
    t_inc.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), bold_font),
                ("FONTNAME", (0, 1), (0, -1), bold_font),
                ("FONTNAME", (1, 1), (-2, -1), reg_font),
                ("FONTNAME", (-1, 1), (-1, -1), bold_font),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ("ALIGN", (0, 1), (0, -1), "CENTER"),
                ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("BACKGROUND", (0, 1), (0, -1), colors.HexColor("#f8fafc")),
                ("BACKGROUND", (-1, 1), (-1, -1), colors.HexColor("#f0f7ff")),
                ("TEXTCOLOR", (-1, 1), (-1, -1), colors.HexColor("#1d4ed8")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("BOX", (0, 0), (-1, -1), 0.9, colors.HexColor("#1e293b")),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(t_inc)
    story.append(Spacer(1, 5))

    def _add_calc_card(sec_hdr: str, title_txt: str, lines_list: list[str], amt_lbl: str, amt_val: int, is_neg: bool = False):
        story.append(Paragraph(_pdf_text(sec_hdr), st_sec))
        body_html = f"<font name='{bold_font}'><b>{_pdf_text(title_txt)}</b></font><br/>" + "<br/>".join(
            _pdf_text(re.sub(r"<[^>]+>", "", ln)) for ln in lines_list
        )
        amt_str = f"-{abs(amt_val):,}원" if amt_val < 0 else f"{amt_val:,}원"
        amt_color = "#dc2626" if is_neg or amt_val < 0 else ("#15803d" if amt_val > 0 else "#334155")
        right_p = Paragraph(
            f"<font name='{bold_font}' size='8.2' color='#475569'>{_pdf_text(amt_lbl)}</font><br/>"
            f"<font name='{bold_font}' size='11.5' color='{amt_color}'><b>{amt_str}</b></font>",
            ParagraphStyle("RAmt", parent=st_body, alignment=2, leading=15),
        )
        card_tbl = Table([[Paragraph(body_html, st_body), right_p]], colWidths=[avail_w * 0.72, avail_w * 0.28])
        border_c = "#dc2626" if (is_neg or amt_val < 0) else ("#16a34a" if amt_val > 0 else "#94a3b8")
        bg_r = "#fef2f2" if (is_neg or amt_val < 0) else ("#f0fdf4" if amt_val > 0 else "#f8fafc")
        card_tbl.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("BACKGROUND", (0, 0), (0, 0), colors.white),
                    ("BACKGROUND", (1, 0), (1, 0), colors.HexColor(bg_r)),
                    ("BOX", (0, 0), (-1, -1), 0.9, colors.HexColor(border_c)),
                    ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                    ("LEFTPADDING", (0, 0), (-1, -1), 10),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ]
            )
        )
        story.append(card_tbl)
        story.append(Spacer(1, 4))

    # 3) (2) 1차년도 세액공제액 계산
    if pkg["active_scheme"] == "new_2026":
        r_y1 = pkg["rates_new_y1"]
        yu, gu = r_y1["청년등"] * 10_000, r_y1["청년등외"] * 10_000
        ya = int(round(cur_inc["youth_inc"] * yu))
        ga = int(round(cur_inc["non_youth_inc"] * gu))
        ded = int(pkg.get("cur_new_ded_won") or 0)
        first_won = max(0, ya + ga - ded)
        y1_lines = [
            f"• 청년 등 상시근로자 증가: {cur_inc['youth_inc']:.2f}명 × {yu:,}원 = {ya:,}원",
            f"• 청년 등 외 상시근로자 증가: {cur_inc['non_youth_inc']:.2f}명 × {gu:,}원 = {ga:,}원",
            f"• 산식 합계: ({cur_inc['youth_inc']:.2f} × {yu:,}원) + ({cur_inc['non_youth_inc']:.2f} × {gu:,}원)"
            + (f" - 최소고용증가인원 차감 {ded:,}원" if ded > 0 else "")
            + f" = {first_won:,}원",
        ]
    else:
        r_leg = pkg["rates_legacy"]
        yu, gu = r_leg["청년등"] * 10_000, r_leg["청년등외"] * 10_000
        ya = int(round(cur_inc["youth_inc"] * yu))
        ga = int(round(cur_inc["non_youth_inc"] * gu))
        first_won = ya + ga
        y1_lines = [
            f"• 청년 등 상시근로자 증가: {cur_inc['youth_inc']:.2f}명 × {yu:,}원 = {ya:,}원",
            f"• 청년 등 외 상시근로자 증가: {cur_inc['non_youth_inc']:.2f}명 × {gu:,}원 = {ga:,}원",
            f"• 산식 합계: ({cur_inc['youth_inc']:.2f} × {yu:,}원) + ({cur_inc['non_youth_inc']:.2f} × {gu:,}원) = {first_won:,}원",
        ]
    _add_calc_card(
        f"(2) 1차년도 세액공제액 계산 ({corp_size}, {loc_label})",
        f"{tax_yr}년 귀속 1차년도 신규 고용증가 세액공제 (조특법 제29조의8 제1항)",
        y1_lines,
        "1차년도 세액공제액",
        first_won,
        False,
    )

    # 4) (3) 2차년도 사후관리 계산
    pm1_title, pm1_lines, pm1_lbl, pm1_val, pm1_neg = _build_pm_formula_lines(
        pm=pkg["pm_y1"],
        cohort_year=tax_yr - 1,
        eval_year=tax_yr,
        elapsed=1,
        cur_pm_reg=cur_s["b2_reg"],
        cur_pm_yth=cur_s["b2_yth"],
        rates_legacy=H.get_unit_rates(corp_size, _cohort_capital(s, tax_yr - 1, is_capital), scheme="legacy", retention_year=1),
    )
    _add_calc_card(
        f"(3) 2차년도 사후관리 계산 ({tax_yr - 1}년 귀속분 → {tax_yr}년 1차 사후관리)",
        pm1_title,
        pm1_lines,
        pm1_lbl,
        pm1_val,
        pm1_neg,
    )

    # 5) (4) 3차년도 사후관리 계산
    pm2_title, pm2_lines, pm2_lbl, pm2_val, pm2_neg = _build_pm_formula_lines(
        pm=pkg["pm_y2"],
        cohort_year=tax_yr - 2,
        eval_year=tax_yr,
        elapsed=2,
        cur_pm_reg=cur_s["b3_reg"],
        cur_pm_yth=cur_s["b3_yth"],
        rates_legacy=H.get_unit_rates(corp_size, _cohort_capital(s, tax_yr - 2, is_capital), scheme="legacy", retention_year=1),
    )
    _add_calc_card(
        f"(4) 3차년도 사후관리 계산 ({tax_yr - 2}년 귀속분 → {tax_yr}년 2차 사후관리)",
        pm2_title,
        pm2_lines,
        pm2_lbl,
        pm2_val,
        pm2_neg,
    )

    # 6) 법령 근거 요약
    story.append(Spacer(1, 4))
    story.append(
        Paragraph(
            _pdf_text(
                "■ 계산근거 법령: 조세특례제한법 제29조의8 제1항(고용증가 세액공제)·제3항(사후관리 연속공제 및 추가납부), "
                "같은 법 시행령 제26조의8 제2항·제3항(상시·청년등 범위 및 증가한도 Cap)·제5항(사후관리 시 청년 연령경과 간주)·"
                "제6항(추가납부세액 산식)·제9항(소수점 둘째 자리 절사)·제10항(포괄양수·고용승계 특례), 농어촌특별세법 제5조 제1항(감면세액의 20%)."
            ),
            st_sub,
        )
    )

    doc.build(story)
    return buf.getvalue()


def _page_calculation():
    s = _S()
    _ensure_built_for_tax_year(s)
    tax_yr = int(s["tax_year"])
    b = s["biz"]
    corp_size = b.get("기업구분", "중소기업")
    cap_bool = H.is_capital_area(b.get("사업장소재지", ""))
    is_capital = True if cap_bool is None else bool(cap_bool)
    loc_label = "수도권" if is_capital else "수도권 외"

    totals_all = _ensure_totals_snapshot(s)
    cur_t = totals_all.get(tax_yr, {})
    prev_t = totals_all.get(tax_yr - 1, {})
    prev2_t = totals_all.get(tax_yr - 2, {})
    b3_title, b4_title, b5_title = _block_titles_for_year(tax_yr, two_line=False)

    # 기신고 서식을 별도로 업로드하지 않았고 사용자가 아직 계산 기준을 수동 변경하지 않았다면,
    # 2단계 사원표(세법원칙)에서 계산된 인원이 3단계에 즉시 반영되도록 자동 설정합니다.
    has_prev_doc = bool(((s.get("ext") or {}).get("prev_filing") or {}).get("연도별"))
    ps = s.setdefault("prev_summary", {})
    has_any_manual_ps = any(
        (ps.get(str(y)) or {}).get(k) is not None
        for y in (tax_yr - 1, tax_yr - 2)
        for k in ("상시", "청년등", "청년등_증가", "청년등외_증가", "공제세액")
    )
    if not s.get("_pm_basis_user_touched") and not has_prev_doc and not has_any_manual_ps:
        if prev_t.get("has_data") and not prev_t.get("from_filed"):
            s["pm_basis"] = R.PM_BASIS_RECALC

    if cap_bool is None:
        st.warning("사업장 소재지가 입력되지 않아 수도권 단가로 임시 계산되었습니다. 좌측 사이드바에서 사업장 소재지를 입력해 주세요.")

    last_m_cur = H.detect_last_paid_month(s.get("people") or {}, tax_yr)
    if s.get("assume_year_end", True) and last_m_cur < 12:
        st.markdown(
            f"<div class='ec-warn-banner'>"
            f"⚠️ <b>[기중 가결산 추정치 안내]</b> 현재 {tax_yr}년 원천징수부가 <b>{last_m_cur}월분</b>까지 업로드되어, "
            f"미도래 월(<b>{last_m_cur+1}~12월</b>)은 <b>'① 연말까지 재직 가정(1 자동 채움)'</b> 기준으로 시뮬레이션된 추정 세액입니다. "
            f"실제 세무신고 시에는 12월 최종 원천징수부를 업로드하거나, 2단계 상단에서 <b>'미도래 월 연말재직 가정'</b> 스위치를 끄고 확정하세요."
            f"</div>",
            unsafe_allow_html=True,
        )

    for cohort in (tax_yr - 1, tax_yr - 2, tax_yr - 3):
        ps.setdefault(str(cohort), {})

    # 백업 복원 등으로 이미 저장된 prev_summary에도 증가인원/수도권 자동 보완 적용
    _ext_pf_map = ((s.get("ext") or {}).get("prev_filing") or {}).get("연도별") or {}
    _extra_cnts = {
        str(yk): {"상시": float(yv["상시"]), "청년등": float(yv["청년등"])}
        for yk, yv in _ext_pf_map.items()
        if isinstance(yv, dict) and yv.get("상시") is not None and yv.get("청년등") is not None
    }
    P.fill_missing_increments(ps, corp_size, _extra_cnts)

    p1 = ps[str(tax_yr - 1)]
    p2 = ps[str(tax_yr - 2)]
    add_in = s.setdefault("additional_inputs", {})
    active_pm_basis = s.get("pm_basis", R.PM_BASIS_RECALC)

    prior_filings_payload = {
        cohort: {
            "init_reg": f.get("상시"),
            "init_yth": f.get("청년등"),
            "init_reg_total": f.get("상시_총인원"),
            "init_yth_total": f.get("청년등_총인원"),
            "init_yth_inc": f.get("청년등_증가"),
            "init_gen_inc": f.get("청년등외_증가"),
            "claimed_won": f.get("공제세액"),
            "carryforward_won": f.get("이월세액"),
            "y1_continued_won": f.get("2차_공제세액") if cohort == tax_yr - 2 else None,
            "prior_clawback_paid_won": f.get("기추징세액") if cohort == tax_yr - 2 else None,
            "is_capital": f.get("수도권"),
        }
        for cohort, f in ((tax_yr - 1, p1), (tax_yr - 2, p2))
    }

    pkg = H.calculate_tax_year_package(
        tax_year=tax_yr,
        corp_size=corp_size,
        is_capital=is_capital,
        summaries=totals_all,
        prior_filings=prior_filings_payload,
        additional_inputs=add_in,
        scheme_2026=s.get("scheme_2026", "new_2026"),
        pm_basis=active_pm_basis,
    )
    s["calc_pkg"] = pkg
    basis_lbl = pkg["pm_basis_label"]

    # ══════════════════════════════════════════════════════════════
    # [상단] 연도별 세액공제 및 사후관리 요약 매트릭스 (4개 과세연도 한눈에 보기)
    # ══════════════════════════════════════════════════════════════
    matrix_cols = _compute_historical_matrix_columns(
        s=s,
        tax_yr=tax_yr,
        corp_size=corp_size,
        is_capital=is_capital,
        totals_all=totals_all,
        ps=ps,
        pkg_cur=pkg,
        active_pm_basis=active_pm_basis,
    )
    yr_list = [tax_yr - 3, tax_yr - 2, tax_yr - 1, tax_yr]

    basis_badge_html = (
        f"<span class='ec-basis-pill-recalc'>⚖️ 적용 기준: 2단계 사원표(세법원칙) 기준</span>"
        if active_pm_basis == R.PM_BASIS_RECALC
        else f"<span class='ec-basis-pill-filed'>📋 적용 기준: 기신고 서식 숫자 기준</span>"
    )

    filed_tag = "<br><span style='font-size:10px;font-weight:500;opacity:.75'>기신고 금액</span>"
    th_years_html = "".join(
        f"<th class='{'active-yr' if y == tax_yr else ''}'>{y}년{' (당해 귀속)' if y == tax_yr else ''}"
        + (filed_tag if matrix_cols.get(y, {}).get("from_filed_stmt") else "")
        + "</th>"
        for y in yr_list
    )
    r1_cells = "".join(
        f"<td class='{'active-yr-cell' if y == tax_yr else ''}'>"
        f"{_fmt_matrix_won(matrix_cols[y]['r1_credit'], matrix_cols[y]['r1_claw'])}</td>"
        for y in yr_list
    )
    r2_cells = "".join(
        f"<td class='{'active-yr-cell' if y == tax_yr else ''}'>"
        f"{_fmt_matrix_won(matrix_cols[y]['r2_credit'], matrix_cols[y]['r2_claw'])}</td>"
        for y in yr_list
    )
    r3_cells = "".join(
        f"<td class='{'active-yr-cell' if y == tax_yr else ''}'>"
        f"{_fmt_matrix_won(matrix_cols[y]['r3_credit'], matrix_cols[y]['r3_claw'])}</td>"
        for y in yr_list
    )
    tot_cells = "".join(
        f"<td class='{'active-yr-cell' if y == tax_yr else ''}'>"
        f"{_fmt_signed_total_won(matrix_cols[y]['net_total'])}</td>"
        for y in yr_list
    )

    st.markdown(
        f"<div class='ec-matrix-wrap'>"
        f"<div class='ec-matrix-title'>"
        f"<span>📊 연도별 통합고용세액공제 요약표 ({corp_size} · {loc_label})</span>"
        f"<span style='font-size:1.04rem;font-weight:700;color:#475569;'>"
        f"{basis_badge_html} &nbsp;·&nbsp; 단위: 원 (추가납부세액은 <span class='ec-neg-val'>-붉은색</span> 표시)"
        f"</span>"
        f"</div>"
        f"<table class='ec-matrix-tbl'>"
        f"<colgroup>"
        f"<col style='width:12%;'><col style='width:8%;'>"
        f"<col style='width:20%;'><col style='width:20%;'><col style='width:20%;'><col style='width:20%;'>"
        f"</colgroup>"
        f"<thead>"
        f"<tr><th colspan='2' style='width:20%;'>구분</th>{th_years_html}</tr>"
        f"</thead>"
        f"<tbody>"
        f"<tr><td rowspan='4' class='lbl-col' style='width:12%;'>세액공제액<br><span style='font-size:.94rem;font-weight:700;color:#dc2626;'>(추가납부세액)</span></td>"
        f"<td class='lbl-col' style='width:8%;'>1차</td>{r1_cells}</tr>"
        f"<tr><td class='lbl-col'>2차</td>{r2_cells}</tr>"
        f"<tr><td class='lbl-col'>3차</td>{r3_cells}</tr>"
        f"<tr class='ec-tot-row'><td class='lbl-col'>합계</td>{tot_cells}</tr>"
        f"</tbody>"
        f"</table>"
        f"</div>",
        unsafe_allow_html=True,
    )

    # ── 계산 기준 선택 바 (2단계 사원표 기준 vs 기신고 서식 기준) ──
    with st.container(border=True):
        c_sel_lbl, c_sel_wg, c_scheme_wg = st.columns([2.3, 2.5, 1.8])
        with c_sel_lbl:
            st.markdown(
                "<div style='padding-top:2px;font-size:1.04rem;font-weight:800;color:#0f172a;'>"
                "🔘 세액공제·사후관리 계산 기준 선택"
                "</div>"
                "<div style='font-size:.90rem;color:#475569;margin-top:2px;'>"
                "2단계 사원표 재계산 값과 기신고 서식 숫자 중 적용할 기준을 선택하세요."
                "</div>",
                unsafe_allow_html=True,
            )
        with c_sel_wg:
            _render_pm_basis_selector_right(s, widget_key=f"pm_basis_top_step3_{tax_yr}")
        with c_scheme_wg:
            if tax_yr >= 2026:
                scheme_opt = st.selectbox(
                    f"{tax_yr}년 신규공제 단가 체계",
                    options=["new_2026", "legacy"],
                    index=0 if s.get("scheme_2026", "new_2026") == "new_2026" else 1,
                    format_func=lambda x: "2026 신법 (연차별 차등 A+B+C)" if x == "new_2026" else "구법 단가 시뮬레이션 (균등단가)",
                    label_visibility="collapsed",
                    key=f"scheme_2026_top_sel_{tax_yr}",
                )
                if scheme_opt != s.get("scheme_2026", "new_2026"):
                    s["scheme_2026"] = scheme_opt
                    _save_ec_to_disk(s)
                    st.rerun()

    # ══════════════════════════════════════════════════════════════
    # [본문] 선택된 당해 귀속연도(tax_yr) 세액공제 상세 내역 (단독 표시)
    # ══════════════════════════════════════════════════════════════
    st.markdown(
        f"<div class='ec-sec-header'>1. {tax_yr}년 세액공제 ({corp_size} · {loc_label} · {basis_lbl})</div>",
        unsafe_allow_html=True,
    )

    # ── (1) 평균 상시근로자 증가 인원 ──
    cur_s = pkg["cur_s"]
    prev_s = pkg["prev_s"]
    cur_inc = pkg["cur_inc"]

    # 당해(1차년도) 신규 공제는 항상 2단계에서 확정한 직전·당해 사원표 재계산 인원 기준
    # (사후관리 기준 선택은 과거 공제분의 유지/추징 판정에만 적용)
    prv_reg_disp = prev_s["regular"]
    prv_yth_disp = prev_s["youth"]
    prv_gen_disp = prev_s["non_youth"]
    inc_disp = cur_inc

    cap_notice_html = ""
    if inc_disp.get("raw_youth_inc", 0) > inc_disp["youth_inc"]:
        cap_notice_html = (
            f"<div style='font-size:.95rem;font-weight:700;color:#b45309;margin-top:-6px;margin-bottom:12px;'>"
            f"※ 청년 등 순증가 인원({inc_disp['raw_youth_inc']:.2f}명)이 전체 상시근로자 증가 한도({inc_disp['total_inc']:.2f}명)를 초과하여 "
            f"한도({inc_disp['youth_inc']:.2f}명)가 적용되었습니다 (조특령 제26조의8 제3항)."
            f"</div>"
        )

    st.markdown(
        "<div class='ec-sub-header'><span class='ec-sub-num'>(1)</span><span>평균 상시근로자 증가 인원</span></div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        f"<table class='ec-inc-tbl'>"
        f"<thead>"
        f"<tr>"
        f"<th>구분</th>"
        f"<th>해당 과세연도 ({tax_yr}년)</th>"
        f"<th>직전 과세연도 ({tax_yr - 1}년)</th>"
        f"<th>증가인원</th>"
        f"</tr>"
        f"</thead>"
        f"<tbody>"
        f"<tr>"
        f"<td class='inc-lbl'>상시근로자 증가</td>"
        f"<td>{cur_s['regular']:.2f}명</td>"
        f"<td>{prv_reg_disp:.2f}명</td>"
        f"<td class='inc-hi'>{inc_disp['total_inc']:.2f}명 "
        f"<span style='font-size:.90rem;color:#475569;font-weight:700;'>(증감 {inc_disp['total_diff']:+.2f})</span></td>"
        f"</tr>"
        f"<tr>"
        f"<td class='inc-lbl'>청년 등 상시근로자 증가</td>"
        f"<td>{cur_s['youth']:.2f}명</td>"
        f"<td>{prv_yth_disp:.2f}명</td>"
        f"<td class='inc-hi'>{inc_disp['youth_inc']:.2f}명</td>"
        f"</tr>"
        f"<tr>"
        f"<td class='inc-lbl'>이 외 상시근로자 증가</td>"
        f"<td>{cur_s['non_youth']:.2f}명</td>"
        f"<td>{prv_gen_disp:.2f}명</td>"
        f"<td class='inc-hi'>{inc_disp['non_youth_inc']:.2f}명</td>"
        f"</tr>"
        f"</tbody>"
        f"</table>"
        f"{cap_notice_html}",
        unsafe_allow_html=True,
    )

    # ── (2) 1차년도 세액공제액 계산 (기업구분, 수도권/비수도권) ──
    st.markdown(
        f"<div class='ec-sub-header'><span class='ec-sub-num'>(2)</span><span>1차년도 세액공제액 계산 ({corp_size}, {loc_label})</span></div>",
        unsafe_allow_html=True,
    )
    if pkg["active_scheme"] == "new_2026":
        r_y1 = pkg["rates_new_y1"]
        y_unit_won = r_y1["청년등"] * 10_000
        g_unit_won = r_y1["청년등외"] * 10_000
        y_amt_won = int(round(inc_disp["youth_inc"] * y_unit_won))
        g_amt_won = int(round(inc_disp["non_youth_inc"] * g_unit_won))
        ded_won = int(pkg["cur_new_ded_won"] or 0)
        first_yr_credit_won = max(0, y_amt_won + g_amt_won - ded_won)
        ded_line_html = (
            f"<div class='f-line' style='color:#b45309;font-weight:700;'>"
            f"• 최소고용증가인원({pkg['hurdle_res']['hurdle']:g}명) 차감액: -{ded_won:,}원 ({pkg['hurdle_res']['note']})"
            f"</div>"
            if ded_won > 0 or not pkg["hurdle_res"]["hurdle_met"]
            else ""
        )
        formula_y1_html = (
            f"<div class='f-title'>{tax_yr}년 귀속 1차년도 신규 고용증가 세액공제 (2026 신법 1년차 단가)</div>"
            f"<div class='f-line'>• 청년 등 상시근로자 증가: <b>{inc_disp['youth_inc']:.2f}명</b> × {y_unit_won:,}원 = <b>{y_amt_won:,}원</b></div>"
            f"<div class='f-line'>• 청년 등 외 상시근로자 증가: <b>{inc_disp['non_youth_inc']:.2f}명</b> × {g_unit_won:,}원 = <b>{g_amt_won:,}원</b></div>"
            f"{ded_line_html}"
            f"<div class='f-sub'>산식 합계: ({inc_disp['youth_inc']:.2f} × {y_unit_won:,}원) + ({inc_disp['non_youth_inc']:.2f} × {g_unit_won:,}원)"
            f"{f' - {ded_won:,}원' if ded_won > 0 else ''} = <b>{first_yr_credit_won:,}원</b></div>"
        )
    else:
        r_leg = pkg["rates_legacy"]
        y_unit_won = r_leg["청년등"] * 10_000
        g_unit_won = r_leg["청년등외"] * 10_000
        y_amt_won = int(round(inc_disp["youth_inc"] * y_unit_won))
        g_amt_won = int(round(inc_disp["non_youth_inc"] * g_unit_won))
        first_yr_credit_won = y_amt_won + g_amt_won
        formula_y1_html = (
            f"<div class='f-title'>{tax_yr}년 귀속 1차년도 고용증가 세액공제 (조특법 제29조의8 제1항 단가)</div>"
            f"<div class='f-line'>• 청년 등 상시근로자 증가: <b>{inc_disp['youth_inc']:.2f}명</b> × {y_unit_won:,}원 = <b>{y_amt_won:,}원</b></div>"
            f"<div class='f-line'>• 청년 등 외 상시근로자 증가: <b>{inc_disp['non_youth_inc']:.2f}명</b> × {g_unit_won:,}원 = <b>{g_amt_won:,}원</b></div>"
            f"<div class='f-sub'>산식 합계: ({inc_disp['youth_inc']:.2f} × {y_unit_won:,}원) + ({inc_disp['non_youth_inc']:.2f} × {g_unit_won:,}원) = <b>{first_yr_credit_won:,}원</b></div>"
        )

    y1_box_cls = "pos-box" if first_yr_credit_won > 0 else "zero-box"
    y1_amt_cls = "pos-amt" if first_yr_credit_won > 0 else ""
    st.markdown(
        f"<div class='ec-calc-box {y1_box_cls}'>"
        f"<div class='ec-calc-formula'>{formula_y1_html}</div>"
        f"<div class='ec-calc-amount {y1_amt_cls}'>"
        f"<div class='a-lbl'>1차년도 세액공제액</div>"
        f"<div class='a-val {'pos' if first_yr_credit_won > 0 else ''}'>{first_yr_credit_won:,}원</div>"
        f"</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

    def _build_pm_req_check_bar_html(pm_obj: dict, cohort_yr: int, eval_yr: int, cur_reg_v: float, cur_yth_v: float) -> str:
        init_r = float(pm_obj.get("init_reg") or 0.0)
        init_y = float(pm_obj.get("init_yth") or 0.0)
        is_active = bool(pm_obj.get("active")) and not bool(pm_obj.get("base_missing"))
        is_new_law = str(pm_obj.get("case_code") or "").startswith("신법")

        if is_new_law and isinstance(pm_obj.get("new_tier_info"), dict):
            ti = pm_obj["new_tier_info"]
            tot_inc = float(ti.get("total_inc") or 0.0)
            yth_inc = float(ti.get("youth_inc") or 0.0)
            reg_dec_yes = tot_inc <= 0
            yth_dec_yes = yth_inc <= 0
            r_sub = f"유지 증가인원: 전체 {tot_inc:.2f}명 ({cohort_yr}년 대비)"
            y_sub = f"유지 증가인원: 청년등 {yth_inc:.2f}명 ({cohort_yr}년 대비)"
            r_yes_cls = "active-yes" if reg_dec_yes else ""
            r_no_cls = "active-no" if not reg_dec_yes else ""
            y_yes_cls = "active-yes" if yth_dec_yes else ""
            y_no_cls = "active-no" if not yth_dec_yes else ""
        elif not is_active:
            r_sub = f"1차년도({cohort_yr}년) 공제이력 또는 기초자료 없음"
            y_sub = f"1차년도({cohort_yr}년) 공제이력 또는 기초자료 없음"
            r_yes_cls = r_no_cls = y_yes_cls = y_no_cls = ""
        else:
            reg_diff_v = round(cur_reg_v - init_r, 2)
            yth_diff_v = round(cur_yth_v - init_y, 2)
            reg_dec_yes = reg_diff_v < 0
            yth_dec_yes = yth_diff_v < 0
            r_sub = f"1차년도({cohort_yr}년) {init_r:.2f}명 → 당해({eval_yr}년) {cur_reg_v:.2f}명 ({reg_diff_v:+.2f}명)"
            y_sub = f"1차년도({cohort_yr}년) {init_y:.2f}명 → 당해({eval_yr}년) {cur_yth_v:.2f}명 ({yth_diff_v:+.2f}명)"
            r_yes_cls = "active-yes" if reg_dec_yes else ""
            r_no_cls = "active-no" if not reg_dec_yes else ""
            y_yes_cls = "active-yes" if yth_dec_yes else ""
            y_no_cls = "active-no" if not yth_dec_yes else ""

        return (
            f"<div class='ec-pm-req-bar'>"
            f"<div class='ec-pm-req-item'>"
            f"<div class='ec-pm-req-lbl'>"
            f"<span class='ec-pm-req-title'>1. 1차년도({cohort_yr}년) 대비 상시근로자 감소여부</span>"
            f"<span class='ec-pm-req-sub'>{r_sub}</span>"
            f"</div>"
            f"<div class='ec-yn-group'>"
            f"<span class='ec-yn-pill {r_yes_cls}'>여 (감소)</span>"
            f"<span class='ec-yn-pill {r_no_cls}'>부 (유지·증가)</span>"
            f"</div>"
            f"</div>"
            f"<div class='ec-pm-req-item'>"
            f"<div class='ec-pm-req-lbl'>"
            f"<span class='ec-pm-req-title'>2. 1차년도({cohort_yr}년) 대비 청년 상시근로자 감소여부</span>"
            f"<span class='ec-pm-req-sub'>{y_sub}</span>"
            f"</div>"
            f"<div class='ec-yn-group'>"
            f"<span class='ec-yn-pill {y_yes_cls}'>여 (감소)</span>"
            f"<span class='ec-yn-pill {y_no_cls}'>부 (유지·증가)</span>"
            f"</div>"
            f"</div>"
            f"</div>"
        )

    # ── (3) 2차년도 사후관리 계산 (직전 과세연도 귀속분의 당해 사후관리) ──
    st.markdown(
        f"<div class='ec-sub-header'><span class='ec-sub-num'>(3)</span><span>2차년도 사후관리 계산 ({tax_yr - 1}년 귀속분 → {tax_yr}년 1차 사후관리)</span></div>",
        unsafe_allow_html=True,
    )
    pm1_req_bar_html = _build_pm_req_check_bar_html(
        pkg["pm_y1"], tax_yr - 1, tax_yr, cur_s["b2_reg"], cur_s["b2_yth"]
    )
    pm1_title, pm1_lines, pm1_amt_lbl, pm1_val, pm1_is_neg = _build_pm_formula_lines(
        pm=pkg["pm_y1"],
        cohort_year=tax_yr - 1,
        eval_year=tax_yr,
        elapsed=1,
        cur_pm_reg=cur_s["b2_reg"],
        cur_pm_yth=cur_s["b2_yth"],
        rates_legacy=H.get_unit_rates(corp_size, _cohort_capital(s, tax_yr - 1, is_capital), scheme="legacy", retention_year=1),
    )
    pm1_lines_html = "".join(f"<div class='f-line'>{ln}</div>" for ln in pm1_lines)
    pm1_val_str = f"-{abs(pm1_val):,}원" if pm1_val < 0 else f"{pm1_val:,}원"
    pm1_cls = "neg" if pm1_is_neg else ("pos" if pm1_val > 0 else "")
    pm1_box_cls = "neg-box" if pm1_is_neg else ("pos-box" if pm1_val > 0 else "zero-box")
    pm1_amt_cls = "neg-amt" if pm1_is_neg else ("pos-amt" if pm1_val > 0 else "")
    pm1_cr = int(pkg["pm_y1"].get("continued_credit_won") or 0)
    pm1_cl = int(pkg["pm_y1"].get("clawback_net_payable_won") or 0)
    pm1_split_html = (
        f"<div class='a-sub-split'>공제 +{pm1_cr:,}원 &nbsp;|&nbsp; <span class='ec-neg-val'>추징 -{pm1_cl:,}원</span></div>"
        if (pm1_cr > 0 and pm1_cl > 0)
        else ""
    )

    st.markdown(
        f"{pm1_req_bar_html}"
        f"<div class='ec-calc-box {pm1_box_cls}'>"
        f"<div class='ec-calc-formula'>"
        f"<div class='f-title'>{pm1_title}</div>"
        f"{pm1_lines_html}"
        f"</div>"
        f"<div class='ec-calc-amount {pm1_amt_cls}'>"
        f"<div class='a-lbl'>{pm1_amt_lbl}</div>"
        f"<div class='a-val {pm1_cls}'>{pm1_val_str}</div>"
        f"{pm1_split_html}"
        f"</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

    # ── (4) 3차년도 사후관리 계산 (전전 과세연도 귀속분의 당해 사후관리) ──
    st.markdown(
        f"<div class='ec-sub-header'><span class='ec-sub-num'>(4)</span><span>3차년도 사후관리 계산 ({tax_yr - 2}년 귀속분 → {tax_yr}년 2차 사후관리)</span></div>",
        unsafe_allow_html=True,
    )
    pm2_req_bar_html = _build_pm_req_check_bar_html(
        pkg["pm_y2"], tax_yr - 2, tax_yr, cur_s["b3_reg"], cur_s["b3_yth"]
    )
    pm2_title, pm2_lines, pm2_amt_lbl, pm2_val, pm2_is_neg = _build_pm_formula_lines(
        pm=pkg["pm_y2"],
        cohort_year=tax_yr - 2,
        eval_year=tax_yr,
        elapsed=2,
        cur_pm_reg=cur_s["b3_reg"],
        cur_pm_yth=cur_s["b3_yth"],
        rates_legacy=H.get_unit_rates(corp_size, _cohort_capital(s, tax_yr - 2, is_capital), scheme="legacy", retention_year=1),
    )
    pm2_lines_html = "".join(f"<div class='f-line'>{ln}</div>" for ln in pm2_lines)
    pm2_val_str = f"-{abs(pm2_val):,}원" if pm2_val < 0 else f"{pm2_val:,}원"
    pm2_cls = "neg" if pm2_is_neg else ("pos" if pm2_val > 0 else "")
    pm2_box_cls = "neg-box" if pm2_is_neg else ("pos-box" if pm2_val > 0 else "zero-box")
    pm2_amt_cls = "neg-amt" if pm2_is_neg else ("pos-amt" if pm2_val > 0 else "")
    pm2_cr = int(pkg["pm_y2"].get("continued_credit_won") or 0)
    pm2_cl = int(pkg["pm_y2"].get("clawback_net_payable_won") or 0)
    pm2_split_html = (
        f"<div class='a-sub-split'>공제 +{pm2_cr:,}원 &nbsp;|&nbsp; <span class='ec-neg-val'>추징 -{pm2_cl:,}원</span></div>"
        if (pm2_cr > 0 and pm2_cl > 0)
        else ""
    )

    st.markdown(
        f"{pm2_req_bar_html}"
        f"<div class='ec-calc-box {pm2_box_cls}'>"
        f"<div class='ec-calc-formula'>"
        f"<div class='f-title'>{pm2_title}</div>"
        f"{pm2_lines_html}"
        f"</div>"
        f"<div class='ec-calc-amount {pm2_amt_cls}'>"
        f"<div class='a-lbl'>{pm2_amt_lbl}</div>"
        f"<div class='a-val {pm2_cls}'>{pm2_val_str}</div>"
        f"{pm2_split_html}"
        f"</div>"
        f"</div>",
        unsafe_allow_html=True,
    )
    for _coh_yr, _pm_cur, _pm_rc, _base_key in (
        (tax_yr - 1, pkg["pm_y1"], pkg["pm_y1_recalc"], "base_y1"),
        (tax_yr - 2, pkg["pm_y2"], pkg["pm_y2_recalc"], "base_y2"),
    ):
        if _pm_cur.get("base_missing") and not _pm_rc.get("base_missing"):
            _c_w, _c_b = st.columns([3.8, 2.2])
            with _c_w:
                st.info(
                    f"💡 **2단계 사원표 기준 {_coh_yr}년 귀속분 재계산 값**: "
                    f"상시 **{_pm_rc.get('init_reg', 0):.2f}명** (청년등 **{_pm_rc.get('init_yth', 0):.2f}명**), "
                    f"증가 **+{_pm_rc.get('init_yth_inc', 0) + _pm_rc.get('init_gen_inc', 0):.2f}명** → "
                    f"사후관리 **{_pm_rc.get('case_code')}** "
                    f"(공제 **+{_pm_rc.get('continued_credit_won', 0):,}원** / 추징 **-{_pm_rc.get('clawback_net_payable_won', 0):,}원**)"
                )
            with _c_b:
                if st.button(
                    f"🔄 {_coh_yr}년 사원표 재계산 값을 기신고 기초값에 바로 반영",
                    type="primary",
                    use_container_width=True,
                    key=f"btn_quick_fill_{_coh_yr}_{tax_yr}",
                ):
                    _fd = ps.setdefault(str(_coh_yr), {})
                    _brc = (pkg.get(_base_key) or {}).get("recalc") or {}
                    if _brc.get("init_reg") is not None:
                        _fd["상시"] = float(_brc["init_reg"])
                    if _brc.get("init_yth") is not None:
                        _fd["청년등"] = float(_brc["init_yth"])
                    if _brc.get("init_yth_inc") is not None:
                        _fd["청년등_증가"] = float(_brc["init_yth_inc"])
                    if _brc.get("init_gen_inc") is not None:
                        _fd["청년등외_증가"] = float(_brc["init_gen_inc"])
                    if _fd.get("공제세액") is None:
                        _rc_rates = H.get_unit_rates(corp_size, _cohort_capital(s, _coh_yr, is_capital), scheme="legacy", retention_year=1)
                        _fd["공제세액"] = int(
                            round(
                                (float(_fd.get("청년등_증가") or 0.0) * _rc_rates["청년등"]
                                 + float(_fd.get("청년등외_증가") or 0.0) * _rc_rates["청년등외"]) * 10_000
                            )
                        )
                    s["fill_ver"] = int(s.get("fill_ver", 0)) + 1
                    _save_ec_to_disk(s)
                    st.rerun()

    # 추가공제(육아휴직복귀/정규직전환) 또는 농특세가 있는 경우 요약 안내
    if pkg["additional_credit_won"] > 0 or pkg["additional_clawback_won"] > 0 or pkg["rural_special_tax_won"] > 0:
        add_net = pkg["additional_credit_won"] - pkg["additional_clawback_won"]
        add_box_cls = "neg-box" if add_net < 0 else ("pos-box" if add_net > 0 else "zero-box")
        add_amt_cls = "neg-amt" if add_net < 0 else ("pos-amt" if add_net > 0 else "")
        st.markdown(
            f"<div class='ec-sub-header'><span class='ec-sub-num'>(5)</span><span>추가공제(육아휴직 복귀·정규직 전환) 및 농어촌특별세(20%) 요약</span></div>"
            f"<div class='ec-calc-box {add_box_cls}'>"
            f"<div class='ec-calc-formula'>"
            f"<div class='f-line'>• 육아휴직 복귀·정규직 전환 추가공제: <b>+{pkg['additional_credit_won']:,}원</b> / "
            f"2년 내 퇴직 추가납부: <span class='ec-neg-val'>-{pkg['additional_clawback_won']:,}원</span></div>"
            f"<div class='f-line'>• 농어촌특별세(실공제세액 {pkg['actual_deducted_credit_won']:,}원의 20%): "
            f"<span class='ec-neg-val'>-{pkg['rural_special_tax_won']:,}원</span> "
            f"(농특세 차감 후 실질 세후 혜택: <b>{pkg['net_after_rural_tax_won']:+,}원</b>)</div>"
            f"</div>"
            f"<div class='ec-calc-amount {add_amt_cls}'>"
            f"<div class='a-lbl'>추가공제 순세액</div>"
            f"<div class='a-val {'neg' if add_net < 0 else 'pos'}'>"
            f"{f'-{abs(add_net):,}원' if add_net < 0 else f'{add_net:,}원'}</div>"
            f"</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

    # ══════════════════════════════════════════════════════════════
    # [보조 설정] 기신고 기초값 수기 입력 및 추가공제 옵션 (접이식 Expander)
    # ══════════════════════════════════════════════════════════════
    fill_ver = int(s.get("fill_ver", 0))
    kver = (abs(hash(str(s.get("built_sig")))) + fill_ver) % 100000
    rates_legacy = H.get_unit_rates(corp_size, is_capital, scheme="legacy", retention_year=1)

    def _num_in(col, label, cur, key, step=0.01, is_won=False, help_txt=None):
        if is_won:
            v = None if cur in (None, "") else int(float(cur))
            return col.number_input(
                label, min_value=0, value=v, step=100_000, placeholder="기신고 금액", key=key, help=help_txt
            )
        v = None if cur in (None, "") else float(cur)
        return col.number_input(
            label, min_value=0.0, value=v, step=step, format="%.2f", placeholder="기신고 숫자", key=key, help=help_txt
        )

    with st.expander(
        f"⚙️ 기신고 서식 숫자 직접 입력·보정 ({tax_yr-1}년 · {tax_yr-2}년 귀속분 — 『📋 기신고 서식 숫자 기준』 선택 시 사용)",
        expanded=(active_pm_basis == R.PM_BASIS_FILED and not has_any_manual_ps),
    ):
        c_cap, c_btn = st.columns([4.2, 1.8])
        with c_cap:
            st.caption(
                "기신고 상시근로자 명세서·공제감면세액계산서 숫자가 사원표 재계산 값과 다를 때 입력합니다. "
                "각 칸 이름 옆 괄호는 2단계 사원표로 계산한 『세법원칙 기준』 값입니다."
            )
        with c_btn:
            if st.button(
                "🔄 2단계 사원표 재계산 값으로 빈칸 자동 채우기",
                use_container_width=True,
                key=f"btn_fill_from_recalc_{tax_yr}",
            ):
                for cohort, t_init, t_before in (
                    (tax_yr - 1, prev_t, prev2_t),
                    (tax_yr - 2, prev2_t, totals_all.get(tax_yr - 3, {})),
                ):
                    f_d = ps.setdefault(str(cohort), {})
                    has_init = bool(t_init.get("has_data")) and not t_init.get("from_filed")
                    has_before = bool(t_before.get("has_data")) and not t_before.get("from_filed")
                    if has_init:
                        if f_d.get("상시") is None:
                            f_d["상시"] = float(t_init.get("상시_평균", 0.0))
                        if f_d.get("청년등") is None:
                            f_d["청년등"] = float(t_init.get("청년등_평균", 0.0))
                        if f_d.get("상시_총인원") is None:
                            f_d["상시_총인원"] = float(t_init.get("상시_합계", 0.0))
                        if f_d.get("청년등_총인원") is None:
                            f_d["청년등_총인원"] = float(t_init.get("청년등_합계", 0.0))
                    if has_init and has_before:
                        inc_c = H.calc_increase_with_cap(
                            t_init["상시_평균"], t_init["청년등_평균"], t_before["상시_평균"], t_before["청년등_평균"]
                        )
                        if f_d.get("청년등_증가") is None:
                            f_d["청년등_증가"] = float(inc_c["youth_inc"])
                        if f_d.get("청년등외_증가") is None:
                            f_d["청년등외_증가"] = float(inc_c["non_youth_inc"])
                        r_coh = H.get_unit_rates(corp_size, _cohort_capital(s, cohort, is_capital), scheme="legacy", retention_year=1)
                        c1_est = int(
                            round(
                                (inc_c["youth_inc"] * r_coh["청년등"] + inc_c["non_youth_inc"] * r_coh["청년등외"])
                                * 10_000
                            )
                        )
                        if f_d.get("공제세액") is None:
                            f_d["공제세액"] = c1_est
                        if cohort == tax_yr - 2 and f_d.get("2차_공제세액") is None and corp_size not in ("일반기업", "대기업"):
                            if not (prev_t.get("has_data") and float(prev_t.get("b2_reg", 0.0)) < float(t_init.get("상시_평균", 0.0))):
                                f_d["2차_공제세액"] = c1_est
                s["fill_ver"] = fill_ver + 1
                _save_ec_to_disk(s)
                st.rerun()

        col_y1, col_y2 = st.columns(2)
        for col, cohort, step_lbl, t_init, t_before in (
            (col_y1, tax_yr - 1, "1차 사후관리 (2차년도)", prev_t, prev2_t),
            (col_y2, tax_yr - 2, "2차 사후관리 (3차년도)", prev2_t, totals_all.get(tax_yr - 3, {})),
        ):
            f = ps.setdefault(str(cohort), {})
            has_init = bool(t_init.get("has_data")) and not t_init.get("from_filed")
            has_before = bool(t_before.get("has_data")) and not t_before.get("from_filed")
            inc_r = (
                H.calc_increase_with_cap(
                    t_init["상시_평균"], t_init["청년등_평균"], t_before["상시_평균"], t_before["청년등_평균"]
                )
                if (has_init and has_before)
                else None
            )
            r_reg = f"{t_init['상시_평균']:.2f}" if has_init else "-"
            r_yth = f"{t_init['청년등_평균']:.2f}" if has_init else "-"
            r_rtot = f"{t_init['상시_합계']:g}" if has_init else "-"
            r_ytot = f"{t_init['청년등_합계']:g}" if has_init else "-"
            r_yi = f"{inc_r['youth_inc']:.2f}" if inc_r else "-"
            r_gi = f"{inc_r['non_youth_inc']:.2f}" if inc_r else "-"

            with col:
                st.markdown(f"**📋 {cohort}년 귀속 기신고분 ({step_lbl})**")
                a, b_ = st.columns(2)
                f["상시_총인원"] = _num_in(
                    a, f"{cohort}년 상시 연인원 합계 (재계산: {r_rtot})", f.get("상시_총인원"), f"pf_{cohort}_rtot_{kver}", step=1.0
                )
                f["청년등_총인원"] = _num_in(
                    b_, f"{cohort}년 청년등 연인원 합계 (재계산: {r_ytot})", f.get("청년등_총인원"), f"pf_{cohort}_ytot_{kver}", step=1.0
                )
                f["상시"] = _num_in(
                    a, f"{cohort}년 상시 평균인원 (재계산: {r_reg})", f.get("상시"), f"pf_{cohort}_reg_{kver}"
                )
                f["청년등"] = _num_in(
                    b_, f"{cohort}년 청년등 평균인원 (재계산: {r_yth})", f.get("청년등"), f"pf_{cohort}_yth_{kver}"
                )
                f["청년등_증가"] = _num_in(
                    a, f"{cohort}년 공제 청년등 증가 (재계산: {r_yi})", f.get("청년등_증가"), f"pf_{cohort}_yi_{kver}"
                )
                f["청년등외_증가"] = _num_in(
                    b_, f"{cohort}년 공제 청년등외 증가 (재계산: {r_gi})", f.get("청년등외_증가"), f"pf_{cohort}_gi_{kver}"
                )
                if cohort == tax_yr - 1:
                    f["공제세액"] = _num_in(
                        a, f"{cohort}년 최초 공제세액(원, 추가납부 한도)", f.get("공제세액"), f"pf_{cohort}_clm_{kver}", is_won=True
                    )
                else:
                    f["공제세액"] = _num_in(
                        a,
                        f"{cohort}년 최초 공제세액(1차년도, 원)",
                        f.get("공제세액"),
                        f"pf_{cohort}_clm_{kver}",
                        is_won=True,
                        help_txt="2년차 추가납부 한도는 이 금액과 아래 2차 공제세액을 자동으로 더해 계산합니다. 1차년도 금액만 넣으세요.",
                    )
                f["이월세액"] = _num_in(
                    b_, f"{cohort}년분 미공제 이월세액(원)", f.get("이월세액"), f"pf_{cohort}_cf_{kver}", is_won=True
                )
                if cohort == tax_yr - 2:
                    f["2차_공제세액"] = _num_in(
                        a,
                        f"{tax_yr-1}년 신고 시 2차 공제세액(원)",
                        f.get("2차_공제세액"),
                        f"pf_{cohort}_y1c_{kver}",
                        is_won=True,
                        help_txt="0을 넣으면 1년차에 공제가 중단된 것으로 봅니다. 모르면 비워두세요.",
                    )
                    f["기추징세액"] = _num_in(
                        b_,
                        f"{tax_yr-1}년 신고 시 1년차 추가납부액(원)",
                        f.get("기추징세액"),
                        f"pf_{cohort}_paid_{kver}",
                        is_won=True,
                    )
                # 최초공제연도 당시 사업장 소재지: 연속공제·추가납부 단가는 공제받을 당시 소재지 기준
                loc_opts = ["사이드바 소재지와 같음", "수도권", "수도권 밖"]
                cur_loc = f.get("수도권")
                sel = st.selectbox(
                    f"{cohort}년 공제 당시 사업장 소재지",
                    loc_opts,
                    index=0 if cur_loc is None else (1 if cur_loc else 2),
                    key=f"pf_{cohort}_loc_{kver}",
                    help="2·3차년도 연속공제와 추가납부는 최초로 공제받은 해의 단가(수도권 1,450만/850만, 수도권 밖 1,550만/950만)를 씁니다. "
                         "본점을 옮겼다면 공제받을 당시 소재지를 고르세요.",
                )
                new_loc = None if sel == loc_opts[0] else (sel == "수도권")
                if new_loc != cur_loc:
                    f["_소재지_추정"] = False
                f["수도권"] = new_loc
                notes = []
                if f.get("_증가_추정"):
                    st.warning("⚠️ 공제세액을 만드는 증가인원 조합이 여러 개라 그중 하나를 추정했습니다. "
                               "단시간근로자가 있었던 회사는 틀릴 수 있으니 기신고 상시근로자 명세서로 꼭 확인하세요.")
                elif f.get("_증가_역산"):
                    notes.append("증가인원은 기신고 공제세액에서 역산한 값입니다")
                if f.get("_2차_AI판독") and cohort == tax_yr - 2:
                    st.warning("⚠️ 2차 공제세액은 세액공제조정명세서 계산명세(18S)로 확인하지 못해 AI가 읽은 값입니다. "
                               f"{tax_yr-1}년 신고서의 통합고용세액공제 2차 금액과 맞는지 확인하세요.")
                if f.get("_소재지_추정") and new_loc is not None:
                    notes.append(f"소재지는 기신고 공제세액이 {'수도권' if new_loc else '수도권 밖'} 단가와 맞아 자동 선택했습니다")
                if notes:
                    st.caption("ℹ️ " + " · ".join(notes) + ". 다르면 고쳐주세요.")

    with st.expander("➕ 추가공제(육아휴직복귀·정규직전환·출산휴가대체인력) 및 미공제 이월세액 입력", expanded=False):
        ca1, ca2, ca3 = st.columns(3)
        add_in["parental_return_count"] = ca1.number_input(
            "육아휴직 복귀자 수 (명, ~2026년 적용)",
            0,
            500,
            int(add_in.get("parental_return_count") or 0),
            1,
            help="조특법 제29조의8 제2항: 1인당 중소 1,300만원 / 중견 900만원 추가공제 (전체 상시근로자 수 미감소 요건 충족 시)",
        )
        add_in["regular_conversion_count"] = ca2.number_input(
            "정규직 전환자 수 (명, ~2024년 귀속까지만 적용)",
            0,
            500,
            int(add_in.get("regular_conversion_count") or 0),
            1,
            disabled=(tax_yr >= 2025),
            help="정규직 전환 추가공제는 2024년 귀속까지만 적용되며 2025년 이후 귀속분은 일몰 종료되었습니다.",
        )
        add_in["additional_clawback_count"] = ca3.number_input(
            "복귀·전환일로부터 2년 내 퇴직자 수 (추징 대상, 명)",
            0,
            500,
            int(add_in.get("additional_clawback_count") or 0),
            1,
            help="조특법 제29조의8 제4항: 복귀·전환일로부터 2년 내 근로관계 종료 시 기공제 세액 추징",
        )
        cb1, cb2, cb3 = st.columns(3)
        add_in["maternity_replacement_count"] = cb1.number_input(
            f"{tax_yr}년 출산전후휴가 대체인력 연평균 제외인원 (명)",
            0.0,
            100.0,
            float(add_in.get("maternity_replacement_count") or 0.0),
            0.01,
            format="%.2f",
            help="대체인력을 채용한 출산전후휴가자는 추가공제 요건(상시근로자 미감소) 판정 시 당해 상시근로자 수에서 뺍니다. 휴가자의 연평균 인원을 넣으세요.",
        )
        add_in["maternity_prev_count"] = cb2.number_input(
            f"{tax_yr-1}년 출산전후휴가 대체인력 연평균 제외인원 (명)",
            0.0,
            100.0,
            float(add_in.get("maternity_prev_count") or 0.0),
            0.01,
            format="%.2f",
            help="직전연도에 대체인력을 채용한 출산전후휴가자의 연평균 인원입니다.",
        )
        add_in["current_unclaimed_carryforward_won"] = cb3.number_input(
            f"{tax_yr}년 발생 공제세액 중 최저한세 등으로 당해 미공제 이월된 세액 (원)",
            0,
            50_000_000_000,
            int(add_in.get("current_unclaimed_carryforward_won") or 0),
            100_000,
            help="농어촌특별세(20%)는 실제 감면받는 세액(당해 공제액 - 당해 미공제 이월액)에 대해서만 부과됩니다 (농특세법 제5조 제1항).",
        )

    # 사원표 및 기신고 vs 세법원칙 비교표 (상세 대조용 접이식)
    with st.expander("📊 [상세 대조] 2단계 사원표 인원 현황 및 기신고 기준 vs 세법원칙 기준 비교표", expanded=False):
        cur_b2_gen = round(max(0.0, pkg["cur_s"]["b2_reg"] - pkg["cur_s"]["b2_yth"]), 2)
        cur_b3_gen = round(max(0.0, pkg["cur_s"]["b3_reg"] - pkg["cur_s"]["b3_yth"]), 2)
        cur_b2_gtot = round(max(0.0, pkg["cur_s"]["reg_total"] - pkg["cur_s"]["b2_yth_total"]), 2)
        cur_b3_gtot = round(max(0.0, pkg["cur_s"]["reg_total"] - pkg["cur_s"]["b3_yth_total"]), 2)
        cmp_rows = [
            {
                "연도 · 블록 구분": f"① {tax_yr}년 귀속 [{b3_title}]",
                "전체 상시 [총인원 / 평균]": f"{pkg['cur_s']['reg_total']:g}명 / {pkg['cur_s']['regular']:.2f}명",
                "청년등 [총인원 / 평균]": f"{pkg['cur_s']['yth_total']:g}명 / {pkg['cur_s']['youth']:.2f}명",
                "청년등 외 [총인원 / 평균]": f"{pkg['cur_s']['non_youth_total']:g}명 / {pkg['cur_s']['non_youth']:.2f}명",
                "적용 기준 및 비교 안내": f"당해({tax_yr}년) 원천징수부 기준 (÷{pkg['cur_s']['months_in_year']}개월 · 합산 후 절사)",
            },
            {
                "연도 · 블록 구분": f"② {tax_yr}년 귀속 [{b4_title}]",
                "전체 상시 [총인원 / 평균]": f"{pkg['cur_s']['reg_total']:g}명 / {pkg['cur_s']['b2_reg']:.2f}명",
                "청년등 [총인원 / 평균]": f"{pkg['cur_s']['b2_yth_total']:g}명 / {pkg['cur_s']['b2_yth']:.2f}명",
                "청년등 외 [총인원 / 평균]": f"{cur_b2_gtot:g}명 / {cur_b2_gen:.2f}명",
                "적용 기준 및 비교 안내": f"{tax_yr-1}년 입사 청년 연령경과(34세 초과) 간주 특례 반영 (합산 후 절사)",
            },
            {
                "연도 · 블록 구분": f"③ {tax_yr}년 귀속 [{b5_title}]",
                "전체 상시 [총인원 / 평균]": f"{pkg['cur_s']['reg_total']:g}명 / {pkg['cur_s']['b3_reg']:.2f}명",
                "청년등 [총인원 / 평균]": f"{pkg['cur_s']['b3_yth_total']:g}명 / {pkg['cur_s']['b3_yth']:.2f}명",
                "청년등 외 [총인원 / 평균]": f"{cur_b3_gtot:g}명 / {cur_b3_gen:.2f}명",
                "적용 기준 및 비교 안내": f"{tax_yr-2}년 입사 청년 연령경과(34세 초과) 간주 특례 반영 (합산 후 절사)",
            },
        ]
        st.dataframe(pd.DataFrame(cmp_rows), use_container_width=True, hide_index=True)

        pm_cmp_df = pd.DataFrame(
            [
                {
                    "사후관리 구분": f"① {tax_yr-1}년 귀속분 1차 사후관리 (2차년도)",
                    "기신고 기준 [연속공제 / 추징]": f"+{pkg['pm_y1_filed']['continued_credit_won']:,}원 / -{pkg['pm_y1_filed']['clawback_net_payable_won']:,}원",
                    "세법원칙 기준 [연속공제 / 추징]": f"+{pkg['pm_y1_recalc']['continued_credit_won']:,}원 / -{pkg['pm_y1_recalc']['clawback_net_payable_won']:,}원",
                    "현재 선택된 적용 결과": f"{pkg['pm_y1']['case_code']} (+{pkg['pm_y1']['continued_credit_won']:,}원 / -{pkg['pm_y1']['clawback_net_payable_won']:,}원)",
                },
                {
                    "사후관리 구분": f"② {tax_yr-2}년 귀속분 2차 사후관리 (3차년도)",
                    "기신고 기준 [연속공제 / 추징]": f"+{pkg['pm_y2_filed']['continued_credit_won']:,}원 / -{pkg['pm_y2_filed']['clawback_net_payable_won']:,}원",
                    "세법원칙 기준 [연속공제 / 추징]": f"+{pkg['pm_y2_recalc']['continued_credit_won']:,}원 / -{pkg['pm_y2_recalc']['clawback_net_payable_won']:,}원",
                    "현재 선택된 적용 결과": f"{pkg['pm_y2']['case_code']} (+{pkg['pm_y2']['continued_credit_won']:,}원 / -{pkg['pm_y2']['clawback_net_payable_won']:,}원)",
                },
            ]
        )
        st.dataframe(pm_cmp_df, use_container_width=True, hide_index=True)

    # ══════════════════════════════════════════════════════════════
    # [하단] 계산근거 법령조문 바로가기 링크
    # ══════════════════════════════════════════════════════════════
    st.markdown(
        "<div class='ec-law-ref-box'>"
        "<div style='font-weight:900;font-size:1.12rem;color:#1e3a8a;margin-bottom:8px;'>"
        "📚 계산근거 관련 법령조문 (국가법령정보센터 바로가기)"
        "</div>"
        "• <a href='https://www.law.go.kr/법령/조세특례제한법/제29조의8' target='_blank'>"
        "조세특례제한법 제29조의8 (통합고용세액공제)</a> — "
        "제1항(고용증가 세액공제 및 연차별 공제단가), 제2항(육아휴직 복귀자·정규직 전환자 추가공제), "
        "제3항(고용유지 연속공제 및 인원 감소 시 추가납부세액)<br>"
        "• <a href='https://www.law.go.kr/법령/조세특례제한법시행령/제26조의8' target='_blank'>"
        "조세특례제한법 시행령 제26조의8 (통합고용세액공제 상시근로자 범위·사후관리 산식)</a> — "
        "제2항·제3항(청년등 상시근로자 범위 및 전체 증가한도 Cap), 제5항(사후관리 시 청년등 연령경과 간주 특례), "
        "제6항·제7항(인원 감소 시 추가납부세액 산식), 제9항(소수점 둘째 자리 절사), 제10항(포괄양수·고용승계 특례)<br>"
        "• <a href='https://www.law.go.kr/법령/조세특례제한법시행규칙/제14조의2' target='_blank'>"
        "조세특례제한법 시행규칙 제14조의2 및 별지 제10호의4 서식 (통합고용세액공제 상시근로자 명세서)</a> &nbsp;|&nbsp; "
        "<a href='https://www.law.go.kr/법령/농어촌특별세법/제5조' target='_blank'>"
        "농어촌특별세법 제5조 제1항 (감면세액의 20% 과세)</a>"
        "</div>",
        unsafe_allow_html=True,
    )

    _save_ec_to_disk(s)
    corp_nm_fn = re.sub(r'[\\/:*?"<>|\s]+', "_", str((b.get("상호") or "사업장")).strip())[:30]
    st.markdown("<div class='ec-nav-divider'></div>", unsafe_allow_html=True)
    c_prev, _, c_pdf3, c_next = st.columns([1.2, 3.45, 1.25, 1.3])
    if c_prev.button("< 이전", use_container_width=True, key="btn_step3_prev"):
        s["step"] = 2
        _trigger_scroll_to_top(s)
        _save_ec_to_disk(s)
        st.rerun()
    with c_pdf3:
        with st.container(key="ec_btn_pdf_step3_wrap"):
            st.download_button(
                "📕 PDF 출력",
                data=_build_step3_calculation_pdf_bytes(s, pkg, matrix_cols),
                file_name=f"{corp_nm_fn}_{tax_yr}년귀속_통합고용세액공제_계산서.pdf",
                mime="application/pdf",
                use_container_width=True,
                key="dl_pdf_step3_calc",
                help="3단계 연도별 세액공제 요약표 및 (1)~(4) 상세 계산 산식을 A4 PDF로 즉시 다운로드합니다.",
            )
    if c_next.button("다음(4단계)", type="primary", use_container_width=True, key="btn_step3_next"):
        s["step"] = 4
        s["max_step_reached"] = max(int(s.get("max_step_reached") or 1), 4)
        _trigger_scroll_to_top(s)
        _save_ec_to_disk(s)
        st.rerun()


# ══════════════════════════════════════════════════════════════════
# 7. 4단계: 자율 에이전트AI 스타일 세무검토 보고서 (대·중·소제목 위계 · 무아이콘 · 심층진단 자동생성 · PDF 출력)
# ══════════════════════════════════════════════════════════════════
_REPORT_EMOJI_RE = re.compile(
    r"[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F]|👑|🔍|🛡️|📋|⚠️|📑|📊|💡|🚨|💰|✅|❌|⚖️|🔄|➕|🏢|📅|📌|🧮|💾|📥|📕|🔘|🌱|🟦|🟧|🔧|✏️|🔒"
)


def _strip_all_emojis(text: str) -> str:
    """보고서 본문 및 기존 캐시된 AI 코멘트에서 아이콘·이모지를 모두 제거합니다."""
    if not text:
        return ""
    return _REPORT_EMOJI_RE.sub("", str(text))


def _sanitize_markdown_tilde(text: str) -> str:
    """
    마크다운(GFM)에서 `10~12월 ... 10~12월`처럼 한 문단에 물결표(`~`)가 두 번 이상 들어가면
    사이에 있는 문장 전체가 취소선(`<del>...</del>`)으로 렌더링되고 물결표가 사라져 `1012월`로 깨지는 문제를 방지합니다.
    반각 물결표(`~`)를 취소선 문법으로 인식되지 않는 유니코드 물결표(`∼`, U+223C)로 변환합니다.
    """
    if not text:
        return ""
    s = str(text)
    s = re.sub(r"~~+", "∼", s)
    s = s.replace("~", "∼")
    s = re.sub(r"\b(1[0-2]|[1-9])12월", r"\1∼12월", s)
    return s


def _parse_and_clean_pro_audit(raw_comment: str) -> tuple[str, str]:
    """
    저장된 `pro_audit_comment`에서:
    1) 적용 모델명(`model_id`)을 분리해 반환하고,
    2) 본문 내 이모지(왕관·돋보기·방패·문서 등)와 상단 `[Pro/Argon 심층 진단 완료 — 적용 모델: ...]` 배너 줄을 제거하며,
    3) `- **추가 절세 가능성 발굴**`, `1. **추가 절세...**`, `#### (1) ...` 등 모든 변형 패턴을
       깔끔한 `### (1) 제목` 소제목 + 1단 불릿(`- **핵심키워드**: 설명`)으로 정규화하고,
    4) 반각 물결표(`~`)로 인한 마크다운 취소선(`선 그어짐`) 현상을 원천 차단합니다.
    반환: (clean_body_markdown, model_name)
    """
    if not raw_comment or not str(raw_comment).strip():
        return "", ""

    txt = _sanitize_markdown_tilde(str(raw_comment).strip())
    model_name = ""
    m_mod = re.search(r"적용\s*모델\s*[:：]\s*`?([^\]\n`]+)`?", txt)
    if m_mod:
        model_name = m_mod.group(1).strip()

    cleaned_lines: list[str] = []
    sub_idx = 0
    for raw_ln in txt.splitlines():
        s_ln = raw_ln.strip()
        if "적용 모델:" in s_ln or "적용모델:" in s_ln or "심층 진단 완료" in s_ln:
            continue
        no_icon = _strip_all_emojis(raw_ln).rstrip()
        s_no_icon = no_icon.strip()
        if not s_no_icon:
            cleaned_lines.append("")
            continue

        # 패턴 A: 이미 ### 또는 #### 소제목인 경우
        if s_no_icon.startswith("### ") or s_no_icon.startswith("#### "):
            hdr_t = re.sub(r"^#{3,4}\s*", "", s_no_icon).strip()
            hdr_t = re.sub(r"^\*\*(.+?)\*\*$", r"\1", hdr_t).strip()
            if not re.match(r"^\(\d+\)", hdr_t):
                sub_idx += 1
                hdr_t = f"({sub_idx}) {hdr_t}"
            cleaned_lines.append("")
            cleaned_lines.append(f"### {hdr_t}")
            continue

        # 패턴 B: 번호형 소제목 (`1. **추가 절세...**` 또는 `(1) **추가 절세...**`)
        m_num_hdr = re.match(r"^(?:[-*•]\s*)?(?:(\d)\.|\((\d)\))\s*\*\*([^*]+)\*\*\s*(.*)$", s_no_icon)
        if m_num_hdr:
            num_d = m_num_hdr.group(1) or m_num_hdr.group(2)
            sub_idx = int(num_d)
            title_part = m_num_hdr.group(3).strip()
            rest_part = m_num_hdr.group(4).strip()
            cleaned_lines.append("")
            cleaned_lines.append(f"### ({num_d}) {title_part}")
            if rest_part:
                cleaned_lines.append(f"- {rest_part.lstrip(':- ')}")
            continue

        # 패턴 C: 불릿 단독 볼드 소제목 (`- **추가 절세 가능성 발굴**` — 뒤에 콜론 설명이 없는 줄)
        m_bullet_hdr = re.match(r"^(?:[-*•])\s*\*\*([^*:：]{3,40})\*\*\s*$", s_no_icon)
        if m_bullet_hdr:
            sub_idx += 1
            title_part = m_bullet_hdr.group(1).strip()
            cleaned_lines.append("")
            cleaned_lines.append(f"### ({sub_idx}) {title_part}")
            continue

        # 패턴 D: 들여쓰기된 2단 불릿(`  - ...` 또는 `  * ...`)을 깔끔한 1단 불릿(`- ...`)으로 평탄화
        if re.match(r"^\s+[-*•]\s+", no_icon):
            cleaned_lines.append("- " + re.sub(r"^\s+[-*•]\s+", "", no_icon).strip())
            continue

        cleaned_lines.append(s_no_icon)

    body = "\n".join(cleaned_lines).strip()
    return body, model_name


def _ensure_auto_pro_audit_comment(s: dict, log_tokens_fn=None, room_key: str = "") -> tuple[str, str]:
    """
    4단계 진입 시 버튼 클릭 없이도 『Ⅳ. 심층 세무진단 의견』이 항상 자동으로 생성·표시되도록 보장합니다.
    """
    _ensure_built_for_tax_year(s)
    tax_yr = int(s["tax_year"])
    shown_years = _years(s)
    cur_sig = f"{s.get('built_sig')}|{tax_yr}|{s.get('pm_basis')}"

    existing_raw = str(s.get("pro_audit_comment") or "").strip()
    if existing_raw and not existing_raw.startswith("❌") and s.get("pro_audit_sig") == cur_sig:
        body, mod_nm = _parse_and_clean_pro_audit(existing_raw)
        if body:
            if not mod_nm:
                mod_nm = str(s.get("pro_audit_model") or "gemini-2.5-pro")
            s["pro_audit_model"] = mod_nm
            return body, mod_nm

    if existing_raw and not existing_raw.startswith("❌") and not s.get("pro_audit_sig"):
        body, mod_nm = _parse_and_clean_pro_audit(existing_raw)
        if body:
            if not mod_nm:
                mod_nm = str(s.get("pro_audit_model") or "gemini-2.5-pro")
            s["pro_audit_model"] = mod_nm
            s["pro_audit_sig"] = cur_sig
            return body, mod_nm

    computed_all, totals_all, ctx_all = {}, {}, {}
    for y in shown_years:
        _, comp_y, tot_y = _build_year_rows(s, y)
        computed_all[y] = comp_y
        totals_all[y] = tot_y
        ctx_all[y] = _ctx(s, y)

    prev = ((s.get("ext") or {}).get("prev_filing") or {}).get("연도별")
    review_items = H.review(
        s["people"],
        s["year_recs"],
        shown_years,
        ctx_all,
        computed_all,
        prev,
        sub_biz_list=s.get("sub_biz_list"),
    )
    audit_payload = {
        "귀속연도": tax_yr,
        "사업자정보": s.get("biz"),
        "합산사업장": s.get("sub_biz_list"),
        "연도별_요약": {
            str(y): {
                "상시_평균": t.get("b1_reg"),
                "청년등_평균": t.get("b1_yth"),
                "1차사후_청년등": t.get("b2_yth"),
                "2차사후_청년등": t.get("b3_yth"),
            }
            for y, t in totals_all.items()
        },
        "결정론적_검토항목": [{"구분": lv, "내용": _strip_all_emojis(msg)} for lv, msg in review_items],
    }

    raw_generated = P.call_pro_argon_audit_commentary(
        audit_payload, log_tokens_fn=log_tokens_fn, room_key=room_key
    )
    body, mod_nm = _parse_and_clean_pro_audit(raw_generated)
    if not mod_nm:
        mod_nm = "gemini-2.5-pro"
    s["pro_audit_comment"] = raw_generated
    s["pro_audit_model"] = mod_nm
    s["pro_audit_sig"] = cur_sig
    _save_ec_to_disk(s)
    return body, mod_nm


def _build_report_markdown(s: dict, log_tokens_fn=None, room_key: str = "") -> str:
    """
    [4단계 보고서 마크다운 생성 — 고가독성 표·목록 위계 · 무아이콘 · Ⅳ. 심층 세무진단 의견 상시 포함]
    - 마크다운 표 앞에는 반드시 빈 줄(`""`)을 두어 표가 텍스트로 깨지지 않고 100% 정식 표로 렌더링되게 합니다.
    - Ⅰ-(1) 사업자 기본사항도 한눈에 들어오는 4열 요약표로 구성합니다.
    """
    _ensure_built_for_tax_year(s)
    b = s.get("biz") or {}
    sub_list = s.get("sub_biz_list") or []
    tax_yr = int(s.get("tax_year") or R.DEFAULT_TAX_YEAR)
    corp_nm = (b.get("상호") or "").strip()
    biz_no = (b.get("사업자번호") or "").strip()
    if corp_nm and biz_no:
        corp_disp = f"**{corp_nm}** ({biz_no})"
    elif corp_nm:
        corp_disp = f"**{corp_nm}**"
    elif biz_no:
        corp_disp = biz_no
    else:
        corp_disp = ""

    corp_sz = b.get("기업구분", "중소기업")
    cap_bool = H.is_capital_area(b.get("사업장소재지", ""))
    is_capital = True if cap_bool is None else bool(cap_bool)
    loc_label = "수도권" if is_capital else "수도권 외(비수도권)"
    addr_str = (b.get("사업장소재지") or "").strip()
    size_loc_disp = f"**{corp_sz} · {loc_label}** ({addr_str})" if addr_str else f"**{corp_sz} · {loc_label}**"

    uptae_val = (b.get("업태") or "").strip()
    jongmok_val = (b.get("종목") or "").strip()
    open_dt_val = (b.get("설립일") or "").strip()
    uj_part = " · ".join([x for x in (uptae_val, jongmok_val) if x])
    if uj_part and open_dt_val:
        uptae_disp = f"{uj_part} (설립·개업일: {open_dt_val})"
    elif uj_part:
        uptae_disp = uj_part
    elif open_dt_val:
        uptae_disp = f"설립·개업일: {open_dt_val}"
    else:
        uptae_disp = ""

    totals_all = _ensure_totals_snapshot(s)
    ps = s.get("prev_summary") or {}
    p1 = ps.get(str(tax_yr - 1)) or {}
    p2 = ps.get(str(tax_yr - 2)) or {}
    active_pm_basis = s.get("pm_basis", R.PM_BASIS_FILED)

    pkg = H.calculate_tax_year_package(
        tax_year=tax_yr,
        corp_size=corp_sz,
        is_capital=is_capital,
        summaries=totals_all,
        prior_filings={
            cohort: {
                "init_reg": f.get("상시"),
                "init_yth": f.get("청년등"),
                "init_yth_inc": f.get("청년등_증가"),
                "init_gen_inc": f.get("청년등외_증가"),
                "claimed_won": f.get("공제세액"),
                "carryforward_won": f.get("이월세액"),
                "y1_continued_won": f.get("2차_공제세액") if cohort == tax_yr - 2 else None,
                "prior_clawback_paid_won": f.get("기추징세액") if cohort == tax_yr - 2 else None,
                "is_capital": f.get("수도권"),
            }
            for cohort, f in ((tax_yr - 1, p1), (tax_yr - 2, p2))
        },
        additional_inputs=s.get("additional_inputs"),
        scheme_2026=s.get("scheme_2026", "new_2026"),
        pm_basis=active_pm_basis,
    )
    s["calc_pkg"] = pkg

    matrix_cols = _compute_historical_matrix_columns(
        s=s,
        tax_yr=tax_yr,
        corp_size=corp_sz,
        is_capital=is_capital,
        totals_all=totals_all,
        ps=ps,
        pkg_cur=pkg,
        active_pm_basis=active_pm_basis,
    )

    pm1 = pkg["pm_y1"]
    pm2 = pkg["pm_y2"]
    cur_s = pkg["cur_s"]
    prev_s = pkg["prev_s"]
    cur_inc = pkg["cur_inc"]
    basis_lbl = pkg.get("pm_basis_label", "기신고 기준")
    b3_title, b4_title, b5_title = _block_titles_for_year(tax_yr, two_line=False)

    sub_biz_lines = []
    for idx, sb in enumerate(sub_list, start=2):
        sb_nm = sb.get("상호") or f"제{idx}사업장"
        sb_no = sb.get("사업자번호") or "-"
        sb_addr = sb.get("사업장소재지") or "-"
        sb_tp = sb.get("구분") or "합산사업장"
        suc_info = ""
        if float(sb.get("승계_직전상시") or 0.0) > 0:
            suc_info = f" / 피승계 직전상시 {float(sb.get('승계_직전상시')):.2f}명(청년등 {float(sb.get('승계_직전청년') or 0.0):.2f}명) 합산 [각주 6]"
        sub_biz_lines.append(
            f"- **합산 제{idx}사업장 ({sb_tp})**: {sb_nm} (사업자등록번호: {sb_no} / 소재지: {sb_addr}{suc_info})"
        )

    yr_list = [tax_yr - 3, tax_yr - 2, tax_yr - 1, tax_yr]

    def _m_txt(cr: int, cl: int) -> str:
        cr_i, cl_i = int(cr or 0), int(cl or 0)
        if cr_i > 0 and cl_i > 0:
            return f"+{cr_i:,}원 / (-){cl_i:,}원"
        if cl_i > 0:
            return f"**-{cl_i:,}원**"
        if cr_i < 0:
            return f"**-{abs(cr_i):,}원**"
        return f"{cr_i:,}원"

    if pkg["active_scheme"] == "new_2026":
        r_y1 = pkg["rates_new_y1"]
        yu, gu = r_y1["청년등"] * 10_000, r_y1["청년등외"] * 10_000
        scheme_desc = "2026년 개편 신법(연차별 차등 인센티브 1년차 단가) [각주 1]"
    else:
        r_leg = pkg["rates_legacy"]
        yu, gu = r_leg["청년등"] * 10_000, r_leg["청년등외"] * 10_000
        scheme_desc = "조세특례제한법 제29조의8 제1항 기본공제 단가 [각주 1]"

    pm1_reg_dec = "여(감소)" if (pm1.get("active") and not pm1.get("base_missing") and cur_s["b2_reg"] < pm1.get("init_reg", 0)) else "부(유지·증가)"
    pm1_yth_dec = "여(감소)" if (pm1.get("active") and not pm1.get("base_missing") and cur_s["b2_yth"] < pm1.get("init_yth", 0)) else "부(유지·증가)"
    pm2_reg_dec = "여(감소)" if (pm2.get("active") and not pm2.get("base_missing") and cur_s["b3_reg"] < pm2.get("init_reg", 0)) else "부(유지·증가)"
    pm2_yth_dec = "여(감소)" if (pm2.get("active") and not pm2.get("base_missing") and cur_s["b3_yth"] < pm2.get("init_yth", 0)) else "부(유지·증가)"

    audit_body, _ = _ensure_auto_pro_audit_comment(s, log_tokens_fn=log_tokens_fn, room_key=room_key)

    lines = [
        f"# {tax_yr}년 귀속 통합고용세액공제 및 사후관리 검토보고서",
        "",
        "## Ⅰ. 사업자 기본사항 및 최종 세액 요약",
        "### (1) 사업자 기본사항",
        "",
        "| 항목 | 내용 | 항목 | 내용 |",
        "| :--- | :--- | :--- | :--- |",
        f"| **상호(법인명)** | {corp_disp} | **기업규모 · 소재지** | {size_loc_disp} |",
        f"| **업태 · 종목** | {uptae_disp} | **과세기간 월수** | 당해({tax_yr}년) {b.get('당해_월수', 12)}개월 / 직전({tax_yr-1}년) {b.get('전년_월수', 12)}개월 |",
        f"| **사후관리 산정 기준** | **{basis_lbl}** | **적용 공제단가 체계** | {scheme_desc} |",
        "",
        *sub_biz_lines,
        "",
        f"### (2) {tax_yr}년 귀속 최종 공제세액 및 추가납부세액 요약 [{basis_lbl}]",
        "",
        "| 구분 | 금액 (원) | 산출 내역 및 법령 근거 |",
        "| :--- | ---: | :--- |",
        f"| **1. 당해({tax_yr}년) 1차년도 신규 고용증가 세액공제** | **{pkg['cur_base_credit_won']:,}원** | 청년등 +{pkg['cur_inc']['youth_inc']:.2f}명, 청년등 외 +{pkg['cur_inc']['non_youth_inc']:.2f}명 (조특법 제29조의8 제1항 [각주 1]) |",
        f"| **2. 직전·전전연도({tax_yr-1}·{tax_yr-2}년) 기공제분 연속공제액** | **{pkg['total_continued_credit_won']:,}원** | 2차년도 {pm1['continued_credit_won']:,}원 + 3차년도 {pm2['continued_credit_won']:,}원 (조특법 제29조의8 제3항 [각주 3]) |",
        f"| **3. 육아휴직 복귀 및 정규직 전환 추가공제액** | **{pkg['additional_credit_won']:,}원** | 복귀 {pkg['parental_ret_cnt']}명 / 전환 {pkg['reg_conv_cnt']}명 (조특법 제29조의8 제2항) |",
        f"| **합계: 당해 총 공제세액 (1+2+3)** | **{pkg['total_credit_gross_won']:,}원** | **공제감면세액계산서 및 세액공제신청서 반영 금액** |",
        f"| **4. 사후관리 추가납부세액 (이월공제 차감 후)** | **{pkg['total_clawback_net_payable_won']:,}원** | 차감전 추징액 {pkg['total_clawback_gross_won']:,}원 − 미공제 이월세액 소멸 {pkg['total_carryforward_offset_won']:,}원 [각주 4, 5] |",
        f"| **5. 농어촌특별세 (실공제세액의 20%)** | **{pkg['rural_special_tax_won']:,}원** | 실공제 {pkg['actual_deducted_credit_won']:,}원 기준 (농어촌특별세법 제5조 제1항 [각주 7]) |",
        f"| **최종 실질 순절세액 (합계 − 4 − 5)** | **{pkg['net_after_rural_tax_won']:,}원** | **당해 최저한세 등 미공제 이월액 {pkg['cur_unclaimed_cf_won']:,}원 반영** |",
        "",
        f"### (3) 4개 과세연도({tax_yr-3}~{tax_yr}년) 세액공제 및 추가납부세액 총괄표",
        "",
        f"| 구분 | 차수 | {yr_list[0]}년 | {yr_list[1]}년 | {yr_list[2]}년 | {yr_list[3]}년 (당해 귀속) | 근거 법령 |",
        "| :---: | :---: | ---: | ---: | ---: | ---: | :--- |",
        f"| **세액공제액 (추가납부액)** | **1차** | {_m_txt(matrix_cols[yr_list[0]]['r1_credit'], matrix_cols[yr_list[0]]['r1_claw'])} | {_m_txt(matrix_cols[yr_list[1]]['r1_credit'], matrix_cols[yr_list[1]]['r1_claw'])} | {_m_txt(matrix_cols[yr_list[2]]['r1_credit'], matrix_cols[yr_list[2]]['r1_claw'])} | **{_m_txt(matrix_cols[yr_list[3]]['r1_credit'], matrix_cols[yr_list[3]]['r1_claw'])}** | 조특법 제29조의8 제1항 [각주 1] |",
        f"| **세액공제액 (추가납부액)** | **2차** | {_m_txt(matrix_cols[yr_list[0]]['r2_credit'], matrix_cols[yr_list[0]]['r2_claw'])} | {_m_txt(matrix_cols[yr_list[1]]['r2_credit'], matrix_cols[yr_list[1]]['r2_claw'])} | {_m_txt(matrix_cols[yr_list[2]]['r2_credit'], matrix_cols[yr_list[2]]['r2_claw'])} | **{_m_txt(matrix_cols[yr_list[3]]['r2_credit'], matrix_cols[yr_list[3]]['r2_claw'])}** | 조특법 제29조의8 제3항 [각주 3, 4] |",
        f"| **세액공제액 (추가납부액)** | **3차** | {_m_txt(matrix_cols[yr_list[0]]['r3_credit'], matrix_cols[yr_list[0]]['r3_claw'])} | {_m_txt(matrix_cols[yr_list[1]]['r3_credit'], matrix_cols[yr_list[1]]['r3_claw'])} | {_m_txt(matrix_cols[yr_list[2]]['r3_credit'], matrix_cols[yr_list[2]]['r3_claw'])} | **{_m_txt(matrix_cols[yr_list[3]]['r3_credit'], matrix_cols[yr_list[3]]['r3_claw'])}** | 조특법 제29조의8 제3항 [각주 3, 4] |",
        f"| **합계** | **순액** | **{int(matrix_cols[yr_list[0]]['net_total']):,}원** | **{int(matrix_cols[yr_list[1]]['net_total']):,}원** | **{int(matrix_cols[yr_list[2]]['net_total']):,}원** | **{int(matrix_cols[yr_list[3]]['net_total']):,}원** | 조특법 제144조 [각주 5] |",
        "",
        f"## Ⅱ. {tax_yr}년 귀속 세액공제 및 사후관리 상세 산출근거",
        f"### (1) 평균 상시근로자 증가 인원 및 코호트별 상시근로자 현황 [각주 2, 3]",
        f"- **산정 방법**: 매월 말 현재 상시근로자 수의 연간 합계(연인원)를 해당 과세연도 개월 수({cur_s['months_in_year']}개월)로 나눈 뒤 소수점 셋째 자리에서 버림(100분의 1 미만 절사, 조특령 제26조의8 제9항)하여 산정하였습니다.",
        f"- **청년등 증가인원 한도(Cap)**: 청년등 상시근로자 증가인원(+{cur_inc['youth_inc']:.2f}명)은 전체 상시근로자 증가인원(+{cur_inc['total_inc']:.2f}명)을 한도로 적용하였습니다(조특령 제26조의8 제3항).",
        "",
        "| 구분 | 전체 상시 [총인원 / 평균] | 청년등 [총인원 / 평균] | 청년등 외 [총인원 / 평균] | 산정 기준 및 법령 근거 |",
        "| :--- | ---: | ---: | ---: | :--- |",
        f"| **{tax_yr}년 귀속 [{b3_title}]** | {cur_s['reg_total']:g}명 / **{cur_s['regular']:.2f}명** | {cur_s['yth_total']:g}명 / **{cur_s['youth']:.2f}명** | {cur_s['non_youth_total']:g}명 / **{cur_s['non_youth']:.2f}명** | 근로계약 체결일 현재 연령 기준 (합산 후 절사) [각주 2] |",
        f"| **{tax_yr}년 귀속 [{b4_title}]** | {cur_s['reg_total']:g}명 / **{cur_s['b2_reg']:.2f}명** | {cur_s['b2_yth_total']:g}명 / **{cur_s['b2_yth']:.2f}명** | {round(max(0.0, cur_s['reg_total']-cur_s['b2_yth_total']),2):g}명 / **{round(max(0.0, cur_s['b2_reg']-cur_s['b2_yth']),2):.2f}명** | {tax_yr-1}년 입사 청년 연령경과 간주 특례 [각주 3] |",
        f"| **{tax_yr}년 귀속 [{b5_title}]** | {cur_s['reg_total']:g}명 / **{cur_s['b3_reg']:.2f}명** | {cur_s['b3_yth_total']:g}명 / **{cur_s['b3_yth']:.2f}명** | {round(max(0.0, cur_s['reg_total']-cur_s['b3_yth_total']),2):g}명 / **{round(max(0.0, cur_s['b3_reg']-cur_s['b3_yth']),2):.2f}명** | {tax_yr-2}년 입사 청년 연령경과 간주 특례 [각주 3] |",
        f"| **{tax_yr-1}년 사후관리 기초 ({basis_lbl})** | - / **{pm1['init_reg']:.2f}명** | - / **{pm1['init_yth']:.2f}명** | - / **{round(max(0.0, pm1['init_reg']-pm1['init_yth']),2):.2f}명** | 1차 사후관리 비교 기준 (증가 청년 {pm1['init_yth_inc']:.2f}명 · 일반 {pm1['init_gen_inc']:.2f}명) |",
        f"| **{tax_yr-2}년 사후관리 기초 ({basis_lbl})** | - / **{pm2['init_reg']:.2f}명** | - / **{pm2['init_yth']:.2f}명** | - / **{round(max(0.0, pm2['init_reg']-pm2['init_yth']),2):.2f}명** | 2차 사후관리 비교 기준 (증가 청년 {pm2['init_yth_inc']:.2f}명 · 일반 {pm2['init_gen_inc']:.2f}명) |",
        "",
        f"### (2) 1차년도({tax_yr}년 귀속) 세액공제액 계산 ({corp_sz}, {loc_label}) [각주 1]",
        f"- **적용 단가 근거**: {scheme_desc} — 청년등 1인당 **{yu:,}원**, 청년등 외 1인당 **{gu:,}원**",
        f"- **계산 산식**: (청년등 증가 {cur_inc['youth_inc']:.2f}명 × {yu:,}원) + (청년등 외 증가 {cur_inc['non_youth_inc']:.2f}명 × {gu:,}원)"
        + (f" − 최소고용증가인원 차감 {pkg['cur_new_ded_won']:,}원" if pkg.get("cur_new_ded_won", 0) > 0 else "")
        + f" = **{pkg['cur_base_credit_won']:,}원**",
        "",
        f"### (3) 2차년도 사후관리 계산 ({tax_yr-1}년 귀속분 → {tax_yr}년 1차 사후관리) [각주 3, 4]",
        f"- **감소 여부 판정**: 1차년도({tax_yr-1}년) 대비 전체 상시근로자 감소 여부 **{pm1_reg_dec}** ({pm1.get('init_reg', 0):.2f}명 → {cur_s['b2_reg']:.2f}명) / 청년등 상시근로자 감소 여부 **{pm1_yth_dec}** ({pm1.get('init_yth', 0):.2f}명 → {cur_s['b2_yth']:.2f}명)",
        f"- **산출 내역 ({pm1.get('case_code')})**: {_strip_all_emojis(pm1.get('formula_note', ''))}",
        f"- **산출 세액**: 2차년도 연속공제액 **+{pm1.get('continued_credit_won', 0):,}원** / 1차 사후관리 추가납부세액 **-{pm1.get('clawback_net_payable_won', 0):,}원**",
        "",
        f"### (4) 3차년도 사후관리 계산 ({tax_yr-2}년 귀속분 → {tax_yr}년 2차 사후관리) [각주 3, 4]",
        f"- **감소 여부 판정**: 1차년도({tax_yr-2}년) 대비 전체 상시근로자 감소 여부 **{pm2_reg_dec}** ({pm2.get('init_reg', 0):.2f}명 → {cur_s['b3_reg']:.2f}명) / 청년등 상시근로자 감소 여부 **{pm2_yth_dec}** ({pm2.get('init_yth', 0):.2f}명 → {cur_s['b3_yth']:.2f}명)",
        f"- **산출 내역 ({pm2.get('case_code')})**: {_strip_all_emojis(pm2.get('formula_note', ''))}",
        f"- **산출 세액**: 3차년도 연속공제액 **+{pm2.get('continued_credit_won', 0):,}원** / 2차 사후관리 추가납부세액 **-{pm2.get('clawback_net_payable_won', 0):,}원**",
        "",
        "## Ⅲ. 계산근거 관련 법령 주석",
        "### (1) 기본공제·상시근로자 범위 및 소수점 절사 규정",
        "- **[각주 1] 조세특례제한법 제29조의8 제1항 (통합고용세액공제 기본공제 및 단가)**: 소비성서비스업 등 제외 업종 외의 내국인이 직전 과세연도 대비 상시근로자 수가 증가한 경우, 청년등 상시근로자 증가인원(중소 수도권 1,450만원·비수도권 1,550만원 / 2026 신법은 유지연차별 점증 단가)과 청년등 외 증가인원(중소 수도권 850만원·비수도권 950만원)에 해당 공제단가를 곱한 금액을 소득세 또는 법인세에서 공제한다.",
        "- **[각주 2] 조세특례제한법 시행령 제26조의8 제2항·제3항·제9항 (상시근로자 제외 범위 · 청년등 증가한도 Cap · 소수점 절사)**: 근로계약기간 1년 미만자(2025년 귀속부터 실제 근로기간 1년 미만자 포함), 월평균 60시간 미만 단시간근로자, 법인의 등기임원, 최대주주·최대출자자(개인사업자는 대표자)와 그 배우자·직계존비속·친족은 상시근로자에서 제외한다(제23조 제10항 준용). 청년등 상시근로자(15~34세 청년[병역기간 최대 6년 차감], 60세 이상, 장애인, 경력단절근로자, 북한이탈주민) 증가인원은 **전체 상시근로자 증가인원을 한도(Cap)**로 하며, 상시근로자 수 계산 시 근로자별 계산한 수의 합에서 **100분의 1 미만은 버린다(소수점 둘째 자리 절사, 2026.5.22. 시행령 개정 기준)**.",
        "",
        "### (2) 사후관리·연속공제·추가납부 및 고용승계 특례 규정",
        "- **[각주 3] 조세특례제한법 시행령 제26조의8 제5항 (사후관리·연속공제 시 청년등 연령경과 간주 특례)**: 최초로 공제받은 과세연도에 청년등 상시근로자에 해당하였던 자는 이후 과세연도에 연령 증가로 34세를 초과하더라도, 그 최초 공제연도 분에 대한 2·3차년도 연속공제 및 사후관리(추가납부세액) 상시근로자 수 산정 시에는 계속하여 **청년등 상시근로자로 본다**.",
        "- **[각주 4] 조세특례제한법 제29조의8 제3항 및 시행령 제26조의8 제6항 (고용 감소 시 추가납부세액 산식 및 이자상당가산액 면제)**: 공제를 받은 과세연도 종료일부터 2년(대기업 1년)이 되는 날이 속하는 과세연도 종료일까지 전체 상시근로자 수가 감소한 경우 연속공제를 중단하고 감소 인원분 공제세액을 추가납부하며(Case 1·Case 2), 전체 상시근로자 수는 유지되었으나 청년등 상시근로자 수만 감소한 경우(Case 3)에는 청년등 단가와 일반 단가의 차액(청년단가 − 일반단가)만을 추가납부한다. 이때 기공제받은 세액을 한도로 하며 이자상당가산액은 부과되지 아니한다.",
        "- **[각주 5] 조세특례제한법 제144조 및 기본통칙 (최저한세 등 미공제 이월세액 우선 소멸 특례)**: 사후관리 위반으로 추가납부 사유가 발생하였으나 최저한세 적용 또는 결손금 등으로 인하여 당초 실제로 공제받지 못하고 이월된 세액공제액(이월세액)이 남아 있는 경우, 현금으로 추가납부하는 대신 해당 미공제 이월세액을 먼저 차감(소멸)한다.",
        "- **[각주 6] 조세특례제한법 시행령 제26조의8 제10항 및 제23조 제13항 준용 (포괄양수·합병·분할·법인전환 고용승계 특례)**: 과세연도 중 사업을 포괄양수하거나 합병·분할·현물출자·법인전환에 따라 고용을 승계한 기업의 직전 과세연도 상시근로자 수는 기존 사업장 직전 인원에 승계 사업장 직전 인원을 더한 수로 하고, 당해 과세연도에는 과세연도 개시일에 승계한 것으로 보아 근무기간을 통산한다.",
        "- **[각주 7] 농어촌특별세법 제5조 제1항 제1호 (농어촌특별세 20%)**: 조세특례제한법에 따라 실제로 감면(공제)받는 소득세·법인세 세액(미공제 이월분 제외)의 **100분의 20**을 농어촌특별세로 납부한다.",
        "",
        "## Ⅳ. 심층 세무진단 의견",
        audit_body,
    ]
    return _sanitize_markdown_tilde("\n".join(lines))


def _build_report_pdf_bytes(s: dict, log_tokens_fn=None, room_key: str = "") -> bytes:
    """
    4단계 『보고서 PDF 다운』 전용 빌더:
    - 화면의 대제목 / 중제목(Ⅰ~Ⅳ) / 소제목 / 본문·표를 그대로 A4 세로(Portrait) 정식 PDF로 출력합니다.
    - 모든 그림문자(느낌표·왕관·돋보기 등)를 제거하고, 하단 적용모델 정보는 PDF에서 완전히 제외합니다.
    """
    _ensure_built_for_tax_year(s)
    reg_font, bold_font = _ensure_korean_pdf_font()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=26,
        rightMargin=26,
        topMargin=26,
        bottomMargin=26,
    )
    avail_w = A4[0] - 52

    styles = getSampleStyleSheet()
    st_h1 = ParagraphStyle(
        "ECRepH1",
        parent=styles["Normal"],
        fontName=bold_font,
        fontSize=15.0,
        leading=20.0,
        textColor=colors.HexColor("#0f172a"),
        spaceAfter=6,
    )
    st_meta = ParagraphStyle(
        "ECRepMeta",
        parent=styles["Normal"],
        fontName=reg_font,
        fontSize=9.0,
        leading=13.5,
        textColor=colors.HexColor("#334155"),
        spaceAfter=8,
    )
    st_h2 = ParagraphStyle(
        "ECRepH2",
        parent=styles["Normal"],
        fontName=bold_font,
        fontSize=11.8,
        leading=16.5,
        textColor=colors.HexColor("#1e3a8a"),
        spaceBefore=11,
        spaceAfter=6,
    )
    st_h3 = ParagraphStyle(
        "ECRepH3",
        parent=styles["Normal"],
        fontName=bold_font,
        fontSize=10.2,
        leading=14.5,
        textColor=colors.HexColor("#0f172a"),
        spaceBefore=7,
        spaceAfter=4,
    )
    st_body = ParagraphStyle(
        "ECRepBody",
        parent=styles["Normal"],
        fontName=reg_font,
        fontSize=9.2,
        leading=14.2,
        textColor=colors.HexColor("#1e293b"),
        spaceAfter=3,
    )
    st_tbl_hdr = ParagraphStyle(
        "ECRepTblHdr",
        parent=styles["Normal"],
        fontName=bold_font,
        fontSize=8.3,
        leading=11.2,
        alignment=1,
        textColor=colors.white,
    )
    st_tbl_cell = ParagraphStyle(
        "ECRepTblCell",
        parent=styles["Normal"],
        fontName=reg_font,
        fontSize=8.2,
        leading=11.2,
        textColor=colors.HexColor("#1e293b"),
    )

    md_full = _build_report_markdown(s, log_tokens_fn=log_tokens_fn, room_key=room_key)
    story = []

    lines = md_full.splitlines()
    idx = 0
    while idx < len(lines):
        raw_ln = _strip_all_emojis(lines[idx]).strip()
        if not raw_ln or raw_ln == "---":
            idx += 1
            continue

        # 모델 정보 줄은 PDF에서 완전히 제외
        if "적용 모델:" in raw_ln or "적용모델:" in raw_ln:
            idx += 1
            continue

        # 마크다운 파이프 표 블록 처리
        if raw_ln.startswith("|") and raw_ln.endswith("|"):
            tbl_lines = []
            while idx < len(lines):
                cand = _strip_all_emojis(lines[idx]).strip()
                if cand.startswith("|") and cand.endswith("|"):
                    tbl_lines.append(cand)
                    idx += 1
                else:
                    break
            parsed_rows = []
            for r_i, t_ln in enumerate(tbl_lines):
                cells = [c.strip() for c in t_ln.strip("|").split("|")]
                if all(re.match(r"^[:\-]+$", c.replace(" ", "")) for c in cells if c):
                    continue
                is_hdr = len(parsed_rows) == 0
                row_paras = []
                for c_txt in cells:
                    c_clean = c_txt.replace("<br>", "\n")
                    p_style = st_tbl_hdr if is_hdr else st_tbl_cell
                    row_paras.append(Paragraph(_pdf_text(c_clean).replace("\n", "<br/>"), p_style))
                parsed_rows.append(row_paras)
            if parsed_rows:
                n_cols = len(parsed_rows[0])
                if n_cols == 3:
                    col_w = [avail_w * 0.36, avail_w * 0.20, avail_w * 0.44]
                elif n_cols == 4:
                    col_w = [avail_w * 0.18, avail_w * 0.32, avail_w * 0.18, avail_w * 0.32]
                elif n_cols == 5:
                    col_w = [avail_w * 0.23, avail_w * 0.17, avail_w * 0.17, avail_w * 0.17, avail_w * 0.26]
                elif n_cols == 7:
                    col_w = [avail_w * 0.15, avail_w * 0.07, avail_w * 0.13, avail_w * 0.13, avail_w * 0.13, avail_w * 0.15, avail_w * 0.24]
                else:
                    col_w = [avail_w / n_cols] * n_cols
                t_obj = Table(parsed_rows, colWidths=col_w, repeatRows=1)
                t_obj.setStyle(
                    TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
                            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                            ("GRID", (0, 0), (-1, -1), 0.45, colors.HexColor("#cbd5e1")),
                            ("BOX", (0, 0), (-1, -1), 0.9, colors.HexColor("#1e293b")),
                            ("TOPPADDING", (0, 0), (-1, -1), 4.5),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5),
                            ("LEFTPADDING", (0, 0), (-1, -1), 5),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                        ]
                    )
                )
                story.append(t_obj)
                story.append(Spacer(1, 5))
            continue

        # 대제목 (# )
        if raw_ln.startswith("# "):
            story.append(Paragraph(_pdf_text(raw_ln[2:].strip()), st_h1))
            idx += 1
            continue

        # 중제목 (## )
        if raw_ln.startswith("## "):
            h2_tbl = Table([[Paragraph(_pdf_text(raw_ln[3:].strip()), st_h2)]], colWidths=[avail_w])
            h2_tbl.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#eff6ff")),
                        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#bfdbfe")),
                        ("TOPPADDING", (0, 0), (-1, -1), 4),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                        ("LEFTPADDING", (0, 0), (-1, -1), 8),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ]
                )
            )
            story.append(Spacer(1, 4))
            story.append(h2_tbl)
            story.append(Spacer(1, 3))
            idx += 1
            continue

        # 소제목 (### 또는 #### )
        if raw_ln.startswith("### ") or raw_ln.startswith("#### "):
            sub_txt = re.sub(r"^#{3,4}\s*", "", raw_ln).strip()
            story.append(Paragraph(_pdf_text(f"■ {sub_txt}"), st_h3))
            idx += 1
            continue

        # 인용구 (> )
        if raw_ln.startswith(">"):
            q_txt = raw_ln.lstrip("> ").strip()
            story.append(Paragraph(_pdf_text(q_txt), st_meta))
            idx += 1
            continue

        # 일반 불릿 (- ) 또는 본문
        if raw_ln.startswith("- ") or raw_ln.startswith("* "):
            b_txt = "• " + raw_ln[2:].strip()
            story.append(Paragraph(_pdf_text(b_txt), st_body))
        else:
            story.append(Paragraph(_pdf_text(raw_ln), st_body))
        idx += 1

    doc.build(story)
    return buf.getvalue()


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
        trunc_mode = "합산 후 절사"
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


def _page_report(room_key: str = "", log_tokens_fn=None):
    s = _S()
    _ensure_built_for_tax_year(s)
    tax_yr = int(s["tax_year"])

    # 버튼 클릭 없이도 Ⅳ. 심층 세무진단 의견이 항상 자동 생성·표시되도록 처리
    with st.spinner("보고서 및 심층 세무진단 의견을 구성하고 있습니다..."):
        audit_clean_body, model_used = _ensure_auto_pro_audit_comment(s, log_tokens_fn=log_tokens_fn, room_key=room_key)

    corp_nm = (s.get("biz", {}).get("상호") or "통합고용세액공제").strip()
    corp_fn = re.sub(r'[\\/:*?"<>|\s]+', "_", corp_nm)[:30]

    # 기중 가결산 안내는 상단 배너 1곳에만 깔끔하게 표시 (보고서 본문 내 중복 제거)
    last_m_cur = H.detect_last_paid_month(s.get("people") or {}, tax_yr)
    if s.get("assume_year_end", True) and last_m_cur < 12:
        st.markdown(
            f"<div class='ec-warn-banner'>"
            f"<b>[기중 가결산 추정치 안내]</b> 본 보고서는 {tax_yr}년 <b>{last_m_cur}월 가결산</b> 기준으로 "
            f"{last_m_cur+1}∼12월을 '연말까지 재직 가정(1 자동 채움)'하여 산출된 추정 보고서입니다. "
            f"확정신고 시에는 12월 최종 원천징수부를 반영하여 확정하시기 바랍니다."
            f"</div>",
            unsafe_allow_html=True,
        )

    md_text = _build_report_markdown(s, log_tokens_fn=log_tokens_fn, room_key=room_key)
    pdf_report_bytes = _build_report_pdf_bytes(s, log_tokens_fn=log_tokens_fn, room_key=room_key)

    # 보고서 본문: 자율 에이전트AI 스크린 글자크기(1.12rem) + 대/중/소제목/내용 위계 적용 래퍼
    st.markdown(f"<div class='ec-agent-report-wrap'>\n\n{md_text}\n\n</div>", unsafe_allow_html=True)

    # 사용자가 보고서 내 Ⅳ. 심층 세무진단 의견 문구를 직접 다듬거나 수정할 수 있는 편집 영역
    disp_model = model_used or str(s.get("pro_audit_model") or "gemini-2.5-pro")
    with st.expander("✏️ Ⅳ. 심층 세무진단 의견 문구 직접 수정 · AI 재생성", expanded=False):
        st.caption("아래에서 보고서 『Ⅳ. 심층 세무진단 의견』 문구를 직접 수정하고 [수정 내용 반영]을 누르면 화면 보고서와 PDF 출력물에 즉시 반영됩니다.")
        edited_audit = st.text_area(
            "Ⅳ. 심층 세무진단 의견 본문",
            value=audit_clean_body,
            height=240,
            label_visibility="collapsed",
            key=f"ec_edit_audit_area_{tax_yr}",
        )
        ce1, ce2, _ = st.columns([1.4, 1.4, 4.2])
        if ce1.button("💾 수정 내용 반영", type="primary", use_container_width=True, key="btn_save_edited_audit"):
            s["pro_audit_comment"] = f"[적용 모델: {disp_model}]\n\n{_sanitize_markdown_tilde(edited_audit)}"
            _save_ec_to_disk(s)
            st.rerun()
        if ce2.button("🔄 AI 의견 다시 생성", use_container_width=True, key="btn_regen_audit"):
            s["pro_audit_comment"] = ""
            s["pro_audit_sig"] = ""
            _save_ec_to_disk(s)
            st.rerun()

    # 하단 적용모델 정보는 스크린에만 표시 (PDF 출력물에서는 제외됨)
    st.markdown(
        f"<div class='ec-model-footer-bar'>"
        f"<span>심층 세무진단 분석 완료</span>"
        f"<span>적용 모델: <code>{disp_model}</code> (스크린 전용 표시 · PDF 출력 제외)</span>"
        f"</div>",
        unsafe_allow_html=True,
    )

    # 하단 단일 네비게이션 & 다운로드 바 (상단 중복 PDF 버튼 제거 → 2·3단계와 동일한 하단 구조로 통일)
    st.markdown("<div class='ec-nav-divider'></div>", unsafe_allow_html=True)
    c_prev, _, c_pdf_bot, c_reset = st.columns([1.2, 3.45, 1.25, 1.3])
    if c_prev.button("< 이전(3단계)", use_container_width=True):
        s["step"] = 3
        _trigger_scroll_to_top(s)
        _save_ec_to_disk(s)
        st.rerun()
    with c_pdf_bot:
        with st.container(key="ec_btn_pdf_rep_bot"):
            st.download_button(
                "📕 보고서 PDF 다운",
                data=pdf_report_bytes,
                file_name=f"{corp_fn}_{tax_yr}년귀속_통합고용세액공제_검토보고서.pdf",
                mime="application/pdf",
                use_container_width=True,
                key="dl_pdf_report_bot",
                help="현재 화면의 통합고용세액공제 및 사후관리 검토보고서를 A4 PDF로 다운로드합니다.",
            )
    if c_reset.button("처음으로(1단계)", use_container_width=True):
        s["step"] = 1
        _trigger_scroll_to_top(s)
        _save_ec_to_disk(s)
        st.rerun()


# ══════════════════════════════════════════════════════════════════
# 8. 진입점
# ══════════════════════════════════════════════════════════════════
def render_credit_wizard(extract_file_fn, log_tokens_fn=None, active_room_key: str = "", **_):
    s = _S()
    try:
        st.markdown(CSS, unsafe_allow_html=True)
        _top_status_bar(s)
        _progress(s["step"])
        _render_scroll_to_top_if_needed(s)

        if s["step"] == 1:
            _page_upload(extract_file_fn, log_tokens_fn, active_room_key)
        elif s["step"] == 2:
            _page_employees(active_room_key, log_tokens_fn=log_tokens_fn)
        elif s["step"] == 3:
            _page_calculation()
        else:
            _page_report(active_room_key, log_tokens_fn=log_tokens_fn)
    finally:
        # 화면 이동(st.rerun)으로 중간에 끝나도 이 시점에 한 번 저장 (내용이 바뀌었을 때만 실제로 씀)
        _flush_ec_save(force=True)