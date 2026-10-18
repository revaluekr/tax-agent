import os
from google import genai
from google.genai import types
from config import GEMINI_API_KEY
from law_api import search_law_data, get_law_content

# 1. Gemini 클라이언트 및 모델 설정
client = genai.Client(api_key=GEMINI_API_KEY)
MODEL_ID = "gemini-3.8-flash"

# 2. Gemini 도구 정의
def search_law_for_gemini(keyword: str, target: str = "law") -> str:
    """국가법령정보센터에서 법령, 판례, 행정규칙을 검색합니다."""
    print(f"\n[시스템] 💡 검색 도구 가동: '{keyword}' (대상: {target})")
    results = search_law_data(keyword, target)
    if not results:
        return "검색 결과가 없습니다."
    
    summary = f"총 {len(results)}건 검색됨:\n"
    for i, item in enumerate(results[:5]):
        if target == "law":
            summary += f"{i+1}. 법령명: {item.get('법령명한글')}, 시행일: {item.get('시행일자')}, ID: {item.get('법령일련번호')}\n"
        elif target == "prec":
            summary += f"{i+1}. 사건명: {item.get('사건명')}, 선고일자: {item.get('선고일자')}\n"
        else:
            summary += f"{i+1}. {item.get('법령명한글', '제목 없음')}\n"
    return summary

def get_law_details_for_gemini(law_id: str) -> str:
    """특정 법령의 ID(일련번호)를 입력받아 법령 본문을 조회합니다."""
    print(f"\n[시스템] 💡 상세 본문 조회 도구 가동: 일련번호 '{law_id}'")
    return get_law_content(law_id)

# 3. 에이전트 시스템 프롬프트 및 실행 로직
SYSTEM_PROMPT = """당신은 세무·법령 검토 자율 전문 에이전트입니다.
사용자 질문 시 반드시 다음 절차를 따르세요:
1. 'search_law_for_gemini' 도구를 통해 관련 법령의 ID(일련번호)를 검색합니다.
2. 필요시 'get_law_details_for_gemini' 도구를 통해 본문을 추가 확인합니다.
3. 분석 후 다음 구조의 [세무·법령 검토 보고서]를 작성합니다:
   - 📌 검토 개요
   - 📜 관련 법령 및 근거
   - 🔍 실무 분석
   - 💡 결론 및 권고사항
"""

# 웹 인터페이스(app.py) 연동을 위해 수정된 메인 함수
def run_agent(user_input: str) -> str:
    """웹에서 전달받은 질문(user_input)을 처리하고 결과 텍스트를 반환합니다."""
    print(f"🤖 [시스템] 웹 요청 처리 중: {user_input}")
    
    try:
        # 단일 요청에 대한 에이전트 세션 생성
        chat = client.chats.create(
            model=MODEL_ID,
            config=types.GenerateContentConfig(
                tools=[search_law_for_gemini, get_law_details_for_gemini],
                temperature=0.2,
                system_instruction=SYSTEM_PROMPT
            )
        )
        
        # 모델에 질문 전달 및 응답 생성
        response = chat.send_message(user_input)
        return response.text
        
    except Exception as e:
        error_msg = f"❌ 실행 중 오류가 발생했습니다: {str(e)}"
        print(error_msg)
        return error_msg