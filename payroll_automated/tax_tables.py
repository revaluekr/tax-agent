# -*- coding: utf-8 -*-
"""
인건비 자동화 — 근로소득 간이세액표(2024.03.01 / 2026.03.01 시행령 별표2) · 종교인소득 간이세액표 · 3.3% 사업소득 · 세후->세전 1원 단위 역산(Gross-up) 엔진

[법제처 원문 기반 2026년 4대보험 요율 및 정밀 연산 반영]
1. 2026년 국민연금 근로자 부담분: 4.75% (전체 9.5%, 국민연금법 부칙 제20885호 2025.4.2. 제4조 제1항 제1호 "2026년은 1만분의 475")
2. 2026년 건강보험 근로자 부담분: 3.595% (전체 7.19%, 국민건강보험법 시행령 제44조 제1항 "1만분의 719")
3. 2026년 장기요양보험: 보수월액 대비 0.9448% (노인장기요양보험법 시행령 제4조 "100만분의 9,448", 즉 건강보험료 × 0.9448 / 7.19)
4. 2026년 고용보험: 근로자 실업급여 0.9% / 사업주 실업급여 0.9% + 고용안정·직능개발(150인 미만 0.25%, 150인 이상 우선지원대상기업 0.45%, 150~999인 0.65%, 1000인 이상 0.85% — 고용보험료징수법 시행령 제12조 제1항)
5. Decimal 기반 10원 미만 절사(floor_10won): 요율 계산 보험료 및 원천세는 10원 미만 절사하며, 고지서·직접 입력 보험료 및 정산분은 원단위 그대로 보존
"""
from __future__ import annotations
import math
import re

import bisect
from decimal import Decimal, ROUND_DOWN
from typing import Any

# ══════════════════════════════════════════════════════════════════
# 1. 법정 4대보험 요율 및 상·하한액 (고지서 미업로드 시 2순위 요율 산출용)
# ══════════════════════════════════════════════════════════════════
INSURANCE_RATES_BY_YEAR = {
    2024: {
        "nps_worker": Decimal("0.045"),
        "nps_owner": Decimal("0.045"),
        "nps_min_base": 370_000,
        "nps_max_base": 5_900_000,
        "nhis_worker": Decimal("0.03545"),
        "nhis_owner": Decimal("0.03545"),
        "nhis_min_base": 279_266,
        "nhis_max_base": 110_332_300,
        "ltc_num": Decimal("0.9182"),
        "ltc_den": Decimal("7.09"),
        "ltc_rate_of_nhis": Decimal("0.1295"),
        "ei_worker": Decimal("0.009"),
        "ei_owner_base": Decimal("0.009"),
        "ei_owner_extra_under150": Decimal("0.0025"),
        "ei_owner_extra_150_priority": Decimal("0.0045"),
        "ei_owner_extra_150_999": Decimal("0.0065"),
        "ei_owner_extra_over1000": Decimal("0.0085"),
    },
    2025: {
        "nps_worker": Decimal("0.045"),
        "nps_owner": Decimal("0.045"),
        "nps_min_base": 390_000,
        "nps_max_base": 6_170_000,
        "nhis_worker": Decimal("0.03545"),
        "nhis_owner": Decimal("0.03545"),
        "nhis_min_base": 279_266,
        "nhis_max_base": 127_056_982,
        "ltc_num": Decimal("0.9182"),
        "ltc_den": Decimal("7.09"),
        "ltc_rate_of_nhis": Decimal("0.1295"),
        "ei_worker": Decimal("0.009"),
        "ei_owner_base": Decimal("0.009"),
        "ei_owner_extra_under150": Decimal("0.0025"),
        "ei_owner_extra_150_priority": Decimal("0.0045"),
        "ei_owner_extra_150_999": Decimal("0.0065"),
        "ei_owner_extra_over1000": Decimal("0.0085"),
    },
    2026: {
        "nps_worker": Decimal("0.0475"),
        "nps_owner": Decimal("0.0475"),
        "nps_min_base": 400_000,
        "nps_max_base": 6_370_000,
        "nhis_worker": Decimal("0.03595"),
        "nhis_owner": Decimal("0.03595"),
        "nhis_min_base": 279_266,
        "nhis_max_base": 127_056_982,
        "ltc_num": Decimal("0.9448"),
        "ltc_den": Decimal("7.19"),
        "ltc_rate_of_nhis": Decimal("0.9448") / Decimal("7.19"),
        "ei_worker": Decimal("0.009"),
        "ei_owner_base": Decimal("0.009"),
        "ei_owner_extra_under150": Decimal("0.0025"),
        "ei_owner_extra_150_priority": Decimal("0.0045"),
        "ei_owner_extra_150_999": Decimal("0.0065"),
        "ei_owner_extra_over1000": Decimal("0.0085"),
    },
}

# 최저임금 기준 (시간급 / 209시간 월 환산액)
MINIMUM_WAGE_BY_YEAR = {
    2024: {"hourly": 9_860, "monthly_209": 2_060_740},
    2025: {"hourly": 10_030, "monthly_209": 2_096_270},
    2026: {"hourly": 10_320, "monthly_209": 2_156_880},
    2027: {"hourly": 10_320, "monthly_209": 2_156_880},
}

# 주요 비과세 한도 (소득세법 제12조 제3호)
NON_TAXABLE_LIMITS = {
    "식대": 200_000,
    "자가운전보조금": 200_000,
    "출산보육수당": 200_000,
    "생산직연장수당_월정액급여한도": 2_100_000,
    "생산직연장수당_연간한도": 2_400_000,
}

# 화면 선택용 고용안정·직업능력개발사업 요율 구간 (고용보험료징수법 시행령 제12조 제1항 제1호)
EI_STABILITY_TIERS = [
    ("150명 미만 · 0.25%", "0.0025"),
    ("150명 이상 우선지원대상기업 · 0.45%", "0.0045"),
    ("150명 이상 1,000명 미만 · 0.65%", "0.0065"),
    ("1,000명 이상 또는 국가·지자체 사업 · 0.85%", "0.0085"),
]


def _safe_float(val: Any, default: float = 0.0) -> float:
    if val is None or isinstance(val, bool):
        return default
    if isinstance(val, (int, float)):
        f = float(val)
        return f if math.isfinite(f) else default
    if isinstance(val, Decimal):
        return float(val) if val.is_finite() else default
    if isinstance(val, str):
        s = val.strip().replace(",", "").replace("원", "").replace(" ", "")
        if not s or s.lower() in ("nan", "none", "null", "inf", "-inf", "infinity", "-infinity", "-"):
            return default
        if s.startswith(("△", "▲")):
            s = "-" + s[1:].strip()
        m_man = re.match(r"^([+-]?\d+(?:\.\d+)?)\s*만$", s)
        if m_man:
            f = float(m_man.group(1)) * 10000.0
            return f if math.isfinite(f) else default
        try:
            f = float(s)
            return f if math.isfinite(f) else default
        except ValueError:
            return default
    return default


def _safe_int(val: Any, default: int = 0) -> int:
    if isinstance(val, int) and not isinstance(val, bool):
        return val
    f = _safe_float(val, float(default))
    try:
        return int(round(f))
    except (ValueError, OverflowError):
        return default


def _to_decimal(val: float | int | Decimal | str | None) -> Decimal:
    """부동소수점 오차(예: 26999.999999999996) 없이 정확한 Decimal 값으로 변환 (NaN/Inf/쉼표문자열 완벽 방어)"""
    if val is None or isinstance(val, bool):
        return Decimal("0")
    if isinstance(val, Decimal):
        return val if val.is_finite() else Decimal("0")
    if isinstance(val, int):
        return Decimal(val)
    if isinstance(val, float):
        if not math.isfinite(val):
            return Decimal("0")
        return Decimal(f"{val:.6f}")
    if isinstance(val, str):
        s = val.strip().replace(",", "").replace("원", "").replace("%", "").replace(" ", "")
        if not s or s.lower() in ("nan", "none", "null", "inf", "-inf", "infinity", "-infinity", "-"):
            return Decimal("0")
        if s.startswith(("△", "▲")):
            s = "-" + s[1:].strip()
        try:
            d = Decimal(s)
            return d if d.is_finite() else Decimal("0")
        except Exception:
            return Decimal("0")
    return Decimal("0")


def floor_10won(val: float | int | Decimal | str | None) -> int:
    """
    원 단위 절사 (10원 미만 버림 - 국세기본법 제86조 및 국민연금·건강·고용보험 산출원칙).
    Decimal 정밀 연산을 사용하여 3,000,000 * 0.009 = 27,000원이 26,990원으로 잘못 절사되는 현상을 원천 방지합니다.
    """
    d = _to_decimal(val)
    if not d.is_finite():
        return 0
    v = int(d.to_integral_value(rounding=ROUND_DOWN))
    if v >= 0:
        return (v // 10) * 10
    return -(((-v) // 10) * 10)


def _roundness_score(amount: int) -> tuple[int, int]:
    """
    세후->세전 역산 시 동일한 실지급액을 만드는 여러 세전 후보 중
    더 둥근 금액(예: 999,980원 대신 1,000,000원)을 우선 선택하기 위한 점수 함수.
    """
    if amount <= 0:
        return (0, 0)
    for power, divisor in enumerate((10, 100, 1_000, 10_000, 100_000, 1_000_000), start=1):
        if amount % divisor != 0:
            return (power - 1, -amount)
    return (6, -amount)


def is_ceo_position(pos_text: Any) -> bool:
    """직급/직책 텍스트가 대표이사(고용보험 제외 대상)인지 판별"""
    s = str(pos_text or "").strip().replace(" ", "")
    return s in ("대표", "대표이사", "대표자", "공동대표", "각자대표", "법인대표")


def calc_4ins_by_rate(
    taxable_pay: int | float,
    year: int = 2026,
    is_ceo: bool = False,
    nps_exempt: bool = False,
    nhis_exempt: bool = False,
    ei_exempt: bool = False,
) -> dict[str, int]:
    """
    과세급여(보수월액)를 기준으로 4대보험 근로자 부담분(10원 미만 절사)을 산출합니다.
    - 2026년 기준: 국민연금 4.75%, 건강보험 3.595%, 장기요양보험 건보료 × (0.9448 / 7.19), 고용보험 0.9%
    - 대표이사(is_ceo=True)는 고용보험 대상에서 자동 제외됩니다.
    """
    rates = INSURANCE_RATES_BY_YEAR.get(_safe_int(year, 2026), INSURANCE_RATES_BY_YEAR[2026])
    base = max(0, _safe_int(taxable_pay, 0))
    if base <= 0:
        return {"국민연금": 0, "건강보험": 0, "장기요양보험료": 0, "고용보험": 0}

    if nps_exempt:
        nps = 0
    else:
        nps_base = (base // 1000) * 1000
        nps_base = max(int(rates["nps_min_base"]), min(int(rates["nps_max_base"]), nps_base))
        nps = floor_10won(Decimal(nps_base) * rates["nps_worker"])

    if nhis_exempt:
        nhis = 0
        ltc = 0
    else:
        nhis_base = max(int(rates["nhis_min_base"]), min(int(rates["nhis_max_base"]), base))
        nhis = floor_10won(Decimal(nhis_base) * rates["nhis_worker"])
        ltc = floor_10won((Decimal(nhis) * rates["ltc_num"]) / rates["ltc_den"])

    if ei_exempt or is_ceo:
        ei = 0
    else:
        ei = floor_10won(Decimal(base) * rates["ei_worker"])

    return {
        "국민연금": nps,
        "건강보험": nhis,
        "장기요양보험료": ltc,
        "고용보험": ei,
    }


def calc_4ins_employer_share(
    taxable_pay: int | float,
    worker_ins: dict[str, int] | None = None,
    year: int = 2026,
    is_ceo: bool = False,
    emp_count: int = 10,
    is_priority_support_corp: bool = False,
    ei_stability_rate: Decimal | float | str | None = None,
) -> dict[str, int]:
    """
    사업주(회사) 부담 4대보험료 추정 (당월 검토보고용, 산재보험 제외).
    - 국민연금·건강보험·장기요양: 근로자 부담분과 같은 금액 (고지 금액이 있으면 그 금액 그대로)
    - 고용보험 사업주 부담 = 보수 × (실업급여 0.9% + 고용안정·직업능력개발 요율) — 고용보험료징수법 시행령 제12조 제1항
      * 고용안정·직능 요율은 화면에서 선택한 값(ei_stability_rate)을 우선 사용하며, 없을 경우 인원수로 판정:
        150명 미만 0.25% / 150명 이상 우선지원대상기업 0.45% / 150명 이상 1,000명 미만 0.65% / 1,000명 이상 0.85%
    """
    rates = INSURANCE_RATES_BY_YEAR.get(_safe_int(year, 2026), INSURANCE_RATES_BY_YEAR[2026])
    base = max(0, _safe_int(taxable_pay, 0))
    w = worker_ins or (calc_4ins_by_rate(base, year=year, is_ceo=is_ceo) if base > 0 else {})
    nps_own = _safe_int(w.get("국민연금", 0), 0)
    nhis_own = _safe_int(w.get("건강보험", 0), 0)
    ltc_own = _safe_int(w.get("장기요양보험료", 0), 0)

    if is_ceo or base <= 0 or _safe_int(w.get("고용보험", 1), 1) == 0:
        ei_own = 0
    else:
        if ei_stability_rate is not None:
            extra = _to_decimal(ei_stability_rate)
        elif _safe_int(emp_count, 10) < 150:
            extra = rates["ei_owner_extra_under150"]
        elif is_priority_support_corp:
            extra = rates["ei_owner_extra_150_priority"]
        elif _safe_int(emp_count, 10) < 1000:
            extra = rates["ei_owner_extra_150_999"]
        else:
            extra = rates["ei_owner_extra_over1000"]
        ei_own = floor_10won(Decimal(base) * (rates["ei_owner_base"] + extra))

    return {
        "국민연금_사업주": nps_own,
        "건강보험_사업주": nhis_own,
        "장기요양_사업주": ltc_own,
        "고용보험_사업주": ei_own,
        "합계_사업주": nps_own + nhis_own + ltc_own + ei_own,
    }


# ══════════════════════════════════════════════════════════════════
# 2. 근로소득 간이세액표 (소득세법 시행령 별표 2 — 661개 전 구간 내장)
# ══════════════════════════════════════════════════════════════════
from .tax_table_data import (
    EARNED_TAX_TABLE_ROWS,
    EARNED_TAX_10000K_EXACT,
    RELIGIOUS_TAX_TABLE_ROWS,
    RELIGIOUS_TAX_12000K_EXACT,
)

_EARNED_STARTS = [r[0] for r in EARNED_TAX_TABLE_ROWS]
_RELIGIOUS_STARTS = [r[0] for r in RELIGIOUS_TAX_TABLE_ROWS]


def _lookup_earned_base_tax_10k(taxable_monthly_krw: int, dependents: int) -> int:
    dep = max(1, _safe_int(dependents, 1))
    if dep > 11:
        t11 = _lookup_earned_base_tax_10k(taxable_monthly_krw, 11)
        t10 = _lookup_earned_base_tax_10k(taxable_monthly_krw, 10)
        diff = max(0, t10 - t11)
        return max(0, t11 - diff * (dep - 11))

    col_idx = dep - 1
    k_val = float(taxable_monthly_krw) / 1000.0

    if k_val < 1060.0:
        return 0

    if k_val < 10000.0:
        idx = bisect.bisect_right(_EARNED_STARTS, k_val) - 1
        if idx < 0:
            return 0
        lo, hi, row_taxes = EARNED_TAX_TABLE_ROWS[idx]
        return int(row_taxes[col_idx])

    base_10m = int(EARNED_TAX_10000K_EXACT[col_idx])
    if k_val == 10000.0:
        return base_10m

    w = Decimal(int(taxable_monthly_krw))
    if w <= Decimal(14_000_000):
        extra = (w - Decimal(10_000_000)) * Decimal("0.98") * Decimal("0.35") + Decimal(25_000)
    elif w <= Decimal(28_000_000):
        extra = Decimal(1_397_000) + (w - Decimal(14_000_000)) * Decimal("0.98") * Decimal("0.38")
    elif w <= Decimal(30_000_000):
        extra = Decimal(6_610_600) + (w - Decimal(28_000_000)) * Decimal("0.98") * Decimal("0.40")
    elif w <= Decimal(45_000_000):
        extra = Decimal(7_394_600) + (w - Decimal(30_000_000)) * Decimal("0.40")
    elif w <= Decimal(87_000_000):
        extra = Decimal(13_394_600) + (w - Decimal(45_000_000)) * Decimal("0.42")
    else:
        extra = Decimal(31_034_600) + (w - Decimal(87_000_000)) * Decimal("0.45")

    return floor_10won(Decimal(base_10m) + extra)


def calc_child_tax_deduction(children_8_to_20: int, year_month: str = "2026-10") -> int:
    cnt = max(0, _safe_int(children_8_to_20, 0))
    if cnt <= 0:
        return 0
    ym_clean = str(year_month or "2026-10").replace(".", "-").replace(" ", "")[:7]
    is_2026_mar_or_later = ym_clean >= "2026-03"
    if is_2026_mar_or_later:
        if cnt == 1:
            return 20_830
        if cnt == 2:
            return 45_830
        return 45_830 + (cnt - 2) * 33_330
    else:
        if cnt == 1:
            return 12_500
        if cnt == 2:
            return 29_160
        return 29_160 + (cnt - 2) * 25_000


def calc_withholding_tax(
    taxable_monthly_krw: int | float,
    dependents: int = 1,
    children_8_to_20: int = 0,
    rate_pct: int = 100,
    year_month: str = "2026-10",
    reduction_pct: float = 0,
) -> dict[str, int]:
    """reduction_pct: 소득세 감면율(%) — 예) 중소기업 취업자 소득세 감면 90%면 간이세액의 10%만 원천징수 (조세특례제한법 제30조)."""
    w = max(0, _safe_int(taxable_monthly_krw, 0))
    base_tax = _lookup_earned_base_tax_10k(w, dependents)
    child_ded = calc_child_tax_deduction(children_8_to_20, year_month=year_month)
    tax_100 = max(0, base_tax - child_ded)

    pct = _safe_int(rate_pct, 100)
    if pct not in (80, 100, 120):
        pct = 100
    if pct != 100:
        income_tax = floor_10won((Decimal(tax_100) * Decimal(pct)) / Decimal(100))
    else:
        income_tax = floor_10won(tax_100)

    red = max(0.0, min(100.0, _safe_float(reduction_pct, 0.0)))
    if red > 0:
        income_tax = floor_10won((Decimal(income_tax) * (Decimal(100) - Decimal(str(red)))) / Decimal(100))

    if income_tax < 1000:
        income_tax = 0

    local_tax = floor_10won(Decimal(income_tax) * Decimal("0.10"))
    if local_tax < 0:
        local_tax = 0

    return {
        "소득세": income_tax,
        "지방소득세": local_tax,
        "세액합계": income_tax + local_tax,
    }


def calc_religious_withholding_tax(monthly_krw: int | float, dependents: int = 1) -> dict[str, int]:
    dep = max(1, min(10, _safe_int(dependents, 1)))
    col_idx = dep - 1
    k_val = float(_safe_int(monthly_krw, 0)) / 1000.0
    if k_val < 1250.0:
        return {"소득세": 0, "지방소득세": 0, "세액합계": 0}
    if k_val < 12000.0:
        idx = bisect.bisect_right(_RELIGIOUS_STARTS, k_val) - 1
        tax = int(RELIGIOUS_TAX_TABLE_ROWS[max(0, idx)][2][col_idx]) if idx >= 0 else 0
    elif k_val == 12000.0:
        tax = int(RELIGIOUS_TAX_12000K_EXACT[col_idx])
    else:
        base_12m = int(RELIGIOUS_TAX_12000K_EXACT[col_idx])
        extra = (Decimal(_safe_int(monthly_krw, 0)) - Decimal(12_000_000)) * Decimal("0.20")
        tax = floor_10won(Decimal(base_12m) + extra)

    if tax < 1000:
        tax = 0
    local = floor_10won(Decimal(tax) * Decimal("0.10"))
    return {"소득세": tax, "지방소득세": local, "세액합계": tax + local}


# ══════════════════════════════════════════════════════════════════
# 3. 3.3% 사업소득(프리랜서) 원천세 계산 및 세후 -> 세전 역산기
# ══════════════════════════════════════════════════════════════════
def calc_freelancer_33_tax(gross_amount: int | float, rate_pct: float = 3.0) -> dict[str, int]:
    gross = max(0, _safe_int(gross_amount, 0))
    r = _to_decimal(rate_pct or 3.0) / Decimal(100)
    inc_tax = floor_10won(Decimal(gross) * r)
    # 소액부징수 적용 안 함: 2024.7.1. 이후 지급하는 인적용역 사업소득(계속·반복 활동)은 소득세법 제86조 소액부징수 대상에서 제외
    loc_tax = floor_10won(Decimal(inc_tax) * Decimal("0.10"))
    tot_ded = inc_tax + loc_tax
    net_pay = gross - tot_ded
    return {
        "지급총액": gross,
        "소득세": inc_tax,
        "지방소득세": loc_tax,
        "공제합계": tot_ded,
        "차인지급액": net_pay,
    }


def gross_up_freelancer_net_to_gross(target_net: int | float, rate_pct: float = 3.0) -> dict[str, int]:
    net = max(0, _safe_int(target_net, 0))
    clean_rate = _safe_float(rate_pct, 3.0)
    if clean_rate <= 0:
        clean_rate = 3.0
    if net <= 0:
        return calc_freelancer_33_tax(0, clean_rate)

    r_eff = min(0.99, max(0.0, (clean_rate * 1.1) / 100.0))
    approx = int(round(net / max(0.01, 1.0 - r_eff)))

    best_gross = approx
    best_key: tuple[int, int, int] = (10**12, 0, 0)
    for cand in range(max(net, approx - 300), approx + 301):
        res = calc_freelancer_33_tax(cand, clean_rate)
        diff = abs(res["차인지급액"] - net)
        r_score, neg_amt = _roundness_score(cand)
        cand_key = (diff, -r_score, -neg_amt)
        if cand_key < best_key:
            best_key = cand_key
            best_gross = cand
    return calc_freelancer_33_tax(best_gross, clean_rate)


# ══════════════════════════════════════════════════════════════════
# 4. 4대보험 근로자 세후(실수령액) -> 세전(기본급) 1원 단위 이진탐색 역산기
# ══════════════════════════════════════════════════════════════════
def gross_up_employee_net_to_gross(
    target_net_pay: int | float,
    non_taxable_pay: int | float = 200_000,
    other_taxable_allowances: int | float = 0,
    dependents: int = 1,
    children_8_to_20: int = 0,
    tax_rate_pct: int = 100,
    year_month: str = "2026-10",
    fixed_ins: dict[str, int] | None = None,
    is_ceo: bool = False,
    income_tax_reduction_pct: float = 0,
) -> dict[str, int]:
    target_net = max(0, _safe_int(target_net_pay, 0))
    non_tax = max(0, _safe_int(non_taxable_pay, 0))
    other_tax = max(0, _safe_int(other_taxable_allowances, 0))
    yr = int(str(year_month or "2026")[:4]) if str(year_month or "2026")[:4].isdigit() else 2026

    if target_net <= non_tax:
        return {
            "기본급": 0,
            "비과세합계": target_net,
            "지급액계": target_net,
            "국민연금": 0,
            "건강보험": 0,
            "장기요양보험료": 0,
            "고용보험": 0,
            "소득세": 0,
            "지방소득세": 0,
            "공제액계": 0,
            "차인지급액": target_net,
        }

    ded_cache: dict[int, int] = {}

    def _eval_ded(total_gross: int) -> int:
        cached = ded_cache.get(total_gross)
        if cached is not None:
            return cached
        taxable = max(0, total_gross - non_tax)
        rate_ins = calc_4ins_by_rate(taxable, year=yr, is_ceo=is_ceo)
        if fixed_ins and isinstance(fixed_ins, dict):
            nps = _safe_int(fixed_ins.get("국민연금")) if _safe_int(fixed_ins.get("국민연금"), 0) > 0 else rate_ins["국민연금"]
            nhis = _safe_int(fixed_ins.get("건강보험")) if _safe_int(fixed_ins.get("건강보험"), 0) > 0 else rate_ins["건강보험"]
            ltc = _safe_int(fixed_ins.get("장기요양보험료")) if _safe_int(fixed_ins.get("장기요양보험료"), 0) > 0 else rate_ins["장기요양보험료"]
            ei = _safe_int(fixed_ins.get("고용보험")) if _safe_int(fixed_ins.get("고용보험"), 0) > 0 else rate_ins["고용보험"]
            adj = (
                _safe_int(fixed_ins.get("건강보험료정산", 0))
                + _safe_int(fixed_ins.get("장기요양보험료정산", 0))
                + _safe_int(fixed_ins.get("국민연금정산", 0))
                + _safe_int(fixed_ins.get("학자금상환액", 0))
            )
        else:
            nps = rate_ins["국민연금"]
            nhis = rate_ins["건강보험"]
            ltc = rate_ins["장기요양보험료"]
            ei = rate_ins["고용보험"]
            adj = 0

        wt = calc_withholding_tax(
            taxable,
            dependents=dependents,
            children_8_to_20=children_8_to_20,
            rate_pct=tax_rate_pct,
            year_month=year_month,
            reduction_pct=income_tax_reduction_pct,
        )
        tot_ded = nps + nhis + ltc + ei + wt["소득세"] + wt["지방소득세"] + adj
        ded_cache[total_gross] = tot_ded
        return tot_ded

    def _build_pack(total_gross: int) -> dict[str, int]:
        taxable = max(0, total_gross - non_tax)
        rate_ins = calc_4ins_by_rate(taxable, year=yr, is_ceo=is_ceo)
        if fixed_ins and isinstance(fixed_ins, dict):
            nps = _safe_int(fixed_ins.get("국민연금")) if _safe_int(fixed_ins.get("국민연금"), 0) > 0 else rate_ins["국민연금"]
            nhis = _safe_int(fixed_ins.get("건강보험")) if _safe_int(fixed_ins.get("건강보험"), 0) > 0 else rate_ins["건강보험"]
            ltc = _safe_int(fixed_ins.get("장기요양보험료")) if _safe_int(fixed_ins.get("장기요양보험료"), 0) > 0 else rate_ins["장기요양보험료"]
            ei = _safe_int(fixed_ins.get("고용보험")) if _safe_int(fixed_ins.get("고용보험"), 0) > 0 else rate_ins["고용보험"]
            adj = (
                _safe_int(fixed_ins.get("건강보험료정산", 0))
                + _safe_int(fixed_ins.get("장기요양보험료정산", 0))
                + _safe_int(fixed_ins.get("국민연금정산", 0))
                + _safe_int(fixed_ins.get("학자금상환액", 0))
            )
        else:
            nps = rate_ins["국민연금"]
            nhis = rate_ins["건강보험"]
            ltc = rate_ins["장기요양보험료"]
            ei = rate_ins["고용보험"]
            adj = 0
        wt = calc_withholding_tax(
            taxable,
            dependents=dependents,
            children_8_to_20=children_8_to_20,
            rate_pct=tax_rate_pct,
            year_month=year_month,
            reduction_pct=income_tax_reduction_pct,
        )
        inc_tax = wt["소득세"]
        loc_tax = wt["지방소득세"]
        tot_ded = nps + nhis + ltc + ei + inc_tax + loc_tax + adj
        net_val = total_gross - tot_ded
        return {
            "기본급": max(0, total_gross - non_tax - other_tax),
            "비과세합계": non_tax,
            "지급액계": total_gross,
            "국민연금": nps,
            "건강보험": nhis,
            "장기요양보험료": ltc,
            "고용보험": ei,
            "소득세": inc_tax,
            "지방소득세": loc_tax,
            "공제액계": tot_ded,
            "차인지급액": net_val,
        }

    lo = target_net
    hi = int(target_net * 1.85) + 500_000
    while lo < hi:
        mid = (lo + hi) // 2
        if (mid - _eval_ded(mid)) < target_net:
            lo = mid + 1
        else:
            hi = mid

    start_c = max(target_net, lo - 400)
    end_c = lo + 400
    best_cand = lo
    best_key: tuple[int, int, int] = (10**12, 0, 0)

    seg_stack: list[tuple[int, int]] = [(start_c, end_c)]
    while seg_stack:
        a, b = seg_stack.pop()
        da = _eval_ded(a)
        db = _eval_ded(b)
        if da == db:
            for c in range(a, b + 1):
                diff = abs((c - da) - target_net)
                if diff > best_key[0]:
                    continue
                r_score, neg_amt = _roundness_score(c)
                cand_key = (diff, -r_score, -neg_amt)
                if cand_key < best_key:
                    best_key = cand_key
                    best_cand = c
            continue
        if b - a <= 1:
            for c, d_val in ((a, da), (b, db)):
                diff = abs((c - d_val) - target_net)
                r_score, neg_amt = _roundness_score(c)
                cand_key = (diff, -r_score, -neg_amt)
                if cand_key < best_key:
                    best_key = cand_key
                    best_cand = c
            continue
        m = (a + b) // 2
        seg_stack.append((m + 1, b))
        seg_stack.append((a, m))
    return _build_pack(best_cand)


# ══════════════════════════════════════════════════════════════════
# 5. 통합 표준 인터페이스 (parsers / calculators / ui 호환용)
# ══════════════════════════════════════════════════════════════════

MINIMUM_HOURLY_WAGE = {yr: v["hourly"] for yr, v in MINIMUM_WAGE_BY_YEAR.items()}
MINIMUM_MONTHLY_WAGE_209H = {yr: v["monthly_209"] for yr, v in MINIMUM_WAGE_BY_YEAR.items()}

RATES_2026 = {
    "national_pension_employee": 0.0475,
    "health_insurance_employee": 0.03595,
    "long_term_care_rate_of_wage": 0.009448,
    "long_term_care_of_health": 0.9448 / 7.19,
    "employment_insurance_employee": 0.009,
}


def lookup_monthly_withholding_tax(
    taxable_monthly_krw: int | float,
    dependents: int = 1,
    children_8_20: int = 0,
    withholding_rate_pct: int = 100,
    effective_table: str = "2026.03",
    income_tax_reduction_pct: float = 0,
) -> dict[str, int]:
    ym = "2026-03" if str(effective_table).startswith("2026") else "2024-03"
    res = calc_withholding_tax(
        taxable_monthly_krw=taxable_monthly_krw,
        dependents=dependents,
        children_8_to_20=children_8_20,
        rate_pct=withholding_rate_pct,
        year_month=ym,
        reduction_pct=income_tax_reduction_pct,
    )
    return {
        "income_tax": res["소득세"],
        "local_tax": res["지방소득세"],
        "total_tax": res["세액합계"],
    }


def calculate_4major_insurance_by_rate(
    taxable_pay: int | float,
    year: int = 2026,
    is_ceo: bool = False,
) -> dict[str, int]:
    return calc_4ins_by_rate(taxable_pay=taxable_pay, year=year, is_ceo=is_ceo)


def calculate_employee_payroll_row(
    base_pay: int = 0,
    bonus: int = 0,
    meal_allowance: int = 0,
    car_allowance: int = 0,
    fixed_overtime_pay: int = 0,
    fixed_holiday_pay: int = 0,
    overtime_pay: int = 0,
    holiday_pay: int = 0,
    unused_leave_pay: int = 0,
    absence_deduction: int = 0,
    adjustment_pay: int = 0,
    dependents: int = 1,
    children_8_20: int = 0,
    withholding_rate_pct: int = 100,
    notice_insurance: dict[str, int] | None = None,
    student_loan_repayment: int = 0,
    effective_table: str = "2026.03",
    is_ceo: bool = False,
    income_tax_reduction_pct: float = 0,
) -> dict[str, Any]:
    """
    단일 근로자 급여대장 행 전체 계산:
    - 지급액계 = 기본급 + 상여 + 식대 + 자가운전 + 약정연장 + 약정휴일 + 연장 + 휴일 + 미사용연차 + 결근공제(음수 가능) + 조정금액
    - 비과세 = min(식대, 200,000) + min(자가운전, 200,000)
    - 과세급여 = max(0, 지급액계 - 비과세)
    - 4대보험: 고지내역(notice_insurance)이 있으면 1순위(원단위 그대로 보존), 없으면 2순위 요율 산출(10원 미만 절사, 대표이사는 고용보험 0원)
    """
    if isinstance(base_pay, dict):
        row_d = base_pay
        base_pay = row_d.get("기본급", 0)
        bonus = row_d.get("상여", bonus)
        meal_allowance = row_d.get("식대", meal_allowance)
        car_allowance = row_d.get("자가운전보조금", car_allowance)
        fixed_overtime_pay = row_d.get("약정연장근로수당", fixed_overtime_pay)
        fixed_holiday_pay = row_d.get("약정휴일근로수당", fixed_holiday_pay)
        overtime_pay = row_d.get("연장근로수당", overtime_pay)
        holiday_pay = row_d.get("휴일근로수당", holiday_pay)
        unused_leave_pay = row_d.get("미사용연차수당", unused_leave_pay)
        absence_deduction = row_d.get("결근공제", absence_deduction)
        adjustment_pay = row_d.get("조정금액", adjustment_pay)
        dependents = row_d.get("부양가족수", dependents)
        children_8_20 = row_d.get("8세~20세자녀수", children_8_20)
        if row_d.get("직급") and not is_ceo:
            is_ceo = is_ceo_position(row_d.get("직급"))
    b_pay = _safe_int(base_pay, 0)
    bon_pay = _safe_int(bonus, 0)
    m_pay = _safe_int(meal_allowance, 0)
    c_pay = _safe_int(car_allowance, 0)
    fot_pay = _safe_int(fixed_overtime_pay, 0)
    fhol_pay = _safe_int(fixed_holiday_pay, 0)
    ot_pay = _safe_int(overtime_pay, 0)
    hol_pay = _safe_int(holiday_pay, 0)
    ul_pay = _safe_int(unused_leave_pay, 0)
    raw_abs = _safe_int(absence_deduction, 0)
    abs_val = -abs(raw_abs) if raw_abs > 0 else raw_abs
    adj_pay = _safe_int(adjustment_pay, 0)
    gross_total = (
        b_pay + bon_pay + m_pay + c_pay + fot_pay + fhol_pay
        + ot_pay + hol_pay + ul_pay + abs_val + adj_pay
    )
    non_taxable = min(max(0, m_pay), NON_TAXABLE_LIMITS["식대"]) + min(
        max(0, c_pay), NON_TAXABLE_LIMITS["자가운전보조금"]
    )
    taxable_pay = max(0, gross_total - non_taxable)

    yr = 2026 if str(effective_table).startswith("2026") else 2025
    rate_ins = calc_4ins_by_rate(taxable_pay, year=yr, is_ceo=is_ceo)
    if notice_insurance:
        # 고지서 및 수기 입력 금액은 원단위 그대로 보존 (절사하지 않음)
        nps = _safe_int(notice_insurance.get("국민연금")) if _safe_int(notice_insurance.get("국민연금"), 0) > 0 else rate_ins["국민연금"]
        nhis = _safe_int(notice_insurance.get("건강보험")) if _safe_int(notice_insurance.get("건강보험"), 0) > 0 else rate_ins["건강보험"]
        ltc = _safe_int(notice_insurance.get("장기요양보험료")) if _safe_int(notice_insurance.get("장기요양보험료"), 0) > 0 else rate_ins["장기요양보험료"]
        ei = _safe_int(notice_insurance.get("고용보험")) if _safe_int(notice_insurance.get("고용보험"), 0) > 0 else rate_ins["고용보험"]
        nhis_settle = _safe_int(notice_insurance.get("건강보험료정산", 0), 0)
        ltc_settle = _safe_int(notice_insurance.get("장기요양보험료정산", 0), 0)
        nps_settle = _safe_int(notice_insurance.get("국민연금정산", 0), 0)
        ins_mode = "고지(1순위)"
    else:
        nps = rate_ins["국민연금"]
        nhis = rate_ins["건강보험"]
        ltc = rate_ins["장기요양보험료"]
        ei = rate_ins["고용보험"]
        nhis_settle = 0
        ltc_settle = 0
        nps_settle = 0
        ins_mode = "요율(2순위)"

    tax_res = lookup_monthly_withholding_tax(
        taxable_monthly_krw=taxable_pay,
        dependents=dependents,
        children_8_20=children_8_20,
        withholding_rate_pct=withholding_rate_pct,
        effective_table=effective_table,
        income_tax_reduction_pct=income_tax_reduction_pct,
    )
    inc_tax = floor_10won(tax_res["income_tax"])
    loc_tax = floor_10won(tax_res["local_tax"])
    student_loan = _safe_int(student_loan_repayment, 0)

    total_deduction = (
        nps + nhis + ltc + ei
        + nhis_settle + ltc_settle + nps_settle
        + student_loan + inc_tax + loc_tax
    )
    net_pay = gross_total - total_deduction

    return {
        "기본급": b_pay,
        "상여": bon_pay,
        "식대": m_pay,
        "자가운전보조금": c_pay,
        "약정연장근로수당": fot_pay,
        "약정휴일근로수당": fhol_pay,
        "연장근로수당": ot_pay,
        "휴일근로수당": hol_pay,
        "미사용연차수당": ul_pay,
        "결근공제": abs_val,
        "조정금액": adj_pay,
        "지급액계": gross_total,
        "비과세합계": non_taxable,
        "과세급여": taxable_pay,
        "보험적용구분": ins_mode,
        "국민연금": nps,
        "건강보험": nhis,
        "장기요양보험료": ltc,
        "고용보험": ei,
        "건강보험료정산": nhis_settle,
        "장기요양보험료정산": ltc_settle,
        "국민연금정산": nps_settle,
        "학자금상환액": student_loan,
        "소득세": inc_tax,
        "지방소득세": loc_tax,
        "소득세감면율": max(0.0, min(100.0, _safe_float(income_tax_reduction_pct, 0.0))),
        "공제액계": total_deduction,
        "차인지급액": net_pay,
    }


def calculate_freelancer_row(gross_pay: int | float | dict, rate_pct: float = 3.0) -> dict[str, int]:
    if isinstance(gross_pay, dict):
        gross_pay = gross_pay.get("지급총액", 0)
    res = calc_freelancer_33_tax(gross_pay, rate_pct=_safe_float(rate_pct, 3.0))
    return {
        "gross_pay": res["지급총액"],
        "income_tax": res["소득세"],
        "local_tax": res["지방소득세"],
        "total_deduction": res["공제합계"],
        "net_pay": res["차인지급액"],
        "지급총액": res["지급총액"],
        "소득세": res["소득세"],
        "지방소득세": res["지방소득세"],
        "공제합계": res["공제합계"],
        "차인지급액": res["차인지급액"],
    }


def solve_gross_from_net_freelancer(target_net_pay: int | float, rate_pct: float = 3.0) -> dict[str, int]:
    res = gross_up_freelancer_net_to_gross(target_net_pay, rate_pct=rate_pct)
    return {
        "gross_pay": res["지급총액"],
        "income_tax": res["소득세"],
        "local_tax": res["지방소득세"],
        "total_deduction": res["공제합계"],
        "net_pay": res["차인지급액"],
    }


def solve_gross_from_net_employee(
    target_net_pay: int | float,
    non_taxable_pay: int | float = 200_000,
    dependents: int = 1,
    children_8_20: int = 0,
    withholding_rate_pct: int = 100,
    notice_insurance: dict[str, int] | None = None,
    student_loan_repayment: int = 0,
    effective_table: str = "2026.03",
    is_ceo: bool = False,
    income_tax_reduction_pct: float = 0,
) -> dict[str, int]:
    ym = "2026-03" if str(effective_table).startswith("2026") else "2024-03"
    fixed = dict(notice_insurance) if notice_insurance else None
    if fixed is not None and student_loan_repayment:
        fixed["학자금상환액"] = int(student_loan_repayment)
    res = gross_up_employee_net_to_gross(
        target_net_pay=target_net_pay,
        non_taxable_pay=non_taxable_pay,
        dependents=dependents,
        children_8_to_20=children_8_20,
        tax_rate_pct=withholding_rate_pct,
        year_month=ym,
        fixed_ins=fixed,
        is_ceo=is_ceo,
        income_tax_reduction_pct=income_tax_reduction_pct,
    )
    return {
        "base_pay": res["기본급"],
        "gross_total": res["지급액계"],
        "net_pay": res["차인지급액"],
        "total_deduction": res["공제액계"],
    }


def get_simplified_tax_revision_alerts() -> list[dict[str, str]]:
    return [
        {
            "law": "소득세법 시행령",
            "display_name": "소득세법 시행령 별표2 (근로소득 간이세액표)",
            "effective_date": "2026.03.01",
            "baseline_prom_no": "36163",
            "status": "updated",
            "summary": "8~20세 자녀세액공제 차감액 인상 반영 (1명 월 20,830원 / 2명 월 45,830원 / 3명 이상 1명당 +33,330원)",
        },
        {
            "law": "소득세법",
            "display_name": "소득세법 (근로소득·비과세 한도)",
            "effective_date": "2026.01.01",
            "baseline_prom_no": "21221",
            "status": "current",
            "summary": "식대 비과세 월 20만원, 자가운전보조금 월 20만원, 출산·보육수당 월 20만원 한도 적용 중",
        },
        {
            "law": "근로기준법",
            "display_name": "근로기준법 (임금명세서·가산수당·주휴수당)",
            "effective_date": "2025.10.23",
            "baseline_prom_no": "20520",
            "status": "current",
            "summary": "제48조제2항 임금명세서 산출식 필수 기재, 제56조 5인 이상 연장·야간·휴일 가산수당(50%/100%) 적용 중",
        },
        {
            "law": "국민연금법",
            "display_name": "2026년 4대보험 요율 및 최저임금 고시",
            "effective_date": "2026.01.01",
            "baseline_prom_no": "20885",
            "status": "updated",
            "summary": "2026년 최저시급 10,320원(월 209시간 2,156,880원) / 근로자 국민연금 4.75%(부칙 제4조), 건강보험 3.595%(시행령 제44조), 장기요양 0.9448%(건보료×0.9448/7.19), 고용 0.9%",
        },
    ]
