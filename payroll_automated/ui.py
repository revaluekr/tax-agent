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
import hashlib
import re
from datetime import datetime
from zoneinfo import ZoneInfo
_KST = ZoneInfo("Asia/Seoul")   # 한국 표준시(KST)
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st
import ui_theme as _ui_theme
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, JsCode

from .backup import (
    build_employment_credit_bridge_payload,
    build_year_month_coverage_notice,
    create_empty_client_db,
    BackupPasswordError,
    decrypt_paybak_to_client_db,
    decrypt_paybak_with_info,
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
    export_review_report_pdf,
    export_wehago_freelancer_excel,
    export_wehago_payroll_excel,
    get_freelancer_statement_preview_b64,
    get_freelancer_receipt_preview_b64,
    get_payslip_template_preview_b64,
)
from .ai_tax_review import build_emp_payload, build_free_payload, run_ai_tax_review
from .ai_tax_review import payload_hash as ai_payload_hash
from .parsers import (
    FREELANCER_INDUSTRY_CODES,
    _call_gemini_contents,
    apply_chat_modifiers_to_state,
    apply_insurance_notices_to_employees,
    extract_full_rrn,
    extract_universal_document_text_and_rows,
    mask_rrn_front7,
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

/* 통합고용세액공제와 동일한 사이드바 법령·예규 모니터링 3D 입체 원형 표시등 및 상태줄 */
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
/* 기존 호환 클래스 유지 */
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
    font-size: 1.22rem !important;
    font-weight: 800 !important;
    color: #191F28 !important;
    background: linear-gradient(90deg, #E8F3FF 0%, #F5F9FF 72%, #FFFFFF 100%) !important;
    border-left: 4.5px solid #3182F6 !important;
    padding: 9px 14px !important;
    margin-top: 1.4rem !important;
    margin-bottom: 0.75rem !important;
    border-radius: 10px !important;
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
        "<div></div>"
        "<script>"
        f"const FILES={payload};const MIME={_json.dumps(mime)};"
        "async function go(){for(const f of FILES){const bin=atob(f.d);const arr=new Uint8Array(bin.length);"
        "for(let i=0;i<bin.length;i++){arr[i]=bin.charCodeAt(i);}"
        "const url=URL.createObjectURL(new Blob([arr],{type:MIME}));const a=document.createElement('a');"
        "a.href=url;a.download=f.n;document.body.appendChild(a);a.click();a.remove();"
        "setTimeout(()=>URL.revokeObjectURL(url),8000);await new Promise(r=>setTimeout(r,250));}}"
        "go();"
        "</script>"
    )
    # 화면 배치를 바꾸지 않도록 내려받기용 숨김 프레임만 넣고(버튼 위치 고정), 안내는 오른쪽 아래 알림으로 표시
    with st.container(key=f"pay_mdl_{key}"):
        st.markdown(
            f"<style>.st-key-pay_mdl_{key},div:has(> .st-key-pay_mdl_{key}){{position:absolute !important;left:-9999px;"
            f"width:1px !important;height:1px !important;margin:0 !important;padding:0 !important;"
            f"overflow:hidden;opacity:0;pointer-events:none;}}</style>",
            unsafe_allow_html=True,
        )
        st.iframe(html, height=1)
    st.toast(
        f"{len(files)}개 파일 다운로드를 시작했습니다. 브라우저가 '여러 파일 다운로드'를 물으면 [허용]을 눌러 주세요.",
        icon=":material/download:",
    )


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
    now = datetime.now(_KST)
    return f"{now.year % 100:02d}{now.month:02d}"


def _get_payroll_state() -> Dict[str, Any]:
    if "payroll_auto_state" not in st.session_state:
        now = datetime.now(_KST)
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


def _reset_payroll_current_work(which: str = "ALL") -> None:
    """작업 자료 초기화 — which: "EMP"(급여명세서만) / "FREE"(사업소득만) / "ALL"(둘 다).
    급여명세서와 사업소득은 서로 영향을 주지 않도록 지금 보고 있는 화면의 자료만 비웁니다."""
    pstate = _get_payroll_state()
    if which in ("EMP", "ALL"):
        pstate["employees"] = []
        pstate["selected_emp_indices"] = []
    if which in ("FREE", "ALL"):
        pstate["freelancers"] = []
        pstate["selected_free_indices"] = []
    if which == "ALL" or not (pstate.get("employees") or pstate.get("freelancers")):
        pstate["notice_logs"] = []
        pstate["chat_logs"] = []
    pstate["grid_version"] = int(pstate.get("grid_version", 0)) + 1


def _normalize_pay_date(v: str) -> str:
    """지급일자 입력값 정리: 20261125 / 2026.11.25 / 2026-11-25 → 2026-11-25 (형식이 다르면 입력 그대로)"""
    t = str(v or "").strip()
    d = re.sub(r"[^0-9]", "", t)
    if len(d) == 8:
        return f"{d[:4]}-{d[4:6]}-{d[6:]}"
    return t


def _apply_period_to_rows(pstate: Dict[str, Any]) -> None:
    """왼쪽 사업자정보의 귀속연월·지급일자를 이미 올린 사업소득 행에도 반영 (자료를 먼저 올리든 나중에 올리든 같은 결과)"""
    ym = str(pstate.get("year_month") or "")
    pd_v = str(pstate.get("pay_date") or "")
    for fr in pstate.get("freelancers", []) or []:
        if ym:
            fr["귀속년월"] = ym
        if pd_v:
            fr["지급년월일"] = pd_v
    pstate["grid_version"] = int(pstate.get("grid_version", 0)) + 1


def _set_period_from_file(pstate: Dict[str, Any], ym: str, pay_date: str = "") -> None:
    """업로드한 파일의 귀속연월로 맞춤 — 단, 왼쪽 사업자정보에서 직접 입력한 귀속연월·지급일자가 있으면 그 값을 우선"""
    if pstate.get("_period_user_set") or not ym:
        return
    pstate["year_month"] = ym
    pstate["pay_date"] = pay_date or f"{ym}-25"
    pstate["effective_table"] = "2026.03" if ym >= "2026-03" else "2024.03"


def _on_sidebar_year_month_change() -> None:
    pstate = _get_payroll_state()
    ym = str(st.session_state.get("pay_sb_year_month") or "").strip()
    if not ym:
        return
    pstate["_period_user_set"] = True
    pstate["year_month"] = ym
    pstate["pay_date"] = f"{ym}-25"
    st.session_state["pay_sb_pay_date"] = pstate["pay_date"]
    pstate["effective_table"] = "2026.03" if ym >= "2026-03" else "2024.03"
    _recalculate_all_employee_rows(pstate)
    _apply_period_to_rows(pstate)


def _on_sidebar_pay_date_change() -> None:
    pstate = _get_payroll_state()
    pd_v = _normalize_pay_date(st.session_state.get("pay_sb_pay_date"))
    pstate["_period_user_set"] = True
    pstate["pay_date"] = pd_v
    st.session_state["pay_sb_pay_date"] = pd_v
    _apply_period_to_rows(pstate)


def _recalculate_all_employee_rows(pstate: Dict[str, Any]) -> None:
    eff_tbl = pstate.get("effective_table", "2026.03")
    ym_cur = pstate.get("year_month") or None
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
                income_tax_reduction_pct=float(emp.get("소득세감면율", 0) or 0),
                year_month=ym_cur,
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
            income_tax_reduction_pct=float(emp.get("소득세감면율", 0) or 0),
            year_month=ym_cur,
        )
        emp.update(calc)
        if emp.get("주민등록번호") or emp.get("_raw_rrn"):
            raw_cand = str(emp.get("주민등록번호") or "")
            if raw_cand and "*" not in raw_cand:
                emp["_raw_rrn"] = extract_full_rrn(raw_cand)
            elif not emp.get("_raw_rrn"):
                emp["_raw_rrn"] = extract_full_rrn(raw_cand)
            emp["주민등록번호"] = mask_rrn_front7(emp.get("_raw_rrn") or raw_cand)
        if "사업장" not in emp:
            emp["사업장"] = wp_lbl
        if not emp.get("사원코드"):
            emp["사원코드"] = f"{idx:03d}"
        new_list.append(emp)
    pstate["employees"] = new_list


def _recalculate_all_freelancer_rows(pstate: Dict[str, Any]) -> None:
    """
    [프리랜서 세전/세후 정밀 재계산]
    - 파일 업로드 시점(또는 수기 수정 시점)의 기준 금액(`_base_amount`)을 보존하여,
      1) '세전'일 때는 `_base_amount`가 그대로 '지급총액'이 되어 3.3%를 공제하고,
      2) '세후역산'일 때는 `_base_amount`가 그대로 '차인지급액(실지급액)'이 되어 지급총액을 역산합니다.
    """
    new_list: List[Dict[str, Any]] = []
    for idx, fr in enumerate(pstate.get("freelancers", []), start=1):
        in_mode = str(fr.get("입력기준", "세전")).strip()
        base_amt = int(fr.get("_base_amount") or 0)
        if base_amt <= 0:
            if in_mode == "세후역산":
                base_amt = int(fr.get("차인지급액", 0) or fr.get("지급총액", 0) or 0)
            else:
                base_amt = int(fr.get("지급총액", 0) or fr.get("차인지급액", 0) or 0)
            fr["_base_amount"] = base_amt

        if in_mode == "세후역산":
            calc = solve_gross_from_net_freelancer(base_amt)
        else:
            calc = calculate_freelancer_row(base_amt)

        fr["지급총액"] = calc["gross_pay"]
        fr["세율"] = 3
        fr["소득세"] = calc["income_tax"]
        fr["지방소득세"] = calc["local_tax"]
        fr["공제액계"] = calc["total_deduction"]
        fr["차인지급액"] = calc["net_pay"]
        if fr.get("주민등록번호") or fr.get("_raw_rrn"):
            raw_cand = str(fr.get("주민등록번호") or "")
            if raw_cand and "*" not in raw_cand:
                fr["_raw_rrn"] = extract_full_rrn(raw_cand)
            elif not fr.get("_raw_rrn"):
                fr["_raw_rrn"] = extract_full_rrn(raw_cand)
            fr["주민등록번호"] = mask_rrn_front7(fr.get("_raw_rrn") or raw_cand)
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
    k2.metric("월 환산 주휴수당 (월 209시간 기준)", f"{res['monthly_holiday_pay']:,}원")
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
    ym = pstate.get("year_month") or datetime.now(_KST).strftime("%Y-%m")
    pay_dt = pstate.get("pay_date") or ""
    return corp_disp, ym, pay_dt


def _won(v: Any) -> str:
    return f"{int(v or 0):,}원"


def _build_emp_review_report(pstate: Dict[str, Any]) -> Dict[str, Any]:
    """급여 검토보고 내용(화면·PDF 공통)."""
    emps = pstate.get("employees", [])
    corp_disp, ym, pay_dt = _report_header_common(pstate)
    diag = analyze_payroll_warnings(employees=emps, freelancers=[], prev_employees=pstate.get("prev_employees", []), prev_freelancers=[])
    sm = lambda k: sum(int(e.get(k, 0) or 0) for e in emps)
    tot_ins = sm("국민연금") + sm("건강보험") + sm("장기요양보험료") + sm("고용보험")
    tot_settle = sm("건강보험료정산") + sm("장기요양보험료정산") + sm("국민연금정산")
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
            year_month=str(ym or ""),
        )
        for k in own:
            own[k] += int(r_own.get(k, 0) or 0)
    mv = diag["movement_summary"]
    j = lambda xs: ", ".join(xs) if xs else "해당 없음"
    reduced = [e for e in emps if float(e.get("소득세감면율", 0) or 0) > 0]
    sections = [
        {"heading": f"[{corp_disp}] {ym} 귀속 급여 및 원천징수 검토 요약",
         "intro": f"지급일: {pay_dt or '미입력'} · 근로소득자 {len(emps)}명",
         "headers": ["지급액계", "비과세", "과세급여", "4대보험 공제", "소득세", "지방소득세", "공제액계", "차인지급액(실지급)"],
         "widths": [11.9] * 7 + [16.7],
         "rows": [[_won(sm("지급액계")), _won(sm("비과세합계")), _won(sm("과세급여")), _won(tot_ins + tot_settle),
                   _won(sm("소득세")), _won(sm("지방소득세")), _won(sm("공제액계")), _won(sm("차인지급액"))]],
         "notes": ([f"4대보험 공제에는 정산분 {tot_settle:,}원이 포함되어 있습니다."] if tot_settle else [])
         + ([f"소득세 감면 적용: {len(reduced)}명 (감면율만큼 간이세액에서 차감)"] if reduced else [])},
        {"heading": "사업주 부담 4대보험 추정 (산재보험 제외)",
         "headers": ["국민연금", "건강보험", "장기요양", "고용보험", "사업주 부담 합계"],
         "widths": [18.5] * 4 + [26.0],
         "rows": [[_won(own["국민연금_사업주"]), _won(own["건강보험_사업주"]), _won(own["장기요양_사업주"]),
                   _won(own["고용보험_사업주"]), _won(own["합계_사업주"])]],
         "notes": [f"국민연금·건강·장기요양은 근로자 부담분(고지 반영 시 고지 금액)과 같은 금액이며, 고용보험은 과세급여 × (실업급여 0.9% + 고용안정·직능 "
                   f"{tier_lbl.split('·')[-1].strip()})로 추정했습니다 (대표이사·고용보험 0원 대상자 제외, 정산분 미포함)."]},
        {"heading": "전월 대비 인원 변동 및 4대보험 신고 대상",
         "bullets": [("신규 입사 (자격취득신고 대상)", j(mv.get("new_hires"))),
                     ("퇴사·제외 (자격상실신고 대상)", j(mv.get("retirees"))),
                     ("전월 대비 급여 20% 이상 변동자", j(mv.get("pay_changes")))]},
    ]
    return {"title": "당월 급여 검토보고 (4대보험 근로소득자)", "kind": "급여", "accent": "#1e3a8a", "sections": sections}


def _build_free_review_report(pstate: Dict[str, Any]) -> Dict[str, Any]:
    """사업소득 검토보고 내용(화면·PDF 공통)."""
    frees = pstate.get("freelancers", [])
    prev = pstate.get("prev_freelancers", []) or []
    corp_disp, ym, pay_dt = _report_header_common(pstate)
    sm = lambda k: sum(int(f.get(k, 0) or 0) for f in frees)
    by_code: Dict[str, List[Dict[str, Any]]] = {}
    for f in frees:
        by_code.setdefault(_ind_code_only(f.get("소득구분") or "940909"), []).append(f)
    cur_names = {str(f.get("성명") or "").strip() for f in frees if str(f.get("성명") or "").strip()}
    prev_names = {str(f.get("성명") or "").strip() for f in prev if str(f.get("성명") or "").strip()}
    j = lambda xs: ", ".join(sorted(xs)) if xs else "해당 없음"
    sections = [
        {"heading": f"[{corp_disp}] {ym} 귀속 사업소득 지급 및 원천징수 검토 요약",
         "intro": f"지급일: {pay_dt or '미입력'} · 사업소득자 {len(frees)}명",
         "headers": ["지급총액(세전)", "소득세(3%)", "지방소득세(0.3%)", "원천징수 합계", "차인지급액(실지급)"],
         "widths": [18.5] * 4 + [26.0],
         "rows": [[_won(sm("지급총액")), _won(sm("소득세")), _won(sm("지방소득세")), _won(sm("공제액계")), _won(sm("차인지급액"))]]},
        {"heading": "업종코드별 지급 현황",
         "headers": ["업종코드(내용)", "인원", "지급총액"],
         "widths": [45.0, 20.0, 35.0],
         "rows": [[_ind_label(c), f"{len(fs)}명", _won(sum(int(f.get('지급총액', 0) or 0) for f in fs))] for c, fs in sorted(by_code.items())]},
        {"heading": "전월 대비 지급 대상 변동",
         "bullets": ([("신규 지급 대상", j(cur_names - prev_names)), ("전월 지급, 당월 미지급", j(prev_names - cur_names))]
                     if prev_names else []),
         "intro": "" if prev_names else "전월 누적 자료가 없어 비교하지 않았습니다."},
    ]
    return {"title": "당월 사업소득 검토보고 (3.3% 사업소득자)", "kind": "사업소득", "accent": "#4c1d95", "sections": sections}


def _render_review_report_html(rep: Dict[str, Any]) -> str:
    """검토보고 화면(B안): 구역 제목 왼쪽 색 막대 · 연한 회색 표 머리 · 마지막 금액 칸 강조 · 인원 변동은 작은 카드 3칸."""
    acc = rep.get("accent") or "#1e3a8a"
    parts = [f"<div class='pay-modal-scroll-box'><div class='rpx-box' style='--rpx-acc:{acc};'>"]
    for sec in rep["sections"]:
        parts.append(f"<div class='rpx-h'>{sec['heading']}</div>")
        if sec.get("intro"):
            parts.append(f"<div class='rpx-intro'>{sec['intro']}</div>")
        if sec.get("headers"):
            cols = "".join(f"<col style='width:{w}%'>" for w in sec["widths"])
            head = "".join(f"<th>{h}</th>" for h in sec["headers"])
            body = ""
            for r in sec["rows"]:
                tds = []
                for ci, v in enumerate(r):
                    is_last = ci == len(r) - 1
                    align = "left" if sec.get("align") == "left" else ("center" if not str(v).endswith("원") else "right")
                    strong = is_last and len(sec["rows"]) == 1 and align != "left"
                    tds.append(f"<td class='{'rpx-strong' if strong else ''}' style='text-align:{align};'>{v}</td>")
                body += "<tr>" + "".join(tds) + "</tr>"
            parts.append(f"<table class='rpx-tbl'><colgroup>{cols}</colgroup><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>")
        for n in sec.get("notes", []):
            parts.append(f"<div class='rpx-note'>{n}</div>")
        if sec.get("bullets"):
            if sec.get("cards") or (len(sec["bullets"]) == 3 and not sec.get("headers") and "인원 변동" in str(sec.get("heading"))):
                parts.append("<div class='rpx-cards'>" + "".join(
                    f"<div class='rpx-card'><div class='k'>{k}</div><div class='v'>{v}</div></div>" for k, v in sec["bullets"]) + "</div>")
            else:
                parts.append("<ul class='rpx-ul'>" + "".join(f"<li><b>{k}:</b> {v}</li>" for k, v in sec["bullets"]) + "</ul>")
    parts.append("</div></div>")
    return _report_html(parts)


def _render_review_report_buttons(pstate: Dict[str, Any], rep: Dict[str, Any], key: str, ai_kind: Optional[str] = None) -> None:
    """보고서 하단: [PDF 다운] [닫기]  ……  [AI 맞춤 절세 검토]
    파일명 '거래처명_당월 급여검토보고_YYMM.pdf' / '거래처명_당월 사업소득검토보고_YYMM.pdf' / '거래처명_AI 맞춤 절세검토_YYMM.pdf'."""
    corp = (pstate.get("corp_name") or "거래처").strip().replace(" ", "")
    ym_digits = re.sub(r"[^0-9]", "", str(pstate.get("year_month") or ""))
    yymm = ym_digits[2:6] if len(ym_digits) >= 6 else datetime.now(_KST).strftime("%y%m")
    if rep["kind"] == "AI절세":
        fname = f"{corp}_AI 맞춤 절세검토({'급여' if key.endswith('emp') else '사업소득'})_{yymm}.pdf"
    else:
        fname = f"{corp}_당월 {rep['kind']}검토보고_{yymm}.pdf"
    if ai_kind:
        c_pdf, c_close, _sp, c_cap, c_ai = st.columns([1, 0.8, 0.6, 1.5, 1.6], gap="small", vertical_alignment="center")
        c_cap.markdown("<div class='rpx-ai-cap'>이름·주민번호 없이 검토해요</div>", unsafe_allow_html=True)
        with c_ai:
            if st.button("AI 맞춤 절세 검토", icon=":material/auto_awesome:", width="stretch", key=f"btn_ai_saving_{key}",
                         help="직원 구성·급여 자료를 AI가 정해진 법령 범위 안에서 검토해 절세 방안을 보고서로 보여 줍니다. 이름·주민번호는 보내지 않습니다."):
                st.session_state["pa_ai_saving_open"] = ai_kind
                st.rerun()
    else:
        c_pdf, c_close = st.columns([1, 1], gap="small")
    with c_pdf:
        st.download_button(
            "PDF 다운",
            data=_lazy_bytes(export_review_report_pdf, rep),
            file_name=fname,
            mime="application/pdf",
            width="stretch",
            key=f"btn_dl_review_pdf_{key}",
        )
    with c_close:
        if st.button("닫기", width="stretch", key=f"btn_close_monthly_rep_{key}"):
            st.rerun()


@st.dialog("당월 급여 검토보고 (4대보험 근로소득자)", width="large")
def _dlg_monthly_review_report_emp():
    """급여명세서 화면 전용 검토보고 — 사업소득자는 포함하지 않습니다."""
    pstate = _get_payroll_state()
    rep = _build_emp_review_report(pstate)
    st.markdown(_render_review_report_html(rep), unsafe_allow_html=True)
    _render_review_report_buttons(pstate, rep, "emp", ai_kind="emp")


@st.dialog("당월 사업소득 검토보고 (3.3% 사업소득자)", width="large")
def _dlg_monthly_review_report_free():
    """사업소득 화면 전용 검토보고 — 근로소득자 내용은 포함하지 않습니다."""
    pstate = _get_payroll_state()
    rep = _build_free_review_report(pstate)
    st.markdown(_render_review_report_html(rep), unsafe_allow_html=True)
    _render_review_report_buttons(pstate, rep, "free", ai_kind="free")


def _ai_log_tokens(model_id: str, in_tok: int, out_tok: int, *_a) -> None:
    try:
        import agent
        if hasattr(agent, "_record_token_usage"):
            agent._record_token_usage(model_id, int(in_tok or 0), int(out_tok or 0), count_call=True)
    except Exception:
        pass


def _ai_call_text(prompt: str) -> str:
    return _call_gemini_contents([prompt], explicit_api_key=st.session_state.get("_pa_explicit_key"), log_tokens_fn=_ai_log_tokens)


@st.dialog("AI 맞춤 절세 검토", width="large")
def _dlg_ai_tax_review():
    """[AI 맞춤 절세 검토] — 같은 자료면 저장된 결과를 다시 보여 줘 토큰을 쓰지 않습니다."""
    pstate = _get_payroll_state()
    kind = st.session_state.get("pa_ai_saving_kind", "emp")
    corp_disp, ym, _pay = _report_header_common(pstate)
    payload, _ids = (build_emp_payload if kind == "emp" else build_free_payload)(pstate)
    h = ai_payload_hash(kind, payload)
    cache = st.session_state.setdefault("pa_ai_saving_cache", {})
    rep = cache.get(h)
    if rep is None:
        with st.spinner("AI가 직원 구성과 급여 자료를 검토하고 있습니다… (보통 10~40초)"):
            rep, err = run_ai_tax_review(kind, pstate, {"corp": corp_disp, "ym": ym}, _ai_call_text)
        if rep is None:
            st.warning(err)
            c1, c2 = st.columns([1, 1], gap="small")
            with c1:
                if st.button("다시 시도", width="stretch", key=f"btn_ai_retry_{kind}"):
                    st.rerun(scope="fragment")
            with c2:
                if st.button("닫기", type="primary", width="stretch", key=f"btn_ai_close_err_{kind}"):
                    st.rerun()
            return
        cache[h] = rep
    st.markdown(_render_review_report_html(rep), unsafe_allow_html=True)
    _render_review_report_buttons(pstate, rep, f"ai_{kind}")


# ─────────────────────────────────────────────────────────────
# 좌측 사이드바 렌더링 (인건비 자동화 모드)
# ─────────────────────────────────────────────────────────────

def render_payroll_automated_sidebar() -> None:
    st.markdown(PAYROLL_CSS, unsafe_allow_html=True)
    pstate = _get_payroll_state()
    is_emp_mode = pstate.get("sub_mode", "EMP") == "EMP"

    # (1) 최상단 카드: 업무 화면 선택 ([급여명세서] 파스텔 블루 / [사업소득] 파스텔 퍼플 — 개정사항 모니터링보다 위에 배치)
    with st.container(border=True):
        st.markdown(_ui_theme.sb_title("grid", "업무 화면"), unsafe_allow_html=True)
        _seg = st.container(key="sbx_pay_seg")
        col_emp, col_free = _seg.columns(2, gap="small")
        with col_emp:
            emp_key = "btn_pay_submode_emp_active" if is_emp_mode else "btn_pay_submode_emp"
            if st.button("급여명세서", key=emp_key, width="stretch"):
                pstate["sub_mode"] = "EMP"
                st.session_state["pay_confirm_reset"] = False   # 화면을 바꾸면 초기화 확인창 닫기 (다른 화면 자료가 지워지지 않도록)
                st.rerun()
        with col_free:
            free_key = "btn_pay_submode_free_active" if not is_emp_mode else "btn_pay_submode_free"
            if st.button("사업소득", key=free_key, width="stretch"):
                pstate["sub_mode"] = "FREE"
                st.session_state["pay_confirm_reset"] = False   # 화면을 바꾸면 초기화 확인창 닫기 (다른 화면 자료가 지워지지 않도록)
                st.rerun()

    # (2) 개정사항·신규 세법 카드 (통합고용세액공제와 동일한 3D 상태줄·아이콘 디자인 적용)
    alerts = check_payroll_law_revisions(force_refresh=False)
    row1_laws = [a for a in alerts if "별표" not in a.get("law", "") and "보험" not in a.get("law", "")]
    row2_laws = [a for a in alerts if "별표" in a.get("law", "") or "보험" in a.get("law", "")]
    row1_new = any(a.get("status") == "new_revision" for a in row1_laws)
    row2_new = any(a.get("status") == "new_revision" for a in row2_laws)
    row2_upd = any(a.get("status") in ("updated", "new_revision") for a in row2_laws) or True

    led_row1 = "orange" if row1_new else "green"
    led_row2 = "orange" if row2_new else ("yellow" if row2_upd else "green")
    badge_row1 = (
        "<span class='ec-law-badge-orange'>신규 개정 감지</span>"
        if row1_new
        else "<span class='ec-law-badge-green'>정상</span>"
    )
    badge_row2 = (
        "<span class='ec-law-badge-orange'>신규 개정 감지</span>"
        if row2_new
        else "<span class='ec-law-badge-orange'>2026.03 별표2·요율 반영</span>"
    )

    with st.expander("개정사항 · 신규 세법 (2026 법령 반영)", expanded=False):
        st.markdown(
            f"<div class='ec-law-status-row'>"
            f"<span class='ec-law-status-left'><span class='ec-law-led-3d {led_row1}'></span>근로기준법 · 소득세법</span>"
            f"{badge_row1}"
            f"</div>"
            f"<div class='ec-law-status-row' style='margin-bottom:8px;'>"
            f"<span class='ec-law-status-left'><span class='ec-law-led-3d {led_row2}'></span>시행령 별표2 · 4대보험 요율</span>"
            f"{badge_row2}"
            f"</div>",
            unsafe_allow_html=True,
        )
        if st.button(
            "상세 보기",
            width="stretch",
            key="btn_pay_law_detail",
            help="근로기준법·소득세법·시행령 별표2(간이세액표) 및 2026년 4대보험 고시 요율의 개정 내역과 원문을 확인합니다.",
        ):
            _dlg_payroll_law_revisions()

    # (3) 작업 자료 관리 카드 (통합고용세액공제와 동일한 아이콘 및 버튼 디자인 적용)
    emp_cnt = len(pstate.get("employees", []))
    free_cnt = len(pstate.get("freelancers", []))
    has_data = (emp_cnt + free_cnt) > 0 or bool(pstate.get("corp_name"))
    _rs_which = "EMP" if is_emp_mode else "FREE"
    _rs_name = "급여명세서(급여대장)" if is_emp_mode else "사업소득(사업소득대장)"
    _rs_has = (emp_cnt if is_emp_mode else free_cnt) > 0

    with st.expander("작업 자료 관리 (초기화 · 백업)", expanded=False):
        status_pill = (
            f"<span class='sb-badge-green'>근로 {emp_cnt}명 · 사업 {free_cnt}명</span>"
            if has_data
            else "<span class='sb-badge-amber'>초기 상태</span>"
        )
        st.markdown(
            _ui_theme.sb_title("refresh", "작업 자료 관리", status_pill),
            unsafe_allow_html=True,
        )
        if not st.session_state.get("pay_confirm_reset"):
            if st.button(
                "자료 초기화 (내용 비우기)",
                width="stretch",
                disabled=not _rs_has,
                key="btn_pay_reset_ask",
                help=f"지금 보고 있는 {_rs_name} 자료만 비웁니다. 다른 화면 자료와 사업자정보는 그대로 둡니다.",
            ):
                st.session_state["pay_confirm_reset"] = True
                st.rerun()
        else:
            st.caption(f"현재 화면의 {_rs_name} 입력 내용만 비울까요? (다른 화면 자료·사업자정보·백업 파일은 그대로)")
            c_y, c_n = st.columns(2)
            if c_y.button("초기화 실행", type="primary", width="stretch", key="btn_pay_reset_yes"):
                _reset_payroll_current_work(_rs_which)
                st.session_state["pay_confirm_reset"] = False
                st.rerun()
            if c_n.button("취소", width="stretch", key="btn_pay_reset_no"):
                st.session_state["pay_confirm_reset"] = False
                st.rerun()

    # (4) 사업자정보 카드 (통합고용세액공제와 동일한 🏢 아이콘 및 우측 끝 '직접입력' 배지 적용)
    with st.container(border=True, key="pay_sb_biz_card"):
        st.markdown(
            _ui_theme.sb_title("building", "사업자정보", "<span class='sb-badge-pro'>직접입력</span>"),
            unsafe_allow_html=True,
        )
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
                manual_fields = [x.strip() for x in str(emp.get("_수기") or "").split(",") if x.strip()]
                if not emp.get("사업장") or emp.get("사업장") in (prev_wp_label, "본점", "지점") or "사업장" not in manual_fields:
                    emp["사업장"] = new_wp_label
            pstate["grid_version"] = int(pstate.get("grid_version", 0)) + 1

        # 귀속연월: 최근 월이 위로 오도록 역순(12월 → 1월, 최근 연도부터)
        _kst_now = datetime.now(_KST)
        ym_options = [
            f"{yr:04d}-{mo:02d}"
            for yr in range(_kst_now.year + 1, _kst_now.year - 3, -1)
            for mo in range(12, 0, -1)
        ]
        curr_ym = str(pstate.get("year_month") or _kst_now.strftime("%Y-%m"))
        if curr_ym not in ym_options:
            ym_options.append(curr_ym)
            ym_options.sort(reverse=True)
        curr_pd = str(pstate.get("pay_date") or f"{curr_ym}-25")

        # 저장된 값(자료 업로드로 바뀐 값 포함)을 왼쪽 입력칸에 그대로 맞춤 — 입력칸이 예전 값으로 되돌리지 않도록
        if st.session_state.get("pay_sb_year_month") != curr_ym:
            st.session_state["pay_sb_year_month"] = curr_ym
        if st.session_state.get("pay_sb_pay_date") != curr_pd:
            st.session_state["pay_sb_pay_date"] = curr_pd

        c_ym, c_pdt = st.columns(2)
        with c_ym:
            st.selectbox(
                "귀속연월",
                options=ym_options,
                key="pay_sb_year_month",
                on_change=_on_sidebar_year_month_change,
            )
        with c_pdt:
            st.text_input(
                "지급일자",
                placeholder="YYYY-MM-DD",
                key="pay_sb_pay_date",
                on_change=_on_sidebar_pay_date_change,
            )

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

        # [당월 검토보고]·[통합고용세액공제 계산 연동]은 급여명세서(근로소득) 화면에서만 표시 — 사업소득 화면에서는 숨김
        if is_emp_mode:
            if st.button("당월 검토보고", icon=":material/description:", width="stretch", key="btn_pay_monthly_report"):
                _dlg_monthly_review_report_emp()
            _ai_kind = st.session_state.pop("pa_ai_saving_open", None)
            if _ai_kind:
                st.session_state["pa_ai_saving_kind"] = _ai_kind
                _dlg_ai_tax_review()

            if st.button(
                "통합고용세액공제 계산 연동",
                icon=":material/link:",
                width="stretch",
                key="btn_pay_bridge_credit",
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
            # 버튼 위 말풍선 대신 버튼 아래 안내 (위쪽 [당월 검토보고] 버튼을 가리지 않도록)
            st.caption("현재 사업장 급여내역을 통합고용세액공제 1단계 원천징수부 자료로 즉시 연동합니다.")

    # (5) 작업 백업 (내 PC) 카드 — 통합고용세액공제와 동일한 디자인·문구 및 단일 비밀번호 입력 적용
    with st.container(border=True):
        st.markdown(_ui_theme.sb_title("save", "작업 백업 (내 PC)"), unsafe_allow_html=True)
        st.caption("앱을 재시작하면 서버의 작업 내용이 사라질 수 있습니다. 비밀번호를 건 파일로 PC에 보관했다가 다시 올려 이어서 작업하세요.")
        saved_months = sorted((pstate.get("client_db") or {}).get("monthly_payroll", {}).keys())
        if saved_months:
            cov_txt = build_year_month_coverage_notice(pstate.get("client_db", {}))
            st.caption(f"현재 누적 귀속월: {', '.join(saved_months)} ({cov_txt})")

        tab_save, tab_load = st.tabs(["내려받기", "불러오기"])
        with tab_save:
            bk_pw = st.text_input(
                "백업 비밀번호",
                type="password",
                key="pay_bk_pw_save",
                help="6자 이상 비밀번호로 백업 파일(.paybak)을 암호화합니다. (서버 보안키가 설정된 경우에만 미입력 허용)",
            )
            if st.button("백업 파일 만들기", width="stretch", key="btn_pay_make_bak"):
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
                try:
                    bak_bytes = encrypt_client_db_to_paybak(pstate["client_db"], password=bk_pw)
                except BackupPasswordError as e_pw:
                    st.error(str(e_pw))
                    bak_bytes = None
                if bak_bytes:
                    c_nm = _sanitize_file_token(pstate.get("corp_name") or "거래처", "거래처")
                    wp_tag = _sanitize_file_token(_current_workplace_label(pstate) or "본점", "본점")
                    st.session_state["pay_bak_ready"] = (bak_bytes, f"{c_nm}_{wp_tag}_인건비누적DB.paybak")
            ready_bak = st.session_state.get("pay_bak_ready")
            if ready_bak:
                st.download_button(
                    "📥 백업 파일 내려받기",
                    data=ready_bak[0],
                    file_name=ready_bak[1],
                    mime="application/octet-stream",
                    width="stretch",
                    key="btn_pay_dl_bak",
                    on_click=lambda: st.session_state.pop("pay_bak_ready", None),
                )
                st.caption(f"`{ready_bak[1]}`  \n고객 자료와 같은 보안 폴더에 보관하세요. 비밀번호는 파일과 따로 관리하세요.")
        with tab_load:
            up_bak = st.file_uploader("백업 파일 (.paybak)", type=["paybak", "json"], key="pay_bk_file_up")
            in_pw = st.text_input("백업 비밀번호", type="password", key="pay_bk_pw_load")
            if up_bak is not None and st.button("파일 열기", width="stretch", key="btn_pay_load_bak"):
                try:
                    loaded_db, bak_info = decrypt_paybak_with_info(up_bak.getvalue(), password=in_pw)
                    if bak_info.get("weak"):
                        st.warning("이 백업은 구버전 공개 기본키(또는 평문)로 저장되어 누구나 열 수 있습니다. 6자 이상 비밀번호로 다시 백업해 주세요.")
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
                        pstate["_period_user_set"] = False   # 백업 복원은 백업 당시 귀속연월 그대로
                        pstate["employees"] = list(latest_pack.get("employees", []))
                        pstate["freelancers"] = list(latest_pack.get("freelancers", []))
                        pstate["grid_version"] += 1
                    st.success(f"백업 파일 불러오기 완료 (총 {len(m_map)}개월분)")
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
    ("소득세감면율", "소득세감면", 76, True, "select_red"),
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

        if lower_nm.endswith((".xlsx", ".xls", ".csv", ".cell", ".hwp", ".hwpx", ".docx")):
            fmt_label = (
                "한글 문서" if lower_nm.endswith((".hwp", ".hwpx"))
                else ("워드 문서" if lower_nm.endswith(".docx")
                      else ("한셀 문서" if lower_nm.endswith(".cell") else "엑셀·CSV"))
            )
            if "사업소득" in fname or "프리랜서" in fname or pstate.get("sub_mode") == "FREE":
                parsed_fr = parse_freelancer_excel(
                    fbytes,
                    filename=fname,
                    default_year_month=pstate.get("year_month", ""),
                    default_pay_date=pstate.get("pay_date", ""),
                    gemini_api_key=gemini_api_key,
                )
                if parsed_fr:
                    pstate["freelancers"] = parsed_fr
                    pstate["sub_mode"] = "FREE"
                    if pstate.get("_period_user_set"):
                        _apply_period_to_rows(pstate)
                    pstate["chat_logs"].append(f"[{fmt_label} 로드] '{fname}'에서 사업소득자 {len(parsed_fr)}명을 불러왔습니다.")
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
                    _set_period_from_file(pstate, res_ex["meta"]["year_month"])
                pstate["chat_logs"].append(
                    f"[{fmt_label} 로드] '{fname}'에서 근로자 {len(res_ex['employees'])}명 급여 내역을 추출했습니다."
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
                if pstate.get("_period_user_set"):
                    _apply_period_to_rows(pstate)
                elif notice_res.get("year_month"):
                    _first_pd = str((notice_res["freelancers"][0] or {}).get("지급년월일") or "")
                    _set_period_from_file(pstate, notice_res["year_month"], _first_pd if len(_first_pd) == 10 else "")
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
                    _set_period_from_file(pstate, notice_res["year_month"])
                pstate["chat_logs"].append(f"[급여대장·명세서 PDF 로드] {notice_res.get('message')}")
            elif ntype != "unknown":
                notice_list.append(notice_res)
                if notice_res.get("corp_name") and not pstate.get("corp_name"):
                    pstate["corp_name"] = notice_res["corp_name"]
                pstate["chat_logs"].append(f"[고지내역 PDF] {notice_res.get('message')}")
            else:
                pstate["chat_logs"].append(notice_res.get("message", f"PDF 확인 필요: {fname}"))

        elif lower_nm.endswith((".png", ".jpg", ".jpeg", ".webp")):
            mime = "image/png" if lower_nm.endswith(".png") else ("image/webp" if lower_nm.endswith(".webp") else "image/jpeg")
            vis_res = parse_image_with_gemini_vision(
                fbytes,
                mime_type=mime,
                gemini_api_key=gemini_api_key,
                sub_mode=pstate.get("sub_mode", "EMP"),
                default_year_month=pstate.get("year_month", ""),
                default_pay_date=pstate.get("pay_date", ""),
                effective_table=eff_tbl,
                default_workplace=wp_lbl,
            )
            if vis_res.get("type") == "freelancer_table" and vis_res.get("freelancers"):
                pstate["freelancers"] = vis_res["freelancers"]
                pstate["sub_mode"] = "FREE"
                if pstate.get("_period_user_set"):
                    _apply_period_to_rows(pstate)
                pstate["chat_logs"].append(vis_res.get("message", f"[캡처 로드] '{fname}' 사업소득 내역 반영 완료"))
            elif vis_res.get("type") == "payroll_table" and vis_res.get("employees"):
                pstate["employees"] = vis_res["employees"]
                pstate["sub_mode"] = "EMP"
                if vis_res.get("year_month"):
                    _set_period_from_file(pstate, vis_res["year_month"])
                pstate["chat_logs"].append(vis_res.get("message", f"[캡처 로드] '{fname}' 급여 내역 반영 완료"))
            elif vis_res.get("type") == "ei_notice":
                notice_list.append(vis_res["notice"])
                pstate["chat_logs"].append(f"[고용보험 이미지] {vis_res['notice'].get('message')}")
            elif vis_res.get("type") == "kakao_text":
                chat_text = (chat_text + "\n" + vis_res.get("extracted_text", "")).strip()
            else:
                pstate["chat_logs"].append(vis_res.get("message", f"이미지 처리 안내: {fname}"))

        elif lower_nm.endswith(".paybak"):
            try:
                _cand_pw = str(st.session_state.get("pay_bk_pw_load") or st.session_state.get("pay_bk_pw_save") or "")
                loaded_db, bak_info = decrypt_paybak_with_info(fbytes, password=_cand_pw)
                if bak_info.get("weak"):
                    pstate["chat_logs"].append(f"[보안 안내] '{fname}'은 구버전 공개 기본키로 저장된 백업입니다. 비밀번호를 걸어 다시 백업하세요.")
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
                    pstate["_period_user_set"] = False   # 백업 복원은 백업 당시 귀속연월 그대로
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
            year_month=pstate.get("year_month") or None,
        )
        pstate["employees"] = updated_emps
        pstate["notice_logs"].extend(n_logs)
        pstate["chat_logs"].extend(n_logs)

    # [핵심 개선] 파일과 채팅을 동시에 올렸거나, 파일을 먼저 올린 뒤 채팅으로
    # "모든 직원이(또는 김아무개가) 비과세식대 200,000원 반영해야해" / "금액에 적힌 급여는 세후 급여야" 등을 입력한 경우
    # 기존 명단에 즉시 일괄/개별 반영하고 전체 세액·4대보험을 재계산합니다.
    if chat_text and chat_text.strip():
        _chat_meta: Dict[str, Any] = {}
        mod_emps, mod_frees, mod_logs, remaining_chat = apply_chat_modifiers_to_state(
            raw_text=chat_text,
            employees=pstate.get("employees", []),
            freelancers=pstate.get("freelancers", []),
            sub_mode=pstate.get("sub_mode", "EMP"),
            effective_table=eff_tbl,
            withholding_rate_pct=int(pstate.get("withholding_rate_pct", 100)),
            default_year_month=pstate.get("year_month", ""),
            default_pay_date=pstate.get("pay_date", ""),
            default_workplace=wp_lbl,
            out_meta=_chat_meta,
        )
        pstate["employees"] = mod_emps
        pstate["freelancers"] = mod_frees
        if _chat_meta.get("pay_date"):
            # 채팅으로 바꾼 지급일 = 왼쪽 사업자정보에서 직접 입력한 것과 같게 처리 (사업소득 행·사이드바 함께 반영)
            pstate["pay_date"] = _chat_meta["pay_date"]
            pstate["_period_user_set"] = True
            _apply_period_to_rows(pstate)
        if mod_logs:
            _recalculate_all_employee_rows(pstate)
            _recalculate_all_freelancer_rows(pstate)
            pstate["chat_logs"].extend(mod_logs)
        chat_text = remaining_chat

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
        pstate["selected_emp_indices"] = []
        hdr_cells = "".join(
            f"<th style='padding:10px 8px;background:#F9FAFB;color:#4E5968;font-size:12.2px;font-weight:700;border-bottom:1px solid #E5E8EB;text-align:center;white-space:nowrap;'>{c[1]}</th>"
            for c in EMP_GRID_COLUMNS[:12]
        )
        st.markdown(
            f"<div style='border:1px solid #E5E8EB;border-radius:14px;overflow:hidden;background:#FFFFFF;margin:6px 0 4px;'>"
            f"<div style='overflow-x:auto;'><table style='width:100%;border-collapse:collapse;'><thead><tr>{hdr_cells}</tr></thead></table></div>"
            f"<div style='padding:44px 24px;text-align:center;background:#FFFFFF;'>"
            f"<div style='font-size:1.02rem;font-weight:800;color:#191F28;margin-bottom:6px;'>아직 등록된 급여 대상자가 없습니다</div>"
            f"<div style='font-size:0.86rem;font-weight:500;color:#8B95A1;'>상단의 <b style='color:#3182F6;font-weight:800;'>[+ 행 추가]</b> 버튼을 누르거나 아래 AI 입력창에 <b style='color:#3182F6;font-weight:700;'>급여대장·고지서 파일</b>을 끌어다 놓으세요.</div>"
            f"</div></div>",
            unsafe_allow_html=True,
        )
        return
    if False:
        df = pd.DataFrame(columns=col_keys + ["_row_idx", "_manual"])
    else:
        rows_norm = []
        for idx, e in enumerate(emps, start=1):
            r = {}
            for k, _, _, _, ctype in EMP_GRID_COLUMNS:
                if k == "사업장":
                    r[k] = str(e.get(k) if e.get(k) is not None else wp_default)
                elif k == "사원코드":
                    r[k] = str(e.get(k) or f"{idx:03d}")
                elif ctype == "select_red":
                    r[k] = _reduction_label(e.get(k))
                elif ctype.startswith("numeric"):
                    r[k] = int(e.get(k, 0) or 0)
                else:
                    r[k] = str(e.get(k, "") or "")
            r["_row_idx"] = idx - 1
            r["_manual"] = str(e.get("_수기") or "")
            rows_norm.append(r)
        df = pd.DataFrame(rows_norm, columns=col_keys + ["_row_idx", "_manual"])

    gb = GridOptionsBuilder.from_dataframe(df)
    gb.configure_default_column(
        resizable=True,
        sortable=True,
        filter=False,
        suppressMenu=True,
        minWidth=30,
    )
    gb.configure_column("_manual", hide=True)
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

    # 잘리면 안 되는 열: 사업장·코드·성명·주민등록번호·소득세감면·입사일·퇴사일·기준·금액 → 내용 길이에 맞춰 폭 자동 확대
    keep_text = {"사업장": 30, "사원코드": 0, "성명": 0, "주민등록번호": 0, "소득세감면율": 16, "입사일": 0, "퇴사일": 0, "입력기준": 0}
    for field, header_name, width, editable, ctype in EMP_GRID_COLUMNS:
        if field in zero_cols:
            width = 42
        elif emps and field in keep_text:
            width = _fit_width(header_name, df[field].tolist(), width, extra=keep_text[field])
        elif emps and ctype.startswith("numeric") and field not in ("부양가족수", "자녀수"):
            width = _fit_width("", df[field].tolist(), width, numeric=True)
        pinned = "left" if field in ("사업장", "사원코드", "성명") else None
        is_first_col = (field == "사업장")
        if ctype == "select_red":
            gb.configure_column(
                field,
                header_name=header_name,
                width=width,
                minWidth=width - 4,
                editable=editable,
                suppressMenu=True,
                cellEditor="agSelectCellEditor",
                cellEditorParams={"values": REDUCTION_OPTIONS},
                cellRenderer=_DROPDOWN_RENDERER,
                headerTooltip="중소기업 취업자 소득세 감면(조특법 제30조): 청년 90% / 60세 이상·장애인·경력단절 근로자 70% — 근로자 감면신청 후 적용",
                cellStyle=_manual_style(),
            )
            continue
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
                cellStyle=_manual_style(),
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
                cellStyle=_manual_style(),
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
                    "backgroundColor": "#E5F9F0",
                    "color": "#00A660",
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
                cellStyle=_manual_style(cell_style),
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
                cellStyle=_manual_style(),
            )

    grid_opts = gb.build()
    grid_opts["suppressSizeToFit"] = True
    grid_opts["ensureDomOrder"] = True
    grid_opts["stopEditingWhenCellsLoseFocus"] = True
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
        server_sync_strategy="server_wins",   # 수정 후 다시 계산한 값(4대보험·세액 등)을 표를 새로 만들지 않고 그대로 반영
    )

    pstate["selected_emp_indices"] = _extract_selected_row_indices(grid_resp)
    updated_df = grid_resp.get("data")
    if updated_df is not None and isinstance(updated_df, pd.DataFrame) and not updated_df.empty:
        # 같은 응답을 두 번 처리하지 않음 (그리드를 새로 만들지 않고 값만 바꾸므로, 직전 응답이 다시 돌아와도 무시)
        _edit_cols = [k for k, _, _, editable, _ct in EMP_GRID_COLUMNS if editable and k in updated_df.columns]
        _sig = _grid_resp_sig(updated_df, _edit_cols)
        if _sig != pstate.get("_emp_grid_resp_sig"):
            pstate["_emp_grid_resp_sig"] = _sig
            new_emps: List[Dict[str, Any]] = []
            changed = False
            for idx, row in updated_df.iterrows():
                orig = emps[idx] if idx < len(emps) else {}
                merged = dict(orig)
                shown = df.iloc[idx].to_dict() if idx < len(df) else {}
                hand = [k for k in _edit_cols if k in shown and not _same_cell(shown.get(k), row.get(k))]
                if not hand:
                    new_emps.append(merged)
                    continue
                changed = True
                _add_manual_marks(orig, merged, hand)
                # 수기 입력 칸만 반영하고 4대보험·세액 등 계산 칸은 다시 계산 (그리드에 남은 예전 계산값으로 덮어쓰지 않음)
                for k, _, _, editable, ctype in EMP_GRID_COLUMNS:
                    if not editable or k not in hand:
                        continue
                    val = row.get(k)
                    if ctype == "select_red":
                        merged[k] = _reduction_value(val)
                    elif ctype.startswith("numeric"):
                        merged[k] = int(round(float(val or 0))) if pd.notna(val) and str(val).strip() != "" else 0
                    else:
                        str_v = "" if pd.isna(val) else str(val).strip()
                        if k == "주민등록번호":
                            if "*" not in str_v and str_v:
                                merged["_raw_rrn"] = extract_full_rrn(str_v)
                            str_v = mask_rrn_front7(merged.get("_raw_rrn") or str_v)
                        merged[k] = str_v
                new_emps.append(merged)
            if changed:
                pstate["employees"] = new_emps
                _recalculate_all_employee_rows(pstate)
                st.rerun()   # 그리드 열쇠(key)는 그대로 → 표를 새로 만들지 않고 값만 갱신 (깜빡임·대기 감소)


def _grid_resp_sig(df_resp: pd.DataFrame, cols: List[str]) -> str:
    """표에서 돌아온 수기 입력 칸의 서명 (같은 응답을 두 번 처리하지 않기 위함) — JSON 직렬화 해시로 계산(기존 대비 약 17배 빠름)"""
    try:
        sub = df_resp[cols] if cols else df_resp
        raw = sub.to_json(orient="values", force_ascii=False, date_format="iso")
        return f"{len(df_resp)}:" + hashlib.md5(raw.encode("utf-8")).hexdigest()
    except Exception:
        return str(hash(df_resp.to_string()))


# 선택 칸 표시: 글자 + 오른쪽 ▾ (HTML 문자열을 돌려주면 그리드가 글자 그대로 보여 주므로 화면 요소를 직접 만듭니다)
_DROPDOWN_RENDERER = JsCode(
    "class PayDropRenderer {"
    " init(p){ this.e=document.createElement('div');"
    " this.e.style.cssText='display:flex;justify-content:space-between;align-items:center;width:100%;gap:4px;';"
    " var t=document.createElement('span'); t.textContent=(p.value==null)?'':String(p.value);"
    " t.style.cssText='overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';"
    " var a=document.createElement('span'); a.textContent='\u25BE'; a.style.cssText='color:#64748b;flex:none;';"
    " this.e.appendChild(t); this.e.appendChild(a); }"
    " getGui(){ return this.e; }"
    " refresh(){ return false; } }"
)

MANUAL_BG = "#fef9c3"  # 편집기에서 직접 고친 칸(수기입력) 바탕: 연노랑


def _manual_style(base: Optional[Dict[str, Any]] = None) -> JsCode:
    """기본 칸 모양 + 수기입력 칸이면 연노랑 바탕."""
    import json as _json
    return JsCode(
        "function(p){var s=Object.assign({}, " + _json.dumps(base or {}, ensure_ascii=False) + ");"
        "var m=(p.data&&p.data._manual)?(','+p.data._manual+','):'';"
        "if(m.indexOf(','+p.colDef.field+',')>=0){s.backgroundColor='" + MANUAL_BG + "';}return s;}"
    )


def _text_px(s: Any) -> float:
    """글자 폭 대략값(px): 한글·전각 12.6, 그 외 7.4."""
    return sum(12.6 if ord(ch) >= 0x1100 else 7.4 for ch in str(s))


def _fit_width(header: str, values: List[Any], base: int, extra: int = 0, numeric: bool = False) -> int:
    """머리글과 값이 잘리지(…) 않는 폭."""
    if numeric:
        vals = [f"{int(v or 0):,}" for v in values]
    else:
        vals = [str(v or "") for v in values]
    need_v = max([_text_px(v) for v in vals] or [0]) + 24 + extra
    need_h = _text_px(header) * 0.98 + 30
    return int(max(base, need_v, need_h))


def _same_cell(a: Any, b: Any) -> bool:
    """화면에 보여 준 값과 그리드에서 돌아온 값이 같은지 (숫자 1 / "1" / 1.0 같은 차이는 같게)."""
    na = a is None or (isinstance(a, float) and pd.isna(a))
    nb = b is None or (isinstance(b, float) and pd.isna(b))
    if na or nb:
        return (na or str(a).strip() == "") and (nb or str(b).strip() == "")
    try:
        return float(str(a).replace(",", "")) == float(str(b).replace(",", ""))
    except Exception:
        return str(a).strip() == str(b).strip()


def _add_manual_marks(orig: Dict[str, Any], merged: Dict[str, Any], fields: List[str]) -> None:
    if not fields:
        return
    cur = [f for f in str(orig.get("_수기") or "").split(",") if f]
    for f in fields:
        if f not in cur:
            cur.append(f)
    merged["_수기"] = ",".join(cur)


REDUCTION_OPTIONS = ["", "90%", "70%"]  # 중소기업 취업자 소득세 감면율 (조특법 제30조: 청년 90%, 그 외 대상 70%)


def _reduction_label(v: Any) -> str:
    try:
        f = float(v or 0)
    except Exception:
        f = 0.0
    return f"{int(f)}%" if f > 0 else ""


def _reduction_value(v: Any) -> float:
    m = re.search(r"(\d+(?:\.\d+)?)", str(v or ""))
    return float(m.group(1)) if m else 0.0


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
        pstate["selected_free_indices"] = []
        hdr_cells = "".join(
            f"<th style='padding:10px 8px;background:#F9FAFB;color:#4E5968;font-size:12.2px;font-weight:700;border-bottom:1px solid #E5E8EB;text-align:center;white-space:nowrap;'>{c[1]}</th>"
            for c in FREE_GRID_COLUMNS
        )
        st.markdown(
            f"<div style='border:1px solid #E5E8EB;border-radius:14px;overflow:hidden;background:#FFFFFF;margin:6px 0 4px;'>"
            f"<div style='overflow-x:auto;'><table style='width:100%;border-collapse:collapse;'><thead><tr>{hdr_cells}</tr></thead></table></div>"
            f"<div style='padding:44px 24px;text-align:center;background:#FFFFFF;'>"
            f"<div style='font-size:1.02rem;font-weight:800;color:#191F28;margin-bottom:6px;'>아직 등록된 사업소득 대상자가 없습니다</div>"
            f"<div style='font-size:0.86rem;font-weight:500;color:#8B95A1;'>상단의 <b style='color:#3182F6;font-weight:800;'>[+ 행 추가]</b> 버튼을 누르거나 아래 AI 입력창에 <b style='color:#3182F6;font-weight:700;'>사업소득 내역(엑셀·PDF·카톡 문자)</b>을 끌어다 놓으세요.</div>"
            f"</div></div>",
            unsafe_allow_html=True,
        )
        return
    if False:
        df = pd.DataFrame(columns=col_keys + ["_row_idx", "_manual"])
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
            r["_manual"] = str(f.get("_수기") or "")
            rows_norm.append(r)
        df = pd.DataFrame(rows_norm, columns=col_keys + ["_row_idx", "_manual"])

    gb = GridOptionsBuilder.from_dataframe(df)
    gb.configure_default_column(
        resizable=True,
        sortable=True,
        filter=False,
        suppressMenu=True,
    )
    gb.configure_column("_manual", hide=True)
    gb.configure_selection(
        selection_mode="multiple",
        use_checkbox=False,
        suppressRowClickSelection=True,
    )
    gb.configure_column("_row_idx", hide=True)

    for field, header_name, width, editable, ctype in FREE_GRID_COLUMNS:
        if frees and field != "세율":
            width = _fit_width(header_name, df[field].tolist(), width,
                               extra=(30 if field == "코드" else 16 if ctype == "select_ind" else 0),
                               numeric=ctype.startswith("numeric"))
        pinned = "left" if field in ("코드", "성명") else None
        is_first_col = (field == "코드")
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
                cellStyle=_manual_style(),
            )
        elif ctype == "select_ind":
            gb.configure_column(
                field,
                header_name=header_name,
                width=width,
                minWidth=width - 4,
                editable=editable,
                suppressMenu=True,
                cellEditor="agSelectCellEditor",
                cellEditorParams={"values": ind_codes},
                cellRenderer=_DROPDOWN_RENDERER,
                tooltipField="소득구분",
                cellStyle=_manual_style(),
            )
        elif ctype.startswith("numeric"):
            cell_style = {"textAlign": "right"}
            if ctype == "numeric_total":
                cell_style = {"textAlign": "right", "fontWeight": "bold", "backgroundColor": "#f8fafc"}
            elif ctype == "numeric_net":
                cell_style = {"textAlign": "right", "fontWeight": "bold", "backgroundColor": "#E5F9F0", "color": "#00A660"}
            gb.configure_column(
                field,
                header_name=header_name,
                width=width,
                minWidth=width - 4,
                editable=editable,
                suppressMenu=True,
                type=["numericColumn"],
                valueFormatter="x != null ? Number(x).toLocaleString() : '0'",
                cellStyle=_manual_style(cell_style),
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
                cellStyle=_manual_style(),
            )

    grid_opts = gb.build()
    grid_opts["suppressSizeToFit"] = True   # 열 폭을 내용에 맞춘 값 그대로 (화면 폭에 맞춰 줄이지 않음 → 머리글·값 잘림 방지)
    grid_height = min(480, max(230, 58 + len(df) * 36))

    grid_resp = AgGrid(
        df,
        gridOptions=grid_opts,
        height=grid_height,
        update_mode=GridUpdateMode.VALUE_CHANGED | GridUpdateMode.SELECTION_CHANGED,
        fit_columns_on_grid_load=False,
        allow_unsafe_jscode=True,
        theme="streamlit",
        key=f"pay_free_aggrid_{pstate.get('grid_version', 0)}",
        server_sync_strategy="server_wins",   # 수정 후 다시 계산한 값(4대보험·세액 등)을 표를 새로 만들지 않고 그대로 반영
    )

    pstate["selected_free_indices"] = _extract_selected_row_indices(grid_resp)
    updated_df = grid_resp.get("data")
    if updated_df is not None and isinstance(updated_df, pd.DataFrame) and not updated_df.empty:
        _edit_cols = [k for k, _, _, editable, _ct in FREE_GRID_COLUMNS if editable and k in updated_df.columns]
        _sig = _grid_resp_sig(updated_df, _edit_cols)
        if _sig != pstate.get("_free_grid_resp_sig"):
            pstate["_free_grid_resp_sig"] = _sig
            new_frees: List[Dict[str, Any]] = []
            changed = False
            for idx, row in updated_df.iterrows():
                orig = frees[idx] if idx < len(frees) else {}
                merged = dict(orig)
                shown = df.iloc[idx].to_dict() if idx < len(df) else {}
                hand = [k for k in _edit_cols if k in shown and not _same_cell(shown.get(k), row.get(k))]
                if not hand:
                    new_frees.append(merged)
                    continue
                changed = True
                _add_manual_marks(orig, merged, hand)
                for k, _, _, editable, ctype in FREE_GRID_COLUMNS:
                    if not editable or k not in hand:
                        continue
                    val = row.get(k)
                    if ctype.startswith("numeric"):
                        num_v = int(round(float(val or 0))) if pd.notna(val) and str(val).strip() != "" else 0
                        merged[k] = num_v
                        if k == "지급총액":
                            merged["_base_amount"] = num_v
                            merged["입력기준"] = "세전"
                        elif k == "차인지급액":
                            merged["_base_amount"] = num_v
                            merged["입력기준"] = "세후역산"
                    else:
                        str_v = "" if pd.isna(val) else str(val).strip()
                        if k == "소득구분":
                            str_v = _ind_code_only(str_v)  # 화면 표시는 "940909 (기타자영업)", 저장은 코드 6자리
                        elif k == "주민등록번호":
                            if "*" not in str_v and str_v:
                                merged["_raw_rrn"] = extract_full_rrn(str_v)
                            str_v = mask_rrn_front7(merged.get("_raw_rrn") or str_v)
                        merged[k] = str_v
                new_frees.append(merged)
            if changed:
                pstate["freelancers"] = new_frees
                _recalculate_all_freelancer_rows(pstate)
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
    st.session_state["_pa_explicit_key"] = gemini_api_key or None
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

    # B안: 위치 표시·꼬리표·큰 제목 → 요약 카드 → 표 카드(툴바 + 표) → 내려받기 카드 → 입력창
    import ui_theme as _ui_theme
    st.markdown(_ui_theme.pay_main_css(), unsafe_allow_html=True)
    _corp_h = pstate.get("corp_name") or "거래처 미입력"
    _wp_h = _current_workplace_label(pstate)
    _ym_h = pstate.get("year_month") or ""
    _pd_h = str(pstate.get("pay_date") or "")
    _chip_cls = "pay" if is_emp_mode else "biz"
    _chips = (
        f"<span class='ecx-chip {_chip_cls}'><span class='dot'></span>{_corp_h}{(' · ' + _wp_h) if _wp_h and _wp_h != _corp_h else ''}</span>"
        f"<span class='ecx-chip'>{_ym_h} 귀속{(' · 지급 ' + _pd_h[5:]) if len(_pd_h) >= 10 else ''}</span>"
    )
    st.markdown(
        _ui_theme.page_header(
            ["인건비 자동화", "급여명세서" if is_emp_mode else "사업소득"],
            _chips,
            "급여대장" if is_emp_mode else "사업소득대장",
            ("4대보험 근로소득자 · 엑셀·고지서·카톡 내용을 넣으면 자동 계산합니다. 연노랑 칸은 직접 고친 값이에요."
             if is_emp_mode else
             "3.3% 프리랜서 · 업종코드는 칸을 눌러 바꿀 수 있어요 (기본 940909 기타자영업)."),
        ),
        unsafe_allow_html=True,
    )
    if is_emp_mode:
        _el = pstate.get("employees", [])
        _mv = diag.get("movement_summary") or {}
        _sm = lambda k: sum(int(e.get(k, 0) or 0) for e in _el)
        _red_n = sum(1 for e in _el if float(e.get("소득세감면율", 0) or 0) > 0)
        st.markdown(_ui_theme.kpi_row([
            ("인원", f"{len(_el)}명", f"신규 {len(_mv.get('new_hires') or [])} · 퇴사 {len(_mv.get('retirees') or [])}", ""),
            ("지급액계", f"{_sm('지급액계'):,}원", f"비과세 {_sm('비과세합계'):,}", ""),
            ("소득세 · 지방소득세", f"{_sm('소득세'):,} · {_sm('지방소득세'):,}", (f"감면 적용 {_red_n}명" if _red_n else "간이세액표 기준"), ""),
            ("공제액계", f"{_sm('공제액계'):,}원", "4대보험 + 소득세", ""),
            ("차인지급액 (실지급)", f"{_sm('차인지급액'):,}원", "이체할 금액", "money"),
        ]), unsafe_allow_html=True)
    else:
        _fl = pstate.get("freelancers", [])
        _fs = lambda k: sum(int(f.get(k, 0) or 0) for f in _fl)
        st.markdown(_ui_theme.kpi_row([
            ("인원", f"{len(_fl)}명", "3.3% 사업소득자", ""),
            ("지급총액 (세전)", f"{_fs('지급총액'):,}원", "", ""),
            ("소득세 3% · 지방소득세 0.3%", f"{_fs('소득세'):,} · {_fs('지방소득세'):,}", f"원천징수 합계 {_fs('공제액계'):,}원", ""),
            ("차인지급액 (실지급)", f"{_fs('차인지급액'):,}원", "이체할 금액", "money biz"),
        ]), unsafe_allow_html=True)

    _tbl_card = st.container(key="pay_table_card")
    if is_emp_mode:
        top_c1, top_c2, top_c3, _top_sp, top_c4, top_c5 = _tbl_card.columns([1.45, 0.85, 1.25, 1.6, 1.45, 1.25], gap="small", vertical_alignment="center")
        emps_cur = pstate.get("employees", [])
        if emps_cur:
            is_emp_all_net = all(str(e.get("입력기준", "세전")) == "세후역산" for e in emps_cur)
            pstate["emp_bulk_is_net"] = is_emp_all_net
        else:
            is_emp_all_net = bool(pstate.get("emp_bulk_is_net", False))
        emp_sw_cls = "pay_free_sw_net" if is_emp_all_net else "pay_free_sw_gross"
        with _top_sp, st.container(key=emp_sw_cls):
            if st.button(
                "●",
                width="stretch",
                key="btn_emp_bulk_gross_net_switch",
                help="클릭 시 근로자 전체의 기준금액을 [세전(기본급 기준)] ↔ [세후(실수령액 기준 역산)]으로 일괄 전환합니다.",
            ):
                pstate["emp_bulk_is_net"] = not is_emp_all_net
                target_emp_mode = "세전" if is_emp_all_net else "세후역산"
                for e_item in emps_cur:
                    e_item["입력기준"] = target_emp_mode
                    if target_emp_mode == "세후역산" and int(e_item.get("목표실수령액", 0) or 0) <= 0:
                        e_item["목표실수령액"] = int(e_item.get("차인지급액", 0) or e_item.get("기본급", 0) or 0)
                _recalculate_all_employee_rows(pstate)
                pstate["grid_version"] = int(pstate.get("grid_version", 0)) + 1
                st.rerun()
    else:
        top_c1, top_c2, top_c3, _top_sp, top_c4, top_c5 = _tbl_card.columns([1.6, 0.85, 1.25, 1.4, 1.35, 1.55], gap="small", vertical_alignment="center")
        frees_cur = pstate.get("freelancers", [])
        if frees_cur:
            is_all_net = all(str(f.get("입력기준", "세전")) == "세후역산" for f in frees_cur)
            pstate["free_bulk_is_net"] = is_all_net
        else:
            is_all_net = bool(pstate.get("free_bulk_is_net", False))
        sw_key_cls = "pay_free_sw_net" if is_all_net else "pay_free_sw_gross"
        with _top_sp, st.container(key=sw_key_cls):
            sw_help = (
                "클릭 시 동그라미(●)가 이동하며 프리랜서 전체의 기준금액을 [세전(지급총액 기준)] ↔ [세후(차인지급액 기준 역산)]으로 일괄 전환합니다."
            )
            if st.button(
                "●",
                width="stretch",
                key="btn_free_bulk_gross_net_switch",
                help=sw_help,
            ):
                pstate["free_bulk_is_net"] = not is_all_net
                target_next_mode = "세전" if is_all_net else "세후역산"
                for f_item in frees_cur:
                    if int(f_item.get("_base_amount") or 0) <= 0:
                        f_item["_base_amount"] = int(
                            f_item.get("차인지급액", 0)
                            if str(f_item.get("입력기준", "세전")) == "세후역산"
                            else f_item.get("지급총액", 0)
                        )
                    f_item["입력기준"] = target_next_mode
                _recalculate_all_freelancer_rows(pstate)
                pstate["grid_version"] = int(pstate.get("grid_version", 0)) + 1
                mode_desc = "세후(파일 금액 = 차인지급액 기준 3.3% 역산)" if target_next_mode == "세후역산" else "세전(파일 금액 = 지급총액 기준 3.3% 공제)"
                pstate["chat_logs"].append(f"[전체 스위치 전환] 프리랜서 {len(frees_cur)}명 전체를 '{mode_desc}'으로 일괄 전환했습니다.")
                st.rerun()

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
                    pstate["employees"] = [{k: v for k, v in e.items() if k != "_수기"} for e in prev_pack["employees"]]
                    _recalculate_all_employee_rows(pstate)
                    pstate["grid_version"] += 1
                    st.toast(f"직전 귀속월({prev_pack.get('year_month')}) 급여대장 {len(pstate['employees'])}명을 불러왔습니다.")
                    st.rerun()
                elif not is_emp_mode and prev_pack.get("freelancers"):
                    pstate["prev_freelancers"] = list(prev_pack["freelancers"])
                    pstate["freelancers"] = [{k: v for k, v in f.items() if k != "_수기"} for f in prev_pack["freelancers"]]
                    _apply_period_to_rows(pstate)   # 전월 명단을 가져오되 귀속연월·지급일자는 지금 화면 기준
                    _recalculate_all_freelancer_rows(pstate)
                    pstate["grid_version"] += 1
                    st.toast(f"직전 귀속월({prev_pack.get('year_month')}) 사업소득자 {len(pstate['freelancers'])}명을 불러왔습니다.")
                    st.rerun()
                else:
                    st.warning("누적 백업 DB에 해당 부문의 전월 데이터가 없습니다.")
            else:
                st.warning("누적 백업(.paybak) 파일에 저장된 전월 이력이 없습니다. 먼저 좌측 사이드바에서 백업 파일을 불러오거나 당월 엑셀을 업로드해 주세요.")

    with top_c2:
        if st.button("+ 행 추가", type="primary", width="stretch", key="btn_pay_add_row"):
            if is_emp_mode:
                next_idx = len(pstate["employees"]) + 1
                row_calc = calculate_employee_payroll_row(
                    base_pay=0,
                    meal_allowance=0,
                    dependents=1,
                    children_8_20=0,
                    effective_table=pstate.get("effective_table", "2026.03"),
                    year_month=pstate.get("year_month") or None,
                )
                pstate["employees"].append({
                    "사업장": _current_workplace_label(pstate),
                    "사원코드": f"{next_idx:03d}",
                    "성명": f"신규사원{next_idx}",
                    "주민등록번호": "",
                    "입사일": datetime.now(_KST).strftime("%Y-%m-01"),
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

    with top_c4, st.container(key=f"pay_warnchip_{diag['status_color']}"):
        _warn_lbl = (f"경고 {diag['danger_count']} · 주의 {diag['warning_count']}" if diag["total_count"] else "이상 없음")
        if st.button(
            _warn_lbl,
            icon=":material/error:" if diag["status_color"] == "red" else (":material/warning:" if diag["status_color"] == "yellow" else ":material/check_circle:"),
            width="stretch",
            key="btn_pay_open_warnings",
            help=f"경고·주의사항 보기 (상태: {status_word})",
        ):
            _dlg_payroll_warnings()

    if is_emp_mode:
        with top_c5:
            with st.popover("수당 계산기", icon=":material/schedule:", width="stretch"):
                if st.button("연장·야간·휴일근로수당 계산기", width="stretch", key="btn_pay_open_ot_calc"):
                    _dlg_overtime_calculator()
                if st.button("주휴수당 계산기", width="stretch", key="btn_pay_open_wh_calc"):
                    _dlg_weekly_holiday_calculator()
    else:
        with top_c5:
            if st.button("업종코드 조회·선택", icon=":material/search:", width="stretch", key="btn_pay_open_ind_code",
                         help="업종코드 목록에서 찾아 고릅니다 (기본 940909 기타자영업)."):
                _dlg_industry_code_selector()

    # 2. 메인 편집 표 (AG Grid 급여대장 / 사업소득대장)
    corp_disp = pstate.get("corp_name") or "거래처미입력"
    wp_disp = _current_workplace_label(pstate)
    ym_disp = pstate.get("year_month") or ""
    yymm_short = _format_yymm_4digit(ym_disp)
    c_safe = _sanitize_file_token(pstate.get("corp_name") or "거래처미입력", "거래처미입력")

    if is_emp_mode:
        wp_tag_str = f" · {wp_disp}" if wp_disp else ""
        with _tbl_card:
            st.markdown("<div class='pgx-hint'>왼쪽 선택칸으로 고른 뒤 [선택한 행 삭제] · 오른쪽으로 넘기면 4대보험·공제 항목</div>", unsafe_allow_html=True)
            _render_employee_aggrid(pstate)

        emps = pstate.get("employees", [])
        tot_gross = sum(int(e.get("지급액계", 0) or 0) for e in emps)
        tot_itax = sum(int(e.get("소득세", 0) or 0) for e in emps)
        tot_ltax = sum(int(e.get("지방소득세", 0) or 0) for e in emps)
        tot_ded = sum(int(e.get("공제액계", 0) or 0) for e in emps)
        tot_net = sum(int(e.get("차인지급액", 0) or 0) for e in emps)
        # 3-A. 급여명세서 양식 선택 + 다운로드 바 (사용자 지정 파일명 규칙 적용)
        with st.container(key="pay_dlcard"):
            _dt1, dl_enc = st.columns([4.2, 1.4], vertical_alignment="center")
            _dt1.markdown(f"<div class='pgx-card-title'>내려받기 <small>귀속 {ym_disp} · {len(emps)}명</small></div>", unsafe_allow_html=True)

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

            c_tpl, c_mag, dl_pdf, dl_img, dl_led, dl_xls = st.columns(
                [1.55, 0.28, 1.75, 1.75, 1.2, 1.75], gap="small", vertical_alignment="center"
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
                    label="급여명세서 일괄 다운, 압축",
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
                    "급여명세서 이미지 다운, 개별",
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
                    label="급여대장 다운",
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
                    label="위하고 급여 업로드 양식",
                    data=_lazy_bytes(export_wehago_payroll_excel, emps),
                    file_name=f"{c_safe}_위하고 업로드 양식_{yymm_short}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    width="stretch",
                    disabled=(len(emps) == 0),
                    key="btn_dl_wehago_emp_xlsx",
                )
    else:
        with _tbl_card:
            st.markdown("<div class='pgx-hint'>업종코드는 칸을 눌러 바꾸거나 위 [업종코드 조회·선택]으로 고릅니다 · 왼쪽 선택칸으로 고른 뒤 [선택한 행 삭제]</div>", unsafe_allow_html=True)
            _render_freelancer_aggrid(pstate)

        frees = pstate.get("freelancers", [])
        tot_fgross = sum(int(f.get("지급총액", 0) or 0) for f in frees)
        tot_fitax = sum(int(f.get("소득세", 0) or 0) for f in frees)
        tot_fltax = sum(int(f.get("지방소득세", 0) or 0) for f in frees)
        tot_fded = sum(int(f.get("공제액계", 0) or 0) for f in frees)
        tot_fnet = sum(int(f.get("차인지급액", 0) or 0) for f in frees)
        # 3-B. 사업소득 모드 다운로드 바 (사용자 지정 파일명 규칙 + [사업소득명세서 PDF 압축] 우측 돋보기 호버 미리보기)
        with st.container(key="pay_dlcard"):
            st.markdown(f"<div class='pgx-card-title'>내려받기 <small>귀속 {ym_disp} · {len(frees)}명</small></div>", unsafe_allow_html=True)
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

            def _free_mag(b64: str = "", title: str = "사업소득명세서 양식 미리보기") -> None:
                b64 = b64 or free_b64
                if b64:
                    st.markdown(
                        "<div class=\"pay-tpl-hover-wrap\" title=\"마우스를 올리면 양식 미리보기가 표시됩니다\">"
                        f"{MAGNIFIER_SVG}"
                        f"<div class=\"pay-tpl-hover-popup\"><div class=\"pay-tpl-hover-title\"><span>{title}</span>"
                        "<span style=\"color:#1D4ED8;\">샘플</span></div>"
                        f"<img src=\"data:image/jpeg;base64,{b64}\" alt=\"미리보기\" /></div></div>",
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
                    "사업소득명세서 일괄 다운, 개별",
                    width="stretch",
                    disabled=(len(frees) == 0),
                    key="btn_dl_free_pdf_each",
                    help=f"{f_inc_cnt}명의 사업소득명세서 PDF를 압축 없이 각각 한 번에 내려받습니다.",
                ):
                    with st.spinner("사업소득명세서 PDF를 만드는 중..."):
                        files = _zip_bytes_to_files(export_freelancer_statements_pdf_zip(**free_kw))
                    _trigger_multi_download(files, "application/pdf", "free_pdf")
            with fp_mag:
                _free_mag(free_b64, "사업소득명세서 PDF 미리보기")
            with fi_btn:
                # [사업소득명세서 일괄 다운(이미지), 개별] = 근로자명_사업소득명세서_YYMM.jpg 를 압축 없이 각각 한 번에
                if st.button(
                    "사업소득명세서 이미지 다운, 개별",
                    width="stretch",
                    disabled=(len(frees) == 0),
                    key="btn_dl_free_jpg_each",
                    help=f"{f_inc_cnt}명의 사업소득명세서 이미지(JPG)를 압축 없이 각각 한 번에 내려받습니다.",
                ):
                    with st.spinner("사업소득명세서 이미지를 만드는 중..."):
                        files = _zip_bytes_to_files(export_freelancer_statements_jpg_zip(**free_kw))
                    _trigger_multi_download(files, "image/jpeg", "free_jpg")
            with fi_mag:
                _free_mag(get_freelancer_receipt_preview_b64(), "사업소득명세서 이미지 미리보기")
            with f_led:
                # [사업소득대장 다운(PDF)] = 거래처명_사업소득대장_YYMM.pdf
                st.download_button(
                    label="사업소득대장 다운",
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
                    label="위하고 사업소득 업로드 양식",
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
        "급여대장·고지서(엑셀·한셀·한글·워드·PDF·캡처·.paybak)를 끌어다 놓거나 지시사항(예: 모든 직원 비과세식대 200,000원 반영해야해 / 세후 급여야)을 입력하세요"
        if is_emp_mode
        else "사업소득 내역(엑셀·한셀·한글·워드·PDF·캡처·.paybak)을 끌어다 놓거나 지시사항(예: 금액에 적힌 급여는 세후 급여야 / 홍길동 세후 300만원)을 입력하세요"
    )
    _chat_sig = inspect.signature(st.chat_input).parameters
    try:
        if "accept_file" in _chat_sig:
            chat_val = st.chat_input(
                bottom_placeholder,
                accept_file="multiple",
                file_type=["xlsx", "xls", "csv", "cell", "hwp", "hwpx", "docx", "pdf", "png", "jpg", "jpeg", "webp", "paybak"],
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

    # [파일 드래그앤드롭 후 Enter 키 즉시 업로드 브릿지]
    # 윈도우 탐색기에서 파일을 끌어다 놓은 직후 입력창 밖(또는 빈 텍스트 상태)에서 Enter를 눌러도 즉시 전송 버튼(➤)이 작동하도록 연동합니다.
    st.components.v1.html(
        """<script>
        (function() {
            const doc = window.parent.document;
            if (doc._payChatEnterBridgeBound) return;
            doc._payChatEnterBridgeBound = true;

            function hasAttachedFiles(chatInput) {
                if (!chatInput) return false;
                const btn = chatInput.querySelector('[data-testid="stChatInputSubmitButton"]');
                const ta = chatInput.querySelector('textarea[data-testid="stChatInputTextArea"], textarea');
                if (btn && !btn.disabled && (!ta || !ta.value.trim())) return true;
                return chatInput.querySelectorAll('[data-testid*="File"], [class*="uploadedFile"], li').length > 0;
            }

            doc.addEventListener('drop', function() {
                setTimeout(function() {
                    const ta = doc.querySelector('[data-testid="stChatInput"] textarea');
                    if (ta) ta.focus();
                }, 180);
            }, true);

            doc.addEventListener('change', function(e) {
                if (e.target && e.target.type === 'file') {
                    setTimeout(function() {
                        const ta = doc.querySelector('[data-testid="stChatInput"] textarea');
                        if (ta) ta.focus();
                    }, 180);
                }
            }, true);

            doc.addEventListener('keydown', function(e) {
                if (e.key !== 'Enter' || e.shiftKey || e.ctrlKey || e.altKey || e.metaKey || e.isComposing) return;
                const chatInput = doc.querySelector('[data-testid="stChatInput"]');
                if (!chatInput) return;
                const submitBtn = chatInput.querySelector('[data-testid="stChatInputSubmitButton"]');
                if (!submitBtn || submitBtn.disabled) return;
                const active = doc.activeElement;
                const ta = chatInput.querySelector('textarea');
                const isInsideChat = chatInput.contains(active) || active === doc.body || active === doc.documentElement;
                if (isInsideChat && hasAttachedFiles(chatInput)) {
                    e.preventDefault();
                    e.stopPropagation();
                    submitBtn.click();
                }
            }, true);
        })();
        </script>""",
        height=0,
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
