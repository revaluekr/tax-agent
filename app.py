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
# 헬퍼 함수 1: 업로드된 파일(Excel, PDF, Word) 텍스트 추출 (한글 깨짐 방지)
# ---------------------------------------------------------
def extract_file_content(uploaded_file) -> str:
    """업로드된 엑셀, CSV, PDF, 워드(.docx) 파일에서 텍스트와 표 데이터를 추출합니다."""
    filename = uploaded_file.name.lower()
    try:
        # 1) 엑셀 파일 (.xlsx, .xls)
        if filename.endswith((".xlsx", ".xls")):
            excel_file = pd.ExcelFile(uploaded_file)
            text_parts = [f"[첨부 엑셀 파일명: {uploaded_file.name}]"]
            for sheet in excel_file.sheet_names:
                df = excel_file.parse(sheet)
                text_parts.append(f"\n--- 시트명: {sheet} (총 {len(df)}행) ---")
                text_parts.append(df.head(200).to_string(index=False))
            return "\n".join(text_parts)

        # 2) CSV 파일 (.csv) - 한글 인코딩(UTF-8 / CP949 / EUC-KR) 자동 감지
        elif filename.endswith(".csv"):
            for enc in ["utf-8-sig", "utf-8", "cp949", "euc-kr"]:
                try:
                    uploaded_file.seek(0)
                    df = pd.read_csv(uploaded_file, encoding=enc)
                    return f"[첨부 CSV 파일명: {uploaded_file.name} (총 {len(df)}행)]\n" + df.head(200).to_string(index=False)
                except Exception:
                    continue
            return "❌ CSV 파일의 한글 인코딩을 읽을 수 없습니다. 엑셀(.xlsx)로 저장 후 다시 올려주세요."

        # 3) PDF 파일 (.pdf)
        elif filename.endswith(".pdf"):
            reader = PdfReader(uploaded_file)
            text_parts = [f"[첨부 PDF 파일명: {uploaded_file.name} (총 {len(reader.pages)}페이지)]"]
            for idx, page in enumerate(reader.pages[:30]):
                page_text = page.extract_text() or ""
                text_parts.append(f"\n--- {idx+1}페이지 ---\n{page_text}")
            return "\n".join(text_parts)[:15000]

        # 4) 워드 파일 (.docx) - 본문 문단 및 표(Table) 전체 추출
        elif filename.endswith(".docx"):
            doc = Document(uploaded_file)
            text_parts = [f"[첨부 워드 파일명: {uploaded_file.name}]"]
            
            # 본문 문단 추출
            for p in doc.paragraphs:
                if p.text.strip():
                    text_parts.append(p.text.strip())
                    
            # 워드 내부의 표(Table) 데이터 추출
            if doc.tables:
                text_parts.append("\n--- [워드 문서 내 표(Table) 데이터] ---")
                for t_idx, table in enumerate(doc.tables):
                    text_parts.append(f"\n[표 {t_idx+1}]")
                    for row in table.rows:
                        row_cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
                        text_parts.append(" | ".join(row_cells))
                        
            return "\n".join(text_parts)[:15000]

        return "지원하지 않는 파일 형식입니다."
    except Exception as e:
        return f"❌ 파일 읽기 오류: {e}"

# ---------------------------------------------------------
# 헬퍼 함수 2: AI 답변을 워드(.docx)로 변환 (한글 폰트 깨짐 방지 적용)
# ---------------------------------------------------------
def create_word_docx(report_text: str) -> bytes:
    """마크다운 형식의 보고서 텍스트를 한글 폰트(맑은 고딕)가 적용된 워드(.docx) 문서로 변환합니다."""
    doc = Document()
    
    # 기본 스타일에 한글 전용 폰트(맑은 고딕) 강제 지정 (한글 깨짐 완벽 방지)
    style = doc.styles["Normal"]
    style.font.name = "Malgun Gothic"
    style.font.size = Pt(10.5)
    style._element.rPr.rFonts.set(qn("w:eastAsia"), "Malgun Gothic")
    
    # 문서 메인 타이틀
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
    # 윈도우/맥 어디서 열어도 한글이 깨지지 않도록 UTF-8-SIG(BOM 포함) 바이트로 반환
    return html_str.encode("utf-8-sig")

# ---------------------------------------------------------
# 2. 왼쪽 사이드바 제어판 및 파일 업로드 UI 구성
# ---------------------------------------------------------
with st.sidebar:
    st.title("⚙️ 에이전트 제어판")
    st.markdown("실시간 법제처·한국은행 DB 연동 및 **3단계 크로스체크** 기반 전문 검토 시스템입니다.")
    
    if st.button("🔄 대화 내용 초기화", use_container_width=True):
        st.session_state.messages = []
        st.rerun()
        
    st.divider()
    
    # 📂 파일 업로드 섹션 (엑셀, PDF, 워드 지원)
    st.subheader("📂 검토 자료 업로드 (선택)")
    uploaded_file = st.file_uploader(
        "엑셀(.xlsx/.xls/.csv), PDF(.pdf), 워드(.docx) 파일을 올리면 법령과 함께 검토합니다.",
        type=["xlsx", "xls", "csv", "pdf", "docx"]
    )
    
    extracted_doc_text = ""
    if uploaded_file is not None:
        with st.spinner("파일 내용을 읽는 중..."):
            extracted_doc_text = extract_file_content(uploaded_file)
        st.success(f"✅ '{uploaded_file.name}' 로드 완료!")
        with st.expander("📄 추출된 파일 내용 미리보기"):
            st.text(extracted_doc_text[:1000] + ("\n...(중략)..." if len(extracted_doc_text) > 1000 else ""))

    st.divider()
    st.subheader("📚 실시간 연동 범위")
    st.markdown("""
    - **현행 법령**: 법률·시행령·시행규칙 원문
    - **행정규칙**: 국세청 훈령·예규 / 노동부 고시
    - **공식 판례**: 대법원 판례 및 법령해석례
    - **경제 통계**: 한국은행(ECOS) 환율·기준금리
    """)
    
    st.divider()
    st.subheader("🔗 주요 기관 바로가기")
    st.markdown("""
    - [국가법령정보센터](https://www.law.go.kr)
    - [국세법령정보시스템](https://taxlaw.nts.go.kr)
    - [한국은행 경제통계(ECOS)](https://ecos.bok.or.kr)
    - [한국회계기준원](https://www.kasb.or.kr)
    """)

# ---------------------------------------------------------
# 3. 메인 화면 및 채팅창 구성
# ---------------------------------------------------------
st.title("⚖️ 세무·법령·회계 검토 자율 에이전트")
st.markdown("국가법령정보센터·한국은행 API 및 **첨부 문서(엑셀·PDF·워드)**를 연동하여 **3단계 팩트체크 보고서**를 작성합니다.")

if "messages" not in st.session_state:
    st.session_state.messages = []

# 이전 대화 기록 출력 및 3종 다운로드 버튼(워드, 인쇄용 문서, 마크다운) 표시
for idx, message in enumerate(st.session_state.messages):
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message["role"] == "assistant":
            col1, col2, col3 = st.columns(3)
            with col1:
                st.download_button(
                    label="📘 워드 다운로드 (.docx)",
                    data=create_word_docx(message["content"]),
                    file_name=f"세무법령_검토보고서_{idx}.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    key=f"docx_{idx}",
                    use_container_width=True
                )
            with col2:
                st.download_button(
                    label="🖨️ 인쇄용 문서 (.html/PDF)",
                    data=create_printable_html(message["content"]),
                    file_name=f"세무법령_검토보고서_{idx}.html",
                    mime="text/html",
                    key=f"print_{idx}",
                    use_container_width=True
                )
            with col3:
                st.download_button(
                    label="📝 마크다운 다운로드 (.md)",
                    data=message["content"].encode("utf-8-sig"),
                    file_name=f"세무법령_검토보고서_{idx}.md",
                    mime="text/markdown",
                    key=f"md_{idx}",
                    use_container_width=True
                )

# 4. 사용자 질문 입력 및 첨부 파일 결합 처리
if prompt := st.chat_input("검토가 필요한 세무·법령·회계 이슈를 입력하세요 (엑셀·PDF·워드 업로드 시 함께 검토합니다)"):
    display_prompt = f"📎 **[첨부파일: {uploaded_file.name}]**\n\n{prompt}" if uploaded_file else prompt
    st.session_state.messages.append({"role": "user", "content": display_prompt})
    with st.chat_message("user"):
        st.markdown(display_prompt)

    if uploaded_file and extracted_doc_text:
        full_input_for_agent = (
            f"사용자 질문: {prompt}\n\n"
            f"아래는 사용자가 업로드한 첨부파일({uploaded_file.name})의 데이터입니다. "
            f"이 데이터와 관련 법령·예규·환율을 대조하여 검토 보고서를 작성하세요:\n"
            f"========================================\n"
            f"{extracted_doc_text}\n"
            f"========================================"
        )
    else:
        full_input_for_agent = prompt

    with st.chat_message("assistant"):
        with st.spinner("🔍 첨부 자료 분석 및 법제처·한국은행 DB 3단계 크로스체크 중입니다..."):
            response = run_agent(full_input_for_agent)
            st.markdown(response)
            
            new_idx = len(st.session_state.messages)
            col1, col2, col3 = st.columns(3)
            with col1:
                st.download_button(
                    label="📘 워드 다운로드 (.docx)",
                    data=create_word_docx(response),
                    file_name="세무법령_검토보고서_최신.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    key=f"docx_new_{new_idx}",
                    use_container_width=True
                )
            with col2:
                st.download_button(
                    label="🖨️ 인쇄용 문서 (.html/PDF)",
                    data=create_printable_html(response),
                    file_name="세무법령_검토보고서_최신.html",
                    mime="text/html",
                    key=f"print_new_{new_idx}",
                    use_container_width=True
                )
            with col3:
                st.download_button(
                    label="📝 마크다운 다운로드 (.md)",
                    data=response.encode("utf-8-sig"),
                    file_name="세무법령_검토보고서_최신.md",
                    mime="text/markdown",
                    key=f"md_new_{new_idx}",
                    use_container_width=True
                )
            
    st.session_state.messages.append({"role": "assistant", "content": response})
