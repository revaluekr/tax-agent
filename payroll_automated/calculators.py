# -*- coding: utf-8 -*-
"""
인건비 자동화 - 수당 계산기 · 경고/주의사항 진단 · 법령 개정 실시간 모니터링 (calculators.py)
1) 연장·야간·휴일근로수당 계산기 (5인 이상 1.5배/2.0배 vs 5인 미만 1.0배 자동 분기 + 산식 + 근로기준법 조문 주석)
2) 주휴수당 계산기 (주 15시간 이상 요건 검증 + 비례 산식 + 근로기준법 제55조·시행령 제30조 조문 주석)
3) 경고·주의사항 통합 진단 엔진 (업로드 전에도 확인 가능한 하단 상시 법령 주석 포함)
4) 급여 관련 법령 및 간이세액표(소득세법 시행령 별표2) 실시간 법제처 API 연동 모니터링
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import date
from typing import Any, Dict, List, Optional

from .tax_tables import (
    MINIMUM_HOURLY_WAGE,
    MINIMUM_MONTHLY_WAGE_209H,
    NON_TAXABLE_LIMITS,
    RATES_2026,
    floor_10won,
    get_simplified_tax_revision_alerts,
)


_PAYROLL_LAW_CACHE_PATH = os.path.join(".workspace_storage", "payroll_law_daily_cache.json")
_PAYROLL_LAW_MEM_CACHE: Dict[str, Any] = {}
_LAW_FAIL_COOLDOWN_SEC: float = 600.0


# ─────────────────────────────────────────────────────────────
# 공통 법령 주석 데이터 (자료 업로드 전·후 모든 팝업 하단에 상시 표시)
# ─────────────────────────────────────────────────────────────

WARNING_MODAL_LEGAL_REFERENCES: List[Dict[str, str]] = [
    {
        "title": "최저임금법 제6조 (최저임금의 효력) 및 2026년 고용노동부 고시",
        "content": (
            "사용자는 최저임금의 적용을 받는 근로자에게 최저임금액 이상의 임금을 지급하여야 합니다. "
            "2026년 적용 최저시급은 10,320원이며, 주 40시간(유급주휴 8시간 포함 월 209시간) 기준 월 환산액은 2,156,880원입니다."
        ),
    },
    {
        "title": "소득세법 제12조 제3호 (비과세 근로소득 한도)",
        "content": (
            "• 식사대(더목): 식사를 제공받지 아니하는 근로자가 받는 월 20만원 이하의 식사대는 비과세합니다.\n"
            "• 자가운전보조금(자목·시행령 제12조제3호): 종업원 소유 차량을 본인 업무에 이용하고 실제 여비를 받지 않는 경우 월 20만원 이내 금액을 비과세합니다.\n"
            "• 출산·보육수당(머목): 근로자 또는 배우자의 출산이나 6세 이하 자녀 보육과 관련하여 받는 급여로서 월 20만원 이내의 금액을 비과세합니다."
        ),
    },
    {
        "title": "4대보험 자격취득·상실 및 보수월액 변경 신고 의무",
        "content": (
            "• 자격취득신고: 국민건강보험(입사일로부터 14일 이내, 국민건강보험법 제8조), 국민연금·고용·산재보험(입사일이 속한 달의 다음 달 15일까지, 국민연금법 제21조·고용보험법 제15조).\n"
            "• 자격상실신고: 퇴사 후 14일 이내(건강보험) 또는 퇴사일이 속한 달의 다음 달 15일까지(국민연금·고용보험) 자격상실 및 당해연도 보수총액을 신고하여야 합니다."
        ),
    },
    {
        "title": "소득세법 제164조·제164조의3 (지급명세서 및 간이지급명세서 제출 의무) 및 근로기준법 제2조",
        "content": (
            "근로소득 및 원천징수 대상 사업소득(3.3%)을 지급하는 자는 소득자의 성명·주민등록번호·지급액을 기재한 간이지급명세서를 제출하여야 하며, "
            "3.3% 사업소득자라 하더라도 사용자의 지휘·감독 아래 출퇴근 시간이 고정되고 매월 고정급을 지급받는 경우 근로기준법 제2조상 근로자로 판정될 수 있습니다."
        ),
    },
]

MONTHLY_REPORT_LEGAL_REFERENCES: List[Dict[str, str]] = [
    {
        "title": "근로소득 원천징수 및 간이세액표 (소득세법 제134조·제136조 및 시행령 제194조·별표2)",
        "content": (
            "원천징수의무자가 매월분 근로소득을 지급할 때에는 비과세 소득을 제외한 월 급여액과 공제대상가족수(기본 본인 1인) 및 "
            "8세 이상 20세 이하 자녀세액공제(2026.3.1. 개정: 1명 20,830원 / 2명 45,830원 / 3명 이상 1명당 +33,330원)를 반영하여 "
            "근로소득 간이세액표에 따른 소득세를 원천징수합니다."
        ),
    },
    {
        "title": "사업소득(3.3%) 원천징수 및 지방소득세 특별징수 (소득세법 제127조·제129조, 지방세법 제103조의13, 국세기본법 제86조)",
        "content": (
            "원천징수 대상 사업소득 지급 시 지급총액의 3%(소득세)와 소득세의 10%(지방소득세 0.3%, 합계 3.3%)를 원천징수하며, "
            "국세기본법 제86조(국세징수법 준용)에 따라 10원 미만의 끝수는 계산하지 아니하고(10원 미만 절사), "
            "2024.7.1. 이후 지급하는 인적용역 사업소득(계속·반복 활동)은 소득세법 제86조의 소액부징수(1,000원 미만 미징수) 대상에서 제외되어 1,000원 미만이어도 원천징수합니다."
        ),
    },
    {
        "title": "2026년 4대보험 법정 요율 근거 (국민연금법 부칙 제4조·국민건강보험법 시행령 제44조·노인장기요양보험법 시행령 제4조·고용보험료징수법 시행령 제12조)",
        "content": (
            "• 국민연금: 기준소득월액의 9.5% (근로자 4.75% / 사용자 4.75%, 상·하한 40만~637만원)\n"
            "• 건강보험 및 장기요양보험: 보수월액의 7.19% (근로자 3.595% / 사용자 3.595%), 장기요양보험료는 보수월액의 0.9448% (= 건강보험료 × 0.9448 / 7.19)\n"
            "• 고용보험: 실업급여(근로자 0.9% / 사업주 0.9%) + 사업주 부담 고용안정·직능개발(150인 미만 0.25%, 150인 이상 우선지원대상기업 0.45%, 150~999인 0.65%, 1,000인 이상 0.85%)"
        ),
    },
    {
        "title": "임금명세서 교부 및 산출방법 기재 의무 (근로기준법 제48조 제2항 및 시행령 제27조의2)",
        "content": (
            "사용자는 임금을 지급할 때 근로자에게 임금의 구성항목·계산방법(연장·야간·휴일근로시간 수 등) 및 공제내역을 적은 임금명세서를 서면 또는 전자문서로 교부하여야 합니다."
        ),
    },
]


# ─────────────────────────────────────────────────────────────
# 1. 연장·야간·휴일근로수당 계산기
# ─────────────────────────────────────────────────────────────

def calculate_overtime_night_holiday_allowance(
    ordinary_hourly_wage: int = 0,
    monthly_ordinary_wage: int = 0,
    monthly_contract_hours: float = 209.0,
    overtime_hours: float = 0.0,
    night_hours: float = 0.0,
    holiday_hours_within_8: float = 0.0,
    holiday_hours_over_8: float = 0.0,
    is_5_or_more_workers: bool = True,
    year: int = 2026,
) -> Dict[str, Any]:
    """
    연장·야간·휴일근로수당 정밀 계산기:
    - 통상시급이 직접 입력되지 않은 경우 월 통상임금 / 월 소정근로시간(기본 209시간)으로 자동 산출
    - 상시근로자 5인 이상:
      * 연장근로: 통상시급 × 시간 × 1.5
      * 야간근로(22:00~06:00): 통상시급 × 시간 × 0.5 가산
      * 휴일근로(8시간 이내): 통상시급 × 시간 × 1.5
      * 휴일근로(8시간 초과): 통상시급 × 시간 × 2.0
    - 상시근로자 5인 미만 (근로기준법 제11조·제56조 적용 제외):
      * 연장·휴일근로 가산수당(0.5배/1.0배) 미적용 -> 1.0배 기본 시급만 산출, 야간가산 0원
    """
    if ordinary_hourly_wage <= 0 and monthly_ordinary_wage > 0 and monthly_contract_hours > 0:
        hourly = int(round(monthly_ordinary_wage / monthly_contract_hours))
    else:
        hourly = int(ordinary_hourly_wage)

    min_wage = MINIMUM_HOURLY_WAGE.get(year, 10_320)
    below_min_wage = hourly > 0 and hourly < min_wage

    if is_5_or_more_workers:
        ot_mult = 1.5
        night_mult = 0.5
        hol_le8_mult = 1.5
        hol_gt8_mult = 2.0
    else:
        ot_mult = 1.0
        night_mult = 0.0
        hol_le8_mult = 1.0
        hol_gt8_mult = 1.0

    overtime_pay = int(round(hourly * overtime_hours * ot_mult))
    night_pay = int(round(hourly * night_hours * night_mult))
    holiday_le8_pay = int(round(hourly * holiday_hours_within_8 * hol_le8_mult))
    holiday_gt8_pay = int(round(hourly * holiday_hours_over_8 * hol_gt8_mult))
    holiday_total_pay = holiday_le8_pay + holiday_gt8_pay
    total_allowance = overtime_pay + night_pay + holiday_total_pay

    formulas = [
        f"통상시급: {hourly:,}원"
        + (f" (= 월 통상임금 {monthly_ordinary_wage:,}원 / {monthly_contract_hours:g}시간)" if monthly_ordinary_wage > 0 else ""),
        f"연장근로수당: {hourly:,}원 × {overtime_hours:g}시간 × {ot_mult}배 = {overtime_pay:,}원",
        f"야간근로가산수당: {hourly:,}원 × {night_hours:g}시간 × {night_mult}배 = {night_pay:,}원",
        f"휴일근로수당(8시간 이내): {hourly:,}원 × {holiday_hours_within_8:g}시간 × {hol_le8_mult}배 = {holiday_le8_pay:,}원",
        f"휴일근로수당(8시간 초과): {hourly:,}원 × {holiday_hours_over_8:g}시간 × {hol_gt8_mult}배 = {holiday_gt8_pay:,}원",
        f"합계 수당: {total_allowance:,}원 (급여대장 반영 시 연장+야간={overtime_pay + night_pay:,}원 / 휴일={holiday_total_pay:,}원)",
    ]

    legal_references = [
        {
            "title": "근로기준법 제56조 (연장·야간 및 휴일 근로 가산수당)",
            "content": (
                "① 사용자는 연장근로(제53조·제59조 및 제69조 단서에 따라 연장된 시간의 근로)에 대하여는 통상임금의 100분의 50 이상을 가산하여 근로자에게 지급하여야 한다.\n"
                "② 제1항에도 불구하고 사용자는 휴일근로에 대하여는 다음 각 호의 기준에 따른 금액 이상을 가산하여 근로자에게 지급하여야 한다.\n"
                "  1. 8시간 이내의 휴일근로: 통상임금의 100분의 50\n"
                "  2. 8시간을 초과한 휴일근로: 통상임금의 100분의 100\n"
                "③ 사용자는 야간근로(오후 10시부터 다음 날 오전 6시 사이의 근로)에 대하여는 통상임금의 100분의 50 이상을 가산하여 근로자에게 지급하여야 한다."
            ),
        },
        {
            "title": "근로기준법 시행령 제6조 (통상임금의 산정 기준)",
            "content": (
                "통상임금이란 근로자에게 정기적이고 일률적으로 소정근로 또는 총 근로에 대하여 지급하기로 정한 시간급 금액·일급 금액·주급 금액·월급 금액을 말하며, "
                "월급 금액으로 정한 임금의 시간급 산정 시 월의 통상임금 산정 기준시간 수(주 40시간제 기준 유급주휴 포함 월 약 209시간)로 나눈 금액으로 합니다."
            ),
        },
        {
            "title": "근로기준법 제11조 제2항 및 시행령 별표1 (상시 4명 이하 사업장 적용 범위 특례)",
            "content": (
                "상시 4명 이하의 근로자를 사용하는 사업 또는 사업장에 대하여는 법 제56조(연장·야간·휴일 가산수당) 규정이 적용되지 아니하므로, "
                "연장·휴일근로 시 가산율(50%/100%) 없이 실제 근로시간에 대한 1.0배 통상시급을 지급합니다."
            ),
        },
    ]

    return {
        "hourly_wage": hourly,
        "min_hourly_wage": min_wage,
        "below_min_wage": below_min_wage,
        "is_5_or_more_workers": is_5_or_more_workers,
        "overtime_pay": overtime_pay,
        "night_pay": night_pay,
        "overtime_and_night_pay": overtime_pay + night_pay,
        "holiday_pay": holiday_total_pay,
        "total_allowance": total_allowance,
        "formulas": formulas,
        "legal_references": legal_references,
    }


# ─────────────────────────────────────────────────────────────
# 2. 주휴수당 계산기
# ─────────────────────────────────────────────────────────────

def calculate_weekly_holiday_allowance(
    hourly_wage: int,
    weekly_contract_hours: float,
    full_attendance: bool = True,
    weeks_in_month: float = 4.345,
    year: int = 2026,
) -> Dict[str, Any]:
    """
    주휴수당 정밀 계산기:
    - 주 소정근로시간이 15시간 이상이고 소정근로일을 개근한 경우 지급 대상
    - 1주 주휴시간 = min(weekly_contract_hours, 40) / 40 × 8시간 (최대 8시간)
    - 1주 주휴수당 = 1주 주휴시간 × 약정시급
    - 월 환산 주휴수당(4.345주 기준) 및 주급/월급 합산액 동시 산출
    """
    min_wage = MINIMUM_HOURLY_WAGE.get(year, 10_320)
    eligible = weekly_contract_hours >= 15.0 and full_attendance

    if eligible:
        capped_hours = min(float(weekly_contract_hours), 40.0)
        weekly_holiday_hours = round((capped_hours / 40.0) * 8.0, 2)
        weekly_holiday_pay = int(round(weekly_holiday_hours * hourly_wage))
    else:
        weekly_holiday_hours = 0.0
        weekly_holiday_pay = 0

    weekly_base_pay = int(round(weekly_contract_hours * hourly_wage))
    weekly_total_pay = weekly_base_pay + weekly_holiday_pay

    monthly_work_hours = round(weekly_contract_hours * weeks_in_month, 1)
    monthly_holiday_hours = round(weekly_holiday_hours * weeks_in_month, 1)
    monthly_total_hours = round(monthly_work_hours + monthly_holiday_hours, 1)
    monthly_holiday_pay = int(round(weekly_holiday_pay * weeks_in_month))
    monthly_base_pay = int(round(weekly_base_pay * weeks_in_month))
    monthly_total_pay = monthly_base_pay + monthly_holiday_pay

    if weekly_contract_hours < 15.0:
        eligibility_reason = "주 소정근로시간 15시간 미만으로 주휴수당 지급 대상이 아닙니다 (근로기준법 제18조 제3항)."
    elif not full_attendance:
        eligibility_reason = "해당 주 소정근로일 개근 요건 미충족으로 해당 주 주휴수당이 발생하지 않습니다."
    else:
        eligibility_reason = "주 15시간 이상 근무 및 소정근로일 개근 요건을 충족하여 주휴수당 지급 대상입니다."

    formulas = [
        f"수급 요건 판정: {eligibility_reason}",
        f"1주 유급주휴시간: min({weekly_contract_hours:g}시간, 40시간) / 40 × 8시간 = {weekly_holiday_hours:g}시간",
        f"1주 주휴수당: {weekly_holiday_hours:g}시간 × {hourly_wage:,}원 = {weekly_holiday_pay:,}원",
        f"월 환산 주휴수당 ({weeks_in_month}주 기준): {weekly_holiday_pay:,}원 × {weeks_in_month}주 = {monthly_holiday_pay:,}원",
        f"월 소정근로시간 합계 (기본+주휴): {monthly_work_hours:g}시간 + {monthly_holiday_hours:g}시간 = {monthly_total_hours:g}시간",
        f"월 예상 기본급 (주휴 포함): {monthly_base_pay:,}원 + {monthly_holiday_pay:,}원 = {monthly_total_pay:,}원",
    ]

    legal_references = [
        {
            "title": "근로기준법 제55조 제1항 및 시행령 제30조 제1항 (유급휴일·주휴수당)",
            "content": (
                "사용자는 근로자에게 1주에 평균 1회 이상의 유급휴일을 보장하여야 하며(법 제55조 제1항), "
                "그 유급휴일은 1주 동안의 소정근로일을 개근한 자에게 주어야 합니다(시행령 제30조 제1항)."
            ),
        },
        {
            "title": "근로기준법 제18조 제2항·제3항 및 시행령 제9조·별표2 (단시간근로자의 근로조건 결정 기준 및 적용 제외)",
            "content": (
                "• 비례 산정 원칙(별표2): 단시간근로자의 유급주휴 시간은 통상근로자의 1주 소정근로시간(40시간)에 대한 단시간근로자의 소정근로시간 비율로 산정합니다.\n"
                "• 초단시간근로자 적용 제외(제18조 제3항): 4주 동안(4주 미만으로 근로하는 경우에는 그 기간)을 평균하여 1주 동안의 소정근로시간이 "
                "15시간 미만인 근로자에 대하여는 제55조(주휴일)와 제54조(휴게)를 적용하지 아니합니다."
            ),
        },
    ]

    return {
        "eligible": eligible,
        "eligibility_reason": eligibility_reason,
        "hourly_wage": hourly_wage,
        "min_hourly_wage": min_wage,
        "below_min_wage": hourly_wage < min_wage,
        "weekly_contract_hours": weekly_contract_hours,
        "weekly_holiday_hours": weekly_holiday_hours,
        "weekly_holiday_pay": weekly_holiday_pay,
        "weekly_total_pay": weekly_total_pay,
        "monthly_holiday_pay": monthly_holiday_pay,
        "monthly_total_hours": monthly_total_hours,
        "monthly_total_pay": monthly_total_pay,
        "formulas": formulas,
        "legal_references": legal_references,
    }


# ─────────────────────────────────────────────────────────────
# 3. 경고·주의사항 통합 진단 엔진 (전월 대비 변동 + 최저임금 + 비과세 + 보험괴리)
# ─────────────────────────────────────────────────────────────

def analyze_payroll_warnings(
    employees: List[Dict[str, Any]],
    freelancers: Optional[List[Dict[str, Any]]] = None,
    prev_employees: Optional[List[Dict[str, Any]]] = None,
    prev_freelancers: Optional[List[Dict[str, Any]]] = None,
    year: int = 2026,
) -> Dict[str, Any]:
    items: List[Dict[str, str]] = []
    min_hourly = MINIMUM_HOURLY_WAGE.get(year, 10_320)
    min_monthly_209 = MINIMUM_MONTHLY_WAGE_209H.get(year, 2_156_880)

    new_hires: List[str] = []
    retirees: List[str] = []
    pay_changes: List[str] = []

    prev_emp_map = {
        str(e.get("성명", "")).strip(): e for e in (prev_employees or []) if e.get("성명")
    }
    curr_emp_map = {
        str(e.get("성명", "")).strip(): e for e in (employees or []) if e.get("성명")
    }

    if prev_emp_map:
        for name, emp in curr_emp_map.items():
            if name not in prev_emp_map:
                new_hires.append(name)
                items.append({
                    "level": "주의",
                    "category": "취득신고 대상",
                    "target": name,
                    "message": f"[취득신고 대상] 전월 급여대장에 없던 신규 인원입니다. 입사일({emp.get('입사일') or '미입력'}) 및 4대보험 자격취득신고 여부를 확인하세요.",
                    "law": "고용보험 및 산업재해보상보험의 보험료징수 등에 관한 법률 / 국민건강보험법(입사일 다음달 15일 이내 신고)",
                })
            else:
                prev_gross = int(prev_emp_map[name].get("지급액계", 0))
                curr_gross = int(emp.get("지급액계", 0))
                if prev_gross > 0:
                    diff_ratio = (curr_gross - prev_gross) / prev_gross
                    if abs(diff_ratio) >= 0.20:
                        pct_str = f"{diff_ratio * 100:+.1f}%"
                        pay_changes.append(f"{name} ({pct_str})")
                        items.append({
                            "level": "주의",
                            "category": "급여변동",
                            "target": name,
                            "message": f"[급여변동] 전월 지급액계({prev_gross:,}원) 대비 당월({curr_gross:,}원) {pct_str} 변동되었습니다. 보수월액 변경신고 또는 연장·상여 반영 내역을 확인하세요.",
                            "law": "국민건강보험법 제70조(보수월액 변경 신청)",
                        })

        for prev_name in prev_emp_map:
            if prev_name not in curr_emp_map:
                retirees.append(prev_name)
                items.append({
                    "level": "주의",
                    "category": "상실신고 대상",
                    "target": prev_name,
                    "message": "[상실신고 대상] 전월 급여대장에 있던 인원이 당월 명단에서 제외되었습니다. 퇴사 처리 및 4대보험 자격상실·보수총액신고 대상인지 확인하세요.",
                    "law": "국민건강보험법 제11조(퇴사일 후 14일 이내 상실신고) / 고용보험법 제15조",
                })

    for emp in employees or []:
        name = str(emp.get("성명", "")).strip()
        if not name:
            continue

        retire_dt = str(emp.get("퇴사일", "")).strip()
        if retire_dt and name not in retirees:
            retirees.append(name)
            items.append({
                "level": "주의",
                "category": "상실신고 대상",
                "target": name,
                "message": f"[상실신고 대상] 퇴사일({retire_dt})이 입력되어 있습니다. 중도퇴사자 급여 일할계산, 퇴직소득 정산 및 4대보험 상실신고를 확인하세요.",
                "law": "소득세법 제137조(중도퇴직자 연말정산) 및 4대보험 자격상실 규정",
            })

        base_pay = int(emp.get("기본급", 0))
        hourly_wage = int(emp.get("약정시급", 0))
        monthly_hours = float(emp.get("월근무시간", 209.0) or 209.0)
        absence_ded = int(emp.get("결근공제", 0))

        if hourly_wage > 0 and hourly_wage < min_hourly:
            items.append({
                "level": "경고",
                "category": "최저임금 미달",
                "target": name,
                "message": f"약정시급({hourly_wage:,}원)이 {year}년 최저시급({min_hourly:,}원)에 미달합니다.",
                "law": "최저임금법 제6조 (최저임금의 효력 - 위반 시 3년 이하 징역 또는 2천만원 이하 벌금)",
            })
        elif monthly_hours >= 209.0 and absence_ded == 0 and not retire_dt and 0 < base_pay < min_monthly_209:
            items.append({
                "level": "경고",
                "category": "최저임금 미달",
                "target": name,
                "message": f"주 40시간(월 209시간) 기준 기본급({base_pay:,}원)이 {year}년 월 환산 최저임금({min_monthly_209:,}원)보다 낮습니다.",
                "law": "최저임금법 제6조",
            })

        meal = int(emp.get("식대", 0))
        car = int(emp.get("자가운전보조금", 0))
        if meal > NON_TAXABLE_LIMITS["식대"]:
            excess = meal - NON_TAXABLE_LIMITS["식대"]
            items.append({
                "level": "주의",
                "category": "비과세 한도 초과",
                "target": name,
                "message": f"식대({meal:,}원)가 월 비과세 한도(200,000원)를 {excess:,}원 초과합니다. 초과분({excess:,}원)은 과세 급여에 자동 합산되었습니다.",
                "law": "소득세법 제12조 제3호 더목 (비과세 식사대 월 20만원 한도)",
            })
        if car > NON_TAXABLE_LIMITS["자가운전보조금"]:
            excess_car = car - NON_TAXABLE_LIMITS["자가운전보조금"]
            items.append({
                "level": "주의",
                "category": "비과세 한도 초과",
                "target": name,
                "message": f"자가운전보조금({car:,}원)이 월 비과세 한도(200,000원)를 {excess_car:,}원 초과합니다. 초과분은 과세 급여에 자동 합산되었습니다.",
                "law": "소득세법 시행령 제12조 제3호 (자가운전보조금 월 20만원 한도)",
            })

        taxable = int(emp.get("과세급여", max(0, int(emp.get("지급액계", 0)) - meal - car)))
        if taxable > 0 and str(emp.get("보험적용구분", "")).startswith("고지"):
            expected_hi = floor_10won(taxable * RATES_2026["health_insurance_employee"])
            actual_hi = int(emp.get("건강보험", 0))
            if expected_hi > 0 and actual_hi > 0:
                gap_ratio = abs(actual_hi - expected_hi) / expected_hi
                if gap_ratio >= 0.15:
                    items.append({
                        "level": "주의",
                        "category": "보수월액 괴리",
                        "target": name,
                        "message": f"고지 건강보험료({actual_hi:,}원)와 당월 과세급여 기준 산출액({expected_hi:,}원, 3.595%)이 {gap_ratio * 100:.1f}% 차이납니다. 기준보수월액과 당월 실지급 급여 차이를 확인하세요.",
                        "law": "국민건강보험법 제70조",
                    })

        rrn_val = str(emp.get("주민등록번호", "")).strip()
        if not rrn_val:
            items.append({
                "level": "주의",
                "category": "인적사항 누락",
                "target": name,
                "message": "주민등록번호가 비어 있습니다. 위하고 업로드 및 생년월일 암호 설정 전에 확인하세요.",
                "law": "소득세법 제164조(지급명세서의 제출)",
            })
        elif "*" in rrn_val:
            items.append({
                "level": "주의",
                "category": "주민번호 마스킹",
                "target": name,
                "message": f"주민등록번호 뒷자리가 마스킹({rrn_val})되어 있습니다. 국민연금 결정내역 PDF 업로드 또는 직접 입력으로 보완할 수 있습니다.",
                "law": "소득세법 제164조",
            })

    prev_free_map = {
        str(f.get("성명", "")).strip(): f for f in (prev_freelancers or []) if f.get("성명")
    }
    for fr in freelancers or []:
        fname = str(fr.get("성명", "")).strip()
        if not fname:
            continue
        if not str(fr.get("주민등록번호", "")).strip():
            items.append({
                "level": "경고",
                "category": "주민등록번호 누락",
                "target": f"{fname} (사업소득)",
                "message": "사업소득자 주민등록번호가 누락되어 위하고 사업소득자료 업로드 및 간이지급명세서 제출 시 오류가 발생합니다.",
                "law": "소득세법 제164조의3 (거주자의 사업소득 간이지급명세서 제출)",
            })
        if fname in prev_free_map:
            prev_amt = int(prev_free_map[fname].get("지급총액", 0))
            curr_amt = int(fr.get("지급총액", 0))
            if prev_amt > 0 and prev_amt == curr_amt:
                items.append({
                    "level": "주의",
                    "category": "프리랜서 반복 지급",
                    "target": f"{fname} (사업소득)",
                    "message": f"전월과 동일한 세전 금액({curr_amt:,}원)이 반복 지급되고 있습니다. 출퇴근 시간 지정·업무 지휘감독이 있는 경우 근로기준법상 근로자로 판정될 유의사항이 있습니다.",
                    "law": "근로기준법 제2조 제1항 제1호 (근로자성 판단 기준)",
                })

    danger_cnt = sum(1 for x in items if x["level"] == "경고")
    warn_cnt = sum(1 for x in items if x["level"] == "주의")

    if danger_cnt > 0:
        status_color = "red"
    elif warn_cnt > 0:
        status_color = "yellow"
    else:
        status_color = "gray"

    return {
        "status_color": status_color,
        "danger_count": danger_cnt,
        "warning_count": warn_cnt,
        "total_count": len(items),
        "items": items,
        "movement_summary": {
            "new_hires": new_hires,
            "retirees": retirees,
            "pay_changes": pay_changes,
        },
        "legal_references": WARNING_MODAL_LEGAL_REFERENCES,
    }


# ─────────────────────────────────────────────────────────────
# 4. 급여 관련 법령 · 시행령 별표2(간이세액표) 실시간 법제처 연동 모니터링
# ─────────────────────────────────────────────────────────────

def _parse_law_search_first_meta(raw_search_txt: Any, target_law_name: str) -> Dict[str, str]:
    clean_target = re.sub(r"\s+", "", target_law_name)
    if isinstance(raw_search_txt, list):
        best: Dict[str, str] = {}
        for row in raw_search_txt:
            if not isinstance(row, dict):
                continue
            nm = re.sub(r"\s+", "", str(row.get("법령명한글") or row.get("법령명") or ""))
            if nm != clean_target:
                continue
            no = re.sub(r"\D", "", str(row.get("공포번호") or ""))
            pd_raw = re.sub(r"\D", "", str(row.get("공포일자") or ""))
            ed_raw = re.sub(r"\D", "", str(row.get("시행일자") or ""))
            if not no:
                continue
            if best and int(best["prom_no"]) >= int(no):
                continue
            best = {
                "law_name": str(row.get("법령명한글") or row.get("법령명") or "").strip(),
                "prom_no": no,
                "prom_date": f"{pd_raw[:4]}.{pd_raw[4:6]}.{pd_raw[6:8]}" if len(pd_raw) >= 8 else pd_raw,
                "effective_date": f"{ed_raw[:4]}.{ed_raw[4:6]}.{ed_raw[6:8]}" if len(ed_raw) >= 8 else ed_raw,
                "law_id": str(row.get("법령ID") or "").strip(),
            }
        return best

    if not raw_search_txt or not isinstance(raw_search_txt, str) or raw_search_txt.startswith("\u274c"):
        return {}
    for line in raw_search_txt.splitlines():
        m = re.search(
            r"\*\*([^*]+)\*\*\s*\[([^\]]*?제(\d+)호[^\]]*?)\|\s*공포:\s*(\d{8})\s*\|\s*시행:\s*(\d{8})\]\s*\(ID:\s*`?(\d+)`?\)",
            line,
        )
        if m:
            found_name = re.sub(r"\s+", "", m.group(1))
            if found_name == clean_target:
                ed = m.group(5)
                pd_str = m.group(4)
                return {
                    "law_name": m.group(1).strip(),
                    "prom_no": m.group(3).strip(),
                    "prom_date": f"{pd_str[:4]}.{pd_str[4:6]}.{pd_str[6:]}",
                    "effective_date": f"{ed[:4]}.{ed[4:6]}.{ed[6:]}",
                    "law_id": m.group(6).strip(),
                }
    return {}


def check_payroll_law_revisions(force_refresh: bool = False) -> List[Dict[str, str]]:
    base_alerts = get_simplified_tax_revision_alerts()
    today_str = date.today().isoformat()
    now_ts = time.time()

    if not force_refresh and _PAYROLL_LAW_MEM_CACHE.get("checked_date") == today_str:
        cached_items = _PAYROLL_LAW_MEM_CACHE.get("items")
        if isinstance(cached_items, list) and cached_items:
            if not _PAYROLL_LAW_MEM_CACHE.get("api_failed") or (now_ts - float(_PAYROLL_LAW_MEM_CACHE.get("ts") or 0.0)) < _LAW_FAIL_COOLDOWN_SEC:
                return cached_items

    if not force_refresh and os.path.exists(_PAYROLL_LAW_CACHE_PATH):
        try:
            with open(_PAYROLL_LAW_CACHE_PATH, "r", encoding="utf-8") as f:
                disk_data = json.load(f)
            if disk_data.get("checked_date") == today_str and isinstance(disk_data.get("items"), list) and not disk_data.get("api_failed"):
                _PAYROLL_LAW_MEM_CACHE.update({
                    "checked_date": today_str,
                    "items": disk_data["items"],
                    "api_failed": False,
                    "ts": now_ts,
                })
                return disk_data["items"]
        except Exception:
            pass

    api_called_ok = False
    try:
        import law_api

        has_key = bool(law_api._live_law_key()) if hasattr(law_api, "_live_law_key") else True
        if has_key and hasattr(law_api, "search_law_data"):
            for item in base_alerts:
                law_name = item["law"]
                raw_res = law_api.search_law_data(law_name, target="law")
                meta = _parse_law_search_first_meta(raw_res, law_name)
                if meta:
                    api_called_ok = True
                    item["effective_date"] = meta["effective_date"]
                    item["live_prom_no"] = meta["prom_no"]
                    item["live_prom_date"] = meta["prom_date"]
                    item["checked_at"] = today_str
                    base_no = str(item.get("baseline_prom_no") or "").strip()
                    if base_no and meta["prom_no"].isdigit() and base_no.isdigit():
                        if int(meta["prom_no"]) > int(base_no):
                            item["status"] = "new_revision"
                            item["summary"] = (
                                f"[신규 개정 감지: 제{meta['prom_no']}호 (공포 {meta['prom_date']} · 시행 {meta['effective_date']})] "
                                + item["summary"]
                            )
    except Exception:
        pass

    for item in base_alerts:
        item.setdefault("display_name", item["law"])
        item.setdefault("checked_at", today_str)

    _PAYROLL_LAW_MEM_CACHE.update({
        "checked_date": today_str,
        "items": base_alerts,
        "api_failed": not api_called_ok,
        "ts": now_ts,
    })
    if api_called_ok:
        try:
            os.makedirs(os.path.dirname(_PAYROLL_LAW_CACHE_PATH), exist_ok=True)
            with open(_PAYROLL_LAW_CACHE_PATH, "w", encoding="utf-8") as f:
                json.dump({"checked_date": today_str, "items": base_alerts, "api_failed": False}, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    return base_alerts
