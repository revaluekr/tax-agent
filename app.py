import streamlit as st
from datetime import datetime
import agent  # 세무·법령 검토 자율 에이전트 모듈

# 1. 웹 페이지 기본 설정
st.set_page_config(
    page_title="세무·법령 AI 에이전트", 
    page_icon="⚖️", 
    layout="wide"
)

# 2. 좌측 사이드바 메뉴 구성
with st.sidebar:
    st.header("⚙️ 에이전트 제어판")
    st.markdown("실시간 법제처 DB 연동 및 **3단계 크로스체크** 기반의 전문 검토 시스템입니다.")
    
    # 대화 초기화 버튼
    if st.button("🔄 대화 내용 초기화", use_container_width=True):
        st.session_state.messages = []
        st.rerun()
        
    st.divider()
    
    st.subheader("📚 실시간 연동 법령 범위")
    st.markdown("""
    - **현행 법령:** 법률·시행령·시행규칙
    - **행정규칙:** 국세청 훈령·예규 / 노동부 고시
    - **공식 판례:** 대법원 판례 및 법령해석례
    - **검토 구조:** 결론 ➔ 법리 ➔ 리스크 ➔ 출처
    """)
    
    st.divider()
    
    st.subheader("🔗 주요 기관 바로가기")
    st.markdown("""
    - [국가법령정보센터](https://www.law.go.kr)
    - [국세법령정보시스템](https://taxlaw.nts.go.kr)
    - [사법정보공개포털](https://portal.scourt.go.kr)
    - [한국회계기준원](https://www.kasb.or.kr)
    """)
    st.caption("Powered by Gemini 3.8 Flash & MOLEG API")

# 3. 메인 타이틀 및 헤더
st.title("⚖️ 세무·법령·회계 검토 자율 에이전트")
st.markdown("국가법령정보센터 API와 연동되어 **법령·예규·판례를 실시간 검색**하고 **3단계 팩트체크 보고서**를 작성합니다.")

# 4. 대화 기록(Session State) 초기화
if "messages" not in st.session_state:
    st.session_state.messages = []

# 5. 이전 대화 기록 화면에 렌더링 (다운로드 버튼 포함)
for idx, msg in enumerate(st.session_state.messages):
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        
        # AI(assistant)가 작성한 정상 보고서 하단에 다운로드 버튼 표시
        if msg["role"] == "assistant" and not msg["content"].startswith("❌"):
            today_str = datetime.now().strftime("%Y%m%d")
            col1, col2, _ = st.columns([2, 2, 6])
            with col1:
                st.download_button(
                    label="📄 보고서 다운로드 (.txt)",
                    data=msg["content"],
                    file_name=f"세무법령_검토보고서_{today_str}_{idx}.txt",
                    mime="text/plain",
                    key=f"dl_txt_{idx}"
                )
            with col2:
                st.download_button(
                    label="📝 마크다운 저장 (.md)",
                    data=msg["content"],
                    file_name=f"세무법령_검토보고서_{today_str}_{idx}.md",
                    mime="text/markdown",
                    key=f"dl_md_{idx}"
                )

# 6. 사용자 채팅 입력창
if prompt := st.chat_input("검토가 필요한 세무·법령·회계·노무 이슈를 입력하세요 (예: 기업업무추진비 한도 초과액 세무조정 검토)"):
    
    # 사용자 질문을 화면에 띄우고 세션에 저장
    st.chat_message("user").markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})

    # AI 에이전트 구동 및 응답 출력
    with st.chat_message("assistant"):
        with st.spinner("🔍 법령·예규·판례를 실시간 검색하고 3단계 크로스체크 보고서를 작성 중입니다..."):
            try:
                response = agent.run_agent(prompt)
                
                # 생성된 보고서를 화면에 렌더링하고 세션에 저장
                st.markdown(response)
                st.session_state.messages.append({"role": "assistant", "content": response})
                
                # 방금 생성된 최신 보고서 하단에도 즉시 다운로드 버튼 표시
                new_idx = len(st.session_state.messages) - 1
                today_str = datetime.now().strftime("%Y%m%d")
                col1, col2, _ = st.columns([2, 2, 6])
                with col1:
                    st.download_button(
                        label="📄 보고서 다운로드 (.txt)",
                        data=response,
                        file_name=f"세무법령_검토보고서_{today_str}_{new_idx}.txt",
                        mime="text/plain",
                        key=f"dl_txt_{new_idx}"
                    )
                with col2:
                    st.download_button(
                        label="📝 마크다운 저장 (.md)",
                        data=response,
                        file_name=f"세무법령_검토보고서_{today_str}_{new_idx}.md",
                        mime="text/markdown",
                        key=f"dl_md_{new_idx}"
                    )
                
            except Exception as e:
                error_msg = f"❌ 실행 중 오류가 발생했습니다: {str(e)}"
                st.error(error_msg)
                st.session_state.messages.append({"role": "assistant", "content": error_msg})
