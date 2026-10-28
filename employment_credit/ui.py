# -*- coding: utf-8 -*-
"""
통합고용세액공제 화면 — 1단계(자료 업로드) · 2단계(사원정보) · 3단계(공제액·사후관리 계산) · 4단계(보고서)

[클로드 14대 수정사항 + 추가 2건 + 제미나이 UI/UX 시각 최적화 · PDF 다운로드 · 디스크 자동보관 · Pro/Argon 심층진단 통합 최종본]
1. [자율 에이전트AI ↔ 통합고용세액공제 양방향 100% 자동 보관 (메모리 + 디스크 `.workspace_storage` 이중 영구저장)]
   - 통합고용세액공제 진행 도중 자율 에이전트AI로 넘어가서 세법 질의를 하고 다시 돌아오거나, 브라우저 새로고침(F5)을 해도
     작업공간별(`ws_id`)로 업로드 파일·사원표 수정내역·진행 단계가 100% 그대로 보존됩니다.
2. [2단계 시각적 완성도 5대 개선 반영]
   - ① `사업장명` 열 노이즈(`첨부 엑셀 명: 년` 등) 완전 제거 및 단일 사업장 시 `'본점'` 깔끔 표기 (`76px` 슬림화)
   - ② AG Grid 전체 열 폭 다이어트(말줄임표 `"..."` 0건 유지 + 가로 스크롤 최소화) 및 대량 인원(35명 이상) 탭 뷰 자동 보호
   - ③ `미도래 월 연말재직 가정(하늘색 #e0f2fe)` vs `급여 0원 월(살구색 #ffedd5)` 색상 명확 분리
   - ④ `청년등 구분`(청년·고령자 등 우대=초록 볼드 / 일반=슬레이트) 및 `제외사유`(제외대상=적색 볼드 / 해당없음=슬레이트) 시각 대비 강화
   - ⑤ 2단계 상단 옵션 박스 슬림화로 첫 번째 사원표가 화면 상단에서 즉시 시작되도록 개선
3. [연도별 우측 상단 `[📕 PDF 다운]` 및 하단 `[📕 전체 PDF 다운]` 붉은 버튼 탑재]
   - 각 연도 귀속 상시근로자 명세 라인 맨 오른쪽 옆에 붉은색 `[📕 PDF 다운]` 버튼을 배치하여 연도별 A4 가로(Landscape) 명세표를 즉시 다운로드합니다.
   - 하단 `[🔍 오류 검토]` 바로 왼쪽 옆에 동일한 디자인의 붉은색 `[📕 전체 PDF 다운]` 버튼을 배치하여 전 연도 통합 명세서 PDF를 원클릭으로 다운로드합니다.
4. [100% 성능 12대 결정론적 오류·절세누락 검토 + 부분적 Pro/Argon AI 심층 세무진단 연동]
"""

# ※ 화면 코드는 단계별 파일로 나뉘어 있습니다: ui_common(공통), ui_sidebar, ui_step1~ui_step4.
#   이 파일은 진입점(render_credit_wizard)과, 기존 코드 호환을 위한 이름 다시 내보내기만 담습니다.
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
    CLASS_COLS,
    CSS,
    INFO_COLS,
    JS_DATE_FMT,
    JS_DEC2_FMT,
    JS_LOCKED,
    JS_MONTH_EDITABLE,
    JS_MONTH_STYLE,
    JS_NUM_FMT,
    JS_STYLE,
    JS_STYLE_CENTER,
    JS_STYLE_EXCL,
    JS_STYLE_REGULAR,
    JS_STYLE_WORKPLACE,
    JS_STYLE_YOUTH,
    JS_YOUTH_PARAMS,
    MONTH_COLS,
    STEPS,
    STORAGE_DIR,
    _ANON_MAX_AGE_SEC,
    _ANON_WS_PREFIX,
    _APP_PDF_CHAR_CAP,
    _CALC_CACHE_KEY,
    _PERSIST_KEYS,
    _REPORT_EMOJI_RE,
    _RRN_FULL_RE,
    _S,
    _SAVED_HASH_KEY,
    _SAVE_PENDING_KEY,
    _adjusted_prev_totals,
    _all_possible_years,
    _block_titles_for_year,
    _build_csv_bytes,
    _build_review_pdf_bytes,
    _build_year_rows,
    _build_year_rows_uncached,
    _calc_cache,
    _calc_fingerprint,
    _carry_over_user_edits,
    _clean_md_for_pdf,
    _cleanup_stale_anon_ec_files,
    _cohort_corp_size,
    _cohort_youth_map,
    _cohort_youth_map_uncached,
    _compose_doc_texts_with_wp,
    _compute_historical_matrix_columns,
    _ctx,
    _current_build_sig,
    _default_state_dict,
    _default_workplace_label,
    _ec_disk_path,
    _ensure_built_for_tax_year,
    _ensure_korean_pdf_font,
    _ensure_totals_snapshot,
    _flush_ec_save,
    _has_year_data,
    _is_emp_id_token_safe,
    _load_ec_from_disk,
    _merge_ext_dicts,
    _pdf_text,
    _pro_comment_pdf_bytes,
    _progress,
    _render_scroll_to_top_if_needed,
    _review_pdf_bytes,
    _sanitize_workplace_label,
    _save_ec_to_disk,
    _succeeded_prev_headcount_sum,
    _succession_map,
    _top_status_bar,
    _transfer_out_map,
    _trigger_scroll_to_top,
    _uploaded_wht_years,
    _workplace_close_month_map,
    _write_ec_to_disk,
    _years,
    reset_credit_all_state,
)
from .ui_sidebar import (  # noqa: F401
    _dlg_industry,
    _dlg_nts_dart_check,
    _int,
    _render_backup_card,
    _restore_from_backup,
    render_credit_sidebar,
)
from .ui_step1 import (  # noqa: F401
    _dlg_missing,
    _enter_step2,
    _page_upload,
    _read_upload_text,
)
from .ui_step2 import (  # noqa: F401
    _apply_changes,
    _build_schedule_pdf_bytes,
    _dlg_review,
    _grid_options,
    _norm,
    _page_employees,
    _render_prev_filing_summary_card,
    _render_year,
    _same_num,
    _year_role_description,
)
from .ui_step3 import (  # noqa: F401
    _dlg_filed_vs_recalc_comparison,
    _build_compact_bridge_info,
    _render_compact_bridge,
    _build_pm_formula_lines,
    _build_step3_calculation_pdf_bytes,
    _build_top_kpi_cards_html,
    _cohort_capital,
    _enrich_matrix_cols_with_cohort_consistency,
    _fmt_matrix_won,
    _fmt_signed_total_won,
    _page_calculation,
    _render_pm_basis_selector_right,
    _verify_step3_math_integrity,
)
from .ui_step4 import (  # noqa: F401
    _build_client_kakao_and_email_drafts,
    _build_report_docx_bytes,
    _build_report_markdown,
    _build_report_pdf_bytes,
    _build_report_xlsx_bytes,
    _compute_report_cache_sig,
    _ensure_auto_pro_audit_comment,
    _page_report,
    _parse_and_clean_pro_audit,
    _sanitize_markdown_tilde,
    _strip_all_emojis,
)




# ══════════════════════════════════════════════════════════════════
# 8. 진입점
# ══════════════════════════════════════════════════════════════════
def render_credit_wizard(extract_file_fn, log_tokens_fn=None, active_room_key: str = "", **_):
    s = _S()
    try:
        st.markdown(CSS, unsafe_allow_html=True)
        _top_status_bar(s)
        _progress(s["step"])
        _render_scroll_to_top_if_needed(s)

        if s["step"] == 1:
            _page_upload(extract_file_fn, log_tokens_fn, active_room_key)
        elif s["step"] == 2:
            _page_employees(active_room_key, log_tokens_fn=log_tokens_fn)
        elif s["step"] == 3:
            _page_calculation()
        else:
            _page_report(active_room_key, log_tokens_fn=log_tokens_fn)
    finally:
        # 화면 이동(st.rerun)으로 중간에 끝나도 이 시점에 한 번 저장 (내용이 바뀌었을 때만 실제로 씀)
        _flush_ec_save(force=True)