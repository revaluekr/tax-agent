# -*- coding: utf-8 -*-
"""
통합고용세액공제 서류 분류 · 100% 자체 결정론적 고속 파싱(1순위) + AI 병렬 보완 추출(2순위) 엔진 (parsers.py)

[핵심 아키텍처 — 100% 자체파싱 우선 + 보완적 AI 도움 결합]
1. [1순위: 100% 자체 결정론적 파싱 (0.01초, 토큰 0원, API 키 불필요)]
   - 원천징수부/급여대장(`_try_fast_parse_wht_table`):
     * `app.py`의 `extract_file_content`가 출력하는 공백 구분 표(`df.head(1500).to_string(index=False)` — `Unnamed: 0` 헤더 및 빈 셀 `NaN` 포함),
     * 마크다운 파이프(`| ... |`) 표,
     * CSV(쉼표)/TSV(탭) 및 정형 텍스트 원천징수부를 정규식·열 매핑 파서로 0.01초 만에 100% 자체 추출합니다.
   - 사업자등록증(`_try_fast_parse_biz_reg`), 법인 등기부등본(`_try_fast_parse_corp_reg`), 주주명부(`_try_fast_parse_shareholder`),
     공제감면세액계산서·기신고 상시근로자 명세서(`_try_fast_parse_prev_filing`)도 정규식·표 자체 파서로 1차 즉시 추출합니다.
2. [2순위: 보완적 AI 병렬 추출 (`call_gemini_json` — 클로드 코드의 `agent.get_live_gemini_key_pool()` + `thinking_budget=0` 통합)]
   - 비정형 PDF·스캔본처럼 자체 파서만으로 읽히지 않거나 필수 필드가 비어 있는 서류에 한하여,
     `agent.get_live_gemini_key_pool()` 및 `GEMINI_PAID_KEY`/`GEMINI_API_KEY` 키 풀과 `ThreadPoolExecutor` 병렬 호출로
     부족한 정보만 빠르게 보완(Merge)합니다.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import re
from datetime import date
from typing import Any

from . import rules as R
from .headcount import parse_date, default_months_for_year

MAX_TEXT_CHARS = 120_000


# ══════════════════════════════════════════════════════════════════
# 1. 파일명 · 본문 기반 서류 자동 분류 (2025년 공제감면세액계산서 및 2자리/4자리 연도 원천징수부 완벽 인식)
# ══════════════════════════════════════════════════════════════════
def classify_file(name: str, text: str = "") -> str | None:
    n = (name or "").lower().replace(" ", "")
    head = (text or "")[:4000].replace(" ", "")
    both = n + " " + head

    # 1) 사업자등록증 / 등기부등본 / 주주명부 우선 판별
    if any(k in n for k in ("사업자등록", "biz_reg")):
        return "biz_reg"
    if any(k in n for k in ("등기부", "등기사항", "등본", "corp_reg")):
        return "corp_reg"
    if any(k in n for k in ("주주명부", "주주현황", "주식등변동", "주식이동", "shareholder")):
        return "shareholder"

    # 2) 원천징수부 / 급여대장 판별 (4자리 연도 및 '24년·25년·26년' 2자리 연도 모두 인식)
    wht_keywords = ("원천징수", "근로소득", "급여대장", "급여명세", "사원대장", "임직원", "wht")
    is_wht_like = any(k in both for k in wht_keywords)
    if is_wht_like and not any(k in n for k in ("공제감면", "공제세액계산", "상시근로자명세")):
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
            if f"{yr}년" in head[:1500] or f"{yr}귀속" in head[:1500]:
                return f"wht_{yr}"

    # 3) 공제감면세액계산서 / 기신고 상시근로자 명세서 판별
    credit_calc_keywords = (
        "공제감면", "감면세액", "공제세액계산", "세액공제신청", "상시근로자", "통합고용", "고용증대", "조정명세", "사후관리", "credit_calc"
    )
    if any(k in both for k in credit_calc_keywords):
        for yr in range(2028, 2020, -1):
            short_yr = f"{yr % 100:02d}"
            if str(yr) in n or f"{short_yr}년" in n or f"_{short_yr}" in n:
                return f"credit_calc_{yr}" if yr >= 2025 else "prev_filing"
        for yr in range(2028, 2024, -1):
            if f"{yr}년" in head[:1500] or f"{yr}귀속" in head[:1500]:
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
# 2. 보완적 AI JSON 추출 호출 (비정형 PDF·누락 필드 보완 전용)
#    - 클로드 코드의 `agent.get_live_gemini_key_pool()` + `GEMINI_PAID_KEY` + `thinking_budget=0` 완벽 통합
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


def _get_gemini_models() -> list[str]:
    models: list[str] = []
    try:
        import agent
        for attr in ("FLASH_MODEL_ID", "FLASH_BACKUP_ID", "FLASH_FALLBACK_ID", "FLASH_LITE_ID"):
            m = getattr(agent, attr, None)
            if m and m not in models:
                models.append(str(m))
    except Exception:
        pass
    for m in ("gemini-2.5-flash", "gemini-2.5-pro"):
        if m not in models:
            models.append(m)
    return models


def call_gemini_json(instruction: str, text: str, log_tokens_fn=None, room_key: str = "") -> dict:
    keys = _get_gemini_api_keys()
    if not keys:
        return {}
    try:
        from google import genai
        from google.genai import types
    except Exception:
        return {}

    models = _get_gemini_models()
    prompt = (
        instruction
        + "\n\n규칙: JSON만 출력하고 설명·마크다운은 쓰지 마세요. "
        "서류에 없는 값은 지어내지 말고 빈 문자열(\"\")이나 null로 두세요.\n\n[서류 내용]\n"
        + (text or "")[:MAX_TEXT_CHARS]
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


PROMPT_BIZ = """다음은 사업자등록증입니다. 아래 JSON 형식으로 정확히 읽어주세요.
{"상호":"", "사업자번호":"000-00-00000", "대표자":"", "개업일":"YYYY-MM-DD", "법인등록번호앞6자리":"", "사업장소재지":"", "업태":"", "종목":""}"""

PROMPT_CORP = """다음은 법인 등기부등본입니다. 현재 재임 중인 임원(대표이사, 사내이사, 이사, 감사 등)만 아래 JSON 형식으로 읽어주세요.
{"상호":"", "설립일":"YYYY-MM-DD", "본점":"", "임원":[{"성명":"", "직책":"대표이사/이사/감사", "주민앞6자리":""}]}"""

PROMPT_SH = """다음은 주주명부입니다. 아래 JSON 형식으로 읽어주세요. 관계는 서류에 적힌 그대로(본인/배우자/자/부/모/형제 등) 적고 없으면 빈 문자열로 두세요.
{"주주":[{"성명":"", "주민앞6자리":"", "지분율":0.0, "관계":""}]}"""

PROMPT_WHT = """다음은 소득자별 근로소득원천징수부입니다. 모든 근로자를 빠짐없이 아래 JSON 형식으로 읽어주세요.
주민등록번호는 앞 6자리와 뒷자리 첫 1자리만 '000000-0' 형태로 적고, 각 월(1~12)의 급여총액(과세급여)을 숫자로 넣으세요.
{"근로자":[{"성명":"", "주민번호앞7자리":"000000-0", "입사일":"YYYY-MM-DD", "퇴사일":"YYYY-MM-DD", "고용유형":"정규직/계약직(기간제)/단시간(60시간 이상)/대표이사/임원", "병역개월":0, "월급여":{"1":0,"2":0,"3":0,"4":0,"5":0,"6":0,"7":0,"8":0,"9":0,"10":0,"11":0,"12":0}}]}"""

PROMPT_PREV = """다음은 이미 신고한 통합고용세액공제(또는 고용증대세액공제) 관련 서식(공제감면세액계산서·상시근로자 명세서·공제세액계산서·세액공제조정명세서)입니다.
연도별 전체 상시근로자 총인원수(연인원 합계) 및 평균인원수(상시), 청년등 총인원수(연인원 합계) 및 평균인원수(청년등), 공제받은 청년등 증가인원, 청년등 외 증가인원, 기공제세액(원), 2차년도 연속공제세액(원), 1차 사후관리 기납부 추징세액(원), 미공제 이월세액(원)을 아래 JSON 형식으로 읽어주세요.
{"연도별":{
  "2023":{"상시_총인원":null, "청년등_총인원":null, "상시":null, "청년등":null, "청년등_증가":null, "청년등외_증가":null, "공제세액":null, "이월세액":null},
  "2024":{"상시_총인원":null, "청년등_총인원":null, "상시":null, "청년등":null, "청년등_증가":null, "청년등외_증가":null, "공제세액":null, "2차_공제세액":null, "기추징세액":null, "이월세액":null},
  "2025":{"상시_총인원":null, "청년등_총인원":null, "상시":null, "청년등":null, "청년등_증가":null, "청년등외_증가":null, "공제세액":null, "이월세액":null}
}}"""


# ══════════════════════════════════════════════════════════════════
# 3. 100% 자체 결정론적 고속 파서 모음 (원천징수부 · 사업자등록증 · 등기부등본 · 주주명부 · 기신고서)
# ══════════════════════════════════════════════════════════════════
def birth_from_rrn7(rrn7: str) -> tuple[date | None, bool]:
    s = re.sub(r"[^0-9]", "", str(rrn7 or ""))
    if len(s) < 6:
        return None, False
    yy, mm, dd = int(s[0:2]), int(s[2:4]), int(s[4:6])
    g = int(s[6]) if len(s) >= 7 else 1
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


def _parse_whitespace_wht_rows(text: str) -> list[dict] | None:
    """
    [포맷 A & C 전담 자체 파서]
    `app.py`의 `extract_file_content`가 출력하는 `df.head(1500).to_string(index=False)` 공백 구분 표,
    탭 구분 표, CSV 표에서 사원 행을 100% 자체 파싱합니다.
    """
    if not text:
        return None

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        return None

    employees: list[dict] = []
    for ln in lines:
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
        for idx in range(min(6, len(tokens))):
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


def _try_fast_parse_wht_table(text: str) -> list[dict] | None:
    """
    원천징수부/급여대장 통합 자체 파서 (0.005초):
    1) 마크다운 파이프(`| ... |`) 표 형식이면 파이프 파서로 즉시 추출.
    2) `app.py`의 `df.to_string(index=False)` 공백 구분 표나 CSV/TSV 형식이면 `_parse_whitespace_wht_rows`로 즉시 추출.
    """
    if not text:
        return None

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
                    if any(k in hc for k in ("성명", "이름", "사원명", "소득자")):
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

    return _parse_whitespace_wht_rows(text)


def _try_fast_parse_biz_reg(text: str) -> dict:
    """사업자등록증 텍스트 자체 정규식 파서 (1순위)."""
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
# 4. 100% 자체파싱(1순위) + 멀티스레드 AI 보완 추출(2순위) 통합 (extract_all)
# ══════════════════════════════════════════════════════════════════
def extract_all(doc_texts: dict[str, str], log_tokens_fn=None, room_key: str = "") -> dict:
    """
    업로드된 모든 서류를 추출합니다:
    - 1단계(자체 파싱): 모든 서류에 대해 파이썬 자체 파서(`_try_fast_parse_*`)를 먼저 즉시 실행합니다.
      * 원천징수부(엑셀/CSV/표)는 자체 파서 성공 시 AI 호출을 100% 생략하여 0.01초 만에 완료합니다.
    - 2단계(보완적 AI 호출): 비정형 PDF 원천징수부(자체 파싱 실패 시)나 사업자등록증·등기부등본·주주명부·공제감면세액계산서 중
      자체 파싱에서 누락된 필드가 있는 경우에만 `ThreadPoolExecutor`로 AI를 병렬 호출하여 빈칸을 보완합니다.
    """
    out: dict = {
        "biz_reg": {},
        "corp_reg": {},
        "shareholder": [],
        "wht": {},
        "prev_filing": {"연도별": {}},
    }
    if not doc_texts:
        return out

    llm_tasks: dict[str, tuple[str, str]] = {}

    for key, text in doc_texts.items():
        if not text or not text.strip():
            continue
        if key.startswith("wht_"):
            yr = key.replace("wht_", "").strip()
            fast_rows = _try_fast_parse_wht_table(text)
            if fast_rows is not None and len(fast_rows) > 0:
                out["wht"][yr] = fast_rows
            else:
                llm_tasks[key] = (PROMPT_WHT, text)
        elif key == "biz_reg":
            fast_biz = _try_fast_parse_biz_reg(text)
            out["biz_reg"] = fast_biz
            if not all(fast_biz.get(k) for k in ("상호", "사업자번호", "사업장소재지", "업태")):
                llm_tasks[key] = (PROMPT_BIZ, text)
        elif key == "corp_reg":
            fast_corp = _try_fast_parse_corp_reg(text)
            out["corp_reg"] = fast_corp
            if not (fast_corp.get("설립일") and fast_corp.get("임원")):
                llm_tasks[key] = (PROMPT_CORP, text)
        elif key == "shareholder":
            fast_sh = _try_fast_parse_shareholder(text)
            out["shareholder"] = fast_sh
            if not fast_sh:
                llm_tasks[key] = (PROMPT_SH, text)
        elif key in ("prev_filing", "prev_credit_calc") or key.startswith("credit_calc_"):
            fast_pf = _try_fast_parse_prev_filing(text)
            if fast_pf.get("연도별"):
                for y_s, y_v in fast_pf["연도별"].items():
                    out["prev_filing"]["연도별"].setdefault(y_s, {}).update(y_v)
            llm_tasks[key] = (PROMPT_PREV, text)

    if llm_tasks:
        max_workers = min(6, len(llm_tasks))
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            fut_map = {
                pool.submit(call_gemini_json, prompt, txt, log_tokens_fn, room_key): k
                for k, (prompt, txt) in llm_tasks.items()
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
                    if norm_rows:
                        out["wht"][yr] = norm_rows

    return out


def build_prev_summary(ext: dict, tax_year: int) -> dict[str, dict]:
    """
    기신고 서식(상시근로자 명세서·공제감면세액계산서)에서 읽은 값을 코호트(최초공제연도)별로 정리합니다.
    """
    ty = int(tax_year or R.DEFAULT_TAX_YEAR)
    keys = (
        "상시_총인원", "청년등_총인원", "상시", "청년등",
        "청년등_증가", "청년등외_증가", "공제세액", "2차_공제세액", "기추징세액", "이월세액"
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
    return out


# ══════════════════════════════════════════════════════════════════
# 5. 사업자정보 및 사원정보(People & Year Records) 빌더
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
    return {
        "고용유형": emp_type if emp_type in R.EMP_TYPES else R.EMP_REGULAR,
        "제외사유": "",
        "청년등": "",
        "상시_override": "",
        "월_override": {},
        "_confirmed": ["고용유형"] if confirmed_emp else [],
        "_user_set": [],
        "_unlocked": False,
    }


def build_people(ext: dict, years: list[int]) -> tuple[dict, dict]:
    """
    모든 연도(예: 2024·2025·2026)의 원천징수부 데이터를 성명+생년월일 기준으로 병합합니다.
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

    for y_str in sorted(wht_by_year.keys()):
        try:
            y_int = int(y_str)
        except ValueError:
            continue
        year_recs.setdefault(y_int, {})
        for row in wht_by_year.get(y_str) or []:
            nm = str(row.get("성명") or "").strip()
            if not nm:
                continue
            b_str = str(row.get("생년월일") or "").strip()
            dedup_key = f"{nm}|{b_str}" if b_str else nm
            pid = key_to_pid.get(dedup_key) or key_to_pid.get(nm)
            if not pid:
                pid = f"p_{len(people) + 1:03d}"
                key_to_pid[dedup_key] = pid
                key_to_pid.setdefault(nm, pid)
                people[pid] = {
                    "pid": pid,
                    "성명": nm,
                    "생년월일": b_str,
                    "입사일": row.get("입사일") or "",
                    "퇴사일": row.get("퇴사일") or "",
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
            if row.get("입사일"):
                if not p["입사일"] or row["입사일"] < p["입사일"]:
                    p["입사일"] = row["입사일"]
                    p["계약체결일"] = row["입사일"]
            if row.get("퇴사일"):
                p["퇴사일"] = row["퇴사일"]
                p["연도별_퇴사일"][str(y_int)] = row["퇴사일"]
            if row.get("병역개월") and not p.get("병역개월"):
                p["병역개월"] = int(row["병역개월"])
            if row.get("외국인"):
                p["외국인"] = True
            p["월급여"][str(y_int)] = row.get("월급여") or {}

            conf = set(p.get("_confirmed") or [])
            conf.add("성명")
            if p["생년월일"]:
                conf.add("생년월일")
            if p["입사일"]:
                conf.add("입사일")
            if p["퇴사일"]:
                conf.add("퇴사일")
            p["_confirmed"] = list(conf)

            emp_t = exec_role_by_name.get(nm) or row.get("고용유형") or R.EMP_REGULAR
            confirmed_emp = nm in exec_role_by_name or (row.get("고용유형") in R.EMP_TYPES)
            year_recs[y_int][pid] = new_year_rec(emp_t, confirmed_emp=confirmed_emp)

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
    """
    [추가 LLM 호출 대기(0초) 없이 추출된 서류 간 불일치·주의사항을 정밀 교차검증]
    """
    if not ext:
        return []
    warnings: list[str] = []

    wht_map = ext.get("wht") or {}
    all_wht_names: set[str] = set()
    missing_birth_names: set[str] = set()
    missing_hire_names: set[str] = set()

    for yr_str, rows in wht_map.items():
        for r in rows or []:
            nm = str(r.get("성명") or "").strip()
            if not nm:
                continue
            all_wht_names.add(nm)
            if not r.get("생년월일"):
                missing_birth_names.add(nm)
            if not r.get("입사일"):
                missing_hire_names.add(nm)

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

    if ext:
        wht = ext.get("wht") or {}
        for y in (tax_year, tax_year - 1):
            if classified.get(f"wht_{y}") and not wht.get(str(y)):
                msgs.append(f"{y}년 원천징수부에서 근로자 명단을 읽지 못했습니다. 2단계에서 직접 입력하거나 파일을 다시 확인하세요.")
        for w in ai_extra_warnings(ext):
            if w not in msgs:
                msgs.append(w)
    return msgs