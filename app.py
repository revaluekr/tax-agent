import os
import io
import re
import time
import json
import hashlib
import inspect
import threading
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, date
from zoneinfo import ZoneInfo
import streamlit as st
import pandas as pd
from pypdf import PdfReader
from docx import Document
from docx.shared import Pt
from docx.oxml.ns import qn
from google import genai
from google.genai import types

# PDF 직접 생성을 위한 ReportLab 모듈
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# 1. 웹 페이지 기본 설정
st.set_page_config(
    page_title="세무·법령·회계 자율 에이전트",
    page_icon="⚖️",
    layout="wide"
)

# 백그라운드 스레드 및 하위 모듈(law_api, agent) 임포트 전에 st.secrets의 모든 API 키를 환경변수로 최우선 동기화
try:
    if hasattr(st, "secrets"):
        for k, v in st.secrets.items():
            if isinstance(v, (str, int, float)) and k not in os.environ:
                os.environ[k] = str(v).strip()
except Exception:
    pass

# 🔒 ImportError 원천 방지 및 환경변수 동기화 후 안전 임포트
import agent
import law_api
from agent import run_agent

# ---------------------------------------------------------
# 공통 정제 도우미 & [미세 디테일 1 & 2 + 물결표(~) 취소선 오작동 방지] 화면 렌더링 전용 마크다운 보정기
# ---------------------------------------------------------
def _format_markdown_for_screen(md_text: str) -> str:
    """
    0) [물결표 취소선 방지]: 한 문장에 숫자 범위 물결표(~)가 2개 이상 들어갈 때(예: '중견기업 8~9%, 대기업 10~17%')
       마크다운 파서가 두 물결표 사이를 취소선(<del>)으로 오인해 가운데 줄을 긋고 물결표를 삼키는 현상을 원천 차단합니다.
    1) [미세 디테일 1]: 한국어 마크다운 파서에서 닫는 괄호/따옴표/퍼센트 등이 포함된 **굵은글씨** 바로 뒤에
       한글 조사(이, 가, 은, 는, 을, 를, 에 등)가 붙어 별표(**) 기호가 화면에 그대로 노출되는 현상을
       <strong>...</strong> 태그로 자동 변환하여 100% 깔끔한 굵은 글씨로 표시합니다.
    2) [미세 디테일 2]: '### 3. 관련법령' 섹션의 리스트를 전용 컴팩트 컨테이너(<div class='related-laws-compact-box'>)로
       감싸서 관련법령 항목들의 줄간격만 조밀하고 정갈하게 렌더링합니다.
    """
    if not md_text:
        return ""

    # 0. 물결표(~)가 마크다운 취소선(~...~ 또는 ~~...~~)으로 오작동하지 않도록 HTML 엔티티(&#126;)로 안전 변환
    s = md_text.replace("~", "&#126;")

    # 1. **텍스트** 패턴을 <strong>텍스트</strong>으로 안전하게 변환 (줄바꿈 없는 인라인 볼드 대상)
    s = re.sub(r"\*\*([^\*\n]+?)\*\*", r"<strong>\1</strong>", s)

    # 2. '### 3. 관련법령' 섹션 리스트를 .related-laws-compact-box로 감싸기
    pattern_rel = re.compile(r"(###\s*3\.\s*관련\s*법령[^\n]*\n)(.*)", flags=re.DOTALL)
    m = pattern_rel.search(s)
    if m:
        heading_part = m.group(1)
        rest_body = m.group(2)
        if "\n---\n" in rest_body:
            laws_part, tail_part = rest_body.split("\n---\n", 1)
            s = (
                s[:m.start()]
                + heading_part
                + f"<div class='related-laws-compact-box'>\n\n{laws_part.strip()}\n\n</div>\n\n---\n"
                + tail_part
            )
        else:
            s = (
                s[:m.start()]
                + heading_part
                + f"<div class='related-laws-compact-box'>\n\n{rest_body.strip()}\n\n</div>"
            )
    return s

def _sanitize_math_text(text: str) -> str:
    if not text:
        return ""
    s = text
    s = re.sub(r"\[(\[(?:판례|심판례|해석례|예규|조문)\s*:\s*[^\]]+\])\]\((https?://[^\s)]+)\)", r"\1", s)
    s = re.sub(r"\[([^\n]+?)\]\((https?://(?:www\.)?law\.go\.kr/[^\s)]+)\)", r"\1", s)

    s = re.sub(r"\$\$(.*?)\$\$", r"\1", s, flags=re.DOTALL)
    s = re.sub(r"\$([^$\n]+)\$", r"\1", s)
    s = re.sub(r"\\text(?:bf|rm|it)?\{([^}]*)\}", r"\1", s)
    s = re.sub(r"\\frac\{([^}]*)\}\{([^}]*)\}", r"(\1/\2)", s)
    s = s.replace(r"\times", " × ").replace(r"\div", " ÷ ").replace(r"\cdot", "·")
    s = s.replace(r"\%", "%").replace(r"\_", "_").replace(r"\,", ",")
    s = re.sub(r"\\(left|right|quad|qquad|mathrm|mathbf)\b", "", s)
    s = s.replace("−", " - ").replace("–", " - ").replace("—", " - ").replace("∼", "~")
    s = s.replace("→", " -> ").replace("↔", " <-> ").replace("≧", ">=").replace("≦", "<=")
    return s

def _extract_clean_copy_text(report_text: str) -> str:
    cleaned = _sanitize_math_text(report_text)
    out_lines = []
    for line in cleaned.split("\n"):
        if line.strip().startswith(">"):
            continue
        out_lines.append(line)
    return "\n".join(out_lines).strip()

def create_excel_from_markdown_tables(report_text: str) -> bytes | None:
    cleaned = _sanitize_math_text(report_text)
    lines = cleaned.split("\n")
    tables = []
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if s.startswith("|") and s.endswith("|"):
            t_rows = []
            while i < len(lines):
                rs = lines[i].strip()
                if not (rs.startswith("|") and rs.endswith("|")):
                    break
                if not re.match(r"^\|[\s\-:|]+\|$", rs):
                    cells = [re.sub(r"\*\*(.*?)\*\*", r"\1", c.strip()) for c in rs.strip("|").split("|")]
                    t_rows.append(cells)
                i += 1
            if len(t_rows) >= 2:
                tables.append(t_rows)
            continue
        i += 1

    if not tables:
        return None

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for idx, t_rows in enumerate(tables):
            max_cols = max(len(r) for r in t_rows)
            padded = [r + [""] * (max_cols - len(r)) for r in t_rows]
            header = padded[0]
            seen_cols = {}
            safe_header = []
            for col_name in header:
                c_label = col_name or "항목"
                if c_label in seen_cols:
                    seen_cols[c_label] += 1
                    safe_header.append(f"{c_label}_{seen_cols[c_label]}")
                else:
                    seen_cols[c_label] = 1
                    safe_header.append(c_label)
            df = pd.DataFrame(padded[1:], columns=safe_header)
            df.to_excel(writer, sheet_name=f"표_{idx+1}", index=False)
    buffer.seek(0)
    return buffer.getvalue()

# ---------------------------------------------------------
# 헬퍼 함수 2: AI 답변을 워드(.docx)로 변환
# ---------------------------------------------------------
def _set_malgun_font(run):
    run.font.name = "Malgun Gothic"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "Malgun Gothic")

def create_word_docx(report_text: str) -> bytes:
    report_text = _sanitize_math_text(report_text)
    doc = Document()
    
    style = doc.styles["Normal"]
    style.font.name = "Malgun Gothic"
    style.font.size = Pt(10.5)
    style._element.rPr.rFonts.set(qn("w:eastAsia"), "Malgun Gothic")
    
    lines = report_text.split("\n")
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped or stripped.startswith(">"):
            i += 1
            continue

        if stripped.startswith("|") and stripped.endswith("|"):
            table_rows = []
            while i < len(lines):
                row_s = lines[i].strip()
                if not (row_s.startswith("|") and row_s.endswith("|")):
                    break
                if not re.match(r"^\|[\s\-:|]+\|$", row_s):
                    cells = [re.sub(r"\*\*(.*?)\*\*", r"\1", c.strip()) for c in row_s.strip("|").split("|")]
                    table_rows.append(cells)
                i += 1
            if table_rows:
                max_cols = max(len(r) for r in table_rows)
                t = doc.add_table(rows=len(table_rows), cols=max_cols)
                t.style = "Table Grid"
                for r_idx, r_data in enumerate(table_rows):
                    for c_idx, val in enumerate(r_data):
                        cell = t.cell(r_idx, c_idx)
                        cell.text = val
                        for p in cell.paragraphs:
                            for run in p.runs:
                                _set_malgun_font(run)
                                if r_idx == 0:
                                    run.bold = True
            continue

        clean_line = re.sub(r"\*\*(.*?)\*\*", r"\1", stripped)
        
        if stripped.startswith("#### "):
            h = doc.add_heading(clean_line.replace("#### ", ""), level=2)
            for run in h.runs:
                _set_malgun_font(run)
        elif stripped.startswith("### ") or stripped.startswith("## "):
            heading_text = clean_line.replace("### ", "").replace("## ", "")
            h = doc.add_heading(heading_text, level=1)
            for run in h.runs:
                _set_malgun_font(run)
        elif stripped.startswith("- ") or stripped.startswith("* "):
            p = doc.add_paragraph(clean_line[2:], style="List Bullet")
            p.paragraph_format.space_after = Pt(4)
        elif not re.match(r"^-{3,}$", stripped):
            p = doc.add_paragraph(clean_line)
            p.paragraph_format.space_after = Pt(6)
        i += 1
            
    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()

# ---------------------------------------------------------
# 헬퍼 함수 3: 정식 PDF 직접 생성 엔진 (+ 📕 하단 면책문구 여백 최적화 완료)
# ---------------------------------------------------------
def _ensure_korean_font() -> tuple[str, str]:
    reg_name = "KoreanFont"
    bold_name = "KoreanFontBold"
    if reg_name in pdfmetrics.getRegisteredFontNames():
        return reg_name, bold_name

    font_dir = STORAGE_DIR
    reg_path = os.path.join(font_dir, "NanumGothic.ttf")
    bold_path = os.path.join(font_dir, "NanumGothicBold.ttf")

    win_malgun = "C:/Windows/Fonts/malgun.ttf"
    win_malgun_bd = "C:/Windows/Fonts/malgunbd.ttf"

    if os.path.exists(win_malgun) and os.path.exists(win_malgun_bd):
        reg_path, bold_path = win_malgun, win_malgun_bd
    else:
        try:
            if not os.path.exists(reg_path):
                urllib.request.urlretrieve(
                    "https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Regular.ttf",
                    reg_path
                )
            if not os.path.exists(bold_path):
                urllib.request.urlretrieve(
                    "https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Bold.ttf",
                    bold_path
                )
        except Exception as e:
            print(f"⚠️ 한글 폰트 다운로드 오류: {e}")

    try:
        pdfmetrics.registerFont(TTFont(reg_name, reg_path))
        pdfmetrics.registerFont(TTFont(bold_name, bold_path if os.path.exists(bold_path) else reg_path))
        return reg_name, bold_name
    except Exception:
        return "Helvetica", "Helvetica-Bold"

def _strip_emojis_for_pdf(text: str) -> str:
    return re.sub(r"[\U00010000-\U0010ffff]", "", text or "")

def _md_to_rl_xml(text: str, bold_font: str) -> str:
    s = _strip_emojis_for_pdf(text).strip()
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    s = re.sub(r"\*\*(.+?)\*\*", rf'<font name="{bold_font}">\1</font>', s)
    s = re.sub(r"`([^`]+)`", r'<font backColor="#f1f5f9">\1</font>', s)
    return s

def _draw_page_footer(canvas, doc):
    canvas.saveState()
    reg_font, _ = _ensure_korean_font()

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
    page_num_str = f"- {doc.page} -"
    canvas.drawRightString(A4[0] - 40, 24, page_num_str)
    canvas.restoreState()

def create_pdf_report(report_text: str) -> bytes:
    reg_font, bold_font = _ensure_korean_font()
    cleaned_text = _sanitize_math_text(report_text)
    raw_lines = cleaned_text.split("\n")

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=40,
        rightMargin=40,
        topMargin=42,
        bottomMargin=48
    )
    usable_width = A4[0] - 80

    styles = getSampleStyleSheet()
    style_h2 = ParagraphStyle(
        "DocH2", parent=styles["Normal"], fontName=bold_font,
        fontSize=13, leading=19, textColor=colors.HexColor("#1f4e78"),
        spaceBefore=12, spaceAfter=6
    )
    style_h3 = ParagraphStyle(
        "DocH3", parent=styles["Normal"], fontName=bold_font,
        fontSize=11, leading=16, textColor=colors.HexColor("#2e5cb8"),
        spaceBefore=10, spaceAfter=4
    )
    style_body = ParagraphStyle(
        "DocBody", parent=styles["Normal"], fontName=reg_font,
        fontSize=9.8, leading=15.5, textColor=colors.HexColor("#1e293b"),
        spaceAfter=4, wordWrap="CJK"
    )
    style_bullet = ParagraphStyle(
        "DocBullet", parent=style_body, leftIndent=12, firstLineIndent=-8, spaceAfter=3.5
    )
    style_th = ParagraphStyle(
        "DocTH", parent=style_body, fontName=bold_font, fontSize=9.2, leading=13.5,
        textColor=colors.HexColor("#0f172a"), alignment=0
    )
    style_td = ParagraphStyle(
        "DocTD", parent=style_body, fontName=reg_font, fontSize=9.0, leading=13.5,
        textColor=colors.HexColor("#1e293b"), alignment=0
    )

    story = []

    i = 0
    while i < len(raw_lines):
        line = raw_lines[i]
        stripped = line.strip()

        if not stripped:
            story.append(Spacer(1, 4))
            i += 1
            continue

        if stripped.startswith(">"):
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
                r_str = raw_lines[i].strip()
                if not (r_str.startswith("|") and r_str.endswith("|")):
                    break
                table_lines.append(r_str)
                i += 1

            rows_data = []
            for r_str in table_lines:
                if re.match(r"^\|[\s\-:|]+\|$", r_str):
                    continue
                cells = [c.strip() for c in r_str.strip("|").split("|")]
                rows_data.append(cells)

            if rows_data:
                max_cols = max(len(r) for r in rows_data)
                pdf_table_data = []
                for r_idx, r in enumerate(rows_data):
                    padded_r = r + [""] * (max_cols - len(r))
                    row_paras = []
                    for c_text in padded_r:
                        cell_xml = _md_to_rl_xml(c_text, bold_font)
                        row_paras.append(Paragraph(cell_xml, style_th if r_idx == 0 else style_td))
                    pdf_table_data.append(row_paras)

                col_w = usable_width / max_cols
                pdf_table = Table(pdf_table_data, colWidths=[col_w] * max_cols, repeatRows=1)
                t_style = [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ]
                for r_idx in range(1, len(pdf_table_data)):
                    if r_idx % 2 == 0:
                        t_style.append(("BACKGROUND", (0, r_idx), (-1, r_idx), colors.HexColor("#f8fafc")))
                pdf_table.setStyle(TableStyle(t_style))
                story.append(Spacer(1, 4))
                story.append(pdf_table)
                story.append(Spacer(1, 8))
            continue

        if stripped.startswith("#### "):
            story.append(Paragraph(_md_to_rl_xml(stripped[5:], bold_font), style_h3))
        elif stripped.startswith("### "):
            story.append(Paragraph(_md_to_rl_xml(stripped[4:], bold_font), style_h2))
        elif stripped.startswith("## "):
            story.append(Paragraph(_md_to_rl_xml(stripped[3:], bold_font), style_h2))
        elif stripped.startswith("# "):
            story.append(Paragraph(_md_to_rl_xml(stripped[2:], bold_font), style_h2))
        elif stripped.startswith(("- ", "* ")):
            indent_level = (len(line) - len(line.lstrip(" "))) // 2
            b_style = ParagraphStyle(
                f"Bullet_{indent_level}", parent=style_bullet,
                leftIndent=12 + (indent_level * 10)
            )
            story.append(Paragraph("• " + _md_to_rl_xml(stripped[2:], bold_font), b_style))
        else:
            story.append(Paragraph(_md_to_rl_xml(stripped, bold_font), style_body))

        i += 1

    if not story:
        story.append(Paragraph("내용 없음", style_body))

    doc.build(story, onFirstPage=_draw_page_footer, onLaterPages=_draw_page_footer)
    buffer.seek(0)
    return buffer.getvalue()

# ---------------------------------------------------------
# 헬퍼 함수 4: 질문/원클릭 액션 통합 백그라운드 실행기
# ---------------------------------------------------------
def _trigger_agent_task(
    effective_ws_id: str,
    selected_room: str,
    raw_prompt: str,
    pro_toggle_on: bool,
    budget_exceeded: bool = False,
    force_flash: bool = False
) -> None:
    task_mgr = get_background_task_manager()
    current_messages = st.session_state.chat_rooms[selected_room]
    current_file_info = _normalize_room_file_entry(st.session_state.room_files[selected_room])
    st.session_state.room_files[selected_room] = current_file_info

    effective_prompt = raw_prompt.strip()
    if force_flash or budget_exceeded:
        if effective_prompt.startswith("[프로]"):
            effective_prompt = effective_prompt.replace("[프로]", "", 1).strip()
    elif pro_toggle_on and not effective_prompt.startswith("[프로]"):
        effective_prompt = f"[프로] {effective_prompt}"

    has_attached_file = bool(current_file_info["name"] and current_file_info["text"])
    display_prompt = f"📎 **[첨부파일: {current_file_info['name']}]**\n\n{effective_prompt}" if has_attached_file else effective_prompt

    if st.session_state.room_titles[selected_room] in ["빈 대화방", "메인 대화"] and not current_messages:
        auto_title = raw_prompt.strip().replace("[프로]", "").strip().replace("\n", " ")[:14]
        st.session_state.room_titles[selected_room] = auto_title

    is_pro_request = (
        not force_flash and not budget_exceeded and (
            effective_prompt.startswith("[프로]") or (has_attached_file and len(current_file_info["text"]) >= 15000)
        )
    )
    msg_char_cap = 24000 if is_pro_request else 8000

    history_context = ""
    if current_messages:
        recent_msgs = (current_messages[:2] + current_messages[-6:]) if len(current_messages) > 6 else current_messages
        history_lines = [
            "[이 대화방의 이전 대화 맥락 — 사용자가 별도 수식어 없이 후속 질문이나 조건 변경, 카톡/이메일 초안 변환, 또는 '[프로] 다시 검토해 줘'라고 말하더라도 반드시 아래 직전 질문·답변의 사례 금액, 자산 정보, 계산 내역을 그대로 이어받아 답변할 것]"
        ]
        for m in recent_msgs:
            role_label = "사용자" if m["role"] == "user" else "에이전트"
            history_lines.append(f"- {role_label}: {m['content'][:msg_char_cap]}")
        history_context = "\n".join(history_lines) + "\n\n"

    current_messages.append({"role": "user", "content": display_prompt})
    save_workspace_to_disk(effective_ws_id)

    if has_attached_file and not force_flash:
        doc_cap = MAX_DOC_CHARS_PRO if is_pro_request else MAX_DOC_CHARS_STANDARD
        full_input_for_agent = (
            f"{history_context}"
            f"[현재 사용자 질문]: {effective_prompt}\n\n"
            f"아래는 사용자가 현재 대화방에 업로드한 첨부파일({current_file_info['name']})의 데이터입니다. "
            f"직전 대화 맥락과 이 파일 데이터를 바탕으로 관련 법령·예규·판례·환율을 정밀 대조하여 답변하세요:\n"
            f"========================================\n"
            f"{current_file_info['text'][:doc_cap]}\n"
            f"========================================"
        )
    else:
        full_input_for_agent = f"{history_context}[현재 사용자 질문]: {effective_prompt}" if history_context else effective_prompt

    new_task_info = {
        "status": "running",
        "response": None,
        "is_pro": is_pro_request,
        "started_at": time.time()
    }
    worker_thread = threading.Thread(
        target=_background_agent_worker,
        args=(
            effective_ws_id,
            selected_room,
            full_input_for_agent,
            effective_prompt,
            (has_attached_file and not force_flash),
            is_pro_request,
            new_task_info
        ),
        daemon=True
    )
    new_task_info["thread"] = worker_thread
    task_mgr["tasks"][f"{effective_ws_id}::{selected_room}"] = new_task_info
    worker_thread.start()
    st.rerun()

# ---------------------------------------------------------
# 헬퍼 함수 5: 📜 법제처 공식 『제·개정이유서』 0토큰 원문 열람 뷰어 & 🔑 API키 통합 관리 모달
# ---------------------------------------------------------
_dialog_decorator = getattr(st, "dialog", getattr(st, "experimental_dialog", None))

def _render_official_reason_viewer_body(
    law_prom_map: dict[str, dict],
    effective_ws_id: str,
    selected_room: str,
    pro_toggle_on: bool,
    budget_exceeded: bool = False,
    preselected_clean_name: str = ""
):
    st.caption(
        "💡 **AI 토큰을 전혀 소모하지 않고(0원)** 국가법령정보센터(법제처 DRF) XML에서 "
        "정부가 직접 작성한 **공식 『제·개정이유 및 주요내용(입법이유)』** 원문을 즉시 불러옵니다."
    )
    items = list(law_prom_map.values())
    if not items:
        st.warning("법제처 공포 정보를 불러오지 못했습니다.")
        return

    options_clean = [it["clean_name"] for it in items]
    default_idx = options_clean.index(preselected_clean_name) if preselected_clean_name in options_clean else 0

    def _fmt_law_opt(cname: str) -> str:
        it = law_prom_map[cname]
        tag = "🚀시행예정" if it["is_future_enforcement"] else (f"🆕공포 D+{it['days_since_prom']}" if it["is_recent_promulgation"] else "현행")
        return f"📘 {it['law_name']} ({it['rev_type']} | 공포: {it['prom_date']} | 시행: {it['enf_date']} | {tag})"

    chosen_clean = st.selectbox(
        "열람할 법령·시행령 선택",
        options=options_clean,
        index=default_idx,
        format_func=_fmt_law_opt
    )
    chosen_item = law_prom_map[chosen_clean]

    st.markdown(
        f"**공포번호:** 제{chosen_item['prom_no']}호 &nbsp;|&nbsp; "
        f"**공포일:** `{chosen_item['prom_date']}` &nbsp;|&nbsp; "
        f"**시행일:** `{chosen_item['enf_date']}` &nbsp;|&nbsp; "
        f"**구분:** `{chosen_item['rev_type']}`"
    )

    with st.spinner("법제처 공식 『제·개정이유서(입법이유)』 원문 수신 중 (0토큰)..."):
        official_reason_text = fetch_official_revision_reason_zero_token(
            chosen_item["law_id"],
            chosen_item["law_name"],
            chosen_item.get("mst_id", ""),
            chosen_item.get("enf_raw", "")
        )

    st.text_area(
        "📜 법제처 공식 『제·개정이유 및 주요내용』 원문",
        value=official_reason_text,
        height=320
    )

    c_v1, c_v2 = st.columns(2)
    with c_v1:
        if st.button("🔄 법제처 최신 공포정보 새로고침", use_container_width=True):
            fetch_latest_tax_law_promulgations.clear()
            fetch_official_revision_reason_zero_token.clear()
            st.rerun()
    with c_v2:
        if st.button(f"⚡ 상단 배너에 「{chosen_item['law_name']}」 신·구법 비교 열기", use_container_width=True):
            curr_msgs = st.session_state.chat_rooms.get(selected_room, [])
            diff_md = generate_banner_law_diff_table(
                curr_msgs, [chosen_item], room_key=f"{effective_ws_id}::{selected_room}"
            )
            st.session_state.setdefault("room_diff_banners", {})[selected_room] = diff_md
            st.session_state[f"diff_banner_open_{selected_room}"] = True
            save_workspace_to_disk(effective_ws_id)
            st.rerun()

# ---------------------------------------------------------
# 🔐 [🔑 API키] 관리자(Manager) 전용 Google 계정 로그인 보안 모듈
# ---------------------------------------------------------
MANAGER_AUTH_FILE = os.path.join(STORAGE_DIR, "_manager_google_auth.json")

def _hash_manager_secret(val: str) -> str:
    return hashlib.sha256(val.strip().encode("utf-8")).hexdigest()

def _mask_google_email(email_str: str) -> str:
    email_str = (email_str or "").strip()
    if "@" not in email_str:
        return email_str
    local_part, domain_part = email_str.split("@", 1)
    if len(local_part) <= 2:
        masked_local = local_part[0] + "***" if local_part else "***"
    else:
        masked_local = local_part[:2] + "*" * max(3, len(local_part) - 2)
    return f"{masked_local}@{domain_part}"

def _load_manager_google_config() -> dict:
    cfg = {"email": "", "pin_hash": "", "source": "none"}
    env_email = ""
    env_pin = ""
    for k in ["MANAGER_GOOGLE_EMAIL", "ADMIN_GOOGLE_EMAIL", "OWNER_GOOGLE_EMAIL", "MANAGER_EMAIL", "ADMIN_EMAIL"]:
        val = os.environ.get(k, "").strip()
        if not val and hasattr(st, "secrets"):
            try:
                val = str(st.secrets.get(k, "")).strip()
            except Exception:
                val = ""
        if val and "@" in val:
            env_email = val.lower()
            break

    for pk in ["MANAGER_SECURITY_PIN", "MANAGER_PASSWORD", "ADMIN_PASSWORD", "MANAGER_PIN"]:
        pval = os.environ.get(pk, "").strip()
        if not pval and hasattr(st, "secrets"):
            try:
                pval = str(st.secrets.get(pk, "")).strip()
            except Exception:
                pval = ""
        if pval:
            env_pin = pval
            break

    if os.path.exists(MANAGER_AUTH_FILE):
        try:
            with open(MANAGER_AUTH_FILE, "r", encoding="utf-8") as f:
                disk_cfg = json.load(f)
            if isinstance(disk_cfg, dict):
                cfg["email"] = str(disk_cfg.get("email", "")).strip().lower()
                cfg["pin_hash"] = str(disk_cfg.get("pin_hash", "")).strip()
                cfg["source"] = "disk"
        except Exception:
            pass

    if env_email:
        cfg["email"] = env_email
        if env_pin:
            cfg["pin_hash"] = _hash_manager_secret(env_pin)
        cfg["source"] = "secrets"

    return cfg

def _save_manager_google_config(email_str: str, pin_plain: str) -> None:
    os.makedirs(STORAGE_DIR, exist_ok=True)
    payload = {
        "email": email_str.strip().lower(),
        "pin_hash": _hash_manager_secret(pin_plain),
        "updated_at": datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M:%S")
    }
    with open(MANAGER_AUTH_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

def _get_streamlit_logged_google_email() -> str:
    try:
        u_obj = getattr(st, "user", None) or getattr(st, "experimental_user", None)
        if u_obj is not None:
            is_logged = getattr(u_obj, "is_logged_in", True)
            raw_email = getattr(u_obj, "email", None)
            if not raw_email and isinstance(u_obj, dict):
                raw_email = u_obj.get("email")
            if is_logged and raw_email:
                clean_em = str(raw_email).strip().lower()
                if clean_em and clean_em != "test@example.com" and "@" in clean_em:
                    return clean_em
    except Exception:
        pass
    return ""

def _render_api_key_manager_body(expiry_all_status: list[dict], law_prom_map: dict):
    mgr_cfg = _load_manager_google_config()
    registered_email = mgr_cfg.get("email", "").strip().lower()
    registered_pin_hash = mgr_cfg.get("pin_hash", "").strip()
    oauth_google_email = _get_streamlit_logged_google_email()
    session_authed_email = str(st.session_state.get("manager_google_authed_email", "")).strip().lower()

    if not registered_email:
        st.warning("🔒 **[보안 설정 필요] 관리자(Manager) Google 계정을 최초 1회 등록해 주세요.**")
        st.caption(
            "아무나 `[🔑 API키]` 버튼을 눌러 API 키 목록이나 관리 링크를 열람·복사하지 못하도록, "
            "본인(Manager)의 Google 계정 이메일과 관리자 보안 비밀번호를 등록합니다."
        )
        with st.container(border=True):
            st.markdown("##### 🛡️ 관리자(Manager) Google 계정 최초 등록")
            default_em = oauth_google_email if oauth_google_email else ""
            reg_email = st.text_input(
                "관리자 Google 이메일 주소",
                value=default_em,
                placeholder="예: myaccount@gmail.com",
                key="mgr_reg_google_email"
            )
            reg_pin1 = st.text_input(
                "관리자 전용 보안 비밀번호 설정 (API키 잠금 해제용)",
                type="password",
                placeholder="본인만 아는 보안 비밀번호 입력",
                key="mgr_reg_pin1"
            )
            reg_pin2 = st.text_input(
                "관리자 전용 보안 비밀번호 확인",
                type="password",
                placeholder="보안 비밀번호 다시 입력",
                key="mgr_reg_pin2"
            )
            if st.button("✅ 내 Google 계정을 유일한 관리자로 등록 및 잠금 활성화", type="primary", use_container_width=True):
                clean_reg_em = reg_email.strip().lower()
                if not clean_reg_em or "@" not in clean_reg_em:
                    st.error("유효한 Google 이메일 주소(예: example@gmail.com)를 입력해 주세요.")
                elif len(reg_pin1.strip()) < 4:
                    st.error("보안 비밀번호는 최소 4자리 이상 입력해 주세요.")
                elif reg_pin1.strip() != reg_pin2.strip():
                    st.error("입력하신 두 보안 비밀번호가 일치하지 않습니다.")
                else:
                    _save_manager_google_config(clean_reg_em, reg_pin1.strip())
                    st.session_state.manager_google_authed_email = clean_reg_em
                    st.success(f"✅ 관리자 Google 계정({clean_reg_em}) 등록 및 보안 잠금이 완료되었습니다!")
                    st.rerun()
        return

    is_oauth_manager = bool(oauth_google_email and oauth_google_email == registered_email)
    is_session_manager = bool(session_authed_email and session_authed_email == registered_email)
    is_manager_verified = is_oauth_manager or is_session_manager

    if not is_manager_verified:
        masked_mgr = _mask_google_email(registered_email)
        st.error(
            f"🔒 **관리자(Manager) 전용 보안 구역입니다.** "
            f"API 키 보호를 위해 등록된 관리자 Google 계정(**`{masked_mgr}`**)으로 로그인해야 열람할 수 있습니다."
        )
        if oauth_google_email and oauth_google_email != registered_email:
            st.warning(
                f"🚫 현재 브라우저에 로그인된 Google 계정(`{oauth_google_email}`)은 관리자 계정이 아닙니다. "
                f"관리자 계정(`{masked_mgr}`)으로 로그인해 주세요."
            )

        with st.container(border=True):
            st.markdown("##### 🌐 방법 1. Google 계정으로 바로 로그인 (Streamlit OAuth)")
            c_gl1, c_gl2 = st.columns(2)
            with c_gl1:
                if st.button("🔐 Google 로그인 (Manager 인증)", type="primary", use_container_width=True, key="btn_st_google_oauth"):
                    if hasattr(st, "login"):
                        try:
                            st.login()
                        except Exception:
                            st.session_state.show_google_oauth_guide = True
                    else:
                        st.session_state.show_google_oauth_guide = True
            with c_gl2:
                st.link_button("🌐 Google 계정 로그인 페이지 열기", "https://accounts.google.com/", use_container_width=True)

            if st.session_state.get("show_google_oauth_guide"):
                st.info(
                    "💡 현재 앱에 Streamlit OIDC(`secrets.toml`의 `[auth]`) 설정이 없어 아래 **방법 2(관리자 Google 이메일 + 보안 비밀번호 인증)**로 즉시 로그인하실 수 있습니다."
                )

        with st.container(border=True):
            st.markdown("##### 🔑 방법 2. 등록된 Manager Google 계정 & 보안 암호로 열기")
            input_g_email = st.text_input(
                "Google 계정 이메일",
                placeholder=f"등록된 관리자 구글 이메일 입력 ({masked_mgr})",
                key="login_mgr_google_email"
            )
            input_g_pin = st.text_input(
                "관리자 보안 비밀번호",
                type="password",
                placeholder="관리자 보안 비밀번호 입력",
                key="login_mgr_google_pin"
            )
            if st.button("🔓 관리자 Google 계정 인증 및 API키 열기", type="primary", use_container_width=True, key="btn_verify_mgr_pin"):
                cand_email = input_g_email.strip().lower()
                cand_pin_hash = _hash_manager_secret(input_g_pin.strip())
                if cand_email != registered_email:
                    st.error("🚫 입력하신 이메일이 등록된 관리자(Manager) Google 계정과 일치하지 않습니다.")
                elif registered_pin_hash and cand_pin_hash != registered_pin_hash:
                    st.error("🚫 관리자 보안 비밀번호가 일치하지 않습니다.")
                else:
                    st.session_state.manager_google_authed_email = registered_email
                    st.success("✅ 관리자(Manager) Google 계정 인증이 완료되었습니다.")
                    st.rerun()
        return

    with st.container(border=True):
        c_top1, c_top2 = st.columns([3.6, 1.4])
        with c_top1:
            st.markdown(f"🛡️ **관리자(Manager) Google 인증 완료:** `{registered_email}`")
            st.caption("현재 에이전트AI에 연동된 전체 API 상태와 만료 예정 키 갱신 바로가기입니다.")
        with c_top2:
            if st.button("🔒 잠금 (로그아웃)", use_container_width=True, key="btn_lock_api_modal"):
                st.session_state.manager_google_authed_email = ""
                if is_oauth_manager and hasattr(st, "logout"):
                    try:
                        st.logout()
                    except Exception:
                        pass
                st.rerun()

    gemini_ok = _check_api_configured(["GEMINI_PAID_KEY", "GEMINI_API_KEY"])
    g_led = "🟢 연동됨" if gemini_ok else "🟡 미설정"
    with st.container(border=True):
        c_g1, c_g2 = st.columns([3.6, 1.4])
        with c_g1:
            st.markdown(f"**1. Google AI Studio (Gemini 유료 API 키)** &nbsp;|&nbsp; `{g_led}`")
            st.caption("구글 AI 스튜디오 API 키 발급 및 관리 (유료 Pay-as-you-go 연동)")
        with c_g2:
            st.link_button("🔗 링크 열기", "https://aistudio.google.com/apikey", use_container_width=True)

    law_ok = bool(_get_law_oc()) or _check_api_configured(["LAW_OPEN_API_KEY", "LAW_API_OC", "OC"]) or bool(law_prom_map)
    dart_ok = _check_api_configured(["DART_API_KEY", "OPENDART_API_KEY"])
    ind_ok = os.path.exists("industry_codes.xlsx")

    permanent_apis = [
        (
            "2. 국가법령정보센터 (법령·판례·심판례·예규 API)",
            "🟢 연동됨 (무기한)" if law_ok else "🟡 미설정",
            "법제처 OPEN API 신청 및 인증키(OC) 관리",
            "https://open.law.go.kr/LSO/openApi/guideList.do"
        ),
        (
            "3. 금융감독원 전자공시시스템 (Open DART API)",
            "🟢 연동됨 (무기한)" if dart_ok else "🟡 미설정",
            "기업개황·재무제표·지분·배당 조회용 오픈다트 인증키 관리",
            "https://opendart.fss.or.kr/uss/umt/EgovMberManage.do"
        ),
    ]
    for title_txt, status_txt, desc_txt, link_url in permanent_apis:
        with st.container(border=True):
            c_p1, c_p2 = st.columns([3.6, 1.4])
            with c_p1:
                st.markdown(f"**{title_txt}** &nbsp;|&nbsp; `{status_txt}`")
                st.caption(desc_txt)
            with c_p2:
                st.link_button("🔗 링크 열기", link_url, use_container_width=True)

    st.markdown("##### ⏰ 주기적 갱신이 필요한 API (만료 예정일 확인 및 바로 갱신)")
    current_expiry_map = load_api_expiry_dates()
    updated_expiry_map = {}

    key_check_map = {
        "VWORLD": ["VWORLD_API_KEY"],
        "DATA_GO_KR": ["NTS_API_KEY", "DATA_GO_KR_KEY", "PUBLIC_DATA_KEY", "MOLIT_API_KEY"],
        "BOK_ECOS": ["BOK_API_KEY", "ECOS_API_KEY"],
    }

    for idx, st_item in enumerate(expiry_all_status, start=4):
        code = st_item["code"]
        d_left = st_item["days_left"]
        is_conn = _check_api_configured(key_check_map.get(code, []))
        conn_tag = "🟢 연동됨" if is_conn else "🟡 미설정"
        if d_left < 0:
            d_tag = f"🚨 만료됨 (D+{-d_left})"
        elif d_left <= 30:
            d_tag = f"🔴 만료임박 (D-{d_left})"
        else:
            d_tag = f"🟢 정상 (D-{d_left})"

        with st.container(border=True):
            c_e1, c_e2 = st.columns([3.6, 1.4])
            with c_e1:
                st.markdown(
                    f"**{idx}. {st_item['name']}** &nbsp;|&nbsp; `{conn_tag}` &nbsp;|&nbsp; `{d_tag}` *(주기: {st_item['cycle']})*"
                )
                val_str = st.text_input(
                    f"{st_item['name']} 만료일 (YYYY-MM-DD)",
                    value=current_expiry_map.get(code, st_item["date_str"]),
                    placeholder="YYYY-MM-DD",
                    label_visibility="collapsed",
                    key=f"modal_exp_input_{code}"
                )
                updated_expiry_map[code] = val_str.strip()
            with c_e2:
                st.link_button("🔗 링크 열기", st_item["url"], use_container_width=True)

    with st.container(border=True):
        ind_led = "🟢 정상 로드됨" if ind_ok else "🟡 파일 없음"
        st.markdown(f"**7. 국세청 6자리 업종코드 마스터 DB (`industry_codes.xlsx`)** &nbsp;|&nbsp; `{ind_led}`")

    if st.button("💾 수정한 API 만료일 저장", use_container_width=True):
        save_api_expiry_dates(updated_expiry_map)
        st.success("API 만료일이 저장되었습니다!")
        st.rerun()

    with st.expander("⚙️ 관리자(Manager) Google 계정 또는 보안 비밀번호 변경"):
        new_mgr_em = st.text_input("변경할 관리자 Google 이메일", value=registered_email, key="chg_mgr_email")
        new_mgr_pw = st.text_input("새 관리자 보안 비밀번호 (4자리 이상)", type="password", key="chg_mgr_pw")
        if st.button("🔄 관리자 보안 정보 업데이트", key="btn_chg_mgr_save"):
            if "@" not in new_mgr_em.strip():
                st.error("유효한 Google 이메일을 입력해 주세요.")
            elif len(new_mgr_pw.strip()) < 4:
                st.error("새 보안 비밀번호를 4자리 이상 입력해 주세요.")
            else:
                _save_manager_google_config(new_mgr_em.strip().lower(), new_mgr_pw.strip())
                st.session_state.manager_google_authed_email = new_mgr_em.strip().lower()
                st.success("✅ 관리자 Google 계정 및 보안 비밀번호가 변경되었습니다.")
                st.rerun()

if _dialog_decorator:
    @_dialog_decorator("📜 법제처 공식 『제·개정이유 및 주요내용』 원문 뷰어", width="large")
    def open_official_reason_modal(
        law_prom_map: dict[str, dict],
        effective_ws_id: str,
        selected_room: str,
        pro_toggle_on: bool,
        budget_exceeded: bool = False,
        preselected_clean_name: str = ""
    ):
        _render_official_reason_viewer_body(
            law_prom_map, effective_ws_id, selected_room, pro_toggle_on, budget_exceeded, preselected_clean_name
        )

    @_dialog_decorator("🔑 연동 API 리스트 및 키 갱신·만료일 관리", width="large")
    def open_api_key_manager_modal(expiry_all_status: list[dict], law_prom_map: dict):
        _render_api_key_manager_body(expiry_all_status, law_prom_map)

# ---------------------------------------------------------
# 2. 왼쪽 사이드바 제어판 (현재 크기·비율 유지 + 옵션 C 오로라 로딩 LED)
# ---------------------------------------------------------
task_mgr = get_background_task_manager()
expiry_alerts, expiry_all_status = check_api_expiry_alerts()
law_prom_map = fetch_latest_tax_law_promulgations()
budget_exceeded = False

if "app_top_mode" not in st.session_state:
    st.session_state.app_top_mode = "AGENT"

with st.sidebar:
    # 🔀 [최상단 고정: "자율 에이전트AI" / "통합고용세액공제" 2열 전환 버튼]
    sb_m1, sb_m2 = st.columns(2, gap="small")
    with sb_m1:
        if st.button(
            "자율 에이전트AI",
            key="btn_top_mode_agent",
            type=("primary" if st.session_state.app_top_mode == "AGENT" else "secondary"),
            use_container_width=True,
        ):
            st.session_state.app_top_mode = "AGENT"
            st.rerun()
    with sb_m2:
        if st.button(
            "통합고용세액공제",
            key="btn_top_mode_credit",
            type=("primary" if st.session_state.app_top_mode == "CREDIT_CALC" else "secondary"),
            use_container_width=True,
        ):
            st.session_state.app_top_mode = "CREDIT_CALC"
            st.rerun()

    st.markdown(
        "<div style='font-size:1.02rem; font-weight:800; color:#0f172a; line-height:1.4; margin-top:4px; margin-bottom:2px; letter-spacing:-0.3px;'>"
        "⚙️ 에이전트 제어판</div>",
        unsafe_allow_html=True
    )
    
    # 📦 [카드 1] 엔진 출력 모드 제어
    with st.container(border=True):
        is_pro_now = st.session_state.get("pro_toggle_state", False)
        mode_pill = (
            "<span class='sb-badge-pro'>🧠 Pro 3배 개방</span>"
            if is_pro_now else
            "<span class='sb-badge-green'>⚡ Flash 고속</span>"
        )
        st.markdown(f"<div class='sb-card-title'><span>🚀 엔진 출력 모드</span>{mode_pill}</div>", unsafe_allow_html=True)
        pro_toggle_on = st.toggle(
            "Pro 심층 모드 (3배 리미트 해제)",
            value=is_pro_now,
            help="켜두면 질문 앞에 [프로]를 입력하지 않아도 최대 15만 자 문서 독해 및 30회 도구 호출 모드로 작동합니다."
        )
        st.session_state.pro_toggle_state = pro_toggle_on

    # 📦 [카드 2] 내 작업공간 (자동 동기화)
    with st.container(border=True):
        ws_widget_ver = st.session_state.get("ws_widget_ver", 0)
        saved_ws_val = st.session_state.get("active_workspace_id", "")
        ws_pill = (
            "<span class='sb-badge-green'>🟢 보안 저장중</span>"
            if saved_ws_val.strip() else
            "<span class='sb-badge-amber'>🔓 공용 임시</span>"
        )
        st.markdown(f"<div class='sb-card-title'><span>🔐 내 작업공간 코드</span>{ws_pill}</div>", unsafe_allow_html=True)
        workspace_input = st.text_input(
            "작업공간 코드",
            value=saved_ws_val,
            type="password",
            placeholder="나만의 암호 입력 후 Enter",
            label_visibility="collapsed",
            key=f"ws_input_box_{ws_widget_ver}",
            help="동일한 코드를 입력하면 다른 PC에서도 1~10번 방 대화와 파일이 그대로 유지됩니다."
        )
        effective_ws_id = workspace_input.strip() if workspace_input.strip() else "default_public"

        if st.session_state.get("loaded_workspace_id") != effective_ws_id:
            ws_data = load_workspace_from_disk(effective_ws_id)
            st.session_state.chat_rooms = ws_data["chat_rooms"]
            st.session_state.room_titles = ws_data["room_titles"]
            st.session_state.room_files = ws_data["room_files"]
            st.session_state.room_diff_banners = ws_data.get("room_diff_banners", {r_id: "" for r_id in ROOM_IDS})
            st.session_state.loaded_workspace_id = effective_ws_id
            st.session_state.active_workspace_id = workspace_input.strip()
            if "current_room" not in st.session_state:
                st.session_state.current_room = ROOM_IDS[0]
            st.rerun()

        # 백그라운드 완료 작업 자동 반영
        for r_id in ROOM_IDS:
            st.session_state.room_files[r_id] = _normalize_room_file_entry(st.session_state.room_files.get(r_id, {}))
            t_key = f"{effective_ws_id}::{r_id}"
            t_info = task_mgr["tasks"].get(t_key)
            if t_info and t_info.get("status") == "done":
                ans = t_info.get("response", "")
                room_msgs = st.session_state.chat_rooms[r_id]
                if ans and (not room_msgs or room_msgs[-1].get("role") != "assistant" or room_msgs[-1].get("content") != ans):
                    room_msgs.append({"role": "assistant", "content": ans})
                del task_mgr["tasks"][t_key]

        if workspace_input.strip():
            if st.button("🔒 작업공간 잠금 (나가기)", use_container_width=True):
                st.session_state.active_workspace_id = ""
                st.session_state.loaded_workspace_id = None
                st.session_state.ws_widget_ver = ws_widget_ver + 1
                st.rerun()

    # 📦 [카드 3] 멀티 대화방 (입체 비우기 버튼 + 1~10번 좌측 정렬 리스트 + 옵션 C 제미나이 오로라 로딩 LED)
    with st.container(border=True):
        if "current_room" not in st.session_state or st.session_state.current_room not in ROOM_IDS:
            st.session_state.current_room = ROOM_IDS[0]
        selected_room = st.session_state.current_room
        active_room_key = f"{effective_ws_id}::{selected_room}"

        rooms_with_rev_cnt = sum(
            1 for r_id in ROOM_IDS
            if get_room_revision_alerts(effective_ws_id, r_id, st.session_state.chat_rooms.get(r_id, []), law_prom_map)[0]
        )
        rev_header_pill = (
            f"<span class='sb-badge-amber'>🔄 {rooms_with_rev_cnt}개방 개정</span>"
            if rooms_with_rev_cnt > 0 else ""
        )
        st.markdown(f"<div class='sb-card-title'><span>🗂️ 멀티 대화방 (1~10번)</span>{rev_header_pill}</div>", unsafe_allow_html=True)

        room_search_kw = st.text_input(
            "전체 대화방 통합 검색",
            placeholder="🔎 1~10번 방 통합 키워드 검색",
            label_visibility="collapsed",
            key=f"room_search_{effective_ws_id}"
        )
        if room_search_kw.strip():
            kw_lower = room_search_kw.strip().lower()
            matched_rooms = []
            for r_id in ROOM_IDS:
                r_title = st.session_state.room_titles.get(r_id, "")
                r_fname = st.session_state.room_files[r_id].get("name") or ""
                r_msgs = st.session_state.chat_rooms.get(r_id, [])
                hit_cnt = sum(1 for m in r_msgs if kw_lower in m.get("content", "").lower())
                if kw_lower in r_title.lower() or kw_lower in r_fname.lower():
                    hit_cnt += 1
                if hit_cnt > 0:
                    matched_rooms.append((r_id, r_title, hit_cnt))
            if matched_rooms:
                for m_rid, m_title, m_cnt in matched_rooms:
                    if st.button(f"👉 {m_rid} [{m_title}] ({m_cnt}건 일치)", key=f"jump_{m_rid}", use_container_width=True):
                        st.session_state.current_room = m_rid
                        st.rerun()
            else:
                st.caption(f"'{room_search_kw}' 검색 결과가 없습니다.")

        new_title = st.text_input(
            "방 주제 메모",
            value=st.session_state.room_titles[selected_room],
            placeholder="✏️ 현재 방 주제 메모 (예: A사 세무조사)",
            label_visibility="collapsed",
            key=f"title_input_{effective_ws_id}_{selected_room}"
        )
        if new_title != st.session_state.room_titles[selected_room]:
            st.session_state.room_titles[selected_room] = new_title
            save_workspace_to_disk(effective_ws_id)
            st.rerun()

        # 🗑️ 입체감이 살아있는 [현재 방 비우기] 버튼
        if st.button(f"🗑️ [{selected_room}] 현재 방 비우기", key="btn_clear_current_room", use_container_width=True):
            task_mgr["tasks"].pop(active_room_key, None)
            st.session_state.chat_rooms[selected_room] = []
            st.session_state.room_files[selected_room] = {"name": None, "text": "", "items": []}
            st.session_state.room_titles[selected_room] = "빈 대화방"
            st.session_state.setdefault("room_diff_banners", {})[selected_room] = ""
            st.session_state[f"diff_banner_open_{selected_room}"] = False
            if hasattr(agent, "reset_room_usage"):
                agent.reset_room_usage(active_room_key)
            st.session_state[f"reset_cnt_{selected_room}"] = st.session_state.get(f"reset_cnt_{selected_room}", 0) + 1
            save_workspace_to_disk(effective_ws_id)
            st.rerun()

        # 📋 [1번~10번 세로 1열 클릭 리스트 — 왼쪽 정렬 + 우측 끝 동그라미 LED (작성 중일 때는 옵션 C 오로라 펄스 작동)]
        for idx_r, r_id in enumerate(ROOM_IDS, start=1):
            r_title = (st.session_state.room_titles.get(r_id, "빈 대화방") or "빈 대화방").strip()
            short_title = r_title[:14] + ("…" if len(r_title) > 14 else "")
            r_msgs = st.session_state.chat_rooms.get(r_id, [])
            q_cnt = (len(r_msgs) + 1) // 2
            f_cnt = len(st.session_state.room_files[r_id].get("items", []))
            t_info = task_mgr["tasks"].get(f"{effective_ws_id}::{r_id}")
            is_run = bool(t_info and t_info.get("status") == "running")
            rev_alerts, _ = get_room_revision_alerts(effective_ws_id, r_id, r_msgs, law_prom_map)

            base_state = "active" if r_id == selected_room else ("hasmsg" if q_cnt > 0 else "empty")
            run_suffix = "_running" if is_run else ""
            btn_key = f"room_btn_{idx_r}_{base_state}{run_suffix}"

            extra_badges = (" 📎" if f_cnt else "") + (" 🔄" if rev_alerts else "") + (" (작성중)" if is_run else "")
            btn_label = f"{idx_r}. {short_title} ({q_cnt}건){extra_badges}"

            if st.button(btn_label, key=btn_key, use_container_width=True):
                if r_id != selected_room:
                    st.session_state.current_room = r_id
                    st.rerun()

    # 📦 [카드 4 — 최하단 고정: [💳 결제] 및 [🔑 API키] 버튼]
    with st.container(border=True):
        col_b1, col_b2 = st.columns(2)
        with col_b1:
            st.link_button("💳 결제", "https://console.cloud.google.com/billing", use_container_width=True)
        with col_b2:
            if st.button("🔑 API키", use_container_width=True, help="연동된 전체 API 리스트 및 갱신 링크 열기"):
                if _dialog_decorator:
                    open_api_key_manager_modal(expiry_all_status, law_prom_map)
                else:
                    st.session_state.show_inline_api_manager = not st.session_state.get("show_inline_api_manager", False)

# ---------------------------------------------------------
# 3. 메인 화면 상단 (슬림 상태바 + 문구가 깔끔해진 법령 개정 배너 버튼: '📜 개정이유서' / '⚡ 신·구법 비교')
# ---------------------------------------------------------
current_messages = st.session_state.chat_rooms[selected_room]
current_room_title = st.session_state.room_titles[selected_room]
current_file_info = _normalize_room_file_entry(st.session_state.room_files[selected_room])
current_task_key = f"{effective_ws_id}::{selected_room}"
active_task = task_mgr["tasks"].get(current_task_key)
is_current_room_running = bool(active_task and active_task.get("status") == "running")

if st.session_state.app_top_mode == "CREDIT_CALC":
    if st.session_state.get("show_inline_api_manager"):
        with st.container(border=True):
            st.subheader("🔑 연동 API 리스트 및 키 갱신·만료일 관리")
            _render_api_key_manager_body(expiry_all_status, law_prom_map)
            if st.button("✖️ API 관리창 닫기"):
                st.session_state.show_inline_api_manager = False
                st.rerun()
    import tax_credit_engine
    tax_credit_engine.render_tax_credit_calculator_ui(
        extract_file_fn=extract_file_content,
        create_pdf_fn=create_pdf_report,
        create_docx_fn=create_word_docx,
        log_tokens_fn=_log_custom_tokens,
        active_room_key=current_task_key,
    )
    st.stop()

# 상단 미니 상태바
q_count_now = (len(current_messages) + 1) // 2
mode_badge_html = (
    "🧠 <b>Pro 심층 모드 (3배 리미트 개방 ON)</b>"
    if pro_toggle_on else
    "⚡ <b>Flash 표준 모드 (고속 검토)</b>"
)
st.markdown(
    f"<div class='top-mini-status-bar'>"
    f"<span>💬 <b>{selected_room} [{current_room_title}]</b> ({q_count_now}건 대화 중)</span>"
    f"<span>💡 현재 엔진: {mode_badge_html}</span>"
    f"</div>",
    unsafe_allow_html=True
)

# 🚨 1) [API 유효기간 1개월(30일) 전 자동 경고 배너]
if expiry_alerts:
    for alert_item in expiry_alerts:
        c_al1, c_al2 = st.columns([5, 1])
        with c_al1:
            if alert_item["level"] == "expired":
                st.error(alert_item["msg"])
            else:
                st.warning(alert_item["msg"])
        with c_al2:
            st.link_button("🔗 연장·재발급", alert_item["url"], use_container_width=True)

# 🔄 2) [개정세법 안내 배너 — 버튼 문구 깔끔하게 정리: '📜 개정이유서' / '⚡ 신·구법 비교']
current_room_rev_alerts, is_post_revision = get_room_revision_alerts(
    effective_ws_id, selected_room, current_messages, law_prom_map
)
saved_diff_md = st.session_state.get("room_diff_banners", {}).get(selected_room, "")
is_diff_open = st.session_state.get(f"diff_banner_open_{selected_room}", False)

if current_room_rev_alerts:
    rev_names_str = ", ".join(
        f"「{it['law_name']}」(공포:{it['prom_date']}/시행:{it['enf_date']})" for it in current_room_rev_alerts
    )
    first_clean = current_room_rev_alerts[0]["clean_name"]
    c_rv1, c_rv2, c_rv3, c_rv4 = st.columns([3.4, 1.1, 1.2, 0.7])
    with c_rv1:
        if is_post_revision:
            st.warning(
                f"🔄 **[사후 법령 개정 감지]** 이 방의 과거 검토 이후에 **{rev_names_str}**이 새로 개정 공포되었습니다."
            )
        else:
            st.info(
                f"📜 **[최근 공포·시행예정 법령 인용 안내]** 이 방에서 인용된 **{rev_names_str}**의 공식 입법이유서 및 신·구 비교표를 바로 열람할 수 있습니다."
            )
    with c_rv2:
        if st.button("📜 개정이유서", key=f"rsn_{selected_room}", use_container_width=True):
            if _dialog_decorator:
                open_official_reason_modal(law_prom_map, effective_ws_id, selected_room, pro_toggle_on, False, first_clean)
            else:
                st.session_state.show_inline_reason_viewer = not st.session_state.get("show_inline_reason_viewer", False)
                st.rerun()
    with c_rv3:
        diff_btn_lbl = "🔼 신·구법 비교 닫기" if (saved_diff_md and is_diff_open) else "⚡ 신·구법 비교"
        if st.button(diff_btn_lbl, key=f"rerev_{selected_room}", use_container_width=True):
            if saved_diff_md:
                st.session_state[f"diff_banner_open_{selected_room}"] = not is_diff_open
                st.rerun()
            else:
                with st.spinner("⚡ 본문 대화와 분리된 상단 [조문명 / 구법내용 / 개정법내용 / 개정효과] 비교표를 생성 중입니다..."):
                    diff_md = generate_banner_law_diff_table(
                        current_messages, current_room_rev_alerts, room_key=current_task_key
                    )
                    st.session_state.setdefault("room_diff_banners", {})[selected_room] = diff_md
                    st.session_state[f"diff_banner_open_{selected_room}"] = True
                    save_workspace_to_disk(effective_ws_id)
                st.rerun()
    with c_rv4:
        if st.button("✅ 확인", key=f"ack_{selected_room}", use_container_width=True, help="이 대화방의 법령 알림을 확인 처리하여 숨깁니다."):
            acknowledge_room_laws(effective_ws_id, selected_room, current_room_rev_alerts)
            st.rerun()

# 📊 본문 대화와 무관하게 언제든 열었다 닫았다 할 수 있는 상단 [조문명/구법내용/개정법내용/개정효과] 배너
if saved_diff_md:
    with st.expander("📊 [신·구법 비교] 조문명 / 구법내용 / 개정법내용 / 개정효과 (클릭하여 열기·닫기)", expanded=is_diff_open):
        st.markdown(f"<div class='law-diff-banner-box'>\n\n{saved_diff_md}\n\n</div>", unsafe_allow_html=True)
        b_col1, b_col2 = st.columns([1, 5])
        with b_col1:
            if st.button("🔄 비교표 다시 생성", key=f"regen_diff_{selected_room}"):
                with st.spinner("⚡ 신·구법 비교표를 새로 작성 중입니다..."):
                    alerts_for_regen = current_room_rev_alerts or extract_cited_laws_in_room(current_messages, law_prom_map)
                    diff_md = generate_banner_law_diff_table(
                        current_messages, alerts_for_regen, room_key=current_task_key
                    )
                    st.session_state.setdefault("room_diff_banners", {})[selected_room] = diff_md
                    st.session_state[f"diff_banner_open_{selected_room}"] = True
                    save_workspace_to_disk(effective_ws_id)
                st.rerun()

# 구버전 Streamlit 폴백용 인라인 뷰어들
if st.session_state.get("show_inline_reason_viewer"):
    with st.container(border=True):
        st.subheader("📜 법제처 공식 『제·개정이유 및 주요내용』 원문 뷰어")
        _render_official_reason_viewer_body(law_prom_map, effective_ws_id, selected_room, pro_toggle_on, False)
        if st.button("✖️ 뷰어 닫기"):
            st.session_state.show_inline_reason_viewer = False
            st.rerun()

if st.session_state.get("show_inline_api_manager"):
    with st.container(border=True):
        st.subheader("🔑 연동 API 리스트 및 키 갱신·만료일 관리")
        _render_api_key_manager_body(expiry_all_status, law_prom_map)
        if st.button("✖️ API 관리창 닫기"):
            st.session_state.show_inline_api_manager = False
            st.rerun()

# ---------------------------------------------------------
# 4. 대화방 메시지 목록 렌더링 (미세 디테일 1·2 자동 보정 적용)
# ---------------------------------------------------------
for idx, message in enumerate(current_messages):
    with st.chat_message(message["role"]):
        display_content = message["content"]
        if message["role"] == "assistant" and hasattr(agent, "_inject_direct_law_links"):
            try:
                display_content = agent._inject_direct_law_links(display_content)
            except Exception:
                pass
        display_content = _format_markdown_for_screen(display_content)
        st.markdown(display_content, unsafe_allow_html=True)

        if message["role"] == "assistant":
            # 📥 1줄: 문서 다운로드 버튼 4종 (PDF / 워드 / 표 엑셀(.xlsx) / 마크다운)
            excel_bytes = create_excel_from_markdown_tables(message["content"])
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.download_button(
                    label="📕 정식 PDF (.pdf)",
                    data=create_pdf_report(message["content"]),
                    file_name=f"검토보고서_{selected_room}_{current_room_title}_{idx}.pdf",
                    mime="application/pdf",
                    key=f"pdf_{effective_ws_id}_{selected_room}_{idx}",
                    use_container_width=True
                )
            with col2:
                st.download_button(
                    label="📘 워드 (.docx)",
                    data=create_word_docx(message["content"]),
                    file_name=f"검토보고서_{selected_room}_{current_room_title}_{idx}.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    key=f"docx_{effective_ws_id}_{selected_room}_{idx}",
                    use_container_width=True
                )
            with col3:
                if excel_bytes:
                    st.download_button(
                        label="📊 표 엑셀 (.xlsx)",
                        data=excel_bytes,
                        file_name=f"검토표_{selected_room}_{current_room_title}_{idx}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key=f"xlsx_{effective_ws_id}_{selected_room}_{idx}",
                        use_container_width=True
                    )
                else:
                    st.button("📊 표 없음 (.xlsx)", disabled=True, key=f"no_xlsx_{effective_ws_id}_{selected_room}_{idx}", use_container_width=True)
            with col4:
                st.download_button(
                    label="📝 마크다운 (.md)",
                    data=message["content"].encode("utf-8-sig"),
                    file_name=f"검토보고서_{selected_room}_{current_room_title}_{idx}.md",
                    mime="text/markdown",
                    key=f"md_{effective_ws_id}_{selected_room}_{idx}",
                    use_container_width=True
                )

            # ⚡ 2줄: 타이핑 제로 원클릭 후속 작업 버튼 3종 (카톡/이메일은 Flash 초저가 강제 실행)
            act1, act2, act3 = st.columns(3)
            with act1:
                if st.button(
                    "💬 카톡 안내문 변환 (Flash)",
                    key=f"kakao_{effective_ws_id}_{selected_room}_{idx}",
                    disabled=is_current_room_running,
                    use_container_width=True
                ):
                    _trigger_agent_task(
                        effective_ws_id, selected_room,
                        "방금 작성한 검토 결과를 바탕으로, 거래처 대표님이나 고객에게 카카오톡으로 바로 복사해서 보낼 수 있도록 핵심 결론과 주의사항만 친절하고 정중한 실무 대화체로 요약해 줘.",
                        pro_toggle_on, False, force_flash=True
                    )
            with act2:
                if st.button(
                    "📧 이메일 회신 초안 (Flash)",
                    key=f"email_{effective_ws_id}_{selected_room}_{idx}",
                    disabled=is_current_room_running,
                    use_container_width=True
                ):
                    _trigger_agent_task(
                        effective_ws_id, selected_room,
                        "방금 작성한 검토 결과를 바탕으로, 거래처에 발송할 정식 비즈니스 이메일 회신 초안(제목, 인사말, 핵심 검토 결과 요약, 실무 유의사항, 맺음말 포함)을 깔끔하게 작성해 줘.",
                        pro_toggle_on, False, force_flash=True
                    )
            with act3:
                if st.button(
                    "🧠 [프로] 3배 개방 재검토",
                    key=f"repro_{effective_ws_id}_{selected_room}_{idx}",
                    disabled=is_current_room_running,
                    use_container_width=True
                ):
                    _trigger_agent_task(
                        effective_ws_id, selected_room,
                        "[프로] 직전 질문 사안에 대해 관련 법령·시행령·판례·심판례·예규와 예외 요건까지 데이터·도구 한도를 3배 개방하여 심층 재검토해 줘.",
                        pro_toggle_on, False, force_flash=False
                    )

            with st.expander("📋 카톡·이메일 전송용 텍스트 원클릭 복사 (우측 상단 복사 아이콘 클릭)"):
                st.code(_extract_clean_copy_text(message["content"]), language="markdown")

# ---------------------------------------------------------
# 5. 현재 방에서 백그라운드 작업이 진행 중일 때 실시간 상태창 표시 (유령 잔상 방지)
# ---------------------------------------------------------
status_placeholder = st.empty()
if active_task and active_task.get("status") == "running":
    is_pro_running = active_task.get("is_pro", False)
    status_title = (
        f"🧠 [{selected_room}] Pro 심층 모드 백그라운드 가동 중 (데이터·도구 한도 3배 개방)..."
        if is_pro_running else
        f"⚡ [{selected_room}] 실시간 법령·공시 DB 조회 및 백그라운드 정밀 검토 중..."
    )
    with status_placeholder.container():
        with st.chat_message("assistant"):
            with st.status(status_title, expanded=True):
                st.write("🔎 **1단계:** 질의 쟁점 분석 및 7대 국가·공공기관(법제처 현행·구법·국세청·DART·국토부·한은) DB 탐색 중...")
                st.write("🧮 **2단계:** 관련 법령·판례 원문 파싱 및 파이썬 1원 단위 정밀 수리 계산기 구동 중...")
                st.write("🛡️ **3단계:** 미조회 근거 강제 차단(`_scan_violations`) 및 듀얼 AI 의미 감수(`_semantic_verify`) 수행 중...")
                st.caption("💡 **백그라운드 멀티태스킹 작동 중:** 지금 좌측 대화방 리스트를 눌러 다른 대화방으로 이동하셔도 이 방의 AI 검토는 멈추지 않고 끝까지 완료됩니다.")

# ---------------------------------------------------------
# 6. 메인 화면 최하단 고정: Gemini 스타일 올인원 통합 채팅 입력창 (드래그 앤 드롭 파일 첨부 통합)
# ---------------------------------------------------------
room_file_entry = _normalize_room_file_entry(st.session_state.room_files[selected_room])
st.session_state.room_files[selected_room] = room_file_entry
saved_items = room_file_entry["items"]
reset_cnt = st.session_state.get(f"reset_cnt_{selected_room}", 0)

# 이미 대화방에 첨부되어 유지 중인 파일이 있으면 하단 입력창 바로 위에 슬림한 칩 형태로 표시
if saved_items:
    with st.container(border=True):
        c_head1, c_head2 = st.columns([8.5, 1.5])
        with c_head1:
            chips_str = " &nbsp;|&nbsp; ".join(
                f"📄 **{it['name']}** *({len(it['text']):,}자)*" for it in saved_items
            )
            st.markdown(
                f"<div style='font-size:0.88rem; color:#15803d;'>📎 <b>현재 [{selected_room}] 첨부 유지 중 ({len(saved_items)}건):</b> {chips_str}</div>",
                unsafe_allow_html=True
            )
        with c_head2:
            if st.button("🗑️ 첨부 비우기", key=f"clear_all_f_{selected_room}", use_container_width=True):
                st.session_state.room_files[selected_room] = {"name": None, "text": "", "items": []}
                st.session_state[f"reset_cnt_{selected_room}"] = reset_cnt + 1
                save_workspace_to_disk(effective_ws_id)
                st.rerun()

chat_input_placeholder = (
    f"⏳ [{selected_room}] 현재 백그라운드 정밀 검토 진행 중입니다... (좌측 다른 대화방을 클릭해 추가 질문을 하실 수 있습니다)"
    if is_current_room_running else
    f"[{selected_room}] 검토할 이슈를 입력하거나 이 칸에 파일(엑셀·PDF·워드·사진)을 바로 끌어다 놓으세요 (+ 버튼 첨부 가능)"
)

# ⚠️ 중요: st.chat_input을 st.container() 밖(최상위 루트)에 단독 호출해야 화면 맨 아래(Bottom)에 고정됩니다!
_chat_sig = inspect.signature(st.chat_input).parameters
try:
    if "accept_file" in _chat_sig:
        chat_val = st.chat_input(
            placeholder=chat_input_placeholder,
            disabled=is_current_room_running,
            accept_file="multiple",
            file_type=["xlsx", "xls", "csv", "pdf", "docx", "png", "jpg", "jpeg"],
            key=f"chat_input_{effective_ws_id}_{selected_room}"
        )
    else:
        chat_val = st.chat_input(
            placeholder=chat_input_placeholder,
            disabled=is_current_room_running,
            key=f"chat_input_{effective_ws_id}_{selected_room}"
        )
except Exception:
    chat_val = st.chat_input(
        placeholder=chat_input_placeholder,
        disabled=is_current_room_running,
        key=f"chat_input_{effective_ws_id}_{selected_room}"
    )

if chat_val:
    if isinstance(chat_val, str):
        user_prompt_text = chat_val
        inline_files = []
    else:
        user_prompt_text = getattr(chat_val, "text", "") or ""
        inline_files = list(getattr(chat_val, "files", []) or [])

    if inline_files:
        existing_names = {it["name"] for it in saved_items}
        for uf in inline_files:
            if uf.name not in existing_names:
                with st.spinner(f"📄 '{uf.name}' 내용 추출 및 저장 중..."):
                    extracted_text = extract_file_content(uf, room_key=active_room_key)
                    saved_items.append({"name": uf.name, "text": extracted_text})
                    existing_names.add(uf.name)
        st.session_state.room_files[selected_room] = _normalize_room_file_entry({"items": saved_items})
        save_workspace_to_disk(effective_ws_id)

    if user_prompt_text.strip():
        _trigger_agent_task(
            effective_ws_id=effective_ws_id,
            selected_room=selected_room,
            raw_prompt=user_prompt_text,
            pro_toggle_on=pro_toggle_on,
            budget_exceeded=False,
            force_flash=False
        )
    elif inline_files:
        st.rerun()

# 백그라운드 작업 폴링 (하단 입력창까지 모두 렌더링한 뒤 깔끔하게 대기 후 완료 시 즉시 갱신)
if active_task and active_task.get("status") == "running":
    while active_task.get("status") == "running":
        time.sleep(0.4)
    status_placeholder.empty()
    ans = active_task.get("response", "")
    if ans and (not current_messages or current_messages[-1].get("role") != "assistant" or current_messages[-1].get("content") != ans):
        current_messages.append({"role": "assistant", "content": ans})
    task_mgr["tasks"].pop(current_task_key, None)
    save_workspace_to_disk(effective_ws_id)
    st.rerun()
