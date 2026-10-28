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
4. 법인 본·지점 합산 및 개인사업자 기중 사업 양도·포괄양수(조특령 제26조의8 제8항 및 제23조 제13항 준용) 복수 사업장 구분 상수 지원.
"""
from __future__ import annotations

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
# (조특령 제26조의8 제4항 제1호: 상시근로자 중 단시간·기간제 제외. 단, 장애인·60세이상·경력단절·북한이탈주민은 가능)
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

# ── 청년등 상시근로자 구분 (조특령 제26조의8 제4항) ──
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
#   - 2026.1.1. 이후 계약: 계약일부터 4년 (대기업 3년)
#   - 2025년 중 계약   : 계약일부터 3년 (대기업 2년)
#   - 2024년 이전 계약 : 적용 안 함 (매달 나이로만 판정)
#   중견기업은 중소기업과 같은 기간. 청년 제외시점 = 계약일 + 인정기간 (상시근로자 명세서 작성방법 예: 2025.4.1. 계약 → 2028.4.1.부터 제외)
YOUTH_HOLD_YEARS_SME = 4     # 2026년 이후 계약 · 중소·중견기업
YOUTH_HOLD_YEARS_LARGE = 3   # 2026년 이후 계약 · 일반기업(대기업)
YOUTH_HOLD_YEARS_2025_SME = 3     # 2025년 계약 · 중소·중견기업
YOUTH_HOLD_YEARS_2025_LARGE = 2   # 2025년 계약 · 일반기업(대기업)

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
    t3 = t - 3
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
            f"{t2}년 소득자별 근로소득원천징수부 [2차 사후관리(3차년도)·{t1}년 고용증가({t2}→{t1}년) 재검증용]",
            False,
            [str(t2), f"{t2 % 100}년"],
        ),
        (
            "prev_filing",
            f"{t2}·{t3}년 공제감면세액계산서 · 상시근로자 명세서 · 세액공제조정명세서(3) [2차 사후관리·추징한도 필수]",
            False,
            ["상시근로자", "통합고용", "고용증대", "공제감면", "공제세액계산서", "조정명세서"],
        ),
        (
            f"wht_{t3}",
            f"{t3}년 소득자별 근로소득원천징수부 [{t2}년 고용증가({t3}→{t2}년) 산정 · 2차 사후관리 재검증용]",
            False,
            [str(t3), f"{t3 % 100}년"],
        ),
    ]


def get_doc_help(tax_year: int = DEFAULT_TAX_YEAR) -> dict[str, str]:
    t = int(tax_year or DEFAULT_TAX_YEAR)
    t1 = t - 1
    t2 = t - 2
    t3 = t - 3
    help_map = {
        "biz_reg": "⚠️ 원천징수부에는 소재지·업종이 없습니다. 수도권/비수도권 공제단가 구분 및 소비성서비스업(조특령 §26의8①) 제외 판정에 필수입니다.",
        "corp_reg": "⚠️ 원천징수부만으로는 등기임원 여부를 알 수 없습니다. 법인의 대표이사·등기이사·감사(조특령 §23⑩ 2호) 상시근로자 자동 제외용 (개인사업자 불필요).",
        "shareholder": "⚠️ 원천징수부만으로는 최대주주·친족 여부를 알 수 없습니다. 최대주주·배우자·직계존비속(조특령 §23⑩ 3호) 상시근로자 제외 판정용.",
        f"wht_{t}": f"{t}년 당해 과세연도 상시·청년등 인원 산정 및 {t1}·{t2}년분 사후관리 판정 필수 서류 (단시간·계약직·병역이행기간은 2단계에서 직접 선택 가능).",
        f"wht_{t1}": f"{t1}년 직전 과세연도 상시·청년등 인원 산정 및 {t1}년 귀속분 '세법원칙 기준' 재계산 필수 서류.",
        f"credit_calc_{t1}": f"⚠️ 원천징수부만으로는 기공제세액(추가납부 한도)과 미공제 이월세액을 알 수 없습니다. {t1}년분 연속공제·추가납부(추징) 계산 시 필수입니다.",
        "prev_credit_calc": f"{t1}년 공제감면세액계산서 (기신고 공제세액·2차공제·1년차 추가납부액·미공제 이월액 확인용)",
        f"wht_{t2}": f"{t2}년 귀속분 2차 사후관리(3차년도 연속공제·추징) 및 {t1}년 고용증가({t2}→{t1}년)의 『세법원칙 기준』 인별 재계산용 (기신고서가 있으면 생략 가능).",
        "prev_filing": f"⚠️ {t2}년 귀속분 2차 사후관리(3차년도 연속공제·추징)의 최초 공제세액 한도·1년차 기추징액 차감·미공제 이월세액 소멸 및 {t3}·{t2}년 기신고 인원 확인에 필수입니다.",
        f"wht_{t3}": f"{t2}년 귀속분 최초 고용증가 인원({t3}→{t2}년) 산정 및 2차 사후관리 『세법원칙 기준』 인별 재계산용 ({t2}·{t3}년 기신고 명세서가 있으면 생략 가능).",
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

# ── 하위 호환 별칭 및 정본 산식·단가 회귀 검증 함수 ──
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


def get_unit_rates(
    corp_size: str,
    is_capital: bool,
    tax_year: int = 2025,
    retention_year: int = 1,
    scheme: str = "legacy",
) -> dict[str, int]:
    cs = corp_size if corp_size in CORP_SIZES else "중소기업"
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
            "청년등_증가": 0.25,  # 2022.05.11. 창업(8개월, 2022년 상시 0.25명) -> 2023년 0.50명 (+0.25명 증가 × 1,550만원 = 3,875,000원)
            "청년등외_증가": 0.00,
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


import contextvars as _contextvars

_ACTIVE_AS_OF_YEAR: _contextvars.ContextVar[int | None] = _contextvars.ContextVar("_ACTIVE_AS_OF_YEAR", default=None)


def install_consistent_comparative_headcount_engine() -> None:
    """
    [일관된 해석 기준 다년도 비교인원 자동 재산정 엔진 런타임 설치기]
    - 당해 공제 인원과 직전·전전 비교 인원에 동일한 잣대(실제 근로기간 1년 미만 퇴사 확정자 소급 제외)를 적용하여:
      1) 2026년 신법 공제 계산 시 2026년 중 1년 미만 퇴사 확정자(박소연·차백준 등)를 2025년 비교인원(nr_)에서도 제외(3.50명)
      2) 2027년(A·B)·2028년(A·B·C) 계산 시에도 해당 과세연도 말(as_of_year)까지 확정된 1년 미만 퇴사 사실을 반영해
         직전·전전 비교연도(2025·2026·2027년)의 비교인원(nr_)을 매년 자동 재산정합니다.
    """
    import sys as _sys
    from datetime import date as _date

    def _patched_tenure_under_1y(person: dict, year: int | None = None, as_of_year: int | None = None) -> bool:
        try:
            from . import hc_eligibility as _he
        except Exception:
            _he = _sys.modules.get("employment_credit.hc_eligibility") or _sys.modules.get("hc_eligibility")
        if _he is None:
            return False
        parse_date = _he.parse_date
        add_years = _he.add_years
        hire = parse_date(person.get("입사일"))
        eff_as_of = as_of_year if as_of_year is not None else _ACTIVE_AS_OF_YEAR.get(None)
        ret_map = person.get("연도별_퇴사일") or {}
        if eff_as_of is None:
            yr_ret_str = ret_map.get(str(year)) if year is not None else None
            retire = parse_date(yr_ret_str if yr_ret_str is not None else person.get("퇴사일"))
            cutoff_year = int(year) if year is not None else None
        else:
            cutoff_year = int(eff_as_of)
            min_yr = int(year) if year is not None else None
            candidates = []
            if isinstance(ret_map, dict):
                for k, v in ret_map.items():
                    try:
                        ky = int(k)
                    except (TypeError, ValueError):
                        continue
                    if min_yr is not None and ky < min_yr:
                        continue
                    if ky > cutoff_year:
                        continue
                    dt = parse_date(v)
                    if dt is not None and dt <= _date(cutoff_year, 12, 31):
                        candidates.append(dt)
            base_ret = parse_date(person.get("퇴사일"))
            if base_ret is not None:
                if (min_yr is None or base_ret.year >= min_yr) and base_ret <= _date(cutoff_year, 12, 31):
                    candidates.append(base_ret)
            retire = min(candidates) if candidates else None
        if not hire or not retire or retire < hire:
            return False
        if cutoff_year is not None and retire > _date(cutoff_year, 12, 31):
            return False
        one_yr_later = add_years(hire, 1)
        return (retire.toordinal() - hire.toordinal() + 1) < (one_yr_later.toordinal() - hire.toordinal())

    def _patched_suggest_exclusion(
        person: dict,
        yrec: dict,
        year: int | None = None,
        old_rule: bool = False,
        as_of_year: int | None = None,
    ) -> str:
        emp_type = yrec.get("고용유형") or EMP_REGULAR
        if emp_type in EMP_AUTO_EXCLUDE:
            return EMP_AUTO_EXCLUDE[emp_type]
        sh_rel = str(person.get("주주관계") or "").strip()
        if sh_rel in EXCL_REASONS:
            return sh_rel
        if not old_rule and _patched_tenure_under_1y(person, year, as_of_year=as_of_year):
            return EXCL_UNDER_1Y
        return EXCL_NONE

    for mod_name in ("employment_credit.hc_eligibility", "hc_eligibility", "employment_credit.headcount", "headcount", "employment_credit.hc_review", "hc_review"):
        mod = _sys.modules.get(mod_name)
        if mod is not None:
            setattr(mod, "tenure_under_1y", _patched_tenure_under_1y)
            if hasattr(mod, "suggest_exclusion"):
                setattr(mod, "suggest_exclusion", _patched_suggest_exclusion)

    for mod_name in ("employment_credit.hc_row_engine", "hc_row_engine", "employment_credit.headcount", "headcount"):
        mod = _sys.modules.get(mod_name)
        if mod is not None:
            if hasattr(mod, "suggest_exclusion"):
                setattr(mod, "suggest_exclusion", _patched_suggest_exclusion)
            orig_cr = getattr(mod, "_orig_compute_row_unwrapped", None) or getattr(mod, "compute_row", None)
            if orig_cr is not None and not getattr(orig_cr, "_is_as_of_wrapped", False):
                def _make_wrapped_cr(_fn):
                    def _wrapped_compute_row(person: dict, yrec: dict, year: int, ctx: dict) -> dict:
                        tok = _ACTIVE_AS_OF_YEAR.set(ctx.get("as_of_year") if isinstance(ctx, dict) else None)
                        try:
                            return _fn(person, yrec, year, ctx)
                        finally:
                            _ACTIVE_AS_OF_YEAR.reset(tok)
                    _wrapped_compute_row._is_as_of_wrapped = True
                    return _wrapped_compute_row
                setattr(mod, "_orig_compute_row_unwrapped", orig_cr)
                setattr(mod, "compute_row", _make_wrapped_cr(orig_cr))

    for mod_name in ("employment_credit.ui_common", "ui_common"):
        uic = _sys.modules.get(mod_name)
        if uic is not None and hasattr(uic, "_apply_tenure_transition"):
            H_mod = getattr(uic, "H", None)
            if H_mod is not None:
                def _patched_apply_tenure_transition(s, year, ctx, people, recs, computed, rows, totals, _H=H_mod) -> None:
                    NEW = _H.NEW_TENURE_RULE_FROM
                    y = int(year)
                    tax_yr = int((s or {}).get("tax_year") or 0)
                    if y >= NEW and ((y - 1) < NEW or (y - 2) < NEW):
                        ctx_old = dict(ctx, old_tenure_rule=True, as_of_year=None)
                        alt_old = {}
                        for pid, c in computed.items():
                            yrec = recs.get(pid) or {}
                            if c["제외사유"] == EXCL_UNDER_1Y and "제외사유" not in (yrec.get("_user_set") or []):
                                alt_old[pid] = _H.compute_row(people[pid], yrec, y, ctx_old)
                        if alt_old:
                            t_old = _H.year_totals([alt_old.get(pid, c) for pid, c in computed.items()], ctx["months_in_year"], year=y)
                            for blk, cohort in (("b2", y - 1), ("b3", y - 2)):
                                if cohort >= NEW:
                                    continue
                                for k in ("yth", "gen", "reg", "yth_act"):
                                    totals[f"{blk}_{k}"] = t_old[f"{blk}_{k}"]
                                for k in ("청년등_합계", "청년외_합계"):
                                    totals[f"{blk}_{k}"] = t_old[f"{blk}_{k}"]
                                for r in rows:
                                    c_old = alt_old.get(r["pid"])
                                    if c_old:
                                        r[f"{blk}_yth"], r[f"{blk}_gen"], r[f"{blk}_reg"] = c_old[f"{blk}_yth"], c_old[f"{blk}_gen"], c_old[f"{blk}_reg"]
                            totals["old_rule_pm_names"] = sorted(people[pid].get("성명", "") for pid in alt_old)
                    if tax_yr >= NEW and (NEW - 1) <= y < tax_yr:
                        ctx_new = dict(ctx, old_tenure_rule=False, as_of_year=tax_yr)
                        alt_new = {}
                        for pid, c in computed.items():
                            yrec = recs.get(pid) or {}
                            if (
                                c["상시"] == "O"
                                and "제외사유" not in (yrec.get("_user_set") or [])
                                and _H.tenure_under_1y(people[pid], y, as_of_year=tax_yr)
                            ):
                                alt_new[pid] = _H.compute_row(people[pid], yrec, y, ctx_new)
                        t_new = _H.year_totals([alt_new.get(pid, c) for pid, c in computed.items()], ctx["months_in_year"], year=y) if alt_new else totals
                        totals["nr_상시_평균"] = t_new["상시_평균"]
                        totals["nr_청년등_평균"] = t_new["청년등_평균"]
                        totals["nr_청년외_평균"] = t_new["청년외_평균"]
                        totals["nr_상시_합계"] = t_new["상시_합계"]
                        totals["nr_청년등_합계"] = t_new["청년등_합계"]
                        totals["nr_청년외_합계"] = t_new["청년외_합계"]
                        totals["nr_names"] = sorted(people[pid].get("성명", "") for pid in alt_new)
                setattr(uic, "_apply_tenure_transition", _patched_apply_tenure_transition)


def verify_golden_case_invariants() -> tuple[bool, list[str]]:
    """
    [실제 계산 엔진(headcount.py) 기반 정답지 회귀 테스트 — 일관된 해석 기준 & 다년도(2026·2027·2028) 자동 재산정 검증]
    1) 라포케어 2026년 귀속 검증:
       - 2025년 구법 자체/사후관리 인원: 상시 4.66명(청년등 3.91명, 청년외 0.75명) [박소연·차백준 포함]
       - 2025년 신법 비교인원(nr_): 상시 3.50명(청년등 3.50명, 청년외 0.00명, 42개월) [이진우·박소연·차백준 제외]
       - 2026년 당해 신법 인원: 상시 11.83명(청년등 10.25명, 청년외 1.58명, 142개월) [박소연·차백준 제외]
       - 2026년 구법 1차 사후관리 인원(b2): 상시 12.58명(청년등 10.75명, 청년외 1.83명) [박소연·차백준 포함]
       - 2026년 증가인원: 전체 +8.33명, 청년등 +6.75명, 청년외 +1.58명 (6.75 + 1.58 = 8.33)
       - 1차 53,570,000원 / 2차 39,640,000원(재계산 40,160,000원) / 3차 16,740,000원 / 합계 109,950,000원 /
         농특세 21,990,000원 / 순절세액 87,960,000원
    2) 다년도(2027년 B · 2028년 C) 비교연도 자동 재산정 검증:
       - 2026년 9월 입사자(도은주)가 2027년 5월 중 퇴사(실제 근로기간 1년 미만)한 경우,
         2026년 당해 신고 시에는 포함(11.83명)되나 2027년·2028년 계산 시 2026년 비교인원(nr_)에서는 자동 제외(11.50명)되고
         2025년 비교인원(nr_)은 2027년 B·2028년 C에서도 동일하게 3.50명으로 유지되는지 검증합니다.
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

    install_consistent_comparative_headcount_engine()

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

    # ── 1) 2026년 귀속(tax_yr = 2026) 실제 엔진 실행 ──
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

        # (A) 2026년 표의 구법 사후관리 b2·b3 종전 규정 재계산
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
                    for k in ("청년등_합계", "청년외_합계"):
                        tot_y[f"{blk}_{k}"] = t_old[f"{blk}_{k}"]

        # (B) 일관된 해석 기준 비교연도(2025 <= y < tax_yr) 인원(nr_) 재계산 (as_of_year = tax_yr)
        if tax_yr >= H.NEW_TENURE_RULE_FROM and (H.NEW_TENURE_RULE_FROM - 1) <= y < tax_yr:
            ctx_new = dict(ctx_y, old_tenure_rule=False, as_of_year=tax_yr)
            alt_new = {
                pid: H.compute_row(people[pid], year_recs[y][pid], y, ctx_new)
                for pid, c in comp_y.items()
                if c["상시"] == "O" and H.tenure_under_1y(people[pid], y, as_of_year=tax_yr)
            }
            t_new = H.year_totals([alt_new.get(pid, c) for pid, c in comp_y.items()], 12, year=y)
            tot_y["nr_상시_평균"] = t_new["상시_평균"]
            tot_y["nr_청년등_평균"] = t_new["청년등_평균"]
            tot_y["nr_청년외_평균"] = t_new["청년외_평균"]
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

    if round(float(summaries[2025]["nr_상시_평균"]), 2) != 3.50 or round(float(summaries[2025]["nr_청년등_평균"]), 2) != 3.50 or round(float(summaries[2025]["nr_청년외_평균"]), 2) != 0.00:
        errors.append(f"2025년 일관된 해석 비교인원(nr_) 불일치: {summaries[2025].get('nr_상시_평균')}/{summaries[2025].get('nr_청년등_평균')}/{summaries[2025].get('nr_청년외_평균')}")
    if summaries[2025].get("nr_names") != ["박소연", "이진우", "차백준"]:
        errors.append(f"2025년 비교인원 1년 미만 제외 대상자 불일치: {summaries[2025].get('nr_names')}")
    if round(float(summaries[2026]["상시_평균"]), 2) != 11.83 or round(float(summaries[2026]["청년등_평균"]), 2) != 10.25 or round(float(summaries[2026]["청년외_평균"]), 2) != 1.58:
        errors.append(f"2026년 당해 상시근로자 수 불일치: {summaries[2026]['상시_평균']}/{summaries[2026]['청년등_평균']}/{summaries[2026]['청년외_평균']}")
    if round(float(summaries[2026]["b2_reg"]), 2) != 12.58 or round(float(summaries[2026]["b2_yth"]), 2) != 10.75 or round(float(summaries[2026]["b2_gen"]), 2) != 1.83:
        errors.append(f"2026년 구법 사후관리 인원 불일치: {summaries[2026]['b2_reg']}/{summaries[2026]['b2_yth']}/{summaries[2026]['b2_gen']}")
    if round(float(pkg["cur_inc"]["total_inc"]), 2) != 8.33 or round(float(pkg["cur_inc"]["youth_inc"]), 2) != 6.75 or round(float(pkg["cur_inc"]["non_youth_inc"]), 2) != 1.58:
        errors.append(f"2026년 신규 증가인원 불일치: 전체 {pkg['cur_inc']['total_inc']}, 청년 {pkg['cur_inc']['youth_inc']}, 일반 {pkg['cur_inc']['non_youth_inc']}")
    if round(float(pkg["pm_y1_filed"]["init_yth_inc"]), 2) != 2.30 or round(float(pkg["pm_y1_filed"]["init_gen_inc"]), 2) != 0.74:
        errors.append(f"2025년 기신고 증가인원 불일치: 청년 {pkg['pm_y1_filed']['init_yth_inc']}, 일반 {pkg['pm_y1_filed']['init_gen_inc']}")
    if round(float(pkg["pm_y1_recalc"]["init_yth_inc"]), 2) != 2.33 or round(float(pkg["pm_y1_recalc"]["init_gen_inc"]), 2) != 0.75:
        errors.append(f"2025년 재계산 증가인원 불일치: 청년 {pkg['pm_y1_recalc']['init_yth_inc']}, 일반 {pkg['pm_y1_recalc']['init_gen_inc']}")
    if round(float(pkg["pm_y2_filed"]["init_yth_inc"]), 2) != 1.08 or round(float(pkg["pm_y2_filed"]["init_gen_inc"]), 2) != 0.00:
        errors.append(f"2024년 3차 연속공제 증가인원 불일치: 청년 {pkg['pm_y2_filed']['init_yth_inc']}, 일반 {pkg['pm_y2_filed']['init_gen_inc']}")
    if c1_won != 53_570_000:
        errors.append(f"2026년 1차 공제액 불일치: {c1_won:,} != 53,570,000")
    if c2_filed_won != 39_640_000:
        errors.append(f"2026년 2차 연속공제액(기신고) 불일치: {c2_filed_won:,} != 39,640,000")
    if c2_recalc_won != 40_160_000:
        errors.append(f"2026년 2차 연속공제액(재계산) 불일치: {c2_recalc_won:,} != 40,160,000")
    if (c2_recalc_won - c2_filed_won) != 520_000:
        errors.append(f"2025년 귀속 경정청구 연간 차액 불일치: {c2_recalc_won - c2_filed_won:,} != 520,000")
    if c3_won != 16_740_000:
        errors.append(f"2026년 3차 연속공제액(2024년 비수도권 단가 승계) 불일치: {c3_won:,} != 16,740,000")
    if tot_gross != 109_950_000:
        errors.append(f"당해 총 공제세액 합계 불일치: {tot_gross:,} != 109,950,000")
    if rural_tax != 21_990_000:
        errors.append(f"농어촌특별세(20%) 불일치: {rural_tax:,} != 21,990,000")
    if net_saving != 87_960_000:
        errors.append(f"실질 순절세액 불일치: {net_saving:,} != 87,960,000")

    # ── 2) 다년도(2027년 B · 2028년 C) 비교연도 자동 재산정 검증 ──
    # 도은주(p22, 2026-09-01 입사)가 2027-05-15에 퇴사(1년 미만)한 경우:
    # - 2026년 자체 계산(as_of_year=2026)에서는 상시근로자 포함(11.83명)
    # - 2027년·2028년 계산 시에는 2026년 비교인원(nr_)에서 도은주(4개월)가 자동 제외되어 138/12 = 11.50명(청년등 119/12 = 9.91명)이 되고,
    #   2025년 비교인원(nr_)은 2027년 B·2028년 C에서도 3.50명으로 일관되게 유지되는지 검증
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
    if round(float(t_2026_nr["상시_평균"]), 2) != 11.50 or round(float(t_2026_nr["청년등_평균"]), 2) != 10.25 or round(float(t_2026_nr["청년외_평균"]), 2) != 1.25:
        errors.append(f"다년도 검증 실패: 2027년 계산 시 2026년 비교인원 재산정 수치 불일치 ({t_2026_nr['상시_평균']}/{t_2026_nr['청년등_평균']}/{t_2026_nr['청년외_평균']} != 11.50/10.25/1.25)")

    summaries_2027 = {
        2025: summaries[2025],
        2026: dict(summaries[2026], nr_상시_평균=t_2026_nr["상시_평균"], nr_청년등_평균=t_2026_nr["청년등_평균"], nr_청년외_평균=t_2026_nr["청년외_평균"]),
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
    # 2027 A: 2027(14.00/12.00) - 2026 nr(11.50/10.25) -> 전체 +2.50, 청년 +1.75, 일반 +0.75
    if round(float(tier_a_2027["total_inc"]), 2) != 2.50 or round(float(tier_a_2027["youth_inc"]), 2) != 1.75 or round(float(tier_a_2027["non_youth_inc"]), 2) != 0.75:
        errors.append(f"2027년 A(직전 2026년 재산정 비교) 증가인원 불일치: {tier_a_2027}")
    # 2027 B: min(2027 14.00, 2026 nr 11.50) - 2025 nr(3.50) = 11.50 - 3.50 = +8.00 (청년 10.25 - 3.50 = +6.75, 일반 +1.25)
    if round(float(tier_b_2027["total_inc"]), 2) != 8.00 or round(float(tier_b_2027["youth_inc"]), 2) != 6.75 or round(float(tier_b_2027["non_youth_inc"]), 2) != 1.25:
        errors.append(f"2027년 B(전전 2025년 3.50명 & 직전 2026년 11.50명 비교) 유지인원 불일치: {tier_b_2027}")

    return (len(errors) == 0), errors


install_consistent_comparative_headcount_engine()