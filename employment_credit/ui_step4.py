# -*- coding: utf-8 -*-
"""통합고용세액공제 계산기 화면 — 4단계 보고서: 보고서·PDF·CSV 내려받기

(ui.py에서 나눈 파일. 현행 조특법 제29조의8·시행령 제26조의8 조문 정합성, 일관된 해석 기준 비교인원 산정 근거 및 다년도 자동 재산정,
사원별 차이원인 정밀 분해[중도퇴사·고용형태 전환 오판 원천 차단], 최저한세 검토, 법제처 API 직링크 자동 결합 반영,
PDF 출력 시각 스타일을 자율 에이전트AI `create_pdf_report`와 100% 동일하게 일치)
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
from datetime import date
import pandas as pd
import streamlit as st
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, JsCode
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether, HRFlowable
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from . import rules as R
from . import headcount as H
from . import parsers as P
from . import backup as B

from .ui_common import (  # noqa: F401
    _REPORT_EMOJI_RE,
    _S,
    _block_titles_for_year,
    _build_year_rows,
    _cohort_corp_size,
    _compute_historical_matrix_columns,
    _ctx,
    _ensure_built_for_tax_year,
    _ensure_korean_pdf_font,
    _ensure_totals_snapshot,
    _pdf_text,
    _save_ec_to_disk,
    _trigger_scroll_to_top,
    _years,
)


_ROMAN_MAP = str.maketrans({
    "Ⅰ": "I", "Ⅱ": "II", "Ⅲ": "III", "Ⅳ": "IV", "Ⅴ": "V",
    "Ⅵ": "VI", "Ⅶ": "VII", "Ⅷ": "VIII", "Ⅸ": "IX", "Ⅹ": "X",
    "ⅰ": "i", "ⅱ": "ii", "ⅲ": "iii", "ⅳ": "iv", "ⅴ": "v",
})


def _format_citation_tag_for_pdf(m: re.Match) -> str:
    kind = m.group(1).strip()
    body = m.group(2).strip()
    return f"[{kind}: {body}]"


def _pdf_text(t: str) -> str:
    """
    PDF 문단용: 자율 에이전트AI `app.py`의 `_sanitize_math_text` 및 `_md_to_rl_xml`과 100% 동일한
    텍스트·수식·법령 태그(`[조문: ...]`, `[부칙: ...]`) 및 마크다운 변환을 수행합니다.
    """
    _, bold_font = _ensure_korean_pdf_font()
    s = str(t or "")
    s = s.translate(_ROMAN_MAP)
    s = s.replace("∼", "~").replace("〜", "~").replace("～", "~")
    s = s.replace("−", " - ").replace("–", " - ").replace("—", " - ")
    s = s.replace("→", " -> ").replace("↔", " <-> ").replace("≧", ">=").replace("≦", "<=")
    s = re.sub(
        r"\[(조문|부칙|별표|판례|심판례|헌재|헌재결정례|해석례|예규)(?:\s*[:：]\s*|\s+)(?=[가-힣A-Za-z0-9「])([^\]]+)\]",
        _format_citation_tag_for_pdf,
        s,
    )
    s = re.sub(
        r"\[(조문|부칙|별표|판례|심판례|헌재|헌재결정례|해석례|예규)(?=[가-힣A-Za-z0-9「])([^\]:：\n]+)\]",
        _format_citation_tag_for_pdf,
        s,
    )
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    s = re.sub(r"\*\*(.+?)\*\*", rf'<font name="{bold_font}">\1</font>', s)
    s = re.sub(r"`([^`]+)`", r'<font backColor="#f1f5f9">\1</font>', s)
    return s


def _strip_all_emojis(text: str) -> str:
    """보고서 본문 및 기존 캐시된 AI 코멘트에서 아이콘·이모지를 모두 제거합니다."""
    if not text:
        return ""
    return _REPORT_EMOJI_RE.sub("", str(text))


def _sanitize_markdown_tilde(text: str) -> str:
    """
    마크다운(GFM)에서 `10~12월 ... 10~12월`처럼 한 문단에 물결표(`~`)가 두 번 이상 들어가면
    사이에 있는 문장 전체가 취소선(`<del>...</del>`)으로 렌더링되고 물결표가 사라져 `1012월`로 깨지는 문제를 방지합니다.
    (단, URL 내부의 `~`는 보존합니다.)
    """
    if not text:
        return ""
    s = str(text)
    s = re.sub(r"~~+", "∼", s)
    parts = re.split(r"(\]\(https?://[^\s)]+\)|https?://[^\s)]+)", s)
    for idx in range(0, len(parts), 2):
        parts[idx] = parts[idx].replace("~", "∼")
        parts[idx] = re.sub(r"\b(1[0-2]|[1-9])12월", r"\1∼12월", parts[idx])
    return "".join(parts)


def _normalize_verified_legal_citations(text: str) -> str:
    """
    AI 생성 코멘트 또는 이전 세션 캐시 문구에서 법령 번호·항 번호·병역차감 구분·경정청구 3년 실익·최저한세율 표기를
    법제처 원문 기준(법률 제21223호 부칙 제34조, 시행령 제26조의8 제2항·제4항·제6항·제8항 등)으로 자동 교정합니다.
    """
    if not text:
        return ""
    s = str(text)
    # 백틱으로 감싸진 법령 링크/태그의 백틱 제거 (초록색 코드블록 및 URL 나열 현상 원천 차단)
    s = re.sub(
        r"`+(\[\[?(?:판례|심판례|헌재|헌재결정례|해석례|예규|조문|부칙|별표|행정해석)[^\]`]+\]\]?\(https?://[^)\s`]+\))`+",
        r"\1",
        s,
    )
    s = re.sub(
        r"`+(\[(?:판례|심판례|헌재|헌재결정례|해석례|예규|조문|부칙|별표|행정해석)[^\]`]+\])`+",
        r"\1",
        s,
    )
    _f10_ln = P._get_ruling_verbatim_line("조특칙_별지_제10호의10_서식", "⑩") if hasattr(P, "_get_ruling_verbatim_line") else "⑩ 청년등 외 상시근로자수(=②-⑨)"
    s = s.replace("조세특례제한법 시행규칙 별지 제10호의9서식(1) 작성방법 제4호", f"조세특례제한법 시행규칙 별지 제10호의10서식({_f10_ln})")
    s = s.replace("별지 제10호의9서식(1) 작성방법 제4호", f"별지 제10호의10서식({_f10_ln})")
    s = s.replace("별지 제10호의10서식 작성방법 제25호", "조세특례제한법 시행령 부칙(2026.2.27.) 제11조")
    s = s.replace("법률 제21065호", "법률 제21223호")
    s = s.replace("구 조세특례제한법 제29조의8 제3항 및 대통령령 제35999호 부칙 제2조", "구 조세특례제한법 제29조의8 제1항(연속공제)·제3항(추가납부) 및 법률 제21223호 부칙 제34조·시행령 부칙 경과조치")
    s = s.replace("중견·일반기업 10~17%", "중견기업 8~9%·10~17%, 일반기업 10~17%")
    s = s.replace("중견·일반기업 10∼17%", "중견기업 8∼9%·10∼17%, 일반기업 10∼17%")
    s = s.replace("중견·일반기업은 10~17%", "중견기업은 8~9%·10~17%, 일반기업은 10~17%")
    s = s.replace("중견·일반기업은 10∼17%", "중견기업은 8∼9%·10∼17%, 일반기업은 10∼17%")

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

    txt = _sanitize_markdown_tilde(_normalize_verified_legal_citations(str(raw_comment).strip()))
    model_name = ""
    m_mod = re.search(r"적용\s*모델\s*[:：]\s*`?([^\]\n|`]+)`?", txt)
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

        if s_no_icon.startswith("### ") or s_no_icon.startswith("#### "):
            hdr_t = re.sub(r"^#{3,4}\s*", "", s_no_icon).strip()
            hdr_t = re.sub(r"^\*\*(.+?)\*\*$", r"\1", hdr_t).strip()
            if not re.match(r"^\(\d+\)", hdr_t):
                sub_idx += 1
                hdr_t = f"({sub_idx}) {hdr_t}"
            cleaned_lines.append("")
            cleaned_lines.append(f"### {hdr_t}")
            continue

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

        m_bullet_hdr = re.match(r"^(?:[-*•])\s*\*\*([^*:：]{3,40})\*\*\s*$", s_no_icon)
        if m_bullet_hdr:
            sub_idx += 1
            title_part = m_bullet_hdr.group(1).strip()
            cleaned_lines.append("")
            cleaned_lines.append(f"### ({sub_idx}) {title_part}")
            continue

        if re.match(r"^\s+[-*•]\s+", no_icon):
            cleaned_lines.append("- " + re.sub(r"^\s+[-*•]\s+", "", no_icon).strip())
            continue

        cleaned_lines.append(s_no_icon)

    body = "\n".join(cleaned_lines).strip()
    return body, model_name


def _analyze_headcount_diff_reasons(
    s: dict,
    tax_yr: int,
    computed_all: dict[int, dict] | None = None,
    totals_all: dict[int, dict] | None = None,
    pkg: dict | None = None,
) -> dict[str, list[str]]:
    """
    [사원별 인원 차이 원인 정밀 분해기 — 보고서 판단 오류 원천 차단]
    1) `구법포함_신법1년미만제외_사원`: 당해(tax_yr) 중도퇴사로 총 근로기간이 1년 미만이어서 당해 신법 공제(b1)에서는 제외되었으나,
       2024·2025년 귀속분 사후관리(b2·b3, 대통령령 제35999호 부칙 제2조 종전규정)에는 산입되어 사후관리 인원과 당해 공제 인원 간 차이를 발생시킨 사원.
    2) `직전연도말_재직_당해중도퇴사_일관제외_사원`: 직전연도(tax_yr - 1) 중 입사해 직전연도 말 현재 재직 중이었다가
       당해(tax_yr) 중 퇴사하여 총 근로기간이 1년 미만이 된 사원 — 일관된 해석 기준(당해 인원과 직전 비교 인원에 동일한 잣대 적용)에 따라
       당해 신법 인원과 직전연도 비교 인원(nr_) 모두에서 제외하고, 종전 규정이 적용되는 구법 자체·사후관리 인원에만 산입한 대상.
    3) `실제_연령도과_청년간주_사원`: 당해 상시근로자('O')이면서 순수하게 연령 도과(만 34세 및 유예기간 도과)로 인해
       당해에는 일반('청년외')이지만 코호트 사후관리(b2·b3)에서만 청년등으로 간주된 사원.
    4) `단시간_정규직_고용형태전환_사원`: 과거 과세연도에는 단시간근로자(0.5명, 청년 제외)였다가 이후 통상근로자(정규직 1.0명)로 전환되어
       청년등 상시근로자로 분류된 사원 (연령경과 간주 예시로 오용 금지).
    """
    people = s.get("people") or {}
    year_recs = s.get("year_recs") or {}
    if computed_all is None:
        computed_all = {}
        for y in _years(s):
            _, comp_y, _ = _build_year_rows(s, y)
            computed_all[y] = comp_y

    comp_cur = computed_all.get(tax_yr) or {}
    comp_prev = computed_all.get(tax_yr - 1) or {}

    under1y_pm_diff: list[str] = []
    conservative_prev_kept: list[str] = []
    age_deemed_youth: list[str] = []
    emp_type_converted: list[str] = []

    for pid, p in people.items():
        nm = str(p.get("성명") or "").strip()
        if not nm:
            continue
        hire_dt = H.parse_date(p.get("입사일"))
        ret_str = (p.get("연도별_퇴사일") or {}).get(str(tax_yr)) or p.get("퇴사일")
        ret_dt = H.parse_date(ret_str)

        c_cur = comp_cur.get(pid) or {}
        c_prev = comp_prev.get(pid) or {}

        # (A) 당해(tax_yr)에서 근속 1년 미만으로 제외되었거나, 사후관리(b2/b3)와 당해(b1) 청년/상시 인원이 다른 경우
        b1_y = float(c_cur.get("b1_yth") or 0.0)
        b2_y = float(c_cur.get("b2_yth") or 0.0)
        b3_y = float(c_cur.get("b3_yth") or 0.0)
        b1_r = float(c_cur.get("b1_reg") or 0.0)
        b2_r = float(c_cur.get("b2_reg") or 0.0)

        is_under_1y_cur = (c_cur.get("제외사유") == R.EXCL_UNDER_1Y) or H.tenure_under_1y(p, tax_yr)
        if is_under_1y_cur and (b2_r > b1_r or b2_y > b1_y or b3_y > b1_y):
            diff_v = max(b2_y - b1_y, b2_r - b1_r, b3_y - b1_y)
            under1y_pm_diff.append(f"{nm}(+{diff_v:.2f}명)")
        elif c_cur.get("상시") == "O" and not is_under_1y_cur and (b2_y > b1_y + 1e-9 or b3_y > b1_y + 1e-9):
            age_deemed_youth.append(f"{nm}(당해 청년 {b1_y:.2f} → 1차사후 {b2_y:.2f} / 2차사후 {b3_y:.2f})")

        # (B) 직전연도(tax_yr - 1) 입사 + 직전연도 말 현재 재직 + 당해(tax_yr) 중 퇴사로 총 근로기간 1년 미만인 사원 (일관된 해석 기준: 비교인원에서도 제외)
        if (
            hire_dt
            and ret_dt
            and hire_dt.year == (tax_yr - 1)
            and ret_dt.year == tax_yr
            and H.tenure_under_1y(p, tax_yr, as_of_year=tax_yr)
            and not H.tenure_under_1y(p, tax_yr - 1, as_of_year=None)
        ):
            prev_r = float(c_prev.get("b1_reg") or 0.0)
            if prev_r > 0 or H.worked_in_year(p, tax_yr - 1):
                conservative_prev_kept.append(
                    f"{nm}(입사 {hire_dt.isoformat()} ~ 퇴사 {ret_dt.isoformat()}, {tax_yr-1}년 구법 {prev_r:.2f}명 산입 · 신법 비교인원 및 {tax_yr}년 당해 모두 제외)"
                )
                # 만약 compute_row에서 b2_y와 b1_y 차이가 totals 레벨에서 반영된 경우도 포착
                if not any(nm in x for x in under1y_pm_diff):
                    # 당해 근무월수 추정 (구법 사후관리 산입분)
                    pay_cur = (p.get("월급여") or {}).get(str(tax_yr)) or {}
                    worked_m = sum(
                        1 for m in range(1, 13)
                        if H.employed_at_month_end(hire_dt, ret_dt, tax_yr, m) and float(pay_cur.get(str(m), 0) or 0) > 0
                    )
                    if worked_m > 0:
                        under1y_pm_diff.append(f"{nm}(구법 사후관리 +{worked_m/12:.2f}명 산입 vs 신법 당해 0명 제외)")

        # (C) 과거 연도 단시간(0.5/0.75) → 이후 연도 정규직(1.0) 전환 사원 포착
        emp_by_yr = {}
        for y_chk in sorted(computed_all.keys()):
            c_y = (computed_all.get(y_chk) or {}).get(pid)
            if c_y and float(c_y.get("row_sum") or 0) > 0:
                emp_by_yr[y_chk] = c_y.get("고용유형") or (year_recs.get(y_chk, {}).get(pid, {}).get("고용유형")) or R.EMP_REGULAR
        yr_keys = sorted(emp_by_yr.keys())
        for i_k in range(len(yr_keys) - 1):
            y_old, y_new = yr_keys[i_k], yr_keys[i_k + 1]
            if emp_by_yr[y_old] in (R.EMP_PT_050, R.EMP_PT_075) and emp_by_yr[y_new] == R.EMP_REGULAR:
                emp_type_converted.append(f"{nm}({y_old}년 {emp_by_yr[y_old]} → {y_new}년 정규직 전환)")
                break

    mil_cur_impact: list[str] = []
    mil_prev_only_impact: list[str] = []
    for pid, p in people.items():
        nm = str(p.get("성명") or "").strip()
        if not nm:
            continue
        b_dt = H.parse_date(p.get("생년월일"))
        h_dt = H.parse_date(p.get("입사일"))
        if not b_dt or not h_dt:
            continue
        age_at_hire = H.full_age(b_dt, h_dt)
        if age_at_hire is not None and 35 <= age_at_hire <= 40 and int(p.get("병역개월") or 0) == 0:
            c_cur = comp_cur.get(pid) or {}
            c_prev = comp_prev.get(pid) or {}
            if float(c_cur.get("b1_reg") or 0.0) > 0:
                mil_cur_impact.append(f"{nm}(입사 시 만 {age_at_hire}세, {tax_yr}년 당해 공제인원 {float(c_cur.get('b1_reg') or 0):.2f}명)")
            elif float(c_prev.get("b1_reg") or 0.0) > 0 or float(c_cur.get("b2_reg") or 0.0) > 0:
                mil_prev_only_impact.append(
                    f"{nm}(입사 시 만 {age_at_hire}세, {tax_yr}년 당해 0명 제외 · {tax_yr-1}년 최초공제 증가인원 재분류 및 {tax_yr}년 2차 연속공제 승계만 해당)"
                )

    return {
        "구법포함_신법1년미만제외_사원": under1y_pm_diff,
        "직전연도말_재직_당해중도퇴사_보수적산입_사원": conservative_prev_kept,
        "실제_연령도과_청년간주_사원": age_deemed_youth,
        "단시간_정규직_고용형태전환_사원": emp_type_converted,
        "병역차감_당해공제_영향_사원": mil_cur_impact,
        "병역차감_과거경정_사후관리_영향_사원": mil_prev_only_impact,
    }


def _build_prior_filing_discrepancy_bullets(
    s: dict,
    totals_all: dict | None = None,
    pkg: dict | None = None,
    diff_diag: dict | None = None,
) -> list[str]:
    """
    당해 공제용 직전연도 비교 인원 산정 기준(과세연도 종료일 기준 보수적 산정 및 개정 규정 적용)의 법적 근거를 생성합니다.
    (※ 기신고 vs 세법상 재계산 경정청구·수정신고 비교는 하단 `⚖️ 기신고 vs 세법상 재계산 비교` 전용 모달 창으로 분리되었습니다.)
    """
    tax_yr = int(s.get("tax_year") or R.DEFAULT_TAX_YEAR)
    if totals_all is None:
        totals_all = _ensure_totals_snapshot(s)

    ps = s.get("prev_summary") or {}
    if pkg is None:
        b = s.get("biz") or {}
        corp_sz = _cohort_corp_size(s, tax_yr)
        cap_bool = H.is_capital_area(b.get("사업장소재지", ""))
        is_cap = True if cap_bool is None else bool(cap_bool)
        p1_f = ps.get(str(tax_yr - 1)) or {}
        p2_f = ps.get(str(tax_yr - 2)) or {}
        try:
            pkg = H.calculate_tax_year_package(
                tax_year=tax_yr,
                corp_size=corp_sz,
                is_capital=is_cap,
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
                    for cohort, f in ((tax_yr - 1, p1_f), (tax_yr - 2, p2_f))
                },
                additional_inputs=s.get("additional_inputs"),
                scheme_2026=s.get("scheme_2026", "new_2026"),
                pm_basis=s.get("pm_basis", R.PM_BASIS_FILED),
                corp_size_by_year=R.get_corp_size_map(s),
            )
        except Exception:
            pkg = s.get("calc_pkg") or {}

    if diff_diag is None:
        diff_diag = _analyze_headcount_diff_reasons(s, tax_yr, totals_all=totals_all, pkg=pkg)

    bullets: list[str] = []
    prev_s = (pkg or {}).get("prev_s") or {}
    old_rule_reg = prev_s.get("old_rule_regular")
    new_rule_reg = prev_s.get("regular")
    cons_list = (diff_diag or {}).get("직전연도말_재직_당해중도퇴사_보수적산입_사원") or []

    if (old_rule_reg is not None and new_rule_reg is not None and abs(float(old_rule_reg) - float(new_rule_reg)) >= 0.01) or cons_list:
        old_r = float(old_rule_reg if old_rule_reg is not None else (new_rule_reg or 0.0))
        new_r = float(new_rule_reg or 0.0)
        r_diff = round(new_r - old_r, 2)
        cons_note = ""
        if cons_list:
            cons_note = (
                f" 특히 **{', '.join(cons_list)}**과 같이 {tax_yr-1}년 중 입사해 {tax_yr}년 중 퇴사하여 실제 총 근로기간이 1년 미만이 된 인원도 "
                f"당해({tax_yr}년) 공제 인원과 직전({tax_yr-1}년) 비교 인원에 동일한 잣대를 적용하는 **일관된 해석 기준**에 따라 "
                f"**{tax_yr-1}년 비교 인원({new_r:.2f}명)에서도 함께 제외**하였으며, 향후 2027년(B)·2028년(C) 다년도 공제 계산 시에도 매년 확정된 퇴사 사실을 반영해 비교연도 인원이 자동 재산정됩니다."
            )
        bullets.append(
            f"**{tax_yr}년 신규공제 산정용 직전연도({tax_yr-1}년) 비교 인원 일관된 해석 기준 재산정({old_r:.2f}명 → {new_r:.2f}명, {r_diff:+.2f}명) 및 다년도 자동 재산정 근거**: "
            f"{tax_yr-1}년 귀속 자체의 공제 및 사후관리에는 [부칙:조세특례제한법 부칙 제34조] (법률 제21223호) 및 [부칙:조세특례제한법 시행령 부칙 제2조] (대통령령 제35999호) 경과조치에 따라 종전 규정(**근로계약기간 1년 미만자만 제외**)이 적용되어 "
            f"**{old_r:.2f}명**으로 산정되나, **{tax_yr}년 귀속 1차년도 신규 고용증가 인원(당해 인원 − 직전 인원) 산정 시 비교하는 직전 과세연도({tax_yr-1}년) 인원**은 "
            f"당해 인원과 동일한 [조문:조세특례제한법 시행령 제26조의8 제2항] 제1호의 개정 규정(**실제 근로기간 1년 미만자 제외**)을 일관되게 적용하여 실제 근로기간 1년 미만 퇴사 확정자를 모두 제외한 **{new_r:.2f}명**을 적용하였습니다.{cons_note}"
        )

    return bullets

def _ensure_auto_pro_audit_comment(
    s: dict,
    log_tokens_fn=None,
    room_key: str = "",
    return_trace: bool = False,
) -> tuple[str, str] | tuple[str, str, dict | None]:
    """
    4단계 진입 시 버튼 클릭 없이도 『Ⅳ. 심층 세무진단 의견』이 항상 자동으로 생성·표시되도록 보장합니다.
    (법제처 API 실시간 조문 연동 + 사원별 차이원인 정밀 분해 + 국가법령정보센터 직링크 자동 결합)
    """
    _ensure_built_for_tax_year(s)
    tax_yr = int(s["tax_year"])
    shown_years = _years(s)

    computed_all, totals_all, ctx_all = {}, {}, {}
    for y in shown_years:
        _, comp_y, tot_y = _build_year_rows(s, y)
        computed_all[y] = comp_y
        totals_all[y] = tot_y
        ctx_all[y] = _ctx(s, y)

    totals_snapshot = _ensure_totals_snapshot(s)
    diff_diag = _analyze_headcount_diff_reasons(s, tax_yr, computed_all=computed_all, totals_all=totals_snapshot, pkg=s.get("calc_pkg"))
    discrepancy_bullets = _build_prior_filing_discrepancy_bullets(s, totals_all=totals_snapshot, pkg=s.get("calc_pkg"), diff_diag=diff_diag)

    # 버전 시그니처에 v4_canonical_law_verified를 포함하여 정본 산식 및 부칙 태그가 즉시 반영되게 함
    cur_sig = f"v9_quote_verified_2603|{s.get('built_sig')}|{tax_yr}|{s.get('pm_basis')}"

    def _attach_sec4_and_links(clean_body: str, tr: dict | None = None) -> str:
        out_b = _normalize_verified_legal_citations(clean_body)
        if discrepancy_bullets:
            # 기존 (4) 섹션이 있으면 최신 discrepancy_bullets로 교체하여 항상 최신 법령 근거가 반영되게 함
            out_b = re.sub(r"\n*#{3,4}\s*\(4\)\s*(?:이전\s*과세연도|직전\s*과세연도).*$", "", out_b, flags=re.DOTALL).rstrip()
            sec4_md = (
                "\n\n### (4) 직전 과세연도 비교 인원 산정 기준 및 경과조치 법령 근거\n"
                + "\n".join(f"- {_sanitize_markdown_tilde(b)}" for b in discrepancy_bullets)
            )
            out_b = (out_b + sec4_md).strip()
        if hasattr(P, "inject_verified_law_links"):
            out_b = P.inject_verified_law_links(out_b, tr)
        return out_b

    existing_raw = str(s.get("pro_audit_comment") or "").strip()
    if existing_raw and not existing_raw.startswith("❌") and s.get("pro_audit_sig") == cur_sig:
        m_qd = re.search(r"인용삭제\s*[:：]\s*(\d+)\s*건", existing_raw)
        if m_qd:
            s["pro_audit_quote_deleted_cnt"] = int(m_qd.group(1))
        body, mod_nm = _parse_and_clean_pro_audit(existing_raw)
        if body:
            if not mod_nm:
                mod_nm = str(s.get("pro_audit_model") or "gemini-2.5-pro")
            s["pro_audit_model"] = mod_nm
            res_body = _attach_sec4_and_links(body)
            return (res_body, mod_nm, None) if return_trace else (res_body, mod_nm)

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
        "사원별_차이원인_정밀분해": diff_diag,
        "결정론적_검토항목": [{"구분": lv, "내용": _strip_all_emojis(msg)} for lv, msg in review_items],
        "기신고_대비_세법원칙_차이분석": discrepancy_bullets,
    }

    raw_generated, audit_trace = P.call_pro_argon_audit_commentary(
        audit_payload, log_tokens_fn=log_tokens_fn, room_key=room_key, return_trace=True
    )
    m_qd_new = re.search(r"인용삭제\s*[:：]\s*(\d+)\s*건", str(raw_generated or ""))
    q_del_cnt = int(m_qd_new.group(1)) if m_qd_new else 0
    s["pro_audit_quote_deleted_cnt"] = q_del_cnt
    body, mod_nm = _parse_and_clean_pro_audit(raw_generated)
    if not mod_nm:
        mod_nm = "gemini-2.5-pro"
    body = _attach_sec4_and_links(body, audit_trace)
    s["pro_audit_comment"] = f"[적용 모델: {mod_nm} | 인용삭제: {q_del_cnt}건]\n\n{body}"
    s["pro_audit_model"] = mod_nm
    s["pro_audit_sig"] = cur_sig
    _save_ec_to_disk(s)
    return (body, mod_nm, audit_trace) if return_trace else (body, mod_nm)


def _build_report_markdown(
    s: dict,
    log_tokens_fn=None,
    room_key: str = "",
    trace: dict | None = None,
    audit_body: str | None = None,
) -> str:
    """
    [4단계 보고서 마크다운 생성 — 현행 법령 정합성 100% · 사원별 차이원인 자동 분해 · 일관된 해석 기준 비교인원 근거 · 법제처 직링크 결합]
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

    corp_sz = _cohort_corp_size(s, tax_yr)
    coh1_sz_s4 = _cohort_corp_size(s, tax_yr - 1, corp_sz)
    coh2_sz_s4 = _cohort_corp_size(s, tax_yr - 2, corp_sz)
    corp_sz_summary_s4 = R.format_corp_size_summary_text(s, [tax_yr - 3, tax_yr - 2, tax_yr - 1, tax_yr])
    cap_bool = H.is_capital_area(b.get("사업장소재지", ""))
    is_capital = True if cap_bool is None else bool(cap_bool)
    loc_label = "수도권" if is_capital else "수도권 외(비수도권)"
    addr_str = (b.get("사업장소재지") or "").strip()
    size_loc_disp = f"**{corp_sz_summary_s4} · {loc_label}** ({addr_str})" if addr_str else f"**{corp_sz_summary_s4} · {loc_label}**"

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
        corp_size_by_year=R.get_corp_size_map(s),
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
    yr_list = [tax_yr - 3, tax_yr - 2, tax_yr - 1, tax_yr]
    from .ui_step3 import _enrich_matrix_cols_with_cohort_consistency
    matrix_cols = _enrich_matrix_cols_with_cohort_consistency(matrix_cols, yr_list)

    pm1 = pkg["pm_y1"]
    pm2 = pkg["pm_y2"]
    cur_s = pkg["cur_s"]
    prev_s = pkg["prev_s"]
    cur_inc = pkg["cur_inc"]
    basis_lbl = pkg.get("pm_basis_label", "기신고 기준")
    b3_title, b4_title, b5_title = _block_titles_for_year(tax_yr, two_line=False)

    diff_diag = _analyze_headcount_diff_reasons(s, tax_yr, totals_all=totals_all, pkg=pkg)
    under1y_pm_names = diff_diag.get("구법포함_신법1년미만제외_사원") or []
    age_deemed_names = diff_diag.get("실제_연령도과_청년간주_사원") or []
    cons_prev_names = diff_diag.get("직전연도말_재직_당해중도퇴사_보수적산입_사원") or []

    if under1y_pm_names and age_deemed_names:
        pm_row_note = f"종전규정([부칙:조세특례제한법 부칙 제34조]·[부칙:조세특례제한법 시행령 부칙 제2조]: {', '.join(under1y_pm_names)}) 및 연령경과 간주({', '.join(age_deemed_names)}) [각주 2, 3]"
    elif under1y_pm_names:
        pm_row_note = f"{tax_yr-1}·{tax_yr-2}년분 사후관리 종전규정 적용 ([부칙:조세특례제한법 부칙 제34조]·[부칙:조세특례제한법 시행령 부칙 제2조]: {', '.join(under1y_pm_names)}) [각주 2, 3]"
    elif age_deemed_names:
        pm_row_note = f"입사 당시 청년 연령경과 간주 특례 ({', '.join(age_deemed_names)}) [각주 3]"
    else:
        pm_row_note = "[부칙:조세특례제한법 부칙 제34조]·[부칙:조세특례제한법 시행령 부칙 제2조] 경과조치(종전규정) 적용 [각주 2, 3]"

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

    def _m_txt(cr: int, cl: int, is_na: bool = False, needs_check: bool = False) -> str:
        if is_na:
            return "-"
        cr_i, cl_i = int(cr or 0), int(cl or 0)
        if cr_i == 0 and cl_i == 0 and needs_check:
            return "*(신고서 확인 필요)*"
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
        scheme_desc = f"현행 [조문:조세특례제한법 제29조의8 제1항] 점증형(A+B+C) 구조 ({tax_yr}년은 비교연도가 {tax_yr-1}년[A]뿐이므로 1년차 단가 적용 · 신법분 추징 없음) [각주 1]"
    else:
        r_leg = pkg["rates_legacy"]
        yu, gu = r_leg["청년등"] * 10_000, r_leg["청년등외"] * 10_000
        scheme_desc = "[조문:조세특례제한법 제29조의8 제1항] 기본공제 단가 [각주 1]"

    pm1_reg_dec = "여(감소)" if (pm1.get("active") and not pm1.get("base_missing") and cur_s["b2_reg"] < pm1.get("init_reg", 0)) else "부(유지·증가)"
    pm1_yth_dec = "여(감소)" if (pm1.get("active") and not pm1.get("base_missing") and cur_s["b2_yth"] < pm1.get("init_yth", 0)) else "부(유지·증가)"
    pm2_reg_dec = "여(감소)" if (pm2.get("active") and not pm2.get("base_missing") and cur_s["b3_reg"] < pm2.get("init_reg", 0)) else "부(유지·증가)"
    pm2_yth_dec = "여(감소)" if (pm2.get("active") and not pm2.get("base_missing") and cur_s["b3_yth"] < pm2.get("init_yth", 0)) else "부(유지·증가)"

    # 2024년·2025년 최초공제 당시 소재지가 현재 소재지와 다른 경우(예: 2024년 비수도권 1,550만원 → 2025년 초 수도권 이전) 주석 생성
    coh1_cap = p1.get("수도권")
    coh2_cap = p2.get("수도권")
    pm1_loc_note = ""
    if coh1_cap is not None and bool(coh1_cap) != is_capital:
        c1_lbl = "수도권" if coh1_cap else "수도권 외(비수도권)"
        pm1_loc_note = f" *(※ {tax_yr-1}년 최초 공제 당시 {c1_lbl} 소재 기준 단가 적용 — 이후 {loc_label} 이전)*"
    pm2_loc_note = ""
    if coh2_cap is not None and bool(coh2_cap) != is_capital:
        c2_lbl = "수도권" if coh2_cap else "수도권 외(비수도권)"
        pm2_loc_note = f" *(※ {tax_yr-2}년 최초 공제 당시 {c2_lbl} 소재 기준 단가[청년등 1,550만원·일반 950만원] 적용 — 이후 {loc_label} 이전)*"

    if audit_body is None:
        audit_body, _, _ensured_trace = _ensure_auto_pro_audit_comment(
            s, log_tokens_fn=log_tokens_fn, room_key=room_key, return_trace=True
        )
        if trace is None:
            trace = _ensured_trace

    # [Section 3 & 4] trace가 전달된 경우 재사용하고, 없을 때만 law_api를 조회하여 중복 조회 제거
    if trace is not None:
        _rep_trace = trace
    else:
        _, _rep_trace = P._fetch_live_employment_law_context() if hasattr(P, "_fetch_live_employment_law_context") else ("", None)
    _mutatis_verified = P.is_26_8_6_mutatis_verified(_rep_trace) if hasattr(P, "is_26_8_6_mutatis_verified") else False
    _mutatis_sent = P.get_verified_26_8_6_mutatis_sentence(_rep_trace) if hasattr(P, "get_verified_26_8_6_mutatis_sentence") else ""
    if _mutatis_verified and _mutatis_sent:
        _calc_law_cite = (
            f'[조문:조세특례제한법 시행령 제26조의8 제6항] ("{_mutatis_sent}" — [조문:조세특례제한법 시행령 제11조의2 제8항] 준용), '
            "국세청 '26.3월 안내(A/B 적용 구분)"
        )
    elif _mutatis_verified:
        _calc_law_cite = "[조문:조세특례제한법 시행령 제26조의8 제6항] ([조문:조세특례제한법 시행령 제11조의2 제8항] 준용), 국세청 '26.3월 안내(A/B 적용 구분)"
    else:
        _calc_law_cite = "[조문:조세특례제한법 시행령 제26조의8 제6항], 국세청 '26.3월 안내(A/B 적용 구분)"
    _ext_trust_note = (
        " (# 확인 필요: '26.3월 국세청 안내 신뢰보호 원칙 연장 적용)"
        if tax_yr >= 2026
        else ""
    )
    _ruling_a_line = P._get_ruling_verbatim_line("국세청_2026_03_상시근로자수_계산안내", "기존(A방식):")
    _ruling_b_line = P._get_ruling_verbatim_line("국세청_2026_03_상시근로자수_계산안내", "현행(개정)(B방식):")
    _form_10_line = P._get_ruling_verbatim_line("조특칙_별지_제10호의10_서식", "⑩")

    prev_basis_bullets = [
        f"- **상시근로자 수 계산방식(A/B) 이원화 및 신뢰보호 적용 구분**: {_calc_law_cite} 및 [부칙:조세특례제한법 시행령 부칙 제11조] (2026.2.27.)에 따라 **2025년 이후 최초 공제 코호트**(당해 1차 공제 및 신법 A·B·C, 상시근로자 현황 직전전·직전·해당, 추가공제 요건)는 **{_ruling_b_line}**을 적용하고, **2024년 이하 최초 공제 코호트**의 2·3차년도 연속공제·사후관리 요건은 신뢰보호 원칙에 따라 **{_ruling_a_line}**을 적용하였습니다{_ext_trust_note}.",
        f"- **청년등 외 상시근로자 수 정본(Canonical) 산식 근거 및 청년등 증가인원 한도(Cap)**: [조문:조세특례제한법 제29조의8 제1항] 제2호(청년등상시근로자 외의 상시근로자) 및 조세특례제한법 시행규칙 별지 제10호의10서식 **{_form_10_line}**에 따라 정본으로 산정하고(직전연도 {prev_s['regular']:.2f}명 − {prev_s['youth']:.2f}명 = **{prev_s['non_youth']:.2f}명**, 당해연도 {cur_s['regular']:.2f}명 − {cur_s['youth']:.2f}명 = **{cur_s['non_youth']:.2f}명**), 청년등 외 증가인원을 **{cur_s['non_youth']:.2f}명 − {prev_s['non_youth']:.2f}명 = +{cur_inc['non_youth_inc']:.2f}명**으로 산출하여 **전체 증가인원(+{cur_inc['total_inc']:.2f}명) = 청년등 증가(+{cur_inc['youth_inc']:.2f}명) + 청년등 외 증가(+{cur_inc['non_youth_inc']:.2f}명)** 항등식을 0.01명 단수 오차 없이 일치시켰습니다. 아울러 청년등 상시근로자 증가인원(+{cur_inc['youth_inc']:.2f}명)은 **[조문:조세특례제한법 제29조의8 제1항] 제1호 괄호 규정**에 따라 전체 상시근로자 증가인원(+{cur_inc['total_inc']:.2f}명)을 한도로 적용하였습니다.",
    ]
    if prev_s.get("old_rule_regular") is not None or cons_prev_names:
        old_rv = float(prev_s.get("old_rule_regular") if prev_s.get("old_rule_regular") is not None else prev_s["regular"])
        cons_detail = (
            f" 이때 **{', '.join(cons_prev_names)}**과 같이 {tax_yr-1}년 중 입사하여 {tax_yr}년 중 퇴사함으로써 실제 총 근로기간이 1년 미만이 된 인원도 "
            f"당해({tax_yr}년) 공제 인원과 직전({tax_yr-1}년) 비교 인원을 동일한 기준으로 산정하는 **일관된 해석 기준**에 따라 "
            f"{tax_yr-1}년 비교 인원(**{prev_s['regular']:.2f}명**)과 {tax_yr}년 당해 인원(**{cur_s['regular']:.2f}명**)에서 모두 제외하였으며(2027년 B·2028년 C 다년도 비교 시에도 확정된 퇴사 사실 자동 반영), "
            f"종전 규정이 적용되는 {tax_yr-1}년분 2차 사후관리 인원(**{cur_s['b2_reg']:.2f}명**)에만 산입하였습니다."
            if cons_prev_names else ""
        )
        prev_basis_bullets.append(
            f"- **{tax_yr}년 공제용 직전연도({tax_yr-1}년) 비교 인원 일관된 해석 기준 ({prev_s['regular']:.2f}명)**: "
            f"{tax_yr-1}년 귀속 자체 및 사후관리용 인원(**{old_rv:.2f}명**)은 [부칙:조세특례제한법 부칙 제34조] (법률 제21223호) 및 [부칙:조세특례제한법 시행령 부칙 제2조] (대통령령 제35999호) 경과조치에 따라 종전 규정(근로계약기간 1년 미만 제외)을 적용하고, "
            f"{tax_yr}년 신규 공제 산정을 위한 직전연도({tax_yr-1}년) 비교 인원(**{prev_s['regular']:.2f}명**)은 당해 인원과 동일한 개정 규정([조문:조세특례제한법 시행령 제26조의8 제2항] 제1호: 실제 근로기간 1년 미만 퇴사 확정자 제외)으로 일관되게 재산정하였습니다.{cons_detail}"
        )
    if abs(cur_s["b2_yth"] - cur_s["youth"]) >= 0.01 or under1y_pm_names:
        prev_basis_bullets.append(
            f"- **사후관리 인원({cur_s['b2_yth']:.2f}명)과 당해 공제 인원({cur_s['youth']:.2f}명) 차이 원인**: "
            + (
                f"두 수치의 차이(**{cur_s['b2_yth'] - cur_s['youth']:+.2f}명**)는 연령경과 간주 때문이 아니라, "
                f"**{', '.join(under1y_pm_names)}** 사원이 {tax_yr-1}·{tax_yr-2}년분 사후관리에는 [부칙:조세특례제한법 시행령 부칙 제2조] (대통령령 제35999호 경과조치: 근로계약기간 1년 이상 포함)에 따라 산입되고, "
                f"{tax_yr}년 당해 공제에서는 개정 규정([조문:조세특례제한법 시행령 제26조의8 제2항] 제1호: 실제 근로기간 1년 미만 제외)에 따라 제외된 결과입니다."
                if under1y_pm_names else
                f"최초 공제연도 기준 청년등 사후관리 특례(구 조특령[대통령령 제36127호 개정 전] 제26조의8 제5항, [부칙:조세특례제한법 시행령 부칙 제11조] 경과조치) 적용 결과입니다."
            )
        )

    cf_note_str = (
        f"당해 최저한세([조문:조세특례제한법 제132조]) 등 미공제 이월액 {pkg['cur_unclaimed_cf_won']:,}원 반영 ([조문:조세특례제한법 제144조] 10년 이월공제)"
        if pkg.get("cur_unclaimed_cf_won", 0) > 0
        else "미공제 이월액 0원 가정 시 금액 (산출세액 및 [조문:조세특례제한법 제132조] 최저한세[중소 7%] 한도 초과분은 [조문:조세특례제한법 제144조]에 따라 10년 이월공제되며 당기 농특세 비과세)"
    )

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
        f"| **1. 당해({tax_yr}년) 1차년도 신규 고용증가 세액공제** | **{pkg['cur_base_credit_won']:,}원** | 청년등 +{pkg['cur_inc']['youth_inc']:.2f}명, 청년등 외 +{pkg['cur_inc']['non_youth_inc']:.2f}명 ([조문:조세특례제한법 제29조의8 제1항] [각주 1]) |",
        f"| **2. 직전·전전연도({tax_yr-1}·{tax_yr-2}년) 기공제분 연속공제액** | **{pkg['total_continued_credit_won']:,}원** | 2차년도 {pm1['continued_credit_won']:,}원 + 3차년도 {pm2['continued_credit_won']:,}원 (구 조특법 제29조의8 제1항 · [부칙:조세특례제한법 부칙 제34조] [각주 3]) |",
        f"| **3. 육아휴직 복귀 및 정규직 전환 추가공제액** | **{pkg['additional_credit_won']:,}원** | 복귀 {pkg['parental_ret_cnt']}명(제5항) / 전환 {pkg['reg_conv_cnt']}명(제4항, ~2024년 전환분 한정) ([조문:조세특례제한법 제29조의8 제4항]·[조문:조세특례제한법 제29조의8 제5항]) |",
        f"| **합계: 당해 총 공제세액 (1+2+3)** | **{pkg['total_credit_gross_won']:,}원** | **공제감면세액계산서 및 세액공제신청서 반영 금액** |",
        f"| **4. 사후관리 추가납부세액 (이월공제 차감 후)** | **{pkg['total_clawback_net_payable_won']:,}원** | 차감전 추징액 {pkg['total_clawback_gross_won']:,}원 − 미공제 이월세액 소멸 {pkg['total_carryforward_offset_won']:,}원 (구 조특법 제29조의8 제3항 · [부칙:조세특례제한법 부칙 제34조] [각주 4, 5]) |",
        f"| **5. 농어촌특별세 (실공제세액의 20%)** | **{pkg['rural_special_tax_won']:,}원** | 실공제 {pkg['actual_deducted_credit_won']:,}원 기준 ([조문:농어촌특별세법 제5조 제1항] [각주 7]) |",
        f"| **최종 실질 순절세액 (합계 − 4 − 5)** | **{pkg['net_after_rural_tax_won']:,}원** | **{cf_note_str}** |",
        "",
        f"### (3) 4개 과세연도({tax_yr-3}~{tax_yr}년) 세액공제 및 추가납부세액 총괄표",
        "",
        f"| 구분 | 차수 | {yr_list[0]}년 ({R.format_corp_size_label(_cohort_corp_size(s, yr_list[0]), short=True)}) | {yr_list[1]}년 ({R.format_corp_size_label(_cohort_corp_size(s, yr_list[1]), short=True)}) | {yr_list[2]}년 ({R.format_corp_size_label(_cohort_corp_size(s, yr_list[2]), short=True)}) | {yr_list[3]}년 ({R.format_corp_size_label(_cohort_corp_size(s, yr_list[3]), short=True)} · 당해) | 근거 법령 |",
        "| :---: | :---: | ---: | ---: | ---: | ---: | :--- |",
        f"| **세액공제액 (추가납부액)** | **1차** | {_m_txt(matrix_cols[yr_list[0]]['r1_credit'], matrix_cols[yr_list[0]]['r1_claw'], bool(matrix_cols[yr_list[0]].get('r1_na')), bool(matrix_cols[yr_list[0]].get('r1_needs_check')))} | {_m_txt(matrix_cols[yr_list[1]]['r1_credit'], matrix_cols[yr_list[1]]['r1_claw'], bool(matrix_cols[yr_list[1]].get('r1_na')), bool(matrix_cols[yr_list[1]].get('r1_needs_check')))} | {_m_txt(matrix_cols[yr_list[2]]['r1_credit'], matrix_cols[yr_list[2]]['r1_claw'], bool(matrix_cols[yr_list[2]].get('r1_na')), bool(matrix_cols[yr_list[2]].get('r1_needs_check')))} | **{_m_txt(matrix_cols[yr_list[3]]['r1_credit'], matrix_cols[yr_list[3]]['r1_claw'])}** | [조문:조세특례제한법 제29조의8 제1항] [각주 1] |",
        f"| **세액공제액 (추가납부액)** | **2차** | {_m_txt(matrix_cols[yr_list[0]]['r2_credit'], matrix_cols[yr_list[0]]['r2_claw'], bool(matrix_cols[yr_list[0]].get('r2_na')))} | {_m_txt(matrix_cols[yr_list[1]]['r2_credit'], matrix_cols[yr_list[1]]['r2_claw'], bool(matrix_cols[yr_list[1]].get('r2_na')))} | {_m_txt(matrix_cols[yr_list[2]]['r2_credit'], matrix_cols[yr_list[2]]['r2_claw'], bool(matrix_cols[yr_list[2]].get('r2_na')))} | **{_m_txt(matrix_cols[yr_list[3]]['r2_credit'], matrix_cols[yr_list[3]]['r2_claw'])}** | 구 조특법 제29조의8 제1항·제3항 ([부칙:조세특례제한법 부칙 제34조]) [각주 3, 4] |",
        f"| **세액공제액 (추가납부액)** | **3차** | {_m_txt(matrix_cols[yr_list[0]]['r3_credit'], matrix_cols[yr_list[0]]['r3_claw'], bool(matrix_cols[yr_list[0]].get('r3_na')))} | {_m_txt(matrix_cols[yr_list[1]]['r3_credit'], matrix_cols[yr_list[1]]['r3_claw'], bool(matrix_cols[yr_list[1]].get('r3_na')))} | {_m_txt(matrix_cols[yr_list[2]]['r3_credit'], matrix_cols[yr_list[2]]['r3_claw'], bool(matrix_cols[yr_list[2]].get('r3_na')))} | **{_m_txt(matrix_cols[yr_list[3]]['r3_credit'], matrix_cols[yr_list[3]]['r3_claw'])}** | 구 조특법 제29조의8 제1항·제3항 ([부칙:조세특례제한법 부칙 제34조]) [각주 3, 4] |",
        f"| **합계** | **순액** | **{int(matrix_cols[yr_list[0]]['net_total']):,}원** | **{int(matrix_cols[yr_list[1]]['net_total']):,}원** | **{int(matrix_cols[yr_list[2]]['net_total']):,}원** | **{int(matrix_cols[yr_list[3]]['net_total']):,}원** | [조문:조세특례제한법 제132조] · [조문:조세특례제한법 제144조] [각주 5] |",
        "",
        f"## Ⅱ. {tax_yr}년 귀속 세액공제 및 사후관리 상세 산출근거",
        f"### (1) 평균 상시근로자 증가 인원 및 코호트별 상시근로자 현황 [각주 1, 2, 3]",
        *prev_basis_bullets,
        "",
        "| 구분 | 전체 상시<br>[총인원 / 평균] | 청년등<br>[총인원 / 평균] | 청년등 외<br>[총인원 / 평균] | 산정 기준 및 법령 근거 |",
        "| :--- | ---: | ---: | ---: | :--- |",
        f"| **{tax_yr}년 귀속 [{b3_title}]** | {cur_s['reg_total']:g}명 / **{cur_s['regular']:.2f}명** | {cur_s['yth_total']:g}명 / **{cur_s['youth']:.2f}명** | {cur_s['non_youth_total']:g}명 / **{cur_s['non_youth']:.2f}명** | 신법(실제 근로기간 1년 미만 제외 · {R.calc_method_badge_label(tax_yr)}) [각주 2] |",
        f"| **{tax_yr}년 귀속 [{b4_title}]** | {cur_s['reg_total']:g}명 / **{cur_s['b2_reg']:.2f}명** | {cur_s['b2_yth_total']:g}명 / **{cur_s['b2_yth']:.2f}명** | {round(max(0.0, cur_s['reg_total']-cur_s['b2_yth_total']),2):g}명 / **{round(max(0.0, cur_s['b2_reg']-cur_s['b2_yth']),2):.2f}명** | {pm_row_note} |",
        f"| **{tax_yr}년 귀속 [{b5_title}]** | {cur_s['reg_total']:g}명 / **{cur_s['b3_reg']:.2f}명** | {cur_s['b3_yth_total']:g}명 / **{cur_s['b3_yth']:.2f}명** | {round(max(0.0, cur_s['reg_total']-cur_s['b3_yth_total']),2):g}명 / **{round(max(0.0, cur_s['b3_reg']-cur_s['b3_yth']),2):.2f}명** | {pm_row_note} |",
        f"| **{tax_yr-1}년 사후관리 기초 ({basis_lbl})** | - / **{pm1['init_reg']:.2f}명** | - / **{pm1['init_yth']:.2f}명** | - / **{round(max(0.0, pm1['init_reg']-pm1['init_yth']),2):.2f}명** | 1차 사후관리 비교 기준 (증가 청년 {pm1['init_yth_inc']:.2f}명 · 일반 {pm1['init_gen_inc']:.2f}명) |",
        f"| **{tax_yr-2}년 사후관리 기초 ({basis_lbl})** | - / **{pm2['init_reg']:.2f}명** | - / **{pm2['init_yth']:.2f}명** | - / **{round(max(0.0, pm2['init_reg']-pm2['init_yth']),2):.2f}명** | 2차 사후관리 비교 기준 (증가 청년 {pm2['init_yth_inc']:.2f}명 · 일반 {pm2['init_gen_inc']:.2f}명){pm2_loc_note} |",
        "",
        f"### (2) 1차년도({tax_yr}년 귀속) 세액공제액 계산 ({R.format_corp_size_label(corp_sz)}, {loc_label} · {R.calc_method_badge_label(tax_yr)}) [각주 1]",
        f"- **신법 산식 구조 및 적용 단가**: 현행 [조문:조세특례제한법 제29조의8 제1항]은 직전 3개 과세연도(2024.12.31. 이전 개시 과세연도 제외) 중 1개 이상 대비 상시근로자 수가 증가한 경우 `A(직전연도 대비 1년차 증가분) + B(전전연도 대비 2년차 유지분) + C(전전전연도 대비 3년차 유지분)`를 합산하도록 규정하고 있습니다. {tax_yr}년 귀속은 비교 대상 과세연도가 {tax_yr-1}년(A)뿐이므로 A만 적용되며(청년등 1인당 **{yu:,}원**, 청년등 외 1인당 **{gu:,}원**), {tax_yr}년 신법 공제분은 사후관리 추징 규정이 적용되지 않습니다(고용 감소에 따른 추징 리스크는 2024·2025년 귀속분에 한정).",
        f"- **계산 산식**: (청년등 증가 {cur_inc['youth_inc']:.2f}명 × {yu:,}원) + (청년등 외 증가 {cur_inc['non_youth_inc']:.2f}명 × {gu:,}원)"
        + (f" − 최소고용증가인원 차감([조문:조세특례제한법 시행령 제26조의8 제3항]) {pkg['cur_new_ded_won']:,}원" if pkg.get("cur_new_ded_won", 0) > 0 else "")
        + f" = **{pkg['cur_base_credit_won']:,}원**",
        "",
        f"### (3) 2차년도 사후관리 계산 ({tax_yr-1}년 귀속 · {R.format_corp_size_label(coh1_sz_s4)} → {tax_yr}년 1차 사후관리 · {R.calc_method_badge_label(tax_yr-1)}) [각주 3, 4]",
        f"- **감소 여부 판정**: 1차년도({tax_yr-1}년) 대비 전체 상시근로자 감소 여부 **{pm1_reg_dec}** ({pm1.get('init_reg', 0):.2f}명 → {cur_s['b2_reg']:.2f}명) / 청년등 상시근로자 감소 여부 **{pm1_yth_dec}** ({pm1.get('init_yth', 0):.2f}명 → {cur_s['b2_yth']:.2f}명)",
        f"- **산출 내역 ({pm1.get('case_code')})**: {_strip_all_emojis(pm1.get('formula_note', ''))}{pm1_loc_note}",
        f"- **산출 세액**: 2차년도 연속공제액 **+{pm1.get('continued_credit_won', 0):,}원** / 1차 사후관리 추가납부세액 **-{pm1.get('clawback_net_payable_won', 0):,}원**",
        "",
        f"### (4) 3차년도 사후관리 계산 ({tax_yr-2}년 귀속 · {R.format_corp_size_label(coh2_sz_s4)} → {tax_yr}년 2차 사후관리 · {R.calc_method_badge_label(tax_yr-2)}{_ext_trust_note}) [각주 3, 4]",
        f"- **감소 여부 판정**: 1차년도({tax_yr-2}년) 대비 전체 상시근로자 감소 여부 **{pm2_reg_dec}** ({pm2.get('init_reg', 0):.2f}명 → {cur_s['b3_reg']:.2f}명) / 청년등 상시근로자 감소 여부 **{pm2_yth_dec}** ({pm2.get('init_yth', 0):.2f}명 → {cur_s['b3_yth']:.2f}명)",
        f"- **산출 내역 ({pm2.get('case_code')})**: {_strip_all_emojis(pm2.get('formula_note', ''))}{pm2_loc_note}",
        f"- **산출 세액**: 3차년도 연속공제액 **+{pm2.get('continued_credit_won', 0):,}원** / 2차 사후관리 추가납부세액 **-{pm2.get('clawback_net_payable_won', 0):,}원**",
        "",
        "## Ⅲ. 계산근거 관련 법령 주석",
        "### (1) 기본공제·청년등 증가한도(Cap)·상시근로자 범위 및 소수점 절사 규정",
        "- **[각주 1] [조문:조세특례제한법 제29조의8 제1항]·[조문:조세특례제한법 제29조의8 제2항]·[조문:조세특례제한법 제29조의8 제4항]·[조문:조세특례제한법 제29조의8 제5항] (통합고용세액공제 기본공제 A+B+C 구조 · 청년등 증가인원 한도 Cap · 경력단절 정의 · 전환 및 복귀 추가공제)**: 소비성서비스업 등 제외 업종([조문:조세특례제한법 시행령 제26조의8 제1항]) 외의 내국인이 직전 3개 과세연도(2024.12.31. 이전 개시 과세연도 제외) 중 1개 이상 대비 상시근로자 수가 증가한 경우 1년차(A, 중소 수도권 청년등 700만·일반 400만 / 비수도권 청년등 1,000만·일반 700만), 2년차(B), 3년차(C) 유지분 금액을 합한 금액(중견 5명·대기업 10명 최소고용증가인원 차감 반영, [조문:조세특례제한법 시행령 제26조의8 제3항])을 공제한다. 이때 제1항 제1호(청년등상시근로자: 가목 중소기업·나목 중견기업·다목 그 외 기업) 및 제2호(청년등외상시근로자: 가목 중소기업·나목 중견기업, 다목 없음[일반기업 0원]) 각 목의 계산식 중 A·B·C 증가·유지 인원 수는 **전체 상시근로자의 증가 인원 수를 한도(Cap)로 하며(제1항 제1호·제2호 각 호 외의 부분 괄호)**, 제2항은 제1항 제1호의 청년등 상시근로자에 포함되는 경력단절 근로자의 요건을 규정하고, 별도 추가공제로서 제4항은 정규직 전환 추가공제(2024.12.31. 이전 전환분까지만 적용), 제5항은 육아휴직 복귀자 추가공제를 규정한다.",
f"- **[각주 2] [조문:조세특례제한법 시행령 제26조의8 제2항]·[조문:조세특례제한법 시행령 제26조의8 제4항]·{_calc_law_cite} (상시근로자 및 청년등 범위 · 상시근로자 수 계산방식 A/B 적용 구분 및 청년등 외 정본 산식)**: 상시근로자란 근로기준법에 따라 근로계약을 체결한 내국인 근로자([조문:조세특례제한법 제2조] 제1항 제1호 및 국세청 사전-2020-법령해석소득-0239에 따라 국적과 무관하게 소득세법상 국내에 주소를 두거나 183일 이상 거소를 둔 거주자인 외국인 근로자 포함) 중 근로기간 1년 미만인 근로자(제2항 제1호), 월평균 60시간 미만 단시간근로자(제2호), 법인의 임원(제3호), 최대주주·최대출자자와 그 배우자(제4호), 직계존비속 및 친족(제5호), 원천징수 및 4대보험 납부 미확인자(제6호)를 제외한 자를 말한다. 상시근로자 수 계산은 {_calc_law_cite}에 따라 **2025년 이후 최초 공제 코호트**는 **{_ruling_b_line}**을, **2024년 이하 최초 공제 코호트**의 2·3차년도 요건·연속공제·사후관리는 신뢰보호 원칙에 따라 **{_ruling_a_line}**을 적용한다{_ext_trust_note}. 이때 청년등 외 상시근로자 수는 [조문:조세특례제한법 제29조의8 제1항] 제2호 및 시행규칙 별지 제10호의10서식 **{_form_10_line}**에 따라 산정한다.",
        "",
        "### (2) 구법 경과조치(연속공제·추가납부·청년 유예기간) 및 최저한세·이월공제·고용승계 특례 규정",
        "- **[각주 3] 구 조세특례제한법(2025.12.23. 법률 제21223호 개정 전) 제29조의8 제1항, [부칙:조세특례제한법 부칙 제34조] 및 [부칙:조세특례제한법 시행령 부칙 제2조] (대통령령 제35999호)·[부칙:조세특례제한법 시행령 부칙 제11조] (2026.2.27., 대통령령 제36127호) (2024·2025년 귀속분 2·3차년도 연속공제·사후관리 및 청년 유예기간)**: **[부칙:조세특례제한법 부칙 제34조] (법률 제21223호)** 및 같은 법 시행령 부칙에 따라, 2024년 또는 2025년 과세연도에 상시근로자 수가 증가한 분에 대한 이후 2년간(대기업 1년간)의 연속공제 및 사후관리는 종전의 규정에 따른다. 또한 **[부칙:조세특례제한법 시행령 부칙 제11조] (2026.2.27.)** 제1항에 따라 제26조의8 제4항 제1호 개정규정(계약체결일 기준 청년 간주: 2026.1.1. 이후 계약자 중소·중견 4년 / 일반 3년)은 2025.1.1. 이후 개시하는 과세연도를 최초 공제연도로 하여 신청하는 경우부터 적용(2024년 이전 최초 공제 코호트에는 미적용)하며, 같은 조 제2항에 따라 **2025.1.1.~2025.12.31. 근로계약 체결 당시 34세 이하(병역기간 최대 6년 차감)인 사람은 계약 체결일부터 3년간(중소·중견기업이 아닌 경우 2년간) 청년등상시근로자로 본다**.",
        "- **[각주 4] 구 조세특례제한법(법률 제21223호 개정 전) 제29조의8 제2항(2024년 귀속)·제3항(2025년 귀속), 구 시행령(대통령령 제36127호 개정 전) 제26조의8 제4항 및 [부칙:조세특례제한법 부칙 제34조] (고용 감소 시 추가납부세액 산식 및 이자상당가산액 면제)**: 현행 제29조의8에서 구 추징 조항은 삭제되었으나 [부칙:조세특례제한법 부칙 제34조] (법률 제21223호)에 따라 2024·2025년 귀속 공제분(종전 규정 적용 대상)에 대하여 최초로 공제를 받은 과세연도의 종료일부터 2년이 되는 날이 속하는 과세연도의 종료일까지(기업규모 구분 없이 2년 사후관리) 전체 상시근로자 수가 감소한 경우 연속공제를 중단하고 감소 인원분 공제세액을 추가납부하며(Case 1·Case 2), 전체 상시근로자 수는 유지되었으나 청년등 상시근로자 수만 감소한 경우(Case 3)에는 청년등 단가와 일반 단가의 차액만을 추가납부한다(기공제세액 한도, 이자상당가산액 미부과). 반면 2026년 이후 신법(제1항 A+B+C 구조) 적용분은 사후관리 추징 규정이 없다.",
        "- **[각주 5] [조문:조세특례제한법 제132조] 및 [조문:조세특례제한법 제144조] (최저한세 적용 및 10년 이월공제 · 미공제 이월세액 우선 소멸)**: 통합고용세액공제는 [조문:조세특례제한법 제132조]에 따른 최저한세(중소기업 과세표준의 7%, 중견기업 8~9%[초기 유예구간]·10~17%, 일반기업 10~17%) 적용 대상이므로, 당기 산출세액에서 최저한세 한도를 초과하여 공제받지 못한 세액은 [조문:조세특례제한법 제144조] 제1항에 따라 10년간 이월공제한다. 또한 사후관리 위반으로 추가납부 사유가 발생하였으나 당초 공제받지 못하고 이월된 세액공제액이 남아 있는 경우 현금 추가납부 대신 해당 미공제 이월세액을 먼저 차감(소멸)한다.",
        "- **[각주 6] [조문:조세특례제한법 시행령 제26조의8 제8항] 및 [조문:조세특례제한법 시행령 제23조 제13항] 준용 (창업·포괄양수·합병·분할·법인전환 고용승계 특례)**: 과세연도 중 사업을 포괄양수하거나 합병·분할·현물출자·법인전환에 따라 고용을 승계한 기업의 직전 과세연도 상시근로자 수는 기존 사업장 직전 인원에 승계 사업장 직전 인원을 더한 수로 하고, 당해 과세연도에는 과세연도 개시일에 승계한 것으로 보아 근무기간을 통산한다.",
        "- **[각주 7] [조문:농어촌특별세법 제5조 제1항] 제1호 (농어촌특별세 20%)**: 조세특례제한법에 따라 당기 실제로 감면(공제)받는 소득세·법인세 세액(최저한세 등으로 당기 공제받지 못하고 이월된 미공제 세액은 제외하며 실제 이월공제받는 연도에 과세)의 **100분의 20**을 농어촌특별세로 납부한다.",
        "",
        "## Ⅳ. 심층 세무진단 의견",
        audit_body,
        "",
        f"<div style='color:#64748b;font-size:0.84rem;margin-top:8px;'>※ 원문 대조 불일치 인용 삭제: {int(s.get('pro_audit_quote_deleted_cnt') or 0)}건</div>",
    ]
    full_md = _sanitize_markdown_tilde("\n".join(lines))
    if hasattr(P, "inject_verified_law_links"):
        full_md = P.inject_verified_law_links(full_md, _rep_trace)
    return full_md


def _build_report_pdf_bytes(s: dict, log_tokens_fn=None, room_key: str = "", md_text: str | None = None) -> bytes:
    """
    4단계 『보고서 PDF 다운』 전용 빌더 — 자율 에이전트AI(`app.py`의 `create_pdf_report`)와
    여백(좌우 40pt, 상 42pt, 하 48pt), 제목(DocH2 13pt #1f4e78), 소제목(DocH3 11pt #2e5cb8),
    본문(DocBody 9.8pt / 줄간격 15.5pt / wordWrap='CJK'), 불릿(leftIndent=12, firstLineIndent=-8),
    표(연회색 헤더 #e2e8f0 + 교차 행 #f8fafc + 얇은 테두리 #cbd5e1 + 상단 정렬),
    법령 태그 표시(`[조문: ...]`, `[부칙: ...]`), 하단 면책문구 및 우측 페이지 번호까지 100% 일치시킵니다.
    """
    _ensure_built_for_tax_year(s)
    reg_font, bold_font = _ensure_korean_pdf_font()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=40,
        rightMargin=40,
        topMargin=42,
        bottomMargin=48,
    )
    usable_width = A4[0] - 80

    styles = getSampleStyleSheet()
    style_h2 = ParagraphStyle(
        "DocH2",
        parent=styles["Normal"],
        fontName=bold_font,
        fontSize=13,
        leading=19,
        textColor=colors.HexColor("#1f4e78"),
        spaceBefore=12,
        spaceAfter=6,
        keepWithNext=True,
    )
    style_h3 = ParagraphStyle(
        "DocH3",
        parent=styles["Normal"],
        fontName=bold_font,
        fontSize=11,
        leading=16,
        textColor=colors.HexColor("#2e5cb8"),
        spaceBefore=10,
        spaceAfter=4,
        keepWithNext=True,
    )
    style_body = ParagraphStyle(
        "DocBody",
        parent=styles["Normal"],
        fontName=reg_font,
        fontSize=9.8,
        leading=15.5,
        textColor=colors.HexColor("#1e293b"),
        spaceAfter=4,
        wordWrap="CJK",
    )
    style_bullet = ParagraphStyle(
        "DocBullet",
        parent=style_body,
        leftIndent=12,
        firstLineIndent=-8,
        spaceAfter=3.5,
    )
    style_th = ParagraphStyle(
        "DocTH",
        parent=style_body,
        fontName=bold_font,
        fontSize=9.2,
        leading=13.5,
        textColor=colors.HexColor("#0f172a"),
        alignment=0,
    )
    style_td = ParagraphStyle(
        "DocTD",
        parent=style_body,
        fontName=reg_font,
        fontSize=9.0,
        leading=13.5,
        textColor=colors.HexColor("#1e293b"),
        alignment=0,
    )

    md_full = md_text if md_text is not None else _build_report_markdown(s, log_tokens_fn=log_tokens_fn, room_key=room_key)
    # 마크다운 링크 `[텍스트](https://...)`에서 URL 괄호를 벗기고 `[조문: ...]` 등 본문 텍스트만 깔끔하게 보존
    md_full = re.sub(
        r"\[(\[(?:조문|부칙|별표|판례|심판례|헌재|헌재결정례|해석례|예규)\s*:\s*[^\]]+\])\]\(https?://[^\s)]+\)",
        r"\1",
        md_full,
    )
    md_full = re.sub(r"\[([^\]]+)\]\(https?://[^\s)]+\)", r"\1", md_full)
    story = []

    raw_lines = md_full.splitlines()
    i = 0
    while i < len(raw_lines):
        line = raw_lines[i]
        stripped = _strip_all_emojis(line).strip()

        if not stripped:
            story.append(Spacer(1, 4))
            i += 1
            continue

        if stripped.startswith("<div") and "원문 대조 불일치 인용 삭제:" in stripped:
            stripped = re.sub(r"<[^>]+>", "", stripped).strip()
        if stripped.startswith(">") or "적용 모델:" in stripped or "적용모델:" in stripped:
            i += 1
            continue

        if re.match(r"^-{3,}$", stripped):
            story.append(Spacer(1, 4))
            story.append(HRFlowable(width="100%", thickness=0.7, color=colors.HexColor("#cbd5e1")))
            story.append(Spacer(1, 6))
            i += 1
            continue

        if stripped.startswith("|") and stripped.endswith("|"):
            table_lines = []
            while i < len(raw_lines):
                r_str = _strip_all_emojis(raw_lines[i]).strip()
                if not (r_str.startswith("|") and r_str.endswith("|")):
                    break
                table_lines.append(r_str)
                i += 1

            rows_data = []
            col_aligns = []
            for r_str in table_lines:
                if re.match(r"^\|[\s\-:|]+\|$", r_str):
                    sep_cells = [c.strip() for c in r_str.strip("|").split("|")]
                    col_aligns = [
                        (1 if (sc.startswith(":") and sc.endswith(":")) else (2 if sc.endswith(":") else 0))
                        for sc in sep_cells
                    ]
                    continue
                cells = [c.strip() for c in r_str.strip("|").split("|")]
                rows_data.append(cells)

            if rows_data:
                max_cols = max(len(r) for r in rows_data)
                padded_rows = [r + [""] * (max_cols - len(r)) for r in rows_data]
                while len(col_aligns) < max_cols:
                    col_aligns.append(0)

                if max_cols >= 8:
                    cur_th = ParagraphStyle("DocTH_Wide8", parent=style_th, fontSize=7.4, leading=10.5)
                    cur_td = ParagraphStyle("DocTD_Wide8", parent=style_td, fontSize=7.2, leading=10.5)
                    h_pad, v_pad = 3.5, 4.5
                elif max_cols >= 6:
                    cur_th = ParagraphStyle("DocTH_Wide6", parent=style_th, fontSize=8.0, leading=11.5)
                    cur_td = ParagraphStyle("DocTD_Wide6", parent=style_td, fontSize=7.8, leading=11.5)
                    h_pad, v_pad = 4.5, 5.0
                else:
                    cur_th, cur_td = style_th, style_td
                    h_pad, v_pad = 6.0, 6.0

                col_weights = []
                for c_idx in range(max_cols):
                    col_lens = [
                        len(re.sub(r"\*\*|`|<br\s*/?>", "", str(pr[c_idx] or "")).strip())
                        for pr in padded_rows
                    ]
                    max_l = max(col_lens) if col_lens else 4
                    avg_l = (sum(col_lens) / len(col_lens)) if col_lens else 4
                    eff_len = max(4.0, min(float(max_l) * 0.65 + float(avg_l) * 0.35, 52.0))
                    col_weights.append(eff_len ** 0.72)

                total_w = sum(col_weights) or 1.0
                min_col_w = max(24.0, usable_width * (0.055 if max_cols >= 8 else 0.075))
                raw_widths = [max(min_col_w, usable_width * (w / total_w)) for w in col_weights]
                scale_factor = usable_width / (sum(raw_widths) or usable_width)
                col_widths = [w * scale_factor for w in raw_widths]

                cur_th_c = ParagraphStyle("DocTH_C", parent=cur_th, alignment=1)
                cur_th_r = ParagraphStyle("DocTH_R", parent=cur_th, alignment=2)
                cur_td_c = ParagraphStyle("DocTD_C", parent=cur_td, alignment=1)
                cur_td_r = ParagraphStyle("DocTD_R", parent=cur_td, alignment=2)
                cur_td_tot_l = ParagraphStyle("DocTD_TotL", parent=cur_td, fontName=bold_font, alignment=0, textColor=colors.HexColor("#0f172a"))
                cur_td_tot_c = ParagraphStyle("DocTD_TotC", parent=cur_td, fontName=bold_font, alignment=1, textColor=colors.HexColor("#0f172a"))
                cur_td_tot_r = ParagraphStyle("DocTD_TotR", parent=cur_td, fontName=bold_font, alignment=2, textColor=colors.HexColor("#1e3a8a"))

                pdf_table_data = []
                summary_row_indices = []
                for r_idx, padded_r in enumerate(padded_rows):
                    row_paras = []
                    first_cell_plain = re.sub(r"\*\*|`|<[^>]+>", "", str(padded_r[0] or "")).strip()
                    is_summary_row = r_idx > 0 and any(
                        first_cell_plain.startswith(k) or k in first_cell_plain
                        for k in ("합계", "최종 실질 순절세액", "총 공제세액")
                    )
                    if is_summary_row:
                        summary_row_indices.append(r_idx)

                    for c_idx, c_text in enumerate(padded_r):
                        c_clean = c_text.replace("<br>", "\n").replace("<br/>", "\n")
                        c_plain = re.sub(r"\*\*|`", "", c_clean).strip()
                        align_code = col_aligns[c_idx] if c_idx < len(col_aligns) else 0
                        if r_idx > 0 and align_code == 0:
                            if re.match(r"^[+\-]?[\d,]+(?:\.\d+)?\s*(?:원|명|%)?(?:\s*\*\(신고서 확인 필요\)\*)?$", c_plain) or (
                                "명 /" in c_plain and c_plain.endswith("명")
                            ):
                                align_code = 2
                            elif c_plain in ("-", "1차", "2차", "3차", "순액"):
                                align_code = 1

                        if is_summary_row and "**" not in c_clean and c_clean.strip():
                            c_clean = f"**{c_clean.strip()}**"
                        cell_xml = _pdf_text(c_clean).replace("\n", "<br/>")

                        if r_idx == 0:
                            st_use = cur_th_c if align_code == 1 else (cur_th_r if align_code == 2 else cur_th)
                        elif is_summary_row:
                            st_use = cur_td_tot_c if align_code == 1 else (cur_td_tot_r if align_code == 2 else cur_td_tot_l)
                        else:
                            st_use = cur_td_c if align_code == 1 else (cur_td_r if align_code == 2 else cur_td)
                        row_paras.append(Paragraph(cell_xml, st_use))
                    pdf_table_data.append(row_paras)

                pdf_table = Table(pdf_table_data, colWidths=col_widths, repeatRows=1)
                t_style = [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING", (0, 0), (-1, -1), v_pad),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), v_pad),
                    ("LEFTPADDING", (0, 0), (-1, -1), h_pad),
                    ("RIGHTPADDING", (0, 0), (-1, -1), h_pad),
                ]
                for r_idx in range(1, len(pdf_table_data)):
                    if r_idx in summary_row_indices:
                        t_style.append(("BACKGROUND", (0, r_idx), (-1, r_idx), colors.HexColor("#eff6ff")))
                        t_style.append(("LINEABOVE", (0, r_idx), (-1, r_idx), 0.9, colors.HexColor("#93c5fd")))
                        t_style.append(("LINEBELOW", (0, r_idx), (-1, r_idx), 1.0, colors.HexColor("#3b82f6")))
                    elif r_idx % 2 == 0:
                        t_style.append(("BACKGROUND", (0, r_idx), (-1, r_idx), colors.HexColor("#f8fafc")))
                pdf_table.setStyle(TableStyle(t_style))
                story.append(Spacer(1, 4))
                story.append(pdf_table)
                story.append(Spacer(1, 8))
            continue

        if stripped.startswith("#### "):
            story.append(Paragraph(_pdf_text(stripped[5:].strip()), style_h3))
        elif stripped.startswith("### "):
            story.append(Paragraph(_pdf_text(stripped[4:].strip()), style_h3))
        elif stripped.startswith("## "):
            story.append(Paragraph(_pdf_text(stripped[3:].strip()), style_h2))
        elif stripped.startswith("# "):
            story.append(Paragraph(_pdf_text(stripped[2:].strip()), style_h2))
        elif stripped.startswith(("- ", "* ")):
            indent_level = (len(line) - len(line.lstrip(" "))) // 2
            b_style = ParagraphStyle(
                f"Bullet_{indent_level}",
                parent=style_bullet,
                leftIndent=12 + (indent_level * 10),
            )
            story.append(Paragraph("• " + _pdf_text(stripped[2:].strip()), b_style))
        else:
            story.append(Paragraph(_pdf_text(stripped), style_body))

        i += 1

    if not story:
        story.append(Paragraph("내용 없음", style_body))

    def _draw_page_footer(canvas, doc_obj):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#e2e8f0"))
        canvas.setLineWidth(0.6)
        canvas.line(40, 36, A4[0] - 40, 36)

        canvas.setFont(reg_font, 6.2)
        canvas.setFillColor(colors.HexColor("#64748b"))
        disclaimer_str = (
            "※ 본 보고서는 질의하신 사실관계와 현행 법령 기준의 참고자료이며, "
            "사실관계 변동이나 과세관청·법원의 해석에 따라 판단이 달라질 수 있습니다."
        )
        canvas.drawString(40, 24, disclaimer_str)

        canvas.setFont(reg_font, 8.2)
        canvas.setFillColor(colors.HexColor("#475569"))
        page_num_str = f"- {doc_obj.page} -"
        canvas.drawRightString(A4[0] - 40, 24, page_num_str)
        canvas.restoreState()

    doc.build(story, onFirstPage=_draw_page_footer, onLaterPages=_draw_page_footer)
    return buf.getvalue()


def _compute_report_cache_sig(s: dict, tax_yr: int) -> str:
    """
    [② 보고서 지연 생성(Lazy Generation) 해시 서명]
    사원표(year_recs/people), 사업자정보, 합산사업장, 기신고 기초값, 추가입력, 계산기준, 법령 세무진단 의견 해시를 모두 결합하여
    단 1글자·1원이라도 바뀌면 즉시 새로 생성하고, 변동이 없으면 캐시에서 0.001초 만에 반환합니다.
    """
    payload = {
        "built_sig": s.get("built_sig"),
        "tax_yr": tax_yr,
        "pm_basis": s.get("pm_basis"),
        "scheme_2026": s.get("scheme_2026"),
        "biz": s.get("biz"),
        "corp_size_default": s.get("corp_size_default"),
        "corp_size_by_year": s.get("corp_size_by_year"),
        "corp_size_user_set": s.get("corp_size_user_set"),
        "sub_biz": s.get("sub_biz_list"),
        "prev_summary": s.get("prev_summary"),
        "add_in": s.get("additional_inputs"),
        "year_recs": s.get("year_recs"),
        "audit": s.get("pro_audit_comment"),
    }
    raw_json = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw_json.encode("utf-8")).hexdigest()[:24]


def _build_report_docx_bytes(md_text: str) -> bytes:
    """마크다운 보고서를 워드(.docx) 문서로 변환합니다."""
    try:
        from docx import Document
        from docx.shared import Pt
        from docx.oxml.ns import qn
    except Exception:
        return md_text.encode("utf-8-sig")

    clean_md = re.sub(
        r"\[(\[(?:조문|부칙|별표|판례|심판례|헌재|헌재결정례|해석례|예규)\s*:\s*[^\]]+\])\]\(https?://[^\s)]+\)",
        r"\1",
        md_text or "",
    )
    clean_md = re.sub(r"\[([^\]]+)\]\(https?://[^\s)]+\)", r"\1", clean_md)

    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Malgun Gothic"
    style.font.size = Pt(10.0)
    style._element.rPr.rFonts.set(qn("w:eastAsia"), "Malgun Gothic")

    def _add_runs(p_obj, txt_str: str, bold_all: bool = False):
        for pt in re.split(r"(\*\*[^*]+?\*\*)", txt_str or ""):
            if not pt:
                continue
            if pt.startswith("**") and pt.endswith("**") and len(pt) > 4:
                r = p_obj.add_run(pt[2:-2])
                r.bold = True
            else:
                r = p_obj.add_run(pt.replace("**", ""))
                if bold_all:
                    r.bold = True
            r.font.name = "Malgun Gothic"
            r._element.rPr.rFonts.set(qn("w:eastAsia"), "Malgun Gothic")

    lines = clean_md.splitlines()
    i = 0
    while i < len(lines):
        s_ln = lines[i].strip()
        if s_ln.startswith("<div") and "원문 대조 불일치 인용 삭제:" in s_ln:
            s_ln = re.sub(r"<[^>]+>", "", s_ln).strip()
        if not s_ln or s_ln.startswith(">"):
            i += 1
            continue
        if s_ln.startswith("|") and s_ln.endswith("|"):
            t_rows = []
            while i < len(lines):
                rs = lines[i].strip()
                if not (rs.startswith("|") and rs.endswith("|")):
                    break
                if not re.match(r"^\|[\s\-:|]+\|$", rs):
                    t_rows.append([c.strip().replace("<br>", " ").replace("<br/>", " ") for c in rs.strip("|").split("|")])
                i += 1
            if t_rows:
                mc = max(len(r) for r in t_rows)
                t = doc.add_table(rows=len(t_rows), cols=mc)
                t.style = "Table Grid"
                for r_i, r_d in enumerate(t_rows):
                    for c_i, val in enumerate(r_d):
                        cell = t.cell(r_i, c_i)
                        cell.text = ""
                        _add_runs(cell.paragraphs[0], val, bold_all=(r_i == 0))
            continue
        clean_h = re.sub(r"\*\*(.*?)\*\*", r"\1", s_ln)
        if s_ln.startswith("# "):
            doc.add_heading(clean_h[2:].strip(), level=0)
        elif s_ln.startswith("## "):
            doc.add_heading(clean_h[3:].strip(), level=1)
        elif s_ln.startswith("### ") or s_ln.startswith("#### "):
            doc.add_heading(re.sub(r"^#{3,4}\s*", "", clean_h).strip(), level=2)
        elif s_ln.startswith(("- ", "* ")):
            p = doc.add_paragraph(style="List Bullet")
            _add_runs(p, s_ln[2:].strip())
        elif not re.match(r"^-{3,}$", s_ln):
            p = doc.add_paragraph()
            _add_runs(p, s_ln)
        i += 1

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _build_report_xlsx_bytes(md_text: str) -> bytes:
    """보고서 내 모든 마크다운 표를 시트별 엑셀(.xlsx) 파일로 변환합니다."""
    clean_md = re.sub(r"\[([^\]]+)\]\(https?://[^\s)]+\)", r"\1", md_text or "")
    lines = clean_md.splitlines()
    tables = []
    i = 0
    while i < len(lines):
        s_ln = lines[i].strip()
        if s_ln.startswith("|") and s_ln.endswith("|"):
            t_rows = []
            while i < len(lines):
                rs = lines[i].strip()
                if not (rs.startswith("|") and rs.endswith("|")):
                    break
                if not re.match(r"^\|[\s\-:|]+\|$", rs):
                    cells = [re.sub(r"\*\*(.*?)\*\*", r"\1", c.strip().replace("<br>", " ").replace("<br/>", " ")) for c in rs.strip("|").split("|")]
                    t_rows.append(cells)
                i += 1
            if len(t_rows) >= 2:
                tables.append(t_rows)
            continue
        i += 1

    buf = io.BytesIO()
    sheet_names = ["1_사업자기본사항", "2_최종세액요약", "3_4개년총괄표", "4_상시근로자현황"]
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        for idx, t_rows in enumerate(tables):
            mc = max(len(r) for r in t_rows)
            padded = [r + [""] * (mc - len(r)) for r in t_rows]
            hdr = [h or f"열{ci+1}" for ci, h in enumerate(padded[0])]
            df_t = pd.DataFrame(padded[1:], columns=hdr)
            sh_nm = sheet_names[idx] if idx < len(sheet_names) else f"표_{idx+1}"
            df_t.to_excel(writer, sheet_name=sh_nm[:31], index=False)
    return buf.getvalue()


def _build_client_kakao_and_email_drafts(s: dict, pkg: dict, tax_yr: int) -> tuple[str, str]:
    """
    [④ 온디맨드(버튼 클릭 시에만 생성) 거래처 전송용 카카오톡 안내문(100% 순수 텍스트·법조문 번호 제외) 및 이메일 회신 초안]
    """
    b = s.get("biz") or {}
    corp_nm = (b.get("상호") or "귀사").strip()
    cur_s = pkg["cur_s"]
    prev_s = pkg["prev_s"]
    cur_inc = pkg["cur_inc"]

    c1_won = int(pkg.get("cur_base_credit_won") or 0)
    c_cont = int(pkg.get("total_continued_credit_won") or 0)
    c_add = int(pkg.get("additional_credit_won") or 0)
    tot_gross = int(pkg.get("total_credit_gross_won") or 0)
    claw_net = int(pkg.get("total_clawback_net_payable_won") or 0)
    rural_won = int(pkg.get("rural_special_tax_won") or 0)
    net_saving = int(pkg.get("net_after_rural_tax_won") or 0)

    kakao_lines = [
        f"[{corp_nm} {tax_yr}년 귀속 통합고용세액공제 검토 요약]",
        "",
        "[한줄 결론]",
        f"- {tax_yr}년 귀속 총 공제세액은 {tot_gross:,}원이며, 농어촌특별세(20%, {rural_won:,}원)"
        + (f" 및 사후관리 추징세액({claw_net:,}원)" if claw_net > 0 else "")
        + f"을 반영한 최종 실질 순절세액은 {net_saving:,}원입니다.",
        "",
        "[핵심 인원 및 금액 내역]",
        f"- 연평균 상시근로자 수: 직전연도 {prev_s['regular']:.2f}명 -> 당해연도 {cur_s['regular']:.2f}명 (전체 +{cur_inc['total_inc']:.2f}명 증가 / 청년등 +{cur_inc['youth_inc']:.2f}명, 일반 +{cur_inc['non_youth_inc']:.2f}명)",
        f"- 당해 신규 고용증가 공제액(1차): {c1_won:,}원",
        f"- 과거연도 고용유지 연속공제액(2·3차): {c_cont:,}원" + (f" / 추가공제: {c_add:,}원" if c_add > 0 else ""),
        f"- 농어촌특별세(감면세액의 20%): -{rural_won:,}원",
        "",
        "[꼭 챙기실 사항]",
        "- 만 35~40세 입사 직원 중 군 복무 이력이 있는 분의 병적증명서(또는 주민등록초본 병역사항)를 전달해 주시면 청년 우대공제 단가를 적용해 절세액을 더 늘릴 수 있습니다.",
        "- 외국인 근로자의 국내 거주 확인서류(외국인등록증)와 중도퇴사자의 근로계약서를 신고 전 최종 확인 부탁드립니다.",
    ]

    email_lines = [
        f"제목: [{corp_nm}] {tax_yr}년 귀속 통합고용세액공제 및 사후관리 검토보고서 송부의 건",
        "",
        f"{corp_nm} 대표님 및 재무·인사 담당자님께,",
        f"안녕하십니까. {tax_yr}년 귀속 통합고용세액공제 및 과거 과세연도 사후관리 정밀 검토 결과를 아래와 같이 안내해 드립니다.",
        "",
        f"1. {tax_yr}년 귀속 최종 세액공제 및 순절세액 요약",
        f"  - 당해 1차년도 신규 고용증가 세액공제: {c1_won:,}원 (상시근로자 {prev_s['regular']:.2f}명 -> {cur_s['regular']:.2f}명, +{cur_inc['total_inc']:.2f}명 증가)",
        f"  - 직전·전전연도 기공제분 연속공제(2·3차년도): {c_cont:,}원",
        f"  - 당해 총 공제세액 합계: {tot_gross:,}원",
        f"  - 사후관리 추가납부세액: {claw_net:,}원 / 농어촌특별세(20%): {rural_won:,}원",
        f"  - 차감 후 최종 실질 순절세액: {net_saving:,}원",
        "    (※ 당기 법인세/소득세 산출세액 및 최저한세 한도를 초과하여 당기 공제받지 못하는 금액은 향후 10년간 이월공제되며, 이월분에는 당기 농어촌특별세가 부과되지 않습니다.)",
        "",
        "2. 신고 전 최종 확인 및 요청 서류",
        "  (1) 병역이행기간 차감 대상자(입사 당시 만 35~40세 남성 근로자)의 병적증명서 또는 주민등록초본(병역사항 포함)",
        "  (2) 외국인 근로자의 외국인등록증 사본(국내 거소 기간 183일 이상 거주자 요건 확인용)",
        "  (3) 중도퇴사자의 근로계약서 사본(근로계약기간 1년 이상 여부 확인용)",
        "",
        "상세한 사원별·연도별 산출 근거와 법령 주석은 첨부해 드리는 검토보고서(PDF)를 참고해 주시기 바라며, 문의사항이 있으시면 언제든 연락 주십시오.",
        "감사합니다.",
    ]
    return "\n".join(kakao_lines), "\n".join(email_lines)


def _page_report(room_key: str = "", log_tokens_fn=None):
    s = _S()
    _ensure_built_for_tax_year(s)
    tax_yr = int(s["tax_year"])

    with st.spinner("법제처 API 실시간 조문·직링크 연동 및 심층 세무진단 보고서를 구성하고 있습니다..."):
        audit_clean_body, model_used, live_trace = _ensure_auto_pro_audit_comment(
            s, log_tokens_fn=log_tokens_fn, room_key=room_key, return_trace=True
        )

    corp_nm = (s.get("biz", {}).get("상호") or "통합고용세액공제").strip()
    corp_fn = re.sub(r'[\\/:*?"<>|\s]+', "_", corp_nm)[:30]

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

    # ② 보고서 지연 생성(Lazy Generation) — 사원표·법령·기신고·추가입력 해시 서명 대조
    cur_rep_sig = _compute_report_cache_sig(s, tax_yr)
    rep_cache = s.get("_report_artifact_cache") or {}
    if rep_cache.get("sig") == cur_rep_sig and rep_cache.get("md") and rep_cache.get("pdf"):
        md_text = rep_cache["md"]
        pdf_report_bytes = rep_cache["pdf"]
        docx_report_bytes = rep_cache.get("docx") or _build_report_docx_bytes(md_text)
        xlsx_report_bytes = rep_cache.get("xlsx") or _build_report_xlsx_bytes(md_text)
    else:
        md_text = _build_report_markdown(
            s, log_tokens_fn=log_tokens_fn, room_key=room_key, trace=live_trace, audit_body=audit_clean_body
        )
        pdf_report_bytes = _build_report_pdf_bytes(s, log_tokens_fn=log_tokens_fn, room_key=room_key, md_text=md_text)
        docx_report_bytes = _build_report_docx_bytes(md_text)
        xlsx_report_bytes = _build_report_xlsx_bytes(md_text)
        s["_report_artifact_cache"] = {
            "sig": cur_rep_sig,
            "md": md_text,
            "pdf": pdf_report_bytes,
            "docx": docx_report_bytes,
            "xlsx": xlsx_report_bytes,
        }

    # ⑨ 상단 3대 KPI 요약 카드 표시 (당해 확정 공제세액 · 추징/농특세 · 실질 순절세액)
    pkg_now = s.get("calc_pkg")
    if isinstance(pkg_now, dict):
        try:
            from .ui_step3 import _build_top_kpi_cards_html, _dlg_filed_vs_recalc_comparison
            st.markdown(_build_top_kpi_cards_html(pkg_now, tax_yr), unsafe_allow_html=True)
        except Exception:
            pass

    st.markdown(f"<div class='ec-agent-report-wrap'>\n\n{md_text}\n\n</div>", unsafe_allow_html=True)

    disp_model = model_used or str(s.get("pro_audit_model") or "gemini-2.5-pro")
    with st.expander("✏️ Ⅳ. 심층 세무진단 의견 문구 직접 수정 · AI 재생성", expanded=False):
        st.caption("아래에서 보고서 『Ⅳ. 심층 세무진단 의견』 문구를 직접 수정하고 [수정 내용 반영]을 누르면 화면 보고서와 PDF·워드 출력물에 즉시 반영됩니다.")
        edited_audit = st.text_area(
            "Ⅳ. 심층 세무진단 의견 본문",
            value=audit_clean_body,
            height=240,
            label_visibility="collapsed",
            key=f"ec_edit_audit_area_{tax_yr}",
        )
        ce1, ce2, _ = st.columns([1.4, 1.4, 4.2])
        if ce1.button("💾 수정 내용 반영", type="primary", use_container_width=True, key="btn_save_edited_audit"):
            _, _ed_trace = P._fetch_live_employment_law_context() if hasattr(P, "_fetch_live_employment_law_context") else ("", None)
            _ed_verified, _ed_qdel = (
                P.verify_and_redact_unmatched_quotes(_sanitize_markdown_tilde(edited_audit), _ed_trace)
                if hasattr(P, "verify_and_redact_unmatched_quotes")
                else (_sanitize_markdown_tilde(edited_audit), 0)
            )
            s["pro_audit_quote_deleted_cnt"] = _ed_qdel
            s["pro_audit_comment"] = f"[적용 모델: {disp_model} | 인용삭제: {_ed_qdel}건]\n\n{_ed_verified}"
            s.pop("_report_artifact_cache", None)
            _save_ec_to_disk(s)
            st.rerun()
        if ce2.button("🔄 AI 의견 다시 생성 (법제처 API 재조회)", use_container_width=True, key="btn_regen_audit"):
            s["pro_audit_comment"] = ""
            s["pro_audit_sig"] = ""
            s.pop("_report_artifact_cache", None)
            _save_ec_to_disk(s)
            st.rerun()

    with st.expander("💬 거래처 전송용 카카오톡 안내문 · 이메일 회신 초안 (버튼을 누를 때만 생성)", expanded=False):
        st.caption("평소에는 생성하지 않아 속도와 토큰을 아끼며, 아래 버튼을 누를 때만 즉시 생성합니다.")
        ck1, ck2, _ = st.columns([1.8, 1.8, 3.4])
        if ck1.button("💬 카카오톡 안내문 생성 (순수 텍스트)", use_container_width=True, key=f"btn_gen_kakao_{tax_yr}"):
            if isinstance(pkg_now, dict):
                k_txt, _ = _build_client_kakao_and_email_drafts(s, pkg_now, tax_yr)
                s["_client_kakao_draft"] = k_txt
        if ck2.button("📧 비즈니스 이메일 초안 생성", use_container_width=True, key=f"btn_gen_email_{tax_yr}"):
            if isinstance(pkg_now, dict):
                _, e_txt = _build_client_kakao_and_email_drafts(s, pkg_now, tax_yr)
                s["_client_email_draft"] = e_txt
        if s.get("_client_kakao_draft"):
            st.markdown("**📱 카카오톡·문자 전송용 안내문 (우측 상단 복사 아이콘 클릭)**")
            st.code(s["_client_kakao_draft"], language="text")
        if s.get("_client_email_draft"):
            st.markdown("**📧 거래처 발송용 이메일 회신 초안 (우측 상단 복사 아이콘 클릭)**")
            st.code(s["_client_email_draft"], language="text")

    st.markdown(
        f"<div class='ec-model-footer-bar'>"
        f"<span>심층 세무진단 분석 완료 (법제처 Open API 조문·직링크 연동 · 캐시 서명 <code>{cur_rep_sig[:8]}</code>)</span>"
        f"<span>적용 모델: <code>{disp_model}</code> (스크린 전용 표시 · PDF 출력 제외)</span>"
        f"</div>",
        unsafe_allow_html=True,
    )

    st.markdown("<div class='ec-nav-divider'></div>", unsafe_allow_html=True)
    c_cmp_bot, _ = st.columns([2.6, 4.8])
    if c_cmp_bot.button("⚖️ 기신고 vs 세법상 재계산 비교 (경정청구 · 수정신고 진단)", use_container_width=True, key=f"btn_step4_filed_vs_recalc_{tax_yr}"):
        from .ui_step3 import _dlg_filed_vs_recalc_comparison
        _dlg_filed_vs_recalc_comparison(s, pkg_now if isinstance(pkg_now, dict) else None, tax_yr)
    c_prev, c_pdf_bot, c_docx_bot, c_xlsx_bot, c_md_bot, c_reset = st.columns([1.15, 1.35, 1.25, 1.25, 1.25, 1.15])
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
    with c_docx_bot:
        st.download_button(
            "📘 워드 (.docx)",
            data=docx_report_bytes,
            file_name=f"{corp_fn}_{tax_yr}년귀속_통합고용세액공제_검토보고서.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            use_container_width=True,
            key="dl_docx_report_bot",
        )
    with c_xlsx_bot:
        st.download_button(
            "📊 표 엑셀 (.xlsx)",
            data=xlsx_report_bytes,
            file_name=f"{corp_fn}_{tax_yr}년귀속_통합고용세액공제_요약표.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key="dl_xlsx_report_bot",
        )
    with c_md_bot:
        st.download_button(
            "📝 마크다운 (.md)",
            data=md_text.encode("utf-8-sig"),
            file_name=f"{corp_fn}_{tax_yr}년귀속_통합고용세액공제_검토보고서.md",
            mime="text/markdown",
            use_container_width=True,
            key="dl_md_report_bot",
        )
    if c_reset.button("처음으로(1단계)", use_container_width=True):
        s["step"] = 1
        _trigger_scroll_to_top(s)
        _save_ec_to_disk(s)
        st.rerun()