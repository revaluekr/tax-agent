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


def get_bok_base_rate(
