# -*- coding: utf-8 -*-
"""
달력 스케줄러 + 카톡 백그라운드 시뮬레이터 + 우측 하단 미소 얼굴 홈버튼 + 60% 확장 To-Do 오버레이 (calendar_scheduler/ui.py)

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
    - to_do.html의 3색 범례(TAX: 세무기한 🔴 / MY: 내 스케줄 🔵 / DONE: 카톡 승인완료 🟢)와
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
    우측 하단 60% 확장 패널에 표시할 카카오톡 백그라운드 자동화 To-Do 리스트 초기값 (to_do.html 6개 시나리오 완벽 반영)
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
            "kakao_original": "[카톡 수신] 외주 디자이너 김지훈(920315-1******) 세전 150만 원 이체했습니다. 사업소득 신고 부탁드려요.",
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
    """달력 상단 3대 KPI 카드 및 오버레이 필터 탭용 건수 집계"""
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
        _push_kakao_biz_income_to_payroll("(주)스타마케팅", "강민호", "940722-1******", 2500000, is_net=False)
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
            "kakao_original": "[카톡 수신] 강민호 940722-1****** 이번 달 외주비 세전 250만 원 지급했습니다. 사업소득 신고 부탁드려요!",
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
/* ═════════ Toss Web TDS & to_do.html 달력·백그라운드 To-Do 전용 스타일 ═════════ */
[data-testid="stApp"] [data-testid="stMain"],
[data-testid="stApp"] [data-testid="stAppScrollToBottomContainer"],
[data-testid="stApp"] [data-testid="stBottom"] > div {
    background: #F4F6FA !important;
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
    margin-bottom: 18px;
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

/* 2. 달력 상단 3대 KPI 카드 (좌측 2/3, 높이 74px 고정) */
.tds-top-status-row {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 12px;
    height: 74px;
    margin-bottom: 14px;
}
.tds-stat-card {
    background: rgba(255, 255, 255, 0.82);
    backdrop-filter: blur(16px);
    border: 1px solid rgba(255, 255, 255, 0.92);
    border-radius: 22px;
    padding: 13px 18px;
    height: 74px;
    box-sizing: border-box;
    display: flex;
    align-items: center;
    justify-content: space-between;
    box-shadow: 0 8px 24px -6px rgba(25, 31, 40, 0.05);
    transition: transform 0.16s ease, border-color 0.16s ease;
}
.tds-stat-card:hover {
    border-color: #3182F6;
    transform: translateY(-1px);
}
.tds-stat-label {
    font-size: 0.78rem;
    font-weight: 700;
    color: #6B7684;
    line-height: 1.2;
}
.tds-stat-val {
    font-size: 1.48rem;
    font-weight: 800;
    color: #191F28;
    margin-top: 2px;
    letter-spacing: -0.5px;
    line-height: 1.15;
    font-variant-numeric: tabular-nums;
}
.tds-stat-val.amber { color: #F59E0B; }
.tds-stat-val.red { color: #F04452; }
.tds-stat-icon {
    width: 36px;
    height: 36px;
    border-radius: 14px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 0.95rem;
    font-weight: 800;
    flex: none;
}
.tds-stat-icon.blue { background: #E8F3FF; color: #3182F6; }
.tds-stat-icon.amber { background: #FFF4E5; color: #D97706; }
.tds-stat-icon.red { background: #FFF0F0; color: #F04452; }

/* 3. 달력 상단 우측 '11월' 초대형 텍스트 & '＋ 일정 추가하기' (높이 74px 라인 일치) */
.tds-month-heading-box {
    display: flex;
    align-items: center;
    justify-content: flex-start;
    height: 74px;
    margin-bottom: 14px;
    padding-left: 4px;
    box-sizing: border-box;
    user-select: none;
}
.tds-month-big-text {
    font-size: 3.35rem;
    font-weight: 900;
    color: #191F28;
    letter-spacing: -2px;
    line-height: 0.88;
    font-variant-numeric: tabular-nums;
}
[data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-cal_add_btn_wrap {
    display: flex !important;
    align-items: center !important;
    justify-content: flex-end !important;
    height: 74px !important;
    margin-bottom: 14px !important;
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
    min-height: 48px !important;
    height: 48px !important;
    padding: 0 18px !important;
    box-shadow: 0 4px 14px rgba(49, 130, 246, 0.24) !important;
    width: auto !important;
}
[data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-cal_add_btn_wrap div.stButton > button:hover {
    background: #1B64DA !important;
    border-color: #1B64DA !important;
}

/* 4. 30% 반투명 글래스모피즘 달력 본체 & 우측 할 일 글래스 카드 */
[data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-cal_glass_surface,
[data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-cal_right_todo_card {
    background: rgba(255, 255, 255, 0.30) !important;
    backdrop-filter: blur(22px) saturate(180%) !important;
    -webkit-backdrop-filter: blur(22px) saturate(180%) !important;
    border: 1px solid rgba(255, 255, 255, 0.68) !important;
    box-shadow: 0 12px 34px -8px rgba(25, 31, 40, 0.06) !important;
    border-radius: 28px !important;
    padding: 20px !important;
}

.tds-cal-card-hdr {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    margin-bottom: 14px;
    padding-bottom: 12px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.55);
}
.tds-cal-card-hdr-l {
    display: flex;
    align-items: center;
    gap: 10px;
}
.tds-cal-ym-title {
    font-size: 1.12rem;
    font-weight: 800;
    color: #191F28;
}
.tds-cal-glass-pill {
    font-size: 0.72rem;
    font-weight: 800;
    background: rgba(255, 255, 255, 0.65);
    color: #3182F6;
    padding: 4px 10px;
    border-radius: 999px;
}
.tds-cal-legend {
    display: flex;
    align-items: center;
    gap: 12px;
    font-size: 0.74rem;
    font-weight: 700;
    color: #4E5968;
}
.tds-cal-legend-item {
    display: inline-flex;
    align-items: center;
    gap: 5px;
}
.tds-cal-legend-dot {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    display: inline-block;
}
.tds-cal-legend-dot.red { background: #F04452; }
.tds-cal-legend-dot.blue { background: #3182F6; }
.tds-cal-legend-dot.green { background: #00A86B; }

.tds-cal-dow-grid {
    display: grid;
    grid-template-columns: repeat(7, 1fr);
    gap: 8px;
    margin-bottom: 8px;
    text-align: center;
}
.tds-cal-dow-cell {
    font-size: 0.76rem;
    font-weight: 800;
    color: #6B7684;
    padding: 4px 0;
}
.tds-cal-dow-cell.sun { color: #F04452; }
.tds-cal-dow-cell.sat { color: #3182F6; }

/* 달력 날짜 셀 (30% 반투명 글래스 + 20px 라운드) */
.tds-cal-day-card {
    background: rgba(255, 255, 255, 0.30);
    backdrop-filter: blur(10px);
    -webkit-backdrop-filter: blur(10px);
    border: 1px solid rgba(255, 255, 255, 0.60);
    border-radius: 20px;
    min-height: 86px;
    padding: 10px;
    box-sizing: border-box;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    transition: all 0.18s cubic-bezier(0.16, 1, 0.3, 1);
    margin-bottom: 4px;
}
.tds-cal-day-card:hover {
    background: rgba(255, 255, 255, 0.58);
    transform: translateY(-2px);
    box-shadow: 0 8px 20px -6px rgba(49, 130, 246, 0.14);
}
.tds-cal-day-card.selected {
    background: rgba(255, 255, 255, 0.72) !important;
    border: 2px solid #3182F6 !important;
    box-shadow: 0 10px 24px -6px rgba(49, 130, 246, 0.22);
}
.tds-cal-day-card.empty {
    background: rgba(255, 255, 255, 0.10);
    border: 1px dashed rgba(229, 232, 235, 0.40);
}
.tds-cal-day-top {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 4px;
}
.tds-cal-day-num {
    font-size: 0.82rem;
    font-weight: 800;
    color: #191F28;
    font-variant-numeric: tabular-nums;
}
.tds-cal-day-num.sun { color: #F04452; }
.tds-cal-day-num.sat { color: #3182F6; }
.tds-cal-today-badge {
    font-size: 0.62rem;
    font-weight: 800;
    color: #FFFFFF;
    background: #3182F6;
    padding: 2px 7px;
    border-radius: 999px;
}
.tds-cal-ev-list {
    display: flex;
    flex-direction: column;
    gap: 3px;
}
.tds-cal-ev-pill {
    font-size: 0.68rem;
    font-weight: 800;
    padding: 2px 7px;
    border-radius: 7px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    line-height: 1.35;
}
.tds-cal-ev-pill.blue { background: rgba(232, 243, 255, 0.92); color: #3182F6; }
.tds-cal-ev-pill.red { background: rgba(255, 240, 240, 0.92); color: #F04452; }
.tds-cal-ev-pill.green { background: rgba(229, 247, 240, 0.92); color: #00A86B; }
.tds-cal-ev-more {
    font-size: 0.65rem;
    font-weight: 800;
    color: #6B7684;
    padding-left: 3px;
}

/* 날짜 셀 클릭 투명 오버레이 (셀 아래 별도 '1일 (0건)' 버튼 노출 완전 제거 — to_do.html 100% 동일) */
[data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-cal_sel_d_"] {
    margin-top: -94px !important;
    height: 86px !important;
    position: relative !important;
    z-index: 5 !important;
}
[data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-cal_sel_d_"] div.stButton,
[data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-cal_sel_d_"] div.stButton > button {
    width: 100% !important;
    height: 86px !important;
    min-height: 86px !important;
    opacity: 0 !important;
    cursor: pointer !important;
    border: none !important;
    background: transparent !important;
    box-shadow: none !important;
    padding: 0 !important;
    margin: 0 !important;
}

/* 5. 우측 '선택한 날짜의 할 일' 패널 내부 스타일 */
.tds-side-hdr {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding-bottom: 12px;
    margin-bottom: 12px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.55);
}
.tds-side-sub {
    font-size: 0.74rem;
    font-weight: 700;
    color: #6B7684;
}
.tds-side-title {
    font-size: 1.05rem;
    font-weight: 800;
    color: #191F28;
    margin-top: 2px;
    letter-spacing: -0.3px;
}
.tds-side-badge {
    font-size: 0.74rem;
    font-weight: 800;
    padding: 4px 10px;
    border-radius: 999px;
    background: #3182F6;
    color: #FFFFFF;
}
.tds-day-ev-card {
    padding: 13px 14px;
    border-radius: 16px;
    background: rgba(255, 255, 255, 0.82);
    border: 1px solid #FFFFFF;
    box-shadow: 0 2px 6px rgba(25, 31, 40, 0.03);
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 8px;
    margin-bottom: 8px;
}
.tds-day-ev-left {
    display: flex;
    align-items: flex-start;
    gap: 10px;
}
.tds-day-ev-dot {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    margin-top: 6px;
    flex: none;
}
.tds-day-ev-dot.blue { background: #3182F6; }
.tds-day-ev-dot.red { background: #F04452; }
.tds-day-ev-dot.green { background: #00A86B; }
.tds-day-ev-meta {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-bottom: 3px;
}
.tds-day-ev-tag {
    font-size: 0.68rem;
    font-weight: 800;
    padding: 2px 8px;
    border-radius: 999px;
}
.tds-day-ev-tag.blue { background: #E8F3FF; color: #3182F6; }
.tds-day-ev-tag.red { background: #FFF0F0; color: #F04452; }
.tds-day-ev-tag.green { background: #E5F7F0; color: #00A86B; }
.tds-day-ev-time {
    font-size: 0.70rem;
    font-weight: 700;
    color: #8B95A1;
}
.tds-day-ev-title {
    font-size: 0.85rem;
    font-weight: 800;
    color: #191F28;
    line-height: 1.35;
}
.tds-quick-add-hdr {
    font-size: 0.76rem;
    font-weight: 800;
    color: #333D4B;
    margin-top: 12px;
    padding-top: 12px;
    border-top: 1px solid rgba(255, 255, 255, 0.55);
    margin-bottom: 6px;
}
</style>
"""


# ═══════════════════════════════════════════════════════════════════════════
# [Part 2: 상태 초기화 + UI 레이아웃 렌더링 및 이벤트 연결부]
# ═══════════════════════════════════════════════════════════════════════════

def _init_calendar_state() -> Dict[str, Any]:
    """달력 및 카톡 백그라운드 To-Do 세션 상태를 초기화하고 KST 날짜 변경을 자동 감지합니다."""
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
            "show_add_modal": False,
        }
    cstate = st.session_state["cal_scheduler_state"]
    cstate.setdefault("silent_read_count", 2)
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


def render_calendar_sidebar() -> None:
    """
    좌측 사이드바 ('달력' 모드 전용 제어판 — to_do.html의 카톡 백그라운드 시뮬레이터 5종 & 하단 푸터 완벽 이식)
    """
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
            st.rerun()

    # 2. 카톡 백그라운드 시뮬레이터 (to_do.html 체험버튼 ①~⑤ 그대로 이식)
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
    메인 화면:
    1) 상단 워크스페이스 필 바 (👨‍💼 범준님의 워크스페이스 | 카톡 자동 닫기(1소거): 단순인사 N건 완료)
    2) 달력 상단 3대 KPI 카드 (일정 / AI작업중 / 작업완료, 승인요청) + 우측 초대형 '11월' & '＋ 일정 추가하기'
    3) 좌측 30% 반투명 글래스 달력 (2/3) + 우측 선택한 날짜의 할 일 & '⚡ 빠른 일정 등록' 글래스 카드 (1/3)
    4) 우측 하단 미소 얼굴 홈버튼 + 직각 네모 말풍선 + 60% 확장 To-Do 오버레이
    """
    cstate = _init_calendar_state()
    today_d = get_kst_today()
    counts = _get_status_counts(cstate)

    st.markdown(CALENDAR_MAIN_CSS, unsafe_allow_html=True)

    user_nm = str(st.session_state.get("current_workspace") or "범준").strip() or "범준"
    if user_nm.startswith("익명"):
        user_nm = "범준"
    silent_cnt = int(cstate.get("silent_read_count", 2))

    # 1. 상단 토스 필 바 (to_do.html Top Toss Pill Bar)
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
                    😊 우측 하단 웃는 홈버튼을 누르면 60% To-Do 화면이 열립니다
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

    # 2. 달력 상단 구성: 좌측 3대 KPI 카드 (74px) + 우측 초대형 'N월' & '＋ 일정 추가하기' (74px)
    col_top_left, col_top_right = st.columns([2.0, 1.0], gap="large")

    with col_top_left:
        st.markdown(
            _html(f"""
            <div class="tds-top-status-row">
                <div class="tds-stat-card">
                    <div>
                        <div class="tds-stat-label">일정</div>
                        <div class="tds-stat-val">{counts['day_schedules']}건</div>
                    </div>
                    <span class="tds-stat-icon blue">📅</span>
                </div>
                <div class="tds-stat-card">
                    <div>
                        <div class="tds-stat-label">AI작업중</div>
                        <div class="tds-stat-val amber">{counts['working']}건</div>
                    </div>
                    <span class="tds-stat-icon amber">⏳</span>
                </div>
                <div class="tds-stat-card">
                    <div>
                        <div class="tds-stat-label">작업완료, 승인요청</div>
                        <div class="tds-stat-val red">{counts['approval_req']}건</div>
                    </div>
                    <span class="tds-stat-icon red">🔔</span>
                </div>
            </div>
            """),
            unsafe_allow_html=True,
        )

    with col_top_right:
        c_m_left, c_m_right = st.columns([1.1, 1.0], gap="small")
        with c_m_left:
            st.markdown(
                _html(f"""
                <div class="tds-month-heading-box">
                    <span class="tds-month-big-text">{month}월</span>
                </div>
                """),
                unsafe_allow_html=True,
            )
        with c_m_right:
            with st.container(key="cal_add_btn_wrap"):
                if st.button("＋ 일정 추가하기", type="primary", key="btn_cal_open_add_schedule"):
                    cstate["show_add_modal"] = not cstate.get("show_add_modal", False)
                    st.rerun()

    # 새 일정 추가 모달/카드 폼 (to_do.html scheduleModal 대응)
    if cstate.get("show_add_modal"):
        with st.container(border=True):
            st.markdown(f"##### 📅 {year}년 {month}월 새 일정 추가하기")
            max_day = calendar.monthrange(year, month)[1]
            m_c1, m_c2, m_c3 = st.columns([1.0, 1.2, 1.8])
            with m_c1:
                in_day = st.selectbox(
                    "날짜 선택",
                    options=list(range(1, max_day + 1)),
                    index=min(selected_day, max_day) - 1,
                    format_func=lambda d: f"{year}년 {month}월 {d}일",
                    key="modal_day_select",
                )
            with m_c2:
                in_type_lbl = st.selectbox(
                    "일정 종류",
                    options=[
                        "📌 내 스케줄 (미팅·결산·방문)",
                        "🔴 세무 법정 신고·납부기한",
                        "🟢 카톡 승인완료 기록",
                    ],
                    key="modal_type_select",
                )
            with m_c3:
                in_title = st.text_input(
                    "일정 내용",
                    placeholder="예: (주)갑 3분기 가결산 미팅",
                    key="modal_title_input",
                )

            b_c1, b_c2 = st.columns([1, 1])
            with b_c1:
                if st.button("저장하기", type="primary", width="stretch", key="btn_save_schedule_modal"):
                    ttl = in_title.strip() or "세무 일정"
                    d_int = int(in_day)
                    ev_t = "TAX" if "세무" in in_type_lbl else ("DONE" if "승인완료" in in_type_lbl else "MY")
                    month_schedules.setdefault(d_int, []).append({
                        "id": f"m_{int(datetime.now().timestamp() * 1000)}",
                        "type": ev_t,
                        "time": "기한" if ev_t == "TAX" else "일정",
                        "title": ttl,
                        "client": "거래처",
                        "category": "세무기한" if ev_t == "TAX" else ("승인완료" if ev_t == "DONE" else "내 스케줄"),
                        "ai_status": "사용자 승인완료" if ev_t == "DONE" else "작업 완료, 승인요청중",
                        "done": (ev_t == "DONE"),
                        "desc": ttl,
                    })
                    cstate["selected_day"] = d_int
                    cstate["show_add_modal"] = False
                    st.toast(f"{month}월 {d_int}일에 일정이 추가되었어요.", icon="📅")
                    st.rerun()
            with b_c2:
                if st.button("취소", width="stretch", key="btn_cancel_schedule_modal"):
                    cstate["show_add_modal"] = False
                    st.rerun()

    # 3. 메인 본문: 좌측 30% 반투명 글래스 달력 (2.0) + 우측 선택한 날짜의 할 일 & 빠른 일정 등록 (1.0)
    col_cal, col_side = st.columns([2.0, 1.0], gap="large")

    with col_cal:
        with st.container(key="cal_glass_surface"):
            st.markdown(
                _html(f"""
                <div class="tds-cal-card-hdr">
                    <div class="tds-cal-card-hdr-l">
                        <span class="tds-cal-ym-title">{year}년 {month}월</span>
                        <span class="tds-cal-glass-pill">30% 반투명 글래스 모드</span>
                    </div>
                    <div class="tds-cal-legend">
                        <span class="tds-cal-legend-item"><span class="tds-cal-legend-dot red"></span>세무기한</span>
                        <span class="tds-cal-legend-item"><span class="tds-cal-legend-dot blue"></span>내 스케줄</span>
                        <span class="tds-cal-legend-item"><span class="tds-cal-legend-dot green"></span>카톡 승인완료</span>
                    </div>
                </div>
                """),
                unsafe_allow_html=True,
            )

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

                            evs = month_schedules.get(day_num, [])
                            pills_html = ""
                            for ev in evs[:2]:
                                p_cls = _ev_pill_cls(ev)
                                pills_html += f"<div class='tds-cal-ev-pill {p_cls}'>{_html_lib.escape(str(ev.get('title', '')))}</div>"
                            if len(evs) > 2:
                                pills_html += f"<div class='tds-cal-ev-more'>+{len(evs) - 2}건</div>"

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
        sel_date_obj = date(year, month, min(selected_day, calendar.monthrange(year, month)[1]))
        sel_wd_full = _WEEKDAYS_FULL[sel_date_obj.weekday()]
        is_sel_today = (sel_date_obj == today_d)
        today_suffix = " · 오늘" if is_sel_today else ""
        day_evs = month_schedules.get(selected_day, [])

        with st.container(key="cal_right_todo_card"):
            st.markdown(
                _html(f"""
                <div class="tds-side-hdr">
                    <div>
                        <div class="tds-side-sub">선택한 날짜의 할 일</div>
                        <div class="tds-side-title">{month}월 {selected_day}일 {sel_wd_full}{today_suffix}</div>
                    </div>
                    <span class="tds-side-badge">{len(day_evs)}건</span>
                </div>
                """),
                unsafe_allow_html=True,
            )

            if not day_evs:
                st.markdown(
                    _html("""
                    <div style="padding:20px;border-radius:16px;background:rgba(255,255,255,0.55);text-align:center;font-size:0.82rem;color:#8B95A1;font-weight:600;">
                        등록된 일정이 없어요.<br/>아래에서 새 일정을 추가해 보세요.
                    </div>
                    """),
                    unsafe_allow_html=True,
                )
            else:
                for idx_e, ev in enumerate(list(day_evs)):
                    dot_cls, tag_lbl, tag_cls = _status_pill_cls(ev)
                    ev_time = _html_lib.escape(str(ev.get("time") or "일정"))
                    ev_title = _html_lib.escape(str(ev.get("title") or ""))
                    c_ev_l, c_ev_r = st.columns([5.2, 1.0], gap="small")
                    with c_ev_l:
                        st.markdown(
                            _html(f"""
                            <div class="tds-day-ev-card">
                                <div class="tds-day-ev-left">
                                    <span class="tds-day-ev-dot {dot_cls}"></span>
                                    <div>
                                        <div class="tds-day-ev-meta">
                                            <span class="tds-day-ev-tag {tag_cls}">{tag_lbl}</span>
                                            <span class="tds-day-ev-time">{ev_time}</span>
                                        </div>
                                        <div class="tds-day-ev-title">{ev_title}</div>
                                    </div>
                                </div>
                            </div>
                            """),
                            unsafe_allow_html=True,
                        )
                    with c_ev_r:
                        if st.button("✕", key=f"btn_del_day_ev_{ev.get('id', idx_e)}_{idx_e}", help="일정 삭제"):
                            month_schedules[selected_day] = [x for i, x in enumerate(day_evs) if i != idx_e]
                            st.rerun()

            # 우측 하단: ⚡ 빠른 일정 등록 (to_do.html quickScheduleInput & btnQuickScheduleAdd 완벽 이식)
            st.markdown("<div class='tds-quick-add-hdr'>⚡ 빠른 일정 등록</div>", unsafe_allow_html=True)
            q_c1, q_c2 = st.columns([3.2, 1.1], gap="small")
            with q_c1:
                quick_val = st.text_input(
                    "빠른 일정 입력",
                    placeholder="예: (주)모 가결산 미팅 14시",
                    label_visibility="collapsed",
                    key=f"quick_sch_inp_{year}_{month}_{selected_day}",
                )
            with q_c2:
                if st.button("등록", type="primary", width="stretch", key=f"btn_quick_sch_add_{year}_{month}_{selected_day}"):
                    if quick_val and quick_val.strip():
                        month_schedules.setdefault(selected_day, []).append({
                            "id": f"q_{int(datetime.now().timestamp() * 1000)}",
                            "type": "MY",
                            "time": "일정",
                            "title": quick_val.strip(),
                            "client": "내 스케줄",
                            "category": "내 스케줄",
                            "ai_status": "작업 완료, 승인요청중",
                            "done": False,
                            "desc": quick_val.strip(),
                        })
                        st.toast(f"{month}월 {selected_day}일에 일정이 등록되었어요.", icon="📅")
                        st.rerun()

    # 4. 우측 하단 플로팅 홈버튼 + 직각 네모 말풍선 + 60% 애니메이션 확장 To-Do 오버레이 렌더링
    render_floating_kakao_todo_overlay()


def render_floating_kakao_todo_overlay() -> None:
    """
    to_do.html의 우측 하단 플로팅 미소 홈버튼(#3898FF, 귀·머리카락 없는 동그라미 선 + 세로 두 눈 SVG) +
    직각 네모 말풍선(6px, [다음 ▸] / [체크리스트 열기]) +
    60% 확장 To-Do 오버레이(전체/작업중/승인요청중/승인완료 컬러 탭, 카톡 원문 + AI 결과 2단 박스,
    [뒤쪽 작업화면에 띄우기], [승인요청 건 모두 승인하기], [홈버튼으로 접기 ↘])를
    window.parent.document에 마운트합니다.
    """
    cstate = _init_calendar_state()
    todos = cstate.get("kakao_todos", [])
    panel_open_init = bool(cstate.get("panel_open", False))
    silent_cnt = int(cstate.get("silent_read_count", 2))
    user_nm = str(st.session_state.get("current_workspace") or "범준").strip() or "범준"
    if user_nm.startswith("익명"):
        user_nm = "범준"

    todos_json = json.dumps(todos, ensure_ascii=False)
    init_open_js = "true" if panel_open_init else "false"
    user_nm_json = json.dumps(user_nm, ensure_ascii=False)

    components.html(
        f"""
        <script>
        (function() {{
            const parentDoc = window.parent.document;
            const TODOS_DATA = {todos_json};
            const INIT_OPEN = {init_open_js};
            const CURRENT_USER = {user_nm_json};
            const SILENT_CNT = {silent_cnt};

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

                /* 60% 확장 To-Do 오버레이 패널 (to_do.html .todo-overlay-panel) */
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
                    box-shadow: 0 24px 64px -12px rgba(15, 23, 42, 0.26), 0 0 0 1px rgba(15, 23, 42, 0.05);
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
                    border-radius: 999px;
                    background: #191F28;
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
                }}
                .tds-kp-sub {{
                    font-size: 0.76rem;
                    color: #8B95A1;
                    font-weight: 500;
                    margin-top: 2px;
                }}
                .tds-kp-hdr-r {{
                    display: flex;
                    align-items: center;
                    gap: 8px;
                }}
                .tds-kp-approve-all-btn {{
                    padding: 8px 16px;
                    border-radius: 16px;
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
                    border-radius: 16px;
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

                /* 컬러 필 필터 탭 바 */
                .tds-kp-tabs-bar {{
                    background: rgba(255, 255, 255, 0.90);
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
                    border-radius: 16px;
                    font-size: 0.78rem;
                    font-weight: 700;
                    border: none;
                    cursor: pointer;
                    transition: all 0.15s ease;
                }}
                .tds-kp-tab.all {{ background: #191F28; color: #FFFFFF; font-weight: 800; }}
                .tds-kp-tab.working {{ background: #FFF4E5; color: #D97706; }}
                .tds-kp-tab.ready {{ background: #FFF0F0; color: #F04452; }}
                .tds-kp-tab.approved {{ background: #E5F7F0; color: #00A86B; }}
                .tds-kp-tab.active-ring {{
                    outline: 2px solid #3182F6;
                    outline-offset: 1px;
                }}
                .tds-kp-silent-info {{
                    font-size: 0.74rem;
                    color: #8B95A1;
                    font-weight: 700;
                }}
                .tds-kp-silent-info b {{
                    color: #3182F6;
                }}

                /* 스크롤 가능한 To-Do 카드 본문 */
                .tds-kp-body {{
                    flex: 1;
                    overflow-y: auto;
                    padding: 20px;
                    background: #FFFFFF;
                    display: flex;
                    flex-direction: column;
                    gap: 12px;
                }}
                .tds-kp-card {{
                    background: #FFFFFF;
                    border-radius: 24px;
                    border: 1px solid #E5E8EB;
                    padding: 20px;
                    box-shadow: 0 2px 6px rgba(15, 23, 42, 0.02);
                    transition: box-shadow 0.15s ease;
                }}
                .tds-kp-card:hover {{
                    box-shadow: 0 6px 18px rgba(15, 23, 42, 0.06);
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
                    font-size: 0.74rem;
                    font-weight: 800;
                }}
                .tds-kp-st-badge.working {{ background: #FFF4E5; color: #D97706; }}
                .tds-kp-st-badge.ready {{ background: #FFF0F0; color: #F04452; }}
                .tds-kp-st-badge.approved {{ background: #E5F7F0; color: #00A86B; }}
                .tds-kp-cat-pill {{
                    font-size: 0.75rem;
                    font-weight: 700;
                    color: #4E5968;
                    background: #F2F4F6;
                    padding: 2px 10px;
                    border-radius: 999px;
                }}
                .tds-kp-time {{
                    font-size: 0.74rem;
                    color: #8B95A1;
                    font-weight: 600;
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
                    background: #F9FAFB;
                    padding: 10px 14px;
                    border-radius: 16px;
                    margin-bottom: 8px;
                    font-weight: 500;
                }}
                .tds-kp-ai-res {{
                    font-size: 0.80rem;
                    color: #191F28;
                    background: rgba(232, 243, 255, 0.55);
                    padding: 10px 14px;
                    border-radius: 16px;
                    white-space: pre-line;
                    line-height: 1.55;
                    margin-bottom: 12px;
                    font-weight: 500;
                }}
                .tds-kp-actions {{
                    display: flex;
                    align-items: center;
                    justify-content: flex-end;
                    gap: 8px;
                }}
                .tds-kp-btn-jump {{
                    padding: 8px 14px;
                    border-radius: 16px;
                    background: #F2F4F6;
                    color: #333D4B;
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
                    border-radius: 16px;
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
                    border-radius: 16px;
                    background: #F59E0B;
                    color: #FFFFFF;
                    border: none;
                    font-size: 0.78rem;
                    font-weight: 800;
                    cursor: pointer;
                }}
                .tds-kp-btn-finish:hover {{
                    background: #D97706;
                }}
                .tds-kp-done-txt {{
                    font-size: 0.76rem;
                    font-weight: 800;
                    color: #00A86B;
                }}

                /* 오버레이 하단 푸터 */
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
                    border-radius: 12px;
                    background: #F2F4F6;
                    border: none;
                    font-weight: 700;
                    color: #333D4B;
                    cursor: pointer;
                }}
                .tds-kp-min-btn:hover {{
                    background: #E5E8EB;
                }}

                /* 직각 네모 말풍선 (to_do.html .square-speech-bubble) */
                #tds-kakao-square-bubble {{
                    background: #FFFFFF;
                    border: 2px solid #3182F6;
                    border-radius: 6px;
                    box-shadow: 0 18px 38px -10px rgba(25, 31, 40, 0.18);
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
                    border-radius: 4px;
                    font-size: 0.68rem;
                    font-weight: 800;
                    background: #E8F3FF;
                    color: #3182F6;
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
                    border-radius: 4px;
                    background: #F2F4F6;
                    border: none;
                    color: #4E5968;
                    font-size: 0.72rem;
                    font-weight: 700;
                    cursor: pointer;
                }}
                .tds-sb-btn-next:hover {{
                    background: #E5E8EB;
                }}
                .tds-sb-btn-open {{
                    padding: 4px 12px;
                    border-radius: 4px;
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

                /* 우측 하단 파란 홈버튼 (to_do.html #floatingHomeBtn + .cute-face-svg) */
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
                    cursor: pointer;
                    transition: transform 0.2s ease, background 0.2s ease;
                }}
                #tds-kakao-home-fab:hover {{
                    background: #2584F4;
                    transform: scale(1.05);
                }}
                #tds-kakao-home-fab:active {{
                    transform: scale(0.95);
                }}
                .cute-face-svg {{
                    animation: cuteWinkBounce 2.8s ease-in-out infinite;
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
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    box-shadow: 0 2px 6px rgba(240, 68, 82, 0.4);
                    z-index: 10;
                }}
            `;

            let rootEl = parentDoc.getElementById("tds-kakao-floating-root");
            if (!rootEl) {{
                rootEl = parentDoc.createElement("div");
                rootEl.id = "tds-kakao-floating-root";
                parentDoc.body.appendChild(rootEl);
            }}

            // to_do.html 원본 그대로: 귀/머리카락 없는 동그라미 선 + 세로 두 눈 캐릭터 SVG
            const FAB_ICON_CLOSED_SVG = `
                <svg class="cute-face-svg" width="46" height="46" viewBox="0 0 32 32" fill="none">
                    <circle cx="16" cy="16" r="12.5" stroke="#FFFFFF" stroke-width="2.9" stroke-linecap="round" stroke-linejoin="round" />
                    <line x1="11.8" y1="13.2" x2="11.8" y2="18.5" stroke="#FFFFFF" stroke-width="3.0" stroke-linecap="round" />
                    <line x1="20.2" y1="13.2" x2="20.2" y2="18.5" stroke="#FFFFFF" stroke-width="3.0" stroke-linecap="round" />
                </svg>
            `;
            const FAB_ICON_OPEN_SVG = `
                <svg width="28" height="28" viewBox="0 0 24 24" fill="none">
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

            if (!window.parent._tdsKakaoState) {{
                window.parent._tdsKakaoState = {{
                    open: INIT_OPEN,
                    filter: "ALL",
                    bubbleIdx: 0,
                    bubbleDismissed: false,
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

            function renderOverlay() {{
                const stObj = window.parent._tdsKakaoState;
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
                            stBadgeHtml = `<span class="tds-kp-st-badge approved">✓ 사용자 승인완료</span>`;
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
                const bTime = `${{bItem.time_ago || "방금 전"}} · 웃는 홈버튼 클릭 시 60% 열림`;

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
                                <button class="tds-kp-close-btn" id="tds-kp-close" title="닫기">✕</button>
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
                            <button class="tds-sb-dismiss" id="tds-sb-dismiss" title="말풍선 닫기">✕</button>
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

                const fabBtn = parentDoc.getElementById("tds-kakao-home-fab");
                const closeBtn = parentDoc.getElementById("tds-kp-close");
                const minBtn = parentDoc.getElementById("tds-kp-minimize");
                const backdropEl = parentDoc.getElementById("tds-kakao-backdrop");
                const approveAllBtn = parentDoc.getElementById("tds-kp-approve-all");
                const sbDismiss = parentDoc.getElementById("tds-sb-dismiss");
                const sbNext = parentDoc.getElementById("tds-sb-next");
                const sbOpen = parentDoc.getElementById("tds-sb-open");

                if (fabBtn) {{
                    fabBtn.onclick = function() {{
                        stObj.open = !stObj.open;
                        renderOverlay();
                    }};
                }}
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
