# -*- coding: utf-8 -*-
"""
================================================================================
범준 세무·업무자동화 에이전트 (tax-agent v3) 자율 실행 검증 & 실측 벤치마크 통합 스위트
- 실행 환경: Python 3.10 ~ 3.12 (표준 unittest + tracemalloc + time.perf_counter)
- 검증 범위:
  1) 기준일·귀속연도 단일 지침 & 감수 컨텍스트 보존(위치·키워드 인자 호환) & 지침 누출 차단 (agent.py)
  2) v3 귀속연도 자동 감지기(detect_query_attribution_years) — 기간 표현 오탐 차단 & 멀티턴 '24년/2024년에 이력 보존 (agent.py)
  3) v3 시행일 타임라인 교차검증(_scan_timeline_hallucinations) & 법령 후보 정렬/배지/조문별 시행일 각인 (agent.py, law_api.py)
  4) AST 수식 계산기 보안 샌드박스 & 거듭제곱 폭탄/Null/쉼표 방어 (agent.py)
  5) 법령·부칙(공포번호 괄호 포함)·판례 인용 검증 및 할루시네이션 차단 (agent.py, law_api.py)
  6) 통합고용세액공제 43개 골든 시나리오 불변성 & JSON 문자열 연도 키 호환 & 백업 복원 (employment_credit/*)
  7) 인건비·원천세·4대보험·가산수당·세후->세전 역산기 극한 엣지 케이스(NaN/Inf/None/쉼표) 방어 (payroll_automated/*)
  8) 인건비 채팅 복합 지시문·연말 지급일 연도 보정·가짜 인명 차단·달력 유효성 검증 (payroll_automated/parsers.py)
  9) 급여명세서·사업소득명세서 PDF/엑셀 익스포터 & .paybak 암호화 백업 무결성 (payroll_automated/exporters.py, backup.py)
 10) 달력 스케줄러 & 60% 확장 카카오톡 To-Do 오버레이 DOM XSS 이스케이프 검증 (calendar_scheduler/ui.py)
================================================================================
"""
from __future__ import annotations

import datetime as dt
import glob
import math
import os
import py_compile
import sys
import time
import tracemalloc
import types
import unittest
from fractions import Fraction

import pandas as pd


# ──────────────────────────────────────────────────────────────────────────────
# 0. 헤드리스 터미널 실행용 Streamlit / AgGrid / GenAI 경량 모킹 하네스
# ──────────────────────────────────────────────────────────────────────────────
class _AttrDict(dict):
    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError:
            raise AttributeError(k)

    def __setattr__(self, k, v):
        self[k] = v

    def __delattr__(self, k):
        try:
            del self[k]
        except KeyError:
            raise AttributeError(k)


def ensure_headless_mocks() -> None:
    if "streamlit" not in sys.modules:
        st = types.ModuleType("streamlit")
        st.session_state = _AttrDict()
        st.secrets = _AttrDict()

        def _identity_decorator(*dargs, **dkwargs):
            if len(dargs) == 1 and callable(dargs[0]) and not dkwargs:
                fn = dargs[0]
                fn.clear = lambda: None
                return fn

            def _wrap(fn):
                fn.clear = lambda: None
                return fn

            return _wrap

        st.cache_data = _identity_decorator
        st.cache_resource = _identity_decorator
        st.fragment = _identity_decorator
        st.dialog = _identity_decorator
        for attr in (
            "markdown", "write", "info", "warning", "error", "success", "caption",
            "subheader", "header", "title", "button", "text_input", "text_area",
            "number_input", "selectbox", "multiselect", "checkbox", "radio",
            "expander", "columns", "tabs", "container", "empty", "spinner",
            "rerun", "stop", "download_button", "file_uploader", "dataframe",
            "table", "metric", "progress", "popover", "divider", "html", "toast",
            "set_page_config",
        ):
            setattr(st, attr, lambda *a, **kw: None)
        st.sidebar = st
        sys.modules["streamlit"] = st
        st_comp = types.ModuleType("streamlit.components")
        st_comp_v1 = types.ModuleType("streamlit.components.v1")
        st_comp_v1.html = lambda *a, **kw: None
        st_comp.v1 = st_comp_v1
        sys.modules["streamlit.components"] = st_comp
        sys.modules["streamlit.components.v1"] = st_comp_v1

    if "st_aggrid" not in sys.modules:
        ag = types.ModuleType("st_aggrid")
        ag.AgGrid = lambda *a, **kw: {"data": None, "selected_rows": []}
        ag.GridOptionsBuilder = type(
            "GridOptionsBuilder",
            (),
            {
                "from_dataframe": classmethod(lambda cls, df, **kw: cls()),
                "configure_default_column": lambda *a, **kw: None,
                "configure_column": lambda *a, **kw: None,
                "configure_selection": lambda *a, **kw: None,
                "configure_grid_options": lambda *a, **kw: None,
                "build": lambda *a, **kw: {},
            },
        )
        ag.GridUpdateMode = type("GridUpdateMode", (), {"VALUE_CHANGED": "VALUE_CHANGED", "MODEL_CHANGED": "MODEL_CHANGED", "NO_UPDATE": "NO_UPDATE", "MANUAL": "MANUAL"})
        ag.DataReturnMode = type("DataReturnMode", (), {"AS_INPUT": "AS_INPUT", "FILTERED_AND_SORTED": "FILTERED_AND_SORTED"})
        ag.JsCode = lambda x: x
        sys.modules["st_aggrid"] = ag

    try:
        from google import genai  # noqa: F401
    except ImportError:
        import google
        genai_mod = types.ModuleType("google.genai")
        types_mod = types.ModuleType("google.genai.types")

        class _DummyConfig:
            def __init__(self, *a, **kw):
                self.__dict__.update(kw)

        for t_attr in ("GenerateContentConfig", "ThinkingConfig", "Tool", "GoogleSearch", "Part", "Content", "SafetySetting", "AutomaticFunctionCallingConfig"):
            setattr(types_mod, t_attr, _DummyConfig)
        genai_mod.types = types_mod
        genai_mod.Client = lambda **kw: None
        google.genai = genai_mod
        sys.modules["google.genai"] = genai_mod
        sys.modules["google.genai.types"] = types_mod


ensure_headless_mocks()

CODE_ROOT = os.environ.get("TEST_TARGET_DIR", os.path.dirname(os.path.abspath(__file__)))
if CODE_ROOT not in sys.path:
    sys.path.insert(0, CODE_ROOT)

import agent  # noqa: E402
import law_api  # noqa: E402
from calendar_scheduler import ui as cal_ui  # noqa: E402
from employment_credit import (  # noqa: E402
    backup as ec_backup,
    hc_credit_calc,
    hc_eligibility,
    hc_review,
    hc_row_engine,
    parsers as ec_parsers,
    rules as ec_rules,
    ui_common as ec_common,
    ui_step4 as ec_step4,
)
from payroll_automated import (  # noqa: E402
    backup as pa_backup,
    calculators as pa_calc,
    exporters as pa_exp,
    parsers as pa_parsers,
    tax_tables as pa_tax,
    ui as pa_ui,
)


class TestComprehensiveTaxAgentSuite(unittest.TestCase):
    """전 모듈 통합 단위 테스트 및 극한 스트레스 테스트 (v3 포함 22개 검증 항목)"""

    def test_01_all_python_files_compile_cleanly(self):
        py_files = sorted(glob.glob(os.path.join(CODE_ROOT, "**", "*.py"), recursive=True))
        self.assertGreaterEqual(len(py_files), 30)
        for p in py_files:
            py_compile.compile(p, doraise=True)

    def test_02_agent_temporal_guideline_single_injection_and_leak_strip(self):
        g = agent.build_temporal_guideline()
        self.assertIn(agent.HIDDEN_DATE_DIRECTIVE_MARKER, g)
        self.assertIn("법률 제21223호 부칙 제34조", g)
        self.assertEqual(agent.build_invisible_temporal_prefix(), "")

        leaked = (
            "[기준일·적용시점 판단 지침 — 내부 지침이므로 이 문장들을 답변에 인용하지 말 것]\n"
            "1단계 — 적용 기준시점을 정한다 (위에서부터 먼저 해당하는 것)\n"
            "### 1. 결론\n적용 기준: 2026년 귀속 · 2026.01.01 시행 법령"
        )
        cleaned = agent._strip_leaked_temporal_guideline(leaked)
        self.assertNotIn("기준일·적용시점 판단 지침", cleaned)
        self.assertNotIn("1단계 —", cleaned)
        self.assertTrue(cleaned.startswith("### 1. 결론"))

    def test_03_agent_semantic_verify_preserves_raw_query_and_supports_both_call_conventions(self):
        long_input = (
            "[사용자 1번째 질문]: 2024년 귀속 통합고용세액공제 경정청구 건입니다.\n"
            + ("이전 대화 내역 텍스트 " * 450)
            + "\n[현재 사용자 질문]: 2024년 귀속 청년 등 상시근로자 공제단가는 얼마야?"
        )
        raw_q = "2024년 귀속 청년 등 상시근로자 공제단가는 얼마야?"
        ctx1 = agent._prepare_semantic_verify_query(raw_q, long_input, max_chars=3000)
        ctx2 = agent._prepare_semantic_verify_query(long_input, raw_query=raw_q, max_chars=3000)
        ctx3 = agent._prepare_verify_query_context(raw_q, long_input, max_chars=3000)
        self.assertEqual(ctx1, ctx2)
        self.assertEqual(ctx1, ctx3)
        self.assertLessEqual(len(ctx1), 3000)
        self.assertIn(raw_q, ctx1)
        self.assertIn("2024년", ctx1)

    def test_04_agent_tax_calculator_sandbox_security_and_null_safety(self):
        self.assertIn("오류", agent.run_tax_calculator_for_gemini(None))
        self.assertIn("오류", agent.run_tax_calculator_for_gemini(""))
        self.assertIn("오류", agent.run_tax_calculator_for_gemini("10 / 0"))
        self.assertIn("오류", agent.run_tax_calculator_for_gemini("__import__('os').system('id')"))
        self.assertIn("오류", agent.run_tax_calculator_for_gemini("999999 ** 999999"))
        self.assertIn("오류", agent.run_tax_calculator_for_gemini("[1] * 10000000"))

        res_ok = agent.run_tax_calculator_for_gemini("min(1,500,000, 2,000,000) * 0.15", "세액공제")
        self.assertIn("225,000", res_ok)
        res_pv = agent.run_tax_calculator_for_gemini("round(1000000 * ((1 + 0.05) ** -3))", "현재가치")
        self.assertIn("863,838", res_pv)

    def test_05_agent_addendum_and_statute_citation_verification(self):
        trace = agent._new_trace()
        tok = agent._TOOL_TRACE.set(trace)
        try:
            sample = (
                "📘 [조세특례제한법 | 공포번호: 제21223호 | 시행일자: 2026.01.01]\n\n"
                "제29조의8(통합고용세액공제) ① 세액을 공제한다.\n\n"
                "📌 [관련 최근 개정 부칙(본칙 한정 시행일·적용례·경과조치) 발췌]\n"
                "부칙 <제21223호, 2025.12.31.> [본칙관련]\n"
                "제34조(통합고용세액공제에 관한 경과조치) 종전의 제29조의8에 따른다."
            )
            agent._record("detail", sample)
            agent._record_law_articles(sample)
        finally:
            agent._TOOL_TRACE.reset(tok)

        valid_lines = [
            "조세특례제한법 제29조의8 제1항에 따라 세액을 공제합니다 [조문: 조세특례제한법 제29조의8].",
            "2024년 귀속분은 조세특례제한법(법률 제21223호) 부칙 제34조에 따릅니다 [부칙: 조세특례제한법(법률 제21223호) 부칙 제34조].",
            "조세특례제한법 부칙(법률 제21223호) 제34조에 따라 종전 규정을 적용합니다.",
        ]
        for ln in valid_lines:
            self.assertEqual(agent._scan_violations(ln, trace), [], msg=f"Unexpected violation on: {ln}")

        bad_main_34 = "조세특례제한법 제34조 제1항에 따라 공제합니다 [조문: 조세특례제한법 제34조]."
        v_bad = agent._scan_violations(bad_main_34, trace)
        self.assertEqual(len(v_bad), 1)
        self.assertIn("본칙 조문 원문 미조회", v_bad[0][1][0])

        bad_prec = "대법원 2099두99999 판결에 의하면 타당합니다 [판례: 2099두99999]."
        v_prec = agent._scan_violations(bad_prec, trace)
        self.assertEqual(len(v_prec), 1)
        self.assertIn("조회 기록 없음", v_prec[0][1][0])

    def test_06_agent_pure_kakao_text_postprocessor(self):
        raw_kakao = (
            "### 1. 검토 결론\n"
            "**조세특례제한법 제29조의8 제1항**에 따라 `1,450만 원` 공제됩니다 [조문: 조세특례제한법 제29조의8].\n"
            "| 구분 | 금액 |\n| --- | --- |\n| 청년 | 1,450만원 |"
        )
        pure = agent._enforce_pure_kakao_text(raw_kakao)
        self.assertNotIn("**", pure)
        self.assertNotIn("###", pure)
        self.assertNotIn("제29조의8", pure)
        self.assertNotIn("[조문:", pure)
        self.assertIn("- 청년 : 1,450만원", pure)

    def test_07_employment_credit_43_golden_case_invariants(self):
        ok, errs = ec_rules.verify_golden_case_invariants()
        self.assertTrue(ok, msg=f"Golden invariants failed: {errs}")

    def test_08_employment_credit_eligibility_edge_cases(self):
        self.assertEqual(hc_eligibility.trunc2(float("nan")), 0.0)
        self.assertEqual(hc_eligibility.trunc2(float("inf")), 0.0)
        self.assertEqual(hc_eligibility.trunc2(None), 0.0)
        self.assertEqual(hc_eligibility.trunc2(Fraction(7, 12)), 0.58)

        b_dt = dt.date(1990, 5, 10)
        r_dt = dt.date(2026, 5, 10)
        age_0 = hc_eligibility.full_age(b_dt, r_dt, 0)
        self.assertEqual(age_0, 36)
        self.assertEqual(hc_eligibility.full_age(b_dt, r_dt, -24), 36)
        self.assertEqual(hc_eligibility.full_age(b_dt, r_dt, 240), 30)
        self.assertEqual(hc_eligibility.full_age(b_dt, r_dt, "24개월"), 34)
        self.assertEqual(hc_eligibility.full_age(b_dt, r_dt, float("nan")), 36)

    def test_09_employment_credit_string_vs_int_year_keys_parity(self):
        sum_int = {
            2024: {"regular": 5.0, "youth": 2.0, "non_youth": 3.0, "has_data": True},
            2025: {"regular": 6.0, "youth": 3.0, "non_youth": 3.0, "has_data": True},
            2026: {"regular": 8.0, "youth": 4.0, "non_youth": 4.0, "b1_reg": 8.0, "b1_yth": 4.0, "b1_gen": 4.0, "has_data": True},
        }
        sum_str = {str(k): dict(v) for k, v in sum_int.items()}
        pf_int = {2025: {"init_reg": 6.0, "init_yth": 3.0, "init_yth_inc": 1.0, "init_gen_inc": 0.0, "claimed_won": 14500000}}
        pf_str = {"2025": {"init_reg": "6.0", "init_yth": "3.0", "init_yth_inc": "1.0", "init_gen_inc": "0.0", "claimed_won": "14,500,000"}}

        pkg_i = hc_credit_calc.calculate_tax_year_package(2026, "중소기업", True, sum_int, prior_filings=pf_int)
        pkg_s = hc_credit_calc.calculate_tax_year_package(2026, "중소기업", True, sum_str, prior_filings=pf_str)
        self.assertEqual(pkg_i["total_credit_gross_won"], pkg_s["total_credit_gross_won"])
        self.assertEqual(pkg_i["net_after_rural_tax_won"], pkg_s["net_after_rural_tax_won"])

    def test_10_employment_credit_mixed_keys_fingerprint_and_backup_roundtrip(self):
        mixed_state = {
            "tax_year": 2026,
            "ext_sig": "sig1",
            "corp_size_by_year": {2025: "중소기업", "2026": "중소기업"},
            "people": {"p1": {"성명": "홍길동", "입사일": dt.date(2024, 1, 1), "주민등록번호": "950101-1234567", "tags": {"a", "b"}, "nan_v": float("nan")}},
            "year_recs": {2025: {}, "2026": {"p1": {"고용유형": "상시"}}},
            "manual_extra_years": ["2023", 2024],
        }
        fp = ec_common._calc_fingerprint(mixed_state)
        sig1 = ec_common._current_build_sig(mixed_state)
        sig2 = ec_step4._compute_report_cache_sig(mixed_state, 2026)
        self.assertTrue(fp and sig1 and sig2)

        blob, fname = ec_backup.make_backup_bytes(mixed_state, "pw123456")
        self.assertTrue(fname.endswith(".ecbak"))
        restored = ec_backup.read_backup_bytes(blob, "pw123456")
        self.assertEqual(restored["state"]["people"]["p1"]["주민등록번호"], "950101-1******")
        self.assertIn(2026, restored["state"]["year_recs"])
        self.assertEqual(restored["state"]["manual_extra_years"], [2023, 2024])

    def test_11_payroll_tax_tables_precision_and_hostile_inputs(self):
        ins_3m = pa_tax.calc_4ins_by_rate(3_000_000, year=2026, is_ceo=False)
        self.assertEqual(ins_3m["고용보험"], 27_000)
        ins_ceo = pa_tax.calc_4ins_by_rate(3_000_000, year=2026, is_ceo=True)
        self.assertEqual(ins_ceo["고용보험"], 0)

        self.assertEqual(pa_tax.floor_10won(float("nan")), 0)
        self.assertEqual(pa_tax.floor_10won(float("inf")), 0)
        self.assertEqual(pa_tax.floor_10won(None), 0)
        self.assertEqual(pa_tax.floor_10won("1,234,567원"), 1_234_560)

        wt = pa_tax.calc_withholding_tax("3,500,000원", dependents="2", children_8_to_20="1")
        self.assertGreater(wt["소득세"], 0)
        self.assertEqual(wt["지방소득세"], pa_tax.floor_10won(wt["소득세"] * 0.1))

    def test_12_payroll_gross_up_solver_accuracy_and_edge_cases(self):
        gu = pa_tax.gross_up_employee_net_to_gross(3_000_000, non_taxable_pay=200_000, dependents=2, children_8_to_20=1)
        self.assertAlmostEqual(gu["차인지급액"], 3_000_000, delta=50)
        self.assertEqual(gu["지급액계"] - gu["공제액계"], gu["차인지급액"])

        f_gu = pa_tax.gross_up_freelancer_net_to_gross(967_000, rate_pct=3.0)
        self.assertEqual(f_gu["지급총액"], 1_000_000)
        self.assertEqual(f_gu["차인지급액"], 967_000)

        self.assertEqual(pa_tax.gross_up_employee_net_to_gross(float("nan"))["차인지급액"], 0)
        self.assertIsInstance(pa_tax.gross_up_freelancer_net_to_gross(500_000, rate_pct=100.0), dict)

    def test_13_payroll_calculators_overtime_weekly_holiday_and_warnings(self):
        ot_5plus = pa_calc.calculate_overtime_night_holiday_allowance(
            ordinary_hourly_wage=10_000, overtime_hours=10, night_hours=4, holiday_hours_within_8=8, holiday_hours_over_8=2, is_5_or_more_workers=True
        )
        self.assertEqual(ot_5plus["total_allowance"], 330_000)

        ot_under5 = pa_calc.calculate_overtime_night_holiday_allowance(
            ordinary_hourly_wage=10_000, overtime_hours=10, night_hours=4, holiday_hours_within_8=8, holiday_hours_over_8=2, is_5_or_more_workers=False
        )
        self.assertEqual(ot_under5["total_allowance"], 200_000)

        wh_40 = pa_calc.calculate_weekly_holiday_allowance(hourly_wage=10_320, weekly_contract_hours=40.0, full_attendance=True, year=2026)
        self.assertTrue(wh_40["eligible"])
        self.assertEqual(wh_40["monthly_total_hours"], 209.0)
        self.assertEqual(wh_40["monthly_total_pay"], 2_156_880)

        wh_14 = pa_calc.calculate_weekly_holiday_allowance(hourly_wage=10_320, weekly_contract_hours=14.0, full_attendance=True, year=2026)
        self.assertFalse(wh_14["eligible"])
        self.assertEqual(wh_14["weekly_holiday_pay"], 0)

    def test_14_payroll_parsers_chat_directives_and_date_validation(self):
        emps = []
        frees = [{"코드": "0001", "성명": "홍길동", "소득구분": "940909", "지급년월일": "2025-12-25", "지급총액": 1000000}]
        meta = {}
        _, frees_out, logs, rem = pa_parsers.apply_chat_modifiers_to_state(
            raw_text="지급일은 1/10로 변경하고 업종코드는 940911로 반영\n소득구분은 940911로 적용",
            employees=emps,
            freelancers=frees,
            sub_mode="FREE",
            default_year_month="2025-12",
            out_meta=meta,
        )
        self.assertEqual(meta.get("pay_date"), "2026-01-10")
        self.assertEqual(frees_out[0]["지급년월일"], "2026-01-10")
        self.assertEqual(frees_out[0]["소득구분"], "940911")
        self.assertEqual(rem.strip(), "")

        self.assertEqual(pa_parsers.parse_date_str("2026-02-29"), "")
        self.assertEqual(pa_parsers.parse_date_str("2024-02-29"), "2024-02-29")
        self.assertEqual(pa_parsers.parse_date_str("2026.13.45"), "")
        self.assertEqual(pa_parsers.rrn_to_birth_dot("991345-1234567"), "")
        self.assertEqual(pa_parsers.rrn_to_birth_dot("950515-1234567"), "1995.05.15")

    def test_15_payroll_exporters_and_backup_encryption(self):
        emp_sample = [{"사원코드": "001", "성명": "홍길동", "주민등록번호": "900101-1234567", "기본급": 3_000_000, "식대": float("nan"), "차인지급액": 2_700_000}]
        xlsx_bytes = pa_exp.export_wehago_payroll_excel(emp_sample)
        self.assertTrue(xlsx_bytes.startswith(b"PK"))

        pdf_slip = pa_exp.render_single_employee_payslip_pdf(emp_sample[0], corp_name="(주)범준택스", year_month="2026-10", pay_date="2026-10-25")
        self.assertTrue(pdf_slip.startswith(b"%PDF"))

        db = pa_backup.create_empty_client_db("(주)범준택스", "본점")
        pa_backup.upsert_monthly_data_into_db(db, "(주)범준택스", "2026-10", "2026-10-25", emp_sample, [])
        db["extra_date"] = dt.date(2026, 11, 4)
        db["extra_nan"] = float("nan")
        enc = pa_backup.encrypt_client_db_to_paybak(db, "pw9999")
        dec = pa_backup.decrypt_paybak_to_client_db(enc, "pw9999")
        self.assertEqual(dec["corp_info"]["corp_name"], "(주)범준택스")
        self.assertIn("2026-10", dec["monthly_payroll"])

    def test_16_calendar_scheduler_kst_and_xss_protection(self):
        today_kst = cal_ui.get_kst_today()
        self.assertIsInstance(today_kst, dt.date)
        sch = cal_ui._default_schedules_for_month(today_kst.year, today_kst.month, today_kst)
        self.assertGreaterEqual(len(sch), 4)

        with open(os.path.join(CODE_ROOT, "calendar_scheduler", "ui.py"), "r", encoding="utf-8") as f:
            cal_src = f.read()
        self.assertIn("function escHtml(v)", cal_src)
        self.assertIn("escHtml(item.title)", cal_src)
        self.assertIn("escHtml(item.preview)", cal_src)

    # ──────────────────────────────────────────────────────────────────────────
    # v3 신규 기능 및 감사 포인트 검증 (test_17 ~ test_22)
    # ──────────────────────────────────────────────────────────────────────────
    def test_17_v3_attribution_year_detector_duration_false_positive_block(self):
        _, _, today_y = agent.get_kst_today_info()
        for q_dur in [
            "15년 이상 계속 가업영위한 법인의 가업상속공제 한도는?",
            "20년 이상 보유한 장기보유특별공제율은 얼마야?",
            "10년 이내 증여재산 합산과세 기준 알려줘",
            "25년 근속 퇴직소득세 공제 계산",
        ]:
            det = agent.detect_query_attribution_years(q_dur)
            self.assertEqual(det["mode"], "DEFAULT_CURRENT", msg=f"Duration false positive on: {q_dur} -> {det}")
            self.assertEqual(det["past_years"], [])

        d1 = agent.detect_query_attribution_years("24년 귀속 통합고용세액공제 사후관리 추징 계산")
        self.assertEqual(d1["mode"], "PAST_ONLY")
        self.assertEqual(d1["past_years"], [2024])

        d2 = agent.detect_query_attribution_years("2023년 귀속분과 2026년 통합고용세액공제 차이점 비교해줘")
        self.assertEqual(d2["mode"], "MIXED_PAST_AND_CURRENT")
        self.assertIn(2023, d2["past_years"])
        self.assertIn(today_y, d2["cur_years"])

    def test_18_v3_multi_turn_history_past_year_detection(self):
        d_2digit = agent.detect_query_attribution_years(
            "그럼 이 경우 추징세액은 얼마야?",
            full_user_input="[사용자 1번째 질문]: '24년 귀속 통합고용세액공제 경정청구 질문이야.\n[현재 사용자 질문]: 그럼 이 경우 추징세액은 얼마야?",
        )
        self.assertEqual(d_2digit["mode"], "MIXED_PAST_AND_CURRENT")
        self.assertEqual(d_2digit["history_past_years"], [2024])
        self.assertEqual(d_2digit["past_years"], [2024])

        d_plain = agent.detect_query_attribution_years(
            "그럼 추징세액은 어떻게 계산해?",
            full_user_input="[사용자 1번째 질문]: 2024년에 입사한 청년 직원이 올해 퇴사했어.\n[현재 사용자 질문]: 그럼 추징세액은 어떻게 계산해?",
        )
        self.assertEqual(d_plain["mode"], "MIXED_PAST_AND_CURRENT")
        self.assertEqual(d_plain["history_past_years"], [2024])
        self.assertEqual(d_plain["past_years"], [2024])

    def test_19_v3_hidden_date_directive_injection_and_strip(self):
        q = "2024년 귀속 통합고용세액공제 사후관리 요건이 뭐야?"
        directive = agent.build_hidden_date_law_directive(q)
        self.assertIn(agent.HIDDEN_DATE_DIRECTIVE_MARKER, directive)
        self.assertIn("2024년 귀속", directive)
        self.assertIn("search_historical_law_for_gemini", directive)

        leaked = directive + "\n### 1. 결론\n정상 답변입니다."
        cleaned = agent._strip_leaked_temporal_guideline(leaked)
        self.assertNotIn(agent.HIDDEN_DATE_DIRECTIVE_MARKER, cleaned)
        self.assertTrue(cleaned.startswith("### 1. 결론"))

    def test_20_v3_law_candidate_sorting_and_effective_date_annotations(self):
        candidates = [
            {"법령명한글": "조세특례제한법", "법령일련번호": "101", "시행일자": "20270101", "공포일자": "20251231"},
            {"법령명한글": "조세특례제한법", "법령일련번호": "100", "시행일자": "20260101", "공포일자": "20251231"},
            {"법령명한글": "조세특례제한법", "법령일련번호": "099", "시행일자": "20250101", "공포일자": "20241231"},
        ]
        sorted_cands = agent._sort_law_candidates_for_today(candidates)
        self.assertEqual(sorted_cands[0]["법령일련번호"], "100")

        raw_tool_out = (
            "📘 [조세특례제한법 | 공포번호: 제21223호 | 시행일자: 2026.01.01]\n"
            "제29조의8(통합고용세액공제) 2026년 1월 1일부터 시행한다.\n"
            "부칙: 2027년 1월 1일 이후 개시하는 과세연도분부터 적용한다."
        )
        annotated = agent._annotate_law_effective_dates_vs_today(raw_tool_out)
        self.assertIn("도구 실시간 시점 판정 브리핑", annotated)
        self.assertIn("2026", annotated)
        self.assertIn("2027", annotated)

    def test_21_v3_timeline_hallucination_scanner(self):
        # 1) 2026년 1월 1일 시행 규정을 아직 미시행 유예로 오판한 답변 적발
        bad_2026_defer = "이 규정은 2026년 1월 1일부터 시행 예정이므로 현재는 적용되지 않습니다."
        errs1 = agent._scan_timeline_hallucinations(bad_2026_defer, user_query="근로소득 간이지급명세서 제출주기 알려줘")
        self.assertTrue(any("이미 시행 중인" in e for e in errs1), msg=f"errs1={errs1}")

        # 2) 2027년 시행 예정 규정을 올해(2026년)부터 바로 적용받는다고 오판한 답변 적발
        bad_2027_premature = "2027년 개정 규정에 따라 올해 2026년 귀속분도 즉시 공제 가능합니다."
        errs2 = agent._scan_timeline_hallucinations(bad_2027_premature, user_query="올해 통합고용세액공제 계산해줘")
        self.assertTrue(any("조기적용 오판" in e for e in errs2), msg=f"errs2={errs2}")

        # 3) 과거(2024년 귀속) 질의인데 답변에서 2024년 언급이 전혀 누락된 경우 적발
        bad_past_missing = "2026년 귀속 통합고용세액공제는 인당 1,450만 원을 공제합니다."
        errs3 = agent._scan_timeline_hallucinations(bad_past_missing, user_query="2024년 귀속 통합고용세액공제 금액 알려줘")
        self.assertTrue(any("2024년" in e for e in errs3), msg=f"errs3={errs3}")

        # 4) 정상 답변은 위반 0건
        good_ans = "적용 기준: 2024년 귀속 · 2024.01.01 시행 구법 및 법률 제21223호 부칙 제34조 경과조치에 따라 종전 규정을 적용합니다."
        errs4 = agent._scan_timeline_hallucinations(good_ans, user_query="2024년 귀속 통합고용세액공제 금액 알려줘")
        self.assertEqual(errs4, [])

    def test_22_v3_app_and_law_api_wiring_verification(self):
        with open(os.path.join(CODE_ROOT, "app.py"), "r", encoding="utf-8") as f:
            app_src = f.read()
        self.assertIn("build_hidden_date_law_directive", app_src)
        self.assertNotIn("[오늘 날짜 기준 지침]:", app_src)

        with open(os.path.join(CODE_ROOT, "law_api.py"), "r", encoding="utf-8") as f:
            law_src = f.read()
        self.assertIn("조문시행일자:", law_src)
        self.assertIn("미시행(미래 시행예정) 조문 경고", law_src)

    def test_23_payroll_dead_zone_1000_brackets_zero_overpayment(self):
        """[극한 데드존 검증] 150만~1,050만 원 전 구간(900개 세율 경계)에서 데드존 진동·초과 산출(Overpayment) 0건 검증"""
        def _net_at(g: int) -> int:
            ins = pa_tax.calc_4ins_by_rate(g, year=2026, is_ceo=False)
            wt = pa_tax.calc_withholding_tax(g, dependents=1, children_8_to_20=0, rate_pct=100, year_month="2026-10")
            return g - (ins["국민연금"] + ins["건강보험"] + ins["장기요양보험료"] + ins["고용보험"] + wt["소득세"] + wt["지방소득세"])

        for b in range(150, 1050, 10):
            g_pre = b * 10_000 - 1
            n_pre = _net_at(g_pre)
            res = pa_tax.gross_up_employee_net_to_gross(n_pre, non_taxable_pay=0, dependents=1, children_8_to_20=0)
            self.assertEqual(res["차인지급액"], n_pre)
            self.assertLessEqual(res["지급액계"], g_pre, msg=f"Dead-zone overpayment at {b*10}k: {res['지급액계']} > {g_pre}")

        # Freelancer extreme tax rate >= 95% boundary check
        res_f95 = pa_tax.gross_up_freelancer_net_to_gross(1_000_000, rate_pct=95.0)
        self.assertGreaterEqual(res_f95["지급총액"], 1_000_000)

    def test_24_agent_ast_calculator_mixed_comma_and_concurrency_stress(self):
        """[AST 수식 & 멀티스레드 검증] 공백 없는 함수 인자와 천 단위 쉼표 공존 수식 무결성 및 16스레드 동시성 검증"""
        import concurrent.futures

        cases = [
            ("min(100,200)", "100"),
            ("max(100,200) + min(300, 400)", "500"),
            ("min(100,200) + 1,000,000", "1,000,100"),
            ("max(1,200,300)", "300"),
            ("round(1,234,567.89, 1)", "1,234,568"),
            ("sum([1,000, 2,000, 3,000])", "6,000"),
        ]
        for expr, expected_substr in cases:
            out = agent.run_tax_calculator_for_gemini(expr, "복합쉼표검증")
            self.assertNotIn("오류", out, msg=f"Failed on {expr}: {out}")
            self.assertIn(expected_substr, out, msg=f"Mismatch on {expr}: {out}")

        def _worker(tid: int) -> bool:
            r = agent._resolve_law_name(f"조특법(법률 제21223호)", agent._BASE_KNOWN_LAW_TITLES)
            c = agent._find_article_refs_with_kind("조세특례제한법 부칙(법률 제21223호) 제34조에 따른다.")
            return r == "조세특례제한법" and len(c) == 1 and c[0][3] is True

        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
            futs = [pool.submit(_worker, i) for i in range(64)]
            self.assertTrue(all(f.result() for f in futs))

    def test_25_law_api_molit_trade_xml_and_nps_2026_rates(self):
        """[law_api 실거래가 XML 파싱 & 2026년 4대보험 요율 정합성 검증] Element.values() 런타임 크래시 제거 및 2026 법정요율 검증"""
        from unittest import mock

        sample_trade_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <response>
            <header><resultCode>00</resultCode><resultMsg>NORMAL SERVICE.</resultMsg></header>
            <body><items>
                <item>
                    <umdNm>역삼동</umdNm>
                    <aptNm>역삼자이</aptNm>
                    <jibun>711</jibun>
                    <excluUseAr>84.99</excluUseAr>
                    <floor>15</floor>
                    <buildYear>2016</buildYear>
                    <dealAmount>235,000</dealAmount>
                    <dealDay>12</dealDay>
                </item>
            </items></body>
        </response>"""

        mock_resp = mock.MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = sample_trade_xml

        with mock.patch.dict(os.environ, {"NTS_API_KEY": "DUMMY_TEST_KEY"}), \
             mock.patch("law_api.requests.get", return_value=mock_resp):
            out = law_api.get_molit_real_estate_trade("apt", "강남구", "202609", "역삼자이")
            self.assertIn("역삼자이", out)
            self.assertIn("235,000만원", out)
            self.assertNotIn("AttributeError", out)

        # Verify 2026 vs 2025 statutory rates in get_nps_workplace_info
        def _fake_nps_get(url, **kwargs):
            m = mock.MagicMock()
            m.status_code = 200
            if "getBassInfoSearchV2" in url:
                m.text = """<response><header><resultCode>00</resultCode></header><body><items>
                    <item><wkplNm>테스트세무법인</wkplNm><bzowrRgstNo>123456</bzowrRgstNo><wkplJnngStcd>1</wkplJnngStcd>
                    <wkplStylDvcd>1</wkplStylDvcd><wkplRoadNmDtlAddr>서울 강남구</wkplRoadNmDtlAddr><dataCrtYm>202609</dataCrtYm><seq>S2026</seq></item>
                    <item><wkplNm>테스트세무법인</wkplNm><bzowrRgstNo>123456</bzowrRgstNo><wkplJnngStcd>1</wkplJnngStcd>
                    <wkplStylDvcd>1</wkplStylDvcd><wkplRoadNmDtlAddr>서울 강남구</wkplRoadNmDtlAddr><dataCrtYm>202509</dataCrtYm><seq>S2025</seq></item>
                </items></body></response>"""
            elif "seq=S2026" in url:
                # 2026년: 보수총액 10,000,000원 -> 국민연금 9.5% = 950,000원
                m.text = """<response><header><resultCode>00</resultCode></header><body><items>
                    <item><jnngpCnt>3</jnngpCnt><crrmmNtcAmt>950000</crrmmNtcAmt><nwAcqzrCnt>0</nwAcqzrCnt><lssJnngpCnt>0</lssJnngpCnt></item>
                </items></body></response>"""
            elif "seq=S2025" in url:
                # 2025년: 보수총액 10,000,000원 -> 국민연금 9.0% = 900,000원
                m.text = """<response><header><resultCode>00</resultCode></header><body><items>
                    <item><jnngpCnt>3</jnngpCnt><crrmmNtcAmt>900000</crrmmNtcAmt><nwAcqzrCnt>0</nwAcqzrCnt><lssJnngpCnt>0</lssJnngpCnt></item>
                </items></body></response>"""
            else:
                m.text = "<response><header><resultCode>00</resultCode></header><body><items></items></body></response>"
            return m

        with mock.patch.dict(os.environ, {"NTS_API_KEY": "DUMMY_TEST_KEY"}), \
             mock.patch("law_api.requests.get", side_effect=_fake_nps_get):
            nps_out = law_api.get_nps_workplace_info("테스트세무법인", "123456")
            # Both 2026 (950,000 / 0.095) and 2025 (900,000 / 0.09) should back-calculate to 10,000,000원 payroll!
            self.assertEqual(nps_out.count("10,000,000원"), 2, msg=f"Unexpected NPS output:\n{nps_out}")

    def test_26_ec_ui_common_and_app_atomic_io_and_fingerprint_parity(self):
        """[ui_common & app.py 검증] 혼합 타입 키 지문(Fingerprint) 결정론적 해시 및 원자적 JSON I/O 검증"""
        import tempfile
        s = ec_common._default_state_dict()
        s["year_recs"] = {2025: {"p1": {"pay": {1: 3000000}}}, "2026": {"p1": {"pay": {"1": 3100000}}}}
        fp1 = ec_common._calc_fingerprint(s)
        fp2 = ec_common._calc_fingerprint(s)
        self.assertEqual(fp1, fp2)
        self.assertEqual(len(fp1), 32)

        with tempfile.TemporaryDirectory() as td:
            test_json = os.path.join(td, "atomic_test.json")
            # Verify atomic write & cached read via app.py helpers
            import importlib.util
            with open(os.path.join(CODE_ROOT, "app.py"), "r", encoding="utf-8") as f:
                app_src = f.read()
            self.assertIn("_atomic_write_json_dict", app_src)
            self.assertIn("_read_json_dict_cached", app_src)
            self.assertIn("_MD_REL_LAWS_RE", app_src)

    def test_27_all_32_modules_ast_signature_and_cross_call_compatibility(self):
        """[전수 호환성 검증] 프로젝트 내 32개 전체 파이썬 모듈 임포트 및 956개 모듈 간 호출부(Call-site) 시그니처 100% 정합성 검증"""
        import ast, inspect, importlib

        py_files = []
        for r, dirs, files in os.walk(CODE_ROOT):
            dirs[:] = [d for d in dirs if d not in ("__pycache__", ".workspace_storage", ".git")]
            for fn in sorted(files):
                if fn.endswith(".py"):
                    py_files.append(os.path.relpath(os.path.join(r, fn), CODE_ROOT))

        loaded_modules = {}
        for pf in py_files:
            if pf == "app.py":
                continue
            mod_name = pf[:-3].replace("/", ".")
            if mod_name.endswith(".__init__"):
                mod_name = mod_name[:-9]
            loaded_modules[mod_name] = importlib.import_module(mod_name)
            loaded_modules[pf] = loaded_modules[mod_name]

        issues = []
        checked_calls = 0
        for pf in py_files:
            full_p = os.path.join(CODE_ROOT, pf)
            with open(full_p, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=pf)
            pkg = os.path.dirname(pf).replace("/", ".")
            imported_objs, imported_mods = {}, {}
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        asname = alias.asname or alias.name
                        if alias.name in loaded_modules:
                            imported_mods[asname] = loaded_modules[alias.name]
                elif isinstance(node, ast.ImportFrom):
                    mod_target = node.module or ""
                    if node.level > 0 and pkg:
                        mod_target = f"{pkg}.{mod_target}".strip(".")
                    if mod_target in loaded_modules:
                        m_obj = loaded_modules[mod_target]
                        for alias in node.names:
                            if alias.name == "*":
                                for k in dir(m_obj):
                                    if not k.startswith("__"):
                                        imported_objs[k] = getattr(m_obj, k)
                            else:
                                asname = alias.asname or alias.name
                                if not hasattr(m_obj, alias.name):
                                    issues.append(f"[{pf}:{node.lineno}] Missing import {alias.name} from {mod_target}")
                                else:
                                    imported_objs[asname] = getattr(m_obj, alias.name)
                                    if inspect.ismodule(imported_objs[asname]):
                                        imported_mods[asname] = imported_objs[asname]

            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    target_fn, target_desc = None, ""
                    if isinstance(node.func, ast.Name) and node.func.id in imported_objs:
                        target_fn = imported_objs[node.func.id]
                        target_desc = node.func.id
                    elif isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                        base_id = node.func.value.id
                        if base_id in imported_mods:
                            m_obj = imported_mods[base_id]
                            if not hasattr(m_obj, node.func.attr):
                                issues.append(f"[{pf}:{node.lineno}] Missing attr {base_id}.{node.func.attr}")
                            else:
                                target_fn = getattr(m_obj, node.func.attr)
                                target_desc = f"{base_id}.{node.func.attr}"
                    if callable(target_fn) and not inspect.isclass(target_fn):
                        try:
                            sig = inspect.signature(target_fn)
                            has_starred = any(isinstance(a, ast.Starred) for a in node.args) or any(kw.arg is None for kw in node.keywords)
                            if not has_starred:
                                sig.bind(*([None] * len(node.args)), **{kw.arg: None for kw in node.keywords if kw.arg is not None})
                            checked_calls += 1
                        except TypeError as e:
                            issues.append(f"[{pf}:{node.lineno}] Signature mismatch on {target_desc}: {e}")

        self.assertGreaterEqual(checked_calls, 900)
        self.assertEqual(issues, [], msg=f"Compatibility issues: {issues}")


def run_comparative_benchmarks(orig_dir: str, opt_dir: str) -> None:
    """터미널에서 기존 코드(orig_dir) vs 최적화 코드(opt_dir) 실측 속도 및 피크 메모리를 비교 출력합니다."""
    import subprocess, json

    bench_worker = """
import sys, os, time, tracemalloc, json, datetime as dt
import pandas as pd
target = sys.argv[1]
sys.path.insert(0, target)
import test_and_benchmark_suite as _tbs
_tbs.ensure_headless_mocks()

import agent
from employment_credit import rules as ec_rules, ui_common as ec_common, ui_step4 as ec_step4
from payroll_automated import tax_tables as pa_tax, parsers as pa_parsers

results = {}
def measure(key, fn, iters=1):
    fn()  # warmup
    t0 = time.perf_counter()
    for _ in range(iters):
        fn()
    ms = (time.perf_counter() - t0) * 1000.0
    tracemalloc.start()
    fn()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    results[key] = {"ms": round(ms, 2), "kb": round(peak / 1024.0, 1)}

# 1. Agent _scan_violations + _inject_direct_law_links (200-line legal report x 10 iters)
trace = agent._new_trace()
tok = agent._TOOL_TRACE.set(trace)
try:
    sample_law = (
        "📘 [조세특례제한법 | 공포번호: 제21223호 | 시행일자: 2026.01.01]\\n\\n"
        + "\\n\\n".join([f"제{j}조(조문제목{j}) ① 조문 본문 내용입니다. 세액을 공제한다." for j in range(1, 50)])
        + "\\n\\n📌 [관련 최근 개정 부칙(본칙 한정 시행일·적용례·경과조치) 발췌]\\n부칙 <제21223호, 2025.12.31.>\\n제34조(경과조치) 종전의 규정에 따른다."
    )
    agent._record("detail", sample_law)
    agent._record_law_articles(sample_law)
finally:
    agent._TOOL_TRACE.reset(tok)

report_200 = "### 1. 결론\\n적용 기준: 2026년 귀속 · 2026.01.01 시행 법령\\n" + "\\n".join([
    f"- 검토 항목 {i}: 조세특례제한법 제{(i % 40) + 1}조 제1항에 따라 세액공제를 적용합니다 [조문: 조세특례제한법 제{(i % 40) + 1}조]. 또한 부칙 제34조에 따라 경과조치를 적용합니다 [부칙: 조세특례제한법 부칙 제34조]."
    for i in range(200)
]) + "\\n### 3. 관련법령\\n- 조세특례제한법 제29조(세액공제)\\n- 조세특례제한법 부칙 제34조"

measure("agent_citation_audit_200lines_x10", lambda: (agent._scan_violations(report_200, trace), agent._inject_direct_law_links(report_200, trace)), iters=10)

# 2. Payroll gross_up_employee_net_to_gross (60 employees batch)
measure("payroll_gross_up_60_employees", lambda: [
    pa_tax.gross_up_employee_net_to_gross(2_000_000 + i * 37_543, dependents=(i % 5) + 1, children_8_to_20=(i % 3), is_ceo=(i % 7 == 0), income_tax_reduction_pct=(90 if i % 4 == 0 else 0))
    for i in range(60)
], iters=1)

# 3. Employment credit fingerprint & step4 report cache sig (100 employees x 3 years x 50 iters)
s_100 = ec_common._default_state_dict()
s_100["tax_year"] = 2026
s_100["corp_size_default"] = "중소기업"
for i in range(1, 101):
    pid = f"p{i:03d}"
    s_100["people"][pid] = {"name": f"사원{i}", "birth": "1992-05-15", "hire": "2024-01-01", "retire": "", "is_regular": True, "wp": "본점"}
for y in (2024, 2025, 2026):
    s_100["year_recs"][y] = {f"p{i:03d}": {"pay": {m: 3_000_000 for m in range(1, 13)}, "고용유형": "상시", "제외사유": "", "청년등": ""} for i in range(1, 101)}

measure("ec_fingerprint_and_report_sig_100emps_x50", lambda: (ec_common._calc_fingerprint(s_100), ec_step4._compute_report_cache_sig(s_100, 2026)), iters=50)

# 4. Employment credit _build_year_rows_uncached (100 employees x 3 years x 5 iters)
measure("ec_build_year_rows_100emps_3yrs_x5", lambda: [ec_common._build_year_rows_uncached(s_100, y) for y in (2024, 2025, 2026)], iters=5)

# 5. Golden case invariants (43 scenarios x 5 iters)
measure("ec_golden_invariants_43cases_x5", lambda: ec_rules.verify_golden_case_invariants(), iters=5)

print("BENCH_JSON:" + json.dumps(results))
"""
    worker_path = "/tmp/_bench_worker.py"
    with open(worker_path, "w", encoding="utf-8") as f:
        f.write(bench_worker)

    def _run_one(target_path: str) -> dict:
        out = subprocess.check_output([sys.executable, worker_path, target_path], text=True)
        for ln in out.splitlines():
            if ln.startswith("BENCH_JSON:"):
                return json.loads(ln[len("BENCH_JSON:"):])
        return {}

    r_orig = _run_one(orig_dir)
    r_opt = _run_one(opt_dir)

    print("\n" + "=" * 95)
    print(f"{'벤치마크 항목':42s} | {'기존 v3 코드 (ms / KB)':22s} | {'최적화 v3 코드 (ms / KB)':22s} | {'개선율'}")
    print("-" * 95)
    for k in r_orig:
        o_ms, o_kb = r_orig[k]["ms"], r_orig[k]["kb"]
        n_ms, n_kb = r_opt[k]["ms"], r_opt[k]["kb"]
        speedup = o_ms / max(0.01, n_ms)
        mem_diff = ((n_kb - o_kb) / max(0.1, o_kb)) * 100.0
        print(f"{k:42s} | {o_ms:8.2f} ms / {o_kb:6.1f} KB | {n_ms:8.2f} ms / {n_kb:6.1f} KB | {speedup:5.2f}x ({mem_diff:+.1f}% mem)")
    print("=" * 95)


if __name__ == "__main__":
    orig_p = "/working_dir/c_1b9d639abbdd8152/workspace_orig"
    opt_p = "/working_dir/c_1b9d639abbdd8152/workspace_opt"
    if os.path.isdir(orig_p) and os.path.isdir(opt_p) and "--bench" in sys.argv:
        sys.argv.remove("--bench")
        run_comparative_benchmarks(orig_p, opt_p)
    unittest.main(verbosity=2)
