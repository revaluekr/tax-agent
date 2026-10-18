import os
import requests

try:
    from config import LAW_OPEN_API_KEY, BOK_API_KEY
except ImportError:
    LAW_OPEN_API_KEY = os.getenv("LAW_OPEN_API_KEY")
    BOK_API_KEY = os.getenv("BOK_API_KEY")

# ---------------------------------------------------------
# 1. 법제처 국가법령정보센터 API 함수
# ---------------------------------------------------------
SEARCH_URL = "https://www.law.go.kr/DRF/lawSearch.do"
SERVICE_URL = "https://www.law.go.kr/DRF/lawService.do"

def search_law_data(keyword: str, target: str = "law"):
    """키워드로 법령, 판례, 행정규칙, 법령해석례 목록을 검색합니다."""
    params = {
        "OC": LAW_OPEN_API_KEY,
        "target": target,
        "type": "JSON",
        "query": keyword
    }
    try:
        response = requests.get(SEARCH_URL, params=params)
        response.raise_for_status()
        data = response.json()
        if "LawSearch" in data and target in data["LawSearch"]:
            return data["LawSearch"][target]
        return []
    except Exception as e:
        print(f"❌ 법령 검색 오류: {e}")
        return []

def get_law_content(law_id: str):
    """법령 일련번호(MST)를 이용해 법령 원문 데이터를 가져옵니다."""
    params = {
        "OC": LAW_OPEN_API_KEY,
        "target": "law",
        "type": "JSON",
        "MST": law_id
    }
    try:
        response = requests.get(SERVICE_URL, params=params)
        response.raise_for_status()
        data = response.json()
        if "법령" in data:
            law_info = data["법령"].get("기본정보", {})
            return f"법령명: {law_info.get('법령명_한글')}, 공포일자: {law_info.get('공포일자')}, 시행일자: {law_info.get('시행일자')}"
        return "법령 상세 내용을 불러올 수 없습니다."
    except Exception as e:
        return f"❌ 본문 조회 오류: {e}"

# ---------------------------------------------------------
# 2. 한국은행 경제통계시스템(ECOS) API 함수 (환율 & 기준금리)
# ---------------------------------------------------------
def get_bok_exchange_rate(start_date: str, end_date: str, currency: str = "USD") -> str:
    """
    한국은행 ECOS API를 통해 특정 기간(YYYYMMDD ~ YYYYMMDD)의 주요 통화 매매기준율을 조회합니다.
    - currency: 'USD'(미국 달러), 'JPY'(일본 100엔), 'EUR'(유로), 'CNY'(중국 위안)
    """
    if not BOK_API_KEY:
        return "❌ 한국은행 API 키(BOK_API_KEY)가 설정되지 않았습니다."
    
    # 한국은행 통계표코드 731Y001 (주요국 통화의 대원화환율) 아이템 매핑
    item_map = {
        "USD": "0000001",  # 원/미국달러(매매기준율)
        "JPY": "0000002",  # 원/일본엔(100엔)
        "EUR": "0000003",  # 원/유로
        "CNY": "0000053"   # 원/위안
    }
    item_code = item_map.get(currency.upper(), "0000001")
    
    # URL 구조: /StatisticSearch/인증키/json/kr/1/30/731Y001/D/시작일/종료일/항목코드
    url = f"https://ecos.bok.or.kr/api/StatisticSearch/{BOK_API_KEY}/json/kr/1/30/731Y001/D/{start_date}/{end_date}/{item_code}"
    
    try:
        response = requests.get(url)
        data = response.json()
        if "StatisticSearch" in data and "row" in data["StatisticSearch"]:
            rows = data["StatisticSearch"]["row"]
            result_str = f"[{currency.upper()} 매매기준율 조회 결과 ({start_date}~{end_date})]\n"
            for r in rows:
                result_str += f"- 일자: {r.get('TIME')} | 환율: {r.get('DATA_VALUE')}원 ({r.get('ITEM_NAME1')})\n"
            return result_str
        else:
            msg = data.get("RESULT", {}).get("MESSAGE", "해당 일자의 고시 환율 데이터가 없습니다(휴일인 경우 직전 영업일 조회 필요).")
            return f"조회 결과 없음: {msg}"
    except Exception as e:
        return f"❌ 한국은행 환율 조회 오류: {e}"

def get_bok_base_rate(start_date: str, end_date: str) -> str:
    """
    한국은행 ECOS API를 통해 특정 기간(YYYYMMDD ~ YYYYMMDD)의 한국은행 기준금리를 조회합니다.
    """
    if not BOK_API_KEY:
        return "❌ 한국은행 API 키(BOK_API_KEY)가 설정되지 않았습니다."
    
    # 통계표코드 722Y001 (한국은행 기준금리 및 여수신금리), 항목코드 0101000 (한국은행 기준금리)
    url = f"https://ecos.bok.or.kr/api/StatisticSearch/{BOK_API_KEY}/json/kr/1/30/722Y001/D/{start_date}/{end_date}/0101000"
    
    try:
        response = requests.get(url)
        data = response.json()
        if "StatisticSearch" in data and "row" in data["StatisticSearch"]:
            rows = data["StatisticSearch"]["row"]
            result_str = f"[한국은행 기준금리 조회 결과 ({start_date}~{end_date})]\n"
            for r in rows[-10:]:  # 최근 10건 요약
                result_str += f"- 일자: {r.get('TIME')} | 기준금리: 연 {r.get('DATA_VALUE')}%\n"
            return result_str
        else:
            return "해당 기간의 기준금리 데이터가 없습니다."
    except Exception as e:
        return f"❌ 한국은행 기준금리 조회 오류: {e}"
