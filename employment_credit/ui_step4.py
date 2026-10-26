# -*- coding: utf-8 -*-
"""통합고용세액공제 계산기 화면 — 4단계 보고서: 보고서·PDF·CSV 내려받기

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



def _strip_all_emojis(text: str) -> str:
    """보고서 본문 및 기존 캐시된 AI 코멘트에서 아이콘·이모지를 모두 제거합니다."""
    if not text:
        return ""
    return _REPORT_EMOJI_RE.sub("", str(text))


def _sanitize_markdown_tilde(text: str) -> str:
    """
    마크다운(GFM)에서 `10~12월 ... 10~12월`처럼 한 문단에 물결표(`~`)가 두 번 이상 들어가면
    사이에 있는 문장 전체가 취소선(`<del>...</del>`)으로 렌더링되고 물결표가 사라져 `1012월`로 깨지는 문제를 방지합니다.
    반각 물결표(`~`)를 취소선 문법으로 인식되지 않는 유니코드 물결표(`∼`, U+223C)로 변환합니다.
    """
    if not text:
        return ""
    s = str(text)
    s = re.sub(r"~~+", "∼", s)
    s = s.replace("~", "∼")
    s = re.sub(r"\b(1[0-2]|[1-9])12월", r"\1∼12월", s)
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

        # 패턴 A: 이미 ### 또는 #### 소제목인 경우
        if s_no_icon.startswith("### ") or s_no_icon.startswith("#### "):
            hdr_t = re.sub(r"^#{3,4}\s*", "", s_no_icon).strip()
            hdr_t = re.sub(r"^\*\*(.+?)\*\*$", r"\1", hdr_t).strip()
            if not re.match(r"^\(\d+\)", hdr_t):
                sub_idx += 1
                hdr_t = f"({sub_idx}) {hdr_t}"
            cleaned_lines.append("")
            cleaned_lines.append(f"### {hdr_t}")
            continue

        # 패턴 B: 번호형 소제목 (`1. **추가 절세...**` 또는 `(1) **추가 절세...**`)
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

        # 패턴 C: 불릿 단독 볼드 소제목 (`- **추가 절세 가능성 발굴**` — 뒤에 콜론 설명이 없는 줄)
        m_bullet_hdr = re.match(r"^(?:[-*•])\s*\*\*([^*:：]{3,40})\*\*\s*$", s_no_icon)
        if m_bullet_hdr:
            sub_idx += 1
            title_part = m_bullet_hdr.group(1).strip()
            cleaned_lines.append("")
            cleaned_lines.append(f"### ({sub_idx}) {title_part}")
            continue

        # 패턴 D: 들여쓰기된 2단 불릿(`  - ...` 또는 `  * ...`)을 깔끔한 1단 불릿(`- ...`)으로 평탄화
        if re.match(r"^\s+[-*•]\s+", no_icon):
            cleaned_lines.append("- " + re.sub(r"^\s+[-*•]\s+", "", no_icon).strip())
            continue

        cleaned_lines.append(s_no_icon)

    body = "\n".join(cleaned_lines).strip()
    return body, model_name


def _ensure_auto_pro_audit_comment(s: dict, log_tokens_fn=None, room_key: str = "") -> tuple[str, str]:
    """
    4단계 진입 시 버튼 클릭 없이도 『Ⅳ. 심층 세무진단 의견』이 항상 자동으로 생성·표시되도록 보장합니다.
    """
    _ensure_built_for_tax_year(s)
    tax_yr = int(s["tax_year"])
    shown_years = _years(s)
    cur_sig = f"{s.get('built_sig')}|{tax_yr}|{s.get('pm_basis')}"

    existing_raw = str(s.get("pro_audit_comment") or "").strip()
    if existing_raw and not existing_raw.startswith("❌") and s.get("pro_audit_sig") == cur_sig:
        body, mod_nm = _parse_and_clean_pro_audit(existing_raw)
        if body:
            if not mod_nm:
                mod_nm = str(s.get("pro_audit_model") or "gemini-2.5-pro")
            s["pro_audit_model"] = mod_nm
            return body, mod_nm

    if existing_raw and not existing_raw.startswith("❌") and not s.get("pro_audit_sig"):
        body, mod_nm = _parse_and_clean_pro_audit(existing_raw)
        if body:
            if not mod_nm:
                mod_nm = str(s.get("pro_audit_model") or "gemini-2.5-pro")
            s["pro_audit_model"] = mod_nm
            s["pro_audit_sig"] = cur_sig
            return body, mod_nm

    computed_all, totals_all, ctx_all = {}, {}, {}
    for y in shown_years:
        _, comp_y, tot_y = _build_year_rows(s, y)
        computed_all[y] = comp_y
        totals_all[y] = tot_y
        ctx_all[y] = _ctx(s, y)

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
        "결정론적_검토항목": [{"구분": lv, "내용": _strip_all_emojis(msg)} for lv, msg in review_items],
    }

    raw_generated = P.call_pro_argon_audit_commentary(
        audit_payload, log_tokens_fn=log_tokens_fn, room_key=room_key
    )
    body, mod_nm = _parse_and_clean_pro_audit(raw_generated)
    if not mod_nm:
        mod_nm = "gemini-2.5-pro"
    s["pro_audit_comment"] = raw_generated
    s["pro_audit_model"] = mod_nm
    s["pro_audit_sig"] = cur_sig
    _save_ec_to_disk(s)
    return body, mod_nm


def _build_report_markdown(s: dict, log_tokens_fn=None, room_key: str = "") -> str:
    """
    [4단계 보고서 마크다운 생성 — 고가독성 표·목록 위계 · 무아이콘 · Ⅳ. 심층 세무진단 의견 상시 포함]
    - 마크다운 표 앞에는 반드시 빈 줄(`""`)을 두어 표가 텍스트로 깨지지 않고 100% 정식 표로 렌더링되게 합니다.
    - Ⅰ-(1) 사업자 기본사항도 한눈에 들어오는 4열 요약표로 구성합니다.
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
        scheme_desc = "2026년 개편 신법(연차별 차등 인센티브 1년차 단가) [각주 1]"
    else:
        r_leg = pkg["rates_legacy"]
        yu, gu = r_leg["청년등"] * 10_000, r_leg["청년등외"] * 10_000
        scheme_desc = "조세특례제한법 제29조의8 제1항 기본공제 단가 [각주 1]"

    pm1_reg_dec = "여(감소)" if (pm1.get("active") and not pm1.get("base_missing") and cur_s["b2_reg"] < pm1.get("init_reg", 0)) else "부(유지·증가)"
    pm1_yth_dec = "여(감소)" if (pm1.get("active") and not pm1.get("base_missing") and cur_s["b2_yth"] < pm1.get("init_yth", 0)) else "부(유지·증가)"
    pm2_reg_dec = "여(감소)" if (pm2.get("active") and not pm2.get("base_missing") and cur_s["b3_reg"] < pm2.get("init_reg", 0)) else "부(유지·증가)"
    pm2_yth_dec = "여(감소)" if (pm2.get("active") and not pm2.get("base_missing") and cur_s["b3_yth"] < pm2.get("init_yth", 0)) else "부(유지·증가)"

    audit_body, _ = _ensure_auto_pro_audit_comment(s, log_tokens_fn=log_tokens_fn, room_key=room_key)

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
        f"| **1. 당해({tax_yr}년) 1차년도 신규 고용증가 세액공제** | **{pkg['cur_base_credit_won']:,}원** | 청년등 +{pkg['cur_inc']['youth_inc']:.2f}명, 청년등 외 +{pkg['cur_inc']['non_youth_inc']:.2f}명 (조특법 제29조의8 제1항 [각주 1]) |",
        f"| **2. 직전·전전연도({tax_yr-1}·{tax_yr-2}년) 기공제분 연속공제액** | **{pkg['total_continued_credit_won']:,}원** | 2차년도 {pm1['continued_credit_won']:,}원 + 3차년도 {pm2['continued_credit_won']:,}원 (조특법 제29조의8 제3항 [각주 3]) |",
        f"| **3. 육아휴직 복귀 및 정규직 전환 추가공제액** | **{pkg['additional_credit_won']:,}원** | 복귀 {pkg['parental_ret_cnt']}명 / 전환 {pkg['reg_conv_cnt']}명 (조특법 제29조의8 제2항) |",
        f"| **합계: 당해 총 공제세액 (1+2+3)** | **{pkg['total_credit_gross_won']:,}원** | **공제감면세액계산서 및 세액공제신청서 반영 금액** |",
        f"| **4. 사후관리 추가납부세액 (이월공제 차감 후)** | **{pkg['total_clawback_net_payable_won']:,}원** | 차감전 추징액 {pkg['total_clawback_gross_won']:,}원 − 미공제 이월세액 소멸 {pkg['total_carryforward_offset_won']:,}원 [각주 4, 5] |",
        f"| **5. 농어촌특별세 (실공제세액의 20%)** | **{pkg['rural_special_tax_won']:,}원** | 실공제 {pkg['actual_deducted_credit_won']:,}원 기준 (농어촌특별세법 제5조 제1항 [각주 7]) |",
        f"| **최종 실질 순절세액 (합계 − 4 − 5)** | **{pkg['net_after_rural_tax_won']:,}원** | **당해 최저한세 등 미공제 이월액 {pkg['cur_unclaimed_cf_won']:,}원 반영** |",
        "",
        f"### (3) 4개 과세연도({tax_yr-3}~{tax_yr}년) 세액공제 및 추가납부세액 총괄표",
        "",
        f"| 구분 | 차수 | {yr_list[0]}년 | {yr_list[1]}년 | {yr_list[2]}년 | {yr_list[3]}년 (당해 귀속) | 근거 법령 |",
        "| :---: | :---: | ---: | ---: | ---: | ---: | :--- |",
        f"| **세액공제액 (추가납부액)** | **1차** | {_m_txt(matrix_cols[yr_list[0]]['r1_credit'], matrix_cols[yr_list[0]]['r1_claw'])} | {_m_txt(matrix_cols[yr_list[1]]['r1_credit'], matrix_cols[yr_list[1]]['r1_claw'])} | {_m_txt(matrix_cols[yr_list[2]]['r1_credit'], matrix_cols[yr_list[2]]['r1_claw'])} | **{_m_txt(matrix_cols[yr_list[3]]['r1_credit'], matrix_cols[yr_list[3]]['r1_claw'])}** | 조특법 제29조의8 제1항 [각주 1] |",
        f"| **세액공제액 (추가납부액)** | **2차** | {_m_txt(matrix_cols[yr_list[0]]['r2_credit'], matrix_cols[yr_list[0]]['r2_claw'])} | {_m_txt(matrix_cols[yr_list[1]]['r2_credit'], matrix_cols[yr_list[1]]['r2_claw'])} | {_m_txt(matrix_cols[yr_list[2]]['r2_credit'], matrix_cols[yr_list[2]]['r2_claw'])} | **{_m_txt(matrix_cols[yr_list[3]]['r2_credit'], matrix_cols[yr_list[3]]['r2_claw'])}** | 조특법 제29조의8 제3항 [각주 3, 4] |",
        f"| **세액공제액 (추가납부액)** | **3차** | {_m_txt(matrix_cols[yr_list[0]]['r3_credit'], matrix_cols[yr_list[0]]['r3_claw'])} | {_m_txt(matrix_cols[yr_list[1]]['r3_credit'], matrix_cols[yr_list[1]]['r3_claw'])} | {_m_txt(matrix_cols[yr_list[2]]['r3_credit'], matrix_cols[yr_list[2]]['r3_claw'])} | **{_m_txt(matrix_cols[yr_list[3]]['r3_credit'], matrix_cols[yr_list[3]]['r3_claw'])}** | 조특법 제29조의8 제3항 [각주 3, 4] |",
        f"| **합계** | **순액** | **{int(matrix_cols[yr_list[0]]['net_total']):,}원** | **{int(matrix_cols[yr_list[1]]['net_total']):,}원** | **{int(matrix_cols[yr_list[2]]['net_total']):,}원** | **{int(matrix_cols[yr_list[3]]['net_total']):,}원** | 조특법 제144조 [각주 5] |",
        "",
        f"## Ⅱ. {tax_yr}년 귀속 세액공제 및 사후관리 상세 산출근거",
        f"### (1) 평균 상시근로자 증가 인원 및 코호트별 상시근로자 현황 [각주 2, 3]",
        f"- **산정 방법**: 매월 말 현재 상시근로자 수의 연간 합계(연인원)를 해당 과세연도 개월 수({cur_s['months_in_year']}개월)로 나눈 뒤 소수점 셋째 자리에서 버림(100분의 1 미만 절사, 조특령 제26조의8 제9항)하여 산정하였습니다.",
        f"- **청년등 증가인원 한도(Cap)**: 청년등 상시근로자 증가인원(+{cur_inc['youth_inc']:.2f}명)은 전체 상시근로자 증가인원(+{cur_inc['total_inc']:.2f}명)을 한도로 적용하였습니다(조특령 제26조의8 제3항).",
        "",
        "| 구분 | 전체 상시 [총인원 / 평균] | 청년등 [총인원 / 평균] | 청년등 외 [총인원 / 평균] | 산정 기준 및 법령 근거 |",
        "| :--- | ---: | ---: | ---: | :--- |",
        f"| **{tax_yr}년 귀속 [{b3_title}]** | {cur_s['reg_total']:g}명 / **{cur_s['regular']:.2f}명** | {cur_s['yth_total']:g}명 / **{cur_s['youth']:.2f}명** | {cur_s['non_youth_total']:g}명 / **{cur_s['non_youth']:.2f}명** | 근로계약 체결일 현재 연령 기준 (합산 후 절사) [각주 2] |",
        f"| **{tax_yr}년 귀속 [{b4_title}]** | {cur_s['reg_total']:g}명 / **{cur_s['b2_reg']:.2f}명** | {cur_s['b2_yth_total']:g}명 / **{cur_s['b2_yth']:.2f}명** | {round(max(0.0, cur_s['reg_total']-cur_s['b2_yth_total']),2):g}명 / **{round(max(0.0, cur_s['b2_reg']-cur_s['b2_yth']),2):.2f}명** | {tax_yr-1}년 입사 청년 연령경과 간주 특례 [각주 3] |",
        f"| **{tax_yr}년 귀속 [{b5_title}]** | {cur_s['reg_total']:g}명 / **{cur_s['b3_reg']:.2f}명** | {cur_s['b3_yth_total']:g}명 / **{cur_s['b3_yth']:.2f}명** | {round(max(0.0, cur_s['reg_total']-cur_s['b3_yth_total']),2):g}명 / **{round(max(0.0, cur_s['b3_reg']-cur_s['b3_yth']),2):.2f}명** | {tax_yr-2}년 입사 청년 연령경과 간주 특례 [각주 3] |",
        f"| **{tax_yr-1}년 사후관리 기초 ({basis_lbl})** | - / **{pm1['init_reg']:.2f}명** | - / **{pm1['init_yth']:.2f}명** | - / **{round(max(0.0, pm1['init_reg']-pm1['init_yth']),2):.2f}명** | 1차 사후관리 비교 기준 (증가 청년 {pm1['init_yth_inc']:.2f}명 · 일반 {pm1['init_gen_inc']:.2f}명) |",
        f"| **{tax_yr-2}년 사후관리 기초 ({basis_lbl})** | - / **{pm2['init_reg']:.2f}명** | - / **{pm2['init_yth']:.2f}명** | - / **{round(max(0.0, pm2['init_reg']-pm2['init_yth']),2):.2f}명** | 2차 사후관리 비교 기준 (증가 청년 {pm2['init_yth_inc']:.2f}명 · 일반 {pm2['init_gen_inc']:.2f}명) |",
        "",
        f"### (2) 1차년도({tax_yr}년 귀속) 세액공제액 계산 ({corp_sz}, {loc_label}) [각주 1]",
        f"- **적용 단가 근거**: {scheme_desc} — 청년등 1인당 **{yu:,}원**, 청년등 외 1인당 **{gu:,}원**",
        f"- **계산 산식**: (청년등 증가 {cur_inc['youth_inc']:.2f}명 × {yu:,}원) + (청년등 외 증가 {cur_inc['non_youth_inc']:.2f}명 × {gu:,}원)"
        + (f" − 최소고용증가인원 차감 {pkg['cur_new_ded_won']:,}원" if pkg.get("cur_new_ded_won", 0) > 0 else "")
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
        "- **[각주 1] 조세특례제한법 제29조의8 제1항 (통합고용세액공제 기본공제 및 단가)**: 소비성서비스업 등 제외 업종 외의 내국인이 직전 과세연도 대비 상시근로자 수가 증가한 경우, 청년등 상시근로자 증가인원(중소 수도권 1,450만원·비수도권 1,550만원 / 2026 신법은 유지연차별 점증 단가)과 청년등 외 증가인원(중소 수도권 850만원·비수도권 950만원)에 해당 공제단가를 곱한 금액을 소득세 또는 법인세에서 공제한다.",
        "- **[각주 2] 조세특례제한법 시행령 제26조의8 제2항·제3항·제9항 (상시근로자 제외 범위 · 청년등 증가한도 Cap · 소수점 절사)**: 근로계약기간 1년 미만자(2025년 귀속부터 실제 근로기간 1년 미만자 포함), 월평균 60시간 미만 단시간근로자, 법인의 등기임원, 최대주주·최대출자자(개인사업자는 대표자)와 그 배우자·직계존비속·친족은 상시근로자에서 제외한다(제23조 제10항 준용). 청년등 상시근로자(15~34세 청년[병역기간 최대 6년 차감], 60세 이상, 장애인, 경력단절근로자, 북한이탈주민) 증가인원은 **전체 상시근로자 증가인원을 한도(Cap)**로 하며, 상시근로자 수 계산 시 근로자별 계산한 수의 합에서 **100분의 1 미만은 버린다(소수점 둘째 자리 절사, 2026.5.22. 시행령 개정 기준)**.",
        "",
        "### (2) 사후관리·연속공제·추가납부 및 고용승계 특례 규정",
        "- **[각주 3] 조세특례제한법 시행령 제26조의8 제5항 (사후관리·연속공제 시 청년등 연령경과 간주 특례)**: 최초로 공제받은 과세연도에 청년등 상시근로자에 해당하였던 자는 이후 과세연도에 연령 증가로 34세를 초과하더라도, 그 최초 공제연도 분에 대한 2·3차년도 연속공제 및 사후관리(추가납부세액) 상시근로자 수 산정 시에는 계속하여 **청년등 상시근로자로 본다**.",
        "- **[각주 4] 조세특례제한법 제29조의8 제3항 및 시행령 제26조의8 제6항 (고용 감소 시 추가납부세액 산식 및 이자상당가산액 면제)**: 공제를 받은 과세연도 종료일부터 2년(대기업 1년)이 되는 날이 속하는 과세연도 종료일까지 전체 상시근로자 수가 감소한 경우 연속공제를 중단하고 감소 인원분 공제세액을 추가납부하며(Case 1·Case 2), 전체 상시근로자 수는 유지되었으나 청년등 상시근로자 수만 감소한 경우(Case 3)에는 청년등 단가와 일반 단가의 차액(청년단가 − 일반단가)만을 추가납부한다. 이때 기공제받은 세액을 한도로 하며 이자상당가산액은 부과되지 아니한다.",
        "- **[각주 5] 조세특례제한법 제144조 및 기본통칙 (최저한세 등 미공제 이월세액 우선 소멸 특례)**: 사후관리 위반으로 추가납부 사유가 발생하였으나 최저한세 적용 또는 결손금 등으로 인하여 당초 실제로 공제받지 못하고 이월된 세액공제액(이월세액)이 남아 있는 경우, 현금으로 추가납부하는 대신 해당 미공제 이월세액을 먼저 차감(소멸)한다.",
        "- **[각주 6] 조세특례제한법 시행령 제26조의8 제10항 및 제23조 제13항 준용 (포괄양수·합병·분할·법인전환 고용승계 특례)**: 과세연도 중 사업을 포괄양수하거나 합병·분할·현물출자·법인전환에 따라 고용을 승계한 기업의 직전 과세연도 상시근로자 수는 기존 사업장 직전 인원에 승계 사업장 직전 인원을 더한 수로 하고, 당해 과세연도에는 과세연도 개시일에 승계한 것으로 보아 근무기간을 통산한다.",
        "- **[각주 7] 농어촌특별세법 제5조 제1항 제1호 (농어촌특별세 20%)**: 조세특례제한법에 따라 실제로 감면(공제)받는 소득세·법인세 세액(미공제 이월분 제외)의 **100분의 20**을 농어촌특별세로 납부한다.",
        "",
        "## Ⅳ. 심층 세무진단 의견",
        audit_body,
    ]
    return _sanitize_markdown_tilde("\n".join(lines))


def _build_report_pdf_bytes(s: dict, log_tokens_fn=None, room_key: str = "") -> bytes:
    """
    4단계 『보고서 PDF 다운』 전용 빌더:
    - 화면의 대제목 / 중제목(Ⅰ~Ⅳ) / 소제목 / 본문·표를 그대로 A4 세로(Portrait) 정식 PDF로 출력합니다.
    - 모든 그림문자(느낌표·왕관·돋보기 등)를 제거하고, 하단 적용모델 정보는 PDF에서 완전히 제외합니다.
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
        bottomMargin=26,
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
    )
    st_h3 = ParagraphStyle(
        "ECRepH3",
        parent=styles["Normal"],
        fontName=bold_font,
        fontSize=10.2,
        leading=14.5,
        textColor=colors.HexColor("#0f172a"),
        spaceBefore=7,
        spaceAfter=4,
    )
    st_body = ParagraphStyle(
        "ECRepBody",
        parent=styles["Normal"],
        fontName=reg_font,
        fontSize=9.2,
        leading=14.2,
        textColor=colors.HexColor("#1e293b"),
        spaceAfter=3,
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
    st_tbl_cell = ParagraphStyle(
        "ECRepTblCell",
        parent=styles["Normal"],
        fontName=reg_font,
        fontSize=8.2,
        leading=11.2,
        textColor=colors.HexColor("#1e293b"),
    )

    md_full = _build_report_markdown(s, log_tokens_fn=log_tokens_fn, room_key=room_key)
    story = []

    lines = md_full.splitlines()
    idx = 0
    while idx < len(lines):
        raw_ln = _strip_all_emojis(lines[idx]).strip()
        if not raw_ln or raw_ln == "---":
            idx += 1
            continue

        # 모델 정보 줄은 PDF에서 완전히 제외
        if "적용 모델:" in raw_ln or "적용모델:" in raw_ln:
            idx += 1
            continue

        # 마크다운 파이프 표 블록 처리
        if raw_ln.startswith("|") and raw_ln.endswith("|"):
            tbl_lines = []
            while idx < len(lines):
                cand = _strip_all_emojis(lines[idx]).strip()
                if cand.startswith("|") and cand.endswith("|"):
                    tbl_lines.append(cand)
                    idx += 1
                else:
                    break
            parsed_rows = []
            for r_i, t_ln in enumerate(tbl_lines):
                cells = [c.strip() for c in t_ln.strip("|").split("|")]
                if all(re.match(r"^[:\-]+$", c.replace(" ", "")) for c in cells if c):
                    continue
                is_hdr = len(parsed_rows) == 0
                row_paras = []
                for c_txt in cells:
                    c_clean = c_txt.replace("<br>", "\n")
                    p_style = st_tbl_hdr if is_hdr else st_tbl_cell
                    row_paras.append(Paragraph(_pdf_text(c_clean).replace("\n", "<br/>"), p_style))
                parsed_rows.append(row_paras)
            if parsed_rows:
                n_cols = len(parsed_rows[0])
                if n_cols == 3:
                    col_w = [avail_w * 0.36, avail_w * 0.20, avail_w * 0.44]
                elif n_cols == 4:
                    col_w = [avail_w * 0.18, avail_w * 0.32, avail_w * 0.18, avail_w * 0.32]
                elif n_cols == 5:
                    col_w = [avail_w * 0.23, avail_w * 0.17, avail_w * 0.17, avail_w * 0.17, avail_w * 0.26]
                elif n_cols == 7:
                    col_w = [avail_w * 0.15, avail_w * 0.07, avail_w * 0.13, avail_w * 0.13, avail_w * 0.13, avail_w * 0.15, avail_w * 0.24]
                else:
                    col_w = [avail_w / n_cols] * n_cols
                t_obj = Table(parsed_rows, colWidths=col_w, repeatRows=1)
                t_obj.setStyle(
                    TableStyle(
                        [
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
                    )
                )
                story.append(t_obj)
                story.append(Spacer(1, 5))
            continue

        # 대제목 (# )
        if raw_ln.startswith("# "):
            story.append(Paragraph(_pdf_text(raw_ln[2:].strip()), st_h1))
            idx += 1
            continue

        # 중제목 (## )
        if raw_ln.startswith("## "):
            h2_tbl = Table([[Paragraph(_pdf_text(raw_ln[3:].strip()), st_h2)]], colWidths=[avail_w])
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

        # 소제목 (### 또는 #### )
        if raw_ln.startswith("### ") or raw_ln.startswith("#### "):
            sub_txt = re.sub(r"^#{3,4}\s*", "", raw_ln).strip()
            story.append(Paragraph(_pdf_text(f"■ {sub_txt}"), st_h3))
            idx += 1
            continue

        # 인용구 (> )
        if raw_ln.startswith(">"):
            q_txt = raw_ln.lstrip("> ").strip()
            story.append(Paragraph(_pdf_text(q_txt), st_meta))
            idx += 1
            continue

        # 일반 불릿 (- ) 또는 본문
        if raw_ln.startswith("- ") or raw_ln.startswith("* "):
            b_txt = "• " + raw_ln[2:].strip()
            story.append(Paragraph(_pdf_text(b_txt), st_body))
        else:
            story.append(Paragraph(_pdf_text(raw_ln), st_body))
        idx += 1

    doc.build(story)
    return buf.getvalue()


def _page_report(room_key: str = "", log_tokens_fn=None):
    s = _S()
    _ensure_built_for_tax_year(s)
    tax_yr = int(s["tax_year"])

    # 버튼 클릭 없이도 Ⅳ. 심층 세무진단 의견이 항상 자동 생성·표시되도록 처리
    with st.spinner("보고서 및 심층 세무진단 의견을 구성하고 있습니다..."):
        audit_clean_body, model_used = _ensure_auto_pro_audit_comment(s, log_tokens_fn=log_tokens_fn, room_key=room_key)

    corp_nm = (s.get("biz", {}).get("상호") or "통합고용세액공제").strip()
    corp_fn = re.sub(r'[\\/:*?"<>|\s]+', "_", corp_nm)[:30]

    # 기중 가결산 안내는 상단 배너 1곳에만 깔끔하게 표시 (보고서 본문 내 중복 제거)
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

    # 보고서 본문: 자율 에이전트AI 스크린 글자크기(1.12rem) + 대/중/소제목/내용 위계 적용 래퍼
    st.markdown(f"<div class='ec-agent-report-wrap'>\n\n{md_text}\n\n</div>", unsafe_allow_html=True)

    # 사용자가 보고서 내 Ⅳ. 심층 세무진단 의견 문구를 직접 다듬거나 수정할 수 있는 편집 영역
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
        if ce2.button("🔄 AI 의견 다시 생성", use_container_width=True, key="btn_regen_audit"):
            s["pro_audit_comment"] = ""
            s["pro_audit_sig"] = ""
            _save_ec_to_disk(s)
            st.rerun()

    # 하단 적용모델 정보는 스크린에만 표시 (PDF 출력물에서는 제외됨)
    st.markdown(
        f"<div class='ec-model-footer-bar'>"
        f"<span>심층 세무진단 분석 완료</span>"
        f"<span>적용 모델: <code>{disp_model}</code> (스크린 전용 표시 · PDF 출력 제외)</span>"
        f"</div>",
        unsafe_allow_html=True,
    )

    # 하단 단일 네비게이션 & 다운로드 바 (상단 중복 PDF 버튼 제거 → 2·3단계와 동일한 하단 구조로 통일)
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
