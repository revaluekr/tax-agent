# -*- coding: utf-8 -*-
"""
[모듈 2/4] 통합고용세액공제 — 사원별 · 월별 상시근로자 판정 및 연도별 A·B 계산방식 동시 산출 엔진 (hc_row_engine.py)
- 2단계 사원표의 개인별 월별 재직 가중치(compute_row)와 연도별 A방식(합계 후 절사)·B방식(사원별 절사 후 합계) 동시 집계(year_totals)를 전담합니다.
- 근거: 국세청 법인세과 「'26년 3월 법인세 통합고용세액공제 상시근로자 수 계산 안내」 (재정경제부 세제실 회신 반영)
  및 조세특례제한법 시행령(2026.2.27. 대통령령 제36127호) 제26조의8 제6항 · 부칙 제11조
"""
from __future__ import annotations

from fractions import Fraction
from typing import Any

from . import rules as R
from .hc_eligibility import (
    NEW_TENURE_RULE_FROM,
    NEW_YOUTH_DEF_FROM_COHORT,
    _get_month_pay,
    _has_any_pay_record,
    _pick,
    active_months,
    calc_method_badge_label,
    calc_method_for,
    contract_age,
    contract_date,
    current_year_end_age,
    employed_at_month_end,
    is_youth_month,
    is_youth_month_for_cohort,
    month_end,
    parse_date,
    suggest_exclusion,
    suggest_youth,
    trunc2,
    was_youth_in_year_by_age,
    youth_flag_old_def,
    youth_options,
)

# ══════════════════════════════════════════════════════════════════
# 4. 개인별 · 월별 상시근로자 및 우측 블록(당해 세액공제 · 1차 사후관리 · 2차 사후관리) 계산
# ══════════════════════════════════════════════════════════════════
def compute_row(person: dict, yrec: dict, year: int, ctx: dict) -> dict:
    corp_size = R.normalize_corp_size(ctx.get("corp_size") or "중소기업")
    corp_size_by_year = ctx.get("corp_size_by_year") or {}
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
    sug_excl = suggest_exclusion(person, yrec, year, old_rule=bool(ctx.get("old_tenure_rule")), as_of_year=ctx.get("as_of_year"))
    excl = _pick(yrec, "제외사유", sug_excl)
    excl_locked = emp_type in R.EMP_AUTO_EXCLUDE

    effective_excl = R.EXCL_NONE if excl == R.EXCL_MATERNITY_REPLACED else excl
    auto_regular = "O" if (effective_excl == R.EXCL_NONE and emp_type not in R.EMP_AUTO_EXCLUDE) else "X"
    ovr_regular = yrec.get("상시_override") or ""
    is_regular = ovr_regular if ovr_regular in ("O", "X") else auto_regular

    opts = youth_options(emp_type)
    sug_youth = suggest_youth(person, yrec, year, corp_size, corp_size_by_year=corp_size_by_year)
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
    c1_was_youth = bool((cmap.get(year - 1) or {}).get(pid, False)) if (year - 1) in cmap else None
    c2_was_youth = bool((cmap.get(year - 2) or {}).get(pid, False)) if (year - 2) in cmap else None

    months: list[float | None] = []
    youth_flags_b1: list[bool] = []
    youth_flags_b2: list[bool] = []
    youth_flags_b3: list[bool] = []
    youth_flags_b2a: list[bool] = []          # 연속공제 판정용 (간주 없음)
    youth_flags_b3a: list[bool] = []
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
                            val = weight
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
                    val = weight
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
                # 조특령 부칙(2026.2.27.) 제11조 제1항: 2024년 이전 최초 공제 코호트에는 계약일 기준 청년 간주 규정을 적용하지 않음
                yf1 = is_youth_month(
                    person, year, m, corp_size,
                    use_hold=(int(year) >= NEW_YOUTH_DEF_FROM_COHORT),
                    corp_size_by_year=corp_size_by_year,
                ) if birth_ok else False
            elif youth == R.YOUTH_NK:
                yf1 = year >= 2025
            else:
                yf1 = True

            # 사후관리용 청년 판정 (귀속분별 규칙)
            #  · 2025년 이후 최초공제분: 새 정의(유예 포함), 간주 없음 → 추가납부·연속공제 모두 당해 판정과 같음
            #  · 2024년 이전 최초공제분: 추가납부는 최초연도 청년 간주(구 제5항), 연속공제 판정은 종전 정의의 실제 청년 (조특령 부칙(2026.2.27.) 제11조 제1항)
            def _cohort_flags(cy: int, was):
                cy_corp_size = R.normalize_corp_size(
                    corp_size_by_year.get(cy) or corp_size_by_year.get(str(cy)) or corp_size,
                    corp_size,
                )
                if cy >= NEW_YOUTH_DEF_FROM_COHORT:
                    if cy_corp_size == corp_size or youth != R.YOUTH_YOUNG:
                        claw = yf1
                        act_cy = yf1
                    else:
                        birth_ok_cy = parse_date(person.get("생년월일")) is not None and contract_date(person) is not None
                        yf_cy = is_youth_month(person, year, m, cy_corp_size, corp_size_by_year=corp_size_by_year) if birth_ok_cy else False
                        claw = yf_cy
                        act_cy = yf_cy
                    if not claw and youth not in (R.YOUTH_SENIOR, R.YOUTH_DISABLED, R.YOUTH_CAREER, R.YOUTH_NK):
                        cdt = contract_date(person)
                        if cdt is not None and cdt.year <= 2024 and parse_date(person.get("생년월일")):
                            w = was if was is not None else was_youth_in_year_by_age(person, cy, cy_corp_size, corp_size_by_year=corp_size_by_year)
                            claw = bool(w)
                    return claw, act_cy
                claw = is_youth_month_for_cohort(person, year, m, cy, cy_corp_size, youth, was, corp_size_by_year=corp_size_by_year)
                act = youth_flag_old_def(person, year, m, cy_corp_size, youth)
                return claw, act
            yf2, yf2a = _cohort_flags(year - 1, c1_was_youth)
            yf3, yf3a = _cohort_flags(year - 2, c2_was_youth)
        else:
            yf1 = yf2 = yf3 = yf2a = yf3a = False

        youth_flags_b1.append(yf1)
        youth_flags_b2.append(yf2)
        youth_flags_b3.append(yf3)
        youth_flags_b2a.append(yf2a)
        youth_flags_b3a.append(yf3a)

    row_sum_frac = sum((Fraction(str(v)) for v in months if v), Fraction(0))
    yth_b1_frac = sum((Fraction(str(v)) for v, f in zip(months, youth_flags_b1) if v and f), Fraction(0))
    yth_b2_frac = sum((Fraction(str(v)) for v, f in zip(months, youth_flags_b2) if v and f), Fraction(0))
    yth_b3_frac = sum((Fraction(str(v)) for v, f in zip(months, youth_flags_b3) if v and f), Fraction(0))
    yth_b2a_frac = sum((Fraction(str(v)) for v, f in zip(months, youth_flags_b2a) if v and f), Fraction(0))
    yth_b3a_frac = sum((Fraction(str(v)) for v, f in zip(months, youth_flags_b3a) if v and f), Fraction(0))

    row_sum = float(row_sum_frac)
    yth_sum_b1 = float(yth_b1_frac)
    yth_sum_b2 = float(yth_b2_frac)
    yth_sum_b3 = float(yth_b3_frac)

    gen_sum_b1 = round(max(0.0, row_sum - yth_sum_b1), 4)
    gen_sum_b2 = round(max(0.0, row_sum - yth_sum_b2), 4)
    gen_sum_b3 = round(max(0.0, row_sum - yth_sum_b3), 4)

    # ── A방식(합계 후 절사 시 개인행 참고용 반올림) vs B방식(사원별 100분의 1 미만 절사, 청년등외 = 전체 - 청년등) 동시 산출 ──
    # B방식 사원별 절사값 (별지 제10호의10서식 ⑩ = ② − ⑨)
    B_b1_reg = trunc2(row_sum_frac / months_in_year)
    B_b1_yth = trunc2(yth_b1_frac / months_in_year)
    B_b1_gen = round(max(0.0, B_b1_reg - B_b1_yth), 2)

    B_b2_reg = B_b1_reg
    B_b2_yth = trunc2(yth_b2_frac / months_in_year)
    B_b2_gen = round(max(0.0, B_b2_reg - B_b2_yth), 2)

    B_b3_reg = B_b1_reg
    B_b3_yth = trunc2(yth_b3_frac / months_in_year)
    B_b3_gen = round(max(0.0, B_b3_reg - B_b3_yth), 2)

    B_b2_yth_act = trunc2(yth_b2a_frac / months_in_year)
    B_b3_yth_act = trunc2(yth_b3a_frac / months_in_year)

    # A방식 개인행 표시값 (연도 합계에서 1회 절사하므로 개인행은 소수 둘째 자리 반올림 참고값)
    A_b1_reg = round(row_sum / months_in_year, 2)
    A_b1_yth = round(yth_sum_b1 / months_in_year, 2)
    A_b1_gen = round(gen_sum_b1 / months_in_year, 2)

    A_b2_reg = A_b1_reg
    A_b2_yth = round(yth_sum_b2 / months_in_year, 2)
    A_b2_gen = round(gen_sum_b2 / months_in_year, 2)

    A_b3_reg = A_b1_reg
    A_b3_yth = round(yth_sum_b3 / months_in_year, 2)
    A_b3_gen = round(gen_sum_b3 / months_in_year, 2)

    A_b2_yth_act = round(float(yth_b2a_frac) / months_in_year, 2)
    A_b3_yth_act = round(float(yth_b3a_frac) / months_in_year, 2)

    # 코호트 연도별 방식 선택 규칙 (calc_method_for 일원화)
    # # 확인 필요: '26.3월 국세청 안내 신뢰보호 원칙 연장 적용 (2026년 이후 평가연도에서 2024년 이하 코호트에 A를 계속 적용)
    m_b1 = calc_method_for(int(year))
    m_b2 = calc_method_for(int(year) - 1)
    m_b3 = calc_method_for(int(year) - 2)

    if m_b1 == "B":
        b1_reg_indiv, b1_yth_indiv, b1_gen_indiv = B_b1_reg, B_b1_yth, B_b1_gen
        b4_reg_trunc, b4_yth_trunc, b4_gen_trunc = A_b1_reg, A_b1_yth, A_b1_gen
    else:
        b1_reg_indiv, b1_yth_indiv, b1_gen_indiv = A_b1_reg, A_b1_yth, A_b1_gen
        b4_reg_trunc, b4_yth_trunc, b4_gen_trunc = B_b1_reg, B_b1_yth, B_b1_gen

    if m_b2 == "B":
        b2_reg_indiv, b2_yth_indiv, b2_gen_indiv = B_b2_reg, B_b2_yth, B_b2_gen
        b2_yth_act_indiv = B_b2_yth_act
    else:
        b2_reg_indiv, b2_yth_indiv, b2_gen_indiv = A_b2_reg, A_b2_yth, A_b2_gen
        b2_yth_act_indiv = A_b2_yth_act

    if m_b3 == "B":
        b3_reg_indiv, b3_yth_indiv, b3_gen_indiv = B_b3_reg, B_b3_yth, B_b3_gen
        b3_yth_act_indiv = B_b3_yth_act
    else:
        b3_reg_indiv, b3_yth_indiv, b3_gen_indiv = A_b3_reg, A_b3_yth, A_b3_gen
        b3_yth_act_indiv = A_b3_yth_act

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
        "youth_flags_b2a": youth_flags_b2a,
        "youth_flags_b3a": youth_flags_b3a,
        "youth_sum_b2a": float(yth_b2a_frac),
        "youth_sum_b3a": float(yth_b3a_frac),
        "b2_yth_act": b2_yth_act_indiv,
        "b3_yth_act": b3_yth_act_indiv,
        "gen_sum_b1": gen_sum_b1,
        "gen_sum_b2": gen_sum_b2,
        "gen_sum_b3": gen_sum_b3,
        # A·B 양쪽 모두 보관
        "A_b1_yth": A_b1_yth,
        "A_b1_gen": A_b1_gen,
        "A_b1_reg": A_b1_reg,
        "B_b1_yth": B_b1_yth,
        "B_b1_gen": B_b1_gen,
        "B_b1_reg": B_b1_reg,
        "A_b2_yth": A_b2_yth,
        "A_b2_gen": A_b2_gen,
        "A_b2_reg": A_b2_reg,
        "B_b2_yth": B_b2_yth,
        "B_b2_gen": B_b2_gen,
        "B_b2_reg": B_b2_reg,
        "A_b3_yth": A_b3_yth,
        "A_b3_gen": A_b3_gen,
        "A_b3_reg": A_b3_reg,
        "B_b3_yth": B_b3_yth,
        "B_b3_gen": B_b3_gen,
        "B_b3_reg": B_b3_reg,
        # 선택된 방식(calc_method_for) 기본값
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
        "_class_diff_msg": str(yrec.get("_class_diff_msg") or ""),
    }


def year_totals(computed_rows: list[dict], months_in_year: int, year: int | None = None) -> dict:
    """
    과세연도 전체 상시근로자 수 및 우측 블록 집계:
    - 모든 연도·모든 열(당해 공제 b1, 사후관리 b2·b3)에 대해
      A값(월별 합계 ÷ 개월수 후 1회 절사)과 B값(사원별 절사 후 합계, 청년등외 = 전체 - 청년등)을 함께 계산해 보관합니다.
    - 기본 표시·적용값은 `calc_method_for(cohort_year)` 규칙으로 선택합니다:
      * b1(당해 연도 자체): calc_method_for(eval_yr)
      * b2(1차 사후관리): calc_method_for(eval_yr - 1)
      * b3(2차 사후관리): calc_method_for(eval_yr - 2)
      # 확인 필요: '26.3월 국세청 안내 신뢰보호 원칙 연장 적용 (2026년 이후 평가연도에서 2024년 이하 코호트에 A를 계속 적용)
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
    yth_b2a_f = sum((Fraction(str(r.get("youth_sum_b2a", r.get("youth_sum_b2", r["youth_sum"])))) for r in computed_rows), Fraction(0))
    yth_b3a_f = sum((Fraction(str(r.get("youth_sum_b3a", r.get("youth_sum_b3", r["youth_sum"])))) for r in computed_rows), Fraction(0))

    reg_total = float(reg_total_f)
    yth_total_b1 = float(yth_b1_f)
    non_total_b1 = round(reg_total - yth_total_b1, 4)

    yth_total_b2 = float(yth_b2_f)
    non_total_b2 = round(max(0.0, reg_total - yth_total_b2), 4)

    yth_total_b3 = float(yth_b3_f)
    non_total_b3 = round(max(0.0, reg_total - yth_total_b3), 4)

    eval_yr = int(year) if year is not None else int((computed_rows[0].get("_eval_year") if computed_rows else 2026) or 2026)

    # ── 1) A방식(기존: 매월 말 상시근로자 수의 합계 ÷ 과세연도 개월수 → 100분의 1 미만 절사) ──
    A_b1_reg = trunc2(reg_total_f / n)
    A_b1_yth = trunc2(yth_b1_f / n)
    A_b1_gen = round(max(0.0, A_b1_reg - A_b1_yth), 2)

    A_b2_reg = A_b1_reg
    A_b2_yth = trunc2(yth_b2_f / n)
    A_b2_gen = round(max(0.0, A_b2_reg - A_b2_yth), 2)
    A_b2_yth_act = trunc2(yth_b2a_f / n)

    A_b3_reg = A_b1_reg
    A_b3_yth = trunc2(yth_b3_f / n)
    A_b3_gen = round(max(0.0, A_b3_reg - A_b3_yth), 2)
    A_b3_yth_act = trunc2(yth_b3a_f / n)

    # ── 2) B방식(현행: [각 상시근로자 근무개월수 ÷ 과세연도 개월수 → 100분의 1 미만 절사]의 합계, 청년등외 = 전체 - 청년등) ──
    B_b1_reg = round(sum(trunc2(Fraction(str(r["row_sum"])) / n) for r in computed_rows), 2)
    B_b1_yth = round(sum(trunc2(Fraction(str(r["youth_sum"])) / n) for r in computed_rows), 2)
    B_b1_gen = round(max(0.0, B_b1_reg - B_b1_yth), 2)

    B_b2_reg = B_b1_reg
    B_b2_yth = round(sum(trunc2(Fraction(str(r.get("youth_sum_b2", r["youth_sum"]))) / n) for r in computed_rows), 2)
    B_b2_gen = round(max(0.0, B_b2_reg - B_b2_yth), 2)
    B_b2_yth_act = round(
        sum(trunc2(Fraction(str(r.get("youth_sum_b2a", r.get("youth_sum_b2", r["youth_sum"])))) / n) for r in computed_rows),
        2,
    )

    B_b3_reg = B_b1_reg
    B_b3_yth = round(sum(trunc2(Fraction(str(r.get("youth_sum_b3", r["youth_sum"]))) / n) for r in computed_rows), 2)
    B_b3_gen = round(max(0.0, B_b3_reg - B_b3_yth), 2)
    B_b3_yth_act = round(
        sum(trunc2(Fraction(str(r.get("youth_sum_b3a", r.get("youth_sum_b3", r["youth_sum"])))) / n) for r in computed_rows),
        2,
    )

    # ── 3) 방식 선택 규칙(calc_method_for)에 따른 기본값 및 비교값 설정 ──
    # # 확인 필요: '26.3월 국세청 안내 신뢰보호 원칙 연장 적용 (2026년 이후 평가연도에서 2024년 이하 코호트에 A를 계속 적용)
    m_b1 = calc_method_for(eval_yr)
    m_b2 = calc_method_for(eval_yr - 1)
    m_b3 = calc_method_for(eval_yr - 2)

    if m_b1 == "B":
        b1_reg, b1_yth, b1_gen = B_b1_reg, B_b1_yth, B_b1_gen
        b4_reg, b4_yth, b4_gen = A_b1_reg, A_b1_yth, A_b1_gen
    else:
        b1_reg, b1_yth, b1_gen = A_b1_reg, A_b1_yth, A_b1_gen
        b4_reg, b4_yth, b4_gen = B_b1_reg, B_b1_yth, B_b1_gen

    if m_b2 == "B":
        b2_reg, b2_yth, b2_gen, b2_yth_act = B_b2_reg, B_b2_yth, B_b2_gen, B_b2_yth_act
    else:
        b2_reg, b2_yth, b2_gen, b2_yth_act = A_b2_reg, A_b2_yth, A_b2_gen, A_b2_yth_act

    if m_b3 == "B":
        b3_reg, b3_yth, b3_gen, b3_yth_act = B_b3_reg, B_b3_yth, B_b3_gen, B_b3_yth_act
    else:
        b3_reg, b3_yth, b3_gen, b3_yth_act = A_b3_reg, A_b3_yth, A_b3_gen, A_b3_yth_act

    return {
        "months_in_year": n,
        "eval_year": eval_yr,
        "calc_method_b1": m_b1,
        "calc_method_b2": m_b2,
        "calc_method_b3": m_b3,
        "calc_badge_b1": calc_method_badge_label(m_b1),
        "calc_badge_b2": calc_method_badge_label(m_b2),
        "calc_badge_b3": calc_method_badge_label(m_b3),
        "ab_diff_b1": (abs(A_b1_reg - B_b1_reg) >= 0.01 or abs(A_b1_yth - B_b1_yth) >= 0.01),
        "ab_diff_b2": (abs(A_b2_reg - B_b2_reg) >= 0.01 or abs(A_b2_yth - B_b2_yth) >= 0.01),
        "ab_diff_b3": (abs(A_b3_reg - B_b3_reg) >= 0.01 or abs(A_b3_yth - B_b3_yth) >= 0.01),
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
        # A방식(합계 후 절사) 전체 보관
        "A_상시_평균": A_b1_reg,
        "A_청년등_평균": A_b1_yth,
        "A_청년외_평균": A_b1_gen,
        "A_b1_yth": A_b1_yth,
        "A_b1_gen": A_b1_gen,
        "A_b1_reg": A_b1_reg,
        "A_b2_yth": A_b2_yth,
        "A_b2_gen": A_b2_gen,
        "A_b2_reg": A_b2_reg,
        "A_b2_yth_act": A_b2_yth_act,
        "A_b3_yth": A_b3_yth,
        "A_b3_gen": A_b3_gen,
        "A_b3_reg": A_b3_reg,
        "A_b3_yth_act": A_b3_yth_act,
        # B방식(사원별 절사 후 합계) 전체 보관
        "B_상시_평균": B_b1_reg,
        "B_청년등_평균": B_b1_yth,
        "B_청년외_평균": B_b1_gen,
        "B_b1_yth": B_b1_yth,
        "B_b1_gen": B_b1_gen,
        "B_b1_reg": B_b1_reg,
        "B_b2_yth": B_b2_yth,
        "B_b2_gen": B_b2_gen,
        "B_b2_reg": B_b2_reg,
        "B_b2_yth_act": B_b2_yth_act,
        "B_b3_yth": B_b3_yth,
        "B_b3_gen": B_b3_gen,
        "B_b3_reg": B_b3_reg,
        "B_b3_yth_act": B_b3_yth_act,
        # 기본 선택값(calc_method_for)
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
        "b2_yth_act": b2_yth_act,
        "b3_yth_act": b3_yth_act,
        "b4_yth": b4_yth,
        "b4_gen": b4_gen,
        "b4_reg": b4_reg,
    }


def regular_excluding_part_time(computed_rows: list[dict], emp_types: list[str], months_in_year: int, year: int | None = None) -> float:
    n = max(1, min(12, int(months_in_year or 12)))
    eval_yr = int(year) if year is not None else int((computed_rows[0].get("_eval_year") if computed_rows else 2026) or 2026)
    m = calc_method_for(eval_yr)
    if m == "B":
        return round(
            sum(
                trunc2(Fraction(str(r["row_sum"])) / n)
                for r, et in zip(computed_rows, emp_types)
                if et not in (R.EMP_PT_050, R.EMP_PT_075)
            ),
            2,
        )
    total_f = sum(
        (Fraction(str(r["row_sum"])) for r, et in zip(computed_rows, emp_types) if et not in (R.EMP_PT_050, R.EMP_PT_075)),
        Fraction(0),
    )
    return trunc2(total_f / n)