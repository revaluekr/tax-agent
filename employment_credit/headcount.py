# -*- coding: utf-8 -*-
"""
통합고용세액공제 결정론적 계산 엔진 통합 진입점 (headcount.py)
- 기존 코드(`from . import headcount as H` 또는 `from .headcount import ...`)와의 100% 하위 호환성을 유지하면서,
  실제 로직은 역할별로 분리된 4개 하위 모듈에서 불러옵니다:
  1) `hc_eligibility.py` : 날짜·나이·1년미만 경과조치·청년 유예기간·사후관리 코호트별 청년 간주 요건·계산방식 선택(calc_method_for)
  2) `hc_row_engine.py`  : 사원별 1~12월 재직·급여 매트릭스 산출 및 연도별 A·B 계산방식 동시 산출 집계
  3) `hc_credit_calc.py` : 2026 신법(A·B·C 점증형)·구법 사후관리(Case 1·2·3 추징 및 연속공제)·농특세·이월세액 계산
  4) `hc_review.py`      : 누락·오류·절세 후보(병역차감·고령자·경력단절 등) 자동 점검 및 월급여 이상감지
- `verify_golden_case_invariants()`는 `rules.py`와 `headcount.py` 양쪽 모두에서 동일하게 호출 가능합니다.
"""
from __future__ import annotations

from . import rules as R
from .hc_eligibility import *  # noqa: F401,F403
from .hc_eligibility import (  # noqa: F401 — 언더스코어 헬퍼 명시적 재노출
    _full_age_cached,
    _get_month_pay,
    _has_any_pay_record,
    _parse_date_str,
    _pick,
    _resolve_contract_year_corp_size,
    _resolve_retire_date_for_tenure,
)
from .hc_row_engine import *  # noqa: F401,F403
from .hc_credit_calc import *  # noqa: F401,F403
from .hc_credit_calc import _pick_summary_by_method  # noqa: F401
from .hc_review import *  # noqa: F401,F403

verify_golden_case_invariants = R.verify_golden_case_invariants