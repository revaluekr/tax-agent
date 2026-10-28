# -*- coding: utf-8 -*-
"""
[모듈 1/4] 통합고용세액공제 — 연도별 자격요건 · 청년 유예기간 · 1년 미만 경과조치 · 기초 유틸리티 (hc_eligibility.py)
- 매년 세법 시행령 개정으로 바뀔 수 있는 '청년 연령·유예기간', '1년 미만 제외 경과조치', '비교 대상 과세연도',
  '상시근로자 수 계산방식(A/B) 선택 규칙(calc_method_for)'을 전담합니다.
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
    - 조특령 제26조의8 제4항 제1호: 병역을 이행한 후 취업한 경우 병역기간(6년 한도)을 빼고 연령 계산.
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


def calc_method_for(cohort_year: int) -> str:
    """
    코호트(최초 공제연도) 기준 상시근로자 수 계산방식(A/B) 일원화 선택 함수.
    - 근거: 국세청 법인세과 「'26년 3월 법인세 통합고용세액공제 상시근로자 수 계산 안내」 (재정경제부 세제실 회신 반영)
      및 조세특례제한법 시행령(2026.2.27. 대통령령 제36127호) 부칙 제11조
    - cohort_year <= 2024: "A" (기존 방식: [매월 말 상시근로자 수의 합계 ÷ 과세연도 개월수]의 값에서 100분의 1 미만 절사 — 최초 공제가 기존 방식이므로 그 코호트의 2·3차년도 요건·연속공제·사후관리는 끝까지 A)
      # 확인 필요: '26.3월 국세청 안내 신뢰보호 원칙 연장 적용 (2026년 이후 평가연도에서 2024년 이하 코호트에 A를 계속 적용)
    - cohort_year >= 2025: "B" (현행 방식: [(각 상시근로자 근무개월수 ÷ 과세연도 개월수)의 값에서 100분의 1 미만 절사한 값]의 합계)
    """
    return "A" if int(cohort_year) <= 2024 else "B"


def calc_method_badge_label(cohort_year_or_method: int | str) -> str:
    """화면·보고서 배지 표시용 문자열 반환: 'B방식(사원별 절사)' / 'A방식(합계 절사·신뢰보호)'"""
    if isinstance(cohort_year_or_method, str) and cohort_year_or_method.upper() in ("A", "B"):
        m = cohort_year_or_method.upper()
    else:
        m = calc_method_for(int(cohort_year_or_method))
    return "B방식(사원별 절사)" if m == "B" else "A방식(합계 절사·신뢰보호)"


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


def _resolve_retire_date_for_tenure(person: dict, year: int | None = None, as_of_year: int | None = None) -> date | None:
    ret_map = person.get("연도별_퇴사일") or {}
    if as_of_year is None:
        yr_ret_str = ret_map.get(str(year)) if year is not None else None
        return parse_date(yr_ret_str if yr_ret_str is not None else person.get("퇴사일"))
    cutoff = int(as_of_year)
    min_yr = int(year) if year is not None else None
    candidates: list[date] = []
    if isinstance(ret_map, dict):
        for k, v in ret_map.items():
            try:
                ky = int(k)
            except (TypeError, ValueError):
                continue
            if min_yr is not None and ky < min_yr:
                continue
            if ky > cutoff:
                continue
            dt = parse_date(v)
            if dt is not None and dt <= date(cutoff, 12, 31):
                candidates.append(dt)
    base_ret = parse_date(person.get("퇴사일"))
    if base_ret is not None:
        if (min_yr is None or base_ret.year >= min_yr) and base_ret <= date(cutoff, 12, 31):
            candidates.append(base_ret)
    return min(candidates) if candidates else None


def tenure_under_1y(person: dict, year: int | None = None, as_of_year: int | None = None) -> bool:
    hire = parse_date(person.get("입사일"))
    retire = _resolve_retire_date_for_tenure(person, year=year, as_of_year=as_of_year)
    if not hire or not retire or retire < hire:
        return False
    cutoff_year = int(as_of_year) if as_of_year is not None else (int(year) if year is not None else None)
    if cutoff_year is not None and retire > date(cutoff_year, 12, 31):
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
    - 현행 조세특례제한법 시행령(2026.2.27. 대통령령 제36127호 개정) 제26조의8 제4항 제1호 후단:
      "이 경우 근로계약 체결 당시 34세 이하인 사람은 근로기간 중 34세를 초과하더라도 근로계약 체결일부터 4년간(중소기업 또는 중견기업이 아닌 경우에는 3년간)은 청년등상시근로자로 본다."
    - 2026년 이후 계약: 중소·중견 4년, 일반기업(대기업) 3년 (조특령 제26조의8 제4항 제1호 후단)
    - 2025년 계약: 중소·중견 3년, 일반기업(대기업) 2년
      (근거: 조특령 부칙(2026.2.27.) 제11조 제2항 — 2025.1.1.~2025.12.31. 근로계약 체결 당시 34세 이하[병역기간 최대 6년 차감]인 사람은 계약 체결일부터 3년간[중소·중견기업이 아닌 경우 2년간] 청년등상시근로자로 봄)
    - 2024년 이전 계약: 0 (인정기간 없음 · 매월 말일 현재 만 34세 이하 여부로 판정 — 조특령 부칙(2026.2.27.) 제11조 제1항)
    """
    large = R.normalize_corp_size(corp_size) in ("일반기업", "대기업")
    if contract_dt is None or contract_dt.year >= 2026:
        return R.YOUTH_HOLD_YEARS_LARGE if large else R.YOUTH_HOLD_YEARS_SME
    if contract_dt.year == 2025:
        # 근거: 조특령 부칙(2026.2.27.) 제11조 제2항 (중소·중견 3년 / 일반기업 2년)
        return getattr(R, "YOUTH_HOLD_YEARS_2025_LARGE", 2) if large else getattr(R, "YOUTH_HOLD_YEARS_2025_SME", 3)
    # 근거: 조특령 부칙(2026.2.27.) 제11조 제1항 (2024년 이전 최초 공제 코호트 및 계약자에는 계약일 기준 청년 간주 규정을 적용하지 않음)
    return 0


def _resolve_contract_year_corp_size(corp_size: str, c_dt: date | None, corp_size_by_year: dict | None = None) -> str:
    """근로계약 체결 연도의 기업규모를 우선 조회하고, 없으면 전달된 corp_size를 반환합니다."""
    if c_dt is not None and isinstance(corp_size_by_year, dict) and corp_size_by_year:
        v = corp_size_by_year.get(c_dt.year) or corp_size_by_year.get(str(c_dt.year))
        if v:
            return R.normalize_corp_size(v, corp_size)
    return R.normalize_corp_size(corp_size)


def is_youth_month(
    person: dict,
    year: int,
    month: int,
    corp_size: str,
    use_hold: bool = True,
    corp_size_by_year: dict | None = None,
) -> bool:
    """
    청년 정규직 해당 여부(월말 기준).
    use_hold=True : 2026.2.27. 개정 정의(계약일 기준 유예 포함) — 2025년 이후 최초공제분·당해 판정 (조특령 부칙(2026.2.27.) 제11조 제1항·제2항)
    use_hold=False: 종전 정의(매달 나이로만 판정) — 2024년 이전 최초공제분의 사후관리 (조특령 부칙(2026.2.27.) 제11조 제1항)
    ※ 청년 연령 유지기간(중소·중견 4년[25년 3년] / 일반 3년[25년 2년])은 근로계약 체결 연도의 기업규모를 기준으로 판정합니다.
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

    # 34세를 넘은 달: 근로계약 체결일 기준 인정기간 안이면 청년 (2024년 이전 계약 및 2024년 이전 코호트는 인정기간 없음: 조특령 부칙(2026.2.27.) 제11조 제1항)
    # - `hold_end = add_years(c_dt, hold)`(계약일 + 유예연수 응당일)는 청년 제외시점(초일 산입)이며,
    #   매월 말일 현재(me = month_end(year, month)) `me < hold_end`이면 해당 월을 청년등 근무개월에 산입합니다.
    if not use_hold:
        return False
    hold_corp_size = _resolve_contract_year_corp_size(corp_size, c_dt, corp_size_by_year)
    hold = youth_hold_years(hold_corp_size, c_dt)
    if hold <= 0:
        return False
    hold_end = add_years(c_dt, hold)          # 청년 제외시점 (계약체결일 + 유예연수 응당일)
    return me < hold_end


def was_youth_in_year_by_age(
    person: dict,
    year: int,
    corp_size: str,
    corp_size_by_year: dict | None = None,
) -> bool:
    """사원표가 없을 때의 보조 판정: 그해(year) 매월 말 재직한 달 중 청년 요건을 충족한 달이 실제로 있었는지 검증."""
    hire = parse_date(person.get("입사일"))
    yr_ret = (person.get("연도별_퇴사일") or {}).get(str(year))
    retire = parse_date(yr_ret if yr_ret is not None else person.get("퇴사일"))
    return any(
        employed_at_month_end(hire, retire, year, m)
        and is_youth_month(person, year, m, corp_size, corp_size_by_year=corp_size_by_year)
        for m in range(1, 13)
    )


# 조특령 부칙(2026.2.27.) 제11조 제1항: 제26조의8 제4항 제1호 개정규정은 2025.1.1. 이후 개시하는 과세연도를 최초 공제연도로 하여 신청하는 경우부터 적용
# (2024년 이전 최초 공제 코호트에는 계약일 기준 청년 간주 규정을 적용하지 않음)
NEW_YOUTH_DEF_FROM_COHORT = 2025


def youth_flag_old_def(person: dict, year: int, month: int, corp_size: str, youth_label: str) -> bool:
    """종전 정의의 '실제' 청년등 여부(간주 없음): 2024년 이전 최초공제분의 연속공제 판정용 (조특령 부칙(2026.2.27.) 제11조 제1항 · 서면-2023-법인-0978)"""
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
    corp_size_by_year: dict | None = None,
) -> bool:
    """
    2024년 이전 최초공제분의 추가납부용 청년등 판정 (구 조특령 제26조의8 제5항 간주 · 조특령 부칙(2026.2.27.) 제11조 제1항)
    = 종전 정의상 현재 청년등  OR  최초공제연도(cohort_year)에 청년등이었던 사람
    ※ 2025년 이후 최초공제분은 제5항이 삭제되어 간주 없이 새 정의(당해 판정)를 그대로 씀 → compute_row에서 처리
    """
    if youth_label in (R.YOUTH_SENIOR, R.YOUTH_DISABLED, R.YOUTH_CAREER):
        return True
    if youth_label == R.YOUTH_NK:
        return cohort_year >= 2025
    if youth_label == R.YOUTH_YOUNG and parse_date(person.get("생년월일")) and \
            is_youth_month(
                person,
                eval_year,
                month,
                corp_size,
                # 조특령 부칙(2026.2.27.) 제11조 제1항: 2024년 이전 최초 공제 코호트에는 계약일 기준 청년 간주 규정을 적용하지 않음
                use_hold=cohort_year >= NEW_YOUTH_DEF_FROM_COHORT,
                corp_size_by_year=corp_size_by_year,
            ):
        return True
    if was_youth_in_cohort is None:
        if not parse_date(person.get("생년월일")):
            return False                       # 생년월일을 모르면 청년으로 보지 않음
        was_youth_in_cohort = was_youth_in_year_by_age(person, cohort_year, corp_size, corp_size_by_year=corp_size_by_year)
    return bool(was_youth_in_cohort)


def youth_options(emp_type: str) -> list[str]:
    if emp_type in R.EMP_NOT_YOUTH_REGULAR:
        return list(R.YOUTH_TYPES_NON_REGULAR)
    return list(R.YOUTH_TYPES)


NEW_TENURE_RULE_FROM = 2026   # '근로기간 1년 미만' 제외는 2026년 이후 최초공제분부터 (대통령령 제35999호 부칙 제2조)


def suggest_exclusion(
    person: dict,
    yrec: dict,
    year: int | None = None,
    old_rule: bool = False,
    as_of_year: int | None = None,
) -> str:
    """
    old_rule=True: 종전 규정(2024·2025년 최초공제분과 그 사후관리) — '근로계약기간 1년 미만'만 제외.
    old_rule=False: 개정 규정 — 실제 근로기간 1년 미만 제외.
      - 당해 자체 계산(as_of_year=None): 해당 과세연도 종료일 기준 확정된 1년 미만 퇴사자 제외
      - 비교연도 재산정(as_of_year=tax_year): 일관된 해석 기준에 따라 공제 계산 과세연도(tax_year) 종료일까지
        확정된 실제 근로기간 1년 미만 퇴사자를 비교연도 인원에서도 동일하게 제외
    """
    emp_type = yrec.get("고용유형") or R.EMP_REGULAR
    if emp_type in R.EMP_AUTO_EXCLUDE:
        return R.EMP_AUTO_EXCLUDE[emp_type]
    sh_rel = str(person.get("주주관계") or "").strip()
    if sh_rel in R.EXCL_REASONS:
        return sh_rel
    if not old_rule and tenure_under_1y(person, year, as_of_year=as_of_year):
        return R.EXCL_UNDER_1Y
    return R.EXCL_NONE


def suggest_youth(
    person: dict,
    yrec: dict,
    year: int,
    corp_size: str,
    corp_size_by_year: dict | None = None,
) -> str:
    emp_type = yrec.get("고용유형") or R.EMP_REGULAR
    c_age = contract_age(person)
    if c_age is not None and c_age >= R.SENIOR_AGE:
        return R.YOUTH_SENIOR
    if emp_type not in R.EMP_NOT_YOUTH_REGULAR:
        # 당해 청년 요건을 충족하는 달이 있을 때만 '취업시 청년'으로 제안
        # (나이가 지난 사람의 사후관리 청년 간주는 이 표시와 무관하게 별도로 계산됨)
        if any(is_youth_month(person, year, m, corp_size, corp_size_by_year=corp_size_by_year) for m in range(1, 13)):
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