# -*- coding: utf-8 -*-
"""
통합고용세액공제 상시근로자 · 청년등 상시근로자 · 사후관리(추가납부세액) 통합 계산 및 12대 정밀 오류검토 엔진 (headcount.py)
근거: 조세특례제한법 제29조의8, 같은 법 시행령 제26조의8, 제11조의2, 제23조 제10항

※ [모듈 분할 구조 안내 — ui.py와 동일한 진입점(Facade) 방식]
매년 세법·시행령 개정 시 전체 2,000줄 코드를 통째로 건드리지 않고 해당 영역 파일만 독립적으로 교체·유지보수할 수 있도록
기능별로 4개의 하위 모듈로 분리되어 있으며, 본 `headcount.py`는 기존 코드(`ui.py`, `parsers.py` 등)와의 100% 호환을 위해
모든 함수와 상수를 그대로 다시 내보냅니다(re-export):
  1. `hc_eligibility.py` : 연도별 자격요건 · 청년 유예기간(2024 이전 / 2025 / 2026 이후) · 1년 미만 경과조치 · 날짜/절사 유틸리티
  2. `hc_row_engine.py`  : 2단계 개인별·월별 상시근로자 판정(`compute_row`) 및 연도별 합산·절사 집계(`year_totals`)
  3. `hc_credit_calc.py` : 3단계 세액공제(구법 / 2026 신법 A+B+C 점증형 / 최소고용증가인원 차감) 및 사후관리(`calc_legacy_post_management`, `calculate_tax_year_package`)
  4. `hc_review.py`      : 2단계·4단계 12대 법령·심판례·절세누락 정밀 오류 검토(`review`)
"""
from __future__ import annotations

from . import rules as R  # noqa: F401

from .hc_eligibility import (  # noqa: F401
    NEW_TENURE_RULE_FROM,
    NEW_YOUTH_DEF_FROM_COHORT,
    _full_age_cached,
    _get_month_pay,
    _has_any_pay_record,
    _parse_date_str,
    _pick,
    active_months,
    add_years,
    contract_age,
    contract_date,
    current_year_end_age,
    default_months_for_year,
    detect_last_paid_month,
    employed_at_month_end,
    fmt_date,
    format_date_dot,
    full_age,
    is_capital_area,
    is_excluded_industry,
    is_youth_month,
    is_youth_month_for_cohort,
    month_end,
    parse_date,
    suggest_exclusion,
    suggest_youth,
    tenure_under_1y,
    trunc2,
    valid_comparison_years_for_new_credit,
    was_youth_in_year_by_age,
    worked_in_year,
    youth_flag_old_def,
    youth_hold_years,
    youth_options,
)
from .hc_row_engine import (  # noqa: F401
    compute_row,
    regular_excluding_part_time,
    year_totals,
)
from .hc_credit_calc import (  # noqa: F401
    apply_minimum_increase_hurdle_2026,
    calc_increase_with_cap,
    calc_legacy_post_management,
    calc_minimum_hurdle_deduction_2026,
    calc_new_2026_credit_abc,
    calculate_tax_year_package,
    get_unit_rates,
)
from .hc_review import (  # noqa: F401
    review,
)