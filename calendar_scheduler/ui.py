# -*- coding: utf-8 -*-
"""
달력 스케줄러 + 우측 하단 말풍선 홈버튼 + 60% 애니메이션 확장 카카오톡 To-Do 패키지 (calendar_scheduler/ui.py)

[디자인 기준: ui_theme.py (화면 디자인 B안) & toss_web_design_system_prompt.md (Toss Web TDS)]
- 전체 배경: #F4F6FA (고정 라이트 캔버스)
- 카드 표면: #FFFFFF (순백색 카드 + 1px solid #E5E8EB 테두리 + 14~16px 라운드)
- 달력 본문: 30% 반투명 글래스모피즘 (rgba(255, 255, 255, 0.30) + backdrop-filter: blur(14px))
- 달력 상단 레이아웃:
  · 좌측(달력 열 기준 좌측 정렬): [일정 N건] · [AI작업중 N건] · [작업완료, 승인요청 N건] 상태 카드 3종 (높이 74px)
  · 우측('선택한 날짜의 할 일' 열 기준): 좌측 라인 정렬 'N월' (높이 74px, 좌측 상태 카드와 상·하단 라인 일치) + 우측 라인 정렬 '＋ 일정 추가하기' 버튼
- 우측 하단 플로팅 홈버튼:
  · #3898FF 파란 라운드 스퀘어 안의 확대된 동그라미 미소 얼굴(귀·머리카락 제거, 열림 시 아래 화살표 ∨ 전환)
  · 네모 말풍선(border-radius: 6px) 실시간 알림 팝업
  · 클릭 시 우측 하단 모서리부터 화면 60% 크기로 부드럽게 확장되는 카카오톡 백그라운드 작업 To-Do 체크리스트 오버레이
- 실시간 한국 표준시(KST) 당일 날짜·연월 자동 인식 반영
"""
from __future__ import annotations

import calendar
import html as _html_lib
import json
from datetime import date, datetime
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

import streamlit as st
import streamlit.components.v1 as components

import ui_theme as _ui_theme

_WEEKDAYS_SHORT = ("월", "화", "수", "목", "금", "토", "일")
_SUN_FIRST_HEADERS = ("일", "월", "화", "수", "목", "금", " 토")



def _html(s: str) -> str:
    """여러 줄 HTML을 한 줄로 이어 붙여 표시 (빈 줄·들여쓰기 때문에 HTML이 코드 글자로 보이는 문제 방지 — 브라우저 표시 결과는 동일)"""
    return " ".join(ln.strip() for ln in str(s).splitlines() if ln.strip())

def get_kst_today() -> date:
    """한국 표준시(KST, Asia/Seoul) 기준 오늘 날짜를 반환합니다."""
    return datetime.now(ZoneInfo("Asia/Seoul")).date()


def _default_schedules_for_month(year: int, month: int, today_d: date) -> Dict[int, List[Dict[str, Any]]]:
    """당해 연월의 기본 세무 일정 및 카카오톡 백그라운드 자동화 연계 일정을 생성합니다."""
    focus_day = today_d.day if (today_d.year == year and today_d.month == month) else 4
    last_day = calendar.monthrange(year, month)[1]
    focus_day = min(max(1, focus_day), last_day)

    data: Dict[int, List[Dict[str, Any]]] = {
        focus_day: [
            {
                "id": f"sch_{year}_{month}_{focus_day}_1",
                "time": "10:00",
                "title": "(주)모 회사 세법 검토 카톡 발송",
                "client": "(주)모 회사",
                "category": "세법검토",
                "ai_status": "작업 완료, 승인요청중",
                "done": False,
                "desc": "통합고용세액공제 및 2026년 귀속 최신 개정 세법 검토 안내문 카톡 초안 작성 완료",
            },
            {
                "id": f"sch_{year}_{month}_{focus_day}_2",
                "time": "11:30",
                "title": "(주)갑 회사 요청 서류 발송",
                "client": "(주)갑 회사",
                "category": "서류발송",
                "ai_status": "작업 완료, 승인요청중",
                "done": False,
                "desc": "홈택스 부가가치세 과세표준증명원·납세증명서 다운로드 및 카톡 첨부 준비 완료",
            },
            {
                "id": f"sch_{year}_{month}_{focus_day}_3",
                "time": "15:00",
                "title": "(주)을 법인 가결산 자료 수집 카톡",
                "client": "(주)을 법인",
                "category": "자료요청",
                "ai_status": "백그라운드 작업중",
                "done": False,
                "desc": f"{year}년 귀속 법인세 중간예납·가결산 필요 서류 안내 메시지 자동 생성 중",
            },
        ],
        10: [
            {
                "id": f"sch_{year}_{month}_10_1",
                "time": "18:00",
                "title": "원천세 및 4대보험 신고·납부 마감",
                "client": "전체 기장 거래처",
                "category": "기한고지",
                "ai_status": "작업 완료, 승인요청중",
                "done": False,
                "desc": "원천징수이행상황신고서 마감 및 거래처별 납부서 카톡 일괄 안내 대기",
            },
        ],
        15: [
            {
                "id": f"sch_{year}_{month}_15_1",
                "time": "14:00",
                "title": "사업장현황신고 및 전자세금계산서 합계표 점검",
                "client": "주요 법인·개인 거래처",
                "category": "세무일정",
                "ai_status": "사용자 승인완료",
                "done": True,
                "desc": "전자세금계산서 발급 누락 여부 점검 및 카톡 알림 발송 완료",
            },
        ],
        25: [
            {
                "id": f"sch_{year}_{month}_25_1",
                "time": "10:00",
                "title": f"{month}월 귀속 급여대장·급여명세서 카톡 발송",
                "client": "인건비 자동화 연동 거래처",
                "category": "인건비",
                "ai_status": "백그라운드 작업중",
                "done": False,
                "desc": "인건비 자동화 모듈에서 생성된 급여명세서 PDF/JPG 거래처별 카톡 전송 준비",
            },
        ],
        last_day: [
            {
                "id": f"sch_{year}_{month}_{last_day}_1",
                "time": "17:00",
                "title": f"{month}월 세무 신고·납부 마감일 최종 점검",
                "client": "전체 거래처",
                "category": "세무마감",
                "ai_status": "작업 완료, 승인요청중",
                "done": False,
                "desc": "당월 마감 세목 미납·미신고 거래처 최종 확인 카톡 안내문 준비 완료",
            },
        ],
    }
    return data


def _default_kakao_todos(today_d: date) -> List[Dict[str, Any]]:
    """우측 하단 60% 확장 패널에 표시할 카카오톡 백그라운드 자동화 To-Do 리스트 초기값"""
    yr = today_d.year
    mo = today_d.month
    return [
        {
            "id": "ktodo_1",
            "client": "(주)모 회사",
            "recipient": "범준",
            "title": "(주)모 회사에 보낼 세법 검토 카톡 완성",
            "bubble_msg": "범준님 (주)모 회사에 보낼 세법 검토 카톡이 완성되었습니다",
            "status": "작업 완료, 승인요청중",
            "category": "세법 검토 카톡",
            "time_ago": "방금 전",
            "checked": True,
            "preview": (
                f"안녕하세요 대표님, 세무회계 사무소입니다.\n"
                f"문의주신 {yr}년 귀속 통합고용세액공제(조세특례제한법 제29조의8) 관련하여, "
                f"올해 청년 정규직 2명 추가 채용 시 1인당 연 1,450만 원(수도권 중소기업 기준) 공제 적용이 가능합니다. "
                f"상세 시뮬레이션 표를 첨부드리오니 확인 부탁드립니다."
            ),
            "attachment": f"(주)모회사_{yr}년귀속_통합고용세액공제_검토보고서.pdf",
        },
        {
            "id": "ktodo_2",
            "client": "(주)갑 회사",
            "recipient": "범준",
            "title": "(주)갑 회사 요청 서류 다운로드 및 발송 준비 완료",
            "bubble_msg": "범준님 (주)갑 회사로부터 요청받은 서류를 다운받아 보낼 준비가 끝났습니다",
            "status": "작업 완료, 승인요청중",
            "category": "민원서류 자동수집",
            "time_ago": "3분 전",
            "checked": True,
            "preview": (
                f"안녕하세요 (주)갑 회사 담당자님.\n"
                f"요청하신 국세 완납증명서, 부가가치세 과세표준증명원, 표준재무제표증명({yr - 1}년 귀속) "
                f"총 3종 서류 발급을 완료하여 전달드립니다. 은행 제출용 비밀번호는 사업자번호 뒤 4자리입니다."
            ),
            "attachment": f"(주)갑회사_국세완납_과세표준_재무제표증명_{today_d.strftime('%Y%m%d')}.zip",
        },
        {
            "id": "ktodo_3",
            "client": "(주)한빛테크",
            "recipient": "범준",
            "title": f"(주)한빛테크 {mo}월 급여대장 및 원천세 납부서 카톡 준비 완료",
            "bubble_msg": f"범준님 (주)한빛테크 {mo}월 급여대장 및 원천세 납부서 카톡 발송 준비가 끝났습니다",
            "status": "작업 완료, 승인요청중",
            "category": "인건비·원천세",
            "time_ago": "12분 전",
            "checked": False,
            "preview": (
                f"안녕하세요 (주)한빛테크 대표님.\n"
                f"{yr}년 {mo}월 귀속 급여대장 및 임직원 급여명세서, 원천세 납부서 전달드립니다. "
                f"이번 달 원천세 납부기한은 10일입니다."
            ),
            "attachment": f"(주)한빛테크_{yr}년{mo:02d}월_급여대장_및_원천세납부서.pdf",
        },
        {
            "id": "ktodo_4",
            "client": "(주)을 법인",
            "recipient": "범준",
            "title": f"(주)을 법인 {yr}년 귀속 가결산 법인세 중간예납 세액 검토 및 안내문 생성",
            "bubble_msg": f"범준님 (주)을 법인 가결산 세액 검토 카톡을 백그라운드에서 작성 중입니다 (78%)",
            "status": "백그라운드 작업중",
            "category": "AI 백그라운드 작업",
            "time_ago": "진행중 (78%)",
            "checked": False,
            "preview": (
                f"[AI 백그라운드 작업 진행 중 — 78%]\n"
                f"· 1단계: 법제처 조세특례제한법·법인세법 {yr}년 개정 조문 대조 완료\n"
                f"· 2단계: (주)을 법인 손익계산서 가결산 세액 산출 중\n"
                f"· 3단계: 대표님 발송용 쉬운 카톡 요약본 생성 중..."
            ),
            "attachment": "생성 중...",
        },
        {
            "id": "ktodo_5",
            "client": "디자인스튜디오 봄",
            "recipient": "범준",
            "title": f"디자인스튜디오 봄 3.3% 사업소득 지급명세서 카톡 발송 완료",
            "bubble_msg": "범준님 디자인스튜디오 봄 카톡 발송이 승인 완료되었습니다",
            "status": "사용자 승인완료",
            "category": "발송 완료",
            "time_ago": "오늘 09:40 승인됨",
            "checked": True,
            "preview": (
                f"안녕하세요 디자인스튜디오 봄 대표님.\n"
                f"{mo}월 프리랜서 3.3% 사업소득 원천징수 영수증 및 지급대장 전송 완료되었습니다."
            ),
            "attachment": f"디자인스튜디오봄_{yr}{mo:02d}_사업소득대장.pdf",
        },
    ]


def _init_calendar_state() -> Dict[str, Any]:
    today_d = get_kst_today()
    today_iso = today_d.isoformat()
    if "cal_scheduler_state" not in st.session_state:
        ym_key = f"{today_d.year:04d}-{today_d.month:02d}"
        st.session_state["cal_scheduler_state"] = {
            "_last_kst_today_iso": today_iso,
            "year": today_d.year,
            "month": today_d.month,
            "selected_day": today_d.day,
            "schedules_by_ym": {
                ym_key: _default_schedules_for_month(today_d.year, today_d.month, today_d),
            },
            "kakao_todos": _default_kakao_todos(today_d),
            "panel_open": False,
            "bubble_visible": True,
            "bubble_idx": 0,
            "todo_filter": "전체",
            "show_add_modal": False,
        }
    cstate = st.session_state["cal_scheduler_state"]
    # 한국시간(KST) 매일 00:00 자정이 지나 날짜가 바뀌면 오늘 기준 연·월·일을 즉시 갱신
    if cstate.get("_last_kst_today_iso") != today_iso:
        cstate["_last_kst_today_iso"] = today_iso
        cstate["year"] = today_d.year
        cstate["month"] = today_d.month
        cstate["selected_day"] = today_d.day
    ym_key = f"{int(cstate['year']):04d}-{int(cstate['month']):02d}"
    if ym_key not in cstate["schedules_by_ym"]:
        cstate["schedules_by_ym"][ym_key] = _default_schedules_for_month(
            int(cstate["year"]), int(cstate["month"]), today_d
        )
    return cstate


def _get_status_counts(cstate: Dict[str, Any]) -> Dict[str, int]:
    ym_key = f"{int(cstate['year']):04d}-{int(cstate['month']):02d}"
    month_map = cstate["schedules_by_ym"].get(ym_key, {})
    sel_day = int(cstate.get("selected_day", 1))
    day_items = month_map.get(sel_day, [])

    todos = cstate.get("kakao_todos", [])
    working_cnt = sum(1 for t in todos if t.get("status") == "백그라운드 작업중")
    req_cnt = sum(1 for t in todos if t.get("status") == "작업 완료, 승인요청중")
    done_cnt = sum(1 for t in todos if t.get("status") == "사용자 승인완료")
    return {
        "day_schedules": len(day_items),
        "month_schedules": sum(len(v) for v in month_map.values()),
        "working": working_cnt,
        "approval_req": req_cnt,
        "approved": done_cnt,
    }


CALENDAR_MAIN_CSS = """
<style>
/* ═════════ 화면 디자인 B안 & Toss Web TDS 공통 캔버스 ═════════ */
[data-testid="stApp"] [data-testid="stMain"],
[data-testid="stApp"] [data-testid="stAppScrollToBottomContainer"],
[data-testid="stApp"] [data-testid="stBottom"] > div {
    background: #F4F6FA !important;
}

/* 화면 머리 (ui_theme.py page_header 호환) */
.ecx-top { display:flex; align-items:center; justify-content:space-between; gap:10px; margin:0 0 6px; }
.ecx-crumb { font-size:.86rem; color:#64748B; font-weight:500; }
.ecx-crumb .sep { color:#94A3B8; margin:0 4px; }
.ecx-chips { display:flex; gap:8px; flex-wrap:wrap; justify-content:flex-end; }
.ecx-chip {
    display:inline-flex; align-items:center; gap:6px;
    font-size:.80rem; font-weight:600; padding:4px 11px;
    border-radius:999px; background:#FFFFFF; border:1px solid #E5E8EB;
    color:#334155; white-space:nowrap;
}
.ecx-chip.tds-blue { background:#E8F3FF; border-color:#C9E2FF; color:#3182F6; }
.ecx-chip.tds-green { background:#E5F9F0; border-color:#B8EED6; color:#00A660; }
.ecx-chip .dot { width:7px; height:7px; border-radius:50%; background:currentColor; display:inline-block; }
.ecx-h1 { font-size:1.72rem; font-weight:800; color:#191F28; letter-spacing:-.6px; line-height:1.25; margin-top:2px; }
.ecx-sub { font-size:.92rem; color:#4E5968; margin:4px 0 14px; }

/* ═════════ 달력 상단 바: 좌측 상태 카드 3개 (74px) & 우측 '11월' + '+ 일정 추가하기' (74px) ═════════ */
.tds-top-status-row {
    display: flex;
    align-items: stretch;
    justify-content: flex-start;
    gap: 10px;
    height: 74px;
    margin-bottom: 10px;
}
.tds-stat-card {
    background: #FFFFFF;
    border: 1px solid #E5E8EB;
    border-radius: 14px;
    padding: 10px 16px;
    min-width: 150px;
    height: 74px;
    box-sizing: border-box;
    display: flex;
    flex-direction: column;
    justify-content: center;
    box-shadow: 0 2px 8px rgba(15, 23, 42, 0.03);
    transition: transform 0.15s ease, border-color 0.15s ease;
}
.tds-stat-card:hover {
    border-color: #3182F6;
    transform: translateY(-1px);
}
.tds-stat-top {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 0.78rem;
    font-weight: 700;
    color: #4E5968;
    margin-bottom: 3px;
    white-space: nowrap;
}
.tds-stat-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    display: inline-block;
    flex: none;
}
.tds-stat-dot.blue { background: #3182F6; }
.tds-stat-dot.amber { background: #D97706; }
.tds-stat-dot.green { background: #00A660; }
.tds-stat-val {
    font-size: 1.24rem;
    font-weight: 800;
    color: #191F28;
    letter-spacing: -0.4px;
    line-height: 1.15;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
}
.tds-stat-val span.emph-blue { color: #3182F6; }
.tds-stat-val span.emph-amber { color: #D97706; }
.tds-stat-val span.emph-green { color: #00A660; }

/* 우측 선택한 날짜의 할 일 상단: 왼쪽 라인 맞춤 '11월' (74px 높이 일치) */
.tds-month-heading-box {
    display: flex;
    align-items: center;
    justify-content: flex-start;
    gap: 10px;
    height: 74px;
    margin-bottom: 10px;
    box-sizing: border-box;
}
.tds-month-big-text {
    font-size: 2.45rem;
    font-weight: 900;
    color: #191F28;
    letter-spacing: -1.2px;
    line-height: 1.0;
    font-variant-numeric: tabular-nums;
}
.tds-month-year-pill {
    font-size: 0.80rem;
    font-weight: 700;
    color: #4E5968;
    background: #FFFFFF;
    border: 1px solid #E5E8EB;
    border-radius: 999px;
    padding: 4px 10px;
    align-self: center;
}

/* 우측 '+ 일정 추가하기' 버튼 컨테이너: 오른쪽 라인 정렬 & 높이 74px 매칭 */
[data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-cal_add_btn_wrap {
    display: flex !important;
    align-items: center !important;
    justify-content: flex-end !important;
    height: 74px !important;
    margin-bottom: 10px !important;
}
[data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-cal_add_btn_wrap div.stButton {
    display: flex !important;
    justify-content: flex-end !important;
    width: 100% !important;
}
[data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-cal_add_btn_wrap div.stButton > button {
    background: #3182F6 !important;
    border: 1px solid #3182F6 !important;
    border-radius: 12px !important;
    color: #FFFFFF !important;
    font-weight: 700 !important;
    min-height: 44px !important;
    height: 44px !important;
    padding: 0 18px !important;
    box-shadow: 0 4px 12px rgba(49, 130, 246, 0.22) !important;
    width: auto !important;
}
[data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-cal_add_btn_wrap div.stButton > button:hover {
    background: #1B64DA !important;
    border-color: #1B64DA !important;
}
[data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-cal_add_btn_wrap div.stButton > button p {
    color: #FFFFFF !important;
    font-size: 0.90rem !important;
    font-weight: 700 !important;
}

/* ═════════ 30% 반투명 토스 스타일 달력 본문 (Glassmorphism) ═════════ */
[data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-cal_glass_surface {
    background: rgba(255, 255, 255, 0.30) !important;
    backdrop-filter: blur(16px) !important;
    -webkit-backdrop-filter: blur(16px) !important;
    border: 1px solid rgba(229, 232, 235, 0.90) !important;
    border-radius: 18px !important;
    padding: 16px 18px 18px !important;
    box-shadow: 0 4px 20px rgba(15, 23, 42, 0.04) !important;
}

.tds-cal-dow-grid {
    display: grid;
    grid-template-columns: repeat(7, 1fr);
    gap: 6px;
    margin-bottom: 8px;
    padding-bottom: 8px;
    border-bottom: 1px solid rgba(229, 232, 235, 0.85);
}
.tds-cal-dow-cell {
    text-align: center;
    font-size: 0.80rem;
    font-weight: 700;
    color: #4E5968;
    padding: 4px 0;
}
.tds-cal-dow-cell.sun { color: #F04452; }
.tds-cal-dow-cell.sat { color: #3182F6; }

/* 달력 날짜 셀 (30% 반투명 유지 + 선택일/오늘 강조) */
.tds-cal-day-card {
    background: rgba(255, 255, 255, 0.30);
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
    border: 1px solid rgba(229, 232, 235, 0.78);
    border-radius: 12px;
    min-height: 92px;
    padding: 8px 9px;
    box-sizing: border-box;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    transition: all 0.14s ease;
    margin-bottom: 4px;
}
.tds-cal-day-card:hover {
    background: rgba(255, 255, 255, 0.58);
    border-color: #3182F6;
}
.tds-cal-day-card.selected {
    background: rgba(232, 243, 255, 0.65);
    border: 2px solid #3182F6;
    box-shadow: 0 4px 12px rgba(49, 130, 246, 0.12);
}
.tds-cal-day-card.empty {
    background: rgba(255, 255, 255, 0.12);
    border: 1px dashed rgba(229, 232, 235, 0.45);
}
.tds-cal-day-top {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 5px;
}
.tds-cal-day-num {
    font-size: 0.86rem;
    font-weight: 700;
    color: #191F28;
    font-variant-numeric: tabular-nums;
}
.tds-cal-day-num.sun { color: #F04452; }
.tds-cal-day-num.sat { color: #3182F6; }
.tds-cal-today-badge {
    font-size: 0.66rem;
    font-weight: 800;
    color: #FFFFFF;
    background: #3182F6;
    padding: 1px 6px;
    border-radius: 999px;
}
.tds-cal-ev-list {
    display: flex;
    flex-direction: column;
    gap: 3px;
}
.tds-cal-ev-pill {
    font-size: 0.71rem;
    font-weight: 600;
    padding: 2px 6px;
    border-radius: 5px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    line-height: 1.3;
}
.tds-cal-ev-pill.blue { background: #E8F3FF; color: #1B64DA; }
.tds-cal-ev-pill.amber { background: #FFF5E5; color: #D97706; }
.tds-cal-ev-pill.green { background: #E5F9F0; color: #00A660; }

/* 날짜 선택 버튼 (컴팩트 플랫 버튼) */
[data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-cal_sel_d_"] div.stButton > button {
    min-height: 26px !important;
    height: 26px !important;
    padding: 0 6px !important;
    border-radius: 7px !important;
    font-size: 0.74rem !important;
    font-weight: 600 !important;
    background: rgba(255, 255, 255, 0.55) !important;
    border: 1px solid #E5E8EB !important;
    color: #4E5968 !important;
    box-shadow: none !important;
}
[data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-cal_sel_d_"] div.stButton > button[kind="primary"] {
    background: #3182F6 !important;
    border-color: #3182F6 !important;
    color: #FFFFFF !important;
}
[data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-cal_sel_d_"] div.stButton > button[kind="primary"] p {
    color: #FFFFFF !important;
    font-weight: 700 !important;
}

/* ═════════ 우측 '선택한 날짜의 할 일' 순백색 카드 ═════════ */
[data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-cal_right_todo_card,
[data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-cal_right_kakao_card {
    background: #FFFFFF !important;
    border: 1px solid #E5E8EB !important;
    border-radius: 16px !important;
    padding: 18px !important;
    box-shadow: 0 2px 10px rgba(15, 23, 42, 0.03) !important;
    margin-bottom: 12px !important;
}
.tds-side-hdr {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding-bottom: 10px;
    margin-bottom: 10px;
    border-bottom: 1px solid #F2F4F6;
}
.tds-side-title {
    font-size: 1.02rem;
    font-weight: 800;
    color: #191F28;
    letter-spacing: -0.3px;
}
.tds-side-badge {
    font-size: 0.74rem;
    font-weight: 700;
    padding: 3px 9px;
    border-radius: 999px;
    background: #E8F3FF;
    color: #3182F6;
}
.tds-todo-item-box {
    background: #F9FAFB;
    border: 1px solid #E5E8EB;
    border-radius: 12px;
    padding: 11px 13px;
    margin-bottom: 8px;
}
.tds-todo-item-top {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 6px;
    margin-bottom: 4px;
}
.tds-todo-time {
    font-size: 0.75rem;
    font-weight: 700;
    color: #8B95A1;
    font-variant-numeric: tabular-nums;
}
.tds-status-pill {
    font-size: 0.70rem;
    font-weight: 700;
    padding: 2px 8px;
    border-radius: 999px;
    white-space: nowrap;
}
.tds-status-pill.working { background: #FFF5E5; color: #D97706; }
.tds-status-pill.req { background: #E8F3FF; color: #3182F6; }
.tds-status-pill.done { background: #E5F9F0; color: #00A660; }
.tds-todo-title {
    font-size: 0.90rem;
    font-weight: 700;
    color: #191F28;
    margin-bottom: 2px;
}
.tds-todo-desc {
    font-size: 0.78rem;
    color: #4E5968;
    line-height: 1.4;
}
</style>
"""


def _status_pill_cls(status_str: str) -> str:
    if "작업중" in status_str:
        return "working"
    if "승인요청" in status_str:
        return "req"
    return "done"


def _ev_pill_cls(status_str: str) -> str:
    if "작업중" in status_str:
        return "amber"
    if "승인요청" in status_str:
        return "blue"
    return "green"


def render_calendar_sidebar() -> None:
    """좌측 사이드바 ('달력' 모드 전용 제어판 — ui_theme.py B안 사이드바 규격 100% 준수)"""
    cstate = _init_calendar_state()
    today_d = get_kst_today()
    counts = _get_status_counts(cstate)
    wd_str = _WEEKDAYS_SHORT[today_d.weekday()]

    with st.container(border=True):
        today_pill = f"<span class='sb-badge-green'>{today_d.strftime('%Y.%m.%d')} ({wd_str})</span>"
        st.markdown(_ui_theme.sb_title("calendar", "달력 기준일 · 월 이동", today_pill), unsafe_allow_html=True)

        c_y, c_m = st.columns(2)
        yr_opts = [today_d.year - 1, today_d.year, today_d.year + 1]
        cur_y = int(cstate.get("year", today_d.year))
        if cur_y not in yr_opts:
            yr_opts.append(cur_y)
            yr_opts.sort()
        with c_y:
            sel_y = st.selectbox(
                "연도",
                options=yr_opts,
                index=yr_opts.index(cur_y),
                format_func=lambda y: f"{y}년",
                key="cal_sb_year_sel",
            )
        with c_m:
            cur_m = int(cstate.get("month", today_d.month))
            sel_m = st.selectbox(
                "월",
                options=list(range(1, 13)),
                index=max(0, min(11, cur_m - 1)),
                format_func=lambda m: f"{m}월",
                key="cal_sb_month_sel",
            )

        if sel_y != cur_y or sel_m != cur_m:
            cstate["year"] = int(sel_y)
            cstate["month"] = int(sel_m)
            last_d = calendar.monthrange(int(sel_y), int(sel_m))[1]
            cstate["selected_day"] = min(int(cstate.get("selected_day", 1)), last_d)
            st.rerun()

        if st.button("오늘 날짜로 즉시 이동", icon=":material/today:", width="stretch", key="btn_cal_go_today"):
            cstate["year"] = today_d.year
            cstate["month"] = today_d.month
            cstate["selected_day"] = today_d.day
            st.rerun()

    with st.container(border=True):
        req_pill = (
            f"<span class='sb-badge-pro'>승인대기 {counts['approval_req']}건</span>"
            if counts["approval_req"] > 0
            else "<span class='sb-badge-green'>모두 승인됨</span>"
        )
        st.markdown(_ui_theme.sb_title("zap", "카톡 백그라운드 To-Do", req_pill), unsafe_allow_html=True)
        st.caption(
            "백그라운드에서 세법 검토나 민원서류 준비가 끝나면 우측 하단 홈버튼에서 네모 말풍선 알림이 뜨고, "
            "홈버튼을 누르면 화면 60% 크기의 체크 To-Do 리스트가 펼쳐집니다."
        )

        col_s1, col_s2 = st.columns(2)
        with col_s1:
            panel_btn_lbl = "60% To-Do 닫기" if cstate.get("panel_open") else "60% To-Do 열기"
            if st.button(
                panel_btn_lbl,
                type="primary" if not cstate.get("panel_open") else "secondary",
                width="stretch",
                key="btn_sb_toggle_todo_panel",
            ):
                cstate["panel_open"] = not cstate.get("panel_open", False)
                st.rerun()
        with col_s2:
            if st.button("알림 말풍선 전환", width="stretch", key="btn_sb_next_bubble"):
                cstate["bubble_visible"] = True
                cstate["bubble_idx"] = (int(cstate.get("bubble_idx", 0)) + 1) % max(1, len(cstate["kakao_todos"]))
                st.rerun()


def render_calendar_main() -> None:
    """메인 화면: 달력 스케줄러 + 선택한 날짜의 할 일 + 우측 하단 플로팅 홈버튼 & 60% To-Do 오버레이"""
    cstate = _init_calendar_state()
    today_d = get_kst_today()
    wd_str = _WEEKDAYS_SHORT[today_d.weekday()]
    counts = _get_status_counts(cstate)

    st.markdown(CALENDAR_MAIN_CSS, unsafe_allow_html=True)

    # 1. 상단 페이지 헤더 (ui_theme.py page_header 규격)
    chips_html = (
        f"<span class='ecx-chip tds-blue'><span class='dot'></span>오늘 {today_d.strftime('%Y.%m.%d')} ({wd_str}) · {today_d.year}년 귀속 기준</span>"
        f"<span class='ecx-chip tds-green'><span class='dot'></span>카톡 백그라운드 자동화 가동 중</span>"
    )
    st.markdown(
        _ui_theme.page_header(
            crumbs=["세무 에이전트", "달력"],
            chips_html=chips_html,
            title="달력 스케줄러 및 카카오톡 자동화 관리",
            sub="기장 거래처 세무 일정과 백그라운드 카카오톡 세법 검토·서류 발송 승인 현황을 한 화면에서 관리합니다.",
        ),
        unsafe_allow_html=True,
    )

    year = int(cstate["year"])
    month = int(cstate["month"])
    selected_day = int(cstate["selected_day"])
    ym_key = f"{year:04d}-{month:02d}"
    month_schedules = cstate["schedules_by_ym"].setdefault(
        ym_key, _default_schedules_for_month(year, month, today_d)
    )

    # 2. 달력 위 상단 구성:
    #    - 중앙 기준 왼쪽(달력 컬럼): 일정 N건 / AI작업중 N건 / 작업완료, 승인요청 N건
    #    - 오른쪽('선택한 날짜의 할 일' 컬럼): 왼쪽 라인 맞춤 '11월'(상단 크기 맞춤) + 오른쪽 라인 맞춤 '+ 일정 추가하기'
    col_top_left, col_top_right = st.columns([2.15, 1.0], gap="large")

    with col_top_left:
        st.markdown(
            _html(f"""
            <div class="tds-top-status-row">
                <div class="tds-stat-card">
                    <div class="tds-stat-top"><span class="tds-stat-dot blue"></span>오늘·선택일 일정</div>
                    <div class="tds-stat-val">일정 <span class="emph-blue">{counts['day_schedules']}건</span></div>
                </div>
                <div class="tds-stat-card">
                    <div class="tds-stat-top"><span class="tds-stat-dot amber"></span>백그라운드 진행</div>
                    <div class="tds-stat-val">AI작업중 <span class="emph-amber">{counts['working']}건</span></div>
                </div>
                <div class="tds-stat-card">
                    <div class="tds-stat-top"><span class="tds-stat-dot green"></span>카톡 발송 승인대기</div>
                    <div class="tds-stat-val">작업완료, 승인요청 <span class="emph-green">{counts['approval_req']}건</span></div>
                </div>
            </div>
            """),
            unsafe_allow_html=True,
        )

    with col_top_right:
        c_m_left, c_m_right = st.columns([1.15, 1.0], gap="small")
        with c_m_left:
            st.markdown(
                _html(f"""
                <div class="tds-month-heading-box">
                    <span class="tds-month-big-text">{month}월</span>
                    <span class="tds-month-year-pill">{year}년</span>
                </div>
                """),
                unsafe_allow_html=True,
            )
        with c_m_right:
            with st.container(key="cal_add_btn_wrap"):
                if st.button("＋ 일정 추가하기", type="primary", key="btn_cal_open_add_schedule"):
                    cstate["show_add_modal"] = not cstate.get("show_add_modal", False)
                    st.rerun()

    # 일정 추가 입력 폼 (버튼 클릭 시 깔끔한 카드로 열림)
    if cstate.get("show_add_modal"):
        with st.container(border=True):
            st.markdown(f"##### ➕ {year}년 {month}월 새 세무 일정 · 카톡 자동화 작업 등록")
            f_c1, f_c2, f_c3, f_c4 = st.columns([0.9, 1.0, 1.4, 1.4])
            max_day = calendar.monthrange(year, month)[1]
            with f_c1:
                in_day = st.number_input("날짜(일)", min_value=1, max_value=max_day, value=min(selected_day, max_day), step=1, key="add_sch_day")
            with f_c2:
                in_time = st.text_input("시간", value="14:00", placeholder="예: 14:00", key="add_sch_time")
            with f_c3:
                in_client = st.text_input("거래처명", placeholder="예: (주)세무테크", key="add_sch_client")
            with f_c4:
                in_status = st.selectbox(
                    "백그라운드 진행 상태",
                    options=["작업 완료, 승인요청중", "백그라운드 작업중", "사용자 승인완료"],
                    key="add_sch_status",
                )
            in_title = st.text_input("일정 제목 (카톡 작업명)", placeholder="예: (주)세무테크 부가세 예정고지 세액 검토 카톡 발송", key="add_sch_title")
            in_desc = st.text_input("상세 내용 (카톡 안내 초안 요약)", placeholder="예: 홈택스 조회 완료 및 대표님 카톡 안내문 생성", key="add_sch_desc")

            b_c1, b_c2 = st.columns([1, 1])
            with b_c1:
                if st.button("저장 및 카톡 To-Do 연동", type="primary", width="stretch", key="btn_save_new_sch"):
                    if in_title.strip():
                        d_int = int(in_day)
                        new_id = f"sch_{year}_{month}_{d_int}_{len(month_schedules.get(d_int, [])) + 1}"
                        cl_nm = in_client.strip() or "거래처"
                        month_schedules.setdefault(d_int, []).append({
                            "id": new_id,
                            "time": in_time.strip() or "10:00",
                            "title": in_title.strip(),
                            "client": cl_nm,
                            "category": "세무·카톡",
                            "ai_status": in_status,
                            "done": (in_status == "사용자 승인완료"),
                            "desc": in_desc.strip() or f"{cl_nm} 맞춤 카톡 안내 및 검토 작업",
                        })
                        cstate["kakao_todos"].insert(0, {
                            "id": f"ktodo_{len(cstate['kakao_todos']) + 1}",
                            "client": cl_nm,
                            "recipient": "범준",
                            "title": in_title.strip(),
                            "bubble_msg": f"범준님 {cl_nm}에 보낼 '{in_title.strip()}' 준비가 완료되었습니다",
                            "status": in_status,
                            "category": "신규 등록 작업",
                            "time_ago": "방금 등록",
                            "checked": (in_status != "백그라운드 작업중"),
                            "preview": in_desc.strip() or f"안녕하세요 {cl_nm} 대표님, 요청하신 '{in_title.strip()}' 검토 결과를 안내드립니다.",
                            "attachment": f"{cl_nm}_{year}{month:02d}{d_int:02d}_검토자료.pdf",
                        })
                        cstate["selected_day"] = d_int
                        cstate["show_add_modal"] = False
                        cstate["bubble_visible"] = True
                        cstate["bubble_idx"] = 0
                        st.rerun()
            with b_c2:
                if st.button("닫기", width="stretch", key="btn_cancel_new_sch"):
                    cstate["show_add_modal"] = False
                    st.rerun()

    # 3. 메인 본문: 좌측 30% 반투명 달력 그리드 (2.15) + 우측 선택한 날짜의 할 일 (1.0)
    col_cal, col_side = st.columns([2.15, 1.0], gap="large")

    with col_cal:
        with st.container(key="cal_glass_surface"):
            # 요일 헤더 (일~토)
            dow_html = "".join(
                f"<div class='tds-cal-dow-cell {'sun' if i == 0 else ('sat' if i == 6 else '')}'>{d_lbl.strip()}</div>"
                for i, d_lbl in enumerate(_SUN_FIRST_HEADERS)
            )
            st.markdown(f"<div class='tds-cal-dow-grid'>{dow_html}</div>", unsafe_allow_html=True)

            cal_obj = calendar.Calendar(firstweekday=6)  # 일요일 시작
            weeks = cal_obj.monthdayscalendar(year, month)

            for w_idx, week in enumerate(weeks):
                w_cols = st.columns(7, gap="small")
                for d_idx, day_num in enumerate(week):
                    with w_cols[d_idx]:
                        if day_num == 0:
                            st.markdown("<div class='tds-cal-day-card empty'></div>", unsafe_allow_html=True)
                        else:
                            is_sel = (day_num == selected_day)
                            is_today = (year == today_d.year and month == today_d.month and day_num == today_d.day)
                            dow_cls = "sun" if d_idx == 0 else ("sat" if d_idx == 6 else "")
                            today_badge = "<span class='tds-cal-today-badge'>오늘</span>" if is_today else ""

                            evs = month_schedules.get(day_num, [])
                            pills_html = ""
                            for ev in evs[:2]:
                                p_cls = _ev_pill_cls(ev.get("ai_status", ""))
                                pills_html += f"<div class='tds-cal-ev-pill {p_cls}'>{_html_lib.escape(str(ev.get('title', '')))}</div>"
                            if len(evs) > 2:
                                pills_html += f"<div class='tds-cal-ev-pill blue'>+{len(evs) - 2}건 더보기</div>"

                            st.markdown(
                                _html(f"""
                                <div class="tds-cal-day-card {'selected' if is_sel else ''}">
                                    <div class="tds-cal-day-top">
                                        <span class="tds-cal-day-num {dow_cls}">{day_num}</span>
                                        {today_badge}
                                    </div>
                                    <div class="tds-cal-ev-list">{pills_html}</div>
                                </div>
                                """),
                                unsafe_allow_html=True,
                            )
                            btn_lbl = f"{day_num}일 선택됨" if is_sel else f"{day_num}일 ({len(evs)}건)"
                            if st.button(
                                btn_lbl,
                                key=f"cal_sel_d_{year}_{month}_{day_num}",
                                type="primary" if is_sel else "secondary",
                                width="stretch",
                            ):
                                cstate["selected_day"] = day_num
                                st.rerun()

    with col_side:
        # 선택한 날짜의 할 일 카드
        sel_date_obj = date(year, month, min(selected_day, calendar.monthrange(year, month)[1]))
        sel_wd = _WEEKDAYS_SHORT[sel_date_obj.weekday()]
        day_evs = month_schedules.get(selected_day, [])

        with st.container(key="cal_right_todo_card"):
            st.markdown(
                _html(f"""
                <div class="tds-side-hdr">
                    <div class="tds-side-title">선택한 날짜의 할 일 · {month}월 {selected_day}일 ({sel_wd})</div>
                    <span class="tds-side-badge">{len(day_evs)}건</span>
                </div>
                """),
                unsafe_allow_html=True,
            )

            if not day_evs:
                st.caption("선택한 날짜에 등록된 세무 일정이 없습니다. 상단 [＋ 일정 추가하기] 버튼으로 일정을 추가해 보세요.")
            else:
                for idx_e, ev in enumerate(list(day_evs)):
                    st_str = ev.get("ai_status", "작업 완료, 승인요청중")
                    p_cls = _status_pill_cls(st_str)
                    st.markdown(
                        _html(f"""
                        <div class="tds-todo-item-box">
                            <div class="tds-todo-item-top">
                                <span class="tds-todo-time">{_html_lib.escape(str(ev.get('time', '10:00')))} · {_html_lib.escape(str(ev.get('client', '거래처')))}</span>
                                <span class="tds-status-pill {p_cls}">{st_str}</span>
                            </div>
                            <div class="tds-todo-title">{_html_lib.escape(str(ev.get('title', '')))}</div>
                            <div class="tds-todo-desc">{_html_lib.escape(str(ev.get('desc', '')))}</div>
                        </div>
                        """),
                        unsafe_allow_html=True,
                    )
                    act_c1, act_c2 = st.columns([1.4, 1.0])
                    with act_c1:
                        if st_str == "작업 완료, 승인요청중":
                            if st.button("카톡 초안 확인·승인", key=f"btn_day_approve_{ev['id']}", type="primary", width="stretch"):
                                ev["ai_status"] = "사용자 승인완료"
                                ev["done"] = True
                                cstate["panel_open"] = True
                                st.rerun()
                        elif st_str == "백그라운드 작업중":
                            if st.button("진행 현황 열기 (60% 창)", key=f"btn_day_open_{ev['id']}", width="stretch"):
                                cstate["panel_open"] = True
                                st.rerun()
                        else:
                            st.caption("✓ 사용자 승인 및 발송 완료")
                    with act_c2:
                        if st.button("일정 삭제", key=f"btn_day_del_{ev['id']}", width="stretch"):
                            month_schedules[selected_day] = [x for x in day_evs if x.get("id") != ev.get("id")]
                            st.rerun()

        # 우측 하단 카드 2: 카카오톡 백그라운드 작업 요약 및 빠른 제어
        with st.container(key="cal_right_kakao_card"):
            st.markdown(
                _html(f"""
                <div class="tds-side-hdr">
                    <div class="tds-side-title">카카오톡 백그라운드 자동화 큐</div>
                    <span class="tds-side-badge">승인요청 {counts['approval_req']}건</span>
                </div>
                """),
                unsafe_allow_html=True,
            )
            st.caption("우측 하단 파란색 미소 홈버튼(또는 네모 말풍선)을 클릭하면 화면의 60% 크기로 전체 체크 To-Do 리스트가 애니메이션과 함께 펼쳐집니다.")
            q_c1, q_c2 = st.columns(2)
            with q_c1:
                if st.button(
                    "60% 확장 To-Do 패널 열기" if not cstate.get("panel_open") else "60% 확장 To-Do 패널 닫기",
                    type="primary" if not cstate.get("panel_open") else "secondary",
                    width="stretch",
                    key="btn_main_toggle_60_panel",
                ):
                    cstate["panel_open"] = not cstate.get("panel_open", False)
                    st.rerun()
            with q_c2:
                if st.button("승인대기 전체 일괄 승인", width="stretch", key="btn_main_approve_all"):
                    for td in cstate.get("kakao_todos", []):
                        if td.get("status") == "작업 완료, 승인요청중":
                            td["status"] = "사용자 승인완료"
                            td["checked"] = True
                            td["time_ago"] = "방금 승인완료"
                    for d_list in month_schedules.values():
                        for ev in d_list:
                            if ev.get("ai_status") == "작업 완료, 승인요청중":
                                ev["ai_status"] = "사용자 승인완료"
                                ev["done"] = True
                    st.rerun()

    # 4. 우측 하단 플로팅 홈버튼 + 네모 말풍선 + 60% 애니메이션 확장 To-Do 오버레이 렌더링
    render_floating_kakao_todo_overlay()


def render_floating_kakao_todo_overlay() -> None:
    """
    우측 하단 고정 플로팅 홈버튼(파란 네모 + 확대한 동그라미 미소 얼굴, 귀·머리카락 없음) +
    네모 말풍선 알림창 + 클릭 시 우측 하단 모서리부터 60% 크기로 커지는 애니메이션 To-Do 오버레이.
    window.parent.document에 직접 마운트하여 기존 작업 공간 위에 자연스럽게 동작합니다.
    """
    cstate = _init_calendar_state()
    todos = cstate.get("kakao_todos", [])
    counts = _get_status_counts(cstate)
    panel_open_init = bool(cstate.get("panel_open", False))

    # 말풍선에 띄울 대표 알림 문구 2건 (요청사항 원문 그대로 반영)
    bubble_messages = [
        "범준님 (주)모 회사에 보낼 세법 검토 카톡이 완성되었습니다",
        "범준님 (주)갑 회사로부터 요청받은 서류를 다운받아 보낼 준비가 끝났습니다",
    ]
    for t in todos:
        b_m = t.get("bubble_msg", "")
        if b_m and b_m not in bubble_messages:
            bubble_messages.append(b_m)

    todos_json = json.dumps(todos, ensure_ascii=False)
    bubbles_json = json.dumps(bubble_messages, ensure_ascii=False)
    init_open_js = "true" if panel_open_init else "false"
    req_badge_cnt = counts["approval_req"]

    components.html(
        f"""
        <script>
        (function() {{
            const parentDoc = window.parent.document;
            const TODOS_DATA = {todos_json};
            const BUBBLE_MSGS = {bubbles_json};
            const INIT_OPEN = {init_open_js};
            const BADGE_CNT = {req_badge_cnt};

            // 스타일 주입
            let styleEl = parentDoc.getElementById("tds-kakao-floating-style");
            if (!styleEl) {{
                styleEl = parentDoc.createElement("style");
                styleEl.id = "tds-kakao-floating-style";
                parentDoc.head.appendChild(styleEl);
            }}
            styleEl.textContent = `
                #tds-kakao-floating-root {{
                    position: fixed;
                    right: 28px;
                    bottom: 26px;
                    z-index: 999990;
                    font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                    user-select: none;
                }}
                /* 배경 반투명 딤(뒤에 기존 작업 공간이 켜진 상태로 보이도록 18%만 부드럽게 처리) */
                #tds-kakao-backdrop {{
                    position: fixed;
                    inset: 0;
                    background: rgba(15, 23, 42, 0.16);
                    backdrop-filter: blur(2px);
                    opacity: 0;
                    pointer-events: none;
                    transition: opacity 0.28s cubic-bezier(0.16, 1, 0.3, 1);
                    z-index: 999988;
                }}
                #tds-kakao-backdrop.open {{
                    opacity: 1;
                    pointer-events: auto;
                }}
                /* 우측 하단 모서리부터 화면의 60% 정도를 차지하며 애니메이션으로 커지는 체크 To-Do 패널 */
                #tds-kakao-todo-panel {{
                    position: fixed;
                    right: 28px;
                    bottom: 104px;
                    width: min(60vw, 920px);
                    min-width: min(92vw, 480px);
                    height: min(74vh, 700px);
                    background: #FFFFFF;
                    border: 1px solid #E5E8EB;
                    border-radius: 22px;
                    box-shadow: 0 24px 60px rgba(15, 23, 42, 0.20), 0 4px 16px rgba(49, 130, 246, 0.10);
                    transform-origin: bottom right;
                    transform: scale(0.08) translateY(40px);
                    opacity: 0;
                    pointer-events: none;
                    transition: transform 0.36s cubic-bezier(0.16, 1, 0.3, 1), opacity 0.26s ease;
                    z-index: 999995;
                    display: flex;
                    flex-direction: column;
                    overflow: hidden;
                }}
                #tds-kakao-todo-panel.open {{
                    transform: scale(1) translateY(0);
                    opacity: 1;
                    pointer-events: auto;
                }}
                .tds-kp-header {{
                    padding: 20px 24px 14px;
                    border-bottom: 1px solid #E5E8EB;
                    background: #FFFFFF;
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                }}
                .tds-kp-title-wrap {{
                    display: flex;
                    align-items: center;
                    gap: 10px;
                }}
                .tds-kp-title {{
                    font-size: 1.18rem;
                    font-weight: 800;
                    color: #191F28;
                    letter-spacing: -0.4px;
                }}
                .tds-kp-sub {{
                    font-size: 0.82rem;
                    color: #4E5968;
                    margin-top: 3px;
                }}
                .tds-kp-close-btn {{
                    background: #F2F4F6;
                    border: none;
                    border-radius: 10px;
                    padding: 7px 13px;
                    font-size: 0.82rem;
                    font-weight: 700;
                    color: #4E5968;
                    cursor: pointer;
                }}
                .tds-kp-close-btn:hover {{
                    background: #E5E8EB;
                    color: #191F28;
                }}
                /* 상태별 필터 탭 */
                .tds-kp-tabs {{
                    display: flex;
                    align-items: center;
                    gap: 8px;
                    padding: 12px 24px;
                    background: #F9FAFB;
                    border-bottom: 1px solid #E5E8EB;
                    flex-wrap: wrap;
                }}
                .tds-kp-tab {{
                    padding: 6px 14px;
                    border-radius: 999px;
                    font-size: 0.80rem;
                    font-weight: 700;
                    border: 1px solid #E5E8EB;
                    background: #FFFFFF;
                    color: #4E5968;
                    cursor: pointer;
                    transition: all 0.15s ease;
                }}
                .tds-kp-tab.active {{
                    background: #3182F6;
                    border-color: #3182F6;
                    color: #FFFFFF;
                }}
                /* 체크 To-Do 리스트 본문 */
                .tds-kp-body {{
                    flex: 1;
                    overflow-y: auto;
                    padding: 16px 24px 20px;
                    background: #F4F6FA;
                    display: flex;
                    flex-direction: column;
                    gap: 12px;
                }}
                .tds-kp-item {{
                    background: #FFFFFF;
                    border: 1px solid #E5E8EB;
                    border-radius: 16px;
                    padding: 15px 18px;
                    box-shadow: 0 2px 6px rgba(15, 23, 42, 0.03);
                    transition: border-color 0.15s ease;
                }}
                .tds-kp-item:hover {{
                    border-color: #3182F6;
                }}
                .tds-kp-item-top {{
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    gap: 10px;
                    margin-bottom: 8px;
                }}
                .tds-kp-chk-label {{
                    display: flex;
                    align-items: center;
                    gap: 10px;
                    font-size: 0.96rem;
                    font-weight: 800;
                    color: #191F28;
                    cursor: pointer;
                }}
                .tds-kp-chk-label input[type="checkbox"] {{
                    width: 18px;
                    height: 18px;
                    accent-color: #3182F6;
                    cursor: pointer;
                }}
                .tds-kp-badge {{
                    font-size: 0.74rem;
                    font-weight: 800;
                    padding: 4px 10px;
                    border-radius: 999px;
                    white-space: nowrap;
                }}
                .tds-kp-badge.working {{ background: #FFF5E5; color: #D97706; }}
                .tds-kp-badge.req {{ background: #E8F3FF; color: #3182F6; }}
                .tds-kp-badge.done {{ background: #E5F9F0; color: #00A660; }}
                .tds-kp-preview {{
                    background: #F9FAFB;
                    border: 1px solid #EEF1F6;
                    border-radius: 10px;
                    padding: 10px 13px;
                    font-size: 0.82rem;
                    color: #334155;
                    line-height: 1.5;
                    white-space: pre-line;
                    margin-bottom: 10px;
                }}
                .tds-kp-foot {{
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    gap: 10px;
                    flex-wrap: wrap;
                }}
                .tds-kp-att {{
                    font-size: 0.76rem;
                    font-weight: 600;
                    color: #64748B;
                }}
                .tds-kp-act-btn {{
                    background: #3182F6;
                    color: #FFFFFF;
                    border: none;
                    border-radius: 9px;
                    padding: 7px 14px;
                    font-size: 0.80rem;
                    font-weight: 700;
                    cursor: pointer;
                }}
                .tds-kp-act-btn:hover {{
                    background: #1B64DA;
                }}
                .tds-kp-act-btn.done {{
                    background: #E5F9F0;
                    color: #00A660;
                    cursor: default;
                }}

                /* ═════════ 네모 말풍선 알림창 (border-radius: 6px 직각 네모 말풍선) ═════════ */
                #tds-kakao-square-bubble {{
                    position: fixed;
                    right: 104px;
                    bottom: 32px;
                    max-width: 410px;
                    background: #FFFFFF;
                    border: 1.5px solid #3182F6;
                    border-radius: 6px;
                    padding: 12px 16px;
                    box-shadow: 0 10px 28px rgba(15, 23, 42, 0.14);
                    z-index: 999992;
                    cursor: pointer;
                    transition: transform 0.2s ease, opacity 0.2s ease;
                }}
                #tds-kakao-square-bubble:hover {{
                    transform: translateY(-2px);
                }}
                #tds-kakao-square-bubble.hidden {{
                    opacity: 0;
                    pointer-events: none;
                    transform: translateX(10px);
                }}
                /* 네모 말풍선 우측 꼬리 */
                #tds-kakao-square-bubble::after {{
                    content: "";
                    position: absolute;
                    right: -8px;
                    bottom: 18px;
                    width: 12px;
                    height: 12px;
                    background: #FFFFFF;
                    border-top: 1.5px solid #3182F6;
                    border-right: 1.5px solid #3182F6;
                    transform: rotate(45deg);
                }}
                .tds-bubble-tag {{
                    display: inline-flex;
                    align-items: center;
                    gap: 5px;
                    font-size: 0.70rem;
                    font-weight: 800;
                    color: #3182F6;
                    margin-bottom: 3px;
                }}
                .tds-bubble-text {{
                    font-size: 0.85rem;
                    font-weight: 700;
                    color: #191F28;
                    line-height: 1.38;
                    word-break: keep-all;
                }}

                /* ═════════ 우측 하단 파란 네모 홈버튼 (확대된 동그라미 귀여운 미소 얼굴, 귀·머리카락 제거) ═════════ */
                #tds-kakao-home-fab {{
                    width: 64px;
                    height: 64px;
                    border-radius: 20px;
                    background: #3898FF;
                    border: none;
                    box-shadow: 0 10px 24px rgba(49, 130, 246, 0.38), inset 0 1px 1px rgba(255, 255, 255, 0.35);
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    cursor: pointer;
                    position: relative;
                    transition: transform 0.22s cubic-bezier(0.16, 1, 0.3, 1), background 0.18s ease;
                }}
                #tds-kakao-home-fab:hover {{
                    transform: scale(1.06);
                    background: #3182F6;
                }}
                #tds-kakao-home-fab:active {{
                    transform: scale(0.96);
                }}
                #tds-kakao-fab-badge {{
                    position: absolute;
                    top: -5px;
                    right: -5px;
                    min-width: 22px;
                    height: 22px;
                    padding: 0 6px;
                    border-radius: 999px;
                    background: #F04452;
                    color: #FFFFFF;
                    font-size: 0.74rem;
                    font-weight: 800;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    border: 2px solid #FFFFFF;
                    box-shadow: 0 2px 6px rgba(240, 68, 82, 0.4);
                }}
            `;

            // 루트 컨테이너 준비
            let rootEl = parentDoc.getElementById("tds-kakao-floating-root");
            if (!rootEl) {{
                rootEl = parentDoc.createElement("div");
                rootEl.id = "tds-kakao-floating-root";
                parentDoc.body.appendChild(rootEl);
            }}

            // 귀·머리카락을 완전히 제거하고 크기를 키운 동그라미 미소 캐릭터 SVG (44x44)
            const SMILE_FACE_SVG = `
                <svg width="44" height="44" viewBox="0 0 44 44" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <circle cx="22" cy="22" r="18.5" fill="#FFFFFF"/>
                    <circle cx="15.8" cy="19.5" r="2.2" fill="#191F28"/>
                    <circle cx="28.2" cy="19.5" r="2.2" fill="#191F28"/>
                    <ellipse cx="11.8" cy="23.2" rx="2.3" ry="1.3" fill="#FF8A9E" fill-opacity="0.55"/>
                    <ellipse cx="32.2" cy="23.2" rx="2.3" ry="1.3" fill="#FF8A9E" fill-opacity="0.55"/>
                    <path d="M15.5 25.0C17.2 28.2 26.8 28.2 28.5 25.0" stroke="#191F28" stroke-width="2.4" stroke-linecap="round"/>
                </svg>
            `;

            // 열림 상태일 때의 하단 화살표 (∨) SVG
            const CHEVRON_DOWN_SVG = `
                <svg width="32" height="32" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path d="M6 9L12 15L18 9" stroke="#FFFFFF" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
            `;

            if (!window.parent._tdsKakaoState) {{
                window.parent._tdsKakaoState = {{
                    open: INIT_OPEN,
                    filter: "전체",
                    bubbleIdx: 0,
                    todos: TODOS_DATA
                }};
            }} else {{
                window.parent._tdsKakaoState.todos = TODOS_DATA;
                if (INIT_OPEN !== window.parent._tdsKakaoState._lastServerOpen) {{
                    window.parent._tdsKakaoState.open = INIT_OPEN;
                    window.parent._tdsKakaoState._lastServerOpen = INIT_OPEN;
                }}
            }}

            function escHtml(v) {{
                return String(v == null ? "" : v)
                    .replace(/&/g, "&amp;")
                    .replace(/</g, "&lt;")
                    .replace(/>/g, "&gt;")
                    .replace(/"/g, "&quot;")
                    .replace(/'/g, "&#39;");
            }}

            function getBadgeClass(st) {{
                const s = String(st || "");
                if (s.indexOf("작업중") >= 0) return "working";
                if (s.indexOf("승인요청") >= 0) return "req";
                return "done";
            }}

            function renderOverlay() {{
                const stObj = window.parent._tdsKakaoState;
                const allTodos = stObj.todos || [];
                const reqCnt = allTodos.filter(t => t.status === "작업 완료, 승인요청중").length;
                const workCnt = allTodos.filter(t => t.status === "백그라운드 작업중").length;
                const doneCnt = allTodos.filter(t => t.status === "사용자 승인완료").length;

                const filtered = allTodos.filter(t => {{
                    if (stObj.filter === "전체") return true;
                    return t.status === stObj.filter;
                }});

                const itemsHtml = filtered.map((item, idx) => {{
                    const bCls = getBadgeClass(item.status);
                    const isReq = item.status === "작업 완료, 승인요청중";
                    const isDone = item.status === "사용자 승인완료";
                    const btnHtml = isReq
                        ? `<button class="tds-kp-act-btn" data-approve-id="${{item.id}}">승인 및 카톡 발송</button>`
                        : (isDone
                            ? `<button class="tds-kp-act-btn done">✓ 사용자 승인완료</button>`
                            : `<button class="tds-kp-act-btn" style="background:#D97706;">백그라운드 생성중...</button>`);
                    return `
                        <div class="tds-kp-item">
                            <div class="tds-kp-item-top">
                                <label class="tds-kp-chk-label">
                                    <input type="checkbox" data-chk-id="${{escHtml(item.id)}}" ${{item.checked ? "checked" : ""}} />
                                    <span>[${{escHtml(item.client)}}] ${{escHtml(item.title)}}</span>
                                </label>
                                <span class="tds-kp-badge ${{bCls}}">${{escHtml(item.status)}} · ${{escHtml(item.time_ago)}}</span>
                            </div>
                            <div class="tds-kp-preview">${{escHtml(item.preview)}}</div>
                            <div class="tds-kp-foot">
                                <span class="tds-kp-att">첨부 준비 파일: ${{escHtml(item.attachment)}}</span>
                                ${{btnHtml}}
                            </div>
                        </div>
                    `;
                }}).join("");

                const curBubbleMsg = BUBBLE_MSGS[stObj.bubbleIdx % BUBBLE_MSGS.length] || BUBBLE_MSGS[0];

                rootEl.innerHTML = `
                    <div id="tds-kakao-backdrop" class="${{stObj.open ? 'open' : ''}}"></div>
                    <div id="tds-kakao-todo-panel" class="${{stObj.open ? 'open' : ''}}">
                        <div class="tds-kp-header">
                            <div>
                                <div class="tds-kp-title">카카오톡 백그라운드 자동화 To-Do 체크리스트</div>
                                <div class="tds-kp-sub">뒤쪽 기존 작업 화면을 유지한 채 백그라운드 작업 현황을 확인하고 카톡 발송을 승인합니다.</div>
                            </div>
                            <button class="tds-kp-close-btn" id="tds-kp-close">닫기 ✕</button>
                        </div>
                        <div class="tds-kp-tabs">
                            <button class="tds-kp-tab ${{stObj.filter === '전체' ? 'active' : ''}}" data-tab="전체">전체 (${{allTodos.length}})</button>
                            <button class="tds-kp-tab ${{stObj.filter === '백그라운드 작업중' ? 'active' : ''}}" data-tab="백그라운드 작업중">백그라운드 작업중 (${{workCnt}})</button>
                            <button class="tds-kp-tab ${{stObj.filter === '작업 완료, 승인요청중' ? 'active' : ''}}" data-tab="작업 완료, 승인요청중">작업 완료, 승인요청중 (${{reqCnt}})</button>
                            <button class="tds-kp-tab ${{stObj.filter === '사용자 승인완료' ? 'active' : ''}}" data-tab="사용자 승인완료">사용자 승인완료 (${{doneCnt}})</button>
                        </div>
                        <div class="tds-kp-body">
                            ${{itemsHtml}}
                        </div>
                    </div>

                    <div id="tds-kakao-square-bubble" class="${{stObj.open ? 'hidden' : ''}}" title="클릭하면 60% 카톡 To-Do 체크리스트가 열립니다">
                        <div class="tds-bubble-tag">● 카톡 백그라운드 작업 완료 알림 (클릭하여 열기)</div>
                        <div class="tds-bubble-text">"${{escHtml(curBubbleMsg)}}"</div>
                    </div>

                    <button id="tds-kakao-home-fab" title="카카오톡 백그라운드 To-Do 열기/닫기">
                        ${{stObj.open ? CHEVRON_DOWN_SVG : SMILE_FACE_SVG}}
                        ${{reqCnt > 0 ? `<span id="tds-kakao-fab-badge">${{reqCnt}}</span>` : ''}}
                    </button>
                `;

                // 이벤트 바인딩
                const fabBtn = parentDoc.getElementById("tds-kakao-home-fab");
                const bubbleEl = parentDoc.getElementById("tds-kakao-square-bubble");
                const closeBtn = parentDoc.getElementById("tds-kp-close");
                const backdropEl = parentDoc.getElementById("tds-kakao-backdrop");

                if (fabBtn) {{
                    fabBtn.onclick = function() {{
                        stObj.open = !stObj.open;
                        renderOverlay();
                    }};
                }}
                if (bubbleEl) {{
                    bubbleEl.onclick = function() {{
                        stObj.open = true;
                        renderOverlay();
                    }};
                }}
                if (closeBtn) {{
                    closeBtn.onclick = function() {{
                        stObj.open = false;
                        renderOverlay();
                    }};
                }}
                if (backdropEl) {{
                    backdropEl.onclick = function() {{
                        stObj.open = false;
                        renderOverlay();
                    }};
                }}

                rootEl.querySelectorAll(".tds-kp-tab").forEach(btn => {{
                    btn.onclick = function() {{
                        stObj.filter = this.getAttribute("data-tab") || "전체";
                        renderOverlay();
                    }};
                }});

                rootEl.querySelectorAll("[data-approve-id]").forEach(btn => {{
                    btn.onclick = function() {{
                        const tid = this.getAttribute("data-approve-id");
                        const target = (stObj.todos || []).find(x => x.id === tid);
                        if (target) {{
                            target.status = "사용자 승인완료";
                            target.checked = true;
                            target.time_ago = "방금 승인완료";
                            renderOverlay();
                        }}
                    }};
                }});

                rootEl.querySelectorAll("[data-chk-id]").forEach(chk => {{
                    chk.onchange = function() {{
                        const tid = this.getAttribute("data-chk-id");
                        const target = (stObj.todos || []).find(x => x.id === tid);
                        if (target) {{
                            target.checked = this.checked;
                        }}
                    }};
                }});
            }}

            renderOverlay();

            // 6초마다 네모 말풍선 알림 문구 자동 순환 (패널이 닫혀 있을 때)
            if (window.parent._tdsKakaoTimer) {{
                clearInterval(window.parent._tdsKakaoTimer);
            }}
            window.parent._tdsKakaoTimer = setInterval(function() {{
                const stObj = window.parent._tdsKakaoState;
                if (stObj && !stObj.open) {{
                    stObj.bubbleIdx = (stObj.bubbleIdx + 1) % BUBBLE_MSGS.length;
                    const txtEl = parentDoc.querySelector("#tds-kakao-square-bubble .tds-bubble-text");
                    if (txtEl) {{
                        txtEl.textContent = '"' + BUBBLE_MSGS[stObj.bubbleIdx] + '"';
                    }}
                }}
            }}, 5500);
        }})();
        </script>
        """,
        height=0,
    )
