import os
import re
import math
import time
import contextvars
import json
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
    """
    유료키만 사용합니다.
    - GEMINI_PAID_KEY(기본) → GEMINI_API_KEY(예비, 다른 값일 때만) 순서로 사용합니다.
    """
    pool = []
    seen = set()
    for env_name, lbl in [("GEMINI_PAID_KEY", "💳 유료키"), ("GEMINI_API_KEY", "💳 유료키(예비)")]:
        k = _get_secret_or_env(env_name)
        if k and k not in seen:
            pool.append((lbl if pool or env_name == "GEMINI_PAID_KEY" else "💳 유료키", k))
            seen.add(k)
    return pool

import law_api

# ---------------------------------------------------------
# 🔎 근거 추적·검증 및 Pro 모드 3배 리미트 해제(Unleash) 동적 제어
# ---------------------------------------------------------
_TOOL_TRACE = contextvars.ContextVar("tool_trace", default=None)

def _new_trace(unleash: bool = False) -> dict:
    return {
        "list": [],
        "detail": [],
        "articles": set(),
        "article_texts": {},
        "counts": {},
        "id_map": {},
        "unleash": unleash
    }

def _is_unleashed() -> bool:
    trace = _TOOL_TRACE.get()
    return bool(trace and trace.get("unleash"))

# 기본(Flash) 1배 한도 vs Pro 모드 3배 개방(Unleash) 시 자동 곱셈 적용
_SEARCH_LIMIT = {"law": 7, "prec": 3, "decc": 3, "expc": 2, "admrul": 2, "ordin": 2}
_DETAIL_LIMIT = {"law": 12, "prec": 3, "decc": 3, "expc": 2, "admrul": 2, "ordin": 2}

def _over_limit(kind: str, target: str) -> bool:
    """kind: 'search' 또는 'detail'. Pro(unleash) 모드일 때는 상한을 3배로 자동 확장합니다."""
    trace = _TOOL_TRACE.get()
    if trace is None:
        return False
    mult = 3 if trace.get("unleash") else 1
    table = _SEARCH_LIMIT if kind == "search" else _DETAIL_LIMIT
    key = f"{kind}:{target}"
    used = trace["counts"].get(key, 0)
    limit_val = table.get(target, 2) * mult
    if used >= limit_val:
        return True
    trace["counts"][key] = used + 1
    return False

def _norm(text: str) -> str:
    return re.sub(r"[\s「」『』\"'“”‘’]", "", text or "")

def _record(kind: str, text: str) -> str:
    """kind: 'list'(목록 검색 결과) 또는 'detail'(원문 조회 결과)"""
    trace = _TOOL_TRACE.get()
    if trace is not None:
        trace[kind].append(text or "")
    return text

def _record_law_articles(text: str) -> None:
    """법령 원문 조회 결과에서 '법령명 + 조문번호'를 뽑아 조회 완료 목록에 추가합니다."""
    trace = _TOOL_TRACE.get()
    if trace is None or not text:
        return
    m = re.search(r"📘 \[(.+?)\]", text)
    if not m:
        return
    title = _norm(m.group(1))
    starts = list(re.finditer(r"(?m)^제(\d+)조(?:의(\d+))?\(", text))
    for n, am in enumerate(starts):
        key = (title, int(am.group(1)), int(am.group(2) or 0))
        trace["articles"].add(key)
        end = starts[n + 1].start() if n + 1 < len(starts) else len(text)
        trace["article_texts"][key] = text[am.start():end].strip()

# ① 사건번호: 법원(2005두9415, 99다1234, 2004헌바92, 2014누53591) / 조세심판(조심2020서1234)
_CASE_NO_PATTERNS = [
    re.compile(r"(?<!\d)((?:19|20)?\d{2})\s?(재두|재다|가합|가단|구합|구단|헌바|헌마|헌가|두|누|다|도|나|후|허|므|구|부|노|고단|고합)\s?(\d{2,6})(?!\d)"),
    re.compile(r"(?:조심|국심)\s?((?:19|20)\d{2})\s?(서|중|부|광|전|구|인|경|지)\s?(\d{2,6})(?!\d)"),
]

# ② 법령 조문: 「상속세 및 증여세법」 제45조의2, 법인세법 시행령 제89조 (법령명이 붙은 경우만 검증)
_ARTICLE_NO = re.compile(r"제\s*(\d+)\s*조(?:\s*의\s*(\d+))?")
_COMMON_LAWS = [
    "상속세및증여세법", "조세특례제한법", "국세기본법", "국세징수법", "법인세법", "소득세법", "부가가치세법",
    "지방세법", "지방세기본법", "지방세특례제한법", "종합부동산세법", "개별소비세법", "교육세법", "농어촌특별세법",
    "인지세법", "증권거래세법", "국제조세조정에관한법률", "조세범처벌법", "근로기준법", "근로자퇴직급여보장법",
    "국민연금법", "국민건강보험법", "노인장기요양보험법", "고용보험법", "고용보험및산업재해보상보험의보험료징수등에관한법률",
    "주식회사등의외부감사에관한법률", "상법", "민법", "부동산등기법", "공익법인의설립ㆍ운영에관한법률",
]
_LAW_ALIASES = {"상증법": "상속세및증여세법", "조특법": "조세특례제한법", "국기법": "국세기본법",
                "국징법": "국세징수법", "부가세법": "부가가치세법", "지특법": "지방세특례제한법",
                "국조법": "국제조세조정에관한법률", "종부세법": "종합부동산세법", "외감법": "주식회사등의외부감사에관한법률",
                "고용산재보험료징수법": "고용보험및산업재해보상보험의보험료징수등에관한법률"}
_REF_SKIP_SUFFIX = ("동법", "같은법", "이법", "본법", "당해법", "해당법", "동법시행령", "같은법시행령", "동법시행규칙")

def _known_law_titles(trace: dict = None) -> list[str]:
    titles = set()
    for base in _COMMON_LAWS:
        titles.update({base, base + "시행령", base + "시행규칙"})
    if trace:
        titles.update(t for (t, _, _) in trace.get("articles", set()))
    return sorted(titles, key=len, reverse=True)

def _resolve_law_name(prefix: str, titles: list[str]):
    """'제N조' 바로 앞 글자들(prefix)의 끝부분에서 법령명을 찾아 정식 명칭(공백 제거)으로 돌려줍니다."""
    tail = _norm(prefix)[-40:]
    for suf in _REF_SKIP_SUFFIX:
        if tail.endswith(suf):
            return None
    for alias, full in _LAW_ALIASES.items():
        for ext in ("시행규칙", "시행령", ""):
            if tail.endswith(alias + ext) or (tail.endswith(alias.replace("법", "령")) and ext == "시행령"):
                return full + ext
    for t in titles:
        if tail.endswith(t):
            return t
    m = re.search(r"([가-힣ㆍ·]{2,30}?법(?:시행령|시행규칙)?)$", tail)
    if not m:
        return None
    partial = m.group(1)
    for t in titles:
        if t.endswith(partial) and len(partial) >= 3:
            return t
    return partial

# ③ 집행기준 번호: 33의2-78의3-1, 52-88-3
_EXEC_STD = re.compile(r"(?<![\d의])(\d{1,3}(?:의\d{1,2})?-\d{1,3}(?:의\d{1,2})?-\d{1,3})(?![\d])")

# ④ 근거 표시: [판례:2005두9415] [심판례:조심2020서1234] [해석례:...] [예규:...] [조문:법인세법 제52조]
_TAG = re.compile(r"\[(판례\vert{}심판례\vert{}해석례\vert{}예규\vert{}조문)\s*:\s*([^\]]+)\]")

# ⑤ 출처가 필요한 서술 키워드 / 허용되는 부정·미조회 표현 / 양식 고정 문구
_AUTHORITY = re.compile(r"대법원|판시|판례|심판원|조세심판|심판례|결정례|헌법재판소|헌재|예규|집행기준|유권해석|해석례|질의회신")
_NEGATION = re.compile(r"없음|없습니다|없으며|없고|없어|확인되지|확인하지 못|찾지 못|미조회|조회되지|조회하지 못")
_TEMPLATE_LABELS = ("예규·심판례·리스크 검증", "법령·기준·공시·실거래 대조", "예규·심판례", "예규·판례·심판례")

_QUOTE = re.compile(r"[“\"]([^”\"]{12,})[”\"]")

def _letters(text: str) -> str:
    """인용문 대조용: 한글·영문·숫자만 남김 (띄어쓰기·문장부호 차이 무시)"""
    return re.sub(r"[^0-9A-Za-z가-힣]", "", text or "")

def _quote_mismatches(line: str, case_nos: list, details: list) -> list[str]:
    """따옴표로 인용한 문장이 조회한 판례·심판례 원문에 실제로 있는지 확인합니다."""
    bad = []
    pool = [d for d in details if any(n in _norm(d) for n in case_nos)] if case_nos else details
    pool_letters = [_letters(d) for d in pool]
    for q in _QUOTE.findall(line):
        segments = [seg for seg in re.split(r"…|\.\.\.|⋯|중략", q) if len(_letters(seg)) >= 10]
        for seg in segments:
            if not
