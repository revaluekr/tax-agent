def _push_kakao_emp_excel_to_payroll(company: str, employees_sample: List[Dict[str, Any]]) -> None:
    """카톡 백그라운드 시뮬레이터(⑤ 급여대장 엑셀파일 수신) → payroll_auto_state['employees'] 자동 반영"""
    try:
        from payroll_automated.ui import _get_payroll_state, _recalculate_all_employee_rows
        pstate = _get_payroll_state()
        if company:
            pstate["corp_name"] = company
        pstate["sub_mode"] = "EMP"
        for emp_in in reversed(employees_sample):
            emp_nm = str(emp_in.get("name") or emp_in.get("성명") or "임직원").strip()
            new_emp = {
                "사업장": company or "본점",
                "사원코드": f"{len(pstate.get('employees', [])) + 1:03d}",
                "성명": emp_nm,
                "사원명": emp_nm,
                "주민등록번호": "",
                "부서": emp_in.get("dept", "관리부"),
                "직급": emp_in.get("title", "사원"),
                "입사일": emp_in.get("hire_date", "2024-01-01"),
                "퇴사일": "",
                "입력기준": "세전",
                "목표실수령액": 0,
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
            }
            pstate.setdefault("employees", []).insert(0, new_emp)
        _recalculate_all_employee_rows(pstate)
        pstate["grid_version"] = int(pstate.get("grid_version", 0)) + 1
    except Exception:
        pass


def _sync_approved_todo_to_calendar(cstate: Dict[str, Any], todo_id: str) -> None:
    """60% To-Do 오버레이에서 승인완료 시 Python 세션 동기화 및 달력 선택일에 초록색 승인완료 배지 추가"""
    today_d = get_kst_today()
    yr = int(cstate.get("year", today_d.year))
    mo = int(cstate.get("month", today_d.month))
    sel_day = int(cstate.get("selected_day", today_d.day))
    ym_key = f"{yr:04d}-{mo:02d}"
    month_map = cstate.setdefault("schedules_by_ym", {}).setdefault(ym_key, {})
    day_list = month_map.setdefault(sel_day, [])

    todos = cstate.get("kakao_todos", [])
    targets = [
        t for t in todos
        if (todo_id == "ALL_READY" and (t.get("status_code") == "READY" or "승인요청" in str(t.get("status", ""))))
        or t.get("id") == todo_id
    ]
    for t in targets:
        t["status_code"] = "APPROVED"
        t["status"] = "사용자 승인완료"
        t["time_ago"] = "방금 승인됨"
        t["checked"] = True
        ev_id = f"done_{t.get('id')}"
        if not any(x.get("id") == ev_id for x in day_list):
            day_list.append({
                "id": ev_id,
                "type": "DONE",
                "time": datetime.now(ZoneInfo("Asia/Seoul")).strftime("%H:%M"),
                "title": f"{t.get('client', '')} {t.get('category', '카톡 승인완료')}".strip(),
                "client": t.get("client", "거래처"),
                "category": "승인완료",
                "ai_status": "사용자 승인완료",
                "done": True,
                "desc": str(t.get("title") or ""),
            })