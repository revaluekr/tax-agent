import os
import io
import re
import time
import json
import hashlib
import threading
import urllib.request
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

# 🔒 ImportError 원천 방지 안전 임포트
import agent
import law_api
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
# 0. 작업공간 · 대화방당 2,000원 계량기 · API 만료일 · 🎯 맥락 연동형 법령 레이더
# ---------------------------------------------------------
ROOM_IDS = [f"대화방 {i}" for i in range(1, 11)]
STORAGE_DIR = ".workspace_storage"
os.makedirs(STORAGE_DIR, exist_ok=True)
USAGE_FILE_PATH = os.path.join(STORAGE_DIR, "api_usage_stats.json")
EXPIRY_FILE_PATH = os.path.join(STORAGE_DIR, "api_expiry_dates.json")
ROOM_LAW_ACK_PATH = os.path.join(STORAGE_DIR, "room_law_ack.json")

def _safe_float(raw_val, default_val: float) -> float:
    if raw_val is None or raw_val == "":
        return float(default_val)
    try:
        cleaned = re.sub(r"[^0-9.\-]", "", str(raw_val))
        return float(cleaned) if cleaned else float(default_val)
    except Exception:
        return float(default_val)

ROOM_LIMIT_KRW = _safe_float(os.getenv("ROOM_LIMIT_KRW"), 2000.0)
USD_TO_KRW_RATE = _safe_float(os.getenv("USD_TO_KRW_RATE"), 1400.0)

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
                law_id = str(top.get("법령일련번호", "")).strip()
                mst_id = str(top.get("법령일련번호") or top.get("MST") or "").strip()

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
def fetch_official_revision_reason_zero_token(law_id: str, law_name: str) -> str:
    oc = _get_law_oc()
    if not oc:
        return "❌ 법제처 API 인증키(OC)를 확인할 수 없습니다."
    if not law_id:
        return "❌ 법령 일련번호(ID)를 확인할 수 없습니다."

    urls_to_try = [
        f"http://www.law.go.kr/DRF/lawService.do?OC={oc}&target=law&ID={law_id}&type=XML",
        f"http://www.law.go.kr/DRF/lawService.do?OC={oc}&target=lsRsn&ID={law_id}&type=XML",
    ]
    reason_texts = []
    amend_texts = []

    for url in urls_to_try:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                xml_bytes = resp.read()
            root = ET.fromstring(xml_bytes)
            for elem in root.iter():
                tag_name = elem.tag.strip()
                if tag_name in ("제개정이유내용", "제개정이유") and elem.text and elem.text.strip():
                    reason_texts.append(elem.text.strip())
                elif tag_name in ("개정문내용", "개정문") and elem.text and elem.text.strip():
                    amend_texts.append(elem.text.strip())
            if reason_texts:
                break
        except Exception:
            continue

    if reason_texts:
        body = "\n\n".join(dict.fromkeys(reason_texts))
        if amend_texts:
            body = f"📌 [공식 개정이유 및 주요내용]\n{body}\n\n---\n📌 [공포 개정문 발췌]\n{amend_texts[0][:1500]}"
        return body

    if amend_texts:
        return f"📌 [공포 개정문 원문]\n{amend_texts[0][:3000]}"

    return f"ℹ️ 「{law_name}」(ID: {law_id})의 해당 공포본에는 별도 제·개정이유서 텍스트가 등록되어 있지 않습니다. 우측의 '⚡ AI 신·구법 비교표 생성' 버튼을 이용해 조문별 변경 내역을 확인하세요."

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

def get_room_usage_stats(room_key: str) -> dict:
    """현재 선택된 대화방의 누적 요금·토큰 데이터를 조회합니다."""
    if hasattr(agent, "get_room_usage"):
        try:
            return agent.get_room_usage(room_key)
        except Exception:
            pass
    return {
        "total_krw": 0.0,
        "total_usd": 0.0,
        "pro_calls": 0,
        "flash_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "limit_krw": ROOM_LIMIT_KRW,
        "updated_at": "-"
    }

def is_room_budget_exceeded(room_key: str) -> tuple[bool, float, float]:
    """현재 대화방 누적 요금이 2,000원 한도를 초과했는지 확인합니다."""
    if hasattr(agent, "is_pro_budget_exceeded"):
        try:
            return agent.is_pro_budget_exceeded(room_key)
        except Exception:
            pass
    stats = get_room_usage_stats(room_key)
    cur_krw = float(stats.get("total_krw", 0.0))
    limit_krw = float(stats.get("limit_krw", ROOM_LIMIT_KRW))
    return (cur_krw >= limit_krw), cur_krw, limit_krw

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
        "room_usage": {r_id: {} for r_id in ROOM_IDS}
    }

def load_workspace_from_disk(workspace_id: str) -> dict:
    path = get_storage_path(workspace_id)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            default_data = get_default_workspace_data()
            for key in ["chat_rooms", "room_titles", "room_files", "room_usage"]:
                if key not in data:
                    data[key] = default_data[key]
                else:
                    for r_id in ROOM_IDS:
                        if r_id not in data[key]:
                            data[key][r_id] = default_data[key][r_id]
            for r_id in ROOM_IDS:
                data["room_files"][r_id] = _normalize_room_file_entry(data["room_files"][r_id])
                if data["room_usage"].get(r_id) and hasattr(agent, "set_room_usage_from_backup"):
                    agent.set_room_usage_from_backup(f"{workspace_id}::{r_id}", data["room_usage"][r_id])
            return data
        except Exception:
            pass
    return get_default_workspace_data()

def save_workspace_to_disk(workspace_id: str):
    if not workspace_id:
        return
    path = get_storage_path(workspace_id)
    room_usage_map = {
        r_id: get_room_usage_stats(f"{workspace_id}::{r_id}")
        for r_id in ROOM_IDS
    }
    st.session_state.room_usage = room_usage_map
    data = {
        "chat_rooms": st.session_state.chat_rooms,
        "room_titles": st.session_state.room_titles,
        "room_files": st.session_state.room_files,
        "room_usage": room_usage_map
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
                disk_data.setdefault("room_usage", {})[room_id] = get_room_usage_stats(room_key)
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

    canvas.setFont(reg_font, 6.8)
    canvas.setFillColor(colors.HexColor("#64748b"))
    disclaimer_str = (
        "※ 본 의견서는 질의하신 사실관계와 조회 시점 현행 법령을 기준으로 작성된 참고자료이며, "
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
    budget_exceeded: bool,
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
# 헬퍼 함수 5: 📜 [방식 3] 법제처 공식 『제·개정이유서』 0토큰 원문 열람 뷰어
# ---------------------------------------------------------
_dialog_decorator = getattr(st, "dialog", getattr(st, "experimental_dialog", None))

def _render_official_reason_viewer_body(
    law_prom_map: dict[str, dict],
    effective_ws_id: str,
    selected_room: str,
    pro_toggle_on: bool,
    budget_exceeded: bool,
    preselected_clean_name: str = ""
):
    st.caption(
        "💡 **AI 토큰을 전혀 소모하지 않고(0원)** 국가법령정보센터(법제처 DRF) XML에서 "
        "정부가 직접 작성한 **공식 『제·개정이유 및 주요내용 요약문』** 원문을 즉시 불러옵니다."
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

    with st.spinner("법제처 공식 『제·개정이유서』 원문 수신 중 (0토큰)..."):
        official_reason_text = fetch_official_revision_reason_zero_token(chosen_item["law_id"], chosen_item["law_name"])

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
        if st.button(f"⚡ 「{chosen_item['law_name']}」 AI 신·구법 비교표 생성", use_container_width=True):
            q_str = (
                f"「{chosen_item['law_name']}」(공포일: {chosen_item['prom_date']}, 제{chosen_item['prom_no']}호, 시행일: {chosen_item['enf_date']})의 "
                "핵심 개정 조문을 조회하여 [종전 규정 vs 현행(개정) 규정 vs 적용시기 및 실무 영향] 신·구 비교표 형태로 상세히 정리해 줘."
            )
            _trigger_agent_task(effective_ws_id, selected_room, q_str, pro_toggle_on, budget_exceeded, force_flash=False)

if _dialog_decorator:
    @_dialog_decorator("📜 법제처 공식 『제·개정이유 및 주요내용』 원문 뷰어 (0토큰)", width="large")
    def open_official_reason_modal(
        law_prom_map: dict[str, dict],
        effective_ws_id: str,
        selected_room: str,
        pro_toggle_on: bool,
        budget_exceeded: bool,
        preselected_clean_name: str = ""
    ):
        _render_official_reason_viewer_body(
            law_prom_map, effective_ws_id, selected_room, pro_toggle_on, budget_exceeded, preselected_clean_name
        )

# ---------------------------------------------------------
# 2. 왼쪽 사이드바 제어판 (대화방별 2,000원 한도 계량기 연동)
# ---------------------------------------------------------
task_mgr = get_background_task_manager()
expiry_alerts, expiry_all_status = check_api_expiry_alerts()
law_prom_map = fetch_latest_tax_law_promulgations()

saved_ws_preview = st.session_state.get("active_workspace_id", "").strip()
effective_ws_preview = saved_ws_preview if saved_ws_preview else "default_public"
selected_room_preview = st.session_state.get("current_room", ROOM_IDS[0])
active_room_key_preview = f"{effective_ws_preview}::{selected_room_preview}"

usage_stats = get_room_usage_stats(active_room_key_preview)
budget_exceeded, cur_krw, limit_krw = is_room_budget_exceeded(active_room_key_preview)
usage_ratio = min(1.0, cur_krw / limit_krw) if limit_krw > 0 else 0.0

with st.sidebar:
    st.markdown(
        "<div style='font-size:1.12rem; font-weight:800; color:#0f172a; line-height:1.4; margin-bottom:8px; letter-spacing:-0.4px;'>"
        "⚙️ 에이전트 제어판</div>",
        unsafe_allow_html=True
    )
    
    # 📦 [카드 1] 엔진 출력 모드 제어
    with st.container(border=True):
        if budget_exceeded:
            st.session_state.pro_toggle_state = False
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
            disabled=budget_exceeded,
            help="켜두면 질문 앞에 [프로]를 입력하지 않아도 최대 15만 자 문서 독해 및 30회 도구 호출 모드로 작동합니다."
        )
        st.session_state.pro_toggle_state = pro_toggle_on
        if budget_exceeded:
            st.caption(f"⛔ 이 방 한도({limit_krw:,.0f}원) 도달로 Pro 잠김")

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
            st.session_state.room_usage = ws_data.get("room_usage", {r_id: {} for r_id in ROOM_IDS})
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

    # 📦 [카드 3] 멀티 대화방 선택 (`🔄개정감지` 역추적 태깅 연동) 및 🔍 10개 방 통합 키워드 검색
    with st.container(border=True):
        rooms_with_rev_cnt = sum(
            1 for r_id in ROOM_IDS
            if get_room_revision_alerts(effective_ws_id, r_id, st.session_state.chat_rooms.get(r_id, []), law_prom_map)[0]
        )
        rev_header_pill = (
            f"<span class='sb-badge-amber'>🔄 {rooms_with_rev_cnt}개방 개정관련</span>"
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

        def format_room_label(r_id: str) -> str:
            title = st.session_state.room_titles.get(r_id, "")
            r_msgs = st.session_state.chat_rooms.get(r_id, [])
            q_cnt = (len(r_msgs) + 1) // 2
            f_items = st.session_state.room_files[r_id].get("items", [])
            file_mark = f"📎({len(f_items)})" if f_items else ""
            t_info = task_mgr["tasks"].get(f"{effective_ws_id}::{r_id}")
            running_mark = " ⏳분석중" if (t_info and t_info.get("status") == "running") else ""
            rev_alerts, is_post = get_room_revision_alerts(effective_ws_id, r_id, r_msgs, law_prom_map)
            rev_mark = (" 🔄사후개정" if is_post else " 📜개정법포함") if rev_alerts else ""
            return f"💬 {r_id} [{title}] ({q_cnt}건) {file_mark}{rev_mark}{running_mark}"

        selected_room = st.selectbox(
            "대화방 선택",
            options=ROOM_IDS,
            index=ROOM_IDS.index(st.session_state.current_room),
            format_func=format_room_label,
            label_visibility="collapsed",
            help="과거 검토에 인용된 법령이 개정되면 방 이름 옆에 자동으로 표시됩니다."
        )
        if selected_room != st.session_state.current_room:
            st.session_state.current_room = selected_room
            st.rerun()

        active_room_key = f"{effective_ws_id}::{selected_room}"
        usage_stats = get_room_usage_stats(active_room_key)
        budget_exceeded, cur_krw, limit_krw = is_room_budget_exceeded(active_room_key)
        usage_ratio = min(1.0, cur_krw / limit_krw) if limit_krw > 0 else 0.0

        new_title = st.text_input(
            "방 주제 메모",
            value=st.session_state.room_titles[selected_room],
            placeholder="✏️ 방 주제 메모 (예: A사 세무조사)",
            label_visibility="collapsed",
            key=f"title_input_{effective_ws_id}_{selected_room}"
        )
        if new_title != st.session_state.room_titles[selected_room]:
            st.session_state.room_titles[selected_room] = new_title
            save_workspace_to_disk(effective_ws_id)
            st.rerun()

        if st.button(f"🗑️ [{selected_room}] 현재 방 비우기 (요금 0원 초기화)", use_container_width=True):
            task_mgr["tasks"].pop(active_room_key, None)
            st.session_state.chat_rooms[selected_room] = []
            st.session_state.room_files[selected_room] = {"name": None, "text": "", "items": []}
            st.session_state.room_titles[selected_room] = "빈 대화방"
            if hasattr(agent, "reset_room_usage"):
                agent.reset_room_usage(active_room_key)
            st.session_state[f"reset_cnt_{selected_room}"] = st.session_state.get(f"reset_cnt_{selected_room}", 0) + 1
            save_workspace_to_disk(effective_ws_id)
            st.rerun()

    # 📦 [카드 4] 현재 방 다중 자료 업로드 (엑셀/PDF/워드 + 📸 사진·스캔본 자동 OCR)
    with st.container(border=True):
        room_file_entry = _normalize_room_file_entry(st.session_state.room_files[selected_room])
        st.session_state.room_files[selected_room] = room_file_entry
        saved_items = room_file_entry["items"]
        file_pill = f"<span class='sb-badge-green'>📎 {len(saved_items)}개 유지중</span>" if saved_items else ""
        st.markdown(f"<div class='sb-card-title'><span>📂 [{selected_room}] 다중 자료·사진 첨부</span>{file_pill}</div>", unsafe_allow_html=True)

        reset_cnt = st.session_state.get(f"reset_cnt_{selected_room}", 0)
        uploaded_files = st.file_uploader(
            "엑셀, PDF(스캔본 포함), 워드, 사진(.jpg/.png) 다중 업로드",
            type=["xlsx", "xls", "csv", "pdf", "docx", "png", "jpg", "jpeg"],
            accept_multiple_files=True,
            label_visibility="collapsed",
            key=f"uploader_{effective_ws_id}_{selected_room}_{reset_cnt}",
            help="여러 파일을 동시에 올릴 수 있습니다. 사진이나 스캔본 PDF는 최초 1회만 Flash 비전으로 글자를 자동 추출해 저장합니다."
        )

        if uploaded_files:
            existing_names = {it["name"] for it in saved_items}
            new_added = False
            for uf in uploaded_files:
                if uf.name not in existing_names:
                    with st.spinner(f"📄 '{uf.name}' 내용 추출 및 저장 중..."):
                        extracted_text = extract_file_content(uf, room_key=active_room_key)
                        saved_items.append({"name": uf.name, "text": extracted_text})
                        existing_names.add(uf.name)
                        new_added = True
            if new_added:
                st.session_state.room_files[selected_room] = _normalize_room_file_entry({"items": saved_items})
                save_workspace_to_disk(effective_ws_id)
                st.rerun()

        if saved_items:
            for f_idx, f_item in enumerate(saved_items):
                c_f1, c_f2 = st.columns([4, 1])
                with c_f1:
                    st.caption(f"📄 **{f_item['name']}** ({len(f_item['text']):,}자)")
                with c_f2:
                    if st.button("✕", key=f"del_f_{selected_room}_{f_idx}", help=f"{f_item['name']} 삭제"):
                        saved_items.pop(f_idx)
                        st.session_state.room_files[selected_room] = _normalize_room_file_entry({"items": saved_items})
                        st.session_state[f"reset_cnt_{selected_room}"] = reset_cnt + 1
                        save_workspace_to_disk(effective_ws_id)
                        st.rerun()
            if len(saved_items) > 1:
                if st.button("❌ 이 방의 첨부파일 전체 비우기", key=f"clear_all_f_{selected_room}", use_container_width=True):
                    st.session_state.room_files[selected_room] = {"name": None, "text": "", "items": []}
                    st.session_state[f"reset_cnt_{selected_room}"] = reset_cnt + 1
                    save_workspace_to_disk(effective_ws_id)
                    st.rerun()

    # 📦 [보조 메뉴] 7대 기관 연동 (`🟢 법제처` 자동 감지) · 📜 공식 개정이유서(0토큰) · API 만료일 · 백업
    exp_header_badge = " ⚠️" if expiry_alerts else ""
    with st.expander(f"📡 7대 기관 DB 연동 및 전체 백업{exp_header_badge}"):
        led_law   = "🟢" if (bool(_get_law_oc()) or _check_api_configured(["LAW_OPEN_API_KEY", "LAW_API_OC", "OC"]) or bool(law_prom_map)) else "🟡"
        led_nts   = "🟢" if _check_api_configured(["NTS_API_KEY", "DATA_GO_KR_KEY", "PUBLIC_DATA_KEY"]) else "🟡"
        led_dart  = "🟢" if _check_api_configured(["DART_API_KEY", "OPENDART_API_KEY"]) else "🟡"
        led_molit = "🟢" if _check_api_configured(["MOLIT_API_KEY", "DATA_GO_KR_KEY", "VWORLD_API_KEY"]) else "🟡"
        led_bok   = "🟢" if _check_api_configured(["BOK_API_KEY", "ECOS_API_KEY"]) else "🟡"
        led_ind   = "🟢" if os.path.exists("industry_codes.xlsx") else "🟡"
        st.caption(
            f"{led_law} 법제처(무기한·구법포함) · {led_nts} 국세청 · {led_dart} DART(무기한)\n\n"
            f"{led_molit} 국토부/브이월드 · {led_bok} 한국은행 · {led_ind} 업종DB"
        )
        if st.button("📜 공식 『제·개정이유서』 원문 열람 (0토큰)", use_container_width=True):
            if _dialog_decorator:
                open_official_reason_modal(law_prom_map, effective_ws_id, selected_room, pro_toggle_on, budget_exceeded)
            else:
                st.session_state.show_inline_reason_viewer = True

        st.divider()
        st.markdown("**⏰ 유효기간 있는 3대 API 만료일 설정** *(만료 30일 전부터 화면 상단 자동 경고)*")
        current_expiry_map = load_api_expiry_dates()
        updated_expiry_map = {}
        for st_item in expiry_all_status:
            code = st_item["code"]
            d_left = st_item["days_left"]
            status_tag = f"🔴 D-{d_left}" if d_left <= 30 else f"🟢 D-{d_left}"
            val_str = st.text_input(
                f"{st_item['name']} (주기: {st_item['cycle']}) [{status_tag}]",
                value=current_expiry_map.get(code, st_item["date_str"]),
                placeholder="YYYY-MM-DD",
                key=f"exp_input_{code}"
            )
            updated_expiry_map[code] = val_str.strip()
        if st.button("💾 API 만료일 저장", use_container_width=True):
            save_api_expiry_dates(updated_expiry_map)
            st.success("만료일이 저장되었습니다!")
            st.rerun()

        st.divider()
        room_usage_backup = {
            r_id: get_room_usage_stats(f"{effective_ws_id}::{r_id}")
            for r_id in ROOM_IDS
        }
        backup_json_bytes = json.dumps({
            "chat_rooms": st.session_state.chat_rooms,
            "room_titles": st.session_state.room_titles,
            "room_files": st.session_state.room_files,
            "room_usage": room_usage_backup
        }, ensure_ascii=False, indent=2).encode("utf-8")
        st.download_button(
            label="📥 10개 방 전체 백업 (.json)",
            data=backup_json_bytes,
            file_name="세무에이전트_전체백업.json",
            mime="application/json",
            use_container_width=True
        )
        restored_file = st.file_uploader("📤 백업 복원 (.json)", type=["json"], key="restore_uploader")
        if restored_file is not None:
            if st.button("✅ 복원 실행", use_container_width=True):
                try:
                    loaded_backup = json.loads(restored_file.read().decode("utf-8"))
                    st.session_state.chat_rooms = loaded_backup["chat_rooms"]
                    st.session_state.room_titles = loaded_backup["room_titles"]
                    st.session_state.room_files = {
                        r: _normalize_room_file_entry(loaded_backup.get("room_files", {}).get(r, {}))
                        for r in ROOM_IDS
                    }
                    restored_usage = loaded_backup.get("room_usage", {})
                    if hasattr(agent, "set_room_usage_from_backup"):
                        for r in ROOM_IDS:
                            if r in restored_usage:
                                agent.set_room_usage_from_backup(f"{effective_ws_id}::{r}", restored_usage[r])
                    save_workspace_to_disk(effective_ws_id)
                    st.rerun()
                except Exception as e:
                    st.error(f"복원 실패: {e}")
        unlock_all_reset = st.checkbox("전체 초기화/파기 동의", key="unlock_reset")
        col_r1, col_r2 = st.columns(2)
        with col_r1:
            if st.button("🔄 전체 비우기", disabled=not unlock_all_reset, use_container_width=True):
                fresh_data = get_default_workspace_data()
                st.session_state.chat_rooms = fresh_data["chat_rooms"]
                st.session_state.room_titles = fresh_data["room_titles"]
                st.session_state.room_files = fresh_data["room_files"]
                for r_id in ROOM_IDS:
                    rk = f"{effective_ws_id}::{r_id}"
                    task_mgr["tasks"].pop(rk, None)
                    if hasattr(agent, "reset_room_usage"):
                        agent.reset_room_usage(rk)
                    st.session_state[f"reset_cnt_{r_id}"] = st.session_state.get(f"reset_cnt_{r_id}", 0) + 1
                save_workspace_to_disk(effective_ws_id)
                st.rerun()
        with col_r2:
            if st.button("🔥 공간 파기", disabled=(not unlock_all_reset or not workspace_input.strip()), use_container_width=True):
                for r_id in ROOM_IDS:
                    rk = f"{effective_ws_id}::{r_id}"
                    task_mgr["tasks"].pop(rk, None)
                    if hasattr(agent, "reset_room_usage"):
                        agent.reset_room_usage(rk)
                delete_workspace_from_disk(effective_ws_id)
                st.session_state.active_workspace_id = ""
                st.session_state.loaded_workspace_id = None
                st.session_state.ws_widget_ver = ws_widget_ver + 1
                st.rerun()

    # 📦 [카드 5 — 최하단 고정: 현재 대화방 2,000원 한도 계량기 & 3버튼 1줄 배치]
    with st.container(border=True):
        total_tokens_k = (usage_stats.get("input_tokens", 0) + usage_stats.get("output_tokens", 0)) / 1000.0
        cur_usd = float(usage_stats.get("total_usd", 0.0))
        badge_cls = "sb-badge-amber" if budget_exceeded else "sb-badge-green"
        st.markdown(
            f"<div class='sb-card-title'><span>💳 [{selected_room}] 요금 계량기</span>"
            f"<span class='{badge_cls}'>{usage_ratio*100:.1f}%</span></div>",
            unsafe_allow_html=True
        )
        st.markdown(
            f"<div style='display:flex; justify-content:space-between; align-items:baseline; line-height:1.4; margin-bottom:4px;'>"
            f"<span style='font-size:1.00rem; font-weight:800; color:#0f172a;'>{cur_krw:,.0f}원 "
            f"<span style='font-size:0.72rem; font-weight:500; color:#64748b;'>(${cur_usd:.3f} / {limit_krw:,.0f}원)</span></span>"
            f"<span style='font-size:0.71rem; color:#475569;'>Flash <b>{usage_stats.get('flash_calls', 0)}</b> · Pro <b>{usage_stats.get('pro_calls', 0)}</b> ({total_tokens_k:,.1f}K)</span>"
            f"</div>",
            unsafe_allow_html=True
        )
        st.progress(usage_ratio)

        col_b1, col_b2, col_b3 = st.columns(3)
        with col_b1:
            if st.button("🔄 갱신", use_container_width=True, help="실시간 사용량 새로고침"):
                st.rerun()
        with col_b2:
            st.link_button("💳 결제", "https://console.cloud.google.com/billing", use_container_width=True)
        with col_b3:
            st.link_button("🔑 API키", "https://aistudio.google.com/apikey", use_container_width=True)

# ---------------------------------------------------------
# 3. 메인 화면 및 현재 선택된 대화방 렌더링
# ---------------------------------------------------------
current_messages = st.session_state.chat_rooms[selected_room]
current_room_title = st.session_state.room_titles[selected_room]
current_file_info = _normalize_room_file_entry(st.session_state.room_files[selected_room])
current_task_key = f"{effective_ws_id}::{selected_room}"
active_task = task_mgr["tasks"].get(current_task_key)
is_current_room_running = bool(active_task and active_task.get("status") == "running")

if budget_exceeded:
    mode_status_str = f"⛔ **Pro 차단됨 (이 대화방 한도 {limit_krw:,.0f}원 도달 → Flash 안전 작동 중)**"
elif pro_toggle_on:
    mode_status_str = "🧠 **Pro 심층 모드 (3배 리미트 개방 ON)**"
else:
    mode_status_str = "⚡ **Flash 표준 모드 (고속 검토)**"

st.title(f"⚖️ 세무·법령·회계 자율 에이전트 — [{selected_room}: {current_room_title}]")
st.markdown(
    f"💡 **현재 엔진 상태:** {mode_status_str} &nbsp;|&nbsp; **[{selected_room}] 누적 예상 요금:** **`{cur_krw:,.0f}원 / {limit_krw:,.0f}원`**"
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

# 🔄 2) [방식 1: 사후 개정 감지 vs 최근 공포·시행예정 법령 개정이유서 안내 구분 표시]
current_room_rev_alerts, is_post_revision = get_room_revision_alerts(
    effective_ws_id, selected_room, current_messages, law_prom_map
)
if current_room_rev_alerts:
    rev_names_str = ", ".join(
        f"「{it['law_name']}」(공포:{it['prom_date']}/시행:{it['enf_date']})" for it in current_room_rev_alerts
    )
    first_clean = current_room_rev_alerts[0]["clean_name"]
    c_rv1, c_rv2, c_rv3, c_rv4 = st.columns([3.5, 1.1, 1.1, 0.8])
    with c_rv1:
        if is_post_revision:
            st.warning(
                f"🔄 **[사후 법령 개정 감지]** 이 방의 과거 검토 이후에 **{rev_names_str}**이 새로 개정 공포되었습니다."
            )
        else:
            st.info(
                f"📜 **[최근 공포·시행예정 법령 인용 안내]** 이 방에서 인용된 **{rev_names_str}**의 공식 개정이유서를 0원으로 열람할 수 있습니다."
            )
    with c_rv2:
        if st.button("📜 개정이유서(0원)", key=f"rsn_{selected_room}", use_container_width=True):
            if _dialog_decorator:
                open_official_reason_modal(law_prom_map, effective_ws_id, selected_room, pro_toggle_on, budget_exceeded, first_clean)
            else:
                st.session_state.show_inline_reason_viewer = True
    with c_rv3:
        if st.button("⚡ 신·구법 비교", key=f"rerev_{selected_room}", disabled=is_current_room_running, use_container_width=True):
            acknowledge_room_laws(effective_ws_id, selected_room, current_room_rev_alerts)
            laws_only = ", ".join(f"「{it['law_name']}」" for it in current_room_rev_alerts)
            re_q = (
                f"이 대화방의 직전 검토 사안과 관련하여, 최근 개정 공포된 {laws_only}의 최신 조문을 조회해 "
                "[종전 규정 vs 현행(개정) 규정 vs 적용시기 및 실무 영향] 신·구 비교표와 함께 정리해 줘."
            )
            _trigger_agent_task(effective_ws_id, selected_room, re_q, pro_toggle_on, budget_exceeded, force_flash=False)
    with c_rv4:
        if st.button("✅ 확인", key=f"ack_{selected_room}", use_container_width=True, help="이 대화방의 법령 알림을 확인 처리하여 숨깁니다."):
            acknowledge_room_laws(effective_ws_id, selected_room, current_room_rev_alerts)
            st.rerun()

# 구버전 Streamlit 폴백용 인라인 뷰어
if st.session_state.get("show_inline_reason_viewer"):
    with st.container(border=True):
        st.subheader("📜 법제처 공식 『제·개정이유 및 주요내용』 원문 뷰어 (0토큰)")
        _render_official_reason_viewer_body(law_prom_map, effective_ws_id, selected_room, pro_toggle_on, budget_exceeded)
        if st.button("✖️ 뷰어 닫기"):
            st.session_state.show_inline_reason_viewer = False
            st.rerun()

for idx, message in enumerate(current_messages):
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
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
                        pro_toggle_on, budget_exceeded, force_flash=True
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
                        pro_toggle_on, budget_exceeded, force_flash=True
                    )
            with act3:
                if st.button(
                    "🧠 [프로] 3배 개방 재검토",
                    key=f"repro_{effective_ws_id}_{selected_room}_{idx}",
                    disabled=(is_current_room_running or budget_exceeded),
                    use_container_width=True
                ):
                    _trigger_agent_task(
                        effective_ws_id, selected_room,
                        "[프로] 직전 질문 사안에 대해 관련 법령·시행령·판례·심판례·예규와 예외 요건까지 데이터·도구 한도를 3배 개방하여 심층 재검토해 줘.",
                        pro_toggle_on, budget_exceeded, force_flash=False
                    )

            with st.expander("📋 카톡·이메일 전송용 텍스트 원클릭 복사 (우측 상단 복사 아이콘 클릭)"):
                st.code(_extract_clean_copy_text(message["content"]), language="markdown")

# 4. 새로운 질문 입력 시 -> 공통 백그라운드 실행기 호출
if prompt := st.chat_input(
    placeholder=(
        f"⏳ [{selected_room}] 현재 백그라운드 정밀 검토 진행 중입니다... (다른 대화방으로 이동하여 추가 질문을 하실 수 있습니다)"
        if is_current_room_running else
        f"[{selected_room}] 검토할 이슈를 입력하세요 (좌측 Pro 토글 ON 또는 맨 앞에 [프로] 입력 시 3배 개방)"
    ),
    disabled=is_current_room_running,
    key=f"chat_input_{effective_ws_id}_{selected_room}"
):
    _trigger_agent_task(
        effective_ws_id=effective_ws_id,
        selected_room=selected_room,
        raw_prompt=prompt,
        pro_toggle_on=pro_toggle_on,
        budget_exceeded=budget_exceeded,
        force_flash=False
    )

# 5. 현재 방에서 백그라운드 작업이 진행 중일 때 실시간 상태창 표시
active_task = task_mgr["tasks"].get(current_task_key)
if active_task and active_task.get("status") == "running":
    is_pro_running = active_task.get("is_pro", False)
    status_title = (
        f"🧠 [{selected_room}] Pro 심층 모드 백그라운드 가동 중 (데이터·도구 한도 3배 개방)..."
        if is_pro_running else
        f"⚡ [{selected_room}] 실시간 법령·공시 DB 조회 및 백그라운드 정밀 검토 중..."
    )
    with st.chat_message("assistant"):
        with st.status(status_title, expanded=True) as status_box:
            st.write("🔎 **1단계:** 질의 쟁점 분석 및 7대 국가·공공기관(법제처 현행·구법·국세청·DART·국토부·한은) DB 탐색 중...")
            st.write("🧮 **2단계:** 관련 법령·판례 원문 파싱 및 파이썬 1원 단위 정밀 수리 계산기 구동 중...")
            st.write("🛡️ **3단계:** 미조회 근거 강제 차단(`_scan_violations`) 및 듀얼 AI 의미 감수(`_semantic_verify`) 수행 중...")
            st.caption("💡 **백그라운드 멀티태스킹 작동 중:** 지금 좌측 버튼을 누르거나 다른 대화방으로 이동하셔도 이 방의 AI 검토는 멈추지 않고 끝까지 완료됩니다.")
            while active_task.get("status") == "running":
                time.sleep(0.4)
            status_box.update(label="✅ 정밀 검토 및 무결성 감수 완료", state="complete", expanded=False)

    ans = active_task.get("response", "")
    if ans and (not current_messages or current_messages[-1].get("role") != "assistant" or current_messages[-1].get("content") != ans):
        current_messages.append({"role": "assistant", "content": ans})
    task_mgr["tasks"].pop(current_task_key, None)
    save_workspace_to_disk(effective_ws_id)
    st.rerun()
