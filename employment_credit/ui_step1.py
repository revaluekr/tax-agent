# -*- coding: utf-8 -*-
"""통합고용세액공제 계산기 화면 — 1단계 자료 업로드: 파일 읽기·서류 분류·자동 추출

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
    _APP_PDF_CHAR_CAP,
    _S,
    _compose_doc_texts_with_wp,
    _current_build_sig,
    _default_workplace_label,
    _ensure_built_for_tax_year,
    _merge_ext_dicts,
    _sanitize_workplace_label,
    _save_ec_to_disk,
    _trigger_scroll_to_top,
)



def _read_upload_text(u, extract_file_fn, room_key: str = "") -> str:
    """
    업로드 파일 → 글자.
    PDF는 계산기가 직접 '모든 쪽'을 읽습니다. app.py 공용 함수는 150쪽·150,000자에서 잘라
    직원 25명을 넘는 원천징수부(1인 3쪽)의 뒷부분이 조용히 빠지기 때문입니다.
    스캔 이미지 PDF처럼 글자가 거의 없으면 공용 함수(이미지 판독)로 넘깁니다.
    """
    name = str(getattr(u, "name", "") or "")
    if name.lower().endswith(".pdf"):
        # 1순위 pypdfium2: 글자 단위로 저장된 원천징수부도 빠르게 읽음 (300쪽 약 4초, pypdf는 약 60초)
        try:
            import pypdfium2 as pdfium
            doc = pdfium.PdfDocument(u.getvalue())
            parts = [f"[첨부 PDF 파일명: {name} (총 {len(doc)}페이지)]"]
            body = 0
            for i in range(len(doc)):
                tp = doc[i].get_textpage()
                t = (tp.get_text_range() or "").strip()
                tp.close()
                body += len(t)
                parts.append(f"\n--- {i + 1}페이지 ---\n{t}")
            doc.close()
            if body >= 40:
                return "\n".join(parts)
        except Exception:
            pass
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(u.getvalue()))
            parts = [f"[첨부 PDF 파일명: {name} (총 {len(reader.pages)}페이지)]"]
            body = 0
            for i, page in enumerate(reader.pages):
                t = (page.extract_text() or "").strip()
                body += len(t)
                parts.append(f"\n--- {i + 1}페이지 ---\n{t}")
            if body >= 40:
                return "\n".join(parts)
        except Exception:
            pass
    text = extract_file_fn(u, room_key) or ""
    if len(text) >= _APP_PDF_CHAR_CAP:
        text += "\n[[계산기 경고: 파일 글자가 공용 읽기 상한에 닿아 뒷부분이 잘렸을 수 있습니다]]"
    return text


# ══════════════════════════════════════════════════════════════════
# 2. 별도 창(대화상자 — 12대 정밀 오류검토 + Pro/Argon 심층 세무진단 연동)
# ══════════════════════════════════════════════════════════════════
@st.dialog("📋 자료 확인 안내")
def _dlg_missing(msgs: list[str]):
    for m in msgs:
        st.markdown(f"- {m}")
    st.caption("확인을 누르면 현재까지 인식된 자료로 다음 단계로 넘어갑니다. 부족한 정보는 사원정보 화면과 사이드바에서 직접 입력·수정할 수 있습니다.")
    if st.button("✅ 확인 및 2단계(사원정보)로 이동", type="primary", use_container_width=True):
        s = _S()
        s["go_step2"] = True
        _save_ec_to_disk(s)
        st.rerun()


# ══════════════════════════════════════════════════════════════════
# 4. 1단계: 자료 업로드
# ══════════════════════════════════════════════════════════════════
def _page_upload(extract_file_fn, log_tokens_fn, room_key):
    s = _S()
    tax_yr = int(s["tax_year"])
    if s.pop("go_step2", False):
        _enter_step2()
        st.rerun()

    st.markdown(f"### 📂 1. 자료 업로드 ({tax_yr}년 귀속 기준)")

    if tax_yr == 2026:
        st.markdown(
            "<div class='ec-law-banner'>"
            "💡 <b>[2026년 귀속 통합 계산 안내]</b> 2026년 귀속 신고 시에는 "
            "<b>① 26년 세액공제(합산 후 절사)</b>, <b>② 25년 1차 사후관리(2차년도 연속공제·추징)</b>, "
            "<b>③ 24년 2차 사후관리(3차년도 연속공제·추징)</b>를 함께 검토합니다. "
            "24·25·26년 공제 및 사후관리(24년 고용증가 23→24년 산정 포함)를 위해 <b>23년 자료(원천징수부·기신고서)</b>도 함께 올리실 수 있으며, "
            "본점·지점 또는 기중 양도(1번)·포괄양수(2번) 복수 사업장 원천징수부를 함께 올리면 자동 합산됩니다."
            "</div>",
            unsafe_allow_html=True,
        )
    elif tax_yr in (2024, 2025):
        trunc_lbl = "합산 후 절사"
        st.markdown(
            f"<div class='ec-law-banner'>"
            f"💡 <b>[{tax_yr}년 귀속 세액공제({trunc_lbl}) 및 사후관리 안내]</b> 2단계 진입 시 <b>『{tax_yr}년 귀속 상시근로자 명세』</b>가 맨 위에 표시되며, "
            f"<b>{tax_yr}년 세액공제({trunc_lbl})</b>와 자료가 있는 <b>{tax_yr-1}년 1차 사후관리</b>·<b>{tax_yr-2}년 2차 사후관리</b>를 자동 구성합니다."
            f"</div>",
            unsafe_allow_html=True,
        )
    else:
        comp_map = H.valid_comparison_years_for_new_credit(tax_yr)
        active_comp = [f"{k}({v}년)" for k, v in comp_map.items() if v is not None]
        st.markdown(
            f"<div class='ec-law-banner'>"
            f"💡 <b>[{tax_yr}년 귀속 점증형 공제 안내]</b> 비교 대상 과세연도: <b>{', '.join(active_comp)}</b> "
            f"(2024.12.31. 이전 개시 과세연도 제외 규정 반영 · A+B+C 자동 합산)."
            f"</div>",
            unsafe_allow_html=True,
        )

    doc_types = R.get_doc_types(tax_yr)
    doc_help = R.get_doc_help(tax_yr)
    all_labels = R.get_all_selectable_doc_labels(tax_yr)
    base_keys = {k for k, *_ in doc_types}

    docs_table_slot = st.empty()
    uploaded_list_slot = st.container()

    st.markdown(
        "<div class='ec-bottom-upload-label'>"
        "<span>📥 <b>파일 추가 업로드</b> (본·지점 / 양도·양수 복수 사업장 파일도 한꺼번에 끌어다 놓으세요)</span>"
        f"<span style='color:#16a34a;font-size:0.80rem;'>{tax_yr-3}·{tax_yr-2}·{tax_yr-1}·{tax_yr}년 원천징수부(100% 자체 고속파싱) · 복수 사업장 합산 지원</span>"
        "</div>",
        unsafe_allow_html=True,
    )
    with st.container(key="ec_drop"):
        ups = st.file_uploader(
            "여기에 파일(PDF·엑셀·CSV·이미지)을 끌어다 놓으세요",
            accept_multiple_files=True,
            type=["pdf", "xlsx", "xls", "csv", "png", "jpg", "jpeg"],
            key=f"ec_up_{s['uploader_ver']}",
            label_visibility="collapsed",
        )

    new = [u for u in (ups or []) if u.name not in s["files"]]
    if new:
        with st.spinner(f"📄 {len(new)}개 파일에서 텍스트 및 표 데이터를 추출하고 있습니다..."):
            for u in new:
                text = _read_upload_text(u, extract_file_fn, room_key)
                auto_wp = _sanitize_workplace_label(getattr(P, "infer_workplace_name", lambda nm, tx="": "")(u.name, text), _default_workplace_label(s))
                s["files"][u.name] = {
                    "key": P.classify_file(u.name, text),
                    "text": text,
                    "wp": auto_wp,
                }
        s["uploader_ver"] += 1
        s["built_sig"] = None
        _save_ec_to_disk(s)
        st.rerun()

    with uploaded_list_slot:
        if s["files"]:
            with st.container(border=True):
                c_h1, c_h2 = st.columns([4, 1])
                with c_h1:
                    st.markdown(
                        f"**📎 업로드된 파일 목록 ({len(s['files'])}건)** — *본·지점 또는 1·2번 사업장 합산 시 가운데 칸에서 『사업장명』을 구분해 주시면 2단계 표 맨 앞에 자동 기록됩니다.*"
                    )
                with c_h2:
                    if st.button("🗑️ 전체 파일 비우기", use_container_width=True, key="ec_clear_all_files"):
                        s["files"] = {}
                        s["ext"] = None
                        s["ext_sig"] = None
                        s["built_sig"] = None
                        s["uploader_ver"] += 1
                        _save_ec_to_disk(s)
                        st.rerun()

                opts = [None] + list(all_labels.keys())
                for name, f in list(s["files"].items()):
                    c1, c_wp, c2, c3 = st.columns([3.4, 1.8, 3.8, 0.9])
                    c1.markdown(f"📄 **{name}**" + (" · <span style='color:#64748b;font-size:.8rem'>💾 백업 복원(원문 없음)</span>"
                                                     if f.get("restored") and not f.get("text") else ""),
                                unsafe_allow_html=True)
                    cur_wp = _sanitize_workplace_label(str(f.get("wp") or ""), _default_workplace_label(s))
                    new_wp = c_wp.text_input(
                        "사업장명",
                        value=cur_wp,
                        placeholder="예: 본점 / 지점 / 1사업장",
                        key=f"ec_wp_{name}",
                        label_visibility="collapsed",
                        help="이 파일에 속한 근로자들의 소속 사업장명(예: 본점, 강남지점, 1번사업장, 2번사업장)",
                    )
                    if new_wp.strip() != cur_wp:
                        f["wp"] = new_wp.strip()
                        s["built_sig"] = None
                        _save_ec_to_disk(s)

                    cur_k = f.get("key") if f.get("key") in opts else None
                    new_k = c2.selectbox(
                        "종류",
                        opts,
                        index=opts.index(cur_k),
                        key=f"ec_k_{name}",
                        format_func=lambda k: "⚠️ 서류 종류를 선택하세요 (미선택 시 분석 제외)"
                        if k is None
                        else all_labels.get(k, str(k)),
                        label_visibility="collapsed",
                    )
                    if new_k != f.get("key"):
                        f["key"] = new_k
                        s["built_sig"] = None
                        _save_ec_to_disk(s)

                    if c3.button("삭제", key=f"ec_del_{name}", use_container_width=True):
                        s["files"].pop(name, None)
                        s["built_sig"] = None
                        _save_ec_to_disk(s)
                        st.rerun()

    have: dict[str, list[str]] = {}
    for name, f in s["files"].items():
        if f.get("key"):
            wp_tag = _sanitize_workplace_label(str(f.get("wp") or ""), R.DEFAULT_WORKPLACE_NAME)
            disp_nm = f"{name} [{wp_tag}]" if wp_tag and wp_tag != R.DEFAULT_WORKPLACE_NAME else name
            have.setdefault(f["key"], []).append(disp_nm)

    trs = []
    for key, label, required, _ in doc_types:
        on = bool(have.get(key))
        pill = "<span class='ec-req-pill'>필수</span>" if required else "<span class='ec-opt-pill'>선택</span>"
        files_str = ", ".join(have.get(key, [])) or "-"
        trs.append(
            f"<tr class='{'on' if on else ''}'>"
            f"<td class='led-cell'><span class='ec-led{' on' if on else ''}'></span></td>"
            f"<td><b>{label}</b> {pill}</td>"
            f"<td class='help'>{doc_help.get(key, '')}</td>"
            f"<td class='fname'>{files_str}</td></tr>"
        )

    for extra_key, extra_files in have.items():
        if extra_key not in base_keys and extra_files:
            extra_lbl = all_labels.get(extra_key, extra_key)
            extra_help = doc_help.get(extra_key, "과거 연도 사원정보 표 생성 및 연속공제·사후관리 검증에 자동 반영됩니다.")
            trs.append(
                f"<tr class='extra'>"
                f"<td class='led-cell'><span class='ec-led on'></span></td>"
                f"<td><b>{extra_lbl}</b> <span class='ec-extra-pill'>➕ 추가 인식됨</span></td>"
                f"<td class='help'>{extra_help}</td>"
                f"<td class='fname'>{', '.join(extra_files)}</td></tr>"
            )

    docs_table_slot.markdown(
        "<table class='ec-docs'><thead><tr>"
        "<th class='led-cell'>상태</th><th>자료명</th><th>검토 용도 및 법령 기준</th><th>업로드된 파일</th>"
        "</tr></thead><tbody>" + "".join(trs) + "</tbody></table>",
        unsafe_allow_html=True,
    )

    st.markdown("<div class='ec-nav-divider'></div>", unsafe_allow_html=True)
    _, right = st.columns([5.8, 1.3])
    if right.button("다음(2단계)", type="primary", use_container_width=True):
        classified: dict[str, list[str]] = {}
        for name, f in s["files"].items():
            if f.get("key"):
                classified.setdefault(f["key"], []).append(name)
        sig = json.dumps(
            sorted((n, f.get("key"), f.get("wp", "")) for n, f in s["files"].items()),
            ensure_ascii=False,
        )
        restored_left = [n for n, f in s["files"].items() if f.get("restored") and not f.get("text")]
        classified_with_text: dict[str, list[str]] = {}
        for name, f in s["files"].items():
            if f.get("key") and f.get("text"):
                classified_with_text.setdefault(f["key"], []).append(name)

        if s["ext_sig"] != sig and restored_left and s.get("ext"):
            if classified_with_text:
                texts_new = _compose_doc_texts_with_wp(s, classified_with_text)
                with st.spinner("⚡ 새로 추가·변경된 서류를 추출하여 기존 복원 데이터에 병합하고 있습니다..."):
                    new_ext = P.extract_all(texts_new, log_tokens_fn, room_key)
                    s["ext"] = _merge_ext_dicts(s.get("ext"), new_ext)
                    msgs = P.check_missing(classified, s["ext"], tax_yr)
                s["ext_sig"] = sig
                s["built_sig"] = None
                s["pending_msgs"] = msgs
                _save_ec_to_disk(s)
            else:
                st.warning(
                    "백업에서 복원한 파일(" + ", ".join(restored_left[:3]) + (" 외" if len(restored_left) > 3 else "") + ")은 "
                    "원문이 없어 다시 읽을 수 없습니다. 지금 읽어둔 사원정보를 그대로 쓰고 다음 단계로 넘어갑니다. "
                    "서류를 새로 읽게 하려면 원본 서류를 추가로 끌어다 놓거나 복원 표시된 파일을 삭제 후 다시 올려주세요."
                )
                s["ext_sig"] = sig
                s["built_sig"] = _current_build_sig(s)
        if s["ext_sig"] != sig:
            texts = _compose_doc_texts_with_wp(s, classified_with_text or classified)
            if texts:
                with st.spinner("⚡ 자체 고속 파서(1순위) 및 하이브리드 Pro/Argon AI(2순위)로 사업자·복수사업장·사원 정보를 추출하고 있습니다..."):
                    s["ext"] = P.extract_all(texts, log_tokens_fn, room_key)
                    msgs = P.check_missing(classified, s["ext"], tax_yr)
            else:
                s["ext"] = {}
                msgs = P.check_missing(classified, None, tax_yr)
                msgs.append("올린 자료가 없어 사업자정보와 사원정보를 모두 직접 입력해야 합니다.")
            s["ext_sig"] = sig
            s["pending_msgs"] = msgs
            _save_ec_to_disk(s)
        msgs = s.get("pending_msgs") or []
        if msgs:
            _dlg_missing(msgs)
        else:
            _enter_step2()
            st.rerun()


def _enter_step2():
    s = _S()
    _ensure_built_for_tax_year(s)
    for k in list(st.session_state.keys()):
        if str(k).startswith("ec_biz_"):
            del st.session_state[k]
    s["step"] = 2
    s["max_step_reached"] = max(int(s.get("max_step_reached") or 1), 2)
    _trigger_scroll_to_top(s)
    _save_ec_to_disk(s)