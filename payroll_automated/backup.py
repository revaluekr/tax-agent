# -*- coding: utf-8 -*-
"""
인건비 자동화 - 거래처별 월별 누적 암호화 백업 (.paybak) 및 통합고용세액공제 원클릭 브릿지 (backup.py)
1) 거래처별 단일 누적 백업 파일 (.paybak):
   - PBKDF2HMAC + Fernet(AES-128-CBC + HMAC-SHA256) + zlib 압축 (통합고용세액공제 백업 규격과 동일)
   - 하나의 파일 안에 거래처 기본정보(corp_info: 상호, 상시근로자 수, 사업주 고용보험 요율 구간 포함), 상시근로자 마스터(employees_master),
     거래처 엑셀 열 매핑 프로필(excel_mapping), 월별 급여·사업소득 이력(monthly_payroll['YYYY-MM'])을 누적 보관
   - 전월 급여 불러오기 시 직전 귀속연월 데이터를 즉시 복원하여 당월 급여대장/사업소득대장 초안 생성
2) 통합고용세액공제 원클릭 연동 브릿지:
   - 누적된 인별 입사일·퇴사일·주민등록번호·월별 과세급여/비과세 데이터를
     통합고용세액공제(employment_credit) 모듈의 session_state('ec_wizard_state')로 자동 변환·주입
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import zlib
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from cryptography.fernet import Fernet, InvalidToken


BACKUP_MAGIC_HEADER = b"PAYBAK_V1:"
PBKDF2_ITERATIONS = 100_000


def _derive_fernet_key(password: str, salt: bytes) -> bytes:
    """비밀번호(또는 기본 시드)와 16바이트 솔트로 Fernet 대칭키 파생"""
    pwd_bytes = (password or "TAX_AGENT_PAYROLL_DEFAULT_KEY_2026").encode("utf-8")
    dk = hashlib.pbkdf2_hmac("sha256", pwd_bytes, salt, PBKDF2_ITERATIONS, dklen=32)
    return base64.urlsafe_b64encode(dk)


def create_empty_client_db(corp_name: str = "") -> Dict[str, Any]:
    """거래처 누적 DB 초기 구조 생성"""
    return {
        "schema_version": "1.0",
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "corp_info": {
            "corp_name": corp_name,
            "biz_no": "",
            "ceo_name": "",
            "is_5_or_more": True,
            "withholding_rate_pct": 100,
            "effective_table": "2026.03",
            "ei_emp_count_manual": None,
            "ei_stability_tier_manual": None,
        },
        "excel_mapping": {},
        "employees_master": {},
        "freelancers_master": {},
        "monthly_payroll": {},
    }


def upsert_monthly_data_into_db(
    client_db: Dict[str, Any],
    corp_name: str,
    year_month: str,
    pay_date: str,
    employees: List[Dict[str, Any]],
    freelancers: List[Dict[str, Any]],
    is_5_or_more: bool = True,
    withholding_rate_pct: int = 100,
    effective_table: str = "2026.03",
    ei_emp_count_manual: Optional[int] = None,
    ei_stability_tier_manual: Optional[str] = None,
) -> Dict[str, Any]:
    """
    현재 작업 중인 귀속연월(YYYY-MM)의 급여대장 및 사업소득대장을 거래처 누적 DB에 병합·저장:
    - 기존 다른 월(예: 2026-08, 2026-09) 데이터는 그대로 보존하고 해당 월(예: 2026-10)만 갱신/추가!
    - 직원의 입사일, 퇴사일, 주민등록번호, 부양가족수는 employees_master에도 최신 상태로 동기화
    - 사용자가 설정한 상시근로자 수 및 사업주 고용보험 요율 구간도 corp_info에 함께 보존
    """
    if not client_db or "monthly_payroll" not in client_db:
        client_db = create_empty_client_db(corp_name)

    client_db["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    client_db.setdefault("corp_info", {})
    if corp_name:
        client_db["corp_info"]["corp_name"] = corp_name
    client_db["corp_info"]["is_5_or_more"] = is_5_or_more
    client_db["corp_info"]["withholding_rate_pct"] = withholding_rate_pct
    client_db["corp_info"]["effective_table"] = effective_table
    client_db["corp_info"]["ei_emp_count_manual"] = ei_emp_count_manual
    client_db["corp_info"]["ei_stability_tier_manual"] = ei_stability_tier_manual

    emp_master = client_db.setdefault("employees_master", {})
    for emp in employees or []:
        nm = str(emp.get("성명", "")).strip()
        if not nm:
            continue
        master_entry = emp_master.get(nm, {})
        for k in ("사원코드", "성명", "주민등록번호", "입사일", "퇴사일", "부서", "직급", "부양가족수", "자녀수", "약정시급"):
            if emp.get(k) not in (None, ""):
                master_entry[k] = emp[k]
        emp_master[nm] = master_entry

    free_master = client_db.setdefault("freelancers_master", {})
    for fr in freelancers or []:
        nm = str(fr.get("성명", "")).strip()
        if not nm:
            continue
        f_entry = free_master.get(nm, {})
        for k in ("코드", "성명", "주민등록번호", "소득구분"):
            if fr.get(k) not in (None, ""):
                f_entry[k] = fr[k]
        free_master[nm] = f_entry

    ym_key = (year_month or datetime.now().strftime("%Y-%m")).strip()
    clean_emps = [
        {k: v for k, v in e.items() if not str(k).startswith("_")}
        for e in (employees or [])
    ]
    clean_frees = [
        {k: v for k, v in f.items() if not str(k).startswith("_")}
        for f in (freelancers or [])
    ]

    client_db["monthly_payroll"][ym_key] = {
        "year_month": ym_key,
        "pay_date": pay_date,
        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "employees": clean_emps,
        "freelancers": clean_frees,
    }
    return client_db


def encrypt_client_db_to_paybak(client_db: Dict[str, Any], password: str = "") -> bytes:
    """거래처 누적 DB를 압축 후 암호화하여 .paybak 바이너리로 반환"""
    json_bytes = json.dumps(client_db, ensure_ascii=False, indent=2).encode("utf-8")
    compressed = zlib.compress(json_bytes, level=9)
    salt = os.urandom(16)
    key = _derive_fernet_key(password, salt)
    token = Fernet(key).encrypt(compressed)
    return BACKUP_MAGIC_HEADER + salt + token


def decrypt_paybak_to_client_db(file_bytes: bytes, password: str = "") -> Dict[str, Any]:
    """
    업로드된 .paybak (또는 JSON 백업) 파일을 복호화하여 거래처 누적 DB dict로 반환
    """
    if file_bytes.startswith(BACKUP_MAGIC_HEADER):
        payload = file_bytes[len(BACKUP_MAGIC_HEADER):]
        salt = payload[:16]
        token = payload[16:]
        for cand_pw in (password, ""):
            try:
                key = _derive_fernet_key(cand_pw, salt)
                decompressed = zlib.decompress(Fernet(key).decrypt(token))
                return json.loads(decompressed.decode("utf-8"))
            except InvalidToken:
                continue
        raise ValueError("백업 파일 암호가 일치하지 않거나 손상된 파일입니다.")

    return json.loads(file_bytes.decode("utf-8"))


def get_previous_month_data(
    client_db: Dict[str, Any],
    current_year_month: str,
) -> Optional[Dict[str, Any]]:
    """
    누적 DB에서 current_year_month(예: '2026-10') 직전 귀속월(예: '2026-09' 또는 가장 최근 이전 월) 데이터를 반환
    """
    monthly = (client_db or {}).get("monthly_payroll", {})
    if not monthly:
        return None
    sorted_months = sorted(monthly.keys())
    prior_months = [m for m in sorted_months if m < current_year_month]
    if prior_months:
        target_ym = prior_months[-1]
        return monthly[target_ym]
    return monthly[sorted_months[-1]]


# ─────────────────────────────────────────────────────────────
# 통합고용세액공제 원클릭 연동 브릿지
# ─────────────────────────────────────────────────────────────

def build_employment_credit_bridge_payload(
    client_db: Dict[str, Any],
    current_corp_name: str,
    current_year_month: str,
    current_employees: List[Dict[str, Any]],
) -> Tuple[Dict[str, Any], str]:
    year_str = (current_year_month or datetime.now().strftime("%Y-%m"))[:4]
    try:
        target_year = int(year_str)
    except ValueError:
        target_year = datetime.now().year

    monthly_map: Dict[str, Dict[str, Any]] = dict((client_db or {}).get("monthly_payroll", {}))
    if current_employees:
        monthly_map[current_year_month] = {
            "year_month": current_year_month,
            "employees": current_employees,
        }

    people_by_name: Dict[str, Dict[str, Any]] = {}
    for ym, m_data in sorted(monthly_map.items()):
        for emp in m_data.get("employees", []):
            nm = str(emp.get("성명", "")).strip()
            if not nm:
                continue
            p = people_by_name.setdefault(nm, {
                "name": nm,
                "rrn": "",
                "hire_date": "",
                "retire_date": "",
                "months_worked": [],
                "total_gross": 0,
                "total_taxable": 0,
            })
            if emp.get("주민등록번호"):
                p["rrn"] = str(emp["주민등록번호"])
            if emp.get("입사일"):
                p["hire_date"] = str(emp["입사일"])
            if emp.get("퇴사일"):
                p["retire_date"] = str(emp["퇴사일"])
            if ym not in p["months_worked"]:
                p["months_worked"].append(ym)
            p["total_gross"] += int(emp.get("지급액계", 0))
            p["total_taxable"] += int(emp.get("과세급여", emp.get("지급액계", 0)))

    people_list: List[Dict[str, Any]] = []
    for idx, (nm, p) in enumerate(people_by_name.items(), start=1):
        birth_iso = _rrn_to_birth_iso(p["rrn"])
        people_list.append({
            "id": f"EMP_{idx:03d}",
            "성명": nm,
            "주민등록번호": p["rrn"],
            "생년월일": birth_iso,
            "입사일": p["hire_date"],
            "퇴사일": p["retire_date"],
            "근무월수": len(p["months_worked"]),
            "누적급여계": p["total_gross"],
            "누적과세급여": p["total_taxable"],
        })

    summary_msg = (
        f"거래처 [{current_corp_name or '미입력'}]의 누적 급여데이터 "
        f"(총 {len(monthly_map)}개월분, 근로자 {len(people_list)}명)를 "
        f"통합고용세액공제 분석 데이터로 연동했습니다."
    )

    bridge_data = {
        "corp_name": current_corp_name,
        "target_year": target_year,
        "months_loaded": sorted(monthly_map.keys()),
        "people": people_list,
        "transferred_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    return bridge_data, summary_msg


def _rrn_to_birth_iso(rrn: str) -> str:
    if not rrn:
        return ""
    import re
    cleaned = re.sub(r"[^0-9]", "", str(rrn))
    if len(cleaned) < 6:
        return ""
    yy = int(cleaned[:2])
    mm = int(cleaned[2:4])
    dd = int(cleaned[4:6])
    gender_digit = cleaned[6:7] if len(cleaned) >= 7 else ""
    if gender_digit in ("1", "2", "5", "6"):
        yyyy = 1900 + yy
    elif gender_digit in ("3", "4", "7", "8"):
        yyyy = 2000 + yy
    else:
        yyyy = 2000 + yy if yy <= 30 else 1900 + yy
    if 1 <= mm <= 12 and 1 <= dd <= 31:
        return f"{yyyy:04d}-{mm:02d}-{dd:02d}"
    return ""
