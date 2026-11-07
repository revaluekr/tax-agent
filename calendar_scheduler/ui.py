# -*- coding: utf-8 -*-
"""
달력 스케줄러 + Today To Do (메인 할 일과 카톡 백그라운드 To-Do 완전 분리) +
카톡 백그라운드 To-Do 블랙(딥 차콜) 컨셉 오버레이 (우측 상단 ✕ 개별 삭제 지원) +
시안 A 토스 아이스 블루(#DCEBFF) 상세입력 모달 (세무일정 / 달력에 표시) +
월별 실제 세무일정 자동 배치(시간 표기 제거) + 네이티브 이벤트 직결 (calendar_scheduler/ui.py)
"""
from __future__ import annotations

import calendar
import html as _html_lib
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

import streamlit as st
import streamlit.components.v1 as components

import ui_theme as _ui_theme

_WEEKDAYS_SHORT = ("월", "화", "수", "목", "금", "토", "일")
_WEEKDAYS_FULL = ("월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일")
_SUN_FIRST_HEADERS = ("일", "월", "화", "수", "목", "금", "토")
_STATE_SCHEMA_VERSION = "v28_clean_native_events_no_simulator"


def _html(s: str) -> str:
    """여러 줄 HTML을 한 줄로 이어 붙여 표시"""
    return " ".join(ln.strip() for ln in str(s).splitlines() if ln.strip())


def get_kst_today() -> date:
    """한국 표준시(KST, Asia/Seoul) 기준 오늘 날짜를 반환합니다."""
    return datetime.now(ZoneInfo("Asia/Seoul")).date()


def get_kst_now_hm() -> str:
    """한국 표준시(KST, Asia/Seoul) 기준 현재 시각(HH:MM) 문자열을 반환합니다."""
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%H:%M")


def _clean_any_legacy_token(raw_val: str) -> str:
    """혹시 남아 있을 수 있는 과거 내부 토큰 접미사를 깨끗하게 제거합니다."""
    s = str(raw_val or "")
    s = re.sub(r"__KAKAO_SYNC_JSON_[\s\S]*__$", "", s)
    s = re.sub(r"__LS_RESTORE_JSON_[\s\S]*__$", "", s)
    s = re.sub(r"__MONTH_SHIFT_(?:PREV|NEXT)__$", "", s)
    s = re.sub(r"__CAL_DBLCLICK_DAY_\d+__$", "", s)
    s = re.sub(r"__ENTER_COMMIT_TGL_A[01]_C[01](?:_T[0-9:]*)?__$", "", s)
    s = re.sub(r"__DTL_OPEN_TGL_A[01]_C[01](?:_T[0-9:]*)?__$", "", s)
    s = re.sub(r"__TGL_A[01]_C[01](?:_T[0-9:]*)?__$", "", s)
    return s.strip()


def _make_tax_ev(
    ev_id: str,
    title: str,
    client: str,
    desc: str,
    repeat: str = "매월 반복",
    urgent: bool = False,
    has_detail: bool = False,
    sub_tasks: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    """세무일정(빨간 배지) 기본 일정 딕셔너리 생성 헬퍼 (앞쪽 시간 표기 없음)"""
    return {
        "id": ev_id,
        "type": "TAX",
        "time": "",
        "title": title,
        "client": client,
        "category": "세무일정",
        "ai_status": "작업 완료, 승인요청중",
        "done": False,
        "alarm": False,
        "alarm_glow": False,
        "show_on_cal": True,
        "urgent": urgent,
        "has_detail": has_detail,
        "repeat": repeat,
        "location": "홈택스 / 위택스",
        "link_target": "CALENDAR",
        "link_label": "",
        "attachment": "",
        "sub_tasks": list(sub_tasks) if sub_tasks else [],
        "desc": desc,
    }


def _default_schedules_for_month(year: int, month: int, today_d: date) -> Dict[int, List[Dict[str, Any]]]:
    """
    1월~12월 각 달의 실제 대한민국 세법상 정기 세무일정을 정확한 날짜에 자동 배치합니다.
    - 모든 세무일정(TAX)은 시간 문자열을 비워('time': '') 달력 셀에 제목만 깔끔하게 표시합니다.
    """
    last_day = calendar.monthrange(year, month)[1]
    prev_m = 12 if month == 1 else (month - 1)

    data: Dict[int, List[Dict[str, Any]]] = {
        10: [
            _make_tax_ev(
                ev_id=f"sch_{year}_{month}_10_1",
                title="원천세 · 지방소득세 신고납부",
                client="전체 기장 거래처",
                desc="원천징수이행상황신고서 마감 및 거래처별 납부서 카톡 일괄 안내",
                repeat="매월 반복",
                urgent=True,
                has_detail=True,
                sub_tasks=[
                    {"title": "원천징수이행상황신고서 마감 검증", "done": True},
                    {"title": "거래처별 납부서 카톡 일괄 안내", "done": False},
                ],
            ),
            _make_tax_ev(
                ev_id=f"sch_{year}_{month}_10_2",
                title=f"4대보험 {prev_m}월분 납부기한",
                client="전체 기장 거래처",
                desc="국민연금·건강보험·고용·산재보험 당월 고지분 납부 마감",
                repeat="매월 반복",
            ),
        ],
        last_day: [
            _make_tax_ev(
                ev_id=f"sch_{year}_{month}_{last_day}_common",
                title="일용근로·간이지급명세서 제출",
                client="인건비 신고 거래처",
                desc="일용근로소득 및 거주자 사업소득 간이지급명세서 정기 제출 기한",
                repeat="매월 반복",
            ),
        ],
    }

    if month == 1:
        data.setdefault(25, []).append(
            _make_tax_ev(
                ev_id=f"sch_{year}_1_25_vat",
                title="부가가치세 제2기 확정신고·납부",
                client="법인·개인 과세사업자 거래처",
                desc="전년도 제2기 부가가치세 확정신고 및 납부 마감",
                repeat="매년 반복",
                urgent=True,
            )
        )
        data[last_day].insert(
            0,
            _make_tax_ev(
                ev_id=f"sch_{year}_1_{last_day}_half",
                title="근로소득 간이지급명세서(하반기) 제출",
                client="상시근로자 고용 거래처",
                desc="전년도 하반기(7~12월) 근로소득 간이지급명세서 제출 마감",
                repeat="매년 반복",
                urgent=True,
            ),
        )
    elif month == 2:
        data[10].append(
            _make_tax_ev(
                ev_id=f"sch_{year}_2_10_exempt",
                title="면세사업자 사업장현황신고",
                client="병·의원·학원 등 면세사업자",
                desc="전년도 귀속 개인 면세사업자 사업장현황신고 및 수입금액 검토",
                repeat="매년 반복",
                urgent=True,
            )
        )
    elif month == 3:
        data[10].append(
            _make_tax_ev(
                ev_id=f"sch_{year}_3_10_yearend",
                title="연말정산 지급명세서 제출·환급신청",
                client="전체 원천징수 거래처",
                desc="근로·퇴직·사업소득 지급명세서 제출 및 연말정산 환급신청 마감",
                repeat="매년 반복",
                urgent=True,
            )
        )
        data[last_day].insert(
            0,
            _make_tax_ev(
                ev_id=f"sch_{year}_3_{last_day}_corp",
                title="12월 결산법인 법인세 정기신고·납부",
                client="12월 결산 법인 거래처",
                desc="12월 결산법인 법인세 과세표준 및 세액신고서 제출·납부 마감",
                repeat="매년 반복",
                urgent=True,
            ),
        )
    elif month == 4:
        data.setdefault(25, []).append(
            _make_tax_ev(
                ev_id=f"sch_{year}_4_25_vat",
                title="부가가치세 제1기 예정신고·납부",
                client="법인 및 예정고지 대상 개인거래처",
                desc="제1기 부가가치세 예정신고(법인) 및 예정고지세액 납부(개인) 마감",
                repeat="매년 반복",
                urgent=True,
            )
        )
        data[last_day].insert(
            0,
            _make_tax_ev(
                ev_id=f"sch_{year}_4_{last_day}_localcorp",
                title="법인지방소득세 확정신고·납부",
                client="12월 결산 법인 거래처",
                desc="12월 결산법인 법인지방소득세 위택스 확정신고 및 납부 마감",
                repeat="매년 반복",
                urgent=True,
            ),
        )
    elif month == 5:
        data[last_day].insert(
            0,
            _make_tax_ev(
                ev_id=f"sch_{year}_5_{last_day}_inc",
                title="종합소득세·개인지방소득세 확정신고",
                client="개인사업자 및 종소세 신고 대상",
                desc="전년도 귀속 종합소득세 및 개인지방소득세 확정신고·납부 마감",
                repeat="매년 반복",
                urgent=True,
            ),
        )
    elif month == 6:
        data[last_day].insert(
            0,
            _make_tax_ev(
                ev_id=f"sch_{year}_6_{last_day}_sincere",
                title="성실신고확인 대상 종합소득세 신고",
                client="성실신고확인 대상 개인거래처",
                desc="성실신고확인서 첨부 대상 사업자 종합소득세 확정신고·납부 마감",
                repeat="매년 반복",
                urgent=True,
            ),
        )
    elif month == 7:
        data.setdefault(25, []).append(
            _make_tax_ev(
                ev_id=f"sch_{year}_7_25_vat",
                title="부가가치세 제1기 확정신고·납부",
                client="법인·개인 과세사업자 거래처",
                desc="당해 제1기 부가가치세 확정신고 및 납부 마감",
                repeat="매년 반복",
                urgent=True,
            )
        )
        data[last_day].insert(
            0,
            _make_tax_ev(
                ev_id=f"sch_{year}_7_{last_day}_half1",
                title="근로소득 간이지급명세서(상반기) 제출",
                client="상시근로자 고용 거래처",
                desc="당해 상반기(1~6월) 근로소득 간이지급명세서 제출 마감",
                repeat="매년 반복",
                urgent=True,
            ),
        )
    elif month == 8:
        data[last_day].insert(
            0,
            _make_tax_ev(
                ev_id=f"sch_{year}_8_{last_day}_corp_mid",
                title="12월 결산법인 법인세 중간예납",
                client="12월 결산 법인 거래처",
                desc="12월 결산법인 법인세 중간예납 신고 및 납부 마감",
                repeat="매년 반복",
                urgent=True,
            ),
        )
    elif month == 9:
        data[last_day].insert(
            0,
            _make_tax_ev(
                ev_id=f"sch_{year}_9_{last_day}_prop",
                title="재산세(토지·주택 2기분) 납부기한",
                client="부동산 보유 거래처",
                desc="9월 정기분 재산세(토지 및 주택 2기분) 고지세액 납부 안내",
                repeat="매년 반복",
            ),
        )
    elif month == 10:
        data.setdefault(25, []).append(
            _make_tax_ev(
                ev_id=f"sch_{year}_10_25_vat",
                title="부가가치세 제2기 예정신고·납부",
                client="법인 및 예정고지 대상 개인거래처",
                desc="제2기 부가가치세 예정신고(법인) 및 예정고지세액 납부(개인) 마감",
                repeat="매년 반복",
                urgent=True,
            )
        )
    elif month == 11:
        data.setdefault(25, []).append(
            _make_tax_ev(
                ev_id=f"sch_{year}_11_25_excise",
                title="개별소비세 · 교통에너지환경세 신고",
                client="해당 과세물품 거래처",
                desc="전월분 개별소비세 및 교통·에너지·환경세 정기 신고·납부 기한",
                repeat="매월 반복",
            )
        )
        data[last_day].insert(
            0,
            _make_tax_ev(
                ev_id=f"sch_{year}_11_{last_day}_inc_mid",
                title="종합소득세 중간예납 납부기한",
                client="개인사업자 거래처",
                desc="종합소득세 중간예납 고지세액 납부 안내 및 추계신고 대상 점검",
                repeat="매년 반복",
                urgent=True,
            ),
        )
    elif month == 12:
        data.setdefault(15, []).append(
            _make_tax_ev(
                ev_id=f"sch_{year}_12_15_comp_prop",
                title="종합부동산세 납부기한",
                client="종부세 대상 법인·개인 거래처",
                desc="당해 귀속 종합부동산세 고지세액 확인 및 특례·합산배제 신고·납부",
                repeat="매년 반복",
                urgent=True,
            )
        )

    return data


def _default_kakao_todos(today_d: date) -> List[Dict[str, Any]]:
    """
    우측 하단 60% 확장 패널에 표시할 카카오톡 백그라운드 자동화 To-Do 리스트 초기값.
    - 초기 실행 시 샘플 데이터 없이 0건(빈 리스트)으로 깔끔하게 시작합니다.
    """
    return []


def push_kakao_background_todo(
    title: str,
    client: str = "",
    category: str = "AI 카톡 자동화",
    status_code: str = "READY",
    kakao_original: str = "",
    workflow_steps: List[Dict[str, Any]] | None = None,
    ai_result: str = "",
    attachment: str = "",
    bubble_msg: str = "",
    target_mode: str = "CALENDAR",
    action_label: str = "카톡 답장 복사 & 승인완료",
) -> Dict[str, Any]:
    """
    실제 카카오톡 자동 AI 시스템에서 새로운 카톡 작업을 수신·처리했을 때
    백그라운드 To-Do 리스트(kakao_todos)와 우측 하단 홈버튼 말풍선에 즉시 등록하는 공식 연동 함수입니다.
    """
    cstate = _init_calendar_state()
    status_map = {
        "WORKING": "백그라운드 작업중",
        "READY": "작업 완료, 승인요청중",
        "APPROVED": "사용자 승인완료",
    }
    norm_code = str(status_code or "READY").upper()
    today_iso = get_kst_today().isoformat()
    new_item = {
        "id": f"kt_{int(datetime.now().timestamp() * 1000)}",
        "status_code": norm_code,
        "status": status_map.get(norm_code, "작업 완료, 승인요청중"),
        "category": category,
        "client": client,
        "recipient": "범준",
        "time_ago": "방금 전",
        "bubble_msg": bubble_msg or f"범준님, {client or '거래처'} 카톡 자동화 작업이 완료되었습니다",
        "title": title,
        "kakao_original": kakao_original or f"[카톡 수신] {title}",
        "workflow_steps": workflow_steps or [
            {"step": "① 카카오톡 메시지/파일 수신 및 요청사항 분석", "done": True},
            {"step": "② 세법·증빙 검토 및 백그라운드 자동 작업 수행", "done": norm_code != "WORKING"},
            {"step": "③ 발송용 카톡 답장 초안 및 첨부자료 준비 완료", "done": norm_code == "READY" or norm_code == "APPROVED"},
        ],
        "ai_result": ai_result,
        "preview": ai_result,
        "attachment": attachment,
        "target_mode": target_mode,
        "action_label": action_label,
        "checked": norm_code == "APPROVED",
        "created_date_iso": today_iso,
        "approved_date_iso": today_iso if norm_code == "APPROVED" else None,
    }
    cstate.setdefault("kakao_todos", []).insert(0, new_item)
    if norm_code == "READY":
        cstate["bubble_visible"] = True
        cstate["bubble_idx"] = 0
    _save_user_schedules_to_disk(cstate)
    return new_item


def _status_pill_cls(ev: Dict[str, Any]) -> tuple[str, str, str]:
    """일정 항목의 (점 색상 클래스, 태그 라벨, 태그 배경 클래스) 반환"""
    ev_type = str(ev.get("type", "")).upper()
    ai_st = str(ev.get("ai_status", ""))
    cat_str = str(ev.get("category", ""))
    if ev_type == "TAX" or "기한" in cat_str or "세무일정" in cat_str:
        return ("red", "세무일정", "red")
    if ev_type == "DONE" or ev.get("done") or "승인완료" in ai_st:
        return ("green", "승인완료", "green")
    return ("blue", "내 스케줄", "blue")


def _ev_pill_cls(ev: Dict[str, Any]) -> str:
    """달력 날짜 셀 내부 이벤트 배지 색상 클래스 반환 ('red' | 'green' | 'blue')"""
    dot_cls, _, _ = _status_pill_cls(ev)
    return dot_cls


def _normalize_time_str(raw_t: str) -> str:
    """사용자 입력 시간 문자열(예: '1430', '4:30', '04:30', '')을 숫자 전용 'HH:MM' 또는 ''로 정규화"""
    s = _clean_any_legacy_token(str(raw_t or "")).strip()
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
    """종 반짝임(노랑-주황-빨강) 작동 조건 (오늘 KST 시간 기준)"""
    if not ev.get("alarm") or ev.get("done"):
        return False
    if ev.get("alarm_glow"):
        return True
    t_norm = _normalize_time_str(str(ev.get("time", "")))
    if not t_norm:
        return True
    now_hm = get_kst_now_hm()
    return now_hm >= t_norm


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
    cstate["_sync_sb_from_cstate"] = True


def _jump_to_target_mode(target_mode: str) -> None:
    """상세 모달 내부에서 업무 화면 바로가기 클릭 시 앱 모드 전환"""
    st.session_state["_sbx_cat_jump_seq"] = int(st.session_state.get("_sbx_cat_jump_seq", 0)) + 1
    if target_mode == "AGENT":
        st.session_state["app_mode"] = "자율 에이전트AI"
        st.session_state["app_top_mode"] = "AGENT"
    elif target_mode in ("PAYROLL_EMP", "PAYROLL_BIZ"):
        st.session_state["app_mode"] = "인건비 자동화"
        st.session_state["app_top_mode"] = "PAYROLL_AUTO"
        try:
            from payroll_automated.ui import _get_payroll_state
            pstate = _get_payroll_state()
            pstate["sub_mode"] = "FREE" if target_mode == "PAYROLL_BIZ" else "EMP"
            pstate["sub_tab"] = "사업소득" if target_mode == "PAYROLL_BIZ" else "급여명세서"
        except Exception:
            pass


CALENDAR_MAIN_CSS = """
<style>
/* ═════════ Toss Web TDS 달력 + Today To Do 규격 100% 일치 스타일 ═════════ */
[data-testid="stApp"],
[data-testid="stApp"] [data-testid="stMain"],
[data-testid="stApp"] [data-testid="stAppScrollToBottomContainer"],
[data-testid="stApp"] [data-testid="stBottom"] > div,
header[data-testid="stHeader"] {
    background: #F4F6FA !important;
    background-color: #F4F6FA !important;
    font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, system-ui, sans-serif !important;
    letter-spacing: -0.02em !important;
}
section[data-testid="stSidebar"] {
    background: #FFFFFF !important;
    border-right: 1px solid #E4ECF7 !important;
    box-shadow: 4px 0 22px rgba(25, 60, 125, 0.04) !important;
}
@keyframes sbxCatCrouchJumpA {
    0%   { transform: translateY(0px) scaleX(1) scaleY(1); }
    22%  { transform: translateY(4px) scaleX(1.18) scaleY(0.76); }
    52%  { transform: translateY(-21px) scaleX(0.90) scaleY(1.12); }
    76%  { transform: translateY(2px) scaleX(1.09) scaleY(0.90); }
    88%  { transform: translateY(-4px) scaleX(0.97) scaleY(1.03); }
    100% { transform: translateY(0px) scaleX(1) scaleY(1); }
}
@keyframes sbxCatCrouchJumpB {
    0%   { transform: translateY(0px) scaleX(1) scaleY(1); }
    22%  { transform: translateY(4px) scaleX(1.18) scaleY(0.76); }
    52%  { transform: translateY(-21px) scaleX(0.90) scaleY(1.12); }
    76%  { transform: translateY(2px) scaleX(1.09) scaleY(0.90); }
    88%  { transform: translateY(-4px) scaleX(0.97) scaleY(1.03); }
    100% { transform: translateY(0px) scaleX(1) scaleY(1); }
}
[data-testid="stApp"] section[data-testid="stSidebar"] .sbx-brand {
    display: flex !important;
    align-items: center !important;
    gap: 12px !important;
    padding: 18px 2px 14px !important;
    overflow: visible !important;
}
[data-testid="stApp"] section[data-testid="stSidebar"] .sbx-logo {
    width: 42px !important;
    height: 42px !important;
    border-radius: 14px !important;
    transform-origin: center bottom !important;
    will-change: transform !important;
    cursor: pointer !important;
}
[data-testid="stApp"] section[data-testid="stSidebar"] .sbx-logo.sbx-cat-jump-a {
    animation: sbxCatCrouchJumpA 0.52s cubic-bezier(0.22, 1, 0.36, 1) both !important;
}
[data-testid="stApp"] section[data-testid="stSidebar"] .sbx-logo.sbx-cat-jump-b {
    animation: sbxCatCrouchJumpB 0.52s cubic-bezier(0.22, 1, 0.36, 1) both !important;
}
[data-testid="stApp"] section[data-testid="stSidebar"] .sbx-brand-t {
    font-size: 1.38rem !important;
    font-weight: 800 !important;
    color: #191F28 !important;
    letter-spacing: -0.03em !important;
    line-height: 1.15 !important;
    white-space: nowrap !important;
}

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

@keyframes tdsBellSparkleOnly {
    0%, 100% { color: #FACC15; transform: scale(1.0) rotate(0deg); }
    25% { color: #F97316; transform: scale(1.14) rotate(-14deg); }
    50% { color: #EF4444; transform: scale(1.20) rotate(14deg); }
    75% { color: #F97316; transform: scale(1.12) rotate(-8deg); }
}

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
    border: 1px solid #E2ECF8;
    border-radius: 16px;
    height: 74px;
    min-height: 74px;
    max-height: 74px;
    padding: 0 18px;
    box-sizing: border-box;
    display: flex;
    align-items: center;
    justify-content: space-between;
    box-shadow: 0 10px 26px rgba(25, 60, 125, 0.06), 0 2px 8px rgba(25, 60, 125, 0.03);
    transition: box-shadow 0.18s ease, transform 0.18s ease;
}
.tds-cal-kpi-card:hover {
    box-shadow: 0 14px 32px rgba(49, 130, 246, 0.12), 0 4px 10px rgba(25, 60, 125, 0.05);
    transform: translateY(-2px);
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
    position: relative;
    z-index: 20;
}
.tds-soft-arrow-btn svg { pointer-events: none; }
.tds-soft-arrow-btn:hover {
    background: #E8F3FF;
    border-color: #90C2FF;
    color: #3182F6;
    transform: translateY(-1px);
}
.tds-soft-arrow-btn:active { transform: translateY(0px) scale(0.96); }

[data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-cal_hidden_month_nav_wrap {
    position: fixed !important;
    left: -9999px !important;
    top: -9999px !important;
    width: 1px !important;
    height: 1px !important;
    overflow: hidden !important;
    opacity: 0 !important;
    pointer-events: none !important;
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
    cursor: pointer !important;
}
[data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-cal_add_btn_wrap div.stButton > button:hover {
    background: #1B64DA !important;
}

[data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-cal_glass_surface {
    background: rgba(255, 255, 255, 0.20) !important;
    background-color: rgba(255, 255, 255, 0.20) !important;
    backdrop-filter: blur(22px) saturate(180%) !important;
    -webkit-backdrop-filter: blur(22px) saturate(180%) !important;
    border: 1.5px solid #DCE6F5 !important;
    box-shadow: 0 10px 28px rgba(15, 35, 75, 0.05), 0 2px 8px rgba(15, 35, 75, 0.03) !important;
    border-radius: 28px !important;
    padding: 18px 20px 22px 20px !important;
    min-height: 830px !important;
    box-sizing: border-box !important;
}

[data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-cal_right_todo_card {
    background: rgba(255, 255, 255, 0.20) !important;
    background-color: rgba(255, 255, 255, 0.20) !important;
    backdrop-filter: blur(22px) saturate(180%) !important;
    -webkit-backdrop-filter: blur(22px) saturate(180%) !important;
    border: 1.5px solid #DCE6F5 !important;
    box-shadow: 0 10px 28px rgba(15, 35, 75, 0.05), 0 2px 8px rgba(15, 35, 75, 0.03) !important;
    border-radius: 28px !important;
    padding: 22px 20px 18px 20px !important;
    min-height: 830px !important;
    display: flex !important;
    flex-direction: column !important;
    justify-content: space-between !important;
    box-sizing: border-box !important;
}

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

.tds-cal-day-card {
    background: #FFFFFF;
    border: 1.8px solid #C4D9F8;
    border-radius: 20px;
    height: 146px;
    min-height: 146px;
    padding: 12px;
    box-sizing: border-box;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    box-shadow: 0 4px 14px rgba(25, 60, 125, 0.045), 0 1px 4px rgba(0, 27, 55, 0.03);
    transition: all 0.18s cubic-bezier(0.16, 1, 0.3, 1);
    margin-bottom: 6px;
    overflow: hidden;
}
.tds-cal-day-card:hover {
    transform: translateY(-2px);
    border-color: #64A8FF;
    box-shadow: 0 8px 20px rgba(49, 130, 246, 0.11);
}
.tds-cal-day-card.selected {
    background: #FFFFFF !important;
    border: 2.5px solid #3182F6 !important;
    box-shadow: 0 8px 22px rgba(49, 130, 246, 0.15), 0 0 0 2px rgba(49, 130, 246, 0.10) !important;
}
.tds-cal-day-card.empty {
    background: rgba(255, 255, 255, 0.32);
    border: 1.5px solid rgba(196, 217, 248, 0.55);
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

.tds-empty-todo-box {
    padding: 32px 20px;
    border-radius: 22px;
    background: #FFFFFF;
    border: 1px solid #E2ECF8;
    box-shadow: 0 8px 24px rgba(25, 60, 125, 0.05), 0 2px 6px rgba(25, 60, 125, 0.03);
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

.tds-todo-card-pure {
    position: relative;
    height: 58px;
    min-height: 58px;
    background: #FFFFFF;
    border: 1px solid #E2ECF8;
    border-radius: 18px;
    padding: 0 16px;
    box-sizing: border-box;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    box-shadow: 0 6px 18px rgba(25, 60, 125, 0.05), 0 2px 6px rgba(0, 27, 55, 0.03);
    transition: border-color 0.15s ease, box-shadow 0.15s ease, transform 0.15s ease;
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
.tds-done-status-pill {
    font-size: 0.68rem;
    font-weight: 800;
    padding: 2px 9px;
    border-radius: 999px;
    border: none;
    background: #E5F9F0;
    color: #00A660;
    flex-shrink: 0;
}
.tds-rollover-pill {
    font-size: 0.68rem;
    font-weight: 800;
    padding: 2px 9px;
    border-radius: 999px;
    border: none;
    background: #FFF3E0;
    color: #D97706;
    flex-shrink: 0;
    font-variant-numeric: tabular-nums;
}
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
.tds-compact-time.done { color: #8B95A1; }
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

[data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-todo_bottom_dock_a {
    background: #FFFFFF !important;
    border: 2px solid #3182F6 !important;
    border-radius: 22px !important;
    padding: 12px 14px !important;
    box-shadow: 0 6px 18px rgba(49, 130, 246, 0.10) !important;
    margin-top: 10px !important;
}
[data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-todo_bottom_dock_a [data-testid="stVerticalBlock"] {
    gap: 8px !important;
}

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
[data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-dock_time_wrap_"] [data-testid="stTextInput"] input {
    background: transparent !important;
    border: none !important;
    height: 36px !important;
    min-height: 36px !important;
    text-align: center !important;
    font-size: 0.86rem !important;
    font-weight: 800 !important;
    color: #191F28 !important;
    font-variant-numeric: tabular-nums !important;
    padding: 0 2px !important;
}

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
[data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-todo_bottom_dock_a button.tds-dock-btn-sunken,
[data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-btn_dock_"] button.tds-dock-btn-sunken {
    background: #1854BA !important;
    background-color: #1854BA !important;
    border: 2px solid #0F3882 !important;
    box-shadow: inset 0 4px 7px rgba(10, 32, 78, 0.65), inset 0 1px 2px rgba(10, 32, 78, 0.85) !important;
    padding-top: 3px !important;
}

section[data-testid="stSidebar"] .st-key-btn_cal_go_today div.stButton > button {
    background: #F2F4F6 !important;
    color: #191F28 !important;
    font-weight: 700 !important;
    border: none !important;
    border-radius: 10px !important;
}

div[data-testid="stDialog"],
div[data-testid="stModal"],
div[data-baseweb="modal"] {
    background: transparent !important;
    background-color: transparent !important;
    backdrop-filter: none !important;
    -webkit-backdrop-filter: none !important;
}
div[data-testid="stDialog"] div[role="dialog"],
div[data-testid="stModal"] div[role="dialog"],
div[data-testid="stDialog"] [aria-label="dialog"],
div[role="dialog"][aria-modal="true"] {
    border-radius: 24px !important;
    padding: 24px 28px !important;
    border: 2.5px solid #3182F6 !important;
    box-shadow: 0 22px 54px rgba(25, 31, 40, 0.16), 0 4px 16px rgba(49, 130, 246, 0.14) !important;
    background: #DCEBFF !important;
    background-color: #DCEBFF !important;
    opacity: 1 !important;
    backdrop-filter: none !important;
    -webkit-backdrop-filter: none !important;
    max-width: 780px !important;
}
div[data-testid="stDialog"] [data-testid="stTextInput"] > div > div,
div[data-testid="stDialog"] [data-testid="stSelectbox"] > div > div,
div[data-testid="stDialog"] [data-testid="stTextArea"] > div > div,
div[data-testid="stDialog"] [data-baseweb="input"],
div[data-testid="stDialog"] [data-baseweb="select"] > div,
div[data-testid="stDialog"] [data-baseweb="textarea"] {
    background: #FFFFFF !important;
    background-color: #FFFFFF !important;
    border: 1.5px solid #90C2FF !important;
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
    background: #FFFFFF !important;
    background-color: #FFFFFF !important;
    color: #3182F6 !important;
    font-size: 0.76rem;
    font-weight: 800;
    padding: 8px 10px;
    border-radius: 999px;
    border: 1.5px solid #90C2FF;
    margin-top: 2px;
    width: 100%;
    box-sizing: border-box;
    box-shadow: 0 2px 6px rgba(49, 130, 246, 0.06);
}
div[data-testid="stDialog"] [class*="st-key-dlg_btn_add_sub_"] div.stButton > button {
    background: #FFFFFF !important;
    color: #3182F6 !important;
    font-weight: 800 !important;
    border: 1.5px solid #90C2FF !important;
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
    border: 1.5px solid #90C2FF !important;
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


def _get_user_schedule_store_paths() -> List[Path]:
    """
    프로젝트 폴더 전체를 통째로 덮어쓰거나 삭제 후 재설치해도 데이터가 살아남도록
    1) OS 사용자 홈 디렉터리(~/.tax_ai_agent/user_calendar_store.json)
    2) 프로젝트 내부 data 폴더(data/user_calendar_store.json)
    두 곳에 동시에 이중 저장하고 읽어오는 경로 리스트를 반환합니다.
    """
    candidates = [
        Path.home() / ".tax_ai_agent" / "user_calendar_store.json",
        Path(__file__).resolve().parent.parent / "data" / "user_calendar_store.json",
        Path("/tmp/user_calendar_store.json"),
    ]
    valid_paths: List[Path] = []
    for p in candidates:
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            valid_paths.append(p)
        except Exception:
            continue
    return valid_paths or [Path("/tmp/user_calendar_store.json")]


def _get_user_schedule_store_path() -> Path:
    return _get_user_schedule_store_paths()[0]


def _is_repeating_schedule(ev: Dict[str, Any]) -> bool:
    """반복적인 스케줄('매일 반복', '매주 반복', '매월 반복', '매년 반복')인지 판별합니다."""
    rep = str(ev.get("repeat", "반복 안함")).strip()
    return rep not in ("", "반복 안함", "없음", "NONE")


def _is_statutory_tax_schedule(ev: Dict[str, Any]) -> bool:
    """코드에서 매월 자동 배치하는 기본 법정 세무일정인지 판별합니다."""
    ev_id = str(ev.get("id", ""))
    ev_type = str(ev.get("type", "")).upper()
    return (ev_id.startswith("sch_") and not ev.get("_user_modified")) or (
        ev_type == "TAX" and ev_id.startswith("sch_") and not ev.get("_user_modified")
    )


def _load_raw_store_from_disk() -> Dict[str, Any]:
    """홈 디렉터리 및 프로젝트 data 폴더의 JSON 저장소 중 가장 최신 데이터를 읽어옵니다."""
    best_data: Dict[str, Any] | None = None
    best_ts = ""
    for sp in _get_user_schedule_store_paths():
        if not sp.exists():
            continue
        try:
            raw = json.loads(sp.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and (raw.get("user_events_by_ym") is not None or raw.get("kakao_todos") is not None):
                cur_ts = str(raw.get("updated_at", ""))
                if best_data is None or cur_ts >= best_ts:
                    best_ts = cur_ts
                    best_data = {
                        "last_kst_today_iso": str(raw.get("last_kst_today_iso", "")),
                        "user_events_by_ym": dict(raw.get("user_events_by_ym", {})),
                        "deleted_tax_ids": list(raw.get("deleted_tax_ids", [])),
                        "kakao_todos": list(raw.get("kakao_todos", [])),
                        "silent_read_count": int(raw.get("silent_read_count", 0)),
                        "updated_at": cur_ts,
                    }
        except Exception:
            continue
    return best_data or {
        "last_kst_today_iso": "",
        "user_events_by_ym": {},
        "deleted_tax_ids": [],
        "kakao_todos": [],
        "silent_read_count": 0,
    }


def _save_user_schedules_to_disk(cstate: Dict[str, Any]) -> None:
    """현재 세션의 사용자 스케줄, To-Do, AI 백그라운드 To-Do를 외부 JSON 파일에 즉시 영구 저장합니다."""
    schedules_by_ym = cstate.get("schedules_by_ym", {})
    user_events_by_ym: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}

    existing_disk = _load_raw_store_from_disk().get("user_events_by_ym", {})
    for k_ym, v_days in existing_disk.items():
        if k_ym not in schedules_by_ym and isinstance(v_days, dict):
            user_events_by_ym[k_ym] = v_days

    for ym_key, day_map in schedules_by_ym.items():
        if not isinstance(day_map, dict):
            continue
        ym_saved: Dict[str, List[Dict[str, Any]]] = {}
        for d_key, ev_list in day_map.items():
            u_list = []
            for ev in (ev_list or []):
                if _is_statutory_tax_schedule(ev):
                    continue
                clean_title = _clean_any_legacy_token(str(ev.get("title", "")))
                if not clean_title:
                    continue
                ev["title"] = clean_title
                u_list.append(ev)
            if u_list:
                ym_saved[str(int(d_key))] = u_list
        user_events_by_ym[str(ym_key)] = ym_saved

    payload = {
        "last_kst_today_iso": str(cstate.get("_last_kst_today_iso", get_kst_today().isoformat())),
        "user_events_by_ym": user_events_by_ym,
        "deleted_tax_ids": list(cstate.get("deleted_tax_ids", [])),
        "kakao_todos": list(cstate.get("kakao_todos", [])),
        "silent_read_count": int(cstate.get("silent_read_count", 0)),
        "updated_at": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(),
    }
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    for sp in _get_user_schedule_store_paths():
        try:
            sp.parent.mkdir(parents=True, exist_ok=True)
            sp.write_text(serialized, encoding="utf-8")
        except Exception:
            continue


def _build_merged_month_schedules(
    year: int,
    month: int,
    today_d: date,
    user_events_by_ym: Dict[str, Any],
    deleted_tax_ids: List[str],
) -> Dict[int, List[Dict[str, Any]]]:
    """1~12월 기본 법정 세무일정 위에 외부 파일에 보관된 사용자 스케줄/To-Do를 병합합니다."""
    ym_key = f"{year:04d}-{month:02d}"
    base = _default_schedules_for_month(year, month, today_d)
    del_set = set(str(x) for x in (deleted_tax_ids or []))

    merged: Dict[int, List[Dict[str, Any]]] = {}
    for d_int, ev_list in base.items():
        kept = [e for e in ev_list if str(e.get("id")) not in del_set]
        if kept:
            merged[int(d_int)] = kept

    saved_ym = user_events_by_ym.get(ym_key, {})
    if isinstance(saved_ym, dict):
        for d_str, u_evs in saved_ym.items():
            try:
                d_num = int(d_str)
            except Exception:
                continue
            bucket = merged.setdefault(d_num, [])
            existing_ids = {str(x.get("id")) for x in bucket}
            for u_ev in (u_evs or []):
                clean_t = _clean_any_legacy_token(str(u_ev.get("title", "")))
                if not clean_t:
                    continue
                u_ev["title"] = clean_t
                uid = str(u_ev.get("id", ""))
                if uid in existing_ids:
                    bucket[:] = [u_ev if str(x.get("id")) == uid else x for x in bucket]
                else:
                    bucket.append(u_ev)
                    existing_ids.add(uid)

    max_d_in_month = calendar.monthrange(year, month)[1]
    seen_rep_sources: Dict[str, Dict[str, Any]] = {}
    for src_ym, src_days in (user_events_by_ym or {}).items():
        if not isinstance(src_days, dict):
            continue
        try:
            sy_str, sm_str = str(src_ym).split("-", 1)
            sy_int, sm_int = int(sy_str), int(sm_str)
        except Exception:
            continue
        for sd_str, s_evs in src_days.items():
            try:
                sd_int = int(sd_str)
            except Exception:
                continue
            for s_ev in (s_evs or []):
                if not _is_repeating_schedule(s_ev):
                    continue
                sid = str(s_ev.get("id", ""))
                if not sid or sid in del_set or sid in seen_rep_sources:
                    continue
                s_copy = dict(s_ev)
                s_copy.setdefault("origin_year", sy_int)
                s_copy.setdefault("origin_month", sm_int)
                s_copy.setdefault("origin_day", sd_int)
                seen_rep_sources[sid] = s_copy

    for sid, rep_ev in seen_rep_sources.items():
        rep_mode = str(rep_ev.get("repeat", "반복 안함")).strip()
        oy = int(rep_ev.get("origin_year", year))
        om = int(rep_ev.get("origin_month", month))
        od = int(rep_ev.get("origin_day", 1))
        try:
            orig_dt = date(oy, om, min(od, calendar.monthrange(oy, om)[1]))
        except Exception:
            continue
        target_days: List[int] = []
        if rep_mode == "매일 반복":
            for d_cand in range(1, max_d_in_month + 1):
                if date(year, month, d_cand) >= orig_dt:
                    target_days.append(d_cand)
        elif rep_mode == "매주 반복":
            for d_cand in range(1, max_d_in_month + 1):
                cand_dt = date(year, month, d_cand)
                if cand_dt >= orig_dt and cand_dt.weekday() == orig_dt.weekday():
                    target_days.append(d_cand)
        elif rep_mode == "매월 반복":
            if (year, month) >= (oy, om):
                target_days.append(min(od, max_d_in_month))
        elif rep_mode == "매년 반복":
            if year >= oy and month == om:
                target_days.append(min(od, max_d_in_month))

        for td in target_days:
            bucket = merged.setdefault(td, [])
            if not any(str(x.get("id")) == sid for x in bucket):
                bucket.append(dict(rep_ev))

    return merged


def _run_daily_0000_maintenance(cstate: Dict[str, Any], today_d: date) -> bool:
    """매일 00:00시 기준 자동 정리 로직"""
    changed = False
    schedules_by_ym = cstate.get("schedules_by_ym", {})
    today_ym_key = f"{today_d.year:04d}-{today_d.month:02d}"
    if today_ym_key not in schedules_by_ym:
        disk_data = _load_raw_store_from_disk()
        schedules_by_ym[today_ym_key] = _build_merged_month_schedules(
            today_d.year,
            today_d.month,
            today_d,
            disk_data.get("user_events_by_ym", {}),
            disk_data.get("deleted_tax_ids", []),
        )
    today_bucket = schedules_by_ym.setdefault(today_ym_key, {}).setdefault(today_d.day, [])
    today_existing_ids = {str(x.get("id")) for x in today_bucket}

    for ym_key, day_map in list(schedules_by_ym.items()):
        if not isinstance(day_map, dict):
            continue
        try:
            y_str, m_str = str(ym_key).split("-", 1)
            y_int, m_int = int(y_str), int(m_str)
        except Exception:
            continue

        for d_key in sorted(list(day_map.keys()), key=lambda x: int(x)):
            d_int = int(d_key)
            try:
                slot_date = date(y_int, m_int, d_int)
            except Exception:
                continue

            if slot_date >= today_d:
                continue

            ev_list = day_map.get(d_key, [])
            kept_list: List[Dict[str, Any]] = []
            for ev_item in ev_list:
                if _is_statutory_tax_schedule(ev_item):
                    kept_list.append(ev_item)
                    continue

                is_rep = _is_repeating_schedule(ev_item)
                is_done = bool(ev_item.get("done", False))

                if is_done:
                    if is_rep:
                        kept_list.append(ev_item)
                    else:
                        comp_ymd = ev_item.get("completed_on_ymd")
                        comp_date = slot_date
                        if isinstance(comp_ymd, (list, tuple)) and len(comp_ymd) == 3:
                            try:
                                comp_date = date(int(comp_ymd[0]), int(comp_ymd[1]), int(comp_ymd[2]))
                            except Exception:
                                comp_date = slot_date
                        if comp_date < today_d:
                            changed = True
                            continue
                        else:
                            kept_list.append(ev_item)
                else:
                    ev_item.setdefault("origin_year", y_int)
                    ev_item.setdefault("origin_month", m_int)
                    ev_item.setdefault("origin_day", d_int)
                    if ev_item.get("show_on_cal"):
                        kept_list.append(ev_item)
                    else:
                        if str(ev_item.get("id")) not in today_existing_ids:
                            today_bucket.append(ev_item)
                            today_existing_ids.add(str(ev_item.get("id")))
                        changed = True

            day_map[d_key] = kept_list

    today_iso_str = today_d.isoformat()
    raw_ktodos = list(cstate.get("kakao_todos", []))
    kept_ktodos: List[Dict[str, Any]] = []
    for kt in raw_ktodos:
        st_code = str(kt.get("status_code", "")).upper()
        st_txt = str(kt.get("status", ""))
        is_approved = (st_code == "APPROVED" or "승인완료" in st_txt)
        if not is_approved:
            kept_ktodos.append(kt)
        else:
            app_iso = str(kt.get("approved_date_iso") or kt.get("created_date_iso") or "").strip()
            if app_iso and app_iso < today_iso_str:
                changed = True
                continue
            kept_ktodos.append(kt)
    if len(kept_ktodos) != len(raw_ktodos):
        cstate["kakao_todos"] = kept_ktodos
        changed = True

    if changed:
        _save_user_schedules_to_disk(cstate)
    return changed


def _find_expired_180d_schedules(cstate: Dict[str, Any], today_d: date) -> List[Dict[str, Any]]:
    """메인 달력에 적어둔 지난 스케줄 중 180일이 경과한 항목(반복 스케줄 제외)을 탐색합니다."""
    expired: List[Dict[str, Any]] = []
    schedules_by_ym = cstate.get("schedules_by_ym", {})
    seen_ids: set[str] = set()

    for ym_key, day_map in sorted(schedules_by_ym.items()):
        if not isinstance(day_map, dict):
            continue
        try:
            y_str, m_str = str(ym_key).split("-", 1)
            y_int, m_int = int(y_str), int(m_str)
        except Exception:
            continue

        for d_key, ev_list in sorted(day_map.items(), key=lambda item: int(item[0])):
            d_int = int(d_key)
            try:
                ev_date = date(y_int, m_int, d_int)
            except Exception:
                continue

            days_elapsed = (today_d - ev_date).days
            if days_elapsed < 180:
                continue

            for ev in (ev_list or []):
                ev_id = str(ev.get("id", ""))
                if not ev_id or ev_id in seen_ids:
                    continue
                if _is_statutory_tax_schedule(ev) or str(ev.get("type", "")).upper() == "TAX":
                    continue
                if _is_repeating_schedule(ev):
                    continue
                seen_ids.add(ev_id)
                expired.append({
                    "ym_key": str(ym_key),
                    "year": y_int,
                    "month": m_int,
                    "day": d_int,
                    "date_str": f"{y_int}.{m_int:02d}.{d_int:02d}",
                    "days_elapsed": days_elapsed,
                    "ev": ev,
                })
    return expired


def _delete_specific_schedule_by_id(cstate: Dict[str, Any], ev_id: str) -> None:
    """특정 스케줄 ID를 모든 연·월 버킷에서 삭제하고 디스크에 즉시 반영합니다."""
    if str(ev_id).startswith("sch_"):
        del_list = cstate.setdefault("deleted_tax_ids", [])
        if str(ev_id) not in del_list:
            del_list.append(str(ev_id))
    for ym_k, d_map in list(cstate.get("schedules_by_ym", {}).items()):
        if isinstance(d_map, dict):
            for dk in list(d_map.keys()):
                d_map[dk] = [x for x in d_map.get(dk, []) if str(x.get("id")) != str(ev_id)]
    _save_user_schedules_to_disk(cstate)


@st.dialog("🗓️ 180일 경과 지난 스케줄 삭제 확인", width="large")
def _open_expired_180d_cleanup_dialog() -> None:
    """180일이 지난 스케줄(반복 스케줄 제외)에 대해 사용자에게 삭제 여부를 묻는 확인 모달입니다."""
    cstate = _init_calendar_state()
    today_d = get_kst_today()
    expired_list = _find_expired_180d_schedules(cstate, today_d)

    st.markdown("<div id='tds-dlg-iceblue-anchor' style='display:none;'></div>", unsafe_allow_html=True)
    st.markdown(
        _html(f"""
        <div style="background:#FFFFFF;border:1.5px solid #90C2FF;border-radius:16px;padding:16px 20px;margin-bottom:14px;">
            <div style="font-size:1.05rem;font-weight:800;color:#191F28;margin-bottom:6px;">
                등록한 지 180일이 지난 스케줄이 <span style="color:#3182F6;">{len(expired_list)}건</span> 있습니다. 삭제할까요?
            </div>
            <div style="font-size:0.80rem;font-weight:600;color:#4E5968;line-height:1.5;">
                • <b>반복적인 스케줄(매일·매주·매월·매년 반복)</b>과 법정 세무일정은 삭제 대상에서 <b>자동 제외</b>되었습니다.<br>
                • 아래 목록에서 정리할 지난 스케줄을 확인하신 뒤 직접 삭제 버튼을 눌러주세요.
            </div>
        </div>
        """),
        unsafe_allow_html=True,
    )

    if not expired_list:
        st.info("현재 180일이 경과한 삭제 대상 스케줄이 없습니다.")
        if st.button("닫기", width="stretch", key="btn_180d_close_empty"):
            cstate["dismissed_180d_prompt"] = True
            st.rerun()
        return

    selected_del_ids: List[str] = []
    for idx, item in enumerate(expired_list):
        ev = item["ev"]
        ev_id = str(ev.get("id", f"exp_{idx}"))
        title_str = str(ev.get("title", "지난 일정"))
        client_str = str(ev.get("client", ""))
        date_str = item["date_str"]
        days_old = item["days_elapsed"]

        c_chk, c_one_del = st.columns([4.6, 1.1], gap="small")
        with c_chk:
            lbl = f"[{date_str} · {days_old}일 경과] {title_str}" + (f" ({client_str})" if client_str and client_str != "내 스케줄" else "")
            if st.checkbox(lbl, value=True, key=f"chk_180d_del_{ev_id}"):
                selected_del_ids.append(ev_id)
        with c_one_del:
            if st.button("직접 삭제", key=f"btn_180d_one_{ev_id}", width="stretch"):
                _delete_specific_schedule_by_id(cstate, ev_id)
                st.toast(f"'{title_str}' 지난 스케줄을 삭제했습니다.", icon="🗑️")
                st.rerun()

    st.divider()
    b_later, b_del_sel = st.columns([1.2, 1.8], gap="small")
    with b_later:
        if st.button("나중에 정리하기 (유지)", width="stretch", key="btn_180d_keep_later"):
            cstate["dismissed_180d_prompt"] = True
            st.rerun()
    with b_del_sel:
        if st.button(f"선택한 {len(selected_del_ids)}건 지금 삭제하기", width="stretch", key="btn_180d_confirm_del"):
            for did in selected_del_ids:
                _delete_specific_schedule_by_id(cstate, did)
            cstate["dismissed_180d_prompt"] = True
            st.toast(f"180일이 지난 스케줄 {len(selected_del_ids)}건을 삭제했습니다.", icon="✅")
            st.rerun()


def _init_calendar_state() -> Dict[str, Any]:
    """달력 및 Today To Do 세션 상태를 초기화합니다."""
    today_d = get_kst_today()
    today_iso = today_d.isoformat()

    if (
        "cal_scheduler_state" not in st.session_state
        or st.session_state["cal_scheduler_state"].get("_schema_v") != _STATE_SCHEMA_VERSION
    ):
        disk_store = _load_raw_store_from_disk()
        user_evs_by_ym = disk_store.get("user_events_by_ym", {})
        del_tax_ids = disk_store.get("deleted_tax_ids", [])

        ym_key = f"{today_d.year:04d}-{today_d.month:02d}"
        schedules_by_ym: Dict[str, Dict[int, List[Dict[str, Any]]]] = {
            ym_key: _build_merged_month_schedules(
                today_d.year, today_d.month, today_d, user_evs_by_ym, del_tax_ids
            )
        }
        for saved_ym_k in user_evs_by_ym.keys():
            if saved_ym_k not in schedules_by_ym:
                try:
                    sy, sm = str(saved_ym_k).split("-", 1)
                    schedules_by_ym[saved_ym_k] = _build_merged_month_schedules(
                        int(sy), int(sm), today_d, user_evs_by_ym, del_tax_ids
                    )
                except Exception:
                    pass

        st.session_state["cal_scheduler_state"] = {
            "_schema_v": _STATE_SCHEMA_VERSION,
            "_last_kst_today_iso": disk_store.get("last_kst_today_iso") or today_iso,
            "year": today_d.year,
            "month": today_d.month,
            "selected_day": today_d.day,
            "schedules_by_ym": schedules_by_ym,
            "deleted_tax_ids": del_tax_ids,
            "dismissed_180d_prompt": False,
            "open_180d_modal_manual": False,
            "kakao_todos": list(disk_store.get("kakao_todos") or _default_kakao_todos(today_d)),
            "silent_read_count": int(disk_store.get("silent_read_count", 0)),
            "panel_open": False,
            "bubble_visible": any(
                str(x.get("status_code", "")).upper() == "READY" or "승인요청" in str(x.get("status", ""))
                for x in (disk_store.get("kakao_todos") or [])
            ),
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
            "_last_cal_click_day": None,
            "_last_cal_click_ts": 0.0,
            "_sync_sb_from_cstate": False,
            "active_detail_ev_id": None,
        }
        _run_daily_0000_maintenance(st.session_state["cal_scheduler_state"], today_d)
        st.session_state["cal_scheduler_state"]["_last_kst_today_iso"] = today_iso
        _save_user_schedules_to_disk(st.session_state["cal_scheduler_state"])

    cstate = st.session_state["cal_scheduler_state"]
    cstate.setdefault("deleted_tax_ids", [])
    cstate.setdefault("dismissed_180d_prompt", False)
    cstate.setdefault("open_180d_modal_manual", False)
    cstate.setdefault("silent_read_count", 0)
    cstate.setdefault("urgent_first", False)
    cstate.setdefault("hide_completed", False)
    cstate.setdefault("dock_alarm", False)
    cstate.setdefault("dock_cal", False)
    cstate.setdefault("dock_dtl", False)
    cstate.setdefault("dock_reset_seq", 0)
    cstate.setdefault("pending_detail_draft", None)
    cstate.setdefault("_last_cal_click_day", None)
    cstate.setdefault("_last_cal_click_ts", 0.0)
    cstate.setdefault("_sync_sb_from_cstate", False)
    cstate.setdefault("active_detail_ev_id", None)

    cstate["kakao_todos"] = [
        t for t in cstate.get("kakao_todos", [])
        if not str(t.get("id", "")).startswith("todo_alarm_")
        and str(t.get("client", "")) != "Today To Do"
    ]

    if cstate.get("_last_kst_today_iso") != today_iso:
        _run_daily_0000_maintenance(cstate, today_d)
        cstate["_last_kst_today_iso"] = today_iso
        cstate["year"] = today_d.year
        cstate["month"] = today_d.month
        cstate["selected_day"] = today_d.day
        cstate["dismissed_180d_prompt"] = False
        cstate["_sync_sb_from_cstate"] = True
        _save_user_schedules_to_disk(cstate)

    ym_key = f"{int(cstate['year']):04d}-{int(cstate['month']):02d}"
    if ym_key not in cstate["schedules_by_ym"]:
        disk_store = _load_raw_store_from_disk()
        cstate["schedules_by_ym"][ym_key] = _build_merged_month_schedules(
            int(cstate["year"]),
            int(cstate["month"]),
            today_d,
            disk_store.get("user_events_by_ym", {}),
            cstate.get("deleted_tax_ids", []),
        )
    return cstate


def _commit_dock_schedule_on_enter() -> None:
    """하단 독(Dock)의 할 일 입력칸 또는 시간 입력칸에서 Enter를 쳤을 때 즉시 할 일을 등록합니다."""
    cstate = _init_calendar_state()
    year = int(cstate["year"])
    month = int(cstate["month"])
    sel_day = int(cstate["selected_day"])
    r_seq = int(cstate.get("dock_reset_seq", 0))
    inp_key = f"dock_chat_inp_{year}_{month}_{sel_day}_{r_seq}"
    time_key = f"dock_time_inp_{year}_{month}_{sel_day}_{r_seq}"

    raw_val = str(st.session_state.get(inp_key, "")).strip()
    clean_txt = _clean_any_legacy_token(raw_val)
    if not clean_txt:
        st.session_state[inp_key] = ""
        return

    raw_time = str(st.session_state.get(time_key, "")).strip()
    norm_t = _normalize_time_str(raw_time)
    is_alarm = bool(cstate.get("dock_alarm", False))
    is_cal = bool(cstate.get("dock_cal", False))

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
        "base_date_iso": date(year, month, sel_day).isoformat(),
        "origin_year": year,
        "origin_month": month,
        "origin_day": sel_day,
        "completed_on_ymd": None,
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
    _save_user_schedules_to_disk(cstate)

    cstate["dock_alarm"] = False
    cstate["dock_cal"] = False
    cstate["dock_dtl"] = False
    cstate["pending_detail_draft"] = None
    cstate["dock_reset_seq"] = r_seq + 1


def _add_sub_task_in_dialog(ev_id: str) -> None:
    """상세 모달 내부에서 [+ 항목 추가] 클릭 또는 Enter 시 하위 체크항목을 한 줄 추가합니다."""
    subs_key = f"dlg_subs_state_{ev_id}"
    inp_key = f"dlg_new_sub_inp_{ev_id}"
    new_txt = str(st.session_state.get(inp_key, "")).strip()
    if new_txt:
        cur_list = list(st.session_state.get(subs_key, []))
        cur_list.append({"title": new_txt, "done": False})
        st.session_state[subs_key] = cur_list
        st.session_state[inp_key] = ""


def _delete_sub_task_in_dialog(ev_id: str, del_idx: int) -> None:
    """상세 모달 내부에서 하위 체크항목의 [✕] 클릭 시 해당 줄만 삭제합니다."""
    subs_key = f"dlg_subs_state_{ev_id}"
    cur_list = list(st.session_state.get(subs_key, []))
    if 0 <= del_idx < len(cur_list):
        cur_list.pop(del_idx)
        st.session_state[subs_key] = cur_list


@st.dialog("📋 상세일정 설정", width="large")
def _open_schedule_detail_dialog(year: int, month: int, day_num: int, ev_id: str) -> None:
    """화면 중앙 상세입력 모달 (시안 A: 토스 아이스 블루 틴트 #DCEBFF + 보더 #3182F6 + 순백색 #FFFFFF 입력칸)"""
    cstate = _init_calendar_state()
    cstate["dock_dtl"] = False
    today_d = get_kst_today()
    ym_key = f"{year:04d}-{month:02d}"
    month_schedules = cstate["schedules_by_ym"].setdefault(
        ym_key, _default_schedules_for_month(year, month, today_d)
    )
    day_evs = month_schedules.setdefault(day_num, [])
    target_ev = next((x for x in day_evs if str(x.get("id")) == str(ev_id)), None)

    r_seq = int(cstate.get("dock_reset_seq", 0))
    inp_key = f"dock_chat_inp_{year}_{month}_{day_num}_{r_seq}"
    time_key = f"dock_time_inp_{year}_{month}_{day_num}_{r_seq}"

    is_new = False
    if target_ev is None:
        is_new = True
        pending = cstate.get("pending_detail_draft") or {}
        raw_draft = _clean_any_legacy_token(str(st.session_state.get(inp_key, "")))
        final_draft_title = _clean_any_legacy_token(
            str(pending.get("title") if pending.get("title") is not None else raw_draft)
        )
        init_alarm = (
            bool(pending["alarm"])
            if "alarm" in pending
            else bool(cstate.get("dock_alarm", False))
        )
        init_cal = (
            bool(pending["show_on_cal"])
            if "show_on_cal" in pending
            else bool(cstate.get("dock_cal", True))
        )
        raw_t_candidate = str(pending.get("time") or "") or str(st.session_state.get(time_key, ""))
        draft_t = _normalize_time_str(raw_t_candidate)

        target_ev = {
            "id": ev_id,
            "type": "MY",
            "time": draft_t,
            "base_date_iso": date(year, month, day_num).isoformat(),
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

    st.markdown("<div id='tds-dlg-iceblue-anchor' style='display:none;'></div>", unsafe_allow_html=True)
    components.html(
        """
        <script>
        (function() {
            const pDoc = window.parent.document;
            const pWin = window.parent;
            function applyOptionAIceBlueModal() {
                const anchor = pDoc.getElementById("tds-dlg-iceblue-anchor") || pDoc.querySelector(".gcal-tds-title-wrap");
                if (!anchor) return;
                const dlgRoot = anchor.closest('div[data-testid="stDialog"], div[data-testid="stModal"], div[data-baseweb="modal"], dialog');
                if (!dlgRoot) return;
                let cur = anchor.parentElement;
                let modalCard = null;
                while (cur && cur !== dlgRoot && cur !== pDoc.body) {
                    const r = cur.getBoundingClientRect();
                    if (r.width >= 320 && r.width <= Math.min(920, pWin.innerWidth * 0.90) && r.height >= 260) {
                        modalCard = cur;
                    }
                    cur = cur.parentElement;
                }
                if (!modalCard) {
                    modalCard = dlgRoot.querySelector('div[role="dialog"], [aria-label="dialog"]') || dlgRoot.querySelector('div > div');
                }
                if (modalCard) {
                    modalCard.style.setProperty("background", "#DCEBFF", "important");
                    modalCard.style.setProperty("background-color", "#DCEBFF", "important");
                    modalCard.style.setProperty("opacity", "1", "important");
                    modalCard.style.setProperty("border", "2.5px solid #3182F6", "important");
                    modalCard.style.setProperty("border-radius", "24px", "important");
                    modalCard.style.setProperty("box-shadow", "0 22px 54px rgba(25, 31, 40, 0.18), 0 4px 16px rgba(49, 130, 246, 0.14)", "important");

                    let inner = anchor.parentElement;
                    while (inner && inner !== modalCard && inner !== dlgRoot) {
                        inner.style.setProperty("background", "transparent", "important");
                        inner.style.setProperty("background-color", "transparent", "important");
                        inner = inner.parentElement;
                    }
                    const hdr = modalCard.querySelector('[data-testid="stDialogHeader"]');
                    if (hdr) {
                        hdr.style.setProperty("background", "transparent", "important");
                        hdr.style.setProperty("background-color", "transparent", "important");
                    }

                    let anc = modalCard.parentElement;
                    while (anc && anc !== pDoc.body) {
                        anc.style.setProperty("background", "transparent", "important");
                        anc.style.setProperty("background-color", "transparent", "important");
                        anc.style.setProperty("backdrop-filter", "none", "important");
                        if (anc === dlgRoot) break;
                        anc = anc.parentElement;
                    }
                }
            }
            applyOptionAIceBlueModal();
            setTimeout(applyOptionAIceBlueModal, 40);
            setTimeout(applyOptionAIceBlueModal, 140);
            setTimeout(applyOptionAIceBlueModal, 320);
        })();
        </script>
        """,
        height=0,
    )

    st.markdown("<div class='gcal-tds-title-wrap'>", unsafe_allow_html=True)
    in_title = st.text_input(
        "일정 제목",
        value=_clean_any_legacy_token(str(target_ev.get("title", ""))),
        placeholder="부가세 예정고지 안내 (제목 입력)",
        label_visibility="collapsed",
        key=f"dlg_title_{ev_id}",
    )
    st.markdown("</div>", unsafe_allow_html=True)

    c_cat, c_urg = st.columns([3.2, 1.2], gap="small")
    cur_type = str(target_ev.get("type", "MY")).upper()
    cat_opts = ["🔵 내 스케줄", "🔴 세무일정", "🟢 승인완료"]
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
            "🔔 정각 종 반짝임 알림 (Today To Do)",
            value=bool(target_ev.get("alarm", False)),
            key=f"dlg_alarm_{ev_id}",
        )
    with r1_sub2:
        in_show_cal = st.checkbox(
            "달력에 표시",
            value=bool(target_ev.get("show_on_cal", False)),
            key=f"dlg_showcal_{ev_id}",
        )

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

    r4_l, r4_r = st.columns([0.72, 3.8], gap="small")
    cur_sub_tasks: List[Dict[str, Any]] = list(st.session_state.get(subs_state_key, []))
    for s_idx, s_item in enumerate(cur_sub_tasks):
        chk_key = f"dlg_sub_chk_{ev_id}_{s_idx}_{s_item.get('title', '')}"
        if chk_key in st.session_state:
            s_item["done"] = bool(st.session_state[chk_key])
    done_sub_cnt = sum(1 for s in cur_sub_tasks if s.get("done"))

    with r4_l:
        st.markdown("<div class='gcal-tds-row-lbl'>체크</div>", unsafe_allow_html=True)
    with r4_r:
        ns_c1, ns_c2 = st.columns([4.2, 1.3], gap="small")
        with ns_c1:
            st.text_input(
                "새 세부 체크항목 추가",
                placeholder=f"세부 체크항목 입력... (현재 {done_sub_cnt}/{len(cur_sub_tasks)} 완료)",
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

    att_meta_key = f"dlg_att_meta_{ev_id}"
    if att_meta_key not in st.session_state:
        st.session_state[att_meta_key] = list(target_ev.get("attachments_meta", []) or [])

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
            placeholder="+ 첨부파일명 직접 입력 또는 아래에서 로컬 파일 업로드",
            label_visibility="collapsed",
            key=f"dlg_att_{ev_id}",
        )
        uploaded_files = st.file_uploader(
            "로컬 첨부파일 업로드",
            accept_multiple_files=True,
            key=f"dlg_file_up_{ev_id}",
            label_visibility="collapsed",
            help="로컬 PC의 파일(PDF, 엑셀, 워드, 이미지 등)을 선택하거나 끌어다 놓으면 일정에 첨부·보관됩니다.",
        )
        cur_att_meta: List[Dict[str, Any]] = list(st.session_state.get(att_meta_key, []))
        if uploaded_files:
            att_dir = Path(__file__).resolve().parent.parent / "data" / "schedule_attachments" / str(ev_id)
            try:
                att_dir.mkdir(parents=True, exist_ok=True)
            except Exception:
                att_dir = Path("/tmp") / "schedule_attachments" / str(ev_id)
                att_dir.mkdir(parents=True, exist_ok=True)
            existing_names = {str(m.get("name", "")) for m in cur_att_meta}
            for uf in uploaded_files:
                uf_name = str(getattr(uf, "name", "") or "").strip()
                if not uf_name:
                    continue
                raw_bytes = uf.getvalue() if hasattr(uf, "getvalue") else b""
                save_p = att_dir / uf_name
                try:
                    save_p.write_bytes(raw_bytes)
                except Exception:
                    pass
                if uf_name not in existing_names:
                    cur_att_meta.append({
                        "name": uf_name,
                        "size": len(raw_bytes),
                        "path": str(save_p),
                    })
                    existing_names.add(uf_name)
            st.session_state[att_meta_key] = cur_att_meta

        for a_idx, a_info in enumerate(list(cur_att_meta)):
            a_name = str(a_info.get("name", "첨부파일"))
            a_path = Path(str(a_info.get("path", "")))
            ac1, ac2, ac3 = st.columns([3.8, 1.2, 0.6], gap="small")
            with ac1:
                st.caption(f"📎 {a_name} ({int(a_info.get('size', 0)):,} bytes)")
            with ac2:
                if a_path.exists():
                    try:
                        st.download_button(
                            "다운로드",
                            data=a_path.read_bytes(),
                            file_name=a_name,
                            key=f"dlg_att_dl_{ev_id}_{a_idx}",
                            width="stretch",
                        )
                    except Exception:
                        pass
            with ac3:
                if st.button("✕", key=f"dlg_att_rm_{ev_id}_{a_idx}"):
                    cur_att_meta.pop(a_idx)
                    st.session_state[att_meta_key] = cur_att_meta
                    st.rerun()

    st.divider()

    _, f_del, f_can, f_save = st.columns([2.6, 0.8, 0.8, 1.0], gap="small")
    with f_del:
        if not is_new:
            if st.button("삭제", width="stretch", key=f"dlg_btn_delete_{ev_id}"):
                _delete_specific_schedule_by_id(cstate, str(ev_id))
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

            final_title = _clean_any_legacy_token(in_title.strip()) or "세무 상세 일정"
            new_type = "TAX" if ("세무일정" in sel_cat_lbl or "세무기한" in sel_cat_lbl) else ("DONE" if "승인완료" in sel_cat_lbl else "MY")
            norm_t = "" if new_type == "TAX" else _normalize_time_str(in_time)

            all_subs_done = bool(updated_subs) and all(s.get("done") for s in updated_subs)
            is_done_final = True if (new_type == "DONE" or all_subs_done) else bool(target_ev.get("done", False))

            saved_att_meta = list(st.session_state.get(att_meta_key, []))
            uploaded_names_str = ", ".join(str(m.get("name", "")) for m in saved_att_meta if m.get("name"))
            final_attach_str = in_attach.strip()
            if uploaded_names_str:
                if not final_attach_str:
                    final_attach_str = uploaded_names_str
                elif uploaded_names_str not in final_attach_str:
                    final_attach_str = f"{final_attach_str}, {uploaded_names_str}"

            new_d_int = int(in_day)
            target_ev.update({
                "title": final_title,
                "type": "DONE" if is_done_final else new_type,
                "category": "세무일정" if new_type == "TAX" else ("승인완료" if is_done_final else "내 스케줄"),
                "time": norm_t,
                "repeat": in_repeat,
                "alarm": bool(in_alarm),
                "alarm_glow": False,
                "show_on_cal": bool(in_show_cal),
                "urgent": bool(in_urgent),
                "client": in_client.strip() or "내 스케줄",
                "sub_tasks": updated_subs,
                "desc": in_desc.strip(),
                "attachment": final_attach_str,
                "attachments_meta": saved_att_meta,
                "done": is_done_final,
                "completed_on_ymd": [year, month, new_d_int] if is_done_final else None,
                "has_detail": True,
                "_user_modified": True,
            })
            if is_new or "origin_day" not in target_ev:
                target_ev["origin_year"] = year
                target_ev["origin_month"] = month
                target_ev["origin_day"] = new_d_int

            if is_new:
                month_schedules.setdefault(new_d_int, []).append(target_ev)
            elif new_d_int != day_num:
                month_schedules[day_num] = [x for x in day_evs if str(x.get("id")) != str(ev_id)]
                month_schedules.setdefault(new_d_int, []).append(target_ev)

            _save_user_schedules_to_disk(cstate)
            disk_after_save = _load_raw_store_from_disk()
            cstate["schedules_by_ym"][ym_key] = _build_merged_month_schedules(
                year,
                month,
                today_d,
                disk_after_save.get("user_events_by_ym", {}),
                cstate.get("deleted_tax_ids", []),
            )
            st.session_state.pop(subs_state_key, None)
            st.session_state.pop(att_meta_key, None)
            cstate["selected_day"] = new_d_int
            cstate["active_detail_ev_id"] = None
            cstate["pending_detail_draft"] = None
            cstate["dock_alarm"] = False
            cstate["dock_cal"] = False
            cstate["dock_dtl"] = False
            cstate["dock_reset_seq"] = r_seq + 1
            st.toast(f"'{final_title}' 상세일정이 저장되었어요.", icon="✅")
            st.rerun()


def render_calendar_sidebar() -> None:
    """좌측 사이드바 ('달력' 모드 전용 제어판 — 가상 시뮬레이터 샘플 버튼 완전 삭제 완료)"""
    cstate = _init_calendar_state()
    today_d = get_kst_today()
    wd_str = _WEEKDAYS_SHORT[today_d.weekday()]

    if cstate.pop("_sync_sb_from_cstate", False):
        st.session_state["cal_sb_year_sel"] = int(cstate["year"])
        st.session_state["cal_sb_month_sel"] = int(cstate["month"])

    with st.container(border=True):
        today_pill = f"<span style='font-size:0.68rem;font-weight:800;padding:2px 9px;border-radius:999px;background:#E5F9F0;color:#00A660;font-variant-numeric:tabular-nums;'>{today_d.strftime('%Y.%m.%d')} ({wd_str})</span>"
        st.markdown(_ui_theme.sb_title("calendar", "달력 기준일 · 월 이동", today_pill), unsafe_allow_html=True)

        c_y, c_m = st.columns(2)
        cur_y = int(cstate.get("year", today_d.year))
        yr_opts = sorted(list({today_d.year - 2, today_d.year - 1, today_d.year, today_d.year + 1, today_d.year + 2, cur_y}))
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
            cstate["_sync_sb_from_cstate"] = True
            st.rerun()

    with st.container(border=True):
        st.markdown(
            _html("""
            <div style="display:flex;align-items:center;justify-content:space-between;font-size:0.74rem;color:#8B95A1;">
                <span>카톡 감시 엔진</span>
                <span style="font-weight:800;color:#00A660;background:#E5F9F0;padding:2px 8px;border-radius:999px;"><span style="color:#00C471;">●</span> 실시간 켜짐</span>
            </div>
            """),
            unsafe_allow_html=True,
        )
        def render_calendar_main() -> None:
    """메인 화면: 좌측 풀사이즈 달력 + 우측 Today To Do (검은색 코드 노출 없이 순정 Streamlit 이벤트 직결)"""
    cstate = _init_calendar_state()
    cstate["dock_dtl"] = False
    today_d = get_kst_today()

    st.markdown(CALENDAR_MAIN_CSS, unsafe_allow_html=True)

    year = int(cstate["year"])
    month = int(cstate["month"])
    max_d_cur = calendar.monthrange(year, month)[1]

    # 달력 날짜 셀 클릭을 상단에서 선제 감지하여 루프 중간 st.rerun()이나 화면 끊김 없이 단일 패스로 즉시 반영
    for _cand_d in range(1, max_d_cur + 1):
        if st.session_state.get(f"cal_sel_d_{year}_{month}_{_cand_d}"):
            now_ts = datetime.now().timestamp()
            prev_d = cstate.get("_last_cal_click_day")
            prev_ts = float(cstate.get("_last_cal_click_ts", 0.0))
            cstate["selected_day"] = _cand_d
            if prev_d == _cand_d and (now_ts - prev_ts) < 1.35:
                cstate["_last_cal_click_day"] = None
                cstate["_last_cal_click_ts"] = 0.0
                cstate["pending_detail_draft"] = {
                    "title": "",
                    "time": "",
                    "alarm": False,
                    "show_on_cal": True,
                }
                cstate["active_detail_modal"] = {
                    "year": year,
                    "month": month,
                    "day": _cand_d,
                    "ev_id": f"dbl_{int(now_ts * 1000)}",
                }
            else:
                cstate["_last_cal_click_day"] = _cand_d
                cstate["_last_cal_click_ts"] = now_ts
            break

    selected_day = int(cstate["selected_day"])
    ym_key = f"{year:04d}-{month:02d}"
    month_schedules = cstate["schedules_by_ym"].setdefault(
        ym_key, _default_schedules_for_month(year, month, today_d)
    )

    # 숨김 처리된 이전 달 / 다음 달 이동 & 더블클릭 상세 오픈 & Enter 즉시 등록 & 카톡 백그라운드 To-Do 개별 삭제 트리거 버튼
    with st.container(key="cal_hidden_month_nav_wrap"):
        if st.button("이전달", key="btn_cal_m_prev"):
            _shift_calendar_month(cstate, -1)
            st.rerun()
        if st.button("다음달", key="btn_cal_m_next"):
            _shift_calendar_month(cstate, 1)
            st.rerun()
        if st.button("엔터등록", key="btn_dock_hidden_enter_commit"):
            _commit_dock_schedule_on_enter()
            st.rerun()
        if st.button("선택일상세오픈", key="btn_cal_dbl_open_selected"):
            cstate["pending_detail_draft"] = {
                "title": "",
                "time": "",
                "alarm": False,
                "show_on_cal": True,
            }
            cstate["active_detail_modal"] = {
                "year": year,
                "month": month,
                "day": selected_day,
                "ev_id": f"dbl_{int(datetime.now().timestamp() * 1000)}",
            }
        for _kt_item in list(cstate.get("kakao_todos", [])):
            _kt_id = str(_kt_item.get("id", ""))
            if _kt_id and st.button(f"KT_DEL_{_kt_id}", key=f"btn_kt_del_{_kt_id}"):
                cstate["kakao_todos"] = [
                    x for x in cstate.get("kakao_todos", []) if str(x.get("id", "")) != _kt_id
                ]
                _save_user_schedules_to_disk(cstate)
                st.rerun()

    expired_180d_items = _find_expired_180d_schedules(cstate, today_d)

    if expired_180d_items and cstate.get("dismissed_180d_prompt", False):
        b_info, b_act = st.columns([4.2, 1.2], gap="small")
        with b_info:
            st.warning(f"🗓️ 등록한 지 **180일이 지난 스케줄이 {len(expired_180d_items)}건** 있습니다. (반복 스케줄 제외) 직접 확인 후 삭제하시겠어요?")
        with b_act:
            if st.button("지난 스케줄 삭제 창 열기", width="stretch", key="btn_reopen_180d_modal"):
                cstate["open_180d_modal_manual"] = True
                st.rerun()

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
                                if p_cls == "red" or str(ev.get("type", "")).upper() == "TAX":
                                    prefix_t = ""
                                else:
                                    t_p = _normalize_time_str(str(ev.get("time", "")))
                                    prefix_t = f"{t_p} " if t_p else ""
                                pills_html += f"<div class='tds-cal-ev-pill {p_cls}'>{_html_lib.escape(prefix_t + _clean_any_legacy_token(str(ev.get('title', ''))))}</div>"
                            if len(cal_evs) > 3:
                                pills_html += f"<div class='tds-cal-ev-more'>+{len(cal_evs) - 3}건</div>"

                            st.markdown(
                                _html(f"""
                                <div class="tds-cal-day-card {'selected' if is_sel else ''}" data-cal-day="{day_num}">
                                    <div class="tds-cal-day-top">
                                        <span class="tds-cal-day-num {dow_cls}">{day_num}</span>
                                        {today_badge}
                                    </div>
                                    <div class="tds-cal-ev-list">{pills_html}</div>
                                </div>
                                """),
                                unsafe_allow_html=True,
                            )
                            st.button(
                                " ",
                                key=f"cal_sel_d_{year}_{month}_{day_num}",
                                width="stretch",
                            )

    with col_side:
        c_m_left, c_m_right = st.columns([1.35, 0.95], gap="small")
        with c_m_left:
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
                    cstate["active_detail_modal"] = {
                        "year": year,
                        "month": month,
                        "day": selected_day,
                        "ev_id": f"m_{int(datetime.now().timestamp() * 1000)}",
                    }

        sel_date_obj = date(year, month, min(selected_day, calendar.monthrange(year, month)[1]))
        is_sel_today = (sel_date_obj == today_d)

        combined_day_evs: List[Dict[str, Any]] = []
        seen_ev_ids: set[str] = set()
        sel_ymd_tuple = (year, month, selected_day)

        for prev_d in sorted([int(k) for k in month_schedules.keys() if int(k) < selected_day]):
            for ev_cand in month_schedules.get(prev_d, []):
                is_tax_ev = str(ev_cand.get("type", "")).upper() == "TAX" or ev_cand.get("category") in ("세무기한", "세무일정")
                if is_tax_ev:
                    continue
                ev_cand.setdefault("origin_year", year)
                ev_cand.setdefault("origin_month", month)
                ev_cand.setdefault("origin_day", prev_d)
                if not ev_cand.get("done"):
                    cid = str(ev_cand.get("id", ""))
                    if cid not in seen_ev_ids:
                        combined_day_evs.append(ev_cand)
                        seen_ev_ids.add(cid)
                else:
                    comp_ymd = ev_cand.get("completed_on_ymd")
                    if isinstance(comp_ymd, (list, tuple)) and len(comp_ymd) == 3 and tuple(comp_ymd) == sel_ymd_tuple:
                        cid = str(ev_cand.get("id", ""))
                        if cid not in seen_ev_ids:
                            combined_day_evs.append(ev_cand)
                            seen_ev_ids.add(cid)

        for ev_cur in month_schedules.get(selected_day, []):
            ev_cur.setdefault("origin_year", year)
            ev_cur.setdefault("origin_month", month)
            ev_cur.setdefault("origin_day", selected_day)
            if ev_cur.get("done"):
                comp_ymd = ev_cur.get("completed_on_ymd")
                if isinstance(comp_ymd, (list, tuple)) and len(comp_ymd) == 3 and tuple(comp_ymd) < sel_ymd_tuple:
                    continue
            cid = str(ev_cur.get("id", ""))
            if cid not in seen_ev_ids:
                combined_day_evs.append(ev_cur)
                seen_ev_ids.add(cid)

        raw_day_evs = combined_day_evs
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
                        ev_title_esc = _html_lib.escape(_clean_any_legacy_token(str(ev.get("title", ""))))
                        t_norm = "" if str(ev.get("type", "")).upper() == "TAX" else _normalize_time_str(str(ev.get("time", "")))

                        subs = ev.get("sub_tasks", []) or []
                        sub_badge_html = ""
                        if subs:
                            s_done = sum(1 for s in subs if s.get("done"))
                            sub_badge_html = f"<span class='tds-sub-progress-pill'>{s_done}/{len(subs)}</span>"

                        urg_badge_html = "<span class='tds-urgent-pill'>중요</span>" if ev.get("urgent") else ""

                        orig_m = int(ev.get("origin_month", month))
                        orig_d = int(ev.get("origin_day", selected_day))
                        is_rollover = (orig_m != month or orig_d != selected_day)

                        status_tag_html = ""
                        if is_done:
                            status_tag_html = "<span class='tds-done-status-pill'>완료됨</span>"
                        elif is_rollover:
                            status_tag_html = f"<span class='tds-rollover-pill'>{orig_m}/{orig_d} 미완료 이월</span>"

                        client_val = str(ev.get("client", "")).strip()
                        client_badge_html = (
                            f"<span class='tds-sub-progress-pill'>{_html_lib.escape(client_val)}</span>"
                            if client_val and client_val != "내 스케줄"
                            else ""
                        )
                        rep_val = str(ev.get("repeat", "반복 안함")).strip()
                        rep_badge_html = (
                            f"<span class='tds-sub-progress-pill'>🔁 {_html_lib.escape(rep_val)}</span>"
                            if _is_repeating_schedule(ev)
                            else ""
                        )
                        att_val = str(ev.get("attachment", "")).strip()
                        att_badge_html = (
                            f"<span class='tds-sub-progress-pill' title='{_html_lib.escape(att_val)}'>📎 {_html_lib.escape(att_val[:14] + ('…' if len(att_val) > 14 else ''))}</span>"
                            if att_val
                            else ""
                        )
                        has_dtl = bool(ev.get("has_detail") or subs or ev.get("desc") or att_val or client_badge_html)
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
                                        {client_badge_html}
                                        {rep_badge_html}
                                        {att_badge_html}
                                        {status_tag_html}
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
                                    ev["completed_on_ymd"] = [year, month, selected_day] if ev["done"] else None
                                    ev["type"] = "DONE" if ev["done"] else ("TAX" if ev.get("category") in ("세무기한", "세무일정") else "MY")
                                    ev["_user_modified"] = True
                                    _save_user_schedules_to_disk(cstate)
                                    st.rerun()
                            with h_body:
                                if st.button(
                                    "상세",
                                    key=f"btn_todo_dtl_{ev_id_str}_{idx_e}",
                                    width="stretch",
                                ):
                                    owner_day = next(
                                        (int(dk) for dk, dlist in month_schedules.items() if any(str(x.get("id")) == ev_id_str for x in dlist)),
                                        selected_day,
                                    )
                                    cstate["active_detail_modal"] = {
                                        "year": year,
                                        "month": month,
                                        "day": owner_day,
                                        "ev_id": ev_id_str,
                                    }
                            with h_del:
                                if st.button(
                                    "삭제",
                                    key=f"btn_todo_del_{ev_id_str}_{idx_e}",
                                    width="stretch",
                                ):
                                    _delete_specific_schedule_by_id(cstate, ev_id_str)
                                    st.rerun()

            # ══════ 하단 고정 영역: 2단 레이아웃 (순수 Streamlit 위젯 직결) ══════
            with st.container(key="todo_bottom_dock_a"):
                r_seq = int(cstate.get("dock_reset_seq", 0))
                inp_key = f"dock_chat_inp_{year}_{month}_{selected_day}_{r_seq}"
                time_key = f"dock_time_inp_{year}_{month}_{selected_day}_{r_seq}"

                if inp_key in st.session_state:
                    cleaned_cur = _clean_any_legacy_token(str(st.session_state.get(inp_key, "")))
                    if cleaned_cur != st.session_state.get(inp_key):
                        st.session_state[inp_key] = cleaned_cur

                with st.container(key=f"dock_chat_wrap_{year}_{month}_{selected_day}"):
                    st.text_input(
                        "할 일 입력",
                        placeholder="할 일을 입력하고 Enter를 누르면 바로 등록됩니다 (Tab: 시간 이동)",
                        label_visibility="collapsed",
                        key=inp_key,
                        on_change=_commit_dock_schedule_on_enter,
                    )

                d_c2, d_c3, d_c4, d_c5, _d_spacer = st.columns([0.96, 0.76, 0.76, 0.76, 2.22], gap="small")
                with d_c2:
                    with st.container(key=f"dock_time_wrap_{year}_{month}_{selected_day}"):
                        st.text_input(
                            "시간 입력",
                            placeholder="00:00",
                            max_chars=5,
                            label_visibility="collapsed",
                            key=time_key,
                            on_change=_commit_dock_schedule_on_enter,
                        )
                with d_c3:
                    if st.button(
                        "알림",
                        width="stretch",
                        key=f"btn_dock_alarm_{year}_{month}_{selected_day}",
                    ):
                        cstate["dock_alarm"] = not bool(cstate.get("dock_alarm", False))
                        st.rerun()
                with d_c4:
                    if st.button(
                        "달력",
                        width="stretch",
                        key=f"btn_dock_cal_{year}_{month}_{selected_day}",
                    ):
                        cstate["dock_cal"] = not bool(cstate.get("dock_cal", False))
                        st.rerun()
                with d_c5:
                    if st.button(
                        "상세",
                        width="stretch",
                        key=f"btn_dock_detail_{year}_{month}_{selected_day}",
                    ):
                        cstate["dock_dtl"] = False
                        draft_txt = _clean_any_legacy_token(str(st.session_state.get(inp_key, "")))
                        draft_time = _normalize_time_str(str(st.session_state.get(time_key, "")))
                        cstate["pending_detail_draft"] = {
                            "title": draft_txt,
                            "time": draft_time,
                            "alarm": bool(cstate.get("dock_alarm", False)),
                            "show_on_cal": bool(cstate.get("dock_cal", True)),
                        }
                        cstate["active_detail_modal"] = {
                            "year": year,
                            "month": month,
                            "day": selected_day,
                            "ev_id": f"dtl_{int(datetime.now().timestamp() * 1000)}",
                        }

    render_floating_kakao_todo_overlay()

    active_modal = cstate.pop("active_detail_modal", None)
    if isinstance(active_modal, dict) and active_modal.get("ev_id"):
        _open_schedule_detail_dialog(
            int(active_modal["year"]),
            int(active_modal["month"]),
            int(active_modal["day"]),
            str(active_modal["ev_id"]),
        )
    elif cstate.pop("open_180d_modal_manual", False) or (expired_180d_items and not cstate.get("dismissed_180d_prompt", False)):
        _open_expired_180d_cleanup_dialog()


def render_floating_kakao_todo_overlay() -> None:
    """
    1) 상세일정 설정 모달: 시안 A 토스 아이스 블루(#DCEBFF) + 보더(#3182F6) + 순백색(#FFFFFF) 입력칸 강제 보장
    2) 입력칸에 어떠한 내부 코드 문자열도 주입하지 않고 순수 Streamlit 버튼과 연동
    3) AI 백그라운드 To-Do 블랙 패널: 홈버튼 퍼짐/감싸기 모션 + 파란 동그라미 (상세) 1회 클릭 아래 확장 + 우측 상단 ✕ 삭제 지원
    """
    cstate = _init_calendar_state()
    todos = cstate.get("kakao_todos", [])
    panel_open_init = bool(cstate.get("panel_open", False))
    silent_cnt = int(cstate.get("silent_read_count", 0))
    alarm_on_js = "true" if cstate.get("dock_alarm", False) else "false"
    cal_on_js = "true" if cstate.get("dock_cal", False) else "false"
    kst_today_iso = get_kst_today().isoformat()
    user_nm = str(st.session_state.get("current_workspace") or "범준").strip() or "범준"
    if user_nm.startswith("익명"):
        user_nm = "범준"

    todos_json = json.dumps(todos, ensure_ascii=False)
    init_open_js = "true" if panel_open_init else "false"
    user_nm_json = json.dumps(user_nm, ensure_ascii=False)
    kst_iso_json = json.dumps(kst_today_iso, ensure_ascii=False)

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
            const DOCK_ALARM_ON = {alarm_on_js};
            const DOCK_CAL_ON = {cal_on_js};

            if (parentWin._tdsCalCleanupTimer) {{
                parentWin.clearInterval(parentWin._tdsCalCleanupTimer);
                parentWin._tdsCalCleanupTimer = null;
            }}

            if (!parentDoc.getElementById("tds-sbx-cat-global-style")) {{
                const catSt = parentDoc.createElement("style");
                catSt.id = "tds-sbx-cat-global-style";
                catSt.textContent = `
                    @keyframes sbxCatCrouchJumpA {{
                        0%   {{ transform: translateY(0px) scaleX(1) scaleY(1); }}
                        22%  {{ transform: translateY(4px) scaleX(1.18) scaleY(0.76); }}
                        52%  {{ transform: translateY(-21px) scaleX(0.90) scaleY(1.12); }}
                        76%  {{ transform: translateY(2px) scaleX(1.09) scaleY(0.90); }}
                        88%  {{ transform: translateY(-4px) scaleX(0.97) scaleY(1.03); }}
                        100% {{ transform: translateY(0px) scaleX(1) scaleY(1); }}
                    }}
                    @keyframes sbxCatCrouchJumpB {{
                        0%   {{ transform: translateY(0px) scaleX(1) scaleY(1); }}
                        22%  {{ transform: translateY(4px) scaleX(1.18) scaleY(0.76); }}
                        52%  {{ transform: translateY(-21px) scaleX(0.90) scaleY(1.12); }}
                        76%  {{ transform: translateY(2px) scaleX(1.09) scaleY(0.90); }}
                        88%  {{ transform: translateY(-4px) scaleX(0.97) scaleY(1.03); }}
                        100% {{ transform: translateY(0px) scaleX(1) scaleY(1); }}
                    }}
                    [data-testid="stApp"] section[data-testid="stSidebar"] .sbx-brand {{
                        display: flex !important;
                        align-items: center !important;
                        gap: 12px !important;
                        padding: 18px 2px 14px !important;
                        overflow: visible !important;
                    }}
                    [data-testid="stApp"] section[data-testid="stSidebar"] .sbx-logo {{
                        width: 42px !important;
                        height: 42px !important;
                        border-radius: 14px !important;
                        transform-origin: center bottom !important;
                        will-change: transform !important;
                        cursor: pointer !important;
                    }}
                    [data-testid="stApp"] section[data-testid="stSidebar"] .sbx-logo.sbx-cat-jump-a {{
                        animation: sbxCatCrouchJumpA 0.52s cubic-bezier(0.22, 1, 0.36, 1) both !important;
                    }}
                    [data-testid="stApp"] section[data-testid="stSidebar"] .sbx-logo.sbx-cat-jump-b {{
                        animation: sbxCatCrouchJumpB 0.52s cubic-bezier(0.22, 1, 0.36, 1) both !important;
                    }}
                    [data-testid="stApp"] section[data-testid="stSidebar"] .sbx-brand-t {{
                        font-size: 1.38rem !important;
                        font-weight: 800 !important;
                        color: #191F28 !important;
                        letter-spacing: -0.03em !important;
                        line-height: 1.15 !important;
                        white-space: nowrap !important;
                    }}
                `;
                parentDoc.head.appendChild(catSt);
            }}

            if (!parentWin._sbxCatGlobalClickBound) {{
                parentWin._sbxCatGlobalClickBound = true;
                parentDoc.addEventListener("mousedown", function(e) {{
                    const t = e.target;
                    if (!t || !t.closest) return;
                    if (t.closest('[class*="st-key-btn_top_mode_"] button') || t.closest('.sbx-logo')) {{
                        const logoEl = parentDoc.querySelector('section[data-testid="stSidebar"] .sbx-logo');
                        if (logoEl) {{
                            logoEl.classList.remove("sbx-cat-jump-a", "sbx-cat-jump-b");
                            void logoEl.offsetWidth;
                            parentWin._sbxJsToggle = !parentWin._sbxJsToggle;
                            logoEl.classList.add(parentWin._sbxJsToggle ? "sbx-cat-jump-a" : "sbx-cat-jump-b");
                        }}
                    }}
                }}, true);
            }}

            function setReactInputValue(inp, newVal) {{
                if (!inp) return;
                const oldVal = inp.value;
                if (oldVal === newVal) return;
                const nativeSetter = Object.getOwnPropertyDescriptor(parentWin.HTMLInputElement.prototype, "value").set;
                nativeSetter.call(inp, newVal);
                if (inp._valueTracker) {{
                    inp._valueTracker.setValue(oldVal);
                }}
                inp.dispatchEvent(new Event("input", {{ bubbles: true }}));
            }}

            function formatNumericTimeLive(raw) {{
                const digits = String(raw || "").replace(/[^0-9]/g, "").slice(0, 4);
                if (!digits) return "";
                if (digits.length <= 2) {{
                    let h = parseInt(digits, 10);
                    if (digits.length === 2 && h > 23) return "23";
                    return digits;
                }}
                let hh = Math.min(23, parseInt(digits.slice(0, 2), 10));
                let mmStr = digits.slice(2);
                if (mmStr.length === 2) {{
                    let mm = Math.min(59, parseInt(mmStr, 10));
                    mmStr = String(mm).padStart(2, "0");
                }}
                return String(hh).padStart(2, "0") + ":" + mmStr;
            }}

            function applyButtonVisualState(btn, isSunken) {{
                if (!btn) return;
                btn.removeAttribute("title");
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

            function enforceOptionAIceBlueDialogSurface() {{
                const anchor = parentDoc.getElementById("tds-dlg-iceblue-anchor") || parentDoc.querySelector(".gcal-tds-title-wrap");
                if (!anchor) return;
                const dlgRoot = anchor.closest('div[data-testid="stDialog"], div[data-testid="stModal"], div[data-baseweb="modal"], dialog');
                if (!dlgRoot) return;
                let cur = anchor.parentElement;
                let modalCard = null;
                while (cur && cur !== dlgRoot && cur !== parentDoc.body) {{
                    const r = cur.getBoundingClientRect();
                    if (r.width >= 320 && r.width <= Math.min(920, parentWin.innerWidth * 0.90) && r.height >= 260) {{
                        modalCard = cur;
                    }}
                    cur = cur.parentElement;
                }}
                if (!modalCard) {{
                    modalCard = dlgRoot.querySelector('div[role="dialog"], [aria-label="dialog"]') || dlgRoot.querySelector('div > div');
                }}
                if (modalCard) {{
                    modalCard.style.setProperty("background", "#DCEBFF", "important");
                    modalCard.style.setProperty("background-color", "#DCEBFF", "important");
                    modalCard.style.setProperty("opacity", "1", "important");
                    modalCard.style.setProperty("border", "2.5px solid #3182F6", "important");
                    modalCard.style.setProperty("border-radius", "24px", "important");
                    modalCard.style.setProperty("box-shadow", "0 22px 54px rgba(25, 31, 40, 0.18), 0 4px 16px rgba(49, 130, 246, 0.14)", "important");

                    let inner = anchor.parentElement;
                    while (inner && inner !== modalCard && inner !== dlgRoot) {{
                        inner.style.setProperty("background", "transparent", "important");
                        inner.style.setProperty("background-color", "transparent", "important");
                        inner = inner.parentElement;
                    }}
                    const hdr = modalCard.querySelector('[data-testid="stDialogHeader"]');
                    if (hdr) {{
                        hdr.style.setProperty("background", "transparent", "important");
                        hdr.style.setProperty("background-color", "transparent", "important");
                    }}

                    let anc = modalCard.parentElement;
                    while (anc && anc !== parentDoc.body) {{
                        anc.style.setProperty("background", "transparent", "important");
                        anc.style.setProperty("background-color", "transparent", "important");
                        anc.style.setProperty("backdrop-filter", "none", "important");
                        if (anc === dlgRoot) break;
                        anc = anc.parentElement;
                    }}
                }}
            }}

            if (parentWin._tdsGlobalDocClickHandler) {{
                parentDoc.removeEventListener("click", parentWin._tdsGlobalDocClickHandler, true);
            }}
            parentWin._tdsGlobalDocClickHandler = function(ev) {{
                const t = ev.target;
                if (!t || !t.closest) return;

                const prevMonthBtn = t.closest("#tds-cal-prev-month-btn");
                if (prevMonthBtn) {{
                    ev.preventDefault();
                    ev.stopPropagation();
                    const stPrev = parentDoc.querySelector('.st-key-btn_cal_m_prev button');
                    if (stPrev) stPrev.click();
                    return;
                }}

                const nextMonthBtn = t.closest("#tds-cal-next-month-btn");
                if (nextMonthBtn) {{
                    ev.preventDefault();
                    ev.stopPropagation();
                    const stNext = parentDoc.querySelector('.st-key-btn_cal_m_next button');
                    if (stNext) stNext.click();
                    return;
                }}
            }};
            parentDoc.addEventListener("click", parentWin._tdsGlobalDocClickHandler, true);

            if (parentWin._tdsGlobalDocDblClickHandler) {{
                parentDoc.removeEventListener("dblclick", parentWin._tdsGlobalDocDblClickHandler, true);
            }}
            parentWin._tdsGlobalDocDblClickHandler = function(ev) {{
                const t = ev.target;
                if (!t || !t.closest) return;

                const bubbleEl = t.closest("#tds-kakao-square-bubble");
                if (bubbleEl && !t.closest("#tds-sb-dismiss") && !t.closest("#tds-sb-next")) {{
                    ev.preventDefault();
                    ev.stopPropagation();
                    if (parentWin._tdsKakaoState) {{
                        setPanelOpenAnimated(true);
                    }}
                    return;
                }}

                const calDayCard = t.closest('.tds-cal-day-card');
                if (calDayCard && !t.closest('[class*="st-key-cal_sel_d_"]')) {{
                    const dblOpenBtn = parentDoc.querySelector('.st-key-btn_cal_dbl_open_selected button');
                    if (dblOpenBtn) {{
                        dblOpenBtn.click();
                    }}
                }}
            }};
            parentDoc.addEventListener("dblclick", parentWin._tdsGlobalDocDblClickHandler, true);

            if (parentWin._tdsGlobalDocKeydownHandler) {{
                parentDoc.removeEventListener("keydown", parentWin._tdsGlobalDocKeydownHandler, true);
            }}
            parentWin._tdsGlobalDocKeydownHandler = function(ev) {{
                if (ev.key !== "Enter" || ev.isComposing) return;
                if (parentDoc.querySelector('div[data-testid="stDialog"]')) return;

                const dockEl = parentDoc.querySelector('.st-key-todo_bottom_dock_a');
                if (!dockEl) return;
                const activeEl = parentDoc.activeElement;
                if (activeEl && dockEl.contains(activeEl) && activeEl.tagName === "BUTTON") {{
                    ev.preventDefault();
                    ev.stopPropagation();
                    const hiddenSubmitBtn = parentDoc.querySelector('.st-key-btn_dock_hidden_enter_commit button');
                    if (hiddenSubmitBtn) hiddenSubmitBtn.click();
                }}
            }};
            parentDoc.addEventListener("keydown", parentWin._tdsGlobalDocKeydownHandler, true);

            if (parentWin._tdsGlobalBlurHandler) {{
                ["focusout", "blur", "change"].forEach(evtName => {{
                    parentDoc.removeEventListener(evtName, parentWin._tdsGlobalBlurHandler, true);
                }});
                parentWin._tdsGlobalBlurHandler = null;
            }}
            if (parentWin._tdsGlobalDocMousedownHandler) {{
                parentDoc.removeEventListener("mousedown", parentWin._tdsGlobalDocMousedownHandler, true);
                parentWin._tdsGlobalDocMousedownHandler = null;
            }}

            function bindDockInputsAndButtons() {{
                enforceOptionAIceBlueDialogSurface();

                const dockEl = parentDoc.querySelector('.st-key-todo_bottom_dock_a');
                if (!dockEl) return;

                parentDoc.querySelectorAll('[data-testid="InputInstructions"]').forEach(el => {{
                    el.style.display = "none";
                }});

                const alarmBtn = dockEl.querySelector('[class*="st-key-btn_dock_alarm_"] button');
                const calBtn = dockEl.querySelector('[class*="st-key-btn_dock_cal_"] button');
                const dtlBtn = dockEl.querySelector('[class*="st-key-btn_dock_detail_"] button');
                const chatInp = dockEl.querySelector('[class*="st-key-dock_chat_wrap_"] input');
                const timeInp = dockEl.querySelector('[class*="st-key-dock_time_wrap_"] input');

                const isDialogOpen = !!parentDoc.querySelector('div[data-testid="stDialog"]');
                applyButtonVisualState(alarmBtn, DOCK_ALARM_ON);
                applyButtonVisualState(calBtn, DOCK_CAL_ON);
                applyButtonVisualState(dtlBtn, isDialogOpen);

                if (chatInp && !chatInp._boundCleanTabV27) {{
                    chatInp._boundCleanTabV27 = true;
                    chatInp.addEventListener("keydown", function(ev) {{
                        if (ev.key === "Tab" && !ev.shiftKey) {{
                            ev.preventDefault();
                            ev.stopPropagation();
                            const curTimeInp = dockEl.querySelector('[class*="st-key-dock_time_wrap_"] input');
                            if (curTimeInp) {{
                                curTimeInp.focus();
                                curTimeInp.select();
                            }}
                        }}
                    }}, true);
                }}

                if (timeInp && !timeInp._boundCleanTimeV27) {{
                    timeInp._boundCleanTimeV27 = true;
                    timeInp.setAttribute("inputmode", "numeric");
                    timeInp.addEventListener("input", function() {{
                        const formatted = formatNumericTimeLive(this.value);
                        if (formatted !== this.value) {{
                            setReactInputValue(this, formatted);
                        }}
                    }});
                }}
            }}

            bindDockInputsAndButtons();
            setTimeout(bindDockInputsAndButtons, 120);
            setTimeout(bindDockInputsAndButtons, 350);

            let styleEl = parentDoc.getElementById("tds-kakao-floating-style");
            if (!styleEl) {{
                styleEl = parentDoc.createElement("style");
                styleEl.id = "tds-kakao-floating-style";
                parentDoc.head.appendChild(styleEl);
            }}
            styleEl.textContent = `
                @keyframes tossPulseRing {{
                    0% {{ box-shadow: 0 0 0 0 rgba(49, 130, 246, 0.45), 0 14px 28px -6px rgba(49, 130, 246, 0.45); }}
                    70% {{ box-shadow: 0 0 0 16px rgba(49, 130, 246, 0), 0 14px 28px -6px rgba(49, 130, 246, 0.45); }}
                    100% {{ box-shadow: 0 0 0 0 rgba(49, 130, 246, 0), 0 14px 28px -6px rgba(49, 130, 246, 0.45); }}
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
                    right: 18px;
                    bottom: 52px;
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
                    background: rgba(10, 14, 20, 0.22);
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
                    bottom: 128px;
                    width: min(60vw, 920px);
                    height: min(68vh, 680px);
                    min-width: 380px;
                    min-height: 460px;
                    background: #121417;
                    border: 1px solid #2A313C;
                    border-radius: 64px;
                    box-shadow: 0 28px 68px -12px rgba(0, 0, 0, 0.65), 0 0 0 1px rgba(255, 255, 255, 0.06);
                    transform-origin: calc(100% - 31px) calc(100% + 43px);
                    transform: translate3d(8px, 16px, 0) scale(0.02, 0.02);
                    opacity: 0;
                    pointer-events: none;
                    transition:
                        transform 0.22s cubic-bezier(0.55, 0.05, 0.67, 0.19),
                        opacity 0.18s ease-in,
                        border-radius 0.20s ease-in;
                    will-change: transform, opacity, border-radius;
                    z-index: 999995;
                    display: flex;
                    flex-direction: column;
                    overflow: hidden;
                }}
                #tds-kakao-todo-panel.open {{
                    transform: translate3d(0, 0, 0) scale(1, 1);
                    border-radius: 26px;
                    opacity: 1;
                    pointer-events: auto;
                    transition:
                        transform 0.27s cubic-bezier(0.16, 1, 0.3, 1),
                        opacity 0.16s ease-out,
                        border-radius 0.22s ease-out;
                }}

                .tds-kp-header {{
                    background: #121417;
                    border-bottom: 1px solid #232A34;
                    padding: 18px 24px;
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    flex-shrink: 0;
                }}
                .tds-kp-hdr-l {{
                    display: flex;
                    align-items: center;
                    gap: 14px;
                }}
                .tds-kp-char-circle {{
                    width: 48px;
                    height: 48px;
                    min-width: 48px;
                    min-height: 48px;
                    border-radius: 16px;
                    background: #3898FF;
                    border: none;
                    color: #FFFFFF;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    flex-shrink: 0;
                    box-shadow: 0 6px 16px rgba(56, 152, 255, 0.38), inset 0 1px 1px rgba(255, 255, 255, 0.28);
                }}
                .tds-kp-title-row {{
                    display: flex;
                    align-items: center;
                    gap: 8px;
                }}
                .tds-kp-title {{
                    font-size: 1.15rem;
                    font-weight: 800;
                    color: #FFFFFF;
                    letter-spacing: -0.02em;
                }}
                .tds-kp-pill-60 {{
                    font-size: 0.70rem;
                    font-weight: 800;
                    background: #17253B;
                    color: #60A5FA;
                    border: 1px solid #1E3A5F;
                    padding: 2px 10px;
                    border-radius: 999px;
                    font-variant-numeric: tabular-nums;
                }}
                .tds-kp-sub {{
                    font-size: 0.75rem;
                    color: #8B95A1;
                    font-weight: 600;
                    margin-top: 3px;
                }}
                .tds-kp-hdr-r {{
                    display: flex;
                    align-items: center;
                    gap: 8px;
                }}
                .tds-kp-approve-all-btn {{
                    padding: 9px 16px;
                    border-radius: 10px;
                    background: #3182F6;
                    color: #FFFFFF;
                    border: 1px solid #3B82F6;
                    font-size: 0.78rem;
                    font-weight: 800;
                    cursor: pointer;
                    transition: background 0.15s ease;
                    box-shadow: 0 4px 12px rgba(49, 130, 246, 0.35);
                }}
                .tds-kp-approve-all-btn:hover {{ background: #1B64DA; }}
                .tds-kp-close-btn {{
                    width: 36px;
                    height: 36px;
                    border-radius: 10px;
                    background: #1E242C;
                    border: 1px solid #2D3540;
                    color: #9CA3AF;
                    font-weight: 700;
                    cursor: pointer;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                }}
                .tds-kp-close-btn:hover {{ background: #2D3540; color: #FFFFFF; }}

                .tds-kp-tabs-bar {{
                    background: #121417;
                    border-bottom: 1px solid #232A34;
                    padding: 11px 24px;
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
                    gap: 8px;
                    flex-wrap: wrap;
                }}
                .tds-kp-tab {{
                    padding: 6px 14px;
                    border-radius: 999px;
                    font-size: 0.76rem;
                    font-weight: 800;
                    cursor: pointer;
                    font-variant-numeric: tabular-nums;
                }}
                .tds-kp-tab.all {{ background: #1E242C; color: #E5E7EB; border: 1px solid #374151; }}
                .tds-kp-tab.working {{ background: #2E2111; color: #F59E0B; border: 1px solid #4D3516; }}
                .tds-kp-tab.ready {{ background: #31151B; color: #F87171; border: 1px solid #521F28; }}
                .tds-kp-tab.approved {{ background: #0F2922; color: #34D399; border: 1px solid #164438; }}
                .tds-kp-tab.active-ring {{ outline: 2px solid #3B82F6; outline-offset: 1px; }}
                .tds-kp-silent-info {{ font-size: 0.73rem; color: #8B95A1; font-weight: 700; }}
                .tds-kp-silent-info b {{ color: #60A5FA; }}

                .tds-kp-body {{
                    flex: 1;
                    overflow-y: auto;
                    padding: 16px 24px;
                    background: #121417;
                    display: flex;
                    flex-direction: column;
                    gap: 10px;
                }}
                .tds-kp-card {{
                    position: relative;
                    background: #1A1F26;
                    border-radius: 16px;
                    border: 1px solid #2A313C;
                    padding: 12px 36px 12px 16px;
                    box-shadow: 0 4px 14px rgba(0, 0, 0, 0.25);
                    transition: border-color 0.22s ease, box-shadow 0.22s ease, background 0.22s ease;
                }}
                .tds-kp-card:hover {{ border-color: #3B82F6; }}
                .tds-kp-card.expanded {{
                    background: #1D232C;
                    border: 1.5px solid #3182F6;
                    box-shadow: 0 14px 34px rgba(0, 0, 0, 0.50);
                    padding: 14px 36px 18px 18px;
                }}
                /* 각 백그라운드 To-Do 카드 우측 상단 작은 ✕ 삭제 버튼 */
                .tds-kp-card-del-x {{
                    position: absolute;
                    top: 8px;
                    right: 8px;
                    width: 20px;
                    height: 20px;
                    border-radius: 50%;
                    background: #252C37;
                    border: 1px solid #374151;
                    color: #9CA3AF;
                    font-size: 0.64rem;
                    font-weight: 800;
                    line-height: 1;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    cursor: pointer;
                    padding: 0;
                    z-index: 6;
                    transition: all 0.15s ease;
                }}
                .tds-kp-card-del-x:hover {{
                    background: #F04452;
                    border-color: #F04452;
                    color: #FFFFFF;
                    transform: scale(1.08);
                }}
                .tds-kp-summary-row {{
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    gap: 12px;
                    min-height: 36px;
                    cursor: pointer;
                    user-select: none;
                }}
                .tds-kp-sum-left {{
                    display: flex;
                    align-items: center;
                    gap: 12px;
                    min-width: 0;
                    flex: 1;
                }}
                .tds-kp-st-badge {{
                    display: inline-flex;
                    align-items: center;
                    gap: 6px;
                    padding: 5px 11px;
                    border-radius: 999px;
                    font-size: 0.73rem;
                    font-weight: 800;
                    white-space: nowrap;
                    flex-shrink: 0;
                }}
                .tds-kp-st-badge.working {{ background: #2E2111; color: #F59E0B; border: 1px solid #4D3516; }}
                .tds-kp-st-badge.ready {{ background: #31151B; color: #F87171; border: 1px solid #521F28; }}
                .tds-kp-st-badge.approved {{ background: #0F2922; color: #34D399; border: 1px solid #164438; }}
                .tds-kp-mini-prog {{
                    width: 28px;
                    height: 5px;
                    border-radius: 999px;
                    background: rgba(245, 158, 11, 0.22);
                    overflow: hidden;
                    display: inline-block;
                }}
                .tds-kp-mini-prog-fill {{ height: 100%; background: #F59E0B; display: block; }}
                .tds-kp-sum-title-wrap {{
                    display: flex;
                    align-items: center;
                    gap: 8px;
                    min-width: 0;
                    flex: 1;
                }}
                .tds-kp-sum-title {{
                    font-size: 0.92rem;
                    font-weight: 800;
                    color: #FFFFFF;
                    white-space: nowrap;
                    overflow: hidden;
                    text-overflow: ellipsis;
                }}
                .tds-kp-blue-dtl-circle {{
                    width: 32px;
                    height: 32px;
                    min-width: 32px;
                    min-height: 32px;
                    border-radius: 50%;
                    background: #3182F6;
                    border: 1.5px solid #60A5FA;
                    color: #FFFFFF;
                    font-size: 0.68rem;
                    font-weight: 800;
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    flex-shrink: 0;
                    cursor: pointer;
                    padding: 0;
                    box-shadow: 0 3px 10px rgba(49, 130, 246, 0.38);
                    transition: transform 0.16s ease, background 0.16s ease;
                }}
                .tds-kp-blue-dtl-circle:hover {{ background: #1B64DA; transform: scale(1.08); }}
                .tds-kp-sum-right {{ display: flex; align-items: center; gap: 6px; flex-shrink: 0; }}
                .tds-kp-row-approve-btn {{
                    min-width: 72px;
                    height: 34px;
                    padding: 0 14px;
                    border-radius: 9px;
                    font-size: 0.78rem;
                    font-weight: 800;
                    cursor: pointer;
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                }}
                .tds-kp-row-approve-btn.ready {{ background: #3182F6; color: #FFFFFF; border: 1px solid #3B82F6; }}
                .tds-kp-row-approve-btn.working {{ background: #261D11; color: #FBBF24; border: 1px solid #573B16; }}
                .tds-kp-row-approve-btn.approved {{ background: #122620; color: #34D399; border: 1px solid #1C4236; cursor: default; }}

                .tds-kp-expand-drawer {{
                    max-height: 0;
                    opacity: 0;
                    overflow: hidden;
                    transform: translateY(-6px);
                    transition:
                        max-height 0.42s cubic-bezier(0.22, 1, 0.36, 1),
                        opacity 0.28s ease,
                        transform 0.32s cubic-bezier(0.22, 1, 0.36, 1),
                        margin-top 0.28s ease,
                        padding-top 0.28s ease;
                }}
                .tds-kp-card.expanded .tds-kp-expand-drawer {{
                    max-height: 760px;
                    opacity: 1;
                    transform: translateY(0);
                    margin-top: 12px;
                    padding-top: 14px;
                    border-top: 1px solid #2A3342;
                }}
                .tds-kp-exp-meta {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }}
                .tds-kp-exp-meta-l {{ display: flex; align-items: center; gap: 8px; }}
                .tds-kp-cat-pill {{ font-size: 0.72rem; font-weight: 700; color: #D1D5DB; background: #252C37; border: 1px solid #323B48; padding: 3px 10px; border-radius: 999px; }}
                .tds-kp-time {{ font-size: 0.73rem; color: #8B95A1; font-weight: 600; }}
                .tds-kp-company {{ font-size: 0.80rem; font-weight: 800; color: #60A5FA; }}
                .tds-kp-kakao-orig {{ font-size: 0.78rem; color: #CBD5E1; background: #13171D; border: 1px solid #252C37; padding: 10px 14px; border-radius: 12px; margin-bottom: 10px; font-weight: 600; }}
                .tds-kp-steps-box {{ background: #151A22; border: 1px solid #263040; border-radius: 12px; padding: 10px 14px; margin-bottom: 10px; display: flex; flex-direction: column; gap: 5px; }}
                .tds-kp-step-item {{ display: flex; align-items: center; gap: 8px; font-size: 0.76rem; font-weight: 700; color: #E2E8F0; }}
                .tds-kp-step-item.pending {{ color: #FBBF24; }}
                .tds-kp-step-icon-done {{ color: #34D399; font-weight: 900; }}
                .tds-kp-step-icon-wait {{ color: #F59E0B; font-weight: 900; }}
                .tds-kp-ai-res {{ font-size: 0.80rem; color: #E2E8F0; background: #152238; border: 1px solid #1E3A5F; padding: 11px 14px; border-radius: 12px; white-space: pre-line; line-height: 1.55; margin-bottom: 10px; font-weight: 600; }}
                .tds-kp-edit-wrap {{ margin-bottom: 10px; display: none; }}
                .tds-kp-edit-wrap.open {{ display: block; }}
                .tds-kp-edit-textarea {{ width: 100%; min-height: 88px; box-sizing: border-box; background: #0F1724; color: #F8FAFC; border: 1.5px solid #3B82F6; border-radius: 12px; padding: 10px 12px; font-family: inherit; font-size: 0.80rem; font-weight: 600; }}
                .tds-kp-edit-foot {{ display: flex; justify-content: flex-end; gap: 6px; margin-top: 6px; }}
                .tds-kp-edit-save-btn {{ padding: 5px 12px; border-radius: 8px; background: #3182F6; color: #FFFFFF; border: none; font-size: 0.73rem; font-weight: 800; cursor: pointer; }}
                .tds-kp-edit-cancel-btn {{ padding: 5px 10px; border-radius: 8px; background: #252C37; color: #CBD5E1; border: 1px solid #374151; font-size: 0.73rem; font-weight: 700; cursor: pointer; }}
                .tds-kp-attach-bar {{ display: flex; align-items: center; margin-bottom: 12px; }}
                .tds-kp-attach-chip {{ display: inline-flex; align-items: center; gap: 6px; padding: 6px 12px; border-radius: 10px; background: #172334; border: 1px solid #264063; color: #93C5FD; font-size: 0.75rem; font-weight: 700; cursor: pointer; }}
                .tds-kp-doc-preview {{ display: none; background: #11161D; border: 1px dashed #334155; border-radius: 10px; padding: 10px 14px; margin-bottom: 12px; font-size: 0.75rem; color: #94A3B8; line-height: 1.5; }}
                .tds-kp-doc-preview.open {{ display: block; }}
                .tds-kp-actions {{ display: flex; align-items: center; justify-content: flex-end; gap: 8px; flex-wrap: wrap; }}
                .tds-kp-btn-edit {{ padding: 8px 13px; border-radius: 10px; background: #1E2631; color: #93C5FD; border: 1px solid #2E3C4E; font-size: 0.75rem; font-weight: 700; cursor: pointer; }}
                .tds-kp-btn-jump {{ padding: 8px 14px; border-radius: 10px; background: #252C37; color: #E5E7EB; border: 1px solid #374151; font-size: 0.76rem; font-weight: 700; cursor: pointer; }}
                .tds-kp-btn-approve {{ padding: 8px 16px; border-radius: 10px; background: #3182F6; color: #FFFFFF; border: 1px solid #3B82F6; font-size: 0.78rem; font-weight: 800; cursor: pointer; }}
                .tds-kp-btn-finish {{ padding: 8px 16px; border-radius: 10px; background: #B45309; color: #FFFFFF; border: 1px solid #D97706; font-size: 0.78rem; font-weight: 800; cursor: pointer; }}
                .tds-kp-done-txt {{ font-size: 0.76rem; font-weight: 800; color: #34D399; }}
                .tds-kp-footer {{ background: #121417; border-top: 1px solid #232A34; padding: 12px 24px; display: flex; align-items: center; justify-content: space-between; font-size: 0.76rem; color: #8B95A1; flex-shrink: 0; }}
                .tds-kp-min-btn {{ padding: 7px 14px; border-radius: 10px; background: #1E242C; border: 1px solid #2D3540; font-weight: 700; color: #E5E7EB; cursor: pointer; }}

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
                    cursor: pointer;
                }}
                #tds-kakao-square-bubble.hidden {{ display: none !important; }}
                .tds-sb-top {{ display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 6px; }}
                .tds-sb-badge {{ display: inline-flex; align-items: center; padding: 2px 8px; border-radius: 999px; font-size: 0.68rem; font-weight: 800; background: #E8F3FF; color: #3182F6; }}
                .tds-sb-dismiss {{ background: transparent; border: none; color: #8B95A1; font-size: 0.75rem; font-weight: 700; cursor: pointer; }}
                .tds-sb-msg {{ font-size: 0.86rem; font-weight: 800; color: #191F28; line-height: 1.38; margin: 0; }}
                .tds-sb-foot {{ display: flex; align-items: center; justify-content: space-between; margin-top: 12px; padding-top: 10px; border-top: 1px solid #F2F4F6; }}
                .tds-sb-time {{ font-size: 0.70rem; color: #8B95A1; font-weight: 600; }}
                .tds-sb-btns {{ display: flex; align-items: center; gap: 6px; }}
                .tds-sb-btn-next {{ padding: 4px 10px; border-radius: 6px; background: #F2F4F6; border: none; color: #191F28; font-size: 0.72rem; font-weight: 700; cursor: pointer; }}
                .tds-sb-btn-open {{ padding: 4px 12px; border-radius: 6px; background: #3182F6; border: none; color: #FFFFFF; font-size: 0.72rem; font-weight: 800; cursor: pointer; }}
                .tds-sb-tail {{ width: 14px; height: 14px; background: #FFFFFF; border-right: 2px solid #3182F6; border-bottom: 2px solid #3182F6; transform: rotate(45deg); position: absolute; bottom: -8px; right: 28px; }}

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
                #tds-kakao-home-fab:hover {{ background: #3182F6; transform: scale(1.05); }}
                #tds-kakao-home-fab.dragging {{ cursor: grabbing !important; transform: scale(1.08) !important; transition: none !important; }}
                .cute-face-svg {{ animation: cuteWinkBounce 2.8s ease-in-out infinite; pointer-events: none; }}
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
                <svg class="cute-face-svg" width="34" height="34" viewBox="0 0 32 32" fill="none">
                    <circle cx="16" cy="16" r="12.5" stroke="#FFFFFF" stroke-width="2.9" stroke-linecap="round" stroke-linejoin="round" />
                    <line x1="11.8" y1="13.2" x2="11.8" y2="18.5" stroke="#FFFFFF" stroke-width="3.0" stroke-linecap="round" />
                    <line x1="20.2" y1="13.2" x2="20.2" y2="18.5" stroke="#FFFFFF" stroke-width="3.0" stroke-linecap="round" />
                </svg>
            `;

            if (!parentWin._tdsKakaoState) {{
                parentWin._tdsKakaoState = {{
                    open: INIT_OPEN,
                    filter: "ALL",
                    bubbleIdx: 0,
                    bubbleDismissed: false,
                    todos: TODOS_DATA,
                    deletedIds: {{}},
                    customPos: null,
                    serverKstIso: SERVER_KST_ISO,
                    expandedMap: {{}},
                    editingMap: {{}},
                    docPreviewMap: {{}}
                }};
            }} else {{
                if (!parentWin._tdsKakaoState.deletedIds) parentWin._tdsKakaoState.deletedIds = {{}};
                const delMap = parentWin._tdsKakaoState.deletedIds;
                const prevTodos = parentWin._tdsKakaoState.todos || [];
                const prevLen = prevTodos.length;
                const prevMap = {{}};
                prevTodos.forEach(item => {{
                    if (item && item.id) prevMap[item.id] = item;
                }});
                const incomingFiltered = TODOS_DATA.filter(srvItem => !(srvItem && srvItem.id && delMap[srvItem.id]));
                if (incomingFiltered.length >= prevTodos.length) {{
                    parentWin._tdsKakaoState.todos = incomingFiltered.map(srvItem => {{
                        const locItem = srvItem && srvItem.id ? prevMap[srvItem.id] : null;
                        if (locItem && (locItem._clientModified || locItem.status_code === "APPROVED")) {{
                            return Object.assign({{}}, srvItem, locItem);
                        }}
                        return srvItem;
                    }});
                }}
                if (!parentWin._tdsKakaoState.expandedMap) parentWin._tdsKakaoState.expandedMap = {{}};
                if (!parentWin._tdsKakaoState.editingMap) parentWin._tdsKakaoState.editingMap = {{}};
                if (!parentWin._tdsKakaoState.docPreviewMap) parentWin._tdsKakaoState.docPreviewMap = {{}};
                if (incomingFiltered.length > prevLen) {{
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
                    rootEl.style.right = "18px";
                    rootEl.style.bottom = "52px";
                }}
            }}

            parentWin._tdsActiveCalFrame = frameEl;
            parentWin._tdsCalCleanupTimer = parentWin.setInterval(function() {{
                const activeFr = parentWin._tdsActiveCalFrame;
                if (!activeFr || !parentDoc.body.contains(activeFr)) {{
                    parentWin.clearInterval(parentWin._tdsCalCleanupTimer);
                    parentWin._tdsCalCleanupTimer = null;
                    return;
                }}
                bindDockInputsAndButtons();
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
                        setPanelOpenAnimated(!parentWin._tdsKakaoState.open);
                    }}
                    hasDragged = false;
                }};

                parentWin.addEventListener("mousemove", parentWin._tdsFabMouseMoveHandler);
                parentWin.addEventListener("mouseup", parentWin._tdsFabMouseUpHandler);

                fabBtn.onclick = function(e) {{
                    if (hasDragged) return;
                    if (e && e.detail === 0) {{
                        setPanelOpenAnimated(!parentWin._tdsKakaoState.open);
                    }}
                }};
            }}

            function updatePanelTransformOriginToFab() {{
                const panelEl = parentDoc.getElementById("tds-kakao-todo-panel");
                const fabEl = parentDoc.getElementById("tds-kakao-home-fab");
                if (!panelEl || !fabEl) return;
                const pRect = panelEl.getBoundingClientRect();
                const fRect = fabEl.getBoundingClientRect();
                if (pRect.width > 10 && fRect.width > 10) {{
                    const originX = (panelEl.offsetWidth || 820) - 31;
                    const originY = (panelEl.offsetHeight || 620) + 43;
                    panelEl.style.transformOrigin = `${{originX}}px ${{originY}}px`;
                }}
            }}

            function setPanelOpenAnimated(nextOpen) {{
                const stObj = parentWin._tdsKakaoState;
                if (!stObj) return;
                stObj.open = !!nextOpen;

                const panelEl = parentDoc.getElementById("tds-kakao-todo-panel");
                const backdropEl = parentDoc.getElementById("tds-kakao-backdrop");
                const sbBubble = parentDoc.getElementById("tds-kakao-square-bubble");
                const fabBtn = parentDoc.getElementById("tds-kakao-home-fab");

                if (!panelEl || !backdropEl) {{
                    renderOverlay();
                    return;
                }}

                updatePanelTransformOriginToFab();

                if (stObj.open) {{
                    panelEl.classList.add("open");
                    backdropEl.classList.add("open");
                    if (sbBubble) sbBubble.classList.add("hidden");
                }} else {{
                    panelEl.classList.remove("open");
                    backdropEl.classList.remove("open");
                    const allTodos = (stObj.todos || []).filter(t => String(t.id || "").indexOf("todo_alarm_") !== 0 && t.client !== "Today To Do");
                    const readyCnt = allTodos.filter(t => getStatusCode(t) === "READY").length;
                    if (sbBubble && readyCnt > 0 && !stObj.bubbleDismissed) {{
                        sbBubble.classList.remove("hidden");
                    }}
                }}

                if (fabBtn) {{
                    const allTodos = (stObj.todos || []).filter(t => String(t.id || "").indexOf("todo_alarm_") !== 0 && t.client !== "Today To Do");
                    const totalAttention = allTodos.filter(t => getStatusCode(t) === "READY" || getStatusCode(t) === "WORKING").length;
                    fabBtn.innerHTML = `
                        ${{totalAttention > 0 ? `<span id="tds-kakao-fab-badge">${{totalAttention}}</span>` : ''}}
                        ${{stObj.open ? FAB_ICON_OPEN_SVG : FAB_ICON_CLOSED_SVG}}
                    `;
                }}
            }}

            function toggleCardExpandWithAnimation(cardEl, itemId) {{
                if (!cardEl || !itemId) return;
                const stObj = parentWin._tdsKakaoState;
                const isNowExp = !cardEl.classList.contains("expanded");
                if (isNowExp) {{
                    cardEl.classList.add("expanded");
                    stObj.expandedMap[itemId] = true;
                }} else {{
                    cardEl.classList.remove("expanded");
                    delete stObj.expandedMap[itemId];
                }}
            }}

            function renderOverlay() {{
                const stObj = parentWin._tdsKakaoState;
                const allTodos = (stObj.todos || []).filter(t => String(t.id || "").indexOf("todo_alarm_") !== 0 && t.client !== "Today To Do");
                const workingList = allTodos.filter(t => getStatusCode(t) === "WORKING");
                const readyList = allTodos.filter(t => getStatusCode(t) === "READY");
                const approvedList = allTodos.filter(t => getStatusCode(t) === "APPROVED");
                const totalAttention = readyList.length + workingList.length;

                const filtered = allTodos.filter(t => {{
                    if (stObj.filter === "ALL") return true;
                    return getStatusCode(t) === stObj.filter;
                }});

                const cardsHtml = filtered.length === 0
                    ? `<div style="padding:56px 24px;text-align:center;color:#8B95A1;font-weight:700;line-height:1.6;">
                        <div style="font-size:0.95rem;color:#E2E8F0;font-weight:800;margin-bottom:6px;">현재 대기 중인 AI 카톡 백그라운드 작업이 없습니다</div>
                        <div style="font-size:0.78rem;color:#6B7684;">실시간 카카오톡이 수신되면 AI가 백그라운드에서 작업을 마친 뒤 이곳과 홈버튼 말풍선으로 알려드립니다.</div>
                       </div>`
                    : filtered.map(item => {{
                        const sCode = getStatusCode(item);
                        const steps = Array.isArray(item.workflow_steps) ? item.workflow_steps : [];
                        const doneStepCnt = steps.filter(s => !!s.done).length;
                        const totalStepCnt = Math.max(1, steps.length);
                        const stepPct = Math.round((doneStepCnt / totalStepCnt) * 100);
                        const isExpanded = !!stObj.expandedMap[item.id];
                        const isEditing = !!stObj.editingMap[item.id];
                        const isDocOpen = !!stObj.docPreviewMap[item.id];

                        let stBadgeHtml = "";
                        let rightSummaryBtnHtml = "";
                        let expActBtnsHtml = "";

                        if (sCode === "WORKING") {{
                            stBadgeHtml = `
                                <span class="tds-kp-st-badge working">
                                    <span>● AI작업중 (${{doneStepCnt}}/${{totalStepCnt}})</span>
                                    <span class="tds-kp-mini-prog"><span class="tds-kp-mini-prog-fill" style="width:${{stepPct}}%"></span></span>
                                </span>
                            `;
                            rightSummaryBtnHtml = `<button class="tds-kp-row-approve-btn working" data-act="finish" data-id="${{escHtml(item.id)}}">작업중...</button>`;
                            expActBtnsHtml = `<button class="tds-kp-btn-finish" data-act="finish" data-id="${{escHtml(item.id)}}">작업 즉시 완료시키기 (시연)</button>`;
                        }} else if (sCode === "READY") {{
                            stBadgeHtml = `<span class="tds-kp-st-badge ready">● 승인요청</span>`;
                            rightSummaryBtnHtml = `<button class="tds-kp-row-approve-btn ready" data-act="approve" data-id="${{escHtml(item.id)}}">승인</button>`;
                            expActBtnsHtml = `
                                <button class="tds-kp-btn-edit" data-act="toggle_edit" data-id="${{escHtml(item.id)}}">✏️ 답장 문구 직접 수정</button>
                                <button class="tds-kp-btn-jump" data-act="jump" data-id="${{escHtml(item.id)}}">뒤쪽 작업화면에 띄우기</button>
                                <button class="tds-kp-btn-approve" data-act="approve" data-id="${{escHtml(item.id)}}">${{escHtml(item.action_label || "카톡 답장 복사 & 승인완료")}}</button>
                            `;
                        }} else {{
                            stBadgeHtml = `<span class="tds-kp-st-badge approved">✓ 승인완료</span>`;
                            rightSummaryBtnHtml = `<button class="tds-kp-row-approve-btn approved" disabled>승인됨 ✓</button>`;
                            expActBtnsHtml = `<span class="tds-kp-done-txt">✓ 사용자 승인 및 처리가 완료된 항목입니다</span>`;
                        }}

                        const origTxt = item.kakao_original || `[카톡 수신] ${{item.title}}`;
                        const aiTxt = item.ai_result || item.preview || "";
                        const attachName = item.attachment || `${{item.client || "거래처"}}_검토자료.pdf`;
                        const stepsHtml = steps.length > 0
                            ? `<div class="tds-kp-steps-box">` + steps.map(st => {{
                                const isDone = !!st.done;
                                return `<div class="tds-kp-step-item ${{isDone ? '' : 'pending'}}">
                                    <span class="${{isDone ? 'tds-kp-step-icon-done' : 'tds-kp-step-icon-wait'}}">${{isDone ? '✓' : '⏳'}}</span>
                                    <span>${{escHtml(st.step || "")}}</span>
                                </div>`;
                            }}).join("") + `</div>`
                            : "";

                        return `
                            <div class="tds-kp-card ${{isExpanded ? 'expanded' : ''}}" data-card-id="${{escHtml(item.id)}}">
                                <button type="button" class="tds-kp-card-del-x" data-act="delete_item" data-id="${{escHtml(item.id)}}" title="이 작업 삭제">✕</button>
                                <div class="tds-kp-summary-row" data-summary-id="${{escHtml(item.id)}}" title="클릭하면 AI 체크리스트와 카톡 답장 상세가 아래로 펼쳐집니다">
                                    <div class="tds-kp-sum-left">
                                        ${{stBadgeHtml}}
                                        <div class="tds-kp-sum-title-wrap">
                                            <span class="tds-kp-sum-title">${{escHtml(item.title)}}</span>
                                            <button type="button" class="tds-kp-blue-dtl-circle" data-dtl-toggle="${{escHtml(item.id)}}" title="클릭하여 상세 열기/닫기">상세</button>
                                        </div>
                                    </div>
                                    <div class="tds-kp-sum-right">
                                        ${{rightSummaryBtnHtml}}
                                    </div>
                                </div>

                                <div class="tds-kp-expand-drawer">
                                    <div class="tds-kp-exp-meta">
                                        <div class="tds-kp-exp-meta-l">
                                            <span class="tds-kp-cat-pill">${{escHtml(item.category || "카톡 자동화")}}</span>
                                            <span class="tds-kp-time">${{escHtml(item.time_ago || "")}}</span>
                                        </div>
                                        <span class="tds-kp-company">${{escHtml(item.client || "")}}</span>
                                    </div>
                                    <div class="tds-kp-kakao-orig">${{escHtml(origTxt)}}</div>
                                    ${{stepsHtml}}
                                    <div class="tds-kp-ai-res" id="tds-kp-res-box-${{escHtml(item.id)}}">${{escHtml(aiTxt)}}</div>

                                    <div class="tds-kp-edit-wrap ${{isEditing ? 'open' : ''}}" id="tds-kp-edit-wrap-${{escHtml(item.id)}}">
                                        <textarea class="tds-kp-edit-textarea" id="tds-kp-edit-ta-${{escHtml(item.id)}}">${{escHtml(aiTxt)}}</textarea>
                                        <div class="tds-kp-edit-foot">
                                            <button class="tds-kp-edit-cancel-btn" data-act="cancel_edit" data-id="${{escHtml(item.id)}}">취소</button>
                                            <button class="tds-kp-edit-save-btn" data-act="save_edit" data-id="${{escHtml(item.id)}}">문구 적용하기</button>
                                        </div>
                                    </div>

                                    <div class="tds-kp-attach-bar">
                                        <button class="tds-kp-attach-chip" data-act="toggle_doc" data-id="${{escHtml(item.id)}}">
                                            📄 ${{escHtml(attachName)}} 미리보기 ${{isDocOpen ? '▴' : '▾'}}
                                        </button>
                                    </div>
                                    <div class="tds-kp-doc-preview ${{isDocOpen ? 'open' : ''}}" id="tds-kp-doc-prev-${{escHtml(item.id)}}">
                                        <div style="color:#60A5FA;font-weight:800;margin-bottom:4px;">🛡️ AI 생성·발급 서류 무결성 검증 요약</div>
                                        <div>• 파일명: <b style="color:#E2E8F0;">${{escHtml(attachName)}}</b></div>
                                        <div>• 대상 거래처: <b style="color:#E2E8F0;">${{escHtml(item.client || "지정 거래처")}}</b> (사업자등록번호 및 귀속연월 대조 일치 완료)</div>
                                        <div>• 상태: 카톡 답장 복사 및 승인 시 해당 서류 폴더 경로가 클립보드에 함께 준비됩니다.</div>
                                    </div>

                                    <div class="tds-kp-actions">${{expActBtnsHtml}}</div>
                                </div>
                            </div>
                        `;
                    }}).join("");

                let showBubble = (readyList.length > 0 && !stObj.open && !stObj.bubbleDismissed);
                if (stObj.bubbleIdx >= readyList.length) stObj.bubbleIdx = 0;
                const bItem = readyList[stObj.bubbleIdx] || {{}};
                const bCat = bItem.category ? `${{bItem.category}} (${{stObj.bubbleIdx + 1}}/${{readyList.length}})` : "카톡 백그라운드 알림";
                const bMsg = bItem.bubble_msg || `${{CURRENT_USER}}님, 거래처에 보낼 세법 검토 카톡이 완성되었습니다`;
                const bTime = `${{bItem.time_ago || "방금 전"}}`;

                rootEl.innerHTML = `
                    <div id="tds-kakao-backdrop" class="${{stObj.open ? 'open' : ''}}"></div>
                    <div id="tds-kakao-todo-panel" class="${{stObj.open ? 'open' : ''}}">
                        <div class="tds-kp-header">
                            <div class="tds-kp-hdr-l">
                                <div class="tds-kp-char-circle">${{HEADER_CHAR_SVG}}</div>
                                <div>
                                    <div class="tds-kp-title-row">
                                        <span class="tds-kp-title">카톡 백그라운드 To-Do</span>
                                        <span class="tds-kp-pill-60">AI 카톡 자동화</span>
                                    </div>
                                    <div class="tds-kp-sub">파란 동그라미 [상세] 버튼을 한 번 클릭하면 AI 체크리스트와 예상 카톡 답장이 아래로 펼쳐집니다</div>
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
                                <button class="tds-kp-tab working ${{stObj.filter === 'WORKING' ? 'active-ring' : ''}}" data-filter="WORKING">AI작업중 ${{workingList.length}}</button>
                                <button class="tds-kp-tab ready ${{stObj.filter === 'READY' ? 'active-ring' : ''}}" data-filter="READY">승인요청 ${{readyList.length}}</button>
                                <button class="tds-kp-tab approved ${{stObj.filter === 'APPROVED' ? 'active-ring' : ''}}" data-filter="APPROVED">승인완료 ${{approvedList.length}}</button>
                            </div>
                            <div class="tds-kp-silent-info">통상적 인사 자동 닫기(1소거): <b>${{SILENT_CNT}}건</b></div>
                        </div>

                        <div class="tds-kp-body">${{cardsHtml}}</div>

                        <div class="tds-kp-footer">
                            <span>💡 파란 동그라미 [상세] 버튼을 클릭하면 AI 작업단계와 예상 카톡 답장을 상세 확인·수정할 수 있습니다</span>
                            <button class="tds-kp-min-btn" id="tds-kp-minimize">홈버튼으로 접기 ↘</button>
                        </div>
                    </div>

                    <div id="tds-kakao-square-bubble" class="${{showBubble ? '' : 'hidden'}}" title="더블클릭하면 전체 체크리스트 화면이 열립니다">
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
                updatePanelTransformOriginToFab();

                const fabBtn = parentDoc.getElementById("tds-kakao-home-fab");
                const closeBtn = parentDoc.getElementById("tds-kp-close");
                const minBtn = parentDoc.getElementById("tds-kp-minimize");
                const backdropEl = parentDoc.getElementById("tds-kakao-backdrop");
                const approveAllBtn = parentDoc.getElementById("tds-kp-approve-all");
                const sbBubble = parentDoc.getElementById("tds-kakao-square-bubble");
                const sbDismiss = parentDoc.getElementById("tds-sb-dismiss");
                const sbNext = parentDoc.getElementById("tds-sb-next");
                const sbOpen = parentDoc.getElementById("tds-sb-open");

                bindFabDrag(fabBtn);

                if (closeBtn) closeBtn.onclick = function() {{ setPanelOpenAnimated(false); }};
                if (minBtn) minBtn.onclick = function() {{ setPanelOpenAnimated(false); }};
                if (backdropEl) backdropEl.onclick = function() {{ setPanelOpenAnimated(false); }};

                if (sbBubble) {{
                    sbBubble.ondblclick = function(e) {{
                        if (e.target && e.target.closest && (e.target.closest("#tds-sb-dismiss") || e.target.closest("#tds-sb-next"))) return;
                        e.preventDefault();
                        e.stopPropagation();
                        setPanelOpenAnimated(true);
                    }};
                    sbBubble.onclick = function(e) {{
                        if (e.target && e.target.closest && (e.target.closest("#tds-sb-dismiss") || e.target.closest("#tds-sb-next") || e.target.closest("#tds-sb-open"))) return;
                        const nowMs = Date.now();
                        const prevTs = stObj._lastBubbleClickTs || 0;
                        stObj._lastBubbleClickTs = nowMs;
                        if ((nowMs - prevTs) < 450) {{
                            stObj._lastBubbleClickTs = 0;
                            setPanelOpenAnimated(true);
                        }}
                    }};
                }}

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
                        setPanelOpenAnimated(true);
                    }};
                }}

                if (approveAllBtn) {{
                    approveAllBtn.onclick = function() {{
                        allTodos.forEach(t => {{
                            if (getStatusCode(t) === "READY") {{
                                t.status_code = "APPROVED";
                                t.status = "사용자 승인완료";
                                t.time_ago = "방금 일괄승인";
                                t.approved_date_iso = SERVER_KST_ISO;
                                t.checked = true;
                                t._clientModified = true;
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

                rootEl.querySelectorAll("button[data-dtl-toggle]").forEach(dtlBtn => {{
                    dtlBtn.onclick = function(e) {{
                        e.preventDefault();
                        e.stopPropagation();
                        const itemId = this.getAttribute("data-dtl-toggle");
                        const cardEl = this.closest(".tds-kp-card");
                        toggleCardExpandWithAnimation(cardEl, itemId);
                    }};
                }});

                rootEl.querySelectorAll(".tds-kp-summary-row").forEach(sumRow => {{
                    const itemId = sumRow.getAttribute("data-summary-id");
                    const cardEl = sumRow.closest(".tds-kp-card");

                    sumRow.onclick = function(e) {{
                        if (e.target && e.target.closest && e.target.closest("button[data-act]")) return;
                        e.preventDefault();
                        e.stopPropagation();
                        toggleCardExpandWithAnimation(cardEl, itemId);
                    }};
                }});

                rootEl.querySelectorAll("button[data-act]").forEach(btn => {{
                    btn.onclick = function(e) {{
                        e.stopPropagation();
                        const act = this.getAttribute("data-act");
                        const tid = this.getAttribute("data-id");

                        if (act === "delete_item") {{
                            stObj.todos = (stObj.todos || []).filter(x => x.id !== tid);
                            if (!stObj.deletedIds) stObj.deletedIds = {{}};
                            stObj.deletedIds[tid] = true;
                            delete stObj.expandedMap[tid];
                            delete stObj.editingMap[tid];
                            delete stObj.docPreviewMap[tid];
                            renderOverlay();
                            const hiddenDelBtn = parentDoc.querySelector(`.st-key-btn_kt_del_${{tid}} button`);
                            if (hiddenDelBtn) hiddenDelBtn.click();
                            return;
                        }}

                        const target = allTodos.find(x => x.id === tid);
                        if (!target) return;

                        if (act === "finish") {{
                            target.status_code = "READY";
                            target.status = "작업 완료, 승인요청중";
                            target.time_ago = "방금 완료됨";
                            if (Array.isArray(target.workflow_steps)) {{
                                target.workflow_steps.forEach(st => {{ st.done = true; }});
                            }}
                            target.ai_result = "✅ 지정 폴더 저장 및 에이전트AI 급여명세서 화면 자동 입력이 완료되었습니다!";
                            target._clientModified = true;
                            stObj.bubbleDismissed = false;
                            stObj.bubbleIdx = 0;
                            renderOverlay();
                        }} else if (act === "approve") {{
                            copyTextSafe(target.ai_result || target.preview || "");
                            target.status_code = "APPROVED";
                            target.status = "사용자 승인완료";
                            target.time_ago = "방금 승인됨";
                            target.approved_date_iso = SERVER_KST_ISO;
                            target.checked = true;
                            target._clientModified = true;
                            renderOverlay();
                        }} else if (act === "jump") {{
                            stObj.open = false;
                            renderOverlay();
                            triggerSidebarMode(target.target_mode || "CALENDAR");
                        }} else if (act === "toggle_edit") {{
                            const editWrap = parentDoc.getElementById(`tds-kp-edit-wrap-${{tid}}`);
                            if (editWrap) {{
                                const nowOpen = !editWrap.classList.contains("open");
                                editWrap.classList.toggle("open", nowOpen);
                                stObj.editingMap[tid] = nowOpen;
                                if (nowOpen) {{
                                    const ta = parentDoc.getElementById(`tds-kp-edit-ta-${{tid}}`);
                                    if (ta) ta.focus();
                                }}
                            }}
                        }} else if (act === "cancel_edit") {{
                            const editWrap = parentDoc.getElementById(`tds-kp-edit-wrap-${{tid}}`);
                            if (editWrap) editWrap.classList.remove("open");
                            delete stObj.editingMap[tid];
                        }} else if (act === "save_edit") {{
                            const ta = parentDoc.getElementById(`tds-kp-edit-ta-${{tid}}`);
                            const resBox = parentDoc.getElementById(`tds-kp-res-box-${{tid}}`);
                            const editWrap = parentDoc.getElementById(`tds-kp-edit-wrap-${{tid}}`);
                            if (ta) {{
                                target.ai_result = ta.value;
                                target.preview = ta.value;
                                target._clientModified = true;
                                if (resBox) resBox.textContent = ta.value;
                            }}
                            if (editWrap) editWrap.classList.remove("open");
                            delete stObj.editingMap[tid];
                        }} else if (act === "toggle_doc") {{
                            const docBox = parentDoc.getElementById(`tds-kp-doc-prev-${{tid}}`);
                            if (docBox) {{
                                const nowOpen = !docBox.classList.contains("open");
                                docBox.classList.toggle("open", nowOpen);
                                stObj.docPreviewMap[tid] = nowOpen;
                                this.innerHTML = `📄 ${{escHtml(target.attachment || "검토자료.pdf")}} 미리보기 ${{nowOpen ? '▴' : '▾'}}`;
                            }}
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
