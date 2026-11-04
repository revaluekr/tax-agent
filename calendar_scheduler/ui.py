# -*- coding: utf-8 -*-
"""
달력 스케줄러 + 카톡 백그라운드 시뮬레이터 + 드래그 가능한 우측 하단 미소 얼굴 홈버튼 + 60% 확장 To-Do 오버레이 (calendar_scheduler/ui.py)

[Part 1: 라이브러리 Import + 스타일/CSS 정의 + 핵심 비즈니스 로직/함수부]
[Part 2: 상태 초기화 + UI 레이아웃 렌더링 및 이벤트 연결부]
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
_WEEKDAYS_FULL = ("월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일")
_SUN_FIRST_HEADERS = ("일", "월", "화", "수", "목", "금", "토")


def _html(s: str) -> str:
    """여러 줄 HTML을 한 줄로 이어 붙여 표시 (빈 줄·들여쓰기로 인해 코드 블록으로 인식되는 현상 방지)"""
    return " ".join(ln.strip() for ln in str(s).splitlines() if ln.strip())


def get_kst_today() -> date:
    """한국 표준시(KST, Asia/Seoul) 기준 오늘 날짜를 반환합니다."""
    return datetime.now(ZoneInfo("Asia/Seoul")).date()


def _default_schedules_for_month(year: int, month: int, today_d: date) -> Dict[int, List[Dict[str, Any]]]:
    """
    당해 연월의 기본 세무 일정 및 카카오톡 백그라운드 자동화 연계 일정을 생성합니다.
    - 3색 구분(TAX: 세무기한 / MY: 내 스케줄 / DONE: 카톡 승인완료)과
      기존 v3 ai_status 필드를 동시에 100% 호환합니다.
    """
    focus_day = today_d.day if (today_d.year == year and today_d.month == month) else 4
    last_day = calendar.monthrange(year, month)[1]
    focus_day = min(max(1, focus_day), last_day)

    data: Dict[int, List[Dict[str, Any]]] = {
        focus_day: [
            {
                "id": f"sch_{year}_{month}_{focus_day}_1",
                "type": "MY",
                "time": "09:30",
                "title": "시범법인 통장 자동분개 점검",
                "client": "시범법인",
                "category": "내 스케줄",
                "ai_status": "작업 완료, 승인요청중",
                "done": False,
                "desc": "법인 통장 입출금 내역 자동분개 규칙 점검 및 이상 거래 확인",
            },
            {
                "id": f"sch_{year}_{month}_{focus_day}_2",
                "type": "MY",
                "time": "14:00",
                "title": "(주)모 대표님 세무자문 미팅",
                "client": "(주)모",
                "category": "내 스케줄",
                "ai_status": "작업 완료, 승인요청중",
                "done": False,
                "desc": "가족 단기 아르바이트 인건비 필요경비 및 통합고용세액공제 자문 미팅",
            },
            {
                "id": f"sch_{year}_{month}_{focus_day}_3",
                "type": "DONE",
                "time": "10:15",
                "title": "(주)성진 급여명세서 자동작성 완료",
                "client": "(주)성진",
                "category": "승인완료",
                "ai_status": "사용자 승인완료",
                "done": True,
                "desc": "카톡 급여대장 엑셀 수신 → 지정 폴더 저장 및 급여명세서 2명 자동 작성 완료",
            },
        ],
        10: [
            {
                "id": f"sch_{year}_{month}_10_1",
                "type": "TAX",
                "time": "기한",
                "title": "원천세 · 지방소득세 신고납부",
                "client": "전체 기장 거래처",
                "category": "세무기한",
                "ai_status": "작업 완료, 승인요청중",
                "done": False,
                "desc": "원천징수이행상황신고서 마감 및 거래처별 납부서 카톡 일괄 안내",
            },
            {
                "id": f"sch_{year}_{month}_10_2",
                "type": "TAX",
                "time": "기한",
                "title": f"4대보험 {max(1, month - 1)}월분 납부기한",
                "client": "전체 기장 거래처",
                "category": "세무기한",
                "ai_status": "작업 완료, 승인요청중",
                "done": False,
                "desc": "국민연금·건강보험·고용·산재보험 당월 고지분 납부 마감",
            },
        ],
        16: [
            {
                "id": f"sch_{year}_{month}_16_1",
                "type": "MY",
                "time": "11:00",
                "title": "두리님과 10개 법인 통장규칙 점검",
                "client": "내부 업무",
                "category": "내 스케줄",
                "ai_status": "백그라운드 작업중",
                "done": False,
                "desc": "주요 기장 법인 10곳 통장 적요별 계정과목 매핑 규칙 점검",
            },
        ],
        25: [
            {
                "id": f"sch_{year}_{month}_25_1",
                "type": "TAX",
                "time": "기한",
                "title": "개별소비세 · 증권거래세 신고",
                "client": "해당 법인 거래처",
                "category": "세무기한",
                "ai_status": "작업 완료, 승인요청중",
                "done": False,
                "desc": "당월분 개별소비세 및 증권거래세 정기 신고·납부 기한",
            },
        ],
        last_day: [
            {
                "id": f"sch_{year}_{month}_{last_day}_1",
                "type": "TAX",
                "time": "기한",
                "title": "종합소득세 중간예납 납부기한",
                "client": "개인사업자 거래처",
                "category": "세무기한",
                "ai_status": "작업 완료, 승인요청중",
                "done": False,
                "desc": "종합소득세 중간예납 고지세액 납부 안내 및 추계신고 대상 점검",
            },
            {
                "id": f"sch_{year}_{month}_{last_day}_2",
                "type": "TAX",
                "time": "기한",
                "title": "일용근로·간이지급명세서 제출",
                "client": "인건비 신고 거래처",
                "category": "세무기한",
                "ai_status": "작업 완료, 승인요청중",
                "done": False,
                "desc": "일용근로소득 및 거주자 사업소득 간이지급명세서 정기 제출 기한",
            },
        ],
    }
    return data


def _default_kakao_todos(today_d: date) -> List[Dict[str, Any]]:
    """
    우측 하단 60% 확장 패널에 표시할 카카오톡 백그라운드 자동화 To-Do 리스트 초기값 (6개 시나리오 완벽 반영)
    """
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


def _get_status_counts(cstate: Dict[str, Any]) -> Dict[str, int]:
    """오버레이 필터 탭 및 일정 건수 집계"""
    ym_key = f"{int(cstate['year']):04d}-{int(cstate['month']):02d}"
    month_map = cstate["schedules_by_ym"].get(ym_key, {})
    sel_day = int(cstate.get("selected_day", 1))
    day_items = month_map.get(sel_day, [])

    todos = cstate.get("kakao_todos", [])
    working_cnt = sum(1 for t in todos if t.get("status") == "백그라운드 작업중" or t.get("status_code") == "WORKING")
    req_cnt = sum(1 for t in todos if t.get("status") == "작업 완료, 승인요청중" or t.get("status_code") == "READY")
    done_cnt = sum(1 for t in todos if t.get("status") == "사용자 승인완료" or t.get("status_code") == "APPROVED")
    return {
        "day_schedules": len(day_items),
        "month_schedules": sum(len(v) for v in month_map.values()),
        "working": working_cnt,
        "approval_req": req_cnt,
        "approved": done_cnt,
        "total_todos": len(todos),
    }


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
                {"name": "오지현 연구원", "dept": "연구소", "title": "선임연구원", "base_pay": 4200000, "meal": 20
