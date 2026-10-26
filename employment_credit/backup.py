# -*- coding: utf-8 -*-
"""
통합고용세액공제 작업 백업 — 비밀번호로 암호화한 파일을 PC에 내려받고, 다시 올려 이어서 작업

[암호화 방식]
- 비밀번호 → PBKDF2-HMAC-SHA256(무작위 salt 16바이트, 39만 회 반복)으로 키 생성
- 내용 → Fernet(AES-128-CBC + HMAC-SHA256)으로 암호화. 비밀번호가 틀리거나 파일이 변조되면 열리지 않음
- 직접 만든 암호가 아니라 `cryptography` 라이브러리의 검증된 기능만 사용

[담는 내용]
- 2·3단계 작업 상태(사업자정보, 추가 사업장, 사원표·직접 수정값, 기신고 숫자, 추가공제 입력, 사후관리 기준 등)
- 업로드한 서류 원문은 담지 않음 (용량·개인정보). 파일 목록만 남겨 화면 구성을 유지
- 주민등록번호 뒷자리는 어디에도 남기지 않음
"""
from __future__ import annotations

import base64
import json
import os
import re
from datetime import datetime

FORMAT_ID = "ec-backup"          # 이 계산기가 만든 백업인지 확인하는 표시
FORMAT_VERSION = 1               # 파일 구조 버전 (나중에 바뀌면 여기서 변환)
KDF_ITERATIONS = 390_000
MIN_PASSWORD_LEN = 6
FILE_EXT = "ecbak"

# 백업에 담는 작업 상태 항목
BACKUP_KEYS = (
    "step", "tax_year", "files", "ext", "ext_sig", "built_sig",
    "biz", "biz_confirmed", "sub_biz_list", "people", "year_recs", "prev_summary",
    "additional_inputs", "scheme_2026", "pm_basis", "assume_year_end",
    "include_unpaid_hire_month", "use_year_tabs", "show_all_4_blocks",
    "show_empty_pm_blocks", "manual_extra_years", "next_pid_seq",
)

_RRN_FULL_RE = re.compile(r"(?<!\d)(\d{6})\s*-\s*([1-8])\d{6}(?!\d)")


class BackupError(Exception):
    """사용자에게 그대로 보여줄 수 있는 백업 오류"""


def crypto_available() -> bool:
    try:
        import cryptography  # noqa: F401
        return True
    except Exception:
        return False


def _fernet(password: str, salt: bytes):
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=KDF_ITERATIONS)
    key = base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))
    return Fernet(key)


def _strip_state(s: dict) -> dict:
    state = {k: s.get(k) for k in BACKUP_KEYS if k in s}
    # 서류 원문은 빼고 파일 목록(이름·종류·사업장)만 남김
    files = {}
    for name, f in (state.get("files") or {}).items():
        if isinstance(f, dict):
            files[name] = {"key": f.get("key"), "wp": f.get("wp", ""), "text": "", "restored": True}
    state["files"] = files
    # 혹시 남아 있을 수 있는 주민번호 전체 자리 제거
    raw = json.dumps(state, ensure_ascii=False, default=str)
    raw = _RRN_FULL_RE.sub(r"\1-\2******", raw)
    return json.loads(raw)


def make_backup_bytes(s: dict, password: str) -> tuple[bytes, str]:
    """작업 상태 → 암호화된 백업 파일 바이트와 권장 파일 이름"""
    if not crypto_available():
        raise BackupError("암호화 부품(cryptography)이 설치되어 있지 않습니다. requirements.txt에 cryptography를 추가하세요.")
    if len(password or "") < MIN_PASSWORD_LEN:
        raise BackupError(f"비밀번호는 {MIN_PASSWORD_LEN}자 이상이어야 합니다.")

    biz = s.get("biz") or {}
    corp = str(biz.get("상호") or "미입력").strip()
    tax_year = int(s.get("tax_year") or 0)
    now = datetime.now()
    inner = {
        "app": "통합고용세액공제 계산기",
        "schema": FORMAT_VERSION,
        "saved_at": now.strftime("%Y-%m-%d %H:%M"),
        "상호": corp,
        "tax_year": tax_year,
        "people_count": len(s.get("people") or {}),
        "state": _strip_state(s),
    }
    salt = os.urandom(16)
    token = _fernet(password, salt).encrypt(json.dumps(inner, ensure_ascii=False, default=str).encode("utf-8"))
    outer = {
        "format": FORMAT_ID,
        "version": FORMAT_VERSION,
        "kdf": "pbkdf2-sha256",
        "iterations": KDF_ITERATIONS,
        "salt": base64.b64encode(salt).decode("ascii"),
        "data": token.decode("ascii"),
        "hint": f"{corp} {tax_year}년 귀속",        # 파일을 열지 않고도 무슨 백업인지 알 수 있게 (민감정보 아님)
    }
    safe_corp = re.sub(r'[\\/:*?"<>|\s]+', "_", corp)[:30] or "미입력"
    fname = f"통합고용_{safe_corp}_{tax_year}귀속_{now.strftime('%Y%m%d_%H%M')}.{FILE_EXT}"
    return json.dumps(outer, ensure_ascii=False, indent=1).encode("utf-8"), fname


def read_backup_bytes(data: bytes, password: str) -> dict:
    """암호화된 백업 파일 → 내용(dict). 실패하면 BackupError"""
    if not crypto_available():
        raise BackupError("암호화 부품(cryptography)이 설치되어 있지 않습니다. requirements.txt에 cryptography를 추가하세요.")
    try:
        outer = json.loads(data.decode("utf-8"))
    except Exception:
        raise BackupError("이 계산기에서 만든 백업 파일이 아닙니다.")
    if not isinstance(outer, dict) or outer.get("format") != FORMAT_ID:
        raise BackupError("이 계산기에서 만든 백업 파일이 아닙니다.")
    if int(outer.get("version") or 0) > FORMAT_VERSION:
        raise BackupError("더 새로운 버전의 계산기에서 만든 백업입니다. 계산기를 최신으로 업데이트한 뒤 여세요.")

    from cryptography.fernet import InvalidToken
    try:
        salt = base64.b64decode(outer["salt"])
        plain = _fernet(password or "", salt).decrypt(outer["data"].encode("ascii"))
    except InvalidToken:
        raise BackupError("비밀번호가 맞지 않거나 파일이 손상되었습니다.")
    except Exception:
        raise BackupError("백업 파일 형식이 올바르지 않습니다.")

    inner = json.loads(plain.decode("utf-8"))
    if not isinstance(inner, dict) or not isinstance(inner.get("state"), dict):
        raise BackupError("백업 파일 내용이 올바르지 않습니다.")
    return _upgrade(inner)


def _upgrade(inner: dict) -> dict:
    """예전 버전 백업을 지금 구조로 맞춤 (버전이 올라가면 여기에 변환 추가)"""
    st_ = inner["state"]
    # JSON에서 문자열이 된 연도 키를 숫자로 복원
    yr = st_.get("year_recs") or {}
    if isinstance(yr, dict):
        st_["year_recs"] = {(int(k) if str(k).isdigit() else k): v for k, v in yr.items()}
    if isinstance(st_.get("manual_extra_years"), list):
        st_["manual_extra_years"] = [int(y) for y in st_["manual_extra_years"] if str(y).isdigit()]
    return inner
