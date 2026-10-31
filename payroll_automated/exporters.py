# -*- coding: utf-8 -*-
"""
인건비 자동화 - 위하고 업로드 엑셀 및 PDF/JPG 명세서·대장 일괄 생성 엔진 (exporters.py)
1) 위하고(WEHAGO / SmartA) 업로드 엑셀:
   - 근로소득 급여 업로드 양식 (.xlsx, 29개 열 2단 병합 헤더 + 합계행)
   - 사업소득(3.3%) 자료입력 업로드 양식 (.xlsx, 15개 열 표준 서식)
2) 급여대장 PDF (A4 가로, 사원별 3단 행 블록 + 하단 합계 블록)
3) 인별 급여명세서 PDF 일괄 압축 (.zip, 1회 최대 200명, 세부내역 + 산출식 테이블 + 생년월일 6자리 암호 옵션)
4) 사업소득지급대장 PDF (A4 세로, 2단 헤더 + 하단 총계)
5) 인별 사업소득명세서 PDF 일괄 압축 (.zip, 1회 최대 100명) 및 이미지(JPG) 일괄 압축 (.zip, 1회 최대 100명)
6) 한글 글꼴 자동 보장: 시스템 폰트 없을 시 통합고용세액공제와 동일하게 NanumGothic TTF를 `.workspace_storage`에 자동 다운로드·캐싱하여 Streamlit Cloud JPG/PDF 한글 깨짐 원천 차단
"""

from __future__ import annotations

import io
import os
import re
import urllib.request
import zipfile
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from PIL import Image
from pypdf import PdfReader, PdfWriter
import pypdfium2 as pdfium
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .parsers import extract_birth_6digits


# ─────────────────────────────────────────────────────────────
# 한글 폰트 자동 등록 (NanumGothic 자동 다운로드 캐시 포함 — PDF 및 pypdfium2 JPG 완벽 호환)
# ─────────────────────────────────────────────────────────────

_STORAGE_DIR = ".workspace_storage"
_REGISTERED_FONT_REGULAR = "Helvetica"
_REGISTERED_FONT_BOLD = "Helvetica-Bold"
_FONT_INIT_DONE = False
_FONT_DOWNLOAD_ATTEMPTED = False


def get_korean_font_names() -> Tuple[str, str]:
    """
    1순위: Windows 맑은 고딕 / `.workspace_storage/NanumGothic.ttf` 캐시 / Linux 시스템 나눔고딕 TTF
    2순위: Streamlit Cloud 등 한글 TTF가 없는 환경에서는 GitHub Google Fonts에서 `NanumGothic.ttf` 및
          `NanumGothicBold.ttf`를 `.workspace_storage/`에 자동 다운로드·캐싱 후 TTFont로 등록
          (통합고용세액공제 `ui_common._ensure_korean_pdf_font`와 동일한 메커니즘으로 JPG 변환 시에도 글자 깨짐 0건 보장)
    3순위: 오프라인 비상 폴백(DroidSansFallbackFull.ttf -> HYGothic-Medium)
    """
    global _REGISTERED_FONT_REGULAR, _REGISTERED_FONT_BOLD, _FONT_INIT_DONE, _FONT_DOWNLOAD_ATTEMPTED
    if _FONT_INIT_DONE:
        return _REGISTERED_FONT_REGULAR, _REGISTERED_FONT_BOLD

    reg_name = "PayKorFont"
    bold_name = "PayKorFontBold"
    registered = pdfmetrics.getRegisteredFontNames()
    if reg_name in registered and bold_name in registered:
        _REGISTERED_FONT_REGULAR = reg_name
        _REGISTERED_FONT_BOLD = bold_name
        _FONT_INIT_DONE = True
        return _REGISTERED_FONT_REGULAR, _REGISTERED_FONT_BOLD

    os.makedirs(_STORAGE_DIR, exist_ok=True)
    cached_reg = os.path.join(_STORAGE_DIR, "NanumGothic.ttf")
    cached_bold = os.path.join(_STORAGE_DIR, "NanumGothicBold.ttf")

    ttf_candidates = [
        ("C:/Windows/Fonts/malgun.ttf", "C:/Windows/Fonts/malgunbd.ttf"),
        (cached_reg, cached_bold),
        ("/usr/share/fonts/truetype/nanum/NanumGothic.ttf", "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"),
        ("/usr/share/fonts/truetype/unfonts-core/UnDotum.ttf", "/usr/share/fonts/truetype/unfonts-core/UnDotumBold.ttf"),
        ("/System/Library/Fonts/Supplemental/AppleGothic.ttf", "/System/Library/Fonts/Supplemental/AppleGothic.ttf"),
    ]

    chosen_reg, chosen_bold = None, None
    for rp, bp in ttf_candidates:
        if os.path.exists(rp):
            chosen_reg = rp
            chosen_bold = bp if os.path.exists(bp) else rp
            break

    # 시스템에 나눔고딕/맑은고딕이 없으면 통합고용세액공제 모듈과 동일하게 NanumGothic 자동 다운로드
    if chosen_reg is None and not _FONT_DOWNLOAD_ATTEMPTED:
        _FONT_DOWNLOAD_ATTEMPTED = True
        try:
            with urllib.request.urlopen(
                "https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Regular.ttf",
                timeout=2.5,
            ) as resp:
                with open(cached_reg, "wb") as out_f:
                    out_f.write(resp.read())
            with urllib.request.urlopen(
                "https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Bold.ttf",
                timeout=3.0,
            ) as resp:
                with open(cached_bold, "wb") as out_f:
                    out_f.write(resp.read())
            if os.path.exists(cached_reg):
                chosen_reg = cached_reg
                chosen_bold = cached_bold if os.path.exists(cached_bold) else cached_reg
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
            _REGISTERED_FONT_REGULAR = reg_name
            _REGISTERED_FONT_BOLD = bold_name
            _FONT_INIT_DONE = True
            return _REGISTERED_FONT_REGULAR, _REGISTERED_FONT_BOLD
        except Exception:
            pass

    try:
        pdfmetrics.registerFont(UnicodeCIDFont("HYGothic-Medium"))
        _REGISTERED_FONT_REGULAR = "HYGothic-Medium"
        _REGISTERED_FONT_BOLD = "HYGothic-Medium"
    except Exception:
        pass

    _FONT_INIT_DONE = True
    return _REGISTERED_FONT_REGULAR, _REGISTERED_FONT_BOLD


def _fmt_won(val: Any) -> str:
    try:
        n = int(round(float(val or 0)))
    except (ValueError, TypeError):
        n = 0
    return f"{n:,}" if n != 0 else ""


def _fmt_won_zero(val: Any) -> str:
    try:
        n = int(round(float(val or 0)))
    except (ValueError, TypeError):
        n = 0
    return f"{n:,}"


def _parse_ym_parts(year_month: str) -> Tuple[int, int]:
    m = re.match(r"^(\d{4})\D*(\d{1,2})", str(year_month or ""))
    if m:
        return int(m.group(1)), int(m.group(2))
    now = datetime.now()
    return now.year, now.month


# ─────────────────────────────────────────────────────────────
# 1. 위하고(WEHAGO) 근로소득 급여 업로드 엑셀 (.xlsx)
# ─────────────────────────────────────────────────────────────

WEHAGO_PAYROLL_ROW1 = [
    "사원코드", "사원명", "부서", "직급", "직종",
    "수당", "", "", "", "", "", "", "", "", "", "", "",
    "공제", "", "", "", "", "", "", "", "", "", "",
    "차인지급액",
]

WEHAGO_PAYROLL_ROW2 = [
    "", "", "", "", "",
    "기본급", "상여", "식대", "자가운전보조금", "약정연장근로수당", "약정휴일근로수당",
    "연장근로수당", "휴일근로수당", "결근공제", "조정금액", "미사용연차수당", "지급액계",
    "국민연금", "건강보험", "고용보험", "장기요양보험료", "소득세", "지방소득세",
    "학자금상환액", "건강보험료정산", "장기요양보험료정산", "국민연금정산", "공제액계",
    "",
]

WEHAGO_PAYROLL_FIELD_KEYS = [
    "기본급", "상여", "식대", "자가운전보조금", "약정연장근로수당", "약정휴일근로수당",
    "연장근로수당", "휴일근로수당", "결근공제", "조정금액", "미사용연차수당", "지급액계",
    "국민연금", "건강보험", "고용보험", "장기요양보험료", "소득세", "지방소득세",
    "학자금상환액", "건강보험료정산", "장기요양보험료정산", "국민연금정산", "공제액계",
]


def export_wehago_payroll_excel(employees: List[Dict[str, Any]]) -> bytes:
    """
    위하고 근로소득 급여자료 업로드용 표준 엑셀 생성 (29컬럼 2단 병합 헤더 + 합계행)
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "근로소득_위하고업로드"

    ws.append(WEHAGO_PAYROLL_ROW1)
    ws.append(WEHAGO_PAYROLL_ROW2)

    for col_idx in (1, 2, 3, 4, 5, 29):
        col_letter = get_column_letter(col_idx)
        ws.merge_cells(f"{col_letter}1:{col_letter}2")
    ws.merge_cells("F1:Q1")
    ws.merge_cells("R1:AB1")

    header_fill = PatternFill("solid", fgColor="E8EEF5")
    header_font = Font(name="맑은 고딕", size=10, bold=True, color="1E293B")
    body_font = Font(name="맑은 고딕", size=10, color="0F172A")
    total_fill = PatternFill("solid", fgColor="F8FAFC")
    total_font = Font(name="맑은 고딕", size=10, bold=True, color="0F172A")
    thin_side = Side(style="thin", color="CBD5E1")
    border_all = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)

    for r_i in (1, 2):
        for c_i in range(1, 30):
            cell = ws.cell(row=r_i, column=c_i)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = border_all

    totals = {k: 0 for k in WEHAGO_PAYROLL_FIELD_KEYS + ["차인지급액"]}

    for idx, emp in enumerate(employees or [], start=1):
        code_str = str(emp.get("사원코드") or f"{idx:03d}").zfill(3)
        row_vals: List[Any] = [
            code_str,
            str(emp.get("성명", "")),
            str(emp.get("부서", "")),
            str(emp.get("직급", "")),
            str(emp.get("직종", "")),
        ]
        for k in WEHAGO_PAYROLL_FIELD_KEYS:
            val = int(emp.get(k, 0) or 0)
            row_vals.append(val)
            totals[k] += val
        net_val = int(emp.get("차인지급액", 0) or 0)
        row_vals.append(net_val)
        totals["차인지급액"] += net_val

        ws.append(row_vals)
        cur_r = ws.max_row
        for c_i in range(1, 30):
            cell = ws.cell(row=cur_r, column=c_i)
            cell.font = body_font
            cell.border = border_all
            if c_i <= 5:
                cell.alignment = Alignment(horizontal="center", vertical="center")
            else:
                cell.alignment = Alignment(horizontal="right", vertical="center")
                cell.number_format = "#,##0"

    sum_row: List[Any] = ["합계", "", "", "", ""]
    for k in WEHAGO_PAYROLL_FIELD_KEYS:
        sum_row.append(totals[k])
    sum_row.append(totals["차인지급액"])
    ws.append(sum_row)
    last_r = ws.max_row
    for c_i in range(1, 30):
        cell = ws.cell(row=last_r, column=c_i)
        cell.fill = total_fill
        cell.font = total_font
        cell.border = border_all
        if c_i <= 5:
            cell.alignment = Alignment(horizontal="center", vertical="center")
        else:
            cell.alignment = Alignment(horizontal="right", vertical="center")
            cell.number_format = "#,##0"

    for c_i in range(1, 30):
        col_letter = get_column_letter(c_i)
        ws.column_dimensions[col_letter].width = 11 if c_i <= 5 else 14

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ─────────────────────────────────────────────────────────────
# 2. 위하고(SmartA) 사업소득 업로드 엑셀 (.xlsx)
# ─────────────────────────────────────────────────────────────

def export_wehago_freelancer_excel(
    freelancers: List[Dict[str, Any]],
    default_year_month: str = "",
    default_pay_date: str = "",
) -> bytes:
    """
    위하고 / SmartA 사업소득자료입력 엑셀 변환 서식 생성 (15개 열 표준 서식)
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"

    ws.append([
        "사업소득자료입력     ※ 본 서식은 SmartA 인사급여 사업소득자료입력 메뉴로 Excel DATA를 자동 변환하기 위한 서식입니다.",
        *([""] * 14),
    ])
    guide_text = (
        "1. 귀속년월 및 지급년월일 : YYYYMM(6자리), YYYYMMDD(8자리) 형태로 입력합니다.\n"
        "2. 주민등록번호 : '-'를 제외한 13자리 숫자로 입력합니다.\n"
        "3. 소득구분 : 업종코드 6자리를 입력합니다 (예: 940909 기타자영업).\n"
        "4. 내.외국인구분 : 내국인 '0', 외국인 '1' / 연말정산 : 비대상 '0', 대상 '1'"
    )
    ws.append([guide_text, *([""] * 14)])
    headers = [
        "", "귀속년월", "지급년월일", "소득자명", "주민등록번호",
        "기본주소", "상세주소", "소득구분", "영수일자", "지급총액",
        "세율(%)", "소득세", "지방소득세", "내.외국인구분", "연말정산",
    ]
    ws.append(headers)

    ws.merge_cells("A1:O1")
    ws.merge_cells("A2:O2")
    ws.row_dimensions[2].height = 54

    header_fill = PatternFill("solid", fgColor="EDE9FE")
    header_font = Font(name="맑은 고딕", size=10, bold=True, color="1E1B4B")
    body_font = Font(name="맑은 고딕", size=10, color="0F172A")
    thin_side = Side(style="thin", color="CBD5E1")
    border_all = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)

    for c_i in range(1, 16):
        cell = ws.cell(row=3, column=c_i)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border_all

    yyyy, mm_num = _parse_ym_parts(default_year_month)
    default_ym6 = f"{yyyy:04d}{mm_num:02d}"
    default_pay8 = re.sub(r"[^0-9]", "", str(default_pay_date or ""))
    if len(default_pay8) != 8:
        default_pay8 = f"{yyyy:04d}{mm_num:02d}25"

    for fr in freelancers or []:
        ym_digits = re.sub(r"[^0-9]", "", str(fr.get("귀속년월") or ""))
        ym6 = ym_digits[:6] if len(ym_digits) >= 6 else default_ym6

        pay_digits = re.sub(r"[^0-9]", "", str(fr.get("지급년월일") or ""))
        pay8 = pay_digits[:8] if len(pay_digits) >= 8 else default_pay8

        rrn_digits = re.sub(r"[^0-9*]", "", str(fr.get("주민등록번호") or ""))
        gross = int(fr.get("지급총액", 0) or 0)
        itax = int(fr.get("소득세", 0) or 0)
        ltax = int(fr.get("지방소득세", 0) or 0)

        row_vals = [
            "",
            ym6,
            pay8,
            str(fr.get("성명", "")),
            rrn_digits,
            str(fr.get("기본주소", "")),
            str(fr.get("상세주소", "")),
            str(fr.get("소득구분") or "940909"),
            pay8,
            gross,
            int(fr.get("세율", 3) or 3),
            itax,
            ltax,
            "0",
            "0",
        ]
        ws.append(row_vals)
        cur_r = ws.max_row
        for c_i in range(1, 16):
            cell = ws.cell(row=cur_r, column=c_i)
            cell.font = body_font
            cell.border = border_all
            if c_i in (10, 12, 13):
                cell.alignment = Alignment(horizontal="right", vertical="center")
                cell.number_format = "#,##0"
            else:
                cell.alignment = Alignment(horizontal="center", vertical="center")

    col_widths = [4, 12, 14, 14, 18, 20, 16, 12, 14, 15, 10, 14, 14, 14, 12]
    for c_i, w in enumerate(col_widths, start=1):
        ws.column_dimensions[get_column_letter(c_i)].width = w

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ─────────────────────────────────────────────────────────────
# 3. 급여대장 PDF (A4 가로 - 사원별 3단 블록 + 합계 블록)
# ─────────────────────────────────────────────────────────────

def export_payroll_ledger_pdf(
    employees: List[Dict[str, Any]],
    corp_name: str = "",
    year_month: str = "",
    pay_date: str = "",
) -> bytes:
    """
    표준 급여대장 PDF (A4 Landscape, 사원별 3행 블록 구조 + 하단 합계 블록)
    """
    font_reg, font_bold = get_korean_font_names()
    yyyy, mm_num = _parse_ym_parts(year_month)
    pay_dt_fmt = pay_date.replace("-", "년 ", 1).replace("-", "월 ") + "일" if "-" in str(pay_date) else f"{yyyy}년{mm_num:02d}월25일"

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        leftMargin=10 * mm,
        rightMargin=10 * mm,
        topMargin=10 * mm,
        bottomMargin=10 * mm,
    )

    title_style = ParagraphStyle(
        "LedgerTitle",
        fontName=font_bold,
        fontSize=16,
        leading=20,
        alignment=1,
    )
    meta_style = ParagraphStyle(
        "LedgerMeta",
        fontName=font_reg,
        fontSize=9,
        leading=12,
        alignment=0,
    )
    meta_right_style = ParagraphStyle(
        "LedgerMetaRight",
        fontName=font_reg,
        fontSize=9,
        leading=12,
        alignment=2,
    )

    elements: List[Any] = []
    elements.append(Paragraph(f"{yyyy}년 {mm_num:02d}월분 급여대장", title_style))
    elements.append(Spacer(1, 3 * mm))

    meta_tbl = Table(
        [[
            Paragraph(f"회사명 : {corp_name or '미입력'} &nbsp;&nbsp;&nbsp; 정렬 : 코드순", meta_style),
            Paragraph(f"[귀속:{yyyy}년{mm_num:02d}월] &nbsp; [지급:{pay_dt_fmt}]", meta_right_style),
        ]],
        colWidths=[138 * mm, 138 * mm],
    )
    meta_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    elements.append(meta_tbl)
    elements.append(Spacer(1, 2 * mm))

    table_data: List[List[str]] = [
        ["사번", "부서", "기본급", "상여", "식대", "자가운전보조금", "약정연장근로수당", "미사용연차수당", "", "", "건강보험료정산", "장기요양보험료정산", ""],
        ["사원명", "직급", "약정휴일근로수당", "연장근로수당", "휴일근로수당", "결근공제", "조정금액", "소득세", "지방소득세", "학자금상환액", "국민연금정산", "공제액계", ""],
        ["입사일", "퇴사일", "지급액계", "국민연금", "건강보험", "장기요양보험료", "고용보험", "", "", "", "", "차인지급액", ""],
    ]

    totals = {k: 0 for k in WEHAGO_PAYROLL_FIELD_KEYS + ["차인지급액"]}

    for idx, emp in enumerate(employees or [], start=1):
        for k in WEHAGO_PAYROLL_FIELD_KEYS:
            totals[k] += int(emp.get(k, 0) or 0)
        totals["차인지급액"] += int(emp.get("차인지급액", 0) or 0)

        c_code = str(emp.get("사원코드") or f"{idx:03d}")
        c_name = str(emp.get("성명", ""))
        c_hire = str(emp.get("입사일", "")).replace("-", ".")
        c_retire = str(emp.get("퇴사일", "")).replace("-", ".")
        c_dept = str(emp.get("부서", ""))
        c_pos = str(emp.get("직급", ""))

        r1 = [
            c_code,
            c_dept,
            _fmt_won(emp.get("기본급")),
            _fmt_won(emp.get("상여")),
            _fmt_won(emp.get("식대")),
            _fmt_won(emp.get("자가운전보조금")),
            _fmt_won(emp.get("약정연장근로수당")),
            _fmt_won(emp.get("미사용연차수당")),
            "",
            "",
            _fmt_won(emp.get("건강보험료정산")),
            _fmt_won(emp.get("장기요양보험료정산")),
            "",
        ]
        r2 = [
            c_name,
            c_pos,
            _fmt_won(emp.get("약정휴일근로수당")),
            _fmt_won(emp.get("연장근로수당")),
            _fmt_won(emp.get("휴일근로수당")),
            _fmt_won(emp.get("결근공제")),
            _fmt_won(emp.get("조정금액")),
            _fmt_won(emp.get("소득세")),
            _fmt_won(emp.get("지방소득세")),
            _fmt_won(emp.get("학자금상환액")),
            _fmt_won(emp.get("국민연금정산")),
            _fmt_won_zero(emp.get("공제액계")),
            "",
        ]
        r3 = [
            c_hire,
            c_retire,
            _fmt_won_zero(emp.get("지급액계")),
            _fmt_won(emp.get("국민연금")),
            _fmt_won(emp.get("건강보험")),
            _fmt_won(emp.get("장기요양보험료")),
            _fmt_won(emp.get("고용보험")),
            "",
            "",
            "",
            "",
            _fmt_won_zero(emp.get("차인지급액")),
            "",
        ]
        table_data.extend([r1, r2, r3])

    emp_cnt = len(employees or [])
    s1 = [
        "합 계", "",
        _fmt_won_zero(totals["기본급"]),
        _fmt_won(totals["상여"]),
        _fmt_won(totals["식대"]),
        _fmt_won(totals["자가운전보조금"]),
        _fmt_won(totals["약정연장근로수당"]),
        _fmt_won(totals["미사용연차수당"]),
        "", "",
        _fmt_won(totals["건강보험료정산"]),
        _fmt_won(totals["장기요양보험료정산"]),
        "",
    ]
    s2 = [
        f"({emp_cnt}명)", "",
        _fmt_won(totals["약정휴일근로수당"]),
        _fmt_won(totals["연장근로수당"]),
        _fmt_won(totals["휴일근로수당"]),
        _fmt_won(totals["결근공제"]),
        _fmt_won(totals["조정금액"]),
        _fmt_won_zero(totals["소득세"]),
        _fmt_won_zero(totals["지방소득세"]),
        _fmt_won(totals["학자금상환액"]),
        _fmt_won(totals["국민연금정산"]),
        _fmt_won_zero(totals["공제액계"]),
        "",
    ]
    s3 = [
        "", "",
        _fmt_won_zero(totals["지급액계"]),
        _fmt_won_zero(totals["국민연금"]),
        _fmt_won_zero(totals["건강보험"]),
        _fmt_won_zero(totals["장기요양보험료"]),
        _fmt_won_zero(totals["고용보험"]),
        "", "", "", "",
        _fmt_won_zero(totals["차인지급액"]),
        "",
    ]
    table_data.extend([s1, s2, s3])

    col_widths = [18 * mm, 16 * mm, 24 * mm, 22 * mm, 22 * mm, 22 * mm, 24 * mm, 22 * mm, 20 * mm, 20 * mm, 22 * mm, 25 * mm, 20 * mm]
    tbl = Table(table_data, colWidths=col_widths, repeatRows=3)

    cmds: List[Any] = [
        ("FONTNAME", (0, 0), (-1, -1), font_reg),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (1, -1), "CENTER"),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (2, 0), (-1, 2), "CENTER"),
        ("BACKGROUND", (0, 0), (-1, 2), colors.HexColor("#E2E8F0")),
        ("FONTNAME", (0, 0), (-1, 2), font_bold),
        ("BOX", (0, 0), (-1, -1), 1.0, colors.HexColor("#334155")),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#CBD5E1")),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]

    total_rows = len(table_data)
    for b_start in range(0, total_rows, 3):
        cmds.append(("LINEABOVE", (0, b_start), (-1, b_start), 0.8, colors.HexColor("#475569")))
        cmds.append(("SPAN", (11, b_start + 1), (12, b_start + 1)))
        cmds.append(("SPAN", (11, b_start + 2), (12, b_start + 2)))

    cmds.append(("BACKGROUND", (0, total_rows - 3), (-1, total_rows - 1), colors.HexColor("#F1F5F9")))
    cmds.append(("FONTNAME", (0, total_rows - 3), (-1, total_rows - 1), font_bold))

    tbl.setStyle(TableStyle(cmds))
    elements.append(tbl)

    doc.build(elements)
    return buf.getvalue()


# ─────────────────────────────────────────────────────────────
# 4. 인별 급여명세서 PDF 생성 및 ZIP 일괄 압축 (1회 최대 200명 + 생년월일 6자리 암호 옵션)
# ─────────────────────────────────────────────────────────────

def render_single_employee_payslip_pdf(
    emp: Dict[str, Any],
    corp_name: str = "",
    year_month: str = "",
    pay_date: str = "",
    password: Optional[str] = None,
) -> bytes:
    """
    단일 근로자 급여명세서 PDF 생성
    """
    font_reg, font_bold = get_korean_font_names()
    yyyy, mm_num = _parse_ym_parts(year_month)
    pay_dt_dot = str(pay_date or f"{yyyy}.{mm_num:02d}.25").replace("-", ".")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
    )

    title_style = ParagraphStyle("SlipTitle", fontName=font_bold, fontSize=18, leading=22, alignment=1)
    sec_style = ParagraphStyle("SlipSec", fontName=font_bold, fontSize=11, leading=15, alignment=1)
    meta_left = ParagraphStyle("SlipMetaL", fontName=font_reg, fontSize=10, leading=14, alignment=0)
    meta_right = ParagraphStyle("SlipMetaR", fontName=font_reg, fontSize=10, leading=14, alignment=2)
    footer_style = ParagraphStyle("SlipFooter", fontName=font_bold, fontSize=11, leading=16, alignment=1)

    elements: List[Any] = []
    elements.append(Paragraph(f"{yyyy}년 {mm_num:02d}월분 급여명세서", title_style))
    elements.append(Spacer(1, 6 * mm))

    head_tbl = Table(
        [[
            Paragraph(f"회사명: {corp_name or '미입력'}", meta_left),
            Paragraph(f"지급일: {pay_dt_dot}", meta_right),
        ]],
        colWidths=[87 * mm, 87 * mm],
    )
    head_tbl.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    elements.append(head_tbl)
    elements.append(Spacer(1, 2 * mm))

    info_tbl = Table(
        [["성명", str(emp.get("성명", "")), "사번", str(emp.get("사원코드", "001"))]],
        colWidths=[32 * mm, 55 * mm, 32 * mm, 55 * mm],
        rowHeights=[8 * mm],
    )
    info_tbl.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), font_reg),
        ("FONTNAME", (0, 0), (0, 0), font_bold),
        ("FONTNAME", (2, 0), (2, 0), font_bold),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#F1F5F9")),
        ("BACKGROUND", (2, 0), (2, 0), colors.HexColor("#F1F5F9")),
        ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#334155")),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#94A3B8")),
    ]))
    elements.append(info_tbl)
    elements.append(Spacer(1, 6 * mm))

    elements.append(Paragraph("세 부 내 역", sec_style))
    elements.append(Spacer(1, 2 * mm))

    pay_rows = [
        ("기본급", emp.get("기본급")),
        ("상여", emp.get("상여")),
        ("식대", emp.get("식대")),
        ("자가운전보조금", emp.get("자가운전보조금")),
        ("약정연장근로수당", emp.get("약정연장근로수당")),
        ("약정휴일근로수당", emp.get("약정휴일근로수당")),
        ("연장근로수당", emp.get("연장근로수당")),
        ("휴일근로수당", emp.get("휴일근로수당")),
        ("결근공제", emp.get("결근공제")),
        ("조정금액", emp.get("조정금액")),
        ("미사용연차수당", emp.get("미사용연차수당")),
    ]
    ded_rows = [
        ("국민연금", emp.get("국민연금")),
        ("건강보험", emp.get("건강보험")),
        ("고용보험", emp.get("고용보험")),
        ("장기요양보험료", emp.get("장기요양보험료")),
        ("소득세", emp.get("소득세")),
        ("지방소득세", emp.get("지방소득세")),
        ("학자금상환액", emp.get("학자금상환액")),
        ("건강보험료정산", emp.get("건강보험료정산")),
        ("장기요양보험료정산", emp.get("장기요양보험료정산")),
        ("국민연금정산", emp.get("국민연금정산")),
        ("", 0),
    ]

    detail_data: List[List[str]] = [
        ["지 급", "", "공 제", ""],
        ["지급 항목", "지급 금액", "공제 항목", "공제 금액"],
    ]
    for (p_label, p_val), (d_label, d_val) in zip(pay_rows, ded_rows):
        detail_data.append([
            p_label,
            _fmt_won(p_val),
            d_label,
            _fmt_won(d_val) if d_label else "",
        ])

    detail_data.append([
        "지급액계",
        _fmt_won_zero(emp.get("지급액계")),
        "공제액계",
        _fmt_won_zero(emp.get("공제액계")),
    ])
    detail_data.append([
        "",
        "",
        "실지급액",
        _fmt_won_zero(emp.get("차인지급액")),
    ])

    detail_tbl = Table(
        detail_data,
        colWidths=[45 * mm, 42 * mm, 45 * mm, 42 * mm],
        rowHeights=[7.5 * mm] * len(detail_data),
    )
    d_last = len(detail_data) - 1
    detail_tbl.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), font_reg),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("SPAN", (0, 0), (1, 0)),
        ("SPAN", (2, 0), (3, 0)),
        ("SPAN", (0, d_last - 1), (0, d_last)),
        ("SPAN", (1, d_last - 1), (1, d_last)),
        ("BACKGROUND", (0, 0), (-1, 1), colors.HexColor("#F1F5F9")),
        ("BACKGROUND", (0, d_last - 1), (-1, d_last), colors.HexColor("#F8FAFC")),
        ("FONTNAME", (0, 0), (-1, 1), font_bold),
        ("FONTNAME", (0, d_last - 1), (-1, d_last), font_bold),
        ("ALIGN", (0, 0), (-1, 1), "CENTER"),
        ("ALIGN", (0, 2), (0, -1), "CENTER"),
        ("ALIGN", (2, 2), (2, -1), "CENTER"),
        ("ALIGN", (1, 2), (1, -1), "RIGHT"),
        ("ALIGN", (3, 2), (3, -1), "RIGHT"),
        ("BOX", (0, 0), (-1, -1), 0.9, colors.HexColor("#334155")),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#94A3B8")),
        ("RIGHTPADDING", (1, 2), (1, -1), 6),
        ("RIGHTPADDING", (3, 2), (3, -1), 6),
    ]))
    elements.append(detail_tbl)
    elements.append(Spacer(1, 6 * mm))

    elements.append(Paragraph("계 산 방 법", sec_style))
    elements.append(Spacer(1, 2 * mm))

    calc_rows: List[List[str]] = [["구분", "산출식 또는 산출방법", "지급액"]]
    ot_pay = int(emp.get("연장근로수당", 0) or 0)
    hol_pay = int(emp.get("휴일근로수당", 0) or 0)
    fixed_ot = int(emp.get("약정연장근로수당", 0) or 0)
    meal_pay = int(emp.get("식대", 0) or 0)
    abs_ded = int(emp.get("결근공제", 0) or 0)

    if fixed_ot > 0:
        calc_rows.append(["약정연장근로수당", "근로계약 약정 고정연장수당", _fmt_won_zero(fixed_ot)])
    if ot_pay > 0:
        ot_h = emp.get("연장근무시간", 0)
        hr_w = emp.get("약정시급", 0)
        formula_txt = f"연장근로시간({ot_h:g}h) X 시급({hr_w:,}원) X 1.5" if (ot_h and hr_w) else "연장근로시간 X 시급 X 1.5"
        calc_rows.append(["연장근로수당", formula_txt, _fmt_won_zero(ot_pay)])
    if hol_pay > 0:
        calc_rows.append(["휴일근로수당", "휴일근로시간 X 시급 X 1.5", _fmt_won_zero(hol_pay)])
    if abs_ded != 0:
        calc_rows.append(["결근공제", "결근시간 X 약정시급 차감", _fmt_won_zero(abs_ded)])
    if meal_pay > 0:
        calc_rows.append(["식대", "비과세식대 (월 20만원 한도)", _fmt_won_zero(meal_pay)])

    while len(calc_rows) < 4:
        calc_rows.append(["", "", ""])

    calc_tbl = Table(
        calc_rows,
        colWidths=[45 * mm, 87 * mm, 42 * mm],
        rowHeights=[7.5 * mm] * len(calc_rows),
    )
    calc_tbl.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), font_reg),
        ("FONTNAME", (0, 0), (-1, 0), font_bold),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F1F5F9")),
        ("ALIGN", (0, 0), (1, -1), "CENTER"),
        ("ALIGN", (2, 1), (2, -1), "RIGHT"),
        ("ALIGN", (2, 0), (2, 0), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#334155")),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#94A3B8")),
        ("RIGHTPADDING", (2, 1), (2, -1), 6),
    ]))
    elements.append(calc_tbl)
    elements.append(Spacer(1, 10 * mm))
    elements.append(Paragraph("귀하의 노고에 감사드립니다.", footer_style))

    doc.build(elements)
    raw_pdf = buf.getvalue()

    if password:
        reader = PdfReader(io.BytesIO(raw_pdf))
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        writer.encrypt(password)
        enc_buf = io.BytesIO()
        writer.write(enc_buf)
        return enc_buf.getvalue()

    return raw_pdf


def export_employee_payslips_zip(
    employees: List[Dict[str, Any]],
    corp_name: str = "",
    year_month: str = "",
    pay_date: str = "",
    encrypt_with_birth: bool = False,
    start_index: int = 0,
    max_count: int = 200,
) -> bytes:
    """
    인별 급여명세서 PDF 일괄 생성 후 단일 ZIP 파일로 압축 반환 (1회 최대 200명, start_index로 201번 이후 분할 다운로드 지원):
    - encrypt_with_birth=True 선택 시 주민등록번호/생년월일 앞 6자리(YYMMDD)로 개별 PDF 암호화
    """
    yyyy, mm_num = _parse_ym_parts(year_month)
    yymm = f"{str(yyyy)[2:]}{mm_num:02d}"
    sliced = (employees or [])[start_index : start_index + max_count]

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for offset, emp in enumerate(sliced, start=start_index + 1):
            name = str(emp.get("성명") or f"사원{offset}").strip()
            pwd: Optional[str] = None
            if encrypt_with_birth:
                birth6 = extract_birth_6digits(str(emp.get("주민등록번호", "")))
                if len(birth6) == 6:
                    pwd = birth6
            pdf_bytes = render_single_employee_payslip_pdf(
                emp=emp,
                corp_name=corp_name,
                year_month=year_month,
                pay_date=pay_date,
                password=pwd,
            )
            safe_name = re.sub(r'[\\/*?:"<>|]', "", name)
            filename = f"{yymm}_급여명세서_{safe_name}님.pdf"
            zf.writestr(filename, pdf_bytes)

    return zip_buf.getvalue()


# ─────────────────────────────────────────────────────────────
# 5. 사업소득지급대장 PDF (A4 세로 - 표준 서식)
# ─────────────────────────────────────────────────────────────

def export_freelancer_ledger_pdf(
    freelancers: List[Dict[str, Any]],
    corp_name: str = "",
    year_month: str = "",
) -> bytes:
    """
    표준 사업소득지급대장 PDF 생성 (A4 Portrait, 2단 헤더 + 총계 블록)
    """
    font_reg, font_bold = get_korean_font_names()
    yyyy, mm_num = _parse_ym_parts(year_month)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
    )

    title_style = ParagraphStyle("FreeLedgerTitle", fontName=font_bold, fontSize=15, leading=20, alignment=1)
    meta_style = ParagraphStyle("FreeLedgerMeta", fontName=font_reg, fontSize=9.5, leading=13, alignment=0)

    elements: List[Any] = []
    elements.append(Paragraph(f"({yyyy}년 {mm_num:02d}월) 사업소득지급대장(합계)", title_style))
    elements.append(Spacer(1, 4 * mm))
    elements.append(Paragraph(f"회사명 : {corp_name or '미입력'}", meta_style))
    elements.append(Spacer(1, 2 * mm))

    table_data: List[List[str]] = [
        ["NO", "코드", "성명", "귀속년월", "지급액", "소득세", "예술·특고인경비", "학자금상환액", "차인지급액", "영수인"],
        ["", "", "", "지급년월", "", "지방소득세", "고용보험료", "산재보험료", "", ""],
    ]

    tot_gross = 0
    tot_itax = 0
    tot_ltax = 0
    tot_net = 0

    for idx, fr in enumerate(freelancers or [], start=1):
        gross = int(fr.get("지급총액", 0) or 0)
        itax = int(fr.get("소득세", 0) or 0)
        ltax = int(fr.get("지방소득세", 0) or 0)
        net = int(fr.get("차인지급액", 0) or 0)
        tot_gross += gross
        tot_itax += itax
        tot_ltax += ltax
        tot_net += net

        ym_str = str(fr.get("귀속년월") or f"{yyyy}-{mm_num:02d}").replace("-", "/")
        pay_str = str(fr.get("지급년월일") or f"{yyyy}-{mm_num:02d}")[:7].replace("-", "/")

        r1 = [
            str(idx),
            str(fr.get("코드") or f"{idx:04d}"),
            str(fr.get("성명", "")),
            ym_str,
            _fmt_won_zero(gross),
            _fmt_won_zero(itax),
            "",
            "",
            _fmt_won_zero(net),
            "",
        ]
        r2 = [
            "",
            "",
            "",
            pay_str,
            "",
            _fmt_won_zero(ltax),
            "",
            "",
            "",
            "",
        ]
        table_data.extend([r1, r2])

    table_data.append([
        "총 계", "", "", "",
        _fmt_won_zero(tot_gross),
        _fmt_won_zero(tot_itax),
        "", "",
        _fmt_won_zero(tot_net),
        "",
    ])
    table_data.append([
        "", "", "", "",
        "",
        _fmt_won_zero(tot_ltax),
        "", "",
        "",
        "",
    ])

    col_widths = [10 * mm, 16 * mm, 22 * mm, 20 * mm, 26 * mm, 22 * mm, 22 * mm, 20 * mm, 26 * mm, 12 * mm]
    tbl = Table(table_data, colWidths=col_widths, repeatRows=2)

    cmds: List[Any] = [
        ("FONTNAME", (0, 0), (-1, -1), font_reg),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (3, -1), "CENTER"),
        ("ALIGN", (4, 2), (8, -1), "RIGHT"),
        ("ALIGN", (4, 0), (9, 1), "CENTER"),
        ("BACKGROUND", (0, 0), (-1, 1), colors.HexColor("#EDE9FE")),
        ("FONTNAME", (0, 0), (-1, 1), font_bold),
        ("BOX", (0, 0), (-1, -1), 0.9, colors.HexColor("#334155")),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CBD5E1")),
    ]

    total_r = len(table_data)
    for r_start in range(0, total_r, 2):
        cmds.append(("LINEABOVE", (0, r_start), (-1, r_start), 0.7, colors.HexColor("#475569")))
        for c_span in (0, 1, 2, 4, 8, 9):
            cmds.append(("SPAN", (c_span, r_start), (c_span, r_start + 1)))

    cmds.append(("SPAN", (0, total_r - 2), (3, total_r - 1)))
    cmds.append(("BACKGROUND", (0, total_r - 2), (-1, total_r - 1), colors.HexColor("#F8FAFC")))
    cmds.append(("FONTNAME", (0, total_r - 2), (-1, total_r - 1), font_bold))

    tbl.setStyle(TableStyle(cmds))
    elements.append(tbl)

    doc.build(elements)
    return buf.getvalue()


# ─────────────────────────────────────────────────────────────
# 6. 인별 사업소득명세서 PDF 및 JPG 일괄 압축 (1회 최대 100명, 세로형 심플 양식)
# ─────────────────────────────────────────────────────────────

def render_single_freelancer_statement_pdf(
    fr: Dict[str, Any],
    corp_name: str = "",
    year_month: str = "",
    pay_date: str = "",
) -> bytes:
    """
    단일 사업소득명세서 PDF 생성 (세로형 심플 레이아웃):
    1) 상단 타이틀: "사업소득명세서"
    2) 기본정보 표: "귀속연월, 지급연월(일자), 소득자 성명, 소득구분"
    3) 지급 및 공제 요약 표:
       - 세전금액 (지급총액)
       - 공제가액 (소득세 3% / 지방소득세 0.3% / 공제합계 3.3% — 10원 미만 절사)
       - 차인지급액 (실지급액)
    """
    font_reg, font_bold = get_korean_font_names()
    yyyy, mm_num = _parse_ym_parts(fr.get("귀속년월") or year_month)
    ym_kor = f"{yyyy}년 {mm_num:02d}월"
    pay_dt_str = str(fr.get("지급년월일") or pay_date or f"{yyyy}-{mm_num:02d}-25")

    gross = int(fr.get("지급총액", 0) or 0)
    itax = int(fr.get("소득세", 0) or 0)
    ltax = int(fr.get("지방소득세", 0) or 0)
    ded_total = int(fr.get("공제액계", itax + ltax) or (itax + ltax))
    net = int(fr.get("차인지급액", gross - ded_total) or (gross - ded_total))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=22 * mm,
        rightMargin=22 * mm,
        topMargin=24 * mm,
        bottomMargin=24 * mm,
    )

    title_style = ParagraphStyle("BizSlipTitle", fontName=font_bold, fontSize=20, leading=26, alignment=1)
    sub_style = ParagraphStyle("BizSlipSub", fontName=font_reg, fontSize=10, leading=14, alignment=1, textColor=colors.HexColor("#475569"))
    sec_style = ParagraphStyle("BizSlipSec", fontName=font_bold, fontSize=11, leading=16, alignment=0)
    foot_style = ParagraphStyle("BizSlipFoot", fontName=font_bold, fontSize=11, leading=16, alignment=1)

    elements: List[Any] = []
    elements.append(Paragraph("사 업 소 득 명 세 서", title_style))
    elements.append(Spacer(1, 2 * mm))
    elements.append(Paragraph(f"원천징수의무자(회사명) : {corp_name or '미입력'}", sub_style))
    elements.append(Spacer(1, 8 * mm))

    # 1. 귀속연월, 지급연월, 소득자 성명 테이블 (칸 넘침 방지 및 정확한 세법 용어 '소득자 성명' 적용)
    info_data = [
        ["귀속연월", ym_kor, "지급연월(일자)", pay_dt_str],
        ["근로자명(성명)", str(fr.get("성명", "")), "소득구분", f"사업소득 (3.3% / {fr.get('소득구분', '940909')})"],
    ]
    info_tbl = Table(
        info_data,
        colWidths=[32 * mm, 45 * mm, 32 * mm, 57 * mm],
        rowHeights=[10 * mm, 10 * mm],
    )
    info_tbl.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), font_reg),
        ("FONTNAME", (0, 0), (0, -1), font_bold),
        ("FONTNAME", (2, 0), (2, -1), font_bold),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F3E8FF")),
        ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#F3E8FF")),
        ("BOX", (0, 0), (-1, -1), 0.9, colors.HexColor("#4C1D95")),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#C4B5FD")),
    ]))
    elements.append(info_tbl)
    elements.append(Spacer(1, 8 * mm))

    # 2. 세전금액 -> 공제가액 -> 차인지급액 세로 표 ('10원 미만 절사' 명시)
    elements.append(Paragraph("지급 및 원천징수 공제 내역", sec_style))
    elements.append(Spacer(1, 2 * mm))

    amt_data = [
        ["구 분", "산출 기준", "금 액 (원)"],
        ["세전금액 (지급총액)", "약정 사업소득 지급총액", f"{gross:,} 원"],
        ["공제가액 - 소득세", "세전금액 × 3.0% (10원 미만 절사)", f"{itax:,} 원"],
        ["공제가액 - 지방소득세", "소득세 × 10% (10원 미만 절사)", f"{ltax:,} 원"],
        ["공제가액 합계", "총 3.3% 원천징수 세액", f"{ded_total:,} 원"],
        ["차인지급액 (실지급액)", "세전금액 - 공제가액 합계", f"{net:,} 원"],
    ]
    amt_tbl = Table(
        amt_data,
        colWidths=[52 * mm, 64 * mm, 50 * mm],
        rowHeights=[10 * mm, 11 * mm, 10 * mm, 10 * mm, 11 * mm, 13 * mm],
    )
    amt_tbl.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), font_reg),
        ("FONTNAME", (0, 0), (-1, 0), font_bold),
        ("FONTNAME", (0, 1), (0, -1), font_bold),
        ("FONTNAME", (0, 4), (-1, 5), font_bold),
        ("FONTSIZE", (0, 0), (-1, 4), 10),
        ("FONTSIZE", (0, 5), (-1, 5), 11.5),
        ("ALIGN", (0, 0), (1, -1), "CENTER"),
        ("ALIGN", (2, 0), (2, 0), "CENTER"),
        ("ALIGN", (2, 1), (2, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F3E8FF")),
        ("BACKGROUND", (0, 4), (-1, 4), colors.HexColor("#F8FAFC")),
        ("BACKGROUND", (0, 5), (-1, 5), colors.HexColor("#EDE9FE")),
        ("BOX", (0, 0), (-1, -1), 1.0, colors.HexColor("#4C1D95")),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")),
        ("RIGHTPADDING", (2, 1), (2, -1), 10),
    ]))
    elements.append(amt_tbl)
    elements.append(Spacer(1, 14 * mm))
    elements.append(Paragraph("위와 같이 사업소득 금액 및 원천징수 세액을 명세합니다.", foot_style))

    doc.build(elements)
    return buf.getvalue()


def convert_pdf_bytes_to_jpg_bytes(pdf_bytes: bytes, scale: float = 2.2) -> bytes:
    """단일 페이지 PDF 바이트를 고해상도 JPG 바이트로 변환 (pypdfium2 + Pillow)"""
    pdf_doc = pdfium.PdfDocument(pdf_bytes)
    page = pdf_doc[0]
    bitmap = page.render(scale=scale)
    pil_img: Image.Image = bitmap.to_pil()
    if pil_img.mode != "RGB":
        pil_img = pil_img.convert("RGB")
    img_buf = io.BytesIO()
    pil_img.save(img_buf, format="JPEG", quality=92)
    return img_buf.getvalue()


def export_freelancer_statements_pdf_zip(
    freelancers: List[Dict[str, Any]],
    corp_name: str = "",
    year_month: str = "",
    pay_date: str = "",
    start_index: int = 0,
    max_count: int = 100,
) -> bytes:
    """인별 사업소득명세서 PDF 일괄 생성 후 단일 ZIP 파일로 압축 반환 (1회 최대 100명, start_index로 101번 이후 분할 다운로드 지원)"""
    yyyy, mm_num = _parse_ym_parts(year_month)
    yymm = f"{str(yyyy)[2:]}{mm_num:02d}"
    sliced = (freelancers or [])[start_index : start_index + max_count]

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for offset, fr in enumerate(sliced, start=start_index + 1):
            name = str(fr.get("성명") or f"소득자{offset}").strip()
            pdf_bytes = render_single_freelancer_statement_pdf(
                fr=fr,
                corp_name=corp_name,
                year_month=year_month,
                pay_date=pay_date,
            )
            safe_name = re.sub(r'[\\/*?:"<>|]', "", name)
            zf.writestr(f"{yymm}_사업소득명세서_{safe_name}님.pdf", pdf_bytes)
    return zip_buf.getvalue()


def export_freelancer_statements_jpg_zip(
    freelancers: List[Dict[str, Any]],
    corp_name: str = "",
    year_month: str = "",
    pay_date: str = "",
    start_index: int = 0,
    max_count: int = 100,
) -> bytes:
    """인별 사업소득명세서 이미지(JPG) 일괄 생성 후 단일 ZIP 파일로 압축 반환 (1회 최대 100명, start_index로 101번 이후 분할 다운로드 지원)"""
    yyyy, mm_num = _parse_ym_parts(year_month)
    yymm = f"{str(yyyy)[2:]}{mm_num:02d}"
    sliced = (freelancers or [])[start_index : start_index + max_count]

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for offset, fr in enumerate(sliced, start=start_index + 1):
            name = str(fr.get("성명") or f"소득자{offset}").strip()
            pdf_bytes = render_single_freelancer_statement_pdf(
                fr=fr,
                corp_name=corp_name,
                year_month=year_month,
                pay_date=pay_date,
            )
            jpg_bytes = convert_pdf_bytes_to_jpg_bytes(pdf_bytes)
            safe_name = re.sub(r'[\\/*?:"<>|]', "", name)
            zf.writestr(f"{yymm}_사업소득명세서_{safe_name}님.jpg", jpg_bytes)
    return zip_buf.getvalue()
