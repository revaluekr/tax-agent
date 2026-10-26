# -*- coding: utf-8 -*-
"""
통합고용세액공제 화면 — 1단계(자료 업로드) · 2단계(사원정보) · 3단계(공제액·사후관리 계산) · 4단계(보고서)

[디자인 & 기능 업그레이드 및 클로드 크로스체크 14개 항목 + 사후관리 '기신고 기준' vs '세법원칙 기준' 선택 기능 완비]
1. "자율 에이전트AI"(app.py)와 100% 동일한 Pretendard 폰트, 에메랄드 그린(#16a34a/#22c55e) & 다크 네이비(#1e293b) 테마,
   상단 슬림 미니 상태바(.top-mini-status-bar), 사이드바 카드 타이틀(.sb-card-title) 및 배지(.sb-badge-green) 완벽 통일.
2. 1단계(자료 업로드) 레이아웃 개선:
   - 『2025년 공제감면세액계산서 (기신고 상시근로자 명세서 포함)』 항목을 체크리스트에 추가하여 업로드 및 드롭다운 선택 시 즉시 초록불 `🟢` 점등.
   - 하단: 파일 업로드 드롭존을 "자율 에이전트AI" 채팅 입력창과 동일한 위치(화면 맨 하단)·너비의 슬림 바 형태로 배치.
3. 2단계(사원정보) 시인성 대폭 개선 및 첨부 엑셀 디자인(2단 그룹 헤더 & 4대 우측 블록) 탑재.
4. 3단계(공제액·사후관리 계산) & 4단계(보고서):
   - 사후관리 총인원수(연인원)/평균인원수 비교표 및 사후관리세액(연속공제·추가납부) 상세 산출표 **오른쪽 위에 기준 선택기(`기신고 기준 (원칙)` vs `세법원칙 기준 (재계산)`)**를 배치하여,
     기본값은 **『기신고 기준』**으로 표시하고 사용자가 클릭 한 번으로 **『세법원칙 기준』**과 비교·전환할 수 있도록 구현.
"""
from __future__ import annotations

import io
import csv
import json
import uuid
import pandas as pd
import streamlit as st
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, JsCode

from . import rules as R
from . import headcount as H
from . import parsers as P

STEPS = ["자료 업로드", "사원정보", "공제액 계산", "보고서"]
MONTH_COLS = [f"M{m:02d}" for m in range(1, 13)]
INFO_COLS = ["성명", "생년월일", "입사일", "퇴사일"]
CLASS_COLS = ["고용유형", "제외사유", "청년등"]


# ══════════════════════════════════════════════════════════════════
# 0. 작업공간별 상태 보관 (작업공간 코드 전환 시 타 거래처와 섞이지 않도록 분리)
# ══════════════════════════════════════════════════════════════════
def _S() -> dict:
    ws_id = st.session_state.get("loaded_workspace_id") or "default_ec"
    store = st.session_state.setdefault("ec_by_ws", {})
    if ws_id not in store:
        store[ws_id] = {
            "step": 1,
            "tax_year": R.DEFAULT_TAX_YEAR,
            "files": {},            # 파일명 → {"key": 서류종류, "text": 본문}
            "uploader_ver": 0,
            "ext": None,
            "ext_sig": None,
            "built_sig": None,
            "biz": {},
            "biz_confirmed": [],
            "people": {},
            "year_recs": {},
            "prev_summary": {},     # 기신고 명세서(공제감면세액계산서) 또는 수기 입력 과거연도 인원·공제액·이월액·기추징액
            "additional_inputs": {  # 육아휴직 복귀·정규직 전환·출산전후휴가 대체인력·당해 이월공제액
                "parental_return_count": 0,
                "regular_conversion_count": 0,
                "additional_clawback_count": 0,
                "maternity_replacement_count": 0.0,
                "current_unclaimed_carryforward_won": 0,
            },
            "scheme_2026": "new_2026",
            "pm_basis": R.PM_BASIS_FILED,   # 사후관리 계산 기준: 기본값 'filed' (기신고 기준 원칙) / 선택 시 'recalc' (세법원칙 기준)
            "assume_year_end": True,        # 1번안 기본: 기중 자료 미도래 월 연말까지 재직 가정(1 자동 채움·노란색 표시)
            "show_all_4_blocks": True,      # 우측 사후관리·인별절사 4대 블록 전체 표시 여부
            "manual_extra_years": [],
            "grid_ver": {},
            "last_sent": {},
            "industry_alert_for": "",
            "next_pid_seq": 1,
        }
    st.session_state.ec = store[ws_id]
    return store[ws_id]


def _uploaded_wht_years(s: dict) -> set[int]:
    """실제로 원천징수부 파일이 업로드된 연도 집합을 반환합니다."""
    yrs = set()
    for f in (s.get("files") or {}).values():
        fk = str(f.get("key") or "")
        if fk.startswith("wht_"):
            ys = fk.replace("wht_", "").strip()
            if ys.isdigit():
                yrs.add(int(ys))
    for y_str, rows in ((s.get("ext") or {}).get("wht") or {}).items():
        if str(y_str).isdigit() and rows:
            yrs.add(int(y_str))
    return yrs


def _has_year_data(s: dict, year: int) -> bool:
    """특정 과세연도(예: 2024년)의 실제 원천징수부 사원 데이터 또는 기신고/수기 요약 데이터가 존재하는지 확인합니다."""
    if year in _uploaded_wht_years(s):
        return True
    if any(H.worked_in_year(p, year) for p in (s.get("people") or {}).values()):
        return True
    ps_y = (s.get("prev_summary") or {}).get(str(year)) or {}
    if (ps_y.get("상시") or 0.0) > 0 or (ps_y.get("청년등") or 0.0) > 0:
        return True
    return False


def _years(s: dict) -> list[int]:
    t = int(s["tax_year"])
    comp = H.valid_comparison_years_for_new_credit(t)
    active_years = {t, t - 1}
    for k in ("A", "B", "C"):
        if comp.get(k) is not None:
            active_years.add(int(comp[k]))

    active_years.update(_uploaded_wht_years(s))
    for my in (s.get("manual_extra_years") or []):
        if isinstance(my, int):
            active_years.add(my)

    return sorted(active_years, reverse=True)


def _all_possible_years(s: dict) -> list[int]:
    t = int(s["tax_year"])
    cands = {t - i for i in range(4)} | _uploaded_wht_years(s) | set(s.get("manual_extra_years") or [])
    return sorted(cands, reverse=True)


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
        "last_paid_month": last_m,
    }


# ══════════════════════════════════════════════════════════════════
# 1. "자율 에이전트AI" 100% 동일 톤앤매너 CSS + 슬림 하단 업로드바 + 우측 상단 기준 선택기 스타일
# ══════════════════════════════════════════════════════════════════
CSS = """
<style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');

/* 🪟 모달(Dialog) 창 기본 아담한 크기(520px) 복원 + 화면 정중앙(가로·세로 중앙) 배치 */
div[data-testid="stDialog"] {
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
}
div[data-testid="stDialog"] > div[role="dialog"],
div[role="dialog"] {
    width: 520px !important;
    max-width: 92vw !important;
    margin: auto !important;
    border-radius: 12px !important;
}
div[role="dialog"] li,
div[role="dialog"] p {
    font-family: 'Pretendard', 'Malgun Gothic', sans-serif !important;
    font-size: 0.95rem !important;
    line-height: 1.6 !important;
    color: #1e293b !important;
    word-break: keep-all !important;
}

/* 🧭 4단계 스텝 진행바 — 자율 에이전트 그린(#16a34a) & 네이비(#1e293b) 테마 */
.ec-steps {
    display: flex;
    gap: 8px;
    margin: 6px 0 16px 0;
    font-family: 'Pretendard', 'Malgun Gothic', sans-serif;
}
.ec-step {
    flex: 1;
    padding: 10px 14px;
    border-radius: 9px;
    background: #f8fafc;
    color: #64748b;
    font-size: 0.92rem;
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

/* 💬 1단계 하단 슬림 파일 업로드 바 — 자율 에이전트AI 하단 채팅창과 동일한 위치·크기·높이감 */
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

/* 🏢 사이드바 사업자정보 입력칸 색상 구분 (서류 확인=회색 잠금, 직접 입력=파란 글씨) */
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

/* 📋 1단계 서류 체크리스트 표 — 자율 에이전트 엔터프라이즈 네이비 테이블과 동일 */
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

/* 🎨 2단계 범례 칩 및 연도별 헤더·요약 KPI 바 */
.ec-legend {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin: 4px 0 8px 0;
}
.ec-legend span {
    display: inline-flex;
    align-items: center;
    padding: 3px 10px;
    border-radius: 6px;
    font-size: 0.81rem;
    font-weight: 700;
}
.ec-year-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    background: linear-gradient(90deg, #f1f5f9 0%, #ffffff 100%);
    border-left: 5px solid #1e3a8a;
    padding: 8px 14px;
    border-radius: 0 8px 8px 0;
    margin-top: 14px;
    margin-bottom: 6px;
}
.ec-year-title {
    font-size: 1.08rem;
    font-weight: 800;
    color: #1e3a8a;
}
.ec-year-sub {
    font-size: 0.83rem;
    font-weight: 600;
    color: #475569;
}
.ec-kpi-bar {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    background: #f8fafc;
    border: 1px solid #cbd5e1;
    border-left: 4px solid #16a34a;
    border-radius: 8px;
    padding: 8px 14px;
    margin: 4px 0 18px 0;
    align-items: center;
    justify-content: space-between;
}
.ec-kpi-items {
    display: flex;
    gap: 16px;
    flex-wrap: wrap;
    font-size: 0.90rem;
    color: #1e293b;
}
.ec-kpi-items b {
    color: #15803d;
    font-size: 0.98rem;
    font-weight: 800;
}
.ec-law-banner {
    background-color: #f8fafc;
    border: 1px solid #e2e8f0;
    border-left: 4px solid #22c55e;
    padding: 9px 14px;
    border-radius: 7px;
    color: #334155;
    font-size: 0.89rem;
    margin-bottom: 10px;
    line-height: 1.55;
}
.ec-warn-banner {
    background-color: #fffbeb;
    border: 1px solid #fde68a;
    border-left: 5px solid #f59e0b;
    padding: 10px 14px;
    border-radius: 7px;
    color: #92400e;
    font-size: 0.89rem;
    margin-bottom: 12px;
    line-height: 1.55;
    font-weight: 600;
}
.ec-nav-divider {
    border-top: 1px dashed #cbd5e1;
    margin: 14px 0 12px 0;
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
    font-size: 1.06rem;
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
    corp_sz = b.get("기업구분") or "중소기업"
    cap = H.is_capital_area(b.get("사업장소재지", ""))
    loc_str = "수도권" if cap is True else ("비수도권(수도권 외)" if cap is False else "소재지 미입력")
    tax_yr = int(s.get("tax_year") or R.DEFAULT_TAX_YEAR)
    pm_lbl = R.PM_BASIS_LABELS.get(s.get("pm_basis", R.PM_BASIS_FILED), "기신고 기준")
    law_ver = (
        f"{tax_yr}귀속 (사후관리: {pm_lbl})"
        if tax_yr >= 2025
        else f"{tax_yr}귀속 (구법 3년 균등공제 · 사후관리: {pm_lbl})"
    )
    step_nm = STEPS[max(0, min(len(STEPS) - 1, int(s.get("step", 1)) - 1))]

    st.markdown(
        f"<div class='top-mini-status-bar'>"
        f"<span>🧮 <b>통합고용세액공제 ({tax_yr}년 귀속)</b> &nbsp;|&nbsp; 🏢 <b>{corp_nm}</b> ({corp_sz} · {loc_str})</span>"
        f"<span>📌 현재 단계: <b>{s.get('step', 1)}단계 [{step_nm}]</b> &nbsp;·&nbsp; <span class='sb-badge-green'>{law_ver}</span></span>"
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
# 2. 별도 창(대화상자 — 520px 기본 크기 및 화면 정중앙 표시)
# ══════════════════════════════════════════════════════════════════
@st.dialog("📋 자료 확인 안내")
def _dlg_missing(msgs: list[str]):
    for m in msgs:
        st.markdown(f"- {m}")
    st.caption("확인을 누르면 현재까지 인식된 자료로 다음 단계로 넘어갑니다. 부족한 정보는 사원정보 화면과 사이드바에서 직접 입력·수정할 수 있습니다.")
    if st.button("✅ 확인 및 2단계(사원정보)로 이동", type="primary", use_container_width=True):
        _S()["go_step2"] = True
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


@st.dialog("🔍 법령·심판례 기반 오류 검토 결과")
def _dlg_review(items: list[tuple[str, str]]):
    errs = [m for lv, m in items if lv == "오류"]
    chks = [m for lv, m in items if lv == "확인"]
    if not items:
        st.success("✅ 법령 및 최신 심판례 기준 검토 결과, 발견된 오류나 특이사항이 없습니다.")
    if errs:
        st.markdown(f"#### 🚨 필수 수정 오류 ({len(errs)}건) — 수정해야 정확한 상시근로자 수가 계산됩니다.")
        for m in errs:
            st.markdown(f"- :red[**{m}**]")
    if chks:
        st.markdown(f"#### 💡 실무·심판례 확인 사항 ({len(chks)}건) — 사실관계가 맞다면 그대로 진행하셔도 됩니다.")
        for m in chks:
            st.markdown(f"- {m}")
    if st.button("닫기", type="primary", use_container_width=True):
        st.rerun()


# ══════════════════════════════════════════════════════════════════
# 3. 사이드바: 귀속사업연도(2024~2028) · 사업자정보 ("자율 에이전트AI" 카드 스타일 통일)
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

    # 📦 [사이드바 카드 A] 귀속사업연도 (2024 ~ 2028 전체 지원)
    with st.container(border=True):
        yr_badge = (
            f"<span class='sb-badge-green'>{tax_yr}년 (신법+사후관리)</span>"
            if tax_yr >= 2026
            else f"<span class='sb-badge-amber'>{tax_yr}년 (구법+사후관리)</span>"
        )
        st.markdown(
            f"<div class='sb-card-title'><span>📅 귀속사업연도</span>{yr_badge}</div>",
            unsafe_allow_html=True,
        )
        new_year = st.selectbox(
            "통합고용세액공제 계산 기준 사업연도",
            options=R.SUPPORTED_TAX_YEARS,
            index=R.SUPPORTED_TAX_YEARS.index(tax_yr),
            format_func=lambda y: f"{y}년 귀속 ({'신규공제 + ' + str(y-1) + '·' + str(y-2) + ' 사후관리'})",
            label_visibility="collapsed",
        )
        if new_year != s["tax_year"]:
            s["tax_year"] = new_year
            s["manual_extra_years"] = []
            s["built_sig"] = None
            st.rerun()

    # 📦 [사이드바 카드 B] 사업자정보
    with st.container(border=True, key="ec_biz"):
        b, conf = s["biz"], set(s["biz_confirmed"])
        cap = H.is_capital_area(b.get("사업장소재지", ""))
        if cap is True:
            loc_pill = "<span class='sb-badge-amber'>수도권 사업장</span>"
        elif cap is False:
            loc_pill = "<span class='sb-badge-green'>수도권 외(비수도권)</span>"
        else:
            loc_pill = "<span class='sb-badge-pro'>직접입력/자동추출</span>"

        st.markdown(
            f"<div class='sb-card-title'><span>🏢 사업자정보</span>{loc_pill}</div>",
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

        txt("상호(법인명)", "상호", "예: 주식회사 세무에이전트")
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
        b["전년_월수"] = c1.number_input(f"직전({tax_yr-1}년) 월수", 1, 12, max(1, _int(b.get("전년_월수"), 12)), key="ec_biz_pm")
        b["당해_월수"] = c2.number_input(f"당해({tax_yr}년) 월수", 1, 12, max(1, _int(b.get("당해_월수"), 12)), key="ec_biz_cm")

        if conf:
            if st.button("🔓 사업자정보 잠금 해제 (직접 수정)", use_container_width=True, key="btn_unlock_biz"):
                s["biz_confirmed"] = []
                st.rerun()

    ind = f"{b.get('업태', '')} {b.get('종목', '')}".strip()
    if ind and H.is_excluded_industry(ind) and s["industry_alert_for"] != ind:
        s["industry_alert_for"] = ind
        _dlg_industry(ind)


# ══════════════════════════════════════════════════════════════════
# 4. 1단계: 자료 업로드 (2025년 공제감면세액계산서 포함 체크리스트 + 중단 파일목록 + 하단 슬림 업로드바)
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
            "<b>① 2026년 최초 공제</b>, <b>② 2025년 귀속분 1차 사후관리(2차년도 연속공제·추징)</b>, "
            "<b>③ 2024년 귀속분 2차 사후관리(3차년도 연속공제·추징)</b>를 함께 검토합니다. "
            "사후관리는 <b>『기신고 기준』(2025년 공제감면세액계산서 등)을 원칙</b>으로 하되, 3단계 표 우측 상단에서 <b>『세법원칙 기준(원천징수부 재계산)』</b>을 선택해 비교할 수 있습니다."
            "</div>",
            unsafe_allow_html=True,
        )
    elif tax_yr in (2024, 2025):
        st.markdown(
            f"<div class='ec-law-banner'>"
            f"💡 <b>[{tax_yr}년 귀속 세액공제 및 사후관리 안내]</b> {tax_yr}년 당해 신규공제뿐만 아니라 "
            f"<b>{tax_yr-1}년 귀속분 1차 사후관리</b> 및 <b>{tax_yr-2}년 귀속분 2차 사후관리(추가납부세액·연속공제)</b>까지 동시에 계산합니다."
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

    # 🎯 [초록불 즉시 점등 핵심 구조]
    docs_table_slot = st.empty()
    uploaded_list_slot = st.container()

    # 💬 [맨 하단 슬림 파일 업로드 바 — 자율 에이전트AI 채팅창과 동일한 위치·크기]
    st.markdown(
        "<div class='ec-bottom-upload-label'>"
        "<span>📥 <b>파일 추가 업로드</b> (PDF·엑셀·CSV·이미지 파일을 아래 바에 끌어다 놓거나 클릭하여 선택하세요)</span>"
        f"<span style='color:#16a34a;font-size:0.80rem;'>{tax_yr-2}·{tax_yr-1}·{tax_yr}년 원천징수부 · {tax_yr-1}년 공제감면세액계산서 자동 인식</span>"
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
                s["files"][u.name] = {"key": P.classify_file(u.name, text), "text": text}
        s["uploader_ver"] += 1
        st.rerun()

    with uploaded_list_slot:
        if s["files"]:
            with st.container(border=True):
                c_h1, c_h2 = st.columns([4, 1])
                with c_h1:
                    st.markdown(
                        f"**📎 업로드된 파일 목록 ({len(s['files'])}건)** — *오른쪽 드롭다운에서 서류 종류를 선택하면 상단 표에 즉시 초록불(🟢)이 켜집니다.*"
                    )
                with c_h2:
                    if st.button("🗑️ 전체 파일 비우기", use_container_width=True, key="ec_clear_all_files"):
                        s["files"] = {}
                        s["ext"] = None
                        s["ext_sig"] = None
                        s["built_sig"] = None
                        s["uploader_ver"] += 1
                        st.rerun()

                opts = [None] + list(all_labels.keys())
                for name, f in list(s["files"].items()):
                    c1, c2, c3 = st.columns([4.5, 4.5, 1.0])
                    c1.markdown(f"📄 **{name}**")
                    cur_k = f.get("key") if f.get("key") in opts else None
                    f["key"] = c2.selectbox(
                        "종류",
                        opts,
                        index=opts.index(cur_k),
                        key=f"ec_k_{name}",
                        format_func=lambda k: "⚠️ 서류 종류를 선택하세요 (미선택 시 분석 제외)"
                        if k is None
                        else all_labels.get(k, str(k)),
                        label_visibility="collapsed",
                    )
                    if c3.button("삭제", key=f"ec_del_{name}", use_container_width=True):
                        s["files"].pop(name, None)
                        st.rerun()

    have: dict[str, list[str]] = {}
    for name, f in s["files"].items():
        if f.get("key"):
            have.setdefault(f["key"], []).append(name)

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

    # ── 하단 네비게이션: 2단계의 [다음(3단계)] 버튼과 100% 동일한 가로 비율([5.8, 1.3]) 적용 ──
    st.markdown("<div class='ec-nav-divider'></div>", unsafe_allow_html=True)
    _, right = st.columns([5.8, 1.3])
    if right.button("다음(2단계)", type="primary", use_container_width=True):
        classified: dict[str, list[str]] = {}
        for name, f in s["files"].items():
            if f.get("key"):
                classified.setdefault(f["key"], []).append(name)
        sig = json.dumps(sorted((n, f.get("key")) for n, f in s["files"].items()), ensure_ascii=False)
        if s["ext_sig"] != sig:
            texts = {k: "\n\n".join(s["files"][n]["text"] for n in names) for k, names in classified.items()}
            if texts:
                with st.spinner("⚡ 서류에서 사업자·주주·임원·연도별 근로자·기신고 세액공제 정보를 병렬 고속 추출하고 있습니다..."):
                    s["ext"] = P.extract_all(texts, log_tokens_fn, room_key)
                    msgs = P.check_missing(classified, s["ext"], tax_yr)
            else:
                s["ext"] = {}
                msgs = P.check_missing(classified, None, tax_yr)
                msgs.append("올린 자료가 없어 사업자정보와 사원정보를 모두 직접 입력해야 합니다.")
            s["ext_sig"] = sig
            s["pending_msgs"] = msgs
        msgs = s.get("pending_msgs") or []
        if msgs:
            _dlg_missing(msgs)
        else:
            _enter_step2()
            st.rerun()


def _enter_step2():
    s = _S()
    sig = f"{s['ext_sig']}|{s['tax_year']}"
    if s["built_sig"] != sig:
        ext = s["ext"] or {}
        s["biz"], s["biz_confirmed"] = P.build_biz_info(ext, int(s["tax_year"]), existing_biz=s.get("biz"))
        s["people"], s["year_recs"] = P.build_people(ext, _all_possible_years(s))

        prev_from_doc = ((ext.get("prev_filing") or {}).get("연도별") or {})
        ps = s.setdefault("prev_summary", {})
        for y_str, vals in prev_from_doc.items():
            if isinstance(vals, dict):
                ps[str(y_str)] = {
                    "상시_총인원": float(vals.get("상시_총인원") or 0.0) if vals.get("상시_총인원") is not None else None,
                    "청년등_총인원": float(vals.get("청년등_총인원") or 0.0) if vals.get("청년등_총인원") is not None else None,
                    "상시": float(vals.get("상시") or 0.0) if vals.get("상시") is not None else None,
                    "청년등": float(vals.get("청년등") or 0.0) if vals.get("청년등") is not None else None,
                    "청년등_증가": float(vals.get("청년등_증가") or 0.0) if vals.get("청년등_증가") is not None else None,
                    "청년등외_증가": float(vals.get("청년등외_증가") or 0.0) if vals.get("청년등외_증가") is not None else None,
                    "공제세액": int(vals.get("공제세액") or 0) if vals.get("공제세액") is not None else 0,
                    "이월세액": int(vals.get("이월세액") or 0) if vals.get("이월세액") is not None else 0,
                    "기추징세액": int(vals.get("기추징세액") or 0) if vals.get("기추징세액") is not None else 0,
                }

        s["grid_ver"], s["last_sent"] = {}, {}
        s["built_sig"] = sig
        for k in list(st.session_state.keys()):
            if str(k).startswith("ec_biz_"):
                del st.session_state[k]
    s["step"] = 2


# ══════════════════════════════════════════════════════════════════
# 5. 2단계: 사원정보 표 (엑셀 2단 그룹헤더 + 1~12월 완벽 표시 + 4대 사후관리 블록)
# ══════════════════════════════════════════════════════════════════
JS_LOCKED = JsCode("""
function(p){
  if (p.node.rowPinned) return false;
  const L = (p.data._lock || '').split(',');
  return !L.includes(p.colDef.field);
}""")

JS_STYLE = JsCode("""
function(p){
  const baseFont = {fontFamily: 'Pretendard, Malgun Gothic, sans-serif', fontSize: '12.5px', paddingLeft: '5px', paddingRight: '5px'};
  if (p.node.rowPinned) return Object.assign(baseFont, {backgroundColor:'#dcfce7', color:'#14532d', fontWeight:'800'});
  const L = (p.data._lock || '').split(',');
  if (L.includes(p.colDef.field)) return Object.assign(baseFont, {backgroundColor:'#e2e8f0', color:'#0f172a', fontWeight:'600'});
  return Object.assign(baseFont, {backgroundColor:'#ffffff', color:'#1d4ed8', fontWeight:'600'});
}""")

JS_STYLE_CENTER = JsCode("""
function(p){
  const baseFont = {fontFamily: 'Pretendard, Malgun Gothic, sans-serif', fontSize: '12.5px', textAlign: 'center', paddingLeft: '4px', paddingRight: '4px'};
  if (p.node.rowPinned) return Object.assign(baseFont, {backgroundColor:'#dcfce7', color:'#14532d', fontWeight:'800'});
  const L = (p.data._lock || '').split(',');
  if (L.includes(p.colDef.field)) return Object.assign(baseFont, {backgroundColor:'#e2e8f0', color:'#0f172a', fontWeight:'600'});
  return Object.assign(baseFont, {backgroundColor:'#ffffff', color:'#1d4ed8', fontWeight:'600'});
}""")

JS_STYLE_REGULAR = JsCode("""
function(p){
  const baseFont = {fontFamily: 'Pretendard, Malgun Gothic, sans-serif', fontSize: '12.5px', textAlign: 'center', paddingLeft: '2px', paddingRight: '2px'};
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
  const s = {fontFamily: 'Pretendard, Malgun Gothic, sans-serif', fontSize: '12.5px', textAlign:'center', paddingLeft:'2px', paddingRight:'2px'};
  if (p.node.rowPinned) return Object.assign(s, {backgroundColor:'#dcfce7', color:'#14532d', fontWeight:'800'});
  const i = parseInt(p.colDef.field.slice(1)) - 1;
  if ((p.data._inact || '')[i] === '1') { s.backgroundColor = '#f1f5f9'; s.color = '#cbd5e1'; return s; }
  if ((p.data._lock || '').split(',').includes('M')) { s.backgroundColor = '#e2e8f0'; s.color = '#94a3b8'; return s; }
  s.color = '#0f172a';
  s.fontWeight = '700';
  s.backgroundColor = (p.data._ymask || '')[i] === '1' ? '#dcfce7' : '#ffffff';
  if ((p.data._proj || '')[i] === '1') { s.backgroundColor = '#fef08a'; s.color = '#854d0e'; }
  if ((p.data._nopay || '')[i] === '1') { s.backgroundColor = '#fef9c3'; s.color = '#9a3412'; }
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


def _build_year_rows(s: dict, year: int) -> tuple[list[dict], dict, dict]:
    people, recs = s["people"], s["year_recs"].setdefault(year, {})
    ctx = _ctx(s, year)
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
            lock += [f for f in INFO_COLS if f in (p.get("_confirmed") or [])]
            lock += [f for f in ("고용유형",) if f in (yrec.get("_confirmed") or [])]
            if p.get("주주관계") or p.get("외국인"):
                lock.append("제외사유")
        if c["excl_locked"]:
            lock.append("제외사유")
        if c["상시"] == "X":
            lock += ["청년등", "M"]
        if c["상시"] == "X" or (yrec.get("고용유형") or R.EMP_REGULAR) in R.EMP_NOT_YOUTH_REGULAR:
            lock.append("병역개월")

        ovr = {int(k) for k in (yrec.get("월_override") or {})}
        yr_ret = (p.get("연도별_퇴사일") or {}).get(str(year))
        disp_retire = yr_ret if yr_ret is not None else p.get("퇴사일", "")

        c_age = c.get("취업연령")
        age_str = f"{c_age}세" if c_age is not None else "-"

        row = {
            "pid": pid,
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
            "_nopay": "".join("1" if (i + 1) in c["no_pay_months"] else "0" for i in range(12)),
            "_proj": "".join("1" if (i + 1) in c.get("projected_months", []) else "0" for i in range(12)),
            "_movr": "".join("1" if (i + 1) in ovr else "0" for i in range(12)),
            "_sovr": "1" if yrec.get("상시_override") else "0",
            "_sauto": c["상시_auto"],
        }
        rows.append(row)
    totals = H.year_totals(list(computed.values()), ctx["months_in_year"])
    totals["has_data"] = len(rows) > 0
    return rows, computed, totals


def _grid_options(df: pd.DataFrame, totals: dict, show_all_4_blocks: bool = True) -> dict:
    gb = GridOptionsBuilder.from_dataframe(df)
    gb.configure_default_column(
        resizable=True,
        sortable=False,
        filter=False,
        suppressMenu=True,
        suppressHeaderMenuButton=True,
        suppressMovable=True,
        editable=JS_LOCKED,
        cellStyle=JS_STYLE,
        minWidth=44,
    )
    gb.configure_grid_options(
        singleClickEdit=True,
        stopEditingWhenCellsLoseFocus=True,
        rowHeight=32,
        headerHeight=32,
        groupHeaderHeight=30,
        suppressMenuHide=True,
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
            "paddingLeft": "3px",
            "paddingRight": "3px",
        }

    grp1_children = [
        {"field": "성명", "headerName": "성명", "pinned": "left", "width": 84, "editable": JS_LOCKED, "cellStyle": JS_STYLE},
        {"field": "생년월일", "headerName": "생년월일", "width": 98, "editable": JS_LOCKED, "cellStyle": JS_STYLE_CENTER, "valueFormatter": JS_DATE_FMT},
        {"field": "입사일", "headerName": "입사일", "width": 98, "editable": JS_LOCKED, "cellStyle": JS_STYLE_CENTER, "valueFormatter": JS_DATE_FMT},
        {"field": "퇴사일", "headerName": "퇴사일", "width": 98, "editable": JS_LOCKED, "cellStyle": JS_STYLE_CENTER, "valueFormatter": JS_DATE_FMT},
        {"field": "취업연령", "headerName": "취업연령", "width": 68, "editable": False, "cellStyle": _blk_style("#f8fafc", "#334155", bold=False)},
        {
            "field": "고용유형",
            "headerName": "고용유형",
            "width": 135,
            "editable": JS_LOCKED,
            "cellStyle": JS_STYLE,
            "cellEditor": "agSelectCellEditor",
            "cellEditorParams": {"values": R.EMP_TYPES},
        },
        {
            "field": "제외사유",
            "headerName": "제외사유",
            "width": 155,
            "editable": JS_LOCKED,
            "cellStyle": JS_STYLE,
            "cellEditor": "agSelectCellEditor",
            "cellEditorParams": {"values": R.EXCL_REASONS},
        },
        {
            "field": "병역개월",
            "headerName": "병역(월)",
            "width": 68,
            "editable": JS_LOCKED,
            "cellStyle": JS_STYLE_CENTER,
            "cellEditor": "agNumberCellEditor",
            "cellEditorParams": {"min": 0, "max": R.MILITARY_MAX_MONTHS, "precision": 0},
        },
        {
            "field": "청년등",
            "headerName": "청년등 구분",
            "width": 135,
            "editable": JS_LOCKED,
            "cellStyle": JS_STYLE,
            "cellEditor": "agSelectCellEditor",
            "cellEditorParams": JS_YOUTH_PARAMS,
        },
        {
            "field": "상시",
            "headerName": "상시",
            "width": 58,
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
                "width": 48,
                "minWidth": 44,
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
            "width": 62,
            "editable": False,
            "valueFormatter": JS_NUM_FMT,
            "cellStyle": _blk_style("#f1f5f9", "#0f172a"),
        }
    )

    grp3_children = [
        {"field": "b1_yth", "headerName": "청년등", "width": 64, "editable": False, "valueFormatter": JS_DEC2_FMT, "cellStyle": _blk_style("#f0fdf4", "#15803d")},
        {"field": "b1_gen", "headerName": "청년외", "width": 64, "editable": False, "valueFormatter": JS_DEC2_FMT, "cellStyle": _blk_style("#f8fafc", "#334155")},
        {"field": "b1_reg", "headerName": "상시", "width": 64, "editable": False, "valueFormatter": JS_DEC2_FMT, "cellStyle": _blk_style("#e0f2fe", "#0369a1")},
    ]

    grp4_children = [
        {"field": "b2_yth", "headerName": "청년등", "width": 64, "editable": False, "valueFormatter": JS_DEC2_FMT, "cellStyle": _blk_style("#eff6ff", "#1d4ed8"), "hide": not show_all_4_blocks},
        {"field": "b2_gen", "headerName": "청년외", "width": 64, "editable": False, "valueFormatter": JS_DEC2_FMT, "cellStyle": _blk_style("#f8fafc", "#475569"), "hide": not show_all_4_blocks},
        {"field": "b2_reg", "headerName": "상시", "width": 64, "editable": False, "valueFormatter": JS_DEC2_FMT, "cellStyle": _blk_style("#eff6ff", "#1e3a8a"), "hide": not show_all_4_blocks},
    ]

    grp5_children = [
        {"field": "b3_yth", "headerName": "청년등", "width": 64, "editable": False, "valueFormatter": JS_DEC2_FMT, "cellStyle": _blk_style("#f5f3ff", "#6d28d9"), "hide": not show_all_4_blocks},
        {"field": "b3_gen", "headerName": "청년외", "width": 64, "editable": False, "valueFormatter": JS_DEC2_FMT, "cellStyle": _blk_style("#f8fafc", "#475569"), "hide": not show_all_4_blocks},
        {"field": "b3_reg", "headerName": "상시", "width": 64, "editable": False, "valueFormatter": JS_DEC2_FMT, "cellStyle": _blk_style("#f5f3ff", "#4c1d95"), "hide": not show_all_4_blocks},
    ]

    grp6_children = [
        {"field": "b4_yth", "headerName": "청년등", "width": 64, "editable": False, "valueFormatter": JS_DEC2_FMT, "cellStyle": _blk_style("#fffbeb", "#b45309"), "hide": not show_all_4_blocks},
        {"field": "b4_gen", "headerName": "청년외", "width": 64, "editable": False, "valueFormatter": JS_DEC2_FMT, "cellStyle": _blk_style("#f8fafc", "#475569"), "hide": not show_all_4_blocks},
        {"field": "b4_reg", "headerName": "상시", "width": 64, "editable": False, "valueFormatter": JS_DEC2_FMT, "cellStyle": _blk_style("#fffbeb", "#92400e"), "hide": not show_all_4_blocks},
    ]

    hidden_cols = [
        {"field": c, "hide": True, "editable": False}
        for c in df.columns
        if c.startswith("_") or c == "pid"
    ]

    go["columnDefs"] = [
        {"headerName": "1. 사원 계산기 (기본정보 · 상시/청년 판정)", "children": grp1_children},
        {"headerName": "2. 매월 말 현재 상시근로자 수 (1월 ~ 12월)", "children": grp2_children},
        {"headerName": "3. 통합고용세액공제", "children": grp3_children},
        {"headerName": "4. 2차년도 사후관리", "children": grp4_children},
        {"headerName": "5. 3차년도 사후관리", "children": grp5_children},
        {"headerName": "6. 인별절사(25.02·26.02개정)", "children": grp6_children},
        *hidden_cols,
    ]

    n = totals["months_in_year"]
    pinned = [
        {
            "성명": "상시근로자",
            "생년월일": "",
            "고용유형": f"÷ {n}개월 (절사)",
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

        for f in INFO_COLS:
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


def _year_role_description(tax_year: int, year: int) -> str:
    if year == tax_year:
        return f"당해 과세연도 ({tax_year}년 신규공제 + {tax_year-1}년분 1차 사후관리 + {tax_year-2}년분 2차 사후관리 동시 판정)"
    diff = tax_year - year
    if diff == 1:
        return f"직전 과세연도 ({tax_year}년 신규공제 비교 대상 & {year}년 귀속분 세법원칙 재계산 검증)"
    if diff == 2:
        return f"전전 과세연도 ({year}년 귀속분 2차 사후관리·3차년도 연속공제 비교 기준)"
    return "과거 비교·사후관리 참고 과세연도"


def _render_year(s: dict, year: int, room_key: str) -> tuple[dict, dict]:
    rows, computed, totals = _build_year_rows(s, year)
    tax_year = int(s["tax_year"])
    role_desc = _year_role_description(tax_year, year)
    last_m = H.detect_last_paid_month(s.get("people") or {}, year)
    mid_yr_badge = (
        f" &nbsp;·&nbsp; <span style='color:#b45309;font-weight:700;'>⚡ {last_m}월 가결산 감지 ({last_m+1}~12월 {'연말재직 자동가정 중' if s.get('assume_year_end', True) else '미도래 0 처리 중'})</span>"
        if last_m < 12
        else ""
    )

    st.markdown(
        f"<div class='ec-year-header'>"
        f"<span class='ec-year-title'>📅 {year}년 상시근로자 명세 ({len(rows)}명)</span>"
        f"<span class='ec-year-sub'>{role_desc}{mid_yr_badge}</span>"
        f"</div>",
        unsafe_allow_html=True,
    )

    if not rows:
        st.info(f"{year}년에 근무한 근로자가 없습니다. {year}년 원천징수부를 올렸는지 확인하거나 아래 [➕ 사원 추가]로 입력하세요.")
        return computed, totals

    df = pd.DataFrame(rows)
    s["last_sent"][year] = rows
    ver = s["grid_ver"].get(year, 0)
    show_all_4 = bool(s.get("show_all_4_blocks", True))

    custom_ag_css = {
        ".ag-header": {"background-color": "#1e293b !important", "color": "#ffffff !important"},
        ".ag-header-group-cell": {
            "background-color": "#0f172a !important",
            "color": "#f8fafc !important",
            "font-weight": "800 !important",
            "font-family": "'Pretendard', 'Malgun Gothic', sans-serif !important",
            "font-size": "12.5px !important",
            "border-right": "1px solid #475569 !important",
            "justify-content": "center !important",
        },
        ".ag-header-cell": {
            "padding-left": "3px !important",
            "padding-right": "3px !important",
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
            "font-size": "12.2px !important",
            "overflow": "visible !important",
            "text-overflow": "clip !important",
            "white-space": "nowrap !important",
        },
        ".ag-header-cell-menu-button, .ag-header-icon": {
            "display": "none !important",
        },
        ".ag-cell": {
            "padding-left": "4px !important",
            "padding-right": "4px !important",
        },
        ".ag-root-wrapper": {"border-radius": "8px !important", "border": "1px solid #cbd5e1 !important"},
    }
    resp = AgGrid(
        df,
        gridOptions=_grid_options(df, totals, show_all_4_blocks=show_all_4),
        update_mode=GridUpdateMode.VALUE_CHANGED,
        allow_unsafe_jscode=True,
        theme="balham",
        custom_css=custom_ag_css,
        key=f"ec_grid_{year}_{ver}_{int(show_all_4)}_{int(s.get('assume_year_end', True))}",
        height=min(680, 114 + 32 * (len(rows) + 3)),
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
        st.rerun()

    st.markdown(
        f"<div class='ec-kpi-bar'>"
        f"<div class='ec-kpi-items'>"
        f"<span>👥 <b>[3.당해공제]</b> 상시 <b>{totals['b1_reg']:.2f}</b> (청년 <b>{totals['b1_yth']:.2f}</b> · 이외 <b>{totals['b1_gen']:.2f}</b>)</span>"
        f"<span>🔄 <b>[4.2차사후({year-1}분)]</b> 청년 <b>{totals['b2_yth']:.2f}</b> · 이외 <b>{totals['b2_gen']:.2f}</b></span>"
        f"<span>🛡️ <b>[5.3차사후({year-2}분)]</b> 청년 <b>{totals['b3_yth']:.2f}</b> · 이외 <b>{totals['b3_gen']:.2f}</b></span>"
        f"<span>📐 <b>[6.인별절사(25.02·26.02)]</b> 상시 <b>{totals['b4_reg']:.2f}</b> (청년 <b>{totals['b4_yth']:.2f}</b>)</span>"
        f"</div>"
        f"<span class='sb-badge-green'>총인원(연인원) {totals['상시_합계']:g}명 ÷ {totals['months_in_year']}개월</span>"
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
            "공제세액": 0,
            "이월세액": 0,
            "기추징세액": 0,
        },
    )
    has_prev_doc = bool(((s.get("ext") or {}).get("prev_filing") or {}).get("연도별"))

    with st.expander(
        f"📋 {t2_year}년 귀속분(2차 사후관리 대상) 인원 확인 — 원천징수부 미첨부 시 기신고 명세서 숫자로 간편 계산됩니다",
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
                value=float(y_entry.get("상시") or 0.0),
                key=f"prev_sum_reg_{t2_year}",
            )
            y_entry["상시"] = reg_val
        with c2:
            yth_val = st.number_input(
                f"{t2_year}년 기신고 청년등 상시근로자 수",
                min_value=0.0,
                step=0.01,
                format="%.2f",
                value=float(y_entry.get("청년등") or 0.0),
                key=f"prev_sum_yth_{t2_year}",
            )
            y_entry["청년등"] = yth_val
        with c3:
            st.write("")
            if st.button(f"➕ {t2_year}년 사원정보 표 직접 열어서 인별 계산하기", use_container_width=True, key=f"btn_open_yr_{t2_year}"):
                extra = s.setdefault("manual_extra_years", [])
                if t2_year not in extra:
                    extra.append(t2_year)
                for pid in s["people"]:
                    s["year_recs"].setdefault(t2_year, {}).setdefault(pid, P.new_year_rec())
                st.rerun()


def _page_employees(room_key: str):
    s = _S()
    tax_yr = int(s["tax_year"])
    shown_years = _years(s)

    st.markdown(f"### 👥 2. 사원정보 및 상시근로자 판정 ({tax_yr}년 귀속)")

    with st.container(border=True):
        c_opt1, c_opt2 = st.columns([3.4, 2.6])
        with c_opt1:
            mode_idx = 0 if s.get("assume_year_end", True) else 1
            chosen_mode = st.radio(
                "⚡ 기중(예: 9월 가결산) 원천징수부 업로드 시 미도래 월(10·11·12월) 처리 방식",
                options=[
                    "① 연말까지 재직 가정 (미도래 월 1 자동 채움 · 진노란색 표시) [권장]",
                    "② 급여 지급 월까지만 산입 (미도래 월 0 처리)",
                ],
                index=mode_idx,
                horizontal=True,
                key="ec_radio_assume_ye",
            )
            new_assume = chosen_mode.startswith("①")
            if new_assume != s.get("assume_year_end", True):
                s["assume_year_end"] = new_assume
                st.rerun()
        with c_opt2:
            st.write("")
            show_4 = st.toggle(
                "📊 우측 『4. 2차 사후관리 · 5. 3차 사후관리 · 6. 인별절사(25.02·26.02개정)』 블록 모두 펼치기",
                value=bool(s.get("show_all_4_blocks", True)),
                key="ec_toggle_4blocks",
            )
            if show_4 != s.get("show_all_4_blocks", True):
                s["show_all_4_blocks"] = show_4
                st.rerun()

    st.markdown(
        "<div class='ec-legend'>"
        "<span style='background:#e2e8f0;color:#0f172a;border:1px solid #cbd5e1'>🔒 서류 확인값 (상시 O/X 전환 시 잠금해제)</span>"
        "<span style='background:#ffffff;color:#1d4ed8;border:1px solid #93c5fd'>✏️ 입력·선택 가능</span>"
        "<span style='background:#dcfce7;color:#14532d;border:1px solid #86efac'>🌱 청년등 인정 월</span>"
        "<span style='background:#fef08a;color:#854d0e;border:1px solid #eab308'>⏩ 미도래 월 연말재직 가정(자동 1)</span>"
        "<span style='background:#fef9c3;color:#9a3412;border:1px solid #fde047'>⚠️ 급여 없는 달 (무급·육아휴직 확인)</span>"
        "<span style='background:#ffffff;color:#0f172a;border:2px solid #f59e0b'>🔧 직접 수정한 값</span>"
        "</div>",
        unsafe_allow_html=True,
    )

    if not s["people"]:
        st.info("읽어온 근로자가 없습니다. 아래 [➕ 사원 추가] 버튼으로 직접 입력하시거나 [< 이전]을 눌러 원천징수부를 업로드하세요.")

    computed_all, totals_all, ctx_all = {}, {}, {}
    for y in shown_years:
        computed_all[y], totals_all[y] = _render_year(s, y, room_key)
        ctx_all[y] = _ctx(s, y)

    _render_prev_filing_summary_card(s, shown_years)

    if tax_yr in totals_all and (tax_yr - 1) in totals_all:
        cur_t, prv_t = totals_all[tax_yr], totals_all[tax_yr - 1]
        inc = H.calc_increase_with_cap(
            cur_t["상시_평균"],
            cur_t["청년등_평균"],
            cur_t["청년외_평균"],
            prv_t["상시_평균"],
            prv_t["청년등_평균"],
            prv_t["청년외_평균"],
        )
        cap_note = ""
        if inc.get("청년등_한도적용전", 0) > inc["청년등_증가"] or inc.get("청년등외_한도적용전", 0) > inc["청년등외_증가"]:
            cap_note = " &nbsp;·&nbsp; ⚠️ <b>전체 상시근로자 증가인원 한도(Cap) 자동 적용됨</b>"
        st.markdown(
            f"<div class='ec-law-banner'>"
            f"📊 <b>[{tax_yr}년 vs {tax_yr-1}년 신규공제 고용증가 요약]</b> &nbsp; "
            f"전체 상시 증가: <b>+{inc['전체_증가']:.2f}명</b> &nbsp;|&nbsp; "
            f"청년등 인정 증가: <b>+{inc['청년등_증가']:.2f}명</b> &nbsp;|&nbsp; "
            f"청년등 외 인정 증가: <b>+{inc['청년등외_증가']:.2f}명</b>{cap_note} &nbsp;&nbsp; "
            f"<span style='color:#1d4ed8'>(1차 사후관리용 {tax_yr}년 청년등: <b>{cur_t['b2_yth']:.2f}명</b> / 2차 사후관리용 청년등: <b>{cur_t['b3_yth']:.2f}명</b>)</span>"
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
        st.rerun()

    st.markdown("<div class='ec-nav-divider'></div>", unsafe_allow_html=True)
    c_prev, _, c_rev, c_next = st.columns([1.3, 3.4, 1.1, 1.3])
    if c_prev.button("< 이전", use_container_width=True):
        s["step"] = 1
        st.rerun()
    if c_rev.button("오류 검토", use_container_width=True):
        prev = ((s.get("ext") or {}).get("prev_filing") or {}).get("연도별")
        _dlg_review(H.review(s["people"], s["year_recs"], shown_years, ctx_all, computed_all, prev))
    if c_next.button("다음(3단계)", type="primary", use_container_width=True):
        s["totals_snapshot"] = totals_all
        s["step"] = 3
        st.rerun()


# ══════════════════════════════════════════════════════════════════
# 6. 3단계: 공제액 · 1·2차 사후관리(추가납부세액) 종합 계산
#    - 표 오른쪽 위에 『기신고 기준 (원칙)』 vs 『세법원칙 기준 (재계산)』 선택기 배치!
# ══════════════════════════════════════════════════════════════════
def _ensure_totals_snapshot(s: dict) -> dict[int, dict]:
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
    s["totals_snapshot"] = totals_all
    return totals_all


def _render_pm_basis_selector_right(s: dict, widget_key: str) -> str:
    """
    표 오른쪽 위에 배치되는 『기신고 기준』(기본/원칙) vs 『세법원칙 기준』(원천징수부 재계산) 선택기.
    어느 쪽 표에서 변경하더라도 세션 상태 `s["pm_basis"]`가 즉시 동기화됩니다.
    """
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
        st.rerun()
    return s["pm_basis"]


def _page_calculation():
    s = _S()
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

    st.markdown(f"### 🧮 3. 통합고용세액공제 및 1·2차 사후관리 계산 ({tax_yr}년 귀속)")
    st.markdown(
        f"<div class='ec-law-banner'>"
        f"🏢 <b>적용 기준:</b> {corp_size} · {loc_label} &nbsp;|&nbsp; "
        f"<b>① {tax_yr}년 신규공제</b> + <b>② {tax_yr-1}년 귀속분 1차 사후관리(2차년도)</b> + "
        f"<b>③ {tax_yr-2}년 귀속분 2차 사후관리(3차년도)</b> + <b>④ 육아휴직복귀/정규직전환 추가공제</b>를 통합 산출합니다. "
        f"<br>📌 <b>사후관리 산정 원칙:</b> 표 오른쪽 위에서 기본값인 <b>『기신고 기준 (원칙)』</b>과 원천징수부 기반 <b>『세법원칙 기준 (재계산)』</b>을 전환하여 총인원수·평균인원수 및 사후관리세액을 즉시 비교하실 수 있습니다."
        f"</div>",
        unsafe_allow_html=True,
    )

    last_m_cur = H.detect_last_paid_month(s.get("people") or {}, tax_yr)
    if s.get("assume_year_end", True) and last_m_cur < 12:
        st.markdown(
            f"<div class='ec-warn-banner'>"
            f"⚠️ <b>[기중 가결산 추정치 안내]</b> 현재 {tax_yr}년 원천징수부가 <b>{last_m_cur}월분</b>까지 업로드되어, "
            f"미도래 월(<b>{last_m_cur+1}~12월</b>)은 <b>'① 연말까지 재직 가정(1 자동 채움)'</b> 기준으로 시뮬레이션된 추정 세액입니다. "
            f"실제 세무신고 시에는 12월 최종 원천징수부를 업로드하거나, 2단계 상단에서 <b>'② 급여 지급 월까지만 산입'</b>으로 전환하여 확정하세요."
            f"</div>",
            unsafe_allow_html=True,
        )

    # ── [섹션 1] 과거 공제연도(T-1, T-2) 기신고 내역·추징한도·기납부추징액 확인·보정 ──
    ps = s.setdefault("prev_summary", {})
    if has_t2_data:
        auto_y1_inc = H.calc_increase_with_cap(
            prev_t.get("상시_평균", 0.0),
            prev_t.get("청년등_평균", 0.0),
            prev2_t.get("상시_평균", 0.0),
            prev2_t.get("청년등_평균", 0.0),
        )
    else:
        auto_y1_inc = {"total_inc": 0.0, "youth_inc": 0.0, "non_youth_inc": 0.0}

    rates_legacy = H.get_unit_rates(corp_size, is_capital, scheme="legacy", retention_year=1)

    with st.expander(
        f"⚙️ 사후관리 『기신고 기준』 기초값 확인·입력 ({tax_yr-1}년 공제감면세액계산서 · {tax_yr-2}년 기신고분)",
        expanded=True,
    ):
        if not has_t2_data:
            st.info(
                f"ℹ️ 현재 **{tax_yr-2}년 원천징수부 또는 기신고 명세서**가 입력되지 않아, "
                f"**{tax_yr-1}년 공제받은 증가수**가 과대 계상되지 않도록 `0.00명`으로 안전하게 초기화되었습니다. "
                f"아래에 {tax_yr-1}년·{tax_yr-2}년 공제감면세액계산서상의 기신고 수치를 확인·입력해 주세요."
            )
        else:
            st.caption(
                f"💡 **{tax_yr-1}년 공제감면세액계산서** 및 기신고 명세서의 수치입니다. "
                f"표 오른쪽 위에서 **『기신고 기준 (원칙)』** 선택 시 아래 입력값이 적용되며, "
                f"**『세법원칙 기준 (재계산)』** 선택 시 원천징수부 사원표에서 세법 원칙대로 재계산된 수치가 자동 적용됩니다."
            )
        col_y1, col_y2 = st.columns(2)

        # (A) 직전연도(T-1, 예: 2025년) 기신고분
        p1 = ps.setdefault(str(tax_yr - 1), {})
        m_y1 = int(b.get("전년_월수", 12) or 12)
        with col_y1:
            st.markdown(f"##### 📌 {tax_yr - 1}년 귀속 기신고 내역 (1차 사후관리 · 2차년도 연속공제 기준)")
            c1a, c1b = st.columns(2)
            p1_reg = c1a.number_input(
                f"{tax_yr-1}년 기신고 상시 평균인원 (세법재계산: {prev_t.get('상시_평균', 0.0):.2f}명)",
                0.0, 9999.0,
                float(p1.get("상시") if p1.get("상시") is not None else prev_t.get("상시_평균", 0.0)),
                0.01, format="%.2f", key=f"calc_p1_reg_{tax_yr}"
            )
            p1_yth = c1b.number_input(
                f"{tax_yr-1}년 기신고 청년등 평균인원 (세법재계산: {prev_t.get('청년등_평균', 0.0):.2f}명)",
                0.0, 9999.0,
                float(p1.get("청년등") if p1.get("청년등") is not None else prev_t.get("청년등_평균", 0.0)),
                0.01, format="%.2f", key=f"calc_p1_yth_{tax_yr}"
            )
            c1t1, c1t2 = st.columns(2)
            default_p1_reg_tot = float(
                p1.get("상시_총인원")
                if p1.get("상시_총인원") is not None
                else (prev_t.get("상시_합계", round(p1_reg * m_y1, 2)) if abs(p1_reg - prev_t.get("상시_평균", 0.0)) < 1e-4 else round(p1_reg * m_y1, 2))
            )
            default_p1_yth_tot = float(
                p1.get("청년등_총인원")
                if p1.get("청년등_총인원") is not None
                else (prev_t.get("청년등_합계", round(p1_yth * m_y1, 2)) if abs(p1_yth - prev_t.get("청년등_평균", 0.0)) < 1e-4 else round(p1_yth * m_y1, 2))
            )
            p1_reg_tot = c1t1.number_input(
                f"{tax_yr-1}년 기신고 상시 총인원수(연인원, 세법: {prev_t.get('상시_합계', 0.0):g}명)",
                0.0, 120000.0,
                default_p1_reg_tot,
                0.25, format="%.2f", key=f"calc_p1_rtot_{tax_yr}"
            )
            p1_yth_tot = c1t2.number_input(
                f"{tax_yr-1}년 기신고 청년등 총인원수(연인원, 세법: {prev_t.get('청년등_합계', 0.0):g}명)",
                0.0, 120000.0,
                default_p1_yth_tot,
                0.25, format="%.2f", key=f"calc_p1_ytot_{tax_yr}"
            )
            c1c, c1d = st.columns(2)
            p1_yth_inc = c1c.number_input(
                f"{tax_yr-1}년 기신고 공제받은 청년등 증가수 (세법: {auto_y1_inc['youth_inc']:.2f}명)",
                0.0, 9999.0,
                float(p1.get("청년등_증가") if p1.get("청년등_증가") is not None else auto_y1_inc["youth_inc"]),
                0.01, format="%.2f", key=f"calc_p1_yinc_{tax_yr}"
            )
            p1_gen_inc = c1d.number_input(
                f"{tax_yr-1}년 기신고 공제받은 청년외 증가수 (세법: {auto_y1_inc['non_youth_inc']:.2f}명)",
                0.0, 9999.0,
                float(p1.get("청년등외_증가") if p1.get("청년등외_증가") is not None else auto_y1_inc["non_youth_inc"]),
                0.01, format="%.2f", key=f"calc_p1_ginc_{tax_yr}"
            )
            default_p1_claimed = int(round((p1_yth_inc * rates_legacy["청년등"] + p1_gen_inc * rates_legacy["청년등외"]) * 10_000))
            c1e, c1f = st.columns(2)
            p1_claimed = c1e.number_input(
                f"{tax_yr-1}년분 기공제세액 (원, 추징 한도)",
                0, 50_000_000_000,
                int(p1.get("공제세액") if (p1.get("공제세액") or 0) > 0 else default_p1_claimed),
                100_000, key=f"calc_p1_clm_{tax_yr}",
                help="1차 사후관리 추가납부세액은 해당 과세연도에 실제 공제받은 세액을 한도로 합니다."
            )
            p1_cf = c1f.number_input(
                f"{tax_yr-1}년분 미공제 이월세액 (원, 추징 차감)",
                0, 50_000_000_000,
                int(p1.get("이월세액") or 0),
                100_000, key=f"calc_p1_cf_{tax_yr}"
            )
            p1.update({
                "상시_총인원": p1_reg_tot,
                "청년등_총인원": p1_yth_tot,
                "상시": p1_reg,
                "청년등": p1_yth,
                "청년등_증가": p1_yth_inc,
                "청년등외_증가": p1_gen_inc,
                "공제세액": p1_claimed,
                "이월세액": p1_cf,
            })

        # (B) 전전연도(T-2, 예: 2024년) 기신고분
        p2 = ps.setdefault(str(tax_yr - 2), {})
        m_y2 = int(b.get("전전년_월수", 12) or 12)
        with col_y2:
            st.markdown(f"##### 📌 {tax_yr - 2}년 귀속 기신고 내역 (2차 사후관리 · 3차년도 연속공제 기준)")
            c2a, c2b = st.columns(2)
            p2_reg = c2a.number_input(
                f"{tax_yr-2}년 기신고 상시 평균인원 (세법재계산: {prev2_t.get('상시_평균', 0.0):.2f}명)",
                0.0, 9999.0,
                float(p2.get("상시") if p2.get("상시") is not None else prev2_t.get("상시_평균", 0.0)),
                0.01, format="%.2f", key=f"calc_p2_reg_{tax_yr}"
            )
            p2_yth = c2b.number_input(
                f"{tax_yr-2}년 기신고 청년등 평균인원 (세법재계산: {prev2_t.get('청년등_평균', 0.0):.2f}명)",
                0.0, 9999.0,
                float(p2.get("청년등") if p2.get("청년등") is not None else prev2_t.get("청년등_평균", 0.0)),
                0.01, format="%.2f", key=f"calc_p2_yth_{tax_yr}"
            )
            c2t1, c2t2 = st.columns(2)
            default_p2_reg_tot = float(
                p2.get("상시_총인원")
                if p2.get("상시_총인원") is not None
                else (prev2_t.get("상시_합계", round(p2_reg * m_y2, 2)) if abs(p2_reg - prev2_t.get("상시_평균", 0.0)) < 1e-4 else round(p2_reg * m_y2, 2))
            )
            default_p2_yth_tot = float(
                p2.get("청년등_총인원")
                if p2.get("청년등_총인원") is not None
                else (prev2_t.get("청년등_합계", round(p2_yth * m_y2, 2)) if abs(p2_yth - prev2_t.get("청년등_평균", 0.0)) < 1e-4 else round(p2_yth * m_y2, 2))
            )
            p2_reg_tot = c2t1.number_input(
                f"{tax_yr-2}년 기신고 상시 총인원수(연인원, 세법: {prev2_t.get('상시_합계', 0.0):g}명)",
                0.0, 120000.0,
                default_p2_reg_tot,
                0.25, format="%.2f", key=f"calc_p2_rtot_{tax_yr}"
            )
            p2_yth_tot = c2t2.number_input(
                f"{tax_yr-2}년 기신고 청년등 총인원수(연인원, 세법: {prev2_t.get('청년등_합계', 0.0):g}명)",
                0.0, 120000.0,
                default_p2_yth_tot,
                0.25, format="%.2f", key=f"calc_p2_ytot_{tax_yr}"
            )
            c2c, c2d = st.columns(2)
            p2_yth_inc = c2c.number_input(
                f"{tax_yr-2}년 기신고 공제받은 청년등 증가수",
                0.0, 9999.0,
                float(p2.get("청년등_증가") if p2.get("청년등_증가") is not None else 0.0),
                0.01, format="%.2f", key=f"calc_p2_yinc_{tax_yr}"
            )
            p2_gen_inc = c2d.number_input(
                f"{tax_yr-2}년 기신고 공제받은 청년외 증가수",
                0.0, 9999.0,
                float(p2.get("청년등외_증가") if p2.get("청년등외_증가") is not None else 0.0),
                0.01, format="%.2f", key=f"calc_p2_ginc_{tax_yr}"
            )
            default_p2_1yr = int(round((p2_yth_inc * rates_legacy["청년등"] + p2_gen_inc * rates_legacy["청년등외"]) * 10_000))
            default_p2_claimed = default_p2_1yr * (1 if corp_size in ("일반기업", "대기업") else 2)
            c2e, c2f, c2g = st.columns(3)
            p2_claimed = c2e.number_input(
                f"{tax_yr-2}년분 누적 기공제세액(한도)",
                0, 50_000_000_000,
                int(p2.get("공제세액") if (p2.get("공제세액") or 0) > 0 else default_p2_claimed),
                100_000, key=f"calc_p2_clm_{tax_yr}",
                help=f"{tax_yr-2}년분 1차년도+2차년도 누적 공제받은 세액 합계(추징 상한액)"
            )
            p2_prior_paid = c2f.number_input(
                f"1차 사후관리 기납부 추징액(차감)",
                0, 50_000_000_000,
                int(p2.get("기추징세액") or 0),
                100_000, key=f"calc_p2_paid_{tax_yr}",
                help=f"직전연도({tax_yr-1}년) 1차 사후관리에서 이미 추징(납부·차감)된 세액이 있다면 입력하여 이중 추징을 방지합니다."
            )
            p2_cf = c2g.number_input(
                f"{tax_yr-2}년분 미공제 이월세액",
                0, 50_000_000_000,
                int(p2.get("이월세액") or 0),
                100_000, key=f"calc_p2_cf_{tax_yr}"
            )
            p2.update({
                "상시_총인원": p2_reg_tot,
                "청년등_총인원": p2_yth_tot,
                "상시": p2_reg,
                "청년등": p2_yth,
                "청년등_증가": p2_yth_inc,
                "청년등외_증가": p2_gen_inc,
                "공제세액": p2_claimed,
                "기추징세액": p2_prior_paid,
                "이월세액": p2_cf,
            })

    # ── [섹션 2] 추가공제 (육아휴직 복귀 · 정규직 전환 · 출산전후휴가 대체인력) 및 당해 이월공제·단가 옵션 ──
    add_in = s.setdefault("additional_inputs", {})
    with st.expander("➕ 추가공제(육아휴직복귀·정규직전환·출산휴가대체인력) · 농특세 실공제 보정 · 단가 옵션", expanded=False):
        ca1, ca2, ca3 = st.columns(3)
        add_in["parental_return_count"] = ca1.number_input(
            "육아휴직 복귀자 수 (명, ~2026년 적용)",
            0, 500, int(add_in.get("parental_return_count") or 0),
            help="1년 이상 근속 후 6개월 이상 육아휴직 후 복귀한 근로자(자녀당 1회, 중소 1,300만원/중견 900만원)"
        )
        add_in["regular_conversion_count"] = ca2.number_input(
            "정규직 전환자 수 (명, 2024년 귀속까지 일몰)",
            0, 500, int(add_in.get("regular_conversion_count") or 0),
            disabled=(tax_yr > 2024),
            help="정규직 전환 추가공제는 2024년 귀속분까지 적용됩니다 (2023.6.30 당시 비정규직·파견·하도급 → 2024년 중 무기계약 전환)."
        )
        add_in["additional_clawback_count"] = ca3.number_input(
            "전환·복귀 후 2년 내 퇴사 추징 인원 (명)",
            0, 500, int(add_in.get("additional_clawback_count") or 0),
            help="정규직 전환일 또는 육아휴직 복귀일로부터 2년 이내에 근로관계가 종료된 인원"
        )
        cb1, cb2, cb3 = st.columns(3)
        add_in["maternity_replacement_count"] = cb1.number_input(
            "출산전후휴가 대체인력 보정 인원 (명, 제7항)",
            0.0, 500.0, float(add_in.get("maternity_replacement_count") or 0.0), 0.01,
            help="조특령 제26조의8 제7항: 추가공제(육아휴직 복귀·정규직 전환)의 상시근로자 비감소 요건 판정 시에만 합산 보정되는 인원입니다."
        )
        add_in["current_unclaimed_carryforward_won"] = cb2.number_input(
            f"당해({tax_yr}년) 최저한세 등 미공제 이월예정액 (원)",
            0, 50_000_000_000, int(add_in.get("current_unclaimed_carryforward_won") or 0), 100_000,
            help="농어촌특별세(20%)는 실제 감면받는 세액(당해 공제액 - 당해 미공제 이월액)에 대해서만 부과됩니다 (농특세법 제5조 제1항)."
        )
        if tax_yr >= 2026:
            scheme_opt = cb3.selectbox(
                f"{tax_yr}년 신규공제 단가 체계",
                options=["new_2026", "legacy"],
                index=0 if s.get("scheme_2026", "new_2026") == "new_2026" else 1,
                format_func=lambda x: "2026 신법 (연차별 차등 A+B+C)" if x == "new_2026" else "구법 단가 시뮬레이션 (균등단가 비교)",
            )
            s["scheme_2026"] = scheme_opt

    if (p2["상시"] > 0 or p2["청년등"] > 0) and not totals_all[tax_yr - 2].get("has_data"):
        has_t2_data = True
        totals_all[tax_yr - 2]["상시_평균"] = p2["상시"]
        totals_all[tax_yr - 2]["청년등_평균"] = p2["청년등"]
        totals_all[tax_yr - 2]["상시_합계"] = p2["상시_총인원"]
        totals_all[tax_yr - 2]["청년등_합계"] = p2["청년등_총인원"]
        totals_all[tax_yr - 2]["has_data"] = True

    prior_filings_payload = {
        tax_yr - 1: {
            "init_reg_total": p1["상시_총인원"],
            "init_yth_total": p1["청년등_총인원"],
            "init_reg": p1["상시"],
            "init_yth": p1["청년등"],
            "init_yth_inc": p1["청년등_증가"],
            "init_gen_inc": p1["청년등외_증가"],
            "claimed_won": p1["공제세액"],
            "carryforward_won": p1["이월세액"],
            "has_t2_data": has_t2_data,
        },
        tax_yr - 2: {
            "init_reg_total": p2["상시_총인원"],
            "init_yth_total": p2["청년등_총인원"],
            "init_reg": p2["상시"],
            "init_yth": p2["청년등"],
            "init_yth_inc": p2["청년등_증가"],
            "init_gen_inc": p2["청년등외_증가"],
            "claimed_won": p2["공제세액"],
            "prior_clawback_paid_won": p2["기추징세액"],
            "carryforward_won": p2["이월세액"],
        },
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

    # ── [섹션 3] 핵심 세액 요약 KPI 카드 4개 ──
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

    # ── [섹션 4-1] 사후관리 총인원수(연인원)/평균인원수 비교표 (오른쪽 위에 기신고 기준 vs 세법원칙 기준 선택기 배치!) ──
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

    # 선택된 기준(기신고 기준 vs 세법원칙 기준)에 따른 과거연도(T-1, T-2) 총인원수 및 평균인원수 결정
    is_recalc = pkg["pm_basis"] == R.PM_BASIS_RECALC
    y1_disp_reg = pkg["prev_s"]["regular"] if is_recalc else p1["상시"]
    y1_disp_yth = pkg["prev_s"]["youth"] if is_recalc else p1["청년등"]
    y1_disp_gen = round(max(0.0, y1_disp_reg - y1_disp_yth), 2)
    y1_disp_rtot = pkg["prev_s"]["reg_total"] if is_recalc else p1["상시_총인원"]
    y1_disp_ytot = pkg["prev_s"]["yth_total"] if is_recalc else p1["청년등_총인원"]
    y1_disp_gtot = round(max(0.0, y1_disp_rtot - y1_disp_ytot), 2)

    y2_has_wht = (tax_yr - 2) in _uploaded_wht_years(s) or any(
        H.worked_in_year(p, tax_yr - 2) for p in (s.get("people") or {}).values()
    )
    y2_disp_reg = pkg["prev2_s"]["regular"] if (is_recalc and y2_has_wht) else p2["상시"]
    y2_disp_yth = pkg["prev2_s"]["youth"] if (is_recalc and y2_has_wht) else p2["청년등"]
    y2_disp_gen = round(max(0.0, y2_disp_reg - y2_disp_yth), 2)
    y2_disp_rtot = pkg["prev2_s"]["reg_total"] if (is_recalc and y2_has_wht) else p2["상시_총인원"]
    y2_disp_ytot = pkg["prev2_s"]["yth_total"] if (is_recalc and y2_has_wht) else p2["청년등_총인원"]
    y2_disp_gtot = round(max(0.0, y2_disp_rtot - y2_disp_ytot), 2)

    cur_b2_gen = round(max(0.0, pkg["cur_s"]["b2_reg"] - pkg["cur_s"]["b2_yth"]), 2)
    cur_b2_gtot = round(max(0.0, pkg["cur_s"]["reg_total"] - pkg["cur_s"]["b2_yth_total"]), 2)
    cur_b3_gen = round(max(0.0, pkg["cur_s"]["b3_reg"] - pkg["cur_s"]["b3_yth"]), 2)
    cur_b3_gtot = round(max(0.0, pkg["cur_s"]["reg_total"] - pkg["cur_s"]["b3_yth_total"]), 2)

    hc_df = pd.DataFrame(
        [
            {
                "구분": f"{tax_yr}년 (당해 신규공제 기준 · Block 3)",
                "전체 [총인원(연인원) / 평균]": f"{pkg['cur_s']['reg_total']:g}명 / {pkg['cur_s']['regular']:.2f}명",
                "청년등 [총인원 / 평균]": f"{pkg['cur_s']['yth_total']:g}명 / {pkg['cur_s']['youth']:.2f}명",
                "청년등 외 [총인원 / 평균]": f"{pkg['cur_s']['non_youth_total']:g}명 / {pkg['cur_s']['non_youth']:.2f}명",
                "적용 기준 및 비교 안내": f"당해({tax_yr}년) 원천징수부 기준 (÷{pkg['cur_s']['months_in_year']}개월)",
            },
            {
                "구분": f"{tax_yr}년 ({tax_yr-1}년분 1차 사후관리 판정용 · Block 4)",
                "전체 [총인원(연인원) / 평균]": f"{pkg['cur_s']['reg_total']:g}명 / {pkg['cur_s']['b2_reg']:.2f}명",
                "청년등 [총인원 / 평균]": f"{pkg['cur_s']['b2_yth_total']:g}명 / {pkg['cur_s']['b2_yth']:.2f}명",
                "청년등 외 [총인원 / 평균]": f"{cur_b2_gtot:g}명 / {cur_b2_gen:.2f}명",
                "적용 기준 및 비교 안내": f"{tax_yr-1}년 입사 청년 연령경과(34세 초과) 간주 특례 반영",
            },
            {
                "구분": f"{tax_yr}년 ({tax_yr-2}년분 2차 사후관리 판정용 · Block 5)",
                "전체 [총인원(연인원) / 평균]": f"{pkg['cur_s']['reg_total']:g}명 / {pkg['cur_s']['b3_reg']:.2f}명",
                "청년등 [총인원 / 평균]": f"{pkg['cur_s']['b3_yth_total']:g}명 / {pkg['cur_s']['b3_yth']:.2f}명",
                "청년등 외 [총인원 / 평균]": f"{cur_b3_gtot:g}명 / {cur_b3_gen:.2f}명",
                "적용 기준 및 비교 안내": f"{tax_yr-2}년 입사 청년 연령경과(34세 초과) 간주 특례 반영",
            },
            {
                "구분": f"{tax_yr}년 (인별절사 25.02·26.02 시행령 비교 · Block 6)",
                "전체 [총인원(연인원) / 평균]": f"- / {pkg['cur_s']['b4_reg']:.2f}명",
                "청년등 [총인원 / 평균]": f"- / {pkg['cur_s']['b4_yth']:.2f}명",
                "청년등 외 [총인원 / 평균]": f"- / {round(max(0.0, pkg['cur_s']['b4_reg'] - pkg['cur_s']['b4_yth']), 2):.2f}명",
                "적용 기준 및 비교 안내": "근로자별 (근무월수÷사업연도월수) 소수점 둘째자리 절사 합산",
            },
            {
                "구분": f"{tax_yr-1}년 사후관리 기초 [{basis_lbl}]",
                "전체 [총인원(연인원) / 평균]": f"{y1_disp_rtot:g}명 / {y1_disp_reg:.2f}명",
                "청년등 [총인원 / 평균]": f"{y1_disp_ytot:g}명 / {y1_disp_yth:.2f}명",
                "청년등 외 [총인원 / 평균]": f"{y1_disp_gtot:g}명 / {y1_disp_gen:.2f}명",
                "적용 기준 및 비교 안내": (
                    f"기신고 기준 적용 중 (세법원칙 재계산 시: 상시 {pkg['prev_s']['regular']:.2f}명 / 청년 {pkg['prev_s']['youth']:.2f}명)"
                    if not is_recalc
                    else f"세법원칙 재계산 적용 중 (기신고 기준: 상시 {p1['상시']:.2f}명 / 청년 {p1['청년등']:.2f}명)"
                ),
            },
            {
                "구분": f"{tax_yr-2}년 사후관리 기초 [{basis_lbl}]",
                "전체 [총인원(연인원) / 평균]": f"{y2_disp_rtot:g}명 / {y2_disp_reg:.2f}명",
                "청년등 [총인원 / 평균]": f"{y2_disp_ytot:g}명 / {y2_disp_yth:.2f}명",
                "청년등 외 [총인원 / 평균]": f"{y2_disp_gtot:g}명 / {y2_disp_gen:.2f}명",
                "적용 기준 및 비교 안내": (
                    f"기신고 기준 적용 중 (세법원칙 재계산 시: 상시 {pkg['prev2_s']['regular']:.2f}명 / 청년 {pkg['prev2_s']['youth']:.2f}명)"
                    if not is_recalc
                    else f"세법원칙 재계산 적용 중 (기신고 기준: 상시 {p2['상시']:.2f}명 / 청년 {p2['청년등']:.2f}명)"
                ),
            },
        ]
    )
    st.dataframe(hc_df, use_container_width=True, hide_index=True)

    # ── [섹션 4-2] 사후관리세액(연속공제·추가납부) 상세 산출표 (오른쪽 위에 기신고 기준 vs 세법원칙 기준 선택기 배치!) ──
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
            "항목 구분": f"① {tax_yr}년 당해 고용증가 기본공제",
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
            "항목 구분": f"② {tax_yr-1}년 귀속분 1차 사후관리 (2차년도)",
            "적용 기준 · 판정 케이스": f"[{basis_lbl}] {pm1['case_code']}",
            "인정 인원 (청년등 / 청년외)": f"유지 청년 {pm1['retained_yth_inc']:.2f}명 / 일반 {pm1['retained_gen_inc']:.2f}명",
            "당해 공제세액 (+)": f"{pm1['continued_credit_won']:,}원",
            "추가납부 추징세액 (-)": f"{pm1['clawback_net_payable_won']:,}원 (이월차감 {pm1['carryforward_offset_won']:,}원)",
            "산출근거 및 기준별 비교": (
                f"{pm1['formula_note']} | 💡 [{alt_lbl} 선택 시: 연속공제 {pm1_alt['continued_credit_won']:,}원 / 추가납부 {pm1_alt['clawback_net_payable_won']:,}원]"
            ),
        },
        {
            "항목 구분": f"③ {tax_yr-2}년 귀속분 2차 사후관리 (3차년도)",
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
            "산출근거 및 기준별 비교": f"1인당 {R.ADDITIONAL_CREDIT_PER_PERSON.get(corp_size, 0):,}만원 (출산전후휴가 대체인력 보정 {pkg['maternity_rep_cnt']:.2f}명 반영)",
        },
    ]
    st.dataframe(pd.DataFrame(detail_rows), use_container_width=True, hide_index=True)

    # ── 하단 네비게이션 ──
    st.markdown("<div class='ec-nav-divider'></div>", unsafe_allow_html=True)
    c_prev, _, c_next = st.columns([1.3, 4.5, 1.3])
    if c_prev.button("< 이전(2단계)", use_container_width=True):
        s["step"] = 2
        st.rerun()
    if c_next.button("다음(4단계 보고서)", type="primary", use_container_width=True):
        s["step"] = 4
        st.rerun()


# ══════════════════════════════════════════════════════════════════
# 7. 4단계: 최종 검토보고서 및 다운로드
# ══════════════════════════════════════════════════════════════════
def _build_report_markdown(s: dict) -> str:
    b = s.get("biz") or {}
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
    if not pkg:
        has_t2_data = bool(totals_all.get(tax_yr - 2, {}).get("has_data") or _has_year_data(s, tax_yr - 2))
        pkg = H.calculate_tax_year_package(
            tax_year=tax_yr,
            corp_size=corp_sz,
            is_capital=is_capital,
            summaries=totals_all,
            prior_filings={
                tax_yr - 1: {
                    "init_reg": p1.get("상시", totals_all.get(tax_yr - 1, {}).get("상시_평균", 0.0)),
                    "init_yth": p1.get("청년등", totals_all.get(tax_yr - 1, {}).get("청년등_평균", 0.0)),
                    "init_yth_inc": p1.get("청년등_증가"),
                    "init_gen_inc": p1.get("청년등외_증가"),
                    "claimed_won": p1.get("공제세액", 0),
                    "carryforward_won": p1.get("이월세액", 0),
                    "has_t2_data": has_t2_data,
                },
                tax_yr - 2: {
                    "init_reg": p2.get("상시", totals_all.get(tax_yr - 2, {}).get("상시_평균", 0.0)),
                    "init_yth": p2.get("청년등", totals_all.get(tax_yr - 2, {}).get("청년등_평균", 0.0)),
                    "init_yth_inc": p2.get("청년등_증가", 0.0),
                    "init_gen_inc": p2.get("청년등외_증가", 0.0),
                    "claimed_won": p2.get("공제세액", 0),
                    "prior_clawback_paid_won": p2.get("기추징세액", 0),
                    "carryforward_won": p2.get("이월세액", 0),
                },
            },
            additional_inputs=s.get("additional_inputs"),
            scheme_2026=s.get("scheme_2026", "new_2026"),
            pm_basis=s.get("pm_basis", R.PM_BASIS_FILED),
        )

    pm1 = pkg["pm_y1"]
    pm2 = pkg["pm_y2"]
    basis_lbl = pkg.get("pm_basis_label", "기신고 기준")
    last_m_cur = H.detect_last_paid_month(s.get("people") or {}, tax_yr)
    est_line = (
        f"\n> ⚠️ **[가결산 추정치 안내]** 본 보고서는 {tax_yr}년 {last_m_cur}월 가결산 원천징수부를 기준으로 미도래 월({last_m_cur+1}~12월)을 "
        f"'연말까지 재직 가정(1 자동 채움)'하여 산출한 시뮬레이션 추정치입니다. 확정신고 시에는 12월 최종 원천징수부를 반영하여 재산출하시기 바랍니다.\n"
        if (s.get("assume_year_end", True) and last_m_cur < 12)
        else ""
    )

    lines = [
        f"# 📑 {tax_yr}년 귀속 통합고용세액공제 및 사후관리 검토보고서",
        est_line,
        "## 1. 사업자 기본사항",
        f"- **상호(법인명)**: {corp_nm} (사업자등록번호: `{b.get('사업자번호') or '-'}`)",
        f"- **기업규모 / 소재지**: **{corp_sz}** / **{loc_label}** (`{b.get('사업장소재지') or '-'}`)",
        f"- **업태 · 종목**: {b.get('업태') or '-'} · {b.get('종목') or '-'} (설립·개업일: `{b.get('설립일') or '-'}`)",
        f"- **사업연도 월수**: 당해({tax_yr}년) {b.get('당해_월수', 12)}개월 / 직전({tax_yr-1}년) {b.get('전년_월수', 12)}개월",
        f"- **사후관리 산정 기준**: **{basis_lbl}** ({'공제감면세액계산서 등 기신고 수치 원칙 적용' if pkg.get('pm_basis') == R.PM_BASIS_FILED else '원천징수부 세법원칙 재계산 수치 적용'})",
        "",
        f"## 2. 최종 공제세액 및 추가납부세액(추징) 요약 [{basis_lbl}]",
        "| 구분 | 금액 (원) | 비고 |",
        "| :--- | ---: | :--- |",
        f"| **① {tax_yr}년 당해 신규 고용증가 공제액** | **{pkg['cur_base_credit_won']:,}원** | 청년등 +{pkg['cur_inc']['youth_inc']:.2f}명, 청년외 +{pkg['cur_inc']['non_youth_inc']:.2f}명 |",
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
        f"| **{tax_yr}년 (당해 신규공제 기준)** | {pkg['cur_s']['reg_total']:g}명 / {pkg['cur_s']['regular']:.2f}명 | {pkg['cur_s']['yth_total']:g}명 / {pkg['cur_s']['youth']:.2f}명 | {pkg['cur_s']['non_youth_total']:g}명 / {pkg['cur_s']['non_youth']:.2f}명 | 근로계약 체결일 현재 연령 기준 |",
        f"| **{tax_yr}년 ({tax_yr-1}년분 1차 사후관리 기준)** | {pkg['cur_s']['reg_total']:g}명 / {pkg['cur_s']['b2_reg']:.2f}명 | {pkg['cur_s']['b2_yth_total']:g}명 / {pkg['cur_s']['b2_yth']:.2f}명 | {round(max(0.0, pkg['cur_s']['reg_total']-pkg['cur_s']['b2_yth_total']),2):g}명 / {round(max(0.0, pkg['cur_s']['b2_reg']-pkg['cur_s']['b2_yth']),2):.2f}명 | 구 조특령 제26조의8 제5항 연령경과 간주 특례 |",
        f"| **{tax_yr}년 ({tax_yr-2}년분 2차 사후관리 기준)** | {pkg['cur_s']['reg_total']:g}명 / {pkg['cur_s']['b3_reg']:.2f}명 | {pkg['cur_s']['b3_yth_total']:g}명 / {pkg['cur_s']['b3_yth']:.2f}명 | {round(max(0.0, pkg['cur_s']['reg_total']-pkg['cur_s']['b3_yth_total']),2):g}명 / {round(max(0.0, pkg['cur_s']['b3_reg']-pkg['cur_s']['b3_yth']),2):.2f}명 | 구 조특령 제26조의8 제5항 연령경과 간주 특례 |",
        f"| **{tax_yr}년 (인별절사 25.02·26.02 시행령 비교)** | - / {pkg['cur_s']['b4_reg']:.2f}명 | - / {pkg['cur_s']['b4_yth']:.2f}명 | - / {round(max(0.0, pkg['cur_s']['b4_reg']-pkg['cur_s']['b4_yth']),2):.2f}명 | 개인별 1/12 절사 후 단순 합산 비교치 |",
        f"| **{tax_yr-1}년 사후관리 기초 ({basis_lbl})** | - / {pm1['init_reg']:.2f}명 | - / {pm1['init_yth']:.2f}명 | - / {round(max(0.0, pm1['init_reg']-pm1['init_yth']),2):.2f}명 | 1차 사후관리 비교 기준 (증가 청년 {pm1['init_yth_inc']:.2f}명 / 일반 {pm1['init_gen_inc']:.2f}명) |",
        f"| **{tax_yr-2}년 사후관리 기초 ({basis_lbl})** | - / {pm2['init_reg']:.2f}명 | - / {pm2['init_yth']:.2f}명 | - / {round(max(0.0, pm2['init_reg']-pm2['init_yth']),2):.2f}명 | 2차 사후관리 비교 기준 (증가 청년 {pm2['init_yth_inc']:.2f}명 / 일반 {pm2['init_gen_inc']:.2f}명) |",
        "",
        "## 4. 사후관리 판정 및 실무 체크포인트 해설",
        f"1. **{tax_yr-1}년 귀속분 1차 사후관리 [{basis_lbl}] ({pm1['case_code']} - {pm1['case_title']})**: {pm1['formula_note']}",
        f"2. **{tax_yr-2}년 귀속분 2차 사후관리 [{basis_lbl}] ({pm2['case_code']} - {pm2['case_title']})**: {pm2['formula_note']}",
        "3. **4대 사후관리 추징 완화 특례 점검**:",
        "   - **이월공제 미공제액 차감 특례(조특법 제29조의8·제144조)**: 최저한세 등으로 실제 감면받지 못하고 이월된 세액이 있는 경우 현금 추가납부 대신 이월공제액을 우선 소멸시킵니다.",
        "   - **청년 연령경과 간주 특례(구 조특령 제26조의8 제5항)**: 최초 공제연도에 실제로 청년등이었던 근로자는 사후관리 기간 중 34세를 초과하더라도 청년등 상시근로자로 유지됩니다.",
        "   - **출산전후휴가자 대체인력 특례(조특령 제26조의8 제7항, 2024.2.29 신설)**: 추가공제 비감소 요건 판정 시 대체인력을 채용한 출산전후휴가자는 상시근로자 산정에서 보정할 수 있습니다.",
        "   - **이자상당가산액 면제**: 고용 감소로 인한 추가납부세액은 원금만 납부하며 이자상당가산액은 가산되지 않습니다.",
    ]
    return "\n".join(lines)


def _build_csv_bytes(s: dict) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "귀속연도", "성명", "생년월일", "입사일", "퇴사일", "취업연령", "고용유형", "제외사유", "병역(월)", "청년등구분", "상시여부",
            *[f"{m}월" for m in range(1, 13)], "월합계",
            "3.통합고용[청년]", "3.통합고용[청년외]", "3.통합고용[상시]",
            "4.2차사후[청년]", "4.2차사후[청년외]", "4.2차사후[상시]",
            "5.3차사후[청년]", "5.3차사후[청년외]", "5.3차사후[상시]",
            "6.인별절사(25.02·26.02)[청년]", "6.인별절사(25.02·26.02)[청년외]", "6.인별절사(25.02·26.02)[상시]",
        ]
    )
    for y in _years(s):
        rows, _, totals = _build_year_rows(s, y)
        for r in rows:
            writer.writerow(
                [
                    y, r["성명"], r["생년월일"], r["입사일"], r["퇴사일"], r["취업연령"],
                    r["고용유형"], r["제외사유"], r["병역개월"], r["청년등"], r["상시"],
                    *[r[MONTH_COLS[i]] if r[MONTH_COLS[i]] is not None else "" for i in range(12)],
                    r["합계"],
                    f"{r['b1_yth']:.2f}", f"{r['b1_gen']:.2f}", f"{r['b1_reg']:.2f}",
                    f"{r['b2_yth']:.2f}", f"{r['b2_gen']:.2f}", f"{r['b2_reg']:.2f}",
                    f"{r['b3_yth']:.2f}", f"{r['b3_gen']:.2f}", f"{r['b3_reg']:.2f}",
                    f"{r['b4_yth']:.2f}", f"{r['b4_gen']:.2f}", f"{r['b4_reg']:.2f}",
                ]
            )
        writer.writerow(
            [
                f"{y}년 합계/평균", "전체 상시·청년 요약", "", "", "", "", f"÷{totals['months_in_year']}개월", "", "", "", "",
                *[totals["월별_상시"][i] if totals["월별_상시"][i] is not None else "" for i in range(12)],
                totals["상시_합계"],
                f"{totals['b1_yth']:.2f}", f"{totals['b1_gen']:.2f}", f"{totals['b1_reg']:.2f}",
                f"{totals['b2_yth']:.2f}", f"{totals['b2_gen']:.2f}", f"{totals['b2_reg']:.2f}",
                f"{totals['b3_yth']:.2f}", f"{totals['b3_gen']:.2f}", f"{totals['b3_reg']:.2f}",
                f"{totals['b4_yth']:.2f}", f"{totals['b4_gen']:.2f}", f"{totals['b4_reg']:.2f}",
            ]
        )
    return buf.getvalue().encode("utf-8-sig")


def _page_report():
    s = _S()
    tax_yr = int(s["tax_year"])
    md_text = _build_report_markdown(s)
    csv_bytes = _build_csv_bytes(s)
    corp_nm = (s.get("biz", {}).get("상호") or "통합고용세액공제").strip()

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

    c_dl1, c_dl2, _ = st.columns([1.8, 1.8, 3.5])
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
            "📊 상시근로자 명세표 다운로드 (엑셀 .csv)",
            data=csv_bytes,
            file_name=f"{corp_nm}_{tax_yr}년귀속_상시근로자명세_4대블록포함.csv",
            mime="text/csv",
            use_container_width=True,
        )

    with st.container(border=True):
        st.markdown(md_text)

    st.markdown("<div class='ec-nav-divider'></div>", unsafe_allow_html=True)
    c_prev, _, c_reset = st.columns([1.3, 4.5, 1.3])
    if c_prev.button("< 이전(3단계)", use_container_width=True):
        s["step"] = 3
        st.rerun()
    if c_reset.button("처음으로(1단계)", use_container_width=True):
        s["step"] = 1
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
        _page_employees(active_room_key)
    elif s["step"] == 3:
        _page_calculation()
    else:
        _page_report()
