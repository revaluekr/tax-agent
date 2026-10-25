# -*- coding: utf-8 -*-
"""
업로드 자료 자동 분류 및 초고속 병렬 정보 추출 (parsers.py)

[업그레이드 내역]
1. 파일 종류 자동 분류 고도화:
   - '2026년', '2025년', '2024년'뿐 아니라 '26년 소득자별 근로소득원천징수부', '25년...', '24년...' 등 2자리 연도 표기 완벽 인식.
2. 1단계 → 2단계 전환 속도 대폭 단축:
   - 여러 서류(사업자등록증·등기부등본·주주명부·연도별 원천징수부·기신고서)를 순차 호출하지 않고
     `ThreadPoolExecutor`로 동시 병렬 호출하여 체감 대기시간을 1/3 이하로 단축했습니다.
   - Gemini Flash 호출 시 `thinking_budget=0` 옵션을 우선 적용하여 불필요한 추론 지연을 제거했습니다.
3. 기신고 통합고용세액공제 서식 추출 확장:
   - 연도별 상시근로자 수·청년등 상시근로자 수뿐 아니라 기신고 청년등 증가인원·청년등외 증가인원·최초공제세액·이월세액까지 추출.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import re
from datetime import date

from . import rules as R
from .headcount import parse_date, default_months_for_year

MAX_TEXT_CHARS = 120_000


def classify_file(name: str, text: str) -> str | None:
    n = (name or "").replace(" ", "")
    head = (text or "")[:4000].replace(" ", "")
    both = n + " " + head

    if "원천징수부" in both or ("원천징수" in n and "근로" in both) or ("급여대장" in both):
        for y in range(2028, 2020, -1):
            if str(y) in n:
                return f"wht_{y}"
        m_short = re.search(r"(?:^|[^0-9])(2[1-8])\s*(?:년|귀속)", name or "")
        if m_short:
            return f"wht_20{m_short.group(1)}"
        m = re.search(r"(?:귀속연도|귀속년도|과세연도|귀속)[^0-9]{0,8}(202[1-8])", head)
        if m:
            return f"wht_{m.group(1)}"
        for y in range(2028, 2020, -1):
            if f"{y}년" in head[:1200]:
                return f"wht_{y}"
        return None

    if any(k in both for k in ("상시근로자명세", "통합고용", "세액공제신청서", "공제세액계산서", "사후관리")):
        return "prev_filing"
    if "주주명부" in both or "주식이동" in both or ("주주" in n):
        return "shareholder"
    if "사업자등록증" in both or "사업자등록" in n:
        return "biz_reg"
    if "등기사항전부증명" in both or "등기부" in both or "등기" in n or "등본" in n:
        return "corp_reg"
    return None


def call_gemini_json(instruction: str, text: str, log_tokens_fn=None, room_key: str = "") -> dict:
    try:
        import agent
        from google import genai
        from google.genai import types
    except Exception:
        return {}

    keys = agent.get_live_gemini_key_pool()
    models = [
        m
        for m in (
            getattr(agent, "FLASH_MODEL_ID", None),
            getattr(agent, "FLASH_BACKUP_ID", None),
            getattr(agent, "FLASH_FALLBACK_ID", "gemini-2.5-flash"),
        )
        if m
    ]
    prompt = (
        instruction
        + "\n\n규칙: JSON만 출력하고 설명·마크다운은 쓰지 마세요. "
        "서류에 없는 값은 지어내지 말고 빈 문자열(\"\")이나 null로 두세요.\n\n[서류 내용]\n"
        + (text or "")[:MAX_TEXT_CHARS]
    )

    for _, key in keys:
        client = genai.Client(api_key=key)
        for model_id in models:
            try:
                try:
                    cfg = types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0,
                        thinking_config=types.ThinkingConfig(thinking_budget=0),
                    )
                except Exception:
                    cfg = types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0,
                    )
                resp = client.models.generate_content(
                    model=model_id,
                    contents=prompt,
                    config=cfg,
                )
                um = getattr(resp, "usage_metadata", None)
                if log_tokens_fn and um:
                    log_tokens_fn(
                        model_id,
                        int(um.prompt_token_count or 0),
                        int(um.candidates_token_count or 0),
                        True,
                        room_key,
                    )
                raw = (resp.text or "").strip()
                raw = re.sub(r"^```(?:json)?|```$", "", raw).strip()
                return json.loads(raw)
            except Exception:
                continue
    return {}


PROMPT_BIZ = """다음은 사업자등록증입니다. 아래 형식으로 값을 읽어주세요.
{"상호":"", "사업자번호":"000-00-00000", "개업일":"YYYY-MM-DD", "법인등록번호앞6자리":"", "대표자":"",
 "업태":"", "종목":"", "사업장소재지":""}"""

PROMPT_CORP = """다음은 법인 등기부등본입니다. 아래 형식으로 읽어주세요. 임원은 현재 재임 중인 사람만 넣으세요.
{"상호":"", "설립일":"YYYY-MM-DD", "본점":"", "임원":[{"성명":"", "직위":"대표이사|사내이사|감사 등"}]}"""

PROMPT_SH = """다음은 주주명부입니다. 아래 형식으로 읽어주세요. 관계는 서류에 적힌 그대로(본인/배우자/자/부/모/형제 등),
없으면 빈 문자열로 두세요.
{"주주":[{"성명":"", "지분율":0.0, "관계":""}]}"""

PROMPT_WHT = """다음은 소득자별 근로소득원천징수부입니다. 근로자별로 아래 형식으로 빠짐없이 읽어주세요.
주민등록번호는 앞 6자리와 뒷자리 첫 1자리만 '000000-0' 형태로 적고 나머지는 절대 적지 마세요.
월급여는 1월~12월 지급액(과세+비과세 합계, 숫자) 12개를 순서대로, 지급이 없으면 0으로 넣으세요.
{"근로자":[{"성명":"", "주민번호7":"000000-0", "입사일":"YYYY-MM-DD", "퇴사일":"YYYY-MM-DD 또는 빈칸",
  "월급여":[0,0,0,0,0,0,0,0,0,0,0,0]}]}"""

PROMPT_PREV = """다음은 이미 신고한 통합고용세액공제 관련 서식(상시근로자 명세서·공제세액계산서·세액공제조정명세서)입니다.
연도별 상시근로자 수, 청년등 상시근로자 수, 청년등 증가인원, 청년등외 증가인원, 공제세액, 미공제 이월세액을 읽어주세요.
서식에 적힌 연도와 숫자만 그대로 옮기세요.
{"연도별":{
  "2023":{"상시":null,"청년등":null,"청년등_증가":null,"청년등외_증가":null,"공제세액":null,"이월세액":null},
  "2024":{"상시":null,"청년등":null,"청년등_증가":null,"청년등외_증가":null,"공제세액":null,"이월세액":null},
  "2025":{"상시":null,"청년등":null,"청년등_증가":null,"청년등외_증가":null,"공제세액":null,"이월세액":null}
}, "공제적용연도":"서식상 최초공제 귀속연도(있으면)", "공제세액":null, "이월세액":null}"""


def birth_from_rrn7(rrn7: str) -> tuple[date | None, bool]:
    d = re.sub(r"[^0-9]", "", rrn7 or "")
    if len(d) < 7:
        return None, False
    yy, mm, dd, g = int(d[:2]), int(d[2:4]), int(d[4:6]), int(d[6])
    century_map = {1: 1900, 2: 1900, 5: 1900, 6: 1900, 3: 2000, 4: 2000, 7: 2000, 8: 2000, 9: 1800, 0: 1800}
    century = century_map.get(g, 1900)
    try:
        return date(century + yy, mm, dd), g in (5, 6, 7, 8)
    except ValueError:
        return None, g in (5, 6, 7, 8)


def _num(v) -> float:
    try:
        return float(str(v).replace(",", "").strip()) if v not in (None, "") else 0.0
    except ValueError:
        return 0.0


def _iso(v) -> str:
    d = parse_date(v)
    return d.isoformat() if d else ""


def _normalize_wht_rows(raw_employees: list[dict]) -> list[dict]:
    rows = []
    for e in raw_employees or []:
        nm = (e.get("성명") or "").strip()
        if not nm:
            continue
        birth, foreign = birth_from_rrn7(e.get("주민번호7", ""))
        if not birth and e.get("생년월일"):
            birth = parse_date(e.get("생년월일"))
        pay = [_num(x) for x in (e.get("월급여") or [])][:12]
        rows.append(
            {
                "성명": nm,
                "생년월일": birth.isoformat() if birth else "",
                "외국인": bool(e.get("외국인", foreign)),
                "입사일": _iso(e.get("입사일")),
                "퇴사일": _iso(e.get("퇴사일")),
                "월급여": pay + [0.0] * (12 - len(pay)) if pay else None,
            }
        )
    return rows


def extract_all(doc_texts: dict[str, str], log_tokens_fn=None, room_key: str = "") -> dict:
    out: dict = {"biz": {}, "corp": {}, "shareholders": [], "wht": {}, "prev_filing": {}}
    if not doc_texts:
        return out

    tasks: dict[str, tuple[str, str]] = {}
    if doc_texts.get("biz_reg"):
        tasks["biz"] = (PROMPT_BIZ, doc_texts["biz_reg"])
    if doc_texts.get("corp_reg"):
        tasks["corp"] = (PROMPT_CORP, doc_texts["corp_reg"])
    if doc_texts.get("shareholder"):
        tasks["shareholder"] = (PROMPT_SH, doc_texts["shareholder"])
    if doc_texts.get("prev_filing"):
        tasks["prev_filing"] = (PROMPT_PREV, doc_texts["prev_filing"])

    for k, txt in doc_texts.items():
        if k.startswith("wht_") and txt:
            tasks[k] = (PROMPT_WHT, txt)

    if not tasks:
        return out

    results: dict[str, dict] = {}
    max_workers = min(8, len(tasks))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        fut_map = {
            pool.submit(call_gemini_json, prompt, txt, log_tokens_fn, room_key): task_key
            for task_key, (prompt, txt) in tasks.items()
        }
        for fut in as_completed(fut_map):
            tk = fut_map[fut]
            try:
                results[tk] = fut.result() or {}
            except Exception:
                results[tk] = {}

    if "biz" in results:
        out["biz"] = results["biz"]
    if "corp" in results:
        out["corp"] = results["corp"]
    if "shareholder" in results:
        out["shareholders"] = results["shareholder"].get("주주", []) or []
    if "prev_filing" in results:
        out["prev_filing"] = results["prev_filing"]

    for tk, res in results.items():
        if tk.startswith("wht_"):
            y_str = tk.replace("wht_", "").strip()
            out["wht"][y_str] = _normalize_wht_rows(res.get("근로자", []) or [])

    return out


def build_biz_info(ext: dict, tax_year: int, existing_biz: dict | None = None) -> tuple[dict, list[str]]:
    biz, corp = (ext or {}).get("biz") or {}, (ext or {}).get("corp") or {}
    prev_b = existing_biz or {}
    info, confirmed = {}, []

    def put(field, *vals):
        for v in vals:
            if v not in (None, ""):
                info[field] = str(v).strip()
                confirmed.append(field)
                return
        info[field] = str(prev_b.get(field, "") or "").strip()

    put("상호", biz.get("상호"), corp.get("상호"))
    put("설립일", corp.get("설립일"), biz.get("개업일"))
    put("사업자번호", biz.get("사업자번호"))
    put("업태", biz.get("업태"))
    put("종목", biz.get("종목"))
    put("사업장소재지", biz.get("사업장소재지"), corp.get("본점"))

    founded = parse_date(info.get("설립일"))
    info["당해_월수"] = int(prev_b.get("당해_월수") or default_months_for_year(tax_year, founded) or 12)
    info["전년_월수"] = int(prev_b.get("전년_월수") or default_months_for_year(tax_year - 1, founded) or 12)
    info["전전년_월수"] = int(prev_b.get("전전년_월수") or default_months_for_year(tax_year - 2, founded) or 12)
    info["기업구분"] = prev_b.get("기업구분") if prev_b.get("기업구분") in R.CORP_SIZES else "중소기업"
    return info, confirmed


def _shareholder_relations(shareholders: list[dict]) -> dict[str, str]:
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
    people: dict[str, dict] = {}
    rel_map = _shareholder_relations((ext or {}).get("shareholders") or [])
    execs = {
        (e.get("성명") or "").strip(): (e.get("직위") or "")
        for e in (((ext or {}).get("corp") or {}).get("임원") or [])
    }

    for y in sorted(((ext or {}).get("wht") or {}).keys()):
        for e in ext["wht"][y]:
            if not e.get("성명"):
                continue
            pid = f"{e['성명']}|{e.get('생년월일', '')}"
            p = people.setdefault(
                pid,
                {
                    "pid": pid,
                    "성명": e["성명"],
                    "생년월일": e.get("생년월일", ""),
                    "입사일": "",
                    "퇴사일": "",
                    "계약체결일": "",
                    "연도별_퇴사일": {},
                    "외국인": e.get("외국인", False),
                    "병역개월": 0,
                    "월급여": {},
                    "_confirmed": ["성명"],
                },
            )
            if e.get("생년월일") and "생년월일" not in p["_confirmed"]:
                p["생년월일"] = e["생년월일"]
                p["_confirmed"].append("생년월일")
            if e.get("입사일"):
                p["입사일"] = e["입사일"]
                if "입사일" not in p["_confirmed"]:
                    p["_confirmed"].append("입사일")
            if e.get("퇴사일"):
                p["퇴사일"] = e["퇴사일"]
                p["연도별_퇴사일"][str(y)] = e["퇴사일"]
                if "퇴사일" not in p["_confirmed"]:
                    p["_confirmed"].append("퇴사일")
            if e.get("월급여"):
                p["월급여"][str(y)] = e["월급여"]
            if e["성명"] in rel_map:
                p["주주관계"] = rel_map[e["성명"]]

    year_recs = {int(y): {} for y in years}
    for pid, p in people.items():
        pos = execs.get(p["성명"], "")
        emp = R.EMP_CEO if "대표" in pos else (R.EMP_EXEC if pos else R.EMP_REGULAR)
        for y in years:
            year_recs[int(y)][pid] = new_year_rec(emp, confirmed_emp=bool(pos))
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


def check_missing(classified: dict[str, list[str]], ext: dict | None, tax_year: int) -> list[str]:
    msgs = []
    for key, label, required, _ in R.get_doc_types(tax_year):
        if required and not classified.get(key):
            msgs.append(f"**{label}** 자료가 없습니다.")
    if ext:
        for y in (str(tax_year), str(tax_year - 1)):
            rows = (ext.get("wht") or {}).get(y)
            if rows is not None and not rows:
                msgs.append(f"**{y}년 원천징수부**에서 근로자를 한 명도 읽지 못했습니다.")
            elif rows:
                no_hire = [r["성명"] for r in rows if not r.get("입사일")]
                if no_hire:
                    msgs.append(
                        f"{y}년 원천징수부에 **입사일 정보**가 없는 근로자가 {len(no_hire)}명 있습니다 "
                        f"({', '.join(no_hire[:5])}{' 외' if len(no_hire) > 5 else ''})."
                    )
                no_birth = [r["성명"] for r in rows if not r.get("생년월일")]
                if no_birth:
                    msgs.append(f"{y}년 원천징수부에서 **생년월일**을 확인하지 못한 근로자가 {len(no_birth)}명 있습니다.")
        if not (ext.get("biz") or {}).get("업태") and classified.get("biz_reg"):
            msgs.append("사업자등록증에서 **업태·종목**을 읽지 못했습니다 (사이드바에서 직접 입력 가능).")
    return msgs


def ai_extra_warnings(ext: dict, log_tokens_fn=None, room_key: str = "") -> list[str]:
    return []
