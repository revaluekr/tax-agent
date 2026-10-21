import os
import io
import re
import json
import hashlib
import urllib.request
import streamlit as st
import pandas as pd
from pypdf import PdfReader
from docx import Document
from docx.shared import Pt
from docx.oxml.ns import qn

# PDF 직접 생성을 위한 ReportLab 모듈
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from agent import run_agent

# 1. 웹 페이지 기본 설정
st.set_page_config(
    page_title="세무·법령·회계 자율 에이전트",
    page_icon="⚖️",
    layout="wide"
)

# ---------------------------------------------------------
# 💎 프리미엄 오피스 커스텀 CSS 스킨 (폰트, 표, 헤더, 워터마크 숨김)
# ---------------------------------------------------------
st.markdown("""
<style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');

html, body, [class*="css"] {
    font-family: 'Pretendard', 'Malgun Gothic', 'Apple SD Gothic Neo', sans-serif;
}

/* 메인 타이틀 스타일 */
h1 {
    color: #0f172a !important;
    font-weight: 800 !important;
    letter-spacing: -0.5px;
    border-bottom: 2px solid #e2e8f0;
    padding-bottom: 12px !important;
    margin-bottom: 16px !important;
}

/* 보고서 대제목 (### 1. 결론, ### 2. 내용, ### 3. 관련법령) */
div[data-testid="stChatMessageContent"] h3 {
    color: #1e3a8a !important;
    background: linear-gradient(90deg, #f1f5f9 0%, #ffffff 100%);
    border-left: 5px solid #1e3a8a;
    padding: 8px 14px !important;
    border-radius: 0 6px 6px 0;
    margin-top: 22px !important;
    margin-bottom: 12px !important;
    font-size: 1.2rem !important;
    font-weight: 700 !important;
}

/* 보고서 소제목 (#### (1) 상세 법리 등) */
div[data-testid="stChatMessageContent"] h4 {
    color: #1e40af !important;
    margin-top: 16px !important;
    margin-bottom: 8px !important;
    font-size: 1.05rem !important;
    font-weight: 700 !important;
}

/* 마크다운 표(Table) 엔터프라이즈 네이비 스타일링 */
div[data-testid="stChatMessageContent"] table {
    width: 100%;
    border-collapse: collapse;
    margin: 14px 0 18px 0;
    font-size: 0.94rem;
    border-radius: 6px;
    overflow: hidden;
    box-shadow: 0 1px 3px rgba(0,0,0,0.05);
}
div[data-testid="stChatMessageContent"] th {
    background-color: #1e293b !important;
    color: #ffffff !important;
    font-weight: 600 !important;
    padding: 10px 12px !important;
    border: 1px solid #334155 !important;
    text-align: left !important;
}
div[data-testid="stChatMessageContent"] td {
    padding: 9px 12px !important;
    border: 1px solid #cbd5e1 !important;
    color: #1e293b;
    background-color: #ffffff;
}
div[data-testid="stChatMessageContent"] tr:nth-child(even) td {
    background-color: #f8fafc;
}

/* 상단 모드 안내 인용구 박스 (> ⚡ / > 🧠) */
div[data-testid="stChatMessageContent"] blockquote {
    background-color: #f8fafc;
    border-left: 4px solid #3b82f6;
    padding: 8px 14px;
    border-radius: 6px;
    color: #334155;
    font-size: 0.9rem;
    margin-bottom: 12px;
}

/* 다운로드 버튼 디자인 정돈 */
div.stDownloadButton > button {
    border-radius: 6px !important;
    border: 1px solid #cbd5e1 !important;
    font-weight: 600 !important;
    transition: all 0.15s ease-in-out !important;
}
div.stDownloadButton > button:hover {
    border-color: #1e3a8a !important;
    color: #1e3a8a !important;
    background-color: #f1f5f9 !important;
}

/* API 연동 상태 LED 카드 */
.api-led-box {
    background-color: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    padding: 10px 12px;
    font-size: 0.82rem;
    line-height: 1.75;
    color: #334155;
    box-shadow: 0 1px 2px rgba(0,0,0,0.03);
}

/* 불필요한 Streamlit 기본 푸터 숨김 */
footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------
# 0. 작업공간(Workspace)별 서버 자동 저장소 설정 및 키 체크
# ---------------------------------------------------------
ROOM_IDS = [f"대화방 {i}" for i in range(1, 11)]
STORAGE_DIR = ".workspace_storage"
os.makedirs(STORAGE_DIR, exist_ok=True)

def _check_api_configured(key_names: list[str]) -> bool:
    """환경변수 또는 st.secrets에 해당 API 키가 설정되어 있는지 확인합니다."""
    for k in key_names:
        try:
            if hasattr(st, "secrets") and k in st.secrets and str(st.secrets[k]).strip():
                return True
        except Exception:
            pass
        if os.getenv(k, "").strip():
            return True
    return False

def get_storage_path(workspace_id: str) -> str:
    """작업공간 ID(암호)를 해시 암호화하여 고유한 저장 파일 경로를 생성합니다."""
    safe_hash = hashlib.sha256(workspace_id.strip().encode("utf-8")).hexdigest()[:16]
    return os.path.join(STORAGE_DIR, f"ws_{safe_hash}.json")

def get_default_workspace_data() -> dict:
    """깨끗한 초기 10개 방 데이터 구조를 생성합니다."""
    default_titles = {r_id: "빈 대화방" for r_id in ROOM_IDS}
    default_titles["대화방 1"] = "메인 대화"
    return {
        "chat_rooms": {r_id: [] for r_id in ROOM_IDS},
        "room_titles": default_titles,
        "room_files": {r_id: {"name": None, "text": ""} for r_id in ROOM_IDS}
    }

def load_workspace_from_disk(workspace_id: str) -> dict:
    """서버 디스크에서 해당 작업공간의 10개 방 데이터를 불러옵니다."""
    path = get_storage_path(workspace_id)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            default_data = get_default_workspace_data()
            for key in ["chat_rooms", "room_titles", "room_files"]:
                if key not in data:
                    data[key] = default_data[key]
                else:
                    for r_id in ROOM_IDS:
                        if r_id not in data[key]:
                            data[key][r_id] = default_data[key][r_id]
            return data
        except Exception:
            pass
    return get_default_workspace_data()

def save_workspace_to_disk(workspace_id: str):
    """현재 세션의 10개 방 대화·제목·첨부파일 텍스트를 서버 디스크에 즉시 자동 저장합니다."""
    if not workspace_id:
        return
    path = get_storage_path(workspace_id)
    data = {
        "chat_rooms": st.session_state.chat_rooms,
        "room_titles": st.session_state.room_titles,
        "room_files": st.session_state.room_files
    }
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ 자동 저장 오류: {e}")

def delete_workspace_from_disk(workspace_id: str):
    """서버 디스크에서 해당 작업공간의 저장 파일(.json)을 영구 삭제합니다."""
    if not workspace_id or workspace_id == "default_public":
        return
    path = get_storage_path(workspace_id)
    if os.path.exists(path):
        try:
            os.remove(path)
        except Exception as e:
            print(f"⚠️ 파일 삭제 오류: {e}")

# ---------------------------------------------------------
# 헬퍼 함수 1: 업로드된 파일(Excel, PDF, Word) 텍스트 추출 (Pro 3배 한도: 150,000자)
# ---------------------------------------------------------
MAX_DOC_CHARS_STANDARD = 50000
MAX_DOC_CHARS_PRO      = 150000

def extract_file_content(uploaded_file) -> str:
    """업로드된 엑셀, CSV, PDF, 워드(.docx) 파일에서 최대 150,000자(Pro 3배 한도)까지 텍스트와 표를 추출합니다."""
    filename = uploaded_file.name.lower()
    try:
        if filename.endswith((".xlsx", ".xls")):
            excel_file = pd.ExcelFile(uploaded_file)
            text_parts = [f"[첨부 엑셀 파일명: {uploaded_file.name}]"]
            for sheet in excel_file.sheet_names:
                df = excel_file.parse(sheet)
                text_parts.append(f"\n--- 시트명: {sheet} (총 {len(df)}행) ---")
                text_parts.append(df.head(1500).to_string(index=False))
            return "\n".join(text_parts)[:MAX_DOC_CHARS_PRO]

        elif filename.endswith(".csv"):
            for enc in ["utf-8-sig", "utf-8", "cp949", "euc-kr"]:
                try:
                    uploaded_file.seek(0)
                    df = pd.read_csv(uploaded_file, encoding=enc)
                    return (f"[첨부 CSV 파일명: {uploaded_file.name} (총 {len(df)}행)]\n" + df.head(1500).to_string(index=False))[:MAX_DOC_CHARS_PRO]
                except Exception:
                    continue
            return "❌ CSV 파일의 한글 인코딩을 읽을 수 없습니다. 엑셀(.xlsx)로 저장 후 다시 올려주세요."

        elif filename.endswith(".pdf"):
            reader = PdfReader(uploaded_file)
            text_parts = [f"[첨부 PDF 파일명: {uploaded_file.name} (총 {len(reader.pages)}페이지)]"]
            for idx, page in enumerate(reader.pages[:150]):
                page_text = page.extract_text() or ""
                text_parts.append(f"\n--- {idx+1}페이지 ---\n{page_text}")
            return "\n".join(text_parts)[:MAX_DOC_CHARS_PRO]

        elif filename.endswith(".docx"):
            doc = Document(uploaded_file)
            text_parts = [f"[첨부 워드 파일명: {uploaded_file.name}]"]
            
            for p in doc.paragraphs:
                if p.text.strip():
                    text_parts.append(p.text.strip())
                    
            if doc.tables:
                text_parts.append("\n--- [워드 문서 내 표(Table) 데이터] ---")
                for t_idx, table in enumerate(doc.tables):
                    text_parts.append(f"\n[표 {t_idx+1}]")
                    for row in table.rows:
                        row_cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
                        text_parts.append(" | ".join(row_cells))
                        
            return "\n".join(text_parts)[:MAX_DOC_CHARS_PRO]

        return "지원하지 않는 파일 형식입니다."
    except Exception as e:
        return f"❌ 파일 읽기 오류: {e}"

# ---------------------------------------------------------
# 공통 정제 도우미: LaTeX 수식 기호 정제 및 클립보드 복사용 순수 본문 추출
# ---------------------------------------------------------
def _sanitize_math_text(text: str) -> str:
    if not text:
        return ""
    s = text
    s = re.sub(r"\$\$(.*?)\$\$", r"\1", s, flags=re.DOTALL)
    s = re.sub(r"\$([^$\n]+)\$", r"\1", s)
    s = re.sub(r"\\text(?:bf|rm|it)?\{([^}]*)\}", r"\1", s)
    s = re.sub(r"\\frac\{([^}]*)\}\{([^}]*)\}", r"(\1/\2)", s)
    s = s.replace(r"\times", " × ").replace(r"\div", " ÷ ").replace(r"\cdot", "·")
    s = s.replace(r"\%", "%").replace(r"\_", "_").replace(r"\,", ",")
    s = re.sub(r"\\(left|right|quad|qquad|mathrm|mathbf)\b", "", s)
    return s

def _extract_clean_copy_text(report_text: str) -> str:
    """클립보드 원클릭 복사용: 상단 시스템 배지(> ⚡ 등)를 제외하고 카톡/이메일/문서에 바로 붙여넣기 좋은 텍스트를 반환합니다."""
    cleaned = _sanitize_math_text(report_text)
    out_lines = []
    for line in cleaned.split("\n"):
        if line.strip().startswith(">"):
            continue
        out_lines.append(line)
    return "\n".join(out_lines).strip()

# ---------------------------------------------------------
# 헬퍼 함수 2: AI 답변을 워드(.docx)로 변환 (상단 타이틀 없이 본문부터 깔끔하게 출력)
# ---------------------------------------------------------
def _set_malgun_font(run):
    run.font.name = "Malgun Gothic"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "Malgun Gothic")

def create_word_docx(report_text: str) -> bytes:
    """마크다운 형식의 보고서 텍스트와 표를 한글 폰트(맑은 고딕)가 적용된 워드(.docx) 문서로 변환합니다."""
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
# 헬퍼 함수 3: 정식 PDF 직접 생성 엔진 (상단 타이틀/검토안건/작성일자 제거, 1. 결론부터 조판)
# ---------------------------------------------------------
def _ensure_korean_font() -> tuple[str, str]:
    """서버 환경(Linux/Windows/Mac)에 한글 폰트를 자동 준비·등록하고 (일반폰트명, 굵은폰트명)을 반환합니다."""
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
    """TTF 기본 폰트에서 네모(□)로 깨질 수 있는 컬러 이모지만 깔끔하게 제거합니다."""
    return re.sub(r"[\U00010000-\U0010ffff]", "", text or "")

def _md_to_rl_xml(text: str, bold_font: str) -> str:
    """마크다운 인라인 문법(**굵게**, `코드`)을 ReportLab Paragraph용 XML 태그로 안전하게 변환합니다."""
    s = _strip_emojis_for_pdf(text).strip()
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    s = re.sub(r"\*\*(.+?)\*\*", rf'<font name="{bold_font}">\1</font>', s)
    s = re.sub(r"`([^`]+)`", r'<font backColor="#f1f5f9">\1</font>', s)
    return s

def _draw_page_footer(canvas, doc):
    """PDF 하단 페이지 번호(- 1 -)만 깔끔하게 출력합니다."""
    canvas.saveState()
    reg_font, _ = _ensure_korean_font()
    canvas.setFont(reg_font, 8.5)
    canvas.setFillColor(colors.HexColor("#64748b"))
    page_num_str = f"- {doc.page} -"
    canvas.drawCentredString(A4[0] / 2.0, 25, page_num_str)
    canvas.restoreState()

def create_pdf_report(report_text: str) -> bytes:
    """상단 타이틀·검토안건·작성일자 없이 '1. 결론 -> 2. 내용 -> 3. 관련법령' 본문을 즉시 깔끔한 PDF로 조판합니다."""
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
        bottomMargin=42
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
# 2. 왼쪽 사이드바 제어판 (Pro 토글 스위치 + 7대 기관 LED 상태창 장착)
# ---------------------------------------------------------
with st.sidebar:
    st.title("⚙️ 에이전트 제어판")
    
    # 🎛️ 1) Pro 심층 모드(3배 리미트 해제) 원클릭 토글 스위치
    st.subheader("🚀 엔진 출력 모드 제어")
    pro_toggle_on = st.toggle(
        "🧠 Pro 심층 모드 (3배 리미트 해제)",
        value=st.session_state.get("pro_toggle_state", False),
        help="켜두면 질문 앞에 [프로]를 직접 입력하지 않아도 자동으로 Pro 모델 가동 및 법령·판례·첨부파일 한도가 3배로 전면 개방됩니다."
    )
    st.session_state.pro_toggle_state = pro_toggle_on
    if pro_toggle_on:
        st.info("🔥 **Pro 3배 리미트 개방 ON:** 모든 질의에 대해 최대 15만 자 문서 독해 및 30회 도구 호출이 작동합니다.")
    else:
        st.caption("⚡ **Flash 표준 모드 작동 중:** 빠르고 경제적인 표준 모드로 응답합니다. (대용량 파일 첨부 시 자동 Pro 전환)")

    st.divider()

    # 🔐 2) 내 작업공간 (자동 동기화)
    st.subheader("🔐 내 작업공간 (자동 동기화)")
    
    ws_widget_ver = st.session_state.get("ws_widget_ver", 0)
    workspace_input = st.text_input(
        "작업공간 코드(ID/암호) 입력",
        value=st.session_state.get("active_workspace_id", ""),
        type="password",
        placeholder="나만의 코드 입력 후 Enter (예: kbj1234)",
        key=f"ws_input_box_{ws_widget_ver}",
        help="창을 닫거나 다른 PC에서 접속해도 동일한 코드를 입력하면 1~10번 방의 대화와 첨부파일이 그대로 유지됩니다."
    )
    
    effective_ws_id = workspace_input.strip() if workspace_input.strip() else "default_public"
    
    if st.session_state.get("loaded_workspace_id") != effective_ws_id:
        ws_data = load_workspace_from_disk(effective_ws_id)
        st.session_state.chat_rooms = ws_data["chat_rooms"]
        st.session_state.room_titles = ws_data["room_titles"]
        st.session_state.room_files = ws_data["room_files"]
        st.session_state.loaded_workspace_id = effective_ws_id
        st.session_state.active_workspace_id = workspace_input.strip()
        if "current_room" not in st.session_state:
            st.session_state.current_room = ROOM_IDS[0]

    if workspace_input.strip():
        st.success("🟢 전용 작업공간 실시간 자동 저장 중")
        if st.button("🔒 코드 풀기 (잠금 / 나가기)", use_container_width=True):
            st.session_state.active_workspace_id = ""
            st.session_state.loaded_workspace_id = None
            st.session_state.ws_widget_ver = ws_widget_ver + 1
            st.rerun()
    else:
        st.warning("🔓 공용 임시 모드입니다. 상단에 나만의 작업공간 코드를 입력하면 대화가 안전하게 분리·보존됩니다.")

    st.divider()
    
    # 🗂️ 3) 멀티 대화방 선택 (1~10번)
    st.subheader("🗂️ 멀티 대화방 선택 (1~10번)")
    
    def format_room_label(r_id: str) -> str:
        title = st.session_state.room_titles.get(r_id, "")
        q_cnt = len(st.session_state.chat_rooms[r_id]) // 2
        file_mark = "📎" if st.session_state.room_files[r_id]["name"] else ""
        return f"💬 {r_id} [{title}] ({q_cnt}건) {file_mark}"

    selected_room = st.selectbox(
        "진행 중인 프로젝트별로 방을 나누어 관리하세요.",
        options=ROOM_IDS,
        index=ROOM_IDS.index(st.session_state.current_room),
        format_func=format_room_label
    )
    st.session_state.current_room = selected_room
    
    new_title = st.text_input(
        "✏️ 현재 대화방 주제(메모) 설정",
        value=st.session_state.room_titles[selected_room],
        placeholder="예: 인도네시아 자문, A사 세무조사 등",
        key=f"title_input_{effective_ws_id}_{selected_room}"
    )
    if new_title != st.session_state.room_titles[selected_room]:
        st.session_state.room_titles[selected_room] = new_title
        save_workspace_to_disk(effective_ws_id)
        st.rerun()
    
    if st.button(f"🗑️ [{selected_room}] 현재 방만 비우기", use_container_width=True):
        st.session_state.chat_rooms[selected_room] = []
        st.session_state.room_files[selected_room] = {"name": None, "text": ""}
        st.session_state.room_titles[selected_room] = "빈 대화방"
        st.session_state[f"reset_cnt_{selected_room}"] = st.session_state.get(f"reset_cnt_{selected_room}", 0) + 1
        save_workspace_to_disk(effective_ws_id)
        st.rerun()

    with st.expander("⚠️ 10개 방 전체 초기화 / 작업공간 파기"):
        unlock_all_reset = st.checkbox("실수 방지: 전체 삭제·파기에 동의합니다", key="unlock_reset")
        
        col_r1, col_r2 = st.columns(2)
        with col_r1:
            if st.button("🔄 10개 방 비우기", disabled=not unlock_all_reset, use_container_width=True):
                fresh_data = get_default_workspace_data()
                st.session_state.chat_rooms = fresh_data["chat_rooms"]
                st.session_state.room_titles = fresh_data["room_titles"]
                st.session_state.room_files = fresh_data["room_files"]
                for r_id in ROOM_IDS:
                    st.session_state[f"reset_cnt_{r_id}"] = st.session_state.get(f"reset_cnt_{r_id}", 0) + 1
                save_workspace_to_disk(effective_ws_id)
                st.rerun()
        with col_r2:
            if st.button("🔥 작업공간 파기", disabled=(not unlock_all_reset or not workspace_input.strip()), use_container_width=True):
                delete_workspace_from_disk(effective_ws_id)
                st.session_state.active_workspace_id = ""
                st.session_state.loaded_workspace_id = None
                st.session_state.ws_widget_ver = ws_widget_ver + 1
                st.rerun()
            
        st.caption("💾 서버 재부팅 대비 내 PC로 전체 대화 백업/복원:")
        backup_json_bytes = json.dumps({
            "chat_rooms": st.session_state.chat_rooms,
            "room_titles": st.session_state.room_titles,
            "room_files": st.session_state.room_files
        }, ensure_ascii=False, indent=2).encode("utf-8")
        
        st.download_button(
            label="📥 10개 방 통째로 내 PC에 백업 (.json)",
            data=backup_json_bytes,
            file_name="세무에이전트_전체백업.json",
            mime="application/json",
            use_container_width=True
        )
        
        restored_file = st.file_uploader("📤 백업 파일(.json) 불러오기", type=["json"], key="restore_uploader")
        if restored_file is not None:
            if st.button("✅ 이 백업 파일로 10개 방 복원하기", use_container_width=True):
                try:
                    loaded_backup = json.loads(restored_file.read().decode("utf-8"))
                    st.session_state.chat_rooms = loaded_backup["chat_rooms"]
                    st.session_state.room_titles = loaded_backup["room_titles"]
                    st.session_state.room_files = loaded_backup["room_files"]
                    save_workspace_to_disk(effective_ws_id)
                    st.success("복원 완료!")
                    st.rerun()
                except Exception as e:
                    st.error(f"복원 실패: {e}")
        
    st.divider()
    
    # 📂 4) 방별 전용 자료 업로드
    st.subheader(f"📂 [{selected_room}] 전용 자료 업로드")
    reset_cnt = st.session_state.get(f"reset_cnt_{selected_room}", 0)
    uploaded_file = st.file_uploader(
        "엑셀, PDF, 워드 파일을 올리면 이 방에 자동 보존됩니다. (15,000자 이상 대용량 문서는 자동으로 Pro 3배 개방 모드가 작동합니다)",
        type=["xlsx", "xls", "csv", "pdf", "docx"],
        key=f"uploader_{effective_ws_id}_{selected_room}_{reset_cnt}"
    )
    
    if uploaded_file is not None:
        if st.session_state.room_files[selected_room]["name"] != uploaded_file.name:
            with st.spinner("문서 내용을 읽고 작업공간에 자동 저장하는 중..."):
                extracted_text = extract_file_content(uploaded_file)
                st.session_state.room_files[selected_room] = {
                    "name": uploaded_file.name,
                    "text": extracted_text
                }
                save_workspace_to_disk(effective_ws_id)
                st.rerun()
                
    saved_file_name = st.session_state.room_files[selected_room]["name"]
    saved_file_text = st.session_state.room_files[selected_room]["text"]
    
    if saved_file_name:
        pro_file_tag = " 🧠 [Pro 자동 전환 대상]" if len(saved_file_text) >= 15000 else ""
        st.success(f"📎 현재 유지 중인 파일: **{saved_file_name}** ({len(saved_file_text):,}자){pro_file_tag}")
        if st.button("❌ 이 방의 첨부파일만 제거", key=f"remove_file_{selected_room}", use_container_width=True):
            st.session_state.room_files[selected_room] = {"name": None, "text": ""}
            st.session_state[f"reset_cnt_{selected_room}"] = reset_cnt + 1
            save_workspace_to_disk(effective_ws_id)
            st.rerun()
        with st.expander("📄 저장된 파일 내용 미리보기"):
            st.text(saved_file_text[:1000] + ("\n...(중략)..." if len(saved_file_text) > 1000 else ""))

    st.divider()

    # 📊 5) 사이드바 하단: 7대 국가·공공기관 API 실시간 연동 상태 그린 라이트(LED) 패널
    st.subheader("📡 7대 기관 DB 실시간 연동 상태")
    led_law   = "🟢" if _check_api_configured(["LAW_API_OC", "OC"]) else "🟡"
    led_nts   = "🟢" if _check_api_configured(["NTS_API_KEY", "DATA_GO_KR_KEY", "PUBLIC_DATA_KEY"]) else "🟡"
    led_dart  = "🟢" if _check_api_configured(["DART_API_KEY", "OPENDART_API_KEY"]) else "🟡"
    led_molit = "🟢" if _check_api_configured(["MOLIT_API_KEY", "DATA_GO_KR_KEY", "VWORLD_API_KEY"]) else "🟡"
    led_bok   = "🟢" if _check_api_configured(["BOK_API_KEY", "ECOS_API_KEY"]) else "🟡"
    led_ind   = "🟢" if os.path.exists("industry_codes.xlsx") else "🟡"

    st.markdown(f"""
    <div class="api-led-box">
        <div>{led_law} <b>법제처 국가법령·판례·심판례 DRF</b></div>
        <div>{led_nts} <b>국세청 사업자 상태·진위확인 API</b></div>
        <div>{led_dart} <b>금융감독원 전자공시(Open DART)</b></div>
        <div>{led_molit} <b>국토부 실거래가 · 브이월드 공시지가</b></div>
        <div>{led_bok} <b>한국은행 경제통계(ECOS) 환율·금리</b></div>
        <div>{led_ind} <b>국세청 6자리 기준경비율 업종 마스터</b></div>
        <div>🟢 <b>Python 1원 단위 정밀 수리 계산 엔진</b></div>
    </div>
    """, unsafe_allow_html=True)

# ---------------------------------------------------------
# 3. 메인 화면 및 현재 선택된 대화방 렌더링
# ---------------------------------------------------------
current_messages = st.session_state.chat_rooms[selected_room]
current_room_title = st.session_state.room_titles[selected_room]
current_file_info = st.session_state.room_files[selected_room]

mode_status_str = "🧠 **Pro 심층 모드 (3배 리미트 개방 ON)**" if pro_toggle_on else "⚡ **Flash 표준 모드 (고속 검토)**"
st.title(f"⚖️ 세무·법령·회계 자율 에이전트 — [{selected_room}: {current_room_title}]")
st.markdown(
    f"💡 **현재 엔진 상태:** {mode_status_str} &nbsp;|&nbsp; 좌측 사이드바의 **토글 스위치**를 켜거나 질문 맨 앞에 **`[프로]`**를 입력하면 데이터·도구 한도가 3배로 확장됩니다."
)

for idx, message in enumerate(current_messages):
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message["role"] == "assistant":
            col1, col2, col3 = st.columns(3)
            with col1:
                st.download_button(
                    label="📕 정식 PDF 보고서 다운로드 (.pdf)",
                    data=create_pdf_report(message["content"]),
                    file_name=f"검토보고서_{selected_room}_{current_room_title}_{idx}.pdf",
                    mime="application/pdf",
                    key=f"pdf_{effective_ws_id}_{selected_room}_{idx}",
                    use_container_width=True
                )
            with col2:
                st.download_button(
                    label="📘 워드 다운로드 (.docx)",
                    data=create_word_docx(message["content"]),
                    file_name=f"검토보고서_{selected_room}_{current_room_title}_{idx}.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    key=f"docx_{effective_ws_id}_{selected_room}_{idx}",
                    use_container_width=True
                )
            with col3:
                st.download_button(
                    label="📝 마크다운 다운로드 (.md)",
                    data=message["content"].encode("utf-8-sig"),
                    file_name=f"검토보고서_{selected_room}_{current_room_title}_{idx}.md",
                    mime="text/markdown",
                    key=f"md_{effective_ws_id}_{selected_room}_{idx}",
                    use_container_width=True
                )
            # 📋 4) 카톡·이메일·문서 붙여넣기용 원클릭 클립보드 복사 블록
            with st.expander("📋 카톡·이메일 전송용 텍스트 원클릭 복사 (우측 상단 복사 아이콘 클릭)"):
                st.code(_extract_clean_copy_text(message["content"]), language="markdown")

# 4. 사용자 질문 입력 및 실시간 3단계 아코디언 상태창(st.status) 처리
if prompt := st.chat_input(
    placeholder=f"[{selected_room}] 검토할 이슈를 입력하세요 (좌측 Pro 토글 ON 또는 맨 앞에 [프로] 입력 시 3배 개방)",
    key=f"chat_input_{effective_ws_id}_{selected_room}"
):
    # 좌측 토글 스위치가 켜져 있으면 자동으로 질문 앞에 [프로] 태그 부착
    effective_prompt = prompt.strip()
    if pro_toggle_on and not effective_prompt.startswith("[프로]"):
        effective_prompt = f"[프로] {effective_prompt}"

    has_attached_file = bool(current_file_info["name"] and current_file_info["text"])
    display_prompt = f"📎 **[첨부파일: {current_file_info['name']}]**\n\n{effective_prompt}" if has_attached_file else effective_prompt
    
    if st.session_state.room_titles[selected_room] in ["빈 대화방", "메인 대화"] and not current_messages:
        auto_title = prompt.strip().replace("[프로]", "").strip().replace("\n", " ")[:12]
        st.session_state.room_titles[selected_room] = auto_title
        current_room_title = auto_title

    is_pro_request = effective_prompt.startswith("[프로]") or (has_attached_file and len(current_file_info["text"]) >= 15000)
    msg_char_cap = 24000 if is_pro_request else 8000

    history_context = ""
    if current_messages:
        recent_msgs = (current_messages[:2] + current_messages[-6:]) if len(current_messages) > 6 else current_messages
        history_lines = [
            "[이 대화방의 이전 대화 맥락 — 사용자가 별도 수식어 없이 후속 질문이나 조건 변경, 또는 '[프로] 다시 검토해 줘'라고 말하더라도 반드시 아래 직전 질문·답변의 사례 금액, 자산 정보, 계산 내역을 그대로 이어받아 답변할 것]"
        ]
        for m in recent_msgs:
            role_label = "사용자" if m["role"] == "user" else "에이전트"
            history_lines.append(f"- {role_label}: {m['content'][:msg_char_cap]}")
        history_context = "\n".join(history_lines) + "\n\n"

    current_messages.append({"role": "user", "content": display_prompt})
    save_workspace_to_disk(effective_ws_id)
    
    with st.chat_message("user"):
        st.markdown(display_prompt)

    if has_attached_file:
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

    status_title = (
        f"🧠 [{selected_room}] Pro 심층 모드 가동 중 (데이터·도구 한도 3배 개방)..."
        if is_pro_request else
        f"⚡ [{selected_room}] 실시간 법령·공시 DB 조회 및 정밀 검토 중..."
    )

    with st.chat_message("assistant"):
        with st.status(status_title, expanded=True) as status_box:
            st.write("🔎 **1단계:** 질의 쟁점 분석 및 7대 국가·공공기관(법제처·국세청·DART·국토부·한은) DB 탐색 중...")
            st.write("🧮 **2단계:** 관련 법령·판례 원문 파싱 및 파이썬 1원 단위 정밀 수리 계산기 구동 중...")
            st.write("🛡️ **3단계:** 미조회 근거 강제 차단(`_scan_violations`) 및 듀얼 AI 의미 감수(`_semantic_verify`) 수행 중...")
            response = run_agent(
                user_input=full_input_for_agent,
                raw_query=effective_prompt,
                has_file=has_attached_file
            )
            status_box.update(label="✅ 정밀 검토 및 무결성 감수 완료", state="complete", expanded=False)
        st.markdown(response)
            
    current_messages.append({"role": "assistant", "content": response})
    save_workspace_to_disk(effective_ws_id)
    st.rerun()
