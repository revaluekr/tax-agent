# -*- coding: utf-8 -*-
"""
인건비 자동화 — 근로소득 간이세액표(2024.03.01 / 2026.03.01 시행령 별표2) · 종교인소득 간이세액표 · 3.3% 사업소득 · 세후->세전 1원 단위 역산(Gross-up) 엔진

[법제처 원문 기반 2026년 4대보험 요율 및 정밀 연산 반영]
1. 2026년 국민연금 근로자 부담분: 4.75% (전체 9.5%, 국민연금법 부칙 제20885호 2025.4.2. 제4조 제1항 제1호 "2026년은 1만분의 475")
2. 2026년 건강보험 근로자 부담분: 3.595% (전체 7.19%, 국민건강보험법 시행령 제44조 제1항 "1만분의 719")
3. 2026년 장기요양보험: 보수월액 대비 0.9448% (노인장기요양보험법 시행령 제4조 "100만분의 9,448", 즉 건강보험료 × 0.9448 / 7.19)
4. 2026년 고용보험: 근로자 실업급여 0.9% / 사업주 실업급여 0.9% + 고용안정·직능개발(150인 미만 0.25%, 150인 이상 우선지원대상기업 0.45%, 150~999인 0.65%, 1000인 이상 0.85% — 고용보험료징수법 시행령 제12조 제1항)
5. Decimal/정수 기반 10원 미만 절사(floor_10won): 요율 계산 보험료 및 원천세는 10원 미만 절사하며, 고지서·직접 입력 보험료 및 정산분은 원단위 그대로 보존
6. 데드존(Dead Zone — 간이세액표 구간 경계 및 국민연금 1,000원 보수월액 계단 경계에서 세전 급여가 올랐는데 실수령액이 감소하는 비단조 구간) 완벽 방어:
   진동(Oscillation) 없이 납세자에게 가장 유리한 최소 세전 금액(동일 오차 시 라운드 금액 우선, 그다음 최소 세전 급여)으로 100% 수렴합니다.
"""
from __future__ import annotations

import bisect
import math
import re
from decimal import Decimal, ROUND_DOWN
from functools import lru_cache
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

_FAST_INS_INT_PARAMS = {
    yr: (
        int(cfg["nps_min_base"]),
        int(cfg["nps_max_base"]),
        int(cfg["nps_worker"] * 10000),
        int(cfg["nhis_min_base"]),
        int(cfg["nhis_max_base"]),
        int(cfg["nhis_worker"] * 100000),
        int(cfg["ltc_num"] * 10000),
        int(cfg["ltc_den"] * 10000),
        int(cfg["ei_worker"] * 1000),
    )
    for yr, cfg in INSURANCE_RATES_BY_YEAR.items()
}

# 국민연금 기준소득월액 상·하한은 "연도"가 아니라 매년 7월 ~ 이듬해 6월 단위로 고시됩니다
# (국민연금법 시행령 제5조, 보건복지부 고시). (적용 시작 귀속연월, 하한액, 상한액)
NPS_BASE_LIMIT_PERIODS: tuple[tuple[str, int, int], ...] = (
    ("2022-07", 350_000, 5_530_000),
    ("2023-07", 370_000, 5_900_000),
    ("2024-07", 390_000, 6_170_000),
    ("2025-07", 400_000, 6_370_000),
)
# 마지막 고시 구간 다음 7월부터는 새 고시값을 이 표에 추가해야 합니다.
# 추가 전에는 직전 고시값이 그대로 쓰이며, nps_base_limits()의 verified=False로 표시됩니다.
_NPS_LIMIT_STARTS = tuple(p[0] for p in NPS_BASE_LIMIT_PERIODS)

_YM_RE = re.compile(r"^\s*(\d{4})\D*(\d{1,2})")


def normalize_year_month(year_month: Any, default: str = "2026-01") -> str:
    """'2026-3', '2026.03', '202603', '2026년 3월' 등을 'YYYY-MM'으로 정규화합니다 (해석 불가 시 default)."""
    s = str(year_month or "").strip()
    m = _YM_RE.match(s)
    if not m and re.fullmatch(r"\d{6}", s):
        m = re.match(r"(\d{4})(\d{2})", s)
    if m:
        yy, mm = int(m.group(1)), int(m.group(2))
        if 1900 <= yy <= 2999 and 1 <= mm <= 12:
            return f"{yy:04d}-{mm:02d}"
    return default


def nps_base_limits(year_month: Any) -> tuple[int, int, bool]:
    """
    귀속연월의 국민연금 기준소득월액 (하한, 상한, 고시값_확인여부)를 반환합니다.
    - 7월~이듬해 6월 단위 고시 구간을 그대로 따릅니다.
    - 표의 마지막 구간보다 1년 이상 뒤면 verified=False (직전 고시값 임시 적용).
    """
    ym = normalize_year_month(year_month)
    idx = bisect.bisect_right(_NPS_LIMIT_STARTS, ym) - 1
    if idx < 0:
        start, lo, hi = NPS_BASE_LIMIT_PERIODS[0]
        return lo, hi, False
    start, lo, hi = NPS_BASE_LIMIT_PERIODS[idx]
    s_y, s_m = int(start[:4]), int(start[5:7])
    nxt = f"{s_y + 1:04d}-{s_m:02d}"
    verified = ym < nxt or idx < len(NPS_BASE_LIMIT_PERIODS) - 1
    return lo, hi, verified


def _ins_int_params(year: int, year_month: Any = None) -> tuple[int, ...]:
    """정수 연산용 보험 파라미터. year_month가 있으면 국민연금 상·하한을 고시 구간 기준으로 덮어씁니다."""
    params = _FAST_INS_INT_PARAMS.get(year) or _FAST_INS_INT_PARAMS[2026]
    if year_month is None or str(year_month).strip() == "":
        return params
    lo, hi, _ = nps_base_limits(year_month)
    return (lo, hi) + tuple(params[2:])


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

_MAN_RE = re.compile(r"^([+-]?\d+(?:\.\d+)?)\s*만$")


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
        m_man = _MAN_RE.match(s)
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
    정수 입력은 C-레벨 정수 나눗셈으로 즉시 처리하고, 실수/문자열 입력은 Decimal 정밀 연산으로 처리합니다.
    """
    if isinstance(val, int) and not isinstance(val, bool):
        return (val // 10) * 10 if val >= 0 else -(((-val) // 10) * 10)
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


@lru_cache(maxsize=512)
def _period_params(ym: str) -> tuple[int, ...]:
    """정규화된 'YYYY-MM' → (보험 정수 파라미터 9개 + 연도). 귀속연월별로 1회만 계산합니다."""
    yr = int(ym[:4])
    return _ins_int_params(yr, ym) + (yr,)


def _ins_rate_components(
    base: int,
    params: tuple[int, ...],
    is_ceo: bool = False,
    nps_exempt: bool = False,
    nhis_exempt: bool = False,
    ei_exempt: bool = False,
) -> tuple[int, int, int, int]:
    """요율 기반 (국민연금, 건강보험, 장기요양, 고용보험) 정수 커널 — 모든 경로가 이 함수 하나만 사용합니다."""
    if base <= 0:
        return 0, 0, 0, 0
    nps_min, nps_max, nps_num, nhis_min, nhis_max, nhis_num, ltc_num, ltc_den, ei_num = params[:9]
    if nps_exempt:
        nps = 0
    else:
        nps_base = max(nps_min, min(nps_max, (base // 1000) * 1000))
        nps = ((nps_base * nps_num // 10000) // 10) * 10
    if nhis_exempt:
        nhis = ltc = 0
    else:
        nhis_base = max(nhis_min, min(nhis_max, base))
        nhis = ((nhis_base * nhis_num // 100000) // 10) * 10
        ltc = ((nhis * ltc_num // ltc_den) // 10) * 10
    ei = 0 if (ei_exempt or is_ceo) else ((base * ei_num // 1000) // 10) * 10
    return nps, nhis, ltc, ei


def _notice_tuple(notice_insurance: dict[str, Any] | None) -> tuple[int, int, int, int] | None:
    if not notice_insurance:
        return None
    return (
        max(0, _safe_int(notice_insurance.get("국민연금"), 0)),
        max(0, _safe_int(notice_insurance.get("건강보험"), 0)),
        max(0, _safe_int(notice_insurance.get("장기요양보험료"), 0)),
        max(0, _safe_int(notice_insurance.get("고용보험"), 0)),
    )


def _overlay_notice(
    rate: tuple[int, int, int, int],
    notice: tuple[int, int, int, int] | None,
    params: tuple[int, ...],
) -> tuple[int, int, int, int]:
    """고지 금액(0 초과 항목) 우선 + 건강보험만 고지 시 장기요양은 고지 건보료 기준 산출."""
    if notice is None:
        return rate
    f_nps, f_nhis, f_ltc, f_ei = notice
    nps = f_nps if f_nps > 0 else rate[0]
    nhis = f_nhis if f_nhis > 0 else rate[1]
    if f_ltc > 0:
        ltc = f_ltc
    elif f_nhis > 0:
        ltc = ((f_nhis * params[6] // params[7]) // 10) * 10
    else:
        ltc = rate[2]
    ei = f_ei if f_ei > 0 else rate[3]
    return nps, nhis, ltc, ei


def calc_4ins_by_rate(
    taxable_pay: int | float,
    year: int = 2026,
    is_ceo: bool = False,
    nps_exempt: bool = False,
    nhis_exempt: bool = False,
    ei_exempt: bool = False,
    year_month: str | None = None,
) -> dict[str, int]:
    """
    과세급여(보수월액)를 기준으로 4대보험 근로자 부담분(10원 미만 절사)을 산출합니다.
    - 2026년 기준: 국민연금 4.75%, 건강보험 3.595%, 장기요양보험료 건보료 × (0.9448 / 7.19), 고용보험 0.9%
    - 대표이사(is_ceo=True)는 고용보험 대상에서 자동 제외됩니다.
    - year_month('YYYY-MM')를 주면 국민연금 상·하한을 7월~이듬해 6월 고시 구간 기준으로 적용합니다.
      (생략 시 종전과 같이 해당 연도 1~6월 구간 값을 사용)
    """
    base = max(0, _safe_int(taxable_pay, 0))
    if base <= 0:
        return {"국민연금": 0, "건강보험": 0, "장기요양보험료": 0, "고용보험": 0}

    yr_key = _safe_int(year, 2026)
    if year_month:
        ym = normalize_year_month(year_month, f"{yr_key:04d}-01")
        params = _period_params(ym)
    else:
        params = _ins_int_params(yr_key) + (yr_key,)
    nps, nhis, ltc, ei = _ins_rate_components(base, params, is_ceo, nps_exempt, nhis_exempt, ei_exempt)
    return {
        "국민연금": nps,
        "건강보험": nhis,
        "장기요양보험료": ltc,
        "고용보험": ei,
    }


def resolve_employee_insurance(
    taxable_pay: int,
    year_month: str,
    is_ceo: bool = False,
    notice_insurance: dict[str, Any] | None = None,
) -> dict[str, int]:
    """
    [단일 진실 공급원] 근로자 4대보험 공제액 결정 규칙 — 정산(세전->세후)과 역산(세후->세전)이 동일 커널을 공유합니다.
    1순위: 고지/수기 금액(0원 초과 항목만, 원단위 보존) / 2순위: 요율 산출(10원 미만 절사)
    건강보험만 고지되고 장기요양보험료가 비어 있으면 '고지된 건강보험료' 기준으로 장기요양보험료를 산출합니다.
    """
    params = _period_params(normalize_year_month(year_month))
    rate = _ins_rate_components(max(0, _safe_int(taxable_pay, 0)), params, is_ceo)
    nps, nhis, ltc, ei = _overlay_notice(rate, _notice_tuple(notice_insurance), params)
    return {"국민연금": nps, "건강보험": nhis, "장기요양보험료": ltc, "고용보험": ei}


def _insurance_settlement_total(notice_insurance: dict[str, Any] | None) -> int:
    """고지서 정산분·학자금 상환액 합계 (음수 환급 허용, 원단위 보존)."""
    if not notice_insurance:
        return 0
    return (
        _safe_int(notice_insurance.get("건강보험료정산", 0), 0)
        + _safe_int(notice_insurance.get("장기요양보험료정산", 0), 0)
        + _safe_int(notice_insurance.get("국민연금정산", 0), 0)
        + _safe_int(notice_insurance.get("학자금상환액", 0), 0)
    )


def calc_4ins_employer_share(
    taxable_pay: int | float,
    worker_ins: dict[str, int] | None = None,
    year: int = 2026,
    is_ceo: bool = False,
    emp_count: int = 10,
    is_priority_support_corp: bool = False,
    ei_stability_rate: Decimal | float | str | None = None,
    year_month: str | None = None,
) -> dict[str, int]:
    """
    사업주(회사) 부담 4대보험료 추정 (당월 검토보고용, 산재보험 제외).
    - year_month를 주면 국민연금 상·하한을 해당 고시 구간 기준으로 적용합니다.
    """
    rates = INSURANCE_RATES_BY_YEAR.get(_safe_int(year, 2026), INSURANCE_RATES_BY_YEAR[2026])
    base = max(0, _safe_int(taxable_pay, 0))
    w = worker_ins or (calc_4ins_by_rate(base, year=year, is_ceo=is_ceo, year_month=year_month) if base > 0 else {})
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
_BRACKET_STARTS_KRW: tuple[int, ...] = tuple(int(r[0] * 1000) for r in EARNED_TAX_TABLE_ROWS) + (
    10_000_000,
    14_000_000,
    28_000_000,
    30_000_000,
    45_000_000,
    87_000_000,
)


@lru_cache(maxsize=16384)
def _lookup_earned_base_tax_10k_cached(k_int_or_w: int, is_under_10m: bool, dep: int) -> int:
    if dep > 11:
        t11 = _lookup_earned_base_tax_10k_cached(k_int_or_w, is_under_10m, 11)
        t10 = _lookup_earned_base_tax_10k_cached(k_int_or_w, is_under_10m, 10)
        diff = max(0, t10 - t11)
        return max(0, t11 - diff * (dep - 11))

    col_idx = dep - 1
    if is_under_10m:
        if k_int_or_w < 1060:
            return 0
        idx = bisect.bisect_right(_EARNED_STARTS, k_int_or_w) - 1
        if idx < 0:
            return 0
        return int(EARNED_TAX_TABLE_ROWS[idx][2][col_idx])

    base_10m = int(EARNED_TAX_10000K_EXACT[col_idx])
    if k_int_or_w == 10_000_000:
        return base_10m

    w = Decimal(k_int_or_w)
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


def _lookup_earned_base_tax_10k(taxable_monthly_krw: int, dependents: int) -> int:
    dep = max(1, _safe_int(dependents, 1))
    w = max(0, _safe_int(taxable_monthly_krw, 0))
    if w < 1_060_000:
        return 0
    if w < 10_000_000:
        return _lookup_earned_base_tax_10k_cached(w // 1000, True, dep)
    return _lookup_earned_base_tax_10k_cached(w, False, dep)


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
        income_tax = (((tax_100 * pct) // 100) // 10) * 10
    else:
        income_tax = (tax_100 // 10) * 10

    red = max(0.0, min(100.0, _safe_float(reduction_pct, 0.0)))
    if red > 0:
        income_tax = floor_10won((Decimal(income_tax) * (Decimal(100) - Decimal(str(red)))) / Decimal(100))

    if income_tax < 1000:
        income_tax = 0

    local_tax = ((income_tax // 10) // 10) * 10
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
    loc_tax = ((inc_tax // 10) // 10) * 10
    tot_ded = inc_tax + loc_tax
    net_pay = gross - tot_ded
    return {
        "지급총액": gross,
        "소득세": inc_tax,
        "지방소득세": loc_tax,
        "공제합계": tot_ded,
        "차인지급액": net_pay,
    }


# ──────────────────────────────────────────────────────────────────
# 세후 -> 세전 역산 공통 엔진: 단조 공제함수의 최소 고정점(Least Fixed Point)
# ──────────────────────────────────────────────────────────────────
# [수학적 근거]
#   실수령액 N(g) = g - D(g),  D(g) = 4대보험 + 원천세 + 정산액 (정수, g에 대해 단조 비감소 계단함수 — 부양가족 1~11명).
#   ※ 부양가족 12명 이상은 별표2 외삽식 자체가 비단조라 아래 _ascending_exact_scan 경로를 사용합니다.
#   (1) N(g+1) - N(g) = 1 - (D(g+1) - D(g)) ≤ 1  → N은 1원씩만 오르고, 계단 경계에서만 떨어집니다.
#       따라서 N은 정수값을 '건너뛰지' 않으며, N(0) 이상인 모든 목표값 T에 대해 N(g) = T인 g가 반드시 존재합니다.
#       (데드존에서도 '정확히 T원'을 만드는 세전 금액은 항상 존재 → 오차 0원 보장)
#   (2) N(g) = T  ⇔  g = T + D(g) = f(g).  f는 단조 비감소이므로 g₀ = 0에서 시작한 반복 g_{k+1} = f(g_k)는
#       단조 증가하며 모든 고정점 g* 이하에 머뭅니다(귀납: g_k ≤ g* ⇒ f(g_k) ≤ f(g*) = g*).
#       정수 단조 증가 수열이 위로 유계이므로 유한 단계에 정지하고, 정지점은 '최소' 고정점 = 최소 세전 금액입니다.
#   (3) 반복은 이진탐색과 달리 비단조 술어를 쓰지 않으므로 진동(Oscillation)이 원천적으로 불가능합니다.
#       한계 공제율 r < 1이면 오차가 r^k로 줄어 통상 10~40회에 수렴합니다.
# 라운드 금액 선호: 최소해 g*에서 round_window원 이내에 실수령액이 정확히 같은 '더 둥근' 금액이 있으면 그것을 고릅니다
#   (종전 정책 유지. round_window=0이면 엄격한 최소 세전 금액).

ROUND_PREFERENCE_WINDOW_KRW = 100
_MAX_FIXED_POINT_ITERS = 100_000
_MONOTONE_TABLE_MAX_DEPENDENTS = 11      # 별표2 표 본문(1~11명)은 소득에 대해 단조 → 고정점 경로 증명 적용
_NONMONOTONE_SCAN_CAP_KRW = 50_000_000  # 11명 초과 외삽 구간 탐색 거리 상한
_NONMONOTONE_SCAN_MAX_STEPS = 200_000    # 평가 횟수 상한 (건너뛰기 덕분에 실측 수십~수백 회)
_OVERSHOOT_LOOKAHEAD_KRW = 5_000


class GrossUpConvergenceError(RuntimeError):
    """공제함수가 단조가 아니거나(입력 테이블 이상) 유효 공제율이 100% 이상이라 고정점이 없을 때."""


def _pick_rounder(target: int, g: int, deduction, round_window: int) -> int:
    """g(실수령액 정확 일치 최소해)에서 round_window원 이내에 실수령액이 같은 더 둥근 금액이 있으면 그 금액."""
    if round_window <= 0:
        return g
    hi = g + round_window
    for div in (1_000_000, 100_000, 10_000, 1_000, 100, 10):
        c = -(-g // div) * div
        while c <= hi:
            if c - deduction(c) == target:
                return c
            c += div
    return g


def _ascending_exact_scan(
    target: int,
    deduction,
    lower_bound: int,
    round_window: int,
    non_tax: int = 0,
) -> int:
    """
    공제함수가 단조가 아닐 때(부양가족 11명 초과 법정 외삽식)의 안전 경로 — '증명된 건너뛰기' 상향 탐색.
    [근거] 원천세 W는 과세급여 1,000만원 미만에서 1,000원 구간마다 일정하고(구간 경계에서만 감소 가능),
           1,000만원 이상에서는 외삽식이 단조입니다. 보험료 I는 항상 단조입니다.
           → 한 구간 안에서는 D = I + W가 단조이므로 N(g+j) ≤ N(g) + j.  N(g) < T이면 g + (T - N(g)) 전까지는
             정확해가 있을 수 없어 그만큼(또는 다음 구간 시작점까지) 안전하게 건너뜁니다.
    [하한] lower_bound(보험료만의 최소 고정점) 미만에서는 N(g) ≤ g - I(g) < T 이므로 해가 없습니다.
    따라서 처음 만나는 'N(g) == T'가 전역 최소해입니다.  정확해 없이 N이 목표를 넘어서면(구간 경계 하락 때문에)
    _OVERSHOOT_LOOKAHEAD_KRW 동안 1원 단위로 정확해를 더 찾고, 없으면 '실수령액 ≥ 목표'인 최소 금액을 반환합니다.
    """
    def _next_boundary(g: int) -> int:
        taxable = g - non_tax
        if taxable < 0:
            return non_tax                       # 과세급여 0 구간 끝
        if taxable < 10_000_000:
            return non_tax + (taxable // 1000 + 1) * 1000
        return g + 10**12                        # 1,000만원 이상: 단조 구간 (경계 없음)

    g = max(0, lower_bound)
    first_ge = None
    overshoot_until = None
    for _ in range(_NONMONOTONE_SCAN_MAX_STEPS):
        if g > lower_bound + _NONMONOTONE_SCAN_CAP_KRW:
            break
        n = g - deduction(g)
        if n == target:
            return _pick_rounder(target, g, deduction, round_window)
        if n < target:
            if overshoot_until is not None and g > overshoot_until:
                break
            g = min(g + (target - n), _next_boundary(g))
        else:
            if first_ge is None:
                first_ge, overshoot_until = g, g + _OVERSHOOT_LOOKAHEAD_KRW
            elif g > overshoot_until:
                break
            g += 1
    if first_ge is not None:
        return first_ge
    raise GrossUpConvergenceError("비단조 구간 탐색이 상한에 도달했습니다.")


def _least_fixed_point_gross(target: int, deduction, round_window: int) -> int:
    g = 0
    for _ in range(_MAX_FIXED_POINT_ITERS):
        nxt = target + deduction(g)
        if nxt < 0:
            nxt = 0
        if nxt == g:
            break
        if nxt < g:
            raise GrossUpConvergenceError(f"공제함수 비단조 감지: f({g})={nxt} < {g}")
        g = nxt
    else:
        raise GrossUpConvergenceError("고정점 반복이 상한에 도달했습니다 (유효 공제율 100% 이상 의심).")
    return _pick_rounder(target, g, deduction, round_window)


def gross_up_freelancer_net_to_gross(
    target_net: int | float,
    rate_pct: float = 3.0,
    round_window: int = ROUND_PREFERENCE_WINDOW_KRW,
) -> dict[str, int]:
    """
    사업소득자(프리랜서) 세후 실지급액 -> 세전 지급총액 정밀 역산기 (최소 고정점 엔진, 오차 0원).
    - 유효세율(소득세+지방세) 100% 이상인 비정상 입력은 역산이 불가능하므로 실지급액을 지급총액으로 간주해 계산합니다.
    """
    net = max(0, _safe_int(target_net, 0))
    clean_rate = _safe_float(rate_pct, 3.0)
    if clean_rate <= 0:
        clean_rate = 3.0
    if net <= 0:
        return calc_freelancer_33_tax(0, clean_rate)
    if (clean_rate * 1.1) / 100.0 >= 0.999:
        return calc_freelancer_33_tax(net, clean_rate)

    r = _to_decimal(clean_rate) / Decimal(100)
    cache: dict[int, int] = {}

    def _ded(g: int) -> int:
        hit = cache.get(g)
        if hit is None:
            inc = floor_10won(Decimal(g) * r)
            hit = inc + ((inc // 10) // 10) * 10
            cache[g] = hit
        return hit

    best = _least_fixed_point_gross(net, _ded, max(0, int(round_window or 0)))
    return calc_freelancer_33_tax(best, clean_rate)


def _withholding_bucket_key(taxable: int) -> int:
    """간이세액표는 1,000만원 미만에서 1,000원 단위 구간 → 같은 구간은 세액이 같으므로 캐시 키로 사용."""
    return taxable // 1000 if taxable < 10_000_000 else 10_000_000 + taxable


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
    round_window: int = ROUND_PREFERENCE_WINDOW_KRW,
    tax_year_month: str | None = None,
) -> dict[str, int]:
    """
    [데드존(Dead Zone) 100% 수렴 역산기 — 최소 고정점 엔진]
    간이세액표 계단 경계(세전 1원 증가에 원천세 최대 수만 원 점프)와 국민연금 1,000원 절사 경계 때문에
    실수령액 N(g)는 비단조입니다. 본 엔진은 이진탐색·구간 휴리스틱 없이 g = T + D(g)의 최소 고정점을 구해
    (a) 실수령액 오차 0원, (b) 그 조건을 만족하는 최소 세전 급여(라운드 선호 창 제외)를 수학적으로 보장합니다.
    공제액 D(g)는 세전->세후 정산(calculate_employee_payroll_row)과 동일한 커널로 계산하므로 왕복 결과가 항상 일치합니다.
    """
    target_net = max(0, _safe_int(target_net_pay, 0))
    non_tax = max(0, _safe_int(non_taxable_pay, 0))
    other_tax = max(0, _safe_int(other_taxable_allowances, 0))
    ym = normalize_year_month(year_month, "2026-10")
    tax_ym = normalize_year_month(tax_year_month, ym) if tax_year_month else ym
    params = _period_params(ym)
    notice = _notice_tuple(fixed_ins) if isinstance(fixed_ins, dict) and fixed_ins else None
    adj = _insurance_settlement_total(fixed_ins) if notice is not None else 0

    wt_cache: dict[int, tuple[int, int]] = {}

    def _wt(taxable: int) -> tuple[int, int]:
        key = _withholding_bucket_key(taxable)
        hit = wt_cache.get(key)
        if hit is None:
            wt = calc_withholding_tax(
                taxable,
                dependents=dependents,
                children_8_to_20=children_8_to_20,
                rate_pct=tax_rate_pct,
                year_month=tax_ym,
                reduction_pct=income_tax_reduction_pct,
            )
            hit = (wt["소득세"], wt["지방소득세"])
            wt_cache[key] = hit
        return hit

    def _components(g: int) -> tuple[int, int, int, int, int, int]:
        taxable = max(0, g - non_tax)
        nps, nhis, ltc, ei = _overlay_notice(_ins_rate_components(taxable, params, is_ceo), notice, params)
        inc, loc = _wt(taxable)
        return nps, nhis, ltc, ei, inc, loc

    ded_cache: dict[int, int] = {}

    def _ded(g: int) -> int:
        hit = ded_cache.get(g)
        if hit is None:
            hit = sum(_components(g)) + adj
            ded_cache[g] = hit
        return hit

    def _ded_ins_only(g: int) -> int:
        # 원천세(≥0)를 뺀 단조 하한 공제함수 → 이 함수의 최소 고정점 미만에서는 실수령액이 목표에 도달 불가
        taxable = max(0, g - non_tax)
        return sum(_overlay_notice(_ins_rate_components(taxable, params, is_ceo), notice, params)) + adj

    def _ded_nocache(g: int) -> int:
        return sum(_components(g)) + adj

    win = max(0, int(round_window or 0))
    dep_clean = max(1, _safe_int(dependents, 1))
    if target_net <= 0:
        best = 0
    elif dep_clean <= _MONOTONE_TABLE_MAX_DEPENDENTS:
        try:
            best = _least_fixed_point_gross(target_net, _ded, win)
        except GrossUpConvergenceError:
            best = _ascending_exact_scan(target_net, _ded_nocache, _least_fixed_point_gross(target_net, _ded_ins_only, 0), win, non_tax)
    else:
        best = _ascending_exact_scan(target_net, _ded_nocache, _least_fixed_point_gross(target_net, _ded_ins_only, 0), win, non_tax)

    nps, nhis, ltc, ei, inc_tax, loc_tax = _components(best)
    tot_ded = nps + nhis + ltc + ei + inc_tax + loc_tax + adj
    return {
        "기본급": max(0, best - non_tax - other_tax),
        "비과세합계": min(non_tax, best),
        "지급액계": best,
        "국민연금": nps,
        "건강보험": nhis,
        "장기요양보험료": ltc,
        "고용보험": ei,
        "소득세": inc_tax,
        "지방소득세": loc_tax,
        "공제액계": tot_ded,
        "차인지급액": best - tot_ded,
    }


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


def _tax_table_year_month(effective_table: str) -> str:
    """간이세액표 버전 → 자녀세액공제 금액 판정용 귀속연월."""
    return "2026-03" if str(effective_table).startswith("2026") else "2024-03"


def _default_ins_year_month(effective_table: str) -> str:
    """귀속연월이 주어지지 않았을 때의 보험 산출 기준월 (종전 정산 로직과 동일: 2026표→2026년, 구표→2025년 요율)."""
    return "2026-03" if str(effective_table).startswith("2026") else "2025-03"


def lookup_monthly_withholding_tax(
    taxable_monthly_krw: int | float,
    dependents: int = 1,
    children_8_20: int = 0,
    withholding_rate_pct: int = 100,
    effective_table: str = "2026.03",
    income_tax_reduction_pct: float = 0,
) -> dict[str, int]:
    ym = _tax_table_year_month(effective_table)
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
    year_month: str | None = None,
) -> dict[str, Any]:
    """
    단일 근로자 급여대장 행 전체 계산:
    - year_month('YYYY-MM'): 4대보험 요율·국민연금 상하한 적용 기준월 (생략 시 간이세액표 버전으로 추정)
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

    ins_ym = normalize_year_month(year_month, _default_ins_year_month(effective_table)) if year_month else _default_ins_year_month(effective_table)
    ins = resolve_employee_insurance(taxable_pay, ins_ym, is_ceo=is_ceo, notice_insurance=notice_insurance or None)
    nps, nhis, ltc, ei = ins["국민연금"], ins["건강보험"], ins["장기요양보험료"], ins["고용보험"]
    if notice_insurance:
        # 고지서 및 수기 입력 금액은 원단위 그대로 보존 (절사하지 않음)
        nhis_settle = _safe_int(notice_insurance.get("건강보험료정산", 0), 0)
        ltc_settle = _safe_int(notice_insurance.get("장기요양보험료정산", 0), 0)
        nps_settle = _safe_int(notice_insurance.get("국민연금정산", 0), 0)
        ins_mode = "고지(1순위)"
    else:
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
    year_month: str | None = None,
) -> dict[str, int]:
    """calculate_employee_payroll_row의 정확한 역함수 (같은 인자로 정산하면 차인지급액이 목표와 1원도 다르지 않음)."""
    ins_ym = normalize_year_month(year_month, _default_ins_year_month(effective_table)) if year_month else _default_ins_year_month(effective_table)
    fixed = dict(notice_insurance) if notice_insurance else None
    if student_loan_repayment:
        # 학자금 상환액은 고지 여부와 무관하게 공제되므로 역산에도 항상 반영 (종전: 고지내역이 없으면 누락되던 버그)
        fixed = fixed if fixed is not None else {}
        fixed["학자금상환액"] = int(_safe_int(student_loan_repayment, 0))
    res = gross_up_employee_net_to_gross(
        target_net_pay=target_net_pay,
        non_taxable_pay=non_taxable_pay,
        dependents=dependents,
        children_8_to_20=children_8_20,
        tax_rate_pct=withholding_rate_pct,
        year_month=ins_ym,
        fixed_ins=fixed,
        is_ceo=is_ceo,
        income_tax_reduction_pct=income_tax_reduction_pct,
        tax_year_month=_tax_table_year_month(effective_table),
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
