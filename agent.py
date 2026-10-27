import os
import re
import ast
import gzip
import math
import time
import contextvars
import json
import threading
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
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

def _safe_float(raw_val, default_val: float) -> float:
    """Secrets에 '2,000'이나 '1,400원'처럼 쉼표·단위가 포함되어 있어도 오류 없이 숫자로 변환합니다."""
    if raw_val is None or raw_val == "":
        return float(default_val)
    try:
        cleaned = re.sub(r"[^0-9.\-]", "", str(raw_val))
        return float(cleaned) if cleaned else float(default_val)
    except Exception:
        return float(default_val)

def get_live_gemini_key_pool() -> list[tuple[str, str]]:
    """
    유료키만 사용합니다.
    - GEMINI_PAID_KEY(기본) → GEMINI_API_KEY(예비, 다른 값일 때만) 순서로 사용합니다.
    """
    pool = []
    seen = set()
    for env_name, lbl in [("GEMINI_PAID_KEY", "💳 유료키"), ("GEMINI_API_KEY", "💳 유료키(예비)"), ("GOOGLE_API_KEY", "💳 유료키(GOOGLE)")]:
        k = _get_secret_or_env(env_name)
        if k and k not in seen:
            pool.append((lbl if pool or env_name == "GEMINI_PAID_KEY" else "💳 유료키", k))
            seen.add(k)
    return pool

import law_api

def get_law_oc_auto() -> str:
    """st.secrets, 환경변수, config.py, law_api 모듈 속성 및 파일 내부에서 법제처 OC 키(LAW_OPEN_API_KEY 최우선)를 자동 추출합니다."""
    for k in ["LAW_OPEN_API_KEY", "LAW_API_OC", "OC", "LAW_OC", "LAW_API_KEY", "MOLEG_OC", "DRF_OC"]:
        val = _get_secret_or_env(k)
        if val:
            return val
    for attr in ["LAW_OPEN_API_KEY", "OC", "LAW_API_OC", "LAW_OC", "LAW_API_KEY", "API_KEY", "USER_OC", "oc"]:
        val = getattr(law_api, attr, None)
        if isinstance(val, str) and val.strip():
            return val.strip()
    try:
        import config
        for attr in ["LAW_OPEN_API_KEY", "OC", "LAW_API_OC", "LAW_OC", "LAW_API_KEY"]:
            val = getattr(config, attr, None)
            if isinstance(val, str) and val.strip():
                return val.strip()
    except Exception:
        pass
    for fname in ["law_api.py", "config.py"]:
        if os.path.exists(fname):
            try:
                with open(fname, "r", encoding="utf-8") as f:
                    src = f.read()
                m = re.search(r'(?:LAW_OPEN_API_KEY|OC|LAW_API_OC|LAW_OC|LAW_API_KEY)\s*=\s*["\']([^"\']+)["\']', src)
                if m and m.group(1).strip():
                    return m.group(1).strip()
                m2 = re.search(r'OC=([A-Za-z0-9_.\-]+)', src)
                if m2 and m2.group(1).strip() and not m2.group(1).startswith("{"):
                    return m2.group(1).strip()
            except Exception:
                pass
    return ""

# ---------------------------------------------------------
# ⚡ [속도 개선 ① & ③] 당일 메모리 캐싱 (12시간 TTL) + 18대 주요 세법 ID 프리워밍 + Gzip 고속 HTTP 수신기
# ---------------------------------------------------------
_LAW_MEMORY_CACHE = {}
_LAW_CACHE_LOCK = threading.Lock()
_LAW_CACHE_TTL_SEC = 43200  # 12시간

def _cache_get(key: tuple):
    now = time.time()
    with _LAW_CACHE_LOCK:
        entry = _LAW_MEMORY_CACHE.get(key)
        if entry and (now - entry[0]) < _LAW_CACHE_TTL_SEC:
            return entry[1]
    return None

def _cache_set(key: tuple, val) -> None:
    if val is None:
        return
    with _LAW_CACHE_LOCK:
        if len(_LAW_MEMORY_CACHE) > 800:
            _LAW_MEMORY_CACHE.clear()
        _LAW_MEMORY_CACHE[key] = (time.time(), val)

def register_prewarmed_law_ids(law_prom_map: dict) -> None:
    """
    [속도 개선 ①] app.py 구동 시 병렬 조회된 18개 주요 세법·시행령의 최신 법령일련번호(mst_id/law_id)를
    에이전트 메모리 캐시에 즉시 등록하여, AI가 search_law_for_gemini 없이 법령명만으로
    1턴 만에 get_law_details_for_gemini를 직행 호출할 수 있도록 지원합니다.
    """
    if not isinstance(law_prom_map, dict):
        return
    today_ymd = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
    for clean_name, info in law_prom_map.items():
        if not isinstance(info, dict):
            continue
        lid = str(info.get("mst_id") or info.get("law_id") or "").strip()
        if clean_name and lid:
            _cache_set(("law_name_to_id", today_ymd, clean_name.replace(" ", "")), lid)

def _http_get_bytes_fast(url: str, timeout: int = 15) -> bytes:
    """
    [속도 개선 ③] Gzip 압축 수신(Accept-Encoding: gzip) 및 Keep-Alive 헤더를 적용해
    대용량 법제처 XML(조특법·법인세법 등 수 MB) 다운로드 시간을 원문 손실 없이 2~3배 단축합니다.
    """
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw_bytes = resp.read()
        enc = (resp.info().get("Content-Encoding") or "").lower()
        if "gzip" in enc or raw_bytes[:2] == b"\x1f\x8b":
            try:
                return gzip.decompress(raw_bytes)
            except Exception:
                return raw_bytes
        return raw_bytes

# ---------------------------------------------------------
# 📡 [속도 개선 ⑥] 실시간 백그라운드 진행 단계 브로드캐스트 콜백
# ---------------------------------------------------------
_LIVE_STATUS_CB = contextvars.ContextVar("live_status_cb", default=None)

def set_live_status_callback(cb):
    return _LIVE_STATUS_CB.set(cb)

def _emit_live_status(step_msg: str) -> None:
    cb = _LIVE_STATUS_CB.get()
    if callable(cb):
        try:
            cb(step_msg)
        except Exception:
            pass

# ---------------------------------------------------------
# 💰 대화방 1개당 2,000원(ROOM_LIMIT_KRW) 정밀 요금 계량기 및 Pro 차단기
#    (아르곤 프로모션 단가 ~2026.11.30 / 12.01 이후 정상가 및 20만 토큰 장문 구간 자동 반영)
# ---------------------------------------------------------
USAGE_STORAGE_DIR = ".workspace_storage"
os.makedirs(USAGE_STORAGE_DIR, exist_ok=True)
USAGE_FILE_PATH = os.path.join(USAGE_STORAGE_DIR, "api_usage_stats.json")
_USAGE_LOCK = threading.Lock()

ROOM_LIMIT_KRW = _safe_float(_get_secret_or_env("ROOM_LIMIT_KRW"), 2000.0)
MONTHLY_PRO_LIMIT_KRW = ROOM_LIMIT_KRW  # 하위 호환용 별칭
USD_TO_KRW_RATE = _safe_float(_get_secret_or_env("USD_TO_KRW_RATE"), 1400.0)

_MODEL_PRICING_USD_PER_1M = {
    "PRO":   {"in": 2.00, "out": 12.00},   # gemini-3.1-pro-preview 기본 기준
    "FLASH": {"in": 0.75, "out": 3.75},    # gemini-3.8-flash / 3.6-flash 기본 기준
}

def _get_dynamic_model_price_usd_per_1m(model_id: str, in_tokens: int = 0) -> dict:
    """
    [정밀 과금 계량] 공식 Gemini Developer API 요금표 기준:
    - gemini-4-argon: 2026-11-30까지 $2.00 / $10.00 (장문 할증 없음), 2026-12-01부터 $4.00 / $20.00
    - gemini-3.1-pro-preview / gemini-2.5-pro: 20만 토큰 이하 $2.00 / $12.00, 20만 토큰 초과 $4.00 / $18.00
    - gemini-3.5-flash-lite: $0.30 / $2.50
    - gemini-3.8-flash / gemini-3.6-flash: 2026-12-31까지 $0.75 / $3.75, 2027-01-01부터 $1.50 / $7.50
    """
    m_low = (model_id or "").lower()
    today_ymd = int(datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d"))

    if "argon" in m_low:
        if today_ymd <= 20261130:
            return {"in": 2.00, "out": 10.00}
        return {"in": 4.00, "out": 20.00}

    if "pro" in m_low:
        if in_tokens > 200_000:
            return {"in": 4.00, "out": 18.00}
        return {"in": 2.00, "out": 12.00}

    if "flash-lite" in m_low:
        return {"in": 0.30, "out": 2.50}

    if today_ymd >= 20270101 and ("3.8-flash" in m_low or "3.6-flash" in m_low):
        return {"in": 1.50, "out": 7.50}
    return {"in": 0.75, "out": 3.75}

_ACTIVE_ROOM_KEY = contextvars.ContextVar("active_room_key", default="default_public::대화방 1")

def set_active_room_key(room_key: str):
    return _ACTIVE_ROOM_KEY.set(room_key or "default_public::대화방 1")

def _default_bucket() -> dict:
    return {
        "total_krw": 0.0,
        "total_usd": 0.0,
        "pro_calls": 0,
        "flash_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "limit_krw": ROOM_LIMIT_KRW,
        "updated_at": "-"
    }

def _load_all_usage_store() -> dict:
    if os.path.exists(USAGE_FILE_PATH):
        try:
            with open(USAGE_FILE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "rooms" in data:
                return data
        except Exception:
            pass
    return {"rooms": {}}

def _save_all_usage_store(store: dict) -> None:
    try:
        with open(USAGE_FILE_PATH, "w", encoding="utf-8") as f:
            json.dump(store, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ 사용량 기록 저장 오류: {e}")

def get_room_usage(room_key: str = "") -> dict:
    """특정 대화방(room_key)의 누적 토큰 및 원화/달러 환산 요금 데이터를 반환합니다."""
    r_key = room_key or _ACTIVE_ROOM_KEY.get()
    with _USAGE_LOCK:
        store = _load_all_usage_store()
        bucket = store.get("rooms", {}).get(r_key, {})
        res = _default_bucket()
        for k in res:
            if k in bucket:
                res[k] = bucket[k]
        res["limit_krw"] = ROOM_LIMIT_KRW
        return res

def set_room_usage_from_backup(room_key: str, usage_data: dict) -> None:
    """대화방 백업 복원 또는 디스크 로드 시 해당 방의 요금 데이터를 동기화합니다."""
    if not room_key or not isinstance(usage_data, dict):
        return
    with _USAGE_LOCK:
        store = _load_all_usage_store()
        b = _default_bucket()
        for k in b:
            if k in usage_data:
                b[k] = usage_data[k]
        b["limit_krw"] = ROOM_LIMIT_KRW
        store.setdefault("rooms", {})[room_key] = b
        _save_all_usage_store(store)

def reset_room_usage(room_key: str) -> None:
    """[현재 방 비우기] 시 해당 대화방의 요금·토큰 계량기를 즉시 0원으로 초기화합니다."""
    if not room_key:
        return
    with _USAGE_LOCK:
        store = _load_all_usage_store()
        store.setdefault("rooms", {})[room_key] = _default_bucket()
        _save_all_usage_store(store)

def get_monthly_usage(room_key: str = "") -> dict:
    return get_room_usage(room_key)

def _record_token_usage(model_id: str, in_tokens: int, out_tokens: int, count_call: bool = True, room_key: str = "") -> None:
    if in_tokens <= 0 and out_tokens <= 0:
        return
    r_key = room_key or _ACTIVE_ROOM_KEY.get()
    is_pro_model = ("pro" in model_id.lower()) or ("argon" in model_id.lower())
    price_info = _get_dynamic_model_price_usd_per_1m(model_id, in_tokens=in_tokens)

    cost_usd = (in_tokens / 1_000_000.0) * price_info["in"] + (out_tokens / 1_000_000.0) * price_info["out"]
    cost_krw = cost_usd * USD_TO_KRW_RATE

    with _USAGE_LOCK:
        store = _load_all_usage_store()
        rooms = store.setdefault("rooms", {})
        stats = rooms.get(r_key, _default_bucket())

        stats["total_usd"] = round(float(stats.get("total_usd", 0.0)) + cost_usd, 6)
        stats["total_krw"] = round(float(stats.get("total_krw", 0.0)) + cost_krw, 2)
        stats["input_tokens"] = int(stats.get("input_tokens", 0)) + int(in_tokens)
        stats["output_tokens"] = int(stats.get("output_tokens", 0)) + int(out_tokens)
        if count_call:
            if is_pro_model:
                stats["pro_calls"] = int(stats.get("pro_calls", 0)) + 1
            else:
                stats["flash_calls"] = int(stats.get("flash_calls", 0)) + 1
        stats["limit_krw"] = ROOM_LIMIT_KRW
        stats["updated_at"] = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%m/%d %H:%M:%S")
        rooms[r_key] = stats
        _save_all_usage_store(store)

def _extract_and_log_response_usage(
    response,
    model_id: str,
    count_call: bool = True,
    est_in_chars: int = 0,
    est_out_chars: int = 0,
    tool_calls_count: int = 0,
    tool_result_chars: int = 0
) -> None:
    in_tok, out_tok = 0, 0
    try:
        um = getattr(response, "usage_metadata", None)
        if um:
            in_tok = int(getattr(um, "prompt_token_count", 0) or 0)
            out_tok = (
                int(getattr(um, "candidates_token_count", 0) or 0)
                + int(getattr(um, "thoughts_token_count", 0) or 0)
            )
    except Exception:
        pass
    if in_tok == 0 and est_in_chars > 0:
        in_tok = int(est_in_chars * 0.7)
    if out_tok == 0 and est_out_chars > 0:
        out_tok = int(est_out_chars * 0.7)

    if tool_calls_count > 0:
        base_prompt_tok = int(est_in_chars * 0.7)
        avg_tool_tok = int((tool_result_chars * 0.7) / max(1, tool_calls_count))
        intermediate_in_tok = sum(base_prompt_tok + (avg_tool_tok * step) for step in range(tool_calls_count))
        intermediate_out_tok = tool_calls_count * 250
        in_tok += intermediate_in_tok
        out_tok += intermediate_out_tok

    _record_token_usage(model_id, in_tok, out_tok, count_call=count_call)

def is_pro_budget_exceeded(room_key: str = "") -> tuple[bool, float, float]:
    stats = get_room_usage(room_key)
    cur_krw = float(stats.get("total_krw", 0.0))
    limit_krw = float(stats.get("limit_krw", ROOM_LIMIT_KRW))
    return (cur_krw >= limit_krw), cur_krw, limit_krw


# ---------------------------------------------------------
# 🔎 근거 추적·검증 및 VERIFY_MODE ('strict' 기본 설정) 제어
# ---------------------------------------------------------
_TOOL_TRACE = contextvars.ContextVar("tool_trace", default=None)

def _verify_mode() -> str:
    """기본값을 'strict'(미조회 근거·불일치 문장 즉시 삭제, 일부 불일치만 ⚠️ 표시)로 작동합니다."""
    m = (_get_secret_or_env("VERIFY_MODE") or "strict").lower().strip()
    return m if m in ("balanced", "strict", "loose") else "strict"

def _new_trace(unleash: bool = False) -> dict:
    return {
        "list": [],
        "detail": [],
        "articles": set(),
        "mentioned_articles": set(),
        "article_texts": {},
        "counts": {},
        "id_map": {},
        "meta_map": {},
        "unleash": unleash
    }

def _is_unleashed() -> bool:
    trace = _TOOL_TRACE.get()
    return bool(trace and trace.get("unleash"))

_SEARCH_LIMIT = {"law": 7, "prec": 3, "decc": 3, "detc": 3, "expc": 2, "admrul": 2, "ordin": 2, "licbyl": 2}
_DETAIL_LIMIT = {"law": 12, "eflaw": 6, "prec": 3, "decc": 3, "detc": 3, "expc": 2, "admrul": 2, "ordin": 2, "licbyl": 2}

def _over_limit(kind: str, target: str) -> bool:
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
    trace = _TOOL_TRACE.get()
    if trace is not None:
        trace[kind].append(text or "")
    return text

def _record_law_articles(text: str) -> None:
    """
    [보강]
    1) 조문 제목 괄호가 없는 시행규칙이나 공백이 섞인 조문(`제10조 ` 등)도 누락 없이 조회 목록에 등록합니다.
    2) 조회한 조문 원문 본문 안에서 직접 인용·언급하고 있는 타 법령 조문(예: 조특법 제29조의8 본문 내 '중소기업기본법 제2조')을
       `mentioned_articles`에 함께 기록하여, AI가 조문 원문 문구를 그대로 설명할 때 억울한 미조회 판정(재작성 루프)이 발생하지 않도록 보호합니다.
    """
    trace = _TOOL_TRACE.get()
    if trace is None or not text:
        return
    m = re.search(r"📘 \[(.+?)\]", text)
    if not m:
        return
    raw_header = m.group(1).split("|")[0].strip()
    title = _norm(raw_header)
    starts = list(re.finditer(r"(?m)^\s*제\s*(\d+)\s*조(?:\s*의\s*(\d+))?(?:\s*\(|\s+)", text))
    for n, am in enumerate(starts):
        key = (title, int(am.group(1)), int(am.group(2) or 0))
        trace["articles"].add(key)
        end = starts[n + 1].start() if n + 1 < len(starts) else len(text)
        trace["article_texts"][key] = text[am.start():end].strip()

    mentioned = trace.setdefault("mentioned_articles", set())
    for m_ref in _find_article_refs(text, trace):
        mentioned.add(m_ref)

_CASE_NO_PATTERNS = [
    re.compile(r"(?<!\d)((?:19|20)?\d{2})\s?(재두|재다|가합|가단|구합|구단|헌바|헌마|헌가|두|누|다|도|나|후|허|므|구|부|노|고단|고합)\s?(\d{2,6})(?!\d)"),
    re.compile(r"(?:조심|국심)\s?((?:19|20)\d{2})\s?(서|중|부|광|전|구|인|경|지)\s?(\d{2,6})(?!\d)"),
]

_ARTICLE_NO = re.compile(r"제\s*(\d+)\s*조(?:\s*의\s*(\d+))?")
_COMMON_LAWS = [
    "상속세및증여세법", "조세특례제한법", "국세기본법", "국세징수법", "법인세법", "소득세법", "부가가치세법",
    "지방세법", "지방세기본법", "지방세특례제한법", "종합부동산세법", "개별소비세법", "교육세법", "농어촌특별세법",
    "인지세법", "증권거래세법", "국제조세조정에관한법률", "조세범처벌법", "중소기업기본법", "근로기준법", "근로자퇴직급여보장법",
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
    """
    1) '국세기본법', '중소기업기본법', '지방세기본법'이 '본법'으로 끝난다고 오판되어 검증에서 빠지지 않도록
       앞 글자가 한글이 아닐 때(독립 단어일 때)만 지시대명사('본법', '이법' 등)로 처리합니다.
    2) '국제조세조정에 관한 법률', '주식회사 등의 외부감사에 관한 법률' 등 '~에 관한 법률'(`법률`)로 끝나는 법령도
       정확히 인식하도록 정규식을 `법률?`로 확장합니다.
    """
    tail = _norm(prefix)[-45:]
    for suf in _REF_SKIP_SUFFIX:
        if tail == suf or (tail.endswith(suf) and not re.search(r"[가-힣]$", tail[:-len(suf)])):
            return None
    for alias, full in _LAW_ALIASES.items():
        for ext in ("시행규칙", "시행령", ""):
            if tail.endswith(alias + ext) or (tail.endswith(alias.replace("법", "령")) and ext == "시행령"):
                return full + ext
    for t in titles:
        if tail.endswith(t):
            return t
    m = re.search(r"([가-힣ㆍ·]{2,35}?법률?(?:시행령|시행규칙)?)$", tail)
    if not m:
        return None
    partial = m.group(1)
    if partial in _REF_SKIP_SUFFIX:
        return None
    for t in titles:
        if t.endswith(partial) and len(partial) >= 3:
            return t
    return partial

_EXEC_STD = re.compile(r"(?<![\d의])(\d{1,3}(?:의\d{1,2})?-\d{1,3}(?:의\d{1,2})?-\d{1,3})(?![\d])")

# [보강 ③] 마크다운 표 등에서 콜론(:)이 빠진 [조문 조세특례제한법 제29조의8] 또는 [조문조세특례제한법...] 형태까지 모두 인식
_TAG = re.compile(
    r"\[(판례|심판례|헌재|헌재결정례|해석례|예규|조문|부칙|별표)(?:\s*[:：]\s*|\s*)(?=[가-힣A-Za-z0-9「])([^\]]+)\]"
)

def _normalize_citation_tags(text: str) -> str:
    """
    [보강 ③] AI가 콜론(:)을 누락하여 작성한 `[조문 조세특례제한법 제29조의8]` 또는
    `[헌재 2021헌바123]` 형태를 표준 `[조문: ...]` / `[헌재: ...]` 형식으로 자동 정규화합니다.
    """
    if not text:
        return ""
    s = re.sub(
        r"\[(판례|심판례|헌재|헌재결정례|해석례|예규|조문|부칙|별표)(?:\s*[:：]\s*|\s+)(?=[가-힣A-Za-z0-9「])([^\]]+)\]",
        r"[\1: \2]",
        text
    )
    s = re.sub(
        r"\[(판례|심판례|헌재|헌재결정례|해석례|예규|조문|부칙|별표)(?=[가-힣A-Za-z0-9「])([^\]:：\n]+)\]",
        r"[\1: \2]",
        s
    )
    return s

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
    """
    조문 번호 앞의 법령명을 추출합니다.
    '~법', '~령', '~규칙'뿐 아니라 '국제조세조정에 관한 법률', '주식회사 등의 외부감사에 관한 법률' 등
    '~법률'(`률`)로 끝나는 모든 법률명을 누락 없이 인식합니다.
    """
    text = text or ""
    titles = _known_law_titles(trace)
    refs = []
    last_end = 0
    for m in _ARTICLE_NO.finditer(text):
        prefix = text[max(last_end, m.start() - 50):m.start()]
        last_end = m.end()
        stripped = re.sub(r"[\s「」『』\[\]:(),·ㆍ]+$", "", prefix)
        if not stripped or not re.search(r"(법률?|령|규칙)$", _norm(stripped)):
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
    """답변을 줄 단위로 검사해 [(줄번호, [위반 설명...], in_refs_section), ...]을 돌려줍니다."""
    detail_blob = _norm(" ".join(trace["detail"]))
    list_blob = _norm(" ".join(trace["list"]))
    fetched = trace["articles"]
    mentioned = trace.get("mentioned_articles", set())

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
            if ref in fetched or (not in_refs_section and ref in mentioned):
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
            violations.append((i, problems, in_refs_section))
    return violations

def _violation_labels(violations: list[tuple]) -> list[str]:
    labels = []
    for item in violations:
        probs = item[1]
        for p in probs:
            if p not in labels:
                labels.append(p)
    return labels

def _show_diag() -> bool:
    return _get_secret_or_env("SHOW_DIAGNOSTICS").lower() in ("on", "true", "1")

def _redact_lines(answer: str, violations: list[tuple]) -> str:
    """
    - 지어낸 사건번호('조회 기록 없음')는 어느 모드에서나 즉시 삭제합니다.
    - VERIFY_MODE == 'strict' (기본): 재작성 후에도 남은 모든 미검증 근거 줄을 조용히 삭제합니다.
    - VERIFY_MODE == 'balanced': 지어낸 사건번호 외의 미확인 근거에는 '⚠️(원문 확인 필요)'를 붙입니다.
    - VERIFY_MODE == 'loose': 지어낸 사건번호만 지우고 나머지는 그대로 둡니다.
    """
    vmode = _verify_mode()
    bad = {item[0]: item[1] for item in violations}
    lines = answer.split("\n")
    out = []
    skip_children_indent = None

    for i, line in enumerate(lines):
        s = line.strip()
        indent = len(line) - len(line.lstrip(" "))
        if skip_children_indent is not None:
            if s and indent > skip_children_indent:
                continue
            elif s:
                skip_children_indent = None

        if i in bad:
            probs = bad[i]
            has_fake_case = any("판례·심판례" in p and "조회 기록 없음" in p for p in probs)
            should_delete = has_fake_case or (vmode == "strict")

            if should_delete:
                if has_fake_case and len(s) < 65 and (s.endswith(":") or s.endswith(")") or s.endswith("]**")):
                    skip_children_indent = indent
                reasons = [r.split(":")[0] for r in probs]
                reason_txt = "; ".join(dict.fromkeys(reasons))[:120]
                if not _show_diag():
                    print(f"[시스템] 🚫 미검증 근거 삭제: {reason_txt} | {s[:60]}")
                    continue
                out.append(" " * indent + f"- 🚫 *(미검증 근거 삭제: {reason_txt})*")
                continue
            elif vmode == "balanced":
                if "⚠️" not in line:
                    out.append(line + " ⚠️*(원문 확인 필요)*")
                else:
                    out.append(line)
                continue
        out.append(line)
    return "\n".join(out)

def _is_kakao_request(user_query: str) -> bool:
    q = (user_query or "").strip()
    return any(k in q for k in ("카톡", "카카오톡", "문자 초안", "문자 안내", "문자로 보낼"))

def _enforce_pure_kakao_text(text: str) -> str:
    """
    [카톡 안내문 전용 100% 순수 텍스트 & 조문번호 완전 제거 후처리기]
    AI가 습관적으로 별표(**), 마크다운 표(| --- |), 샵(###), 조문번호(제29조의8 등)를 넣더라도
    카톡 붙여넣기 시 기호나 법조문이 절대 노출되지 않도록 순수 텍스트로 자동 정제합니다.
    """
    if not text:
        return ""
    s = text
    # 1) 대괄호 출처 태그 및 마크다운 링크 제거
    s = re.sub(r"\[(?:\[)?(?:판례|심판례|해석례|예규|조문)[^\]]*\](?:\([^)]*\))?", "", s)
    s = re.sub(r"\[([^\]]+)\]\(https?://[^)]+\)", r"\1", s)
    # 2) 괄호로 묶인 법령·조문 표기 제거 (예: (조세특례제한법 제29조의8), (제29조의8 제1항))
    s = re.sub(r"\([^)\n]*제\s*\d+\s*조[^)\n]*\)", "", s)
    # 3) 문장 내 법령명+조문번호 또는 단독 조문번호(제N조의M 제N항 제N호) 깔끔하게 제거 (줄바꿈 보존)
    s = re.sub(
        r"[「『]?[가-힣ㆍ· ]{2,25}(?:법률?|시행령|시행규칙)[」』]?[ ]*제[ ]*\d+[ ]*조(?:[ ]*의[ ]*\d+)?(?:[ ]*제[ ]*\d+[ ]*[항호목])*(?:[ ]*(?:에[ ]*따르면|에[ ]*따른|에[ ]*따라|에[ ]*의하면|에[ ]*의한|규정에[ ]*따르면|규정에[ ]*따라|상))?[ ]*",
        "",
        s
    )
    s = re.sub(r"제[ ]*\d+[ ]*조(?:[ ]*의[ ]*\d+)?(?:[ ]*제[ ]*\d+[ ]*[항호목])*[ ]*", "", s)
    # 4) 마크다운 굵게(**), 기울임(*), 취소선(~~), 인라인 코드(`) 기호 완전 제거
    s = re.sub(r"\*\*(.*?)\*\*", r"\1", s)
    s = re.sub(r"__(.*?)__", r"\1", s)
    s = re.sub(r"~~(.*?)~~", r"\1", s)
    s = s.replace("`", "").replace("「", "").replace("」", "").replace("『", "").replace("』", "")
    # 5) 마크다운 표(| --- |)가 있다면 카톡용 단순 줄바꿈 텍스트로 자동 변환
    lines = s.split("\n")
    out_lines = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("|") and line.endswith("|"):
            t_rows = []
            while i < len(lines):
                r_line = lines[i].strip()
                if not (r_line.startswith("|") and r_line.endswith("|")):
                    break
                if not re.match(r"^\|[\s\-:|]+\|$", r_line):
                    cells = [c.strip() for c in r_line.strip("|").split("|") if c.strip()]
                    if cells:
                        t_rows.append(cells)
                i += 1
            if len(t_rows) >= 2:
                headers = t_rows[0]
                for row in t_rows[1:]:
                    if len(row) == 2:
                        out_lines.append(f"- {row[0]} : {row[1]}")
                    else:
                        pairs = [f"{headers[idx]} {val}" if idx < len(headers) else val for idx, val in enumerate(row)]
                        out_lines.append("- " + " / ".join(pairs))
            continue
        # 6) 마크다운 헤더(### 등) 제거 후 깔끔한 대괄호 소제목으로 변환
        m_hdr = re.match(r"^#{1,6}\s*(.+)$", line)
        if m_hdr:
            hdr_txt = re.sub(r"^\d+\.\s*", "", m_hdr.group(1).strip())
            if not (hdr_txt.startswith("[") and hdr_txt.endswith("]")):
                hdr_txt = f"[{hdr_txt}]"
            out_lines.append(hdr_txt)
        elif re.match(r"^-{3,}$", line):
            pass
        else:
            # 글머리 기호(* )를 깔끔한 하이픈(- )으로 통일
            cleaned_line = re.sub(r"^(\s*)\*\s+", r"\1- ", lines[i])
            cleaned_line = re.sub(r"  +", " ", cleaned_line).rstrip()
            out_lines.append(cleaned_line)
        i += 1
    res = "\n".join(out_lines)
    res = re.sub(r"\n{3,}", "\n\n", res).strip()
    return res

def _strip_fake_cases_in_track2(answer: str, trace: dict, user_query: str = "") -> str:
    """트랙 2(카톡·이메일 초안 등 자유 양식)에서 미조회 사건번호를 제거하고, 카톡 요청 시 100% 순수 텍스트·조문번호 제거를 강제합니다."""
    if not answer:
        return answer
    out_text = answer
    if trace is not None:
        detail_blob = _norm(" ".join(trace["detail"]))
        list_blob = _norm(" ".join(trace["list"]))
        out_lines = []
        for line in out_text.split("\n"):
            fake_nos = [
                no for no in _find_case_numbers(line)
                if (no not in detail_blob and no not in list_blob)
            ]
            if fake_nos:
                print(f"[시스템] 🚫 트랙 2 미조회 사건번호 제거: {fake_nos}")
                continue
            out_lines.append(line)
        out_text = "\n".join(out_lines)
    if _is_kakao_request(user_query):
        out_text = _enforce_pure_kakao_text(out_text)
    return out_text

# ---------------------------------------------------------
# 🧪 의미 검증 (검증 모델 — 감수기 원문 글자 수 12,000자 무손실 유지 + 정밀 계산 결과 최우선 포함 + 경량 사고 버짓)
# ---------------------------------------------------------
def _strip_md(text: str) -> str:
    return re.sub(r"[*_`>#]", "", text or "").strip(" -")

def _extract_claims(answer: str, trace: dict, max_claims: int = 20) -> tuple[list, dict]:
    mult = 3 if trace.get("unleash") else 1
    effective_max_claims = max_claims * mult
    src_char_cap = 12000 * mult
    total_char_cap = 60000 * mult

    details = trace["detail"]
    art_texts = trace.get("article_texts", {})
    sources, src_index = {}, {}

    def _src_id(label: str, text: str) -> str:
        if label not in src_index:
            sid = f"S{len(src_index) + 1}"
            src_index[label] = sid
            if len(text) > src_char_cap:
                clipped = (
                    text[:src_char_cap]
                    + f"\n...[※ 원문 총 {len(text):,}자 중 앞 {src_char_cap:,}자만 표시됨. 생략된 뒷부분에 있을 수 있는 내용은 unsupported로 단정하지 말 것]"
                )
            else:
                clipped = text
            sources[sid] = (label, clipped)
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

    # 파이썬 정밀 계산기 산출 내역(`🧮 [정밀 계산 완료...`)을 최우선 포함하고,
    # 이어서 조회한 모든 조문 및 판례 원문을 원문 글자 수 축소 없이(12,000자 * mult) 그대로 전달합니다.
    total = sum(len(t) for _, t in sources.values())
    for idx, d in enumerate(details):
        if d.startswith("🧮"):
            head = d.split("\n", 1)[0][:55]
            if head not in src_index and total < total_char_cap:
                _src_id(head, d)
                total += min(len(d), src_char_cap)
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
    _emit_live_status("🛡️ 3단계: 듀얼 AI 감수(_semantic_verify) 정밀 판정 중...")
    src_block = "\n\n".join(f"[{sid}] {label}\n{text}" for sid, (label, text) in sources.items())
    claim_block = "\n".join(f"{n + 1}. (근거: {', '.join(c['sources'])}) {c['text']}" for n, c in enumerate(claims))
    prompt = (
        "당신은 세무 답변의 근거를 검증하는 감수자입니다. 아래 [사용자 질문(사례 전제)]와 [원문(법령·판례·계산 결과)] 전체를 기준으로 각 [주장]의 '핵심 법적 명제'가 뒷받침되는지 판정하세요.\n"
        "- supported: 핵심 법리가 [원문]에 부합하고, 사례 금액·계산값이 [사용자 질문] 또는 [정밀 계산 완료] 내역과 일치함. 특히 법령 원문의 천분율·만분율(예: 1천분의 70.9, 1천분의 90, 1만분의 91.82)을 백분율(%)로 환산한 수치나 노사 절반(50%, 1/2) 부담분으로 나눈 수치(예: 3.545%, 4.5%, 0.4591%, 건보료 대비 12.95% 등), 같은 뜻의 요약·의역, 원문들을 결합해 도출되는 당연한 세무조정·소득처분 결론은 모두 supported로 판정할 것\n"
        "- partial: 법령상의 고정 기준 수치(예: 세율, 법정한도율, 기준금액)를 [원문]의 환산값과도 다르게 잘못 적은 경우에만 부여할 것. (사용자 질문의 사례 금액이나 단위 환산·절반 분담 계산값이 법조문 글자와 표기 형태만 다르다는 이유로 partial을 주지 말 것!)\n"
        "- unsupported: 핵심 법리 자체가 [원문]과 정면으로 모순되는 경우 (원문이 일부 생략된 표시가 있을 때는 생략된 부분에 있을 수 있으므로 함부로 unsupported를 주지 말 것)\n"
        "원문 밖의 지식으로 판단하지 마세요. 사소한 표현 차이로 partial/unsupported를 주지 말 것. "
        "reason은 한국어 30자 이내로, 'S1' 같은 번호 대신 법령·판례 이름으로 쓰세요.\n"
        '출력은 JSON 배열만: [{"id": 1, "verdict": "supported", "reason": "..."}]\n\n'
        f"[사용자 질문(사례 전제)]\n{user_query[:3000]}\n\n[원문]\n{src_block}\n\n[주장]\n{claim_block}"
    )
    try:
        client = genai.Client(api_key=api_key, http_options={"timeout": 50000})
    except Exception:
        client = genai.Client(api_key=api_key)

    verifier_candidates = list(dict.fromkeys([VERIFIER_MODEL_ID, FLASH_BACKUP_ID, FLASH_LITE_ID, FLASH_FALLBACK_ID]))
    resp = None
    used_v_model = VERIFIER_MODEL_ID
    last_v_err = None
    for vm_id in verifier_candidates:
        try:
            # [속도 개선 ④] 감수기가 단위 환산(천분율→백분율 등)과 복합 조문 논리는 정확히 계산하되
            # 과도한 장문 추론으로 지연되지 않도록 thinking_budget=1024(핵심 추론 보장)를 부여하여 지능 저하 없이 속도만 단축합니다.
            try:
                fast_cfg = types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.0,
                    thinking_config=types.ThinkingConfig(thinking_budget=1024),
                )
                resp = client.models.generate_content(model=vm_id, contents=prompt, config=fast_cfg)
            except Exception:
                std_cfg = types.GenerateContentConfig(response_mime_type="application/json", temperature=0.0)
                resp = client.models.generate_content(model=vm_id, contents=prompt, config=std_cfg)
            used_v_model = vm_id
            break
        except Exception as e:
            last_v_err = e
            continue
    if resp is None:
        raise last_v_err or RuntimeError("감수 모델 호출 실패")

    raw = extract_safe_text(resp)
    _extract_and_log_response_usage(resp, used_v_model, count_call=False, est_in_chars=len(prompt), est_out_chars=len(raw))
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
    vmode = _verify_mode()
    counts = {"supported": 0, "partial": 0, "unsupported": 0, "unknown": 0}
    line_actions = {}
    for n, c in enumerate(claims):
        verdict, reason = verdicts.get(n + 1, ("unknown", ""))
        counts[verdict] = counts.get(verdict, 0) + 1
        if verdict in ("partial", "unsupported"):
            line_actions[c["line"]] = (verdict, reason)
            print(f"[시스템] 🧪 의미 검증 감지({verdict}): {reason} | {c['text'][:60]}")

    if not line_actions or vmode == "loose":
        return answer, counts

    out_lines = []
    for idx, line in enumerate(answer.split("\n")):
        if idx in line_actions:
            v_type, r_txt = line_actions[idx]
            if v_type == "unsupported" and vmode == "strict":
                if _show_diag():
                    indent = len(line) - len(line.lstrip(" "))
                    out_lines.append(" " * indent + f"- 🚫 *(의미 검증 불일치 삭제: {r_txt})*")
                continue
            else:
                if "⚠️" not in line:
                    note_str = f" ⚠️*(원문 확인 필요: {r_txt})*" if r_txt else " ⚠️*(원문 확인 필요)*"
                    out_lines.append(line + note_str)
                else:
                    out_lines.append(line)
                continue
        out_lines.append(line)
    return "\n".join(out_lines), counts


# ---------------------------------------------------------
# ✨ 스마트 법령 텍스트 압축기 (복합 조문 균등 추출 + 조문당 20,000자 확대) & 법령 전체 XML 통합 캐시
# ---------------------------------------------------------
def _fetch_full_law_xml_direct(doc_id: str, query_filter: str = "") -> str:
    """
    [속도 개선 ② & ③] 법령 전체 XML을 Gzip 압축으로 빠르게 받아 doc_id 단위로 통합 캐싱(`full_law_xml`)하고,
    동일 법령의 다른 조문(예: 제29조의8, 제127조, 제132조)을 연속 조회할 때
    두 번째 조문부터는 네트워크 다운로드 없이 메모리에서 0.001초 만에 즉시 반환합니다.
    """
    clean_id = str(doc_id).strip()
    if not clean_id.isdigit():
        return ""
    today_ymd = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
    full_cache_key = ("full_law_xml", today_ymd, clean_id)
    cached_full = _cache_get(full_cache_key)
    if cached_full is not None:
        return cached_full

    oc = get_law_oc_auto()
    if not oc:
        return ""
    # '0'으로 시작하는 6자리 법령ID(예: 001592)는 ID 파라미터 우선, 그 외 법령일련번호(MST)는 MST 우선 호출하여 첫 시도에 즉시 적중
    id_param_order = ("ID", "MST") if clean_id.startswith("0") else ("MST", "ID")
    for id_param in id_param_order:
        url = f"http://www.law.go.kr/DRF/lawService.do?OC={oc}&target=law&{id_param}={clean_id}&type=XML"
        try:
            xml_bytes = _http_get_bytes_fast(url, timeout=15)
            root = ET.fromstring(xml_bytes)
            lname = (root.findtext(".//법령명_한글") or root.findtext(".//법령명한글") or "").strip()
            if not lname:
                continue
            article_blocks = []
            for unit in root.findall(".//조문단위"):
                jo_content = (unit.findtext("조문내용") or "").strip()
                if not jo_content:
                    continue
                lines = [jo_content]
                for hang in unit.findall(".//항"):
                    h_txt = (hang.findtext("항내용") or "").strip()
                    if h_txt:
                        lines.append(h_txt)
                    for ho in hang.findall(".//호"):
                        ho_txt = (ho.findtext("호내용") or "").strip()
                        if ho_txt:
                            lines.append("  " + ho_txt)
                        for mok in ho.findall(".//목"):
                            mok_txt = (mok.findtext("목내용") or "").strip()
                            if mok_txt:
                                lines.append("    " + mok_txt)
                article_blocks.append("\n".join(lines))
            addenda_units = []
            for a_unit in root.findall(".//부칙단위"):
                anc_dt = re.sub(r"\D", "", a_unit.findtext("부칙공포일자") or "")
                anc_no = (a_unit.findtext("부칙공포번호") or "").strip()
                a_body = (a_unit.findtext("부칙내용") or "").strip()
                if not a_body:
                    a_body = "\n".join(t.strip() for t in a_unit.itertext() if t and t.strip())
                if not a_body:
                    continue
                dt_fmt = f"{anc_dt[:4]}.{anc_dt[4:6]}.{anc_dt[6:]}." if len(anc_dt) == 8 else anc_dt
                no_fmt = f"제{anc_no}호, " if anc_no else ""
                addenda_units.append((int(anc_dt) if anc_dt.isdigit() else 0, f"부칙 <{no_fmt}{dt_fmt}>\n{a_body}"))
            addenda_units.sort(key=lambda x: x[0], reverse=True)
            for _, a_blk in addenda_units[:15]:
                article_blocks.append(a_blk)
            if article_blocks:
                full_text = f"📘 [{lname}]\n\n" + "\n\n".join(article_blocks)
                _cache_set(full_cache_key, full_text)
                return full_text
        except Exception:
            continue
    return ""

def _resolve_law_id_if_name(doc_id: str) -> str:
    """
    [속도 개선 ①] AI가 search_law_for_gemini를 거치지 않고 doc_id 자리에
    '조세특례제한법', '법인세법 시행령' 등 법령명을 직접 넣었을 때
    프리워밍된 메모리 캐시(0.001초) 또는 즉시 검색을 통해 자동으로 법령일련번호(ID)로 변환합니다.
    """
    s_id = str(doc_id or "").strip()
    if not s_id or s_id.isdigit():
        return s_id

    clean_q = re.sub(r"[「」『』\[\]\"']", "", s_id).strip()
    clean_norm = clean_q.replace(" ", "")
    for alias, full in _LAW_ALIASES.items():
        if clean_norm == alias:
            clean_q = full
            clean_norm = full
            break
        elif clean_norm == alias + "시행령" or clean_norm == alias[:-1] + "령":
            clean_q = full + " 시행령"
            clean_norm = full + "시행령"
            break
        elif clean_norm == alias + "시행규칙" or clean_norm == alias[:-1] + "규칙":
            clean_q = full + " 시행규칙"
            clean_norm = full + "시행규칙"
            break

    today_ymd = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
    map_key = ("law_name_to_id", today_ymd, clean_norm)
    cached_id = _cache_get(map_key)
    if cached_id:
        return cached_id

    try:
        res = law_api.search_law_data(clean_q, "law")
        if res:
            if isinstance(res, dict):
                res = [res]
            exact = [it for it in res if str(it.get("법령명한글", "")).replace(" ", "") == clean_norm]
            cands = exact if exact else res[:1]
            cands.sort(key=lambda x: (str(x.get("공포일자", "")), str(x.get("시행일자", ""))), reverse=True)
            found_id = str(cands[0].get("법령일련번호") or cands[0].get("법령ID") or "").strip()
            if found_id:
                _cache_set(map_key, found_id)
                print(f"[시스템] 🔄 법령명 자동 ID 변환 완료: '{doc_id}' -> ID '{found_id}'")
                return found_id
    except Exception:
        pass
    return s_id

def compress_legal_text(raw_text: str, query_filter: str = "") -> str:
    if not raw_text:
        return ""

    def _keep_recent_rev_tag(match: re.Match) -> str:
        full_tag = match.group(0)
        if re.search(r"202[5-9]", full_tag):
            years = re.findall(r"202[5-9]\.\s*\d{1,2}\.\s*\d{1,2}\.?", full_tag)
            kind = match.group(1)
            if years:
                return f" <최근{kind}: {', '.join(years[-2:])}>"
            return full_tag
        return ""

    cleaned = re.sub(r"<(개정|신설|타법개정|일부개정|전문개정)[^>]*>", _keep_recent_rev_tag, raw_text)
    cleaned = re.sub(r"\[(전문개정|본조신설|제목개정|제\d+조에서 이동)[^\]]*\]", _keep_recent_rev_tag, cleaned)

    mult = 3 if _is_unleashed() else 1
    art_matches = re.findall(r"제?\s*(\d+)\s*조(?:\s*의\s*(\d+))?", query_filter or "")
    base_limit = 20000 if art_matches else 5000
    limit = base_limit * mult

    if art_matches:
        target_prefixes = list(dict.fromkeys(
            f"제{m[0]}조" + (f"의{m[1]}" if m[1] else "")
            for m in art_matches
        ))
        wants_add = "부칙" in (query_filter or "")
        blocks = cleaned.split("\n\n")
        header = blocks[0] if blocks else ""
        exact_articles = []
        other_mentions = []
        addenda_matches = []
        addenda_all = []

        for blk in blocks[1:]:
            blk_s = blk.strip()
            blk_clean = blk_s.replace(" ", "")
            is_add_blk = blk_s.startswith("부칙") or blk_s.startswith("[부칙") or blk_s.startswith("📌")
            if is_add_blk:
                addenda_all.append(blk_s)
                if any(tp in blk_clean for tp in target_prefixes):
                    addenda_matches.append(blk_s)
                continue
            if any(
                blk_clean.startswith(tp + "(") or blk_clean.startswith(tp + " ") or blk_clean == tp
                or re.match(rf"^{re.escape(tp)}(?![0-9의])", blk_clean)
                for tp in target_prefixes
            ):
                exact_articles.append(blk_s)
            elif any(tp in blk_clean for tp in target_prefixes):
                other_mentions.append(blk_s)

        if wants_add and not exact_articles and addenda_all:
            picked_add = addenda_matches if addenda_matches else addenda_all[:5 * mult]
            cleaned = header + "\n\n📌 [법령 부칙 (시행일·적용례·경과조치)]\n\n" + "\n\n".join(picked_add)
        elif exact_articles:
            total_exact_len = sum(len(x) for x in exact_articles)
            if len(exact_articles) > 1 and total_exact_len > limit:
                per_art_quota = max(5000, (limit - len(header) - 200) // len(exact_articles))
                balanced_articles = []
                for ea in exact_articles:
                    if len(ea) > per_art_quota:
                        balanced_articles.append(ea[:per_art_quota] + f"\n...[※ 해당 조문 {len(ea):,}자 중 {per_art_quota:,}자 표시]")
                    else:
                        balanced_articles.append(ea)
                cleaned = header + "\n\n" + "\n\n".join(balanced_articles)
            else:
                cleaned = header + "\n\n" + "\n\n".join(exact_articles)
            if addenda_matches:
                add_Cap = 4500 * mult if wants_add else 2500 * mult
                add_txt = "\n\n".join(addenda_matches[:4 if wants_add else 2])[:add_Cap]
                cleaned += "\n\n📌 [관련 최근 개정 부칙(시행일·적용례·경과조치) 발췌]\n" + add_txt
            elif wants_add and addenda_all:
                add_txt = "\n\n".join(addenda_all[:3 * mult])[:4500 * mult]
                cleaned += "\n\n📌 [최근 개정 부칙(시행일·적용례·경과조치)]\n" + add_txt
        elif other_mentions:
            cleaned = header + "\n\n" + "\n\n".join(other_mentions[:3 * mult])
    elif query_filter and query_filter.strip():
        kw_clean = query_filter.strip().replace(" ", "")
        blocks = cleaned.split("\n\n")
        header = blocks[0] if blocks else ""
        matched_blks = [b.strip() for b in blocks[1:] if kw_clean in b.replace(" ", "")]
        if matched_blks:
            cleaned = header + "\n\n" + "\n\n".join(matched_blks[:5 * mult])

    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    if len(cleaned) > limit:
        return (cleaned[:limit]
                + f"\n\n[※ 원문 {len(cleaned):,}자 중 {limit:,}자까지만 표시됨. 필요한 조문이 더 있으면 "
                  "query_filter에 해당 조문번호를 지정해 다시 조회할 것]")
    return cleaned


# ---------------------------------------------------------
# 1. 모델 설정 (1번 아르곤 직결 방식 + 2026.10 공식 Gemini API 라인업) & 대화방당 2,000원 Pro 차단기
# ---------------------------------------------------------
def _model_id(env_key: str, default: str) -> str:
    return _get_secret_or_env(env_key) or default

# ⚡ Flash 고속 모드 라인업 (전원 Stable GA 정식 모델 우선 배치)
FLASH_MODEL_ID     = _model_id("GEMINI_FLASH_MODEL", "gemini-3.8-flash")
FLASH_BACKUP_ID    = _model_id("GEMINI_FLASH_BACKUP_MODEL", "gemini-3.6-flash")
FLASH_LITE_ID      = _model_id("GEMINI_FLASH_LITE_MODEL", "gemini-3.5-flash-lite")
FLASH_FALLBACK_ID  = "gemini-2.5-flash"

VERIFIER_MODEL_ID  = _model_id("GEMINI_VERIFIER_MODEL", "gemini-3.8-flash")
SEMANTIC_VERIFY_ON = (
    (_get_secret_or_env("SEMANTIC_VERIFY").lower() in ("on", "true", "1"))
    if _verify_mode() == "loose"
    else (_get_secret_or_env("SEMANTIC_VERIFY").lower() not in ("off", "false", "0"))
)

# 👑 Pro 심층 모드: [1번 아르곤 직결 방식] gemini-4-argon (Stable GA) 1순위 기본 활성화!
# (만약 추후 Argon을 잠그고 싶을 때만 Secrets/환경변수에 USE_ARGON_MODEL="off" 설정)
USE_ARGON_MODEL = _get_secret_or_env("USE_ARGON_MODEL").lower() not in ("off", "false", "0")
ARGON_MODEL_ID  = _model_id("GEMINI_ARGON_MODEL", "gemini-4-argon")

PAID_PRO_MODEL_IDS = (
    ([ARGON_MODEL_ID] if USE_ARGON_MODEL else [])
    + [
        _model_id("GEMINI_PAID_PRO_CUSTOMTOOLS_MODEL", "gemini-3.1-pro-preview-customtools"),  # 2순위: 도구 호출 특화 Pro
        _model_id("GEMINI_PAID_PRO_MODEL", "gemini-3.1-pro-preview"),                          # 3순위: 표준 3.1 Pro
        "gemini-2.5-pro",                                                                      # 4순위: 안정형 2.5 Pro 백업
    ]
)

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
            f"> ⛔ **[이 대화방 한도({limit_krw:,.0f}원) 도달 — Pro/Argon 모드 자동 차단됨]** "
            f"현재 대화방의 누적 예상 요금(**{cur_krw:,.0f}원**)이 방 한도({limit_krw:,.0f}원)를 초과하여 "
            "과금 보호를 위해 **Flash 표준 모드**로 자동 전환되었습니다. (새 대화방을 이용하거나 현재 방을 비우시면 Pro/Argon이 다시 활성화됩니다.)\n"
        )
        return "FLASH", "⚡ **[Flash 표준 모드 (대화방 한도 보호 작동)]** 실무 표준 검토", block_notice

    if wants_manual_pro:
        return (
            "PRO",
            "👑 **[Pro 심층 모드 — Argon 직결 (데이터·도구 한도 3배 개방)]** 사용자 지정 초정밀 검토 (`[프로]`)",
            ""
        )

    if wants_file_pro:
        return (
            "PRO",
            f"👑 **[Pro 심층 모드 자동 전환 — Argon 직결 (데이터·도구 한도 3배 개방)]** 대용량 첨부문서({full_input_len:,}자) 초정밀 분석",
            ""
        )

    matched_simul = [kw for kw in SIMUL_KEYWORDS if kw in q_clean]
    if len(q_clean) >= LONG_SIMUL_QUERY_CHARS and len(matched_simul) >= 1 and not budget_exceeded:
        kw_str = ", ".join(matched_simul[:3])
        notice = (
            f"> 💡 **[Pro/Argon 정밀검토 전환 안내]** 초장문({len(q_clean):,}자) 시뮬레이션 질의(감지 키워드: `{kw_str}`)가 확인되었습니다. "
            "현재 답변은 표준 한도(Flash)로 빠르게 작성되었으며, **판례·예규 전문 독해 및 데이터·도구 한도 3배 개방(Argon 직결)**을 통한 "
            "심층 재검토가 필요하시면 좌측 **Pro 토글을 켜거나** 답변 하단의 **`👑 [프로/Argon] 3배 개방 재검토`** 버튼을 눌러주세요.\n"
        )
        return "FLASH", "⚡ **[Flash 빠른 검토 모드]** 실무 표준 검토", notice

    return "FLASH", "⚡ **[Flash 빠른 검토 모드]** 실무 표준 검토", ""

# ---------------------------------------------------------
# 2. Gemini 도구 정의 (12개 도구 전체 docstring + 복수 법령 병렬 조회 및 1턴 직행 지원)
# ---------------------------------------------------------
def search_law_for_gemini(keyword: str, target: str = "law") -> str:
    """
    국가법령정보센터에서 법령, 대법원 판례, 헌법재판소 결정례, 조세심판원 결정례, 행정규칙, 법령해석례, 지자체 조례, 별표·서식 목록과 일련번호(ID)를 검색합니다.
    - target: 'law'(법령), 'prec'(대법원 판례), 'detc'(헌법재판소 위헌·헌법불합치 결정례), 'decc'(조세심판원 결정례), 'admrul'(훈령·예규·고시·기본통칙), 'expc'(법령해석례), 'ordin'(지자체 조례), 'licbyl'(법령 별표·서식)
    - target='law'일 때 keyword에는 '법령명만' 넣을 것 (예: '소득세법', '소득세법 시행령'). 주제어는 넣지 말 것. (정식 법령명을 아는 경우 get_law_details_for_gemini의 doc_id에 법령명을 바로 넣으면 1턴에 직행 조회됨)
    - target='prec'/'detc'/'decc'/'expc'는 핵심 주제어(예: '업무무관 가지급금')나 사건번호(예: '2005두9415', '2021헌바123')로 검색할 것.
    """
    if _over_limit("search", target):
        print(f"\n[시스템] ⛔ 검색 한도 도달 → 차단: '{keyword}' (대상: {target})")
        return (f"[검색 한도 도달] 이번 질문에서 '{target}' 검색은 더 할 수 없습니다. "
                "지금까지 조회한 원문만으로 답변을 작성하고, 찾지 못한 근거는 '관련 원문을 확인하지 못했다'고 쓰세요.")

    _emit_live_status(f"🔎 1단계: 법제처 DB 목록 탐색 중 ('{keyword}' · {target})...")
    today_ymd = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
    cache_key = ("search", today_ymd, keyword.strip(), target)
    cached_pack = _cache_get(cache_key)
    if cached_pack is not None:
        results, used_keyword = cached_pack
        print(f"\n[시스템] ⚡ [메모리 캐시 즉시 히트(0.001초)] 목록 검색: '{keyword}' (대상: {target})")
    else:
        print(f"\n[시스템] 💡 목록 검색 도구 가동: '{keyword}' (대상: {target})")
        try:
            results = law_api.search_law_data(keyword, target)
        except Exception as e:
            print(f"[시스템] ⚠️ 법제처 검색 오류: {e}")
            results = None
        used_keyword = keyword

        if not results and target in ("prec", "decc", "detc", "expc", "admrul"):
            print("[시스템]    ↳ 제목 검색 결과 없음 → 본문 검색으로 재시도")
            try:
                results = law_api.search_law_data(keyword, target, search_mode=2)
            except Exception:
                results = None
            if results:
                used_keyword = keyword + " (본문검색)"

        words = keyword.split()
        while not results and len(words) > 1:
            words = words[:-1]
            used_keyword = " ".join(words)
            print(f"[시스템]    ↳ 결과 없음 → '{used_keyword}'로 자동 재검색")
            try:
                results = law_api.search_law_data(used_keyword, target)
                if not results and target in ("prec", "decc", "detc", "expc", "admrul"):
                    results = law_api.search_law_data(used_keyword, target, search_mode=2)
            except Exception:
                results = None

        if results:
            _cache_set(cache_key, (results, used_keyword))

    if not results:
        return _record("list", f"'{keyword}' (대상: {target}) 검색 결과가 없습니다. 법령은 법령명만, 판례는 핵심 주제어 1~2개로 다시 검색하세요.")

    if isinstance(results, dict):
        results = [results]

    if target == "law":
        for item in results[:5]:
            lnm = str(item.get("법령명한글", "")).replace(" ", "").strip()
            lid = str(item.get("법령일련번호") or item.get("법령ID") or "").strip()
            if lnm and lid:
                _cache_set(("law_name_to_id", today_ymd, lnm), lid)

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
        elif target == "detc":
            summary += f"{i+1}. [헌재결정례] 사건명: {item.get('사건명')} | 사건번호: {item.get('사건번호')} | 종국일자: {item.get('종국일자')} | ID: {item.get('헌재결정례일련번호')}\n"
        elif target == "licbyl":
            summary += f"{i+1}. [별표/서식] {item.get('별표명')} | 관련법령: {item.get('관련법령명')} | 구분: {item.get('별표구분')} | ID: {item.get('별표일련번호')}\n"
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
    if trace is not None:
        meta = trace.setdefault("meta_map", {})
        for item in results[:15]:
            if target in ("prec", "decc", "detc"):
                rid = item.get("판례일련번호") or item.get("헌재결정례일련번호") or item.get("특별행정심판재결례일련번호") or item.get("행정심판재결례일련번호")
                rno = item.get("사건번호") or item.get("청구번호")
                if rid and rno:
                    trace["id_map"][str(rid).strip()] = rno.strip()
                    meta[(target, _norm(rno))] = str(rid).strip()
            elif target == "expc":
                rid = item.get("법령해석례일련번호")
                rno = item.get("안건번호")
                if rid and rno:
                    meta[("expc", _norm(rno))] = str(rid).strip()
            elif target == "admrul":
                rid = item.get("행정규칙일련번호")
                rnm = item.get("행정규칙명")
                rno = item.get("발령번호")
                if rid and rnm:
                    meta[("admrul", _norm(rnm))] = str(rid).strip()
                if rid and rno:
                    meta[("admrul", _norm(rno))] = str(rid).strip()
    return _record("list", summary)

def get_law_details_for_gemini(doc_id: str, target: str = "law", query_filter: str = "") -> str:
    """
    검색된 일련번호(ID) 또는 정식 법령명(예: '조세특례제한법', '조세특례제한법 시행령')으로 조문·부칙·판례·헌재결정례·심판례 원문을 조회합니다.
    - 법령('law') 조회 시 query_filter에 조문번호(예: '제29조의8', '제29조의8, 부칙') 또는 '부칙'(시행일·적용례·경과조치 확인용)을 넣어 호출하세요.
    - target: 'law'(법령·부칙), 'prec'(대법원 판례), 'detc'(헌법재판소 결정례), 'decc'(조세심판원 결정례), 'admrul'(행정규칙·예규), 'expc'(법령해석례), 'ordin'(조례), 'licbyl'(별표·서식)
    - doc_id에 정식 법령명을 바로 넣으면 search_law_for_gemini 없이 1턴에 즉시 원문 및 관련 개정 부칙이 조회됩니다.
    """
    _emit_live_status(f"📖 2단계: 법령·판례 원문 정밀 파싱 중 ('{doc_id}' · {query_filter or target})...")

    # [속도 개선 ②] doc_id에 쉼표(,)로 복수 법령/ID가 들어온 경우 ThreadPoolExecutor로 병렬 XML 프리페치 후 순차 결합
    if "," in str(doc_id or "") and len(str(doc_id).split(",")) <= 4:
        sub_ids = [s.strip() for s in str(doc_id).split(",") if s.strip()]
        if len(sub_ids) > 1:
            if target == "law":
                resolved_pairs = [(sid, _resolve_law_id_if_name(sid)) for sid in sub_ids]
                with ThreadPoolExecutor(max_workers=min(4, len(resolved_pairs))) as ex:
                    for _, rid in resolved_pairs:
                        if rid.isdigit():
                            ex.submit(_fetch_full_law_xml_direct, rid, query_filter)
            combined_parts = [get_law_details_for_gemini(sid, target=target, query_filter=query_filter) for sid in sub_ids]
            return "\n\n====================\n\n".join(combined_parts)

    if target == "law":
        doc_id = _resolve_law_id_if_name(doc_id)

    trace = _TOOL_TRACE.get()
    if trace is not None and target != "law":
        seen = trace.setdefault("seen_docs", set())
        if (target, str(doc_id)) in seen:
            print(f"\n[시스템] ♻️ 이미 조회한 원문 → 재조회 생략: ID '{doc_id}' (대상: {target})")
            return "[이미 조회한 원문] 이 문서는 이번 질문에서 이미 전체 원문을 조회했습니다. 앞의 조회 결과를 그대로 참고하세요."
    if _over_limit("detail", target):
        print(f"\n[시스템] ⛔ 원문 조회 한도 도달 → 차단: ID '{doc_id}' (대상: {target})")
        return (f"[원문 조회 한도 도달] 이번 질문에서 '{target}' 원문 조회는 더 할 수 없습니다. "
                "이미 조회한 원문만으로 답변을 작성하세요.")

    today_ymd = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
    clean_id = str(doc_id).strip()
    cache_key = ("detail_raw", today_ymd, clean_id, target, query_filter.strip())

    # 동일 법령의 전체 XML이 이미 메모리에 캐싱되어 있으면 API 호출 없이 0.001초 만에 즉시 활용
    full_law_cached = _cache_get(("full_law_xml", today_ymd, clean_id)) if target == "law" else None
    raw_text = full_law_cached if full_law_cached is not None else _cache_get(cache_key)

    if raw_text is not None:
        print(f"\n[시스템] ⚡ [메모리 캐시 즉시 히트(0.001초)] 원문 조회: ID '{clean_id}' (대상: {target}, 필터: '{query_filter}')")
    else:
        print(f"\n[시스템] 📖 원문 정밀 조회 가동: ID '{clean_id}' (대상: {target}, 필터: '{query_filter}')")
        if target == "law" and clean_id.isdigit():
            raw_text = _fetch_full_law_xml_direct(clean_id, query_filter)
            if not raw_text:
                try:
                    raw_text = law_api.get_law_content(clean_id, target, query_filter)
                except Exception as e:
                    raw_text = f"❌ 원문 조회 오류: {e}"
        else:
            try:
                raw_text = law_api.get_law_content(clean_id, target, query_filter)
            except Exception as e:
                raw_text = f"❌ 원문 조회 오류: {e}"

        if raw_text and not str(raw_text).startswith("❌"):
            _cache_set(cache_key, raw_text)

    result = compress_legal_text(raw_text, query_filter)
    body_ok = bool(result and not result.startswith("❌") and len(result) >= 80)

    if trace is not None and target != "law" and body_ok:
        trace.setdefault("seen_docs", set()).add((target, clean_id))

    preview = result[:150].replace("\n", " ")
    print(f"[시스템]    ↳ 원문 {len(raw_text or ''):,}자 → 전달 {len(result):,}자 | 앞부분: {preview}")
    if target == "law" and body_ok:
        _record_law_articles(result)
    if trace is not None and target in ("prec", "decc", "detc"):
        rno = trace["id_map"].get(clean_id)
        if rno and body_ok and _norm(rno) not in _norm(result):
            result = f"[사건(청구)번호: {rno}]\n" + result
        if not body_ok:
            print(f"[시스템]    ↳ ⚠️ 원문이 비었거나 오류: {result[:120]}")
    return _record("detail", result)

def search_historical_law_for_gemini(law_name: str, target_date: str, query_filter: str = "") -> str:
    """
    과거 귀속연도(예: '2022', '2023-06-30', '20211231') 세무조사·경정청구·기한후신고 검토 시
    국가법령정보센터 연혁·시행일법령(target='eflaw') DB에서 해당 과거 시점에 실제로 시행 중이던 구법 조문 원문을 조회합니다.
    - law_name: 정식 법령명만 입력 (예: '조세특례제한법', '법인세법 시행령')
    - target_date: 과거 기준연도 또는 일자 (예: '2022', '20221231')
    - query_filter: 조회할 조문번호 (예: '제29조의7', '제10조')
    """
    if _over_limit("detail", "eflaw"):
        return "[구법 조회 한도 도달] 이번 질문에서 추가 연혁법령 조회는 더 할 수 없습니다."

    _emit_live_status(f"🕰️ 2단계: 구법(연혁법령) 타임머신 조회 중 ('{law_name}' · {target_date})...")
    digits = re.sub(r"[^0-9]", "", str(target_date or ""))
    if len(digits) == 4:
        ymd_int = int(digits + "1231")
    elif len(digits) == 6:
        ymd_int = int(digits + "28")
    elif len(digits) >= 8:
        ymd_int = int(digits[:8])
    else:
        ymd_int = int(datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d"))

    oc = get_law_oc_auto()
    if not oc:
        return "❌ 법제처 API 인증키(OC)를 확인할 수 없어 연혁법령 조회가 불가능합니다."

    cache_key = ("hist_law", law_name.strip(), ymd_int, query_filter.strip())
    cached_res = _cache_get(cache_key)
    if cached_res is not None:
        print(f"\n[시스템] ⚡ [메모리 캐시 히트] 구법 타임머신: '{law_name}' (기준일: {ymd_int}, 필터: '{query_filter}')")
        _record_law_articles(cached_res)
        return _record("detail", cached_res)

    print(f"\n[시스템] 🕰️ 구법(연혁법령) 타임머신 가동: '{law_name}' (과거 기준일: {ymd_int}, 조문필터: '{query_filter}')")
    encoded_q = urllib.parse.quote(law_name.strip())

    try:
        candidates = []
        target_clean = law_name.replace(" ", "").strip()
        for s_target in ("eflaw", "law"):
            search_url = f"http://www.law.go.kr/DRF/lawSearch.do?OC={oc}&target={s_target}&type=XML&query={encoded_q}&display=50"
            xml_data = _http_get_bytes_fast(search_url, timeout=15)
            root = ET.fromstring(xml_data)
            for law_node in root.findall(".//law"):
                lname = (law_node.findtext("법령명한글") or "").strip()
                if lname.replace(" ", "") != target_clean:
                    continue
                ef_yd = re.sub(r"[^0-9]", "", law_node.findtext("시행일자") or "")
                anc_yd = re.sub(r"[^0-9]", "", law_node.findtext("공포일자") or "")
                mst = (law_node.findtext("법령일련번호") or law_node.findtext("MST") or "").strip()
                anc_no = (law_node.findtext("공포번호") or "").strip()
                rev_nm = (law_node.findtext("제개정구분명") or "").strip()
                if ef_yd.isdigit() and int(ef_yd) <= ymd_int and mst:
                    candidates.append({
                        "lname": lname,
                        "ef_yd": int(ef_yd),
                        "anc_yd": int(anc_yd) if anc_yd.isdigit() else 0,
                        "mst": mst,
                        "anc_no": anc_no,
                        "rev_nm": rev_nm
                    })
            if candidates:
                break

        if not candidates:
            return f"'{law_name}'의 {ymd_int} 기준 연혁법령 목록을 찾지 못했습니다. 일반 get_law_details_for_gemini 도구로 현행 조문 및 부칙을 확인하세요."

        candidates.sort(key=lambda x: (x["ef_yd"], x["anc_yd"]), reverse=True)
        chosen = candidates[0]
        mst_id = chosen["mst"]
        ef_yd_str = str(chosen["ef_yd"])

        full_hist_key = ("hist_law_full", mst_id, ef_yd_str)
        full_raw = _cache_get(full_hist_key)

        if not full_raw:
            detail_urls = [
                f"http://www.law.go.kr/DRF/lawService.do?OC={oc}&target=eflaw&MST={mst_id}&efYd={ef_yd_str}&type=XML",
                f"http://www.law.go.kr/DRF/lawService.do?OC={oc}&target=law&MST={mst_id}&type=XML",
                f"http://www.law.go.kr/DRF/lawService.do?OC={oc}&target=law&ID={mst_id}&type=XML",
            ]
            article_blocks = []
            for d_url in detail_urls:
                try:
                    detail_xml = _http_get_bytes_fast(d_url, timeout=20)
                    d_root = ET.fromstring(detail_xml)
                    for unit in d_root.findall(".//조문단위"):
                        jo_content = (unit.findtext("조문내용") or "").strip()
                        if not jo_content:
                            continue
                        lines = [jo_content]
                        for hang in unit.findall(".//항"):
                            h_txt = (hang.findtext("항내용") or "").strip()
                            if h_txt:
                                lines.append(h_txt)
                            for ho in hang.findall(".//호"):
                                ho_txt = (ho.findtext("호내용") or "").strip()
                                if ho_txt:
                                    lines.append("  " + ho_txt)
                                for mok in ho.findall(".//목"):
                                    mok_txt = (mok.findtext("목내용") or "").strip()
                                    if mok_txt:
                                        lines.append("    " + mok_txt)
                        article_blocks.append("\n".join(lines))
                    for a_unit in d_root.findall(".//부칙단위"):
                        anc_dt = re.sub(r"\D", "", a_unit.findtext("부칙공포일자") or "")
                        anc_no = (a_unit.findtext("부칙공포번호") or "").strip()
                        a_body = (a_unit.findtext("부칙내용") or "").strip()
                        if a_body:
                            dt_fmt = f"{anc_dt[:4]}.{anc_dt[4:6]}.{anc_dt[6:]}." if len(anc_dt) == 8 else anc_dt
                            no_fmt = f"제{anc_no}호, " if anc_no else ""
                            article_blocks.append(f"부칙 <{no_fmt}{dt_fmt}>\n{a_body}")
                    if article_blocks:
                        break
                except Exception:
                    continue

            if not article_blocks:
                fallback_txt = law_api.get_law_content(mst_id, "law", query_filter)
                return _record("detail", compress_legal_text(fallback_txt, query_filter))

            header_str = (
                f"📘 [{chosen['lname']} | 🕰️ 구법(연혁법령) 타임머신 조회 (기준일: {ymd_int}) | "
                f"시행일: {chosen['ef_yd']} | 공포번호: 제{chosen['anc_no']}호 ({chosen['rev_nm']}) | MST: {mst_id}]"
            )
            full_raw = header_str + "\n\n" + "\n\n".join(article_blocks)
            _cache_set(full_hist_key, full_raw)

        compressed = compress_legal_text(full_raw, query_filter)
        _cache_set(cache_key, compressed)
        _record_law_articles(compressed)
        return _record("detail", compressed)
    except Exception as e:
        return f"❌ 구법(연혁법령) 조회 중 오류 발생 ({law_name}, 기준일 {ymd_int}): {e}"

def search_exchange_rate_for_gemini(start_date: str, end_date: str, currency: str = "USD") -> str:
    """한국은행(ECOS) 공식 환율을 조회합니다. start_date/end_date는 'YYYYMMDD', currency는 'USD','JPY','EUR','CNY' 등."""
    _emit_live_status(f"💱 1단계: 한국은행(ECOS) 공식 환율 조회 중 ({currency})...")
    print(f"\n[시스템] 💱 한국은행 환율 조회 도구 가동: {currency} ({start_date}~{end_date})")
    try:
        return _record("detail", law_api.get_bok_exchange_rate(start_date, end_date, currency))
    except Exception as e:
        return f"환율 조회 오류: {e}"

def search_base_rate_for_gemini(start_date: str, end_date: str) -> str:
    """한국은행 기준금리를 조회합니다. start_date/end_date는 'YYYYMMDD' 형식입니다."""
    _emit_live_status("📈 1단계: 한국은행(ECOS) 기준금리 조회 중...")
    print(f"\n[시스템] 📈 한국은행 기준금리 조회 도구 가동: ({start_date}~{end_date})")
    try:
        return _record("detail", law_api.get_bok_base_rate(start_date, end_date))
    except Exception as e:
        return f"기준금리 조회 오류: {e}"

def search_industry_code_for_gemini(keyword: str) -> str:
    """국세청 업종코드(6자리) 및 기준·단순경비율을 검색합니다. keyword에 업종명이나 6자리 코드를 넣으세요."""
    _emit_live_status(f"🏢 1단계: 국세청 업종코드·경비율 DB 조회 중 ('{keyword}')...")
    print(f"\n[시스템] 🏢 국세청 업종코드 검색 도구 가동: '{keyword}'")
    try:
        return _record("detail", law_api.search_industry_code(keyword))
    except Exception as e:
        return f"업종코드 조회 오류: {e}"

def search_dart_corp_for_gemini(corp_name: str, bsns_year: str = "2025") -> str:
    """DART 전자공시에서 기업개황·요약재무제표·최대주주 지분·배당 정보를 조회합니다. bsns_year는 '2025' 등 4자리 연도."""
    _emit_live_status(f"📊 1단계: DART 전자공시 재무·지분 조회 중 ('{corp_name}')...")
    print(f"\n[시스템] 📊 DART 전자공시 통합 조회 가동: '{corp_name}' ({bsns_year}년)")
    cap = 12000 if _is_unleashed() else 4000
    try:
        return _record("detail", law_api.get_dart_corp_info(corp_name, bsns_year)[:cap])
    except Exception as e:
        return f"DART 공시 조회 오류: {e}"

def check_nts_biz_status_for_gemini(biz_numbers: str) -> str:
    """국세청 사업자등록 상태(계속/휴·폐업) 및 과세유형(일반/간이/면세)을 실시간 조회합니다."""
    _emit_live_status("🔎 1단계: 국세청 사업자등록 상태·과세유형 실시간 조회 중...")
    print(f"\n[시스템] 🔎 국세청 사업자등록 상태·과세유형 실시간 조회 가동: '{biz_numbers}'")
    try:
        return _record("detail", law_api.get_nts_biz_status(biz_numbers))
    except Exception as e:
        return f"사업자 상태 조회 오류: {e}"

def verify_nts_biz_info_for_gemini(b_no: str, start_dt: str, p_nm: str, b_nm: str = "") -> str:
    """국세청 사업자등록 진위확인을 수행합니다. b_no(10자리), start_dt(개업일 YYYYMMDD), p_nm(대표자명)."""
    _emit_live_status("🛡️ 1단계: 국세청 사업자등록 진위확인 중...")
    print(f"\n[시스템] 🛡️ 국세청 사업자등록 진위확인 가동: {b_no} | {start_dt} | {p_nm}")
    try:
        if hasattr(law_api, "verify_nts_biz_info"):
            return _record("detail", law_api.verify_nts_biz_info(b_no, start_dt, p_nm, b_nm))
        return "현재 law_api.py에 진위확인 함수가 없습니다."
    except Exception as e:
        return f"사업자 진위확인 오류: {e}"

def search_real_estate_trade_for_gemini(property_type: str, region: str, deal_ymd: str, filter_keyword: str = "") -> str:
    """국토부 부동산 실거래가를 조회합니다. property_type('apt','offi','commercial','land'), region(지역명), deal_ymd('YYYYMM')."""
    _emit_live_status(f"🏘️ 1단계: 국토교통부 부동산 실거래가 조회 중 ({region})...")
    print(f"\n[시스템] 🏘️ 국토교통부 부동산 실거래가 조회 가동: 유형={property_type} | 지역={region} | 연월={deal_ymd} | 필터='{filter_keyword}'")
    try:
        if hasattr(law_api, "get_molit_real_estate_trade"):
            return _record("detail", law_api.get_molit_real_estate_trade(property_type, region, deal_ymd, filter_keyword))
        return "현재 law_api.py에 부동산 실거래가 조회 함수가 없습니다."
    except Exception as e:
        return f"실거래가 조회 오류: {e}"

def search_official_land_price_for_gemini(address: str, stdr_year: str = "") -> str:
    """브이월드 API로 부동산 개별공시지가 및 공동주택 공시가격을 조회합니다."""
    _emit_live_status(f"🏛️ 1단계: 브이월드 공시지가·공동주택공시가격 조회 중 ({address})...")
    print(f"\n[시스템] 🏛️ 브이월드 공시지가·공동주택공시가격 조회 가동: 주소='{address}' | 기준연도='{stdr_year}'")
    try:
        if hasattr(law_api, "get_vworld_official_price"):
            return _record("detail", law_api.get_vworld_official_price(address, stdr_year))
        return "현재 law_api.py에 공시지가 조회 함수가 없습니다."
    except Exception as e:
        return f"공시지가 조회 오류: {e}"

# ---------------------------------------------------------
# 🛡️ 정밀 수리 계산기: AST 화이트리스트 보안 샌드박스 & 천 단위 쉼표 지능형 정제
#    (min(100,200) 공백 없는 인자 쉼표 보호 + 음수 거듭제곱 1.05**-3 허용 + pow(a,b) 지수 한도 검증 완벽 통합)
# ---------------------------------------------------------
_ALLOWED_CALC_FUNCS = {"abs", "round", "min", "max", "sum", "pow", "int", "float"}
_ALLOWED_MATH_ATTRS = {
    "floor", "ceil", "sqrt", "trunc", "log", "log10", "exp", "pow", "fabs", "isfinite", "pi", "e"
}
_ALLOWED_AST_NODES = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.BoolOp,
    ast.Compare,
    ast.IfExp,
    ast.Call,
    ast.keyword,
    ast.Constant,
    ast.Name,
    ast.Load,
    ast.Attribute,
    ast.Tuple,
    ast.List,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
    ast.UAdd,
    ast.USub,
    ast.Not,
    ast.And,
    ast.Or,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
)

def _check_safe_pow_exponent(exp_node: ast.AST) -> None:
    """
    `10 ** 10000`이나 `pow(10, 10000)` 같은 과도한 거듭제곱을 차단하되,
    세무·회계 현재가치 할인 계산에 필수적인 음수 지수(`(1 + 0.05) ** -3`)는 안전하게 허용합니다.
    """
    if isinstance(exp_node, ast.Constant) and isinstance(exp_node.value, (int, float)) and not isinstance(exp_node.value, bool):
        if abs(exp_node.value) > 1000:
            raise ValueError("거듭제곱 지수가 너무 큽니다(최대 1000).")
        return
    if (
        isinstance(exp_node, ast.UnaryOp)
        and isinstance(exp_node.op, (ast.UAdd, ast.USub))
        and isinstance(exp_node.operand, ast.Constant)
        and isinstance(exp_node.operand.value, (int, float))
        and not isinstance(exp_node.operand.value, bool)
    ):
        if abs(exp_node.operand.value) > 1000:
            raise ValueError("거듭제곱 지수가 너무 큽니다(최대 1000).")
        return
    raise ValueError("거듭제곱 지수는 상수(-1000 ~ 1000)만 허용됩니다.")

def _strip_thousands_commas_safely(expr: str) -> str:
    """
    1) `min(100,200)`(공백 없는 2인자 함수), `min(1500000, 2000000)`, `round(x, 2)` 등 이미 유효한 파이썬 수식은
       단일 숫자 튜플(`1,500,000`)이 아닌 한 원형 그대로 보존하여 `min(100,200)`이 `min(100200)`으로 깨지는 현상을 원천 방지합니다.
    2) `min(1,500,000, 2,000,000)`이나 `1,500,000 * 0.15`처럼 천 단위 구분 쉼표가 섞여 있을 때는
       2그룹 이상 천 단위 숫자(`\d{1,3}(?:,\d{3}){2,}`)를 먼저 정제한 뒤 재검증하고, 필요시 나머지 천 단위 쉼표를 제거합니다.
    """
    s = (expr or "").strip()
    if not s:
        return ""

    # 1단계: 백만 단위 이상(쉼표 2개 이상: 1,500,000) 숫자는 무조건 천 단위 구분자이므로 최우선 제거
    s_clean = re.sub(r"(?<![\d.])\d{1,3}(?:,\d{3}){2,}(?![\d])", lambda m: m.group(0).replace(",", ""), s)
    # 2단계: 같은 괄호 안에 `, ` (쉼표+공백) 인자 구분자가 함께 존재할 때의 공백 없는 천 단위 쉼표(예: min(100,000, 200,000)) 제거
    if re.search(r",\s+", s_clean):
        s_clean = re.sub(r"(?<![\d.])\d{1,3}(?:,\d{3})+(?![\d])", lambda m: m.group(0).replace(",", ""), s_clean)
    try:
        tree = ast.parse(s_clean, mode="eval")
        if not isinstance(tree.body, ast.Tuple):
            return s_clean
    except SyntaxError:
        pass
    # 3단계: 괄호 밖 일반 사칙연산의 천 단위 쉼표(예: 100,000 * 0.15) 제거
    return re.sub(r"(?<![\d.])\d{1,3}(?:,\d{3})+(?![\d])", lambda m: m.group(0).replace(",", ""), s_clean)

def _validate_safe_math_ast(expr: str) -> None:
    """
    [AST 화이트리스트 보안 샌드박스]
    1) `().__class__.__base__` 등 모든 언더스코어(`_`) 속성 접근 및 허용되지 않은 AST 노드를 원천 차단합니다.
    2) `[1]*10**9`, `10**10000`, `pow(10, 10000)` 같은 메모리/CPU 고갈 수식을 AST 단계에서 차단합니다.
    """
    if len(expr) > 400:
        raise ValueError("수식이 너무 깁니다(400자 제한).")
    tree = ast.parse(expr, mode="eval")
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_AST_NODES):
            raise ValueError(f"허용되지 않는 수식 구문입니다: {type(node).__name__}")

        if isinstance(node, ast.Constant):
            if not isinstance(node.value, (int, float)) or isinstance(node.value, bool):
                raise ValueError(f"숫자 외의 상수는 허용되지 않습니다: {node.value!r}")

        if isinstance(node, ast.Name):
            if node.id.startswith("_") or (node.id not in _ALLOWED_CALC_FUNCS and node.id != "math"):
                raise ValueError(f"허용되지 않는 식별자입니다: {node.id}")

        if isinstance(node, ast.Attribute):
            if (
                not isinstance(node.value, ast.Name)
                or node.value.id != "math"
                or node.attr.startswith("_")
                or node.attr not in _ALLOWED_MATH_ATTRS
            ):
                raise ValueError(f"허용되지 않는 속성 접근입니다: {getattr(node, 'attr', '')}")

        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id not in _ALLOWED_CALC_FUNCS:
                    raise ValueError(f"허용되지 않는 함수 호출입니다: {node.func.id}")
                if node.func.id == "pow" and len(node.args) >= 2:
                    _check_safe_pow_exponent(node.args[1])
            elif isinstance(node.func, ast.Attribute):
                if (
                    not isinstance(node.func.value, ast.Name)
                    or node.func.value.id != "math"
                    or node.func.attr not in _ALLOWED_MATH_ATTRS
                ):
                    raise ValueError("허용되지 않는 모듈 함수 호출입니다.")
                if node.func.attr == "pow" and len(node.args) >= 2:
                    _check_safe_pow_exponent(node.args[1])
            else:
                raise ValueError("간접 함수 호출은 허용되지 않습니다.")

        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
            _check_safe_pow_exponent(node.right)

        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
            if isinstance(node.left, (ast.List, ast.Tuple)) or isinstance(node.right, (ast.List, ast.Tuple)):
                raise ValueError("리스트/튜플 곱셈은 허용되지 않습니다.")

def run_tax_calculator_for_gemini(formula_expression: str, description: str = "") -> str:
    """
    파이썬 사칙연산 수식(formula_expression)을 입력받아 단 1원의 오차 없이 정밀 계산합니다.
    - 숫자에는 천 단위 쉼표를 쓰지 말 것 (예: 1500000 * 0.15).
    - 함수 인자는 쉼표+공백으로 구분할 것 (예: min(1500000, 2000000), round(x, 2)).
    """
    _emit_live_status(f"🧮 2단계: 파이썬 1원 단위 정밀 수리 계산기 구동 중 ({description or formula_expression[:20]})...")
    print(f"\n[시스템] 🧮 파이썬 정밀 세액 계산기 가동: [{description}] 수식: {formula_expression}")
    allowed_names = {
        "abs": abs, "round": round, "min": min, "max": max, "sum": sum, "pow": pow,
        "int": int, "float": float, "math": math
    }
    try:
        clean_expr = _strip_thousands_commas_safely(formula_expression)
        _validate_safe_math_ast(clean_expr)
        result = eval(clean_expr, {"__builtins__": {}}, allowed_names)
        if isinstance(result, (int, float)):
            return _record(
                "detail",
                f"🧮 [정밀 계산 완료 - {description} | 수식: {clean_expr}]\n- 입력 수식: {clean_expr}\n- 정확한 산출값: {result:,.4f} (정수 반올림: {round(result):,}원)"
            )
        return _record("detail", f"🧮 [정밀 계산 완료 - {description} | 수식: {clean_expr}]\n- 결과: {str(result)[:300]}")
    except Exception as e:
        return f"❌ 수식 계산 오류 ({formula_expression}): {e} -> 숫자에 쉼표 없이 올바른 파이썬 사칙연산 수식으로 다시 호출하세요."

# 3. 에이전트 시스템 프롬프트 템플릿 (기존 12대 도구 라우팅 규칙 100% 보존 + 1턴 직행 병렬 조회 + 계산기 쉼표 예방 문구 결합)
SYSTEM_PROMPT = """당신은 세무·법령·회계·노무 검토 자율 전문 에이전트입니다.
사용자의 질문 성격에 따라 아래의 **[투트랙(Two-Track) 운영 프로토콜]**을 지능적으로 구분하여 작동하세요.

[투트랙(Two-Track) 운영 프로토콜 — 최우선 판단 기준]
- **📋 트랙 1 [전문 검토 보고서 모드]**: 세무·법령·회계·노무·4대보험에 관한 법리 검토, 요건 판정, 수당·세액·공제 계산, 기업 공시·실거래가·공시지가·사업자 상태 조회 등 **법령 검색이나 데이터/수식 계산이 필요한 모든 전문 질문**일 때 작동합니다. 반드시 먼저 제공된 도구(API)들을 사용하여 실제 원문 데이터와 통계를 확인한 뒤, **3번의 `<precheck>` 정식 3단 크로스체크 검수표를 한 글자도 축약 없이 먼저 작성하고 이어서 [1. 결론 -> 2. 내용 -> 3. 관련법령] 보고서 양식**으로 출력하세요.
- **💬 트랙 2 [자유 대화 및 실무 초안 모드]**: 사용자가 일상적인 대화·인사·브레인스토밍을 하거나, 직전 검토 결과를 바탕으로 **'거래처/고객 안내용 카톡·문자·이메일 초안 작성', '쉬운 요약 설명', '문장 다듬기', '일반 양식 작성'** 등을 요청한 경우에 작동합니다. 이때는 `<precheck>`나 보고서 양식, 대괄호 출처 태그([조문:...])를 모두 생략하고 자연스럽고 친절한 대화체나 사용자가 요청한 실무 양식(카톡/이메일 등)으로 자유롭게 답변하세요.
  * **[📱 카카오톡·문자 안내문 작성 시 절대 고정 규칙]**:
    1. **100% 순수 텍스트 전용**: 카카오톡에 복사·붙여넣기 했을 때 기호가 그대로 노출되지 않도록 별표(`**굵게**`), 샵(`### 제목`), 마크다운 표(`| --- |`), 꺾쇠(`>`) 등 마크다운 문법을 **절대 단 한 개도 쓰지 말고**, 오직 순수 텍스트와 대괄호 소제목(`[한줄 결론]` 등), 하이픈(`- `)만 사용할 것.
    2. **법령명·조문번호·판례번호 완전 제외**: `조세특례제한법 제29조의8`, `제1항`, `대법원 2020두...` 같은 법령명이나 조문번호, 사건번호는 **단 한 글자도 적지 말 것.**
    3. **초간단·쉬운 일상 용어 사용**: 세법을 전혀 모르는 거래처 대표님이 스마트폰으로 5초 만에 이해할 수 있도록 어려운 전문용어(상시근로자, 사후관리 추징, 손금불산입, 익금산입, 과세표준 등)를 모두 쉬운 일상 표현(전체 직원 수, 직원이 줄면 세금을 다시 내야 함, 비용 처리 불가 등)으로 바꿔서 짧고 단순하게(10~12줄 이내) 작성할 것.

[트랙 1 (전문 검토 보고서 모드) 필수 도구 호출 원칙]
- **[핵심 조문 조회 및 ⚡ 1턴 고속 직행 원칙]**: 세법·노동법·공단 규정 등 법령 질문은 **법률과 시행령(필요시 시행규칙)의 해당 조문을 모두** 원문으로 조회한 뒤 답변할 것. 특히 정식 법령명을 알고 있는 현행 법령(예: 조세특례제한법, 조세특례제한법 시행령, 법인세법, 소득세법, 부가가치세법, 상속세 및 증여세법, 국세기본법, 지방세법, 농어촌특별세법, 근로기준법 등)은 `search_law_for_gemini` 목록 검색을 거치지 말고 첫 턴에 바로 `get_law_details_for_gemini(doc_id='조세특례제한법', target='law', query_filter='제29조의8, 제127조, 제132조')`처럼 `doc_id`에 정식 법령명을 넣고 필요한 조문번호들을 `query_filter`에 쉼표로 묶어 한 번에 직행 조회할 것(법률과 시행령도 한 턴에 동시에 병렬 호출할 것). 도구 호출은 필요한 만큼 하되, **이미 결과를 받은 검색을 같은 검색어로 반복하지 말 것.**
- **[🕰️ 과거 귀속연도(경정청구·세무조사·구법) 조회 원칙]**: 질문에 특정 과거 연도나 과거 시점(예: '2021년 귀속', '2022년 양도분', '종전 규정')이 명시된 경우, 반드시 **`search_historical_law_for_gemini(law_name, target_date, query_filter)`** 도구를 호출하여 해당 과거 과세기간 당시에 시행되던 구법(연혁법령) 원문을 직접 대조할 것.
- 법령 검색(search_law_for_gemini, target='law')의 keyword에는 **법령명만** 넣을 것 (예: '소득세법', '근로기준법', '소득세법 시행령'). 주제어는 넣지 말 것.
- 조회한 원문에서 직접 확인하지 못한 금액·비율·연도는 단정하지 말고 **"(원문 미확인)"**이라고 표시할 것.
- **[근거 표시 의무 (트랙 1 전용)]** 전문 검토 보고서(1. 결론 ~ 3. 관련법령)를 작성할 때 판례·심판례·해석례·예규·법령 조문을 근거로 쓰는 문장 끝에는 반드시 아래 형식의 근거 표시를 붙일 것(콜론 ':'과 닫는 대괄호 ']'가 누락되지 않도록 주의).
  * 판례: [판례:2005두9415] / 조세심판: [심판례:조심2020서1234] / 법령해석례: [해석례:안건번호] / 예규·고시: [예규:문서명 또는 번호]
  * 법령 조문: [조문:법인세법 시행령 제89조] (반드시 정식 법령명과 콜론 ':' 포함. '동법', '같은 법' 사용 금지)
- **판례·심판례·해석례 인용 규칙**: 판결요지·결정요지를 서술하는 사건은 반드시 get_law_details_for_gemini(target='prec' 등)로 **원문을 조회한 사건만** 쓸 것. 목록 검색에서만 본 사건은 사건번호·선고일만 적고 "(요지 미조회)"로 표시할 것. **도구로 조회하지 않은 사건번호를 기억으로 적지 말 것.**
- **법령 조문 인용 규칙**: 전문 검토 보고서에 법령명과 함께 적는 조문(예: 「법인세법」 제52조)은 반드시 get_law_details_for_gemini 또는 search_historical_law_for_gemini로 **그 조문을 조회한 것만** 쓸 것. 조회하지 않은 조문이 필요하면 먼저 조회할 것.
- **답변에 시스템·도구·검증 절차·삭제 여부에 대한 언급을 절대 쓰지 말 것**. 근거가 부족하면 "관련 원문을 확인하지 못했다"고만 쓸 것.
- **법령명은 반드시 정식 명칭**으로 쓸 것 (예: 「상속세 및 증여세법」, 「조세특례제한법 시행령」, 「근로기준법」).
- **근거 표시는 그 문장의 내용이 실제로 해당 원문에 있을 때만** 붙일 것. 한 판례에 없는 내용을 그 판례 근거 표시로 묶지 말 것.
- **따옴표(“ ”) 인용은 조회한 원문을 글자 그대로 옮길 때만** 사용하고, 요약·의역할 때는 따옴표를 쓰지 말 것.
- **[수식 및 표 작성 규칙]**: 인쇄용 문서 출력 시 글자가 깨지는 LaTeX 수식 문법($$, $, \\frac, \\times, \\text 등)은 절대 사용하지 말고 일반 텍스트 기호(×, ÷, +, -, =)로만 깔끔하게 표기할 것. 마크다운 표를 작성할 때는 반드시 표 위아래로 빈 줄을 띄우고 헤더 구분선(| --- | --- |)을 정확히 작성할 것.
- 현행 법령·판례·심판례·예규·지방세조례 확인: 정식 법령명을 아는 현행 법령은 'get_law_details_for_gemini'(doc_id에 법령명, query_filter에 조문번호 입력)로 바로 읽고, 판례·심판례·예규·조례는 'search_law_for_gemini'로 ID를 찾은 뒤 'get_law_details_for_gemini'로 원문을 읽을 것.
- 과거 시점 구법(연혁법령) 원문 확인: 'search_historical_law_for_gemini' 호출.
- 기업 공시·재무·지분·배당·출자 확인: 'search_dart_corp_for_gemini' 호출.
- 사업자 상태(휴·폐업/과세유형) 및 진위확인: 'check_nts_biz_status_for_gemini' 또는 'verify_nts_biz_info_for_gemini' 호출.
- 부동산(아파트·오피스텔·상가·토지) 실거래가 확인: 'search_real_estate_trade_for_gemini' 호출.
- 부동산 개별공시지가 및 공동주택 공시가격(기준시가) 확인: 'search_official_land_price_for_gemini' 호출.
- 세액·공제액·수당·지분율 등 모든 숫자 계산: 반드시 'run_tax_calculator_for_gemini'를 호출하여 단 1원의 오차도 없이 정확히 계산할 것. (수식 내 숫자에는 천 단위 쉼표를 넣지 말고 `1500000 * 0.15`처럼 적으며, 함수 인자는 `min(1500000, 2000000)`처럼 쉼표+공백으로 구분할 것)

1. 자료 검토 우선순위 및 기준
- 1순위 (법령 및 자치법규/행정규칙): 국가법령정보센터 기준 가장 최근 개정된 [법률 / 시행령 / 시행규칙 / 지방세 조례 / 행정규칙(고시·훈령)]을 최우선 기준으로 삼되, 과거 귀속연도 사안은 해당 과세기간 시행 연혁법령(구법)을 대조할 것.
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
- **[🔄 최근 개정 조문 자동 신·구 비교 원칙]**: 만약 조회한 핵심 조문에 최근 개정사항(2025~2026년 개정·신설 또는 시행예정 규정)이 포함되어 있거나 과거 구법과 현행법을 비교하는 질의라면, 별도 요청이 없더라도 본 항목 안에 반드시 **`| 구분 | 종전 규정(구법) | 현행(개정) 규정 | 적용시기 및 실무 영향 |`** 형식의 마크다운 신·구 비교표를 포함하여 무엇이 바뀌었는지 한눈에 보이도록 정리할 것.

#### (2) 계산
- 정밀 계산기(run_tax_calculator_for_gemini)로 산출한 단계별 계산 과정 및 산출 내역 (※ 단, 질문에 세액·수당·비율 등 수치 계산 내용이 전혀 없는 단순 법리 질의라면 이 '(2) 계산' 소제목과 항목은 완전히 생략하고 바로 아래 항목을 '(2) 실무 적용 및 리스크 주의사항'으로 당겨서 작성할 것)

#### (3) 실무 적용 및 리스크 주의사항
- 가산세 및 사후관리(고용감소 추징 등) 리스크, 최저한세·농어촌특별세·중복공제 배제 여부, 소득처분·지방소득세 등 연쇄 세목 영향, 증빙 수취 요건, 홈택스/위택스 신고 시 주의할 점 정리 (※ 위 계산 항목이 생략된 경우 '(2) 실무 적용 및 리스크 주의사항'으로 번호를 맞춰 기재할 것)

---

### 3. 관련법령
- 이번 검토에서 실제 원문을 조회한 법령·조문·판례·예규만 나열하되, 하위 항목에「법령명」 제N조(조문제목) 또는 사건번호를 명확히 기재할 것
  * 국가법령정보센터(법령·판례·심판례·조례·기본통칙): https://www.law.go.kr
  * 금융감독원 전자공시시스템(DART): https://dart.fss.or.kr
  * 국토교통부 실거래가 공개시스템 / 브이월드(공시가격): https://rt.molit.go.kr / https://www.vworld.kr
  * 한국은행 경제통계시스템(ECOS): https://ecos.bok.or.kr
  * 국세청 홈택스(사업자상태/업종코드): https://www.hometax.go.kr
"""

def _extract_and_strip_precheck(text: str) -> tuple[str, str]:
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
    """
    [속도 개선 ⑤ — 무손실 정밀 판정]
    - <precheck> 3단 자기검열(120자 이상 + 1·2·3단 필수 점검)은 이전과 100% 동일하게 강제하여 할루시네이션 차단력을 완벽히 유지합니다.
    - 다만 비계산 법리 질의에서 모델이 3단에 '기한', '가산세', '해당 없음' 등의 표현을 썼을 때 억울하게 부실 판정되어
      멀쩡한 보고서를 통째로 다시 쓰던(15~25초 지연) 오탐(False Positive)만 제거했습니다.
    """
    if not precheck_body or len(precheck_body.strip()) < 120:
        return False
    has_step1 = any(k in precheck_body for k in ("1단", "원문", "법령", "조문", "개정", "일몰", "귀속"))
    has_step2 = any(k in precheck_body for k in ("2단", "단서", "예외", "배제", "최저한세", "농어촌", "농특세", "사후관리", "소득처분", "요건"))
    has_step3 = any(k in precheck_body for k in ("3단", "검산", "계산", "수치", "기한", "가산세", "지방소득세", "세율", "공제액", "산출"))
    return bool(has_step1 and has_step2 and has_step3)

def _is_valid_report_body(text: str) -> bool:
    """재작성 응답이 '알겠습니다' 같은 짧은 대답일 때 기존 보고서를 덮어쓰지 않도록 검증합니다."""
    if not text or len(text.strip()) < 250:
        return False
    return bool(re.search(r"###\s*1\.\s*결론|###\s*2\.\s*내용", text))

# ---------------------------------------------------------
# 🔗 검증 완료된 법령·판례·심판례·해석례·예규·기본통칙 100% 원클릭 직링크 자동 결합 엔진
#    (괄호가 포함된 판례·해석례 URL 생성 시 `%28`, `%29` 인코딩으로 마크다운/PDF/워드 괄호 잔류 원천 방지)
# ---------------------------------------------------------
def _build_direct_law_url(kind: str, val: str, trace: dict, rev_id_map: dict, meta_map: dict) -> str:
    """검증된 태그 종류와 값으로부터 국가법령정보센터 공식 원문 직링크 URL을 생성합니다."""
    if kind == "조문":
        refs = _find_article_refs(val, trace)
        if refs:
            law_name, jo, gaji = refs[0]
            art_str = f"제{jo}조" + (f"의{gaji}" if gaji else "")
            return f"https://www.law.go.kr/법령/{urllib.parse.quote(law_name)}/{urllib.parse.quote(art_str)}"
    elif kind == "판례":
        nos = _find_case_numbers(val)
        if nos:
            c_no = nos[0]
            seq_id = meta_map.get(("prec", _norm(c_no))) or rev_id_map.get(_norm(c_no))
            if seq_id:
                return f"https://www.law.go.kr/LSW/precInfoP.do?precSeq={seq_id}"
            return f"https://www.law.go.kr/판례/%28{urllib.parse.quote(c_no)}%29"
    elif kind == "심판례":
        nos = _find_case_numbers(val)
        if nos:
            c_no = nos[0]
            seq_id = meta_map.get(("decc", _norm(c_no))) or rev_id_map.get(_norm(c_no))
            if seq_id:
                return f"https://www.law.go.kr/LSW/deccInfoP.do?deccSeq={seq_id}"
            return f"https://www.law.go.kr/LSW/lsSc.do?query={urllib.parse.quote(c_no)}"
    elif kind == "해석례":
        clean_no = val.split()[0].strip()
        seq_id = meta_map.get(("expc", _norm(clean_no))) or meta_map.get(("expc", _norm(val)))
        if seq_id:
            return f"https://www.law.go.kr/LSW/expcInfoP.do?expcSeq={seq_id}"
        return f"https://www.law.go.kr/법령해석례/%28{urllib.parse.quote(clean_no)}%29"
    elif kind == "예규":
        clean_name = re.sub(r"\s+", "", val)
        seq_id = meta_map.get(("admrul", _norm(val)))
        if seq_id:
            return f"https://www.law.go.kr/LSW/admRulInfoP.do?admRulSeq={seq_id}"
        return f"https://www.law.go.kr/행정규칙/{urllib.parse.quote(clean_name)}"
    return ""

def _inject_direct_law_links(text: str, trace: dict = None) -> str:
    """
    1) 본문의 [조문:...], [판례:...], [심판례:...], [해석례:...], [예규:...] 태그(콜론 누락 포함)에 100% 검증된 법제처 원문 직링크를 결합합니다.
    2) '### 3. 관련법령' 섹션의 모든 하위 조문 줄 및 기본통칙 줄을 클릭하면 즉시 해당 법제처 조문·기본통칙 원문 페이지로 이동하도록 글자 자체에 직링크를 걸어줍니다.
    """
    if not text:
        return ""

    text = _normalize_citation_tags(text)

    rev_id_map = {}
    meta_map = {}
    if trace:
        for doc_id, case_no in (trace.get("id_map") or {}).items():
            rev_id_map[_norm(case_no)] = str(doc_id).strip()
        meta_map = trace.get("meta_map") or {}

    def _replace_tag_with_link(match: re.Match) -> str:
        kind = match.group(1).strip()
        val = match.group(2).strip()
        canonical_tag = f"[{kind}: {val}]"
        url = _build_direct_law_url(kind, val, trace, rev_id_map, meta_map)
        if url:
            return f"[{canonical_tag}]({url})"
        return canonical_tag

    lines = text.split("\n")
    in_refs = False
    known_titles = _known_law_titles(trace)
    base_tax_laws = sorted(_COMMON_LAWS, key=len, reverse=True)
    out_lines = []

    for line in lines:
        s = line.strip()
        if s.startswith("#"):
            in_refs = ("관련법령" in s) or ("관련 법령" in s) or ("근거 자료" in s) or ("근거자료" in s)
            out_lines.append(line)
            continue

        if not in_refs:
            linked_line = re.sub(
                r"(?<!\[)\[(판례|심판례|해석례|예규|조문)(?:\s*[:：]\s*|\s*)(?=[가-힣A-Za-z0-9「])([^\]]+)\](?!\()",
                _replace_tag_with_link,
                line
            )
            out_lines.append(linked_line)
            continue

        if s:
            m_bullet = re.match(r"^(\s*(?:[-*•◦‣]|\d+\.)\s+)(.+)$", line)
            if m_bullet and "](" not in line and "http://" not in line and "https://" not in line:
                prefix_bullet, item_body = m_bullet.group(1), m_bullet.group(2).strip()
                clean_item_body = re.sub(
                    r"\s*\[(?:판례|심판례|해석례|예규|조문)(?:\s*[:：]\s*|\s*)(?=[가-힣A-Za-z0-9「])[^\]]+\]\s*$",
                    "",
                    item_body
                ).strip() or item_body
                direct_url = ""
                compact_body = _norm(item_body)

                if "기본통칙" in compact_body:
                    matched_base_law = ""
                    for blaw in base_tax_laws:
                        if blaw in compact_body:
                            matched_base_law = blaw
                            break
                    if not matched_base_law:
                        for alias, full in _LAW_ALIASES.items():
                            if alias in compact_body:
                                matched_base_law = full
                                break
                    if matched_base_law:
                        rule_title = f"{matched_base_law}기본통칙"
                        direct_url = f"https://www.law.go.kr/행정규칙/{urllib.parse.quote(rule_title)}"

                if not direct_url:
                    art_refs = _find_article_refs(item_body, trace)
                    if art_refs:
                        law_name, jo, gaji = art_refs[0]
                        art_str = f"제{jo}조" + (f"의{gaji}" if gaji else "")
                        direct_url = f"https://www.law.go.kr/법령/{urllib.parse.quote(law_name)}/{urllib.parse.quote(art_str)}"

                if not direct_url:
                    case_nos = _find_case_numbers(item_body)
                    if case_nos:
                        c_no = case_nos[0]
                        if ("조심" in item_body) or ("국심" in item_body) or ("심판" in item_body):
                            seq_id = meta_map.get(("decc", _norm(c_no))) or rev_id_map.get(_norm(c_no))
                            if seq_id:
                                direct_url = f"https://www.law.go.kr/LSW/deccInfoP.do?deccSeq={seq_id}"
                            else:
                                direct_url = f"https://www.law.go.kr/LSW/lsSc.do?query={urllib.parse.quote(c_no)}"
                        else:
                            seq_id = meta_map.get(("prec", _norm(c_no))) or rev_id_map.get(_norm(c_no))
                            if seq_id:
                                direct_url = f"https://www.law.go.kr/LSW/precInfoP.do?precSeq={seq_id}"
                            else:
                                direct_url = f"https://www.law.go.kr/판례/%28{urllib.parse.quote(c_no)}%29"

                if not direct_url:
                    for t in known_titles:
                        if t in compact_body:
                            direct_url = f"https://www.law.go.kr/법령/{urllib.parse.quote(t)}"
                            break

                if direct_url:
                    line = f"{prefix_bullet}[{clean_item_body}]({direct_url})"
                else:
                    line = re.sub(
                        r"(?<!\[)\[(판례|심판례|해석례|예규|조문)(?:\s*[:：]\s*|\s*)(?=[가-힣A-Za-z0-9「])([^\]]+)\](?!\()",
                        _replace_tag_with_link,
                        line
                    )

        out_lines.append(line)

    return "\n".join(out_lines)

def _clean_latex_for_export(text: str) -> str:
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
    s = re.sub(
        r"(\[(?:조문|판례|심판례|해석례|예규)(?:\s*[:：]\s*|\s+)(?=[가-힣A-Za-z0-9「])[^\]\n(]+?)\s+(\()(?![^\n\[]*\])",
        r"\1] \2",
        s
    )
    s = _normalize_citation_tags(s)
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
    timeout_ms = 120000 if unleash else 60000
    max_remote_calls = 30 if unleash else 20

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
        _emit_live_status(f"🔎 1단계: 질의 쟁점 분석 및 법제처·공공기관 DB 탐색 중 ({model_id})...")
        response = chat.send_message(user_input)
        raw_output = extract_safe_text(response)
        trace = _TOOL_TRACE.get()

        tool_res_chars = sum(len(x) for x in trace["list"]) + sum(len(x) for x in trace["detail"])
        tool_call_cnt = sum(trace["counts"].values())
        _extract_and_log_response_usage(
            response, model_id, count_call=True,
            est_in_chars=len(user_input) + len(dynamic_prompt),
            est_out_chars=len(raw_output),
            tool_calls_count=tool_call_cnt,
            tool_result_chars=tool_res_chars
        )

        if not raw_output:
            follow_up = chat.send_message(
                "지금까지 조회한 법령 조문과 계산 결과를 바탕으로 추가 도구 호출 없이 즉시 <precheck> 3단 크로스체크(최소 200자 이상)를 먼저 작성한 뒤 [1. 결론 -> 2. 내용 -> 3. 관련법령] 순서로 답변을 작성해 주세요."
            )
            raw_output = extract_safe_text(follow_up)
            _extract_and_log_response_usage(follow_up, model_id, count_call=False, est_in_chars=500, est_out_chars=len(raw_output))
    finally:
        _TOOL_TRACE.reset(trace_token)

    if not raw_output:
        raise ValueError("빈 응답이 반환되었습니다.")

    stripped_body, precheck_text = _extract_and_strip_precheck(raw_output)
    is_formal_report = bool(re.search(r"###\s*1\.\s*결론|###\s*2\.\s*내용|###\s*3\.\s*관련법령", stripped_body))

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
                if _is_valid_report_body(s_body2):
                    raw_output = p_raw
                    stripped_body = s_body2
                    if p_text2:
                        precheck_text = p_text2
                    response = p_resp
                elif p_text2 and not precheck_text:
                    precheck_text = p_text2
        except Exception as e:
            print(f"[시스템]    ↳ 3단 크로스체크 재작성 호출 오류: {e}")
        finally:
            _TOOL_TRACE.reset(trace_token_p)

    if precheck_text:
        print(f"\n[시스템] 🛡️ 사전 3단 크로스체크 정밀 수행 완료 ({len(precheck_text):,}자):\n{precheck_text}")

    final_text = re.sub(r"\s*<br\s*/?>\s*", " / ", stripped_body)
    final_text = _clean_latex_for_export(final_text)

    citation_note = ""

    if is_formal_report and trace is not None:
        _emit_live_status("🛡️ 3단계: 미조회 근거 강제 차단(_scan_violations) 검증 중...")
        violations = _scan_violations(final_text, trace)
        if violations:
            has_body_violation = any(not in_refs for _, _, in_refs in violations)
            first_labels = _violation_labels(violations)

            if has_body_violation:
                print(f"[시스템] 🔒 본문 미검증 근거 {len(first_labels)}건 감지 → 재작성 요청: {first_labels[:8]}")
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
                    retry_body, retry_precheck = _extract_and_strip_precheck(retry_text)
                    if _is_valid_report_body(retry_body):
                        if retry_precheck:
                            precheck_text = retry_precheck
                        final_text = re.sub(r"\s*<br\s*/?>\s*", " / ", retry_body)
                        final_text = _clean_latex_for_export(final_text)
                        response = retry_resp

            remaining = _scan_violations(final_text, trace)
            if remaining:
                final_text = _redact_lines(final_text, remaining)
                short = [r.split(":")[0] if r.startswith(("출처 표시 없는", "판례 인용문")) else r for r in _violation_labels(remaining)]
                short = list(dict.fromkeys(short))
                citation_note = (f"\n> 🚫 미검증 근거 후처리({_verify_mode()} 모드): "
                                 + "; ".join(short[:10]))
            else:
                citation_note = ("\n> 🔒 미검증 근거가 감지되어 **재작성**(원문 조회 또는 삭제)했습니다. (최초 감지 "
                                 + str(len(first_labels)) + "건)")
        else:
            citation_note = "\n> ✅ 답변의 판례·조문·예규 근거가 모두 이번 조회 기록과 일치합니다."

        if SEMANTIC_VERIFY_ON and (trace["list"] or trace["detail"]):
            claims, sources = _extract_claims(final_text, trace)
            if claims:
                print(f"[시스템] 🧪 의미 검증 가동: 주장 {len(claims)}건 / 원문 {len(sources)}건")
                try:
                    verdicts = _semantic_verify(api_key, claims, sources, user_input)
                    final_text, cnt = _apply_semantic_results(final_text, claims, verdicts, sources)
                    citation_note += (f"\n> 🧪 의미 검증 {len(claims)}건: 일치 {cnt['supported']} · "
                                      f"원문 확인 필요 {cnt['partial']} · 불일치 {cnt['unsupported']}"
                                      + (f" · 판정 누락 {cnt['unknown']}" if cnt.get("unknown") else ""))
                except Exception as e:
                    print(f"[시스템]    ↳ 의미 검증 실패: {e}")
                    citation_note += "\n> 🧪 의미 검증을 수행하지 못했습니다(검증 모델 오류). 근거 표시 문장은 직접 확인하세요."

        final_text = _inject_direct_law_links(final_text, trace)

    elif trace is not None:
        final_text = _strip_fake_cases_in_track2(final_text, trace, user_input)

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

# 4. 실행 순서(유료키 전용):
#    - Flash 모드: gemini-3.8-flash → gemini-3.6-flash → gemini-3.5-flash-lite → gemini-2.5-flash
#    - Pro 심층 모드(1번 아르곤 직결): gemini-4-argon → gemini-3.1-pro-preview-customtools → gemini-3.1-pro-preview → gemini-2.5-pro
def run_agent(user_input: str, raw_query: str = "", has_file: bool = False, room_key: str = "", status_callback=None) -> str:
    live_pool = get_live_gemini_key_pool()
    if not live_pool:
        return "❌ 설정된 Gemini 유료 API 키가 없습니다. .env 또는 Streamlit Secrets에 GEMINI_PAID_KEY를 넣어 주세요."

    rk_token = set_active_room_key(room_key) if room_key else None
    cb_token = set_live_status_callback(status_callback) if status_callback else None
    try:
        query_for_routing = raw_query if raw_query else user_input
        tier_mode, mode_badge, recommend_pro_notice = select_optimal_model(
            user_query=query_for_routing,
            has_file=has_file,
            full_input_len=len(user_input)
        )
        unleash_mode = (tier_mode == "PRO")

        today_str = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y년 %m월 %d일")
        unleash_guide = (
            "\n[🚀 PRO/ARGON 3배 리미트 해제 모드 가동 중: 법령 검색 최대 21회, 원문 조회 최대 36회, 판례·심판례·예규 조회 최대 6~9회, "
            "원문 길이 최대 60,000자까지 한도가 3배 확장되었습니다. 관련 법령 조문과 판례·예규의 구체적 사실관계(이유)까지 빠짐없이 깊이 있게 대조하여 작성하세요.]\n"
            if unleash_mode else ""
        )
        dynamic_prompt = (
            f"[시스템 기준일 안내: 오늘 날짜는 {today_str}입니다. 질문에 등장하는 연도와 날짜의 과거/현재 여부를 반드시 오늘 날짜({today_str}) 기준으로 판단하세요.]"
            f"{unleash_guide}\n\n" + SYSTEM_PROMPT
        )

        tools_list = [
            search_law_for_gemini,
            get_law_details_for_gemini,
            search_historical_law_for_gemini,
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

        flash_candidates = list(dict.fromkeys([FLASH_MODEL_ID, FLASH_BACKUP_ID, FLASH_LITE_ID, FLASH_FALLBACK_ID]))
        execution_plan = []
        for lbl, k in live_pool:
            if tier_mode == "PRO":
                for m in dict.fromkeys(PAID_PRO_MODEL_IDS):
                    execution_plan.append((lbl, k, m, f"{mode_badge} *(🔑 {lbl} · {m})*"))
                for m in flash_candidates:
                    execution_plan.append((lbl, k, m, f"⚡ **[Pro 실패 → Flash 백업 (3배 리미트 개방 유지)]** *(🔑 {lbl} · {m})*"))
            else:
                for m in flash_candidates:
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
                        time.sleep(1.5)
                        continue
                    break

        return f"❌ 모든 API 키 호출이 실패했습니다. 마지막 오류: {str(last_error)}"
    finally:
        if cb_token is not None:
            _LIVE_STATUS_CB.reset(cb_token)
        if rk_token is not None:
            _ACTIVE_ROOM_KEY.reset(rk_token)