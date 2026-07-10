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
