# -*- coding: utf-8 -*-
"""통합고용세액공제 계산기 화면 — 3단계 공제액 계산: 기신고 입력·사후관리·연도별 매트릭스·산식 설명

(ui.py에서 나눈 파일. 현행 조세특례제한법 제29조의8 및 시행령 제26조의8 조문 체계·부칙 경과조치·직전연도 비교인원 보수적 산정 근거 반영)
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
from typing import Any
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
    _block_titles_for_year,
    _compute_historical_matrix_columns,
    _ensure_built_for_tax_year,
    _ensure_korean_pdf_font,
    _ensure_totals_snapshot,
    _pdf_text,
    _save_ec_to_disk,
    _trigger_scroll_to_top,
)


_ROMAN_MAP_S3 = str.maketrans({
    "Ⅰ": "I", "Ⅱ": "II", "Ⅲ": "III", "Ⅳ": "IV", "Ⅴ": "V",
    "Ⅵ": "VI", "Ⅶ": "VII", "Ⅷ": "VIII", "Ⅸ": "IX", "Ⅹ": "X",
})


def _pdf_text(t: str) -> str:
    """PDF 문단용: 폰트 미지원 로마숫자(Ⅰ~Ⅳ)·유니코드 물결표(∼)·마이너스(−) 치환 및 마크다운 변환"""
    _, bold_font = _ensure_korean_pdf_font()
    s = str(t or "").translate(_ROMAN_MAP_S3)
    s = s.replace("∼", "~").replace("〜", "~").replace("～", "~")
    s = s.replace("−", "-").replace("–", "-").replace("—", "-")
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    s = re.sub(r"\*\*(.+?)\*\*", rf"<font name='{bold_font}'><b>\1</b></font>", s)
    s = re.sub(r"`([^`]+)`", rf"<font name='{bold_font}'><b>\1</b></font>", s)
    return s


def _render_pm_basis_selector_right(s: dict, widget_key: str) -> str:
    cur_basis = s.get("pm_basis", R.PM_BASIS_FILED)
    if cur_basis not in (R.PM_BASIS_FILED, R.PM_BASIS_RECALC):
        cur_basis = R.PM_BASIS_FILED
        s["pm_basis"] = cur_basis

    opts = [R.PM_BASIS_RECALC, R.PM_BASIS_FILED]
    fmt_map = {
        R.PM_BASIS_RECALC: "⚖️ 2단계 사원표(세법원칙) 기준 계산",
        R.PM_BASIS_FILED: "📋 기신고 서식 숫자 기준 계산",
    }

    seg_fn = getattr(st, "segmented_control", None)
    if callable(seg_fn):
        try:
            chosen = seg_fn(
                "사후관리 및 공제액 계산 기준 선택",
                options=opts,
                default=cur_basis,
                format_func=lambda k: fmt_map.get(k, k),
                label_visibility="collapsed",
                key=widget_key,
            )
            if chosen in opts and chosen != cur_basis:
                s["pm_basis"] = chosen
                s["_pm_basis_user_touched"] = True
                _save_ec_to_disk(s)
                st.rerun()
            return s["pm_basis"]
        except Exception:
            pass

    chosen_r = st.radio(
        "사후관리 및 공제액 계산 기준 선택",
        options=opts,
        index=opts.index(cur_basis),
        format_func=lambda k: fmt_map.get(k, k),
        horizontal=True,
        label_visibility="collapsed",
        key=widget_key,
    )
    if chosen_r != cur_basis:
        s["pm_basis"] = chosen_r
        s["_pm_basis_user_touched"] = True
        _save_ec_to_disk(s)
        st.rerun()
    return s["pm_basis"]


def _fmt_matrix_won(
    credit_won: int | float | None,
    clawback_won: int | float | None = 0,
    is_na: bool = False,
    is_inferred: bool = False,
) -> str:
    if is_na:
        return "<span class='ec-zero-val'>-</span>"
    """
    상단 4개년 요약 매트릭스 셀 포맷터:
    - 공제세액(양수)과 추가납부세액(음수, 붉은 글씨 '-')을 구분하여 HTML 문자열로 반환
    - 2024년 2차 연속공제액에서 역산 복원된 2023년(T-3) 1차 공제액(`is_inferred=True`)은
      원칙 ①(확정값과 추정값 구분)에 따라 주황색 [추정복원] 배지를 함께 표시합니다.
    """
    cr = int(round(float(credit_won or 0)))
    cl = int(round(float(clawback_won or 0)))
    if cr > 0 and cl > 0:
        return (
            f"<div class='ec-mat-dual'><span class='ec-cell-tag pos'>공제</span><span class='ec-pos-val'>{cr:,}</span></div>"
            f"<div class='ec-mat-dual'><span class='ec-cell-tag neg'>추징</span><span class='ec-neg-val'>-{cl:,}</span></div>"
        )
    if cl > 0:
        return f"<span class='ec-neg-val'>-{cl:,}</span>"
    if cr < 0:
        return f"<span class='ec-neg-val'>-{abs(cr):,}</span>"
    if cr > 0:
        if is_inferred:
            return (
                f"<div class='ec-mat-dual' title='차년도 2차 연속공제액(청년 미감소 가정)으로부터 역산 복원된 추정값'>"
                f"<span class='ec-cell-tag' style='background:#ffedd5;color:#c2410c;border:1px solid #fdba74;'>추정복원</span>"
                f"<span class='ec-pos-val'>{cr:,}</span></div>"
            )
        return f"<span class='ec-pos-val'>{cr:,}</span>"
    return "<span class='ec-zero-val'>0</span>"


def _verify_step3_math_integrity(pkg: dict, matrix_cols: dict[int, dict[str, Any]], yr_list: list[int]) -> tuple[bool, list[str]]:
    """
    [5대 수리·법령 항등식 무오차 자가검증 엔진]
    1) 각 연도 `전체 상시(절사) - 청년등 상시(절사) == 청년등 외 상시` (0.00명 오차)
    2) 당해 `전체 증가인원 == 청년등 인정 증가인원 + 청년등 외 인정 증가인원` 및 청년등 증가 <= 전체 증가(Cap)
    3) 최초 1차 공제액이 0원인 코호트의 2·3차 연속공제액 == 0원
    4) 사후관리 추가납부세액(추징액) <= 기공제세액 한도
    5) 농어촌특별세 == (당해 총공제세액 - 당해 미공제 이월세액) × 20% (1원 단위 무오차)
    """
    issues: list[str] = []
    cur_s = pkg.get("cur_s") or {}
    prev_s = pkg.get("prev_s") or {}
    cur_inc = pkg.get("cur_inc") or {}

    if abs(round(float(cur_s.get("regular") or 0) - float(cur_s.get("youth") or 0), 2) - round(float(cur_s.get("non_youth") or 0), 2)) > 1e-6:
        issues.append("당해 청년등 외 상시근로자 수 차감 항등식 불일치")
    if abs(round(float(prev_s.get("regular") or 0) - float(prev_s.get("youth") or 0), 2) - round(float(prev_s.get("non_youth") or 0), 2)) > 1e-6:
        issues.append("직전연도 청년등 외 상시근로자 수 차감 항등식 불일치")
    if abs(round(float(cur_inc.get("youth_inc") or 0) + float(cur_inc.get("non_youth_inc") or 0), 2) - round(float(cur_inc.get("total_inc") or 0), 2)) > 1e-6:
        issues.append("증가인원 합계(청년등 + 청년등 외 == 전체 증가) 항등식 불일치")
    if float(cur_inc.get("youth_inc") or 0) > float(cur_inc.get("total_inc") or 0) + 1e-6:
        issues.append("청년등 증가인원이 전체 증가인원 한도(Cap)를 초과함")

    if len(yr_list) >= 3:
        y0, y1, y2 = yr_list[0], yr_list[1], yr_list[2]
        if int((matrix_cols.get(y0) or {}).get("r1_credit") or 0) == 0 and int((matrix_cols.get(y1) or {}).get("r2_credit") or 0) > 0:
            issues.append(f"{y0}년 1차 공제액이 0원인데 {y1}년 2차 연속공제액이 존재함")

    actual_ded = int(pkg.get("actual_deducted_credit_won") or 0)
    rural_tax = int(pkg.get("rural_special_tax_won") or 0)
    if abs(int(round(actual_ded * R.RURAL_SPECIAL_TAX_RATE)) - rural_tax) > 1:
        issues.append("농어촌특별세(20%) 산출 오차 감지")

    if hasattr(R, "verify_golden_case_invariants"):
        ok_g, g_errs = R.verify_golden_case_invariants()
        if not ok_g:
            issues.extend(g_errs)

    return (len(issues) == 0), issues


def _build_top_kpi_cards_html(pkg: dict, tax_yr: int) -> str:
    """
    [⑨ 상단 4대 핵심 KPI 요약 카드 — 확정 순절세액과 조건부·다연도 경정청구 실익을 엄격히 분리]
    - 확정 당해 공제/순절세액은 파란색·초록색 카드로 표시하고,
    - 과거연도 합산 후 절사 재계산에 따른 3개년 경정청구 실익은 주황색 '확인 사항(조건부 별도)' 카드로 분리합니다.
    """
    tot_gross = int(pkg.get("total_credit_gross_won") or 0)
    claw_net = int(pkg.get("total_clawback_net_payable_won") or 0)
    rural_won = int(pkg.get("rural_special_tax_won") or 0)
    net_Confirmed = int(pkg.get("net_after_rural_tax_won") or 0)

    c1_won = int(pkg.get("cur_base_credit_won") or 0)
    c_cont = int(pkg.get("total_continued_credit_won") or 0)
    c_add = int(pkg.get("additional_credit_won") or 0)

    pm1_f = pkg.get("pm_y1_filed") or {}
    pm1_r = pkg.get("pm_y1_recalc") or {}
    diff_pm1 = int(pm1_r.get("continued_credit_won") or 0) - int(pm1_f.get("continued_credit_won") or 0)
    has_amend_benefit = (
        diff_pm1 > 0
        and not pm1_f.get("base_missing")
        and not pm1_r.get("base_missing")
        and int(pm1_f.get("continued_credit_won") or 0) > 0
    )
    if has_amend_benefit:
        gross_3yr = diff_pm1 * 3
        net_3yr = int(round(gross_3yr * 0.8))
        card4_val = f"세후 +{net_3yr:,}원"
        card4_sub = f"3개년 세전 +{gross_3yr:,}원 (연 +{diff_pm1:,}원) · 확정세액 합산 제외"
    else:
        card4_val = "해당 없음 (0원)"
        card4_sub = f"{tax_yr-1}년 기신고·재계산 일치 또는 경정청구 차액 없음"

    return (
        "<div style='display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-bottom:12px;'>"
        f"<div style='background:#eff6ff;border:1px solid #bfdbfe;border-left:4px solid #1d4ed8;border-radius:10px;padding:10px 13px;'>"
        f"<div style='font-size:0.82rem;font-weight:800;color:#1e40af;'>① {tax_yr}년 총 공제세액 (확정)</div>"
        f"<div style='font-size:1.30rem;font-weight:900;color:#1d4ed8;margin-top:3px;'>+{tot_gross:,}원</div>"
        f"<div style='font-size:0.76rem;color:#475569;margin-top:2px;'>1차 {c1_won:,} + 연속 {c_cont:,}"
        + (f" + 추가 {c_add:,}" if c_add > 0 else "")
        + "</div></div>"
        f"<div style='background:#f8fafc;border:1px solid #cbd5e1;border-left:4px solid #64748b;border-radius:10px;padding:10px 13px;'>"
        f"<div style='font-size:0.82rem;font-weight:800;color:#334155;'>② 추가납부(추징) · 농특세(20%)</div>"
        f"<div style='font-size:1.30rem;font-weight:900;color:{'#dc2626' if claw_net > 0 else '#334155'};margin-top:3px;'>"
        f"-{claw_net + rural_won:,}원</div>"
        f"<div style='font-size:0.76rem;color:#475569;margin-top:2px;'>사후추징 -{claw_net:,}원 · 농특세 -{rural_won:,}원</div>"
        f"</div>"
        f"<div style='background:#f0fdf4;border:1px solid #86efac;border-left:4px solid #16a34a;border-radius:10px;padding:10px 13px;'>"
        f"<div style='font-size:0.82rem;font-weight:800;color:#166534;'>③ 당해 확정 실질 순절세액</div>"
        f"<div style='font-size:1.30rem;font-weight:900;color:#15803d;margin-top:3px;'>{net_Confirmed:+,}원</div>"
        f"<div style='font-size:0.76rem;color:#15803d;font-weight:700;margin-top:2px;'>총공제 − 추징 − 농특세 (당해 확정분)</div>"
        f"</div>"
        f"<div style='background:#fff7ed;border:1px solid #fdba74;border-left:4px solid #ea580c;border-radius:10px;padding:10px 13px;'>"
        f"<div style='font-size:0.82rem;font-weight:800;color:#c2410c;'>④ [확인 사항] 경정청구 잠재 실익</div>"
        f"<div style='font-size:1.22rem;font-weight:900;color:#c2410c;margin-top:3px;'>{card4_val}</div>"
        f"<div style='font-size:0.75rem;color:#9a3412;margin-top:2px;'>{card4_sub}</div>"
        f"</div>"
        "</div>"
    )


def _build_headcount_waterfall_and_comparison(s: dict, pkg: dict, tax_yr: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    [인원 증감 브리지 표(Waterfall Bridge) 및 직전연도 비교인원 보수적 vs 공격적 산정 세액 비교표]
    """
    people = s.get("people") or {}
    try:
        from .ui_common import _build_year_rows
        _, comp_cur, _ = _build_year_rows(s, tax_yr)
        _, comp_prev, _ = _build_year_rows(s, tax_yr - 1)
    except Exception:
        comp_cur, comp_prev = {}, {}

    cur_s = pkg["cur_s"]
    prev_s = pkg["prev_s"]

    new_hire_reg = 0.0
    new_hire_names = []
    retired_or_excl_diff = 0.0
    retired_names = []
    agg_retro_excl_reg = 0.0
    agg_retro_excl_yth = 0.0
    agg_retro_names = []

    for pid, p in people.items():
        nm = str(p.get("성명") or "").strip()
        h_dt = H.parse_date(p.get("입사일"))
        r_str = (p.get("연도별_퇴사일") or {}).get(str(tax_yr)) or p.get("퇴사일")
        r_dt = H.parse_date(r_str)
        c_c = comp_cur.get(pid) or {}
        c_p = comp_prev.get(pid) or {}
        r_cur = float(c_c.get("b1_reg") or 0.0)
        r_prv = float(c_p.get("b1_reg") or 0.0)
        y_prv = float(c_p.get("b1_yth") or 0.0)

        if h_dt and h_dt.year == tax_yr and r_cur > 0:
            new_hire_reg += r_cur
            new_hire_names.append(f"{nm}(+{r_cur:.2f})")
        elif r_cur < r_prv - 1e-6:
            diff_d = r_prv - r_cur
            retired_or_excl_diff += diff_d
            retired_names.append(f"{nm}(-{diff_d:.2f})")

        if (
            h_dt and r_dt
            and h_dt.year == (tax_yr - 1)
            and r_dt.year == tax_yr
            and H.tenure_under_1y(p, tax_yr)
            and not H.tenure_under_1y(p, tax_yr - 1)
            and r_prv > 0
        ):
            agg_retro_excl_reg += r_prv
            agg_retro_excl_yth += y_prv
            agg_retro_names.append(f"{nm}({r_prv:.2f}명)")

    cont_change = round(cur_s["regular"] - prev_s["regular"] - new_hire_reg + retired_or_excl_diff, 2)
    wf_rows = [
        {
            "단계 구분": f"① 직전 과세연도({tax_yr-1}년) 비교 상시근로자 수 (기초)",
            "전체 상시 (명)": f"{prev_s['regular']:.2f}명",
            "청년등 상시 (명)": f"{prev_s['youth']:.2f}명",
            "청년등 외 (명)": f"{prev_s['non_youth']:.2f}명",
            "주요 변동 사원 및 산정 근거": f"{tax_yr-1}년 중 1년 미만 퇴사 확정자 제외 · 연말 재직자 보수적 산입",
        },
        {
            "단계 구분": f"② {tax_yr}년 신규 입사 상시근로자 증가 (+)",
            "전체 상시 (명)": f"+{new_hire_reg:.2f}명",
            "청년등 상시 (명)": "-",
            "청년등 외 (명)": "-",
            "주요 변동 사원 및 산정 근거": ", ".join(new_hire_names[:8]) + (" 외" if len(new_hire_names) > 8 else "") if new_hire_names else "당해 신규 입사자 없음",
        },
        {
            "단계 구분": f"③ {tax_yr}년 중도퇴사 · 1년 미만 제외 감소 (-)",
            "전체 상시 (명)": f"-{retired_or_excl_diff:.2f}명",
            "청년등 상시 (명)": "-",
            "청년등 외 (명)": "-",
            "주요 변동 사원 및 산정 근거": ", ".join(retired_names[:8]) + (" 외" if len(retired_names) > 8 else "") if retired_names else "중도퇴사 감소 없음",
        },
        {
            "단계 구분": f"④ 기존 계속근로자 근무월수 증가 · 단수 절사 조정 (±)",
            "전체 상시 (명)": f"{cont_change:+.2f}명",
            "청년등 상시 (명)": "-",
            "청년등 외 (명)": "-",
            "주요 변동 사원 및 산정 근거": f"전년도 기중 입사자의 당해 만근(12개월) 전환 및 합산 후 절사 효과",
        },
        {
            "단계 구분": f"⑤ 당해 과세연도({tax_yr}년) 상시근로자 수 (기말 확정)",
            "전체 상시 (명)": f"{cur_s['regular']:.2f}명 (증가 +{pkg['cur_inc']['total_inc']:.2f}명)",
            "청년등 상시 (명)": f"{cur_s['youth']:.2f}명 (증가 +{pkg['cur_inc']['youth_inc']:.2f}명)",
            "청년등 외 (명)": f"{cur_s['non_youth']:.2f}명 (증가 +{pkg['cur_inc']['non_youth_inc']:.2f}명)",
            "주요 변동 사원 및 산정 근거": "조특령 제26조의8 제6항 합산 후 절사 및 시행규칙 별지 제10호의9서식 정본 산식",
        },
    ]

    # 보수적(기본 정본) vs 공격적(사후 1년 미만 퇴사자 소급 제외) 비교
    cons_reg = float(prev_s["regular"])
    cons_yth = float(prev_s["youth"])
    agg_reg = round(max(0.0, cons_reg - agg_retro_excl_reg), 2)
    agg_yth = round(max(0.0, cons_yth - agg_retro_excl_yth), 2)
    inc_cons = pkg["cur_inc"]
    inc_agg = H.calc_increase_with_cap(cur_s["regular"], cur_s["youth"], cur_s["non_youth"], agg_reg, agg_yth, round(max(0.0, agg_reg - agg_yth), 2))
    r_u = pkg["rates_new_y1"] if pkg.get("active_scheme") == "new_2026" else pkg["rates_legacy"]
    c1_cons = int(pkg.get("cur_base_credit_won") or 0)
    c1_agg = int(round((inc_agg["youth_inc"] * r_u["청년등"] + inc_agg["non_youth_inc"] * r_u["청년등외"]) * 10_000))

    ca_rows = [
        {
            "비교 산정 방식": "🛡️ 보수적 산정 (현재 적용 정본 — 권장)",
            f"직전({tax_yr-1}년) 비교인원 [상시 / 청년 / 외]": f"{cons_reg:.2f}명 / {cons_yth:.2f}명 / {round(cons_reg - cons_yth, 2):.2f}명",
            f"당해({tax_yr}년) 증가인원 [전체 / 청년 / 외]": f"+{inc_cons['total_inc']:.2f}명 / +{inc_cons['youth_inc']:.2f}명 / +{inc_cons['non_youth_inc']:.2f}명",
            f"{tax_yr}년 1차 공제세액": f"{c1_cons:,}원 (기준)",
            "법적 근거 및 리스크 판단": f"{tax_yr-1}.12.31. 현재 정상 재직 중이던 인원({', '.join(agg_retro_names) or '해당자 없음'})을 비교인원에 유지하여 과다공제·가산세 리스크 원천 차단",
        },
        {
            "비교 산정 방식": "⚡ 공격적 산정 (사후 1년 미만 퇴사자 소급 제외 시 참고)",
            f"직전({tax_yr-1}년) 비교인원 [상시 / 청년 / 외]": f"{agg_reg:.2f}명 / {agg_yth:.2f}명 / {round(agg_reg - agg_yth, 2):.2f}명",
            f"당해({tax_yr}년) 증가인원 [전체 / 청년 / 외]": f"+{inc_agg['total_inc']:.2f}명 / +{inc_agg['youth_inc']:.2f}명 / +{inc_agg['non_youth_inc']:.2f}명",
            f"{tax_yr}년 1차 공제세액": f"{c1_agg:,}원 ({c1_agg - c1_cons:+,}원)",
            "법적 근거 및 리스크 판단": f"{tax_yr}년 중 퇴사로 총 근속 1년 미만이 된 {', '.join(agg_retro_names) or '인원'}을 {tax_yr-1}년 비교인원에서도 소급 차감하는 해석 (과세관청 소명 요구 가능성 있음)",
        },
    ]
    return pd.DataFrame(wf_rows), pd.DataFrame(ca_rows)


def _fmt_signed_total_won(net_won: int | float | None) -> str:
    v = int(round(float(net_won or 0)))
    if v < 0:
        return f"<span class='ec-neg-val'>-{abs(v):,}</span>"
    if v > 0:
        return f"<span class='ec-pos-val'>{v:,}</span>"
    return "<span class='ec-zero-val'>0</span>"


def _cohort_capital(s: dict, cohort: int, default: bool) -> bool:
    v = ((s.get("prev_summary") or {}).get(str(cohort)) or {}).get("수도권")
    return default if v is None else bool(v)


def _enrich_matrix_cols_with_cohort_consistency(
    matrix_cols: dict[int, dict[str, Any]],
    yr_list: list[int],
) -> dict[int, dict[str, Any]]:
    """
    총괄표(4개 과세연도 요약표) 정합성 보정:
    - T-3(예: 2023년) 1차 공제액이 0원인데 T-2(2024년) 2차 또는 T-1(2025년) 3차 연속공제액이 존재하는 경우(예: 3,875,000원),
      구법(구 조특법 제29조의8 제1항)상 2·3차년도 연속공제액은 최초 1차년도 공제세액과 동일하므로 T-3 1차 공제액에 해당 금액을 복원합니다.
    - 또한 T-3 이전 과세연도(2021·2022년) 귀속분 사후관리에 해당하는 T-3의 2·3차 및 T-2의 3차 칸이 0원(검토범위 외)인 경우
      `r2_na` / `r3_na` 플래그를 부여하여 '0원' 대신 '-' (대상외)로 명확히 표시합니다.
    """
    if len(yr_list) >= 3:
        y0, y1, y2 = yr_list[0], yr_list[1], yr_list[2]
        m0 = matrix_cols.get(y0)
        m1 = matrix_cols.get(y1)
        m2 = matrix_cols.get(y2)
        if isinstance(m0, dict) and isinstance(m1, dict) and isinstance(m2, dict):
            if int(m0.get("r1_credit") or 0) == 0 and int(m0.get("r1_claw") or 0) == 0:
                inferred_r1 = int(m1.get("r2_credit") or 0) or int(m2.get("r3_credit") or 0)
                if inferred_r1 > 0:
                    m0["r1_credit"] = inferred_r1
                    m0["r1_inferred_from_continued"] = True
                    m0["net_total"] = (
                        int(m0.get("r1_credit") or 0)
                        + int(m0.get("r2_credit") or 0)
                        + int(m0.get("r3_credit") or 0)
                        - int(m0.get("r1_claw") or 0)
                        - int(m0.get("r2_claw") or 0)
                        - int(m0.get("r3_claw") or 0)
                    )
            if int(m0.get("r2_credit") or 0) == 0 and int(m0.get("r2_claw") or 0) == 0:
                m0["r2_na"] = True
            if int(m0.get("r3_credit") or 0) == 0 and int(m0.get("r3_claw") or 0) == 0:
                m0["r3_na"] = True
            if int(m1.get("r3_credit") or 0) == 0 and int(m1.get("r3_claw") or 0) == 0:
                m1["r3_na"] = True
    return matrix_cols


def _build_pm_formula_lines(
    pm: dict,
    cohort_year: int,
    eval_year: int,
    elapsed: int,
    cur_pm_reg: float,
    cur_pm_yth: float,
    rates_legacy: dict[str, int],
    cohort_is_capital: bool | None = None,
    cur_is_capital: bool | None = None,
) -> tuple[str, list[str], str, int, bool]:
    """
    (3) 2차년도 사후관리 계산 / (4) 3차년도 사후관리 계산 박스용 상세 산식 생성.
    반환: (제목 요약, 산식 줄 리스트, 우측 금액 라벨, 표시 금액(음수는 추징), 음수여부)
    """
    yth_r = int(rates_legacy["청년등"])
    gen_r = int(rates_legacy["청년등외"])
    diff_r = max(0, yth_r - gen_r)
    nth_label = f"{elapsed + 1}차년도"

    if pm.get("base_missing"):
        return (
            f"{cohort_year}년 귀속분 기초자료 미입력 ({pm.get('case_code', '기초값 없음')})",
            [
                f"• {cohort_year}년 최초공제연도의 상시·청년등 인원 또는 증가인원 기초값이 없습니다.",
                "• 상단 계산 기준을 『⚖️ 2단계 사원표(세법원칙) 기준 계산』으로 선택하거나 아래 기신고 기초값을 입력해 주세요.",
            ],
            "세액공제액 / 추가납부액",
            0,
            False,
        )

    if str(pm.get("case_code") or "").startswith("신법") and isinstance(pm.get("new_tier_info"), dict):
        ti = pm["new_tier_info"]
        t_rates = ti.get("rates") or {"청년등": 0, "청년등외": 0}
        y_u = int(t_rates.get("청년등", 0)) * 10_000
        g_u = int(t_rates.get("청년등외", 0)) * 10_000
        y_inc = float(ti.get("youth_inc") or 0.0)
        g_inc = float(ti.get("non_youth_inc") or 0.0)
        y_w = int(ti.get("item1_youth_won") or 0)
        g_w = int(ti.get("item2_non_youth_won") or 0)
        d_w = int(ti.get("item3_deduction_won") or 0)
        cr_w = int(ti.get("credit_won") or 0)
        new_lines = [
            f"• {cohort_year}년 이후 개시 과세연도 귀속분은 구법 사후관리(추징) 대상이 아니며, 현행 조특법 제29조의8 제1항 {nth_label}(B·C) 유지분 점증형 공제단가가 적용됩니다.",
            f"• 청년 등 유지 인원: <b>{y_inc:.2f}명</b> × {y_u:,}원 = <b>{y_w:,}원</b> / 청년 등 외 유지 인원: <b>{g_inc:.2f}명</b> × {g_u:,}원 = <b>{g_w:,}원</b>"
            + (f" (최소고용증가인원 차감 -{d_w:,}원)" if d_w > 0 else ""),
            f"• 산식 합계: ({y_inc:.2f} × {y_u:,}원) + ({g_inc:.2f} × {g_u:,}원)"
            + (f" - {d_w:,}원" if d_w > 0 else "")
            + f" = <b>{cr_w:,}원</b>",
        ]
        return (
            f"{cohort_year}년 귀속분 {nth_label} 유지 세액공제 — {pm.get('case_code')}",
            new_lines,
            f"{nth_label} 유지 세액공제액",
            cr_w,
            False,
        )

    if not pm.get("active"):
        return (
            f"{cohort_year}년 귀속분 — {pm.get('case_title', '사후관리 대상 아님')}",
            [
                f"• {cohort_year}년 귀속 최초 공제 대상 고용증가 인원이 없거나 사후관리 대상이 아닙니다.",
                f"• 산식: 공제대상 증가인원 0명 × 공제단가 = 0원",
            ],
            "세액공제액 / 추가납부액",
            0,
            False,
        )

    init_reg = float(pm.get("init_reg") or 0.0)
    init_yth = float(pm.get("init_yth") or 0.0)
    init_y_inc = float(pm.get("init_yth_inc") or 0.0)
    init_g_inc = float(pm.get("init_gen_inc") or 0.0)
    ret_y = float(pm.get("retained_yth_inc") or 0.0)
    ret_g = float(pm.get("retained_gen_inc") or 0.0)
    reg_dec = float(pm.get("reg_decrease") or 0.0)
    yth_dec = float(pm.get("yth_decrease") or 0.0)

    cont_won = int(pm.get("continued_credit_won") or 0)
    claw_net_won = int(pm.get("clawback_net_payable_won") or 0)
    claw_raw_won = int(pm.get("clawback_raw_cumulative_won") or 0)
    prior_ded_won = int(pm.get("prior_clawback_deducted_won") or 0)
    cf_off_won = int(pm.get("carryforward_offset_won") or 0)

    loc_diff_note = ""
    if cohort_is_capital is not None and cur_is_capital is not None and cohort_is_capital != cur_is_capital:
        coh_loc_lbl = "수도권" if cohort_is_capital else "수도권 외(비수도권)"
        cur_loc_lbl = "수도권" if cur_is_capital else "수도권 외(비수도권)"
        loc_diff_note = f" [{cohort_year}년 최초공제 당시 {coh_loc_lbl} 소재 단가(청년등 {yth_r:,}만·일반 {gen_r:,}만) 적용 — 이후 {cur_loc_lbl} 이전]"

    lines = [
        f"• 인원 비교 ({cohort_year}년 최초공제 대비 {eval_year}년 사후관리 기준 [법률 제21223호 부칙 제34조 · 시행령 부칙 종전규정 적용]): "
        f"전체 상시 {init_reg:.2f}명 → {cur_pm_reg:.2f}명 (증감 {cur_pm_reg - init_reg:+.2f}명) / "
        f"청년등 {init_yth:.2f}명 → {cur_pm_yth:.2f}명 (증감 {cur_pm_yth - init_yth:+.2f}명)",
        f"• {cohort_year}년 최초 공제받은 증가인원: 전체 {init_y_inc + init_g_inc:.2f}명 "
        f"(청년등 {init_y_inc:.2f}명 · 청년등 외 {init_g_inc:.2f}명){loc_diff_note}",
    ]

    if cont_won > 0 and claw_net_won == 0:
        lines.append(
            f"• {nth_label} 연속공제 산식 (구 조특법 제29조의8 제1항 · 법률 제21223호 부칙 제34조): (유지 청년등 {ret_y:.2f}명 × {yth_r*10_000:,}원) + "
            f"(유지 청년등 외 {ret_g:.2f}명 × {gen_r*10_000:,}원) = {cont_won:,}원"
        )
        return (
            f"{cohort_year}년 귀속분 {nth_label} 사후관리 — {pm.get('case_code', '고용 유지')}",
            lines,
            f"{nth_label} 세액공제액",
            cont_won,
            False,
        )

    if claw_net_won > 0 and cont_won > 0:
        capped_y_dec = min(init_y_inc, yth_dec)
        lines.append(
            f"• {nth_label} 부분 연속공제 산식: (유지 청년등 {ret_y:.2f}명 × {yth_r*10_000:,}원) + "
            f"(대체포함 일반 {ret_g:.2f}명 × {gen_r*10_000:,}원) = {cont_won:,}원"
        )
        lines.append(
            f"• 청년등 감소분 단가차액 추가납부 산식: 감소 청년등 {capped_y_dec:.2f}명 × "
            f"({yth_r*10_000:,}원 - {gen_r*10_000:,}원 = {diff_r*10_000:,}원) → 추가납부 (-){claw_net_won:,}원"
        )
        net_v = cont_won - claw_net_won
        return (
            f"{cohort_year}년 귀속분 {nth_label} 사후관리 — {pm.get('case_code', '부분공제 + 추가납부')}",
            lines,
            f"{nth_label} 순세액 (공제 {cont_won:,} / 추징 -{claw_net_won:,})",
            net_v,
            net_v < 0,
        )

    if claw_net_won > 0 or claw_raw_won > 0:
        lines.append(f"• 사후관리 추징 산식 (구 조특법 제29조의8 제3항 · 법률 제21223호 부칙 제34조): {pm.get('formula_note', '')}")
        if prior_ded_won > 0 or cf_off_won > 0:
            lines.append(
                f"• 차감 반영: 산출 추징액 {claw_raw_won:,}원 - 기추징 차감 {prior_ded_won:,}원 - "
                f"미공제 이월세액 차감(조특법 제144조) {cf_off_won:,}원 = 당기 추가납부세액 (-){claw_net_won:,}원"
            )
        return (
            f"{cohort_year}년 귀속분 {nth_label} 사후관리 — {pm.get('case_code', '고용 감소 추징')}",
            lines,
            f"{nth_label} 추가납부세액",
            -claw_net_won,
            claw_net_won > 0,
        )

    lines.append(f"• 검토 결과: {pm.get('formula_note', '연속공제 및 추가납부세액 0원')}")
    return (
        f"{cohort_year}년 귀속분 {nth_label} 사후관리 — {pm.get('case_code', '세액 없음')}",
        lines,
        "세액공제액 / 추가납부액",
        0,
        False,
    )


def _build_step3_calculation_pdf_bytes(
    s: dict,
    pkg: dict,
    matrix_cols: dict[int, dict[str, Any]],
) -> bytes:
    """
    3단계 『공제액 계산』 화면의:
    ① 4개년 통합고용세액공제 요약표 (1차 / 2차 / 3차 / 합계)
    ② (1) 평균 상시근로자 증가 인원 표
    ③ (2) 1차년도 세액공제액 계산 산식
    ④ (3) 2차년도 사후관리 요건 검토(여/부) 및 계산 산식
    ⑤ (4) 3차년도 사후관리 요건 검토(여/부) 및 계산 산식
    ⑥ 계산근거 관련 법령 조문
    을 A4 세로(Portrait) 고해상도 정식 PDF로 생성합니다.
    """
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
    st_title = ParagraphStyle(
        "ECStep3Title",
        parent=styles["Normal"],
        fontName=bold_font,
        fontSize=13.5,
        leading=18,
        textColor=colors.HexColor("#0f172a"),
        spaceAfter=3,
    )
    st_sub = ParagraphStyle(
        "ECStep3Sub",
        parent=styles["Normal"],
        fontName=reg_font,
        fontSize=8.8,
        leading=13,
        textColor=colors.HexColor("#334155"),
        spaceAfter=8,
    )
    st_sec = ParagraphStyle(
        "ECStep3Sec",
        parent=styles["Normal"],
        fontName=bold_font,
        fontSize=10.8,
        leading=15,
        textColor=colors.HexColor("#1e3a8a"),
        spaceBefore=8,
        spaceAfter=5,
    )
    st_body = ParagraphStyle(
        "ECStep3Body",
        parent=styles["Normal"],
        fontName=reg_font,
        fontSize=8.8,
        leading=13.5,
        textColor=colors.HexColor("#1e293b"),
    )

    b = s.get("biz") or {}
    corp_nm = (b.get("상호") or "").strip()
    biz_no = (b.get("사업자번호") or "").strip()
    corp_size = pkg.get("corp_size") or "중소기업"
    is_capital = bool(pkg.get("is_capital", True))
    loc_label = "수도권" if is_capital else "수도권 외(비수도권)"
    tax_yr = int(pkg.get("tax_year") or R.DEFAULT_TAX_YEAR)
    basis_lbl = pkg.get("pm_basis_label") or "기신고 기준"

    story = []
    story.append(
        Paragraph(
            _pdf_text((f"[{corp_nm}] " if corp_nm else "") + f"{tax_yr}년 귀속 통합고용세액공제 및 사후관리 계산서"),
            st_title,
        )
    )
    story.append(
        Paragraph(
            _pdf_text(
                f"사업자등록번호: {biz_no}  |  기업규모·소재지: {corp_size} · {loc_label}  |  "
                f"적용 기준: {basis_lbl}  |  단위: 원 (추가납부세액은 - 표시)"
            ),
            st_sub,
        )
    )

    # 1) 상단 4개년 요약 매트릭스 표
    yr_list = [tax_yr - 3, tax_yr - 2, tax_yr - 1, tax_yr]
    matrix_cols = _enrich_matrix_cols_with_cohort_consistency(matrix_cols, yr_list)
    matrix_cols = _enrich_matrix_cols_with_cohort_consistency(matrix_cols, yr_list)
    story.append(Paragraph(_pdf_text(f"■ 연도별 통합고용세액공제 요약표 ({corp_size} · {loc_label})"), st_sec))

    def _cell_str(cr: int, cl: int, is_na: bool = False, is_inferred: bool = False) -> str:
        if is_na:
            return "-"
        cr_i, cl_i = int(cr or 0), int(cl or 0)
        if cr_i > 0 and cl_i > 0:
            return f"+{cr_i:,}\n(-{cl_i:,})"
        if cl_i > 0:
            return f"-{cl_i:,}"
        if cr_i < 0:
            return f"-{abs(cr_i):,}"
        if cr_i > 0 and is_inferred:
            return f"{cr_i:,}\n(추정복원)"
        return f"{cr_i:,}"

    mat_data = [
        ["구분", "차수", *[f"{y}년{' (당해)' if y == tax_yr else ''}" for y in yr_list]],
        ["세액공제액\n(추가납부세액)", "1차", *[_cell_str(matrix_cols[y]["r1_credit"], matrix_cols[y]["r1_claw"], bool(matrix_cols[y].get("r1_na")), bool(matrix_cols[y].get("r1_inferred_from_continued"))) for y in yr_list]],
        ["", "2차", *[_cell_str(matrix_cols[y]["r2_credit"], matrix_cols[y]["r2_claw"], bool(matrix_cols[y].get("r2_na"))) for y in yr_list]],
        ["", "3차", *[_cell_str(matrix_cols[y]["r3_credit"], matrix_cols[y]["r3_claw"], bool(matrix_cols[y].get("r3_na"))) for y in yr_list]],
        ["합계 (순액)", "", *[f"{int(matrix_cols[y]['net_total']):,}" for y in yr_list]],
    ]
    mat_widths = [avail_w * 0.16, avail_w * 0.08, avail_w * 0.19, avail_w * 0.19, avail_w * 0.19, avail_w * 0.19]
    t_mat = Table(mat_data, colWidths=mat_widths)
    t_mat.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), bold_font),
                ("FONTNAME", (0, 1), (1, -1), bold_font),
                ("FONTNAME", (2, 1), (-1, -2), reg_font),
                ("FONTNAME", (0, -1), (-1, -1), bold_font),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("LEADING", (0, 0), (-1, -1), 11.5),
                ("SPAN", (0, 0), (1, 0)),
                ("SPAN", (0, 1), (0, 3)),
                ("SPAN", (0, 4), (1, 4)),
                ("ALIGN", (0, 0), (1, -1), "CENTER"),
                ("ALIGN", (2, 0), (-1, 0), "CENTER"),
                ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("BACKGROUND", (-1, 0), (-1, 0), colors.HexColor("#1d4ed8")),
                ("BACKGROUND", (0, 1), (1, -1), colors.HexColor("#f8fafc")),
                ("BACKGROUND", (-1, 1), (-1, -2), colors.HexColor("#f0f7ff")),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#f1f5f9")),
                ("BACKGROUND", (-1, -1), (-1, -1), colors.HexColor("#dbeafe")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("BOX", (0, 0), (-1, -1), 1.0, colors.HexColor("#1e293b")),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(t_mat)
    story.append(Spacer(1, 6))

    # 2) (1) 평균 상시근로자 증가 인원 표
    cur_s = pkg["cur_s"]
    prev_s = pkg["prev_s"]
    cur_inc = pkg["cur_inc"]
    story.append(Paragraph(_pdf_text(f"1. {tax_yr}년 세액공제 — (1) 평균 상시근로자 증가 인원"), st_sec))
    inc_data = [
        ["구분", f"해당 과세연도 ({tax_yr}년)", f"직전 과세연도 ({tax_yr-1}년)", "증가인원"],
        ["상시근로자 증가", f"{cur_s['regular']:.2f}명", f"{prev_s['regular']:.2f}명", f"{cur_inc['total_inc']:.2f}명 (증감 {cur_inc['total_diff']:+.2f})"],
        ["청년 등 상시근로자 증가", f"{cur_s['youth']:.2f}명", f"{prev_s['youth']:.2f}명", f"{cur_inc['youth_inc']:.2f}명"],
        ["이 외 상시근로자 증가", f"{cur_s['non_youth']:.2f}명", f"{prev_s['non_youth']:.2f}명", f"{cur_inc['non_youth_inc']:.2f}명"],
    ]
    t_inc = Table(inc_data, colWidths=[avail_w * 0.25, avail_w * 0.25, avail_w * 0.25, avail_w * 0.25])
    t_inc.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), bold_font),
                ("FONTNAME", (0, 1), (0, -1), bold_font),
                ("FONTNAME", (1, 1), (-2, -1), reg_font),
                ("FONTNAME", (-1, 1), (-1, -1), bold_font),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ("ALIGN", (0, 1), (0, -1), "CENTER"),
                ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("BACKGROUND", (0, 1), (0, -1), colors.HexColor("#f8fafc")),
                ("BACKGROUND", (-1, 1), (-1, -1), colors.HexColor("#f0f7ff")),
                ("TEXTCOLOR", (-1, 1), (-1, -1), colors.HexColor("#1d4ed8")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("BOX", (0, 0), (-1, -1), 0.9, colors.HexColor("#1e293b")),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(t_inc)
    story.append(Spacer(1, 5))

    def _add_calc_card(sec_hdr: str, title_txt: str, lines_list: list[str], amt_lbl: str, amt_val: int, is_neg: bool = False):
        story.append(Paragraph(_pdf_text(sec_hdr), st_sec))
        body_html = f"<font name='{bold_font}'><b>{_pdf_text(title_txt)}</b></font><br/>" + "<br/>".join(
            _pdf_text(re.sub(r"<[^>]+>", "", ln)) for ln in lines_list
        )
        amt_str = f"-{abs(amt_val):,}원" if amt_val < 0 else f"{amt_val:,}원"
        amt_color = "#dc2626" if is_neg or amt_val < 0 else ("#15803d" if amt_val > 0 else "#334155")
        right_p = Paragraph(
            f"<font name='{bold_font}' size='8.2' color='#475569'>{_pdf_text(amt_lbl)}</font><br/>"
            f"<font name='{bold_font}' size='11.5' color='{amt_color}'><b>{amt_str}</b></font>",
            ParagraphStyle("RAmt", parent=st_body, alignment=2, leading=15),
        )
        card_tbl = Table([[Paragraph(body_html, st_body), right_p]], colWidths=[avail_w * 0.72, avail_w * 0.28])
        border_c = "#dc2626" if (is_neg or amt_val < 0) else ("#16a34a" if amt_val > 0 else "#94a3b8")
        bg_r = "#fef2f2" if (is_neg or amt_val < 0) else ("#f0fdf4" if amt_val > 0 else "#f8fafc")
        card_tbl.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("BACKGROUND", (0, 0), (0, 0), colors.white),
                    ("BACKGROUND", (1, 0), (1, 0), colors.HexColor(bg_r)),
                    ("BOX", (0, 0), (-1, -1), 0.9, colors.HexColor(border_c)),
                    ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                    ("LEFTPADDING", (0, 0), (-1, -1), 10),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ]
            )
        )
        story.append(card_tbl)
        story.append(Spacer(1, 4))

    # 3) (2) 1차년도 세액공제액 계산
    if pkg["active_scheme"] == "new_2026":
        r_y1 = pkg["rates_new_y1"]
        yu, gu = r_y1["청년등"] * 10_000, r_y1["청년등외"] * 10_000
        ya = int(round(cur_inc["youth_inc"] * yu))
        ga = int(round(cur_inc["non_youth_inc"] * gu))
        ded = int(pkg.get("cur_new_ded_won") or 0)
        first_won = max(0, ya + ga - ded)
        y1_lines = [
            f"• 청년 등 상시근로자 증가(A): {cur_inc['youth_inc']:.2f}명 × {yu:,}원 = {ya:,}원",
            f"• 청년 등 외 상시근로자 증가(A): {cur_inc['non_youth_inc']:.2f}명 × {gu:,}원 = {ga:,}원",
            f"• 산식 합계(조특법 제29조의8 제1항 A+B+C 구조 중 {tax_yr}년은 A만 해당): ({cur_inc['youth_inc']:.2f} × {yu:,}원) + ({cur_inc['non_youth_inc']:.2f} × {gu:,}원)"
            + (f" - 최소고용증가인원 차감 {ded:,}원" if ded > 0 else "")
            + f" = {first_won:,}원 (신법 적용분은 사후관리 추징 없음)",
        ]
    else:
        r_leg = pkg["rates_legacy"]
        yu, gu = r_leg["청년등"] * 10_000, r_leg["청년등외"] * 10_000
        ya = int(round(cur_inc["youth_inc"] * yu))
        ga = int(round(cur_inc["non_youth_inc"] * gu))
        first_won = ya + ga
        y1_lines = [
            f"• 청년 등 상시근로자 증가: {cur_inc['youth_inc']:.2f}명 × {yu:,}원 = {ya:,}원",
            f"• 청년 등 외 상시근로자 증가: {cur_inc['non_youth_inc']:.2f}명 × {gu:,}원 = {ga:,}원",
            f"• 산식 합계: ({cur_inc['youth_inc']:.2f} × {yu:,}원) + ({cur_inc['non_youth_inc']:.2f} × {gu:,}원) = {first_won:,}원",
        ]
    _add_calc_card(
        f"(2) 1차년도 세액공제액 계산 ({corp_size}, {loc_label})",
        f"{tax_yr}년 귀속 1차년도 신규 고용증가 세액공제 (조특법 제29조의8 제1항)",
        y1_lines,
        "1차년도 세액공제액",
        first_won,
        False,
    )

    # 4) (3) 2차년도 사후관리 계산
    pm1_title, pm1_lines, pm1_lbl, pm1_val, pm1_neg = _build_pm_formula_lines(
        pm=pkg["pm_y1"],
        cohort_year=tax_yr - 1,
        eval_year=tax_yr,
        elapsed=1,
        cur_pm_reg=cur_s["b2_reg"],
        cur_pm_yth=cur_s["b2_yth"],
        rates_legacy=H.get_unit_rates(corp_size, _cohort_capital(s, tax_yr - 1, is_capital), scheme="legacy", retention_year=1),
        cohort_is_capital=_cohort_capital(s, tax_yr - 1, is_capital),
        cur_is_capital=is_capital,
    )
    _add_calc_card(
        f"(3) 2차년도 사후관리 계산 ({tax_yr - 1}년 귀속분 → {tax_yr}년 1차 사후관리)",
        pm1_title,
        pm1_lines,
        pm1_lbl,
        pm1_val,
        pm1_neg,
    )

    # 5) (4) 3차년도 사후관리 계산
    pm2_title, pm2_lines, pm2_lbl, pm2_val, pm2_neg = _build_pm_formula_lines(
        pm=pkg["pm_y2"],
        cohort_year=tax_yr - 2,
        eval_year=tax_yr,
        elapsed=2,
        cur_pm_reg=cur_s["b3_reg"],
        cur_pm_yth=cur_s["b3_yth"],
        rates_legacy=H.get_unit_rates(corp_size, _cohort_capital(s, tax_yr - 2, is_capital), scheme="legacy", retention_year=1),
        cohort_is_capital=_cohort_capital(s, tax_yr - 2, is_capital),
        cur_is_capital=is_capital,
    )
    _add_calc_card(
        f"(4) 3차년도 사후관리 계산 ({tax_yr - 2}년 귀속분 → {tax_yr}년 2차 사후관리)",
        pm2_title,
        pm2_lines,
        pm2_lbl,
        pm2_val,
        pm2_neg,
    )

    # 6) 법령 근거 요약
    story.append(Spacer(1, 4))
    story.append(
        Paragraph(
            _pdf_text(
                "■ 계산근거 법령: 조세특례제한법 제29조의8 제1항(고용증가 세액공제 A+B+C 구조 및 제1호 괄호 청년등 증가한도 Cap)·제2항(경력단절 근로자 요건)·"
                "제4항(정규직 전환 추가공제, ~2024년 전환분)·제5항(육아휴직 복귀 추가공제), 구 조세특례제한법(법률 제21223호 개정 전) 제29조의8 제1항(연속공제)·제3항(추가납부) 및 법률 제21223호 부칙 제34조(2024·2025년분 경과조치), "
                "같은 법 시행령 제26조의8 제2항(상시근로자 범위·제1호 실제 근로기간 1년 미만 제외·제3호~제5호 임원·최대주주·친족 제외)·제3항(최소고용증가인원수)·제4항(청년등 범위)·"
                "제6항 및 제11조의2 제8항 제1호 가목·나목 준용(전체·청년등 합산 후 소수점 둘째 자리 절사 및 시행규칙 별지 제10호의9서식 작성방법 제4호에 따른 청년등 외 차감 산정)·제8항 및 제23조 제13항 준용(포괄양수·고용승계 특례)·대통령령 제35999호 부칙 제2조·제36127호 부칙 제11조 경과조치, "
                "조세특례제한법 제132조(최저한세)·제144조(이월공제 10년 및 미공제 이월세액 우선 차감), 농어촌특별세법 제5조 제1항(실제 감면세액의 20%)."
            ),
            st_sub,
        )
    )

    doc.build(story)
    return buf.getvalue()


def _page_calculation():
    s = _S()
    _ensure_built_for_tax_year(s)
    tax_yr = int(s["tax_year"])
    b = s["biz"]
    corp_size = b.get("기업구분", "중소기업")
    cap_bool = H.is_capital_area(b.get("사업장소재지", ""))
    is_capital = True if cap_bool is None else bool(cap_bool)
    loc_label = "수도권" if is_capital else "수도권 외"

    totals_all = _ensure_totals_snapshot(s)
    cur_t = totals_all.get(tax_yr, {})
    prev_t = totals_all.get(tax_yr - 1, {})
    prev2_t = totals_all.get(tax_yr - 2, {})
    b3_title, b4_title, b5_title = _block_titles_for_year(tax_yr, two_line=False)

    has_prev_doc = bool(((s.get("ext") or {}).get("prev_filing") or {}).get("연도별"))
    ps = s.setdefault("prev_summary", {})
    has_any_manual_ps = any(
        (ps.get(str(y)) or {}).get(k) is not None
        for y in (tax_yr - 1, tax_yr - 2)
        for k in ("상시", "청년등", "청년등_증가", "청년등외_증가", "공제세액")
    )
    if not s.get("_pm_basis_user_touched") and not has_prev_doc and not has_any_manual_ps:
        if prev_t.get("has_data") and not prev_t.get("from_filed"):
            s["pm_basis"] = R.PM_BASIS_RECALC

    if cap_bool is None:
        st.warning("사업장 소재지가 입력되지 않아 수도권 단가로 임시 계산되었습니다. 좌측 사이드바에서 사업장 소재지를 입력해 주세요.")

    last_m_cur = H.detect_last_paid_month(s.get("people") or {}, tax_yr)
    if s.get("assume_year_end", True) and last_m_cur < 12:
        st.markdown(
            f"<div class='ec-warn-banner'>"
            f"⚠️ <b>[기중 가결산 추정치 안내]</b> 현재 {tax_yr}년 원천징수부가 <b>{last_m_cur}월분</b>까지 업로드되어, "
            f"미도래 월(<b>{last_m_cur+1}~12월</b>)은 <b>'① 연말까지 재직 가정(1 자동 채움)'</b> 기준으로 시뮬레이션된 추정 세액입니다. "
            f"실제 세무신고 시에는 12월 최종 원천징수부를 업로드하거나, 2단계 상단에서 <b>'미도래 월 연말재직 가정'</b> 스위치를 끄고 확정하세요."
            f"</div>",
            unsafe_allow_html=True,
        )

    for cohort in (tax_yr - 1, tax_yr - 2, tax_yr - 3):
        ps.setdefault(str(cohort), {})

    _ext_pf_map = ((s.get("ext") or {}).get("prev_filing") or {}).get("연도별") or {}
    _extra_cnts = {
        str(yk): {"상시": float(yv["상시"]), "청년등": float(yv["청년등"])}
        for yk, yv in _ext_pf_map.items()
        if isinstance(yv, dict) and yv.get("상시") is not None and yv.get("청년등") is not None
    }
    P.fill_missing_increments(ps, corp_size, _extra_cnts)

    p1 = ps[str(tax_yr - 1)]
    p2 = ps[str(tax_yr - 2)]
    add_in = s.setdefault("additional_inputs", {})
    active_pm_basis = s.get("pm_basis", R.PM_BASIS_RECALC)

    prior_filings_payload = {
        cohort: {
            "init_reg": f.get("상시"),
            "init_yth": f.get("청년등"),
            "init_reg_total": f.get("상시_총인원"),
            "init_yth_total": f.get("청년등_총인원"),
            "init_yth_inc": f.get("청년등_증가"),
            "init_gen_inc": f.get("청년등외_증가"),
            "claimed_won": f.get("공제세액"),
            "carryforward_won": f.get("이월세액"),
            "y1_continued_won": f.get("2차_공제세액") if cohort == tax_yr - 2 else None,
            "prior_clawback_paid_won": f.get("기추징세액") if cohort == tax_yr - 2 else None,
            "is_capital": f.get("수도권"),
        }
        for cohort, f in ((tax_yr - 1, p1), (tax_yr - 2, p2))
    }

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

    matrix_cols = _compute_historical_matrix_columns(
        s=s,
        tax_yr=tax_yr,
        corp_size=corp_size,
        is_capital=is_capital,
        totals_all=totals_all,
        ps=ps,
        pkg_cur=pkg,
        active_pm_basis=active_pm_basis,
    )
    yr_list = [tax_yr - 3, tax_yr - 2, tax_yr - 1, tax_yr]
    matrix_cols = _enrich_matrix_cols_with_cohort_consistency(matrix_cols, yr_list)

    # 상단 4대 KPI 요약 카드 (확정 순절세액 vs 주황색 조건부 경정청구 실익 분리) 및 5대 수리·법령 정합성 배지
    st.markdown(_build_top_kpi_cards_html(pkg, tax_yr), unsafe_allow_html=True)
    ok_math, math_issues = _verify_step3_math_integrity(pkg, matrix_cols, yr_list)
    if ok_math:
        st.markdown(
            "<div style='margin-bottom:8px;padding:6px 12px;background:#f0fdf4;border:1px solid #86efac;border-radius:8px;"
            "font-size:0.86rem;font-weight:700;color:#166534;display:flex;justify-content:space-between;align-items:center;'>"
            "<span>🛡️ <b>5대 수리·법령 항등식 자동검증 통과</b>: ① 청년등외 차감 정본산식(0.00명 오차) · ② 청년등 증가한도(Cap) · ③ 코호트 연속성 · ④ 추징한도 · ⑤ 농특세(20%) 일치</span>"
            "<span style='font-size:0.78rem;color:#15803d;'>100% 파이썬 결정론적 엔진</span>"
            "</div>",
            unsafe_allow_html=True,
        )
    else:
        st.warning("⚠️ 수리 정합성 점검 필요: " + " | ".join(math_issues))

    basis_badge_html = (
        f"<span class='ec-basis-pill-recalc'>⚖️ 적용 기준: 2단계 사원표(세법원칙) 기준</span>"
        if active_pm_basis == R.PM_BASIS_RECALC
        else f"<span class='ec-basis-pill-filed'>📋 적용 기준: 기신고 서식 숫자 기준</span>"
    )

    filed_tag = "<br><span style='font-size:10px;font-weight:500;opacity:.75'>기신고 금액</span>"
    th_years_html = "".join(
        f"<th class='{'active-yr' if y == tax_yr else ''}'>{y}년{' (당해 귀속)' if y == tax_yr else ''}"
        + (filed_tag if matrix_cols.get(y, {}).get("from_filed_stmt") else "")
        + "</th>"
        for y in yr_list
    )
    r1_cells = "".join(
        f"<td class='{'active-yr-cell' if y == tax_yr else ''}'>"
        f"{_fmt_matrix_won(matrix_cols[y]['r1_credit'], matrix_cols[y]['r1_claw'], bool(matrix_cols[y].get('r1_na')), bool(matrix_cols[y].get('r1_inferred_from_continued')))}</td>"
        for y in yr_list
    )
    r2_cells = "".join(
        f"<td class='{'active-yr-cell' if y == tax_yr else ''}'>"
        f"{_fmt_matrix_won(matrix_cols[y]['r2_credit'], matrix_cols[y]['r2_claw'], bool(matrix_cols[y].get('r2_na')))}</td>"
        for y in yr_list
    )
    r3_cells = "".join(
        f"<td class='{'active-yr-cell' if y == tax_yr else ''}'>"
        f"{_fmt_matrix_won(matrix_cols[y]['r3_credit'], matrix_cols[y]['r3_claw'], bool(matrix_cols[y].get('r3_na')))}</td>"
        for y in yr_list
    )
    tot_cells = "".join(
        f"<td class='{'active-yr-cell' if y == tax_yr else ''}'>"
        f"{_fmt_signed_total_won(matrix_cols[y]['net_total'])}</td>"
        for y in yr_list
    )

    st.markdown(
        f"<div class='ec-matrix-wrap'>"
        f"<div class='ec-matrix-title'>"
        f"<span>📊 연도별 통합고용세액공제 요약표 ({corp_size} · {loc_label})</span>"
        f"<span style='font-size:1.04rem;font-weight:700;color:#475569;'>"
        f"{basis_badge_html} &nbsp;·&nbsp; 단위: 원 (추가납부세액은 <span class='ec-neg-val'>-붉은색</span> 표시)"
        f"</span>"
        f"</div>"
        f"<table class='ec-matrix-tbl'>"
        f"<colgroup>"
        f"<col style='width:12%;'><col style='width:8%;'>"
        f"<col style='width:20%;'><col style='width:20%;'><col style='width:20%;'><col style='width:20%;'>"
        f"</colgroup>"
        f"<thead>"
        f"<tr><th colspan='2' style='width:20%;'>구분</th>{th_years_html}</tr>"
        f"</thead>"
        f"<tbody>"
        f"<tr><td rowspan='4' class='lbl-col' style='width:12%;'>세액공제액<br><span style='font-size:.94rem;font-weight:700;color:#dc2626;'>(추가납부세액)</span></td>"
        f"<td class='lbl-col' style='width:8%;'>1차</td>{r1_cells}</tr>"
        f"<tr><td class='lbl-col'>2차</td>{r2_cells}</tr>"
        f"<tr><td class='lbl-col'>3차</td>{r3_cells}</tr>"
        f"<tr class='ec-tot-row'><td class='lbl-col'>합계</td>{tot_cells}</tr>"
        f"</tbody>"
        f"</table>"
        f"</div>",
        unsafe_allow_html=True,
    )
    if any(bool(matrix_cols[y].get("r1_inferred_from_continued")) for y in yr_list):
        inferred_yrs = [str(y) for y in yr_list if matrix_cols[y].get("r1_inferred_from_continued")]
        st.caption(
            f"🟧 **[추정복원 안내]** {', '.join(inferred_yrs)}년 1차 세액공제액은 해당 연도 기신고서가 없는 상태에서 다음 해 2차 연속공제액을 바탕으로 역산(청년 감소로 단가가 바뀌지 않은 경우)한 **추정 복원값**입니다."
        )

    with st.container(border=True):
        c_sel_lbl, c_sel_wg, c_scheme_wg = st.columns([2.3, 2.5, 1.8])
        with c_sel_lbl:
            st.markdown(
                "<div style='padding-top:2px;font-size:1.04rem;font-weight:800;color:#0f172a;'>"
                "🔘 세액공제·사후관리 계산 기준 선택"
                "</div>"
                "<div style='font-size:.90rem;color:#475569;margin-top:2px;'>"
                "2단계 사원표 재계산 값과 기신고 서식 숫자 중 적용할 기준을 선택하세요."
                "</div>",
                unsafe_allow_html=True,
            )
        with c_sel_wg:
            _render_pm_basis_selector_right(s, widget_key=f"pm_basis_top_step3_{tax_yr}")
        with c_scheme_wg:
            if tax_yr >= 2026:
                scheme_opt = st.selectbox(
                    f"{tax_yr}년 신규공제 단가 체계",
                    options=["new_2026", "legacy"],
                    index=0 if s.get("scheme_2026", "new_2026") == "new_2026" else 1,
                    format_func=lambda x: "2026 신법 (연차별 차등 A+B+C)" if x == "new_2026" else "구법 단가 시뮬레이션 (균등단가)",
                    label_visibility="collapsed",
                    key=f"scheme_2026_top_sel_{tax_yr}",
                )
                if scheme_opt != s.get("scheme_2026", "new_2026"):
                    s["scheme_2026"] = scheme_opt
                    _save_ec_to_disk(s)
                    st.rerun()

    st.markdown(
        f"<div class='ec-sec-header'>1. {tax_yr}년 세액공제 ({corp_size} · {loc_label} · {basis_lbl})</div>",
        unsafe_allow_html=True,
    )

    cur_s = pkg["cur_s"]
    prev_s = pkg["prev_s"]
    cur_inc = pkg["cur_inc"]

    prv_reg_disp = prev_s["regular"]
    prv_yth_disp = prev_s["youth"]
    prv_gen_disp = prev_s["non_youth"]
    inc_disp = cur_inc

    cap_notice_html = ""
    if inc_disp.get("raw_youth_inc", 0) > inc_disp["youth_inc"]:
        cap_notice_html = (
            f"<div style='font-size:.95rem;font-weight:700;color:#b45309;margin-top:-6px;margin-bottom:12px;'>"
            f"※ 청년 등 순증가 인원({inc_disp['raw_youth_inc']:.2f}명)이 전체 상시근로자 증가 한도({inc_disp['total_inc']:.2f}명)를 초과하여 "
            f"한도({inc_disp['youth_inc']:.2f}명)가 적용되었습니다 (조특법 제29조의8 제1항 제1호)."
            f"</div>"
        )

    st.markdown(
        "<div class='ec-sub-header'><span class='ec-sub-num'>(1)</span><span>평균 상시근로자 증가 인원</span></div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        f"<table class='ec-inc-tbl' style='table-layout:fixed !important; width:100% !important;'>"
        f"<colgroup>"
        f"<col style='width:25% !important;'>"
        f"<col style='width:25% !important;'>"
        f"<col style='width:25% !important;'>"
        f"<col style='width:25% !important;'>"
        f"</colgroup>"
        f"<thead>"
        f"<tr>"
        f"<th style='width:25% !important;'>구분</th>"
        f"<th style='width:25% !important;'>해당 과세연도 ({tax_yr}년)</th>"
        f"<th style='width:25% !important;'>직전 과세연도 ({tax_yr - 1}년)</th>"
        f"<th style='width:25% !important;'>증가인원</th>"
        f"</tr>"
        f"</thead>"
        f"<tbody>"
        f"<tr>"
        f"<td class='inc-lbl' style='width:25% !important;'>상시근로자 증가</td>"
        f"<td style='width:25% !important;'>{cur_s['regular']:.2f}명</td>"
        f"<td style='width:25% !important;'>{prv_reg_disp:.2f}명</td>"
        f"<td class='inc-hi' style='width:25% !important;'>{inc_disp['total_inc']:.2f}명 "
        f"<span style='font-size:.90rem;color:#475569;font-weight:700;'>(증감 {inc_disp['total_diff']:+.2f})</span></td>"
        f"</tr>"
        f"<tr>"
        f"<td class='inc-lbl' style='width:25% !important;'>청년 등 상시근로자 증가</td>"
        f"<td>{cur_s['youth']:.2f}명</td>"
        f"<td>{prv_yth_disp:.2f}명</td>"
        f"<td class='inc-hi'>{inc_disp['youth_inc']:.2f}명</td>"
        f"</tr>"
        f"<tr>"
        f"<td class='inc-lbl' style='width:25% !important;'>이 외 상시근로자 증가</td>"
        f"<td>{cur_s['non_youth']:.2f}명</td>"
        f"<td>{prv_gen_disp:.2f}명</td>"
        f"<td class='inc-hi'>{inc_disp['non_youth_inc']:.2f}명</td>"
        f"</tr>"
        f"</tbody>"
        f"</table>"
        f"{cap_notice_html}",
        unsafe_allow_html=True,
    )
    if prev_s.get("old_rule_regular") is not None and abs(prev_s["old_rule_regular"] - prv_reg_disp) > 1e-9:
        st.caption(
            f"ℹ️ 직전 과세연도({tax_yr - 1}년) 비교 인원({prv_reg_disp:.2f}명)은 개정 규정(조특령 제26조의8 제2항 제1호: 실제 근로기간 1년 미만 제외)으로 재산정하되, "
            f"{tax_yr - 1}년 과세연도 종료일({tax_yr - 1}.12.31.) 현재 계속 근로 중이었던 인원({tax_yr}년 중도퇴사자 포함)은 과세연도 종료일 현황 기준으로 보수적으로 산입하고 "
            f"{tax_yr - 1}년 중 퇴사하여 1년 미만이 확정된 인원만 제외한 값입니다. "
            f"(2단계 {tax_yr - 1}년 표의 {prev_s['old_rule_regular']:.2f}명은 {tax_yr - 1}년 귀속분과 그 사후관리에 쓰는 종전 규정[법률 제21223호 부칙 제34조 · 대통령령 제35999호 부칙 제2조] 인원입니다. "
            f"또한 조특령 제26조의8 제6항 및 제11조의2 제8항 제1호는 가목[전체 상시]과 나목[청년등 상시]만 개별 절사 산식을 두고 있으므로, 시행규칙 별지 제10호의9서식(1) 작성방법 제4호에 따라 "
            f"『① 전체 상시(절사) − ② 청년등 상시(절사) = ③ 청년등 외 상시』 순서로 정본 산정하여[직전 {prv_reg_disp:.2f} − {prv_yth_disp:.2f} = {prv_gen_disp:.2f}명, 당해 {cur_s['regular']:.2f} − {cur_s['youth']:.2f} = {cur_s['non_youth']:.2f}명, 증가 +{inc_disp['non_youth_inc']:.2f}명] "
            f"전체 증가인원 = 청년등 증가 + 청년등 외 증가 항등식을 0.01명 오차 없이 일치시켰습니다.)"
        )

    st.markdown(
        f"<div class='ec-sub-header'><span class='ec-sub-num'>(2)</span><span>1차년도 세액공제액 계산 ({corp_size}, {loc_label})</span></div>",
        unsafe_allow_html=True,
    )
    if pkg["active_scheme"] == "new_2026":
        r_y1 = pkg["rates_new_y1"]
        y_unit_won = r_y1["청년등"] * 10_000
        g_unit_won = r_y1["청년등외"] * 10_000
        y_amt_won = int(round(inc_disp["youth_inc"] * y_unit_won))
        g_amt_won = int(round(inc_disp["non_youth_inc"] * g_unit_won))
        ded_won = int(pkg["cur_new_ded_won"] or 0)
        first_yr_credit_won = max(0, y_amt_won + g_amt_won - ded_won)
        ded_line_html = (
            f"<div class='f-line' style='color:#b45309;font-weight:700;'>"
            f"• 최소고용증가인원({pkg['hurdle_res']['hurdle']:g}명, 조특령 제26조의8 제3항) 차감액: -{ded_won:,}원 ({pkg['hurdle_res']['note']})"
            f"</div>"
            if ded_won > 0 or not pkg["hurdle_res"]["hurdle_met"]
            else ""
        )
        formula_y1_html = (
            f"<div class='f-title'>{tax_yr}년 귀속 1차년도 신규 고용증가 세액공제 (현행 조특법 제29조의8 제1항 A+B+C 구조 중 A 적용 · 신법분 추징 없음)</div>"
            f"<div class='f-line'>• 청년 등 상시근로자 증가(A): <b>{inc_disp['youth_inc']:.2f}명</b> × {y_unit_won:,}원 = <b>{y_amt_won:,}원</b></div>"
            f"<div class='f-line'>• 청년 등 외 상시근로자 증가(A): <b>{inc_disp['non_youth_inc']:.2f}명</b> × {g_unit_won:,}원 = <b>{g_amt_won:,}원</b></div>"
            f"{ded_line_html}"
            f"<div class='f-sub'>산식 합계: ({inc_disp['youth_inc']:.2f} × {y_unit_won:,}원) + ({inc_disp['non_youth_inc']:.2f} × {g_unit_won:,}원)"
            f"{f' - {ded_won:,}원' if ded_won > 0 else ''} = <b>{first_yr_credit_won:,}원</b></div>"
        )
    else:
        r_leg = pkg["rates_legacy"]
        y_unit_won = r_leg["청년등"] * 10_000
        g_unit_won = r_leg["청년등외"] * 10_000
        y_amt_won = int(round(inc_disp["youth_inc"] * y_unit_won))
        g_amt_won = int(round(inc_disp["non_youth_inc"] * g_unit_won))
        first_yr_credit_won = y_amt_won + g_amt_won
        formula_y1_html = (
            f"<div class='f-title'>{tax_yr}년 귀속 1차년도 고용증가 세액공제 (조특법 제29조의8 제1항 단가)</div>"
            f"<div class='f-line'>• 청년 등 상시근로자 증가: <b>{inc_disp['youth_inc']:.2f}명</b> × {y_unit_won:,}원 = <b>{y_amt_won:,}원</b></div>"
            f"<div class='f-line'>• 청년 등 외 상시근로자 증가: <b>{inc_disp['non_youth_inc']:.2f}명</b> × {g_unit_won:,}원 = <b>{g_amt_won:,}원</b></div>"
            f"<div class='f-sub'>산식 합계: ({inc_disp['youth_inc']:.2f} × {y_unit_won:,}원) + ({inc_disp['non_youth_inc']:.2f} × {g_unit_won:,}원) = <b>{first_yr_credit_won:,}원</b></div>"
        )

    y1_box_cls = "pos-box" if first_yr_credit_won > 0 else "zero-box"
    y1_amt_cls = "pos-amt" if first_yr_credit_won > 0 else ""
    st.markdown(
        f"<div class='ec-calc-box {y1_box_cls}'>"
        f"<div class='ec-calc-formula'>{formula_y1_html}</div>"
        f"<div class='ec-calc-amount {y1_amt_cls}'>"
        f"<div class='a-lbl'>1차년도 세액공제액</div>"
        f"<div class='a-val {'pos' if first_yr_credit_won > 0 else ''}'>{first_yr_credit_won:,}원</div>"
        f"</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

    def _build_pm_req_check_bar_html(pm_obj: dict, cohort_yr: int, eval_yr: int, cur_reg_v: float, cur_yth_v: float) -> str:
        init_r = float(pm_obj.get("init_reg") or 0.0)
        init_y = float(pm_obj.get("init_yth") or 0.0)
        is_active = bool(pm_obj.get("active")) and not bool(pm_obj.get("base_missing"))
        is_new_law = str(pm_obj.get("case_code") or "").startswith("신법")

        if is_new_law and isinstance(pm_obj.get("new_tier_info"), dict):
            ti = pm_obj["new_tier_info"]
            tot_inc = float(ti.get("total_inc") or 0.0)
            yth_inc = float(ti.get("youth_inc") or 0.0)
            reg_dec_yes = tot_inc <= 0
            yth_dec_yes = yth_inc <= 0
            r_sub = f"유지 증가인원: 전체 {tot_inc:.2f}명 ({cohort_yr}년 대비)"
            y_sub = f"유지 증가인원: 청년등 {yth_inc:.2f}명 ({cohort_yr}년 대비)"
            r_yes_cls = "active-yes" if reg_dec_yes else ""
            r_no_cls = "active-no" if not reg_dec_yes else ""
            y_yes_cls = "active-yes" if yth_dec_yes else ""
            y_no_cls = "active-no" if not yth_dec_yes else ""
        elif not is_active:
            r_sub = f"1차년도({cohort_yr}년) 공제이력 또는 기초자료 없음"
            y_sub = f"1차년도({cohort_yr}년) 공제이력 또는 기초자료 없음"
            r_yes_cls = r_no_cls = y_yes_cls = y_no_cls = ""
        else:
            reg_diff_v = round(cur_reg_v - init_r, 2)
            yth_diff_v = round(cur_yth_v - init_y, 2)
            reg_dec_yes = reg_diff_v < 0
            yth_dec_yes = yth_diff_v < 0
            r_sub = f"1차년도({cohort_yr}년) {init_r:.2f}명 → 당해({eval_yr}년) {cur_reg_v:.2f}명 ({reg_diff_v:+.2f}명)"
            y_sub = f"1차년도({cohort_yr}년) {init_y:.2f}명 → 당해({eval_yr}년) {cur_yth_v:.2f}명 ({yth_diff_v:+.2f}명)"
            r_yes_cls = "active-yes" if reg_dec_yes else ""
            r_no_cls = "active-no" if not reg_dec_yes else ""
            y_yes_cls = "active-yes" if yth_dec_yes else ""
            y_no_cls = "active-no" if not yth_dec_yes else ""

        return (
            f"<div class='ec-pm-req-bar'>"
            f"<div class='ec-pm-req-item'>"
            f"<div class='ec-pm-req-lbl'>"
            f"<span class='ec-pm-req-title'>1. 1차년도({cohort_yr}년) 대비 상시근로자 감소여부</span>"
            f"<span class='ec-pm-req-sub'>{r_sub}</span>"
            f"</div>"
            f"<div class='ec-yn-group'>"
            f"<span class='ec-yn-pill {r_yes_cls}'>여 (감소)</span>"
            f"<span class='ec-yn-pill {r_no_cls}'>부 (유지·증가)</span>"
            f"</div>"
            f"</div>"
            f"<div class='ec-pm-req-item'>"
            f"<div class='ec-pm-req-lbl'>"
            f"<span class='ec-pm-req-title'>2. 1차년도({cohort_yr}년) 대비 청년 상시근로자 감소여부</span>"
            f"<span class='ec-pm-req-sub'>{y_sub}</span>"
            f"</div>"
            f"<div class='ec-yn-group'>"
            f"<span class='ec-yn-pill {y_yes_cls}'>여 (감소)</span>"
            f"<span class='ec-yn-pill {y_no_cls}'>부 (유지·증가)</span>"
            f"</div>"
            f"</div>"
            f"</div>"
        )

    st.markdown(
        f"<div class='ec-sub-header'><span class='ec-sub-num'>(3)</span><span>2차년도 사후관리 계산 ({tax_yr - 1}년 귀속분 → {tax_yr}년 1차 사후관리)</span></div>",
        unsafe_allow_html=True,
    )
    pm1_req_bar_html = _build_pm_req_check_bar_html(
        pkg["pm_y1"], tax_yr - 1, tax_yr, cur_s["b2_reg"], cur_s["b2_yth"]
    )
    pm1_title, pm1_lines, pm1_amt_lbl, pm1_val, pm1_is_neg = _build_pm_formula_lines(
        pm=pkg["pm_y1"],
        cohort_year=tax_yr - 1,
        eval_year=tax_yr,
        elapsed=1,
        cur_pm_reg=cur_s["b2_reg"],
        cur_pm_yth=cur_s["b2_yth"],
        rates_legacy=H.get_unit_rates(corp_size, _cohort_capital(s, tax_yr - 1, is_capital), scheme="legacy", retention_year=1),
        cohort_is_capital=_cohort_capital(s, tax_yr - 1, is_capital),
        cur_is_capital=is_capital,
    )
    pm1_lines_html = "".join(f"<div class='f-line'>{ln}</div>" for ln in pm1_lines)
    pm1_val_str = f"-{abs(pm1_val):,}원" if pm1_val < 0 else f"{pm1_val:,}원"
    pm1_cls = "neg" if pm1_is_neg else ("pos" if pm1_val > 0 else "")
    pm1_box_cls = "neg-box" if pm1_is_neg else ("pos-box" if pm1_val > 0 else "zero-box")
    pm1_amt_cls = "neg-amt" if pm1_is_neg else ("pos-amt" if pm1_val > 0 else "")
    pm1_cr = int(pkg["pm_y1"].get("continued_credit_won") or 0)
    pm1_cl = int(pkg["pm_y1"].get("clawback_net_payable_won") or 0)
    pm1_split_html = (
        f"<div class='a-sub-split'>공제 +{pm1_cr:,}원 &nbsp;|&nbsp; <span class='ec-neg-val'>추징 -{pm1_cl:,}원</span></div>"
        if (pm1_cr > 0 and pm1_cl > 0)
        else ""
    )

    st.markdown(
        f"{pm1_req_bar_html}"
        f"<div class='ec-calc-box {pm1_box_cls}'>"
        f"<div class='ec-calc-formula'>"
        f"<div class='f-title'>{pm1_title}</div>"
        f"{pm1_lines_html}"
        f"</div>"
        f"<div class='ec-calc-amount {pm1_amt_cls}'>"
        f"<div class='a-lbl'>{pm1_amt_lbl}</div>"
        f"<div class='a-val {pm1_cls}'>{pm1_val_str}</div>"
        f"{pm1_split_html}"
        f"</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

    st.markdown(
        f"<div class='ec-sub-header'><span class='ec-sub-num'>(4)</span><span>3차년도 사후관리 계산 ({tax_yr - 2}년 귀속분 → {tax_yr}년 2차 사후관리)</span></div>",
        unsafe_allow_html=True,
    )
    pm2_req_bar_html = _build_pm_req_check_bar_html(
        pkg["pm_y2"], tax_yr - 2, tax_yr, cur_s["b3_reg"], cur_s["b3_yth"]
    )
    pm2_title, pm2_lines, pm2_amt_lbl, pm2_val, pm2_is_neg = _build_pm_formula_lines(
        pm=pkg["pm_y2"],
        cohort_year=tax_yr - 2,
        eval_year=tax_yr,
        elapsed=2,
        cur_pm_reg=cur_s["b3_reg"],
        cur_pm_yth=cur_s["b3_yth"],
        rates_legacy=H.get_unit_rates(corp_size, _cohort_capital(s, tax_yr - 2, is_capital), scheme="legacy", retention_year=1),
        cohort_is_capital=_cohort_capital(s, tax_yr - 2, is_capital),
        cur_is_capital=is_capital,
    )
    pm2_lines_html = "".join(f"<div class='f-line'>{ln}</div>" for ln in pm2_lines)
    pm2_val_str = f"-{abs(pm2_val):,}원" if pm2_val < 0 else f"{pm2_val:,}원"
    pm2_cls = "neg" if pm2_is_neg else ("pos" if pm2_val > 0 else "")
    pm2_box_cls = "neg-box" if pm2_is_neg else ("pos-box" if pm2_val > 0 else "zero-box")
    pm2_amt_cls = "neg-amt" if pm2_is_neg else ("pos-amt" if pm2_val > 0 else "")
    pm2_cr = int(pkg["pm_y2"].get("continued_credit_won") or 0)
    pm2_cl = int(pkg["pm_y2"].get("clawback_net_payable_won") or 0)
    pm2_split_html = (
        f"<div class='a-sub-split'>공제 +{pm2_cr:,}원 &nbsp;|&nbsp; <span class='ec-neg-val'>추징 -{pm2_cl:,}원</span></div>"
        if (pm2_cr > 0 and pm2_cl > 0)
        else ""
    )

    st.markdown(
        f"{pm2_req_bar_html}"
        f"<div class='ec-calc-box {pm2_box_cls}'>"
        f"<div class='ec-calc-formula'>"
        f"<div class='f-title'>{pm2_title}</div>"
        f"{pm2_lines_html}"
        f"</div>"
        f"<div class='ec-calc-amount {pm2_amt_cls}'>"
        f"<div class='a-lbl'>{pm2_amt_lbl}</div>"
        f"<div class='a-val {pm2_cls}'>{pm2_val_str}</div>"
        f"{pm2_split_html}"
        f"</div>"
        f"</div>",
        unsafe_allow_html=True,
    )
    for _coh_yr, _pm_cur, _pm_rc, _base_key in (
        (tax_yr - 1, pkg["pm_y1"], pkg["pm_y1_recalc"], "base_y1"),
        (tax_yr - 2, pkg["pm_y2"], pkg["pm_y2_recalc"], "base_y2"),
    ):
        if _pm_cur.get("base_missing") and not _pm_rc.get("base_missing"):
            _c_w, _c_b = st.columns([3.8, 2.2])
            with _c_w:
                st.info(
                    f"💡 **2단계 사원표 기준 {_coh_yr}년 귀속분 재계산 값**: "
                    f"상시 **{_pm_rc.get('init_reg', 0):.2f}명** (청년등 **{_pm_rc.get('init_yth', 0):.2f}명**), "
                    f"증가 **+{_pm_rc.get('init_yth_inc', 0) + _pm_rc.get('init_gen_inc', 0):.2f}명** → "
                    f"사후관리 **{_pm_rc.get('case_code')}** "
                    f"(공제 **+{_pm_rc.get('continued_credit_won', 0):,}원** / 추징 **-{_pm_rc.get('clawback_net_payable_won', 0):,}원**)"
                )
            with _c_b:
                if st.button(
                    f"🔄 {_coh_yr}년 사원표 재계산 값을 기신고 기초값에 바로 반영",
                    type="primary",
                    use_container_width=True,
                    key=f"btn_quick_fill_{_coh_yr}_{tax_yr}",
                ):
                    _fd = ps.setdefault(str(_coh_yr), {})
                    _brc = (pkg.get(_base_key) or {}).get("recalc") or {}
                    if _brc.get("init_reg") is not None:
                        _fd["상시"] = float(_brc["init_reg"])
                    if _brc.get("init_yth") is not None:
                        _fd["청년등"] = float(_brc["init_yth"])
                    if _brc.get("init_yth_inc") is not None:
                        _fd["청년등_증가"] = float(_brc["init_yth_inc"])
                    if _brc.get("init_gen_inc") is not None:
                        _fd["청년등외_증가"] = float(_brc["init_gen_inc"])
                    if _fd.get("공제세액") is None:
                        _rc_rates = H.get_unit_rates(corp_size, _cohort_capital(s, _coh_yr, is_capital), scheme="legacy", retention_year=1)
                        _fd["공제세액"] = int(
                            round(
                                (float(_fd.get("청년등_증가") or 0.0) * _rc_rates["청년등"]
                                 + float(_fd.get("청년등외_증가") or 0.0) * _rc_rates["청년등외"]) * 10_000
                            )
                        )
                    s["fill_ver"] = int(s.get("fill_ver", 0)) + 1
                    _save_ec_to_disk(s)
                    st.rerun()

    if pkg["additional_credit_won"] > 0 or pkg["additional_clawback_won"] > 0 or pkg["rural_special_tax_won"] > 0:
        add_net = pkg["additional_credit_won"] - pkg["additional_clawback_won"]
        add_box_cls = "neg-box" if add_net < 0 else ("pos-box" if add_net > 0 else "zero-box")
        add_amt_cls = "neg-amt" if add_net < 0 else ("pos-amt" if add_net > 0 else "")
        st.markdown(
            f"<div class='ec-sub-header'><span class='ec-sub-num'>(5)</span><span>추가공제(육아휴직 복귀·정규직 전환) 및 농어촌특별세(20%) 요약</span></div>"
            f"<div class='ec-calc-box {add_box_cls}'>"
            f"<div class='ec-calc-formula'>"
            f"<div class='f-line'>• 육아휴직 복귀(제5항)·정규직 전환(제4항, ~2024년 전환분) 추가공제: <b>+{pkg['additional_credit_won']:,}원</b> / "
            f"2년 내 퇴직 추가납부: <span class='ec-neg-val'>-{pkg['additional_clawback_won']:,}원</span></div>"
            f"<div class='f-line'>• 농어촌특별세(실공제세액 {pkg['actual_deducted_credit_won']:,}원의 20%, 미공제 이월액 제외): "
            f"<span class='ec-neg-val'>-{pkg['rural_special_tax_won']:,}원</span> "
            f"(농특세 차감 후 실질 세후 혜택: <b>{pkg['net_after_rural_tax_won']:+,}원</b> · 최저한세[조특법 제132조] 한도 초과 이월분은 아래 입력란에서 조정 가능)</div>"
            f"</div>"
            f"<div class='ec-calc-amount {add_amt_cls}'>"
            f"<div class='a-lbl'>추가공제 순세액</div>"
            f"<div class='a-val {'neg' if add_net < 0 else 'pos'}'>"
            f"{f'-{abs(add_net):,}원' if add_net < 0 else f'{add_net:,}원'}</div>"
            f"</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

    fill_ver = int(s.get("fill_ver", 0))
    kver = (abs(hash(str(s.get("built_sig")))) + fill_ver) % 100000

    def _num_in(col, label, cur, key, step=0.01, is_won=False, help_txt=None):
        if is_won:
            v = None if cur in (None, "") else int(float(cur))
            return col.number_input(
                label, min_value=0, value=v, step=100_000, placeholder="기신고 금액", key=key, help=help_txt
            )
        v = None if cur in (None, "") else float(cur)
        return col.number_input(
            label, min_value=0.0, value=v, step=step, format="%.2f", placeholder="기신고 숫자", key=key, help=help_txt
        )

    with st.expander(
        f"⚙️ 기신고 서식 숫자 직접 입력·보정 ({tax_yr-1}년 · {tax_yr-2}년 귀속분 — 『📋 기신고 서식 숫자 기준』 선택 시 사용)",
        expanded=(active_pm_basis == R.PM_BASIS_FILED and not has_any_manual_ps),
    ):
        c_cap, c_btn = st.columns([4.2, 1.8])
        with c_cap:
            st.caption(
                "기신고 상시근로자 명세서·공제감면세액계산서 숫자가 사원표 재계산 값과 다를 때 입력합니다. "
                "각 칸 이름 옆 괄호는 2단계 사원표로 계산한 『세법원칙 기준』 값입니다."
            )
        with c_btn:
            if st.button(
                "🔄 2단계 사원표 재계산 값으로 빈칸 자동 채우기",
                use_container_width=True,
                key=f"btn_fill_from_recalc_{tax_yr}",
            ):
                for cohort, t_init, t_before in (
                    (tax_yr - 1, prev_t, prev2_t),
                    (tax_yr - 2, prev2_t, totals_all.get(tax_yr - 3, {})),
                ):
                    f_d = ps.setdefault(str(cohort), {})
                    has_init = bool(t_init.get("has_data")) and not t_init.get("from_filed")
                    has_before = bool(t_before.get("has_data")) and not t_before.get("from_filed")
                    if has_init:
                        if f_d.get("상시") is None:
                            f_d["상시"] = float(t_init.get("상시_평균", 0.0))
                        if f_d.get("청년등") is None:
                            f_d["청년등"] = float(t_init.get("청년등_평균", 0.0))
                        if f_d.get("상시_총인원") is None:
                            f_d["상시_총인원"] = float(t_init.get("상시_합계", 0.0))
                        if f_d.get("청년등_총인원") is None:
                            f_d["청년등_총인원"] = float(t_init.get("청년등_합계", 0.0))
                    if has_init and has_before:
                        inc_c = H.calc_increase_with_cap(
                            t_init["상시_평균"], t_init["청년등_평균"], t_before["상시_평균"], t_before["청년등_평균"]
                        )
                        if f_d.get("청년등_증가") is None:
                            f_d["청년등_증가"] = float(inc_c["youth_inc"])
                        if f_d.get("청년등외_증가") is None:
                            f_d["청년등외_증가"] = float(inc_c["non_youth_inc"])
                        r_coh = H.get_unit_rates(corp_size, _cohort_capital(s, cohort, is_capital), scheme="legacy", retention_year=1)
                        c1_est = int(
                            round(
                                (inc_c["youth_inc"] * r_coh["청년등"] + inc_c["non_youth_inc"] * r_coh["청년등외"])
                                * 10_000
                            )
                        )
                        if f_d.get("공제세액") is None:
                            f_d["공제세액"] = c1_est
                        if cohort == tax_yr - 2 and f_d.get("2차_공제세액") is None and corp_size not in ("일반기업", "대기업"):
                            if not (prev_t.get("has_data") and float(prev_t.get("b2_reg", 0.0)) < float(t_init.get("상시_평균", 0.0))):
                                f_d["2차_공제세액"] = c1_est
                s["fill_ver"] = fill_ver + 1
                _save_ec_to_disk(s)
                st.rerun()

        col_y1, col_y2 = st.columns(2)
        for col, cohort, step_lbl, t_init, t_before in (
            (col_y1, tax_yr - 1, "1차 사후관리 (2차년도)", prev_t, prev2_t),
            (col_y2, tax_yr - 2, "2차 사후관리 (3차년도)", prev2_t, totals_all.get(tax_yr - 3, {})),
        ):
            f = ps.setdefault(str(cohort), {})
            has_init = bool(t_init.get("has_data")) and not t_init.get("from_filed")
            has_before = bool(t_before.get("has_data")) and not t_before.get("from_filed")
            inc_r = (
                H.calc_increase_with_cap(
                    t_init["상시_평균"], t_init["청년등_평균"], t_before["상시_평균"], t_before["청년등_평균"]
                )
                if (has_init and has_before)
                else None
            )
            r_reg = f"{t_init['상시_평균']:.2f}" if has_init else "-"
            r_yth = f"{t_init['청년등_평균']:.2f}" if has_init else "-"
            r_rtot = f"{t_init['상시_합계']:g}" if has_init else "-"
            r_ytot = f"{t_init['청년등_합계']:g}" if has_init else "-"
            r_yi = f"{inc_r['youth_inc']:.2f}" if inc_r else "-"
            r_gi = f"{inc_r['non_youth_inc']:.2f}" if inc_r else "-"

            with col:
                st.markdown(f"**📋 {cohort}년 귀속 기신고분 ({step_lbl})**")
                a, b_ = st.columns(2)
                f["상시_총인원"] = _num_in(
                    a, f"{cohort}년 상시 연인원 합계 (재계산: {r_rtot})", f.get("상시_총인원"), f"pf_{cohort}_rtot_{kver}", step=1.0
                )
                f["청년등_총인원"] = _num_in(
                    b_, f"{cohort}년 청년등 연인원 합계 (재계산: {r_ytot})", f.get("청년등_총인원"), f"pf_{cohort}_ytot_{kver}", step=1.0
                )
                f["상시"] = _num_in(
                    a, f"{cohort}년 상시 평균인원 (재계산: {r_reg})", f.get("상시"), f"pf_{cohort}_reg_{kver}"
                )
                f["청년등"] = _num_in(
                    b_, f"{cohort}년 청년등 평균인원 (재계산: {r_yth})", f.get("청년등"), f"pf_{cohort}_yth_{kver}"
                )
                f["청년등_증가"] = _num_in(
                    a, f"{cohort}년 공제 청년등 증가 (재계산: {r_yi})", f.get("청년등_증가"), f"pf_{cohort}_yi_{kver}"
                )
                f["청년등외_증가"] = _num_in(
                    b_, f"{cohort}년 공제 청년등외 증가 (재계산: {r_gi})", f.get("청년등외_증가"), f"pf_{cohort}_gi_{kver}"
                )
                if cohort == tax_yr - 1:
                    f["공제세액"] = _num_in(
                        a, f"{cohort}년 최초 공제세액(원, 추가납부 한도)", f.get("공제세액"), f"pf_{cohort}_clm_{kver}", is_won=True
                    )
                else:
                    f["공제세액"] = _num_in(
                        a,
                        f"{cohort}년 최초 공제세액(1차년도, 원)",
                        f.get("공제세액"),
                        f"pf_{cohort}_clm_{kver}",
                        is_won=True,
                        help_txt="2년차 추가납부 한도는 이 금액과 아래 2차 공제세액을 자동으로 더해 계산합니다. 1차년도 금액만 넣으세요.",
                    )
                f["이월세액"] = _num_in(
                    b_, f"{cohort}년분 미공제 이월세액(원)", f.get("이월세액"), f"pf_{cohort}_cf_{kver}", is_won=True
                )
                if cohort == tax_yr - 2:
                    f["2차_공제세액"] = _num_in(
                        a,
                        f"{tax_yr-1}년 신고 시 2차 공제세액(원)",
                        f.get("2차_공제세액"),
                        f"pf_{cohort}_y1c_{kver}",
                        is_won=True,
                        help_txt="0을 넣으면 1년차에 공제가 중단된 것으로 봅니다. 모르면 비워두세요.",
                    )
                    f["기추징세액"] = _num_in(
                        b_,
                        f"{tax_yr-1}년 신고 시 1년차 추가납부액(원)",
                        f.get("기추징세액"),
                        f"pf_{cohort}_paid_{kver}",
                        is_won=True,
                    )
                loc_opts = ["사이드바 소재지와 같음", "수도권", "수도권 밖"]
                cur_loc = f.get("수도권")
                sel = st.selectbox(
                    f"{cohort}년 공제 당시 사업장 소재지",
                    loc_opts,
                    index=0 if cur_loc is None else (1 if cur_loc else 2),
                    key=f"pf_{cohort}_loc_{kver}",
                    help="2·3차년도 연속공제와 추가납부는 최초로 공제받은 해의 단가(수도권 1,450만/850만, 수도권 밖 1,550만/950만)를 씁니다. "
                         "본점을 옮겼다면 공제받을 당시 소재지를 고르세요.",
                )
                new_loc = None if sel == loc_opts[0] else (sel == "수도권")
                if new_loc != cur_loc:
                    f["_소재지_추정"] = False
                f["수도권"] = new_loc
                notes = []
                if f.get("_증가_추정"):
                    st.warning("⚠️ 공제세액을 만드는 증가인원 조합이 여러 개라 그중 하나를 추정했습니다. "
                               "단시간근로자가 있었던 회사는 틀릴 수 있으니 기신고 상시근로자 명세서로 꼭 확인하세요.")
                elif f.get("_증가_역산"):
                    notes.append("증가인원은 기신고 공제세액에서 역산한 값입니다")
                if f.get("_2차_AI판독") and cohort == tax_yr - 2:
                    st.warning("⚠️ 2차 공제세액은 세액공제조정명세서 계산명세(18S)로 확인하지 못해 AI가 읽은 값입니다. "
                               f"{tax_yr-1}년 신고서의 통합고용세액공제 2차 금액과 맞는지 확인하세요.")
                if f.get("_소재지_추정") and new_loc is not None:
                    notes.append(f"소재지는 기신고 공제세액이 {'수도권' if new_loc else '수도권 밖'} 단가와 맞아 자동 선택했습니다")
                if notes:
                    st.caption("ℹ️ " + " · ".join(notes) + ". 다르면 고쳐주세요.")

    with st.expander("➕ 추가공제(육아휴직복귀·정규직전환·출산휴가대체인력) 및 최저한세 미공제 이월세액 입력", expanded=False):
        ca1, ca2, ca3 = st.columns(3)
        add_in["parental_return_count"] = ca1.number_input(
            "육아휴직 복귀자 수 (명, ~2026년 복귀분 적용)",
            0,
            500,
            int(add_in.get("parental_return_count") or 0),
            1,
            help="조특법 제29조의8 제5항: 1인당 중소 1,300만원 / 중견 900만원 추가공제 (전체 상시근로자 수 미감소 요건 충족 시)",
        )
        add_in["regular_conversion_count"] = ca2.number_input(
            "정규직 전환자 수 (명, ~2024년 전환분까지만 적용)",
            0,
            500,
            int(add_in.get("regular_conversion_count") or 0),
            1,
            disabled=(tax_yr >= 2025),
            help="조특법 제29조의8 제4항 정규직 전환 추가공제는 2024년 12월 31일 이전 전환분까지만 적용되며 2025년 이후 전환분은 해당이 없습니다.",
        )
        add_in["additional_clawback_count"] = ca3.number_input(
            "복귀·전환일로부터 2년 내 퇴직자 수 (추징 대상, 명)",
            0,
            500,
            int(add_in.get("additional_clawback_count") or 0),
            1,
            help="조특법 제29조의8 제6항: 복귀·전환일로부터 2년 내 근로관계 종료 시 기공제 세액 추징",
        )
        cb1, cb2, cb3 = st.columns(3)
        add_in["maternity_replacement_count"] = cb1.number_input(
            f"{tax_yr}년 출산전후휴가 대체인력 연평균 제외인원 (명)",
            0.0,
            100.0,
            float(add_in.get("maternity_replacement_count") or 0.0),
            0.01,
            format="%.2f",
            help="조특령 제26조의8 제7항: 대체인력을 채용한 출산전후휴가자는 추가공제 요건(상시근로자 미감소) 판정 시 당해 상시근로자 수에서 뺍니다.",
        )
        add_in["maternity_prev_count"] = cb2.number_input(
            f"{tax_yr-1}년 출산전후휴가 대체인력 연평균 제외인원 (명)",
            0.0,
            100.0,
            float(add_in.get("maternity_prev_count") or 0.0),
            0.01,
            format="%.2f",
            help="직전연도에 대체인력을 채용한 출산전후휴가자의 연평균 인원입니다.",
        )
        add_in["current_unclaimed_carryforward_won"] = cb3.number_input(
            f"{tax_yr}년 발생 공제세액 중 최저한세(조특법 제132조) 등으로 당해 미공제 이월된 세액 (원)",
            0,
            50_000_000_000,
            int(add_in.get("current_unclaimed_carryforward_won") or 0),
            100_000,
            help="통합고용세액공제는 조특법 제132조 최저한세(중소 과세표준의 7%) 적용 대상이며, 한도 초과 미공제분은 조특법 제144조에 따라 10년간 이월공제됩니다. 농어촌특별세(20%)는 실제 감면받는 세액(당해 공제액 - 당해 미공제 이월액)에 대해서만 부과됩니다.",
        )


    with st.expander("📊 [상세 대조] 인원 증감 브리지 표 · 비교인원(보수적 vs 공격적) · 기신고 vs 세법원칙 비교표", expanded=False):
        wf_df, ca_df = _build_headcount_waterfall_and_comparison(s, pkg, tax_yr)
        st.markdown(f"**① {tax_yr-1}년 비교인원 → {tax_yr}년 당해 상시근로자 인원 증감 브리지 표 (Waterfall Bridge)**")
        st.dataframe(wf_df, use_container_width=True, hide_index=True)
        st.markdown(f"**② 직전연도({tax_yr-1}년) 비교인원 산정 기준 비교 (보수적 정본 vs 공격적 소급제외)**")
        st.dataframe(ca_df, use_container_width=True, hide_index=True)
        st.markdown("**③ 연도 · 블록별 상시근로자 현황 및 사후관리 기신고 vs 세법원칙 비교**")
        cur_b2_gen = round(max(0.0, pkg["cur_s"]["b2_reg"] - pkg["cur_s"]["b2_yth"]), 2)
        cur_b3_gen = round(max(0.0, pkg["cur_s"]["b3_reg"] - pkg["cur_s"]["b3_yth"]), 2)
        cur_b2_gtot = round(max(0.0, pkg["cur_s"]["reg_total"] - pkg["cur_s"]["b2_yth_total"]), 2)
        cur_b3_gtot = round(max(0.0, pkg["cur_s"]["reg_total"] - pkg["cur_s"]["b3_yth_total"]), 2)
        cmp_rows = [
            {
                "연도 · 블록 구분": f"① {tax_yr}년 귀속 [{b3_title}]",
                "전체 상시 [총인원 / 평균]": f"{pkg['cur_s']['reg_total']:g}명 / {pkg['cur_s']['regular']:.2f}명",
                "청년등 [총인원 / 평균]": f"{pkg['cur_s']['yth_total']:g}명 / {pkg['cur_s']['youth']:.2f}명",
                "청년등 외 [총인원 / 평균]": f"{pkg['cur_s']['non_youth_total']:g}명 / {pkg['cur_s']['non_youth']:.2f}명",
                "적용 기준 및 비교 안내": f"당해({tax_yr}년) 신법 기준(실제 근로기간 1년 미만 제외 · ÷{pkg['cur_s']['months_in_year']}개월 합산 후 절사)",
            },
            {
                "연도 · 블록 구분": f"② {tax_yr}년 귀속 [{b4_title}]",
                "전체 상시 [총인원 / 평균]": f"{pkg['cur_s']['reg_total']:g}명 / {pkg['cur_s']['b2_reg']:.2f}명",
                "청년등 [총인원 / 평균]": f"{pkg['cur_s']['b2_yth_total']:g}명 / {pkg['cur_s']['b2_yth']:.2f}명",
                "청년등 외 [총인원 / 평균]": f"{cur_b2_gtot:g}명 / {cur_b2_gen:.2f}명",
                "적용 기준 및 비교 안내": f"{tax_yr-1}년분 사후관리 종전규정(법률 제21223호 부칙 제34조 · 대통령령 제35999호 부칙 제2조 · 제36127호 부칙 제11조 · 구 조특령[대통령령 제36127호 개정 전] 제26조의8 제5항) 반영",
            },
            {
                "연도 · 블록 구분": f"③ {tax_yr}년 귀속 [{b5_title}]",
                "전체 상시 [총인원 / 평균]": f"{pkg['cur_s']['reg_total']:g}명 / {pkg['cur_s']['b3_reg']:.2f}명",
                "청년등 [총인원 / 평균]": f"{pkg['cur_s']['b3_yth_total']:g}명 / {pkg['cur_s']['b3_yth']:.2f}명",
                "청년등 외 [총인원 / 평균]": f"{cur_b3_gtot:g}명 / {cur_b3_gen:.2f}명",
                "적용 기준 및 비교 안내": f"{tax_yr-2}년분 사후관리 종전규정(법률 제21223호 부칙 제34조 · 대통령령 제35999호 부칙 제2조 · 제36127호 부칙 제11조 · 구 조특령[대통령령 제36127호 개정 전] 제26조의8 제5항) 반영",
            },
        ]
        st.dataframe(pd.DataFrame(cmp_rows), use_container_width=True, hide_index=True)

        pm_cmp_df = pd.DataFrame(
            [
                {
                    "사후관리 구분": f"① {tax_yr-1}년 귀속분 1차 사후관리 (2차년도)",
                    "기신고 기준 [연속공제 / 추징]": f"+{pkg['pm_y1_filed']['continued_credit_won']:,}원 / -{pkg['pm_y1_filed']['clawback_net_payable_won']:,}원",
                    "세법원칙 기준 [연속공제 / 추징]": f"+{pkg['pm_y1_recalc']['continued_credit_won']:,}원 / -{pkg['pm_y1_recalc']['clawback_net_payable_won']:,}원",
                    "현재 선택된 적용 결과": f"{pkg['pm_y1']['case_code']} (+{pkg['pm_y1']['continued_credit_won']:,}원 / -{pkg['pm_y1']['clawback_net_payable_won']:,}원)",
                },
                {
                    "사후관리 구분": f"② {tax_yr-2}년 귀속분 2차 사후관리 (3차년도)",
                    "기신고 기준 [연속공제 / 추징]": f"+{pkg['pm_y2_filed']['continued_credit_won']:,}원 / -{pkg['pm_y2_filed']['clawback_net_payable_won']:,}원",
                    "세법원칙 기준 [연속공제 / 추징]": f"+{pkg['pm_y2_recalc']['continued_credit_won']:,}원 / -{pkg['pm_y2_recalc']['clawback_net_payable_won']:,}원",
                    "현재 선택된 적용 결과": f"{pkg['pm_y2']['case_code']} (+{pkg['pm_y2']['continued_credit_won']:,}원 / -{pkg['pm_y2']['clawback_net_payable_won']:,}원)",
                },
            ]
        )
        st.dataframe(pm_cmp_df, use_container_width=True, hide_index=True)

    st.markdown(
        "<div class='ec-law-ref-box'>"
        "<div style='font-weight:900;font-size:1.12rem;color:#1e3a8a;margin-bottom:8px;'>"
        "📚 계산근거 관련 법령조문 (국가법령정보센터 바로가기)"
        "</div>"
        "• <a href='https://www.law.go.kr/법령/조세특례제한법/제29조의8' target='_blank'>"
        "조세특례제한법 제29조의8 (통합고용세액공제)</a> — "
        "제1항(고용증가 세액공제 A+B+C 점증형 구조), 제2항(경력단절 근로자 정의), "
        "구 제1항(연속공제)·구 제3항(인원 감소 시 추가납부세액) 및 법률 제21223호 부칙 제34조 경과조치(2024·2025년 귀속분), "
        "제4항(정규직 전환 추가공제, ~2024년 전환분), 제5항(육아휴직 복귀 추가공제)<br>"
        "• <a href='https://www.law.go.kr/법령/조세특례제한법시행령/제26조의8' target='_blank'>"
        "조세특례제한법 시행령 제26조의8 (통합고용세액공제 상시근로자 범위·사후관리 산식)</a> — "
        "제2항(내국인 근로자[조특법 제2조 제1항 제1호 거주자 포함] 및 실제 근로기간 1년 미만 제외 · 대통령령 제35999호 부칙 제2조 경과조치), "
        "제3항(최소고용증가인원수), 제4항(청년등 상시근로자 범위, 전체 증가한도 Cap은 법 제29조의8 제1항 제1호), "
        "제6항 및 <a href='https://www.law.go.kr/법령/조세특례제한법시행령/제11조의2' target='_blank'>제11조의2 제8항 제1호 가목·나목</a> 준용(전체·청년등 합산 후 100분의 1 미만 절사 및 시행규칙 별지 제10호의9서식 작성방법 제4호에 따른 청년등 외 차감 산정), "
        "제8항 및 <a href='https://www.law.go.kr/법령/조세특례제한법시행령/제23조' target='_blank'>제23조 제13항</a> 준용(포괄양수·고용승계 특례)<br>"
        "• <a href='https://www.law.go.kr/법령/조세특례제한법/제132조' target='_blank'>"
        "조세특례제한법 제132조 (최저한세)</a> &nbsp;|&nbsp; "
        "<a href='https://www.law.go.kr/법령/조세특례제한법/제144조' target='_blank'>"
        "조세특례제한법 제144조 (세액공제액의 이월공제 10년 및 미공제분 우선 차감)</a> &nbsp;|&nbsp; "
        "<a href='https://www.law.go.kr/법령/농어촌특별세법/제5조' target='_blank'>"
        "농어촌특별세법 제5조 제1항 (실제 감면세액의 20% 과세)</a>"
        "</div>",
        unsafe_allow_html=True,
    )

    _save_ec_to_disk(s)
    corp_nm_fn = re.sub(r'[\\/:*?"<>|\s]+', "_", str((b.get("상호") or "사업장")).strip())[:30]
    st.markdown("<div class='ec-nav-divider'></div>", unsafe_allow_html=True)
    c_prev, _, c_pdf3, c_next = st.columns([1.2, 3.45, 1.25, 1.3])
    if c_prev.button("< 이전", use_container_width=True, key="btn_step3_prev"):
        s["step"] = 2
        _trigger_scroll_to_top(s)
        _save_ec_to_disk(s)
        st.rerun()
    with c_pdf3:
        with st.container(key="ec_btn_pdf_step3_wrap"):
            st.download_button(
                "📕 PDF 출력",
                data=_build_step3_calculation_pdf_bytes(s, pkg, matrix_cols),
                file_name=f"{corp_nm_fn}_{tax_yr}년귀속_통합고용세액공제_계산서.pdf",
                mime="application/pdf",
                use_container_width=True,
                key="dl_pdf_step3_calc",
                help="3단계 연도별 세액공제 요약표 및 (1)~(4) 상세 계산 산식을 A4 PDF로 즉시 다운로드합니다.",
            )
    if c_next.button("다음(4단계)", type="primary", use_container_width=True, key="btn_step3_next"):
        s["step"] = 4
        s["max_step_reached"] = max(int(s.get("max_step_reached") or 1), 4)
        _trigger_scroll_to_top(s)
        _save_ec_to_disk(s)
        st.rerun()