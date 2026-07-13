"""登录、登出与会话管理相关的工具函数"""

import re
from urllib.parse import parse_qs, urlparse

from .errors import AuthenticationFailure, AuthError

TOKEN_PATTERNS = (
    re.compile(
        r'name\s*=\s*["\']tokenValue["\'][^>]*'
        r'value\s*=\s*["\']([^"\']+)["\']',
        re.IGNORECASE,
    ),
    re.compile(
        r'value\s*=\s*["\']([^"\']+)["\'][^>]*'
        r'name\s*=\s*["\']tokenValue["\']',
        re.IGNORECASE,
    ),
)

CSRF_FAILURE_MARKERS = (
    "csrf token",
    "csrf_token",
    "invalid csrf",
    "tokenvalue invalid",
    "tokenvalue expired",
    "tokenvalue无效",
    "tokenvalue已失效",
    "令牌无效",
    "令牌已失效",
)


def extract_token_value(html: str) -> str:
    """提取tokenValue"""
    for pattern in TOKEN_PATTERNS:
        match = pattern.search(html)
        if match is not None:
            return match.group(1)
    msg = "page does not contain tokenValue"
    raise AuthError(msg)


def extract_error_code(*values: str) -> str:
    """提取服务端返回的 errorCode"""
    for value in values:
        parsed = urlparse(value)
        query = parsed.query or value
        error_codes = parse_qs(query).get("errorCode", [])
        if error_codes:
            return error_codes[0]
    return ""


def classify_authentication_failure(
    *,
    status: int,
    response_url: str,
    redirect_locations: tuple[str, ...] = (),
    text: str = "",
) -> AuthenticationFailure | None:
    """从 HTTP 状态、重定向链与响应内容统一识别认证失败"""
    values = (response_url, *redirect_locations, text)
    error_code = extract_error_code(*values)
    if error_code == AuthenticationFailure.CONCURRENT_SESSION_EXPIRED.value:
        return AuthenticationFailure.CONCURRENT_SESSION_EXPIRED

    lowered_values = " ".join(values).lower()
    lowered_redirects = " ".join((response_url, *redirect_locations)).lower()
    if any(marker in lowered_values for marker in CSRF_FAILURE_MARKERS):
        return AuthenticationFailure.CSRF_TOKEN_EXPIRED
    if "/login" in lowered_redirects or "gotologin" in lowered_values:
        return AuthenticationFailure.LOGIN_REDIRECT
    if status in {401, 403}:
        return AuthenticationFailure.SESSION_EXPIRED
    return None
