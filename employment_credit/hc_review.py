# -*- coding: utf-8 -*-
"""
[모듈 4/4] 통합고용세액공제 — 12대 법령 · 심판례 · 절세누락 정밀 오류 검토 엔진 (hc_review.py)
- 2단계 [오류 검토] 모달 및 4단계 감사 리포트에서 사용하는 12대 세무·절세 정밀 진단 규칙을 전담합니다.
"""
from __future__ import annotations

from typing import Any

from . import rules as R
from .hc_eligibility import (
    NEW_TENURE_RULE_FROM,
    _get_month_pay,
    _has_any_pay_record,
    contract_age,
    parse_date,
    suggest_youth,
    tenure_under_1y,
)
from .hc_row_engine import (
    regular_excluding_part_time,
    year_totals,
)

# ══════════════════════════════════════════════════════════════════
# 6. 100% 성능 12대 법령 · 심판례 · 절세누락 정밀 오류 검토 엔진 (Review Dialog용)
# ══════════════════════════════════════════════════════════════════
def review(
    people: dict,
    year_recs: dict,
    years: list[int],
    ctx_by_year: dict,
    computed: dict,
    prev_filing: dict | None = None,
    sub_biz_list: list[dict] | None = None,
    **kwargs,
) -> list[tuple[str, str]]:
    """
    2단계 [🔍 오류 검토] 모달 및 4단계 감사 리포트에서 사용하는 12대 세무·절세 정밀 진단 엔진.
    반환 형식: [("오류" | "절세누락" | "확인", 상세 설명), ...]
    """
    items: list[tuple[str, str]] = []

    # 0) 복수 사업장(합산 사유) 설정에 따른 필수 입력값 누락 점검
    for idx, sb in enumerate(sub_biz_list or []):
        sb_nm = str(sb.get("상호") or f"제{idx+2}사업장").strip()
        sb_tp = str(sb.get("구분") or "").strip()
        if "기중양도" in sb_tp and not parse_date(sb.get("폐업일")):
            items.append(
                (
                    "오류",
                    f"[복수 사업장 · {sb_nm}] 합산 사유가 '{sb_tp}'으로 선택되었으나 '폐업·양도일'이 비어 있습니다. "
                    f"좌측 사이드바에서 양도일을 입력해야 양도월 이후 미도래 월 자동 산입이 차단됩니다.",
                )
            )
        if ("포괄양수" in sb_tp or "승계" in sb_tp) and float(sb.get("승계_직전상시", 0.0) or 0.0) <= 0:
            items.append(
                (
                    "확인",
                    f"[복수 사업장 · {sb_nm}] 합산 사유가 '{sb_tp}'으로 선택되었습니다. "
                    f"조특령 제26조의8 제10항에 따라 종전 사업장의 직전 과세연도 상시근로자 수를 좌측 사이드바에 합산 입력했는지 확인하세요.",
                )
            )

    for y in years:
        c_map = computed.get(y) or {}
        ctx = ctx_by_year.get(y) or {}
        n_months = ctx.get("months_in_year", 12)
        corp_size = ctx.get("corp_size") or "중소기업"
        rows = list(c_map.values())
        emp_types = [r.get("고용유형", R.EMP_REGULAR) for r in rows]

        # 1) 단시간(0.75 가중치) 적용 요건 검증 (조특령 제26조의8 제6항 단서)
        if any(et == R.EMP_PT_075 for et in emp_types):
            cur_ft = regular_excluding_part_time(rows, emp_types, n_months)
            if cur_ft < 0.75:
                items.append(
                    (
                        "오류",
                        f"[{y}년 · 단시간 0.75 요건 위반] 단시간 제외 상시근로자 수({cur_ft:.2f}명)가 최소 기준(0.75명) 미만이라 단시간 0.75명 가중치를 적용할 수 없습니다 (0.5명 적용 대상).",
                    )
                )
            prev_y = y - 1
            if prev_y in computed:
                prev_rows = list(computed[prev_y].values())
                prev_ets = [r.get("고용유형", R.EMP_REGULAR) for r in prev_rows]
                prev_ft = regular_excluding_part_time(
                    prev_rows, prev_ets, (ctx_by_year.get(prev_y) or {}).get("months_in_year", 12)
                )
                if cur_ft < prev_ft:
                    items.append(
                        (
                            "오류",
                            f"[{y}년 · 단시간 0.75 요건 위반] 통상근로자 상시근로자 수가 직전연도({prev_ft:.2f}명)보다 감소({cur_ft:.2f}명)하여 단시간 0.75 대신 0.5를 적용해야 합니다.",
                        )
                    )

        cohort_preserved_names: list[str] = []
        projected_names: list[str] = []
        hire_nopay_names: list[str] = []
        nopay_names: list[str] = []
        succession_names: list[str] = []
        transferred_out_names: list[str] = []
        absent_wht_names: list[str] = []

        for pid, c in c_map.items():
            p = people.get(pid) or {}
            nm = p.get("성명") or pid
            wp = (p.get("연도별_사업장명") or {}).get(str(y)) or p.get("사업장명") or ""
            nm_disp = f"{nm}({wp})" if wp and wp != "본점" else nm
            yrec = (year_recs.get(y) or {}).get(pid) or {}

            birth_dt = parse_date(p.get("생년월일"))
            hire_dt = parse_date(p.get("입사일"))
            ret_dt = parse_date((p.get("연도별_퇴사일") or {}).get(str(y)) or p.get("퇴사일"))
            mil_m = int(p.get("병역개월", 0) or 0)
            c_age = contract_age(p)
            pay_obj = (p.get("월급여") or {}).get(str(y))

            # 2) 입·퇴사일 역전 오류
            if hire_dt and ret_dt and ret_dt < hire_dt:
                items.append(
                    (
                        "오류",
                        f"[{y}년 · {nm_disp}] 퇴사일({ret_dt})이 입사일({hire_dt})보다 빠릅니다. 입·퇴사일을 정정하세요.",
                    )
                )

            # 3) 퇴사일 이후 월 급여 지급 여부 점검 (퇴직 후 성과급·정산금 vs 재입사)
            if ret_dt and _has_any_pay_record(pay_obj):
                if ret_dt.year == y and ret_dt.month < 12:
                    post_ret_months = [
                        m for m in range(ret_dt.month + 1, 13)
                        if (_get_month_pay(pay_obj, m) or 0.0) > 0
                    ]
                    if post_ret_months:
                        m_str = ", ".join(f"{m}월" for m in post_ret_months)
                        items.append(
                            (
                                "오류",
                                f"[{y}년 · {nm_disp}] 퇴사일({ret_dt}) 이후인 {m_str}에 급여 지급 내역이 존재합니다. "
                                f"중도 퇴사 후 재입사했거나 퇴사일 오기재라면 퇴사일을 수정하세요 (단순 퇴직 후 미지급금 정산이면 현재처럼 0 제외가 맞습니다).",
                            )
                        )
                elif ret_dt.year < y:
                    paid_m = [m for m in range(1, 13) if (_get_month_pay(pay_obj, m) or 0.0) > 0]
                    if paid_m:
                        items.append(
                            (
                                "오류",
                                f"[{y}년 · {nm_disp}] 과거 퇴사일({ret_dt}) 이후인 {y}년에 급여 지급 내역({len(paid_m)}개 월)이 있습니다. 재입사 여부를 확인하세요.",
                            )
                        )

            # 4) 1년 미만 단기 퇴사자가 상시='O'로 산입된 경우 경고 (조특령 §23⑩ 1호)
            if c["상시"] == "O" and hire_dt and ret_dt and tenure_under_1y(p, y):
                tenure_days = (ret_dt - hire_dt).days + 1
                items.append(
                    (
                        "확인",
                        (f"[{y}년 · {nm_disp}] 총 근로기간이 {tenure_days}일({hire_dt} ~ {ret_dt})로 1년 미만인데 상시근로자('O')로 산입되어 있습니다. "
                         f"2026년 이후 최초공제분은 계약기간과 무관하게 실제 근로기간 1년 미만이면 제외됩니다(조특령 제26조의8 제2항 제1호). 상시(O/X)를 확인하세요.")
                        if y >= NEW_TENURE_RULE_FROM else
                        (f"[{y}년 · {nm_disp}] 실제 근로기간이 {tenure_days}일({hire_dt} ~ {ret_dt})로 1년 미만이지만, {y}년 표는 종전 규정"
                         f"(근로계약기간 1년 미만만 제외, 대통령령 제35999호 부칙 제2조)이라 기간 정함 없는 계약으로 보아 포함했습니다. "
                         f"근로계약기간 자체가 1년 미만인 기간제였다면 제외사유를 '근로계약 1년미만'으로 바꾸세요."
                         + (f" 2026년 신규공제의 직전연도 비교에서는 개정 규정에 따라 제외됩니다." if y == NEW_TENURE_RULE_FROM - 1 else "")),
                    )
                )

            # 5) 필수 입사일·생년월일 누락 점검
            if c["상시"] == "O":
                if not hire_dt:
                    items.append(
                        (
                            "오류",
                            f"[{y}년 · {nm_disp}] 입사일이 비어 있습니다. 매월 말 재직 판정 및 청년등 연령 계산을 위해 입사일을 입력하세요.",
                        )
                    )
                if c["청년등"] in (R.YOUTH_YOUNG, R.YOUTH_SENIOR) and not birth_dt:
                    items.append(
                        (
                            "오류",
                            f"[{y}년 · {nm_disp}] 생년월일이 비어 있어 '{c['청년등']}' 연령 요건을 검증할 수 없습니다.",
                        )
                    )

            # 6) [절세누락 자동 탐지] 청년(15~34세) 또는 고령자(60세 이상) 요건 충족자 중 '해당없음(일반)'으로 설정된 경우
            if c["상시"] == "O" and c["청년등"] == R.YOUTH_NONE and c["row_sum"] > 0 and birth_dt and hire_dt:
                sug_y = suggest_youth(p, yrec, y, corp_size)
                if sug_y == R.YOUTH_SENIOR and c_age is not None and c_age >= R.SENIOR_AGE:
                    items.append(
                        (
                            "절세누락",
                            f"[{y}년 · {nm_disp}] 입사 당시 만 {c_age}세(60세 이상 고령자)로 『취업시 60세 이상』 우대공제 대상이나 현재 '해당없음(일반)'으로 설정되어 있습니다! "
                            f"'취업시 60세 이상'으로 변경하면 청년등 우대 공제단가가 적용됩니다.",
                        )
                    )
                elif sug_y == R.YOUTH_YOUNG and c_age is not None and (R.YOUTH_AGE_MIN <= c_age <= R.YOUTH_AGE_MAX):
                    items.append(
                        (
                            "절세누락",
                            f"[{y}년 · {nm_disp}] 입사 당시 만 {c_age}세로 {y}년 중 청년 요건(15~34세)을 충족하나 현재 '해당없음(일반)'으로 설정되어 있습니다! "
                            f"특별한 제외 사유가 없다면 『{R.YOUTH_YOUNG}』으로 변경하여 청년등 우대 공제단가를 적용받으세요.",
                        )
                    )

            # 7) 청년·고령자 연령 초과 오분류 및 병역이행(35~40세) 절세 후보 발굴
            if c["상시"] == "O" and c["청년등"] == R.YOUTH_SENIOR:
                if c_age is not None and c_age < R.SENIOR_AGE:
                    items.append(
                        (
                            "오류",
                            f"[{y}년 · {nm_disp}] 근로계약 체결일 기준 만 {c_age}세라 '취업시 60세 이상'에 해당하지 않습니다.",
                        )
                    )

            if c["상시"] == "O" and c["청년등"] == R.YOUTH_YOUNG:
                if c_age is not None and c_age > R.YOUTH_AGE_MAX and mil_m == 0:
                    if c_age <= R.YOUTH_AGE_MAX + 6:
                        items.append(
                            (
                                "확인",
                                f"[{y}년 · {nm_disp}] 입사 시 만 나이가 {c_age}세로 34세를 초과합니다. "
                                f"병역이행기간(최대 72개월)이 있다면 '병역(월)' 칸에 입력하여 청년 요건 충족 여부를 확인하세요.",
                            )
                        )
                    else:
                        items.append(
                            (
                                "오류",
                                f"[{y}년 · {nm_disp}] 입사 시 만 나이가 {c_age}세로 청년 연령(15~34세)을 초과합니다.",
                            )
                        )
            elif c["상시"] == "O" and c["청년등"] == R.YOUTH_NONE and c_age is not None and (35 <= c_age <= 40) and mil_m == 0:
                need_mil_years = c_age - R.YOUTH_AGE_MAX
                items.append(
                    (
                        "확인",
                        f"[{y}년 · {nm_disp} · 병역차감 후보] 입사 시 만 {c_age}세로 34세를 {need_mil_years}세 초과하여 일반근로자로 분류되었습니다. "
                        f"만약 군 복무 이력이 있다면 '병역(월)' 칸에 복무개월수(최대 72개월)를 입력 시 『취업시 청년』 우대공제 전환이 가능할 수 있습니다.",
                    )
                )

            if c["청년등"] == R.YOUTH_NK and y <= 2024:
                items.append(
                    (
                        "확인",
                        f"[{y}년 · {nm_disp}] 북한이탈주민은 2025.2.28 시행령 개정으로 2025년 귀속분부터 청년등 상시근로자에 포함됩니다.",
                    )
                )

            # 8) 단시간근로자(0.5/0.75) 월급여 급증(통상근로 전환 의심) 점검
            if c["상시"] == "O" and c["고용유형"] in (R.EMP_PT_050, R.EMP_PT_075) and _has_any_pay_record(pay_obj):
                pays = [(_get_month_pay(pay_obj, m) or 0.0) for m in range(1, 13) if (_get_month_pay(pay_obj, m) or 0.0) > 0]
                if pays and max(pays) >= 2_500_000 and min(pays) > 0 and (max(pays) / min(pays)) >= 1.6:
                    items.append(
                        (
                            "확인",
                            f"[{y}년 · {nm_disp}] 단시간근로자({c['고용유형']})로 설정되어 있으나 기중 월급여가 {min(pays):,.0f}원 → {max(pays):,.0f}원으로 크게 증가했습니다. "
                            f"기중에 통상근로자(주 40시간)로 전환되었다면 고용유형 및 가중치(1.0) 반영 여부를 확인하세요.",
                        )
                    )

            # 9) 복수 사업장 전출입 합산 안내
            if "→" in wp:
                items.append(
                    (
                        "확인",
                        f"[{y}년 · {nm_disp}] 복수 사업장 간 이동·승계({wp})가 감지되어 월별 급여 및 재직기간을 합산 반영했습니다 (조특령 제26조의8 제10항).",
                    )
                )

            # 10) 입사월 무급(익월지급) vs 기중 무급휴직 연도별 그룹화 수집 (오류검토 창이 한 화면에 들어오도록 요약)
            if c.get("hire_month_nopay"):
                raw_ms = c["hire_month_nopay"]
                ms = [raw_ms] if isinstance(raw_ms, int) else list(raw_ms)
                m_str = f"{ms[0]}월" if len(ms) == 1 else f"{min(ms)}~{max(ms)}월"
                hire_nopay_names.append(f"{nm_disp}({m_str})")
            if c.get("no_pay_months"):
                raw_ms = c["no_pay_months"]
                ms = [raw_ms] if isinstance(raw_ms, int) else list(raw_ms)
                m_str = f"{ms[0]}월" if len(ms) == 1 else (f"{min(ms)}~{max(ms)}월" if ms == list(range(min(ms), max(ms) + 1)) else ",".join(f"{m}월" for m in ms))
                nopay_names.append(f"{nm_disp}({m_str})")

            if c.get("projected_months"):
                projected_names.append(f"{nm_disp}({min(c['projected_months'])}~{max(c['projected_months'])}월)")

            # 11) 청년 연령 도과자 사후관리/연속공제 청년 간주(조특령 §26의8⑤) 자동 보호 내역 수집
            if c["상시"] == "O" and (c.get("b2_yth", 0) > c.get("b1_yth", 0) or c.get("b3_yth", 0) > c.get("b1_yth", 0)):
                cohort_preserved_names.append(
                    f"{nm_disp}(당해 청년 {c['b1_yth']:.2f} → 1차사후 {c['b2_yth']:.2f} / 2차사후 {c['b3_yth']:.2f})"
                )

            # 승계·양도·미등재 처리 안내 (연도별 그룹화 수집)
            if c.get("succession_months"):
                succession_names.append(f"{nm_disp}({len(c['succession_months'])}개월)")
            if c.get("transferred_out"):
                transferred_out_names.append(nm_disp)
            if c.get("absent_in_wht"):
                absent_wht_names.append(nm_disp)

            if p.get("외국인") and c.get("상시") == "O":
                items.append(("확인", f"[{y}년 · {nm_disp}] 원천징수부에 '외국인'으로 표시되어 있습니다. 상시근로자의 내국인은 국적과 무관하게 "
                                     f"국내에 주소를 두거나 183일 이상 거소를 둔 사람이므로 포함했습니다. 비거주자라면 제외사유를 '외국인 근로자'로 바꾸세요."))

            # 12) 수동 오버라이드 감사 추적
            if yrec.get("상시_override"):
                items.append(
                    (
                        "확인",
                        f"[{y}년 · {nm_disp}] 상시 여부가 자동판정({c['상시_auto']})에서 '{c['상시']}'로 수동 변경되었습니다.",
                    )
                )
            if yrec.get("월_override"):
                ovr_m_keys = sorted(int(k) for k in (yrec.get("월_override") or {}).keys() if str(k).isdigit())
                if ovr_m_keys:
                    items.append(
                        (
                            "확인",
                            f"[{y}년 · {nm_disp}] {', '.join(f'{m}월' for m in ovr_m_keys)} 상시근로자 수치가 수동 입력(오버라이드)되었습니다.",
                        )
                    )

        if cohort_preserved_names:
            items.append(
                (
                    "확인",
                    f"[{y}년 · 사후관리 청년 간주 자동적용] {', '.join(cohort_preserved_names)}: "
                    f"당해 세액공제(3번 블록)에서는 청년등이 아니지만(나이·인정기간 경과 또는 단시간·기간제 등), "
                    f"최초공제연도에 청년등이었으므로 조특령 제26조의8 제5항에 따라 1·2차 사후관리(4·5번 블록)에서는 '청년등'으로 유지했습니다.",
                )
            )

        if hire_nopay_names:
            items.append(
                (
                    "확인",
                    f"[{y}년 · 입사월 급여 0원 익월지급 산입({len(hire_nopay_names)}명)] {', '.join(hire_nopay_names[:8])}{' 외 ' + str(len(hire_nopay_names) - 8) + '명' if len(hire_nopay_names) > 8 else ''}: "
                    f"입사월 급여가 0원이나 익월 지급 관행을 고려해 재직(산입)으로 두고 살구색으로 표시했습니다 (미근무 시 0으로 수정하거나 상단 체크 해제).",
                )
            )

        if nopay_names:
            items.append(
                (
                    "확인",
                    f"[{y}년 · 재직 중 급여 0원 월 자동 제외({len(nopay_names)}명)] {', '.join(nopay_names[:8])}{' 외 ' + str(len(nopay_names) - 8) + '명' if len(nopay_names) > 8 else ''}: "
                    f"재직기간 중 급여가 없는 달(살구색 표시)은 상시근로자에서 자동 제외(0)되었습니다 (육아휴직·무급휴직 여부 확인).",
                )
            )

        if succession_names:
            items.append(
                (
                    "확인",
                    f"[{y}년 · 포괄양수·승계 개시일 산입({len(succession_names)}명)] {', '.join(succession_names[:8])}{' 외 ' + str(len(succession_names) - 8) + '명' if len(succession_names) > 8 else ''}: "
                    f"포괄양수·승계 근로자로 승계일 이전 기간을 과세연도 개시일 승계 의제로 산입했습니다 (조특령 제23조 제13항 준용).",
                )
            )

        if transferred_out_names:
            items.append(
                (
                    "확인",
                    f"[{y}년 · 기중양도(고용승계) 제외·직전연도 차감({len(transferred_out_names)}명)] {', '.join(transferred_out_names[:8])}{' 외 ' + str(len(transferred_out_names) - 8) + '명' if len(transferred_out_names) > 8 else ''}: "
                    f"기중양도 사업장 근로자로 개시일에 승계시킨 것으로 보아 {y}년 인원에서 제외하고 직전연도 인원에서도 차감했습니다 (조특령 제23조 제13항 준용).",
                )
            )

        if absent_wht_names:
            items.append(
                (
                    "확인",
                    f"[{y}년 · 원천징수부 미등재 0 처리({len(absent_wht_names)}명)] {', '.join(absent_wht_names[:8])}{' 외 ' + str(len(absent_wht_names) - 8) + '명' if len(absent_wht_names) > 8 else ''}: "
                    f"{y}년 원천징수부에 없는 사람이라 {y}년에는 근무하지 않은 것으로 보아 0으로 처리했습니다 (실제 근무 시 월별 칸 직접 입력).",
                )
            )

        if projected_names:
            items.append(
                (
                    "확인",
                    f"[{y}년 · 기중 가결산 연말재직 가정({len(projected_names)}명)] {', '.join(projected_names[:6])}{' 외 ' + str(len(projected_names) - 6) + '명' if len(projected_names) > 6 else ''}의 "
                    f"미도래 월이 하늘색 셀('연말까지 재직 가정')로 자동 산입되었습니다.",
                )
            )

    # 13) 기신고 내역 vs 세법원칙 재계산 수치 대조
    if prev_filing and isinstance(prev_filing, dict):
        for y_str, pdata in prev_filing.items():
            try:
                yi = int(y_str)
            except (TypeError, ValueError):
                continue
            if yi in computed and isinstance(pdata, dict):
                tot = year_totals(list(computed[yi].values()), (ctx_by_year.get(yi) or {}).get("months_in_year", 12), year=yi)
                prev_reg = pdata.get("상시")
                prev_yth = pdata.get("청년등")
                if prev_reg is not None and abs(float(prev_reg) - tot["상시_평균"]) >= 0.01:
                    items.append(
                        (
                            "확인",
                            f"[{yi}년 기신고 대조] 기신고 상시근로자 수({float(prev_reg):.2f}명)와 "
                            f"세법원칙 재계산 상시근로자 수({tot['상시_평균']:.2f}명)가 {abs(float(prev_reg) - tot['상시_평균']):.2f}명 차이납니다. "
                            f"3단계 우측 상단에서 '기신고 기준(원칙)'과 '세법원칙 기준(경정청구·수정신고용)'을 선택하여 비교할 수 있습니다.",
                        )
                    )
                if prev_yth is not None and abs(float(prev_yth) - tot["청년등_평균"]) >= 0.01:
                    items.append(
                        (
                            "확인",
                            f"[{yi}년 기신고 대조] 기신고 청년등 상시근로자 수({float(prev_yth):.2f}명)와 "
                            f"세법원칙 재계산 청년등 상시근로자 수({tot['청년등_평균']:.2f}명)가 {abs(float(prev_yth) - tot['청년등_평균']):.2f}명 차이납니다.",
                        )
                    )

    # 중요도 순 정렬: 오류 -> 절세누락 -> 확인
    priority = {"오류": 0, "절세누락": 1, "확인": 2}
    items.sort(key=lambda x: priority.get(x[0], 9))
    return items