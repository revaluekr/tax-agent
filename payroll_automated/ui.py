# -*- coding: utf-8 -*-
"""
인건비 자동화 UI 모듈 (payroll_automated/ui.py)
- 좌측 사이드바:
  1) 개정사항 모니터링 카드 (근로기준법, 소득세법 근로소득/비과세, 소득세법 시행령 별표2 간이세액표, 2026년 4대보험 요율 — 실시간 법제처 API 연동)
  2) 작업 초기화 3D 버튼 카드
  3) 좌·우 3D 모드 전환 버튼 ([급여명세서] 파스텔 블루 / [사업소득] 파스텔 퍼플)
  4) 사업자정보 카드 (거래처명, 귀속연월, 지급일자, 상시근로자 수 통합 입력 및 5인 이상/미만 자동 연동, 사업주 고용보험 요율 선택, [당월 검토보고], [통합고용세액공제 계산])
  5) 거래처별 월별 누적 암호화 백업 카드 (.paybak)
- 우측 메인 화면:
  1) 최상단 툴바: 좌측([전월 급여 불러오기], [행 추가], [마지막 행 삭제]) /
     우측([경고·주의사항] 상태점 표시 버튼, [연장·야간·휴일근로수당 계산기], [주휴수당 계산기])
  2) AG Grid 편집 대장 (급여대장 / 사업소득대장 실시간 편집 및 자동 재계산)
  3) 서식 일괄 다운로드 바 (근로자 200명 / 사업소득 100명 한 번에 압축, 초과 시 구간 선택 · 버튼 클릭 시 지연 생성)
  4) 하단 드래그앤드롭 파일 업로드 영역 및 올인원 채팅·파일 입력창 (st.chat_input)
- 이모티콘 미사용 원칙 준수 (순수 텍스트 및 CSS 원형 인디케이터만 사용)
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode

from .backup import (
    build_employment_credit_bridge_payload,
    create_empty_client_db,
    decrypt_paybak_to_client_db,
    encrypt_client_db_to_paybak,
    get_previous_month_data,
    upsert_monthly_data_into_db,
)
from .calculators import (
    MONTHLY_REPORT_LEGAL_REFERENCES,
    WARNING_MODAL_LEGAL_REFERENCES,
    analyze_payroll_warnings,
    calculate_overtime_night_holiday_allowance,
    calculate_weekly_holiday_allowance,
    check_payroll_law_revisions,
)
from .exporters import (
    export_employee_payslips_zip,
    export_freelancer_ledger_pdf,
    export_freelancer_statements_jpg_zip,
    export_freelancer_statements_pdf_zip,
    export_payroll_ledger_pdf,
    export_wehago_freelancer_excel,
    export_wehago_payroll_excel,
)
from .parsers import (
    apply_insurance_notices_to_employees,
    parse_client_payroll_excel,
    parse_freelancer_excel,
    parse_image_with_gemini_vision,
    parse_insurance_notice_pdf,
    parse_kakao_text_instructions,
)
from .tax_tables import (
    EI_STABILITY_TIERS,
    calc_4ins_employer_share,
    calculate_employee_payroll_row,
    calculate_freelancer_row,
    is_ceo_position,
    solve_gross_from_net_employee,
    solve_gross_from_net_freelancer,
)


# ─────────────────────────────────────────────────────────────
# 전용 CSS (3D 파스텔 블루/퍼플 버튼, 모니터 내 모달 스크롤 보호, CSS 상태 원형 점)
# ─────────────────────────────────────────────────────────────

PAYROLL_CSS = """
<style>
/* 사이드바 최상단 2x2 그리드 버튼 동일 규격 */
.st-key-btn_top_mode_agent button,
.st-key-btn_top_mode_credit button,
.st-key-btn_top_mode_payroll button,
.st-key-btn_top_mode_reserved button {
    border-radius: 10px !important;
    min-height: 40px !important;
    height: 40px !important;
    padding: 6px 8px !important;
    font-size: 0.88rem !important;
    font-weight: 800 !important;
    letter-spacing: -0.3px !important;
}

/* [급여명세서] / [사업소득] 3D 입체 버튼 (파스텔 블루 & 파스텔 퍼플) */
.st-key-btn_pay_submode_emp button,
.st-key-btn_pay_submode_free button {
    border-radius: 9px !important;
    min-height: 40px !important;
    height: 40px !important;
    font-size: 0.88rem !important;
    font-weight: 800 !important;
    transition: all 0.14s ease !important;
    background: linear-gradient(180deg, #ffffff 0%, #f1f5f9 100%) !important;
    border: 1px solid #cbd5e1 !important;
    border-bottom: 3px solid #94a3b8 !important;
    color: #334155 !important;
    box-shadow: 0 2px 4px rgba(15, 23, 42, 0.06) !important;
}
.st-key-btn_pay_submode_emp_active button {
    border-radius: 9px !important;
    min-height: 40px !important;
    height: 40px !important;
    font-size: 0.88rem !important;
    font-weight: 800 !important;
    background: linear-gradient(180deg, #dbeafe 0%, #bfdbfe 100%) !important;
    border: 1.5px solid #60a5fa !important;
    border-bottom: 3.5px solid #2563eb !important;
    color: #1e3a8a !important;
    box-shadow: 0 3px 6px rgba(37, 99, 235, 0.18) !important;
}
.st-key-btn_pay_submode_emp_active button p {
    color: #1e3a8a !important;
    font-weight: 800 !important;
}
.st-key-btn_pay_submode_free_active button {
    border-radius: 9px !important;
    min-height: 40px !important;
    height: 40px !important;
    font-size: 0.88rem !important;
    font-weight: 800 !important;
    background: linear-gradient(180deg, #ede9fe 0%, #ddd6fe 100%) !important;
    border: 1.5px solid #a78bfa !important;
    border-bottom: 3.5px solid #7c3aed !important;
    color: #4c1d95 !important;
    box-shadow: 0 3px 6px rgba(124, 58, 237, 0.18) !important;
}
.st-key-btn_pay_submode_free_active button p {
    color: #4c1d95 !important;
    font-weight: 800 !important;
}

/* 사이드바 3D 액션 버튼 (작업초기화 / 당월 검토보고 / 통합고용세액공제 계산 / 상세보기) */
.st-key-btn_pay_reset_ask button,
.st-key-btn_pay_law_detail button,
.st-key-btn_pay_monthly_report button,
.st-key-btn_pay_bridge_credit button {
    background: linear-gradient(180deg, #ffffff 0%, #f1f5f9 100%) !important;
    border: 1px solid #94a3b8 !important;
    border-bottom: 2.5px solid #64748b !important;
    border-radius: 8px !important;
    min-height: 2.25rem !important;
    font-size: 0.85rem !important;
    font-weight: 700 !important;
    color: #1e293b !important;
    box-shadow: 0 2px 4px rgba(15, 23, 42, 0.08) !important;
}
.st-key-btn_pay_bridge_credit button {
    background: linear-gradient(180deg, #f0fdf4 0%, #dcfce7 100%) !important;
    border: 1px solid #4ade80 !important;
    border-bottom: 2.5px solid #16a34a !important;
    color: #14532d !important;
}

/* 상태 원형 점 (이모티콘 없이 순수 CSS 원형 도트) */
.pay-dot {
    display: inline-block;
    width: 9px;
    height: 9px;
    border-radius: 50%;
    margin-right: 6px;
    vertical-align: middle;
}
.pay-dot-gray {
    background-color: #94a3b8;
    box-shadow: 0 0 0 2px rgba(148, 163, 184, 0.25);
}
.pay-dot-green {
    background-color: #16a34a;
    box-shadow: 0 0 0 2px rgba(22, 163, 74, 0.25);
}
.pay-dot-yellow {
    background-color: #eab308;
    box-shadow: 0 0 0 2px rgba(234, 179, 8, 0.30);
}
.pay-dot-red {
    background-color: #dc2626;
    box-shadow: 0 0 0 2px rgba(220, 38, 38, 0.30);
}

/* 개정사항 카드 상태 행 */
.pay-law-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    font-size: 0.80rem;
    color: #334155;
    padding: 3px 0;
}
.pay-law-badge-green {
    background-color: #dcfce7;
    color: #15803d;
    font-size: 0.70rem;
    font-weight: 700;
    padding: 1px 6px;
    border-radius: 999px;
}
.pay-law-badge-amber {
    background-color: #fef3c7;
    color: #b45309;
    font-size: 0.70rem;
    font-weight: 700;
    padding: 1px 6px;
    border-radius: 999px;
}

/* 모달 팝업 상하단 잘림 방지 (모니터 화면 안에 100% 들어오도록 고정) */
div[data-testid="stDialog"] div[role="dialog"] {
    max-height: 85vh !important;
    overflow-y: auto !important;
}
.pay-modal-scroll-box {
    max-height: 68vh;
    overflow-y: auto;
    padding-right: 6px;
}
.pay-formula-box {
    background-color: #f8fafc;
    border: 1px solid #cbd5e1;
    border-left: 4px solid #2563eb;
    border-radius: 6px;
    padding: 10px 14px;
    margin-top: 10px;
    margin-bottom: 10px;
    font-size: 0.90rem;
    color: #1e293b;
}
.pay-law-ref-box {
    background-color: #fcfcfd;
    border: 1px solid #e2e8f0;
    border-left: 4px solid #475569;
    border-radius: 6px;
    padding: 10px 14px;
    margin-top: 8px;
    font-size: 0.86rem;
    color: #334155;
}
</style>
"""


# ─────────────────────────────────────────────────────────────
# 세션 상태 초기화 및 헬퍼 (급여명세서 200명 / 사업소득명세서 100명 기준)
# ─────────────────────────────────────────────────────────────

EMP_ZIP_MAX = 200
FREE_ZIP_MAX = 100


def _lazy_bytes(fn, *args, enabled: bool = True, **kwargs):
    """
    다운로드 버튼을 실제로 클릭할 때만 PDF/ZIP/XLSX 파일을 생성하도록 호출 가능한 함수(Callable)를 반환합니다.
    매 화면 리런마다 무거운 deepcopy를 수행하지 않고 얕은 스냅샷 참조만 전달하여 메모리와 속도를 최적화합니다.
    """
    if not enabled:
        return b""
    captured_args = tuple(list(a) if isinstance(a, list) else a for a in args)
    captured_kwargs = {k: (list(v) if isinstance(v, list) else v) for k, v in kwargs.items()}
    return lambda: fn(*captured_args, **captured_kwargs)


def _get_payroll_state() -> Dict[str, Any]:
    if "payroll_auto_state" not in st.session_state:
        now = datetime.now()
        default_ym = now.strftime("%Y-%m")
        default_pay_dt = now.strftime("%Y-%m-25")
        st.session_state.payroll_auto_state = {
            "sub_mode": "EMP",  # "EMP" (급여명세서) | "FREE" (사업소득)
            "corp_name": "",
            "year_month": default_ym,
            "pay_date": default_pay_dt,
            "is_5_or_more": True,
            "ei_emp_count": 0,
            "ei_emp_count_manual": None,
            "ei_stability_tier": EI_STABILITY_TIERS[0][0],
            "ei_stability_tier_manual": None,
            "withholding_rate_pct": 100,
            "effective_table": "2026.03",
            "encrypt_payslip_zip": False,
            "employees": [],
            "freelancers": [],
            "prev_employees": [],
            "prev_freelancers": [],
            "notice_logs": [],
            "chat_logs": [],
            "client_db": create_empty_client_db(""),
            "grid_version": 0,
        }
    return st.session_state.payroll_auto_state


def _reset_payroll_current_work() -> None:
    """
    [작업 초기화 (내용 비우기)] 실행 시 대장 목록뿐만 아니라
    수기 입력했던 상시근로자 수 및 고용보험 요율 선택값도 초기 상태로 함께 리셋합니다.
    """
    pstate = _get_payroll_state()
    pstate["employees"] = []
    pstate["freelancers"] = []
    pstate["notice_logs"] = []
    pstate["chat_logs"] = []
    pstate["ei_emp_count"] = 0
    pstate["ei_emp_count_manual"] = None
    pstate["ei_stability_tier"] = EI_STABILITY_TIERS[0][0]
    pstate["ei_stability_tier_manual"] = None
    pstate["is_5_or_more"] = False
    pstate["grid_version"] = int(pstate.get("grid_version", 0)) + 1


def _recalculate_all_employee_rows(pstate: Dict[str, Any]) -> None:
    eff_tbl = pstate.get("effective_table", "2026.03")
    pct = int(pstate.get("withholding_rate_pct", 100))
    new_list: List[Dict[str, Any]] = []
    for idx, emp in enumerate(pstate.get("employees", []), start=1):
        in_mode = str(emp.get("입력기준", "세전")).strip()
        ins_mode = str(emp.get("보험적용구분", "요율(2순위)")).strip()
        ceo_flag = is_ceo_position(emp.get("직급", ""))
        notice_ins = None
        if ins_mode.startswith("고지") or any(
            emp.get(flag) for flag in ("_nhis_notice_applied", "_nps_notice_applied", "_ei_notice_applied")
        ):
            notice_ins = {
                "국민연금": int(emp.get("국민연금", 0) or 0),
                "건강보험": int(emp.get("건강보험", 0) or 0),
                "장기요양보험료": int(emp.get("장기요양보험료", 0) or 0),
                "고용보험": int(emp.get("고용보험", 0) or 0),
                "건강보험료정산": int(emp.get("건강보험료정산", 0) or 0),
                "장기요양보험료정산": int(emp.get("장기요양보험료정산", 0) or 0),
                "국민연금정산": int(emp.get("국민연금정산", 0) or 0),
            }

        deps = max(1, int(emp.get("부양가족수", 1) or 1))
        children = max(0, int(emp.get("자녀수", 0) or 0))
        meal = int(emp.get("식대", 0) or 0)
        car = int(emp.get("자가운전보조금", 0) or 0)

        if in_mode == "세후역산" and int(emp.get("목표실수령액", 0) or 0) > 0:
            solved = solve_gross_from_net_employee(
                target_net_pay=int(emp["목표실수령액"]),
                non_taxable_pay=meal + car,
                dependents=deps,
                children_8_20=children,
                withholding_rate_pct=pct,
                notice_insurance=notice_ins,
                student_loan_repayment=int(emp.get("학자금상환액", 0) or 0),
                effective_table=eff_tbl,
                is_ceo=ceo_flag,
            )
            emp["기본급"] = solved["base_pay"]

        calc = calculate_employee_payroll_row(
            base_pay=int(emp.get("기본급", 0) or 0),
            bonus=int(emp.get("상여", 0) or 0),
            meal_allowance=meal,
            car_allowance=car,
            fixed_overtime_pay=int(emp.get("약정연장근로수당", 0) or 0),
            fixed_holiday_pay=int(emp.get("약정휴일근로수당", 0) or 0),
            overtime_pay=int(emp.get("연장근로수당", 0) or 0),
            holiday_pay=int(emp.get("휴일근로수당", 0) or 0),
            unused_leave_pay=int(emp.get("미사용연차수당", 0) or 0),
            absence_deduction=int(emp.get("결근공제", 0) or 0),
            adjustment_pay=int(emp.get("조정금액", 0) or 0),
            dependents=deps,
            children_8_20=children,
            withholding_rate_pct=pct,
            notice_insurance=notice_ins,
            student_loan_repayment=int(emp.get("학자금상환액", 0) or 0),
            effective_table=eff_tbl,
            is_ceo=ceo_flag,
        )
        emp.update(calc)
        if not emp.get("사원코드"):
            emp["사원코드"] = f"{idx:03d}"
        new_list.append(emp)
    pstate["employees"] = new_list


def _recalculate_all_freelancer_rows(pstate: Dict[str, Any]) -> None:
    new_list: List[Dict[str, Any]] = []
    for idx, fr in enumerate(pstate.get("freelancers", []), start=1):
        in_mode = str(fr.get("입력기준", "세전")).strip()
        if in_mode == "세후역산" and int(fr.get("차인지급액", 0) or 0) > 0 and int(fr.get("지급총액", 0) or 0) == 0:
            calc = solve_gross_from_net_freelancer(int(fr["차인지급액"]))
        else:
            calc = calculate_freelancer_row(int(fr.get("지급총액", 0) or 0))
        fr["지급총액"] = calc["gross_pay"]
        fr["세율"] = 3
        fr["소득세"] = calc["income_tax"]
        fr["지방소득세"] = calc["local_tax"]
        fr["공제액계"] = calc["total_deduction"]
        fr["차인지급액"] = calc["net_pay"]
        if not fr.get("코드"):
            fr["코드"] = f"{idx:04d}"
        new_list.append(fr)
    pstate["freelancers"] = new_list


# ─────────────────────────────────────────────────────────────
# 별도 웹 팝업 모달 (@st.dialog) 5종 — 상하단 잘림 방지 설계
# ─────────────────────────────────────────────────────────────

@st.dialog("급여·원천세·근로기준법 개정사항 및 간이세액표 안내", width="large")
def _dlg_payroll_law_revisions():
    force_now = bool(st.session_state.pop("pay_force_law_refresh", False))
    alerts = check_payroll_law_revisions(force_refresh=force_now)

    st.markdown("<div class='pay-modal-scroll-box'>", unsafe_allow_html=True)
    c_hdr, c_btn = st.columns([4.2, 1.3], vertical_alignment="center")
    with c_hdr:
        checked_at = alerts[0].get("checked_at", "-") if alerts else "-"
        st.markdown(f"#### 1. 근로기준법 · 소득세법 · 시행령 별표2(간이세액표) 실시간 기준 현황 (확인일: `{checked_at}`)")
    with c_btn:
        if st.button("지금 다시 조회", width="stretch", key="btn_pay_law_refresh_now"):
            st.session_state["pay_force_law_refresh"] = True
            st.rerun()

    md_rows = [
        "| 법령 및 별표 구분 | 시행·적용 기준일 | 핵심 개정 및 적용 내용 | 상태 |",
        "| :--- | :---: | :--- | :---: |",
    ]
    for a in alerts:
        st_code = a.get("status", "current")
        if st_code == "new_revision":
            st_txt = "신규 개정 감지"
        elif st_code == "updated":
            st_txt = "개정 반영"
        else:
            st_txt = "현행 적용"
        disp_nm = a.get("display_name") or a.get("law", "")
        md_rows.append(
            f"| **{disp_nm}** | {a['effective_date']} | {a['summary']} | **{st_txt}** |"
        )
    st.markdown("\n".join(md_rows))

    st.markdown("#### 2. 2026년 4대보험 근로자·사업주 법정 요율 (법제처 원문 기준)")
    st.markdown(
        "| 보험 구분 | 2026년 근로자 부담율 | 2026년 사업주 부담율 | 법령 근거 (법제처 원문) |\n"
        "| :--- | :---: | :---: | :--- |\n"
        "| **국민연금** | **4.75%** (전체 9.5%) | **4.75%** | 국민연금법 부칙(법률 제20885호, 2025.4.2.) 제4조 제1항 제1호 |\n"
        "| **건강보험** | **3.595%** (전체 7.19%) | **3.595%** | 국민건강보험법 시행령 제44조 제1항 |\n"
        "| **장기요양보험** | **보수의 0.4724%** (건보료 × 0.9448/7.19) | **보수의 0.4724%** | 노인장기요양보험법 시행령 제4조 (보수월액 대비 100만분의 9,448) |\n"
        "| **고용보험(실업급여)** | **0.9%** (전체 1.8%) | **0.9%** + 고안직능(0.25%~0.85%) | 고용보험 및 산업재해보상보험의 보험료징수 등에 관한 법률 시행령 제12조 제1항 |"
    )

    st.markdown("#### 3. 소득세법 시행령 별표2 (근로소득 간이세액표) 개정 비교 (2024.03.01 vs 2026.03.01)")
    st.markdown(
        "- **월 급여액 구간별 기본 간이세액 (661개 구간 및 1,000만원 초과 산식)**: 동일 유지\n"
        "- **8세 이상 20세 이하 자녀세액공제 차감액 (별표2 제3호)**: **2026.03.01 이후 지급분부터 공제액 상향 (원천징수 세액 인하)**\n"
        "  - 자녀 1명: 월 **12,500원** (2024.03) → 월 **20,830원** (2026.03)\n"
        "  - 자녀 2명: 월 **29,160원** (2024.03) → 월 **45,830원** (2026.03)\n"
        "  - 자녀 3명 이상: 2명 공제액 + 2명 초과 1명당 월 **25,000원** (2024.03) → 월 **33,330원** (2026.03)"
    )
    st.markdown("</div>", unsafe_allow_html=True)
    if st.button("닫기", type="primary", width="stretch", key="btn_close_pay_law_dlg"):
        st.rerun()


@st.dialog("경고·주의사항 및 전월 대비 변동 점검", width="large")
def _dlg_payroll_warnings():
    pstate = _get_payroll_state()
    diag = analyze_payroll_warnings(
        employees=pstate.get("employees", []),
        freelancers=pstate.get("freelancers", []),
        prev_employees=pstate.get("prev_employees", []),
        prev_freelancers=pstate.get("prev_freelancers", []),
    )
    st.markdown("<div class='pay-modal-scroll-box'>", unsafe_allow_html=True)
    mv = diag["movement_summary"]
    c1, c2, c3 = st.columns(3)
    c1.metric("신규 입사 (취득신고 대상)", f"{len(mv['new_hires'])}명")
    c2.metric("퇴사·제외 (상실신고 대상)", f"{len(mv['retirees'])}명")
    c3.metric("급여 20% 이상 변동", f"{len(mv['pay_changes'])}명")

    if not diag["items"]:
        st.success("현재 급여대장 및 사업소득대장에서 감지된 경고·주의사항이 없습니다.")
    else:
        st.markdown(
            f"총 **{diag['total_count']}건** (경고 **{diag['danger_count']}건**, 주의 **{diag['warning_count']}건**)이 감지되었습니다."
        )
        rows_md = [
            "| 구분 | 분류 | 대상자 | 상세 점검 내용 | 관련 법령 근거 |",
            "| :---: | :--- | :---: | :--- | :--- |",
        ]
        for it in diag["items"]:
            rows_md.append(
                f"| **{it['level']}** | {it['category']} | **{it['target']}** | {it['message']} | {it['law']} |"
            )
        st.markdown("\n".join(rows_md))

    st.markdown("##### 관련 법령 및 점검 기준 주석")
    for ref in diag.get("legal_references", WARNING_MODAL_LEGAL_REFERENCES):
        ref_content = ref["content"].replace("\n", "<br>")
        st.markdown(
            f"<div class='pay-law-ref-box'><b>[{ref['title']}]</b><br>{ref_content}</div>",
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)
    if st.button("확인 및 닫기", type="primary", width="stretch", key="btn_close_warn_dlg"):
        st.rerun()


@st.dialog("연장·야간·휴일근로수당 계산기", width="large")
def _dlg_overtime_calculator():
    pstate = _get_payroll_state()
    emps = pstate.get("employees", [])
    emp_names = ["직접 입력"] + [str(e.get("성명", "")) for e in emps if e.get("성명")]

    st.markdown("<div class='pay-modal-scroll-box'>", unsafe_allow_html=True)
    col_sel, col_scale = st.columns([2, 2])
    with col_sel:
        selected_emp_name = st.selectbox("적용 대상 근로자 선택", options=emp_names, key="ot_calc_emp_sel")
    with col_scale:
        is_5_plus = st.radio(
            "상시근로자 수 기준 (사이드바 상시근로자 수와 자동 연동)",
            options=["5인 이상 (연장·휴일 1.5배 / 야간 0.5배)", "5인 미만 (가산율 미적용 · 1.0배)"],
            index=0 if pstate.get("is_5_or_more", True) else 1,
            horizontal=True,
            key="ot_calc_5plus_radio",
        )

    preset_hourly = 0
    preset_base = 2_200_000
    preset_hours = 209.0
    if selected_emp_name != "직접 입력":
        matched_e = next((e for e in emps if e.get("성명") == selected_emp_name), None)
        if matched_e:
            preset_hourly = int(matched_e.get("약정시급", 0) or 0)
            preset_base = int(matched_e.get("기본급", 0) or 0)
            preset_hours = float(matched_e.get("월근무시간", 209.0) or 209.0)

    c1, c2, c3 = st.columns(3)
    with c1:
        in_hourly = st.number_input("통상시급 (원, 0 입력 시 월급여로 자동계산)", min_value=0, value=preset_hourly, step=100, key="ot_in_hourly")
    with c2:
        in_base = st.number_input("월 통상임금/기본급 (원)", min_value=0, value=preset_base, step=10000, key="ot_in_base")
    with c3:
        in_mhours = st.number_input("월 소정근로시간 (시간)", min_value=1.0, value=float(preset_hours), step=1.0, key="ot_in_mhours")

    h1, h2, h3, h4 = st.columns(4)
    with h1:
        ot_h = st.number_input("연장근로시간 (시간)", min_value=0.0, value=0.0, step=0.5, key="ot_in_oth")
    with h2:
        night_h = st.number_input("야간근로시간 (22~06시)", min_value=0.0, value=0.0, step=0.5, key="ot_in_nighth")
    with h3:
        hol_le8 = st.number_input("휴일근로 (8시간 이내)", min_value=0.0, value=0.0, step=0.5, key="ot_in_hol8")
    with h4:
        hol_gt8 = st.number_input("휴일근로 (8시간 초과)", min_value=0.0, value=0.0, step=0.5, key="ot_in_holgt8")

    res = calculate_overtime_night_holiday_allowance(
        ordinary_hourly_wage=int(in_hourly),
        monthly_ordinary_wage=int(in_base),
        monthly_contract_hours=float(in_mhours),
        overtime_hours=float(ot_h),
        night_hours=float(night_h),
        holiday_hours_within_8=float(hol_le8),
        holiday_hours_over_8=float(hol_gt8),
        is_5_or_more_workers=is_5_plus.startswith("5인 이상"),
    )

    if res["below_min_wage"]:
        st.error(f"주의: 산출된 통상시급({res['hourly_wage']:,}원)이 최저시급({res['min_hourly_wage']:,}원)보다 낮습니다.")

    m1, m2, m3 = st.columns(3)
    m1.metric("연장+야간근로수당", f"{res['overtime_and_night_pay']:,}원")
    m2.metric("휴일근로수당", f"{res['holiday_pay']:,}원")
    m3.metric("총 가산수당 합계", f"{res['total_allowance']:,}원")

    formula_html = "<b>[산출 산식]</b><br>" + "<br>".join(f"• {line}" for line in res["formulas"])
    st.markdown(f"<div class='pay-formula-box'>{formula_html}</div>", unsafe_allow_html=True)

    for ref in res["legal_references"]:
        ref_content = ref["content"].replace("\n", "<br>")
        st.markdown(
            f"<div class='pay-law-ref-box'><b>[{ref['title']}]</b><br>{ref_content}</div>",
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)

    b1, b2 = st.columns(2)
    with b1:
        if selected_emp_name != "직접 입력":
            if st.button(f"[{selected_emp_name}] 급여대장에 수당 반영", type="primary", width="stretch", key="btn_apply_ot_to_emp"):
                for emp in pstate["employees"]:
                    if emp.get("성명") == selected_emp_name:
                        emp["약정시급"] = res["hourly_wage"]
                        emp["연장근무시간"] = float(ot_h)
                        emp["휴일근무시간"] = float(hol_le8 + hol_gt8)
                        emp["연장근로수당"] = res["overtime_and_night_pay"]
                        emp["휴일근로수당"] = res["holiday_pay"]
                _recalculate_all_employee_rows(pstate)
                pstate["grid_version"] += 1
                st.rerun()
    with b2:
        if st.button("닫기", width="stretch", key="btn_close_ot_dlg"):
            st.rerun()


@st.dialog("주휴수당 계산기", width="large")
def _dlg_weekly_holiday_calculator():
    pstate = _get_payroll_state()
    emps = pstate.get("employees", [])
    emp_names = ["직접 입력"] + [str(e.get("성명", "")) for e in emps if e.get("성명")]

    st.markdown("<div class='pay-modal-scroll-box'>", unsafe_allow_html=True)
    c_sel, c_att = st.columns([2, 2])
    with c_sel:
        selected_emp_name = st.selectbox("적용 대상 근로자 선택", options=emp_names, key="wh_calc_emp_sel")
    with c_att:
        full_att = st.checkbox("소정근로일 개근 충족", value=True, key="wh_calc_full_att")

    c1, c2 = st.columns(2)
    with c1:
        hr_wage = st.number_input("약정 시급 (원)", min_value=0, value=10320, step=100, key="wh_in_hourly")
    with c2:
        wk_hours = st.number_input("1주 소정근로시간 (시간)", min_value=0.0, max_value=52.0, value=40.0, step=1.0, key="wh_in_wkhours")

    res = calculate_weekly_holiday_allowance(
        hourly_wage=int(hr_wage),
        weekly_contract_hours=float(wk_hours),
        full_attendance=bool(full_att),
    )

    if res["below_min_wage"]:
        st.error(f"주의: 입력 시급({res['hourly_wage']:,}원)이 최저시급({res['min_hourly_wage']:,}원)에 미달합니다.")

    k1, k2, k3 = st.columns(3)
    k1.metric("1주 주휴수당 (주휴시간)", f"{res['weekly_holiday_pay']:,}원 ({res['weekly_holiday_hours']:g}h)")
    k2.metric("월 환산 주휴수당 (4.345주)", f"{res['monthly_holiday_pay']:,}원")
    k3.metric("월 예상 기본급 (주휴 포함)", f"{res['monthly_total_pay']:,}원")

    formula_html = "<b>[산출 산식]</b><br>" + "<br>".join(f"• {line}" for line in res["formulas"])
    st.markdown(f"<div class='pay-formula-box'>{formula_html}</div>", unsafe_allow_html=True)

    for ref in res["legal_references"]:
        ref_content = ref["content"].replace("\n", "<br>")
        st.markdown(
            f"<div class='pay-law-ref-box'><b>[{ref['title']}]</b><br>{ref_content}</div>",
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)

    b1, b2 = st.columns(2)
    with b1:
        if selected_emp_name != "직접 입력":
            if st.button(f"[{selected_emp_name}] 기본급에 월 예상 기본급 반영", type="primary", width="stretch", key="btn_apply_wh_to_emp"):
                for emp in pstate["employees"]:
                    if emp.get("성명") == selected_emp_name:
                        emp["약정시급"] = int(hr_wage)
                        emp["주근무시간"] = float(wk_hours)
                        emp["월근무시간"] = float(res["monthly_total_hours"])
                        emp["기본급"] = int(res["monthly_total_pay"])
                _recalculate_all_employee_rows(pstate)
                pstate["grid_version"] += 1
                st.rerun()
    with b2:
        if st.button("닫기", width="stretch", key="btn_close_wh_dlg"):
            st.rerun()


@st.dialog("당월 인건비 종합 검토보고서", width="large")
def _dlg_monthly_review_report():
    pstate = _get_payroll_state()
    emps = pstate.get("employees", [])
    frees = pstate.get("freelancers", [])
    corp = pstate.get("corp_name") or "미입력"
    ym = pstate.get("year_month") or datetime.now().strftime("%Y-%m")
    pay_dt = pstate.get("pay_date") or ""

    diag = analyze_payroll_warnings(
        employees=emps,
        freelancers=frees,
        prev_employees=pstate.get("prev_employees", []),
        prev_freelancers=pstate.get("prev_freelancers", []),
    )

    tot_emp_gross = sum(int(e.get("지급액계", 0) or 0) for e in emps)
    tot_emp_net = sum(int(e.get("차인지급액", 0) or 0) for e in emps)
    tot_emp_itax = sum(int(e.get("소득세", 0) or 0) for e in emps)
    tot_emp_ltax = sum(int(e.get("지방소득세", 0) or 0) for e in emps)
    tot_emp_ins = sum(
        int(e.get("국민연금", 0) or 0)
        + int(e.get("건강보험", 0) or 0)
        + int(e.get("장기요양보험료", 0) or 0)
        + int(e.get("고용보험", 0) or 0)
        + int(e.get("건강보험료정산", 0) or 0)
        + int(e.get("장기요양보험료정산", 0) or 0)
        + int(e.get("국민연금정산", 0) or 0)
        for e in emps
    )

    tot_free_gross = sum(int(f.get("지급총액", 0) or 0) for f in frees)
    tot_free_tax = sum(int(f.get("공제액계", 0) or 0) for f in frees)
    tot_free_net = sum(int(f.get("차인지급액", 0) or 0) for f in frees)

    st.markdown("<div class='pay-modal-scroll-box'>", unsafe_allow_html=True)
    st.markdown(f"#### [{corp}] {ym} 귀속 인건비 및 원천징수 검토 요약 (지급일: {pay_dt})")

    summary_md = "\n".join([
        "| 구분 | 대상 인원 | 세전 지급총액 | 4대보험 공제계 | 소득세+지방소득세 | 차인지급액(실지급액) |",
        "| :--- | :---: | ---: | ---: | ---: | ---: |",
        f"| **4대보험 근로소득자** | {len(emps)}명 | {tot_emp_gross:,}원 | {tot_emp_ins:,}원 | {tot_emp_itax + tot_emp_ltax:,}원 | **{tot_emp_net:,}원** |",
        f"| **3.3% 사업소득자** | {len(frees)}명 | {tot_free_gross:,}원 | 해당없음 | {tot_free_tax:,}원 | **{tot_free_net:,}원** |",
        f"| **당월 인건비 총계** | **{len(emps) + len(frees)}명** | **{tot_emp_gross + tot_free_gross:,}원** | **{tot_emp_ins:,}원** | **{tot_emp_itax + tot_emp_ltax + tot_free_tax:,}원** | **{tot_emp_net + tot_free_net:,}원** |",
    ])
    st.markdown(summary_md)

    # 사업주 부담 4대보험 추정 (산재보험 제외)
    if emps:
        tier_map = dict(EI_STABILITY_TIERS)
        tier_lbl = pstate.get("ei_stability_tier") or EI_STABILITY_TIERS[0][0]
        tier_rate = tier_map.get(tier_lbl, EI_STABILITY_TIERS[0][1])
        yr_i = int(str(ym)[:4]) if str(ym)[:4].isdigit() else 2026
        own = {"국민연금_사업주": 0, "건강보험_사업주": 0, "장기요양_사업주": 0, "고용보험_사업주": 0, "합계_사업주": 0}
        for e in emps:
            r_own = calc_4ins_employer_share(
                int(e.get("과세급여", 0) or 0),
                worker_ins={k: int(e.get(k, 0) or 0) for k in ("국민연금", "건강보험", "장기요양보험료", "고용보험")},
                year=yr_i,
                is_ceo=is_ceo_position(e.get("직급", "")),
                ei_stability_rate=tier_rate,
            )
            for k in own:
                own[k] += int(r_own.get(k, 0) or 0)
        st.markdown("#### 사업주 부담 4대보험 추정 (산재보험 제외)")
        st.markdown("\n".join([
            "| 국민연금(사업주) | 건강보험(사업주) | 장기요양(사업주) | 고용보험(사업주) | 사업주 부담 합계 |",
            "| ---: | ---: | ---: | ---: | ---: |",
            f"| {own['국민연금_사업주']:,}원 | {own['건강보험_사업주']:,}원 | {own['장기요양_사업주']:,}원 | {own['고용보험_사업주']:,}원 | **{own['합계_사업주']:,}원** |",
        ]))
        st.caption(
            f"국민연금·건강·장기요양은 근로자 부담분(고지 금액이 있으면 고지 금액)과 같은 금액입니다. "
            f"고용보험은 과세급여 × (실업급여 0.9% + 고용안정·직능 {tier_lbl.split('·')[-1].strip()})로 추정했습니다 (대표이사 및 근로자 고용보험 0원 대상자는 제외). "
            f"정산분은 포함하지 않았습니다."
        )

    mv = diag["movement_summary"]
    st.markdown("#### 전월 대비 인원 변동 및 4대보험 신고 대상")
    st.markdown(
        f"- **신규 입사 (4대보험 취득신고 대상)**: {', '.join(mv['new_hires']) if mv['new_hires'] else '해당 없음'}\n"
        f"- **퇴사·제외 (4대보험 상실신고 대상)**: {', '.join(mv['retirees']) if mv['retirees'] else '해당 없음'}\n"
        f"- **급여 20% 이상 변동자**: {', '.join(mv['pay_changes']) if mv['pay_changes'] else '해당 없음'}"
    )

    if diag["items"]:
        st.markdown("#### 주요 점검 사항")
        for it in diag["items"]:
            st.markdown(f"- **[{it['level']} · {it['category']}] {it['target']}**: {it['message']}")

    st.markdown("#### 관련 법령 및 원천징수·4대보험 산출 기준 주석")
    for ref in MONTHLY_REPORT_LEGAL_REFERENCES:
        ref_content = ref["content"].replace("\n", "<br>")
        st.markdown(
            f"<div class='pay-law-ref-box'><b>[{ref['title']}]</b><br>{ref_content}</div>",
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)

    if st.button("닫기", type="primary", width="stretch", key="btn_close_monthly_rep_dlg"):
        st.rerun()


# ─────────────────────────────────────────────────────────────
# 좌측 사이드바 렌더링 (인건비 자동화 모드)
# ─────────────────────────────────────────────────────────────

def render_payroll_automated_sidebar() -> None:
    st.markdown(PAYROLL_CSS, unsafe_allow_html=True)
    pstate = _get_payroll_state()

    # (1) 최상단: 개정사항 모니터링 카드 (통합고용세액공제와 동일한 스타일 + 법제처 API 연동)
    alerts = check_payroll_law_revisions(force_refresh=False)
    has_new_rev = any(a.get("status") == "new_revision" for a in alerts)
    has_updated = any(a.get("status") in ("updated", "new_revision") for a in alerts)
    led_cls = "pay-dot-red" if has_new_rev else ("pay-dot-yellow" if has_updated else "pay-dot-green")
    badge_html = (
        "<span class='pay-law-badge-amber'>신규 개정 감지</span>"
        if has_new_rev
        else (
            "<span class='pay-law-badge-amber'>2026.03 별표2·요율 반영</span>"
            if has_updated
            else "<span class='pay-law-badge-green'>현행 일치</span>"
        )
    )

    with st.container(border=True):
        st.markdown(
            "<div class='sb-card-title'><span>개정사항 모니터링</span></div>"
            f"<div class='pay-law-row'>"
            f"<span><span class='pay-dot {led_cls}'></span>근로기준법 · 소득세법</span>"
            f"<span class='pay-law-badge-green'>정상</span>"
            f"</div>"
            f"<div class='pay-law-row' style='margin-bottom:8px;'>"
            f"<span><span class='pay-dot {led_cls}'></span>시행령 별표2 · 4대보험 요율</span>"
            f"{badge_html}"
            f"</div>",
            unsafe_allow_html=True,
        )
        if st.button("상세 보기", width="stretch", key="btn_pay_law_detail"):
            _dlg_payroll_law_revisions()

    # (2) 작업 초기화 버튼 카드 (통합고용세액공제 UI와 동일)
    emp_cnt = len(pstate.get("employees", []))
    free_cnt = len(pstate.get("freelancers", []))
    has_data = (
        (emp_cnt + free_cnt) > 0
        or bool(pstate.get("corp_name"))
        or pstate.get("ei_emp_count_manual") is not None
        or pstate.get("ei_stability_tier_manual") is not None
    )

    with st.container(border=True):
        status_pill = (
            f"<span class='sb-badge-green'>근로 {emp_cnt}명 · 사업 {free_cnt}명</span>"
            if (emp_cnt + free_cnt) > 0
            else "<span class='sb-badge-amber'>초기 상태</span>"
        )
        st.markdown(
            f"<div class='sb-card-title'><span>작업 자료 관리</span>{status_pill}</div>",
            unsafe_allow_html=True,
        )
        if not st.session_state.get("pay_confirm_reset"):
            if st.button(
                "작업 초기화 (내용 비우기)",
                width="stretch",
                disabled=not has_data,
                key="btn_pay_reset_ask",
            ):
                st.session_state["pay_confirm_reset"] = True
                st.rerun()
        else:
            st.caption("현재 화면의 급여대장·사업소득대장 입력 내용을 비울까요? (백업 DB는 유지됩니다)")
            c_y, c_n = st.columns(2)
            if c_y.button("초기화 실행", type="primary", width="stretch", key="btn_pay_reset_yes"):
                _reset_payroll_current_work()
                st.session_state["pay_confirm_reset"] = False
                st.rerun()
            if c_n.button("취소", width="stretch", key="btn_pay_reset_no"):
                st.session_state["pay_confirm_reset"] = False
                st.rerun()

    # (3) 좌·우 3D 버튼: [급여명세서] (파스텔 블루) / [사업소득] (파스텔 퍼플)
    with st.container(border=True):
        st.markdown("<div class='sb-card-title'><span>업무 화면 선택</span></div>", unsafe_allow_html=True)
        col_emp, col_free = st.columns(2, gap="small")
        is_emp_mode = pstate.get("sub_mode", "EMP") == "EMP"
        with col_emp:
            emp_key = "btn_pay_submode_emp_active" if is_emp_mode else "btn_pay_submode_emp"
            if st.button("급여명세서", key=emp_key, width="stretch"):
                pstate["sub_mode"] = "EMP"
                st.rerun()
        with col_free:
            free_key = "btn_pay_submode_free_active" if not is_emp_mode else "btn_pay_submode_free"
            if st.button("사업소득", key=free_key, width="stretch"):
                pstate["sub_mode"] = "FREE"
                st.rerun()

    # (4) 사업자정보 카드 (거래처명, 귀속연월, 지급일자, 상시근로자 수 통합 입력, 사업주 고용보험 요율, [당월 검토보고], [통합고용세액공제 계산])
    with st.container(border=True):
        st.markdown("<div class='sb-card-title'><span>사업자정보</span></div>", unsafe_allow_html=True)
        corp_val = st.text_input(
            "거래처명",
            value=pstate.get("corp_name", ""),
            placeholder="예: 주식회사 한빛테크",
            key="pay_sb_corp_name",
        )
        pstate["corp_name"] = corp_val.strip()

        ym_options = [
            f"{yr:04d}-{mo:02d}"
            for yr in (2024, 2025, 2026, 2027)
            for mo in range(1, 13)
        ]
        curr_ym = pstate.get("year_month", "2026-10")
        if curr_ym not in ym_options:
            ym_options.append(curr_ym)
            ym_options.sort()

        c_ym, c_pdt = st.columns(2)
        with c_ym:
            sel_ym = st.selectbox(
                "귀속연월",
                options=ym_options,
                index=ym_options.index(curr_ym),
                key="pay_sb_year_month",
            )
            if sel_ym != pstate.get("year_month"):
                pstate["year_month"] = sel_ym
                pstate["pay_date"] = f"{sel_ym}-25"
                pstate["effective_table"] = "2026.03" if sel_ym >= "2026-03" else "2024.03"
                _recalculate_all_employee_rows(pstate)
        with c_pdt:
            pay_dt_val = st.text_input(
                "지급일자",
                value=pstate.get("pay_date", f"{sel_ym}-25"),
                placeholder="YYYY-MM-DD",
                key="pay_sb_pay_date",
            )
            pstate["pay_date"] = pay_dt_val.strip()

        active_workers = sum(
            1 for e in pstate.get("employees", [])
            if str(e.get("성명", "")).strip() and not str(e.get("퇴사일", "")).strip()
        )
        total_workers = len(pstate.get("employees", []))

        # 상시근로자 수 통합 입력칸 (기본값은 급여대장 인원을 따라가며, 직접 수정 시 5인 이상/미만 가산수당 및 고용보험 구간에 동시 반영)
        manual_cnt = pstate.get("ei_emp_count_manual")
        default_cnt_val = int(manual_cnt) if manual_cnt is not None else int(total_workers)
        ei_cnt = int(
            st.number_input(
                "상시근로자 수 (전 사업장 합산 · 수정 가능)",
                min_value=0,
                value=default_cnt_val,
                step=1,
                key=f"pay_sb_ei_emp_count_{total_workers}_{pstate.get('grid_version', 0)}",
                help="기본값은 급여대장 인원입니다. 타 지점 합산 등으로 직접 숫자를 수정하면 연장·야간·휴일 가산수당(5인 이상 1.5배) 및 고용보험 요율 구간에 즉시 반영됩니다.",
            )
        )
        pstate["ei_emp_count_manual"] = ei_cnt if ei_cnt != int(total_workers) else None
        pstate["ei_emp_count"] = ei_cnt

        # 수정사항 ① 반영: 사용자가 사이드바에서 입력/수정한 상시근로자 수(ei_cnt)를 기준으로 5인 이상/미만 가산수당 판정 연동
        pstate["is_5_or_more"] = ei_cnt >= 5
        scale_label = "5인 이상 (가산수당 1.5배)" if pstate["is_5_or_more"] else "5인 미만 (가산수당 1.0배 특례)"

        st.markdown(
            f"<div style='background:#f8fafc; border:1px solid #e2e8f0; border-radius:6px; padding:5px 9px; margin-top:-4px; margin-bottom:6px; font-size:0.78rem; color:#334155;'>"
            f"대장 인원: <b>{total_workers}명</b>(재직 {active_workers}명) · 수당 기준: <b>{scale_label}</b>"
            f"</div>",
            unsafe_allow_html=True,
        )

        # 사업주 고용보험 (고용안정·직능) 요율 선택
        tier_labels = [t[0] for t in EI_STABILITY_TIERS]
        auto_tier = tier_labels[0] if ei_cnt < 150 else tier_labels[1]
        manual_tier = pstate.get("ei_stability_tier_manual")
        cur_tier = manual_tier if manual_tier in tier_labels else auto_tier
        sel_tier = st.selectbox(
            "사업주 고용보험 (고용안정·직능) 요율",
            options=tier_labels,
            index=tier_labels.index(cur_tier),
            key=f"pay_sb_ei_tier_{'150up' if ei_cnt >= 150 else 'under150'}_{pstate.get('grid_version', 0)}",
            help=(
                "150명 미만은 0.25%입니다. 150명 이상이면 우선지원대상기업 여부에 따라 0.45% / 0.65% / 0.85% 중 선택하세요. "
                "인원 증가로 요율이 오른 경우 3년간 종전 요율을 적용합니다 (시행령 제12조 제4항)."
            ),
        )
        pstate["ei_stability_tier_manual"] = sel_tier if sel_tier != auto_tier else None
        pstate["ei_stability_tier"] = sel_tier

        if ei_cnt >= 150 and sel_tier == tier_labels[1] and manual_tier is None:
            st.caption("[안내] 150명 이상이므로 우선지원대상기업(0.45%)이 기본 선택되었습니다. 우선지원대상이 아니면 0.65% 또는 0.85%로 변경하세요.")
        if ei_cnt >= 150 and sel_tier == tier_labels[0]:
            st.caption("[확인] 상시근로자 150명 이상인데 0.25% 구간이 선택되어 있습니다. 3년 종전 요율 유지 특례 대상인지 확인하세요.")
        elif ei_cnt < 150 and sel_tier != tier_labels[0]:
            st.caption("[확인] 상시근로자 150명 미만은 원칙적으로 0.25% 구간입니다. 선택한 구간을 확인하세요.")

        if st.button("당월 검토보고", width="stretch", key="btn_pay_monthly_report"):
            _dlg_monthly_review_report()

        if st.button("통합고용세액공제 계산 연동", width="stretch", key="btn_pay_bridge_credit"):
            pstate["client_db"] = upsert_monthly_data_into_db(
                client_db=pstate.get("client_db", {}),
                corp_name=pstate.get("corp_name", ""),
                year_month=pstate.get("year_month", ""),
                pay_date=pstate.get("pay_date", ""),
                employees=pstate.get("employees", []),
                freelancers=pstate.get("freelancers", []),
                is_5_or_more=pstate.get("is_5_or_more", True),
                ei_emp_count_manual=pstate.get("ei_emp_count_manual"),
                ei_stability_tier_manual=pstate.get("ei_stability_tier_manual"),
            )
            bridge_payload, msg = build_employment_credit_bridge_payload(
                client_db=pstate["client_db"],
                current_corp_name=pstate.get("corp_name", ""),
                current_year_month=pstate.get("year_month", ""),
                current_employees=pstate.get("employees", []),
            )
            st.session_state["payroll_to_ec_bridge"] = bridge_payload
            st.session_state["payroll_bridge_notice"] = msg
            st.session_state.app_top_mode = "CREDIT_CALC"
            st.rerun()

    # (5) 거래처별 월별 누적 작업 백업 (.paybak) 카드
    with st.container(border=True):
        saved_months = sorted((pstate.get("client_db") or {}).get("monthly_payroll", {}).keys())
        m_badge = (
            f"<span class='sb-badge-green'>누적 {len(saved_months)}개월</span>"
            if saved_months
            else "<span class='sb-badge-amber'>미저장</span>"
        )
        st.markdown(f"<div class='sb-card-title'><span>작업 백업 (월별 누적 DB)</span>{m_badge}</div>", unsafe_allow_html=True)
        if saved_months:
            st.caption(f"누적 귀속월: {', '.join(saved_months)}")
        else:
            st.caption("하나의 백업 파일(.paybak)에 매월 급여·사업소득 내역을 누적 저장하고 다음 달에 이어서 작업합니다.")

        tab_save, tab_load = st.tabs(["내려받기", "불러오기"])
        with tab_save:
            bk_pw = st.text_input("백업 암호 (선택)", type="password", key="pay_bk_pw_save", placeholder="미입력 시 기본 보안키 적용")
            if st.button("당월 내역 누적 및 백업 생성", width="stretch", key="btn_pay_make_bak"):
                pstate["client_db"] = upsert_monthly_data_into_db(
                    client_db=pstate.get("client_db", {}),
                    corp_name=pstate.get("corp_name", ""),
                    year_month=pstate.get("year_month", ""),
                    pay_date=pstate.get("pay_date", ""),
                    employees=pstate.get("employees", []),
                    freelancers=pstate.get("freelancers", []),
                    is_5_or_more=pstate.get("is_5_or_more", True),
                    ei_emp_count_manual=pstate.get("ei_emp_count_manual"),
                    ei_stability_tier_manual=pstate.get("ei_stability_tier_manual"),
                )
                bak_bytes = encrypt_client_db_to_paybak(pstate["client_db"], password=bk_pw)
                c_nm = pstate.get("corp_name") or "거래처"
                st.session_state["pay_bak_ready"] = (bak_bytes, f"{c_nm}_인건비누적DB.paybak")
            ready_bak = st.session_state.get("pay_bak_ready")
            if ready_bak:
                st.download_button(
                    "백업 파일(.paybak) 다운로드",
                    data=ready_bak[0],
                    file_name=ready_bak[1],
                    mime="application/octet-stream",
                    width="stretch",
                    key="btn_pay_dl_bak",
                )
        with tab_load:
            up_bak = st.file_uploader("누적 백업 파일 (.paybak)", type=["paybak", "json"], key="pay_bk_file_up")
            in_pw = st.text_input("백업 암호", type="password", key="pay_bk_pw_load")
            if up_bak is not None and st.button("백업 DB 불러오기", width="stretch", key="btn_pay_load_bak"):
                try:
                    loaded_db = decrypt_paybak_to_client_db(up_bak.getvalue(), password=in_pw)
                    pstate["client_db"] = loaded_db
                    c_info = loaded_db.get("corp_info", {})
                    if c_info.get("corp_name"):
                        pstate["corp_name"] = c_info["corp_name"]
                    pstate["ei_emp_count_manual"] = c_info.get("ei_emp_count_manual")
                    pstate["ei_stability_tier_manual"] = c_info.get("ei_stability_tier_manual")
                    m_map = loaded_db.get("monthly_payroll", {})
                    if m_map:
                        latest_ym = sorted(m_map.keys())[-1]
                        latest_pack = m_map[latest_ym]
                        pstate["year_month"] = latest_ym
                        pstate["pay_date"] = latest_pack.get("pay_date", f"{latest_ym}-25")
                        pstate["employees"] = list(latest_pack.get("employees", []))
                        pstate["freelancers"] = list(latest_pack.get("freelancers", []))
                        pstate["grid_version"] += 1
                    st.success(f"누적 백업 로드 완료 (총 {len(m_map)}개월분)")
                    st.rerun()
                except Exception as e:
                    st.error(str(e))


# ─────────────────────────────────────────────────────────────
# 우측 메인 화면 렌더링
# ─────────────────────────────────────────────────────────────

EMP_GRID_COLUMNS: List[Tuple[str, str, int, bool, str]] = [
    ("사원코드", "사원코드", 82, True, "text"),
    ("성명", "성명", 95, True, "text"),
    ("주민등록번호", "주민등록번호", 138, True, "text"),
    ("입사일", "입사일", 105, True, "text"),
    ("퇴사일", "퇴사일", 105, True, "text"),
    ("직급", "직급", 90, True, "text"),
    ("부양가족수", "부양가족", 82, True, "numeric"),
    ("자녀수", "8~20세자녀", 92, True, "numeric"),
    ("입력기준", "입력기준", 92, True, "select_mode"),
    ("목표실수령액", "목표실수령(역산용)", 135, True, "numeric"),
    ("기본급", "기본급", 115, True, "numeric"),
    ("식대", "식대(비과세)", 110, True, "numeric"),
    ("자가운전보조금", "자가운전", 100, True, "numeric"),
    ("상여", "상여", 100, True, "numeric"),
    ("약정연장근로수당", "약정연장수당", 115, True, "numeric"),
    ("약정휴일근로수당", "약정휴일수당", 115, True, "numeric"),
    ("연장근로수당", "연장근로수당", 115, True, "numeric"),
    ("휴일근로수당", "휴일근로수당", 115, True, "numeric"),
    ("미사용연차수당", "미사용연차", 105, True, "numeric"),
    ("결근공제", "결근공제", 100, True, "numeric"),
    ("조정금액", "조정금액", 100, True, "numeric"),
    ("지급액계", "지급액계(세전)", 125, False, "numeric_total"),
    ("보험적용구분", "4대보험기준", 108, True, "select_ins"),
    ("국민연금", "국민연금", 105, True, "numeric"),
    ("건강보험", "건강보험", 105, True, "numeric"),
    ("장기요양보험료", "장기요양", 100, True, "numeric"),
    ("고용보험", "고용보험", 100, True, "numeric"),
    ("건강보험료정산", "건강정산", 100, True, "numeric"),
    ("장기요양보험료정산", "요양정산", 100, True, "numeric"),
    ("국민연금정산", "연금정산", 100, True, "numeric"),
    ("학자금상환액", "학자금상환", 100, True, "numeric"),
    ("소득세", "소득세", 100, True, "numeric"),
    ("지방소득세", "지방소득세", 100, True, "numeric"),
    ("공제액계", "공제액계", 115, False, "numeric_total"),
    ("차인지급액", "차인지급액(실지급)", 135, False, "numeric_net"),
]

FREE_GRID_COLUMNS: List[Tuple[str, str, int, bool, str]] = [
    ("코드", "코드", 85, True, "text"),
    ("성명", "소득자명(성명)", 110, True, "text"),
    ("주민등록번호", "주민등록번호", 145, True, "text"),
    ("소득구분", "업종코드", 100, True, "text"),
    ("귀속년월", "귀속년월", 105, True, "text"),
    ("지급년월일", "지급년월일", 115, True, "text"),
    ("입력기준", "입력기준", 98, True, "select_mode"),
    ("지급총액", "지급총액(세전)", 135, True, "numeric"),
    ("세율", "세율(%)", 85, False, "numeric"),
    ("소득세", "소득세(3%)", 120, False, "numeric"),
    ("지방소득세", "지방소득세(0.3%)", 125, False, "numeric"),
    ("공제액계", "공제액계(3.3%)", 125, False, "numeric_total"),
    ("차인지급액", "차인지급액(실지급)", 140, True, "numeric_net"),
]


def _process_uploaded_files_and_text(
    pstate: Dict[str, Any],
    uploaded_files: List[Any],
    chat_text: str = "",
    gemini_api_key: Optional[str] = None,
) -> None:
    eff_tbl = pstate.get("effective_table", "2026.03")
    notice_list: List[Dict[str, Any]] = []

    for f_obj in uploaded_files or []:
        fname = getattr(f_obj, "name", "") or ""
        fbytes = f_obj.getvalue() if hasattr(f_obj, "getvalue") else f_obj.read()
        lower_nm = fname.lower()

        if lower_nm.endswith((".xlsx", ".xls")):
            if "사업소득" in fname or "프리랜서" in fname or pstate.get("sub_mode") == "FREE":
                parsed_fr = parse_freelancer_excel(
                    fbytes,
                    filename=fname,
                    default_year_month=pstate.get("year_month", ""),
                    default_pay_date=pstate.get("pay_date", ""),
                )
                if parsed_fr:
                    pstate["freelancers"] = parsed_fr
                    pstate["sub_mode"] = "FREE"
                    pstate["chat_logs"].append(f"[엑셀 로드] '{fname}'에서 사업소득자 {len(parsed_fr)}명을 불러왔습니다.")
                    continue

            res_ex = parse_client_payroll_excel(
                fbytes,
                filename=fname,
                effective_table=eff_tbl,
                gemini_api_key=gemini_api_key,
            )
            if res_ex["employees"]:
                if pstate.get("employees") and not pstate.get("prev_employees"):
                    pstate["prev_employees"] = list(pstate["employees"])
                pstate["employees"] = res_ex["employees"]
                # 새 급여 엑셀이 업로드되면 상시근로자 수 입력칸이 새 인원수를 자동 추적하도록 수기 고정값 해제
                pstate["ei_emp_count_manual"] = None
                if res_ex["meta"].get("year_month"):
                    pstate["year_month"] = res_ex["meta"]["year_month"]
                    pstate["pay_date"] = f"{res_ex['meta']['year_month']}-25"
                pstate["chat_logs"].append(
                    f"[급여 엑셀 로드] '{fname}'에서 근로자 {len(res_ex['employees'])}명 급여 내역을 추출했습니다."
                )
            for w_msg in res_ex.get("warnings", []):
                pstate["chat_logs"].append(f"[안내] {w_msg}")

        elif lower_nm.endswith(".pdf"):
            notice_res = parse_insurance_notice_pdf(fbytes, filename=fname)
            if notice_res.get("notice_type") != "unknown":
                notice_list.append(notice_res)
                if notice_res.get("corp_name") and not pstate.get("corp_name"):
                    pstate["corp_name"] = notice_res["corp_name"]
                pstate["chat_logs"].append(f"[고지내역 PDF] {notice_res.get('message')}")
            else:
                pstate["chat_logs"].append(notice_res.get("message", f"PDF 확인 필요: {fname}"))

        elif lower_nm.endswith((".png", ".jpg", ".jpeg", ".webp")):
            mime = "image/png" if lower_nm.endswith(".png") else "image/jpeg"
            vis_res = parse_image_with_gemini_vision(
                fbytes, mime_type=mime, gemini_api_key=gemini_api_key
            )
            if vis_res.get("type") == "ei_notice":
                notice_list.append(vis_res["notice"])
                pstate["chat_logs"].append(f"[고용보험 이미지] {vis_res['notice'].get('message')}")
            elif vis_res.get("type") == "kakao_text":
                chat_text = (chat_text + "\n" + vis_res.get("extracted_text", "")).strip()
            else:
                pstate["chat_logs"].append(vis_res.get("message", f"이미지 처리 안내: {fname}"))

        elif lower_nm.endswith(".paybak"):
            try:
                loaded_db = decrypt_paybak_to_client_db(fbytes)
                pstate["client_db"] = loaded_db
                c_info = loaded_db.get("corp_info", {})
                pstate["ei_emp_count_manual"] = c_info.get("ei_emp_count_manual")
                pstate["ei_stability_tier_manual"] = c_info.get("ei_stability_tier_manual")
                pstate["chat_logs"].append(f"[백업 로드] '{fname}' 누적 백업 DB를 복원했습니다.")
            except Exception as e:
                pstate["chat_logs"].append(f"[백업 오류] {e}")

    if notice_list and pstate.get("employees"):
        updated_emps, n_logs = apply_insurance_notices_to_employees(
            pstate["employees"],
            notice_list,
            effective_table=eff_tbl,
        )
        pstate["employees"] = updated_emps
        pstate["notice_logs"].extend(n_logs)
        pstate["chat_logs"].extend(n_logs)

    if chat_text and chat_text.strip():
        kakao_res = parse_kakao_text_instructions(
            raw_text=chat_text,
            existing_employees=pstate.get("employees", []),
            existing_freelancers=pstate.get("freelancers", []),
            default_year_month=pstate.get("year_month", ""),
            default_pay_date=pstate.get("pay_date", ""),
            effective_table=eff_tbl,
        )
        if kakao_res["employees"]:
            by_nm = {e["성명"]: idx for idx, e in enumerate(pstate["employees"])}
            for new_e in kakao_res["employees"]:
                if new_e["성명"] in by_nm:
                    pstate["employees"][by_nm[new_e["성명"]]].update(new_e)
                else:
                    new_e["사원코드"] = f"{len(pstate['employees']) + 1:03d}"
                    pstate["employees"].append(new_e)
        if kakao_res["freelancers"]:
            by_fnm = {f["성명"]: idx for idx, f in enumerate(pstate["freelancers"])}
            for new_f in kakao_res["freelancers"]:
                if new_f["성명"] in by_fnm:
                    pstate["freelancers"][by_fnm[new_f["성명"]]].update(new_f)
                else:
                    new_f["코드"] = f"{len(pstate['freelancers']) + 1:04d}"
                    pstate["freelancers"].append(new_f)
            if not kakao_res["employees"]:
                pstate["sub_mode"] = "FREE"
        pstate["chat_logs"].extend(kakao_res["messages"])

    pstate["grid_version"] = int(pstate.get("grid_version", 0)) + 1


def _render_employee_aggrid(pstate: Dict[str, Any]) -> None:
    emps = pstate.get("employees", [])
    col_keys = [c[0] for c in EMP_GRID_COLUMNS]

    if not emps:
        df = pd.DataFrame(columns=col_keys)
    else:
        rows_norm = []
        for idx, e in enumerate(emps, start=1):
            r = {}
            for k, _, _, _, ctype in EMP_GRID_COLUMNS:
                if k == "사원코드":
                    r[k] = str(e.get(k) or f"{idx:03d}")
                elif ctype.startswith("numeric"):
                    r[k] = int(e.get(k, 0) or 0)
                else:
                    r[k] = str(e.get(k, "") or "")
            rows_norm.append(r)
        df = pd.DataFrame(rows_norm, columns=col_keys)

    gb = GridOptionsBuilder.from_dataframe(df)
    gb.configure_default_column(resizable=True, sortable=True, filter=False)

    for field, header_name, width, editable, ctype in EMP_GRID_COLUMNS:
        pinned = "left" if field in ("사원코드", "성명") else None
        if ctype == "select_mode":
            gb.configure_column(
                field,
                header_name=header_name,
                width=width,
                editable=editable,
                cellEditor="agSelectCellEditor",
                cellEditorParams={"values": ["세전", "세후역산"]},
            )
        elif ctype == "select_ins":
            gb.configure_column(
                field,
                header_name=header_name,
                width=width,
                editable=editable,
                cellEditor="agSelectCellEditor",
                cellEditorParams={"values": ["고지(1순위)", "요율(2순위)"]},
            )
        elif ctype.startswith("numeric"):
            cell_style = {"textAlign": "right"}
            if ctype == "numeric_total":
                cell_style = {"textAlign": "right", "fontWeight": "bold", "backgroundColor": "#f8fafc"}
            elif ctype == "numeric_net":
                cell_style = {"textAlign": "right", "fontWeight": "bold", "backgroundColor": "#eff6ff", "color": "#1e3a8a"}
            gb.configure_column(
                field,
                header_name=header_name,
                width=width,
                editable=editable,
                type=["numericColumn", "numberColumnFilter"],
                valueFormatter="x != null ? Number(x).toLocaleString() : '0'",
                cellStyle=cell_style,
            )
        else:
            gb.configure_column(
                field,
                header_name=header_name,
                width=width,
                editable=editable,
                pinned=pinned,
            )

    grid_opts = gb.build()
    grid_height = min(520, max(220, 56 + len(df) * 36))

    grid_resp = AgGrid(
        df,
        gridOptions=grid_opts,
        height=grid_height,
        update_mode=GridUpdateMode.VALUE_CHANGED,
        allow_unsafe_jscode=True,
        theme="streamlit",
        key=f"pay_emp_aggrid_{pstate.get('grid_version', 0)}",
    )

    updated_df = grid_resp.get("data")
    if updated_df is not None and isinstance(updated_df, pd.DataFrame) and not updated_df.empty:
        new_emps: List[Dict[str, Any]] = []
        changed = False
        for idx, row in updated_df.iterrows():
            orig = emps[idx] if idx < len(emps) else {}
            merged = dict(orig)
            for k, _, _, _, ctype in EMP_GRID_COLUMNS:
                val = row.get(k)
                if ctype.startswith("numeric"):
                    num_v = int(round(float(val or 0))) if pd.notna(val) and str(val).strip() != "" else 0
                    if int(orig.get(k, 0) or 0) != num_v:
                        changed = True
                    merged[k] = num_v
                else:
                    str_v = "" if pd.isna(val) else str(val).strip()
                    if str(orig.get(k, "") or "") != str_v:
                        changed = True
                    merged[k] = str_v
            new_emps.append(merged)
        if changed:
            pstate["employees"] = new_emps
            _recalculate_all_employee_rows(pstate)
            pstate["grid_version"] += 1
            st.rerun()


def _render_freelancer_aggrid(pstate: Dict[str, Any]) -> None:
    frees = pstate.get("freelancers", [])
    col_keys = [c[0] for c in FREE_GRID_COLUMNS]

    if not frees:
        df = pd.DataFrame(columns=col_keys)
    else:
        rows_norm = []
        for idx, f in enumerate(frees, start=1):
            r = {}
            for k, _, _, _, ctype in FREE_GRID_COLUMNS:
                if k == "코드":
                    r[k] = str(f.get(k) or f"{idx:04d}")
                elif ctype.startswith("numeric"):
                    r[k] = int(f.get(k, 0) or 0)
                else:
                    r[k] = str(f.get(k, "") or "")
            rows_norm.append(r)
        df = pd.DataFrame(rows_norm, columns=col_keys)

    gb = GridOptionsBuilder.from_dataframe(df)
    gb.configure_default_column(resizable=True, sortable=True, filter=False)

    for field, header_name, width, editable, ctype in FREE_GRID_COLUMNS:
        pinned = "left" if field in ("코드", "성명") else None
        if ctype == "select_mode":
            gb.configure_column(
                field,
                header_name=header_name,
                width=width,
                editable=editable,
                cellEditor="agSelectCellEditor",
                cellEditorParams={"values": ["세전", "세후역산"]},
            )
        elif ctype.startswith("numeric"):
            cell_style = {"textAlign": "right"}
            if ctype == "numeric_total":
                cell_style = {"textAlign": "right", "fontWeight": "bold", "backgroundColor": "#f8fafc"}
            elif ctype == "numeric_net":
                cell_style = {"textAlign": "right", "fontWeight": "bold", "backgroundColor": "#f3e8ff", "color": "#4c1d95"}
            gb.configure_column(
                field,
                header_name=header_name,
                width=width,
                editable=editable,
                type=["numericColumn", "numberColumnFilter"],
                valueFormatter="x != null ? Number(x).toLocaleString() : '0'",
                cellStyle=cell_style,
            )
        else:
            gb.configure_column(
                field,
                header_name=header_name,
                width=width,
                editable=editable,
                pinned=pinned,
            )

    grid_opts = gb.build()
    grid_height = min(480, max(220, 56 + len(df) * 36))

    grid_resp = AgGrid(
        df,
        gridOptions=grid_opts,
        height=grid_height,
        update_mode=GridUpdateMode.VALUE_CHANGED,
        allow_unsafe_jscode=True,
        theme="streamlit",
        key=f"pay_free_aggrid_{pstate.get('grid_version', 0)}",
    )

    updated_df = grid_resp.get("data")
    if updated_df is not None and isinstance(updated_df, pd.DataFrame) and not updated_df.empty:
        new_frees: List[Dict[str, Any]] = []
        changed = False
        for idx, row in updated_df.iterrows():
            orig = frees[idx] if idx < len(frees) else {}
            merged = dict(orig)
            for k, _, _, _, ctype in FREE_GRID_COLUMNS:
                val = row.get(k)
                if ctype.startswith("numeric"):
                    num_v = int(round(float(val or 0))) if pd.notna(val) and str(val).strip() != "" else 0
                    if int(orig.get(k, 0) or 0) != num_v:
                        changed = True
                    merged[k] = num_v
                else:
                    str_v = "" if pd.isna(val) else str(val).strip()
                    if str(orig.get(k, "") or "") != str_v:
                        changed = True
                    merged[k] = str_v
            new_frees.append(merged)
        if changed:
            pstate["freelancers"] = new_frees
            _recalculate_all_freelancer_rows(pstate)
            pstate["grid_version"] += 1
            st.rerun()


def render_payroll_automated_main(gemini_api_key: Optional[str] = None) -> None:
    st.markdown(PAYROLL_CSS, unsafe_allow_html=True)
    pstate = _get_payroll_state()
    is_emp_mode = pstate.get("sub_mode", "EMP") == "EMP"

    diag = analyze_payroll_warnings(
        employees=pstate.get("employees", []),
        freelancers=pstate.get("freelancers", []),
        prev_employees=pstate.get("prev_employees", []),
        prev_freelancers=pstate.get("prev_freelancers", []),
    )
    dot_color_map = {"gray": "#94a3b8", "yellow": "#eab308", "red": "#dc2626"}
    dot_hex = dot_color_map.get(diag["status_color"], "#94a3b8")
    status_label_map = {"gray": "이상없음", "yellow": "주의", "red": "경고"}
    status_word = status_label_map.get(diag["status_color"], "이상없음")

    # 1. 최상단 컨트롤 바
    top_c1, top_c2, top_c3, top_c4, top_c5, top_c6 = st.columns([1.45, 0.85, 0.85, 1.55, 1.55, 1.25], gap="small")

    with top_c1:
        prev_btn_label = "전월 급여 불러오기" if is_emp_mode else "전월 사업소득 불러오기"
        if st.button(prev_btn_label, width="stretch", key="btn_pay_load_prev_month"):
            prev_pack = get_previous_month_data(
                pstate.get("client_db", {}),
                pstate.get("year_month", ""),
            )
            if prev_pack:
                if is_emp_mode and prev_pack.get("employees"):
                    pstate["prev_employees"] = list(prev_pack["employees"])
                    pstate["employees"] = [dict(e) for e in prev_pack["employees"]]
                    _recalculate_all_employee_rows(pstate)
                    pstate["grid_version"] += 1
                    st.toast(f"직전 귀속월({prev_pack.get('year_month')}) 급여대장 {len(pstate['employees'])}명을 불러왔습니다.")
                    st.rerun()
                elif not is_emp_mode and prev_pack.get("freelancers"):
                    pstate["prev_freelancers"] = list(prev_pack["freelancers"])
                    pstate["freelancers"] = [dict(f) for f in prev_pack["freelancers"]]
                    _recalculate_all_freelancer_rows(pstate)
                    pstate["grid_version"] += 1
                    st.toast(f"직전 귀속월({prev_pack.get('year_month')}) 사업소득자 {len(pstate['freelancers'])}명을 불러왔습니다.")
                    st.rerun()
                else:
                    st.warning("누적 백업 DB에 해당 부문의 전월 데이터가 없습니다.")
            else:
                st.warning("누적 백업(.paybak) 파일에 저장된 전월 이력이 없습니다. 먼저 좌측 사이드바에서 백업 파일을 불러오거나 당월 엑셀을 업로드해 주세요.")

    with top_c2:
        if st.button("행 추가", width="stretch", key="btn_pay_add_row"):
            if is_emp_mode:
                next_idx = len(pstate["employees"]) + 1
                row_calc = calculate_employee_payroll_row(
                    base_pay=2_200_000,
                    meal_allowance=200_000,
                    dependents=1,
                    children_8_20=0,
                    effective_table=pstate.get("effective_table", "2026.03"),
                )
                pstate["employees"].append({
                    "사원코드": f"{next_idx:03d}",
                    "성명": f"신규사원{next_idx}",
                    "주민등록번호": "",
                    "입사일": datetime.now().strftime("%Y-%m-01"),
                    "퇴사일": "",
                    "부서": "",
                    "직급": "사원",
                    "부양가족수": 1,
                    "자녀수": 0,
                    "입력기준": "세전",
                    "목표실수령액": 0,
                    **row_calc,
                })
            else:
                next_idx = len(pstate["freelancers"]) + 1
                f_calc = calculate_freelancer_row(1_000_000)
                pstate["freelancers"].append({
                    "코드": f"{next_idx:04d}",
                    "성명": f"소득자{next_idx}",
                    "주민등록번호": "",
                    "소득구분": "940909",
                    "귀속년월": pstate.get("year_month", ""),
                    "지급년월일": pstate.get("pay_date", ""),
                    "입력기준": "세전",
                    "지급총액": f_calc["gross_pay"],
                    "세율": 3,
                    "소득세": f_calc["income_tax"],
                    "지방소득세": f_calc["local_tax"],
                    "공제액계": f_calc["total_deduction"],
                    "차인지급액": f_calc["net_pay"],
                })
            pstate["grid_version"] += 1
            st.rerun()

    with top_c3:
        if st.button("마지막 행 삭제", width="stretch", key="btn_pay_del_row"):
            if is_emp_mode and pstate["employees"]:
                pstate["employees"].pop()
                pstate["grid_version"] += 1
                st.rerun()
            elif not is_emp_mode and pstate["freelancers"]:
                pstate["freelancers"].pop()
                pstate["grid_version"] += 1
                st.rerun()

    with top_c4:
        if st.button(
            f"경고·주의사항 ({status_word} {diag['total_count']}건)",
            width="stretch",
            key="btn_pay_open_warnings",
        ):
            _dlg_payroll_warnings()
        st.markdown(
            f"<div style='margin-top:-6px; text-align:center; font-size:0.74rem; color:#475569;'>"
            f"<span style='display:inline-block;width:8px;height:8px;border-radius:50%;background:{dot_hex};margin-right:5px;'></span>"
            f"상태: <b>{status_word}</b> (경고 {diag['danger_count']} / 주의 {diag['warning_count']})"
            f"</div>",
            unsafe_allow_html=True,
        )

    with top_c5:
        if st.button("연장·야간·휴일근로수당 계산기", width="stretch", key="btn_pay_open_ot_calc"):
            _dlg_overtime_calculator()

    with top_c6:
        if st.button("주휴수당 계산기", width="stretch", key="btn_pay_open_wh_calc"):
            _dlg_weekly_holiday_calculator()

    # 2. 메인 편집 표 (AG Grid 급여대장 / 사업소득대장)
    corp_disp = pstate.get("corp_name") or "거래처 미입력"
    ym_disp = pstate.get("year_month") or ""

    if is_emp_mode:
        st.markdown(
            f"<div style='display:flex; justify-content:space-between; align-items:center; margin-top:4px; margin-bottom:4px;'>"
            f"<span style='font-size:1.02rem; font-weight:800; color:#1e3a8a;'>급여대장 편집기 (4대보험 근로소득자 · {corp_disp} · {ym_disp})</span>"
            f"<span style='font-size:0.82rem; color:#475569;'>셀을 더블클릭하여 수정하면 2026년 4대보험·간이세액·실수령액이 즉시 재계산됩니다 (부양가족 기본 1명)</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
        _render_employee_aggrid(pstate)

        emps = pstate.get("employees", [])
        tot_gross = sum(int(e.get("지급액계", 0) or 0) for e in emps)
        tot_ded = sum(int(e.get("공제액계", 0) or 0) for e in emps)
        tot_net = sum(int(e.get("차인지급액", 0) or 0) for e in emps)
        st.markdown(
            f"<div style='background:#f8fafc; border:1px solid #cbd5e1; border-radius:8px; padding:8px 14px; margin-bottom:10px; display:flex; justify-content:space-between; font-size:0.90rem; color:#0f172a;'>"
            f"<span><b>총 인원:</b> {len(emps)}명</span>"
            f"<span><b>지급액계 합계:</b> {tot_gross:,}원</span>"
            f"<span><b>공제액계 합계:</b> {tot_ded:,}원</span>"
            f"<span style='color:#1e3a8a;'><b>차인지급액(실지급) 합계:</b> {tot_net:,}원</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

        # 3-A. 급여명세서 모드 다운로드 바 (최대 200명 한 번에 · 초과 시 구간 선택 · 클릭 시 지연 생성)
        with st.container(border=True):
            emp_start_idx = 0
            if len(emps) > EMP_ZIP_MAX:
                batch_options = [
                    f"{b_start + 1}번 ~ {min(b_start + EMP_ZIP_MAX, len(emps))}번 ({min(EMP_ZIP_MAX, len(emps) - b_start)}명)"
                    for b_start in range(0, len(emps), EMP_ZIP_MAX)
                ]
                c_warn_emp, c_sel_emp = st.columns([3.2, 1.8], vertical_alignment="center")
                with c_warn_emp:
                    st.warning(
                        f"현재 총 {len(emps)}명으로 1회 급여명세서 ZIP 압축 한도({EMP_ZIP_MAX}명)를 초과합니다. 우측에서 구간을 선택해 {EMP_ZIP_MAX}명씩 분할 다운로드해 주세요. (위하고 엑셀 및 급여대장 PDF는 {len(emps)}명 전체가 포함됩니다)"
                    )
                with c_sel_emp:
                    sel_batch_lbl = st.selectbox("급여명세서 ZIP 다운로드 구간", options=batch_options, key="emp_zip_batch_sel")
                    emp_start_idx = batch_options.index(sel_batch_lbl) * EMP_ZIP_MAX

            dl1, dl2, dl3, dl4 = st.columns([1.6, 1.8, 1.1, 1.5], gap="small", vertical_alignment="center")
            yymm_short = re.sub(r"[^0-9]", "", ym_disp)[2:6] if len(re.sub(r"[^0-9]", "", ym_disp)) >= 6 else "2610"
            c_safe = corp_disp.replace(" ", "")

            with dl1:
                st.download_button(
                    label="위하고 급여 업로드양식 (.xlsx)",
                    data=_lazy_bytes(export_wehago_payroll_excel, emps, enabled=bool(emps)),
                    file_name=f"{yymm_short}_근로소득(업로드양식)_{c_safe}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    width="stretch",
                    disabled=(len(emps) == 0),
                    key="btn_dl_wehago_emp_xlsx",
                )
            with dl3:
                enc_chk = st.checkbox(
                    "생년월일 6자리 암호 설정",
                    value=bool(pstate.get("encrypt_payslip_zip", False)),
                    key="chk_pay_enc_birth",
                    help="체크 시 각 인별 급여명세서 PDF에 주민등록번호 앞 6자리(YYMMDD) 비밀번호가 설정되어 압축됩니다.",
                )
                pstate["encrypt_payslip_zip"] = enc_chk
            with dl2:
                inc_cnt = min(EMP_ZIP_MAX, max(0, len(emps) - emp_start_idx))
                st.download_button(
                    label=f"급여명세서 일괄 다운 (.zip / {inc_cnt}명)",
                    data=_lazy_bytes(
                        export_employee_payslips_zip,
                        enabled=bool(emps),
                        employees=emps,
                        corp_name=pstate.get("corp_name", ""),
                        year_month=ym_disp,
                        pay_date=pstate.get("pay_date", ""),
                        encrypt_with_birth=enc_chk,
                        start_index=emp_start_idx,
                        max_count=EMP_ZIP_MAX,
                    ),
                    file_name=f"{yymm_short}_급여명세서_일괄({emp_start_idx + 1}_{emp_start_idx + inc_cnt}번)_{c_safe}.zip",
                    mime="application/zip",
                    width="stretch",
                    disabled=(len(emps) == 0),
                    key="btn_dl_payslips_zip",
                )
            with dl4:
                st.download_button(
                    label="급여대장 다운로드 (.pdf)",
                    data=_lazy_bytes(
                        export_payroll_ledger_pdf,
                        enabled=bool(emps),
                        employees=emps,
                        corp_name=pstate.get("corp_name", ""),
                        year_month=ym_disp,
                        pay_date=pstate.get("pay_date", ""),
                    ),
                    file_name=f"{yymm_short}_급여대장_{c_safe}.pdf",
                    mime="application/pdf",
                    width="stretch",
                    disabled=(len(emps) == 0),
                    key="btn_dl_payroll_ledger_pdf",
                )
    else:
        st.markdown(
            f"<div style='display:flex; justify-content:space-between; align-items:center; margin-top:4px; margin-bottom:4px;'>"
            f"<span style='font-size:1.02rem; font-weight:800; color:#4c1d95;'>사업소득대장 편집기 (3.3% 프리랜서 · {corp_disp} · {ym_disp})</span>"
            f"<span style='font-size:0.82rem; color:#475569;'>세전 또는 세후역산 선택 시 소득세(3%)·지방소득세(0.3%)가 10원 미만 절사로 자동 계산됩니다</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
        _render_freelancer_aggrid(pstate)

        frees = pstate.get("freelancers", [])
        tot_fgross = sum(int(f.get("지급총액", 0) or 0) for f in frees)
        tot_fded = sum(int(f.get("공제액계", 0) or 0) for f in frees)
        tot_fnet = sum(int(f.get("차인지급액", 0) or 0) for f in frees)
        st.markdown(
            f"<div style='background:#faf5ff; border:1px solid #d8b4fe; border-radius:8px; padding:8px 14px; margin-bottom:10px; display:flex; justify-content:space-between; font-size:0.90rem; color:#1e1b4b;'>"
            f"<span><b>총 인원:</b> {len(frees)}명</span>"
            f"<span><b>지급총액(세전) 합계:</b> {tot_fgross:,}원</span>"
            f"<span><b>공제세액(3.3%) 합계:</b> {tot_fded:,}원</span>"
            f"<span style='color:#4c1d95;'><b>차인지급액(실지급) 합계:</b> {tot_fnet:,}원</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

        # 3-B. 사업소득 모드 다운로드 바 (최대 100명 한 번에 · 초과 시 구간 선택 · 클릭 시 지연 생성)
        with st.container(border=True):
            free_start_idx = 0
            if len(frees) > FREE_ZIP_MAX:
                f_batch_options = [
                    f"{b_start + 1}번 ~ {min(b_start + FREE_ZIP_MAX, len(frees))}번 ({min(FREE_ZIP_MAX, len(frees) - b_start)}명)"
                    for b_start in range(0, len(frees), FREE_ZIP_MAX)
                ]
                c_warn_fr, c_sel_fr = st.columns([3.2, 1.8], vertical_alignment="center")
                with c_warn_fr:
                    st.warning(
                        f"현재 총 {len(frees)}명으로 1회 사업소득명세서(PDF/JPG) ZIP 압축 한도({FREE_ZIP_MAX}명)를 초과합니다. 우측에서 구간을 선택해 {FREE_ZIP_MAX}명씩 분할 다운로드해 주세요. (위하고 엑셀 및 사업소득지급대장 PDF는 {len(frees)}명 전체가 포함됩니다)"
                    )
                with c_sel_fr:
                    sel_fbatch_lbl = st.selectbox("사업소득명세서 ZIP 다운로드 구간", options=f_batch_options, key="free_zip_batch_sel")
                    free_start_idx = f_batch_options.index(sel_fbatch_lbl) * FREE_ZIP_MAX

            fd1, fd2, fd3, fd4 = st.columns(4, gap="small", vertical_alignment="center")
            yymm_short = re.sub(r"[^0-9]", "", ym_disp)[2:6] if len(re.sub(r"[^0-9]", "", ym_disp)) >= 6 else "2610"
            c_safe = corp_disp.replace(" ", "")
            f_inc_cnt = min(FREE_ZIP_MAX, max(0, len(frees) - free_start_idx))

            with fd1:
                st.download_button(
                    label="위하고 사업소득 업로드양식 (.xlsx)",
                    data=_lazy_bytes(
                        export_wehago_freelancer_excel,
                        enabled=bool(frees),
                        freelancers=frees,
                        default_year_month=ym_disp,
                        default_pay_date=pstate.get("pay_date", ""),
                    ),
                    file_name=f"{yymm_short}_사업소득(업로드양식)_{c_safe}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    width="stretch",
                    disabled=(len(frees) == 0),
                    key="btn_dl_wehago_free_xlsx",
                )
            with fd2:
                st.download_button(
                    label=f"사업소득명세서 PDF 압축 (.zip / {f_inc_cnt}명)",
                    data=_lazy_bytes(
                        export_freelancer_statements_pdf_zip,
                        enabled=bool(frees),
                        freelancers=frees,
                        corp_name=pstate.get("corp_name", ""),
                        year_month=ym_disp,
                        pay_date=pstate.get("pay_date", ""),
                        start_index=free_start_idx,
                        max_count=FREE_ZIP_MAX,
                    ),
                    file_name=f"{yymm_short}_사업소득명세서_PDF({free_start_idx + 1}_{free_start_idx + f_inc_cnt}번)_{c_safe}.zip",
                    mime="application/zip",
                    width="stretch",
                    disabled=(len(frees) == 0),
                    key="btn_dl_free_pdf_zip",
                )
            with fd3:
                st.download_button(
                    label=f"사업소득명세서 이미지 압축 (.zip / JPG {f_inc_cnt}명)",
                    data=_lazy_bytes(
                        export_freelancer_statements_jpg_zip,
                        enabled=bool(frees),
                        freelancers=frees,
                        corp_name=pstate.get("corp_name", ""),
                        year_month=ym_disp,
                        pay_date=pstate.get("pay_date", ""),
                        start_index=free_start_idx,
                        max_count=FREE_ZIP_MAX,
                    ),
                    file_name=f"{yymm_short}_사업소득명세서_JPG({free_start_idx + 1}_{free_start_idx + f_inc_cnt}번)_{c_safe}.zip",
                    mime="application/zip",
                    width="stretch",
                    disabled=(len(frees) == 0),
                    key="btn_dl_free_jpg_zip",
                )
            with fd4:
                st.download_button(
                    label="사업소득지급대장 다운로드 (.pdf)",
                    data=_lazy_bytes(
                        export_freelancer_ledger_pdf,
                        enabled=bool(frees),
                        freelancers=frees,
                        corp_name=pstate.get("corp_name", ""),
                        year_month=ym_disp,
                    ),
                    file_name=f"{yymm_short}_사업소득지급대장_{c_safe}.pdf",
                    mime="application/pdf",
                    width="stretch",
                    disabled=(len(frees) == 0),
                    key="btn_dl_free_ledger_pdf",
                )

    # 4. 하단 드래그앤드롭 자료 업로드 영역
    with st.container(border=True):
        st.markdown(
            "<div style='font-size:0.92rem; font-weight:800; color:#0f172a; margin-bottom:4px;'>"
            "자료 드래그앤드롭 업로드 (거래처 급여 엑셀 · 4대보험 고지내역 PDF · 카카오톡 캡처 이미지)"
            "</div>",
            unsafe_allow_html=True,
        )
        up_files = st.file_uploader(
            "급여 엑셀(.xlsx), 건강·연금·고용보험 고지내역(.pdf/.png), 카톡 캡처(.jpg/.png)를 드래그하여 올려주세요.",
            type=["xlsx", "xls", "pdf", "png", "jpg", "jpeg", "paybak"],
            accept_multiple_files=True,
            key=f"pay_drag_uploader_{pstate.get('grid_version', 0)}",
        )
        if up_files:
            if st.button("업로드한 파일 대장에 즉시 반영", type="primary", width="stretch", key="btn_pay_apply_drag_files"):
                _process_uploaded_files_and_text(
                    pstate=pstate,
                    uploaded_files=up_files,
                    chat_text="",
                    gemini_api_key=gemini_api_key,
                )
                st.rerun()

    if pstate.get("chat_logs"):
        with st.expander("최근 자동 반영 내역 로그", expanded=False):
            for lg in reversed(pstate["chat_logs"][-12:]):
                st.markdown(f"- {lg}")

    with st.expander("관련 법령 및 원천징수·4대보험·수당 산출 근거 주석 (업로드 전·후 상시 열람)", expanded=False):
        for ref in MONTHLY_REPORT_LEGAL_REFERENCES + WARNING_MODAL_LEGAL_REFERENCES[:2]:
            ref_content = ref["content"].replace("\n", "<br>")
            st.markdown(
                f"<div class='pay-law-ref-box'><b>[{ref['title']}]</b><br>{ref_content}</div>",
                unsafe_allow_html=True,
            )

    # 5. 최하단 올인원 입력창
    chat_val = st.chat_input(
        "카카오톡 급여 내역 텍스트 붙여넣기 (예: 홍길동 실수령 280만원, 김영희 세전 350, 박민수 프리랜서 150만원) 또는 파일 첨부",
        accept_file="multiple",
        file_type=["xlsx", "xls", "pdf", "png", "jpg", "jpeg", "paybak"],
        key="pay_bottom_all_in_one_input",
    )
    if chat_val:
        in_text = ""
        in_files: List[Any] = []
        if isinstance(chat_val, str):
            in_text = chat_val
        else:
            in_text = getattr(chat_val, "text", "") or ""
            in_files = list(getattr(chat_val, "files", []) or [])
        _process_uploaded_files_and_text(
            pstate=pstate,
            uploaded_files=in_files,
            chat_text=in_text,
            gemini_api_key=gemini_api_key,
        )
        st.rerun()
