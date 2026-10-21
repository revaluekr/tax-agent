import os
import io
import re
import time
import json
import hashlib
import threading
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo
import streamlit as st
import pandas as pd
from pypdf import PdfReader
from docx import Document
from docx.shared import Pt
from docx.oxml.ns import qn
from google import genai
from google.genai import types

# PDF 직접 생성을 위한 ReportLab 모듈
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# 🔒 ImportError 원천 방지 안전 임포트
import agent
from agent import run_agent

# 1. 웹 페이지 기본 설정
st.set_page_config(
    page_title="세무·법령·회계 자율 에이전트",
    page_icon="⚖️",
    layout="wide"
)

# 백그라운드 스레드에서도 st.secrets의 모든 API 키를 읽을 수 있도록 환경변수로 안전 동기화
try:
    if hasattr(st, "secrets"):
        for k, v in st.secrets.items():
            if isinstance(v, (str, int, float)) and k not in os.environ:
                os.environ[k] = str(v).strip()
except Exception:
    pass

# ---------------------------------------------------------
# 💎 프리미엄 화이트 카드 사이드바(글자 잘림 방지 + 원스크린 배치) CSS
# ---------------------------------------------------------
st.markdown("""
<style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');

html, body, [class*="css"] {
    font-family: 'Pretendard', 'Malgun Gothic', 'Apple SD Gothic Neo', sans-serif;
}

/* 📐 우측 본문 상단 여백 축소 -> 좌측 사이드바 타이틀과 수평 라인 정렬 */
div.block-container {
    padding-top: 2.0rem !important;
    padding-bottom: 2.0rem !important;
}

/* 🎨 사이드바 전체 배경 및 상하 여백 */
section[data-testid="stSidebar"] {
    background-color: #f1f5f9 !important;
    border-right: 1px solid #cbd5e1 !important;
}
section[data-testid="stSidebar"] div[data-testid="stSidebarUserContent"] {
    padding-top: 1.0rem !important;
    padding-bottom: 0.8rem !important;
}

/* 📦 사이드바 내부 화이트 카드 패딩 및 간격 */
section[data-testid="stSidebar"] div[data-testid="stVerticalBlockBorderWrapper"] {
    background-color: #ffffff !important;
    border: 1px solid #e2e8f0 !important;
    border-radius: 10px !important;
    padding: 10px 12px !important;
    margin-bottom: 7px !important;
    box-shadow: 0 1px 3px rgba(15, 23, 42, 0.03) !important;
}

/* 사이드바 내부 위젯 간격 (입력창이 위 제목을 덮지 않도록 안전 간격 확보) */
section[data-testid="stSidebar"] div[data-testid="stVerticalBlock"] {
    gap: 0.55rem !important;
}
section[data-testid="stSidebar"] div[data-testid="stMarkdownContainer"] {
    overflow: visible !important;
}
section[data-testid="stSidebar"] div[data-testid="stTextInput"],
section[data-testid="stSidebar"] div[data-testid="stSelectbox"],
section[data-testid="stSidebar"] div[data-testid="stFileUploader"] {
    margin-top: 2px !important;
}

/* 사이드바 버튼 높이 컴팩트화 */
section[data-testid="stSidebar"] button {
    min-height: 2.1rem !important;
    padding: 0.22rem 0.6rem !important;
    font-size: 0.82rem !important;
    border-radius: 7px !important;
    font-weight: 600 !important;
}
section[data-testid="stSidebar"] a[data-testid="stBaseLinkButton-secondary"] {
    min-height: 2.1rem !important;
    padding: 0.22rem 0.5rem !important;
    font-size: 0.80rem !important;
    border-radius: 7px !important;
    font-weight: 600 !important;
}

/* 사이드바 카드 소제목(라벨) 스타일 — 줄높이와 하단 여백을 넉넉히 주어 글자 잘림 완벽 방지 */
.sb-card-title {
    font-size: 0.85rem;
    font-weight: 800;
    color: #0f172a;
    line-height: 1.45 !important;
    padding-top: 1px !important;
    padding-bottom: 4px !important;
    margin-bottom: 4px !important;
    display: flex;
    align-items: center;
    justify-content: space-between;
    letter-spacing: -0.3px;
}
.sb-badge-green {
    background-color: #dcfce7;
    color: #15803d;
    font-size: 0.70rem;
    font-weight: 700;
    padding: 2px 7px;
    border-radius: 999px;
    line-height: 1.2 !important;
}
.sb-badge-amber {
    background-color: #fef3c7;
    color: #b45309;
    font-size: 0.70rem;
    font-weight: 700;
    padding: 2px 7px;
    border-radius: 999px;
    line-height: 1.2 !important;
}
.sb-badge-pro {
    background-color: #dbeafe;
    color: #1d4ed8;
    font-size: 0.70rem;
    font-weight: 700;
    padding: 2px 7px;
    border-radius: 999px;
    line-height: 1.2 !important;
}

/* 메인 타이틀 스타일 */
h1 {
    color: #0f172a !important;
    font-weight: 800 !important;
    font-size: 1.85rem !important;
    letter-spacing: -0.5px;
    border-bottom: 2px solid #e2e8f0;
    padding-bottom: 10px !important;
    margin-top: 0px !important;
    margin-bottom: 12px !important;
}

/* 🤖 기본 답변 로봇 아이콘 디자인 100% 유지 + 초록색 배경(#22c55e) & 흰색 아이콘(#ffffff) */
[data-testid="chatAvatarIcon-assistant"],
div[data-testid="stChatMessageAvatarAssistant"] {
    background-color: #22c55e !important;
    color: #ffffff !important;
}
[data-testid="chatAvatarIcon-assistant"] svg,
div[data-testid="stChatMessageAvatarAssistant"] svg {
    fill: #ffffff !important;
    color: #ffffff !important;
}

/* 보고서 대제목 (### 1. 결론, ### 2. 내용, ### 3. 관련법령) */
div[data-testid="stChatMessageContent"] h3 {
    color: #1e3a8a !important;
    background: linear-gradient(90deg, #f1f5f9 0%, #ffffff 100%);
    border-left: 5px solid #1e3a8a;
    padding: 8px 14px !important;
    border-radius: 0 6px 6px 0;
    margin-top: 22px !important;
    margin-bottom: 12px !important;
    font-size: 1.2rem !important;
    font-weight: 700 !important;
}

/* 보고서 소제목 (#### (1) 상세 법리 등) */
div[data-testid="stChatMessageContent"] h4 {
    color: #1e40af !important;
    margin-top: 16px !important;
    margin-bottom: 8px !important;
    font-size: 1.05rem !important;
    font-weight: 700 !important;
}

/* 마크다운 표(Table) 엔터프라이즈 네이비 스타일링 */
div[data-testid="stChatMessageContent"] table {
    width: 100%;
    border-collapse: collapse;
    margin: 14px 0 18px 0;
    font-size: 0.94rem;
    border-radius: 6px;
    overflow: hidden;
    box-shadow: 0 1px 3px rgba(0,0,0,0.05);
}
div[data-testid="stChatMessageContent"] th {
    background-color: #1e293b !important;
    color: #ffffff !important;
    font-weight: 600 !important;
    padding: 10px 12px !important;
    border: 1px solid #334155 !important;
    text-align: left !important;
}
div[data-testid="stChatMessageContent"] td {
    padding: 9px 12px !important;
    border: 1px solid #cbd5e1 !important;
    color: #1e293b;
    background-color: #ffffff;
}
div[data-testid="stChatMessageContent"] tr:nth-child(even) td {
    background-color: #f8fafc;
}

/* 상단 모드 안내 인용구 박스 (> ⚡ / > 🧠) */
div[data-testid="stChatMessageContent"] blockquote {
    background-color: #f8fafc;
    border-left: 4px solid #22c55e;
    padding: 8px 14px;
    border-radius: 6px;
    color: #334155;
    font-size: 0.9rem;
    margin-bottom: 12px;
}

/* 본문 다운로드 버튼 디자인 */
div.stDownloadButton > button {
    border-radius: 8px !important;
    font-weight: 600 !important;
    transition: all 0.15s ease-in-out !important;
}
div.stDownloadButton > button:hover {
    border-color: #16a34a !important;
    color: #15803d !important;
    background-color: #f0fdf4 !important;
}

/* 불필요한 Streamlit 기본 푸터 숨김 */
footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------
# 0. 작업공간(Workspace) · 월간 요금 계량기 · 백그라운드 스레드 매니저
# ---------------------------------------------------------
ROOM_IDS = [f"대화방 {i}" for i in range(1, 11)]
STORAGE_DIR = ".workspace_storage"
os.makedirs(STORAGE_DIR, exist_ok=True)
USAGE_FILE_PATH = os.path.join(STORAGE_DIR, "api_usage_stats.json")
MONTHLY_PRO_LIMIT_KRW = 20000.0
USD_TO_KRW_RATE = 1400.0

@st.cache_resource
def get_background_task_manager() -> dict:
    """대화방을 이동하거나 버튼을 눌러도 AI 검색이 끊기지 않도록 백그라운드 작업을 관리합니다."""
    return {"tasks": {}, "lock": threading.Lock()}

def get_monthly_usage() -> dict:
    """agent.py 버전에 관계없이 안전하게 당월 누적 요금 데이터를 조회합니다."""
    if hasattr(agent, "get_monthly_usage"):
        try:
            return agent.get_monthly_usage()
        except Exception:
            pass
    ym = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m")
    default_stats = {
        "year_month": ym,
        "total_krw": 0.0,
        "total_usd": 0.0,
        "pro_calls": 0,
        "flash_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "limit_krw": MONTHLY_PRO_LIMIT_KRW,
        "updated_at": "-"
    }
    if os.path.exists(USAGE_FILE_PATH):
        try:
            with open(USAGE_FILE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("year_month") == ym:
                for k, v in default_stats.items():
                    data.setdefault(k, v)
                data["limit_krw"] = MONTHLY_PRO_LIMIT_KRW
                return data
        except Exception:
            pass
    return default_stats

def is_pro_budget_exceeded() -> tuple[bool, float, float]:
    """당월 누적 요금이 20,000원을 초과했는지 확인합니다."""
    if hasattr(agent, "is_pro_budget_exceeded"):
        try:
            return agent.is_pro_budget_exceeded()
        except Exception:
            pass
    stats = get_monthly_usage()
    cur_krw = float(stats.get("total_krw", 0.0))
    limit_krw = float(stats.get("limit_krw", MONTHLY_PRO_LIMIT_KRW))
    return (cur_krw >= limit_krw), cur_krw, limit_krw

def _log_custom_tokens(model_id: str, in_tok: int, out_tok: int, count_call: bool = True) -> None:
    """OCR 등 app.py에서 직접 호출한 소액 토큰도 실시간 요금 계량기에 합산합니다."""
    if hasattr(agent, "_record_token_usage"):
        try:
            agent._record_token_usage(model_id, in_tok, out_tok, count_call=count_call)
            return
        except Exception:
            pass
    stats = get_monthly_usage()
    is_pro = ("pro" in model_id.lower()) or ("argon" in model_id.lower())
    in_price, out_price = (1.50, 10.00) if is_pro else (0.15, 0.60)
    cost_usd = (in_tok / 1_000_000.0) * in_price + (out_tok / 1_000_000.0) * out_price
    cost_krw = cost_usd * USD_TO_KRW_RATE

    stats["total_usd"] = round(stats.get("total_usd", 0.0) + cost_usd, 6)
    stats["total_krw"] = round(stats.get("total_krw", 0.0) + cost_krw, 2)
    stats["input_tokens"] = int(stats.get("input_tokens", 0)) + int(in_tok)
    stats["output_tokens"] = int(stats.get("output_tokens", 0)) + int(out_tok)
    if count_call:
        if is_pro:
            stats["pro_calls"] = int(stats.get("pro_calls", 0)) + 1
        else:
            stats["flash_calls"] = int(stats.get("flash_calls", 0)) + 1
    stats["updated_at"] = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%m/%d %H:%M:%S")
    try:
        with open(USAGE_FILE_PATH, "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def _record_usage_fallback(user_input: str, response_text: str, is_pro: bool) -> None:
    """만약 agent.py가 구버전이더라도 app.py에서 자동으로 토큰과 요금을 계산해 기록합니다."""
    if hasattr(agent, "_record_token_usage"):
        return
    in_tok = int((len(user_input) + 12000) * 0.7) * (3 if is_pro else 1)
    out_tok = int(len(response_text) * 0.8)
    _log_custom_tokens("pro" if is_pro else "flash", in_tok, out_tok, count_call=True)

def _check_api_configured(key_names: list[str]) -> bool:
    """환경변수 또는 st.secrets에 해당 API 키가 설정되어 있는지 확인합니다."""
    for k in key_names:
        try:
            if hasattr(st, "secrets") and k in st.secrets and str(st.secrets[k]).strip():
                return True
        except Exception:
            pass
        if os.getenv(k, "").strip():
            return True
    return False

def get_storage_path(workspace_id: str) -> str:
    """작업공간 ID(암호)를 해시 암호화하여 고유한 저장 파일 경로를 생성합니다."""
    safe_hash = hashlib.sha256(workspace_id.strip().encode("utf-8")).hexdigest()[:16]
    return os.path.join(STORAGE_DIR, f"ws_{safe_hash}.json")

def _normalize_room_file_entry(entry: dict) -> dict:
    """단일 파일 구조와 다중 파일(items) 구조를 모두 호환하도록 정규화합니다."""
    if not isinstance(entry, dict):
        return {"name": None, "text": "", "items": []}
    items = entry.get("items")
    if items is None:
        if entry.get("name") and entry.get("text"):
            items = [{"name": entry["name"], "text": entry["text"]}]
        else:
            items = []
    if not items:
        return {"name": None, "text": "", "items": []}
    summary_name = items[0]["name"] if len(items) == 1 else f"{items[0]['name']} 외 {len(items)-1}건"
    combined_text = "\n\n========================================\n\n".join(
        f"📄 [파일 {idx+1}: {it['name']}]\n{it['text']}" for idx, it in enumerate(items)
    )
    return {"name": summary_name, "text": combined_text, "items": items}

def get_default_workspace_data() -> dict:
    """깨끗한 초기 10개 방 데이터 구조를 생성합니다."""
    default_titles = {r_id: "빈 대화방" for r_id in ROOM_IDS}
    default_titles["대화방 1"] = "메인 대화"
    return {
        "chat_rooms": {r_id: [] for r_id in ROOM_IDS},
        "room_titles": default_titles,
        "room_files": {r_id: {"name": None, "text": "", "items": []} for r_id in ROOM_IDS}
    }

def load_workspace_from_disk(workspace_id: str) -> dict:
    """서버 디스크에서 해당 작업공간의 10개 방 데이터를 불러옵니다."""
    path = get_storage_path(workspace_id)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            default_data = get_default_workspace_data()
            for key in ["chat_rooms", "room_titles", "room_files"]:
                if key not in data:
                    data[key] = default_data[key]
                else:
                    for r_id in ROOM_IDS:
                        if r_id not in data[key]:
                            data[key][r_id] = default_data[key][r_id]
            for r_id in ROOM_IDS:
                data["room_files"][r_id] = _normalize_room_file_entry(data["room_files"][r_id])
            return data
        except Exception:
            pass
    return get_default_workspace_data()

def save_workspace_to_disk(workspace_id: str):
    """현재 세션의 10개 방 대화·제목·첨부파일 텍스트를 서버 디스크에 즉시 자동 저장합니다."""
    if not workspace_id:
        return
    path = get_storage_path(workspace_id)
    data = {
        "chat_rooms": st.session_state.chat_rooms,
        "room_titles": st.session_state.room_titles,
        "room_files": st.session_state.room_files
    }
    try:
        with get_background_task_manager()["lock"]:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ 자동 저장 오류: {e}")

def delete_workspace_from_disk(workspace_id: str):
    """서버 디스크에서 해당 작업공간의 저장 파일(.json)을 영구 삭제합니다."""
    if not workspace_id or workspace_id == "default_public":
        return
    path = get_storage_path(workspace_id)
    if os.path.exists(path):
        try:
            os.remove(path)
        except Exception as e:
            print(f"⚠️ 파일 삭제 오류: {e}")

def _background_agent_worker(
    ws_id: str,
    room_id: str,
    full_input: str,
    raw_query: str,
    has_file: bool,
    is_pro: bool,
    task_info: dict
) -> None:
    """
    화면 이동이나 버튼 클릭으로 Streamlit이 새로고침되더라도
    백그라운드에서 끝까지 법령 검색과 답변 생성을 완수하고 디스크에 저장하는 독립 워커입니다.
    """
    try:
        response_text = run_agent(
            user_input=full_input,
            raw_query=raw_query,
            has_file=has_file
        )
        _record_usage_fallback(full_input, response_text, is_pro)
    except Exception as e:
        response_text = f"❌ 에이전트 실행 중 오류가 발생했습니다: {e}"

    try:
        mgr = get_background_task_manager()
        with mgr["lock"]:
            disk_data = load_workspace_from_disk(ws_id)
            room_msgs = disk_data["chat_rooms"].get(room_id, [])
            if not room_msgs or room_msgs[-1].get("role") != "assistant" or room_msgs[-1].get("content") != response_text:
                room_msgs.append({"role": "assistant", "content": response_text})
                disk_data["chat_rooms"][room_id] = room_msgs
                path = get_storage_path(ws_id)
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(disk_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ 백그라운드 디스크 저장 오류: {e}")

    task_info["response"] = response_text
    task_info["status"] = "done"

# ---------------------------------------------------------
# 헬퍼 함수 1: 파일 추출 + 📸 사진/스캔본 PDF 1회 자동 OCR (Gemini Flash 비전)
# ---------------------------------------------------------
MAX_DOC_CHARS_STANDARD = 50000
MAX_DOC_CHARS_PRO      = 150000

def _ocr_with_gemini_flash(file_bytes: bytes, mime_type: str, filename: str) -> str:
    """사진(.jpg/.png)이나 텍스트가 없는 스캔본 PDF를 업로드 시 딱 1회만 저렴한 Flash 모델로 OCR 추출해 저장합니다."""
    pool = agent.get_live_gemini_key_pool() if hasattr(agent, "get_live_gemini_key_pool") else []
    api_key = pool[0][1] if pool else (os.getenv("GEMINI_PAID_KEY") or os.getenv("GEMINI_API_KEY") or "")
    if not api_key:
        return "❌ [OCR 오류] 설정된 Gemini API 키가 없어 이미지/스캔본 글자를 인식할 수 없습니다."

    ocr_prompt = (
        f"첨부된 문서/이미지({filename})의 모든 텍스트, 숫자, 사업자등록번호, 날짜, 금액, 계약 조항, "
        "그리고 표(Table) 내용을 단 한 글자도 누락하거나 요약하지 말고 원문 그대로 추출하세요. "
        "표가 있다면 마크다운 표(| 컬럼 | ... |) 형식으로 정확히 옮겨 적으세요."
    )
    models_to_try = [
        getattr(agent, "FLASH_MODEL_ID", "gemini-3.8-flash"),
        getattr(agent, "FLASH_BACKUP_ID", "gemini-3.6-flash"),
        "gemini-2.5-flash"
    ]
    last_err = ""
    for m_id in dict.fromkeys(models_to_try):
        try:
            client = genai.Client(api_key=api_key, http_options={"timeout": 90000})
            resp = client.models.generate_content(
                model=m_id,
                contents=[
                    types.Part.from_bytes(data=file_bytes, mime_type=mime_type),
                    ocr_prompt
                ]
            )
            extracted = agent.extract_safe_text(resp) if hasattr(agent, "extract_safe_text") else (resp.text or "")
            um = getattr(resp, "usage_metadata", None)
            in_tok = int(getattr(um, "prompt_token_count", 0) or 1500)
            out_tok = int(getattr(um, "candidates_token_count", 0) or max(200, int(len(extracted) * 0.7)))
            _log_custom_tokens(m_id, in_tok, out_tok, count_call=True)
            if extracted.strip():
                return f"[📸 AI 비전 OCR 자동 판독 완료: {filename}]\n{extracted.strip()}"
        except Exception as e:
            last_err = str(e)
            continue
    return f"❌ 이미지/스캔본 OCR 판독 실패 ({filename}): {last_err}"

def extract_file_content(uploaded_file) -> str:
    """엑셀, CSV, 텍스트 PDF, 워드는 무료 파이썬으로 추출하고, 사진이나 스캔본 PDF만 1회 Flash OCR을 가동합니다."""
    filename = uploaded_file.name
    lower_name = filename.lower()
    try:
        uploaded_file.seek(0)
        raw_bytes = uploaded_file.read()

        if lower_name.endswith((".xlsx", ".xls")):
            excel_file = pd.ExcelFile(io.BytesIO(raw_bytes))
            text_parts = [f"[첨부 엑셀 파일명: {filename}]"]
            for sheet in excel_file.sheet_names:
                df = excel_file.parse(sheet)
                text_parts.append(f"\n--- 시트명: {sheet} (총 {len(df)}행) ---")
                text_parts.append(df.head(1500).to_string(index=False))
            return "\n".join(text_parts)[:MAX_DOC_CHARS_PRO]

        elif lower_name.endswith(".csv"):
            for enc in ["utf-8-sig", "utf-8", "cp949", "euc-kr"]:
                try:
                    df = pd.read_csv(io.BytesIO(raw_bytes), encoding=enc)
                    return (f"[첨부 CSV 파일명: {filename} (총 {len(df)}행)]\n" + df.head(1500).to_string(index=False))[:MAX_DOC_CHARS_PRO]
                except Exception:
                    continue
            return "❌ CSV 파일의 한글 인코딩을 읽을 수 없습니다. 엑셀(.xlsx)로 저장 후 다시 올려주세요."

        elif lower_name.endswith(".pdf"):
            reader = PdfReader(io.BytesIO(raw_bytes))
            text_parts = [f"[첨부 PDF 파일명: {filename} (총 {len(reader.pages)}페이지)]"]
            pure_body_chars = 0
            for idx, page in enumerate(reader.pages[:150]):
                page_text = (page.extract_text() or "").strip()
                pure_body_chars += len(page_text)
                text_parts.append(f"\n--- {idx+1}페이지 ---\n{page_text}")
            if pure_body_chars < 40:
                return _ocr_with_gemini_flash(raw_bytes, "application/pdf", filename)[:MAX_DOC_CHARS_PRO]
            return "\n".join(text_parts)[:MAX_DOC_CHARS_PRO]

        elif lower_name.endswith(".docx"):
            doc = Document(io.BytesIO(raw_bytes))
            text_parts = [f"[첨부 워드 파일명: {filename}]"]
            for p in doc.paragraphs:
                if p.text.strip():
                    text_parts.append(p.text.strip())
            if doc.tables:
                text_parts.append("\n--- [워드 문서 내 표(Table) 데이터] ---")
                for t_idx, table in enumerate(doc.tables):
                    text_parts.append(f"\n[표 {t_idx+1}]")
                    for row in table.rows:
                        row_cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
                        text_parts.append(" | ".join(row_cells))
            return "\n".join(text_parts)[:MAX_DOC_CHARS_PRO]

        elif lower_name.endswith((".png", ".jpg", ".jpeg")):
            mime = "image/png" if lower_name.endswith(".png") else "image/jpeg"
            return _ocr_with_gemini_flash(raw_bytes, mime, filename)[:MAX_DOC_CHARS_PRO]

        return "지원하지 않는 파일 형식입니다."
    except Exception as e:
        return f"❌ 파일 읽기 오류: {e}"

# ---------------------------------------------------------
# 공통 정제 도우미 및 📊 마크다운 표 -> 엑셀(.xlsx) 변환기 (0토큰·무료)
# ---------------------------------------------------------
def _sanitize_math_text(text: str) -> str:
    if not text:
        return ""
    s = text
    s = re.sub(r"\$\$(.*?)\$\$", r"\1", s, flags=re.DOTALL)
    s = re.sub(r"\$([^$\n]+)\$", r"\1", s)
    s = re.sub(r"\\text(?:bf|rm|it)?\{([^}]*)\}", r"\1", s)
    s = re.sub(r"\\frac\{([^}]*)\}\{([^}]*)\}", r"(\1/\2)", s)
    s = s.replace(r"\times", " × ").replace(r"\div", " ÷ ").replace(r"\cdot", "·")
    s = s.replace(r"\%", "%").replace(r"\_", "_").replace(r"\,", ",")
    s = re.sub(r"\\(left|right|quad|qquad|mathrm|mathbf)\b", "", s)
    s = s.replace("−", " - ").replace("–", " - ").replace("—", " - ").replace("∼", "~")
    s = s.replace("→", " -> ").replace("↔", " <-> ").replace("≧", ">=").replace("≦", "<=")
    return s

def _extract_clean_copy_text(report_text: str) -> str:
    """클립보드 원클릭 복사용: 상단 시스템 배지(> ⚡ 등)를 제외하고 카톡/이메일/문서에 바로 붙여넣기 좋은 텍스트를 반환합니다."""
    cleaned = _sanitize_math_text(report_text)
    out_lines = []
    for line in cleaned.split("\n"):
        if line.strip().startswith(">"):
            continue
        out_lines.append(line)
    return "\n".join(out_lines).strip()

def create_excel_from_markdown_tables(report_text: str) -> bytes | None:
    """답변 안의 마크다운 표(| ... |)들을 자동 감지하여 시트별로 정리된 엑셀(.xlsx) 바이트로 변환합니다 (0토큰)."""
    cleaned = _sanitize_math_text(report_text)
    lines = cleaned.split("\n")
    tables = []
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if s.startswith("|") and s.endswith("|"):
            t_rows = []
            while i < len(lines):
                rs = lines[i].strip()
                if not (rs.startswith("|") and rs.endswith("|")):
                    break
                if not re.match(r"^\|[\s\-:|]+\|$", rs):
                    cells = [re.sub(r"\*\*(.*?)\*\*", r"\1", c.strip()) for c in rs.strip("|").split("|")]
                    t_rows.append(cells)
                i += 1
            if len(t_rows) >= 2:
                tables.append(t_rows)
            continue
        i += 1

    if not tables:
        return None

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for idx, t_rows in enumerate(tables):
            max_cols = max(len(r) for r in t_rows)
            padded = [r + [""] * (max_cols - len(r)) for r in t_rows]
            header = padded[0]
            seen_cols = {}
            safe_header = []
            for col_name in header:
                c_label = col_name or "항목"
                if c_label in seen_cols:
                    seen_cols[c_label] += 1
                    safe_header.append(f"{c_label}_{seen_cols[c_label]}")
                else:
                    seen_cols[c_label] = 1
                    safe_header.append(c_label)
            df = pd.DataFrame(padded[1:], columns=safe_header)
            df.to_excel(writer, sheet_name=f"표_{idx+1}", index=False)
    buffer.seek(0)
    return buffer.getvalue()

# ---------------------------------------------------------
# 헬퍼 함수 2: AI 답변을 워드(.docx)로 변환
# ---------------------------------------------------------
def _set_malgun_font(run):
    run.font.name = "Malgun Gothic"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "Malgun Gothic")

def create_word_docx(report_text: str) -> bytes:
    """마크다운 형식의 보고서 텍스트와 표를 한글 폰트(맑은 고딕)가 적용된 워드(.docx) 문서로 변환합니다."""
    report_text = _sanitize_math_text(report_text)
    doc = Document()
    
    style = doc.styles["Normal"]
    style.font.name = "Malgun Gothic"
    style.font.size = Pt(10.5)
    style._element.rPr.rFonts.set(qn("w:eastAsia"), "Malgun Gothic")
    
    lines = report_text.split("\n")
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped or stripped.startswith(">"):
            i += 1
            continue

        if stripped.startswith("|") and stripped.endswith("|"):
            table_rows = []
            while i < len(lines):
                row_s = lines[i].strip()
                if not (row_s.startswith("|") and row_s.endswith("|")):
                    break
                if not re.match(r"^\|[\s\-:|]+\|$", row_s):
                    cells = [re.sub(r"\*\*(.*?)\*\*", r"\1", c.strip()) for c in row_s.strip("|").split("|")]
                    table_rows.append(cells)
                i += 1
            if table_rows:
                max_cols = max(len(r) for r in table_rows)
                t = doc.add_table(rows=len(table_rows), cols=max_cols)
                t.style = "Table Grid"
                for r_idx, r_data in enumerate(table_rows):
                    for c_idx, val in enumerate(r_data):
                        cell = t.cell(r_idx, c_idx)
                        cell.text = val
                        for p in cell.paragraphs:
                            for run in p.runs:
                                _set_malgun_font(run)
                                if r_idx == 0:
                                    run.bold = True
            continue

        clean_line = re.sub(r"\*\*(.*?)\*\*", r"\1", stripped)
        
        if stripped.startswith("#### "):
            h = doc.add_heading(clean_line.replace("#### ", ""), level=2)
            for run in h.runs:
                _set_malgun_font(run)
        elif stripped.startswith("### ") or stripped.startswith("## "):
            heading_text = clean_line.replace("### ", "").replace("## ", "")
            h = doc.add_heading(heading_text, level=1)
            for run in h.runs:
                _set_malgun_font(run)
        elif stripped.startswith("- ") or stripped.startswith("* "):
            p = doc.add_paragraph(clean_line[2:], style="List Bullet")
            p.paragraph_format.space_after = Pt(4)
        elif not re.match(r"^-{3,}$", stripped):
            p = doc.add_paragraph(clean_line)
            p.paragraph_format.space_after = Pt(6)
        i += 1
            
    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()

# ---------------------------------------------------------
# 헬퍼 함수 3: 정식 PDF 직접 생성 엔진
# ---------------------------------------------------------
def _ensure_korean_font() -> tuple[str, str]:
    """서버 환경(Linux/Windows/Mac)에 한글 폰트를 자동 준비·등록하고 (일반폰트명, 굵은폰트명)을 반환합니다."""
    reg_name = "KoreanFont"
    bold_name = "KoreanFontBold"
    if reg_name in pdfmetrics.getRegisteredFontNames():
        return reg_name, bold_name

    font_dir = STORAGE_DIR
    reg_path = os.path.join(font_dir, "NanumGothic.ttf")
    bold_path = os.path.join(font_dir, "NanumGothicBold.ttf")

    win_malgun = "C:/Windows/Fonts/malgun.ttf"
    win_malgun_bd = "C:/Windows/Fonts/malgunbd.ttf"

    if os.path.exists(win_malgun) and os.path.exists(win_malgun_bd):
        reg_path, bold_path = win_malgun, win_malgun_bd
    else:
        try:
            if not os.path.exists(reg_path):
                urllib.request.urlretrieve(
                    "https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Regular.ttf",
                    reg_path
                )
            if not os.path.exists(bold_path):
                urllib.request.urlretrieve(
                    "https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Bold.ttf",
                    bold_path
                )
        except Exception as e:
            print(f"⚠️ 한글 폰트 다운로드 오류: {e}")

    try:
        pdfmetrics.registerFont(TTFont(reg_name, reg_path))
        pdfmetrics.registerFont(TTFont(bold_name, bold_path if os.path.exists(bold_path) else reg_path))
        return reg_name, bold_name
    except Exception:
        return "Helvetica", "Helvetica-Bold"

def _strip_emojis_for_pdf(text: str) -> str:
    """TTF 기본 폰트에서 네모(□)로 깨질 수 있는 컬러 이모지만 깔끔하게 제거합니다."""
    return re.sub(r"[\U00010000-\U0010ffff]", "", text or "")

def _md_to_rl_xml(text: str, bold_font: str) -> str:
    """마크다운 인라인 문법(**굵게**, `코드`)을 ReportLab Paragraph용 XML 태그로 안전하게 변환합니다."""
    s = _strip_emojis_for_pdf(text).strip()
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    s = re.sub(r"\*\*(.+?)\*\*", rf'<font name="{bold_font}">\1</font>', s)
    s = re.sub(r"`([^`]+)`", r'<font backColor="#f1f5f9">\1</font>', s)
    return s

def _draw_page_footer(canvas, doc):
    """PDF 하단 페이지 번호(- 1 -)만 깔끔하게 출력합니다."""
    canvas.saveState()
    reg_font, _ = _ensure_korean_font()
    canvas.setFont(reg_font, 8.5)
    canvas.setFillColor(colors.HexColor("#64748b"))
    page_num_str = f"- {doc.page} -"
    canvas.drawCentredString(A4[0] / 2.0, 25, page_num_str)
    canvas.restoreState()

def create_pdf_report(report_text: str) -> bytes:
    """상단 타이틀·검토안건·작성일자 없이 '1. 결론 -> 2. 내용 -> 3. 관련법령' 본문을 즉시 깔끔한 PDF로 조판합니다."""
    reg_font, bold_font = _ensure_korean_font()
    cleaned_text = _sanitize_math_text(report_text)
    raw_lines = cleaned_text.split("\n")

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=40,
        rightMargin=40,
        topMargin=42,
        bottomMargin=42
    )
    usable_width = A4[0] - 80

    styles = getSampleStyleSheet()
    style_h2 = ParagraphStyle(
        "DocH2", parent=styles["Normal"], fontName=bold_font,
        fontSize=13, leading=19, textColor=colors.HexColor("#1f4e78"),
        spaceBefore=12, spaceAfter=6
    )
    style_h3 = ParagraphStyle(
        "DocH3", parent=styles["Normal"], fontName=bold_font,
        fontSize=11, leading=16, textColor=colors.HexColor("#2e5cb8"),
        spaceBefore=10, spaceAfter=4
    )
    style_body = ParagraphStyle(
        "DocBody", parent=styles["Normal"], fontName=reg_font,
        fontSize=9.8, leading=15.5, textColor=colors.HexColor("#1e293b"),
        spaceAfter=4, wordWrap="CJK"
    )
    style_bullet = ParagraphStyle(
        "DocBullet", parent=style_body, leftIndent=12, firstLineIndent=-8, spaceAfter=3.5
    )
    style_th = ParagraphStyle(
        "DocTH", parent=style_body, fontName=bold_font, fontSize=9.2, leading=13.5,
        textColor=colors.HexColor("#0f172a"), alignment=0
    )
    style_td = ParagraphStyle(
        "DocTD", parent=style_body, fontName=reg_font, fontSize=9.0, leading=13.5,
        textColor=colors.HexColor("#1e293b"), alignment=0
    )

    story = []

    i = 0
    while i < len(raw_lines):
        line = raw_lines[i]
        stripped = line.strip()

        if not stripped:
            story.append(Spacer(1, 4))
            i += 1
            continue

        if stripped.startswith(">"):
            i += 1
            continue

        if re.match(r"^-{3,}$", stripped):
            story.append(Spacer(1, 4))
            story.append(HRFlowable(width="100%", thickness=0.7, color=colors.HexColor("#cbd5e1")))
            story.append(Spacer(1, 6))
            i += 1
            continue

        if stripped.startswith("|") and stripped.endswith("|"):
            table_lines = []
            while i < len(raw_lines):
                r_str = raw_lines[i].strip()
                if not (r_str.startswith("|") and r_str.endswith("|")):
                    break
                table_lines.append(r_str)
                i += 1

            rows_data = []
            for r_str in table_lines:
                if re.match(r"^\|[\s\-:|]+\|$", r_str):
                    continue
                cells = [c.strip() for c in r_str.strip("|").split("|")]
                rows_data.append(cells)

            if rows_data:
                max_cols = max(len(r) for r in rows_data)
                pdf_table_data = []
                for r_idx, r in enumerate(rows_data):
                    padded_r = r + [""] * (max_cols - len(r))
                    row_paras = []
                    for c_text in padded_r:
                        cell_xml = _md_to_rl_xml(c_text, bold_font)
                        row_paras.append(Paragraph(cell_xml, style_th if r_idx == 0 else style_td))
                    pdf_table_data.append(row_paras)

                col_w = usable_width / max_cols
                pdf_table = Table(pdf_table_data, colWidths=[col_w] * max_cols, repeatRows=1)
                t_style = [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1,
