import os
import io
import re
import json
import hashlib
import streamlit as st
import pandas as pd
from pypdf import PdfReader
from docx import Document
from docx.shared import Pt
from docx.oxml.ns import qn
from agent import run_agent

# 1. 웹 페이지 기본 설정
st.set_page_config(
    page_title="세무·법령·회계 자율 에이전트",
    page_icon="⚖️",
    layout="wide"
)

# ---------------------------------------------------------
# 0. 작업공간(Workspace)별 서버 자동 저장소 설정
# ---------------------------------------------------------
ROOM_IDS = [f"대화방 {i}" for i in range(1, 11)]
STORAGE_DIR = ".workspace_storage"
os.makedirs(STORAGE_DIR, exist_ok=True)

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
# 헬퍼 함수 1: 업로드된 파일(Excel, PDF, Word) 텍스트 추출 (대용량 50,000자 한도)
# ---------------------------------------------------------
MAX_DOC_CHARS = 50000

def extract_file_content(uploaded_file) -> str:
    """업로드된 엑셀, CSV, PDF, 워드(.docx) 파일에서 텍스트와 표 데이터를 추출합니다."""
    filename = uploaded_file.name.lower()
    try:
        if filename.endswith((".xlsx", ".xls")):
            excel_file = pd.ExcelFile(uploaded_file)
            text_parts = [f"[첨부 엑셀 파일명: {uploaded_file.name}]"]
            for sheet in excel_file.sheet_names:
                df = excel_file.parse(sheet)
                text_parts.append(f"\n--- 시트명: {sheet} (총 {len(df)}행) ---")
                text_parts.append(df.head(500).to_string(index=False))
            return "\n".join(text_parts)[:MAX_DOC_CHARS]

        elif filename.endswith(".csv"):
            for enc in ["utf-8-sig", "utf-8", "cp949", "euc-kr"]:
                try:
                    uploaded_file.seek(0)
                    df = pd.read_csv(uploaded_file, encoding=enc)
                    return (f"[첨부 CSV 파일명: {uploaded_file.name} (총 {len(df)}행)]\n" + df.head(500).to_string(index=False))[:MAX_DOC_CHARS]
                except Exception:
                    continue
            return "❌ CSV 파일의 한글 인코딩을 읽을 수 없습니다. 엑셀(.xlsx)로 저장 후 다시 올려주세요."

        elif filename.endswith(".pdf"):
            reader = PdfReader(uploaded_file)
            text_parts = [f"[첨부 PDF 파일명: {uploaded_file.name} (총 {len(reader.pages)}페이지)]"]
            for idx, page in enumerate(reader.pages[:50]):
                page_text = page.extract_text() or ""
                text_parts.append(f"\n--- {idx+1}페이지 ---\n{page_text}")
            return "\n".join(text_parts)[:MAX_DOC_CHARS]

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
                        
            return "\n".join(text_parts)[:MAX_DOC_CHARS]

        return "지원하지 않는 파일 형식입니다."
    except Exception as e:
        return f"❌ 파일 읽기 오류: {e}"

# ---------------------------------------------------------
# 공통 정제 도우미: 기존 대화 내역에 남아있는 LaTeX 수식 기호까지 깔끔하게 정리
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

# ---------------------------------------------------------
# 헬퍼 함수 2: AI 답변을 워드(.docx)로 변환 (한글 폰트 + 마크다운 표 변환 지원)
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
    
    title = doc.add_heading("세무·법령·회계 전문 검토 보고서", level=0)
    for run in title.runs:
        _set_malgun_font(run)
    
    lines = report_text.split("\n")
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped:
            i += 1
            continue

        # 마크다운 표(| ... |) 감지 및 워드 표(Table)로 변환
        if stripped.startswith("|") and stripped.endswith("|"):
            table_rows = []
            while i < len(lines):
                row_s = lines[i].strip()
                if not (row_s.startswith("|") and row_s.endswith("|")):
                    break
                # 구분선(|---|---|)은 건너뜀
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
        else:
            p = doc.add_paragraph(clean_line)
            p.paragraph_format.space_after = Pt(6)
        i += 1
            
    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()

# ---------------------------------------------------------
# 헬퍼 함수 3: 한글·표·수식 깨짐 없는 인쇄용 문서(.html / PDF 변환용) 생성
# ---------------------------------------------------------
def _format_inline_md(escaped_line: str) -> str:
    """HTML 이스케이프된 한 줄 텍스트에 굵게(**), 기울임(*), 인라인 코드(`) 서식을 적용합니다."""
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped_line)
    s = re.sub(r"\*(.+?)\*", r"<em>\1</em>", s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    return s

def create_printable_html(report_text: str) -> bytes:
    """마크다운 표, 소제목(####), 목록, 수식을 완벽한 HTML 태그로 변환하여 인쇄용 문서를 생성합니다."""
    cleaned_text = _sanitize_math_text(report_text)
    raw_lines = cleaned_text.split("\n")
    html_parts = []
    i = 0

    while i < len(raw_lines):
        line = raw_lines[i]
        stripped = line.strip()

        if not stripped:
            html_parts.append('<div style="height: 8px;"></div>')
            i += 1
            continue

        # 1) 구분선 (---)
        if re.match(r"^-{3,}$", stripped):
            html_parts.append("<hr>")
            i += 1
            continue

        # 2) 마크다운 표 (| ... |) 블록 감지 -> HTML <table> 변환
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
                # |---|---| 형태의 구분선은 건너뜀
                if re.match(r"^\|[\s\-:|]+\|$", r_str):
                    continue
                cells = [c.strip() for c in r_str.strip("|").split("|")]
                rows_data.append(cells)

            if rows_data:
                t_html = ['<table class="report-table">']
                # 첫 행은 헤더(th)
                t_html.append("<thead><tr>")
                for c in rows_data[0]:
                    esc_c = _format_inline_md(c.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
                    t_html.append(f"<th>{esc_c}</th>")
                t_html.append("</tr></thead>")
                # 나머지 행은 본문(td)
                if len(rows_data) > 1:
                    t_html.append("<tbody>")
                    for r in rows_data[1:]:
                        t_html.append("<tr>")
                        for c in r:
                            esc_c = _format_inline_md(c.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
                            t_html.append(f"<td>{esc_c}</td>")
                        t_html.append("</tr>")
                    t_html.append("</tbody>")
                t_html.append("</table>")
                html_parts.append("".join(t_html))
            continue

        # 일반 줄 HTML 이스케이프
        esc = stripped.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        # 3) 제목 (#### -> h3, ###/## -> h2, # -> h1 순서로 매칭해 '#' 찌꺼기 원천 방지)
        if stripped.startswith("#### "):
            html_parts.append(f"<h3>{_format_inline_md(esc[5:])}</h3>")
        elif stripped.startswith("### "):
            html_parts.append(f"<h2>{_format_inline_md(esc[4:])}</h2>")
        elif stripped.startswith("## "):
            html_parts.append(f"<h2>{_format_inline_md(esc[3:])}</h2>")
        elif stripped.startswith("# "):
            html_parts.append(f"<h2>{_format_inline_md(esc[2:])}</h2>")
        # 4) 상단 모드 배지 / 인용구 (> ...)
        elif stripped.startswith(">"):
            quote_body = _format_inline_md(re.sub(r"^&gt;\s*", "", esc))
            html_parts.append(f'<div class="quote-box">{quote_body}</div>')
        # 5) 불릿 및 번호 목록
        elif stripped.startswith(("- ", "* ")):
            indent_px = (len(line) - len(line.lstrip(" "))) * 10
            html_parts.append(f'<div class="list-item" style="margin-left: {indent_px}px;">• {_format_inline_md(esc[2:])}</div>')
        else:
            indent_px = (len(line) - len(line.lstrip(" "))) * 10
            html_parts.append(f'<div class="para-line" style="margin-left: {indent_px}px;">{_format_inline_md(esc)}</div>')

        i += 1

    html_body = "\n".join(html_parts)
    
    html_str = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title>세무·법령·회계 검토 보고서</title>
<style>
    body {{ font-family: 'Malgun Gothic', 'Apple SD Gothic Neo', 'NanumGothic', sans-serif; line-height: 1.75; color: #222; max-width: 880px; margin: 35px auto; padding: 20px; font-size: 14.5px; }}
    h1 {{ border-bottom: 2px solid #1f4e78; padding-bottom: 10px; color: #1f4e78; font-size: 23px; }}
    h2 {{ margin-top: 26px; margin-bottom: 10px; color: #1f4e78; border-left: 4px solid #2e5cb8; padding-left: 10px; font-size: 18px; }}
    h3 {{ margin-top: 18px; margin-bottom: 8px; color: #2e5cb8; font-size: 16px; }}
    hr {{ border: 0; border-top: 1px solid #d0d7de; margin: 20px 0; }}
    .quote-box {{ background: #f6f8fa; border-left: 4px solid #8c959f; padding: 6px 12px; margin: 6px 0; color: #57606a; font-size: 13px; border-radius: 4px; }}
    .list-item {{ margin: 4px 0; padding-left: 12px; text-indent: -12px; }}
    .para-line {{ margin: 5px 0; }}
    .report-table {{ width: 100%; border-collapse: collapse; margin: 14px 0 18px 0; font-size: 13.5px; }}
    .report-table th, .report-table td {{ border: 1px solid #cbd5e1; padding: 8px 10px; text-align: left; vertical-align: top; }}
    .report-table th {{ background-color: #f1f5f9; color: #1e293b; font-weight: bold; }}
    .report-table tr:nth-child(even) td {{ background-color: #f8fafc; }}
    code {{ background: #f1f5f9; padding: 2px 5px; border-radius: 4px; font-family: monospace; font-size: 13px; }}
    .print-guide {{ background: #f0f4f8; padding: 12px 16px; border-radius: 8px; margin-bottom: 25px; font-size: 14px; }}
    @media print {{ .print-guide {{ display: none; }} body {{ margin: 0; padding: 10px; }} }}
</style>
</head>
<body>
    <div class="print-guide">
        💡 <b>인쇄 및 PDF 저장 안내:</b> 우측 버튼을 누르거나 키보드에서 <b>Ctrl + P</b>를 누른 후 대상 프린터를 <b>'PDF로 저장'</b>으로 선택하면 한글 깨짐 없이 깔끔한 PDF로 저장됩니다.
        <button onclick="window.print()" style="margin-left:15px; padding:6px 14px; cursor:pointer; font-weight:bold;">🖨️ 인쇄 / PDF로 저장하기</button>
    </div>
    <h1>⚖️ 세무·법령·회계 전문 검토 보고서</h1>
    <div>{html_body}</div>
</body>
</html>"""
    return html_str.encode("utf-8-sig")

# ---------------------------------------------------------
# 2. 왼쪽 사이드바 제어판 (작업공간 원클릭 잠금 해제/파기 버튼 장착)
# ---------------------------------------------------------
with st.sidebar:
    st.title("⚙️ 에이전트 제어판")
    
    # 🔐 1) 작업공간 ID(암호) 입력창 및 원클릭 코드 풀기(잠금) 버튼
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
    
    # 작업공간 ID가 처음 입력되었거나 변경된 경우 디스크에서 해당 작업공간 데이터 즉시 로드
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
    
    # 🗂️ 2) 멀티 대화방 선택 (1~10번)
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
    
    # 현재 선택된 방의 이름(메모) 수정칸 (변경 즉시 디스크 자동 저장)
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
    
    # 🗑️ 3) 비우기 버튼 설계
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
    
    # 📂 4) 방별 독립 파일 업로드
    st.subheader(f"📂 [{selected_room}] 전용 자료 업로드")
    reset_cnt = st.session_state.get(f"reset_cnt_{selected_room}", 0)
    uploaded_file = st.file_uploader(
        "엑셀, PDF, 워드 파일을 올리면 이 방에 자동 보존됩니다.",
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
        st.success(f"📎 현재 유지 중인 파일: **{saved_file_name}** ({len(saved_file_text):,}자)")
        if st.button("❌ 이 방의 첨부파일만 제거", key=f"remove_file_{selected_room}", use_container_width=True):
            st.session_state.room_files[selected_room] = {"name": None, "text": ""}
            st.session_state[f"reset_cnt_{selected_room}"] = reset_cnt + 1
            save_workspace_to_disk(effective_ws_id)
            st.rerun()
        with st.expander("📄 저장된 파일 내용 미리보기"):
            st.text(saved_file_text[:1000] + ("\n...(중략)..." if len(saved_file_text) > 1000 else ""))

# ---------------------------------------------------------
# 3. 메인 화면 및 현재 선택된 대화방 렌더링
# ---------------------------------------------------------
current_messages = st.session_state.chat_rooms[selected_room]
current_room_title = st.session_state.room_titles[selected_room]
current_file_info = st.session_state.room_files[selected_room]

st.title(f"⚖️ 세무·법령·회계 자율 에이전트 — [{selected_room}: {current_room_title}]")
st.markdown("왼쪽 상단에 **나만의 작업공간 코드**를 입력해 두면, 브라우저를 닫거나 다른 PC에서 접속해도 **1~10번 방의 모든 대화와 첨부파일이 실시간 자동 복원**됩니다.")

for idx, message in enumerate(current_messages):
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message["role"] == "assistant":
            col1, col2, col3 = st.columns(3)
            with col1:
                st.download_button(
                    label="📘 워드 다운로드 (.docx)",
                    data=create_word_docx(message["content"]),
                    file_name=f"검토보고서_{selected_room}_{current_room_title}_{idx}.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    key=f"docx_{effective_ws_id}_{selected_room}_{idx}",
                    use_container_width=True
                )
            with col2:
                st.download_button(
                    label="🖨️ 인쇄용 문서 (.html/PDF)",
                    data=create_printable_html(message["content"]),
                    file_name=f"검토보고서_{selected_room}_{current_room_title}_{idx}.html",
                    mime="text/html",
                    key=f"print_{effective_ws_id}_{selected_room}_{idx}",
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

# 4. 사용자 질문 입력 및 실시간 자동 저장 처리
# ⚠️ 핵심 패치: placeholder에 동적으로 바뀌는 current_room_title을 넣으면 첫 질문 직후 위젯 ID가 바뀌어
# 두 번째 질문의 첫 엔터가 씹히는 스트림릿 버그가 발생하므로 고정 key와 고정 placeholder를 사용합니다.
if prompt := st.chat_input(
    placeholder=f"[{selected_room}] 검토할 세무·법령·회계 이슈를 입력하세요 (이전 대화 맥락이 자동으로 이어집니다)",
    key=f"chat_input_{effective_ws_id}_{selected_room}"
):
    has_attached_file = bool(current_file_info["name"] and current_file_info["text"])
    display_prompt = f"📎 **[첨부파일: {current_file_info['name']}]**\n\n{prompt}" if has_attached_file else prompt
    
    if st.session_state.room_titles[selected_room] in ["빈 대화방", "메인 대화"] and not current_messages:
        auto_title = prompt.strip().replace("\n", " ")[:12]
        st.session_state.room_titles[selected_room] = auto_title
        current_room_title = auto_title

    history_context = ""
    if current_messages:
        recent_msgs = current_messages[-6:]
        history_lines = [
            "[이 대화방의 직전 대화 맥락 — 사용자가 별도 수식어 없이 후속 질문이나 조건 변경만 말하더라도 반드시 아래 직전 질문·답변의 사례 금액, 토지/자산 정보, 계산 내역을 그대로 이어받아 답변할 것]"
        ]
        for m in recent_msgs:
            role_label = "사용자" if m["role"] == "user" else "에이전트"
            # 직전 답변의 표와 계산 내역이 잘리지 않도록 8,000자까지 넉넉히 전달
            history_lines.append(f"- {role_label}: {m['content'][:8000]}")
        history_context = "\n".join(history_lines) + "\n\n"

    current_messages.append({"role": "user", "content": display_prompt})
    save_workspace_to_disk(effective_ws_id)
    
    with st.chat_message("user"):
        st.markdown(display_prompt)

    if has_attached_file:
        full_input_for_agent = (
            f"{history_context}"
            f"[현재 사용자 질문]: {prompt}\n\n"
            f"아래는 사용자가 현재 대화방에 업로드한 첨부파일({current_file_info['name']})의 데이터입니다. "
            f"직전 대화 맥락과 이 파일 데이터를 바탕으로 관련 법령·예규·판례·환율을 정밀 대조하여 답변하세요:\n"
            f"========================================\n"
            f"{current_file_info['text']}\n"
            f"========================================"
        )
    else:
        full_input_for_agent = f"{history_context}[현재 사용자 질문]: {prompt}" if history_context else prompt

    with st.chat_message("assistant"):
        with st.spinner(f"🔍 [{selected_room}] 맥락 분석 및 3단계 크로스체크 중입니다..."):
            response = run_agent(
                user_input=full_input_for_agent,
                raw_query=prompt,
                has_file=has_attached_file
            )
            st.markdown(response)
            
    current_messages.append({"role": "assistant", "content": response})
    save_workspace_to_disk(effective_ws_id)
    # 답변 저장 직후 즉시 화면 상태를 확정하여 다음 질문 첫 엔터가 씹히지 않도록 보장
    st.rerun()
