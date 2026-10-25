# -*- coding: utf-8 -*-
"""
통합고용세액공제 화면 — 1단계(자료 업로드) · 2단계(사원정보)

[디자인 & 기능 업그레이드 내역]
1. "자율 에이전트AI"(app.py)와 100% 동일한 Pretendard 폰트, 에메랄드 그린(#16a34a/#22c55e) & 다크 네이비(#1e293b) 테마,
   상단 슬림 미니 상태바(.top-mini-status-bar), 사이드바 카드 타이틀(.sb-card-title) 및 배지(.sb-badge-green) 완벽 통일.
2. 귀속사업연도 선택 리스트에 [2024, 2025, 2026, 2027, 2028] 전체 탑재 및 선택 연도별 동적 서류·법령 안내.
3. 2단계 사원표 스마트 노출:
   - 2026년 귀속 선택 시 2024년 원천징수부를 안 올렸다면 빈 2024년 사원표를 띄우지 않고 '2026년·2025년' 사원표 2개만 깔끔하게 표시!
   - 2024년 인원은 '기신고 상시근로자 명세서'에서 읽어온 숫자(또는 요약 카드에서 직접 입력)로 처리.
   - 단, 사용자가 2024년(또는 2023년) 원천징수부를 직접 올렸거나 좌측에서 '2024년 귀속 / 2025년 귀속'을 선택했을 때만 해당 과거 연도 사원표가 자동으로 나타납니다.
4. UI 레이아웃 디테일 개선:
   - 1단계 '📋 자료 확인 안내' 및 '🚫 적용 불가 업종 안내' 다이얼로그 창 가로 폭을 넓혀(width="large" + CSS 최소 폭 보강) 문장이 두 줄로 꺾이지 않도록 개선.
   - 2단계 하단 버튼 배치를 상단 [➕ 사원 추가](좌측 끝)와 분리하여,
     그 아래 줄에 [⬅️ 이전](좌측 끝) <---> [🔍 오류 검토] [다음 (3단계) ➡️](우측 끝) 2단 구조로 깔끔하게 정렬.
"""
from __future__ import annotations

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
            "ext": None, "ext_sig": None, "built_sig": None,
            "biz": {}, "biz_confirmed": [],
            "people": {}, "year_recs": {},
            "prev_summary": {},     # 기신고 명세서 또는 수기 입력 과거연도 인원 {"2024": {"상시": 0.0, "청년등": 0.0}, ...}
            "manual_extra_years": [],
            "grid_ver": {}, "last_sent": {},
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


def _years(s: dict) -> list[int]:
    """
    [2단계 사원정보 표에 표시할 연도 목록 결정]
    1) 기본 필수 비교연도:
       - 2024·2025·2026년 귀속: 당해연도(T)와 직전연도(T-1) 2개만 기본 표시!
         (예: 2026년 귀속은 2026·2025년만, 2025년 귀속은 2025·2024년만, 2024년 귀속은 2024·2023년만 기본 표시)
       - 2027년 귀속: 2027·2026·2025년 (A·B 산식 대상)
       - 2028년 귀속: 2028·2027·2026·2025년 (A·B·C 산식 대상)
    2) 추가 확장 연도:
       - 사용자가 1단계에서 직접 원천징수부를 업로드한 연도(예: 2026년 귀속인데 2024년·2023년 원천징수부를 직접 올린 경우)
       - 또는 2단계에서 사용자가 '과거연도 사원표 직접 열기'로 추가한 연도
    """
    t = int(s["tax_year"])
    comp = H.valid_comparison_years_for_new_credit(t)
    active_years = {t, t - 1}
    for k in ("A", "B", "C"):
        if comp.get(k) is not None:
            active_years.add(int(comp[k]))

    # 사용자가 실제로 원천징수부를 업로드한 연도는 모두 표로 보여줌
    active_years.update(_uploaded_wht_years(s))
    # 사용자가 수동으로 열기를 선택한 과거 연도도 포함
    for my in (s.get("manual_extra_years") or []):
        if isinstance(my, int):
            active_years.add(my)

    return sorted(active_years, reverse=True)


def _all_possible_years(s: dict) -> list[int]:
    """사원 데이터 초기화 시 사용할 전체 후보 연도 범위."""
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
    return {"corp_size": b.get("기업구분", "중소기업"), "months_in_year": n if n > 0 else 12}


# ══════════════════════════════════════════════════════════════════
# 1. "자율 에이전트AI" 100% 동일 톤앤매너 CSS (Pretendard + 에메랄드 그린 & 다크 네이비)
# ══════════════════════════════════════════════════════════════════
CSS = """
<style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');

/* 🪟 모달(Dialog) 창 가로 폭 확장 — 안내 문구가 줄바꿈으로 잘리지 않도록 여유 폭 보장 */
div[data-testid="stDialog"] > div[role="dialog"],
div[role="dialog"] {
    min-width: min(680px, 94vw) !important;
    max-width: 780px !important;
}
div[role="dialog"] li,
div[role="dialog"] p {
    font-family: 'Pretendard', 'Malgun Gothic', sans-serif !important;
    font-size: 0.98rem !important;
    line-height: 1.65 !important;
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

/* 📤 파일 업로드 드롭존 — 에메랄드 그린 호버 포인트 */
.st-key-ec_drop [data-testid="stFileUploaderDropzone"] {
    min-height: 175px;
    border: 2px dashed #94a3b8 !important;
    border-radius: 12px !important;
    background: linear-gradient(180deg, #f8fafc 0%, #f1f5f9 100%) !important;
    align-items: center;
    justify-content: center;
    transition: all 0.18s ease;
}
.st-key-ec_drop [data-testid="stFileUploaderDropzone"]:hover {
    border-color: #16a34a !important;
    background: #f0fdf4 !important;
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
    margin: 6px 0 14px 0;
    font-size: 0.94rem;
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
    font-size: 0.90rem;
}
.ec-docs td {
    padding: 9px 12px;
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
    font-size: 0.86rem;
}
.ec-docs td.fname {
    color: #15803d;
    font-weight: 700;
    font-size: 0.86rem;
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
    margin: 6px 0 10px 0;
}
.ec-legend span {
    display: inline-flex;
    align-items: center;
    padding: 3px 10px;
    border-radius: 6px;
    font-size: 0.82rem;
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
    margin-top: 16px;
    margin-bottom: 8px;
}
.ec-year-title {
    font-size: 1.12rem;
    font-weight: 800;
    color: #1e3a8a;
}
.ec-year-sub {
    font-size: 0.84rem;
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
    padding: 9px 14px;
    margin: 4px 0 20px 0;
    align-items: center;
    justify-content: space-between;
}
.ec-kpi-items {
    display: flex;
    gap: 18px;
    flex-wrap: wrap;
    font-size: 0.94rem;
    color: #1e293b;
}
.ec-kpi-items b {
    color: #15803d;
    font-size: 1.02rem;
    font-weight: 800;
}
.ec-law-banner {
    background-color: #f8fafc;
    border: 1px solid #e2e8f0;
    border-left: 4px solid #22c55e;
    padding: 9px 14px;
    border-radius: 7px;
    color: #334155;
    font-size: 0.90rem;
    margin-bottom: 12px;
    line-height: 1.55;
}
.ec-nav-divider {
    border-top: 1px dashed #cbd5e1;
    margin: 14px 0 12px 0;
}
</style>
"""


def _top_status_bar(s: dict):
    """자율 에이전트AI 상단과 동일한 디자인의 미니 상태바(.top-mini-status-bar)를 렌더링합니다."""
    b = s.get("biz") or {}
    corp_nm = (b.get("상호") or "").strip() or "상호 미입력"
    corp_sz = b.get("기업구분") or "중소기업"
    cap = H.is_capital_area(b.get("사업장소재지", ""))
    loc_str = "수도권" if cap is True else ("비수도권(수도권 밖)" if cap is False else "소재지 미입력")
    tax_yr = int(s.get("tax_year") or R.DEFAULT_TAX_YEAR)
    law_ver = "개정 신법 (인별 합산 · A+B+C 점증형)" if tax_yr >= 2026 else "구법 (3년 균등공제 · 신법기준 전년도 재계산)"
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
# 2. 별도 창(대화상자 — width="large" 적용으로 가로 폭 확보)
# ══════════════════════════════════════════════════════════════════
@st.dialog("📋 자료 확인 안내", width="large")
def _dlg_missing(msgs: list[str]):
    for m in msgs:
        st.markdown(f"- {m}")
    st.caption("확인을 누르면 현재까지 인식된 자료로 다음 단계로 넘어갑니다. 부족한 정보는 사원정보 화면과 사이드바에서 직접 입력·수정할 수 있습니다.")
    if st.button("✅ 확인 및 2단계(사원정보)로 이동", type="primary", use_container_width=True):
        _S()["go_step2"] = True
        st.rerun()


@st.dialog("🚫 통합고용세액공제 적용 불가 업종 안내", width="large")
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


@st.dialog("🔍 법령·심판례 기반 오류 검토 결과", width="large")
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
            f"<span class='sb-badge-green'>{tax_yr}년 (신법)</span>"
            if tax_yr >= 2026 else
            f"<span class='sb-badge-amber'>{tax_yr}년 (구법·경정)</span>"
        )
        st.markdown(
            f"<div class='sb-card-title'><span>📅 귀속사업연도</span>{yr_badge}</div>",
            unsafe_allow_html=True,
        )
        new_year = st.selectbox(
            "통합고용세액공제 계산 기준 사업연도",
            options=R.SUPPORTED_TAX_YEARS,
            index=R.SUPPORTED_TAX_YEARS.index(tax_yr),
            format_func=lambda y: f"{y}년 귀속 ({'개정 신법 A+B+C' if y >= 2026 else '구법 · 경정청구/연속공제'})",
            label_visibility="collapsed",
        )
        if new_year != s["tax_year"]:
            s["tax_year"] = new_year
            s["manual_extra_years"] = []
            s["built_sig"] = None            # 귀속연도가 바뀌면 해당 연도 기준으로 사원표 재구성
            st.rerun()

    # 📦 [사이드바 카드 B] 사업자정보
    with st.container(border=True, key="ec_biz"):
        b, conf = s["biz"], set(s["biz_confirmed"])
        cap = H.is_capital_area(b.get("사업장소재지", ""))
        if cap is True:
            loc_pill = "<span class='sb-badge-amber'>수도권 사업장</span>"
        elif cap is False:
            loc_pill = "<span class='sb-badge-green'>수도권 밖(비수도권)</span>"
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
        txt("사업장 소재지", "사업장소재지", "예: 서울특별시 강남구... / 경기도...")

        b["기업구분"] = st.selectbox(
            "기업 규모 구분",
            R.CORP_SIZES,
            index=R.CORP_SIZES.index(b.get("기업구분", "중소기업")) if b.get("기업구분") in R.CORP_SIZES else 0,
            key="ec_biz_size",
        )
        c1, c2 = st.columns(2)
        b["전년_월수"] = c1.number_input(f"직전({tax_yr-1}년) 월수", 0, 12, _int(b.get("전년_월수"), 12), key="ec_biz_pm")
        b["당해_월수"] = c2.number_input(f"당해({tax_yr}년) 월수", 0, 12, _int(b.get("당해_월수"), 12), key="ec_biz_cm")

        if conf:
            if st.button("🔓 사업자정보 잠금 해제 (직접 수정)", use_container_width=True, key="btn_unlock_biz"):
                s["biz_confirmed"] = []
                st.rerun()

    ind = f"{b.get('업태', '')} {b.get('종목', '')}".strip()
    if ind and H.is_excluded_industry(ind) and s["industry_alert_for"] != ind:
        s["industry_alert_for"] = ind
        _dlg_industry(ind)


# ══════════════════════════════════════════════════════════════════
# 4. 1단계: 자료 업로드 (귀속연도 연동 + 추가 과거/보충 자료 무제한 수용)
# ══════════════════════════════════════════════════════════════════
def _page_upload(extract_file_fn, log_tokens_fn, room_key):
    s = _S()
    tax_yr = int(s["tax_year"])
    if s.pop("go_step2", False):
        _enter_step2()
        st.rerun()

    st.markdown(f"### 📂 1. 자료 업로드 ({tax_yr}년 귀속 기준)")

    # 귀속연도별 핵심 법령 가이드 배너
    if tax_yr == 2026:
        st.markdown(
            "<div class='ec-law-banner'>"
            "💡 <b>[2026년 귀속 개정 세법 안내]</b> 「조세특례제한법」 제29조의8 제1항 단서에 따라 "
            "<b>2026년 신규 공제(A+B+C)는 2025년 대비 증가분(A)만 계산</b>하므로 <b>2026년·2025년 원천징수부만 필수</b>입니다. "
            "2024·2025년 구법 기공제분의 2·3차 연속공제 및 사후관리는 <b>「2025년 기신고 상시근로자 명세서」</b>의 인원수로 간편하게 처리됩니다 "
            "(2024년 원천징수부를 직접 올리신 경우에만 2단계에 2024년 사원표가 추가로 열립니다)."
            "</div>",
            unsafe_allow_html=True,
        )
    elif tax_yr in (2024, 2025):
        st.markdown(
            f"<div class='ec-law-banner'>"
            f"💡 <b>[{tax_yr}년 귀속 경정청구·기한후신고 안내]</b> {tax_yr}년 귀속분 계산을 위해 "
            f"<b>{tax_yr}년(당해) 및 {tax_yr - 1}년(직전) 원천징수부</b>가 필수이며, 직전 과세연도({tax_yr - 1}년) 인원도 "
            f"당해연도와 동일한 신법 기준(만 15~34세 등)으로 재산정하여 비교합니다."
            f"</div>",
            unsafe_allow_html=True,
        )
    else:
        comp_map = H.valid_comparison_years_for_new_credit(tax_yr)
        active_comp = [f"{k}({v}년)" for k, v in comp_map.items() if v is not None]
        st.markdown(
            f"<div class='ec-law-banner'>"
            f"💡 <b>[{tax_yr}년 귀속 점증형 공제 안내]</b> 비교 대상 과세연도: <b>{', '.join(active_comp)}</b> "
            f"(2024.12.31. 이전 개시 과세연도 제외 규정 반영)."
            f"</div>",
            unsafe_allow_html=True,
        )

    doc_types = R.get_doc_types(tax_yr)
    doc_help = R.get_doc_help(tax_yr)
    all_labels = R.get_all_selectable_doc_labels(tax_yr)
    base_keys = {k for k, *_ in doc_types}

    have: dict[str, list[str]] = {}
    for name, f in s["files"].items():
        if f.get("key"):
            have.setdefault(f["key"], []).append(name)

    trs = []
    # 1) 현재 귀속연도 기준 기본 체크리스트 서류 행
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

    # 2) 사용자가 기본 리스트 외에 추가로 올린 파일(예: 2022·2023년 원천징수부, 근로계약서 등) 자동 표시 행
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

    st.markdown(
        "<table class='ec-docs'><thead><tr>"
        "<th class='led-cell'>상태</th><th>자료명</th><th>검토 용도 및 법령 기준</th><th>업로드된 파일</th>"
        "</tr></thead><tbody>" + "".join(trs) + "</tbody></table>",
        unsafe_allow_html=True,
    )

    _, mid, _ = st.columns([0.6, 4.8, 0.6])
    with mid:
        with st.container(key="ec_drop"):
            ups = st.file_uploader(
                "📥 여기에 파일(PDF·엑셀·CSV·이미지)을 한꺼번에 끌어다 놓으세요 — 2021~2028년 원천징수부·기신고서·근로계약서 자동 분류",
                accept_multiple_files=True,
                type=["pdf", "xlsx", "xls", "csv", "png", "jpg", "jpeg"],
                key=f"ec_up_{s['uploader_ver']}",
            )
    new = [u for u in (ups or []) if u.name not in s["files"]]
    if new:
        with st.spinner(f"📄 {len(new)}개 파일에서 텍스트 및 표 데이터를 추출하고 있습니다..."):
            for u in new:
                text = extract_file_fn(u, room_key) or ""
                s["files"][u.name] = {"key": P.classify_file(u.name, text), "text": text}
        s["uploader_ver"] += 1
        st.rerun()

    if s["files"]:
        with st.container(border=True):
            c_h1, c_h2 = st.columns([4, 1])
            with c_h1:
                st.markdown(f"**📎 업로드된 파일 목록 ({len(s['files'])}건)** — *자동 분류가 다르면 오른쪽 드롭다운에서 변경하세요.*")
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
                    format_func=lambda k: "⚠️ 서류 종류를 선택하세요 (미선택 시 분석 제외)" if k is None else all_labels.get(k, str(k)),
                    label_visibility="collapsed",
                )
                if c3.button("삭제", key=f"ec_del_{name}", use_container_width=True):
                    s["files"].pop(name, None)
                    st.rerun()

    st.write("")
    _, right = st.columns([4.5, 1.5])
    if right.button("다음 (2단계 사원정보) ➡️", type="primary", use_container_width=True):
        classified: dict[str, list[str]] = {}
        for name, f in s["files"].items():
            if f.get("key"):
                classified.setdefault(f["key"], []).append(name)
        sig = json.dumps(sorted((n, f.get("key")) for n, f in s["files"].items()), ensure_ascii=False)
        if s["ext_sig"] != sig:
            texts = {k: "\n\n".join(s["files"][n]["text"] for n in names) for k, names in classified.items()}
            if texts:
                with st.spinner("🤖 서류에서 사업자·주주·임원·연도별 근로자 정보를 정밀 추출하고 있습니다..."):
                    s["ext"] = P.extract_all(texts, log_tokens_fn, room_key)
                    msgs = P.check_missing(classified, s["ext"], tax_yr)
                    msgs += [m for m in P.ai_extra_warnings(s["ext"], log_tokens_fn, room_key) if m not in msgs]
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

        # 기신고 명세서에서 읽어온 연도별 상시·청년등 숫자를 prev_summary에 초기 세팅
        prev_from_doc = ((ext.get("prev_filing") or {}).get("연도별") or {})
        ps = s.setdefault("prev_summary", {})
        for y_str, vals in prev_from_doc.items():
            if isinstance(vals, dict):
                ps[str(y_str)] = {
                    "상시": float(vals.get("상시") or 0.0) if vals.get("상시") is not None else None,
                    "청년등": float(vals.get("청년등") or 0.0) if vals.get("청년등") is not None else None,
                }

        s["grid_ver"], s["last_sent"] = {}, {}
        s["built_sig"] = sig
        for k in list(st.session_state.keys()):
            if str(k).startswith("ec_biz_"):
                del st.session_state[k]
    s["step"] = 2


# ══════════════════════════════════════════════════════════════════
# 5. 2단계: 사원정보 표 (AgGrid Pretendard·네이비/그린 스타일 + 연도별 KPI 요약 카드)
# ══════════════════════════════════════════════════════════════════
JS_LOCKED = JsCode("""
function(p){
  if (p.node.rowPinned) return false;
  const L = (p.data._lock || '').split(',');
  return !L.includes(p.colDef.field);
}""")

JS_STYLE = JsCode("""
function(p){
  const baseFont = {fontFamily: 'Pretendard, Malgun Gothic, sans-serif', fontSize: '13px'};
  if (p.node.rowPinned) return Object.assign(baseFont, {backgroundColor:'#dcfce7', color:'#14532d', fontWeight:'800'});
  const L = (p.data._lock || '').split(',');
  if (L.includes(p.colDef.field)) return Object.assign(baseFont, {backgroundColor:'#e2e8f0', color:'#0f172a', fontWeight:'600'});
  return Object.assign(baseFont, {backgroundColor:'#ffffff', color:'#1d4ed8', fontWeight:'600'});
}""")

JS_STYLE_REGULAR = JsCode("""
function(p){
  const baseFont = {fontFamily: 'Pretendard, Malgun Gothic, sans-serif', fontSize: '13px', textAlign: 'center'};
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
  const s = {fontFamily: 'Pretendard, Malgun Gothic, sans-serif', fontSize: '13px', textAlign:'center'};
  if (p.node.rowPinned) return Object.assign(s, {backgroundColor:'#dcfce7', color:'#14532d', fontWeight:'800'});
  const i = parseInt(p.colDef.field.slice(1)) - 1;
  if ((p.data._inact || '')[i] === '1') { s.backgroundColor = '#f1f5f9'; s.color = '#cbd5e1'; return s; }
  if ((p.data._lock || '').split(',').includes('M')) { s.backgroundColor = '#e2e8f0'; s.color = '#94a3b8'; return s; }
  s.color = '#1d4ed8';
  s.fontWeight = '600';
  s.backgroundColor = (p.data._ymask || '')[i] === '1' ? '#dcfce7' : '#ffffff';
  if ((p.data._nopay || '')[i] === '1') s.backgroundColor = '#fef9c3';
  if ((p.data._movr || '')[i] === '1') { s.border = '2px solid #f59e0b'; s.fontWeight = '800'; }
  return s;
}""")

JS_YOUTH_PARAMS = JsCode("""
function(p){ return {values: (p.data._yopts || '').split('|')}; }""")

JS_NUM_FMT = JsCode("""
function(p){
  if (p.value === null || p.value === undefined || p.value === '') return '';
  const v = Number(p.value); if (isNaN(v)) return p.value;
  return (Math.round(v * 10000) / 10000).toString();
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

        row = {
            "pid": pid,
            "성명": p.get("성명", ""),
            "생년월일": p.get("생년월일", ""),
            "입사일": p.get("입사일", ""),
            "퇴사일": disp_retire,
            "고용유형": yrec.get("고용유형") or R.EMP_REGULAR,
            "제외사유": c["제외사유"],
            "병역개월": int(p.get("병역개월", 0) or 0),
            "청년등": c["청년등"],
            "상시": c["상시"],
            **{MONTH_COLS[i]: c["months"][i] for i in range(12)},
            "합계": float(c["row_sum"]),
            "평균": round(c["row_avg"], 4),
            "_lock": ",".join(lock),
            "_yopts": "|".join(c["youth_options"]),
            "_ymask": "".join("1" if f else "0" for f in c["youth_flags"]),
            "_inact": "".join("1" if v is None else "0" for v in c["months"]),
            "_nopay": "".join("1" if (i + 1) in c["no_pay_months"] else "0" for i in range(12)),
            "_movr": "".join("1" if (i + 1) in ovr else "0" for i in range(12)),
            "_sovr": "1" if yrec.get("상시_override") else "0",
            "_sauto": c["상시_auto"],
        }
        rows.append(row)
    totals = H.year_totals(list(computed.values()), ctx["months_in_year"])
    return rows, computed, totals


def _grid_options(df: pd.DataFrame, totals: dict) -> dict:
    gb = GridOptionsBuilder.from_dataframe(df)
    gb.configure_default_column(
        resizable=True, sortable=False, filter=False, suppressMovable=True,
        editable=JS_LOCKED, cellStyle=JS_STYLE, minWidth=60
    )
    for c in [c for c in df.columns if c.startswith("_") or c == "pid"]:
        gb.configure_column(c, hide=True, editable=False)

    gb.configure_column("성명", pinned="left", width=92)
    for c in ("생년월일", "입사일", "퇴사일"):
        gb.configure_column(c, width=105)
    gb.configure_column("고용유형", width=155, cellEditor="agSelectCellEditor",
                        cellEditorParams={"values": R.EMP_TYPES})
    gb.configure_column("제외사유", headerName="상시근로자 제외사유", width=195, cellEditor="agSelectCellEditor",
                        cellEditorParams={"values": R.EXCL_REASONS})
    gb.configure_column("병역개월", headerName="병역(개월)", width=90, cellEditor="agNumberCellEditor",
                        cellEditorParams={"min": 0, "max": R.MILITARY_MAX_MONTHS, "precision": 0})
    gb.configure_column("청년등", headerName="청년등 상시근로자", width=155, cellEditor="agSelectCellEditor",
                        cellEditorParams=JS_YOUTH_PARAMS)
    gb.configure_column("상시", headerName="상시(O/X)", width=88, editable=True, cellStyle=JS_STYLE_REGULAR,
                        cellEditor="agSelectCellEditor", cellEditorParams={"values": ["O", "X"]})
    for i, c in enumerate(MONTH_COLS, start=1):
        gb.configure_column(
            c, headerName=f"{i}월", width=58, editable=JS_MONTH_EDITABLE, cellStyle=JS_MONTH_STYLE,
            cellEditor="agSelectCellEditor", cellEditorParams={"values": R.MONTH_CHOICES},
            valueFormatter=JS_NUM_FMT
        )
    sum_style = {
        "fontFamily": "Pretendard, Malgun Gothic, sans-serif",
        "fontSize": "13px",
        "backgroundColor": "#f1f5f9",
        "color": "#0f172a",
        "fontWeight": "800",
        "textAlign": "center",
    }
    gb.configure_column("합계", width=72, editable=False, valueFormatter=JS_NUM_FMT, cellStyle=sum_style)
    gb.configure_column("평균", width=78, editable=False, valueFormatter=JS_NUM_FMT, cellStyle=sum_style)
    gb.configure_grid_options(singleClickEdit=True, stopEditingWhenCellsLoseFocus=True, rowHeight=32, headerHeight=34)
    go = gb.build()

    n = totals["months_in_year"]
    pinned = []
    for label, mk, sk, ak in (
        ("상시근로자", "월별_상시", "상시_합계", "상시_평균"),
        ("청년등", "월별_청년등", "청년등_합계", "청년등_평균"),
        ("청년등 외", "월별_청년외", "청년외_합계", "청년외_평균"),
    ):
        r = {"성명": label, "생년월일": "", "고용유형": f"÷ {n}개월 (절사)"}
        r.update({MONTH_COLS[i]: totals[mk][i] for i in range(12)})
        r["합계"], r["평균"] = totals[sk], totals[ak]
        pinned.append(r)
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
    """표에서 바뀐 칸을 찾아 사람정보·연도별 입력값에 반영. 바뀐 게 있으면 True"""
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
    """연도별 법적 역할(당해/직전A/전전B/2024년 이전 제외 단서 등)을 명확히 설명합니다."""
    if year == tax_year:
        return "당해 과세연도 (공제 신청 기준연도)"
    if tax_year >= 2026 and year <= 2024:
        return "2024.12.31. 이전 개시 과세연도 — 신규공제(A+B+C) 비교에서는 제외(법 제29조의8 제1항 단서)되며, 구법 기공제분의 연속공제·사후관리 검증용"
    diff = tax_year - year
    if diff == 1:
        return "직전 과세연도 (A 산식 비교 대상 · 신법 기준 재산정)"
    if diff == 2:
        return "전전 과세연도 (B 산식 고용유지 비교 대상)"
    if diff == 3:
        return "전전전 과세연도 (C 산식 고용유지 비교 대상)"
    return "과거 비교·사후관리 참고 과세연도"


def _render_year(s: dict, year: int, room_key: str) -> tuple[dict, dict]:
    rows, computed, totals = _build_year_rows(s, year)
    tax_year = int(s["tax_year"])
    role_desc = _year_role_description(tax_year, year)

    st.markdown(
        f"<div class='ec-year-header'>"
        f"<span class='ec-year-title'>📅 {year}년 상시근로자 명세 ({len(rows)}명)</span>"
        f"<span class='ec-year-sub'>{role_desc}</span>"
        f"</div>",
        unsafe_allow_html=True,
    )

    if not rows:
        st.info(f"{year}년에 근무한 근로자가 없습니다. {year}년 원천징수부를 올렸는지 확인하거나 아래 [➕ 사원 추가]로 입력하세요.")
        return computed, totals

    df = pd.DataFrame(rows)
    s["last_sent"][year] = rows
    ver = s["grid_ver"].get(year, 0)
    custom_ag_css = {
        ".ag-header": {"background-color": "#1e293b !important", "color": "#ffffff !important"},
        ".ag-header-cell-text": {
            "color": "#ffffff !important",
            "font-weight": "700 !important",
            "font-family": "'Pretendard', 'Malgun Gothic', sans-serif !important",
            "font-size": "12.8px !important",
        },
        ".ag-root-wrapper": {"border-radius": "8px !important", "border": "1px solid #cbd5e1 !important"},
    }
    resp = AgGrid(
        df,
        gridOptions=_grid_options(df, totals),
        update_mode=GridUpdateMode.VALUE_CHANGED,
        allow_unsafe_jscode=True,
        theme="balham",
        custom_css=custom_ag_css,
        key=f"ec_grid_{year}_{ver}",
        height=min(650, 84 + 32 * (len(rows) + 3)),
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
        f"<span>👥 {year}년 전체 상시근로자: <b>{totals['상시_평균']:.2f}명</b> <small style='color:#64748b'>(연인원 {totals['상시_합계']:g} ÷ {totals['months_in_year']}개월)</small></span>"
        f"<span>🌱 청년등 상시근로자: <b>{totals['청년등_평균']:.2f}명</b> <small style='color:#64748b'>(연인원 {totals['청년등_합계']:g})</small></span>"
        f"<span>👔 청년등 외(일반): <b>{totals['청년외_평균']:.2f}명</b> <small style='color:#64748b'>(전체 절사후 - 청년등 절사후)</small></span>"
        f"</div>"
        f"<span class='sb-badge-green'>100분의 1 미만 절사 완료</span>"
        f"</div>",
        unsafe_allow_html=True,
    )
    return computed, totals


def _render_prev_filing_summary_card(s: dict, shown_years: list[int]):
    """
    2024년(또는 T-2년) 원천징수부를 직접 올리지 않아 2단계에 2024년 사원표가 뜨지 않을 때,
    기신고 상시근로자 명세서에서 읽어온 2024년 인원 숫자를 보여주거나(또는 3단계에서도 입력 가능하도록)
    필요시 사용자가 과거연도 사원표를 직접 열 수 있는 옵션을 제공합니다.
    """
    tax_yr = int(s["tax_year"])
    t2_year = tax_yr - 2
    if t2_year in shown_years:
        return

    ps = s.setdefault("prev_summary", {})
    y_entry = ps.setdefault(str(t2_year), {"상시": None, "청년등": None})
    has_prev_doc = bool(((s.get("ext") or {}).get("prev_filing") or {}).get("연도별"))

    with st.expander(
        f"📋 {t2_year}년 인원 처리 안내 — 원천징수부 미첨부로 빈 {t2_year}년 사원표는 숨김 처리되었습니다 (기신고 명세서 숫자 활용 또는 3단계에서 직접 입력)",
        expanded=has_prev_doc,
    ):
        st.caption(
            f"💡 **{tax_yr}년 귀속 신규 공제(A)**에는 **{tax_yr}년·{tax_yr - 1}년 사원표 2개**만 필요합니다. "
            f"{t2_year}년 귀속 구법 기공제분의 연속공제·사후관리가 있는 경우, 1단계에 올리신 **기신고 상시근로자 명세서**에서 읽어온 아래 숫자로 처리하거나 "
            f"**3단계(공제액 계산)** 화면에서 직접 입력할 수 있습니다."
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
    st.markdown(
        "<div class='ec-legend'>"
        "<span style='background:#e2e8f0;color:#0f172a;border:1px solid #cbd5e1'>🔒 서류로 확인된 값</span>"
        "<span style='background:#ffffff;color:#1d4ed8;border:1px solid #93c5fd'>✏️ 입력·선택 가능</span>"
        "<span style='background:#dcfce7;color:#14532d;border:1px solid #86efac'>🌱 청년등 인정 월</span>"
        "<span style='background:#fef9c3;color:#854d0e;border:1px solid #fde047'>⚠️ 급여 지급 없는 달 (4대보험 납부유예 확인)</span>"
        "<span style='background:#ffffff;color:#0f172a;border:2px solid #f59e0b'>🔧 직접 수정한 값</span>"
        "</div>",
        unsafe_allow_html=True,
    )
    st.caption(
        "💡 왼쪽부터 **고용유형 → 상시근로자 제외사유 → 병역(개월) → 청년등 상시근로자** 순서로 선택하세요. "
        "병역기간은 최대 72개월(6년)까지 나이에서 차감하며, 청년 정규직(계약체결 시 34세 이하)은 체결일부터 4년간(일반기업 3년) 34세 초과 후에도 청년등으로 인정됩니다. "
        "회색 잠금 칸을 수정하려면 해당 근로자의 **상시(O/X)**를 한 번 전환하면 잠금이 해제됩니다."
    )

    if not s["people"]:
        st.info("읽어온 근로자가 없습니다. 아래 [➕ 사원 추가] 버튼으로 직접 입력하시거나 [< 이전]을 눌러 원천징수부를 업로드하세요.")

    computed_all, totals_all, ctx_all = {}, {}, {}
    for y in shown_years:
        computed_all[y], totals_all[y] = _render_year(s, y, room_key)
        ctx_all[y] = _ctx(s, y)

    # 2024년(또는 T-2년) 원천징수부를 올리지 않았을 때 기신고 명세서 숫자 확인·입력 카드 표시
    _render_prev_filing_summary_card(s, shown_years)

    # 직전연도 대비 증감(Cap 적용) 요약 미리보기 배너
    if tax_yr in totals_all and (tax_yr - 1) in totals_all:
        cur_t, prv_t = totals_all[tax_yr], totals_all[tax_yr - 1]
        inc = H.calc_increase_with_cap(
            cur_t["상시_평균"], cur_t["청년등_평균"], cur_t["청년외_평균"],
            prv_t["상시_평균"], prv_t["청년등_평균"], prv_t["청년외_평균"],
        )
        cap_note = ""
        if inc.get("청년등_한도적용전", 0) > inc["청년등_증가"] or inc.get("청년등외_한도적용전", 0) > inc["청년등외_증가"]:
            cap_note = " &nbsp;·&nbsp; ⚠️ <b>전체 상시근로자 증가인원 한도(Cap) 자동 적용됨(조심2023부6839)</b>"
        st.markdown(
            f"<div class='ec-law-banner'>"
            f"📊 <b>[{tax_yr}년 vs {tax_yr-1}년(A) 고용증가 요약 미리보기]</b> &nbsp; "
            f"전체 상시 증가: <b>+{inc['전체_증가']:.2f}명</b> &nbsp;|&nbsp; "
            f"청년등 인정 증가: <b>+{inc['청년등_증가']:.2f}명</b> &nbsp;|&nbsp; "
            f"청년등 외 인정 증가: <b>+{inc['청년등외_증가']:.2f}명</b>{cap_note}"
            f"</div>",
            unsafe_allow_html=True,
        )

    # ── 1단: 왼쪽 끝 [➕ 사원 추가] ─────────────────────────────────────
    c_add, _ = st.columns([1.3, 5.8])
    if c_add.button("➕ 사원 추가", use_container_width=True):
        seq = int(s.get("next_pid_seq", 1))
        s["next_pid_seq"] = seq + 1
        pid = f"manual_{seq}_{uuid.uuid4().hex[:6]}"
        s["people"][pid] = {
            "pid": pid, "성명": f"신규사원{seq}", "생년월일": "", "입사일": "", "퇴사일": "",
            "계약체결일": "", "병역개월": 0, "월급여": {}, "연도별_퇴사일": {}, "_confirmed": []
        }
        for y in _all_possible_years(s):
            s["year_recs"].setdefault(y, {})[pid] = P.new_year_rec()
            s["grid_ver"][y] = s["grid_ver"].get(y, 0) + 1
        st.rerun()

    # ── 2단(살짝 간격을 둔 하단 네비게이션): [< 이전] (왼쪽 끝) <---> [오류 검토] [다음(3단계)] (오른쪽 끝) ──
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
# 6. 진입점
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
    else:
        st.info("3단계(공제액 계산)와 4단계(보고서)는 2단계 확인이 끝난 뒤 이어서 만듭니다.")
        if st.button("< 이전 (2단계 사원정보)"):
            s["step"] = 2
            st.rerun()
