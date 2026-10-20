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
def search_law_data(keyword: str, target: str = "law", search_mode: int = None) -> list[dict]:
    """search_mode: None/1 = 제목(법령명·사건명·안건명) 검색, 2 = 본문 검색 (판례·해석례·행정규칙 주제어 검색용)"""
    if not LAW_OPEN_API_KEY:
        return []

    # 'decc'는 API상 일반 행정심판 재결례(국민권익위 등)라서 세무와 무관한 결과가 나옴
    # → 조세심판원 결정례는 'ttSpecialDecc'로만 조회 (일반 행정심판으로 대체하지 않음)
    if target == "decc":
        return _search_law_data_raw(keyword, "ttSpecialDecc", search_mode)
    return _search_law_data_raw(keyword, target, search_mode)


def _search_law_data_raw(keyword: str, target: str, search_mode: int = None) -> list[dict]:
    url = "http://www.law.go.kr/DRF/lawSearch.do"
    params = {
        "OC": LAW_OPEN_API_KEY,
        "target": target,
        "type": "XML",
        "query": keyword,
        "display": 10
    }
    if search_mode:
        params["search"] = search_mode
    if target in ("prec", "ttSpecialDecc"):
        params["sort"] = "ddes"   # 선고·의결일자 최신순 (기본값은 오래된 순이라 1990년대 사건부터 나옴)

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
            "ttSpecialDecc": "decc",   # 실제 응답: <Decc><decc id="1">…</decc></Decc>
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


# ---------------------------------------------------------
# 1-1. 법령 조문 정밀 추출 도우미
# ---------------------------------------------------------
_CIRCLED_NUM = {chr(0x2460 + i): i + 1 for i in range(20)}  # ①~⑳ → 1~20

def _parse_article_filter(query_filter: str):
    """'제33조의2', '제78조의3 제8항' 같은 입력에서 (조, 가지, 항)을 추출합니다. 조문번호가 없으면 None."""
    m = re.search(r"제\s*(\d+)\s*조(?:\s*의\s*(\d+))?(?:\s*제?\s*(\d+)\s*항)?", query_filter or "")
    if not m:
        return None
    jo = int(m.group(1))
    gaji = int(m.group(2)) if m.group(2) else 0
    hang = int(m.group(3)) if m.group(3) else None
    return jo, gaji, hang

def _hang_number(text: str):
    t = (text or "").strip()
    if t and t[0] in _CIRCLED_NUM:
        return _CIRCLED_NUM[t[0]]
    d = re.match(r"(\d+)", t)
    return int(d.group(1)) if d else None

def _to_int(text: str, default: int = 0) -> int:
    d = re.sub(r"\D", "", text or "")
    return int(d) if d else default

def _format_article(art, only_hang=None) -> str:
    """조문단위 XML 하나를 '조문 제목 → 항 → 호 → 목' 순서의 읽기 쉬운 텍스트로 변환합니다."""
    lines = []
    jo_content = (art.findtext("조문내용") or "").strip()
    if jo_content:
        lines.append(jo_content)

    hangs = art.findall("항")
    if hangs:
        for hang in hangs:
            if only_hang is not None:
                hn = _hang_number(hang.findtext("항번호")) or _hang_number(hang.findtext("항내용"))
                if hn != only_hang:
                    continue
            for el in hang.iter():
                if el.tag in ("항내용", "호내용", "목내용") and el.text and el.text.strip():
                    indent = {"항내용": "", "호내용": "  ", "목내용": "    "}[el.tag]
                    lines.append(indent + el.text.strip())
    else:
        for el in art.iter():
            if el.tag in ("호내용", "목내용") and el.text and el.text.strip():
                lines.append(("  " if el.tag == "호내용" else "    ") + el.text.strip())

    text = "\n".join(lines)
    eff = re.sub(r"\D", "", art.findtext("조문시행일자") or "")
    if len(eff) == 8:
        text += f"\n[조문시행일자: {eff[:4]}.{eff[4:6]}.{eff[6:]}]"
    return text

def _fetch_xml_root(url: str, params: dict):
    try:
        resp = requests.get(url, params=params, timeout=20)
        resp.encoding = "utf-8"
        if resp.status_code != 200:
            return None
        return ET.fromstring(resp.text)
    except Exception:
        return None

def _get_statute_articles(doc_id: str, query_filter: str = "") -> str:
    """
    법령 원문에서 조문을 정밀 추출합니다.
    """
    url = "http://www.law.go.kr/DRF/lawService.do"
    art_filter = _parse_article_filter(query_filter)
    base = {"OC": LAW_OPEN_API_KEY, "target": "law", "type": "XML"}

    attempts = []
    if art_filter:
        jo_code = f"{art_filter[0]:04d}{art_filter[1]:02d}"
        attempts.append({**base, "MST": doc_id, "JO": jo_code})
    attempts.append({**base, "MST": doc_id})
    attempts.append({**base, "ID": doc_id})

    title = "명칭 미상"
    found_any_law = False

    for params in attempts:
        root = _fetch_xml_root(url, params)
        if root is None:
            continue
        articles = [
            a for a in root.findall(".//조문단위")
            if (a.findtext("조문여부") or "조문").strip() != "전문"
        ]
        if not articles:
            continue

        found_any_law = True
        title = (root.findtext(".//법령명_한글") or root.findtext(".//법령명한글") or title).strip()
        law_eff = re.sub(r"\D", "", root.findtext(".//시행일자") or "")
        eff_note = f" | 법령 시행일자: {law_eff[:4]}.{law_eff[4:6]}.{law_eff[6:]}" if len(law_eff) == 8 else ""
        header = f"📘 [{title}] (일련번호: {doc_id}{eff_note})"

        # ① 조문번호 지정 조회: 번호가 정확히 일치하는 조문만
        if art_filter:
            jo, gaji, hang = art_filter
            matched = [
                a for a in articles
                if _to_int(a.findtext("조문번호")) == jo and _to_int(a.findtext("조문가지번호")) == gaji
            ]
            if matched:
                body = "\n\n".join(_format_article(a, only_hang=hang) for a in matched)
                return (header + "\n\n" + body)[:15000]
            continue

        # ② 키워드 조회: 키워드가 들어간 조문 (최대 8개)
        if query_filter:
            kw = query_filter.replace(" ", "")
            matched = []
            for a in articles:
                txt = _format_article(a)
                if kw in txt.replace(" ", ""):
                    matched.append(txt)
            if not matched:
                return f"'{title}' 내에서 '{query_filter}' 키워드가 포함된 조문을 찾지 못했습니다. 조문번호(예: '제33조의2')로 다시 조회하세요."
            note = f"\n\n[※ 키워드 포함 조문 {len(matched)}개 중 앞 8개만 표시]" if len(matched) > 8 else ""
            return (header + "\n\n" + "\n\n".join(matched[:8]))[:12000] + note

        # ③ 필터 없음: 전체 조문 (분량 제한)
        body = "\n\n".join(_format_article(a) for a in articles)
        return (header + "\n\n" + body)[:12000] + "\n\n[※ 전체 조문 중 앞부분만 표시. 조문번호를 지정해 다시 조회하세요]"

    if art_filter and found_any_law:
        jo, gaji, _ = art_filter
        label = f"제{jo}조" + (f"의{gaji}" if gaji else "")
        return f"'{title}'에서 {label}를 찾지 못했습니다. 법률/시행령 일련번호를 혼동하지 않았는지 확인하세요."
    return f"❌ 일련번호 '{doc_id}'로 법령 원문을 불러오지 못했습니다. search_law_for_gemini로 일련번호를 다시 확인하세요."


def get_law_content(doc_id: str, target: str = "law", query_filter: str = "") -> str:
    if not LAW_OPEN_API_KEY:
        return "❌ LAW_OPEN_API_KEY가 설정되지 않았습니다."

    if target == "law":
        try:
            return _get_statute_articles(doc_id, query_filter)
        except Exception as e:
            return f"❌ 법령 조문 조회 중 오류 발생: {e}"

    url = "http://www.law.go.kr/DRF/lawService.do"
    api_target = "ttSpecialDecc" if target == "decc" else target
    params = {
        "OC": LAW_OPEN_API_KEY,
        "target": api_target,
        "ID": doc_id,
        "type": "XML"
    }

    try:
        resp = requests.get(url, params=params, timeout=20)
        resp.encoding = "utf-8"
        if resp.status_code != 200:
            return f"❌ 원문 조회 실패 (HTTP {resp.status_code})"

        root = ET.fromstring(resp.text)

        if target == "ordin":
            title = root.findtext(".//자치법규명") or root.findtext(".//법령명_한글") or "명칭 미상"
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
            case_no = root.findtext(".//사건번호") or root.findtext(".//청구번호") or ""
            dec_date = root.findtext(".//의결일자") or root.findtext(".//처분일자") or ""
            agency = root.findtext(".//재결청") or "조세심판원 등"
            order = root.findtext(".//주문") or ""
            summary = root.findtext(".//결정요지") or root.findtext(".//재결요지") or ""
            reason = root.findtext(".//이유") or ""

            if not (order or summary or reason):
                body_all = "\n".join(t.strip() for t in root.itertext() if t.strip())
                return f"🏛️ [조세심판원/특별행정심판 결정례] {case_name} ({case_no})\n{body_all[:10000]}"
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

    years_to_try = [bsns_year.strip(), str(int(bsns_year.strip()) - 1)] if bsns_year.strip().isdigit() else ["2025", "2024"]
    active_year = years_to_try[0]

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


# ---------------------------------------------------------
# 6. 국토교통부 부동산 매매 실거래가 4종 통합 조회 (아파트 / 오피스텔 / 상업업무용 상가·빌딩 / 토지)
# ---------------------------------------------------------
_LAWD_CODE_MAP = {
    # 서울특별시 25개 자치구
    "종로구": "11110", "중구": "11140", "용산구": "11170", "성동구": "11200", "광진구": "11215",
    "동대문구": "11230", "중랑구": "11260", "성북구": "11290", "강북구": "11305", "도봉구": "11320",
    "노원구": "11350", "은평구": "11380", "서대문구": "11410", "마포구": "11440", "양천구": "11470",
    "강서구": "11500", "구로구": "11530", "금천구": "11545", "영등포구": "11560", "동작구": "11590",
    "관악구": "11620", "서초구": "11650", "강남구": "11680", "송파구": "11710", "강동구": "11740",
    # 경기도 및 주요 광역시 핵심 시·군·구
    "분당구": "41135", "수정구": "41131", "중원구": "41133", "수지구": "41465", "기흥구": "41463",
    "처인구": "41461", "영통구": "41117", "팔달구": "41115", "권선구": "41113", "장안구": "41111",
    "과천시": "41290", "광명시": "41210", "하남시": "41450", "고양시 일산동구": "41285", "일산동구": "41285",
    "일산서구": "41287", "덕양구": "41281", "부천시": "41190", "안양시 동안구": "41173", "동안구": "41173",
    "만안구": "41171", "화성시": "41590", "평택시": "41220", "남양주시": "41360", "김포시": "41570",
    "연수구": "28185", "남동구": "28200", "부평구": "28237", "서구": "28260", "해운대구": "26350",
    "수영구": "26500", "부산진구": "26230", "수성구": "27260", "유성구": "30200", "세종시": "36110"
}

def _resolve_lawd_cd(region_str: str) -> str:
    """입력된 문자열에서 5자리 법정동코드(LAWD_CD)를 추출하거나 시군구 이름으로 매핑합니다."""
    digits = re.sub(r"\D", "", region_str)
    if len(digits) >= 5:
        return digits[:5]
    for name, code in _LAWD_CODE_MAP.items():
        if name in region_str:
            return code
    return ""

def get_molit_real_estate_trade(property_type: str, region: str, deal_ymd: str, filter_keyword: str = "") -> str:
    if not NTS_API_KEY:
        return "❌ NTS_API_KEY(공공데이터포털 인증키)가 설정되지 않았습니다."

    lawd_cd = _resolve_lawd_cd(region)
    if not lawd_cd:
        return f"❌ '{region}'에 해당하는 5자리 법정동코드를 찾지 못했습니다. 시·군·구 명칭(예: '강남구', '관악구', '분당구')이나 5자리 법정동코드(예: '11680')로 다시 입력해 주세요."

    ymd = re.sub(r"\D", "", deal_ymd)[:6]
    if len(ymd) != 6:
        return f"❌ 계약연월('{deal_ymd}')은 'YYYYMM' 6자리 형식(예: '202609')이어야 합니다."

    ptype = property_type.lower().strip()
    if ptype in ["아파트", "공동주택", "apt"]:
        endpoint = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev"
        fallback_ep = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade"
        type_label = "아파트(공동주택) 매매"
    elif ptype in ["오피스텔", "offi", "officetel"]:
        endpoint = "https://apis.data.go.kr/1613000/RTMSDataSvcOffiTrade/getRTMSDataSvcOffiTrade"
        fallback_ep = None
        type_label = "오피스텔 매매"
    elif ptype in ["상가", "상업업무용", "빌딩", "comm", "commercial"]:
        endpoint = "https://apis.data.go.kr/1613000/RTMSDataSvcNrgTrade/getRTMSDataSvcNrgTrade"
        fallback_ep = None
        type_label = "상업·업무용(상가·오피스·빌딩) 매매"
    elif ptype in ["토지", "대지", "임야", "land"]:
        endpoint = "https://apis.data.go.kr/1613000/RTMSDataSvcLandTrade/getRTMSDataSvcLandTrade"
        fallback_ep = None
        type_label = "토지 매매"
    else:
        endpoint = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev"
        fallback_ep = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade"
        type_label = "아파트(공동주택) 매매"

    encoded_key = NTS_API_KEY if "%" in NTS_API_KEY else urllib.parse.quote(NTS_API_KEY, safe="")

    def _fetch_xml(ep_url: str):
        full_url = f"{ep_url}?serviceKey={encoded_key}&LAWD_CD={lawd_cd}&DEAL_YMD={ymd}&numOfRows=200&pageNo=1"
        return requests.get(full_url, timeout=15)

    try:
        resp = _fetch_xml(endpoint)
        if (resp.status_code != 200 or "<item>" not in resp.text) and fallback_ep:
            resp2 = _fetch_xml(fallback_ep)
            if resp2.status_code == 200 and "<item>" in resp2.text:
                resp = resp2

        if resp.status_code != 200:
            return f"❌ 국토교통부 API 호출 실패 (HTTP {resp.status_code}): 공공데이터포털 활용신청 동기화 대기 중이거나 키 오류입니다."

        root = ET.fromstring(resp.text)
        result_code = (root.findtext(".//resultCode") or "").strip()
        result_msg = (root.findtext(".//resultMsg") or "").strip()

        if result_code not in ["00", "000", "0000", ""]:
            return f"❌ 국토부 API 응답 오류 (코드 {result_code}): {result_msg}"

        items = root.findall(".//item")
        if not items:
            return f"조회된 [{type_label}] 실거래 내역이 없습니다. (지역코드: {lawd_cd}, 계약연월: {ymd})"

        kw = filter_keyword.strip()
        parsed_rows = []

        for it in items:
            data = {child.tag: (child.text or "").strip() for child in it}
            raw_str = " ".join(data.values())
            if kw and kw not in raw_str:
                continue

            umd = data.get("umdNm") or data.get(" 법정동") or data.get("dong") or ""
            jibun = data.get("jibun") or data.get("지번") or ""
            deal_amt = data.get("dealAmount") or data.get("거래금액") or "-"
            deal_day = f"{ymd[:4]}-{ymd[4:6]}-{str(data.get('dealDay') or data.get('일') or '01').zfill(2)}"
            cdeal_type = data.get("cdealType") or data.get("해제여부") or ""
            cancel_note = f" [⚠️해제됨:{cdeal_type}]" if cdeal_type and cdeal_type != "-" else ""

            if "아파트" in type_label or "오피스텔" in type_label:
                bldg_nm = data.get("aptNm") or data.get("offiNm") or data.get("아파트") or data.get("단지") or "명칭미상"
                exclu_area = data.get("excluUseAr") or data.get("전용면적") or "-"
                floor = data.get("floor") or data.get("층") or "-"
                build_yr = data.get("buildYear") or data.get("건축년도") or "-"
                parsed_rows.append(
                    f"- [{deal_day}] {umd} {bldg_nm} ({jibun}) | 전용 {exclu_area}㎡ ({floor}층, 건축:{build_yr}년) | 거래가액: {deal_amt}만원{cancel_note}"
                )
            elif "상업" in type_label:
                bldg_use = data.get("buildingUse") or data.get("건물주용도") or "-"
                land_use = data.get("landUse") or data.get("용도지역") or "-"
                bldg_ar = data.get("buildingAr") or data.get("건물면적") or "-"
                plottage_ar = data.get("plottageAr") or data.get("대지면적") or "-"
                floor = data.get("floor") or data.get("층") or "-"
                parsed_rows.append(
                    f"- [{deal_day}] {umd} ({jibun}) | 용도:{bldg_use}({land_use}) | 건물면적:{bldg_ar}㎡ (대지:{plottage_ar}㎡, {floor}층) | 거래가액: {deal_amt}만원{cancel_note}"
                )
            else:
                jimok = data.get("jimok") or data.get("지목") or "-"
                land_use = data.get("landUse") or data.get("용도지역") or "-"
                deal_ar = data.get("dealArea") or data.get("거래면적") or "-"
                share_gbn = data.get("shareDealingType") or data.get("지분구분") or ""
                parsed_rows.append(
                    f"- [{deal_day}] {umd} ({jibun}) | 지목:{jimok} ({land_use}) | 거래면적:{deal_ar}㎡ {f'({share_gbn})' if share_gbn else ''} | 거래가액: {deal_amt}만원{cancel_note}"
                )

        if not parsed_rows:
            return f"지역({lawd_cd})·연월({ymd})의 전체 거래 {len(items)}건 중 '{kw}' 키워드가 포함된 내역이 없습니다. 필터 키워드를 빼거나 동 이름만 입력해 다시 조회하세요."

        header = f"🏘️ [국토교통부 {type_label} 실거래가 조회 결과 | 지역:{region}({lawd_cd}) | 연월:{ymd} | 검색:{kw or '전체'} (총 {len(parsed_rows)}건 중 최근 25건)]"
        return header + "\n" + "\n".join(parsed_rows[:25])

    except Exception as e:
        return f"❌ 국토교통부 실거래가 조회 중 오류 발생: {e}"


# ---------------------------------------------------------
# 7. 국토교통부 브이월드(V-World) 개별공시지가 및 공동주택 공시가격 조회
# ---------------------------------------------------------
_MAJOR_BJDONG_MAP = {
    # 주요 세무 자문 빈출 법정동 10자리 코드 (지오코더 지연 시 즉시 매핑용)
    "역삼동": "1168010100", "대치동": "1168010600", "삼성동": "1168010500", "청담동": "1168010400",
    "논현동": "1168010800", "신사동": "1168010700", "압구정동": "1168011000", "도곡동": "1168011800",
    "서초동": "1165010800", "반포동": "1165010700", "잠원동": "1165010600", "양재동": "1165010200",
    "방배동": "1165010100", "잠실동": "1171010100", "가락동": "1171010700", "문정동": "1171010800",
    "서교동": "1144012000", "합정동": "1144012200", "연남동": "1144012400", "상암동": "1144012700",
    "여의도동": "1156011000", "문래동3가": "1156012100", "성수동1가": "1120011400", "성수동2가": "1120011500",
    "한남동": "1117013100", "이태원동": "1117013000", "신림동": "1162010200", "봉천동": "1162010100",
    "종로1가": "1111012600", "을지로1가": "1114010400", "명동2가": "1114012700", "구로동": "1153010200",
    "가산동": "1154510100", "목동": "1147010200", "마곡동": "1150010500", "백현동": "4113511000",
    "삼평동": "4113510900", "정자동": "4113510300", "서현동": "4113510500"
}

def _get_vworld_key() -> str:
    try:
        import streamlit as st
        if hasattr(st, "secrets") and "VWORLD_API_KEY" in st.secrets:
            val = str(st.secrets["VWORLD_API_KEY"]).strip().strip('"').strip("'")
            if val:
                return val
    except Exception:
        pass
    return os.getenv("VWORLD_API_KEY", "").strip().strip('"').strip("'")


def _build_19digit_pnu(bjdong_10: str, jibun_text: str) -> str:
    """10자리 법정동코드와 지번 문자열(예: '858', '대치동 316 (은마아파트)', '395-166')을 결합해 19자리 PNU를 생성합니다."""
    bjdong_clean = re.sub(r"\D", "", bjdong_10 or "")
    if len(bjdong_clean) != 10:
        return ""
    cleaned = re.sub(r"\([^)]*\)", " ", jibun_text or "").strip()

    # 1순위: '동/리/가' 바로 뒤에 오는 지번 추출 (뒤에 건물명이 붙어 있어도 정확히 매칭)
    m = re.search(r"(?:[가-힣0-9]+(?:동|리|가))\s+(산)?\s*(\d{1,4})(?:\s*-\s*(\d{1,4}))?(?!\d)", cleaned)
    # 2순위: 단독 지번 문자열('858', '395-166', '산12-3') 추출
    if not m:
        m = re.search(r"(?:^|\s)(산)?\s*(\d{1,4})(?:\s*-\s*(\d{1,4}))?\s*(?:번지|호)?(?:\s|$)", cleaned)
    if not m:
        return ""

    san_flag = "2" if m.group(1) else "1"
    bonbun = int(m.group(2))
    bubun = int(m.group(3)) if m.group(3) else 0
    return f"{bjdong_clean}{san_flag}{bonbun:04d}{bubun:04d}"


def _address_to_pnu(address: str, vworld_key: str) -> tuple[str, str]:
    """한글 지번/도로명 주소(예: '서울 강남구 역삼동 858')를 19자리 필지고유번호(PNU)로 변환합니다."""
    raw = re.sub(r"\([^)]*\)", " ", address or "").strip()
    raw = re.sub(r"\s+", " ", raw)
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 19:
        return digits, raw

    # 1차: 내장 주요 법정동 코드 사전으로 즉시 19자리 PNU 조립 (속도 최우선 및 해외 IP 지연 방어)
    for dong_nm, bjdong_10 in _MAJOR_BJDONG_MAP.items():
        if dong_nm in raw:
            built = _build_19digit_pnu(bjdong_10, raw)
            if len(built) == 19:
                return built, raw

    # 2차: 브이월드 Search API (type=address, category=parcel/road)
    s_url = "https://api.vworld.kr/req/search"
    for cat in ("parcel", "road"):
        try:
            s_res = requests.get(s_url, params={
                "service": "search", "request": "search", "version": "2.0",
                "query": raw, "type": "address", "category": cat,
                "format": "json", "key": vworld_key,
                "domain": "https://ailaw-j.streamlit.app"
            }, timeout=10).json()
            items = s_res.get("response", {}).get("result", {}).get("items", [])
            if items:
                pnu_id = re.sub(r"\D", "", str(items[0].get("id", "")))
                addr_obj = items[0].get("address", {}) or {}
                addr_title = addr_obj.get("parcel") or addr_obj.get("road") or items[0].get("title") or raw
                if len(pnu_id) == 19:
                    return pnu_id, addr_title
                elif len(pnu_id) >= 10:
                    built = _build_19digit_pnu(pnu_id[:10], addr_title) or _build_19digit_pnu(pnu_id[:10], raw)
                    if len(built) == 19:
                        return built, addr_title
        except Exception:
            continue

    # 3차: 브이월드 Address Geocode API (10자리 level4LC + level5 지번 결합)
    for addr_type in ("parcel", "PARCEL", "road", "ROAD"):
        try:
            g_url = "https://api.vworld.kr/req/address"
            g_res = requests.get(g_url, params={
                "service": "address", "request": "getcoord", "version": "2.0",
                "crs": "epsg:4326", "address": raw,
                "refine": "true", "simple": "false", "format": "json",
                "type": addr_type, "key": vworld_key,
                "domain": "https://ailaw-j.streamlit.app"
            }, timeout=10).json()
            if g_res.get("response", {}).get("status") == "OK":
                refined = g_res["response"].get("refined", {}) or {}
                struct = refined.get("structure", {}) or {}
                bjdong_10 = str(struct.get("level4LC") or struct.get("level4AC") or "").strip()
                level5 = str(struct.get("level5") or "").strip()
                full_text = refined.get("text") or raw
                built = _build_19digit_pnu(bjdong_10, level5) or _build_19digit_pnu(bjdong_10, full_text) or _build_19digit_pnu(bjdong_10, raw)
                if len(built) == 19:
                    return built, full_text
        except Exception:
            continue

    return "", "해당 주소의 19자리 필지고유번호(PNU)를 찾을 수 없습니다. 정확한 법정동+지번(예: '서울 강남구 역삼동 858') 또는 19자리 PNU 코드로 다시 입력해 주세요."


def get_vworld_official_price(address_or_pnu: str, stdr_year: str = "") -> str:
    """
    지번 주소 또는 19자리 PNU 코드를 입력받아 브이월드(V-World)에서
    1) 토지 개별공시지가(원/㎡) 및 2) 공동주택 공시가격을 통합 조회합니다.
    """
    vworld_key = _get_vworld_key()
    if not vworld_key:
        return "⚠️ 브이월드 인증키(VWORLD_API_KEY)가 설정되지 않았습니다. .env 또는 Streamlit Secrets에 VWORLD_API_KEY를 추가해 주세요."

    pnu, resolved_addr = _address_to_pnu(address_or_pnu, vworld_key)
    if not pnu:
        return f"❌ 주소 변환 실패: {resolved_addr}"

    output = [f"🏛️ [국토교통부 브이월드 공시가격 통합 조회 | 주소: {resolved_addr} (PNU: {pnu})]"]

    def _call_vworld_ned(ep_url: str, extra_params: dict) -> tuple[dict, str]:
        last_err = ""
        # 1순위: domain 파라미터 없이 호출 -> 2순위: 등록된 서비스URL들로 순차 호출
        for dom in ("", "https://ailaw-j.streamlit.app", "ailaw-j.streamlit.app", "http://ailaw-j.streamlit.app"):
            p = {**extra_params}
            if dom:
                p["domain"] = dom
            try:
                r = requests.get(ep_url, params=p, timeout=10)
                if r.status_code != 200:
                    last_err = f"HTTP {r.status_code}"
                    continue
                js = r.json()
                # 정상 데이터 블록이 있고 field가 존재하면 즉시 반환
                if "indvdLandPrices" in js:
                    if js["indvdLandPrices"].get("field"):
                        return js, ""
                    rc = js["indvdLandPrices"].get("resultCode", "")
                    rm = js["indvdLandPrices"].get("resultMsg", "")
                    if rc or rm:
                        last_err = f"{rc} {rm}".strip()
                elif "apartHousingPrices" in js:
                    if js["apartHousingPrices"].get("field"):
                        return js, ""
                    rc = js["apartHousingPrices"].get("resultCode", "")
                    rm = js["apartHousingPrices"].get("resultMsg", "")
                    if rc or rm:
                        last_err = f"{rc} {rm}".strip()
                elif "error" in js:
                    err_obj = js.get("error") or {}
                    last_err = f"{err_obj.get('code', '')}: {err_obj.get('text') or err_obj.get('message') or err_obj}"
                elif "response" in js and js["response"].get("status") == "ERROR":
                    err_obj = js["response"].get("error") or {}
                    last_err = f"{err_obj.get('code', '')}: {err_obj.get('text', '')}"
            except Exception as ex:
                last_err = str(ex)
                continue
        return {}, last_err

    req_years = re.findall(r"(?:19|20)\d{2}", stdr_year or "")

    # 1) 개별공시지가 조회 (getIndvdLandPriceAttr)
    try:
        land_url = "https://api.vworld.kr/ned/data/getIndvdLandPriceAttr"
        params = {
            "key": vworld_key,
            "pnu": pnu,
            "format": "json",
            "numOfRows": 100,
            "pageNo": 1
        }
        l_res, l_err = _call_vworld_ned(land_url, params)
        fields = l_res.get("indvdLandPrices", {}).get("field", [])
        if isinstance(fields, dict):
            fields = [fields]

        if fields:
            sorted_fields = sorted(fields, key=lambda x: str(x.get("stdrYear", "")), reverse=True)
            selected = sorted_fields[:12]
            for f in sorted_fields[12:]:
                if str(f.get("stdrYear", "")) in req_years and f not in selected:
                    selected.append(f)

            output.append("\n■ 1. 개별공시지가 (토지 기준시가, 연도별 내역):")
            for f in selected:
                yr = f.get("stdrYear", "-")
                price = str(f.get("pblntfPclnd", "0")).strip()
                p_str = f"{int(price):,}원/㎡" if price.isdigit() else f"{price}원/㎡"
                std_dt = f.get("pblntfDe", "-")
                output.append(f"- [{yr}년 기준] {p_str} (공시일자: {std_dt})")
        else:
            note = f" (사유: {l_err})" if l_err else " (도로·공공용지 등 비과세 미공시 필지이거나 지번 확인 필요)"
            output.append(f"\n■ 1. 개별공시지가: 해당 필지({pnu})의 공시지가 데이터가 조회되지 않았습니다.{note}")
    except Exception as e:
        output.append(f"\n■ 1. 개별공시지가 조회 오류: {e}")

    # 2) 공동주택 공시가격 조회 (getApartHousingPriceAttr)
    try:
        apt_url = "https://api.vworld.kr/ned/data/getApartHousingPriceAttr"
        target_yrs = req_years if req_years else ["2026", "2025", "2024"]
        a_fields = []
        for yr in target_yrs:
            a_params = {
                "key": vworld_key,
                "pnu": pnu,
                "stdrYear": yr,
                "format": "json",
                "numOfRows": 30,
                "pageNo": 1
            }
            a_res, _ = _call_vworld_ned(apt_url, a_params)
            f_list = a_res.get("apartHousingPrices", {}).get("field", [])
            if isinstance(f_list, dict):
                f_list = [f_list]
            if f_list:
                a_fields = f_list
                break

        if a_fields:
            output.append("\n■ 2. 공동주택 공시가격 (상위 표본 15건):")
            for f in a_fields[:15]:
                yr = f.get("stdrYear", "-")
                hs_nm = f.get("aphusNm", "")
                dong = f.get("dongNm", "")
                ho = f.get("hoNm", "")
                area = f.get("prvuseAr", "-")
                price = str(f.get("pblntfPc", "0")).strip()
                p_str = f"{int(price):,}원" if price.isdigit() else f"{price}원"
                output.append(f"- [{yr}년] {hs_nm} {dong}동 {ho}호 (전용 {area}㎡) -> 공시가격: {p_str}")
    except Exception:
        pass

    return "\n".join(output)
