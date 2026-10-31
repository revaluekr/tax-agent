import os
import io
import re
import json
import zipfile
import threading
import urllib.parse
import requests
import xml.etree.ElementTree as ET
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

def _get_api_key(key_name: str, fallback_keys: list[str] = None) -> str:
    """config.py, st.secrets, 환경변수(.env 포함)에서 실시간으로 API 키를 안전하게 추출합니다."""
    keys_to_check = [key_name] + (fallback_keys or [])
    try:
        import config
        for k in keys_to_check:
            val = getattr(config, k, None)
            if isinstance(val, str) and val.strip():
                return val.strip().strip('"').strip("'")
    except ImportError:
        pass
    try:
        import streamlit as st
        if hasattr(st, "secrets"):
            for k in keys_to_check:
                if k in st.secrets:
                    val = str(st.secrets[k]).strip().strip('"').strip("'")
                    if val:
                        return val
    except Exception:
        pass
    for k in keys_to_check:
        val = os.getenv(k, "").strip().strip('"').strip("'")
        if val:
            return val
    return ""

def _get_app_domain() -> str:
    """브이월드 등 도메인 등록형 API에 전달할 앱 주소(APP_DOMAIN)를 st.secrets/환경변수에서 읽습니다."""
    dom = _get_api_key("APP_DOMAIN") or "https://ailaw-j.streamlit.app"
    dom = dom.rstrip("/")
    return dom if dom.startswith("http") else f"https://{dom}"

LAW_OPEN_API_KEY = _get_api_key("LAW_OPEN_API_KEY", ["LAW_API_OC", "OC", "LAW_OC", "LAW_API_KEY", "MOLEG_OC", "DRF_OC"])
BOK_API_KEY = _get_api_key("BOK_API_KEY", ["ECOS_API_KEY"])
DART_API_KEY = _get_api_key("DART_API_KEY", ["OPENDART_API_KEY"])
NTS_API_KEY = _get_api_key("NTS_API_KEY", ["DATA_GO_KR_KEY", "PUBLIC_DATA_KEY", "MOLIT_API_KEY"])

def _live_law_key() -> str:
    return _get_api_key("LAW_OPEN_API_KEY", ["LAW_API_OC", "OC", "LAW_OC", "LAW_API_KEY", "MOLEG_OC", "DRF_OC"]) or LAW_OPEN_API_KEY

def _live_bok_key() -> str:
    return _get_api_key("BOK_API_KEY", ["ECOS_API_KEY"]) or BOK_API_KEY

def _live_dart_key() -> str:
    return _get_api_key("DART_API_KEY", ["OPENDART_API_KEY"]) or DART_API_KEY

def _live_nts_key() -> str:
    return _get_api_key("NTS_API_KEY", ["DATA_GO_KR_KEY", "PUBLIC_DATA_KEY", "MOLIT_API_KEY"]) or NTS_API_KEY


# ---------------------------------------------------------
# 1. 국가법령정보센터 (법령, 판례, 행정규칙, 법령해석례, 조세심판원 재결례, 지자체 조례)
# ---------------------------------------------------------
def search_law_data(keyword: str, target: str = "law", search_mode: int = None) -> list[dict]:
    """search_mode: None/1 = 제목(법령명·사건명·안건명) 검색, 2 = 본문 검색 (판례·해석례·행정규칙 주제어 검색용)"""
    law_key = _live_law_key()
    if not law_key:
        return []

    if target == "decc":
        return _search_law_data_raw(keyword, "ttSpecialDecc", search_mode, law_key)
    return _search_law_data_raw(keyword, target, search_mode, law_key)


def _search_law_data_raw(keyword: str, target: str, search_mode: int = None, law_key: str = "") -> list[dict]:
    oc_key = law_key or _live_law_key()
    url = "http://www.law.go.kr/DRF/lawSearch.do"
    params = {
        "OC": oc_key,
        "target": target,
        "type": "XML",
        "query": keyword,
        "display": 10
    }
    if search_mode:
        params["search"] = search_mode
    if target in ("prec", "ttSpecialDecc", "detc"):
        params["sort"] = "ddes"

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.encoding = "utf-8"
        if resp.status_code != 200:
            return []

        root = ET.fromstring(resp.text)

        tag_map = {
            "law": "law",
            "prec": "prec",
            "detc": "Detc",
            "admrul": "admrul",
            "expc": "expc",
            "decc": "decc",
            "ttSpecialDecc": "decc",
            "ordin": "law",
            "licbyl": "licbyl",
        }
        item_tag = tag_map.get(target, target)
        items = root.findall(f".//{item_tag}")
        if not items and target == "detc":
            items = root.findall(".//detc") or root.findall(".//Detc")
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
_CIRCLED_NUM = {chr(0x2460 + i): i + 1 for i in range(20)}

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

def _slim_large_addendum_block(full_blk: str, query_filter: str = "") -> str:
    """
    대용량 부칙 블록(예: 법률 제21223호 부칙 60여 개 조문)에서 앞부분 3,000~4,500자 절삭으로 인해
    중간에 위치한 핵심 경과조치(예: 제34조 통합고용세액공제에 관한 경과조치)가 잘려 나가는 문제를 방지합니다.
    - 부칙 헤더 + 제1조(시행일) + 제2조(일반적 적용례) + query_filter의 조문번호/키워드 또는 고용세액공제 관련 조문만 정밀 발췌합니다.
    """
    if not full_blk or len(full_blk) <= 2000:
        return full_blk

    lines = full_blk.splitlines()
    header_line = lines[0] if lines else "부칙"
    body_text = "\n".join(lines[1:])

    art_starts = list(re.finditer(r"(?m)^\s*제\s*(\d+)\s*조(?:\s*의\s*(\d+))?(?:\s*\(|\s+)", body_text))
    if len(art_starts) <= 3:
        return full_blk[:4500]

    qf_nospace = (query_filter or "").replace(" ", "")
    req_arts = [a.replace(" ", "") for a in re.findall(r"제\s*\d+\s*조(?:\s*의\s*\d+)?", query_filter or "")]
    priority_keywords = ["통합고용", "고용증대", "상시근로자", "경과조치", "적용례"]
    for kw in re.split(r"[,\s]+", re.sub(r"부칙|제\s*\d+\s*조(?:\s*의\s*\d+)?", " ", query_filter or "")):
        kw_s = kw.strip()
        if len(kw_s) >= 2 and kw_s not in priority_keywords:
            priority_keywords.append(kw_s)

    kept_chunks = []
    for idx, m in enumerate(art_starts):
        jo_num = int(m.group(1))
        gaji_num = int(m.group(2) or 0)
        art_label = f"제{jo_num}조" + (f"의{gaji_num}" if gaji_num else "")
        end_pos = art_starts[idx + 1].start() if idx + 1 < len(art_starts) else len(body_text)
        chunk = body_text[m.start():end_pos].strip()
        chunk_ns = chunk.replace(" ", "")

        # 제1조(시행일), 제2조(적용례)는 기본 유지하고, 요청 조문번호나 핵심 키워드가 포함된 부칙 조문을 최우선 보존
        if jo_num in (1, 2) and len(chunk) <= 800:
            kept_chunks.append(chunk)
        elif art_label in req_arts or any(ra in chunk_ns for ra in req_arts):
            kept_chunks.append(chunk)
        elif any(pk in chunk_ns for pk in ("통합고용", "고용증대", "제29조의8", "제26조의8")):
            kept_chunks.append(chunk)
        elif qf_nospace and any(pk in chunk_ns for pk in priority_keywords if pk not in ("경과조치", "적용례")):
            kept_chunks.append(chunk)

    if not kept_chunks:
        return full_blk[:4000]
    return header_line + "\n" + "\n\n".join(kept_chunks)


def _extract_addenda_blocks(root, query_filter: str = "", max_recent: int = 8) -> list[str]:
    """
    법제처 법령 XML의 <부칙단위>에서 공포일자·공포번호·부칙내용을 최신순으로 추출합니다.
    - 최신 타법개정(예: 법률 제21467호) 뒤에 있는 본 개정 부칙(예: 법률 제21223호 부칙 제34조)도 누락 없이 포착하며,
      대용량 부칙은 `_slim_large_addendum_block`으로 핵심 조문을 발췌하여 반환합니다.
    """
    raw_units = root.findall(".//부칙단위")
    if not raw_units:
        return []

    parsed_units = []
    for u in raw_units:
        anc_dt = re.sub(r"\D", "", u.findtext("부칙공포일자") or "")
        anc_no = (u.findtext("부칙공포번호") or "").strip()
        content = (u.findtext("부칙내용") or "").strip()
        if not content:
            content = "\n".join(t.strip() for t in u.itertext() if t and t.strip())
        if not content:
            continue
        dt_fmt = f"{anc_dt[:4]}.{anc_dt[4:6]}.{anc_dt[6:]}." if len(anc_dt) == 8 else anc_dt
        no_fmt = f"제{anc_no}호, " if anc_no else ""
        head = f"부칙 <{no_fmt}{dt_fmt}>".strip()
        full_blk = f"{head}\n{content}" if not content.startswith("부칙") else f"[{head}]\n{content}"
        parsed_units.append((int(anc_dt) if anc_dt.isdigit() else 0, anc_no, full_blk))

    parsed_units.sort(key=lambda x: x[0], reverse=True)

    qf_clean = re.sub(r"부칙", "", query_filter or "").strip()
    art_refs = re.findall(r"제\s*\d+\s*조(?:\s*의\s*\d+)?", qf_clean)
    yr_refs = re.findall(r"20\d{2}", qf_clean)
    no_refs = re.findall(r"\b\d{4,6}\b", qf_clean)

    matched_blocks = []
    for dt_int, anc_no, blk in parsed_units:
        blk_nospace = blk.replace(" ", "")
        if art_refs and any(a.replace(" ", "") in blk_nospace for a in art_refs):
            matched_blocks.append(_slim_large_addendum_block(blk, query_filter))
        elif no_refs and any(n in anc_no or n in blk_nospace for n in no_refs):
            matched_blocks.append(_slim_large_addendum_block(blk, query_filter))
        elif yr_refs and any(str(dt_int).startswith(y) or y in blk_nospace for y in yr_refs):
            matched_blocks.append(_slim_large_addendum_block(blk, query_filter))
        elif qf_clean and not art_refs and qf_clean.replace(" ", "") in blk_nospace:
            matched_blocks.append(_slim_large_addendum_block(blk, query_filter))

    if matched_blocks:
        return matched_blocks[:max_recent]
    return [_slim_large_addendum_block(blk, query_filter) for _, _, blk in parsed_units[:max_recent]]


def _get_statute_articles(doc_id: str, query_filter: str = "") -> str:
    """법령 원문에서 조문 및 개정 부칙(적용례·경과조치)을 정밀 추출합니다."""
    law_key = _live_law_key()
    url = "http://www.law.go.kr/DRF/lawService.do"
    wants_addendum = "부칙" in (query_filter or "")
    art_filter = _parse_article_filter(query_filter) if not wants_addendum else _parse_article_filter(re.sub(r"부칙[^,]*", "", query_filter or ""))
    base = {"OC": law_key, "target": "law", "type": "XML"}

    attempts = []
    # 부칙을 함께 조회해야 할 때는 JO 단일조문 호출(부칙 미포함) 대신 전체 법령 XML 호출을 우선 실행
    if art_filter and not wants_addendum:
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
        addenda_nodes = root.findall(".//부칙단위")
        if not articles and not addenda_nodes:
            continue

        found_any_law = True
        title = (root.findtext(".//법령명_한글") or root.findtext(".//법령명한글") or title).strip()
        law_prom_no = (root.findtext(".//공포번호") or "").strip()
        law_prom_dt = re.sub(r"\D", "", root.findtext(".//공포일자") or "")
        law_eff = re.sub(r"\D", "", root.findtext(".//시행일자") or "")
        prom_no_note = f" | 공포번호: 제{law_prom_no}호" if law_prom_no else ""
        prom_dt_note = f" | 공포일자: {law_prom_dt[:4]}.{law_prom_dt[4:6]}.{law_prom_dt[6:]}" if len(law_prom_dt) == 8 else ""
        eff_note = f" | 시행일자: {law_eff[:4]}.{law_eff[4:6]}.{law_eff[6:]}" if len(law_eff) == 8 else ""
        header = f"📘 [{title}{prom_no_note}{prom_dt_note}{eff_note}] (일련번호: {doc_id})"

        # 1) '부칙' 단독 또는 '제29조의8, 부칙' 복합 조회
        if wants_addendum:
            out_sections = []
            if art_filter and articles:
                jo, gaji, hang = art_filter
                matched_arts = [
                    a for a in articles
                    if _to_int(a.findtext("조문번호")) == jo and _to_int(a.findtext("조문가지번호")) == gaji
                ]
                if matched_arts:
                    out_sections.append("\n\n".join(_format_article(a, only_hang=hang) for a in matched_arts))
            add_blocks = _extract_addenda_blocks(root, query_filter=query_filter, max_recent=6)
            if add_blocks:
                out_sections.append("📌 [법령 부칙 (시행일 · 적용례 · 경과조치)]\n\n" + "\n\n".join(add_blocks))
            if out_sections:
                return (header + "\n\n" + "\n\n".join(out_sections))[:16000]

        # 2) 일반 조문번호 조회 (+ 전체 XML인 경우 해당 조문 관련 최근 부칙 자동 첨부)
        if art_filter:
            jo, gaji, hang = art_filter
            matched = [
                a for a in articles
                if _to_int(a.findtext("조문번호")) == jo and _to_int(a.findtext("조문가지번호")) == gaji
            ]
            if matched:
                body = "\n\n".join(_format_article(a, only_hang=hang) for a in matched)
                art_label = f"제{jo}조" + (f"의{gaji}" if gaji else "")
                rel_add = _extract_addenda_blocks(root, query_filter=art_label, max_recent=3)
                rel_add = [b for b in rel_add if art_label in b.replace(" ", "")]
                if rel_add:
                    body += "\n\n📌 [관련 최근 개정 부칙(적용례·경과조치) 발췌]\n" + "\n\n".join(rel_add)[:3000]
                return (header + "\n\n" + body)[:16000]
            continue

        if query_filter:
            kw = query_filter.replace(" ", "")
            matched = []
            for a in articles:
                txt = _format_article(a)
                if kw in txt.replace(" ", ""):
                    matched.append(txt)
            for b in _extract_addenda_blocks(root, query_filter=query_filter, max_recent=5):
                if kw in b.replace(" ", ""):
                    matched.append(b)
            if not matched:
                return f"'{title}' 내에서 '{query_filter}' 키워드가 포함된 조문·부칙을 찾지 못했습니다. 조문번호(예: '제29조의8') 또는 '부칙'으로 다시 조회하세요."
            note = f"\n\n[※ 키워드 포함 조문·부칙 {len(matched)}개 중 앞 8개만 표시]" if len(matched) > 8 else ""
            return (header + "\n\n" + "\n\n".join(matched[:8]))[:14000] + note

        body = "\n\n".join(_format_article(a) for a in articles)
        return (header + "\n\n" + body)[:12000] + "\n\n[※ 전체 조문 중 앞부분만 표시. 조문번호나 '부칙'을 지정해 다시 조회하세요]"

    if art_filter and found_any_law:
        jo, gaji, _ = art_filter
        label = f"제{jo}조" + (f"의{gaji}" if gaji else "")
        return f"'{title}'에서 {label}를 찾지 못했습니다. 법률/시행령 일련번호를 혼동하지 않았는지 확인하세요."
    return f"❌ 일련번호 '{doc_id}'로 법령 원문을 불러오지 못했습니다. search_law_for_gemini로 일련번호를 다시 확인하세요."


def get_law_content(doc_id: str, target: str = "law", query_filter: str = "") -> str:
    law_key = _live_law_key()
    if not law_key:
        return "❌ LAW_OPEN_API_KEY가 설정되지 않았습니다."

    if target == "law":
        try:
            return _get_statute_articles(doc_id, query_filter)
        except Exception as e:
            return f"❌ 법령 조문 조회 중 오류 발생: {e}"

    url = "http://www.law.go.kr/DRF/lawService.do"
    api_target = "ttSpecialDecc" if target == "decc" else target
    params = {
        "OC": law_key,
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

        elif target == "detc":
            case_name = root.findtext(".//사건명") or ""
            case_no = root.findtext(".//사건번호") or ""
            dec_date = root.findtext(".//종국일자") or root.findtext(".//선고일자") or ""
            holding = root.findtext(".//판시사항") or ""
            summary = root.findtext(".//결정요지") or ""
            target_law = root.findtext(".//심판대상조문") or ""
            ref_law = root.findtext(".//참조조문") or ""
            full_body = root.findtext(".//전문") or ""

            text = (
                f"⚖️ [헌법재판소 결정례 상세] {case_name} ({case_no}, 종국일: {dec_date})\n"
                f"■ 판시사항:\n{holding}\n\n"
                f"■ 결정요지:\n{summary}\n\n"
                f"■ 심판대상조문:\n{target_law}\n\n"
                f"■ 참조조문:\n{ref_law}\n\n"
                f"■ 결정전문(주문·이유 발췌):\n{full_body[:6000]}"
            )
            return text[:14000]

        elif target == "licbyl":
            byl_name = root.findtext(".//별표명") or ""
            law_name_rel = root.findtext(".//관련법령명") or ""
            byl_no = root.findtext(".//별표번호") or ""
            byl_kind = root.findtext(".//별표구분") or "별표/서식"
            byl_content = root.findtext(".//별표내용") or ""
            if not byl_content:
                byl_content = "\n".join(t.strip() for t in root.itertext() if t and t.strip())
            text = (
                f"📊 [{byl_kind} 상세] {law_name_rel} - {byl_name} (번호: {byl_no}, ID: {doc_id})\n\n"
                f"{byl_content[:12000]}"
            )
            return text[:14000]

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
    bok_key = _live_bok_key()
    if not bok_key:
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

    url = f"https://ecos.bok.or.kr/api/StatisticSearch/{bok_key}/json/kr/1/30/731Y001/D/{s_date}/{e_date}/{item_code}"
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
    bok_key = _live_bok_key()
    if not bok_key:
        return "❌ BOK_API_KEY가 설정되지 않았습니다."

    s_date = start_date.replace("-", "").strip()
    e_date = end_date.replace("-", "").strip()
    url = f"https://ecos.bok.or.kr/api/StatisticSearch/{bok_key}/json/kr/1/30/722Y001/D/{s_date}/{e_date}/0101000"
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
# 3. 국세청 기준경비율 6자리 업종코드 마스터 엑셀/CSV 검색 (멀티스레드 Lock 적용)
# ---------------------------------------------------------
_INDUSTRY_DF_CACHE = None
_INDUSTRY_LOCK = threading.Lock()

def search_industry_code(keyword: str) -> str:
    global _INDUSTRY_DF_CACHE
    try:
        with _INDUSTRY_LOCK:
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
# 4. 금융감독원 전자공시시스템 (Open DART) 6대 핵심 정보 통합 조회 (멀티스레드 Lock 적용)
# ---------------------------------------------------------
_DART_CORP_CACHE = None
_DART_LOCK = threading.Lock()

def _load_dart_corp_codes() -> list[dict]:
    global _DART_CORP_CACHE
    dart_key = _live_dart_key()
    if not dart_key:
        return []

    with _DART_LOCK:
        if _DART_CORP_CACHE is not None:
            return _DART_CORP_CACHE

        cache_file = ".workspace_storage/dart_corp_codes.xml"
        os.makedirs(".workspace_storage", exist_ok=True)

        try:
            if not os.path.exists(cache_file):
                url = f"https://opendart.fss.or.kr/api/corpCode.xml?crtfc_key={dart_key}"
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
    dart_key = _live_dart_key()
    if not dart_key:
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
        info_res = requests.get(info_url, params={"crtfc_key": dart_key, "corp_code": corp_code}, timeout=10).json()
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
            "crtfc_key": dart_key,
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
                "crtfc_key": dart_key,
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
        output.append("\n■ 3. 주요 재무제표 요약: 정기 사업보고서 제출 대상이 아니거나 비상장 외감법인(감사보고서 원문 공시 대상)입니다. 위 2번 공시 목록의 감사보고서 링크를 참고하세요.")

    try:
        sh_url = "https://opendart.fss.or.kr/api/hyslrSttus.json"
        sh_res = requests.get(sh_url, params={
            "crtfc_key": dart_key,
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
            "crtfc_key": dart_key,
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
            "crtfc_key": dart_key,
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
    nts_key = _live_nts_key()
    if not nts_key:
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
    encoded_key = nts_key if "%" in nts_key else urllib.parse.quote(nts_key, safe="")
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
    nts_key = _live_nts_key()
    if not nts_key:
        return "❌ NTS_API_KEY가 설정되지 않았습니다."

    clean_bno = re.sub(r"\D", "", b_no)
    clean_dt = re.sub(r"\D", "", start_dt)
    if len(clean_bno) != 10 or len(clean_dt) != 8 or not p_nm.strip():
        return "❌ 진위확인을 위해서는 10자리 사업자번호, 8자리 개업일자(YYYYMMDD), 대표자 성명이 모두 필요합니다."

    encoded_key = nts_key if "%" in nts_key else urllib.parse.quote(nts_key, safe="")
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
    "종로구": "11110", "중구": "11140", "용산구": "11170", "성동구": "11200", "광진구": "11215",
    "동대문구": "11230", "중랑구": "11260", "성북구": "11290", "강북구": "11305", "도봉구": "11320",
    "노원구": "11350", "은평구": "11380", "서대문구": "11410", "마포구": "11440", "양천구": "11470",
    "강서구": "11500", "구로구": "11530", "금천구": "11545", "영등포구": "11560", "동작구": "11590",
    "관악구": "11620", "서초구": "11650", "강남구": "11680", "송파구": "11710", "강동구": "11740",
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
    nts_key = _live_nts_key()
    if not nts_key:
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

    encoded_key = nts_key if "%" in nts_key else urllib.parse.quote(nts_key, safe="")

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

        for data in items:
            raw_str = " ".join(data.values())
            if kw and kw not in raw_str:
                continue

            umd = data.get("umdNm") or data.get("법정동") or data.get("dong") or ""
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
# 6-2. 국토교통부 부동산 전월세 실거래가 4종 통합 조회 (아파트 / 오피스텔 / 연립다세대 / 단독다가구)
# ---------------------------------------------------------
def get_molit_real_estate_rent(property_type: str, region: str, deal_ymd: str, filter_keyword: str = "") -> str:
    """
    공공데이터포털 인증키(NTS_API_KEY)를 사용하여 국토교통부 전월세(보증금·월세) 실거래가를 조회합니다.
    - property_type: 'apt'(아파트), 'offi'(오피스텔), 'rh'/'villa'(연립다세대·빌라), 'sh'/'house'(단독·다가구)
    - region: 시·군·구 명칭(예: '강남구', '분당구') 또는 5자리 LAWD_CD(예: '11680')
    - deal_ymd: 계약연월 6자리 'YYYYMM'(예: '202609')
    """
    nts_key = _live_nts_key()
    if not nts_key:
        return "❌ NTS_API_KEY(공공데이터포털 인증키)가 설정되지 않았습니다."

    lawd_cd = _resolve_lawd_cd(region)
    if not lawd_cd:
        return f"❌ '{region}'에 해당하는 5자리 법정동코드를 찾지 못했습니다. 시·군·구 명칭(예: '강남구', '서초구', '분당구')이나 5자리 법정동코드(예: '11680')로 다시 입력해 주세요."

    ymd = re.sub(r"\D", "", deal_ymd)[:6]
    if len(ymd) != 6:
        return f"❌ 계약연월('{deal_ymd}')은 'YYYYMM' 6자리 형식(예: '202609')이어야 합니다."

    ptype = (property_type or "").lower().strip()
    if ptype in ("오피스텔", "offi", "officetel"):
        endpoint = "https://apis.data.go.kr/1613000/RTMSDataSvcOffiRent/getRTMSDataSvcOffiRent"
        type_label = "오피스텔 전월세"
    elif ptype in ("연립", "다세대", "연립다세대", "빌라", "rh", "villa"):
        endpoint = "https://apis.data.go.kr/1613000/RTMSDataSvcRHRent/getRTMSDataSvcRHRent"
        type_label = "연립·다세대(빌라) 전월세"
    elif ptype in ("단독", "다가구", "단독다가구", "sh", "house"):
        endpoint = "https://apis.data.go.kr/1613000/RTMSDataSvcSHRent/getRTMSDataSvcSHRent"
        type_label = "단독·다가구 전월세"
    else:
        endpoint = "https://apis.data.go.kr/1613000/RTMSDataSvcAptRent/getRTMSDataSvcAptRent"
        type_label = "아파트(공동주택) 전월세"

    encoded_key = nts_key if "%" in nts_key else urllib.parse.quote(nts_key, safe="")
    full_url = f"{endpoint}?serviceKey={encoded_key}&LAWD_CD={lawd_cd}&DEAL_YMD={ymd}&numOfRows=200&pageNo=1"

    try:
        resp = requests.get(full_url, timeout=15)
        if resp.status_code != 200:
            return (
                f"❌ 국토교통부 전월세 API 호출 실패 (HTTP {resp.status_code}): "
                "공공데이터포털(data.go.kr)에서 '국토교통부_아파트/오피스텔/연립다세대/단독다가구 전월세 실거래가 자료' 활용신청 여부를 확인해 주세요."
            )

        items_dict_list, err_msg = _parse_data_go_kr_items(resp.text, f"국토교통부 {type_label}")
        if err_msg:
            return err_msg
        items = items_dict_list
        if not items:
            return f"조회된 [{type_label}] 실거래 내역이 없습니다. (지역코드: {lawd_cd}, 계약연월: {ymd})"

        kw = (filter_keyword or "").strip()
        parsed_rows = []
        for data in items:
            raw_str = " ".join(data.values())
            if kw and kw not in raw_str:
                continue

            umd = data.get("umdNm") or data.get("법정동") or ""
            jibun = data.get("jibun") or data.get("지번") or ""
            bldg_nm = (
                data.get("aptNm")
                or data.get("offiNm")
                or data.get("mhouseNm")
                or data.get("아파트")
                or data.get("단지")
                or "단독/다가구"
            )
            area = data.get("excluUseAr") or data.get("cntrArea") or data.get("전용면적") or data.get("계약면적") or "-"
            floor = data.get("floor") or data.get("층") or "-"
            build_yr = data.get("buildYear") or data.get("건축년도") or "-"
            dep = data.get("deposit") or data.get("보증금액") or "0"
            m_rent = data.get("monthlyRent") or data.get("월세금액") or "0"
            m_rent_clean = re.sub(r"[^0-9]", "", m_rent)
            rent_kind = "전세" if (not m_rent_clean or int(m_rent_clean) == 0) else f"월세 {m_rent}만원"
            deal_day = f"{ymd[:4]}-{ymd[4:6]}-{str(data.get('dealDay') or data.get('일') or '01').zfill(2)}"
            c_type = data.get("contractType") or data.get("계약구분") or ""
            c_term = data.get("contractTerm") or data.get("계약기간") or ""
            extra_tag = f" ({c_type}{', ' + c_term if c_term else ''})" if c_type or c_term else ""

            parsed_rows.append(
                f"- [{deal_day}] {umd} {bldg_nm} ({jibun}) | 전용/계약 {area}㎡ ({floor}층, 건축:{build_yr}년) | "
                f"보증금: {dep}만원 / {rent_kind}{extra_tag}"
            )

        if not parsed_rows:
            return f"지역({lawd_cd})·연월({ymd})의 전체 전월세 {len(items)}건 중 '{kw}' 키워드가 포함된 내역이 없습니다."

        header = f"🏠 [국토교통부 {type_label} 실거래가 조회 결과 | 지역:{region}({lawd_cd}) | 연월:{ymd} | 검색:{kw or '전체'} (총 {len(parsed_rows)}건 중 최근 25건)]"
        return header + "\n" + "\n".join(parsed_rows[:25])
    except Exception as e:
        return f"❌ 국토교통부 전월세 실거래가 조회 중 오류 발생: {e}"


# ---------------------------------------------------------
# 7. 국토교통부 브이월드(V-World) 개별공시지가 및 공동주택 공시가격 조회
# ---------------------------------------------------------
_MAJOR_BJDONG_MAP = {
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
    return _get_api_key("VWORLD_API_KEY")


def _build_19digit_pnu(bjdong_10: str, jibun_text: str) -> str:
    """10자리 법정동코드와 지번 문자열(예: '858', '대치동 316 (은마아파트)', '395-166')을 결합해 19자리 PNU를 생성합니다."""
    bjdong_clean = re.sub(r"\D", "", bjdong_10 or "")
    if len(bjdong_clean) != 10:
        return ""
    cleaned = re.sub(r"\([^)]*\)", " ", jibun_text or "").strip()

    m = re.search(r"(?:[가-힣0-9]+(?:동|리|가))\s+(산)?\s*(\d{1,4})(?:\s*-\s*(\d{1,4}))?(?!\d)", cleaned)
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

    for dong_nm, bjdong_10 in _MAJOR_BJDONG_MAP.items():
        if dong_nm in raw:
            built = _build_19digit_pnu(bjdong_10, raw)
            if len(built) == 19:
                return built, raw

    s_url = "https://api.vworld.kr/req/search"
    for cat in ("parcel", "road"):
        try:
            s_res = requests.get(s_url, params={
                "service": "search", "request": "search", "version": "2.0",
                "query": raw, "type": "address", "category": cat,
                "format": "json", "key": vworld_key,
                "domain": _get_app_domain()
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

    for addr_type in ("parcel", "PARCEL", "road", "ROAD"):
        try:
            g_url = "https://api.vworld.kr/req/address"
            g_res = requests.get(g_url, params={
                "service": "address", "request": "getcoord", "version": "2.0",
                "crs": "epsg:4326", "address": raw,
                "refine": "true", "simple": "false", "format": "json",
                "type": addr_type, "key": vworld_key,
                "domain": _get_app_domain()
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
    지번 주소 또는 19자리 PNU 코드를 입력받아
    1) 토지 개별공시지가(원/㎡) 및 2) 공동주택 공시가격을 조회합니다.
    (stdrYear 명시 호출 및 해외 클라우드 IP의 HTTP 502 우회 게이트웨이 5종 탑재)
    """
    vworld_key = _get_vworld_key()
    if not vworld_key:
        return "⚠️ 브이월드 인증키(VWORLD_API_KEY)가 설정되지 않았습니다. .env 또는 Streamlit Secrets에 VWORLD_API_KEY를 추가해 주세요."

    pnu, resolved_addr = _address_to_pnu(address_or_pnu, vworld_key)
    if not pnu:
        return f"❌ 주소 변환 실패: {resolved_addr}"

    output = [f"🏛️ [국토교통부 브이월드 공시가격 통합 조회 | 주소: {resolved_addr} (PNU: {pnu})]"]

    browser_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
    }

    def _parse_vworld_payload(raw_txt: str) -> dict:
        if not raw_txt:
            return {}
        txt = raw_txt.strip()
        try:
            js = json.loads(txt)
            # allorigins /get 래퍼인 경우 contents 내부 JSON 추출
            if isinstance(js, dict) and "contents" in js and isinstance(js["contents"], str):
                inner = js["contents"].strip()
                if inner.startswith("{"):
                    js = json.loads(inner)
            if isinstance(js, dict) and ("indvdLandPrices" in js or "apartHousingPrices" in js or "response" in js):
                return js
        except Exception:
            pass
        return {}

    def _fetch_json_with_bypass(target_url: str, params: dict) -> tuple[dict, str]:
        """직접 호출(한국 IP/로컬) 시도 후 해외 IP 차단(HTTP 502) 발생 시 5종 우회 게이트웨이를 순차 시도합니다."""
        last_err = ""
        params_with_dom = {**params, "domain": _get_app_domain()}
        url_dom = f"{target_url}?{urllib.parse.urlencode(params_with_dom)}"
        url_nodom = f"{target_url}?{urllib.parse.urlencode(params)}"

        # 1차: 직접 호출 (로컬 PC 한국 IP에서는 즉시 통과)
        for direct_u in (url_nodom, url_dom):
            try:
                r = requests.get(direct_u, headers=browser_headers, timeout=5)
                if r.status_code == 200:
                    parsed = _parse_vworld_payload(r.text)
                    if parsed:
                        return parsed, ""
                last_err = f"HTTP {r.status_code}"
            except Exception as e:
                last_err = str(e)

        # 2차: Streamlit Cloud(해외 IP) 502 차단 우회용 공개 게이트웨이
        # 보안: 공개 우회 서버로 보내는 주소에는 브이월드 인증키(key=)가 그대로 들어가 제3자 서버에 노출되므로
        #       기본값은 사용 안 함. Secrets에 VWORLD_USE_PUBLIC_PROXY = "on" 을 넣은 경우에만 사용합니다.
        if _get_api_key("VWORLD_USE_PUBLIC_PROXY").lower() not in ("on", "true", "1", "yes"):
            return {}, last_err
        enc_u = urllib.parse.quote(url_nodom, safe="")
        proxy_candidates = [
            f"https://api.allorigins.win/get?url={enc_u}",
            f"https://api.allorigins.win/raw?url={enc_u}",
            f"https://api.codetabs.com/v1/proxy?quest={enc_u}",
            f"https://corsproxy.io/?url={enc_u}",
            f"https://thingproxy.freeboard.io/fetch/{url_nodom}",
        ]
        for p_url in proxy_candidates:
            try:
                r = requests.get(p_url, headers=browser_headers, timeout=8)
                if r.status_code == 200:
                    parsed = _parse_vworld_payload(r.text)
                    if parsed:
                        return parsed, ""
            except Exception:
                continue

        return {}, last_err

    req_years = re.findall(r"(?:19|20)\d{2}", stdr_year or "")
    # 브이월드 API는 stdrYear(기준연도)를 지정해야 정확히 반환하므로 요청 연도 또는 최근 연도(2025, 2024, 2020) 순회
    target_years = list(dict.fromkeys(req_years + ["2025", "2024"])) if req_years else ["2025", "2024", "2023", "2020"]

    # 1) 개별공시지가 조회 (getIndvdLandPriceAttr)
    try:
        land_url = "https://api.vworld.kr/ned/data/getIndvdLandPriceAttr"
        fields = []
        last_err = ""

        for yr in target_years[:4]:
            params = {
                "key": vworld_key,
                "pnu": pnu,
                "stdrYear": yr,
                "format": "json",
                "numOfRows": 10,
                "pageNo": 1
            }
            l_res, err = _fetch_json_with_bypass(land_url, params)
            if err:
                last_err = err
            f_item = l_res.get("indvdLandPrices", {}).get("field", [])
            if isinstance(f_item, dict):
                fields.append(f_item)
            elif isinstance(f_item, list) and f_item:
                fields.extend(f_item)

        if fields:
            sorted_fields = sorted(fields, key=lambda x: str(x.get("stdrYear", "")), reverse=True)
            output.append("\n■ 1. 개별공시지가 (토지 기준시가, 연도별 내역):")
            seen_yrs = set()
            for f in sorted_fields:
                yr = str(f.get("stdrYear", "-"))
                if yr in seen_yrs:
                    continue
                seen_yrs.add(yr)
                price = str(f.get("pblntfPclnd", "0")).strip()
                p_str = f"{int(price):,}원/㎡" if price.isdigit() else f"{price}원/㎡"
                std_dt = f.get("pblntfDe", "-")
                ld_nm = f.get("ldCodeNm", "")
                mnnm = f.get("mnnmSlno", "")
                loc_txt = f" ({ld_nm} {mnnm})" if ld_nm else ""
                output.append(f"- [{yr}년 기준] {p_str} (공시일자: {std_dt}){loc_txt}")
        else:
            note = f" (사유: {last_err})" if last_err else ""
            output.append(f"\n■ 1. 개별공시지가: 브이월드 서버의 해외 클라우드 IP 접속 제한(HTTP 502)으로 실시간 단가를 불러오지 못했습니다.{note}")
    except Exception as e:
        output.append(f"\n■ 1. 개별공시지가 조회 오류: {e}")

    # 2) 공동주택 공시가격 조회 (getApartHousingPriceAttr)
    try:
        apt_url = "https://api.vworld.kr/ned/data/getApartHousingPriceAttr"
        a_fields = []
        for yr in ["2025", "2024"]:
            a_params = {
                "key": vworld_key,
                "pnu": pnu,
                "stdrYear": yr,
                "format": "json",
                "numOfRows": 30,
                "pageNo": 1
            }
            a_res, _ = _fetch_json_with_bypass(apt_url, a_params)
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

# ---------------------------------------------------------
# 8. 국토교통부 건축물대장 표제부 · 층별개요 조회 (겸용주택 주택/상가 면적 비율 · 주용도 · 위반건축물 판정용)
# ---------------------------------------------------------
def _parse_data_go_kr_items(raw_text: str, service_label: str) -> tuple[list[dict], str]:
    """
    공공데이터포털(apis.data.go.kr)의 XML 또는 JSON 응답을 모두 파싱하여 (items_dict_list, error_msg)를 반환합니다.
    특히 활용신청 직후 게이트웨이 키 동기화 대기(10분~1시간) 중에 발생하는
    <cmmMsgHeader><returnReasonCode>30</returnReasonCode><returnAuthMsg>SERVICE_KEY_IS_NOT_REGISTERED_ERROR</returnAuthMsg>
    에러를 정밀 감지하여 명확한 안내 메시지를 반환합니다.
    """
    txt = (raw_text or "").strip()
    if not txt:
        return [], f"❌ {service_label} API로부터 빈 응답이 반환되었습니다."

    # 1) JSON 응답인 경우 자동 처리
    if txt.startswith("{") or txt.startswith("["):
        try:
            js = json.loads(txt)
            if isinstance(js, dict):
                cmm = js.get("cmmMsgHeader") or (js.get("OpenAPI_ServiceResponse", {}) or {}).get("cmmMsgHeader") or {}
                if cmm:
                    r_code = str(cmm.get("returnReasonCode") or "").strip()
                    r_auth = str(cmm.get("returnAuthMsg") or cmm.get("errMsg") or "").strip()
                    if r_code == "30" or "NOT_REGISTERED" in r_auth:
                        return [], (
                            f"⏳ [{service_label}] 공공데이터포털 인증키 동기화 대기 중 (코드 30: {r_auth})\n"
                            "→ 공공데이터포털(data.go.kr)에서 [활용신청] 승인 직후에는 게이트웨이 서버에 인증키가 전파되는 데 약 10분~1시간이 소요됩니다. 잠시 후 다시 조회해 주세요."
                        )
                    if r_code == "20" or "ACCESS_DENIED" in r_auth:
                        return [], (
                            f"⏳ [{service_label}] 공공데이터포털 서비스 접근 권한 미반영 (코드 20: {r_auth})\n"
                            "→ 활용신청을 방금 완료하셨다면 키 동기화까지 약 10~30분 정도 기다려 주시고, 아직 신청 전이라면 data.go.kr에서 활용신청을 진행해 주세요."
                        )
                    return [], f"❌ [{service_label}] 게이트웨이 오류 (코드 {r_code}): {r_auth}"

                resp_obj = js.get("response") or js
                header = resp_obj.get("header") or {}
                res_code = str(header.get("resultCode") or "").strip()
                res_msg = str(header.get("resultMsg") or "").strip()
                if res_code not in ("00", "000", "0000", ""):
                    return [], f"❌ [{service_label}] API 응답 오류 (코드 {res_code}): {res_msg}"

                body = resp_obj.get("body") or {}
                items_node = body.get("items")
                if isinstance(items_node, dict):
                    item_list = items_node.get("item")
                elif isinstance(items_node, list):
                    item_list = items_node
                else:
                    item_list = []

                if isinstance(item_list, dict):
                    item_list = [item_list]
                elif not isinstance(item_list, list):
                    item_list = []

                cleaned_items = []
                for it in item_list:
                    if isinstance(it, dict):
                        cleaned_items.append({str(k): str(v).strip() if v is not None else "" for k, v in it.items()})
                return cleaned_items, ""
        except Exception as e:
            return [], f"❌ [{service_label}] JSON 응답 파싱 실패: {e}"

    # 2) XML 응답인 경우 처리
    try:
        root = ET.fromstring(txt)
    except Exception as e:
        return [], f"❌ [{service_label}] XML 응답 파싱 실패: {e}"

    reason_code = (root.findtext(".//returnReasonCode") or "").strip()
    auth_msg = (root.findtext(".//returnAuthMsg") or "").strip()
    err_msg = (root.findtext(".//errMsg") or "").strip()
    if reason_code or auth_msg:
        combined_err = f"{auth_msg} ({err_msg})" if err_msg and err_msg != auth_msg else (auth_msg or err_msg)
        if reason_code == "30" or "NOT_REGISTERED" in combined_err:
            return [], (
                f"⏳ [{service_label}] 공공데이터포털 인증키 동기화 대기 중 (코드 {reason_code}: {combined_err})\n"
                "→ 공공데이터포털(data.go.kr)에서 [활용신청] 승인 직후에는 실제 API 게이트웨이 서버에 인증키 권한이 반영되는 데 약 10분~1시간이 소요됩니다. 잠시 후 다시 조회해 주세요."
            )
        if reason_code == "20" or "ACCESS_DENIED" in combined_err:
            return [], (
                f"⏳ [{service_label}] 공공데이터포털 서비스 접근 권한 미반영 (코드 {reason_code}: {combined_err})\n"
                "→ 활용신청을 방금 완료하셨다면 키 동기화까지 약 10~30분 정도 기다려 주시고, 아직 신청 전이라면 data.go.kr에서 활용신청을 진행해 주세요."
            )
        return [], f"❌ [{service_label}] 공공데이터포털 게이트웨이 오류 (코드 {reason_code}): {combined_err}"

    res_code = (root.findtext(".//resultCode") or "").strip()
    res_msg = (root.findtext(".//resultMsg") or "").strip()
    if res_code not in ("00", "000", "0000", ""):
        return [], f"❌ [{service_label}] API 응답 오류 (코드 {res_code}): {res_msg}"

    items = []
    for it in root.findall(".//item"):
        items.append({c.tag: (c.text or "").strip() for c in it})
    return items, ""


def get_building_ledger_info(address_or_pnu: str) -> str:
    """
    지번/도로명 주소 또는 19자리 PNU를 입력받아 국토교통부 건축물대장(BldRgstHubService)의
    1) 표제부(주용도·대지면적·연면적·층수·사용승인일·위반건축물 여부) 및
    2) 층별개요(층별 용도·면적 및 겸용주택 주택/비주택 면적 자동 합산 비교)를 조회합니다.
    """
    nts_key = _live_nts_key()
    if not nts_key:
        return "❌ NTS_API_KEY(공공데이터포털 인증키)가 설정되지 않았습니다."

    vworld_key = _get_vworld_key()
    pnu, resolved_addr = _address_to_pnu(address_or_pnu, vworld_key)
    if not pnu or len(pnu) != 19:
        return f"❌ 건축물대장 조회를 위한 19자리 PNU 변환 실패: {resolved_addr}"

    sigungu_cd = pnu[0:5]
    bjdong_cd = pnu[5:10]
    plat_gb_cd = "0" if pnu[10] == "1" else "1"
    bun = pnu[11:15]
    ji = pnu[15:19]
    encoded_key = nts_key if "%" in nts_key else urllib.parse.quote(nts_key, safe="")

    output = [
        f"🏢 [국토교통부 건축물대장 표제부·층별개요 통합 조회 | 주소: {resolved_addr} (PNU: {pnu})]",
        f"- 행정구역코드: 시군구({sigungu_cd}) · 법정동({bjdong_cd}) · 번지({int(bun)}-{int(ji)})",
    ]

    def _call_bld_hub(op_name: str, num_rows: int = 30) -> tuple[list[dict], str]:
        # platGbCd 지정 호출 후 결과 0건이면 platGbCd 생략 재시도
        urls = [
            f"https://apis.data.go.kr/1613000/BldRgstHubService/{op_name}?serviceKey={encoded_key}&sigunguCd={sigungu_cd}&bjdongCd={bjdong_cd}&platGbCd={plat_gb_cd}&bun={bun}&ji={ji}&numOfRows={num_rows}&pageNo=1",
            f"https://apis.data.go.kr/1613000/BldRgstHubService/{op_name}?serviceKey={encoded_key}&sigunguCd={sigungu_cd}&bjdongCd={bjdong_cd}&bun={bun}&ji={ji}&numOfRows={num_rows}&pageNo=1",
        ]
        last_err = ""
        for u in urls:
            try:
                r = requests.get(u, timeout=15)
                if r.status_code != 200:
                    last_err = (
                        f"❌ 건축물대장 API 호출 실패 (HTTP {r.status_code}): "
                        "공공데이터포털(data.go.kr/data/15134735/openapi.do)에서 '국토교통부_건축HUB_건축물대장정보 서비스' 활용신청 및 키 동기화(신청 후 약 10~30분 소요) 여부를 확인해 주세요."
                    )
                    continue
                items, err_msg = _parse_data_go_kr_items(r.text, "국토교통부 건축물대장(BldRgstHubService)")
                if err_msg:
                    return [], err_msg
                if items:
                    return items, ""
            except Exception as e:
                last_err = f"❌ 건축물대장 API 통신 오류: {e}"
        return [], last_err

    # 1) 표제부 조회 (getBrTitleInfo)
    t_items, t_err = _call_bld_hub("getBrTitleInfo", num_rows=20)
    if t_err:
        return t_err

    if not t_items:
        output.append("\n■ 1. 건축물대장 표제부: 해당 지번으로 조회된 표제부 내역이 없습니다.")
    else:
        output.append(f"\n■ 1. 건축물대장 표제부 (총 {len(t_items)}동 중 주요 내역):")
        for idx, d in enumerate(t_items[:5], start=1):
            bld_nm = d.get("bldNm") or d.get("dongNm") or f"건축물 #{idx}"
            main_p = d.get("mainPurpsCdNm") or "-"
            etc_p = d.get("etcPurps") or ""
            strct = d.get("strctCdNm") or "-"
            plat_ar = d.get("platArea") or "0"
            arch_ar = d.get("archArea") or "0"
            tot_ar = d.get("totArea") or "0"
            grnd_cnt = d.get("grndFlrCnt") or "0"
            ugrnd_cnt = d.get("ugrndFlrCnt") or "0"
            hhld = d.get("hhldCnt") or "0"
            fmly = d.get("fmlyCnt") or "0"
            ho = d.get("hoCnt") or "0"
            apr_day = d.get("useAprDay") or "-"
            viol = d.get("violBldYn") or "0"
            viol_str = "⚠️ 위반건축물 등재(Y)" if viol in ("1", "Y", "유") else "정상(위반사항 없음)"
            output.append(
                f"- [{bld_nm}] 주용도: {main_p}{f' ({etc_p})' if etc_p and etc_p != main_p else ''} | 주구조: {strct}\n"
                f"  · 대지면적: {plat_ar}㎡ | 건축면적: {arch_ar}㎡ | 연면적: {tot_ar}㎡ (지상 {grnd_cnt}층 / 지하 {ugrnd_cnt}층)\n"
                f"  · 세대/가구/호수: {hhld}세대 · {fmly}가구 · {ho}호 | 사용승인일: {apr_day} | 위반건축물: {viol_str}"
            )

    # 2) 층별개요 조회 (getBrFlrOulnInfo) — 겸용주택 주택 vs 상가(근린생활시설) 면적 자동 판정
    f_items, f_err = _call_bld_hub("getBrFlrOulnInfo", num_rows=50)
    if f_items:
        output.append(f"\n■ 2. 층별개요 및 용도별 면적 분석 (총 {len(f_items)}개 층 데이터):")
        house_area = 0.0
        non_house_area = 0.0
        house_keywords = ("주택", "다가구", "다세대", "연립", "아파트", "기숙사")
        for fd in f_items[:30]:
            flr_gb = fd.get("flrGbCdNm") or ""
            flr_nm = fd.get("flrNoNm") or fd.get("flrNo") or "-"
            purp = fd.get("mainPurpsCdNm") or fd.get("etcPurps") or "-"
            etc_p = fd.get("etcPurps") or ""
            ar_str = fd.get("area") or "0"
            try:
                ar_val = float(ar_str)
            except ValueError:
                ar_val = 0.0
            comb_purp = f"{purp} {etc_p}"
            is_house = any(hk in comb_purp for hk in house_keywords) and "오피스텔" not in comb_purp
            if is_house:
                house_area += ar_val
            else:
                non_house_area += ar_val
            tag_h = "[주택]" if is_house else "[비주택/상가등]"
            output.append(
                f"- {flr_gb} {flr_nm}: {purp}{f' ({etc_p})' if etc_p and etc_p != purp else ''} | 면적: {ar_val:,.2f}㎡ {tag_h}"
            )
        tot_flr_ar = house_area + non_house_area
        if tot_flr_ar > 0:
            h_ratio = (house_area / tot_flr_ar) * 100.0
            rule_note = (
                "주택 연면적 > 비주택 연면적 (소득세법 시행령 제154조 제3항 겸용주택 특례 요건 참고)"
                if house_area > non_house_area
                else "주택 연면적 ≤ 비주택 연면적 (주택 부분만 주택으로 판정)"
            )
            output.append(
                f"\n📌 [겸용주택 용도별 면적 자동 집계]\n"
                f"- 주택 부분 합계: {house_area:,.2f}㎡ ({h_ratio:.1f}%) | 비주택(상가·업무 등) 합계: {non_house_area:,.2f}㎡ ({100.0 - h_ratio:.1f}%)\n"
                f"- 비교 판정: {rule_note}"
            )
    elif f_err:
        output.append(f"\n■ 2. 층별개요 조회 참고: {f_err}")

    return "\n".join(output)[:14000]

# ---------------------------------------------------------
# 9. 근로복지공단 고용·산재보험 가입 사업장 현황 조회 (사업자번호 기준 상시인원·성립일자·업종 대사)
# ---------------------------------------------------------
def get_comwel_workplace_info(biz_no: str, insurance_type: str = "all") -> str:
    """
    공공데이터포털 인증키(NTS_API_KEY)를 사용하여 근로복지공단 고용·산재보험 가입 사업장 상세정보(gySjbPstateInfoService)를 조회합니다.
    - biz_no: 10자리 사업자등록번호 (예: '123-45-67890' 또는 '1234567890')
    - insurance_type: 'all'(산재+고용 모두), '1'(산재), '2'(고용)
    """
    nts_key = _live_nts_key()
    if not nts_key:
        return "❌ NTS_API_KEY(공공데이터포털 인증키)가 설정되지 않았습니다."

    cleaned = re.sub(r"(\d{3})-(\d{2})-(\d{5})", r"\1\2\3", biz_no or "")
    b_nos = re.findall(r"\b\d{10}\b", cleaned)
    if not b_nos:
        digits = re.sub(r"\D", "", biz_no or "")
        if len(digits) == 10:
            b_nos = [digits]
    if not b_nos:
        return f"❌ 입력된 값('{biz_no}')에서 유효한 10자리 사업자등록번호를 찾을 수 없습니다."

    encoded_key = nts_key if "%" in nts_key else urllib.parse.quote(nts_key, safe="")
    fg_list = ["2", "1"] if str(insurance_type).lower() not in ("1", "2") else [str(insurance_type)]
    fg_label_map = {"1": "산재보험", "2": "고용보험"}
    saeop_fg_map = {"1": "계속", "3": "일괄계속", "4": "일괄유기", "7": "사업개시계속"}

    output = [f"👷 [근로복지공단 고용·산재보험 가입 사업장 현황 조회 (총 {len(b_nos)}개 사업자번호)]"]
    for bno in b_nos[:10]:
        fmt_bno = f"{bno[:3]}-{bno[3:5]}-{bno[5:]}"
        bno_lines = [f"\n■ 사업자등록번호: {fmt_bno}"]
        found_any = False
        for fg in fg_list:
            ep = (
                f"https://apis.data.go.kr/B490001/gySjbPstateInfoService/getGySjBoheomBsshItem"
                f"?serviceKey={encoded_key}&v_saeopjaDrno={bno}&opaBoheomFg={fg}&pageNo=1&numOfRows=20"
            )
            try:
                resp = requests.get(ep, timeout=15)
                if resp.status_code != 200:
                    return (
                        f"❌ 근로복지공단 API 호출 실패 (HTTP {resp.status_code}): "
                        "공공데이터포털(data.go.kr/data/15059256/openapi.do)에서 '근로복지공단_고용/산재보험 현황정보' 활용신청 여부를 확인해 주세요."
                    )
                items, err_msg = _parse_data_go_kr_items(resp.text, f"근로복지공단 {fg_label_map.get(fg, fg)}")
                if err_msg:
                    bno_lines.append(f"  - {err_msg}")
                    continue
                for d in items[:5]:
                    found_any = True
                    s_nm = d.get("saeopjangNm") or "-"
                    cnt = d.get("sangsiInwonCnt") or "0"
                    dt = d.get("seongripDt") or "-"
                    if len(dt) == 8 and dt.isdigit():
                        dt = f"{dt[:4]}-{dt[4:6]}-{dt[6:]}"
                    s_fg = saeop_fg_map.get(d.get("saeopFg", ""), d.get("saeopFg") or "-")
                    addr = d.get("addr") or "-"
                    up_cd = d.get("gyEopjongCd") or d.get("sjEopjongCd") or "-"
                    up_nm = d.get("gyEopjongNm") or d.get("sjEopjongNm") or "-"
                    bno_lines.append(
                        f"  - [{fg_label_map.get(fg, '보험')}] 사업장명: {s_nm} | 상시인원(피보험자): {cnt}명 | "
                        f"성립일자: {dt} | 가입상태: {s_fg} | 업종: {up_nm}({up_cd}) | 주소: {addr}"
                    )
            except Exception as e:
                bno_lines.append(f"  - [{fg_label_map.get(fg, fg)}] 조회 오류: {e}")

        if not found_any and len(bno_lines) == 1:
            bno_lines.append("  - 조회된 고용·산재보험 성립 내역이 없습니다.")
        output.extend(bno_lines)

    return "\n".join(output)[:14000]


# ---------------------------------------------------------
# 10. 4대보험(국민연금·건강·장기요양·고용·산재) 월별 고지보험료 및 연간 고지총액 합계 실시간 통합 조회
# ---------------------------------------------------------
def _estimate_sanjae_rate_by_upjong(upjong_nm: str, upjong_cd: str = "") -> tuple[float, str]:
    """근로복지공단 산재업종명/코드에 따른 산재보험요율(사업주 100% 부담, 출퇴근재해 0.06% 포함)을 반환합니다."""
    nm = (upjong_nm or "").strip()
    if any(k in nm for k in ("소프트웨어", "정보처리", "포털", "연구", "법무", "회계", "세무", "건축기술", "금융", "보험", "교육", "전문", "광고", "출판", "디자인", "경영컨설팅")):
        return 0.0066, "금융·전문·정보통신·사무서비스업 (0.66%)"
    if any(k in nm for k in ("도매", "소매", "음식", "숙박", "부동산", "임대", "보건", "사회복지", "병원", "의원")):
        return 0.0086, "도소매·음식·숙박·보건·임대업 (0.86%)"
    if any(k in nm for k in ("건설", "토목", "건축")):
        return 0.0356, "건설업 (3.56%)"
    if any(k in nm for k in ("운수", "창고", "물류", "화물", "택배")):
        return 0.0186, "운수·창고·통신업 (1.86%)"
    if any(k in nm for k in ("제조", "기계", "금속", "화학", "식품", "섬유", "전자", "전기")):
        return 0.0136, "제조업 평균 (1.36%)"
    return 0.0106, "일반 사업장 평균 (1.06%)"


def get_nps_workplace_info(
    corp_name: str,
    biz_no_prefix6: str = "",
    region_keyword: str = "",
    target_year: str = ""
) -> str:
    """
    공공데이터포털 인증키(NTS_API_KEY)를 사용하여 국민연금공단(NpsBplcInfoInqireServiceV2) 및 근로복지공단(gySjbPstateInfoService) API를 연동해
    사업장의 [국민연금 · 건강보험 · 장기요양보험 · 고용보험 · 산재보험] 4대보험 전체의
    1) 연도별(연간) 고지보험료 총액 합계 (전체 / 사업주 부담분 / 근로자 부담분) 및
    2) 월별 4대보험 고지보험료 상세 내역과 가입자수(신규/상실)를 실시간 조회·산출합니다.
    - corp_name: 사업장명(상호, 예: '삼성전자', '(주)세무법인')
    - biz_no_prefix6: 사업자등록번호 앞 6자리 또는 전체 10자리 (선택, 10자리 입력 시 근로복지공단 업종·상시인원 자동 교차조회)
    - region_keyword: 주소 필터 키워드 (선택, 예: '강남구', '성남시')
    - target_year: 특정 연도 필터 (선택, 예: '2026', '2025' — 비워두면 조회된 전체 연도별·월별 합계 자동 산출)
    """
    from concurrent.futures import ThreadPoolExecutor

    nts_key = _live_nts_key()
    if not nts_key:
        return "❌ NTS_API_KEY(공공데이터포털 인증키)가 설정되지 않았습니다."

    kw = (corp_name or "").strip()
    raw_bno_digits = re.sub(r"\D", "", biz_no_prefix6 or "")
    bno6 = raw_bno_digits[:6]
    bno10 = raw_bno_digits[:10] if len(raw_bno_digits) >= 10 else ""
    yr_filter = re.sub(r"\D", "", str(target_year or ""))[:4]
    if not kw and not bno6:
        return "❌ 조회할 사업장명(corp_name) 또는 사업자등록번호(biz_no_prefix6)를 입력해 주세요."

    encoded_key = nts_key if "%" in nts_key else urllib.parse.quote(nts_key, safe="")

    # 10자리 사업자번호가 함께 들어온 경우 근로복지공단 API에서 실제 업종명·상시인원 동시 조회
    comwel_upjong_nm = ""
    comwel_upjong_cd = ""
    comwel_cnt = 0
    if bno10:
        try:
            cw_ep = (
                f"https://apis.data.go.kr/B490001/gySjbPstateInfoService/getGySjBoheomBsshItem"
                f"?serviceKey={encoded_key}&v_saeopjaDrno={bno10}&opaBoheomFg=1&pageNo=1&numOfRows=5"
            )
            cw_r = requests.get(cw_ep, timeout=8)
            if cw_r.status_code == 200:
                cw_items, _ = _parse_data_go_kr_items(cw_r.text, "근로복지공단")
                if cw_items:
                    comwel_upjong_nm = cw_items[0].get("sjEopjongNm") or cw_items[0].get("gyEopjongNm") or ""
                    comwel_upjong_cd = cw_items[0].get("sjEopjongCd") or cw_items[0].get("gyEopjongCd") or ""
                    comwel_cnt = int(re.sub(r"\D", "", str(cw_items[0].get("sangsiInwonCnt") or "0")) or 0)
        except Exception:
            pass

    base_urls = [
        "https://apis.data.go.kr/B552015/NpsBplcInfoInqireServiceV2/getBassInfoSearchV2",
        "http://apis.data.go.kr/B552015/NpsBplcInfoInqireService/getBassInfoSearch",
    ]
    detail_urls = [
        "https://apis.data.go.kr/B552015/NpsBplcInfoInqireServiceV2/getDetailInfoSearchV2",
        "http://apis.data.go.kr/B552015/NpsBplcInfoInqireService/getDetailInfoSearch",
    ]

    q_params = f"serviceKey={encoded_key}&numOfRows=100&pageNo=1"
    if kw:
        enc_kw = urllib.parse.quote(kw)
        q_params += f"&wkplNm={enc_kw}&wkpl_nm={enc_kw}"
    if bno6:
        q_params += f"&bzowrRgstNo={bno6}&bzowr_rgst_no={bno6}"

    items = []
    err_msg = ""
    used_v2 = True
    last_status = 0

    for idx, b_url in enumerate(base_urls):
        try:
            r = requests.get(f"{b_url}?{q_params}", timeout=15)
            last_status = r.status_code
            if r.status_code != 200:
                continue
            cand_items, cand_err = _parse_data_go_kr_items(r.text, "국민연금 가입 사업장 내역(NpsBplcInfoInqireServiceV2)")
            if cand_items:
                items = cand_items
                err_msg = ""
                used_v2 = (idx == 0)
                break
            if cand_err and not err_msg:
                err_msg = cand_err
                used_v2 = (idx == 0)
        except Exception as e:
            if not err_msg:
                err_msg = str(e)
            continue

    if err_msg and not items:
        return err_msg

    if not items and last_status != 200:
        return (
            f"❌ 4대보험(국민연금) 사업장 API 호출 실패 (HTTP {last_status}): "
            "공공데이터포털(data.go.kr/data/3046071/openapi.do)에서 '국민연금공단_국민연금 가입 사업장 내역' 활용신청 및 키 동기화 여부를 확인해 주세요."
        )

    if not items:
        return (
            f"조회된 사업장 내역이 없습니다. (검색 상호: '{kw}', 사업자번호 앞6자리: '{bno6 or '전체'}')\n"
            "※ 참고: 국민연금 공개 Open API는 개인정보 보호를 위해 가입자 3인 이상 사업장(법인 3인 이상 / 개인 10인 이상 등 공단 공개 기준 충족 사업장)만 수록됩니다."
        )

    reg_kw = (region_keyword or "").strip()
    parsed = []
    for d in items:
        addr = d.get("wkplRoadNmDtlAddr") or d.get("wkplJgongAddr") or ""
        if reg_kw and reg_kw not in addr:
            continue
        b_no_item = d.get("bzowrRgstNo") or ""
        if bno6 and b_no_item and not b_no_item.startswith(bno6):
            continue
        ym_val = str(d.get("dataCrtYm") or "").strip()
        if yr_filter and ym_val and not ym_val.startswith(yr_filter):
            continue
        parsed.append(d)

    if not parsed:
        return f"검색된 {len(items)}건 중 조건(지역:'{reg_kw}', 사업자번호앞6자리:'{bno6}', 연도:'{yr_filter or '전체'}')에 일치하는 사업장이 없습니다."

    parsed.sort(key=lambda x: (str(x.get("wkplJnngStcd", "")) == "1", str(x.get("dataCrtYm", ""))), reverse=True)
    primary = parsed[0]
    p_nm = primary.get("wkplNm") or kw
    p_bno = primary.get("bzowrRgstNo") or ""
    p_addr = primary.get("wkplRoadNmDtlAddr") or primary.get("wkplJgongAddr") or "-"
    p_tp = "법인" if primary.get("wkplStylDvcd") == "1" else "개인"
    p_st = "등록(계속)" if primary.get("wkplJnngStcd") == "1" else "탈퇴/해지"
    p_upjong = comwel_upjong_nm or primary.get("vldtVlKrnNm") or ""

    same_wp_rows = [
        d for d in parsed
        if (d.get("wkplNm") == p_nm and (not p_bno or d.get("bzowrRgstNo") == p_bno))
    ]
    ym_to_row = {}
    for d in same_wp_rows:
        ym = str(d.get("dataCrtYm") or "").strip()
        seq = str(d.get("seq") or "").strip()
        if ym and seq and ym not in ym_to_row:
            ym_to_row[ym] = d

    target_ym_rows = [ym_to_row[k] for k in sorted(ym_to_row.keys(), reverse=True)[:18]]
    if not target_ym_rows:
        target_ym_rows = parsed[:12]

    det_ep = detail_urls[0] if used_v2 else detail_urls[1]

    def _fetch_detail_by_seq(row_item: dict) -> dict:
        seq_val = str(row_item.get("seq") or "").strip()
        if not seq_val:
            return {}
        try:
            dr = requests.get(f"{det_ep}?serviceKey={encoded_key}&seq={seq_val}", timeout=10)
            if dr.status_code == 200:
                d_items, _ = _parse_data_go_kr_items(dr.text, "국민연금 상세")
                if d_items:
                    return d_items[0]
        except Exception:
            pass
        return {}

    detail_map = {}
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(target_ym_rows)))) as pool:
        futs = {pool.submit(_fetch_detail_by_seq, r): str(r.get("seq") or "") for r in target_ym_rows}
        for fut, s_key in futs.items():
            try:
                res_d = fut.result()
                if s_key and res_d:
                    detail_map[s_key] = res_d
            except Exception:
                pass

    sj_rate, sj_label = _estimate_sanjae_rate_by_upjong(p_upjong, comwel_upjong_cd)

    output = [
        f"🏦 [4대보험(국민연금·건강·장기요양·고용·산재) 월별 고지보험료 및 연간 고지총액 통합 조회]",
        f"- 사업장명: {p_nm} ({p_tp} · 사업자번호: {bno10 or p_bno} | 가입상태: {p_st})",
        f"- 소재지: {p_addr}" + (f" | 산재/고용 업종: {p_upjong}({comwel_upjong_cd})" if p_upjong else ""),
    ]

    yearly_totals: dict[str, dict] = {}
    monthly_rows = []

    for r in sorted(target_ym_rows, key=lambda x: str(x.get("dataCrtYm") or ""), reverse=True):
        ym = str(r.get("dataCrtYm") or "-")
        yr = ym[:4] if len(ym) >= 4 else "기타"
        seq = str(r.get("seq") or "")
        dd = detail_map.get(seq) or {}
        j_cnt = int(re.sub(r"\D", "", str(dd.get("jnngpCnt") or "0")) or 0)
        nps_total = int(re.sub(r"\D", "", str(dd.get("crrmmNtcAmt") or "0")) or 0)
        nw_cnt = int(re.sub(r"\D", "", str(dd.get("nwAcqzrCnt") or "0")) or 0)
        lss_cnt = int(re.sub(r"\D", "", str(dd.get("lssJnngpCnt") or "0")) or 0)

        # 1) 국민연금 (API 실제 고지 원문 수치: 총 9.0%, 사업주 4.5% / 근로자 4.5%)
        nps_emp_owner = nps_total // 2
        nps_worker = nps_total - nps_emp_owner
        est_payroll = int(round(nps_total / 0.09)) if nps_total > 0 else 0

        # 2) 건강보험 (법정요율 7.09%: 사업주 3.545% / 근로자 3.545%)
        nhis_total = int(round(est_payroll * 0.0709))
        nhis_owner = nhis_total // 2
        nhis_worker = nhis_total - nhis_owner

        # 3) 노인장기요양보험 (건강보험료의 12.95%: 사업주 50% / 근로자 50%)
        ltc_total = int(round(nhis_total * 0.1295))
        ltc_owner = ltc_total // 2
        ltc_worker = ltc_total - ltc_owner

        # 4) 고용보험 (실업급여 노사 각 0.9% + 고안직능 사업주 부담: 150인 미만 0.25%, 150~999인 0.65%, 1000인 이상 0.85%)
        eff_cnt = max(j_cnt, comwel_cnt)
        ei_extra_rate = 0.0085 if eff_cnt >= 1000 else (0.0065 if eff_cnt >= 150 else 0.0025)
        ei_worker = int(round(est_payroll * 0.009))
        ei_owner = int(round(est_payroll * (0.009 + ei_extra_rate)))
        ei_total = ei_owner + ei_worker

        # 5) 산재보험 (사업주 100% 부담)
        sj_owner = int(round(est_payroll * sj_rate))
        sj_total = sj_owner

        # 당월 4대보험 합계
        m_all_total = nps_total + nhis_total + ltc_total + ei_total + sj_total
        m_owner_total = nps_emp_owner + nhis_owner + ltc_owner + ei_owner + sj_owner
        m_worker_total = nps_worker + nhis_worker + ltc_worker + ei_worker

        if nps_total > 0 or j_cnt > 0:
            yb = yearly_totals.setdefault(yr, {
                "months": 0, "sum_cnt": 0, "est_payroll": 0,
                "nps_tot": 0, "nps_own": 0,
                "nhis_tot": 0, "nhis_own": 0,
                "ltc_tot": 0, "ltc_own": 0,
                "ei_tot": 0, "ei_own": 0,
                "sj_tot": 0, "sj_own": 0,
                "all_tot": 0, "all_own": 0, "all_wrk": 0,
            })
            yb["months"] += 1
            yb["sum_cnt"] += j_cnt
            yb["est_payroll"] += est_payroll
            yb["nps_tot"] += nps_total
            yb["nps_own"] += nps_emp_owner
            yb["nhis_tot"] += nhis_total
            yb["nhis_own"] += nhis_owner
            yb["ltc_tot"] += ltc_total
            yb["ltc_own"] += ltc_owner
            yb["ei_tot"] += ei_total
            yb["ei_own"] += ei_owner
            yb["sj_tot"] += sj_total
            yb["sj_own"] += sj_owner
            yb["all_tot"] += m_all_total
            yb["all_own"] += m_owner_total
            yb["all_wrk"] += m_worker_total

        ym_fmt = f"{ym[:4]}-{ym[4:6]}" if len(ym) == 6 else ym
        monthly_rows.append(
            f"| {ym_fmt} | {j_cnt:,}명 (+{nw_cnt}/-{lss_cnt}) | {nps_total:,}원 | {nhis_total + ltc_total:,}원 | "
            f"{ei_total:,}원 | {sj_total:,}원 | **{m_all_total:,}원** (사업주 {m_owner_total:,}원) |"
        )

    if yearly_totals:
        output.append("\n■ 1. 연도별(연간) 4대보험 고지총액 합계 및 회사(사업주) 부담분 요약:")
        output.append("| 귀속연도 (집계월수) | 월평균 가입자 | 추정 연간 보수총액 | ① 국민연금 (실제고지) | ② 건강+장기요양 (법정요율) | ③ 고용보험 (법정요율) | ④ 산재보험 (업종요율) | **4대보험 연간 고지총액 합계** | **사업주(회사) 연간 부담분** | **근로자 연간 부담분** |")
        output.append("| :--- | :---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
        for yr in sorted(yearly_totals.keys(), reverse=True):
            yb = yearly_totals[yr]
            mc = yb["months"]
            avg_c = yb["sum_cnt"] / mc if mc else 0.0
            output.append(
                f"| **{yr}년 ({mc}개월)** | {avg_c:.1f}명 | {yb['est_payroll']:,}원 | "
                f"{yb['nps_tot']:,}원 | {yb['nhis_tot'] + yb['ltc_tot']:,}원 | "
                f"{yb['ei_tot']:,}원 | {yb['sj_tot']:,}원 | "
                f"**{yb['all_tot']:,}원** | **{yb['all_own']:,}원** | {yb['all_wrk']:,}원 |"
            )

    if monthly_rows:
        output.append(f"\n■ 2. 월별 4대보험 고지보험료 상세 내역 (최근 {len(monthly_rows)}개월):")
        output.append("| 기준년월 | 가입자(신규/상실) | ① 국민연금(실제고지) | ② 건강+장기요양 | ③ 고용보험 | ④ 산재보험 | **당월 4대보험 고지합계 (사업주 부담분)** |")
        output.append("| :---: | :---: | ---: | ---: | ---: | ---: | ---: |")
        output.extend(monthly_rows)

    other_wps = []
    seen_wp_keys = {(p_nm, p_bno)}
    for d in parsed:
        k_pair = (d.get("wkplNm") or "", d.get("bzowrRgstNo") or "")
        if k_pair not in seen_wp_keys:
            seen_wp_keys.add(k_pair)
            other_wps.append(f"{k_pair[0]}({k_pair[1]} · {d.get('wkplRoadNmDtlAddr', '')[:18]})")
    if other_wps:
        output.append(f"\n*(참고 - 동일 검색어 내 타 사업장/지점 후보: {', '.join(other_wps[:5])})*")

    output.append(
        f"\n※ [산출 기준 안내] ① 국민연금은 국민연금공단 Open API 실제 고지 원문 수치(crrmmNtcAmt)이며, "
        f"②~④ 건강보험(7.09%)·장기요양(건보의 12.95%)·고용보험(실업급여 1.8%+규모별 고안직능)·산재보험({sj_label})은 "
        f"국민연금 고지액에서 역산된 보수총액에 법정요율을 적용한 실시간 산출치입니다(상한액 초과자·비과세 및 개별 정산분에 따라 실제 고지서와 소폭 차이가 날 수 있음)."
    )

    return "\n".join(output)[:14000]


# ---------------------------------------------------------
# 11. 관세청 수출입 과세환율 정보 조회 (관세법 제18조 · 부가가치세 영세율/수입세금계산서 과세표준 검증용)
# ---------------------------------------------------------
def get_customs_exchange_rate(aply_bgn_dt: str, imex_type: str = "2", currency: str = "") -> str:
    """
    공공데이터포털 인증키(NTS_API_KEY)를 사용하여 관세청_관세환율정보(retrieveTrifFxrtInfo)를 조회합니다.
    - aply_bgn_dt: 조회 기준일자 8자리 'YYYYMMDD' (예: '20261025')
    - imex_type: 수출입 구분 ('1' 또는 'export'=수출, '2' 또는 'import'=수입, 'all'=수출·수입 모두)
    - currency: 통화코드 필터 (예: 'USD', 'JPY', 'EUR', 'CNY' — 비워두면 주요 통화 전체 출력)
    """
    nts_key = _live_nts_key()
    if not nts_key:
        return "❌ NTS_API_KEY(공공데이터포털 인증키)가 설정되지 않았습니다."

    dt_clean = re.sub(r"\D", "", aply_bgn_dt or "")[:8]
    if len(dt_clean) != 8:
        return f"❌ 조회일자('{aply_bgn_dt}')는 'YYYYMMDD' 8자리 형식(예: '20261025')이어야 합니다."

    tp_raw = (imex_type or "2").lower().strip()
    if tp_raw in ("1", "수출", "export", "exp"):
        tp_list = [("1", "수출 과세환율")]
    elif tp_raw in ("all", "전체", "수출입"):
        tp_list = [("2", "수입 과세환율"), ("1", "수출 과세환율")]
    else:
        tp_list = [("2", "수입 과세환율")]

    encoded_key = nts_key if "%" in nts_key else urllib.parse.quote(nts_key, safe="")
    curr_filter = (currency or "").upper().strip()
    major_currs = {"USD", "JPY", "EUR", "CNY", "GBP", "HKD", "SGD", "AUD", "CAD", "CHF", "VND", "THB"}

    output = [f"🚢 [관세청 관세법 제18조 주간 수출입 과세환율 조회 | 기준일: {dt_clean[:4]}-{dt_clean[4:6]}-{dt_clean[6:]}]"]

    for tp_code, tp_label in tp_list:
        ep = (
            f"https://apis.data.go.kr/1220000/retrieveTrifFxrtInfo/getRetrieveTrifFxrtInfo"
            f"?serviceKey={encoded_key}&aplyBgnDt={dt_clean}&weekFxrtTpcd={tp_code}"
        )
        try:
            resp = requests.get(ep, timeout=15)
            if resp.status_code != 200:
                return (
                    f"❌ 관세청 과세환율 API 호출 실패 (HTTP {resp.status_code}): "
                    "공공데이터포털(data.go.kr/data/15101230/openapi.do)에서 '관세청_관세환율정보(GW)' 활용신청 여부를 확인해 주세요."
                )
            items, err_msg = _parse_data_go_kr_items(resp.text, f"관세청 {tp_label}")
            if err_msg:
                output.append(f"\n■ {tp_label}: {err_msg}")
                continue
            if not items:
                output.append(f"\n■ {tp_label}: 해당 일자({dt_clean})로 조회된 과세환율 내역이 없습니다.")
                continue

            rows = []
            for d in items:
                c_sgn = (d.get("currSgn") or "").upper()
                if curr_filter and curr_filter not in c_sgn and curr_filter not in (d.get("cntySgn") or "").upper():
                    continue
                if not curr_filter and c_sgn not in major_currs and len(items) > 15:
                    continue
                cnty = d.get("cntySgn") or "-"
                u_nm = d.get("mtryUtNm") or "-"
                fxrt = d.get("fxrt") or "-"
                bgn = d.get("aplyBgnDt") or dt_clean
                rows.append(f"  - [{c_sgn} ({cnty} · {u_nm})] {fxrt} 원 (적용개시일: {bgn})")

            if not rows and items:
                for d in items[:15]:
                    rows.append(
                        f"  - [{d.get('currSgn', '-')} ({d.get('cntySgn', '-')} · {d.get('mtryUtNm', '-')})] "
                        f"{d.get('fxrt', '-')} 원 (적용개시일: {d.get('aplyBgnDt', dt_clean)})"
                    )

            output.append(f"\n■ {tp_label} (조회 {len(rows)}건):")
            output.extend(rows[:20])
        except Exception as e:
            output.append(f"\n■ {tp_label} 조회 오류: {e}")

    return "\n".join(output)[:14000]