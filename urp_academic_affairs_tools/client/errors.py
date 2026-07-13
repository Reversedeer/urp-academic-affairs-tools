"""客户端层共享异常类型。"""

from enum import Enum


class AuthenticationFailure(str, Enum):
    SESSION_EXPIRED = "sessionExpired"
    CONCURRENT_SESSION_EXPIRED = "concurrentSessionExpired"
    LOGIN_REDIRECT = "loginRedirect"
    CSRF_TOKEN_EXPIRED = "csrfTokenExpired"


class AuthError(Exception):
    """登录或验证码处理失败"""


class InvalidCredentialsError(AuthError):
    """账号或密码错误"""


class ServiceError(Exception):
    """教务系统返回异常响应"""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.retryable = retryable


class SessionExpiredError(Exception):
    """请求被重定向至登录页"""

    def __init__(
        self,
        message: str,
        *,
        reason: AuthenticationFailure = AuthenticationFailure.SESSION_EXPIRED,
        error_code: str = "",
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.error_code = error_code


class ConcurrentSessionExpiredError(SessionExpiredError):
    """账号在其他位置登录，导致当前服务端会话失效"""

    def __init__(self) -> None:
        super().__init__(
            "account was logged in elsewhere; the current session expired",
            reason=AuthenticationFailure.CONCURRENT_SESSION_EXPIRED,
            error_code="concurrentSessionExpired",
        )


class CsrfTokenExpiredError(SessionExpiredError):
    """请求携带的 CSRF/tokenValue 已被服务端拒绝"""

    def __init__(self) -> None:
        super().__init__(
            "the request CSRF token expired or was rejected",
            reason=AuthenticationFailure.CSRF_TOKEN_EXPIRED,
        )
