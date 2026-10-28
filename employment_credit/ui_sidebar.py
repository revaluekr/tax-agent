# -*- coding: utf-8 -*-
"""통합고용세액공제 계산기 화면 — 사이드바: 귀속연도·사업자정보·추가 사업장·작업 백업

(ui.py에서 나눈 파일. 함수 본문은 원래 ui.py와 같습니다.)
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

from .ui_common import (  # noqa: F401
    _S,
    _current_build_sig,
    _default_state_dict,
    _ensure_built_for_tax_year,
    _save_ec_to_disk,
)



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


@st.dialog("🔎 국세청 사업자상태 · 진위확인 · DART 주주/업종 대사", width="large")
def _dlg_nts_dart_check():
    s = _S()
    b = s.get("biz") or {}
    sub_list = s.get("sub_biz_list") or []
    tax_yr = int(s.get("tax_year") or R.DEFAULT_TAX_YEAR)
    ext_biz = (s.get("ext") or {}).get("biz_reg") or {}
    default_ceo = str(ext_biz.get("대표자") or "").strip()

    try:
        import law_api as _law_api
    except Exception:
        _law_api = None

    if _law_api is None:
        st.error("프로젝트 루트의 `law_api.py` 모듈을 불러올 수 없습니다.")
        return

    tab_nts, tab_verify, tab_dart, tab_ins = st.tabs([
        "🏛️ 1. 국세청 휴·폐업/과세유형",
        "🛡️ 2. 사업자 진위확인",
        "📊 3. DART 주주 · 업종코드",
        "👷 4. 4대보험 월·연 고지액 · 인원 대사",
    ])

    with tab_nts:
        st.caption("주사업장(본점) 및 합산 대상 추가 사업장의 사업자등록번호로 국세청 실시간 납세자상태(계속/휴·폐업일자) 및 과세유형을 일괄 조회합니다.")
        all_bnos = []
        if b.get("사업자번호"):
            all_bnos.append(f"{b.get('상호') or '주사업장'}: {b.get('사업자번호')}")
        for idx, sb in enumerate(sub_list):
            if sb.get("사업자번호"):
                all_bnos.append(f"{sb.get('상호') or f'제{idx+2}사업장'}: {sb.get('사업자번호')}")
        default_bno_str = ", ".join(all_bnos) if all_bnos else str(b.get("사업자번호") or "")
        bno_input = st.text_input(
            "조회할 사업자등록번호 (복수 입력 시 쉼표로 구분)",
            value=default_bno_str,
            placeholder="예: 123-45-67890, 234-56-78901",
            key="ec_nts_status_input",
        )
        if st.button("🔎 국세청 실시간 상태 조회 실행", type="primary", use_container_width=True, key="btn_run_ec_nts_status"):
            with st.spinner("국세청 API로 사업자 상태 및 휴·폐업일자를 조회하고 있습니다..."):
                st.session_state["ec_nts_status_res"] = _law_api.get_nts_biz_status(bno_input)
        res_txt = st.session_state.get("ec_nts_status_res")
        if res_txt:
            st.code(res_txt, language="text")

    with tab_verify:
        st.caption("국세청 사업자등록정보 진위확인 API를 통해 사업자번호·개업일·대표자성명 일치 여부를 검증합니다.")
        cv1, cv2 = st.columns(2)
        v_bno = cv1.text_input("사업자등록번호 (10자리)", value=str(b.get("사업자번호") or ""), key="ec_v_bno")
        v_dt = cv2.text_input("개업일/설립일 (YYYY-MM-DD)", value=str(b.get("설립일") or ""), key="ec_v_dt")
        cv3, cv4 = st.columns(2)
        v_ceo = cv3.text_input("대표자 성명 (필수)", value=default_ceo, placeholder="예: 홍길동", key="ec_v_ceo")
        v_nm = cv4.text_input("상호(법인명, 선택)", value=str(b.get("상호") or ""), key="ec_v_nm")
        if st.button("🛡️ 국세청 진위확인 실행", type="primary", use_container_width=True, key="btn_run_ec_nts_verify"):
            with st.spinner("국세청 진위확인 API 호출 중..."):
                st.session_state["ec_nts_verify_res"] = _law_api.verify_nts_biz_info(v_bno, v_dt, v_ceo, v_nm)
        v_res = st.session_state.get("ec_nts_verify_res")
        if v_res:
            st.code(v_res, language="text")

    with tab_dart:
        st.caption("외감·상장법인의 Open DART 공시 최대주주·특수관계인 지분현황을 조회하여 2단계 사원표의 상시근로자 제외대상 누락 여부를 대사하고, 국세청 6자리 업종코드를 검색합니다.")
        cd1, cd2, cd3 = st.columns([2.5, 1.2, 1.3])
        d_corp = cd1.text_input("DART 조회 법인명", value=str(b.get("상호") or ""), key="ec_dart_corp_nm")
        d_yr = cd2.text_input("사업보고서 연도", value=str(tax_yr - 1), key="ec_dart_yr")
        if cd3.button("📊 DART 조회", type="primary", use_container_width=True, key="btn_run_ec_dart"):
            with st.spinner("Open DART 전자공시 데이터를 조회하고 있습니다..."):
                dart_txt = _law_api.get_dart_corp_info(d_corp, d_yr)
                st.session_state["ec_dart_res"] = dart_txt
        d_res = st.session_state.get("ec_dart_res")
        if d_res:
            emp_names = {
                str(p.get("성명") or "").strip()
                for p in (s.get("people") or {}).values()
                if str(p.get("성명") or "").strip()
            }
            matched_emp = sorted(nm for nm in emp_names if len(nm) >= 2 and nm in d_res)
            if matched_emp:
                st.warning(
                    f"⚠️ 현재 사원표 인원 중 DART 공시문서(대표자·최대주주·특수관계인)에 등장하는 성명이 감지되었습니다: "
                    f"**{', '.join(matched_emp)}** → 2단계 사원표에서 임원·최대주주·배우자·직계존비속 제외사유를 확인하세요."
                )
            st.code(d_res, language="text")

        st.markdown("---")
        ci1, ci2 = st.columns([3.7, 1.3])
        ind_kw = ci1.text_input(
            "국세청 6자리 업종코드 검색어",
            value=str(b.get("종목") or b.get("업태") or ""),
            placeholder="예: 소프트웨어, 도소매, 음식점, 호스텔",
            key="ec_ind_kw",
        )
        if ci2.button("🏢 업종코드 검색", use_container_width=True, key="btn_run_ec_ind"):
            st.session_state["ec_ind_res"] = _law_api.search_industry_code(ind_kw)
        if st.session_state.get("ec_ind_res"):
            st.code(st.session_state["ec_ind_res"], language="text")

    with tab_ins:
        st.caption(
            "근로복지공단(고용·산재보험 상시인원·업종·성립일) 및 국민연금공단(월별 고지액·가입자수) Open API를 실시간 교차 조회하여 "
            "**4대보험(국민연금·건강·장기요양·고용·산재) 전체 월별 고지보험료 및 연간 고지총액 합계(사업주/근로자 부담분)**와 사원표 인원을 대사합니다."
        )
        ci_a, ci_b = st.columns([3.5, 1.5])
        cw_bno = ci_a.text_input(
            "근로복지공단 조회용 사업자등록번호 (10자리, 복수 가능)",
            value=str(b.get("사업자번호") or ""),
            placeholder="예: 123-45-67890",
            key="ec_comwel_bno",
        )
        if ci_b.button("👷 고용·산재 조회", type="primary", use_container_width=True, key="btn_run_ec_comwel"):
            with st.spinner("근로복지공단 고용·산재보험 현황 조회 중..."):
                st.session_state["ec_comwel_res"] = _law_api.get_comwel_workplace_info(cw_bno)
        if st.session_state.get("ec_comwel_res"):
            st.code(st.session_state["ec_comwel_res"], language="text")

        st.markdown("---")
        cn1, cn2, cn3, cn4 = st.columns([1.9, 1.3, 0.9, 1.4])
        nps_nm = cn1.text_input("4대보험 조회 사업장명(상호)", value=str(b.get("상호") or ""), key="ec_nps_nm")
        nps_bno6 = cn2.text_input(
            "사업자번호(10자리 권장·앞6자리 가능)",
            value=str(b.get("사업자번호") or ""),
            placeholder="10자리 입력 시 산재업종 자동연계",
            key="ec_nps_bno6",
        )
        nps_yr = cn3.text_input("연도(비우면 전체)", value="", placeholder=str(tax_yr), key="ec_nps_yr")
        if cn4.button("🏦 4대보험 월·연 고지액", type="primary", use_container_width=True, key="btn_run_ec_nps"):
            with st.spinner("4대보험(국민연금·건보·장기요양·고용·산재) 월별·연간 고지총액 및 인원 병렬 조회 중..."):
                st.session_state["ec_nps_res"] = _law_api.get_nps_workplace_info(nps_nm, nps_bno6, target_year=nps_yr)
        if st.session_state.get("ec_nps_res"):
            st.code(st.session_state["ec_nps_res"], language="text")


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

        # ── 과거 공제연도(T-1 · T-2) 당시 사업장 소재지 빠른 설정 (지방→수도권 이전 기업용) ──
        ps_sb = s.setdefault("prev_summary", {})
        with st.expander(f"📍 과거 공제연도({tax_yr-2}·{tax_yr-1}년) 소재지 설정 (이전 기업용)", expanded=False):
            st.caption(
                "2·3차년도 연속공제 및 추가납부 단가는 **최초 공제연도 당시 소재지** 기준입니다(예: 2024년 비수도권 공제 후 2025년 수도권 이전 시 2024년분은 비수도권 단가 유지)."
            )
            loc_opts_sb = ["현재 소재지와 같음", "수도권", "수도권 외(비수도권)"]
            for coh_y in (tax_yr - 1, tax_yr - 2):
                f_coh = ps_sb.setdefault(str(coh_y), {})
                cur_c_loc = f_coh.get("수도권")
                idx_c = 0 if cur_c_loc is None else (1 if cur_c_loc else 2)
                sel_c = st.selectbox(
                    f"{coh_y}년 귀속 공제 당시 소재지",
                    loc_opts_sb,
                    index=idx_c,
                    key=f"ec_sb_coh_loc_{coh_y}_{tax_yr}",
                )
                new_c_loc = None if sel_c == loc_opts_sb[0] else (sel_c == "수도권")
                if new_c_loc != cur_c_loc:
                    f_coh["수도권"] = new_c_loc
                    f_coh["_소재지_추정"] = False
                    _save_ec_to_disk(s)
                    st.rerun()

        if hasattr(R, "verify_golden_case_invariants"):
            ok_g, errs_g = R.verify_golden_case_invariants()
            if ok_g:
                st.markdown(
                    "<div style='margin-top:4px;padding:4px 8px;background:#f0fdf4;border:1px solid #bbf7d0;border-radius:6px;"
                    "font-size:0.76rem;font-weight:700;color:#15803d;text-align:center;'>"
                    "🛡️ 정본 산식 · 단가 회귀검증(0.01명·1원 무오차) 정상"
                    "</div>",
                    unsafe_allow_html=True,
                )
            else:
                st.error("⚠️ 산식 회귀검증 경고: " + "; ".join(errs_g))

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

        if st.button(
            "🔎 국세청 · DART · 4대보험 사업장 대사",
            use_container_width=True,
            key="btn_open_nts_dart_modal",
            help="국세청 API(사업자 휴·폐업일·과세유형·진위확인) 및 Open DART(최대주주·특수관계인 지분 공시)를 실시간 조회합니다.",
        ):
            _dlg_nts_dart_check()

    _save_ec_to_disk(s)
    _render_backup_card(s)
    ind = f"{b.get('업태', '')} {b.get('종목', '')}".strip()
    if ind and H.is_excluded_industry(ind) and s["industry_alert_for"] != ind:
        s["industry_alert_for"] = ind
        _dlg_industry(ind)


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