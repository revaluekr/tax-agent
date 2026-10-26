# -*- coding: utf-8 -*-
"""
통합고용세액공제 계산기 — 작업 상태 암호화 백업/복원 모듈

[왜 이 방식을 쓰는가]
- Streamlit Cloud(무료 호스팅)는 앱이 재시작되면 서버 디스크(`.workspace_storage/`)가 초기화됩니다.
- 세무 자료(원천징수부·사원 명부)는 개인정보가 들어 있으므로, 외부 클라우드 DB 대신
  **사용자 PC에 비밀번호로 암호화된 단일 파일(.ecbak)로 내려받아 보관**하고
  다음에 접속해 다시 올려 이어서 작업하는 방식이 가장 안전하고 비용도 들지 않습니다.

[암호화 규격]
- 키 파생 : PBKDF2-HMAC-SHA256, 16바이트 무작위 솔트, 390,000회 반복 (OWASP 권고 수준)
- 대칭키 암호: cryptography.Fernet (AES-128-CBC + HMAC-SHA256 인증 암호화, 변조 자동 감지)
- 압축    : zlib (사원 100명 기준 보통 수십 KB로 줄어듦)
- 개인정보 최소화: 업로드했던 서류의 **원문 텍스트(`files[*].text`)는 백업에 넣지 않고**
  추출·검토가 끝난 사원표·설정·기신고 기초값만 저장합니다. 혹시 남아 있을 수 있는
  13자리 주민등록번호 패턴은 백업 전에 한 번 더 마스킹합니다.
"""
from __future__ import annotations

import base64
import copy
import datetime
import json
import os
import re
import zlib

try:
    from cryptography.fernet import Fernet, InvalidToken
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    _CRYPTO_OK = True
except Exception:  # pragma: no cover - 라이브러리 미설치 환경 대비
    _CRYPTO_OK = False
    InvalidToken = Exception  # type: ignore

MAGIC = b"ECBK1\n"          # 파일 식별 헤더 (버전 1)
SALT_LEN = 16
KDF_ITERS = 390_000
MIN_PASSWORD_LEN = 6
FILE_EXT = "ecbak"

_RRN_FULL_RE = re.compile(r"(?<!\d)(\d{6})\s*-\s*([1-8])\d{6}(?!\d)")

# ui.py의 _PERSIST_KEYS와 맞추되, 복원에 필요한 작업 상태 키를 모두 포함
BACKUP_KEYS = (
    "tax_year",
    "step",
    "max_step_reached",
    "max_step_reached",
    "biz",
    "sub_biz_list",
    "files",
    "ext_sig",
    "ext",
    "people",
    "year_recs",
    "prev_summary",
    "additional_inputs",
    "scheme_2026",
    "pm_basis",
    "_pm_basis_user_touched",
    "assume_year_end",
    "use_year_tabs",
    "_tabs_user_touched",
    "manual_extra_years",
    "built_sig",
    "fill_ver",
    "pro_audit_comment",
    "pro_audit_model",
    "pro_audit_sig",
    "biz_confirmed",
    "include_unpaid_hire_month",
    "show_all_4_blocks",
    "show_empty_pm_blocks",
    "next_pid_seq",
)


class BackupError(ValueError):
    """백업 생성·복원 중 사용자에게 그대로 안내할 수 있는 오류"""


def crypto_available() -> bool:
    return _CRYPTO_OK


def _derive_fernet_key(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=KDF_ITERS,
    )
    return base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))


def _mask_rrn_deep(obj):
    if isinstance(obj, str):
        return _RRN_FULL_RE.sub(r"\1-\2******", obj)
    if isinstance(obj, dict):
        return {k: _mask_rrn_deep(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_mask_rrn_deep(v) for v in obj]
    return obj


def _sanitize_state_for_backup(s: dict) -> dict:
    """
    백업 파일에 담을 상태를 추려냅니다.
    - 업로드 서류 원문(`files[*].text`)은 용량도 크고 원천징수부 전체 텍스트가 들어 있으므로 비웁니다.
      대신 파일명·분류·사업장 배정 정보만 남겨 1단계 목록에서 어떤 서류로 작업했는지 확인할 수 있게 합니다.
    """
    payload = {}
    for k in BACKUP_KEYS:
        if k in s:
            payload[k] = copy.deepcopy(s[k])

    if isinstance(payload.get("files"), dict):
        slim_files = {}
        for name, meta in payload["files"].items():
            if isinstance(meta, dict):
                slim_files[name] = {
                    "key": meta.get("key"),
                    "label": meta.get("label"),
                    "wp": meta.get("wp", ""),
                    "text": "",                  # 원문 미포함 (사원표는 people/year_recs에 이미 반영됨)
                    "restored": True,
                }
        payload["files"] = slim_files

    return _mask_rrn_deep(payload)


def make_backup_bytes(state: dict, password: str) -> tuple[bytes, str]:
    """
    현재 계산기 상태(`state`)를 비밀번호로 암호화해 `(파일 바이트, 권장 파일명)`으로 돌려줍니다.
    """
    if not _CRYPTO_OK:
        raise BackupError("암호화 라이브러리(cryptography)가 설치되어 있지 않아 백업 파일을 만들 수 없습니다.")
    pw = (password or "").strip()
    if len(pw) < MIN_PASSWORD_LEN:
        raise BackupError(f"백업 비밀번호는 {MIN_PASSWORD_LEN}자 이상 입력해 주세요.")

    clean_state = _sanitize_state_for_backup(state or {})
    corp = str((clean_state.get("biz") or {}).get("상호") or "미입력사업장").strip()
    tax_yr = int(clean_state.get("tax_year") or 2026)
    saved_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    envelope = {
        "version": 1,
        "saved_at": saved_at,
        "tax_year": tax_yr,
        "상호": corp,
        "people_count": len(clean_state.get("people") or {}),
        "state": clean_state,
    }
    raw_json = json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    compressed = zlib.compress(raw_json, level=6)

    salt = os.urandom(SALT_LEN)
    token = Fernet(_derive_fernet_key(pw, salt)).encrypt(compressed)
    blob = MAGIC + salt + token

    safe_corp = re.sub(r'[\\/:*?"<>|\s]+', "_", corp)[:30] or "사업장"
    today = datetime.date.today().strftime("%Y%m%d")
    filename = f"통합고용세액공제_{safe_corp}_{tax_yr}귀속_{today}.{FILE_EXT}"
    return blob, filename


def read_backup_bytes(blob: bytes, password: str) -> dict:
    """
    암호화된 백업 바이트(`blob`)를 복호화해 `{"version", "saved_at", "tax_year", "상호", "people_count", "state"}` 사전을 돌려줍니다.
    비밀번호가 틀리거나 파일이 손상되었으면 `BackupError`를 일으킵니다.
    """
    if not _CRYPTO_OK:
        raise BackupError("암호화 라이브러리(cryptography)가 설치되어 있지 않아 백업 파일을 열 수 없습니다.")
    if not blob or not blob.startswith(MAGIC) or len(blob) <= len(MAGIC) + SALT_LEN:
        raise BackupError("올바른 통합고용세액공제 백업 파일(.ecbak)이 아닙니다.")
    pw = (password or "").strip()
    if not pw:
        raise BackupError("백업 파일을 만들 때 설정한 비밀번호를 입력해 주세요.")

    salt = blob[len(MAGIC): len(MAGIC) + SALT_LEN]
    token = blob[len(MAGIC) + SALT_LEN:]
    try:
        compressed = Fernet(_derive_fernet_key(pw, salt)).decrypt(token)
    except InvalidToken:
        raise BackupError("비밀번호가 맞지 않거나 백업 파일이 손상되었습니다.")
    except Exception as e:
        raise BackupError(f"백업 복호화 실패: {e}")

    try:
        inner = json.loads(zlib.decompress(compressed).decode("utf-8"))
    except Exception as e:
        raise BackupError(f"백업 데이터 해석 실패: {e}")

    if not isinstance(inner, dict) or not isinstance(inner.get("state"), dict):
        raise BackupError("백업 파일 내부 구조가 올바르지 않습니다.")
    return inner