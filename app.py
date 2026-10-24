import os
import io
import re
import time
import json
import hashlib
import inspect
import threading
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, date
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

# 1. 웹 페이지 기본 설정
st.set_page_config(
    page_title="세무·법령·회계 자율 에이전트",
    page_icon="⚖️",
    layout="wide"
)

# 백그라운드 스레드 및 하위 모듈(law_api, agent) 임포트 전에 st.secrets의 모든 API 키를 환경변수로 최우선 동기화
try:
    if hasattr(st, "secrets"):
        for k, v in st.secrets.items():
            if isinstance(v, (str, int, float)) and k not in os.environ:
                os.environ[k] = str(v).strip()
except Exception:
    pass

# 🔒 ImportError 원천 방지 및 환경변수 동기화 후 안전 임포트
import agent
import law_api
from agent import run_agent

# ---------------------------------------------------------
# 💎 1) 기본 화면 배율 고정(14px 컴팩트) + 2) 1~10번 세로 대화방 우측 신호등 LED + 3) Gemini형 하단 통합 채팅창 CSS
# ---------------------------------------------------------
st.markdown("""
<style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');

/* 1. 브라우저 배율을 줄이지 않아도 캡처 화면처럼 아담하고 한눈에 들어오도록 루트 폰트 크기 고정 */
html {
    font-size: 13.8px !important;
}
html, body, [class*="css"] {
    font-family: 'Pretendard', 'Malgun Gothic', 'Apple SD Gothic Neo', sans-serif;
}

/* 📐 상단 상태바가 Streamlit 헤더(Share 바)에 절대 가려지지 않도록 상단 안전 여백(3.2rem) 확보 */
div.block-container {
    padding-top: 3.2rem !important;
    padding-bottom: 2.5rem !important;
    max-width: 100% !important;
}

/* 🎨 좌측 사이드바 너비 및 컴팩트 여백 고정 */
section[data-testid="stSidebar"] {
    background-color: #f1f5f9 !important;
    border-right: 1px solid #cbd5e1 !important;
    min-width: 270px !important;
    max-width: 285px !important;
}
section[data-testid="stSidebar"] div[data-testid="stSidebarUserContent"] {
    padding-top: 0.65rem !important;
    padding-bottom: 0.5rem !important;
    padding-left: 0.75rem !important;
    padding-right: 0.75rem !important;
}

/* 📦 사이드바 내부 화이트 카드 패딩 및 간격 컴팩트화 */
section[data-testid="stSidebar"] div[data-testid="stVerticalBlockBorderWrapper"] {
    background-color: #ffffff !important;
    border: 1px solid #e2e8f0 !important;
    border-radius: 10px !important;
    padding: 7px 10px !important;
    margin-bottom: 4px !important;
    box-shadow: 0 1px 2px rgba(15, 23, 42, 0.03) !important;
}

/* 사이드바 내부 위젯 간격 */
section[data-testid="stSidebar"] div[data-testid="stVerticalBlock"] {
    gap: 0.32rem !important;
}
section[data-testid="stSidebar"] div[data-testid="stMarkdownContainer"] {
    overflow: visible !important;
}
section[data-testid="stSidebar"] div[data-testid="stTextInput"] input {
    padding-top: 0.28rem !important;
    padding-bottom: 0.28rem !important;
    font-size: 0.82rem !important;
    min-height: 1.9rem !important;
}

/* 사이드바 일반 버튼 높이 컴팩트화 */
section[data-testid="stSidebar"] button {
    min-height: 1.85rem !important;
    padding: 0.15rem 0.5rem !important;
    font-size: 0.8rem !important;
    border-radius: 7px !important;
    font-weight: 600 !important;
}
section[data-testid="stSidebar"] a[data-testid="stBaseLinkButton-secondary"] {
    min-height: 1.85rem !important;
    padding: 0.15rem 0.5rem !important;
    font-size: 0.8rem !important;
    border-radius: 7px !important;
    font-weight: 600 !important;
}

/* 🟢 좌측 사이드바 최상단 모드 전환 2버튼 (모서리 둥근 사각형 박스 + 활성화 시 선명한 녹색) */
.st-key-btn_top_mode_agent button,
.st-key-btn_top_mode_credit button {
    border-radius: 9px !important;
    min-height: 36px !important;
    height: 36px !important;
    padding: 4px 6px !important;
    font-size: 0.82rem !important;
    font-weight: 800 !important;
    letter-spacing: -0.4px !important;
    box-shadow: 0 2px 4px rgba(15, 23, 42, 0.06) !important;
    transition: all 0.15s ease-in-out !important;
}

/* 활성화된 버튼(Primary) -> 선명한 녹색(#16a34a) + 흰색 글씨 */
div.stButton > button[kind="primary"],
div.stButton > button[data-testid="stBaseButton-primary"],
div.stButton > button[data-testid="baseButton-primary"],
.st-key-btn_top_mode_agent button[kind="primary"],
.st-key-btn_top_mode_credit button[kind="primary"] {
    background-color: #16a34a !important;
    border: 1.5px solid #15803d !important;
    color: #ffffff !important;
    border-radius: 9px !important;
    font-weight: 800 !important;
}
div.stButton > button[kind="primary"]:hover,
div.stButton > button[data-testid="stBaseButton-primary"]:hover,
div.stButton > button[data-testid="baseButton-primary"]:hover,
.st-key-btn_top_mode_agent button[kind="primary"]:hover,
.st-key-btn_top_mode_credit button[kind="primary"]:hover,
div.stButton > button[kind="primary"]:active,
div.stButton > button[kind="primary"]:focus:not(:active) {
    background-color: #15803d !important;
    border-color: #166534 !important;
    color: #ffffff !important;
    box-shadow: 0 2px 6px rgba(22, 163, 74, 0.25) !important;
}
div.stButton > button[kind="primary"] p,
div.stButton > button[data-testid="stBaseButton-primary"] p,
.st-key-btn_top_mode_agent button[kind="primary"] p,
.st-key-btn_top_mode_credit button[kind="primary"] p {
    color: #ffffff !important;
    font-weight: 800 !important;
}

/* 비활성화된 상단 모드 버튼(Secondary) -> 깔끔한 화이트 사각형 박스 */
.st-key-btn_top_mode_agent button[kind="secondary"],
.st-key-btn_top_mode_credit button[kind="secondary"],
.st-key-btn_top_mode_agent button[data-testid="stBaseButton-secondary"],
.st-key-btn_top_mode_credit button[data-testid="stBaseButton-secondary"] {
    background-color: #ffffff !important;
    border: 1.5px solid #cbd5e1 !important;
    color: #334155 !important;
    border-radius: 9px !important;
}
.st-key-btn_top_mode_agent button[kind="secondary"]:hover,
.st-key-btn_top_mode_credit button[kind="secondary"]:hover,
.st-key-btn_top_mode_agent button[data-testid="stBaseButton-secondary"]:hover,
.st-key-btn_top_mode_credit button[data-testid="stBaseButton-secondary"]:hover {
    background-color: #f0fdf4 !important;
    border-color: #16a34a !important;
    color: #15803d !important;
}

/* 사이드바 카드 소제목(라벨) 스타일 */
.sb-card-title {
    font-size: 0.82rem;
    font-weight: 800;
    color: #0f172a;
    line-height: 1.3 !important;
    padding-top: 0px !important;
    padding-bottom: 2px !important;
    margin-bottom: 2px !important;
    display: flex;
    align-items: center;
    justify-content: space-between;
    letter-spacing: -0.3px;
}
.sb-badge-green {
    background-color: #dcfce7;
    color: #15803d;
    font-size: 0.68rem;
    font-weight: 700;
    padding: 1px 6px;
    border-radius: 999px;
    line-height: 1.2 !important;
}
.sb-badge-amber {
    background-color: #fef3c7;
    color: #b45309;
    font-size: 0.68rem;
    font-weight: 700;
    padding: 1px 6px;
    border-radius: 999px;
    line-height: 1.2 !important;
}
.sb-badge-pro {
    background-color: #dbeafe;
    color: #1d4ed8;
    font-size: 0.68rem;
    font-weight: 700;
    padding: 1px 6px;
    border-radius: 999px;
    line-height: 1.2 !important;
}

/* 🚦 좌측 1~10번 대화방 세로 클릭 버튼 + 우측 동그라미 신호등 LED 스타일 */
@keyframes trafficPulse {
    0%   { background-color: #ef4444; box-shadow: 0 0 6px #ef4444; }
    50%  { background-color: #f97316; box-shadow: 0 0 7px #f97316; }
    100% { background-color: #eab308; box-shadow: 0 0 6px #eab308; }
}

div[class*="st-key-room_btn_"] button {
    position: relative !important;
    min-height: 1.62rem !important;
    height: 1.62rem !important;
    padding: 0.1rem 1.6rem 0.1rem 0.5rem !important;
    display: flex !important;
    justify-content: flex-start !important;
    align-items: center !important;
    border-radius: 6px !important;
    margin-bottom: 0px !important;
    transition: all 0.12s ease !important;
    box-shadow: none !important;
}
div[class*="st-key-room_btn_"] button p {
    font-size: 0.74rem !important;
    margin: 0 !important;
    white-space: nowrap !important;
    overflow: hidden !important;
    text-overflow: ellipsis !important;
    text-align: left !important;
    letter-spacing: -0.3px !important;
}
/* 우측 끝 동그라미(LED) 공통 */
div[class*="st-key-room_btn_"] button::after {
    content: "" !important;
    width: 8px !important;
    height: 8px !important;
    border-radius: 50% !important;
    position: absolute !important;
    right: 8px !important;
    top: 50% !important;
    transform: translateY(-50%) !important;
}
/* 상태 1: 작성된 글이 없을 때 (0건, 비선택) -> 칸 기본 배경 + 우측 동그라미 불 꺼짐 */
div[class*="st-key-room_btn_"][class*="_empty"] button {
    background-color: #f8fafc !important;
    border: 1px solid #e2e8f0 !important;
    color: #64748b !important;
}
div[class*="st-key-room_btn_"][class*="_empty"] button p {
    color: #64748b !important;
    font-weight: 500 !important;
}
div[class*="st-key-room_btn_"][class*="_empty"] button::after {
    background-color: transparent !important;
    border: 1.5px solid #cbd5e1 !important;
}
/* 상태 2: 작성된 글이 있을 때 (1건 이상, 비선택) -> 칸 화이트 + 우측 동그라미 초록불 점등 */
div[class*="st-key-room_btn_"][class*="_hasmsg"] button {
    background-color: #ffffff !important;
    border: 1px solid #cbd5e1 !important;
    color: #1e293b !important;
}
div[class*="st-key-room_btn_"][class*="_hasmsg"] button p {
    color: #1e293b !important;
    font-weight: 600 !important;
}
div[class*="st-key-room_btn_"][class*="_hasmsg"] button::after {
    background-color: #22c55e !important;
    border: 1px solid #16a34a !important;
    box-shadow: 0 0 4px rgba(34, 197, 94, 0.45) !important;
}
/* 상태 3: 현재 선택된 대화방 -> 지금처럼 칸 전체가 연녹색으로 불이 들어옴 + 우측 초록불 */
div[class*="st-key-room_btn_"][class*="_active"] button {
    background-color: #dcfce7 !important;
    border: 1.5px solid #22c55e !important;
    color: #15803d !important;
}
div[class*="st-key-room_btn_"][class*="_active"] button p {
    color: #15803d !important;
    font-weight: 800 !important;
}
div[class*="st-key-room_btn_"][class*="_active"] button::after {
    background-color: #16a34a !important;
    border: 1px solid #15803d !important;
    box-shadow: 0 0 5px rgba(22, 163, 74, 0.65) !important;
}
/* 상태 4: 백그라운드 작성(분석) 중일 때 -> 우측 동그라미가 빨간색↔주황색↔노란색으로 실시간 변색! */
div[class*="st-key-room_btn_"][class*="_running"] button::after {
    border: none !important;
    animation: trafficPulse 1.1s infinite alternate ease-in-out !important;
}

div[class*="st-key-room_btn_"] button:hover {
    border-color: #16a34a !important;
    background-color: #f0fdf4 !important;
}

/* 우측 상단 미니 상태바 (큰 제목 h1 대체, 상단 잘림 완벽 해결) */
.top-mini-status-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    background-color: #f8fafc;
    border: 1px solid #cbd5e1;
    border-left: 4px solid #16a34a;
    border-radius: 8px;
    padding: 7px 14px;
    margin-top: 2px;
    margin-bottom: 12px;
    font-size: 0.88rem;
    color: #1e293b;
    box-shadow: 0 1px 2px rgba(15, 23, 42, 0.03);
}

/* 💬 하단 Gemini 스타일 통합 채팅 입력창 (드래그 앤 드롭 시 입력칸 자체가 넓어지며 파일 표시) */
div[data-testid="stChatInput"] {
    border-radius: 16px !important;
}
div[data-testid="stChatInput"] > div {
    border-radius: 16px !important;
    border: 1.5px solid #cbd5e1 !important;
    background-color: #ffffff !important;
    box-shadow: 0 4px 12px rgba(15, 23, 42, 0.06) !important;
    padding: 4px 8px !important;
    transition: all 0.15s ease-in-out !important;
}
div[data-testid="stChatInput"] > div:focus-within {
    border-color: #16a34a !important;
    box-shadow: 0 4px 14px rgba(22, 163, 74, 0.15) !important;
}
div[data-testid="stChatInput"] textarea {
    font-size: 0.92rem !important;
    line-height: 1.45 !important;
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
    margin-top: 20px !important;
    margin-bottom: 10px !important;
    font-size: 1.15rem !important;
    font-weight: 700 !important;
}

/* 보고서 소제목 (#### (1) 상세 법리 등) */
div[data-testid="stChatMessageContent"] h4 {
    color: #1e40af !important;
    margin-top: 14px !important;
    margin-bottom: 6px !important;
    font-size: 1.02rem !important;
    font-weight: 700 !important;
}

/* 본문 근거 태그 및 3. 관련법령 조문 직링크 스타일 */
div[data-testid="stChatMessageContent"] a {
    color: #1d4ed8 !important;
    font-weight: 600 !important;
    text-decoration: none !important;
}
div[data-testid="stChatMessageContent"] a:hover {
    text-decoration: underline !important;
    color: #15803d !important;
}

/* 마크다운 표(Table) 엔터프라이즈 네이비 스타일링 (본문 및 상단 신·구법 비교 배너 공통) */
div[data-testid="stChatMessageContent"] table,
div[data-testid="stExpander"] table,
.law-diff-banner-box table {
    width: 100%;
    border-collapse: collapse;
    margin: 10px 0 14px 0;
    font-size: 0.9rem;
    border-radius: 6px;
    overflow: hidden;
    box-shadow: 0 1px 3px rgba(0,0,0,0.05);
}
div[data-testid="stChatMessageContent"] th,
div[data-testid="stExpander"] th,
.law-diff-banner-box th {
    background-color: #1e293b !important;
    color: #ffffff !important;
    font-weight: 600 !important;
    padding: 8px 11px !important;
    border: 1px solid #334155 !important;
    text-align: left !important;
}
div[data-testid="stChatMessageContent"] td,
div[data-testid="stExpander"] td,
.law-diff-banner-box td {
    padding: 8px 11px !important;
    border: 1px solid #cbd5e1 !important;
    color: #1e293b;
    background-color: #ffffff;
}
div[data-testid="stChatMessageContent"] tr:nth-child(even) td,
div[data-testid="stExpander"] tr:nth-child(even) td,
.law-diff-banner-box tr:nth-child(even) td {
    background-color: #f8fafc;
}

/* 상단 모드 안내 인용구 박스 (> ⚡ / > 🧠) */
div[data-testid="stChatMessageContent"] blockquote {
    background-color: #f8fafc;
    border-left: 4px solid #22c55e;
    padding: 7px 12px;
    border-radius: 6px;
    color: #334155;
    font-size: 0.88rem;
    margin-bottom: 10px;
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
# 0. 작업공간 · API 만료일 · 🎯 맥락 연동형 법령 레이더 (개정이유서 심층 추출 및 접이식 신·구 비교표 배너 포함)
# ---------------------------------------------------------
ROOM_IDS = [f"대화방 {i}" for i in range(1, 11)]
STORAGE_DIR = ".workspace_storage"
WORKSPACE_STORAGE_DIR = STORAGE_DIR
os.makedirs(STORAGE_DIR, exist_ok=True)
EXPIRY_FILE_PATH = os.path.join(STORAGE_DIR, "api_expiry_dates.json")
ROOM_LAW_ACK_PATH = os.path.join(STORAGE_DIR, "room_law_ack.json")

WATCHED_TAX_LAWS = [
    "국세기본법",
    "법인세법",
    "소득세법",
    "부가가치세법",
    "조세특례제한법",
    "상속세 및 증여세법",
    "지방세법",
    "농어촌특별세법",
    "근로기준법"
]

def _get_law_oc() -> str:
    """agent.py, law_api.py, config.py, st.secrets, 환경변수에서 법제처 OC 키(LAW_OPEN_API_KEY 최우선)를 자동 추출합니다."""
    if hasattr(agent, "get_law_oc_auto"):
        val = agent.get_law_oc_auto()
        if val:
            return val
    for k in ["LAW_OPEN_API_KEY", "LAW_API_OC", "OC", "LAW_OC", "LAW_API_KEY", "MOLEG_OC", "DRF_OC"]:
        try:
            if hasattr(st, "secrets") and k in st.secrets and str(st.secrets[k]).strip():
                return str(st.secrets[k]).strip()
        except Exception:
            pass
        if os.getenv(k, "").strip():
            return os.getenv(k, "").strip()
    for attr in ["LAW_OPEN_API_KEY", "OC", "LAW_API_OC", "LAW_OC", "LAW_API_KEY", "API_KEY", "USER_OC", "oc"]:
        val = getattr(law_api, attr, None)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""

def _fmt_ymd_str(raw_ymd: str) -> str:
    s = re.sub(r"[^0-9]", "", str(raw_ymd or ""))
    if len(s) == 8:
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return str(raw_ymd or "-")

@st.cache_data(ttl=43200, show_spinner=False)
def fetch_latest_tax_law_promulgations() -> dict[str, dict]:
    today_d = datetime.now(ZoneInfo("Asia/Seoul")).date()
    today_int = int(today_d.strftime("%Y%m%d"))
    results_map = {}

    for base_name in WATCHED_TAX_LAWS:
        for suffix in ("", " 시행령"):
            law_name = base_name + suffix
            try:
                raw_res = law_api.search_law_data(law_name, "law")
                if not raw_res:
                    continue
                if isinstance(raw_res, dict):
                    raw_res = [raw_res]

                target_clean = law_name.replace(" ", "")
                exact_matches = [
                    it for it in raw_res
                    if str(it.get("법령명한글", "")).replace(" ", "") == target_clean
                ]
                candidates = exact_matches if exact_matches else raw_res[:1]
                candidates.sort(
                    key=lambda x: (str(x.get("공포일자", "")), str(x.get("시행일자", ""))),
                    reverse=True
                )
                top = candidates[0]
                prom_raw = str(top.get("공포일자", "")).strip()
                enf_raw = str(top.get("시행일자", "")).strip()
                prom_no = str(top.get("공포번호", "")).strip()
                rev_type = str(top.get("제개정구분명", "개정")).strip()
                law_id = str(top.get("법령일련번호") or top.get("ID") or "").strip()
                mst_id = str(top.get("법령일련번호") or top.get("MST") or law_id).strip()

                days_since_prom = 9999
                if len(prom_raw) == 8 and prom_raw.isdigit():
                    try:
                        prom_d = datetime.strptime(prom_raw, "%Y%m%d").date()
                        days_since_prom = (today_d - prom_d).days
                    except Exception:
                        pass

                is_future_enforcement = bool(len(enf_raw) == 8 and enf_raw.isdigit() and int(enf_raw) > today_int)
                is_recent_promulgation = (0 <= days_since_prom <= 60)

                results_map[target_clean] = {
                    "law_name": law_name,
                    "clean_name": target_clean,
                    "prom_date": _fmt_ymd_str(prom_raw),
                    "prom_raw": prom_raw,
                    "enf_date": _fmt_ymd_str(enf_raw),
                    "enf_raw": enf_raw,
                    "prom_no": prom_no,
                    "rev_type": rev_type,
                    "law_id": law_id,
                    "mst_id": mst_id,
                    "days_since_prom": days_since_prom,
                    "is_future_enforcement": is_future_enforcement,
                    "is_recent_promulgation": is_recent_promulgation,
                    "version_key": f"{prom_raw}_{prom_no}_{enf_raw}"
                }
            except Exception:
                continue
    return results_map

@st.cache_data(ttl=43200, show_spinner=False)
def fetch_official_revision_reason_zero_token(law_id: str, law_name: str, mst_id: str = "", enf_raw: str = "") -> str:
    """
    [해결 완료] 법제처 XML에서 제·개정이유서(입법이유)가 비어 나오던 문제를 해결하기 위해:
    1) MST / ID 기반 lsRsn, eflaw, law 타겟 다중 조회
    2) 최신 공포본이 단순 '타법개정'이어서 개정이유서가 비어 있는 경우, 연혁 검색(eflaw)을 통해
       가장 최근 '일부개정' 공포본의 입법이유서 및 부칙까지 자동으로 추적하여 추출합니다.
    """
    oc = _get_law_oc()
    if not oc:
        return "❌ 법제처 API 인증키(OC)를 확인할 수 없습니다."

    def _extract_from_xml_urls(url_list: list[str]) -> tuple[list[str], list[str], list[str]]:
        r_list, a_list, s_list = [], [], []
        for u in url_list:
            try:
                req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=12) as resp:
                    xml_bytes = resp.read()
                root = ET.fromstring(xml_bytes)
                for elem in root.iter():
                    t_name = elem.tag.strip()
                    txt = (elem.text or "").strip()
                    if not txt:
                        continue
                    if t_name in ("제개정이유내용", "제개정이유", "개정이유", "주요내용"):
                        if txt not in r_list:
                            r_list.append(txt)
                    elif t_name in ("개정문내용", "개정문"):
                        if txt not in a_list:
                            a_list.append(txt)
                    elif t_name in ("부칙내용",) and len(s_list) < 3:
                        if txt not in s_list:
                            s_list.append(txt)
                if r_list:
                    break
            except Exception:
                continue
        return r_list, a_list, s_list

    use_mst = mst_id or law_id
    primary_urls = []
    if use_mst:
        primary_urls.extend([
            f"http://www.law.go.kr/DRF/lawService.do?OC={oc}&target=law&MST={use_mst}&type=XML",
            f"http://www.law.go.kr/DRF/lawService.do?OC={oc}&target=lsRsn&MST={use_mst}&type=XML",
            f"http://www.law.go.kr/DRF/lawService.do?OC={oc}&target=law&ID={use_mst}&type=XML",
            f"http://www.law.go.kr/DRF/lawService.do?OC={oc}&target=lsRsn&ID={use_mst}&type=XML",
        ])
        if enf_raw and len(str(enf_raw)) == 8:
            primary_urls.insert(1, f"http://www.law.go.kr/DRF/lawService.do?OC={oc}&target=eflaw&MST={use_mst}&efYd={enf_raw}&type=XML")

    reason_texts, amend_texts, supp_texts = _extract_from_xml_urls(primary_urls)

    # 만약 최신 공포본이 '타법개정' 등이라 개정이유서가 비어 있다면, 연혁 검색에서 가장 최근 '일부개정' MST를 찾아 입법이유서를 가져옴
    fallback_rev_note = ""
    if not reason_texts and law_name:
        try:
            enc_q = urllib.parse.quote(law_name.strip())
            target_clean = law_name.replace(" ", "").strip()
            search_u = f"http://www.law.go.kr/DRF/lawSearch.do?OC={oc}&target=eflaw&type=XML&query={enc_q}&display=20"
            req_s = urllib.request.Request(search_u, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req_s, timeout=10) as resp_s:
                s_root = ET.fromstring(resp_s.read())
            hist_cands = []
            for l_node in s_root.findall(".//law"):
                lname = (l_node.findtext("법령명한글") or "").strip()
                if lname.replace(" ", "") != target_clean:
                    continue
                rev_gbn = (l_node.findtext("제개정구분명") or "").strip()
                h_mst = (l_node.findtext("법령일련번호") or l_node.findtext("MST") or "").strip()
                h_ef = (l_node.findtext("시행일자") or "").strip()
                h_anc = (l_node.findtext("공포일자") or "").strip()
                h_no = (l_node.findtext("공포번호") or "").strip()
                if h_mst and h_mst != use_mst:
                    priority = 1 if "일부개정" in rev_gbn or "전부개정" in rev_gbn else 0
                    hist_cands.append((priority, h_anc, h_ef, h_mst, rev_gbn, h_no))
            hist_cands.sort(reverse=True)
            for _, h_anc, h_ef, h_mst, rev_gbn, h_no in hist_cands[:3]:
                fb_urls = [
                    f"http://www.law.go.kr/DRF/lawService.do?OC={oc}&target=law&MST={h_mst}&type=XML",
                    f"http://www.law.go.kr/DRF/lawService.do?OC={oc}&target=eflaw&MST={h_mst}&efYd={h_ef}&type=XML",
                ]
                r2, a2, s2 = _extract_from_xml_urls(fb_urls)
                if r2 or a2:
                    reason_texts = r2 or reason_texts
                    amend_texts = a2 or amend_texts
                    supp_texts = s2 or supp_texts
                    fallback_rev_note = f"※ 최신 공포본이 단순 타법개정이어서 직전 본개정(공포일: {_fmt_ymd_str(h_anc)}, 제{h_no}호 {rev_gbn})의 공식 입법이유서를 함께 표시합니다.\n\n"
                    break
        except Exception:
            pass

    out_parts = []
    if fallback_rev_note:
        out_parts.append(fallback_rev_note.strip())
    if reason_texts:
        out_parts.append("📌 [공식 제·개정이유 및 주요내용 (입법이유)]\n" + "\n\n".join(dict.fromkeys(reason_texts)))
    if amend_texts:
        out_parts.append("📌 [공포 개정문 원문 발췌]\n" + amend_texts[0][:2500])
    if supp_texts and not reason_texts:
        out_parts.append("📌 [최신 개정 부칙 (시행일 및 적용례)]\n" + "\n\n".join(supp_texts)[:2000])

    if out_parts:
        return "\n\n" + ("\n\n" + "-" * 50 + "\n\n").join(out_parts)

    return (
        f"ℹ️ 「{law_name}」의 해당 공포본 XML에 별도 제·개정이유 텍스트가 수록되어 있지 않습니다. "
        "우측의 '⚡ 신·구법 비교' 배너 버튼을 누르시면 인용된 조문 기준 [조문명 / 구법내용 / 개정법내용 / 개정효과] 비교표를 즉시 확인하실 수 있습니다."
    )

def load_room_law_ack() -> dict:
    if os.path.exists(ROOM_LAW_ACK_PATH):
        try:
            with open(ROOM_LAW_ACK_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_room_law_ack(ack_data: dict) -> None:
    try:
        with open(ROOM_LAW_ACK_PATH, "w", encoding="utf-8") as f:
            json.dump(ack_data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def extract_cited_laws_in_room(messages: list[dict], law_prom_map: dict[str, dict]) -> list[dict]:
    if not messages or not law_prom_map:
        return []
    blob = "\n".join(m.get("content", "") for m in messages if m.get("role") == "assistant")
    if not blob:
        return []

    found_clean_names = set()
    for m in re.finditer(r"\[조문\s*:\s*([^\]]+)\]", blob):
        val = m.group(1)
        val_clean = re.sub(r"제\s*\d+\s*조.*", "", val).replace(" ", "").replace("「", "").replace("」", "").strip()
        if val_clean in law_prom_map:
            found_clean_names.add(val_clean)
        elif val_clean.endswith("시행규칙"):
            base_c = val_clean.replace("시행규칙", "")
            if base_c in law_prom_map:
                found_clean_names.add(base_c)

    return [law_prom_map[cname] for cname in sorted(found_clean_names)]

def extract_cited_law_articles_in_room(messages: list[dict]) -> list[str]:
    """대화방 답변에서 실제 인용된 [조문:법령명 제N조...] 목록을 중복 없이 추출합니다."""
    if not messages:
        return []
    blob = "\n".join(m.get("content", "") for m in messages if m.get("role") == "assistant")
    cited_articles = []
    for m in re.finditer(r"\[조문\s*:\s*([^\]]+)\]", blob):
        art_str = m.group(1).strip()
        if art_str and art_str not in cited_articles:
            cited_articles.append(art_str)
    return cited_articles

def generate_banner_law_diff_table(
    messages: list[dict],
    rev_alerts: list[dict],
    room_key: str = ""
) -> str:
    """
    [해결 완료] 채팅창의 대화를 늘리지 않고, 상단 배너 안에서 열고 닫을 수 있는
    단순 명쾌한 4열 마크다운 표(| 조문명 | 구법내용 | 개정법내용 | 개정효과 |)를 생성합니다.
    """
    pool = agent.get_live_gemini_key_pool() if hasattr(agent, "get_live_gemini_key_pool") else []
    api_key = pool[0][1] if pool else (os.getenv("GEMINI_PAID_KEY") or os.getenv("GEMINI_API_KEY") or "")
    if not api_key:
        return "❌ Gemini API 키가 설정되어 있지 않아 비교표를 생성할 수 없습니다."

    cited_articles = extract_cited_law_articles_in_room(messages)
    laws_desc = ", ".join(
        f"「{it['law_name']}」(공포일:{it['prom_date']}, 시행일:{it['enf_date']}, 제{it['prom_no']}호 {it['rev_type']})"
        for it in rev_alerts
    )

    # 인용된 조문 원문 및 개정이유서를 법제처에서 직접 조회하여 프롬프트에 주입 (할루시네이션 차단)
    fetched_snippets = []
    for it in rev_alerts[:3]:
        rsn_txt = fetch_official_revision_reason_zero_token(
            it["law_id"], it["law_name"], it.get("mst_id", ""), it.get("enf_raw", "")
        )
        if rsn_txt and not rsn_txt.startswith("❌"):
            fetched_snippets.append(f"[{it['law_name']} 공식 개정이유/개정문]\n{rsn_txt[:2500]}")

        for art_ref in cited_articles[:5]:
            if it["clean_name"] in art_ref.replace(" ", ""):
                m_jo = re.search(r"제\s*\d+\s*조(?:\s*의\s*\d+)?", art_ref)
                jo_filter = m_jo.group(0).replace(" ", "") if m_jo else ""
                if jo_filter:
                    try:
                        art_content = law_api.get_law_content(it["law_id"], "law", jo_filter)
                        if art_content and not str(art_content).startswith("❌"):
                            fetched_snippets.append(f"[{art_ref} 현행 원문]\n{art_content[:1800]}")
                    except Exception:
                        pass

    last_user_q = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            last_user_q = m.get("content", "")[:600]
            break

    ref_context = "\n\n".join(fetched_snippets) if fetched_snippets else "인용 조문 기준 조회"
    cited_str = ", ".join(cited_articles) if cited_articles else laws_desc

    prompt = (
        "당신은 대한민국 세법 개정 비교 전문가입니다.\n"
        f"현재 대화방에서 검토한 질문 요지: {last_user_q}\n"
        f"이 방에서 인용된 조문: {cited_str}\n"
        f"관련 개정 법령 정보: {laws_desc}\n\n"
        f"[법제처 조회 원문 및 개정이유서]\n{ref_context}\n\n"
        "위 자료를 바탕으로, 본문 대화와 별도로 상단 배너에서 한눈에 확인하고 열고 닫을 수 있도록 "
        "인사말이나 부연 설명 없이 **오직 아래 4개 열로 구성된 마크다운 표(Table)만** 출력하세요.\n\n"
        "| 조문명 | 구법내용 | 개정법내용 | 개정효과 |\n"
        "| :--- | :--- | :--- | :--- |\n\n"
        "- 조문명: 인용된 조문(예: 「국세기본법」 제47조의3 등) 및 관련 주요 개정 조문\n"
        "- 구법내용: 종전 규정 핵심 요약\n"
        "- 개정법내용: 개정(또는 시행예정) 규정 핵심 요약 (타법개정·조문변동 없음인 경우 '종전과 동일(타법개정 등)'으로 명시)\n"
        "- 개정효과: 시행일(적용시기) 및 이 대화방의 질문 사안에 미치는 실무상 영향 요약"
    )

    m_id = getattr(agent, "FLASH_MODEL_ID", "gemini-3.8-flash")
    try:
        client = genai.Client(api_key=api_key, http_options={"timeout": 60000})
        resp = client.models.generate_content(model=m_id, contents=prompt)
        out_txt = agent.extract_safe_text(resp) if hasattr(agent, "extract_safe_text") else (resp.text or "")
        um = getattr(resp, "usage_metadata", None)
        in_tok = int(getattr(um, "prompt_token_count", 0) or 1000)
        out_tok = int(getattr(um, "candidates_token_count", 0) or 400)
        _log_custom_tokens(m_id, in_tok, out_tok, count_call=True, room_key=room_key)
        return out_txt.strip() or "비교표를 생성하지 못했습니다."
    except Exception as e:
        return f"❌ 신·구법 비교표 배너 생성 중 오류 발생: {e}"

def get_room_revision_alerts(ws_id: str, room_id: str, messages: list[dict], law_prom_map: dict[str, dict]) -> tuple[list[dict], bool]:
    cited_list = extract_cited_laws_in_room(messages, law_prom_map)
    if not cited_list:
        return [], False

    ack_all = load_room_law_ack()
    room_key = f"{ws_id}::{room_id}"
    room_ack = ack_all.get(room_key, {})

    post_rev_alerts = []
    recent_info_alerts = []

    for item in cited_list:
        cname = item["clean_name"]
        vkey = item["version_key"]
        acked_vkey = room_ack.get(cname)

        if acked_vkey == vkey:
            continue
        if acked_vkey is not None and acked_vkey != vkey:
            post_rev_alerts.append(item)
        elif item["is_recent_promulgation"] or item["is_future_enforcement"]:
            recent_info_alerts.append(item)

    if post_rev_alerts:
        return post_rev_alerts, True
    return recent_info_alerts, False

def acknowledge_room_laws(ws_id: str, room_id: str, law_items: list[dict]) -> None:
    ack_all = load_room_law_ack()
    room_key = f"{ws_id}::{room_id}"
    room_ack = ack_all.get(room_key, {})
    for it in law_items:
        room_ack[it["clean_name"]] = it["version_key"]
    ack_all[room_key] = room_ack
    save_room_law_ack(ack_all)

DEFAULT_API_EXPIRY_CONFIG = {
    "VWORLD": {
        "name": "브이월드(공시지가) API",
        "secret_key": "VWORLD_EXPIRY_DATE",
        "default_date": "2027-04-20",
        "cycle": "6개월",
        "url": "https://www.vworld.kr/dev/v4dv_apikey_s001.do"
    },
    "DATA_GO_KR": {
        "name": "공공데이터포털(국세청·실거래가) API",
        "secret_key": "DATA_GO_KR_EXPIRY_DATE",
        "default_date": "2028-10-20",
        "cycle": "2년",
        "url": "https://www.data.go.kr/iim/api/selectAcountList.do"
    },
    "BOK_ECOS": {
        "name": "한국은행(ECOS 환율·금리) API",
        "secret_key": "BOK_EXPIRY_DATE",
        "default_date": "2028-10-20",
        "cycle": "2년",
        "url": "https://ecos.bok.or.kr/api/#/MyPage/CertKeyInfo"
    }
}

def load_api_expiry_dates() -> dict:
    saved = {}
    if os.path.exists(EXPIRY_FILE_PATH):
        try:
            with open(EXPIRY_FILE_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
        except Exception:
            pass
    result = {}
    for code, info in DEFAULT_API_EXPIRY_CONFIG.items():
        env_val = os.getenv(info["secret_key"], "").strip()
        result[code] = saved.get(code) or env_val or info["default_date"]
    return result

def save_api_expiry_dates(expiry_dict: dict) -> None:
    try:
        with open(EXPIRY_FILE_PATH, "w", encoding="utf-8") as f:
            json.dump(expiry_dict, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ 만료일 저장 오류: {e}")

def check_api_expiry_alerts() -> tuple[list[dict], list[dict]]:
    expiry_map = load_api_expiry_dates()
    today_d = datetime.now(ZoneInfo("Asia/Seoul")).date()
    alerts = []
    all_status = []

    for code, info in DEFAULT_API_EXPIRY_CONFIG.items():
        d_str = expiry_map.get(code, info["default_date"])
        try:
            exp_d = datetime.strptime(d_str, "%Y-%m-%d").date()
        except Exception:
            exp_d = date(2027, 4, 20)
        days_left = (exp_d - today_d).days
        fmt_kor = f"{str(exp_d.year)[2:]}년 {exp_d.month:02d}월 {exp_d.day:02d}일"

        item_data = {
            "code": code,
            "name": info["name"],
            "date_str": exp_d.strftime("%Y-%m-%d"),
            "fmt_kor": fmt_kor,
            "days_left": days_left,
            "cycle": info["cycle"],
            "url": info["url"]
        }
        all_status.append(item_data)

        if days_left < 0:
            item_data["level"] = "expired"
            item_data["msg"] = (
                f"🚨 **[{info['name']} 만료됨]** 키가 **{fmt_kor}**자로 만료되었습니다(D+{-days_left}). "
                "새로운 API키를 발급받아주세요."
            )
            alerts.append(item_data)
        elif days_left <= 30:
            item_data["level"] = "warning"
            item_data["msg"] = (
                f"⚠️ **[API 만료 임박 알림]** **{info['name']}** 키가 **{fmt_kor}**자로 만료예정입니다(D-{days_left}). "
                "새로운 API키를 발급받아주세요."
            )
            alerts.append(item_data)

    return alerts, all_status

@st.cache_resource
def get_background_task_manager() -> dict:
    return {"tasks": {}, "lock": threading.Lock()}

def _log_custom_tokens(model_id: str, in_tok: int, out_tok: int, count_call: bool = True, room_key: str = "") -> None:
    if hasattr(agent, "_record_token_usage"):
        try:
            agent._record_token_usage(model_id, in_tok, out_tok, count_call=count_call, room_key=room_key)
            return
        except Exception:
            pass

def _check_api_configured(key_names: list[str]) -> bool:
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
    safe_hash = hashlib.sha256(workspace_id.strip().encode("utf-8")).hexdigest()[:16]
    return os.path.join(STORAGE_DIR, f"ws_{safe_hash}.json")

def _normalize_room_file_entry(entry: dict) -> dict:
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
    default_titles = {r_id: "빈 대화방" for r_id in ROOM_IDS}
    default_titles["대화방 1"] = "메인 대화"
    return {
        "chat_rooms": {r_id: [] for r_id in ROOM_IDS},
        "room_titles": default_titles,
        "room_files": {r_id: {"name": None, "text": "", "items": []} for r_id in ROOM_IDS},
        "room_diff_banners": {r_id: "" for r_id in ROOM_IDS}
    }

def load_workspace_from_disk(workspace_id: str) -> dict:
    path = get_storage_path(workspace_id)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            default_data = get_default_workspace_data()
            for key in ["chat_rooms", "room_titles", "room_files", "room_diff_banners"]:
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
    if not workspace_id:
        return
    path = get_storage_path(workspace_id)
    data = {
        "chat_rooms": st.session_state.chat_rooms,
        "room_titles": st.session_state.room_titles,
        "room_files": st.session_state.room_files,
        "room_diff_banners": st.session_state.get("room_diff_banners", {r_id: "" for r_id in ROOM_IDS})
    }
    try:
        with get_background_task_manager()["lock"]:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ 자동 저장 오류: {e}")

def delete_workspace_from_disk(workspace_id: str):
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
    room_key = f"{ws_id}::{room_id}"
    try:
        response_text = run_agent(
            user_input=full_input,
            raw_query=raw_query,
            has_file=has_file,
            room_key=room_key
        )
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

def _ocr_with_gemini_flash(file_bytes: bytes, mime_type: str, filename: str, room_key: str = "") -> str:
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
            out_tok = (
                int(getattr(um, "candidates_token_count", 0) or max(200, int(len(extracted) * 0.7)))
                + int(getattr(um, "thoughts_token_count", 0) or 0)
            )
            _log_custom_tokens(m_id, in_tok, out_tok, count_call=True, room_key=room_key)
            if extracted.strip():
                return f"[📸 AI 비전 OCR 자동 판독 완료: {filename}]\n{extracted.strip()}"
        except Exception as e:
            last_err = str(e)
            continue
    return f"❌ 이미지/스캔본 OCR 판독 실패 ({filename}): {last_err}"

def extract_file_content(uploaded_file, room_key: str = "") -> str:
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
                return _ocr_with_gemini_flash(raw_bytes, "application/pdf", filename, room_key=room_key)[:MAX_DOC_CHARS_PRO]
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
            return _ocr_with_gemini_flash(raw_bytes, mime, filename, room_key=room_key)[:MAX_DOC_CHARS_PRO]

        return "지원하지 않는 파일 형식입니다."
    except Exception as e:
        return f"❌ 파일 읽기 오류: {e}"

# ---------------------------------------------------------
# 공통 정제 도우미 (PDF/워드/엑셀/복사 시 직링크 URL 인코딩 문자열 깔끔 정리)
# ---------------------------------------------------------
def _sanitize_math_text(text: str) -> str:
    if not text:
        return ""
    s = text
    s = re.sub(r"\[(\[(?:판례|심판례|해석례|예규|조문)\s*:\s*[^\]]+\])\]\((https?://[^\s)]+)\)", r"\1", s)
    s = re.sub(r"\[([^\n]+?)\]\((https?://(?:www\.)?law\.go\.kr/[^\s)]+)\)", r"\1", s)

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
    cleaned = _sanitize_math_text(report_text)
    out_lines = []
    for line in cleaned.split("\n"):
        if line.strip().startswith(">"):
            continue
        out_lines.append(line)
    return "\n".join(out_lines).strip()

def create_excel_from_markdown_tables(report_text: str) -> bytes | None:
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
# 헬퍼 함수 3: 정식 PDF 직접 생성 엔진 (+ 📕 하단 면책문구 여백 최적화 완료)
# ---------------------------------------------------------
def _ensure_korean_font() -> tuple[str, str]:
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
    return re.sub(r"[\U00010000-\U0010ffff]", "", text or "")

def _md_to_rl_xml(text: str, bold_font: str) -> str:
    s = _strip_emojis_for_pdf(text).strip()
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    s = re.sub(r"\*\*(.+?)\*\*", rf'<font name="{bold_font}">\1</font>', s)
    s = re.sub(r"`([^`]+)`", r'<font backColor="#f1f5f9">\1</font>', s)
    return s

def _draw_page_footer(canvas, doc):
    canvas.saveState()
    reg_font, _ = _ensure_korean_font()

    canvas.setStrokeColor(colors.HexColor("#e2e8f0"))
    canvas.setLineWidth(0.6)
    canvas.line(40, 36, A4[0] - 40, 36)

    canvas.setFont(reg_font, 6.2)
    canvas.setFillColor(colors.HexColor("#64748b"))
    disclaimer_str = (
        "※ 본 보고서는 질의하신 사실관계와 현행 법령 기준의 참고자료이며, "
        "사실관계 변동이나 과세관청·법원의 해석에 따라 판단이 달라질 수 있습니다."
    )
    canvas.drawString(40, 24, disclaimer_str)

    canvas.setFont(reg_font, 8.2)
    canvas.setFillColor(colors.HexColor("#475569"))
    page_num_str = f"- {doc.page} -"
    canvas.drawRightString(A4[0] - 40, 24, page_num_str)
    canvas.restoreState()

def create_pdf_report(report_text: str) -> bytes:
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
        bottomMargin=48
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
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ]
                for r_idx in range(1, len(pdf_table_data)):
                    if r_idx % 2 == 0:
                        t_style.append(("BACKGROUND", (0, r_idx), (-1, r_idx), colors.HexColor("#f8fafc")))
                pdf_table.setStyle(TableStyle(t_style))
                story.append(Spacer(1, 4))
                story.append(pdf_table)
                story.append(Spacer(1, 8))
            continue

        if stripped.startswith("#### "):
            story.append(Paragraph(_md_to_rl_xml(stripped[5:], bold_font), style_h3))
        elif stripped.startswith("### "):
            story.append(Paragraph(_md_to_rl_xml(stripped[4:], bold_font), style_h2))
        elif stripped.startswith("## "):
            story.append(Paragraph(_md_to_rl_xml(stripped[3:], bold_font), style_h2))
        elif stripped.startswith("# "):
            story.append(Paragraph(_md_to_rl_xml(stripped[2:], bold_font), style_h2))
        elif stripped.startswith(("- ", "* ")):
            indent_level = (len(line) - len(line.lstrip(" "))) // 2
            b_style = ParagraphStyle(
                f"Bullet_{indent_level}", parent=style_bullet,
                leftIndent=12 + (indent_level * 10)
            )
            story.append(Paragraph("• " + _md_to_rl_xml(stripped[2:], bold_font), b_style))
        else:
            story.append(Paragraph(_md_to_rl_xml(stripped, bold_font), style_body))

        i += 1

    if not story:
        story.append(Paragraph("내용 없음", style_body))

    doc.build(story, onFirstPage=_draw_page_footer, onLaterPages=_draw_page_footer)
    buffer.seek(0)
    return buffer.getvalue()

# ---------------------------------------------------------
# 헬퍼 함수 4: 질문/원클릭 액션 통합 백그라운드 실행기
# ---------------------------------------------------------
def _trigger_agent_task(
    effective_ws_id: str,
    selected_room: str,
    raw_prompt: str,
    pro_toggle_on: bool,
    budget_exceeded: bool = False,
    force_flash: bool = False
) -> None:
    task_mgr = get_background_task_manager()
    current_messages = st.session_state.chat_rooms[selected_room]
    current_file_info = _normalize_room_file_entry(st.session_state.room_files[selected_room])
    st.session_state.room_files[selected_room] = current_file_info

    effective_prompt = raw_prompt.strip()
    if force_flash or budget_exceeded:
        if effective_prompt.startswith("[프로]"):
            effective_prompt = effective_prompt.replace("[프로]", "", 1).strip()
    elif pro_toggle_on and not effective_prompt.startswith("[프로]"):
        effective_prompt = f"[프로] {effective_prompt}"

    has_attached_file = bool(current_file_info["name"] and current_file_info["text"])
    display_prompt = f"📎 **[첨부파일: {current_file_info['name']}]**\n\n{effective_prompt}" if has_attached_file else effective_prompt

    if st.session_state.room_titles[selected_room] in ["빈 대화방", "메인 대화"] and not current_messages:
        auto_title = raw_prompt.strip().replace("[프로]", "").strip().replace("\n", " ")[:12]
        st.session_state.room_titles[selected_room] = auto_title

    is_pro_request = (
        not force_flash and not budget_exceeded and (
            effective_prompt.startswith("[프로]") or (has_attached_file and len(current_file_info["text"]) >= 15000)
        )
    )
    msg_char_cap = 24000 if is_pro_request else 8000

    history_context = ""
    if current_messages:
        recent_msgs = (current_messages[:2] + current_messages[-6:]) if len(current_messages) > 6 else current_messages
        history_lines = [
            "[이 대화방의 이전 대화 맥락 — 사용자가 별도 수식어 없이 후속 질문이나 조건 변경, 카톡/이메일 초안 변환, 또는 '[프로] 다시 검토해 줘'라고 말하더라도 반드시 아래 직전 질문·답변의 사례 금액, 자산 정보, 계산 내역을 그대로 이어받아 답변할 것]"
        ]
        for m in recent_msgs:
            role_label = "사용자" if m["role"] == "user" else "에이전트"
            history_lines.append(f"- {role_label}: {m['content'][:msg_char_cap]}")
        history_context = "\n".join(history_lines) + "\n\n"

    current_messages.append({"role": "user", "content": display_prompt})
    save_workspace_to_disk(effective_ws_id)

    if has_attached_file and not force_flash:
        doc_cap = MAX_DOC_CHARS_PRO if is_pro_request else MAX_DOC_CHARS_STANDARD
        full_input_for_agent = (
            f"{history_context}"
            f"[현재 사용자 질문]: {effective_prompt}\n\n"
            f"아래는 사용자가 현재 대화방에 업로드한 첨부파일({current_file_info['name']})의 데이터입니다. "
            f"직전 대화 맥락과 이 파일 데이터를 바탕으로 관련 법령·예규·판례·환율을 정밀 대조하여 답변하세요:\n"
            f"========================================\n"
            f"{current_file_info['text'][:doc_cap]}\n"
            f"========================================"
        )
    else:
        full_input_for_agent = f"{history_context}[현재 사용자 질문]: {effective_prompt}" if history_context else effective_prompt

    new_task_info = {
        "status": "running",
        "response": None,
        "is_pro": is_pro_request,
        "started_at": time.time()
    }
    worker_thread = threading.Thread(
        target=_background_agent_worker,
        args=(
            effective_ws_id,
            selected_room,
            full_input_for_agent,
            effective_prompt,
            (has_attached_file and not force_flash),
            is_pro_request,
            new_task_info
        ),
        daemon=True
    )
    new_task_info["thread"] = worker_thread
    task_mgr["tasks"][f"{effective_ws_id}::{selected_room}"] = new_task_info
    worker_thread.start()
    st.rerun()

# ---------------------------------------------------------
# 헬퍼 함수 5: 📜 법제처 공식 『제·개정이유서』 0토큰 원문 열람 뷰어 & 🔑 API키 통합 관리 모달
# ---------------------------------------------------------
_dialog_decorator = getattr(st, "dialog", getattr(st, "experimental_dialog", None))

def _render_official_reason_viewer_body(
    law_prom_map: dict[str, dict],
    effective_ws_id: str,
    selected_room: str,
    pro_toggle_on: bool,
    budget_exceeded: bool = False,
    preselected_clean_name: str = ""
):
    st.caption(
        "💡 **AI 토큰을 전혀 소모하지 않고(0원)** 국가법령정보센터(법제처 DRF) XML에서 "
        "정부가 직접 작성한 **공식 『제·개정이유 및 주요내용(입법이유)』** 원문을 즉시 불러옵니다."
    )
    items = list(law_prom_map.values())
    if not items:
        st.warning("법제처 공포 정보를 불러오지 못했습니다.")
        return

    options_clean = [it["clean_name"] for it in items]
    default_idx = options_clean.index(preselected_clean_name) if preselected_clean_name in options_clean else 0

    def _fmt_law_opt(cname: str) -> str:
        it = law_prom_map[cname]
        tag = "🚀시행예정" if it["is_future_enforcement"] else (f"🆕공포 D+{it['days_since_prom']}" if it["is_recent_promulgation"] else "현행")
        return f"📘 {it['law_name']} ({it['rev_type']} | 공포: {it['prom_date']} | 시행: {it['enf_date']} | {tag})"

    chosen_clean = st.selectbox(
        "열람할 법령·시행령 선택",
        options=options_clean,
        index=default_idx,
        format_func=_fmt_law_opt
    )
    chosen_item = law_prom_map[chosen_clean]

    st.markdown(
        f"**공포번호:** 제{chosen_item['prom_no']}호 &nbsp;|&nbsp; "
        f"**공포일:** `{chosen_item['prom_date']}` &nbsp;|&nbsp; "
        f"**시행일:** `{chosen_item['enf_date']}` &nbsp;|&nbsp; "
        f"**구분:** `{chosen_item['rev_type']}`"
    )

    with st.spinner("법제처 공식 『제·개정이유서(입법이유)』 원문 수신 중 (0토큰)..."):
        official_reason_text = fetch_official_revision_reason_zero_token(
            chosen_item["law_id"],
            chosen_item["law_name"],
            chosen_item.get("mst_id", ""),
            chosen_item.get("enf_raw", "")
        )

    st.text_area(
        "📜 법제처 공식 『제·개정이유 및 주요내용』 원문 (0토큰 무료 조회)",
        value=official_reason_text,
        height=320
    )

    c_v1, c_v2 = st.columns(2)
    with c_v1:
        if st.button("🔄 법제처 최신 공포정보 새로고침", use_container_width=True):
            fetch_latest_tax_law_promulgations.clear()
            fetch_official_revision_reason_zero_token.clear()
            st.rerun()
    with c_v2:
        if st.button(f"⚡ 상단 배너에 「{chosen_item['law_name']}」 신·구 비교표 열기", use_container_width=True):
            curr_msgs = st.session_state.chat_rooms.get(selected_room, [])
            diff_md = generate_banner_law_diff_table(
                curr_msgs, [chosen_item], room_key=f"{effective_ws_id}::{selected_room}"
            )
            st.session_state.setdefault("room_diff_banners", {})[selected_room] = diff_md
            st.session_state[f"diff_banner_open_{selected_room}"] = True
            save_workspace_to_disk(effective_ws_id)
            st.rerun()

# ---------------------------------------------------------
# 🔐 [🔑 API키] 관리자(Manager) 전용 Google 계정 로그인 보안 모듈
# ---------------------------------------------------------
MANAGER_AUTH_FILE = os.path.join(STORAGE_DIR, "_manager_google_auth.json")

def _hash_manager_secret(val: str) -> str:
    return hashlib.sha256(val.strip().encode("utf-8")).hexdigest()

def _mask_google_email(email_str: str) -> str:
    email_str = (email_str or "").strip()
    if "@" not in email_str:
        return email_str
    local_part, domain_part = email_str.split("@", 1)
    if len(local_part) <= 2:
        masked_local = local_part[0] + "***" if local_part else "***"
    else:
        masked_local = local_part[:2] + "*" * max(3, len(local_part) - 2)
    return f"{masked_local}@{domain_part}"

def _load_manager_google_config() -> dict:
    cfg = {"email": "", "pin_hash": "", "source": "none"}
    env_email = ""
    env_pin = ""
    for k in ["MANAGER_GOOGLE_EMAIL", "ADMIN_GOOGLE_EMAIL", "OWNER_GOOGLE_EMAIL", "MANAGER_EMAIL", "ADMIN_EMAIL"]:
        val = os.environ.get(k, "").strip()
        if not val and hasattr(st, "secrets"):
            try:
                val = str(st.secrets.get(k, "")).strip()
            except Exception:
                val = ""
        if val and "@" in val:
            env_email = val.lower()
            break

    for pk in ["MANAGER_SECURITY_PIN", "MANAGER_PASSWORD", "ADMIN_PASSWORD", "MANAGER_PIN"]:
        pval = os.environ.get(pk, "").strip()
        if not pval and hasattr(st, "secrets"):
            try:
                pval = str(st.secrets.get(pk, "")).strip()
            except Exception:
                pval = ""
        if pval:
            env_pin = pval
            break

    if os.path.exists(MANAGER_AUTH_FILE):
        try:
            with open(MANAGER_AUTH_FILE, "r", encoding="utf-8") as f:
                disk_cfg = json.load(f)
            if isinstance(disk_cfg, dict):
                cfg["email"] = str(disk_cfg.get("email", "")).strip().lower()
                cfg["pin_hash"] = str(disk_cfg.get("pin_hash", "")).strip()
                cfg["source"] = "disk"
        except Exception:
            pass

    if env_email:
        cfg["email"] = env_email
        if env_pin:
            cfg["pin_hash"] = _hash_manager_secret(env_pin)
        cfg["source"] = "secrets"

    return cfg

def _save_manager_google_config(email_str: str, pin_plain: str) -> None:
    os.makedirs(STORAGE_DIR, exist_ok=True)
    payload = {
        "email": email_str.strip().lower(),
        "pin_hash": _hash_manager_secret(pin_plain),
        "updated_at": datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M:%S")
    }
    with open(MANAGER_AUTH_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

def _get_streamlit_logged_google_email() -> str:
    try:
        u_obj = getattr(st, "user", None) or getattr(st, "experimental_user", None)
        if u_obj is not None:
            is_logged = getattr(u_obj, "is_logged_in", True)
            raw_email = getattr(u_obj, "email", None)
            if not raw_email and isinstance(u_obj, dict):
                raw_email = u_obj.get("email")
            if is_logged and raw_email:
                clean_em = str(raw_email).strip().lower()
                if clean_em and clean_em != "test@example.com" and "@" in clean_em:
                    return clean_em
    except Exception:
        pass
    return ""

def _render_api_key_manager_body(expiry_all_status: list[dict], law_prom_map: dict):
    mgr_cfg = _load_manager_google_config()
    registered_email = mgr_cfg.get("email", "").strip().lower()
    registered_pin_hash = mgr_cfg.get("pin_hash", "").strip()
    oauth_google_email = _get_streamlit_logged_google_email()
    session_authed_email = str(st.session_state.get("manager_google_authed_email", "")).strip().lower()

    if not registered_email:
        st.warning("🔒 **[보안 설정 필요] 관리자(Manager) Google 계정을 최초 1회 등록해 주세요.**")
        st.caption(
            "아무나 `[🔑 API키]` 버튼을 눌러 API 키 목록이나 관리 링크를 열람·복사하지 못하도록, "
            "본인(Manager)의 Google 계정 이메일과 관리자 보안 비밀번호를 등록합니다."
        )
        with st.container(border=True):
            st.markdown("##### 🛡️ 관리자(Manager) Google 계정 최초 등록")
            default_em = oauth_google_email if oauth_google_email else ""
            reg_email = st.text_input(
                "관리자 Google 이메일 주소",
                value=default_em,
                placeholder="예: myaccount@gmail.com",
                key="mgr_reg_google_email"
            )
            reg_pin1 = st.text_input(
                "관리자 전용 보안 비밀번호 설정 (API키 잠금 해제용)",
                type="password",
                placeholder="본인만 아는 보안 비밀번호 입력",
                key="mgr_reg_pin1"
            )
            reg_pin2 = st.text_input(
                "관리자 전용 보안 비밀번호 확인",
                type="password",
                placeholder="보안 비밀번호 다시 입력",
                key="mgr_reg_pin2"
            )
            if st.button("✅ 내 Google 계정을 유일한 관리자로 등록 및 잠금 활성화", type="primary", use_container_width=True):
                clean_reg_em = reg_email.strip().lower()
                if not clean_reg_em or "@" not in clean_reg_em:
                    st.error("유효한 Google 이메일 주소(예: example@gmail.com)를 입력해 주세요.")
                elif len(reg_pin1.strip()) < 4:
                    st.error("보안 비밀번호는 최소 4자리 이상 입력해 주세요.")
                elif reg_pin1.strip() != reg_pin2.strip():
                    st.error("입력하신 두 보안 비밀번호가 일치하지 않습니다.")
                else:
                    _save_manager_google_config(clean_reg_em, reg_pin1.strip())
                    st.session_state.manager_google_authed_email = clean_reg_em
                    st.success(f"✅ 관리자 Google 계정({clean_reg_em}) 등록 및 보안 잠금이 완료되었습니다!")
                    st.rerun()
        return

    is_oauth_manager = bool(oauth_google_email and oauth_google_email == registered_email)
    is_session_manager = bool(session_authed_email and session_authed_email == registered_email)
    is_manager_verified = is_oauth_manager or is_session_manager

    if not is_manager_verified:
        masked_mgr = _mask_google_email(registered_email)
        st.error(
            f"🔒 **관리자(Manager) 전용 보안 구역입니다.** "
            f"API 키 보호를 위해 등록된 관리자 Google 계정(**`{masked_mgr}`**)으로 로그인해야 열람할 수 있습니다."
        )
        if oauth_google_email and oauth_google_email != registered_email:
            st.warning(
                f"🚫 현재 브라우저에 로그인된 Google 계정(`{oauth_google_email}`)은 관리자 계정이 아닙니다. "
                f"관리자 계정(`{masked_mgr}`)으로 로그인해 주세요."
            )

        with st.container(border=True):
            st.markdown("##### 🌐 방법 1. Google 계정으로 바로 로그인 (Streamlit OAuth)")
            c_gl1, c_gl2 = st.columns(2)
            with c_gl1:
                if st.button("🔐 Google 로그인 (Manager 인증)", type="primary", use_container_width=True, key="btn_st_google_oauth"):
                    if hasattr(st, "login"):
                        try:
                            st.login()
                        except Exception:
                            st.session_state.show_google_oauth_guide = True
                    else:
                        st.session_state.show_google_oauth_guide = True
            with c_gl2:
                st.link_button("🌐 Google 계정 로그인 페이지 열기", "https://accounts.google.com/", use_container_width=True)

            if st.session_state.get("show_google_oauth_guide"):
                st.info(
                    "💡 현재 앱에 Streamlit OIDC(`secrets.toml`의 `[auth]`) 설정이 없어 아래 **방법 2(관리자 Google 이메일 + 보안 비밀번호 인증)**로 즉시 로그인하실 수 있습니다."
                )

        with st.container(border=True):
            st.markdown("##### 🔑 방법 2. 등록된 Manager Google 계정 & 보안 암호로 열기")
            input_g_email = st.text_input(
                "Google 계정 이메일",
                placeholder=f"등록된 관리자 구글 이메일 입력 ({masked_mgr})",
                key="login_mgr_google_email"
            )
            input_g_pin = st.text_input(
                "관리자 보안 비밀번호",
                type="password",
                placeholder="관리자 보안 비밀번호 입력",
                key="login_mgr_google_pin"
            )
            if st.button("🔓 관리자 Google 계정 인증 및 API키 열기", type="primary", use_container_width=True, key="btn_verify_mgr_pin"):
                cand_email = input_g_email.strip().lower()
                cand_pin_hash = _hash_manager_secret(input_g_pin.strip())
                if cand_email != registered_email:
                    st.error("🚫 입력하신 이메일이 등록된 관리자(Manager) Google 계정과 일치하지 않습니다.")
                elif registered_pin_hash and cand_pin_hash != registered_pin_hash:
                    st.error("🚫 관리자 보안 비밀번호가 일치하지 않습니다.")
                else:
                    st.session_state.manager_google_authed_email = registered_email
                    st.success("✅ 관리자(Manager) Google 계정 인증이 완료되었습니다.")
                    st.rerun()
        return

    with st.container(border=True):
        c_top1, c_top2 = st.columns([3.6, 1.4])
        with c_top1:
            st.markdown(f"🛡️ **관리자(Manager) Google 인증 완료:** `{registered_email}`")
            st.caption("현재 에이전트AI에 연동된 전체 API 상태와 만료 예정 키 갱신 바로가기입니다.")
        with c_top2:
            if st.button("🔒 잠금 (로그아웃)", use_container_width=True, key="btn_lock_api_modal"):
                st.session_state.manager_google_authed_email = ""
                if is_oauth_manager and hasattr(st, "logout"):
                    try:
                        st.logout()
                    except Exception:
                        pass
                st.rerun()

    gemini_ok = _check_api_configured(["GEMINI_PAID_KEY", "GEMINI_API_KEY"])
    g_led = "🟢 연동됨" if gemini_ok else "🟡 미설정"
    with st.container(border=True):
        c_g1, c_g2 = st.columns([3.6, 1.4])
        with c_g1:
            st.markdown(f"**1. Google AI Studio (Gemini 유료 API 키)** &nbsp;|&nbsp; `{g_led}`")
            st.caption("구글 AI 스튜디오 API 키 발급 및 관리 (유료 Pay-as-you-go 연동)")
        with c_g2:
            st.link_button("🔗 링크 열기", "https://aistudio.google.com/apikey", use_container_width=True)

    law_ok = bool(_get_law_oc()) or _check_api_configured(["LAW_OPEN_API_KEY", "LAW_API_OC", "OC"]) or bool(law_prom_map)
    dart_ok = _check_api_configured(["DART_API_KEY", "OPENDART_API_KEY"])
    ind_ok = os.path.exists("industry_codes.xlsx")

    permanent_apis = [
        (
            "2. 국가법령정보센터 (법령·판례·심판례·예규 API)",
            "🟢 연동됨 (무기한)" if law_ok else "🟡 미설정",
            "법제처 OPEN API 신청 및 인증키(OC) 관리",
            "https://open.law.go.kr/LSO/openApi/guideList.do"
        ),
        (
            "3. 금융감독원 전자공시시스템 (Open DART API)",
            "🟢 연동됨 (무기한)" if dart_ok else "🟡 미설정",
            "기업개황·재무제표·지분·배당 조회용 오픈다트 인증키 관리",
            "https://opendart.fss.or.kr/uss/umt/EgovMberManage.do"
        ),
    ]
    for title_txt, status_txt, desc_txt, link_url in permanent_apis:
        with st.container(border=True):
            c_p1, c_p2 = st.columns([3.6, 1.4])
            with c_p1:
                st.markdown(f"**{title_txt}** &nbsp;|&nbsp; `{status_txt}`")
                st.caption(desc_txt)
            with c_p2:
                st.link_button("🔗 링크 열기", link_url, use_container_width=True)

    st.markdown("##### ⏰ 주기적 갱신이 필요한 API (만료 예정일 확인 및 바로 갱신)")
    current_expiry_map = load_api_expiry_dates()
    updated_expiry_map = {}

    key_check_map = {
        "VWORLD": ["VWORLD_API_KEY"],
        "DATA_GO_KR": ["NTS_API_KEY", "DATA_GO_KR_KEY", "PUBLIC_DATA_KEY", "MOLIT_API_KEY"],
        "BOK_ECOS": ["BOK_API_KEY", "ECOS_API_KEY"],
    }

    for idx, st_item in enumerate(expiry_all_status, start=4):
        code = st_item["code"]
        d_left = st_item["days_left"]
        is_conn = _check_api_configured(key_check_map.get(code, []))
        conn_tag = "🟢 연동됨" if is_conn else "🟡 미설정"
        if d_left < 0:
            d_tag = f"🚨 만료됨 (D+{-d_left})"
        elif d_left <= 30:
            d_tag = f"🔴 만료임박 (D-{d_left})"
        else:
            d_tag = f"🟢 정상 (D-{d_left})"

        with st.container(border=True):
            c_e1, c_e2 = st.columns([3.6, 1.4])
            with c_e1:
                st.markdown(
                    f"**{idx}. {st_item['name']}** &nbsp;|&nbsp; `{conn_tag}` &nbsp;|&nbsp; `{d_tag}` *(주기: {st_item['cycle']})*"
                )
                val_str = st.text_input(
                    f"{st_item['name']} 만료일 (YYYY-MM-DD)",
                    value=current_expiry_map.get(code, st_item["date_str"]),
                    placeholder="YYYY-MM-DD",
                    label_visibility="collapsed",
                    key=f"modal_exp_input_{code}"
                )
                updated_expiry_map[code] = val_str.strip()
            with c_e2:
                st.link_button("🔗 링크 열기", st_item["url"], use_container_width=True)

    with st.container(border=True):
        ind_led = "🟢 정상 로드됨" if ind_ok else "🟡 파일 없음"
        st.markdown(f"**7. 국세청 6자리 업종코드 마스터 DB (`industry_codes.xlsx`)** &nbsp;|&nbsp; `{ind_led}`")

    if st.button("💾 수정한 API 만료일 저장", use_container_width=True):
        save_api_expiry_dates(updated_expiry_map)
        st.success("API 만료일이 저장되었습니다!")
        st.rerun()

    with st.expander("⚙️ 관리자(Manager) Google 계정 또는 보안 비밀번호 변경"):
        new_mgr_em = st.text_input("변경할 관리자 Google 이메일", value=registered_email, key="chg_mgr_email")
        new_mgr_pw = st.text_input("새 관리자 보안 비밀번호 (4자리 이상)", type="password", key="chg_mgr_pw")
        if st.button("🔄 관리자 보안 정보 업데이트", key="btn_chg_mgr_save"):
            if "@" not in new_mgr_em.strip():
                st.error("유효한 Google 이메일을 입력해 주세요.")
            elif len(new_mgr_pw.strip()) < 4:
                st.error("새 보안 비밀번호를 4자리 이상 입력해 주세요.")
            else:
                _save_manager_google_config(new_mgr_em.strip().lower(), new_mgr_pw.strip())
                st.session_state.manager_google_authed_email = new_mgr_em.strip().lower()
                st.success("✅ 관리자 Google 계정 및 보안 비밀번호가 변경되었습니다.")
                st.rerun()

if _dialog_decorator:
    @_dialog_decorator("📜 법제처 공식 『제·개정이유 및 주요내용』 원문 뷰어 (0토큰)", width="large")
    def open_official_reason_modal(
        law_prom_map: dict[str, dict],
        effective_ws_id: str,
        selected_room: str,
        pro_toggle_on: bool,
        budget_exceeded: bool = False,
        preselected_clean_name: str = ""
    ):
        _render_official_reason_viewer_body(
            law_prom_map, effective_ws_id, selected_room, pro_toggle_on, budget_exceeded, preselected_clean_name
        )

    @_dialog_decorator("🔑 연동 API 리스트 및 키 갱신·만료일 관리", width="large")
    def open_api_key_manager_modal(expiry_all_status: list[dict], law_prom_map: dict):
        _render_api_key_manager_body(expiry_all_status, law_prom_map)

# ---------------------------------------------------------
# 2. 왼쪽 사이드바 제어판 (드롭다운 제거 + 1~10번 세로 클릭 리스트 + 우측 신호등 LED)
# ---------------------------------------------------------
task_mgr = get_background_task_manager()
expiry_alerts, expiry_all_status = check_api_expiry_alerts()
law_prom_map = fetch_latest_tax_law_promulgations()
budget_exceeded = False

if "app_top_mode" not in st.session_state:
    st.session_state.app_top_mode = "AGENT"

with st.sidebar:
    # 🔀 [최상단 고정: "자율 에이전트AI" / "통합고용세액공제" 2열 전환 버튼]
    sb_m1, sb_m2 = st.columns(2, gap="small")
    with sb_m1:
        if st.button(
            "자율 에이전트AI",
            key="btn_top_mode_agent",
            type=("primary" if st.session_state.app_top_mode == "AGENT" else "secondary"),
            use_container_width=True,
        ):
            st.session_state.app_top_mode = "AGENT"
            st.rerun()
    with sb_m2:
        if st.button(
            "통합고용세액공제",
            key="btn_top_mode_credit",
            type=("primary" if st.session_state.app_top_mode == "CREDIT_CALC" else "secondary"),
            use_container_width=True,
        ):
            st.session_state.app_top_mode = "CREDIT_CALC"
            st.rerun()

    st.markdown(
        "<div style='font-size:0.96rem; font-weight:800; color:#0f172a; line-height:1.3; margin-top:2px; margin-bottom:2px; letter-spacing:-0.4px;'>"
        "⚙️ 에이전트 제어판</div>",
        unsafe_allow_html=True
    )
    
    # 📦 [카드 1] 엔진 출력 모드 제어
    with st.container(border=True):
        is_pro_now = st.session_state.get("pro_toggle_state", False)
        mode_pill = (
            "<span class='sb-badge-pro'>🧠 Pro 3배 개방</span>"
            if is_pro_now else
            "<span class='sb-badge-green'>⚡ Flash 고속</span>"
        )
        st.markdown(f"<div class='sb-card-title'><span>🚀 엔진 출력 모드</span>{mode_pill}</div>", unsafe_allow_html=True)
        pro_toggle_on = st.toggle(
            "Pro 심층 모드 (3배 리미트 해제)",
            value=is_pro_now,
            help="켜두면 질문 앞에 [프로]를 입력하지 않아도 최대 15만 자 문서 독해 및 30회 도구 호출 모드로 작동합니다."
        )
        st.session_state.pro_toggle_state = pro_toggle_on

    # 📦 [카드 2] 내 작업공간 (자동 동기화)
    with st.container(border=True):
        ws_widget_ver = st.session_state.get("ws_widget_ver", 0)
        saved_ws_val = st.session_state.get("active_workspace_id", "")
        ws_pill = (
            "<span class='sb-badge-green'>🟢 보안 저장중</span>"
            if saved_ws_val.strip() else
            "<span class='sb-badge-amber'>🔓 공용 임시</span>"
        )
        st.markdown(f"<div class='sb-card-title'><span>🔐 내 작업공간 코드</span>{ws_pill}</div>", unsafe_allow_html=True)
        workspace_input = st.text_input(
            "작업공간 코드",
            value=saved_ws_val,
            type="password",
            placeholder="나만의 암호 입력 후 Enter",
            label_visibility="collapsed",
            key=f"ws_input_box_{ws_widget_ver}",
            help="동일한 코드를 입력하면 다른 PC에서도 1~10번 방 대화와 파일이 그대로 유지됩니다."
        )
        effective_ws_id = workspace_input.strip() if workspace_input.strip() else "default_public"

        if st.session_state.get("loaded_workspace_id") != effective_ws_id:
            ws_data = load_workspace_from_disk(effective_ws_id)
            st.session_state.chat_rooms = ws_data["chat_rooms"]
            st.session_state.room_titles = ws_data["room_titles"]
            st.session_state.room_files = ws_data["room_files"]
            st.session_state.room_diff_banners = ws_data.get("room_diff_banners", {r_id: "" for r_id in ROOM_IDS})
            st.session_state.loaded_workspace_id = effective_ws_id
            st.session_state.active_workspace_id = workspace_input.strip()
            if "current_room" not in st.session_state:
                st.session_state.current_room = ROOM_IDS[0]
            st.rerun()

        # 백그라운드 완료 작업 자동 반영
        for r_id in ROOM_IDS:
            st.session_state.room_files[r_id] = _normalize_room_file_entry(st.session_state.room_files.get(r_id, {}))
            t_key = f"{effective_ws_id}::{r_id}"
            t_info = task_mgr["tasks"].get(t_key)
            if t_info and t_info.get("status") == "done":
                ans = t_info.get("response", "")
                room_msgs = st.session_state.chat_rooms[r_id]
                if ans and (not room_msgs or room_msgs[-1].get("role") != "assistant" or room_msgs[-1].get("content") != ans):
                    room_msgs.append({"role": "assistant", "content": ans})
                del task_mgr["tasks"][t_key]

        if workspace_input.strip():
            if st.button("🔒 작업공간 잠금 (나가기)", use_container_width=True):
                st.session_state.active_workspace_id = ""
                st.session_state.loaded_workspace_id = None
                st.session_state.ws_widget_ver = ws_widget_ver + 1
                st.rerun()

    # 📦 [카드 3] 멀티 대화방 (드롭다운 완전 제거 + 1~10번 세로 1열 클릭 리스트 + 우측 신호등 LED)
    with st.container(border=True):
        if "current_room" not in st.session_state or st.session_state.current_room not in ROOM_IDS:
            st.session_state.current_room = ROOM_IDS[0]
        selected_room = st.session_state.current_room
        active_room_key = f"{effective_ws_id}::{selected_room}"

        rooms_with_rev_cnt = sum(
            1 for r_id in ROOM_IDS
            if get_room_revision_alerts(effective_ws_id, r_id, st.session_state.chat_rooms.get(r_id, []), law_prom_map)[0]
        )
        rev_header_pill = (
            f"<span class='sb-badge-amber'>🔄 {rooms_with_rev_cnt}개방 개정</span>"
            if rooms_with_rev_cnt > 0 else ""
        )
        st.markdown(f"<div class='sb-card-title'><span>🗂️ 멀티 대화방 (1~10번)</span>{rev_header_pill}</div>", unsafe_allow_html=True)

        room_search_kw = st.text_input(
            "전체 대화방 통합 검색",
            placeholder="🔎 1~10번 방 통합 키워드 검색",
            label_visibility="collapsed",
            key=f"room_search_{effective_ws_id}"
        )
        if room_search_kw.strip():
            kw_lower = room_search_kw.strip().lower()
            matched_rooms = []
            for r_id in ROOM_IDS:
                r_title = st.session_state.room_titles.get(r_id, "")
                r_fname = st.session_state.room_files[r_id].get("name") or ""
                r_msgs = st.session_state.chat_rooms.get(r_id, [])
                hit_cnt = sum(1 for m in r_msgs if kw_lower in m.get("content", "").lower())
                if kw_lower in r_title.lower() or kw_lower in r_fname.lower():
                    hit_cnt += 1
                if hit_cnt > 0:
                    matched_rooms.append((r_id, r_title, hit_cnt))
            if matched_rooms:
                for m_rid, m_title, m_cnt in matched_rooms:
                    if st.button(f"👉 {m_rid} [{m_title}] ({m_cnt}건 일치)", key=f"jump_{m_rid}", use_container_width=True):
                        st.session_state.current_room = m_rid
                        st.rerun()
            else:
                st.caption(f"'{room_search_kw}' 검색 결과가 없습니다.")

        new_title = st.text_input(
            "방 주제 메모",
            value=st.session_state.room_titles[selected_room],
            placeholder="✏️ 현재 방 주제 메모 (예: A사 세무조사)",
            label_visibility="collapsed",
            key=f"title_input_{effective_ws_id}_{selected_room}"
        )
        if new_title != st.session_state.room_titles[selected_room]:
            st.session_state.room_titles[selected_room] = new_title
            save_workspace_to_disk(effective_ws_id)
            st.rerun()

        if st.button(f"🗑️ [{selected_room}] 현재 방 비우기", use_container_width=True):
            task_mgr["tasks"].pop(active_room_key, None)
            st.session_state.chat_rooms[selected_room] = []
            st.session_state.room_files[selected_room] = {"name": None, "text": "", "items": []}
            st.session_state.room_titles[selected_room] = "빈 대화방"
            st.session_state.setdefault("room_diff_banners", {})[selected_room] = ""
            st.session_state[f"diff_banner_open_{selected_room}"] = False
            if hasattr(agent, "reset_room_usage"):
                agent.reset_room_usage(active_room_key)
            st.session_state[f"reset_cnt_{selected_room}"] = st.session_state.get(f"reset_cnt_{selected_room}", 0) + 1
            save_workspace_to_disk(effective_ws_id)
            st.rerun()

        # 📋 [1번~10번 세로 1열 클릭 리스트 + 우측 동그라미 신호등 LED 표시]
        # - 글 없음(0건, 비선택): _empty (칸 기본 배경 + 우측 동그라미 불 꺼짐)
        # - 글 있음(1건 이상, 비선택): _hasmsg (칸 화이트 + 우측 동그라미 초록불)
        # - 현재 선택된 방: _active (칸 전체 연녹색 점등 + 우측 초록불)
        # - 작성(분석) 중일 때: _running 추가 (우측 동그라미 빨강↔주황↔노랑 실시간 변색 애니메이션)
        for idx_r, r_id in enumerate(ROOM_IDS, start=1):
            r_title = (st.session_state.room_titles.get(r_id, "빈 대화방") or "빈 대화방").strip()
            short_title = r_title[:10] + ("…" if len(r_title) > 10 else "")
            r_msgs = st.session_state.chat_rooms.get(r_id, [])
            q_cnt = (len(r_msgs) + 1) // 2
            f_cnt = len(st.session_state.room_files[r_id].get("items", []))
            t_info = task_mgr["tasks"].get(f"{effective_ws_id}::{r_id}")
            is_run = bool(t_info and t_info.get("status") == "running")
            rev_alerts, _ = get_room_revision_alerts(effective_ws_id, r_id, r_msgs, law_prom_map)

            base_state = "active" if r_id == selected_room else ("hasmsg" if q_cnt > 0 else "empty")
            run_suffix = "_running" if is_run else ""
            btn_key = f"room_btn_{idx_r}_{base_state}{run_suffix}"

            extra_badges = (" 📎" if f_cnt else "") + (" 🔄" if rev_alerts else "") + (" (작성중)" if is_run else "")
            btn_label = f"{idx_r}. {short_title} ({q_cnt}건){extra_badges}"

            if st.button(btn_label, key=btn_key, use_container_width=True):
                if r_id != selected_room:
                    st.session_state.current_room = r_id
                    st.rerun()

    # 📦 [카드 4 — 최하단 고정: [💳 결제] 및 [🔑 API키] 버튼]
    with st.container(border=True):
        col_b1, col_b2 = st.columns(2)
        with col_b1:
            st.link_button("💳 결제", "https://console.cloud.google.com/billing", use_container_width=True)
        with col_b2:
            if st.button("🔑 API키", use_container_width=True, help="연동된 전체 API 리스트 및 갱신 링크 열기"):
                if _dialog_decorator:
                    open_api_key_manager_modal(expiry_all_status, law_prom_map)
                else:
                    st.session_state.show_inline_api_manager = not st.session_state.get("show_inline_api_manager", False)

# ---------------------------------------------------------
# 3. 메인 화면 상단 (상단 잘림 없는 슬림 상태바 + 본문과 분리된 접이식 신·구 비교표 배너)
# ---------------------------------------------------------
current_messages = st.session_state.chat_rooms[selected_room]
current_room_title = st.session_state.room_titles[selected_room]
current_file_info = _normalize_room_file_entry(st.session_state.room_files[selected_room])
current_task_key = f"{effective_ws_id}::{selected_room}"
active_task = task_mgr["tasks"].get(current_task_key)
is_current_room_running = bool(active_task and active_task.get("status") == "running")

if st.session_state.app_top_mode == "CREDIT_CALC":
    if st.session_state.get("show_inline_api_manager"):
        with st.container(border=True):
            st.subheader("🔑 연동 API 리스트 및 키 갱신·만료일 관리")
            _render_api_key_manager_body(expiry_all_status, law_prom_map)
            if st.button("✖️ API 관리창 닫기"):
                st.session_state.show_inline_api_manager = False
                st.rerun()
    import tax_credit_engine
    tax_credit_engine.render_tax_credit_calculator_ui(
        extract_file_fn=extract_file_content,
        create_pdf_fn=create_pdf_report,
        create_docx_fn=create_word_docx,
        log_tokens_fn=_log_custom_tokens,
        active_room_key=current_task_key,
    )
    st.stop()

# 상단 미니 상태바 (여백 3.2rem 확보로 잘림 현상 완벽 해결)
q_count_now = (len(current_messages) + 1) // 2
mode_badge_html = (
    "🧠 <b>Pro 심층 모드 (3배 리미트 개방 ON)</b>"
    if pro_toggle_on else
    "⚡ <b>Flash 표준 모드 (고속 검토)</b>"
)
st.markdown(
    f"<div class='top-mini-status-bar'>"
    f"<span>💬 <b>{selected_room} [{current_room_title}]</b> ({q_count_now}건 대화 중)</span>"
    f"<span>💡 현재 엔진: {mode_badge_html}</span>"
    f"</div>",
    unsafe_allow_html=True
)

# 🚨 1) [API 유효기간 1개월(30일) 전 자동 경고 배너]
if expiry_alerts:
    for alert_item in expiry_alerts:
        c_al1, c_al2 = st.columns([5, 1])
        with c_al1:
            if alert_item["level"] == "expired":
                st.error(alert_item["msg"])
            else:
                st.warning(alert_item["msg"])
        with c_al2:
            st.link_button("🔗 연장·재발급", alert_item["url"], use_container_width=True)

# 🔄 2) [개정세법 안내 배너 + 본문 대화와 무관하게 배너로 열었다 닫았다 하는 신·구법 비교표]
current_room_rev_alerts, is_post_revision = get_room_revision_alerts(
    effective_ws_id, selected_room, current_messages, law_prom_map
)
saved_diff_md = st.session_state.get("room_diff_banners", {}).get(selected_room, "")
is_diff_open = st.session_state.get(f"diff_banner_open_{selected_room}", False)

if current_room_rev_alerts:
    rev_names_str = ", ".join(
        f"「{it['law_name']}」(공포:{it['prom_date']}/시행:{it['enf_date']})" for it in current_room_rev_alerts
    )
    first_clean = current_room_rev_alerts[0]["clean_name"]
    c_rv1, c_rv2, c_rv3, c_rv4 = st.columns([3.4, 1.1, 1.2, 0.7])
    with c_rv1:
        if is_post_revision:
            st.warning(
                f"🔄 **[사후 법령 개정 감지]** 이 방의 과거 검토 이후에 **{rev_names_str}**이 새로 개정 공포되었습니다."
            )
        else:
            st.info(
                f"📜 **[최근 공포·시행예정 법령 인용 안내]** 이 방에서 인용된 **{rev_names_str}**의 공식 입법이유서 및 신·구 비교표를 바로 열람할 수 있습니다."
            )
    with c_rv2:
        if st.button("📜 개정이유서(0원)", key=f"rsn_{selected_room}", use_container_width=True):
            if _dialog_decorator:
                open_official_reason_modal(law_prom_map, effective_ws_id, selected_room, pro_toggle_on, False, first_clean)
            else:
                st.session_state.show_inline_reason_viewer = not st.session_state.get("show_inline_reason_viewer", False)
                st.rerun()
    with c_rv3:
        diff_btn_lbl = "🔼 신·구법 비교 닫기" if (saved_diff_md and is_diff_open) else "⚡ 신·구법 비교 (배너)"
        if st.button(diff_btn_lbl, key=f"rerev_{selected_room}", use_container_width=True):
            if saved_diff_md:
                st.session_state[f"diff_banner_open_{selected_room}"] = not is_diff_open
                st.rerun()
            else:
                with st.spinner("⚡ 본문 대화와 분리된 상단 [조문명 / 구법내용 / 개정법내용 / 개정효과] 비교표 배너를 생성 중입니다..."):
                    diff_md = generate_banner_law_diff_table(
                        current_messages, current_room_rev_alerts, room_key=current_task_key
                    )
                    st.session_state.setdefault("room_diff_banners", {})[selected_room] = diff_md
                    st.session_state[f"diff_banner_open_{selected_room}"] = True
                    save_workspace_to_disk(effective_ws_id)
                st.rerun()
    with c_rv4:
        if st.button("✅ 확인", key=f"ack_{selected_room}", use_container_width=True, help="이 대화방의 법령 알림을 확인 처리하여 숨깁니다."):
            acknowledge_room_laws(effective_ws_id, selected_room, current_room_rev_alerts)
            st.rerun()

# 📊 본문 대화와 무관하게 언제든 열었다 닫았다 할 수 있는 상단 [조문명/구법내용/개정법내용/개정효과] 배너
if saved_diff_md:
    with st.expander("📊 [신·구법 비교 배너] 조문명 / 구법내용 / 개정법내용 / 개정효과 (클릭하여 열기·닫기)", expanded=is_diff_open):
        st.markdown(f"<div class='law-diff-banner-box'>\n\n{saved_diff_md}\n\n</div>", unsafe_allow_html=True)
        b_col1, b_col2 = st.columns([1, 5])
        with b_col1:
            if st.button("🔄 비교표 다시 생성", key=f"regen_diff_{selected_room}"):
                with st.spinner("⚡ 신·구법 비교표를 새로 작성 중입니다..."):
                    alerts_for_regen = current_room_rev_alerts or extract_cited_laws_in_room(current_messages, law_prom_map)
                    diff_md = generate_banner_law_diff_table(
                        current_messages, alerts_for_regen, room_key=current_task_key
                    )
                    st.session_state.setdefault("room_diff_banners", {})[selected_room] = diff_md
                    st.session_state[f"diff_banner_open_{selected_room}"] = True
                    save_workspace_to_disk(effective_ws_id)
                st.rerun()

# 구버전 Streamlit 폴백용 인라인 뷰어들
if st.session_state.get("show_inline_reason_viewer"):
    with st.container(border=True):
        st.subheader("📜 법제처 공식 『제·개정이유 및 주요내용』 원문 뷰어 (0토큰)")
        _render_official_reason_viewer_body(law_prom_map, effective_ws_id, selected_room, pro_toggle_on, False)
        if st.button("✖️ 뷰어 닫기"):
            st.session_state.show_inline_reason_viewer = False
            st.rerun()

if st.session_state.get("show_inline_api_manager"):
    with st.container(border=True):
        st.subheader("🔑 연동 API 리스트 및 키 갱신·만료일 관리")
        _render_api_key_manager_body(expiry_all_status, law_prom_map)
        if st.button("✖️ API 관리창 닫기"):
            st.session_state.show_inline_api_manager = False
            st.rerun()

# ---------------------------------------------------------
# 4. 대화방 메시지 목록 렌더링
# ---------------------------------------------------------
for idx, message in enumerate(current_messages):
    with st.chat_message(message["role"]):
        display_content = message["content"]
        if message["role"] == "assistant" and hasattr(agent, "_inject_direct_law_links"):
            try:
                display_content = agent._inject_direct_law_links(display_content)
            except Exception:
                pass
        st.markdown(display_content)

        if message["role"] == "assistant":
            # 📥 1줄: 문서 다운로드 버튼 4종 (PDF / 워드 / 표 엑셀(.xlsx) / 마크다운)
            excel_bytes = create_excel_from_markdown_tables(message["content"])
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.download_button(
                    label="📕 정식 PDF (.pdf)",
                    data=create_pdf_report(message["content"]),
                    file_name=f"검토보고서_{selected_room}_{current_room_title}_{idx}.pdf",
                    mime="application/pdf",
                    key=f"pdf_{effective_ws_id}_{selected_room}_{idx}",
                    use_container_width=True
                )
            with col2:
                st.download_button(
                    label="📘 워드 (.docx)",
                    data=create_word_docx(message["content"]),
                    file_name=f"검토보고서_{selected_room}_{current_room_title}_{idx}.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    key=f"docx_{effective_ws_id}_{selected_room}_{idx}",
                    use_container_width=True
                )
            with col3:
                if excel_bytes:
                    st.download_button(
                        label="📊 표 엑셀 (.xlsx)",
                        data=excel_bytes,
                        file_name=f"검토표_{selected_room}_{current_room_title}_{idx}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key=f"xlsx_{effective_ws_id}_{selected_room}_{idx}",
                        use_container_width=True
                    )
                else:
                    st.button("📊 표 없음 (.xlsx)", disabled=True, key=f"no_xlsx_{effective_ws_id}_{selected_room}_{idx}", use_container_width=True)
            with col4:
                st.download_button(
                    label="📝 마크다운 (.md)",
                    data=message["content"].encode("utf-8-sig"),
                    file_name=f"검토보고서_{selected_room}_{current_room_title}_{idx}.md",
                    mime="text/markdown",
                    key=f"md_{effective_ws_id}_{selected_room}_{idx}",
                    use_container_width=True
                )

            # ⚡ 2줄: 타이핑 제로 원클릭 후속 작업 버튼 3종 (카톡/이메일은 Flash 초저가 강제 실행)
            act1, act2, act3 = st.columns(3)
            with act1:
                if st.button(
                    "💬 카톡 안내문 변환 (Flash)",
                    key=f"kakao_{effective_ws_id}_{selected_room}_{idx}",
                    disabled=is_current_room_running,
                    use_container_width=True
                ):
                    _trigger_agent_task(
                        effective_ws_id, selected_room,
                        "방금 작성한 검토 결과를 바탕으로, 거래처 대표님이나 고객에게 카카오톡으로 바로 복사해서 보낼 수 있도록 핵심 결론과 주의사항만 친절하고 정중한 실무 대화체로 요약해 줘.",
                        pro_toggle_on, False, force_flash=True
                    )
            with act2:
                if st.button(
                    "📧 이메일 회신 초안 (Flash)",
                    key=f"email_{effective_ws_id}_{selected_room}_{idx}",
                    disabled=is_current_room_running,
                    use_container_width=True
                ):
                    _trigger_agent_task(
                        effective_ws_id, selected_room,
                        "방금 작성한 검토 결과를 바탕으로, 거래처에 발송할 정식 비즈니스 이메일 회신 초안(제목, 인사말, 핵심 검토 결과 요약, 실무 유의사항, 맺음말 포함)을 깔끔하게 작성해 줘.",
                        pro_toggle_on, False, force_flash=True
                    )
            with act3:
                if st.button(
                    "🧠 [프로] 3배 개방 재검토",
                    key=f"repro_{effective_ws_id}_{selected_room}_{idx}",
                    disabled=is_current_room_running,
                    use_container_width=True
                ):
                    _trigger_agent_task(
                        effective_ws_id, selected_room,
                        "[프로] 직전 질문 사안에 대해 관련 법령·시행령·판례·심판례·예규와 예외 요건까지 데이터·도구 한도를 3배 개방하여 심층 재검토해 줘.",
                        pro_toggle_on, False, force_flash=False
                    )

            with st.expander("📋 카톡·이메일 전송용 텍스트 원클릭 복사 (우측 상단 복사 아이콘 클릭)"):
                st.code(_extract_clean_copy_text(message["content"]), language="markdown")

# ---------------------------------------------------------
# 5. 현재 방에서 백그라운드 작업이 진행 중일 때 실시간 상태창 표시 (유령 잔상 방지)
# ---------------------------------------------------------
status_placeholder = st.empty()
if active_task and active_task.get("status") == "running":
    is_pro_running = active_task.get("is_pro", False)
    status_title = (
        f"🧠 [{selected_room}] Pro 심층 모드 백그라운드 가동 중 (데이터·도구 한도 3배 개방)..."
        if is_pro_running else
        f"⚡ [{selected_room}] 실시간 법령·공시 DB 조회 및 백그라운드 정밀 검토 중..."
    )
    with status_placeholder.container():
        with st.chat_message("assistant"):
            with st.status(status_title, expanded=True):
                st.write("🔎 **1단계:** 질의 쟁점 분석 및 7대 국가·공공기관(법제처 현행·구법·국세청·DART·국토부·한은) DB 탐색 중...")
                st.write("🧮 **2단계:** 관련 법령·판례 원문 파싱 및 파이썬 1원 단위 정밀 수리 계산기 구동 중...")
                st.write("🛡️ **3단계:** 미조회 근거 강제 차단(`_scan_violations`) 및 듀얼 AI 의미 감수(`_semantic_verify`) 수행 중...")
                st.caption("💡 **백그라운드 멀티태스킹 작동 중:** 지금 좌측 대화방 리스트를 눌러 다른 대화방으로 이동하셔도 이 방의 AI 검토는 멈추지 않고 끝까지 완료됩니다.")

# ---------------------------------------------------------
# 6. 메인 화면 최하단 고정: Gemini 스타일 올인원 통합 채팅 입력창 (드래그 앤 드롭 파일 첨부 통합)
# ---------------------------------------------------------
room_file_entry = _normalize_room_file_entry(st.session_state.room_files[selected_room])
st.session_state.room_files[selected_room] = room_file_entry
saved_items = room_file_entry["items"]
reset_cnt = st.session_state.get(f"reset_cnt_{selected_room}", 0)

# 이미 대화방에 첨부되어 유지 중인 파일이 있으면 하단 입력창 바로 위에 슬림한 칩 형태로 표시
if saved_items:
    with st.container(border=True):
        c_head1, c_head2 = st.columns([8.5, 1.5])
        with c_head1:
            chips_str = " &nbsp;|&nbsp; ".join(
                f"📄 **{it['name']}** *({len(it['text']):,}자)*" for it in saved_items
            )
            st.markdown(
                f"<div style='font-size:0.8rem; color:#15803d;'>📎 <b>현재 [{selected_room}] 첨부 유지 중 ({len(saved_items)}건):</b> {chips_str}</div>",
                unsafe_allow_html=True
            )
        with c_head2:
            if st.button("🗑️ 첨부 비우기", key=f"clear_all_f_{selected_room}", use_container_width=True):
                st.session_state.room_files[selected_room] = {"name": None, "text": "", "items": []}
                st.session_state[f"reset_cnt_{selected_room}"] = reset_cnt + 1
                save_workspace_to_disk(effective_ws_id)
                st.rerun()

chat_input_placeholder = (
    f"⏳ [{selected_room}] 현재 백그라운드 정밀 검토 진행 중입니다... (좌측 다른 대화방을 클릭해 추가 질문을 하실 수 있습니다)"
    if is_current_room_running else
    f"[{selected_room}] 검토할 이슈를 입력하거나 이 칸에 파일(엑셀·PDF·워드·사진)을 바로 끌어다 놓으세요 (+ 버튼 첨부 가능)"
)

# ⚠️ 중요: st.chat_input을 st.container() 밖(최상위 루트)에 단독 호출해야 화면 맨 아래(Bottom)에 고정됩니다!
_chat_sig = inspect.signature(st.chat_input).parameters
try:
    if "accept_file" in _chat_sig:
        chat_val = st.chat_input(
            placeholder=chat_input_placeholder,
            disabled=is_current_room_running,
            accept_file="multiple",
            file_type=["xlsx", "xls", "csv", "pdf", "docx", "png", "jpg", "jpeg"],
            key=f"chat_input_{effective_ws_id}_{selected_room}"
        )
    else:
        chat_val = st.chat_input(
            placeholder=chat_input_placeholder,
            disabled=is_current_room_running,
            key=f"chat_input_{effective_ws_id}_{selected_room}"
        )
except Exception:
    chat_val = st.chat_input(
        placeholder=chat_input_placeholder,
        disabled=is_current_room_running,
        key=f"chat_input_{effective_ws_id}_{selected_room}"
    )

if chat_val:
    if isinstance(chat_val, str):
        user_prompt_text = chat_val
        inline_files = []
    else:
        user_prompt_text = getattr(chat_val, "text", "") or ""
        inline_files = list(getattr(chat_val, "files", []) or [])

    if inline_files:
        existing_names = {it["name"] for it in saved_items}
        for uf in inline_files:
            if uf.name not in existing_names:
                with st.spinner(f"📄 '{uf.name}' 내용 추출 및 저장 중..."):
                    extracted_text = extract_file_content(uf, room_key=active_room_key)
                    saved_items.append({"name": uf.name, "text": extracted_text})
                    existing_names.add(uf.name)
        st.session_state.room_files[selected_room] = _normalize_room_file_entry({"items": saved_items})
        save_workspace_to_disk(effective_ws_id)

    if user_prompt_text.strip():
        _trigger_agent_task(
            effective_ws_id=effective_ws_id,
            selected_room=selected_room,
            raw_prompt=user_prompt_text,
            pro_toggle_on=pro_toggle_on,
            budget_exceeded=False,
            force_flash=False
        )
    elif inline_files:
        st.rerun()

# 백그라운드 작업 폴링 (하단 입력창까지 모두 렌더링한 뒤 깔끔하게 대기 후 완료 시 즉시 갱신)
if active_task and active_task.get("status") == "running":
    while active_task.get("status") == "running":
        time.sleep(0.4)
    status_placeholder.empty()
    ans = active_task.get("response", "")
    if ans and (not current_messages or current_messages[-1].get("role") != "assistant" or current_messages[-1].get("content") != ans):
        current_messages.append({"role": "assistant", "content": ans})
    task_mgr["tasks"].pop(current_task_key, None)
    save_workspace_to_disk(effective_ws_id)
    st.rerun()
