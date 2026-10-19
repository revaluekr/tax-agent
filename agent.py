import os
import math
from datetime import datetime
from google import genai
from google.genai import types

try:
    from config import get_gemini_key_pool
    API_KEY_POOL = get_gemini_key_pool()
except ImportError:
    API_KEY_POOL = []
    seen_keys = set()
    for i in range(1, 6):
        k = os.getenv(f"GEMINI_FREE_KEY_{i}", "").strip()
        if k and k not in seen_keys:
            API_KEY_POOL.append((f"무료키 #{i}", k))
            seen_keys.add(k)
    for env_name, lbl in [("GEMINI_PAID_KEY", "💳 유료 예비키(최후 방어벽)"), ("GEMINI_API_KEY", "기본키(예비)")]:
        k = os.getenv(env_name, "").strip()
        if k and k not in seen_keys:
            final_lbl = "💳 유료 예비키(최후 방어벽)" if API_KEY_POOL else lbl
            API_KEY_POOL.append((final_lbl, k))
            seen_keys.add(k)

from law_api import (
    search_law_data, 
    get_law_content, 
    get_bok_exchange_rate, 
    get_bok_base_rate,
    search_industry_code
)

# 1. 기본/심층 모델 설정 및 스마트 라우팅 기준
FLASH_MODEL_ID = "gemini-3.8-flash"
PRO_MODEL_ID = "gemini-3.8-pro"

FORCE_PRO_TRIGGERS = ["[프로]", "[정밀검토]", "[심층검토]", "프로모드"]

DEEP_KEYWORDS = [
    "합병", "분할", "세무조사", "조세심판", "부당행위계산", "가업승계",
    "실질과세", "법인격", "명의신탁", "사기나 그 밖의 부정한", "조세범",
    "뇌물방지법", "조세조약", "고정사업장", "이전가격", "불균등증자", "불균등감자"
]

CALC_KEYWORDS = [
    "시뮬레이션", "시나리오별", "실효세율 비교", "20년 플랜", "30년 플랜"
]

def select_optimal_model(user_query: str, has_file: bool = False, full_input_len: int = 0) -> tuple[str, str]:
    """평소 95% 이상은 Flash를 쓰고, 초대형 문서나 복합 고난도 쟁점일 때만 제한적으로 Pro를 선택합니다."""
    for trigger in FORCE_PRO_TRIGGERS:
        if trigger in user_query:
            return PRO_MODEL_ID, f"🧠 **[Pro 심층 모드]** 사용자 지정 정밀 검토 ({trigger})"

    if has_file and full_input_len >= 15000:
        return PRO_MODEL_ID, f"🧠 **[Pro 심층 모드 자동 전환]** 대용량 문서({full_input_len:,}자) 정밀 분석"

    matched_deep = [kw for kw in DEEP_KEYWORDS if kw in user_query]
    if len(matched_deep) >= 2:
        return PRO_MODEL_ID, f"🧠 **[Pro 심층 모드 자동 전환]** 복합 고난도 쟁점 감지 ({', '.join(matched_deep[:3])})"

    matched_calc = [kw for kw in CALC_KEYWORDS if kw in user_query]
    if len(user_query.strip()) >= 500 and len(matched_calc) >= 1:
        return PRO_MODEL_ID, "🧠 **[Pro 심층 모드 자동 전환]** 초장문 복합 시뮬레이션 감지"

    return FLASH_MODEL_ID, "⚡ **[Flash 빠른 검토 모드]** 실무 표준 검토 (토큰 절약 모드)"

# 2. Gemini 도구 정의 (법제처 6종 DB + 한국은행 ECOS + 국세청 업종코드 + 파이썬 정밀 계산기)
def search_law_for_gemini(keyword: str, target: str = "law") -> str:
    """
    국가법령정보센터에서 법령, 판례, 행정규칙, 법령해석례, 조세심판원 재결례, 지방세 자치법규(조례) 목록과 일련번호(ID)를 검색합니다.
    - target 파라미터 값 안내:
      * 'law': 현행 법령 (법률, 대통령령/시행령, 총리령/부령/시행규칙, 지방세법 등)
      * 'prec': 대법원 등 판례
      * 'decc': 특별행정심판재결례 (조세심판원 심판결정례 '조심' 등)
      * 'admrul': 행정규칙 (국세청 훈령·예규·고시, 고용노동부 고시·지침 등)
      * 'expc': 법령해석례 (기획재정부·국세청·법제처 등 유권해석 및 질의회신)
      * 'ordin': 지방자치단체 자치법규 (서울시·경기도 등 시·군·구 지방세 감면/중과 조례 등)
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
        elif target == "decc":
            summary += f"{i+1}. [조세심판/특별행정심판] 사건명: {item.get('사건명')} | 사건번호: {item.get('사건번호')} | 의결일자: {item.get('의결일자', item.get('처분일자'))} | ID: {item.get('특별행정심판재결례일련번호')}\n"
        elif target == "admrul":
            summary += f"{i+1}. [행정규칙/예규/고시] {item.get('행정규칙명')} | 소관부처: {item.get('소관부처명')} | 발령번호: {item.get('발령번호')} | 발령일: {item.get('발령일자')} | ID: {item.get('행정규칙일련번호')}\n"
        elif target == "expc":
            summary += f"{i+1}. [법령해석례/질의회신] 안건명: {item.get('안건명')} | 안건번호: {item.get('안건번호')} | 회신기관: {item.get('회신기관명')} | ID: {item.get('법령해석례일련번호')}\n"
        elif target == "ordin":
            summary += f"{i+1}. [지자체 조례/자치법규] {item.get('자치법규명', item.get('법령명한글'))} | 지자체: {item.get('지자체기관명')} | 시행일: {item.get('시행일자')} | ID: {item.get('자치법규일련번호', item.get('법령일련번호'))}\n"
        else:
            summary += f"{i+1}. {item.get('법령명한글', item.get('행정규칙명', '제목 없음'))}\n"
    return summary

def get_law_details_for_gemini(doc_id: str, target: str = "law", query_filter: str = "") -> str:
    """
    검색된 일련번호(ID)를 입력받아 법령 조문, 판례 요지, 조세심판원 결정례('decc'), 행정규칙('admrul'), 법령해석례('expc'), 지자체 조례('ordin') 본문 원문을 상세 조회합니다.
    - doc_id: search_law_for_gemini에서 확인한 ID(일련번호) 문자열
    - target: 'law'(법령), 'prec'(판례), 'decc'(조세심판원 재결례), 'admrul'(행정규칙/예규), 'expc'(법령해석례), 'ordin'(지자체 조례)
    - query_filter: (선택사항) target이 'law' 또는 'ordin'일 때 특정 조문 번호나 단어(예: '제6조', '중과')가 포함된 조문만 추출할 때 입력
    """
    print(f"\n[시스템] 📖 원문 정밀 조회 가동: ID '{doc_id}' (대상: {target}, 필터: '{query_filter}')")
    return get_law_content(doc_id, target, query_filter)

def search_exchange_rate_for_gemini(start_date: str, end_date: str, currency: str = "USD") -> str:
    """
    한국은행 ECOS에서 특정 기간의 공식 환율(매매기준율)을 조회합니다.
    - start_date, end_date: 'YYYYMMDD' 형식 (휴일 대비 5~7일 구간 조회 필수)
    - currency: 'USD'(미국 달러), 'JPY'(일본 엔), 'EUR'(유로), 'CNY'(중국 위안)
    """
    print(f"\n[시스템] 💱 한국은행 환율 조회 도구 가동: {currency} ({start_date}~{end_date})")
    return get_bok_exchange_rate(start_date, end_date, currency)

def search_base_rate_for_gemini(start_date: str, end_date: str) -> str:
    """한국은행 ECOS에서 특정 기간('YYYYMMDD' ~ 'YYYYMMDD')의 한국은행 기준금리를 조회합니다."""
    print(f"\n[시스템] 📈 한국은행 기준금리 조회 도구 가동: ({start_date}~{end_date})")
    return get_bok_base_rate(start_date, end_date)

def search_industry_code_for_gemini(keyword: str) -> str:
    """프로젝트 내 마스터 데이터('industry_codes.xlsx')에서 국세청 6자리 기준경비율 업종코드를 검색합니다."""
    print(f"\n[시스템] 🏢 국세청 업종코드 검색 도구 가동: '{keyword}'")
    return search_industry_code(keyword)

def run_tax_calculator_for_gemini(formula_expression: str, description: str = "") -> str:
    """
    세액 계산, 누진세율 구간 계산, 퇴직소득세/양도소득세/법인세 시뮬레이션, 지분율 및 가산세 산출 등
    모든 수학·산술 계산 시 암산 오차를 0%로 만들기 위해 반드시 호출하는 파이썬 정밀 계산기 도구입니다.
    - formula_expression: 실행할 파이썬 수식 문자열 (예: '(500000000 - 200000000) * 0.19 + 200000000 * 0.09')
    - description: 해당 수식이 무엇을 계산하는지 간단한 설명 (예: '법인세 산출세액 계산')
    """
    print(f"\n[시스템] 🧮 파이썬 정밀 세액 계산기 가동: [{description}] 수식: {formula_expression}")
    allowed_names = {
        "abs": abs, "round": round, "min": min, "max": max, "sum": sum, "pow": pow,
        "int": int, "float": float, "math": math
    }
    try:
        clean_expr = formula_expression.strip().replace(",", "")
        result = eval(clean_expr, {"__builtins__": {}}, allowed_names)
        if isinstance(result, (int, float)):
            return f"🧮 [정밀 계산 완료 - {description}]\n- 입력 수식: {clean_expr}\n- 정확한 산출값: {result:,.4f} (정수 반올림: {round(result):,}원)"
        return f"🧮 [정밀 계산 완료 - {description}]\n- 결과: {result}"
    except Exception as e:
        return f"❌ 수식 계산 오류 ({formula_expression}): {e} -> 올바른 파이썬 사칙연산 수식으로 다시 호출하세요."

# 3. 에이전트 시스템 프롬프트 템플릿
SYSTEM_PROMPT = """당신은 세무·법령·회계·노무 검토 자율 전문 에이전트입니다.
앞으로의 질문에 답변할 때는 반드시 먼저 제공된 도구(API)들을 사용하여 실제 원문 데이터와 통계를 확인한 뒤, 아래의 **[자료 검토 기준]**을 엄격히 준수하고, 반드시 **[A. 사전 3줄 크로스체크]**를 먼저 출력한 뒤 **[B. 최종 답변]**을 작성해줘.

[필수 도구 호출 원칙 및 효율성 제한]
- 법령·판례·심판례·예규·지방세조례 확인: 'search_law_for_gemini'(target: 'law', 'prec', 'decc', 'admrul', 'expc', 'ordin')로 ID를 찾은 뒤 'get_law_details_for_gemini'로 실제 원문을 읽을 것.
- 세액·비율·가산세 등 모든 숫자 계산: 절대 머리로 암산하지 말고 반드시 'run_tax_calculator_for_gemini' 도구를 호출하여 단 1원의 오차도 없이 정확히 계산할 것.
- ⚠️ [다수 법령·판례 문서 검토 시 주의]: 첨부된 문서에 이미 법령 조문과 판례 요지가 상세히 수록되어 있는 경우, 모든 조문을 중복 조회하느라 도구 호출 횟수를 소진하지 말고 가장 핵심적인 쟁점 법령·판례·심판례 3~5건만 선별하여 빠르게 실존 및 정합성을 크로스체크한 뒤 즉시 최종 답변을 작성할 것.
- 환율·기준금리 확인: 날짜의 과거/미래 여부를 예단하지 말고 반드시 'search_exchange_rate_for_gemini' 또는 'search_base_rate_for_gemini'를 호출할 것.
- 국세청 업종코드 확인: 업종코드 질문 시 반드시 'search_industry_code_for_gemini'를 호출하여 데이터에서 확인된 6자리 코드만 안내하고, 도구에서 조회되지 않는 코드는 절대 임의로 숫자를 조합해 생성하지 말 것.

1. 자료 검토 우선순위 및 기준
- 1순위 (법령 및 자치법규/행정규칙): 국가법령정보센터 기준 가장 최근 개정된 [법률 / 시행령 / 시행규칙 / 지방세 조례 / 행정규칙(고시·훈령)]을 최우선 기준으로 삼을 것.
- 2순위 (공식 유권해석·판례·조세심판례): [대법원 판례('prec') / 조세심판원 결정례('decc') / 법령해석례('expc') / 세법집행기준·예규]를 대조할 것.
- 3순위 (회계기준 및 공식 통계·업종DB): 한국회계기준원의 [K-IFRS / 일반기업회계기준] 원문 문단, 한국은행 경제통계시스템(ECOS) 공식 환율·금리, 국세청 기준경비율 업종코드 데이터를 참고할 것.
- 4순위 (실무 참고): 전문가 블로그 글은 전산 처리나 실무 흐름 파악용으로만 참고하되, 1~3순위 법령·예규와 충돌하거나 법적 근거가 없는 편법은 절대 채택하지 말 것.

2. 할루시네이션(임의 생성) 금지 규칙
- 확인되지 않은 법조문 번호, 통칙·집행기준 번호, 예규·판례·심판례 번호, 업종코드(6자리), 환율·금리 수치, 깨진 상세 URL을 절대 임의로 추측하거나 조합해 만들어내지 말 것.
- 번호가 정확히 확인되지 않으면 번호를 생략하고 정확한 법리와 원문 검색 키워드만 안내할 것.

3. 필수 출력 양식 (반드시 A → B 순서대로 화면에 출력할 것)

### 🔍 [A. 사전 3줄 크로스체크]
- **1차(쟁점 파악)**: 질문의 핵심 쟁점 및 잘못된 전제 유무 1줄 요약
- **2차(법령·기준 대조)**: 적용할 핵심 법령명·조례·회계기준·업종코드/환율 및 반드시 체크해야 할 단서·예외 요건 1줄 요약
- **3차(예규·심판례·리스크 검증)**: 상충 예규·심판례 유무 및 가산세·실무 신고 시 핵심 주의점 1줄 요약

---

### 📋 [B. 최종 답변]

### 📌 [핵심 결론]
- 위 3줄 검증 결과를 반영하여 질문에 대한 가능/불가능 여부, 적용 세율·업종코드·회계처리 등 핵심 결론을 2~3줄로 명확히 요약

### ⚖️ [상세 법리 및 기준 검토]
- 1~3순위 근거(법령 조문, 단서·예외 요건, 지자체 조례, 회계기준, 예규·판례·조세심판례, 정밀 계산기 산출 내역)를 바탕으로 상세 요건 설명

### 🚨 [실무 적용 및 리스크 유의사항]
- 가산세 리스크, 증빙 수취 요건, 홈택스/위택스 신고·전산 처리(위하고 등) 시 주의할 점 정리

### 🔗 [근거 자료 및 검색 방법]
- 답변 하단에 항상 `[법령/기준명 - 대표 링크주소 - 상세 검색방법(조문 위치·검색 키워드)]` 형식으로 출처 기재 (폐지·오류 방지를 위해 기관 공식 도메인으로 연결)
  * 국가법령정보센터(법령·판례·심판례·조례): https://www.law.go.kr
  * 국세법령정보시스템: https://taxlaw.nts.go.kr
  * 조세심판원: https://www.tt.go.kr
  * 한국은행 경제통계시스템(ECOS): https://ecos.bok.or.kr
  * 한국회계기준원: https://www.kasb.or.kr
  * 국세청 홈택스: https://www.hometax.go.kr
"""

def extract_safe_text(response) -> str:
    """Gemini 응답 객체에서 NoneType 오류 없이 안전하게 텍스트를 추출합니다."""
    if not response:
        return ""
    try:
        if getattr(response, "text", None):
            return response.text
    except Exception:
        pass
    
    extracted_parts = []
    try:
        for cand in getattr(response, "candidates", []) or []:
            content = getattr(cand, "content", None)
            if content:
                for part in getattr(content, "parts", []) or []:
                    if getattr(part, "text", None):
                        extracted_parts.append(part.text)
    except Exception:
        pass
    return "\n".join(extracted_parts).strip()

def _execute_with_key_and_model(api_key: str, model_id: str, user_input: str, dynamic_prompt: str, tools_list: list, safety_settings: list) -> str:
    """특정 API 키와 모델로 세션을 열어 답변 텍스트를 받아옵니다."""
    temp_client = genai.Client(api_key=api_key)
    chat = temp_client.chats.create(
        model=model_id,
        config=types.GenerateContentConfig(
            tools=tools_list,
            temperature=0.2,
            system_instruction=dynamic_prompt,
            safety_settings=safety_settings,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                maximum_remote_calls=14
            )
        )
    )
    response = chat.send_message(user_input)
    final_text = extract_safe_text(response)
    
    if not final_text:
        follow_up = chat.send_message("지금까지 조회한 법령·판례·심판례 데이터와 계산 결과를 바탕으로 즉시 [A. 사전 3줄 크로스체크]와 [B. 최종 답변]을 작성해 주세요.")
        final_text = extract_safe_text(follow_up)
        
    if not final_text:
        raise ValueError("빈 응답이 반환되었습니다.")
    return final_text

# 4. 정교화된 4단계 계단식 방어벽 (무료 Pro 총동원 -> 무료 Flash 총동원 -> 최후 유료 키)
def run_agent(user_input: str, raw_query: str = "", has_file: bool = False) -> str:
    """
    [Pro 필요 시]: 무료키 #1 Pro -> 무료키 #2 Pro -> 무료키 #1 Flash -> 무료키 #2 Flash -> 💳 유료키 Pro -> 💳 유료키 Flash
    [Flash 필요 시]: 무료키 #1 Flash -> 무료키 #2 Flash -> 💳 유료키 Flash
    """
    if not API_KEY_POOL:
        return "❌ 설정된 Gemini API 키가 없습니다. .env 또는 Streamlit Secrets를 확인해 주세요."

    query_for_routing = raw_query if raw_query else user_input
    selected_model, mode_badge = select_optimal_model(
        user_query=query_for_routing,
        has_file=has_file,
        full_input_len=len(user_input)
    )
    
    today_str = datetime.now().strftime("%Y년 %m월 %d일")
    dynamic_prompt = f"[시스템 기준일 안내: 오늘 날짜는 {today_str}입니다. 질문에 등장하는 연도와 날짜의 과거/현재 여부를 반드시 오늘 날짜({today_str}) 기준으로 판단하세요.]\n\n" + SYSTEM_PROMPT
    
    tools_list = [
        search_law_for_gemini, 
        get_law_details_for_gemini,
        search_exchange_rate_for_gemini,
        search_base_rate_for_gemini,
        search_industry_code_for_gemini,
        run_tax_calculator_for_gemini
    ]
    
    safety_settings = [
        types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"),
        types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"),
        types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"),
        types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
    ]

    free_keys = [(lbl, k) for lbl, k in API_KEY_POOL if "유료" not in lbl]
    paid_keys = [(lbl, k) for lbl, k in API_KEY_POOL if "유료" in lbl]

    if not free_keys:
        free_keys = paid_keys
        paid_keys = []

    execution_plan = []

    if selected_model == PRO_MODEL_ID:
        for lbl, k in free_keys:
            execution_plan.append((lbl, k, PRO_MODEL_ID, f"{mode_badge} *(🔑 {lbl} Pro 가동)*"))
        for lbl, k in free_keys:
            execution_plan.append((lbl, k, FLASH_MODEL_ID, f"⚡ **[Flash 무료 방어 모드]** *(🔑 {lbl} - 무료 Pro 소진으로 무료 Flash 우회)*"))
        for lbl, k in paid_keys:
            execution_plan.append((lbl, k, PRO_MODEL_ID, f"{mode_badge} *(🔑 {lbl} 가동)*"))
        for lbl, k in paid_keys:
            execution_plan.append((lbl, k, FLASH_MODEL_ID, f"⚡ **[최후 백업 모드]** *(🔑 {lbl} Flash 가동)*"))
    else:
        for lbl, k in free_keys:
            execution_plan.append((lbl, k, FLASH_MODEL_ID, f"{mode_badge} *(🔑 {lbl} 가동)*"))
        for lbl, k in paid_keys:
            execution_plan.append((lbl, k, FLASH_MODEL_ID, f"{mode_badge} *(🔑 {lbl} 가동)*"))

    last_error = None

    for key_label, current_key, target_model, final_badge in execution_plan:
        print(f"🔄 [라우팅 시도] 키: [{key_label}] | 모델: {target_model}")
        try:
            final_text = _execute_with_key_and_model(
                api_key=current_key,
                model_id=target_model,
                user_input=user_input,
                dynamic_prompt=dynamic_prompt,
                tools_list=tools_list,
                safety_settings=safety_settings
            )
            return f"> {final_badge}\n\n" + final_text
        except Exception as e:
            last_error = e
            print(f"⚠️ [{key_label} | {target_model}] 전환 사유 발생: {e}")
            continue

    error_msg = f"❌ 모든 API 키 및 백업 모델 호출이 실패했습니다. 마지막 오류: {str(last_error)}"
    print(error_msg)
    return error_msg
