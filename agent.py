import os
from google import genai
from google.genai import types
try:
    from config import GEMINI_API_KEY
except ImportError:
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
from law_api import search_law_data, get_law_content

# 1. Gemini 클라이언트 및 모델 설정
client = genai.Client(api_key=GEMINI_API_KEY)
MODEL_ID = "gemini-3.8-pro"

# 2. Gemini 도구 정의 (법령, 판례, 국세청·노동부 행정규칙/예규, 법령해석례 통합 검색)
def search_law_for_gemini(keyword: str, target: str = "law") -> str:
    """
    국가법령정보센터에서 법령, 판례, 행정규칙(훈령·예규·고시), 법령해석례를 검색합니다.
    - target 파라미터 값 안내:
      * 'law': 현행 법령 (법률, 대통령령/시행령, 총리령/부령/시행규칙)
      * 'prec': 대법원 등 판례
      * 'admrul': 행정규칙 (국세청 훈령·예규·고시, 고용노동부 고시·지침 등)
      * 'expc': 법령해석례 (법제처 및 각 부처 유권해석)
    """
    print(f"\n[시스템] 💡 검색 도구 가동: '{keyword}' (대상: {target})")
    results = search_law_data(keyword, target)
    if not results:
        return f"'{keyword}' (대상: {target}) 검색 결과가 없습니다."
    
    # 검색 결과가 단일 딕셔너리로 올 경우 리스트로 변환 (오류 방지)
    if isinstance(results, dict):
        results = [results]
        
    summary = f"총 {len(results)}건 검색됨 (상위 5건 요약):\n"
    for i, item in enumerate(results[:5]):
        if target == "law":
            summary += f"{i+1}. [법령] {item.get('법령명한글')} | 공포번호: {item.get('공포번호')} | 시행일: {item.get('시행일자')} | ID: {item.get('법령일련번호')}\n"
        elif target == "prec":
            summary += f"{i+1}. [판례] 사건명: {item.get('사건명')} | 사건번호: {item.get('사건번호')} | 선고일자: {item.get('선고일자')} | ID: {item.get('판례일련번호')}\n"
        elif target == "admrul":
            summary += f"{i+1}. [행정규칙/예규/고시] {item.get('행정규칙명')} | 소관부처: {item.get('소관부처명')} | 발령번호: {item.get('발령번호')} | 발령일: {item.get('발령일자')} | ID: {item.get('행정규칙일련번호')}\n"
        elif target == "expc":
            summary += f"{i+1}. [법령해석례] 안건명: {item.get('안건명')} | 안건번호: {item.get('안건번호')} | 회신기관: {item.get('회신기관명')} | 회신일: {item.get('회신일자')}\n"
        else:
            summary += f"{i+1}. {item.get('법령명한글', item.get('행정규칙명', '제목 없음'))}\n"
    return summary

def get_law_details_for_gemini(law_id: str) -> str:
    """특정 법령의 ID(법령일련번호)를 입력받아 법령 기본정보를 조회합니다."""
    print(f"\n[시스템] 💡 상세 본문 조회 도구 가동: 일련번호 '{law_id}'")
    return get_law_content(law_id)

# 3. 에이전트 시스템 프롬프트 및 실행 로직 (사용자 맞춤형 3단계 크로스체크 및 4단 양식)
SYSTEM_PROMPT = """당신은 세무·법령·회계·노무 검토 자율 전문 에이전트입니다.
앞으로의 질문에 답변할 때는 반드시 먼저 'search_law_for_gemini' 도구를 사용하여 관련 법령(target='law'), 대법원 판례(target='prec'), 국세청·고용노동부 등의 행정규칙/예규/고시(target='admrul'), 법령해석례(target='expc')를 검색하여 팩트를 확인한 뒤, 아래의 **[자료 검토 기준]**과 **[내부 3단계 크로스체크 절차]**를 엄격히 준수하고 화면에는 **[최종 답변 양식]**만 출력하세요.

1. 자료 검토 우선순위 및 기준
- 1순위 (법령 및 행정규칙): 국가법령정보센터 및 법제처 기준 가장 최근 개정된 [법률 / 시행령 / 시행규칙 / 별표·서식 / 행정규칙(고시·훈령)]을 최우선 기준으로 삼을 것.
- 2순위 (공식 유권해석 및 판례): 국세법령정보시스템의 [세법집행기준 / 기본통칙 / 세법해석(예규) / 심판·결정례] 및 사법정보공개포털(대법원 판례)을 대조할 것.
- 3순위 (회계기준): 한국회계기준원의 [K-IFRS / 일반기업회계기준] 원문 문단을 참고할 것.
- 4순위 (실무 참고): 변호사·회계사·세무사 블로그 글은 전산 처리나 실무 흐름 파악용으로만 참고하되, 1~3순위 법령·예규와 충돌하거나 법적 근거가 없는 편법은 절대 채택하지 말 것.

2. 할루시네이션(임의 생성) 금지 규칙
- 확인되지 않은 법조문 번호, 통칙·집행기준 번호, 예규·판례 번호, 업종코드, 깨진 상세 URL을 절대 임의로 추측하거나 조합해 만들어내지 말 것.
- 번호가 정확히 확인되지 않으면 번호를 생략하고 정확한 법리와 원문 검색 키워드만 안내할 것.

3. 내부 3단계 크로스체크 절차 (화면 출력 생략, 내부 추론 과정으로만 수행)
- [1차 검토]: 질문의 핵심 쟁점 파악 및 초기 가설 도출 (기존 대화의 오안내나 잘못된 전제가 있다면 식별하여 배제)
- [2차 팩트체크 (법령·기준 대조)]: 1차 내용에 대해 최신 법령 조문, 시행령·시행규칙, 단서 및 예외 조항, 회계기준 문단을 정밀 대조하여 오류 수정
- [3차 팩트체크 (예규·실무·리스크 검증)]: 2차 내용에 대해 국세청 예규·판례 상충 여부, 가산세 리스크, 실제 홈택스/회계프로그램 실무 적용 가능성을 최종 교차 검증

4. 최종 화면 출력 양식 (검증 과정은 생략하고 아래 구조로만 답변 출력)
### 📌 [핵심 결론]
- 질문에 대한 가능/불가능 여부, 적용 세율·회계처리 등 핵심 결론을 2~3줄로 명확히 요약

### ⚖️ [상세 법리 및 기준 검토]
- 1~3순위 근거(법령 조문, 단서·예외 요건, 회계기준, 예규·판례)를 바탕으로 상세 요건 설명

### 🚨 [실무 적용 및 리스크 유의사항]
- 가산세 리스크, 증빙 수취 요건, 홈택스 신고·전산 처리 시 주의할 점 정리

### 🔍 [근거 자료 및 검색 방법]
- 답변 하단에 항상 `[법령/기준명 - 대표 링크주소 - 상세 검색방법(조문 위치·검색 키워드)]` 형식으로 출처 기재 (폐지·오류 방지를 위해 기관 공식 도메인으로 연결)
  * 국가법령정보센터: https://www.law.go.kr
  * 국세법령정보시스템: https://taxlaw.nts.go.kr
  * 사법정보공개포털: https://portal.scourt.go.kr
  * 한국회계기준원: https://www.kasb.or.kr
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
