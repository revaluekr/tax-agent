# -*- coding: utf-8 -*-
"""
상시근로자 판정·연평균 인원(4대 블록 동시 산출)·공제세액 및 1·2차 사후관리(추징) 확정 계산 엔진

숫자는 이 파일에서만 만듭니다. AI는 서류에서 값을 읽어오는 역할만 하고 계산에는 관여하지 않습니다.
인원 합계는 Fraction(분수)으로 정확히 더한 뒤, 마지막에 한 번만 소수점 셋째 자리 이하를 버립니다.
동시에 2025.02 시행령 개정 이슈 비교를 위해 인별 소수점 셋째 자리 버림 합산치(Block 4)도 함께 계산합니다.
"""
from __future__ import annotations

from datetime import date, datetime
from calendar import monthrange
from fractions import Fraction
from decimal import Decimal, ROUND_DOWN
import re
from typing import Any

from . import rules as R


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
    for fmt in ("%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            pass
    digits = re.sub(r"[^0-9]", "", s)
    try:
        if len(digits) == 8:
            return date(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))
    except ValueError:
        return None
    return None


def fmt_date(d: date | None) -> str:
    return d.isoformat() if d else ""


def format_date_dot(val) -> str:
    d = parse_date(val)
    return d.strftime("%Y.%m.%d") if d else (str(val).strip() if val else "")


def add_years(d: date, n: int) -> date:
    try:
        return d.replace(year=d.year + n)
    except ValueError:
        return d.replace(year=d.year + n, day=28)


def full_age(birth: date | None, ref: date | None, military_months: int = 0) -> int | None:
    if not birth or not ref:
        return None
    m = max(0, min(int(military_months or 0), R.MILITARY_MAX_MONTHS))
    by, bm = birth.year, birth.month + m
    by += (bm - 1) // 12
    bm = (bm - 1) % 12 + 1
    bd = min(birth.day, monthrange(by, bm)[1])
    adj_birth = date(by, bm, bd)
    age = ref.year - adj_birth.year - ((ref.month, ref.day) < (adj_birth.month, adj_birth.day))
    return max(0, age)


def month_end(year: int, month: int) -> date:
    return date(year, month, monthrange(year, month)[1])


def trunc2(x: Fraction | float) -> float:
    d = Decimal(x.numerator) / Decimal(x.denominator) if isinstance(x, Fraction) else Decimal(str(x))
    return float(d.quantize(Decimal("0.01"), rounding=ROUND_DOWN))


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
    n = max(1, min(12, int(months_in_year or 12)))
    return list(range(13 - n, 13))


def default_months_for_year(year: int, founded: date | None) -> int:
    if founded and founded.year == year:
        return 12 - founded.month + 1
    if founded and founded.year > year:
        return 0
    return 12


def valid_comparison_years_for_new_credit(tax_year: int) -> dict[str, int | None]:
    ty = int(tax_year or R.DEFAULT_TAX_YEAR)
    if ty <= 2025:
        return {"A": ty - 1, "B": None, "C": None}
    a = ty - 1 if (ty - 1) >= 2025 else None
    b = ty - 2 if (ty - 2) >= 2025 else None
    c = ty - 3 if (ty - 3) >= 2025 else None
    return {"A": a, "B": b, "C": c}


def employed_at_month_end(hire: date | None, retire: date | None, year: int, month: int) -> bool:
    if not hire:
        return False
    me = month_end(year, month)
    if hire > me:
        return False
    if retire and retire < me:
        return False
    return True


def worked_in_year(person: dict, year: int) -> bool:
    hire = parse_date(person.get("입사일"))
    yr_ret = (person.get("연도별_퇴사일") or {}).get(str(year))
    retire = parse_date(yr_ret if yr_ret is not None else person.get("퇴사일"))
    if not hire:
        return True
    if hire > date(year, 12, 31):
        return False
    if retire and retire < date(year, 1, 31):
        return False
    return True


def tenure_under_1y(person: dict, year: int | None = None) -> bool:
    hire = parse_date(person.get("입사일"))
    if year is not None:
        yr_ret = (person.get("연도별_퇴사일") or {}).get(str(year))
        retire = parse_date(yr_ret if yr_ret is not None else person.get("퇴사일"))
    else:
        retire = parse_date(person.get("퇴사일"))
    if not hire or not retire:
        return False
    return retire < add_years(hire, 1)


def contract_date(person: dict) -> date | None:
    return parse_date(person.get("계약체결일")) or parse_date(person.get("입사일"))


def contract_age(person: dict) -> int | None:
    return full_age(parse_date(person.get("생년월일")), contract_date(person), person.get("병역개월", 0))


def current_year_end_age(person: dict, year: int) -> int | None:
    return full_age(parse_date(person.get("생년월일")), date(year, 12, 31), 0)


def youth_hold_years(corp_size: str) -> int:
    return R.YOUTH_HOLD_YEARS_LARGE if corp_size in ("일반기업", "대기업") else R.YOUTH_HOLD_YEARS_SME


def is_youth_month(person: dict, year: int, month: int, corp_size: str) -> bool:
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


def is_youth_month_for_cohort(
    person: dict,
    eval_year: int,
    month: int,
    cohort_year: int,
    corp_size: str,
    youth_label: str,
) -> bool:
    if not youth_label or youth_label == R.YOUTH_NONE:
        return False
    if youth_label in (R.YOUTH_SENIOR, R.YOUTH_DISABLED, R.YOUTH_CAREER):
        return True
    if youth_label == R.YOUTH_NK:
        return cohort_year >= 2025
    if youth_label == R.YOUTH_YOUNG:
        c_age = contract_age(person)
        if c_age is not None and R.YOUTH_AGE_MIN <= c_age <= R.YOUTH_AGE_MAX:
            c_dt = contract_date(person)
            if c_dt and c_dt <= date(cohort_year, 12, 31):
                return True
        return is_youth_month(person, eval_year, month, corp_size)
    return False


def youth_options(emp_type: str) -> list[str]:
    return R.YOUTH_TYPES_NON_REGULAR if emp_type in R.EMP_NOT_YOUTH_REGULAR else R.YOUTH_TYPES


def suggest_exclusion(person: dict, yrec: dict, year: int | None = None) -> str:
    emp = yrec.get("고용유형") or R.EMP_REGULAR
    if emp in R.EMP_AUTO_EXCLUDE:
        return R.EMP_AUTO_EXCLUDE[emp]
    if person.get("외국인"):
        return R.EXCL_FOREIGN
    if person.get("주주관계") in ("최대주주", "최대주주의 배우자", "최대주주의 직계존비속 등"):
        return person["주주관계"]
    if tenure_under_1y(person, year):
        return R.EXCL_UNDER_1Y
    return R.EXCL_NONE


def suggest_youth(person: dict, yrec: dict, year: int, corp_size: str) -> str:
    emp = yrec.get("고용유형") or R.EMP_REGULAR
    c_age = contract_age(person)
    if c_age is not None and c_age >= R.SENIOR_AGE:
        return R.YOUTH_SENIOR
    if emp not in R.EMP_NOT_YOUTH_REGULAR:
        if any(is_youth_month(person, year, m, corp_size) for m in range(1, 13)):
            return R.YOUTH_YOUNG
        if c_age is not None and R.YOUTH_AGE_MIN <= c_age <= R.YOUTH_AGE_MAX:
            return R.YOUTH_YOUNG
    return R.YOUTH_NONE


def _pick(yrec: dict, field: str, suggestion: str) -> str:
    if field in (yrec.get("_user_set") or []):
        return yrec.get(field) or suggestion
    return suggestion


def detect_last_paid_month(people: dict, year: int) -> int:
    last_m = 0
    has_any_pay_record = False
    for p in (people or {}).values():
        pay = (p.get("월급여") or {}).get(str(year))
        if pay and len(pay) >= 12:
            has_any_pay_record = True
            for idx in range(11, -1, -1):
                if (pay[idx] or 0) > 0:
                    if (idx + 1) > last_m:
                        last_m = idx + 1
                    break
    if not has_any_pay_record or last_m == 0:
        return 12
    return last_m


def compute_row(person: dict, yrec: dict, year: int, ctx: dict) -> dict:
    corp_size = ctx.get("corp_size", "중소기업")
    months_in_yr = max(1, min(12, int(ctx.get("months_in_year", 12) or 12)))
    act = active_months(year, months_in_yr)
    assume_year_end = bool(ctx.get("assume_year_end", True))
    last_paid_month = int(ctx.get("last_paid_month", 12) or 12)

    emp = yrec.get("고용유형") or R.EMP_REGULAR

    if emp in R.EMP_AUTO_EXCLUDE:
        excl = R.EMP_AUTO_EXCLUDE[emp]
    else:
        excl = _pick(yrec, "제외사유", suggest_exclusion(person, yrec, year))

    auto_regular = excl == R.EXCL_NONE
    ovr = yrec.get("상시_override") or ""
    is_regular = auto_regular if ovr not in ("O", "X") else (ovr == "O")

    allowed = youth_options(emp)
    if is_regular:
        youth = _pick(yrec, "청년등", suggest_youth(person, yrec, year, corp_size))
        if youth not in allowed:
            youth = suggest_youth(person, yrec, year, corp_size)
    else:
        youth = ""

    weight = R.EMP_WEIGHT.get(emp, 1.0)
    hire = parse_date(person.get("입사일"))
    yr_ret = (person.get("연도별_퇴사일") or {}).get(str(year))
    retire = parse_date(yr_ret if yr_ret is not None else person.get("퇴사일"))
    overrides = {int(k): float(v) for k, v in (yrec.get("월_override") or {}).items()}
    pay = (person.get("월급여") or {}).get(str(year))

    active_at_cutoff = True
    if pay and len(pay) >= 12 and last_paid_month < 12:
        paid_at_cut = (pay[last_paid_month - 1] or 0) > 0
        hired_after_cut = bool(hire and hire > month_end(year, last_paid_month))
        active_at_cutoff = paid_at_cut or hired_after_cut

    months, auto_months = [], []
    youth_flags, youth_b2_flags, youth_b3_flags = [], [], []
    no_pay, projected_months = [], []

    for m in range(1, 13):
        if m not in act:
            months.append(None)
            auto_months.append(None)
            youth_flags.append(False)
            youth_b2_flags.append(False)
            youth_b3_flags.append(False)
            continue

        emp_end = employed_at_month_end(hire, retire, year, m)
        is_unreached = (last_paid_month < 12) and (m > last_paid_month)

        if not is_regular or not emp_end:
            auto_v = 0.0
        elif is_unreached:
            if assume_year_end and active_at_cutoff:
                auto_v = weight
            else:
                auto_v = 0.0
        else:
            auto_v = weight

        v = overrides.get(m, auto_v) if is_regular else 0.0
        months.append(v)
        auto_months.append(auto_v)

        if youth == R.YOUTH_YOUNG:
            y_flag = is_youth_month(person, year, m, corp_size)
        else:
            y_flag = bool(youth) and youth != R.YOUTH_NONE
        youth_flags.append(bool(v) and y_flag)

        yb2 = is_youth_month_for_cohort(person, year, m, year - 1, corp_size, youth)
        youth_b2_flags.append(bool(v) and yb2)

        yb3 = is_youth_month_for_cohort(person, year, m, year - 2, corp_size, youth)
        youth_b3_flags.append(bool(v) and yb3)

        if v:
            if is_unreached and m not in overrides:
                projected_months.append(m)
            elif not is_unreached and pay and len(pay) == 12 and not (pay[m - 1] or 0):
                no_pay.append(m)

    n = len(act) or 12
    row_sum = sum(Fraction(str(v)) for v in months if v)
    youth_sum = sum(Fraction(str(v)) for v, yf in zip(months, youth_flags) if v and yf)
    youth_b2_sum = sum(Fraction(str(v)) for v, yf in zip(months, youth_b2_flags) if v and yf)
    youth_b3_sum = sum(Fraction(str(v)) for v, yf in zip(months, youth_b3_flags) if v and yf)

    row_avg_exact = float(row_sum / n) if n else 0.0
    row_avg_trunc = trunc2(row_sum / n) if n else 0.0
    yth_b1_trunc = trunc2(youth_sum / n) if n else 0.0
    gen_b1_trunc = round(max(0.0, row_avg_trunc - yth_b1_trunc), 2)

    yth_b2_trunc = trunc2(youth_b2_sum / n) if n else 0.0
    gen_b2_trunc = round(max(0.0, row_avg_trunc - yth_b2_trunc), 2)

    yth_b3_trunc = trunc2(youth_b3_sum / n) if n else 0.0
    gen_b3_trunc = round(max(0.0, row_avg_trunc - yth_b3_trunc), 2)

    under_1y = tenure_under_1y(person, year)
    b4_reg = 0.0 if (under_1y and year >= 2025) else row_avg_trunc
    b4_yth = 0.0 if (under_1y and year >= 2025) else yth_b1_trunc
    b4_gen = round(max(0.0, b4_reg - b4_yth), 2)

    c_age = contract_age(person)
    cur_age = current_year_end_age(person, year)

    return {
        "제외사유": excl,
        "청년등": youth,
        "상시": "O" if is_regular else "X",
        "상시_auto": "O" if auto_regular else "X",
        "취업연령": c_age,
        "현재연령": cur_age,
        "months": months,
        "auto_months": auto_months,
        "youth_flags": youth_flags,
        "youth_b2_flags": youth_b2_flags,
        "youth_b3_flags": youth_b3_flags,
        "row_sum": row_sum,
        "youth_sum": youth_sum,
        "youth_b2_sum": youth_b2_sum,
        "youth_b3_sum": youth_b3_sum,
        "row_avg": row_avg_exact,
        "row_avg_trunc": row_avg_trunc,
        "b1_yth": yth_b1_trunc,
        "b1_gen": gen_b1_trunc,
        "b1_reg": row_avg_trunc,
        "b2_yth": yth_b2_trunc,
        "b2_gen": gen_b2_trunc,
        "b2_reg": row_avg_trunc,
        "b3_yth": yth_b3_trunc,
        "b3_gen": gen_b3_trunc,
        "b3_reg": row_avg_trunc,
        "b4_yth": b4_yth,
        "b4_gen": b4_gen,
        "b4_reg": b4_reg,
        "youth_options": allowed,
        "no_pay_months": no_pay,
        "projected_months": projected_months,
        "excl_locked": emp in R.EMP_AUTO_EXCLUDE,
    }


def year_totals(computed_rows: list[dict], months_in_year: int) -> dict:
    n = max(1, min(12, int(months_in_year or 12)))
    total = sum((r["row_sum"] for r in computed_rows), Fraction(0))
    youth = sum((r["youth_sum"] for r in computed_rows), Fraction(0))
    youth_b2 = sum((r.get("youth_b2_sum", r["youth_sum"]) for r in computed_rows), Fraction(0))
    youth_b3 = sum((r.get("youth_b3_sum", r["youth_sum"]) for r in computed_rows), Fraction(0))

    regular = trunc2(total / n)
    youth_cnt = trunc2(youth / n)
    general = round(max(0.0, regular - youth_cnt), 2)

    b2_yth_cnt = trunc2(youth_b2 / n)
    b2_gen_cnt = round(max(0.0, regular - b2_yth_cnt), 2)

    b3_yth_cnt = trunc2(youth_b3 / n)
    b3_gen_cnt = round(max(0.0, regular - b3_yth_cnt), 2)

    b4_reg_cnt = round(sum(float(r.get("b4_reg", 0.0)) for r in computed_rows), 2)
    b4_yth_cnt = round(sum(float(r.get("b4_yth", 0.0)) for r in computed_rows), 2)
    b4_gen_cnt = round(max(0.0, b4_reg_cnt - b4_yth_cnt), 2)

    month_regular, month_youth = [], []
    for m in range(12):
        vals = [r["months"][m] for r in computed_rows]
        if all(v is None for v in vals):
            month_regular.append(None)
            month_youth.append(None)
            continue
        month_regular.append(float(sum(Fraction(str(v)) for v in vals if v)))
        month_youth.append(
            float(
                sum(
                    Fraction(str(r["months"][m]))
                    for r in computed_rows
                    if r["months"][m] and r["youth_flags"][m]
                )
            )
        )
    month_general = [None if a is None else round(a - b, 2) for a, b in zip(month_regular, month_youth)]

    return {
        "상시_합계": float(total),
        "청년등_합계": float(youth),
        "청년외_합계": float(total - youth),
        "상시_평균": regular,
        "청년등_평균": youth_cnt,
        "청년외_평균": general,
        "b1_reg": regular,
        "b1_yth": youth_cnt,
        "b1_gen": general,
        "b2_reg": regular,
        "b2_yth": b2_yth_cnt,
        "b2_gen": b2_gen_cnt,
        "b3_reg": regular,
        "b3_yth": b3_yth_cnt,
        "b3_gen": b3_gen_cnt,
        "b4_reg": b4_reg_cnt,
        "b4_yth": b4_yth_cnt,
        "b4_gen": b4_gen_cnt,
        "월별_상시": month_regular,
        "월별_청년등": month_youth,
        "월별_청년외": month_general,
        "months_in_year": n,
    }


def regular_excluding_part_time(computed_rows: list[dict], emp_types: list[str], months_in_year: int) -> float:
    n = max(1, min(12, int(months_in_year or 12)))
    total = sum(
        (r["row_sum"] for r, e in zip(computed_rows, emp_types) if e not in (R.EMP_PT_050, R.EMP_PT_075)),
        Fraction(0),
    )
    return trunc2(total / n)


def calc_increase_with_cap(
    cur_regular: float,
    cur_youth: float,
    cur_non_youth_or_prev_reg: float,
    prev_regular_or_prev_yth: float,
    prev_youth: float | None = None,
    prev_non_youth: float | None = None,
) -> dict[str, float]:
    if prev_youth is None:
        prev_reg = float(cur_non_youth_or_prev_reg or 0.0)
        prev_yth = float(prev_regular_or_prev_yth or 0.0)
    else:
        prev_reg = float(prev_regular_or_prev_yth or 0.0)
        prev_yth = float(prev_youth or 0.0)

    cur_reg = float(cur_regular or 0.0)
    cur_yth = float(cur_youth or 0.0)
    cur_gen = round(max(0.0, cur_reg - cur_yth), 2)
    prev_gen = round(max(0.0, prev_reg - prev_yth), 2) if prev_non_youth is None else float(prev_non_youth or 0.0)

    total_diff = round(cur_reg - prev_reg, 2)
    youth_diff = round(cur_yth - prev_yth, 2)
    gen_diff = round(cur_gen - prev_gen, 2)

    total_inc = max(0.0, total_diff)
    youth_inc_raw = max(0.0, youth_diff)
    gen_inc_raw = max(0.0, gen_diff)

    youth_inc_capped = round(min(total_inc, youth_inc_raw), 2)
    non_youth_inc = round(max(0.0, total_inc - youth_inc_capped), 2)

    return {
        "전체_증감": total_diff,
        "전체_증가": total_inc,
        "청년등_증가": youth_inc_capped,
        "청년등외_증가": non_youth_inc,
        "청년등_한도적용전": youth_inc_raw,
        "청년등외_한도적용전": gen_inc_raw,
        "total_diff": total_diff,
        "youth_diff": youth_diff,
        "total_inc": total_inc,
        "youth_inc_raw": youth_inc_raw,
        "youth_inc": youth_inc_capped,
        "non_youth_inc": non_youth_inc,
    }


def apply_minimum_increase_hurdle_2026(
    corp_size: str,
    total_inc: float,
    youth_inc: float,
) -> dict[str, float]:
    hurdle = R.MIN_INCREASE_HURDLE_2026.get(corp_size, 0.0)
    if total_inc <= hurdle:
        return {
            "hurdle": hurdle,
            "recognized_total_inc": 0.0,
            "recognized_youth_inc": 0.0,
            "recognized_non_youth_inc": 0.0,
        }
    recognized_total = round(total_inc - hurdle, 2)
    recognized_youth = round(min(youth_inc, recognized_total), 2)
    recognized_non_youth = round(max(0.0, recognized_total - recognized_youth), 2)
    return {
        "hurdle": hurdle,
        "recognized_total_inc": recognized_total,
        "recognized_youth_inc": recognized_youth,
        "recognized_non_youth_inc": recognized_non_youth,
    }


def get_unit_rates(
    corp_size: str,
    is_capital: bool,
    scheme: str = "legacy",
    retention_year: int = 1,
) -> dict[str, int]:
    reg_key = "수도권" if is_capital else "수도권 외"
    size_key = corp_size if corp_size in R.CREDIT_RATES_LEGACY_2023_2025 else "중소기업"
    if scheme == "new_2026":
        tbl = R.CREDIT_RATES_NEW_2026[size_key][reg_key]
        ry = max(1, min(3, int(retention_year or 1)))
        return {
            "청년등": int(tbl["청년등"].get(ry, 0)),
            "청년등외": int(tbl["청년등외"].get(ry, 0)),
        }
    tbl = R.CREDIT_RATES_LEGACY_2023_2025[size_key][reg_key]
    return {"청년등": int(tbl["청년등"]), "청년등외": int(tbl["청년등외"])}


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
) -> dict[str, Any]:
    elapsed = eval_year - cohort_year
    rates = get_unit_rates(corp_size, is_capital, scheme="legacy")
    r_yth = rates["청년등"] * 10_000
    r_gen = rates["청년등외"] * 10_000
    r_diff = max(0, r_yth - r_gen)

    init_total_inc = round(init_yth_inc + init_gen_inc, 2)
    is_large = corp_size in ("일반기업", "대기업")

    if init_total_inc <= 0 or (is_large and elapsed >= 2) or elapsed not in (1, 2):
        return {
            "applicable": False,
            "cohort_year": cohort_year,
            "eval_year": eval_year,
            "stage_label": f"{cohort_year}년 귀속분 {'1차 사후관리(2차년도)' if elapsed == 1 else '2차 사후관리(3차년도)'}",
            "case_code": "N/A",
            "case_title": "해당 없음 (최초 공제인원 0명 또는 사후관리 기간 종료)",
            "continued_credit_won": 0,
            "clawback_gross_won": 0,
            "carryforward_offset_won": 0,
            "clawback_net_payable_won": 0,
            "retained_yth_inc": 0.0,
            "retained_gen_inc": 0.0,
            "claw_yth_cnt": 0.0,
            "claw_gen_cnt": 0.0,
            "claw_diff_cnt": 0.0,
            "prior_years_claimed_count": 0,
            "formula_note": "최초 공제받은 고용증가 인원이 없거나 사후관리 대상이 아닙니다.",
        }

    prior_years_claimed_count = 1
    if elapsed == 2:
        if prev_pm_reg is None or prev_pm_reg >= init_reg:
            prior_years_claimed_count = 2

    if cur_pm_reg >= init_reg:
        dec_yth = max(0.0, round(init_yth - cur_pm_yth, 2))
        claw_diff_cnt = round(min(init_yth_inc, dec_yth), 2)
        retained_yth = round(max(0.0, init_yth_inc - claw_diff_cnt), 2)
        retained_gen = round(init_gen_inc + claw_diff_cnt, 2)

        continued_credit_won = int(round(retained_yth * r_yth + retained_gen * r_gen))
        clawback_gross_won = int(round(claw_diff_cnt * r_diff * prior_years_claimed_count))

        if claw_diff_cnt == 0:
            case_code = "A-1"
            case_title = "정상 유지 (전체 상시 및 청년등 상시근로자 모두 유지)"
            formula_note = (
                f"전체 상시({cur_pm_reg:.2f}명 ≥ 최초 {init_reg:.2f}명) 및 청년등({cur_pm_yth:.2f}명 ≥ 최초 {init_yth:.2f}명) 모두 유지 → "
                f"{elapsed + 1}차년도 연속공제 100% 수령, 추가납부(추징) 0원"
            )
        else:
            case_code = "A-2"
            case_title = "전체 상시 유지 + 청년등만 일부 감소 (단가 차액 추징 및 일반단가 연속공제)"
            formula_note = (
                f"전체 상시({cur_pm_reg:.2f}명 ≥ 최초 {init_reg:.2f}명) 유지, 청년등 {claw_diff_cnt:.2f}명 감소 → "
                f"감소분 {claw_diff_cnt:.2f}명은 청년등외 단가({rates['청년등외']:,}만원)로 대체 유지된 것으로 보아 "
                f"단가차액({rates['청년등'] - rates['청년등외']:,}만원 × {prior_years_claimed_count}개년) 추징 후 연속공제 계속 적용"
            )

        if init_credit_claimed_won > 0:
            clawback_gross_won = min(clawback_gross_won, int(init_credit_claimed_won))
        offset_won = min(clawback_gross_won, max(0, int(unclaimed_carryforward_won or 0)))
        net_payable = max(0, clawback_gross_won - offset_won)

        return {
            "applicable": True,
            "cohort_year": cohort_year,
            "eval_year": eval_year,
            "stage_label": f"{cohort_year}년 귀속분 {'1차 사후관리(2차년도)' if elapsed == 1 else '2차 사후관리(3차년도)'}",
            "case_code": case_code,
            "case_title": case_title,
            "continued_credit_won": continued_credit_won,
            "clawback_gross_won": clawback_gross_won,
            "carryforward_offset_won": offset_won,
            "clawback_net_payable_won": net_payable,
            "retained_yth_inc": retained_yth,
            "retained_gen_inc": retained_gen,
            "claw_yth_cnt": 0.0,
            "claw_gen_cnt": 0.0,
            "claw_diff_cnt": claw_diff_cnt,
            "prior_years_claimed_count": prior_years_claimed_count,
            "formula_note": formula_note,
        }

    continued_credit_won = 0
    dec_total = round(min(init_total_inc, max(0.0, round(init_reg - cur_pm_reg, 2))), 2)
    dec_yth_raw = max(0.0, round(init_yth - cur_pm_yth, 2))

    claw_yth_cnt = round(min(init_yth_inc, dec_yth_raw, dec_total), 2)
    claw_gen_cnt = round(min(init_gen_inc, max(0.0, round(dec_total - claw_yth_cnt, 2))), 2)

    remaining_yth_inc = round(max(0.0, init_yth_inc - claw_yth_cnt), 2)
    excess_yth_dec = round(max(0.0, dec_yth_raw - claw_yth_cnt), 2)
    claw_diff_cnt = round(min(remaining_yth_inc, excess_yth_dec), 2)

    per_year_clawback = int(round(claw_yth_cnt * r_yth + claw_gen_cnt * r_gen + claw_diff_cnt * r_diff))
    clawback_gross_won = per_year_clawback * prior_years_claimed_count

    if init_credit_claimed_won > 0:
        clawback_gross_won = min(clawback_gross_won, int(init_credit_claimed_won))

    offset_won = min(clawback_gross_won, max(0, int(unclaimed_carryforward_won or 0)))
    net_payable = max(0, clawback_gross_won - offset_won)

    if claw_yth_cnt > 0 and claw_gen_cnt == 0 and claw_diff_cnt == 0:
        case_code = "B-1"
        case_title = "전체 상시 감소 (청년등 상시근로자 감소분 추징 · 연속공제 중단)"
    elif claw_yth_cnt == 0 and claw_gen_cnt > 0:
        case_code = "B-2"
        case_title = "전체 상시 감소 (청년등 유지, 청년등외 감소분 추징 · 연속공제 중단)"
    else:
        case_code = "B-3"
        case_title = "전체 상시 감소 (청년등 + 청년등외 복합 감소 추징 · 연속공제 중단)"

    formula_note = (
        f"전체 상시 {dec_total:.2f}명 감소({init_reg:.2f}→{cur_pm_reg:.2f}명)로 당해 연속공제 중단(0원). "
        f"[추징 산식: (청년등 감소 {claw_yth_cnt:.2f}명×{rates['청년등']:,}만원 + "
        f"청년등외 감소 {claw_gen_cnt:.2f}명×{rates['청년등외']:,}만원"
        + (f" + 일반대체 차액 {claw_diff_cnt:.2f}명×{rates['청년등'] - rates['청년등외']:,}만원" if claw_diff_cnt > 0 else "")
        + f") × 기공제 {prior_years_claimed_count}개년]"
    )

    return {
        "applicable": True,
        "cohort_year": cohort_year,
        "eval_year": eval_year,
        "stage_label": f"{cohort_year}년 귀속분 {'1차 사후관리(2차년도)' if elapsed == 1 else '2차 사후관리(3차년도)'}",
        "case_code": case_code,
        "case_title": case_title,
        "continued_credit_won": continued_credit_won,
        "clawback_gross_won": clawback_gross_won,
        "carryforward_offset_won": offset_won,
        "clawback_net_payable_won": net_payable,
        "retained_yth_inc": round(max(0.0, init_yth_inc - claw_yth_cnt - claw_diff_cnt), 2),
        "retained_gen_inc": round(max(0.0, init_gen_inc - claw_gen_cnt), 2),
        "claw_yth_cnt": claw_yth_cnt,
        "claw_gen_cnt": claw_gen_cnt,
        "claw_diff_cnt": claw_diff_cnt,
        "prior_years_claimed_count": prior_years_claimed_count,
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
    ty = int(tax_year or R.DEFAULT_TAX_YEAR)
    prior_filings = prior_filings or {}
    add_in = additional_inputs or {}

    def _norm_sum(d: dict | None) -> dict:
        if not d:
            return {"regular": 0.0, "youth": 0.0, "non_youth": 0.0, "b2_reg": 0.0, "b2_yth": 0.0, "b3_reg": 0.0, "b3_yth": 0.0, "b4_reg": 0.0, "b4_yth": 0.0}
        reg = float(d.get("상시_평균", d.get("regular", d.get("b1_reg", 0.0))) or 0.0)
        yth = float(d.get("청년등_평균", d.get("youth", d.get("b1_yth", 0.0))) or 0.0)
        gen = float(d.get("청년외_평균", d.get("non_youth", round(max(0.0, reg - yth), 2))) or 0.0)
        return {
            "regular": reg,
            "youth": yth,
            "non_youth": gen,
            "b2_reg": float(d.get("b2_reg", d.get("b2_regular", reg)) or reg),
            "b2_yth": float(d.get("b2_yth", d.get("b2_youth", yth)) or yth),
            "b3_reg": float(d.get("b3_reg", d.get("b3_regular", reg)) or reg),
            "b3_yth": float(d.get("b3_yth", d.get("b3_youth", yth)) or yth),
            "b4_reg": float(d.get("b4_reg", d.get("b4_regular", reg)) or reg),
            "b4_yth": float(d.get("b4_yth", d.get("b4_youth", yth)) or yth),
        }

    cur_s = _norm_sum(summaries.get(ty))
    prev_s = _norm_sum(summaries.get(ty - 1))
    prev2_s = _norm_sum(summaries.get(ty - 2))

    cur_inc = calc_increase_with_cap(
        cur_s["regular"], cur_s["youth"], prev_s["regular"], prev_s["youth"]
    )
    rates_legacy = get_unit_rates(corp_size, is_capital, scheme="legacy")
    rates_new_y1 = get_unit_rates(corp_size, is_capital, scheme="new_2026", retention_year=1)
    rates_new_y2 = get_unit_rates(corp_size, is_capital, scheme="new_2026", retention_year=2)
    rates_new_y3 = get_unit_rates(corp_size, is_capital, scheme="new_2026", retention_year=3)

    cur_legacy_yth_won = int(round(cur_inc["youth_inc"] * rates_legacy["청년등"] * 10_000))
    cur_legacy_gen_won = int(round(cur_inc["non_youth_inc"] * rates_legacy["청년등외"] * 10_000))
    cur_legacy_total_won = cur_legacy_yth_won + cur_legacy_gen_won

    hurdle_res = apply_minimum_increase_hurdle_2026(corp_size, cur_inc["total_inc"], cur_inc["youth_inc"])
    cur_new2026_yth_won = int(round(hurdle_res["recognized_youth_inc"] * rates_new_y1["청년등"] * 10_000))
    cur_new2026_gen_won = int(round(hurdle_res["recognized_non_youth_inc"] * rates_new_y1["청년등외"] * 10_000))
    cur_new2026_total_won = cur_new2026_yth_won + cur_new2026_gen_won

    active_scheme = "new_2026" if (ty >= 2026 and scheme_2026 == "new_2026") else "legacy"
    cur_base_credit_won = cur_new2026_total_won if active_scheme == "new_2026" else cur_legacy_total_won

    pf_y1 = prior_filings.get(ty - 1, {})
    auto_y1_inc = calc_increase_with_cap(
        prev_s["regular"], prev_s["youth"], prev2_s["regular"], prev2_s["youth"]
    )
    y1_init_reg = float(pf_y1.get("init_reg", prev_s["regular"]) or 0.0)
    y1_init_yth = float(pf_y1.get("init_yth", prev_s["youth"]) or 0.0)
    y1_init_yth_inc = float(pf_y1.get("init_yth_inc", auto_y1_inc["youth_inc"]) or 0.0)
    y1_init_gen_inc = float(pf_y1.get("init_gen_inc", auto_y1_inc["non_youth_inc"]) or 0.0)
    y1_claimed_won = int(pf_y1.get("claimed_won", 0) or 0)
    y1_carryforward_won = int(pf_y1.get("carryforward_won", 0) or 0)

    pm_y1 = calc_legacy_post_management(
        cohort_year=ty - 1,
        eval_year=ty,
        corp_size=corp_size,
        is_capital=is_capital,
        init_reg=y1_init_reg,
        init_yth=y1_init_yth,
        init_yth_inc=y1_init_yth_inc,
        init_gen_inc=y1_init_gen_inc,
        cur_pm_reg=cur_s["b2_reg"],
        cur_pm_yth=cur_s["b2_yth"],
        init_credit_claimed_won=y1_claimed_won,
        unclaimed_carryforward_won=y1_carryforward_won,
    )

    pf_y2 = prior_filings.get(ty - 2, {})
    y2_init_reg = float(pf_y2.get("init_reg", prev2_s["regular"]) or 0.0)
    y2_init_yth = float(pf_y2.get("init_yth", prev2_s["youth"]) or 0.0)
    y2_init_yth_inc = float(pf_y2.get("init_yth_inc", 0.0) or 0.0)
    y2_init_gen_inc = float(pf_y2.get("init_gen_inc", 0.0) or 0.0)
    y2_claimed_won = int(pf_y2.get("claimed_won", 0) or 0)
    y2_carryforward_won = int(pf_y2.get("carryforward_won", 0) or 0)

    pm_y2 = calc_legacy_post_management(
        cohort_year=ty - 2,
        eval_year=ty,
        corp_size=corp_size,
        is_capital=is_capital,
        init_reg=y2_init_reg,
        init_yth=y2_init_yth,
        init_yth_inc=y2_init_yth_inc,
        init_gen_inc=y2_init_gen_inc,
        cur_pm_reg=cur_s["b3_reg"],
        cur_pm_yth=cur_s["b3_yth"],
        init_credit_claimed_won=y2_claimed_won,
        unclaimed_carryforward_won=y2_carryforward_won,
        prev_pm_reg=prev_s["b2_reg"],
        prev_pm_yth=prev_s["b2_yth"],
    )

    add_unit_manwon = R.ADDITIONAL_CREDIT_PER_PERSON.get(corp_size, 0)
    add_unit_won = add_unit_manwon * 10_000
    non_decrease_ok = cur_s["regular"] >= prev_s["regular"]

    parental_ret_cnt = int(add_in.get("parental_return_count", 0) or 0)
    reg_conv_cnt = int(add_in.get("regular_conversion_count", 0) or 0) if ty <= 2024 else 0
    additional_credit_won = (parental_ret_cnt + reg_conv_cnt) * add_unit_won if non_decrease_ok else 0

    early_term_add_cnt = int(add_in.get("additional_clawback_count", 0) or 0)
    additional_clawback_won = early_term_add_cnt * add_unit_won

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
    rural_special_tax_won = int(round(total_credit_gross_won * R.RURAL_SPECIAL_TAX_RATE))

    return {
        "tax_year": ty,
        "corp_size": corp_size,
        "is_capital": is_capital,
        "active_scheme": active_scheme,
        "cur_s": cur_s,
        "prev_s": prev_s,
        "prev2_s": prev2_s,
        "rates_legacy": rates_legacy,
        "rates_new_y1": rates_new_y1,
        "rates_new_y2": rates_new_y2,
        "rates_new_y3": rates_new_y3,
        "cur_inc": cur_inc,
        "hurdle_res": hurdle_res,
        "cur_legacy_yth_won": cur_legacy_yth_won,
        "cur_legacy_gen_won": cur_legacy_gen_won,
        "cur_legacy_total_won": cur_legacy_total_won,
        "cur_new2026_yth_won": cur_new2026_yth_won,
        "cur_new2026_gen_won": cur_new2026_gen_won,
        "cur_new2026_total_won": cur_new2026_total_won,
        "cur_base_credit_won": cur_base_credit_won,
        "pm_y1": pm_y1,
        "pm_y2": pm_y2,
        "non_decrease_ok": non_decrease_ok,
        "parental_ret_cnt": parental_ret_cnt,
        "reg_conv_cnt": reg_conv_cnt,
        "additional_credit_won": additional_credit_won,
        "early_term_add_cnt": early_term_add_cnt,
        "additional_clawback_won": additional_clawback_won,
        "total_continued_credit_won": total_continued_credit_won,
        "total_credit_gross_won": total_credit_gross_won,
        "total_clawback_gross_won": total_clawback_gross_won,
        "total_carryforward_offset_won": total_carryforward_offset_won,
        "total_clawback_net_payable_won": total_clawback_net_payable_won,
        "net_tax_benefit_won": net_tax_benefit_won,
        "rural_special_tax_won": rural_special_tax_won,
        "net_after_rural_tax_won": net_tax_benefit_won - rural_special_tax_won,
    }


def review(
    people: dict,
    year_recs: dict,
    years: list[int],
    ctx_by_year: dict,
    computed: dict,
    prev_filing: dict | None = None,
) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []

    for pid, p in people.items():
        nm = p.get("성명") or "(이름없음)"
        birth, hire, retire = (parse_date(p.get(k)) for k in ("생년월일", "입사일", "퇴사일"))
        if not birth:
            out.append(("오류", f"{nm}: 생년월일이 없어 청년(15~34세)·60세 이상 판정을 할 수 없습니다."))
        if not hire:
            out.append(("오류", f"{nm}: 입사일이 없어 월별 근무 여부를 계산할 수 없습니다."))
        if hire and retire and retire < hire:
            out.append(("오류", f"{nm}: 퇴사일({retire})이 입사일({hire})보다 빠릅니다."))

    for y in years:
        rows = computed.get(y, {})
        for pid, c in rows.items():
            p, yrec = people[pid], year_recs[y][pid]
            nm = p.get("성명") or "(이름없음)"
            if c["no_pay_months"]:
                ms = ", ".join(f"{m}월" for m in c["no_pay_months"])
                out.append(
                    ("확인", f"[{y}년] {nm}: {ms} 급여 지급이 없습니다. 무급휴직·육아휴직 등으로 4대보험 납부도 없었다면 해당 월을 0으로 바꾸세요.")
                )
            if c["청년등"] == R.YOUTH_SENIOR:
                a = contract_age(p)
                if a is not None and a < R.SENIOR_AGE:
                    out.append(
                        ("오류", f"[{y}년] {nm}: 근로계약 체결일 기준 만 {a}세라 '취업시 60세 이상'에 해당하지 않습니다.")
                    )
            if c["청년등"] == R.YOUTH_YOUNG and not any(c["youth_flags"]):
                out.append(
                    ("확인", f"[{y}년] {nm}: '취업시 청년'으로 선택했지만 {y}년에 당해 신규공제용 청년 요건을 충족하는 달이 없습니다. 병역기간 차감 여부를 확인하세요.")
                )
            if c["청년등"] == R.YOUTH_NK and y <= 2024:
                out.append(
                    ("확인", f"[{y}년] {nm}: 북한이탈주민은 2025.2.28 시행령 개정으로 2025년 귀속분부터 청년등 상시근로자에 포함됩니다.")
                )
            if p.get("주주관계") and c["상시"] == "O":
                out.append(
                    ("확인", f"[{y}년] {nm}: 주주명부상 '{p['주주관계']}'로 보이는데 상시근로자에 포함되어 있습니다.")
                )
            if yrec.get("고용유형") == R.EMP_PT_075:
                out.append(
                    ("확인", f"[{y}년] {nm}: 단시간 0.75명은 기간의 정함이 없는 근로계약·차별 없음·시간당 임금 최저임금 120%(중소기업) 이상 요건을 모두 충족해야 합니다.")
                )
            if c.get("제외사유") == R.EXCL_MATERNITY_REPLACED:
                out.append(
                    ("확인", f"[{y}년] {nm}: '출산전후휴가자(대체인력채용)' 제외 특례(조특령 제26조의8 제7항, 2024.2.29 신설)가 적용되었습니다.")
                )

        if any(year_recs[y][pid].get("고용유형") == R.EMP_PT_075 for pid in rows):
            cur = regular_excluding_part_time(
                list(rows.values()),
                [year_recs[y][pid].get("고용유형") for pid in rows],
                ctx_by_year[y]["months_in_year"],
            )
            if cur < 0.75:
                out.append(
                    ("오류", f"[{y}년] 단시간 제외 상시근로자 수({cur:.2f}명)가 최소 기준(0.75명) 미만이라 단시간 0.75명 가중치를 적용할 수 없습니다.")
                )
            if (y - 1) in computed:
                prv_rows = computed[y - 1]
                prv = regular_excluding_part_time(
                    list(prv_rows.values()),
                    [year_recs[y - 1][pid].get("고용유형") for pid in prv_rows],
                    ctx_by_year[y - 1]["months_in_year"],
                )
                if cur < prv:
                    out.append(
                        ("오류", f"[{y}년] 단시간 제외 상시근로자 수({cur:.2f}명)가 {y-1}년({prv:.2f}명)보다 감소해 0.75명을 적용할 수 없습니다. 0.5명으로 바꾸세요.")
                    )

    if prev_filing:
        for y in years:
            filed = prev_filing.get(str(y))
            if filed and y in computed:
                t = year_totals(list(computed[y].values()), ctx_by_year[y]["months_in_year"])
                if filed.get("상시") is not None and abs(float(filed["상시"]) - t["상시_평균"]) >= 0.01:
                    out.append(
                        ("확인", f"[{y}년] 기신고 명세서 상시근로자({filed['상시']}명) ↔ 원천징수부 자동계산({t['상시_평균']:.2f}명) 차이가 있습니다. (25.02 인별절사 합산치: {t['b4_reg']:.2f}명)")
                    )

    return out
