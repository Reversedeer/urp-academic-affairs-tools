"""登录流程共享的常量和辅助函数。"""

import re
from urllib.parse import parse_qs, urlparse

from .errors import AuthError

BASE_URL = "https://jws.qgxy.cn"
LOGIN_PAGE = f"{BASE_URL}/login"
LOGIN_URL = f"{BASE_URL}/j_spring_security_check"
CAPTCHA_URL = f"{BASE_URL}/img/captcha.jpg"
INDEX_URL = f"{BASE_URL}/index.jsp"

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


def extract_token_value(html: str) -> str:
    """从教务系统 HTML 表单中提取 ``tokenValue``。"""
    for pattern in TOKEN_PATTERNS:
        match = pattern.search(html)
        if match is not None:
            return match.group(1)
    msg = "page does not contain tokenValue"
    raise AuthError(msg)


def extract_error_code(*values: str) -> str:
    """从重定向地址或响应文本中提取 ``errorCode``。"""
    for value in values:
        parsed = urlparse(value)
        query = parsed.query or value
        error_codes = parse_qs(query).get("errorCode", [])
        if error_codes:
            return error_codes[0]
    return ""
