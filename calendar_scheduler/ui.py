# -*- coding: utf-8 -*-
"""
달력 스케줄러 + Today To Do 체크리스트 + 구글 캘린더형 중앙 상세정보 모달 + 드래그 가능한 미소 홈버튼 & 60% 확장 To-Do 오버레이 (calendar_scheduler/ui.py)

[Part 1: 라이브러리 Import + 스타일/CSS 정의 + 핵심 비즈니스 로직/함수부]
[Part 2: 상태 초기화 + 중앙 상세정보 모달 + UI 레이아웃 렌더링 및 이벤트 연결부]
"""
from __future__ import annotations

import calendar
import html as _html_lib
import json
from datetime import date, datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import streamlit as st
import streamlit.components.v1 as components

import ui_theme as _ui_theme

_WEEKDAYS_SHORT = ("월", "화", "수", "목", "금", "토", "일")
_WEEKDAYS_FULL = ("월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일")
_SUN_FIRST_HEADERS = ("일", "월", "화", "수", "목", "금", "토")


def _html(s: str) -> str:
    """여러 줄 HTML을 한 줄로 이어 붙여 표시 (빈 줄·들여쓰기로 인해 코드 블록으로 인식되는 현상 방지)"""
    return " ".join(ln.strip() for ln in str(s).splitlines() if ln.strip())


def get_kst_today() -> date:
    """한국 표준시(KST, Asia/Seoul) 기준 오늘 날짜(00:00 자정 기준)를 반환합니다."""
    return datetime.now(ZoneInfo("Asia/Seoul")).date()


def get_kst_now_hm() -> str:
    """한국 표준시(KST, Asia/Seoul) 기준 현재 시각을 'HH:MM' 문자열로 반환합니다."""
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%H:%M")


def _normalize_time_str(raw: str) -> str:
    """입력된 시간 문자열(예: '930', '09:30', '14:00')을 정규화합니다."""
    s = str(raw or "").strip()
    if not s or s in ("일정", "기한", "-"):
        return ""
    digits = "".join(ch for ch in s if ch.isdigit())
    if len(digits) == 3:
        digits = "0" + digits
    if len(digits) == 4:
        hh = min(23, max(0, int(digits[:2])))
        mm = min(59, max(0, int(digits[2:4])))
        return f"{hh:02d}:{mm:02d}"
    return s[:5]


def _is_valid_hhmm(val: str) -> bool:
    """'HH:MM' 형식의 시간인지 판별합니다."""
    s = str(val or "").strip()
    if len(s) == 5 and s[2] == ":" and s[:2].isdigit() and s[3:].isdigit():
        return True
    return False


def _is_alarm_due(ev_time: str, now_hm: str, is_today_selected: bool) -> bool:
    """알림이 설정된 할 일이 지정 시각에 도달(또는 경과)했는지 판별합니다."""
    if not _is_valid_hhmm(ev_time):
        return False
    if not is_today_selected:
        return False
    return now_hm >= ev_time


def _has_detail_info(ev: Dict[str, Any]) -> bool:
    """할 일에 상세정보(하위 체크리스트, 메모, 거래처, 업무화면 연결, 첨부파일 등)가 있는지 확인합니다."""
    if ev.get("has_detail"):
        return True
    if ev.get("sub_checks"):
        return True
    if str(ev.get("memo") or "").strip():
        return True
    if str(ev.get("attachment") or "").strip():
        return True
    if str(ev.get("location") or "").strip():
        return True
    if str(ev.get("link_target") or "") not in ("", "NONE"):
        return True
    return False


def _default_schedules_for_month(year: int, month: int, today_d: date) -> Dict[int, List[Dict[str, Any]]]:
    """
    당해 연월의 기본 세무 일정 및 Today To Do 체크리스트 초기 데이터를 생성합니다.
    """
    focus_day = today_d.day if (today_d.year == year and today_d.month == month) else 5
    last_day = calendar.monthrange(year, month)[1]
    focus_day = min(max(1, focus_day), last_day)

    data: Dict[int, List[Dict[str, Any]]] = {
        focus_day: [
            {
                "id": f"sch_{year}_{month}_{focus_day}_1",
                "type": "MY",
                "time": "09:30",
                "end_time": "10:00",
                "title": "시범법인 통장 자동분개 점검",
                "client": "시범법인",
                "category": "내 스케줄",
                "ai_status": "작업 완료, 승인요청중",
                "done": False,
                "alarm": False,
                "in_calendar": True,
                "important": False,
                "has_detail": False,
                "repeat": "반복 안함",
                "location": "",
                "link_target": "NONE",
                "sub_checks": [],
                "memo": "",
                "attachment": "",
                "desc": "법인 통장 입출금 내역 자동분개 규칙 점검 및 이상 거래 확인",
            },
            {
                "id": f"sch_{year}_{month}_{focus_day}_2",
                "type": "MY",
                "time": "14:00",
                "end_time": "15:00",
                "title": "(주)성진 급여 세부문자 미팅",
                "client": "(주)성진 · 김성진 대표님",
                "category": "내 스케줄",
                "ai_status": "작업 완료, 승인요청중",
                "done": False,
                "alarm": True,
                "in_calendar": True,
                "important": False,
                "has_detail": True,
                "repeat": "매월 반복",
                "location": "3층 회의실 / 전화미팅",
                "link_target": "PAYROLL_EMP",
                "sub_checks": [
                    {"text": "10월분 급여대장 엑셀 수령 확인", "done": True},
                    {"text": "식대 비과세 한도(20만 원) 반영 점검", "done": True},
                    {"text": "대표님께 카톡으로 급여명세서 초안 발송", "done": False},
                ],
                "memo": "이번 달 신규 입사자 1명 중도정산 반영 여부 대표님께 안내드리기.",
                "attachment": f"(주)성진_{year}년{month}월_급여대장_세전자료.xlsx",
                "desc": "(주)성진 급여 세부문자 및 급여명세서 초안 검토 미팅",
            },
            {
                "id": f"sch_{year}_{month}_{focus_day}_3",
                "type": "DONE",
                "time": "16:30",
                "end_time": "17:00",
                "title": "(주)성진 급여명세서 자동작성 완료",
                "client": "(주)성진",
                "category": "승인완료",
                "ai_status": "사용자 승인완료",
                "done": True,
                "alarm": False,
                "in_calendar": True,
                "important": False,
                "has_detail": False,
                "repeat": "반복 안함",
                "location": "",
                "link_target": "PAYROLL_EMP",
                "sub_checks": [],
                "memo": "",
                "attachment": "",
                "desc": "카톡 급여대장 엑셀 수신 → 지정 폴더 저장 및 급여명세서 2명 자동 작성 완료",
            },
            {
                "id": f"sch_{year}_{month}_{focus_day}_4",
                "type": "MY",
                "time": "16:30",
                "end_time": "17:00",
                "title": "김모님께 연락하기",
                "client": "(주)모 · 김모 대표님",
                "category": "내 스케줄",
                "ai_status": "작업 완료, 승인요청중",
                "done": False,
                "alarm": True,
                "in_calendar": True,
                "important": False,
                "has_detail": True,
                "repeat": "반복 안함",
                "location": "전화 자문",
                "link_target": "AGENT",
                "sub_checks": [],
                "memo": "가족 단기 아르바이트 인건비 필요경비 및 통합고용세액공제 검토 결과 안내드리기.",
                "attachment": f"(주)모_{year}년_가족인건비_검토안내.pdf",
                "desc": "가족 단기 아르바이트 인건비 필요경비 및 통합고용세액공제 자문 연락",
            },
        ],
        10: [
            {
                "id": f"sch_{year}_{month}_10_1",
                "type": "TAX",
                "time": "09:00",
                "end_time": "18:00",
                "title": "원천세 · 지방소득세 신고납부",
                "client": "전체 기장 거래처",
                "category": "세무기한",
                "ai_status": "작업 완료, 승인요청중",
                "done": False,
                "alarm": True,
                "in_calendar": True,
                "important": True,
                "has_detail": True,
                "repeat": "매월 반복",
                "location": "홈택스 / 위택스 전자신고",
                "link_target": "PAYROLL_EMP",
                "sub_checks": [
                    {"text": "기장 거래처 급여·사업소득 마감 확인", "done": True},
                    {"text": "원천징수이행상황신고서 전자신고", "done": False},
                    {"text": "거래처별 납부서 카톡 일괄 발송", "done": False},
                ],
                "memo": "매월 10일 원천세 및 특별징수 지방소득세 정기 신고·납부 마감일",
                "attachment": "",
                "desc": "원천징수이행상황신고서 마감 및 거래처별 납부서 카톡 일괄 안내",
            },
            {
                "id": f"sch_{year}_{month}_10_2",
                "type": "TAX",
                "time": "10:00",
                "end_time": "18:00",
                "title": f"4대보험 {max(1, month - 1)}월분 납부기한",
                "client": "전체 기장 거래처",
                "category": "세무기한",
                "ai_status": "작업 완료, 승인요청중",
                "done": False,
                "alarm": False,
                "in_calendar": True,
                "important": False,
                "has_detail": False,
                "repeat": "매월 반복",
                "location": "",
                "link_target": "NONE",
                "sub_checks": [],
                "memo": "",
                "attachment": "",
                "desc": "국민연금·건강보험·고용·산재보험 당월 고지분 납부 마감",
            },
        ],
        16: [
            {
                "id": f"sch_{year}_{month}_16_1",
                "type": "MY",
                "time": "11:00",
                "end_time": "12:00",
                "title": "두리님과 10개 법인 통장규칙 점검",
                "client": "내부 업무",
                "category": "내 스케줄",
                "ai_status": "백그라운드 작업중",
                "done": False,
                "alarm": True,
                "in_calendar": True,
                "important": False,
                "has_detail": True,
                "repeat": "반복 안함",
                "location": "회의실",
                "link_target": "AGENT",
                "sub_checks": [
                    {"text": "10개 법인 style_config.json 규칙 백업", "done": True},
                    {"text": "신규 적요 계정과목 매핑 테스트", "done": False},
                ],
                "memo": "주요 기장 법인 10곳 통장 적요별 계정과목 매핑 규칙 점검",
                "attachment": "",
                "desc": "주요 기장 법인 10곳 통장 적요별 계정과목 매핑 규칙 점검",
            },
        ],
        25: [
            {
                "id": f"sch_{year}_{month}_25_1",
                "type": "TAX",
                "time": "09:00",
                "end_time": "18:00",
                "title": "개별소비세 · 증권거래세 신고",
                "client": "해당 법인 거래처",
                "category": "세무기한",
                "ai_status": "작업 완료, 승인요청중",
                "done": False,
                "alarm": False,
                "in_calendar": True,
                "important": False,
                "has_detail": False,
                "repeat": "매월 반복",
                "location": "",
                "link_target": "NONE",
                "sub_checks": [],
                "memo": "",
                "attachment": "",
                "desc": "당월분 개별소비세 및 증권거래세 정기 신고·납부 기한",
            },
        ],
        last_day: [
            {
                "id": f"sch_{year}_{month}_{last_day}_1",
                "type": "TAX",
                "time": "09:00",
                "end_time": "18:00",
                "title": "종합소득세 중간예납 납부기한",
                "client": "개인사업자 거래처",
                "category": "세무기한",
                "ai_status": "작업 완료, 승인요청중",
                "done": False,
                "alarm": True,
                "in_calendar": True,
                "important": True,
                "has_detail": False,
                "repeat": "반복 안함",
                "location": "",
                "link_target": "NONE",
                "sub_checks": [],
                "memo": "",
                "attachment": "",
                "desc": "종합소득세 중간예납 고지세액 납부 안내 및 추계신고 대상 점검",
            },
            {
                "id": f"sch_{year}_{month}_{last_day}_2",
                "type": "TAX",
                "time": "14:00",
                "end_time": "18:00",
                "title": "일용근로·간이지급명세서 제출",
                "client": "인건비 신고 거래처",
                "category": "세무기한",
                "ai_status": "작업 완료, 승인요청중",
                "done": False,
                "alarm": True,
                "in_calendar": True,
                "important": False,
                "has_detail": False,
                "repeat": "매월 반복",
                "location": "",
                "link_target": "PAYROLL_BIZ",
                "sub_checks": [],
                "memo": "",
                "attachment": "",
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


def _sort_day_events(evs: List[Dict[str, Any]], important_first: bool = False) -> List[Dict[str, Any]]:
    """
    시간이 지정된(HH:MM) 할 일을 상단에 시간대별 오름차순으로 우선 정렬하고,
    시간 미지정 할 일은 하단에 배치합니다. (중요 우선 토글 활성화 시 중요 핀 항목 최상단 고정)
    """
    def _sort_key(item: Dict[str, Any]):
        t_str = str(item.get("time") or "").strip()
        has_valid_t = _is_valid_hhmm(t_str)
        imp_rank = 0 if (important_first and item.get("important")) else 1
        time_rank = 0 if has_valid_t else 1
        return (imp_rank, time_rank, t_str if has_valid_t else "99:99", str(item.get("id", "")))

    return sorted(evs, key=_sort_key)


def _switch_app_navigation_to(target_mode: str) -> None:
    """상세정보 모달에서 업무 화면 바로가기 클릭 시 해당 모드로 전환합니다."""
    mode_map = {
        "AGENT": "자율 에이전트AI",
        "CREDIT": "통합고용세액공제",
        "PAYROLL_EMP": "인건비 자동화",
        "PAYROLL_BIZ": "인건비 자동화",
    }
    label = mode_map.get(target_mode)
    if not label:
        return
    for k in ("app_mode", "nav_mode", "current_page", "selected_menu", "main_nav"):
        if k in st.session_state:
            st.session_state[k] = label


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


CALENDAR_MAIN_CSS = """
<style>
/* ═════════ Toss Web TDS 달력 (브라우저 90% 배율 풀사이즈) & Today To Do 전용 스타일 ═════════ */
[data-testid="stApp"] [data-testid="stMain"],
[data-testid="stApp"] [data-testid="stAppScrollToBottomContainer"],
[data-testid="stApp"] [data-testid="stBottom"] > div {
    background: #F4F6FA !important;
}

/* 알림 종(Bell) 노랑-주황-빨강-주황-노랑 후광 애니메이션 */
@keyframes bellGlowCycle {
    0%, 100% {
        background: radial-gradient(circle, rgba(253, 224, 71, 0.85) 0%, rgba(251, 146, 60, 0.35) 55%, rgba(239, 68, 68, 0) 100%);
        box-shadow: 0 0 12px 3px rgba(250, 204, 21, 0.65);
        transform: scale(1) rotate(0deg);
        color: #D97706;
    }
    25% {
        background: radial-gradient(circle, rgba(251, 146, 60, 0.90) 0%, rgba(239, 68, 68, 0.45) 60%, rgba(251, 146, 60, 0) 100%);
        box-shadow: 0 0 16px 5px rgba(249, 115, 22, 0.75);
        transform: scale(1.10) rotate(-10deg);
        color: #EA580C;
    }
    50% {
        background: radial-gradient(circle, rgba(239, 68, 68, 0.92) 0%, rgba(251, 146, 60, 0.55) 65%, rgba(253, 224, 71, 0) 100%);
        box-shadow: 0 0 20px 6px rgba(239, 68, 68, 0.82);
        transform: scale(1.14) rotate(10deg);
        color: #FFFFFF;
    }
    75% {
        background: radial-gradient(circle, rgba(251, 146, 60, 0.90) 0%, rgba(253, 224, 71, 0.45) 60%, rgba(251, 146, 60, 0) 100%);
        box-shadow: 0 0 16px 5px rgba(249, 115, 22, 0.75);
        transform: scale(1.08) rotate(-6deg);
        color: #EA580C;
    }
}

/* 1. 상단 워크스페이스 필 바 (Top Toss Pill Bar) */
.tds-workspace-pill-bar {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    background: rgba(255, 255, 255, 0.78);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    border: 1px solid rgba(255, 255, 255, 0.90);
    border-radius: 16px;
    padding: 10px 18px;
    margin-bottom: 14px;
    box-shadow: 0 2px 10px rgba(25, 31, 40, 0.04);
    font-size: 0.85rem;
    color: #333D4B;
}
.tds-wp-left {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
}
.tds-wp-user {
    font-weight: 800;
    color: #191F28;
}
.tds-wp-sep {
    color: #D1D6DB;
}
.tds-wp-silent {
    color: #4E5968;
    font-weight: 500;
}
.tds-wp-silent b {
    color: #3182F6;
    font-weight: 800;
}
.tds-wp-right-badge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 0.76rem;
    font-weight: 700;
    background: #E8F3FF;
    color: #3182F6;
    padding: 5px 12px;
    border-radius: 999px;
}

/* 2. 우측 상단 연도 표시 A안 ('2026년' 상단 미니 라벨 + '11월' 초대형 텍스트) & '＋ 일정 추가하기' */
.tds-month-heading-box {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    justify-content: center;
    height: 68px;
    margin-bottom: 10px;
    padding-left: 4px;
    box-sizing: border-box;
    user-select: none;
}
.tds-year-mini-label {
    font-size: 0.84rem;
    font-weight: 800;
    color: #6B7684;
    letter-spacing: 0.3px;
    line-height: 1.1;
    margin-bottom: 3px;
    font-variant-numeric: tabular-nums;
}
.tds-month-big-text {
    font-size: 3.15rem;
    font-weight: 900;
    color: #191F28;
    letter-spacing: -2px;
    line-height: 0.90;
    font-variant-numeric: tabular-nums;
}
[data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-cal_add_btn_wrap {
    display: flex !important;
    align-items: center !important;
    justify-content: flex-end !important;
    height: 68px !important;
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
    border-radius: 16px !important;
    color: #FFFFFF !important;
    font-weight: 800 !important;
    min-height: 46px !important;
    height: 46px !important;
    padding: 0 18px !important;
    box-shadow: 0 4px 14px rgba(49, 130, 246, 0.24) !important;
    width: auto !important;
}
[data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-cal_add_btn_wrap div.stButton > button:hover {
    background: #1B64DA !important;
    border-color: #1B64DA !important;
}

/* 3. 좌측 30% 반투명 글래스모피즘 달력 본체 (90% 배율에서도 바닥까지 꽉 차는 830px) */
[data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-cal_glass_surface {
    background: rgba(255, 255, 255, 0.30) !important;
    backdrop-filter: blur(22px) saturate(180%) !important;
    -webkit-backdrop-filter: blur(22px) saturate(180%) !important;
    border: 1px solid rgba(255, 255, 255, 0.68) !important;
    box-shadow: 0 12px 34px -8px rgba(25, 31, 40, 0.06) !important;
    border-radius: 28px !important;
    padding: 18px 20px 22px 20px !important;
    min-height: 830px !important;
    box-sizing: border-box !important;
}

/* 우측 'Today To Do' 글래스 카드 (달력 하단 끝선과 일치하도록 752px 확장) */
[data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-cal_right_todo_card {
    background: rgba(255, 255, 255, 0.38) !important;
    backdrop-filter: blur(22px) saturate(180%) !important;
    -webkit-backdrop-filter: blur(22px) saturate(180%) !important;
    border: 1px solid rgba(255, 255, 255, 0.78) !important;
    box-shadow: 0 12px 34px -8px rgba(25, 31, 40, 0.06) !important;
    border-radius: 28px !important;
    padding: 20px 20px 18px 20px !important;
    min-height: 752px !important;
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
    font-weight: 800;
    color: #6B7684;
    padding: 4px 0 6px 0;
}
.tds-cal-dow-cell.sun { color: #F04452; }
.tds-cal-dow-cell.sat { color: #3182F6; }

/* 달력 날짜 셀 (146px 확장) */
.tds-cal-day-card {
    background: rgba(255, 255, 255, 0.36);
    backdrop-filter: blur(10px);
    -webkit-backdrop-filter: blur(10px);
    border: 1px solid rgba(255, 255, 255, 0.65);
    border-radius: 20px;
    height: 146px;
    min-height: 146px;
    padding: 12px;
    box-sizing: border-box;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    transition: all 0.18s cubic-bezier(0.16, 1, 0.3, 1);
    margin-bottom: 6px;
    overflow: hidden;
}
.tds-cal-day-card:hover {
    background: rgba(255, 255, 255, 0.64);
    transform: translateY(-2px);
    box-shadow: 0 8px 20px -6px rgba(49, 130, 246, 0.14);
}
.tds-cal-day-card.selected {
    background: rgba(255, 255, 255, 0.78) !important;
    border: 2.5px solid #3182F6 !important;
    box-shadow: 0 10px 24px -6px rgba(49, 130, 246, 0.22);
}
.tds-cal-day-card.empty {
    background: rgba(255, 255, 255, 0.10);
    border: 1px dashed rgba(229, 232, 235, 0.45);
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
    color: #FFFFFF;
    background: #3182F6;
    padding: 2px 8px;
    border-radius: 999px;
}
.tds-cal-ev-list {
    display: flex;
    flex-direction: column;
    gap: 4px;
}
.tds-cal-ev-pill {
    font-size: 0.71rem;
    font-weight: 800;
    padding: 3px 8px;
    border-radius: 8px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    line-height: 1.35;
}
.tds-cal-ev-pill.blue { background: rgba(232, 243, 255, 0.94); color: #3182F6; }
.tds-cal-ev-pill.red { background: rgba(255, 240, 240, 0.94); color: #F04452; }
.tds-cal-ev-pill.green { background: rgba(229, 247, 240, 0.94); color: #00A86B; }
.tds-cal-ev-more {
    font-size: 0.68rem;
    font-weight: 800;
    color: #6B7684;
    padding-left: 3px;
}

/* 날짜 셀 클릭 투명 오버레이 (146px 셀 높이에 정합 매칭) */
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
}

/* 4. 우측 'Today To Do' 상단 헤더 & 미니 진행률 바 */
.tds-todo-hdr-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    margin-bottom: 8px;
}
.tds-todo-hdr-left {
    display: flex;
    align-items: center;
    gap: 10px;
}
.tds-todo-main-title {
    font-size: 1.32rem;
    font-weight: 900;
    color: #191F28;
    letter-spacing: -0.4px;
}
.tds-todo-cnt-pill {
    font-size: 0.76rem;
    font-weight: 800;
    padding: 3px 11px;
    border-radius: 999px;
    background: #3182F6;
    color: #FFFFFF;
}
.tds-todo-progress-track {
    width: 100%;
    height: 5px;
    border-radius: 999px;
    background: rgba(229, 232, 235, 0.85);
    overflow: hidden;
    margin-bottom: 12px;
}
.tds-todo-progress-fill {
    height: 100%;
    border-radius: 999px;
    background: linear-gradient(90deg, #3182F6 0%, #60A5FA 100%);
    transition: width 0.25s ease;
}

/* 상단 [중요 우선] / [완료 숨김] 미니 토글 버튼 스타일 */
[data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-btn_todo_flt_"] div.stButton > button {
    min-height: 28px !important;
    height: 28px !important;
    padding: 0 10px !important;
    border-radius: 999px !important;
    font-size: 0.72rem !important;
    font-weight: 800 !important;
}

/* 5. 1칸 높이 컴팩트 Today To Do 아이템 카드 */
[data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-todo_item_row_"] {
    position: relative !important;
    background: rgba(255, 255, 255, 0.92) !important;
    border: 1.5px solid rgba(229, 232, 235, 0.95) !important;
    border-radius: 18px !important;
    padding: 8px 14px 8px 12px !important;
    margin-bottom: 8px !important;
    box-shadow: 0 2px 8px rgba(25, 31, 40, 0.03) !important;
    transition: all 0.16s ease !important;
}
[data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-todo_item_row_"]:hover {
    border-color: rgba(49, 130, 246, 0.55) !important;
    box-shadow: 0 6px 14px rgba(25, 31, 40, 0.06) !important;
}
[data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-todo_item_row_"] [data-testid="stHorizontalBlock"] {
    align-items: center !important;
    gap: 6px !important;
}

/* 좌측 부드러운 사각 ㅁ 체크박스 (토스 블루 시안 1) */
[data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-chk_todo_"] {
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
}
[data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-chk_todo_"] [data-testid="stCheckbox"] {
    margin: 0 !important;
    padding: 0 !important;
}
[data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-chk_todo_"] input[type="checkbox"] + div {
    border-radius: 7px !important;
}

/* 컴팩트 1줄 할 일 제목 & 우측 끝 시간·종 아이콘 영역 */
.tds-compact-todo-line {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    width: 100%;
    min-height: 32px;
}
.tds-compact-title-wrap {
    display: flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
    flex: 1;
}
.tds-compact-title {
    font-size: 0.88rem;
    font-weight: 800;
    color: #191F28;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    line-height: 1.3;
}
.tds-compact-title.done {
    text-decoration: line-through;
    text-decoration-thickness: 2px;
    color: #8B95A1;
    font-weight: 700;
}
.tds-imp-mini-badge {
    font-size: 0.65rem;
    font-weight: 800;
    padding: 2px 7px;
    border-radius: 999px;
    background: #FFF0F0;
    color: #F04452;
    flex-shrink: 0;
}
.tds-sub-cnt-badge {
    font-size: 0.68rem;
    font-weight: 800;
    padding: 2px 8px;
    border-radius: 999px;
    background: #E8F3FF;
    color: #3182F6;
    flex-shrink: 0;
}
.tds-compact-right-meta {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-shrink: 0;
    padding-right: 4px;
}
.tds-bell-wrap {
    width: 24px;
    height: 24px;
    border-radius: 999px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    color: #3182F6;
    background: #E8F3FF;
    flex-shrink: 0;
}
.tds-bell-wrap.glow {
    animation: bellGlowCycle 1.6s ease-in-out infinite;
}
.tds-compact-time {
    font-size: 0.84rem;
    font-weight: 800;
    color: #191F28;
    font-variant-numeric: tabular-nums;
    letter-spacing: -0.2px;
}
.tds-compact-time.done {
    color: #8B95A1;
}

/* 할 일 옆 파란색 바탕 동그라미 '상세' 버튼 */
[data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-btn_todo_dtl_"] div.stButton > button {
    width: 34px !important;
    min-width: 34px !important;
    height: 34px !important;
    min-height: 34px !important;
    border-radius: 999px !important;
    background: #3182F6 !important;
    border: 1.5px solid #3182F6 !important;
    color: #FFFFFF !important;
    font-size: 0.67rem !important;
    font-weight: 800 !important;
    padding: 0 !important;
    box-shadow: 0 3px 8px rgba(49, 130, 246, 0.28) !important;
}
[data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-btn_todo_dtl_"] div.stButton > button:hover {
    background: #1B64DA !important;
    transform: scale(1.06) !important;
}

/* 오른쪽 대각 상단 작은 동그라미 안의 x 삭제 버튼 */
[data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-btn_todo_del_"] {
    display: flex !important;
    justify-content: flex-end !important;
    margin-top: -16px !important;
    margin-right: -8px !important;
}
[data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-btn_todo_del_"] div.stButton > button {
    width: 22px !important;
    min-width: 22px !important;
    height: 22px !important;
    min-height: 22px !important;
    border-radius: 999px !important;
    background: #FFFFFF !important;
    border: 1.5px solid #D1D6DB !important;
    color: #6B7684 !important;
    font-size: 0.65rem !important;
    font-weight: 800 !important;
    padding: 0 !important;
    line-height: 1 !important;
    box-shadow: 0 2px 5px rgba(25, 31, 40, 0.08) !important;
}
[data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-btn_todo_del_"] div.stButton > button:hover {
    border-color: #F04452 !important;
    color: #F04452 !important;
    background: #FFF0F0 !important;
}

/* 6. 최하단 레이아웃 A: 한 줄 일체형 대화입력 독(Dock) 바 */
[data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-todo_bottom_dock_a {
    background: #FFFFFF !important;
    border: 2px solid #3182F6 !important;
    border-radius: 20px !important;
    padding: 8px 10px !important;
    box-shadow: 0 6px 18px rgba(49, 130, 246, 0.12) !important;
    margin-top: 8px !important;
}
[data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-todo_bottom_dock_a [data-testid="stHorizontalBlock"] {
    align-items: center !important;
    gap: 6px !important;
}
[data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-dock_chat_inp input {
    border: none !important;
    background: transparent !important;
    font-size: 0.84rem !important;
    font-weight: 700 !important;
    padding: 4px 6px !important;
    box-shadow: none !important;
}
[data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-dock_time_inp input {
    border-radius: 12px !important;
    background: #F4F6FA !important;
    border: 1px solid #D1D6DB !important;
    text-align: center !important;
    font-size: 0.78rem !important;
    font-weight: 800 !important;
    padding: 4px 4px !important;
}
[data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-dock_btn_alarm div.stButton > button,
[data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-dock_btn_cal div.stButton > button {
    border-radius: 12px !important;
    min-height: 36px !important;
    height: 36px !important;
    padding: 0 8px !important;
    font-size: 0.74rem !important;
    font-weight: 800 !important;
}
[data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-dock_btn_detail div.stButton > button {
    border-radius: 12px !important;
    min-height: 36px !important;
    height: 36px !important;
    padding: 0 10px !important;
    font-size: 0.76rem !important;
    font-weight: 800 !important;
    background: #3182F6 !important;
    border-color: #3182F6 !important;
    color: #FFFFFF !important;
}

/* 7. 구글 캘린더 스타일 화면 중앙 상세정보 모달 (@st.dialog) 커스텀 */
div[data-testid="stDialog"] > div[role="dialog"] {
    border-radius: 30px !important;
    border: 1px solid rgba(255, 255, 255, 0.90) !important;
    box-shadow: 0 24px 64px -12px rgba(15, 23, 42, 0.28) !important;
    background: #FFFFFF !important;
}
.gcal-modal-drag-bar {
    width: 48px;
    height: 5px;
    border-radius: 999px;
    background: #D1D6DB;
    margin: 0 auto 10px auto;
}
.gcal-row-badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 5px 10px;
    border-radius: 10px;
    font-size: 0.76rem;
    font-weight: 800;
    background: #E8F3FF;
    color: #3182F6;
    margin-bottom: 4px;
}
.gcal-row-badge.green {
    background: #E5F7F0;
    color: #00A86B;
}
</style>
"""


# ═══════════════════════════════════════════════════════════════════════════
# [Part 2: 상태 초기화 + 중앙 상세정보 모달 + UI 레이아웃 렌더링 및 이벤트 연결부]
# ═══════════════════════════════════════════════════════════════════════════

def _init_calendar_state() -> Dict[str, Any]:
    """
    달력 및 Today To Do 세션 상태를 초기화하고,
    한국 표준시(KST) 00:00 자정 경과 시 당일 날짜의 달력으로 자동 전환합니다.
    """
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
            "silent_read_count": 2,
            "panel_open": False,
            "bubble_visible": True,
            "bubble_idx": 0,
            "todo_filter": "전체",
            "todo_important_first": False,
            "todo_hide_completed": False,
            "dock_alarm_on": True,
            "dock_cal_on": True,
            "dock_input_seq": 0,
            "active_detail_modal": None,
        }
    cstate = st.session_state["cal_scheduler_state"]
    cstate.setdefault("silent_read_count", 2)
    cstate.setdefault("todo_important_first", False)
    cstate.setdefault("todo_hide_completed", False)
    cstate.setdefault("dock_alarm_on", True)
    cstate.setdefault("dock_cal_on", True)
    cstate.setdefault("dock_input_seq", 0)

    # KST 00:00 자정이 지나 날짜가 바뀌면 무조건 새 당일 날짜로 달력 & 사이드바 셀렉트박스 동기화
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


def _handle_dock_quick_submit() -> None:
    """최하단 대화형 입력칸에서 텍스트 입력 후 Enter를 쳤을 때 즉시 체크리스트에 등록합니다."""
    cstate = _init_calendar_state()
    seq = int(cstate.get("dock_input_seq", 0))
    txt_key = f"dock_chat_text_{seq}"
    time_key = f"dock_time_text_{seq}"

    raw_title = str(st.session_state.get(txt_key) or "").strip()
    if not raw_title:
        return

    raw_time = _normalize_time_str(str(st.session_state.get(time_key) or ""))
    alarm_on = bool(cstate.get("dock_alarm_on", True))
    cal_on = bool(cstate.get("dock_cal_on", True))

    year = int(cstate["year"])
    month = int(cstate["month"])
    sel_day = int(cstate["selected_day"])
    ym_key = f"{year:04d}-{month:02d}"
    month_schedules = cstate["schedules_by_ym"].setdefault(
        ym_key, _default_schedules_for_month(year, month, get_kst_today())
    )

    new_ev: Dict[str, Any] = {
        "id": f"q_{int(datetime.now().timestamp() * 1000)}",
        "type": "MY",
        "time": raw_time,
        "end_time": "",
        "title": raw_title,
        "client": "",
        "category": "내 스케줄",
        "ai_status": "작업 완료, 승인요청중",
        "done": False,
        "alarm": alarm_on,
        "in_calendar": cal_on,
        "important": False,
        "has_detail": False,
        "repeat": "반복 안함",
        "location": "",
        "link_target": "NONE",
        "sub_checks": [],
        "memo": "",
        "attachment": "",
        "desc": raw_title,
    }
    month_schedules.setdefault(sel_day, []).append(new_ev)

    # 만약 알림이 켜져 있고 오늘 날짜라면 홈버튼 말풍선에도 알림 등록
    if alarm_on and raw_time:
        cstate["bubble_visible"] = True

    cstate["dock_input_seq"] = seq + 1


@st.dialog("상세 일정 및 할 일 설정", width="large")
def _open_google_cal_style_detail_modal(modal_ctx: Dict[str, Any]) -> None:
    """
    구글 캘린더 디자인을 참고하여 우리 토스(TDS) 글래스 컨셉에 맞춘 화면 정중앙 상세정보 모달입니다.
    - 할 일 옆 파란 동그라미 '상세' 버튼 클릭 시 또는 하단 입력 바 '상세' 버튼 클릭 시 오픈됩니다.
    """
    cstate = _init_calendar_state()
    today_d = get_kst_today()

    year = int(modal_ctx.get("year", cstate["year"]))
    month = int(modal_ctx.get("month", cstate["month"]))
    day_init = int(modal_ctx.get("day", cstate["selected_day"]))
    ev_id: Optional[str] = modal_ctx.get("ev_id")
    ym_key = f"{year:04d}-{month:02d}"
    month_schedules = cstate["schedules_by_ym"].setdefault(
        ym_key, _default_schedules_for_month(year, month, today_d)
    )

    # 기존 할 일 찾기 또는 신규 초안 구성
    target_ev: Optional[Dict[str, Any]] = None
    target_day = day_init
    if ev_id:
        for d_k, ev_list in month_schedules.items():
            for item in ev_list:
                if item.get("id") == ev_id:
                    target_ev = item
                    target_day = int(d_k)
                    break
            if target_ev:
                break

    is_new = target_ev is None
    ev_data = dict(target_ev) if target_ev else {
        "id": f"dtl_{int(datetime.now().timestamp() * 1000)}",
        "type": "MY",
        "time": modal_ctx.get("draft_time") or "14:00",
        "end_time": "15:00",
        "title": modal_ctx.get("draft_title") or "",
        "client": "",
        "category": "내 스케줄",
        "done": False,
        "alarm": bool(modal_ctx.get("draft_alarm", True)),
        "in_calendar": bool(modal_ctx.get("draft_cal", True)),
        "important": False,
        "has_detail": True,
        "repeat": "반복 안함",
        "location": "",
        "link_target": "NONE",
        "sub_checks": [],
        "memo": "",
        "attachment": "",
    }

    st.markdown("<div class='gcal-modal-drag-bar'></div>", unsafe_allow_html=True)

    # 1. 제목 및 파란색 하단 포커스 라인 (구글 캘린더 시그니처)
    in_title = st.text_input(
        "제목 및 시간 추가",
        value=str(ev_data.get("title") or ""),
        placeholder="제목 및 할 일 입력 (예: (주)성진 급여 세부문자 미팅)",
        label_visibility="collapsed",
        key=f"gcal_mdl_title_{ev_data['id']}",
    )
    st.markdown(
        "<div style='height:3px;background:#3182F6;border-radius:999px;margin-top:-8px;margin-bottom:14px;'></div>",
        unsafe_allow_html=True,
    )

    # 2. 카테고리 캡슐 선택 (🔵 내 스케줄 / 🔴 세무기한 / 🟢 승인완료) + ★ 중요 핀
    cat_c1, cat_c2 = st.columns([2.8, 1.2])
    type_options = ["🔵 내 스케줄", "🔴 세무기한", "🟢 승인완료"]
    cur_type_code = str(ev_data.get("type", "MY")).upper()
    default_type_idx = 1 if cur_type_code == "TAX" else (2 if cur_type_code == "DONE" else 0)
    with cat_c1:
        sel_type_lbl = st.radio(
            "일정 분류",
            options=type_options,
            index=default_type_idx,
            horizontal=True,
            label_visibility="collapsed",
            key=f"gcal_mdl_type_{ev_data['id']}",
        )
    with cat_c2:
        in_important = st.checkbox(
            "★ 중요 핀 고정",
            value=bool(ev_data.get("important", False)),
            key=f"gcal_mdl_imp_{ev_data['id']}",
        )

    st.markdown("<hr style='margin:8px 0 14px 0;border:none;border-top:1px solid #F2F4F6;'/>", unsafe_allow_html=True)

    # 3. [시간] 행: 날짜 선택 + 시작~종료 시간 + 반복 설정 + 알림/달력 토글
    st.markdown("<span class='gcal-row-badge'>🕒 시간 · 반복 · 알림</span>", unsafe_allow_html=True)
    max_d = calendar.monthrange(year, month)[1]
    t_c1, t_c2, t_c3, t_c4 = st.columns([1.5, 1.0, 1.0, 1.2])
    with t_c1:
        in_day = st.selectbox(
            "날짜",
            options=list(range(1, max_d + 1)),
            index=min(max(1, target_day), max_d) - 1,
            format_func=lambda d: f"{year}년 {month}월 {d}일 ({_WEEKDAYS_SHORT[date(year, month, d).weekday()]})",
            label_visibility="collapsed",
            key=f"gcal_mdl_day_{ev_data['id']}",
        )
    with t_c2:
        in_time = st.text_input(
            "시작 시각",
            value=str(ev_data.get("time") or "14:00"),
            placeholder="14:00",
            label_visibility="collapsed",
            key=f"gcal_mdl_stime_{ev_data['id']}",
        )
    with t_c3:
        in_end_time = st.text_input(
            "종료 시각",
            value=str(ev_data.get("end_time") or "15:00"),
            placeholder="15:00",
            label_visibility="collapsed",
            key=f"gcal_mdl_etime_{ev_data['id']}",
        )
    with t_c4:
        rep_opts = ["반복 안함", "매일 반복", "매주 반복", "매월 반복", "매년 반복"]
        cur_rep = str(ev_data.get("repeat") or "반복 안함")
        rep_idx = rep_opts.index(cur_rep) if cur_rep in rep_opts else 0
        in_repeat = st.selectbox(
            "반복",
            options=rep_opts,
            index=rep_idx,
            label_visibility="collapsed",
            key=f"gcal_mdl_rep_{ev_data['id']}",
        )

    al_c1, al_c2 = st.columns(2)
    with al_c1:
        in_alarm = st.checkbox(
            "🔔 정각 홈버튼 알림 + 시간 옆 빛나는 종 표시",
            value=bool(ev_data.get("alarm", True)),
            key=f"gcal_mdl_alarm_{ev_data['id']}",
        )
    with al_c2:
        in_cal = st.checkbox(
            "📅 좌측 메인 달력에 이 일정 표시",
            value=bool(ev_data.get("in_calendar", True)),
            key=f"gcal_mdl_cal_{ev_data['id']}",
        )

    # 4. [거래처] & [연결] 행: 기장 거래처 매칭 & 에이전트AI 작업화면 바로가기
    st.markdown("<span class='gcal-row-badge'>🏢 거래처 매칭 & 업무 화면 연결</span>", unsafe_allow_html=True)
    cl_c1, cl_c2 = st.columns([1.4, 1.2])
    with cl_c1:
        in_client = st.text_input(
            "기장 거래처 / 담당자",
            value=str(ev_data.get("client") or ""),
            placeholder="예: (주)성진 · 김성진 대표님 (카톡 연동)",
            key=f"gcal_mdl_client_{ev_data['id']}",
        )
    with cl_c2:
        in_location = st.text_input(
            "위치 / 미팅 방법",
            value=str(ev_data.get("location") or ""),
            placeholder="예: 3층 회의실 / 전화·카톡 미팅",
            key=f"gcal_mdl_loc_{ev_data['id']}",
        )

    link_opts = [
        ("NONE", "연결 안함 (일반 일정)"),
        ("PAYROLL_EMP", "🚀 [인건비 자동화 > 급여명세서] 화면 연결"),
        ("PAYROLL_BIZ", "🚀 [인건비 자동화 > 사업소득] 화면 연결"),
        ("AGENT", "🚀 [자율 에이전트AI] 세법 검토 화면 연결"),
        ("CREDIT", "🚀 [통합고용세액공제] 분석 화면 연결"),
    ]
    cur_link = str(ev_data.get("link_target") or "NONE")
    link_codes = [x[0] for x in link_opts]
    link_idx = link_codes.index(cur_link) if cur_link in link_codes else 0

    lk_c1, lk_c2 = st.columns([2.2, 1.0])
    with lk_c1:
        in_link_target = st.selectbox(
            "업무 화면 바로가기 설정",
            options=link_codes,
            index=link_idx,
            format_func=lambda code: dict(link_opts).get(code, code),
            label_visibility="collapsed",
            key=f"gcal_mdl_link_{ev_data['id']}",
        )
    with lk_c2:
        if in_link_target != "NONE":
            if st.button("🚀 연결된 화면 열기", width="stretch", key=f"gcal_btn_jump_{ev_data['id']}"):
                _switch_app_navigation_to(in_link_target)
                st.toast("연결된 업무 화면으로 이동합니다.", icon="🚀")
                st.rerun()

    # 5. [체크] 행: 추천 기능 ① 하위 세부 체크항목 (2/3 진행률 배지 자동 연동)
    sub_list: List[Dict[str, Any]] = list(ev_data.get("sub_checks") or [])
    done_sub_cnt = sum(1 for s in sub_list if s.get("done"))
    st.markdown(
        f"<span class='gcal-row-badge green'>☑️ 하위 세부 체크항목 ({done_sub_cnt}/{len(sub_list)} 완료 — 할 일 옆에 {done_sub_cnt}/{len(sub_list)} 배지로 표시)</span>",
        unsafe_allow_html=True,
    )

    updated_subs: List[Dict[str, Any]] = []
    for s_idx, s_item in enumerate(sub_list):
        sc_col1, sc_col2 = st.columns([6.0, 0.8])
        with sc_col1:
            s_checked = st.checkbox(
                str(s_item.get("text") or ""),
                value=bool(s_item.get("done", False)),
                key=f"gcal_sub_chk_{ev_data['id']}_{s_idx}",
            )
        with sc_col2:
            del_sub = st.button("✕", key=f"gcal_sub_del_{ev_data['id']}_{s_idx}", help="세부 항목 삭제")
        if not del_sub:
            updated_subs.append({"text": str(s_item.get("text") or ""), "done": s_checked})
        else:
            target_ev_ref = target_ev if target_ev is not None else ev_data
            target_ev_ref["sub_checks"] = [x for i, x in enumerate(sub_list) if i != s_idx]
            st.rerun()

    ns_c1, ns_c2 = st.columns([4.2, 1.2])
    with ns_c1:
        new_sub_txt = st.text_input(
            "새 세부 체크항목 추가",
            placeholder="예: 대표님께 카톡으로 급여명세서 초안 발송",
            label_visibility="collapsed",
            key=f"gcal_new_sub_inp_{ev_data['id']}",
        )
    with ns_c2:
        if st.button("＋ 세부항목 추가", width="stretch", key=f"gcal_btn_add_sub_{ev_data['id']}"):
            if new_sub_txt and new_sub_txt.strip():
                updated_subs.append({"text": new_sub_txt.strip(), "done": False})
                if target_ev is not None:
                    target_ev["sub_checks"] = updated_subs
                    target_ev["has_detail"] = True
                st.rerun()

    # 6. [메모 & 첨부파일] 행
    st.markdown("<span class='gcal-row-badge'>📝 상세 메모 & 첨부파일</span>", unsafe_allow_html=True)
    in_memo = st.text_area(
        "상세 메모",
        value=str(ev_data.get("memo") or ev_data.get("desc") or ""),
        placeholder="세무 검토 특이사항이나 미팅 메모를 입력하세요...",
        height=68,
        label_visibility="collapsed",
        key=f"gcal_mdl_memo_{ev_data['id']}",
    )
    in_attach = st.text_input(
        "첨부파일명 또는 문서 경로",
        value=str(ev_data.get("attachment") or ""),
        placeholder="예: (주)성진_2026년11월_급여대장_세전자료.xlsx",
        key=f"gcal_mdl_attach_{ev_data['id']}",
    )

    # 7. 하단 담당자 정보 & [삭제] / [취소] / [저장] 버튼
    st.markdown(
        _html("""
        <div style="display:flex;align-items:center;gap:8px;font-size:0.78rem;font-weight:700;color:#6B7684;margin:10px 0;">
            <span style="width:10px;height:10px;border-radius:50%;background:#3182F6;display:inline-block;"></span>
            <span>김범준 · 한가함 · 기본 공개 설정 · 정각 홈버튼 알림 연동</span>
        </div>
        """),
        unsafe_allow_html=True,
    )

    f_b1, f_b2, f_b3 = st.columns([1.0, 1.0, 1.4])
    with f_b1:
        if not is_new:
            if st.button("🗑️ 삭제", width="stretch", key=f"gcal_btn_del_{ev_data['id']}"):
                month_schedules[target_day] = [x for x in month_schedules.get(target_day, []) if x.get("id") != ev_id]
                st.toast("일정이 삭제되었습니다.", icon="🗑️")
                st.rerun()
    with f_b2:
        if st.button("취소", width="stretch", key=f"gcal_btn_cancel_{ev_data['id']}"):
            st.rerun()
    with f_b3:
        if st.button("저장", type="primary", width="stretch", key=f"gcal_btn_save_{ev_data['id']}"):
            final_title = in_title.strip() or "세무 일정"
            final_time = _normalize_time_str(in_time)
            new_type = "TAX" if "세무기한" in sel_type_lbl else ("DONE" if "승인완료" in sel_type_lbl else "MY")
            new_cat = "세무기한" if new_type == "TAX" else ("승인완료" if new_type == "DONE" else "내 스케줄")

            # 하위 체크항목이 모두 완료(예: 3/3)되었으면 본 할 일도 자동 완료 연동
            all_subs_done = (len(updated_subs) > 0 and all(s.get("done") for s in updated_subs))
            is_done = True if (new_type == "DONE" or all_subs_done) else bool(ev_data.get("done", False))

            saved_obj: Dict[str, Any] = {
                "id": ev_data["id"],
                "type": "DONE" if is_done else new_type,
                "time": final_time,
                "end_time": _normalize_time_str(in_end_time),
                "title": final_title,
                "client": in_client.strip(),
                "category": "승인완료" if is_done else new_cat,
                "ai_status": "사용자 승인완료" if is_done else "작업 완료, 승인요청중",
                "done": is_done,
                "alarm": bool(in_alarm),
                "in_calendar": bool(in_cal),
                "important": bool(in_important),
                "has_detail": True,
                "repeat": in_repeat,
                "location": in_location.strip(),
                "link_target": in_link_target,
                "sub_checks": updated_subs,
                "memo": in_memo.strip(),
                "attachment": in_attach.strip(),
                "desc": in_memo.strip() or final_title,
            }

            new_day_int = int(in_day)
            if not is_new and target_day in month_schedules:
                month_schedules[target_day] = [x for x in month_schedules[target_day] if x.get("id") != ev_id]
            month_schedules.setdefault(new_day_int, []).append(saved_obj)
            cstate["selected_day"] = new_day_int
            st.toast(f"{month}월 {new_day_int}일 상세 일정이 저장되었습니다.", icon="✅")
            st.rerun()


def render_calendar_sidebar() -> None:
    """좌측 사이드바 ('달력' 모드 전용 제어판 — KST 기준일 표시 + 카톡 백그라운드 시뮬레이터 5종)"""
    cstate = _init_calendar_state()
    today_d = get_kst_today()
    wd_str = _WEEKDAYS_SHORT[today_d.weekday()]

    # 1. 달력 기준일 · 연월 이동 카드
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
            st.session_state["cal_sb_year_sel"] = today_d.year
            st.session_state["cal_sb_month_sel"] = today_d.month
            st.rerun()

    # 2. 카톡 백그라운드 시뮬레이터 (체험버튼 ①~⑤)
    with st.container(border=True):
        sim_pill = "<span style='font-size:0.66rem;font-weight:700;padding:2px 8px;border-radius:999px;background:#FFF4E5;color:#D97706;'>체험버튼</span>"
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

    # 3. 사이드바 하단 푸터 (카톡 감시 엔진 + To-Do 열기 / 초기화)
    with st.container(border=True):
        st.markdown(
            _html("""
            <div style="display:flex;align-items:center;justify-content:space-between;font-size:0.74rem;color:#8B95A1;margin-bottom:8px;">
                <span>카톡 감시 엔진</span>
                <span style="font-weight:700;color:#00A86B;background:#E5F7F0;padding:2px 8px;border-radius:999px;">● 실시간 켜짐</span>
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
    """
    메인 화면 렌더링:
    1) 상단 토스 워크스페이스 필 바
    2) 좌측: 요일 최상단 배치 & 바닥까지 꽉 차는 30% 반투명 글래스 달력 (2/3)
    3) 우측: '2026년 + 11월'(A안) & '＋ 일정 추가하기' 헤더 + 'Today To Do' 체크리스트 & 최하단 일체형 독 바 (1/3)
    4) 우측 하단: 드래그 가능한 미소 얼굴 홈버튼 + 직각 네모 말풍선 + 60% 확장 To-Do 오버레이
    """
    cstate = _init_calendar_state()
    today_d = get_kst_today()
    now_hm = get_kst_now_hm()

    st.markdown(CALENDAR_MAIN_CSS, unsafe_allow_html=True)

    user_nm = str(st.session_state.get("current_workspace") or "범준").strip() or "범준"
    if user_nm.startswith("익명"):
        user_nm = "범준"
    silent_cnt = int(cstate.get("silent_read_count", 2))

    # 1. 상단 토스 필 바
    st.markdown(
        _html(f"""
        <div class="tds-workspace-pill-bar">
            <div class="tds-wp-left">
                <span class="tds-wp-user">👨‍💼 {_html_lib.escape(user_nm)}님의 워크스페이스</span>
                <span class="tds-wp-sep">|</span>
                <span class="tds-wp-silent">카톡 자동 닫기(1소거): <b>단순인사 {silent_cnt}건 완료</b></span>
            </div>
            <div>
                <span class="tds-wp-right-badge">
                    😊 우측 하단 웃는 홈버튼은 드래그로 이동 가능하며 클릭 시 60% To-Do가 열립니다
                </span>
            </div>
        </div>
        """),
        unsafe_allow_html=True,
    )

    year = int(cstate["year"])
    month = int(cstate["month"])
    selected_day = int(cstate["selected_day"])
    ym_key = f"{year:04d}-{month:02d}"
    month_schedules = cstate["schedules_by_ym"].setdefault(
        ym_key, _default_schedules_for_month(year, month, today_d)
    )

    # 2. 메인 본문 2단 레이아웃: 좌측 확장형 달력 (2.0) + 우측 Today To Do (1.0)
    col_cal, col_side = st.columns([2.0, 1.0], gap="large")

    with col_cal:
        with st.container(key="cal_glass_surface"):
            # 달력 최상단 요일(일~토) 배치
            dow_html = "".join(
                f"<div class='tds-cal-dow-cell {'sun' if i == 0 else ('sat' if i == 6 else '')}'>{d_lbl}</div>"
                for i, d_lbl in enumerate(_SUN_FIRST_HEADERS)
            )
            st.markdown(f"<div class='tds-cal-dow-grid
