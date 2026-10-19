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
    - 무료 한도는 키가 아니라 프로젝트 단위라 키를 늘려도 효과가 없고,
      여러 프로젝트로 한도를 늘리는 방식은 '한도 우회'로 제재될 위험이 있어 무료키 사용을 중단했습니다.
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
# 🔎 근거 추적·검증
#   - 이번 질문에서 도구가 실제로 돌려준 원문(목록/원문/조회한 조문 번호)을 기록하고,
#   - 답변에 나온 ① 사건번호 ② 법령 조문 ③ 집행기준 번호 ④ [근거 표시] ⑤ 출처 없는 판례·예규 서술을
#     조회 기록과 줄 단위로 대조합니다.
# ---------------------------------------------------------
_TOOL_TRACE = contextvars.ContextVar("tool_trace", default=None)

def _new_trace() -> dict:
    return {"list": [], "detail": [], "articles": set(), "article_texts": {}, "counts": {}, "id_map": {}}

# 질문 1건당 도구 사용 상한 (프롬프트 지시만으로는 지켜지지 않아 코드에서 강제)
_SEARCH_LIMIT = {"law": 4, "prec": 3, "decc": 3, "expc": 2, "admrul": 2, "ordin": 2}
_DETAIL_LIMIT = {"law": 8, "prec": 3, "decc": 3, "expc": 2, "admrul": 2, "ordin": 2}

def _over_limit(kind: str, target: str) -> bool:
    """kind: 'search' 또는 'detail'. 상한을 넘으면 True (넘지 않으면 횟수를 1 늘림)"""
    trace = _TOOL_TRACE.get()
    if trace is None:
        return False
    table = _SEARCH_LIMIT if kind == "search" else _DETAIL_LIMIT
    key = f"{kind}:{target}"
    used = trace["counts"].get(key, 0)
    if used >= table.get(target, 2):
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
#    법령명은 띄어쓰기·'및'이 들어간 정식 명칭이 많아서, '제N조' 앞쪽 글자를 아래 법령명 목록과 뒤에서부터 맞춰 봅니다.
_ARTICLE_NO = re.compile(r"제\s*(\d+)\s*조(?:\s*의\s*(\d+))?")
_COMMON_LAWS = [
    "상속세및증여세법", "조세특례제한법", "국세기본법", "국세징수법", "법인세법", "소득세법", "부가가치세법",
    "지방세법", "지방세기본법", "지방세특례제한법", "종합부동산세법", "개별소비세법", "교육세법", "농어촌특별세법",
    "인지세법", "증권거래세법", "국제조세조정에관한법률", "조세범처벌법", "근로기준법", "근로자퇴직급여보장법",
    "주식회사등의외부감사에관한법률", "상법", "민법", "부동산등기법", "공익법인의설립ㆍ운영에관한법률",
]
_LAW_ALIASES = {"상증법": "상속세및증여세법", "조특법": "조세특례제한법", "국기법": "국세기본법",
                "국징법": "국세징수법", "부가세법": "부가가치세법", "지특법": "지방세특례제한법",
                "국조법": "국제조세조정에관한법률", "종부세법": "종합부동산세법", "외감법": "주식회사등의외부감사에관한법률"}
_REF_SKIP_SUFFIX = ("동법", "같은법", "이법", "본법", "당해법", "해당법", "동법시행령", "같은법시행령", "동법시행규칙")

def _known_law_titles(trace: dict = None) -> list[str]:
    titles = set()
    for base in _COMMON_LAWS:
        titles.update({base, base + "시행령", base + "시행규칙"})
    if trace:
        titles.update(t for (t, _, _) in trace.get("articles", set()))
    return sorted(titles, key=len, reverse=True)   # 긴 이름부터 맞춰야 '증여세법'이 '상속세및증여세법'을 가로채지 않음

def _resolve_law_name(prefix: str, titles: list[str]):
    """'제N조' 바로 앞 글자들(prefix)의 끝부분에서 법령명을 찾아 정식 명칭(공백 제거)으로 돌려줍니다."""
    tail = _norm(prefix)[-40:]
    for suf in _REF_SKIP_SUFFIX:
        if tail.endswith(suf):
            return None
    for alias, full in _LAW_ALIASES.items():
        for ext in ("시행규칙", "시행령", ""):
            if tail.endswith(alias + ext) or tail.endswith(alias.replace("법", "령")) and ext == "시행령":
                return full + ext
    for t in titles:
        if tail.endswith(t):
            return t
    # 정식 명칭 일부만 쓴 경우 (예: '증여세법' → '상속세및증여세법')
    m = re.search(r"([가-힣ㆍ·]{2,30}?법(?:시행령|시행규칙)?)$", tail)
    if not m:
        return None
    partial = m.group(1)
    for t in titles:
        if t.endswith(partial) and len(partial) >= 3:
            return t
    return partial   # 목록에 없는 법령명 → 그대로 반환(조회 기록과 대조되어 미조회로 처리됨)

# ③ 집행기준 번호: 33의2-78의3-1, 52-88-3
_EXEC_STD = re.compile(r"(?<![\d의])(\d{1,3}(?:의\d{1,2})?-\d{1,3}(?:의\d{1,2})?-\d{1,3})(?![\d])")

# ④ 근거 표시: [판례:2005두9415] [심판례:조심2020서1234] [해석례:...] [예규:...] [조문:법인세법 제52조]
_TAG = re.compile(r"\[(판례|심판례|해석례|예규|조문)\s*:\s*([^\]]+)\]")

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
    """문장 속 '법령명 + 제N조(의M)'를 (정식법령명, 조, 가지)로 추출합니다. 법령명이 바로 앞에 없으면 건너뜁니다."""
    text = text or ""
    titles = _known_law_titles(trace)
    refs = []
    last_end = 0
    for m in _ARTICLE_NO.finditer(text):
        # 바로 앞 조문 참조 이후의 글자만 본다 (예: '법인세법 제28조 및 제52조'에서 제52조 앞은 '및')
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
    parent_stack = []   # (들여쓰기, 이 줄에 검증된 출처가 있는지, 이 줄의 사건번호들)

    for i, line in enumerate(answer.split("\n")):
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            in_refs_section = "근거 자료" in s
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

        # ① 사건번호
        for no in _find_case_numbers(line):
            if no in detail_blob:
                verified_source = True
            elif no in list_blob and "요지미조회" in compact:
                verified_source = True
            elif no in list_blob:
                problems.append(f"판례·심판례 {no} (목록만 조회, 원문 미조회)")
            else:
                problems.append(f"판례·심판례 {no} (조회 기록 없음)")

        # ② 법령 조문 (근거 표시 안팎 모두)
        for ref in _find_article_refs(line, trace):
            if ref in fetched:
                verified_source = True
            else:
                problems.append(f"{_article_label(ref)} (조문 원문 미조회)")

        # ③ 집행기준 번호
        for no in _EXEC_STD.findall(line):
            if _norm(no) in detail_blob:
                verified_source = True
            else:
                problems.append(f"집행기준 {no} (원문 미조회)")

        # ④ 근거 표시 자체 검증
        for kind, val in _TAG.findall(line):
            if kind == "조문":
                refs = _find_article_refs(val, trace)
                if not refs:
                    problems.append(f"[조문:{val}] (법령명이 빠져 검증 불가)")
                # 법령명이 있는 경우는 ②에서 이미 검사됨
            else:
                nos = _find_case_numbers(val)
                if nos:
                    ok = all(n in detail_blob or (n in list_blob and "요지미조회" in compact) for n in nos)
                else:
                    ok = _norm(val) in detail_blob
                if ok:
                    verified_source = True
                elif not nos:   # 번호 있는 경우는 ①에서 이미 지적됨
                    problems.append(f"[{kind}:{val}] (원문 미조회)")

        # ④-2 따옴표 인용문 대조 (판례·심판례 근거가 걸린 줄, 또는 그 하위 항목)
        line_cases = _find_case_numbers(line) + [n for k, v in _TAG.findall(line) if k != "조문" for n in _find_case_numbers(v)]
        if (line_cases or inherited_ok or _TAG.search(line)) and _QUOTE.search(line):
            problems.extend(_quote_mismatches(line, line_cases or parent_cases, trace["detail"]))

        # ⑤ 출처 없는 판례·예규 서술 (근거 자료 섹션은 제외)
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
    """위반 줄과 그 하위 항목(더 깊게 들여쓴 줄)을 삭제하고 삭제 사실을 한 줄로 남깁니다."""
    bad = {i: probs for i, probs in violations}
    out, skip_indent = [], None
    for i, line in enumerate(answer.split("\n")):
        indent = len(line) - len(line.lstrip(" "))
        if skip_indent is not None:
            if line.strip() and indent > skip_indent:
                continue
            skip_indent = None
        if i in bad:
            reasons = [r.split(":")[0] if r.startswith(("출처 표시 없는", "판례 인용문")) else r for r in bad[i]]
            reason_txt = "; ".join(dict.fromkeys(reasons))[:120]
            if not _show_diag():
                # 고객 화면: 삭제 표시 없이 해당 줄(과 하위 항목)만 조용히 제거, 사유는 로그로
                print(f"[시스템] 🚫 미검증 근거 삭제: {reason_txt} | {line.strip()[:60]}")
                if not line.strip().startswith("|"):
                    skip_indent = indent
                continue
            if line.strip().startswith("|"):
                # 표의 한 행이면 칸 수를 유지한 채 내용만 비움 (표가 깨지지 않게)
                n_cols = max(line.strip().strip("|").count("|") + 1, 1)
                out.append("| 🚫 *(검증되지 않아 삭제)* " + "| " * (n_cols - 1) + "|")
            else:
                out.append(" " * indent + f"- 🚫 *(검증되지 않은 근거 삭제: {reason_txt})*")
                skip_indent = indent
            continue
        out.append(line)

    # 같은 들여쓰기의 삭제 표시가 연달아 나오면 한 줄로 묶음
    merged = []
    for line in out:
        if (merged and "🚫 *(검증되지 않은 근거 삭제" in line and "🚫 *(검증되지 않은 근거" in merged[-1]
                and not line.strip().startswith("|")
                and (len(line) - len(line.lstrip(" "))) == (len(merged[-1]) - len(merged[-1].lstrip(" ")))):
            prev = merged[-1]
            m = re.search(r"(\d+)건", prev)
            n = int(m.group(1)) + 1 if m else 2
            merged[-1] = " " * (len(line) - len(line.lstrip(" "))) + f"- 🚫 *(검증되지 않은 근거 {n}건 삭제)*"
            continue
        merged.append(line)
    return "\n".join(merged)

# ---------------------------------------------------------
# 🧪 의미 검증 (검증 모델)
#   - 기계적 대조로는 못 잡는 것: 조회한 근거 표시를 붙였지만 내용은 원문에 없는 '의역 주장'
#   - 근거 표시가 붙은 문장(+검증된 판례 항목의 하위 문장)만 골라, 해당 원문과 함께
#     별도 모델에게 "원문이 이 주장을 뒷받침하는가"를 판정시킵니다.
#   - 판정: supported(통과) / partial(⚠️ 표시) / unsupported(삭제)
# ---------------------------------------------------------
def _strip_md(text: str) -> str:
    return re.sub(r"[*_`>#]", "", text or "").strip(" -")

def _extract_claims(answer: str, trace: dict, max_claims: int = 20) -> tuple[list, dict]:
    """검증 대상 문장과 그 근거 원문을 뽑습니다. 반환: (claims, sources)"""
    details = trace["detail"]
    art_texts = trace.get("article_texts", {})
    sources, src_index = {}, {}

    def _src_id(label: str, text: str) -> str:
        if label not in src_index:
            sid = f"S{len(src_index) + 1}"
            src_index[label] = sid
            sources[sid] = (label, text[:6000])
        return src_index[label]

    claims = []
    in_refs = False
    stack = []  # (indent, case_numbers)
    for i, line in enumerate(answer.split("\n")):
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            in_refs = "근거 자료" in s
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
            # 근거 표시가 없더라도, 검증된 판례 항목의 하위 문장이거나 판례번호와 함께 쓴 긴 서술이면 검증
            cases = line_cases if (line_cases and len(body) >= 40) else (parent_cases if len(body) >= 15 else [])
            for n in cases:
                for d in details:
                    if n in _norm(d):
                        src_ids.append(_src_id(f"판례 {n}", d))
        src_ids = list(dict.fromkeys(src_ids))
        if src_ids and len(body) >= 15:
            claims.append({"line": i, "text": body[:400], "sources": src_ids})
        if len(claims) >= max_claims:
            break

    # 근거 표시와 다른 조문에 내용이 있을 수 있으므로, 이번에 조회한 다른 원문도 '참고 원문'으로 함께 제공 (총량 제한)
    total = sum(len(t) for _, t in sources.values())
    for key, txt in art_texts.items():
        label = _article_label(key)
        if label not in src_index and total < 40000:
            _src_id(label, txt); total += min(len(txt), 6000)
    for d in details:
        head = d.split("\n", 1)[0][:60]
        if head not in src_index and total < 40000:
            _src_id(head, d); total += min(len(d), 6000)
    return claims, sources

def _semantic_verify(api_key: str, claims: list, sources: dict) -> dict:
    """검증 모델 호출. 반환: {claim_id: (verdict, reason)}"""
    src_block = "\n\n".join(f"[{sid}] {label}\n{text}" for sid, (label, text) in sources.items())
    claim_block = "\n".join(f"{n + 1}. (근거: {', '.join(c['sources'])}) {c['text']}" for n, c in enumerate(claims))
    prompt = (
        "당신은 세무 답변의 근거를 검증하는 감수자입니다. 아래 [원문] 전체를 기준으로 각 [주장]의 '핵심 법적 명제'가 뒷받침되는지 판정하세요.\n"
        "- supported: 핵심 명제(요건·효과·수치)가 원문(지정 근거 또는 다른 원문)에 있음. 같은 뜻의 요약·의역, 원문에서 직접 도출되는 당연한 결론, "
        "'실무상 유의' 같은 부수적 권고 문구는 문제 삼지 말 것\n"
        "- partial: 핵심 명제는 맞지만, 주장에 적힌 **구체적 수치·기간·비율·요건**이 원문에 없거나 원문과 다름\n"
        "- unsupported: 핵심 명제 자체가 원문 어디에도 없거나 원문과 모순됨 (일반 지식으로 맞더라도 원문에 없으면 unsupported)\n"
        "원문 밖의 지식으로 판단하지 마세요. 사소한 표현 차이로 partial/unsupported를 주지 마세요. "
        "reason은 한국어 30자 이내로, 'S1' 같은 번호 대신 법령·판례 이름으로 쓰세요.\n"
        '출력은 JSON 배열만: [{"id": 1, "verdict": "supported", "reason": "..."}]\n\n'
        f"[원문]\n{src_block}\n\n[주장]\n{claim_block}"
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
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip()).strip()
    data = json.loads(raw)
    result = {}
    for item in data if isinstance(data, list) else []:
        try:
            cid = int(item.get("id"))
            verdict = str(item.get("verdict", "")).strip().lower()
            if verdict in ("supported", "partial", "unsupported"):
                reason = str(item.get("reason", ""))[:60]
                for sid, (label, _) in sources.items():          # 'S2에 없음' → '법인세법시행령 제44조에 없음'
                    reason = re.sub(rf"\b{sid}\b", label[:30], reason)
                result[cid] = (verdict, reason)
        except Exception:
            continue
    return result

_TRUNC_MARK = ("[※ 원문", "앞부분만 표시", "앞 8개만 표시")

def _apply_semantic_results(answer: str, claims: list, verdicts: dict, sources: dict = None) -> tuple[str, dict]:
    lines = answer.split("\n")
    counts = {"supported": 0, "partial": 0, "unsupported": 0, "unknown": 0}
    to_delete = []
    for n, c in enumerate(claims):
        verdict, reason = verdicts.get(n + 1, ("unknown", ""))
        # 근거 원문이 길어 잘린 채로 조회됐다면, '원문에 없음'이 잘린 부분 때문일 수 있으므로 삭제 대신 확인 필요로 표시
        if verdict == "unsupported" and sources:
            src_texts = [sources[sid][1] for sid in c["sources"] if sid in sources]
            if any(m in t for t in src_texts for m in _TRUNC_MARK) or any(len(t) >= 5900 for t in src_texts):
                verdict, reason = "partial", "원문이 길어 일부만 대조됨 – 직접 확인 필요"
        counts[verdict] = counts.get(verdict, 0) + 1
        if verdict == "partial":
            print(f"[시스템] ⚠️ 원문 확인 필요: {reason} | {c['text'][:60]}")
            if _show_diag():
                lines[c["line"]] = lines[c["line"]].rstrip() + f" ⚠️*(원문 확인 필요: {reason})*"
            else:
                lines[c["line"]] = lines[c["line"]].rstrip() + " ⚠️*(원문 확인 필요)*"
        elif verdict == "unsupported":
            to_delete.append((c["line"], [f"의미 검증 불일치 – {reason}"]))
    text = "\n".join(lines)
    if to_delete:
        text = _redact_lines(text, to_delete)
    return text, counts


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

    # 4) 조문번호로 특정 조문 1개를 조회한 경우 8,000자, 그 외(키워드 조회 등)는 3,500자까지 허용
    #    (시행령 제78조의3처럼 항이 많은 조문이 중간에 잘리지 않도록)
    limit = 12000 if (qf.startswith("제") and "조" in qf) else 3500
    if len(cleaned) > limit:
        return (cleaned[:limit]
                + f"\n\n[※ 원문 {len(cleaned):,}자 중 {limit:,}자까지만 표시됨. 필요한 항이 없으면 "
                  "query_filter에 '제78조의3 제8항'처럼 항 번호까지 넣어 다시 조회할 것]")
    return cleaned


# 1. 모델 설정 (2026-09-18부터 2.5 계열은 신규 프로젝트에서 404 → 3.x로 전환)
#    Secrets/.env에 같은 이름의 키를 넣으면 코드 수정 없이 모델명을 바꿀 수 있습니다.
def _model_id(env_key: str, default: str) -> str:
    return _get_secret_or_env(env_key) or default

FLASH_MODEL_ID     = _model_id("GEMINI_FLASH_MODEL", "gemini-3.8-flash")         # 기본 답변 모델
FLASH_BACKUP_ID    = _model_id("GEMINI_FLASH_BACKUP_MODEL", "gemini-3.6-flash")  # 3.8 과부하(503 등) 시 예비
VERIFIER_MODEL_ID  = _model_id("GEMINI_VERIFIER_MODEL", "gemini-3.8-flash")      # 의미 검증 모델
SEMANTIC_VERIFY_ON = _get_secret_or_env("SEMANTIC_VERIFY").lower() not in ("off", "false", "0")
# Pro급 (첫 번째가 실패하면 두 번째로)
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

    # 자동 전환은 비용이 크므로 기본 OFF (Secrets에 AUTO_PRO = "on" 을 넣으면 켜짐)
    if _get_secret_or_env("AUTO_PRO").lower() not in ("on", "true", "1"):
        return "FLASH", "⚡ **[Flash 빠른 검토 모드]** 실무 표준 검토"

    if has_file and full_input_len >= 15000:
        return "PRO", f"🧠 **[Pro 심층 모드 자동 전환]** 대용량 문서({full_input_len:,}자) 정밀 분석"

    matched_deep = [kw for kw in DEEP_KEYWORDS if kw in user_query]
    if len(matched_deep) >= 2:
        return "PRO", f"🧠 **[Pro 심층 모드 자동 전환]** 복합 고난도 쟁점 감지 ({', '.join(matched_deep[:3])})"

    matched_calc = [kw for kw in CALC_KEYWORDS if kw in user_query]
    if len(user_query.strip()) >= 500 and len(matched_calc) >= 1:
        return "PRO", "🧠 **[Pro 심층 모드 자동 전환]** 초장문 복합 시뮬레이션 감지"

    return "FLASH", "⚡ **[Flash 빠른 검토 모드]** 실무 표준 검토"

# 2. Gemini 도구 정의
def search_law_for_gemini(keyword: str, target: str = "law") -> str:
    """
    국가법령정보센터에서 법령, 판례, 행정규칙, 법령해석례, 조세심판원 재결례, 지방세 자치법규(조례) 목록과 일련번호(ID)를 검색합니다.
    - target: 'law'(법령), 'prec'(판례), 'decc'(조세심판원 결정례 – 내부적으로 ttSpecialDecc 사용), 'admrul'(훈령·예규·고시), 'expc'(법령해석례), 'ordin'(지자체 조례)
    - target='law'일 때 keyword에는 '법령명만' 넣을 것 (예: '소득세법', '소득세법 시행령', '조세특례제한법').
      '업무용승용차' 같은 주제어는 keyword가 아니라 get_law_details_for_gemini의 query_filter(조문번호)로 찾을 것.
    - target='prec'/'decc'/'expc'는 핵심 주제어(예: '업무무관 가지급금')나 사건번호(예: '2005두9415')로 검색할 것.
      제목에 없으면 본문 검색으로 자동 재시도됨.
    """
    if _over_limit("search", target):
        print(f"\n[시스템] ⛔ 검색 한도 도달 → 차단: '{keyword}' (대상: {target})")
        return (f"[검색 한도 도달] 이번 질문에서 '{target}' 검색은 더 할 수 없습니다. "
                "지금까지 조회한 원문만으로 답변을 작성하고, 찾지 못한 근거는 '관련 원문을 확인하지 못했다'고 쓰세요.")
    print(f"\n[시스템] 💡 목록 검색 도구 가동: '{keyword}' (대상: {target})")
    results = law_api.search_law_data(keyword, target)
    used_keyword = keyword

    # 판례·심판례·해석례·행정규칙은 제목 검색에 안 걸리면 본문 검색으로 자동 재시도
    if not results and target in ("prec", "decc", "expc", "admrul"):
        print(f"[시스템]    ↳ 제목 검색 결과 없음 → 본문 검색으로 재시도")
        results = law_api.search_law_data(keyword, target, search_mode=2)
        if results:
            used_keyword = keyword + " (본문검색)"

    # 결과가 없으면 뒤쪽 단어를 하나씩 빼며 자동 재검색 (예: '소득세법 업무용승용차' → '소득세법')
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

    summary = ""
    if used_keyword != keyword:
        summary += f"※ '{keyword}' 검색 결과가 없어 '{used_keyword}'(으)로 재검색한 결과입니다.\n"
    summary += f"총 {len(results)}건 검색됨 (상위 5건 요약):\n"
    for i, item in enumerate(results[:5]):
        if target == "law":
            summary += f"{i+1}. [법령] {item.get('법령명한글')} | 공포번호: {item.get('공포번호')} | 시행일: {item.get('시행일자')} | ID: {item.get('법령일련번호')}\n"
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
    """
    검색된 일련번호(ID)로 원문을 조회합니다. 법령('law') 조회 시 반드시 query_filter에 조문번호(예: '제29조의8', '제26조')나 핵심 단어를 넣어 호출하세요.
    """
    # 판례·심판례·해석례·예규는 query_filter와 상관없이 같은 원문이 오므로, 같은 문서를 다시 조회하지 않음
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
    # 법리 왜곡 없이 개정 연혁 태그와 타 조문 군더더기만 제거하여 토큰 50% 절감
    result = compress_legal_text(raw_text, query_filter)
    # 🔧 진단용: 모델에게 실제로 전달되는 분량과 앞부분을 터미널에 표시
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

[필수 도구 호출 원칙]
- **[핵심 조문 조회 원칙]**: 세법 질문은 **법률과 시행령의 해당 조문을 모두** 원문으로 조회한 뒤 답변할 것. 도구 호출은 필요한 만큼(보통 4~8회) 하되, **이미 결과를 받은 검색을 같은 검색어로 반복하지 말 것.**
- 법령 검색(search_law_for_gemini, target='law')의 keyword에는 **법령명만** 넣을 것 (예: '소득세법', '소득세법 시행령'). 주제어는 넣지 말 것.
- 조회한 원문에서 직접 확인하지 못한 금액·비율·연도는 단정하지 말고 **"(원문 미확인)"**이라고 표시할 것.
- **[근거 표시 의무]** 판례·심판례·해석례·예규·법령 조문을 근거로 쓰는 문장 끝에는 반드시 아래 형식의 근거 표시를 붙일 것. 시스템이 근거 표시를 도구 조회 기록과 자동 대조하며, **조회하지 않은 근거나 근거 표시 없는 판례·예규 서술은 자동 삭제됨.**
  * 판례: [판례:2005두9415] / 조세심판: [심판례:조심2020서1234] / 법령해석례: [해석례:안건번호] / 예규·고시: [예규:문서명 또는 번호]
  * 법령 조문: [조문:법인세법 시행령 제89조] (반드시 정식 법령명 포함. '동법', '같은 법' 사용 금지)
- **판례·심판례·해석례 인용 규칙**: 판결요지·결정요지를 서술하는 사건은 반드시 get_law_details_for_gemini(target='prec' 등)로 **원문을 조회한 사건만** 쓸 것. 목록 검색에서만 본 사건은 사건번호·선고일만 적고 "(요지 미조회)"로 표시할 것. **도구로 조회하지 않은 사건번호를 기억으로 적지 말 것.**
- **법령 조문 인용 규칙**: 답변에 법령명과 함께 적는 조문(예: 「법인세법」 제52조)은 반드시 get_law_details_for_gemini로 **그 조문을 조회한 것만** 쓸 것. 조회하지 않은 조문이 필요하면 먼저 조회할 것.
- **답변에 시스템·도구·검증 절차·삭제 여부에 대한 언급을 절대 쓰지 말 것** (예: "시스템상 미조회 항목은 배제" 같은 문장 금지). 근거가 부족하면 "관련 원문을 확인하지 못했다"고만 쓸 것.
- **법령명은 반드시 정식 명칭**으로 쓸 것 (예: 「상속세 및 증여세법」, 「조세특례제한법 시행령」).
- 판례 검색 순서: 주제어로 목록 검색 → 결과 중 관련성 높은 1~2건의 ID로 원문 조회 → 그 내용만 인용. **판례 목록 검색은 질문당 최대 3회, 판례 원문 조회는 최대 3건**까지만 할 것.
- **근거 표시는 그 문장의 내용이 실제로 해당 원문에 있을 때만** 붙일 것. 한 판례에 없는 내용을 그 판례 근거 표시로 묶지 말 것.
- **따옴표(“ ”) 인용은 조회한 원문을 글자 그대로 옮길 때만** 사용하고, 요약·의역할 때는 따옴표를 쓰지 말 것. (시스템이 인용문을 원문과 글자 단위로 대조함)
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
- **3차(예규·심판례·리스크 검증)**: 조회한 예규·심판례가 있으면 근거 표시와 함께 요지, 없으면 "확인된 예규·심판례 없음"이라고 쓰고, 가산세·사후관리 등 실무 주의점 1줄 요약

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
                maximum_remote_calls=12
            )
        )
    )
    trace_token = _TOOL_TRACE.set(_new_trace())
    try:
        response = chat.send_message(user_input)
        final_text = extract_safe_text(response)

        if not final_text:
            follow_up = chat.send_message("지금까지 조회한 법령 조문과 계산 결과를 바탕으로 추가 도구 호출 없이 즉시 [A. 사전 3줄 크로스체크]와 [B. 최종 답변]을 작성해 주세요.")
            final_text = extract_safe_text(follow_up)
        trace = _TOOL_TRACE.get()
    finally:
        _TOOL_TRACE.reset(trace_token)

    if not final_text:
        raise ValueError("빈 응답이 반환되었습니다.")
    final_text = re.sub(r"\s*<br\s*/?>\s*", " / ", final_text)   # 표 안 <br>이 글자로 보이는 문제 정리

    # ---------------------------------------------------------
    # 🔒 근거 강제 검증 (도구 기록이 수집된 경우에만)
    #   대상: 사건번호 / 법령명+조문 / 집행기준 번호 / [근거 표시] / 출처 없는 판례·예규 서술
    #   1단계: 위반이 있으면 모델에게 "원문을 조회하거나 삭제하라"고 1회 재작성 요청
    #   2단계: 그래도 남으면 해당 줄(과 하위 항목)을 코드에서 직접 삭제
    # ---------------------------------------------------------
    citation_note = ""
    if trace and (trace["list"] or trace["detail"]):
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
                  "조회하지 않은 근거는 다시 쓰지 말고, 양식([A]→[B])을 유지해 전체 답변을 다시 작성하세요. "
                  "다시 쓴 답변에는 이 검증 요청이나 삭제 사실, 시스템에 대한 언급을 절대 넣지 마세요."
            )
            trace_token2 = _TOOL_TRACE.set(trace)   # 재작성 중 조회한 원문도 같은 기록에 누적
            try:
                retry_resp = chat.send_message(fix_msg)
                retry_text = extract_safe_text(retry_resp)
            except Exception as e:
                retry_text = ""
                print(f"[시스템]    ↳ 재작성 요청 실패: {e}")
            finally:
                _TOOL_TRACE.reset(trace_token2)

            if retry_text:
                final_text = retry_text
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

        # 🧪 의미 검증: 근거 표시가 붙은 문장이 실제로 원문 내용과 맞는지 별도 모델로 판정
        if SEMANTIC_VERIFY_ON:
            claims, sources = _extract_claims(final_text, trace)
            if claims:
                print(f"[시스템] 🧪 의미 검증 가동: 주장 {len(claims)}건 / 원문 {len(sources)}건")
                try:
                    verdicts = _semantic_verify(api_key, claims, sources)
                    final_text, cnt = _apply_semantic_results(final_text, claims, verdicts, sources)
                    citation_note += (f"\n> 🧪 의미 검증 {len(claims)}건: 일치 {cnt['supported']} · "
                                      f"원문 확인 필요 {cnt['partial']}(⚠️ 표시) · 불일치 {cnt['unsupported']}(삭제)"
                                      + (f" · 판정 누락 {cnt['unknown']}" if cnt.get("unknown") else ""))
                except Exception as e:
                    print(f"[시스템]    ↳ 의미 검증 실패: {e}")
                    citation_note += "\n> 🧪 의미 검증을 수행하지 못했습니다(검증 모델 오류). 근거 표시 문장은 직접 확인하세요."

    # 🔧 진단용: 실제 호출된 도구 목록을 답변 하단에 표시
    #    (chat 모드에서는 response가 아니라 chat 기록에 도구 호출이 남으므로 둘 다 확인)
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

    # 마지막 응답에 아직 function_call이 남아 있으면 호출 한도에 걸려 중간에 끊긴 것
    limit_hit = False
    try:
        for p in (response.candidates[0].content.parts or []):
            if getattr(p, "function_call", None):
                limit_hit = True
    except Exception:
        pass

    # 진단 정보(도구 호출·검증 결과)는 기본적으로 화면에 숨기고 터미널/로그에만 남김
    #   Secrets 또는 .env에 SHOW_DIAGNOSTICS = "on" 을 넣으면 답변 하단에 다시 표시됨
    if calls:
        diag = "\n\n---\n> 🛠 도구 호출 " + str(len(calls)) + "회: " + " → ".join(calls)
    else:
        diag = "\n\n---\n> 🛠 도구 호출 없음 (모델 자체 지식으로 답변)"
    if limit_hit:
        diag += "\n> ⚠️ 도구 호출 한도에 도달해 조회가 중간에 끊겼습니다. 결론을 원문과 대조해 확인하세요."
    diag += citation_note

    if _show_diag():
        final_text += diag
    else:
        print("[시스템] 📋 진단 정보(화면 미표시):" + diag.replace("\n> ", "\n   ").replace("\n\n---", ""))
    final_text = re.sub(r"\s*<br\s*/?>\s*", " / ", final_text)

    return final_text

# 4. 실행 순서(유료키 전용): 3.8-flash → 3.6-flash (PRO 모드는 Pro 모델 → Flash 백업)
#    경량(lite) 모델은 세무 답변 정확도 문제로 사용하지 않음. 500/503/504는 2초 후 1회 재시도
def run_agent(user_input: str, raw_query: str = "", has_file: bool = False) -> str:
    live_pool = get_live_gemini_key_pool()
    if not live_pool:
        return "❌ 설정된 Gemini 유료 API 키가 없습니다. .env 또는 Streamlit Secrets에 GEMINI_PAID_KEY를 넣어 주세요."

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

    execution_plan = []
    for lbl, k in live_pool:
        if tier_mode == "PRO":
            for m in PAID_PRO_MODEL_IDS:
                execution_plan.append((lbl, k, m, f"{mode_badge} *(🔑 {lbl} · {m})*"))
            for m in (FLASH_MODEL_ID, FLASH_BACKUP_ID):
                execution_plan.append((lbl, k, m, f"⚡ **[Pro 실패 → Flash 백업]** *(🔑 {lbl} · {m})*"))
        else:
            for m in (FLASH_MODEL_ID, FLASH_BACKUP_ID):
                execution_plan.append((lbl, k, m, f"{mode_badge} *(🔑 {lbl} · {m})*"))

    last_error = None
    diag_notes = []
    dead_models = set()  # 404 난 모델은 다른 키로 재시도하지 않음

    for key_label, current_key, target_model, final_badge in execution_plan:
        if target_model in dead_models:
            continue
        for attempt in range(2):  # 500/503/504(일시 과부하·응답 지연)는 2초 후 1회 재시도
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
