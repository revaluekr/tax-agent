# -*- coding: utf-8 -*-
"""
업로드 자료 분류 및 정보 추출

[개선 및 버그 패치 내역]
1. 파일 종류 자동 분류 확장: 2021년~2028년 모든 연도의 근로소득원천징수부(`wht_YYYY`), 다년도 기신고 명세서(`prev_filing`),
   근로계약서·4대보험 가입자명부 등 보충서류(`labor_contract`)까지 유연하게 자동 인식합니다.
2. 주민등록번호 7자리 안전 파싱(`birth_from_rrn7`): KeyError 및 비정상 연도 생성 원천 방지.
3. 다년도 원천징수부 병합 시 재입사자 퇴사일 잔류 버그 패치:
   과거 연도(예: 2024·2025)에 퇴사일이 있었으나 이후 연도(예: 2026)에 재입사하여 퇴사일이 없는 경우,
   과거 퇴사일이 최신 연도의 근무월을 0으로 덮어쓰지 않도록 연도별 퇴사일(`연도별_퇴사일`)을 분리 보존합니다.
4. 사이드바 수기 입력 보존(`build_biz_info`): 1단계에서 사용자가 사이드바에 먼저 입력한 상호·소재지·업종 등을
   2단계 진입 시 빈 값으로 덮어쓰지 않고 안전하게 병합(Merge)합니다.
"""
from __future__ import annotations

import json
import re
from datetime import date

from . import rules as R
from .headcount import parse_date

MAX_TEXT_CHARS = 120_000


# ══════════════════════════════════════════════════════════════════
# 1. 파일 종류 분류 (2021~2028 전 연도 원천징수부 + 보조서류 자동 인식)
# ══════════════════════════════════════════════════════════════════
def classify_file(name: str, text: str) -> str | None:
    n = (name or "").replace(" ", "")
    head = (text or "")[:3500].replace(" ", "")
    both = n + " " + head

    # 1) 근로소득원천징수부 (2021~2028 모든 연도 인식)
    if "원천징수부" in both or ("원천징수" in n and "근로" in both) or ("소득자별" in both and "원천징수" in both):
        for y in sorted(R.WHT_YEAR_RANGE, reverse=True):
            ys = str(y)
            if ys in n:
                return f"wht_{ys}"
        m = re.search(r"(?:귀속연도|귀속년도|과세연도|귀속)[^0-9]{0,8}(202[1-8])", head)
        if m:
            return f"wht_{m.group(1)}"
        for y in sorted(R.WHT_YEAR_RANGE, reverse=True):
            if str(y) in head[:800]:
                return f"wht_{y}"
        return None

    # 2) 기신고 통합고용세액공제 / 고용증대세액공제 명세서·신청서
    if any(k in both for k in ("상시근로자명세", "통합고용", "고용증대", "세액공제신청서", "공제세액계산서")):
        return "prev_filing"

    # 3) 주주명부 / 출자자명부
    if any(k in both for k in ("주주명부", "주식등변동", "출자자명부")) or ("주주" in n):
        return "shareholder"

    # 4) 사업자등록증
    if "사업자등록증" in both or "사업자등록" in n:
        return "biz_reg"

    # 5) 법인 등기부등본 (등기사항전부증명서)
    if any(k in both for k in ("등기사항전부증명", "등기부등본", "법인등기")) or ("등기" in n or "등본" in n):
        return "corp_reg"

    # 6) 근로계약서 · 4대보험 가입자명부 · 급여대장 등 추가 보충자료
    if any(k in both for k in ("근로계약서", "연봉계약서", "4대보험", "가입자명부", "건강보험", "국민연금", "고용보험")):
        return "labor_contract"

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
# 3. 서류별 추출 프롬프트 및 안전 파서
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

PROMPT_PREV = """다음은 이미 신고한 통합고용세액공제(또는 고용증대세액공제) 관련 서식(상시근로자 명세서·공제세액계산서)입니다.
서식에 등장하는 모든 연도(예: 2022, 2023, 2024, 2025 등)의 상시근로자 수와 청년등상시근로자 수를 읽어주세요.
서식에 적힌 연도와 숫자만 그대로 옮기세요.
{"연도별":{"2023":{"상시":null,"청년등":null}, "2024":{"상시":null,"청년등":null}, "2025":{"상시":null,"청년등":null}},
 "공제적용연도":"서식상 최초공제 귀속연도(있으면)", "공제세액":null}"""

PROMPT_CONTRACT = """다음은 근로계약서 또는 4대보험 가입자명부 등 보충 서류입니다.
근로자별로 확인되는 계약체결일, 고용형태(정규직/기간제/단시간), 월평균(또는 주당) 소정근로시간을 읽어주세요.
{"근로자":[{"성명":"", "계약체결일":"YYYY-MM-DD", "고용유형":"정규직|계약직(기간제)|단시간(60시간 이상)|단시간(60시간 미만)"}]}"""


def birth_from_rrn7(rrn7: str) -> tuple[date | None, bool]:
    """'900101-1' → (1990-01-01, 외국인여부). 잘못된 뒷자리 숫자나 오타에도 예외 없이 안전 동작."""
    d = re.sub(r"[^0-9]", "", rrn7 or "")
    if len(d) < 6:
        return None, False
    yy, mm, dd = int(d[:2]), int(d[2:4]), int(d[4:6])
    g = int(d[6]) if len(d) >= 7 else 0
    century_map = {1: 1900, 2: 1900, 5: 1900, 6: 1900, 3: 2000, 4: 2000, 7: 2000, 8: 2000}
    century = century_map.get(g, 2000 if yy <= 26 else 1900)
    is_foreign = g in (5, 6, 7, 8)
    try:
        dt = date(century + yy, mm, dd)
        if not (1920 <= dt.year <= 2028):
            return None, is_foreign
        return dt, is_foreign
    except ValueError:
        return None, is_foreign


def _num(v) -> float:
    try:
        return float(str(v).replace(",", "")) if v not in (None, "") else 0.0
    except ValueError:
        return 0.0


def _iso(v) -> str:
    d = parse_date(v)
    return d.isoformat() if d else ""


def extract_all(doc_texts: dict[str, str], log_tokens_fn=None, room_key: str = "") -> dict:
    """doc_texts: {"biz_reg": "...", "wht_2026": "...", "wht_2023": "...", ...} → 정리된 추출 결과"""
    out = {"biz": {}, "corp": {}, "shareholders": [], "wht": {}, "prev_filing": {}, "contracts": []}

    if doc_texts.get("biz_reg"):
        out["biz"] = call_gemini_json(PROMPT_BIZ, doc_texts["biz_reg"], log_tokens_fn, room_key) or {}
    if doc_texts.get("corp_reg"):
        out["corp"] = call_gemini_json(PROMPT_CORP, doc_texts["corp_reg"], log_tokens_fn, room_key) or {}
    if doc_texts.get("shareholder"):
        out["shareholders"] = (call_gemini_json(PROMPT_SH, doc_texts["shareholder"], log_tokens_fn, room_key)
                               or {}).get("주주", []) or []

    # 2021~2028 중 업로드된 모든 원천징수부 연도 추출
    wht_keys = sorted([k for k in doc_texts.keys() if k.startswith("wht_") and doc_texts.get(k)])
    for wk in wht_keys:
        y = wk.replace("wht_", "").strip()
        res = call_gemini_json(PROMPT_WHT, doc_texts[wk], log_tokens_fn, room_key) or {}
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
    if doc_texts.get("labor_contract"):
        c_res = call_gemini_json(PROMPT_CONTRACT, doc_texts["labor_contract"], log_tokens_fn, room_key) or {}
        out["contracts"] = c_res.get("근로자", []) or []
    return out


# ══════════════════════════════════════════════════════════════════
# 4. 추출 결과 → 사업자정보·사원 DB
# ══════════════════════════════════════════════════════════════════
def build_biz_info(ext: dict, tax_year: int, existing_biz: dict | None = None) -> tuple[dict, list[str]]:
    """
    반환: (사업자정보, 서류로 확인된 항목 목록)
    [버그 패치] 사용자가 1단계에서 사이드바에 먼저 수기 입력한 값(existing_biz)이 있으면
    서류 추출값이 비어 있을 때 절대 날리지 않고 그대로 보존합니다.
    """
    biz, corp = ext.get("biz") or {}, ext.get("corp") or {}
    prev = existing_biz or {}
    info, confirmed = {}, []

    def put(field, *vals):
        for v in vals:
            if v not in (None, "") and str(v).strip():
                info[field] = str(v).strip()
                confirmed.append(field)
                return
        # 서류에 없으면 기존 사이드바 수기 입력값 유지
        info[field] = str(prev.get(field, "") or "").strip()

    put("상호", biz.get("상호"), corp.get("상호"))
    put("설립일", corp.get("설립일"), biz.get("개업일"))
    put("사업자번호", biz.get("사업자번호"))
    put("업태", biz.get("업태"))
    put("종목", biz.get("종목"))
    put("사업장소재지", biz.get("사업장소재지"), corp.get("본점"))

    from .headcount import default_months_for_year
    founded = parse_date(info.get("설립일"))
    info["당해_월수"] = prev.get("당해_월수") or default_months_for_year(tax_year, founded)
    info["전년_월수"] = prev.get("전년_월수") or default_months_for_year(tax_year - 1, founded)
    info["전전년_월수"] = prev.get("전전년_월수") or default_months_for_year(tax_year - 2, founded)
    info["기업구분"] = prev.get("기업구분") or "중소기업"
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
    - 같은 사람은 (성명, 생년월일)로 묶되, 생년월일이 한쪽 연도에만 있는 경우에도 이름으로 매칭하여 중복 생성을 막습니다.
    - [버그 패치] 과거 연도에 퇴사 후 최신 연도에 재입사(퇴사일 공란)한 근로자의 과거 퇴사일이
      최신 연도 재직 판정을 덮어쓰지 않도록 안전하게 처리합니다.
    """
    people: dict[str, dict] = {}
    name_to_pid: dict[str, str] = {}
    rel_map = _shareholder_relations(ext.get("shareholders") or [])
    execs = {(e.get("성명") or "").strip(): (e.get("직위") or "")
             for e in ((ext.get("corp") or {}).get("임원") or [])}
    contract_map = {(c.get("성명") or "").strip(): c for c in (ext.get("contracts") or []) if c.get("성명")}

    for y in sorted(ext.get("wht", {}).keys()):
        for e in ext["wht"][y]:
            nm = (e.get("성명") or "").strip()
            if not nm:
                continue
            b_str = e.get("생년월일") or ""
            pid = f"{nm}|{b_str}" if b_str else name_to_pid.get(nm, f"{nm}|")
            if nm in name_to_pid and name_to_pid[nm].endswith("|") and b_str:
                old_pid = name_to_pid[nm]
                if old_pid in people:
                    p_old = people.pop(old_pid)
                    p_old["pid"] = pid
                    people[pid] = p_old
            name_to_pid[nm] = pid

            p = people.setdefault(pid, {
                "pid": pid, "성명": nm, "생년월일": b_str, "입사일": "", "퇴사일": "",
                "계약체결일": "", "외국인": e.get("외국인", False), "병역개월": 0,
                "월급여": {}, "연도별_퇴사일": {}, "_confirmed": ["성명"],
            })
            if b_str and not p.get("생년월일"):
                p["생년월일"] = b_str
            if p.get("생년월일") and "생년월일" not in p["_confirmed"]:
                p["_confirmed"].append("생년월일")

            if e.get("입사일"):
                # 더 최근 연도 원천징수부에 새로운 입사일이 찍혀 있고 퇴사일이 비어 있으면(재입사), 과거 퇴사일 초기화
                if p.get("입사일") and e["입사일"] > p["입사일"] and not e.get("퇴사일"):
                    p["퇴사일"] = ""
                    if "퇴사일" in p["_confirmed"]:
                        p["_confirmed"].remove("퇴사일")
                p["입사일"] = e["입사일"]
                if "입사일" not in p["_confirmed"]:
                    p["_confirmed"].append("입사일")

            if e.get("퇴사일"):
                p["퇴사일"] = e["퇴사일"]
                p.setdefault("연도별_퇴사일", {})[str(y)] = e["퇴사일"]
                if "퇴사일" not in p["_confirmed"]:
                    p["_confirmed"].append("퇴사일")
            else:
                # 해당 연도 원천징수부에서 연말 현재 재직 중(퇴사일 없음)이면 해당 연도 퇴사일은 빈 값으로 명시
                p.setdefault("연도별_퇴사일", {})[str(y)] = ""
                if p.get("퇴사일") and p["퇴사일"][:4] < str(y):
                    p["퇴사일"] = ""
                    if "퇴사일" in p["_confirmed"]:
                        p["_confirmed"].remove("퇴사일")

            if e.get("월급여"):
                p["월급여"][str(y)] = e["월급여"]
            if nm in rel_map:
                p["주주관계"] = rel_map[nm]
            if nm in contract_map:
                c_info = contract_map[nm]
                if c_info.get("계약체결일"):
                    p["계약체결일"] = _iso(c_info.get("계약체결일"))

    year_recs = {y: {} for y in years}
    for pid, p in people.items():
        nm = p["성명"]
        pos = execs.get(nm, "")
        c_emp = (contract_map.get(nm) or {}).get("고용유형") or ""
        if "대표" in pos:
            emp, conf_emp = R.EMP_CEO, True
        elif pos:
            emp, conf_emp = R.EMP_EXEC, True
        elif c_emp in R.EMP_TYPES:
            emp, conf_emp = c_emp, True
        else:
            emp, conf_emp = R.EMP_REGULAR, False

        for y in years:
            year_recs[y][pid] = new_year_rec(emp, confirmed_emp=conf_emp)
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
    """선택된 귀속사업연도(tax_year) 기준 필수 서류 및 핵심 항목 누락을 코드로 확정 판정합니다."""
    msgs = []
    for key, label, required, _ in R.get_doc_types(tax_year):
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
        "사업자": ext.get("biz"),
        "등기": {k: v for k, v in (ext.get("corp") or {}).items() if k != "임원"},
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
