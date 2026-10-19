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
    default_titles["대화방 1"] = "메인 검토"
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
        # 원클릭으로 작업공간 코드를 풀고 공용 모드로 나가는 심플 버튼!
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
    
    # 🗑️ 3) 비우기 버튼 설계 (현재 방 단일 비우기 vs 10개 방 초기화 / 작업공간 완전 파기)
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
            # 서버에 저장된 이 작업공간 파일(.json) 자체를 완전 삭제하고 코드도 풀어버리는 버튼
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
if prompt := st.chat_input(f"[{selected_room}: {current_room_title}]에 검토할 이슈를 입력하세요"):
    has_attached_file = bool(current_file_info["name"] and current_file_info["text"])
    display_prompt = f"📎 **[첨부파일: {current_file_info['name']}]**\n\n{prompt}" if has_attached_file else prompt
    
    if st.session_state.room_titles[selected_room] in ["빈 대화방", "메인 검토"] and not current_messages:
        auto_title = prompt.strip().replace("\n", " ")[:12]
        st.session_state.room_titles[selected_room] = auto_title
        current_room_title = auto_title

    history_context = ""
    if current_messages:
        recent_msgs = current_messages[-6:]
        history_lines = ["[이 대화방의 직전 대화 맥락 (참고용)]"]
        for m in recent_msgs:
            role_label = "사용자" if m["role"] == "user" else "에이전트"
            history_lines.append(f"- {role_label}: {m['content'][:1500]}")
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
            
            new_idx = len(current_messages)
            col1, col2, col3 = st.columns(3)
            with col1:
                st.download_button(
                    label="📘 워드 다운로드 (.docx)",
                    data=create_word_docx(response),
                    file_name=f"검토보고서_{selected_room}_{current_room_title}_최신.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    key=f"docx_new_{effective_ws_id}_{selected_room}_{new_idx}",
                    use_container_width=True
                )
            with col2:
                st.download_button(
                    label="🖨️ 인쇄용 문서 (.html/PDF)",
                    data=create_printable_html(response),
                    file_name=f"검토보고서_{selected_room}_{current_room_title}_최신.html",
                    mime="text/html",
                    key=f"print_new_{effective_ws_id}_{selected_room}_{new_idx}",
                    use_container_width=True
                )
            with col3:
                st.download_button(
                    label="📝 마크다운 다운로드 (.md)",
                    data=response.encode("utf-8-sig"),
                    file_name=f"검토보고서_{selected_room}_{current_room_title}_최신.md",
                    mime="text/markdown",
                    key=f"md_new_{effective_ws_id}_{selected_room}_{new_idx}",
                    use_container_width=True
                )
            
    current_messages.append({"role": "assistant", "content": response})
    save_workspace_to_disk(effective_ws_id)
