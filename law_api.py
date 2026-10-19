import os
import io
import re
import zipfile
import urllib.parse
import requests
import xml.etree.ElementTree as ET
import pandas as pd

try:
    from config import LAW_OPEN_API_KEY, BOK_API_KEY, DART_API_KEY, NTS_API_KEY
except ImportError:
    LAW_OPEN_API_KEY = os.getenv("LAW_OPEN_API_KEY", "").strip()
    BOK_API_KEY = os.getenv("BOK_API_KEY", "").strip()
    DART_API_KEY = os.getenv("DART_API_KEY", "").strip()
    NTS_API_KEY = os.getenv("NTS_API_KEY", "").strip()

# ---------------------------------------------------------
# 1. 국가법령정보센터 (법령, 판례, 행정규칙, 법령해석례, 조세심판원 재결례, 지자체 조례)
# ---------------------------------------------------------
def search_law_data(keyword: str, target: str = "law") -> list[dict]:
    if not LAW_OPEN_API_KEY:
        return []

    url = "http://www.law.go.kr/DRF/lawSearch.do"
    params = {
        "OC": LAW_OPEN_API_KEY,
        "target": target,
        "type": "XML",
        "query": keyword,
        "display": 10
    }

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.encoding = "utf-8"
        if resp.status_code != 200:
            return []

        root = ET.fromstring(resp.text)
        
        tag_map = {
            "law": "law",
            "prec": "prec",
            "admrul": "admrul",
            "expc": "expc",
            "decc": "decc",
            "ordin": "law"
        }
        item_tag = tag_map.get(target, target)
        items = root.findall(f".//{item_tag}")
        if not items and target == "ordin":
            items = root.findall(".//ordin")

        results = []
        for item in items:
            row = {}
            for child in item:
                row[child.tag] = (child.text or "").strip()
            if row:
                results.append(row)
        return results
    except Exception as e:
        print(f"⚠️ 법제처 목록 검색 오류 ({target}): {e}")
        return []


def get_law_content(doc_id: str, target: str = "law", query_filter: str = "") -> str:
    if not LAW_OPEN_API_KEY:
        return "❌ LAW_OPEN_API_KEY가 설정되지 않았습니다."

    url = "http://www.law.go.kr/DRF/lawService.do"
    params = {
        "OC": LAW_OPEN_API_KEY,
        "target": target,
        "ID": doc_id,
        "type": "XML"
    }

    try:
        resp = requests.get(url, params=params, timeout=20)
        resp.encoding = "utf-8"
        if resp.status_code != 200:
            return f"❌ 원문 조회 실패 (HTTP {resp.status_code})"

        root = ET.fromstring(resp.text)

        if target in ["law", "ordin"]:
            title_tag = "법령명_한글" if target == "law" else "자치법규명"
            title = root.findtext(f".//{title_tag}") or root.findtext(".//법령명_한글") or "명칭 미상"
            articles = root.findall(".//조문단위")
            
            extracted = [f"📘 [{title}] (ID: {doc_id})"]
            for art in articles:
                art_body = "".join(art.itertext()).strip()
                if query_filter:
                    if query_filter.replace(" ", "") in art_body.replace(" ", ""):
                        extracted.append(art_body)
                else:
                    extracted.append(art_body)

            if len(extracted) == 1 and query_filter:
                return f"'{title}' 내에서 '{query_filter}' 키워드가 포함된 조문을 찾지 못했습니다. 필터 없이 다시 조회하거나 다른 조문번호를 검색하세요."
            
            full_text = "\n\n".join(extracted)
            return full_text[:12000]

        elif target == "prec":
            case_name = root.findtext(".//사건명") or ""
            case_no = root.findtext(".//사건번호") or ""
            dec_date = root.findtext(".//선고일자") or ""
            summary = root.findtext(".//판결요지") or ""
            holding = root.findtext(".//판시사항") or ""
            ref_law = root.findtext(".//참조조문") or ""
            body = root.findtext(".//판례내용") or ""

            text = (
                f"⚖️ [판례 상세] {case_name} ({case_no}, 선고일: {dec_date})\n"
                f"■ 판시사항:\n{holding}\n\n"
                f"■ 판결요지:\n{summary}\n\n"
                f"■ 참조조문:\n{ref_law}\n\n"
                f"■ 판례본문(발췌):\n{body[:5000]}"
            )
            return text[:12000]

        elif target == "decc":
            case_name = root.findtext(".//사건명") or ""
            case_no = root.findtext(".//사건번호") or ""
            dec_date = root.findtext(".//의결일자") or root.findtext(".//처분일자") or ""
            agency = root.findtext(".//재결청") or "조세심판원 등"
            order = root.findtext(".//주문") or ""
            summary = root.findtext(".//결정요지") or root.findtext(".//재결요지") or ""
            reason = root.findtext(".//이유") or ""

            text = (
                f"🏛️ [조세심판원/특별행정심판 결정례] {case_name}\n"
                f"- 사건번호: {case_no} | 재결청: {agency} | 결정일: {dec_date}\n"
                f"■ 주문:\n{order}\n\n"
                f"■ 결정요지:\n{summary}\n\n"
                f"■ 이유(본문 발췌):\n{reason[:6000]}"
            )
            return text[:12000]

        elif target == "admrul":
            rule_name = root.findtext(".//행정규칙명") or ""
            ministry = root.findtext(".//소관부처명") or ""
            issue_date = root.findtext(".//발령일자") or ""
            body_nodes = [elem.text.strip() for elem in root.iter() if elem.text and elem.text.strip()]
            body_text = "\n".join(body_nodes)
            return f"📋 [행정규칙/훈령/고시] {rule_name} ({ministry}, 발령일: {issue_date})\n\n{body_text[:10000]}"

        elif target == "expc":
            title = root.findtext(".//안건명") or ""
            item_no = root.findtext(".//안건번호") or ""
            reply_org = root.findtext(".//회신기관명") or ""
            reply_date = root.findtext(".//회신일자") or ""
            question = root.findtext(".//질의요지") or ""
            answer = root.findtext(".//회답") or ""
            reason = root.findtext(".//이유") or ""

            text = (
                f"📑 [법령해석례/질의회신] {title} ({item_no}, {reply_org}, 회신일: {reply_date})\n"
                f"■ 질의요지:\n{question}\n\n"
                f"■ 회답:\n{answer}\n\n"
                f"■ 이유:\n{reason[:6000]}"
            )
            return text[:12000]

        all_text = "\n".join([t.strip() for t in root.itertext() if t.strip()])
        return all_text[:10000]

    except Exception as e:
        return f"❌ 원문 상세 조회 중 오류 발생: {e}"


# ---------------------------------------------------------
# 2. 한국은행 경제통계시스템 (ECOS) 환율 및 기준금리 조회
# ---------------------------------------------------------
def get_bok_exchange_rate(start_date: str, end_date: str, currency: str = "USD") -> str:
    if not BOK_API_KEY:
        return "❌ BOK_API_KEY가 설정되지 않았습니다."

    curr_map = {
        "USD": "0000001",
        "JPY": "0000002",
        "EUR": "0000003",
        "CNY": "0000053"
    }
    item_code = curr_map.get(currency.upper(), "0000001")
    s_date = start_date.replace("-", "").strip()
    e_date = end_date.replace("-", "").strip()

    url = f"https://ecos.bok.or.kr/api/StatisticSearch/{BOK_API_KEY}/json/kr/1/30/731Y001/D/{s_date}/{e_date}/{item_code}"
    try:
        resp = requests.get(url, timeout=10).json()
        rows = resp.get("StatisticSearch", {}).get("row", [])
        if not rows:
            return f"해당 기간({s_date}~{e_date})의 {currency} 환율 데이터가 없습니다. (휴일인 경우 직전 영업일을 포함해 5~7일 구간으로 조회하세요)"
        
        lines = [f"💱 [한국은행 공식 매매기준율 - {currency}]"]
        for r in rows:
            lines.append(f"- {r.get('TIME')}: {r.get('DATA_VALUE')} 원")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ 환율 조회 오류: {e}"


def get_bok_base_rate(start_date: str, end_date: str) -> str:
    if not BOK_API_KEY:
        return "❌ BOK_API_KEY가 설정되지 않았습니다."

    s_date = start_date.replace("-", "").strip()
    e_date = end_date.replace("-", "").strip()
    url = f"https://ecos.bok.or.kr/api/StatisticSearch/{BOK_API_KEY}/json/kr/1/30/722Y001/D/{s_date}/{e_date}/0101000"
    try:
        resp = requests.get(url, timeout=10).json()
        rows = resp.get("StatisticSearch", {}).get("row", [])
        if not rows:
            return f"해당 기간({s_date}~{e_date})의 기준금리 데이터가 없습니다."
        
        lines = ["📈 [한국은행 기준금리 조회 결과]"]
        for r in rows[-10:]:
            lines.append(f"- {r.get('TIME')}: 연 {r.get('DATA_VALUE')}%")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ 기준금리 조회 오류: {e}"


# ---------------------------------------------------------
# 3. 국세청 기준경비율 6자리 업종코드 마스터 엑셀/CSV 검색
# ---------------------------------------------------------
_INDUSTRY_DF_CACHE = None

def search_industry_code(keyword: str) -> str:
    global _INDUSTRY_DF_CACHE
    try:
        if _INDUSTRY_DF_CACHE is None:
            if os.path.exists("industry_codes.xlsx"):
                _INDUSTRY_DF_CACHE = pd.read_excel("industry_codes.xlsx", dtype=str).fillna("")
            elif os.path.exists("industry_codes.csv"):
                for enc in ["utf-8-sig", "cp949", "euc-kr", "utf-8"]:
                    try:
                        _INDUSTRY_DF_CACHE = pd.read_csv("industry_codes.csv", encoding=enc, dtype=str).fillna("")
                        break
                    except Exception:
                        continue
            else:
                return "⚠️ 프로젝트 폴더에 'industry_codes.xlsx' 파일이 없습니다. 임의로 6자리 코드를 생성하지 마세요."

        df = _INDUSTRY_DF_CACHE
        kw = keyword.strip()
        mask = df.apply(lambda row: kw in " ".join(row.values), axis=1)
        matched = df[mask]

        if matched.empty:
            return f"'{keyword}' 키워드로 검색된 국세청 업종코드가 없습니다. 유사한 다른 단어(예: 도소매, 소프트웨어, 자문 등)로 다시 검색하거나 번호 생성을 생략하세요."

        lines = [f"🏢 [국세청 업종코드 마스터 DB 검색 결과: '{keyword}' (총 {len(matched)}건 중 상위 15건)]"]
        for _, row in matched.head(15).iterrows():
            row_str = " | ".join([f"{col}: {val}" for col, val in row.items() if str(val).strip()])
            lines.append(f"- {row_str}")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ 업종코드 파일 검색 오류: {e}"


# ---------------------------------------------------------
# 4. 금융감독원 전자공시시스템 (Open DART) 6대 핵심 정보 통합 조회
#    (기업개황 + 최근 공시 + 주요 재무제표 + 최대주주 지분현황 + 배당 내역 + 타법인 출자현황)
# ---------------------------------------------------------
_DART_CORP_CACHE = None

def _load_dart_corp_codes() -> list[dict]:
    global _DART_CORP_CACHE
    if _DART_CORP_CACHE is not None:
        return _DART_CORP_CACHE
    if not DART_API_KEY:
        return []

    cache_file = ".workspace_storage/dart_corp_codes.xml"
    os.makedirs(".workspace_storage", exist_ok=True)

    try:
        if not os.path.exists(cache_file):
            url = f"https://opendart.fss.or.kr/api/corpCode.xml?crtfc_key={DART_API_KEY}"
            resp = requests.get(url, timeout=25)
            with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
                xml_name = z.namelist()[0]
                xml_bytes = z.read(xml_name)
                with open(cache_file, "wb") as f:
                    f.write(xml_bytes)

        tree = ET.parse(cache_file)
        root = tree.getroot()
        corp_list = []
        for item in root.findall(".//list"):
            c_name = (item.findtext("corp_name") or "").strip()
            c_code = (item.findtext("corp_code") or "").strip()
            s_code = (item.findtext("stock_code") or "").strip()
            m_date = (item.findtext("modify_date") or "").strip()
            if c_name and c_code:
                corp_list.append({
                    "corp_name": c_name,
                    "corp_code": c_code,
                    "stock_code": s_code,
                    "modify_date": m_date
                })
        _DART_CORP_CACHE = corp_list
        return _DART_CORP_CACHE
    except Exception as e:
        print(f"⚠️ DART 고유번호 마스터 로드 오류: {e}")
        return []


def get_dart_corp_info(corp_name: str, bsns_year: str = "2025") -> str:
    """
    DART에서 특정 기업의 1) 기업개황, 2) 최근 공시 목록, 3) 주요 재무제표,
    4) 최대주주 및 특수관계인 지분현황, 5) 배당에 관한 사항, 6) 타법인 출자현황을 통합 조회합니다.
    """
    if not DART_API_KEY:
        return "❌ DART_API_KEY가 설정되지 않았습니다."

    corps = _load_dart_corp_codes()
    if not corps:
        return "❌ DART 기업 고유번호 목록을 불러오지 못했습니다."

    kw = corp_name.strip().replace("(주)", "").replace("주식회사", "").strip()
    exact_matches = [c for c in corps if c["corp_name"] == kw or c["corp_name"] == corp_name.strip()]
    partial_matches = [c for c in corps if kw in c["corp_name"]]

    candidates = exact_matches if exact_matches else partial_matches
    if not candidates:
        return f"DART에 '{corp_name}' 명칭으로 등록된 외감/상장법인을 찾을 수 없습니다."

    candidates.sort(key=lambda x: (1 if x["stock_code"] else 0, x["modify_date"]), reverse=True)
    target = candidates[0]
    corp_code = target["corp_code"]

    output = [f"🏛️ [DART 전자공시 6대 정보 통합 조회: {target['corp_name']} (고유번호: {corp_code} / 종목코드: {target['stock_code'] or '비상장'})]"]
    if len(candidates) > 1:
        other_names = ", ".join([f"{c['corp_name']}({c['corp_code']})" for c in candidates[1:5]])
        output.append(f"*(참고 - 동명/유사 법인 후보: {other_names})*")

    # 1) 기업개황
    try:
        info_url = "https://opendart.fss.or.kr/api/company.json"
        info_res = requests.get(info_url, params={"crtfc_key": DART_API_KEY, "corp_code": corp_code}, timeout=10).json()
        if info_res.get("status") == "000":
            output.append(
                f"\n■ 1. 기업개황:\n"
                f"- 정식명칭: {info_res.get('corp_name')} | 대표자: {info_res.get('ceo_nm')}\n"
                f"- 사업자등록번호: {info_res.get('bizr_no')} | 법인등록번호: {info_res.get('jurir_no')}\n"
                f"- 업종코드: {info_res.get('induty_code')} | 결산월: {info_res.get('acc_mt')}월\n"
                f"- 주소: {info_res.get('adres')}"
            )
    except Exception as e:
        output.append(f"\n■ 1. 기업개황 조회 오류: {e}")

    # 2) 최근 주요 공시보고서 목록 (상위 8건)
    try:
        list_url = "https://opendart.fss.or.kr/api/list.json"
        list_res = requests.get(list_url, params={
            "crtfc_key": DART_API_KEY,
            "corp_code": corp_code,
            "page_count": 8
        }, timeout=10).json()
        if list_res.get("status") == "000":
            output.append("\n■ 2. 최근 주요 공시보고서 (상위 8건):")
            for item in list_res.get("list", [])[:8]:
                r_nm = item.get("report_nm")
                r_dt = item.get("rcept_dt")
                r_no = item.get("rcept_no")
                output.append(f"- [{r_dt}] {r_nm} (접수번호: {r_no} | 열람: https://dart.fss.or.kr/dsaf001/main.do?rcpNo={r_no} )")
    except Exception as e:
        output.append(f"\n■ 2. 공시 목록 조회 오류: {e}")

    # 기준 사업연도 자동 탐색 (지정 연도 데이터가 없으면 직전 연도 사업보고서 자동 조회)
    years_to_try = [bsns_year.strip(), str(int(bsns_year.strip()) - 1)] if bsns_year.strip().isdigit() else ["2025", "2024"]
    active_year = years_to_try[0]

    # 3) 주요 재무제표 요약
    fin_found = False
    for yr in years_to_try:
        try:
            fin_url = "https://opendart.fss.or.kr/api/fnlttSinglAcnt.json"
            fin_res = requests.get(fin_url, params={
                "crtfc_key": DART_API_KEY,
                "corp_code": corp_code,
                "bsns_year": yr,
                "reprt_code": "11011"
            }, timeout=10).json()
            if fin_res.get("status") == "000" and fin_res.get("list"):
                active_year = yr
                output.append(f"\n■ 3. 주요 재무제표 요약 ({yr}년 사업보고서 기준):")
                for row in fin_res.get("list", []):
                    fs_nm = row.get("fs_nm")
                    sj_nm = row.get("sj_nm")
                    acct_nm = row.get("account_nm")
                    thstrm = row.get("thstrm_amount", "-")
                    frmtrm = row.get("frmtrm_amount", "-")
                    if fs_nm == "재무제표" or "연결" in fs_nm:
                        output.append(f"- [{fs_nm} | {sj_nm}] {acct_nm}: 당기 {thstrm}원 (전기: {frmtrm}원)")
                fin_found = True
                break
        except Exception:
            continue

    if not fin_found:
        output.append(f"\n■ 3. 주요 재무제표 요약: 정기 사업보고서 제출 대상이 아니거나 비상장 외감법인(감사보고서 원문 공시 대상)입니다. 위 2번 공시 목록의 감사보고서 링크를 참고하세요.")

    # 4) 최대주주 및 특수관계인 지분현황 (hyslrSttus.json)
    try:
        sh_url = "https://opendart.fss.or.kr/api/hyslrSttus.json"
        sh_res = requests.get(sh_url, params={
            "crtfc_key": DART_API_KEY,
            "corp_code": corp_code,
            "bsns_year": active_year,
            "reprt_code": "11011"
        }, timeout=10).json()
        if sh_res.get("status") == "000" and sh_res.get("list"):
            output.append(f"\n■ 4. 최대주주 및 특수관계인 지분현황 ({active_year}년 기준):")
            for row in sh_res.get("list", [])[:15]:
                nm = row.get("nm", "-")
                rel = row.get("relate", "-")
                stock_knd = row.get("stock_knd", "보통주")
                trmend_cnt = row.get("trmend_posesn_stock_co", "-")
                trmend_rt = row.get("trmend_posesn_stock_qota_rt", "-")
                output.append(f"- 주주명: {nm} (관계: {rel} | {stock_knd}) -> 기말주식수: {trmend_cnt}주 (지분율: {trmend_rt}%)")
    except Exception:
        pass

    # 5) 배당에 관한 사항 (alotMatter.json)
    try:
        div_url = "https://opendart.fss.or.kr/api/alotMatter.json"
        div_res = requests.get(div_url, params={
            "crtfc_key": DART_API_KEY,
            "corp_code": corp_code,
            "bsns_year": active_year,
            "reprt_code": "11011"
        }, timeout=10).json()
        if div_res.get("status") == "000" and div_res.get("list"):
            output.append(f"\n■ 5. 배당에 관한 주요 사항 ({active_year}년 기준):")
            for row in div_res.get("list", []):
                se = row.get("se", "-")
                stock_knd = row.get("stock_knd", "")
                thstrm = row.get("thstrm", "-")
                frmtrm = row.get("frmtrm", "-")
                lwfr = row.get("lwfr", "-")
                label = f"{se} ({stock_knd})" if stock_knd else se
                output.append(f"- {label}: 당기 {thstrm} | 전기 {frmtrm} | 전전기 {lwfr}")
    except Exception:
        pass

    # 6) 타법인 출자현황 (otrCprInvstmntSttus.json)
    try:
        inv_url = "https://opendart.fss.or.kr/api/otrCprInvstmntSttus.json"
        inv_res = requests.get(inv_url, params={
            "crtfc_key": DART_API_KEY,
            "corp_code": corp_code,
            "bsns_year": active_year,
            "reprt_code": "11011"
        }, timeout=10).json()
        if inv_res.get("status") == "000" and inv_res.get("list"):
            output.append(f"\n■ 6. 타법인 출자(자회사·관계기업 지분) 현황 ({active_year}년 기준, 상위 15건):")
            for row in inv_res.get("list", [])[:15]:
                inv_prm = row.get("inv_prm", "-")
                inv_purp = row.get("invstmnt_purps", "-")
                trmend_blce_acnt = row.get("trmend_blce_acnt_amount", "-")
                trmend_qota_rt = row.get("trmend_blce_qota_rt", "-")
                recent_ni = row.get("recent_bsns_year_fnnr_sttus_thstrm_ntpf", "-")
                output.append(f"- 피출자법인: {inv_prm} (목적: {inv_purp}) | 지분율: {trmend_qota_rt}% | 기말장부가액: {trmend_blce_acnt} | 최근연도 당기순이익: {recent_ni}")
    except Exception:
        pass

    return "\n".join(output)[:14000]


# ---------------------------------------------------------
# 5. 국세청 사업자등록 상태조회 및 대표자·개업일 진위확인
# ---------------------------------------------------------
def get_nts_biz_status(biz_numbers_text: str) -> str:
    """사업자등록번호(10자리)로 납세자상태(계속/휴폐업) 및 과세유형(일반/간이/면세)을 조회합니다."""
    if not NTS_API_KEY:
        return "❌ NTS_API_KEY가 설정되지 않았습니다."

    cleaned_input = re.sub(r"(\d{3})-(\d{2})-(\d{5})", r"\1\2\3", biz_numbers_text)
    b_nos = re.findall(r"\b\d{10}\b", cleaned_input)
    if not b_nos:
        digits_only = re.sub(r"\D", "", biz_numbers_text)
        if len(digits_only) == 10:
            b_nos = [digits_only]

    if not b_nos:
        return f"❌ 입력된 값('{biz_numbers_text}')에서 유효한 10자리 사업자등록번호를 찾을 수 없습니다."

    b_nos = list(dict.fromkeys(b_nos))[:100]
    encoded_key = NTS_API_KEY if "%" in NTS_API_KEY else urllib.parse.quote(NTS_API_KEY, safe="")
    url = f"https://api.odcloud.kr/api/nts-businessman/v1/status?serviceKey={encoded_key}"

    try:
        resp = requests.post(
            url,
            json={"b_no": b_nos},
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            timeout=10
        )
        if resp.status_code != 200:
            return f"❌ 국세청 API 호출 실패 (HTTP {resp.status_code}): {resp.text[:200]}"

        res_json = resp.json()
        data_list = res_json.get("data", [])
        if not data_list:
            return "조회된 사업자등록 상태 데이터가 없습니다."

        lines = [f"🏛️ [국세청 사업자등록 상태 및 과세유형 실시간 조회 결과 (총 {len(data_list)}건)]"]
        for item in data_list:
            b_no = item.get("b_no", "")
            formatted_bno = f"{b_no[:3]}-{b_no[3:5]}-{b_no[5:]}" if len(b_no) == 10 else b_no
            b_stt = item.get("b_stt") or "미등록/확인불가"
            tax_type = item.get("tax_type") or "-"
            end_dt = item.get("end_dt") or "-"
            utcc_yn = item.get("utcc_yn") or "-"
            tax_type_change_dt = item.get("tax_type_change_dt") or "-"
            invoice_apply_dt = item.get("invoice_apply_dt") or "-"
            rbf_tax_type = item.get("rbf_tax_type") or "-"

            detail = f"■ 사업자번호: {formatted_bno}\n  - 납세자상태: {b_stt}\n  - 과세유형: {tax_type}"
            if end_dt != "-":
                detail += f"\n  - ⚠️ 폐업일자: {end_dt}"
            if tax_type_change_dt != "-":
                detail += f"\n  - 과세유형전환일자: {tax_type_change_dt} (직전 과세유형: {rbf_tax_type})"
            if utcc_yn != "-":
                detail += f"\n  - 단위과세전환폐업여부: {utcc_yn}"
            if invoice_apply_dt != "-":
                detail += f"\n  - 세금계산서적용일자: {invoice_apply_dt}"
            lines.append(detail)

        return "\n\n".join(lines)
    except Exception as e:
        return f"❌ 국세청 사업자 상태조회 중 오류 발생: {e}"


def verify_nts_biz_info(b_no: str, start_dt: str, p_nm: str, b_nm: str = "") -> str:
    """
    사업자등록번호(10자리) + 개업일자(YYYYMMDD) + 대표자성명(필수) + 상호(선택)를 국세청 전산과 대조하여
    실제 등록된 진위 여부('01': 일치, '02': 불일치)를 검증합니다.
    """
    if not NTS_API_KEY:
        return "❌ NTS_API_KEY가 설정되지 않았습니다."

    clean_bno = re.sub(r"\D", "", b_no)
    clean_dt = re.sub(r"\D", "", start_dt)
    if len(clean_bno) != 10 or len(clean_dt) != 8 or not p_nm.strip():
        return "❌ 진위확인을 위해서는 10자리 사업자번호, 8자리 개업일자(YYYYMMDD), 대표자 성명이 모두 필요합니다."

    encoded_key = NTS_API_KEY if "%" in NTS_API_KEY else urllib.parse.quote(NTS_API_KEY, safe="")
    url = f"https://api.odcloud.kr/api/nts-businessman/v1/validate?serviceKey={encoded_key}"

    payload = {
        "businesses": [
            {
                "b_no": clean_bno,
                "start_dt": clean_dt,
                "p_nm": p_nm.strip(),
                "p_nm2": "",
                "b_nm": b_nm.strip(),
                "corp_no": "",
                "b_sector": "",
                "b_type": "",
                "b_adr": ""
            }
        ]
    }

    try:
        resp = requests.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            timeout=10
        )
        if resp.status_code != 200:
            return f"❌ 국세청 진위확인 API 호출 실패 (HTTP {resp.status_code}): {resp.text[:200]}"

        res_json = resp.json()
        data_list = res_json.get("data", [])
        if not data_list:
            return "진위확인 결과가 반환되지 않았습니다."

        item = data_list[0]
        valid_code = item.get("valid", "")
        valid_msg = "✅ 일치 (정상 진위확인 완료)" if valid_code == "01" else f"❌ 불일치 (사유: {item.get('valid_msg', '등록정보와 다름')})"
        status_info = item.get("status", {}) or {}

        return (
            f"🛡️ [국세청 사업자등록정보 진위확인 결과]\n"
            f"- 검증 대상: 사업자번호 {clean_bno} | 개업일 {clean_dt} | 대표자 {p_nm} {f'| 상호 {b_nm}' if b_nm else ''}\n"
            f"- 진위확인 판정: {valid_msg} (코드: {valid_code})\n"
            f"- 현재 납세자상태: {status_info.get('b_stt', '-')} | 과세유형: {status_info.get('tax_type', '-')}"
        )
    except Exception as e:
        return f"❌ 국세청 사업자 진위확인 중 오류 발생: {e}"
