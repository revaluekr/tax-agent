# -*- coding: utf-8 -*-
"""
[모듈 1/4] 통합고용세액공제 — 연도별 자격요건 · 청년 유예기간 · 1년 미만 경과조치 · 기초 유틸리티 (hc_eligibility.py)
- 매년 세법 시행령 개정으로 바뀔 수 있는 '청년 연령·유예기간', '1년 미만 제외 경과조치', '비교 대상 과세연도' 규정을 전담합니다.
- 향후 세법 개정 시 이 파일만 독립적으로 수정·덮어쓰기할 수 있습니다.
"""
from __future__ import annotations

from datetime import date, datetime
from calendar import monthrange
from fractions import Fraction
from decimal import Decimal, ROUND_DOWN
import re
from functools import lru_cache
from typing import Any

from . import rules as R

# 1. 날짜 · 연령 · 소수점 둘째자리 절사 · 월급여 조회 유틸리티
# ══════════════════════════════════════════════════════════════════
def parse_date(val) -> date | None:
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    if isinstance(val, datetime):
        return val.date()
    return _parse_date_str(str(val or ""))


@lru_cache(maxsize=65536)
def _parse_date_str(raw: str) -> date | None:
    """문자열 → 날짜 (같은 문자열은 한 번만 해석해 재사용, date는 바뀌지 않는 값이라 안전)"""
    s = raw.strip()
    if not s or s.lower() in ("none", "null", "nan", "nat", "-"):
        return None
    s = re.sub(r"[년월/.]", "-", s)
    s = re.sub(r"일|\s+", "", s).strip("-")
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m2 = re.match(r"^(\d{4})(\d{2})(\d{2})$", s)
    if m2:
        try:
            return date(int(m2.group(1)), int(m2.group(2)), int(m2.group(3)))
        except ValueError:
            return None
    return None


def fmt_date(d: date | None) -> str:
    return d.isoformat() if d else ""


def format_date_dot(val) -> str:
    d = parse_date(val)
    return d.strftime("%Y.%m.%d") if d else ""


def add_years(d: date, n: int) -> date:
    try:
        return d.replace(year=d.year + n)
    except ValueError:
        return d.replace(year=d.year + n, day=28)


def full_age(birth: date | None, ref: date | None, military_months: int = 0) -> int | None:
    try:
        mil = int(military_months or 0)
    except (TypeError, ValueError):
        mil = 0
    return _full_age_cached(birth, ref, mil)


@lru_cache(maxsize=131072)
def _full_age_cached(birth: date | None, ref: date | None, military_months: int = 0) -> int | None:
    """
    기준일(ref) 현재 만 나이 (병역이행기간 최대 72개월 차감 반영).
    - 조특령 제26조의8 제3항 제1호 가목: 병역을 이행한 후 취업한 경우 병역기간(6년 한도)을 빼고 연령 계산.
    """
    if not birth or not ref or ref < birth:
        return None
    mil = max(0, min(int(military_months or 0), R.MILITARY_MAX_MONTHS))
    y_add, m_add = divmod(mil, 12)
    ny = birth.year + y_add
    nm = birth.month + m_add
    if nm > 12:
        ny += (nm - 1) // 12
        nm = (nm - 1) % 12 + 1
    max_day = monthrange(ny, nm)[1]
    adj_birth = date(ny, nm, min(birth.day, max_day))
    if ref < adj_birth:
        return 0
    years = ref.year - adj_birth.year
    if (ref.month, ref.day) < (adj_birth.month, adj_birth.day):
        years -= 1
    return max(0, years)


@lru_cache(maxsize=4096)
def month_end(year: int, month: int) -> date:
    return date(year, month, monthrange(year, month)[1])


def trunc2(x: Fraction | float) -> float:
    """
    소수점 셋째 자리에서 버림(절사)하여 소수점 둘째 자리까지 반환 (조특령 제26조의8 제6항).
    """
    if isinstance(x, Fraction):
        if x >= 0:
            q = (x.numerator * 100) // x.denominator
            return q / 100.0
        q = ((-x.numerator) * 100) // x.denominator
        return -(q / 100.0)
    d = Decimal(str(round(float(x), 8)))
    return float(d.quantize(Decimal("0.01"), rounding=ROUND_DOWN))


def _get_month_pay(pay_obj: Any, month: int) -> float | None:
    """
    연도별 월급여 데이터가 dict({"1": 3000000, ...})이든 list([3000000, ...])이든
    100% 호환하여 해당 월(1~12)의 급여액을 반환합니다. 데이터가 아예 없으면 None을 반환합니다.
    """
    if not pay_obj:
        return None
    if isinstance(pay_obj, dict):
        raw = pay_obj.get(str(month), pay_obj.get(month, None))
        if raw is None:
            return None
        try:
            return float(raw or 0.0)
        except (TypeError, ValueError):
            return 0.0
    if isinstance(pay_obj, (list, tuple)):
        idx = month - 1
        if 0 <= idx < len(pay_obj):
            try:
                return float(pay_obj[idx] or 0.0)
            except (TypeError, ValueError):
                return 0.0
    return None


def _has_any_pay_record(pay_obj: Any) -> bool:
    if not pay_obj:
        return False
    if isinstance(pay_obj, dict):
        return len(pay_obj) > 0
    if isinstance(pay_obj, (list, tuple)):
        return len(pay_obj) > 0
    return False


# ══════════════════════════════════════════════════════════════════
# 2. 업종 · 소재지 · 과세연도 월수 판정
# ══════════════════════════════════════════════════════════════════
def is_excluded_industry(biz_type_text: str) -> bool:
    t = str(biz_type_text or "").replace(" ", "")
    if not t:
        return False
    for exc in R.EXCLUDED_INDUSTRY_EXCEPTIONS:
        if exc in t:
            return False
    return any(k in t for k in R.EXCLUDED_INDUSTRY_KEYWORDS)


def is_capital_area(address: str) -> bool | None:
    s = str(address or "").strip()
    if not s:
        return None
    return any(s.startswith(k) or k in s[:8] for k in R.CAPITAL_AREA_KEYWORDS)


def active_months(year: int, months_in_year: int) -> list[int]:
    n = max(1, min(12, int(months_in_year or 12)))
    return list(range(13 - n, 13))


def default_months_for_year(year: int, founded: date | None) -> int:
    if not founded:
        return 12
    if founded.year > year:
        return 12
    if founded.year < year:
        return 12
    return 12 - founded.month + 1


def valid_comparison_years_for_new_credit(tax_year: int) -> dict[str, int | None]:
    t = int(tax_year or R.DEFAULT_TAX_YEAR)
    if t <= 2025:
        return {"A": t - 1, "B": None, "C": None}
    return {
        "A": (t - 1) if (t - 1) >= 2025 else None,
        "B": (t - 2) if (t - 2) >= 2025 else None,
        "C": (t - 3) if (t - 3) >= 2025 else None,
    }


# ══════════════════════════════════════════════════════════════════
# 3. 재직 · 근로계약 1년 미만 · 청년등 상시근로자 판정 (사후관리 코호트별 분리)
# ══════════════════════════════════════════════════════════════════
def employed_at_month_end(hire: date | None, retire: date | None, year: int, month: int) -> bool:
    me = month_end(year, month)
    if hire and hire > me:
        return False
    if retire and retire < me:
        return False
    return True


def worked_in_year(person: dict, year: int) -> bool:
    pay_by_yr = (person.get("월급여") or {}).get(str(year))
    if _has_any_pay_record(pay_by_yr):
        if any((_get_month_pay(pay_by_yr, m) or 0.0) > 0 for m in range(1, 13)):
            return True
    hire = parse_date(person.get("입사일"))
    yr_ret_str = (person.get("연도별_퇴사일") or {}).get(str(year))
    retire = parse_date(yr_ret_str if yr_ret_str is not None else person.get("퇴사일"))
    if not hire:
        return False
    y_start = date(year, 1, 1)
    y_end = date(year, 12, 31)
    if hire > y_end:
        return False
    if retire and retire < y_start:
        return False
    return True


def tenure_under_1y(person: dict, year: int | None = None) -> bool:
    hire = parse_date(person.get("입사일"))
    yr_ret_str = (person.get("연도별_퇴사일") or {}).get(str(year)) if year else None
    retire = parse_date(yr_ret_str if yr_ret_str is not None else person.get("퇴사일"))
    if not hire or not retire or retire < hire:
        return False
    # 근로기간 1년 미만은 해당 과세연도 말 기준으로 판단: 과세연도 종료일 현재 재직 중이었다면
    # (그 뒤에 1년을 못 채우고 퇴사했더라도) 그 연도에는 1년 이상 근무할 것으로 봄. 퇴사한 연도에 제외.
    if year and retire > date(int(year), 12, 31):
        return False
    one_yr_later = add_years(hire, 1)
    return (retire.toordinal() - hire.toordinal() + 1) < (one_yr_later.toordinal() - hire.toordinal())


def contract_date(person: dict) -> date | None:
    return parse_date(person.get("계약체결일")) or parse_date(person.get("입사일"))


def contract_age(person: dict) -> int | None:
    birth = parse_date(person.get("생년월일"))
    c_dt = contract_date(person)
    mil = int(person.get("병역개월", 0) or 0)
    return full_age(birth, c_dt, mil)


def current_year_end_age(person: dict, year: int) -> int | None:
    birth = parse_date(person.get("생년월일"))
    mil = int(person.get("병역개월", 0) or 0)
    return full_age(birth, date(year, 12, 31), mil)


def youth_hold_years(corp_size: str, contract_dt: date | None = None) -> int:
    """
    근로계약 체결일 기준 청년 인정기간(년). 0이면 인정기간 없음(매달 나이로만 판정).
    - 2026년 이후 계약: 중소·중견 4년, 대기업 3년 / 2025년 계약: 중소·중견 3년, 대기업 2년 / 2024년 이전 계약: 0
    """
    large = corp_size in ("일반기업", "대기업")
    if contract_dt is None or contract_dt.year >= 2026:
        return R.YOUTH_HOLD_YEARS_LARGE if large else R.YOUTH_HOLD_YEARS_SME
    if contract_dt.year == 2025:
        return getattr(R, "YOUTH_HOLD_YEARS_2025_LARGE", 2) if large else getattr(R, "YOUTH_HOLD_YEARS_2025_SME", 3)
    return 0


def is_youth_month(person: dict, year: int, month: int, corp_size: str, use_hold: bool = True) -> bool:
    """
    청년 정규직 해당 여부(월말 기준).
    use_hold=True : 2026.2.27. 개정 정의(계약일 기준 유예 포함) — 2025년 이후 최초공제분·당해 판정
    use_hold=False: 종전 정의(매달 나이로만 판정) — 2024년 이전 최초공제분의 사후관리
    """
    birth = parse_date(person.get("생년월일"))
    c_dt = contract_date(person)
    if not birth or not c_dt:
        return False
    mil = int(person.get("병역개월", 0) or 0)
    age_at_contract = full_age(birth, c_dt, mil)
    if age_at_contract is None or not (R.YOUTH_AGE_MIN <= age_at_contract <= R.YOUTH_AGE_MAX):
        return False

    me = month_end(year, month)
    if me < c_dt:
        return False

    age_at_me = full_age(birth, me, mil)
    if age_at_me is not None and R.YOUTH_AGE_MIN <= age_at_me <= R.YOUTH_AGE_MAX:
        return True

    # 34세를 넘은 달: 근로계약 체결일 기준 인정기간 안이면 청년 (2024년 이전 계약은 인정기간 없음)
    if not use_hold:
        return False
    hold = youth_hold_years(corp_size, c_dt)
    if hold <= 0:
        return False
    hold_end = add_years(c_dt, hold)          # 청년 제외시점 (이 날부터 청년 아님)
    return me < hold_end


def was_youth_in_year_by_age(person: dict, year: int, corp_size: str) -> bool:
    """사원표가 없을 때의 보조 판정: 그해(year) 매월 말 재직한 달 중 청년 요건을 충족한 달이 실제로 있었는지 검증."""
    hire = parse_date(person.get("입사일"))
    yr_ret = (person.get("연도별_퇴사일") or {}).get(str(year))
    retire = parse_date(yr_ret if yr_ret is not None else person.get("퇴사일"))
    return any(
        employed_at_month_end(hire, retire, year, m) and is_youth_month(person, year, m, corp_size)
        for m in range(1, 13)
    )


NEW_YOUTH_DEF_FROM_COHORT = 2025   # 2025.1.1. 이후 개시 과세연도를 최초공제연도로 하는 분부터 새 정의(시행령 부칙 제36127호 제11조)


def youth_flag_old_def(person: dict, year: int, month: int, corp_size: str, youth_label: str) -> bool:
    """종전 정의의 '실제' 청년등 여부(간주 없음): 2024년 이전 최초공제분의 연속공제 판정용 (서면-2023-법인-0978)"""
    if youth_label in (R.YOUTH_SENIOR, R.YOUTH_DISABLED, R.YOUTH_CAREER):
        return True
    if youth_label == R.YOUTH_YOUNG and parse_date(person.get("생년월일")) and contract_date(person) is not None:
        return is_youth_month(person, year, month, corp_size, use_hold=False)
    return False                    # 북한이탈주민은 2025년 이후 최초공제분부터 청년등


def is_youth_month_for_cohort(
    person: dict,
    eval_year: int,
    month: int,
    cohort_year: int,
    corp_size: str,
    youth_label: str,
    was_youth_in_cohort: bool | None = None,
) -> bool:
    """
    2024년 이전 최초공제분의 추가납부용 청년등 판정 (구 조특령 제26조의8 제5항 간주)
    = 종전 정의상 현재 청년등  OR  최초공제연도(cohort_year)에 청년등이었던 사람
    ※ 2025년 이후 최초공제분은 제5항이 삭제되어 간주 없이 새 정의(당해 판정)를 그대로 씀 → compute_row에서 처리
    """
    if youth_label in (R.YOUTH_SENIOR, R.YOUTH_DISABLED, R.YOUTH_CAREER):
        return True
    if youth_label == R.YOUTH_NK:
        return cohort_year >= 2025
    if youth_label == R.YOUTH_YOUNG and parse_date(person.get("생년월일")) and \
            is_youth_month(person, eval_year, month, corp_size, use_hold=cohort_year >= NEW_YOUTH_DEF_FROM_COHORT):
        return True
    if was_youth_in_cohort is None:
        if not parse_date(person.get("생년월일")):
            return False                       # 생년월일을 모르면 청년으로 보지 않음
        was_youth_in_cohort = was_youth_in_year_by_age(person, cohort_year, corp_size)
    return bool(was_youth_in_cohort)


def youth_options(emp_type: str) -> list[str]:
    if emp_type in R.EMP_NOT_YOUTH_REGULAR:
        return list(R.YOUTH_TYPES_NON_REGULAR)
    return list(R.YOUTH_TYPES)


NEW_TENURE_RULE_FROM = 2026   # '근로기간 1년 미만' 제외는 2026년 이후 최초공제분부터 (대통령령 제35999호 부칙 제2조)


def suggest_exclusion(person: dict, yrec: dict, year: int | None = None, old_rule: bool = False) -> str:
    """
    old_rule=True: 종전 규정(2024·2025년 최초공제분과 그 사후관리) — '근로계약기간 1년 미만'만 제외.
      원천징수부로는 계약기간을 알 수 없으므로 기간 정함 없는 계약으로 보아 자동 제외하지 않고,
      1년 미만 기간제는 사용자가 제외사유 '근로계약 1년미만'을 직접 선택해 제외합니다.
    old_rule=False: 개정 규정 — 실제 근로기간 1년 미만 제외(과세연도 말 기준).
    """
    emp_type = yrec.get("고용유형") or R.EMP_REGULAR
    if emp_type in R.EMP_AUTO_EXCLUDE:
        return R.EMP_AUTO_EXCLUDE[emp_type]
    sh_rel = str(person.get("주주관계") or "").strip()
    if sh_rel in R.EXCL_REASONS:
        return sh_rel
    # ※ 외국인 표시만으로 자동 제외하지 않음: 상시근로자의 '내국인'은 국적과 무관하게
    #   국내에 주소를 두거나 183일 이상 거소를 둔 개인(통합고용세액공제 상시근로자 명세서 작성방법 10).
    #   비거주자인 경우에만 사용자가 제외사유 '외국인 근로자'를 직접 선택 → 오류 검토에서 확인 안내.
    if not old_rule and tenure_under_1y(person, year):
        return R.EXCL_UNDER_1Y
    return R.EXCL_NONE


def suggest_youth(person: dict, yrec: dict, year: int, corp_size: str) -> str:
    emp_type = yrec.get("고용유형") or R.EMP_REGULAR
    c_age = contract_age(person)
    if c_age is not None and c_age >= R.SENIOR_AGE:
        return R.YOUTH_SENIOR
    if emp_type not in R.EMP_NOT_YOUTH_REGULAR:
        # 당해 청년 요건을 충족하는 달이 있을 때만 '취업시 청년'으로 제안
        # (나이가 지난 사람의 사후관리 청년 간주는 이 표시와 무관하게 별도로 계산됨)
        if any(is_youth_month(person, year, m, corp_size) for m in range(1, 13)):
            return R.YOUTH_YOUNG
    return R.YOUTH_NONE


def _pick(yrec: dict, field: str, suggestion: str) -> str:
    user_set = yrec.get("_user_set") or []
    cur = yrec.get(field)
    if field in user_set and cur:
        return cur
    return suggestion


def detect_last_paid_month(people: dict, year: int) -> int:
    max_m = 0
    has_any_pay = False
    for p in (people or {}).values():
        pay_obj = (p.get("월급여") or {}).get(str(year))
        if _has_any_pay_record(pay_obj):
            has_any_pay = True
            for m in range(1, 13):
                v = _get_month_pay(pay_obj, m)
                if v is not None and v > 0:
                    if m > max_m:
                        max_m = m
    if not has_any_pay or max_m == 0:
        return 12
    return max_m