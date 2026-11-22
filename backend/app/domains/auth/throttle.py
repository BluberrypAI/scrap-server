"""비밀번호 로그인 실패 제한 (무차별 대입·비밀번호 스프레이 방어).

최근 WINDOW_SECONDS 동안의 실패 횟수를 아이디별, 접속 IP별로 센다. 어느 한쪽이라도 한도에
닿으면 창이 지날 때까지 그 아이디·IP의 로그인을 429로 막는다(맞는 비밀번호여도 막음).
로그인에 성공하면 그 아이디의 기록만 지운다(IP 기록은 남겨 여러 아이디 대입을 계속 막음).

프로세스 메모리에 두므로 인스턴스마다 따로 세고, 재시작하면 초기화된다(운영 App Service는 1대).
"""

import math
import time
from collections import deque

from fastapi import Request

WINDOW_SECONDS = 15 * 60
MAX_FAILURES_PER_LOGIN = 10
MAX_FAILURES_PER_IP = 30
# 임의 아이디를 계속 바꿔 보내 메모리를 늘리는 것을 막는 상한. 넘으면 오래된 키부터 정리함
MAX_TRACKED_KEYS = 10_000

_failures: dict[str, deque[float]] = {}


def client_ip(request: Request) -> str:
    """Front Door가 넣는 X-Azure-ClientIP를 먼저 씀. 앱은 Front Door·VNet으로만 열려 있음."""
    forwarded = request.headers.get("x-azure-clientip", "").strip()
    if forwarded:
        return forwarded
    return request.client.host if request.client else "unknown"


def _keys(login_id: str, ip: str) -> tuple[tuple[str, int], tuple[str, int]]:
    return (f"login:{login_id}", MAX_FAILURES_PER_LOGIN), (f"ip:{ip}", MAX_FAILURES_PER_IP)


def _recent(key: str, now: float) -> deque[float]:
    hits = _failures.get(key)
    if hits is None:
        return deque()
    while hits and now - hits[0] >= WINDOW_SECONDS:
        hits.popleft()
    if not hits:
        del _failures[key]
    return hits


def retry_after(login_id: str, ip: str, now: float | None = None) -> int | None:
    """막혀 있으면 다시 시도할 수 있을 때까지 남은 초, 아니면 None."""
    now = time.monotonic() if now is None else now
    waits = []
    for key, limit in _keys(login_id, ip):
        hits = _recent(key, now)
        if len(hits) >= limit:
            waits.append(hits[len(hits) - limit] + WINDOW_SECONDS - now)
    return max(1, math.ceil(max(waits))) if waits else None


def record_failure(login_id: str, ip: str, now: float | None = None) -> None:
    now = time.monotonic() if now is None else now
    if len(_failures) >= MAX_TRACKED_KEYS:
        for key in list(_failures):
            _recent(key, now)
        while len(_failures) >= MAX_TRACKED_KEYS:
            del _failures[next(iter(_failures))]
    for key, _ in _keys(login_id, ip):
        _failures.setdefault(key, deque()).append(now)


def record_success(login_id: str) -> None:
    _failures.pop(f"login:{login_id}", None)


def reset() -> None:
    """테스트용: 모든 기록을 지움."""
    _failures.clear()
