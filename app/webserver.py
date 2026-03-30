from __future__ import annotations

import html as html_module
import logging
import time

from aiohttp import web

from app.data import IPRegistry
from app.tokens import TokenStore

logger = logging.getLogger(__name__)

_CONFIRM_HTML = """<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <title>IP 등록 확인</title>
  <style>
    body {{ font-family: sans-serif; text-align: center; padding: 60px; background: #f0f4f8; }}
    .card {{ display: inline-block; background: white; padding: 40px 60px;
             border-radius: 12px; box-shadow: 0 2px 12px rgba(0,0,0,.1); }}
    h2 {{ color: #2563eb; }}
    .info {{ margin: 20px 0; color: #555; }}
    button {{ background: #2563eb; color: white; border: none; padding: 14px 40px;
             border-radius: 8px; font-size: 1.1em; cursor: pointer; }}
    button:hover {{ background: #1d4ed8; }}
    .note {{ margin-top: 24px; color: #888; font-size: .9em; }}
  </style>
</head>
<body>
  <div class="card">
    <h2>🔗 IP 자동 등록</h2>
    <p class="info">현재 접속 IP를 등록합니다.<br>아래 버튼을 눌러 진행하세요.</p>
    <form method="POST" action="/ip/claim">
      <input type="hidden" name="token" value="{token}">
      <button type="submit">등록하기</button>
    </form>
    <p class="note">이 링크는 1회만 사용할 수 있습니다.</p>
  </div>
</body>
</html>"""

_SUCCESS_HTML = """<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <title>IP 등록 완료</title>
  <style>
    body {{ font-family: sans-serif; text-align: center; padding: 60px; background: #f0f4f8; }}
    .card {{ display: inline-block; background: white; padding: 40px 60px;
             border-radius: 12px; box-shadow: 0 2px 12px rgba(0,0,0,.1); }}
    h2 {{ color: #2d7d46; }} table {{ margin: 20px auto; border-collapse: collapse; }}
    td {{ padding: 6px 16px; text-align: left; }} td:first-child {{ color: #666; }}
    .note {{ margin-top: 24px; color: #888; font-size: .9em; }}
  </style>
</head>
<body>
  <div class="card">
    <h2>✅ IP 등록 완료</h2>
    <table>
      <tr><td>IP 주소</td><td><strong>{ip}</strong></td></tr>
      <tr><td>기기 이름</td><td>{device}</td></tr>
      <tr><td>사람 이름</td><td>{person}</td></tr>
      <tr><td>등록 방식</td><td>자동 (auto)</td></tr>
    </table>
    <p class="note">이 창을 닫아도 됩니다.</p>
  </div>
</body>
</html>"""

_ERROR_HTML = """<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <title>오류</title>
  <style>
    body {{ font-family: sans-serif; text-align: center; padding: 60px; background: #f0f4f8; }}
    .card {{ display: inline-block; background: white; padding: 40px 60px;
             border-radius: 12px; box-shadow: 0 2px 12px rgba(0,0,0,.1); }}
    h2 {{ color: #c0392b; }}
  </style>
</head>
<body>
  <div class="card">
    <h2>❌ 오류</h2>
    <p>{message}</p>
  </div>
</body>
</html>"""


class RateLimiter:
    """IP별 슬라이딩 윈도우 rate limiter."""

    def __init__(self, window: int, max_requests: int) -> None:
        self._window = window
        self._max = max_requests
        self._hits: dict[str, list[float]] = {}
        self._last_cleanup = time.monotonic()

    def is_allowed(self, ip: str) -> bool:
        now = time.monotonic()
        # 5분마다 오래된 항목 정리 (메모리 누수 방지)
        if now - self._last_cleanup > 300:
            self._cleanup(now)
        cutoff = now - self._window
        timestamps = self._hits.get(ip)
        if timestamps is not None:
            timestamps[:] = [t for t in timestamps if t > cutoff]
        else:
            timestamps = []
            self._hits[ip] = timestamps
        if len(timestamps) >= self._max:
            return False
        timestamps.append(now)
        return True

    def _cleanup(self, now: float) -> None:
        cutoff = now - self._window
        dead = [ip for ip, ts in self._hits.items() if not ts or ts[-1] <= cutoff]
        for ip in dead:
            del self._hits[ip]
        self._last_cleanup = now


def create_web_app(
    registry: IPRegistry,
    token_store: TokenStore,
    ip_prefix: str,
    rate_limit_window: int = 60,
    rate_limit_max: int = 10,
) -> web.Application:
    app = web.Application()
    app["registry"] = registry
    app["token_store"] = token_store
    app["ip_prefix"] = ip_prefix
    app["rate_limiter"] = RateLimiter(rate_limit_window, rate_limit_max)
    app.router.add_get("/ip/claim", handle_claim_get)
    app.router.add_post("/ip/claim", handle_claim_post)
    app.router.add_get("/health", handle_health)
    return app


async def handle_health(request: web.Request) -> web.Response:
    return web.Response(text="ok")


async def handle_claim_get(request: web.Request) -> web.Response:
    """GET: 확인 폼을 렌더링한다. 상태 변경 없음, 토큰 소비 안 함."""
    token_store: TokenStore = request.app["token_store"]

    token_str = request.rel_url.query.get("token", "").strip()
    if not token_str:
        return _err("토큰이 없습니다.", 400)

    # 토큰 존재·유효 여부만 확인 (소비하지 않음)
    if not token_store.peek(token_str):
        return _err("토큰이 만료되었거나 이미 사용된 토큰입니다.", 400)

    html = _CONFIRM_HTML.format(token=html_module.escape(token_str))
    return _html_response(html)


async def handle_claim_post(request: web.Request) -> web.Response:
    """POST: 토큰을 소비하고 IP를 등록한다."""
    rate_limiter: RateLimiter = request.app["rate_limiter"]
    client_ip_for_rl = (request.remote or "").strip()
    if not rate_limiter.is_allowed(client_ip_for_rl):
        logger.warning(f"Rate limit 초과: {client_ip_for_rl}")
        return _err("요청이 너무 많습니다. 잠시 후 다시 시도하세요.", 429)

    registry: IPRegistry = request.app["registry"]
    token_store: TokenStore = request.app["token_store"]
    ip_prefix: str = request.app["ip_prefix"]

    # POST body에서 토큰 추출
    try:
        form = await request.post()
    except Exception:
        return _err("잘못된 요청입니다.", 400)

    token_str = form.get("token", "")
    if isinstance(token_str, str):
        token_str = token_str.strip()
    else:
        token_str = ""

    if not token_str:
        return _err("토큰이 없습니다.", 400)

    token = token_store.consume(token_str)
    if token is None:
        return _err("토큰이 만료되었거나 이미 사용된 토큰입니다.", 400)

    # 클라이언트 IP 추출 (프록시 헤더 무시 — 직접 연결만 신뢰)
    client_ip = (request.remote or "").strip()

    if not client_ip:
        return _err("IP 주소를 확인할 수 없습니다.", 400)

    # 서브넷 검증
    parts = client_ip.split(".")
    if len(parts) != 4 or ".".join(parts[:3]) != ip_prefix:
        return _err(
            f"허용되지 않는 IP 주소입니다: {html_module.escape(client_ip)}<br>"
            f"허용 대역: {html_module.escape(ip_prefix)}.1 ~ {html_module.escape(ip_prefix)}.254",
            403,
        )

    success, message = registry.register(
        user_id=token.discord_user_id,
        username=token.discord_username,
        display_name=token.discord_display_name,
        address=client_ip,
        device_label=token.device_label,
        person_name=token.person_name,
        source="auto",
    )

    if not success:
        return _err(message, 409)

    logger.info(
        f"Auto claim: {client_ip} ← discord_user={token.discord_user_id} "
        f"device={token.device_label!r} person={token.person_name!r}"
    )

    html = _SUCCESS_HTML.format(
        ip=html_module.escape(client_ip),
        device=html_module.escape(token.device_label or "(미지정)"),
        person=html_module.escape(token.person_name or "(미지정)"),
    )
    return _html_response(html)


def _html_response(html: str, status: int = 200) -> web.Response:
    return web.Response(
        text=html,
        content_type="text/html",
        status=status,
        headers={"X-Frame-Options": "DENY"},
    )


def _err(message: str, status: int) -> web.Response:
    return web.Response(
        text=_ERROR_HTML.format(message=message),
        content_type="text/html",
        status=status,
        headers={"X-Frame-Options": "DENY"},
    )
