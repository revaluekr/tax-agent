# -*- coding: utf-8 -*-
"""
상시근로자 판정 및 연평균 인원 계산 (화면·AI와 무관한 순수 계산 엔진)

[첨부 PDF 법령 및 심판례 명세 반영]
1. 인원 합계는 근로자별 (해당 과세연도 근무개월 수 ÷ 해당 과세연도 개월 수)를 Fraction(분수)으로 끝까지 합산한 뒤,
   최종 합계에서 단 1회만 소수점 셋째 자리 이하를 버립니다(100분의 1 미만 절사, 조특령 제11조의2 제8항).
2. 청년등외상시근로자 수 = 전체 상시근로자 수(절사 후) - 청년등상시근로자 수(절사 후)로 계산하여
   단수 차이(0.01명 오차)를 원천 차단합니다(조특법 제29조의8 제1항 제2호).
3. 청년등 증가 인원 및 청년등외 증가 인원은 각각 '전체 상시근로자 증가 인원 수'를 한도(Cap)로 합니다(조심2023부6839).
4. 2026년 귀속부터 비교 대상 직전 3개 과세연도(A·B·C) 중 '2024년 12월 31일 이전에 개시한 과세연도'는
   신규 공제 비교 대상에서 자동 제외합니다(2026년 귀속 시 B=0, C=0 / 2027년 귀속 시 C=0).
5. 육아휴직 등으로 급여가 없고 4대보험 납부유예로 납부사실도 없는 달은 제외 안내(조심2026소1019),
   경력단절 근로자 동일 기업 재취업 요건 및 실제 근로계약서 구비 안내(조심2024서5382)를 오류검토에 반영합니다.
"""
from __future__ import annotations

from datetime import date, datetime
from calendar import monthrange
from fractions import Fraction
from decimal import Decimal, ROUND_DOWN
import re

from . import rules as R


# ══════════════════════════════════════════════════════════════════
# 1. 날짜·나이·절사 유틸
# ══════════════════════════════════════════════════════════════════
def parse_date(val) -> date | None:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    s = str(val).strip()
    if not s or s.lower() in ("nan", "none", "nat", "-"):
        return None
    digits = re.sub(r"[^0-9]", "", s)
    try:
        if len(digits) == 8:
            return date(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))
    except ValueError:
        return None
    return None


def fmt_date(d: date | None) -> str:
    return d.isoformat() if d else ""


def add_years(d: date, n: int) -> date:
    try:
        return d.replace(year=d.year + n)
    except ValueError:                      # 2월 29일 윤년 처리
        return d.replace(year=d.year + n, day=28)


def full_age(birth: date | None, ref: date | None, military_months: int = 0) -> int | None:
    """만 나이 계산. 병역기간(최대 6년=72개월)은 생일을 그만큼 늦춘 것으로 보아 현재 연령에서 차감."""
    if not birth or not ref:
        return None
    m = max(0, min(int(military_months or 0), R.MILITARY_MAX_MONTHS))
    by, bm = birth.year, birth.month + m
    by += (bm - 1) // 12
    bm = (bm - 1) % 12 + 1
    bd = min(birth.day, monthrange(by, bm)[1])
    adj_birth = date(by, bm, bd)
    age = ref.year - adj_birth.year - ((ref.month, ref.day) < (adj_birth.month, adj_birth.day))
    return age


def month_end(year: int, month: int) -> date:
    return date(year, month, monthrange(year, month)[1])


def trunc2(x: Fraction | float) -> float:
    """100분의 1 미만 버림(소수점 셋째 자리 이하 절사 — 조특령 제11조의2 제8항)."""
    d = Decimal(x.numerator) / Decimal(x.denominator) if isinstance(x, Fraction) else Decimal(str(x))
    return float(d.quantize(Decimal("0.01"), rounding=ROUND_DOWN))


# ══════════════════════════════════════════════════════════════════
# 2. 사업자 판정 및 비교 과세연도 규칙
# ══════════════════════════════════════════════════════════════════
def is_excluded_industry(biz_type_text: str) -> bool:
    t = (biz_type_text or "").replace(" ", "")
    if any(ex in t for ex in R.EXCLUDED_INDUSTRY_EXCEPTIONS):
        return False
    return any(k in t for k in R.EXCLUDED_INDUSTRY_KEYWORDS)


def is_capital_area(address: str) -> bool | None:
    a = (address or "").strip()
    if not a:
        return None
    return any(a.startswith(k) or k in a[:6] for k in R.CAPITAL_AREA_KEYWORDS)


def active_months(year: int, months_in_year: int) -> list[int]:
    """사업연도 월수가 12 미만이면(연도 중 신규 창업 등) 연말 쪽 N개월만 사업연도로 봄 (12월 결산 가정)."""
    n = max(1, min(12, int(months_in_year or 12)))
    return list(range(13 - n, 13))


def default_months_for_year(year: int, founded: date | None) -> int:
    if founded and founded.year == year:
        return max(1, 12 - founded.month + 1)
    if founded and founded.year > year:
        return 0
    return 12


def valid_comparison_years_for_new_credit(tax_year: int) -> dict[str, int | None]:
    """
    [조특법 제29조의8 제1항 각 호 외의 부분 본문 단서]
    2026년 귀속부터 직전 3개 과세연도(A 직전, B 전전, C 전전전)와 비교할 때
    '2024년 12월 31일 이전에 개시한 과세연도는 제외'합니다.
    - 2026년 귀속: A=2025, B=None(2024 제외), C=None(2023 제외)
    - 2027년 귀속: A=2026, B=2025, C=None(2024 제외)
    - 2028년 귀속: A=2027, B=2026, C=2025
    - 2024·2025년 귀속(구법): A=tax_year-1 단일 비교
    """
    t = int(tax_year)
    if t <= 2025:
        return {"A": t - 1, "B": None, "C": None}
    return {
        "A": (t - 1) if (t - 1) >= 2025 else None,
        "B": (t - 2) if (t - 2) >= 2025 else None,
        "C": (t - 3) if (t - 3) >= 2025 else None,
    }


def calc_increase_with_cap(
    cur_total: float, cur_youth: float, cur_general: float,
    base_total: float, base_youth: float, base_general: float
) -> dict[str, float]:
    """
    [필수 한도(Cap) 로직 — 조특법 제29조의8 제1항 제1호·제2호 및 조심2023부6839]
    청년등 증가 인원수와 청년등외 증가 인원수는 각각 '전체 상시근로자의 증가 인원수'를 한도로 하며,
    계산값이 음수인 경우 0으로 봅니다.
    """
    total_inc = trunc2(max(0.0, round(cur_total - base_total, 2)))
    if total_inc <= 0:
        return {"전체_증가": 0.0, "청년등_증가": 0.0, "청년등외_증가": 0.0}

    raw_youth_inc = max(0.0, round(cur_youth - base_youth, 2))
    raw_gen_inc = max(0.0, round(cur_general - base_general, 2))

    capped_youth_inc = trunc2(min(raw_youth_inc, total_inc))
    capped_gen_inc = trunc2(min(raw_gen_inc, round(total_inc - capped_youth_inc, 2)))
    return {
        "전체_증가": total_inc,
        "청년등_증가": capped_youth_inc,
        "청년등외_증가": capped_gen_inc,
        "청년등_한도적용전": trunc2(raw_youth_inc),
        "청년등외_한도적용전": trunc2(raw_gen_inc),
    }


# ══════════════════════════════════════════════════════════════════
# 3. 근로자 판정
# ══════════════════════════════════════════════════════════════════
def employed_at_month_end(hire: date | None, retire: date | None, year: int, month: int) -> bool:
    """매월 말 현재 근무 여부(조특령 제11조의2 제8항). 말일 퇴사자는 말일 현재 근무한 것으로 산입."""
    if not hire:
        return False
    me = month_end(year, month)
    if hire > me:
        return False
    if retire and retire < me:
        return False
    return True


def worked_in_year(person: dict, year: int) -> bool:
    """해당 연도 원천징수부 급여 이력이 있거나 입·퇴사일 기간이 해당 연도에 걸치는지 판정."""
    pay_map = person.get("월급여") or {}
    if str(year) in pay_map:
        return True
    hire, retire = parse_date(person.get("입사일")), parse_date(person.get("퇴사일"))
    if not hire:
        return True                       # 입사일 미확인자는 표에 표시하고 오류검토에서 안내
    if hire > date(year, 12, 31):
        return False
    if retire and retire < date(year, 1, 1):
        return False
    return True


def tenure_under_1y(person: dict) -> bool:
    """퇴사자 중 입사일~퇴사일 실제 근로기간이 1년 미만인 경우(조특령 제26조의8 제2항 제1호)."""
    hire, retire = parse_date(person.get("입사일")), parse_date(person.get("퇴사일"))
    if not hire or not retire:
        return False
    return retire < add_years(hire, 1)


def contract_date(person: dict) -> date | None:
    return parse_date(person.get("계약체결일")) or parse_date(person.get("입사일"))


def contract_age(person: dict) -> int | None:
    return full_age(parse_date(person.get("생년월일")), contract_date(person), person.get("병역개월", 0))


def youth_hold_years(corp_size: str) -> int:
    return R.YOUTH_HOLD_YEARS_LARGE if corp_size == "일반기업" else R.YOUTH_HOLD_YEARS_SME


def is_youth_month(person: dict, year: int, month: int, corp_size: str) -> bool:
    """
    [조특령 제26조의8 제4항 제1호]
    청년 정규직: 그 달 말일 현재 만 15~34세(병역 최대 6년 차감)이거나,
    근로계약 체결 당시 만 15~34세였고 체결일부터 4년(일반기업 3년) 이내인 달.
    """
    birth = parse_date(person.get("생년월일"))
    me = month_end(year, month)
    mil = person.get("병역개월", 0)
    age_now = full_age(birth, me, mil)
    if age_now is not None and R.YOUTH_AGE_MIN <= age_now <= R.YOUTH_AGE_MAX:
        return True
    c_dt, c_age = contract_date(person), contract_age(person)
    if c_dt and c_age is not None and R.YOUTH_AGE_MIN <= c_age <= R.YOUTH_AGE_MAX:
        return me < add_years(c_dt, youth_hold_years(corp_size))
    return False


def youth_options(emp_type: str) -> list[str]:
    """
    기간제·단시간근로자는 제1호(청년 정규직)에서만 제외되며,
    제2호(장애인 등), 제3호(취업시 60세 이상), 제4호(경력단절), 제5호(북한이탈주민)는 선택 가능!
    """
    return R.YOUTH_TYPES_NON_REGULAR if emp_type in R.EMP_NOT_YOUTH_REGULAR else R.YOUTH_TYPES


def suggest_exclusion(person: dict, yrec: dict) -> str:
    emp = yrec.get("고용유형") or R.EMP_REGULAR
    if emp in R.EMP_AUTO_EXCLUDE:
        return R.EMP_AUTO_EXCLUDE[emp]
    if person.get("외국인"):
        return R.EXCL_FOREIGN
    if person.get("주주관계") in ("최대주주", "최대주주의 배우자", "최대주주의 직계존비속 등"):
        return person["주주관계"]
    if tenure_under_1y(person):
        return R.EXCL_UNDER_1Y
    return R.EXCL_NONE


def suggest_youth(person: dict, yrec: dict, year: int, corp_size: str) -> str:
    emp = yrec.get("고용유형") or R.EMP_REGULAR
    c_age = contract_age(person)
    # 제3호: 근로계약 체결일 현재 60세 이상 (단시간·기간제도 포함)
    if c_age is not None and c_age >= R.SENIOR_AGE:
        return R.YOUTH_SENIOR
    # 제1호: 청년 정규직 (기간제·단시간 제외)
    if emp not in R.EMP_NOT_YOUTH_REGULAR:
        if any(is_youth_month(person, year, m, corp_size) for m in range(1, 13)):
            return R.YOUTH_YOUNG
    return R.YOUTH_NONE


def _pick(yrec: dict, field: str, suggestion: str) -> str:
    """사용자가 직접 고른 값이 있으면 그 값, 없으면 자동 제안값."""
    if field in (yrec.get("_user_set") or []):
        val = yrec.get(field)
        if val == R.EXCL_UNDER_1Y_LEGACY:
            return R.EXCL_UNDER_1Y
        return val or suggestion
    return suggestion


# ══════════════════════════════════════════════════════════════════
# 4. 한 사람·한 연도 계산
# ══════════════════════════════════════════════════════════════════
def compute_row(person: dict, yrec: dict, year: int, ctx: dict) -> dict:
    """
    ctx: corp_size, months_in_year(해당 연도 사업연도 월수)
    반환: 화면에 그릴 확정값 (제외사유·청년등·상시 O/X·월별값·합계·평균·경고)
    """
    corp_size = ctx.get("corp_size", "중소기업")
    act = active_months(year, ctx.get("months_in_year", 12))
    emp = yrec.get("고용유형") or R.EMP_REGULAR

    # ① 제외사유 — 고용유형으로 자동 제외되면 무조건 그 사유(대분류 우선)
    if emp in R.EMP_AUTO_EXCLUDE:
        excl = R.EMP_AUTO_EXCLUDE[emp]
    else:
        excl = _pick(yrec, "제외사유", suggest_exclusion(person, yrec))

    auto_regular = excl == R.EXCL_NONE
    ovr = yrec.get("상시_override") or ""
    is_regular = auto_regular if ovr not in ("O", "X") else (ovr == "O")

    # ② 청년등 — 상시근로자일 때만
    allowed = youth_options(emp)
    if is_regular:
        youth = _pick(yrec, "청년등", suggest_youth(person, yrec, year, corp_size))
        if youth not in allowed:
            youth = suggest_youth(person, yrec, year, corp_size)
    else:
        youth = ""

    # ③ 월별 값 (인별 근무개월 가중치 합산)
    weight = R.EMP_WEIGHT.get(emp, 1.0)
    hire, retire = parse_date(person.get("입사일")), parse_date(person.get("퇴사일"))
    # 해당 연도에 재입사하기 전 과거 퇴사일이 다른 연도에만 해당하면 무시하도록 안전 처리
    yr_retire_map = person.get("연도별_퇴사일") or {}
    if str(year) in yr_retire_map:
        retire = parse_date(yr_retire_map[str(year)])
    elif retire and retire.year < year and str(year) in (person.get("월급여") or {}):
        retire = None

    overrides = {int(k): float(v) for k, v in (yrec.get("월_override") or {}).items()}
    pay = (person.get("월급여") or {}).get(str(year))

    months, auto_months, youth_flags, no_pay = [], [], [], []
    for m in range(1, 13):
        if m not in act:
            months.append(None); auto_months.append(None); youth_flags.append(False)
            continue
        auto_v = weight if (is_regular and employed_at_month_end(hire, retire, year, m)) else 0.0
        v = overrides.get(m, auto_v) if is_regular else 0.0
        months.append(v)
        auto_months.append(auto_v)
        if youth == R.YOUTH_YOUNG:
            y_flag = is_youth_month(person, year, m, corp_size)
        else:
            y_flag = bool(youth) and youth != R.YOUTH_NONE
        youth_flags.append(bool(v) and y_flag)
        if v and pay and len(pay) == 12 and not (pay[m - 1] or 0):
            no_pay.append(m)

    n = len(act) or 12
    row_sum = sum(Fraction(str(v)) for v in months if v)
    youth_sum = sum(Fraction(str(v)) for v, yf in zip(months, youth_flags) if v and yf)

    return {
        "제외사유": excl,
        "청년등": youth,
        "상시": "O" if is_regular else "X",
        "상시_auto": "O" if auto_regular else "X",
        "months": months,
        "auto_months": auto_months,
        "youth_flags": youth_flags,
        "row_sum": row_sum,
        "youth_sum": youth_sum,
        "row_avg": float(row_sum / n) if n else 0.0,
        "youth_options": allowed,
        "no_pay_months": no_pay,
        "excl_locked": emp in R.EMP_AUTO_EXCLUDE,
    }


# ══════════════════════════════════════════════════════════════════
# 5. 연도 합계 (근로자별 비율 합산 후 최종 1회 소수점 셋째 자리 버림)
# ══════════════════════════════════════════════════════════════════
def year_totals(computed_rows: list[dict], months_in_year: int) -> dict:
    n = max(1, min(12, int(months_in_year or 12)))
    # 조특령 제11조의2 제8항: 상시근로자별 (근무개월 수 ÷ 과세연도 개월 수)의 합에서 100분의 1 미만 버림
    total_ratio_sum = sum((r["row_sum"] / Fraction(n) for r in computed_rows), Fraction(0))
    youth_ratio_sum = sum((r["youth_sum"] / Fraction(n) for r in computed_rows), Fraction(0))

    total_months_sum = sum((r["row_sum"] for r in computed_rows), Fraction(0))
    youth_months_sum = sum((r["youth_sum"] for r in computed_rows), Fraction(0))

    regular = trunc2(total_ratio_sum)
    youth_cnt = trunc2(youth_ratio_sum)
    general = round(regular - youth_cnt, 2)          # 청년등외 = 전체 상시(절사후) − 청년등(절사후)

    month_regular, month_youth = [], []
    for m in range(12):
        vals = [r["months"][m] for r in computed_rows]
        if all(v is None for v in vals):
            month_regular.append(None); month_youth.append(None)
            continue
        month_regular.append(float(sum(Fraction(str(v)) for v in vals if v)))
        month_youth.append(float(sum(Fraction(str(r["months"][m])) for r in computed_rows
                                     if r["months"][m] and r["youth_flags"][m])))
    month_general = [None if a is None else round(a - b, 2) for a, b in zip(month_regular, month_youth)]

    return {
        "상시_합계": float(total_months_sum),
        "청년등_합계": float(youth_months_sum),
        "청년외_합계": float(total_months_sum - youth_months_sum),
        "상시_평균": regular,
        "청년등_평균": youth_cnt,
        "청년외_평균": general,
        "월별_상시": month_regular,
        "월별_청년등": month_youth,
        "월별_청년외": month_general,
        "months_in_year": n,
    }


def regular_excluding_part_time(computed_rows: list[dict], emp_types: list[str], months_in_year: int) -> float:
    """0.75명 특례 요건① 판정용 — 단시간근로자를 제외한 상시근로자 수."""
    n = max(1, min(12, int(months_in_year or 12)))
    total_ratio = sum((r["row_sum"] / Fraction(n) for r, e in zip(computed_rows, emp_types)
                       if e not in (R.EMP_PT_050, R.EMP_PT_075)), Fraction(0))
    return trunc2(total_ratio)


# ══════════════════════════════════════════════════════════════════
# 6. 오류 검토 (법령 + 최신 조세심판례 8대 체크포인트 탑재)
# ══════════════════════════════════════════════════════════════════
def review(people: dict, year_recs: dict, years: list[int], ctx_by_year: dict,
           computed: dict, prev_filing: dict | None = None) -> list[tuple[str, str]]:
    """반환: [(수준, 메시지)], 수준은 '오류' 또는 '확인'"""
    out: list[tuple[str, str]] = []

    for pid, p in people.items():
        nm = p.get("성명") or "(이름없음)"
        birth, hire, retire = (parse_date(p.get(k)) for k in ("생년월일", "입사일", "퇴사일"))
        if not birth:
            out.append(("오류", f"{nm}: 생년월일이 없어 청년(15~34세)·60세 이상 판정을 할 수 없습니다."))
        if not hire:
            out.append(("오류", f"{nm}: 입사일(근로계약 체결일)이 없어 월별 근무 및 연령 판정을 할 수 없습니다."))
        if hire and retire and retire < hire:
            out.append(("오류", f"{nm}: 퇴사일({retire})이 입사일({hire})보다 빠릅니다."))

    for y in years:
        rows = computed.get(y, {})
        for pid, c in rows.items():
            p, yrec = people[pid], year_recs[y][pid]
            nm = p.get("성명") or "(이름없음)"
            emp = yrec.get("고용유형") or R.EMP_REGULAR

            # 1) 육아휴직·무급휴직 심판례 체크 (조심2026소1019)
            if c["no_pay_months"]:
                ms = ", ".join(f"{m}월" for m in c["no_pay_months"])
                out.append((
                    "확인",
                    f"[{y}] {nm}: {ms}에 원천징수 급여 지급액이 0원입니다. 육아휴직·무급휴직 중 건강보험 납입고지 유예 및 국민연금 납부예외로 "
                    f"실제 4대보험 납부사실도 모두 없다면 상시근로자에서 제외해야 합니다(조심2026소1019). 해당 월을 0으로 바꿀지 확인하세요."
                ))

            # 2) 60세 이상 근로계약 체결일 시점 체크 (조특령 제26조의8 제4항 제3호)
            if c["청년등"] == R.YOUTH_SENIOR:
                a = contract_age(p)
                if a is not None and a < R.SENIOR_AGE:
                    out.append((
                        "오류",
                        f"[{y}] {nm}: 근로계약 체결일(입사일) 기준 만 {a}세이므로 '취업시 60세 이상'에 해당하지 않습니다 "
                        f"(근무 중 60세가 도래해도 자동 전환 불가 — 조특령 제26조의8 제4항 제3호)."
                    ))

            # 3) 청년 정규직 기간제·단시간 배제 및 연령 유예 체크
            if c["청년등"] == R.YOUTH_YOUNG:
                if emp in R.EMP_NOT_YOUTH_REGULAR:
                    out.append((
                        "오류",
                        f"[{y}] {nm}: 기간제·단시간근로자({emp})는 만 15~34세이더라도 청년 정규직에서 명시적으로 제외됩니다 "
                        f"(전체 상시근로자에는 포함되나 청년등외로 분류 — 조특령 제26조의8 제4항 제1호 가목)."
                    ))
                elif not any(c["youth_flags"]):
                    out.append((
                        "확인",
                        f"[{y}] {nm}: '취업시 청년(4년)'으로 선택했지만 {y}년에 청년 요건(계약체결 시 34세 이하 & 체결일부터 4년/대기업 3년 이내)을 "
                        f"충족하는 달이 없습니다. 병역기간(최대 72개월) 차감 여부를 확인하세요."
                    ))

            # 4) 경력단절 근로자 동일 기업 재취업 요건 체크 (조특법 제29조의8 제2항 제1호)
            if c["청년등"] == R.YOUTH_CAREER:
                out.append((
                    "확인",
                    f"[{y}] {nm}: '경력단절 근로자'는 반드시 **동일 기업**에서 1년 이상 근무 후 결혼·임신·출산·육아·자녀교육·가족돌봄 사유로 퇴직하고 "
                    f"퇴직일로부터 2년 이상 15년 미만에 재취업한 경우만 해당합니다(타 기업 퇴직 후 채용은 비해당)."
                ))

            # 5) 주주명부상 최대주주·친족 체크
            if p.get("주주관계") and c["상시"] == "O":
                out.append(("확인", f"[{y}] {nm}: 주주명부상 '{p['주주관계']}'로 확인되는데 상시근로자(O)에 포함되어 있습니다."))

            # 6) 0.75명 단시간근로자 4대 요건 체크 (조특령 제11조의2 제8항 제2호)
            if emp == R.EMP_PT_075:
                out.append((
                    "확인",
                    f"[{y}] {nm}: 단시간 0.75명 특례는 ①단시간 제외 상시근로자 수 미감소, ②기간의 정함이 없는 근로계약(무기계약), "
                    f"③차별적 처우 없음, ④시간당 임금이 최저임금의 120%(중견·일반 130%) 이상 요건을 모두 충족하고 실제 근로계약서가 구비되어야 합니다(조심2024서5382)."
                ))

        # 7) 0.75명 요건① — 단시간 제외 상시근로자 수가 직전연도보다 감소하지 않았을 것
        if y - 1 in computed and any(year_recs[y][pid].get("고용유형") == R.EMP_PT_075 for pid in rows):
            cur = regular_excluding_part_time(
                list(rows.values()),
                [year_recs[y][pid].get("고용유형") for pid in rows],
                ctx_by_year[y]["months_in_year"]
            )
            prv_rows = computed[y - 1]
            prv = regular_excluding_part_time(
                list(prv_rows.values()),
                [year_recs[y - 1][pid].get("고용유형") for pid in prv_rows],
                ctx_by_year[y - 1]["months_in_year"]
            )
            if cur < prv:
                out.append((
                    "오류",
                    f"[{y}] 단시간근로자 제외 상시근로자 수({cur}명)가 직전연도({y-1}년, {prv}명)보다 감소하여 "
                    f"단시간 0.75명 특례를 적용할 수 없습니다. 0.5명('단시간(60시간 이상)')으로 변경하세요."
                ))

    # 8) 기신고 명세서와 신법 재계산 인원 대조 안내
    if prev_filing:
        for y in years:
            filed = prev_filing.get(str(y))
            if filed and y in computed:
                t = year_totals(list(computed[y].values()), ctx_by_year[y]["months_in_year"])
                if filed.get("상시") is not None and abs(float(filed["상시"]) - t["상시_평균"]) >= 0.01:
                    out.append((
                        "확인",
                        f"[{y}] 기신고 명세서 상시근로자({filed['상시']}명) ↔ 이번 계산({t['상시_평균']}명) 차이가 있습니다. "
                        f"2026년 귀속 인별 합산 방식 개정 또는 신법 기준(만 15~34세 등) 재산정에 따른 차이인지 확인하세요."
                    ))

    return out
