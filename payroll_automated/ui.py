# -*- coding: utf-8 -*-
"""
인건비 자동화 UI 모듈 (payroll_automated/ui.py)
- 좌측 사이드바 (사용자 지정 순서):
  1) 업무 화면 선택 카드 ([급여명세서] 파스텔 블루 3D / [사업소득] 파스텔 퍼플 3D — 개정사항 모니터링보다 상단 배치)
  2) 개정사항 모니터링 카드 (근로기준법·소득세법 정상 초록불 / 시행령 별표2·4대보험 요율 반영 노란불 분리)
  3) 작업 자료 관리 ([작업 초기화 (내용 비우기)] 3D 버튼)
  4) 사업자정보 카드 (거래처명, 사업장 구분[본점/지점/직접입력/선택안함], 귀속연월, 지급일자,
     상시근로자 수·사업주 고용보험 요율[근로소득 전용], [당월 검토보고], [통합고용세액공제 계산 연동 — 사업소득 시 비활성화])
  5) 거래처별 월별 누적 암호화 백업 카드 (.paybak)
- 우측 메인 화면:
  1) 최상단 툴바:
     - [급여명세서] 모드: [전월 급여 불러오기], [행 추가], [선택한 행 삭제], [경고·주의사항], [연장·야간·휴일근로수당 계산기], [주휴수당 계산기]
     - [사업소득] 모드: [전월 사업소득 불러오기], [행 추가], [선택한 행 삭제], [경고·주의사항], [업종코드 조회·선택] (근로기준법 수당 계산기 2종 미노출)
  2) AG Grid 편집 대장:
     - [급여대장 편집기]: 맨 앞 열 '사업장'(본점/지점/직접입력/거래처명/공란 우선순위 반영, 위하고 엑셀 업로드양식에서는 자동 제외) +
       좌측 체크박스 다중 행 선택 + 한 화면 우측 끝이 '지급액계(세전)'까지 잘림(...) 없이 보이도록 열 폭 최적화 및 ☰ 필터 아이콘 제거
     - [사업소득대장 편집기]: 업종코드 기본 940909 + 드롭다운 및 [업종코드 조회·선택] 모달 연동 + 좌측 체크박스 다중 행 선택
  3) 서식 일괄 다운로드 바:
     - 급여명세서 6종 양식 선택(기본: 근로기준1) + 각 양식 우측 끝 돋보기 마우스 오버(:hover) 미리보기
     - [급여명세서 일괄 다운 (이미지)] 추가 및 [사업소득명세서 PDF 압축] 우측 돋보기 마우스 오버 미리보기
     - 사용자 지정 저장 파일명 규칙(`거래처명_..._YYMM`) 완벽 적용
  4) 최하단 올인원 입력창 (`st.chat_input` — 중간 중복 드래그앤드롭 박스 제거 후 파일 드래그앤드롭과 카톡 텍스트 입력을 최하단 창으로 일원화)
- [당월 검토보고]: 자율 에이전트AI의 보고서 양식과 동일한 형태(1. 결론 / 2. 내용 / 3. 관련법령), 색상, 폰트, 간격 적용 및 '주요 점검 사항' 영구 제외
- 이모티콘 미사용 원칙 준수 (순수 텍스트, SVG 돋보기 아이콘 및 CSS 원형 인디케이터만 사용)
"""

from __future__ import annotations

import inspect
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, JsCode

from .backup import (
    build_employment_credit_bridge_payload,
    build_year_month_coverage_notice,
    create_empty_client_db,
    decrypt_paybak_to_client_db,
    encrypt_client_db_to_paybak,
    get_previous_month_data,
    resolve_workplace_label,
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
    PAYSLIP_TEMPLATE_OPTIONS,
    export_employee_payslips_jpg_zip,
    export_employee_payslips_zip,
    export_freelancer_ledger_pdf,
    export_freelancer_statements_jpg_zip,
    export_freelancer_statements_pdf_zip,
    export_payroll_ledger_pdf,
    export_wehago_freelancer_excel,
    export_wehago_payroll_excel,
    get_freelancer_statement_preview_b64,
    get_payslip_template_preview_b64,
)
from .parsers import (
    FREELANCER_INDUSTRY_CODES,
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


# 돋보기 SVG 아이콘 (이모티콘 없이 순수 벡터 그래픽 사용)
MAGNIFIER_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" '
    'fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" '
    'style="vertical-align:middle;">'
    '<circle cx="11" cy="11" r="8"></circle>'
    '<line x1="21" y1="21" x2="16.65" y2="16.65"></line>'
    '</svg>'
)


# ─────────────────────────────────────────────────────────────
# 전용 CSS (3D 파스텔 블루/퍼플 버튼, 자율 에이전트AI 동일 보고서 서식, 돋보기 호버 미리보기)
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
.st-key-btn_pay_bridge_credit button:not(:disabled) {
    background: linear-gradient(180deg, #f0fdf4 0%, #dcfce7 100%) !important;
    border: 1px solid #4ade80 !important;
    border-bottom: 2.5px solid #16a34a !important;
    color: #14532d !important;
}
.st-key-btn_pay_bridge_credit button:disabled {
    background: linear-gradient(180deg, #f8fafc 0%, #e2e8f0 100%) !important;
    border: 1px solid #cbd5e1 !important;
    border-bottom: 2.5px solid #94a3b8 !important;
    color: #94a3b8 !important;
    opacity: 0.72 !important;
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

/* 자율 에이전트AI 보고서와 100% 동일한 형태·색상·폰트·간격 전용 스타일 */
.pa-agent-report-box {
    font-family: 'Pretendard', 'Malgun Gothic', 'Apple SD Gothic Neo', sans-serif !important;
    font-size: 1.12rem !important;
    line-height: 1.78 !important;
    color: #1e293b !important;
    letter-spacing: -0.2px !important;
}
.pa-agent-report-box h3 {
    font-size: 1.20rem !important;
    font-weight: 800 !important;
    color: #0f172a !important;
    background: linear-gradient(90deg, #f1f5f9 0%, #ffffff 100%);
    border-left: 4px solid #1e3a8a;
    padding: 6px 12px !important;
    margin-top: 1.4rem !important;
    margin-bottom: 0.75rem !important;
    border-radius: 0 6px 6px 0;
    line-height: 1.4 !important;
}
.pa-agent-report-box h4 {
    font-size: 1.08rem !important;
    font-weight: 700 !important;
    color: #1e40af !important;
    margin-top: 1.1rem !important;
    margin-bottom: 0.45rem !important;
    line-height: 1.45 !important;
}
.pa-agent-report-box p,
.pa-agent-report-box li {
    font-size: 1.06rem !important;
    line-height: 1.78 !important;
    color: #1e293b !important;
    margin-bottom: 0.45rem !important;
}
.pa-agent-report-box table {
    width: 100%;
    border-collapse: collapse;
    margin: 10px 0 14px 0;
    font-size: 0.95rem !important;
}
.pa-agent-report-box th {
    background-color: #f1f5f9 !important;
    color: #0f172a !important;
    font-weight: 700 !important;
    padding: 8px 10px !important;
    border: 1px solid #cbd5e1 !important;
    text-align: center !important;
}
.pa-agent-report-box td {
    padding: 7px 10px !important;
    border: 1px solid #cbd5e1 !important;
    color: #1e293b !important;
}
.pa-agent-report-box .related-laws-compact-box {
    font-size: 0.90rem !important;
    line-height: 1.56 !important;
    background-color: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    padding: 10px 14px;
    margin-top: 6px;
    color: #334155 !important;
}

/* 급여명세서 6종 및 사업소득명세서 우측 돋보기 마우스 오버(:hover) 미리보기 */
.pay-tpl-hover-wrap {
    position: relative;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    color: #1e40af;
    background: #eff6ff;
    border: 1px solid #93c5fd;
    border-radius: 7px;
    padding: 5px 8px;
    min-height: 36px;
    font-size: 0.78rem;
    font-weight: 700;
    user-select: none;
    transition: all 0.12s ease;
}
.pay-tpl-hover-wrap:hover {
    background: #dbeafe;
    border-color: #2563eb;
    color: #1e3a8a;
}
.pay-tpl-hover-popup {
    visibility: hidden;
    opacity: 0;
    position: fixed;
    right: 38px;
    bottom: 85px;
    z-index: 999999;
    width: 460px;
    max-width: 90vw;
    background: #ffffff;
    border: 2px solid #1e3a8a;
    border-radius: 12px;
    padding: 10px;
    box-shadow: 0 18px 38px rgba(15, 23, 42, 0.32);
    transition: opacity 0.14s ease, visibility 0.14s ease;
    pointer-events: none;
}
.pay-tpl-hover-wrap:hover .pay-tpl-hover-popup {
    visibility: visible;
    opacity: 1;
}
.pay-tpl-hover-title {
    font-size: 0.85rem;
    font-weight: 800;
    color: #0f172a;
    margin-bottom: 6px;
    padding-bottom: 5px;
    border-bottom: 1px solid #e2e8f0;
    display: flex;
    justify-content: space-between;
}
.pay-tpl-hover-popup img {
    width: 100%;
    height: auto;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    display: block;
}
</style>
"""


# ─────────────────────────────────────────────────────────────
# 세션 상태 초기화 및 헬퍼
# ─────────────────────────────────────────────────────────────

EMP_ZIP_MAX = 200
FREE_ZIP_MAX = 100


def _zip_bytes_to_files(zip_bytes: bytes) -> List[Tuple[str, bytes]]:
    import io as _io
    import zipfile as _zf
    out: List[Tuple[str, bytes]] = []
    with _zf.ZipFile(_io.BytesIO(zip_bytes)) as zf:
        for nm in zf.namelist():
            if not nm.endswith("/"):
                out.append((nm, zf.read(nm)))
    return out


def _trigger_multi_download(files: List[Tuple[str, bytes]], mime: str, key: str) -> None:
    """여러 파일을 압축하지 않고 개별 파일로 한 번에 내려받게 합니다.
    브라우저가 '여러 파일 다운로드 허용'을 물으면 [허용]을 누르면 됩니다(처음 한 번)."""
    import base64 as _b64
    import json as _json
    payload = _json.dumps([{"n": n, "d": _b64.b64encode(b).decode("ascii")} for n, b in files], ensure_ascii=False)
    html = (
        "<div style='font-family:sans-serif;font-size:12px;color:#334155;'>"
        "<button id='go' style='padding:4px 10px;border:1px solid #cbd5e1;border-radius:6px;background:#f8fafc;cursor:pointer;'>"
        f"다운로드가 시작되지 않으면 여기를 누르세요 ({len(files)}개)</button></div>"
        "<script>"
        f"const FILES={payload};const MIME={_json.dumps(mime)};"
        "async function go(){for(const f of FILES){const bin=atob(f.d);const arr=new Uint8Array(bin.length);"
        "for(let i=0;i<bin.length;i++){arr[i]=bin.charCodeAt(i);}"
        "const url=URL.createObjectURL(new Blob([arr],{type:MIME}));const a=document.createElement('a');"
        "a.href=url;a.download=f.n;document.body.appendChild(a);a.click();a.remove();"
        "setTimeout(()=>URL.revokeObjectURL(url),8000);await new Promise(r=>setTimeout(r,250));}}"
        "document.getElementById('go').onclick=go;go();"
        "</script>"
    )
    st.iframe(html, height=40)
    st.caption(f"{len(files)}개 파일 다운로드를 시작했습니다. 브라우저가 '여러 파일 다운로드'를 물으면 [허용]을 눌러 주세요.")


def _lazy_bytes(fn, *args, enabled: bool = True, **kwargs):
    """다운로드 버튼을 누를 때만 파일을 만들도록 호출 가능한 객체를 돌려줍니다."""
    import copy as _copy
    if not enabled:
        return b""
    a = _copy.deepcopy(args)
    kw = _copy.deepcopy(kwargs)
    return lambda: fn(*a, **kw)


def _sanitize_file_token(val: str, fallback: str = "거래처미입력") -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]+', "_", str(val or "").strip())
    return cleaned if cleaned else fallback


def _format_yymm_4digit(ym_str: str) -> str:
    digits = re.sub(r"[^0-9]", "", str(ym_str or ""))
    if len(digits) >= 6:
        return digits[2:6]
    if len(digits) == 4:
        return digits
    now = datetime.now()
    return f"{now.year % 100:02d}{now.month:02d}"


def _get_payroll_state() -> Dict[str, Any]:
    if "payroll_auto_state" not in st.session_state:
        now = datetime.now()
        default_ym = now.strftime("%Y-%m")
        default_pay_dt = now.strftime("%Y-%m-25")
        st.session_state.payroll_auto_state = {
            "sub_mode": "EMP",  # "EMP" (급여명세서) | "FREE" (사업소득)
            "corp_name": "",
            "workplace_mode": "본점",  # "본점" | "지점" | "직접입력" | "선택안함(거래처명 표시)"
            "workplace_custom": "",
            "year_month": default_ym,
            "pay_date": default_pay_dt,
            "is_5_or_more": True,
            "withholding_rate_pct": 100,
            "effective_table": "2026.03",
            "payslip_template": "근로기준1",
            "encrypt_payslip_zip": False,
            "employees": [],
            "freelancers": [],
            "prev_employees": [],
            "prev_freelancers": [],
            "selected_emp_indices": [],
            "selected_free_indices": [],
            "notice_logs": [],
            "chat_logs": [],
            "client_db": create_empty_client_db(""),
            "grid_version": 0,
        }
    pstate = st.session_state.payroll_auto_state
    pstate.setdefault("workplace_mode", "본점")
    pstate.setdefault("workplace_custom", "")
    pstate.setdefault("payslip_template", "근로기준1")
    pstate.setdefault("selected_emp_indices", [])
    pstate.setdefault("selected_free_indices", [])
    return pstate


def _current_workplace_label(pstate: Dict[str, Any]) -> str:
    return resolve_workplace_label(
        workplace_mode=pstate.get("workplace_mode", "본점"),
        workplace_custom=pstate.get("workplace_custom", ""),
        corp_name=pstate.get("corp_name", ""),
    )


def _sync_workplace_to_employees(pstate: Dict[str, Any], force_all: bool = False) -> None:
    wp_lbl = _current_workplace_label(pstate)
    for emp in pstate.get("employees", []):
        if force_all or "사업장" not in emp:
            emp["사업장"] = wp_lbl


def _reset_payroll_current_work() -> None:
    pstate = _get_payroll_state()
    pstate["employees"] = []
    pstate["freelancers"] = []
    pstate["selected_emp_indices"] = []
    pstate["selected_free_indices"] = []
    pstate["notice_logs"] = []
    pstate["chat_logs"] = []
    pstate["grid_version"] = int(pstate.get("grid_version", 0)) + 1


def _recalculate_all_employee_rows(pstate: Dict[str, Any]) -> None:
    eff_tbl = pstate.get("effective_table", "2026.03")
    pct = int(pstate.get("withholding_rate_pct", 100))
    wp_lbl = _current_workplace_label(pstate)
    new_list: List[Dict[str, Any]] = []
    for idx, emp in enumerate(pstate.get("employees", []), start=1):
        in_mode = str(emp.get("입력기준", "세전")).strip()
        ins_mode = str(emp.get("보험적용구분", "요율(2순위)")).strip()
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
        ceo_flag = is_ceo_position(str(emp.get("직급", "")))

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
        if "사업장" not in emp:
            emp["사업장"] = wp_lbl
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
        if not fr.get("소득구분"):
            fr["소득구분"] = "940909"
        new_list.append(fr)
    pstate["freelancers"] = new_list


# ─────────────────────────────────────────────────────────────
# 별도 웹 팝업 모달 (@st.dialog) — 상하단 잘림 방지 설계
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

    st.markdown("#### 관련 법령 및 신고 기준 안내")
    for ref in WARNING_MODAL_LEGAL_REFERENCES:
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
            "상시근로자 수 기준 (가산율 자동 분기)",
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


@st.dialog("사업소득(3.3%) 업종코드 조회 및 선택 반영", width="large")
def _dlg_industry_code_selector():
    pstate = _get_payroll_state()
    frees = pstate.get("freelancers", [])
    sel_indices: List[int] = pstate.get("selected_free_indices") or []

    st.markdown("<div class='pay-modal-scroll-box'>", unsafe_allow_html=True)
    kw = st.text_input(
        "업종코드 또는 업종내용 검색",
        placeholder="예: 940909, 강사, IT, 프로그래머, 디자이너, 모델, 배달...",
        key="pay_ind_search_kw",
    ).strip().lower()

    filtered = [
        item for item in FREELANCER_INDUSTRY_CODES
        if not kw
        or kw in item["code"].lower()
        or kw in item["name"].lower()
        or kw in item["category"].lower()
    ]
    if not filtered:
        filtered = FREELANCER_INDUSTRY_CODES

    st.caption("표 왼쪽 앞의 선택 칸(○)으로 적용할 업종코드를 선택한 뒤 하단 [반영] 버튼을 누르세요. (기본값: 940909)")
    code_list = [item["code"] for item in filtered]
    label_map = {
        item["code"]: f"{item['code']}  |  {item['name']}  ({item['category']})"
        for item in filtered
    }
    def_idx = code_list.index("940909") if "940909" in code_list else 0
    chosen_code = st.radio(
        "업종코드 / 내용 선택 (○)",
        options=code_list,
        index=def_idx,
        format_func=lambda c: label_map.get(c, c),
        key="pay_ind_radio_choice",
    )

    valid_sel = [i for i in sel_indices if 0 <= i < len(frees)]
    if valid_sel:
        sel_names = [str(frees[i].get("성명", "")) for i in valid_sel]
        st.info(f"현재 체크박스로 선택된 대상자 ({len(valid_sel)}명): {', '.join(sel_names)}")
    else:
        st.caption("표 왼쪽 체크박스로 특정 대상자를 먼저 체크하시면 [선택한 행에 반영]으로 개별 적용할 수 있습니다.")
    st.markdown("</div>", unsafe_allow_html=True)

    c_b1, c_b2, c_b3 = st.columns([1.8, 1.8, 1.0])
    with c_b1:
        if st.button(
            f"선택한 행에 반영 ({chosen_code})",
            type="primary",
            width="stretch",
            disabled=(len(valid_sel) == 0),
            key="btn_ind_apply_selected",
        ):
            for i in valid_sel:
                frees[i]["소득구분"] = chosen_code
            pstate["grid_version"] += 1
            st.rerun()
    with c_b2:
        if st.button(
            f"전체 행에 일괄 반영 ({chosen_code})",
            width="stretch",
            disabled=(len(frees) == 0),
            key="btn_ind_apply_all",
        ):
            for fr in frees:
                fr["소득구분"] = chosen_code
            pstate["grid_version"] += 1
            st.rerun()
    with c_b3:
        if st.button("닫기", width="stretch", key="btn_ind_close"):
            st.rerun()


def _report_html(parts: List[str]) -> str:
    """보고서 HTML을 들여쓰기 없이 이어 붙입니다 (들여쓰기가 있으면 Streamlit 마크다운이 코드 블록으로 표시해 HTML이 깨져 보임)."""
    return "\n".join(line.strip() for part in parts for line in str(part).splitlines() if line.strip())


def _report_header_common(pstate: Dict[str, Any]) -> Tuple[str, str, str]:
    corp = pstate.get("corp_name") or "미입력"
    wp_lbl = _current_workplace_label(pstate)
    corp_disp = f"{corp} ({wp_lbl})" if wp_lbl and wp_lbl != corp else corp
    ym = pstate.get("year_month") or datetime.now().strftime("%Y-%m")
    pay_dt = pstate.get("pay_date") or ""
    return corp_disp, ym, pay_dt


@st.dialog("당월 급여 검토보고 (4대보험 근로소득자)", width="large")
def _dlg_monthly_review_report_emp():
    """급여명세서 화면 전용 검토보고 — 이전 구성(검토 요약표 → 사업주 부담 추정 → 인원 변동)을 유지하고,
    디자인·폰트·간격만 자율 에이전트AI 보고서 스타일(pa-agent-report-box)을 따릅니다. 사업소득자는 포함하지 않습니다."""
    pstate = _get_payroll_state()
    emps = pstate.get("employees", [])
    corp_disp, ym, pay_dt = _report_header_common(pstate)
    diag = analyze_payroll_warnings(
        employees=emps,
        freelancers=[],
        prev_employees=pstate.get("prev_employees", []),
        prev_freelancers=[],
    )
    sm = lambda k: sum(int(e.get(k, 0) or 0) for e in emps)
    tot_gross, tot_nontax, tot_taxable = sm("지급액계"), sm("비과세합계"), sm("과세급여")
    tot_ins = sm("국민연금") + sm("건강보험") + sm("장기요양보험료") + sm("고용보험")
    tot_settle = sm("건강보험료정산") + sm("장기요양보험료정산") + sm("국민연금정산")
    tot_itax, tot_ltax, tot_ded, tot_net = sm("소득세"), sm("지방소득세"), sm("공제액계"), sm("차인지급액")

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

    mv = diag["movement_summary"]
    j = lambda xs: ", ".join(xs) if xs else "해당 없음"
    html = _report_html([
        "<div class='pay-modal-scroll-box'><div class='pa-agent-report-box'>",
        f"<h3>[{corp_disp}] {ym} 귀속 급여 및 원천징수 검토 요약</h3>",
        f"<p>지급일: <b>{pay_dt or '미입력'}</b> · 근로소득자 <b>{len(emps)}명</b></p>",
        "<table style='table-layout:fixed;'><colgroup>" + "<col style='width:11.9%'>" * 7 + "<col style='width:16.7%'></colgroup>"
        "<thead><tr><th>지급액계</th><th>비과세</th><th>과세급여</th><th>4대보험 공제</th><th>소득세</th><th>지방소득세</th><th>공제액계</th><th>차인지급액(실지급)</th></tr></thead>",
        f"<tbody><tr><td style='text-align:right;'>{tot_gross:,}원</td><td style='text-align:right;'>{tot_nontax:,}원</td>"
        f"<td style='text-align:right;'>{tot_taxable:,}원</td><td style='text-align:right;'>{tot_ins + tot_settle:,}원</td>"
        f"<td style='text-align:right;'>{tot_itax:,}원</td><td style='text-align:right;'>{tot_ltax:,}원</td>"
        f"<td style='text-align:right;'>{tot_ded:,}원</td><td style='text-align:right; font-weight:800; color:#1e3a8a;'>{tot_net:,}원</td></tr></tbody></table>",
        (f"<p style='font-size:0.92rem; color:#475569;'>* 4대보험 공제에는 정산분 {tot_settle:,}원이 포함되어 있습니다.</p>" if tot_settle else ""),
        "<h3>사업주 부담 4대보험 추정 (산재보험 제외)</h3>",
        "<table style='table-layout:fixed;'><colgroup>" + "<col style='width:18.5%'>" * 4 + "<col style='width:26%'></colgroup>"
        "<thead><tr><th>국민연금</th><th>건강보험</th><th>장기요양</th><th>고용보험</th><th>사업주 부담 합계</th></tr></thead>",
        f"<tbody><tr><td style='text-align:right;'>{own['국민연금_사업주']:,}원</td><td style='text-align:right;'>{own['건강보험_사업주']:,}원</td>"
        f"<td style='text-align:right;'>{own['장기요양_사업주']:,}원</td><td style='text-align:right;'>{own['고용보험_사업주']:,}원</td>"
        f"<td style='text-align:right; font-weight:800; color:#1e3a8a;'>{own['합계_사업주']:,}원</td></tr></tbody></table>",
        f"<p style='font-size:0.92rem; color:#475569;'>* 국민연금·건강·장기요양은 근로자 부담분(고지 반영 시 고지 금액)과 같은 금액이며, "
        f"고용보험은 과세급여 × (실업급여 0.9% + 고용안정·직능 {tier_lbl.split('·')[-1].strip()})로 추정했습니다 (대표이사·고용보험 0원 대상자 제외, 정산분 미포함).</p>",
        "<h3>전월 대비 인원 변동 및 4대보험 신고 대상</h3>",
        f"<ul><li><b>신규 입사 (자격취득신고 대상):</b> {j(mv.get('new_hires'))}</li>"
        f"<li><b>퇴사·제외 (자격상실신고 대상):</b> {j(mv.get('retirees'))}</li>"
        f"<li><b>전월 대비 급여 20% 이상 변동자:</b> {j(mv.get('pay_changes'))}</li></ul>",
        "</div></div>",
    ])
    st.markdown(html, unsafe_allow_html=True)
    if st.button("닫기", type="primary", width="stretch", key="btn_close_monthly_rep_emp"):
        st.rerun()


@st.dialog("당월 사업소득 검토보고 (3.3% 사업소득자)", width="large")
def _dlg_monthly_review_report_free():
    """사업소득 화면 전용 검토보고 — 근로소득자 내용은 포함하지 않습니다."""
    pstate = _get_payroll_state()
    frees = pstate.get("freelancers", [])
    prev = pstate.get("prev_freelancers", []) or []
    corp_disp, ym, pay_dt = _report_header_common(pstate)
    sm = lambda k: sum(int(f.get(k, 0) or 0) for f in frees)
    tot_gross, tot_itax, tot_ltax, tot_ded, tot_net = sm("지급총액"), sm("소득세"), sm("지방소득세"), sm("공제액계"), sm("차인지급액")
    by_code: Dict[str, List[str]] = {}
    for f in frees:
        by_code.setdefault(str(f.get("소득구분") or "940909"), []).append(str(f.get("성명") or ""))
    code_rows = "".join(
        f"<tr><td style='text-align:center;'>{_ind_label(c)}</td><td style='text-align:center;'>{len(ns)}명</td>"
        f"<td style='text-align:right;'>{sum(int(f.get('지급총액', 0) or 0) for f in frees if str(f.get('소득구분') or '940909') == c):,}원</td></tr>"
        for c, ns in sorted(by_code.items())
    )
    cur_names = {str(f.get("성명") or "").strip() for f in frees if str(f.get("성명") or "").strip()}
    prev_names = {str(f.get("성명") or "").strip() for f in prev if str(f.get("성명") or "").strip()}
    j = lambda xs: ", ".join(sorted(xs)) if xs else "해당 없음"
    html = _report_html([
        "<div class='pay-modal-scroll-box'><div class='pa-agent-report-box'>",
        f"<h3>[{corp_disp}] {ym} 귀속 사업소득 지급 및 원천징수 검토 요약</h3>",
        f"<p>지급일: <b>{pay_dt or '미입력'}</b> · 사업소득자 <b>{len(frees)}명</b></p>",
        "<table><thead><tr><th>지급총액(세전)</th><th>소득세(3%)</th><th>지방소득세(0.3%)</th><th>원천징수 합계</th><th>차인지급액(실지급)</th></tr></thead>",
        f"<tbody><tr><td style='text-align:right;'>{tot_gross:,}원</td><td style='text-align:right;'>{tot_itax:,}원</td>"
        f"<td style='text-align:right;'>{tot_ltax:,}원</td><td style='text-align:right;'>{tot_ded:,}원</td>"
        f"<td style='text-align:right; font-weight:800; color:#4c1d95;'>{tot_net:,}원</td></tr></tbody></table>",
        "<h3>업종코드별 지급 현황</h3>",
        f"<table><thead><tr><th>업종코드(내용)</th><th>인원</th><th>지급총액</th></tr></thead><tbody>{code_rows}</tbody></table>",
        "<h3>전월 대비 지급 대상 변동</h3>",
        (f"<ul><li><b>신규 지급 대상:</b> {j(cur_names - prev_names)}</li><li><b>전월 지급, 당월 미지급:</b> {j(prev_names - cur_names)}</li></ul>"
         if prev_names else "<p>전월 누적 자료가 없어 비교하지 않았습니다.</p>"),
        "</div></div>",
    ])
    st.markdown(html, unsafe_allow_html=True)
    if st.button("닫기", type="primary", width="stretch", key="btn_close_monthly_rep_free"):
        st.rerun()


# ─────────────────────────────────────────────────────────────
# 좌측 사이드바 렌더링 (인건비 자동화 모드)
# ─────────────────────────────────────────────────────────────

def render_payroll_automated_sidebar() -> None:
    st.markdown(PAYROLL_CSS, unsafe_allow_html=True)
    pstate = _get_payroll_state()
    is_emp_mode = pstate.get("sub_mode", "EMP") == "EMP"

    # (1) 최상단 카드: 업무 화면 선택 ([급여명세서] 파스텔 블루 / [사업소득] 파스텔 퍼플 — 개정사항 모니터링보다 위에 배치)
    with st.container(border=True):
        st.markdown("<div class='sb-card-title'><span>업무 화면 선택</span></div>", unsafe_allow_html=True)
        col_emp, col_free = st.columns(2, gap="small")
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

    # (2) 개정사항 모니터링 카드 (Row 1: 근로기준법·소득세법 초록불 / Row 2: 시행령 별표2·4대보험 요율 노란불 분리)
    alerts = check_payroll_law_revisions(force_refresh=False)
    row1_laws = [a for a in alerts if "별표" not in a.get("law", "") and "보험" not in a.get("law", "")]
    row2_laws = [a for a in alerts if "별표" in a.get("law", "") or "보험" in a.get("law", "")]
    row1_new = any(a.get("status") == "new_revision" for a in row1_laws)
    row2_new = any(a.get("status") == "new_revision" for a in row2_laws)
    row2_upd = any(a.get("status") in ("updated", "new_revision") for a in row2_laws) or True

    led_row1 = "pay-dot-red" if row1_new else "pay-dot-green"
    led_row2 = "pay-dot-red" if row2_new else ("pay-dot-yellow" if row2_upd else "pay-dot-green")
    badge_row2 = (
        "<span class='pay-law-badge-amber'>신규 개정 감지</span>"
        if row2_new
        else "<span class='pay-law-badge-amber'>2026.03 별표2·요율 반영</span>"
    )

    with st.container(border=True):
        st.markdown(
            "<div class='sb-card-title'><span>개정사항 모니터링</span></div>"
            f"<div class='pay-law-row'>"
            f"<span><span class='pay-dot {led_row1}'></span>근로기준법 · 소득세법</span>"
            f"<span class='pay-law-badge-green'>정상</span>"
            f"</div>"
            f"<div class='pay-law-row' style='margin-bottom:8px;'>"
            f"<span><span class='pay-dot {led_row2}'></span>시행령 별표2 · 4대보험 요율</span>"
            f"{badge_row2}"
            f"</div>",
            unsafe_allow_html=True,
        )
        if st.button("상세 보기", width="stretch", key="btn_pay_law_detail"):
            _dlg_payroll_law_revisions()

    # (3) 작업 초기화 버튼 카드
    emp_cnt = len(pstate.get("employees", []))
    free_cnt = len(pstate.get("freelancers", []))
    has_data = (emp_cnt + free_cnt) > 0 or bool(pstate.get("corp_name"))

    with st.container(border=True):
        status_pill = (
            f"<span class='sb-badge-green'>근로 {emp_cnt}명 · 사업 {free_cnt}명</span>"
            if has_data
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

    # (4) 사업자정보 카드 (거래처명 + 사업장 구분[본점/지점/직접입력/선택안함] + 귀속연월 + 지급일자 + [당월 검토보고] + [통합고용세액공제 계산 연동])
    with st.container(border=True):
        st.markdown("<div class='sb-card-title'><span>사업자정보</span></div>", unsafe_allow_html=True)
        prev_wp_label = _current_workplace_label(pstate)

        corp_val = st.text_input(
            "거래처명",
            value=pstate.get("corp_name", ""),
            placeholder="예: 주식회사 한빛테크",
            key="pay_sb_corp_name",
        )
        pstate["corp_name"] = corp_val.strip()

        wp_options = ["본점", "지점", "직접입력", "선택안함(거래처명 표시)"]
        cur_wp_mode = pstate.get("workplace_mode", "본점")
        if cur_wp_mode not in wp_options:
            cur_wp_mode = "본점"
        sel_wp_mode = st.selectbox(
            "사업장 구분 (본·지점 / 사업장명)",
            options=wp_options,
            index=wp_options.index(cur_wp_mode),
            key="pay_sb_wp_mode",
            help="급여대장 편집기 맨 앞 '사업장' 열에 표시되며, 본점·지점 백업파일(.paybak)을 통합고용세액공제에 드래그앤드롭하여 합산할 때 구분 기준으로 사용됩니다.",
        )
        pstate["workplace_mode"] = sel_wp_mode

        if sel_wp_mode in ("지점", "직접입력"):
            wp_custom_val = st.text_input(
                "지점·사업장 명칭",
                value=pstate.get("workplace_custom", ""),
                placeholder="예: 강남지점 / B사업장",
                key="pay_sb_wp_custom",
            )
            pstate["workplace_custom"] = wp_custom_val.strip()

        new_wp_label = _current_workplace_label(pstate)
        if new_wp_label != prev_wp_label:
            for emp in pstate.get("employees", []):
                if not emp.get("사업장") or emp.get("사업장") == prev_wp_label:
                    emp["사업장"] = new_wp_label
            pstate["grid_version"] = int(pstate.get("grid_version", 0)) + 1

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
        scale_label = "5인 이상 (가산수당 1.5배)" if total_workers >= 5 else "5인 미만 (가산수당 특례)"
        pstate["is_5_or_more"] = total_workers >= 5

        if is_emp_mode:
            st.markdown(
                f"<div style='background:#f8fafc; border:1px solid #e2e8f0; border-radius:6px; padding:6px 10px; margin-bottom:8px; font-size:0.83rem; color:#1e293b;'>"
                f"<b>상시근로자 수:</b> {total_workers}명 (재직 {active_workers}명)<br>"
                f"<span style='font-size:0.76rem; color:#475569;'>적용 기준: {scale_label}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )

            manual_cnt = pstate.get("ei_emp_count_manual")
            ei_cnt = st.number_input(
                "상시근로자 수 (전 사업장 합산)",
                min_value=0,
                value=int(manual_cnt) if manual_cnt is not None else int(total_workers),
                step=1,
                key=f"pay_sb_ei_emp_count_{total_workers}",
                help="기본값은 급여대장 인원입니다. 다른 사업장이 있으면 합산한 인원으로 고치세요 (시행령 제12조 제2항).",
            )
            ei_cnt = int(ei_cnt)
            pstate["ei_emp_count_manual"] = ei_cnt if ei_cnt != int(total_workers) else None
            pstate["ei_emp_count"] = ei_cnt
            tier_labels = [t[0] for t in EI_STABILITY_TIERS]
            auto_tier = tier_labels[0] if ei_cnt < 150 else tier_labels[1]
            manual_tier = pstate.get("ei_stability_tier_manual")
            cur_tier = manual_tier if manual_tier in tier_labels else auto_tier
            sel_tier = st.selectbox(
                "사업주 고용보험 (고용안정·직능) 요율",
                options=tier_labels,
                index=tier_labels.index(cur_tier),
                key=f"pay_sb_ei_tier_{'150up' if ei_cnt >= 150 else 'under150'}",
                help=(
                    "150명 미만은 0.25%입니다. 150명 이상이면 우선지원대상기업 여부에 따라 0.45% / 0.65% / 0.85% 중 직접 고르세요."
                ),
            )
            pstate["ei_stability_tier_manual"] = sel_tier if sel_tier != auto_tier else None
            pstate["ei_stability_tier"] = sel_tier

        if st.button("당월 검토보고", width="stretch", key="btn_pay_monthly_report"):
            if is_emp_mode:
                _dlg_monthly_review_report_emp()
            else:
                _dlg_monthly_review_report_free()

        if st.button(
            "통합고용세액공제 계산 연동",
            width="stretch",
            disabled=(not is_emp_mode),
            key="btn_pay_bridge_credit",
            help=None if not is_emp_mode else "현재 사업장 급여내역을 통합고용세액공제 1단계 원천징수부 자료로 즉시 연동합니다.",
        ):
            pstate["client_db"] = upsert_monthly_data_into_db(
                client_db=pstate.get("client_db", {}),
                corp_name=pstate.get("corp_name", ""),
                year_month=pstate.get("year_month", ""),
                pay_date=pstate.get("pay_date", ""),
                employees=pstate.get("employees", []),
                freelancers=pstate.get("freelancers", []),
                is_5_or_more=pstate.get("is_5_or_more", True),
                workplace_mode=pstate.get("workplace_mode", "본점"),
                workplace_custom=pstate.get("workplace_custom", ""),
            )
            bridge_payload, msg = build_employment_credit_bridge_payload(
                client_db=pstate["client_db"],
                current_corp_name=pstate.get("corp_name", ""),
                current_year_month=pstate.get("year_month", ""),
                current_employees=pstate.get("employees", []),
                workplace_label=_current_workplace_label(pstate),
            )
            st.session_state["payroll_to_ec_bridge"] = bridge_payload
            st.session_state["payroll_bridge_notice"] = msg
            st.session_state.app_top_mode = "CREDIT_CALC"
            st.rerun()
        if not is_emp_mode:
            st.caption("사업소득 화면에서는 통합고용세액공제 계산 연동이 비활성화됩니다.")

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
            cov_txt = build_year_month_coverage_notice(pstate.get("client_db", {}))
            st.caption(f"누적 귀속월: {', '.join(saved_months)} ({cov_txt})")
        else:
            st.caption("본점·지점별 백업 파일(.paybak)을 생성해 두면 통합고용세액공제 1단계에 드래그앤드롭하여 복수 사업장으로 합산할 수 있습니다.")

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
                    workplace_mode=pstate.get("workplace_mode", "본점"),
                    workplace_custom=pstate.get("workplace_custom", ""),
                )
                bak_bytes = encrypt_client_db_to_paybak(pstate["client_db"], password=bk_pw)
                c_nm = _sanitize_file_token(pstate.get("corp_name") or "거래처", "거래처")
                wp_tag = _sanitize_file_token(_current_workplace_label(pstate) or "본점", "본점")
                st.session_state["pay_bak_ready"] = (bak_bytes, f"{c_nm}_{wp_tag}_인건비누적DB.paybak")
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
                    if c_info.get("workplace_mode"):
                        pstate["workplace_mode"] = c_info["workplace_mode"]
                    if c_info.get("workplace_custom") is not None:
                        pstate["workplace_custom"] = c_info.get("workplace_custom", "")
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

# 급여대장 편집기 컬럼:
# 맨 앞 '사업장' 열 추가 + 한 화면 우측 끝이 '지급액계(세전)'까지 잘림 없이 보이도록 열 폭 배분
EMP_GRID_COLUMNS: List[Tuple[str, str, int, bool, str]] = [
    ("사업장", "사업장", 82, True, "text"),
    ("사원코드", "코드", 46, True, "text"),
    ("성명", "성명", 62, True, "text"),
    ("주민등록번호", "주민등록번호", 108, True, "text"),
    ("입사일", "입사일", 80, True, "text"),
    ("퇴사일", "퇴사일", 80, True, "text"),
    ("직급", "직급", 50, True, "text"),
    ("부양가족수", "부양", 48, True, "numeric"),
    ("자녀수", "자녀", 48, True, "numeric"),
    ("입력기준", "기준", 50, True, "select_mode"),
    ("목표실수령액", "목표실수령", 80, True, "numeric"),
    ("기본급", "기본급", 92, True, "numeric"),
    ("식대", "식대", 78, True, "numeric"),
    ("자가운전보조금", "차량", 78, True, "numeric"),
    ("상여", "상여", 78, True, "numeric"),
    ("약정연장근로수당", "약정연장", 82, True, "numeric"),
    ("약정휴일근로수당", "약정휴일", 82, True, "numeric"),
    ("연장근로수당", "연장수당", 82, True, "numeric"),
    ("휴일근로수당", "휴일수당", 82, True, "numeric"),
    ("미사용연차수당", "연차수당", 80, True, "numeric"),
    ("결근공제", "결근공제", 80, True, "numeric"),
    ("조정금액", "조정금액", 78, True, "numeric"),
    ("지급액계", "지급액계(세전)", 106, False, "numeric_total"),
    # ── 아래부터는 가로 스크롤 우측 영역 (4대보험 및 공제·차인지급액) ──
    ("보험적용구분", "4대보험기준", 104, True, "select_ins"),
    ("국민연금", "국민연금", 98, True, "numeric"),
    ("건강보험", "건강보험", 98, True, "numeric"),
    ("장기요양보험료", "장기요양", 92, True, "numeric"),
    ("고용보험", "고용보험", 92, True, "numeric"),
    ("건강보험료정산", "건강정산", 92, True, "numeric"),
    ("장기요양보험료정산", "요양정산", 92, True, "numeric"),
    ("국민연금정산", "연금정산", 92, True, "numeric"),
    ("학자금상환액", "학자금상환", 92, True, "numeric"),
    ("소득세", "소득세", 92, True, "numeric"),
    ("지방소득세", "지방소득세", 92, True, "numeric"),
    ("공제액계", "공제액계", 106, False, "numeric_total"),
    ("차인지급액", "차인지급액(실지급)", 126, False, "numeric_net"),
]

FREE_GRID_COLUMNS: List[Tuple[str, str, int, bool, str]] = [
    ("코드", "코드", 92, True, "text"),
    ("성명", "소득자명(성명)", 110, True, "text"),
    ("주민등록번호", "주민등록번호", 145, True, "text"),
    ("소득구분", "업종코드(내용)", 190, True, "select_ind"),
    ("귀속년월", "귀속년월", 100, True, "text"),
    ("지급년월일", "지급년월일", 110, True, "text"),
    ("입력기준", "입력기준", 95, True, "select_mode"),
    ("지급총액", "지급총액(세전)", 130, True, "numeric"),
    ("세율", "세율(%)", 78, False, "numeric"),
    ("소득세", "소득세(3%)", 115, False, "numeric"),
    ("지방소득세", "지방소득세(0.3%)", 120, False, "numeric"),
    ("공제액계", "공제액계(3.3%)", 120, False, "numeric_total"),
    ("차인지급액", "차인지급액(실지급)", 138, True, "numeric_net"),
]


def _extract_selected_row_indices(grid_resp: Dict[str, Any]) -> List[int]:
    sel = grid_resp.get("selected_rows")
    if sel is None:
        return []
    if isinstance(sel, pd.DataFrame):
        if sel.empty or "_row_idx" not in sel.columns:
            return []
        return [int(v) for v in sel["_row_idx"].dropna().tolist()]
    if isinstance(sel, list):
        out: List[int] = []
        for item in sel:
            if isinstance(item, dict) and "_row_idx" in item:
                try:
                    out.append(int(item["_row_idx"]))
                except Exception:
                    pass
        return out
    return []


def _process_uploaded_files_and_text(
    pstate: Dict[str, Any],
    uploaded_files: List[Any],
    chat_text: str = "",
    gemini_api_key: Optional[str] = None,
) -> None:
    eff_tbl = pstate.get("effective_table", "2026.03")
    wp_lbl = _current_workplace_label(pstate)
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
                default_workplace=wp_lbl,
            )
            if res_ex["employees"]:
                if pstate.get("employees") and not pstate.get("prev_employees"):
                    pstate["prev_employees"] = list(pstate["employees"])
                pstate["employees"] = res_ex["employees"]
                pstate["sub_mode"] = "EMP"
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
            ntype = notice_res.get("notice_type")
            if ntype in ("사업소득대장", "사업소득대장_PDF") and notice_res.get("freelancers"):
                pstate["freelancers"] = notice_res["freelancers"]
                pstate["sub_mode"] = "FREE"
                if notice_res.get("corp_name") and not pstate.get("corp_name"):
                    pstate["corp_name"] = notice_res["corp_name"]
                if notice_res.get("year_month"):
                    pstate["year_month"] = notice_res["year_month"]
                pstate["chat_logs"].append(f"[사업소득대장 PDF 로드] {notice_res.get('message')}")
            elif ntype in ("급여대장", "급여대장_PDF") and notice_res.get("employees"):
                emps_loaded = notice_res["employees"]
                for e in emps_loaded:
                    if not e.get("사업장"):
                        e["사업장"] = wp_lbl
                pstate["employees"] = emps_loaded
                _recalculate_all_employee_rows(pstate)
                pstate["sub_mode"] = "EMP"
                if notice_res.get("corp_name") and not pstate.get("corp_name"):
                    pstate["corp_name"] = notice_res["corp_name"]
                if notice_res.get("year_month"):
                    pstate["year_month"] = notice_res["year_month"]
                pstate["chat_logs"].append(f"[급여대장·명세서 PDF 로드] {notice_res.get('message')}")
            elif ntype != "unknown":
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
                if c_info.get("corp_name"):
                    pstate["corp_name"] = c_info["corp_name"]
                if c_info.get("workplace_mode"):
                    pstate["workplace_mode"] = c_info["workplace_mode"]
                if c_info.get("workplace_custom") is not None:
                    pstate["workplace_custom"] = c_info.get("workplace_custom", "")
                m_map = loaded_db.get("monthly_payroll", {})
                if m_map:
                    latest_ym = sorted(m_map.keys())[-1]
                    latest_pack = m_map[latest_ym]
                    pstate["year_month"] = latest_ym
                    pstate["pay_date"] = latest_pack.get("pay_date", f"{latest_ym}-25")
                    pstate["employees"] = list(latest_pack.get("employees", []))
                    pstate["freelancers"] = list(latest_pack.get("freelancers", []))
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
            default_is_freelancer=(pstate.get("sub_mode") == "FREE"),
            default_workplace=wp_lbl,
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
    _sync_workplace_to_employees(pstate, force_all=False)
    emps = pstate.get("employees", [])
    wp_default = _current_workplace_label(pstate)
    col_keys = [c[0] for c in EMP_GRID_COLUMNS]

    if not emps:
        df = pd.DataFrame(columns=col_keys + ["_row_idx"])
    else:
        rows_norm = []
        for idx, e in enumerate(emps, start=1):
            r = {}
            for k, _, _, _, ctype in EMP_GRID_COLUMNS:
                if k == "사업장":
                    r[k] = str(e.get(k) if e.get(k) is not None else wp_default)
                elif k == "사원코드":
                    r[k] = str(e.get(k) or f"{idx:03d}")
                elif ctype.startswith("numeric"):
                    r[k] = int(e.get(k, 0) or 0)
                else:
                    r[k] = str(e.get(k, "") or "")
            r["_row_idx"] = idx - 1
            rows_norm.append(r)
        df = pd.DataFrame(rows_norm, columns=col_keys + ["_row_idx"])

    gb = GridOptionsBuilder.from_dataframe(df)
    gb.configure_default_column(
        resizable=True,
        sortable=True,
        filter=False,
        suppressMenu=True,
        minWidth=30,
    )
    gb.configure_selection(
        selection_mode="multiple",
        use_checkbox=False,
        suppressRowClickSelection=True,
    )
    gb.configure_column("_row_idx", hide=True)

    # 모든 사원이 0원인 금액 열(상여·차량 등)은 자동으로 좁혀 오른쪽 열(지급액계 등)이 한 화면에 더 보이게 합니다.
    zero_cols = set()
    if emps:
        for field, _, _, _, ctype in EMP_GRID_COLUMNS:
            if ctype == "numeric" and field not in ("부양가족수", "자녀수") and all(int(e.get(field, 0) or 0) == 0 for e in emps):
                zero_cols.add(field)

    for field, header_name, width, editable, ctype in EMP_GRID_COLUMNS:
        if field in zero_cols:
            width = 42
        pinned = "left" if field in ("사업장", "사원코드", "성명") else None
        is_first_col = (field == "사업장")
        if ctype == "select_mode":
            gb.configure_column(
                field,
                header_name=header_name,
                width=width,
                minWidth=width - 4,
                editable=editable,
                suppressMenu=True,
                cellEditor="agSelectCellEditor",
                cellEditorParams={"values": ["세전", "세후역산"]},
            )
        elif ctype == "select_ins":
            gb.configure_column(
                field,
                header_name=header_name,
                width=width,
                minWidth=width - 4,
                editable=editable,
                suppressMenu=True,
                cellEditor="agSelectCellEditor",
                cellEditorParams={"values": ["고지(1순위)", "요율(2순위)"]},
            )
        elif ctype.startswith("numeric"):
            cell_style = {"textAlign": "right", "paddingLeft": "4px", "paddingRight": "6px"}
            if ctype == "numeric_total":
                cell_style = {
                    "textAlign": "right",
                    "fontWeight": "bold",
                    "backgroundColor": "#eff6ff" if field == "지급액계" else "#f8fafc",
                    "color": "#1e3a8a" if field == "지급액계" else "#0f172a",
                    "paddingLeft": "4px",
                    "paddingRight": "6px",
                }
            elif ctype == "numeric_net":
                cell_style = {
                    "textAlign": "right",
                    "fontWeight": "bold",
                    "backgroundColor": "#f0fdf4",
                    "color": "#15803d",
                    "paddingLeft": "4px",
                    "paddingRight": "6px",
                }
            gb.configure_column(
                field,
                header_name=header_name,
                width=width,
                minWidth=width - 4,
                editable=editable,
                suppressMenu=True,
                type=["numericColumn"],
                valueFormatter="x != null ? Number(x).toLocaleString() : '0'",
                cellStyle=cell_style,
            )
        else:
            gb.configure_column(
                field,
                header_name=header_name,
                width=width,
                minWidth=width - 4,
                editable=editable,
                pinned=pinned,
                checkboxSelection=is_first_col,
                headerCheckboxSelection=is_first_col,
                suppressMenu=True,
            )

    grid_opts = gb.build()
    grid_opts["suppressSizeToFit"] = True
    grid_opts["ensureDomOrder"] = True
    # 최소화한 열: 머리글을 두 줄로 접어 말줄임(…) 없이 표시
    for cdef in grid_opts.get("columnDefs", []):
        if cdef.get("field") in zero_cols:
            cdef["wrapHeaderText"] = True
            cdef["autoHeaderHeight"] = True
            cdef["headerTooltip"] = f"{cdef.get('headerName', '')} (전원 0원 — 자동 축소)"
            cdef["headerClass"] = "pay-col-min"
            cdef["minWidth"] = 30
    grid_height = min(520, max(230, 58 + len(df) * 36))

    custom_css = {
        ".ag-header-cell-label": {"justify-content": "center", "font-weight": "700", "font-size": "12.2px"},
        ".ag-cell": {"font-size": "12.5px"},
        ".pay-col-min": {"padding-left": "2px !important", "padding-right": "2px !important"},
        ".pay-col-min .ag-header-cell-text": {"white-space": "normal !important", "line-height": "1.15", "text-align": "center"},
    }

    grid_resp = AgGrid(
        df,
        gridOptions=grid_opts,
        height=grid_height,
        update_mode=GridUpdateMode.VALUE_CHANGED | GridUpdateMode.SELECTION_CHANGED,
        fit_columns_on_grid_load=False,
        allow_unsafe_jscode=True,
        custom_css=custom_css,
        theme="streamlit",
        key=f"pay_emp_aggrid_{pstate.get('grid_version', 0)}",
    )

    pstate["selected_emp_indices"] = _extract_selected_row_indices(grid_resp)
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


def _ind_short_name(code: str) -> str:
    for item in FREELANCER_INDUSTRY_CODES:
        if item["code"] == code:
            return re.split(r"\s*[·(]\s*", item["name"])[0].strip()
    return ""


def _ind_code_only(val: Any) -> str:
    m = re.search(r"(\d{6})", str(val or ""))
    return m.group(1) if m else "940909"


def _ind_label(code_or_label: Any) -> str:
    """업종코드를 화면 표시용 "940909 (기타자영업)" 형태로 바꿉니다."""
    code = _ind_code_only(code_or_label)
    nm = _ind_short_name(code)
    return f"{code} ({nm})" if nm else code


def _render_freelancer_aggrid(pstate: Dict[str, Any]) -> None:
    frees = pstate.get("freelancers", [])
    col_keys = [c[0] for c in FREE_GRID_COLUMNS]
    ind_codes = [_ind_label(c["code"]) for c in FREELANCER_INDUSTRY_CODES]

    if not frees:
        df = pd.DataFrame(columns=col_keys + ["_row_idx"])
    else:
        rows_norm = []
        for idx, f in enumerate(frees, start=1):
            r = {}
            for k, _, _, _, ctype in FREE_GRID_COLUMNS:
                if k == "코드":
                    r[k] = str(f.get(k) or f"{idx:04d}")
                elif k == "소득구분":
                    r[k] = _ind_label(f.get(k) or "940909")
                elif ctype.startswith("numeric"):
                    r[k] = int(f.get(k, 0) or 0)
                else:
                    r[k] = str(f.get(k, "") or "")
            r["_row_idx"] = idx - 1
            rows_norm.append(r)
        df = pd.DataFrame(rows_norm, columns=col_keys + ["_row_idx"])

    gb = GridOptionsBuilder.from_dataframe(df)
    gb.configure_default_column(
        resizable=True,
        sortable=True,
        filter=False,
        suppressMenu=True,
    )
    gb.configure_selection(
        selection_mode="multiple",
        use_checkbox=False,
        suppressRowClickSelection=True,
    )
    gb.configure_column("_row_idx", hide=True)

    for field, header_name, width, editable, ctype in FREE_GRID_COLUMNS:
        pinned = "left" if field in ("코드", "성명") else None
        is_first_col = (field == "코드")
        if ctype == "select_mode":
            gb.configure_column(
                field,
                header_name=header_name,
                width=width,
                editable=editable,
                suppressMenu=True,
                cellEditor="agSelectCellEditor",
                cellEditorParams={"values": ["세전", "세후역산"]},
            )
        elif ctype == "select_ind":
            gb.configure_column(
                field,
                header_name=header_name,
                width=width,
                editable=editable,
                suppressMenu=True,
                cellEditor="agSelectCellEditor",
                cellEditorParams={"values": ind_codes},
                cellRenderer=JsCode(
                    "function(p){var v=(p.value==null)?'':String(p.value);"
                    "return v+'<span style=\"float:right;color:#64748b;\">▾</span>';}"
                ),
                tooltipField="소득구분",
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
                suppressMenu=True,
                type=["numericColumn"],
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
                checkboxSelection=is_first_col,
                headerCheckboxSelection=is_first_col,
                suppressMenu=True,
            )

    grid_opts = gb.build()
    grid_height = min(480, max(230, 58 + len(df) * 36))

    grid_resp = AgGrid(
        df,
        gridOptions=grid_opts,
        height=grid_height,
        update_mode=GridUpdateMode.VALUE_CHANGED | GridUpdateMode.SELECTION_CHANGED,
        allow_unsafe_jscode=True,
        theme="streamlit",
        key=f"pay_free_aggrid_{pstate.get('grid_version', 0)}",
    )

    pstate["selected_free_indices"] = _extract_selected_row_indices(grid_resp)
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
                    if k == "소득구분":
                        str_v = _ind_code_only(str_v)  # 화면 표시는 "940909 (기타자영업)", 저장은 코드 6자리
                    if str(orig.get(k, "") or "") != str_v:
                        changed = True
                    merged[k] = str_v
            new_frees.append(merged)
        if changed:
            pstate["freelancers"] = new_frees
            _recalculate_all_freelancer_rows(pstate)
            pstate["grid_version"] += 1
            st.rerun()


def _payslip_tpl_label(tpl_name: str) -> str:
    return f"급여명세서({tpl_name})"


def _render_employee_template_selector(pstate: Dict[str, Any], col_sel=None, col_mag=None) -> str:
    """급여명세서 양식 선택: [급여명세서(근로기준1) ▼] 드롭다운 + 오른쪽 돋보기(마우스 오버 시 선택한 양식 미리보기)."""
    cur_tpl = str(pstate.get("payslip_template") or "근로기준1")
    if cur_tpl not in PAYSLIP_TEMPLATE_OPTIONS:
        cur_tpl = "근로기준1"
    labels = [_payslip_tpl_label(t) for t in PAYSLIP_TEMPLATE_OPTIONS]
    with (col_sel or st.container()):
        sel_lbl = st.selectbox(
            "급여명세서 양식",
            options=labels,
            index=PAYSLIP_TEMPLATE_OPTIONS.index(cur_tpl),
            key="sel_pay_payslip_template",
            label_visibility="collapsed",
            help="기본: 급여명세서(근로기준1). 오른쪽 돋보기에 마우스를 올리면 선택한 양식 미리보기가 표시됩니다.",
        )
    tpl_name = PAYSLIP_TEMPLATE_OPTIONS[labels.index(sel_lbl)]
    pstate["payslip_template"] = tpl_name
    with (col_mag or st.container()):
        b64_png = get_payslip_template_preview_b64(tpl_name)
        if b64_png:
            st.markdown(
                f"<div class=\"pay-tpl-hover-wrap\" title=\"마우스를 올리면 {_payslip_tpl_label(tpl_name)} 미리보기가 표시됩니다\">"
                f"{MAGNIFIER_SVG}"
                f"<div class=\"pay-tpl-hover-popup\">"
                f"<div class=\"pay-tpl-hover-title\"><span>양식 미리보기 — {_payslip_tpl_label(tpl_name)}</span><span style=\"color:#2563eb;\">샘플</span></div>"
                f"<img src=\"data:image/png;base64,{b64_png}\" alt=\"{tpl_name}\" />"
                f"</div></div>",
                unsafe_allow_html=True,
            )
    return tpl_name


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

    # 1. 최상단 컨트롤 바 (사업소득 모드에서는 수당 계산기 2종 숨김 + 업종코드 조회·선택 버튼 노출)
    if is_emp_mode:
        top_c1, top_c2, top_c3, top_c4, top_c5, top_c6 = st.columns([1.40, 0.80, 1.05, 1.50, 1.50, 1.20], gap="small")
    else:
        top_c1, top_c2, top_c3, top_c4, top_c5 = st.columns([1.50, 0.90, 1.15, 1.60, 1.60], gap="small")

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
                    "사업장": _current_workplace_label(pstate),
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
        sel_indices = pstate.get("selected_emp_indices", []) if is_emp_mode else pstate.get("selected_free_indices", [])
        del_btn_lbl = f"선택한 행 삭제 ({len(sel_indices)}건)" if sel_indices else "선택한 행 삭제"
        if st.button(del_btn_lbl, width="stretch", key="btn_pay_del_row"):
            if is_emp_mode:
                if sel_indices:
                    drop_set = set(sel_indices)
                    pstate["employees"] = [
                        e for i, e in enumerate(pstate.get("employees", [])) if i not in drop_set
                    ]
                    pstate["selected_emp_indices"] = []
                    pstate["grid_version"] += 1
                    st.rerun()
                else:
                    st.warning("삭제할 행의 맨 왼쪽 체크박스를 먼저 선택해 주세요.")
            else:
                if sel_indices:
                    drop_set = set(sel_indices)
                    pstate["freelancers"] = [
                        f for i, f in enumerate(pstate.get("freelancers", [])) if i not in drop_set
                    ]
                    pstate["selected_free_indices"] = []
                    pstate["grid_version"] += 1
                    st.rerun()
                else:
                    st.warning("삭제할 대상자의 맨 왼쪽 체크박스를 먼저 선택해 주세요.")

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

    if is_emp_mode:
        with top_c5:
            if st.button("연장·야간·휴일근로수당 계산기", width="stretch", key="btn_pay_open_ot_calc"):
                _dlg_overtime_calculator()
        with top_c6:
            if st.button("주휴수당 계산기", width="stretch", key="btn_pay_open_wh_calc"):
                _dlg_weekly_holiday_calculator()
    else:
        with top_c5:
            if st.button("업종코드 조회·선택 (기본 940909)", width="stretch", key="btn_pay_open_ind_code"):
                _dlg_industry_code_selector()

    # 2. 메인 편집 표 (AG Grid 급여대장 / 사업소득대장)
    corp_disp = pstate.get("corp_name") or "거래처미입력"
    wp_disp = _current_workplace_label(pstate)
    ym_disp = pstate.get("year_month") or ""
    yymm_short = _format_yymm_4digit(ym_disp)
    c_safe = _sanitize_file_token(pstate.get("corp_name") or "거래처미입력", "거래처미입력")

    if is_emp_mode:
        wp_tag_str = f" · {wp_disp}" if wp_disp else ""
        st.markdown(
            f"<div style='display:flex; justify-content:space-between; align-items:center; margin-top:4px; margin-bottom:4px;'>"
            f"<span style='font-size:1.02rem; font-weight:800; color:#1e3a8a;'>급여대장 편집기 (4대보험 근로소득자 · {corp_disp}{wp_tag_str} · {ym_disp})</span>"
            f"<span style='font-size:0.82rem; color:#475569;'>좌측 체크박스 선택 후 [선택한 행 삭제] 가능 · 우측 끝 지급액계 이후 공제항목은 가로 스크롤</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
        _render_employee_aggrid(pstate)

        emps = pstate.get("employees", [])
        tot_gross = sum(int(e.get("지급액계", 0) or 0) for e in emps)
        tot_itax = sum(int(e.get("소득세", 0) or 0) for e in emps)
        tot_ltax = sum(int(e.get("지방소득세", 0) or 0) for e in emps)
        tot_ded = sum(int(e.get("공제액계", 0) or 0) for e in emps)
        tot_net = sum(int(e.get("차인지급액", 0) or 0) for e in emps)
        st.markdown(
            f"<div style='background:#f8fafc; border:1px solid #cbd5e1; border-radius:8px; padding:8px 14px; margin-bottom:10px; display:flex; flex-wrap:wrap; gap:12px; justify-content:space-between; font-size:0.90rem; color:#0f172a;'>"
            f"<span><b>총 인원:</b> {len(emps)}명</span>"
            f"<span><b>지급액계 합계:</b> {tot_gross:,}원</span>"
            f"<span><b>소득세 합계:</b> {tot_itax:,}원 · <b>지방소득세 합계:</b> {tot_ltax:,}원</span>"
            f"<span><b>공제액계 합계:</b> {tot_ded:,}원</span>"
            f"<span style='color:#1e3a8a;'><b>차인지급액(실지급) 합계:</b> {tot_net:,}원</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

        # 3-A. 급여명세서 양식 선택 + 다운로드 바 (사용자 지정 파일명 규칙 적용)
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
                        f"현재 총 {len(emps)}명으로 1회 급여명세서 ZIP 압축 한도({EMP_ZIP_MAX}명)를 초과합니다. 우측에서 구간을 선택해 분할 다운로드해 주세요."
                    )
                with c_sel_emp:
                    sel_batch_lbl = st.selectbox("급여명세서 ZIP 다운로드 구간", options=batch_options, key="emp_zip_batch_sel")
                    emp_start_idx = batch_options.index(sel_batch_lbl) * EMP_ZIP_MAX

            c_tpl, c_mag, dl_pdf, dl_img, dl_led, dl_xls, dl_enc = st.columns(
                [1.6, 0.28, 1.55, 1.6, 1.15, 1.45, 1.0], gap="small", vertical_alignment="center"
            )
            selected_tpl = _render_employee_template_selector(pstate, c_tpl, c_mag)
            inc_cnt = min(EMP_ZIP_MAX, max(0, len(emps) - emp_start_idx))
            with dl_enc:
                enc_chk = st.checkbox(
                    "생년월일 6자리 암호",
                    value=bool(pstate.get("encrypt_payslip_zip", False)),
                    key="chk_pay_enc_birth",
                    help="체크 시 압축 파일 안의 각 급여명세서 PDF에 주민등록번호 앞 6자리(YYMMDD) 비밀번호가 설정됩니다.",
                )
                pstate["encrypt_payslip_zip"] = enc_chk
            with dl_pdf:
                # [급여명세서 일괄 다운(PDF), 압축] zip = 거래처명_급여명세서_YYMM.zip / 내부 = 근로자명_급여명세서_YYMM.pdf
                st.download_button(
                    label="급여명세서 일괄 다운(PDF), 압축",
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
                        template_type=selected_tpl,
                    ),
                    file_name=f"{c_safe}_급여명세서_{yymm_short}.zip",
                    mime="application/zip",
                    width="stretch",
                    disabled=(len(emps) == 0),
                    key="btn_dl_payslips_zip",
                    help=f"{inc_cnt}명의 급여명세서 PDF를 zip 파일 하나로 내려받습니다.",
                )
            with dl_img:
                # [급여명세서 일괄 다운(이미지), 개별] = 근로자명_급여명세서_YYMM.jpg 를 압축 없이 각각 한 번에
                if st.button(
                    "급여명세서 일괄 다운(이미지), 개별",
                    width="stretch",
                    disabled=(len(emps) == 0),
                    key="btn_dl_payslips_jpg_each",
                    help=f"{inc_cnt}명의 급여명세서 이미지(JPG)를 압축 없이 각각 한 번에 내려받습니다.",
                ):
                    with st.spinner("급여명세서 이미지를 만드는 중..."):
                        files = _zip_bytes_to_files(export_employee_payslips_jpg_zip(
                            employees=emps,
                            corp_name=pstate.get("corp_name", ""),
                            year_month=ym_disp,
                            pay_date=pstate.get("pay_date", ""),
                            start_index=emp_start_idx,
                            max_count=EMP_ZIP_MAX,
                            template_type=selected_tpl,
                        ))
                    _trigger_multi_download(files, "image/jpeg", "emp_jpg")
            with dl_led:
                # [급여대장 다운(PDF)] = 거래처명_급여대장_YYMM.pdf
                st.download_button(
                    label="급여대장 다운(PDF)",
                    data=_lazy_bytes(
                        export_payroll_ledger_pdf,
                        enabled=bool(emps),
                        employees=emps,
                        corp_name=pstate.get("corp_name", ""),
                        year_month=ym_disp,
                        pay_date=pstate.get("pay_date", ""),
                    ),
                    file_name=f"{c_safe}_급여대장_{yymm_short}.pdf",
                    mime="application/pdf",
                    width="stretch",
                    disabled=(len(emps) == 0),
                    key="btn_dl_payroll_ledger_pdf",
                )
            with dl_xls:
                # [위하고 급여 업로드 양식(.xlsx)] = 거래처명_위하고 업로드 양식_YYMM.xlsx ('사업장' 열 자동 제외)
                st.download_button(
                    label="위하고 급여 업로드 양식(.xlsx)",
                    data=_lazy_bytes(export_wehago_payroll_excel, emps),
                    file_name=f"{c_safe}_위하고 업로드 양식_{yymm_short}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    width="stretch",
                    disabled=(len(emps) == 0),
                    key="btn_dl_wehago_emp_xlsx",
                )
    else:
        st.markdown(
            f"<div style='display:flex; justify-content:space-between; align-items:center; margin-top:4px; margin-bottom:4px;'>"
            f"<span style='font-size:1.02rem; font-weight:800; color:#4c1d95;'>사업소득대장 편집기 (3.3% 프리랜서 · {corp_disp} · {ym_disp})</span>"
            f"<span style='font-size:0.82rem; color:#475569;'>업종코드 기본값 940909 · 상단 [업종코드 조회·선택] 또는 셀 클릭으로 변경 가능</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
        _render_freelancer_aggrid(pstate)

        frees = pstate.get("freelancers", [])
        tot_fgross = sum(int(f.get("지급총액", 0) or 0) for f in frees)
        tot_fitax = sum(int(f.get("소득세", 0) or 0) for f in frees)
        tot_fltax = sum(int(f.get("지방소득세", 0) or 0) for f in frees)
        tot_fded = sum(int(f.get("공제액계", 0) or 0) for f in frees)
        tot_fnet = sum(int(f.get("차인지급액", 0) or 0) for f in frees)
        st.markdown(
            f"<div style='background:#faf5ff; border:1px solid #d8b4fe; border-radius:8px; padding:8px 14px; margin-bottom:10px; display:flex; flex-wrap:wrap; gap:12px; justify-content:space-between; font-size:0.90rem; color:#1e1b4b;'>"
            f"<span><b>총 인원:</b> {len(frees)}명</span>"
            f"<span><b>지급총액(세전) 합계:</b> {tot_fgross:,}원</span>"
            f"<span><b>소득세(3%) 합계:</b> {tot_fitax:,}원 · <b>지방소득세(0.3%) 합계:</b> {tot_fltax:,}원 (계 {tot_fded:,}원)</span>"
            f"<span style='color:#4c1d95;'><b>차인지급액(실지급) 합계:</b> {tot_fnet:,}원</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

        # 3-B. 사업소득 모드 다운로드 바 (사용자 지정 파일명 규칙 + [사업소득명세서 PDF 압축] 우측 돋보기 호버 미리보기)
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
                        f"현재 총 {len(frees)}명으로 1회 사업소득명세서(PDF/JPG) ZIP 압축 한도({FREE_ZIP_MAX}명)를 초과합니다. 우측에서 구간을 선택해 분할 다운로드해 주세요."
                    )
                with c_sel_fr:
                    sel_fbatch_lbl = st.selectbox("사업소득명세서 ZIP 다운로드 구간", options=f_batch_options, key="free_zip_batch_sel")
                    free_start_idx = f_batch_options.index(sel_fbatch_lbl) * FREE_ZIP_MAX

            f_inc_cnt = min(FREE_ZIP_MAX, max(0, len(frees) - free_start_idx))
            fp_btn, fp_mag, fi_btn, fi_mag, f_led, f_xls = st.columns(
                [1.75, 0.28, 1.8, 0.28, 1.3, 1.6], gap="small", vertical_alignment="center"
            )
            free_b64 = get_freelancer_statement_preview_b64()

            def _free_mag() -> None:
                if free_b64:
                    st.markdown(
                        "<div class=\"pay-tpl-hover-wrap\" title=\"마우스를 올리면 사업소득명세서 양식 미리보기가 표시됩니다\">"
                        f"{MAGNIFIER_SVG}"
                        "<div class=\"pay-tpl-hover-popup\"><div class=\"pay-tpl-hover-title\"><span>사업소득명세서 양식 미리보기</span>"
                        "<span style=\"color:#7c3aed;\">샘플</span></div>"
                        f"<img src=\"data:image/png;base64,{free_b64}\" alt=\"사업소득명세서 미리보기\" /></div></div>",
                        unsafe_allow_html=True,
                    )

            free_kw = dict(
                freelancers=frees,
                corp_name=pstate.get("corp_name", ""),
                year_month=ym_disp,
                pay_date=pstate.get("pay_date", ""),
                start_index=free_start_idx,
                max_count=FREE_ZIP_MAX,
            )
            with fp_btn:
                # [사업소득명세서 일괄 다운(PDF), 개별] = 근로자명_사업소득명세서_YYMM.pdf 를 압축 없이 각각 한 번에
                if st.button(
                    "사업소득명세서 일괄 다운(PDF), 개별",
                    width="stretch",
                    disabled=(len(frees) == 0),
                    key="btn_dl_free_pdf_each",
                    help=f"{f_inc_cnt}명의 사업소득명세서 PDF를 압축 없이 각각 한 번에 내려받습니다.",
                ):
                    with st.spinner("사업소득명세서 PDF를 만드는 중..."):
                        files = _zip_bytes_to_files(export_freelancer_statements_pdf_zip(**free_kw))
                    _trigger_multi_download(files, "application/pdf", "free_pdf")
            with fp_mag:
                _free_mag()
            with fi_btn:
                # [사업소득명세서 일괄 다운(이미지), 개별] = 근로자명_사업소득명세서_YYMM.jpg 를 압축 없이 각각 한 번에
                if st.button(
                    "사업소득명세서 일괄 다운(이미지), 개별",
                    width="stretch",
                    disabled=(len(frees) == 0),
                    key="btn_dl_free_jpg_each",
                    help=f"{f_inc_cnt}명의 사업소득명세서 이미지(JPG)를 압축 없이 각각 한 번에 내려받습니다.",
                ):
                    with st.spinner("사업소득명세서 이미지를 만드는 중..."):
                        files = _zip_bytes_to_files(export_freelancer_statements_jpg_zip(**free_kw))
                    _trigger_multi_download(files, "image/jpeg", "free_jpg")
            with fi_mag:
                _free_mag()
            with f_led:
                # [사업소득대장 다운(PDF)] = 거래처명_사업소득대장_YYMM.pdf
                st.download_button(
                    label="사업소득대장 다운(PDF)",
                    data=_lazy_bytes(
                        export_freelancer_ledger_pdf,
                        enabled=bool(frees),
                        freelancers=frees,
                        corp_name=pstate.get("corp_name", ""),
                        year_month=ym_disp,
                    ),
                    file_name=f"{c_safe}_사업소득대장_{yymm_short}.pdf",
                    mime="application/pdf",
                    width="stretch",
                    disabled=(len(frees) == 0),
                    key="btn_dl_free_ledger_pdf",
                )
            with f_xls:
                # [위하고 사업소득 업로드 양식(.xlsx)] = 거래처명_위하고 업로드양식_YYMM.xlsx
                st.download_button(
                    label="위하고 사업소득 업로드 양식(.xlsx)",
                    data=_lazy_bytes(
                        export_wehago_freelancer_excel,
                        freelancers=frees,
                        default_year_month=ym_disp,
                        default_pay_date=pstate.get("pay_date", ""),
                    ),
                    file_name=f"{c_safe}_위하고 업로드양식_{yymm_short}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    width="stretch",
                    disabled=(len(frees) == 0),
                    key="btn_dl_wehago_free_xlsx",
                )

    if pstate.get("chat_logs"):
        with st.expander(f"최근 자동 반영 내역 로그 ({len(pstate['chat_logs'])}건)", expanded=False):
            for lg in reversed(pstate["chat_logs"][-12:]):
                st.markdown(f"- {lg}")

    # 4. 최하단 올인원 입력창 (파일 드래그앤드롭과 내용 입력을 최하단 한 곳으로 일원화)
    bottom_placeholder = (
        "급여대장·4대보험 고지서(엑셀·PDF·사진·.paybak)를 이 칸에 끌어다 놓거나 카톡 급여 내역(예: 홍길동 실수령 280만원)을 입력하세요"
        if is_emp_mode
        else "사업소득대장(엑셀·PDF·사진·.paybak)을 이 칸에 끌어다 놓거나 내역(예: 홍길동, 950101-*******, 세후 300만원)을 입력하세요"
    )
    _chat_sig = inspect.signature(st.chat_input).parameters
    try:
        if "accept_file" in _chat_sig:
            chat_val = st.chat_input(
                bottom_placeholder,
                accept_file="multiple",
                file_type=["xlsx", "xls", "pdf", "png", "jpg", "jpeg", "paybak"],
                key="pay_bottom_all_in_one_input",
            )
        else:
            chat_val = st.chat_input(
                bottom_placeholder,
                key="pay_bottom_all_in_one_input",
            )
    except Exception:
        chat_val = st.chat_input(
            bottom_placeholder,
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
