# -*- coding: utf-8 -*-
"""
통합고용세액공제(조세특례제한법 제29조의8) — 법령 상수·공제단가·화면 선택지 (2023~2028년 귀속 통합)
법이 바뀌면 이 파일만 고치면 되도록 숫자·문구를 한곳에 모았습니다.

[핵심 반영 법령 — 2023~2028년 귀속 완벽 대응]
- 조세특례제한법 제29조의8 (법률 제20615호·제21065호, 2025.12.31 및 2026.1.2 개정)
- 조세특례제한법 시행령 제26조의8 (대통령령 제34268호·제35345호·제35945호, 2024.2.29 / 2025.2.28 / 2025.12.30 개정)
- 상시근로자 제외: 조특령 제26조의8 제2항 및 제7항(2024.2.29 신설 출산전후휴가자 대체인력 채용 시 산정 제외 특례)
- 인원 계산: 매월 말 현재 상시근로자 합 ÷ 사업연도 개월수 (100분의 1 미만 버림)
  * 2025.02 개정 이슈 비교용: 근로자별 (근무개월÷사업연도 월수) 절사 합산 방식 동시 지원
- 단시간근로자: 월평균 60시간 이상 0.5명 / 상생요건 충족 시 0.75명 (단시간 제외 상시 0.75명 이상 및 비감소 요건)
- 청년등 상시근로자:
  * 청년 정규직: 근로계약 체결일 현재 15~34세(병역 최대 72개월 차감), 기간제·단시간 제외
  * 사후관리 연령경과 간주 특례(구 조특령 제26조의8 제5항 / 현행 4년(일반기업 3년) 보유 특례):
    최초 공제연도에 청년등이었던 근로자는 이후 사후관리·연속공제 연도에 34세를 초과해도 계속 청년등으로 인정
  * 60세 이상 고령자, 장애인, 국가유공자등
  * 경력단절 근로자 (2024귀속: 경력단절 여성 동일업종 / 2025.7.1 이후: 경력단절 남성·가족돌봄 사유 포함)
  * 북한이탈주민 (2025.2.28 시행령 개정: 2025년 귀속부터 추가)
"""
from __future__ import annotations

# ══════════════════════════════════════════════════════════════════
# 1. 귀속사업연도 및 기업·지역 구분
# ══════════════════════════════════════════════════════════════════
SUPPORTED_TAX_YEARS = [2024, 2025, 2026, 2027, 2028]
TAX_YEARS = SUPPORTED_TAX_YEARS
DEFAULT_TAX_YEAR = 2026
YEARS_SHOWN_BACK = 2

CORP_SIZES = ["중소기업", "중견기업", "일반기업"]
REGIONS = ["수도권", "수도권 외"]
CAPITAL_AREA_KEYWORDS = ["서울", "인천", "경기"]

EXCLUDED_INDUSTRY_KEYWORDS = [
    "호텔업", "여관업", "모텔", "여인숙",
    "일반유흥주점", "무도유흥주점", "단란주점", "유흥주점",
    "무도장", "카지노", "사행",
]
EXCLUDED_INDUSTRY_EXCEPTIONS = ["관광숙박", "관광호텔", "외국인전용", "관광유흥"]


# ══════════════════════════════════════════════════════════════════
# 2. 고용유형 (대분류) 및 상시근로자 제외사유
# ══════════════════════════════════════════════════════════════════
EMP_CEO = "대표이사"
EMP_EXEC = "임원"
EMP_REGULAR = "정규직"
EMP_PT_050 = "단시간(60시간 이상)"
EMP_PT_075 = "단시간(60시간 이상+요건충족)"
EMP_PT_UNDER = "단시간(60시간 미만)"
EMP_FIXED = "계약직(기간제)"

EMP_TYPES = [EMP_CEO, EMP_EXEC, EMP_REGULAR, EMP_PT_050, EMP_PT_075, EMP_PT_UNDER, EMP_FIXED]
EMPLOYMENT_TYPES = EMP_TYPES

EMP_WEIGHT = {
    EMP_REGULAR: 1.0,
    EMP_FIXED: 1.0,
    EMP_PT_050: 0.5,
    EMP_PT_075: 0.75,
}

EMP_AUTO_EXCLUDE = {
    EMP_CEO: "대표이사",
    EMP_EXEC: "임원",
    EMP_PT_UNDER: "월평균 60시간 미만 단시간근로자",
}
EXCLUDED_BY_EMP_TYPE = EMP_AUTO_EXCLUDE

EMP_NOT_YOUTH_REGULAR = {EMP_PT_050, EMP_PT_075, EMP_FIXED}

EXCL_NONE = "해당없음"
EXCL_UNDER_1Y = "근로계약 1년미만"
EXCL_NO_WHT = "원천징수·4대보험 납부사실 모두 없음"
EXCL_FOREIGN = "외국인 근로자"
EXCL_MATERNITY_REPLACED = "출산전후휴가자(대체인력채용)"  # 조특령 제26조의8 제7항 (2024.2.29 신설)
EXCL_HIGH_SALARY = "고액연봉자(7,000만원 초과·추계특례 제외)"

EXCL_REASONS = [
    EXCL_NONE,
    "대표이사",
    "임원",
    "최대주주",
    "최대주주의 배우자",
    "최대주주의 직계존비속 등",
    EXCL_UNDER_1Y,
    "월평균 60시간 미만 단시간근로자",
    EXCL_NO_WHT,
    EXCL_FOREIGN,
    EXCL_MATERNITY_REPLACED,
    EXCL_HIGH_SALARY,
]
EXCLUSION_REASONS = EXCL_REASONS


# ══════════════════════════════════════════════════════════════════
# 3. 청년등 상시근로자 구분 및 연령 요건
# ══════════════════════════════════════════════════════════════════
YOUTH_NONE = "해당없음(일반)"
YOUTH_YOUNG = "취업시 청년(4년)"
YOUTH_SENIOR = "취업시 60세 이상"
YOUTH_DISABLED = "장애인 등"
YOUTH_CAREER = "경력단절 근로자"
YOUTH_NK = "북한이탈주민"

YOUTH_TYPES = [YOUTH_NONE, YOUTH_YOUNG, YOUTH_SENIOR, YOUTH_DISABLED, YOUTH_CAREER, YOUTH_NK]
YOUTH_TYPES_NON_REGULAR = [YOUTH_NONE, YOUTH_SENIOR, YOUTH_DISABLED, YOUTH_CAREER, YOUTH_NK]

YOUTH_AGE_MIN = 15
YOUTH_AGE_MAX = 34
YOUTH_MIN_AGE = YOUTH_AGE_MIN
YOUTH_MAX_AGE = YOUTH_AGE_MAX
SENIOR_AGE = 60
AGE_60_PLUS = SENIOR_AGE
MILITARY_MAX_MONTHS = 72
YOUTH_HOLD_YEARS_SME = 4
YOUTH_HOLD_YEARS_LARGE = 3

MONTH_AUTO = "자동"
MONTH_CHOICES = [MONTH_AUTO, "1", "0.75", "0.5", "0"]


# ══════════════════════════════════════════════════════════════════
# 4. 1인당 공제단가 (단위: 만원) — 구법(2023~2025) & 개정 신법(2026~)
# ══════════════════════════════════════════════════════════════════
CREDIT_RATES_LEGACY_2023_2025 = {
    "중소기업": {
        "수도권":    {"청년등": 1450, "청년등외": 850},
        "수도권 외": {"청년등": 1550, "청년등외": 950},
    },
    "중견기업": {
        "수도권":    {"청년등": 800, "청년등외": 450},
        "수도권 외": {"청년등": 800, "청년등외": 450},
    },
    "일반기업": {
        "수도권":    {"청년등": 400, "청년등외": 0},
        "수도권 외": {"청년등": 400, "청년등외": 0},
    },
    "대기업": {
        "수도권":    {"청년등": 400, "청년등외": 0},
        "수도권 외": {"청년등": 400, "청년등외": 0},
    },
}

CREDIT_RATES_NEW_2026 = {
    "중소기업": {
        "수도권": {
            "청년등":   {1: 700,  2: 1600, 3: 1700},
            "청년등외": {1: 400,  2: 900,  3: 1000},
        },
        "수도권 외": {
            "청년등":   {1: 1000, 2: 1900, 3: 2000},
            "청년등외": {1: 600,  2: 1000, 3: 1100},
        },
    },
    "중견기업": {
        "수도권": {
            "청년등":   {1: 500,  2: 900,  3: 1000},
            "청년등외": {1: 300,  2: 500,  3: 550},
        },
        "수도권 외": {
            "청년등":   {1: 500,  2: 900,  3: 1000},
            "청년등외": {1: 300,  2: 500,  3: 550},
        },
    },
    "일반기업": {
        "수도권": {
            "청년등":   {1: 300,  2: 500,  3: 0},
            "청년등외": {1: 0,    2: 0,    3: 0},
        },
        "수도권 외": {
            "청년등":   {1: 300,  2: 500,  3: 0},
            "청년등외": {1: 0,    2: 0,    3: 0},
        },
    },
    "대기업": {
        "수도권": {
            "청년등":   {1: 300,  2: 500,  3: 0},
            "청년등외": {1: 0,    2: 0,    3: 0},
        },
        "수도권 외": {
            "청년등":   {1: 300,  2: 500,  3: 0},
            "청년등외": {1: 0,    2: 0,    3: 0},
        },
    },
}

MIN_INCREASE_HURDLE_2026 = {
    "중소기업": 0.0,
    "중견기업": 5.0,
    "일반기업": 10.0,
    "대기업": 10.0,
}

ADDITIONAL_CREDIT_PER_PERSON = {
    "중소기업": 1300,
    "중견기업": 900,
    "일반기업": 0,
    "대기업": 0,
}

RURAL_SPECIAL_TAX_RATE = 0.20


# ══════════════════════════════════════════════════════════════════
# 5. 1단계 업로드 자료 목록 (귀속연도별 동적 생성)
# ══════════════════════════════════════════════════════════════════
def get_doc_types(tax_year: int = DEFAULT_TAX_YEAR) -> list[tuple[str, str, bool, list[str]]]:
    ty = int(tax_year or DEFAULT_TAX_YEAR)
    return [
        ("biz_reg",      "사업자등록증",                                         False, ["사업자등록", "사업자 등록"]),
        ("corp_reg",     "법인 등기부등본",                                      False, ["등기", "등본"]),
        ("shareholder",  "주주명부",                                             False, ["주주"]),
        (f"wht_{ty}",    f"{ty}년 소득자별 근로소득원천징수부 (당해)",            True,  [str(ty), f"{str(ty)[2:]}년"]),
        (f"wht_{ty-1}",  f"{ty-1}년 소득자별 근로소득원천징수부 (직전)",          True,  [str(ty - 1), f"{str(ty - 1)[2:]}년"]),
        (f"wht_{ty-2}",  f"{ty-2}년 소득자별 근로소득원천징수부 (전전년·선택)",    False, [str(ty - 2), f"{str(ty - 2)[2:]}년"]),
        ("prev_filing",  f"{ty-1}·{ty-2}년 기신고 통합고용세액공제 상시근로자 명세서", False, ["명세서", "기신고", "공제신청", "공제세액계산서"]),
    ]


def get_doc_help(tax_year: int = DEFAULT_TAX_YEAR) -> dict[str, str]:
    ty = int(tax_year or DEFAULT_TAX_YEAR)
    help_map = {
        "biz_reg": "상호·업종(소비성서비스업 제외 여부)·소재지(수도권/지방 공제단가) 확인용 (없으면 사이드바 직접 입력)",
        "corp_reg": "설립일·등기임원(대표이사·이사·감사 자동 제외) 확인용 (개인사업자는 생략)",
        "shareholder": "최대주주·배우자·직계존비속(상시근로자 제외 대상) 자동 판별용 (없으면 사원표에서 직접 선택)",
        f"wht_{ty}": f"당해연도({ty}년) 근로자 입·퇴사일, 생년월일(청년 연령 판정), 월별 급여 지급 내역 확인 (필수)",
        f"wht_{ty-1}": f"직전연도({ty-1}년) 상시근로자 수 비교(A 산식) 및 {ty-1}년 귀속분 1차 사후관리 확인 (필수)",
        f"wht_{ty-2}": f"{ty-2}년 귀속분 2차 사후관리(3차년도 연속공제·추징) 인원 직접 검증 시 업로드 (기신고 명세서로 대체 가능)",
        "prev_filing": f"{ty-2}·{ty-1}년 귀속 기공제분의 당해 연속공제·사후관리(추징) 및 미공제 이월세액(제144조) 대조용",
    }
    for y in range(2021, 2029):
        wk = f"wht_{y}"
        if wk not in help_map:
            help_map[wk] = f"{y}년 귀속 소득자별 근로소득원천징수부 (과거연도 비교·사후관리 검증용)"
    return help_map


def get_all_selectable_doc_labels(tax_year: int = DEFAULT_TAX_YEAR) -> dict[str, str]:
    labels: dict[str, str] = {k: lbl for k, lbl, _, _ in get_doc_types(tax_year)}
    for y in range(2028, 2020, -1):
        wk = f"wht_{y}"
        if wk not in labels:
            labels[wk] = f"{y}년 소득자별 근로소득원천징수부"
    return labels


DOC_TYPES = get_doc_types(DEFAULT_TAX_YEAR)
DOC_LABEL = {k: lbl for k, lbl, _, _ in DOC_TYPES}
DOC_REQUIRED = {k: req for k, _, req, _ in DOC_TYPES}
DOC_HELP = get_doc_help(DEFAULT_TAX_YEAR)
CREDIT_RATES = CREDIT_RATES_LEGACY_2023_2025
