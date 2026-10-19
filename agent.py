import os
import re
import math
from datetime import datetime
from zoneinfo import ZoneInfo
import streamlit as st
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

def _get_secret_or_env(key_name: str) -> str:
    """Streamlit Cloud의 st.secrets와 로컬 .env 양쪽에서 실시간으로 키를 읽어옵니다."""
    try:
        if hasattr(st, "secrets") and key_name in st.secrets:
            val = str(st.secrets[key_name]).strip().strip('"').strip("'")
            if val:
                return val
    except Exception:
        pass
    return os.getenv(key_name, "").strip().strip('"').strip("'")

def get_live_gemini_key_pool() -> list[tuple[str, str]]:
    """무료키 1~5번을 최우선으로 배열하고 유료 예비키를 맨 마지막에 배치합니다."""
    pool = []
    seen = set()

    for i in range(1, 6):
        k = _get_secret_or_env(f"GEMINI_FREE_KEY_{i}")
        if k and k not in seen:
            pool.append((f"무료키 #{i}", k))
            seen.add(k)

    for env_name in ["GEMINI_PAID_KEY", "GEMINI_API_KEY"]:
        k = _get_secret_or_env(env_name)
        if k and k not in seen:
            lbl = "💳 유료 예비키(최후 방어벽)" if pool else "기본키(단독)"
            pool.append((lbl, k))
            seen.add(k)

    return pool

import law_api

# ---------------------------------------------------------
# ✨ 법리 왜곡 0% 스마트 법령 텍스트 압축기 (토큰 50% 추가 절감)
# ---------------------------------------------------------
def compress_legal_text(raw_text: str, query_filter: str = "") -> str:
    """
    법령·판례 원문에서 법리 해석과 무관한 개정 연혁 태그(<개정 ...>), 중복 공백,
    타 조문 단순 인용구 등을 제거하여 단서·예외 규정 왜곡 없이 토큰만 최소화합니다.
    """
    if not raw_text:
        return ""

    # 1) 불필요한 개정/신설 연혁 꼬리표 제거 (예: <개정 2020. 12. 29., 2022. 12. 31.>, [전문개정 ...])
    cleaned = re.sub(r"<(개정|신설|타법개정|일부개정|전문개정)[^>]*>", "", raw_text)
    cleaned = re.sub(r"\[(전문개정|본조신설|제목개정|제\d+조에서 이동)[^\]]*\]", "", cleaned)

    # 2) 만약 특정 조문번호(예: '제29조의8', '제26조')로 필터링한 경우,
    #    해당 조문으로 시작하는 '진짜 본조문' 블록을 최우선 배치하고 단순 언급 조문은 뒤로 밀어냄
    qf = query_filter.strip().replace(" ", "")
    if qf.startswith("제") and "조" in qf:
        blocks = cleaned.split("\n\n")
        header = blocks[0] if blocks else ""
        exact_articles = []
        other_mentions = []

        for blk in blocks[1:]:
            blk_clean = blk.strip().replace(" ", "")
            # '제29조의8(' 또는 '제29조의8 ' 형태로 시작하는 실제 해당 조문인지 판별
            if blk_clean.startswith(qf + "(") or blk_clean.startswith(qf + " ") or blk_clean == qf:
                exact_articles.append(blk.strip())
            else:
                other_mentions.append(blk.strip())

        if exact_articles:
            # 진짜 타깃 조문이 있으면 그 조문 전체(1항~끝항, 단서 포함)를 온전히 보존
            cleaned = header + "\n\n" + "\n\n".join(exact_articles)
        else:
            cleaned = header + "\n\n" + "\n\n".join(other_mentions[:3])

    # 3) 연속된 빈 줄 및 불필요한 공백 압축
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    # 4) 단일 조문 전체가 잘리지 않도록 3,500자(순수 조문 기준 매우 넉넉한 분량)까지 허용
    return cleaned[:3500]


# 1. 모델 설정 (2026-09-18부터 2.5 계열은 신규 프로젝트에서 404 → 3.x로 전환)
#    Secrets/.env에 같은 이름의 키를 넣으면 코드 수정 없이 모델명을 바꿀 수 있습니다.
def _model_id(env_key: str, default: str) -> str:
    return _get_secret_or_env(env_key) or default

FREE_TIER_FLASH_ID = _model_id("GEMINI_FREE_MODEL", "gemini-3.8-flash")           # 무료 등급 지원
FREE_TIER_MID_ID   = _model_id("GEMINI_FREE_MID_MODEL", "gemini-3.6-flash")        # 3.8 과부하(503) 시 차선
FREE_TIER_LITE_ID  = _model_id("GEMINI_FREE_LITE_MODEL", "gemini-3.5-flash-lite") # 무료 예비(별도 쿼터)
PAID_TIER_FLASH_ID = _model_id("GEMINI_PAID_FLASH_MODEL", "gemini-3.8-flash")
# Pro급은 무료 등급 미지원 → 유료키 전용. 첫 번째가 실패하면 두 번째로 넘어갑니다.
PAID_PRO_MODEL_IDS = [
    _model_id("GEMINI_PAID_PRO_MODEL", "gemini-3.1-pro-preview"),
    "gemini-4-argon",
]

def _is_model_not_found(e: Exception) -> bool:
    s = str(e)
    return ("404" in s or "NOT_FOUND" in s) and "model" in s.lower()

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
            return "PRO", f"🧠 **[Pro 심층 모드]** 사용자 지정 정밀 검토 ({trigger})"

    if has_file and full_input_len >= 15000:
        return "PRO", f"🧠 **[Pro 심층 모드 자동 전환]** 대용량 문서({full_input_len:,}자) 정밀 분석"

    matched_deep = [kw for kw in DEEP_KEYWORDS if kw in user_query]
    if len(matched_deep) >= 2:
        return "PRO", f"🧠 **[Pro 심층 모드 자동 전환]** 복합 고난도 쟁점 감지 ({', '.join(matched_deep[:3])})"

    matched_calc = [kw for kw in CALC_KEYWORDS if kw in user_query]
    if len(user_query.strip()) >= 500 and len(matched_calc) >= 1:
        return "PRO", "🧠 **[Pro 심층 모드 자동 전환]** 초장문 복합 시뮬레이션 감지"

    return "FLASH", "⚡ **[Flash 빠른 검토 모드]** 실무 표준 검토 (토큰 절약 모드)"

# 2. Gemini 도구 정의
def search_law_for_gemini(keyword: str, target: str = "law") -> str:
    """
    국가법령정보센터에서 법령, 판례, 행정규칙, 법령해석례, 조세심판원 재결례, 지방세 자치법규(조례) 목록과 일련번호(ID)를 검색합니다.
    - target: 'law'(법령), 'prec'(판례), 'decc'(조세심판원 결정례), 'admrul'(훈령·예규·고시), 'expc'(법령해석례), 'ordin'(지자체 조례)
    """
    print(f"\n[시스템] 💡 목록 검색 도구 가동: '{keyword}' (대상: {target})")
    results = law_api.search_law_data(keyword, target)
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
    검색된 일련번호(ID)로 원문을 조회합니다. 법령('law') 조회 시 반드시 query_filter에 조문번호(예: '제29조의8', '제26조')나 핵심 단어를 넣어 호출하세요.
    """
    print(f"\n[시스템] 📖 원문 정밀 조회 가동: ID '{doc_id}' (대상: {target}, 필터: '{query_filter}')")
    raw_text = law_api.get_law_content(doc_id, target, query_filter)
    # 법리 왜곡 없이 개정 연혁 태그와 타 조문 군더더기만 제거하여 토큰 50% 절감
    return compress_legal_text(raw_text, query_filter)

def search_exchange_rate_for_gemini(start_date: str, end_date: str, currency: str = "USD") -> str:
    """한국은행 ECOS에서 특정 기간의 공식 환율(매매기준율)을 조회합니다."""
    print(f"\n[시스템] 💱 한국은행 환율 조회 도구 가동: {currency} ({start_date}~{end_date})")
    return law_api.get_bok_exchange_rate(start_date, end_date, currency)

def search_base_rate_for_gemini(start_date: str, end_date: str) -> str:
    """한국은행 ECOS에서 특정 기간('YYYYMMDD' ~ 'YYYYMMDD')의 한국은행 기준금리를 조회합니다."""
    print(f"\n[시스템] 📈 한국은행 기준금리 조회 도구 가동: ({start_date}~{end_date})")
    return law_api.get_bok_base_rate(start_date, end_date)

def search_industry_code_for_gemini(keyword: str) -> str:
    """프로젝트 내 마스터 데이터('industry_codes.xlsx')에서 국세청 6자리 기준경비율 업종코드를 검색합니다."""
    print(f"\n[시스템] 🏢 국세청 업종코드 검색 도구 가동: '{keyword}'")
    return law_api.search_industry_code(keyword)

def search_dart_corp_for_gemini(corp_name: str, bsns_year: str = "2025") -> str:
    """금융감독원 전자공시시스템(Open DART)에서 특정 기업의 6대 핵심 정보를 통합 조회합니다."""
    print(f"\n[시스템] 📊 DART 전자공시 통합 조회 가동: '{corp_name}' ({bsns_year}년)")
    return law_api.get_dart_corp_info(corp_name, bsns_year)[:4000]

def check_nts_biz_status_for_gemini(biz_numbers: str) -> str:
    """국세청 API를 통해 사업자등록번호(10자리)의 납세자 상태(계속/휴폐업) 및 과세유형을 실시간 조회합니다."""
    print(f"\n[시스템] 🔎 국세청 사업자등록 상태·과세유형 실시간 조회 가동: '{biz_numbers}'")
    return law_api.get_nts_biz_status(biz_numbers)

def verify_nts_biz_info_for_gemini(b_no: str, start_dt: str, p_nm: str, b_nm: str = "") -> str:
    """국세청 API를 통해 사업자등록번호(10자리) + 개업일자(YYYYMMDD) + 대표자 성명의 진위확인을 수행합니다."""
    print(f"\n[시스템] 🛡️ 국세청 사업자등록 진위확인 가동: {b_no} | {start_dt} | {p_nm}")
    if hasattr(law_api, "verify_nts_biz_info"):
        return law_api.verify_nts_biz_info(b_no, start_dt, p_nm, b_nm)
    return "현재 law_api.py에 진위확인 함수가 없습니다."

def search_real_estate_trade_for_gemini(property_type: str, region: str, deal_ymd: str, filter_keyword: str = "") -> str:
    """국토교통부 부동산 매매 실거래가 4종(아파트 'apt', 오피스텔 'offi', 상가 'comm', 토지 'land')을 조회합니다."""
    print(f"\n[시스템] 🏘️ 국토교통부 부동산 실거래가 조회 가동: 유형={property_type} | 지역={region} | 연월={deal_ymd} | 필터='{filter_keyword}'")
    if hasattr(law_api, "get_molit_real_estate_trade"):
        return law_api.get_molit_real_estate_trade(property_type, region, deal_ymd, filter_keyword)
    return "현재 law_api.py에 부동산 실거래가 조회 함수가 없습니다."

def run_tax_calculator_for_gemini(formula_expression: str, description: str = "") -> str:
    """세액 계산, 누진세율 구간 계산, 양도세/증여세/상속세/공제액 시뮬레이션 등 모든 수학 계산 시 호출하는 파이썬 정밀 계산기입니다."""
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

[필수 도구 호출 원칙 및 초고속 핀셋 규칙]
- ⚡ **[초고속 핵심 핀셋 조회 원칙]**: 도구 호출은 질문당 **최대 2~4회 이내**로 가장 핵심적인 법령 조문(query_filter에 반드시 '제29조의8'처럼 조문번호 입력)과 계산기만 핀셋 호출하고 즉시 최종 답변을 작성할 것!
- 법령·판례·심판례·예규·지방세조례 확인: 'search_law_for_gemini'로 ID를 찾은 뒤 'get_law_details_for_gemini'(반드시 query_filter에 조문번호 입력)로 핵심 조문만 읽을 것.
- 기업 공시·재무·지분·배당·출자 확인: 'search_dart_corp_for_gemini' 호출.
- 사업자 상태(휴·폐업/과세유형) 및 진위확인: 'check_nts_biz_status_for_gemini' 또는 'verify_nts_biz_info_for_gemini' 호출.
- 부동산(아파트·오피스텔·상가·토지) 실거래가 확인: 'search_real_estate_trade_for_gemini' 호출.
- 세액·공제액·지분율 등 모든 숫자 계산: 반드시 'run_tax_calculator_for_gemini'를 호출하여 단 1원의 오차도 없이 정확히 계산할 것.

1. 자료 검토 우선순위 및 기준
- 1순위 (법령 및 자치법규/행정규칙): 국가법령정보센터 기준 가장 최근 개정된 [법률 / 시행령 / 시행규칙 / 지방세 조례 / 행정규칙(고시·훈령)]을 최우선 기준으로 삼을 것.
- 2순위 (공식 유권해석·판례·조세심판례): [대법원 판례('prec') / 조세심판원 결정례('decc') / 법령해석례('expc') / 세법집행기준·예규]를 대조할 것.
- 3순위 (회계기준·DART 전자공시·국세청·국토부·한국은행·업종DB): 한국회계기준원, 금융감독원(DART), 국세청 사업자 상태/진위확인, 국토교통부 실거래가, 한국은행(ECOS) 공식 환율·금리, 국세청 업종코드 데이터를 참고할 것.
- 4순위 (실무 참고): 전문가 블로그 글은 전산 처리나 실무 흐름 파악용으로만 참고하되, 1~3순위 법령·예규와 충돌하거나 법적 근거가 없는 편법은 절대 채택하지 말 것.

2. 할루시네이션(임의 생성) 금지 규칙
- 확인되지 않은 법조문 번호, 통칙·집행기준 번호, 예규·판례·심판례 번호, 업종코드(6자리), 환율·금리·재무제표·지분율·실거래가 수치, 깨진 상세 URL을 절대 임의로 추측하거나 조합해 만들어내지 말 것.

3. 필수 출력 양식 (반드시 A → B 순서대로 화면에 출력할 것)

### 🔍 [A. 사전 3줄 크로스체크]
- **1차(쟁점 파악)**: 질문의 핵심 쟁점 및 잘못된 전제 유무 1줄 요약
- **2차(법령·기준·공시·실거래 대조)**: 적용할 핵심 법령명·조례·회계기준·DART 공시·사업자 과세유형·부동산 실거래가/업종코드/환율 및 단서·예외 요건 1줄 요약
- **3차(예규·심판례·리스크 검증)**: 상충 예규·심판례 유무 및 가산세·매입세액 불공제·사후관리 등 실무 신고 시 핵심 주의점 1줄 요약

---

### 📋 [B. 최종 답변]

### 📌 [핵심 결론]
- 위 3줄 검증 결과를 반영하여 질문에 대한 가능/불가능 여부, 적용 세율·세액공제액·과세유형·업종코드·회계처리 등 핵심 결론을 2~3줄로 명확히 요약

### ⚖️ [상세 법리 및 기준 검토]
- 1~3순위 근거(법령 조문, 단서·예외 요건, 지자체 조례, 회계기준, 각 기관 API 조회 데이터, 예규·판례·조세심판례, 정밀 계산기 산출 내역)를 바탕으로 상세 요건 설명

### 🚨 [실무 적용 및 리스크 유의사항]
- 가산세 및 사후관리(고용감소 추징 등) 리스크, 최저한세 적용 여부, 중복공제 배제 여부, 증빙 수취 요건, 홈택스/위택스 신고 시 주의할 점 정리

### 🔗 [근거 자료 및 검색 방법]
- 답변 하단에 항상 `[법령/기준명 - 대표 링크주소 - 상세 검색방법(조문 위치·검색 키워드)]` 형식으로 출처 기재
  * 국가법령정보센터(법령·판례·심판례·조례): https://www.law.go.kr
  * 국세법령정보시스템: https://taxlaw.nts.go.kr
  * 금융감독원 전자공시시스템(DART): https://dart.fss.or.kr
  * 국토교통부 실거래가 공개시스템: https://rt.molit.go.kr
  * 한국은행 경제통계시스템(ECOS): https://ecos.bok.or.kr
  * 국세청 홈택스(사업자상태/업종코드): https://www.hometax.go.kr
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
    """특정 API 키와 모델로 세션을 열어 답변을 받아옵니다."""
    try:
        # 타임아웃 단위는 밀리초(60초). Pro 모델·다중 도구 호출 시 20초는 부족할 수 있음
        temp_client = genai.Client(api_key=api_key, http_options={"timeout": 60000})
    except Exception:
        temp_client = genai.Client(api_key=api_key)

    chat = temp_client.chats.create(
        model=model_id,
        config=types.GenerateContentConfig(
            tools=tools_list,
            # temperature=0.2,  # 2026-07-21 deprecated → 제거
            system_instruction=dynamic_prompt,
            safety_settings=safety_settings,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                maximum_remote_calls=5
            )
        )
    )
    response = chat.send_message(user_input)
    final_text = extract_safe_text(response)

    if not final_text:
        follow_up = chat.send_message("지금까지 조회한 법령 조문과 계산 결과를 바탕으로 추가 도구 호출 없이 즉시 [A. 사전 3줄 크로스체크]와 [B. 최종 답변]을 작성해 주세요.")
        final_text = extract_safe_text(follow_up)

    if not final_text:
        raise ValueError("빈 응답이 반환되었습니다.")
    return final_text

# 4. 실행 순서: 무료 3.8-flash → 무료 3.6-flash → 무료 3.5-flash-lite → 유료 (PRO 모드는 유료 Pro 우선)
def run_agent(user_input: str, raw_query: str = "", has_file: bool = False) -> str:
    live_pool = get_live_gemini_key_pool()
    if not live_pool:
        return "❌ 설정된 Gemini API 키가 없습니다. .env 또는 Streamlit Secrets를 확인해 주세요."

    query_for_routing = raw_query if raw_query else user_input
    tier_mode, mode_badge = select_optimal_model(
        user_query=query_for_routing,
        has_file=has_file,
        full_input_len=len(user_input)
    )

    # Streamlit Cloud 서버는 UTC이므로 한국 시간 기준으로 오늘 날짜 계산
    today_str = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y년 %m월 %d일")
    dynamic_prompt = f"[시스템 기준일 안내: 오늘 날짜는 {today_str}입니다. 질문에 등장하는 연도와 날짜의 과거/현재 여부를 반드시 오늘 날짜({today_str}) 기준으로 판단하세요.]\n\n" + SYSTEM_PROMPT

    tools_list = [
        search_law_for_gemini,
        get_law_details_for_gemini,
        search_exchange_rate_for_gemini,
        search_base_rate_for_gemini,
        search_industry_code_for_gemini,
        search_dart_corp_for_gemini,
        check_nts_biz_status_for_gemini,
        verify_nts_biz_info_for_gemini,
        search_real_estate_trade_for_gemini,
        run_tax_calculator_for_gemini
    ]

    safety_settings = [
        types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"),
        types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"),
        types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"),
        types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
    ]

    free_keys = [(lbl, k) for lbl, k in live_pool if "무료" in lbl]
    paid_keys = [(lbl, k) for lbl, k in live_pool if "무료" not in lbl]

    execution_plan = []

    if tier_mode == "PRO":
        # 무료 Pro가 없으므로: 유료 Pro → 무료 Flash → 유료 Flash
        for lbl, k in paid_keys:
            for m in PAID_PRO_MODEL_IDS:
                execution_plan.append((lbl, k, m, f"{mode_badge} *(🔑 {lbl} · {m})*"))
        for lbl, k in free_keys:
            execution_plan.append((lbl, k, FREE_TIER_FLASH_ID, f"⚡ **[Flash 무료 방어 모드]** *(🔑 {lbl} 가동)*"))
        for lbl, k in paid_keys:
            execution_plan.append((lbl, k, PAID_TIER_FLASH_ID, f"⚡ **[최후 백업 모드]** *(🔑 {lbl} Flash 가동)*"))
    else:
        # 무료 3.8-flash → 무료 3.6-flash → 무료 3.5-flash-lite (각각 전 키) → 유료 3.8-flash
        for m in (FREE_TIER_FLASH_ID, FREE_TIER_MID_ID, FREE_TIER_LITE_ID):
            for lbl, k in free_keys:
                execution_plan.append((lbl, k, m, f"{mode_badge} *(🔑 {lbl} · {m})*"))
        for lbl, k in paid_keys:
            execution_plan.append((lbl, k, PAID_TIER_FLASH_ID, f"{mode_badge} *(🔑 {lbl} 가동)*"))

    last_error = None
    diag_notes = []
    dead_models = set()  # 404 난 모델은 다른 키로 재시도하지 않음

    for key_label, current_key, target_model, final_badge in execution_plan:
        if target_model in dead_models:
            continue
        try:
            final_text = _execute_with_key_and_model(
                api_key=current_key,
                model_id=target_model,
                user_input=user_input,
                dynamic_prompt=dynamic_prompt,
                tools_list=tools_list,
                safety_settings=safety_settings
            )
            diag_header = f"> {final_badge}\n"
            if diag_notes:
                diag_header += f"> *(ℹ️ 앞선 시도 실패: {' | '.join(diag_notes[:2])})*\n"
            return diag_header + "\n" + final_text
        except Exception as e:
            if _is_model_not_found(e):
                dead_models.add(target_model)
            err_short = str(e).splitlines()[0][:90]
            diag_notes.append(f"{key_label}({target_model}): {err_short}")
            last_error = e
            continue

    return f"❌ 모든 API 키 호출이 실패했습니다. 마지막 오류: {str(last_error)}"
