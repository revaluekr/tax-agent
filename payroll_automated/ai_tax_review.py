"""
인건비 자동화 — [AI 맞춤 절세 검토]

· 직원(또는 사업소득자) 자료를 이름·주민번호 없이 'E01/F01' 번호로 바꿔 AI에 보내고, 답변의 번호는 화면에서 다시 이름으로 바꿉니다.
· 토큰 절약: 법령 원문 검색 없이 아래 '검토 범위 법령' 요약만 주고 그 범위 안에서만 판단하게 합니다.
  범위 밖 내용은 '추가 검토 권장' 제목으로만 받습니다.
· 같은 자료로 다시 열면 저장된 결과를 그대로 보여 줍니다 (재호출 없음).
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from .tax_tables import NON_TAXABLE_LIMITS, is_ceo_position

SCOPE_BASE_DATE = "2026-10"

# ── 검토 범위 법령 (근로소득자) ──────────────────────────────────────────
EMP_LAW_SCOPE: List[Tuple[str, str]] = [
    ("조세특례제한법 제30조·시행령 제27조 (중소기업 취업자 소득세 감면)",
     "중소기업체에 2026.12.31.까지 취업한 사람. 청년(근로계약 체결일 현재 15~34세, 병역 이행기간 최대 6년 차감) 소득세 90% 감면, 취업일부터 5년. "
     "60세 이상·장애인·경력단절 근로자 70% 감면, 3년. 과세기간별 감면세액 200만원 한도. 제외: 임원, 최대주주·그 배우자·직계존비속·친족, 일용근로자, "
     "국민연금·건강보험료 납부가 확인되지 않는 사람, 감면 대상 업종이 아닌 기업. 근로자가 감면신청서를 내고 회사는 신청받은 달의 다음 달 10일까지 명단 제출. "
     "신청 전 기간도 경정청구로 환급 가능."),
    ("조세특례제한법 제29조의8 (통합고용세액공제)",
     "상시근로자 수가 직전 과세연도보다 늘면 증가 인원 × 1인당 공제액을 법인세·소득세에서 공제(청년 정규직·장애인·60세 이상·경력단절 근로자는 우대 공제액). "
     "중소기업은 3년간 공제, 2년 이내 인원이 줄면 추징. 정규직 전환·육아휴직 복귀자 추가공제. 금액 계산은 앱의 [통합고용세액공제] 탭에서 함."),
    ("소득세법 제12조 제3호·시행령 제12조·제17조의2 등 (근로소득 비과세)",
     f"식대 월 {NON_TAXABLE_LIMITS['식대']:,}원(회사가 식사를 현물로 제공하면 불가). 자가운전보조금 월 {NON_TAXABLE_LIMITS['자가운전보조금']:,}원"
     "(본인 명의 차량을 업무에 쓰고 실제 여비를 따로 받지 않는 경우). 6세 이하 자녀 보육수당 자녀 1명당 월 20만원. 출산지원금 출생일 이후 2년 이내 최대 2회 전액. "
     "중소기업 등 연구원 연구보조비 월 20만원. 생산직 등 근로자 연장·야간·휴일근로수당 연 240만원(월정액급여·직전연도 총급여 기준 충족 시). "
     "비과세는 실제 지급 요건과 사내 규정이 있어야 하며, 기본급을 줄여 비과세 항목으로 바꾸면 통상임금·최저임금·퇴직금에 영향이 있음."),
    ("두루누리 사회보험료 지원 (고용보험료징수법 제21조, 국민연금법 제100조의3)",
     "근로자 10명 미만 사업장의 월평균보수 기준액 미만 신규 가입 근로자와 사업주의 고용보험·국민연금 보험료 80% 지원(최대 36개월). "
     "기준액과 재산·소득 요건은 해마다 근로복지공단 공고로 확인."),
    ("소득세법 시행령 제194조 (원천징수세액 선택)",
     "근로자는 간이세액표 금액의 80%·100%·120% 중 선택 가능 — 세금 총액은 같고 연말정산 환급·추가납부 시기만 달라짐. "
     "부양가족 수·8~20세 자녀 수가 실제와 다르면 매월 원천징수가 과다·과소."),
]

# ── 검토 범위 법령 (사업소득자) ──────────────────────────────────────────
FREE_LAW_SCOPE: List[Tuple[str, str]] = [
    ("소득세법 제127조·제129조, 지방세법 제103조의13 (사업소득 원천징수)",
     "인적용역 사업소득 지급 시 3% + 지방소득세 0.3%. 2024.7.1. 이후 지급하는 계속·반복 인적용역 사업소득은 소액부징수(1,000원 미만) 적용 안 함. "
     "지급일이 속하는 달의 다음 달 10일까지 신고·납부(반기납부 승인 사업장은 반기)."),
    ("소득세법 제164조의3·제81조의11 (간이지급명세서)",
     "원천징수 대상 사업소득은 지급일이 속하는 달의 다음 달 말일까지 매월 간이지급명세서 제출. 미제출·지연제출 시 가산세."),
    ("소득세법 제21조·제19조 (기타소득과 사업소득 구분)",
     "고용관계 없이 일시적·우발적으로 제공한 인적용역은 기타소득(필요경비 60% 의제, 실효 8.8%), 계속·반복이면 사업소득(3.3%). 소득 구분이 틀리면 원천징수 오류."),
    ("근로기준법 제2조 등 (근로자성)",
     "계약 형식이 아니라 실질(업무 내용을 회사가 정함, 근무시간·장소 지정, 지휘·감독, 매월 고정 보수 등)로 판단. 근로자로 보면 4대보험·퇴직금·근로소득 원천징수 대상."),
    ("부가가치세법 제26조 (인적용역 면세)",
     "사업자등록 없이 독립된 자격으로 제공하는 인적용역은 부가가치세 면세 — 사업자등록을 한 과세사업자라면 3.3% 대신 세금계산서 수취 대상인지 확인."),
]


def birth_from_rrn(rrn: Any) -> Optional[datetime]:
    """주민번호(뒷자리 가림 포함)에서 생년월일 추정. 성별자리가 없으면 만 15세 이상이 되는 세기로 추정."""
    s = re.sub(r"[^0-9*]", "", str(rrn or ""))
    if len(s) < 6 or not s[:6].isdigit():
        return None
    yy, mm, dd = int(s[:2]), int(s[2:4]), int(s[4:6])
    g = s[6] if len(s) > 6 and s[6].isdigit() else ""
    if g in ("1", "2", "5", "6"):
        cent = 1900
    elif g in ("3", "4", "7", "8"):
        cent = 2000
    elif g in ("9", "0"):
        cent = 1800
    else:
        cent = 2000 if 2000 + yy <= datetime.now().year - 15 else 1900
    try:
        return datetime(cent + yy, mm, dd)
    except ValueError:
        return None


def age_on(birth: datetime, on: datetime) -> int:
    return on.year - birth.year - ((on.month, on.day) < (birth.month, birth.day))


def parse_ymd(v: Any) -> Optional[datetime]:
    m = re.search(r"(\d{4})\D?(\d{1,2})\D?(\d{1,2})", str(v or ""))
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _ref_date(ym: str) -> datetime:
    try:
        return datetime(int(str(ym)[:4]), int(str(ym)[5:7]), 1)
    except Exception:
        return datetime.now()


def _i(v: Any) -> int:
    try:
        return int(float(v or 0))
    except Exception:
        return 0


def _role(pos: Any) -> str:
    p = str(pos or "")
    if is_ceo_position(p):
        return "대표"
    if re.search(r"이사|임원|감사", p):
        return "임원"
    return "직원"


# ── 익명 자료 만들기 ────────────────────────────────────────────────────
def build_emp_payload(pstate: Dict[str, Any]) -> Tuple[str, Dict[str, str]]:
    """근로소득자 자료를 번호(E01…)로 바꾼 표(텍스트)와 번호→이름 표를 돌려줍니다."""
    emps = [e for e in pstate.get("employees", []) if str(e.get("성명") or "").strip()]
    ym = str(pstate.get("year_month") or datetime.now().strftime("%Y-%m"))
    ref = _ref_date(ym)
    prev_names = {str(e.get("성명") or "").strip() for e in (pstate.get("prev_employees") or [])}
    id_map: Dict[str, str] = {}
    lines = ["번호|구분|입사일|입사시나이|현재나이|퇴사일|기본급|식대|차량|상여|연장등수당|비과세계|과세급여|연금|건보|고용|소득세|감면율|부양|자녀|전월재직"]
    for n, e in enumerate(emps, 1):
        eid = f"E{n:02d}"
        id_map[eid] = str(e.get("성명")).strip()
        b, h = birth_from_rrn(e.get("주민등록번호")), parse_ymd(e.get("입사일"))
        ot = sum(_i(e.get(k)) for k in ("약정연장근로수당", "약정휴일근로수당", "연장근로수당", "휴일근로수당"))
        lines.append("|".join(str(x) for x in (
            eid, _role(e.get("직급")), f"{h:%Y-%m-%d}" if h else "?",
            age_on(b, h) if (b and h) else "?", age_on(b, ref) if b else "?",
            str(e.get("퇴사일") or "-") or "-",
            _i(e.get("기본급")), _i(e.get("식대")), _i(e.get("자가운전보조금")), _i(e.get("상여")), ot,
            _i(e.get("비과세합계")), _i(e.get("과세급여")), _i(e.get("국민연금")), _i(e.get("건강보험")), _i(e.get("고용보험")),
            _i(e.get("소득세")), f"{_i(e.get('소득세감면율'))}%", _i(e.get("부양가족수") or 1), _i(e.get("자녀수")),
            "Y" if id_map[eid] in prev_names else ("N" if prev_names else "?"),
        )))
    cnt = pstate.get("ei_emp_count") or len(emps)
    head = (f"귀속 {ym} · 근로소득자 {len(emps)}명 · 상시근로자(전 사업장 합산) {cnt}명 · "
            + (f"전월 재직 {len(prev_names)}명" if prev_names else "전월 자료 없음"))
    return head + "\n" + "\n".join(lines), id_map


def build_free_payload(pstate: Dict[str, Any]) -> Tuple[str, Dict[str, str]]:
    frees = [f for f in pstate.get("freelancers", []) if str(f.get("성명") or "").strip()]
    ym = str(pstate.get("year_month") or datetime.now().strftime("%Y-%m"))
    prev = {str(f.get("성명") or "").strip(): _i(f.get("지급총액")) for f in (pstate.get("prev_freelancers") or [])}
    id_map: Dict[str, str] = {}
    lines = ["번호|업종코드|지급총액|소득세|지방소득세|전월지급액"]
    for n, f in enumerate(frees, 1):
        fid = f"F{n:02d}"
        id_map[fid] = str(f.get("성명")).strip()
        code = re.sub(r"\D", "", str(f.get("소득구분") or "940909"))[:6] or "940909"
        lines.append("|".join(str(x) for x in (
            fid, code, _i(f.get("지급총액")), _i(f.get("소득세")), _i(f.get("지방소득세")),
            prev.get(id_map[fid], 0) if prev else "?",
        )))
    emp_cnt = len([e for e in pstate.get("employees", []) if str(e.get("성명") or "").strip()])
    head = f"귀속 {ym} · 사업소득자 {len(frees)}명 · 같은 회사 근로소득자 {emp_cnt}명 · 전월 자료 {'있음' if prev else '없음'}"
    return head + "\n" + "\n".join(lines), id_map


# ── 프롬프트 ─────────────────────────────────────────────────────────
def build_prompt(kind: str, payload: str) -> str:
    scope = EMP_LAW_SCOPE if kind == "emp" else FREE_LAW_SCOPE
    who = "근로소득자(4대보험 가입 직원)" if kind == "emp" else "3.3% 사업소득자(프리랜서)"
    focus = ("직원 구성(나이·입사일·인원 증감)과 급여 구성(비과세·감면 적용 여부)을 보고 회사와 직원이 줄일 수 있는 세금·보험료를 찾으세요."
             if kind == "emp" else
             "지급 대상의 계속성·금액·업종코드를 보고 원천징수·신고 위험과 절세·정리 방안을 찾으세요.")
    scope_txt = "\n".join(f"[{i}] {t}: {c}" for i, (t, c) in enumerate(scope, 1))
    return f"""당신은 한국 세무사 사무실의 급여·원천세 검토 담당자입니다. {who} 자료를 검토해 맞춤 절세 방안을 제시합니다.
{focus}

규칙:
1. 판단 근거는 아래 '검토 범위 법령'(기준 {SCOPE_BASE_DATE})만 사용하세요. 범위 밖 제도는 'extra'에 제목만 적으세요. 법령 내용을 지어내지 마세요.
2. 사람은 번호(E01, F01 등)로만 가리키세요. 자료로 판단할 수 없는 요건(장애인·경력단절·병역·최대주주 친족 여부 등)은 'checks'에 확인할 내용을 적으세요.
3. 금액 효과는 자료로 계산할 수 있을 때만 숫자로(예: E03 월 소득세 31,730원 × 90% = 월 28,550원), 아니면 '요건 확인 후 산정'이라고 쓰세요. 10원 미만은 버리세요.
4. 이미 적용 중이고 문제없는 항목은 쓰지 말고, 실제로 도움이 되는 방안만 중요한 순서로 최대 8개.
5. 대표·임원은 소득세 감면 대상이 아닙니다.
6. 한국어 존댓말, 짧고 쉬운 문장. JSON 하나만 출력하세요(설명·코드블록 금지).

출력 형식:
{{"summary":"2~3문장 총평","items":[{{"title":"방안","targets":["E01"],"basis":"근거 법령 번호와 이름","effect":"예상 효과","action":"실무자가 할 일"}}],"checks":["확인 필요 사항"],"extra":["범위 밖 추가 검토 권장 제목"]}}

검토 범위 법령:
{scope_txt}

검토 자료(| 구분, 금액 단위 원, ?는 자료 없음):
{payload}
"""


def _extract_json(raw: str) -> Optional[Dict[str, Any]]:
    s = str(raw or "").strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s)
    m = re.search(r"\{.*\}", s, re.S)
    for cand in (s, m.group(0) if m else ""):
        if not cand:
            continue
        try:
            obj = json.loads(cand)
            if isinstance(obj, dict):
                return obj
        except Exception:
            continue
    return None


def _names(text: Any, id_map: Dict[str, str]) -> str:
    t = re.sub(r"(?<![A-Za-z0-9])([EF]\d{2,3})(?!\d)", lambda m: id_map.get(m.group(1), m.group(1)), str(text or ""))
    return re.sub(r"\[\d{1,2}\]\s*", "", t)


def build_ai_report(kind: str, ai: Dict[str, Any], id_map: Dict[str, str], header: Dict[str, str]) -> Dict[str, Any]:
    """AI 답변(JSON)을 당월 검토보고와 같은 구조(sections)로 바꿉니다."""
    scope = EMP_LAW_SCOPE if kind == "emp" else FREE_LAW_SCOPE
    rows = []
    for it in (ai.get("items") or [])[:8]:
        if not isinstance(it, dict):
            continue
        tg = it.get("targets") or []
        tg_txt = ", ".join(id_map.get(str(t), str(t)) for t in tg) if isinstance(tg, list) else _names(tg, id_map)
        rows.append([_names(it.get("title"), id_map), tg_txt or "전체", _names(it.get("basis"), id_map),
                     _names(it.get("effect"), id_map), _names(it.get("action"), id_map)])
    checks = [_names(c, id_map) for c in (ai.get("checks") or []) if str(c).strip()]
    extra = [_names(c, id_map) for c in (ai.get("extra") or []) if str(c).strip()]
    label = "근로소득자" if kind == "emp" else "사업소득자"
    sections: List[Dict[str, Any]] = [
        {"heading": f"[{header['corp']}] {header['ym']} 귀속 AI 맞춤 절세 검토 ({label})",
         "intro": _names(ai.get("summary"), id_map) or "검토 결과 요약이 없습니다."},
        {"heading": "절세 방안", "align": "left",
         "headers": ["절세 방안", "대상", "근거", "예상 효과", "해야 할 일"],
         "widths": [17.0, 15.0, 18.0, 20.0, 30.0],
         "rows": rows or [["제시된 방안 없음", "-", "-", "-", "-"]]},
    ]
    bl = [(f"확인 {n}", c) for n, c in enumerate(checks, 1)]
    if bl:
        sections.append({"heading": "확인이 필요한 사항", "bullets": bl})
    if extra:
        sections.append({"heading": "검토 범위 밖 — 추가 검토 권장", "bullets": [(f"{n}", c) for n, c in enumerate(extra, 1)]})
    sections.append({"heading": "검토 범위와 유의사항",
                     "notes": [f"AI가 아래 법령 범위(기준 {SCOPE_BASE_DATE})만으로 검토한 결과입니다. 실제 적용 전 요건과 최신 개정 여부를 확인해 주세요."]
                     + [t for t, _ in scope]
                     + ["개인정보 보호: AI에는 이름·주민등록번호 없이 번호·나이·입사일·금액만 보냈고, 화면에서 이름으로 다시 바꿔 표시했습니다."]})
    return {"title": f"AI 맞춤 절세 검토 ({label})", "kind": "AI절세", "accent": "#0f766e", "sections": sections}


def payload_hash(kind: str, payload: str) -> str:
    return hashlib.sha256(f"{kind}|{SCOPE_BASE_DATE}|{payload}".encode("utf-8")).hexdigest()[:20]


def run_ai_tax_review(kind: str, pstate: Dict[str, Any], header: Dict[str, str],
                      call_fn: Callable[[str], str]) -> Tuple[Optional[Dict[str, Any]], str]:
    """AI 검토 실행. 성공 시 (보고서, ""), 실패 시 (None, 오류 안내)."""
    payload, id_map = (build_emp_payload if kind == "emp" else build_free_payload)(pstate)
    if not id_map:
        return None, "검토할 인원이 없습니다. 표에 자료를 먼저 넣어 주세요."
    raw = call_fn(build_prompt(kind, payload))
    if not raw:
        return None, "AI 응답을 받지 못했습니다. API 키 또는 사용량을 확인한 뒤 다시 시도해 주세요."
    ai = _extract_json(raw)
    if not ai:
        return None, "AI 응답 형식을 읽지 못했습니다. 다시 시도해 주세요."
    return build_ai_report(kind, ai, id_map, header), ""
