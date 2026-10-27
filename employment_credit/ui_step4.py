# -*- coding: utf-8 -*-
"""통합고용세액공제 계산기 화면 — 4단계 보고서: 보고서·PDF·CSV 내려받기

(ui.py에서 나눈 파일. 현행 조특법 제29조의8·시행령 제26조의8 조문 정합성, 방식 2 보수적 비교인원 산정 근거,
사원별 차이원인 정밀 분해[박소연·김우주 등 오판 원천 차단], 최저한세 검토, 법제처 API 직링크 자동 결합 반영)
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
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
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
    if kind in ("조문", "부칙", "별표"):
        m_law = re.match(r"^(조세특례제한법\s*시행령|조세특례제한법\s*시행규칙|조세특례제한법|소득세법\s*시행령|소득세법|법인세법\s*시행령|법인세법|농어촌특별세법|근로기준법)\s*(.*)$", body)
        if m_law:
            law_nm, rest = m_law.group(1).strip(), m_law.group(2).strip()
            return f"「{law_nm}」 {rest}" if rest else f"「{law_nm}」"
        return body
    return f"[{kind}: {body}]"


def _pdf_text(t: str) -> str:
    """PDF 문단용: 폰트 미지원 전각 로마숫자(Ⅰ~Ⅳ)·유니코드 물결표(∼)·마이너스(−) 치환 및 마크다운 변환"""
    _, bold_font = _ensure_korean_pdf_font()
    s = str(t or "")
    s = s.translate(_ROMAN_MAP)
    s = s.replace("∼", "~").replace("〜", "~").replace("～", "~")
    s = s.replace("−", "-").replace("–", "-").replace("—", "-")
    s = re.sub(r"\[(조문|부칙|별표|판례|심판례|헌재|헌재결정례|해석례|예규)\s*:\s*([^\]]+)\]", _format_citation_tag_for_pdf, s)
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    s = re.sub(r"\*\*(.+?)\*\*", rf"<font name='{bold_font}'><b>\1</b></font>", s)
    s = re.sub(r"`([^`]+)`", rf"<font name='{bold_font}'><b>\1</b></font>", s)
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
       2024·2025년 귀속분 사후관리(b2·b3, 대통령령 제35999호 부칙 제2조 종전규정)에는 산입되어 사후관리 인원과 당해 공제 인원 간 차이를 발생시킨 사원 (예: 박소연 +0.50명 등).
    2) `직전연도말_재직_당해중도퇴사_보수적산입_사원`: 직전연도(tax_yr - 1) 중 입사해 직전연도 말 현재 재직 중이었다가
       당해(tax_yr) 중 퇴사하여 총 근로기간이 1년 미만이 된 사원 (예: 박소연, 차백준) — 방식 2(과세연도 종료일 기준 보수적 산정)에 따라
       직전연도 비교 인원에는 포함하고 당해 인원에서만 제외한 대상.
    3) `실제_연령도과_청년간주_사원`: 당해 상시근로자('O')이면서 순수하게 연령 도과(만 34세 및 유예기간 도과)로 인해
       당해에는 일반('청년외')이지만 코호트 사후관리(b2·b3)에서만 청년등으로 간주된 사원.
    4) `단시간_정규직_고용형태전환_사원`: 과거 과세연도에는 단시간근로자(0.5명, 청년 제외)였다가 이후 통상근로자(정규직 1.0명)로 전환되어
       청년등 상시근로자로 분류된 사원 (예: 김우주 등 — 연령경과 간주 예시로 오용 금지).
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

        # (B) 직전연도(tax_yr - 1) 입사 + 직전연도 말 현재 재직 + 당해(tax_yr) 중 퇴사로 총 근로기간 1년 미만인 사원
        if (
            hire_dt
            and ret_dt
            and hire_dt.year == (tax_yr - 1)
            and ret_dt.year == tax_yr
            and H.tenure_under_1y(p, tax_yr)
            and not H.tenure_under_1y(p, tax_yr - 1)
        ):
            prev_r = float(c_prev.get("b1_reg") or 0.0)
            if prev_r > 0 or H.worked_in_year(p, tax_yr - 1):
                conservative_prev_kept.append(
                    f"{nm}(입사 {hire_dt.isoformat()} ~ 퇴사 {ret_dt.isoformat()}, {tax_yr-1}년 비교인원 {prev_r:.2f}명 산입 · {tax_yr}년 당해 제외)"
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

    return {
        "구법포함_신법1년미만제외_사원": under1y_pm_diff,
        "직전연도말_재직_당해중도퇴사_보수적산입_사원": conservative_prev_kept,
        "실제_연령도과_청년간주_사원": age_deemed_youth,
        "단시간_정규직_고용형태전환_사원": emp_type_converted,
    }


def _build_prior_filing_discrepancy_bullets(
    s: dict,
    totals_all: dict | None = None,
    pkg: dict | None = None,
    diff_diag: dict | None = None,
) -> list[str]:
    """
    이전 과세연도 기신고 자료(prev_summary / ext.prev_filing)와 2·3단계 세법원칙 재계산 수치 간 차이,
    그리고 2026년 공제용 직전연도(2025년) 비교 인원 산정 기준(방식 2: 과세연도 종료일 기준 보수적 산정)의 법적 근거를 명확히 생성합니다.
    """
    tax_yr = int(s.get("tax_year") or R.DEFAULT_TAX_YEAR)
    if totals_all is None:
        totals_all = _ensure_totals_snapshot(s)

    ps = s.get("prev_summary") or {}
    ext_pf = ((s.get("ext") or {}).get("prev_filing") or {}).get("연도별") or {}

    if pkg is None:
        b = s.get("biz") or {}
        corp_sz = b.get("기업구분", "중소기업")
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
            )
        except Exception:
            pkg = s.get("calc_pkg") or {}

    if diff_diag is None:
        diff_diag = _analyze_headcount_diff_reasons(s, tax_yr, totals_all=totals_all, pkg=pkg)

    bullets: list[str] = []
    has_higher_recalc = False
    has_lower_recalc = False

    # 1) 과세연도별 기신고 인원 vs 2단계 사원표(세법원칙) 재계산 인원 비교
    for y in (tax_yr - 1, tax_yr - 2, tax_yr - 3):
        t_y = totals_all.get(y) or {}
        if not t_y.get("has_data") or t_y.get("from_filed"):
            continue

        f_merged = {}
        if isinstance(ext_pf.get(str(y)), dict):
            f_merged.update(ext_pf[str(y)])
        if isinstance(ps.get(str(y)), dict):
            for k, v in ps[str(y)].items():
                if v is not None:
                    f_merged[k] = v

        f_reg_raw = f_merged.get("상시")
        f_yth_raw = f_merged.get("청년등")
        if f_reg_raw is None and f_yth_raw is None:
            continue

        recalc_reg = float(t_y.get("old_rule_regular") if t_y.get("old_rule_regular") is not None else t_y.get("상시_평균", t_y.get("b1_reg", 0.0)) or 0.0)
        recalc_yth = float(t_y.get("old_rule_youth") if t_y.get("old_rule_youth") is not None else t_y.get("청년등_평균", t_y.get("b1_yth", 0.0)) or 0.0)
        indiv_reg = float(t_y.get("b4_reg", recalc_reg) or 0.0)
        indiv_yth = float(t_y.get("b4_yth", recalc_yth) or 0.0)

        f_reg = float(f_reg_raw) if f_reg_raw is not None else recalc_reg
        f_yth = float(f_yth_raw) if f_yth_raw is not None else recalc_yth
        diff_reg = round(recalc_reg - f_reg, 2)
        diff_yth = round(recalc_yth - f_yth, 2)

        if abs(diff_reg) < 0.01 and abs(diff_yth) < 0.01:
            continue

        if diff_reg > 0 or diff_yth > 0:
            has_higher_recalc = True
        if diff_reg < 0 or diff_yth < 0:
            has_lower_recalc = True

        diff_parts = []
        if f_reg_raw is not None and abs(diff_reg) >= 0.01:
            diff_parts.append(f"전체 상시근로자 기신고 **{f_reg:.2f}명** → 세법원칙 재계산 **{recalc_reg:.2f}명**(차이 **{diff_reg:+.2f}명**)")
        if f_yth_raw is not None and abs(diff_yth) >= 0.01:
            diff_parts.append(f"청년등 상시근로자 기신고 **{f_yth:.2f}명** → 세법원칙 재계산 **{recalc_yth:.2f}명**(차이 **{diff_yth:+.2f}명**)")
        diff_summary = ", ".join(diff_parts)

        is_trunc_diff = (
            (abs(f_reg - indiv_reg) <= 0.02 and abs(diff_reg) >= 0.01)
            or (abs(f_yth - indiv_yth) <= 0.02 and abs(diff_yth) >= 0.01)
            or (abs(diff_reg) <= 0.12 and abs(diff_yth) <= 0.12)
        )
        if is_trunc_diff:
            reason_str = (
                "과거 신고 시에는 근로자 개개인별로 근무월수를 과세연도 개월 수(12개월)로 나눈 값을 먼저 소수점 둘째 자리에서 버림한 뒤 합산(인별 절사 방식)하여 "
                "중도 입·퇴사자의 소수점 셋째 자리 이하 자투리가 절사된 반면, 현행 시행령 산식([조문:조세특례제한법 시행령 제26조의8 제6항] 및 [조문:조세특례제한법 시행령 제11조의2 제8항] 준용)은 "
                "**해당 과세연도 매월 말 현재 상시근로자 수의 합(연인원)을 과세연도 개월 수로 나눈 뒤 100분의 1 미만 부분을 1회 버림(합산 후 절사)**하도록 규정하고 있기 때문입니다."
            )
        else:
            reason_str = (
                "원천징수부 기반 인별 세법 요건 재검토 결과, ① 중도 입·퇴사자의 매월 말일 재직 판정([조문:조세특례제한법 시행령 제26조의8 제2항]), "
                "② 근로계약 체결일 현재 만 15∼34세 청년 연령 및 병역이행기간(최대 6년) 차감 판정([조문:조세특례제한법 시행령 제26조의8 제4항]), "
                "③ 등기임원·최대주주·친족·1년 미만 근로자 등 상시근로자 제외대상 분류([조문:조세특례제한법 시행령 제23조 제10항] 준용) 및 합산 후 1회 절사([조문:조세특례제한법 시행령 제26조의8 제6항]) 원칙을 적용함에 따라 발생한 차이입니다."
            )

        bullets.append(f"**{y}년 귀속 기신고 인원 대비 세법원칙 재계산 차이**: {diff_summary}. {reason_str}")

    # 2) 직전 과세연도(tax_yr - 1)의 『종전 규정 인원(2단계 표·사후관리용)』 vs 『개정 규정 인원(3단계 당해 신규공제 비교용 — 방식 2 보수적 산정)』 차이 및 근거
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
                f" 특히 **{', '.join(cons_list)}**의 경우 {tax_yr}년 중 퇴사하여 총 근로기간이 1년 미만이 되었으므로 {tax_yr}년 당해 인원에서는 제외하였으나, "
                f"**{tax_yr-1}년 과세연도 종료일({tax_yr-1}.12.31.) 현재에는 퇴사하지 않고 정상 재직 중(근로계약기간 1년 이상)**이었으므로 "
                f"과세연도 종료일 현황 판정 원칙에 따라 **{tax_yr-1}년 비교 인원({new_r:.2f}명)에는 보수적으로 산입**하여 과다공제 및 가산세 리스크를 원천 차단하였습니다 "
                f"(참고: 사후 확정된 총 근로기간을 {tax_yr-1}년 비교 인원에도 소급 적용해 제외할 경우 {tax_yr}년 1차 공제액이 증가하나, 세무상 안정성을 위해 연도말 재직 기준을 채택함)."
            )
        bullets.append(
            f"**{tax_yr}년 신규공제 산정용 직전연도({tax_yr-1}년) 비교 인원 재산정 및 보수적 산정 기준 (종전규정 {old_r:.2f}명 → 개정규정 비교값 {new_r:.2f}명, {r_diff:+.2f}명)**: "
            f"{tax_yr-1}년 귀속 자체의 공제 및 그 사후관리에는 종전 규정(**근로계약기간 1년 미만자만 제외**, 대통령령 제35999호 부칙 제2조 경과조치)이 적용되어 "
            f"2단계 {tax_yr-1}년 표에서는 **{old_r:.2f}명**으로 산정되며, **{tax_yr}년 귀속 1차년도 신규 고용증가 인원을 계산할 때 비교하는 직전 과세연도({tax_yr-1}년) 인원**은 "
            f"개정 규정(**실제 근로기간 1년 미만자 제외**, [조문:조세특례제한법 시행령 제26조의8 제2항] 제1호)으로 재산정하여 {tax_yr-1}년 내 1년 미만 퇴사자를 제외한 **{new_r:.2f}명**을 적용하였습니다.{cons_note}"
        )

    # 3) 경정청구 실익 및 비연동(상충관계 없음) 안내
    pm1_f = (pkg or {}).get("pm_y1_filed") or {}
    pm1_r = (pkg or {}).get("pm_y1_recalc") or {}
    pm2_f = (pkg or {}).get("pm_y2_filed") or {}
    pm2_r = (pkg or {}).get("pm_y2_recalc") or {}

    net_f = (
        int(pm1_f.get("continued_credit_won") or 0)
        - int(pm1_f.get("clawback_net_payable_won") or 0)
        + int(pm2_f.get("continued_credit_won") or 0)
        - int(pm2_f.get("clawback_net_payable_won") or 0)
    )
    net_r = (
        int(pm1_r.get("continued_credit_won") or 0)
        - int(pm1_r.get("clawback_net_payable_won") or 0)
        + int(pm2_r.get("continued_credit_won") or 0)
        - int(pm2_r.get("clawback_net_payable_won") or 0)
    )

    if bullets or abs(net_r - net_f) >= 10:
        tax_diff_note = ""
        if abs(net_r - net_f) >= 10 and not pm1_f.get("base_missing") and not pm1_r.get("base_missing"):
            diff_won = net_r - net_f
            fav_lbl = "세법원칙 재계산 기준" if diff_won > 0 else "기신고 서식 기준"
            tax_diff_note = (
                f" 당해 사후관리 순세액(연속공제 − 추가납부) 비교 시 기신고 기준(**{net_f:,}원**) 대비 "
                f"세법원칙 재계산 기준(**{net_r:,}원**)이 **{diff_won:+,}원** 차이나며(**{fav_lbl}** 유리),"
            )
        if has_higher_recalc:
            bullets.append(
                f"**경정청구 실익 및 당해 비교인원 비연동(상충관계 없음) 안내**:{tax_diff_note} "
                f"{tax_yr}년 신규 공제 계산에 사용한 직전연도({tax_yr-1}년) 비교 인원(**{prev_s.get('regular', 0):.2f}명**)은 이미 개정 규정으로 별도 재계산한 값이므로 "
                f"**{tax_yr-1}년 귀속분 경정청구 여부와 무관합니다(경정청구 시 {tax_yr}년 공제액이 줄어드는 상충관계 없음)**. "
                f"따라서 과거 과세연도 기신고(인별 절사) 대비 재계산(합산 후 절사, [조문:조세특례제한법 시행령 제26조의8 제6항]) 차이에 대해서는 "
                f"법정신고기한 경과 후 5년 이내에 **[조문:국세기본법 제45조의2](경정청구)**에 따른 순수 환급 실익만 판단하여 진행하시기 바랍니다."
            )
        elif has_lower_recalc or tax_diff_note:
            bullets.append(
                f"**사후관리 소명 및 수정신고·경정청구 검토 가이드**:{tax_diff_note} "
                f"기신고 서식 수치와 원천징수부 세법원칙 재계산 수치 간 차이에 대해 3단계 상단의 계산 기준 선택 스위치로 세액 영향을 비교하고, "
                f"필요시 **[조문:국세기본법 제45조](수정신고)** 또는 **[조문:국세기본법 제45조의2](경정청구)** 규정에 따라 기초 인원 정합성을 맞추어 신고하시기 바랍니다."
            )

    return bullets


def _ensure_auto_pro_audit_comment(s: dict, log_tokens_fn=None, room_key: str = "") -> tuple[str, str]:
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

    # 버전 시그니처에 v2_law_api를 포함하여 이전의 잘못된 조문/오판 캐시를 자동 갱신
    cur_sig = f"v2_law_api|{s.get('built_sig')}|{tax_yr}|{s.get('pm_basis')}"

    def _attach_sec4_and_links(clean_body: str) -> str:
        out_b = clean_body
        if discrepancy_bullets and "### (4)" not in out_b and "#### (4)" not in out_b:
            sec4_md = (
                "\n\n### (4) 이전 과세연도 기신고 내역과 세법원칙 재계산 차이 및 법령 근거\n"
                + "\n".join(f"- {_sanitize_markdown_tilde(b)}" for b in discrepancy_bullets)
            )
            out_b = (out_b.rstrip() + sec4_md).strip()
        if hasattr(P, "inject_verified_law_links"):
            out_b = P.inject_verified_law_links(out_b)
        return out_b

    existing_raw = str(s.get("pro_audit_comment") or "").strip()
    if existing_raw and not existing_raw.startswith("❌") and s.get("pro_audit_sig") == cur_sig:
        body, mod_nm = _parse_and_clean_pro_audit(existing_raw)
        if body:
            if not mod_nm:
                mod_nm = str(s.get("pro_audit_model") or "gemini-2.5-pro")
            s["pro_audit_model"] = mod_nm
            return _attach_sec4_and_links(body), mod_nm

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

    raw_generated = P.call_pro_argon_audit_commentary(
        audit_payload, log_tokens_fn=log_tokens_fn, room_key=room_key
    )
    body, mod_nm = _parse_and_clean_pro_audit(raw_generated)
    if not mod_nm:
        mod_nm = "gemini-2.5-pro"
    body = _attach_sec4_and_links(body)
    s["pro_audit_comment"] = f"[적용 모델: {mod_nm}]\n\n{body}"
    s["pro_audit_model"] = mod_nm
    s["pro_audit_sig"] = cur_sig
    _save_ec_to_disk(s)
    return body, mod_nm


def _build_report_markdown(s: dict, log_tokens_fn=None, room_key: str = "") -> str:
    """
    [4단계 보고서 마크다운 생성 — 현행 법령 정합성 100% · 사원별 차이원인 자동 분해 · 방식 2 보수적 비교인원 근거 · 법제처 직링크 결합]
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

    diff_diag = _analyze_headcount_diff_reasons(s, tax_yr, totals_all=totals_all, pkg=pkg)
    under1y_pm_names = diff_diag.get("구법포함_신법1년미만제외_사원") or []
    age_deemed_names = diff_diag.get("실제_연령도과_청년간주_사원") or []
    cons_prev_names = diff_diag.get("직전연도말_재직_당해중도퇴사_보수적산입_사원") or []

    # 1·2차 사후관리 행의 비고란을 실제 원인(구법·신법 1년 미만 퇴사자 처리 차이 vs 실제 연령경과 간주)에 맞게 동적 생성
    if under1y_pm_names and age_deemed_names:
        pm_row_note = f"종전규정(대통령령 제35999호 부칙 제2조: {', '.join(under1y_pm_names)}) 및 연령경과 간주({', '.join(age_deemed_names)}) [각주 2, 3]"
    elif under1y_pm_names:
        pm_row_note = f"{tax_yr-1}·{tax_yr-2}년분 사후관리 종전규정 적용 (대통령령 제35999호 부칙 제2조: {', '.join(under1y_pm_names)}) [각주 2, 3]"
    elif age_deemed_names:
        pm_row_note = f"입사 당시 청년 연령경과 간주 특례 ({', '.join(age_deemed_names)}) [각주 3]"
    else:
        pm_row_note = "대통령령 제35999호 부칙 제2조(종전규정) 및 구 조특령 제26조의8 제5항 적용 [각주 2, 3]"

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
        scheme_desc = f"현행 [조문:조세특례제한법 제29조의8 제1항] 점증형(A+B+C) 구조 ({tax_yr}년은 비교연도가 {tax_yr-1}년[A]뿐이므로 1년차 단가 적용 · 신법분 추징 없음) [각주 1]"
    else:
        r_leg = pkg["rates_legacy"]
        yu, gu = r_leg["청년등"] * 10_000, r_leg["청년등외"] * 10_000
        scheme_desc = "[조문:조세특례제한법 제29조의8 제1항] 기본공제 단가 [각주 1]"

    pm1_reg_dec = "여(감소)" if (pm1.get("active") and not pm1.get("base_missing") and cur_s["b2_reg"] < pm1.get("init_reg", 0)) else "부(유지·증가)"
    pm1_yth_dec = "여(감소)" if (pm1.get("active") and not pm1.get("base_missing") and cur_s["b2_yth"] < pm1.get("init_yth", 0)) else "부(유지·증가)"
    pm2_reg_dec = "여(감소)" if (pm2.get("active") and not pm2.get("base_missing") and cur_s["b3_reg"] < pm2.get("init_reg", 0)) else "부(유지·증가)"
    pm2_yth_dec = "여(감소)" if (pm2.get("active") and not pm2.get("base_missing") and cur_s["b3_yth"] < pm2.get("init_yth", 0)) else "부(유지·증가)"

    audit_body, _ = _ensure_auto_pro_audit_comment(s, log_tokens_fn=log_tokens_fn, room_key=room_key)

    # 직전연도 비교인원 보수적 산정(방식 2) 안내 불릿
    prev_basis_bullets = [
        f"- **산정 방법**: 매월 말 현재 상시근로자 수의 연간 합계(연인원)를 해당 과세연도 개월 수({cur_s['months_in_year']}개월)로 나눈 뒤 소수점 셋째 자리에서 버림(100분의 1 미만 절사, [조문:조세특례제한법 시행령 제26조의8 제6항] 및 [조문:조세특례제한법 시행령 제11조의2 제8항] 준용)하여 산정하였습니다.",
        f"- **청년등 증가인원 한도(Cap)**: 청년등 상시근로자 증가인원(+{cur_inc['youth_inc']:.2f}명)은 전체 상시근로자 증가인원(+{cur_inc['total_inc']:.2f}명)을 한도로 적용하였습니다([조문:조세특례제한법 시행령 제26조의8 제4항]).",
    ]
    if prev_s.get("old_rule_regular") is not None or cons_prev_names:
        old_rv = float(prev_s.get("old_rule_regular") if prev_s.get("old_rule_regular") is not None else prev_s["regular"])
        cons_detail = (
            f" 이때 **{', '.join(cons_prev_names)}**과 같이 {tax_yr-1}년 중 입사하여 **{tax_yr-1}년 과세연도 종료일({tax_yr-1}.12.31.) 현재 퇴사하지 않고 계속 근로 중이었던 인원**은 "
            f"{tax_yr-1}년 종료일 시점 기준으로는 1년 미만 퇴사 사유가 확정되지 않았으므로 보수적으로 {tax_yr-1}년 비교 인원(**{prev_s['regular']:.2f}명**)에 그대로 포함하고, "
            f"실제 중도퇴사 사유가 발생한 {tax_yr}년 당해 인원에서만 제외하였습니다."
            if cons_prev_names else ""
        )
        prev_basis_bullets.append(
            f"- **{tax_yr}년 공제용 직전연도({tax_yr-1}년) 비교 인원 보수적 산정 기준 ({prev_s['regular']:.2f}명)**: "
            f"{tax_yr-1}년 귀속 자체 및 사후관리용 인원(**{old_rv:.2f}명**)은 대통령령 제35999호 부칙 제2조 경과조치에 따라 종전 규정(근로계약기간 1년 미만 제외)을 적용하고, "
            f"{tax_yr}년 신규 공제 산정을 위한 직전연도({tax_yr-1}년) 비교 인원(**{prev_s['regular']:.2f}명**)은 개정 규정([조문:조세특례제한법 시행령 제26조의8 제2항] 제1호: 실제 근로기간 1년 미만 제외)으로 재산정하였습니다.{cons_detail}"
        )
    if abs(cur_s["b2_yth"] - cur_s["youth"]) >= 0.01 or under1y_pm_names:
        prev_basis_bullets.append(
            f"- **사후관리 인원({cur_s['b2_yth']:.2f}명)과 당해 공제 인원({cur_s['youth']:.2f}명) 차이 원인**: "
            + (
                f"두 수치의 차이(**{cur_s['b2_yth'] - cur_s['youth']:+.2f}명**)는 연령경과 간주 때문이 아니라, "
                f"**{', '.join(under1y_pm_names)}** 사원이 {tax_yr-1}·{tax_yr-2}년분 사후관리에는 대통령령 제35999호 부칙 제2조 경과조치(종전 규정: 근로계약기간 1년 이상 포함)에 따라 산입되고, "
                f"{tax_yr}년 당해 공제에서는 개정 규정(실제 근로기간 1년 미만 제외)에 따라 제외된 결과입니다."
                if under1y_pm_names else
                f"최초 공제연도 기준 청년등 사후관리 특례(구 조특령 제26조의8 제5항, 부칙 경과조치) 적용 결과입니다."
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
        f"| **2. 직전·전전연도({tax_yr-1}·{tax_yr-2}년) 기공제분 연속공제액** | **{pkg['total_continued_credit_won']:,}원** | 2차년도 {pm1['continued_credit_won']:,}원 + 3차년도 {pm2['continued_credit_won']:,}원 (구 조특법 제29조의8 제3항 · 개정법 부칙 경과조치 [각주 3]) |",
        f"| **3. 육아휴직 복귀 및 정규직 전환 추가공제액** | **{pkg['additional_credit_won']:,}원** | 복귀 {pkg['parental_ret_cnt']}명(제5항) / 전환 {pkg['reg_conv_cnt']}명(제4항, ~2024년 전환분 한정) ([조문:조세특례제한법 제29조의8 제4항]·[조문:조세특례제한법 제29조의8 제5항]) |",
        f"| **합계: 당해 총 공제세액 (1+2+3)** | **{pkg['total_credit_gross_won']:,}원** | **공제감면세액계산서 및 세액공제신청서 반영 금액** |",
        f"| **4. 사후관리 추가납부세액 (이월공제 차감 후)** | **{pkg['total_clawback_net_payable_won']:,}원** | 차감전 추징액 {pkg['total_clawback_gross_won']:,}원 − 미공제 이월세액 소멸 {pkg['total_carryforward_offset_won']:,}원 [각주 4, 5] |",
        f"| **5. 농어촌특별세 (실공제세액의 20%)** | **{pkg['rural_special_tax_won']:,}원** | 실공제 {pkg['actual_deducted_credit_won']:,}원 기준 ([조문:농어촌특별세법 제5조 제1항] [각주 7]) |",
        f"| **최종 실질 순절세액 (합계 − 4 − 5)** | **{pkg['net_after_rural_tax_won']:,}원** | **{cf_note_str}** |",
        "",
        f"### (3) 4개 과세연도({tax_yr-3}~{tax_yr}년) 세액공제 및 추가납부세액 총괄표",
        "",
        f"| 구분 | 차수 | {yr_list[0]}년 | {yr_list[1]}년 | {yr_list[2]}년 | {yr_list[3]}년 (당해 귀속) | 근거 법령 |",
        "| :---: | :---: | ---: | ---: | ---: | ---: | :--- |",
        f"| **세액공제액 (추가납부액)** | **1차** | {_m_txt(matrix_cols[yr_list[0]]['r1_credit'], matrix_cols[yr_list[0]]['r1_claw'])} | {_m_txt(matrix_cols[yr_list[1]]['r1_credit'], matrix_cols[yr_list[1]]['r1_claw'])} | {_m_txt(matrix_cols[yr_list[2]]['r1_credit'], matrix_cols[yr_list[2]]['r1_claw'])} | **{_m_txt(matrix_cols[yr_list[3]]['r1_credit'], matrix_cols[yr_list[3]]['r1_claw'])}** | [조문:조세특례제한법 제29조의8 제1항] [각주 1] |",
        f"| **세액공제액 (추가납부액)** | **2차** | {_m_txt(matrix_cols[yr_list[0]]['r2_credit'], matrix_cols[yr_list[0]]['r2_claw'])} | {_m_txt(matrix_cols[yr_list[1]]['r2_credit'], matrix_cols[yr_list[1]]['r2_claw'])} | {_m_txt(matrix_cols[yr_list[2]]['r2_credit'], matrix_cols[yr_list[2]]['r2_claw'])} | **{_m_txt(matrix_cols[yr_list[3]]['r2_credit'], matrix_cols[yr_list[3]]['r2_claw'])}** | 구 조특법 제29조의8 제3항 (부칙 경과조치) [각주 3, 4] |",
        f"| **세액공제액 (추가납부액)** | **3차** | {_m_txt(matrix_cols[yr_list[0]]['r3_credit'], matrix_cols[yr_list[0]]['r3_claw'])} | {_m_txt(matrix_cols[yr_list[1]]['r3_credit'], matrix_cols[yr_list[1]]['r3_claw'])} | {_m_txt(matrix_cols[yr_list[2]]['r3_credit'], matrix_cols[yr_list[2]]['r3_claw'])} | **{_m_txt(matrix_cols[yr_list[3]]['r3_credit'], matrix_cols[yr_list[3]]['r3_claw'])}** | 구 조특법 제29조의8 제3항 (부칙 경과조치) [각주 3, 4] |",
        f"| **합계** | **순액** | **{int(matrix_cols[yr_list[0]]['net_total']):,}원** | **{int(matrix_cols[yr_list[1]]['net_total']):,}원** | **{int(matrix_cols[yr_list[2]]['net_total']):,}원** | **{int(matrix_cols[yr_list[3]]['net_total']):,}원** | [조문:조세특례제한법 제132조] · [조문:조세특례제한법 제144조] [각주 5] |",
        "",
        f"## Ⅱ. {tax_yr}년 귀속 세액공제 및 사후관리 상세 산출근거",
        f"### (1) 평균 상시근로자 증가 인원 및 코호트별 상시근로자 현황 [각주 2, 3]",
        *prev_basis_bullets,
        "",
        "| 구분 | 전체 상시<br>[총인원 / 평균] | 청년등<br>[총인원 / 평균] | 청년등 외<br>[총인원 / 평균] | 산정 기준 및 법령 근거 |",
        "| :--- | ---: | ---: | ---: | :--- |",
        f"| **{tax_yr}년 귀속 [{b3_title}]** | {cur_s['reg_total']:g}명 / **{cur_s['regular']:.2f}명** | {cur_s['yth_total']:g}명 / **{cur_s['youth']:.2f}명** | {cur_s['non_youth_total']:g}명 / **{cur_s['non_youth']:.2f}명** | 신법(실제 근로기간 1년 미만 제외 · 합산 후 절사) [각주 2] |",
        f"| **{tax_yr}년 귀속 [{b4_title}]** | {cur_s['reg_total']:g}명 / **{cur_s['b2_reg']:.2f}명** | {cur_s['b2_yth_total']:g}명 / **{cur_s['b2_yth']:.2f}명** | {round(max(0.0, cur_s['reg_total']-cur_s['b2_yth_total']),2):g}명 / **{round(max(0.0, cur_s['b2_reg']-cur_s['b2_yth']),2):.2f}명** | {pm_row_note} |",
        f"| **{tax_yr}년 귀속 [{b5_title}]** | {cur_s['reg_total']:g}명 / **{cur_s['b3_reg']:.2f}명** | {cur_s['b3_yth_total']:g}명 / **{cur_s['b3_yth']:.2f}명** | {round(max(0.0, cur_s['reg_total']-cur_s['b3_yth_total']),2):g}명 / **{round(max(0.0, cur_s['b3_reg']-cur_s['b3_yth']),2):.2f}명** | {pm_row_note} |",
        f"| **{tax_yr-1}년 사후관리 기초 ({basis_lbl})** | - / **{pm1['init_reg']:.2f}명** | - / **{pm1['init_yth']:.2f}명** | - / **{round(max(0.0, pm1['init_reg']-pm1['init_yth']),2):.2f}명** | 1차 사후관리 비교 기준 (증가 청년 {pm1['init_yth_inc']:.2f}명 · 일반 {pm1['init_gen_inc']:.2f}명) |",
        f"| **{tax_yr-2}년 사후관리 기초 ({basis_lbl})** | - / **{pm2['init_reg']:.2f}명** | - / **{pm2['init_yth']:.2f}명** | - / **{round(max(0.0, pm2['init_reg']-pm2['init_yth']),2):.2f}명** | 2차 사후관리 비교 기준 (증가 청년 {pm2['init_yth_inc']:.2f}명 · 일반 {pm2['init_gen_inc']:.2f}명) |",
        "",
        f"### (2) 1차년도({tax_yr}년 귀속) 세액공제액 계산 ({corp_sz}, {loc_label}) [각주 1]",
        f"- **신법 산식 구조 및 적용 단가**: 현행 [조문:조세특례제한법 제29조의8 제1항]은 직전 3개 과세연도(2024.12.31. 이전 개시 과세연도 제외) 중 1개 이상 대비 상시근로자 수가 증가한 경우 `A(직전연도 대비 1년차 증가분) + B(전전연도 대비 2년차 유지분) + C(전전전연도 대비 3년차 유지분)`를 합산하도록 규정하고 있습니다. {tax_yr}년 귀속은 비교 대상 과세연도가 {tax_yr-1}년(A)뿐이므로 A만 적용되며(청년등 1인당 **{yu:,}원**, 청년등 외 1인당 **{gu:,}원**), {tax_yr}년 신법 공제분은 사후관리 추징 규정이 적용되지 않습니다(고용 감소에 따른 추징 리스크는 2024·2025년 귀속분에 한정).",
        f"- **계산 산식**: (청년등 증가 {cur_inc['youth_inc']:.2f}명 × {yu:,}원) + (청년등 외 증가 {cur_inc['non_youth_inc']:.2f}명 × {gu:,}원)"
        + (f" − 최소고용증가인원 차감([조문:조세특례제한법 시행령 제26조의8 제3항]) {pkg['cur_new_ded_won']:,}원" if pkg.get("cur_new_ded_won", 0) > 0 else "")
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
        "- **[각주 1] [조문:조세특례제한법 제29조의8 제1항]·[조문:조세특례제한법 제29조의8 제2항]·[조문:조세특례제한법 제29조의8 제4항]·[조문:조세특례제한법 제29조의8 제5항] (통합고용세액공제 기본공제 A+B+C 구조 및 추가공제)**: 소비성서비스업 등 제외 업종 외의 내국인이 직전 3개 과세연도(2024.12.31. 이전 개시 과세연도 제외) 중 1개 이상 대비 상시근로자 수가 증가한 경우 1년차(A, 중소 수도권 청년등 700만·일반 400만 / 비수도권 청년등 1,000만·일반 700만), 2년차(B), 3년차(C) 유지분 금액을 합한 금액(중견 5명·대기업 10명 최소고용증가인원 차감 반영, [조문:조세특례제한법 시행령 제26조의8 제3항])을 공제한다. 제2항은 경력단절 근로자 정의, 제4항은 정규직 전환 추가공제(2024.12.31. 이전 전환분까지만 적용), 제5항은 육아휴직 복귀자 추가공제를 규정한다.",
        "- **[각주 2] [조문:조세특례제한법 시행령 제26조의8 제2항]·[조문:조세특례제한법 시행령 제26조의8 제4항]·[조문:조세특례제한법 시행령 제26조의8 제6항] 및 [조문:조세특례제한법 시행령 제11조의2 제8항] 준용 (상시근로자 범위 · 내국인 근로자 정의 · 청년등 증가한도 Cap · 소수점 절사)**: 상시근로자란 「근로기준법」에 따라 근로계약을 체결한 내국인 근로자([조문:조세특례제한법 제2조] 제1항 제1호 및 시행규칙 별지 제10호의10서식 작성방법, 국세청 사전-2020-법령해석소득-0239에 따라 국적과 무관하게 「소득세법」상 국내에 주소를 두거나 183일 이상 거소를 둔 거주자인 외국인 근로자 포함) 중 실제 근로기간 1년 미만자(제2항 제1호, 대통령령 제35999호 개정), 월평균 60시간 미만 단시간근로자, 법인의 등기임원, 최대주주·배우자·직계존비속([조문:조세특례제한법 시행령 제23조 제10항] 준용)을 제외한 자를 말한다. 청년등 상시근로자 증가인원은 **전체 상시근로자 증가인원을 한도(Cap)**로 하며(제4항), 상시근로자 수는 매월 말 현재 상시근로자 수의 합을 과세연도 개월 수로 나눈 뒤 **100분의 1 미만 부분을 버린다(합산 후 소수점 둘째 자리 절사, 제6항 및 제11조의2 제8항 준용)**.",
        "",
        "### (2) 구법 경과조치(사후관리·연속공제·추가납부) 및 최저한세·이월공제·고용승계 특례 규정",
        "- **[각주 3] 구 조세특례제한법(법률 제21065호 개정 전) 제29조의8 제3항 및 대통령령 제35999호 부칙 제2조 (2024·2025년 귀속분 연속공제·사후관리 경과조치 및 청년 연령경과 간주)**: 현행 제29조의8에서 구 제3항은 삭제되었으나, **개정 법률 부칙 및 대통령령 제35999호(2025.12.31.) 부칙 제2조(통합고용세액공제에 관한 경과조치)**에 따라 2024년 또는 2025년 귀속 과세연도에 상시근로자 수가 증가한 분에 대한 이후 1~2년간의 2·3차년도 연속공제 및 사후관리(상시근로자 산정 시 계약기간 1년 이상 중도퇴사자 포함 및 구 시행령 제26조의8 제5항에 따른 최초 공제연도 청년등의 연령경과 간주 특례)는 **종전의 규정**에 따른다.",
        "- **[각주 4] 구 조세특례제한법 제29조의8 제3항 및 구 시행령 제26조의8 제6항 (고용 감소 시 추가납부세액 산식 및 이자상당가산액 면제)**: 2024·2025년 귀속 공제분(종전 규정 적용 대상)에 대하여 공제를 받은 과세연도 종료일부터 2년(대기업 1년)이 되는 날이 속하는 과세연도 종료일까지 전체 상시근로자 수가 감소한 경우 연속공제를 중단하고 감소 인원분 공제세액을 추가납부하며(Case 1·Case 2), 전체 상시근로자 수는 유지되었으나 청년등 상시근로자 수만 감소한 경우(Case 3)에는 청년등 단가와 일반 단가의 차액만을 추가납부한다(기공제세액 한도, 이자상당가산액 미부과). 반면 2026년 이후 신법(제1항 A+B+C 구조) 적용분은 사후관리 추징 규정이 없다.",
        "- **[각주 5] [조문:조세특례제한법 제132조] 및 [조문:조세특례제한법 제144조] (최저한세 적용 및 10년 이월공제 · 미공제 이월세액 우선 소멸)**: 통합고용세액공제는 [조문:조세특례제한법 제132조]에 따른 최저한세(중소기업 과세표준의 7%, 중견·일반기업 10~17%) 적용 대상이므로, 당기 산출세액에서 최저한세 한도를 초과하여 공제받지 못한 세액은 [조문:조세특례제한법 제144조] 제1항에 따라 10년간 이월공제한다. 또한 사후관리 위반으로 추가납부 사유가 발생하였으나 당초 공제받지 못하고 이월된 세액공제액이 남아 있는 경우 현금 추가납부 대신 해당 미공제 이월세액을 먼저 차감(소멸)한다.",
        "- **[각주 6] [조문:조세특례제한법 시행령 제26조의8 제10항] 및 [조문:조세특례제한법 시행령 제23조 제13항] 준용 (포괄양수·합병·분할·법인전환 고용승계 특례)**: 과세연도 중 사업을 포괄양수하거나 합병·분할·현물출자·법인전환에 따라 고용을 승계한 기업의 직전 과세연도 상시근로자 수는 기존 사업장 직전 인원에 승계 사업장 직전 인원을 더한 수로 하고, 당해 과세연도에는 과세연도 개시일에 승계한 것으로 보아 근무기간을 통산한다.",
        "- **[각주 7] [조문:농어촌특별세법 제5조 제1항] 제1호 (농어촌특별세 20%)**: 조세특례제한법에 따라 당기 실제로 감면(공제)받는 소득세·법인세 세액(최저한세 등으로 당기 공제받지 못하고 이월된 미공제 세액은 제외하며 실제 이월공제받는 연도에 과세)의 **100분의 20**을 농어촌특별세로 납부한다.",
        "",
        "## Ⅳ. 심층 세무진단 의견",
        audit_body,
    ]
    full_md = _sanitize_markdown_tilde("\n".join(lines))
    if hasattr(P, "inject_verified_law_links"):
        full_md = P.inject_verified_law_links(full_md)
    return full_md


def _build_report_pdf_bytes(s: dict, log_tokens_fn=None, room_key: str = "") -> bytes:
    """
    4단계 『보고서 PDF 다운』 전용 빌더:
    - 화면의 대제목 / 중제목(I~IV) / 소제목 / 본문·표를 그대로 A4 세로(Portrait) 정식 PDF로 출력합니다.
    - 전각 로마숫자(Ⅰ~Ⅳ) 및 유니코드 물결표(∼)·마이너스(−) 폰트 누락 방지, 소제목 고립(Orphan Heading) 방지,
      표 숫자·금액 열 우측 정렬 및 합계 행 하이라이트, 하단 페이지 번호를 적용합니다.
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
        bottomMargin=32,
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
        keepWithNext=True,
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
        keepWithNext=True,
    )
    st_h3 = ParagraphStyle(
        "ECRepH3",
        parent=styles["Normal"],
        fontName=bold_font,
        fontSize=10.2,
        leading=14.5,
        textColor=colors.HexColor("#0f172a"),
        spaceBefore=8,
        spaceAfter=4,
        keepWithNext=True,
    )
    st_body = ParagraphStyle(
        "ECRepBody",
        parent=styles["Normal"],
        fontName=reg_font,
        fontSize=9.2,
        leading=14.2,
        textColor=colors.HexColor("#1e293b"),
        spaceAfter=3.5,
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
    st_tbl_cell_l = ParagraphStyle(
        "ECRepTblCellL",
        parent=styles["Normal"],
        fontName=reg_font,
        fontSize=8.2,
        leading=11.2,
        alignment=0,
        textColor=colors.HexColor("#1e293b"),
    )
    st_tbl_cell_c = ParagraphStyle(
        "ECRepTblCellC",
        parent=styles["Normal"],
        fontName=reg_font,
        fontSize=8.2,
        leading=11.2,
        alignment=1,
        textColor=colors.HexColor("#1e293b"),
    )
    st_tbl_cell_r = ParagraphStyle(
        "ECRepTblCellR",
        parent=styles["Normal"],
        fontName=reg_font,
        fontSize=8.2,
        leading=11.2,
        alignment=2,
        textColor=colors.HexColor("#1e293b"),
    )

    md_full = _build_report_markdown(s, log_tokens_fn=log_tokens_fn, room_key=room_key)
    # PDF 출력 시 마크다운 링크 `[텍스트](https://...)`에서 URL 괄호를 벗기고 텍스트만 깔끔하게 표시
    md_full = re.sub(r"\[(\[(?:조문|부칙|별표|판례|심판례|헌재|헌재결정례|해석례|예규)\s*:\s*[^\]]+\])\]\(https?://[^\s)]+\)", r"\1", md_full)
    md_full = re.sub(r"\[([^\]]+)\]\(https?://[^\s)]+\)", r"\1", md_full)
    story = []

    lines = md_full.splitlines()
    idx = 0
    while idx < len(lines):
        raw_ln = _strip_all_emojis(lines[idx]).strip()
        if not raw_ln or raw_ln == "---":
            idx += 1
            continue

        if "적용 모델:" in raw_ln or "적용모델:" in raw_ln:
            idx += 1
            continue

        if raw_ln.startswith("|") and raw_ln.endswith("|"):
            tbl_lines = []
            while idx < len(lines):
                cand = _strip_all_emojis(lines[idx]).strip()
                if cand.startswith("|") and cand.endswith("|"):
                    tbl_lines.append(cand)
                    idx += 1
                else:
                    break
            col_aligns: list[str] = []
            raw_rows: list[list[str]] = []
            for t_ln in tbl_lines:
                cells = [c.strip() for c in t_ln.strip("|").split("|")]
                if all(re.match(r"^[:\-]+$", c.replace(" ", "")) for c in cells if c):
                    col_aligns = []
                    for c in cells:
                        cs = c.replace(" ", "")
                        if cs.startswith(":") and cs.endswith(":"):
                            col_aligns.append("C")
                        elif cs.endswith(":"):
                            col_aligns.append("R")
                        else:
                            col_aligns.append("L")
                    continue
                raw_rows.append(cells)

            parsed_rows = []
            highlight_row_indices: list[tuple[int, str]] = []
            for r_i, cells in enumerate(raw_rows):
                is_hdr = r_i == 0
                row_paras = []
                first_cell_plain = re.sub(r"\*+", "", cells[0] if cells else "").strip()
                if not is_hdr:
                    if first_cell_plain.startswith("최종 실질 순절세액"):
                        highlight_row_indices.append((r_i, "#dbeafe"))
                    elif first_cell_plain.startswith("합계"):
                        highlight_row_indices.append((r_i, "#f1f5f9"))
                for c_i, c_txt in enumerate(cells):
                    c_clean = c_txt.replace("<br>", "\n")
                    if is_hdr:
                        p_style = st_tbl_hdr
                    else:
                        al = col_aligns[c_i] if c_i < len(col_aligns) else "L"
                        p_style = st_tbl_cell_r if al == "R" else (st_tbl_cell_c if al == "C" else st_tbl_cell_l)
                    row_paras.append(Paragraph(_pdf_text(c_clean).replace("\n", "<br/>"), p_style))
                parsed_rows.append(row_paras)

            if parsed_rows:
                n_cols = len(parsed_rows[0])
                if n_cols == 3:
                    col_w = [avail_w * 0.35, avail_w * 0.19, avail_w * 0.46]
                elif n_cols == 4:
                    col_w = [avail_w * 0.18, avail_w * 0.32, avail_w * 0.18, avail_w * 0.32]
                elif n_cols == 5:
                    col_w = [avail_w * 0.23, avail_w * 0.17, avail_w * 0.17, avail_w * 0.17, avail_w * 0.26]
                elif n_cols == 7:
                    col_w = [avail_w * 0.15, avail_w * 0.07, avail_w * 0.13, avail_w * 0.13, avail_w * 0.13, avail_w * 0.15, avail_w * 0.24]
                else:
                    col_w = [avail_w / n_cols] * n_cols
                t_obj = Table(parsed_rows, colWidths=col_w, repeatRows=1)
                t_cmds = [
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
                for hr_idx, hex_bg in highlight_row_indices:
                    t_cmds.append(("BACKGROUND", (0, hr_idx), (-1, hr_idx), colors.HexColor(hex_bg)))
                t_obj.setStyle(TableStyle(t_cmds))
                story.append(t_obj)
                story.append(Spacer(1, 5))
            continue

        if raw_ln.startswith("# "):
            story.append(Paragraph(_pdf_text(raw_ln[2:].strip()), st_h1))
            idx += 1
            continue

        if raw_ln.startswith("## "):
            h2_tbl = Table([[Paragraph(_pdf_text(raw_ln[3:].strip()), st_h2)]], colWidths=[avail_w])
            h2_tbl.keepWithNext = True
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

        if raw_ln.startswith("### ") or raw_ln.startswith("#### "):
            sub_txt = re.sub(r"^#{3,4}\s*", "", raw_ln).strip()
            p_h3 = Paragraph(_pdf_text(f"■ {sub_txt}"), st_h3)
            p_h3.keepWithNext = True
            story.append(p_h3)
            idx += 1
            continue

        if raw_ln.startswith(">"):
            q_txt = raw_ln.lstrip("> ").strip()
            story.append(Paragraph(_pdf_text(q_txt), st_meta))
            idx += 1
            continue

        if raw_ln.startswith("- ") or raw_ln.startswith("* "):
            b_txt = "• " + raw_ln[2:].strip()
            story.append(Paragraph(_pdf_text(b_txt), st_body))
        else:
            story.append(Paragraph(_pdf_text(raw_ln), st_body))
        idx += 1

    def _draw_page_footer(canvas, doc_obj):
        canvas.saveState()
        canvas.setFont(reg_font, 8.0)
        canvas.setFillColor(colors.HexColor("#64748b"))
        page_str = f"- {canvas.getPageNumber()} -"
        canvas.drawCentredString(A4[0] / 2.0, 14, page_str)
        canvas.restoreState()

    doc.build(story, onFirstPage=_draw_page_footer, onLaterPages=_draw_page_footer)
    return buf.getvalue()


def _page_report(room_key: str = "", log_tokens_fn=None):
    s = _S()
    _ensure_built_for_tax_year(s)
    tax_yr = int(s["tax_year"])

    with st.spinner("법제처 API 실시간 조문·직링크 연동 및 심층 세무진단 보고서를 구성하고 있습니다..."):
        audit_clean_body, model_used = _ensure_auto_pro_audit_comment(s, log_tokens_fn=log_tokens_fn, room_key=room_key)

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

    md_text = _build_report_markdown(s, log_tokens_fn=log_tokens_fn, room_key=room_key)
    pdf_report_bytes = _build_report_pdf_bytes(s, log_tokens_fn=log_tokens_fn, room_key=room_key)

    st.markdown(f"<div class='ec-agent-report-wrap'>\n\n{md_text}\n\n</div>", unsafe_allow_html=True)

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
        if ce2.button("🔄 AI 의견 다시 생성 (법제처 API 재조회)", use_container_width=True, key="btn_regen_audit"):
            s["pro_audit_comment"] = ""
            s["pro_audit_sig"] = ""
            _save_ec_to_disk(s)
            st.rerun()

    st.markdown(
        f"<div class='ec-model-footer-bar'>"
        f"<span>심층 세무진단 분석 완료 (법제처 Open API 조문·직링크 연동)</span>"
        f"<span>적용 모델: <code>{disp_model}</code> (스크린 전용 표시 · PDF 출력 제외)</span>"
        f"</div>",
        unsafe_allow_html=True,
    )

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