# -*- coding: utf-8 -*-
"""
통합고용세액공제 법령·시행령·시행규칙·농어촌특별세법 기준 해시 캡처 스크립트 (capture_baseline_laws.py)

[용도]
- 법제처 국가법령정보센터 Open API(LAW_OPEN_API_KEY)가 연결된 환경에서 개발자가 1회 실행합니다.
- 앱(employment_credit/parsers.py)과 100% 동일한 파서(`_parse_law_header_and_sections`)로
  실제 법제처 원문을 받아 법령명 일치 여부를 확인하고,
  법령ID, 공포번호, 공포일, 시행일, 감시 조문별 해시(시행령 제11조의2 제8항 항 슬라이싱 포함),
  특정 부칙 조문 해시(21223_제34조, 35999_제2조, 36127_제11조), 별지 서식 개정일을 추출하여
  `employment_credit/rules.py`의 `BASELINE_LAW_INFO`에 붙여넣을 수 있는 파이썬 코드를 표준출력(stdout)으로만 표시합니다.
- 이 스크립트는 rules.py, 디스크 캐시, 세션 상태를 직접 수정하지 않습니다 (읽기 전용 출력).
"""
from __future__ import annotations

from datetime import date
import json
import re
import sys

import agent
import law_api
from employment_credit import rules as R
from employment_credit import parsers as P


def capture_live_baseline_dict() -> dict[str, dict]:
    law_queries = [
        ("조세특례제한법", "제29조의8, 제132조, 제144조, 부칙 제34조"),
        ("조세특례제한법 시행령", "제26조의8, 제11조의2, 제23조, 부칙 제2조, 부칙 제11조"),
        ("조세특례제한법 시행규칙", "제14조, 부칙"),
        ("농어촌특별세법", "제5조, 부칙"),
    ]

    # 별지 제10호의9·제10호의10 서식 개정일 조회
    form_rev_dates: dict[str, str] = {}
    try:
        byl_rows = law_api.search_law_data("통합고용세액공제", target="licbyl") or []
        for r_byl in byl_rows:
            if not isinstance(r_byl, dict):
                continue
            b_title = str(r_byl.get("별표명") or r_byl.get("서식명") or "")
            b_dt = R._fmt_dot_date(str(r_byl.get("공포일자") or r_byl.get("시행일자") or ""))
            if "10호의9" in b_title and b_dt and b_dt != "-":
                form_rev_dates["별지 제10호의9서식"] = b_dt
            elif "10호의10" in b_title and b_dt and b_dt != "-":
                form_rev_dates["별지 제10호의10서식"] = b_dt
    except Exception:
        pass

    captured: dict[str, dict] = {}
    today_iso = date.today().isoformat()

    for l_nm, qf in law_queries:
        # 1) 법령명으로 검색하여 응답 법령명 일치 확인 및 법령ID 추출
        found_law_id = ""
        s_rows = law_api.search_law_data(l_nm, "law") or []
        if isinstance(s_rows, dict):
            s_rows = [s_rows]
        target_norm = re.sub(r"\s+", "", l_nm)
        exact_rows = [
            r for r in s_rows
            if re.sub(r"\s+", "", str(r.get("법령명한글") or r.get("법령명_한글") or "")) == target_norm
        ]
        if exact_rows:
            exact_rows.sort(key=lambda x: (str(x.get("공포일자", "")), str(x.get("시행일자", ""))), reverse=True)
            found_law_id = str(exact_rows[0].get("법령ID") or exact_rows[0].get("법령일련번호") or "").strip()

        # 2) 앱과 동일한 파서로 조문 및 부칙 원문 조회·분리
        w_tok = agent._TOOL_TRACE.set(agent._new_trace(unleash=True))
        try:
            raw_res = agent.get_law_details_for_gemini(doc_id=l_nm, target="law", query_filter=qf)
        finally:
            agent._TOOL_TRACE.reset(w_tok)

        parsed = P._parse_law_header_and_sections(str(raw_res or ""), l_nm)
        if parsed.get("_fetch_error") or parsed.get("_law_name_mismatch"):
            raise RuntimeError(
                f"법령 '{l_nm}' 원문 캡처 실패 또는 법령명 불일치: {parsed}"
            )

        b_cfg = R.BASELINE_LAW_INFO.get(l_nm) or {}
        eff_id = str(parsed.get("법령ID") or found_law_id).strip()
        entry = {
            "법령ID": eff_id,
            "법령명": l_nm,
            "법종구분": b_cfg.get("법종구분", "법령"),
            "감시조문": tuple(b_cfg.get("감시조문") or ()),
            "관련부칙": b_cfg.get("관련부칙", ""),
            "특정부칙_목록": tuple(b_cfg.get("특정부칙_목록") or ()),
            "공포번호": str(parsed.get("공포번호") or ""),
            "공포일": str(parsed.get("공포일") or ""),
            "시행일": str(parsed.get("시행일") or ""),
            "반영일": today_iso,
            "조문해시": str(parsed.get("조문해시") or ""),
            "세부조문해시": dict(parsed.get("세부조문해시") or {}),
            "특정부칙해시": dict(parsed.get("특정부칙해시") or {}),
            "적용시기_부칙원문": str(parsed.get("부칙원문") or "")[:600],
            "영향항목": list(b_cfg.get("영향항목") or ()),
        }
        if l_nm == "조세특례제한법 시행규칙":
            merged_forms = {**dict(b_cfg.get("서식개정일_목록") or {}), **form_rev_dates}
            entry["서식개정일"] = merged_forms.get("별지 제10호의10서식", "2026.03.20")
            entry["서식개정일_목록"] = merged_forms
        captured[l_nm] = entry

    return captured


def main() -> int:
    try:
        data = capture_live_baseline_dict()
    except Exception as exc:
        print(f"# [오류] 법제처 API 원문 캡처 실패: {exc}", file=sys.stderr)
        return 1

    print("# === 아래 블록을 검토한 뒤 employment_credit/rules.py의 BASELINE_LAW_INFO에 붙여넣으세요 ===")
    print("BASELINE_LAW_INFO = " + json.dumps(data, ensure_ascii=False, indent=4))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())