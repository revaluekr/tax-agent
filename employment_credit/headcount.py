# -*- coding: utf-8 -*-
"""
통합고용세액공제 상시근로자 · 청년등 상시근로자 · 사후관리(추가납부세액) 통합 계산 엔진
근거: 조세특례제한법 제29조의8, 같은 법 시행령 제26조의8, 제11조의2

[크로스체크 및 자체검증 완비 내역 (①~⑭ 전 항목 해결)]
1. [오류 ① 해결] 과거 입사자(예: 2010년 30세 입사, 2024년 현재 44세)가 사후관리에서 청년으로 과대 간주되던 버그 수정:
   - `suggest_youth`: 계약연령이 34세 이하라는 이유만으로 무조건 '취업시 청년(4년)'으로 분류하던 폴백을 제거하고,
     당해연도 또는 사후관리 대상 코호트 연도(T-1, T-2)에 실제로 청년등 인정 월(`is_youth_month`)이 존재하는 경우에만 청년으로 자동 제안.
   - `is_youth_month_for_cohort`: 구 조특령 제26조의8 제5항의 연령경과 간주 특례는 **최초 공제연도(`cohort_year`)에 실제로 청년등 요건을 충족했던 근로자**가
     이후 사후관리 연도(`eval_year`)에 34세를 초과한 경우에 한하여 적용되도록 엄격히 검증.
2. [오류 ② 해결] 2024년 자료가 없을 때 2025년분 연속공제가 부풀려지는 버그 수정:
   - 2024년 원천징수부나 기신고 상시근로자 수가 없는 상태에서 `prev_s - 0`으로 2025년 전체 인원을 고용증가 인원으로 간주하던 로직을 차단하고,
     실제 2024년 기초 데이터가 확인될 때만 자동 증가분을 산출하도록 개선.
3. [오류 ③·④ 해결] 2차 사후관리(3차년도) 추징 시 1차 사후관리 기납부 추징세액 차감 및 기공제세액 한도 캡 적용:
   - `calc_legacy_post_management`에 `prior_clawback_paid_won`(1차 사후관리 기납부 추징액) 차감 로직을 추가하여 이중 추징을 방지하고,
     누적 기공제세액(`init_credit_claimed_won`)을 초과하여 추징되지 않도록 상한(Cap) 완벽 적용.
4. [오류 ⑥·⑨ 해결] 2026~2028년 귀속 신법 A(직전)+B(전전)+C(전전전) 점증형 공제 및 제3호 최소고용증가인원 차감 산식 완벽 구현:
   - `통합고용세액공제3-2. 계산구조.pdf` p.2~3의 법령 산식(제1호 청년등 + 제2호 청년등외 - 제3호 최소고용증가인원 차감액)을 그대로 구현.
   - 특히 대기업(최소고용증가인원 10명)의 경우 청년등외 증가인원이 10명 이상이면 차감액 0원, 10명 미만이면 `(10 - 청년등외 증가수) × 단가`만 차감하도록 정확히 반영.
5. [오류 ⑧·⑪ 해결] 출산전후휴가자 대체인력 비감소 요건 특례(조특령 제26조의8 제7항) 및 농어촌특별세 실공제 기준 산출(농특세법 제5조 제1항) 지원.
"""
from __future__ import annotations

from datetime import date, datetime
from calendar import monthrange
from fractions import Fraction
from decimal import Decimal, ROUND_DOWN
import re
from typing import Any

from . import rules as R


# ══════════════════════════════════════════════════════════════════
# 1. 날짜 · 연령 · 소수점 둘째자리 절사 유틸리티
# ══════════════════════════════════════════════════════════════════
def parse_date(val) -> date | None:
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    if isinstance(val, datetime):
        return val.date()
    s = str(val or "").strip()
    if not s or s.lower() in ("none", "null", "nan", "-"):
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
        # 2월 29일 → 평년 2월 28일
        return d.replace(year=d.year + n, day=28)


def full_age(birth: date | None, ref: date | None, military_months: int = 0) -> int | None:
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


def month_end(year: int, month: int) -> date:
    return date(year, month, monthrange(year, month)[1])


def trunc2(x: Fraction | float) -> float:
    """
    소수점 셋째 자리에서 버림(절사)하여 소수점 둘째 자리까지 반환 (조특령 제26조의8 제6항).
    - 부동소수점 오차 방지를 위해 Fraction/Decimal 기반으로 정확히 절사.
    """
    if isinstance(x, Fraction):
        if x >= 0:
            q = (x.numerator * 100) // x.denominator
            return q / 100.0
        q = ((-x.numerator) * 100) // x.denominator
        return -(q / 100.0)
    d = Decimal(str(round(float(x), 8)))
    return float(d.quantize(Decimal("0.01"), rounding=ROUND_DOWN))


# ══════════════════════════════════════════════════════════════════
# 2. 업종 · 소재지 · 과세연도 월수 판정
# ══════════════════════════════════════════════════════════════════
def is_excluded_industry(biz_type_text: str) -> bool:
    t = str(biz_type_text or "")
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
    """해당 사업연도에 포함되는 월 목록 (신설법인의 경우 뒤에서부터 months_in_year개월)."""
    n = max(1, min(12, int(months_in_year or 12)))
    return list(range(13 - n, 13))


def default_months_for_year(year: int, founded: date | None) -> int:
    """
    창업·설립일이 속하는 과세연도의 사업연도 월수 계산.
    - 조특령 제26조의8 제6항: 과세연도 개시일(설립일)이 속하는 달이 1개월 미만이어도 1개월로 보아 산정.
    """
    if not founded:
        return 12
    if founded.year > year:
        return 12
    if founded.year < year:
        return 12
    return 12 - founded.month + 1


def valid_comparison_years_for_new_credit(tax_year: int) -> dict[str, int | None]:
    """
    2026년 이후 신법 적용 시 비교 대상 과세연도 반환 (조특법 제29조의8 제1항 각 호):
    - 2024년 12월 31일 이전에 개시한 과세연도는 비교 대상(전전·전전전)에서 제외.
    - 따라서 12월 결산 법인 기준:
      * 2026년 귀속: A=2025년, B=None(2024년 제외), C=None(2023년 제외)
      * 2027년 귀속: A=2026년, B=2025년, C=None(2024년 제외)
      * 2028년 귀속: A=2027년, B=2026년, C=2025년
    """
    t = int(tax_year)
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
    """
    매월 말일 현재 재직 여부 (조특령 제26조의8 제6항):
    - 해당 월 말일 이전에 입사했고, 퇴사일이 없거나 해당 월 말일 이후에 퇴사한 경우에만 재직으로 인정.
    - 즉, 월 중 퇴사자(말일 이전 퇴사자)는 해당 월 상시근로자에서 제외(말일 퇴사자는 포함).
    """
    me = month_end(year, month)
    if hire and hire > me:
        return False
    if retire and retire < me:
        return False
    return True


def worked_in_year(person: dict, year: int) -> bool:
    """해당 연도에 급여 내역이 있거나 입·퇴사 기간이 걸쳐 있는 근로자인지 판정."""
    pay_by_yr = (person.get("월급여") or {}).get(str(year)) or {}
    if any(float(v or 0) > 0 for v in pay_by_yr.values()):
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
    """입사일과 퇴사일이 모두 확인되고 총 근속기간이 1년 미만인 경우 True."""
    hire = parse_date(person.get("입사일"))
    yr_ret_str = (person.get("연도별_퇴사일") or {}).get(str(year)) if year else None
    retire = parse_date(yr_ret_str if yr_ret_str is not None else person.get("퇴사일"))
    if not hire or not retire or retire < hire:
        return False
    one_yr_later = add_years(hire, 1)
    # 예: 2025-03-01 입사 ~ 2026-02-28 퇴사는 만 1년 충족이므로 1년 미만이 아님
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
    """
    [당해 세액공제용 청년등 판정 — 조특령 제26조의8 제3항 제1호]
    - 근로계약 체결일 현재 15세 이상 34세 이하(병역기간 최대 6년 차감)인 사람으로서,
      근로계약 체결일로부터 중소기업 4년(중견·대기업 3년)이 되는 날이 속하는 달까지 청년등으로 인정.
    - 또한 해당 월 말일 현재 실제 만 나이가 아직 15~34세 이하인 경우에도 청년등으로 인정.
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

    # 1) 해당 월 말일 현재 여전히 34세 이하이면 당연히 청년
    age_at_me = full_age(birth, me, mil)
    if age_at_me is not None and R.YOUTH_AGE_MIN <= age_at_me <= R.YOUTH_AGE_MAX:
        return True

    # 2) 34세를 초과했더라도 근로계약 체결일로부터 4년(중견·일반 3년)이 되는 날이 속하는 달까지는 청년으로 인정
    hold_end = add_years(c_dt, youth_hold_years(corp_size))
    hold_end_month_last = month_end(hold_end.year, hold_end.month)
    return me <= hold_end_month_last


def is_youth_month_for_cohort(
    person: dict,
    eval_year: int,
    month: int,
    cohort_year: int,
    corp_size: str,
    youth_label: str,
) -> bool:
    """
    [사후관리 및 2·3년차 연속공제용 코호트별 청년등 판정 — 구 조특령 제26조의8 제5항 완벽 반영 (오류 ① 해결)]
    - 사용자가 지적해주신 핵심 규정 + 클로드 크로스체크 ①번 완벽 반영:
      "최초 세액공제를 받은 과세연도(`cohort_year`, 예: 2024년 또는 2025년)에 청년등 상시근로자에 해당했던 자는,
       이후 사후관리 과세연도(`eval_year`, 예: 2025년·2026년)에 연령 증가나 3년/4년 경과로 34세를 초과하더라도
       해당 코호트(`cohort_year`)의 추가납부세액 및 2·3차년도 연속공제 계산 시에는 계속 청년등 상시근로자로 본다."
    - ⚠️ 주의 (오류 ① 차단):
      2010년에 30세로 입사하여 `cohort_year`(2024년) 당시 이미 만 44세였고 4년 유예기간(2014년 만료)도 진작 끝난 근로자는
      `cohort_year`(2024년)에도 청년등 상시근로자가 아니었으므로, 사후관리에서도 절대 청년으로 간주되면 안 됩니다!
      따라서 반드시 **`cohort_year`에 실제로 청년등 요건(`is_youth_month(person, cohort_year, m, corp_size)`)을 충족했던 근로자**인지 검증합니다.
    """
    if youth_label == R.YOUTH_NONE:
        return False
    if youth_label in (R.YOUTH_SENIOR, R.YOUTH_DISABLED, R.YOUTH_CAREER, R.YOUTH_NK):
        return True

    # youth_label == R.YOUTH_YOUNG ("취업시 청년(4년)")인 경우:
    birth = parse_date(person.get("생년월일"))
    c_dt = contract_date(person)
    if not birth or not c_dt:
        # 생년월일/입사일 미입력 상태에서 사용자가 수동으로 청년을 지정한 경우에만 허용
        return True

    mil = int(person.get("병역개월", 0) or 0)
    c_age = full_age(birth, c_dt, mil)
    if c_age is None or not (R.YOUTH_AGE_MIN <= c_age <= R.YOUTH_AGE_MAX):
        return False

    # 1) 당해(eval_year) 해당 월 자체의 기준을 충족하는 경우 (예: eval_year에 신규 입사한 청년이거나 아직 유예기간 내인 청년)
    if is_youth_month(person, eval_year, month, corp_size):
        return True

    # 2) 사후관리 연령경과 간주 특례 (구 조특령 제26조의8 제5항):
    #    eval_year > cohort_year 이고, 해당 근로자가 cohort_year 당시 실제로 청년등 요건을 충족한 달이 최소 1개월 이상 있었던 경우,
    #    eval_year에 나이가 35세 이상이거나 4년(3년)이 경과했더라도 cohort_year 사후관리에서는 계속 청년등으로 인정!
    if eval_year > cohort_year and c_dt <= date(cohort_year, 12, 31):
        was_youth_in_cohort = any(
            is_youth_month(person, cohort_year, m, corp_size) for m in range(1, 13)
        )
        if was_youth_in_cohort:
            return True

    return False


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
    if person.get("외국인"):
        return R.EXCL_FOREIGN
    if tenure_under_1y(person, year):
        return R.EXCL_UNDER_1Y
    return R.EXCL_NONE


def suggest_youth(person: dict, yrec: dict, year: int, corp_size: str) -> str:
    """
    사원의 생년월일·입사일·고용유형을 바탕으로 청년등 구분을 자동 제안합니다.
    - [오류 ① 완벽 해결]: 과거(예: 2010년)에 30세로 입사했으나 당해연도(year) 및 사후관리 대상 연도(year-1, year-2)에
      이미 만 34세를 초과하고 4년(3년) 유예기간도 모두 만료된 근로자는 절대 '취업시 청년(4년)'으로 분류하지 않고
      '해당없음(일반)'으로 분류합니다.
    """
    emp_type = yrec.get("고용유형") or R.EMP_REGULAR
    c_age = contract_age(person)
    if c_age is not None and c_age >= R.SENIOR_AGE:
        return R.YOUTH_SENIOR
    if emp_type not in R.EMP_NOT_YOUTH_REGULAR:
        # 당해연도(year)에 최소 1개월이라도 청년등 요건을 충족하거나,
        # 사후관리 코호트 연도(year-1, year-2)에 청년등 요건을 충족했던 경우에만 '취업시 청년(4년)' 제안
        if any(is_youth_month(person, year, m, corp_size) for m in range(1, 13)):
            return R.YOUTH_YOUNG
        if any(
            is_youth_month(person, cy, m, corp_size)
            for cy in (year - 1, year - 2)
            for m in range(1, 13)
        ):
            return R.YOUTH_YOUNG
    return R.YOUTH_NONE


def _pick(yrec: dict, field: str, suggestion: str) -> str:
    user_set = yrec.get("_user_set") or []
    cur = yrec.get(field)
    if field in user_set and cur:
        return cur
    return suggestion


def detect_last_paid_month(people: dict, year: int) -> int:
    """
    해당 연도 원천징수부에서 급여가 지급된 마지막 월(1~12)을 감지합니다.
    - 예: 9월 가결산 원천징수부를 업로드해 1~9월까지만 급여가 있고 10~12월 급여가 전원 0원이면 9를 반환.
    - 급여 데이터가 아예 없으면(수기 입력 등) 12를 반환.
    """
    max_m = 0
    has_any_pay_record = False
    for p in (people or {}).values():
        pay = (p.get("월급여") or {}).get(str(year)) or {}
        if pay:
            has_any_pay_record = True
        for m in range(1, 13):
            v = pay.get(str(m), pay.get(m, 0))
            try:
                if float(v or 0) > 0:
                    if m > max_m:
                        max_m = m
            except (TypeError, ValueError):
                pass
    if not has_any_pay_record or max_m == 0:
        return 12
    return max_m


# ══════════════════════════════════════════════════════════════════
# 4. 개인별 · 월별 상시근로자 및 4대 우측 블록(당해공제·2차사후·3차사후·인별절사) 계산
# ══════════════════════════════════════════════════════════════════
def compute_row(person: dict, yrec: dict, year: int, ctx: dict) -> dict:
    """
    사원 1인의 특정 과세연도(year)에 대하여:
    - 1월~12월 매월 말 상시근로자 가중치(1 / 0.75 / 0.5 / 0)
    - [기중 가결산 시뮬레이션 지원]: `ctx["assume_year_end"] == True`(1번안 기본)이고
      당해연도 원천징수부가 `last_paid_month`(예: 9월)까지만 있는 경우,
      퇴사하지 않고 `last_paid_month`에 재직 중인 사원의 미도래 월(`last_paid_month+1 ~ 12월`)을
      연말까지 재직 가정으로 자동 산입하고 `projected_months`(노란색 표시)에 기록합니다.
    - 첨부 엑셀 디자인(`image_176778.png`)의 우측 4대 요약 블록:
      * Block 1 (`b1_yth`, `b1_gen`, `b1_reg`): 통합고용세액공제 (당해 세액공제용)
      * Block 2 (`b2_yth`, `b2_gen`, `b2_reg`): 2차년도 사후관리 (직전연도 `year-1` 기공제분 사후관리용 — 연령경과 간주 특례 반영)
      * Block 3 (`b3_yth`, `b3_gen`, `b3_reg`): 3차년도 사후관리 (전전연도 `year-2` 기공제분 사후관리용 — 연령경과 간주 특례 반영)
      * Block 4 (`b4_yth`, `b4_gen`, `b4_reg`): 인별절사(25.02·26.02 시행령) (개인별 `근무월수 ÷ 사업연도월수`를 소수점 둘째자리 절사)
    """
    corp_size = ctx.get("corp_size") or "중소기업"
    months_in_year = max(1, min(12, int(ctx.get("months_in_year") or 12)))
    assume_year_end = bool(ctx.get("assume_year_end", True))
    last_paid_month = int(ctx.get("last_paid_month") or 12)
    act_months = set(active_months(year, months_in_year))

    emp_type = yrec.get("고용유형") or R.EMP_REGULAR
    sug_excl = suggest_exclusion(person, yrec, year)
    excl = _pick(yrec, "제외사유", sug_excl)
    excl_locked = emp_type in R.EMP_AUTO_EXCLUDE

    # 상시 O/X 판정 (참고: 출산전후휴가 대체인력 상수가 과거 세션에 남아있더라도 기본 상시근로자에서는 제외하지 않음)
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
    pay_by_month = (person.get("월급여") or {}).get(str(year)) or {}
    has_any_pay_data = len(pay_by_month) > 0
    weight = R.EMP_WEIGHT.get(emp_type, 1.0)
    m_ovr = yrec.get("월_override") or {}

    # 이 사원이 마지막 급여월(last_paid_month)에 급여를 받고 재직 중인지 확인
    paid_in_last_m = False
    if last_paid_month < 12 and has_any_pay_data:
        raw_lp = pay_by_month.get(str(last_paid_month), pay_by_month.get(last_paid_month, 0))
        try:
            paid_in_last_m = float(raw_lp or 0) > 0
        except (TypeError, ValueError):
            paid_in_last_m = False

    months: list[float | None] = []
    youth_flags_b1: list[bool] = []  # 당해 세액공제용 청년 인정 마스크
    youth_flags_b2: list[bool] = []  # 2차년도 사후관리용(year-1 코호트) 청년 인정 마스크
    youth_flags_b3: list[bool] = []  # 3차년도 사후관리용(year-2 코호트) 청년 인정 마스크
    no_pay_months: list[int] = []
    projected_months: list[int] = []

    for m in range(1, 13):
        if m not in act_months:
            months.append(None)
            youth_flags_b1.append(False)
            youth_flags_b2.append(False)
            youth_flags_b3.append(False)
            continue

        if is_regular == "X":
            val = 0.0
        elif str(m) in m_ovr:
            val = float(m_ovr[str(m)])
        else:
            emp_ok = employed_at_month_end(hire, retire, year, m)
            raw_pay = pay_by_month.get(str(m), pay_by_month.get(m, None))
            paid = (float(raw_pay or 0) > 0) if raw_pay is not None else None

            if not emp_ok:
                val = 0.0
            else:
                if has_any_pay_data:
                    if paid:
                        val = weight
                    elif last_paid_month < 12 and m > last_paid_month:
                        # 미도래 월(예: 9월 가결산 시 10·11·12월) 처리
                        if assume_year_end and (paid_in_last_m or (hire and hire <= month_end(year, m))):
                            val = weight
                            projected_months.append(m)
                        else:
                            val = 0.0
                    else:
                        # 입·퇴사 기간 내인데 도래한 월에 급여가 0원인 달(무급휴직·육아휴직 등)
                        val = 0.0
                        no_pay_months.append(m)
                else:
                    val = weight

        months.append(val)

        if val and val > 0:
            # 1) 당해 세액공제용 청년 판정
            if youth == R.YOUTH_NONE:
                yf1 = False
            elif youth == R.YOUTH_YOUNG:
                birth_ok = parse_date(person.get("생년월일")) is not None and contract_date(person) is not None
                yf1 = is_youth_month(person, year, m, corp_size) if birth_ok else True
            else:
                yf1 = True

            # 2) 2차년도 사후관리용 (year-1 코호트 기준 연령경과 간주 특례)
            yf2 = is_youth_month_for_cohort(person, year, m, year - 1, corp_size, youth)
            # 3) 3차년도 사후관리용 (year-2 코호트 기준 연령경과 간주 특례)
            yf3 = is_youth_month_for_cohort(person, year, m, year - 2, corp_size, youth)
        else:
            yf1 = yf2 = yf3 = False

        youth_flags_b1.append(yf1)
        youth_flags_b2.append(yf2)
        youth_flags_b3.append(yf3)

    active_vals = [v for v in months if v is not None]
    row_sum = round(sum(active_vals), 4)
    yth_sum_b1 = round(sum(v for v, f in zip(months, youth_flags_b1) if v is not None and f), 4)
    yth_sum_b2 = round(sum(v for v, f in zip(months, youth_flags_b2) if v is not None and f), 4)
    yth_sum_b3 = round(sum(v for v, f in zip(months, youth_flags_b3) if v is not None and f), 4)

    gen_sum_b1 = round(max(0.0, row_sum - yth_sum_b1), 4)
    gen_sum_b2 = round(max(0.0, row_sum - yth_sum_b2), 4)
    gen_sum_b3 = round(max(0.0, row_sum - yth_sum_b3), 4)

    # 개인별 기여도 (소수점 둘째자리 반올림 표기용 vs 인별 절사 비교용)
    b1_reg_indiv = round(row_sum / months_in_year, 2)
    b1_yth_indiv = round(yth_sum_b1 / months_in_year, 2)
    b1_gen_indiv = round(gen_sum_b1 / months_in_year, 2)

    b2_reg_indiv = round(row_sum / months_in_year, 2)
    b2_yth_indiv = round(yth_sum_b2 / months_in_year, 2)
    b2_gen_indiv = round(gen_sum_b2 / months_in_year, 2)

    b3_reg_indiv = round(row_sum / months_in_year, 2)
    b3_yth_indiv = round(yth_sum_b3 / months_in_year, 2)
    b3_gen_indiv = round(gen_sum_b3 / months_in_year, 2)

    # 6. 인별절사(25.02·26.02개정) 비교용: 개인별 (근무월수 / 사업연도월수)를 각각 소수점 둘째자리 절사
    b4_reg_trunc = trunc2(Fraction(int(round(row_sum * 100)), months_in_year * 100))
    b4_yth_trunc = trunc2(Fraction(int(round(yth_sum_b1 * 100)), months_in_year * 100))
    b4_gen_trunc = round(max(0.0, b4_reg_trunc - b4_yth_trunc), 2)

    return {
        "고용유형": emp_type,
        "제외사유": excl,
        "excl_locked": excl_locked,
        "청년등": youth,
        "youth_options": opts,
        "상시": is_regular,
        "상시_auto": auto_regular,
        "취업연령": contract_age(person),
        "months": months,
        "youth_flags": youth_flags_b1,
        "youth_flags_b2": youth_flags_b2,
        "youth_flags_b3": youth_flags_b3,
        "no_pay_months": no_pay_months,
        "projected_months": projected_months,
        "row_sum": row_sum,
        "youth_sum": yth_sum_b1,
        "youth_sum_b2": yth_sum_b2,
        "youth_sum_b3": yth_sum_b3,
        "gen_sum_b1": gen_sum_b1,
        "gen_sum_b2": gen_sum_b2,
        "gen_sum_b3": gen_sum_b3,
        # 4대 우측 블록 개인별 표시값
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


def year_totals(computed_rows: list[dict], months_in_year: int) -> dict:
    """
    과세연도 전체 상시근로자 수 및 4대 우측 블록 집계:
    - 법정 원칙: `(전체 근로자 연인원 합계 ÷ 사업연도 개월수)`에서 소수점 셋째 자리 절사 (`trunc2`).
    - 청년등 외 상시근로자 수 = `상시근로자 수(절사 후) - 청년등 상시근로자 수(절사 후)`.
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
        r_sum = round(sum((r["months"][idx] or 0.0) for r in computed_rows), 4)
        y_sum = round(
            sum((r["months"][idx] or 0.0) for r in computed_rows if r["youth_flags"][idx]),
            4,
        )
        m_reg.append(r_sum)
        m_yth.append(y_sum)
        m_non.append(round(r_sum - y_sum, 4))

    reg_total = round(sum(v for v in m_reg if v is not None), 4)
    yth_total_b1 = round(sum(v for v in m_yth if v is not None), 4)
    non_total_b1 = round(reg_total - yth_total_b1, 4)

    yth_total_b2 = round(sum(r.get("youth_sum_b2", 0.0) for r in computed_rows), 4)
    yth_total_b3 = round(sum(r.get("youth_sum_b3", 0.0) for r in computed_rows), 4)

    # Block 1: 당해 통합고용세액공제용 (연인원 합계 ÷ 개월수 절사)
    b1_reg = trunc2(Fraction(int(round(reg_total * 100)), n * 100))
    b1_yth = trunc2(Fraction(int(round(yth_total_b1 * 100)), n * 100))
    b1_gen = round(max(0.0, b1_reg - b1_yth), 2)

    # Block 2: 2차년도 사후관리용 (직전연도 기공제분 사후관리 — 연령경과 간주 특례 반영)
    b2_reg = b1_reg
    b2_yth = trunc2(Fraction(int(round(yth_total_b2 * 100)), n * 100))
    b2_gen = round(max(0.0, b2_reg - b2_yth), 2)

    # Block 3: 3차년도 사후관리용 (전전연도 기공제분 사후관리 — 연령경과 간주 특례 반영)
    b3_reg = b1_reg
    b3_yth = trunc2(Fraction(int(round(yth_total_b3 * 100)), n * 100))
    b3_gen = round(max(0.0, b3_reg - b3_yth), 2)

    # Block 4: 인별절사(25.02·26.02개정) 비교용 (개인별 1/n 절사값들의 합계)
    b4_reg = round(sum(r.get("b4_reg", 0.0) for r in computed_rows), 2)
    b4_yth = round(sum(r.get("b4_yth", 0.0) for r in computed_rows), 2)
    b4_gen = round(max(0.0, b4_reg - b4_yth), 2)

    return {
        "months_in_year": n,
        "월별_상시": m_reg,
        "월별_청년등": m_yth,
        "월별_청년외": m_non,
        "상시_합계": reg_total,
        "청년등_합계": yth_total_b1,
        "청년외_합계": non_total_b1,
        "상시_평균": b1_reg,
        "청년등_평균": b1_yth,
        "청년외_평균": b1_gen,
        # 4대 우측 블록 총계
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
    """단시간근로자(0.5/0.75)를 제외한 통상근로자만의 상시근로자 수 (단시간 가중치 0.75 요건 검증용)."""
    n = max(1, min(12, int(months_in_year or 12)))
    total = 0.0
    for r, et in zip(computed_rows, emp_types):
        if et in (R.EMP_PT_050, R.EMP_PT_075):
            continue
        total += sum(v for v in r["months"] if v is not None)
    return trunc2(Fraction(int(round(total * 100)), n * 100))


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
    """
    [법정 고용증가 인원 한도(Cap) 계산 — 조특령 제26조의8 제3항]
    - 4개 인자 호출 `(cur_reg, cur_yth, prev_reg, prev_yth)` 및
      6개 인자 호출 `(cur_reg, cur_yth, cur_non_yth, prev_reg, prev_yth, prev_non_yth)` 모두 완벽 호환!
    - 전체 상시근로자 증가인원 = max(0, 당해 상시 - 직전 상시)
    - 청년등 증가인원 = min(전체 상시근로자 증가인원, max(0, 당해 청년등 - 직전 청년등))
    - 청년등 외 증가인원 = 전체 상시근로자 증가인원 - 청년등 증가인원
    """
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

    total_inc = round(max(0.0, float(cur_regular or 0.0) - prev_regular), 2)
    raw_youth_inc = round(max(0.0, float(cur_youth or 0.0) - prev_y), 2)
    raw_non_youth_inc = round(max(0.0, cur_non_y - prev_non_y), 2)

    youth_inc = round(min(total_inc, raw_youth_inc), 2)
    non_youth_inc = round(max(0.0, total_inc - youth_inc), 2)

    return {
        "전체_증가": total_inc,
        "청년등_증가": youth_inc,
        "청년등외_증가": non_youth_inc,
        "청년등_한도적용전": raw_youth_inc,
        "청년등외_한도적용전": raw_non_youth_inc,
        "total_inc": total_inc,
        "youth_inc": youth_inc,
        "non_youth_inc": non_youth_inc,
        "raw_youth_inc": raw_youth_inc,
    }


def get_unit_rates(corp_size: str, is_capital: bool, scheme: str = "legacy", retention_year: int = 1) -> dict[str, int]:
    """
    기업규모·소재지·법령체계(구법 legacy vs 2026 신법 new_2026)·유지연차(1~3년차)에 따른 공제단가(만원) 반환.
    """
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
    """
    [2026년 이후 신법: 조특법 제29조의8 제1항 제3호 최소고용증가인원 차감 금액 계산 (오류 ⑨ 완벽 해결)]
    - 출처: `통합고용세액공제3-2. 계산구조.pdf` p.3 [제3호: 최소고용증가인원수에 대한 차감 금액]
    - 최소고용증가인원수: 중소기업 0명, 중견기업 5명, 대기업(일반기업) 10명.
    - 만약 전체 증가인원(`total_inc`)이 최소고용증가인원수 이하이면 공제 요건 미충족(공제액 0원).
    - 전체 증가인원이 최소고용증가인원수를 초과하는 경우:
      * 가. 중견기업 (hurdle = 5명):
        1) 청년등외 증가수 >= 5명:
           - 직전(1년차, A): 5명 × 300만원 = 1,500만원 차감
           - 전전(2년차, B) 또는 전전전(3년차, C): 5명 × 500만원 = 2,500만원 차감
        2) 청년등외 증가수 < 5명:
           - 직전(1년차, A): (청년등외 증가수 × 300만원) + (5 - 청년등외 증가수) × 500만원 차감
           - 전전(2년차, B) 또는 전전전(3년차, C): (청년등외 증가수 × 500만원) + (5 - 청년등외 증가수) × 900만원 차감
      * 나. 대기업/일반기업 (hurdle = 10명):
        1) 청년등외 증가수 >= 10명: 차감액 0원! (청년등외 증가인원만으로 최소고용증가인원 10명을 채웠으므로 청년 공제액 차감 없음)
        2) 청년등외 증가수 < 10명:
           - 직전(1년차, A): (10 - 청년등외 증가수) × 300만원 차감
           - 전전(2년차, B) 또는 전전전(3년차, C): (10 - 청년등외 증가수) × 500만원 차감
    """
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
        # 대기업 / 일반기업 (hurdle = 10명)
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
    """하위 호환 래퍼: `calc_minimum_hurdle_deduction_2026` 결과를 반환합니다."""
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
    """
    [2026~2028년 귀속 신법: A(직전 대비 1년차) + B(전전 대비 2년차 유지) + C(전전전 대비 3년차 유지) 통합 계산 (오류 ⑥·⑨ 해결)]
    - 근거: 조세특례제한법 제29조의8 제1항 제1호 + 제2호 - 제3호 (`통합고용세액공제3-2. 계산구조.pdf` p.2~3)
    - 비교 대상 과세연도: 2024.12.31. 이전 개시 과세연도는 비교 대상에서 제외(`valid_comparison_years_for_new_credit`).
      * 2026년 귀속: A(2025 대비)만 산출
      * 2027년 귀속: A(2026 대비) + B(2025 대비 유지분) 산출
      * 2028년 귀속: A(2027 대비) + B(2026 대비 유지분) + C(2025 대비 유지분) 산출
    """
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

    # ── (A) 직전 과세연도(T-1) 대비 증가분 (1년차 단가) ──
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

    # ── (B) 전전 과세연도(T-2) 대비 유지분 (2년차 단가, 2027년 귀속부터 활성) ──
    rates_b = get_unit_rates(corp_size, is_capital, scheme="new_2026", retention_year=2)
    if comp.get("B") is not None and s_t2["has_data"]:
        min_reg_b = min(s_t["reg"], s_t1["reg"])
        min_yth_b = min(s_t["b2_yth"], s_t1["yth"])
        tot_b = round(max(0.0, min_reg_b - s_t2["reg"]), 2)
        yth_b = round(min(tot_b, max(0.0, min_yth_b - s_t2["yth"])), 2)
        gen_b = round(max(0.0, tot_b - yth_b), 2)
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

    # ── (C) 전전전 과세연도(T-3) 대비 유지분 (3년차 단가, 2028년 귀속부터 활성, 대기업 제외) ──
    rates_c = get_unit_rates(corp_size, is_capital, scheme="new_2026", retention_year=3)
    if comp.get("C") is not None and s_t3["has_data"] and (rates_c["청년등"] > 0 or rates_c["청년등외"] > 0):
        min_reg_c = min(s_t["reg"], s_t1["reg"], s_t2["reg"])
        min_yth_c = min(s_t["b3_yth"], s_t1["b2_yth"], s_t2["yth"])
        tot_c = round(max(0.0, min_reg_c - s_t3["reg"]), 2)
        yth_c = round(min(tot_c, max(0.0, min_yth_c - s_t3["yth"])), 2)
        gen_c = round(max(0.0, tot_c - yth_c), 2)
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
) -> dict[str, Any]:
    """
    [2023~2025년 귀속 공제분의 1차·2차 사후관리(2·3차년도 연속공제 및 추가납부세액) 정밀 산출]
    - 근거: 조세특례제한법 제29조의8 제1항·제3항, 같은 법 시행령 제26조의8 제4항·제5항,
            첨부 PDF 「2023년~2025년 세액공제, 추가납부.pdf」 및 「2024년 통합고용2.pdf」
    - [오류 ③·④ 해결]:
      1) `prior_clawback_paid_won`: 2차 사후관리(3차년도, `elapsed == 2`)에서 추가납부세액 산출 시
         1차 사후관리(2차년도)에서 이미 납부(또는 이월차감)한 추징세액을 차감하여 이중 추징 방지!
      2) `init_credit_claimed_won`: 해당 코호트에서 누적 공제받은 세액 한도(Cap)를 초과하여 추징되지 않도록 상한 적용!
      3) `unclaimed_carryforward_won`: 최저한세 등으로 실제 공제받지 못한 이월공제액(조특법 제144조)이 있는 경우
         현금 납부 대신 이월공제액을 우선 차감(소멸)하고 잔액만 실제 추가납부세액으로 산출!
    """
    elapsed = int(eval_year) - int(cohort_year)
    rates = get_unit_rates(corp_size, is_capital, scheme="legacy")
    yth_rate = rates["청년등"]       # 만원
    gen_rate = rates["청년등외"]     # 만원
    diff_rate = max(0, yth_rate - gen_rate)  # 대체 감소 시 차액 단가 (예: 중소 수도권 1,450 - 850 = 600만원)

    is_large = corp_size in ("일반기업", "대기업")
    max_credit_years = 2 if is_large else 3
    can_receive_continued = (1 <= elapsed < max_credit_years) and (init_yth_inc + init_gen_inc > 0)

    # 사후관리 의무 기간: 중소·중견·대기업 모두 최초 공제 과세연도 종료 후 2년간 (elapsed in (1, 2))
    if elapsed not in (1, 2) or (init_yth_inc <= 0 and init_gen_inc <= 0):
        return {
            "cohort_year": cohort_year,
            "eval_year": eval_year,
            "elapsed_year": elapsed,
            "active": False,
            "case_code": "해당없음",
            "case_title": f"{cohort_year}년 귀속분 공제이력 없음 (사후관리 대상 아님)",
            "continued_credit_won": 0,
            "clawback_gross_won": 0,
            "prior_clawback_deducted_won": 0,
            "carryforward_offset_won": 0,
            "clawback_net_payable_won": 0,
            "retained_yth_inc": 0.0,
            "retained_gen_inc": 0.0,
            "reg_decrease": 0.0,
            "yth_decrease": 0.0,
            "formula_note": "해당 과세연도에 공제받은 고용증가 인원이 없어 사후관리(연속공제·추가납부) 대상이 아닙니다.",
        }

    reg_diff = round(cur_pm_reg - init_reg, 2)
    yth_diff = round(cur_pm_yth - init_yth, 2)
    reg_dec = round(max(0.0, init_reg - cur_pm_reg), 2)
    yth_dec = round(max(0.0, init_yth - cur_pm_yth), 2)

    # 3차년도(elapsed==2) 연속공제 및 추징배수 판정 시 직전 사후관리(2차년도) 현황 고려
    if elapsed == 1:
        prior_years_claimed_count = 1
    else:
        if prev_pm_reg is not None and prev_pm_reg < init_reg:
            prior_years_claimed_count = 1
        else:
            prior_years_claimed_count = 2 if not is_large else 1

    # ── 케이스 1: 전체 상시근로자 유지/증가 & 청년등 상시근로자도 유지/증가 (추징 0, 전액 연속공제) ──
    if reg_diff >= 0 and yth_diff >= 0:
        case_code = "유지/증가"
        case_title = "전체 상시 및 청년등 인원 모두 유지 (전액 연속공제 · 추징 없음)"
        ret_yth = round(init_yth_inc, 2)
        ret_gen = round(init_gen_inc, 2)
        if elapsed == 2 and prev_pm_reg is not None:
            if prev_pm_reg < init_reg:
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

    # ── 케이스 2: 전체 상시근로자 수는 유지(cur_pm_reg >= init_reg)되었으나, 청년등 수가 감소(cur_pm_yth < init_yth) ──
    elif reg_diff >= 0 and yth_diff < 0:
        case_code = "Case 1 (청년→일반 대체감소)"
        case_title = "전체 상시근로자 유지 · 청년등만 감소 (부분 연속공제 + 단가차액 추가납부)"
        capped_yth_dec = round(min(init_yth_inc, yth_dec), 2)
        ret_yth = round(max(0.0, init_yth_inc - capped_yth_dec), 2)
        ret_gen = round(init_gen_inc + capped_yth_dec, 2)

        if elapsed == 2 and prev_pm_reg is not None and prev_pm_reg < init_reg:
            ret_yth = 0.0
            ret_gen = 0.0

        cont_man = (ret_yth * yth_rate + ret_gen * gen_rate) if can_receive_continued else 0.0
        raw_claw_man = capped_yth_dec * diff_rate * prior_years_claimed_count
        formula_note = (
            f"[{cohort_year}년분 {elapsed+1}차년도 · Case 1] 전체 상시 유지({cur_pm_reg:.2f} ≥ {init_reg:.2f}), "
            f"청년등 {capped_yth_dec:.2f}명 감소(일반 대체) → "
            f"추징(차액): {capped_yth_dec:.2f}명 × ({yth_rate:,}-{gen_rate:,})만원 × {prior_years_claimed_count}년 = {raw_claw_man:,.1f}만원 / "
            f"연속공제: 유지청년 {ret_yth:.2f}명×{yth_rate:,}만 + 대체포함일반 {ret_gen:.2f}명×{gen_rate:,}만 = {cont_man:,.1f}만원"
        )

    # ── 케이스 3: 전체 상시근로자 수가 최초 공제연도보다 감소(cur_pm_reg < init_reg) ──
    else:
        ret_yth = 0.0
        ret_gen = 0.0
        cont_man = 0.0
        total_init_inc = round(init_yth_inc + init_gen_inc, 2)
        capped_reg_dec = round(min(total_init_inc, reg_dec), 2)

        # Case 2-1: 전체 상시 감소인원 <= 청년등 감소인원
        if reg_dec <= yth_dec + 1e-9:
            case_code = "Case 2-1 (전체 상시감소 ≤ 청년감소)"
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
                f"[{cohort_year}년분 {elapsed+1}차년도 · Case 2-1] 전체 상시 {capped_reg_dec:.2f}명 감소 ≤ 청년등 {yth_dec:.2f}명 감소 → "
                f"연속공제 중단(0원) / 추징: [청년이탈 {pure_yth_lost:.2f}명×{yth_rate:,}만 + "
                f"청년→일반대체 {sub_yth_to_gen:.2f}명×{diff_rate:,}만"
                + (f" + 일반이탈 {gen_also_lost:.2f}명×{gen_rate:,}만" if gen_also_lost > 0 else "")
                + f"] × {prior_years_claimed_count}년 = {raw_claw_man:,.1f}만원"
            )
        # Case 2-2: 전체 상시 감소인원 > 청년등 감소인원
        else:
            case_code = "Case 2-2 (전체 상시감소 > 청년감소)"
            case_title = "전체 상시근로자 감소 > 청년등 감소 (연속공제 중단 + 청년감소분·일반감소분 각각 추징)"
            yth_lost = round(min(init_yth_inc, yth_dec), 2)
            gen_lost_raw = round(max(0.0, capped_reg_dec - yth_lost), 2)
            gen_lost = round(min(init_gen_inc, gen_lost_raw), 2)
            extra_yth_lost = round(max(0.0, gen_lost_raw - gen_lost), 2)
            total_yth_lost = round(min(init_yth_inc, yth_lost + extra_yth_lost), 2)

            raw_claw_man = ((total_yth_lost * yth_rate) + (gen_lost * gen_rate)) * prior_years_claimed_count
            formula_note = (
                f"[{cohort_year}년분 {elapsed+1}차년도 · Case 2-2] 전체 상시 {capped_reg_dec:.2f}명 감소 > 청년등 {yth_dec:.2f}명 감소 → "
                f"연속공제 중단(0원) / 추징: [청년감소 {total_yth_lost:.2f}명×{yth_rate:,}만 + "
                f"일반감소 {gen_lost:.2f}명×{gen_rate:,}만] × {prior_years_claimed_count}년 = {raw_claw_man:,.1f}만원"
            )

    continued_credit_won = int(round(cont_man * 10_000))
    raw_clawback_won = int(round(raw_claw_man * 10_000))

    # [오류 ④ 해결] 누적 기공제세액 한도(init_credit_claimed_won) 적용: 공제받은 총 세액을 초과하여 추징할 수 없음
    claimed_cap = max(0, int(init_credit_claimed_won or 0))
    if claimed_cap > 0:
        capped_cumulative_claw_won = min(raw_clawback_won, claimed_cap)
    else:
        capped_cumulative_claw_won = raw_clawback_won

    # [오류 ③ 해결] 2차 사후관리(elapsed == 2) 시 1차 사후관리에서 이미 납부(또는 차감)한 추징세액 차감 (이중추징 방지)
    prior_paid = max(0, int(prior_clawback_paid_won or 0)) if elapsed == 2 else 0
    prior_deducted_won = min(capped_cumulative_claw_won, prior_paid)
    clawback_gross_won = max(0, capped_cumulative_claw_won - prior_deducted_won)
    if prior_deducted_won > 0:
        formula_note += f" (1차 사후관리 기추징액 {prior_deducted_won:,}원 차감 반영)"

    # 이월공제 미공제액(조특법 제144조) 우선 차감 특례
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
) -> dict[str, Any]:
    """
    [선택된 귀속사업연도(2024~2028)의 통합고용세액공제 종합 계산 패키지]
    1. 당해연도(T) 신규 고용증가분 세액공제:
       - 2024·2025년 귀속: 구법 단가(1년차)
       - 2026~2028년 귀속: 신법 A(직전 대비 1년차) + B(전전 대비 2년차) + C(전전전 대비 3년차) 점증형 공제
         (제1호 청년등 + 제2호 청년등외 - 제3호 최소고용증가인원 차감액 완벽 반영) 및 구법 시뮬레이션 병행
    2. 직전연도(T-1) 귀속분의 1차 사후관리 (2차년도 연속공제 또는 추가납부세액):
       - 2024·2025년 기공제분(구법 코호트)에 대해 구 조특령 제26조의8 제5항 연령경과 간주 특례(`b2_yth`) 적용
       - [오류 ② 해결]: T-2년(예: 2024년) 자료가 없을 때 T-1년 전체 인원이 증가인원으로 부풀려지지 않도록 방지
    3. 전전연도(T-2) 귀속분의 2차 사후관리 (3차년도 연속공제 또는 추가납부세액):
       - 2023·2024년 기공제분(구법 코호트)에 대해 구 조특령 제26조의8 제5항 연령경과 간주 특례(`b3_yth`) 적용
       - [오류 ③·④ 해결]: 1차 사후관리 기납부 추징세액 차감 및 누적 기공제세액 한도(Cap) 자동 반영
    4. 정규직 전환자(2024년 귀속까지 일몰) · 육아휴직 복귀자(2026년 귀속까지 적용) 추가공제 및 2년 내 퇴사 추징:
       - [오류 ⑧ 해결]: 출산전후휴가자 대체인력 수(`maternity_replacement_count`)를 비감소 요건 판정에 반영(조특령 제26조의8 제7항)
    5. 이월공제 미공제액 차감 후 최종 납부할 추가납부세액 및 농어촌특별세(실공제세액의 20%, 오류 ⑪ 해결) 산출
    """
    t = int(tax_year)
    pf = prior_filings or {}
    add_in = additional_inputs or {}

    def _s(y: int) -> dict[str, Any]:
        d = summaries.get(y) or {}
        reg = float(d.get("상시_평균", d.get("regular", d.get("b1_reg", 0.0))) or 0.0)
        yth = float(d.get("청년등_평균", d.get("youth", d.get("b1_yth", 0.0))) or 0.0)
        non_y = float(d.get("청년외_평균", d.get("non_youth", d.get("b1_gen", max(0.0, reg - yth)))) or 0.0)
        b2_r = float(d.get("b2_reg", reg) or 0.0)
        b2_y = float(d.get("b2_yth", yth) or 0.0)
        b3_r = float(d.get("b3_reg", reg) or 0.0)
        b3_y = float(d.get("b3_yth", yth) or 0.0)
        b4_r = float(d.get("b4_reg", reg) or 0.0)
        b4_y = float(d.get("b4_yth", yth) or 0.0)
        has_data = bool(d.get("has_data", reg > 0 or yth > 0))
        return {
            "regular": reg,
            "youth": yth,
            "non_youth": non_y,
            "b2_reg": b2_r,
            "b2_yth": b2_y,
            "b3_reg": b3_r,
            "b3_yth": b3_y,
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

    # ── 2) 직전연도(T-1) 귀속분의 1차 사후관리 (구법 코호트인 2023~2025년 귀속분에 대해 작동) ──
    pf_y1 = pf.get(t - 1) or pf.get(str(t - 1)) or {}
    # [오류 ② 해결]: T-2년(예: 2024년) 데이터가 실제로 존재하는 경우에만 prev_s - prev2_s로 자동 증가분을 계산
    has_t2_data = bool(prev2_s["has_data"] or pf_y1.get("has_t2_data"))
    if has_t2_data:
        auto_y1_inc = calc_increase_with_cap(prev_s["regular"], prev_s["youth"], prev2_s["regular"], prev2_s["youth"])
    else:
        auto_y1_inc = {"total_inc": 0.0, "youth_inc": 0.0, "non_youth_inc": 0.0}

    y1_init_reg = float(pf_y1.get("init_reg", prev_s["regular"]) or 0.0)
    y1_init_yth = float(pf_y1.get("init_yth", prev_s["youth"]) or 0.0)
    y1_init_yth_inc = float(
        pf_y1["init_yth_inc"] if pf_y1.get("init_yth_inc") is not None else auto_y1_inc["youth_inc"]
    )
    y1_init_gen_inc = float(
        pf_y1["init_gen_inc"] if pf_y1.get("init_gen_inc") is not None else auto_y1_inc["non_youth_inc"]
    )
    y1_default_claimed_won = int(
        round((y1_init_yth_inc * rates_legacy["청년등"] + y1_init_gen_inc * rates_legacy["청년등외"]) * 10_000)
    )
    y1_claimed_won = int(
        pf_y1["claimed_won"] if pf_y1.get("claimed_won") is not None and int(pf_y1.get("claimed_won") or 0) > 0 else y1_default_claimed_won
    )
    y1_cf_won = int(pf_y1.get("carryforward_won", 0) or 0)

    if (t - 1) <= 2025:
        pm_y1 = calc_legacy_post_management(
            cohort_year=t - 1,
            eval_year=t,
            corp_size=corp_size,
            is_capital=is_capital,
            init_reg=y1_init_reg,
            init_yth=y1_init_yth,
            init_yth_inc=y1_init_yth_inc,
            init_gen_inc=y1_init_gen_inc,
            cur_pm_reg=cur_s["b2_reg"],
            cur_pm_yth=cur_s["b2_yth"],
            init_credit_claimed_won=y1_claimed_won,
            unclaimed_carryforward_won=y1_cf_won,
        )
    else:
        # 2026년 이후 귀속분은 신법 점증형(B·C)으로 통합되어 별도 구법 사후관리 추징이 없음
        pm_y1 = {
            "cohort_year": t - 1,
            "eval_year": t,
            "elapsed_year": 1,
            "active": False,
            "case_code": "신법 B(전전 대비) 통합",
            "case_title": f"{t-1}년 귀속분은 2026 신법(점증형 B)으로 통합 계산됨 (추징 규정 폐지)",
            "continued_credit_won": 0,
            "clawback_gross_won": 0,
            "prior_clawback_deducted_won": 0,
            "carryforward_offset_won": 0,
            "clawback_net_payable_won": 0,
            "retained_yth_inc": abc_res["tiers"]["B"]["youth_inc"],
            "retained_gen_inc": abc_res["tiers"]["B"]["non_youth_inc"],
            "reg_decrease": 0.0,
            "yth_decrease": 0.0,
            "formula_note": f"{t-1}년 귀속분(2026년 이후 개시)은 구법 사후관리 추징 대상이 아니며, 신법 2년차(B) 유지분 공제로 반영됩니다.",
        }

    # ── 3) 전전연도(T-2) 귀속분의 2차 사후관리 (구법 코호트인 2023~2025년 귀속분에 대해 작동) ──
    pf_y2 = pf.get(t - 2) or pf.get(str(t - 2)) or {}
    y2_init_reg = float(pf_y2.get("init_reg", prev2_s["regular"]) or 0.0)
    y2_init_yth = float(pf_y2.get("init_yth", prev2_s["youth"]) or 0.0)
    y2_init_yth_inc = float(pf_y2.get("init_yth_inc", 0.0) or 0.0)
    y2_init_gen_inc = float(pf_y2.get("init_gen_inc", 0.0) or 0.0)

    # 2차 사후관리의 기공제세액 한도 기본값: 1차년도 + 2차년도 누적 공제받은 세액
    y2_1yr_credit_won = int(
        round((y2_init_yth_inc * rates_legacy["청년등"] + y2_init_gen_inc * rates_legacy["청년등외"]) * 10_000)
    )
    y2_prior_years_cnt = 1 if (prev_s["b2_reg"] < y2_init_reg and prev_s["has_data"]) else (1 if corp_size in ("일반기업", "대기업") else 2)
    y2_default_claimed_won = y2_1yr_credit_won * y2_prior_years_cnt
    y2_claimed_won = int(
        pf_y2["claimed_won"] if pf_y2.get("claimed_won") is not None and int(pf_y2.get("claimed_won") or 0) > 0 else y2_default_claimed_won
    )
    y2_cf_won = int(pf_y2.get("carryforward_won", 0) or 0)
    y2_prior_clawback_paid_won = int(pf_y2.get("prior_clawback_paid_won", 0) or 0)

    if (t - 2) <= 2025:
        pm_y2 = calc_legacy_post_management(
            cohort_year=t - 2,
            eval_year=t,
            corp_size=corp_size,
            is_capital=is_capital,
            init_reg=y2_init_reg,
            init_yth=y2_init_yth,
            init_yth_inc=y2_init_yth_inc,
            init_gen_inc=y2_init_gen_inc,
            cur_pm_reg=cur_s["b3_reg"],
            cur_pm_yth=cur_s["b3_yth"],
            init_credit_claimed_won=y2_claimed_won,
            unclaimed_carryforward_won=y2_cf_won,
            prev_pm_reg=prev_s["b2_reg"] if prev_s["has_data"] else None,
            prev_pm_yth=prev_s["b2_yth"] if prev_s["has_data"] else None,
            prior_clawback_paid_won=y2_prior_clawback_paid_won,
        )
    else:
        pm_y2 = {
            "cohort_year": t - 2,
            "eval_year": t,
            "elapsed_year": 2,
            "active": False,
            "case_code": "신법 C(전전전 대비) 통합",
            "case_title": f"{t-2}년 귀속분은 2026 신법(점증형 C)으로 통합 계산됨 (추징 규정 폐지)",
            "continued_credit_won": 0,
            "clawback_gross_won": 0,
            "prior_clawback_deducted_won": 0,
            "carryforward_offset_won": 0,
            "clawback_net_payable_won": 0,
            "retained_yth_inc": abc_res["tiers"]["C"]["youth_inc"],
            "retained_gen_inc": abc_res["tiers"]["C"]["non_youth_inc"],
            "reg_decrease": 0.0,
            "yth_decrease": 0.0,
            "formula_note": f"{t-2}년 귀속분(2026년 이후 개시)은 구법 사후관리 추징 대상이 아니며, 신법 3년차(C) 유지분 공제로 반영됩니다.",
        }

    # ── 4) 정규직 전환자(~2024년 귀속) 및 육아휴직 복귀자(~2026년 귀속) 추가공제 (오류 ⑧ 해결) ──
    add_unit_man = R.ADDITIONAL_CREDIT_PER_PERSON.get(corp_size, 0)
    parental_ret_cnt = int(add_in.get("parental_return_count", 0) or 0) if t <= 2026 else 0
    reg_conv_cnt = int(add_in.get("regular_conversion_count", 0) or 0) if t <= 2024 else 0
    early_term_add_cnt = int(add_in.get("additional_clawback_count", 0) or 0)
    maternity_rep_cnt = float(add_in.get("maternity_replacement_count", 0.0) or 0.0)

    # 조특령 제26조의8 제7항: 대체인력을 채용한 출산전후휴가자가 있는 경우 비감소 요건 판정 시 보정 가능
    non_decrease_ok = (cur_s["regular"] + maternity_rep_cnt + 1e-9) >= prev_s["regular"]
    additional_credit_won = (
        int((parental_ret_cnt + reg_conv_cnt) * add_unit_man * 10_000) if non_decrease_ok else 0
    )
    additional_clawback_won = int(early_term_add_cnt * add_unit_man * 10_000)

    # ── 5) 총 공제세액 · 총 추가납부세액 · 농어촌특별세(20%, 오류 ⑪ 해결) 종합 집계 ──
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

    # [오류 ⑪ 해결] 농어촌특별세법 제5조 제1항 제1호:
    # 당해연도 최저한세 등으로 공제받지 못하고 이월되는 세액(current_unclaimed_carryforward_won)은
    # 실제 감면받은 세액이 아니므로 당해연도 농어촌특별세 과세표준에서 제외(실제 공제받는 세액의 20%만 부과)
    cur_unclaimed_cf_won = max(0, int(add_in.get("current_unclaimed_carryforward_won", 0) or 0))
    actual_deducted_credit_won = max(0, total_credit_gross_won - cur_unclaimed_cf_won)
    rural_special_tax_won = int(round(actual_deducted_credit_won * R.RURAL_SPECIAL_TAX_RATE))
    net_after_rural_tax_won = net_tax_benefit_won - rural_special_tax_won

    return {
        "tax_year": t,
        "corp_size": corp_size,
        "is_capital": is_capital,
        "active_scheme": active_scheme,
        "has_t2_data": has_t2_data,
        "auto_y1_inc": auto_y1_inc,
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
        "y1_claimed_won": y1_claimed_won,
        "y2_claimed_won": y2_claimed_won,
        "non_decrease_ok": non_decrease_ok,
        "maternity_rep_cnt": maternity_rep_cnt,
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
# 6. 법령 · 심판례 기반 오류 검토 (Review Dialog용)
# ══════════════════════════════════════════════════════════════════
def review(
    people: dict,
    year_recs: dict,
    years: list[int],
    ctx_by_year: dict,
    computed: dict,
    prev_filing: dict | None = None,
) -> list[tuple[str, str]]:
    """
    2단계 사원정보 화면의 [오류 검토] 버튼 클릭 시 실행되는 정밀 법령·심판례 검증 엔진.
    """
    items: list[tuple[str, str]] = []

    for y in years:
        c_map = computed.get(y) or {}
        ctx = ctx_by_year.get(y) or {}
        n_months = ctx.get("months_in_year", 12)
        rows = list(c_map.values())
        emp_types = [r.get("고용유형", R.EMP_REGULAR) for r in rows]

        if any(et == R.EMP_PT_075 for et in emp_types) and len(years) >= 2:
            prev_y = y - 1
            if prev_y in computed:
                cur_ft = regular_excluding_part_time(rows, emp_types, n_months)
                prev_rows = list(computed[prev_y].values())
                prev_ets = [r.get("고용유형", R.EMP_REGULAR) for r in prev_rows]
                prev_ft = regular_excluding_part_time(
                    prev_rows, prev_ets, (ctx_by_year.get(prev_y) or {}).get("months_in_year", 12)
                )
                if cur_ft < prev_ft:
                    items.append(
                        (
                            "오류",
                            f"[{y}년] 단시간(0.75 가중치) 적용 요건 미충족: 통상근로자 상시근로자 수가 "
                            f"직전연도({prev_ft:.2f}명)보다 감소({cur_ft:.2f}명)하여 0.75 대신 0.5를 적용해야 합니다.",
                        )
                    )

        for pid, c in c_map.items():
            p = people.get(pid) or {}
            nm = p.get("성명") or pid
            yrec = (year_recs.get(y) or {}).get(pid) or {}

            if c["상시"] == "O":
                if not parse_date(p.get("입사일")):
                    items.append(
                        (
                            "오류",
                            f"[{y}년 · {nm}] 입사일이 비어 있습니다. 매월 말 재직 판정 및 청년등 연령 계산을 위해 입사일을 입력하세요.",
                        )
                    )
                if c["청년등"] in (R.YOUTH_YOUNG, R.YOUTH_SENIOR) and not parse_date(p.get("생년월일")):
                    items.append(
                        (
                            "오류",
                            f"[{y}년 · {nm}] 생년월일이 비어 있어 '{c['청년등']}' 연령 요건을 검증할 수 없습니다.",
                        )
                    )

            if c["상시"] == "O" and c["청년등"] == R.YOUTH_YOUNG:
                c_age = contract_age(p)
                if c_age is not None and c_age > R.YOUTH_AGE_MAX and int(p.get("병역개월", 0) or 0) == 0:
                    if c_age <= R.YOUTH_AGE_MAX + 6:
                        items.append(
                            (
                                "확인",
                                f"[{y}년 · {nm}] 입사 시 만 나이가 {c_age}세로 34세를 초과합니다. "
                                f"병역이행기간(최대 72개월)이 있다면 '병역(월)' 칸에 입력하여 청년 요건 충족 여부를 확인하세요.",
                            )
                        )
                    else:
                        items.append(
                            (
                                "오류",
                                f"[{y}년 · {nm}] 입사 시 만 나이가 {c_age}세로 청년 연령(15~34세)을 초과합니다.",
                            )
                        )

            if c.get("no_pay_months"):
                m_str = ", ".join(f"{m}월" for m in c["no_pay_months"])
                items.append(
                    (
                        "확인",
                        f"[{y}년 · {nm}] 재직기간 중 급여가 없는 달({m_str})이 있어 상시근로자에서 자동 제외(0)되었습니다. "
                        f"육아휴직·무급휴직 등이 맞는지 확인하세요.",
                    )
                )

            if c.get("projected_months"):
                m_str = f"{min(c['projected_months'])}~{max(c['projected_months'])}월"
                items.append(
                    (
                        "확인",
                        f"[{y}년 · {nm}] 기중 가결산 자료로 감지되어 미도래 월({m_str})이 '연말까지 재직 가정(1)'으로 자동 채워졌습니다.",
                    )
                )

            if yrec.get("상시_override"):
                items.append(
                    (
                        "확인",
                        f"[{y}년 · {nm}] 상시 여부가 자동판정({c['상시_auto']})에서 '{c['상시']}'로 수동 변경되었습니다.",
                    )
                )

    if prev_filing and isinstance(prev_filing, dict):
        for y_str, pdata in prev_filing.items():
            try:
                yi = int(y_str)
            except (TypeError, ValueError):
                continue
            if yi in computed and isinstance(pdata, dict):
                tot = year_totals(list(computed[yi].values()), (ctx_by_year.get(yi) or {}).get("months_in_year", 12))
                prev_reg = pdata.get("상시")
                prev_yth = pdata.get("청년등")
                if prev_reg is not None and abs(float(prev_reg) - tot["상시_평균"]) >= 0.01:
                    items.append(
                        (
                            "확인",
                            f"[{yi}년 기신고 대조] 기신고 상시근로자 수({float(prev_reg):.2f}명)와 "
                            f"현재 계산된 상시근로자 수({tot['상시_평균']:.2f}명)가 다릅니다.",
                        )
                    )
                if prev_yth is not None and abs(float(prev_yth) - tot["청년등_평균"]) >= 0.01:
                    items.append(
                        (
                            "확인",
                            f"[{yi}년 기신고 대조] 기신고 청년등 상시근로자 수({float(prev_yth):.2f}명)와 "
                            f"현재 계산된 청년등 상시근로자 수({tot['청년등_평균']:.2f}명)가 다릅니다.",
                        )
                    )

    return items
