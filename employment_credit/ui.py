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
import hashlib
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

STEPS = ["자료 업로드", "사원정보", "공제액 계산", "보고서"]
MONTH_COLS = [f"M{m:02d}" for m in range(1, 13)]
INFO_COLS = ["사업장명", "성명", "생년월일", "입사일", "퇴사일"]
CLASS_COLS = ["고용유형", "제외사유", "청년등"]

STORAGE_DIR = ".workspace_storage"
os.makedirs(STORAGE_DIR, exist_ok=True)

_PERSIST_KEYS = (
    "step",
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
)


# ══════════════════════════════════════════════════════════════════
# 0. 작업공간별 상태 보관 (메모리 + 디스크 `.workspace_storage` 자동 동기화)
# ══════════════════════════════════════════════════════════════════
def _ec_disk_path(ws_id: str) -> str:
    safe_hash = hashlib.md5(str(ws_id or "default_ec").encode("utf-8")).hexdigest()[:16]
    return os.path.join(STORAGE_DIR, f"ec_state_{safe_hash}.json")


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


def _save_ec_to_disk(s: dict | None = None) -> None:
    try:
        ws_id = st.session_state.get("loaded_workspace_id") or "default_ec"
        if s is None:
            store = st.session_state.get("ec_by_ws") or {}
            s = store.get(ws_id)
        if not isinstance(s, dict):
            return
        os.makedirs(STORAGE_DIR, exist_ok=True)
        payload = {k: s.get(k) for k in _PERSIST_KEYS if k in s}
        with open(_ec_disk_path(ws_id), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
    except Exception:
        pass


def _default_state_dict() -> dict:
    return {
        "step": 1,
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
    }


def _S() -> dict:
    ws_id = st.session_state.get("loaded_workspace_id") or "default_ec"
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
    }


def _cohort_youth_map(s: dict, cohort_year: int) -> dict[str, bool]:
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
            clean_wp = _sanitize_workplace_label(raw_wp, "") or P.infer_workplace_name(n, f_obj.get("text", "")) or default_wp
            chunks.append(f"<<<FILE_WP:{clean_wp}>>>\n{f_obj.get('text', '')}")
        texts[k] = "\n\n".join(chunks)
    return texts


def _carry_over_user_edits(s: dict, old_people: dict, old_recs: dict) -> None:
    """
    사원표를 다시 만들 때(귀속연도 변경·파일 추가 등) 2단계에서 직접 입력한 값을 이어 붙입니다.
    같은 사람 판정: 성명+생년월일. 서류 없이 직접 추가한 사원은 그대로 옮깁니다.
    """
    if not old_people:
        return
    key = lambda p: f"{p.get('성명', '')}|{p.get('생년월일', '')}"
    new_by_key = {key(p): pid for pid, p in s["people"].items()}
    for opid, op in old_people.items():
        npid = new_by_key.get(key(op))
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
        if s.get("ext") is None and s.get("files"):
            classified: dict[str, list[str]] = {}
            for name, f in s["files"].items():
                if f.get("key"):
                    classified.setdefault(f["key"], []).append(name)
            texts = _compose_doc_texts_with_wp(s, classified)
            s["ext"] = P.extract_all(texts, None, "")
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

        parsed_prev = P.build_prev_summary(ext, tax_yr)
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
                }

        s["grid_ver"], s["last_sent"] = {}, {}
        s["built_sig"] = sig
        _save_ec_to_disk(s)


# ══════════════════════════════════════════════════════════════════
# 0-B. 상시근로자 명세서 A4 가로(Landscape) 정식 PDF 생성 엔진
# ══════════════════════════════════════════════════════════════════
def _ensure_korean_pdf_font() -> tuple[str, str]:
    reg_name = "ECKoreanFont"
    bold_name = "ECKoreanFontBold"
    if reg_name in pdfmetrics.getRegisteredFontNames():
        return reg_name, bold_name

    win_malgun = "C:/Windows/Fonts/malgun.ttf"
    win_malgun_bd = "C:/Windows/Fonts/malgunbd.ttf"
    reg_path = os.path.join(STORAGE_DIR, "NanumGothic.ttf")
    bold_path = os.path.join(STORAGE_DIR, "NanumGothicBold.ttf")

    if os.path.exists(win_malgun):
        reg_path = win_malgun
        bold_path = win_malgun_bd if os.path.exists(win_malgun_bd) else win_malgun
    elif not os.path.exists(reg_path):
        try:
            urllib.request.urlretrieve(
                "https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Regular.ttf",
                reg_path,
            )
            urllib.request.urlretrieve(
                "https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Bold.ttf",
                bold_path,
            )
        except Exception:
            pass

    if os.path.exists(reg_path):
        try:
            pdfmetrics.registerFont(TTFont(reg_name, reg_path))
            pdfmetrics.registerFont(TTFont(bold_name, bold_path if os.path.exists(bold_path) else reg_path))
            return reg_name, bold_name
        except Exception:
            pass

    try:
        pdfmetrics.registerFont(UnicodeCIDFont("HYGothic-Medium"))
        return "HYGothic-Medium", "HYGothic-Medium"
    except Exception:
        return "Helvetica", "Helvetica-Bold"


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
    corp_nm = (b.get("상호") or "").strip() or "상호미입력"
    biz_no = (b.get("사업자번호") or "").strip() or "-"
    corp_sz = b.get("기업구분") or "중소기업"
    cap = H.is_capital_area(b.get("사업장소재지", ""))
    loc_str = "수도권" if cap is True else ("수도권 외(비수도권)" if cap is False else "소재지미입력")
    tax_yr = int(s.get("tax_year") or R.DEFAULT_TAX_YEAR)

    story = []
    if len(target_years) == 1:
        y_only = target_years[0]
        story.append(Paragraph(f"[{corp_nm}] {y_only}년 귀속 상시근로자 명세서 (통합고용세액공제 · 사후관리 판정표)", st_title))
    else:
        story.append(Paragraph(f"[{corp_nm}] {tax_yr}년 귀속 통합고용세액공제 전체 연도 상시근로자 명세서 ({', '.join(str(y)+'년' for y in target_years)})", st_title))

    story.append(
        Paragraph(
            f"사업자등록번호: {biz_no}  |  기업규모·소재지: {corp_sz} · {loc_str}  |  귀속사업연도: {tax_yr}년 귀속",
            st_sub,
        )
    )

    totals_by_yr: dict[int, dict] = {}
    for idx_y, y in enumerate(target_years):
        if idx_y > 0:
            story.append(Spacer(1, 10))
        rows, _, totals = _build_year_rows(s, y)
        totals_by_yr[y] = totals
        role_desc = _year_role_description(s, tax_yr, y)
        trunc_mode = "인별절사" if int(y) >= 2025 else "전체절사"
        b3_t, b4_t, b5_t = _block_titles_for_year(y, two_line=False)

        has_y1 = _has_year_data(s, y - 1) or bool(s.get("show_empty_pm_blocks", False))
        has_y2 = _has_year_data(s, y - 2) or bool(s.get("show_empty_pm_blocks", False))

        story.append(
            Paragraph(
                f"■ {y}년 귀속 상시근로자 명세 ({len(rows)}명) — {role_desc}",
                st_yr_hdr,
            )
        )
        kpi_line = (
            f"[{b3_t}] 상시 {totals['b1_reg']:.2f}명 (청년등 {totals['b1_yth']:.2f} · 청년외 {totals['b1_gen']:.2f})"
            + (f"   |   [{b4_t}] 상시 {totals['b2_reg']:.2f}명 (청년등 {totals['b2_yth']:.2f} · 청년외 {totals['b2_gen']:.2f})" if has_y1 else "")
            + (f"   |   [{b5_t}] 상시 {totals['b3_reg']:.2f}명 (청년등 {totals['b3_yth']:.2f} · 청년외 {totals['b3_gen']:.2f})" if has_y2 else "")
            + f"   |   총인원(연인원) {totals['상시_합계']:g}명 ÷ {totals['months_in_year']}개월 ({trunc_mode})"
        )
        story.append(Paragraph(kpi_line, st_sub))

        headers = [
            "사업장", "성명", "생년월일", "입사일", "퇴사일", "연령", "고용유형", "제외사유", "청년등 구분", "상시",
            *[f"{m}월" for m in range(1, 13)], "월합",
            f"{y%100:02d}공제\n청년", f"{y%100:02d}공제\n일반", f"{y%100:02d}공제\n상시",
        ]
        col_widths = [
            34, 36, 42, 42, 42, 22, 44, 52, 54, 18,
            *[16.5 for _ in range(12)], 22,
            24, 24, 24,
        ]
        if has_y1:
            headers.extend([f"{(y-1)%100:02d}사후\n청년", f"{(y-1)%100:02d}사후\n일반", f"{(y-1)%100:02d}사후\n상시"])
            col_widths.extend([24, 24, 24])
        if has_y2:
            headers.extend([f"{(y-2)%100:02d}사후\n청년", f"{(y-2)%100:02d}사후\n일반", f"{(y-2)%100:02d}사후\n상시"])
            col_widths.extend([24, 24, 24])

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
                str(r["사업장명"])[:6],
                str(r["성명"])[:6],
                str(r["생년월일"]).replace("-", "."),
                str(r["입사일"]).replace("-", "."),
                str(r["퇴사일"]).replace("-", "."),
                str(r["취업연령"]),
                str(r["고용유형"]).replace("근로자", ""),
                str(r["제외사유"])[:8],
                str(r["청년등"])[:8],
                str(r["상시"]),
                *m_cells,
                f"{r['합계']:g}",
                f"{r['b1_yth']:.2f}", f"{r['b1_gen']:.2f}", f"{r['b1_reg']:.2f}",
            ]
            if has_y1:
                row_cells.extend([f"{r['b2_yth']:.2f}", f"{r['b2_gen']:.2f}", f"{r['b2_reg']:.2f}"])
            if has_y2:
                row_cells.extend([f"{r['b3_yth']:.2f}", f"{r['b3_gen']:.2f}", f"{r['b3_reg']:.2f}"])
            tbl_data.append(row_cells)

        # 하단 요약 3행 추가
        sum_rows = [
            (
                "합산합계", "상시근로자", f"÷{totals['months_in_year']}개월({trunc_mode})",
                [f"{v:g}" if v is not None else "-" for v in totals["월별_상시"]],
                f"{totals['상시_합계']:g}",
                [f"{totals['b1_yth']:.2f}", f"{totals['b1_gen']:.2f}", f"{totals['b1_reg']:.2f}"],
                [f"{totals['b2_yth']:.2f}", f"{totals['b2_gen']:.2f}", f"{totals['b2_reg']:.2f}"],
                [f"{totals['b3_yth']:.2f}", f"{totals['b3_gen']:.2f}", f"{totals['b3_reg']:.2f}"],
            ),
            (
                "합산합계", "청년등", "코호트 기준",
                [f"{v:g}" if v is not None else "-" for v in totals["월별_청년등"]],
                f"{totals['청년등_합계']:g}",
                [f"{totals['b1_yth']:.2f}", "-", "-"],
                [f"{totals['b2_yth']:.2f}", "-", "-"],
                [f"{totals['b3_yth']:.2f}", "-", "-"],
            ),
            (
                "합산합계", "청년등 외", "상시 - 청년등",
                [f"{v:g}" if v is not None else "-" for v in totals["월별_청년외"]],
                f"{totals['청년외_합계']:g}",
                ["-", f"{totals['b1_gen']:.2f}", "-"],
                ["-", f"{totals['b2_gen']:.2f}", "-"],
                ["-", f"{totals['b3_gen']:.2f}", "-"],
            ),
        ]
        for wp_l, nm_l, et_l, m_list, tot_s, b1_l, b2_l, b3_l in sum_rows:
            s_row = [wp_l, nm_l, "", "", "", "", et_l, "", "", "", *m_list, tot_s, *b1_l]
            if has_y1:
                s_row.extend(b2_l)
            if has_y2:
                s_row.extend(b3_l)
            tbl_data.append(s_row)

        t_obj = Table(tbl_data, colWidths=col_widths, repeatRows=1)
        n_data_end = len(tbl_data) - 3
        t_style = [
            ("FONTNAME", (0, 0), (-1, 0), bold_font),
            ("FONTNAME", (0, 1), (-1, -1), reg_font),
            ("FONTNAME", (0, n_data_end), (-1, -1), bold_font),
            ("FONTSIZE", (0, 0), (-1, -1), 6.3),
            ("LEADING", (0, 0), (-1, -1), 8.0),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("BACKGROUND", (0, n_data_end), (-1, -1), colors.HexColor("#dcfce7")),
            ("TEXTCOLOR", (0, n_data_end), (-1, -1), colors.HexColor("#14532d")),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#cbd5e1")),
            ("TOPPADDING", (0, 0), (-1, -1), 2.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
            ("LEFTPADDING", (0, 0), (-1, -1), 1.5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 1.5),
        ]
        for r_i in range(1, n_data_end):
            if r_i % 2 == 0:
                t_style.append(("BACKGROUND", (0, r_i), (-1, r_i), colors.HexColor("#f8fafc")))
        t_obj.setStyle(TableStyle(t_style))
        story.append(t_obj)

    if include_summary and tax_yr in totals_by_yr and (tax_yr - 1) in totals_by_yr:
        story.append(Spacer(1, 10))
        cur_t, prv_t = totals_by_yr[tax_yr], totals_by_yr[tax_yr - 1]
        suc_reg, suc_yth = _succeeded_prev_headcount_sum(s)
        eff_prv_reg = round(prv_t["상시_평균"] + suc_reg, 2)
        eff_prv_yth = round(prv_t["청년등_평균"] + suc_yth, 2)
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
    width: 660px !important;
    max-width: 94vw !important;
    margin: auto !important;
    border-radius: 12px !important;
}
div[role="dialog"] li,
div[role="dialog"] p {
    font-family: 'Pretendard', 'Malgun Gothic', sans-serif !important;
    font-size: 0.93rem !important;
    line-height: 1.58 !important;
    color: #1e293b !important;
    word-break: keep-all !important;
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

/* 🧭 4단계 스텝 진행바 — 자율 에이전트 그린(#16a34a) & 네이비(#1e293b) 테마 */
.ec-steps {
    display: flex;
    gap: 8px;
    margin: 4px 0 12px 0;
    font-family: 'Pretendard', 'Malgun Gothic', sans-serif;
}
.ec-step {
    flex: 1;
    padding: 8px 13px;
    border-radius: 9px;
    background: #f8fafc;
    color: #64748b;
    font-size: 0.90rem;
    font-weight: 700;
    border: 1px solid #e2e8f0;
    border-bottom: 3px solid #cbd5e1;
    display: flex;
    align-items: center;
    justify-content: space-between;
    letter-spacing: -0.3px;
    transition: all 0.15s ease;
}
.ec-step.done {
    background: #f0fdf4;
    color: #15803d;
    border-color: #bbf7d0;
    border-bottom: 3px solid #22c55e;
    font-weight: 800;
}
.ec-step.now {
    background: linear-gradient(135deg, #16a34a 0%, #15803d 100%);
    color: #ffffff;
    border-color: #15803d;
    border-bottom: 3px solid #14532d;
    font-weight: 800;
    box-shadow: 0 3px 8px rgba(22, 163, 74, 0.22);
}
.ec-step-badge {
    font-size: 0.72rem;
    padding: 2px 7px;
    border-radius: 999px;
    font-weight: 700;
}
.ec-step.now .ec-step-badge {
    background: rgba(255, 255, 255, 0.22);
    color: #ffffff;
}
.ec-step.done .ec-step-badge {
    background: #dcfce7;
    color: #15803d;
}
.ec-step.wait .ec-step-badge {
    background: #e2e8f0;
    color: #64748b;
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
    gap: 6px;
    margin: 2px 0 6px 0;
}
.ec-legend span {
    display: inline-flex;
    align-items: center;
    padding: 2px 9px;
    border-radius: 6px;
    font-size: 0.79rem;
    font-weight: 700;
}
.ec-year-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    background: linear-gradient(90deg, #f1f5f9 0%, #ffffff 100%);
    border-left: 5px solid #1e3a8a;
    border-top: 1px solid #e2e8f0;
    border-right: 1px solid #e2e8f0;
    border-bottom: 1px solid #e2e8f0;
    padding: 7px 14px;
    border-radius: 0 8px 8px 0;
    min-height: 38px;
}
.ec-year-title {
    font-size: 1.04rem;
    font-weight: 800;
    color: #1e3a8a;
    white-space: nowrap;
}
.ec-year-sub {
    font-size: 0.82rem;
    font-weight: 600;
    color: #475569;
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
    padding: 9px 13px;
    margin: 5px 0 16px 0;
    align-items: center;
    justify-content: space-between;
    box-shadow: 0 2px 6px rgba(15, 23, 42, 0.05);
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
</style>
"""


def _top_status_bar(s: dict):
    """자율 에이전트AI 상단과 동일한 디자인의 미니 상태바(.top-mini-status-bar)를 렌더링합니다."""
    b = s.get("biz") or {}
    corp_nm = (b.get("상호") or "").strip() or "상호 미입력"
    sub_cnt = len(s.get("sub_biz_list") or [])
    if sub_cnt > 0:
        corp_nm = f"{corp_nm} 외 {sub_cnt}개 사업장 합산"
    corp_sz = b.get("기업구분") or "중소기업"
    cap = H.is_capital_area(b.get("사업장소재지", ""))
    loc_str = "수도권" if cap is True else ("비수도권(수도권 외)" if cap is False else "소재지 미입력")
    tax_yr = int(s.get("tax_year") or R.DEFAULT_TAX_YEAR)
    pm_lbl = R.PM_BASIS_LABELS.get(s.get("pm_basis", R.PM_BASIS_FILED), "기신고 기준")
    law_ver = (
        f"{tax_yr}귀속 (인별절사 · 사후관리: {pm_lbl})"
        if tax_yr >= 2025
        else f"{tax_yr}귀속 (전체절사 · 사후관리: {pm_lbl})"
    )
    step_nm = STEPS[max(0, min(len(STEPS) - 1, int(s.get("step", 1)) - 1))]

    st.markdown(
        f"<div class='top-mini-status-bar'>"
        f"<span>🧮 <b>통합고용세액공제 ({tax_yr}년 귀속)</b> &nbsp;|&nbsp; 🏢 <b>{corp_nm}</b> ({corp_sz} · {loc_str})</span>"
        f"<span>📌 현재 단계: <b>{s.get('step', 1)}단계 [{step_nm}]</b> &nbsp;·&nbsp; <span class='sb-badge-green'>💾 자동보관 ON · {law_ver}</span></span>"
        f"</div>",
        unsafe_allow_html=True,
    )


def _progress(step: int):
    cells = []
    for i, name in enumerate(STEPS, start=1):
        if i == step:
            cls, badge = "now", "진행중"
        elif i < step:
            cls, badge = "done", "✓ 완료"
        else:
            cls, badge = "wait", "대기"
        cells.append(
            f"<div class='ec-step {cls}'>"
            f"<span>{i}. {name}</span>"
            f"<span class='ec-step-badge'>{badge}</span>"
            f"</div>"
        )
    st.markdown(f"<div class='ec-steps'>{''.join(cells)}</div>", unsafe_allow_html=True)


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


@st.dialog("🔍 법령·심판례·절세누락 12대 정밀 오류 검토")
def _dlg_review(items: list[tuple[str, str]], audit_payload: dict | None = None, log_tokens_fn=None, room_key: str = ""):
    s = _S()
    errs = [m for lv, m in items if lv == "오류"]
    savs = [m for lv, m in items if lv == "절세누락"]
    chks = [m for lv, m in items if lv == "확인"]

    st.markdown(
        f"<div style='display:flex;gap:8px;margin-bottom:10px;flex-wrap:wrap;'>"
        f"<span style='background:#fef2f2;color:#b91c1c;border:1px solid #fecaca;padding:4px 11px;border-radius:999px;font-weight:800;font-size:0.84rem;'>🚨 필수 수정 오류 {len(errs)}건</span>"
        f"<span style='background:#f0fdf4;color:#15803d;border:1px solid #86efac;padding:4px 11px;border-radius:999px;font-weight:800;font-size:0.84rem;'>💰 절세누락 주의 {len(savs)}건</span>"
        f"<span style='background:#eff6ff;color:#1d4ed8;border:1px solid #bfdbfe;padding:4px 11px;border-radius:999px;font-weight:800;font-size:0.84rem;'>💡 실무·심판례 확인 {len(chks)}건</span>"
        f"</div>",
        unsafe_allow_html=True,
    )

    if not items:
        st.success("✅ 법령 및 최신 조세심판례 12대 항목 검토 결과, 발견된 오류나 절세누락 사항이 없습니다.")
    if errs:
        st.markdown(f"#### 🚨 필수 수정 오류 ({len(errs)}건) — 수정해야 정확한 상시근로자 수가 계산됩니다.")
        for m in errs:
            st.markdown(f"- :red[**{m}**]")
    if savs:
        st.markdown(f"#### 💰 절세누락 주의 ({len(savs)}건) — 청년·고령자 우대공제 추가 적용이 가능한 대상입니다.")
        for m in savs:
            st.markdown(f"- :green[**{m}**]")
    if chks:
        st.markdown(f"#### 💡 실무·심판례 확인 사항 ({len(chks)}건) — 사실관계가 맞다면 그대로 진행하셔도 됩니다.")
        for m in chks:
            st.markdown(f"- {m}")

    st.markdown("<div class='ec-nav-divider'></div>", unsafe_allow_html=True)
    if audit_payload:
        if st.button("👑 Pro/Argon AI 심층 세무진단 코멘트 생성 (특수사례·판례 정밀점검)", use_container_width=True, key="btn_run_pro_audit"):
            with st.spinner("👑 Pro/Argon 모델이 사원표·특례·사후관리 리스크를 심층 분석하고 있습니다..."):
                s["pro_audit_comment"] = P.call_pro_argon_audit_commentary(
                    audit_payload, log_tokens_fn=log_tokens_fn, room_key=room_key
                )
                _save_ec_to_disk(s)
        if s.get("pro_audit_comment"):
            with st.container(border=True):
                st.markdown("##### 👑 Pro/Argon AI 심층 세무진단 의견")
                st.markdown(s["pro_audit_comment"])

    if st.button("닫기", type="primary", use_container_width=True):
        st.rerun()


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
            f"<span class='sb-badge-green'>{tax_yr}년 (인별절사)</span>"
            if tax_yr >= 2025
            else f"<span class='sb-badge-amber'>{tax_yr}년 (전체절사)</span>"
        )
        st.markdown(
            f"<div class='sb-card-title'><span>📅 귀속사업연도</span>{yr_badge}</div>",
            unsafe_allow_html=True,
        )
        new_year = st.selectbox(
            "통합고용세액공제 계산 기준 사업연도",
            options=R.SUPPORTED_TAX_YEARS,
            index=R.SUPPORTED_TAX_YEARS.index(tax_yr),
            format_func=lambda y: f"{y}년 귀속 ({'인별절사' if y >= 2025 else '전체절사'} · {(y-1)%100:02d}·{(y-2)%100:02d} 사후관리)",
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
                        st.caption("⚖️ **조특령 제26조의8 제10항 (고용승계·포괄양수 특례)**: 피승계(양도) 사업장의 직전연도 상시·청년등 인원을 입력하면 3단계 직전연도 비교 인원에 자동 합산됩니다.")
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
                        st.caption(
                            "⚖️ **기중양도·폐업 사업장 특례**: 위 『폐업·양도일』을 입력하면 타 사업장으로 전출(`→`)되지 않은 소속 근로자는 양도월 이후 미도래 월에 대해 연말재직 가정(1 채움)이 자동 중단(`0` 처리)됩니다."
                        )
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
    ind = f"{b.get('업태', '')} {b.get('종목', '')}".strip()
    if ind and H.is_excluded_industry(ind) and s["industry_alert_for"] != ind:
        s["industry_alert_for"] = ind
        _dlg_industry(ind)


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
            "<b>① 26년 세액공제(인별절사)</b>, <b>② 25년 1차 사후관리(2차년도 연속공제·추징)</b>, "
            "<b>③ 24년 2차 사후관리(3차년도 연속공제·추징)</b>를 함께 검토합니다. "
            "본점·지점 또는 기중 양도(1번)·포괄양수(2번) 복수 사업장 원천징수부를 함께 올리면 자동 합산됩니다."
            "</div>",
            unsafe_allow_html=True,
        )
    elif tax_yr in (2024, 2025):
        trunc_lbl = "인별절사" if tax_yr >= 2025 else "전체절사"
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
                text = extract_file_fn(u, room_key) or ""
                auto_wp = _sanitize_workplace_label(P.infer_workplace_name(u.name, text), _default_workplace_label(s))
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
                    c1.markdown(f"📄 **{name}**")
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
        if s["ext_sig"] != sig:
            texts = _compose_doc_texts_with_wp(s, classified)
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
  const baseFont = {fontFamily: 'Pretendard, Malgun Gothic, sans-serif', fontSize: '11.8px', paddingLeft: '3px', paddingRight: '3px', overflow: 'visible', textOverflow: 'clip'};
  if (p.node.rowPinned) return Object.assign(baseFont, {backgroundColor:'#dcfce7', color:'#14532d', fontWeight:'800'});
  const L = (p.data._lock || '').split(',');
  if (L.includes(p.colDef.field)) return Object.assign(baseFont, {backgroundColor:'#e2e8f0', color:'#0f172a', fontWeight:'600'});
  return Object.assign(baseFont, {backgroundColor:'#ffffff', color:'#1d4ed8', fontWeight:'600'});
}""")

JS_STYLE_WORKPLACE = JsCode("""
function(p){
  const baseFont = {fontFamily: 'Pretendard, Malgun Gothic, sans-serif', fontSize: '11.6px', textAlign: 'center', paddingLeft: '3px', paddingRight: '3px', overflow: 'visible', textOverflow: 'clip'};
  if (p.node.rowPinned) return Object.assign(baseFont, {backgroundColor:'#dcfce7', color:'#14532d', fontWeight:'800'});
  const v = String(p.value || '');
  if (v.includes('→')) return Object.assign(baseFont, {backgroundColor:'#dbeafe', color:'#1e40af', fontWeight:'800'});
  return Object.assign(baseFont, {backgroundColor:'#f8fafc', color:'#334155', fontWeight:'700'});
}""")

JS_STYLE_CENTER = JsCode("""
function(p){
  const baseFont = {fontFamily: 'Pretendard, Malgun Gothic, sans-serif', fontSize: '11.8px', textAlign: 'center', paddingLeft: '3px', paddingRight: '3px', overflow: 'visible', textOverflow: 'clip'};
  if (p.node.rowPinned) return Object.assign(baseFont, {backgroundColor:'#dcfce7', color:'#14532d', fontWeight:'800'});
  const L = (p.data._lock || '').split(',');
  if (L.includes(p.colDef.field)) return Object.assign(baseFont, {backgroundColor:'#e2e8f0', color:'#0f172a', fontWeight:'600'});
  return Object.assign(baseFont, {backgroundColor:'#ffffff', color:'#1d4ed8', fontWeight:'600'});
}""")

JS_STYLE_EXCL = JsCode("""
function(p){
  const baseFont = {fontFamily: 'Pretendard, Malgun Gothic, sans-serif', fontSize: '11.6px', textAlign: 'center', paddingLeft: '3px', paddingRight: '3px', overflow: 'visible', textOverflow: 'clip'};
  if (p.node.rowPinned) return Object.assign(baseFont, {backgroundColor:'#dcfce7', color:'#14532d', fontWeight:'800'});
  const v = String(p.value || '');
  if (v && v !== '해당없음') return Object.assign(baseFont, {backgroundColor:'#fef2f2', color:'#b91c1c', fontWeight:'800'});
  const L = (p.data._lock || '').split(',');
  if (L.includes(p.colDef.field)) return Object.assign(baseFont, {backgroundColor:'#e2e8f0', color:'#64748b', fontWeight:'500'});
  return Object.assign(baseFont, {backgroundColor:'#ffffff', color:'#64748b', fontWeight:'500'});
}""")

JS_STYLE_YOUTH = JsCode("""
function(p){
  const baseFont = {fontFamily: 'Pretendard, Malgun Gothic, sans-serif', fontSize: '11.6px', textAlign: 'center', paddingLeft: '3px', paddingRight: '3px', overflow: 'visible', textOverflow: 'clip'};
  if (p.node.rowPinned) return Object.assign(baseFont, {backgroundColor:'#dcfce7', color:'#14532d', fontWeight:'800'});
  const v = String(p.value || '');
  if (v && !v.startsWith('해당없음')) return Object.assign(baseFont, {backgroundColor:'#f0fdf4', color:'#15803d', fontWeight:'800'});
  const L = (p.data._lock || '').split(',');
  if (L.includes(p.colDef.field)) return Object.assign(baseFont, {backgroundColor:'#e2e8f0', color:'#64748b', fontWeight:'500'});
  return Object.assign(baseFont, {backgroundColor:'#ffffff', color:'#64748b', fontWeight:'500'});
}""")

JS_STYLE_REGULAR = JsCode("""
function(p){
  const baseFont = {fontFamily: 'Pretendard, Malgun Gothic, sans-serif', fontSize: '12.0px', textAlign: 'center', paddingLeft: '2px', paddingRight: '2px', overflow: 'visible', textOverflow: 'clip'};
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
  const s = {fontFamily: 'Pretendard, Malgun Gothic, sans-serif', fontSize: '11.8px', textAlign:'center', paddingLeft:'1px', paddingRight:'1px', overflow: 'visible', textOverflow: 'clip'};
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
    trunc_mode = "인별절사" if y0 >= 2025 else "전체절사"
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
            if P._is_employee_id_token(pt_c) or any(k in pt_c for k in noise_marks) or pt_c in ("년", "월"):
                pt_c = default_wp
            if pt_c and pt_c not in parts:
                parts.append(pt_c)
        return "→".join(parts) if parts else default_wp
    if P._is_employee_id_token(s) or any(k in s for k in noise_marks) or s in ("년", "월", "귀속"):
        return default_wp
    return s


def _build_year_rows(s: dict, year: int) -> tuple[list[dict], dict, dict]:
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
            lock += [f for f in ("고용유형",) if f in (yrec.get("_confirmed") or [])]
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
            "fontSize": "11.8px",
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
            "width": 88,
            "minWidth": 88,
            "suppressSizeToFit": True,
            "editable": JS_LOCKED,
            "cellStyle": JS_STYLE_CENTER,
            "valueFormatter": JS_DATE_FMT,
        },
        {
            "field": "입사일",
            "headerName": "입사일",
            "width": 88,
            "minWidth": 88,
            "suppressSizeToFit": True,
            "editable": JS_LOCKED,
            "cellStyle": JS_STYLE_CENTER,
            "valueFormatter": JS_DATE_FMT,
        },
        {
            "field": "퇴사일",
            "headerName": "퇴사일",
            "width": 88,
            "minWidth": 88,
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
            "width": 118,
            "minWidth": 118,
            "suppressSizeToFit": True,
            "editable": JS_LOCKED,
            "cellStyle": JS_STYLE,
            "cellEditor": "agSelectCellEditor",
            "cellEditorParams": {"values": R.EMP_TYPES},
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
                "width": 42,
                "minWidth": 42,
                "suppressSizeToFit": True,
                "suppressMenu": True,
                "suppressHeaderMenuButton": True,
                "editable": JS_MONTH_EDITABLE,
                "cellStyle": JS_MONTH_STYLE,
                "cellEditor": "agSelectCellEditor",
                "cellEditorParams": {"values": R.MONTH_CHOICES},
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
    trunc_mode = "인별절사" if int(year) >= 2025 else "전체절사"
    pinned = [
        {
            "사업장명": "합산합계",
            "성명": "상시근로자",
            "생년월일": "",
            "고용유형": f"÷ {n}개월 ({trunc_mode})",
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
            "font-size": "11.8px !important",
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
            "font-size": "11.6px !important",
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
    trunc_mode = "인별절사" if int(year) >= 2025 else "전체절사"
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
            if st.button(f"➕ {t2_year}년 사원정보 표 직접 열어서 전체절사 계산하기", use_container_width=True, key=f"btn_open_yr_{t2_year}"):
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
        cur_t, prv_t = totals_all[tax_yr], totals_all[tax_yr - 1]
        suc_reg, suc_yth = _succeeded_prev_headcount_sum(s)
        eff_prv_reg = round(prv_t["상시_평균"] + suc_reg, 2)
        eff_prv_yth = round(prv_t["청년등_평균"] + suc_yth, 2)
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
        suc_note = f" (포괄양수·승계 직전인원 +{suc_reg:.2f}명 반영)" if suc_reg > 0 else ""
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

    suc_reg, suc_yth = _succeeded_prev_headcount_sum(s)
    if (suc_reg > 0 or suc_yth > 0) and (tax_yr - 1) in totals_all:
        t1 = totals_all[tax_yr - 1]
        m1 = int(t1.get("months_in_year") or 12)
        t1["상시_평균"] = round(float(t1.get("상시_평균") or 0.0) + suc_reg, 2)
        t1["청년등_평균"] = round(float(t1.get("청년등_평균") or 0.0) + suc_yth, 2)
        t1["청년외_평균"] = round(max(0.0, t1["상시_평균"] - t1["청년등_평균"]), 2)
        t1["b1_reg"] = t1["상시_평균"]
        t1["b1_yth"] = t1["청년등_평균"]
        t1["b1_gen"] = t1["청년외_평균"]
        t1["상시_합계"] = round(float(t1.get("상시_합계") or 0.0) + suc_reg * m1, 2)
        t1["청년등_합계"] = round(float(t1.get("청년등_합계") or 0.0) + suc_yth * m1, 2)
        t1["청년외_합계"] = round(max(0.0, t1["상시_합계"] - t1["청년등_합계"]), 2)
        t1["has_data"] = True

    s["totals_snapshot"] = totals_all
    return totals_all


def _render_pm_basis_selector_right(s: dict, widget_key: str) -> str:
    cur_basis = s.get("pm_basis", R.PM_BASIS_FILED)
    if cur_basis not in (R.PM_BASIS_FILED, R.PM_BASIS_RECALC):
        cur_basis = R.PM_BASIS_FILED
        s["pm_basis"] = cur_basis

    opts = [R.PM_BASIS_FILED, R.PM_BASIS_RECALC]
    fmt_map = {
        R.PM_BASIS_FILED: "📋 기신고 기준 (원칙)",
        R.PM_BASIS_RECALC: "⚖️ 세법원칙 기준 (재계산)",
    }

    seg_fn = getattr(st, "segmented_control", None)
    if callable(seg_fn):
        try:
            chosen = seg_fn(
                "사후관리 계산 기준",
                options=opts,
                default=cur_basis,
                format_func=lambda k: fmt_map.get(k, k),
                label_visibility="collapsed",
                key=widget_key,
            )
            if chosen in opts and chosen != cur_basis:
                s["pm_basis"] = chosen
                _save_ec_to_disk(s)
                st.rerun()
            return s["pm_basis"]
        except Exception:
            pass

    chosen_r = st.radio(
        "사후관리 계산 기준",
        options=opts,
        index=opts.index(cur_basis),
        format_func=lambda k: fmt_map.get(k, k),
        horizontal=True,
        label_visibility="collapsed",
        key=widget_key,
    )
    if chosen_r != cur_basis:
        s["pm_basis"] = chosen_r
        _save_ec_to_disk(s)
        st.rerun()
    return s["pm_basis"]


def _page_calculation():
    s = _S()
    _ensure_built_for_tax_year(s)
    tax_yr = int(s["tax_year"])
    b = s["biz"]
    corp_size = b.get("기업구분", "중소기업")
    cap_bool = H.is_capital_area(b.get("사업장소재지", ""))
    is_capital = True if cap_bool is None else bool(cap_bool)
    loc_label = "수도권" if is_capital else "수도권 외(비수도권)"

    totals_all = _ensure_totals_snapshot(s)
    cur_t = totals_all.get(tax_yr, {})
    prev_t = totals_all.get(tax_yr - 1, {})
    prev2_t = totals_all.get(tax_yr - 2, {})
    has_t2_data = bool(prev2_t.get("has_data") or _has_year_data(s, tax_yr - 2))
    b3_title, b4_title, b5_title = _block_titles_for_year(tax_yr, two_line=False)

    st.markdown(f"### 🧮 3. 통합고용세액공제 및 1·2차 사후관리 계산 ({tax_yr}년 귀속)")
    st.markdown(
        f"<div class='ec-law-banner'>"
        f"🏢 <b>적용 기준:</b> {corp_size} · {loc_label} &nbsp;|&nbsp; "
        f"<b>① {b3_title}</b> + <b>② {b4_title}</b> + "
        f"<b>③ {b5_title}</b> + <b>④ 육아휴직복귀/정규직전환 추가공제</b>를 통합 산출합니다. "
        f"<br>📌 <b>사후관리 산정 원칙:</b> 표 오른쪽 위에서 기본값인 <b>『기신고 기준 (원칙)』</b>과 원천징수부 기반 <b>『세법원칙 기준 (재계산)』</b>을 전환하여 총인원수·평균인원수 및 사후관리세액을 즉시 비교하실 수 있습니다."
        f"</div>",
        unsafe_allow_html=True,
    )

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

    ps = s.setdefault("prev_summary", {})
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
        f"⚙️ 사후관리 『기신고 기준』 기초값 ({tax_yr-1}년 · {tax_yr-2}년 귀속분 기신고 서식)", expanded=True,
    ):
        c_cap, c_btn = st.columns([4.2, 1.8])
        with c_cap:
            st.caption(
                "기신고 상시근로자 명세서·공제감면세액계산서에서 읽은 값입니다. 빈 칸은 서식에서 읽지 못한 값이니 직접 입력하시거나 우측 버튼으로 사원표 재계산 값을 복사해 채울 수 있습니다. "
                "각 칸 이름 옆 괄호는 2단계 사원표로 다시 계산한 『세법원칙 기준』 값입니다 (사원표가 없으면 '-')."
            )
        with c_btn:
            if st.button(
                "🔄 사원표 재계산 값으로 빈칸 채우기",
                use_container_width=True,
                key=f"btn_fill_from_recalc_{tax_yr}",
                help="별도 기신고서를 올리지 않은 경우, 2단계 사원표에서 계산된 인원·증가인원·추정 공제세액을 기신고 입력칸에 복사합니다.",
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
                        if f_d.get("공제세액") is None:
                            yr_cnt = 1 if cohort == tax_yr - 1 else (1 if corp_size in ("일반기업", "대기업") else 2)
                            f_d["공제세액"] = int(
                                round(
                                    (inc_c["youth_inc"] * rates_legacy["청년등"] + inc_c["non_youth_inc"] * rates_legacy["청년등외"])
                                    * 10_000
                                    * yr_cnt
                                )
                            )
                s["fill_ver"] = fill_ver + 1
                _save_ec_to_disk(s)
                st.rerun()

        col_y1, col_y2 = st.columns(2)
        for col, cohort, t_init, t_before, m_key in (
            (col_y1, tax_yr - 1, prev_t, prev2_t, "전년_월수"),
            (col_y2, tax_yr - 2, prev2_t, totals_all.get(tax_yr - 3, {}), "전전년_월수"),
        ):
            f = ps.setdefault(str(cohort), {})
            has_init = bool(t_init.get("has_data")) and not t_init.get("from_filed")
            has_before = bool(t_before.get("has_data")) and not t_before.get("from_filed")
            law_inc = (
                H.calc_increase_with_cap(
                    t_init["상시_평균"], t_init["청년등_평균"], t_before["상시_평균"], t_before["청년등_평균"]
                )
                if has_init and has_before
                else None
            )
            law = lambda k: (f"{t_init.get(k, 0.0):.2f}" if has_init else "-")
            stage = "2차년도·사후관리 1년차" if cohort == tax_yr - 1 else "3차년도·사후관리 2년차"
            with col:
                st.markdown(f"##### 📌 {cohort}년 귀속분 ({stage})")
                a, b_ = st.columns(2)
                f["상시"] = _num_in(a, f"상시 평균인원 ({law('상시_평균')})", f.get("상시"), f"pf_{cohort}_reg_{kver}")
                f["청년등"] = _num_in(b_, f"청년등 평균인원 ({law('청년등_평균')})", f.get("청년등"), f"pf_{cohort}_yth_{kver}")
                f["상시_총인원"] = _num_in(
                    a, f"상시 총인원수·연인원 ({law('상시_합계')})", f.get("상시_총인원"), f"pf_{cohort}_rt_{kver}", step=0.25
                )
                f["청년등_총인원"] = _num_in(
                    b_, f"청년등 총인원수·연인원 ({law('청년등_합계')})", f.get("청년등_총인원"), f"pf_{cohort}_yt_{kver}", step=0.25
                )
                f["청년등_증가"] = _num_in(
                    a,
                    f"공제받은 청년등 증가 ({'-' if law_inc is None else format(law_inc['youth_inc'], '.2f')})",
                    f.get("청년등_증가"),
                    f"pf_{cohort}_yi_{kver}",
                )
                f["청년등외_증가"] = _num_in(
                    b_,
                    f"공제받은 청년등외 증가 ({'-' if law_inc is None else format(law_inc['non_youth_inc'], '.2f')})",
                    f.get("청년등외_증가"),
                    f"pf_{cohort}_gi_{kver}",
                )
                if cohort == tax_yr - 1:
                    f["공제세액"] = _num_in(
                        a, f"{cohort}년 최초 공제세액(원, 추가납부 한도)", f.get("공제세액"), f"pf_{cohort}_clm_{kver}", is_won=True
                    )
                else:
                    f["공제세액"] = _num_in(
                        a,
                        f"{cohort}년분 누적 공제세액(1·2차년도, 원, 한도)",
                        f.get("공제세액"),
                        f"pf_{cohort}_clm_{kver}",
                        is_won=True,
                        help_txt="2년차 추가납부 한도는 직전 2년 내 공제받은 세액 합계입니다.",
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
                missing = [k for k in ("상시", "청년등", "청년등_증가", "청년등외_증가") if f.get(k) is None]
                if missing:
                    st.caption(f"⚠️ 기신고 숫자 없음: {', '.join(missing)} → 『기신고 기준』으로는 계산하지 않습니다.")
    p1, p2 = ps[str(tax_yr - 1)], ps[str(tax_yr - 2)]

    add_in = s.setdefault("additional_inputs", {})
    with st.expander("➕ 추가공제(육아휴직복귀·정규직전환·출산휴가대체인력) · 농특세 실공제 보정 · 단가 옵션", expanded=False):
        ca1, ca2, ca3 = st.columns(3)
        add_in["parental_return_count"] = ca1.number_input(
            "육아휴직 복귀자 수 (명, ~2026년 적용)",
            0,
            500,
            int(add_in.get("parental_return_count") or 0),
            help="1년 이상 근속 후 6개월 이상 육아휴직 후 복귀한 근로자(자녀당 1회, 중소 1,300만원/중견 900만원)",
        )
        add_in["regular_conversion_count"] = ca2.number_input(
            "정규직 전환자 수 (명, 2024년 귀속까지 일몰)",
            0,
            500,
            int(add_in.get("regular_conversion_count") or 0),
            disabled=(tax_yr > 2024),
            help="정규직 전환 추가공제는 2024년 귀속분까지 적용됩니다 (2023.6.30 당시 비정규직·파견·하도급 → 2024년 중 무기계약 전환).",
        )
        add_in["additional_clawback_count"] = ca3.number_input(
            "전환·복귀 후 2년 내 퇴사 추징 인원 (명)",
            0,
            500,
            int(add_in.get("additional_clawback_count") or 0),
            help="정규직 전환일 또는 육아휴직 복귀일로부터 2년 이내에 근로관계가 종료된 인원",
        )
        cb1, cb2, cb3 = st.columns(3)
        add_in["maternity_replacement_count"] = cb1.number_input(
            f"출산전후휴가자 제외 인원 ({tax_yr}년, 연평균)",
            0.0,
            500.0,
            float(add_in.get("maternity_replacement_count") or 0.0),
            0.01,
            help="대체인력을 채용한 출산전후휴가자는 추가공제(정규직 전환·육아휴직 복귀)의 비감소 판정 시 상시근로자 수에서 뺍니다 (조특령 제26조의8 제7항).",
        )
        add_in["maternity_prev_count"] = cb1.number_input(
            f"출산전후휴가자 제외 인원 ({tax_yr-1}년, 연평균)",
            0.0,
            500.0,
            float(add_in.get("maternity_prev_count") or 0.0),
            0.01,
        )
        add_in["current_unclaimed_carryforward_won"] = cb2.number_input(
            f"당해({tax_yr}년) 최저한세 등 미공제 이월예정액 (원)",
            0,
            50_000_000_000,
            int(add_in.get("current_unclaimed_carryforward_won") or 0),
            100_000,
            help="농어촌특별세(20%)는 실제 감면받는 세액(당해 공제액 - 당해 미공제 이월액)에 대해서만 부과됩니다 (농특세법 제5조 제1항).",
        )
        if tax_yr >= 2026:
            scheme_opt = cb3.selectbox(
                f"{tax_yr}년 신규공제 단가 체계",
                options=["new_2026", "legacy"],
                index=0 if s.get("scheme_2026", "new_2026") == "new_2026" else 1,
                format_func=lambda x: "2026 신법 (연차별 차등 A+B+C)" if x == "new_2026" else "구법 단가 시뮬레이션 (균등단가 비교)",
            )
            s["scheme_2026"] = scheme_opt

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
        }
        for cohort, f in ((tax_yr - 1, p1), (tax_yr - 2, p2))
    }

    active_pm_basis = s.get("pm_basis", R.PM_BASIS_FILED)
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
    basis_pill_html = (
        f"<span class='ec-basis-pill-filed'>📋 현재 기준: {basis_lbl} (원칙)</span>"
        if pkg["pm_basis"] == R.PM_BASIS_FILED
        else f"<span class='ec-basis-pill-recalc'>⚖️ 현재 기준: {basis_lbl} (원천징수부 재계산)</span>"
    )

    k1, k2, k3, k4 = st.columns(4)
    with k1:
        st.markdown(
            f"<div class='ec-summary-card green'>"
            f"<div class='card-lbl'>① {tax_yr}년 총 공제세액 ({basis_lbl})</div>"
            f"<div class='card-val'>{pkg['total_credit_gross_won']:,}원</div>"
            f"<div class='card-sub'>당해 신규 {pkg['cur_base_credit_won']:,}원 + 연속 {pkg['total_continued_credit_won']:,}원 + 추가 {pkg['additional_credit_won']:,}원</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
    with k2:
        st.markdown(
            f"<div class='ec-summary-card {'red' if pkg['total_clawback_net_payable_won'] > 0 else ''}'>"
            f"<div class='card-lbl'>② 사후관리 추가납부세액 ({basis_lbl})</div>"
            f"<div class='card-val'>{pkg['total_clawback_net_payable_won']:,}원</div>"
            f"<div class='card-sub'>차감전 추징 {pkg['total_clawback_gross_won']:,}원 − 미공제 이월액 소멸 {pkg['total_carryforward_offset_won']:,}원</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
    with k3:
        st.markdown(
            f"<div class='ec-summary-card'>"
            f"<div class='card-lbl'>③ 농어촌특별세 (실공제세액의 20%)</div>"
            f"<div class='card-val'>{pkg['rural_special_tax_won']:,}원</div>"
            f"<div class='card-sub'>실공제 {pkg['actual_deducted_credit_won']:,}원 기준 (당해 이월액·추징액 제외)</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
    with k4:
        st.markdown(
            f"<div class='ec-summary-card green'>"
            f"<div class='card-lbl'>④ 실질 순절세 효과 (① − ② − ③)</div>"
            f"<div class='card-val'>{pkg['net_after_rural_tax_won']:,}원</div>"
            f"<div class='card-sub'>농특세 차감 전 순공제액: {pkg['net_tax_benefit_won']:,}원</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

    c_th1, c_th2 = st.columns([3.4, 2.2])
    with c_th1:
        st.markdown(
            f"<div class='ec-tbl-header-bar'>"
            f"<span class='ec-tbl-header-title'>📊 1. 연도별·사후관리 총인원수(연인원) / 평균인원수 비교표 {basis_pill_html}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
    with c_th2:
        _render_pm_basis_selector_right(s, widget_key=f"pm_basis_sel_hc_{tax_yr}")

    is_recalc = pkg["pm_basis"] == R.PM_BASIS_RECALC

    def _fmt(v, f=".2f"):
        return "-" if v is None else format(float(v), f)

    def _base_row(cohort: int, base: dict, s_year: dict, pf: dict) -> dict:
        use = base.get("recalc" if is_recalc else "filed") or {}
        reg, yth = use.get("init_reg"), use.get("init_yth")
        if is_recalc and s_year.get("has_data") and not s_year.get("from_filed"):
            rtot, ytot = s_year["reg_total"], s_year["yth_total"]
        else:
            rtot, ytot = pf.get("상시_총인원"), pf.get("청년등_총인원")
        gen = None if reg is None or yth is None else round(max(0.0, reg - yth), 2)
        gtot = None if rtot is None or ytot is None else round(max(0.0, float(rtot) - float(ytot)), 2)
        other = base.get("filed" if is_recalc else "recalc") or {}
        borrowed = base.get("borrowed") or []
        return {
            "구분": f"{cohort}년 사후관리 기초 [{basis_lbl}]",
            "전체 [총인원(연인원) / 평균]": f"{_fmt(rtot, 'g')}명 / {_fmt(reg)}명",
            "청년등 [총인원 / 평균]": f"{_fmt(ytot, 'g')}명 / {_fmt(yth)}명",
            "청년등 외 [총인원 / 평균]": f"{_fmt(gtot, 'g')}명 / {_fmt(gen)}명",
            "적용 기준 및 비교 안내": (
                f"{'기신고 기준' if is_recalc else '세법원칙 기준'}이면: 상시 {_fmt(other.get('init_reg'))}명 / 청년등 {_fmt(other.get('init_yth'))}명"
                + (f" · 세법원칙 기준 중 {', '.join(borrowed)}은 사원표가 없어 기신고 숫자 사용" if is_recalc and borrowed else "")
            ),
        }

    cur_b2_gen = round(max(0.0, pkg["cur_s"]["b2_reg"] - pkg["cur_s"]["b2_yth"]), 2)
    cur_b2_gtot = round(max(0.0, pkg["cur_s"]["reg_total"] - pkg["cur_s"]["b2_yth_total"]), 2)
    cur_b3_gen = round(max(0.0, pkg["cur_s"]["b3_reg"] - pkg["cur_s"]["b3_yth"]), 2)
    cur_b3_gtot = round(max(0.0, pkg["cur_s"]["reg_total"] - pkg["cur_s"]["b3_yth_total"]), 2)

    hc_rows = [
        {
            "구분": f"{tax_yr}년 귀속 [{b3_title}]",
            "전체 [총인원(연인원) / 평균]": f"{pkg['cur_s']['reg_total']:g}명 / {pkg['cur_s']['regular']:.2f}명",
            "청년등 [총인원 / 평균]": f"{pkg['cur_s']['yth_total']:g}명 / {pkg['cur_s']['youth']:.2f}명",
            "청년등 외 [총인원 / 평균]": f"{pkg['cur_s']['non_youth_total']:g}명 / {pkg['cur_s']['non_youth']:.2f}명",
            "적용 기준 및 비교 안내": f"당해({tax_yr}년) 원천징수부 기준 (÷{pkg['cur_s']['months_in_year']}개월 · {'인별절사' if tax_yr >= 2025 else '전체절사'})",
        },
    ]
    if _has_year_data(s, tax_yr - 1):
        hc_rows.append(
            {
                "구분": f"{tax_yr}년 귀속 [{b4_title}]",
                "전체 [총인원(연인원) / 평균]": f"{pkg['cur_s']['reg_total']:g}명 / {pkg['cur_s']['b2_reg']:.2f}명",
                "청년등 [총인원 / 평균]": f"{pkg['cur_s']['b2_yth_total']:g}명 / {pkg['cur_s']['b2_yth']:.2f}명",
                "청년등 외 [총인원 / 평균]": f"{cur_b2_gtot:g}명 / {cur_b2_gen:.2f}명",
                "적용 기준 및 비교 안내": f"{tax_yr-1}년 입사 청년 연령경과(34세 초과) 간주 특례 반영 ({'인별절사' if (tax_yr-1) >= 2025 else '전체절사'})",
            }
        )
    if has_t2_data:
        hc_rows.append(
            {
                "구분": f"{tax_yr}년 귀속 [{b5_title}]",
                "전체 [총인원(연인원) / 평균]": f"{pkg['cur_s']['reg_total']:g}명 / {pkg['cur_s']['b3_reg']:.2f}명",
                "청년등 [총인원 / 평균]": f"{pkg['cur_s']['b3_yth_total']:g}명 / {pkg['cur_s']['b3_yth']:.2f}명",
                "청년등 외 [총인원 / 평균]": f"{cur_b3_gtot:g}명 / {cur_b3_gen:.2f}명",
                "적용 기준 및 비교 안내": f"{tax_yr-2}년 입사 청년 연령경과(34세 초과) 간주 특례 반영 ({'인별절사' if (tax_yr-2) >= 2025 else '전체절사'})",
            }
        )
    if pkg.get("base_y1"):
        hc_rows.append(_base_row(tax_yr - 1, pkg["base_y1"], pkg["prev_s"], p1))
    if pkg.get("base_y2"):
        hc_rows.append(_base_row(tax_yr - 2, pkg["base_y2"], pkg["prev2_s"], p2))
    st.dataframe(pd.DataFrame(hc_rows), use_container_width=True, hide_index=True)

    c_tx1, c_tx2 = st.columns([3.4, 2.2])
    with c_tx1:
        st.markdown(
            f"<div class='ec-tbl-header-bar'>"
            f"<span class='ec-tbl-header-title'>💰 2. 항목별 공제세액 및 사후관리세액(연속공제·추가납부) 산출내역 {basis_pill_html}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
    with c_tx2:
        _render_pm_basis_selector_right(s, widget_key=f"pm_basis_sel_tax_{tax_yr}")

    pm1 = pkg["pm_y1"]
    pm2 = pkg["pm_y2"]
    pm1_alt = pkg["pm_y1_recalc"] if not is_recalc else pkg["pm_y1_filed"]
    pm2_alt = pkg["pm_y2_recalc"] if not is_recalc else pkg["pm_y2_filed"]
    alt_lbl = "세법원칙 재계산" if not is_recalc else "기신고 기준"

    abc_tiers = pkg["abc_res"]["tiers"]
    abc_desc = (
        f"A(1년차) {pkg['cur_new_a_won']:,}원"
        + (f" + B(2년차) {pkg['cur_new_b_won']:,}원" if abc_tiers["B"]["comp_year"] else "")
        + (f" + C(3년차) {pkg['cur_new_c_won']:,}원" if abc_tiers["C"]["comp_year"] else "")
        + f" ({pkg['hurdle_res']['note']})"
    )
    detail_rows = [
        {
            "항목 구분": f"① {b3_title}",
            "적용 기준 · 판정 케이스": "2026 신법(A+B+C)" if pkg["active_scheme"] == "new_2026" else "구법 단가",
            "인정 인원 (청년등 / 청년외)": f"청년등 +{pkg['hurdle_res']['recognized_youth_inc'] if pkg['active_scheme']=='new_2026' else pkg['cur_inc']['youth_inc']:.2f}명 / 청년외 +{pkg['hurdle_res']['recognized_non_youth_inc'] if pkg['active_scheme']=='new_2026' else pkg['cur_inc']['non_youth_inc']:.2f}명",
            "당해 공제세액 (+)": f"{pkg['cur_base_credit_won']:,}원",
            "추가납부 추징세액 (-)": "0원",
            "산출근거 및 기준별 비교": (
                f"전체 증가 +{pkg['cur_inc']['total_inc']:.2f}명 한도(Cap) 적용 · "
                + (
                    f"{abc_desc} (구법 적용 시 {pkg['cur_legacy_total_won']:,}원)"
                    if pkg["active_scheme"] == "new_2026"
                    else f"구법 단가(청년 {pkg['rates_legacy']['청년등']:,}만/일반 {pkg['rates_legacy']['청년등외']:,}만) 적용"
                )
            ),
        },
        {
            "항목 구분": f"② {b4_title} (2차년도)",
            "적용 기준 · 판정 케이스": f"[{basis_lbl}] {pm1['case_code']}",
            "인정 인원 (청년등 / 청년외)": f"유지 청년 {pm1['retained_yth_inc']:.2f}명 / 일반 {pm1['retained_gen_inc']:.2f}명",
            "당해 공제세액 (+)": f"{pm1['continued_credit_won']:,}원",
            "추가납부 추징세액 (-)": f"{pm1['clawback_net_payable_won']:,}원 (이월차감 {pm1['carryforward_offset_won']:,}원)",
            "산출근거 및 기준별 비교": (
                f"{pm1['formula_note']} | 💡 [{alt_lbl} 선택 시: 연속공제 {pm1_alt['continued_credit_won']:,}원 / 추가납부 {pm1_alt['clawback_net_payable_won']:,}원]"
            ),
        },
        {
            "항목 구분": f"③ {b5_title} (3차년도)",
            "적용 기준 · 판정 케이스": f"[{basis_lbl}] {pm2['case_code']}",
            "인정 인원 (청년등 / 청년외)": f"유지 청년 {pm2['retained_yth_inc']:.2f}명 / 일반 {pm2['retained_gen_inc']:.2f}명",
            "당해 공제세액 (+)": f"{pm2['continued_credit_won']:,}원",
            "추가납부 추징세액 (-)": f"{pm2['clawback_net_payable_won']:,}원 (이월차감 {pm2['carryforward_offset_won']:,}원)",
            "산출근거 및 기준별 비교": (
                f"{pm2['formula_note']} | 💡 [{alt_lbl} 선택 시: 연속공제 {pm2_alt['continued_credit_won']:,}원 / 추가납부 {pm2_alt['clawback_net_payable_won']:,}원]"
            ),
        },
        {
            "항목 구분": "④ 육아휴직 복귀 · 정규직 전환 추가공제 및 추징",
            "적용 기준 · 판정 케이스": "상시근로자 비감소 충족" if pkg["non_decrease_ok"] else "상시근로자 감소로 추가공제 배제",
            "인정 인원 (청년등 / 청년외)": f"복귀 {pkg['parental_ret_cnt']}명 / 전환 {pkg['reg_conv_cnt']}명 / 추징 {pkg['early_term_add_cnt']}명",
            "당해 공제세액 (+)": f"{pkg['additional_credit_won']:,}원",
            "추가납부 추징세액 (-)": f"{pkg['additional_clawback_won']:,}원",
            "산출근거 및 기준별 비교": f"1인당 {R.ADDITIONAL_CREDIT_PER_PERSON.get(corp_size, 0):,}만원 (출산전후휴가자 당해 제외 -{pkg['maternity_rep_cnt']:.2f}명 / 직전 제외 -{pkg.get('maternity_prev_cnt', 0.0):.2f}명 반영)",
        },
    ]
    st.dataframe(pd.DataFrame(detail_rows), use_container_width=True, hide_index=True)

    _save_ec_to_disk(s)
    st.markdown("<div class='ec-nav-divider'></div>", unsafe_allow_html=True)
    c_prev, _, c_next = st.columns([1.3, 4.5, 1.3])
    if c_prev.button("< 이전(2단계)", use_container_width=True):
        s["step"] = 2
        _save_ec_to_disk(s)
        st.rerun()
    if c_next.button("다음(4단계 보고서)", type="primary", use_container_width=True):
        s["step"] = 4
        _save_ec_to_disk(s)
        st.rerun()


# ══════════════════════════════════════════════════════════════════
# 7. 4단계: 최종 검토보고서 및 다운로드
# ══════════════════════════════════════════════════════════════════
def _build_report_markdown(s: dict) -> str:
    _ensure_built_for_tax_year(s)
    b = s.get("biz") or {}
    sub_list = s.get("sub_biz_list") or []
    tax_yr = int(s.get("tax_year") or R.DEFAULT_TAX_YEAR)
    corp_nm = (b.get("상호") or "").strip() or "미입력 법인(사업자)"
    corp_sz = b.get("기업구분", "중소기업")
    cap_bool = H.is_capital_area(b.get("사업장소재지", ""))
    is_capital = True if cap_bool is None else bool(cap_bool)
    loc_label = "수도권" if is_capital else "수도권 외(비수도권)"

    totals_all = _ensure_totals_snapshot(s)
    pkg = s.get("calc_pkg")
    ps = s.get("prev_summary") or {}
    p1 = ps.get(str(tax_yr - 1)) or {}
    p2 = ps.get(str(tax_yr - 2)) or {}
    if not pkg or int(pkg.get("tax_year", 0)) != tax_yr:
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
                }
                for cohort, f in ((tax_yr - 1, p1), (tax_yr - 2, p2))
            },
            additional_inputs=s.get("additional_inputs"),
            scheme_2026=s.get("scheme_2026", "new_2026"),
            pm_basis=s.get("pm_basis", R.PM_BASIS_FILED),
        )

    pm1 = pkg["pm_y1"]
    pm2 = pkg["pm_y2"]
    basis_lbl = pkg.get("pm_basis_label", "기신고 기준")
    b3_title, b4_title, b5_title = _block_titles_for_year(tax_yr, two_line=False)
    last_m_cur = H.detect_last_paid_month(s.get("people") or {}, tax_yr)
    est_line = (
        f"\n> ⚠️ **[가결산 추정치 안내]** 본 보고서는 {tax_yr}년 {last_m_cur}월 가결산 원천징수부를 기준으로 미도래 월({last_m_cur+1}~12월)을 "
        f"'연말까지 재직 가정(1 자동 채움)'하여 산출한 시뮬레이션 추정치입니다. 확정신고 시에는 12월 최종 원천징수부를 반영하여 재산출하시기 바랍니다.\n"
        if (s.get("assume_year_end", True) and last_m_cur < 12)
        else ""
    )

    sub_biz_lines = []
    for idx, sb in enumerate(sub_list, start=2):
        sb_nm = sb.get("상호") or f"제{idx}사업장"
        sb_no = sb.get("사업자번호") or "-"
        sb_addr = sb.get("사업장소재지") or "-"
        sb_tp = sb.get("구분") or "합산사업장"
        suc_info = ""
        if float(sb.get("승계_직전상시") or 0.0) > 0:
            suc_info = f" / 피승계 직전상시 `{float(sb.get('승계_직전상시')):.2f}명`(청년등 `{float(sb.get('승계_직전청년') or 0.0):.2f}명`) 합산"
        sub_biz_lines.append(
            f"- **합산 제{idx}사업장 ({sb_tp})**: {sb_nm} (사업자번호: `{sb_no}` / 소재지: `{sb_addr}`{suc_info})"
        )

    lines = [
        f"# 📑 {tax_yr}년 귀속 통합고용세액공제 및 사후관리 검토보고서",
        est_line,
        "## 1. 사업자 기본사항",
        f"- **주사업장 상호(법인명)**: {corp_nm} (사업자등록번호: `{b.get('사업자번호') or '-'}`)",
        *sub_biz_lines,
        f"- **기업규모 / 소재지**: **{corp_sz}** / **{loc_label}** (`{b.get('사업장소재지') or '-'}`)",
        f"- **업태 · 종목**: {b.get('업태') or '-'} · {b.get('종목') or '-'} (설립·개업일: `{b.get('설립일') or '-'}`)",
        f"- **사업연도 월수**: 당해({tax_yr}년) {b.get('당해_월수', 12)}개월 / 직전({tax_yr-1}년) {b.get('전년_월수', 12)}개월",
        f"- **사후관리 산정 기준**: **{basis_lbl}** ({'공제감면세액계산서 등 기신고 수치 원칙 적용' if pkg.get('pm_basis') == R.PM_BASIS_FILED else '원천징수부 세법원칙 재계산 수치 적용'})",
        "",
        f"## 2. 최종 공제세액 및 추가납부세액(추징) 요약 [{basis_lbl}]",
        "| 구분 | 금액 (원) | 비고 |",
        "| :--- | ---: | :--- |",
        f"| **① {b3_title}** | **{pkg['cur_base_credit_won']:,}원** | 청년등 +{pkg['cur_inc']['youth_inc']:.2f}명, 청년외 +{pkg['cur_inc']['non_youth_inc']:.2f}명 |",
        f"| **② {tax_yr-1}년·{tax_yr-2}년 기공제분 연속공제액 ({basis_lbl})** | **{pkg['total_continued_credit_won']:,}원** | 2차년도 {pm1['continued_credit_won']:,}원 + 3차년도 {pm2['continued_credit_won']:,}원 |",
        f"| **③ 육아휴직 복귀 · 정규직 전환 추가공제액** | **{pkg['additional_credit_won']:,}원** | 복귀 {pkg['parental_ret_cnt']}명 / 전환 {pkg['reg_conv_cnt']}명 |",
        f"| **합계: 당해 총 공제세액 (①+②+③)** | **{pkg['total_credit_gross_won']:,}원** | 세액공제신청서 반영 금액 |",
        f"| **④ 사후관리 추가납부세액 ({basis_lbl}, 이월차감 후)** | **{pkg['total_clawback_net_payable_won']:,}원** | 차감전 {pkg['total_clawback_gross_won']:,}원 − 이월공제 소멸 {pkg['total_carryforward_offset_won']:,}원 |",
        f"| **⑤ 농어촌특별세 (실공제세액의 20%)** | **{pkg['rural_special_tax_won']:,}원** | 실공제 {pkg['actual_deducted_credit_won']:,}원 기준 (농어촌특별세법 제5조 제1항) |",
        f"| **최종 실질 순절세액 (합계 − ④ − ⑤)** | **{pkg['net_after_rural_tax_won']:,}원** | 당해 미공제 이월액 {pkg['cur_unclaimed_cf_won']:,}원 반영 |",
        "",
        "## 3. 연도별·사후관리 코호트별 상시근로자 수 상세 (총인원수 / 평균인원수)",
        "| 구분 | 전체 상시 [총인원 / 평균] | 청년등 [총인원 / 평균] | 청년등 외 [총인원 / 평균] | 적용 기준 |",
        "| :--- | ---: | ---: | ---: | :--- |",
        f"| **{tax_yr}년 귀속 [{b3_title}]** | {pkg['cur_s']['reg_total']:g}명 / {pkg['cur_s']['regular']:.2f}명 | {pkg['cur_s']['yth_total']:g}명 / {pkg['cur_s']['youth']:.2f}명 | {pkg['cur_s']['non_youth_total']:g}명 / {pkg['cur_s']['non_youth']:.2f}명 | 근로계약 체결일 현재 연령 기준 ({'인별절사' if tax_yr >= 2025 else '전체절사'}) |",
        f"| **{tax_yr}년 귀속 [{b4_title}]** | {pkg['cur_s']['reg_total']:g}명 / {pkg['cur_s']['b2_reg']:.2f}명 | {pkg['cur_s']['b2_yth_total']:g}명 / {pkg['cur_s']['b2_yth']:.2f}명 | {round(max(0.0, pkg['cur_s']['reg_total']-pkg['cur_s']['b2_yth_total']),2):g}명 / {round(max(0.0, pkg['cur_s']['b2_reg']-pkg['cur_s']['b2_yth']),2):.2f}명 | 구 조특령 제26조의8 제5항 연령경과 간주 특례 |",
        f"| **{tax_yr}년 귀속 [{b5_title}]** | {pkg['cur_s']['reg_total']:g}명 / {pkg['cur_s']['b3_reg']:.2f}명 | {pkg['cur_s']['b3_yth_total']:g}명 / {pkg['cur_s']['b3_yth']:.2f}명 | {round(max(0.0, pkg['cur_s']['reg_total']-pkg['cur_s']['b3_yth_total']),2):g}명 / {round(max(0.0, pkg['cur_s']['b3_reg']-pkg['cur_s']['b3_yth']),2):.2f}명 | 구 조특령 제26조의8 제5항 연령경과 간주 특례 |",
        f"| **{tax_yr-1}년 사후관리 기초 ({basis_lbl})** | - / {pm1['init_reg']:.2f}명 | - / {pm1['init_yth']:.2f}명 | - / {round(max(0.0, pm1['init_reg']-pm1['init_yth']),2):.2f}명 | 1차 사후관리 비교 기준 (증가 청년 {pm1['init_yth_inc']:.2f}명 / 일반 {pm1['init_gen_inc']:.2f}명) |",
        f"| **{tax_yr-2}년 사후관리 기초 ({basis_lbl})** | - / {pm2['init_reg']:.2f}명 | - / {pm2['init_yth']:.2f}명 | - / {round(max(0.0, pm2['init_reg']-pm2['init_yth']),2):.2f}명 | 2차 사후관리 비교 기준 (증가 청년 {pm2['init_yth_inc']:.2f}명 / 일반 {pm2['init_gen_inc']:.2f}명) |",
        "",
        "## 4. 사후관리 판정 및 실무 체크포인트 해설",
        f"1. **{b4_title} [{basis_lbl}] ({pm1['case_code']} - {pm1['case_title']})**: {pm1['formula_note']}",
        f"2. **{b5_title} [{basis_lbl}] ({pm2['case_code']} - {pm2['case_title']})**: {pm2['formula_note']}",
        "3. **4대 사후관리 추징 완화 및 복수 사업장 합산 특례 점검**:",
        "   - **본·지점 및 기중 사업 양도·포괄양수 합산(조특령 제26조의8 제10항)**: 동일 과세단위 내 본·지점 근로자 및 포괄양수·승계 사업장 근로자는 통산하여 상시근로자 수를 산정합니다.",
        "   - **이월공제 미공제액 차감 특례(조특법 제29조의8·제144조)**: 최저한세 등으로 실제 감면받지 못하고 이월된 세액이 있는 경우 현금 추가납부 대신 이월공제액을 우선 소멸시킵니다.",
        "   - **청년 연령경과 간주 특례(구 조특령 제26조의8 제5항)**: 최초 공제연도에 실제로 청년등이었던 근로자는 사후관리 기간 중 34세를 초과하더라도 청년등 상시근로자로 유지됩니다.",
        "   - **출산전후휴가자 대체인력 특례(조특령 제26조의8 제7항, 2024.2.29 신설)**: 추가공제 비감소 요건 판정 시 대체인력을 채용한 출산전후휴가자는 상시근로자 산정에서 제외(차감)합니다.",
        "   - **이자상당가산액 면제**: 고용 감소로 인한 추가납부세액은 원금만 납부하며 이자상당가산액은 가산되지 않습니다.",
    ]
    if s.get("pro_audit_comment"):
        lines.extend(["", "## 5. 👑 Pro/Argon AI 심층 세무진단 코멘트", s["pro_audit_comment"]])
    return "\n".join(lines)


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
        trunc_mode = "인별절사" if int(y) >= 2025 else "전체절사"
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


def _page_report():
    s = _S()
    _ensure_built_for_tax_year(s)
    tax_yr = int(s["tax_year"])
    md_text = _build_report_markdown(s)
    csv_bytes = _build_csv_bytes(s)
    corp_nm = (s.get("biz", {}).get("상호") or "통합고용세액공제").strip()
    shown_years = _years(s)

    st.markdown(f"### 📑 4. 통합고용세액공제 및 사후관리 최종 보고서 ({tax_yr}년 귀속)")

    last_m_cur = H.detect_last_paid_month(s.get("people") or {}, tax_yr)
    if s.get("assume_year_end", True) and last_m_cur < 12:
        st.markdown(
            f"<div class='ec-warn-banner'>"
            f"⚠️ <b>[기중 가결산 추정치 안내]</b> 본 보고서는 {tax_yr}년 <b>{last_m_cur}월 가결산</b> 기준으로 "
            f"{last_m_cur+1}~12월을 '연말까지 재직 가정(1 자동 채움)'하여 산출된 추정 보고서입니다."
            f"</div>",
            unsafe_allow_html=True,
        )

    c_dl1, c_dl2, c_dl3, _ = st.columns([1.8, 1.8, 1.8, 1.8])
    with c_dl1:
        st.download_button(
            "📥 검토보고서 다운로드 (.md)",
            data=md_text.encode("utf-8"),
            file_name=f"{corp_nm}_{tax_yr}년귀속_통합고용세액공제_검토보고서.md",
            mime="text/markdown",
            use_container_width=True,
        )
    with c_dl2:
        st.download_button(
            "📊 상시근로자 명세표 다운로드 (.csv)",
            data=csv_bytes,
            file_name=f"{corp_nm}_{tax_yr}년귀속_상시근로자명세_사후관리블록포함.csv",
            mime="text/csv",
            use_container_width=True,
        )
    with c_dl3:
        with st.container(key="ec_btn_pdf_rep_wrap"):
            st.download_button(
                "📕 전체 상시명세 PDF 다운 (.pdf)",
                data=_build_schedule_pdf_bytes(s, shown_years, include_summary=True),
                file_name=f"{corp_nm}_{tax_yr}년귀속_전체연도_상시근로자명세.pdf",
                mime="application/pdf",
                use_container_width=True,
                key="dl_pdf_report_all",
            )

    with st.container(border=True):
        st.markdown(md_text)

    st.markdown("<div class='ec-nav-divider'></div>", unsafe_allow_html=True)
    c_prev, _, c_reset = st.columns([1.3, 4.5, 1.3])
    if c_prev.button("< 이전(3단계)", use_container_width=True):
        s["step"] = 3
        _save_ec_to_disk(s)
        st.rerun()
    if c_reset.button("처음으로(1단계)", use_container_width=True):
        s["step"] = 1
        _save_ec_to_disk(s)
        st.rerun()


# ══════════════════════════════════════════════════════════════════
# 8. 진입점
# ══════════════════════════════════════════════════════════════════
def render_credit_wizard(extract_file_fn, log_tokens_fn=None, active_room_key: str = "", **_):
    s = _S()
    st.markdown(CSS, unsafe_allow_html=True)
    _top_status_bar(s)
    _progress(s["step"])

    if s["step"] == 1:
        _page_upload(extract_file_fn, log_tokens_fn, active_room_key)
    elif s["step"] == 2:
        _page_employees(active_room_key, log_tokens_fn=log_tokens_fn)
    elif s["step"] == 3:
        _page_calculation()
    else:
        _page_report()
    _save_ec_to_disk(s)