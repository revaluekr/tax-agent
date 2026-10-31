# -*- coding: utf-8 -*-
"""
[모듈 3/4] 통합고용세액공제 — 세액공제(구법·2026 신법 A+B+C) 및 1·2차 사후관리(연속공제·추징) 계산 엔진 (hc_credit_calc.py)
- 매년 세법 개정으로 단가·사후관리 산식·최소고용증가인원(중견 5명/대기업 10명) 등이 변경될 때 이 파일만 수정·덮어쓰기할 수 있습니다.
"""
from __future__ import annotations

from typing import Any

from . import rules as R
from .hc_eligibility import (
    NEW_TENURE_RULE_FROM,
    calc_method_badge_label,
    calc_method_for,
    valid_comparison_years_for_new_credit,
)


def _pick_summary_by_method(d: dict[str, Any] | None, method: str = "B", block: str = "b1") -> dict[str, float]:
    """
    연도별 집계 딕셔너리(d)에서 지정된 계산방식(method="A"|"B")과 블록(block="b1"|"b2"|"b3"|"nr")에 맞는
    (reg, yth, gen, yth_act) 인원수를 반환합니다.
    - A·B 별도 키(예: A_b1_reg / B_b1_reg, nr_A_상시_평균 / nr_B_상시_평균)가 있으면 최우선 사용하고,
      단일 키만 주어진 수동 딕셔너리의 경우 기존 키로 안전하게 폴백합니다.
    """
    if not isinstance(d, dict):
        return {"reg": 0.0, "yth": 0.0, "gen": 0.0, "yth_act": 0.0}
    m = "A" if str(method).upper() == "A" else "B"

    if block == "nr":
        if d.get(f"nr_{m}_상시_평균") is not None:
            reg = float(d.get(f"nr_{m}_상시_평균") or 0.0)
            yth = float(d.get(f"nr_{m}_청년등_평균") or 0.0)
            gen = float(d.get(f"nr_{m}_청년외_평균", round(max(0.0, reg - yth), 2)) or 0.0)
            return {"reg": reg, "yth": yth, "gen": gen, "yth_act": yth}
        if d.get("nr_상시_평균") is not None:
            reg = float(d.get("nr_상시_평균") or 0.0)
            yth = float(d.get("nr_청년등_평균") or 0.0)
            gen = float(d.get("nr_청년외_평균", round(max(0.0, reg - yth), 2)) or 0.0)
            return {"reg": reg, "yth": yth, "gen": gen, "yth_act": yth}
        return _pick_summary_by_method(d, method=m, block="b1")

    if block in ("b2", "b3"):
        if d.get(f"{m}_{block}_reg") is not None:
            reg = float(d.get(f"{m}_{block}_reg") or 0.0)
            yth = float(d.get(f"{m}_{block}_yth") or 0.0)
            gen = float(d.get(f"{m}_{block}_gen", round(max(0.0, reg - yth), 2)) or 0.0)
            ya = float(d.get(f"{m}_{block}_yth_act", yth) if d.get(f"{m}_{block}_yth_act") is not None else yth)
            return {"reg": reg, "yth": yth, "gen": gen, "yth_act": ya}
        reg = float(d.get(f"{block}_reg", d.get("상시_평균", d.get("regular", d.get("b1_reg", 0.0)))) or 0.0)
        yth = float(d.get(f"{block}_yth", d.get("청년등_평균", d.get("youth", d.get("b1_yth", 0.0)))) or 0.0)
        gen = float(d.get(f"{block}_gen", round(max(0.0, reg - yth), 2)) or 0.0)
        ya = float(d.get(f"{block}_yth_act", yth) if d.get(f"{block}_yth_act") is not None else yth)
        return {"reg": reg, "yth": yth, "gen": gen, "yth_act": ya}

    # block == "b1": 만약 사용자가 수동 테스트용으로 dict(summaries[y], 상시_평균=...)처럼 상시_평균만 오버라이드한 경우를 감지
    has_ab = (d.get(f"{m}_b1_reg") is not None) or (d.get(f"{m}_상시_평균") is not None)
    if has_ab:
        def_m = d.get("calc_method_b1")
        top_reg = d.get("상시_평균", d.get("regular"))
        def_reg = d.get(f"{def_m}_b1_reg", d.get(f"{def_m}_상시_평균")) if def_m in ("A", "B") else None
        # 상시_평균이 기본 선택 방식 값과 다르게 외부에서 직접 덮어씌워진 경우(단위 테스트 시뮬레이션 등) 오버라이드 값 존중
        if top_reg is not None and def_reg is not None and abs(float(top_reg) - float(def_reg)) >= 1e-6:
            reg = float(top_reg or 0.0)
            yth = float(d.get("청년등_평균", d.get("youth", 0.0)) or 0.0)
            gen = float(d.get("청년외_평균", d.get("non_youth", round(max(0.0, reg - yth), 2))) or 0.0)
            return {"reg": reg, "yth": yth, "gen": gen, "yth_act": yth}
        reg = float(d.get(f"{m}_b1_reg", d.get(f"{m}_상시_평균", 0.0)) or 0.0)
        yth = float(d.get(f"{m}_b1_yth", d.get(f"{m}_청년등_평균", 0.0)) or 0.0)
        gen = float(d.get(f"{m}_b1_gen", d.get(f"{m}_청년외_평균", round(max(0.0, reg - yth), 2))) or 0.0)
        return {"reg": reg, "yth": yth, "gen": gen, "yth_act": yth}

    reg = float(d.get("상시_평균", d.get("regular", d.get("b1_reg", 0.0))) or 0.0)
    yth = float(d.get("청년등_평균", d.get("youth", d.get("b1_yth", 0.0))) or 0.0)
    gen = float(d.get("청년외_평균", d.get("non_youth", d.get("b1_gen", round(max(0.0, reg - yth), 2)))) or 0.0)
    return {"reg": reg, "yth": yth, "gen": gen, "yth_act": yth}


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
    corp_size_by_year: dict[int | str, str] | None = None,
) -> dict[str, Any]:
    """
    2026년 이후 신법(조특법 제29조의8 제1항) A·B·C 티어 세액공제 산출.
    - 적용 방식: `calc_method_for(tax_year)` -> "B" (해당·비교연도 모두 B방식 사원별 절사 후 합계 인원 적용)
    """
    t = int(tax_year)
    m_abc = calc_method_for(t, eval_year=t)
    comp = valid_comparison_years_for_new_credit(t)

    def _sz_for(y: int | None) -> str:
        if y is not None and isinstance(corp_size_by_year, dict):
            v = corp_size_by_year.get(int(y)) or corp_size_by_year.get(str(y))
            if v:
                return R.normalize_corp_size(v, corp_size)
        if y is not None:
            d = summaries_by_year.get(int(y)) or {}
            if d.get("corp_size"):
                return R.normalize_corp_size(d.get("corp_size"), corp_size)
        return R.normalize_corp_size(corp_size, "중소기업")

    def _s(y: int | None, is_comp: bool = False) -> dict[str, float]:
        if y is None:
            return {"reg": 0.0, "yth": 0.0, "gen": 0.0, "b2_yth": 0.0, "b3_yth": 0.0, "has_data": False}
        d = summaries_by_year.get(y) or {}
        if "regular" in d and "youth" in d and (not is_comp or d.get("_nr_applied")):
            reg = float(d.get("regular") or 0.0)
            yth = float(d.get("youth") or 0.0)
        else:
            picked = _pick_summary_by_method(d, method=m_abc, block=("nr" if is_comp else "b1"))
            reg, yth = picked["reg"], picked["yth"]
        gen = round(max(0.0, reg - yth), 2)
        b2_y = float(d.get("b2_yth", yth) or 0.0)
        b3_y = float(d.get("b3_yth", b2_y) or 0.0)
        has_d = bool(d.get("has_data", reg > 0 or yth > 0))
        return {"reg": reg, "yth": yth, "gen": gen, "b2_yth": b2_y, "b3_yth": b3_y, "has_data": has_d}

    s_t = _s(t, is_comp=False)
    s_t1 = _s(comp.get("A"), is_comp=True)
    s_t2 = _s(comp.get("B"), is_comp=True)
    s_t3 = _s(comp.get("C"), is_comp=True)

    tiers: dict[str, dict[str, Any]] = {}

    sz_a = _sz_for(t)
    rates_a = get_unit_rates(sz_a, is_capital, scheme="new_2026", retention_year=1)
    if comp.get("A") is not None:
        inc_a = calc_increase_with_cap(s_t["reg"], s_t["yth"], s_t1["reg"], s_t1["yth"])
        hurdle_a = calc_minimum_hurdle_deduction_2026(
            sz_a, inc_a["total_inc"], inc_a["youth_inc"], inc_a["non_youth_inc"], retention_year=1
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
        hurdle_a = calc_minimum_hurdle_deduction_2026(sz_a, 0.0, 0.0, 0.0, retention_year=1)
        item1_won = item2_won = item3_won = net_a_won = 0

    tiers["A"] = {
        "comp_year": comp.get("A"),
        "retention_year": 1,
        "corp_size": sz_a,
        "calc_method": m_abc,
        "rates": rates_a,
        "cur_reg": s_t["reg"],
        "cur_yth": s_t["yth"],
        "comp_reg": s_t1["reg"],
        "comp_yth": s_t1["yth"],
        "total_inc": inc_a["total_inc"],
        "youth_inc": inc_a["youth_inc"],
        "non_youth_inc": inc_a["non_youth_inc"],
        "hurdle": hurdle_a,
        "item1_youth_won": item1_won,
        "item2_non_youth_won": item2_won,
        "item3_deduction_won": item3_won,
        "credit_won": net_a_won,
    }

    # 확인 필요: 신법(2026년 이후, 조세특례제한법 제29조의8 제1항) B(2년차)·C(3년차) 유지분 공제단가는
    # 법문상 "내국인의 해당 과세연도의 ... 상시근로자 수가 직전 3개 과세연도의 상시근로자 수보다 증가한 경우 다음 각 호에 따른 금액을 ... 공제한다"로만 규정되어 있어,
    # 최초 증가연도(T-1·T-2)와 당해 과세연도(T) 사이에 기업규모가 변동된 경우 '해당 과세연도(T) 기업규모' 기준인지 '최초 증가연도(T-1·T-2) 기업규모' 기준인지
    # 명시적 조문·유권해석이 아직 없으므로 확인 전 기본값으로 당해 과세연도(t)의 기업규모를 적용합니다.
    sz_b = _sz_for(t)
    rates_b = get_unit_rates(sz_b, is_capital, scheme="new_2026", retention_year=2)
    if comp.get("B") is not None and s_t2["has_data"]:
        tot_b = round(max(0.0, min(s_t["reg"], s_t1["reg"]) - s_t2["reg"]), 2)
        yth_b = round(min(tot_b, max(0.0, min(s_t["yth"], s_t1["yth"]) - s_t2["yth"])), 2)
        raw_gen_b = round(max(0.0, min(s_t["gen"], s_t1["gen"]) - s_t2["gen"]), 2)
        gen_b = round(min(tot_b, max(0.0, tot_b - yth_b), raw_gen_b), 2)
        hurdle_b = calc_minimum_hurdle_deduction_2026(sz_b, tot_b, yth_b, gen_b, retention_year=2)
        if hurdle_b["hurdle_met"]:
            b1_won = int(round(yth_b * rates_b["청년등"] * 10_000))
            b2_won = int(round(gen_b * rates_b["청년등외"] * 10_000))
            b3_won = hurdle_b["deduction_won"]
            net_b_won = max(0, b1_won + b2_won - b3_won)
        else:
            b1_won = b2_won = b3_won = net_b_won = 0
    else:
        tot_b = yth_b = gen_b = 0.0
        hurdle_b = calc_minimum_hurdle_deduction_2026(sz_b, 0.0, 0.0, 0.0, retention_year=2)
        b1_won = b2_won = b3_won = net_b_won = 0

    tiers["B"] = {
        "comp_year": comp.get("B"),
        "retention_year": 2,
        "corp_size": sz_b,
        "calc_method": m_abc,
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

    # 확인 필요: 신법 C(3년차) 단가 기준 기업규모 (기본값: 당해 과세연도 t 기업규모 적용)
    sz_c = _sz_for(t)
    rates_c = get_unit_rates(sz_c, is_capital, scheme="new_2026", retention_year=3)
    if comp.get("C") is not None and s_t3["has_data"] and (rates_c["청년등"] > 0 or rates_c["청년등외"] > 0):
        tot_c = round(max(0.0, min(s_t["reg"], s_t1["reg"], s_t2["reg"]) - s_t3["reg"]), 2)
        yth_c = round(min(tot_c, max(0.0, min(s_t["yth"], s_t1["yth"], s_t2["yth"]) - s_t3["yth"])), 2)
        raw_gen_c = round(max(0.0, min(s_t["gen"], s_t1["gen"], s_t2["gen"]) - s_t3["gen"]), 2)
        gen_c = round(min(tot_c, max(0.0, tot_c - yth_c), raw_gen_c), 2)
        hurdle_c = calc_minimum_hurdle_deduction_2026(sz_c, tot_c, yth_c, gen_c, retention_year=3)
        if hurdle_c["hurdle_met"]:
            c1_won = int(round(yth_c * rates_c["청년등"] * 10_000))
            c2_won = int(round(gen_c * rates_c["청년등외"] * 10_000))
            c3_won = hurdle_c["deduction_won"]
            net_c_won = max(0, c1_won + c2_won - c3_won)
        else:
            c1_won = c2_won = c3_won = net_c_won = 0
    else:
        tot_c = yth_c = gen_c = 0.0
        hurdle_c = calc_minimum_hurdle_deduction_2026(sz_c, 0.0, 0.0, 0.0, retention_year=3)
        c1_won = c2_won = c3_won = net_c_won = 0

    tiers["C"] = {
        "comp_year": comp.get("C"),
        "retention_year": 3,
        "corp_size": sz_c,
        "calc_method": m_abc,
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
        "calc_method": m_abc,
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
    cur_pm_yth_actual: float | None = None,
    prev_pm_yth_actual: float | None = None,
) -> dict[str, Any]:
    """
    [2023~2025년 귀속 공제분의 1차·2차 사후관리(2·3차년도 연속공제 및 추가납부세액) 정밀 산출]
    - 상시근로자 수 비교 방식: `calc_method_for(cohort_year)` (2024년 이하 코호트 A방식, 2025년 코호트 B방식)
      # 확인 필요: '26.3월 국세청 안내 신뢰보호 원칙 연장 적용 (2026년 이후 평가연도에서 2024년 이하 코호트에 A를 계속 적용)
    """
    elapsed = int(eval_year) - int(cohort_year)
    coh_method = calc_method_for(cohort_year, eval_year=eval_year)
    rates = get_unit_rates(corp_size, is_capital, scheme="legacy")
    yth_rate = rates["청년등"]
    gen_rate = rates["청년등외"]
    diff_rate = max(0, yth_rate - gen_rate)

    is_large = R.normalize_corp_size(corp_size) in ("일반기업", "대기업")
    max_credit_years = 2 if is_large else 3
    can_receive_continued = (1 <= elapsed < max_credit_years) and (init_yth_inc + init_gen_inc > 0)

    if elapsed not in (1, 2) or (init_yth_inc <= 0 and init_gen_inc <= 0):
        return {
            "cohort_year": cohort_year,
            "eval_year": eval_year,
            "elapsed_year": elapsed,
            "calc_method": coh_method,
            "calc_badge": calc_method_badge_label(coh_method, eval_year=eval_year),
            "active": False,
            "case_code": "해당없음",
            "case_title": f"{cohort_year}년 귀속분 공제이력 없음 (사후관리 대상 아님)",
            "continued_credit_won": 0,
            "clawback_raw_cumulative_won": 0,
            "prior_clawback_deducted_won": 0,
            "clawback_gross_won": 0,
            "carryforward_offset_won": 0,
            "clawback_net_payable_won": 0,
            "cap_applied": False,
            "claimed_cap_won": 0,
            "retained_yth_inc": 0.0,
            "retained_gen_inc": 0.0,
            "reg_decrease": 0.0,
            "yth_decrease": 0.0,
            "init_reg": round(float(init_reg or 0.0), 2),
            "init_yth": round(float(init_yth or 0.0), 2),
            "init_yth_inc": round(float(init_yth_inc or 0.0), 2),
            "init_gen_inc": round(float(init_gen_inc or 0.0), 2),
            "cur_pm_reg": round(float(cur_pm_reg or 0.0), 2),
            "cur_pm_yth": round(float(cur_pm_yth or 0.0), 2),
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
            prior_years_claimed_count = 2 if y1_continued_credit_won > 0 else 1
        elif prev_pm_reg is not None and prev_pm_reg < init_reg:
            prior_years_claimed_count = 1
        else:
            prior_years_claimed_count = 2

    yth_act = cur_pm_yth if cur_pm_yth_actual is None else cur_pm_yth_actual
    full_man = init_yth_inc * yth_rate + init_gen_inc * gen_rate
    conv_man = (init_yth_inc + init_gen_inc) * gen_rate
    stopped_now = round(yth_act - init_yth, 2) < 0
    stopped_before = False
    y1_halted = False
    if elapsed == 2:
        if (y1_continued_credit_won is not None and y1_continued_credit_won == 0) or (
            prev_pm_reg is not None and prev_pm_reg < init_reg
        ):
            y1_halted = True
        prev_act = prev_pm_yth_actual if prev_pm_yth_actual is not None else prev_pm_yth
        if prev_act is not None and round(prev_act - init_yth, 2) < 0:
            stopped_before = True
        if y1_continued_credit_won and 0 < y1_continued_credit_won < int(round(full_man * 10_000)) - 10:
            stopped_before = True
    youth_stopped = stopped_now or stopped_before

    if reg_diff >= 0:
        if y1_halted:
            ret_yth, ret_gen, cont_man = 0.0, 0.0, 0.0
        elif youth_stopped:
            ret_yth, ret_gen = 0.0, round(init_yth_inc + init_gen_inc, 2)
            cont_man = conv_man if can_receive_continued else 0.0
        else:
            ret_yth, ret_gen = round(init_yth_inc, 2), round(init_gen_inc, 2)
            cont_man = full_man if can_receive_continued else 0.0
        if not can_receive_continued and is_large and elapsed == 2:
            cont_txt = "연속공제: 대기업(일반기업) 2년 공제기간 만료로 3차년도 연속공제 없음(0원 · 2차 사후관리 추징 요건만 점검)"
        elif y1_halted:
            cont_txt = "연속공제: 1년차 감소로 중단(0원)"
        elif youth_stopped:
            cont_txt = f"연속공제: (청년 {init_yth_inc:.2f} + 청년외 {init_gen_inc:.2f})명 × {gen_rate:,}만 = {cont_man:,.1f}만원 (청년 단가 중단)"
        else:
            cont_txt = f"연속공제: 청년 {init_yth_inc:.2f}명×{yth_rate:,}만 + 청년외 {init_gen_inc:.2f}명×{gen_rate:,}만 = {cont_man:,.1f}만원"
        if yth_diff < 0:
            case_code = "Case 3 (전체 유지·청년등만 감소)"
            case_title = "전체 상시근로자 유지 · 청년등만 감소 (청년 단가 중단 + 단가차액 추가납부)"
            capped_yth_dec = round(min(init_yth_inc, yth_dec), 2)
            raw_claw_man = capped_yth_dec * diff_rate * prior_years_claimed_count
            formula_note = (
                f"[{cohort_year}년분 {elapsed+1}차년도 · Case 3] 전체 상시 유지({cur_pm_reg:.2f} ≥ {init_reg:.2f}), "
                f"청년등 {capped_yth_dec:.2f}명 감소 → 추징(차액): {capped_yth_dec:.2f}명 × ({yth_rate:,}-{gen_rate:,})만원 × "
                f"{prior_years_claimed_count}회 = {raw_claw_man:,.1f}만원"
            )
        else:
            raw_claw_man = 0.0
            if is_large and elapsed == 2:
                case_code = "공제기간 종료(일반기업 2년) · 고용유지(추징 없음)"
                case_title = f"{cohort_year}년 귀속분 공제기간 종료(일반기업 2년) — 3차 연속공제 없음 · 2차 사후관리 고용유지(추징 없음)"
                formula_note = (
                    f"[{cohort_year}년분 3차년도(2차 사후관리)] 일반기업(대기업) 공제기간(2년) 만료로 3차 연속공제 없음(0원) / "
                    f"구 조특법 제29조의8 제2항·제3항 2년 사후관리 점검 결과 상시({cur_pm_reg:.2f} ≥ {init_reg:.2f}) 및 "
                    f"청년등({cur_pm_yth:.2f} ≥ {init_yth:.2f}) 유지 → 추가납부(추징) 0원"
                )
            elif youth_stopped and not y1_halted:
                case_code = "청년 단가 중단 (추징 없음)"
                case_title = "청년등 수가 최초공제연도보다 적어(나이 경과 등) 청년 단가 중단 · 추가납부 없음"
                why = ("1년차에 이미 청년 단가가 중단됨" if stopped_before and not stopped_now else
                       f"판정용 청년 {yth_act:.2f} < 최초 {init_yth:.2f} (나이 경과 등, 추가납부는 간주 인원 {cur_pm_yth:.2f}로 계산)")
                formula_note = f"[{cohort_year}년분 {elapsed+1}차년도] 상시 유지, {why} → 추징 0원 / {cont_txt}"
            else:
                case_code = "유지/증가"
                case_title = "전체 상시 및 청년등 인원 모두 유지 (전액 연속공제 · 추징 없음)"
                formula_note = (
                    f"[{cohort_year}년분 {elapsed+1}차년도] 상시({cur_pm_reg:.2f} ≥ {init_reg:.2f}) 및 "
                    f"청년등({yth_act:.2f} ≥ {init_yth:.2f}) 유지 → {cont_txt} / 추징 0원"
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
            # 구 조특령 제26조의8 제4항 제1호 가목2)·제2호 가목2) (법 부칙 제34조로 2024·2025년분 적용):
            #   [청년등 감소 인원(전체 감소 인원 한도) × 청년 단가] + [청년등 외 감소 인원(전체 감소 인원 한도) × 청년외 단가]
            #   감소 인원에 '최초 증가인원' 한도는 없으며, 총액은 공제받은 세액 한도(아래 claimed_cap / full_man)로만 제한.
            gen_dec = round(max(0.0, (init_reg - init_yth) - (cur_pm_reg - cur_pm_yth)), 2)
            yth_lost = round(min(reg_dec, yth_dec), 2)
            gen_lost = round(min(reg_dec, gen_dec), 2)
            total_yth_lost = yth_lost

            raw_claw_man = ((total_yth_lost * yth_rate) + (gen_lost * gen_rate)) * prior_years_claimed_count
            credited_cap_man = full_man * prior_years_claimed_count
            case2_cap_note = ""
            case2_formula_man = raw_claw_man
            if raw_claw_man > credited_cap_man + 1e-9:
                raw_claw_man = credited_cap_man
                case2_cap_note = f" → 공제받은 세액 추정 한도({credited_cap_man:,.1f}만원) 적용"
            formula_note = (
                f"[{cohort_year}년분 {elapsed+1}차년도 · Case 2] 전체 상시 {reg_dec:.2f}명 감소 > 청년등 {yth_dec:.2f}명 감소 → "
                f"연속공제 중단(0원) / 추징: [청년감소 {total_yth_lost:.2f}명×{yth_rate:,}만 + "
                f"청년외 감소 {gen_lost:.2f}명×{gen_rate:,}만] × {prior_years_claimed_count}년 = {case2_formula_man:,.1f}만원"
                + case2_cap_note
            )

    continued_credit_won = int(round(cont_man * 10_000))
    raw_clawback_won = int(round(raw_claw_man * 10_000))

    claimed_cap = max(0, int(init_credit_claimed_won or 0))
    if elapsed == 2 and claimed_cap > 0:
        if y1_continued_credit_won is not None and y1_continued_credit_won > 0:
            claimed_cap = claimed_cap + int(y1_continued_credit_won)
        elif y1_continued_credit_won is None and prior_years_claimed_count == 2:
            y1_est_cap = int(round((conv_man if stopped_before else full_man) * 10_000))
            claimed_cap = claimed_cap + (y1_est_cap if y1_est_cap > 0 else claimed_cap)

    cap_applied = False
    if claimed_cap > 0:
        if raw_clawback_won > claimed_cap:
            cap_applied = True
        capped_cumulative_claw_won = min(raw_clawback_won, claimed_cap)
    else:
        capped_cumulative_claw_won = raw_clawback_won

    # 6-6. 구법 추징 산식 문구가 한도 적용 전 금액을 보여주고 결과는 한도 적용 후 금액인 경우 산식 끝에 명시
    if cap_applied:
        formula_note += f" → 기공제세액({claimed_cap:,}원) 한도 적용"
    if reg_diff >= 0 and yth_diff < 0:
        formula_note += f" / {cont_txt}"

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
        "calc_method": coh_method,
        "calc_badge": calc_method_badge_label(coh_method, eval_year=eval_year),
        "corp_size": R.normalize_corp_size(corp_size),
        "active": True,
        "case_code": case_code,
        "case_title": case_title,
        "continued_credit_won": continued_credit_won,
        "clawback_raw_cumulative_won": raw_clawback_won,
        "prior_clawback_deducted_won": prior_deducted_won,
        "clawback_gross_won": clawback_gross_won,
        "carryforward_offset_won": carryforward_offset_won,
        "clawback_net_payable_won": clawback_net_payable_won,
        "cap_applied": cap_applied,
        "claimed_cap_won": claimed_cap,
        "retained_yth_inc": ret_yth,
        "retained_gen_inc": ret_gen,
        "reg_decrease": reg_dec,
        "yth_decrease": yth_dec,
        "init_reg": round(float(init_reg or 0.0), 2),
        "init_yth": round(float(init_yth or 0.0), 2),
        "init_yth_inc": round(float(init_yth_inc or 0.0), 2),
        "init_gen_inc": round(float(init_gen_inc or 0.0), 2),
        "cur_pm_reg": round(float(cur_pm_reg or 0.0), 2),
        "cur_pm_yth": round(float(cur_pm_yth or 0.0), 2),
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
    corp_size_by_year: dict[int | str, str] | None = None,
) -> dict[str, Any]:
    """
    [선택된 귀속사업연도(2024~2028)의 통합고용세액공제 종합 계산 패키지 — A/B 계산방식 일원화(calc_method_for) 완벽 반영]
    - 당해 연도 1차 공제(구법) 및 신법 A·B·C의 해당·비교연도 인원: `calc_method_for(tax_year)` (2025년 이후 "B")
    - 상시근로자 현황 표시(직전전·직전·해당) 및 추가공제 요건(해당·직전): `calc_method_for(tax_year)` (2025년 이후 "B")
    - 구법 코호트의 사후관리·연속공제 비교(최초 공제연도 인원 ↔ 평가연도 인원): `calc_method_for(cohort_year)`로 양쪽 모두 같은 방식 적용
      # 확인 필요: '26.3월 국세청 안내 신뢰보호 원칙 연장 적용 (2026년 이후 평가연도에서 2024년 이하 코호트에 A를 계속 적용)
    """
    t = int(tax_year)
    cur_method = calc_method_for(t, eval_year=t)
    pf = prior_filings or {}
    add_in = additional_inputs or {}
    basis = R.PM_BASIS_RECALC if pm_basis == R.PM_BASIS_RECALC else R.PM_BASIS_FILED

    def _sz_for(y: int) -> str:
        if isinstance(corp_size_by_year, dict):
            v = corp_size_by_year.get(int(y)) or corp_size_by_year.get(str(y))
            if v:
                return R.normalize_corp_size(v, corp_size)
        pf_y = pf.get(int(y)) or pf.get(str(y)) or {}
        if isinstance(pf_y, dict) and pf_y.get("corp_size"):
            return R.normalize_corp_size(pf_y.get("corp_size"), corp_size)
        s_y = summaries.get(int(y)) or {}
        if isinstance(s_y, dict) and s_y.get("corp_size"):
            return R.normalize_corp_size(s_y.get("corp_size"), corp_size)
        return R.normalize_corp_size(corp_size, "중소기업")

    cur_corp_size = _sz_for(t)
    corp_size_map_resolved = {y_k: _sz_for(y_k) for y_k in (t - 3, t - 2, t - 1, t)}

    def _s(y: int, target_method: str | None = None) -> dict[str, Any]:
        d = summaries.get(y) or {}
        n_m = int(d.get("months_in_year", 12) or 12)
        use_m = target_method or calc_method_for(y, eval_year=y)
        p_b1 = _pick_summary_by_method(d, method=use_m, block="b1")
        reg, yth, non_y = p_b1["reg"], p_b1["yth"], p_b1["gen"]

        p_A = _pick_summary_by_method(d, method="A", block="b1")
        p_B = _pick_summary_by_method(d, method="B", block="b1")

        reg_tot = float(d.get("상시_합계", round(reg * n_m, 2)) or 0.0)
        yth_tot = float(d.get("청년등_합계", round(yth * n_m, 2)) or 0.0)
        non_tot = float(d.get("청년외_합계", round(max(0.0, reg_tot - yth_tot), 2)) or 0.0)

        m_b2 = calc_method_for(y - 1, eval_year=y)
        p_b2 = _pick_summary_by_method(d, method=m_b2, block="b2")
        b2_r, b2_y, b2_ya = p_b2["reg"], p_b2["yth"], p_b2["yth_act"]
        b2_y_tot = float(d.get("b2_청년등_합계", round(b2_y * n_m, 2)) or 0.0)

        m_b3 = calc_method_for(y - 2, eval_year=y)
        p_b3 = _pick_summary_by_method(d, method=m_b3, block="b3")
        b3_r, b3_y, b3_ya = p_b3["reg"], p_b3["yth"], p_b3["yth_act"]
        b3_y_tot = float(d.get("b3_청년등_합계", round(b3_y * n_m, 2)) or 0.0)

        p_b2_A = _pick_summary_by_method(d, method="A", block="b2")
        p_b2_B = _pick_summary_by_method(d, method="B", block="b2")
        p_b3_A = _pick_summary_by_method(d, method="A", block="b3")
        p_b3_B = _pick_summary_by_method(d, method="B", block="b3")

        alt_p = p_A if use_m == "B" else p_B
        has_data = bool(d.get("has_data", reg > 0 or yth > 0 or p_A["reg"] > 0 or p_B["reg"] > 0))
        return {
            "from_filed": bool(d.get("from_filed")),
            "months_in_year": n_m,
            "calc_method": use_m,
            "calc_badge": calc_method_badge_label(use_m, eval_year=y if target_method is None else None),
            "calc_method_b2": m_b2,
            "calc_badge_b2": calc_method_badge_label(m_b2, eval_year=y),
            "calc_method_b3": m_b3,
            "calc_badge_b3": calc_method_badge_label(m_b3, eval_year=y),
            "regular": reg,
            "youth": yth,
            "non_youth": non_y,
            "A_regular": p_A["reg"],
            "A_youth": p_A["yth"],
            "A_non_youth": p_A["gen"],
            "B_regular": p_B["reg"],
            "B_youth": p_B["yth"],
            "B_non_youth": p_B["gen"],
            "ab_diff": (abs(p_A["reg"] - p_B["reg"]) >= 0.01 or abs(p_A["yth"] - p_B["yth"]) >= 0.01),
            "reg_total": reg_tot,
            "yth_total": yth_tot,
            "non_youth_total": non_tot,
            "b2_reg": b2_r,
            "b2_yth": b2_y,
            "b2_yth_total": b2_y_tot,
            "A_b2_reg": p_b2_A["reg"],
            "A_b2_yth": p_b2_A["yth"],
            "A_b2_gen": p_b2_A["gen"],
            "B_b2_reg": p_b2_B["reg"],
            "B_b2_yth": p_b2_B["yth"],
            "B_b2_gen": p_b2_B["gen"],
            "ab_diff_b2": (abs(p_b2_A["reg"] - p_b2_B["reg"]) >= 0.01 or abs(p_b2_A["yth"] - p_b2_B["yth"]) >= 0.01),
            "b3_reg": b3_r,
            "b3_yth": b3_y,
            "b3_yth_total": b3_y_tot,
            "A_b3_reg": p_b3_A["reg"],
            "A_b3_yth": p_b3_A["yth"],
            "A_b3_gen": p_b3_A["gen"],
            "B_b3_reg": p_b3_B["reg"],
            "B_b3_yth": p_b3_B["yth"],
            "B_b3_gen": p_b3_B["gen"],
            "ab_diff_b3": (abs(p_b3_A["reg"] - p_b3_B["reg"]) >= 0.01 or abs(p_b3_A["yth"] - p_b3_B["yth"]) >= 0.01),
            "b2_yth_act": b2_ya,
            "b3_yth_act": b3_ya,
            "b4_reg": alt_p["reg"],
            "b4_yth": alt_p["yth"],
            "b4_gen": alt_p["gen"],
            "has_data": has_data,
        }

    def _s_new_cmp(y: int, base_s: dict[str, Any]) -> dict[str, Any]:
        """
        당해 연도(t) 1차 공제(구법·신법 A·B·C) 및 상시근로자 현황·추가공제 요건 비교 시:
        - 계산방식은 `cur_method = calc_method_for(t, eval_year=t)` (2025년 이후 "B")를 일관되게 적용합니다.
        - 2026년 이후 신법(t >= 2026) 비교 대상 연도(2025 <= y < t)에 nr_ 재산정 인원이 있으면 해당 방식(cur_method)의 nr_ 인원을 적용합니다.
        """
        yd = summaries.get(y) or {}
        if t >= NEW_TENURE_RULE_FROM and (yd.get("nr_상시_평균") is not None or yd.get(f"nr_{cur_method}_상시_평균") is not None):
            p_nr = _pick_summary_by_method(yd, method=cur_method, block="nr")
            p_nr_A = _pick_summary_by_method(yd, method="A", block="nr")
            p_nr_B = _pick_summary_by_method(yd, method="B", block="nr")
            nr_reg, nr_yth, nr_gen = p_nr["reg"], p_nr["yth"], p_nr["gen"]
            nr_reg_tot = float(yd.get("nr_상시_합계") if yd.get("nr_상시_합계") is not None else round(nr_reg * base_s["months_in_year"], 2))
            nr_yth_tot = float(yd.get("nr_청년등_합계") if yd.get("nr_청년등_합계") is not None else round(nr_yth * base_s["months_in_year"], 2))
            nr_gen_tot = round(max(0.0, nr_reg_tot - nr_yth_tot), 2)
            p_old = _pick_summary_by_method(yd, method=calc_method_for(y), block="b1")
            return dict(
                base_s,
                _nr_applied=True,
                calc_method=cur_method,
                calc_badge=calc_method_badge_label(cur_method, eval_year=t),
                regular=nr_reg,
                youth=nr_yth,
                non_youth=nr_gen,
                A_regular=p_nr_A["reg"],
                A_youth=p_nr_A["yth"],
                A_non_youth=p_nr_A["gen"],
                B_regular=p_nr_B["reg"],
                B_youth=p_nr_B["yth"],
                B_non_youth=p_nr_B["gen"],
                ab_diff=(abs(p_nr_A["reg"] - p_nr_B["reg"]) >= 0.01 or abs(p_nr_A["yth"] - p_nr_B["yth"]) >= 0.01),
                reg_total=nr_reg_tot,
                yth_total=nr_yth_tot,
                non_youth_total=nr_gen_tot,
                old_rule_regular=p_old["reg"],
                old_rule_youth=p_old["yth"],
                nr_names=list(yd.get("nr_names") or []),
            )
        # 구법 1차년도 공제(예: t == 2025일 때 직전 2024년 비교인원) 및 상시근로자 현황 표시: cur_method(B방식) 적용
        p_cmp = _pick_summary_by_method(yd, method=cur_method, block="b1")
        return dict(
            base_s,
            calc_method=cur_method,
            calc_badge=calc_method_badge_label(cur_method, eval_year=t),
            regular=p_cmp["reg"],
            youth=p_cmp["yth"],
            non_youth=p_cmp["gen"],
        )

    cur_s = _s(t, target_method=cur_method)
    prev_s = _s(t - 1)
    prev2_s = _s(t - 2)
    prev3_s = _s(t - 3)

    prev_cmp = _s_new_cmp(t - 1, prev_s)
    prev2_cmp = _s_new_cmp(t - 2, prev2_s)
    prev3_cmp = _s_new_cmp(t - 3, prev3_s)

    # ── 1) 당해(T) 신규 고용증가분 계산 (신법 A+B+C vs 구법 — cur_method 적용) ──
    cur_inc = calc_increase_with_cap(cur_s["regular"], cur_s["youth"], prev_cmp["regular"], prev_cmp["youth"])
    rates_legacy = get_unit_rates(cur_corp_size, is_capital, scheme="legacy", retention_year=1)
    rates_new_y1 = get_unit_rates(cur_corp_size, is_capital, scheme="new_2026", retention_year=1)

    cur_legacy_yth_won = int(round(cur_inc["youth_inc"] * rates_legacy["청년등"] * 10_000))
    cur_legacy_gen_won = int(round(cur_inc["non_youth_inc"] * rates_legacy["청년등외"] * 10_000))
    cur_legacy_total_won = cur_legacy_yth_won + cur_legacy_gen_won

    abc_res = calc_new_2026_credit_abc(
        tax_year=t,
        corp_size=cur_corp_size,
        is_capital=is_capital,
        summaries_by_year={t: cur_s, t - 1: prev_cmp, t - 2: prev2_cmp, t - 3: prev3_cmp},
        corp_size_by_year=corp_size_map_resolved,
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

    def _missing(cohort: int, note: str, coh_sz: str | None = None) -> dict:
        use_sz = coh_sz or _sz_for(cohort)
        r = calc_legacy_post_management(cohort, t, use_sz, is_capital, 0, 0, 0, 0, 0, 0)
        r.update({"case_code": "기초값 없음", "case_title": "최초공제연도 인원·증가인원이 없어 계산하지 않음",
                  "formula_note": note, "base_missing": True, "corp_size": use_sz})
        return r

    def _new_law(cohort: int, tier: str, label: str) -> dict:
        use_sz = _sz_for(cohort)
        r = calc_legacy_post_management(cohort, t, use_sz, is_capital, 0, 0, 0, 0, 0, 0)
        t_info = abc_res["tiers"].get(tier) or {}
        r.update({"case_code": f"신법 {tier} 통합", "case_title": f"{cohort}년 귀속분은 신법 점증형({tier})으로 계산",
                  "retained_yth_inc": t_info.get("youth_inc", 0.0), "retained_gen_inc": t_info.get("non_youth_inc", 0.0),
                  "new_tier_info": t_info, "corp_size": use_sz,
                  "formula_note": f"{cohort}년 귀속분은 구법 사후관리 대상이 아니며 신법 {label}(B·C) 유지분 공제로 반영됩니다."})
        return r

    def _cohort(cohort: int, elapsed: int) -> tuple[dict, dict, dict]:
        """
        구법 코호트(cohort)의 사후관리·연속공제 비교 (2026.5.22. 대통령령 제36342호 반영):
        - `pm_method = calc_method_for(cohort, eval_year=t)`: 평가연도(t)의 사후관리 인원(b2/b3) 계산방식
          (t >= 2026이면 합계 후 1회 절사 "A"). 결과 dict의 calc_method·calc_badge도 이 기준으로 표시합니다.
        - 직전연도(t-1) 1차 사후관리 인원(elapsed == 2일 때의 prev_pm_pick)은 `calc_method_for(cohort, eval_year=t - 1)`로 계산합니다.
        - `coh_method = calc_method_for(cohort)`: 최초 공제연도 인원(cohort 및 cohort-1, s_init_coh·s_before_coh) 계산방식
          (최초 공제연도 당시 규칙 → 2025년분은 B, 2024년 이하분은 A). 세법원칙(재계산) 기준에만 쓰이며,
          기신고 기준은 기신고값을 그대로 사용합니다.
        # 확인 필요: 최초 공제연도 B방식 신고값과 평가연도 합계 절사값의 비교 — 2027년 국세청 신고 안내 확인
        """
        coh_method = calc_method_for(cohort)
        pm_method = calc_method_for(cohort, eval_year=t)
        blk_name = "b2" if elapsed == 1 else "b3"
        cur_pm_pick = _pick_summary_by_method(summaries.get(t), method=pm_method, block=blk_name)
        cur_reg, cur_yth, cur_yth_act = cur_pm_pick["reg"], cur_pm_pick["yth"], cur_pm_pick["yth_act"]

        s_init_coh = _s(cohort, target_method=coh_method)
        s_before_coh = _s(cohort - 1, target_method=coh_method)

        f = pf.get(cohort) or pf.get(str(cohort)) or {}
        coh_sz = _sz_for(cohort)
        coh_cap = is_capital if f.get("is_capital") is None else bool(f.get("is_capital"))
        coh_rates = get_unit_rates(coh_sz, coh_cap, scheme="legacy", retention_year=1)
        filed = {k: _fv(f, k) for k in ("init_reg", "init_yth", "init_yth_inc", "init_gen_inc")}
        claimed = int(_fv(f, "claimed_won") or 0)
        cf = int(_fv(f, "carryforward_won") or 0)
        y1_cont = _fv(f, "y1_continued_won")
        paid = int(_fv(f, "prior_clawback_paid_won") or 0)
        extra = {}
        if elapsed == 2:
            prev_pm_pick = _pick_summary_by_method(summaries.get(t - 1), method=calc_method_for(cohort, eval_year=t - 1), block="b2")
            extra = dict(prev_pm_reg=prev_pm_pick["reg"] if prev_s["has_data"] else None,
                         prev_pm_yth=prev_pm_pick["yth"] if prev_s["has_data"] else None,
                         prev_pm_yth_actual=prev_pm_pick["yth_act"] if prev_s["has_data"] else None,
                         prior_clawback_paid_won=paid,
                         y1_continued_credit_won=int(y1_cont) if y1_cont is not None else None)

        def _run(vals: dict, label: str, borrowed: list[str], claimed: int = claimed, cap_note: str = "") -> dict:
            if any(v is None for v in vals.values()):
                return _missing(cohort, f"[{label}] {cohort}년 최초공제연도의 상시·청년등 인원 또는 공제받은 증가인원이 없습니다. "
                                        f"3단계 위쪽에 기신고 숫자를 입력하세요.", coh_sz=coh_sz)
            r = calc_legacy_post_management(cohort, t, coh_sz, coh_cap,
                                            vals["init_reg"], vals["init_yth"], vals["init_yth_inc"], vals["init_gen_inc"],
                                            cur_reg, cur_yth, init_credit_claimed_won=claimed,
                                            unclaimed_carryforward_won=cf, cur_pm_yth_actual=cur_yth_act, **extra)
            r["corp_size"] = coh_sz
            r["calc_method"] = pm_method
            r["calc_badge"] = calc_method_badge_label(cohort, eval_year=t)
            r["rates_legacy"] = coh_rates
            r["base_label"] = label + (f" ({', '.join(borrowed)}은 기신고 숫자 사용)" if borrowed else "")
            if claimed > 0 and (vals.get("init_yth_inc") is not None or vals.get("init_gen_inc") is not None):
                exp_c_won = int(
                    round(
                        (
                            float(vals.get("init_yth_inc") or 0.0) * coh_rates["청년등"]
                            + float(vals.get("init_gen_inc") or 0.0) * coh_rates["청년등외"]
                        )
                        * 10_000
                    )
                )
                if exp_c_won >= 0 and abs(claimed - exp_c_won) >= 10:
                    r["filed_credit_mismatch"] = True
                    r["filed_claimed_won"] = claimed
                    r["expected_claimed_by_size_won"] = exp_c_won
                    r["filed_credit_mismatch_msg"] = (
                        f"[{cohort}년 귀속] 기신고 공제세액이 선택한 기업규모 단가와 다릅니다. 규모 선택 또는 신고서를 확인하세요 "
                        f"(기신고 공제세액 {claimed:,}원 ≠ 기신고 인원 × {R.format_corp_size_label(coh_sz)} 단가 {exp_c_won:,}원)."
                    )
            if claimed <= 0 and r.get("clawback_gross_won", 0) > 0:
                r["formula_note"] += " ※ 기신고 공제세액이 없어 추가납부 한도를 적용하지 못했습니다."
            if cap_note:
                r["formula_note"] += cap_note
            return r

        r_filed = _run(filed, "기신고 기준", [])
        recalc, borrowed = dict(filed), []
        law_ok = lambda d: d["has_data"] and not d.get("from_filed")
        if law_ok(s_init_coh):
            recalc["init_reg"], recalc["init_yth"] = s_init_coh["regular"], s_init_coh["youth"]
            recalc["init_reg_total"], recalc["init_yth_total"] = s_init_coh["reg_total"], s_init_coh["yth_total"]
        else:
            borrowed.append("최초연도 인원")
        if law_ok(s_init_coh) and law_ok(s_before_coh):
            inc = calc_increase_with_cap(s_init_coh["regular"], s_init_coh["youth"], s_before_coh["regular"], s_before_coh["youth"])
            recalc["init_yth_inc"], recalc["init_gen_inc"] = inc["youth_inc"], inc["non_youth_inc"]
        else:
            borrowed.append("증가인원")
        recalc_claimed, cap_note = claimed, ""
        if claimed <= 0 and recalc.get("init_yth_inc") is not None and recalc.get("init_gen_inc") is not None:
            y0_est_won = int(round((float(recalc["init_yth_inc"]) * coh_rates["청년등"]
                                    + float(recalc["init_gen_inc"]) * coh_rates["청년등외"]) * 10_000))
            recalc_claimed = y0_est_won
            if elapsed == 2 and y1_cont is None and not (
                prev_s["has_data"] and prev_s["b2_reg"] < float(recalc.get("init_reg") or 0.0)
            ):
                y1_act = prev_s.get("b2_yth_act", prev_s["b2_yth"])
                if prev_s["has_data"] and y1_act < float(recalc.get("init_yth") or 0.0):
                    tot_inc_recalc = float(recalc["init_yth_inc"]) + float(recalc["init_gen_inc"])
                    y1_est_won = int(round(tot_inc_recalc * coh_rates["청년등외"] * 10_000))
                else:
                    y1_est_won = y0_est_won
                recalc_claimed = y0_est_won + y1_est_won
            cap_note = f" ※ 한도는 재계산 증가인원 × 구법 단가로 추정({recalc_claimed:,}원)했습니다."
        r_recalc = _run(recalc, "세법원칙 기준", borrowed, claimed=recalc_claimed, cap_note=cap_note)
        return r_filed, r_recalc, {"filed": filed, "recalc": recalc, "borrowed": borrowed, "calc_method": pm_method}

    if (t - 1) <= 2025:
        pm_y1_filed, pm_y1_recalc, base_y1 = _cohort(t - 1, 1)
    else:
        pm_y1_filed = pm_y1_recalc = _new_law(t - 1, "B", "2년차")
        base_y1 = {}
    if (t - 2) <= 2025:
        pm_y2_filed, pm_y2_recalc, base_y2 = _cohort(t - 2, 2)
    else:
        pm_y2_filed = pm_y2_recalc = _new_law(t - 2, "C", "3년차")
        base_y2 = {}
    has_t2_data = bool(prev2_s["has_data"])

    pm_y1 = pm_y1_recalc if basis == R.PM_BASIS_RECALC else pm_y1_filed
    pm_y2 = pm_y2_recalc if basis == R.PM_BASIS_RECALC else pm_y2_filed

    # ── 4) 정규직 전환자(~2024년 귀속) 및 육아휴직 복귀자(~2026년 귀속) 추가공제 (cur_method = B방식 인원 비교) ──
    add_unit_man = R.ADDITIONAL_CREDIT_PER_PERSON.get(cur_corp_size, 0)
    parental_ret_cnt = int(add_in.get("parental_return_count", 0) or 0) if t <= 2026 else 0
    reg_conv_cnt = int(add_in.get("regular_conversion_count", 0) or 0) if t <= 2024 else 0
    early_term_add_cnt = int(add_in.get("additional_clawback_count", 0) or 0)
    maternity_rep_cnt = float(add_in.get("maternity_replacement_count", 0.0) or 0.0)
    maternity_prev_cnt = float(add_in.get("maternity_prev_count", 0.0) or 0.0)

    non_decrease_ok = (cur_s["regular"] - maternity_rep_cnt + 1e-9) >= (prev_cmp["regular"] - maternity_prev_cnt)
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
        "calc_method": cur_method,
        "calc_badge": calc_method_badge_label(cur_method),
        "corp_size": cur_corp_size,
        "corp_size_by_year": corp_size_map_resolved,
        "coh1_corp_size": _sz_for(t - 1),
        "coh2_corp_size": _sz_for(t - 2),
        "is_capital": is_capital,
        "active_scheme": active_scheme,
        "pm_basis": basis,
        "pm_basis_label": R.PM_BASIS_LABELS.get(basis, "기신고 기준"),
        "has_t2_data": has_t2_data,
        "base_y1": base_y1,
        "base_y2": base_y2,
        "cur_s": cur_s,
        "prev_s": prev_cmp,
        "prev_s_pm": prev_s,
        "prev2_s": prev2_s,
        "prev2_s_cmp": prev2_cmp,
        "prev3_s_cmp": prev3_cmp,
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
        "filed_credit_mismatch_warnings": [
            w["filed_credit_mismatch_msg"]
            for w in (pm_y1_filed, pm_y2_filed)
            if isinstance(w, dict) and w.get("filed_credit_mismatch") and w.get("filed_credit_mismatch_msg")
        ],
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