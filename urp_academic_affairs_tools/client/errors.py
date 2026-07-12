"""客户端层共享异常类型。"""


class AuthError(Exception):
    """登录或验证码处理失败。"""


class InvalidCredentialsError(AuthError):
    """账号或密码错误。"""


class ServiceError(Exception):
    """教务系统返回异常响应。"""

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
    """请求被重定向至登录页。"""

    def __init__(self, message: str, *, error_code: str = "") -> None:
        super().__init__(message)
        self.error_code = error_code


class ConcurrentSessionExpiredError(SessionExpiredError):
    """账号在其他位置登录，导致当前服务端会话失效。"""

    def __init__(self) -> None:
        super().__init__(
            "account was logged in elsewhere; the current session expired",
            error_code="concurrentSessionExpired",
        )
