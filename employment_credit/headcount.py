# -*- coding: utf-8 -*-
"""
통합고용세액공제 상시근로자 · 청년등 상시근로자 · 사후관리(추가납부세액) 통합 계산 및 12대 정밀 오류검토 엔진 (headcount.py)
근거: 조세특례제한법 제29조의8, 같은 법 시행령 제26조의8, 제11조의2, 제23조 제10항

[핵심 통합 및 고도화 내역]
1. [사후관리 코호트 청년등 판정 (`is_youth_month_for_cohort`, 조특령 §26의8⑤)]
   - 최초공제연도(cohort_year) 사원표에서 판정된 청년등 여부(`was_youth_in_cohort`)를 우선 반영하되,
     사원표가 없을 때는 그해 실제로 재직하며 청년 요건을 충족한 달이 있었는지를 정밀 검증합니다.
   - 나이가 지나 당해에는 '해당없음(일반)'으로 표시되는 근로자도 1·2차 사후관리 블록에서는 청년등으로 자동 간주됩니다.
2. [입사월 무급(익월지급) vs 기중 무급휴직 분리 + 기중양도 사업장 폐업월 이후 자동채움 차단 (`compute_row`)]
   - 입사월 급여 0원은 `include_unpaid_hire_month` 설정(기본 True)에 따라 산입(1) 후 `hire_month_nopay`로 별도 표기합니다.
   - `workplace_close_month_map`을 통해 기중양도 사업장의 양도월 이후에는 미도래 월 연말재직 가정(`_proj`)이 적용되지 않도록 제어합니다.
3. [2026~2028년 귀속 신법 A(직전)+B(전전)+C(전전전) 점증형 공제 및 제3호 최소고용증가인원 차감 산식 완벽 구현]
4. [귀속연도별 절사 방식 자동 분기]
   - 모든 귀속연도: 근로자별 (근무개월÷사업연도 월수)의 합에서 100분의 1 미만 1회 절사 (2026.5.22. 시행령 개정 기준)
   - 근로자별 먼저 절사한 값(2026.2.27. 문언)은 경정청구 검토용 비교값(6번 블록)으로만 표시
5. [100% 성능 12대 결정론적 세무 오류·절세누락 검토 엔진 (`review`)]
   - `sub_biz_list` 및 `**kwargs` 완벽 호환
   - ① 입사월 익월지급(무급 산입) vs 기중 무급휴직(0 제외) 정밀 구분
   - ② 퇴사일 이후 급여 지급자(퇴사 후 정산금 vs 재입사) 자동 탐지
   - ③ 1년 미만 단기 퇴사자 상시근로자 산입 위험(조특령 §23⑩ 1호) 경고
   - ④ [절세누락 탐지] 연령상 청년(15~34세)·고령자(60세 이상) 요건 충족자 중 '해당없음(일반)'으로 설정된 과소공제 대상자 자동 발굴
   - ⑤ 청년등 구분 오분류(생년월일·입사일 누락, 연령 초과, 북한이탈주민 2024년 이전 적용) 검출
   - ⑥ 만 35~40세 일반근로자 중 병역이행 연령차감(최대 72개월) 시 청년 전환 가능 후보자 발굴
   - ⑦ 단시간(0.5 / 0.75) 가중치 법정 요건 및 급여 급증(통상근로 전환 의심) 점검
   - ⑧ 청년 연령 도과자 사후관리/연속공제 청년 간주(조특령 §26의8⑤) 자동 적용 명단 안내
   - ⑨ 기중 가결산 미도래 월 연말재직 가정(`_proj`) 현황 브리핑
   - ⑩ 복수 사업장(본·지점 / 기중 양도·포괄양수 / 합병·분할·법인전환) 승계 특례 및 누락 입력 점검
   - ⑪ 기신고 내역 vs 세법원칙 재계산 수치 불일치 정밀 대조
   - ⑫ 수동 오버라이드(`상시_override` / `월_override`) 내역 감사 추적
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


# ══════════════════════════════════════════════════════════════════
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


def youth_hold_years(corp_size: str) -> int:
    return R.YOUTH_HOLD_YEARS_SME if corp_size == "중소기업" else R.YOUTH_HOLD_YEARS_LARGE


def is_youth_month(person: dict, year: int, month: int, corp_size: str) -> bool:
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

    hold_end = add_years(c_dt, youth_hold_years(corp_size))
    hold_end_month_last = month_end(hold_end.year, hold_end.month)
    return me <= hold_end_month_last


def was_youth_in_year_by_age(person: dict, year: int, corp_size: str) -> bool:
    """사원표가 없을 때의 보조 판정: 그해(year) 매월 말 재직한 달 중 청년 요건을 충족한 달이 실제로 있었는지 검증."""
    hire = parse_date(person.get("입사일"))
    yr_ret = (person.get("연도별_퇴사일") or {}).get(str(year))
    retire = parse_date(yr_ret if yr_ret is not None else person.get("퇴사일"))
    return any(
        employed_at_month_end(hire, retire, year, m) and is_youth_month(person, year, m, corp_size)
        for m in range(1, 13)
    )


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
    사후관리·연속공제용 청년등 판정 (구 조특령 제26조의8 제5항)
    = 당해 판정상 청년등  OR  최초공제연도(cohort_year)에 청년등이었던 사람
    ※ 나이가 지나 지금은 '해당없음(일반)'으로 표시되는 사람이 바로 간주 대상이므로, 현재 표시와 무관하게 판정합니다.
    """
    if youth_label in (R.YOUTH_SENIOR, R.YOUTH_DISABLED, R.YOUTH_CAREER):
        return True
    if youth_label == R.YOUTH_NK:
        return cohort_year >= 2025
    if youth_label == R.YOUTH_YOUNG and parse_date(person.get("생년월일")) and \
            is_youth_month(person, eval_year, month, corp_size):
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


def suggest_exclusion(person: dict, yrec: dict, year: int | None = None) -> str:
    emp_type = yrec.get("고용유형") or R.EMP_REGULAR
    if emp_type in R.EMP_AUTO_EXCLUDE:
        return R.EMP_AUTO_EXCLUDE[emp_type]
    sh_rel = str(person.get("주주관계") or "").strip()
    if sh_rel in R.EXCL_REASONS:
        return sh_rel
    # ※ 외국인 표시만으로 자동 제외하지 않음: 상시근로자의 '내국인'은 국적과 무관하게
    #   국내에 주소를 두거나 183일 이상 거소를 둔 개인(통합고용세액공제 상시근로자 명세서 작성방법 10).
    #   비거주자인 경우에만 사용자가 제외사유 '외국인 근로자'를 직접 선택 → 오류 검토에서 확인 안내.
    if tenure_under_1y(person, year):
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


# ══════════════════════════════════════════════════════════════════
# 4. 개인별 · 월별 상시근로자 및 우측 블록(당해 세액공제 · 1차 사후관리 · 2차 사후관리) 계산
# ══════════════════════════════════════════════════════════════════
def compute_row(person: dict, yrec: dict, year: int, ctx: dict) -> dict:
    corp_size = ctx.get("corp_size") or "중소기업"
    months_in_year = max(1, min(12, int(ctx.get("months_in_year") or 12)))
    assume_year_end = bool(ctx.get("assume_year_end", True))
    include_unpaid_hire_month = bool(ctx.get("include_unpaid_hire_month", True))
    last_paid_month = int(ctx.get("last_paid_month") or 12)
    act_months = set(active_months(year, months_in_year))

    # 기중양도·폐업 사업장인 경우 해당 양도월 이후에는 미도래 월 연말재직 가정(1 자동 채움) 차단
    wp_close_map = ctx.get("workplace_close_month_map") or {}
    person_wp = str((person.get("연도별_사업장명") or {}).get(str(year)) or person.get("사업장명") or "").strip()
    wp_primary = person_wp.split("→")[-1].strip() if "→" in person_wp else person_wp
    wp_close_month = wp_close_map.get(person_wp) if "→" not in person_wp else wp_close_map.get(wp_primary)

    # 포괄양수·승계 사업장(조특령 제23조 제13항 준용): 해당 과세연도 개시일에 승계한 것으로 보아 승계월 이전 달도 산입
    succ_map = ctx.get("succession_map") or {}
    succ = succ_map.get(person_wp) or succ_map.get(wp_primary) or {}
    succ_month = succ.get("month")
    succ_date = succ.get("date")
    if succ and not succ.get("keep_hire", True) and succ_date:
        _h = parse_date(person.get("입사일"))
        if not _h or _h < succ_date:          # 입사일 유지 안 함 → 승계일을 입사·계약일로 봄 (청년 연령·근속 판정)
            person = dict(person, 입사일=succ_date.isoformat(), 계약체결일=succ_date.isoformat())

    emp_type = yrec.get("고용유형") or R.EMP_REGULAR
    sug_excl = suggest_exclusion(person, yrec, year)
    excl = _pick(yrec, "제외사유", sug_excl)
    excl_locked = emp_type in R.EMP_AUTO_EXCLUDE

    effective_excl = R.EXCL_NONE if excl == R.EXCL_MATERNITY_REPLACED else excl
    auto_regular = "O" if (effective_excl == R.EXCL_NONE and emp_type not in R.EMP_AUTO_EXCLUDE) else "X"
    ovr_regular = yrec.get("상시_override") or ""
    is_regular = ovr_regular if ovr_regular in ("O", "X") else auto_regular

    opts = youth_options(emp_type)
    sug_youth = suggest_youth(person, yrec, year, corp_size)
    youth = _pick(yrec, "청년등", sug_youth)
    if youth not in opts:
        youth = sug_youth if sug_youth in opts else R.YOUTH_NONE

    hire = parse_date(person.get("입사일"))
    yr_ret_str = (person.get("연도별_퇴사일") or {}).get(str(year))
    retire = parse_date(yr_ret_str if yr_ret_str is not None else person.get("퇴사일"))
    pay_obj = (person.get("월급여") or {}).get(str(year))
    has_any_pay_data = _has_any_pay_record(pay_obj)
    weight = R.EMP_WEIGHT.get(emp_type, 1.0)

    # 그해 원천징수부가 올라와 있는데 그 안에 없는 사람(다른 연도 자료에만 있음)은 그해 이 회사에서 근무하지 않은 것으로 봄
    wht_years = {int(y) for y in (ctx.get("wht_years") or [])}
    other_year_pay = any(
        _has_any_pay_record(v) for k, v in (person.get("월급여") or {}).items() if str(k) != str(year)
    )
    # 그해 원천징수부에 없는 사람은 사용자가 '상시'를 O로 직접 지정했을 때만 산입
    # (고용유형만 바꾼 경우까지 산입하면 승계·전입자가 직전연도에 이중 계산될 수 있음. 월별 값 직접 입력은 별도로 항상 반영)
    user_activated_row = yrec.get("상시_override") == "O"
    absent_in_wht = int(year) in wht_years and not has_any_pay_data and other_year_pay and not user_activated_row

    # 기중양도(고용승계 포함, 조특령 제23조 제13항 준용): 양도일 현재 근무자는 개시일에 승계시킨 것으로 보아 그해 0
    tr_out_map = ctx.get("transfer_out_map") or {}
    tr_date = tr_out_map.get(person_wp) if "→" not in person_wp else tr_out_map.get(wp_primary)
    transferred_out = bool(tr_date) and (hire is None or hire <= tr_date) and (retire is None or retire >= tr_date)
    m_ovr = yrec.get("월_override") or {}

    paid_in_last_m = False
    if last_paid_month < 12 and has_any_pay_data:
        lp_val = _get_month_pay(pay_obj, last_paid_month)
        paid_in_last_m = bool(lp_val is not None and lp_val > 0)

    cmap = ctx.get("cohort_youth_map") or {}
    pid = person.get("pid")
    # 최초공제연도 사원표가 있으면 거기 없는 사람은 그해 근무하지 않은 것이므로 청년 간주 대상 아님(False)
    c1_was_youth = bool((cmap.get(year - 1) or {}).get(pid, False)) if (year - 1) in cmap else None
    c2_was_youth = bool((cmap.get(year - 2) or {}).get(pid, False)) if (year - 2) in cmap else None

    months: list[float | None] = []
    youth_flags_b1: list[bool] = []
    youth_flags_b2: list[bool] = []
    youth_flags_b3: list[bool] = []
    no_pay_months: list[int] = []
    hire_month_nopay: list[int] = []
    projected_months: list[int] = []
    succession_months: list[int] = []

    for m in range(1, 13):
        if m not in act_months:
            months.append(None)
            youth_flags_b1.append(False)
            youth_flags_b2.append(False)
            youth_flags_b3.append(False)
            continue

        ovr_v = m_ovr.get(str(m), m_ovr.get(m, None))
        if is_regular == "X":
            val = 0.0
        elif ovr_v is not None:
            val = float(ovr_v)
        else:
            emp_ok = employed_at_month_end(hire, retire, year, m)
            if wp_close_month is not None and m > int(wp_close_month):
                emp_ok = False
            m_pay = _get_month_pay(pay_obj, m)
            paid = (m_pay > 0) if m_pay is not None else None

            if not emp_ok:
                val = 0.0
            else:
                if has_any_pay_data:
                    if paid:
                        val = weight
                    elif last_paid_month < 12 and m > last_paid_month:
                        hired_after_cut = bool(hire and hire > month_end(year, last_paid_month))
                        if assume_year_end and (paid_in_last_m or hired_after_cut):
                            val = weight
                            projected_months.append(m)
                        else:
                            val = 0.0
                    elif hire and hire.year == year and hire.month == m:
                        if include_unpaid_hire_month:
                            val = weight                  # 입사월: 급여 익월 지급 가능 → 산입하고 표시만
                            hire_month_nopay.append(m)
                        else:
                            val = 0.0
                            no_pay_months.append(m)
                    else:
                        val = 0.0
                        no_pay_months.append(m)
                else:
                    val = weight

        if ovr_v is None and is_regular == "O":
            if absent_in_wht or transferred_out:
                val = 0.0
            elif succ_month and m < int(succ_month) and not val:
                hire_ok = hire is None or hire <= month_end(year, int(succ_month))
                if hire_ok and (retire is None or retire >= month_end(year, m)):
                    val = weight                 # 승계월 이전: 개시일 승계 의제로 산입
                    succession_months.append(m)
                    if m in no_pay_months:
                        no_pay_months.remove(m)
                    if m in hire_month_nopay:
                        hire_month_nopay.remove(m)

        months.append(val)

        if val and val > 0:
            if youth == R.YOUTH_NONE:
                yf1 = False
            elif youth == R.YOUTH_YOUNG:
                birth_ok = parse_date(person.get("생년월일")) is not None and contract_date(person) is not None
                yf1 = is_youth_month(person, year, m, corp_size) if birth_ok else False
            elif youth == R.YOUTH_NK:
                yf1 = year >= 2025
            else:
                yf1 = True

            yf2 = is_youth_month_for_cohort(person, year, m, year - 1, corp_size, youth, c1_was_youth)
            yf3 = is_youth_month_for_cohort(person, year, m, year - 2, corp_size, youth, c2_was_youth)
        else:
            yf1 = yf2 = yf3 = False

        youth_flags_b1.append(yf1)
        youth_flags_b2.append(yf2)
        youth_flags_b3.append(yf3)

    row_sum_frac = sum((Fraction(str(v)) for v in months if v), Fraction(0))
    yth_b1_frac = sum((Fraction(str(v)) for v, f in zip(months, youth_flags_b1) if v and f), Fraction(0))
    yth_b2_frac = sum((Fraction(str(v)) for v, f in zip(months, youth_flags_b2) if v and f), Fraction(0))
    yth_b3_frac = sum((Fraction(str(v)) for v, f in zip(months, youth_flags_b3) if v and f), Fraction(0))

    row_sum = float(row_sum_frac)
    yth_sum_b1 = float(yth_b1_frac)
    yth_sum_b2 = float(yth_b2_frac)
    yth_sum_b3 = float(yth_b3_frac)

    gen_sum_b1 = round(max(0.0, row_sum - yth_sum_b1), 4)
    gen_sum_b2 = round(max(0.0, row_sum - yth_sum_b2), 4)
    gen_sum_b3 = round(max(0.0, row_sum - yth_sum_b3), 4)

    # 사원별 표시값: 합산 후 절사 원칙이므로 개인 값은 참고용 반올림, 6번 블록(b4)만 근로자별 절사 비교값
    use_indiv_b1 = use_indiv_b2 = use_indiv_b3 = False

    b1_reg_trunc = trunc2(row_sum_frac / months_in_year)
    b1_yth_trunc = trunc2(yth_b1_frac / months_in_year)
    b1_gen_trunc = round(max(0.0, b1_reg_trunc - b1_yth_trunc), 2)

    b1_reg_round = round(row_sum / months_in_year, 2)
    b1_yth_round = round(yth_sum_b1 / months_in_year, 2)
    b1_gen_round = round(gen_sum_b1 / months_in_year, 2)

    if use_indiv_b1:
        b1_reg_indiv, b1_yth_indiv, b1_gen_indiv = b1_reg_trunc, b1_yth_trunc, b1_gen_trunc
        b4_reg_trunc, b4_yth_trunc, b4_gen_trunc = b1_reg_round, b1_yth_round, b1_gen_round
    else:
        b1_reg_indiv, b1_yth_indiv, b1_gen_indiv = b1_reg_round, b1_yth_round, b1_gen_round
        b4_reg_trunc, b4_yth_trunc, b4_gen_trunc = b1_reg_trunc, b1_yth_trunc, b1_gen_trunc

    if use_indiv_b2:
        b2_reg_indiv = trunc2(row_sum_frac / months_in_year)
        b2_yth_indiv = trunc2(yth_b2_frac / months_in_year)
        b2_gen_indiv = round(max(0.0, b2_reg_indiv - b2_yth_indiv), 2)
    else:
        b2_reg_indiv = round(row_sum / months_in_year, 2)
        b2_yth_indiv = round(yth_sum_b2 / months_in_year, 2)
        b2_gen_indiv = round(gen_sum_b2 / months_in_year, 2)

    if use_indiv_b3:
        b3_reg_indiv = trunc2(row_sum_frac / months_in_year)
        b3_yth_indiv = trunc2(yth_b3_frac / months_in_year)
        b3_gen_indiv = round(max(0.0, b3_reg_indiv - b3_yth_indiv), 2)
    else:
        b3_reg_indiv = round(row_sum / months_in_year, 2)
        b3_yth_indiv = round(yth_sum_b3 / months_in_year, 2)
        b3_gen_indiv = round(gen_sum_b3 / months_in_year, 2)

    return {
        "_eval_year": int(year),
        "고용유형": emp_type,
        "제외사유": excl,
        "excl_locked": excl_locked,
        "청년등": youth,
        "youth_options": opts,
        "상시": is_regular,
        "상시_auto": auto_regular,
        "취업연령": contract_age(person),
        "현재연령": current_year_end_age(person, year),
        "months": months,
        "youth_flags": youth_flags_b1,
        "youth_flags_b2": youth_flags_b2,
        "youth_flags_b3": youth_flags_b3,
        "no_pay_months": no_pay_months,
        "hire_month_nopay": hire_month_nopay,
        "succession_months": succession_months,
        "transferred_out": transferred_out,
        "absent_in_wht": absent_in_wht,
        "projected_months": projected_months,
        "row_sum": row_sum,
        "youth_sum": yth_sum_b1,
        "youth_sum_b2": yth_sum_b2,
        "youth_sum_b3": yth_sum_b3,
        "gen_sum_b1": gen_sum_b1,
        "gen_sum_b2": gen_sum_b2,
        "gen_sum_b3": gen_sum_b3,
        "b1_yth": b1_yth_indiv,
        "b1_gen": b1_gen_indiv,
        "b1_reg": b1_reg_indiv,
        "b2_yth": b2_yth_indiv,
        "b2_gen": b2_gen_indiv,
        "b2_reg": b2_reg_indiv,
        "b3_yth": b3_yth_indiv,
        "b3_gen": b3_gen_indiv,
        "b3_reg": b3_reg_indiv,
        "b4_yth": b4_yth_trunc,
        "b4_gen": b4_gen_trunc,
        "b4_reg": b4_reg_trunc,
    }


def year_totals(computed_rows: list[dict], months_in_year: int, year: int | None = None) -> dict:
    """
    과세연도 전체 상시근로자 수 및 우측 블록 집계:
    - 모든 연도: 합산 후 1회 절사 (2026.5.22. 시행령 개정). 6번 블록(b4)은 근로자별 먼저 절사한 비교값
    """
    n = max(1, min(12, int(months_in_year or 12)))
    act = set(active_months(2025, n))

    m_reg: list[float | None] = []
    m_yth: list[float | None] = []
    m_non: list[float | None] = []

    for m in range(1, 13):
        if m not in act:
            m_reg.append(None)
            m_yth.append(None)
            m_non.append(None)
            continue
        idx = m - 1
        r_sum_f = sum((Fraction(str(r["months"][idx])) for r in computed_rows if r["months"][idx]), Fraction(0))
        y_sum_f = sum(
            (Fraction(str(r["months"][idx])) for r in computed_rows if r["months"][idx] and r["youth_flags"][idx]),
            Fraction(0),
        )
        r_sum = float(r_sum_f)
        y_sum = float(y_sum_f)
        m_reg.append(r_sum)
        m_yth.append(y_sum)
        m_non.append(round(r_sum - y_sum, 4))

    reg_total_f = sum((Fraction(str(r["row_sum"])) for r in computed_rows), Fraction(0))
    yth_b1_f = sum((Fraction(str(r["youth_sum"])) for r in computed_rows), Fraction(0))
    yth_b2_f = sum((Fraction(str(r.get("youth_sum_b2", r["youth_sum"]))) for r in computed_rows), Fraction(0))
    yth_b3_f = sum((Fraction(str(r.get("youth_sum_b3", r["youth_sum"]))) for r in computed_rows), Fraction(0))

    reg_total = float(reg_total_f)
    yth_total_b1 = float(yth_b1_f)
    non_total_b1 = round(reg_total - yth_total_b1, 4)

    yth_total_b2 = float(yth_b2_f)
    non_total_b2 = round(max(0.0, reg_total - yth_total_b2), 4)

    yth_total_b3 = float(yth_b3_f)
    non_total_b3 = round(max(0.0, reg_total - yth_total_b3), 4)

    eval_yr = int(year) if year is not None else int((computed_rows[0].get("_eval_year") if computed_rows else 2026) or 2026)
    # 2026.5.22. 시행령 개정: 모든 연도 '근로자별 계산한 수의 합'에서 100분의 1 미만 절사(합산 후 1회 절사).
    # 근로자별 먼저 절사(2026.2.27. 문언)는 경정청구 검토용 비교값(b4)으로만 제공.
    use_indiv_b1 = use_indiv_b2 = use_indiv_b3 = False

    tot_trunc_reg = trunc2(reg_total_f / n)
    tot_trunc_yth_b1 = trunc2(yth_b1_f / n)
    tot_trunc_gen_b1 = round(max(0.0, tot_trunc_reg - tot_trunc_yth_b1), 2)

    indiv_sum_reg = round(sum(trunc2(Fraction(str(r["row_sum"])) / n) for r in computed_rows), 2)
    indiv_sum_yth_b1 = round(sum(trunc2(Fraction(str(r["youth_sum"])) / n) for r in computed_rows), 2)
    indiv_sum_gen_b1 = round(max(0.0, indiv_sum_reg - indiv_sum_yth_b1), 2)

    if use_indiv_b1:
        b1_reg, b1_yth, b1_gen = indiv_sum_reg, indiv_sum_yth_b1, indiv_sum_gen_b1
        b4_reg, b4_yth, b4_gen = tot_trunc_reg, tot_trunc_yth_b1, tot_trunc_gen_b1
    else:
        b1_reg, b1_yth, b1_gen = tot_trunc_reg, tot_trunc_yth_b1, tot_trunc_gen_b1
        b4_reg, b4_yth, b4_gen = indiv_sum_reg, indiv_sum_yth_b1, indiv_sum_gen_b1

    if use_indiv_b2:
        b2_reg = indiv_sum_reg
        b2_yth = round(sum(trunc2(Fraction(str(r.get("youth_sum_b2", r["youth_sum"]))) / n) for r in computed_rows), 2)
        b2_gen = round(max(0.0, b2_reg - b2_yth), 2)
    else:
        b2_reg = tot_trunc_reg
        b2_yth = trunc2(yth_b2_f / n)
        b2_gen = round(max(0.0, b2_reg - b2_yth), 2)

    if use_indiv_b3:
        b3_reg = indiv_sum_reg
        b3_yth = round(sum(trunc2(Fraction(str(r.get("youth_sum_b3", r["youth_sum"]))) / n) for r in computed_rows), 2)
        b3_gen = round(max(0.0, b3_reg - b3_yth), 2)
    else:
        b3_reg = tot_trunc_reg
        b3_yth = trunc2(yth_b3_f / n)
        b3_gen = round(max(0.0, b3_reg - b3_yth), 2)

    return {
        "months_in_year": n,
        "월별_상시": m_reg,
        "월별_청년등": m_yth,
        "월별_청년외": m_non,
        "상시_합계": reg_total,
        "청년등_합계": yth_total_b1,
        "청년외_합계": non_total_b1,
        "b2_청년등_합계": yth_total_b2,
        "b2_청년외_합계": non_total_b2,
        "b3_청년등_합계": yth_total_b3,
        "b3_청년외_합계": non_total_b3,
        "상시_평균": b1_reg,
        "청년등_평균": b1_yth,
        "청년외_평균": b1_gen,
        "b1_yth": b1_yth,
        "b1_gen": b1_gen,
        "b1_reg": b1_reg,
        "b2_yth": b2_yth,
        "b2_gen": b2_gen,
        "b2_reg": b2_reg,
        "b3_yth": b3_yth,
        "b3_gen": b3_gen,
        "b3_reg": b3_reg,
        "b4_yth": b4_yth,
        "b4_gen": b4_gen,
        "b4_reg": b4_reg,
    }


def regular_excluding_part_time(computed_rows: list[dict], emp_types: list[str], months_in_year: int) -> float:
    n = max(1, min(12, int(months_in_year or 12)))
    total_f = sum(
        (Fraction(str(r["row_sum"])) for r, et in zip(computed_rows, emp_types) if et not in (R.EMP_PT_050, R.EMP_PT_075)),
        Fraction(0),
    )
    return trunc2(total_f / n)


# ══════════════════════════════════════════════════════════════════
# 5. 고용증가 인원 한도(Cap) · 신법 A+B+C(제1~3호) · 1·2차 사후관리(추가납부세액) 계산
# ══════════════════════════════════════════════════════════════════
def calc_increase_with_cap(
    cur_regular: float,
    cur_youth: float,
    cur_non_youth_or_prev_reg: float,
    prev_regular_or_prev_yth: float,
    prev_youth: float | None = None,
    prev_non_youth: float | None = None,
) -> dict[str, float]:
    if prev_youth is None and prev_non_youth is None:
        prev_regular = float(cur_non_youth_or_prev_reg or 0.0)
        prev_y = float(prev_regular_or_prev_yth or 0.0)
        cur_non_y = round(max(0.0, float(cur_regular or 0.0) - float(cur_youth or 0.0)), 2)
        prev_non_y = round(max(0.0, prev_regular - prev_y), 2)
    else:
        cur_non_y = float(cur_non_youth_or_prev_reg or 0.0)
        prev_regular = float(prev_regular_or_prev_yth or 0.0)
        prev_y = float(prev_youth or 0.0)
        prev_non_y = float(prev_non_youth if prev_non_youth is not None else max(0.0, prev_regular - prev_y))

    total_diff = round(float(cur_regular or 0.0) - prev_regular, 2)
    youth_diff = round(float(cur_youth or 0.0) - prev_y, 2)
    total_inc = round(max(0.0, total_diff), 2)
    raw_youth_inc = round(max(0.0, youth_diff), 2)
    raw_non_youth_inc = round(max(0.0, cur_non_y - prev_non_y), 2)

    youth_inc = round(min(total_inc, raw_youth_inc), 2)
    non_youth_inc = round(max(0.0, total_inc - youth_inc), 2)

    return {
        "전체_증감": total_diff,
        "전체_증가": total_inc,
        "청년등_증가": youth_inc,
        "청년등외_증가": non_youth_inc,
        "청년등_한도적용전": raw_youth_inc,
        "청년등외_한도적용전": raw_non_youth_inc,
        "total_diff": total_diff,
        "youth_diff": youth_diff,
        "total_inc": total_inc,
        "youth_inc": youth_inc,
        "non_youth_inc": non_youth_inc,
        "raw_youth_inc": raw_youth_inc,
    }


def get_unit_rates(corp_size: str, is_capital: bool, scheme: str = "legacy", retention_year: int = 1) -> dict[str, int]:
    sz = corp_size if corp_size in R.CREDIT_RATES_LEGACY_2023_2025 else "중소기업"
    loc = "수도권" if is_capital else "수도권 외"
    if scheme == "new_2026":
        tb = R.CREDIT_RATES_NEW_2026.get(sz, R.CREDIT_RATES_NEW_2026["중소기업"]).get(loc)
        yr = max(1, min(3, int(retention_year or 1)))
        return {
            "청년등": int(tb["청년등"].get(yr, 0)),
            "청년등외": int(tb["청년등외"].get(yr, 0)),
        }
    tb = R.CREDIT_RATES_LEGACY_2023_2025.get(sz, R.CREDIT_RATES_LEGACY_2023_2025["중소기업"]).get(loc)
    return {"청년등": int(tb["청년등"]), "청년등외": int(tb["청년등외"])}


def calc_minimum_hurdle_deduction_2026(
    corp_size: str,
    total_inc: float,
    youth_inc: float,
    non_youth_inc: float,
    retention_year: int = 1,
) -> dict[str, Any]:
    hurdle = float(R.MIN_INCREASE_HURDLE_2026.get(corp_size, 0.0))
    t_inc = round(max(0.0, float(total_inc or 0.0)), 2)
    y_inc = round(min(t_inc, max(0.0, float(youth_inc or 0.0))), 2)
    g_inc = round(max(0.0, float(non_youth_inc if non_youth_inc is not None else (t_inc - y_inc))), 2)
    yr = max(1, min(3, int(retention_year or 1)))

    if hurdle <= 0.0:
        return {
            "hurdle": 0.0,
            "hurdle_met": t_inc > 0,
            "deduction_manwon": 0.0,
            "deduction_won": 0,
            "recognized_total_inc": t_inc,
            "recognized_youth_inc": y_inc,
            "recognized_non_youth_inc": g_inc,
            "note": "중소기업 최소고용증가인원 기준 없음(0명)",
        }

    if t_inc <= hurdle:
        return {
            "hurdle": hurdle,
            "hurdle_met": False,
            "deduction_manwon": 0.0,
            "deduction_won": 0,
            "recognized_total_inc": 0.0,
            "recognized_youth_inc": 0.0,
            "recognized_non_youth_inc": 0.0,
            "note": f"{corp_size} 최소고용증가인원({hurdle:g}명) 미초과로 공제 제외",
        }

    if corp_size == "중견기업":
        gen_rate = 300 if yr == 1 else 500
        yth_rate = 500 if yr == 1 else 900
        if g_inc >= 5.0:
            ded_man = 5.0 * gen_rate
            rec_g = round(g_inc - 5.0, 2)
            rec_y = y_inc
            note = f"중견기업 제3호 가목1): 청년등외 증가({g_inc:.2f}명) ≥ 5명 → 5명 × {gen_rate}만원 = {ded_man:,.0f}만원 차감"
        else:
            rem_y = round(5.0 - g_inc, 2)
            ded_man = (g_inc * gen_rate) + (rem_y * yth_rate)
            rec_g = 0.0
            rec_y = round(max(0.0, y_inc - rem_y), 2)
            note = (
                f"중견기업 제3호 가목2): 청년등외({g_inc:.2f}명)×{gen_rate}만 + "
                f"청년등({rem_y:.2f}명)×{yth_rate}만 = {ded_man:,.1f}만원 차감"
            )
    else:
        yth_rate = 300 if yr == 1 else (500 if yr == 2 else 0)
        if g_inc >= 10.0:
            ded_man = 0.0
            rec_g = round(g_inc - 10.0, 2)
            rec_y = y_inc
            note = f"대기업 제3호 나목1): 청년등외 증가({g_inc:.2f}명) ≥ 10명 → 차감 금액 0원 (청년등 {y_inc:.2f}명 전액 인정)"
        else:
            rem_y = round(10.0 - g_inc, 2)
            ded_man = rem_y * yth_rate
            rec_g = 0.0
            rec_y = round(max(0.0, y_inc - rem_y), 2)
            note = f"대기업 제3호 나목2): (10명 - 청년등외 {g_inc:.2f}명) × {yth_rate}만원 = {ded_man:,.1f}만원 차감"

    return {
        "hurdle": hurdle,
        "hurdle_met": True,
        "deduction_manwon": round(ded_man, 4),
        "deduction_won": int(round(ded_man * 10_000)),
        "recognized_total_inc": round(rec_y + rec_g, 2),
        "recognized_youth_inc": rec_y,
        "recognized_non_youth_inc": rec_g,
        "note": note,
    }


def apply_minimum_increase_hurdle_2026(
    corp_size: str,
    total_inc: float,
    youth_inc: float,
    retention_year: int = 1,
) -> dict[str, Any]:
    t_inc = round(max(0.0, float(total_inc or 0.0)), 2)
    y_inc = round(min(t_inc, max(0.0, float(youth_inc or 0.0))), 2)
    g_inc = round(max(0.0, t_inc - y_inc), 2)
    return calc_minimum_hurdle_deduction_2026(corp_size, t_inc, y_inc, g_inc, retention_year=retention_year)


def calc_new_2026_credit_abc(
    tax_year: int,
    corp_size: str,
    is_capital: bool,
    summaries_by_year: dict[int, dict],
) -> dict[str, Any]:
    t = int(tax_year)
    comp = valid_comparison_years_for_new_credit(t)

    def _s(y: int | None) -> dict[str, float]:
        if y is None:
            return {"reg": 0.0, "yth": 0.0, "b2_yth": 0.0, "b3_yth": 0.0, "has_data": False}
        d = summaries_by_year.get(y) or {}
        reg = float(d.get("regular", d.get("상시_평균", d.get("b1_reg", 0.0))) or 0.0)
        yth = float(d.get("youth", d.get("청년등_평균", d.get("b1_yth", 0.0))) or 0.0)
        b2_y = float(d.get("b2_yth", yth) or 0.0)
        b3_y = float(d.get("b3_yth", b2_y) or 0.0)
        has_d = bool(d.get("has_data", reg > 0 or yth > 0))
        return {"reg": reg, "yth": yth, "b2_yth": b2_y, "b3_yth": b3_y, "has_data": has_d}

    s_t = _s(t)
    s_t1 = _s(comp.get("A"))
    s_t2 = _s(comp.get("B"))
    s_t3 = _s(comp.get("C"))

    tiers: dict[str, dict[str, Any]] = {}

    rates_a = get_unit_rates(corp_size, is_capital, scheme="new_2026", retention_year=1)
    if comp.get("A") is not None:
        inc_a = calc_increase_with_cap(s_t["reg"], s_t["yth"], s_t1["reg"], s_t1["yth"])
        hurdle_a = calc_minimum_hurdle_deduction_2026(
            corp_size, inc_a["total_inc"], inc_a["youth_inc"], inc_a["non_youth_inc"], retention_year=1
        )
        if hurdle_a["hurdle_met"]:
            item1_won = int(round(inc_a["youth_inc"] * rates_a["청년등"] * 10_000))
            item2_won = int(round(inc_a["non_youth_inc"] * rates_a["청년등외"] * 10_000))
            item3_won = hurdle_a["deduction_won"]
            net_a_won = max(0, item1_won + item2_won - item3_won)
        else:
            item1_won = item2_won = item3_won = net_a_won = 0
    else:
        inc_a = {"total_inc": 0.0, "youth_inc": 0.0, "non_youth_inc": 0.0}
        hurdle_a = calc_minimum_hurdle_deduction_2026(corp_size, 0.0, 0.0, 0.0, retention_year=1)
        item1_won = item2_won = item3_won = net_a_won = 0

    tiers["A"] = {
        "comp_year": comp.get("A"),
        "retention_year": 1,
        "rates": rates_a,
        "total_inc": inc_a["total_inc"],
        "youth_inc": inc_a["youth_inc"],
        "non_youth_inc": inc_a["non_youth_inc"],
        "hurdle": hurdle_a,
        "item1_youth_won": item1_won,
        "item2_non_youth_won": item2_won,
        "item3_deduction_won": item3_won,
        "credit_won": net_a_won,
    }

    rates_b = get_unit_rates(corp_size, is_capital, scheme="new_2026", retention_year=2)
    if comp.get("B") is not None and s_t2["has_data"]:
        gen = lambda d: max(0.0, d["reg"] - d["yth"])
        tot_b = round(max(0.0, min(s_t["reg"], s_t1["reg"]) - s_t2["reg"]), 2)
        yth_b = round(min(tot_b, max(0.0, min(s_t["yth"], s_t1["yth"]) - s_t2["yth"])), 2)
        gen_b = round(min(tot_b, max(0.0, min(gen(s_t), gen(s_t1)) - gen(s_t2))), 2)
        hurdle_b = calc_minimum_hurdle_deduction_2026(corp_size, tot_b, yth_b, gen_b, retention_year=2)
        if hurdle_b["hurdle_met"]:
            b1_won = int(round(yth_b * rates_b["청년등"] * 10_000))
            b2_won = int(round(gen_b * rates_b["청년등외"] * 10_000))
            b3_won = hurdle_b["deduction_won"]
            net_b_won = max(0, b1_won + b2_won - b3_won)
        else:
            b1_won = b2_won = b3_won = net_b_won = 0
    else:
        tot_b = yth_b = gen_b = 0.0
        hurdle_b = calc_minimum_hurdle_deduction_2026(corp_size, 0.0, 0.0, 0.0, retention_year=2)
        b1_won = b2_won = b3_won = net_b_won = 0

    tiers["B"] = {
        "comp_year": comp.get("B"),
        "retention_year": 2,
        "rates": rates_b,
        "total_inc": tot_b,
        "youth_inc": yth_b,
        "non_youth_inc": gen_b,
        "hurdle": hurdle_b,
        "item1_youth_won": b1_won,
        "item2_non_youth_won": b2_won,
        "item3_deduction_won": b3_won,
        "credit_won": net_b_won,
    }

    rates_c = get_unit_rates(corp_size, is_capital, scheme="new_2026", retention_year=3)
    if comp.get("C") is not None and s_t3["has_data"] and (rates_c["청년등"] > 0 or rates_c["청년등외"] > 0):
        gen = lambda d: max(0.0, d["reg"] - d["yth"])
        tot_c = round(max(0.0, min(s_t["reg"], s_t1["reg"], s_t2["reg"]) - s_t3["reg"]), 2)
        yth_c = round(min(tot_c, max(0.0, min(s_t["yth"], s_t1["yth"], s_t2["yth"]) - s_t3["yth"])), 2)
        gen_c = round(min(tot_c, max(0.0, min(gen(s_t), gen(s_t1), gen(s_t2)) - gen(s_t3))), 2)
        hurdle_c = calc_minimum_hurdle_deduction_2026(corp_size, tot_c, yth_c, gen_c, retention_year=3)
        if hurdle_c["hurdle_met"]:
            c1_won = int(round(yth_c * rates_c["청년등"] * 10_000))
            c2_won = int(round(gen_c * rates_c["청년등외"] * 10_000))
            c3_won = hurdle_c["deduction_won"]
            net_c_won = max(0, c1_won + c2_won - c3_won)
        else:
            c1_won = c2_won = c3_won = net_c_won = 0
    else:
        tot_c = yth_c = gen_c = 0.0
        hurdle_c = calc_minimum_hurdle_deduction_2026(corp_size, 0.0, 0.0, 0.0, retention_year=3)
        c1_won = c2_won = c3_won = net_c_won = 0

    tiers["C"] = {
        "comp_year": comp.get("C"),
        "retention_year": 3,
        "rates": rates_c,
        "total_inc": tot_c,
        "youth_inc": yth_c,
        "non_youth_inc": gen_c,
        "hurdle": hurdle_c,
        "item1_youth_won": c1_won,
        "item2_non_youth_won": c2_won,
        "item3_deduction_won": c3_won,
        "credit_won": net_c_won,
    }

    total_new_abc_won = net_a_won + net_b_won + net_c_won
    return {
        "tiers": tiers,
        "A_won": net_a_won,
        "B_won": net_b_won,
        "C_won": net_c_won,
        "total_abc_won": total_new_abc_won,
    }


def calc_legacy_post_management(
    cohort_year: int,
    eval_year: int,
    corp_size: str,
    is_capital: bool,
    init_reg: float,
    init_yth: float,
    init_yth_inc: float,
    init_gen_inc: float,
    cur_pm_reg: float,
    cur_pm_yth: float,
    init_credit_claimed_won: int = 0,
    unclaimed_carryforward_won: int = 0,
    prev_pm_reg: float | None = None,
    prev_pm_yth: float | None = None,
    prior_clawback_paid_won: int = 0,
    y1_continued_credit_won: int | None = None,
) -> dict[str, Any]:
    """
    [2023~2025년 귀속 공제분의 1차·2차 사후관리(2·3차년도 연속공제 및 추가납부세액) 정밀 산출]
    """
    elapsed = int(eval_year) - int(cohort_year)
    rates = get_unit_rates(corp_size, is_capital, scheme="legacy")
    yth_rate = rates["청년등"]
    gen_rate = rates["청년등외"]
    diff_rate = max(0, yth_rate - gen_rate)

    is_large = corp_size in ("일반기업", "대기업")
    max_credit_years = 2 if is_large else 3
    can_receive_continued = (1 <= elapsed < max_credit_years) and (init_yth_inc + init_gen_inc > 0)

    if elapsed not in (1, 2) or (init_yth_inc <= 0 and init_gen_inc <= 0):
        return {
            "cohort_year": cohort_year,
            "eval_year": eval_year,
            "elapsed_year": elapsed,
            "active": False,
            "case_code": "해당없음",
            "case_title": f"{cohort_year}년 귀속분 공제이력 없음 (사후관리 대상 아님)",
            "continued_credit_won": 0,
            "clawback_raw_cumulative_won": 0,
            "prior_clawback_deducted_won": 0,
            "clawback_gross_won": 0,
            "carryforward_offset_won": 0,
            "clawback_net_payable_won": 0,
            "retained_yth_inc": 0.0,
            "retained_gen_inc": 0.0,
            "reg_decrease": 0.0,
            "yth_decrease": 0.0,
            "init_reg": round(float(init_reg or 0.0), 2),
            "init_yth": round(float(init_yth or 0.0), 2),
            "init_yth_inc": round(float(init_yth_inc or 0.0), 2),
            "init_gen_inc": round(float(init_gen_inc or 0.0), 2),
            "formula_note": "해당 과세연도에 공제받은 고용증가 인원이 없어 사후관리(연속공제·추가납부) 대상이 아닙니다.",
        }

    reg_diff = round(cur_pm_reg - init_reg, 2)
    yth_diff = round(cur_pm_yth - init_yth, 2)
    reg_dec = round(max(0.0, init_reg - cur_pm_reg), 2)
    yth_dec = round(max(0.0, init_yth - cur_pm_yth), 2)

    if elapsed == 1:
        prior_years_claimed_count = 1
    else:
        if y1_continued_credit_won is not None:
            prior_years_claimed_count = 2 if (y1_continued_credit_won > 0 and not is_large) else 1
        elif prev_pm_reg is not None and prev_pm_reg < init_reg:
            prior_years_claimed_count = 1
        else:
            prior_years_claimed_count = 2 if not is_large else 1

    if reg_diff >= 0 and yth_diff >= 0:
        case_code = "유지/증가"
        case_title = "전체 상시 및 청년등 인원 모두 유지 (전액 연속공제 · 추징 없음)"
        ret_yth = round(init_yth_inc, 2)
        ret_gen = round(init_gen_inc, 2)
        if elapsed == 2:
            if (y1_continued_credit_won is not None and y1_continued_credit_won == 0) or (
                prev_pm_reg is not None and prev_pm_reg < init_reg
            ):
                ret_yth = 0.0
                ret_gen = 0.0
            elif prev_pm_yth is not None and prev_pm_yth < init_yth:
                lost_y1 = max(0.0, init_yth - prev_pm_yth)
                ret_yth = round(max(0.0, init_yth_inc - lost_y1), 2)
                ret_gen = round(init_gen_inc + (init_yth_inc - ret_yth), 2)

        cont_man = (ret_yth * yth_rate + ret_gen * gen_rate) if can_receive_continued else 0.0
        raw_claw_man = 0.0
        formula_note = (
            f"[{cohort_year}년분 {elapsed+1}차년도] 상시({cur_pm_reg:.2f} ≥ {init_reg:.2f}) 및 "
            f"청년등({cur_pm_yth:.2f} ≥ {init_yth:.2f}) 유지 → "
            f"연속공제: 청년 {ret_yth:.2f}명×{yth_rate:,}만 + 청년외 {ret_gen:.2f}명×{gen_rate:,}만 = {cont_man:,.1f}만원 / 추징 0원"
        )

    elif reg_diff >= 0 and yth_diff < 0:
        case_code = "Case 3 (전체 유지·청년등만 감소)"
        case_title = "전체 상시근로자 유지 · 청년등만 감소 (부분 연속공제 + 단가차액 추가납부)"
        capped_yth_dec = round(min(init_yth_inc, yth_dec), 2)
        ret_yth = round(max(0.0, init_yth_inc - capped_yth_dec), 2)
        ret_gen = round(init_gen_inc + capped_yth_dec, 2)

        if elapsed == 2 and (
            (y1_continued_credit_won is not None and y1_continued_credit_won == 0)
            or (prev_pm_reg is not None and prev_pm_reg < init_reg)
        ):
            ret_yth = 0.0
            ret_gen = 0.0

        cont_man = (ret_yth * yth_rate + ret_gen * gen_rate) if can_receive_continued else 0.0
        raw_claw_man = capped_yth_dec * diff_rate * prior_years_claimed_count
        formula_note = (
            f"[{cohort_year}년분 {elapsed+1}차년도 · Case 3] 전체 상시 유지({cur_pm_reg:.2f} ≥ {init_reg:.2f}), "
            f"청년등 {capped_yth_dec:.2f}명 감소(일반 대체) → "
            f"추징(차액): {capped_yth_dec:.2f}명 × ({yth_rate:,}-{gen_rate:,})만원 × {prior_years_claimed_count}년 = {raw_claw_man:,.1f}만원 / "
            f"연속공제: 유지청년 {ret_yth:.2f}명×{yth_rate:,}만 + 대체포함일반 {ret_gen:.2f}명×{gen_rate:,}만 = {cont_man:,.1f}만원"
        )

    else:
        ret_yth = 0.0
        ret_gen = 0.0
        cont_man = 0.0
        total_init_inc = round(init_yth_inc + init_gen_inc, 2)
        capped_reg_dec = round(min(total_init_inc, reg_dec), 2)

        if reg_dec <= yth_dec + 1e-9:
            case_code = "Case 1 (전체 감소·청년등 감소 ≥ 전체 감소)"
            case_title = "전체 상시근로자 감소 & 청년등 더 크게 감소 (연속공제 중단 + 청년이탈·대체분 추징)"
            pure_yth_lost = round(min(init_yth_inc, capped_reg_dec), 2)
            gen_also_lost = round(max(0.0, capped_reg_dec - pure_yth_lost), 2)
            remaining_yth_capacity = round(max(0.0, init_yth_inc - pure_yth_lost), 2)
            sub_yth_to_gen = round(min(remaining_yth_capacity, max(0.0, yth_dec - capped_reg_dec)), 2)

            raw_claw_man = (
                (pure_yth_lost * yth_rate)
                + (gen_also_lost * gen_rate)
                + (sub_yth_to_gen * diff_rate)
            ) * prior_years_claimed_count
            formula_note = (
                f"[{cohort_year}년분 {elapsed+1}차년도 · Case 1] 전체 상시 {capped_reg_dec:.2f}명 감소 ≤ 청년등 {yth_dec:.2f}명 감소 → "
                f"연속공제 중단(0원) / 추징: [청년이탈 {pure_yth_lost:.2f}명×{yth_rate:,}만 + "
                f"청년→일반대체 {sub_yth_to_gen:.2f}명×{diff_rate:,}만"
                + (f" + 일반이탈 {gen_also_lost:.2f}명×{gen_rate:,}만" if gen_also_lost > 0 else "")
                + f"] × {prior_years_claimed_count}년 = {raw_claw_man:,.1f}만원"
            )
        else:
            case_code = "Case 2 (전체 감소·그 밖의 경우)"
            case_title = "전체 상시근로자 감소 > 청년등 감소 (연속공제 중단 + 청년감소분·일반감소분 각각 추징)"
            yth_lost = round(min(init_yth_inc, yth_dec), 2)
            gen_lost_raw = round(max(0.0, capped_reg_dec - yth_lost), 2)
            gen_lost = round(min(init_gen_inc, gen_lost_raw), 2)
            total_yth_lost = yth_lost        # 청년등외 증가분을 넘는 감소는 공제받은 적이 없으므로 추징 대상 아님

            raw_claw_man = ((total_yth_lost * yth_rate) + (gen_lost * gen_rate)) * prior_years_claimed_count
            formula_note = (
                f"[{cohort_year}년분 {elapsed+1}차년도 · Case 2] 전체 상시 {capped_reg_dec:.2f}명 감소 > 청년등 {yth_dec:.2f}명 감소 → "
                f"연속공제 중단(0원) / 추징: [청년감소 {total_yth_lost:.2f}명×{yth_rate:,}만 + "
                f"일반감소 {gen_lost:.2f}명×{gen_rate:,}만] × {prior_years_claimed_count}년 = {raw_claw_man:,.1f}만원"
            )

    continued_credit_won = int(round(cont_man * 10_000))
    raw_clawback_won = int(round(raw_claw_man * 10_000))

    claimed_cap = max(0, int(init_credit_claimed_won or 0))
    if elapsed == 2 and y1_continued_credit_won and y1_continued_credit_won > 0:
        claimed_cap = claimed_cap + int(y1_continued_credit_won) if claimed_cap > 0 else 0

    if claimed_cap > 0:
        capped_cumulative_claw_won = min(raw_clawback_won, claimed_cap)
    else:
        capped_cumulative_claw_won = raw_clawback_won

    prior_paid = max(0, int(prior_clawback_paid_won or 0)) if elapsed == 2 else 0
    prior_deducted_won = min(capped_cumulative_claw_won, prior_paid)
    clawback_gross_won = max(0, capped_cumulative_claw_won - prior_deducted_won)
    if prior_deducted_won > 0:
        formula_note += f" (1차 사후관리 기추징액 {prior_deducted_won:,}원 차감 반영)"

    cf_avail = max(0, int(unclaimed_carryforward_won or 0))
    carryforward_offset_won = min(clawback_gross_won, cf_avail)
    clawback_net_payable_won = max(0, clawback_gross_won - carryforward_offset_won)

    return {
        "cohort_year": cohort_year,
        "eval_year": eval_year,
        "elapsed_year": elapsed,
        "active": True,
        "case_code": case_code,
        "case_title": case_title,
        "continued_credit_won": continued_credit_won,
        "clawback_raw_cumulative_won": raw_clawback_won,
        "prior_clawback_deducted_won": prior_deducted_won,
        "clawback_gross_won": clawback_gross_won,
        "carryforward_offset_won": carryforward_offset_won,
        "clawback_net_payable_won": clawback_net_payable_won,
        "retained_yth_inc": ret_yth,
        "retained_gen_inc": ret_gen,
        "reg_decrease": reg_dec,
        "yth_decrease": yth_dec,
        "init_reg": round(float(init_reg or 0.0), 2),
        "init_yth": round(float(init_yth or 0.0), 2),
        "init_yth_inc": round(float(init_yth_inc or 0.0), 2),
        "init_gen_inc": round(float(init_gen_inc or 0.0), 2),
        "formula_note": formula_note,
    }


def calculate_tax_year_package(
    tax_year: int,
    corp_size: str,
    is_capital: bool,
    summaries: dict[int, dict],
    prior_filings: dict[int, dict] | None = None,
    additional_inputs: dict[str, Any] | None = None,
    scheme_2026: str = "new_2026",
    pm_basis: str = R.PM_BASIS_FILED,
) -> dict[str, Any]:
    """
    [선택된 귀속사업연도(2024~2028)의 통합고용세액공제 종합 계산 패키지]
    """
    t = int(tax_year)
    pf = prior_filings or {}
    add_in = additional_inputs or {}
    basis = R.PM_BASIS_RECALC if pm_basis == R.PM_BASIS_RECALC else R.PM_BASIS_FILED

    def _s(y: int) -> dict[str, Any]:
        d = summaries.get(y) or {}
        n_m = int(d.get("months_in_year", 12) or 12)
        reg = float(d.get("상시_평균", d.get("regular", d.get("b1_reg", 0.0))) or 0.0)
        yth = float(d.get("청년등_평균", d.get("youth", d.get("b1_yth", 0.0))) or 0.0)
        non_y = float(d.get("청년외_평균", d.get("non_youth", d.get("b1_gen", max(0.0, reg - yth)))) or 0.0)
        reg_tot = float(d.get("상시_합계", round(reg * n_m, 2)) or 0.0)
        yth_tot = float(d.get("청년등_합계", round(yth * n_m, 2)) or 0.0)
        non_tot = float(d.get("청년외_합계", round(max(0.0, reg_tot - yth_tot), 2)) or 0.0)

        b2_r = float(d.get("b2_reg", reg) or 0.0)
        b2_y = float(d.get("b2_yth", yth) or 0.0)
        b2_y_tot = float(d.get("b2_청년등_합계", round(b2_y * n_m, 2)) or 0.0)

        b3_r = float(d.get("b3_reg", reg) or 0.0)
        b3_y = float(d.get("b3_yth", yth) or 0.0)
        b3_y_tot = float(d.get("b3_청년등_합계", round(b3_y * n_m, 2)) or 0.0)

        b4_r = float(d.get("b4_reg", reg) or 0.0)
        b4_y = float(d.get("b4_yth", yth) or 0.0)
        has_data = bool(d.get("has_data", reg > 0 or yth > 0))
        return {
            "from_filed": bool(d.get("from_filed")),
            "months_in_year": n_m,
            "regular": reg,
            "youth": yth,
            "non_youth": non_y,
            "reg_total": reg_tot,
            "yth_total": yth_tot,
            "non_youth_total": non_tot,
            "b2_reg": b2_r,
            "b2_yth": b2_y,
            "b2_yth_total": b2_y_tot,
            "b3_reg": b3_r,
            "b3_yth": b3_y,
            "b3_yth_total": b3_y_tot,
            "b4_reg": b4_r,
            "b4_yth": b4_y,
            "has_data": has_data,
        }

    cur_s = _s(t)
    prev_s = _s(t - 1)
    prev2_s = _s(t - 2)
    prev3_s = _s(t - 3)

    # ── 1) 당해(T) 신규 고용증가분 계산 (신법 A+B+C vs 구법) ──
    cur_inc = calc_increase_with_cap(cur_s["regular"], cur_s["youth"], prev_s["regular"], prev_s["youth"])
    rates_legacy = get_unit_rates(corp_size, is_capital, scheme="legacy", retention_year=1)
    rates_new_y1 = get_unit_rates(corp_size, is_capital, scheme="new_2026", retention_year=1)

    cur_legacy_yth_won = int(round(cur_inc["youth_inc"] * rates_legacy["청년등"] * 10_000))
    cur_legacy_gen_won = int(round(cur_inc["non_youth_inc"] * rates_legacy["청년등외"] * 10_000))
    cur_legacy_total_won = cur_legacy_yth_won + cur_legacy_gen_won

    abc_res = calc_new_2026_credit_abc(
        tax_year=t,
        corp_size=corp_size,
        is_capital=is_capital,
        summaries_by_year={t: cur_s, t - 1: prev_s, t - 2: prev2_s, t - 3: prev3_s},
    )
    hurdle_res = abc_res["tiers"]["A"]["hurdle"]
    cur_new_yth_won = abc_res["tiers"]["A"]["item1_youth_won"]
    cur_new_gen_won = abc_res["tiers"]["A"]["item2_non_youth_won"]
    cur_new_ded_won = abc_res["tiers"]["A"]["item3_deduction_won"]
    cur_new_a_won = abc_res["A_won"]
    cur_new_b_won = abc_res["B_won"]
    cur_new_c_won = abc_res["C_won"]
    cur_new_total_won = abc_res["total_abc_won"]

    active_scheme = "new_2026" if (t >= 2026 and scheme_2026 == "new_2026") else "legacy"
    cur_base_credit_won = cur_new_total_won if active_scheme == "new_2026" else cur_legacy_total_won

    # ── 2)·3) 직전·전전연도 귀속분 사후관리 (기신고 기준 / 세법원칙 기준 동시 산출) ──
    def _fv(d: dict, k: str):
        v = d.get(k)
        try:
            return None if v is None or v == "" else float(v)
        except (TypeError, ValueError):
            return None

    def _missing(cohort: int, note: str) -> dict:
        r = calc_legacy_post_management(cohort, t, corp_size, is_capital, 0, 0, 0, 0, 0, 0)
        r.update({"case_code": "기초값 없음", "case_title": "최초공제연도 인원·증가인원이 없어 계산하지 않음",
                  "formula_note": note, "base_missing": True})
        return r

    def _new_law(cohort: int, tier: str, label: str) -> dict:
        r = calc_legacy_post_management(cohort, t, corp_size, is_capital, 0, 0, 0, 0, 0, 0)
        t_info = abc_res["tiers"].get(tier) or {}
        r.update({"case_code": f"신법 {tier} 통합", "case_title": f"{cohort}년 귀속분은 신법 점증형({tier})으로 계산",
                  "retained_yth_inc": t_info.get("youth_inc", 0.0), "retained_gen_inc": t_info.get("non_youth_inc", 0.0),
                  "new_tier_info": t_info,
                  "formula_note": f"{cohort}년 귀속분은 구법 사후관리 대상이 아니며 신법 {label}(B·C) 유지분 공제로 반영됩니다."})
        return r

    def _cohort(cohort: int, elapsed: int, cur_reg: float, cur_yth: float, s_init: dict, s_before: dict) -> tuple[dict, dict, dict]:
        f = pf.get(cohort) or pf.get(str(cohort)) or {}
        # 최초공제연도 사업장 소재지(수도권 여부): 연속공제·추가납부 단가는 최초공제연도 기준. 없으면 현재 소재지.
        coh_cap = is_capital if f.get("is_capital") is None else bool(f.get("is_capital"))
        coh_rates = get_unit_rates(corp_size, coh_cap, scheme="legacy", retention_year=1)
        filed = {k: _fv(f, k) for k in ("init_reg", "init_yth", "init_yth_inc", "init_gen_inc")}
        claimed = int(_fv(f, "claimed_won") or 0)                     # 한도: 기신고 공제세액(사실값)
        cf = int(_fv(f, "carryforward_won") or 0)
        y1_cont = _fv(f, "y1_continued_won")
        paid = int(_fv(f, "prior_clawback_paid_won") or 0)
        extra = {}
        if elapsed == 2:
            extra = dict(prev_pm_reg=prev_s["b2_reg"] if prev_s["has_data"] else None,
                         prev_pm_yth=prev_s["b2_yth"] if prev_s["has_data"] else None,
                         prior_clawback_paid_won=paid,
                         y1_continued_credit_won=int(y1_cont) if y1_cont is not None else None)

        def _run(vals: dict, label: str, borrowed: list[str], claimed: int = claimed, cap_note: str = "") -> dict:
            if any(v is None for v in vals.values()):
                return _missing(cohort, f"[{label}] {cohort}년 최초공제연도의 상시·청년등 인원 또는 공제받은 증가인원이 없습니다. "
                                        f"3단계 위쪽에 기신고 숫자를 입력하세요.")
            r = calc_legacy_post_management(cohort, t, corp_size, coh_cap,
                                            vals["init_reg"], vals["init_yth"], vals["init_yth_inc"], vals["init_gen_inc"],
                                            cur_reg, cur_yth, init_credit_claimed_won=claimed,
                                            unclaimed_carryforward_won=cf, **extra)
            r["base_label"] = label + (f" ({', '.join(borrowed)}은 기신고 숫자 사용)" if borrowed else "")
            if claimed <= 0 and r.get("clawback_gross_won", 0) > 0:
                r["formula_note"] += " ※ 기신고 공제세액이 없어 추가납부 한도를 적용하지 못했습니다."
            if cap_note:
                r["formula_note"] += cap_note
            return r

        r_filed = _run(filed, "기신고 기준", [])
        recalc, borrowed = dict(filed), []
        law_ok = lambda d: d["has_data"] and not d.get("from_filed")
        if law_ok(s_init):
            recalc["init_reg"], recalc["init_yth"] = s_init["regular"], s_init["youth"]
        else:
            borrowed.append("최초연도 인원")
        if law_ok(s_init) and law_ok(s_before):
            inc = calc_increase_with_cap(s_init["regular"], s_init["youth"], s_before["regular"], s_before["youth"])
            recalc["init_yth_inc"], recalc["init_gen_inc"] = inc["youth_inc"], inc["non_youth_inc"]
        else:
            borrowed.append("증가인원")
        # 세법원칙 기준인데 기신고 공제세액이 없으면, 재계산한 증가인원 × 구법 단가로 추가납부 한도를 추정
        recalc_claimed, cap_note = claimed, ""
        if claimed <= 0 and recalc.get("init_yth_inc") is not None and recalc.get("init_gen_inc") is not None:
            recalc_claimed = int(round((float(recalc["init_yth_inc"]) * coh_rates["청년등"]
                                        + float(recalc["init_gen_inc"]) * coh_rates["청년등외"]) * 10_000))
            if elapsed == 2 and y1_cont is None and corp_size not in ("일반기업", "대기업") and not (
                prev_s["has_data"] and prev_s["b2_reg"] < float(recalc.get("init_reg") or 0.0)
            ):
                recalc_claimed *= 2
            cap_note = f" ※ 한도는 재계산 증가인원 × 구법 단가로 추정({recalc_claimed:,}원)했습니다."
        r_recalc = _run(recalc, "세법원칙 기준", borrowed, claimed=recalc_claimed, cap_note=cap_note)
        return r_filed, r_recalc, {"filed": filed, "recalc": recalc, "borrowed": borrowed}

    if (t - 1) <= 2025:
        pm_y1_filed, pm_y1_recalc, base_y1 = _cohort(t - 1, 1, cur_s["b2_reg"], cur_s["b2_yth"], prev_s, prev2_s)
    else:
        pm_y1_filed = pm_y1_recalc = _new_law(t - 1, "B", "2년차")
        base_y1 = {}
    if (t - 2) <= 2025:
        pm_y2_filed, pm_y2_recalc, base_y2 = _cohort(t - 2, 2, cur_s["b3_reg"], cur_s["b3_yth"], prev2_s, prev3_s)
    else:
        pm_y2_filed = pm_y2_recalc = _new_law(t - 2, "C", "3년차")
        base_y2 = {}
    has_t2_data = bool(prev2_s["has_data"])

    pm_y1 = pm_y1_recalc if basis == R.PM_BASIS_RECALC else pm_y1_filed
    pm_y2 = pm_y2_recalc if basis == R.PM_BASIS_RECALC else pm_y2_filed

    # ── 4) 정규직 전환자(~2024년 귀속) 및 육아휴직 복귀자(~2026년 귀속) 추가공제 ──
    add_unit_man = R.ADDITIONAL_CREDIT_PER_PERSON.get(corp_size, 0)
    parental_ret_cnt = int(add_in.get("parental_return_count", 0) or 0) if t <= 2026 else 0
    reg_conv_cnt = int(add_in.get("regular_conversion_count", 0) or 0) if t <= 2024 else 0
    early_term_add_cnt = int(add_in.get("additional_clawback_count", 0) or 0)
    maternity_rep_cnt = float(add_in.get("maternity_replacement_count", 0.0) or 0.0)      # 당해 제외 인원(연평균)
    maternity_prev_cnt = float(add_in.get("maternity_prev_count", 0.0) or 0.0)            # 직전 제외 인원(연평균)

    non_decrease_ok = (cur_s["regular"] - maternity_rep_cnt + 1e-9) >= (prev_s["regular"] - maternity_prev_cnt)
    additional_credit_won = (
        int((parental_ret_cnt + reg_conv_cnt) * add_unit_man * 10_000) if non_decrease_ok else 0
    )
    additional_clawback_won = int(early_term_add_cnt * add_unit_man * 10_000)

    # ── 5) 총 공제세액 · 총 추가납부세액 · 농어촌특별세(20%) 종합 집계 ──
    total_continued_credit_won = pm_y1["continued_credit_won"] + pm_y2["continued_credit_won"]
    total_credit_gross_won = cur_base_credit_won + total_continued_credit_won + additional_credit_won

    total_clawback_gross_won = (
        pm_y1["clawback_gross_won"] + pm_y2["clawback_gross_won"] + additional_clawback_won
    )
    total_carryforward_offset_won = pm_y1["carryforward_offset_won"] + pm_y2["carryforward_offset_won"]
    total_clawback_net_payable_won = (
        pm_y1["clawback_net_payable_won"] + pm_y2["clawback_net_payable_won"] + additional_clawback_won
    )

    net_tax_benefit_won = total_credit_gross_won - total_clawback_net_payable_won

    cur_unclaimed_cf_won = max(0, int(add_in.get("current_unclaimed_carryforward_won", 0) or 0))
    actual_deducted_credit_won = max(0, total_credit_gross_won - cur_unclaimed_cf_won)
    rural_special_tax_won = int(round(actual_deducted_credit_won * R.RURAL_SPECIAL_TAX_RATE))
    net_after_rural_tax_won = net_tax_benefit_won - rural_special_tax_won

    return {
        "tax_year": t,
        "corp_size": corp_size,
        "is_capital": is_capital,
        "active_scheme": active_scheme,
        "pm_basis": basis,
        "pm_basis_label": R.PM_BASIS_LABELS.get(basis, "기신고 기준"),
        "has_t2_data": has_t2_data,
        "base_y1": base_y1,
        "base_y2": base_y2,
        "cur_s": cur_s,
        "prev_s": prev_s,
        "prev2_s": prev2_s,
        "cur_inc": cur_inc,
        "hurdle_res": hurdle_res,
        "abc_res": abc_res,
        "rates_legacy": rates_legacy,
        "rates_new_y1": rates_new_y1,
        "cur_legacy_yth_won": cur_legacy_yth_won,
        "cur_legacy_gen_won": cur_legacy_gen_won,
        "cur_legacy_total_won": cur_legacy_total_won,
        "cur_new_yth_won": cur_new_yth_won,
        "cur_new_gen_won": cur_new_gen_won,
        "cur_new_ded_won": cur_new_ded_won,
        "cur_new_a_won": cur_new_a_won,
        "cur_new_b_won": cur_new_b_won,
        "cur_new_c_won": cur_new_c_won,
        "cur_new_total_won": cur_new_total_won,
        "cur_base_credit_won": cur_base_credit_won,
        "pm_y1": pm_y1,
        "pm_y2": pm_y2,
        "pm_y1_filed": pm_y1_filed,
        "pm_y1_recalc": pm_y1_recalc,
        "pm_y2_filed": pm_y2_filed,
        "pm_y2_recalc": pm_y2_recalc,
        "y1_claimed_won": int(_fv(pf.get(t - 1) or pf.get(str(t - 1)) or {}, "claimed_won") or 0),
        "y2_claimed_won": int(_fv(pf.get(t - 2) or pf.get(str(t - 2)) or {}, "claimed_won") or 0),
        "non_decrease_ok": non_decrease_ok,
        "maternity_rep_cnt": maternity_rep_cnt,
        "maternity_prev_cnt": maternity_prev_cnt,
        "parental_ret_cnt": parental_ret_cnt,
        "reg_conv_cnt": reg_conv_cnt,
        "early_term_add_cnt": early_term_add_cnt,
        "additional_credit_won": additional_credit_won,
        "additional_clawback_won": additional_clawback_won,
        "total_continued_credit_won": total_continued_credit_won,
        "total_credit_gross_won": total_credit_gross_won,
        "cur_unclaimed_cf_won": cur_unclaimed_cf_won,
        "actual_deducted_credit_won": actual_deducted_credit_won,
        "total_clawback_gross_won": total_clawback_gross_won,
        "total_carryforward_offset_won": total_carryforward_offset_won,
        "total_clawback_net_payable_won": total_clawback_net_payable_won,
        "net_tax_benefit_won": net_tax_benefit_won,
        "rural_special_tax_won": rural_special_tax_won,
        "net_after_rural_tax_won": net_after_rural_tax_won,
    }


# ══════════════════════════════════════════════════════════════════
# 6. 100% 성능 12대 법령 · 심판례 · 절세누락 정밀 오류 검토 엔진 (Review Dialog용)
# ══════════════════════════════════════════════════════════════════
def review(
    people: dict,
    year_recs: dict,
    years: list[int],
    ctx_by_year: dict,
    computed: dict,
    prev_filing: dict | None = None,
    sub_biz_list: list[dict] | None = None,
    **kwargs,
) -> list[tuple[str, str]]:
    """
    2단계 [🔍 오류 검토] 모달 및 4단계 감사 리포트에서 사용하는 12대 세무·절세 정밀 진단 엔진.
    반환 형식: [("오류" | "절세누락" | "확인", 상세 설명), ...]
    """
    items: list[tuple[str, str]] = []

    # 0) 복수 사업장(합산 사유) 설정에 따른 필수 입력값 누락 점검
    for idx, sb in enumerate(sub_biz_list or []):
        sb_nm = str(sb.get("상호") or f"제{idx+2}사업장").strip()
        sb_tp = str(sb.get("구분") or "").strip()
        if "기중양도" in sb_tp and not parse_date(sb.get("폐업일")):
            items.append(
                (
                    "오류",
                    f"[복수 사업장 · {sb_nm}] 합산 사유가 '{sb_tp}'으로 선택되었으나 '폐업·양도일'이 비어 있습니다. "
                    f"좌측 사이드바에서 양도일을 입력해야 양도월 이후 미도래 월 자동 산입이 차단됩니다.",
                )
            )
        if ("포괄양수" in sb_tp or "승계" in sb_tp) and float(sb.get("승계_직전상시", 0.0) or 0.0) <= 0:
            items.append(
                (
                    "확인",
                    f"[복수 사업장 · {sb_nm}] 합산 사유가 '{sb_tp}'으로 선택되었습니다. "
                    f"조특령 제26조의8 제10항에 따라 종전 사업장의 직전 과세연도 상시근로자 수를 좌측 사이드바에 합산 입력했는지 확인하세요.",
                )
            )

    for y in years:
        c_map = computed.get(y) or {}
        ctx = ctx_by_year.get(y) or {}
        n_months = ctx.get("months_in_year", 12)
        corp_size = ctx.get("corp_size") or "중소기업"
        rows = list(c_map.values())
        emp_types = [r.get("고용유형", R.EMP_REGULAR) for r in rows]

        # 1) 단시간(0.75 가중치) 적용 요건 검증 (조특령 제26조의8 제6항 단서)
        if any(et == R.EMP_PT_075 for et in emp_types):
            cur_ft = regular_excluding_part_time(rows, emp_types, n_months)
            if cur_ft < 0.75:
                items.append(
                    (
                        "오류",
                        f"[{y}년 · 단시간 0.75 요건 위반] 단시간 제외 상시근로자 수({cur_ft:.2f}명)가 최소 기준(0.75명) 미만이라 단시간 0.75명 가중치를 적용할 수 없습니다 (0.5명 적용 대상).",
                    )
                )
            prev_y = y - 1
            if prev_y in computed:
                prev_rows = list(computed[prev_y].values())
                prev_ets = [r.get("고용유형", R.EMP_REGULAR) for r in prev_rows]
                prev_ft = regular_excluding_part_time(
                    prev_rows, prev_ets, (ctx_by_year.get(prev_y) or {}).get("months_in_year", 12)
                )
                if cur_ft < prev_ft:
                    items.append(
                        (
                            "오류",
                            f"[{y}년 · 단시간 0.75 요건 위반] 통상근로자 상시근로자 수가 직전연도({prev_ft:.2f}명)보다 감소({cur_ft:.2f}명)하여 단시간 0.75 대신 0.5를 적용해야 합니다.",
                        )
                    )

        cohort_preserved_names: list[str] = []
        projected_names: list[str] = []
        hire_nopay_names: list[str] = []
        nopay_names: list[str] = []
        succession_names: list[str] = []
        transferred_out_names: list[str] = []
        absent_wht_names: list[str] = []

        for pid, c in c_map.items():
            p = people.get(pid) or {}
            nm = p.get("성명") or pid
            wp = (p.get("연도별_사업장명") or {}).get(str(y)) or p.get("사업장명") or ""
            nm_disp = f"{nm}({wp})" if wp and wp != "본점" else nm
            yrec = (year_recs.get(y) or {}).get(pid) or {}

            birth_dt = parse_date(p.get("생년월일"))
            hire_dt = parse_date(p.get("입사일"))
            ret_dt = parse_date((p.get("연도별_퇴사일") or {}).get(str(y)) or p.get("퇴사일"))
            mil_m = int(p.get("병역개월", 0) or 0)
            c_age = contract_age(p)
            pay_obj = (p.get("월급여") or {}).get(str(y))

            # 2) 입·퇴사일 역전 오류
            if hire_dt and ret_dt and ret_dt < hire_dt:
                items.append(
                    (
                        "오류",
                        f"[{y}년 · {nm_disp}] 퇴사일({ret_dt})이 입사일({hire_dt})보다 빠릅니다. 입·퇴사일을 정정하세요.",
                    )
                )

            # 3) 퇴사일 이후 월 급여 지급 여부 점검 (퇴직 후 성과급·정산금 vs 재입사)
            if ret_dt and _has_any_pay_record(pay_obj):
                if ret_dt.year == y and ret_dt.month < 12:
                    post_ret_months = [
                        m for m in range(ret_dt.month + 1, 13)
                        if (_get_month_pay(pay_obj, m) or 0.0) > 0
                    ]
                    if post_ret_months:
                        m_str = ", ".join(f"{m}월" for m in post_ret_months)
                        items.append(
                            (
                                "오류",
                                f"[{y}년 · {nm_disp}] 퇴사일({ret_dt}) 이후인 {m_str}에 급여 지급 내역이 존재합니다. "
                                f"중도 퇴사 후 재입사했거나 퇴사일 오기재라면 퇴사일을 수정하세요 (단순 퇴직 후 미지급금 정산이면 현재처럼 0 제외가 맞습니다).",
                            )
                        )
                elif ret_dt.year < y:
                    paid_m = [m for m in range(1, 13) if (_get_month_pay(pay_obj, m) or 0.0) > 0]
                    if paid_m:
                        items.append(
                            (
                                "오류",
                                f"[{y}년 · {nm_disp}] 과거 퇴사일({ret_dt}) 이후인 {y}년에 급여 지급 내역({len(paid_m)}개 월)이 있습니다. 재입사 여부를 확인하세요.",
                            )
                        )

            # 4) 1년 미만 단기 퇴사자가 상시='O'로 산입된 경우 경고 (조특령 §23⑩ 1호)
            if c["상시"] == "O" and hire_dt and ret_dt and tenure_under_1y(p, y):
                tenure_days = (ret_dt - hire_dt).days + 1
                items.append(
                    (
                        "확인",
                        (f"[{y}년 · {nm_disp}] 총 근로기간이 {tenure_days}일({hire_dt} ~ {ret_dt})로 1년 미만인데 상시근로자('O')로 산입되어 있습니다. "
                         f"2025년 귀속부터는 계약기간과 무관하게 실제 근로기간 1년 미만이면 제외됩니다(조특령 제26조의8 제2항 제1호). 상시(O/X)를 확인하세요.")
                        if y >= 2025 else
                        (f"[{y}년 · {nm_disp}] 총 재직기간이 {tenure_days}일({hire_dt} ~ {ret_dt})로 1년 미만이나 현재 상시근로자('O')로 산입되어 있습니다. "
                         f"{y}년 귀속은 종전 규정(근로계약기간 1년 미만 제외)이 적용되므로, 계약기간 자체가 1년 미만이었다면 제외사유를 변경하세요."),
                    )
                )

            # 5) 필수 입사일·생년월일 누락 점검
            if c["상시"] == "O":
                if not hire_dt:
                    items.append(
                        (
                            "오류",
                            f"[{y}년 · {nm_disp}] 입사일이 비어 있습니다. 매월 말 재직 판정 및 청년등 연령 계산을 위해 입사일을 입력하세요.",
                        )
                    )
                if c["청년등"] in (R.YOUTH_YOUNG, R.YOUTH_SENIOR) and not birth_dt:
                    items.append(
                        (
                            "오류",
                            f"[{y}년 · {nm_disp}] 생년월일이 비어 있어 '{c['청년등']}' 연령 요건을 검증할 수 없습니다.",
                        )
                    )

            # 6) [절세누락 자동 탐지] 청년(15~34세) 또는 고령자(60세 이상) 요건 충족자 중 '해당없음(일반)'으로 설정된 경우
            if c["상시"] == "O" and c["청년등"] == R.YOUTH_NONE and c["row_sum"] > 0 and birth_dt and hire_dt:
                sug_y = suggest_youth(p, yrec, y, corp_size)
                if sug_y == R.YOUTH_SENIOR and c_age is not None and c_age >= R.SENIOR_AGE:
                    items.append(
                        (
                            "절세누락",
                            f"[{y}년 · {nm_disp}] 입사 당시 만 {c_age}세(60세 이상 고령자)로 『취업시 60세 이상』 우대공제 대상이나 현재 '해당없음(일반)'으로 설정되어 있습니다! "
                            f"'취업시 60세 이상'으로 변경하면 청년등 우대 공제단가가 적용됩니다.",
                        )
                    )
                elif sug_y == R.YOUTH_YOUNG and c_age is not None and (R.YOUTH_AGE_MIN <= c_age <= R.YOUTH_AGE_MAX):
                    items.append(
                        (
                            "절세누락",
                            f"[{y}년 · {nm_disp}] 입사 당시 만 {c_age}세로 {y}년 중 청년 요건(15~34세)을 충족하나 현재 '해당없음(일반)'으로 설정되어 있습니다! "
                            f"특별한 제외 사유가 없다면 『{R.YOUTH_YOUNG}』으로 변경하여 청년등 우대 공제단가를 적용받으세요.",
                        )
                    )

            # 7) 청년·고령자 연령 초과 오분류 및 병역이행(35~40세) 절세 후보 발굴
            if c["상시"] == "O" and c["청년등"] == R.YOUTH_SENIOR:
                if c_age is not None and c_age < R.SENIOR_AGE:
                    items.append(
                        (
                            "오류",
                            f"[{y}년 · {nm_disp}] 근로계약 체결일 기준 만 {c_age}세라 '취업시 60세 이상'에 해당하지 않습니다.",
                        )
                    )

            if c["상시"] == "O" and c["청년등"] == R.YOUTH_YOUNG:
                if c_age is not None and c_age > R.YOUTH_AGE_MAX and mil_m == 0:
                    if c_age <= R.YOUTH_AGE_MAX + 6:
                        items.append(
                            (
                                "확인",
                                f"[{y}년 · {nm_disp}] 입사 시 만 나이가 {c_age}세로 34세를 초과합니다. "
                                f"병역이행기간(최대 72개월)이 있다면 '병역(월)' 칸에 입력하여 청년 요건 충족 여부를 확인하세요.",
                            )
                        )
                    else:
                        items.append(
                            (
                                "오류",
                                f"[{y}년 · {nm_disp}] 입사 시 만 나이가 {c_age}세로 청년 연령(15~34세)을 초과합니다.",
                            )
                        )
            elif c["상시"] == "O" and c["청년등"] == R.YOUTH_NONE and c_age is not None and (35 <= c_age <= 40) and mil_m == 0:
                need_mil_years = c_age - R.YOUTH_AGE_MAX
                items.append(
                    (
                        "확인",
                        f"[{y}년 · {nm_disp} · 병역차감 후보] 입사 시 만 {c_age}세로 34세를 {need_mil_years}세 초과하여 일반근로자로 분류되었습니다. "
                        f"만약 군 복무 이력이 있다면 '병역(월)' 칸에 복무개월수(최대 72개월)를 입력 시 『취업시 청년』 우대공제 전환이 가능할 수 있습니다.",
                    )
                )

            if c["청년등"] == R.YOUTH_NK and y <= 2024:
                items.append(
                    (
                        "확인",
                        f"[{y}년 · {nm_disp}] 북한이탈주민은 2025.2.28 시행령 개정으로 2025년 귀속분부터 청년등 상시근로자에 포함됩니다.",
                    )
                )

            # 8) 단시간근로자(0.5/0.75) 월급여 급증(통상근로 전환 의심) 점검
            if c["상시"] == "O" and c["고용유형"] in (R.EMP_PT_050, R.EMP_PT_075) and _has_any_pay_record(pay_obj):
                pays = [(_get_month_pay(pay_obj, m) or 0.0) for m in range(1, 13) if (_get_month_pay(pay_obj, m) or 0.0) > 0]
                if pays and max(pays) >= 2_500_000 and min(pays) > 0 and (max(pays) / min(pays)) >= 1.6:
                    items.append(
                        (
                            "확인",
                            f"[{y}년 · {nm_disp}] 단시간근로자({c['고용유형']})로 설정되어 있으나 기중 월급여가 {min(pays):,.0f}원 → {max(pays):,.0f}원으로 크게 증가했습니다. "
                            f"기중에 통상근로자(주 40시간)로 전환되었다면 고용유형 및 가중치(1.0) 반영 여부를 확인하세요.",
                        )
                    )

            # 9) 복수 사업장 전출입 합산 안내
            if "→" in wp:
                items.append(
                    (
                        "확인",
                        f"[{y}년 · {nm_disp}] 복수 사업장 간 이동·승계({wp})가 감지되어 월별 급여 및 재직기간을 합산 반영했습니다 (조특령 제26조의8 제10항).",
                    )
                )

            # 10) 입사월 무급(익월지급) vs 기중 무급휴직 연도별 그룹화 수집 (오류검토 창이 한 화면에 들어오도록 요약)
            if c.get("hire_month_nopay"):
                raw_ms = c["hire_month_nopay"]
                ms = [raw_ms] if isinstance(raw_ms, int) else list(raw_ms)
                m_str = f"{ms[0]}월" if len(ms) == 1 else f"{min(ms)}~{max(ms)}월"
                hire_nopay_names.append(f"{nm_disp}({m_str})")
            if c.get("no_pay_months"):
                raw_ms = c["no_pay_months"]
                ms = [raw_ms] if isinstance(raw_ms, int) else list(raw_ms)
                m_str = f"{ms[0]}월" if len(ms) == 1 else (f"{min(ms)}~{max(ms)}월" if ms == list(range(min(ms), max(ms) + 1)) else ",".join(f"{m}월" for m in ms))
                nopay_names.append(f"{nm_disp}({m_str})")

            if c.get("projected_months"):
                projected_names.append(f"{nm_disp}({min(c['projected_months'])}~{max(c['projected_months'])}월)")

            # 11) 청년 연령 도과자 사후관리/연속공제 청년 간주(조특령 §26의8⑤) 자동 보호 내역 수집
            if c["상시"] == "O" and (c.get("b2_yth", 0) > c.get("b1_yth", 0) or c.get("b3_yth", 0) > c.get("b1_yth", 0)):
                cohort_preserved_names.append(
                    f"{nm_disp}(당해 청년 {c['b1_yth']:.2f} → 1차사후 {c['b2_yth']:.2f} / 2차사후 {c['b3_yth']:.2f})"
                )

            # 승계·양도·미등재 처리 안내 (연도별 그룹화 수집)
            if c.get("succession_months"):
                succession_names.append(f"{nm_disp}({len(c['succession_months'])}개월)")
            if c.get("transferred_out"):
                transferred_out_names.append(nm_disp)
            if c.get("absent_in_wht"):
                absent_wht_names.append(nm_disp)

            if p.get("외국인") and c.get("상시") == "O":
                items.append(("확인", f"[{y}년 · {nm_disp}] 원천징수부에 '외국인'으로 표시되어 있습니다. 상시근로자의 내국인은 국적과 무관하게 "
                                     f"국내에 주소를 두거나 183일 이상 거소를 둔 사람이므로 포함했습니다. 비거주자라면 제외사유를 '외국인 근로자'로 바꾸세요."))

            # 12) 수동 오버라이드 감사 추적
            if yrec.get("상시_override"):
                items.append(
                    (
                        "확인",
                        f"[{y}년 · {nm_disp}] 상시 여부가 자동판정({c['상시_auto']})에서 '{c['상시']}'로 수동 변경되었습니다.",
                    )
                )
            if yrec.get("월_override"):
                ovr_m_keys = sorted(int(k) for k in (yrec.get("월_override") or {}).keys() if str(k).isdigit())
                if ovr_m_keys:
                    items.append(
                        (
                            "확인",
                            f"[{y}년 · {nm_disp}] {', '.join(f'{m}월' for m in ovr_m_keys)} 상시근로자 수치가 수동 입력(오버라이드)되었습니다.",
                        )
                    )

        if cohort_preserved_names:
            items.append(
                (
                    "확인",
                    f"[{y}년 · 청년 연령도과 사후관리 특례 자동적용] {', '.join(cohort_preserved_names)}: "
                    f"근로계약 체결일부터 청년 인정기간(중소·중견 4년/그 외 3년) 도과로 당해 세액공제(3번 블록)에서는 '청년외'로 전환되었으나, "
                    f"조특령 제26조의8 제5항에 따라 1·2차 사후관리(4·5번 블록)에서는 최초공제연도 기준 '청년등'으로 안전하게 유지되었습니다.",
                )
            )

        if hire_nopay_names:
            items.append(
                (
                    "확인",
                    f"[{y}년 · 입사월 급여 0원 익월지급 산입({len(hire_nopay_names)}명)] {', '.join(hire_nopay_names[:8])}{' 외 ' + str(len(hire_nopay_names) - 8) + '명' if len(hire_nopay_names) > 8 else ''}: "
                    f"입사월 급여가 0원이나 익월 지급 관행을 고려해 재직(산입)으로 두고 살구색으로 표시했습니다 (미근무 시 0으로 수정하거나 상단 체크 해제).",
                )
            )

        if nopay_names:
            items.append(
                (
                    "확인",
                    f"[{y}년 · 재직 중 급여 0원 월 자동 제외({len(nopay_names)}명)] {', '.join(nopay_names[:8])}{' 외 ' + str(len(nopay_names) - 8) + '명' if len(nopay_names) > 8 else ''}: "
                    f"재직기간 중 급여가 없는 달(살구색 표시)은 상시근로자에서 자동 제외(0)되었습니다 (육아휴직·무급휴직 여부 확인).",
                )
            )

        if succession_names:
            items.append(
                (
                    "확인",
                    f"[{y}년 · 포괄양수·승계 개시일 산입({len(succession_names)}명)] {', '.join(succession_names[:8])}{' 외 ' + str(len(succession_names) - 8) + '명' if len(succession_names) > 8 else ''}: "
                    f"포괄양수·승계 근로자로 승계일 이전 기간을 과세연도 개시일 승계 의제로 산입했습니다 (조특령 제23조 제13항 준용).",
                )
            )

        if transferred_out_names:
            items.append(
                (
                    "확인",
                    f"[{y}년 · 기중양도(고용승계) 제외·직전연도 차감({len(transferred_out_names)}명)] {', '.join(transferred_out_names[:8])}{' 외 ' + str(len(transferred_out_names) - 8) + '명' if len(transferred_out_names) > 8 else ''}: "
                    f"기중양도 사업장 근로자로 개시일에 승계시킨 것으로 보아 {y}년 인원에서 제외하고 직전연도 인원에서도 차감했습니다 (조특령 제23조 제13항 준용).",
                )
            )

        if absent_wht_names:
            items.append(
                (
                    "확인",
                    f"[{y}년 · 원천징수부 미등재 0 처리({len(absent_wht_names)}명)] {', '.join(absent_wht_names[:8])}{' 외 ' + str(len(absent_wht_names) - 8) + '명' if len(absent_wht_names) > 8 else ''}: "
                    f"{y}년 원천징수부에 없는 사람이라 {y}년에는 근무하지 않은 것으로 보아 0으로 처리했습니다 (실제 근무 시 월별 칸 직접 입력).",
                )
            )

        if projected_names:
            items.append(
                (
                    "확인",
                    f"[{y}년 · 기중 가결산 연말재직 가정({len(projected_names)}명)] {', '.join(projected_names[:6])}{' 외 ' + str(len(projected_names) - 6) + '명' if len(projected_names) > 6 else ''}의 "
                    f"미도래 월이 하늘색 셀('연말까지 재직 가정')로 자동 산입되었습니다.",
                )
            )

    # 13) 기신고 내역 vs 세법원칙 재계산 수치 대조
    if prev_filing and isinstance(prev_filing, dict):
        for y_str, pdata in prev_filing.items():
            try:
                yi = int(y_str)
            except (TypeError, ValueError):
                continue
            if yi in computed and isinstance(pdata, dict):
                tot = year_totals(list(computed[yi].values()), (ctx_by_year.get(yi) or {}).get("months_in_year", 12), year=yi)
                prev_reg = pdata.get("상시")
                prev_yth = pdata.get("청년등")
                if prev_reg is not None and abs(float(prev_reg) - tot["상시_평균"]) >= 0.01:
                    items.append(
                        (
                            "확인",
                            f"[{yi}년 기신고 대조] 기신고 상시근로자 수({float(prev_reg):.2f}명)와 "
                            f"세법원칙 재계산 상시근로자 수({tot['상시_평균']:.2f}명)가 {abs(float(prev_reg) - tot['상시_평균']):.2f}명 차이납니다. "
                            f"3단계 우측 상단에서 '기신고 기준(원칙)'과 '세법원칙 기준(경정청구·수정신고용)'을 선택하여 비교할 수 있습니다.",
                        )
                    )
                if prev_yth is not None and abs(float(prev_yth) - tot["청년등_평균"]) >= 0.01:
                    items.append(
                        (
                            "확인",
                            f"[{yi}년 기신고 대조] 기신고 청년등 상시근로자 수({float(prev_yth):.2f}명)와 "
                            f"세법원칙 재계산 청년등 상시근로자 수({tot['청년등_평균']:.2f}명)가 {abs(float(prev_yth) - tot['청년등_평균']):.2f}명 차이납니다.",
                        )
                    )

    # 중요도 순 정렬: 오류 -> 절세누락 -> 확인
    priority = {"오류": 0, "절세누락": 1, "확인": 2}
    items.sort(key=lambda x: priority.get(x[0], 9))
    return items