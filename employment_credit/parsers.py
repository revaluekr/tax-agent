# -*- coding: utf-8 -*-
"""
업로드 자료 분류 및 정보 추출

- 파일 종류 분류: 파일명·본문 키워드로 먼저 판정 (AI 미사용)
- 내용 추출: Gemini가 서류에서 값을 JSON으로 '읽어오기'만 함
- 주민등록번호: AI에는 앞 7자리만 받게 하고, 생년월일·내외국인 판정은 파이썬이 한 뒤 버림
"""
from __future__ import annotations

import json
import re
from datetime import date

from . import rules as R
from .headcount import parse_date

MAX_TEXT_CHARS = 120_000


# ══════════════════════════════════════════════════════════════════
# 1. 파일 종류 분류 (키워드)
# ══════════════════════════════════════════════════════════════════
def classify_file(name: str, text: str) -> str | None:
    n = (name or "").replace(" ", "")
    head = (text or "")[:3000].replace(" ", "")
    both = n + " " + head

    if "원천징수부" in both or ("원천징수" in n and "근로" in both):
        for y in ("2026", "2025", "2024"):
            if y in n:
                return f"wht_{y}"
        m = re.search(r"(?:귀속연도|귀속년도|과세연도)[^0-9]{0,6}(20\d\d)", head)
        if m and m.group(1) in ("2026", "2025", "2024"):
            return f"wht_{m.group(1)}"
        return None
    if any(k in both for k in ("상시근로자명세", "통합고용", "세액공제신청서", "공제세액계산서")):
        return "prev_filing"
    if "주주명부" in both or ("주주" in n):
        return "shareholder"
    if "사업자등록증" in both or "사업자등록" in n:
        return "biz_reg"
    if "등기" in both or "등본" in n:
        return "corp_reg"
    return None


# ══════════════════════════════════════════════════════════════════
# 2. Gemini 호출 (JSON 전용)
# ══════════════════════════════════════════════════════════════════
def call_gemini_json(instruction: str, text: str, log_tokens_fn=None, room_key: str = "") -> dict:
    """앱의 유료키·모델 설정을 그대로 사용. 실패하면 빈 dict."""
    try:
        import agent
        from google import genai
        from google.genai import types
    except Exception:
        return {}

    keys = agent.get_live_gemini_key_pool()
    models = [m for m in (getattr(agent, "FLASH_MODEL_ID", None), getattr(agent, "FLASH_BACKUP_ID", None),
                          getattr(agent, "FLASH_FALLBACK_ID", "gemini-2.5-flash")) if m]
    prompt = (instruction + "\n\n규칙: JSON만 출력하고 설명·마크다운은 쓰지 마세요. "
              "서류에 없는 값은 지어내지 말고 빈 문자열(\"\")이나 null로 두세요.\n\n[서류 내용]\n"
              + (text or "")[:MAX_TEXT_CHARS])

    for _, key in keys:
        client = genai.Client(api_key=key)
        for model_id in models:
            try:
                resp = client.models.generate_content(
                    model=model_id,
                    contents=prompt,
                    config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0),
                )
                um = getattr(resp, "usage_metadata", None)
                if log_tokens_fn and um:
                    log_tokens_fn(model_id, int(um.prompt_token_count or 0),
                                  int(um.candidates_token_count or 0), True, room_key)
                raw = (resp.text or "").strip()
                raw = re.sub(r"^```(?:json)?|```$", "", raw).strip()
                return json.loads(raw)
            except Exception:
                continue
    return {}


# ══════════════════════════════════════════════════════════════════
# 3. 서류별 추출
# ══════════════════════════════════════════════════════════════════
PROMPT_BIZ = """다음은 사업자등록증입니다. 아래 형식으로 값을 읽어주세요.
{"상호":"", "사업자번호":"000-00-00000", "개업일":"YYYY-MM-DD", "법인등록번호앞6자리":"", "대표자":"",
 "업태":"", "종목":"", "사업장소재지":""}"""

PROMPT_CORP = """다음은 법인 등기부등본입니다. 아래 형식으로 읽어주세요. 임원은 현재 재임 중인 사람만 넣으세요.
{"상호":"", "설립일":"YYYY-MM-DD", "본점":"", "임원":[{"성명":"", "직위":"대표이사|사내이사|감사 등"}]}"""

PROMPT_SH = """다음은 주주명부입니다. 아래 형식으로 읽어주세요. 관계는 서류에 적힌 그대로(본인/배우자/자/부/모/형제 등),
없으면 빈 문자열로 두세요.
{"주주":[{"성명":"", "지분율":0.0, "관계":""}]}"""

PROMPT_WHT = """다음은 소득자별 근로소득원천징수부입니다. 근로자별로 아래 형식으로 읽어주세요.
주민등록번호는 앞 6자리와 뒷자리 첫 1자리만 '000000-0' 형태로 적고 나머지는 절대 적지 마세요.
월급여는 1월~12월 지급액(과세+비과세 합계, 숫자) 12개를 순서대로, 지급이 없으면 0으로 넣으세요.
{"근로자":[{"성명":"", "주민번호7":"000000-0", "입사일":"YYYY-MM-DD", "퇴사일":"YYYY-MM-DD 또는 빈칸",
  "월급여":[0,0,0,0,0,0,0,0,0,0,0,0]}]}"""

PROMPT_PREV = """다음은 이미 신고한 통합고용세액공제 관련 서식(상시근로자 명세서·공제세액계산서)입니다.
연도별 상시근로자 수와 청년등상시근로자 수를 읽어주세요. 서식에 적힌 연도와 숫자만 그대로 옮기세요.
{"연도별":{"2024":{"상시":null,"청년등":null}, "2025":{"상시":null,"청년등":null}},
 "공제적용연도":"서식상 최초공제 귀속연도(있으면)", "공제세액":null}"""


def birth_from_rrn7(rrn7: str) -> tuple[date | None, bool]:
    """'900101-1' → (1990-01-01, 외국인여부)"""
    d = re.sub(r"[^0-9]", "", rrn7 or "")
    if len(d) < 7:
        return None, False
    yy, mm, dd, g = int(d[:2]), int(d[2:4]), int(d[4:6]), int(d[6])
    century = {1: 1900, 2: 1900, 5: 1900, 6: 1900, 3: 2000, 4: 2000, 7: 2000, 8: 2000, 9: 1800, 0: 1800}[g]
    try:
        return date(century + yy, mm, dd), g in (5, 6, 7, 8)
    except ValueError:
        return None, g in (5, 6, 7, 8)


def _num(v) -> float:
    try:
        return float(str(v).replace(",", "")) if v not in (None, "") else 0.0
    except ValueError:
        return 0.0


def _iso(v) -> str:
    d = parse_date(v)
    return d.isoformat() if d else ""


def extract_all(doc_texts: dict[str, str], log_tokens_fn=None, room_key: str = "") -> dict:
    """doc_texts: {"biz_reg": "...", "wht_2026": "...", ...} → 정리된 추출 결과"""
    out = {"biz": {}, "corp": {}, "shareholders": [], "wht": {}, "prev_filing": {}}

    if doc_texts.get("biz_reg"):
        out["biz"] = call_gemini_json(PROMPT_BIZ, doc_texts["biz_reg"], log_tokens_fn, room_key) or {}
    if doc_texts.get("corp_reg"):
        out["corp"] = call_gemini_json(PROMPT_CORP, doc_texts["corp_reg"], log_tokens_fn, room_key) or {}
    if doc_texts.get("shareholder"):
        out["shareholders"] = (call_gemini_json(PROMPT_SH, doc_texts["shareholder"], log_tokens_fn, room_key)
                               or {}).get("주주", []) or []
    for y in ("2026", "2025", "2024"):
        if doc_texts.get(f"wht_{y}"):
            res = call_gemini_json(PROMPT_WHT, doc_texts[f"wht_{y}"], log_tokens_fn, room_key) or {}
            rows = []
            for e in res.get("근로자", []) or []:
                birth, foreign = birth_from_rrn7(e.get("주민번호7", ""))
                pay = [_num(x) for x in (e.get("월급여") or [])][:12]
                rows.append({
                    "성명": (e.get("성명") or "").strip(),
                    "생년월일": birth.isoformat() if birth else "",
                    "외국인": foreign,
                    "입사일": _iso(e.get("입사일")),
                    "퇴사일": _iso(e.get("퇴사일")),
                    "월급여": pay + [0.0] * (12 - len(pay)) if pay else None,
                })
            out["wht"][y] = rows
    if doc_texts.get("prev_filing"):
        out["prev_filing"] = call_gemini_json(PROMPT_PREV, doc_texts["prev_filing"], log_tokens_fn, room_key) or {}
    return out


# ══════════════════════════════════════════════════════════════════
# 4. 추출 결과 → 사업자정보·사원 DB
# ══════════════════════════════════════════════════════════════════
def build_biz_info(ext: dict, tax_year: int) -> tuple[dict, list[str]]:
    """반환: (사업자정보, 서류로 확인된 항목 목록)"""
    biz, corp = ext.get("biz") or {}, ext.get("corp") or {}
    info, confirmed = {}, []

    def put(field, *vals):
        for v in vals:
            if v not in (None, ""):
                info[field] = str(v).strip()
                confirmed.append(field)
                return
        info[field] = ""

    put("상호", biz.get("상호"), corp.get("상호"))
    put("설립일", corp.get("설립일"), biz.get("개업일"))
    put("사업자번호", biz.get("사업자번호"))
    put("업태", biz.get("업태"))
    put("종목", biz.get("종목"))
    put("사업장소재지", biz.get("사업장소재지"), corp.get("본점"))

    from .headcount import default_months_for_year
    founded = parse_date(info.get("설립일"))
    info["당해_월수"] = default_months_for_year(tax_year, founded)
    info["전년_월수"] = default_months_for_year(tax_year - 1, founded)
    info["전전년_월수"] = default_months_for_year(tax_year - 2, founded)
    info["기업구분"] = "중소기업"
    return info, confirmed


def _shareholder_relations(shareholders: list[dict]) -> dict[str, str]:
    """성명 → 최대주주 / 최대주주의 배우자 / 최대주주의 직계존비속 등"""
    if not shareholders:
        return {}
    top = max(shareholders, key=lambda s: _num(s.get("지분율")))
    rel_map = {(top.get("성명") or "").strip(): "최대주주"}
    for s in shareholders:
        nm, rel = (s.get("성명") or "").strip(), (s.get("관계") or "").replace(" ", "")
        if not nm or nm in rel_map:
            continue
        if "배우자" in rel or rel in ("처", "남편", "부인"):
            rel_map[nm] = "최대주주의 배우자"
        elif rel and rel not in ("본인", "타인", "기타"):
            rel_map[nm] = "최대주주의 직계존비속 등"
    return rel_map


def build_people(ext: dict, years: list[int]) -> tuple[dict, dict]:
    """
    반환: people {pid: 사람정보}, year_recs {연도: {pid: 연도별 입력값}}
    같은 사람은 (성명, 생년월일)로 묶어 한 번만 보관합니다.
    """
    people: dict[str, dict] = {}
    rel_map = _shareholder_relations(ext.get("shareholders") or [])
    execs = {(e.get("성명") or "").strip(): (e.get("직위") or "")
             for e in ((ext.get("corp") or {}).get("임원") or [])}

    for y in sorted(ext.get("wht", {}).keys()):
        for e in ext["wht"][y]:
            if not e["성명"]:
                continue
            pid = f"{e['성명']}|{e['생년월일']}"
            p = people.setdefault(pid, {
                "pid": pid, "성명": e["성명"], "생년월일": e["생년월일"], "입사일": "", "퇴사일": "",
                "외국인": e.get("외국인", False), "병역개월": 0, "월급여": {}, "_confirmed": ["성명"],
            })
            if e["생년월일"] and "생년월일" not in p["_confirmed"]:
                p["_confirmed"].append("생년월일")
            for f in ("입사일", "퇴사일"):
                if e.get(f):
                    p[f] = e[f]                       # 최근 연도 값이 우선
                    if f not in p["_confirmed"]:
                        p["_confirmed"].append(f)
            if e.get("월급여"):
                p["월급여"][y] = e["월급여"]
            if e["성명"] in rel_map:
                p["주주관계"] = rel_map[e["성명"]]

    year_recs = {y: {} for y in years}
    for pid, p in people.items():
        pos = execs.get(p["성명"], "")
        emp = R.EMP_CEO if "대표" in pos else (R.EMP_EXEC if pos else R.EMP_REGULAR)
        for y in years:
            year_recs[y][pid] = new_year_rec(emp, confirmed_emp=bool(pos))
    return people, year_recs


def new_year_rec(emp_type: str = R.EMP_REGULAR, confirmed_emp: bool = False) -> dict:
    return {
        "고용유형": emp_type,
        "제외사유": "",
        "청년등": "",
        "상시_override": "",
        "월_override": {},
        "_user_set": [],
        "_confirmed": ["고용유형"] if confirmed_emp else [],
        "_unlocked": False,
    }


# ══════════════════════════════════════════════════════════════════
# 5. [다음] 버튼 경고 — 코드 판정 + AI 보충
# ══════════════════════════════════════════════════════════════════
def check_missing(classified: dict[str, list[str]], ext: dict | None, tax_year: int) -> list[str]:
    """파일 누락·핵심 항목 누락은 코드로 확정 판정"""
    msgs = []
    for key, label, required, _ in R.DOC_TYPES:
        if required and not classified.get(key):
            msgs.append(f"{label} 자료가 없습니다.")
    if ext:
        for y in (str(tax_year), str(tax_year - 1)):
            rows = ext.get("wht", {}).get(y)
            if rows is not None and not rows:
                msgs.append(f"{y}년 원천징수부에서 근로자를 한 명도 읽지 못했습니다.")
            elif rows:
                no_hire = [r["성명"] for r in rows if not r.get("입사일")]
                if no_hire:
                    msgs.append(f"{y}년 원천징수부에 입사일 정보가 없는 근로자가 {len(no_hire)}명 있습니다 "
                                f"({', '.join(no_hire[:5])}{' 외' if len(no_hire) > 5 else ''}).")
                no_birth = [r["성명"] for r in rows if not r.get("생년월일")]
                if no_birth:
                    msgs.append(f"{y}년 원천징수부에서 생년월일을 확인하지 못한 근로자가 {len(no_birth)}명 있습니다.")
        if not (ext.get("biz") or {}).get("업태") and classified.get("biz_reg"):
            msgs.append("사업자등록증에서 업태·종목을 읽지 못했습니다.")
    return msgs


def ai_extra_warnings(ext: dict, log_tokens_fn=None, room_key: str = "") -> list[str]:
    """코드가 못 잡는 '내용상 부족한 점'만 AI가 짧게 안내 (최대 3개)"""
    summary = {
        "사업자": ext.get("biz"), "등기": {k: v for k, v in (ext.get("corp") or {}).items() if k != "임원"},
        "주주수": len(ext.get("shareholders") or []),
        "연도별_근로자수": {y: len(v) for y, v in (ext.get("wht") or {}).items()},
        "기신고": ext.get("prev_filing"),
    }
    res = call_gemini_json(
        "통합고용세액공제 계산을 위해 업로드된 자료를 요약한 것입니다. 계산에 꼭 필요한데 빠졌거나 서로 맞지 않는 정보만 "
        "최대 3개, 한 문장씩 '○○ 정보가 없습니다' 형태로 알려주세요. 문제가 없으면 빈 배열을 주세요. "
        '형식: {"경고":["..."]}',
        json.dumps(summary, ensure_ascii=False), log_tokens_fn, room_key)
    return [str(x) for x in (res.get("경고") or [])][:3]
