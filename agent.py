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
# 💰 월간 API 사용량·요금 실시간 추적 및 월 20,000원 Pro 자동 차단기
# ---------------------------------------------------------
USAGE_STORAGE_DIR = ".workspace_storage"
os.makedirs(USAGE_STORAGE_DIR, exist_ok=True)
USAGE_FILE_PATH = os.path.join(USAGE_STORAGE_DIR, "api_usage_stats.json")

MONTHLY_PRO_LIMIT_KRW = float(_get_secret_or_env("MONTHLY_PRO_LIMIT_KRW") or 20000.0)
USD_TO_KRW_RATE = 1400.0

_MODEL_PRICING_USD_PER_1M = {
    "PRO":   {"in": 1.50, "out": 10.00},
    "FLASH": {"in": 0.15, "out": 0.60},
}

def _current_ym() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m")

def get_monthly_usage() -> dict:
    """현재 월(YYYY-MM)의 누적 토큰 및 원화 환산 요금 데이터를 불러옵니다. 달이 바뀌면 자동 초기화됩니다."""
    ym = _current_ym()
    default_stats = {
        "year_month": ym,
        "total_krw": 0.0,
        "total_usd": 0.0,
        "pro_calls": 0,
        "flash_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "limit_krw": MONTHLY_PRO_LIMIT_KRW,
        "updated_at": "-"
    }
    if os.path.exists(USAGE_FILE_PATH):
        try:
            with open(USAGE_FILE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("year_month") == ym:
                for k, v in default_stats.items():
                    data.setdefault(k, v)
                data["limit_krw"] = MONTHLY_PRO_LIMIT_KRW
                return data
        except Exception:
            pass
    return default_stats

def _record_token_usage(model_id: str, in_tokens: int, out_tokens: int, count_call: bool = True) -> None:
    """API 응답의 입출력 토큰을 원화 요금으로 환산해 디스크에 즉시 누적 저장합니다."""
    if in_tokens <= 0 and out_tokens <= 0:
        return
    stats = get_monthly_usage()
    is_pro_model = ("pro" in model_id.lower()) or ("argon" in model_id.lower())
    tier_key = "PRO" if is_pro_model else "FLASH"
    price_info = _MODEL_PRICING_USD_PER_1M[tier_key]

    cost_usd = (in_tokens / 1_000_000.0) * price_info["in"] + (out_tokens / 1_000_000.0) * price_info["out"]
    cost_krw = cost_usd * USD_TO_KRW_RATE

    stats["total_usd"] = round(stats.get("total_usd", 0.0) + cost_usd, 6)
    stats["total_krw"] = round(stats.get("total_krw", 0.0) + cost_krw, 2)
    stats["input_tokens"] = int(stats.get("input_tokens", 0)) + int(in_tokens)
    stats["output_tokens"] = int(stats.get("output_tokens", 0)) + int(out_tokens)
    if count_call:
        if is_pro_model:
            stats["pro_calls"] = int(stats.get("pro_calls", 0)) + 1
        else:
            stats["flash_calls"] = int(stats.get("flash_calls", 0)) + 1
    stats["updated_at"] = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%m/%d %H:%M:%S")

    try:
        with open(USAGE_FILE_PATH, "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ 사용량 기록 저장 오류: {e}")

def _extract_and_log_response_usage(response, model_id: str, count_call: bool = True, est_in_chars: int = 0, est_out_chars: int = 0) -> None:
    """Gemini 응답 객체에서 usage_metadata를 추출하여 요금을 기록합니다."""
    in_tok, out_tok = 0, 0
    try:
        um = getattr(response, "usage_metadata", None)
        if um:
            in_tok = int(getattr(um, "prompt_token_count", 0) or 0)
            out_tok = int(getattr(um, "candidates_token_count", 0) or 0)
    except Exception:
        pass
    if in_tok == 0 and est_in_chars > 0:
        in_tok = int(est_in_chars * 0.7)
    if out_tok == 0 and est_out_chars > 0:
        out_tok = int(est_out_chars * 0.7)
    _record_token_usage(model_id, in_tok, out_tok, count_call=count_call)

def is_pro_budget_exceeded() -> tuple[bool, float, float]:
    """당월 누적 요금이 한도(20,000원)를 초과했는지 확인합니다."""
    stats = get_monthly_usage()
    cur_krw = float(stats.get("total_krw", 0.0))
    limit_krw = float(stats.get("limit_krw", MONTHLY_PRO_LIMIT_KRW))
    return (cur_krw >= limit_krw), cur_krw, limit_krw


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

_CASE_NO_PATTERNS = [
    re.compile(r"(?<!\d)((?:19|20)?\d{2})\s?(재두|재다|가합|가단|구합|구단|헌바|헌마|헌가|두|누|다|도|나|후|허|므|구|부|노|고단|고합)\s?(\d{2,6})(?!\d)"),
    re.compile(r"(?:조심|국심)\s?((?:19|20)\d{2})\s?(서|중|부|광|전|구|인|경|지)\s?(\d{2,6})(?!\d)"),
]

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

_EXEC_STD = re.compile(r"(?<![\d의])(\d{1,3}(?:의\d{1,2})?-\d{1,3}(?:의\d{1,2})?-\d{1,3})(?![\d])")
_TAG = re.compile(r"\[(판례|심판례|해석례|예규|조문)\s*:\s*([^\]]+)\]")
_AUTHORITY = re.compile(r"대법원|판시|판례|심판원|조세심판|심판례|결정례|헌법재판소|헌재|예규|집행기준|유권해석|해석례|질의회신")
_NEGATION = re.compile(r"없음|없습니다|없으며|없고|없어|확인되지|확인하지 못|찾지 못|미조회|조회되지|조회하지 못")
_TEMPLATE_LABELS = ("상세 법리 및 기준 검토", "상세법리 및 기준검토", "실무 적용 및 리스크 주의사항", "실무적용 및 리스크 주의사항", "근거자료 및 검색방법", "근거 자료 및 검색 방법", "관련법령")
_QUOTE = re.compile(r"[“\"]([^”\"]{12,})[”\"]")

def _letters(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]", "", text or "")

def _quote_mismatches(line: str, case_nos: list, details: list) -> list[str]:
    bad = []
    pool = [d for d in details if any(n in _norm(d) for n in case_nos)] if case_nos else details
    pool_letters = [_letters(d) for d in pool]
    for q in _QUOTE.findall(line):
        segments = [seg for seg in re.split(r"…|\.\.\.|⋯|중략", q) if len(_letters(seg)) >= 10]
        for seg in segments:
            if not any(_letters(seg) in t for t in pool_letters):
                bad.append("판례 인용문이 조회한 원문과 다름: \"" + q[:25] + "…\"")
                break
    return bad

def _find_case_numbers(text: str) -> list[str]:
    cited = []
    for pat in _CASE_NO_PATTERNS:
        for m in pat.finditer(text or ""):
            no = "".join(m.groups())
            if no not in cited:
                cited.append(no)
    return cited

def _find_article_refs(text: str, trace: dict = None) -> list[tuple]:
    text = text or ""
    titles = _known_law_titles(trace)
    refs = []
    last_end = 0
    for m in _ARTICLE_NO.finditer(text):
        prefix = text[max(last_end, m.start() - 45):m.start()]
        last_end = m.end()
        stripped = re.sub(r"[\s「」『』\[\]:(),·ㆍ]+$", "", prefix)
        if not stripped or not re.search(r"(법|령|규칙)$", _norm(stripped)):
            continue
        name = _resolve_law_name(stripped, titles)
        if not name:
            continue
        ref = (name, int(m.group(1)), int(m.group(2) or 0))
        if ref not in refs:
            refs.append(ref)
    return refs

def _article_label(ref: tuple) -> str:
    name, jo, gaji = ref
    return f"{name} 제{jo}조" + (f"의{gaji}" if gaji else "")

def _scan_violations(answer: str, trace: dict) -> list[tuple]:
    """답변을 줄 단위로 검사해 [(줄번호, [위반 설명...]), ...]을 돌려줍니다."""
    detail_blob = _norm(" ".join(trace["detail"]))
    list_blob = _norm(" ".join(trace["list"]))
    fetched = trace["articles"]

    violations = []
    in_refs_section = False
    parent_stack = []

    for i, line in enumerate(answer.split("\n")):
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            in_refs_section = ("근거 자료" in s) or ("근거자료" in s) or ("관련법령" in s) or ("관련 법령" in s)
            parent_stack = []
            continue
        line_cases = []

        indent = len(line) - len(line.lstrip(" "))
        while parent_stack and parent_stack[-1][0] >= indent:
            parent_stack.pop()
        inherited_ok = any(ok for _, ok, _ in parent_stack)
        parent_cases = [n for _, _, nos in parent_stack for n in nos]

        compact = _norm(line)
        problems = []
        verified_source = False

        for no in _find_case_numbers(line):
            if no in detail_blob:
                verified_source = True
            elif no in list_blob and "요지미조회" in compact:
                verified_source = True
            elif no in list_blob:
                problems.append(f"판례·심판례 {no} (목록만 조회, 원문 미조회)")
            else:
                problems.append(f"판례·심판례 {no} (조회 기록 없음)")

        for ref in _find_article_refs(line, trace):
            if ref in fetched:
                verified_source = True
            else:
                problems.append(f"{_article_label(ref)} (조문 원문 미조회)")

        for no in _EXEC_STD.findall(line):
            if _norm(no) in detail_blob:
                verified_source = True
            else:
                problems.append(f"집행기준 {no} (원문 미조회)")

        for kind, val in _TAG.findall(line):
            if kind == "조문":
                refs = _find_article_refs(val, trace)
                if not refs:
                    problems.append(f"[조문:{val}] (법령명이 빠져 검증 불가)")
            else:
                nos = _find_case_numbers(val)
                if nos:
                    ok = all(n in detail_blob or (n in list_blob and "요지미조회" in compact) for n in nos)
                else:
                    ok = _norm(val) in detail_blob
                if ok:
                    verified_source = True
                elif not nos:
                    problems.append(f"[{kind}:{val}] (원문 미조회)")

        line_cases = _find_case_numbers(line) + [n for k, v in _TAG.findall(line) if k != "조문" for n in _find_case_numbers(v)]
        if (line_cases or inherited_ok or _TAG.search(line)) and _QUOTE.search(line):
            problems.extend(_quote_mismatches(line, line_cases or parent_cases, trace["detail"]))

        if not in_refs_section and not problems:
            body = line
            for lbl in _TEMPLATE_LABELS:
                body = body.replace(lbl, "")
            if (_AUTHORITY.search(body) and not _TAG.search(line) and not verified_source
                    and not inherited_ok and not _NEGATION.search(body)):
                problems.append("출처 표시 없는 판례·예규 서술: \"" + s[:40] + "…\"")

        parent_stack.append((indent, verified_source and not problems, line_cases))
        if problems:
            violations.append((i, problems))
    return violations

def _violation_labels(violations: list[tuple]) -> list[str]:
    labels = []
    for _, probs in violations:
        for p in probs:
            if p not in labels:
                labels.append(p)
    return labels

def _show_diag() -> bool:
    return _get_secret_or_env("SHOW_DIAGNOSTICS").lower() in ("on", "true", "1")

def _redact_lines(answer: str, violations: list[tuple]) -> str:
    bad = {i: probs for i, probs in violations}
    out = []
    for i, line in enumerate(answer.split("\n")):
        if i in bad:
            probs = bad[i]
            has_fake_case = any("판례·심판례" in p and "조회 기록 없음" in p for p in probs)
            if not has_fake_case:
                out.append(line)
                continue
            reasons = [r.split(":")[0] for r in probs]
            reason_txt = "; ".join(dict.fromkeys(reasons))[:120]
            if not _show_diag():
                print(f"[시스템] 🚫 미조회 사건번호 삭제: {reason_txt} | {line.strip()[:60]}")
                continue
            indent = len(line) - len(line.lstrip(" "))
            out.append(" " * indent + f"- 🚫 *(미조회 판례·심판례 삭제: {reason_txt})*")
            continue
        out.append(line)
    return "\n".join(out)

# ---------------------------------------------------------
# 🧪 의미 검증 (검증 모델)
# ---------------------------------------------------------
def _strip_md(text: str) -> str:
    return re.sub(r"[*_`>#]", "", text or "").strip(" -")

def _extract_claims(answer: str, trace: dict, max_claims: int = 20) -> tuple[list, dict]:
    mult = 3 if trace.get("unleash") else 1
    effective_max_claims = max_claims * mult
    src_char_cap = 6000 * mult
    total_char_cap = 40000 * mult

    details = trace["detail"]
    art_texts = trace.get("article_texts", {})
    sources, src_index = {}, {}

    def _src_id(label: str, text: str) -> str:
        if label not in src_index:
            sid = f"S{len(src_index) + 1}"
            src_index[label] = sid
            sources[sid] = (label, text[:src_char_cap])
        return src_index[label]

    claims = []
    in_refs = False
    stack = []
    for i, line in enumerate(answer.split("\n")):
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            in_refs = ("근거 자료" in s) or ("근거자료" in s) or ("관련법령" in s) or ("관련 법령" in s)
            stack = []
            continue
        if in_refs:
            continue
        indent = len(line) - len(line.lstrip(" "))
        while stack and stack[-1][0] >= indent:
            stack.pop()
        parent_cases = [n for _, nos in stack for n in nos]

        tags = _TAG.findall(line)
        line_cases = [n for n in _find_case_numbers(line) if any(n in _norm(d) for d in details)]
        stack.append((indent, line_cases))

        src_ids = []
        for kind, val in tags:
            if kind == "조문":
                for ref in _find_article_refs(val, trace):
                    if ref in art_texts:
                        src_ids.append(_src_id(_article_label(ref), art_texts[ref]))
            else:
                nos = _find_case_numbers(val)
                for d in details:
                    nd = _norm(d)
                    if (nos and any(n in nd for n in nos)) or (not nos and _norm(val) in nd):
                        src_ids.append(_src_id(f"{kind} {val}", d))
        body = _strip_md(_TAG.sub("", line))
        if not tags:
            cases = line_cases if (line_cases and len(body) >= 40) else (parent_cases if len(body) >= 15 else [])
            for n in cases:
                for d in details:
                    if n in _norm(d):
                        src_ids.append(_src_id(f"판례 {n}", d))
        src_ids = list(dict.fromkeys(src_ids))
        if src_ids and len(body) >= 15:
            claims.append({"line": i, "text": body[:400], "sources": src_ids})
        if len(claims) >= effective_max_claims:
            break

    total = sum(len(t) for _, t in sources.values())
    for key, txt in art_texts.items():
        label = _article_label(key)
        if label not in src_index and total < total_char_cap:
            _src_id(label, txt)
            total += min(len(txt), src_char_cap)
    for idx, d in enumerate(details):
        head = d.split("\n", 1)[0][:55]
        if head in src_index:
            head = f"{head} (#{idx + 1})"
        if total < total_char_cap:
            _src_id(head, d)
            total += min(len(d), src_char_cap)
    return claims, sources

def _semantic_verify(api_key: str, claims: list, sources: dict, user_query: str = "") -> dict:
    src_block = "\n\n".join(f"[{sid}] {label}\n{text}" for sid, (label, text) in sources.items())
    claim_block = "\n".join(f"{n + 1}. (근거: {', '.join(c['sources'])}) {c['text']}" for n, c in enumerate(claims))
    prompt = (
        "당신은 세무 답변의 근거를 검증하는 감수자입니다. 아래 [사용자 질문(사례 전제)]와 [원문(법령·판례·계산 결과)] 전체를 기준으로 각 [주장]의 '핵심 법적 명제'가 뒷받침되는지 판정하세요.\n"
        "- supported: 핵심 법리가 [원문]에 부합하고, 사례 금액·계산값이 [사용자 질문] 또는 [정밀 계산 완료] 내역과 일치함. 특히 법령 원문의 천분율·만분율(예: 1천분의 70.9, 1천분의 90, 1만분의 91.82)을 백분율(%)로 환산한 수치나 노사 절반(50%, 1/2) 부담분으로 나눈 수치(예: 3.545%, 4.5%, 0.4591%, 건보료 대비 12.95% 등), 같은 뜻의 요약·의역, 원문들을 결합해 도출되는 당연한 세무조정·소득처분 결론은 모두 supported로 판정할 것\n"
        "- partial: 법령상의 고정 기준 수치(예: 세율, 법정한도율, 기준금액)를 [원문]의 환산값과도 다르게 잘못 적은 경우에만 부여할 것. (사용자 질문의 사례 금액이나 단위 환산·절반 분담 계산값이 법조문 글자와 표기 형태만 다르다는 이유로 partial을 주지 말 것!)\n"
        "- unsupported: 핵심 법리 자체가 [원문] 어디에도 없거나 [원문]과 정면으로 모순되는 경우\n"
        "원문 밖의 지식으로 판단하지 마세요. 사소한 표현 차이로 partial/unsupported를 주지 말 것. "
        "reason은 한국어 30자 이내로, 'S1' 같은 번호 대신 법령·판례 이름으로 쓰세요.\n"
        '출력은 JSON 배열만: [{"id": 1, "verdict": "supported", "reason": "..."}]\n\n'
        f"[사용자 질문(사례 전제)]\n{user_query[:3000]}\n\n[원문]\n{src_block}\n\n[주장]\n{claim_block}"
    )
    try:
        client = genai.Client(api_key=api_key, http_options={"timeout": 60000})
    except Exception:
        client = genai.Client(api_key=api_key)
    resp = client.models.generate_content(
        model=VERIFIER_MODEL_ID,
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    raw = extract_safe_text(resp)
    _extract_and_log_response_usage(resp, VERIFIER_MODEL_ID, count_call=False, est_in_chars=len(prompt), est_out_chars=len(raw))
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip()).strip()
    data = json.loads(raw)
    result = {}
    for item in data if isinstance(data, list) else []:
        try:
            cid = int(item.get("id"))
            verdict = str(item.get("verdict", "")).strip().lower()
            if verdict in ("supported", "partial", "unsupported"):
                reason = str(item.get("reason", ""))[:60]
                for sid, (label, _) in sources.items():
                    reason = re.sub(rf"\b{sid}\b", label[:30], reason)
                result[cid] = (verdict, reason)
        except Exception:
            continue
    return result

def _apply_semantic_results(answer: str, claims: list, verdicts: dict, sources: dict = None) -> tuple[str, dict]:
    counts = {"supported": 0, "partial": 0, "unsupported": 0, "unknown": 0}
    for n, c in enumerate(claims):
        verdict, reason = verdicts.get(n + 1, ("unknown", ""))
        if verdict == "unsupported" and sources:
            verdict = "partial"
        counts[verdict] = counts.get(verdict, 0) + 1
        if verdict in ("partial", "unsupported"):
            print(f"[시스템] ℹ️ 의미 검증 참고({verdict}): {reason} | {c['text'][:60]}")
    return answer, counts


# ---------------------------------------------------------
# ✨ 스마트 법령 텍스트 압축기 (최근 2025~2029년 개정·신설·시행일 태그는 보존하여 신·구법 비교 지원!)
# ---------------------------------------------------------
def compress_legal_text(raw_text: str, query_filter: str = "") -> str:
    if not raw_text:
        return ""

    def _keep_recent_rev_tag(match: re.Match) -> str:
        full_tag = match.group(0)
        # 2025년 이후 최근 개정·신설 이력은 보존하여 AI가 최근 개정 조문임을 즉시 파악하게 함
        if re.search(r"202[5-9]", full_tag):
            years = re.findall(r"202[5-9]\.\s*\d{1,2}\.\s*\d{1,2}\.?", full_tag)
            kind = match.group(1)
            if years:
                return f" <최근{kind}: {', '.join(years[-2:])}>"
            return full_tag
        return ""

    cleaned = re.sub(r"<(개정|신설|타법개정|일부개정|전문개정)[^>]*>", _keep_recent_rev_tag, raw_text)
    cleaned = re.sub(r"\[(전문개정\vert{}본조신설\vert{}제목개정\vert{}제\d+조에서 이동)[^\]]*\]", _keep_recent_rev_tag, cleaned)

    mult = 3 if _is_unleashed() else 1
    qf = query_filter.strip().replace(" ", "")
    if qf.startswith("제") and "조" in qf:
        blocks = cleaned.split("\n\n")
        header = blocks[0] if blocks else ""
        exact_articles = []
        other_mentions = []

        for blk in blocks[1:]:
            blk_clean = blk.strip().replace(" ", "")
            if blk_clean.startswith(qf + "(") or blk_clean.startswith(qf + " ") or blk_clean == qf:
                exact_articles.append(blk.strip())
            else:
                other_mentions.append(blk.strip())

        if exact_articles:
            cleaned = header + "\n\n" + "\n\n".join(exact_articles)
        else:
            cleaned = header + "\n\n" + "\n\n".join(other_mentions[:3 * mult])

    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    base_limit = 12000 if (qf.startswith("제") and "조" in qf) else 3500
    limit = base_limit * mult
    if len(cleaned) > limit:
        return (cleaned[:limit]
                + f"\n\n[※ 원문 {len(cleaned):,}자 중 {limit:,}자까지만 표시됨. 필요한 항이 없으면 "
                  "query_filter에 '제78조의3 제8항'처럼 항 번호까지 넣어 다시 조회할 것]")
    return cleaned


# ---------------------------------------------------------
# 1. 모델 설정 및 개편된 3대 라우팅 프로토콜 + 월 2만원 Pro 차단기
# ---------------------------------------------------------
def _model_id(env_key: str, default: str) -> str:
    return _get_secret_or_env(env_key) or default

FLASH_MODEL_ID     = _model_id("GEMINI_FLASH_MODEL", "gemini-3.8-flash")
FLASH_BACKUP_ID    = _model_id("GEMINI_FLASH_BACKUP_MODEL", "gemini-3.6-flash")
VERIFIER_MODEL_ID  = _model_id("GEMINI_VERIFIER_MODEL", "gemini-3.8-flash")
SEMANTIC_VERIFY_ON = _get_secret_or_env("SEMANTIC_VERIFY").lower() not in ("off", "false", "0")
PAID_PRO_MODEL_IDS = [
    _model_id("GEMINI_PAID_PRO_MODEL", "gemini-3.1-pro-preview"),
    "gemini-4-argon",
]

def _is_model_not_found(e: Exception) -> bool:
    s = str(e)
    return ("404" in s or "NOT_FOUND" in s) and "model" in s.lower()

LARGE_FILE_AUTO_PRO_CHARS = 15000
LONG_SIMUL_QUERY_CHARS    = 600

SIMUL_KEYWORDS = [
    "시뮬레이션", "시나리오", "비교", "플랜", "부담부증여", "분할증여",
    "일괄증여", "법인전환", "절세전략", "유불리", "실효세율"
]

def select_optimal_model(user_query: str, has_file: bool = False, full_input_len: int = 0) -> tuple[str, str, str]:
    q_clean = (user_query or "").strip()
    budget_exceeded, cur_krw, limit_krw = is_pro_budget_exceeded()

    wants_manual_pro = q_clean.startswith("[프로]")
    wants_file_pro   = has_file and full_input_len >= LARGE_FILE_AUTO_PRO_CHARS

    if (wants_manual_pro or wants_file_pro) and budget_exceeded:
        block_notice = (
            f"> ⛔ **[월간 요금 한도({limit_krw:,.0f}원) 도달 — Pro 모드 자동 차단됨]** "
            f"당월 누적 API 예상 요금(**{cur_krw:,.0f}원**)이 설정된 월 한도({limit_krw:,.0f}원)를 초과하여 "
            "과금 보호를 위해 **Flash 표준 모드**로 자동 전환되었습니다.\n"
        )
        return "FLASH", "⚡ **[Flash 표준 모드 (월 한도 초과 보호 작동)]** 실무 표준 검토", block_notice

    if wants_manual_pro:
        return (
            "PRO",
            "🧠 **[Pro 심층 모드 (데이터·도구 한도 3배 개방)]** 사용자 지정 정밀 검토 (`[프로]`)",
            ""
        )

    if wants_file_pro:
        return (
            "PRO",
            f"🧠 **[Pro 심층 모드 자동 전환 (데이터·도구 한도 3배 개방)]** 대용량 첨부문서({full_input_len:,}자) 정밀 분석",
            ""
        )

    matched_simul = [kw for kw in SIMUL_KEYWORDS if kw in q_clean]
    if len(q_clean) >= LONG_SIMUL_QUERY_CHARS and len(matched_simul) >= 1 and not budget_exceeded:
        kw_str = ", ".join(matched_simul[:3])
        notice = (
            f"> 💡 **[Pro 정밀검토 전환 안내]** 초장문({len(q_clean):,}자) 시뮬레이션 질의(감지 키워드: `{kw_str}`)가 확인되었습니다. "
            "현재 답변은 표준 한도(Flash)로 빠르게 작성되었으며, **판례·예규 전문 독해 및 데이터·도구 한도 3배 개방(Unleash)**을 통한 "
            "심층 재검토가 필요하시면 좌측 **Pro 토글을 켜거나** 답변 하단의 **`🧠 [프로] 3배 개방 재검토`** 버튼을 눌러주세요.\n"
        )
        return "FLASH", "⚡ **[Flash 빠른 검토 모드]** 실무 표준 검토", notice

    return "FLASH", "⚡ **[Flash 빠른 검토 모드]** 실무 표준 검토", ""

# 2. Gemini 도구 정의
def search_law_for_gemini(keyword: str, target: str = "law") -> str:
    if _over_limit("search", target):
        print(f"\n[시스템] ⛔ 검색 한도 도달 → 차단: '{keyword}' (대상: {target})")
        return (f"[검색 한도 도달] 이번 질문에서 '{target}' 검색은 더 할 수 없습니다. "
                "지금까지 조회한 원문만으로 답변을 작성하고, 찾지 못한 근거는 '관련 원문을 확인하지 못했다'고 쓰세요.")
    print(f"\n[시스템] 💡 목록 검색 도구 가동: '{keyword}' (대상: {target})")
    results = law_api.search_law_data(keyword, target)
    used_keyword = keyword

    if not results and target in ("prec", "decc", "expc", "admrul"):
        print(f"[시스템]    ↳ 제목 검색 결과 없음 → 본문 검색으로 재시도")
        results = law_api.search_law_data(keyword, target, search_mode=2)
        if results:
            used_keyword = keyword + " (본문검색)"

    words = keyword.split()
    while not results and len(words) > 1:
        words = words[:-1]
        used_keyword = " ".join(words)
        print(f"[시스템]    ↳ 결과 없음 → '{used_keyword}'로 자동 재검색")
        results = law_api.search_law_data(used_keyword, target)
        if not results and target in ("prec", "decc", "expc", "admrul"):
            results = law_api.search_law_data(used_keyword, target, search_mode=2)

    if not results:
        return _record("list", f"'{keyword}' (대상: {target}) 검색 결과가 없습니다. 법령은 법령명만, 판례는 핵심 주제어 1~2개로 다시 검색하세요.")

    if isinstance(results, dict):
        results = [results]

    top_n = 10 if _is_unleashed() else 5
    summary = ""
    if used_keyword != keyword:
        summary += f"※ '{keyword}' 검색 결과가 없어 '{used_keyword}'(으)로 재검색한 결과입니다.\n"
    summary += f"총 {len(results)}건 검색됨 (상위 {min(len(results), top_n)}건 요약):\n"
    for i, item in enumerate(results[:top_n]):
        if target == "law":
            summary += f"{i+1}. [법령] {item.get('법령명한글')} | 공포번호: {item.get('공포번호')} | 공포일: {item.get('공포일자')} | 시행일: {item.get('시행일자')} | 구분: {item.get('제개정구분명')} | ID: {item.get('법령일련번호')}\n"
        elif target == "prec":
            summary += f"{i+1}. [판례] 사건명: {item.get('사건명')} | 사건번호: {item.get('사건번호')} | 선고일자: {item.get('선고일자')} | ID: {item.get('판례일련번호')}\n"
        elif target == "decc":
            case_no = item.get('사건번호') or item.get('청구번호') or '-'
            dec_id = item.get('특별행정심판재결례일련번호') or item.get('행정심판재결례일련번호') or item.get('id') or '-'
            summary += f"{i+1}. [조세심판/특별행정심판] 사건명: {item.get('사건명')} | 청구(사건)번호: {case_no} | 의결일자: {item.get('의결일자') or item.get('처분일자')} | ID: {dec_id}\n"
        elif target == "admrul":
            summary += f"{i+1}. [행정규칙/예규/고시] {item.get('행정규칙명')} | 소관부처: {item.get('소관부처명')} | 발령번호: {item.get('발령번호')} | 발령일: {item.get('발령일자')} | ID: {item.get('행정규칙일련번호')}\n"
        elif target == "expc":
            summary += f"{i+1}. [법령해석례/질의회신] 안건명: {item.get('안건명')} | 안건번호: {item.get('안건번호')} | 회신기관: {item.get('회신기관명')} | ID: {item.get('법령해석례일련번호')}\n"
        elif target == "ordin":
            summary += f"{i+1}. [지자체 조례/자치법규] {item.get('자치법규명', item.get('법령명한글'))} | 지자체: {item.get('지자체기관명')} | 시행일: {item.get('시행일자')} | ID: {item.get('자치법규일련번호', item.get('법령일련번호'))}\n"
        else:
            summary += f"{i+1}. {item.get('법령명한글', item.get('행정규칙명', '제목 없음'))}\n"
    trace = _TOOL_TRACE.get()
    if trace is not None and target in ("prec", "decc"):
        for item in results[:10]:
            rid = item.get("판례일련번호") or item.get("특별행정심판재결례일련번호") or item.get("행정심판재결례일련번호")
            rno = item.get("사건번호") or item.get("청구번호")
            if rid and rno:
                trace["id_map"][str(rid).strip()] = rno.strip()
    return _record("list", summary)

def get_law_details_for_gemini(doc_id: str, target: str = "law", query_filter: str = "") -> str:
    trace = _TOOL_TRACE.get()
    if trace is not None and target != "law":
        seen = trace.setdefault("seen_docs", set())
        if (target, str(doc_id)) in seen:
            print(f"\n[시스템] ♻️ 이미 조회한 원문 → 재조회 생략: ID '{doc_id}' (대상: {target})")
            return "[이미 조회한 원문] 이 문서는 이번 질문에서 이미 전체 원문을 조회했습니다. 앞의 조회 결과를 그대로 참고하세요."
        seen.add((target, str(doc_id)))
    if _over_limit("detail", target):
        print(f"\n[시스템] ⛔ 원문 조회 한도 도달 → 차단: ID '{doc_id}' (대상: {target})")
        return (f"[원문 조회 한도 도달] 이번 질문에서 '{target}' 원문 조회는 더 할 수 없습니다. "
                "이미 조회한 원문만으로 답변을 작성하세요.")
    print(f"\n[시스템] 📖 원문 정밀 조회 가동: ID '{doc_id}' (대상: {target}, 필터: '{query_filter}')")
    raw_text = law_api.get_law_content(doc_id, target, query_filter)
    result = compress_legal_text(raw_text, query_filter)
    preview = result[:150].replace("\n", " ")
    print(f"[시스템]    ↳ 원문 {len(raw_text or ''):,}자 → 전달 {len(result):,}자 | 앞부분: {preview}")
    if target == "law":
        _record_law_articles(result)
    trace = _TOOL_TRACE.get()
    if trace is not None and target in ("prec", "decc"):
        rno = trace["id_map"].get(str(doc_id).strip())
        body_ok = result and not result.startswith("❌") and len(result) >= 300
        if rno and body_ok and _norm(rno) not in _norm(result):
            result = f"[사건(청구)번호: {rno}]\n" + result
        if not body_ok:
            print(f"[시스템]    ↳ ⚠️ 원문이 비었거나 오류: {result[:120]}")
    return _record("detail", result)

def search_exchange_rate_for_gemini(start_date: str, end_date: str, currency: str = "USD") -> str:
    print(f"\n[시스템] 💱 한국은행 환율 조회 도구 가동: {currency} ({start_date}~{end_date})")
    return _record("detail", law_api.get_bok_exchange_rate(start_date, end_date, currency))

def search_base_rate_for_gemini(start_date: str, end_date: str) -> str:
    print(f"\n[시스템] 📈 한국은행 기준금리 조회 도구 가동: ({start_date}~{end_date})")
    return _record("detail", law_api.get_bok_base_rate(start_date, end_date))

def search_industry_code_for_gemini(keyword: str) -> str:
    print(f"\n[시스템] 🏢 국세청 업종코드 검색 도구 가동: '{keyword}'")
    return _record("detail", law_api.search_industry_code(keyword))

def search_dart_corp_for_gemini(corp_name: str, bsns_year: str = "2025") -> str:
    print(f"\n[시스템] 📊 DART 전자공시 통합 조회 가동: '{corp_name}' ({bsns_year}년)")
    cap = 12000 if _is_unleashed() else 4000
    return _record("detail", law_api.get_dart_corp_info(corp_name, bsns_year)[:cap])

def check_nts_biz_status_for_gemini(biz_numbers: str) -> str:
    print(f"\n[시스템] 🔎 국세청 사업자등록 상태·과세유형 실시간 조회 가동: '{biz_numbers}'")
    return _record("detail", law_api.get_nts_biz_status(biz_numbers))

def verify_nts_biz_info_for_gemini(b_no: str, start_dt: str, p_nm: str, b_nm: str = "") -> str:
    print(f"\n[시스템] 🛡️ 국세청 사업자등록 진위확인 가동: {b_no} | {start_dt} | {p_nm}")
    if hasattr(law_api, "verify_nts_biz_info"):
        return _record("detail", law_api.verify_nts_biz_info(b_no, start_dt, p_nm, b_nm))
    return "현재 law_api.py에 진위확인 함수가 없습니다."

def search_real_estate_trade_for_gemini(property_type: str, region: str, deal_ymd: str, filter_keyword: str = "") -> str:
    print(f"\n[시스템] 🏘️ 국토교통부 부동산 실거래가 조회 가동: 유형={property_type} | 지역={region} | 연월={deal_ymd} | 필터='{filter_keyword}'")
    if hasattr(law_api, "get_molit_real_estate_trade"):
        return _record("detail", law_api.get_molit_real_estate_trade(property_type, region, deal_ymd, filter_keyword))
    return "현재 law_api.py에 부동산 실거래가 조회 함수가 없습니다."

def search_official_land_price_for_gemini(address: str, stdr_year: str = "") -> str:
    print(f"\n[시스템] 🏛️ 브이월드 공시지가·공동주택공시가격 조회 가동: 주소='{address}' | 기준연도='{stdr_year}'")
    if hasattr(law_api, "get_vworld_official_price"):
        return _record("detail", law_api.get_vworld_official_price(address, stdr_year))
    return "현재 law_api.py에 공시지가 조회 함수가 없습니다."

def run_tax_calculator_for_gemini(formula_expression: str, description: str = "") -> str:
    print(f"\n[시스템] 🧮 파이썬 정밀 세액 계산기 가동: [{description}] 수식: {formula_expression}")
    allowed_names = {
        "abs": abs, "round": round, "min": min, "max": max, "sum": sum, "pow": pow,
        "int": int, "float": float, "math": math
    }
    try:
        clean_expr = formula_expression.strip().replace(",", "")
        result = eval(clean_expr, {"__builtins__": {}}, allowed_names)
        if isinstance(result, (int, float)):
            return _record(
                "detail",
                f"🧮 [정밀 계산 완료 - {description} | 수식: {clean_expr}]\n- 입력 수식: {clean_expr}\n- 정확한 산출값: {result:,.4f} (정수 반올림: {round(result):,}원)"
            )
        return _record("detail", f"🧮 [정밀 계산 완료 - {description} | 수식: {clean_expr}]\n- 결과: {result}")
    except Exception as e:
        return f"❌ 수식 계산 오류 ({formula_expression}): {e} -> 올바른 파이썬 사칙연산 수식으로 다시 호출하세요."

# 3. 에이전트 시스템 프롬프트 템플릿 (완전체 3단 체크 + 최근 개정 조문 신·구법 비교표 자동 생성 지침 탑재)
SYSTEM_PROMPT = """당신은 세무·법령·회계·노무 검토 자율 전문 에이전트입니다.
사용자의 질문 성격에 따라 아래의 **[투트랙(Two-Track) 운영 프로토콜]**을 지능적으로 구분하여 작동하세요.

[투트랙(Two-Track) 운영 프로토콜 — 최우선 판단 기준]
- **📋 트랙 1 [전문 검토 보고서 모드]**: 세무·법령·회계·노무·4대보험에 관한 법리 검토, 요건 판정, 수당·세액·공제 계산, 기업 공시·실거래가·공시지가·사업자 상태 조회 등 **법령 검색이나 데이터/수식 계산이 필요한 모든 전문 질문**일 때 작동합니다. 반드시 먼저 제공된 도구(API)들을 사용하여 실제 원문 데이터와 통계를 확인한 뒤, **3번의 `<precheck>` 정식 3단 크로스체크 검수표를 한 글자도 축약 없이 먼저 작성하고 이어서 [1. 결론 -> 2. 내용 -> 3. 관련법령] 보고서 양식**으로 출력하세요.
- **💬 트랙 2 [자유 대화 및 실무 초안 모드]**: 사용자가 일상적인 대화·인사·브레인스토밍을 하거나, 직전 검토 결과를 바탕으로 **'거래처/고객 안내용 카톡·문자·이메일 초안 작성', '쉬운 요약 설명', '문장 다듬기', '일반 양식 작성'** 등을 요청한 경우에 작동합니다. 이때는 `<precheck>`나 보고서 양식, 대괄호 출처 태그([조문:...])를 모두 생략하고 자연스럽고 친절한 대화체나 사용자가 요청한 실무 양식(카톡/이메일 등)으로 자유롭게 답변하세요.

[트랙 1 (전문 검토 보고서 모드) 필수 도구 호출 원칙]
- **[핵심 조문 조회 원칙]**: 세법·노동법·공단 규정 등 법령 질문은 **법률과 시행령(필요시 시행규칙)의 해당 조문을 모두** 원문으로 조회한 뒤 답변할 것. 도구 호출은 필요한 만큼 하되, **이미 결과를 받은 검색을 같은 검색어로 반복하지 말 것.**
- 법령 검색(search_law_for_gemini, target='law')의 keyword에는 **법령명만** 넣을 것 (예: '소득세법', '근로기준법', '소득세법 시행령'). 주제어는 넣지 말 것.
- 조회한 원문에서 직접 확인하지 못한 금액·비율·연도는 단정하지 말고 **"(원문 미확인)"**이라고 표시할 것.
- **[근거 표시 의무 (트랙 1 전용)]** 전문 검토 보고서(1. 결론 ~ 3. 관련법령)를 작성할 때 판례·심판례·해석례·예규·법령 조문을 근거로 쓰는 문장 끝에는 반드시 아래 형식의 근거 표시를 붙일 것(닫는 대괄호 ']'가 누락되지 않도록 주의).
  * 판례: [판례:2005두9415] / 조세심판: [심판례:조심2020서1234] / 법령해석례: [해석례:안건번호] / 예규·고시: [예규:문서명 또는 번호]
  * 법령 조문: [조문:법인세법 시행령 제89조] (반드시 정식 법령명 포함. '동법', '같은 법' 사용 금지)
- **판례·심판례·해석례 인용 규칙**: 판결요지·결정요지를 서술하는 사건은 반드시 get_law_details_for_gemini(target='prec' 등)로 **원문을 조회한 사건만** 쓸 것. 목록 검색에서만 본 사건은 사건번호·선고일만 적고 "(요지 미조회)"로 표시할 것. **도구로 조회하지 않은 사건번호를 기억으로 적지 말 것.**
- **법령 조문 인용 규칙**: 전문 검토 보고서에 법령명과 함께 적는 조문(예: 「법인세법」 제52조)은 반드시 get_law_details_for_gemini로 **그 조문을 조회한 것만** 쓸 것. 조회하지 않은 조문이 필요하면 먼저 조회할 것.
- **답변에 시스템·도구·검증 절차·삭제 여부에 대한 언급을 절대 쓰지 말 것**. 근거가 부족하면 "관련 원문을 확인하지 못했다"고만 쓸 것.
- **법령명은 반드시 정식 명칭**으로 쓸 것 (예: 「상속세 및 증여세법」, 「조세특례제한법 시행령」, 「근로기준법」).
- **근거 표시는 그 문장의 내용이 실제로 해당 원문에 있을 때만** 붙일 것. 한 판례에 없는 내용을 그 판례 근거 표시로 묶지 말 것.
- **따옴표(“ ”) 인용은 조회한 원문을 글자 그대로 옮길 때만** 사용하고, 요약·의역할 때는 따옴표를 쓰지 말 것.
- **[수식 및 표 작성 규칙]**: 인쇄용 문서 출력 시 글자가 깨지는 LaTeX 수식 문법($$, $, \\frac, \\times, \\text 등)은 절대 사용하지 말고 일반 텍스트 기호(×, ÷, +, -, =)로만 깔끔하게 표기할 것. 마크다운 표를 작성할 때는 반드시 표 위아래로 빈 줄을 띄우고 헤더 구분선(| --- | --- |)을 정확히 작성할 것.
- 법령·판례·심판례·예규·지방세조례 확인: 'search_law_for_gemini'로 ID를 찾은 뒤 'get_law_details_for_gemini'(반드시 query_filter에 조문번호 입력)로 핵심 조문만 읽을 것.
- 기업 공시·재무·지분·배당·출자 확인: 'search_dart_corp_for_gemini' 호출.
- 사업자 상태(휴·폐업/과세유형) 및 진위확인: 'check_nts_biz_status_for_gemini' 또는 'verify_nts_biz_info_for_gemini' 호출.
- 부동산(아파트·오피스텔·상가·토지) 실거래가 확인: 'search_real_estate_trade_for_gemini' 호출.
- 부동산 개별공시지가 및 공동주택 공시가격(기준시가) 확인: 'search_official_land_price_for_gemini' 호출.
- 세액·공제액·수당·지분율 등 모든 숫자 계산: 반드시 'run_tax_calculator_for_gemini'를 호출하여 단 1원의 오차도 없이 정확히 계산할 것.

1. 자료 검토 우선순위 및 기준
- 1순위 (법령 및 자치법규/행정규칙): 국가법령정보센터 기준 가장 최근 개정된 [법률 / 시행령 / 시행규칙 / 지방세 조례 / 행정규칙(고시·훈령)]을 최우선 기준으로 삼을 것.
- 2순위 (공식 유권해석·판례·조세심판례): [대법원 판례('prec') / 조세심판원 결정례('decc') / 법령해석례('expc') / 세법집행기준·예규]를 대조할 것.
- 3순위 (회계기준·DART 전자공시·국세청·국토부·한국은행·업종DB): 한국회계기준원, 금융감독원(DART), 국세청 사업자 상태/진위확인, 국토교통부 실거래가 및 공시지가(브이월드), 한국은행(ECOS) 공식 환율·금리, 국세청 업종코드 데이터를 참고할 것.
- 4순위 (실무 참고): 전문가 블로그 글은 전산 처리나 실무 흐름 파악용으로만 참고하되, 1~3순위 법령·예규와 충돌하거나 법적 근거가 없는 편법은 절대 채택하지 말 것.

2. 할루시네이션(임의 생성) 금지 규칙
- 확인되지 않은 법조문 번호, 통칙·집행기준 번호, 예규·판례·심판례 번호, 업종코드(6자리), 환율·금리·재무제표·지분율·실거래가·공시지가 수치, 깨진 상세 URL을 절대 임의로 추측하거나 조합해 만들어내지 말 것.

3. 트랙 1 (전문 검토 보고서 모드) 필수 출력 양식 (반드시 아래 `<precheck>` 3단 크로스체크 검수표를 최소 200자 이상 구체적인 조문·수치로 작성한 뒤, 그 검증 결과를 바탕으로 `### 1. 결론`을 도출할 것. `<precheck>`가 누락되거나 부실하면 감사 시스템에서 즉시 반려됨!)

<precheck>
- [1단: 법령·판례 원문 및 최근 개정·귀속시기·일몰 대조] 이번에 도구로 실제 원문을 조회한 법률·시행령·시행규칙의 정확한 조·항·호 번호와 판례·심판례 사건번호를 구체적으로 열거하고, 해당 조문에 최근 개정 이력(<최근개정: 2025~2027...> 등)이나 경과규정이 있는지, 질문 사안의 귀속연도(과세기간) 적용 기준 및 조세특례 일몰기한(예: ~2026.12.31. 또는 ~2028.12.31.)이 유효한지 대조할 것
- [2단: 단서·배제 요건 및 연쇄 세목(농특세·소득처분) 정밀 점검] 해당 조문의 단서(다만, ~제외한다), 특수관계인·지배주주·업종·규모 배제 요건, 최저한세(조세특례제한법 제132조), 중복지원 배제(제127조), 농어촌특별세(20%) 부과 여부, 사후관리 추징 요건, 그리고 법인세 손금불산입 시 소득처분(상여·배당·기타사외유출)에 따른 원천세·4대보험 연쇄 리스크 중 본 사안에 적용되는 항목을 빠짐없이 짚어낼 것
- [3단: 수리 계산식·지방소득세·가산세 감면율 최종 검산] 파이썬 정밀 계산기로 산출한 수식, 세율 구간·누진공제, 안분 비율, 공제 한도액의 오차 여부 및 지방소득세(10%) 별도 부과 여부를 수치로 직접 검산할 것 (수치 계산이 없는 법리·절차 질문인 경우 법정 신고·경정청구 기한, 가산세율 및 수정신고·기한후신고 감면율 요건을 수치로 재확인할 것)
</precheck>

### 1. 결론
- 위 3단 크로스체크 결과를 바탕으로 질문에 대한 핵심 결론(가능/불가능 여부, 적용 세율·산출세액·공제액·수당·과세유형·업종코드·회계처리 등)을 명확하고 간결하게 요약

---

### 2. 내용

#### (1) 상세 법리 및 기준 검토
- 1~3순위 근거(법령 조문, 단서·예외 요건, 지자체 조례, 회계기준, 각 기관 API 조회 데이터, 예규·판례·조세심판례)를 바탕으로 상세 법리 및 요건 설명
- **[🔄 최근 개정 조문 자동 신·구 비교 원칙]**: 만약 조회한 핵심 조문에 최근 개정사항(2025~2026년 개정·신설 또는 시행예정 규정)이 포함되어 있거나 질문이 개정세법 관련 질의라면, 별도 요청이 없더라도 본 항목 안에 반드시 **`| 구분 | 종전 규정 | 현행(개정) 규정 | 적용시기 및 실무 영향 |`** 형식의 마크다운 신·구 비교표를 포함하여 무엇이 바뀌었는지 한눈에 보이도록 정리할 것.

#### (2) 계산
- 정밀 계산기(run_tax_calculator_for_gemini)로 산출한 단계별 계산 과정 및 산출 내역 (※ 단, 질문에 세액·수당·비율 등 수치 계산 내용이 전혀 없는 단순 법리 질의라면 이 '(2) 계산' 소제목과 항목은 완전히 생략하고 바로 아래 항목을 '(2) 실무 적용 및 리스크 주의사항'으로 당겨서 작성할 것)

#### (3) 실무 적용 및 리스크 주의사항
- 가산세 및 사후관리(고용감소 추징 등) 리스크, 최저한세·농어촌특별세·중복공제 배제 여부, 소득처분·지방소득세 등 연쇄 세목 영향, 증빙 수취 요건, 홈택스/위택스 신고 시 주의할 점 정리 (※ 위 계산 항목이 생략된 경우 '(2) 실무 적용 및 리스크 주의사항'으로 번호를 맞춰 기재할 것)

---

### 3. 관련법령
- 근거 자료 및 검색 방법을 `[법령/기준명 - 대표 링크주소 - 상세 검색방법(조문 위치·검색 키워드)]` 형식으로 기재
  * 국가법령정보센터(법령·판례·심판례·조례): https://www.law.go.kr
  * 국세법령정보시스템: https://taxlaw.nts.go.kr
  * 금융감독원 전자공시시스템(DART): https://dart.fss.or.kr
  * 국토교통부 실거래가 공개시스템 / 브이월드(공시가격): https://rt.molit.go.kr / https://www.vworld.kr
  * 한국은행 경제통계시스템(ECOS): https://ecos.bok.or.kr
  * 국세청 홈택스(사업자상태/업종코드): https://www.hometax.go.kr
"""

def _extract_and_strip_precheck(text: str) -> tuple[str, str]:
    """
    원문에서 <precheck>...</precheck> 내용을 추출해 (정제된_본문, 추출된_3단체크_원문) 튜플로 반환합니다.
    """
    if not text:
        return "", ""
    m = re.search(r"<precheck>(.*?)</precheck>", text, flags=re.DOTALL | re.IGNORECASE)
    if m:
        precheck_body = m.group(1).strip()
        cleaned = re.sub(r"<precheck>.*?</precheck>\s*", "", text, flags=re.DOTALL | re.IGNORECASE).lstrip()
        return cleaned, precheck_body
    elif "<precheck>" in text.lower() and "### 1. 결론" in text:
        idx = text.find("### 1. 결론")
        precheck_body = re.sub(r"</?precheck>", "", text[:idx], flags=re.IGNORECASE).strip()
        return text[idx:].lstrip(), precheck_body
    return text.lstrip(), ""

def _is_precheck_thorough(precheck_body: str) -> bool:
    """3단 크로스체크가 대충 작성되지 않고 1·2·3단 모두 구체적으로(최소 120자 이상) 작성되었는지 엄격히 검사합니다."""
    if not precheck_body or len(precheck_body.strip()) < 120:
        return False
    has_step1 = ("1단" in precheck_body) or ("원문" in precheck_body) or ("법령" in precheck_body)
    has_step2 = ("2단" in precheck_body) or ("단서" in precheck_body) or ("예외" in precheck_body) or ("배제" in precheck_body)
    has_step3 = ("3단" in precheck_body) or ("검산" in precheck_body) or ("계산" in precheck_body) or ("수치" in precheck_body)
    return bool(has_step1 and has_step2 and has_step3)

def _clean_latex_for_export(text: str) -> str:
    """히든 <precheck> 블록을 분리·제거하고, 인쇄용 문서(.html/PDF) 및 워드 출력 시 깨지는 모든 LaTeX 수식 문법을 일반 텍스트로 정제합니다."""
    if not text:
        return ""
    s, _ = _extract_and_strip_precheck(text)
    s = re.sub(r"\$\$(.*?)\$\$", r"\1", s, flags=re.DOTALL)
    s = re.sub(r"\$([^$\n]+)\$", r"\1", s)
    s = re.sub(r"\\text(?:bf|rm|it)?\{([^}]*)\}", r"\1", s)
    s = re.sub(r"\\frac\{([^}]*)\}\{([^}]*)\}", r"(\1/\2)", s)
    s = s.replace(r"\times", " × ").replace(r"\div", " ÷ ").replace(r"\cdot", "·")
    s = s.replace(r"\%", "%").replace(r"\_", "_").replace(r"\,", ",")
    s = re.sub(r"\\(left|right|quad|qquad|mathrm|mathbf)\b", "", s)
    s = re.sub(r"(\[(?:조문|판례|심판례|해석례|예규)\s*:\s*[^\]\n(]+?)\s+(\()", r"\1] \2", s)
    return s

def extract_safe_text(response) -> str:
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

def _execute_with_key_and_model(
    api_key: str,
    model_id: str,
    user_input: str,
    dynamic_prompt: str,
    tools_list: list,
    safety_settings: list,
    unleash: bool = False
) -> tuple[str, int]:
    """(정제된 최종 보고서 본문, 수행된 3단 크로스체크 글자 수)를 반환합니다."""
    timeout_ms = 120000 if unleash else 60000
    max_remote_calls = 30 if unleash else 16

    try:
        temp_client = genai.Client(api_key=api_key, http_options={"timeout": timeout_ms})
    except Exception:
        temp_client = genai.Client(api_key=api_key)

    chat = temp_client.chats.create(
        model=model_id,
        config=types.GenerateContentConfig(
            tools=tools_list,
            system_instruction=dynamic_prompt,
            safety_settings=safety_settings,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                maximum_remote_calls=max_remote_calls
            )
        )
    )
    trace_token = _TOOL_TRACE.set(_new_trace(unleash=unleash))
    try:
        response = chat.send_message(user_input)
        raw_output = extract_safe_text(response)
        _extract_and_log_response_usage(
            response, model_id, count_call=True,
            est_in_chars=len(user_input) + len(dynamic_prompt),
            est_out_chars=len(raw_output)
        )

        if not raw_output:
            follow_up = chat.send_message(
                "지금까지 조회한 법령 조문과 계산 결과를 바탕으로 추가 도구 호출 없이 즉시 <precheck> 3단 크로스체크(최소 200자 이상)를 먼저 작성한 뒤 [1. 결론 -> 2. 내용 -> 3. 관련법령] 순서로 답변을 작성해 주세요."
            )
            raw_output = extract_safe_text(follow_up)
            _extract_and_log_response_usage(follow_up, model_id, count_call=False, est_in_chars=500, est_out_chars=len(raw_output))
        trace = _TOOL_TRACE.get()
    finally:
        _TOOL_TRACE.reset(trace_token)

    if not raw_output:
        raise ValueError("빈 응답이 반환되었습니다.")

    stripped_body, precheck_text = _extract_and_strip_precheck(raw_output)
    is_formal_report = bool(re.search(r"###\s*1\.\s*결론|###\s*2\.\s*내용|###\s*3\.\s*관련법령", stripped_body))

    # 🛡️ 정식 보고서인데 <precheck> 3단 크로스체크를 건너뛰었거나 120자 미만으로 대충 적었다면 강제 재작성!
    if is_formal_report and not _is_precheck_thorough(precheck_text):
        print(f"[시스템] ⚠️ 사전 3단 크로스체크 누락/부실 감지({len(precheck_text)}자) → 정밀 3단 체크 후 재작성 강제")
        enforce_precheck_msg = (
            "방금 답변에서 `<precheck> ... </precheck>` 사전 3단 크로스체크가 누락되었거나 너무 간략하게 작성되었습니다. "
            "결론을 내리기 전에 반드시 `<precheck>` 태그 안에 ① [1단: 법령·판례 원문 및 최근 개정·귀속시기·일몰 대조], "
            "② [2단: 단서·배제 요건 및 연쇄 세목(농특세·소득처분) 정밀 점검], ③ [3단: 수리 계산식·지방소득세·가산세 감면율 최종 검산]을 "
            "구체적인 조문 번호와 수치로 최소 200자 이상 꼼꼼히 먼저 작성한 뒤, "
            "그 검증 결과를 반영하여 `### 1. 결론`부터 `### 3. 관련법령`까지 전체 보고서를 다시 작성하세요."
        )
        trace_token_p = _TOOL_TRACE.set(trace)
        try:
            p_resp = chat.send_message(enforce_precheck_msg)
            p_raw = extract_safe_text(p_resp)
            _extract_and_log_response_usage(p_resp, model_id, count_call=False, est_in_chars=len(enforce_precheck_msg), est_out_chars=len(p_raw))
            if p_raw:
                s_body2, p_text2 = _extract_and_strip_precheck(p_raw)
                if s_body2:
                    raw_output = p_raw
                    stripped_body = s_body2
                    if p_text2:
                        precheck_text = p_text2
                    response = p_resp
        except Exception as e:
            print(f"[시스템]    ↳ 3단 크로스체크 재작성 호출 오류: {e}")
        finally:
            _TOOL_TRACE.reset(trace_token_p)

    if precheck_text:
        print(f"\n[시스템] 🛡️ 사전 3단 크로스체크 정밀 수행 완료 ({len(precheck_text):,}자):\n{precheck_text}")

    final_text = re.sub(r"\s*<br\s*/?>\s*", " / ", stripped_body)
    final_text = _clean_latex_for_export(final_text)

    # ---------------------------------------------------------
    # 🔒 근거 강제 검증 (트랙 1: 정식 보고서 양식이고 도구 기록이 수집된 경우에만 작동)
    # ---------------------------------------------------------
    citation_note = ""

    if is_formal_report and trace and (trace["list"] or trace["detail"]):
        violations = _scan_violations(final_text, trace)
        if violations:
            first_labels = _violation_labels(violations)
            print(f"[시스템] 🔒 미검증 근거 {len(first_labels)}건 감지 → 재작성 요청: {first_labels[:8]}")
            fix_msg = (
                "방금 답변에서 도구 조회 기록으로 확인되지 않는 근거가 발견되었습니다:\n- "
                + "\n- ".join(first_labels[:15])
                + "\n\n각 항목에 대해 ① get_law_details_for_gemini로 원문(판결요지·조문)을 조회해 확인한 뒤 근거 표시"
                  "([판례:사건번호], [조문:정식법령명 제N조], [예규:문서명] 등)를 붙여 인용하거나, "
                  "② 조회할 수 없으면 그 근거와 관련 서술을 답변에서 완전히 삭제하세요. "
                  "'대법원은 ~ 판시' 같은 서술에도 반드시 근거 표시가 있어야 합니다. "
                  "조회하지 않은 근거는 다시 쓰지 말고, `<precheck>` 3단 크로스체크와 양식(1. 결론 → 2. 내용 → 3. 관련법령)을 유지해 전체 답변을 다시 작성하세요. "
                  "다시 쓴 답변에는 이 검증 요청이나 삭제 사실, 시스템에 대한 언급을 절대 넣지 마세요."
            )
            trace_token2 = _TOOL_TRACE.set(trace)
            try:
                retry_resp = chat.send_message(fix_msg)
                retry_text = extract_safe_text(retry_resp)
                _extract_and_log_response_usage(retry_resp, model_id, count_call=False, est_in_chars=len(fix_msg), est_out_chars=len(retry_text))
            except Exception as e:
                retry_text = ""
                print(f"[시스템]    ↳ 재작성 요청 실패: {e}")
            finally:
                _TOOL_TRACE.reset(trace_token2)

            if retry_text:
                _, retry_precheck = _extract_and_strip_precheck(retry_text)
                if retry_precheck:
                    precheck_text = retry_precheck
                final_text = re.sub(r"\s*<br\s*/?>\s*", " / ", retry_text)
                final_text = _clean_latex_for_export(final_text)
                response = retry_resp

            remaining = _scan_violations(final_text, trace)
            if remaining:
                final_text = _redact_lines(final_text, remaining)
                short = [r.split(":")[0] if r.startswith(("출처 표시 없는", "판례 인용문")) else r for r in _violation_labels(remaining)]
                short = list(dict.fromkeys(short))
                citation_note = ("\n> 🚫 재작성 후에도 검증되지 않은 근거가 남아 **코드에서 삭제**했습니다: "
                                 + "; ".join(short[:10]))
            else:
                citation_note = ("\n> 🔒 미검증 근거가 감지되어 **재작성**(원문 조회 또는 삭제)했습니다. (최초 감지 "
                                 + str(len(first_labels)) + "건)")
        else:
            citation_note = "\n> ✅ 답변의 판례·조문·예규 근거가 모두 이번 조회 기록과 일치합니다."

        if SEMANTIC_VERIFY_ON:
            claims, sources = _extract_claims(final_text, trace)
            if claims:
                print(f"[시스템] 🧪 의미 검증 가동: 주장 {len(claims)}건 / 원문 {len(sources)}건")
                try:
                    verdicts = _semantic_verify(api_key, claims, sources, user_input)
                    final_text, cnt = _apply_semantic_results(final_text, claims, verdicts, sources)
                    citation_note += (f"\n> 🧪 의미 검증 {len(claims)}건: 일치 {cnt['supported']} · "
                                      f"원문 확인 필요 {cnt['partial']}(⚠️ 표시) · 불일치 {cnt['unsupported']}(삭제)"
                                      + (f" · 판정 누락 {cnt['unknown']}" if cnt.get("unknown") else ""))
                except Exception as e:
                    print(f"[시스템]    ↳ 의미 검증 실패: {e}")
                    citation_note += "\n> 🧪 의미 검증을 수행하지 못했습니다(검증 모델 오류). 근거 표시 문장은 직접 확인하세요."

    history = []
    try:
        history = chat.get_history(curated=False) or []
    except Exception:
        pass
    if not history:
        history = getattr(response, "automatic_function_calling_history", None) or []

    calls = []
    for c in history:
        for p in (getattr(c, "parts", None) or []):
            fc = getattr(p, "function_call", None)
            if fc and getattr(fc, "name", None):
                args = ", ".join(f"{k}={v}" for k, v in (fc.args or {}).items())
                calls.append(f"{fc.name}({args})")

    limit_hit = False
    try:
        for p in (response.candidates[0].content.parts or []):
            if getattr(p, "function_call", None):
                limit_hit = True
    except Exception:
        pass

    if calls:
        diag = "\n\n---\n> 🛠 도구 호출 " + str(len(calls)) + "회: " + " → ".join(calls)
    else:
        diag = "\n\n---\n> 🛠 도구 호출 없음 (자유 대화 / 자체 지식 답변)"
    if limit_hit:
        diag += "\n> ⚠️ 도구 호출 한도에 도달해 조회가 중간에 끊겼습니다. 결론을 원문과 대조해 확인하세요."
    diag += citation_note

    if _show_diag():
        final_text += diag
    else:
        print("[시스템] 📋 진단 정보(화면 미표시):" + diag.replace("\n> ", "\n   ").replace("\n\n---", ""))
    final_text = re.sub(r"\s*<br\s*/?>\s*", " / ", final_text)

    return _clean_latex_for_export(final_text), len(precheck_text)

# 4. 실행 순서(유료키 전용): 3.8-flash → 3.6-flash (PRO 모드는 Pro 모델 + 3배 리미트 개방)
def run_agent(user_input: str, raw_query: str = "", has_file: bool = False) -> str:
    live_pool = get_live_gemini_key_pool()
    if not live_pool:
        return "❌ 설정된 Gemini 유료 API 키가 없습니다. .env 또는 Streamlit Secrets에 GEMINI_PAID_KEY를 넣어 주세요."

    query_for_routing = raw_query if raw_query else user_input
    tier_mode, mode_badge, recommend_pro_notice = select_optimal_model(
        user_query=query_for_routing,
        has_file=has_file,
        full_input_len=len(user_input)
    )
    unleash_mode = (tier_mode == "PRO")

    today_str = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y년 %m월 %d일")
    unleash_guide = (
        "\n[🚀 PRO 3배 리미트 해제 모드 가동 중: 법령 검색 최대 21회, 원문 조회 최대 36회, 판례·심판례·예규 조회 최대 6~9회, "
        "원문 길이 최대 36,000자까지 한도가 3배 확장되었습니다. 관련 법령 조문과 판례·예규의 구체적 사실관계(이유)까지 빠짐없이 깊이 있게 대조하여 작성하세요.]\n"
        if unleash_mode else ""
    )
    dynamic_prompt = (
        f"[시스템 기준일 안내: 오늘 날짜는 {today_str}입니다. 질문에 등장하는 연도와 날짜의 과거/현재 여부를 반드시 오늘 날짜({today_str}) 기준으로 판단하세요.]"
        f"{unleash_guide}\n\n" + SYSTEM_PROMPT
    )

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
        search_official_land_price_for_gemini,
        run_tax_calculator_for_gemini
    ]

    safety_settings = [
        types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"),
        types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"),
        types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"),
        types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
    ]

    execution_plan = []
    for lbl, k in live_pool:
        if tier_mode == "PRO":
            for m in PAID_PRO_MODEL_IDS:
                execution_plan.append((lbl, k, m, f"{mode_badge} *(🔑 {lbl} · {m})*"))
            for m in (FLASH_MODEL_ID, FLASH_BACKUP_ID):
                execution_plan.append((lbl, k, m, f"⚡ **[Pro 실패 → Flash 백업 (3배 리미트 개방 유지)]** *(🔑 {lbl} · {m})*"))
        else:
            for m in (FLASH_MODEL_ID, FLASH_BACKUP_ID):
                execution_plan.append((lbl, k, m, f"{mode_badge} *(🔑 {lbl} · {m})*"))

    last_error = None
    diag_notes = []
    dead_models = set()

    for key_label, current_key, target_model, final_badge in execution_plan:
        if target_model in dead_models:
            continue
        for attempt in range(2):
            try:
                final_text, precheck_len = _execute_with_key_and_model(
                    api_key=current_key,
                    model_id=target_model,
                    user_input=user_input,
                    dynamic_prompt=dynamic_prompt,
                    tools_list=tools_list,
                    safety_settings=safety_settings,
                    unleash=unleash_mode
                )
                precheck_badge = f" · 🛡️ **3단 크로스체크 완료({precheck_len:,}자 검증)**" if precheck_len > 0 else ""
                diag_header = f"> {final_badge}{precheck_badge}\n"
                if recommend_pro_notice:
                    diag_header += recommend_pro_notice
                if diag_notes:
                    if _show_diag():
                        diag_header += f"> *(ℹ️ 앞선 시도 실패: {' | '.join(diag_notes)})*\n"
                    else:
                        print("[시스템] ℹ️ 앞선 시도 실패: " + " | ".join(diag_notes))
                return diag_header + "\n" + final_text
            except Exception as e:
                if _is_model_not_found(e):
                    dead_models.add(target_model)
                m_code = re.search(r"\b(4\d\d|5\d\d)\b", str(e))
                err_short = m_code.group(1) if m_code else str(e).splitlines()[0][:40]
                retry_tag = "(재시도)" if attempt == 1 else ""
                diag_notes.append(f"{key_label}({target_model}){retry_tag}: {err_short}")
                last_error = e
                if attempt == 0 and err_short in ("500", "503", "504"):
                    time.sleep(2)
                    continue
                break

    return f"❌ 모든 API 키 호출이 실패했습니다. 마지막 오류: {str(last_error)}"
