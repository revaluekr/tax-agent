# -*- coding: utf-8 -*-
"""
달력 스케줄러 + Today To Do (0건 초기화 & Toss Web TDS 규격 100% 일치 렌더링) +
평면(Flat) 기본 / 클릭 시 오목 입체(Sunken) 다중 토글 독(Dock) + 중앙 상세입력 모달 (calendar_scheduler/ui.py)
"""
from __future__ import annotations

import calendar
import html as _html_lib
import json
import re
from datetime import date, datetime
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

import streamlit as st
import streamlit.components.v1 as components

import ui_theme as _ui_theme

_WEEKDAYS_SHORT = ("월", "화", "수", "목", "금", "토", "일")
_WEEKDAYS_FULL = ("월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일")
_SUN_FIRST_HEADERS = ("일", "월", "화", "수", "목", "금", "토")
_STATE_SCHEMA_VERSION = "v10_enter_on_dock_buttons_and_blue_modal"


def _html(s: str) -> str:
    """여러 줄 HTML을 한 줄로 이어 붙여 표시"""
    return " ".join(ln.strip() for ln in str(s).splitlines() if ln.strip())


def get_kst_today() -> date:
    """한국 표준시(KST, Asia/Seoul) 기준 오늘 날짜를 반환합니다."""
    return datetime.now(ZoneInfo("Asia/Seoul")).date()


def get_kst_now_hm() -> str:
    """한국 표준시(KST, Asia/Seoul) 기준 현재 시각(HH:MM) 문자열을 반환합니다."""
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%H:%M")


def _default_schedules_for_month(year: int, month: int, today_d: date) -> Dict[int, List[Dict[str, Any]]]:
    """
    당해 연월의 기본 세무기한 일정을 생성합니다.
    - 오늘자(focus_day) 임의 할 일 리스트는 모두 비워 Today To Do가 0건으로 시작합니다.
    """
    last_day = calendar.monthrange(year, month)[1]

    data: Dict[int, List[Dict[str, Any]]] = {
        10: [
            {
                "id": f"sch_{year}_{month}_10_1",
                "type": "TAX",
                "time": "18:00",
                "title": "원천세 · 지방소득세 신고납부",
                "client": "전체 기장 거래처",
                "category": "세무기한",
                "ai_status": "작업 완료, 승인요청중",
                "done": False,
                "alarm": False,
                "alarm_glow": False,
                "show_on_cal": True,
                "urgent": True,
                "has_detail": True,
                "repeat": "매월 반복",
                "location": "홈택스 / 위택스",
                "link_target": "PAYROLL_EMP",
                "link_label": "[인건비 자동화 > 급여명세서] 바로가기",
                "attachment": "",
                "sub_tasks": [
                    {"title": "원천징수이행상황신고서 마감 검증", "done": True},
                    {"title": "거래처별 납부서 카톡 일괄 안내", "done": False},
                ],
                "desc": "원천징수이행상황신고서 마감 및 거래처별 납부서 카톡 일괄 안내",
            },
            {
                "id": f"sch_{year}_{month}_10_2",
                "type": "TAX",
                "time": "18:00",
                "title": f"4대보험 {max(1, month - 1)}월분 납부기한",
                "client": "전체 기장 거래처",
                "category": "세무기한",
                "ai_status": "작업 완료, 승인요청중",
                "done": False,
                "alarm": False,
                "alarm_glow": False,
                "show_on_cal": True,
                "urgent": False,
                "has_detail": False,
                "repeat": "매월 반복",
                "location": "",
                "link_target": "CALENDAR",
                "link_label": "",
                "attachment": "",
                "sub_tasks": [],
                "desc": "국민연금·건강보험·고용·산재보험 당월 고지분 납부 마감",
            },
        ],
        25: [
            {
                "id": f"sch_{year}_{month}_25_1",
                "type": "TAX",
                "time": "18:00",
                "title": "개별소비세 · 증권거래세 신고",
                "client": "해당 법인 거래처",
                "category": "세무기한",
                "ai_status": "작업 완료, 승인요청중",
                "done": False,
                "alarm": False,
                "alarm_glow": False,
                "show_on_cal": True,
                "urgent": False,
                "has_detail": False,
                "repeat": "매월 반복",
                "location": "",
                "link_target": "CALENDAR",
                "link_label": "",
                "attachment": "",
                "sub_tasks": [],
                "desc": "당월분 개별소비세 및 증권거래세 정기 신고·납부 기한",
            },
        ],
        last_day: [
            {
                "id": f"sch_{year}_{month}_{last_day}_1",
                "type": "TAX",
                "time": "18:00",
                "title": "종합소득세 중간예납 납부기한",
                "client": "개인사업자 거래처",
                "category": "세무기한",
                "ai_status": "작업 완료, 승인요청중",
                "done": False,
                "alarm": False,
                "alarm_glow": False,
                "show_on_cal": True,
                "urgent": True,
                "has_detail": False,
                "repeat": "반복 안함",
                "location": "",
                "link_target": "CALENDAR",
                "link_label": "",
                "attachment": "",
                "sub_tasks": [],
                "desc": "종합소득세 중간예납 고지세액 납부 안내 및 추계신고 대상 점검",
            },
            {
                "id": f"sch_{year}_{month}_{last_day}_2",
                "type": "TAX",
                "time": "18:00",
                "title": "일용근로·간이지급명세서 제출",
                "client": "인건비 신고 거래처",
                "category": "세무기한",
                "ai_status": "작업 완료, 승인요청중",
                "done": False,
                "alarm": False,
                "alarm_glow": False,
                "show_on_cal": True,
                "urgent": False,
                "has_detail": False,
                "repeat": "매월 반복",
                "location": "",
                "link_target": "PAYROLL_BIZ",
                "link_label": "[인건비 자동화 > 사업소득] 바로가기",
                "attachment": "",
                "sub_tasks": [],
                "desc": "일용근로소득 및 거주자 사업소득 간이지급명세서 정기 제출 기한",
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
            "status_code": "READY",
            "status": "작업 완료, 승인요청중",
            "category": "세법 검토 카톡 완성",
            "client": "(주)모",
            "recipient": "범준",
            "time_ago": "방금 전",
            "bubble_msg": "범준님, (주)모 회사에 보낼 세법 검토 카톡이 완성되었습니다",
            "title": "(주)모 — 가족 단기 아르바이트 인건비 필요경비 및 4대보험 검토 답변",
            "kakao_original": "[카톡 수신] 세무사님, 저희 매장에 배우자랑 대학생 아들이 주말마다 일하는데 인건비 신고하면 비용 처리 다 되나요?",
            "ai_result": (
                "안녕하세요 대표님, 문의하신 가족 인건비 기준 안내드립니다.\n"
                "1. [비용 처리] 실제 근무 기록과 급여 계좌이체 증빙이 명확하면 가족이라도 인건비 필요경비 인정이 가능합니다.\n"
                "2. [4대보험] 배우자 및 동거 친족은 고용·산재보험 대상에서 제외되며, 월 60시간 이상 근무 시 국민연금·건강보험만 가입합니다.\n"
                "※ 법령 기준의 원론적 안내이며, 구체적 급여액은 담당자 확인 후 안내드리겠습니다."
            ),
            "preview": (
                "안녕하세요 대표님, 문의하신 가족 인건비 기준 안내드립니다.\n"
                "1. [비용 처리] 실제 근무 기록과 급여 계좌이체 증빙이 명확하면 가족이라도 인건비 필요경비 인정이 가능합니다.\n"
                "2. [4대보험] 배우자 및 동거 친족은 고용·산재보험 대상에서 제외되며, 월 60시간 이상 근무 시 국민연금·건강보험만 가입합니다."
            ),
            "attachment": f"(주)모_{yr}년_가족인건비_및_통합고용세액공제_검토안내.pdf",
            "target_mode": "AGENT",
            "action_label": "카톡 답장 복사 & 승인완료",
            "checked": True,
        },
        {
            "id": "ktodo_2",
            "status_code": "READY",
            "status": "작업 완료, 승인요청중",
            "category": "요청 서류 준비 완료",
            "client": "(주)갑",
            "recipient": "범준",
            "time_ago": "3분 전",
            "bubble_msg": "범준님, (주)갑 회사로부터 요청받은 서류를 다운받아 보낼 준비가 끝났습니다",
            "title": "(주)갑 — 국세완납증명서 및 부가세 과세표준증명원 다운로드·검증 완료",
            "kakao_original": "[카톡 수신] 은행 대출 연장 때문에 국세완납증명서랑 부가세 과세표준증명원 급하게 부탁드려요!",
            "ai_result": (
                "📁 저장 폴더: C:\\tax_automation\\거래처_데이터\\02_(주)갑\\4_발급서류_보관함\\(주)갑_증명서.pdf\n"
                "🛡️ [안전 검증 완료] PDF 사업자번호(214-86-*****) == (주)갑 사업자번호 100% 일치 확인"
            ),
            "preview": (
                "📁 저장 폴더: C:\\tax_automation\\거래처_데이터\\02_(주)갑\\4_발급서류_보관함\\(주)갑_증명서.pdf\n"
                "🛡️ [안전 검증 완료] PDF 사업자번호(214-86-*****) == (주)갑 사업자번호 100% 일치 확인"
            ),
            "attachment": f"(주)갑_국세완납_부가세과세표준증명원_{today_d.strftime('%Y%m%d')}.pdf",
            "target_mode": "CALENDAR",
            "action_label": "서류 파일 복사 & 승인완료",
            "checked": True,
        },
        {
            "id": "ktodo_3",
            "status_code": "READY",
            "status": "작업 완료, 승인요청중",
            "category": "사업소득 자동 입력 완료",
            "client": "(주)한빛디자인",
            "recipient": "범준",
            "time_ago": "8분 전",
            "bubble_msg": "범준님, (주)한빛디자인 카톡 인건비 자료를 사업소득 화면에 자동 작성했습니다",
            "title": "(주)한빛디자인 — 프리랜서 김지훈(150만 원) 사업소득 화면 자동 드래그&드롭 완료",
            "kakao_original": "[카톡 수신] 외주 디자이너 김지훈([RRN Omitted]) 세전 150만 원 이체했습니다. 사업소득 신고 부탁드려요.",
            "ai_result": (
                "✅ 에이전트AI [인건비 자동화 > 사업소득] 화면에 자동 입력 완료\n"
                "• 지급총액: 1,500,000원 / 소득세: 45,000원 / 지방세: 4,500원 / 실지급액: 1,450,500원"
            ),
            "preview": (
                "✅ 에이전트AI [인건비 자동화 > 사업소득] 화면에 자동 입력 완료\n"
                "• 지급총액: 1,500,000원 / 소득세: 45,000원 / 지방세: 4,500원 / 실지급액: 1,450,500원"
            ),
            "attachment": f"(주)한빛디자인_{yr}{mo:02d}_사업소득지급명세서.xlsx",
            "target_mode": "PAYROLL_BIZ",
            "action_label": "사업소득 화면 확인 & 승인완료",
            "checked": True,
        },
        {
            "id": "ktodo_4",
            "status_code": "WORKING",
            "status": "백그라운드 작업중",
            "category": "급여대장 파일 자동 변환중",
            "client": "(주)대성테크",
            "recipient": "범준",
            "time_ago": "진행률 75%",
            "bubble_msg": "범준님, (주)대성테크 급여대장 파일을 폴더에 저장하고 급여명세서로 작성 중입니다",
            "title": f"(주)대성테크 — 카톡 수신 '{mo}월_급여대장_세전자료.xlsx' 폴더 저장 및 급여명세서 입력중",
            "kakao_original": f"[카톡 파일 수신] {mo}월_급여대장_세전자료.xlsx (임직원 8명)",
            "ai_result": "⏳ 지정 폴더 저장 완료 → 에이전트AI 급여명세서 화면에 자동 드래그&드롭 중입니다. (아래 버튼으로 즉시 완료 테스트 가능)",
            "preview": "⏳ 지정 폴더 저장 완료 → 에이전트AI 급여명세서 화면에 자동 드래그&드롭 중입니다.",
            "attachment": f"(주)대성테크_{yr}{mo:02d}_급여대장_세전자료.xlsx",
            "target_mode": "PAYROLL_EMP",
            "action_label": "작업 즉시 완료시키기 (시연)",
            "checked": False,
        },
        {
            "id": "ktodo_5",
            "status_code": "APPROVED",
            "status": "사용자 승인완료",
            "category": "급여명세서 자동작성 완료",
            "client": "(주)성진",
            "recipient": "범준",
            "time_ago": "10:15 승인됨",
            "bubble_msg": "",
            "title": f"(주)성진 — {mo}월 급여대장 엑셀 폴더 저장 및 급여명세서 2명 자동 작성",
            "kakao_original": f"[카톡 파일 수신] (주)성진_{mo}월급여대장.xlsx",
            "ai_result": f"✅ 사용자 승인완료 · 달력({mo}/{today_d.day})에 완료 기록이 저장되었습니다.",
            "preview": f"✅ 사용자 승인완료 · 달력({mo}/{today_d.day})에 완료 기록이 저장되었습니다.",
            "attachment": f"(주)성진_{yr}{mo:02d}_급여명세서_완성본.zip",
            "target_mode": "PAYROLL_EMP",
            "action_label": "승인 완료됨",
            "checked": True,
        },
        {
            "id": "ktodo_6",
            "status_code": "APPROVED",
            "status": "사용자 승인완료",
            "category": "통상적 메시지 자동 닫기",
            "client": "(주)케이물산 외 1곳",
            "recipient": "범준",
            "time_ago": "09:45 자동처리",
            "bubble_msg": "",
            "title": "(주)케이물산 — \"네 세무사님 확인했습니다 감사합니다!\" (답변 없이 숫자 1 자동 소거)",
            "kakao_original": "[카톡 수신] 네 세무사님 확인했습니다 감사합니다!",
            "ai_result": "✅ 답변이 필요 없는 통상적 메시지로 확인되어 백그라운드에서 읽음 처리 후 창을 닫았습니다.",
            "preview": "✅ 답변이 필요 없는 통상적 메시지로 확인되어 백그라운드에서 읽음 처리 후 창을 닫았습니다.",
            "attachment": "자동 읽음 처리 로그 (1 소거 완료)",
            "target_mode": "CALENDAR",
            "action_label": "자동 종결됨",
            "checked": True,
        },
    ]


def _status_pill_cls(ev: Dict[str, Any]) -> tuple[str, str, str]:
    """일정 항목의 (점 색상 클래스, 태그 라벨, 태그 배경 클래스) 반환"""
    ev_type = str(ev.get("type", "")).upper()
    ai_st = str(ev.get("ai_status", ""))
    if ev_type == "TAX" or "기한" in str(ev.get("category", "")):
        return ("red", "세무기한", "red")
    if ev_type == "DONE" or ev.get("done") or "승인완료" in ai_st:
        return ("green", "승인완료", "green")
    return ("blue", "내 스케줄", "blue")


def _ev_pill_cls(ev: Dict[str, Any]) -> str:
    """달력 날짜 셀 내부 이벤트 배지 색상 클래스 반환 ('red' | 'green' | 'blue')"""
    dot_cls, _, _ = _status_pill_cls(ev)
    return dot_cls


def _normalize_time_str(raw_t: str) -> str:
    """사용자 입력 시간 문자열(예: '1430', '4:30', '04:30', '')을 숫자 전용 'HH:MM' 또는 ''로 정규화"""
    s = str(raw_t or "").strip()
    if not s or s in ("일정", "기한", ":"):
        return ""
    if ":" in s:
        parts = s.split(":", 1)
        h_digits = "".join(ch for ch in parts[0] if ch.isdigit())[:2]
        m_digits = "".join(ch for ch in parts[1] if ch.isdigit())[:2]
        if not h_digits and not m_digits:
            return ""
        hh = min(23, max(0, int(h_digits))) if h_digits else 0
        mm = min(59, max(0, int(m_digits))) if m_digits else 0
        return f"{hh:02d}:{mm:02d}"
    digits = "".join(ch for ch in s if ch.isdigit())
    if not digits:
        return ""
    if len(digits) >= 4:
        hh = min(23, max(0, int(digits[:2])))
        mm = min(59, max(0, int(digits[2:4])))
        return f"{hh:02d}:{mm:02d}"
    if len(digits) == 3:
        hh = min(23, max(0, int(digits[:1])))
        mm = min(59, max(0, int(digits[1:3])))
        return f"{hh:02d}:{mm:02d}"
    hh = min(23, max(0, int(digits)))
    return f"{hh:02d}:00"


def _sort_day_events(evs: List[Dict[str, Any]], urgent_first: bool = False) -> List[Dict[str, Any]]:
    """시간이 적힌 스케줄은 상단에 시간대별로 우선 나열, 시간 미지정 할 일은 하단 배치"""
    def _sort_key(item: Dict[str, Any]):
        t_norm = _normalize_time_str(str(item.get("time", "")))
        has_time = 0 if t_norm else 1
        urg_rank = (0 if item.get("urgent") else 1) if urgent_first else 0
        return (urg_rank, has_time, t_norm if t_norm else "99:99", str(item.get("id", "")))

    return sorted(evs, key=_sort_key)


def _is_alarm_due(ev: Dict[str, Any], is_today_selected: bool = True) -> bool:
    """
    종 반짝임(노랑-주황-빨강) 작동 조건 (오늘 KST 시간 기준):
    - 반드시 [알림]이 켜져 있고(alarm=True), 완료되지 않았으며,
    - 시간이 입력되어 있고 오늘 현재 시각(KST)이 해당 시간 이상이거나(정각 도달), 시간이 미지정인 알림일 때 작동
    """
    if not ev.get("alarm") or ev.get("done"):
        return False
    if ev.get("alarm_glow"):
        return True
    t_norm = _normalize_time_str(str(ev.get("time", "")))
    if not t_norm:
        return True
    now_hm = get_kst_now_hm()
    return now_hm >= t_norm


def _parse_dock_raw_payload(raw_val: str) -> tuple[str, bool | None, bool | None, str | None, str]:
    """
    JS에서 전달한 인코딩 문자열을 파싱하여
    (순수 제목, 알림 토글 여부, 달력 토글 여부, 시간 문자열, 액션 모드['ENTER' | 'DETAIL' | 'NONE'])를 반환합니다.
    """
    s = str(raw_val or "").strip()

    m_enter = re.search(r"__ENTER_COMMIT_TGL_A([01])_C([01])(?:_T([0-9:]*))?__$", s)
    if m_enter:
        clean_title = s[: m_enter.start()].strip()
        a_on = (m_enter.group(1) == "1")
        c_on = (m_enter.group(2) == "1")
        t_str = (m_enter.group(3) or "").strip()
        return clean_title, a_on, c_on, t_str, "ENTER"

    m_dtl = re.search(r"__DTL_OPEN_TGL_A([01])_C([01])(?:_T([0-9:]*))?__$", s)
    if m_dtl:
        clean_title = s[: m_dtl.start()].strip()
        a_on = (m_dtl.group(1) == "1")
        c_on = (m_dtl.group(2) == "1")
        t_str = (m_dtl.group(3) or "").strip()
        return clean_title, a_on, c_on, t_str, "DETAIL"

    m_draft = re.search(r"__TGL_A([01])_C([01])(?:_T([0-9:]*))?__$", s)
    if m_draft:
        clean_title = s[: m_draft.start()].strip()
        a_on = (m_draft.group(1) == "1")
        c_on = (m_draft.group(2) == "1")
        t_str = (m_draft.group(3) or "").strip()
        return clean_title, a_on, c_on, t_str, "NONE"

    return s, None, None, None, "NONE"


def _shift_calendar_month(cstate: Dict[str, Any], delta: int) -> None:
    """◀ / ▶ 화살표 클릭 시 이전 달 또는 다음 달로 연·월 이동"""
    cur_y = int(cstate.get("year", get_kst_today().year))
    cur_m = int(cstate.get("month", get_kst_today().month))
    new_m = cur_m + delta
    new_y = cur_y
    if new_m < 1:
        new_m = 12
        new_y -= 1
    elif new_m > 12:
        new_m = 1
        new_y += 1
    cstate["year"] = new_y
    cstate["month"] = new_m
    last_d = calendar.monthrange(new_y, new_m)[1]
    cstate["selected_day"] = min(int(cstate.get("selected_day", 1)), last_d)
    st.session_state["cal_sb_year_sel"] = new_y
    st.session_state["cal_sb_month_sel"] = new_m


def _push_kakao_biz_income_to_payroll(company: str, name: str, rrn: str, gross_won: int, is_net: bool = False) -> None:
    """카톡 백그라운드 시뮬레이터(④ 사업소득 문자 수신) → payroll_auto_state['freelancers'] 자동 반영"""
    try:
        from payroll_automated.ui import _get_payroll_state, _recalculate_all_freelancer_rows
        pstate = _get_payroll_state()
        if company and not pstate.get("corp_name"):
            pstate["corp_name"] = company
        ym_digits = str(pstate.get("year_month", "2026-11")).replace("-", "")
        pay_dt_digits = str(pstate.get("pay_date", "2026-11-25")).replace("-", "")
        new_row = {
            "코드": f"{len(pstate.get('freelancers', [])) + 1:04d}",
            "성명": name,
            "주민등록번호": rrn,
            "_raw_rrn": rrn,
            "내외국인": "내국인1",
            "소득구분": "940909",
            "귀속연월": ym_digits,
            "지급연월": pay_dt_digits[:6],
            "지급일자": pay_dt_digits,
            "입력기준": "세후역산" if is_net else "세전",
            "_base_amount": int(gross_won),
            "지급총액": int(gross_won),
            "세율": 3,
            "비고": f"카톡 자동입력 ({company})",
        }
        pstate.setdefault("freelancers", []).insert(0, new_row)
        _recalculate_all_freelancer_rows(pstate)
        pstate["grid_version"] = int(pstate.get("grid_version", 0)) + 1
    except Exception:
        pass


def _push_kakao_emp_excel_to_payroll(company: str, employees_sample: List[Dict[str, Any]]) -> None:
    """카톡 백그라운드 시뮬레이터(⑤ 급여대장 엑셀파일 수신) → payroll_auto_state['employees'] 자동 반영"""
    try:
        from payroll_automated.ui import _get_payroll_state, _recalculate_all_employee_rows
        pstate = _get_payroll_state()
        if company:
            pstate["corp_name"] = company
        for emp_in in reversed(employees_sample):
            new_emp = {
                "사원코드": f"{len(pstate.get('employees', [])) + 1:03d}",
                "사원명": emp_in.get("name", "임직원"),
                "부서": emp_in.get("dept", "관리부"),
                "직급": emp_in.get("title", "사원"),
                "입사일": emp_in.get("hire_date", "2024-01-01"),
                "입력기준": "세전",
                "보험적용구분": "요율(2순위)",
                "기본급": int(emp_in.get("base_pay", 3200000)),
                "상여": int(emp_in.get("bonus", 0)),
                "식대": int(emp_in.get("meal", 200000)),
                "자가운전보조금": 0,
                "약정연장근로수당": 0,
                "약정휴일근로수당": 0,
                "연장근로수당": 0,
                "휴일근로수당": 0,
                "미사용연차수당": 0,
                "결근공제": 0,
                "조정금액": 0,
                "부양가족수": int(emp_in.get("deps", 1)),
                "자녀수": int(emp_in.get("children", 0)),
                "학자금상환액": 0,
                "소득세감면율": 0,
                "사업장": company or "본점",
            }
            pstate.setdefault("employees", []).insert(0, new_emp)
        _recalculate_all_employee_rows(pstate)
        pstate["grid_version"] = int(pstate.get("grid_version", 0)) + 1
    except Exception:
        pass


def _trigger_kakao_simulator(sim_no: int, cstate: Dict[str, Any]) -> str:
    """사이드바의 '카톡 백그라운드 시뮬레이터 (체험버튼 ①~⑤)' 실행 핸들러"""
    today_d = get_kst_today()
    yr, mo = today_d.year, today_d.month

    if sim_no == 1:
        cstate["silent_read_count"] = int(cstate.get("silent_read_count", 2)) + 1
        cstate["kakao_todos"].insert(0, {
            "id": f"sim_{int(datetime.now().timestamp() * 1000)}",
            "status_code": "APPROVED",
            "status": "사용자 승인완료",
            "category": "통상적 메시지 자동 닫기",
            "client": "(주)우진상사",
            "recipient": "범준",
            "time_ago": "방금 자동처리",
            "bubble_msg": "",
            "title": "(주)우진상사 — \"네 확인했습니다 세무사님!\" (백그라운드 읽음 후 닫기 · 1 소거)",
            "kakao_original": "[카톡 수신] 네 확인했습니다 세무사님!",
            "ai_result": "✅ 답변이 필요 없는 통상적 인사로 판별되어 알림 없이 카톡 숫자 1만 지우고 닫았습니다.",
            "preview": "✅ 답변이 필요 없는 통상적 인사로 판별되어 알림 없이 카톡 숫자 1만 지우고 닫았습니다.",
            "attachment": "자동 읽음 처리 로그 (1 소거 완료)",
            "target_mode": "CALENDAR",
            "action_label": "자동 종결됨",
            "checked": True,
        })
        return "🔕 '(주)우진상사: 네 확인했습니다' → 답변 없이 백그라운드에서 숫자 1만 지우고 닫았어요!"

    if sim_no == 2:
        cstate["kakao_todos"].insert(0, {
            "id": f"sim_{int(datetime.now().timestamp() * 1000)}",
            "status_code": "READY",
            "status": "작업 완료, 승인요청중",
            "category": "요청 서류 준비 완료",
            "client": "(주)갑",
            "recipient": "범준",
            "time_ago": "방금 전",
            "bubble_msg": "범준님, (주)갑 회사로부터 요청받은 서류를 다운받아 보낼 준비가 끝났습니다",
            "title": "(주)갑 — 지방세 세목별과세증명서 & 납세증명서 다운로드 완료",
            "kakao_original": "[카톡 수신] 세무사님 (주)갑인데 은행 제출용 납세증명서랑 지방세 과세증명서 부탁드립니다!",
            "ai_result": (
                "📁 지정 폴더 저장: C:\\tax_automation\\거래처_데이터\\02_(주)갑\\4_발급서류_보관함\\(주)갑_증명서.pdf\n"
                "🛡️ 사업자번호 일치 검증 통과 완료!"
            ),
            "preview": "📁 지정 폴더 저장 완료 및 사업자번호 일치 검증 통과 완료!",
            "attachment": f"(주)갑_지방세과세증명_납세증명서_{today_d.strftime('%Y%m%d')}.pdf",
            "target_mode": "CALENDAR",
            "action_label": "서류 파일 복사 & 승인완료",
            "checked": True,
        })
        cstate["bubble_visible"] = True
        cstate["bubble_idx"] = 0
        cstate["panel_open"] = False
        return "📄 우측 하단 네모 말풍선에 (주)갑 서류 준비 완료 알림이 떴어요!"

    if sim_no == 3:
        cstate["kakao_todos"].insert(0, {
            "id": f"sim_{int(datetime.now().timestamp() * 1000)}",
            "status_code": "READY",
            "status": "작업 완료, 승인요청중",
            "category": "세법 검토 카톡 완성",
            "client": "(주)모",
            "recipient": "범준",
            "time_ago": "방금 전",
            "bubble_msg": "범준님, (주)모 회사에 보낼 세법 검토 카톡이 완성되었습니다",
            "title": "(주)모 — 거래처 경조사비(청첩장·부고) 법인비용 한도 문의 답변 완성",
            "kakao_original": "[카톡 수신] 거래처 대표님 자녀 결혼식 축의금을 50만 원 보내려는데 전부 비용 인정되나요?",
            "ai_result": (
                "안녕하세요 대표님, 거래처 경조사비 세법 기준 안내드립니다.\n"
                "1. 거래처 경조사비는 건당 20만 원까지만 청첩장·부고장 등 증빙으로 기업업무추진비(접대비) 인정됩니다.\n"
                "2. 건당 20만 원 초과 시 전액 비용 불산입되므로 20만 원 이내 지출이 유리합니다.\n"
                "※ 법령 기준의 원론적 안내이며, 구체적 처리는 담당자 확인 후 안내드리겠습니다."
            ),
            "preview": "거래처 경조사비는 건당 20만 원까지만 청첩장·부고장 등 증빙으로 기업업무추진비(접대비) 인정됩니다.",
            "attachment": f"(주)모_경조사비_세법검토안내_{today_d.strftime('%Y%m%d')}.md",
            "target_mode": "AGENT",
            "action_label": "카톡 답장 복사 & 승인완료",
            "checked": True,
        })
        cstate["bubble_visible"] = True
        cstate["bubble_idx"] = 0
        cstate["panel_open"] = False
        return "⚖️ 우측 하단 네모 말풍선에 (주)모 세법 검토 완료 알림이 떴어요!"

    if sim_no == 4:
        _push_kakao_biz_income_to_payroll("(주)스타마케팅", "강민호", "[RRN Omitted]", 2500000, is_net=False)
        cstate["kakao_todos"].insert(0, {
            "id": f"sim_{int(datetime.now().timestamp() * 1000)}",
            "status_code": "READY",
            "status": "작업 완료, 승인요청중",
            "category": "사업소득 자동 입력 완료",
            "client": "(주)스타마케팅",
            "recipient": "범준",
            "time_ago": "방금 전",
            "bubble_msg": "범준님, (주)스타마케팅 카톡 인건비를 사업소득 화면에 자동 작성했습니다",
            "title": "(주)스타마케팅 — 프리랜서 강민호(세전 250만 원) 사업소득 자동 입력 완료",
            "kakao_original": "[카톡 수신] 강민호 [RRN Omitted] 이번 달 외주비 세전 250만 원 지급했습니다. 사업소득 신고 부탁드려요!",
            "ai_result": (
                "✅ 에이전트AI [사업소득] 화면에 자동 드래그&드롭 입력 완료!\n"
                "• 세전 2,500,000원 / 소득세 75,000원 / 지방세 7,500원 / 차인지급액 2,417,500원"
            ),
            "preview": "✅ 에이전트AI [사업소득] 화면에 자동 드래그&드롭 입력 완료! (세전 2,500,000원 / 실지급 2,417,500원)",
            "attachment": f"(주)스타마케팅_강민호_{yr}{mo:02d}_사업소득영수증.pdf",
            "target_mode": "PAYROLL_BIZ",
            "action_label": "사업소득 화면 확인 & 승인완료",
            "checked": True,
        })
        cstate["bubble_visible"] = True
        cstate["bubble_idx"] = 0
        cstate["panel_open"] = False
        return "💼 카톡 인건비(강민호 250만 원)가 [인건비 자동화 > 사업소득] 화면에 자동 입력되었어요!"

    if sim_no == 5:
        _push_kakao_emp_excel_to_payroll(
            "(주)미래바이오",
            [
                {"name": "오지현 연구원", "dept": "연구소", "title": "선임연구원", "base_pay": 4200000, "meal": 200000, "deps": 2},
                {"name": "박준혁 주임", "dept": "영업부", "title": "주임", "base_pay": 3400000, "meal": 200000, "deps": 1},
            ],
        )
        cstate["kakao_todos"].insert(0, {
            "id": f"sim_{int(datetime.now().timestamp() * 1000)}",
            "status_code": "READY",
            "status": "작업 완료, 승인요청중",
            "category": "급여대장 폴더저장 & 자동입력",
            "client": "(주)미래바이오",
            "recipient": "범준",
            "time_ago": "방금 전",
            "bubble_msg": "범준님, (주)미래바이오 급여대장 파일을 폴더에 저장하고 급여명세서에 입력했습니다",
            "title": f"(주)미래바이오 — '{mo}월_급여대장_세전자료.xlsx' 폴더 저장 및 급여명세서 자동 작성 완료",
            "kakao_original": f"[카톡 파일 수신] (주)미래바이오_{mo}월_급여대장_세전자료.xlsx",
            "ai_result": "📁 지정 폴더 저장 완료 → 에이전트AI [급여명세서] 화면에 임직원 세전·4대보험·실수령액 자동 반영 완료!",
            "preview": "📁 지정 폴더 저장 완료 → 에이전트AI [급여명세서] 화면에 자동 반영 완료!",
            "attachment": f"(주)미래바이오_{yr}{mo:02d}_급여명세서.zip",
            "target_mode": "PAYROLL_EMP",
            "action_label": "급여명세서 확인 & 승인완료",
            "checked": True,
        })
        cstate["bubble_visible"] = True
        cstate["bubble_idx"] = 0
        cstate["panel_open"] = False
        return "📊 급여대장 파일이 폴더에 저장되고 [인건비 자동화 > 급여명세서] 화면에 자동 입력되었어요!"

    return "처리가 완료되었습니다."


def _jump_to_target_mode(target_mode: str) -> None:
    """상세 모달 내부에서 업무 화면 바로가기 클릭 시 앱 모드 전환"""
    if target_mode == "AGENT":
        st.session_state["app_mode"] = "자율 에이전트AI"
    elif target_mode in ("PAYROLL_EMP", "PAYROLL_BIZ"):
        st.session_state["app_mode"] = "인건비 자동화"
        try:
            from payroll_automated.ui import _get_payroll_state
            pstate = _get_payroll_state()
            pstate["sub_tab"] = "사업소득" if target_mode == "PAYROLL_BIZ" else "급여명세서"
        except Exception:
            pass


CALENDAR_MAIN_CSS = """
<style>
/* ═════════ Toss Web TDS 달력 + Today To Do 규격 100% 일치 스타일 ═════════ */
[data-testid="stApp"],
[data-testid="stApp"] [data-testid="stMain"],
[data-testid="stApp"] [data-testid="stAppScrollToBottomContainer"],
[data-testid="stApp"] [data-testid="stBottom"] > div {
    background: #F4F6FA !important;
    font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, system-ui, sans-serif !important;
    letter-spacing: -0.02em !important;
}

/* 1. 모든 입력창의 'Press Enter to apply' 문구 및 하단 독 버튼 툴팁 완전 삭제 */
[data-testid="InputInstructions"],
div[data-testid="InputInstructions"],
.st-key-todo_bottom_dock_a [data-testid="stTooltipContent"],
.st-key-todo_bottom_dock_a [data-testid="stTooltipHoverTarget"] > div[role="tooltip"] {
    display: none !important;
    visibility: hidden !important;
    width: 0 !important;
    height: 0 !important;
    opacity: 0 !important;
    pointer-events: none !important;
}

/* 종(Bell) 아이콘 자체만 노랑-주황-빨강-주황-노랑으로 반짝이는 애니메이션 (빛/배경 없음) */
@keyframes tdsBellSparkleOnly {
    0%, 100% {
        color: #FACC15;
        transform: scale(1.0) rotate(0deg);
    }
    25% {
        color: #F97316;
        transform: scale(1.14) rotate(-14deg);
    }
    50% {
        color: #EF4444;
        transform: scale(1.20) rotate(14deg);
    }
    75% {
        color: #F97316;
        transform: scale(1.12) rotate(-8deg);
    }
}

/* ══════ [5]-1 달력 상단 좌측 3대 현황 카드 (높이 74px 고정 & 우측 헤더와 1:1 라인 정렬) ══════ */
.tds-cal-top-kpi-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 12px;
    height: 74px;
    min-height: 74px;
    max-height: 74px;
    margin-bottom: 10px;
    box-sizing: border-box;
}
.tds-cal-kpi-card {
    background: #FFFFFF;
    border: 1px solid #E5E8EB;
    border-radius: 16px;
    height: 74px;
    min-height: 74px;
    max-height: 74px;
    padding: 0 18px;
    box-sizing: border-box;
    display: flex;
    align-items: center;
    justify-content: space-between;
    box-shadow: 0 2px 10px rgba(0, 27, 55, 0.04);
    transition: box-shadow 0.16s ease, transform 0.16s ease;
}
.tds-cal-kpi-card:hover {
    box-shadow: 0 6px 18px rgba(49, 130, 246, 0.10);
    transform: translateY(-1px);
}
.tds-cal-kpi-left {
    display: flex;
    flex-direction: column;
    justify-content: center;
    gap: 5px;
    min-width: 0;
}
.tds-cal-kpi-badge {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    width: fit-content;
    padding: 2px 9px;
    border-radius: 999px;
    border: none;
    font-size: 0.71rem;
    font-weight: 800;
    line-height: 1.3;
    white-space: nowrap;
}
.tds-cal-kpi-badge.blue { background: #E8F3FF; color: #3182F6; }
.tds-cal-kpi-badge.amber { background: #FFF5E5; color: #D97706; }
.tds-cal-kpi-badge.red { background: #FFEEEE; color: #F04452; }
.tds-cal-kpi-badge.green { background: #E5F9F0; color: #00A660; }
.tds-cal-kpi-sub {
    font-size: 0.74rem;
    font-weight: 600;
    color: #8B95A1;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    font-variant-numeric: tabular-nums;
}
.tds-cal-kpi-val {
    font-size: 1.55rem;
    font-weight: 800;
    color: #191F28;
    font-variant-numeric: tabular-nums;
    letter-spacing: -0.03em;
    flex-shrink: 0;
}
.tds-cal-kpi-val small {
    font-size: 0.84rem;
    font-weight: 700;
    color: #4E5968;
    margin-left: 2px;
}

/* 우측 상단 연도 표시 ('2026년' + '◀ 11월 ▶') & '[+ 일정 추가하기]' — 좌측 3대 카드와 74px 1:1 정렬 */
.tds-month-heading-box {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    justify-content: center;
    height: 74px;
    min-height: 74px;
    max-height: 74px;
    margin-bottom: 10px;
    padding-left: 4px;
    box-sizing: border-box;
    user-select: none;
}
.tds-year-mini-label {
    font-size: 0.84rem;
    font-weight: 700;
    color: #8B95A1;
    letter-spacing: -0.02em;
    line-height: 1.1;
    margin-bottom: 4px;
    padding-left: 2px;
    font-variant-numeric: tabular-nums;
}
.tds-month-nav-row {
    display: inline-flex;
    align-items: center;
    gap: 10px;
}
.tds-month-big-text {
    font-size: 2.95rem;
    font-weight: 800;
    color: #191F28;
    letter-spacing: -1.8px;
    line-height: 0.92;
    font-variant-numeric: tabular-nums;
    min-width: 78px;
    text-align: center;
}
.tds-soft-arrow-btn {
    width: 32px;
    height: 32px;
    min-width: 32px;
    min-height: 32px;
    border-radius: 10px;
    background: #FFFFFF;
    border: 1px solid #E5E8EB;
    color: #4E5968;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    padding: 0;
    box-shadow: 0 2px 6px rgba(0, 27, 55, 0.04);
    transition: all 0.15s ease;
}
.tds-soft-arrow-btn:hover {
    background: #E8F3FF;
    border-color: #90C2FF;
    color: #3182F6;
    transform: translateY(-1px);
}
.tds-soft-arrow-btn:active {
    transform: translateY(0px) scale(0.96);
}

/* 숨김 월 이동 트리거 버튼 래퍼 */
[data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-cal_hidden_month_nav_wrap {
    position: absolute !important;
    width: 0 !important;
    height: 0 !important;
    overflow: hidden !important;
    opacity: 0 !important;
    pointer-events: none !important;
    margin: 0 !important;
    padding: 0 !important;
}

[data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-cal_add_btn_wrap {
    display: flex !important;
    align-items: center !important;
    justify-content: flex-end !important;
    height: 74px !important;
    min-height: 74px !important;
    max-height: 74px !important;
    margin-bottom: 10px !important;
}
[data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-cal_add_btn_wrap div.stButton {
    display: flex !important;
    justify-content: flex-end !important;
    width: 100% !important;
}
/* [3]-2 1순위 Primary 버튼 규격: 솔리드 토스 블루(#3182F6), 텍스트 #FFFFFF, 800, border: none, border-radius: 10px */
[data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-cal_add_btn_wrap div.stButton > button {
    background: #3182F6 !important;
    border: none !important;
    border-radius: 10px !important;
    color: #FFFFFF !important;
    font-weight: 800 !important;
    min-height: 46px !important;
    height: 46px !important;
    padding: 0 18px !important;
    box-shadow: 0 6px 18px rgba(49, 130, 246, 0.10) !important;
    width: auto !important;
}
[data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-cal_add_btn_wrap div.stButton > button:hover {
    background: #1B64DA !important;
}

/* [5]-1 좌측 달력 본체 & 우측 할 일 카드: 30% 반투명 글래스모피즘 통일 */
[data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-cal_glass_surface {
    background: rgba(255, 255, 255, 0.30) !important;
    backdrop-filter: blur(22px) saturate(180%) !important;
    -webkit-backdrop-filter: blur(22px) saturate(180%) !important;
    border: 1px solid #E5E8EB !important;
    box-shadow: 0 2px 10px rgba(0, 27, 55, 0.04) !important;
    border-radius: 28px !important;
    padding: 18px 20px 22px 20px !important;
    min-height: 830px !important;
    box-sizing: border-box !important;
}

[data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-cal_right_todo_card {
    background: rgba(255, 255, 255, 0.30) !important;
    backdrop-filter: blur(22px) saturate(180%) !important;
    -webkit-backdrop-filter: blur(22px) saturate(180%) !important;
    border: 1px solid #E5E8EB !important;
    box-shadow: 0 2px 10px rgba(0, 27, 55, 0.04) !important;
    border-radius: 28px !important;
    padding: 22px 20px 18px 20px !important;
    min-height: 830px !important;
    display: flex !important;
    flex-direction: column !important;
    justify-content: space-between !important;
    box-sizing: border-box !important;
}

/* 달력 최상단 요일 헤더 */
.tds-cal-dow-grid {
    display: grid;
    grid-template-columns: repeat(7, 1fr);
    gap: 10px;
    margin-bottom: 10px;
    text-align: center;
}
.tds-cal-dow-cell {
    font-size: 0.84rem;
    font-weight: 700;
    color: #4E5968;
    padding: 4px 0 6px 0;
}
.tds-cal-dow-cell.sun { color: #F04452; }
.tds-cal-dow-cell.sat { color: #3182F6; }

/* 달력 날짜 셀 (146px 풀사이즈) */
.tds-cal-day-card {
    background: #FFFFFF;
    border: 1px solid #E5E8EB;
    border-radius: 20px;
    height: 146px;
    min-height: 146px;
    padding: 12px;
    box-sizing: border-box;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    box-shadow: 0 2px 10px rgba(0, 27, 55, 0.04);
    transition: all 0.18s cubic-bezier(0.16, 1, 0.3, 1);
    margin-bottom: 6px;
    overflow: hidden;
}
.tds-cal-day-card:hover {
    transform: translateY(-2px);
    box-shadow: 0 6px 18px rgba(49, 130, 246, 0.10);
}
.tds-cal-day-card.selected {
    background: #FFFFFF !important;
    border: 2px solid #3182F6 !important;
    box-shadow: 0 6px 18px rgba(49, 130, 246, 0.10);
}
.tds-cal-day-card.empty {
    background: rgba(255, 255, 255, 0.18);
    border: 1px dashed #E5E8EB;
    box-shadow: none;
}
.tds-cal-day-top {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 6px;
}
.tds-cal-day-num {
    font-size: 0.90rem;
    font-weight: 800;
    color: #191F28;
    font-variant-numeric: tabular-nums;
}
.tds-cal-day-num.sun { color: #F04452; }
.tds-cal-day-num.sat { color: #3182F6; }
.tds-cal-today-badge {
    font-size: 0.65rem;
    font-weight: 800;
    color: #3182F6;
    background: #E8F3FF;
    padding: 2px 8px;
    border-radius: 999px;
    border: none;
}
.tds-cal-ev-list {
    display: flex;
    flex-direction: column;
    gap: 4px;
}
/* [1]-5 보더리스 파스텔 캡슐 배지 (border-radius: 999px, 테두리 없음) */
.tds-cal-ev-pill {
    font-size: 0.71rem;
    font-weight: 700;
    padding: 3px 9px;
    border-radius: 999px;
    border: none;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    line-height: 1.35;
    font-variant-numeric: tabular-nums;
}
.tds-cal-ev-pill.blue { background: #E8F3FF; color: #3182F6; }
.tds-cal-ev-pill.red { background: #FFEEEE; color: #F04452; }
.tds-cal-ev-pill.green { background: #E5F9F0; color: #00A660; }
.tds-cal-ev-more {
    font-size: 0.68rem;
    font-weight: 700;
    color: #8B95A1;
    padding-left: 3px;
    font-variant-numeric: tabular-nums;
}

/* [5]-1 날짜 셀 아래에 별도 버튼을 절대 노출하지 않고 투명 오버레이로 처리 */
[data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-cal_sel_d_"] {
    margin-top: -154px !important;
    height: 146px !important;
    position: relative !important;
    z-index: 5 !important;
}
[data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-cal_sel_d_"] div.stButton,
[data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-cal_sel_d_"] div.stButton > button {
    width: 100% !important;
    height: 146px !important;
    min-height: 146px !important;
    opacity: 0 !important;
    cursor: pointer !important;
    border: none !important;
    background: transparent !important;
    box-shadow: none !important;
    padding: 0 !important;
    margin: 0 !important;
    color: transparent !important;
    font-size: 0 !important;
}

/* 우측 'Today To Do' 헤더 & 슬림 진행률 바 */
.tds-todo-hdr-left {
    display: flex;
    align-items: center;
    gap: 10px;
}
.tds-todo-main-title {
    font-size: 1.45rem;
    font-weight: 800;
    color: #191F28;
    letter-spacing: -0.02em;
    line-height: 1.1;
}
.tds-todo-cnt-pill {
    font-size: 0.78rem;
    font-weight: 800;
    padding: 3px 11px;
    border-radius: 999px;
    background: #E8F3FF;
    color: #3182F6;
    border: none;
    font-variant-numeric: tabular-nums;
}
.tds-todo-progress-track {
    width: 100%;
    height: 6px;
    background: #F2F4F6;
    border-radius: 999px;
    overflow: hidden;
    margin: 10px 0 14px 0;
}
.tds-todo-progress-fill {
    height: 100%;
    background: #3182F6;
    border-radius: 999px;
    transition: width 0.28s ease;
}

/* 상단 [중요 우선] · [완료 숨김] 미니 캡슐 버튼 */
[data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-btn_todo_hdr_urgent div.stButton > button {
    min-height: 28px !important;
    height: 28px !important;
    padding: 0 10px !important;
    border-radius: 999px !important;
    font-size: 0.72rem !important;
    font-weight: 800 !important;
    background: #E8F3FF !important;
    color: #3182F6 !important;
    border: none !important;
    box-shadow: none !important;
}
[data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-btn_todo_hdr_hide div.stButton > button {
    min-height: 28px !important;
    height: 28px !important;
    padding: 0 10px !important;
    border-radius: 999px !important;
    font-size: 0.72rem !important;
    font-weight: 700 !important;
    background: #F2F4F6 !important;
    color: #4E5968 !important;
    border: none !important;
    box-shadow: none !important;
}

/* 0건 초기 빈 상태 안내 카드 */
.tds-empty-todo-box {
    padding: 32px 20px;
    border-radius: 22px;
    background: #FFFFFF;
    border: 1px solid #E5E8EB;
    box-shadow: 0 2px 10px rgba(0, 27, 55, 0.04);
    text-align: center;
    margin-top: 4px;
}
.tds-empty-chk-circle {
    width: 48px;
    height: 48px;
    border-radius: 50%;
    background: #E8F3FF;
    color: #3182F6;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    margin-bottom: 12px;
}
.tds-empty-title {
    font-size: 0.96rem;
    font-weight: 800;
    color: #191F28;
    margin-bottom: 6px;
}
.tds-empty-sub {
    font-size: 0.76rem;
    font-weight: 600;
    color: #8B95A1;
}

/* 순수 HTML 할 일 카드 (높이 58px 고정 + 투명 클릭 오버레이) */
.tds-todo-card-pure {
    position: relative;
    height: 58px;
    min-height: 58px;
    background: #FFFFFF;
    border: 1px solid #E5E8EB;
    border-radius: 18px;
    padding: 0 16px;
    box-sizing: border-box;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    box-shadow: 0 2px 10px rgba(0, 27, 55, 0.04);
    transition: border-color 0.15s ease, box-shadow 0.15s ease;
    user-select: none;
}
.tds-todo-card-pure:hover {
    box-shadow: 0 6px 18px rgba(49, 130, 246, 0.10);
}
.tds-todo-card-pure.done-card {
    background: rgba(255, 255, 255, 0.72);
}
.tds-todo-card-left {
    display: flex;
    align-items: center;
    gap: 12px;
    min-width: 0;
    flex: 1;
}

/* 정사각형 24x24 부드러운 사각 체크박스 (토스 블루) */
.tds-sq-chk {
    width: 24px;
    height: 24px;
    min-width: 24px;
    min-height: 24px;
    border-radius: 7px;
    border: 2px solid #B0B8C1;
    background: #FFFFFF;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    box-sizing: border-box;
}
.tds-sq-chk.checked {
    background: #3182F6;
    border-color: #3182F6;
}

/* 할 일 제목 & 바로 옆 파란 동그라미 '상세' + '2/3' 배지 */
.tds-todo-title-wrap {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
    flex: 1;
}
.tds-todo-title-txt {
    font-size: 0.90rem;
    font-weight: 800;
    color: #191F28;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.tds-todo-title-txt.done {
    text-decoration: line-through;
    text-decoration-thickness: 2px;
    text-decoration-color: #8B95A1;
    color: #8B95A1;
    font-weight: 700;
}

/* 할 일 제목 바로 옆 파란색 바탕 동그라미 '상세' 배지 */
.tds-blue-circle-dtl {
    width: 30px;
    height: 30px;
    min-width: 30px;
    min-height: 30px;
    border-radius: 50%;
    background: #3182F6;
    color: #FFFFFF;
    font-size: 0.66rem;
    font-weight: 800;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    box-shadow: 0 2px 6px rgba(49, 130, 246, 0.28);
}
.tds-sub-progress-pill {
    font-size: 0.68rem;
    font-weight: 800;
    padding: 2px 8px;
    border-radius: 999px;
    border: none;
    background: #E8F3FF;
    color: #3182F6;
    flex-shrink: 0;
    font-variant-numeric: tabular-nums;
}
.tds-urgent-pill {
    font-size: 0.66rem;
    font-weight: 800;
    padding: 2px 8px;
    border-radius: 999px;
    border: none;
    background: #FFEEEE;
    color: #F04452;
    flex-shrink: 0;
}

/* 우측 끝 종 아이콘(빛/배경 없이 종만 반짝임) + 시간 */
.tds-todo-card-right {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-shrink: 0;
    padding-right: 4px;
}
.tds-bell-pure {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 20px;
    height: 20px;
    background: transparent !important;
    box-shadow: none !important;
    color: #3182F6;
}
.tds-bell-pure.sparkle {
    animation: tdsBellSparkleOnly 1.2s infinite ease-in-out;
}
.tds-compact-time {
    font-size: 0.86rem;
    font-weight: 800;
    color: #191F28;
    font-variant-numeric: tabular-nums;
}
.tds-compact-time.done {
    color: #8B95A1;
}

/* 우측 상단 대각선 모서리 작은 원형 '✕' 아이콘 */
.tds-corner-x-circle {
    position: absolute;
    top: -7px;
    right: -7px;
    width: 20px;
    height: 20px;
    border-radius: 50%;
    background: #FFFFFF;
    border: 1px solid #E5E8EB;
    color: #8B95A1;
    font-size: 0.62rem;
    font-weight: 800;
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow: 0 2px 10px rgba(0, 27, 55, 0.04);
    z-index: 4;
}

/* 할 일 카드 위를 덮는 투명 클릭 오버레이 행 */
[data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-todo_hit_row_"] {
    margin-top: -62px !important;
    height: 58px !important;
    margin-bottom: 10px !important;
    position: relative !important;
    z-index: 10 !important;
}
[data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-todo_hit_row_"] div.stButton,
[data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-todo_hit_row_"] div.stButton > button {
    width: 100% !important;
    height: 58px !important;
    min-height: 58px !important;
    opacity: 0 !important;
    cursor: pointer !important;
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    padding: 0 !important;
    margin: 0 !important;
}

/* ══════ 우측 최하단 한 줄 일체형 대화입력 독(Dock) 바 (평상시 Flat / 클릭 시 Sunken 입체) ══════ */
[data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-todo_bottom_dock_a {
    background: #FFFFFF !important;
    border: 2px solid #3182F6 !important;
    border-radius: 22px !important;
    padding: 10px 12px !important;
    box-shadow: 0 6px 18px rgba(49, 130, 246, 0.10) !important;
    margin-top: 10px !important;
}

/* 좌측 할 일 대화입력칸 */
[data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-dock_chat_wrap_"] [data-testid="stTextInput"] > div > div {
    background: #F4F6FA !important;
    border: 1px solid #E5E8EB !important;
    border-radius: 10px !important;
    height: 40px !important;
    min-height: 40px !important;
    padding-right: 4px !important;
    box-shadow: none !important;
}
[data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-dock_chat_wrap_"] [data-testid="stTextInput"] input {
    background: transparent !important;
    border: none !important;
    height: 38px !important;
    min-height: 38px !important;
    font-size: 0.84rem !important;
    font-weight: 700 !important;
    color: #191F28 !important;
    padding: 0 10px !important;
    width: 100% !important;
}

/* 중앙 분리형 숫자 전용 [ 시 : 분 ] 시간 입력칸 */
[data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-dock_time_wrap_"] [data-testid="stTextInput"] > div > div {
    background: #E8F3FF !important;
    border: 1.5px solid #90C2FF !important;
    border-radius: 10px !important;
    height: 40px !important;
    min-height: 40px !important;
    padding: 0 4px !important;
    box-shadow: none !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
}
.tds-dual-time-box {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 100%;
    height: 38px;
    gap: 1px;
    box-sizing: border-box;
}
.tds-time-part-inp {
    width: 42% !important;
    height: 34px !important;
    min-height: 34px !important;
    background: transparent !important;
    border: none !important;
    outline: none !important;
    padding: 0 !important;
    margin: 0 !important;
    text-align: center !important;
    font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, system-ui, sans-serif !important;
    font-size: 0.86rem !important;
    font-weight: 800 !important;
    color: #191F28 !important;
    font-variant-numeric: tabular-nums !important;
    ime-mode: disabled !important;
}
.tds-time-part-inp::placeholder {
    color: #8B95A1 !important;
    font-weight: 700 !important;
    font-size: 0.76rem !important;
}
.tds-time-part-inp:focus {
    background: #FFFFFF !important;
    border-radius: 6px !important;
    box-shadow: 0 0 0 1.5px #3182F6 !important;
}
.tds-time-colon {
    font-size: 0.90rem;
    font-weight: 800;
    color: #3182F6;
    line-height: 1;
    padding: 0 1px;
    user-select: none;
}

/* 우측 [알림], [달력], [상세] 버튼: 평상시에는 입체감 없는 매끈한 평면(Flat) 토스 블루 버튼 */
[data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-todo_bottom_dock_a button,
[data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-btn_dock_"] button {
    width: 100% !important;
    height: 40px !important;
    min-height: 40px !important;
    padding: 0 4px !important;
    border-radius: 10px !important;
    font-size: 0.78rem !important;
    font-weight: 800 !important;
    background: #3182F6 !important;
    background-color: #3182F6 !important;
    border: none !important;
    color: #FFFFFF !important;
    box-shadow: none !important;
    transform: none !important;
    transition: all 0.10s ease !important;
    cursor: pointer !important;
}
[data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-todo_bottom_dock_a button * {
    color: #FFFFFF !important;
    font-weight: 800 !important;
    pointer-events: none !important;
}
/* 클릭하여 활성화된(ON) 상태일 때만 안으로 꾹 들어간 오목 입체(Sunken) 스타일! */
[data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-todo_bottom_dock_a button.tds-dock-btn-sunken,
[data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-btn_dock_"] button.tds-dock-btn-sunken {
    background: #1854BA !important;
    background-color: #1854BA !important;
    border: 2px solid #0F3882 !important;
    box-shadow: inset 0 4px 7px rgba(10, 32, 78, 0.65), inset 0 1px 2px rgba(10, 32, 78, 0.85) !important;
    padding-top: 3px !important;
}

/* 사이드바 하단 초기화 버튼 3순위 Destructive 적용 */
section[data-testid="stSidebar"] .st-key-btn_sb_footer_reset_demo div.stButton > button {
    background: #FFEEEE !important;
    color: #F04452 !important;
    font-weight: 700 !important;
    border: none !important;
    border-radius: 10px !important;
}
section[data-testid="stSidebar"] .st-key-btn_sb_footer_open_todo div.stButton > button,
section[data-testid="stSidebar"] .st-key-btn_cal_go_today div.stButton > button {
    background: #F2F4F6 !important;
    color: #191F28 !important;
    font-weight: 700 !important;
    border: none !important;
    border-radius: 10px !important;
}

/* ══════ 화면 중앙 상세입력 창 (주변 배경 어둡지 않게 유지 + 푸른색 바탕 + 순백색 입력칸) ══════ */
div[data-testid="stDialog"],
div[data-testid="stModal"],
div[data-baseweb="modal"],
div[data-testid="stDialog"] > div:first-child {
    background: transparent !important;
    background-color: transparent !important;
    backdrop-filter: none !important;
    -webkit-backdrop-filter: none !important;
}
div[data-testid="stDialog"] div[role="dialog"],
div[data-testid="stDialog"] > div > div {
    border-radius: 28px !important;
    padding: 24px 28px !important;
    border: 2px solid #90C2FF !important;
    box-shadow: 0 20px 50px rgba(49, 130, 246, 0.18), 0 4px 16px rgba(0, 27, 55, 0.08) !important;
    background: #E8F3FF !important;
    background-color: #E8F3FF !important;
    max-width: 780px !important;
}
/* 상세일정 모달 내부 모든 입력칸·드롭다운·텍스트영역을 순백색(#FFFFFF)으로 강조 */
div[data-testid="stDialog"] [data-testid="stTextInput"] > div > div,
div[data-testid="stDialog"] [data-testid="stSelectbox"] > div > div,
div[data-testid="stDialog"] [data-testid="stTextArea"] > div > div,
div[data-testid="stDialog"] [data-baseweb="input"],
div[data-testid="stDialog"] [data-baseweb="select"] > div,
div[data-testid="stDialog"] [data-baseweb="textarea"] {
    background: #FFFFFF !important;
    background-color: #FFFFFF !important;
    border: 1px solid #C9E2FF !important;
    border-radius: 12px !important;
    box-shadow: 0 2px 6px rgba(49, 130, 246, 0.05) !important;
}
div[data-testid="stDialog"] input,
div[data-testid="stDialog"] textarea {
    background: #FFFFFF !important;
    color: #191F28 !important;
}
.gcal-tds-title-wrap [data-testid="stTextInput"] > div > div {
    background: #FFFFFF !important;
    background-color: #FFFFFF !important;
    border: 1.5px solid #90C2FF !important;
    border-bottom: 3px solid #3182F6 !important;
    border-radius: 14px !important;
    padding-left: 12px !important;
    box-shadow: 0 2px 8px rgba(49, 130, 246, 0.06) !important;
}
.gcal-tds-title-wrap [data-testid="stTextInput"] input {
    font-size: 1.35rem !important;
    font-weight: 800 !important;
    color: #191F28 !important;
    padding-left: 4px !important;
}
.gcal-tds-row-lbl {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    background: #FFFFFF;
    color: #3182F6;
    font-size: 0.76rem;
    font-weight: 800;
    padding: 8px 10px;
    border-radius: 999px;
    border: 1px solid #90C2FF;
    margin-top: 2px;
    width: 100%;
    box-sizing: border-box;
    box-shadow: 0 2px 6px rgba(49, 130, 246, 0.06);
}
div[data-testid="stDialog"] [class*="st-key-dlg_btn_add_sub_"] div.stButton > button {
    background: #FFFFFF !important;
    color: #3182F6 !important;
    font-weight: 800 !important;
    border: 1px solid #90C2FF !important;
    border-radius: 10px !important;
}
div[data-testid="stDialog"] [class*="st-key-dlg_btn_save_"] div.stButton > button {
    background: #3182F6 !important;
    color: #FFFFFF !important;
    font-weight: 800 !important;
    border: none !important;
    border-radius: 10px !important;
}
div[data-testid="stDialog"] [class*="st-key-dlg_btn_save_"] div.stButton > button:hover {
    background: #1B64DA !important;
}
div[data-testid="stDialog"] [class*="st-key-dlg_btn_cancel_"] div.stButton > button {
    background: #FFFFFF !important;
    color: #191F28 !important;
    font-weight: 700 !important;
    border: 1px solid #C9E2FF !important;
    border-radius: 10px !important;
}
div[data-testid="stDialog"] [class*="st-key-dlg_btn_delete_"] div.stButton > button {
    background: #FFEEEE !important;
    color: #F04452 !important;
    font-weight: 700 !important;
    border: none !important;
    border-radius: 10px !important;
}
</style>
"""


def _init_calendar_state() -> Dict[str, Any]:
    """
    달력 및 Today To Do 세션 상태를 초기화합니다.
    - 초기 dock_alarm, dock_cal, dock_dtl은 모두 False(평면 기본 상태)로 시작합니다.
    """
    today_d = get_kst_today()
    today_iso = today_d.isoformat()

    if (
        "cal_scheduler_state" not in st.session_state
        or st.session_state["cal_scheduler_state"].get("_schema_v") != _STATE_SCHEMA_VERSION
    ):
        ym_key = f"{today_d.year:04d}-{today_d.month:02d}"
        st.session_state["cal_scheduler_state"] = {
            "_schema_v": _STATE_SCHEMA_VERSION,
            "_last_kst_today_iso": today_iso,
            "year": today_d.year,
            "month": today_d.month,
            "selected_day": today_d.day,
            "schedules_by_ym": {
                ym_key: _default_schedules_for_month(today_d.year, today_d.month, today_d),
            },
            "kakao_todos": _default_kakao_todos(today_d),
            "silent_read_count": 2,
            "panel_open": False,
            "bubble_visible": True,
            "bubble_idx": 0,
            "todo_filter": "전체",
            "show_add_modal": False,
            "urgent_first": False,
            "hide_completed": False,
            "dock_alarm": False,
            "dock_cal": False,
            "dock_dtl": False,
            "dock_reset_seq": 0,
            "pending_detail_draft": None,
            "open_detail_from_dock": False,
            "active_detail_ev_id": None,
        }
    cstate = st.session_state["cal_scheduler_state"]
    cstate.setdefault("silent_read_count", 2)
    cstate.setdefault("urgent_first", False)
    cstate.setdefault("hide_completed", False)
    cstate.setdefault("dock_alarm", False)
    cstate.setdefault("dock_cal", False)
    cstate.setdefault("dock_dtl", False)
    cstate.setdefault("dock_reset_seq", 0)
    cstate.setdefault("pending_detail_draft", None)
    cstate.setdefault("open_detail_from_dock", False)
    cstate.setdefault("active_detail_ev_id", None)

    if cstate.get("_last_kst_today_iso") != today_iso:
        cstate["_last_kst_today_iso"] = today_iso
        cstate["year"] = today_d.year
        cstate["month"] = today_d.month
        cstate["selected_day"] = today_d.day
        st.session_state["cal_sb_year_sel"] = today_d.year
        st.session_state["cal_sb_month_sel"] = today_d.month

    ym_key = f"{int(cstate['year']):04d}-{int(cstate['month']):02d}"
    if ym_key not in cstate["schedules_by_ym"]:
        cstate["schedules_by_ym"][ym_key] = _default_schedules_for_month(
            int(cstate["year"]), int(cstate["month"]), today_d
        )
    return cstate


def _commit_dock_schedule_on_enter() -> None:
    """
    하단 독(Dock)에서:
    1) 사용자가 [Enter] 키를 쳤을 때(__ENTER_COMMIT_TGL_...__): 할 일 + 시간 + [알림]·[달력] 상태를 즉시 등록합니다.
    2) 사용자가 [상세] 버튼을 눌렀을 때(__DTL_OPEN_TGL_...__): 입력한 내용과 시간을 pending_detail_draft에 담아
       상세 모달을 오픈합니다.
    3) 단순 Tab 키 이동이나 blur일 때(NONE): 등록하지 않고 입력값을 보존합니다.
    """
    cstate = _init_calendar_state()
    year = int(cstate["year"])
    month = int(cstate["month"])
    sel_day = int(cstate["selected_day"])
    inp_key = f"dock_chat_inp_{year}_{month}_{sel_day}"
    time_key = f"dock_time_inp_{year}_{month}_{sel_day}"

    raw_val = str(st.session_state.get(inp_key, "")).strip()
    clean_txt, js_alarm, js_cal, js_time, action_mode = _parse_dock_raw_payload(raw_val)

    if action_mode == "NONE":
        if clean_txt != raw_val:
            st.session_state[inp_key] = clean_txt
        return

    raw_time = js_time if js_time is not None else str(st.session_state.get(time_key, "")).strip()
    norm_t = _normalize_time_str(raw_time)
    is_alarm = js_alarm if js_alarm is not None else bool(cstate.get("dock_alarm", False))
    is_cal = js_cal if js_cal is not None else bool(cstate.get("dock_cal", False))

    # [상세] 버튼 클릭으로 진입한 경우: 입력한 제목·시간·알림·달력 상태를 그대로 상세모달로 전달
    if action_mode == "DETAIL":
        st.session_state[inp_key] = clean_txt
        cstate["dock_alarm"] = is_alarm
        cstate["dock_cal"] = is_cal
        cstate["dock_dtl"] = False
        cstate["pending_detail_draft"] = {
            "title": clean_txt,
            "time": norm_t,
            "alarm": is_alarm,
            "show_on_cal": is_cal,
        }
        cstate["open_detail_from_dock"] = True
        return

    # [Enter] 키로 직접 등록한 경우
    if not clean_txt:
        st.session_state[inp_key] = ""
        return

    today_d = get_kst_today()
    ym_key = f"{year:04d}-{month:02d}"
    month_schedules = cstate["schedules_by_ym"].setdefault(
        ym_key, _default_schedules_for_month(year, month, today_d)
    )
    new_ev_id = f"q_{int(datetime.now().timestamp() * 1000)}"

    new_ev = {
        "id": new_ev_id,
        "type": "MY",
        "time": norm_t,
        "base_date_iso": today_d.isoformat(),
        "title": clean_txt,
        "client": "내 스케줄",
        "category": "내 스케줄",
        "ai_status": "작업 완료, 승인요청중",
        "done": False,
        "alarm": is_alarm,
        "alarm_glow": False,
        "show_on_cal": is_cal,
        "urgent": False,
        "has_detail": False,
        "repeat": "반복 안함",
        "location": "",
        "link_target": "CALENDAR",
        "link_label": "",
        "attachment": "",
        "sub_tasks": [],
        "desc": clean_txt,
    }
    month_schedules.setdefault(sel_day, []).append(new_ev)

    if is_alarm:
        cstate["kakao_todos"].insert(0, {
            "id": f"todo_alarm_{new_ev_id}",
            "status_code": "READY",
            "status": "작업 완료, 승인요청중",
            "category": f"⏰ 오늘 {norm_t or '일정'} 알림",
            "client": "Today To Do",
            "recipient": "범준",
            "time_ago": norm_t or "방금 등록",
            "bubble_msg": f"범준님, [{clean_txt}] 오늘 일정({norm_t or '시간 미지정'}) 알림이 설정되었습니다",
            "title": f"[오늘 일정 알림] {clean_txt} ({norm_t or '시간 미지정'})",
            "kakao_original": f"[Today To Do 등록 · 오늘({today_d.month}/{today_d.day}) 기준] {norm_t} · {clean_txt}",
            "ai_result": "✅ 오늘 지정된 시각에 우측 하단 홈버튼 말풍선과 종 아이콘 반짝임으로 알려드립니다.",
            "preview": "✅ 오늘 지정된 시각에 우측 하단 홈버튼 말풍선으로 알려드립니다.",
            "attachment": "",
            "target_mode": "CALENDAR",
            "action_label": "일정 확인 완료",
            "checked": False,
        })
        cstate["bubble_visible"] = True
        cstate["bubble_idx"] = 0

    # 등록 완료 후 입력칸 및 버튼 3개 모두 평면(Flat) 기본 상태로 초기화
    st.session_state[inp_key] = ""
    st.session_state[time_key] = ""
    cstate["dock_alarm"] = False
    cstate["dock_cal"] = False
    cstate["dock_dtl"] = False
    cstate["pending_detail_draft"] = None
    cstate["dock_reset_seq"] = int(cstate.get("dock_reset_seq", 0)) + 1


def _add_sub_task_in_dialog(ev_id: str) -> None:
    """상세 모달 내부에서 [+ 항목 추가] 클릭 또는 Enter 시 모달을 닫지 않고 하위 체크항목을 한 줄 추가합니다."""
    subs_key = f"dlg_subs_state_{ev_id}"
    inp_key = f"dlg_new_sub_inp_{ev_id}"
    new_txt = str(st.session_state.get(inp_key, "")).strip()
    if new_txt:
        cur_list = list(st.session_state.get(subs_key, []))
        cur_list.append({"title": new_txt, "done": False})
        st.session_state[subs_key] = cur_list
        st.session_state[inp_key] = ""


def _delete_sub_task_in_dialog(ev_id: str, del_idx: int) -> None:
    """상세 모달 내부에서 하위 체크항목의 [✕] 클릭 시 모달을 닫지 않고 해당 줄만 삭제합니다."""
    subs_key = f"dlg_subs_state_{ev_id}"
    cur_list = list(st.session_state.get(subs_key, []))
    if 0 <= del_idx < len(cur_list):
        cur_list.pop(del_idx)
        st.session_state[subs_key] = cur_list


@st.dialog("📋 상세일정 설정", width="large")
def _open_schedule_detail_dialog(year: int, month: int, day_num: int, ev_id: str) -> None:
    """
    화면 중앙 상세입력 모달 (푸른색 바탕 + 순백색 입력칸 + 투명 배경 유지):
    - 하단 독에서 입력한 내용·시간(시:분)·알림·달력 상태를 그대로 이어받아 표시합니다.
    - '연결' 행 및 좌측 하단 '김범준 · 한가함 · 기본 공개 설정' 문구를 모두 제거했습니다.
    - '체크' 란에서 [+ 항목 추가] 클릭 시 창이 닫히지 않고 즉시 아래에 체크 항목 한 줄이 추가됩니다.
    """
    cstate = _init_calendar_state()
    cstate["dock_dtl"] = False
    today_d = get_kst_today()
    ym_key = f"{year:04d}-{month:02d}"
    month_schedules = cstate["schedules_by_ym"].setdefault(
        ym_key, _default_schedules_for_month(year, month, today_d)
    )
    day_evs = month_schedules.setdefault(day_num, [])
    target_ev = next((x for x in day_evs if str(x.get("id")) == str(ev_id)), None)

    inp_key = f"dock_chat_inp_{year}_{month}_{day_num}"
    time_key = f"dock_time_inp_{year}_{month}_{day_num}"

    is_new = False
    if target_ev is None:
        is_new = True
        pending = cstate.get("pending_detail_draft") or {}
        raw_draft = str(st.session_state.get(inp_key, "")).strip()
        clean_title, js_a, js_c, js_t, _ = _parse_dock_raw_payload(raw_draft)
        if clean_title != raw_draft:
            st.session_state[inp_key] = clean_title

        final_draft_title = str(pending.get("title") if pending.get("title") is not None else clean_title).strip()
        init_alarm = (
            bool(pending["alarm"])
            if "alarm" in pending
            else (js_a if js_a is not None else bool(cstate.get("dock_alarm", False)))
        )
        init_cal = (
            bool(pending["show_on_cal"])
            if "show_on_cal" in pending
            else (js_c if js_c is not None else bool(cstate.get("dock_cal", False)))
        )
        raw_t_candidate = (
            str(pending.get("time") or "")
            or (js_t if js_t else "")
            or str(st.session_state.get(time_key, ""))
        )
        draft_t = _normalize_time_str(raw_t_candidate)

        target_ev = {
            "id": ev_id,
            "type": "MY",
            "time": draft_t,
            "base_date_iso": today_d.isoformat(),
            "title": final_draft_title,
            "client": "",
            "category": "내 스케줄",
            "ai_status": "작업 완료, 승인요청중",
            "done": False,
            "alarm": init_alarm,
            "alarm_glow": False,
            "show_on_cal": init_cal,
            "urgent": False,
            "has_detail": True,
            "repeat": "반복 안함",
            "location": "",
            "link_target": "CALENDAR",
            "link_label": "",
            "attachment": "",
            "sub_tasks": [],
            "desc": "",
        }

    subs_state_key = f"dlg_subs_state_{ev_id}"
    if subs_state_key not in st.session_state:
        st.session_state[subs_state_key] = [
            {"title": str(s.get("title", "")), "done": bool(s.get("done", False))}
            for s in list(target_ev.get("sub_tasks", []))
        ]

    # 1) 제목 입력 (순백색 입력칸 + 파란색 포인트 보더)
    st.markdown("<div class='gcal-tds-title-wrap'>", unsafe_allow_html=True)
    in_title = st.text_input(
        "일정 제목",
        value=str(target_ev.get("title", "")),
        placeholder="부가세 예정고지 안내 (제목 입력)",
        label_visibility="collapsed",
        key=f"dlg_title_{ev_id}",
    )
    st.markdown("</div>", unsafe_allow_html=True)

    # 2) 카테고리 선택 캡슐 (내 스케줄 / 세무기한 / 승인완료 / ★ 중요 핀)
    c_cat, c_urg = st.columns([3.2, 1.2], gap="small")
    cur_type = str(target_ev.get("type", "MY")).upper()
    cat_opts = ["🔵 내 스케줄", "🔴 세무기한", "🟢 승인완료"]
    cat_idx = 1 if cur_type == "TAX" else (2 if cur_type == "DONE" else 0)
    with c_cat:
        sel_cat_lbl = st.radio(
            "카테고리",
            options=cat_opts,
            index=cat_idx,
            horizontal=True,
            label_visibility="collapsed",
            key=f"dlg_cat_{ev_id}",
        )
    with c_urg:
        in_urgent = st.checkbox(
            "★ 중요 핀",
            value=bool(target_ev.get("urgent", False)),
            key=f"dlg_urg_{ev_id}",
        )

    # 3) 시간 · 날짜 · 반복 + 알림/달력 연동 행
    r1_l, r1_c1, r1_c2, r1_c3 = st.columns([0.72, 1.55, 1.05, 1.2], gap="small")
    max_day = calendar.monthrange(year, month)[1]
    with r1_l:
        st.markdown("<div class='gcal-tds-row-lbl'>시간</div>", unsafe_allow_html=True)
    with r1_c1:
        in_day = st.selectbox(
            "날짜",
            options=list(range(1, max_day + 1)),
            index=min(day_num, max_day) - 1,
            format_func=lambda d: f"{year}년 {month}월 {d}일 ({_WEEKDAYS_SHORT[date(year, month, d).weekday()]})",
            label_visibility="collapsed",
            key=f"dlg_day_{ev_id}",
        )
    with r1_c2:
        in_time = st.text_input(
            "시간 (HH:MM)",
            value=str(target_ev.get("time", "")),
            placeholder="00:00 (미입력 시 시간 없음)",
            label_visibility="collapsed",
            key=f"dlg_time_{ev_id}",
        )
    with r1_c3:
        rep_opts = ["반복 안함", "매일 반복", "매주 반복", "매월 반복", "매년 반복"]
        cur_rep = str(target_ev.get("repeat", "반복 안함"))
        rep_idx = rep_opts.index(cur_rep) if cur_rep in rep_opts else 0
        in_repeat = st.selectbox(
            "반복",
            options=rep_opts,
            index=rep_idx,
            label_visibility="collapsed",
            key=f"dlg_rep_{ev_id}",
        )

    _, r1_sub1, r1_sub2 = st.columns([0.72, 1.9, 1.9], gap="small")
    with r1_sub1:
        in_alarm = st.checkbox(
            "🔔 정각 홈버튼 & 종 반짝임 알림",
            value=bool(target_ev.get("alarm", False)),
            key=f"dlg_alarm_{ev_id}",
        )
    with r1_sub2:
        in_show_cal = st.checkbox(
            "● 오늘자 달력에 표시됨",
            value=bool(target_ev.get("show_on_cal", False)),
            key=f"dlg_showcal_{ev_id}",
        )

    # 4) 거래처 행
    r2_l, r2_r = st.columns([0.72, 3.8], gap="small")
    with r2_l:
        st.markdown("<div class='gcal-tds-row-lbl'>거래처</div>", unsafe_allow_html=True)
    with r2_r:
        in_client = st.text_input(
            "기장 거래처 및 담당자",
            value=str(target_ev.get("client", "")),
            placeholder="기장 거래처 / 담당자 입력 (예: (주)성진 · 김성진 대표님)",
            label_visibility="collapsed",
            key=f"dlg_client_{ev_id}",
        )

    # 5) 체크 행 (하위 세부 체크항목 — [+ 항목 추가] 클릭 시 창이 닫히지 않고 즉시 아래에 한 줄씩 추가됨)
    r4_l, r4_r = st.columns([0.72, 3.8], gap="small")
    cur_sub_tasks: List[Dict[str, Any]] = list(st.session_state.get(subs_state_key, []))
    with r4_l:
        st.markdown("<div class='gcal-tds-row-lbl'>체크</div>", unsafe_allow_html=True)
    with r4_r:
        for s_idx, s_item in enumerate(cur_sub_tasks):
            chk_key = f"dlg_sub_chk_{ev_id}_{s_idx}_{s_item.get('title', '')}"
            if chk_key in st.session_state:
                s_item["done"] = bool(st.session_state[chk_key])

        done_sub_cnt = sum(1 for s in cur_sub_tasks if s.get("done"))
        st.caption(
            f"**하위 세부 체크항목 추가 ({done_sub_cnt}/{len(cur_sub_tasks)} 완료)** (등록 시 할일 옆에 0/N 진행률 표시)"
        )

        for s_idx, s_item in enumerate(cur_sub_tasks):
            sc_chk, sc_del = st.columns([5.5, 0.8], gap="small")
            chk_key = f"dlg_sub_chk_{ev_id}_{s_idx}_{s_item.get('title', '')}"
            with sc_chk:
                s_checked = st.checkbox(
                    str(s_item.get("title", "")),
                    value=bool(s_item.get("done", False)),
                    key=chk_key,
                )
                cur_sub_tasks[s_idx]["done"] = bool(s_checked)
            with sc_del:
                st.button(
                    "✕",
                    key=f"dlg_sub_del_{ev_id}_{s_idx}",
                    on_click=_delete_sub_task_in_dialog,
                    args=(ev_id, s_idx),
                )

        st.session_state[subs_state_key] = cur_sub_tasks

        ns_c1, ns_c2 = st.columns([4.2, 1.3], gap="small")
        with ns_c1:
            st.text_input(
                "새 세부 체크항목 추가",
                placeholder="세부 체크항목 입력...",
                label_visibility="collapsed",
                key=f"dlg_new_sub_inp_{ev_id}",
                on_change=_add_sub_task_in_dialog,
                args=(ev_id,),
            )
        with ns_c2:
            st.button(
                "＋ 항목 추가",
                width="stretch",
                key=f"dlg_btn_add_sub_{ev_id}",
                on_click=_add_sub_task_in_dialog,
                args=(ev_id,),
            )

    # 6) 메모 행
    r5_l, r5_r = st.columns([0.72, 3.8], gap="small")
    with r5_l:
        st.markdown("<div class='gcal-tds-row-lbl'>메모</div>", unsafe_allow_html=True)
    with r5_r:
        in_desc = st.text_area(
            "상세 메모",
            value=str(target_ev.get("desc", "")),
            placeholder="상세 설명 또는 Google Drive / 로컬 첨부파일 추가",
            height=68,
            label_visibility="collapsed",
            key=f"dlg_desc_{ev_id}",
        )
        in_attach = st.text_input(
            "첨부파일명",
            value=str(target_ev.get("attachment", "")),
            placeholder="+ 첨부파일명 입력 또는 파일 추가",
            label_visibility="collapsed",
            key=f"dlg_att_{ev_id}",
        )

    st.divider()

    # 7) 하단 푸터 (좌측 문구 제거, 우측 취소 / 저장 버튼만 배치)
    _, f_del, f_can, f_save = st.columns([2.6, 0.8, 0.8, 1.0], gap="small")
    with f_del:
        if not is_new:
            if st.button("삭제", width="stretch", key=f"dlg_btn_delete_{ev_id}"):
                month_schedules[day_num] = [x for x in day_evs if str(x.get("id")) != str(ev_id)]
                st.session_state.pop(subs_state_key, None)
                cstate["active_detail_ev_id"] = None
                cstate["pending_detail_draft"] = None
                cstate["dock_dtl"] = False
                st.rerun()
    with f_can:
        if st.button("취소", width="stretch", key=f"dlg_btn_cancel_{ev_id}"):
            st.session_state.pop(subs_state_key, None)
            cstate["active_detail_ev_id"] = None
            cstate["pending_detail_draft"] = None
            cstate["dock_dtl"] = False
            st.rerun()
    with f_save:
        if st.button("저장", width="stretch", key=f"dlg_btn_save_{ev_id}"):
            leftover_sub = str(st.session_state.get(f"dlg_new_sub_inp_{ev_id}", "")).strip()
            updated_subs = list(st.session_state.get(subs_state_key, []))
            if leftover_sub:
                updated_subs.append({"title": leftover_sub, "done": False})

            final_title = in_title.strip() or "세무 상세 일정"
            new_type = "TAX" if "세무기한" in sel_cat_lbl else ("DONE" if "승인완료" in sel_cat_lbl else "MY")
            norm_t = _normalize_time_str(in_time)

            all_subs_done = bool(updated_subs) and all(s.get("done") for s in updated_subs)
            is_done_final = True if (new_type == "DONE" or all_subs_done) else bool(target_ev.get("done", False))

            target_ev.update({
                "title": final_title,
                "type": "DONE" if is_done_final else new_type,
                "category": "세무기한" if new_type == "TAX" else ("승인완료" if is_done_final else "내 스케줄"),
                "time": norm_t,
                "repeat": in_repeat,
                "alarm": bool(in_alarm),
                "alarm_glow": False,
                "show_on_cal": bool(in_show_cal),
                "urgent": bool(in_urgent),
                "client": in_client.strip() or "내 스케줄",
                "sub_tasks": updated_subs,
                "desc": in_desc.strip(),
                "attachment": in_attach.strip(),
                "done": is_done_final,
                "has_detail": True,
            })

            new_d_int = int(in_day)
            if is_new:
                month_schedules.setdefault(new_d_int, []).append(target_ev)
                st.session_state[inp_key] = ""
                st.session_state[time_key] = ""
                if in_alarm:
                    cstate["kakao_todos"].insert(0, {
                        "id": f"todo_alarm_{ev_id}",
                        "status_code": "READY",
                        "status": "작업 완료, 승인요청중",
                        "category": f"⏰ 오늘 {norm_t or '일정'} 알림",
                        "client": "Today To Do",
                        "recipient": "범준",
                        "time_ago": norm_t or "방금 등록",
                        "bubble_msg": f"범준님, [{final_title}] 오늘 일정({norm_t or '시간 미지정'}) 알림이 설정되었습니다",
                        "title": f"[오늘 일정 알림] {final_title} ({norm_t or '시간 미지정'})",
                        "kakao_original": f"[Today To Do 상세등록 · {month}월 {new_d_int}일] {norm_t} · {final_title}",
                        "ai_result": "✅ 오늘 지정된 시각에 우측 하단 홈버튼 말풍선과 종 아이콘 반짝임으로 알려드립니다.",
                        "preview": "✅ 오늘 지정된 시각에 우측 하단 홈버튼 말풍선으로 알려드립니다.",
                        "attachment": "",
                        "target_mode": "CALENDAR",
                        "action_label": "일정 확인 완료",
                        "checked": False,
                    })
                    cstate["bubble_visible"] = True
                    cstate["bubble_idx"] = 0
            elif new_d_int != day_num:
                month_schedules[day_num] = [x for x in day_evs if str(x.get("id")) != str(ev_id)]
                month_schedules.setdefault(new_d_int, []).append(target_ev)

            st.session_state.pop(subs_state_key, None)
            cstate["selected_day"] = new_d_int
            cstate["active_detail_ev_id"] = None
            cstate["pending_detail_draft"] = None
            cstate["dock_alarm"] = False
            cstate["dock_cal"] = False
            cstate["dock_dtl"] = False
            cstate["dock_reset_seq"] = int(cstate.get("dock_reset_seq", 0)) + 1
            st.toast(f"'{final_title}' 상세일정이 저장되었어요.", icon="✅")
            st.rerun()


def render_calendar_sidebar() -> None:
    """좌측 사이드바 ('달력' 모드 전용 제어판)"""
    cstate = _init_calendar_state()
    today_d = get_kst_today()
    wd_str = _WEEKDAYS_SHORT[today_d.weekday()]

    with st.container(border=True):
        today_pill = f"<span style='font-size:0.68rem;font-weight:800;padding:2px 9px;border-radius:999px;background:#E5F9F0;color:#00A660;font-variant-numeric:tabular-nums;'>{today_d.strftime('%Y.%m.%d')} ({wd_str})</span>"
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
            st.session_state["cal_sb_year_sel"] = today_d.year
            st.session_state["cal_sb_month_sel"] = today_d.month
            st.rerun()

    with st.container(border=True):
        sim_pill = "<span style='font-size:0.66rem;font-weight:800;padding:2px 8px;border-radius:999px;background:#FFF5E5;color:#D97706;'>체험버튼</span>"
        st.markdown(_ui_theme.sb_title("zap", "카톡 백그라운드 시뮬레이터", sim_pill), unsafe_allow_html=True)
        st.caption("버튼을 누르면 우측 하단 **웃는 얼굴 홈버튼**과 **네모 말풍선**이 반응합니다.")

        sim_buttons = [
            (1, "💬 ① '네 확인했습니다' 수신 · 무응답 1소거"),
            (2, "📄 ② (주)갑 서류요청 카톡 · 다운+말풍선"),
            (3, "⚖️ ③ (주)모 세법질문 카톡 · 초안+말풍선"),
            (4, "💼 ④ 카톡 사업소득 문자 수신 · 자동입력"),
            (5, "📊 ⑤ 급여대장 엑셀파일 수신 · 폴더+급여"),
        ]
        for s_no, s_lbl in sim_buttons:
            if st.button(s_lbl, width="stretch", key=f"btn_cal_sim_{s_no}"):
                toast_msg = _trigger_kakao_simulator(s_no, cstate)
                st.toast(toast_msg)
                st.rerun()

    with st.container(border=True):
        st.markdown(
            _html("""
            <div style="display:flex;align-items:center;justify-content:space-between;font-size:0.74rem;color:#8B95A1;margin-bottom:8px;">
                <span>카톡 감시 엔진</span>
                <span style="font-weight:800;color:#00A660;background:#E5F9F0;padding:2px 8px;border-radius:999px;"><span style="color:#00C471;">●</span> 실시간 켜짐</span>
            </div>
            """),
            unsafe_allow_html=True,
        )
        f_c1, f_c2 = st.columns(2)
        with f_c1:
            open_lbl = "To-Do 닫기" if cstate.get("panel_open") else "To-Do 열기"
            if st.button(open_lbl, width="stretch", key="btn_sb_footer_open_todo"):
                cstate["panel_open"] = not cstate.get("panel_open", False)
                st.rerun()
        with f_c2:
            if st.button("초기화", width="stretch", key="btn_sb_footer_reset_demo"):
                st.session_state.pop("cal_scheduler_state", None)
                st.rerun()


def render_calendar_main() -> None:
    """메인 화면: 좌측 풀사이즈 달력(상단 74px 3대 현황 카드 포함) + 우측 Today To Do & 하단 평면/입체 다중토글 독(Dock)"""
    cstate = _init_calendar_state()
    cstate["dock_dtl"] = False
    today_d = get_kst_today()

    st.markdown(CALENDAR_MAIN_CSS, unsafe_allow_html=True)

    # 숨김 처리된 이전 달 / 다음 달 이동 트리거 버튼 (우측 ◀ 11월 ▶ 버튼과 연동)
    with st.container(key="cal_hidden_month_nav_wrap"):
        if st.button("이전달", key="btn_cal_m_prev"):
            _shift_calendar_month(cstate, -1)
            st.rerun()
        if st.button("다음달", key="btn_cal_m_next"):
            _shift_calendar_month(cstate, 1)
            st.rerun()

    year = int(cstate["year"])
    month = int(cstate["month"])
    selected_day = int(cstate["selected_day"])
    ym_key = f"{year:04d}-{month:02d}"
    month_schedules = cstate["schedules_by_ym"].setdefault(
        ym_key, _default_schedules_for_month(year, month, today_d)
    )

    # 하단 독에서 [상세] 버튼을 눌러 입력한 내용·시간·알림·달력이 전달된 경우 즉시 모달 오픈
    if cstate.pop("open_detail_from_dock", False):
        new_dtl_id = f"dtl_{int(datetime.now().timestamp() * 1000)}"
        _open_schedule_detail_dialog(year, month, selected_day, new_dtl_id)

    # [5]-1 좌측 상단 3대 현황 카드용 실시간 집계 (일정 / AI작업중 / 작업완료, 승인요청)
    total_month_ev_cnt = sum(len(evs) for evs in month_schedules.values())
    sel_day_ev_cnt = len(month_schedules.get(selected_day, []))
    kakao_todos_all = cstate.get("kakao_todos", [])
    ai_working_cnt = sum(
        1 for t in kakao_todos_all
        if str(t.get("status_code", "")).upper() == "WORKING" or "작업중" in str(t.get("status", ""))
    )
    ai_ready_cnt = sum(
        1 for t in kakao_todos_all
        if str(t.get("status_code", "")).upper() == "READY" or "승인요청" in str(t.get("status", ""))
    )

    col_cal, col_side = st.columns([2.0, 1.0], gap="large")

    with col_cal:
        # [5]-1 달력 상단 좌측 3대 현황 카드 (높이 74px 고정 -> 우측 ◀ 11월 ▶ 타이틀 및 [+ 일정 추가하기]와 1:1 정렬)
        st.markdown(
            _html(f"""
            <div class="tds-cal-top-kpi-grid">
                <div class="tds-cal-kpi-card">
                    <div class="tds-cal-kpi-left">
                        <span class="tds-cal-kpi-badge blue">● 일정</span>
                        <span class="tds-cal-kpi-sub">{month}월 전체 · 선택일 {sel_day_ev_cnt}건</span>
                    </div>
                    <div class="tds-cal-kpi-val">{total_month_ev_cnt}<small>건</small></div>
                </div>
                <div class="tds-cal-kpi-card">
                    <div class="tds-cal-kpi-left">
                        <span class="tds-cal-kpi-badge amber">● AI작업중</span>
                        <span class="tds-cal-kpi-sub">백그라운드 실시간 처리</span>
                    </div>
                    <div class="tds-cal-kpi-val">{ai_working_cnt}<small>건</small></div>
                </div>
                <div class="tds-cal-kpi-card">
                    <div class="tds-cal-kpi-left">
                        <span class="tds-cal-kpi-badge red">● 작업완료, 승인요청</span>
                        <span class="tds-cal-kpi-sub">검토 및 카톡 발송 대기</span>
                    </div>
                    <div class="tds-cal-kpi-val">{ai_ready_cnt}<small>건</small></div>
                </div>
            </div>
            """),
            unsafe_allow_html=True,
        )

        with st.container(key="cal_glass_surface"):
            dow_html = "".join(
                f"<div class='tds-cal-dow-cell {'sun' if i == 0 else ('sat' if i == 6 else '')}'>{d_lbl}</div>"
                for i, d_lbl in enumerate(_SUN_FIRST_HEADERS)
            )
            st.markdown(f"<div class='tds-cal-dow-grid'>{dow_html}</div>", unsafe_allow_html=True)

            cal_obj = calendar.Calendar(firstweekday=6)
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

                            raw_evs = month_schedules.get(day_num, [])
                            cal_evs = [
                                e for e in _sort_day_events(raw_evs)
                                if e.get("show_on_cal", False)
                            ]
                            pills_html = ""
                            for ev in cal_evs[:3]:
                                p_cls = _ev_pill_cls(ev)
                                t_p = _normalize_time_str(str(ev.get("time", "")))
                                prefix_t = f"{t_p} " if t_p else ""
                                pills_html += f"<div class='tds-cal-ev-pill {p_cls}'>{_html_lib.escape(prefix_t + str(ev.get('title', '')))}</div>"
                            if len(cal_evs) > 3:
                                pills_html += f"<div class='tds-cal-ev-more'>+{len(cal_evs) - 3}건</div>"

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
                            # [5]-1 날짜 셀 아래에 '1일 (0건)' 같은 별도 버튼을 절대 노출하지 않고 투명 오버레이로 처리
                            if st.button(
                                " ",
                                key=f"cal_sel_d_{year}_{month}_{day_num}",
                                width="stretch",
                            ):
                                cstate["selected_day"] = day_num
                                st.rerun()

    with col_side:
        c_m_left, c_m_right = st.columns([1.35, 0.95], gap="small")
        with c_m_left:
            # "11월" 양쪽 옆에 부드러운 ◀ ▶ 화살표 버튼 배치
            st.markdown(
                _html(f"""
                <div class="tds-month-heading-box">
                    <span class="tds-year-mini-label">{year}년</span>
                    <div class="tds-month-nav-row">
                        <button type="button" class="tds-soft-arrow-btn" id="tds-cal-prev-month-btn" aria-label="이전 달">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                                <path d="M15.2 6.2L8.4 12L15.2 17.8Z" fill="currentColor" stroke="currentColor" stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round"/>
                            </svg>
                        </button>
                        <span class="tds-month-big-text">{month}월</span>
                        <button type="button" class="tds-soft-arrow-btn" id="tds-cal-next-month-btn" aria-label="다음 달">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                                <path d="M8.8 6.2L15.6 12L8.8 17.8Z" fill="currentColor" stroke="currentColor" stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round"/>
                            </svg>
                        </button>
                    </div>
                </div>
                """),
                unsafe_allow_html=True,
            )
        with c_m_right:
            with st.container(key="cal_add_btn_wrap"):
                if st.button("+ 일정 추가하기", key="btn_cal_open_add_schedule"):
                    cstate["pending_detail_draft"] = {
                        "title": "",
                        "time": "",
                        "alarm": False,
                        "show_on_cal": True,
                    }
                    new_modal_id = f"m_{int(datetime.now().timestamp() * 1000)}"
                    _open_schedule_detail_dialog(year, month, selected_day, new_modal_id)

        sel_date_obj = date(year, month, min(selected_day, calendar.monthrange(year, month)[1]))
        is_sel_today = (sel_date_obj == today_d)
        raw_day_evs = month_schedules.get(selected_day, [])
        sorted_day_evs = _sort_day_events(raw_day_evs, urgent_first=bool(cstate.get("urgent_first", False)))

        total_ev_cnt = len(sorted_day_evs)
        done_ev_cnt = sum(1 for e in sorted_day_evs if e.get("done"))
        prog_pct = int(round((done_ev_cnt / total_ev_cnt) * 100)) if total_ev_cnt > 0 else 0

        visible_evs = (
            [e for e in sorted_day_evs if not e.get("done")]
            if cstate.get("hide_completed")
            else sorted_day_evs
        )

        with st.container(key="cal_right_todo_card"):
            with st.container():
                hdr_c1, hdr_c2, hdr_c3 = st.columns([2.15, 1.05, 1.05], gap="small")
                with hdr_c1:
                    st.markdown(
                        _html(f"""
                        <div class="tds-todo-hdr-left">
                            <span class="tds-todo-main-title">Today To Do</span>
                            <span class="tds-todo-cnt-pill">{total_ev_cnt}건</span>
                        </div>
                        """),
                        unsafe_allow_html=True,
                    )
                with hdr_c2:
                    urg_on = bool(cstate.get("urgent_first", False))
                    if st.button(
                        "중요 우선",
                        width="stretch",
                        key="btn_todo_hdr_urgent",
                    ):
                        cstate["urgent_first"] = not urg_on
                        st.rerun()
                with hdr_c3:
                    hide_on = bool(cstate.get("hide_completed", False))
                    if st.button(
                        "완료 숨김",
                        width="stretch",
                        key="btn_todo_hdr_hide",
                    ):
                        cstate["hide_completed"] = not hide_on
                        st.rerun()

                st.markdown(
                    _html(f"""
                    <div class="tds-todo-progress-track">
                        <div class="tds-todo-progress-fill" style="width:{prog_pct}%;"></div>
                    </div>
                    """),
                    unsafe_allow_html=True,
                )

                if not visible_evs:
                    st.markdown(
                        _html("""
                        <div class="tds-empty-todo-box">
                            <div class="tds-empty-chk-circle">
                                <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
                                    <path d="M5 12.5L9.5 17L19 7.5" stroke="#3182F6" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round"/>
                                </svg>
                            </div>
                            <div class="tds-empty-title">등록된 오늘 할 일이 없어요</div>
                            <div class="tds-empty-sub">아래 입력칸에 할 일을 적고 Tab으로 시간(시:분) 입력 후 Enter를 쳐보세요</div>
                        </div>
                        """),
                        unsafe_allow_html=True,
                    )
                else:
                    BELL_SVG = """
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                        <path d="M12 22c1.1 0 2-.9 2-2h-4c0 1.1.9 2 2 2zm6-6v-5c0-3.07-1.63-5.64-4.5-6.32V4c0-.83-.67-1.5-1.5-1.5s-1.5.67-1.5 1.5v.68C7.64 5.36 6 7.92 6 11v5l-2 2v1h16v-1l-2-2z"/>
                    </svg>
                    """
                    CHK_SVG = """
                    <svg width="13" height="13" viewBox="0 0 14 14" fill="none">
                        <path d="M2.5 7.2L5.6 10.3L11.5 3.8" stroke="#FFFFFF" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round"/>
                    </svg>
                    """
                    for idx_e, ev in enumerate(visible_evs):
                        ev_id_str = str(ev.get("id", f"ev_{idx_e}"))
                        is_done = bool(ev.get("done", False))
                        ev_title_esc = _html_lib.escape(str(ev.get("title", "")))
                        t_norm = _normalize_time_str(str(ev.get("time", "")))

                        subs = ev.get("sub_tasks", []) or []
                        sub_badge_html = ""
                        if subs:
                            s_done = sum(1 for s in subs if s.get("done"))
                            sub_badge_html = f"<span class='tds-sub-progress-pill'>{s_done}/{len(subs)}</span>"

                        urg_badge_html = "<span class='tds-urgent-pill'>중요</span>" if ev.get("urgent") else ""

                        has_dtl = bool(ev.get("has_detail") or subs)
                        dtl_circle_html = "<span class='tds-blue-circle-dtl'>상세</span>" if has_dtl else ""

                        bell_html = ""
                        if ev.get("alarm"):
                            sparkle_cls = "sparkle" if _is_alarm_due(ev, is_sel_today) else ""
                            bell_html = f"<span class='tds-bell-pure {sparkle_cls}' data-alarm-time='{_html_lib.escape(t_norm)}'>{BELL_SVG}</span>"

                        time_html = (
                            f"<span class='tds-compact-time {'done' if is_done else ''}'>{_html_lib.escape(t_norm)}</span>"
                            if t_norm
                            else ""
                        )

                        chk_box_html = (
                            f"<span class='tds-sq-chk checked'>{CHK_SVG}</span>"
                            if is_done
                            else "<span class='tds-sq-chk'></span>"
                        )

                        st.markdown(
                            _html(f"""
                            <div class="tds-todo-card-pure {'done-card' if is_done else ''}">
                                <span class="tds-corner-x-circle">✕</span>
                                <div class="tds-todo-card-left">
                                    {chk_box_html}
                                    <div class="tds-todo-title-wrap">
                                        <span class="tds-todo-title-txt {'done' if is_done else ''}">{ev_title_esc}</span>
                                        {dtl_circle_html}
                                        {sub_badge_html}
                                        {urg_badge_html}
                                    </div>
                                </div>
                                <div class="tds-todo-card-right">
                                    {bell_html}
                                    {time_html}
                                </div>
                            </div>
                            """),
                            unsafe_allow_html=True,
                        )

                        with st.container(key=f"todo_hit_row_{ev_id_str}_{idx_e}"):
                            h_chk, h_body, h_del = st.columns([0.55, 3.95, 0.45], gap="small")
                            with h_chk:
                                if st.button(
                                    "체크",
                                    key=f"btn_todo_chk_{ev_id_str}_{idx_e}",
                                    width="stretch",
                                ):
                                    ev["done"] = not is_done
                                    ev["type"] = "DONE" if ev["done"] else ("TAX" if ev.get("category") == "세무기한" else "MY")
                                    st.rerun()
                            with h_body:
                                if st.button(
                                    "상세",
                                    key=f"btn_todo_dtl_{ev_id_str}_{idx_e}",
                                    width="stretch",
                                ):
                                    _open_schedule_detail_dialog(year, month, selected_day, ev_id_str)
                            with h_del:
                                if st.button(
                                    "삭제",
                                    key=f"btn_todo_del_{ev_id_str}_{idx_e}",
                                    width="stretch",
                                ):
                                    month_schedules[selected_day] = [
                                        x for x in raw_day_evs if str(x.get("id")) != ev_id_str
                                    ]
                                    st.rerun()

            # ══════ 하단 고정 영역: 5개 컬럼 고정 (할 일 → 시간 → [알림]/[달력] 클릭 후 바로 Enter 치면 즉시 등록!) ══════
            with st.container(key="todo_bottom_dock_a"):
                d_c1, d_c2, d_c3, d_c4, d_c5 = st.columns([2.20, 0.92, 0.78, 0.78, 0.78], gap="small")
                inp_key = f"dock_chat_inp_{year}_{month}_{selected_day}"
                time_key = f"dock_time_inp_{year}_{month}_{selected_day}"

                with d_c1:
                    with st.container(key=f"dock_chat_wrap_{year}_{month}_{selected_day}"):
                        st.text_input(
                            "할 일 입력",
                            placeholder="",
                            label_visibility="collapsed",
                            key=inp_key,
                            on_change=_commit_dock_schedule_on_enter,
                        )
                with d_c2:
                    with st.container(key=f"dock_time_wrap_{year}_{month}_{selected_day}"):
                        st.text_input(
                            "시간 입력",
                            placeholder=":",
                            label_visibility="collapsed",
                            key=time_key,
                        )
                with d_c3:
                    if st.button(
                        "알림",
                        width="stretch",
                        key=f"btn_dock_alarm_{year}_{month}_{selected_day}",
                    ):
                        cstate["dock_alarm"] = not bool(cstate.get("dock_alarm", False))
                with d_c4:
                    if st.button(
                        "달력",
                        width="stretch",
                        key=f"btn_dock_cal_{year}_{month}_{selected_day}",
                    ):
                        cstate["dock_cal"] = not bool(cstate.get("dock_cal", False))
                with d_c5:
                    if st.button(
                        "상세",
                        width="stretch",
                        key=f"btn_dock_detail_{year}_{month}_{selected_day}",
                    ):
                        cstate["dock_dtl"] = False
                        new_id = f"dtl_{int(datetime.now().timestamp() * 1000)}"
                        _open_schedule_detail_dialog(year, month, selected_day, new_id)

    render_floating_kakao_todo_overlay()


def render_floating_kakao_todo_overlay() -> None:
    """
    1) 할일 입력 → 시간 입력 → [알림] 또는 [달력] 클릭 후 바로 Enter를 치더라도,
       버튼 클릭이 취소되지 않고 즉시 할일이 상단 Today To Do에 등록되도록 전역 Enter 핸들러 적용
    2) 상세 모달 오픈 시 주변 배경이 어두워지지 않도록(투명 유지) 처리하고 모달 바탕은 푸른색(#E8F3FF), 입력칸은 흰색(#FFFFFF)으로 스타일링
    """
    cstate = _init_calendar_state()
    todos = cstate.get("kakao_todos", [])
    panel_open_init = bool(cstate.get("panel_open", False))
    silent_cnt = int(cstate.get("silent_read_count", 2))
    dock_reset_seq = int(cstate.get("dock_reset_seq", 0))
    dock_ctx_key = f"{cstate.get('year')}_{cstate.get('month')}_{cstate.get('selected_day')}_{dock_reset_seq}"
    kst_today_iso = get_kst_today().isoformat()
    user_nm = str(st.session_state.get("current_workspace") or "범준").strip() or "범준"
    if user_nm.startswith("익명"):
        user_nm = "범준"

    todos_json = json.dumps(todos, ensure_ascii=False)
    init_open_js = "true" if panel_open_init else "false"
    user_nm_json = json.dumps(user_nm, ensure_ascii=False)
    kst_iso_json = json.dumps(kst_today_iso, ensure_ascii=False)
    dock_ctx_json = json.dumps(dock_ctx_key, ensure_ascii=False)

    components.html(
        f"""
        <div id="tds-cal-iframe-marker" style="display:none;"></div>
        <script>
        (function() {{
            const parentWin = window.parent;
            const parentDoc = parentWin.document;
            const frameEl = window.frameElement;
            const TODOS_DATA = {todos_json};
            const INIT_OPEN = {init_open_js};
            const CURRENT_USER = {user_nm_json};
            const SILENT_CNT = {silent_cnt};
            const SERVER_KST_ISO = {kst_iso_json};
            const DOCK_CTX_KEY = {dock_ctx_json};

            if (parentWin._tdsCalCleanupTimer) {{
                parentWin.clearInterval(parentWin._tdsCalCleanupTimer);
                parentWin._tdsCalCleanupTimer = null;
            }}

            if (!parentWin._tdsDockToggleState || parentWin._tdsDockToggleState.ctxKey !== DOCK_CTX_KEY) {{
                parentWin._tdsDockToggleState = {{
                    ctxKey: DOCK_CTX_KEY,
                    alarm: false,
                    cal: false,
                    dtl: false,
                    hourStr: "",
                    minStr: "",
                    allowEnterCommit: false
                }};
            }} else {{
                if (!parentDoc.querySelector('div[data-testid="stDialog"]')) {{
                    parentWin._tdsDockToggleState.dtl = false;
                }}
            }}

            function stripDockTokenSuffix(val) {{
                return String(val || "")
                    .replace(/__ENTER_COMMIT_TGL_A[01]_C[01](?:_T[0-9:]*)?__$/, "")
                    .replace(/__DTL_OPEN_TGL_A[01]_C[01](?:_T[0-9:]*)?__$/, "")
                    .replace(/__TGL_A[01]_C[01](?:_T[0-9:]*)?__$/, "");
            }}

            function sanitizeHourDigits(raw) {{
                let d = String(raw || "").replace(/[^0-9]/g, "").slice(0, 2);
                if (d.length === 2) {{
                    let n = parseInt(d, 10);
                    if (n > 23) d = "23";
                }}
                return d;
            }}

            function sanitizeMinDigits(raw) {{
                let d = String(raw || "").replace(/[^0-9]/g, "").slice(0, 2);
                if (d.length === 2) {{
                    let n = parseInt(d, 10);
                    if (n > 59) d = "59";
                }}
                return d;
            }}

            function formatDualTimeForCommit(hRaw, mRaw) {{
                const h = sanitizeHourDigits(hRaw);
                const m = sanitizeMinDigits(mRaw);
                if (!h && !m) return "";
                const hh = h ? String(Math.min(23, Math.max(0, parseInt(h, 10)))).padStart(2, "0") : "00";
                const mm = m ? String(Math.min(59, Math.max(0, parseInt(m, 10)))).padStart(2, "0") : "00";
                return `${{hh}}:${{mm}}`;
            }}

            function applyButtonVisualState(btn, isSunken) {{
                if (!btn) return;
                btn.removeAttribute("title");
                btn.style.setProperty("width", "100%", "important");
                btn.style.setProperty("height", "40px", "important");
                btn.style.setProperty("min-height", "40px", "important");
                btn.style.setProperty("border-radius", "10px", "important");
                btn.style.setProperty("font-size", "0.78rem", "important");
                btn.style.setProperty("font-weight", "800", "important");
                btn.style.setProperty("color", "#FFFFFF", "important");
                if (isSunken) {{
                    btn.classList.add("tds-dock-btn-sunken");
                    btn.style.setProperty("background", "#1854BA", "important");
                    btn.style.setProperty("background-color", "#1854BA", "important");
                    btn.style.setProperty("border", "2px solid #0F3882", "important");
                    btn.style.setProperty("box-shadow", "inset 0 4px 7px rgba(10, 32, 78, 0.65), inset 0 1px 2px rgba(10, 32, 78, 0.85)", "important");
                    btn.style.setProperty("padding-top", "3px", "important");
                }} else {{
                    btn.classList.remove("tds-dock-btn-sunken");
                    btn.style.setProperty("background", "#3182F6", "important");
                    btn.style.setProperty("background-color", "#3182F6", "important");
                    btn.style.setProperty("border", "none", "important");
                    btn.style.setProperty("box-shadow", "none", "important");
                    btn.style.setProperty("padding-top", "0px", "important");
                }}
            }}

            function readCurrentDualTimeFromDOM() {{
                const dState = parentWin._tdsDockToggleState;
                const dualBox = parentDoc.querySelector(".tds-dual-time-box");
                if (dualBox) {{
                    const hEl = dualBox.querySelector(".tds-hour-inp");
                    const mEl = dualBox.querySelector(".tds-min-inp");
                    if (hEl) dState.hourStr = sanitizeHourDigits(hEl.value);
                    if (mEl) dState.minStr = sanitizeMinDigits(mEl.value);
                }}
                return formatDualTimeForCommit(dState.hourStr, dState.minStr);
            }}

            function triggerReactCommitPayload(chatInp, modeTag) {{
                if (!chatInp) return;
                const dState = parentWin._tdsDockToggleState;
                const rawTitle = stripDockTokenSuffix(chatInp.value || "").trim();
                if (modeTag === "ENTER" && !rawTitle) return;

                const aBit = dState.alarm ? "1" : "0";
                const cBit = dState.cal ? "1" : "0";
                const timeFormatted = readCurrentDualTimeFromDOM();
                const prefix = modeTag === "DETAIL" ? "__DTL_OPEN_TGL_" : "__ENTER_COMMIT_TGL_";
                const encodedVal = rawTitle + `${{prefix}}A${{aBit}}_C${{cBit}}_T${{timeFormatted}}__`;

                dState.allowEnterCommit = true;
                const nativeSetter = Object.getOwnPropertyDescriptor(parentWin.HTMLInputElement.prototype, "value").set;
                nativeSetter.call(chatInp, encodedVal);
                chatInp.dispatchEvent(new Event("input", {{ bubbles: true }}));

                if (modeTag === "ENTER") {{
                    dState.alarm = false;
                    dState.cal = false;
                    dState.dtl = false;
                    dState.hourStr = "";
                    dState.minStr = "";
                    const dualBox = parentDoc.querySelector(".tds-dual-time-box");
                    if (dualBox) {{
                        const hEl = dualBox.querySelector(".tds-hour-inp");
                        const mEl = dualBox.querySelector(".tds-min-inp");
                        if (hEl) hEl.value = "";
                        if (mEl) mEl.value = "";
                    }}
                }} else {{
                    dState.dtl = false;
                }}

                setTimeout(function() {{
                    chatInp.focus();
                    chatInp.dispatchEvent(new KeyboardEvent("keydown", {{
                        key: "Enter",
                        code: "Enter",
                        keyCode: 13,
                        which: 13,
                        bubbles: true,
                        cancelable: true
                    }}));
                    setTimeout(function() {{ dState.allowEnterCommit = false; }}, 350);
                }}, 25);
            }}

            function bindMonthArrowButtons() {{
                const prevBtn = parentDoc.getElementById("tds-cal-prev-month-btn");
                const nextBtn = parentDoc.getElementById("tds-cal-next-month-btn");
                if (prevBtn && !prevBtn._boundClick) {{
                    prevBtn._boundClick = true;
                    prevBtn.addEventListener("click", function(e) {{
                        e.preventDefault();
                        e.stopPropagation();
                        const stPrev = parentDoc.querySelector('.st-key-btn_cal_m_prev button');
                        if (stPrev) stPrev.click();
                    }});
                }}
                if (nextBtn && !nextBtn._boundClick) {{
                    nextBtn._boundClick = true;
                    nextBtn.addEventListener("click", function(e) {{
                        e.preventDefault();
                        e.stopPropagation();
                        const stNext = parentDoc.querySelector('.st-key-btn_cal_m_next button');
                        if (stNext) stNext.click();
                    }});
                }}
            }}

            function mountSplitTimeBox(dockEl, chatInp) {{
                const timeWrap = dockEl.querySelector('[class*="st-key-dock_time_wrap_"] [data-testid="stTextInput"] > div > div');
                const origTimeInp = dockEl.querySelector('[class*="st-key-dock_time_wrap_"] input:not(.tds-time-part-inp)');
                if (!timeWrap || !origTimeInp) return null;

                origTimeInp.style.setProperty("display", "none", "important");
                origTimeInp.tabIndex = -1;

                const dState = parentWin._tdsDockToggleState;
                let dualBox = timeWrap.querySelector(".tds-dual-time-box");
                if (!dualBox) {{
                    dualBox = parentDoc.createElement("div");
                    dualBox.className = "tds-dual-time-box";
                    dualBox.innerHTML = `
                        <input type="text" class="tds-time-part-inp tds-hour-inp" inputmode="numeric" maxlength="2" placeholder="" autocomplete="off" spellcheck="false" />
                        <span class="tds-time-colon">:</span>
                        <input type="text" class="tds-time-part-inp tds-min-inp" inputmode="numeric" maxlength="2" placeholder="" autocomplete="off" spellcheck="false" />
                    `;
                    timeWrap.appendChild(dualBox);

                    const hourInp = dualBox.querySelector(".tds-hour-inp");
                    const minInp = dualBox.querySelector(".tds-min-inp");
                    hourInp.value = dState.hourStr || "";
                    minInp.value = dState.minStr || "";

                    function syncTimeState() {{
                        hourInp.value = sanitizeHourDigits(hourInp.value);
                        minInp.value = sanitizeMinDigits(minInp.value);
                        dState.hourStr = hourInp.value;
                        dState.minStr = minInp.value;
                    }}

                    // 한글(IME)·영문·특수문자 원천 차단 및 숫자 전용 필터링
                    [hourInp, minInp].forEach((inp, idx) => {{
                        inp.addEventListener("compositionstart", function() {{
                            this.value = this.value.replace(/[^0-9]/g, "");
                        }});
                        inp.addEventListener("compositionupdate", function() {{
                            this.value = this.value.replace(/[^0-9]/g, "");
                        }});
                        inp.addEventListener("compositionend", function() {{
                            syncTimeState();
                        }});
                        inp.addEventListener("input", function() {{
                            syncTimeState();
                        }});
                        inp.addEventListener("keydown", function(ev) {{
                            if (ev.key === "Enter" && !ev.isComposing) {{
                                ev.preventDefault();
                                ev.stopPropagation();
                                ev.stopImmediatePropagation();
                                syncTimeState();
                                const curChatInp = parentDoc.querySelector('.st-key-todo_bottom_dock_a [class*="st-key-dock_chat_wrap_"] input');
                                triggerReactCommitPayload(curChatInp || chatInp, "ENTER");
                                return;
                            }}
                            if (idx === 0 && ((ev.key === "Tab" && !ev.shiftKey) || ev.key === ":" || (ev.key === "ArrowRight" && this.selectionStart === this.value.length))) {{
                                ev.preventDefault();
                                ev.stopPropagation();
                                ev.stopImmediatePropagation();
                                syncTimeState();
                                minInp.focus();
                                minInp.select();
                                return;
                            }}
                            if (idx === 1 && ((ev.key === "Tab" && ev.shiftKey) || (ev.key === "ArrowLeft" && this.selectionStart === 0) || (ev.key === "Backspace" && this.value.length === 0))) {{
                                ev.preventDefault();
                                ev.stopPropagation();
                                ev.stopImmediatePropagation();
                                hourInp.focus();
                                hourInp.select();
                                return;
                            }}
                            const allowedKeys = ["Backspace", "Delete", "Tab", "ArrowLeft", "ArrowRight", "Home", "End"];
                            if (allowedKeys.indexOf(ev.key) >= 0 || ev.ctrlKey || ev.metaKey) {{
                                return;
                            }}
                            if (!/^[0-9]$/.test(ev.key)) {{
                                ev.preventDefault();
                                ev.stopPropagation();
                                return;
                            }}
                            if (idx === 0 && this.value.length >= 2 && this.selectionStart === this.selectionEnd) {{
                                ev.preventDefault();
                                ev.stopPropagation();
                                minInp.focus();
                                minInp.value = sanitizeMinDigits(ev.key);
                                syncTimeState();
                            }}
                        }}, true);
                    }});
                }}
                return dualBox;
            }}

            // 전역 문서 캡처 핸들러:
            // 1) [알림], [달력] 버튼 클릭 시:
            //    - mousedown에서 preventDefault()로 포커스가 버튼에 갇히지 않게 하고
            //    - click에서 Sunken 입체 토글 후 포커스를 할 일 입력칸(또는 시간칸)으로 유지하여
            //      그 상태에서 바로 Enter를 치면 버튼이 취소되지 않고 즉시 할 일이 등록되게 함!
            if (parentWin._tdsGlobalDocMousedownHandler) {{
                parentDoc.removeEventListener("mousedown", parentWin._tdsGlobalDocMousedownHandler, true);
            }}
            parentWin._tdsGlobalDocMousedownHandler = function(ev) {{
                const t = ev.target;
                if (!t || !t.closest) return;
                const dockEl = parentDoc.querySelector('.st-key-todo_bottom_dock_a');
                if (!dockEl || !dockEl.contains(t)) return;
                const isDockBtn = t.closest('[class*="st-key-btn_dock_alarm_"] button, [class*="st-key-btn_dock_cal_"] button, [class*="st-key-btn_dock_detail_"] button');
                if (isDockBtn) {{
                    ev.preventDefault();
                }}
            }};
            parentDoc.addEventListener("mousedown", parentWin._tdsGlobalDocMousedownHandler, true);

            if (parentWin._tdsGlobalDocClickHandler) {{
                parentDoc.removeEventListener("click", parentWin._tdsGlobalDocClickHandler, true);
            }}
            parentWin._tdsGlobalDocClickHandler = function(ev) {{
                const t = ev.target;
                if (!t || !t.closest) return;
                const dockEl = parentDoc.querySelector('.st-key-todo_bottom_dock_a');
                if (!dockEl || !dockEl.contains(t)) return;

                const dState = parentWin._tdsDockToggleState;
                const alarmBtn = t.closest('[class*="st-key-btn_dock_alarm_"] button');
                if (alarmBtn) {{
                    ev.preventDefault();
                    ev.stopPropagation();
                    ev.stopImmediatePropagation();
                    dState.alarm = !dState.alarm;
                    applyButtonVisualState(alarmBtn, dState.alarm);
                    return;
                }}

                const calBtn = t.closest('[class*="st-key-btn_dock_cal_"] button');
                if (calBtn) {{
                    ev.preventDefault();
                    ev.stopPropagation();
                    ev.stopImmediatePropagation();
                    dState.cal = !dState.cal;
                    applyButtonVisualState(calBtn, dState.cal);
                    return;
                }}

                const dtlBtn = t.closest('[class*="st-key-btn_dock_detail_"] button');
                if (dtlBtn) {{
                    ev.preventDefault();
                    ev.stopPropagation();
                    ev.stopImmediatePropagation();
                    const chatInp = dockEl.querySelector('[class*="st-key-dock_chat_wrap_"] input');
                    triggerReactCommitPayload(chatInp, "DETAIL");
                    return;
                }}
            }};
            parentDoc.addEventListener("click", parentWin._tdsGlobalDocClickHandler, true);

            // 전역 Enter 키 캡처 핸들러:
            // 할일 입력 → 시간 입력 → [알림]/[달력] 버튼 클릭 직후 마우스를 다시 입력칸에 대지 않고
            // 바로 Enter 키를 쳐도 버튼이 취소되지 않고 즉시 할일이 등록되도록 보장!
            if (parentWin._tdsGlobalDocKeydownHandler) {{
                parentDoc.removeEventListener("keydown", parentWin._tdsGlobalDocKeydownHandler, true);
            }}
            parentWin._tdsGlobalDocKeydownHandler = function(ev) {{
                if (ev.key !== "Enter" || ev.isComposing) return;
                const dState = parentWin._tdsDockToggleState;
                if (dState && dState.allowEnterCommit) return;

                // 모달 창이 열려 있을 때는 모달 내부 동작 우선
                if (parentDoc.querySelector('div[data-testid="stDialog"]')) return;

                const dockEl = parentDoc.querySelector('.st-key-todo_bottom_dock_a');
                if (!dockEl) return;
                const chatInp = dockEl.querySelector('[class*="st-key-dock_chat_wrap_"] input');
                if (!chatInp) return;

                const rawTitle = stripDockTokenSuffix(chatInp.value || "").trim();
                const activeEl = parentDoc.activeElement;
                const isInsideDock = activeEl && dockEl.contains(activeEl);
                const isBodyOrNonInput = !activeEl || activeEl === parentDoc.body || (activeEl.tagName !== "INPUT" && activeEl.tagName !== "TEXTAREA" && activeEl.tagName !== "SELECT");

                if (rawTitle && (isInsideDock || isBodyOrNonInput)) {{
                    ev.preventDefault();
                    ev.stopPropagation();
                    ev.stopImmediatePropagation();
                    triggerReactCommitPayload(chatInp, "ENTER");
                }}
            }};
            parentDoc.addEventListener("keydown", parentWin._tdsGlobalDocKeydownHandler, true);

            if (parentWin._tdsGlobalBlurHandler) {{
                ["focusout", "blur", "change"].forEach(evtName => {{
                    parentDoc.removeEventListener(evtName, parentWin._tdsGlobalBlurHandler, true);
                }});
            }}
            parentWin._tdsGlobalBlurHandler = function(ev) {{
                const t = ev.target;
                if (t && t.closest && t.closest('[class*="st-key-dock_chat_wrap_"]')) {{
                    if (!parentWin._tdsDockToggleState.allowEnterCommit) {{
                        ev.stopPropagation();
                        ev.stopImmediatePropagation();
                    }}
                }}
            }};
            ["focusout", "blur", "change"].forEach(evtName => {{
                parentDoc.addEventListener(evtName, parentWin._tdsGlobalBlurHandler, true);
            }});

            function bindDockMultiToggleAndKeys() {{
                bindMonthArrowButtons();

                const dockEl = parentDoc.querySelector('.st-key-todo_bottom_dock_a');
                if (!dockEl) return;

                parentDoc.querySelectorAll('[data-testid="InputInstructions"]').forEach(el => {{
                    el.style.display = "none";
                    el.remove();
                }});
                dockEl.querySelectorAll('[data-testid="stTooltipHoverTarget"]').forEach(el => {{
                    el.removeAttribute("title");
                }});

                const dState = parentWin._tdsDockToggleState;
                const alarmBtn = dockEl.querySelector('[class*="st-key-btn_dock_alarm_"] button');
                const calBtn = dockEl.querySelector('[class*="st-key-btn_dock_cal_"] button');
                const dtlBtn = dockEl.querySelector('[class*="st-key-btn_dock_detail_"] button');
                const chatInp = dockEl.querySelector('[class*="st-key-dock_chat_wrap_"] input');

                const dualBox = mountSplitTimeBox(dockEl, chatInp);
                const hourInp = dualBox ? dualBox.querySelector(".tds-hour-inp") : null;

                if (chatInp && !dState.allowEnterCommit) {{
                    const stripped = stripDockTokenSuffix(chatInp.value || "");
                    if (stripped !== chatInp.value) {{
                        const nativeSetter = Object.getOwnPropertyDescriptor(parentWin.HTMLInputElement.prototype, "value").set;
                        nativeSetter.call(chatInp, stripped);
                        chatInp.dispatchEvent(new Event("input", {{ bubbles: true }}));
                    }}
                }}

                const isDialogOpen = !!parentDoc.querySelector('div[data-testid="stDialog"]');
                dState.dtl = isDialogOpen;

                applyButtonVisualState(alarmBtn, dState.alarm);
                applyButtonVisualState(calBtn, dState.cal);
                applyButtonVisualState(dtlBtn, isDialogOpen);

                if (chatInp && !chatInp._boundStrictEnterV10) {{
                    chatInp._boundStrictEnterV10 = true;
                    chatInp.addEventListener("keydown", function(ev) {{
                        if (ev.key === "Tab" && !ev.shiftKey) {{
                            ev.preventDefault();
                            ev.stopPropagation();
                            ev.stopImmediatePropagation();
                            const curDual = dockEl.querySelector(".tds-hour-inp") || hourInp;
                            if (curDual) {{
                                curDual.focus();
                                curDual.select();
                            }}
                        }} else if (ev.key === "Enter" && !ev.isComposing) {{
                            if (!dState.allowEnterCommit) {{
                                ev.preventDefault();
                                ev.stopPropagation();
                                ev.stopImmediatePropagation();
                                triggerReactCommitPayload(chatInp, "ENTER");
                            }}
                        }}
                    }}, true);
                }}
            }}

            bindDockMultiToggleAndKeys();
            setTimeout(bindDockMultiToggleAndKeys, 120);
            setTimeout(bindDockMultiToggleAndKeys, 350);

            // ══════ [2]-2 우측 하단 플로팅 홈버튼 & 직각 네모 말풍선 & 60% To-Do 오버레이 ══════
            let styleEl = parentDoc.getElementById("tds-kakao-floating-style");
            if (!styleEl) {{
                styleEl = parentDoc.createElement("style");
                styleEl.id = "tds-kakao-floating-style";
                parentDoc.head.appendChild(styleEl);
            }}
            styleEl.textContent = `
                @keyframes tossPulseRing {{
                    0% {{
                        box-shadow: 0 0 0 0 rgba(49, 130, 246, 0.45), 0 14px 28px -6px rgba(49, 130, 246, 0.45);
                    }}
                    70% {{
                        box-shadow: 0 0 0 16px rgba(49, 130, 246, 0), 0 14px 28px -6px rgba(49, 130, 246, 0.45);
                    }}
                    100% {{
                        box-shadow: 0 0 0 0 rgba(49, 130, 246, 0), 0 14px 28px -6px rgba(49, 130, 246, 0.45);
                    }}
                }}
                @keyframes cuteWinkBounce {{
                    0%, 100% {{ transform: translateY(0px) rotate(0deg); }}
                    50% {{ transform: translateY(-2px) rotate(2deg); }}
                }}
                @keyframes squareBubblePop {{
                    0% {{ opacity: 0; transform: translateY(12px) scale(0.94); }}
                    100% {{ opacity: 1; transform: translateY(0px) scale(1); }}
                }}

                #tds-kakao-floating-root {{
                    position: fixed;
                    right: 20px;
                    bottom: 60px;
                    z-index: 999990;
                    font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, 'Apple SD Gothic Neo', 'Malgun Gothic', sans-serif;
                    letter-spacing: -0.02em;
                    display: flex;
                    flex-direction: column;
                    align-items: flex-end;
                    user-select: none;
                    touch-action: none;
                }}

                #tds-kakao-backdrop {{
                    position: fixed;
                    inset: 0;
                    background: rgba(25, 31, 40, 0.14);
                    backdrop-filter: blur(1.5px);
                    opacity: 0;
                    pointer-events: none;
                    transition: opacity 0.26s ease;
                    z-index: 999985;
                }}
                #tds-kakao-backdrop.open {{
                    opacity: 1;
                    pointer-events: auto;
                }}

                #tds-kakao-todo-panel {{
                    position: fixed;
                    right: 20px;
                    bottom: 136px;
                    width: min(60vw, 920px);
                    height: min(64vh, 640px);
                    min-width: 340px;
                    min-height: 430px;
                    background: #FFFFFF;
                    border: 1px solid #E5E8EB;
                    border-radius: 26px;
                    box-shadow: 0 24px 64px -12px rgba(0, 27, 55, 0.24), 0 0 0 1px rgba(0, 27, 55, 0.04);
                    transform-origin: bottom right;
                    transform: scale(0.06);
                    opacity: 0;
                    pointer-events: none;
                    transition: transform 0.36s cubic-bezier(0.16, 1, 0.3, 1), opacity 0.24s ease;
                    z-index: 999995;
                    display: flex;
                    flex-direction: column;
                    overflow: hidden;
                }}
                #tds-kakao-todo-panel.open {{
                    transform: scale(1);
                    opacity: 1;
                    pointer-events: auto;
                }}

                .tds-kp-header {{
                    background: #FFFFFF;
                    border-bottom: 1px solid #E5E8EB;
                    padding: 16px 24px;
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    flex-shrink: 0;
                }}
                .tds-kp-hdr-l {{
                    display: flex;
                    align-items: center;
                    gap: 12px;
                }}
                .tds-kp-char-circle {{
                    width: 40px;
                    height: 40px;
                    border-radius: 13px;
                    background: #3898FF;
                    color: #FFFFFF;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    flex-shrink: 0;
                }}
                .tds-kp-title-row {{
                    display: flex;
                    align-items: center;
                    gap: 8px;
                }}
                .tds-kp-title {{
                    font-size: 1.08rem;
                    font-weight: 800;
                    color: #191F28;
                }}
                .tds-kp-pill-60 {{
                    font-size: 0.70rem;
                    font-weight: 800;
                    background: #E8F3FF;
                    color: #3182F6;
                    padding: 2px 10px;
                    border-radius: 999px;
                    border: none;
                    font-variant-numeric: tabular-nums;
                }}
                .tds-kp-sub {{
                    font-size: 0.76rem;
                    color: #8B95A1;
                    font-weight: 600;
                    margin-top: 2px;
                }}
                .tds-kp-hdr-r {{
                    display: flex;
                    align-items: center;
                    gap: 8px;
                }}
                .tds-kp-approve-all-btn {{
                    padding: 8px 16px;
                    border-radius: 10px;
                    background: #3182F6;
                    color: #FFFFFF;
                    border: none;
                    font-size: 0.78rem;
                    font-weight: 800;
                    cursor: pointer;
                    transition: background 0.15s ease;
                }}
                .tds-kp-approve-all-btn:hover {{
                    background: #1B64DA;
                }}
                .tds-kp-close-btn {{
                    width: 36px;
                    height: 36px;
                    border-radius: 10px;
                    background: #F2F4F6;
                    border: none;
                    color: #4E5968;
                    font-weight: 700;
                    cursor: pointer;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                }}
                .tds-kp-close-btn:hover {{
                    background: #E5E8EB;
                    color: #191F28;
                }}

                .tds-kp-tabs-bar {{
                    background: #FFFFFF;
                    border-bottom: 1px solid #F2F4F6;
                    padding: 12px 24px;
                    display: flex;
                    flex-wrap: wrap;
                    align-items: center;
                    justify-content: space-between;
                    gap: 8px;
                    flex-shrink: 0;
                }}
                .tds-kp-tabs-l {{
                    display: flex;
                    align-items: center;
                    gap: 6px;
                    flex-wrap: wrap;
                }}
                .tds-kp-tab {{
                    padding: 6px 14px;
                    border-radius: 999px;
                    font-size: 0.78rem;
                    font-weight: 700;
                    border: none;
                    cursor: pointer;
                    transition: all 0.15s ease;
                    font-variant-numeric: tabular-nums;
                }}
                .tds-kp-tab.all {{ background: #E8F3FF; color: #3182F6; font-weight: 800; }}
                .tds-kp-tab.working {{ background: #FFF5E5; color: #D97706; }}
                .tds-kp-tab.ready {{ background: #FFEEEE; color: #F04452; }}
                .tds-kp-tab.approved {{ background: #E5F9F0; color: #00A660; }}
                .tds-kp-tab.active-ring {{
                    outline: 2px solid #3182F6;
                    outline-offset: 1px;
                }}
                .tds-kp-silent-info {{
                    font-size: 0.74rem;
                    color: #8B95A1;
                    font-weight: 700;
                    font-variant-numeric: tabular-nums;
                }}
                .tds-kp-silent-info b {{
                    color: #3182F6;
                }}

                .tds-kp-body {{
                    flex: 1;
                    overflow-y: auto;
                    padding: 20px;
                    background: #F4F6FA;
                    display: flex;
                    flex-direction: column;
                    gap: 12px;
                }}
                .tds-kp-card {{
                    background: #FFFFFF;
                    border-radius: 20px;
                    border: 1px solid #E5E8EB;
                    padding: 20px;
                    box-shadow: 0 2px 10px rgba(0, 27, 55, 0.04);
                    transition: box-shadow 0.15s ease;
                }}
                .tds-kp-card:hover {{
                    box-shadow: 0 6px 18px rgba(49, 130, 246, 0.10);
                }}
                .tds-kp-card-top {{
                    display: flex;
                    flex-wrap: wrap;
                    align-items: center;
                    justify-content: space-between;
                    gap: 8px;
                    margin-bottom: 10px;
                }}
                .tds-kp-card-badges {{
                    display: flex;
                    align-items: center;
                    gap: 8px;
                    flex-wrap: wrap;
                }}
                .tds-kp-st-badge {{
                    display: inline-flex;
                    align-items: center;
                    gap: 6px;
                    padding: 4px 12px;
                    border-radius: 999px;
                    border: none;
                    font-size: 0.74rem;
                    font-weight: 800;
                }}
                .tds-kp-st-badge.working {{ background: #FFF5E5; color: #D97706; }}
                .tds-kp-st-badge.ready {{ background: #FFEEEE; color: #F04452; }}
                .tds-kp-st-badge.approved {{ background: #E5F9F0; color: #00A660; }}
                .tds-kp-cat-pill {{
                    font-size: 0.75rem;
                    font-weight: 700;
                    color: #4E5968;
                    background: #F2F4F6;
                    padding: 2px 10px;
                    border-radius: 999px;
                    border: none;
                }}
                .tds-kp-time {{
                    font-size: 0.74rem;
                    color: #8B95A1;
                    font-weight: 600;
                    font-variant-numeric: tabular-nums;
                }}
                .tds-kp-company {{
                    font-size: 0.82rem;
                    font-weight: 800;
                    color: #3182F6;
                }}
                .tds-kp-card-title {{
                    font-size: 0.95rem;
                    font-weight: 800;
                    color: #191F28;
                    margin-bottom: 8px;
                }}
                .tds-kp-kakao-orig {{
                    font-size: 0.78rem;
                    color: #4E5968;
                    background: #F4F6FA;
                    padding: 10px 14px;
                    border-radius: 14px;
                    margin-bottom: 8px;
                    font-weight: 600;
                }}
                .tds-kp-ai-res {{
                    font-size: 0.80rem;
                    color: #191F28;
                    background: #E8F3FF;
                    padding: 10px 14px;
                    border-radius: 14px;
                    white-space: pre-line;
                    line-height: 1.55;
                    margin-bottom: 12px;
                    font-weight: 600;
                    font-variant-numeric: tabular-nums;
                }}
                .tds-kp-actions {{
                    display: flex;
                    align-items: center;
                    justify-content: flex-end;
                    gap: 8px;
                }}
                .tds-kp-btn-jump {{
                    padding: 8px 14px;
                    border-radius: 10px;
                    background: #F2F4F6;
                    color: #191F28;
                    border: none;
                    font-size: 0.76rem;
                    font-weight: 700;
                    cursor: pointer;
                }}
                .tds-kp-btn-jump:hover {{
                    background: #E5E8EB;
                }}
                .tds-kp-btn-approve {{
                    padding: 8px 16px;
                    border-radius: 10px;
                    background: #3182F6;
                    color: #FFFFFF;
                    border: none;
                    font-size: 0.78rem;
                    font-weight: 800;
                    cursor: pointer;
                }}
                .tds-kp-btn-approve:hover {{
                    background: #1B64DA;
                }}
                .tds-kp-btn-finish {{
                    padding: 8px 16px;
                    border-radius: 10px;
                    background: #FFF5E5;
                    color: #D97706;
                    border: none;
                    font-size: 0.78rem;
                    font-weight: 800;
                    cursor: pointer;
                }}
                .tds-kp-done-txt {{
                    font-size: 0.76rem;
                    font-weight: 800;
                    color: #00A660;
                }}

                .tds-kp-footer {{
                    background: #FFFFFF;
                    border-top: 1px solid #E5E8EB;
                    padding: 12px 24px;
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    font-size: 0.76rem;
                    color: #8B95A1;
                    flex-shrink: 0;
                }}
                .tds-kp-min-btn {{
                    padding: 6px 14px;
                    border-radius: 10px;
                    background: #F2F4F6;
                    border: none;
                    font-weight: 700;
                    color: #191F28;
                    cursor: pointer;
                }}
                .tds-kp-min-btn:hover {{
                    background: #E5E8EB;
                }}

                /* [2]-2 직각 네모 말풍선 (border: 2px solid #3182F6, border-radius: 6px) */
                #tds-kakao-square-bubble {{
                    background: #FFFFFF;
                    border: 2px solid #3182F6;
                    border-radius: 6px;
                    box-shadow: 0 6px 18px rgba(49, 130, 246, 0.10);
                    animation: squareBubblePop 0.28s cubic-bezier(0.16, 1, 0.3, 1) forwards;
                    margin-bottom: 14px;
                    width: 350px;
                    max-width: 90vw;
                    padding: 16px;
                    position: relative;
                }}
                #tds-kakao-square-bubble.hidden {{
                    display: none !important;
                }}
                .tds-sb-top {{
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    gap: 8px;
                    margin-bottom: 6px;
                }}
                .tds-sb-badge {{
                    display: inline-flex;
                    align-items: center;
                    gap: 4px;
                    padding: 2px 8px;
                    border-radius: 999px;
                    border: none;
                    font-size: 0.68rem;
                    font-weight: 800;
                    background: #E8F3FF;
                    color: #3182F6;
                    font-variant-numeric: tabular-nums;
                }}
                .tds-sb-dismiss {{
                    background: transparent;
                    border: none;
                    color: #8B95A1;
                    font-size: 0.75rem;
                    font-weight: 700;
                    cursor: pointer;
                    padding: 0 4px;
                }}
                .tds-sb-dismiss:hover {{
                    color: #191F28;
                }}
                .tds-sb-msg {{
                    font-size: 0.86rem;
                    font-weight: 800;
                    color: #191F28;
                    line-height: 1.38;
                    margin: 0;
                }}
                .tds-sb-foot {{
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    margin-top: 12px;
                    padding-top: 10px;
                    border-top: 1px solid #F2F4F6;
                }}
                .tds-sb-time {{
                    font-size: 0.70rem;
                    color: #8B95A1;
                    font-weight: 600;
                }}
                .tds-sb-btns {{
                    display: flex;
                    align-items: center;
                    gap: 6px;
                }}
                .tds-sb-btn-next {{
                    padding: 4px 10px;
                    border-radius: 6px;
                    background: #F2F4F6;
                    border: none;
                    color: #191F28;
                    font-size: 0.72rem;
                    font-weight: 700;
                    cursor: pointer;
                }}
                .tds-sb-btn-next:hover {{
                    background: #E5E8EB;
                }}
                .tds-sb-btn-open {{
                    padding: 4px 12px;
                    border-radius: 6px;
                    background: #3182F6;
                    border: none;
                    color: #FFFFFF;
                    font-size: 0.72rem;
                    font-weight: 800;
                    cursor: pointer;
                }}
                .tds-sb-btn-open:hover {{
                    background: #1B64DA;
                }}
                .tds-sb-tail {{
                    width: 14px;
                    height: 14px;
                    background: #FFFFFF;
                    border-right: 2px solid #3182F6;
                    border-bottom: 2px solid #3182F6;
                    transform: rotate(45deg);
                    position: absolute;
                    bottom: -8px;
                    right: 28px;
                }}

                /* [2]-2 홈버튼 디자인 고정: 66x66px, border-radius: 22px, background: #3898FF */
                #tds-kakao-home-fab {{
                    animation: tossPulseRing 2.2s infinite;
                    position: relative;
                    width: 66px;
                    height: 66px;
                    border-radius: 22px;
                    background: #3898FF;
                    border: none;
                    color: #FFFFFF;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    cursor: grab;
                    transition: transform 0.2s ease, background 0.2s ease;
                    touch-action: none;
                }}
                #tds-kakao-home-fab:hover {{
                    background: #3182F6;
                    transform: scale(1.05);
                }}
                #tds-kakao-home-fab.dragging {{
                    cursor: grabbing !important;
                    transform: scale(1.08) !important;
                    transition: none !important;
                }}
                .cute-face-svg {{
                    animation: cuteWinkBounce 2.8s ease-in-out infinite;
                    pointer-events: none;
                }}
                #tds-kakao-fab-badge {{
                    position: absolute;
                    top: -6px;
                    right: -6px;
                    min-width: 24px;
                    height: 24px;
                    padding: 0 6px;
                    border-radius: 999px;
                    background: #F04452;
                    border: 2px solid #FFFFFF;
                    color: #FFFFFF;
                    font-size: 0.74rem;
                    font-weight: 800;
                    font-variant-numeric: tabular-nums;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    box-shadow: 0 2px 6px rgba(240, 68, 82, 0.4);
                    z-index: 10;
                    pointer-events: none;
                }}
            `;

            const isFreshEntry = !parentDoc.getElementById("tds-kakao-floating-root");
            let rootEl = parentDoc.getElementById("tds-kakao-floating-root");
            if (!rootEl) {{
                rootEl = parentDoc.createElement("div");
                rootEl.id = "tds-kakao-floating-root";
                parentDoc.body.appendChild(rootEl);
            }}

            const FAB_ICON_CLOSED_SVG = `
                <svg class="cute-face-svg" width="46" height="46" viewBox="0 0 32 32" fill="none">
                    <circle cx="16" cy="16" r="12.5" stroke="#FFFFFF" stroke-width="2.9" stroke-linecap="round" stroke-linejoin="round" />
                    <line x1="11.8" y1="13.2" x2="11.8" y2="18.5" stroke="#FFFFFF" stroke-width="3.0" stroke-linecap="round" />
                    <line x1="20.2" y1="13.2" x2="20.2" y2="18.5" stroke="#FFFFFF" stroke-width="3.0" stroke-linecap="round" />
                </svg>
            `;
            const FAB_ICON_OPEN_SVG = `
                <svg width="28" height="28" viewBox="0 0 24 24" fill="none" style="pointer-events:none;">
                    <path d="M6 9L12 15L18 9" stroke="#FFFFFF" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round" />
                </svg>
            `;
            const HEADER_CHAR_SVG = `
                <svg width="22" height="22" viewBox="0 0 28 28" fill="none">
                    <circle cx="14" cy="14" r="9.5" stroke="#FFFFFF" stroke-width="2.3"/>
                    <line x1="10.8" y1="12.2" x2="10.8" y2="15.4" stroke="#FFFFFF" stroke-width="2.3" stroke-linecap="round"/>
                    <line x1="17.2" y1="12.2" x2="17.2" y2="15.4" stroke="#FFFFFF" stroke-width="2.3" stroke-linecap="round"/>
                </svg>
            `;

            if (!parentWin._tdsKakaoState) {{
                parentWin._tdsKakaoState = {{
                    open: INIT_OPEN,
                    filter: "ALL",
                    bubbleIdx: 0,
                    bubbleDismissed: false,
                    todos: TODOS_DATA,
                    customPos: null,
                    serverKstIso: SERVER_KST_ISO
                }};
            }} else {{
                const prevLen = (parentWin._tdsKakaoState.todos || []).length;
                parentWin._tdsKakaoState.todos = TODOS_DATA;
                if (TODOS_DATA.length > prevLen) {{
                    parentWin._tdsKakaoState.bubbleDismissed = false;
                    parentWin._tdsKakaoState.bubbleIdx = 0;
                }}
                parentWin._tdsKakaoState.serverKstIso = SERVER_KST_ISO;
                if (INIT_OPEN !== parentWin._tdsKakaoState._lastServerOpen) {{
                    parentWin._tdsKakaoState.open = INIT_OPEN;
                    parentWin._tdsKakaoState._lastServerOpen = INIT_OPEN;
                }}
                if (isFreshEntry) {{
                    parentWin._tdsKakaoState.customPos = null;
                }}
            }}

            function applyFloatingPosition() {{
                const stObj = parentWin._tdsKakaoState;
                if (stObj && stObj.customPos) {{
                    rootEl.style.left = stObj.customPos.left + "px";
                    rootEl.style.top = stObj.customPos.top + "px";
                    rootEl.style.right = "auto";
                    rootEl.style.bottom = "auto";
                }} else {{
                    rootEl.style.left = "auto";
                    rootEl.style.top = "auto";
                    rootEl.style.right = "20px";
                    rootEl.style.bottom = "60px";
                }}
            }}

            parentWin._tdsActiveCalFrame = frameEl;
            parentWin._tdsCalCleanupTimer = parentWin.setInterval(function() {{
                const activeFr = parentWin._tdsActiveCalFrame;
                if (!activeFr || !parentDoc.body.contains(activeFr)) {{
                    const r = parentDoc.getElementById("tds-kakao-floating-root");
                    if (r) r.remove();
                    if (parentWin._tdsKakaoState) {{
                        parentWin._tdsKakaoState.customPos = null;
                        parentWin._tdsKakaoState.open = false;
                    }}
                    parentWin.clearInterval(parentWin._tdsCalCleanupTimer);
                    parentWin._tdsCalCleanupTimer = null;
                    return;
                }}
                bindDockMultiToggleAndKeys();
                try {{
                    const kstNow = new Date(new Date().toLocaleString("en-US", {{ timeZone: "Asia/Seoul" }}));
                    const y = kstNow.getFullYear();
                    const m = String(kstNow.getMonth() + 1).padStart(2, "0");
                    const d = String(kstNow.getDate()).padStart(2, "0");
                    const hh = String(kstNow.getHours()).padStart(2, "0");
                    const mm = String(kstNow.getMinutes()).padStart(2, "0");
                    const curIso = `${{y}}-${{m}}-${{d}}`;
                    const curHm = `${{hh}}:${{mm}}`;

                    parentDoc.querySelectorAll(".tds-bell-pure[data-alarm-time]").forEach(bellEl => {{
                        const alarmHm = bellEl.getAttribute("data-alarm-time") || "";
                        if (!alarmHm || curHm >= alarmHm) {{
                            bellEl.classList.add("sparkle");
                        }}
                    }});

                    if (parentWin._tdsKakaoState && parentWin._tdsKakaoState.serverKstIso && curIso !== parentWin._tdsKakaoState.serverKstIso) {{
                        parentWin._tdsKakaoState.serverKstIso = curIso;
                        const todayBtn = Array.from(parentDoc.querySelectorAll('section[data-testid="stSidebar"] button'))
                            .find(b => (b.textContent || "").indexOf("오늘 날짜로 즉시 이동") >= 0);
                        if (todayBtn) todayBtn.click();
                    }}
                }} catch (err) {{}}
            }}, 350);

            function escHtml(v) {{
                return String(v == null ? "" : v)
                    .replace(/&/g, "&amp;")
                    .replace(/</g, "&lt;")
                    .replace(/>/g, "&gt;")
                    .replace(/"/g, "&quot;")
                    .replace(/'/g, "&#39;");
            }}

            function getStatusCode(item) {{
                if (item.status_code) return item.status_code;
                const s = String(item.status || "");
                if (s.indexOf("작업중") >= 0) return "WORKING";
                if (s.indexOf("승인요청") >= 0) return "READY";
                return "APPROVED";
            }}

            function copyTextSafe(text) {{
                try {{
                    const ta = parentDoc.createElement("textarea");
                    ta.value = text;
                    ta.style.position = "fixed";
                    ta.style.opacity = "0";
                    parentDoc.body.appendChild(ta);
                    ta.select();
                    parentDoc.execCommand("copy");
                    parentDoc.body.removeChild(ta);
                }} catch (e) {{}}
            }}

            function triggerSidebarMode(targetMode) {{
                const btns = Array.from(parentDoc.querySelectorAll('section[data-testid="stSidebar"] button'));
                let keyword = "달력";
                if (targetMode === "AGENT") keyword = "자율 에이전트AI";
                else if (targetMode === "PAYROLL_BIZ" || targetMode === "PAYROLL_EMP") keyword = "인건비 자동화";
                const found = btns.find(b => (b.textContent || "").indexOf(keyword) >= 0);
                if (found) found.click();
            }}

            function bindFabDrag(fabBtn) {{
                if (!fabBtn) return;
                let isPointerDown = false;
                let hasDragged = false;
                let startX = 0;
                let startY = 0;
                let origLeft = 0;
                let origTop = 0;
                const DRAG_THRESHOLD = 5;

                fabBtn.addEventListener("mousedown", function(e) {{
                    if (e.button !== 0) return;
                    isPointerDown = true;
                    hasDragged = false;
                    startX = e.clientX;
                    startY = e.clientY;
                    const rect = rootEl.getBoundingClientRect();
                    origLeft = rect.left;
                    origTop = rect.top;
                    e.preventDefault();
                }});

                if (parentWin._tdsFabMouseMoveHandler) {{
                    parentWin.removeEventListener("mousemove", parentWin._tdsFabMouseMoveHandler);
                }}
                if (parentWin._tdsFabMouseUpHandler) {{
                    parentWin.removeEventListener("mouseup", parentWin._tdsFabMouseUpHandler);
                }}

                parentWin._tdsFabMouseMoveHandler = function(e) {{
                    if (!isPointerDown) return;
                    const dx = e.clientX - startX;
                    const dy = e.clientY - startY;
                    if (!hasDragged && Math.hypot(dx, dy) > DRAG_THRESHOLD) {{
                        hasDragged = true;
                        fabBtn.classList.add("dragging");
                    }}
                    if (hasDragged) {{
                        const rootRect = rootEl.getBoundingClientRect();
                        const maxLeft = parentWin.innerWidth - rootRect.width - 10;
                        const maxTop = parentWin.innerHeight - rootRect.height - 10;
                        const nextLeft = Math.max(10, Math.min(maxLeft, origLeft + dx));
                        const nextTop = Math.max(10, Math.min(maxTop, origTop + dy));
                        rootEl.style.left = nextLeft + "px";
                        rootEl.style.top = nextTop + "px";
                        rootEl.style.right = "auto";
                        rootEl.style.bottom = "auto";
                        parentWin._tdsKakaoState.customPos = {{ left: nextLeft, top: nextTop }};
                    }}
                }};

                parentWin._tdsFabMouseUpHandler = function(e) {{
                    if (!isPointerDown) return;
                    isPointerDown = false;
                    fabBtn.classList.remove("dragging");
                    if (!hasDragged) {{
                        parentWin._tdsKakaoState.open = !parentWin._tdsKakaoState.open;
                        renderOverlay();
                    }}
                    hasDragged = false;
                }};

                parentWin.addEventListener("mousemove", parentWin._tdsFabMouseMoveHandler);
                parentWin.addEventListener("mouseup", parentWin._tdsFabMouseUpHandler);
            }}

            function renderOverlay() {{
                const stObj = parentWin._tdsKakaoState;
                const allTodos = stObj.todos || [];
                const workingList = allTodos.filter(t => getStatusCode(t) === "WORKING");
                const readyList = allTodos.filter(t => getStatusCode(t) === "READY");
                const approvedList = allTodos.filter(t => getStatusCode(t) === "APPROVED");
                const totalAttention = readyList.length + workingList.length;

                const filtered = allTodos.filter(t => {{
                    if (stObj.filter === "ALL") return true;
                    return getStatusCode(t) === stObj.filter;
                }});

                const cardsHtml = filtered.length === 0
                    ? `<div style="padding:40px;text-align:center;color:#8B95A1;font-weight:700;">해당 상태의 카톡 자동화 내역이 없어요.</div>`
                    : filtered.map(item => {{
                        const sCode = getStatusCode(item);
                        let stBadgeHtml = "";
                        let actBtnsHtml = "";
                        if (sCode === "WORKING") {{
                            stBadgeHtml = `<span class="tds-kp-st-badge working">● 백그라운드 작업중</span>`;
                            actBtnsHtml = `<button class="tds-kp-btn-finish" data-act="finish" data-id="${{escHtml(item.id)}}">작업 즉시 완료시키기 (시연)</button>`;
                        }} else if (sCode === "READY") {{
                            stBadgeHtml = `<span class="tds-kp-st-badge ready">● 작업 완료, 승인요청중</span>`;
                            actBtnsHtml = `
                                <button class="tds-kp-btn-jump" data-act="jump" data-id="${{escHtml(item.id)}}">뒤쪽 작업화면에 띄우기</button>
                                <button class="tds-kp-btn-approve" data-act="approve" data-id="${{escHtml(item.id)}}">${{escHtml(item.action_label || "승인 및 카톡 발송")}}</button>
                            `;
                        }} else {{
                            stBadgeHtml = `<span class="tds-kp-st-badge approved"><span style="color:#00C471;">✓</span> 사용자 승인완료</span>`;
                            actBtnsHtml = `<span class="tds-kp-done-txt">승인 완료됨</span>`;
                        }}

                        const origTxt = item.kakao_original || `[카톡 수신] ${{item.title}}`;
                        const aiTxt = item.ai_result || item.preview || "";

                        return `
                            <div class="tds-kp-card">
                                <div class="tds-kp-card-top">
                                    <div class="tds-kp-card-badges">
                                        ${{stBadgeHtml}}
                                        <span class="tds-kp-cat-pill">${{escHtml(item.category || "카톡 자동화")}}</span>
                                        <span class="tds-kp-time">${{escHtml(item.time_ago || "")}}</span>
                                    </div>
                                    <span class="tds-kp-company">${{escHtml(item.client || "")}}</span>
                                </div>
                                <div class="tds-kp-card-title">${{escHtml(item.title)}}</div>
                                <div class="tds-kp-kakao-orig">${{escHtml(origTxt)}}</div>
                                <div class="tds-kp-ai-res">${{escHtml(aiTxt)}}</div>
                                <div class="tds-kp-actions">${{actBtnsHtml}}</div>
                            </div>
                        `;
                    }}).join("");

                let showBubble = (readyList.length > 0 && !stObj.open && !stObj.bubbleDismissed);
                if (stObj.bubbleIdx >= readyList.length) stObj.bubbleIdx = 0;
                const bItem = readyList[stObj.bubbleIdx] || {{}};
                const bCat = bItem.category ? `${{bItem.category}} (${{stObj.bubbleIdx + 1}}/${{readyList.length}})` : "카톡 백그라운드 알림";
                const bMsg = bItem.bubble_msg || `${{CURRENT_USER}}님, (주)모 회사에 보낼 세법 검토 카톡이 완성되었습니다`;
                const bTime = `${{bItem.time_ago || "방금 전"}}`;

                rootEl.innerHTML = `
                    <div id="tds-kakao-backdrop" class="${{stObj.open ? 'open' : ''}}"></div>
                    <div id="tds-kakao-todo-panel" class="${{stObj.open ? 'open' : ''}}">
                        <div class="tds-kp-header">
                            <div class="tds-kp-hdr-l">
                                <div class="tds-kp-char-circle">${{HEADER_CHAR_SVG}}</div>
                                <div>
                                    <div class="tds-kp-title-row">
                                        <span class="tds-kp-title">${{escHtml(CURRENT_USER)}}님의 카톡 백그라운드 To-Do</span>
                                        <span class="tds-kp-pill-60">60% 오버레이</span>
                                    </div>
                                    <div class="tds-kp-sub">뒤쪽 작업 공간을 유지한 채 진행상황을 확인하고 승인합니다</div>
                                </div>
                            </div>
                            <div class="tds-kp-hdr-r">
                                <button class="tds-kp-approve-all-btn" id="tds-kp-approve-all">승인요청 건 모두 승인하기</button>
                                <button class="tds-kp-close-btn" id="tds-kp-close">✕</button>
                            </div>
                        </div>

                        <div class="tds-kp-tabs-bar">
                            <div class="tds-kp-tabs-l">
                                <button class="tds-kp-tab all ${{stObj.filter === 'ALL' ? 'active-ring' : ''}}" data-filter="ALL">전체 ${{allTodos.length}}</button>
                                <button class="tds-kp-tab working ${{stObj.filter === 'WORKING' ? 'active-ring' : ''}}" data-filter="WORKING">백그라운드 작업중 ${{workingList.length}}</button>
                                <button class="tds-kp-tab ready ${{stObj.filter === 'READY' ? 'active-ring' : ''}}" data-filter="READY">작업 완료, 승인요청중 ${{readyList.length}}</button>
                                <button class="tds-kp-tab approved ${{stObj.filter === 'APPROVED' ? 'active-ring' : ''}}" data-filter="APPROVED">사용자 승인완료 ${{approvedList.length}}</button>
                            </div>
                            <div class="tds-kp-silent-info">통상적 인사 자동 닫기(1소거): <b>${{SILENT_CNT}}건</b></div>
                        </div>

                        <div class="tds-kp-body">${{cardsHtml}}</div>

                        <div class="tds-kp-footer">
                            <span>💡 승인완료 버튼을 누르면 달력에 완료 기록이 자동으로 추가돼요</span>
                            <button class="tds-kp-min-btn" id="tds-kp-minimize">홈버튼으로 접기 ↘</button>
                        </div>
                    </div>

                    <div id="tds-kakao-square-bubble" class="${{showBubble ? '' : 'hidden'}}">
                        <div class="tds-sb-top">
                            <span class="tds-sb-badge">${{escHtml(bCat)}}</span>
                            <button class="tds-sb-dismiss" id="tds-sb-dismiss">✕</button>
                        </div>
                        <p class="tds-sb-msg">${{escHtml(bMsg)}}</p>
                        <div class="tds-sb-foot">
                            <span class="tds-sb-time">${{escHtml(bTime)}}</span>
                            <div class="tds-sb-btns">
                                <button class="tds-sb-btn-next" id="tds-sb-next">다음 ▸</button>
                                <button class="tds-sb-btn-open" id="tds-sb-open">체크리스트 열기</button>
                            </div>
                        </div>
                        <div class="tds-sb-tail"></div>
                    </div>

                    <button id="tds-kakao-home-fab" aria-label="홈버튼 열기">
                        ${{totalAttention > 0 ? `<span id="tds-kakao-fab-badge">${{totalAttention}}</span>` : ''}}
                        ${{stObj.open ? FAB_ICON_OPEN_SVG : FAB_ICON_CLOSED_SVG}}
                    </button>
                `;

                applyFloatingPosition();

                const fabBtn = parentDoc.getElementById("tds-kakao-home-fab");
                const closeBtn = parentDoc.getElementById("tds-kp-close");
                const minBtn = parentDoc.getElementById("tds-kp-minimize");
                const backdropEl = parentDoc.getElementById("tds-kakao-backdrop");
                const approveAllBtn = parentDoc.getElementById("tds-kp-approve-all");
                const sbDismiss = parentDoc.getElementById("tds-sb-dismiss");
                const sbNext = parentDoc.getElementById("tds-sb-next");
                const sbOpen = parentDoc.getElementById("tds-sb-open");

                bindFabDrag(fabBtn);

                if (closeBtn) closeBtn.onclick = function() {{ stObj.open = false; renderOverlay(); }};
                if (minBtn) minBtn.onclick = function() {{ stObj.open = false; renderOverlay(); }};
                if (backdropEl) backdropEl.onclick = function() {{ stObj.open = false; renderOverlay(); }};

                if (sbDismiss) {{
                    sbDismiss.onclick = function(e) {{
                        e.stopPropagation();
                        stObj.bubbleDismissed = true;
                        renderOverlay();
                    }};
                }}
                if (sbNext) {{
                    sbNext.onclick = function(e) {{
                        e.stopPropagation();
                        stObj.bubbleIdx = stObj.bubbleIdx + 1;
                        renderOverlay();
                    }};
                }}
                if (sbOpen) {{
                    sbOpen.onclick = function(e) {{
                        e.stopPropagation();
                        stObj.open = true;
                        renderOverlay();
                    }};
                }}

                if (approveAllBtn) {{
                    approveAllBtn.onclick = function() {{
                        allTodos.forEach(t => {{
                            if (getStatusCode(t) === "READY") {{
                                t.status_code = "APPROVED";
                                t.status = "사용자 승인완료";
                                t.time_ago = "방금 일괄승인";
                                t.checked = true;
                            }}
                        }});
                        renderOverlay();
                    }};
                }}

                rootEl.querySelectorAll(".tds-kp-tab").forEach(btn => {{
                    btn.onclick = function() {{
                        stObj.filter = this.getAttribute("data-filter") || "ALL";
                        renderOverlay();
                    }};
                }});

                rootEl.querySelectorAll("button[data-act]").forEach(btn => {{
                    btn.onclick = function() {{
                        const act = this.getAttribute("data-act");
                        const tid = this.getAttribute("data-id");
                        const target = allTodos.find(x => x.id === tid);
                        if (!target) return;
                        if (act === "finish") {{
                            target.status_code = "READY";
                            target.status = "작업 완료, 승인요청중";
                            target.time_ago = "방금 완료됨";
                            target.ai_result = "✅ 지정 폴더 저장 및 에이전트AI 급여명세서 화면(임직원 8명) 자동 입력이 완료되었습니다!";
                            renderOverlay();
                        }} else if (act === "approve") {{
                            copyTextSafe(target.ai_result || target.preview || "");
                            target.status_code = "APPROVED";
                            target.status = "사용자 승인완료";
                            target.time_ago = "방금 승인됨";
                            target.checked = true;
                            renderOverlay();
                        }} else if (act === "jump") {{
                            stObj.open = false;
                            renderOverlay();
                            triggerSidebarMode(target.target_mode || "CALENDAR");
                        }}
                    }};
                }});
            }}

            renderOverlay();
        }})();
        </script>
        """,
        height=0,
    )