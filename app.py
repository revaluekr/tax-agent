import streamlit as st
import agent  # 터미널용으로 완성하신 기존 에이전트 모듈

# 1. 웹 페이지 기본 설정
st.set_page_config(
    page_title="세무·법령 AI 에이전트", 
    page_icon="⚖️", 
    layout="centered"
)

# 2. 메인 타이틀 및 헤더
st.title("⚖️ 세무·법령 검토 자율 에이전트")
st.markdown("법제처 API와 연동되어 자율적으로 법령을 검색하고 4단 구조의 검토 보고서를 작성합니다.")

# 3. 대화 기록(Session State) 초기화
# Streamlit은 상호작용이 일어날 때마다 코드를 처음부터 재실행하므로, 대화 내역을 메모리에 보존해야 합니다.
if "messages" not in st.session_state:
    st.session_state.messages = []

# 4. 이전 대화 기록 화면에 렌더링
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# 5. 사용자 채팅 입력창
if prompt := st.chat_input("검토가 필요한 이슈나 키워드를 입력하세요 (예: 근로기준법상 연차 휴가 규정 검토)"):
    
    # 사용자 질문을 화면에 띄우고 세션에 저장
    st.chat_message("user").markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})

    # AI 에이전트 구동 및 응답 출력
    with st.chat_message("assistant"):
        # API 검색 및 생성 시간을 고려해 스피너(로딩 UI) 추가
        with st.spinner("에이전트가 법령을 검색하고 검토 보고서를 작성 중입니다..."):
            try:
                # 👉 주의: agent.py 내부에서 질문을 받아 텍스트를 리턴하는 실제 함수명으로 변경하세요.
                # (예: generate_report, chat_with_agent 등)
                response = agent.run_agent(prompt) 
                
                # 생성된 4단 구조 보고서를 화면에 렌더링하고 세션에 저장
                st.markdown(response)
                st.session_state.messages.append({"role": "assistant", "content": response})
                
            except Exception as e:
                error_msg = f"실행 중 오류가 발생했습니다: {str(e)}"
                st.error(error_msg)
                st.session_state.messages.append({"role": "assistant", "content": error_msg})