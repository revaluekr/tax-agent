import os
import requests

try:
    from config import LAW_OPEN_API_KEY, BOK_API_KEY
except ImportError:
    LAW_OPEN_API_KEY = os.getenv("LAW_OPEN_API_KEY")
    BOK_API_KEY = os.getenv("BOK_API_KEY")

# ---------------------------------------------------------
# 1. 법제처 국가법령정보센터 API 함수 (목록 검색 + 본문 정밀 조회)
# ---------------------------------------------------------
SEARCH_URL = "https://www.law.go.kr/DRF/lawSearch.do"
SERVICE_URL = "https://www.law.go.kr/DRF/lawService.do"

def search_law_data(keyword: str, target: str = "law"):
    """키워드로 법령(law), 판례(prec), 행정규칙(admrul), 법령해석례(expc) 목록을 검색합니다."""
    params = {
        "OC": LAW_OPEN_API_KEY,
        "target": target,
        "type": "JSON",
        "query": keyword
    }
    try:
        response = requests.get(SEARCH_URL, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        # 검색 대상별 JSON 루트 키 매핑
        root_keys = {
            "law": "LawSearch",
            "prec": "PrecSearch",
            "admrul": "AdmRulSearch",
            "expc": "Expc"
        }
        root_key = root_keys.get(target, "LawSearch")
        
        if root_key in data and target in data[root_key]:
            return data[root_key][target]
        elif "LawSearch" in data and target in data["LawSearch"]:
            return data["LawSearch"][target]
        return []
    except Exception as e:
        print(f"❌ 법령 검색 오류 ({target}): {e}")
        return []

def get_law_content(doc_id: str, target: str = "law", query_filter: str = "") -> str:
    """
    일련번호(ID)를 이용해 법령 조문, 판례 요지, 행정규칙(예규/고시), 법령해석례의 실제 본문을 가져옵니다.
    - doc_id: 검색 목록에서 확인한 일련번호
    - target: 'law'(법령), 'prec'(판례), 'admrul'(행정규칙/예규), 'expc'(법령해석례)
    - query_filter: 법령 본문 내 특정 키워드(예: '업무용승용차', '제27조')만 발췌하고 싶을 때 입력
    """
    params = {
        "OC": LAW_OPEN_API_KEY,
        "target": target,
        "type": "JSON"
    }
    if target == "law":
        params["MST"] = doc_id
    else:
        params["ID"] = doc_id

    try:
        response = requests.get(SERVICE_URL, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()

        # 1) 현행 법령(law) 조문 텍스트 추출
        if target == "law" and "법령" in data:
            law_data = data["법령"]
            info = law_data.get("기본정보", {})
            header = f"📘 [법령명]: {info.get('법령명_한글')} (시행일자: {info.get('시행일자')})\n"
            
            articles = law_data.get("조문", {}).get("조문단위", [])
            if isinstance(articles, dict):
                articles = [articles]
                
            extracted = []
            for art in articles:
                art_content = str(art.get("조문내용", "")).strip()
                # 항/호/목 세부 내용 결합
                hangs = art.get("항", [])
                if isinstance(hangs, dict):
                    hangs = [hangs]
                for h in hangs:
                    h_text = str(h.get("항내용", "")).strip()
                    if h_text:
                        art_content += f"\n  {h_text}"
                    hos = h.get("호", [])
                    if isinstance(hos, dict):
                        hos = [hos]
                    for ho in hos:
                        ho_text = str(ho.get("호내용", "")).strip()
                        if ho_text:
                            art_content += f"\n    {ho_text}"
                
                # 키워드 필터가 있으면 해당 키워드가 포함된 조문만 추출
                if not query_filter or (query_filter in art_content):
                    if art_content:
                        extracted.append(art_content)
            
            if not extracted and query_filter:
                return header + f"'{query_filter}' 키워드가 포함된 조문을 찾지 못했습니다. 키워드 없이 다시 조회하거나 다른 키워드를 입력해 보세요."
            
            body = "\n\n".join(extracted[:15])  # 토큰 초과 방지를 위해 핵심 조문 최대 15개 반환
            return (header + "\n" + body)[:10000]

        # 2) 대법원 등 판례(prec) 본문 추출
        elif target == "prec" and "PrecService" in data:
            p = data["PrecService"]
            return (
                f"⚖️ [사건명]: {p.get('사건명')} ({p.get('사건번호')}, 선고일: {p.get('선고일자')})\n"
                f"■ [판시사항]:\n{p.get('판시사항')}\n\n"
                f"■ [판결요지]:\n{p.get('판결요지')}\n\n"
                f"■ [참조조문]: {p.get('참조조문')}"
            )[:10000]

        # 3) 국세청 예규·훈령·고시 등 행정규칙(admrul) 본문 추출
        elif target == "admrul" and "AdmRulService" in data:
            a = data["AdmRulService"]
            info = a.get("행정규칙기본정보", {})
            body = a.get("조문내용", "")
            return (
                f"📜 [행정규칙/예규명]: {info.get('행정규칙명')} (발령일: {info.get('발령일자')}, 소관: {info.get('소관부처명')})\n"
                f"■ [본문 내용]:\n{body}"
            )[:10000]

        # 4) 법령해석례(expc) 본문 추출
        elif target == "expc" and "ExpcService" in data:
            e = data["ExpcService"]
            return (
                f"🔍 [안건명]: {e.get('안건명')} ({e.get('안건번호')}, 회신일: {e.get('회신일자')})\n"
                f"■ [질의요지]:\n{e.get('질의요지')}\n\n"
                f"■ [회답]:\n{e.get('회답')}\n\n"
                f"■ [이유]:\n{e.get('이유')}"
            )[:10000]

        return "상세 본문 데이터를 불러올 수 없습니다."
    except Exception as e:
        return f"❌ 본문 상세 조회 오류: {e}"

# ---------------------------------------------------------
# 2. 한국은행 경제통계시스템(ECOS) API 함수 (환율 & 기준금리)
# ---------------------------------------------------------
def get_bok_exchange_rate(start_date: str, end_date: str, currency: str = "USD") -> str:
    """한국은행 ECOS API를 통해 특정 기간(YYYYMMDD ~ YYYYMMDD)의 주요 통화 매매기준율을 조회합니다."""
    if not BOK_API_KEY:
        return "❌ 한국은행 API 키(BOK_API_KEY)가 설정되지 않았습니다."
    
    item_map = {
        "USD": "0000001",  # 원/미국달러(매매기준율)
        "JPY": "0000002",  # 원/일본엔(100엔)
        "EUR": "0000003",  # 원/유로
        "CNY": "0000053"   # 원/위안
    }
    item_code = item_map.get(currency.upper(), "0000001")
    url = f"https://ecos.bok.or.kr/api/StatisticSearch/{BOK_API_KEY}/json/kr/1/30/731Y001/D/{start_date}/{end_date}/{item_code}"
    
    try:
        response = requests.get(url, timeout=10)
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
    """한국은행 ECOS API를 통해 특정 기간(YYYYMMDD ~ YYYYMMDD)의 한국은행 기준금리를 조회합니다."""
    if not BOK_API_KEY:
        return "❌ 한국은행 API 키(BOK_API_KEY)가 설정되지 않았습니다."
    
    url = f"https://ecos.bok.or.kr/api/StatisticSearch/{BOK_API_KEY}/json/kr/1/30/722Y001/D/{start_date}/{end_date}/0101000"
    
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        if "StatisticSearch" in data and "row" in data["StatisticSearch"]:
            rows = data["StatisticSearch"]["row"]
            result_str = f"[한국은행 기준금리 조회 결과 ({start_date}~{end_date})]\n"
            for r in rows[-10:]:
                result_str += f"- 일자: {r.get('TIME')} | 기준금리: 연 {r.get('DATA_VALUE')}%\n"
            return result_str
        else:
            return "해당 기간의 기준금리 데이터가 없습니다."
    except Exception as e:
        return f"❌ 한국은행 기준금리 조회 오류: {e}"
