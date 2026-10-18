import os
import requests
try:
    from config import LAW_OPEN_API_KEY
except ImportError:
    LAW_OPEN_API_KEY = os.getenv("LAW_OPEN_API_KEY")

SEARCH_URL = "https://www.law.go.kr/DRF/lawSearch.do"
SERVICE_URL = "https://www.law.go.kr/DRF/lawService.do"

def search_law_data(keyword: str, target: str = "law"):
    """키워드로 법령, 판례 목록을 검색합니다."""
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
        print(f"❌ 검색 오류: {e}")
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
            law_name = law_info.get("법령명_한글", "")
            return f"[{law_name}] 법령 원문 데이터 조회 성공 (일련번호: {law_id})"
        return "법령 본문 정보를 가져올 수 없습니다."
    except Exception as e:
        return f"본문 조회 중 오류 발생: {e}"
