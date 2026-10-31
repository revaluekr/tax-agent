# -*- coding: utf-8 -*-
"""
인건비 자동화 - 다중 포맷 입력 파서 엔진 (parsers.py)
1) 거래처 급여 엑셀 파서 (.xlsx 및 구형 .xls 완벽 지원):
   - 단일/다중 테이블(상단 근로계약 테이블 + 하단 급여계산 테이블 배치형 등) 정밀 인식 및 성명 기준 병합
   - 줄바꿈·괄호·공백 포함 헤더('약정\\n추가근로수당', '(세전) 상여', '결근공제', '주민등록번호') 100% 매칭
   - 하단 시뮬레이션 블록('1. 격주...', '가나다' 등 더미 행) 자동 차단
   - 비정형 양식일 경우 개인정보 마스킹 후 앱 표준 Gemini 엔진(Vertex 크레딧 / 설정 모델 체인)으로 헤더 매핑 폴백
2) PDF 통합 파서:
   - 4대보험 고지내역 PDF 3종 (건강보험·장기요양 / 국민연금 / 고용보험)
   - 사업소득지급대장 PDF 파서 (코드, 성명, 귀속년월, 지급년월, 지급액, 소득세, 지방소득세, 차인지급액 추출)
   - 급여대장 PDF 및 급여명세서 PDF 파서 (기존 급여대장/명세서 PDF 업로드 시 급여대장 편집기에 즉시 복원)
3) 카카오톡 텍스트 및 캡처 이미지 파서:
   - 텍스트 내 주민등록번호(YYMMDD-******* 또는 13자리) 최우선 분리 추출 (생년월일이 급여 금액으로 오인되는 버그 원천 차단)
   - 현재 선택된 탭([급여명세서] vs [사업소득]) 및 키워드 기반 자동 분류 및 세후->세전 1원 단위 역산
4) 국세청 3.3% 사업소득(인적용역) 업종코드 마스터 제공
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
    calculate_employee_payroll_row,
    calculate_freelancer_row,
    is_ceo_position,
    solve_gross_from_net_employee,
    solve_gross_from_net_freelancer,
)


# ─────────────────────────────────────────────────────────────
# 국세청 3.3% 사업소득(인적용역) 표준 업종코드 목록
# ─────────────────────────────────────────────────────────────

FREELANCER_INDUSTRY_CODES: List[Dict[str, str]] = [
    {"code": "940909", "name": "기타자영업 (일반 프리랜서·외주용역 기본)", "category": "기타인적용역"},
    {"code": "940911", "name": "컴퓨터프로그래머 · IT개발 · 웹디자인 · 시스템자문", "category": "전문·기술용역"},
    {"code": "940903", "name": "학원강사 · 교육강사 · 외래강사", "category": "교육·강의"},
    {"code": "940600", "name": "디자이너 (시각·패션·인테리어·편집디자인)", "category": "전문·디자인"},
    {"code": "940500", "name": "모델 (패션·광고·피팅·홍보모델)", "category": "연예·예술"},
    {"code": "940100", "name": "저술가 · 작가 · 번역가 · 카피라이터", "category": "문예·창작"},
    {"code": "940200", "name": "화가 · 조각가 · 미술작가", "category": "문예·창작"},
    {"code": "940301", "name": "작사가 · 작곡가 · 편곡가", "category": "연예·예술"},
    {"code": "940305", "name": "배우 · 성우 · 방송출연자 · 크리에이터", "category": "연예·예술"},
    {"code": "940904", "name": "보험설계사 · 보험모집인", "category": "모집·판매"},
    {"code": "940905", "name": "학습지교사 · 방문교육교사", "category": "교육·강의"},
    {"code": "940906", "name": "다단계판매원 · 방문판매원", "category": "모집·판매"},
    {"code": "940908", "name": "간병인 · 케어복지사", "category": "보건·돌봄"},
    {"code": "940910", "name": "대리운전기사", "category": "운송·배달"},
    {"code": "940913", "name": "행사도우미 · 판촉도우미 · 내레이터모델", "category": "행사·홍보"},
    {"code": "940916", "name": "골프장 캐디", "category": "체육·레저"},
    {"code": "940918", "name": "가사도우미 · 육아도우미", "category": "생활서비스"},
    {"code": "940920", "name": "중고자동차 판매원 · 딜러", "category": "모집·판매"},
    {"code": "940921", "name": "병원의사 (초빙의·대진의)", "category": "보건·의료"},
    {"code": "940926", "name": "퀵서비스 · 배달라이더 · 택배배송원", "category": "운송·배달"},
]


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
    if raw_name is None:
        return ""
    s = str(raw_name).strip()
    if not s or s.lower() in ("nan", "none", "null"):
        return ""
    s = re.sub(r"\([^)]*\)", "", s)
    s = re.sub(r"\s+", "", s)
    return s.strip()


def is_valid_person_name(name: str) -> bool:
    if not name or len(name) < 2 or len(name) > 15:
        return False
    if name in DUMMY_NAMES:
        return False
    for pat in SIMULATION_MARKER_PATTERNS:
        if re.search(pat, name):
            return False
    if re.search(r"[:/%\[\]=+]", name):
        return False
    if re.match(r"^\d", name) or not re.search(r"[가-힣A-Za-z]", name):
        return False
    if any(k in name for k in ("합계", "총계", "소계", "근무시", "급여계산", "근로계약", "단위", "산출식")):
        return False
    return True


def parse_number(val: Any, default: int = 0) -> int:
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
    # △ 또는 ▲ 음수 표기 처리
    if s.startswith(("△", "▲")):
        s = "-" + s[1:].strip()
    m_man = re.match(r"^([+-]?\d+(?:\.\d+)?)\s*만$", s)
    if m_man:
        return int(round(float(m_man.group(1)) * 10000))
    try:
        return int(round(float(s)))
    except ValueError:
        return default


def parse_date_str(val: Any) -> str:
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
    # YYMMDD-******* 형태에서 * 개수가 6~7개인 경우 정규화
    m_mask = re.match(r"^(\d{6})[-~\s]*([1-8*][0-9*]{5,6})$", s)
    if m_mask:
        return f"{m_mask.group(1)}-{m_mask.group(2)[:7].ljust(7, '*')}"
    return s


def extract_birth_6digits(rrn_or_birth: str) -> str:
    if not rrn_or_birth:
        return ""
    digits = re.sub(r"[^0-9]", "", str(rrn_or_birth))
    if len(digits) >= 8 and digits[:2] in ("19", "20"):
        return digits[2:8]
    if len(digits) >= 6:
        return digits[:6]
    return ""


def rrn_to_birth_dot(rrn_or_birth: str) -> str:
    """주민등록번호에서 급여명세서 표기용 생년월일(YYYY.MM.DD) 추출"""
    if not rrn_or_birth:
        return ""
    s = str(rrn_or_birth).strip()
    m_iso = re.match(r"^(\d{4})[-./](\d{2})[-./](\d{2})", s)
    if m_iso:
        return f"{m_iso.group(1)}.{m_iso.group(2)}.{m_iso.group(3)}"
    cleaned = re.sub(r"[^0-9]", "", s)
    if len(cleaned) >= 6:
        yy = int(cleaned[:2])
        mm = int(cleaned[2:4])
        dd = int(cleaned[4:6])
        g = cleaned[6:7] if len(cleaned) >= 7 else ""
        if g in ("1", "2", "5", "6"):
            yyyy = 1900 + yy
        elif g in ("3", "4", "7", "8"):
            yyyy = 2000 + yy
        else:
            yyyy = 2000 + yy if yy <= 30 else 1900 + yy
        if 1 <= mm <= 12 and 1 <= dd <= 31:
            return f"{yyyy:04d}.{mm:02d}.{dd:02d}"
    return ""


def mask_pii_preview_rows(rows: List[List[Any]]) -> List[List[str]]:
    masked: List[List[str]] = []
    for row in rows:
        new_row: List[str] = []
        for cell in row:
            if cell is None:
                new_row.append("")
                continue
            s = str(cell).strip()
            s = re.sub(r"\b\d{6}[-~\s]*[1-8*][0-9*]{5,6}\b", "000000-*******", s)
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
# 1. 거래처 급여 엑셀 파서 (.xlsx / .xls 다중 섹션 + 줄바꿈/병합 헤더 완벽 매칭)
# ─────────────────────────────────────────────────────────────

HEADER_SYNONYMS: Dict[str, List[str]] = {
    "성명": ["성명", "성 명", "사원명", "이름", "근로자명", "직원명"],
    "사원코드": ["사원코드", "사번", "코드", "사원번호"],
    "주민등록번호": ["주민등록번호", "주민번호", "생년월일"],
    "입사일": ["입사일", "입사일자", "고용일", "채용일"],
    "퇴사일": ["퇴사일", "퇴사일자", "퇴직일", "고용종료일", "상실일"],
    "부서": ["부서", "부서명", "소속"],
    "직급": ["직급", "직위", "직책", "업무내용", "직종", "담당업무"],
    "부양가족수": ["부양가족수", "부양가족", "공제대상가족수"],
    "자녀수": ["8~20세자녀수", "자녀수", "20세이하자녀", "다자녀"],
    "기본급": ["기본급", "월기본급", "기본급여", "본봉"],
    "식대": ["식대", "식대(비과세)", "식사대", "중식대", "급식비"],
    "자가운전보조금": ["자가운전보조금", "자가운전", "차량유지비", "차량보조금"],
    "상여": ["상여", "(세전) 상여", "(세전)상여", "세전상여", "상여금", "인센티브", "성과급", "보너스", "명절상여"],
    "약정연장근로수당": ["약정연장근로수당", "약정추가근로수당", "고정연장수당", "약정연장수당", "포괄연장수당", "고정추가근로수당"],
    "약정휴일근로수당": ["약정휴일근로수당", "약정휴일수당", "고정휴일수당"],
    "연장근로수당": ["연장근로수당", "추가근로수당", "연장수당", "초과근무수당", "시간외수당", "OT수당"],
    "휴일근로수당": ["휴일근로수당", "휴일수당", "특근수당"],
    "미사용연차수당": ["미사용연차수당", "연차수당", "월차수당"],
    "결근공제": ["결근공제", "결근차감", "무급공제", "지각조퇴결근공제"],
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
    "국민연금정산": ["국민연금정산", "국민연금소급", "연금정산"],
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
    if not header_text:
        return None
    h_nospace = re.sub(r"\s+", "", header_text)
    h_noparen = re.sub(r"[()\[\]]", "", h_nospace)

    # '약정 월급여' / '약정월급여'는 계약상 합계액이므로 기본급/지급액계와 혼동되지 않도록 제외
    if h_noparen in ("약정월급여", "약정급여", "세전연봉", "연봉", "계약조건"):
        return None

    for canonical, synonyms in HEADER_SYNONYMS.items():
        for syn in synonyms:
            syn_nospace = re.sub(r"\s+", "", syn)
            syn_noparen = re.sub(r"[()\[\]]", "", syn_nospace)
            if h_nospace == syn_nospace or h_noparen == syn_noparen:
                return canonical

    for canonical, synonyms in HEADER_SYNONYMS.items():
        for syn in synonyms:
            syn_nospace = re.sub(r"\s+", "", syn)
            if len(syn_nospace) >= 2 and syn_nospace in h_nospace:
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
                if canonical == "상여" and "연봉" in h_nospace:
                    continue
                return canonical
    return None


def _read_excel_rows_universal(file_bytes: bytes) -> List[List[Any]]:
    """신형 .xlsx(openpyxl) 및 구형 .xls(pandas/xlrd) 모두 2차원 리스트로 안전하게 변환"""
    try:
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
        sheet = wb[wb.sheetnames[0]]
        return [list(r) for r in sheet.iter_rows(values_only=True)]
    except Exception:
        df = pd.read_excel(io.BytesIO(file_bytes), header=None)
        return df.where(pd.notna(df), None).values.tolist()


def _infer_excel_columns_with_ai(
    all_rows: List[List[Any]],
    gemini_api_key: Optional[str] = None,
) -> Optional[Tuple[int, Dict[int, str]]]:
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
    default_workplace: str = "본점",
) -> Dict[str, Any]:
    """
    거래처 급여 엑셀 파싱 (.xlsx 및 .xls 다중 테이블 병합 + 위하고 양식 + 비정형 AI 매핑 폴백)
    """
    all_rows = _read_excel_rows_universal(file_bytes)

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
            # 같은 테이블 안에 이미 매핑된 필드가 있어도 오른쪽 열이 실제 수당 열인 경우(예: 상단 설명열 vs 본 데이터열) 허용하되 첫 매핑 우선
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
            "사업장": default_workplace,
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
# 2. PDF 통합 파서 (4대보험 고지내역 3종 + 사업소득지급대장 PDF + 급여대장/급여명세서 PDF)
# ─────────────────────────────────────────────────────────────

def _extract_pdf_full_text(file_bytes: bytes) -> str:
    """pypdfium2 우선(고속·정확) -> pypdf 폴백으로 PDF 전체 텍스트 추출"""
    try:
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(file_bytes)
        pages = []
        for i in range(len(doc)):
            tp = doc[i].get_textpage()
            pages.append(tp.get_text_range() or "")
            tp.close()
        doc.close()
        txt = "\n".join(pages).strip()
        if len(txt) >= 20:
            return txt
    except Exception:
        pass

    reader = PdfReader(io.BytesIO(file_bytes))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


_LEDGER_PDF_HEADER_MAP: Dict[str, str] = {
    "사번": "사원코드", "사원코드": "사원코드", "코드": "사원코드", "사원번호": "사원코드",
    "부서": "부서", "부서명": "부서",
    "사원명": "성명", "성명": "성명", "근로자명": "성명",
    "직급": "직급", "직위": "직급", "직책": "직급",
    "입사일": "입사일", "입사일자": "입사일",
    "퇴사일": "퇴사일", "퇴사일자": "퇴사일",
    "기본급": "기본급", "기본급여": "기본급",
    "상여": "상여", "상여금": "상여",
    "식대": "식대", "식사대": "식대", "비과세식대": "식대",
    "자가운전보조금": "자가운전보조금", "자가운전": "자가운전보조금", "차량유지비": "자가운전보조금",
    "약정연장근로수당": "약정연장근로수당", "약정연장수당": "약정연장근로수당", "고정연장수당": "약정연장근로수당", "약정추가근로수당": "약정연장근로수당",
    "미사용연차수당": "미사용연차수당", "연차수당": "미사용연차수당", "월차수당": "미사용연차수당",
    "건강보험료정산": "건강보험료정산", "건강정산": "건강보험료정산", "건보정산": "건강보험료정산",
    "장기요양보험료정산": "장기요양보험료정산", "요양정산": "장기요양보험료정산", "장기요양정산": "장기요양보험료정산",
    "약정휴일근로수당": "약정휴일근로수당", "약정휴일수당": "약정휴일근로수당", "고정휴일수당": "약정휴일근로수당",
    "연장근로수당": "연장근로수당", "연장수당": "연장근로수당", "시간외수당": "연장근로수당",
    "휴일근로수당": "휴일근로수당", "휴일수당": "휴일근로수당",
    "결근공제": "결근공제",
    "조정금액": "조정금액", "조정수당": "조정금액", "기타수당": "조정금액",
    "소득세": "소득세", "근로소득세": "소득세",
    "지방소득세": "지방소득세", "주민세": "지방소득세",
    "학자금상환액": "학자금상환액", "학자금상환": "학자금상환액", "학자금": "학자금상환액",
    "국민연금정산": "국민연금정산", "연금정산": "국민연금정산",
    "공제액계": "공제액계", "공제합계": "공제액계", "총공제액": "공제액계",
    "지급액계": "지급액계", "지급합계": "지급액계", "총지급액": "지급액계",
    "국민연금": "국민연금", "연금보험료": "국민연금",
    "건강보험": "건강보험", "건강보험료": "건강보험",
    "장기요양보험료": "장기요양보험료", "장기요양": "장기요양보험료", "장기요양보험": "장기요양보험료",
    "고용보험": "고용보험", "고용보험료": "고용보험",
    "차인지급액": "차인지급액", "실지급액": "차인지급액", "실수령액": "차인지급액",
}


def _extract_page_coord_rows(page: Any, y_tol: float = 4.2) -> List[Tuple[float, List[Tuple[float, str]]]]:
    """pypdf page.extract_text(visitor_text=...)를 이용해 페이지 내 모든 텍스트 조각을 (py, [(px, text), ...]) 행 리스트로 반환"""
    frags: List[Tuple[float, float, str]] = []

    def _visitor(text: str, cm: Any, tm: Any, fontDict: Any, fontSize: float) -> None:
        t = (text or "").strip()
        if not t:
            return
        try:
            px = float(cm[0]) * float(tm[4]) + float(cm[2]) * float(tm[5]) + float(cm[4])
            py = float(cm[1]) * float(tm[4]) + float(cm[3]) * float(tm[5]) + float(cm[5])
        except Exception:
            px = float(tm[4]) if tm and len(tm) > 4 else 0.0
            py = float(tm[5]) if tm and len(tm) > 5 else 0.0
        frags.append((px, py, t))

    page.extract_text(visitor_text=_visitor)
    if not frags:
        return []

    frags.sort(key=lambda it: (-it[1], it[0]))
    rows: List[Tuple[float, List[Tuple[float, str]]]] = []
    for px, py, t in frags:
        if not rows or abs(rows[-1][0] - py) > y_tol:
            rows.append((py, [(px, t)]))
        else:
            rows[-1][1].append((px, t))

    for _, items in rows:
        items.sort(key=lambda x: x[0])
    return rows


def parse_insurance_notice_pdf(file_bytes: bytes, filename: str = "") -> Dict[str, Any]:
    """
    업로드된 PDF를 자동 판별하여 처리:
    1) 건강보험 산출내역서 PDF -> notice_type="건강보험"
    2) 국민연금 결정내역 통지서 PDF -> notice_type="국민연금"
    3) 고용보험 산정보험료 내역 PDF -> notice_type="고용보험"
    4) 사업소득지급대장 PDF -> notice_type="사업소득대장_PDF", freelancers=[...]
    5) 급여대장 / 급여명세서 PDF -> notice_type="급여대장_PDF", employees=[...]
    """
    full_text = _extract_pdf_full_text(file_bytes)

    if "사업소득지급대장" in full_text or ("사업소득" in full_text and "차인지급액" in full_text):
        return _parse_freelancer_ledger_pdf_text(full_text, filename, file_bytes=file_bytes)

    if ("급여대장" in full_text or "급여명세서" in full_text) and ("기본급" in full_text or "지급액계" in full_text or "차인지급액" in full_text or "실지급액" in full_text):
        return _parse_payroll_ledger_or_slip_pdf_text(full_text, filename, file_bytes=file_bytes)

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
        "message": f"PDF 문서 유형을 자동 식별하지 못했습니다 ({filename}).",
    }


def _parse_freelancer_ledger_pdf_coords(file_bytes: bytes, default_ym: str = "") -> List[Dict[str, Any]]:
    """
    좌표 기반(visitor_text) 사업소득지급대장 PDF 파서:
    - 앱이 생성한 사업소득지급대장 PDF(세로 병합 셀 포함) 및 위하고 출력 양식 모두에서
      머리글(코드, 성명, 귀속년월, 지급년월, 지급액, 소득세, 지방소득세, 차인지급액)의 x 좌표를 기준으로
      정확한 열 값을 매칭합니다. '총 계'/'합 계' 행은 제외합니다.
    """
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
    except Exception:
        return []

    freelancers: List[Dict[str, Any]] = []
    for page in reader.pages:
        rows = _extract_page_coord_rows(page, y_tol=3.5)
        if not rows:
            continue

        # 머리글 x 좌표 탐지
        hx_map: Dict[str, float] = {}
        header_bottom_y: Optional[float] = None
        for py, items in rows:
            joined = "".join(re.sub(r"\s+", "", t) for _, t in items)
            if any(k in joined for k in ("귀속년월", "지급년월", "차인지급액", "지방소득세")):
                for px, t in items:
                    tc = re.sub(r"\s+", "", t)
                    for key_cand in ("NO", "코드", "성명", "귀속년월", "지급년월", "지급액", "소득세", "지방소득세", "차인지급액"):
                        if key_cand in tc and key_cand not in hx_map:
                            hx_map[key_cand] = px
                header_bottom_y = py if header_bottom_y is None else min(header_bottom_y, py)

        if header_bottom_y is None or "지급액" not in hx_map:
            continue

        x_code = hx_map.get("코드", 42.0)
        x_name = hx_map.get("성명", 96.0)
        x_ym = hx_map.get("귀속년월", 147.0)
        x_gross = hx_map.get("지급액", 216.0)
        x_tax = min(hx_map.get("소득세", 280.0), hx_map.get("지방소득세", 280.0))
        x_net = hx_map.get("차인지급액", 460.0)

        data_rows = [(py, items) for py, items in rows if py < header_bottom_y - 3.0]
        if not data_rows:
            continue

        # 성명이 등장하는 기준 행(anchor row)을 찾고, 그 위·아래 인접 y 행(±12pt)의 귀속년월·지급년월·소득세·지방소득세를 묶음
        anchors: List[int] = []
        for idx_r, (py, items) in enumerate(data_rows):
            has_total = any(re.sub(r"\s+", "", t) in ("총계", "합계", "소계") for _, t in items)
            if has_total:
                continue
            for px, t in items:
                if (x_name - 25.0) <= px < (x_ym - 10.0):
                    nm_cand = normalize_korean_name(t)
                    if is_valid_person_name(nm_cand):
                        anchors.append(idx_r)
                        break

        for a_pos, r_idx in enumerate(anchors):
            anchor_py, _ = data_rows[r_idx]
            prev_anchor_py = data_rows[anchors[a_pos - 1]][0] if a_pos > 0 else (header_bottom_y - 1.0)
            next_anchor_py = data_rows[anchors[a_pos + 1]][0] if a_pos + 1 < len(anchors) else -9999.0

            upper_y = (anchor_py + prev_anchor_py) / 2.0 if a_pos > 0 else header_bottom_y
            lower_y = (anchor_py + next_anchor_py) / 2.0 if a_pos + 1 < len(anchors) else (anchor_py - 14.0)

            block_rows = [
                (py, items)
                for py, items in data_rows
                if lower_y < py <= upper_y
                and not any(re.sub(r"\s+", "", t) in ("총계", "합계", "소계") for _, t in items)
            ]

            code_str = ""
            name_str = ""
            yms_found: List[Tuple[float, str]] = []
            taxes_found: List[Tuple[float, int]] = []
            gross_val = 0
            net_val = 0

            for py, items in block_rows:
                for px, t in items:
                    tc = t.strip()
                    if (x_code - 15.0) <= px < (x_name - 15.0) and re.match(r"^\d{2,8}$", tc):
                        code_str = tc
                    elif (x_name - 15.0) <= px < (x_ym - 10.0) and is_valid_person_name(normalize_korean_name(tc)):
                        name_str = normalize_korean_name(tc)
                    elif (x_ym - 15.0) <= px < (x_gross - 15.0) and re.match(r"^20\d{2}[./-]\d{1,2}$", tc):
                        yms_found.append((py, tc.replace(".", "-").replace("/", "-")))
                    elif (x_gross - 15.0) <= px < (x_tax - 12.0) and re.match(r"^[\d,]+$", tc):
                        gross_val = parse_number(tc)
                    elif (x_tax - 12.0) <= px < (x_net - 30.0) and re.match(r"^[\d,]+$", tc):
                        taxes_found.append((py, parse_number(tc)))
                    elif px >= (x_net - 30.0) and re.match(r"^[\d,]+$", tc):
                        net_val = parse_number(tc)

            if not name_str or gross_val <= 0:
                continue

            yms_found.sort(key=lambda x: -x[0])
            ym_attr = yms_found[0][1] if yms_found else default_ym
            ym_pay = yms_found[1][1] if len(yms_found) >= 2 else ym_attr

            taxes_found.sort(key=lambda x: -x[0])
            itax_val = taxes_found[0][1] if taxes_found else 0
            ltax_val = taxes_found[1][1] if len(taxes_found) >= 2 else 0

            freelancers.append({
                "코드": code_str or f"{len(freelancers) + 1:04d}",
                "성명": name_str,
                "주민등록번호": "",
                "소득구분": "940909",
                "귀속년월": ym_attr,
                "지급년월일": f"{ym_pay}-25" if len(ym_pay) == 7 else ym_pay,
                "입력기준": "세전",
                "지급총액": gross_val,
                "세율": 3,
                "소득세": itax_val,
                "지방소득세": ltax_val,
                "공제액계": itax_val + ltax_val,
                "차인지급액": net_val if net_val > 0 else (gross_val - itax_val - ltax_val),
            })

    return freelancers


def _parse_freelancer_ledger_pdf_text(
    text: str,
    filename: str = "",
    file_bytes: Optional[bytes] = None,
) -> Dict[str, Any]:
    """
    사업소득지급대장(합계) PDF 파싱:
    1) 위하고 출력 형식 ('1 000031 정다은 2026.08 2,056,670 61,700 / 2026.09 6,170 1,988,800')
    2) 앱 생성 형식 (`export_freelancer_ledger_pdf` — '1 0001 강사001 / 2026.10 / 1,000,000 / 30,000 / 967,000 / 2026.10 3,000')
    두 가지 형식을 좌표 기반(file_bytes) 및 정규식 기반(text)으로 모두 지원하며 '총 계' 행은 제외합니다.
    """
    corp_name = ""
    m_corp = re.search(r"회사명\s*[:：]\s*([^\n\r]+)", text)
    if m_corp:
        corp_name = m_corp.group(1).strip()

    year_month = ""
    m_ym = re.search(r"\((\d{4})년\s*(\d{1,2})월\)", text)
    if m_ym:
        year_month = f"{int(m_ym.group(1)):04d}-{int(m_ym.group(2)):02d}"

    freelancers: List[Dict[str, Any]] = []
    if file_bytes:
        freelancers = _parse_freelancer_ledger_pdf_coords(file_bytes, default_ym=year_month)

    if not freelancers:
        # 정규식 폴백:
        # - 분기 A (앱 생성 형식): 귀속년월 뒤 숫자 3개(지급액, 소득세, 차인지급액) + 지급년월 + 숫자 1개(지방소득세)
        # - 분기 B (위하고 출력 형식): 귀속년월 뒤 숫자 2개(지급액, 소득세) + 지급년월 + 숫자 2개(지방소득세, 차인지급액)
        pattern = re.compile(
            r"(?:^|\s)(\d{1,3})\s+(\d{3,8})\s+([가-힣A-Za-z][가-힣A-Za-z0-9_]{1,12})\s+"
            r"(20\d{2}[./-]\d{1,2})\s+([\d,]+)\s+([\d,]+)\s+"
            r"(?:([\d,]+)\s+(20\d{2}[./-]\d{1,2})\s+([\d,]+)|(20\d{2}[./-]\d{1,2})\s+([\d,]+)\s+([\d,]+))",
            re.MULTILINE,
        )
        for m in pattern.finditer(text):
            code_str = m.group(2).strip()
            name_str = normalize_korean_name(m.group(3))
            if not is_valid_person_name(name_str):
                continue
            ym_attr = m.group(4).replace(".", "-").replace("/", "-")
            gross = parse_number(m.group(5))
            itax = parse_number(m.group(6))
            if m.group(7) is not None:
                # 분기 A: 앱 생성 형식 (차인지급액 -> 지급년월 -> 지방소득세)
                net = parse_number(m.group(7))
                ym_pay = m.group(8).replace(".", "-").replace("/", "-")
                ltax = parse_number(m.group(9))
            else:
                # 분기 B: 위하고 출력 형식 (지급년월 -> 지방소득세 -> 차인지급액)
                ym_pay = m.group(10).replace(".", "-").replace("/", "-")
                ltax = parse_number(m.group(11))
                net = parse_number(m.group(12))

            freelancers.append({
                "코드": code_str,
                "성명": name_str,
                "주민등록번호": "",
                "소득구분": "940909",
                "귀속년월": ym_attr,
                "지급년월일": f"{ym_pay}-25" if len(ym_pay) == 7 else ym_pay,
                "입력기준": "세전",
                "지급총액": gross,
                "세율": 3,
                "소득세": itax,
                "지방소득세": ltax,
                "공제액계": itax + ltax,
                "차인지급액": net,
            })

    return {
        "notice_type": "사업소득대장_PDF",
        "corp_name": corp_name,
        "year_month": year_month,
        "freelancers": freelancers,
        "records": {},
        "message": f"사업소득지급대장 PDF에서 소득자 {len(freelancers)}명 내역을 추출했습니다.",
    }


def _build_employee_from_ledger_record(
    rec: Dict[str, Any],
    idx_fallback: int,
    effective_table: str = "2026.03",
) -> Optional[Dict[str, Any]]:
    """급여대장 PDF에서 추출한 원시 필드 dict로 calculate_employee_payroll_row를 실행하고 4대보험·세액 원단위를 보존"""
    raw_name = str(rec.get("성명", "")).strip()
    if not raw_name or raw_name in ("합 계", "합계", "총 계", "총계") or re.match(r"^\(\d+명\)$", raw_name):
        return None
    norm_name = normalize_korean_name(raw_name)
    if not is_valid_person_name(norm_name):
        return None

    nps_v = parse_number(rec.get("국민연금", 0))
    nhis_v = parse_number(rec.get("건강보험", 0))
    ltc_v = parse_number(rec.get("장기요양보험료", 0))
    ei_v = parse_number(rec.get("고용보험", 0))
    nhis_settle = parse_number(rec.get("건강보험료정산", 0))
    ltc_settle = parse_number(rec.get("장기요양보험료정산", 0))
    nps_settle = parse_number(rec.get("국민연금정산", 0))

    notice_ins = {
        "국민연금": nps_v,
        "건강보험": nhis_v,
        "장기요양보험료": ltc_v,
        "고용보험": ei_v,
        "건강보험료정산": nhis_settle,
        "장기요양보험료정산": ltc_settle,
        "국민연금정산": nps_settle,
    }

    pos_str = str(rec.get("직급", "")).strip()
    row_calc = calculate_employee_payroll_row(
        base_pay=parse_number(rec.get("기본급", 0)),
        bonus=parse_number(rec.get("상여", 0)),
        meal_allowance=parse_number(rec.get("식대", 0)),
        car_allowance=parse_number(rec.get("자가운전보조금", 0)),
        fixed_overtime_pay=parse_number(rec.get("약정연장근로수당", 0)),
        fixed_holiday_pay=parse_number(rec.get("약정휴일근로수당", 0)),
        overtime_pay=parse_number(rec.get("연장근로수당", 0)),
        holiday_pay=parse_number(rec.get("휴일근로수당", 0)),
        unused_leave_pay=parse_number(rec.get("미사용연차수당", 0)),
        absence_deduction=parse_number(rec.get("결근공제", 0)),
        adjustment_pay=parse_number(rec.get("조정금액", 0)),
        notice_insurance=notice_ins,
        student_loan_repayment=parse_number(rec.get("학자금상환액", 0)),
        effective_table=effective_table,
        is_ceo=is_ceo_position(pos_str),
    )

    if "공제액계" in rec or "차인지급액" in rec:
        pdf_itax = parse_number(rec.get("소득세", row_calc["소득세"]))
        pdf_ltax = parse_number(rec.get("지방소득세", row_calc["지방소득세"]))
        pdf_ded = parse_number(rec.get("공제액계", row_calc["공제액계"]))
        pdf_net = parse_number(rec.get("차인지급액", row_calc["차인지급액"]))
        if pdf_ded != row_calc["공제액계"] or pdf_net != row_calc["차인지급액"]:
            row_calc["소득세"] = pdf_itax
            row_calc["지방소득세"] = pdf_ltax
            row_calc["공제액계"] = pdf_ded
            row_calc["차인지급액"] = pdf_net

    return {
        "사업장": "본점",
        "사원코드": str(rec.get("사원코드") or f"{idx_fallback:03d}"),
        "성명": norm_name,
        "주민등록번호": "",
        "입사일": str(rec.get("입사일", "")).replace(".", "-"),
        "퇴사일": str(rec.get("퇴사일", "")).replace(".", "-"),
        "부서": str(rec.get("부서", "")),
        "직급": pos_str,
        "부양가족수": 1,
        "자녀수": 0,
        "입력기준": "세전",
        "목표실수령액": 0,
        **row_calc,
    }


def _parse_payroll_ledger_pdf_coords(file_bytes: bytes, effective_table: str = "2026.03") -> List[Dict[str, Any]]:
    """
    pypdf visitor_text 좌표 기반 급여대장 PDF(다중 인원·다중 페이지) 파서:
    - 머리글 3행(사번·기본급... / 사원명·소득세·공제액계... / 입사일·지급액계·차인지급액...)의 x 위치를 기준으로
      0원 빈칸으로 인해 생략된 열이 있더라도 정확한 항목에 숫자를 배정합니다.
    - 합계 행('합 계', '(N명)')은 제외합니다.
    """
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
    except Exception:
        return []

    all_body_rows: List[Tuple[float, List[Tuple[float, str]]]] = []
    global_header_bounds: Optional[List[List[Tuple[float, float, str]]]] = None

    for page in reader.pages:
        rows = _extract_page_coord_rows(page, y_tol=4.2)
        if not rows:
            continue

        h_idx: Optional[int] = None
        for r_i in range(len(rows) - 2):
            r0_labels = {_LEDGER_PDF_HEADER_MAP.get(re.sub(r"\s+", "", t)) for _, t in rows[r_i][1]}
            r1_labels = {_LEDGER_PDF_HEADER_MAP.get(re.sub(r"\s+", "", t)) for _, t in rows[r_i + 1][1]}
            r2_labels = {_LEDGER_PDF_HEADER_MAP.get(re.sub(r"\s+", "", t)) for _, t in rows[r_i + 2][1]}
            if ("사원코드" in r0_labels and "기본급" in r0_labels) and ("성명" in r1_labels) and ("지급액계" in r2_labels):
                h_idx = r_i
                break

        if h_idx is None:
            continue

        header_bounds: List[List[Tuple[float, float, str]]] = []
        for offset in range(3):
            h_items: List[Tuple[float, str]] = []
            for px, t in rows[h_idx + offset][1]:
                canon = _LEDGER_PDF_HEADER_MAP.get(re.sub(r"\s+", "", t))
                if canon:
                    h_items.append((px, canon))
            h_items.sort(key=lambda x: x[0])
            bounds: List[Tuple[float, float, str]] = []
            for idx_c, (hx, canon) in enumerate(h_items):
                left_b = 0.0 if idx_c == 0 else (hx - 16.0)
                right_b = (h_items[idx_c + 1][0] - 16.0) if idx_c + 1 < len(h_items) else 9999.0
                bounds.append((left_b, right_b, canon))
            header_bounds.append(bounds)

        if global_header_bounds is None:
            global_header_bounds = header_bounds

        all_body_rows.extend(rows[h_idx + 3:])

    if not global_header_bounds or not all_body_rows:
        return []

    employees: List[Dict[str, Any]] = []
    b_i = 0
    while b_i + 2 < len(all_body_rows):
        rec: Dict[str, Any] = {}
        skip_block = False
        for r_mod in range(3):
            _, r_items = all_body_rows[b_i + r_mod]
            bounds = global_header_bounds[r_mod]
            for px, tok in r_items:
                tok_clean = tok.strip()
                if tok_clean in ("합 계", "합계", "총 계", "총계") or re.match(r"^\(\d+명\)$", tok_clean):
                    skip_block = True
                    break
                for left_b, right_b, field_nm in bounds:
                    if left_b <= px < right_b:
                        rec[field_nm] = tok_clean
                        break
            if skip_block:
                break
        b_i += 3
        if skip_block:
            continue

        emp_obj = _build_employee_from_ledger_record(rec, len(employees) + 1, effective_table=effective_table)
        if emp_obj:
            employees.append(emp_obj)

    return employees


def _parse_payroll_ledger_plain_text_fallback(text: str, effective_table: str = "2026.03") -> List[Dict[str, Any]]:
    """file_bytes 없이 텍스트만 전달된 경우(또는 위하고 텍스트 추출본)의 3행 블록 급여대장 파서"""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    start_idx = 0
    for idx, ln in enumerate(lines):
        if "지급액계" in ln and ("국민연금" in ln or "차인지급액" in ln):
            start_idx = idx + 1

    body = lines[start_idx:]
    employees: List[Dict[str, Any]] = []
    i = 0
    while i + 2 < len(body):
        ln0, ln1, ln2 = body[i], body[i + 1], body[i + 2]
        if any(
            k in ln0 or k in ln1
            for k in ("합 계", "합계", "총 계", "총계", "사번", "사원명", "입사일")
        ) or re.search(r"\(\d+명\)", ln0 + " " + ln1):
            i += 1
            continue

        m0 = re.match(r"^(\d{2,6})\s+(?:([가-힣A-Za-z]+)\s+)?(.+)$", ln0)
        m1 = re.match(r"^([가-힣A-Za-z][가-힣A-Za-z0-9_]{1,12})\s+(?:([가-힣A-Za-z]+)\s+)?(.+)$", ln1)
        if not m0 or not m1:
            i += 1
            continue

        code_str = m0.group(1)
        dept_str = m0.group(2) or ""
        nums0 = [parse_number(x) for x in re.findall(r"[+-]?[\d,]+", m0.group(3))]

        name_str = m1.group(1)
        pos_str = m1.group(2) or ""
        nums1 = [parse_number(x) for x in re.findall(r"[+-]?[\d,]+", m1.group(3))]

        dates2 = re.findall(r"20\d{2}[.-]\d{2}[.-]\d{2}", ln2)
        ln2_wo_dates = re.sub(r"20\d{2}[.-]\d{2}[.-]\d{2}", " ", ln2)
        nums2 = [parse_number(x) for x in re.findall(r"[+-]?[\d,]+", ln2_wo_dates)]

        if not nums0 or not nums1 or len(nums2) < 2:
            i += 1
            continue

        gross_val = nums2[0]
        net_val = nums2[-1]
        ins_vals = nums2[1:-1]
        nps_v = ins_vals[0] if len(ins_vals) >= 1 else 0
        nhis_v = ins_vals[1] if len(ins_vals) >= 2 else 0
        ltc_v = ins_vals[2] if len(ins_vals) >= 3 else 0
        ei_v = ins_vals[3] if len(ins_vals) >= 4 else 0

        ded_val = nums1[-1]
        itax_v, ltax_v = 0, 0
        allow_row1 = nums1[:-1]
        if len(allow_row1) >= 2:
            itax_v = allow_row1[-2]
            ltax_v = allow_row1[-1]
            allow_row1 = allow_row1[:-2]
        elif len(allow_row1) == 1:
            itax_v = allow_row1[0]
            allow_row1 = []

        base_v = nums0[0]
        meal_v = 0
        bonus_v = 0
        for extra_v in nums0[1:]:
            if extra_v == 200_000 and meal_v == 0:
                meal_v = extra_v
            else:
                bonus_v += extra_v

        ot_v = sum(allow_row1)
        rec = {
            "사원코드": code_str,
            "성명": name_str,
            "부서": dept_str,
            "직급": pos_str,
            "입사일": dates2[0] if dates2 else "",
            "퇴사일": dates2[1] if len(dates2) >= 2 else "",
            "기본급": base_v,
            "상여": bonus_v,
            "식대": meal_v,
            "연장근로수당": ot_v,
            "지급액계": gross_val,
            "국민연금": nps_v,
            "건강보험": nhis_v,
            "장기요양보험료": ltc_v,
            "고용보험": ei_v,
            "소득세": itax_v,
            "지방소득세": ltax_v,
            "공제액계": ded_val,
            "차인지급액": net_val,
        }
        emp_obj = _build_employee_from_ledger_record(rec, len(employees) + 1, effective_table=effective_table)
        if emp_obj:
            employees.append(emp_obj)
        i += 3

    return employees


def _parse_single_payslip_page_text(
    page_txt: str,
    idx_fallback: int = 1,
    effective_table: str = "2026.03",
) -> Optional[Dict[str, Any]]:
    """
    단일 페이지 급여명세서 텍스트 파서 (6종 양식: 근로기준1~5 및 '구' 양식 모두 지원):
    - '사 원 명: 직원001' ('구' 양식 띄어쓰기), '사원명 : 직원001' (근로기준1), '성명 직원001' (근로기준2~5) 모두 인식
    - 하단 '계산방법' 표 이전의 본문 세부내역 영역만 분리하여 중복 매칭을 방지하고 모든 지급·공제 항목을 추출합니다.
    """
    if "급여명세서" not in page_txt:
        return None

    m_name = re.search(
        r"(?:사\s*원\s*명|성\s*명)\s*[:：]?\s*([가-힣A-Za-z][가-힣A-Za-z0-9_]{1,12})",
        page_txt,
    )
    if not m_name:
        return None
    nm = normalize_korean_name(m_name.group(1))
    if not is_valid_person_name(nm):
        return None

    code = f"{idx_fallback:03d}"
    m_code1 = re.search(r"사\s*원\s*코\s*드\s*[:：]?\s*([A-Za-z0-9_-]+)", page_txt)
    m_code2 = re.search(r"생년월일\s*\(\s*사\s*번\s*\)[^\n]*?\(\s*([A-Za-z0-9_-]+)\s*\)", page_txt)
    m_code3 = re.search(r"(?<!\()\b사\s*번\s*[:：]?\s*([A-Za-z0-9_-]+)", page_txt)
    if m_code1:
        code = m_code1.group(1).strip()
    elif m_code2:
        code = m_code2.group(1).strip()
    elif m_code3:
        code = m_code3.group(1).strip()

    dept = ""
    m_dept = re.search(r"부\s*서\s*[:：]?\s*([가-힣A-Za-z0-9_]+)", page_txt)
    if m_dept and m_dept.group(1) not in ("직급", "직", "호봉"):
        dept = m_dept.group(1).strip()

    pos = ""
    m_pos = re.search(r"직\s*급\s*[:：]?\s*([가-힣A-Za-z0-9_]+)", page_txt)
    if m_pos and m_pos.group(1) not in ("호봉", "호", "연장근로시간", "세부내역"):
        pos = m_pos.group(1).strip()

    hire_dt = ""
    m_hire = re.search(r"입\s*사\s*일\s*[:：]?\s*(20\d{2}[./-]\d{2}[./-]\d{2})", page_txt)
    if m_hire:
        hire_dt = m_hire.group(1).replace(".", "-").replace("/", "-")

    # 하단 '계산방법' 표에 있는 식대·연장수당과 중복 매칭되지 않도록 본문 영역만 분리
    main_sec = page_txt.split("계산방법")[0]

    def _find_item_amt(label: str) -> int:
        spaced_pat = r"\s*".join(re.escape(ch) for ch in label)
        m_it = re.search(rf"(?:^|\s){spaced_pat}(?!\s*정산)\s+([+-]?[\d,]+)", main_sec)
        return parse_number(m_it.group(1)) if m_it else 0

    rec: Dict[str, Any] = {
        "사원코드": code,
        "성명": nm,
        "부서": dept,
        "직급": pos,
        "입사일": hire_dt,
        "기본급": _find_item_amt("기본급"),
        "상여": _find_item_amt("상여"),
        "식대": _find_item_amt("식대"),
        "자가운전보조금": _find_item_amt("자가운전보조금"),
        "약정연장근로수당": _find_item_amt("약정연장근로수당"),
        "약정휴일근로수당": _find_item_amt("약정휴일근로수당"),
        "연장근로수당": _find_item_amt("연장근로수당"),
        "휴일근로수당": _find_item_amt("휴일근로수당"),
        "미사용연차수당": _find_item_amt("미사용연차수당"),
        "결근공제": _find_item_amt("결근공제"),
        "조정금액": _find_item_amt("조정금액"),
        "국민연금": _find_item_amt("국민연금"),
        "건강보험": _find_item_amt("건강보험"),
        "장기요양보험료": _find_item_amt("장기요양보험료"),
        "고용보험": _find_item_amt("고용보험"),
        "건강보험료정산": _find_item_amt("건강보험료정산"),
        "장기요양보험료정산": _find_item_amt("장기요양보험료정산"),
        "국민연금정산": _find_item_amt("국민연금정산"),
        "학자금상환액": _find_item_amt("학자금상환액"),
        "소득세": _find_item_amt("소득세"),
        "지방소득세": _find_item_amt("지방소득세"),
    }

    gross_tot = _find_item_amt("지급액계")
    ded_tot = _find_item_amt("공제액계")
    net_tot = _find_item_amt("차인지급액") or _find_item_amt("실지급액")
    if gross_tot > 0:
        rec["지급액계"] = gross_tot
    if ded_tot > 0 or "공 제 액 계" in main_sec or "공제액계" in main_sec:
        rec["공제액계"] = ded_tot
    if net_tot > 0:
        rec["차인지급액"] = net_tot

    return _build_employee_from_ledger_record(rec, idx_fallback, effective_table=effective_table)


def _parse_payroll_ledger_or_slip_pdf_text(
    text: str,
    filename: str = "",
    effective_table: str = "2026.03",
    file_bytes: Optional[bytes] = None,
) -> Dict[str, Any]:
    """
    급여대장 PDF(다중 인원·다중 페이지) 또는 급여명세서 PDF(6종 양식 단일/다중 페이지)를 업로드했을 때
    사원별 급여 내역을 추출하여 급여대장 편집기에 복원합니다.
    """
    corp_name = ""
    m_corp = re.search(r"회사명\s*[:：]\s*([^\s\n\r]+)", text)
    if m_corp and m_corp.group(1).strip() not in ("지급일", "정렬"):
        corp_name = m_corp.group(1).strip()
    else:
        m_corp_gu = re.search(r"귀하의\s*노고에\s*감사드립니다\.?\s*([^\n\r]+)", text)
        if m_corp_gu:
            corp_name = m_corp_gu.group(1).strip()

    year_month = ""
    m_ym = re.search(r"(\d{4})년\s*(\d{1,2})월분", text)
    if m_ym:
        year_month = f"{int(m_ym.group(1)):04d}-{int(m_ym.group(2)):02d}"

    employees: List[Dict[str, Any]] = []

    # 1) 급여대장 PDF (여러 명) 처리
    if "급여대장" in text and "급여명세서" not in text:
        if file_bytes:
            employees = _parse_payroll_ledger_pdf_coords(file_bytes, effective_table=effective_table)
        if not employees:
            employees = _parse_payroll_ledger_plain_text_fallback(text, effective_table=effective_table)

    # 2) 급여명세서 PDF (근로기준1~5 및 '구' 양식, 단일 또는 다중 페이지) 처리
    elif "급여명세서" in text:
        page_texts: List[str] = []
        if file_bytes:
            try:
                import pypdfium2 as pdfium
                doc = pdfium.PdfDocument(file_bytes)
                for i in range(len(doc)):
                    tp = doc[i].get_textpage()
                    page_texts.append(tp.get_text_range() or "")
                    tp.close()
                doc.close()
            except Exception:
                try:
                    reader = PdfReader(io.BytesIO(file_bytes))
                    page_texts = [(p.extract_text() or "") for p in reader.pages]
                except Exception:
                    page_texts = []

        if not page_texts:
            parts = re.split(r"(?=\d{4}년\s*\d{1,2}월분\s*급여명세서)", text)
            page_texts = [p for p in parts if "급여명세서" in p] or [text]

        for idx_p, p_txt in enumerate(page_texts, start=1):
            emp_obj = _parse_single_payslip_page_text(p_txt, idx_fallback=idx_p, effective_table=effective_table)
            if emp_obj:
                employees.append(emp_obj)

    return {
        "notice_type": "급여대장_PDF",
        "corp_name": corp_name,
        "year_month": year_month,
        "employees": employees,
        "records": {},
        "message": f"급여 PDF에서 근로자 {len(employees)}명 내역을 추출했습니다.",
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

        ceo_flag = is_ceo_position(emp.get("직급", ""))
        if emp.get("입력기준") == "세후역산" and emp.get("목표실수령액", 0) > 0:
            solved = solve_gross_from_net_employee(
                target_net_pay=emp["목표실수령액"],
                non_taxable_pay=emp.get("식대", 0) + emp.get("자가운전보조금", 0),
                dependents=emp.get("부양가족수", 1),
                children_8_20=emp.get("자녀수", 0),
                notice_insurance=notice_ins,
                student_loan_repayment=emp.get("학자금상환액", 0),
                effective_table=effective_table,
                is_ceo=ceo_flag,
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
            is_ceo=ceo_flag,
        )
        emp.update(recalc)
        updated_employees.append(emp)

    return updated_employees, logs


# ─────────────────────────────────────────────────────────────
# 3. 사업소득(3.3%) 엑셀 파서 (.xlsx / .xls 모두 호환)
# ─────────────────────────────────────────────────────────────

def parse_freelancer_excel(
    file_bytes: bytes,
    filename: str = "",
    default_year_month: str = "",
    default_pay_date: str = "",
) -> List[Dict[str, Any]]:
    """사업소득대장 또는 위하고 사업소득 업로드 엑셀 파싱"""
    rows = _read_excel_rows_universal(file_bytes)

    header_idx = -1
    col_map: Dict[int, str] = {}
    for r_i, row in enumerate(rows):
        temp_map: Dict[int, str] = {}
        next_row = rows[r_i + 1] if r_i + 1 < len(rows) else []
        for c_i, val in enumerate(row):
            txt = re.sub(r"\s+", "", _clean_header_cell(val))
            sub_txt = re.sub(r"\s+", "", _clean_header_cell(next_row[c_i])) if c_i < len(next_row) else ""
            for cand in (txt, sub_txt):
                if not cand:
                    continue
                if cand in ("소득자명", "성명", "이름", "근로자명"):
                    temp_map.setdefault(c_i, "성명")
                elif cand in ("주민등록번호", "주민번호", "생년월일"):
                    temp_map.setdefault(c_i, "주민등록번호")
                elif cand in ("지급총액", "지급액", "세전금액", "세전", "지급액계"):
                    temp_map.setdefault(c_i, "지급총액")
                elif cand in ("차인지급액", "실지급액", "세후금액"):
                    temp_map.setdefault(c_i, "차인지급액")
                elif cand in ("귀속년월", "귀속연월"):
                    temp_map.setdefault(c_i, "귀속년월")
                elif cand in ("지급년월일", "지급연월", "지급년월", "지급일자"):
                    temp_map.setdefault(c_i, "지급년월일")
                elif cand in ("소득구분", "업종코드", "직종"):
                    temp_map.setdefault(c_i, "소득구분")
                elif cand in ("코드", "사번", "사원코드"):
                    temp_map.setdefault(c_i, "코드")
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
            if c_i < len(row) and row[c_i] is not None and str(row[c_i]).strip() != "":
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

        raw_ind = str(rec.get("소득구분") or "940909").strip()
        m_ind = re.search(r"\b(\d{6})\b", raw_ind)
        ind_code = m_ind.group(1) if m_ind else "940909"

        freelancers.append({
            "코드": code_val,
            "성명": norm_name,
            "주민등록번호": normalize_rrn(rec.get("주민등록번호", "")),
            "소득구분": ind_code,
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
# 4. 카카오톡 텍스트 & 이미지 캡처 파서 (주민번호 최우선 분리 + 현재 탭 연동)
# ─────────────────────────────────────────────────────────────

def parse_kakao_text_instructions(
    raw_text: str,
    existing_employees: Optional[List[Dict[str, Any]]] = None,
    existing_freelancers: Optional[List[Dict[str, Any]]] = None,
    default_year_month: str = "",
    default_pay_date: str = "",
    effective_table: str = "2026.03",
    default_is_freelancer: bool = False,
    default_workplace: str = "본점",
) -> Dict[str, Any]:
    """
    사장님 카톡 텍스트를 파싱하여 4대보험 근로자(세전/세후역산)와 3.3% 사업소득자로 자동 분류:
    - '김미모, 830411-*******, 세후 300만원' 입력 시 주민등록번호('830411-*******')를 먼저 분리 추출한 뒤
      남은 텍스트에서 금액('300만원')을 파싱하므로 생년월일이 급여액으로 오인되지 않습니다.
    - 한 줄에 한 명씩('성명, 주민번호, 세전/세후 금액') 적은 경우와 쉼표로 여러 명을 적은 경우를 모두 자동 판별합니다.
    """
    if not raw_text or not raw_text.strip():
        return {"employees": [], "freelancers": [], "messages": []}

    existing_emp_map = {
        normalize_korean_name(e.get("성명", "")): e for e in (existing_employees or [])
    }
    existing_free_map = {
        normalize_korean_name(f.get("성명", "")): f for f in (existing_freelancers or [])
    }

    text_norm = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", raw_text)  # "3,000,000원"처럼 뒤에 한글이 붙어도 쉼표 제거

    # 줄바꿈이 있으면 줄 단위로 먼저 나누고, 한 줄 안에 쉼표로 구분된 항목이 '이름+주민번호+금액' 단일 인원인지 복수 인원인지 판별
    raw_lines = [ln.strip() for ln in re.split(r"[\n;/]+", text_norm) if ln.strip()]
    segments: List[str] = []
    for ln in raw_lines:
        # 쉼표로 나눴을 때 각 조각마다 한글 이름이 있으면 복수 인원, 아니면 단일 인원의 속성(이름, 주민번호, 세후 300만원)
        comma_parts = [p.strip() for p in re.split(r"(?<!\d),(?!\d)", ln) if p.strip()]
        if len(comma_parts) > 1:
            parts_with_names = 0
            for cp in comma_parts:
                cands = [
                    w for w in re.findall(r"[가-힣]{2,4}", cp)
                    if w not in (
                        "실수령", "실수령액", "세후금액", "세전금액", "세전으로", "세후로", "세후", "세전",
                        "프리랜서", "사업소득", "아르바이트", "알바비", "식대포함", "입금요청",
                        "입금해", "주세요", "만원씩", "만원", "기본급", "상여금", "연장수당",
                    )
                ]
                if cands:
                    parts_with_names += 1
            if parts_with_names >= 2:
                segments.extend(comma_parts)
            else:
                segments.append(ln)
        else:
            segments.append(ln)

    parsed_employees: List[Dict[str, Any]] = []
    parsed_freelancers: List[Dict[str, Any]] = []
    messages: List[str] = []

    for seg in segments:
        # 1단계: 주민등록번호(예: 830411-******* 또는 830411-1234567 또는 13자리 숫자) 최우선 추출 및 텍스트에서 제거!
        extracted_rrn = ""
        m_rrn = re.search(r"(\d{6}\s*-\s*[1-8*][0-9*]{5,6}|\b\d{13}\b)", seg)
        if m_rrn:
            extracted_rrn = normalize_rrn(m_rrn.group(1))
            seg_wo_rrn = seg[:m_rrn.start()] + " " + seg[m_rrn.end():]
        else:
            seg_wo_rrn = seg

        # 2단계: 이름 추출 (2~4자 한글)
        candidates = re.findall(r"[가-힣]{2,4}", seg_wo_rrn)
        person_name = ""
        for cand in candidates:
            if cand not in (
                "실수령", "실수령액", "세후금액", "세전금액", "세전으로", "세후로", "세후", "세전",
                "프리랜서", "사업소득", "아르바이트", "알바비", "식대포함", "입금요청",
                "입금해", "주세요", "만원씩", "만원", "기본급", "상여금", "연장수당",
            ):
                person_name = cand
                break
        if not person_name:
            continue

        has_emp_kw = any(k in seg_wo_rrn for k in ("4대보험", "정규직", "식대", "기본급"))
        has_free_kw = any(k in seg_wo_rrn for k in ("3.3", "프리랜서", "사업소득", "외주", "용역"))

        is_freelancer = (
            has_free_kw
            or (default_is_freelancer and not has_emp_kw)
            or (person_name in existing_free_map and person_name not in existing_emp_map)
        )
        is_net = any(k in seg_wo_rrn for k in ("실수령", "세후", "실지급", "맞춰", "입금기준"))

        # 3단계: 식대 추출
        meal_val = 200_000
        m_meal = re.search(r"식대\s*(\d+(?:\.\d+)?)\s*(만\s*원|만|원)?", seg_wo_rrn)
        if m_meal:
            raw_m = float(m_meal.group(1))
            unit_m = m_meal.group(2) or ""
            meal_val = int(raw_m * 10000) if ("만" in unit_m or raw_m < 100) else int(raw_m)
            seg_wo_meal = seg_wo_rrn[:m_meal.start()] + " " + seg_wo_rrn[m_meal.end():]
        else:
            seg_wo_meal = seg_wo_rrn

        # 4단계: 3.3% 문구 제거 후 급여 금액 추출
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
                "주민등록번호": extracted_rrn or base_f.get("주민등록번호", ""),
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
                "사업장": base_e.get("사업장") or default_workplace,
                "사원코드": base_e.get("사원코드") or f"{len(parsed_employees) + 1:03d}",
                "성명": person_name,
                "주민등록번호": extracted_rrn or base_e.get("주민등록번호", ""),
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
    try:
        from google.genai import types

        prompt = (
            "이 이미지는 세무사 사무실에 전달된 (1) 고용보험 산정보험료 근로자내역 표 이미지이거나, "
            "(2) 거래처의 급여/프리랜서 지급 요청 캡처(카카오톡 등)입니다.\n"
            "반드시 아래 JSON 형식으로만 응답하세요:\n"
            "1) 고용보험 근로자내역 표인 경우:\n"
            '{"type": "ei_notice", "records": [{"name": "근로자명", "ei_fee": 근로자실업급여보험료_숫자}]}\n'
            "2) 급여/프리랜서 지급 요청 캡처인 경우:\n"
            '{"type": "kakao_text", "lines": ["이름, 주민등록번호(있는경우), 세전/실수령 금액 (프리랜서 여부)"]}'
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
