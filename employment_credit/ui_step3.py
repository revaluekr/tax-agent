# -*- coding: utf-8 -*-
"""통합고용세액공제 계산기 화면 — 3단계 공제액 계산: 기신고 입력·사후관리·연도별 매트릭스·산식 설명

(ui.py에서 나눈 파일. 현행 조세특례제한법 제29조의8 및 시행령 제26조의8 조문 체계·부칙 경과조치·직전·전전 비교인원 일관된 해석 기준 및 다년도 자동 재산정 반영)
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
    _cohort_corp_size,
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
    needs_check: bool = False,
) -> str:
    if is_na:
        return "<span class='ec-zero-val'>-</span>"
    """
    [6-4] 상단 4개년 요약 매트릭스 셀 포맷터:
    - 과거 연도 1차 공제액의 '추정복원'을 폐지하고, 세액공제조정명세서(부표3)나 기신고서에서 확인되지 않으면
      빈칸 + 주황 배지 '신고서 확인 필요'로 표시합니다.
    """
    cr = int(round(float(credit_won or 0)))
    cl = int(round(float(clawback_won or 0)))
    if cr == 0 and cl == 0 and needs_check:
        return (
            "<span class='ec-cell-tag' style='background:#ffedd5;color:#c2410c;border:1px solid #fdba74;font-weight:800;'>"
            "신고서 확인 필요</span>"
        )
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
        if int((matrix_cols.get(y0) or {}).get("r1_credit") or 0) == 0 and not bool((matrix_cols.get(y0) or {}).get("r1_needs_check")) and int((matrix_cols.get(y1) or {}).get("r2_credit") or 0) > 0:
            issues.append(f"{y0}년 1차 공제액이 0원인데 {y1}년 2차 연속공제액이 존재함")

    actual_ded = int(pkg.get("actual_deducted_credit_won") or 0)
    rural_tax = int(pkg.get("rural_special_tax_won") or 0)
    if abs(int(round(actual_ded * R.RURAL_SPECIAL_TAX_RATE)) - rural_tax) > 1:
        issues.append("농어촌특별세(20%) 산출 오차 감지")

    return (len(issues) == 0), issues


def _build_top_kpi_cards_html(pkg: dict, tax_yr: int) -> str:
    """
    [⑨ 상단 3대 핵심 KPI 요약 카드 — 당해 확정 공제세액 · 추징/농특세 · 실질 순절세액]
    - 경정청구(기신고 vs 세법상 재계산 비교)는 상단 KPI 카드에서 제외하고 하단 전용 비교 창(st.dialog)으로 분리합니다.
    """
    tot_gross = int(pkg.get("total_credit_gross_won") or 0)
    claw_net = int(pkg.get("total_clawback_net_payable_won") or 0)
    rural_won = int(pkg.get("rural_special_tax_won") or 0)
    net_confirmed = int(pkg.get("net_after_rural_tax_won") or 0)

    c1_won = int(pkg.get("cur_base_credit_won") or 0)
    c_cont = int(pkg.get("total_continued_credit_won") or 0)
    c_add = int(pkg.get("additional_credit_won") or 0)

    return (
        "<div style='display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-bottom:12px;'>"
        f"<div style='background:#eff6ff;border:1px solid #bfdbfe;border-left:4px solid #1d4ed8;border-radius:10px;padding:10px 14px;'>"
        f"<div style='font-size:0.83rem;font-weight:800;color:#1e40af;'>① {tax_yr}년 총 공제세액 (확정)</div>"
        f"<div style='font-size:1.32rem;font-weight:900;color:#1d4ed8;margin-top:3px;'>+{tot_gross:,}원</div>"
        f"<div style='font-size:0.77rem;color:#475569;margin-top:2px;'>1차 {c1_won:,} + 연속 {c_cont:,}"
        + (f" + 추가 {c_add:,}" if c_add > 0 else "")
        + "</div></div>"
        f"<div style='background:#f8fafc;border:1px solid #cbd5e1;border-left:4px solid #64748b;border-radius:10px;padding:10px 14px;'>"
        f"<div style='font-size:0.83rem;font-weight:800;color:#334155;'>② 추가납부(추징) · 농특세(20%)</div>"
        f"<div style='font-size:1.32rem;font-weight:900;color:{'#dc2626' if claw_net > 0 else '#334155'};margin-top:3px;'>"
        f"-{claw_net + rural_won:,}원</div>"
        f"<div style='font-size:0.77rem;color:#475569;margin-top:2px;'>사후추징 -{claw_net:,}원 · 농특세 -{rural_won:,}원</div>"
        f"</div>"
        f"<div style='background:#f0fdf4;border:1px solid #86efac;border-left:4px solid #16a34a;border-radius:10px;padding:10px 14px;'>"
        f"<div style='font-size:0.83rem;font-weight:800;color:#166534;'>③ 당해 확정 실질 순절세액</div>"
        f"<div style='font-size:1.32rem;font-weight:900;color:#15803d;margin-top:3px;'>{net_confirmed:+,}원</div>"
        f"<div style='font-size:0.77rem;color:#15803d;font-weight:700;margin-top:2px;'>총공제 − 추징 − 농특세 (당해 확정분)</div>"
        f"</div>"
        "</div>"
    )

def _build_compact_bridge_info(
    s: dict,
    prev_yr: int,
    cur_yr: int,
    prev_reg_override: float | None = None,
    cur_reg_override: float | None = None,
    use_new_rule_prev: bool = True,
) -> dict[str, Any]:
    """
    [100명·1,000명 규모 대응 2줄 고정 길이 인원 증감 브리지 산출 엔진]
    - 1줄(항상 고정 길이): `{prev_yr}년 {start_m:g} → 신규 +{new_m:g} · 기존 재직 {cont_m:+g} · 퇴사·제외 −{excl_m:g} → {cur_yr}년 {end_m:g} ({prev_reg:.2f}명 → {cur_reg:.2f}명, {inc_diff:+.2f}명)`
    - 2줄(이름 최대 3명): `퇴사·제외 사원명 −월수` (4명 이상이면 `"외 N명"`으로 축약하고 전체 명단은 접힌 영역에 제공)
    """
    people = s.get("people") or {}
    recs = s.get("year_recs") or {}
    try:
        from .ui_common import _build_year_rows, _ctx
        _, comp_cur, tot_cur = _build_year_rows(s, cur_yr)
        _, comp_prev_raw, tot_prev = _build_year_rows(s, prev_yr)
    except Exception:
        comp_cur, tot_cur, comp_prev_raw, tot_prev = {}, {}, {}, {}

    comp_prev = dict(comp_prev_raw)
    nr_excl_items: list[tuple[str, float]] = []
    raw_prev_m = round(sum(float((comp_prev_raw.get(pid) or {}).get("row_sum") or 0.0) for pid in people), 2)
    if use_new_rule_prev and cur_yr >= H.NEW_TENURE_RULE_FROM and prev_yr >= H.NEW_TENURE_RULE_FROM - 1:
        try:
            from .ui_common import _ctx
            ctx_new = dict(_ctx(s, prev_yr), old_tenure_rule=False, as_of_year=cur_yr)
            recs_prev = recs.get(prev_yr) or {}
            for pid, c_old in list(comp_prev.items()):
                yrec = recs_prev.get(pid) or {}
                p_obj = people.get(pid) or {}
                if (
                    c_old.get("상시") == "O"
                    and "제외사유" not in (yrec.get("_user_set") or [])
                    and H.tenure_under_1y(p_obj, prev_yr, as_of_year=cur_yr)
                ):
                    c_re = H.compute_row(p_obj, yrec, prev_yr, ctx_new)
                    comp_prev[pid] = c_re
                    old_m = round(float(c_old.get("row_sum") or 0.0), 2)
                    new_m_v = round(float(c_re.get("row_sum") or 0.0), 2)
                    if old_m > new_m_v + 1e-6:
                        nm_p = str(p_obj.get("성명") or "").strip()
                        if nm_p:
                            nr_excl_items.append((nm_p, -(old_m - new_m_v)))
            nr_excl_items.sort(key=lambda x: (x[1], x[0]))
        except Exception:
            pass

    start_m_raw = sum(float((comp_prev.get(pid) or {}).get("row_sum") or 0.0) for pid in people)
    end_m_raw = sum(float((comp_cur.get(pid) or {}).get("row_sum") or 0.0) for pid in people)

    if prev_reg_override is not None:
        prev_reg = float(prev_reg_override)
    elif use_new_rule_prev and tot_prev.get("nr_상시_평균") is not None:
        prev_reg = float(tot_prev["nr_상시_평균"])
    else:
        prev_reg = float(tot_prev.get("상시_평균", tot_prev.get("b1_reg", 0.0)) or 0.0)

    if cur_reg_override is not None:
        cur_reg = float(cur_reg_override)
    else:
        cur_reg = float(tot_cur.get("상시_평균", tot_cur.get("b1_reg", 0.0)) or 0.0)

    start_m = round(start_m_raw, 2)
    end_m = round(end_m_raw, 2)

    new_m = 0.0
    cont_m = 0.0
    excl_m = 0.0

    new_items: list[tuple[str, float]] = []
    cont_items: list[tuple[str, float]] = []
    excl_items: list[tuple[str, float]] = []

    for pid, p in people.items():
        nm = str(p.get("성명") or "").strip()
        if not nm:
            continue
        h_dt = H.parse_date(p.get("입사일"))
        m_p = round(float((comp_prev.get(pid) or {}).get("row_sum") or 0.0), 2)
        m_c = round(float((comp_cur.get(pid) or {}).get("row_sum") or 0.0), 2)

        if m_p == 0.0 and m_c == 0.0:
            continue

        if m_p == 0.0 and m_c > 0.0 and (h_dt is None or h_dt.year == cur_yr):
            new_m = round(new_m + m_c, 2)
            new_items.append((nm, m_c))
        elif m_c < m_p - 1e-6:
            diff_neg = round(m_p - m_c, 2)
            excl_m = round(excl_m + diff_neg, 2)
            excl_items.append((nm, -diff_neg))
        else:
            diff_pos = round(m_c - m_p, 2)
            cont_m = round(cont_m + diff_pos, 2)
            if abs(diff_pos) > 1e-6:
                cont_items.append((nm, diff_pos))

    excl_items.sort(key=lambda x: (x[1], x[0]))
    new_items.sort(key=lambda x: (-x[1], x[0]))
    cont_items.sort(key=lambda x: (-abs(x[1]), x[0]))

    inc_diff = round(cur_reg - prev_reg, 2)
    inc_color = "#15803d" if inc_diff > 0 else ("#dc2626" if inc_diff < 0 else "#64748b")
    cont_color = "#2563eb" if cont_m >= 0 else "#dc2626"

    line1_html = (
        f"<div class='ec-bridge-line1'>"
        f"<span class='ec-br-yr'>{prev_yr}년 <b>{start_m:g}</b></span>"
        f"<span class='ec-br-arr'>→</span>"
        f"<span>신규 <b style='color:#15803d;'>+{new_m:g}</b></span>"
        f"<span class='ec-br-dot'>·</span>"
        f"<span>기존 재직 <b style='color:{cont_color};'>{cont_m:+g}</b></span>"
        f"<span class='ec-br-dot'>·</span>"
        f"<span>퇴사·제외 <b style='color:#dc2626;'>−{excl_m:g}</b></span>"
        f"<span class='ec-br-arr'>→</span>"
        f"<span class='ec-br-yr'>{cur_yr}년 <b>{end_m:g}</b></span>"
        f"<span class='ec-br-avg'>({prev_reg:.2f}명 → {cur_reg:.2f}명, "
        f"<b style='color:{inc_color};'>{inc_diff:+.2f}명</b>)</span>"
        f"</div>"
    )

    nr_suffix_html = ""
    if nr_excl_items:
        nr_top3 = nr_excl_items[:3]
        nr_rest = max(0, len(nr_excl_items) - 3)
        nr_parts = [f"{nm} <b style='color:#dc2626;'>−{abs(val):g}</b>" for nm, val in nr_top3]
        nr_tail = f" 외 {nr_rest}명" if nr_rest > 0 else ""
        nr_suffix_html = (
            f" &nbsp;<span style='color:#cbd5e1;'>|</span>&nbsp; "
            f"<span class='ec-br-tag'>1년미만 비교제외({prev_yr}년 {raw_prev_m:g}→{start_m:g})</span> "
            + ", ".join(nr_parts)
            + nr_tail
        )

    if excl_items:
        top3 = excl_items[:3]
        rest_cnt = max(0, len(excl_items) - 3)
        parts_html = [
            f"{nm} <b style='color:#dc2626;'>−{abs(val):g}</b>"
            for nm, val in top3
        ]
        tail_str = f" 외 {rest_cnt}명" if rest_cnt > 0 else ""
        line2_html = (
            f"<div class='ec-bridge-line2'>"
            f"<span class='ec-br-tag'>퇴사·제외</span> "
            + ", ".join(parts_html)
            + tail_str
            + nr_suffix_html
            + "</div>"
        )
    elif new_items:
        top3 = new_items[:3]
        rest_cnt = max(0, len(new_items) - 3)
        parts_html = [
            f"{nm} <b style='color:#15803d;'>+{val:g}</b>"
            for nm, val in top3
        ]
        tail_str = f" 외 {rest_cnt}명" if rest_cnt > 0 else ""
        line2_html = (
            f"<div class='ec-bridge-line2'>"
            f"<span class='ec-br-tag'>퇴사·제외 없음 · 신규입사</span> "
            + ", ".join(parts_html)
            + tail_str
            + "</div>"
        )
    else:
        line2_html = (
            "<div class='ec-bridge-line2'>"
            "<span class='ec-br-tag'>인원 변동</span> 신규 입사 및 퇴사·제외 변동 없음"
            "</div>"
        )

    return {
        "prev_yr": prev_yr,
        "cur_yr": cur_yr,
        "start_m": start_m,
        "end_m": end_m,
        "new_m": new_m,
        "cont_m": cont_m,
        "excl_m": excl_m,
        "prev_reg": prev_reg,
        "cur_reg": cur_reg,
        "inc_diff": inc_diff,
        "new_items": new_items,
        "cont_items": cont_items,
        "excl_items": excl_items,
        "has_overflow": len(excl_items) >= 4,
        "html": f"<div class='ec-bridge-box'>{line1_html}{line2_html}</div>",
    }


def _render_compact_bridge(
    bridge: dict[str, Any],
    *,
    between_tables: bool = False,
    force_expander: bool = False,
) -> None:
    """2줄 고정 길이 인원 증감 브리지 및 (4명 이상 시) 전체 명단 접힌 영역(expander)을 렌더링합니다."""
    margin_css = "16px 0 18px 0" if between_tables else "6px 0 12px 0"
    st.markdown(
        f"""
        <style>
        .ec-bridge-box {{
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-left: 3.5px solid #94a3b8;
            border-radius: 8px;
            padding: 8px 14px;
            margin: {margin_css};
            font-size: 0.86rem;
            line-height: 1.54;
            color: #64748b;
        }}
        .ec-bridge-line1 {{
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            gap: 6px;
            color: #64748b;
            font-weight: 500;
        }}
        .ec-bridge-line1 .ec-br-yr {{
            color: #475569;
        }}
        .ec-bridge-line1 .ec-br-arr {{
            color: #94a3b8;
            font-weight: 700;
        }}
        .ec-bridge-line1 .ec-br-dot {{
            color: #cbd5e1;
            font-weight: 800;
        }}
        .ec-bridge-line1 .ec-br-avg {{
            margin-left: 4px;
            color: #64748b;
        }}
        .ec-bridge-line2 {{
            margin-top: 2px;
            font-size: 0.83rem;
            color: #64748b;
        }}
        .ec-bridge-line2 .ec-br-tag {{
            font-weight: 600;
            color: #475569;
            margin-right: 4px;
        }}
        </style>
        """
        + bridge["html"],
        unsafe_allow_html=True,
    )
    excl_items = bridge.get("excl_items") or []
    new_items = bridge.get("new_items") or []
    cont_items = bridge.get("cont_items") or []
    if len(excl_items) >= 4 or force_expander:
        with st.expander(
            f"📋 {bridge['prev_yr']}년 → {bridge['cur_yr']}년 퇴사·제외 및 인원 증감 전체 명단 보기 "
            f"(퇴사·제외 {len(excl_items)}명 · 신규 {len(new_items)}명 · 기존재직 변동 {len(cont_items)}명)",
            expanded=False,
        ):
            lines_md = []
            if excl_items:
                excl_str = ", ".join(f"**{nm}** ({val:g})" for nm, val in excl_items)
                lines_md.append(f"- **퇴사·제외 ({len(excl_items)}명, 합계 −{bridge['excl_m']:g})**: {excl_str}")
            if new_items:
                new_str = ", ".join(f"**{nm}** (+{val:g})" for nm, val in new_items)
                lines_md.append(f"- **신규 입사 ({len(new_items)}명, 합계 +{bridge['new_m']:g})**: {new_str}")
            if cont_items:
                cont_str = ", ".join(f"**{nm}** ({val:+g})" for nm, val in cont_items)
                lines_md.append(f"- **기존 재직 월수 변동 ({len(cont_items)}명, 합계 {bridge['cont_m']:+g})**: {cont_str}")
            st.markdown("\n".join(lines_md))


def _build_filed_vs_recalc_data(s: dict, pkg: dict | None, tax_yr: int) -> dict[str, Any]:
    """
    [Section 5 & 6-2: 기신고 vs 세법상 재계산 비교 데이터 산출]
    - 재계산값도 2번 규칙(`R.calc_method_for`)으로 계산합니다.
    - 기신고값과 재계산값의 차이가 A·B 계산방식 차이로만 설명되는 경우 경정청구·수정신고를 안내하지 않고
      "계산방식(A/B) 차이 — 국세청 '26.3월 안내 기준 적용"으로 표시합니다.
    - 기신고서에서 2·3차년도 요건을 B방식 숫자로 계산한 경우, A방식으로 재계산해 요건 충족 여부가 달라지는지 표시합니다.
    - `_auto_filled` 플래그가 있는 연도는 "차이 없음" 대신 "신고서 미입력"으로 표시합니다.
    """
    totals_all = _ensure_totals_snapshot(s)
    if not isinstance(pkg, dict) or not pkg.get("cur_s"):
        b = s.get("biz") or {}
        corp_sz = _cohort_corp_size(s, tax_yr)
        cap_bool = H.is_capital_area(b.get("사업장소재지", ""))
        is_cap = True if cap_bool is None else bool(cap_bool)
        ps = s.get("prev_summary") or {}
        p1_f = ps.get(str(tax_yr - 1)) or {}
        p2_f = ps.get(str(tax_yr - 2)) or {}
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

    ps = s.get("prev_summary") or {}
    ext_pf = ((s.get("ext") or {}).get("prev_filing") or {}).get("연도별") or {}
    y1 = tax_yr - 1
    y2 = tax_yr - 2
    t_y1 = totals_all.get(y1) or {}
    t_y2 = totals_all.get(y2) or {}
    t_cur = totals_all.get(tax_yr) or {}

    f_merged = {}
    if isinstance(ext_pf.get(str(y1)), dict):
        f_merged.update(ext_pf[str(y1)])
    if isinstance(ps.get(str(y1)), dict):
        for k, v in ps[str(y1)].items():
            if v is not None:
                f_merged[k] = v

    auto_filled_y1 = bool((ps.get(str(y1)) or {}).get("_auto_filled") or f_merged.get("_auto_filled"))
    has_real_filing_y1 = (not auto_filled_y1) and (
        f_merged.get("상시") is not None or f_merged.get("공제세액") is not None
    )

    pm1_f = pkg.get("pm_y1_filed") or {}
    pm1_r = pkg.get("pm_y1_recalc") or {}

    # 2번 규칙(calc_method_for)에 따른 y1 재계산값 선택 및 A·B 두 값 추출
    m_y1 = R.calc_method_for(y1, eval_year=y1)
    a_reg_y1 = float(t_y1.get("A_상시_평균", t_y1.get("A_b1_reg", t_y1.get("상시_평균", 0.0))) or 0.0)
    a_yth_y1 = float(t_y1.get("A_청년등_평균", t_y1.get("A_b1_yth", t_y1.get("청년등_평균", 0.0))) or 0.0)
    b_reg_y1 = float(t_y1.get("B_상시_평균", t_y1.get("B_b1_reg", t_y1.get("b4_reg", a_reg_y1))) or 0.0)
    b_yth_y1 = float(t_y1.get("B_청년등_평균", t_y1.get("B_b1_yth", t_y1.get("b4_yth", a_yth_y1))) or 0.0)

    recalc_reg = round(b_reg_y1 if m_y1 == "B" else a_reg_y1, 2)
    recalc_yth = round(b_yth_y1 if m_y1 == "B" else a_yth_y1, 2)
    recalc_gen = round(max(0.0, recalc_reg - recalc_yth), 2)

    f_reg = float(f_merged.get("상시")) if f_merged.get("상시") is not None else float(pm1_f.get("init_reg") or recalc_reg)
    f_yth = float(f_merged.get("청년등")) if f_merged.get("청년등") is not None else float(pm1_f.get("init_yth") or recalc_yth)
    f_gen = round(max(0.0, f_reg - f_yth), 2)

    f_yi = float(pm1_f.get("init_yth_inc") or 0.0)
    f_gi = float(pm1_f.get("init_gen_inc") or 0.0)
    f_ti = round(f_yi + f_gi, 2)

    r_yi = float(pm1_r.get("init_yth_inc") or 0.0)
    r_gi = float(pm1_r.get("init_gen_inc") or 0.0)
    r_ti = round(r_yi + r_gi, 2)

    c1_filed = int(f_merged.get("공제세액") if f_merged.get("공제세액") is not None else (pm1_f.get("continued_credit_won") or 0))
    c1_recalc = int(pm1_r.get("continued_credit_won") or 0)
    diff_c1 = c1_recalc - c1_filed

    c2_filed = int(pm1_f.get("continued_credit_won") or 0) - int(pm1_f.get("clawback_net_payable_won") or 0)
    c2_recalc = int(pm1_r.get("continued_credit_won") or 0) - int(pm1_r.get("clawback_net_payable_won") or 0)
    diff_c2 = c2_recalc - c2_filed

    corp_sz_y1 = _cohort_corp_size(s, y1)
    diff_c3 = diff_c1 if corp_sz_y1 not in ("일반기업", "대기업") else 0

    diff_reg = round(recalc_reg - f_reg, 2)
    diff_yth = round(recalc_yth - f_yth, 2)
    diff_gen = round(recalc_gen - f_gen, 2)

    # [Section 5] A·B 계산방식 차이 진단 (이 차이만으로 설명되면 경정청구·수정신고 미안내)
    a_prev_reg = float(t_y2.get("A_상시_평균", t_y2.get("상시_평균", 0.0)) or 0.0) if t_y2.get("has_data") else None
    a_prev_yth = float(t_y2.get("A_청년등_평균", t_y2.get("청년등_평균", 0.0)) or 0.0) if t_y2.get("has_data") else None
    b_prev_reg = float(t_y2.get("B_상시_평균", t_y2.get("b4_reg", a_prev_reg or 0.0)) or 0.0) if t_y2.get("has_data") else None
    b_prev_yth = float(t_y2.get("B_청년등_평균", t_y2.get("b4_yth", a_prev_yth or 0.0)) or 0.0) if t_y2.get("has_data") else None
    f_prev_d = ps.get(str(y2)) or {}
    f_prev_reg = float(f_prev_d["상시"]) if f_prev_d.get("상시") is not None else None
    f_prev_yth = float(f_prev_d["청년등"]) if f_prev_d.get("청년등") is not None else None

    ab_diag = R.diagnose_ab_method_difference(
        cohort_year=y1,
        filed_reg=f_reg,
        filed_yth=f_yth,
        recalc_reg=recalc_reg,
        recalc_yth=recalc_yth,
        a_reg=a_reg_y1,
        a_yth=a_yth_y1,
        b_reg=b_reg_y1,
        b_yth=b_yth_y1,
        filed_prev_reg=f_prev_reg,
        filed_prev_yth=f_prev_yth,
        a_prev_reg=a_prev_reg,
        a_prev_yth=a_prev_yth,
        b_prev_reg=b_prev_reg,
        b_prev_yth=b_prev_yth,
    )
    is_only_ab_diff = bool(ab_diag.get("is_only_ab_method_diff"))

    # [Section 5] 기신고서에서 2·3차년도 요건(2024년 이하 코호트)을 B방식 숫자로 계산한 경우,
    # A방식으로 재계산해 요건 충족 여부가 달라지는지 판정
    req_23_checks: list[dict[str, Any]] = []
    for coh_y, nth_lbl, eval_y, blk_prefix in (
        (y1, "2차년도(1차 사후관리)", tax_yr, "b2"),
        (y2, "3차년도(2차 사후관리)", tax_yr, "b3"),
    ):
        if R.calc_method_for(coh_y, eval_year=eval_y) != "A":
            continue
        t_coh = totals_all.get(coh_y) or {}
        if not t_coh.get("has_data") or not t_cur.get("has_data"):
            continue
        a_init_r = round(float(t_coh.get("A_b1_reg", t_coh.get("상시_평균", 0.0)) or 0.0), 2)
        a_init_y = round(float(t_coh.get("A_b1_yth", t_coh.get("청년등_평균", 0.0)) or 0.0), 2)
        b_init_r = round(float(t_coh.get("B_b1_reg", t_coh.get("b4_reg", a_init_r)) or 0.0), 2)
        b_init_y = round(float(t_coh.get("B_b1_yth", t_coh.get("b4_yth", a_init_y)) or 0.0), 2)

        a_eval_r = round(float(t_cur.get(f"A_{blk_prefix}_reg", t_cur.get(f"{blk_prefix}_reg", 0.0)) or 0.0), 2)
        a_eval_y = round(float(t_cur.get(f"A_{blk_prefix}_yth", t_cur.get(f"{blk_prefix}_yth", 0.0)) or 0.0), 2)
        b_eval_r = round(float(t_cur.get(f"B_{blk_prefix}_reg", t_cur.get(f"{blk_prefix}_reg", 0.0)) or 0.0), 2)
        b_eval_y = round(float(t_cur.get(f"B_{blk_prefix}_yth", t_cur.get(f"{blk_prefix}_yth", 0.0)) or 0.0), 2)

        b_maintained = (b_eval_r >= b_init_r - 1e-9) and (b_eval_y >= b_init_y - 1e-9)
        a_maintained = (a_eval_r >= a_init_r - 1e-9) and (a_eval_y >= a_init_y - 1e-9)
        changed = (b_maintained != a_maintained)
        req_23_checks.append({
            "cohort_year": coh_y,
            "nth_label": nth_lbl,
            "eval_year": eval_y,
            "a_init_reg": a_init_r, "a_init_yth": a_init_y,
            "a_eval_reg": a_eval_r, "a_eval_yth": a_eval_y,
            "b_init_reg": b_init_r, "b_init_yth": b_init_y,
            "b_eval_reg": b_eval_r, "b_eval_yth": b_eval_y,
            "b_maintained": b_maintained,
            "a_maintained": a_maintained,
            "requirement_changed": changed,
        })

    if not has_real_filing_y1:
        cause_line = (
            f"{y1}년 기신고 공제세액계산서(별지 제10호의9)가 입력되지 않았거나 사원표 재계산값이 임시 입력된 상태입니다(신고서 확인 필요)."
        )
    elif abs(diff_reg) < 0.01 and abs(diff_yth) < 0.01 and abs(diff_c1) < 10:
        cause_line = (
            f"{y1}년 기신고 상시근로자 수 및 공제세액이 국세청 '26.3월 안내 기준({R.calc_method_badge_label(y1)}) 재계산 결과와 일치합니다."
        )
    elif is_only_ab_diff:
        cause_line = (
            f"계산방식(A/B) 차이 — 국세청 '26.3월 안내 기준 적용 ({ab_diag.get('detail')}). "
            f"A·B 계산방식 차이로만 설명되므로 경정청구·수정신고 대상이 아닙니다."
        )
    else:
        cause_line = (
            f"{y1}년 기신고 인원({f_reg:.2f}명)과 원천징수부 기반 세법상 재계산({R.calc_method_badge_label(y1)}) 인원({recalc_reg:.2f}명) 간 차이({diff_reg:+.2f}명)가 발생했습니다."
        )

    return {
        "y1": y1,
        "tax_yr": tax_yr,
        "cohort_corp_size": corp_sz_y1,
        "calc_method": m_y1,
        "calc_method_badge": R.calc_method_badge_label(y1),
        "auto_filled": auto_filled_y1,
        "has_real_filing": has_real_filing_y1,
        "is_only_ab_method_diff": is_only_ab_diff,
        "ab_diag": ab_diag,
        "req_23_checks": req_23_checks,
        "a_reg": round(a_reg_y1, 2), "a_yth": round(a_yth_y1, 2),
        "b_reg": round(b_reg_y1, 2), "b_yth": round(b_yth_y1, 2),
        "f_reg": f_reg, "recalc_reg": recalc_reg, "diff_reg": diff_reg,
        "f_yth": f_yth, "recalc_yth": recalc_yth, "diff_yth": diff_yth,
        "f_gen": f_gen, "recalc_gen": recalc_gen, "diff_gen": diff_gen,
        "f_ti": f_ti, "r_ti": r_ti, "diff_ti": round(r_ti - f_ti, 2),
        "f_yi": f_yi, "r_yi": r_yi, "diff_yi": round(r_yi - f_yi, 2),
        "f_gi": f_gi, "r_gi": r_gi, "diff_gi": round(r_gi - f_gi, 2),
        "c1_filed": c1_filed, "c1_recalc": c1_recalc, "diff_c1": diff_c1,
        "c2_filed": c2_filed, "c2_recalc": c2_recalc, "diff_c2": diff_c2,
        "diff_c3": diff_c3,
        "cause_line": cause_line,
        "prev_compare_reg": float((pkg.get("prev_s") or {}).get("regular") or 0.0),
    }


def _render_filed_vs_recalc_comparison_body(s: dict, pkg: dict | None, tax_yr: int) -> None:
    d = _build_filed_vs_recalc_data(s, pkg, tax_yr)
    y1 = d["y1"]
    diff_c1 = d["diff_c1"]
    diff_c2 = d["diff_c2"]
    diff_c3 = d["diff_c3"]
    net_factor = 1.0 - R.RURAL_SPECIAL_TAX_RATE
    tot_2yr_gross = diff_c1 + diff_c2
    tot_2yr_net = int(round(tot_2yr_gross * net_factor))
    c1_net = int(round(diff_c1 * net_factor))
    c2_net = int(round(diff_c2 * net_factor))
    c3_net = int(round(diff_c3 * net_factor))

    # [6-2] 사원표 재계산값 임시 입력(_auto_filled) 또는 기신고서 미입력 시 주황 배지 및 '신고서 미입력' 표시
    if d.get("auto_filled") or not d.get("has_real_filing"):
        st.markdown(
            "<div style='margin-bottom:8px;padding:8px 12px;background:#fff7ed;border:1.5px solid #fdba74;"
            "border-left:5px solid #f97316;border-radius:8px;font-size:0.86rem;font-weight:800;color:#c2410c;'>"
            "🟧 사원표 재계산값 임시 입력 · 신고서 확인 필요"
            "</div>",
            unsafe_allow_html=True,
        )
        badge_html = "<span style='background:#ffedd5;color:#c2410c;border:1px solid #fdba74;padding:3px 10px;border-radius:999px;font-weight:800;font-size:0.84rem;'>🟧 신고서 미입력 (사원표 재계산값 임시 입력 · 신고서 확인 필요)</span>"
        card_bg, card_bd, val_color = "#fff7ed", "#fdba74", "#c2410c"
        action_lbl = f"{y1}년 1차 세액 차이 (신고서 미입력)"
        guide_line_txt = "안내: 기신고 공제세액계산서(별지 제10호의9) 원문을 확인하여 실제 기신고 수치를 입력해 주세요."
        row1_label = f"{y1}년 1차 (신고서 미입력)"
        row2_label = f"{tax_yr}년 2차"
    elif d.get("is_only_ab_method_diff"):
        # [Section 5] 기신고값과 재계산값의 차이가 A·B 계산방식 차이로만 설명되는 경우 경정청구·수정신고 미안내
        badge_html = "<span style='background:#e0f2fe;color:#0369a1;border:1px solid #7dd3fc;padding:3px 10px;border-radius:999px;font-weight:800;font-size:0.84rem;'>🟦 계산방식(A/B) 차이 — 국세청 '26.3월 안내 기준 적용</span>"
        card_bg, card_bd, val_color = "#f0f9ff", "#7dd3fc", "#0369a1"
        action_lbl = f"{y1}년 1차 계산방식(A/B) 단수 차이"
        guide_line_txt = "계산방식(A/B) 차이 — 국세청 '26.3월 안내 기준 적용 (단순 계산방식 차이이므로 별도 안내 대상 아님)"
        row1_label = f"{y1}년 1차 (계산방식 A/B 차이)"
        row2_label = f"{tax_yr}년 2차"
    elif diff_c1 > 0 or tot_2yr_gross > 0:
        badge_html = "<span style='background:#dbeafe;color:#1d4ed8;border:1px solid #93c5fd;padding:3px 10px;border-radius:999px;font-weight:800;font-size:0.84rem;'>🟦 경정청구 가능 (재계산 유리)</span>"
        card_bg, card_bd, val_color = "#eff6ff", "#93c5fd", "#1d4ed8"
        action_lbl = f"{y1}년 1차 경정청구 환급 예상액"
        guide_line_txt = f"청구기한: 법정신고기한 경과 후 5년 이내 (국세기본법 제45조의2 · 12월 결산법인 {y1}년분은 {y1+6}.03.31.까지)"
        row1_label = f"{y1}년 1차 (경정 대상)"
        row2_label = f"{tax_yr}년 2차 ({y1}년 경정청구와 함께 반영)"
    elif diff_c1 < 0 or tot_2yr_gross < 0:
        badge_html = "<span style='background:#fee2e2;color:#b91c1c;border:1px solid #fca5a5;padding:3px 10px;border-radius:999px;font-weight:800;font-size:0.84rem;'>🟥 수정신고 필요 (기신고 과다)</span>"
        card_bg, card_bd, val_color = "#fef2f2", "#fca5a5", "#dc2626"
        action_lbl = f"{y1}년 1차 수정신고 추가납부 예상액"
        guide_line_txt = "신고안내: 법정신고기한 경과 후 수정신고 대상 (국세기본법 제45조 · 과소신고 가산세 감면은 수정신고 시기에 따라 달라짐, 국세기본법 제48조 제2항)"
        row1_label = f"{y1}년 1차 (수정신고 대상)"
        row2_label = f"{tax_yr}년 2차 ({y1}년 수정신고와 함께 반영)"
    else:
        badge_html = "<span style='background:#f1f5f9;color:#475569;border:1px solid #cbd5e1;padding:3px 10px;border-radius:999px;font-weight:800;font-size:0.84rem;'>⬜ 차이 없음 (기신고·재계산 일치)</span>"
        card_bg, card_bd, val_color = "#f8fafc", "#cbd5e1", "#334155"
        action_lbl = f"{y1}년 1차 세액 차이"
        guide_line_txt = f"적용 방식: {d.get('calc_method_badge')} — 기신고 내역과 세법상 재계산 결과 일치"
        row1_label = f"{y1}년 1차"
        row2_label = f"{tax_yr}년 2차"

    # ① 상단 결론 카드
    st.markdown(
        f"<div style='background:{card_bg};border:1.5px solid {card_bd};border-radius:10px;padding:12px 16px;margin-bottom:10px;'>"
        f"<div style='display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;margin-bottom:8px;'>"
        f"{badge_html}"
        f"<span style='font-size:0.80rem;color:#475569;font-weight:600;'>{guide_line_txt}</span>"
        f"</div>"
        f"<div style='display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;'>"
        f"<div style='background:#ffffff;border:1px solid #e2e8f0;border-radius:8px;padding:8px 12px;'>"
        f"<div style='font-size:0.78rem;color:#64748b;font-weight:700;'>① {action_lbl}</div>"
        f"<div style='font-size:1.18rem;font-weight:900;color:{val_color};margin-top:2px;'>세전 {diff_c1:+,}원 <span style='font-size:0.86rem;font-weight:700;color:#475569;'>(농특세 20% 반영 후 순액 {c1_net:+,}원)</span></div>"
        f"</div>"
        f"<div style='background:#ffffff;border:1px solid #e2e8f0;border-radius:8px;padding:8px 12px;'>"
        f"<div style='font-size:0.78rem;color:#64748b;font-weight:700;'>② {y1}년(1차) + {tax_yr}년(2차) 합산 세액 차이</div>"
        f"<div style='font-size:1.18rem;font-weight:900;color:{val_color};margin-top:2px;'>세전 {tot_2yr_gross:+,}원 <span style='font-size:0.86rem;font-weight:700;color:#475569;'>(농특세 20% 반영 후 순액 {tot_2yr_net:+,}원)</span></div>"
        f"</div>"
        f"</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

    # ② 한 줄 원인 + 참고 A/B값
    st.markdown(
        f"<div style='background:#f8fafc;border-left:3.5px solid #475569;padding:7px 12px;border-radius:6px;font-size:0.85rem;color:#334155;margin-bottom:10px;'>"
        f"<b>핵심 원인 ({d.get('calc_method_badge')}):</b> {d['cause_line']}"
        f"<br><span style='font-size:0.79rem;color:#64748b;'>참고({y1}년 인원): A방식(합계 절사) 상시 {d['a_reg']:.2f}명·청년등 {d['a_yth']:.2f}명 / B방식(사원별 절사) 상시 {d['b_reg']:.2f}명·청년등 {d['b_yth']:.2f}명</span>"
        f"</div>",
        unsafe_allow_html=True,
    )

    # [Section 5] 기신고서에서 2·3차년도 요건을 B방식 숫자로 계산한 경우, A방식으로 재계산해 요건 충족 여부가 달라지는지 표시
    req_23_checks = d.get("req_23_checks") or []
    if req_23_checks:
        chk_lines = []
        for rc in req_23_checks:
            c_yr = rc["cohort_year"]
            n_lbl = rc["nth_label"]
            b_st = "요건 충족(유지·증가)" if rc["b_maintained"] else "요건 미충족(감소)"
            a_st = "요건 충족(유지·증가)" if rc["a_maintained"] else "요건 미충족(감소)"
            chg_badge = (
                "<span style='color:#dc2626;font-weight:800;'>⚠️ B→A 재계산 시 요건 충족 여부 변동됨!</span>"
                if rc["requirement_changed"]
                else "<span style='color:#15803d;font-weight:800;'>✓ B→A 재계산 시에도 요건 충족 여부 동일</span>"
            )
            chk_lines.append(
                f"• <b>{c_yr}년 귀속분 {n_lbl} (국세청 '26.3월 안내상 A방식[신뢰보호] 적용 대상)</b>: "
                f"B방식 숫자({rc['b_init_reg']:.2f}→{rc['b_eval_reg']:.2f}명, 청년 {rc['b_init_yth']:.2f}→{rc['b_eval_yth']:.2f}명: {b_st}) vs "
                f"A방식 재계산({rc['a_init_reg']:.2f}→{rc['a_eval_reg']:.2f}명, 청년 {rc['a_init_yth']:.2f}→{rc['a_eval_yth']:.2f}명: {a_st}) → {chg_badge}"
            )
        st.markdown(
            "<div style='background:#f8fafc;border:1px solid #cbd5e1;border-left:4px solid #0284c7;padding:8px 12px;border-radius:7px;font-size:0.83rem;color:#1e293b;margin-bottom:10px;line-height:1.55;'>"
            "<b>📐 [2·3차년도 사후관리 요건 B방식 → A방식(신뢰보호) 재계산 점검]</b><br>"
            + "<br>".join(chk_lines)
            + "</div>",
            unsafe_allow_html=True,
        )

    # ③ 표 1 — 인원 비교 (구분 | 기신고 | 재계산 | 차이)
    st.markdown(f"**표 1 — {y1}년 귀속({R.format_corp_size_label(d.get('cohort_corp_size'))} · {d.get('calc_method_badge')}) 상시근로자 및 고용증가 인원 비교**")
    hc_df = pd.DataFrame(
        [
            {
                "구분": "전체 상시근로자 (증가인원)",
                "기신고": f"{d['f_reg']:.2f}명 ({d['f_ti']:+.2f}명)",
                "재계산": f"{d['recalc_reg']:.2f}명 ({d['r_ti']:+.2f}명)",
                "차이": f"{d['diff_reg']:+.2f}명 ({d['diff_ti']:+.2f}명)",
            },
            {
                "구분": "청년등 상시근로자 (증가인원)",
                "기신고": f"{d['f_yth']:.2f}명 ({d['f_yi']:+.2f}명)",
                "재계산": f"{d['recalc_yth']:.2f}명 ({d['r_yi']:+.2f}명)",
                "차이": f"{d['diff_yth']:+.2f}명 ({d['diff_yi']:+.2f}명)",
            },
            {
                "구분": "청년등 외 상시근로자 (증가인원)",
                "기신고": f"{d['f_gen']:.2f}명 ({d['f_gi']:+.2f}명)",
                "재계산": f"{d['recalc_gen']:.2f}명 ({d['r_gi']:+.2f}명)",
                "차이": f"{d['diff_gen']:+.2f}명 ({d['diff_gi']:+.2f}명)",
            },
        ]
    )
    st.dataframe(hc_df, width="stretch", hide_index=True)

    # ④ 표 2 — 세액 비교
    st.markdown("**표 2 — 연차별 공제세액 비교**")
    tx_df = pd.DataFrame(
        [
            {
                "귀속연도 · 차수": row1_label,
                "기신고": f"{d['c1_filed']:,}원",
                "재계산": f"{d['c1_recalc']:,}원",
                "차이": f"{diff_c1:+,}원 (농특세 차감 후 순액 {c1_net:+,}원)",
            },
            {
                "귀속연도 · 차수": row2_label,
                "기신고": f"{d['c2_filed']:,}원",
                "재계산": f"{d['c2_recalc']:,}원",
                "차이": f"{diff_c2:+,}원 (농특세 차감 후 순액 {c2_net:+,}원)",
            },
        ]
    )
    st.dataframe(tx_df, width="stretch", hide_index=True)
    st.caption(
        f"📌 **{tax_yr+1}년 3차 (향후 연속공제 차이 예상):** 세전 **{diff_c3:+,}원** "
        f"(농특세 20% 차감 후 순액 **{c3_net:+,}원**) — {tax_yr+1}년 상시근로자 수가 {y1}년 최초 공제연도 인원 이상으로 유지될 때 실현됩니다."
    )

    if not d.get("is_only_ab_method_diff"):
        with st.expander("ℹ️ 비교 검토 유의사항 및 법령 원문 바로가기", expanded=False):
            st.markdown(
                f"- **당해({tax_yr}년) 1차 신규공제 비교인원과의 비연동 (상충관계 없음):** `{tax_yr}년` 신규공제 산정에 사용한 직전연도(`{y1}년`) 비교 인원(**{d['prev_compare_reg']:.2f}명**)은 신법 기준(실제 근로기간 1년 미만 퇴사자 제외 · B방식)으로 별도 재산정한 값입니다.\n"
                f"- **농어촌특별세(20%) 동시 반영:** 조세특례제한법상 통합고용세액공제 세액 변동 시 농어촌특별세법 제5조 제1항 제1호에 따라 감면세액의 20%에 해당하는 농어촌특별세를 함께 반영해야 합니다.\n"
                f"- **관련 법령 원문 직링크:** "
                f"[조세특례제한법 시행령 제26조의8 제6항](https://www.law.go.kr/법령/조세특례제한법시행령/제26조의8) · "
                f"[조세특례제한법 시행령 제11조의2 제8항](https://www.law.go.kr/법령/조세특례제한법시행령/제11조의2)"
            )


if hasattr(st, "dialog"):
    @st.dialog("⚖️ 기신고 vs 세법상 재계산 비교", width="large")
    def _dlg_filed_vs_recalc_comparison(s: dict, pkg: dict | None, tax_yr: int) -> None:
        _render_filed_vs_recalc_comparison_body(s, pkg, tax_yr)
else:
    def _dlg_filed_vs_recalc_comparison(s: dict, pkg: dict | None, tax_yr: int) -> None:
        _render_filed_vs_recalc_comparison_body(s, pkg, tax_yr)


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
    [6-4] 총괄표(4개 과세연도 요약표) 정합성 보정:
    - 과거 연도 1차 공제액의 '추정복원(다른 연도의 연속공제 금액으로 거꾸로 채우는 로직)'을 폐지합니다.
    - 세액공제조정명세서(법인세법 시행규칙 별지 제8호서식 부표3)나 기신고서에서 1차 공제액을 읽을 수 없으면
      빈칸(`r1_needs_check = True`)으로 두고 '신고서 확인 필요'로 표시합니다.
    - T-3 이전 과세연도(2021·2022년) 귀속분 사후관리에 해당하는 T-3의 2·3차 및 T-2의 3차 칸이 0원(검토범위 외)인 경우
      `r2_na` / `r3_na` 플래그를 부여하여 '0원' 대신 '-' (대상외)로 표시합니다.
    """
    if len(yr_list) >= 3:
        y0, y1, y2 = yr_list[0], yr_list[1], yr_list[2]
        m0 = matrix_cols.get(y0)
        m1 = matrix_cols.get(y1)
        m2 = matrix_cols.get(y2)
        if isinstance(m0, dict) and isinstance(m1, dict) and isinstance(m2, dict):
            if int(m0.get("r1_credit") or 0) == 0 and int(m0.get("r1_claw") or 0) == 0:
                if int(m1.get("r2_credit") or 0) > 0 or int(m2.get("r3_credit") or 0) > 0:
                    m0["r1_needs_check"] = True
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
            f"{cohort_year}년 귀속분 기신고 기초자료 미입력 ({pm.get('case_code', '기초값 없음 — 사후관리 계산 보류')})",
            [
                f"• [발생 사유] 현재 『📋 기신고 서식 숫자 기준』 모드이나, {cohort_year}년 최초 공제연도의 기신고 인원·증가인원·공제세액 기초값이 비어 있어 사후관리 계산이 0원으로 보류된 상태입니다.",
                f"• [해결 방법] 바로 아래 초록색 『🔄 {cohort_year}년 사원표 재계산 값을 기신고 기초값에 바로 반영』 버튼을 누르면 2단계 사원표 계산값이 1클릭으로 입력되어 즉시 산출됩니다. (또는 상단 계산 기준을 『⚖️ 2단계 사원표(세법원칙) 기준 계산』으로 전환하세요.)",
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
        if pm.get("period_expired") or "공제기간 종료" in str(pm.get("case_code") or ""):
            return (
                f"{cohort_year}년 귀속분 {nth_label} — {pm.get('case_code', '공제기간 종료(일반기업 2년)')}",
                [
                    f"• {pm.get('formula_note') or f'{cohort_year}년 귀속분은 최초 공제연도 기업규모가 일반기업(대기업)이므로 공제기간 종료(일반기업 2년) 및 사후관리 기간(1년)이 만료되었습니다.'}",
                    f"• 산식: 공제기간 종료(일반기업 2년) → {nth_label} 연속공제 0원 · 사후관리 대상 아님",
                ],
                "공제기간 종료(일반기업 2년)",
                0,
                False,
            )
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
    tax_yr = int(pkg.get("tax_year") or R.DEFAULT_TAX_YEAR)
    corp_size = _cohort_corp_size(s, tax_yr, pkg.get("corp_size") or "중소기업")
    coh1_sz_pdf = _cohort_corp_size(s, tax_yr - 1, corp_size)
    coh2_sz_pdf = _cohort_corp_size(s, tax_yr - 2, corp_size)
    corp_sz_summary_pdf = R.format_corp_size_summary_text(s, [tax_yr - 3, tax_yr - 2, tax_yr - 1, tax_yr])
    is_capital = bool(pkg.get("is_capital", True))
    loc_label = "수도권" if is_capital else "수도권 외(비수도권)"
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
                f"사업자등록번호: {biz_no}  |  기업규모·소재지: {corp_sz_summary_pdf} · {loc_label}  |  "
                f"적용 기준: {basis_lbl}  |  단위: 원 (추가납부세액은 - 표시)"
            ),
            st_sub,
        )
    )

    # 1) 상단 4개년 요약 매트릭스 표
    yr_list = [tax_yr - 3, tax_yr - 2, tax_yr - 1, tax_yr]
    matrix_cols = _enrich_matrix_cols_with_cohort_consistency(matrix_cols, yr_list)
    story.append(Paragraph(_pdf_text(f"■ 연도별 통합고용세액공제 요약표 ({corp_sz_summary_pdf} · {loc_label})"), st_sec))

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
        ["구분", "차수", *[f"{y}년 ({R.format_corp_size_label(_cohort_corp_size(s, y, corp_size), short=True)})" + (" [당해]" if y == tax_yr else "") for y in yr_list]],
        ["세액공제액\n(추가납부세액)", "1차", *[_cell_str(matrix_cols[y]["r1_credit"], matrix_cols[y]["r1_claw"], bool(matrix_cols[y].get("r1_na")), bool(matrix_cols[y].get("r1_needs_check"))) for y in yr_list]],
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
        f"(2) 1차년도 세액공제액 계산 ({tax_yr}년 귀속 · {R.format_corp_size_label(corp_size)}, {loc_label})",
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
        rates_legacy=H.get_unit_rates(coh1_sz_pdf, _cohort_capital(s, tax_yr - 1, is_capital), scheme="legacy", retention_year=1),
        cohort_is_capital=_cohort_capital(s, tax_yr - 1, is_capital),
        cur_is_capital=is_capital,
    )
    _add_calc_card(
        f"(3) 2차년도 사후관리 계산 ({tax_yr - 1}년 귀속 · {R.format_corp_size_label(coh1_sz_pdf)} → {tax_yr}년 1차 사후관리)",
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
        rates_legacy=H.get_unit_rates(coh2_sz_pdf, _cohort_capital(s, tax_yr - 2, is_capital), scheme="legacy", retention_year=1),
        cohort_is_capital=_cohort_capital(s, tax_yr - 2, is_capital),
        cur_is_capital=is_capital,
    )
    _add_calc_card(
        f"(4) 3차년도 사후관리 계산 ({tax_yr - 2}년 귀속 · {R.format_corp_size_label(coh2_sz_pdf)} → {tax_yr}년 2차 사후관리)",
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
                "제6항(제11조의2 제8항 준용) 및 국세청 '26.3월 안내(2025년 이후 코호트 B방식[사원별 절사] · 2024년 이하 코호트 A방식[합계 절사·신뢰보호] 이원화 및 별지 제10호의10서식 ⑩ = ② − ⑨ 청년등 외 차감 산정)·제8항 및 제23조 제13항 준용(포괄양수·고용승계 특례)·대통령령 제35999호 부칙 제2조·제36127호 부칙 제11조 경과조치, "
                "조세특례제한법 제132조(최저한세)·제144조(이월공제 10년 및 미공제 이월세액 우선 차감), 농어촌특별세법 제5조 제1항(실제 감면세액의 20%)."
            ),
            st_sub,
        )
    )

    doc.build(story)
    return buf.getvalue()



def _build_prior_new_law_recalc_warnings(
    s: dict,
    tax_yr: int,
    corp_size: str,
    is_capital: bool,
    totals_all: dict[int, dict[str, Any]],
    ps: dict[str, Any],
) -> list[str]:
    """
    [다년도(2027·2028년) 계산 시 직전·전전 신법 과세연도(2026년 이후) 사후 재산정 경고 생성기]
    - 조건: 직전·전전 비교연도(y >= 2026)의 재산정 비교인원(nr_상시_평균)이 그 연도의 당해 신고 인원(상시_평균 또는 기신고 상시)과 다를 때
    - 문구: “○○년 인원이 신고 당시 ○○명 → 재산정 ○○명으로 변경됨 (1년 미만 퇴사 확정). ○○년 공제액 차이 ○○원, 수정신고 여부 검토 필요”
    """
    warnings_out: list[str] = []
    if int(tax_yr) <= H.NEW_TENURE_RULE_FROM:
        return warnings_out

    for y_chk in range(H.NEW_TENURE_RULE_FROM, int(tax_yr)):
        t_y = totals_all.get(y_chk) or {}
        if not t_y.get("has_data"):
            continue
        nr_reg = t_y.get("nr_상시_평균")
        if nr_reg is None:
            continue
        recalc_reg = round(float(nr_reg), 2)
        recalc_yth = round(float(t_y.get("nr_청년등_평균", t_y.get("청년등_평균", 0.0)) or 0.0), 2)
        recalc_gen = round(max(0.0, recalc_reg - recalc_yth), 2)

        f_y = (ps or {}).get(str(y_chk)) or {}
        orig_reg = round(float(f_y["상시"] if f_y.get("상시") is not None else (t_y.get("상시_평균", t_y.get("b1_reg", 0.0)) or 0.0)), 2)
        orig_yth = round(float(f_y["청년등"] if f_y.get("청년등") is not None else (t_y.get("청년등_평균", t_y.get("b1_yth", 0.0)) or 0.0)), 2)
        orig_gen = round(max(0.0, orig_reg - orig_yth), 2)

        if abs(recalc_reg - orig_reg) < 0.01 and abs(recalc_yth - orig_yth) < 0.01:
            continue

        coh_cap = _cohort_capital(s, y_chk, is_capital)
        sim_orig = dict(totals_all)
        sim_orig[y_chk] = dict(t_y, 상시_평균=orig_reg, 청년등_평균=orig_yth, 청년외_평균=orig_gen)
        sim_recalc = dict(totals_all)
        sim_recalc[y_chk] = dict(t_y, 상시_평균=recalc_reg, 청년등_평균=recalc_yth, 청년외_평균=recalc_gen)

        try:
            ychk_sz = _cohort_corp_size(s, y_chk, corp_size)
            sz_map_w = R.get_corp_size_map(s)
            res_orig = H.calculate_tax_year_package(
                tax_year=y_chk,
                corp_size=ychk_sz,
                is_capital=coh_cap,
                summaries=sim_orig,
                prior_filings={},
                additional_inputs={},
                scheme_2026="new_2026",
                pm_basis=R.PM_BASIS_FILED,
                corp_size_by_year=sz_map_w,
            )
            res_recalc = H.calculate_tax_year_package(
                tax_year=y_chk,
                corp_size=ychk_sz,
                is_capital=coh_cap,
                summaries=sim_recalc,
                prior_filings={},
                additional_inputs={},
                scheme_2026="new_2026",
                pm_basis=R.PM_BASIS_FILED,
                corp_size_by_year=sz_map_w,
            )
            orig_won = int(f_y["공제세액"]) if f_y.get("공제세액") is not None else int(res_orig.get("cur_base_credit_won") or 0)
            recalc_won = int(res_recalc.get("cur_base_credit_won") or 0)
            diff_won = abs(orig_won - recalc_won)
        except Exception:
            diff_won = 0

        nr_names = t_y.get("nr_names") or []
        names_sfx = f": {', '.join(nr_names)}" if nr_names else ""
        warnings_out.append(
            f"⚠️ <b>[기신고 과세연도 사후 재산정 안내]</b> "
            f"<b>{y_chk}년</b> 인원이 신고 당시 <b>{orig_reg:.2f}명</b> → 재산정 <b>{recalc_reg:.2f}명</b>으로 변경됨 "
            f"(1년 미만 퇴사 확정{names_sfx}). "
            f"<b>{y_chk}년 공제액 차이 {diff_won:,}원</b>, 수정신고 여부 검토 필요"
        )
    return warnings_out


_STEP3_QUICK_FILL_CSS = """
<style>
@keyframes ecQuickFillPulse {
    0% {
        box-shadow: 0 0 0 0 rgba(22, 163, 74, 0.62), 0 4px 14px rgba(21, 128, 61, 0.30);
        transform: scale(1);
    }
    50% {
        box-shadow: 0 0 0 9px rgba(22, 163, 74, 0), 0 7px 20px rgba(21, 128, 61, 0.48);
        transform: scale(1.018);
    }
    100% {
        box-shadow: 0 0 0 0 rgba(22, 163, 74, 0), 0 4px 14px rgba(21, 128, 61, 0.30);
        transform: scale(1);
    }
}
@keyframes ecQuickFillShimmer {
    0% { background-position: 0% 50%; }
    50% { background-position: 100% 50%; }
    100% { background-position: 0% 50%; }
}
div[class*="st-key-btn_quick_fill_"] [data-testid="stButton"] > button,
div[class*="st-key-btn_quick_fill_"] button {
    background: linear-gradient(135deg, #16a34a 0%, #059669 50%, #15803d 100%) !important;
    background-size: 200% 200% !important;
    color: #ffffff !important;
    border: 2px solid #bbf7d0 !important;
    border-bottom: 3px solid #14532d !important;
    border-radius: 10px !important;
    min-height: 54px !important;
    padding: 10px 16px !important;
    font-family: 'Pretendard', 'Malgun Gothic', sans-serif !important;
    font-size: 0.96rem !important;
    font-weight: 800 !important;
    letter-spacing: -0.2px !important;
    animation: ecQuickFillPulse 1.85s infinite ease-in-out, ecQuickFillShimmer 4s infinite ease !important;
    transition: all 0.18s ease !important;
    cursor: pointer !important;
}
div[class*="st-key-btn_quick_fill_"] [data-testid="stButton"] > button:hover,
div[class*="st-key-btn_quick_fill_"] button:hover {
    background: linear-gradient(135deg, #22c55e 0%, #16a34a 100%) !important;
    border-color: #ffffff !important;
    box-shadow: 0 0 0 4px rgba(34, 197, 94, 0.32), 0 8px 22px rgba(21, 128, 61, 0.50) !important;
    transform: translateY(-2px) scale(1.02) !important;
    animation-play-state: paused !important;
}
div[class*="st-key-btn_quick_fill_"] [data-testid="stButton"] > button p,
div[class*="st-key-btn_quick_fill_"] button p {
    color: #ffffff !important;
    font-weight: 800 !important;
    font-size: 0.96rem !important;
}
.ec-qf-card {
    background: linear-gradient(90deg, #f0fdf4 0%, #ecfdf5 65%, #f8fafc 100%);
    border: 1.5px solid #86efac;
    border-left: 6px solid #16a34a;
    border-radius: 10px;
    padding: 11px 15px;
    margin: -4px 0 10px 0;
    box-shadow: 0 2px 8px rgba(22, 163, 74, 0.08);
    font-family: 'Pretendard', 'Malgun Gothic', sans-serif;
}
.ec-qf-top-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    flex-wrap: wrap;
    margin-bottom: 4px;
}
.ec-qf-why-badge {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    background: #dcfce7;
    color: #166534;
    border: 1px solid #86efac;
    font-size: 0.82rem;
    font-weight: 800;
    padding: 2px 9px;
    border-radius: 999px;
}
.ec-qf-hover-pill {
    position: relative;
    display: inline-flex;
    align-items: center;
    gap: 4px;
    background: #1e293b;
    color: #ffffff;
    font-size: 0.78rem;
    font-weight: 700;
    padding: 2px 9px;
    border-radius: 999px;
    cursor: help;
}
.ec-qf-hover-pill .ec-qf-tooltip-box {
    visibility: hidden;
    opacity: 0;
    position: absolute;
    bottom: 130%;
    right: 0;
    width: 420px;
    max-width: 82vw;
    background: #0f172a;
    color: #f8fafc;
    border: 1px solid #334155;
    border-left: 4px solid #22c55e;
    border-radius: 10px;
    padding: 12px 14px;
    font-size: 0.85rem;
    font-weight: 500;
    line-height: 1.58;
    box-shadow: 0 10px 25px rgba(15, 23, 42, 0.38);
    z-index: 9999;
    transition: opacity 0.16s ease, visibility 0.16s ease;
    pointer-events: none;
    text-align: left;
    word-break: keep-all;
}
.ec-qf-hover-pill:hover .ec-qf-tooltip-box {
    visibility: visible;
    opacity: 1;
}
.ec-qf-desc {
    font-size: 0.92rem;
    color: #1e293b;
    line-height: 1.55;
    font-weight: 600;
}
.ec-qf-preview {
    margin-top: 4px;
    font-size: 0.90rem;
    color: #14532d;
    font-weight: 700;
}
</style>
"""


def _render_pm_quick_fill_banner(
    s: dict,
    pkg: dict,
    ps: dict,
    _coh_yr: int,
    _pm_cur: dict,
    _pm_rc: dict,
    _base_key: str,
    tax_yr: int,
    corp_size: str,
    is_capital: bool,
    nth_label: str,
) -> None:
    """
    사후관리 박스((3) 2차년도 / (4) 3차년도) 바로 아래에 직결 배치되는
    기신고 기초값 1클릭 자동반영 안내 배너 및 애니메이션 초록 버튼.
    """
    if not (_pm_cur.get("base_missing") and not _pm_rc.get("base_missing")):
        return

    _rc_reg = float(_pm_rc.get("init_reg") or 0.0)
    _rc_yth = float(_pm_rc.get("init_yth") or 0.0)
    _rc_y_inc = float(_pm_rc.get("init_yth_inc") or 0.0)
    _rc_g_inc = float(_pm_rc.get("init_gen_inc") or 0.0)
    _rc_tot_inc = _rc_y_inc + _rc_g_inc
    _rc_cont_won = int(_pm_rc.get("continued_credit_won") or 0)
    _rc_claw_won = int(_pm_rc.get("clawback_net_payable_won") or 0)
    _coh_corp_size = _cohort_corp_size(s, _coh_yr, corp_size)
    _rc_rates = H.get_unit_rates(
        _coh_corp_size,
        _cohort_capital(s, _coh_yr, is_capital),
        scheme="legacy",
        retention_year=1,
    )
    _est_c1_won = int(
        round((_rc_y_inc * _rc_rates["청년등"] + _rc_g_inc * _rc_rates["청년등외"]) * 10_000)
    )

    _btn_help_md = (
        f"📌 [왜 이 버튼이 나타났나요?]\n"
        f"• 현재 계산 기준이 『📋 기신고 서식 숫자 기준』으로 선택되어 있으나, {_coh_yr}년 기신고 서류(공제감면세액계산서 등)가 없거나 "
        f"기초값(상시·청년등 인원, 증가인원, 최초 공제세액)이 비어 있어 바로 위 {nth_label} 사후관리 계산이 0원으로 보류된 상태입니다.\n"
        f"• 반면 2단계 사원표에는 원천징수부 급여대장으로 산출된 {_coh_yr}년 재계산 데이터가 준비되어 있어 원클릭 연동을 안내합니다.\n\n"
        f"⚡ [누르면 어떤 동작이 실행되나요?]\n"
        f"• 하단 기신고 입력칸을 일일이 수기로 열지 않고도, 2단계 사원표의 {_coh_yr}년 상시({_rc_reg:.2f}명)·청년등({_rc_yth:.2f}명)·"
        f"고용증가(+{_rc_tot_inc:.2f}명)·최초 공제세액({_est_c1_won:,}원)을 기신고 기초값에 즉시 복사·저장합니다.\n"
        f"• 반영 즉시 위 {nth_label} 사후관리 결과가 『{_pm_rc.get('case_code')}』(공제 +{_rc_cont_won:,}원 / 추징 -{_rc_claw_won:,}원)으로 자동 계산됩니다."
    )

    _c_w, _c_b = st.columns([3.7, 2.3], vertical_alignment="center")
    with _c_w:
        st.markdown(
            f"<div class='ec-qf-card'>"
            f"<div class='ec-qf-top-row'>"
            f"<span class='ec-qf-why-badge'>⚡ 왜 0원인가요? {_coh_yr}년 기신고 기초값 미입력 (사후관리 보류 중)</span>"
            f"<span class='ec-qf-hover-pill'>💬 버튼 상세설명 (마우스 오버)"
            f"<span class='ec-qf-tooltip-box'>"
            f"<b style='color:#4ade80;'>① 왜 이 버튼이 나타났나요?</b><br>"
            f"원천징수부만 업로드하고 {_coh_yr}년 기신고 세액공제 서식을 넣지 않았거나 기초값이 비어 있어, "
            f"위 {nth_label} 사후관리 세액이 <b>0원(보류)</b>으로 멈춰 있기 때문입니다.<br><br>"
            f"<b style='color:#4ade80;'>② 우측 초록 버튼을 누르면 무엇이 실행되나요?</b><br>"
            f"2단계 사원표에서 계산된 <b>{_coh_yr}년 상시({_rc_reg:.2f}명)·청년등({_rc_yth:.2f}명)·증가(+{_rc_tot_inc:.2f}명)·"
            f"최초 공제세액({_est_c1_won:,}원)</b>을 기신고 기초값에 1클릭으로 자동 입력하여 위 사후관리 세액을 즉시 산출합니다."
            f"</span></span>"
            f"</div>"
            f"<div class='ec-qf-desc'>"
            f"원천징수부 기준으로 계산된 <b>2단계 사원표({_coh_yr}년 귀속)</b> 수치가 준비되어 있습니다. 우측 초록 버튼을 누르면 하단 기신고 입력칸에 즉시 반영됩니다."
            f"</div>"
            f"<div class='ec-qf-preview'>"
            f"👉 <b>반영될 사원표 기초값</b>: 상시 <b>{_rc_reg:.2f}명</b> (청년등 <b>{_rc_yth:.2f}명</b>) · 증가 <b>+{_rc_tot_inc:.2f}명</b> "
            f"→ <b>사후관리 산출: {_pm_rc.get('case_code')} (공제 +{_rc_cont_won:,}원 / 추징 -{_rc_claw_won:,}원)</b>"
            f"</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
    with _c_b:
        if st.button(
            f"🔄 {_coh_yr}년 사원표 재계산 값을 기신고 기초값에 바로 반영 ({nth_label} 산출)",
            type="primary",
            width="stretch",
            key=f"btn_quick_fill_{_coh_yr}_{tax_yr}",
            help=_btn_help_md,
        ):
            _fd = ps.setdefault(str(_coh_yr), {})
            _brc = (pkg.get(_base_key) or {}).get("recalc") or {}
            if _brc.get("init_reg") is not None:
                _fd["상시"] = float(_brc["init_reg"])
            if _brc.get("init_yth") is not None:
                _fd["청년등"] = float(_brc["init_yth"])
            if _brc.get("init_reg_total") is not None and _fd.get("상시_총인원") is None:
                _fd["상시_총인원"] = float(_brc["init_reg_total"])
            if _brc.get("init_yth_total") is not None and _fd.get("청년등_총인원") is None:
                _fd["청년등_총인원"] = float(_brc["init_yth_total"])
            if _brc.get("init_yth_inc") is not None:
                _fd["청년등_증가"] = float(_brc["init_yth_inc"])
            if _brc.get("init_gen_inc") is not None:
                _fd["청년등외_증가"] = float(_brc["init_gen_inc"])
            if _fd.get("공제세액") is None:
                _fd["공제세액"] = _est_c1_won
            _fd["_auto_filled"] = True
            _fd["_needs_filing_check"] = False
            s["fill_ver"] = int(s.get("fill_ver", 0)) + 1
            _save_ec_to_disk(s)
            st.rerun()


def _page_calculation():
    st.markdown(_STEP3_QUICK_FILL_CSS, unsafe_allow_html=True)
    s = _S()
    _ensure_built_for_tax_year(s)
    tax_yr = int(s["tax_year"])
    b = s["biz"]
    corp_size = _cohort_corp_size(s, tax_yr)
    coh1_corp_size = _cohort_corp_size(s, tax_yr - 1, corp_size)
    coh2_corp_size = _cohort_corp_size(s, tax_yr - 2, corp_size)
    corp_size_map_s3 = R.get_corp_size_map(s)
    corp_size_summary_s3 = R.format_corp_size_summary_text(s, [tax_yr - 3, tax_yr - 2, tax_yr - 1, tax_yr])
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
    P.fill_missing_increments(ps, corp_size, _extra_cnts, corp_size_by_year=corp_size_map_s3)

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
        corp_size_by_year=corp_size_map_s3,
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

    # 직전·전전 신법 과세연도(2026년 이후)가 차년도 1년 미만 퇴사 확정으로 재산정된 경우 주황 경고 표시
    for _warn_html in _build_prior_new_law_recalc_warnings(s, tax_yr, corp_size, is_capital, totals_all, ps):
        st.markdown(f"<div class='ec-warn-banner'>{_warn_html}</div>", unsafe_allow_html=True)

    # 기신고 공제세액과 선택한 연도별 기업규모 단가가 다른 경우 주황 경고 표시
    for _mismatch_msg in (pkg.get("filed_credit_mismatch_warnings") or []):
        st.markdown(
            f"<div class='ec-warn-banner'>⚠️ <b>{_mismatch_msg}</b></div>",
            unsafe_allow_html=True,
        )

    # 상단 3대 KPI 요약 카드 (당해 확정 공제세액 · 추징/농특세 · 실질 순절세액) 및 5대 수리·법령 정합성 배지
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
        f"<th class='{'active-yr' if y == tax_yr else ''}'>{y}년 ({R.format_corp_size_label(_cohort_corp_size(s, y, corp_size), short=True)}){' · 당해' if y == tax_yr else ''}"
        + (filed_tag if matrix_cols.get(y, {}).get("from_filed_stmt") else "")
        + "</th>"
        for y in yr_list
    )
    r1_cells = "".join(
        f"<td class='{'active-yr-cell' if y == tax_yr else ''}'>"
        f"{_fmt_matrix_won(matrix_cols[y]['r1_credit'], matrix_cols[y]['r1_claw'], bool(matrix_cols[y].get('r1_na')), bool(matrix_cols[y].get('r1_needs_check')))}</td>"
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
        f"<span>📊 연도별 통합고용세액공제 요약표 ({corp_size_summary_s3} · {loc_label})</span>"
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
    if any(bool(matrix_cols[y].get("r1_needs_check")) for y in yr_list):
        chk_yrs = [str(y) for y in yr_list if matrix_cols[y].get("r1_needs_check")]
        st.caption(
            f"🟧 **[신고서 확인 필요]** {', '.join(chk_yrs)}년 1차 세액공제액은 기신고 공제세액계산서(별지 제10호의9) 또는 세액공제조정명세서(별지 제8호서식 부표3)에서 확인되지 않아 추정복원 없이 빈칸으로 표시했습니다."
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
        f"<div class='ec-sec-header'>1. {tax_yr}년 세액공제 ({corp_size_summary_s3} · {loc_label} · {basis_lbl})</div>",
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

    m_cur_badge = R.calc_method_badge_label(tax_yr, eval_year=tax_yr)
    st.markdown(
        f"<div class='ec-sub-header'><span class='ec-sub-num'>(1)</span><span>평균 상시근로자 증가 인원</span>"
        f"<span style='background:#dcfce7;color:#15803d;border:1px solid #86efac;padding:2px 9px;border-radius:999px;font-size:0.80rem;font-weight:800;margin-left:8px;'>📐 {m_cur_badge}</span></div>",
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
    # [Section 4] 같은 연도의 A·B값이 다르면 표 아래 회색 한 줄로 다른 방식의 값을 참고 표시 (계산에는 쓰지 않음)
    _ref_s3_parts = []
    _cur_a_r = float(cur_t.get("A_상시_평균", cur_s["regular"]))
    _cur_b_r = float(cur_t.get("B_상시_평균", cur_s["regular"]))
    _cur_a_y = float(cur_t.get("A_청년등_평균", cur_s["youth"]))
    _cur_b_y = float(cur_t.get("B_청년등_평균", cur_s["youth"]))
    if round(_cur_a_r, 2) != round(_cur_b_r, 2) or round(_cur_a_y, 2) != round(_cur_b_y, 2):
        if R.calc_method_for(tax_yr, eval_year=tax_yr) == "B":
            _ref_s3_parts.append(f"당해({tax_yr}년) 합계 후 절사 참고값: 상시 {_cur_a_r:.2f}명 (청년등 {_cur_a_y:.2f} · 청년외 {max(0.0, _cur_a_r - _cur_a_y):.2f})")
        else:
            _ref_s3_parts.append(f"당해({tax_yr}년) 사원별 절사 참고값: 상시 {_cur_b_r:.2f}명 (청년등 {_cur_b_y:.2f} · 청년외 {max(0.0, _cur_b_r - _cur_b_y):.2f})")
    _prv_a_r = float(prev_t.get("nr_A_상시_평균" if pkg["active_scheme"] == "new_2026" and prev_t.get("nr_A_상시_평균") is not None else "A_상시_평균", prv_reg_disp))
    _prv_b_r = float(prev_t.get("nr_B_상시_평균" if pkg["active_scheme"] == "new_2026" and prev_t.get("nr_B_상시_평균") is not None else "B_상시_평균", prv_reg_disp))
    _prv_a_y = float(prev_t.get("nr_A_청년등_평균" if pkg["active_scheme"] == "new_2026" and prev_t.get("nr_A_청년등_평균") is not None else "A_청년등_평균", prv_yth_disp))
    _prv_b_y = float(prev_t.get("nr_B_청년등_평균" if pkg["active_scheme"] == "new_2026" and prev_t.get("nr_B_청년등_평균") is not None else "B_청년등_평균", prv_yth_disp))
    if round(_prv_a_r, 2) != round(_prv_b_r, 2) or round(_prv_a_y, 2) != round(_prv_b_y, 2):
        if R.calc_method_for(tax_yr, eval_year=tax_yr) == "B":
            _ref_s3_parts.append(f"직전({tax_yr-1}년 비교) 합계 후 절사 참고값: 상시 {_prv_a_r:.2f}명 (청년등 {_prv_a_y:.2f} · 청년외 {max(0.0, _prv_a_r - _prv_a_y):.2f})")
        else:
            _ref_s3_parts.append(f"직전({tax_yr-1}년 비교) 사원별 절사 참고값: 상시 {_prv_b_r:.2f}명 (청년등 {_prv_b_y:.2f} · 청년외 {max(0.0, _prv_b_r - _prv_b_y):.2f})")
    if _ref_s3_parts:
        st.markdown(
            f"<div style='margin:-12px 0 12px 4px;font-size:0.82rem;color:#64748b;font-weight:600;'>"
            f"ℹ️ 다른 계산방식 참고(계산 미사용): {' &nbsp;|&nbsp; '.join(_ref_s3_parts)}"
            f"</div>",
            unsafe_allow_html=True,
        )
    _bridge_s3 = _build_compact_bridge_info(
        s,
        tax_yr - 1,
        tax_yr,
        prev_reg_override=prv_reg_disp,
        cur_reg_override=cur_s["regular"],
        use_new_rule_prev=(pkg["active_scheme"] == "new_2026"),
    )
    _render_compact_bridge(_bridge_s3, between_tables=False)
    if prev_s.get("old_rule_regular") is not None and abs(prev_s["old_rule_regular"] - prv_reg_disp) > 1e-9:
        nr_excl_nms = ", ".join(prev_s.get("nr_names") or [])
        nr_excl_str = f"({nr_excl_nms} 제외) " if nr_excl_nms else ""
        st.caption(
            f"ℹ️ 직전 과세연도({tax_yr - 1}년) 비교 인원({prv_reg_disp:.2f}명)은 일관된 해석 기준에 따라 당해({tax_yr}년) 공제 인원과 동일한 잣대"
            f"(조특령 제26조의8 제2항 제1호 개정 규정: 실제 근로기간 1년 미만 퇴사 확정자 제외 — {tax_yr - 1}년 입사 후 {tax_yr}년 중 1년 미만 퇴사 확정자 포함)로 재산정한 값입니다{nr_excl_str}"
            f"[2027년 B·2028년 C 다년도 비교 시에도 매년 확정된 퇴사 사실을 반영해 비교연도 인원을 자동 재산정]. "
            f"(2단계 {tax_yr - 1}년 표의 {prev_s['old_rule_regular']:.2f}명은 {tax_yr - 1}년 귀속분 자체 공제와 그 사후관리에 쓰는 종전 규정[법률 제21223호 부칙 제34조 · 대통령령 제35999호 부칙 제2조] 인원입니다. "
            f"또한 조특법 제29조의8 제1항 제2호('청년등상시근로자 외의 상시근로자') 및 시행규칙 별지 제10호의10서식(⑩ = ② − ⑨)에 따라 "
            f"『① 전체 상시(절사) − ② 청년등 상시(절사) = ③ 청년등 외 상시』 순서로 정본 산정하여[직전 {prv_reg_disp:.2f} − {prv_yth_disp:.2f} = {prv_gen_disp:.2f}명, 당해 {cur_s['regular']:.2f} − {cur_s['youth']:.2f} = {cur_s['non_youth']:.2f}명, 증가 +{inc_disp['non_youth_inc']:.2f}명] "
            f"전체 증가인원 = 청년등 증가 + 청년등 외 증가 항등식을 0.01명 오차 없이 일치시켰습니다.)"
        )

    st.markdown(
        f"<div class='ec-sub-header'><span class='ec-sub-num'>(2)</span><span>1차년도 세액공제액 계산 ({tax_yr}년 귀속 · {R.format_corp_size_label(corp_size)}, {loc_label})</span><span style='background:#dcfce7;color:#15803d;border:1px solid #86efac;padding:2px 9px;border-radius:999px;font-size:0.80rem;font-weight:800;margin-left:8px;'>📐 {R.calc_method_badge_label(tax_yr, eval_year=tax_yr)}</span></div>",
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
            if pm_obj.get("period_expired") or "공제기간 종료" in str(pm_obj.get("case_code") or ""):
                r_sub = f"공제기간 종료(일반기업 2년) — {eval_yr}년 사후관리 대상 아님"
                y_sub = f"공제기간 종료(일반기업 2년) — {eval_yr}년 사후관리 대상 아님"
            else:
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

    _m1_badge = R.calc_method_badge_label(tax_yr - 1, eval_year=tax_yr)
    _m1_style = "background:#dcfce7;color:#15803d;border:1px solid #86efac;" if (tax_yr >= 2026 or R.calc_method_for(tax_yr - 1, eval_year=tax_yr) == "B") else "background:#fef3c7;color:#b45309;border:1px solid #fcd34d;"
    _af1_badge = (
        "<span style='background:#ffedd5;color:#c2410c;border:1px solid #fdba74;padding:2px 9px;border-radius:999px;font-size:0.80rem;font-weight:800;margin-left:6px;'>🟧 사원표 재계산값 임시 입력 · 신고서 확인 필요</span>"
        if p1.get("_auto_filled")
        else ""
    )
    st.markdown(
        f"<div class='ec-sub-header'><span class='ec-sub-num'>(3)</span><span>2차년도 사후관리 계산 ({tax_yr - 1}년 귀속 · {R.format_corp_size_label(coh1_corp_size)} → {tax_yr}년 1차 사후관리)</span>"
        f"<span style='{_m1_style}padding:2px 9px;border-radius:999px;font-size:0.80rem;font-weight:800;margin-left:8px;'>📐 {_m1_badge}</span>{_af1_badge}</div>",
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
        rates_legacy=H.get_unit_rates(coh1_corp_size, _cohort_capital(s, tax_yr - 1, is_capital), scheme="legacy", retention_year=1),
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
    _a_b2_r, _b_b2_r = float(cur_t.get("A_b2_reg", cur_s["b2_reg"])), float(cur_t.get("B_b2_reg", cur_s["b2_reg"]))
    _a_b2_y, _b_b2_y = float(cur_t.get("A_b2_yth", cur_s["b2_yth"])), float(cur_t.get("B_b2_yth", cur_s["b2_yth"]))
    if round(_a_b2_r, 2) != round(_b_b2_r, 2) or round(_a_b2_y, 2) != round(_b_b2_y, 2):
        _other_m1_txt = (
            f"합계 후 절사 참고값: 당해 사후관리 상시 {_a_b2_r:.2f}명 (청년등 {_a_b2_y:.2f} · 청년외 {max(0.0, _a_b2_r - _a_b2_y):.2f})"
            if R.calc_method_for(tax_yr - 1, eval_year=tax_yr) == "B"
            else f"사원별 절사 참고값: 당해 사후관리 상시 {_b_b2_r:.2f}명 (청년등 {_b_b2_y:.2f} · 청년외 {max(0.0, _b_b2_r - _b_b2_y):.2f})"
        )
        _chk_m1 = " &nbsp;|&nbsp; # 확인 필요: 최초 공제연도 B방식 신고값과 평가연도 합계 절사값의 비교 — 2027년 국세청 신고 안내 확인" if (tax_yr >= 2026 and (tax_yr - 1) == 2025) else ""
        st.markdown(
            f"<div style='margin:-12px 0 12px 4px;font-size:0.81rem;color:#64748b;font-weight:600;'>ℹ️ 다른 계산방식 참고(계산 미사용): {_other_m1_txt}{_chk_m1}</div>",
            unsafe_allow_html=True,
        )
    _render_pm_quick_fill_banner(
        s=s,
        pkg=pkg,
        ps=ps,
        _coh_yr=tax_yr - 1,
        _pm_cur=pkg["pm_y1"],
        _pm_rc=pkg["pm_y1_recalc"],
        _base_key="base_y1",
        tax_yr=tax_yr,
        corp_size=corp_size,
        is_capital=is_capital,
        nth_label="2차년도(1차 사후관리)",
    )

    _m2_badge = R.calc_method_badge_label(tax_yr - 2, eval_year=tax_yr)
    _m2_style = "background:#dcfce7;color:#15803d;border:1px solid #86efac;" if (tax_yr >= 2026 or R.calc_method_for(tax_yr - 2, eval_year=tax_yr) == "B") else "background:#fef3c7;color:#b45309;border:1px solid #fcd34d;"
    _af2_badge = (
        "<span style='background:#ffedd5;color:#c2410c;border:1px solid #fdba74;padding:2px 9px;border-radius:999px;font-size:0.80rem;font-weight:800;margin-left:6px;'>🟧 사원표 재계산값 임시 입력 · 신고서 확인 필요</span>"
        if p2.get("_auto_filled")
        else ""
    )
    st.markdown(
        f"<div class='ec-sub-header'><span class='ec-sub-num'>(4)</span><span>3차년도 사후관리 계산 ({tax_yr - 2}년 귀속 · {R.format_corp_size_label(coh2_corp_size)} → {tax_yr}년 2차 사후관리)</span>"
        f"<span style='{_m2_style}padding:2px 9px;border-radius:999px;font-size:0.80rem;font-weight:800;margin-left:8px;'>📐 {_m2_badge}</span>{_af2_badge}</div>",
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
        rates_legacy=H.get_unit_rates(coh2_corp_size, _cohort_capital(s, tax_yr - 2, is_capital), scheme="legacy", retention_year=1),
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
    _a_b3_r, _b_b3_r = float(cur_t.get("A_b3_reg", cur_s["b3_reg"])), float(cur_t.get("B_b3_reg", cur_s["b3_reg"]))
    _a_b3_y, _b_b3_y = float(cur_t.get("A_b3_yth", cur_s["b3_yth"])), float(cur_t.get("B_b3_yth", cur_s["b3_yth"]))
    if round(_a_b3_r, 2) != round(_b_b3_r, 2) or round(_a_b3_y, 2) != round(_b_b3_y, 2):
        _other_m2_txt = (
            f"합계 후 절사 참고값: 당해 사후관리 상시 {_a_b3_r:.2f}명 (청년등 {_a_b3_y:.2f} · 청년외 {max(0.0, _a_b3_r - _a_b3_y):.2f})"
            if R.calc_method_for(tax_yr - 2, eval_year=tax_yr) == "B"
            else f"사원별 절사 참고값: 당해 사후관리 상시 {_b_b3_r:.2f}명 (청년등 {_b_b3_y:.2f} · 청년외 {max(0.0, _b_b3_r - _b_b3_y):.2f})"
        )
        _ext_note_m2 = " &nbsp;|&nbsp; # 확인 필요: '26.3월 국세청 안내 신뢰보호 원칙 연장 적용" if (tax_yr >= 2026 and (tax_yr - 2) <= 2024) else ""
        st.markdown(
            f"<div style='margin:-12px 0 12px 4px;font-size:0.81rem;color:#64748b;font-weight:600;'>ℹ️ 다른 계산방식 참고(계산 미사용): {_other_m2_txt}{_ext_note_m2}</div>",
            unsafe_allow_html=True,
        )
    _render_pm_quick_fill_banner(
        s=s,
        pkg=pkg,
        ps=ps,
        _coh_yr=tax_yr - 2,
        _pm_cur=pkg["pm_y2"],
        _pm_rc=pkg["pm_y2_recalc"],
        _base_key="base_y2",
        tax_yr=tax_yr,
        corp_size=corp_size,
        is_capital=is_capital,
        nth_label="3차년도(2차 사후관리)",
    )

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
                width="stretch",
                key=f"btn_fill_from_recalc_{tax_yr}",
                help=(
                    f"📌 [왜 이 버튼이 필요한가요?]\n"
                    f"• {tax_yr-1}년·{tax_yr-2}년 기신고 서식을 업로드하지 않았거나 일부 칸이 비어 있을 때 수기로 하나씩 타이핑하는 번거로움을 덜어줍니다.\n\n"
                    f"⚡ [누르면 어떤 동작이 실행되나요?]\n"
                    f"• 현재 비어 있는 기신고 입력칸(상시·청년등 연인원/평균인원, 고용증가 인원, 최초 공제세액, 2차 공제세액)에 2단계 사원표 재계산 값을 한 번에 채워 넣습니다. (이미 직접 입력한 칸은 덮어쓰지 않고 보존합니다.)"
                ),
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
                        coh_sz_fill = _cohort_corp_size(s, cohort, corp_size)
                        r_coh = H.get_unit_rates(coh_sz_fill, _cohort_capital(s, cohort, is_capital), scheme="legacy", retention_year=1)
                        c1_est = int(
                            round(
                                (inc_c["youth_inc"] * r_coh["청년등"] + inc_c["non_youth_inc"] * r_coh["청년등외"])
                                * 10_000
                            )
                        )
                        if f_d.get("공제세액") is None:
                            f_d["공제세액"] = c1_est
                        f_d["_auto_filled"] = True
                        f_d["_needs_filing_check"] = False
                        if cohort == tax_yr - 2 and f_d.get("2차_공제세액") is None and coh_sz_fill not in ("일반기업", "대기업"):
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
                _af_hdr_pill = (
                    " <span style='background:#ffedd5;color:#c2410c;border:1px solid #fdba74;padding:1px 7px;border-radius:999px;font-size:0.74rem;font-weight:800;'>사원표 재계산값 임시 입력 · 신고서 확인 필요</span>"
                    if f.get("_auto_filled")
                    else ""
                )
                st.markdown(
                    f"**📋 {cohort}년 귀속({R.format_corp_size_label(_cohort_corp_size(s, cohort, corp_size))} · {R.calc_method_short_label(cohort, eval_year=cohort)}) 기신고분 ({step_lbl})**{_af_hdr_pill}",
                    unsafe_allow_html=True,
                )
                # [6-3] 같은 과세연도의 인원이 서로 다른 연도 신고서에서 다르게 기재된 경우 주황 경고 및 선택기 표시
                _conf_list = f.get("_conflicts") or []
                if len(_conf_list) >= 2:
                    _conf_desc = " vs ".join(
                        f"<b>{c.get('source_label')}</b>(상시 {float(c.get('상시') or 0):.2f}·청년등 {float(c.get('청년등') or 0):.2f}명)"
                        for c in _conf_list
                    )
                    st.markdown(
                        f"<div style='margin:4px 0 8px 0;padding:8px 10px;background:#fff7ed;border:1.5px solid #fdba74;"
                        f"border-left:4px solid #f97316;border-radius:7px;font-size:0.80rem;color:#9a3412;line-height:1.45;'>"
                        f"🟧 <b>[{cohort}년 기신고 인원 신고서 간 불일치 감지]</b><br>{_conf_desc}<br>"
                        f"<span style='color:#c2410c;'>사후관리 기준으로 사용할 신고서를 선택하세요 (기본값: 최신 신고서):</span>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
                    _cur_c_idx = int(f.get("_conflict_selected_idx", len(_conf_list) - 1))
                    _cur_c_idx = max(0, min(len(_conf_list) - 1, _cur_c_idx))
                    _sel_c_idx = st.radio(
                        f"{cohort}년 사후관리 기준 신고서 선택",
                        options=list(range(len(_conf_list))),
                        index=_cur_c_idx,
                        format_func=lambda idx: f"{_conf_list[idx].get('source_label')} — 상시 {float(_conf_list[idx].get('상시') or 0):.2f}명 / 청년등 {float(_conf_list[idx].get('청년등') or 0):.2f}명" + (" [최신·기본]" if idx == len(_conf_list) - 1 else ""),
                        key=f"pf_conf_sel_{cohort}_{kver}",
                    )
                    if _sel_c_idx != _cur_c_idx:
                        _chosen_c = _conf_list[_sel_c_idx]
                        f["_conflict_selected_idx"] = _sel_c_idx
                        f["_conflict_selected_source"] = _chosen_c.get("source_label")
                        if _chosen_c.get("상시") is not None:
                            f["상시"] = float(_chosen_c["상시"])
                        if _chosen_c.get("청년등") is not None:
                            f["청년등"] = float(_chosen_c["청년등"])
                        s["fill_ver"] = int(s.get("fill_ver", 0)) + 1
                        _save_ec_to_disk(s)
                        st.rerun()
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


    with st.expander("📊 [상세 대조] 연도 · 블록별 상시근로자 현황 및 사후관리 기신고 vs 세법원칙 요약표", expanded=False):
        st.markdown("**연도 · 블록별 상시근로자 현황 및 사후관리 기신고 vs 세법원칙 비교**")
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
                "적용 기준 및 비교 안내": f"당해({tax_yr}년) 신법 기준(실제 근로기간 1년 미만 제외 · ÷{pkg['cur_s']['months_in_year']}개월 {R.calc_method_badge_label(tax_yr, eval_year=tax_yr)})",
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
        st.dataframe(pd.DataFrame(cmp_rows), width="stretch", hide_index=True)

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
        st.dataframe(pm_cmp_df, width="stretch", hide_index=True)

    st.markdown(
        "<div class='ec-law-ref-box'>"
        "<div style='font-weight:900;font-size:1.12rem;color:#1e3a8a;margin-bottom:8px;'>"
        "📚 계산근거 관련 법령조문 (국가법령정보센터 바로가기)"
        "</div>"
        "• <a href='https://www.law.go.kr/법령/조세특례제한법/제29조의8' target='_blank'>"
        "조세특례제한법 제29조의8 (통합고용세액공제)</a> — "
        "제1항(고용증가 세액공제 A+B+C 점증형 구조), 제2항(경력단절 근로자 정의), "
        "구 제1항(연속공제)·구 제2항·제3항(인원 감소 시 추가납부세액, 구 시행령 제26조의8 제4항) 및 법률 제21223호 부칙 제34조 경과조치(2024·2025년 귀속분), "
        "제4항(정규직 전환 추가공제, ~2024년 전환분), 제5항(육아휴직 복귀 추가공제)<br>"
        "• <a href='https://www.law.go.kr/법령/조세특례제한법시행령/제26조의8' target='_blank'>"
        "조세특례제한법 시행령 제26조의8 (통합고용세액공제 상시근로자 범위·사후관리 산식)</a> — "
        "제2항(내국인 근로자[조특법 제2조 제1항 제1호 거주자 포함] 및 실제 근로기간 1년 미만 제외 · 대통령령 제35999호 부칙 제2조 경과조치), "
        "제3항(최소고용증가인원수), 제4항(청년등 상시근로자 범위, 전체 증가한도 Cap은 법 제29조의8 제1항 제1호·제2호 괄호), "
        "제6항(<a href='https://www.law.go.kr/법령/조세특례제한법시행령/제11조의2' target='_blank'>제11조의2 제8항</a> 준용) 및 국세청 '26.3월 안내(A/B 계산방식 적용 구분 · 별지 제10호의10서식 ⑩ = ② − ⑨), 조특령 부칙(2026.2.27.) 제11조(청년 유예기간 경과조치), "
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
    c_prev, c_cmp3, _, c_pdf3, c_next = st.columns([1.15, 2.05, 1.4, 1.25, 1.3])
    if c_prev.button("< 이전", width="stretch", key="btn_step3_prev"):
        s["step"] = 2
        _trigger_scroll_to_top(s)
        _save_ec_to_disk(s)
        st.rerun()
    if c_cmp3.button("⚖️ 기신고 vs 세법상 재계산 비교", width="stretch", key="btn_step3_filed_vs_recalc"):
        _dlg_filed_vs_recalc_comparison(s, pkg, tax_yr)
    with c_pdf3:
        with st.container(key="ec_btn_pdf_step3_wrap"):
            st.download_button(
                "📕 PDF 출력",
                data=_build_step3_calculation_pdf_bytes(s, pkg, matrix_cols),
                file_name=f"{corp_nm_fn}_{tax_yr}년귀속_통합고용세액공제_계산서.pdf",
                mime="application/pdf",
                width="stretch",
                key="dl_pdf_step3_calc",
                help="3단계 연도별 세액공제 요약표 및 (1)~(4) 상세 계산 산식을 A4 PDF로 즉시 다운로드합니다.",
            )
    if c_next.button("다음(4단계)", type="primary", width="stretch", key="btn_step3_next"):
        s["step"] = 4
        s["max_step_reached"] = max(int(s.get("max_step_reached") or 1), 4)
        _trigger_scroll_to_top(s)
        _save_ec_to_disk(s)
        st.rerun()