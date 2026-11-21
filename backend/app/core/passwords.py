"""비밀번호 해시. 의존성 없이 표준 라이브러리 scrypt를 씀.

저장 형식: scrypt$<n>$<r>$<p>$<salt b64>$<hash b64>
매개변수를 함께 저장해서 나중에 강도를 올려도 기존 해시를 검증할 수 있음.
"""

import base64
import hashlib
import hmac
import secrets

_N, _R, _P = 2**14, 8, 1
_DKLEN = 32
_SCHEME = "scrypt"
# 비밀번호 길이 하한·상한. 상한은 해시 계산 비용을 묶어 둠
MIN_LENGTH = 8
MAX_LENGTH = 128


def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(
        password.encode(), salt=salt, n=n, r=r, p=p, dklen=_DKLEN, maxmem=64 * 1024 * 1024
    )


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = _derive(password, salt, _N, _R, _P)
    b64 = base64.b64encode
    return f"{_SCHEME}${_N}${_R}${_P}${b64(salt).decode()}${b64(digest).decode()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored or len(password) > MAX_LENGTH:
        return False
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != _SCHEME:
            return False
        expected = base64.b64decode(digest)
        actual = _derive(password, base64.b64decode(salt), int(n), int(r), int(p))
    except ValueError:
        return False
    return hmac.compare_digest(actual, expected)


# 없는 아이디에도 같은 시간만큼 계산해서 응답 시간으로 계정 존재 여부가 드러나지 않게 함
DUMMY_HASH = hash_password(secrets.token_urlsafe(16))
