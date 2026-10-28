# -*- coding: utf-8 -*-
"""
통합고용세액공제 법령 상수 · 공제단가 · 서류 정의 (2023~2028년 귀속 전면 지원)
근거: 조세특례제한법 제29조의8, 같은 법 시행령 제26조의8, 농어촌특별세법 제5조 제1항

[크로스체크 및 법령 정합성 검증 반영 내역]
1. 2026년 신법 공제단가표(조특법 제29조의8 제1항, 통합고용세액공제1·3-2 PDF) 100% 일치:
   - 중소기업 · 수도권 외(비수도권) · 청년등외: 1년차(A) 700만원 / 2년차(B) 1,200만원 / 3년차(C) 1,300만원
   - 중견기업 · 3년차(C): 청년등 900만원 / 청년등외 500만원
2. 제외사유(조특령 제26조의8 제2항 제1호~제6호) 법령 정합성 정비:
   - 근로소득증대세제(제29조의4)의 요건인 '고액연봉자(7,000만원 초과)'를 통합고용세액공제 상시근로자 제외사유에서 제거.
   - '출산전후휴가자(대체인력채용)'는 기본공제(제1항) 상시근로자 산정 시 제외사유가 아니라,
     추가공제(정규직 전환·육아휴직 복귀, 제7항)의 상시근로자 비감소 요건 판정 특례이므로 일반 제외사유 드롭다운에서 분리하여
     기본 상시근로자 수가 과소 산정되지 않도록 보호.
3. 1단계 업로드 목록에 세액공제 및 사후관리(추가납부) 적법 계산을 위한 필수·핵심 서류를 명확히 안내하고,
   사후관리 기준('기신고 기준' 원칙 vs '세법원칙 기준' 선택) 상수 지원.
4. 법인 본·지점 합산 및 개인사업자 기중 사업 양도·포괄양수(조특령 제26조의8 제10항) 복수 사업장 구분 상수 지원.
"""
from __future__ import annotations
from typing import Any

# ── 지원 귀속연도 (2024~2028년 A·B·C 점증형 산식 및 구법 사후관리 전면 지원) ──
SUPPORTED_TAX_YEARS = [2024, 2025, 2026, 2027, 2028]
TAX_YEARS = SUPPORTED_TAX_YEARS
DEFAULT_TAX_YEAR = 2026
YEARS_SHOWN_BACK = 2  # 기본 비교 과세연도 범위

# ── 복수 사업장 합산 구분 (법인 본·지점 합산 / 개인 기중 양도·포괄양수 / 합병·분할·법인전환) ──
WORKPLACE_TYPES = [
    "지점(법인 본·지점 합산)",
    "포괄양수 사업장(기중 양수)",
    "기중양도 사업장(종전 사업장)",
    "합병·분할·법인전환 승계사업장",
    "기타 합산 사업장",
]
DEFAULT_WORKPLACE_NAME = "본점"

# ── 사후관리 계산 기준 모드 (기신고 기준 원칙 vs 세법원칙 재계산 기준) ──
PM_BASIS_FILED = "filed"      # 기신고 기준 (원칙: 공제감면세액계산서·기신고 명세서 수치 기준)
PM_BASIS_RECALC = "recalc"    # 세법원칙 기준 (원천징수부 사원별 세법원칙 재계산 수치 기준)
PM_BASIS_LABELS = {
    PM_BASIS_FILED: "기신고 기준",
    PM_BASIS_RECALC: "세법원칙 기준",
}

# ── 기업규모 및 소재지 ──
CORP_SIZES = ["중소기업", "중견기업", "일반기업"]
REGIONS = ["수도권", "수도권 외"]
CAPITAL_AREA_KEYWORDS = ["서울", "인천", "경기"]

# ── 소비성서비스업(적용 제외 업종) — 조특령 제26조의8 제1항, 제29조 제3항 ──
EXCLUDED_INDUSTRY_KEYWORDS = [
    "호텔업", "여관업", "모텔", "여인숙",
    "일반유흥주점", "무도유흥주점", "단란주점", "유흥주점", "무도장",
    "카지노", "사행",
]
EXCLUDED_INDUSTRY_EXCEPTIONS = [
    "관광숙박", "관광호텔", "외국인전용", "관광유흥",
]

# ── 고용유형 및 가중치 (조특령 제26조의8 제2항·제6항, 제11조의2 제8항) ──
EMP_CEO = "대표이사"
EMP_EXEC = "임원"
EMP_REGULAR = "정규직"
EMP_PT_050 = "단시간(60시간 이상)"
EMP_PT_075 = "단시간(60시간 이상+요건충족)"  # 상생협약 체결 등 0.75 가중치 특례
EMP_PT_UNDER = "단시간(60시간 미만)"
EMP_FIXED = "계약직(기간제)"

EMP_TYPES = [
    EMP_CEO,
    EMP_EXEC,
    EMP_REGULAR,
    EMP_PT_050,
    EMP_PT_075,
    EMP_PT_UNDER,
    EMP_FIXED,
]
EMPLOYMENT_TYPES = EMP_TYPES

EMP_WEIGHT = {
    EMP_REGULAR: 1.0,
    EMP_FIXED: 1.0,      # 계약기간 1년 이상 기간제 근로자는 1.0 (1년 미만은 제외사유로 제외)
    EMP_PT_050: 0.5,
    EMP_PT_075: 0.75,
}

# 고용유형 선택 시 자동으로 매핑되는 제외사유
EMP_AUTO_EXCLUDE = {
    EMP_CEO: "대표이사",
    EMP_EXEC: "임원",
    EMP_PT_UNDER: "월평균 60시간 미만 단시간근로자",
}
EXCLUDED_BY_EMP_TYPE = EMP_AUTO_EXCLUDE

# 단시간·기간제(계약직)는 청년(15~34세) 연령 요건으로는 청년등 상시근로자가 될 수 없음
# (조특령 제26조의8 제3항 제1호: 상시근로자 중 단시간·기간제 제외. 단, 장애인·60세이상·경력단절·북한이탈주민은 가능)
EMP_NOT_YOUTH_REGULAR = {EMP_PT_050, EMP_PT_075, EMP_FIXED}

# ── 상시근로자 제외사유 (조특령 제26조의8 제2항 제1호~제6호, 제11조의2 제7항) ──
EXCL_NONE = "해당없음"
EXCL_UNDER_1Y = "근로계약 1년미만"
EXCL_NO_WHT = "원천징수·4대보험 납부사실 모두 없음"
EXCL_FOREIGN = "외국인 근로자"
# 참고: 출산전후휴가자(대체인력채용)는 제7항(정규직전환·육아휴직복귀 추가공제 비감소 요건 판정) 전용 상수로 유지
EXCL_MATERNITY_REPLACED = "출산전후휴가자(대체인력채용)"
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
]
EXCLUSION_REASONS = EXCL_REASONS

# ── 청년등 상시근로자 구분 (조특령 제26조의8 제3항) ──
YOUTH_NONE = "해당없음(일반)"
YOUTH_YOUNG = "취업시 청년(4년)"
YOUTH_SENIOR = "취업시 60세 이상"
YOUTH_DISABLED = "장애인 등"
YOUTH_CAREER = "경력단절 근로자"
YOUTH_NK = "북한이탈주민"

YOUTH_TYPES = [
    YOUTH_NONE,
    YOUTH_YOUNG,
    YOUTH_SENIOR,
    YOUTH_DISABLED,
    YOUTH_CAREER,
    YOUTH_NK,
]

# 단시간·계약직 근로자가 선택 가능한 청년등 구분 (청년 연령트랙 제외)
YOUTH_TYPES_NON_REGULAR = [
    YOUTH_NONE,
    YOUTH_SENIOR,
    YOUTH_DISABLED,
    YOUTH_CAREER,
    YOUTH_NK,
]

# ── 연령 및 청년 유지기간 기준 ──
YOUTH_AGE_MIN = 15
YOUTH_AGE_MAX = 34
YOUTH_MIN_AGE = YOUTH_AGE_MIN
YOUTH_MAX_AGE = YOUTH_AGE_MAX
SENIOR_AGE = 60
AGE_60_PLUS = SENIOR_AGE
MILITARY_MAX_MONTHS = 72     # 병역이행기간 차감 한도: 최대 6년(72개월)
# 근로계약 체결일 기준 청년 인정기간 (근로계약 체결일 현재 만 34세 이하인 경우)
#   - 2026.1.1. 이후 계약: 계약일부터 4년 (대기업 3년) — 조특령 제26조의8 제4항 제1호 후단
#   - 2025년 중 계약   : 계약일부터 3년 (대기업 2년) — 조특령 부칙(2026.2.27.) 제11조 제2항
#   - 2024년 이전 계약 및 2024년 이전 최초 공제 코호트: 적용 안 함 (매달 나이로만 판정) — 조특령 부칙(2026.2.27.) 제11조 제1항
YOUTH_HOLD_YEARS_SME = 4          # 2026년 이후 계약 · 중소·중견기업 (조특령 제26조의8 제4항 제1호 후단)
YOUTH_HOLD_YEARS_LARGE = 3        # 2026년 이후 계약 · 일반기업(대기업) (조특령 제26조의8 제4항 제1호 후단)
YOUTH_HOLD_YEARS_2025_SME = 3     # 2025년 계약 · 중소·중견기업 (조특령 부칙(2026.2.27.) 제11조 제2항)
YOUTH_HOLD_YEARS_2025_LARGE = 2   # 2025년 계약 · 일반기업(대기업) (조특령 부칙(2026.2.27.) 제11조 제2항)

# ── 월별 셀 선택값 ──
MONTH_AUTO = "자동"
MONTH_CHOICES = [MONTH_AUTO, "1", "0.75", "0.5", "0"]


# ══════════════════════════════════════════════════════════════════
# 공제단가 및 사후관리·최소고용증가인원 기준표 (단위: 만원)
# ══════════════════════════════════════════════════════════════════

# 1. [구법: 2023~2025년 귀속 최초공제분 & 2025·2026년 중 해당 코호트의 2·3년차 연속공제/추징 단가]
CREDIT_RATES_LEGACY_2023_2025 = {
    "중소기업": {
        "수도권": {"청년등": 1450, "청년등외": 850},
        "수도권 외": {"청년등": 1550, "청년등외": 950},
    },
    "중견기업": {
        "수도권": {"청년등": 800, "청년등외": 450},
        "수도권 외": {"청년등": 800, "청년등외": 450},
    },
    "일반기업": {
        "수도권": {"청년등": 400, "청년등외": 0},
        "수도권 외": {"청년등": 400, "청년등외": 0},
    },
    "대기업": {
        "수도권": {"청년등": 400, "청년등외": 0},
        "수도권 외": {"청년등": 400, "청년등외": 0},
    },
}

# 2. [신법: 2026년 이후 개시 과세연도 고용증가분 — 점증형(유지연차별 차등) 인센티브 구조]
#    - 1년차(A, 직전연도 대비 증가), 2년차(B, 전전연도 대비 유지), 3년차(C, 전전전연도 대비 유지)
CREDIT_RATES_NEW_2026 = {
    "중소기업": {
        "수도권": {
            "청년등": {1: 700, 2: 1600, 3: 1700},     # 3년 합계 4,000만원
            "청년등외": {1: 400, 2: 900, 3: 1000},    # 3년 합계 2,300만원
        },
        "수도권 외": {
            "청년등": {1: 1000, 2: 1900, 3: 2000},    # 3년 합계 4,900만원
            "청년등외": {1: 700, 2: 1200, 3: 1300},   # 3년 합계 3,200만원 (700/1,200/1,300 정확 반영)
        },
    },
    "중견기업": {
        "수도권": {
            "청년등": {1: 500, 2: 900, 3: 900},       # 3년 합계 2,300만원 (500/900/900 정확 반영)
            "청년등외": {1: 300, 2: 500, 3: 500},     # 3년 합계 1,300만원 (300/500/500 정확 반영)
        },
        "수도권 외": {
            "청년등": {1: 500, 2: 900, 3: 900},
            "청년등외": {1: 300, 2: 500, 3: 500},
        },
    },
    "일반기업": {
        "수도권": {
            "청년등": {1: 300, 2: 500, 3: 0},         # 대기업은 최대 2년 공제 (300/500)
            "청년등외": {1: 0, 2: 0, 3: 0},
        },
        "수도권 외": {
            "청년등": {1: 300, 2: 500, 3: 0},
            "청년등외": {1: 0, 2: 0, 3: 0},
        },
    },
    "대기업": {
        "수도권": {
            "청년등": {1: 300, 2: 500, 3: 0},
            "청년등외": {1: 0, 2: 0, 3: 0},
        },
        "수도권 외": {
            "청년등": {1: 300, 2: 500, 3: 0},
            "청년등외": {1: 0, 2: 0, 3: 0},
        },
    },
}

# 2026년 이후 신법: 중견기업·대기업 최소고용증가인원수 기준 (조특법 제29조의8 제1항 제3호)
MIN_INCREASE_HURDLE_2026 = {
    "중소기업": 0.0,
    "중견기업": 5.0,
    "일반기업": 10.0,
    "대기업": 10.0,
}

# 3. [정규직 전환자(~2024년 귀속) 및 육아휴직 복귀자(~2026년 귀속) 추가공제 단가 (만원)]
ADDITIONAL_CREDIT_PER_PERSON = {
    "중소기업": 1300,
    "중견기업": 900,
    "일반기업": 0,
    "대기업": 0,
}

# 4. 농어촌특별세율 (실제 감면받는 세액의 20% — 농어촌특별세법 제5조 제1항 제1호)
RURAL_SPECIAL_TAX_RATE = 0.20


# ══════════════════════════════════════════════════════════════════
# 귀속연도별 동적 업로드 서류 정의 (2024~2028년 연동)
# ══════════════════════════════════════════════════════════════════
def get_doc_types(tax_year: int = DEFAULT_TAX_YEAR) -> list[tuple[str, str, bool, list[str]]]:
    """
    선택된 귀속사업연도(tax_year)에 맞춰 1단계 업로드 필수/선택 서류 목록을 동적으로 반환합니다.
    - 원천징수부만으로는 ① 사업장 소재지(수도권/비수도권 단가), ② 업종(소비성서비스업 제외),
      ③ 법인 등기임원·최대주주 및 친족 제외(조특령 §26의8② 2·3호),
      ④ 기공제세액(사후관리 추가납부 한도)·2차공제·미공제 이월세액(조특법 §29의8③·§144)을 알 수 없으므로,
      자료명 자체에 왜 필요한지와 필수 여부를 명확히 표기합니다.
    """
    t = int(tax_year or DEFAULT_TAX_YEAR)
    t1 = t - 1
    t2 = t - 2
    return [
        (
            "biz_reg",
            "사업자등록증 [필수권장 · 수도권/비수도권 공제단가 및 소비성서비스업 제외 판정]",
            False,
            ["사업자등록", "사업자 등록"],
        ),
        (
            "corp_reg",
            "법인 등기부등본 [법인 필수 · 대표이사·등기임원 상시근로자 자동 제외 판정]",
            False,
            ["등기", "등본"],
        ),
        (
            "shareholder",
            "주주명부 / 주식등변동상황명세서 [법인 필수 · 최대주주 및 배우자·직계존비속 제외 판정]",
            False,
            ["주주명부", "주주현황", "주식등변동"],
        ),
        (
            f"wht_{t}",
            f"{t}년 소득자별 근로소득원천징수부 [필수 · 당해 상시·청년등 인원 산정 (복수 사업장 합산 가능)]",
            True,
            [str(t), f"{t % 100}년"],
        ),
        (
            f"wht_{t1}",
            f"{t1}년 소득자별 근로소득원천징수부 [필수 · 직전연도 대비 고용증가 및 1차 사후관리 산정]",
            True,
            [str(t1), f"{t1 % 100}년"],
        ),
        (
            f"credit_calc_{t1}",
            f"{t1}년 공제감면세액계산서 · 상시근로자 명세서 · 세액공제조정명세서(3) [사후관리·추가납부 필수]",
            False,
            [f"{t1}년 공제", f"{t1 % 100}년 공제", "공제감면세액계산서", "공제세액계산서", "세액공제신청서", "세액공제조정명세서"],
        ),
        (
            f"wht_{t2}",
            f"{t2}년 소득자별 근로소득원천징수부 [2차 사후관리(3차년도)·직전연도 증가인원 재검증용]",
            False,
            [str(t2), f"{t2 % 100}년"],
        ),
        (
            "prev_filing",
            f"{t2}년 공제감면세액계산서 · 상시근로자 명세서 · 세액공제조정명세서(3) [2차 사후관리·추징한도 필수]",
            False,
            ["상시근로자", "통합고용", "고용증대", "공제감면", "공제세액계산서", "조정명세서"],
        ),
    ]


def get_doc_help(tax_year: int = DEFAULT_TAX_YEAR) -> dict[str, str]:
    t = int(tax_year or DEFAULT_TAX_YEAR)
    t1 = t - 1
    t2 = t - 2
    help_map = {
        "biz_reg": "⚠️ 원천징수부에는 소재지·업종이 없습니다. 수도권/비수도권 공제단가 구분 및 소비성서비스업(조특령 §26의8①) 제외 판정에 필수입니다.",
        "corp_reg": "⚠️ 원천징수부만으로는 등기임원 여부를 알 수 없습니다. 법인의 대표이사·등기이사·감사(조특령 §23⑩ 2호) 상시근로자 자동 제외용 (개인사업자 불필요).",
        "shareholder": "⚠️ 원천징수부만으로는 최대주주·친족 여부를 알 수 없습니다. 최대주주·배우자·직계존비속(조특령 §23⑩ 3호) 상시근로자 제외 판정용.",
        f"wht_{t}": f"{t}년 당해 과세연도 상시·청년등 인원 산정 및 {t1}·{t2}년분 사후관리 판정 필수 서류 (단시간·계약직·병역이행기간은 2단계에서 직접 선택 가능).",
        f"wht_{t1}": f"{t1}년 직전 과세연도 상시·청년등 인원 산정 및 {t1}년 귀속분 '세법원칙 기준' 재계산 필수 서류.",
        f"credit_calc_{t1}": f"⚠️ 원천징수부만으로는 기공제세액(추가납부 한도)과 미공제 이월세액을 알 수 없습니다. {t1}년분 연속공제·추가납부(추징) 계산 시 필수입니다.",
        "prev_credit_calc": f"{t1}년 공제감면세액계산서 (기신고 공제세액·2차공제·1년차 추가납부액·미공제 이월액 확인용)",
        f"wht_{t2}": f"{t2}년 귀속분 2차 사후관리(3차년도 연속공제·추징)의 『세법원칙 기준』 인별 재계산용 (기신고서가 있으면 생략 가능).",
        "prev_filing": f"⚠️ {t2}년 귀속분 2차 사후관리(3차년도 연속공제·추징)의 최초 공제세액 한도·1년차 기추징액 차감·미공제 이월세액 소멸 계산에 필수입니다.",
    }
    for y in range(2021, 2029):
        wk = f"wht_{y}"
        if wk not in help_map:
            help_map[wk] = f"{y}년 귀속 소득자별 근로소득원천징수부 (과거연도 비교·사후관리 검증용)"
    return help_map


def get_all_selectable_doc_labels(tax_year: int = DEFAULT_TAX_YEAR) -> dict[str, str]:
    """드롭다운에서 선택 가능한 모든 서류 종류 라벨 사전."""
    base = {k: lbl for k, lbl, *_ in get_doc_types(tax_year)}
    for y in range(2028, 2020, -1):
        wk = f"wht_{y}"
        if wk not in base:
            base[wk] = f"{y}년 소득자별 근로소득원천징수부 (추가 비교·사후관리용)"
        ck = f"credit_calc_{y}"
        if ck not in base:
            base[ck] = f"{y}년 공제감면세액계산서 · 상시근로자 명세서 · 세액공제조정명세서(3)"
    return base


# 하위 호환용 기본 상수
DOC_TYPES = get_doc_types(DEFAULT_TAX_YEAR)
DOC_LABEL = {k: label for k, label, _, _ in DOC_TYPES}
DOC_REQUIRED = {k: req for k, _, req, _ in DOC_TYPES}
DOC_HELP = get_doc_help(DEFAULT_TAX_YEAR)
CREDIT_RATES = CREDIT_RATES_LEGACY_2023_2025


# ── 하위 호환 별칭 및 연도별 기업규모(중소·중견·일반) 관리 헬퍼 ──
MAX_MILITARY_MONTHS = MILITARY_MAX_MONTHS
YOUTH_AGE = YOUTH_YOUNG
YOUTH_60_PLUS = YOUTH_SENIOR
YOUTH_CAREER_BRK = YOUTH_CAREER
YOUTH_NK_DEFECTOR = YOUTH_NK
SPECIAL_YOUTH_TYPES = {YOUTH_SENIOR, YOUTH_DISABLED, YOUTH_CAREER, YOUTH_NK}
YOUTH_RETENTION_YEARS = {"중소기업": 4, "중견기업": 4, "일반기업": 3, "대기업": 3}
CARRYFORWARD_YEARS = 10
ADDITIONAL_CREDIT_RATES = ADDITIONAL_CREDIT_PER_PERSON

UNIT_RATES_LEGACY = {
    ("중소기업", "수도권"): {"청년등": 1450, "청년등외": 850},
    ("중소기업", "수도권 외"): {"청년등": 1550, "청년등외": 950},
    ("중견기업", "수도권"): {"청년등": 800, "청년등외": 450},
    ("중견기업", "수도권 외"): {"청년등": 800, "청년등외": 450},
    ("일반기업", "수도권"): {"청년등": 400, "청년등외": 0},
    ("일반기업", "수도권 외"): {"청년등": 400, "청년등외": 0},
}
UNIT_RATES = UNIT_RATES_LEGACY

UNIT_RATES_2026_NEW = {
    1: {
        ("중소기업", "수도권"): {"청년등": 700, "청년등외": 400},
        ("중소기업", "수도권 외"): {"청년등": 1000, "청년등외": 700},
        ("중견기업", "수도권"): {"청년등": 500, "청년등외": 300},
        ("중견기업", "수도권 외"): {"청년등": 500, "청년등외": 300},
        ("일반기업", "수도권"): {"청년등": 300, "청년등외": 0},
        ("일반기업", "수도권 외"): {"청년등": 300, "청년등외": 0},
    },
    2: {
        ("중소기업", "수도권"): {"청년등": 1600, "청년등외": 900},
        ("중소기업", "수도권 외"): {"청년등": 1900, "청년등외": 1200},
        ("중견기업", "수도권"): {"청년등": 900, "청년등외": 500},
        ("중견기업", "수도권 외"): {"청년등": 900, "청년등외": 500},
        ("일반기업", "수도권"): {"청년등": 500, "청년등외": 0},
        ("일반기업", "수도권 외"): {"청년등": 500, "청년등외": 0},
    },
    3: {
        ("중소기업", "수도권"): {"청년등": 1700, "청년등외": 1000},
        ("중소기업", "수도권 외"): {"청년등": 2000, "청년등외": 1300},
        ("중견기업", "수도권"): {"청년등": 900, "청년등외": 500},
        ("중견기업", "수도권 외"): {"청년등": 900, "청년등외": 500},
        ("일반기업", "수도권"): {"청년등": 0, "청년등외": 0},
        ("일반기업", "수도권 외"): {"청년등": 0, "청년등외": 0},
    },
}


def normalize_corp_size(value: str | None, default: str = "중소기업") -> str:
    v = str(value or "").strip()
    if v in ("중소", "중소기업"):
        return "중소기업"
    if v in ("중견", "중견기업"):
        return "중견기업"
    if v in ("일반", "일반기업", "대기업", "일반기업(대기업)", "중소·중견 외"):
        return "일반기업"
    d = str(default or "중소기업").strip()
    return d if d in CORP_SIZES else "중소기업"


def format_corp_size_label(corp_size: str | None, short: bool = False) -> str:
    cs = normalize_corp_size(corp_size)
    if short:
        return {"중소기업": "중소", "중견기업": "중견", "일반기업": "일반"}.get(cs, cs)
    return "일반기업(대기업)" if cs == "일반기업" else cs


def _cohort_corp_size(s: dict | None, year: int | str | None = None, default: str | None = None) -> str:
    if not isinstance(s, dict):
        return normalize_corp_size(default, "중소기업")
    fallback = normalize_corp_size(
        default or s.get("corp_size_default") or (s.get("biz") or {}).get("기업구분") or "중소기업",
        "중소기업",
    )
    if year is None:
        return fallback
    ys = str(int(year)) if str(year).strip().lstrip("-").isdigit() else str(year).strip()
    by_yr = s.get("corp_size_by_year")
    if isinstance(by_yr, dict):
        v = by_yr.get(ys) if ys in by_yr else by_yr.get(int(ys) if ys.isdigit() else ys)
        if v:
            return normalize_corp_size(v, fallback)
    pf = (s.get("prev_filing") or {}).get(ys)
    if isinstance(pf, dict) and pf.get("corp_size"):
        return normalize_corp_size(pf.get("corp_size"), fallback)
    ps = (s.get("prev_summary") or {}).get(ys)
    if isinstance(ps, dict) and ps.get("corp_size"):
        return normalize_corp_size(ps.get("corp_size"), fallback)
    return fallback


def get_corp_size_for_year(s: dict | None, year: int | str, default: str | None = None) -> str:
    return _cohort_corp_size(s, year, default=default)


def get_corp_size_map(s: dict | None, years: list[int] | None = None) -> dict[str, str]:
    if not isinstance(s, dict):
        return {}
    tax_yr = int(s.get("tax_year") or DEFAULT_TAX_YEAR)
    target_yrs = years or [tax_yr - 3, tax_yr - 2, tax_yr - 1, tax_yr]
    out: dict[str, str] = {}
    by_yr = s.get("corp_size_by_year")
    if isinstance(by_yr, dict):
        for k, v in by_yr.items():
            ks = str(k).strip()
            if ks.isdigit():
                out[ks] = normalize_corp_size(v, _cohort_corp_size(s, None))
    for y in target_yrs:
        ys = str(int(y))
        out[ys] = _cohort_corp_size(s, int(y))
    return out


def apply_corp_size_default_change(s: dict, new_default: str) -> None:
    nd = normalize_corp_size(new_default, "중소기업")
    s["corp_size_default"] = nd
    s.setdefault("biz", {})["기업구분"] = nd
    by_yr = s.setdefault("corp_size_by_year", {})
    user_set = {str(x).strip() for x in (s.get("corp_size_user_set") or []) if str(x).strip()}
    tax_yr = int(s.get("tax_year") or DEFAULT_TAX_YEAR)
    for y in range(min(2021, tax_yr - 3), max(2030, tax_yr + 2)):
        ys = str(y)
        if ys not in user_set:
            by_yr[ys] = nd


def apply_corp_size_year_change(s: dict, year: int | str, new_size: str) -> None:
    ys = str(int(year))
    ns = normalize_corp_size(new_size, _cohort_corp_size(s, None))
    by_yr = s.setdefault("corp_size_by_year", {})
    by_yr[ys] = ns
    user_set = {str(x).strip() for x in (s.get("corp_size_user_set") or []) if str(x).strip()}
    def_sz = normalize_corp_size(s.get("corp_size_default") or (s.get("biz") or {}).get("기업구분") or "중소기업")
    if ns == def_sz:
        user_set.discard(ys)
    else:
        user_set.add(ys)
    s["corp_size_user_set"] = sorted(user_set)
    tax_yr = int(s.get("tax_year") or DEFAULT_TAX_YEAR)
    if int(year) == tax_yr and not user_set:
        s["corp_size_default"] = ns
        s.setdefault("biz", {})["기업구분"] = ns


def has_mixed_corp_sizes(s: dict | None, years: list[int] | None = None) -> bool:
    if not isinstance(s, dict):
        return False
    tax_yr = int(s.get("tax_year") or DEFAULT_TAX_YEAR)
    yrs = years or [tax_yr - 3, tax_yr - 2, tax_yr - 1, tax_yr]
    sizes = {_cohort_corp_size(s, int(y)) for y in yrs}
    return len(sizes) > 1


def format_corp_size_summary_text(s: dict | None, years: list[int] | None = None) -> str:
    if not isinstance(s, dict):
        return "중소기업"
    tax_yr = int(s.get("tax_year") or DEFAULT_TAX_YEAR)
    yrs = sorted(years or [tax_yr - 3, tax_yr - 2, tax_yr - 1, tax_yr])
    if not has_mixed_corp_sizes(s, yrs):
        return format_corp_size_label(_cohort_corp_size(s, tax_yr))
    parts = [f"{int(y)}년 {format_corp_size_label(_cohort_corp_size(s, int(y)), short=True)}" for y in yrs]
    return f"{format_corp_size_label(_cohort_corp_size(s, tax_yr))} (연도별: {' · '.join(parts)})"


def get_unit_rates(
    corp_size: str,
    is_capital: bool,
    tax_year: int = 2025,
    retention_year: int = 1,
    scheme: str = "legacy",
) -> dict[str, int]:
    cs = normalize_corp_size(corp_size)
    reg = "수도권" if is_capital else "수도권 외"
    if scheme == "new_2026":
        ry = max(1, min(3, int(retention_year or 1)))
        tbl = UNIT_RATES_2026_NEW.get(ry, UNIT_RATES_2026_NEW[1])
        return dict(tbl.get((cs, reg), {"청년등": 0, "청년등외": 0}))
    return dict(UNIT_RATES_LEGACY.get((cs, reg), {"청년등": 0, "청년등외": 0}))


# ── 법제처 원문 확인 완료 조문 번호 상수 (2026.2.27. 대통령령 제36127호 개정 기준 단일 상수) ──
LAW_ART_BASIC = "조세특례제한법 제29조의8 제1항"          # 기본공제(A+B+C 구조) 및 제1호 괄호 청년등 증가한도(Cap)
LAW_ART_CAREER_BREAK = "조세특례제한법 제29조의8 제2항"   # 경력단절 근로자 요건 정의
LAW_ART_REG_CONV = "조세특례제한법 제29조의8 제4항"       # 정규직 전환 추가공제 (~2024년 전환분 한정)
LAW_ART_PARENTAL_RET = "조세특례제한법 제29조의8 제5항"   # 육아휴직 복귀자 추가공제
LAW_ART_ADDENDUM_34 = "조세특례제한법 부칙 제34조"        # 법률 제21223호(2025.12.23.) 2024·2025년분 경과조치
DEC_ART_EXCL_IND = "조세특례제한법 시행령 제26조의8 제1항"    # 소비성서비스업 제외
DEC_ART_REG_SCOPE = "조세특례제한법 시행령 제26조의8 제2항"   # 상시근로자 범위 및 제1호~제6호 제외대상
DEC_ART_MIN_HURDLE = "조세특례제한법 시행령 제26조의8 제3항"  # 최소고용증가인원수 (중견 5명 · 일반 10명)
DEC_ART_YOUTH_SCOPE = "조세특례제한법 시행령 제26조의8 제4항" # 청년등 상시근로자 범위 (제1호: 15~34세, 병역 6년 차감, 4년 유지)
DEC_ART_CALC_METHOD = "조세특례제한법 시행령 제26조의8 제6항" # 상시근로자 수 및 청년등 상시근로자 수 계산식(제11조의2 제8항 준용)
DEC_ART_MATERNITY = "조세특례제한법 시행령 제26조의8 제7항"   # 출산전후휴가자 대체인력 특례
DEC_ART_SUCCESSION = "조세특례제한법 시행령 제26조의8 제8항"  # 창업·포괄양수·합병·분할·법인전환 고용승계 특례(제23조 제13항 준용)

# ── 라포케어 20명 실제 사원 데이터 (엔진 회귀 테스트 전용 고정 픽스처) ──
LAFOCARE_GOLDEN_FIXTURE = {
    "tax_year": 2026,
    "corp_size": "중소기업",
    "is_capital": True,
    "biz": {
        "상호": "주식회사 라포케어",
        "사업자번호": "173-88-02279",
        "사업장소재지": "서울특별시 금천구 가산디지털2로 98",
        "업태": "도매 및 소매업",
        "종목": "전자상거래업",
        "설립일": "2022-05-11",
        "기업구분": "중소기업",
        "전전년_월수": 12,
        "전년_월수": 12,
        "당해_월수": 12,
    },
    "prev_summary": {
        "2025": {
            "상시": 4.62,
            "청년등": 3.88,
            "청년등_증가": 2.30,
            "청년등외_증가": 0.74,
            "공제세액": 39_640_000,
            "이월세액": 0,
            "수도권": True,
        },
        "2024": {
            "상시": 1.58,
            "청년등": 1.58,
            "청년등_증가": 1.08,
            "청년등외_증가": 0.00,
            "공제세액": 16_740_000,
            "2차_공제세액": 16_740_000,
            "기추징세액": 0,
            "이월세액": 0,
            "수도권": False,  # 2024년 최초 공제 당시 비수도권(청년등 1,550만원)
        },
        "2023": {
            "상시": 0.50,
            "청년등": 0.00,
            "청년등_증가": 0.00,
            "청년등외_증가": 0.50,
            "공제세액": 3_875_000,
            "이월세액": 0,
            "수도권": False,
        },
    },
    "employees": [
        {"pid": "p01", "성명": "박명호", "생년월일": "1993-06-03", "입사일": "2022-09-01", "퇴사일": "", "고용유형": EMP_EXEC, "active": {2023: range(1, 13), 2024: range(1, 13), 2025: range(1, 13), 2026: range(1, 13)}},
        {"pid": "p02", "성명": "김우주", "생년월일": "1999-02-05", "입사일": "2022-09-01", "퇴사일": "2024-10-31", "고용유형_연도별": {2023: EMP_PT_050, 2024: EMP_REGULAR}, "active": {2023: range(1, 13), 2024: range(1, 11)}},
        {"pid": "p03", "성명": "김성은", "생년월일": "1998-07-30", "입사일": "2024-04-01", "퇴사일": "2026-01-14", "고용유형": EMP_REGULAR, "active": {2024: range(4, 13), 2025: range(1, 13), 2026: range(1, 2)}},
        {"pid": "p04", "성명": "서성관", "생년월일": "1998-01-24", "입사일": "2025-05-01", "퇴사일": "", "고용유형": EMP_REGULAR, "active": {2025: range(5, 13), 2026: range(1, 13)}},
        {"pid": "p05", "성명": "이병주", "생년월일": "1994-11-25", "입사일": "2025-05-01", "퇴사일": "", "고용유형": EMP_REGULAR, "active": {2025: range(5, 13), 2026: range(1, 13)}},
        {"pid": "p06", "성명": "이진우", "생년월일": "1989-06-08", "입사일": "2025-05-01", "퇴사일": "2025-09-23", "고용유형": EMP_REGULAR, "active": {2025: range(5, 10)}},
        {"pid": "p07", "성명": "정우람", "생년월일": "1997-12-24", "입사일": "2025-05-01", "퇴사일": "", "고용유형": EMP_REGULAR, "active": {2025: range(5, 13), 2026: range(1, 13)}},
        {"pid": "p08", "성명": "박소연", "생년월일": "1998-03-03", "입사일": "2025-08-01", "퇴사일": "2026-07-03", "고용유형": EMP_REGULAR, "active": {2025: range(8, 13), 2026: range(1, 8)}},
        {"pid": "p09", "성명": "김범주", "생년월일": "1994-10-21", "입사일": "2025-08-01", "퇴사일": "", "고용유형": EMP_REGULAR, "active": {2025: range(8, 13), 2026: range(1, 13)}},
        {"pid": "p10", "성명": "차백준", "생년월일": "1989-01-20", "입사일": "2025-08-01", "퇴사일": "2026-03-31", "고용유형": EMP_REGULAR, "active": {2025: range(8, 13), 2026: range(1, 4)}},
        {"pid": "p11", "성명": "최가연", "생년월일": "2000-11-25", "입사일": "2025-12-01", "퇴사일": "", "고용유형": EMP_REGULAR, "active": {2025: range(12, 13), 2026: range(1, 13)}},
        {"pid": "p12", "성명": "이재빈", "생년월일": "1990-11-24", "입사일": "2026-03-01", "퇴사일": "", "고용유형": EMP_REGULAR, "active": {2026: range(3, 13)}},
        {"pid": "p13", "성명": "김주연", "생년월일": "1998-04-22", "입사일": "2026-04-01", "퇴사일": "", "고용유형": EMP_REGULAR, "active": {2026: range(4, 13)}},
        {"pid": "p14", "성명": "이화준", "생년월일": "2002-03-05", "입사일": "2026-04-01", "퇴사일": "", "고용유형": EMP_REGULAR, "active": {2026: range(4, 13)}},
        {"pid": "p15", "성명": "오수민", "생년월일": "2000-03-08", "입사일": "2026-04-01", "퇴사일": "", "고용유형": EMP_REGULAR, "active": {2026: range(4, 13)}},
        {"pid": "p16", "성명": "여인서", "생년월일": "1997-06-18", "입사일": "2026-04-01", "퇴사일": "", "고용유형": EMP_REGULAR, "active": {2026: range(4, 13)}},
        {"pid": "p17", "성명": "오혜성", "생년월일": "2002-04-20", "입사일": "2026-06-01", "퇴사일": "", "고용유형": EMP_REGULAR, "active": {2026: range(6, 13)}},
        {"pid": "p18", "성명": "서금빈", "생년월일": "2000-11-18", "입사일": "2026-06-01", "퇴사일": "", "고용유형": EMP_REGULAR, "active": {2026: range(6, 13)}},
        {"pid": "p19", "성명": "류슬기", "생년월일": "1993-04-22", "입사일": "2026-06-01", "퇴사일": "", "고용유형": EMP_REGULAR, "active": {2026: range(6, 13)}},
        {"pid": "p20", "성명": "정태환", "생년월일": "1995-09-03", "입사일": "2026-07-01", "퇴사일": "", "고용유형": EMP_REGULAR, "active": {2026: range(7, 13)}},
        {"pid": "p21", "성명": "이정욱", "생년월일": "1977-02-20", "입사일": "2026-08-01", "퇴사일": "", "고용유형": EMP_REGULAR, "active": {2026: range(8, 13)}},
        {"pid": "p22", "성명": "도은주", "생년월일": "1991-01-26", "입사일": "2026-09-01", "퇴사일": "", "고용유형": EMP_REGULAR, "active": {2026: range(9, 13)}},
    ],
}


def calc_method_for(cohort_year: int) -> str:
    """
    코호트(최초 공제연도) 기준 상시근로자 수 계산방식(A/B) 일원화 선택 함수.
    - 근거: 국세청 법인세과 「'26년 3월 법인세 통합고용세액공제 상시근로자 수 계산 안내」 (재정경제부 세제실 회신 반영)
      및 조세특례제한법 시행령(2026.2.27. 대통령령 제36127호) 부칙 제11조
    - cohort_year <= 2024: "A" (기존 방식: [매월 말 상시근로자 수의 합계 ÷ 과세연도 개월수]의 값에서 100분의 1 미만 절사 — 최초 공제가 기존 방식이므로 그 코호트의 2·3차년도 요건·연속공제·사후관리는 끝까지 A)
      # 확인 필요: '26.3월 국세청 안내 신뢰보호 원칙 연장 적용 (2026년 이후 평가연도에서 2024년 이하 코호트에 A를 계속 적용)
    - cohort_year >= 2025: "B" (현행 방식: [(각 상시근로자 근무개월수 ÷ 과세연도 개월수)의 값에서 100분의 1 미만 절사한 값]의 합계)
    """
    return "A" if int(cohort_year) <= 2024 else "B"


def calc_method_badge_label(cohort_year_or_method: int | str) -> str:
    """화면·보고서 배지 표시용 문자열: 'B방식(사원별 절사)' / 'A방식(합계 절사·신뢰보호)'"""
    if isinstance(cohort_year_or_method, str) and cohort_year_or_method.upper() in ("A", "B"):
        m = cohort_year_or_method.upper()
    else:
        m = calc_method_for(int(cohort_year_or_method))
    return "B방식(사원별 절사)" if m == "B" else "A방식(합계 절사·신뢰보호)"


# ── 앱 고정 표기(배지·상태 문구) 목록: 인용문 사후 대조(verify_and_redact_unmatched_quotes) 검사 제외 대상 ──
# 이 목록은 '앱 표기'로만 쓰며 법령·안내문 원문 출처 목록(allowed_compact_sources)에는 넣지 않는다.
APP_FIXED_LABELS: tuple[str, ...] = (
    calc_method_badge_label("B"),
    calc_method_badge_label("A"),
    "# 확인 필요: '26.3월 국세청 안내 신뢰보호 원칙 연장 적용",
    "계산방식(A/B) 차이 — 국세청 '26.3월 안내 기준 적용",
    "사원표 재계산값 임시 입력 · 신고서 확인 필요",
    "신고서 확인 필요",
    "신고서 미입력",
    "차이 없음",
    "기신고·재계산 차이 발생",
    PM_BASIS_LABELS[PM_BASIS_FILED],
    PM_BASIS_LABELS[PM_BASIS_RECALC],
)


# ── 행정해석 · 국세청 공문 · 법정서식 원문 데이터 ──
# [원칙]
# - "원문" 필드: 사용자가 제공한 원본(안내문 이미지·서식 PDF)의 글자를 그대로 옮긴 것. 요약·재구성·기호 변경 금지.
#   (표는 "항목: 내용" 한 줄 형식으로 옮겼으며, 글자 대조는 공백 제거 기준으로 수행한다.)
# - 원본에 없는 문장은 "원문"에 절대 넣지 않는다. 원본 일부만 제공된 경우 제공된 범위까지만 수록한다.
# - "앱_요약" 필드: 앱이 작성한 요약. 화면·프롬프트에 원문으로 노출하지 않는다.
ADMIN_RULINGS_AND_NOTICES = {
    "국세청_2026_03_상시근로자수_계산안내": {
        "출처": {
            "문서명": "'26년 3월 법인세 통합고용세액공제 상시근로자 수 계산 안내",
            "발행기관": "국세청 법인세과",
            "발행연월": "2026-03",
        },
        "원문": (
            "'26년 3월 법인세 통합고용세액공제 상시근로자 수 계산 안내\n"
            "안녕하십니까, 국세청 법인세과입니다.\n"
            "「조세특례제한법 시행령」 제26조의8이 개정됨('26.2.27. 시행)에 따라 통합고용세액공제 상시근로자 수 계산 방식이 변경되었습니다. "
            "(영 시행 이후 과세표준을 신고하는 경우부터 적용)\n"
            "【상시근로자 수 계산방식】\n"
            "기존(A방식): (매월말 상시근로자 수의 합계/과세연도 개월수)의 값에서 100분의 1 미만 절사\n"
            "현행(개정)(B방식): [(각 상시근로자 근무 개월 수/과세연도 개월수)의 값에서 100분의 1 미만 절사한 값]의 합계\n"
            "이와 관련하여 재정경제부 세제실에 문의한 결과, 신뢰보호 측면을 고려하여, 개정된 계산 방식(B방식)은 "
            "2025년을 최초 공제 연도로 하여 신고하는 경우부터 적용하는 것임을 알려드립니다. "
            "따라서 「조세특례제한법 시행규칙」 별지 제10호의9서식(통합고용세액공제 공제세액계산서)상 공제세액 계산은 "
            "다음과 같이 적용해주시기 바랍니다.\n"
            "1. 2025사업연도를 1차년도로 하는 경우: 현행(개정) B방식 적용\n"
            "2. 2025사업연도를 2차년도, 3차년도로 하는 경우: 기존 A방식 적용\n"
            "【상시근로자 수 계산방식 적용】\n"
            "기존(A방식)\n"
            "❶ [④기본공제 공제세액 계산내용] - [나. 2차년도 세제지원 요건]의 상시근로자 수(㉒직전 과세연도, ㉑해당 과세연도)\n"
            "❷ [④기본공제 공제세액 계산내용] - [다. 3차년도 세제지원 요건]의 상시근로자 수(㉖직전전 과세연도, ㉗해당 과세연도)\n"
            "현행(개정)(B방식)\n"
            "❶ [③상시근로자 현황]의 ⑥상시근로자 수, ⑦청년등상시근로자 수, ⑧청년등상시근로자를 제외한 상시근로자 수"
            "(직전전 과세연도, 직전 과세연도, 해당 과세연도)\n"
            "❷ [④기본공제 공제세액 계산내용] - [가. 1차년도 세제지원 요건]의 상시근로자 수(⑫⑮⑱직전 과세연도, ⑪⑭⑰해당 과세연도)\n"
            "❸ [⑤추가공제 공제세액 계산내용] - [가. 세제지원 요건]의 상시근로자 수(㉞직전 과세연도, ㉝해당 과세연도)"
        ),
        "앱_요약": (
            "앱 요약(원문 아님): 2025년 이후 최초 공제 코호트(상시근로자 현황·1차년도 요건·추가공제 요건)는 현행(B방식), "
            "2024년 이하 최초 공제 코호트의 사후관리(2·3차년도 요건)는 기존(A방식)을 적용함."
        ),
    },
    "국세청_2026_03_법인세신고_협조안내문": {
        "출처": {
            "문서명": "'26년 3월 법인세 신고 협조 안내문",
            "발행기관": "국세청 법인세과",
            "발행연월": "2026-03",
        },
        # 제공된 원본 이미지가 계산방식 표까지만 있으므로 그 범위까지만 수록함
        "원문": (
            "'26년 3월 법인세 신고 협조 안내문\n"
            "안녕하십니까, 국세청 법인세과입니다.\n"
            "「조세특례제한법 시행령」 제26조의8이 개정됨('26.2.27. 시행)에 따라 통합고용세액공제 상시근로자 수 계산 방식이 "
            "변경되었습니다(영 시행 이후 과세표준을 신고하는 경우부터 적용).\n"
            "이에 「조세특례제한법 시행규칙」 별지 제10호의10서식(통합고용세액공제 상시근로자 명세서)(이하 '서식')도 "
            "현재 입법예고 중('26.3.3.~16.)이나, 입법예고안 서식에 수정사항이 생겨 전산 반영 중에 있습니다.\n"
            "【상시근로자 계산방식】\n"
            "기존 서식: (매월말 상시근로자 수의 합계/과세연도 개월수)의 값에서 100분의 1 미만 절사\n"
            "입법예고안: (상시근로자별 근무 개월 수의 합계/과세연도 개월수)의 값에서 100분의 1 미만 절사\n"
            "변경안: [(각 상시근로자 근무 개월 수/과세연도 개월수)의 값에서 100분의 1 미만 절사한 값]의 합계"
        ),
        "앱_요약": (
            "앱 요약(원문 아님): 별지 제10호의10서식이 입법예고안(합계 후 절사)에서 변경안(사원별 절사 후 합계)으로 수정되어 전산 반영 중임."
        ),
    },
    "조특칙_별지_제10호의10_서식": {
        "출처": {
            "문서명": "조세특례제한법 시행규칙 [별지 제10호의10서식] 통합고용세액공제 상시근로자 명세서 <개정 2026. 3. 20.>",
            "발행기관": "조세특례제한법 시행규칙(별지 서식)",
            "발행연월": "2026-03",
        },
        "원문": (
            "■ 조세특례제한법 시행규칙 [별지 제10호의10서식] <개정 2026. 3. 20.>\n"
            "통합고용세액공제 상시근로자 명세서\n"
            "1. 상시근로자 수 계산\n"
            "① 과세연도 개월수\n"
            "② 상시근로자 수\n"
            "③ 청년등 상시근로자 수\n"
            "④ 청년 상시근로자 수\n"
            "⑤ 장애인 상시근로자 수\n"
            "⑥ 고령자 상시근로자 수\n"
            "⑦ 경력단절근로자 상시근로자 수\n"
            "⑧ 북한이탈주민 상시근로자 수\n"
            "⑨ 합계(=④+⑤+⑥+⑦+⑧)\n"
            "⑩ 청년등 외 상시근로자수(=②-⑨)\n"
            "작성방법\n"
            "1. \"②해당(직전) 과세연도 상시근로자수\"란: \"㉑(㊸) 상시근로자별 계산한 수\"의 합계를 적습니다.\n"
            "13. \"㉑(㊸) 상시근로자별 계산한 수\"란: \"⑳(㊷) 상시근로자 근무개월수\"를 \"①해당(직전) 과세연도 개월수\"로 "
            "나눈 값(100분의 1 미만의 부분은 없는 것으로 한다)을 적습니다."
        ),
        "앱_요약": (
            "앱 요약(원문 아님): 청년등외 상시근로자 수(⑩)는 상시근로자 수(②)에서 청년등 상시근로자 수 합계(⑨)를 차감(②-⑨)하여 산정함."
        ),
    },
}


def format_admin_rulings_for_prompt() -> str:
    """
    AI 심층 세무진단 프롬프트 및 화면 노출용 행정해석 원문 반환.
    - 원칙: AI 프롬프트와 화면에는 반드시 '원문' 필드(및 '출처' 표기)만 넣으며, '앱_요약'은 섞지 않는다.
    """
    blocks: list[str] = ["[국세청 '26.3월 안내문 및 법정서식 원문]"]
    for item in ADMIN_RULINGS_AND_NOTICES.values():
        src = item.get("출처") or {}
        if isinstance(src, dict):
            src_label = f"{src.get('문서명', '')} ({src.get('발행기관', '')}, {src.get('발행연월', '')})"
        else:
            src_label = str(src)
        blocks.append(f"[출처: {src_label}]\n{item.get('원문', '')}")
    return "\n\n".join(blocks)


def diagnose_ab_method_difference(
    cohort_year: int,
    filed_reg: float | None = None,
    filed_yth: float | None = None,
    recalc_A_reg: float | None = None,
    recalc_A_yth: float | None = None,
    recalc_B_reg: float | None = None,
    recalc_B_yth: float | None = None,
    *,
    recalc_reg: float | None = None,
    recalc_yth: float | None = None,
    a_reg: float | None = None,
    a_yth: float | None = None,
    b_reg: float | None = None,
    b_yth: float | None = None,
    filed_prev_reg: float | None = None,
    filed_prev_yth: float | None = None,
    a_prev_reg: float | None = None,
    a_prev_yth: float | None = None,
    b_prev_reg: float | None = None,
    b_prev_yth: float | None = None,
) -> dict[str, Any]:
    """
    기신고값과 재계산값(calc_method_for 기준)의 차이가 A·B 계산방식 차이로만 설명되는지 판정합니다 (5번 · 7-4번 검증).
    - rules.py 단위 테스트 시그니처(`recalc_A_reg`, `recalc_B_reg`)와
      ui_step3.py 호출 시그니처(`a_reg`, `b_reg`, `recalc_reg`, `filed_prev_reg` 등)를 모두 지원합니다.
    """
    target_m = calc_method_for(cohort_year)
    a_r = float(recalc_A_reg if recalc_A_reg is not None else (a_reg or 0.0))
    a_y = float(recalc_A_yth if recalc_A_yth is not None else (a_yth or 0.0))
    b_r = float(recalc_B_reg if recalc_B_reg is not None else (b_reg or 0.0))
    b_y = float(recalc_B_yth if recalc_B_yth is not None else (b_yth or 0.0))

    rec_r = float(recalc_reg) if recalc_reg is not None else (b_r if target_m == "B" else a_r)
    rec_y = float(recalc_yth) if recalc_yth is not None else (b_y if target_m == "B" else a_y)
    alt_r = a_r if target_m == "B" else b_r
    alt_y = a_y if target_m == "B" else b_y

    if filed_reg is None or filed_yth is None:
        return {
            "target_method": target_m,
            "is_ab_diff_only": False,
            "is_only_ab_method_diff": False,
            "status_label": "신고서 미입력",
            "guide_text": "기신고 공제세액계산서(별지 제10호의9) 기초값이 입력되지 않았습니다.",
            "reason": "",
        }

    diff_reg = round(rec_r - float(filed_reg), 2)
    diff_yth = round(rec_y - float(filed_yth), 2)
    has_diff = (abs(diff_reg) >= 0.01 or abs(diff_yth) >= 0.01)
    matches_alt = (abs(float(filed_reg) - alt_r) < 0.01 and abs(float(filed_yth) - alt_y) < 0.01)

    prev_ok = True
    if filed_prev_reg is not None and a_prev_reg is not None and b_prev_reg is not None:
        prev_ok = (
            abs(float(filed_prev_reg) - float(a_prev_reg)) < 0.01
            or abs(float(filed_prev_reg) - float(b_prev_reg)) < 0.01
        )
    if prev_ok and filed_prev_yth is not None and a_prev_yth is not None and b_prev_yth is not None:
        prev_ok = (
            abs(float(filed_prev_yth) - float(a_prev_yth)) < 0.01
            or abs(float(filed_prev_yth) - float(b_prev_yth)) < 0.01
        )

    is_ab_only = bool(has_diff and matches_alt and prev_ok)
    if is_ab_only:
        msg = (
            f"계산방식(A/B) 차이 — 국세청 '26.3월 안내 기준 적용 "
            f"(기신고 {float(filed_reg):.2f}/{float(filed_yth):.2f}명은 {'A방식(합계 절사)' if target_m == 'B' else 'B방식(사원별 절사)'} 값과 일치하며, "
            f"{cohort_year}년 코호트 정본인 {calc_method_badge_label(target_m)} 재계산값 {rec_r:.2f}/{rec_y:.2f}명과의 단수 차이임)"
        )
        return {
            "target_method": target_m,
            "is_ab_diff_only": True,
            "is_only_ab_method_diff": True,
            "status_label": "계산방식(A/B) 차이 — 국세청 '26.3월 안내 기준 적용",
            "guide_text": "계산방식(A/B) 차이 — 국세청 '26.3월 안내 기준 적용 (인별 절사 B방식과 합산 절사 A방식 간 단수 차이로 설명됨)",
            "reason": msg,
        }
    return {
        "target_method": target_m,
        "is_ab_diff_only": False,
        "is_only_ab_method_diff": False,
        "status_label": "차이 없음" if not has_diff else "기신고·재계산 차이 발생",
        "guide_text": "기신고 내역과 재계산 결과 비교",
        "reason": "",
    }


def verify_golden_case_invariants() -> tuple[bool, list[str]]:
    """
    [실제 계산 엔진(headcount.py) 기반 정답지 회귀 테스트 — 7-1 ~ 7-4 전면 검증]
    1) 라포케어 2026년 귀속 검증 (모든 연도 중소기업 기본 시나리오, 2번 규칙: 2025년 이후 코호트 B / 2024년 이하 코호트 A):
       - 2025년 코호트(B방식): 상시 4.62명(청년등 3.88명, 청년외 0.74명) [변경 전(A): 4.66/3.91/0.75 → 변경 후(B): 4.62/3.88/0.74, 사유: A→B]
       - 2025년 신법 비교인원(nr_, B방식): 상시 3.47명(청년등 3.47명, 청년외 0.00명) [변경 전(A): 3.50/3.50/0.00 → 변경 후(B): 3.47/3.47/0.00, 사유: A→B]
       - 2026년 당해 신법 인원(B방식): 상시 11.81명(청년등 10.24명, 청년외 1.57명) [변경 전(A): 11.83/10.25/1.58 → 변경 후(B): 11.81/10.24/1.57, 사유: A→B]
       - 2026년 구법 1차 사후관리 인원(b2, 2025년 코호트 → B방식): 상시 12.56명(청년등 10.74명, 청년외 1.82명) [변경 전(A): 12.58/10.75/1.83 → 변경 후(B): 12.56/10.74/1.82, 사유: A→B]
       - 2026년 구법 2차 사후관리 인원(b3, 2024년 코호트 → A방식 유지): 상시 12.58명(청년등 10.75명, 청년외 1.83명)
       - 2026년 증가인원(B방식): 전체 +8.34명, 청년등 +6.77명, 청년외 +1.57명 [변경 전(A): +8.33/+6.75/+1.58 → 변경 후(B): +8.34/+6.77/+1.57, 사유: A→B]
       - 1차 53,670,000원 [변경 전: 53,570,000 → 변경 후: 53,670,000, 사유: A→B] /
         2차 39,640,000원(재계산도 B방식 39,640,000원으로 기신고와 일치) [변경 전 재계산: 40,160,000 → 변경 후: 39,640,000, 사유: A→B] /
         3차 16,740,000원(2024년 코호트 A방식 유지) /
         합계 110,050,000원 [변경 전: 109,950,000 → 변경 후: 110,050,000, 사유: A→B] /
         농특세 22,010,000원 [변경 전: 21,990,000 → 변경 후: 22,010,000, 사유: A→B] /
         순절세액 88,040,000원 [변경 전: 87,960,000 → 변경 후: 88,040,000, 사유: A→B]
    2) 다년도(2027년 B · 2028년 C) 비교연도 자동 재산정 검증 (도은주 시나리오, B방식)
    3) 연도별 기업규모 변동 검증 (2023 중소기업 / 2024 일반기업 / 2025 중견기업 / 2026 중견기업)
    4) 2024년 코호트(A방식) 2026년 감소 추징 검증
    5) 2028년 중소기업 B 교차 변동 검증
    6) 2025년 계약자 기업규모별 청년 유예기간(3년/2년) 월 경계 검증
    7) 7-2 합성 데이터 A·B 단위 테스트 (3건) + 7-3 방식 선택 테스트 + 7-4 비교 창 A·B 차이 시 경정청구·수정신고 미표시 검증
    """
    errors: list[str] = []
    try:
        from . import headcount as H
    except Exception:
        try:
            import os as _os, sys as _sys, types as _types, importlib as _importlib
            _pkg_dir = _os.path.dirname(_os.path.abspath(__file__))
            if "employment_credit" not in _sys.modules:
                _pkg = _types.ModuleType("employment_credit")
                _pkg.__path__ = [_pkg_dir]
                _pkg.__package__ = "employment_credit"
                _sys.modules["employment_credit"] = _pkg
            _sys.modules.setdefault("employment_credit.rules", _sys.modules[__name__])
            H = _importlib.import_module("employment_credit.headcount")
        except Exception as e:
            return False, [f"headcount 모듈 로드 실패: {e}"]

    fx = LAFOCARE_GOLDEN_FIXTURE
    people: dict[str, dict] = {}
    year_recs: dict[int, dict[str, dict]] = {y: {} for y in (2023, 2024, 2025, 2026)}

    for emp in fx["employees"]:
        pid = emp["pid"]
        pay_by_yr = {}
        yr_ret = {}
        for y in (2023, 2024, 2025, 2026):
            act_m = emp["active"].get(y, ())
            pay_by_yr[str(y)] = {str(m): (3_000_000.0 if m in act_m else 0.0) for m in range(1, 13)}
            if emp["퇴사일"] and emp["퇴사일"].startswith(f"{y}-"):
                yr_ret[str(y)] = emp["퇴사일"]
        people[pid] = {
            "pid": pid,
            "사업장명": "본점",
            "연도별_사업장명": {},
            "성명": emp["성명"],
            "생년월일": emp["생년월일"],
            "입사일": emp["입사일"],
            "퇴사일": emp["퇴사일"],
            "연도별_퇴사일": yr_ret,
            "계약체결일": emp["입사일"],
            "병역개월": 0,
            "월급여": pay_by_yr,
        }
        for y in (2023, 2024, 2025, 2026):
            emp_t = (emp.get("고용유형_연도별") or {}).get(y) or emp.get("고용유형") or EMP_REGULAR
            year_recs[y][pid] = {
                "고용유형": emp_t,
                "제외사유": "",
                "청년등": "",
                "상시_override": "",
                "월_override": {},
                "_user_set": ["고용유형"] if "고용유형_연도별" in emp else [],
            }

    # ── 1) 2026년 귀속(tax_yr = 2026, 모든 연도 중소기업) 실제 엔진 실행 ──
    tax_yr = 2026
    summaries: dict[int, dict] = {}
    cohort_maps: dict[int, dict[str, bool]] = {}
    for y in (2023, 2024, 2025, 2026):
        ctx_y = {
            "corp_size": fx["corp_size"],
            "months_in_year": 12,
            "assume_year_end": True,
            "include_unpaid_hire_month": True,
            "last_paid_month": 9 if y == 2026 else 12,
            "cohort_youth_map": {
                y - 1: cohort_maps.get(y - 1, {}),
                y - 2: cohort_maps.get(y - 2, {}),
            },
            "old_tenure_rule": y < H.NEW_TENURE_RULE_FROM,
        }
        comp_y = {}
        c_map = {}
        for pid, p in people.items():
            if not H.worked_in_year(p, y):
                continue
            c_row = H.compute_row(p, year_recs[y][pid], y, ctx_y)
            comp_y[pid] = c_row
            c_map[pid] = (c_row["상시"] == "O") and any(c_row["youth_flags"])
        cohort_maps[y] = c_map
        tot_y = H.year_totals(list(comp_y.values()), 12, year=y)
        tot_y["has_data"] = True

        # (A) 2026년 표의 구법 사후관리 b2(2025 코호트 → B)·b3(2024 코호트 → A) 종전 규정 재계산 (A·B 두 값 모두 보관)
        if y >= H.NEW_TENURE_RULE_FROM and ((y - 1) < H.NEW_TENURE_RULE_FROM or (y - 2) < H.NEW_TENURE_RULE_FROM):
            ctx_old = dict(ctx_y, old_tenure_rule=True, as_of_year=None)
            alt_old = {
                pid: H.compute_row(people[pid], year_recs[y][pid], y, ctx_old)
                for pid, c in comp_y.items()
                if c["제외사유"] == EXCL_UNDER_1Y
            }
            if alt_old:
                t_old = H.year_totals([alt_old.get(pid, c) for pid, c in comp_y.items()], 12, year=y)
                for blk in ("b2", "b3"):
                    for k in ("yth", "gen", "reg", "yth_act"):
                        tot_y[f"{blk}_{k}"] = t_old[f"{blk}_{k}"]
                        tot_y[f"A_{blk}_{k}"] = t_old[f"A_{blk}_{k}"]
                        tot_y[f"B_{blk}_{k}"] = t_old[f"B_{blk}_{k}"]
                    tot_y[f"ab_diff_{blk}"] = t_old[f"ab_diff_{blk}"]
                    for k in ("청년등_합계", "청년외_합계"):
                        tot_y[f"{blk}_{k}"] = t_old[f"{blk}_{k}"]

        # (B) 일관된 해석 기준 비교연도(2025 <= y < tax_yr) 인원(nr_) 재계산 (A·B 두 값 모두 보관, 기본값은 calc_method_for(tax_yr) = B)
        if tax_yr >= H.NEW_TENURE_RULE_FROM and (H.NEW_TENURE_RULE_FROM - 1) <= y < tax_yr:
            ctx_new = dict(ctx_y, old_tenure_rule=False, as_of_year=tax_yr)
            alt_new = {
                pid: H.compute_row(people[pid], year_recs[y][pid], y, ctx_new)
                for pid, c in comp_y.items()
                if c["상시"] == "O" and H.tenure_under_1y(people[pid], y, as_of_year=tax_yr)
            }
            t_new = H.year_totals([alt_new.get(pid, c) for pid, c in comp_y.items()], 12, year=y)
            tot_y["nr_A_상시_평균"] = t_new["A_상시_평균"]
            tot_y["nr_A_청년등_평균"] = t_new["A_청년등_평균"]
            tot_y["nr_A_청년외_평균"] = t_new["A_청년외_평균"]
            tot_y["nr_B_상시_평균"] = t_new["B_상시_평균"]
            tot_y["nr_B_청년등_평균"] = t_new["B_청년등_평균"]
            tot_y["nr_B_청년외_평균"] = t_new["B_청년외_평균"]
            m_nr = calc_method_for(tax_yr)
            tot_y["nr_상시_평균"] = t_new[f"{m_nr}_상시_평균"]
            tot_y["nr_청년등_평균"] = t_new[f"{m_nr}_청년등_평균"]
            tot_y["nr_청년외_평균"] = t_new[f"{m_nr}_청년외_평균"]
            tot_y["nr_상시_합계"] = t_new["상시_합계"]
            tot_y["nr_청년등_합계"] = t_new["청년등_합계"]
            tot_y["nr_청년외_합계"] = t_new["청년외_합계"]
            tot_y["nr_names"] = sorted(people[pid].get("성명", "") for pid in alt_new)
        summaries[y] = tot_y

    ps = fx["prev_summary"]
    prior_filings = {
        cohort: {
            "init_reg": f.get("상시"),
            "init_yth": f.get("청년등"),
            "init_yth_inc": f.get("청년등_증가"),
            "init_gen_inc": f.get("청년등외_증가"),
            "claimed_won": f.get("공제세액"),
            "carryforward_won": f.get("이월세액"),
            "y1_continued_won": f.get("2차_공제세액") if cohort == 2024 else None,
            "prior_clawback_paid_won": f.get("기추징세액") if cohort == 2024 else None,
            "is_capital": f.get("수도권"),
        }
        for cohort, f in ((2025, ps["2025"]), (2024, ps["2024"]))
    }

    pkg = H.calculate_tax_year_package(
        tax_year=2026,
        corp_size=fx["corp_size"],
        is_capital=fx["is_capital"],
        summaries=summaries,
        prior_filings=prior_filings,
        additional_inputs={},
        scheme_2026="new_2026",
        pm_basis=PM_BASIS_FILED,
    )

    c1_won = int(pkg["cur_base_credit_won"])
    c2_filed_won = int(pkg["pm_y1_filed"]["continued_credit_won"])
    c2_recalc_won = int(pkg["pm_y1_recalc"]["continued_credit_won"])
    c3_won = int(pkg["pm_y2_filed"]["continued_credit_won"])
    tot_gross = int(pkg["total_credit_gross_won"])
    rural_tax = int(pkg["rural_special_tax_won"])
    net_saving = int(pkg["net_after_rural_tax_won"])

    # 변경 전: 3.50/3.50/0.00 → 변경 후: 3.47/3.47/0.00, 사유: A→B (2026년 신법 A 티어의 직전 비교연도 인원에 B방식 적용)
    if round(float(summaries[2025]["nr_상시_평균"]), 2) != 3.47 or round(float(summaries[2025]["nr_청년등_평균"]), 2) != 3.47 or round(float(summaries[2025]["nr_청년외_평균"]), 2) != 0.00:
        errors.append(f"2025년 일관된 해석 비교인원(nr_, B방식) 불일치: {summaries[2025].get('nr_상시_평균')}/{summaries[2025].get('nr_청년등_평균')}/{summaries[2025].get('nr_청년외_평균')}")
    if summaries[2025].get("nr_names") != ["박소연", "이진우", "차백준"]:
        errors.append(f"2025년 비교인원 1년 미만 제외 대상자 불일치: {summaries[2025].get('nr_names')}")
    # 변경 전: 11.83/10.25/1.58 → 변경 후: 11.81/10.24/1.57, 사유: A→B (2026년 당해 신법 인원에 B방식 적용)
    if round(float(summaries[2026]["상시_평균"]), 2) != 11.81 or round(float(summaries[2026]["청년등_평균"]), 2) != 10.24 or round(float(summaries[2026]["청년외_평균"]), 2) != 1.57:
        errors.append(f"2026년 당해 상시근로자 수(B방식) 불일치: {summaries[2026]['상시_평균']}/{summaries[2026]['청년등_평균']}/{summaries[2026]['청년외_평균']}")
    # 변경 전: 12.58/10.75/1.83 → 변경 후: 12.56/10.74/1.82, 사유: A→B (2025년 코호트의 2026년 1차 사후관리 b2에 B방식 적용)
    if round(float(summaries[2026]["b2_reg"]), 2) != 12.56 or round(float(summaries[2026]["b2_yth"]), 2) != 10.74 or round(float(summaries[2026]["b2_gen"]), 2) != 1.82:
        errors.append(f"2026년 구법 1차 사후관리(2025 코호트 B방식) 인원 불일치: {summaries[2026]['b2_reg']}/{summaries[2026]['b2_yth']}/{summaries[2026]['b2_gen']}")
    # 2024년 코호트의 2026년 2차 사후관리(b3)는 A방식 유지: 12.58/10.75/1.83
    if round(float(summaries[2026]["b3_reg"]), 2) != 12.58 or round(float(summaries[2026]["b3_yth"]), 2) != 10.75 or round(float(summaries[2026]["b3_gen"]), 2) != 1.83:
        errors.append(f"2026년 구법 2차 사후관리(2024 코호트 A방식) 인원 불일치: {summaries[2026]['b3_reg']}/{summaries[2026]['b3_yth']}/{summaries[2026]['b3_gen']}")
    # 변경 전: +8.33/+6.75/+1.58 → 변경 후: +8.34/+6.77/+1.57, 사유: A→B (11.81 - 3.47 = 8.34, 10.24 - 3.47 = 6.77, 1.57 - 0.00 = 1.57)
    if round(float(pkg["cur_inc"]["total_inc"]), 2) != 8.34 or round(float(pkg["cur_inc"]["youth_inc"]), 2) != 6.77 or round(float(pkg["cur_inc"]["non_youth_inc"]), 2) != 1.57:
        errors.append(f"2026년 신규 증가인원(B방식) 불일치: 전체 {pkg['cur_inc']['total_inc']}, 청년 {pkg['cur_inc']['youth_inc']}, 일반 {pkg['cur_inc']['non_youth_inc']}")
    if round(float(pkg["pm_y1_filed"]["init_yth_inc"]), 2) != 2.30 or round(float(pkg["pm_y1_filed"]["init_gen_inc"]), 2) != 0.74:
        errors.append(f"2025년 기신고 증가인원 불일치: 청년 {pkg['pm_y1_filed']['init_yth_inc']}, 일반 {pkg['pm_y1_filed']['init_gen_inc']}")
    # 변경 전: 2.33/0.75 → 변경 후: 2.30/0.74, 사유: A→B (2025년 코호트 재계산도 calc_method_for(2025) = B방식으로 계산되어 기신고와 일치)
    if round(float(pkg["pm_y1_recalc"]["init_yth_inc"]), 2) != 2.30 or round(float(pkg["pm_y1_recalc"]["init_gen_inc"]), 2) != 0.74:
        errors.append(f"2025년 재계산 증가인원(B방식) 불일치: 청년 {pkg['pm_y1_recalc']['init_yth_inc']}, 일반 {pkg['pm_y1_recalc']['init_gen_inc']}")
    if round(float(pkg["pm_y2_filed"]["init_yth_inc"]), 2) != 1.08 or round(float(pkg["pm_y2_filed"]["init_gen_inc"]), 2) != 0.00:
        errors.append(f"2024년 3차 연속공제 증가인원 불일치: 청년 {pkg['pm_y2_filed']['init_yth_inc']}, 일반 {pkg['pm_y2_filed']['init_gen_inc']}")
    # 변경 전: 53,570,000 → 변경 후: 53,670,000, 사유: A→B (6.77 × 700만 + 1.57 × 400만 = 53,670,000원)
    if c1_won != 53_670_000:
        errors.append(f"2026년 1차 공제액(B방식) 불일치: {c1_won:,} != 53,670,000")
    if c2_filed_won != 39_640_000:
        errors.append(f"2026년 2차 연속공제액(기신고) 불일치: {c2_filed_won:,} != 39,640,000")
    # 변경 전: 40,160,000 (차액 520,000) → 변경 후: 39,640,000 (차액 0), 사유: A→B (2025년 코호트 재계산에 B방식 적용)
    if c2_recalc_won != 39_640_000:
        errors.append(f"2026년 2차 연속공제액(재계산 B방식) 불일치: {c2_recalc_won:,} != 39,640,000")
    if (c2_recalc_won - c2_filed_won) != 0:
        errors.append(f"2025년 귀속 기신고 vs 재계산(B방식) 차액 불일치: {c2_recalc_won - c2_filed_won:,} != 0")
    if c3_won != 16_740_000:
        errors.append(f"2026년 3차 연속공제액(2024년 비수도권 단가 승계) 불일치: {c3_won:,} != 16,740,000")
    # 변경 전: 109,950,000 / 21,990,000 / 87,960,000 → 변경 후: 110,050,000 / 22,010,000 / 88,040,000, 사유: A→B
    if tot_gross != 110_050_000:
        errors.append(f"당해 총 공제세액 합계 불일치: {tot_gross:,} != 110,050,000")
    if rural_tax != 22_010_000:
        errors.append(f"농어촌특별세(20%) 불일치: {rural_tax:,} != 22,010,000")
    if net_saving != 88_040_000:
        errors.append(f"실질 순절세액 불일치: {net_saving:,} != 88,040,000")

    # ── 2) 다년도(2027년 B · 2028년 C) 비교연도 자동 재산정 검증 ──
    p22_sim = dict(people["p22"], 퇴사일="2027-05-15", 연도별_퇴사일={"2027": "2027-05-15"})
    if H.tenure_under_1y(p22_sim, 2026, as_of_year=None):
        errors.append("다년도 검증 실패: 2026년 말 기준 재직자(도은주)가 2026년 당해 자체 계산에서 1년 미만으로 잘못 제외됨")
    if not H.tenure_under_1y(p22_sim, 2026, as_of_year=2027):
        errors.append("다년도 검증 실패: 2027년 중 1년 미만 퇴사자(도은주)가 2027년 기준 2026년 비교인원 재산정에서 제외되지 않음")
    people_sim = dict(people, p22=p22_sim)
    ctx_2026_asof_2027 = dict(ctx_y, old_tenure_rule=False, as_of_year=2027)
    comp_2026_for_2027 = {
        pid: H.compute_row(p_obj, year_recs[2026][pid], 2026, ctx_2026_asof_2027)
        for pid, p_obj in people_sim.items()
        if H.worked_in_year(p_obj, 2026)
    }
    t_2026_nr = H.year_totals(list(comp_2026_for_2027.values()), 12, year=2026)
    # 변경 전: 11.50/10.25/1.25 → 변경 후: 11.48/10.24/1.24, 사유: A→B (2026년 비교인원 B방식 사원별 절사 합계)
    if round(float(t_2026_nr["상시_평균"]), 2) != 11.48 or round(float(t_2026_nr["청년등_평균"]), 2) != 10.24 or round(float(t_2026_nr["청년외_평균"]), 2) != 1.24:
        errors.append(f"다년도 검증 실패: 2027년 계산 시 2026년 비교인원 재산정 수치(B방식) 불일치 ({t_2026_nr['상시_평균']}/{t_2026_nr['청년등_평균']}/{t_2026_nr['청년외_평균']} != 11.48/10.24/1.24)")

    summaries_2027 = {
        2025: summaries[2025],
        2026: dict(
            summaries[2026],
            nr_상시_평균=t_2026_nr["상시_평균"],
            nr_청년등_평균=t_2026_nr["청년등_평균"],
            nr_청년외_평균=t_2026_nr["청년외_평균"],
            nr_B_상시_평균=t_2026_nr["B_상시_평균"],
            nr_B_청년등_평균=t_2026_nr["B_청년등_평균"],
            nr_B_청년외_평균=t_2026_nr["B_청년외_평균"],
        ),
        2027: {"상시_평균": 14.00, "청년등_평균": 12.00, "청년외_평균": 2.00, "months_in_year": 12, "has_data": True},
    }
    pkg_2027 = H.calculate_tax_year_package(
        tax_year=2027,
        corp_size=fx["corp_size"],
        is_capital=fx["is_capital"],
        summaries=summaries_2027,
        prior_filings={},
        additional_inputs={},
        scheme_2026="new_2026",
        pm_basis=PM_BASIS_FILED,
    )
    tier_a_2027 = pkg_2027["abc_res"]["tiers"]["A"]
    tier_b_2027 = pkg_2027["abc_res"]["tiers"]["B"]
    # 변경 전: 2.50/1.75/0.75 → 변경 후: 2.52/1.76/0.76, 사유: A→B (14.00 - 11.48 = 2.52, 12.00 - 10.24 = 1.76)
    if round(float(tier_a_2027["total_inc"]), 2) != 2.52 or round(float(tier_a_2027["youth_inc"]), 2) != 1.76 or round(float(tier_a_2027["non_youth_inc"]), 2) != 0.76:
        errors.append(f"2027년 A(직전 2026년 재산정 비교, B방식) 증가인원 불일치: {tier_a_2027}")
    # 변경 전: 8.00/6.75/1.25 → 변경 후: 8.01/6.77/1.24, 사유: A→B (11.48 - 3.47 = 8.01, 10.24 - 3.47 = 6.77, 1.24 - 0.00 = 1.24)
    if round(float(tier_b_2027["total_inc"]), 2) != 8.01 or round(float(tier_b_2027["youth_inc"]), 2) != 6.77 or round(float(tier_b_2027["non_youth_inc"]), 2) != 1.24:
        errors.append(f"2027년 B(전전 2025년 3.47명 & 직전 2026년 11.48명 비교, B방식) 유지인원 불일치: {tier_b_2027}")

    res_2026_recalc_after_2027 = H.calculate_tax_year_package(
        tax_year=2026,
        corp_size=fx["corp_size"],
        is_capital=fx["is_capital"],
        summaries={
            2025: summaries[2025],
            2026: dict(summaries[2026], 상시_평균=t_2026_nr["상시_평균"], 청년등_평균=t_2026_nr["청년등_평균"], 청년외_평균=t_2026_nr["청년외_평균"]),
        },
        prior_filings={},
        additional_inputs={},
        scheme_2026="new_2026",
        pm_basis=PM_BASIS_FILED,
    )
    # 변경 전: 52,250,000 → 변경 후: 52,350,000, 사유: A→B (차액은 도은주 4개월 = 0.33명 × 400만 = 1,320,000원으로 동일)
    if int(res_2026_recalc_after_2027["cur_base_credit_won"]) != 52_350_000 or (c1_won - int(res_2026_recalc_after_2027["cur_base_credit_won"])) != 1_320_000:
        errors.append(f"2026년 신고분 사후 재산정 세액 차이 불일치: {c1_won - int(res_2026_recalc_after_2027['cur_base_credit_won']):,} != 1,320,000")

    # ── 3) 연도별 기업규모 변동 시나리오(2023 중소 / 2024 일반기업 / 2025 중견기업 / 2026 중견기업) 검증 ──
    sz_by_yr = {"2023": "중소기업", "2024": "일반기업", "2025": "중견기업", "2026": "중견기업"}
    pkg_mixed_filed = H.calculate_tax_year_package(
        tax_year=2026,
        corp_size="중견기업",
        is_capital=fx["is_capital"],
        summaries=summaries,
        prior_filings=prior_filings,
        additional_inputs={},
        scheme_2026="new_2026",
        pm_basis=PM_BASIS_FILED,
        corp_size_by_year=sz_by_yr,
    )
    tier_a_mixed = pkg_mixed_filed["abc_res"]["tiers"]["A"]
    gross_a_before_hurdle = int(tier_a_mixed["item1_youth_won"]) + int(tier_a_mixed["item2_non_youth_won"])
    # 변경 전: 38,490,000 → 변경 후: 38,560,000, 사유: A→B (청년등 6.77×500만 + 청년외 1.57×300만 = 38,560,000)
    if gross_a_before_hurdle != 38_560_000:
        errors.append(f"연도별 기업규모(2026 중견) 차감 전 1차 산출액 불일치: {gross_a_before_hurdle:,} != 38,560,000")
    # 변경 전: 21,840,000 → 변경 후: 21,860,000, 사유: A→B (청년외 1.57×300만 + 청년등 3.43×500만 = 21,860,000)
    if int(tier_a_mixed["item3_deduction_won"]) != 21_860_000:
        errors.append(f"연도별 기업규모(2026 중견) 5명 최소고용증가인원 차감액 불일치: {tier_a_mixed['item3_deduction_won']:,} != 21,860,000")
    # 변경 전: 16,650,000 → 변경 후: 16,700,000, 사유: A→B (38,560,000 - 21,860,000 = 16,700,000)
    if int(pkg_mixed_filed["cur_base_credit_won"]) != 16_700_000:
        errors.append(f"연도별 기업규모(2026 중견) 차감 후 1차 공제액 불일치: {pkg_mixed_filed['cur_base_credit_won']:,} != 16,700,000")
    if int(pkg_mixed_filed["pm_y1_filed"]["continued_credit_won"]) != 21_730_000:
        errors.append(f"연도별 기업규모(2025 중견, 기신고 기준) 2차 연속공제액 불일치: {pkg_mixed_filed['pm_y1_filed']['continued_credit_won']:,} != 21,730,000")
    # 변경 전: 22,015,000 → 변경 후: 21,730,000, 사유: A→B (2025년 코호트 재계산에 B방식 적용하여 2.30×800만 + 0.74×450만 = 21,730,000)
    if int(pkg_mixed_filed["pm_y1_recalc"]["continued_credit_won"]) != 21_730_000:
        errors.append(f"연도별 기업규모(2025 중견, 재계산 B방식) 2차 연속공제액 불일치: {pkg_mixed_filed['pm_y1_recalc']['continued_credit_won']:,} != 21,730,000")
    if (
        int(pkg_mixed_filed["pm_y2"]["continued_credit_won"]) != 0
        or int(pkg_mixed_filed["pm_y2"]["clawback_net_payable_won"]) != 0
        or pkg_mixed_filed["pm_y2"].get("case_code") != "공제기간 종료(일반기업 2년) · 고용유지(추징 없음)"
    ):
        errors.append(f"연도별 기업규모(2024 일반기업, 고용유지) 3차 공제기간 종료·추징없음 판정 불일치: {pkg_mixed_filed['pm_y2']}")
    # 변경 전: 38,380,000 / 7,676,000 → 변경 후: 38,430,000 / 7,686,000, 사유: A→B (16,700,000 + 21,730,000 = 38,430,000)
    if int(pkg_mixed_filed["total_credit_gross_won"]) != 38_430_000 or int(pkg_mixed_filed["rural_special_tax_won"]) != 7_686_000:
        errors.append(f"연도별 기업규모(기신고 기준) 총공제액/농특세 불일치: {pkg_mixed_filed['total_credit_gross_won']:,} / {pkg_mixed_filed['rural_special_tax_won']:,}")

    # ── 4) 2024년 코호트(비수도권)가 2026년(2차 사후관리)에 상시·청년등 1.00명으로 감소한 경우 추징 검증 ──
    summaries_2026_dec = {
        **summaries,
        2026: dict(
            summaries[2026],
            상시_평균=1.00,
            청년등_평균=1.00,
            청년외_평균=0.00,
            b2_reg=1.00,
            b2_yth=1.00,
            b2_yth_act=1.00,
            b3_reg=1.00,
            b3_yth=1.00,
            b3_yth_act=1.00,
            A_b3_reg=1.00,
            A_b3_yth=1.00,
            A_b3_gen=0.00,
            A_b3_yth_act=1.00,
            B_b2_reg=1.00,
            B_b2_yth=1.00,
            B_b2_gen=0.00,
            B_b2_yth_act=1.00,
        ),
    }
    pf_2024_large = {
        **prior_filings,
        2024: dict(
            prior_filings[2024],
            claimed_won=4_320_000,
            y1_continued_won=4_320_000,
            is_capital=False,
        ),
    }
    pkg_2024_large_claw = H.calculate_tax_year_package(
        tax_year=2026,
        corp_size="중견기업",
        is_capital=fx["is_capital"],
        summaries=summaries_2026_dec,
        prior_filings=pf_2024_large,
        additional_inputs={},
        scheme_2026="new_2026",
        pm_basis=PM_BASIS_FILED,
        corp_size_by_year={"2023": "중소기업", "2024": "일반기업", "2025": "중견기업", "2026": "중견기업"},
    )
    pm2_large_claw = pkg_2024_large_claw["pm_y2_filed"]
    if int(pm2_large_claw["continued_credit_won"]) != 0 or int(pm2_large_claw["clawback_net_payable_won"]) != 4_640_000:
        errors.append(
            f"2024 일반기업(비수도권) 코호트 2026년 인원 감소(1.58→1.00명) 시 3차 공제/추징 불일치: "
            f"공제 {pm2_large_claw['continued_credit_won']:,} != 0 또는 추징 {pm2_large_claw['clawback_net_payable_won']:,} != 4,640,000"
        )

    pkg_2024_sme_claw = H.calculate_tax_year_package(
        tax_year=2026,
        corp_size="중소기업",
        is_capital=fx["is_capital"],
        summaries=summaries_2026_dec,
        prior_filings=prior_filings,
        additional_inputs={},
        scheme_2026="new_2026",
        pm_basis=PM_BASIS_FILED,
        corp_size_by_year={"2023": "중소기업", "2024": "중소기업", "2025": "중소기업", "2026": "중소기업"},
    )
    pm2_sme_claw = pkg_2024_sme_claw["pm_y2_filed"]
    if int(pm2_sme_claw["continued_credit_won"]) != 0 or int(pm2_sme_claw["clawback_net_payable_won"]) != 17_980_000:
        errors.append(
            f"2024 중소기업(비수도권, 1,550만원) 코호트 2026년 인원 감소(1.58→1.00명) 시 3차 공제/추징 불일치: "
            f"공제 {pm2_sme_claw['continued_credit_won']:,} != 0 또는 추징 {pm2_sme_claw['clawback_net_payable_won']:,} != 17,980,000"
        )

    # ── 5) 2028년 중소기업(수도권) B(2년차 유지분) 청년↔청년등외 교차 변동 검증 ──
    abc_cross_2028 = H.calc_new_2026_credit_abc(
        tax_year=2028,
        corp_size="중소기업",
        is_capital=True,
        summaries_by_year={
            2025: {"상시_평균": 0.0, "청년등_평균": 0.0, "청년외_평균": 0.0, "has_data": True},
            2026: {"상시_평균": 0.0, "청년등_평균": 0.0, "청년외_평균": 0.0, "has_data": True},
            2027: {"상시_평균": 10.0, "청년등_평균": 2.0, "청년외_평균": 8.0, "has_data": True},
            2028: {"상시_평균": 10.0, "청년등_평균": 8.0, "청년외_평균": 2.0, "has_data": True},
        },
    )
    tier_b_cross = abc_cross_2028["tiers"]["B"]
    if (
        round(float(tier_b_cross["total_inc"]), 2) != 10.00
        or round(float(tier_b_cross["youth_inc"]), 2) != 2.00
        or round(float(tier_b_cross["non_youth_inc"]), 2) != 2.00
        or int(tier_b_cross["credit_won"]) != 50_000_000
    ):
        errors.append(
            f"2028년 중소·수도권 B 교차 변동 산식 불일치: "
            f"tot_b={tier_b_cross['total_inc']}, yth_b={tier_b_cross['youth_inc']}, gen_b={tier_b_cross['non_youth_inc']}, B_won={tier_b_cross['credit_won']:,} != 50,000,000"
        )

    # ── 6) 만 34세 초과자(1990-06-01생, 2025-05-01 근로계약 체결) 계약연도 기업규모별 유예기간 및 월 경계(me < hold_end) 검증 ──
    p_boundary = {
        "pid": "p_bnd",
        "사업장명": "본점",
        "성명": "홍길동",
        "생년월일": "1990-06-01",
        "입사일": "2025-05-01",
        "퇴사일": "",
        "연도별_퇴사일": {},
        "계약체결일": "2025-05-01",
        "병역개월": 0,
        "월급여": {"2027": {str(m): 3_500_000.0 for m in range(1, 13)}},
    }
    yrec_bnd = {"고용유형": EMP_REGULAR, "제외사유": "", "청년등": "", "상시_override": "", "월_override": {}, "_user_set": []}
    ctx_bnd_mid = {
        "corp_size": "중견기업",
        "corp_size_by_year": {2025: "중견기업", 2026: "중견기업", 2027: "중견기업"},
        "months_in_year": 12,
        "assume_year_end": True,
        "include_unpaid_hire_month": True,
        "last_paid_month": 12,
        "cohort_youth_map": {},
        "old_tenure_rule": False,
    }
    ctx_bnd_large = {
        "corp_size": "중견기업",
        "corp_size_by_year": {2025: "일반기업", 2026: "중견기업", 2027: "중견기업"},
        "months_in_year": 12,
        "assume_year_end": True,
        "include_unpaid_hire_month": True,
        "last_paid_month": 12,
        "cohort_youth_map": {},
        "old_tenure_rule": False,
    }
    row_bnd_mid = H.compute_row(p_boundary, dict(yrec_bnd), 2027, ctx_bnd_mid)
    row_bnd_large = H.compute_row(p_boundary, dict(yrec_bnd), 2027, ctx_bnd_large)
    yth_months_mid = sum(1 for flg in row_bnd_mid["youth_flags"] if flg)
    yth_months_large = sum(1 for flg in row_bnd_large["youth_flags"] if flg)
    if yth_months_mid != 12 or round(float(row_bnd_mid["b1_yth"]), 2) != 1.00:
        errors.append(f"2025년 중견기업 계약(3년 유예) 2027년 청년 인정 개월 수 불일치: {yth_months_mid}개월 ({row_bnd_mid['b1_yth']}) != 12개월 (1.00명)")
    if yth_months_large != 4 or row_bnd_large["youth_flags"][:4] != [True] * 4 or any(row_bnd_large["youth_flags"][4:]) or round(float(row_bnd_large["b1_yth"]), 2) != 0.33:
        errors.append(
            f"2025년 일반기업 계약(2년 유예 · 2027-05-01 제외시점) 2027년 월 경계 판정 불일치: "
            f"청년 {yth_months_large}개월 ({row_bnd_large['youth_flags']}, {row_bnd_large['b1_yth']}) != 1~4월 4개월 (0.33명)"
        )

    # ── 7-2) A·B 방식 단위 테스트 추가 (합성 데이터 3건) ──
    # 케이스 ①: 사원 3명, 근무개월수 8 · 8 · 5, 과세연도 12개월 → A: 21 ÷ 12 = 1.75 / B: 0.66 + 0.66 + 0.41 = 1.73
    syn_rows_1 = [
        {"_eval_year": 2025, "months": [1.0 if m <= cnt else 0.0 for m in range(1, 13)], "youth_flags": [False] * 12, "row_sum": float(cnt), "youth_sum": 0.0}
        for cnt in (8, 8, 5)
    ]
    syn_tot_1 = H.year_totals(syn_rows_1, 12, year=2025)
    if round(float(syn_tot_1["A_상시_평균"]), 2) != 1.75 or round(float(syn_tot_1["B_상시_평균"]), 2) != 1.73:
        errors.append(f"7-2 단위테스트 ①(8·8·5개월) 불일치: A={syn_tot_1['A_상시_평균']:.2f} (기대 1.75), B={syn_tot_1['B_상시_평균']:.2f} (기대 1.73)")

    # 케이스 ②: 단시간 0.5명 사원 1명(12개월) + 정규 1명(7개월) → A: (6 + 7) ÷ 12 = 1.08 / B: 0.50 + 0.58 = 1.08
    syn_rows_2 = [
        {"_eval_year": 2025, "months": [0.5] * 12, "youth_flags": [False] * 12, "row_sum": 6.0, "youth_sum": 0.0},
        {"_eval_year": 2025, "months": [1.0 if m <= 7 else 0.0 for m in range(1, 13)], "youth_flags": [False] * 12, "row_sum": 7.0, "youth_sum": 0.0},
    ]
    syn_tot_2 = H.year_totals(syn_rows_2, 12, year=2025)
    if round(float(syn_tot_2["A_상시_평균"]), 2) != 1.08 or round(float(syn_tot_2["B_상시_평균"]), 2) != 1.08:
        errors.append(f"7-2 단위테스트 ②(단시간 0.5×12개월 + 정규 7개월) 불일치: A={syn_tot_2['A_상시_평균']:.2f} (기대 1.08), B={syn_tot_2['B_상시_평균']:.2f} (기대 1.08)")

    # 케이스 ③: 청년등 사원별 절사: 청년 근무 7개월 사원 3명 → A: 1.75 / B: 1.74 (0.58 × 3)
    syn_rows_3 = [
        {"_eval_year": 2025, "months": [1.0 if m <= 7 else 0.0 for m in range(1, 13)], "youth_flags": [m <= 7 for m in range(1, 13)], "row_sum": 7.0, "youth_sum": 7.0}
        for _ in range(3)
    ]
    syn_tot_3 = H.year_totals(syn_rows_3, 12, year=2025)
    if round(float(syn_tot_3["A_청년등_평균"]), 2) != 1.75 or round(float(syn_tot_3["B_청년등_평균"]), 2) != 1.74:
        errors.append(f"7-2 단위테스트 ③(청년 7개월×3명) 불일치: A={syn_tot_3['A_청년등_평균']:.2f} (기대 1.75), B={syn_tot_3['B_청년등_평균']:.2f} (기대 1.74)")

    # ── 7-3) 방식 선택 테스트 ──
    # · 2024년 코호트의 2026년 사후관리 비교에 A값이, 2025년 코호트의 2026년 사후관리 비교에 B값이 쓰이는지
    if pkg["pm_y2_filed"].get("calc_method") != "A" or round(float(pkg["pm_y2_filed"].get("cur_pm_reg", 0.0)), 2) != 12.58:
        errors.append(f"7-3 방식 선택 실패: 2024년 코호트 2026년 사후관리에 A값(12.58)이 쓰이지 않음 ({pkg['pm_y2_filed'].get('calc_method')}, {pkg['pm_y2_filed'].get('cur_pm_reg')})")
    if pkg["pm_y1_filed"].get("calc_method") != "B" or round(float(pkg["pm_y1_filed"].get("cur_pm_reg", 0.0)), 2) != 12.56:
        errors.append(f"7-3 방식 선택 실패: 2025년 코호트 2026년 사후관리에 B값(12.56)이 쓰이지 않음 ({pkg['pm_y1_filed'].get('calc_method')}, {pkg['pm_y1_filed'].get('cur_pm_reg')})")
    # · 신법 당해 A 티어의 해당·비교 인원에 B값이 쓰이는지
    tier_a_cur = pkg["abc_res"]["tiers"]["A"]
    if (
        tier_a_cur.get("calc_method") != "B"
        or round(float(tier_a_cur.get("cur_reg", 0.0)), 2) != 11.81
        or round(float(tier_a_cur.get("comp_reg", 0.0)), 2) != 3.47
    ):
        errors.append(f"7-3 방식 선택 실패: 신법 A 티어의 해당(11.81)·비교(3.47) 인원에 B값이 쓰이지 않음 ({tier_a_cur})")

    # ── 7-4) 기신고 vs 재계산 비교 창에서 A·B 차이만 있는 경우 경정청구·수정신고 문구가 나오지 않는지 검증 ──
    ab_diag = diagnose_ab_method_difference(
        cohort_year=2025,
        filed_reg=4.66,      # A방식 숫자로 신고된 경우 가정
        filed_yth=3.91,
        recalc_A_reg=4.66,
        recalc_A_yth=3.91,
        recalc_B_reg=4.62,   # 2025년 정본(B방식) 재계산값
        recalc_B_yth=3.88,
    )
    if (
        not ab_diag.get("is_ab_diff_only")
        or ab_diag.get("status_label") != "계산방식(A/B) 차이 — 국세청 '26.3월 안내 기준 적용"
        or "경정청구" in ab_diag.get("status_label", "")
        or "수정신고" in ab_diag.get("status_label", "")
        or "경정청구" in ab_diag.get("guide_text", "")
        or "수정신고" in ab_diag.get("guide_text", "")
    ):
        errors.append(f"7-4 A·B 차이 단독 시 경정청구·수정신고 미표시 검증 실패: {ab_diag}")

    # ── 8) 법령·행정해석 원문 일치 보장 (1~4번) 단위 테스트 ──
    # (8-1) ADMIN_RULINGS_AND_NOTICES 구조("원문", "출처", "앱_요약") 및 비원문 문구 4종 완전 삭제 검증
    forbidden_phrases = (
        "부칙 제2조(일반적 적용례)에 따라",
        "(개정에 따른 납세자 신뢰보호를 위해 기 공제받은 내용에 대한 사후관리와 추가공제 계산 시에는 기존의 계산방식을 적용하여 계산)",
        "또는 창업연도",
        "(* 사원별 상시근로자수의 소수점 셋째자리 이하 절사 후 합산)",
        "납세자 신뢰보호를 위해 세제실과 협의 완료",
        "전산 반영 전에는",
        "(⑦/⑧)",
        "'23년 또는 '24년에 통합고용세액공제를 신청하고",
    )
    required_phrases = {
        "국세청_2026_03_상시근로자수_계산안내": (
            "2. 2025사업연도를 2차년도, 3차년도로 하는 경우: 기존 A방식 적용",
            "❸ [⑤추가공제 공제세액 계산내용] - [가. 세제지원 요건]의 상시근로자 수(㉞직전 과세연도, ㉝해당 과세연도)",
        ),
        "국세청_2026_03_법인세신고_협조안내문": (
            "현재 입법예고 중('26.3.3.~16.)이나, 입법예고안 서식에 수정사항이 생겨 전산 반영 중에 있습니다.",
        ),
        "조특칙_별지_제10호의10_서식": (
            "⑩ 청년등 외 상시근로자수(=②-⑨)",
        ),
    }
    for k_req, phrases in required_phrases.items():
        body_req = str((ADMIN_RULINGS_AND_NOTICES.get(k_req) or {}).get("원문") or "")
        for ph in phrases:
            if ph not in body_req:
                errors.append(f"8-1 실패: {k_req} 원문에 원본 문장이 없음 ({ph})")
    prompt_ruling_txt = format_admin_rulings_for_prompt()
    if "앱 요약" in prompt_ruling_txt:
        errors.append("8-1 실패: format_admin_rulings_for_prompt()에 앱_요약이 섞여 있음")
    for k_r, item_r in ADMIN_RULINGS_AND_NOTICES.items():
        if not isinstance(item_r.get("원문"), str) or not isinstance(item_r.get("출처"), dict):
            errors.append(f"8-1 실패: {k_r} 항목에 원문 또는 출처 필드가 누락됨")
        app_sum = str(item_r.get("앱_요약") or "")
        if app_sum and not app_sum.startswith("앱 요약(원문 아님)"):
            errors.append(f"8-1 실패: {k_r} 앱_요약 필드에 '앱 요약(원문 아님)' 표시가 누락됨")
        for fp in forbidden_phrases:
            if fp in str(item_r.get("원문") or "") or fp in prompt_ruling_txt:
                errors.append(f"8-1 실패: 삭제 대상 비원문 문구({fp})가 남아 있음")

    # (8-2 ~ 8-4) parsers.py 전역 플래그 제거, 제26조의8 본문 구간 준용 검증, 인용문 원문 대조 사후 검증 테스트
    try:
        from . import parsers as P
    except Exception:
        import importlib as _il
        P = _il.import_module("employment_credit.parsers")

    if hasattr(P, "_VERIFIED_26_8_6_MUTATIS_SESSION"):
        errors.append("8-2 실패: parsers.py에 전역 플래그 _VERIFIED_26_8_6_MUTATIS_SESSION이 남아 있음")
    if P.is_26_8_6_mutatis_verified(None) is not False or P.is_26_8_6_mutatis_verified({"verified_26_8_6_mutatis_11_2_8": False}) is not False:
        errors.append("8-2 실패: trace가 None이거나 플래그가 False일 때 False를 반환하지 않음")

    # 제26조의8과 제11조의2제8항이 다른 조문에 각각 있을 때는 False여야 함
    fake_separate_res = (
        "📘 [조세특례제한법 시행령]\n"
        "제11조의2(연구·인력개발비 세액공제) ⑧ 제11조의2제8항 본문입니다.\n"
        "제26조의8(통합고용세액공제) ① 상시근로자 정의 조문입니다.\n"
    )
    tr_sep = {"detail": [fake_separate_res], "article_texts": {}}
    if P.is_26_8_6_mutatis_verified(tr_sep) is not False:
        errors.append("8-3 실패: 제26조의8 본문 밖(타 조문)에 제11조의2제8항이 있는 경우를 통과시킴")

    # 제26조의8 본문 안에 "제11조의2제8항을 준용" 문언이 있을 때만 True 및 원문 문장(공백 보존) 저장
    real_mutatis_sent = "⑥ 제2항에 따른 상시근로자 수 및 제4항에 따른 청년등상시근로자 수의 계산방법에 관하여는 제11조의2제8항을 준용한다."
    valid_26_8_res = (
        "📘 [조세특례제한법 시행령]\n"
        f"제26조의8(통합고용세액공제) ① 제1항 본문.\n{real_mutatis_sent}\n"
        "제26조의9(다음 조문) ① 다음 조문 본문.\n"
    )
    tr_ok = {"detail": [valid_26_8_res], "article_texts": {}}
    if P.is_26_8_6_mutatis_verified(tr_ok) is not True or tr_ok.get("verified_26_8_6_mutatis_sentence") != real_mutatis_sent:
        errors.append(f"8-3 실패: 제26조의8 본문 내 준용 문언 검증 또는 원문 문장 저장 불일치 ({tr_ok.get('verified_26_8_6_mutatis_sentence')})")

    # (8-4) 인용문 사후 검증 단위 테스트: 원문과 일치하는 인용문 1건 유지 + 한 글자라도 다른 인용문 1건 "(원문 대조 불일치로 인용 삭제)" 대체
    sample_ai_output = (
        f'1) 법령 원문 일치 인용: [조문:조세특례제한법 시행령 제26조의8 제6항] "{real_mutatis_sent}"에 따라 계산합니다.\n'
        '2) 한 글자 변형 인용: "⑥ 제2항에 따른 상시근로자 수 및 제3항에 따른 청년등상시근로자 수의 계산방법에 관하여는 제11조의2제8항을 준용한다."라고 규정되어 있습니다.'
    )
    verified_txt, del_cnt = P.verify_and_redact_unmatched_quotes(sample_ai_output, tr_ok)
    if del_cnt != 1 or f'"{real_mutatis_sent}"' not in verified_txt or "(원문 대조 불일치로 인용 삭제)" not in verified_txt:
        errors.append(f"8-4 실패: 인용문 사후 대조 결과 불일치 (del_cnt={del_cnt}, verified_txt={verified_txt})")

    # (8-5) 인용문 검사 범위: 금액·짧은 용어·법령명·일반 강조 따옴표는 유지, 법령·안내문 인용으로 보이는 불일치 문장만 삭제
    keep_cases = (
        '금액은 "53,670,000원"입니다.',
        '총 공제세액은 "110,050,000원"입니다.',
        "사원별로 '사원별 절사'를 적용했습니다.",
        "최대주주 친족은 '상시근로자 제외 대상'입니다.",
        "「연구개발특구의 육성에 관한 특별법」 규정을 참고했습니다.",
        '담당자는 "신고 전에 근로계약서와 4대보험 가입 내역을 함께 확인하시기 바랍니다"라고 안내했습니다.',
    )
    for kc in keep_cases:
        out_k, cnt_k = P.verify_and_redact_unmatched_quotes(kc, {"detail": []})
        if cnt_k != 0 or out_k != kc:
            errors.append(f"8-5 실패(유지 대상 삭제됨): {kc} -> {out_k}")
    del_cases = (
        '[조문:조세특례제한법 제29조의8 제1항] "전체 상시근로자의 증가 인원 수를 두 배로 한도로 한다"',
        '시행령은 "상시근로자 수는 매월 말 현재 인원의 평균으로 계산하는 것으로 본다"고 규정합니다.',
    )
    for dc in del_cases:
        out_d, cnt_d = P.verify_and_redact_unmatched_quotes(dc, {"detail": ["청년등상시근로자의 증가 인원 수(전체 상시근로자의 증가 인원 수를 한도로 한다)"]})
        if cnt_d != 1 or "(원문 대조 불일치로 인용 삭제)" not in out_d:
            errors.append(f"8-5 실패(불일치 법령 인용 미삭제): {dc} -> {out_d}")
    ok_legal = '[조문:조세특례제한법 제29조의8 제1항] "전체 상시근로자의 증가 인원 수를 한도로 한다"'
    out_ok, cnt_ok = P.verify_and_redact_unmatched_quotes(ok_legal, {"detail": ["청년등상시근로자의 증가 인원 수(전체 상시근로자의 증가 인원 수를 한도로 한다)"]})
    if cnt_ok != 0:
        errors.append(f"8-5 실패(원문 일치 법령 인용 삭제됨): {out_ok}")

    # (8-6) APP_FIXED_LABELS 검사 제외 확인 (원문 출처가 없어도 삭제되지 않아야 함)
    for app_lbl in APP_FIXED_LABELS:
        q_lbl = f'[조문:조세특례제한법 시행령 제26조의8 제6항] "{app_lbl}"'
        out_lbl, cnt_lbl = P.verify_and_redact_unmatched_quotes(q_lbl, {"detail": []})
        if cnt_lbl != 0 or app_lbl not in out_lbl:
            errors.append(f"8-6 실패(APP_FIXED_LABELS 삭제됨): {app_lbl} -> {out_lbl}")

    # (8-7) "](" 괄호 소실 방지 검증: "[부칙:조세특례제한법 시행령 부칙 제11조](2026.2.27.)" 입력 시 "(2026.2.27.)" 유지
    raw_add_paren = "[부칙:조세특례제한법 시행령 부칙 제11조](2026.2.27.)"
    linked_add_paren = P.inject_verified_law_links(raw_add_paren)
    if "(2026.2.27.)" not in linked_add_paren or "https://www.law.go.kr/" not in linked_add_paren:
        errors.append(f"8-7 실패(부칙 뒤 괄호 소실 또는 링크 미결합): {linked_add_paren}")

    # (8-8) 이중 대괄호 링크 마스킹 검증: [[조문: ...]](https://...) 뒤의 불일치 인용문이 정상 삭제되는지 확인
    dbl_link_quote = (
        '[[조문: 조세특례제한법 제29조의8 제1항]](https://www.law.go.kr/법령/조세특례제한법/제29조의8) '
        '"원문에 없는 가짜 조문 문장이라고 규정한다"'
    )
    out_dbl, cnt_dbl = P.verify_and_redact_unmatched_quotes(dbl_link_quote, {"detail": []})
    if (
        cnt_dbl != 1
        or "(원문 대조 불일치로 인용 삭제)" not in out_dbl
        or "[[조문: 조세특례제한법 제29조의8 제1항]](https://www.law.go.kr/법령/조세특례제한법/제29조의8)" not in out_dbl
    ):
        errors.append(f"8-8 실패(이중 대괄호 링크 뒤 불일치 인용 미삭제 또는 링크 훼손): cnt={cnt_dbl}, out={out_dbl}")

    return (len(errors) == 0), errors