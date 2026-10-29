# -*- coding: utf-8 -*-
"""통합고용세액공제 계산기 화면 — 2단계 사원정보: 연도별 사원표(AgGrid)·월별 입력·오류 검토·심층진단

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
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from . import rules as R
from . import headcount as H
from . import parsers as P
from . import backup as B

from .ui_common import (  # noqa: F401
    JS_DATE_FMT,
    JS_DEC2_FMT,
    JS_LOCKED,
    JS_MONTH_EDITABLE,
    JS_MONTH_STYLE,
    JS_NAME_FMT,
    JS_NUM_FMT,
    _CALC_CACHE_KEY,
    _prune_manual_without_hire,
    JS_STYLE,
    JS_STYLE_CENTER,
    JS_STYLE_EXCL,
    JS_STYLE_REGULAR,
    JS_STYLE_WORKPLACE,
    JS_STYLE_YOUTH,
    JS_YOUTH_PARAMS,
    MONTH_COLS,
    _S,
    _adjusted_prev_totals,
    _all_possible_years,
    _cohort_corp_size,
    _block_titles_for_year,
    _build_review_pdf_bytes,
    _build_year_rows,
    _ctx,
    _default_workplace_label,
    _ensure_built_for_tax_year,
    _ensure_korean_pdf_font,
    _ensure_totals_snapshot,
    _has_year_data,
    _save_ec_to_disk,
    _trigger_scroll_to_top,
    _years,
)



def _build_schedule_pdf_bytes(s: dict, target_years: list[int], include_summary: bool = False) -> bytes:
    """
    선택된 연도(`target_years`)의 상시근로자 명세표(사원 계산기 + 1~12월 + 우측 3·4·5 블록 + 합산합계 행)를
    A4 가로(Landscape) 고해상도 정식 PDF로 생성합니다.
    """
    _ensure_built_for_tax_year(s)
    reg_font, bold_font = _ensure_korean_pdf_font()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        leftMargin=18,
        rightMargin=18,
        topMargin=20,
        bottomMargin=20,
    )

    styles = getSampleStyleSheet()
    st_title = ParagraphStyle(
        "ECTitle",
        parent=styles["Normal"],
        fontName=bold_font,
        fontSize=13,
        leading=17,
        textColor=colors.HexColor("#0f172a"),
        spaceAfter=4,
    )
    st_sub = ParagraphStyle(
        "ECSub",
        parent=styles["Normal"],
        fontName=reg_font,
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor("#334155"),
        spaceAfter=6,
    )
    st_yr_hdr = ParagraphStyle(
        "ECYrHdr",
        parent=styles["Normal"],
        fontName=bold_font,
        fontSize=10.5,
        leading=14,
        textColor=colors.HexColor("#1e3a8a"),
        spaceBefore=4,
        spaceAfter=4,
    )

    b = s.get("biz") or {}
    corp_nm = (b.get("상호") or "").strip()
    biz_no = (b.get("사업자번호") or "").strip()
    corp_sz = R.format_corp_size_summary_text(s, target_years)
    cap = H.is_capital_area(b.get("사업장소재지", ""))
    loc_str = "수도권" if cap is True else ("수도권 외(비수도권)" if cap is False else "")
    tax_yr = int(s.get("tax_year") or R.DEFAULT_TAX_YEAR)

    story = []
    if len(target_years) == 1:
        y_only = target_years[0]
        story.append(Paragraph((f"[{corp_nm}] " if corp_nm else "") + f"{y_only}년 귀속 상시근로자 명세서 (통합고용세액공제 · 사후관리 판정표)", st_title))
    else:
        story.append(Paragraph((f"[{corp_nm}] " if corp_nm else "") + f"{tax_yr}년 귀속 통합고용세액공제 전체 연도 상시근로자 명세서 ({', '.join(str(y)+'년' for y in target_years)})", st_title))

    story.append(
        Paragraph(
            f"사업자등록번호: {biz_no}  |  기업규모·소재지: {corp_sz} · {loc_str}  |  귀속사업연도: {tax_yr}년 귀속",
            st_sub,
        )
    )

    # 전체 연도 출력 시 모든 연도의 열 위치·간격이 수직으로 100% 일치하도록 동일한 우측 블록 구성을 유지합니다.
    multi_yr_mode = len(target_years) > 1
    any_has_y1 = any(
        (_has_year_data(s, yy - 1) or bool(s.get("show_empty_pm_blocks", False)))
        for yy in target_years
    )
    any_has_y2 = any(
        (_has_year_data(s, yy - 2) or bool(s.get("show_empty_pm_blocks", False)))
        for yy in target_years
    )

    totals_by_yr: dict[int, dict] = {}
    for idx_y, y in enumerate(target_years):
        if idx_y > 0:
            story.append(Spacer(1, 16))
        rows, _, totals = _build_year_rows(s, y)
        totals_by_yr[y] = totals
        role_desc = _year_role_description(s, tax_yr, y)
        trunc_mode = R.calc_method_short_label(y, eval_year=y)
        b3_t, b4_t, b5_t = _block_titles_for_year(y, two_line=False)

        yr_has_y1 = _has_year_data(s, y - 1) or bool(s.get("show_empty_pm_blocks", False))
        yr_has_y2 = _has_year_data(s, y - 2) or bool(s.get("show_empty_pm_blocks", False))
        col_has_y1 = any_has_y1 if multi_yr_mode else yr_has_y1
        col_has_y2 = any_has_y2 if multi_yr_mode else yr_has_y2

        yr_flowables = []
        yr_sz_lbl = R.format_corp_size_label(R.get_corp_size_for_year(s, y))
        yr_flowables.append(
            Paragraph(
                f"■ {y}년 귀속 상시근로자 명세 ({len(rows)}명 · 기업구분: {yr_sz_lbl} · {trunc_mode}) — {role_desc}",
                st_yr_hdr,
            )
        )
        kpi_line = (
            f"[{b3_t}] 상시 {totals['b1_reg']:.2f}명 (청년등 {totals['b1_yth']:.2f} · 청년외 {totals['b1_gen']:.2f})"
            + (f"   |   [{b4_t}] 상시 {totals['b2_reg']:.2f}명 (청년등 {totals['b2_yth']:.2f} · 청년외 {totals['b2_gen']:.2f})" if yr_has_y1 else "")
            + (f"   |   [{b5_t}] 상시 {totals['b3_reg']:.2f}명 (청년등 {totals['b3_yth']:.2f} · 청년외 {totals['b3_gen']:.2f})" if yr_has_y2 else "")
            + f"   |   총인원(연인원) {totals['상시_합계']:g}명 ÷ {totals['months_in_year']}개월 ({trunc_mode})"
        )
        yr_flowables.append(Paragraph(kpi_line, st_sub))

        headers = [
            "사업장", "성명", "생년월일", "입사일", "퇴사일", "연령", "고용유형", "제외사유", "청년등 구분", "상시",
            *[f"{m}월" for m in range(1, 13)], "월합",
            f"{y%100:02d}공제\n청년", f"{y%100:02d}공제\n일반", f"{y%100:02d}공제\n상시",
        ]
        col_widths = [
            33, 35, 41, 41, 41, 22, 48, 56, 58, 18,
            *[16.0 for _ in range(12)], 21,
            23.5, 23.5, 23.5,
        ]
        if col_has_y1:
            headers.extend([f"{(y-1)%100:02d}사후\n청년", f"{(y-1)%100:02d}사후\n일반", f"{(y-1)%100:02d}사후\n상시"])
            col_widths.extend([23.5, 23.5, 23.5])
        if col_has_y2:
            headers.extend([f"{(y-2)%100:02d}사후\n청년", f"{(y-2)%100:02d}사후\n일반", f"{(y-2)%100:02d}사후\n상시"])
            col_widths.extend([23.5, 23.5, 23.5])

        # 폭 비율 자동 맞춤 (A4 가로 가용 폭 806pt)
        avail_w = landscape(A4)[0] - 36
        scale = avail_w / sum(col_widths)
        col_widths = [w * scale for w in col_widths]

        tbl_data = [headers]
        for r in rows:
            m_cells = []
            for i in range(12):
                mv = r[MONTH_COLS[i]]
                if mv is None:
                    m_cells.append("-")
                else:
                    m_cells.append(f"{mv:g}")
            row_cells = [
                str(r["사업장명"])[:7],
                str(r["성명"])[:7],
                str(r["생년월일"]).replace("-", "."),
                str(r["입사일"]).replace("-", "."),
                str(r["퇴사일"]).replace("-", "."),
                str(r["취업연령"]),
                str(r["고용유형"]).replace("근로자", "").replace("시간 이상", "h↑").replace("시간 미만", "h↓"),
                ("실제근로 1년미만" if (y >= 2026 and str(r["제외사유"]) == R.EXCL_UNDER_1Y) else str(r["제외사유"]))[:11],
                str(r["청년등"])[:11],
                str(r["상시"]),
                *m_cells,
                f"{r['합계']:g}",
                f"{r['b1_yth']:.2f}", f"{r['b1_gen']:.2f}", f"{r['b1_reg']:.2f}",
            ]
            if col_has_y1:
                if yr_has_y1:
                    row_cells.extend([f"{r['b2_yth']:.2f}", f"{r['b2_gen']:.2f}", f"{r['b2_reg']:.2f}"])
                else:
                    row_cells.extend(["-", "-", "-"])
            if col_has_y2:
                if yr_has_y2:
                    row_cells.extend([f"{r['b3_yth']:.2f}", f"{r['b3_gen']:.2f}", f"{r['b3_reg']:.2f}"])
                else:
                    row_cells.extend(["-", "-", "-"])
            tbl_data.append(row_cells)

        # 하단 요약 3행 추가 (2~9열 SPAN 병합으로 안내 문구가 이웃 열과 겹치지 않도록 정렬)
        sum_rows = [
            (
                "합산합계 · 상시근로자", "", f"÷ {totals['months_in_year']}개월 ({trunc_mode})",
                [f"{v:g}" if v is not None else "-" for v in totals["월별_상시"]],
                f"{totals['상시_합계']:g}",
                [f"{totals['b1_yth']:.2f}", f"{totals['b1_gen']:.2f}", f"{totals['b1_reg']:.2f}"],
                [f"{totals['b2_yth']:.2f}", f"{totals['b2_gen']:.2f}", f"{totals['b2_reg']:.2f}"] if yr_has_y1 else ["-", "-", "-"],
                [f"{totals['b3_yth']:.2f}", f"{totals['b3_gen']:.2f}", f"{totals['b3_reg']:.2f}"] if yr_has_y2 else ["-", "-", "-"],
            ),
            (
                "합산합계 · 청년등", "", "각 코호트 기준",
                [f"{v:g}" if v is not None else "-" for v in totals["월별_청년등"]],
                f"{totals['청년등_합계']:g}",
                [f"{totals['b1_yth']:.2f}", "-", "-"],
                [f"{totals['b2_yth']:.2f}", "-", "-"] if yr_has_y1 else ["-", "-", "-"],
                [f"{totals['b3_yth']:.2f}", "-", "-"] if yr_has_y2 else ["-", "-", "-"],
            ),
            (
                "합산합계 · 청년등 외", "", "상시 - 청년등",
                [f"{v:g}" if v is not None else "-" for v in totals["월별_청년외"]],
                f"{totals['청년외_합계']:g}",
                ["-", f"{totals['b1_gen']:.2f}", "-"],
                ["-", f"{totals['b2_gen']:.2f}", "-"] if yr_has_y1 else ["-", "-", "-"],
                ["-", f"{totals['b3_gen']:.2f}", "-"] if yr_has_y2 else ["-", "-", "-"],
            ),
        ]
        for wp_l, nm_l, et_l, m_list, tot_s, b1_l, b2_l, b3_l in sum_rows:
            s_row = [wp_l, nm_l, et_l, "", "", "", "", "", "", "", *m_list, tot_s, *b1_l]
            if col_has_y1:
                s_row.extend(b2_l)
            if col_has_y2:
                s_row.extend(b3_l)
            tbl_data.append(s_row)

        t_obj = Table(tbl_data, colWidths=col_widths, repeatRows=1)
        n_data_end = len(tbl_data) - 3
        t_style = [
            ("FONTNAME", (0, 0), (-1, 0), bold_font),
            ("FONTNAME", (0, 1), (-1, -1), reg_font),
            ("FONTNAME", (0, n_data_end), (-1, -1), bold_font),
            ("FONTSIZE", (0, 0), (-1, -1), 6.4),
            ("LEADING", (0, 0), (-1, -1), 8.2),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("BACKGROUND", (0, n_data_end), (-1, -1), colors.HexColor("#dcfce7")),
            ("TEXTCOLOR", (0, n_data_end), (-1, -1), colors.HexColor("#14532d")),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#cbd5e1")),
            ("LINEABOVE", (0, n_data_end), (-1, n_data_end), 0.8, colors.HexColor("#15803d")),
            ("LINEBELOW", (0, -1), (-1, -1), 0.9, colors.HexColor("#14532d")),
            ("TOPPADDING", (0, 0), (-1, -1), 2.8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.8),
            ("LEFTPADDING", (0, 0), (-1, -1), 1.5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 1.5),
        ]
        for sum_r in range(n_data_end, len(tbl_data)):
            t_style.append(("SPAN", (0, sum_r), (1, sum_r)))
            t_style.append(("SPAN", (2, sum_r), (9, sum_r)))
        for r_i in range(1, n_data_end):
            if r_i % 2 == 0:
                t_style.append(("BACKGROUND", (0, r_i), (-1, r_i), colors.HexColor("#f8fafc")))
        t_obj.setStyle(TableStyle(t_style))
        yr_flowables.append(t_obj)
        if len(rows) <= 18:
            story.append(KeepTogether(yr_flowables))
        else:
            story.extend(yr_flowables)

    if include_summary and tax_yr in totals_by_yr and (tax_yr - 1) in totals_by_yr:
        story.append(Spacer(1, 10))
        snap_all = _ensure_totals_snapshot(s)
        cur_t = snap_all.get(tax_yr) or totals_by_yr[tax_yr]
        prv_snap = snap_all.get(tax_yr - 1) or totals_by_yr[tax_yr - 1]
        use_nr = (tax_yr >= H.NEW_TENURE_RULE_FROM) and (prv_snap.get("nr_상시_평균") is not None)
        eff_prv_reg = round(float(prv_snap["nr_상시_평균"] if use_nr else (prv_snap.get("상시_평균", prv_snap.get("b1_reg", 0.0)) or 0.0)), 2)
        eff_prv_yth = round(float(prv_snap.get("nr_청년등_평균", 0.0) if use_nr else (prv_snap.get("청년등_평균", prv_snap.get("b1_yth", 0.0)) or 0.0)), 2)
        eff_prv_gen = round(max(0.0, eff_prv_reg - eff_prv_yth), 2)
        inc = H.calc_increase_with_cap(
            cur_t["상시_평균"], cur_t["청년등_평균"], cur_t["청년외_평균"], eff_prv_reg, eff_prv_yth, eff_prv_gen
        )
        prv_basis_note = f" (직전연도 신법 비교인원 {eff_prv_reg:.2f}명 기준)" if tax_yr >= 2026 else ""
        story.append(
            Paragraph(
                f"■ [{tax_yr}년 vs {tax_yr-1}년 신규공제 고용증가 요약{prv_basis_note}]  "
                f"전체 상시 증가: +{inc['전체_증가']:.2f}명  |  "
                f"청년등 인정 증가: +{inc['청년등_증가']:.2f}명  |  "
                f"청년등 외 인정 증가: +{inc['청년등외_증가']:.2f}명",
                st_yr_hdr,
            )
        )

    doc.build(story)
    return buf.getvalue()


@st.dialog("🔍 법령·심판례·절세누락 12대 정밀 오류 검토", width="large")
def _dlg_review(items: list[tuple[str, str]], audit_payload: dict | None = None, log_tokens_fn=None, room_key: str = ""):
    s = _S()
    errs = [m for lv, m in items if lv == "오류"]
    savs = [m for lv, m in items if lv == "절세누락"]
    chks = [m for lv, m in items if lv == "확인"]

    st.markdown(
        f"<div style='display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:10px;flex-wrap:wrap;'>"
        f"<div style='display:flex;gap:8px;flex-wrap:wrap;'>"
        f"<span style='background:#fef2f2;color:#b91c1c;border:1px solid #fecaca;padding:5px 13px;border-radius:999px;font-weight:800;font-size:0.92rem;'>🚨 필수 수정 오류 {len(errs)}건</span>"
        f"<span style='background:#f0fdf4;color:#15803d;border:1px solid #86efac;padding:5px 13px;border-radius:999px;font-weight:800;font-size:0.92rem;'>💰 절세누락 주의 {len(savs)}건</span>"
        f"<span style='background:#eff6ff;color:#1d4ed8;border:1px solid #bfdbfe;padding:5px 13px;border-radius:999px;font-weight:800;font-size:0.92rem;'>💡 실무·심판례 확인 {len(chks)}건</span>"
        f"</div>"
        f"<span style='font-size:0.86rem;color:#64748b;font-weight:600;'>※ 반복 안내 항목은 연도별로 자동 묶음 요약됩니다.</span>"
        f"</div>",
        unsafe_allow_html=True,
    )

    if not items:
        st.success("✅ 법령 및 최신 조세심판례 12대 항목 검토 결과, 발견된 오류나 절세누락 사항이 없습니다.")
    else:
        sections_html = ["<div class='ec-rev-scroll-wrap'>"]
        if errs:
            sections_html.append(
                f"<div class='ec-rev-sec-hdr err'>"
                f"<span>🚨 필수 수정 오류 ({len(errs)}건) — 수정해야 정확한 상시근로자 수가 계산됩니다</span>"
                f"</div>"
                f"<div class='ec-rev-grid'>"
            )
            for m in errs:
                sections_html.append(f"<div class='ec-rev-card err'>• <b>{m}</b></div>")
            sections_html.append("</div>")

        if savs:
            sections_html.append(
                f"<div class='ec-rev-sec-hdr sav'>"
                f"<span>💰 절세누락 주의 ({len(savs)}건) — 청년·고령자·장애인 우대공제 추가 적용 가능 대상</span>"
                f"</div>"
                f"<div class='ec-rev-grid'>"
            )
            for m in savs:
                sections_html.append(f"<div class='ec-rev-card sav'>• <b>{m}</b></div>")
            sections_html.append("</div>")

        if chks:
            sections_html.append(
                f"<div class='ec-rev-sec-hdr chk'>"
                f"<span>💡 실무·심판례 확인 사항 ({len(chks)}건) — 사실관계가 맞다면 그대로 진행하셔도 됩니다</span>"
                f"</div>"
                f"<div class='ec-rev-grid'>"
            )
            for m in chks:
                sections_html.append(f"<div class='ec-rev-card chk'>• {m}</div>")
            sections_html.append("</div>")

        sections_html.append("</div>")
        st.markdown("".join(sections_html), unsafe_allow_html=True)

    corp_fn = re.sub(r'[\\/:*?"<>|\s]+', "_", str((s.get("biz") or {}).get("상호") or "사업장"))[:30]
    tax_yr = int(s.get("tax_year") or R.DEFAULT_TAX_YEAR)

    st.markdown("<div class='ec-nav-divider' style='margin:10px 0;'></div>", unsafe_allow_html=True)
    c_ai, c_pdf_rev, c_close = st.columns([2.15, 1.15, 0.85])
    with c_ai:
        if audit_payload:
            if st.button("👑 Pro/Argon AI 심층 세무진단 코멘트 생성 (특수사례·판례 정밀점검)", use_container_width=True, key="btn_run_pro_audit"):
                with st.spinner("👑 Pro/Argon 모델이 사원표·특례·사후관리 리스크를 심층 분석하고 있습니다..."):
                    s["pro_audit_comment"] = getattr(P, "call_pro_argon_audit_commentary", lambda *a, **kw: "Pro/Argon 심층 진단 함수를 찾을 수 없습니다. parsers.py를 최신 버전으로 업데이트해 주세요.")(
                        audit_payload, log_tokens_fn=log_tokens_fn, room_key=room_key
                    )
                    _save_ec_to_disk(s)
    with c_pdf_rev:
        with st.container(key="ec_btn_pdf_rev_only"):
            st.download_button(
                "📕 오류검토 PDF 다운",
                data=_build_review_pdf_bytes(s, items, pro_comment=""),
                file_name=f"통합고용_오류검토_{corp_fn}_{tax_yr}귀속.pdf",
                mime="application/pdf",
                use_container_width=True,
                key="btn_dl_review_pdf",
                help="현재 화면의 법령·심판례·절세누락 12대 정밀 오류 검토 내역을 A4 PDF로 다운로드합니다.",
            )
    with c_close:
        if st.button("닫기", type="primary", use_container_width=True, key="btn_close_dlg_review"):
            st.rerun()

    if s.get("pro_audit_comment"):
        with st.container(border=True):
            c_pro_hdr, c_pro_pdf = st.columns([3.0, 1.25])
            with c_pro_hdr:
                st.markdown("##### 👑 Pro/Argon AI 심층 세무진단 의견")
            with c_pro_pdf:
                if not str(s["pro_audit_comment"]).startswith("❌"):
                    with st.container(key="ec_btn_pdf_rev_pro"):
                        st.download_button(
                            "📕 심층진단 포함 PDF 다운",
                            data=_build_review_pdf_bytes(s, items, pro_comment=str(s.get("pro_audit_comment") or "")),
                            file_name=f"통합고용_심층진단_{corp_fn}_{tax_yr}귀속.pdf",
                            mime="application/pdf",
                            use_container_width=True,
                            key="btn_dl_pro_pdf",
                            help="12대 정밀 오류 검토 내역과 Pro/Argon AI 심층 세무진단 코멘트를 함께 A4 PDF로 다운로드합니다.",
                        )
            st.markdown(s["pro_audit_comment"])


@st.dialog("사원 추가")
def _dlg_add_employee():
    s = _S()
    shown_years = _years(s)
    sub_list = s.get("sub_biz_list") or []
    is_multi_wp = len(sub_list) > 0

    st.caption("필수(*) 항목을 입력한 뒤 [확인]을 누르면 사원표에 즉시 반영됩니다.")

    if is_multi_wp:
        default_wp = _default_workplace_label(s)
        wp_opts = [default_wp]
        for sb in sub_list:
            sb_nm = str((sb or {}).get("상호") or "").strip()
            if sb_nm and sb_nm not in wp_opts:
                wp_opts.append(sb_nm)
        if R.DEFAULT_WORKPLACE_NAME not in wp_opts:
            wp_opts.append(R.DEFAULT_WORKPLACE_NAME)
        wp_val = st.selectbox("사업장", options=wp_opts, index=0, key="dlg_add_emp_wp")
    else:
        wp_val = R.DEFAULT_WORKPLACE_NAME

    c1, c2 = st.columns(2)
    with c1:
        name_in = st.text_input("성명 *", placeholder="예: 홍길동", key="dlg_add_emp_name")
        hire_in = st.text_input("입사일 * (YYYY-MM-DD)", placeholder="예: 2026-04-01", key="dlg_add_emp_hire")
        retire_in = st.text_input("퇴사일 (선택, YYYY-MM-DD)", placeholder="재직 중이면 비워두세요", key="dlg_add_emp_retire")
        mil_in = st.number_input(
            "병역개월 (선택, 기본 0)",
            min_value=0,
            max_value=R.MILITARY_MAX_MONTHS,
            value=0,
            step=1,
            key="dlg_add_emp_mil",
        )
    with c2:
        birth_in = st.text_input("생년월일 * (YYYY-MM-DD)", placeholder="예: 1995-05-15", key="dlg_add_emp_birth")
        default_emp_idx = R.EMP_TYPES.index(R.EMP_REGULAR) if R.EMP_REGULAR in R.EMP_TYPES else 0
        emp_in = st.selectbox("고용형태 *", options=R.EMP_TYPES, index=default_emp_idx, key="dlg_add_emp_type")
        contract_in = st.text_input(
            "근로계약 체결일 (선택, 비우면 입사일)",
            placeholder="비워두면 입사일과 동일하게 적용",
            key="dlg_add_emp_contract",
        )

    name_str = (name_in or "").strip()
    birth_raw = (birth_in or "").strip()
    hire_raw = (hire_in or "").strip()
    retire_raw = (retire_in or "").strip()
    contract_raw = (contract_in or "").strip()

    birth_dt = H.parse_date(birth_raw) if birth_raw else None
    hire_dt = H.parse_date(hire_raw) if hire_raw else None
    retire_dt = H.parse_date(retire_raw) if retire_raw else None
    contract_dt = H.parse_date(contract_raw) if contract_raw else hire_dt

    if birth_raw and birth_dt is None:
        st.error("생년월일 형식이 올바르지 않습니다. (예: 1995-05-15)")
    if hire_raw and hire_dt is None:
        st.error("입사일 형식이 올바르지 않습니다. (예: 2026-04-01)")

    opt_date_err = False
    if retire_raw and retire_dt is None:
        st.error("퇴사일 형식이 올바르지 않습니다. (예: 2026-03-31)")
        opt_date_err = True
    if contract_raw and H.parse_date(contract_raw) is None:
        st.error("근로계약 체결일 형식이 올바르지 않습니다. (예: 2026-04-01)")
        opt_date_err = True

    missing_req = not (name_str and birth_dt and hire_dt and emp_in)

    retire_order_err = False
    if hire_dt and retire_dt and hire_dt > retire_dt:
        st.error("입사일이 퇴사일보다 늦습니다 (입사일 > 퇴사일). 날짜를 확인해 주세요.")
        retire_order_err = True

    if hire_dt and shown_years:
        min_yr, max_yr = min(shown_years), max(shown_years)
        if hire_dt.year < min_yr or hire_dt.year > max_yr:
            st.warning(
                f"입사일({hire_dt.isoformat()})이 현재 표시 연도 범위({min_yr}~{max_yr}년) 밖입니다. "
                f"(추가는 가능하며 재직 연도에 자동 반영됩니다)"
            )

    is_dup = False
    if name_str and birth_dt:
        for ep in (s.get("people") or {}).values():
            if str(ep.get("성명") or "").strip() == name_str and H.parse_date(ep.get("생년월일")) == birth_dt:
                is_dup = True
                break

    if is_dup:
        st.warning(
            f"⚠️ 같은 성명({name_str})·생년월일({birth_dt.isoformat()}) 사원이 이미 존재합니다 (중복 가능성). "
            f"동일인이 아닌 경우 [그래도 추가] 버튼을 눌러 추가하세요."
        )

    cannot_add = missing_req or opt_date_err or retire_order_err

    def _clear_dlg_keys():
        for k in (
            "dlg_add_emp_name",
            "dlg_add_emp_birth",
            "dlg_add_emp_hire",
            "dlg_add_emp_retire",
            "dlg_add_emp_contract",
            "dlg_add_emp_mil",
            "dlg_add_emp_type",
            "dlg_add_emp_wp",
        ):
            st.session_state.pop(k, None)

    def _commit_new_employee():
        seq = int(s.get("next_pid_seq", 1))
        s["next_pid_seq"] = seq + 1
        pid = f"manual_{seq}_{uuid.uuid4().hex[:6]}"
        eff_contract = (contract_dt or hire_dt).isoformat()
        eff_retire = retire_dt.isoformat() if retire_dt else ""
        s["people"][pid] = {
            "pid": pid,
            "_manual": True,
            "사업장명": wp_val,
            "연도별_사업장명": {},
            "성명": name_str,
            "생년월일": birth_dt.isoformat(),
            "입사일": hire_dt.isoformat(),
            "퇴사일": eff_retire,
            "계약체결일": eff_contract,
            "병역개월": int(mil_in or 0),
            "월급여": {},
            "연도별_퇴사일": {},
            "_confirmed": [],
        }
        s["emp_quick_filter"] = "ALL"
        target_yrs = set(_all_possible_years(s)) | {hire_dt.year}
        for y in target_yrs:
            yrec = P.new_year_rec()
            yrec["고용유형"] = emp_in
            if emp_in != R.EMP_REGULAR:
                yrec["_user_set"] = ["고용유형"]
            s["year_recs"].setdefault(y, {})[pid] = yrec
            s["grid_ver"][y] = s["grid_ver"].get(y, 0) + 1
        st.session_state.pop(_CALC_CACHE_KEY, None)
        s.pop("totals_snapshot", None)
        s.pop("_report_artifact_cache", None)
        _clear_dlg_keys()
        _save_ec_to_disk(s)
        st.rerun()

    st.markdown("<div class='ec-nav-divider' style='margin:10px 0;'></div>", unsafe_allow_html=True)
    if is_dup:
        c_ok, c_force, c_cancel = st.columns([1.2, 1.4, 1.2])
        with c_ok:
            st.button("확인", type="primary", use_container_width=True, disabled=True, key="btn_dlg_add_emp_ok")
        with c_force:
            if st.button("그래도 추가", type="primary", use_container_width=True, disabled=cannot_add, key="btn_dlg_add_emp_force"):
                _commit_new_employee()
        with c_cancel:
            if st.button("취소", use_container_width=True, key="btn_dlg_add_emp_cancel"):
                _clear_dlg_keys()
                st.rerun()
    else:
        c_ok, c_cancel = st.columns([1.5, 1.5])
        with c_ok:
            if st.button("확인", type="primary", use_container_width=True, disabled=cannot_add, key="btn_dlg_add_emp_ok"):
                _commit_new_employee()
        with c_cancel:
            if st.button("취소", use_container_width=True, key="btn_dlg_add_emp_cancel"):
                _clear_dlg_keys()
                st.rerun()


def _grid_options(
    df: pd.DataFrame,
    totals: dict,
    year: int = 2026,
    show_b2: bool = True,
    show_b3: bool = True,
) -> dict:
    gb = GridOptionsBuilder.from_dataframe(df)
    gb.configure_default_column(
        resizable=True,
        sortable=False,
        filter=False,
        suppressMenu=True,
        suppressHeaderMenuButton=True,
        suppressMovable=True,
        suppressSizeToFit=True,
        editable=JS_LOCKED,
        cellStyle=JS_STYLE,
    )
    gb.configure_grid_options(
        singleClickEdit=True,
        stopEditingWhenCellsLoseFocus=True,
        rowHeight=32,
        headerHeight=32,
        groupHeaderHeight=44,
        suppressMenuHide=True,
        suppressAutoSize=True,
        suppressRowVirtualisation=True,
        suppressColumnVirtualisation=True,
        alwaysShowHorizontalScroll=True,
    )
    go = gb.build()

    def _blk_style(bg_hex: str, fg_hex: str = "#0f172a", bold: bool = True) -> dict:
        return {
            "fontFamily": "Pretendard, Malgun Gothic, sans-serif",
            "fontSize": "12.5px",
            "backgroundColor": bg_hex,
            "color": fg_hex,
            "fontWeight": "800" if bold else "600",
            "textAlign": "center",
            "paddingLeft": "2px",
            "paddingRight": "2px",
            "overflow": "visible",
            "textOverflow": "clip",
        }

    b3_title_2l, b4_title_2l, b5_title_2l = _block_titles_for_year(year, two_line=True)

    grp_pinned_children = [
        {
            "field": "사업장명",
            "headerName": "사업장명",
            "pinned": "left",
            "width": 76,
            "minWidth": 76,
            "suppressSizeToFit": True,
            "editable": True,
            "cellStyle": JS_STYLE_WORKPLACE,
        },
        {
            "field": "성명",
            "headerName": "성명",
            "pinned": "left",
            "width": 98,
            "minWidth": 88,
            "suppressSizeToFit": True,
            "editable": JS_LOCKED,
            "cellStyle": JS_STYLE,
            "valueFormatter": JS_NAME_FMT,
        },
    ]

    grp1_children = [
        {
            "field": "생년월일",
            "headerName": "생년월일",
            "width": 82,
            "minWidth": 82,
            "suppressSizeToFit": True,
            "editable": JS_LOCKED,
            "cellStyle": JS_STYLE_CENTER,
            "valueFormatter": JS_DATE_FMT,
        },
        {
            "field": "입사일",
            "headerName": "입사일",
            "width": 82,
            "minWidth": 82,
            "suppressSizeToFit": True,
            "editable": JS_LOCKED,
            "cellStyle": JS_STYLE_CENTER,
            "valueFormatter": JS_DATE_FMT,
        },
        {
            "field": "퇴사일",
            "headerName": "퇴사일",
            "width": 82,
            "minWidth": 82,
            "suppressSizeToFit": True,
            "editable": JS_LOCKED,
            "cellStyle": JS_STYLE_CENTER,
            "valueFormatter": JS_DATE_FMT,
        },
        {
            "field": "취업연령",
            "headerName": "취업연령",
            "width": 64,
            "minWidth": 64,
            "suppressSizeToFit": True,
            "editable": False,
            "cellStyle": _blk_style("#f8fafc", "#334155", bold=False),
        },
        {
            "field": "고용유형",
            "headerName": "고용유형",
            "width": 108,          # 셀은 컴팩트하게 유지하고 클릭 시 팝업(260px)으로 전체 표시
            "minWidth": 108,
            "suppressSizeToFit": True,
            "editable": JsCode("function(p){ return !p.node.rowPinned; }"),
            "cellStyle": JS_STYLE,
            "cellEditor": "agSelectCellEditor",
            "cellEditorPopup": True,
            "cellEditorParams": {"values": R.EMP_TYPES, "valueListMaxWidth": 260},
        },
        {
            "field": "제외사유",
            "headerName": "제외사유",
            "width": 132,
            "minWidth": 132,
            "suppressSizeToFit": True,
            "editable": JS_LOCKED,
            "cellStyle": JS_STYLE_EXCL,
            "cellEditor": "agSelectCellEditor",
            "cellEditorParams": {"values": [("실제근로 1년미만" if (year >= 2026 and x == R.EXCL_UNDER_1Y) else x) for x in R.EXCL_REASONS]},
        },
        {
            "field": "병역개월",
            "headerName": "병역(월)",
            "width": 64,
            "minWidth": 64,
            "suppressSizeToFit": True,
            "editable": JS_LOCKED,
            "cellStyle": JS_STYLE_CENTER,
            "cellEditor": "agNumberCellEditor",
            "cellEditorParams": {"min": 0, "max": R.MILITARY_MAX_MONTHS, "precision": 0},
        },
        {
            "field": "청년등",
            "headerName": "청년등 구분",
            "width": 126,
            "minWidth": 126,
            "suppressSizeToFit": True,
            "editable": JS_LOCKED,
            "cellStyle": JS_STYLE_YOUTH,
            "cellEditor": "agSelectCellEditor",
            "cellEditorParams": JS_YOUTH_PARAMS,
        },
        {
            "field": "상시",
            "headerName": "상시",
            "width": 52,
            "minWidth": 52,
            "suppressSizeToFit": True,
            "editable": True,
            "cellStyle": JS_STYLE_REGULAR,
            "cellEditor": "agSelectCellEditor",
            "cellEditorParams": {"values": ["O", "X"]},
        },
    ]

    grp2_children = []
    for i, c in enumerate(MONTH_COLS, start=1):
        grp2_children.append(
            {
                "field": c,
                "headerName": f"{i}월",
                "width": 44,       # 클릭 시 팝업(90px)으로 표시되므로 셀 폭은 한 화면 수납을 위해 슬림화
                "minWidth": 44,
                "suppressSizeToFit": True,
                "suppressMenu": True,
                "suppressHeaderMenuButton": True,
                "editable": JS_MONTH_EDITABLE,
                "cellStyle": JS_MONTH_STYLE,
                "cellEditor": "agSelectCellEditor",
                "cellEditorPopup": True,
                "cellEditorParams": {"values": R.MONTH_CHOICES, "valueListMaxWidth": 90},
                "valueFormatter": JS_NUM_FMT,
            }
        )
    grp2_children.append(
        {
            "field": "합계",
            "headerName": "월합계",
            "width": 58,
            "minWidth": 58,
            "suppressSizeToFit": True,
            "editable": False,
            "valueFormatter": JS_NUM_FMT,
            "cellStyle": _blk_style("#f1f5f9", "#0f172a"),
        }
    )

    grp3_children = [
        {"field": "b1_yth", "headerName": "청년등", "width": 60, "minWidth": 60, "suppressSizeToFit": True, "editable": False, "valueFormatter": JS_DEC2_FMT, "cellStyle": _blk_style("#f0fdf4", "#15803d")},
        {"field": "b1_gen", "headerName": "청년외", "width": 60, "minWidth": 60, "suppressSizeToFit": True, "editable": False, "valueFormatter": JS_DEC2_FMT, "cellStyle": _blk_style("#f8fafc", "#334155")},
        {"field": "b1_reg", "headerName": "상시", "width": 60, "minWidth": 60, "suppressSizeToFit": True, "editable": False, "valueFormatter": JS_DEC2_FMT, "cellStyle": _blk_style("#e0f2fe", "#0369a1")},
    ]

    grp4_children = [
        {"field": "b2_yth", "headerName": "청년등", "width": 60, "minWidth": 60, "suppressSizeToFit": True, "editable": False, "valueFormatter": JS_DEC2_FMT, "cellStyle": _blk_style("#eff6ff", "#1d4ed8")},
        {"field": "b2_gen", "headerName": "청년외", "width": 60, "minWidth": 60, "suppressSizeToFit": True, "editable": False, "valueFormatter": JS_DEC2_FMT, "cellStyle": _blk_style("#f8fafc", "#475569")},
        {"field": "b2_reg", "headerName": "상시", "width": 60, "minWidth": 60, "suppressSizeToFit": True, "editable": False, "valueFormatter": JS_DEC2_FMT, "cellStyle": _blk_style("#eff6ff", "#1e3a8a")},
    ]

    grp5_children = [
        {"field": "b3_yth", "headerName": "청년등", "width": 60, "minWidth": 60, "suppressSizeToFit": True, "editable": False, "valueFormatter": JS_DEC2_FMT, "cellStyle": _blk_style("#f5f3ff", "#6d28d9")},
        {"field": "b3_gen", "headerName": "청년외", "width": 60, "minWidth": 60, "suppressSizeToFit": True, "editable": False, "valueFormatter": JS_DEC2_FMT, "cellStyle": _blk_style("#f8fafc", "#475569")},
        {"field": "b3_reg", "headerName": "상시", "width": 60, "minWidth": 60, "suppressSizeToFit": True, "editable": False, "valueFormatter": JS_DEC2_FMT, "cellStyle": _blk_style("#f5f3ff", "#4c1d95")},
    ]

    extra_hidden_fields = {"pid", "b4_yth", "b4_gen", "b4_reg"}
    if not show_b2:
        extra_hidden_fields.update({"b2_yth", "b2_gen", "b2_reg"})
    if not show_b3:
        extra_hidden_fields.update({"b3_yth", "b3_gen", "b3_reg"})

    hidden_cols = [
        {"field": c, "hide": True, "editable": False}
        for c in df.columns
        if c.startswith("_") or c in extra_hidden_fields
    ]

    col_defs = [
        {"headerName": "사업장 · 성명", "children": grp_pinned_children},
        {"headerName": "1. 사원 계산기 (생년월일 · 입퇴사 · 상시/청년 판정)", "children": grp1_children},
        {"headerName": "2. 매월 말 현재 상시근로자 수 (1월 ~ 12월)", "children": grp2_children},
        {"headerName": b3_title_2l, "children": grp3_children},
    ]
    if show_b2:
        col_defs.append({"headerName": b4_title_2l, "children": grp4_children})
    if show_b3:
        col_defs.append({"headerName": b5_title_2l, "children": grp5_children})
    col_defs.extend(hidden_cols)
    go["columnDefs"] = col_defs

    n = totals["months_in_year"]
    trunc_mode = R.calc_method_short_label(year, eval_year=year)
    pinned = [
        {
            "사업장명": "합산합계",
            "성명": "상시근로자",
            "생년월일": "",
            "고용유형": f"÷{n}월({'사원별절사' if R.calc_method_for(year, eval_year=year)=='B' else '합계절사'})",
            **{MONTH_COLS[i]: totals["월별_상시"][i] for i in range(12)},
            "합계": totals["상시_합계"],
            "b1_yth": totals["b1_yth"],
            "b1_gen": totals["b1_gen"],
            "b1_reg": totals["b1_reg"],
            "b2_yth": totals["b2_yth"],
            "b2_gen": totals["b2_gen"],
            "b2_reg": totals["b2_reg"],
            "b3_yth": totals["b3_yth"],
            "b3_gen": totals["b3_gen"],
            "b3_reg": totals["b3_reg"],
            "b4_yth": totals["b4_yth"],
            "b4_gen": totals["b4_gen"],
            "b4_reg": totals["b4_reg"],
        },
        {
            "사업장명": "합산합계",
            "성명": "청년등",
            "생년월일": "",
            "고용유형": "각 코호트 기준",
            **{MONTH_COLS[i]: totals["월별_청년등"][i] for i in range(12)},
            "합계": totals["청년등_합계"],
            "b1_yth": totals["b1_yth"],
            "b1_gen": None,
            "b1_reg": None,
            "b2_yth": totals["b2_yth"],
            "b2_gen": None,
            "b2_reg": None,
            "b3_yth": totals["b3_yth"],
            "b3_gen": None,
            "b3_reg": None,
            "b4_yth": totals["b4_yth"],
            "b4_gen": None,
            "b4_reg": None,
        },
        {
            "사업장명": "합산합계",
            "성명": "청년등 외",
            "생년월일": "",
            "고용유형": "상시 - 청년등",
            **{MONTH_COLS[i]: totals["월별_청년외"][i] for i in range(12)},
            "합계": totals["청년외_합계"],
            "b1_yth": None,
            "b1_gen": totals["b1_gen"],
            "b1_reg": None,
            "b2_yth": None,
            "b2_gen": totals["b2_gen"],
            "b2_reg": None,
            "b3_yth": None,
            "b3_gen": totals["b3_gen"],
            "b3_reg": None,
            "b4_yth": None,
            "b4_gen": totals["b4_gen"],
            "b4_reg": None,
        },
    ]
    go["pinnedBottomRowData"] = pinned
    return go


def _norm(v) -> str:
    if v is None:
        return ""
    try:
        if pd.isna(v):
            return ""
    except (TypeError, ValueError):
        pass
    return str(v).strip()


def _apply_changes(s: dict, year: int, sent: list[dict], back: pd.DataFrame) -> bool:
    if back is None or back.empty or "pid" not in back.columns:
        return False
    before = {r["pid"]: r for r in sent}
    changed = False
    for _, nr in back.iterrows():
        pid = nr.get("pid")
        old = before.get(pid)
        if old is None or pid not in s["people"]:
            continue
        p, yrec = s["people"][pid], s["year_recs"][year][pid]
        us = yrec.setdefault("_user_set", [])

        nv_wp = _norm(nr.get("사업장명"))
        if nv_wp != _norm(old.get("사업장명")):
            p["사업장명"] = nv_wp
            p.setdefault("연도별_사업장명", {})[str(year)] = nv_wp
            changed = True

        for f in ("성명", "생년월일", "입사일", "퇴사일"):
            nv = _norm(nr.get(f))
            if nv != _norm(old.get(f)):
                d = H.parse_date(nv) if f != "성명" else None
                val_to_save = nv if f == "성명" else (d.isoformat() if d else nv)
                p[f] = val_to_save
                if f == "퇴사일":
                    p.setdefault("연도별_퇴사일", {})[str(year)] = val_to_save
                changed = True

        nv = _norm(nr.get("병역개월"))
        if nv != _norm(old.get("병역개월")) and not _same_num(nv or "0", _norm(old.get("병역개월")) or "0"):
            try:
                months = int(float(nv or 0))
            except ValueError:
                months = 0
            p["병역개월"] = max(0, min(months, R.MILITARY_MAX_MONTHS))
            changed = True

        nv = _norm(nr.get("고용유형"))
        if nv and nv != _norm(old.get("고용유형")):
            yrec["고용유형"] = nv
            yrec["_user_set"] = [x for x in us if x not in ("제외사유", "청년등")] + ["고용유형"]
            us = yrec["_user_set"]
            if nv not in R.EMP_AUTO_EXCLUDE and float(old.get("합계") or 0.0) == 0.0:
                yrec["월_override"] = {}
            changed = True

        nv = _norm(nr.get("제외사유"))
        if nv == "실제근로 1년미만":
            nv = R.EXCL_UNDER_1Y
        old_excl = R.EXCL_UNDER_1Y if _norm(old.get("제외사유")) == "실제근로 1년미만" else _norm(old.get("제외사유"))
        if nv and nv != old_excl:
            yrec["제외사유"] = nv
            yrec["_user_set"] = [x for x in us if x != "청년등"] + (["제외사유"] if "제외사유" not in us else [])
            us = yrec["_user_set"]
            changed = True

        nv = _norm(nr.get("청년등"))
        if nv and nv != _norm(old.get("청년등")):
            yrec["청년등"] = nv
            if "청년등" not in us:
                us.append("청년등")
            changed = True

        nv = _norm(nr.get("상시"))
        if nv in ("O", "X") and nv != _norm(old.get("상시")):
            if nv == old.get("_sauto"):
                yrec["상시_override"] = ""
            else:
                yrec["상시_override"] = nv
                yrec["_unlocked"] = True
            changed = True

        mo = yrec.setdefault("월_override", {})
        for i, c in enumerate(MONTH_COLS, start=1):
            nv, ov = _norm(nr.get(c)), _norm(old.get(c))
            if nv == ov or (nv and ov and _same_num(nv, ov)):
                continue
            if nv == R.MONTH_AUTO or nv == "":
                mo.pop(str(i), None)
            else:
                try:
                    mo[str(i)] = float(nv)
                except ValueError:
                    continue
            changed = True
    return changed


def _same_num(a: str, b: str) -> bool:
    try:
        return abs(float(a) - float(b)) < 1e-9
    except ValueError:
        return False


def _year_role_description(s: dict, tax_year: int, year: int) -> str:
    has_y1 = _has_year_data(s, year - 1)
    has_y2 = _has_year_data(s, year - 2)
    active_parts = [f"{year%100:02d}년 세액공제"]
    if has_y1:
        active_parts.append(f"{(year-1)%100:02d}년 1차 사후관리")
    if has_y2:
        active_parts.append(f"{(year-2)%100:02d}년 2차 사후관리")
    omitted = []
    if not has_y1:
        omitted.append(f"{(year-1)%100:02d}년 1차")
    if not has_y2:
        omitted.append(f"{(year-2)%100:02d}년 2차")
    omit_note = f" (미업로드 생략: {', '.join(omitted)} 사후관리)" if omitted else ""
    prefix = "당해 귀속" if year == tax_year else ("직전 귀속" if year == tax_year - 1 else "전전 귀속")
    return f"{prefix} · {' · '.join(active_parts)}{omit_note}"


def _render_year(s: dict, year: int, room_key: str) -> tuple[dict, dict]:
    rows, computed, totals = _build_year_rows(s, year)
    tax_year = int(s["tax_year"])
    role_desc = _year_role_description(s, tax_year, year)
    last_m = H.detect_last_paid_month(s.get("people") or {}, year)
    mid_yr_badge = (
        f" &nbsp;·&nbsp; <span style='color:#0369a1;font-weight:700;'>⚡ {last_m}월 가결산 ({last_m+1}~12월 {'연말재직 자동가정' if s.get('assume_year_end', True) else '미도래 0 처리'})</span>"
        if last_m < 12
        else ""
    )

    corp_nm = (s.get("biz", {}).get("상호") or "상호미입력").strip()

    # ── 연도별 상시근로자 명세 헤더 라인 + [기업규모 선택칸 (중소/중견/일반기업)] + 맨 오른쪽 붉은색 [📕 PDF 다운] 버튼 ──
    def_sz_s2 = R.normalize_corp_size(s.get("corp_size_default") or s.get("biz", {}).get("기업구분", "중소기업"))
    cur_yr_sz = _cohort_corp_size(s, year, def_sz_s2)
    cur_yr_sz_lbl = R.format_corp_size_label(cur_yr_sz, short=True)
    sz_pill_color = (
        "background:#dcfce7;color:#166534;border:1px solid #86efac;"
        if cur_yr_sz == "중소기업"
        else (
            "background:#dbeafe;color:#1e40af;border:1px solid #93c5fd;"
            if cur_yr_sz == "중견기업"
            else "background:#fef3c7;color:#92400e;border:1px solid #fcd34d;"
        )
    )
    diff_pill_html = (
        "<span style='background:#fff7ed;color:#c2410c;border:1px solid #fdba74;padding:1px 6px;"
        "border-radius:999px;font-size:0.74rem;font-weight:800;margin-left:5px;'>기본값과 다름</span>"
        if cur_yr_sz != def_sz_s2
        else ""
    )
    m_code_yr = R.calc_method_for(year, eval_year=year)
    m_lbl_yr = R.calc_method_short_label(year, eval_year=year)
    m_pill_style = (
        "background:#dcfce7;color:#15803d;border:1px solid #86efac;"
        if (int(year) >= 2026 or m_code_yr == "B")
        else "background:#fef3c7;color:#b45309;border:1px solid #fcd34d;"
    )
    method_badge_html = (
        f"<span style='{m_pill_style}padding:2px 8px;border-radius:999px;font-size:0.76rem;font-weight:800;margin-left:6px;'>"
        f"📐 {m_lbl_yr}</span>"
    )
    # 우측에 이미 연도별 기업규모 드롭다운이 있으므로 헤더 좌측에는 계산방식 배지(+기본값과 다를 때만 알림 배지)만 간결히 표시
    yr_sz_badge_html = f"{method_badge_html}{diff_pill_html}"
    c_hdr, c_sz, c_pdf = st.columns([4.90, 1.25, 0.85], vertical_alignment="center")
    with c_hdr:
        st.markdown(
            f"<div class='ec-year-header'>"
            f"<span class='ec-year-title'>📅 {year}년 귀속 상시근로자 명세 ({len(rows)}명){yr_sz_badge_html}</span>"
            f"<span class='ec-year-sub'>{role_desc}{mid_yr_badge}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
    with c_sz:
        yr_sz_ver = int(s.get("yr_sz_ver", 0))
        sel_yr_sz = st.selectbox(
            f"{year}년 기업규모",
            options=R.CORP_SIZES,
            index=R.CORP_SIZES.index(cur_yr_sz) if cur_yr_sz in R.CORP_SIZES else 0,
            format_func=lambda x: f"🏢 {year%100:02d}년: {'일반기업(대기업)' if x == '일반기업' else x}",
            label_visibility="collapsed",
            key=f"ec_yr_corp_size_{year}_{yr_sz_ver}",
            help=(
                f"📌 [{year}년 귀속 기업규모 선택 — 중소기업 / 중견기업 / 일반기업(대기업)]\n"
                f"• 1단계·사이드바의 해당 연도 기업규모와 동일한 상태를 공유합니다.\n"
                f"• 변경 시 근로계약 체결연도({year}년) 기업규모에 따른 청년 유예기간(2026년 이후 계약: 중소·중견 4년 / 일반 3년, "
                f"2025년 계약: 중소·중견 3년 / 일반 2년 — 계약일로부터 유예연수가 되는 날이 속한 달부터 청년에서 제외, "
                f"예: 2025.5.1. 일반기업 계약 → 2027년 5월부터 제외되어 2027년 1~4월 4개월 청년 인정) 인원계산과 "
                f"3·4단계 공제단가, 최소고용증가인원(중견 5명 / 일반 10명), 공제기간(중소·중견 3년 / 일반 2년), 2년 사후관리 세액계산에 즉시 반영됩니다."
            ),
        )
        if sel_yr_sz != cur_yr_sz:
            R.apply_corp_size_year_change(s, year, sel_yr_sz)
            s["yr_sz_ver"] = yr_sz_ver + 1
            for y_all in _all_possible_years(s):
                s["grid_ver"][y_all] = s["grid_ver"].get(y_all, 0) + 1
            s.pop("_report_artifact_cache", None)
            _save_ec_to_disk(s)
            st.rerun()
    with c_pdf:
        with st.container(key=f"ec_btn_pdf_yr_{year}"):
            st.download_button(
                "📕 PDF 다운",
                data=_build_schedule_pdf_bytes(s, [year], include_summary=False),
                file_name=f"{corp_nm}_{year}년귀속_상시근로자명세.pdf",
                mime="application/pdf",
                use_container_width=True,
                key=f"dl_pdf_yr_{year}",
                help=f"{year}년 귀속 상시근로자 명세 및 사후관리 판정표(A4 가로 PDF)를 다운로드합니다.",
            )

    if not rows:
        st.info(f"{year}년에 근무한 근로자가 없습니다. {year}년 원천징수부를 올렸는지 확인하거나 아래 [➕ 사원 추가]로 입력하세요.")
        return computed, totals

    for _r in rows:
        if year >= 2026 and _r.get("제외사유") == R.EXCL_UNDER_1Y:
            _r["제외사유"] = "실제근로 1년미만"
    # 전체 원본 rows를 last_sent에 보존하여 필터링 상태에서도 수정사항이 누락 없이 반영되게 함
    s["last_sent"][year] = rows

    q_filter = str(s.get("emp_quick_filter") or "ALL")
    disp_rows = rows
    if q_filter == "CHECK":
        disp_rows = [
            r for r in rows
            if r.get("상시") == "X"
            or r.get("제외사유") not in ("", R.EXCL_NONE)
            or not str(r.get("생년월일") or "").strip()
            or not str(r.get("입사일") or "").strip()
            or bool(r.get("_nopay_months"))
        ]
    elif q_filter == "SAVING":
        def _is_saving_cand(r_item: dict) -> bool:
            if str(r_item.get("청년등") or "") not in ("", R.YOUTH_NONE):
                return True
            try:
                age_v = int(float(str(r_item.get("취업연령") or "0").replace("세", "").strip() or 0))
            except ValueError:
                age_v = 0
            return (35 <= age_v <= 40) and int(r_item.get("병역개월") or 0) == 0

        disp_rows = [r for r in rows if _is_saving_cand(r)]
    elif q_filter == "MOVED":
        yr_prefix = f"{year}-"
        disp_rows = [
            r for r in rows
            if str(r.get("입사일") or "").startswith(yr_prefix)
            or str(r.get("퇴사일") or "").startswith(yr_prefix)
            or ("→" in str(r.get("사업장명") or ""))
        ]

    if not disp_rows:
        st.caption(f"ℹ️ {year}년 귀속 명세({len(rows)}명) 중 현재 선택한 필터 조건에 해당하는 사원이 없습니다. (상단 필터를 '전체 사원 보기'로 변경하면 전체 명단이 표시됩니다.)")
        return computed, totals

    df = pd.DataFrame(disp_rows)
    for _mc in MONTH_COLS:
        if _mc in df.columns:
            df[_mc] = df[_mc].apply(lambda v: "" if (v is None or pd.isna(v) or v == "") else f"{float(v):g}")
    ver = s["grid_ver"].get(year, 0)
    show_all_4 = bool(s.get("show_all_4_blocks", True))
    force_empty = bool(s.get("show_empty_pm_blocks", False))
    has_y1 = _has_year_data(s, year - 1)
    has_y2 = _has_year_data(s, year - 2)
    show_b2 = show_all_4 and (has_y1 or force_empty)
    show_b3 = show_all_4 and (has_y2 or force_empty)

    custom_ag_css = {
        ".ag-header": {"background-color": "#1e293b !important", "color": "#ffffff !important"},
        ".ag-header-group-cell": {
            "background-color": "#0f172a !important",
            "color": "#f8fafc !important",
            "font-weight": "800 !important",
            "font-family": "'Pretendard', 'Malgun Gothic', sans-serif !important",
            "font-size": "12.6px !important",
            "border-right": "1px solid #475569 !important",
            "justify-content": "center !important",
            "padding-left": "3px !important",
            "padding-right": "3px !important",
        },
        ".ag-header-group-cell-label": {
            "justify-content": "center !important",
            "align-items": "center !important",
            "text-align": "center !important",
            "width": "100% !important",
            "overflow": "visible !important",
            "text-overflow": "clip !important",
        },
        ".ag-header-group-text": {
            "white-space": "pre-line !important",
            "text-align": "center !important",
            "line-height": "1.25 !important",
            "overflow": "visible !important",
            "text-overflow": "clip !important",
            "font-weight": "800 !important",
            "color": "#f8fafc !important",
        },
        ".ag-header-cell": {
            "padding-left": "2px !important",
            "padding-right": "2px !important",
            "border-right": "1px solid #334155 !important",
        },
        ".ag-header-cell-label": {
            "justify-content": "center !important",
            "overflow": "visible !important",
            "text-overflow": "clip !important",
        },
        ".ag-header-cell-text": {
            "color": "#ffffff !important",
            "font-weight": "700 !important",
            "font-family": "'Pretendard', 'Malgun Gothic', sans-serif !important",
            "font-size": "12.4px !important",
            "overflow": "visible !important",
            "text-overflow": "clip !important",
            "white-space": "nowrap !important",
        },
        ".ag-header-cell-menu-button, .ag-header-icon": {
            "display": "none !important",
        },
        ".ag-cell": {
            "padding-left": "3px !important",
            "padding-right": "3px !important",
            "overflow": "visible !important",
            "text-overflow": "clip !important",
        },
        ".ag-root-wrapper": {"border-radius": "8px !important", "border": "1px solid #cbd5e1 !important"},
    }
    resp = AgGrid(
        df,
        gridOptions=_grid_options(df, totals, year=year, show_b2=show_b2, show_b3=show_b3),
        update_mode=GridUpdateMode.VALUE_CHANGED,
        allow_unsafe_jscode=True,
        theme="balham",
        custom_css=custom_ag_css,
        key=f"ec_grid_{year}_{ver}_{cur_yr_sz}_{int(show_b2)}_{int(show_b3)}_{int(s.get('assume_year_end', True))}_{int(s.get('include_unpaid_hire_month', True))}_{s.get('emp_quick_filter', 'ALL')}",
        height=min(720, 128 + 32 * (len(rows) + 3)),
        fit_columns_on_grid_load=False,
    )
    back = getattr(resp, "data", None)
    if back is None:
        try:
            back = resp["data"]
        except Exception:
            back = None
    if isinstance(back, pd.DataFrame) and _apply_changes(s, year, rows, back):
        for y in _all_possible_years(s):
            s["grid_ver"][y] = s["grid_ver"].get(y, 0) + 1
        _save_ec_to_disk(s)
        st.rerun()

    b3_title, b4_title, b5_title = _block_titles_for_year(year, two_line=False)
    kpi_chips = [
        f"<div class='ec-kpi-chip b3'>"
        f"<span class='kpi-tag'>👥 {b3_title}</span>"
        f"<span class='kpi-main'>상시 {totals['b1_reg']:.2f}명</span>"
        f"<span class='kpi-sub'>(청년등 <b>{totals['b1_yth']:.2f}</b> · 청년외 <b>{totals['b1_gen']:.2f}</b>)</span>"
        f"</div>"
    ]
    if show_b2:
        kpi_chips.append(
            f"<div class='ec-kpi-chip b4'>"
            f"<span class='kpi-tag'>🔄 {b4_title}</span>"
            f"<span class='kpi-main'>상시 {totals['b2_reg']:.2f}명</span>"
            f"<span class='kpi-sub'>(청년등 <b>{totals['b2_yth']:.2f}</b> · 청년외 <b>{totals['b2_gen']:.2f}</b>)</span>"
            f"</div>"
        )
    if show_b3:
        kpi_chips.append(
            f"<div class='ec-kpi-chip b5'>"
            f"<span class='kpi-tag'>🛡️ {b5_title}</span>"
            f"<span class='kpi-main'>상시 {totals['b3_reg']:.2f}명</span>"
            f"<span class='kpi-sub'>(청년등 <b>{totals['b3_yth']:.2f}</b> · 청년외 <b>{totals['b3_gen']:.2f}</b>)</span>"
            f"</div>"
        )
    trunc_mode = R.calc_method_short_label(year, eval_year=year)
    # [Section 4] 같은 연도의 A·B값이 다르면 표 아래 회색 한 줄로 다른 방식의 값을 참고 표시 (계산에는 쓰지 않음)
    ref_parts = []
    a_b1_r = float(totals.get("A_b1_reg", totals["b1_reg"]))
    b_b1_r = float(totals.get("B_b1_reg", totals["b1_reg"]))
    a_b1_y = float(totals.get("A_b1_yth", totals["b1_yth"]))
    b_b1_y = float(totals.get("B_b1_yth", totals["b1_yth"]))
    a_b1_g = float(totals.get("A_b1_gen", totals["b1_gen"]))
    b_b1_g = float(totals.get("B_b1_gen", totals["b1_gen"]))
    if round(a_b1_r, 2) != round(b_b1_r, 2) or round(a_b1_y, 2) != round(b_b1_y, 2):
        if R.calc_method_for(year, eval_year=year) == "B":
            ref_parts.append(
                f"3. {year%100:02d}년 세액공제 — 합계 후 절사 참고값: 상시 {a_b1_r:.2f}명 (청년등 {a_b1_y:.2f} · 청년외 {a_b1_g:.2f})"
            )
        else:
            ref_parts.append(
                f"3. {year%100:02d}년 세액공제 — 사원별 절사 참고값: 상시 {b_b1_r:.2f}명 (청년등 {b_b1_y:.2f} · 청년외 {b_b1_g:.2f})"
            )
    if show_b2:
        a_b2_r, b_b2_r = float(totals.get("A_b2_reg", totals["b2_reg"])), float(totals.get("B_b2_reg", totals["b2_reg"]))
        a_b2_y, b_b2_y = float(totals.get("A_b2_yth", totals["b2_yth"])), float(totals.get("B_b2_yth", totals["b2_yth"]))
        a_b2_g, b_b2_g = float(totals.get("A_b2_gen", totals["b2_gen"])), float(totals.get("B_b2_gen", totals["b2_gen"]))
        if round(a_b2_r, 2) != round(b_b2_r, 2) or round(a_b2_y, 2) != round(b_b2_y, 2):
            m_b2 = R.calc_method_for(year - 1, eval_year=year)
            if m_b2 == "B":
                ref_parts.append(f"4. {(year-1)%100:02d}년 1차 사후관리 — 합계 후 절사 참고값: 상시 {a_b2_r:.2f}명 (청년등 {a_b2_y:.2f} · 청년외 {a_b2_g:.2f})")
            else:
                ref_parts.append(f"4. {(year-1)%100:02d}년 1차 사후관리 — 사원별 절사 참고값: 상시 {b_b2_r:.2f}명 (청년등 {b_b2_y:.2f} · 청년외 {b_b2_g:.2f})")
    if show_b3:
        a_b3_r, b_b3_r = float(totals.get("A_b3_reg", totals["b3_reg"])), float(totals.get("B_b3_reg", totals["b3_reg"]))
        a_b3_y, b_b3_y = float(totals.get("A_b3_yth", totals["b3_yth"])), float(totals.get("B_b3_yth", totals["b3_yth"]))
        a_b3_g, b_b3_g = float(totals.get("A_b3_gen", totals["b3_gen"])), float(totals.get("B_b3_gen", totals["b3_gen"]))
        if round(a_b3_r, 2) != round(b_b3_r, 2) or round(a_b3_y, 2) != round(b_b3_y, 2):
            m_b3 = R.calc_method_for(year - 2, eval_year=year)
            if m_b3 == "B":
                ref_parts.append(f"5. {(year-2)%100:02d}년 2차 사후관리 — 합계 후 절사 참고값: 상시 {a_b3_r:.2f}명 (청년등 {a_b3_y:.2f} · 청년외 {a_b3_g:.2f})")
            else:
                ref_parts.append(f"5. {(year-2)%100:02d}년 2차 사후관리 — 사원별 절사 참고값: 상시 {b_b3_r:.2f}명 (청년등 {b_b3_y:.2f} · 청년외 {b_b3_g:.2f})")

    ref_line_html = (
        f"<div style='margin:-20px 0 22px 4px;font-size:0.81rem;color:#64748b;font-weight:600;'>"
        f"ℹ️ 다른 계산방식 참고(계산 미사용): {' &nbsp;|&nbsp; '.join(ref_parts)}"
        f"</div>"
        if ref_parts
        else ""
    )

    # [Section 6-5] 상시근로자 명세서(별지 제10호의10) 분류와 원천징수부 분류가 다른 사원 주황 안내
    cls_diff_items = [
        f"<b>{r.get('성명')}</b> ({r.get('_class_diff_msg')})"
        for r in rows
        if r.get("_class_diff") == "1" and r.get("_class_diff_msg")
    ]
    cls_diff_html = (
        f"<div style='margin:-16px 0 20px 0;padding:8px 12px;background:#fff7ed;border:1.5px solid #fdba74;"
        f"border-left:5px solid #f97316;border-radius:8px;font-size:0.84rem;color:#9a3412;line-height:1.5;'>"
        f"🟧 <b>상시근로자 명세서(별지 제10호의10) vs 원천징수부 분류 차이 감지 ({len(cls_diff_items)}명 · 표 주황색 행 표시):</b><br>"
        + "<br>".join(f"• {it}" for it in cls_diff_items)
        + "</div>"
        if cls_diff_items
        else ""
    )

    st.markdown(
        f"<div class='ec-kpi-bar'>"
        f"<div class='ec-kpi-items'>{''.join(kpi_chips)}</div>"
        f"<span class='ec-kpi-total-pill'>총인원(연인원) <b>{totals['상시_합계']:g}명</b> ÷ {totals['months_in_year']}개월 ({trunc_mode})</span>"
        f"</div>{ref_line_html}{cls_diff_html}",
        unsafe_allow_html=True,
    )
    return computed, totals


def _render_prev_filing_summary_card(s: dict, shown_years: list[int]):
    tax_yr = int(s["tax_year"])
    t2_year = tax_yr - 2
    if t2_year in shown_years:
        return

    ps = s.setdefault("prev_summary", {})
    y_entry = ps.setdefault(
        str(t2_year),
        {
            "상시_총인원": None,
            "청년등_총인원": None,
            "상시": None,
            "청년등": None,
            "청년등_증가": None,
            "청년등외_증가": None,
            "공제세액": None,
            "2차_공제세액": None,
            "이월세액": None,
            "기추징세액": None,
        },
    )
    has_prev_doc = bool(((s.get("ext") or {}).get("prev_filing") or {}).get("연도별"))

    with st.expander(
        f"📋 {t2_year}년 귀속분(2차 사후관리 대상) 인원 확인 — 현재 {t2_year}년 원천징수부 미첨부로 표 생략됨 (기신고 숫자로 간편 입력 가능)",
        expanded=has_prev_doc,
    ):
        st.caption(
            f"💡 **{t2_year}년 귀속분 2차 사후관리(3차년도 연속공제 또는 추가납부세액)** 및 **{tax_yr-1}년 고용증가 인원 검증**을 위해 "
            f"{t2_year}년 기신고 상시·청년등 인원을 입력하거나 아래 버튼으로 {t2_year}년 사원표를 직접 열 수 있습니다."
        )
        c1, c2, c3 = st.columns([1.8, 1.8, 2.4])
        with c1:
            reg_val = st.number_input(
                f"{t2_year}년 기신고 전체 상시근로자 수",
                min_value=0.0,
                step=0.01,
                format="%.2f",
                value=None if y_entry.get("상시") is None else float(y_entry.get("상시")),
                placeholder="기신고 숫자",
                key=f"prev_sum_reg_{t2_year}",
            )
            y_entry["상시"] = reg_val
        with c2:
            yth_val = st.number_input(
                f"{t2_year}년 기신고 청년등 상시근로자 수",
                min_value=0.0,
                step=0.01,
                format="%.2f",
                value=None if y_entry.get("청년등") is None else float(y_entry.get("청년등")),
                placeholder="기신고 숫자",
                key=f"prev_sum_yth_{t2_year}",
            )
            y_entry["청년등"] = yth_val
        with c3:
            st.write("")
            if st.button(f"➕ {t2_year}년 사원정보 표 직접 열어서 계산하기", use_container_width=True, key=f"btn_open_yr_{t2_year}"):
                extra = s.setdefault("manual_extra_years", [])
                if t2_year not in extra:
                    extra.append(t2_year)
                for pid in s["people"]:
                    s["year_recs"].setdefault(t2_year, {}).setdefault(pid, P.new_year_rec())
                _save_ec_to_disk(s)
                st.rerun()


def _page_employees(room_key: str, log_tokens_fn=None):
    s = _S()
    _ensure_built_for_tax_year(s)
    _prune_manual_without_hire(s)
    pruned_n = int(s.pop("_pruned_manual_no_hire_count", 0) or 0)
    if pruned_n > 0:
        st.warning(f"ℹ️ 입사일 미입력 수기 사원 {pruned_n}명 제외")
        _save_ec_to_disk(s)
    tax_yr = int(s["tax_year"])
    shown_years = _years(s)

    # ── 상단 타이틀 + 슬림 옵션 바 (첫 번째 사원표가 화면 상단에서 즉시 시작되도록 최적화) ──
    c_ttl, c_opt_pop = st.columns([4.2, 1.8])
    with c_ttl:
        st.markdown(f"### 2. 사원정보 및 상시근로자 판정 ({tax_yr}년 귀속)")
    with c_opt_pop:
        if len(s.get("people") or {}) >= 35 and not s.get("use_year_tabs", False):
            st.caption("💡 인원수가 많을 때는 아래 **『연도별 탭 보기』**를 켜면 브라우저가 훨씬 빠릅니다.")

    with st.container(border=True):
        co1, co2, co3, co4 = st.columns([1.5, 1.5, 1.5, 1.5])
        with co1:
            assume_on = st.toggle(
                "⏩ 미도래 월 연말재직 가정(1 채움)",
                value=bool(s.get("assume_year_end", True)),
                key="ec_toggle_assume_ye",
                help="기중(예: 9월 가결산) 원천징수부 업로드 시 미도래 월(10~12월)을 연말까지 재직 가정(1 자동 채움 · 하늘색 표시)합니다.",
            )
            if assume_on != s.get("assume_year_end", True):
                s["assume_year_end"] = assume_on
                _save_ec_to_disk(s)
                st.rerun()
        with co2:
            hm_on = st.toggle(
                "📅 입사월 무급 시 익월지급 산입(1)",
                value=bool(s.get("include_unpaid_hire_month", True)),
                key="ec_toggle_hire_month_nopay",
                help="입사월 급여가 다음 달에 지급되어 당월 원천징수부 급여가 0원인 경우에도 재직(1)으로 산입하고 살구색으로 표시합니다.",
            )
            if hm_on != s.get("include_unpaid_hire_month", True):
                s["include_unpaid_hire_month"] = hm_on
                _save_ec_to_disk(s)
                st.rerun()
        with co3:
            show_4 = st.toggle(
                "📊 우측 4·5번 사후관리 열 표시",
                value=bool(s.get("show_all_4_blocks", True)),
                key="ec_toggle_4blocks",
                help="우측 4번(1차 사후관리)·5번(2차 사후관리) 블록을 함께 표시합니다.",
            )
            if show_4 != s.get("show_all_4_blocks", True):
                s["show_all_4_blocks"] = show_4
                _save_ec_to_disk(s)
                st.rerun()
        with co4:
            use_tabs = st.toggle(
                "🗂️ 연도별 탭으로 나누어 보기",
                value=bool(s.get("use_year_tabs", False)),
                key="ec_toggle_year_tabs",
                help="기본은 전 연도 연속 펼쳐보기이며, 인원이 많을 때 탭 보기로 전환하면 한 연도씩 쾌적하게 볼 수 있습니다.",
            )
            if use_tabs != s.get("use_year_tabs", False):
                s["use_year_tabs"] = use_tabs
                s["_tabs_user_touched"] = True
                _save_ec_to_disk(s)
                st.rerun()

        has_people = bool(s.get("people"))
        if has_people:
            filter_opts = ["ALL", "CHECK", "SAVING", "MOVED"]
            filter_labels = {
                "ALL": "👥 전체 사원 보기",
                "CHECK": "🚨 제외·확인 필요 사원만 (상시X·누락·무급월)",
                "SAVING": "💰 청년·병역 절세 후보만 (35~40세 병역미입력·청년우대)",
                "MOVED": "🔄 중도 입·퇴사 · 사업장 전출입자만",
            }
            cur_qf = str(s.get("emp_quick_filter") or "ALL")
            if cur_qf not in filter_opts:
                cur_qf = "ALL"
            chosen_qf = st.radio(
                "🔎 사원 빠른 필터 (필터 상태에서도 하단 합산합계는 전체 인원 기준으로 유지됩니다)",
                options=filter_opts,
                index=filter_opts.index(cur_qf),
                format_func=lambda k: filter_labels.get(k, k),
                horizontal=True,
                key="ec_emp_quick_filter_radio",
            )
            if chosen_qf != cur_qf:
                s["emp_quick_filter"] = chosen_qf
                _save_ec_to_disk(s)
                st.rerun()

    if has_people:
        st.markdown(
            "<div class='ec-legend'>"
            "<span style='background:#e2e8f0;color:#0f172a;border:1px solid #cbd5e1'>🔒 서류 확인값 (상시 O/X 전환 시 잠금해제)</span>"
            "<span style='background:#ffffff;color:#1d4ed8;border:1px solid #93c5fd'>✏️ 입력·선택 가능</span>"
            "<span style='background:#dbeafe;color:#1e40af;border:1px solid #93c5fd'>🏢 사업장 간 전출입·승계 합산(A→B)</span>"
            "<span style='background:#dcfce7;color:#14532d;border:1px solid #86efac'>🌱 청년등 인정 월</span>"
            "<span style='background:#e0f2fe;color:#0369a1;border:1px solid #7dd3fc'>🟦 미도래 월 연말재직 가정(자동 1)</span>"
            "<span style='background:#ffedd5;color:#c2410c;border:1px solid #fdba74'>🟧 급여 0원 월 (입사월 익월지급 산입 / 기중 무급 0 제외)</span>"
            "<span style='background:#ffffff;color:#0f172a;border:2px solid #f59e0b'>🔧 직접 수정한 값</span>"
            "<span style='background:#f3e8ff;color:#6b21a8;border:1px solid #d8b4fe'>✍️ [수기 추가] 수기 입력 사원</span>"
            "</div>",
            unsafe_allow_html=True,
        )

    computed_all, totals_all, ctx_all = {}, {}, {}
    if s.get("use_year_tabs", False) and len(shown_years) > 1:
        from .ui_step3 import _build_compact_bridge_info, _render_compact_bridge
        tab_objs = st.tabs([f"📅 {y}년 귀속 명세" for y in shown_years])
        for tab_o, y in zip(tab_objs, shown_years):
            with tab_o:
                computed_all[y], totals_all[y] = _render_year(s, y, room_key)
                ctx_all[y] = _ctx(s, y)
                if has_people and (y - 1) in shown_years:
                    _br_tab = _build_compact_bridge_info(
                        s,
                        y - 1,
                        y,
                        use_new_rule_prev=(y >= H.NEW_TENURE_RULE_FROM and (y - 1) >= H.NEW_TENURE_RULE_FROM - 1),
                    )
                    _render_compact_bridge(_br_tab, between_tables=False)
    else:
        from .ui_step3 import _build_compact_bridge_info, _render_compact_bridge
        for idx_y, y in enumerate(shown_years):
            if has_people and idx_y > 0:
                y_upper = shown_years[idx_y - 1]
                if y_upper - y == 1:
                    _br_between = _build_compact_bridge_info(
                        s,
                        y,
                        y_upper,
                        use_new_rule_prev=(y_upper >= H.NEW_TENURE_RULE_FROM and y >= H.NEW_TENURE_RULE_FROM - 1),
                    )
                    _render_compact_bridge(_br_between, between_tables=True)
            computed_all[y], totals_all[y] = _render_year(s, y, room_key)
            ctx_all[y] = _ctx(s, y)

    _render_prev_filing_summary_card(s, shown_years)

    if has_people and tax_yr in totals_all and (tax_yr - 1) in totals_all:
        snap_all = _ensure_totals_snapshot(s)
        cur_t = snap_all.get(tax_yr) or totals_all[tax_yr]
        _, suc_reg, ded_reg = _adjusted_prev_totals(s, totals_all[tax_yr - 1])
        prv_snap = snap_all.get(tax_yr - 1) or totals_all[tax_yr - 1]
        use_nr = (tax_yr >= H.NEW_TENURE_RULE_FROM) and (prv_snap.get("nr_상시_평균") is not None)
        eff_prv_reg = round(float(prv_snap["nr_상시_평균"] if use_nr else (prv_snap.get("상시_평균", prv_snap.get("b1_reg", 0.0)) or 0.0)), 2)
        eff_prv_yth = round(float(prv_snap.get("nr_청년등_평균", 0.0) if use_nr else (prv_snap.get("청년등_평균", prv_snap.get("b1_yth", 0.0)) or 0.0)), 2)
        eff_prv_gen = round(max(0.0, eff_prv_reg - eff_prv_yth), 2)
        inc = H.calc_increase_with_cap(
            cur_t["상시_평균"],
            cur_t["청년등_평균"],
            cur_t["청년외_평균"],
            eff_prv_reg,
            eff_prv_yth,
            eff_prv_gen,
        )
        cap_note = ""
        if inc.get("청년등_한도적용전", 0) > inc["청년등_증가"] or inc.get("청년등외_한도적용전", 0) > inc["청년등외_증가"]:
            cap_note = " &nbsp;·&nbsp; ⚠️ <b>전체 상시근로자 증가인원 한도(Cap) 자동 적용됨</b>"
        suc_note = (f" (포괄양수·승계 직전인원 +{suc_reg:.2f}명 반영)" if suc_reg > 0 else "") + \
                   (f" (기중양도 승계 근로자 직전인원 −{ded_reg:.2f}명 차감)" if ded_reg > 0 else "")
        st.markdown(
            f"<div class='ec-law-banner'>"
            f"📊 <b>[{tax_yr}년 vs {tax_yr-1}년 신규공제 고용증가 요약{suc_note}]</b> &nbsp; "
            f"전체 상시 증가: <b>+{inc['전체_증가']:.2f}명</b> &nbsp;|&nbsp; "
            f"청년등 인정 증가: <b>+{inc['청년등_증가']:.2f}명</b> &nbsp;|&nbsp; "
            f"청년등 외 인정 증가: <b>+{inc['청년등외_증가']:.2f}명</b>{cap_note} &nbsp;&nbsp; "
            f"<span style='color:#1d4ed8'>({(tax_yr-1)%100:02d}년 1차 사후관리 청년등: <b>{cur_t['b2_yth']:.2f}명</b>"
            + (f" / {(tax_yr-2)%100:02d}년 2차 사후관리 청년등: <b>{cur_t['b3_yth']:.2f}명</b>" if _has_year_data(s, tax_yr - 2) else "")
            + ")</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

    c_add, _ = st.columns([1.3, 5.8])
    if c_add.button("➕ 사원 추가", use_container_width=True):
        _dlg_add_employee()

    # ── 하단 네비게이션 바: [< 이전] ... [📕 전체 PDF 다운] [🔍 오류 검토] [다음(3단계)] ──
    corp_nm = (s.get("biz", {}).get("상호") or "상호미입력").strip()
    st.markdown("<div class='ec-nav-divider'></div>", unsafe_allow_html=True)
    c_prev, _, c_all_pdf, c_rev, c_next = st.columns([1.2, 2.3, 1.25, 1.15, 1.3])
    if c_prev.button("< 이전", use_container_width=True):
        s["step"] = 1
        _trigger_scroll_to_top(s)
        _save_ec_to_disk(s)
        st.rerun()

    with c_all_pdf:
        with st.container(key="ec_btn_pdf_all_wrap"):
            st.download_button(
                "📕 전체 PDF 다운",
                data=_build_schedule_pdf_bytes(s, shown_years, include_summary=True),
                file_name=f"{corp_nm}_{tax_yr}년귀속_전체연도_상시근로자명세.pdf",
                mime="application/pdf",
                use_container_width=True,
                key="dl_pdf_all_years",
                help=f"화면에 표시된 전체 연도({', '.join(str(y)+'년' for y in shown_years)})의 상시근로자 명세 및 고용증가 요약을 한 파일의 PDF로 다운로드합니다.",
            )

    if c_rev.button("🔍 오류 검토", use_container_width=True):
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
            "결정론적_검토항목": [{"구분": lv, "내용": msg} for lv, msg in review_items],
        }
        _dlg_review(review_items, audit_payload=audit_payload, log_tokens_fn=log_tokens_fn, room_key=room_key)

    if c_next.button("다음(3단계)", type="primary", use_container_width=True):
        s["totals_snapshot"] = totals_all
        s["step"] = 3
        s["max_step_reached"] = max(int(s.get("max_step_reached") or 1), 3)
        _trigger_scroll_to_top(s)
        _save_ec_to_disk(s)
        st.rerun()