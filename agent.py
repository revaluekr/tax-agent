import os
from datetime import datetime
from google import genai
from google.genai import types
try:
    from config import GEMINI_API_KEY
except ImportError:
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

from law_api import (
    search_law_data, 
    get_law_content, 
    get_bok_exchange_rate, 
    get_bok_base_rate,
    search_industry_code
)

# 1. Gemini 클라이언트 및 기본/심층 모델 설정
client = genai.Client(api_key=GEMINI_API_KEY)
FLASH_MODEL_ID = "gemini-3.8-flash"
PRO_MODEL_ID = "gemini-3.8-pro"

# 고난도 법리 검토 키워드 목록
DEEP_KEYWORDS = [
    "합병", "분할", "세무조사", "조세심판", "부당행위", "가업승계", "계약서",
    "실질과세", "법인격", "명의신탁", "주식평가", "사기나 그 밖의 부정한", "조세범",
    "뇌물", "외국환", "비거주자", "조세조약", "고정사업장", "이전가격", "불균등",
    "증여의제", "과점주주", "청산", "해산", "자본거래", "심층", "정밀", "종합검토"
]

# 복합 세액 계산 및 시뮬레이션 키워드 목록
CALC_KEYWORDS = [
    "시뮬레이션", "시나리오", "비교", "절세효과", "실효세율", "한도초과", "세무조정",
    "퇴직소득", "할인율", "현재가치", "가지급금 인정이자", "대손충당금", "감가상각"
]

def select_optimal_model(user_query: str, has_file: bool = False) -> tuple[str, str]:
    """
    질문 내용과 파일 첨부 여부를 분석하여 최적의 모델(Flash vs Pro)과 전환 사유를 반환합니다.
    분석이 끝나면 다음 질문에서는 다시 기본 상태(Flash)에서 새로 판단합니다.
    """
    # 조건 1: 엑셀, PDF, 워드 등 첨부파일이 있는 경우 무조건 Pro 전환
    if has_file:
        return PRO_MODEL_ID, "🧠 **[Pro 심층 모드 자동 전환]** 첨부 문서 정밀 분석 및 법령 교차 검증"

    # 조건 2: 고난도 심층 키워드가 포함된 경우 Pro 전환
    matched_deep = [kw for kw in DEEP_KEYWORDS if kw in user_query]
    if matched_deep:
        return PRO_MODEL_ID, f"🧠 **[Pro 심층 모드 자동 전환]** 고난도 쟁점 감지 ({', '.join(matched_deep[:3])})"

    # 조건 3: 질문 길이가 길거나(250자 이상) 복합 계산 키워드가 2개 이상 결합된 경우 Pro 전환
    matched_calc = [kw for kw in CALC_KEYWORDS if kw in user_query]
    if len(user_query.strip()) >= 250 or (len(user_query.strip()) >= 120 and len(matched_calc) >= 2):
        return PRO_MODEL_ID, "🧠 **[Pro 심층 모드 자동 전환]** 장문·복합 계산 시뮬레이션 감지"

    # 평상시 기본값: 토큰 절약을 위해 Flash 모델 사용
    return FLASH_MODEL_ID, "⚡ **[Flash 빠른 검토 모드]** 일반 법령·통계·업종코드 신속 조회"

# 2. Gemini 도구 정의 (법제처 원문 + 한국은행 ECOS + 국세청 업종코드 검색 도구 통합)
def search_law_for_gemini(keyword: str, target: str = "law") -> str:
    """
    국가법령정보센터에서 법령, 판례, 행정규칙(훈령·예규·고시), 법령해석례 목록과 일련번호(ID)를 검색합니다.
    - target 파라미터 값 안내:
      * 'law': 현행 법령 (법률, 대통령령/시행령, 총리령/부령/시행규칙)
      * 'prec': 대법원 등 판례
      * 'admrul': 행정규칙 (국세청 훈령·예규·고시, 고용노동부 고시·지침 등)
      * 'expc': 법령해석례 (법제처 및 각 부처 유권해석)
    """
    print(f"\n[시스템] 💡 목록 검색 도구 가동: '{keyword}' (대상: {target})")
    results = search_law_data(keyword, target)
    if not results:
        return f"'{keyword}' (대상: {target}) 검색 결과가 없습니다."
    
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
            summary += f"{i+1}. [법령해석례] 안건명: {item.get('안건명')} | 안건번호: {item.get('안건번호')} | 회신기관: {item.get('회신기관명')} | ID: {item.get('법령해석례일련번호')}\n"
        else:
            summary += f"{i+1}. {item.get('법령명한글', item.get('행정규칙명', '제목 없음'))}\n"
    return summary

def get_law_details_for_gemini(doc_id: str, target: str = "law", query_filter: str = "") -> str:
    """
    검색된 일련번호(ID)를 입력받아 법령 조문, 판례 요지, 행정규칙(예규) 본문, 법령해석례 회답 원문을 상세 조회합니다.
    - doc_id: search_law_for_gemini에서 확인한 ID(일련번호) 문자열
    - target: 'law'(법령), 'prec'(판례), 'admrul'(행정규칙/예규), 'expc'(법령해석례)
    - query_filter: (선택사항) target이 'law'일 때 특정 조문 번호나 단어(예: '제6조', '창업중소기업')가 포함된 조문만 추출할 때 입력
    """
    print(f"\n[시스템] 📖 원문 정밀 조회 가동: ID '{doc_id}' (대상: {target}, 필터: '{query_filter}')")
    return get_law_content(doc_id, target, query_filter)

def search_exchange_rate_for_gemini(start_date: str, end_date: str, currency: str = "USD") -> str:
    """
    한국은행 ECOS에서 특정 기간의 공식 환율(매매기준율)을 조회합니다.
    - start_date, end_date: 'YYYYMMDD' 형식 (예: '20251226', '20251231' / 휴일 대비 5~7일 구간 조회 필수)
    - currency: 'USD'(미국 달러), 'JPY'(일본 엔), 'EUR'(유로), 'CNY'(중국 위안)
    """
    print(f"\n[시스템] 💱 한국은행 환율 조회 도구 가동: {currency} ({start_date}~{end_date})")
    return get_bok_exchange_rate(start_date, end_date, currency)

def search_base_rate_for_gemini(start_date: str, end_date: str) -> str:
    """
    한국은행 ECOS에서 특정 기간('YYYYMMDD' ~ 'YYYYMMDD')의 한국은행 기준금리를 조회합니다.
    """
    print(f"\n[시스템] 📈 한국은행 기준금리 조회 도구 가동: ({start_date}~{end_date})")
    return get_bok_base_rate(start_date, end_date)

def search_industry_code_for_gemini(keyword: str) -> str:
    """
    프로젝트 내 마스터 데이터('industry_codes.xlsx' 또는 '.csv')에서 국세청 6자리 기준경비율 업종코드, 세세분류명, 적용범위를 검색합니다.
    업종코드나 사업자등록 업태·종목, 창업감면 대상 업종코드 질문 시 반드시 이 도구를 먼저 호출하세요.
    - keyword: 검색할 핵심 업종 키워드 또는 6자리 코드 (예: '전자상거래', '소프트웨어', '음식점', '525101')
    """
    print(f"\n[시스템] 🏢 국세청 업종코드 검색 도구 가동: '{keyword}'")
    return search_industry_code(keyword)

# 3. 에이전트 시스템 프롬프트 템플릿 (사전 3줄 크로스체크 선출력 + API 연동 결합본)
SYSTEM_PROMPT = """당신은 세무·법령·회계·노무 검토 자율 전문 에이전트입니다.
앞으로의 질문에 답변할 때는 반드시 먼저 제공된 도구(API)들을 사용하여 실제 원문 데이터와 통계를 확인한 뒤, 아래의 **[자료 검토 기준]**을 엄격히 준수하고, 반드시 **[A. 사전 3줄 크로스체크]**를 먼저 출력한 뒤 **[B. 최종 답변]**을 작성해줘.

[필수 도구 호출 원칙]
- 법령·판례·예규 확인: 'search_law_for_gemini'로 ID를 찾은 뒤 'get_law_details_for_gemini'로 실제 조문·본문을 읽을 것.
- 환율·기준금리 확인: 날짜의 과거/미래 여부를 예단하지 말고 반드시 'search_exchange_rate_for_gemini' 또는 'search_base_rate_for_gemini'를 호출할 것 (주말/공휴일 대비 대상일 직전 5~7일 구간 조회 필수).
- 국세청 업종코드 확인: 업종코드 질문 시 반드시 'search_industry_code_for_gemini'를 호출하여 데이터에서 확인된 6자리 코드만 안내하고, 도구에서 조회되지 않는 코드는 절대 임의로 숫자를 조합해 생성하지 말 것.

1. 자료 검토 우선순위 및 기준
- 1순위 (법령 및 행정규칙): 국가법령정보센터 및 법제처 기준 가장 최근 개정된 [법률 / 시행령 / 시행규칙 / 별표·서식 / 행정규칙(고시·훈령)]을 최우선 기준으로 삼을 것.
- 2순위 (공식 유권해석 및 판례): 국세법령정보시스템의 [세법집행기준 / 기본통칙 / 세법해석(예규) / 심판·결정례] 및 사법정보공개포털(대법원 판례)을 대조할 것.
- 3순위 (회계기준 및 공식 통계·업종DB): 한국회계기준원의 [K-IFRS / 일반기업회계기준] 원문 문단, 한국은행 경제통계시스템(ECOS) 공식 환율·금리, 국세청 기준경비율 업종코드 데이터를 참고할 것.
- 4순위 (실무 참고): 전문가 블로그 글은 전산 처리나 실무 흐름 파악용으로만 참고하되, 1~3순위 법령·예규와 충돌하거나 법적 근거가 없는 편법은 절대 채택하지 말 것.

2. 할루시네이션(임의 생성) 금지 규칙
- 확인되지 않은 법조문 번호, 통칙·집행기준 번호, 예규·판례 번호, 업종코드(6자리), 환율·금리 수치, 깨진 상세 URL을 절대 임의로 추측하거나 조합해 만들어내지 말 것.
- 번호가 정확히 확인되지 않으면 번호를 생략하고 정확한 법리와 원문 검색 키워드만 안내할 것.

3. 필수 출력 양식 (반드시 A → B 순서대로 화면에 출력할 것)

### 🔍 [A. 사전 3줄 크로스체크]
- **1차(쟁점 파악)**: 질문의 핵심 쟁점 및 잘못된 전제 유무 1줄 요약
- **2차(법령·기준 대조)**: 적용할 핵심 법령명·회계기준·업종코드/환율 및 반드시 체크해야 할 단서·예외 요건 1줄 요약
- **3차(예규·리스크 검증)**: 상충 예규 유무 및 가산세·실무 신고 시 핵심 주의점 1줄 요약

---

### 📋 [B. 최종 답변]

### 📌 [핵심 결론]
- 위 3줄 검증 결과를 반영하여 질문에 대한 가능/불가능 여부, 적용 세율·업종코드·회계처리 등 핵심 결론을 2~3줄로 명확히 요약

### ⚖️ [상세 법리 및 기준 검토]
- 1~3순위 근거(법령 조문, 단서·예외 요건, 회계기준, 예규·판례, 공식 통계·업종코드)를 바탕으로 상세 요건 설명

### 🚨 [실무 적용 및 리스크 유의사항]
- 가산세 리스크, 증빙 수취 요건, 홈택스 신고·전산 처리(위하고 등) 시 주의할 점 정리

### 🔗 [근거 자료 및 검색 방법]
- 답변 하단에 항상 `[법령/기준명 - 대표 링크주소 - 상세 검색방법(조문 위치·검색 키워드)]` 형식으로 출처 기재 (폐지·오류 방지를 위해 기관 공식 도메인으로 연결)
  * 국가법령정보센터: https://www.law.go.kr
  * 국세법령정보시스템: https://taxlaw.nts.go.kr
  * 한국은행 경제통계시스템(ECOS): https://ecos.bok.or.kr
  * 한국회계기준원: https://www.kasb.or.kr
  * 국세청 홈택스(업종코드 조회): https://www.hometax.go.kr
"""

# 웹 인터페이스(app.py) 연동을 위해 수정된 메인 함수 (스마트 모델 자동 전환 적용)
def run_agent(user_input: str, raw_query: str = "", has_file: bool = False) -> str:
    """
    웹에서 전달받은 질문을 분석하여 평소에는 Flash로,
    특정 조건(파일 첨부, 고난도 키워드, 장문·복합 계산)일 때만 Pro로 자동 전환하여 실행합니다.
    """
    query_for_routing = raw_query if raw_query else user_input
    selected_model, mode_badge = select_optimal_model(query_for_routing, has_file)
    
    print(f"🤖 [시스템] 선택된 모델: {selected_model} | 사유: {mode_badge}")
    
    today_str = datetime.now().strftime("%Y년 %m월 %d일")
    dynamic_prompt = f"[시스템 기준일 안내: 오늘 날짜는 {today_str}입니다. 질문에 등장하는 연도와 날짜의 과거/현재 여부를 반드시 오늘 날짜({today_str}) 기준으로 판단하세요.]\n\n" + SYSTEM_PROMPT
    
    tools_list = [
        search_law_for_gemini, 
        get_law_details_for_gemini,
        search_exchange_rate_for_gemini,
        search_base_rate_for_gemini,
        search_industry_code_for_gemini
    ]
    
    try:
        chat = client.chats.create(
            model=selected_model,
            config=types.GenerateContentConfig(
                tools=tools_list,
                temperature=0.2,
                system_instruction=dynamic_prompt
            )
        )
        
        response = chat.send_message(user_input)
        return f"> {mode_badge}\n\n" + response.text
        
    except Exception as e:
        # 만약 Pro 모델 호출 중 일시적 서버 지연 등이 발생하면 즉시 Flash 모델로 안전하게 폴백(Fallback)
        if selected_model == PRO_MODEL_ID:
            print(f"⚠️ Pro 모델 응답 지연으로 Flash 모델로 자동 전환하여 재시도합니다: {e}")
            try:
                fallback_chat = client.chats.create(
                    model=FLASH_MODEL_ID,
                    config=types.GenerateContentConfig(
                        tools=tools_list,
                        temperature=0.2,
                        system_instruction=dynamic_prompt
                    )
                )
                response = fallback_chat.send_message(user_input)
                return f"> ⚡ **[Flash 백업 모드]** (Pro 서버 응답 지연으로 자동 전환됨)\n\n" + response.text
            except Exception as e2:
                return f"❌ 실행 중 오류가 발생했습니다: {str(e2)}"
        
        error_msg = f"❌ 실행 중 오류가 발생했습니다: {str(e)}"
        print(error_msg)
        return error_msg
