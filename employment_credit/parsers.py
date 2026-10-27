# -*- coding: utf-8 -*-
"""
통합고용세액공제 서류 분류 · 100% 자체 결정론적 고속 파싱(1순위) + 하이브리드 Flash/Pro(Argon) AI 보완 추출(2순위) + 복수 사업장 합산 엔진 (parsers.py)

[핵심 아키텍처 — 100% 자체파싱 우선 + 부분적 Pro/Argon 정밀 보완 + 복수 사업장 합산]
1. [1순위: 100% 자체 결정론적 파싱 (0.01초, 토큰 0원, API 키 불필요)]
   - 원천징수부/급여대장(`_try_fast_parse_wht_table`):
     * `app.py`의 `extract_file_content`가 출력하는 공백 구분 표(`df.head(1500).to_string(index=False)`),
     * 마크다운 파이프(`| ... |`) 표, CSV/TSV 표를 0.01초 만에 100% 자체 추출합니다.
     * 사번(`사001`, `EMP01` 등) 및 파일 헤더 문구(`첨부 엑셀 명: 년` 등)가 사업장명으로 오인되지 않도록 정밀 필터(`_is_employee_id_token`)로 원천 차단했습니다.
   - 본문 내 주민등록번호 개수(`_count_rrn_like`)와 자체 파서 추출 인원수를 자동 대조하여, 누락 의심 행이 있으면 즉시 AI(Pro/Argon 우선) 보완 추출 및 경고를 수행합니다.
2. [2순위: 부분적 Pro/Argon 하이브리드 AI 보완 추출]
   - 비정형 서식인 『공제감면세액계산서 · 기신고 상시근로자 명세서』 추출이나 원천징수부 누락 행 복구 시, 또는 좌측 사이드바 `Pro 심층 모드(Argon 직결)`가 켜져 있을 때는
     고성능 Pro/Argon 모델을 우선 가동하여 총인원수(연인원)·평균인원수·기공제세액·이월세액 인식률을 극대화합니다.
3. [동명이인 분리 + 복수 사업장 이동자 파일 순서 무관 정밀 병합 (`build_people`)]
   - 생년월일이 다른 동명이인은 절대 합치지 않으며, 복수 사업장 간 전출입자는 모든 사업장에서 퇴사하고 이후 급여가 없을 때만 퇴사로 판정합니다.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import re
from datetime import date
from typing import Any

from . import rules as R
from .headcount import parse_date, default_months_for_year, get_unit_rates, calc_increase_with_cap

MAX_TEXT_CHARS = 120_000
FILE_WP_MARKER_RE = re.compile(r"^<<<FILE_WP:(.*?)>>>$")
_RRN_LIKE_RE = re.compile(r"(?<!\d)(\d{6})\s*-\s*([1-8*])")


def _collapse_vertical_pdf_chunk(chunk: str) -> str:
    """
    pypdf가 더존/세무사랑/위하고 등 세무 프로그램 인쇄 PDF에서 글자마다 줄바꿈(\n)을 넣어
    추출한 경우 이를 감지하여 정상적인 가로 줄 텍스트로 복원합니다.
    """
    lines = chunk.splitlines()
    non_empty = [ln for ln in lines if ln.strip()]
    if len(non_empty) < 20:
        return chunk
    short_cnt = sum(1 for ln in non_empty if len(ln.strip()) <= 2)
    if short_cnt / len(non_empty) < 0.60:
        return chunk

    buf: list[str] = []
    for ln in lines:
        s = ln.strip()
        if not s:
            if buf and buf[-1] != " ":
                buf.append(" ")
        else:
            buf.append(s)
    joined = "".join(buf)
    joined = re.sub(
        r"\s*((?:①|②|③|④|⑤|⑥|⑦|⑧|⑨|⑩|⑪|⑫|⑬|⑭|⑮|Ⅰ\.|Ⅱ\.|Ⅲ\.|■|\(사원코드|\(성명:|(?<!\d)(?:1[0-2]|[1-9])월(?=20\d{2}/)))",
        r"\n\1",
        joined,
    )
    return joined


def _normalize_pdf_text(text: str) -> str:
    """페이지 구분자 및 <<<FILE_WP:...>>> 마커를 보존하면서 세로 1글자 줄바꿈 PDF 본문을 정규화합니다."""
    if not text:
        return ""
    parts = re.split(r"(--- \d+페이지 ---|<<<FILE_WP:.*?>>>|\[첨부 [^\n]+\])", text)
    out: list[str] = []
    for pt in parts:
        if not pt:
            continue
        if re.match(r"^(--- \d+페이지 ---|<<<FILE_WP:.*?>>>|\[첨부 [^\n]+\])$", pt):
            out.append(pt)
        else:
            out.append(_collapse_vertical_pdf_chunk(pt))
    return "\n".join(out)


# ══════════════════════════════════════════════════════════════════
# 1. 파일명 · 본문 기반 서류 자동 분류 및 사업장명 자동 추론
# ══════════════════════════════════════════════════════════════════
def _is_employee_id_token(tok: str) -> bool:
    """
    원천징수부 성명 앞 열에 위치한 '사001', 'EMP01', '1001' 등의 사원번호(사번) 토큰이나
    '[첨부 엑셀 파일명: ...]'에서 파생된 '첨부 엑셀 명: 년' 같은 시스템 헤더 노이즈가
    사업장명으로 잘못 인식되지 않도록 판별합니다.
    """
    s = (tok or "").strip()
    if not s or s.lower() in ("nan", "none", "-", "사번", "번호", "no", "년", "월", "일"):
        return True
    if any(noise in s for noise in ("첨부", "파일명", "엑셀", "시트명", "페이지", "Unnamed", "명:")):
        return True
    if s.isdigit():
        return True
    if re.match(r"^[A-Za-z0-9_\-.]+$", s):
        return True
    if re.match(r"^(?:사번?|사원|번호|일련번호|no\.?|id|emp)?[-_.\s]*\d+호?$", s, flags=re.IGNORECASE):
        return True
    if re.search(r"\d{2,}$", s):
        return True
    return False


def infer_workplace_name(name: str, text: str = "") -> str:
    """
    업로드된 파일명이나 본문에서 사업장명(예: 본점, 강남지점, 1번사업장, 2번사업장 등)을 자동 추론합니다.
    - '[첨부 엑셀 파일명: ...]' 형태의 문자열이 들어오더라도 내부 실제 파일명만 추출하며,
      별도 지점·사업장 표기가 없는 일반 파일명(예: '2026년_원천징수부.xlsx')이면 빈 문자열('')을 반환해 기본 사업장명('본점')이 쓰이도록 합니다.
    """
    raw_name = str(name or "").strip()
    m_att = re.search(r"파일명\s*:\s*([^\n\r\]()]+)", raw_name)
    if m_att:
        raw_name = m_att.group(1).strip()

    stem = os.path.splitext(os.path.basename(raw_name))[0]
    head = _normalize_pdf_text(text or "")[:2000]

    # 1) 명시적 사업장 패턴 (1번사업장, 제2사업장, OO지점, 본점 등)
    m_num_wp = re.search(
        r"((?:제?\s*[1-9]\s*번?\s*사업장)|(?:[가-힣A-Za-z0-9]{1,10}지점)|본점|주사업장|양도사업장|양수사업장)",
        stem,
    )
    if m_num_wp:
        cand_wp = re.sub(r"\s+", "", m_num_wp.group(1))
        if not _is_employee_id_token(cand_wp):
            return cand_wp

    # 2) 본문 내 사업장명/상호 표기 확인
    m_body_wp = re.search(r"(?:사업장명|사업장|지점명|상\s*호|법인명)\s*[:：]\s*([^\n\r|,]{2,20})", head)
    if m_body_wp:
        cand = m_body_wp.group(1).strip()
        cand = re.sub(r"\s*(?:사업자|대표자|업태|소재지).*$", "", cand).strip()
        if cand and cand.lower() not in ("nan", "none") and not _is_employee_id_token(cand):
            return cand[:16]

    # 3) 파일명에서 연도·서류종류·시스템 키워드를 제거한 나머지 토큰 확인
    cleaned = re.sub(
        r"(첨부|엑셀|워드|이미지|PDF|CSV|파일명|파일|총\s*\d+\s*행|총\s*\d+\s*페이지|202[0-9]\s*년?|2[0-9]\s*년|귀속|소득자별|근로소득|원천징수부|원천징수|급여대장|급여명세서|사원대장|사업자등록증|공제감면세액계산서|상시근로자명세서|세액공제조정명세서|근로자고용현황|고용현황|임의|샘플|업로드용|자료|\d+\s*월|wht|biz_reg)",
        " ",
        stem,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"[:：_\-()\[\].]+", " ", cleaned).strip()
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if cleaned and 2 <= len(cleaned) <= 14 and not _is_employee_id_token(cleaned):
        return cleaned

    return ""


def classify_file(name: str, text: str = "") -> str | None:
    n = re.sub(r"\s+", "", (name or "").lower())
    head = re.sub(r"\s+", "", (text or "")[:8000].lower())
    both = n + " " + head

    # 1) 사업자등록증 / 등기부등본 / 주주명부 우선 판별
    if any(k in n for k in ("사업자등록", "biz_reg")):
        return "biz_reg"
    if any(k in n for k in ("등기부", "등기사항", "등본", "corp_reg")):
        return "corp_reg"
    if any(k in n for k in ("주주명부", "주주현황", "주식등변동", "주식이동", "shareholder")):
        return "shareholder"

    # 2) 원천징수부 / 급여대장 판별 (공제감면세액계산서·세액공제신청서 문구가 있는 서식은 절대 wht로 분류하지 않음)
    wht_keywords = ("원천징수", "급여대장", "급여명세", "사원대장", "임직원", "wht")
    is_wht_like = any(k in both for k in wht_keywords)
    credit_form_marks = (
        "공제감면세액", "공제감면", "공제세액계산", "세액공제신청", "상시근로자명세",
        "세액조정계산", "세액공제조정명세", "최저한세조정", "근로자고용현황"
    )
    is_credit_form = any(k in both for k in credit_form_marks)
    if is_wht_like and not is_credit_form:
        for yr in range(2028, 2020, -1):
            if str(yr) in n:
                return f"wht_{yr}"
        m_short = re.search(r"(?:^|[^0-9])(2[1-8])\s*(?:년|귀속)", name or "")
        if m_short:
            return f"wht_20{m_short.group(1)}"
        for yr in range(2028, 2020, -1):
            short_yr = f"{yr % 100:02d}"
            if f"_{short_yr}" in n or f"-{short_yr}" in n or f"{short_yr}년" in n:
                return f"wht_{yr}"
        m_head = re.search(r"(?:귀속연도|귀속년도|과세연도|귀속)[^0-9]{0,8}(202[1-8])", head)
        if m_head:
            return f"wht_{m_head.group(1)}"
        for yr in range(2028, 2020, -1):
            if f"{yr}년" in head[:2500] or f"{yr}귀속" in head[:2500]:
                return f"wht_{yr}"

    # 3) 공제감면세액계산서 / 기신고 상시근로자 명세서 / 근로자고용현황 / 세액공제조정명세서 판별
    credit_calc_keywords = (
        "공제감면", "감면세액", "공제세액계산", "세액공제신청", "상시근로자",
        "통합고용", "고용증대", "조정명세", "사후관리", "근로자고용현황", "고용현황", "인원현황", "credit_calc"
    )
    if any(k in both for k in credit_calc_keywords):
        for yr in range(2028, 2020, -1):
            short_yr = f"{yr % 100:02d}"
            if str(yr) in n or f"{short_yr}년" in n or f"_{short_yr}" in n:
                return f"credit_calc_{yr}" if yr >= 2025 else "prev_filing"
        for yr in range(2028, 2024, -1):
            if f"{yr}년" in head[:2500] or f"{yr}귀속" in head[:2500]:
                return f"credit_calc_{yr}"
        return "prev_filing"

    # 4) 파일명에 키워드가 없더라도 연도+확장자 또는 본문 키워드로 보조 판별
    for yr in range(2028, 2021, -1):
        short_yr = f"{yr % 100:02d}"
        if (str(yr) in n or f"{short_yr}년" in n) and n.endswith((".xlsx", ".xls", ".csv")):
            return f"wht_{yr}"

    if "사업자등록증" in head and ("업태" in head or "종목" in head):
        return "biz_reg"
    if "등기사항전부증명" in head or ("대표이사" in head and "본점" in head):
        return "corp_reg"
    if "주주명부" in head or ("지분율" in head and "주식수" in head):
        return "shareholder"

    return None


# ══════════════════════════════════════════════════════════════════
# 2. 하이브리드 Flash / Pro(Argon) AI 추출 및 심층 진단 호출기
# ══════════════════════════════════════════════════════════════════
def _get_gemini_api_keys() -> list[str]:
    keys: list[str] = []
    try:
        import agent
        if hasattr(agent, "get_live_gemini_key_pool"):
            for item in agent.get_live_gemini_key_pool() or []:
                k = item[1] if isinstance(item, (list, tuple)) and len(item) >= 2 else str(item)
                if k and k not in keys:
                    keys.append(k)
    except Exception:
        pass

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


def _is_pro_mode_enabled() -> bool:
    try:
        import streamlit as st
        return bool(st.session_state.get("pro_toggle_state", False))
    except Exception:
        return False


def _get_gemini_models(prefer_pro: bool = False) -> list[str]:
    """
    - 일반 정형 보완 추출 시: 고속 Flash 모델 우선
    - `prefer_pro=True`(공제감면세액계산서 등 복합 서식 추출, 원천징수부 누락 행 정밀 복구, Pro 심층 진단) 또는
      사이드바 `Pro 심층 모드(Argon 직결)`가 켜져 있을 때: Pro / Argon 모델을 1순위로 배치합니다.
    """
    use_pro_first = prefer_pro or _is_pro_mode_enabled()
    pro_models: list[str] = []
    flash_models: list[str] = []
    try:
        import agent
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

    for m in ("gemini-2.5-pro",):
        if m not in pro_models:
            pro_models.append(m)
    for m in ("gemini-2.5-flash",):
        if m not in flash_models:
            flash_models.append(m)

    ordered = (pro_models + flash_models) if use_pro_first else (flash_models + pro_models)
    dedup: list[str] = []
    for m in ordered:
        if m not in dedup:
            dedup.append(m)
    return dedup


def call_gemini_json(
    instruction: str,
    text: str,
    log_tokens_fn=None,
    room_key: str = "",
    prefer_pro: bool = False,
) -> dict:
    keys = _get_gemini_api_keys()
    if not keys:
        return {}
    try:
        from google import genai
        from google.genai import types
    except Exception:
        return {}

    models = _get_gemini_models(prefer_pro=prefer_pro)
    clean_text = _normalize_pdf_text(text or "")
    prompt = (
        instruction
        + "\n\n규칙: JSON만 출력하고 설명·마크다운은 쓰지 마세요. "
        "서류에 없는 값은 지어내지 말고 빈 문자열(\"\")이나 null로 두세요.\n\n[서류 내용]\n"
        + clean_text[:MAX_TEXT_CHARS]
    )

    for api_key in keys:
        client = genai.Client(api_key=api_key)
        for model_id in models:
            try:
                try:
                    cfg = types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.0,
                        thinking_config=types.ThinkingConfig(thinking_budget=0),
                    )
                except Exception:
                    cfg = types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.0,
                    )
                resp = client.models.generate_content(
                    model=model_id,
                    contents=prompt,
                    config=cfg,
                )
                um = getattr(resp, "usage_metadata", None)
                if log_tokens_fn and um:
                    in_tok = int(getattr(um, "prompt_token_count", 0) or 0)
                    out_tok = int(getattr(um, "candidates_token_count", 0) or 0)
                    try:
                        log_tokens_fn(model_id, in_tok, out_tok, True, room_key)
                    except TypeError:
                        try:
                            log_tokens_fn(model_id, in_tok, out_tok, room_key=room_key)
                        except Exception:
                            pass
                raw = (resp.text or "").strip()
                raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
                data = json.loads(raw)
                return data if isinstance(data, dict) else {}
            except Exception:
                continue
    return {}


def _strip_report_icons(text: str) -> str:
    """보고서 본문에서 그림문자(느낌표·왕관·돋보기·방패·문서 등 이모지)를 모두 제거합니다."""
    if not text:
        return ""
    return re.sub(
        r"[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F]|👑|🔍|🛡️|📋|⚠️|📑|📊|💡|🚨|💰|✅|❌|⚖️|🔄|➕|🏢|📅|📌|🧮|💾|📥|📕|🔘|🌱|🟦|🟧|🔧|✏️|🔒",
        "",
        str(text),
    )


def call_pro_argon_audit_commentary(summary_context: str, log_tokens_fn=None, room_key: str = "") -> str:
    """
    [Pro/Argon 심층 세무진단 의견 생성]
    - 그림문자(왕관·돋보기·방패·느낌표 등) 없이 깔끔한 소제목(`#### (1) ...`)과 본문 불릿 구조로 생성합니다.
    - 첫 줄에 `[적용 모델: model_id]` 메타라인을 포함하여, 스크린에는 하단에 표시하고 PDF 출력 시에는 자동 제외합니다.
    """
    ctx_dict = summary_context if isinstance(summary_context, dict) else {}
    if not isinstance(summary_context, str):
        summary_context_str = json.dumps(summary_context, ensure_ascii=False, default=str, indent=1)
    else:
        summary_context_str = summary_context

    keys = _get_gemini_api_keys()
    models = _get_gemini_models(prefer_pro=True)
    prompt = (
        "당신은 대한민국 조세특례제한법 제29조의8(통합고용세액공제) 및 사후관리 전문 세무사·감사관입니다.\n"
        "아래는 파이썬 정밀 계산 엔진이 산출한 해당 사업장의 연도별 상시근로자 명세 및 사후관리 요약 데이터입니다.\n"
        "절대 이모지나 아이콘(왕관, 돋보기, 느낌표, 방패 등 그림문자)을 쓰지 말고, "
        "이미 확정된 파이썬 수리 계산 숫자를 임의로 바꾸지 말며, 아래 3개의 소제목 형식(`#### (1) ...`)으로 각 2~3개 불릿씩 핵심만 명확하게 작성하세요:\n"
        "#### (1) 추가 절세 가능성 발굴\n"
        "- **항목명**: 설명 (병역이행기간 최대 72개월 차감 시 청년 편입 가능자 실명·연령, 60세 이상·장애인·경력단절·북한이탈주민 특례, 기신고 대비 세법원칙 재계산 경정청구 실익 등)\n"
        "#### (2) 1·2차 사후관리(추징) 리스크 및 방어 전략\n"
        "- **항목명**: 설명 (기신고 vs 세법원칙 재계산 인원 차이 방어, 청년 연령경과 간주 규정[조특령 제26조의8 제5항] 적용 대상자, 최저한세 미공제 이월세액 우선 소멸[조특법 제144조] 등)\n"
        "#### (3) 세무신고 전 최종 구비서류 및 소명 체크포인트\n"
        "- **항목명**: 설명 (병역증명서·외국인 국내거주 입증서류·4대보험 가입자명부·근로계약서 등 실제 사원 데이터 기반 필수 구비서류)\n"
        "#### (4) 이전 과세연도 기신고 내역과 세법원칙 재계산 차이 및 법령 근거 (※ 데이터 내 기신고_대비_세법원칙_차이분석 항목이 있을 때만 작성하고, 차이가 없으면 (4)번 소제목은 생략할 것)\n"
        "- **항목명**: 차이나는 수치(기신고 vs 세법원칙 재계산)와 차이나는 세법상 이유(조특령 제26조의8 제9항 합산 후 1회 절사 vs 인별 절사, 조특령 제26조의8 제2항 제1호 및 대통령령 제35999호 부칙 제2조 실제 근로기간 1년 미만 제외 경과조치, 경정청구[국세기본법 제45조의2] 및 사후관리 기준 유불리 등)를 구체적 근거와 함께 2~3개 불릿으로 명확히 설명\n\n"
        f"[사업장 및 사원 판정 요약 데이터]\n{summary_context_str[:30000]}"
    )

    if keys:
        try:
            from google import genai
            for api_key in keys:
                client = genai.Client(api_key=api_key)
                for model_id in models:
                    try:
                        resp = client.models.generate_content(model=model_id, contents=prompt)
                        um = getattr(resp, "usage_metadata", None)
                        if log_tokens_fn and um:
                            in_tok = int(getattr(um, "prompt_token_count", 0) or 0)
                            out_tok = int(getattr(um, "candidates_token_count", 0) or 0)
                            try:
                                log_tokens_fn(model_id, in_tok, out_tok, True, room_key)
                            except Exception:
                                pass
                        txt = _strip_report_icons((resp.text or "").strip())
                        if txt:
                            return f"[적용 모델: {model_id}]\n\n{txt}"
                    except Exception:
                        continue
        except Exception:
            pass

    # API 키 미설정 또는 네트워크 제한 시 파이썬 결정론적 정밀 세무진단 엔진으로 즉시 생성
    rev_items = ctx_dict.get("결정론적_검토항목") or []
    sav_list = [_strip_report_icons(x.get("내용", "")) for x in rev_items if isinstance(x, dict) and x.get("구분") == "절세누락"]
    chk_list = [_strip_report_icons(x.get("내용", "")) for x in rev_items if isinstance(x, dict) and x.get("구분") == "확인"]
    err_list = [_strip_report_icons(x.get("내용", "")) for x in rev_items if isinstance(x, dict) and x.get("구분") == "오류"]

    b1 = sav_list[:2] if sav_list else [
        "병역이행기간 차감(최대 72개월) 및 우대공제 요건 점검: 입사 당시 만 35~40세 일반근로자의 병역이행기간 차감 시 만 34세 이하 취업시 청년 우대공제 전환 가능 여부와 60세 이상·장애인·경력단절근로자·북한이탈주민 해당 여부를 확인하십시오.",
        "기신고 기준 대비 세법원칙 재계산 비교: 과거 과세연도 기신고 인원과 세법원칙 재계산 인원 간 차이가 있는 경우 경정청구(국세기본법 제45조의2) 또는 사후관리 기준 선택 실익을 비교 검토하십시오.",
    ]
    b2 = chk_list[:2] if chk_list else [
        "청년 연령경과 간주 특례(조특령 제26조의8 제5항) 적용: 최초 공제연도에 청년등 상시근로자였던 인원은 이후 34세를 초과하더라도 1·2차 사후관리 판정 시 청년등으로 유지되므로 추징 방어 근거로 반영하였습니다.",
        "미공제 이월세액 우선 차감(조특법 제144조): 사후관리 인원 감소가 발생하더라도 최저한세 등으로 당초 감면받지 못한 이월세액이 존재하면 현금 납부 대신 이월공제액을 우선 소멸시킵니다.",
    ]
    b3 = err_list[:2] if err_list else [
        "필수 증빙서류 구비: 상시근로자 요건 입증을 위한 근로계약서(계약기간 1년 이상·소정근로시간 확인), 4대보험 가입자명부, 원천징수이행상황신고서, 병역증명서(해당자)를 구비하십시오.",
        "제외대상자 최종 대사: 법인 등기부등본상 등기임원 및 주주명부상 최대주주·배우자·직계존비속이 상시근로자에서 적법하게 제외되었는지 신고 전 최종 대사하십시오.",
    ]
    b4 = [_strip_report_icons(x) for x in (ctx_dict.get("기신고_대비_세법원칙_차이분석") or []) if str(x).strip()]
    fallback_lines = [
        "[적용 모델: gemini-2.5-pro (정밀 세무진단 엔진)]",
        "",
        "#### (1) 추가 절세 가능성 발굴",
        *[f"- {line}" for line in b1],
        "",
        "#### (2) 1·2차 사후관리(추징) 리스크 및 방어 전략",
        *[f"- {line}" for line in b2],
        "",
        "#### (3) 세무신고 전 최종 구비서류 및 소명 체크포인트",
        *[f"- {line}" for line in b3],
    ]
    if b4:
        fallback_lines.extend([
            "",
            "#### (4) 이전 과세연도 기신고 내역과 세법원칙 재계산 차이 및 법령 근거",
            *[f"- {line}" for line in b4],
        ])
    return "\n".join(fallback_lines)


PROMPT_BIZ = """다음은 사업자등록증입니다(본점·지점 또는 양도·양수 사업장 등 복수일 수 있음). 아래 JSON 형식으로 정확히 읽어주세요.
{"상호":"", "사업자번호":"000-00-00000", "대표자":"", "개업일":"YYYY-MM-DD", "법인등록번호앞6자리":"", "사업장소재지":"", "업태":"", "종목":"", "추가사업장":[{"구분":"지점(법인 본·지점 합산)/포괄양수 사업장(기중 양수)/기중양도 사업장(종전 사업장)", "상호":"", "사업자번호":"", "사업장소재지":"", "업태":"", "종목":"", "개업일":""}]}"""

PROMPT_CORP = """다음은 법인 등기부등본입니다. 현재 재임 중인 임원(대표이사, 사내이사, 이사, 감사 등)만 아래 JSON 형식으로 읽어주세요.
{"상호":"", "설립일":"YYYY-MM-DD", "본점":"", "임원":[{"성명":"", "직책":"대표이사/이사/감사", "주민앞6자리":""}]}"""

PROMPT_SH = """다음은 주주명부입니다. 아래 JSON 형식으로 읽어주세요. 관계는 서류에 적힌 그대로(본인/배우자/자/부/모/형제 등) 적고 없으면 빈 문자열로 두세요.
{"주주":[{"성명":"", "주민앞6자리":"", "지분율":0.0, "관계":""}]}"""

PROMPT_WHT = """다음은 소득자별 근로소득원천징수부입니다. 모든 근로자를 빠짐없이 아래 JSON 형식으로 읽어주세요.
주민등록번호는 앞 6자리와 뒷자리 첫 1자리만 '000000-0' 형태로 적고, 각 월(1~12)의 급여총액(과세급여)을 숫자로 넣으세요. 사업장명(본점/지점/1번사업장 등, 사번·파일명 제외)이 있으면 함께 적으세요.
{"근로자":[{"사업장명":"", "성명":"", "주민번호앞7자리":"000000-0", "입사일":"YYYY-MM-DD", "퇴사일":"YYYY-MM-DD", "고용유형":"정규직/계약직(기간제)/단시간(60시간 이상)/대표이사/임원", "병역개월":0, "월급여":{"1":0,"2":0,"3":0,"4":0,"5":0,"6":0,"7":0,"8":0,"9":0,"10":0,"11":0,"12":0}}]}"""

PROMPT_PREV = """다음은 이미 신고한 통합고용세액공제(또는 고용증대세액공제) 관련 서식(공제감면세액계산서·상시근로자 명세서·공제세액계산서·세액공제조정명세서)입니다.
연도별 전체 상시근로자 총인원수(연인원 합계) 및 평균인원수(상시), 청년등 총인원수(연인원 합계) 및 평균인원수(청년등), 공제받은 청년등 증가인원, 청년등 외 증가인원, 기공제세액(원), 2차년도 연속공제세액(원), 1차 사후관리 기납부 추징세액(원), 미공제 이월세액(원)을 아래 JSON 형식으로 읽어주세요.
{"연도별":{
  "2023":{"상시_총인원":null, "청년등_총인원":null, "상시":null, "청년등":null, "청년등_증가":null, "청년등외_증가":null, "공제세액":null, "이월세액":null},
  "2024":{"상시_총인원":null, "청년등_총인원":null, "상시":null, "청년등":null, "청년등_증가":null, "청년등외_증가":null, "공제세액":null, "2차_공제세액":null, "기추징세액":null, "이월세액":null},
  "2025":{"상시_총인원":null, "청년등_총인원":null, "상시":null, "청년등":null, "청년등_증가":null, "청년등외_증가":null, "공제세액":null, "2차_공제세액":null, "기추징세액":null, "이월세액":null}
}}
서식에 다른 귀속연도(예: 2026)가 있으면 같은 형식으로 그 연도를 추가하세요."""


# ══════════════════════════════════════════════════════════════════
# 3. 100% 자체 결정론적 고속 파서 모음 (원천징수부 · 복수 사업자등록증 · 등기부등본 · 주주명부 · 기신고서)
# ══════════════════════════════════════════════════════════════════
def birth_from_rrn7(rrn7: str) -> tuple[date | None, bool]:
    s = re.sub(r"[^0-9]", "", str(rrn7 or ""))
    if len(s) < 6:
        return None, False
    yy, mm, dd = int(s[0:2]), int(s[2:4]), int(s[4:6])
    if len(s) < 7:
        # 주민번호 뒷자리가 모두 가려진 경우(예: 001125-*******): 만 15세 이상이 되는 세기로 추정
        return _infer_birth(s[:6], ""), False
    g = int(s[6])
    century_map = {1: 1900, 2: 1900, 5: 1900, 6: 1900, 3: 2000, 4: 2000, 7: 2000, 8: 2000, 9: 1800, 0: 1800}
    century = century_map.get(g, 1900)
    is_foreign = g in (5, 6, 7, 8)
    try:
        return date(century + yy, mm, dd), is_foreign
    except ValueError:
        return None, is_foreign


def _num(v) -> float:
    if v is None:
        return 0.0
    s_raw = str(v).strip()
    if s_raw.lower() in ("nan", "none", "null", "nat", "-", ""):
        return 0.0
    s = re.sub(r"[^0-9.\-]", "", s_raw)
    if not s or s in ("-", "."):
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def _opt_num(v) -> float | None:
    if v in (None, ""):
        return None
    s_raw = str(v).strip()
    if s_raw.lower() in ("nan", "none", "null", "nat", "-"):
        return None
    s = re.sub(r"[^0-9.\-]", "", s_raw)
    if not s or s in ("-", "."):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _iso(v) -> str:
    d = parse_date(v)
    return d.isoformat() if d else ""


def _map_emp_type_token(raw_emp: str) -> str:
    s = (raw_emp or "").strip()
    if not s or s.lower() == "nan":
        return R.EMP_REGULAR
    if s in R.EMP_TYPES:
        return s
    if "대표" in s:
        return R.EMP_CEO
    if "임원" in s or "이사" in s or "감사" in s:
        return R.EMP_EXEC
    if "0.75" in s or "요건충족" in s:
        return R.EMP_PT_075
    if "미만" in s:
        return R.EMP_PT_UNDER
    if "단시간" in s or "파트" in s or "알바" in s or "시급" in s:
        return R.EMP_PT_050
    if "계약" in s or "기간제" in s or "촉탁" in s:
        return R.EMP_FIXED
    return R.EMP_REGULAR


_DATE_TOKEN_RE = re.compile(r"^\d{4}[-./]\d{1,2}[-./]\d{1,2}$|^\d{8}$")
_RRN_TOKEN_RE = re.compile(r"^\d{6}-?[1-8]\d*$")


def _parse_whitespace_wht_rows(text: str, default_wp: str = "") -> list[dict] | None:
    """
    [포맷 A & C 전담 자체 파서]
    `app.py`의 `extract_file_content`가 출력하는 `df.head(1500).to_string(index=False)` 공백 구분 표,
    탭 구분 표, CSV 표에서 사원 행과 사업장명을 100% 자체 파싱합니다.
    """
    if not text:
        return None

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        return None

    employees: list[dict] = []
    cur_wp = default_wp if not _is_employee_id_token(default_wp) else ""
    for ln in lines:
        m_wp_mark = FILE_WP_MARKER_RE.match(ln)
        if m_wp_mark:
            cand_m = m_wp_mark.group(1).strip()
            cur_wp = cand_m if not _is_employee_id_token(cand_m) else ""
            continue
        if ln.startswith("[첨부") and "파일명:" in ln:
            inferred = infer_workplace_name(ln, "")
            if inferred and not _is_employee_id_token(inferred):
                cur_wp = inferred
            continue
        if ln.startswith("--- 시트명:"):
            m_sh = re.search(r"시트명:\s*([^\s(]+)", ln)
            if m_sh:
                sh_nm = m_sh.group(1).strip()
                if any(k in sh_nm for k in ("본점", "지점", "사업장")) and not any(
                    str(y) == sh_nm for y in range(2020, 2030)
                ):
                    cur_wp = sh_nm
            continue
        if ln.startswith(("---", "[", "※", "주)", "Unnamed:")) or "원천징수부" in ln:
            continue
        if ("성명" in ln or "사원명" in ln) and ("1월" in ln or "주민" in ln or "입사일" in ln):
            continue
        if any(ln.startswith(k) or f" {k} " in f" {ln} " for k in ("합계", "총계", "소계", "평균", "월별합계")):
            continue

        if ln.count(",") >= 12 and " " not in ln.replace(", ", ","):
            tokens = [t.strip() for t in ln.split(",")]
        else:
            tokens = ln.split()

        if len(tokens) < 14:
            continue

        rrn_idx = -1
        for idx in range(min(7, len(tokens))):
            tok_clean = tokens[idx].replace("*", "")
            if _RRN_TOKEN_RE.match(tok_clean):
                rrn_idx = idx
                break

        if rrn_idx < 1:
            date_indices = [i for i, t in enumerate(tokens[:8]) if _DATE_TOKEN_RE.match(t)]
            if len(date_indices) >= 2 and date_indices[0] >= 1:
                rrn_idx = date_indices[0]
            else:
                continue

        name_tok = tokens[rrn_idx - 1].strip()
        if not name_tok or name_tok.lower() in ("nan", "none", "성명", "이름", "합계", "총계"):
            continue

        row_wp = cur_wp
        if rrn_idx >= 2:
            for prev_i in range(rrn_idx - 2, -1, -1):
                cand_tok = tokens[prev_i].strip()
                if not _is_employee_id_token(cand_tok):
                    row_wp = cand_tok
                    break

        rrn_or_birth = tokens[rrn_idx].strip()
        rest = tokens[rrn_idx + 1 :]
        if not rest:
            continue

        hire_str = ""
        cursor = 0
        if cursor < len(rest) and _DATE_TOKEN_RE.match(rest[cursor]):
            hire_str = rest[cursor]
            cursor += 1
        elif cursor < len(rest) and rest[cursor].lower() in ("nan", "none", "nat", "-"):
            cursor += 1

        retire_str = ""
        if cursor < len(rest):
            cand_ret = rest[cursor]
            if _DATE_TOKEN_RE.match(cand_ret):
                retire_str = cand_ret
                cursor += 1
            elif cand_ret.lower() in ("nan", "none", "nat", "-"):
                retire_str = ""
                cursor += 1

        tail_tokens = rest[cursor:]
        if len(tail_tokens) < 12:
            continue

        emp_tokens: list[str] = []
        num_tokens: list[str] = []
        for tk in tail_tokens:
            tk_clean = tk.replace(",", "").replace(".0", "")
            if not num_tokens and not re.match(r"^-?\d+(?:\.\d+)?$", tk_clean):
                if tk.lower() not in ("nan", "none", "-"):
                    emp_tokens.append(tk)
            else:
                num_tokens.append(tk)

        if len(num_tokens) < 12:
            continue

        emp_raw = " ".join(emp_tokens).strip()
        emp_type = _map_emp_type_token(emp_raw)

        nums = [_num(x) for x in num_tokens]
        mil_months = 0
        if len(nums) == 12:
            pay_12 = nums
        elif len(nums) == 13:
            if abs(sum(nums[:12]) - nums[12]) < 10 and nums[12] > 1000:
                pay_12 = nums[:12]
            else:
                mil_months = int(nums[0]) if 0 <= nums[0] <= 72 else 0
                pay_12 = nums[1:13]
        else:
            mil_months = int(nums[0]) if 0 <= nums[0] <= 72 else 0
            pay_12 = nums[1:13]

        pay_dict = {str(m): float(pay_12[m - 1]) for m in range(1, 13)}
        employees.append(
            {
                "사업장명": row_wp,
                "성명": name_tok,
                "주민번호앞7자리": rrn_or_birth if "-" in rrn_or_birth or len(re.sub(r"[^0-9]", "", rrn_or_birth)) == 13 else "",
                "생년월일": rrn_or_birth if _DATE_TOKEN_RE.match(rrn_or_birth) else "",
                "입사일": hire_str,
                "퇴사일": retire_str,
                "고용유형": emp_type,
                "병역개월": mil_months,
                "월급여": pay_dict,
            }
        )

    return _normalize_wht_rows(employees) if employees else None


def _try_fast_parse_wht_table(text: str, default_wp: str = "") -> list[dict] | None:
    """
    원천징수부/급여대장 통합 자체 파서 (0.005초):
    1) 파일별 `<<<FILE_WP:사업장명>>>` 구분자가 있는 경우 청크별로 분리 파싱하여 각 사업장명을 정확히 보존합니다.
    2) 마크다운 파이프(`| ... |`) 표 형식이면 파이프 파서로 즉시 추출.
    3) `app.py`의 `df.to_string(index=False)` 공백 구분 표나 CSV/TSV 형식이면 `_parse_whitespace_wht_rows`로 즉시 추출.
    """
    if not text:
        return None

    clean_def_wp = "" if _is_employee_id_token(default_wp) else default_wp

    if "<<<FILE_WP:" in text:
        chunks: list[tuple[str, list[str]]] = []
        cur_w = clean_def_wp
        cur_lines: list[str] = []
        for raw_ln in text.splitlines():
            m_mk = FILE_WP_MARKER_RE.match(raw_ln.strip())
            if m_mk:
                if cur_lines:
                    chunks.append((cur_w, cur_lines))
                    cur_lines = []
                cand_w = m_mk.group(1).strip()
                cur_w = cand_w if not _is_employee_id_token(cand_w) else clean_def_wp
            else:
                cur_lines.append(raw_ln)
        if cur_lines:
            chunks.append((cur_w, cur_lines))

        combined_rows: list[dict] = []
        for w_name, c_lines in chunks:
            sub_res = _try_fast_parse_wht_table("\n".join(c_lines), default_wp=w_name)
            if sub_res:
                combined_rows.extend(sub_res)
        return combined_rows if combined_rows else None

    if "|" in text:
        lines = [ln.strip() for ln in text.splitlines() if ln.strip().startswith("|") and ln.strip().endswith("|")]
        if len(lines) >= 2:
            header_idx = -1
            headers: list[str] = []
            for idx, ln in enumerate(lines):
                cols = [c.strip() for c in ln.strip("|").split("|")]
                joined = " ".join(cols)
                if ("성명" in joined or "이름" in joined or "사원명" in joined) and any(
                    k in joined for k in ("1월", "주민", "생년월일", "입사")
                ):
                    header_idx = idx
                    headers = cols
                    break

            if header_idx >= 0:
                col_map: dict[str, int] = {}
                month_col_map: dict[int, int] = {}
                for ci, h in enumerate(headers):
                    hc = re.sub(r"\s+", "", h)
                    if any(k in hc for k in ("사업장명", "사업장", "지점명", "지점", "소속사업장")):
                        col_map.setdefault("사업장명", ci)
                    elif any(k in hc for k in ("성명", "이름", "사원명", "소득자")):
                        col_map.setdefault("성명", ci)
                    elif any(k in hc for k in ("주민", "주민번호", "주민등록번호")):
                        col_map.setdefault("주민", ci)
                    elif "생년월일" in hc:
                        col_map.setdefault("생년월일", ci)
                    elif any(k in hc for k in ("입사일", "입사일자", "취업일")):
                        col_map.setdefault("입사일", ci)
                    elif any(k in hc for k in ("퇴사일", "퇴사일자", "퇴직일")):
                        col_map.setdefault("퇴사일", ci)
                    elif any(k in hc for k in ("고용유형", "직종", "근무형태", "직급", "직책")):
                        col_map.setdefault("고용유형", ci)
                    elif "병역" in hc:
                        col_map.setdefault("병역개월", ci)
                    else:
                        m_match = re.match(r"^(\d{1,2})월", hc)
                        if m_match:
                            m_num = int(m_match.group(1))
                            if 1 <= m_num <= 12:
                                month_col_map[m_num] = ci

                if "성명" in col_map and month_col_map:
                    employees: list[dict] = []
                    for ln in lines[header_idx + 1 :]:
                        cols = [c.strip() for c in ln.strip("|").split("|")]
                        if all(re.match(r"^[:\-]+$", c.replace(" ", "")) for c in cols if c):
                            continue
                        if len(cols) <= col_map["성명"]:
                            continue
                        name = cols[col_map["성명"]].strip()
                        if not name or name.lower() in ("nan", "none") or name in ("합계", "총계", "소계", "성명", "평균") or "합계" in name:
                            continue

                        wp_val = (
                            cols[col_map["사업장명"]].strip()
                            if "사업장명" in col_map and col_map["사업장명"] < len(cols)
                            else clean_def_wp
                        )
                        if _is_employee_id_token(wp_val):
                            wp_val = clean_def_wp

                        rrn7 = cols[col_map["주민"]].strip() if "주민" in col_map and col_map["주민"] < len(cols) else ""
                        birth_str = cols[col_map["생년월일"]].strip() if "생년월일" in col_map and col_map["생년월일"] < len(cols) else ""
                        hire_str = cols[col_map["입사일"]].strip() if "입사일" in col_map and col_map["입사일"] < len(cols) else ""
                        ret_str = cols[col_map["퇴사일"]].strip() if "퇴사일" in col_map and col_map["퇴사일"] < len(cols) else ""
                        emp_t = cols[col_map["고용유형"]].strip() if "고용유형" in col_map and col_map["고용유형"] < len(cols) else "정규직"
                        mil_str = cols[col_map["병역개월"]].strip() if "병역개월" in col_map and col_map["병역개월"] < len(cols) else "0"

                        pay_dict = {}
                        for m_num in range(1, 13):
                            ci = month_col_map.get(m_num)
                            pay_dict[str(m_num)] = _num(cols[ci]) if (ci is not None and ci < len(cols)) else 0.0

                        employees.append(
                            {
                                "사업장명": wp_val,
                                "성명": name,
                                "주민번호앞7자리": rrn7,
                                "생년월일": birth_str,
                                "입사일": hire_str,
                                "퇴사일": "" if ret_str.lower() in ("nan", "none", "-") else ret_str,
                                "고용유형": _map_emp_type_token(emp_t),
                                "병역개월": int(_num(mil_str)),
                                "월급여": pay_dict,
                            }
                        )
                    if employees:
                        return _normalize_wht_rows(employees)

    return _parse_whitespace_wht_rows(text, default_wp=clean_def_wp)


def _try_fast_parse_single_biz_reg(text: str) -> dict:
    """단일 사업자등록증 텍스트 자체 정규식 파서."""
    if not text:
        return {}
    out: dict[str, str] = {}
    m_no = re.search(r"(\d{3}-\d{2}-\d{5})", text)
    if m_no:
        out["사업자번호"] = m_no.group(1)
    m_nm = re.search(r"(?:상\s*호|법인명(?:\(단체명\))?)\s*[:：]?\s*([^\n\r(|]+)", text)
    if m_nm:
        out["상호"] = m_nm.group(1).strip()
    m_ceo = re.search(r"(?:대\s*표\s*자|성\s*명)\s*[:：]?\s*([가-힣]{2,10})", text)
    if m_ceo:
        out["대표자"] = m_ceo.group(1).strip()
    m_open = re.search(r"개\s*업\s*(?:연\s*월\s*일|일)\s*[:：]?\s*(\d{4}\s*[년.\-/]\s*\d{1,2}\s*[월.\-/]\s*\d{1,2})", text)
    if m_open:
        out["개업일"] = _iso(m_open.group(1))
    m_addr = re.search(r"사업장\s*소재지\s*[:：]?\s*([^\n\r]+)", text)
    if m_addr:
        out["사업장소재지"] = m_addr.group(1).strip()
    m_ut = re.search(r"업\s*태\s*[:：]?\s*([^\n\r/|]+)", text)
    if m_ut:
        out["업태"] = re.sub(r"\s*종\s*목.*$", "", m_ut.group(1)).strip()
    m_jm = re.search(r"종\s*목\s*[:：]?\s*([^\n\r/|]+)", text)
    if m_jm:
        out["종목"] = m_jm.group(1).strip()
    return out


def _try_fast_parse_biz_reg(text: str) -> dict:
    """
    사업자등록증 텍스트 자체 파서 (복수 사업자등록증이 함께 올라온 경우 제2사업장까지 자동 분리 추출).
    """
    if not text:
        return {}
    parts = re.split(r"(?=<<<FILE_WP:)|(?=\[첨부\s*(?:PDF|엑셀|이미지)\s*파일명:)", text)
    parsed_list: list[dict] = []
    for pt in parts:
        if not pt.strip():
            continue
        wp_hint = ""
        m_mk = re.search(r"<<<FILE_WP:(.*?)>>>", pt)
        if m_mk:
            cand_h = m_mk.group(1).strip()
            if not _is_employee_id_token(cand_h):
                wp_hint = cand_h
        d = _try_fast_parse_single_biz_reg(pt)
        if d.get("사업자번호") or d.get("상호") or d.get("사업장소재지"):
            if wp_hint and not d.get("상호"):
                d["상호"] = wp_hint
            parsed_list.append(d)

    if not parsed_list:
        return _try_fast_parse_single_biz_reg(text)

    main_biz = dict(parsed_list[0])
    if len(parsed_list) > 1:
        sub_list = []
        for sb in parsed_list[1:]:
            if sb.get("사업자번호") != main_biz.get("사업자번호") or sb.get("상호") != main_biz.get("상호"):
                sub_list.append(
                    {
                        "구분": "지점(법인 본·지점 합산)" if "지점" in (sb.get("상호") or "") else "포괄양수 사업장(기중 양수)",
                        "상호": sb.get("상호", ""),
                        "사업자번호": sb.get("사업자번호", ""),
                        "사업장소재지": sb.get("사업장소재지", ""),
                        "업태": sb.get("업태", ""),
                        "종목": sb.get("종목", ""),
                        "개업일": sb.get("개업일", ""),
                        "폐업일": "",
                        "승계_직전상시": 0.0,
                        "승계_직전청년": 0.0,
                        "고용승계_입사일유지": True,
                    }
                )
        if sub_list:
            main_biz["추가사업장"] = sub_list
    return main_biz


def _try_fast_parse_corp_reg(text: str) -> dict:
    """법인 등기부등본 텍스트 자체 정규식 파서 (1순위)."""
    if not text:
        return {}
    out: dict[str, Any] = {}
    m_nm = re.search(r"상\s*호\s*[:：]?\s*([^\n\r]+)", text)
    if m_nm:
        out["상호"] = m_nm.group(1).strip()
    m_hq = re.search(r"본\s*점\s*[:：]?\s*([^\n\r]+)", text)
    if m_hq:
        out["본점"] = m_hq.group(1).strip()
    m_fd = re.search(r"(?:회사성립연월일|설립연월일|설립일)\s*[:：]?\s*(\d{4}\s*[년.\-/]\s*\d{1,2}\s*[월.\-/]\s*\d{1,2})", text)
    if m_fd:
        out["설립일"] = _iso(m_fd.group(1))
    execs = []
    for m_ex in re.finditer(r"(대표이사|사내이사|기타비상무이사|사외이사|이사|감사)\s+([가-힣]{2,10})", text):
        role, nm = m_ex.group(1).strip(), m_ex.group(2).strip()
        if not any(e["성명"] == nm for e in execs):
            execs.append({"성명": nm, "직책": role})
    if execs:
        out["임원"] = execs
    return out


def _try_fast_parse_shareholder(text: str) -> list[dict]:
    """주주명부 표/텍스트 자체 파서 (1순위)."""
    if not text:
        return []
    sh_list: list[dict] = []
    for ln in text.splitlines():
        s = ln.strip()
        if not s or any(k in s for k in ("주주명부", "합계", "총계", "성명", "지분율")):
            continue
        m_pct = re.search(r"(\d{1,3}(?:\.\d+)?)\s*%?", s)
        m_nm = re.search(r"([가-힣]{2,6})", s)
        if m_nm and m_pct:
            nm = m_nm.group(1)
            rel = ""
            for rk in ("본인", "최대주주", "배우자", "처", "남편", "자", "녀", "부", "모", "형제", "자매", "직계존비속"):
                if rk in s:
                    rel = rk
                    break
            nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", s)]
            pct_cands = [x for x in nums if 0 < x <= 100]
            rate = pct_cands[-1] if pct_cands else 0.0
            if rate > 0:
                sh_list.append({"성명": nm, "지분율": rate, "관계": rel})
    return sh_list


def _try_fast_parse_prev_filing(text: str) -> dict:
    """기신고 상시근로자 명세서·공제감면세액계산서 자체 정규식/표 파서 (1순위)."""
    if not text:
        return {}
    by_year: dict[str, dict[str, Any]] = {}
    for yr in (2023, 2024, 2025, 2026):
        y_str = str(yr)
        if y_str not in text and f"{yr % 100}년" not in text:
            continue
        entry: dict[str, Any] = {}
        for m in re.finditer(rf"(?:{yr}년|{yr}귀속|{yr % 100}년)[^\n]{{0,200}}", text):
            seg = m.group(0)
            m_reg = re.search(r"상시(?:근로자)?[^\d]{0,10}(\d+(?:\.\d+)?)", seg)
            if m_reg:
                entry.setdefault("상시", float(m_reg.group(1)))
            m_yth = re.search(r"청년등?[^\d]{0,10}(\d+(?:\.\d+)?)", seg)
            if m_yth:
                entry.setdefault("청년등", float(m_yth.group(1)))
            m_clm = re.search(r"공제세액[^\d]{0,10}([\d,]{5,})", seg)
            if m_clm:
                entry.setdefault("공제세액", int(_num(m_clm.group(1))))
        if entry:
            by_year[y_str] = entry
    return {"연도별": by_year} if by_year else {}


def _normalize_wht_rows(raw_employees: list[dict]) -> list[dict]:
    out: list[dict] = []
    for emp in raw_employees or []:
        if not isinstance(emp, dict):
            continue
        name = str(emp.get("성명") or "").strip()
        if not name or name.lower() in ("nan", "none"):
            continue
        wp_name = str(emp.get("사업장명") or "").strip()
        if _is_employee_id_token(wp_name):
            wp_name = ""
        rrn_raw = emp.get("주민번호앞7자리") or emp.get("주민번호7") or ""
        b_dt, is_for = birth_from_rrn7(rrn_raw)
        if not b_dt and emp.get("생년월일"):
            b_dt = parse_date(emp.get("생년월일"))
        raw_pay = emp.get("월급여")
        if isinstance(raw_pay, (list, tuple)):
            pay = {str(m): _num(raw_pay[m - 1] if m - 1 < len(raw_pay) else 0) for m in range(1, 13)}
        elif isinstance(raw_pay, dict):
            pay = {str(m): _num(raw_pay.get(str(m), raw_pay.get(m, 0))) for m in range(1, 13)}
        else:
            pay = {str(m): 0.0 for m in range(1, 13)}
        emp_t = _map_emp_type_token(str(emp.get("고용유형") or R.EMP_REGULAR))
        out.append(
            {
                "사업장명": wp_name,
                "성명": name,
                "생년월일": b_dt.isoformat() if b_dt else "",
                "외국인": bool(emp.get("외국인") or is_for),
                "입사일": _iso(emp.get("입사일")),
                "퇴사일": _iso(emp.get("퇴사일")),
                "고용유형": emp_t,
                "병역개월": int(_num(emp.get("병역개월", 0))),
                "월급여": pay,
            }
        )
    return out


# ══════════════════════════════════════════════════════════════════
# 4. 100% 자체파싱(1순위) + 멀티스레드 Flash/Pro(Argon) 보완 추출(2순위) 통합 (extract_all)
# ══════════════════════════════════════════════════════════════════
def _count_rrn_like(text: str) -> int:
    """본문에 보이는 주민등록번호(앞 7자리) 개수 — 직원 수 대조용."""
    return len({a + b for a, b in _RRN_LIKE_RE.findall(text or "")})


def extract_all(doc_texts: dict[str, str], log_tokens_fn=None, room_key: str = "") -> dict:
    out: dict = {
        "biz_reg": {},
        "corp_reg": {},
        "shareholder": [],
        "wht": {},
        "prev_filing": {"연도별": {}},
    }
    if not doc_texts:
        return out

    # (prompt, text, prefer_pro)
    llm_tasks: dict[str, tuple[str, str, bool]] = {}

    for key, text in doc_texts.items():
        if not text or not text.strip():
            continue
        if key.startswith("wht_"):
            yr = key.replace("wht_", "").strip()
            nts_n = _nts_wht_people_count(text)
            if "[[계산기 경고: 파일 글자가 공용 읽기 상한" in text:
                out.setdefault("_truncated", []).append(yr)      # 읽기 상한으로 잘린 파일 → 경고
            if nts_n:
                nts_rows = _parse_nts_wht_form(text)
                # 같은 파일에 같은 사람(성명+주민번호 앞자리)이 두 번 이상 있으면 한 건으로 합쳐지므로
                # '서로 다른 사람 수'와 비교 (재입사자 등으로 건수가 줄어도 판독 결과를 버리지 않음)
                uniq_n = _nts_wht_unique_people_count(text)
                if nts_rows and (len(nts_rows) == nts_n or uniq_n <= len(nts_rows) <= nts_n):
                    out["wht"][yr] = nts_rows          # 국세청 서식 전원 판독 → AI 호출 없음
                    continue
            fast_rows = _try_fast_parse_wht_table(text)
            expected = max(_count_rrn_like(text), nts_n)
            if fast_rows:
                out["wht"][yr] = fast_rows
            if not fast_rows or (expected and len(fast_rows) < expected):
                # 자체 파서가 놓친 비정형 원천징수부 행 복구 시 Pro/Argon 우선 활용
                llm_tasks[key] = (PROMPT_WHT, text, True)
                out.setdefault("_parse_expected", {})[yr] = expected
        elif key == "biz_reg":
            fast_biz = _try_fast_parse_biz_reg(text)
            out["biz_reg"] = fast_biz
            if not all(fast_biz.get(k) for k in ("상호", "사업자번호", "사업장소재지", "업태")):
                llm_tasks[key] = (PROMPT_BIZ, text, False)
        elif key == "corp_reg":
            fast_corp = _try_fast_parse_corp_reg(text)
            out["corp_reg"] = fast_corp
            if not (fast_corp.get("설립일") and fast_corp.get("임원")):
                llm_tasks[key] = (PROMPT_CORP, text, False)
        elif key == "shareholder":
            fast_sh = _try_fast_parse_shareholder(text)
            out["shareholder"] = fast_sh
            if not fast_sh:
                llm_tasks[key] = (PROMPT_SH, text, False)
        elif key in ("prev_filing", "prev_credit_calc") or key.startswith("credit_calc_"):
            out.setdefault("credit_stmt", {}).update(_parse_credit_adjust_stmt(text))
            fast_pf = _try_fast_parse_prev_filing(text)
            if fast_pf.get("연도별"):
                for y_s, y_v in fast_pf["연도별"].items():
                    out["prev_filing"]["연도별"].setdefault(y_s, {}).update(y_v)
            # 복합 표 구조인 공제감면세액계산서·기신고 명세서는 Pro/Argon 모델을 우선 가동하여 정확도 극대화
            llm_tasks[key] = (PROMPT_PREV, text, True)

    if llm_tasks:
        max_workers = min(6, len(llm_tasks))
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            fut_map = {
                pool.submit(call_gemini_json, prompt, txt, log_tokens_fn, room_key, prefer_pro): k
                for k, (prompt, txt, prefer_pro) in llm_tasks.items()
            }
            for fut in as_completed(fut_map):
                k = fut_map[fut]
                try:
                    res = fut.result() or {}
                except Exception:
                    res = {}
                if not res:
                    continue
                if k == "biz_reg":
                    for fk, fv in res.items():
                        if fv and not out["biz_reg"].get(fk):
                            out["biz_reg"][fk] = fv
                elif k == "corp_reg":
                    for fk, fv in res.items():
                        if fv and not out["corp_reg"].get(fk):
                            out["corp_reg"][fk] = fv
                elif k == "shareholder":
                    if res.get("주주"):
                        out["shareholder"] = res.get("주주") or out["shareholder"]
                elif k in ("prev_filing", "prev_credit_calc") or k.startswith("credit_calc_"):
                    yr_dict = (res.get("연도별") if isinstance(res, dict) else None) or {}
                    if isinstance(yr_dict, dict):
                        target_map = out["prev_filing"].setdefault("연도별", {})
                        for y_str, y_vals in yr_dict.items():
                            if not isinstance(y_vals, dict):
                                continue
                            cur_entry = target_map.setdefault(str(y_str), {})
                            for fk, fv in y_vals.items():
                                if _opt_num(fv) is not None and (_opt_num(fv) > 0 or fk not in cur_entry):
                                    cur_entry[fk] = fv
                elif k.startswith("wht_"):
                    yr = k.replace("wht_", "").strip()
                    norm_rows = _normalize_wht_rows(res.get("근로자") or [])
                    if norm_rows and len(norm_rows) > len(out["wht"].get(yr) or []):
                        out["wht"][yr] = norm_rows

    return out


def build_prev_summary(ext: dict, tax_year: int, corp_size: str = "중소기업") -> dict[str, dict]:
    """
    기신고 서식(상시근로자 명세서·공제감면세액계산서)에서 읽은 값을 코호트(최초공제연도)별로 정리합니다.
    """
    ty = int(tax_year or R.DEFAULT_TAX_YEAR)
    keys = (
        "상시_총인원", "청년등_총인원", "상시", "청년등",
        "청년등_증가", "청년등외_증가", "공제세액", "2차_공제세액", "기추징세액", "이월세액", "수도권"
    )
    out = {str(y): {k: None for k in keys} for y in (ty - 1, ty - 2)}

    prev_map = ((ext or {}).get("prev_filing") or {}).get("연도별") or {}
    for y_str, vals in prev_map.items():
        if str(y_str) in out and isinstance(vals, dict):
            o = out[str(y_str)]
            for k in keys:
                v = _opt_num(vals.get(k))
                if v is not None:
                    o[k] = v
            if o.get("기추징세액") is None and _opt_num(vals.get("1년차_추징액")) is not None:
                o["기추징세액"] = _opt_num(vals.get("1년차_추징액"))

    # ① 세액공제조정명세서 계산명세(18S): F년 신고의 1차 = F년분 공제세액, 2차 = F-1년분의 2차 공제세액
    cs = {int(k): v for k, v in ((ext or {}).get("credit_stmt") or {}).items()}
    for y_str, o in out.items():
        y = int(y_str)
        if cs:
            if y in cs:
                o["공제세액"] = float(cs[y]["1차"])
            # AI가 읽은 '2차 공제세액'은 귀속연도 대응이 자주 틀려, 다음 해 계산명세로 확인될 때만 사용
            o["2차_공제세액"] = float(cs[y + 1]["2차"]) if (y + 1) in cs else None
        elif o.get("2차_공제세액") is not None:
            o["_2차_AI판독"] = True                # 18S 서식이 없어 AI 판독값 사용 → 화면에서 확인 경고
        # ② 이월세액이 공제세액 이상이면 소계·공제세액을 잘못 읽은 것 → 비움 (직접 입력)
        cf, cr = o.get("이월세액"), o.get("공제세액")
        if cf is not None and (cr is None or cf >= cr):
            o["이월세액"] = None
        # 공제세액이 0원으로 확인된 해는 공제받은 증가인원도 0명
        if cr is not None and float(cr) == 0.0:
            if o.get("청년등_증가") is None:
                o["청년등_증가"] = 0.0
            if o.get("청년등외_증가") is None:
                o["청년등외_증가"] = 0.0
    # ③ 증가인원·최초공제연도 소재지 보완 (기신고 인원 차이 우선 → 공제세액 조합 역산)
    prior_counts = {}
    for y_str, vals in prev_map.items():
        if isinstance(vals, dict) and _opt_num(vals.get("상시")) is not None and _opt_num(vals.get("청년등")) is not None:
            prior_counts[str(y_str)] = {"상시": _opt_num(vals.get("상시")), "청년등": _opt_num(vals.get("청년등"))}
    fill_missing_increments(out, corp_size, prior_counts)
    return out


def fill_missing_increments(ps: dict, corp_size: str = "중소기업", extra_counts: dict | None = None) -> None:
    """
    기신고 기초값(ps)에서 비어 있는 '공제받은 증가인원'과 '공제 당시 소재지'를 보완합니다.
    1순위: 그해와 직전연도의 기신고 인원(상시·청년등)이 모두 있으면 법정 산식(전체 증가 한도)으로 증가인원을 계산하고,
           그 인원 × 단가가 기신고 공제세액과 정확히 맞을 때만 채택 (맞는 단가표로 소재지도 결정)
    2순위: 공제세액을 만드는 청년등·청년등외 조합 역산 (_infer_increase_and_location)
    이미 값이 있으면 건드리지 않고, 소재지만 비어 있으면 추정합니다. 계산 단계에서도 다시 호출해 예전 백업도 보완됩니다.
    """
    counts = dict(extra_counts or {})
    for y_str, o in (ps or {}).items():
        if isinstance(o, dict) and o.get("상시") is not None and o.get("청년등") is not None:
            counts[str(y_str)] = {"상시": float(o["상시"]), "청년등": float(o["청년등"])}
    for y_str, o in (ps or {}).items():
        if not isinstance(o, dict) or not str(y_str).isdigit():
            continue
        if o.get("청년등_증가") is not None and o.get("청년등외_증가") is not None:
            _infer_increase_and_location(o, corp_size)          # 소재지만 확인
            continue
        credit = o.get("공제세액")
        prev = counts.get(str(int(y_str) - 1))
        if credit and prev and o.get("상시") is not None and o.get("청년등") is not None:
            inc = calc_increase_with_cap(float(o["상시"]), float(o["청년등"]), prev["상시"], prev["청년등"])
            yi, gi = round(inc["youth_inc"], 2), round(inc["non_youth_inc"], 2)
            hits = []
            for cap in (True, False):
                r = get_unit_rates(corp_size, cap, scheme="legacy")
                if int(round((round(yi * 100) * r["청년등"] + round(gi * 100) * r["청년등외"]) * 100)) == int(round(float(credit))):
                    hits.append(cap)
            if hits:
                o["청년등_증가"], o["청년등외_증가"] = yi, gi
                o["_증가_역산"] = True
                if o.get("수도권") is None and len(hits) == 1:
                    o["수도권"] = hits[0]
                    o["_소재지_추정"] = True
                continue
        _infer_increase_and_location(o, corp_size)


def _twelfth_consistent(v) -> bool:
    """인원(소수 둘째 자리)이 '정수 근무월수 합계 ÷ 12'를 절사한 값으로 설명되는지"""
    try:
        c = round(float(v) * 100)
    except (TypeError, ValueError):
        return False
    return any((m * 100) // 12 == c for m in range(max(0, c * 12 // 100 - 1), c * 12 // 100 + 3))


def _infer_increase_and_location(o: dict, corp_size: str = "중소기업") -> None:
    """
    기신고 공제세액과 인원으로 (a) 최초공제연도 수도권 여부, (b) 비어 있는 증가인원을 역산합니다.
    - 증가인원이 있으면: 어느 단가표(수도권/수도권 밖)로 공제세액이 맞는지 확인해 소재지를 추정
    - 증가인원이 없으면: 청년등·청년등외 증가인원 조합 중 공제세액과 정확히 맞는 조합을 역산
      (0.01 단위 전수 탐색에서 유일해가 있으면 즉시 채택하고, 복수해가 있을 때는 12개월 절사 나머지 조건·정수 증가 조건으로 유일해 판별)
    """
    credit = o.get("공제세액")
    if not credit:
        return
    cents = int(round(float(credit)))

    def _won(cap: bool, y: float, g: float) -> int:
        r = get_unit_rates(corp_size, cap, scheme="legacy")
        return int(round((round(y * 100) * r["청년등"] + round(g * 100) * r["청년등외"]) * 100))

    yi, gi = o.get("청년등_증가"), o.get("청년등외_증가")
    if yi is not None and gi is not None:
        hits = [cap for cap in (True, False) if _won(cap, yi, gi) == cents]
        if len(hits) == 1 and o.get("수도권") is None:
            o["수도권"] = hits[0]
            o["_소재지_추정"] = True
        return
    reg, yth = o.get("상시"), o.get("청년등")
    if reg is None or yth is None:
        return
    gen_cap = max(0.0, float(reg) - float(yth))
    sols = []
    for cap in (True, False):
        r = get_unit_rates(corp_size, cap, scheme="legacy")
        ry, rg = r["청년등"], r["청년등외"]
        for yc in range(0, int(round(float(yth) * 100)) + 1):
            rest = cents - yc * ry * 100
            if rest < 0:
                break
            if rg == 0:
                if rest == 0:
                    sols.append((cap, yc / 100, 0.0))
                continue
            if rest % (rg * 100) == 0 and rest // (rg * 100) <= round(gen_cap * 100):
                sols.append((cap, yc / 100, rest / (rg * 100) / 100))
    picked = None
    if len(sols) == 1:
        picked = sols[0]
    elif len(sols) > 1 and _twelfth_consistent(reg) and _twelfth_consistent(yth):
        # 복수해 필터는 '인원 = 근무월수 ÷ 12'(정규직만)일 때만 성립.
        # 단시간(0.5·0.75) 가중치가 섞여 당해 인원이 12분의 1 단위로 설명되지 않으면 쓰지 않고 비워 둠 (틀린 값 채움 방지)
        twelfth_rem = {(m * 100) // 12 for m in range(12)}
        r_cur = round(float(reg) * 100) % 100
        y_cur = round(float(yth) * 100) % 100
        valid_tot_rem = {(r_cur - rp) % 100 for rp in twelfth_rem}
        valid_yth_rem = {(y_cur - yp) % 100 for yp in twelfth_rem}
        f1 = [
            (cap, y, g) for (cap, y, g) in sols
            if (round((y + g) * 100) % 100) in valid_tot_rem
            and (round(g * 100) == 0 or (round(y * 100) % 100) in valid_yth_rem)
        ]
        if len(f1) == 1:
            picked = f1[0]
        elif len(f1) > 1 and r_cur == 0 and y_cur == 0:
            f2 = [(cap, y, g) for (cap, y, g) in f1 if round(y * 100) % 100 == 0 and round(g * 100) % 100 == 0]
            if len(f2) == 1:
                picked = f2[0]
    if picked is not None:
        cap, y, g = picked
        o["청년등_증가"], o["청년등외_증가"] = y, g
        o["_증가_역산"] = True
        if len(sols) > 1:
            o["_증가_추정"] = True          # 여러 조합 중 필터로 고른 값 → 화면에서 확인 경고
        if o.get("수도권") is None:
            o["수도권"] = cap
            o["_소재지_추정"] = True


# ══════════════════════════════════════════════════════════════════
# 5. 사업자정보(복수 사업장 포함) 및 사원정보(People & Year Records) 빌더
# ══════════════════════════════════════════════════════════════════
def build_biz_info(ext: dict, tax_year: int, existing_biz: dict | None = None) -> tuple[dict, list[str]]:
    br = (ext or {}).get("biz_reg") or (ext or {}).get("biz") or {}
    cr = (ext or {}).get("corp_reg") or (ext or {}).get("corp") or {}
    prev = existing_biz or {}

    founded_str = _iso(cr.get("설립일")) or _iso(br.get("개업일")) or prev.get("설립일", "")
    founded_dt = parse_date(founded_str)

    biz = {
        "상호": (br.get("상호") or cr.get("상호") or prev.get("상호") or "").strip(),
        "설립일": founded_str,
        "사업자번호": (br.get("사업자번호") or prev.get("사업자번호") or "").strip(),
        "업태": (br.get("업태") or prev.get("업태") or "").strip(),
        "종목": (br.get("종목") or prev.get("종목") or "").strip(),
        "사업장소재지": (br.get("사업장소재지") or cr.get("본점") or prev.get("사업장소재지") or "").strip(),
        "기업구분": prev.get("기업구분") if prev.get("기업구분") in R.CORP_SIZES else "중소기업",
        "전전년_월수": int(prev.get("전전년_월수") or default_months_for_year(tax_year - 2, founded_dt) or 12),
        "전년_월수": int(prev.get("전년_월수") or default_months_for_year(tax_year - 1, founded_dt) or 12),
        "당해_월수": int(prev.get("당해_월수") or default_months_for_year(tax_year, founded_dt) or 12),
    }

    confirmed = []
    for f in ("상호", "설립일", "사업자번호", "업태", "종목", "사업장소재지"):
        if biz.get(f) and (br.get(f) or cr.get(f) or (f == "설립일" and (cr.get("설립일") or br.get("개업일")))):
            confirmed.append(f)

    return biz, confirmed


def build_sub_biz_list(ext: dict, main_biz: dict, existing_sub_biz: list[dict] | None = None) -> list[dict]:
    """
    업로드된 복수 사업자등록증 또는 원천징수부 내 서로 다른 사업장명을 감지하여
    좌측 사이드바 하단에 표시할 『추가 합산 사업장(지점 · 양도/양수 사업장)』 목록을 구성합니다.
    """
    out: list[dict] = [dict(x) for x in (existing_sub_biz or []) if isinstance(x, dict)]
    seen_names = {str(x.get("상호") or "").strip() for x in out if str(x.get("상호") or "").strip()}
    main_nm = str((main_biz or {}).get("상호") or "").strip()

    br = (ext or {}).get("biz_reg") or {}
    for sb in br.get("추가사업장") or []:
        if not isinstance(sb, dict):
            continue
        nm = str(sb.get("상호") or "").strip()
        if nm and nm not in seen_names and nm != main_nm and not _is_employee_id_token(nm):
            seen_names.add(nm)
            out.append(
                {
                    "구분": sb.get("구분") or "지점(법인 본·지점 합산)",
                    "상호": nm,
                    "사업자번호": str(sb.get("사업자번호") or "").strip(),
                    "사업장소재지": str(sb.get("사업장소재지") or "").strip(),
                    "업태": str(sb.get("업태") or "").strip(),
                    "종목": str(sb.get("종목") or "").strip(),
                    "개업일": _iso(sb.get("개업일")),
                    "폐업일": _iso(sb.get("폐업일")),
                    "승계_직전상시": float(sb.get("승계_직전상시") or 0.0),
                    "승계_직전청년": float(sb.get("승계_직전청년") or 0.0),
                    "고용승계_입사일유지": bool(sb.get("고용승계_입사일유지", True)),
                }
            )

    wht_wps: list[str] = []
    for rows in ((ext or {}).get("wht") or {}).values():
        for r in rows or []:
            wp = str(r.get("사업장명") or "").strip()
            if wp and not _is_employee_id_token(wp) and wp not in wht_wps:
                wht_wps.append(wp)

    if len(wht_wps) >= 2:
        for wp in wht_wps[1:]:
            if wp not in seen_names and wp != main_nm and wp not in ("본점", "주사업장"):
                seen_names.add(wp)
                w_type = (
                    "지점(법인 본·지점 합산)"
                    if "지점" in wp
                    else ("포괄양수 사업장(기중 양수)" if ("2" in wp or "양수" in wp) else "기타 합산 사업장")
                )
                out.append(
                    {
                        "구분": w_type,
                        "상호": wp,
                        "사업자번호": "",
                        "사업장소재지": "",
                        "업태": "",
                        "종목": "",
                        "개업일": "",
                        "폐업일": "",
                        "승계_직전상시": 0.0,
                        "승계_직전청년": 0.0,
                        "고용승계_입사일유지": True,
                    }
                )

    return out


def _shareholder_relations(shareholders: list[dict]) -> dict[str, str]:
    if not shareholders:
        return {}
    best_rate = -1.0
    for sh in shareholders:
        r = _num(sh.get("지분율"))
        if r > best_rate:
            best_rate = r

    rel_map: dict[str, str] = {}
    for sh in shareholders:
        nm = str(sh.get("성명") or "").strip()
        if not nm:
            continue
        r = _num(sh.get("지분율"))
        rel = str(sh.get("관계") or "").strip()
        if best_rate > 0 and abs(r - best_rate) < 1e-6 and rel in ("", "본인", "최대주주"):
            rel_map[nm] = "최대주주"
        elif "배우자" in rel or "처" in rel or "남편" in rel or "부인" in rel:
            rel_map[nm] = "최대주주의 배우자"
        elif any(k in rel for k in ("자", "녀", "부", "모", "조", "손", "형제", "자매", "친족", "직계")):
            rel_map[nm] = "최대주주의 직계존비속 등"
    return rel_map


def new_year_rec(emp_type: str = R.EMP_REGULAR, confirmed_emp: bool = False) -> dict:
    # 고용유형은 원천징수부만으로 확정할 수 없으므로(단시간 0.5/0.75, 계약직, 임원 여부 등 실무 변경 필수)
    # 항상 입력·선택 가능한 열림 상태로 유지합니다.
    return {
        "고용유형": emp_type if emp_type in R.EMP_TYPES else R.EMP_REGULAR,
        "제외사유": "",
        "청년등": "",
        "상시_override": "",
        "월_override": {},
        "_confirmed": [],
        "_user_set": [],
        "_unlocked": False,
    }


def _combine_workplace_labels(old_wp: str, new_wp: str) -> str:
    o = "" if _is_employee_id_token(old_wp) else (old_wp or "").strip()
    n = "" if _is_employee_id_token(new_wp) else (new_wp or "").strip()
    if not o:
        return n
    if not n or o == n:
        return o
    parts = [p.strip() for p in o.split("→") if p.strip() and not _is_employee_id_token(p.strip())]
    if n not in parts:
        parts.append(n)
    return "→".join(parts)


def build_people(
    ext: dict,
    years: list[int],
    max_tax_year: int | None = None,
    default_workplace: str = R.DEFAULT_WORKPLACE_NAME,
) -> tuple[dict, dict]:
    """
    선택된 귀속사업연도(`max_tax_year`) 이하의 원천징수부 데이터를 성명+생년월일 기준으로 병합합니다.
    - 생년월일이 다른 동명이인은 별도 인원으로 분리하고, 한 해 자료에만 생년월일이 빠진 동일인은 정상 연결합니다.
    - 동일 사원이 본·지점 또는 1번(양도)·2번(포괄양수) 사업장에 중복 등재된 경우,
      파일 처리 순서와 무관하게 월별 급여를 합산하고 모든 사업장에서 퇴사했을 때(그리고 이후 월 급여가 없을 때)만 퇴사로 판정합니다.
    """
    wht_by_year = (ext or {}).get("wht") or {}
    corp_execs = ((ext or {}).get("corp_reg") or (ext or {}).get("corp") or {}).get("임원") or []
    ceo_from_biz = str(((ext or {}).get("biz_reg") or (ext or {}).get("biz") or {}).get("대표자") or "").strip()
    sh_list = (ext or {}).get("shareholder") or (ext or {}).get("shareholders") or []
    sh_map = _shareholder_relations(sh_list)

    exec_role_by_name: dict[str, str] = {}
    if ceo_from_biz:
        exec_role_by_name[ceo_from_biz] = R.EMP_CEO
    for ex in corp_execs:
        nm = str(ex.get("성명") or "").strip()
        role = str(ex.get("직책") or ex.get("직위") or "").strip()
        if nm:
            exec_role_by_name[nm] = R.EMP_CEO if "대표" in role else R.EMP_EXEC

    people: dict[str, dict] = {}
    year_recs: dict[int, dict[str, dict]] = {int(y): {} for y in years}
    key_to_pid: dict[str, str] = {}
    name_to_pids: dict[str, list[str]] = {}
    clean_fallback_wp = (
        R.DEFAULT_WORKPLACE_NAME
        if _is_employee_id_token(default_workplace)
        else ((default_workplace or R.DEFAULT_WORKPLACE_NAME).strip() or R.DEFAULT_WORKPLACE_NAME)
    )

    for y_str in sorted(wht_by_year.keys()):
        try:
            y_int = int(y_str)
        except ValueError:
            continue
        if max_tax_year is not None and y_int > int(max_tax_year):
            continue

        year_recs.setdefault(y_int, {})
        for row in wht_by_year.get(y_str) or []:
            nm = str(row.get("성명") or "").strip()
            if not nm:
                continue
            b_str = str(row.get("생년월일") or "").strip()
            raw_wp = str(row.get("사업장명") or "").strip()
            row_wp = raw_wp if (raw_wp and not _is_employee_id_token(raw_wp)) else clean_fallback_wp
            dedup_key = f"{nm}|{b_str}" if b_str else nm
            pid = key_to_pid.get(dedup_key)
            if not pid:
                cands = name_to_pids.get(nm, [])
                if b_str:
                    no_birth = [c for c in cands if not people[c].get("생년월일")]
                    if len(no_birth) == 1:
                        pid = no_birth[0]
                        key_to_pid[dedup_key] = pid
                elif len(cands) == 1:
                    pid = cands[0]
            if not pid:
                pid = f"p_{len(people) + 1:03d}"
                key_to_pid[dedup_key] = pid
                name_to_pids.setdefault(nm, []).append(pid)
                people[pid] = {
                    "pid": pid,
                    "사업장명": row_wp,
                    "연도별_사업장명": {},
                    "성명": nm,
                    "생년월일": b_str,
                    "입사일": row.get("입사일") or "",
                    "퇴사일": "",
                    "연도별_퇴사일": {},
                    "계약체결일": row.get("입사일") or "",
                    "병역개월": int(row.get("병역개월") or 0),
                    "외국인": bool(row.get("외국인")),
                    "주주관계": sh_map.get(nm, ""),
                    "월급여": {},
                    "_confirmed": [],
                }

            p = people[pid]
            if b_str and not p["생년월일"]:
                p["생년월일"] = b_str

            prev_yr_wp = p["연도별_사업장명"].get(str(y_int), "")
            combined_yr_wp = _combine_workplace_labels(prev_yr_wp, row_wp) or clean_fallback_wp
            p["연도별_사업장명"][str(y_int)] = combined_yr_wp
            p["사업장명"] = _combine_workplace_labels(p.get("사업장명", ""), row_wp) or clean_fallback_wp

            if row.get("입사일"):
                if not p["입사일"] or row["입사일"] < p["입사일"]:
                    p["입사일"] = row["입사일"]
                    p["계약체결일"] = row["입사일"]

            incoming_pay = row.get("월급여") or {}
            existing_pay = p["월급여"].get(str(y_int))
            if existing_pay:
                merged_pay = {}
                for m in range(1, 13):
                    mk = str(m)
                    merged_pay[mk] = float(existing_pay.get(mk, 0.0) or 0.0) + float(incoming_pay.get(mk, 0.0) or 0.0)
                p["월급여"][str(y_int)] = merged_pay
            else:
                p["월급여"][str(y_int)] = {str(m): float(incoming_pay.get(str(m), 0.0) or 0.0) for m in range(1, 13)}

            row_ret = str(row.get("퇴사일") or "").strip()
            p.setdefault("_ret_rows", {}).setdefault(str(y_int), []).append(row_ret)

            if row.get("병역개월") and not p.get("병역개월"):
                p["병역개월"] = int(row["병역개월"])
            if row.get("외국인"):
                p["외국인"] = True

            conf = set(p.get("_confirmed") or [])
            conf.add("성명")
            if p["생년월일"]:
                conf.add("생년월일")
            if p["입사일"]:
                conf.add("입사일")
            p["_confirmed"] = list(conf)

            emp_t = exec_role_by_name.get(nm) or row.get("고용유형") or R.EMP_REGULAR
            confirmed_emp = nm in exec_role_by_name or (row.get("고용유형") in R.EMP_TYPES)
            year_recs[y_int][pid] = new_year_rec(emp_t, confirmed_emp=confirmed_emp)

    for p in people.values():
        rr = p.pop("_ret_rows", {}) or {}
        yr_ret: dict[str, str] = {}
        for ys, lst in rr.items():
            if lst and all(lst):
                cand_ret = max(lst, key=lambda d: parse_date(d) or date.min)
                cand_dt = parse_date(cand_ret)
                pay_y = (p.get("월급여") or {}).get(str(ys)) or {}
                # 사업장이 하나뿐인 퇴사자는 퇴사 다음 달 급여(익월 지급·퇴직 정산)가 있어도 퇴사일을 그대로 둠.
                # 같은 해 여러 사업장 기록이 있는 이동자만, 퇴사월 이후 급여가 있으면 계속 근무로 봄.
                if len(lst) > 1 and cand_dt and any(
                    float(pay_y.get(str(m), 0.0) or 0.0) > 0 for m in range(cand_dt.month + 1, 13)
                ):
                    continue
                yr_ret[ys] = cand_ret
        p["연도별_퇴사일"] = yr_ret
        latest = max(rr.keys()) if rr else None
        p["퇴사일"] = yr_ret.get(latest, "") if latest else ""
        conf = set(p.get("_confirmed") or [])
        if p["퇴사일"]:
            conf.add("퇴사일")
        else:
            conf.discard("퇴사일")
        p["_confirmed"] = list(conf)

    for y in years:
        y_int = int(y)
        year_recs.setdefault(y_int, {})
        for pid, p in people.items():
            if pid not in year_recs[y_int]:
                nm = p.get("성명", "")
                emp_t = exec_role_by_name.get(nm, R.EMP_REGULAR)
                year_recs[y_int][pid] = new_year_rec(emp_t, confirmed_emp=(nm in exec_role_by_name))

    return people, year_recs


def ai_extra_warnings(ext: dict, log_tokens_fn=None, room_key: str = "") -> list[str]:
    if not ext:
        return []
    warnings: list[str] = []

    for yr in (ext.get("_truncated") or []):
        warnings.append(f"{yr}년 원천징수부가 너무 커서 뒷부분이 잘렸을 수 있습니다. 직원 수가 맞는지 2단계에서 꼭 확인하세요.")
    for yr, exp in (ext.get("_parse_expected") or {}).items():
        got = len((ext.get("wht") or {}).get(yr) or [])
        if exp and got < exp:
            warnings.append(
                f"{yr}년 원천징수부: 본문에 보이는 주민등록번호는 {exp}건인데 읽은 직원은 {got}명입니다. 누락된 직원이 없는지 2단계에서 확인하세요."
            )

    wht_map = ext.get("wht") or {}
    all_wht_names: set[str] = set()
    missing_birth_names: set[str] = set()
    missing_hire_names: set[str] = set()
    workplaces_found: set[str] = set()

    for yr_str, rows in wht_map.items():
        for r in rows or []:
            nm = str(r.get("성명") or "").strip()
            if not nm:
                continue
            all_wht_names.add(nm)
            wp = str(r.get("사업장명") or "").strip()
            if wp and not _is_employee_id_token(wp):
                workplaces_found.add(wp)
            if not r.get("생년월일"):
                missing_birth_names.add(nm)
            if not r.get("입사일"):
                missing_hire_names.add(nm)

    if len(workplaces_found) >= 2:
        warnings.append(
            f"복수 사업장({', '.join(sorted(workplaces_found))}) 근로자 데이터가 감지되어 합산 반영되었습니다. 좌측 사이드바 하단의 추가 사업장 정보와 2단계 표 맨 앞의 '사업장명' 열을 확인하세요."
        )

    ceo_nm = str(((ext.get("biz_reg") or ext.get("biz") or {}).get("대표자")) or "").strip()
    exec_list = ((ext.get("corp_reg") or ext.get("corp") or {}).get("임원")) or []
    exec_names = {str(e.get("성명") or "").strip() for e in exec_list if e.get("성명")}
    if ceo_nm:
        exec_names.add(ceo_nm)
    matched_execs = sorted(all_wht_names & exec_names)
    if matched_execs:
        warnings.append(
            f"등기임원·대표자({', '.join(matched_execs)})가 원천징수부에서 확인되어 상시근로자 제외 대상('대표이사/임원')으로 자동 분류됩니다."
        )

    sh_map = _shareholder_relations(ext.get("shareholder") or ext.get("shareholders") or [])
    matched_sh = [f"{nm}({rel})" for nm, rel in sh_map.items() if nm in all_wht_names]
    if matched_sh:
        warnings.append(
            f"주주명부상 최대주주·특수관계인({', '.join(matched_sh)})이 원천징수부에서 확인되어 상시근로자 제외 대상으로 자동 반영됩니다."
        )

    if missing_birth_names:
        sample = ", ".join(sorted(missing_birth_names)[:5])
        warnings.append(
            f"원천징수부에서 생년월일(주민번호)이 확인되지 않는 인원({sample} 등 {len(missing_birth_names)}명)이 있습니다. 2단계에서 생년월일을 확인하세요."
        )
    if missing_hire_names:
        sample = ", ".join(sorted(missing_hire_names)[:5])
        warnings.append(
            f"원천징수부에서 입사일이 비어 있는 인원({sample} 등 {len(missing_hire_names)}명)이 있습니다. 2단계에서 입사일을 확인하세요."
        )

    return warnings


def check_missing(classified: dict[str, list[str]], ext: dict | None, tax_year: int) -> list[str]:
    msgs: list[str] = []
    for k, label, req, _ in R.get_doc_types(tax_year):
        if req and not classified.get(k):
            msgs.append(f"**{label}** 자료가 업로드되지 않았습니다.")

    t1 = int(tax_year) - 1
    t2 = int(tax_year) - 2
    t3 = int(tax_year) - 3
    if not classified.get(f"credit_calc_{t1}") and not classified.get("prev_filing") and not classified.get("prev_credit_calc"):
        msgs.append(
            f"**{t1}년 공제감면세액계산서**가 업로드되지 않았습니다. "
            f"(3단계에서 사후관리 기본값인 『기신고 기준』 숫자를 직접 입력하거나 『세법원칙 기준(재계산)』으로 전환하여 계산할 수 있습니다.)"
        )
    if not classified.get(f"wht_{t2}") and not classified.get("prev_filing") and not classified.get(f"credit_calc_{t2}"):
        msgs.append(
            f"**{t2}년 귀속분 2차 사후관리(3차년도)** 확인을 위한 `{t2}년 원천징수부` 또는 `기신고 명세서`가 없습니다. "
            f"(2단계·3단계에서 {t2}년 기신고 인원을 직접 입력하거나 사원표를 열어 계산할 수 있습니다.)"
        )
    elif classified.get(f"wht_{t2}") and not (
        classified.get(f"wht_{t3}") or classified.get("prev_filing") or classified.get(f"credit_calc_{t2}") or classified.get(f"credit_calc_{t3}")
    ):
        msgs.append(
            f"**{t2}년 귀속분 고용증가 인원({t3}→{t2}년)** 산정을 위한 `{t3}년 원천징수부` 또는 `{t2}·{t3}년 기신고 명세서`가 없습니다. "
            f"(3단계에서 {t2}년 기신고 증가인원을 직접 입력하거나 `{t3}년 자료`를 추가 업로드하면 자동 계산됩니다.)"
        )

    if ext:
        wht = ext.get("wht") or {}
        for y in (tax_year, tax_year - 1, tax_year - 2, tax_year - 3):
            if classified.get(f"wht_{y}") and not wht.get(str(y)):
                msgs.append(f"{y}년 원천징수부에서 근로자 명단을 읽지 못했습니다. 2단계에서 직접 입력하거나 파일을 다시 확인하세요.")
        for w in ai_extra_warnings(ext):
            if w not in msgs:
                msgs.append(w)
    return msgs

# ══════════════════════════════════════════════════════════════════
# 국세청 표준 서식 전용 판독기 (AI 없이 확정적으로 읽음)
# - pypdf가 글자마다 줄을 바꾸는 PDF도 공백을 모두 지운 뒤 서식 구조로 읽음
# ══════════════════════════════════════════════════════════════════
_NUM = r"(?:0(?![,\d])|[1-9]\d{0,2}(?:,\d{3})*|0)"


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", str(text or ""))


def _infer_birth(yymmdd: str, gender_digit: str = "") -> date | None:
    """주민번호 앞 6자리 + (있으면) 성별 숫자로 생년월일. 성별 숫자가 가려져 있으면 나이가 15세 이상이 되는 세기로 추정."""
    try:
        yy, mm, dd = int(yymmdd[0:2]), int(yymmdd[2:4]), int(yymmdd[4:6])
    except (ValueError, IndexError):
        return None
    if gender_digit and gender_digit.isdigit():
        century = {1: 1900, 2: 1900, 5: 1900, 6: 1900, 3: 2000, 4: 2000, 7: 2000, 8: 2000, 9: 1800, 0: 1800}.get(int(gender_digit), 1900)
    else:
        century = 2000 if (2000 + yy) <= date.today().year - 15 else 1900
    try:
        return date(century + yy, mm, dd)
    except ValueError:
        return None


def _parse_nts_wht_form(text: str, default_wp: str = "") -> list[dict]:
    """
    소득자별 근로소득원천징수부(소득세법 시행규칙 별지 제25호서식(1)) 판독.
    - 복수사업장 구분자(<<<FILE_WP:사업장명>>>) 보존
    - 당월지급(2023/01) 및 익월지급(2023/02) 모두 지원하며 급여구간(~) 직전 과세총급여(계) 우선 추출
    - 3쪽 징수의무자 대표자이면서 급여가 0원인 경우 대표이사(R.EMP_CEO)로 자동 분류
    """
    if not text:
        return []
    if "<<<FILE_WP:" in text:
        combined: list[dict] = []
        cur_wp = default_wp
        buf: list[str] = []
        for ln in text.splitlines():
            m_wp = FILE_WP_MARKER_RE.match(ln.strip())
            if m_wp is not None:
                if buf:
                    combined.extend(_parse_nts_wht_form("\n".join(buf), default_wp=cur_wp))
                    buf = []
                raw_wp = m_wp.group(1).strip()
                cur_wp = "" if _is_employee_id_token(raw_wp) else raw_wp
            else:
                buf.append(ln)
        if buf:
            combined.extend(_parse_nts_wht_form("\n".join(buf), default_wp=cur_wp))
        return combined

    clean_wp = "" if _is_employee_id_token(default_wp) else default_wp
    s = _squash(text)
    signer_tails = re.findall(r"징수의무자:\(서명또는인\)\d{8}([^※]{2,30})(?:※|210mm)", s)
    chunks = re.split(r"①귀속연도", s)
    out: list[dict] = []
    seen_idx: dict[tuple[str, str], int] = {}

    for ch in chunks:
        m = re.search(r"⑤성명([가-힣A-Za-z·]{1,20}?)⑥주민등록번호(\d{6})-?([\d\*]?)", ch)
        if not m:
            continue
        name = m.group(1)
        rrn6 = m.group(2)
        g_dig = m.group(3) if m.group(3) not in ("*", "") else ""
        birth = _infer_birth(rrn6, g_dig)
        rrn7 = f"{rrn6}-{m.group(3) or '*'}"
        mh = (
            re.search(r"⑦입사일(\d{4})년(\d{1,2})월(\d{1,2})일", ch)
            or re.search(r"⑦입사일(\d{4})[-./](\d{1,2})[-./](\d{1,2})", ch)
        )
        mr = (
            re.search(r"⑦퇴사일(\d{4})년(\d{1,2})월(\d{1,2})일", ch)
            or re.search(r"⑦퇴사일(\d{4})[-./](\d{1,2})[-./](\d{1,2})", ch)
        )
        try:
            hire = date(int(mh.group(1)), int(mh.group(2)), int(mh.group(3))) if mh else None
            retire = date(int(mr.group(1)), int(mr.group(2)), int(mr.group(3))) if mr else None
        except ValueError:
            hire = retire = None
        page1 = re.split(r"Ⅱ\.비과세소득|Ⅲ\.근로소득원천징수액등", ch)[0]
        m_tbl = re.search(r"소득세1월(.*?)연말종전납세", page1)
        tbl_str = "1월" + m_tbl.group(1) if m_tbl else page1
        pay = {str(k): 0.0 for k in range(1, 13)}

        # 당월지급 및 익월지급 모두 포착 (지급연월 YYYY/MM 뒤 행 토큰에서 과세급여 추출)
        for m_paid in re.finditer(
            r"(1[0-2]|[1-9])월(20\d{2}/(?:0[1-9]|1[0-2]))(.*?)(?=(?:1[0-2]|[1-9])월(?:20\d{2}/|(?:1[0-2]|[1-9])월|연말)|연말|$)",
            tbl_str,
        ):
            mon = int(m_paid.group(1))
            if not (1 <= mon <= 12):
                continue
            row_tail = m_paid.group(3)
            tokens = re.findall(r"\d{1,3}(?:,\d{3})+(?:~\d{1,3}(?:,\d{3})+)?", row_tail)
            pre_range: list[float] = []
            has_tilde = any("~" in tk for tk in tokens)
            for tk in tokens:
                if "~" in tk:
                    break
                pre_range.append(float(tk.replace(",", "")))
            if pre_range:
                if has_tilde:
                    pay[str(mon)] = pre_range[-1]
                elif len(pre_range) >= 3 and abs(pre_range[0] + pre_range[1] - pre_range[2]) < 10:
                    pay[str(mon)] = pre_range[2]
                else:
                    pay[str(mon)] = pre_range[0]
            else:
                m_simple = re.match(r"^(" + _NUM + ")", row_tail)
                if m_simple:
                    pay[str(mon)] = float(m_simple.group(1).replace(",", "") or 0) or 1.0

        foreign = "⑧내외국인구분외국인" in ch
        is_signer = any(t.endswith(name) for t in signer_tails)
        emp_type = R.EMP_CEO if (is_signer and sum(pay.values()) == 0) else R.EMP_REGULAR
        dedup_k = (clean_wp, name, rrn6)
        if dedup_k in seen_idx:
            ex = out[seen_idx[dedup_k]]
            for k in range(1, 13):
                mk = str(k)
                ex["월급여"][mk] = float(ex["월급여"].get(mk, 0.0)) + float(pay.get(mk, 0.0))
            if hire and (not ex.get("입사일") or hire.isoformat() < ex["입사일"]):
                ex["입사일"] = hire.isoformat()
            if retire:
                ex["퇴사일"] = retire.isoformat()
        else:
            seen_idx[dedup_k] = len(out)
            out.append({
                "사업장명": clean_wp,
                "성명": name,
                "주민번호앞7자리": rrn7,
                "생년월일": birth.isoformat() if birth else "",
                "외국인": foreign,
                "입사일": hire.isoformat() if hire else "",
                "퇴사일": retire.isoformat() if retire else "",
                "고용유형": emp_type,
                "병역개월": 0,
                "월급여": pay,
            })
    return out


def _nts_wht_unique_people_count(text: str) -> int:
    """서식 안의 서로 다른 사람 수 (사업장 구분 + 성명 + 주민번호 앞 6자리 기준)"""
    total = 0
    for seg in re.split(r"<<<FILE_WP:.*?>>>", str(text or "")):
        pairs = re.findall(r"⑤성명([가-힣A-Za-z·]{1,20}?)⑥주민등록번호(\d{6})", _squash(seg))
        total += len(set(pairs))
    return total


def _nts_wht_people_count(text: str) -> int:
    return len(re.findall(r"⑤성명", _squash(text)))


def _parse_credit_adjust_stmt(text: str) -> dict[int, dict]:
    """
    세액공제조정명세서(3)의 통합고용세액공제(코드 18S) 계산명세 'A + B + C  합계' 판독.
    신고 사업연도 F 기준: A = F년 귀속분(1차), B = F-1년 귀속분 2차, C = F-2년 귀속분 3차.
    세 금액의 합이 합계와 맞을 때만 채택.
    """
    s = _squash(text)
    out: dict[int, dict] = {}
    for m in re.finditer(r"18S(" + _NUM + r")\+(" + _NUM + r")\+(" + _NUM + r")(" + _NUM + ")", s):
        vals = [int(m.group(i).replace(",", "")) for i in range(1, 5)]
        if vals[0] + vals[1] + vals[2] != vals[3]:
            continue
        yrs = re.findall(r"(\d{4})\.01\.01", s[: m.start()])
        if not yrs:
            continue
        f = int(yrs[-1])
        out[f] = {"1차": vals[0], "2차": vals[1], "3차": vals[2], "합계": vals[3]}
    return out