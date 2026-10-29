# -*- coding: utf-8 -*-
"""
통합고용세액공제 법령·시행령·시행규칙·농어촌특별세법 기준 해시 캡처 스크립트 (capture_baseline_laws.py)

[용도]
- 법제처 국가법령정보센터 Open API(LAW_OPEN_API_KEY)가 연결된 환경에서 개발자가 1회 실행합니다.
- 감시 대상 조문과 부칙을 조문별로 개별 조회하여 누락 없이 합친 뒤,
  법령명 일치 여부, 감시 조문 누락(missing_articles) 여부, 특정 부칙 블록(21223_제34조, 35999_제2조, 36127_제11조) 발견 여부를 검증합니다.
- 법령ID(고유번호)와 법령일련번호(MST)를 분리하여 저장하며,
  캡처 성공 시 각 조문·부칙의 원문 앞 80자 미리보기를 함께 출력합니다.
- 이 스크립트는 rules.py, 디스크 캐시, 세션 상태를 직접 수정하지 않습니다 (읽기 전용 출력).
"""
from __future__ import annotations

from datetime import date
import json
import re
import sys

import law_api
from employment_credit import rules as R
from employment_credit import parsers as P


def capture_live_baseline_dict() -> tuple[dict[str, dict], list[str], list[str]]:
    law_specs = [
        ("조세특례제한법", ("제29조의8", "제132조", "제144조"), ("부칙 제34조", "부칙")),
        ("조세특례제한법 시행령", ("제26조의8", "제11조의2 제8항", "제23조 제13항"), ("부칙 제11조", "부칙 제2조", "부칙")),
        ("조세특례제한법 시행규칙", ("제14조",), ("부칙",)),
        ("농어촌특별세법", ("제5조",), ("부칙",)),
    ]

    warnings_out: list[str] = []
    previews_out: list[str] = []

    # 별지 제10호의9·제10호의10 서식 개정일 조회 (미수신 시 기본값 대체 금지, 빈 값 + 경고)
    form_rev_dates: dict[str, str] = {
        "별지 제10호의9서식": "",
        "별지 제10호의10서식": "",
    }
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
    except Exception as exc:
        warnings_out.append(f"[경고] 별지 서식 목록 조회 오류: {exc}")

    for fm_k, fm_v in form_rev_dates.items():
        if not fm_v:
            warnings_out.append(f"[경고] 시행규칙 '{fm_k}'의 서식 개정일을 API에서 확인하지 못해 빈 값('')으로 둡니다.")

    captured: dict[str, dict] = {}
    today_iso = date.today().isoformat()

    for l_nm, w_arts, add_qs in law_specs:
        # 1) 법령명 검색 결과에서 법령ID(고유번호)와 법령일련번호(MST) 분리 추출
        found_law_id = ""
        found_mst_id = ""
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
            top_r = exact_rows[0]
            found_law_id = str(top_r.get("법령ID") or "").strip()
            found_mst_id = str(top_r.get("법령일련번호") or top_r.get("MST") or "").strip()

        # 2) 감시 조문 및 부칙 개별 조회 후 파싱
        combined_raw = P._fetch_single_law_by_individual_articles(l_nm, w_arts, add_qs, law_id_hint=found_law_id, mst_id_hint=found_mst_id)
        parsed = P._parse_law_header_and_sections(combined_raw, l_nm)
        if found_law_id:
            parsed["법령ID"] = found_law_id
        if found_mst_id and not parsed.get("법령일련번호"):
            parsed["법령일련번호"] = found_mst_id

        # 3) 누락 조문 및 특정 부칙 블록 발견 여부 엄격 검증
        b_cfg = R.BASELINE_LAW_INFO.get(l_nm) or {}
        ok_entry, entry_errs = R.validate_captured_law_entry(l_nm, parsed, baseline_cfg=b_cfg)
        if not ok_entry:
            for sp_k, sp_p in (parsed.get("특정부칙_앞80자") or {}).items():
                if sp_p == "미발견":
                    print(f"# [미발견] {l_nm} 특정 부칙 '{sp_k}': 미발견", file=sys.stderr)
            raise RuntimeError(" / ".join(entry_errs))

        # 4) 캡처 성공 조문·부칙 앞 80자 미리보기 기록
        for a_k, a_prev in (parsed.get("조문별_앞80자") or {}).items():
            previews_out.append(f"# [{l_nm} - {a_k} 앞 80자]: {a_prev}")
        for sp_k, sp_prev in (parsed.get("특정부칙_앞80자") or {}).items():
            previews_out.append(f"# [{l_nm} - 부칙 {sp_k} 앞 80자]: {sp_prev}")

        entry = {
            "법령ID": str(parsed.get("법령ID") or ""),
            "법령일련번호": str(parsed.get("법령일련번호") or ""),
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
            entry["서식개정일"] = form_rev_dates.get("별지 제10호의10서식", "")
            entry["서식개정일_목록"] = dict(form_rev_dates)
        captured[l_nm] = entry

    return captured, previews_out, warnings_out


def main() -> int:
    try:
        data, previews, warnings = capture_live_baseline_dict()
    except Exception as exc:
        print(f"# [오류] 법제처 API 원문 캡처 실패: {exc}", file=sys.stderr)
        return 1

    for w in warnings:
        print(f"# {w}", file=sys.stderr)
    print("# === [캡처된 감시 조문 및 특정 부칙 원문 앞 80자 확인] ===")
    for pv in previews:
        print(pv)
    print("\n# === 아래 블록을 검토한 뒤 employment_credit/rules.py의 BASELINE_LAW_INFO에 붙여넣으세요 ===")
    print("BASELINE_LAW_INFO = " + json.dumps(data, ensure_ascii=False, indent=4))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())