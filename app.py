import io
import re
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
# 0. 멀티 대화방(10개 세션) 및 파일 캐시 메모리 초기화
# ---------------------------------------------------------
ROOM_IDS = [f"검토방 {i}" for i in range(1, 11)]

if "chat_rooms" not in st.session_state:
    st.session_state.chat_rooms = {r_id: [] for r_id in ROOM_IDS}

# 각 방의 사용자 지정 별명(메모) 저장용 (예: 검토방 1 -> 인도네시아 건)
if "room_titles" not in st.session_state:
    default_titles = {r_id: "빈 대화방" for r_id in ROOM_IDS}
    default_titles["검토방 1"] = "메인 검토"
    st.session_state.room_titles = default_titles

# 방 이동 시 첨부파일을 매번 다시 읽지 않도록 잡아주는 고속 캐시 메모리
if "room_files" not in st.session_state:
    st.session_state.room_files = {r_id: {"name": None, "text": ""} for r_id in ROOM_IDS}

if "current_room" not in st.session_state:
    st.session_state.current_room = ROOM_IDS[0]

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
# 헬퍼 함수 2: AI 답변을 워드(.docx)로 변환 (한글 폰트 깨짐 방지 적용)
# ---------------------------------------------------------
def create_word_docx(report_text: str) -> bytes:
    """마크다운 형식의 보고서 텍스트를 한글 폰트(맑은 고딕)가 적용된 워드(.docx) 문서로 변환합니다."""
    doc = Document()
    
    style = doc.styles["Normal"]
    style.font.name = "Malgun Gothic"
    style.font.size = Pt(10.5)
    style._element.rPr.rFonts.set(qn("w:eastAsia"), "Malgun Gothic")
    
    title = doc.add_heading("세무·법령·회계 전문 검토 보고서", level=0)
    for run in title.runs:
        run.font.name = "Malgun Gothic"
        run._element.rPr.rFonts.set(qn("w:eastAsia"), "Malgun Gothic")
    
    for line in report_text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        
        clean_line = re.sub(r"\*\*(.*?)\*\*", r"\1", stripped)
        
        if stripped.startswith("### ") or stripped.startswith("## "):
            heading_text = clean_line.replace("### ", "").replace("## ", "")
            h = doc.add_heading(heading_text, level=1)
            for run in h.runs:
                run.font.name = "Malgun Gothic"
                run._element.rPr.rFonts.set(qn("w:eastAsia"), "Malgun Gothic")
        elif stripped.startswith("- ") or stripped.startswith("* "):
            p = doc.add_paragraph(clean_line[2:], style="List Bullet")
            p.paragraph_format.space_after = Pt(4)
        else:
            p = doc.add_paragraph(clean_line)
            p.paragraph_format.space_after = Pt(6)
            
    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()

# ---------------------------------------------------------
# 헬퍼 함수 3: 한글 깨짐 없는 인쇄용 문서(.html / PDF 변환용) 생성
# ---------------------------------------------------------
def create_printable_html(report_text: str) -> bytes:
    """브라우저에서 열어 바로 인쇄하거나 PDF로 저장할 수 있는 UTF-8-SIG 인코딩 문서입니다."""
    html_body = report_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    html_body = re.sub(r"### (.*)", r"<h2>\1</h2>", html_body)
    html_body = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", html_body)
    html_body = html_body.replace("\n", "<br>\n")
    
    html_str = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title>세무·법령·회계 검토 보고서</title>
<style>
    body {{ font-family: 'Malgun Gothic', 'Apple SD Gothic Neo', 'NanumGothic', sans-serif; line-height: 1.7; color: #222; max-width: 850px; margin: 40px auto; padding: 20px; }}
    h1 {{ border-bottom: 2px solid #1f4e78; padding-bottom: 10px; color: #1f4e78; }}
    h2 {{ margin-top: 28px; color: #2e5cb8; border-left: 4px solid #2e5cb8; padding-left: 10px; }}
    .print-guide {{ background: #f0f4f8; padding: 12px 16px; border-radius: 8px; margin-bottom: 25px; font-size: 14px; }}
    @media print {{ .print-guide {{ display: none; }} body {{ margin: 0; }} }}
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
# 2. 왼쪽 사이드바 제어판 (10개 대화방 드롭다운 + 방 이름 메모 + 캐시 파일 업로더)
# ---------------------------------------------------------
with st.sidebar:
    st.title("⚙️ 에이전트 제어판")
    
    st.subheader("🗂️ 멀티 대화방 선택 (1~10번)")
    
    # 드롭다운 목록에 [방 번호 - 방 제목 (대화 건수)] 형태로 직관적으로 표시
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
    
    # 현재 선택된 방의 이름(메모)을 직접 수정할 수 있는 입력칸
    new_title = st.text_input(
        "✏️ 현재 대화방 주제(메모) 설정",
        value=st.session_state.room_titles[selected_room],
        placeholder="예: 인도네시아 자문, A사 세무조사 등",
        key=f"title_input_{selected_room}"
    )
    if new_title != st.session_state.room_titles[selected_room]:
        st.session_state.room_titles[selected_room] = new_title
        st.rerun()
    
    col_del1, col_del2 = st.columns(2)
    with col_del1:
        if st.button("🗑️ 현재 방 비우기", use_container_width=True):
            st.session_state.chat_rooms[selected_room] = []
            st.session_state.room_files[selected_room] = {"name": None, "text": ""}
            st.rerun()
    with col_del2:
        if st.button("🔄 10개 방 전체 초기화", use_container_width=True):
            st.session_state.chat_rooms = {r_id: [] for r_id in ROOM_IDS}
            st.session_state.room_files = {r_id: {"name": None, "text": ""} for r_id in ROOM_IDS}
            st.rerun()
        
    st.divider()
    
    # 📂 방별 독립 파일 업로드 (캐시 적용으로 방 전환 시 재로딩 지연 0초!)
    st.subheader(f"📂 [{selected_room}] 전용 자료 업로드")
    uploaded_file = st.file_uploader(
        "이 대화방에서만 사용할 엑셀, PDF, 워드 파일을 올려주세요.",
        type=["xlsx", "xls", "csv", "pdf", "docx"],
        key=f"uploader_{selected_room}"
    )
    
    if uploaded_file is not None:
        # 새로 올린 파일이거나 파일명이 바뀐 경우에만 텍스트 추출 수행 (캐싱)
        if st.session_state.room_files[selected_room]["name"] != uploaded_file.name:
            with st.spinner("문서 내용을 읽고 메모리에 캐싱하는 중..."):
                extracted_text = extract_file_content(uploaded_file)
                st.session_state.room_files[selected_room] = {
                    "name": uploaded_file.name,
                    "text": extracted_text
                }
        cached_name = st.session_state.room_files[selected_room]["name"]
        cached_text = st.session_state.room_files[selected_room]["text"]
        st.success(f"✅ '{cached_name}' 유지 중 ({len(cached_text):,}자)")
        with st.expander("📄 추출된 파일 내용 미리보기"):
            st.text(cached_text[:1000] + ("\n...(중략)..." if len(cached_text) > 1000 else ""))
    else:
        # 파일 업로더에서 X를 눌러 지운 경우 캐시도 비움
        st.session_state.room_files[selected_room] = {"name": None, "text": ""}

    st.divider()
    st.subheader("🤖 스마트 라우팅 & 방어벽")
    st.markdown("""
    - **⚡ Flash 모드 (기본)**: 일반 질의 및 중소형 문서 (토큰 절약)
    - **🧠 Pro 모드 (자동 전환)**:
      1. 15,000자 이상 대용량 문서 첨부 시
      2. 고난도 키워드 2개 이상 결합 시
      3. 질문에 **`[프로]`** 또는 **`[정밀검토]`** 입력 시
    """)

# ---------------------------------------------------------
# 3. 메인 화면 및 현재 선택된 대화방 렌더링
# ---------------------------------------------------------
current_messages = st.session_state.chat_rooms[selected_room]
current_room_title = st.session_state.room_titles[selected_room]
current_file_info = st.session_state.room_files[selected_room]

st.title(f"⚖️ 세무·법령·회계 자율 에이전트 — [{selected_room}: {current_room_title}]")
st.markdown("10개의 독립된 검토방에서 거래처·주제별로 대화를 누적 관리할 수 있습니다. *(⚠️ 주의: 브라우저 창을 완전히 닫거나 앱을 재부팅하면 임시 대화 내역은 초기화되므로 중요한 보고서는 하단 버튼으로 꼭 다운로드해 두세요!)*")

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
                    key=f"docx_{selected_room}_{idx}",
                    use_container_width=True
                )
            with col2:
                st.download_button(
                    label="🖨️ 인쇄용 문서 (.html/PDF)",
                    data=create_printable_html(message["content"]),
                    file_name=f"검토보고서_{selected_room}_{current_room_title}_{idx}.html",
                    mime="text/html",
                    key=f"print_{selected_room}_{idx}",
                    use_container_width=True
                )
            with col3:
                st.download_button(
                    label="📝 마크다운 다운로드 (.md)",
                    data=message["content"].encode("utf-8-sig"),
                    file_name=f"검토보고서_{selected_room}_{current_room_title}_{idx}.md",
                    mime="text/markdown",
                    key=f"md_{selected_room}_{idx}",
                    use_container_width=True
                )

# 4. 사용자 질문 입력 및 이전 대화 맥락(Context) + 첨부 파일 결합 처리
if prompt := st.chat_input(f"[{selected_room}: {current_room_title}]에 검토할 이슈를 입력하세요"):
    has_attached_file = bool(current_file_info["name"] and current_file_info["text"])
    display_prompt = f"📎 **[첨부파일: {current_file_info['name']}]**\n\n{prompt}" if has_attached_file else prompt
    
    # 첫 질문이고 방 제목이 기본값('빈 대화방')이면 첫 질문 앞 12글자로 방 제목을 자동 세팅해주는 센스 기능!
    if st.session_state.room_titles[selected_room] in ["빈 대화방", "메인 검토"] and not current_messages:
        auto_title = prompt.strip().replace("\n", " ")[:12]
        st.session_state.room_titles[selected_room] = auto_title
        current_room_title = auto_title

    # 현재 방의 직전 대화 맥락(최근 6개 메시지 = 3턴) 요약 추출
    history_context = ""
    if current_messages:
        recent_msgs = current_messages[-6:]
        history_lines = ["[이 대화방의 직전 대화 맥락 (참고용)]"]
        for m in recent_msgs:
            role_label = "사용자" if m["role"] == "user" else "에이전트"
            history_lines.append(f"- {role_label}: {m['content'][:1500]}")
        history_context = "\n".join(history_lines) + "\n\n"

    current_messages.append({"role": "user", "content": display_prompt})
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
            
            new_idx = len(current_messages)
            col1, col2, col3 = st.columns(3)
            with col1:
                st.download_button(
                    label="📘 워드 다운로드 (.docx)",
                    data=create_word_docx(response),
                    file_name=f"검토보고서_{selected_room}_{current_room_title}_최신.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    key=f"docx_new_{selected_room}_{new_idx}",
                    use_container_width=True
                )
            with col2:
                st.download_button(
                    label="🖨️ 인쇄용 문서 (.html/PDF)",
                    data=create_printable_html(response),
                    file_name=f"검토보고서_{selected_room}_{current_room_title}_최신.html",
                    mime="text/html",
                    key=f"print_new_{selected_room}_{new_idx}",
                    use_container_width=True
                )
            with col3:
                st.download_button(
                    label="📝 마크다운 다운로드 (.md)",
                    data=response.encode("utf-8-sig"),
                    file_name=f"검토보고서_{selected_room}_{current_room_title}_최신.md",
                    mime="text/markdown",
                    key=f"md_new_{selected_room}_{new_idx}",
                    use_container_width=True
                )
            
    current_messages.append({"role": "assistant", "content": response})
