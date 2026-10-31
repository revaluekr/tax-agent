# -*- coding: utf-8 -*-
"""
인건비 자동화 - 다중 포맷 입력 파서 엔진 (parsers.py)
1) 거래처 급여 엑셀 파서:
   - 단일/다중 테이블(근로계약 테이블 + 급여계산 테이블 상하 배치형 등) 자동 인식 및 병합
   - 하단 시뮬레이션 블록(예: '1. 격주...', '가나다' 등 더미/모의계산 행) 자동 차단
   - 불규칙 양식일 경우 개인정보 마스킹(홍*동, 000000-*******) 후 앱 표준 Gemini 엔진(Vertex 크레딧 / 설정 모델 체인 / 504·429 재시도)으로 헤더 매핑 폴백
2) 4대보험 고지내역 PDF / 이미지 파서:
   - 건강보험·장기요양보험 산출내역서 PDF (당월 산출보험료 vs 정산보험료/당월경감 분리 추출)
   - 국민연금 결정내역 통지서 PDF (근로자기여금 및 13자리 주민등록번호 보완 추출)
   - 고용보험 당월산정보험료 근로자내역 PDF / PNG / JPG (근로자실업급여보험료 추출)
3) 카카오톡 텍스트 및 캡처 이미지 파서:
   - 4대보험 근로자(세전/세후 역산) 및 3.3% 사업소득자 자동 분류
"""

from __future__ import annotations

import io
import json
import os
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

import openpyxl
import pandas as pd
from pypdf import PdfReader

from .tax_tables import (
    is_ceo_position,
    calculate_employee_payroll_row,
    calculate_freelancer_row,
    solve_gross_from_net_employee,
    solve_gross_from_net_freelancer,
)


# ─────────────────────────────────────────────────────────────
# 앱 공통 Gemini 호출 헬퍼 (Vertex AI 크레딧 우선 · 설정 모델 체인 · 504/429 재시도)
# ─────────────────────────────────────────────────────────────

def _is_pro_mode_enabled() -> bool:
    try:
        import streamlit as st
        return bool(st.session_state.get("pro_toggle_state", False))
    except Exception:
        return False


def _get_gemini_api_keys(pro: bool = False, explicit_key: Optional[str] = None) -> List[str]:
    """
    앱의 `agent.py` 및 `employment_credit/parsers.py`와 동일한 키 풀 규칙 적용:
    - Vertex AI 전용 모드(`is_vertex_enabled() == True` and not `is_vertex_fallback_enabled()`)일 때는
      유료 AI Studio 카드 결제 키를 섞지 않고 Vertex 크레딧 경로만 사용합니다.
    """
    if pro:
        try:
            import agent
            if hasattr(agent, "get_pro_key_pool"):
                pro_keys = [
                    item[1]
                    for item in (agent.get_pro_key_pool() or [])
                    if isinstance(item, (list, tuple)) and len(item) >= 2
                ]
                if pro_keys:
                    return list(dict.fromkeys(pro_keys))
        except Exception:
            pass

    keys: List[str] = []
    try:
        import agent
        if hasattr(agent, "get_live_gemini_key_pool"):
            for item in agent.get_live_gemini_key_pool() or []:
                k = item[1] if isinstance(item, (list, tuple)) and len(item) >= 2 else str(item)
                if k and k not in keys:
                    keys.append(k)
        if hasattr(agent, "is_vertex_enabled") and agent.is_vertex_enabled() and not agent.is_vertex_fallback_enabled():
            return keys if keys else [getattr(agent, "VERTEX_KEY_SENTINEL", "__VERTEX_AI__")]
    except Exception:
        pass

    if explicit_key and explicit_key.strip() and explicit_key.strip() not in keys:
        keys.append(explicit_key.strip())

    try:
        import streamlit as st
        if hasattr(st, "secrets"):
            for k_name in ("GEMINI_PAID_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
                val = str(st.secrets.get(k_name, "") or "").strip()
                if val and val not in keys:
                    keys.append(val)
    except Exception:
        pass

    for k_name in ("GEMINI_PAID_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        val = (os.environ.get(k_name) or "").strip()
        if val and val not in keys:
            keys.append(val)

    return keys


def _get_gemini_models(prefer_pro: bool = False) -> List[str]:
    """
    `agent.py`에 설정된 모델 ID(`FLASH_MODEL_ID`, `PAID_PRO_MODEL_IDS` 등) 및
    504/429 슬로우 모델 회피(`_skip_slow_models`)를 그대로 따릅니다.
    """
    use_pro_first = prefer_pro or _is_pro_mode_enabled()
    pro_models: List[str] = []
    flash_models: List[str] = []
    try:
        import agent
        for pm in getattr(agent, "PAID_PRO_MODEL_IDS", []) or []:
            if pm and str(pm) not in pro_models:
                pro_models.append(str(pm))
        for attr in ("ARGON_MODEL_ID", "PRO_MODEL_ID", "PRO_BACKUP_ID", "PRO_FALLBACK_ID"):
            m = getattr(agent, attr, None)
            if m and str(m) not in pro_models:
                pro_models.append(str(m))
        for attr in ("FLASH_MODEL_ID", "FLASH_BACKUP_ID", "FLASH_FALLBACK_ID", "FLASH_LITE_ID"):
            m = getattr(agent, attr, None)
            if m and str(m) not in flash_models:
                flash_models.append(str(m))
    except Exception:
        pass

    for m in ("gemini-4-argon", "gemini-3.1-pro-preview-customtools", "gemini-3.1-pro-preview", "gemini-2.5-pro"):
        if m not in pro_models:
            pro_models.append(m)
    for m in ("gemini-3.8-flash", "gemini-3.6-flash", "gemini-2.5-flash"):
        if m not in flash_models:
            flash_models.append(m)

    ordered = (pro_models + flash_models) if use_pro_first else (flash_models + pro_models)
    dedup: List[str] = []
    for m in ordered:
        if m not in dedup:
            dedup.append(m)

    try:
        import agent
        if hasattr(agent, "_skip_slow_models"):
            return agent._skip_slow_models(dedup)
    except Exception:
        pass
    return dedup


def _make_genai_client(api_key: str, timeout_ms: int = 90000):
    try:
        import agent
        if hasattr(agent, "make_genai_client"):
            return agent.make_genai_client(api_key, timeout_ms=timeout_ms)
    except Exception:
        pass
    from google import genai
    from google.genai import types
    return genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=timeout_ms))


def _note_model_error(model_id: str, exc: Exception) -> None:
    try:
        import agent
        if hasattr(agent, "_is_slow_error") and agent._is_slow_error(exc):
            if hasattr(agent, "_mark_slow_model"):
                agent._mark_slow_model(model_id)
    except Exception:
        pass


def _call_gemini_contents(
    contents: List[Any],
    prefer_pro: bool = False,
    explicit_api_key: Optional[str] = None,
    log_tokens_fn=None,
) -> str:
    """
    Vertex AI 크레딧 · 설정 모델 체인 · 504/429 슬로우 모델 자동 폴백을 지원하는 통합 Gemini 호출기
    """
    keys = _get_gemini_api_keys(pro=prefer_pro or _is_pro_mode_enabled(), explicit_key=explicit_api_key)
    if not keys:
        return ""
    try:
        from google.genai import types
    except Exception:
        return ""

    models = _get_gemini_models(prefer_pro=prefer_pro)
    for api_key in keys:
        try:
            client = _make_genai_client(api_key, timeout_ms=90000)
        except Exception:
            continue
        for model_id in models:
            try:
                cfg = types.GenerateContentConfig(temperature=0.0)
                resp = client.models.generate_content(model=model_id, contents=contents, config=cfg)
                um = getattr(resp, "usage_metadata", None)
                if log_tokens_fn and um:
                    in_tok = int(getattr(um, "prompt_token_count", 0) or 0)
                    out_tok = int(getattr(um, "candidates_token_count", 0) or 0)
                    try:
                        log_tokens_fn(model_id, in_tok, out_tok, True, "")
                    except Exception:
                        pass
                raw = (resp.text or "").strip()
                if raw:
                    return raw
            except Exception as e:
                _note_model_error(model_id, e)
                continue
    return ""


# ─────────────────────────────────────────────────────────────
# 공통 유틸리티 (이름 정규화, 숫자/날짜 파싱, 개인정보 마스킹)
# ─────────────────────────────────────────────────────────────

DUMMY_NAMES = {
    "가나다", "홍길동(예시)", "홍길동(샘플)", "샘플", "예시", "합계", "총계", "소계",
    "평균", "인원", "성명", "이름", "사원명", "근로자명", "소득자명", "구분", "비고",
}

SIMULATION_MARKER_PATTERNS = [
    r"^\d+\.\s*격주",
    r"^\d+\.\s*주\s*\d+일\s*근무시",
    r"모의\s*계산",
    r"시뮬레이션",
    r"예시\s*급여",
    r"참고\s*사항",
]


def normalize_korean_name(raw_name: Any) -> str:
    """
    이름 문자열 정규화:
    - '홍길동(HONG GIL DONG)' -> '홍길동'
    - 공백 및 줄바꿈 제거
    """
    if raw_name is None:
        return ""
    s = str(raw_name).strip()
    if not s or s.lower() in ("nan", "none", "null"):
        return ""
    s = re.sub(r"\([^)]*\)", "", s)
    s = re.sub(r"\s+", "", s)
    return s.strip()


def is_valid_person_name(name: str) -> bool:
    """실제 인명인지 판별 (숫자, 기호, 합계/더미 제외)"""
    if not name or len(name) < 2 or len(name) > 15:
        return False
    if name in DUMMY_NAMES:
        return False
    for pat in SIMULATION_MARKER_PATTERNS:
        if re.search(pat, name):
            return False
    if re.search(r"[\d:/%\[\]=+]", name):
        return False
    if any(k in name for k in ("합계", "총계", "소계", "근무시", "급여계산", "근로계약", "단위", "산출식")):
        return False
    return True


def parse_number(val: Any, default: int = 0) -> int:
    """안전한 정수 변환 (콤마, '원', 공백, 소수점 처리)"""
    if val is None:
        return default
    if isinstance(val, (int, float)):
        if pd.isna(val):
            return default
        return int(round(float(val)))
    s = str(val).strip()
    if not s or s.lower() in ("nan", "none", "-", ""):
        return default
    s = s.replace(",", "").replace("원", "").replace(" ", "").strip()
    m_man = re.match(r"^([+-]?\d+(?:\.\d+)?)\s*만$", s)
    if m_man:
        return int(round(float(m_man.group(1)) * 10000))
    try:
        return int(round(float(s)))
    except ValueError:
        return default


def parse_date_str(val: Any) -> str:
    """날짜 셀 값을 'YYYY-MM-DD' 문자열로 변환"""
    if val is None:
        return ""
    if isinstance(val, (datetime, date)):
        return val.strftime("%Y-%m-%d")
    s = str(val).strip()
    if not s or s.lower() in ("nan", "none", "nat", "-"):
        return ""
    m = re.match(r"^(\d{4})[-./](\d{1,2})[-./](\d{1,2})", s)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m2 = re.match(r"^(\d{2})[-./](\d{1,2})[-./](\d{1,2})$", s)
    if m2:
        yy = int(m2.group(1))
        yyyy = 2000 + yy if yy < 50 else 1900 + yy
        return f"{yyyy:04d}-{int(m2.group(2)):02d}-{int(m2.group(3)):02d}"
    m3 = re.match(r"^(\d{4})(\d{2})(\d{2})$", s)
    if m3:
        return f"{m3.group(1)}-{m3.group(2)}-{m3.group(3)}"
    return ""


def normalize_rrn(val: Any) -> str:
    """주민등록번호/생년월일 정규화 (예: 900101-1234567 또는 900101-1******)"""
    if val is None:
        return ""
    s = str(val).strip()
    if not s or s.lower() in ("nan", "none"):
        return ""
    cleaned = re.sub(r"[^0-9*]", "", s)
    if len(cleaned) == 13:
        return f"{cleaned[:6]}-{cleaned[6:]}"
    if len(cleaned) == 6 and cleaned.isdigit():
        return cleaned
    return s


def extract_birth_6digits(rrn_or_birth: str) -> str:
    """주민등록번호 또는 생년월일에서 앞 6자리(YYMMDD) 추출 (급여명세서 PDF 암호용)"""
    if not rrn_or_birth:
        return ""
    digits = re.sub(r"[^0-9]", "", str(rrn_or_birth))
    if len(digits) >= 8 and digits[:2] in ("19", "20"):
        return digits[2:8]
    if len(digits) >= 6:
        return digits[:6]
    return ""


def mask_pii_preview_rows(rows: List[List[Any]]) -> List[List[str]]:
    """
    AI에 엑셀 구조(헤더+샘플행)를 보낼 때 개인정보(성명, 주민등록번호, 전화번호, 계좌번호)를
    완전히 마스킹하여 외부로 실제 개인정보가 전송되지 않도록 보호
    """
    masked: List[List[str]] = []
    for row in rows:
        new_row: List[str] = []
        for cell in row:
            if cell is None:
                new_row.append("")
                continue
            s = str(cell).strip()
            s = re.sub(r"\b\d{6}[-~\s]*[1-8]\d{6}\b", "000000-*******", s)
            s = re.sub(r"\b\d{13}\b", "000000*******", s)
            s = re.sub(r"\b01[016789][-.\s]*\d{3,4}[-.\s]*\d{4}\b", "010-****-****", s)
            norm = normalize_korean_name(s)
            if (
                2 <= len(norm) <= 4
                and re.match(r"^[가-힣]+$", norm)
                and norm not in (
                    "성명", "이름", "사원명", "기본급", "식대", "상여", "합계", "총계",
                    "직급", "부서", "입사일", "퇴사일", "월급여", "시급", "연봉", "구분",
                    "정규직", "계약직", "일용직", "비고", "차인지급액", "공제액계", "지급액계",
                )
            ):
                s = norm[0] + "*" * (len(norm) - 1)
            new_row.append(s)
        masked.append(new_row)
    return masked


# ─────────────────────────────────────────────────────────────
# 1. 거래처 급여 엑셀 파서 (다중 섹션 + 표준/자유양식 + AI 헤더 매핑 폴백)
# ─────────────────────────────────────────────────────────────

HEADER_SYNONYMS: Dict[str, List[str]] = {
    "성명": ["성명", "성 명", "사원명", "이름", "근로자명", "직원명"],
    "사원코드": ["사원코드", "사번", "코드", "사원번호"],
    "주민등록번호": ["주민등록번호", "주민번호", "생년월일"],
    "입사일": ["입사일", "입사일자", "고용일", "채용일"],
    "퇴사일": ["퇴사일", "퇴사일자", "퇴직일", "고용종료일", "상실일"],
    "부서": ["부서", "부서명", "소속"],
    "직급": ["직급", "직위", "직책", "업무내용", "직종"],
    "부양가족수": ["부양가족수", "부양가족", "공제대상가족수"],
    "자녀수": ["8~20세자녀수", "자녀수", "20세이하자녀", "다자녀"],
    "기본급": ["기본급", "월기본급", "기본급여", "본봉"],
    "식대": ["식대", "식대(비과세)", "식사대", "중식대", "급식비"],
    "자가운전보조금": ["자가운전보조금", "자가운전", "차량유지비", "차량보조금"],
    "상여": ["상여", "(세전) 상여", "(세전)상여", "상여금", "인센티브", "성과급", "보너스"],
    "약정연장근로수당": ["약정연장근로수당", "약정추가근로수당", "고정연장수당", "약정연장수당", "포괄연장수당"],
    "약정휴일근로수당": ["약정휴일근로수당", "약정휴일수당", "고정휴일수당"],
    "연장근로수당": ["연장근로수당", "추가근로수당", "연장수당", "초과근무수당", "시간외수당", "OT수당"],
    "휴일근로수당": ["휴일근로수당", "휴일수당", "특근수당"],
    "미사용연차수당": ["미사용연차수당", "연차수당", "월차수당"],
    "결근공제": ["결근공제", "결근차감", "무급공제"],
    "조정금액": ["조정금액", "기타수당", "조정수당", "직책수당", "자격수당"],
    "지급액계": ["지급액계", "지급합계", "급여합계", "세전합계", "세전급여", "총지급액", "지급총액"],
    "약정시급": ["약정시급", "시급", "통상시급"],
    "연장근무시간": ["연장근무시간", "연장근로시간", "추가근무시간"],
    "휴일근무시간": ["휴일근무시간", "휴일근로시간"],
    "결근시간": ["결근시간"],
    "주근무시간": ["주 근무시간", "주근무시간", "주소정근로시간"],
    "월근무시간": ["월 근무시간", "월근무시간", "월소정근로시간"],
    "국민연금": ["국민연금", "연금보험료"],
    "건강보험": ["건강보험", "건강보험료"],
    "장기요양보험료": ["장기요양보험료", "장기요양", "요양보험료"],
    "고용보험": ["고용보험", "고용보험료"],
    "건강보험료정산": ["건강보험료정산", "건강정산"],
    "장기요양보험료정산": ["장기요양보험료정산", "요양정산", "장기요양정산"],
    "국민연금정산": ["국민연금정산", "연금정산"],
    "학자금상환액": ["학자금상환액", "학자금공제"],
    "소득세": ["소득세", "갑근세", "근로소득세"],
    "지방소득세": ["지방소득세", "주민세"],
}


def _clean_header_cell(cell_val: Any) -> str:
    if cell_val is None:
        return ""
    s = str(cell_val).replace("\n", " ").replace("\r", " ").strip()
    s = re.sub(r"\s+", " ", s)
    return s


def _match_canonical_field(header_text: str) -> Optional[str]:
    """헤더 셀 문자열을 표준 필드명으로 매핑"""
    if not header_text:
        return None
    h_nospace = re.sub(r"\s+", "", header_text)
    for canonical, synonyms in HEADER_SYNONYMS.items():
        for syn in synonyms:
            syn_nospace = re.sub(r"\s+", "", syn)
            if h_nospace == syn_nospace:
                return canonical
    for canonical, synonyms in HEADER_SYNONYMS.items():
        for syn in synonyms:
            syn_nospace = re.sub(r"\s+", "", syn)
            if len(syn_nospace) >= 3 and syn_nospace in h_nospace:
                if canonical == "연장근로수당" and "약정" in h_nospace:
                    return "약정연장근로수당"
                if canonical == "휴일근로수당" and "약정" in h_nospace:
                    return "약정휴일근로수당"
                if canonical == "건강보험" and "정산" in h_nospace:
                    return "건강보험료정산"
                if canonical == "장기요양보험료" and "정산" in h_nospace:
                    return "장기요양보험료정산"
                if canonical == "국민연금" and "정산" in h_nospace:
                    return "국민연금정산"
                return canonical
    return None


def _infer_excel_columns_with_ai(
    all_rows: List[List[Any]],
    gemini_api_key: Optional[str] = None,
) -> Optional[Tuple[int, Dict[int, str]]]:
    """
    거래처 고유 엑셀 양식에서 규칙 기반으로 헤더를 찾지 못했을 때,
    상위 15줄의 개인정보를 완전히 마스킹(홍*동, 000000-*******)한 뒤
    앱 표준 Gemini 클라이언트(Vertex 크레딧 우선, Flash -> Argon 폴백)로
    데이터 시작 행과 열 번호 매핑을 추론합니다.
    """
    preview = mask_pii_preview_rows(all_rows[:15])
    allowed_fields = list(HEADER_SYNONYMS.keys())
    prompt = (
        "아래는 거래처 급여 엑셀 시트의 상위 15행(개인정보 마스킹 완료)입니다.\n"
        "각 행의 0-기반 행 번호(header_row_index)와 0-기반 열 번호(column_map)를 분석하여 "
        "표준 급여 필드명으로 매핑한 JSON만 출력하세요.\n"
        f"- 허용 표준 필드명: {allowed_fields}\n"
        "- 출력 JSON 형식 예시:\n"
        '{"header_row_index": 2, "column_map": {"0": "성명", "1": "직급", "2": "기본급", "3": "식대", "4": "지급액계"}}\n\n'
        f"[엑셀 상위 행 데이터]\n{json.dumps(preview, ensure_ascii=False)}"
    )
    raw = _call_gemini_contents([prompt], prefer_pro=False, explicit_api_key=gemini_api_key)
    if not raw:
        return None
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        h_idx = int(data.get("header_row_index", 0))
        cmap_raw = data.get("column_map", {})
        col_map: Dict[int, str] = {}
        for k_str, v_field in cmap_raw.items():
            if str(k_str).isdigit() and v_field in HEADER_SYNONYMS:
                col_map[int(k_str)] = str(v_field)
        if "성명" in col_map.values() and len(col_map) >= 2:
            return (h_idx, col_map)
    except Exception:
        return None
    return None


def parse_client_payroll_excel(
    file_bytes: bytes,
    filename: str = "",
    effective_table: str = "2026.03",
    gemini_api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    거래처 급여 엑셀 파싱 (다중 테이블 병합 지원 + 위하고 양식 지원 + 비정형 양식 AI 헤더 매핑 폴백):
    - 반환값:
      {
        "employees": [표준 급여대장 행 dict 리스트],
        "meta": {"corp_name": ..., "year_month": ..., "pay_date": ..., "detected_tables": ...},
        "warnings": [...]
      }
    """
    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
    sheet = wb[wb.sheetnames[0]]

    all_rows: List[List[Any]] = []
    for r in sheet.iter_rows(values_only=True):
        all_rows.append(list(r))

    meta: Dict[str, Any] = {
        "corp_name": "",
        "year_month": "",
        "pay_date": "",
        "detected_tables": 0,
    }
    warnings: List[str] = []

    if filename:
        m_ym = re.search(r"(20\d{2})[-._년\s]*(\d{1,2})", filename)
        if m_ym:
            meta["year_month"] = f"{int(m_ym.group(1)):04d}-{int(m_ym.group(2)):02d}"
        else:
            m_m = re.search(r"(\d{1,2})\s*월", filename)
            if m_m:
                meta["year_month"] = f"{datetime.now().year:04d}-{int(m_m.group(1)):02d}"

    for r_idx in range(min(30, len(all_rows))):
        row_text = " ".join(str(c) for c in all_rows[r_idx] if c is not None)
        m_title_ym = re.search(r"(20\d{2})\s*년\s*(\d{1,2})\s*월", row_text)
        if m_title_ym and not meta["year_month"]:
            meta["year_month"] = f"{int(m_title_ym.group(1)):04d}-{int(m_title_ym.group(2)):02d}"

    header_blocks: List[Tuple[int, Dict[int, str]]] = []
    idx = 0
    while idx < len(all_rows):
        row = all_rows[idx]
        col_map: Dict[int, str] = {}
        next_row = all_rows[idx + 1] if idx + 1 < len(all_rows) else []
        for c_i, cell_val in enumerate(row):
            h_txt = _clean_header_cell(cell_val)
            mapped = _match_canonical_field(h_txt)
            if not mapped and c_i < len(next_row):
                sub_txt = _clean_header_cell(next_row[c_i])
                mapped = _match_canonical_field(sub_txt)
            if mapped and mapped not in col_map.values():
                col_map[c_i] = mapped

        if "성명" in col_map.values() and len(col_map) >= 3:
            used_second_row = False
            if idx + 1 < len(all_rows):
                sub_matches = sum(
                    1 for c_i in range(len(next_row))
                    if _match_canonical_field(_clean_header_cell(next_row[c_i])) is not None
                )
                if sub_matches >= 3:
                    used_second_row = True
            header_blocks.append((idx + (1 if used_second_row else 0), col_map))
            if used_second_row:
                idx += 2
                continue
        idx += 1

    # 규칙 기반으로 헤더를 찾지 못한 비정형 엑셀인 경우, 개인정보 마스킹 후 AI 헤더 매핑 폴백 가동
    if not header_blocks and all_rows:
        ai_inferred = _infer_excel_columns_with_ai(all_rows, gemini_api_key=gemini_api_key)
        if ai_inferred is not None:
            header_blocks.append(ai_inferred)
            warnings.append("비정형 엑셀 서식이 감지되어 AI 헤더 매핑(개인정보 마스킹 보호)으로 열 구조를 인식했습니다.")

    meta["detected_tables"] = len(header_blocks)

    merged_by_name: Dict[str, Dict[str, Any]] = {}
    name_order: List[str] = []

    for b_i, (h_row_idx, col_map) in enumerate(header_blocks):
        next_h_row_idx = header_blocks[b_i + 1][0] if b_i + 1 < len(header_blocks) else len(all_rows)
        name_col_idx = [c for c, f in col_map.items() if f == "성명"][0]

        stop_current_block = False
        for r_idx in range(h_row_idx + 1, next_h_row_idx):
            row = all_rows[r_idx]
            non_empty_texts = [str(c).strip() for c in row if c is not None and str(c).strip() != ""]
            if not non_empty_texts:
                continue

            joined_line = " ".join(non_empty_texts)
            for pat in SIMULATION_MARKER_PATTERNS:
                if re.search(pat, joined_line):
                    stop_current_block = True
                    break
            if stop_current_block:
                break

            raw_name = row[name_col_idx] if name_col_idx < len(row) else None
            if raw_name is None or str(raw_name).strip() in ("", "합계", "총계", "소계"):
                num_cols = [c for c, f in col_map.items() if f in ("기본급", "지급액계")]
                if any(c < len(row) and parse_number(row[c], 0) > 0 for c in num_cols):
                    break
                continue

            norm_name = normalize_korean_name(raw_name)
            if not is_valid_person_name(norm_name):
                continue

            if norm_name not in merged_by_name:
                merged_by_name[norm_name] = {
                    "성명": norm_name,
                    "원본성명": str(raw_name).strip(),
                }
                name_order.append(norm_name)

            rec = merged_by_name[norm_name]
            for c_idx, field_name in col_map.items():
                if c_idx >= len(row) or field_name == "성명":
                    continue
                val = row[c_idx]
                if val is None or str(val).strip() == "":
                    continue
                if field_name in ("입사일", "퇴사일"):
                    d_str = parse_date_str(val)
                    if d_str:
                        rec[field_name] = d_str
                elif field_name == "주민등록번호":
                    rrn_str = normalize_rrn(val)
                    if rrn_str:
                        rec[field_name] = rrn_str
                elif field_name in ("사원코드", "부서", "직급"):
                    rec[field_name] = str(val).strip()
                elif field_name in ("연장근무시간", "휴일근무시간", "결근시간", "주근무시간", "월근무시간"):
                    try:
                        rec[field_name] = round(float(val), 2)
                    except (ValueError, TypeError):
                        pass
                else:
                    rec[field_name] = parse_number(val, 0)

    employees: List[Dict[str, Any]] = []
    for idx_emp, norm_name in enumerate(name_order, start=1):
        raw_rec = merged_by_name[norm_name]
        emp_code = raw_rec.get("사원코드") or f"{idx_emp:03d}"

        has_preset_ins = any(
            raw_rec.get(k, 0) > 0
            for k in ("국민연금", "건강보험", "장기요양보험료", "고용보험")
        )
        notice_override: Optional[Dict[str, int]] = None
        if has_preset_ins:
            notice_override = {
                "국민연금": raw_rec.get("국민연금", 0),
                "건강보험": raw_rec.get("건강보험", 0),
                "장기요양보험료": raw_rec.get("장기요양보험료", 0),
                "고용보험": raw_rec.get("고용보험", 0),
                "건강보험료정산": raw_rec.get("건강보험료정산", 0),
                "장기요양보험료정산": raw_rec.get("장기요양보험료정산", 0),
                "국민연금정산": raw_rec.get("국민연금정산", 0),
            }

        # 기본급이 비어있고 지급액계만 있는 양식의 경우 지급액계 - 식대 등으로 기본급 역산
        base_pay_in = raw_rec.get("기본급", 0)
        if base_pay_in == 0 and raw_rec.get("지급액계", 0) > 0:
            other_sum = (
                raw_rec.get("상여", 0)
                + raw_rec.get("식대", 0)
                + raw_rec.get("자가운전보조금", 0)
                + raw_rec.get("약정연장근로수당", 0)
                + raw_rec.get("약정휴일근로수당", 0)
                + raw_rec.get("연장근로수당", 0)
                + raw_rec.get("휴일근로수당", 0)
                + raw_rec.get("미사용연차수당", 0)
                + raw_rec.get("결근공제", 0)
                + raw_rec.get("조정금액", 0)
            )
            base_pay_in = max(0, raw_rec["지급액계"] - other_sum)

        row_calc = calculate_employee_payroll_row(
            base_pay=base_pay_in,
            bonus=raw_rec.get("상여", 0),
            meal_allowance=raw_rec.get("식대", 0),
            car_allowance=raw_rec.get("자가운전보조금", 0),
            fixed_overtime_pay=raw_rec.get("약정연장근로수당", 0),
            fixed_holiday_pay=raw_rec.get("약정휴일근로수당", 0),
            overtime_pay=raw_rec.get("연장근로수당", 0),
            holiday_pay=raw_rec.get("휴일근로수당", 0),
            unused_leave_pay=raw_rec.get("미사용연차수당", 0),
            absence_deduction=raw_rec.get("결근공제", 0),
            adjustment_pay=raw_rec.get("조정금액", 0),
            dependents=max(1, raw_rec.get("부양가족수", 1)),
            children_8_20=max(0, raw_rec.get("자녀수", 0)),
            notice_insurance=notice_override,
            student_loan_repayment=raw_rec.get("학자금상환액", 0),
            effective_table=effective_table,
            is_ceo=is_ceo_position(raw_rec.get("직급", "")),
        )

        emp_entry: Dict[str, Any] = {
            "사원코드": str(emp_code).zfill(3) if str(emp_code).isdigit() else str(emp_code),
            "성명": norm_name,
            "주민등록번호": raw_rec.get("주민등록번호", ""),
            "입사일": raw_rec.get("입사일", ""),
            "퇴사일": raw_rec.get("퇴사일", ""),
            "부서": raw_rec.get("부서", ""),
            "직급": raw_rec.get("직급", ""),
            "부양가족수": max(1, raw_rec.get("부양가족수", 1)),
            "자녀수": max(0, raw_rec.get("자녀수", 0)),
            "입력기준": "세전",
            "목표실수령액": 0,
            **row_calc,
            "약정시급": raw_rec.get("약정시급", 0),
            "연장근무시간": raw_rec.get("연장근무시간", 0.0),
            "휴일근무시간": raw_rec.get("휴일근무시간", 0.0),
            "결근시간": raw_rec.get("결근시간", 0.0),
            "주근무시간": raw_rec.get("주근무시간", 40.0),
            "월근무시간": raw_rec.get("월근무시간", 209.0),
        }
        employees.append(emp_entry)

    return {
        "employees": employees,
        "meta": meta,
        "warnings": warnings,
    }


# ─────────────────────────────────────────────────────────────
# 2. 4대보험 고지내역 PDF / 이미지 파서 (건강·요양 / 국민연금 / 고용보험)
# ─────────────────────────────────────────────────────────────

def parse_insurance_notice_pdf(file_bytes: bytes, filename: str = "") -> Dict[str, Any]:
    """
    4대보험 고지내역 PDF 자동 판별 및 직원별 고지보험료 추출:
    - 건강보험 산출내역서 PDF:
      직원별 '건강'(산출보험료, 정산금액/당월경감), '요양'(산출보험료, 정산금액) 추출
    - 국민연금 결정내역 통지서 PDF:
      직원별 '근로자기여금', '주민등록번호(13자리)', 소급분 정산 추출
    - 고용보험 산정보험료 내역 PDF:
      직원별 '근로자실업급여보험료' 추출
    """
    reader = PdfReader(io.BytesIO(file_bytes))
    full_text_pages: List[str] = []
    for page in reader.pages:
        full_text_pages.append(page.extract_text() or "")
    full_text = "\n".join(full_text_pages)

    if "건강보험" in full_text and ("보수월액" in full_text or "장기요양" in full_text or "증번호" in full_text):
        return _parse_nhis_pdf_text(full_text, filename)
    if "국민연금" in full_text and ("근로자기여금" in full_text or "연금보험료" in full_text):
        return _parse_nps_pdf_text(full_text, filename)
    if "고용보험" in full_text or "근로자실업급여보험료" in full_text or "당월산정보험료" in full_text:
        return _parse_ei_pdf_text(full_text, filename)

    return {
        "notice_type": "unknown",
        "corp_name": "",
        "year_month": "",
        "records": {},
        "message": f"고지내역 유형을 자동 식별하지 못했습니다 ({filename}).",
    }


def _parse_nhis_pdf_text(text: str, filename: str = "") -> Dict[str, Any]:
    corp_name = ""
    m_corp = re.search(r"사업장명칭\s+([^\n]+?)\s+단위사업장", text)
    if m_corp:
        corp_name = m_corp.group(1).strip()

    year_month = ""
    m_ym = re.search(r"(20\d{2})년\s*(\d{1,2})월분", text)
    if m_ym:
        year_month = f"{int(m_ym.group(1)):04d}-{int(m_ym.group(2)):02d}"

    records: Dict[str, Dict[str, Any]] = {}
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    current_name: Optional[str] = None
    for ln in lines:
        m_health = re.match(
            r"^(\d+)\s+([가-힣A-Za-z]+)\s+(\d{8,12})\s+(\d{6}-[1-8*]+)\s+([\d,]+)\s+건강\s+(.+)$",
            ln,
        )
        if m_health:
            name = normalize_korean_name(m_health.group(2))
            rrn_masked = m_health.group(4)
            bosu = parse_number(m_health.group(5))
            tail = m_health.group(6)
            parsed_nums = _extract_nhis_line_amounts(tail)

            current_name = name
            if name not in records:
                records[name] = {
                    "성명": name,
                    "주민등록번호_마스킹": rrn_masked,
                    "보수월액": bosu,
                    "건강보험": 0,
                    "장기요양보험료": 0,
                    "건강보험료정산": 0,
                    "장기요양보험료정산": 0,
                    "사유": parsed_nums["reason"],
                }
            records[name]["건강보험"] += parsed_nums["calculated"]
            records[name]["건강보험료정산"] += parsed_nums["settlement"]
            continue

        if current_name and ln.startswith("요양"):
            tail = ln[len("요양"):].strip()
            parsed_nums = _extract_nhis_line_amounts(tail)
            records[current_name]["장기요양보험료"] += parsed_nums["calculated"]
            records[current_name]["장기요양보험료정산"] += parsed_nums["settlement"]
            current_name = None

    return {
        "notice_type": "건강보험",
        "corp_name": corp_name,
        "year_month": year_month,
        "records": records,
        "message": f"건강보험·장기요양 고지내역 {len(records)}명 추출 완료",
    }


def _extract_nhis_line_amounts(tail: str) -> Dict[str, Any]:
    cleaned = re.sub(r"\b20\d{4}~20\d{4}\b", " ", tail)
    reasons = re.findall(r"[가-힣]+", cleaned)
    reason_str = " ".join(reasons) if reasons else ""
    nums = [parse_number(tok) for tok in re.findall(r"[+-]?[\d,]+", cleaned)]
    if len(nums) >= 3:
        return {
            "calculated": nums[0],
            "settlement": nums[1],
            "billed": nums[-1],
            "reason": reason_str,
        }
    if len(nums) == 2:
        return {
            "calculated": nums[0],
            "settlement": 0,
            "billed": nums[1],
            "reason": reason_str,
        }
    if len(nums) == 1:
        return {
            "calculated": nums[0],
            "settlement": 0,
            "billed": nums[0],
            "reason": reason_str,
        }
    return {"calculated": 0, "settlement": 0, "billed": 0, "reason": reason_str}


def _parse_nps_pdf_text(text: str, filename: str = "") -> Dict[str, Any]:
    corp_name = ""
    year_month = ""
    m_ym = re.search(r"(20\d{2})년\s*(\d{1,2})월분", text)
    if m_ym:
        year_month = f"{int(m_ym.group(1)):04d}-{int(m_ym.group(2)):02d}"

    records: Dict[str, Dict[str, Any]] = {}
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    in_retro_section = False
    for ln in lines:
        if "소급분 내역" in ln or "정산사유" in ln:
            in_retro_section = True
            continue

        if not in_retro_section:
            m_reg = re.match(
                r"^(\d+)\s+([가-힣A-Za-z]+)\s+(\d{13}|\d{6}-\d{7})\s+([+-]?[\d,]+)\s+([+-]?[\d,]+)\s+([+-]?[\d,]+)$",
                ln,
            )
            if m_reg:
                name = normalize_korean_name(m_reg.group(2))
                rrn = normalize_rrn(m_reg.group(3))
                emp_contrib = parse_number(m_reg.group(5))
                records[name] = {
                    "성명": name,
                    "주민등록번호": rrn,
                    "국민연금": emp_contrib,
                    "국민연금정산": 0,
                }
        else:
            m_retro = re.match(
                r"^(\d+)\s+([가-힣A-Za-z]+)\s+(\d{13}|\d{6}-\d{7})\s+(\S+)\s+(\S+)\s+([+-]?[\d,]+)\s+([+-]?[\d,]+)\s+([+-]?[\d,]+)$",
                ln,
            )
            if m_retro:
                name = normalize_korean_name(m_retro.group(2))
                rrn = normalize_rrn(m_retro.group(3))
                retro_emp = parse_number(m_retro.group(7))
                if name not in records:
                    records[name] = {
                        "성명": name,
                        "주민등록번호": rrn,
                        "국민연금": 0,
                        "국민연금정산": 0,
                    }
                records[name]["국민연금정산"] += retro_emp

    return {
        "notice_type": "국민연금",
        "corp_name": corp_name,
        "year_month": year_month,
        "records": records,
        "message": f"국민연금 결정내역 {len(records)}명 추출 완료",
    }


def _parse_ei_pdf_text(text: str, filename: str = "") -> Dict[str, Any]:
    records: Dict[str, Dict[str, Any]] = {}
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    current_name: Optional[str] = None

    for ln in lines:
        m_person = re.search(r"([가-힣]{2,5})\s+(\d{4}[-.]\d{2}[-.]\d{2}|\d{2}[-.]\d{2}[-.]\d{2})", ln)
        if m_person and "근로자" not in m_person.group(1):
            current_name = normalize_korean_name(m_person.group(1))
        if "근로자실업급여보험료" in ln and current_name:
            nums = [parse_number(tok) for tok in re.findall(r"[+-]?[\d,]+", ln)]
            if nums:
                ei_fee = nums[1] if len(nums) >= 2 else nums[-1]
                records[current_name] = {
                    "성명": current_name,
                    "고용보험": ei_fee,
                }
    return {
        "notice_type": "고용보험",
        "corp_name": "",
        "year_month": "",
        "records": records,
        "message": f"고용보험 산정내역 {len(records)}명 추출 완료",
    }


def apply_insurance_notices_to_employees(
    employees: List[Dict[str, Any]],
    notice_results: List[Dict[str, Any]],
    effective_table: str = "2026.03",
) -> Tuple[List[Dict[str, Any]], List[str]]:
    logs: List[str] = []
    by_name: Dict[str, Dict[str, Any]] = {
        normalize_korean_name(emp.get("성명", "")): emp for emp in employees
    }

    for notice in notice_results:
        ntype = notice.get("notice_type", "")
        recs = notice.get("records", {})
        matched_cnt = 0
        for name, n_data in recs.items():
            norm = normalize_korean_name(name)
            if norm not in by_name:
                continue
            emp = by_name[norm]
            matched_cnt += 1

            if n_data.get("주민등록번호") and (
                not emp.get("주민등록번호") or "*" in str(emp.get("주민등록번호"))
            ):
                emp["주민등록번호"] = n_data["주민등록번호"]
            elif n_data.get("주민등록번호_마스킹") and not emp.get("주민등록번호"):
                emp["주민등록번호"] = n_data["주민등록번호_마스킹"]

            if ntype == "건강보험":
                emp["건강보험"] = n_data.get("건강보험", emp.get("건강보험", 0))
                emp["장기요양보험료"] = n_data.get("장기요양보험료", emp.get("장기요양보험료", 0))
                emp["건강보험료정산"] = n_data.get("건강보험료정산", emp.get("건강보험료정산", 0))
                emp["장기요양보험료정산"] = n_data.get("장기요양보험료정산", emp.get("장기요양보험료정산", 0))
                emp["_nhis_notice_applied"] = True
            elif ntype == "국민연금":
                emp["국민연금"] = n_data.get("국민연금", emp.get("국민연금", 0))
                emp["_nps_retro_suggested"] = n_data.get("국민연금정산", 0)
                emp["_nps_notice_applied"] = True
            elif ntype == "고용보험":
                emp["고용보험"] = n_data.get("고용보험", emp.get("고용보험", 0))
                emp["_ei_notice_applied"] = True

        if ntype and recs:
            logs.append(f"[{ntype} 고지내역] 총 {len(recs)}명 중 급여대장 {matched_cnt}명 자동 매칭 완료")

    updated_employees: List[Dict[str, Any]] = []
    for emp in employees:
        notice_ins = None
        if any(emp.get(flag) for flag in ("_nhis_notice_applied", "_nps_notice_applied", "_ei_notice_applied")):
            notice_ins = {
                "국민연금": emp.get("국민연금", 0),
                "건강보험": emp.get("건강보험", 0),
                "장기요양보험료": emp.get("장기요양보험료", 0),
                "고용보험": emp.get("고용보험", 0),
                "건강보험료정산": emp.get("건강보험료정산", 0),
                "장기요양보험료정산": emp.get("장기요양보험료정산", 0),
                "국민연금정산": emp.get("국민연금정산", 0),
            }

        if emp.get("입력기준") == "세후역산" and emp.get("목표실수령액", 0) > 0:
            solved = solve_gross_from_net_employee(
                target_net_pay=emp["목표실수령액"],
                non_taxable_pay=emp.get("식대", 0) + emp.get("자가운전보조금", 0),
                dependents=emp.get("부양가족수", 1),
                children_8_20=emp.get("자녀수", 0),
                notice_insurance=notice_ins,
                student_loan_repayment=emp.get("학자금상환액", 0),
                effective_table=effective_table,
            )
            emp["기본급"] = solved["base_pay"]

        recalc = calculate_employee_payroll_row(
            base_pay=emp.get("기본급", 0),
            bonus=emp.get("상여", 0),
            meal_allowance=emp.get("식대", 0),
            car_allowance=emp.get("자가운전보조금", 0),
            fixed_overtime_pay=emp.get("약정연장근로수당", 0),
            fixed_holiday_pay=emp.get("약정휴일근로수당", 0),
            overtime_pay=emp.get("연장근로수당", 0),
            holiday_pay=emp.get("휴일근로수당", 0),
            unused_leave_pay=emp.get("미사용연차수당", 0),
            absence_deduction=emp.get("결근공제", 0),
            adjustment_pay=emp.get("조정금액", 0),
            dependents=emp.get("부양가족수", 1),
            children_8_20=emp.get("자녀수", 0),
            notice_insurance=notice_ins,
            student_loan_repayment=emp.get("학자금상환액", 0),
            effective_table=effective_table,
        )
        emp.update(recalc)
        updated_employees.append(emp)

    return updated_employees, logs


# ─────────────────────────────────────────────────────────────
# 3. 사업소득(3.3%) 엑셀 파서
# ─────────────────────────────────────────────────────────────

def parse_freelancer_excel(
    file_bytes: bytes,
    filename: str = "",
    default_year_month: str = "",
    default_pay_date: str = "",
) -> List[Dict[str, Any]]:
    """사업소득대장 또는 위하고 사업소득 업로드 엑셀 파싱"""
    try:
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
        sheet = wb[wb.sheetnames[0]]
        rows = [list(r) for r in sheet.iter_rows(values_only=True)]
    except Exception:
        df = pd.read_excel(io.BytesIO(file_bytes), header=None)
        rows = df.values.tolist()

    header_idx = -1
    col_map: Dict[int, str] = {}
    for r_i, row in enumerate(rows):
        temp_map: Dict[int, str] = {}
        for c_i, val in enumerate(row):
            txt = _clean_header_cell(val)
            if txt in ("소득자명", "성명", "성 명", "이름"):
                temp_map[c_i] = "성명"
            elif txt in ("주민등록번호", "주민번호", "생년월일"):
                temp_map[c_i] = "주민등록번호"
            elif txt in ("지급총액", "지급액", "세전금액", "세전"):
                temp_map[c_i] = "지급총액"
            elif txt in ("차인지급액", "실지급액", "세후금액"):
                temp_map[c_i] = "차인지급액"
            elif txt in ("귀속년월", "귀속연월"):
                temp_map[c_i] = "귀속년월"
            elif txt in ("지급년월일", "지급연월", "지급일자"):
                temp_map[c_i] = "지급년월일"
            elif txt in ("소득구분", "업종코드", "직종"):
                temp_map[c_i] = "소득구분"
            elif txt in ("코드", "사번"):
                temp_map[c_i] = "코드"
        if "성명" in temp_map.values() and len(temp_map) >= 2:
            header_idx = r_i
            col_map = temp_map
            break

    if header_idx < 0:
        return []

    freelancers: List[Dict[str, Any]] = []
    for r_i in range(header_idx + 1, len(rows)):
        row = rows[r_i]
        name_cols = [c for c, f in col_map.items() if f == "성명"]
        if not name_cols or name_cols[0] >= len(row):
            continue
        norm_name = normalize_korean_name(row[name_cols[0]])
        if not is_valid_person_name(norm_name):
            continue

        rec: Dict[str, Any] = {}
        for c_i, f_name in col_map.items():
            if c_i < len(row):
                rec[f_name] = row[c_i]

        gross_val = parse_number(rec.get("지급총액"), 0)
        net_val = parse_number(rec.get("차인지급액"), 0)

        if gross_val == 0 and net_val > 0:
            calc = solve_gross_from_net_freelancer(net_val)
            input_mode = "세후역산"
        else:
            calc = calculate_freelancer_row(gross_val)
            input_mode = "세전"

        code_val = str(rec.get("코드") or f"{len(freelancers) + 1:04d}").strip()
        ym_val = str(rec.get("귀속년월") or default_year_month or datetime.now().strftime("%Y-%m")).strip()
        pay_d_val = str(rec.get("지급년월일") or default_pay_date or datetime.now().strftime("%Y-%m-%d")).strip()

        freelancers.append({
            "코드": code_val,
            "성명": norm_name,
            "주민등록번호": normalize_rrn(rec.get("주민등록번호", "")),
            "소득구분": str(rec.get("소득구분") or "940909").strip(),
            "귀속년월": ym_val,
            "지급년월일": pay_d_val,
            "입력기준": input_mode,
            "지급총액": calc["gross_pay"],
            "세율": 3,
            "소득세": calc["income_tax"],
            "지방소득세": calc["local_tax"],
            "공제액계": calc["total_deduction"],
            "차인지급액": calc["net_pay"],
        })
    return freelancers


# ─────────────────────────────────────────────────────────────
# 4. 카카오톡 텍스트 & 이미지 캡처 파서 (정규직 세전/세후 역산 & 3.3% 자동 분류)
# ─────────────────────────────────────────────────────────────

def parse_kakao_text_instructions(
    raw_text: str,
    existing_employees: Optional[List[Dict[str, Any]]] = None,
    existing_freelancers: Optional[List[Dict[str, Any]]] = None,
    default_year_month: str = "",
    default_pay_date: str = "",
    effective_table: str = "2026.03",
) -> Dict[str, Any]:
    if not raw_text or not raw_text.strip():
        return {"employees": [], "freelancers": [], "messages": []}

    existing_emp_map = {
        normalize_korean_name(e.get("성명", "")): e for e in (existing_employees or [])
    }
    existing_free_map = {
        normalize_korean_name(f.get("성명", "")): f for f in (existing_freelancers or [])
    }

    text_norm = re.sub(r"(?<=\d),(?=\d{3}\b)", "", raw_text)
    segments = [
        seg.strip()
        for seg in re.split(r"[\n;/]+|(?<!\d),(?!\d)", text_norm)
        if seg.strip()
    ]

    parsed_employees: List[Dict[str, Any]] = []
    parsed_freelancers: List[Dict[str, Any]] = []
    messages: List[str] = []

    for seg in segments:
        m_name = re.search(r"([가-힣]{2,4})", seg)
        if not m_name:
            continue
        candidates = re.findall(r"[가-힣]{2,4}", seg)
        person_name = ""
        for cand in candidates:
            if cand not in (
                "실수령", "실수령액", "세후금액", "세전금액", "세전으로", "세후로",
                "프리랜서", "사업소득", "아르바이트", "알바비", "식대포함", "입금요청",
                "입금해", "주세요", "만원씩", "만원", "기본급", "상여금", "연장수당",
            ):
                person_name = cand
                break
        if not person_name:
            continue

        is_freelancer = (
            any(k in seg for k in ("3.3", "프리랜서", "사업소득", "외주", "용역"))
            or (person_name in existing_free_map and person_name not in existing_emp_map)
        )
        is_net = any(k in seg for k in ("실수령", "세후", "실지급", "맞춰", "입금기준"))

        meal_val = 200_000
        m_meal = re.search(r"식대\s*(\d+(?:\.\d+)?)\s*(만\s*원|만|원)?", seg)
        if m_meal:
            raw_m = float(m_meal.group(1))
            unit_m = m_meal.group(2) or ""
            meal_val = int(raw_m * 10000) if ("만" in unit_m or raw_m < 100) else int(raw_m)
            seg_wo_meal = seg[:m_meal.start()] + " " + seg[m_meal.end():]
        else:
            seg_wo_meal = seg

        seg_clean = re.sub(r"3\.3\s*%?", " ", seg_wo_meal)
        m_amt = re.search(r"(\d+(?:\.\d+)?)\s*(만\s*원|만|원)?", seg_clean)
        if not m_amt:
            continue
        raw_num = float(m_amt.group(1))
        unit = m_amt.group(2) or ""
        if "만" in unit or raw_num < 5000:
            amount = int(round(raw_num * 10000))
        else:
            amount = int(round(raw_num))

        if amount <= 0:
            continue

        if is_freelancer:
            if is_net:
                calc = solve_gross_from_net_freelancer(amount)
                in_mode = "세후역산"
            else:
                calc = calculate_freelancer_row(amount)
                in_mode = "세전"

            base_f = existing_free_map.get(person_name, {})
            parsed_freelancers.append({
                "코드": base_f.get("코드") or f"{len(parsed_freelancers) + 1:04d}",
                "성명": person_name,
                "주민등록번호": base_f.get("주민등록번호", ""),
                "소득구분": base_f.get("소득구분", "940909"),
                "귀속년월": default_year_month or datetime.now().strftime("%Y-%m"),
                "지급년월일": default_pay_date or datetime.now().strftime("%Y-%m-%d"),
                "입력기준": in_mode,
                "지급총액": calc["gross_pay"],
                "세율": 3,
                "소득세": calc["income_tax"],
                "지방소득세": calc["local_tax"],
                "공제액계": calc["total_deduction"],
                "차인지급액": calc["net_pay"],
            })
            messages.append(
                f"[사업소득 3.3%] {person_name}: {in_mode} 기준 세전 {calc['gross_pay']:,}원 -> 실지급 {calc['net_pay']:,}원"
            )
        else:
            base_e = existing_emp_map.get(person_name, {})
            deps = base_e.get("부양가족수", 1)
            children = base_e.get("자녀수", 0)
            meal = meal_val if m_meal else base_e.get("식대", 200_000 if amount >= 2_000_000 else 0)

            if is_net:
                solved = solve_gross_from_net_employee(
                    target_net_pay=amount,
                    non_taxable_pay=meal,
                    dependents=deps,
                    children_8_20=children,
                    effective_table=effective_table,
                )
                row_calc = calculate_employee_payroll_row(
                    base_pay=solved["base_pay"],
                    meal_allowance=meal,
                    dependents=deps,
                    children_8_20=children,
                    effective_table=effective_table,
                )
                in_mode = "세후역산"
                target_net = amount
            else:
                base_pay_val = max(0, amount - meal)
                row_calc = calculate_employee_payroll_row(
                    base_pay=base_pay_val,
                    meal_allowance=meal,
                    dependents=deps,
                    children_8_20=children,
                    effective_table=effective_table,
                )
                in_mode = "세전"
                target_net = 0

            parsed_employees.append({
                "사원코드": base_e.get("사원코드") or f"{len(parsed_employees) + 1:03d}",
                "성명": person_name,
                "주민등록번호": base_e.get("주민등록번호", ""),
                "입사일": base_e.get("입사일", ""),
                "퇴사일": base_e.get("퇴사일", ""),
                "부서": base_e.get("부서", ""),
                "직급": base_e.get("직급", ""),
                "부양가족수": deps,
                "자녀수": children,
                "입력기준": in_mode,
                "목표실수령액": target_net,
                **row_calc,
                "약정시급": base_e.get("약정시급", 0),
                "연장근무시간": 0.0,
                "휴일근무시간": 0.0,
                "결근시간": 0.0,
                "주근무시간": 40.0,
                "월근무시간": 209.0,
            })
            messages.append(
                f"[4대보험 근로자] {person_name}: {in_mode} 기준 지급액계 {row_calc['지급액계']:,}원 -> 차인지급액 {row_calc['차인지급액']:,}원"
            )

    return {
        "employees": parsed_employees,
        "freelancers": parsed_freelancers,
        "messages": messages,
    }


def parse_image_with_gemini_vision(
    image_bytes: bytes,
    mime_type: str = "image/png",
    gemini_api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    고용보험 산정내역 이미지(PNG/JPG) 또는 카카오톡 급여 캡처 이미지를
    앱 표준 Gemini 엔진(Vertex AI 크레딧 우선, FLASH_MODEL_ID / PAID_PRO_MODEL_IDS 체인, 504/429 재시도)으로 판독합니다.
    """
    try:
        from google.genai import types

        prompt = (
            "이 이미지는 세무사 사무실에 전달된 (1) 고용보험 산정보험료 근로자내역 표 이미지이거나, "
            "(2) 거래처의 급여/프리랜서 지급 요청 캡처(카카오톡 등)입니다.\n"
            "반드시 아래 JSON 형식으로만 응답하세요:\n"
            "1) 고용보험 근로자내역 표인 경우:\n"
            '{"type": "ei_notice", "records": [{"name": "근로자명", "ei_fee": 근로자실업급여보험료_숫자}]}\n'
            "2) 급여/프리랜서 지급 요청 캡처인 경우:\n"
            '{"type": "kakao_text", "lines": ["이름 세전/실수령 금액 (프리랜서 여부)"]}'
        )
        img_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
        raw_txt = _call_gemini_contents(
            contents=[img_part, prompt],
            prefer_pro=False,
            explicit_api_key=gemini_api_key,
        )
        if not raw_txt:
            return {
                "type": "error",
                "message": "이미지 자동 판독을 위해 Vertex AI 또는 Gemini API 키 연결을 확인해 주세요.",
            }
        m_json = re.search(r"\{.*\}", raw_txt, re.DOTALL)
        if m_json:
            data = json.loads(m_json.group(0))
            if data.get("type") == "ei_notice":
                records = {}
                for item in data.get("records", []):
                    nm = normalize_korean_name(item.get("name", ""))
                    if nm:
                        records[nm] = {"성명": nm, "고용보험": parse_number(item.get("ei_fee", 0))}
                return {
                    "type": "ei_notice",
                    "notice": {
                        "notice_type": "고용보험",
                        "corp_name": "",
                        "year_month": "",
                        "records": records,
                        "message": f"고용보험 이미지에서 {len(records)}명 보험료 추출 완료",
                    },
                }
            if data.get("type") == "kakao_text":
                return {
                    "type": "kakao_text",
                    "extracted_text": "\n".join(data.get("lines", [])),
                }
    except Exception as e:
        return {"type": "error", "message": f"이미지 판독 중 오류 발생: {e}"}

    return {"type": "error", "message": "이미지에서 유효한 급여 데이터를 찾지 못했습니다."}
