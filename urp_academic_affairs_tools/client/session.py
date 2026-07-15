"""异步教务系统会话、登录与请求重试"""

import asyncio
import hashlib
import json as json_module
import logging
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import TracebackType
from typing import TYPE_CHECKING, Any, Generic, TypeVar, cast

import aiohttp

if TYPE_CHECKING:
    from typing_extensions import Self

from .auth import (
    classify_authentication_failure,
    extract_error_code,
    extract_token_value,
)
from .captcha import (
    CAPTCHA_RE,
    CaptchaRecognizer,
    CaptchaSolver,
    verify_image_bytes,
)
from .errors import (
    AuthenticationFailure,
    AuthError,
    ConcurrentSessionExpiredError,
    CsrfTokenExpiredError,
    InvalidCredentialsError,
    ServiceError,
    SessionExpiredError,
)

HTTP_STATUS_OK = 200
HTTP_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
RETRYABLE_STATUS_CODES = frozenset({429, 502, 503, 504})
IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})

log = logging.getLogger(__name__)
_RANDOM = secrets.SystemRandom()
_T = TypeVar("_T")


ResponseDecoder = Callable[[str], _T]
RequestParams = Mapping[str, str | int | float]


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """普通请求的指数退避策略"""

    max_retry: int = 3
    base_sleep: float = 0.2
    max_sleep: float = 1.5
    jitter: float = 0.2

    def __post_init__(self) -> None:
        if self.max_retry < 1:
            msg = "max_retry must be at least 1"
            raise ValueError(msg)
        if min(self.base_sleep, self.max_sleep, self.jitter) < 0:
            msg = "retry delays cannot be negative"
            raise ValueError(msg)
        if self.max_sleep < self.base_sleep:
            msg = "max_sleep cannot be less than base_sleep"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class SessionOptions:
    """会话连接和登录配置"""

    timeout_total: float = 10.0
    timeout_connect: float = 3.0
    connector_limit: int = 20
    login_attempts: int = 0
    max_redirects: int = 10
    login_retry_sleep: float = 0.2
    login_retry_jitter: float = 0.15

    def __post_init__(self) -> None:
        if min(self.timeout_total, self.timeout_connect) <= 0:
            msg = "timeouts must be positive"
            raise ValueError(msg)
        if min(self.connector_limit, self.max_redirects) < 1:
            msg = "session limits must be at least 1"
            raise ValueError(msg)
        if self.login_attempts < 0:
            msg = "login_attempts cannot be negative"
            raise ValueError(msg)
        if min(self.login_retry_sleep, self.login_retry_jitter) < 0:
            msg = "login retry delays cannot be negative"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class _RequestSpec:
    method: str
    url: str
    params: RequestParams | None = None
    data: object | None = None
    json_data: object | None = None
    headers: Mapping[str, str] | None = None
    allow_redirects: bool = True


@dataclass(frozen=True, slots=True)
class _AttemptResult(Generic[_T]):
    value: _T | None = None
    error: Exception | None = None


class AsyncJWSSession:
    """维护教务系统 Cookie"""

    def __init__(
        self,
        base_url: str,
        *,
        options: SessionOptions | None = None,
        retry: RetryPolicy | None = None,
        captcha_solver: CaptchaSolver | None = None,
        cookie_jar: aiohttp.CookieJar | None = None,
    ) -> None:
        normalized_base_url = base_url.rstrip("/")
        if not normalized_base_url.startswith(("http://", "https://")):
            msg = "base_url must start with http:// or https://"
            raise ValueError(msg)

        self.base_url = normalized_base_url
        self.login_page = f"{self.base_url}/login"
        self.login_url = f"{self.base_url}/j_spring_security_check"
        self.captcha_url = f"{self.base_url}/img/captcha.jpg"
        self.index_url = f"{self.base_url}/index.jsp"

        self.options = options or SessionOptions()
        self.retry = retry or RetryPolicy()
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            "Referer": self.login_page,
        }

        self._session: aiohttp.ClientSession | None = None
        self._credentials: tuple[str, str] | None = None
        self._captcha_solver = captcha_solver
        self._captcha_recognizer: CaptchaRecognizer | None = None
        self._login_lock = asyncio.Lock()
        self._cookie_jar = cookie_jar
        self._on_reauthenticated: Callable[[], None] | None = None
        self._on_session_expired: Callable[[AuthenticationFailure], None] | None = None

    @property
    def started(self) -> bool:
        return self._session is not None and not self._session.closed

    def set_reauthentication_callback(
        self,
        callback: Callable[[], None] | None,
    ) -> None:
        self._on_reauthenticated = callback

    def set_session_expired_callback(
        self,
        callback: Callable[[AuthenticationFailure], None] | None,
    ) -> None:
        self._on_session_expired = callback

    async def start(self) -> None:
        if self.started:
            return

        timeout = aiohttp.ClientTimeout(
            total=self.options.timeout_total,
            connect=self.options.timeout_connect,
        )
        connector = aiohttp.TCPConnector(
            limit=self.options.connector_limit,
            ttl_dns_cache=300,
        )
        self._session = aiohttp.ClientSession(
            timeout=timeout,
            connector=connector,
            cookie_jar=self._cookie_jar,
            headers=self.headers,
            raise_for_status=False,
        )

    async def close(self) -> None:
        session = self._session
        self._session = None
        self._credentials = None
        if session is not None and not session.closed:
            await session.close()

    async def __aenter__(self) -> "Self":
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()

    def _require_session(self) -> aiohttp.ClientSession:
        if not self.started or self._session is None:
            msg = "session has not been started"
            raise RuntimeError(msg)
        return self._session

    @staticmethod
    def _md5(text: str) -> str:
        return hashlib.md5(
            text.encode("utf-8"),
            usedforsecurity=False,
        ).hexdigest()

    @staticmethod
    def _extract_token(html: str) -> str:
        return extract_token_value(html)

    @staticmethod
    def check_login_page(text: str) -> bool:
        lowered = text.lower()
        has_login_form = (
            "tokenvalue" in lowered and "j_spring_security_check" in lowered
        )
        return has_login_form or "gotologin" in lowered

    @staticmethod
    def _is_login_redirect(location: str | None) -> bool:
        lowered = (location or "").lower()
        return "gotologin" in lowered or "/login" in lowered

    @staticmethod
    def _authentication_error(
        reason: AuthenticationFailure,
        *values: str,
    ) -> SessionExpiredError:
        error_code = extract_error_code(*values)
        if reason is AuthenticationFailure.CONCURRENT_SESSION_EXPIRED:
            return ConcurrentSessionExpiredError()
        if reason is AuthenticationFailure.CSRF_TOKEN_EXPIRED:
            return CsrfTokenExpiredError()
        return SessionExpiredError(
            "request was redirected to the login page",
            reason=reason,
            error_code=error_code,
        )

    def _notify_session_expired(self, error: SessionExpiredError) -> None:
        if self._on_session_expired is not None:
            self._on_session_expired(error.reason)

    def _build_url(self, path: str) -> str:
        if path.startswith(("http://", "https://")):
            return path
        suffix = path if path.startswith("/") else f"/{path}"
        return f"{self.base_url}{suffix}"

    async def _sleep_login_retry(self) -> None:
        delay = self.options.login_retry_sleep
        if self.options.login_retry_jitter:
            delay += _RANDOM.uniform(0, self.options.login_retry_jitter)
        if delay:
            await asyncio.sleep(delay)

    @staticmethod
    async def _sleep_request_retry(attempt: int, policy: RetryPolicy) -> None:
        delay = min(
            policy.max_sleep,
            policy.base_sleep * (2 ** (attempt - 1)),
        )
        if policy.jitter:
            delay += _RANDOM.uniform(0, policy.jitter)
        if delay:
            await asyncio.sleep(delay)

    async def _load_login_token(self) -> str:
        session = self._require_session()
        async with session.get(
            self.login_page,
            allow_redirects=True,
            max_redirects=self.options.max_redirects,
        ) as response:
            html = await response.text(errors="ignore")
            if response.status != HTTP_STATUS_OK:
                msg = f"login page returned status {response.status}"
                raise ServiceError(
                    msg,
                    status=response.status,
                    retryable=response.status in RETRYABLE_STATUS_CODES,
                )
        return self._extract_token(html)

    async def _fetch_captcha_image(self) -> bytes:
        session = self._require_session()
        async with session.get(
            self.captcha_url,
            allow_redirects=True,
            max_redirects=self.options.max_redirects,
        ) as response:
            content_type = response.headers.get("Content-Type", "").lower()
            image_bytes = await response.read()
            if response.status != HTTP_STATUS_OK:
                msg = f"captcha endpoint returned status {response.status}"
                raise ServiceError(
                    msg,
                    status=response.status,
                    retryable=response.status in RETRYABLE_STATUS_CODES,
                )

        if not content_type.startswith("image/"):
            msg = "captcha endpoint did not return an image"
            raise AuthError(msg)
        if not await asyncio.to_thread(verify_image_bytes, image_bytes):
            msg = "captcha endpoint returned invalid image data"
            raise AuthError(msg)
        return image_bytes

    async def _submit_login(
        self,
        username: str,
        password: str,
        token: str,
        captcha: str,
    ) -> None:
        session = self._require_session()
        form = {
            "tokenValue": token,
            "j_username": username,
            "j_password": self._md5(password),
            "j_captcha": captcha,
        }
        async with session.post(
            self.login_url,
            data=form,
            allow_redirects=False,
        ) as response:
            text = await response.text(errors="ignore")
            error_code = extract_error_code(
                response.headers.get("Location", ""),
                text,
            )
            if error_code == "badCredentials":
                msg = "username or password was rejected"
                raise InvalidCredentialsError(msg)
            if error_code == "badCaptcha":
                msg = "captcha was rejected"
                raise AuthError(msg)
            if response.status in RETRYABLE_STATUS_CODES:
                msg = f"login endpoint returned status {response.status}"
                raise ServiceError(
                    msg,
                    status=response.status,
                    retryable=True,
                )
            if response.status >= 400:  # noqa: PLR2004
                msg = f"login endpoint returned status {response.status}"
                raise AuthError(msg)

    async def is_logged_in(self) -> bool:
        """请求首页并判断服务器端会话是否仍然有效"""
        session = self._require_session()
        async with session.get(
            self.index_url,
            allow_redirects=False,
        ) as response:
            if response.status == HTTP_STATUS_OK:
                text = await response.text(errors="ignore")
                if self.check_login_page(text):
                    error = self._authentication_error(
                        AuthenticationFailure.LOGIN_REDIRECT,
                        str(response.url),
                        text,
                    )
                    self._notify_session_expired(error)
                    return False
                return True
            await response.read()
            if response.status in HTTP_REDIRECT_STATUSES:
                location = response.headers.get("Location", "")
                if self._is_login_redirect(location):
                    reason = (
                        classify_authentication_failure(
                            status=response.status,
                            response_url=str(response.url),
                            redirect_locations=(location,),
                        )
                        or AuthenticationFailure.LOGIN_REDIRECT
                    )
                    error = self._authentication_error(reason, location)
                    self._notify_session_expired(error)
                    return False
                return True
            if response.status in {401, 403}:
                return False
            if response.status >= 400:  # noqa: PLR2004
                msg = f"session check returned status {response.status}"
                raise ServiceError(
                    msg,
                    status=response.status,
                    retryable=response.status in RETRYABLE_STATUS_CODES,
                )
        return False

    async def _login_once(self, username: str, password: str) -> None:
        token = await self._load_login_token()
        image_bytes = await self._fetch_captcha_image()
        captcha = await self.parse_captcha(image_bytes)
        if CAPTCHA_RE.fullmatch(captcha) is None:
            msg = "captcha solver did not return four ASCII letters or digits"
            raise AuthError(msg)

        await self._submit_login(username, password, token, captcha)
        if not await self.is_logged_in():
            msg = "credentials or captcha were rejected"
            raise AuthError(msg)

    async def _try_login_once(
        self,
        username: str,
        password: str,
    ) -> Exception | None:
        try:
            await self._login_once(username, password)
        except (
            aiohttp.ClientError,
            asyncio.TimeoutError,
            AuthError,
            OSError,
            ServiceError,
            ValueError,
        ) as error:
            return error
        return None

    async def login(self, username: str, password: str) -> None:
        """登录教务系统"""
        self._require_session()
        if not username or not password:
            msg = "username and password cannot be empty"
            raise AuthError(msg)

        async with self._login_lock:
            if self._credentials == (username, password) and await self.is_logged_in():
                return
            await self._login_until_success(username, password)

    async def _login_until_success(self, username: str, password: str) -> None:
        last_error: Exception | None = None
        attempt = 1
        while (
            self.options.login_attempts == 0 or attempt <= self.options.login_attempts
        ):
            max_attempts = (
                "∞"
                if self.options.login_attempts == 0
                else str(
                    self.options.login_attempts,
                )
            )
            log.info("第 %d/%s 次尝试登录", attempt, max_attempts)
            last_error = await self._try_login_once(username, password)
            if last_error is None:
                self._credentials = (username, password)
                log.info("登录成功")
                return
            if isinstance(last_error, InvalidCredentialsError):
                msg = "username or password is incorrect"
                raise InvalidCredentialsError(msg) from last_error

            log.warning("登录失败：%s", last_error)
            if (
                self.options.login_attempts == 0
                or attempt < self.options.login_attempts
            ):
                await self._sleep_login_retry()
            attempt += 1

        msg = f"login failed after {self.options.login_attempts} attempts"
        raise AuthError(msg) from last_error

    async def _restore_login(self, *, force: bool = False) -> None:
        if self._credentials is None:
            msg = "session expired and no saved credentials are available"
            raise SessionExpiredError(msg)
        async with self._login_lock:
            if not force and await self.is_logged_in():
                return
            username, password = self._credentials
            await self._login_until_success(username, password)
            if self._on_reauthenticated is not None:
                self._on_reauthenticated()

    async def _ensure_login(self) -> None:
        if await self.is_logged_in():
            return
        log.info("会话已过期，正在重新登录")
        await self._restore_login()

    async def parse_captcha(self, image_bytes: bytes) -> str:
        """在线程池中执行验证码识别"""
        solver = self._captcha_solver
        if solver is None:
            if self._captcha_recognizer is None:
                self._captcha_recognizer = CaptchaRecognizer()
            solver = self._captcha_recognizer
        return await asyncio.to_thread(solver, image_bytes)

    async def _perform_request_once(
        self,
        spec: _RequestSpec,
        decoder: ResponseDecoder[_T],
    ) -> _T:
        session = self._require_session()
        async with session.request(
            spec.method,
            spec.url,
            params=spec.params,
            data=spec.data,
            json=spec.json_data,
            headers=spec.headers,
            allow_redirects=spec.allow_redirects,
            max_redirects=self.options.max_redirects,
        ) as response:
            text = await response.text(errors="ignore")
            response_url = str(response.url)
            redirect_locations = tuple(
                item.headers.get("Location", "") for item in response.history
            )
            authentication_failure = classify_authentication_failure(
                status=response.status,
                response_url=response_url,
                redirect_locations=(
                    response.headers.get("Location", ""),
                    *redirect_locations,
                ),
                text=text,
            )
            if authentication_failure is not None:
                error = self._authentication_error(
                    authentication_failure,
                    response_url,
                    *redirect_locations,
                    text,
                )
                self._notify_session_expired(error)
                raise error
            if self.check_login_page(text):
                error = self._authentication_error(
                    AuthenticationFailure.LOGIN_REDIRECT,
                    response_url,
                    *redirect_locations,
                    text,
                )
                self._notify_session_expired(error)
                raise error
            if response.status in RETRYABLE_STATUS_CODES:
                msg = f"service returned retryable status {response.status}"
                raise ServiceError(
                    msg,
                    status=response.status,
                    retryable=True,
                )
            if response.status >= 400:  # noqa: PLR2004
                msg = f"service returned status {response.status}"
                raise ServiceError(msg, status=response.status)
            return decoder(text)

    async def _capture_request_attempt(
        self,
        spec: _RequestSpec,
        decoder: ResponseDecoder[_T],
    ) -> _AttemptResult[_T]:
        try:
            value = await self._perform_request_once(spec, decoder)
        except (
            aiohttp.ClientError,
            asyncio.TimeoutError,
            ServiceError,
            SessionExpiredError,
        ) as error:
            return _AttemptResult(error=error)
        return _AttemptResult(value=value)

    @staticmethod
    def _is_retryable_error(error: Exception) -> bool:
        if isinstance(error, ServiceError):
            return error.retryable
        return isinstance(error, aiohttp.ClientError | asyncio.TimeoutError)

    async def _request_with_retry(
        self,
        spec: _RequestSpec,
        decoder: ResponseDecoder[_T],
        policy: RetryPolicy,
    ) -> _T:
        is_idempotent = spec.method in IDEMPOTENT_METHODS
        if not is_idempotent:
            await self._ensure_login()

        max_attempts = policy.max_retry if is_idempotent else 1
        attempt = 1
        reauthenticated = False
        while attempt <= max_attempts:
            result = await self._capture_request_attempt(spec, decoder)
            if result.error is None:
                return cast("_T", result.value)

            error = result.error
            if isinstance(error, SessionExpiredError):
                if reauthenticated:
                    raise error
                log.info("认证中间件检测到 %s, 正在重新登录", error.reason.value)
                await self._restore_login(
                    force=error.reason is AuthenticationFailure.CSRF_TOKEN_EXPIRED,
                )
                reauthenticated = True
                continue

            if attempt == max_attempts or not self._is_retryable_error(error):
                raise error

            log.warning(
                "请求失败，第 %d/%d 次重试：%s",
                attempt,
                max_attempts,
                error,
            )
            await self._sleep_request_retry(attempt, policy)
            attempt += 1

        msg = "request retry loop ended unexpectedly"
        raise ServiceError(msg)

    @staticmethod
    def _decode_text(text: str) -> str:
        return text

    @staticmethod
    def _decode_json_object(text: str) -> dict[str, Any]:
        try:
            value = json_module.loads(text)
        except json_module.JSONDecodeError as error:
            preview = text[:200].replace("\n", " ").replace("\r", " ")
            msg = f"response is not valid JSON: {preview}"
            raise ServiceError(msg, retryable=True) from error
        if not isinstance(value, dict):
            msg = "JSON response is not an object"
            raise ServiceError(msg)
        return value

    def _make_request_spec(  # noqa: PLR0913
        self,
        method: str,
        path: str,
        *,
        params: RequestParams | None,
        data: object | None,
        json: object | None,
        headers: Mapping[str, str] | None,
        allow_redirects: bool,
    ) -> _RequestSpec:
        return _RequestSpec(
            method=method.upper(),
            url=self._build_url(path),
            params=params,
            data=data,
            json_data=json,
            headers=headers,
            allow_redirects=allow_redirects,
        )

    async def request_text(  # noqa: PLR0913
        self,
        method: str,
        path: str,
        *,
        params: RequestParams | None = None,
        data: object | None = None,
        json: object | None = None,
        headers: Mapping[str, str] | None = None,
        allow_redirects: bool = True,
        retry: RetryPolicy | None = None,
    ) -> str:
        """请求文本"""
        spec = self._make_request_spec(
            method,
            path,
            params=params,
            data=data,
            json=json,
            headers=headers,
            allow_redirects=allow_redirects,
        )
        return await self._request_with_retry(
            spec,
            self._decode_text,
            retry or self.retry,
        )

    async def request_json(  # noqa: PLR0913
        self,
        method: str,
        path: str,
        *,
        params: RequestParams | None = None,
        data: object | None = None,
        json: object | None = None,
        headers: Mapping[str, str] | None = None,
        allow_redirects: bool = True,
        retry: RetryPolicy | None = None,
    ) -> dict[str, Any]:
        """请求并解析 JSON 对象"""
        spec = self._make_request_spec(
            method,
            path,
            params=params,
            data=data,
            json=json,
            headers=headers,
            allow_redirects=allow_redirects,
        )
        return await self._request_with_retry(
            spec,
            self._decode_json_object,
            retry or self.retry,
        )
