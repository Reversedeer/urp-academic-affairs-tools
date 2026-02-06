"""登录会话"""

import re
import asyncio
import aiohttp
import ddddocr
import hashlib
import random
import logging

from collections import Counter
from dataclasses import dataclass
from io import BytesIO
from typing import Optional
from PIL import Image, ImageSequence

BASE_URL = "https://jws.qgxy.cn"
LOGIN_PAGE = f"{BASE_URL}/login"
LOGIN_URL = f"{BASE_URL}/j_spring_security_check"
CAPTCHA_URL = f"{BASE_URL}/img/captcha.jpg"
INDEX_URL = f"{BASE_URL}/index.jsp"

CODE_LEN = 4
ASCII_CODE_RE = re.compile(r"^[A-Za-z0-9]{4}$")
TOKEN_RE = re.compile(r'name="tokenValue"\s+value="([^"]+)"', re.I)

log = logging.getLogger(__name__)


@dataclass
class RetryPolicy:
    max_retry: int = 4
    base_sleep: float = 0.15
    max_sleep: float = 1.2
    jitter: float = 0.2


class AuthError(Exception): ...


class ServiceError(Exception): ...


class SessionExpired(Exception): ...


class AsyncJWSSession:
    def __init__(
        self,
        timeout_total: float = 6.0,
        timeout_connect: float = 2.0,
        connector_limit: int = 50,
        retry: RetryPolicy = RetryPolicy(),
        jitter_range=(0.0, 0.15),
    ) -> None:
        self._timeout = aiohttp.ClientTimeout(
            total=timeout_total, connect=timeout_connect
        )
        self._connector = aiohttp.TCPConnector(limit=connector_limit, ttl_dns_cache=300)
        self._session: Optional[aiohttp.ClientSession] = None

        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_12_6) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/73.0.3683.75 Safari/537.36"
            ),
            "Referer": LOGIN_PAGE,
        }
        self.retry = retry
        self.jitter_range = jitter_range

        self._username = None
        self._password = None
        self._ocr = ddddocr.DdddOcr(show_ad=False, beta=True)

    async def __aenter__(self) -> "AsyncJWSSession":
        self._session = aiohttp.ClientSession(
            timeout=self._timeout,
            connector=self._connector,
            headers=self.headers,
            raise_for_status=False,
        )
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    @staticmethod
    def _md5(text: str) -> str:
        """明文密码 MD5 加密"""
        return hashlib.md5(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _extract_token(html: str) -> str:
        """获取tokenValue"""
        m: re.Match[str] | None = TOKEN_RE.search(html or "")
        if not m:
            raise AuthError("tokenValue not found")
        return m.group(1)

    async def _sleep_jitter(self) -> None:
        """随机等待，防止请求过快"""
        lo, hi = self.jitter_range
        if hi > 0:
            await asyncio.sleep(random.uniform(lo, hi))

    def check_login_page(self, text: str) -> bool:
        """检查是否为登录页面"""
        t: str = (text or "").lower()
        return (
            ("tokenvalue" in t and "j_spring_security_check" in t)
            or ("gotologin" in t)
            or ("/login" in t)
        )

    async def is_logged_in(self) -> bool:
        """检查是否已登录"""
        if not self._session:
            log.error("session not started")
            raise RuntimeError("session not started ")

        try:
            async with self._session.get(INDEX_URL, allow_redirects=False) as r:
                if r.status == 200:
                    txt = await r.text(errors="ignore")
                    return not self.check_login_page(txt)
                if r.status in (301, 302, 303, 307, 308):
                    loc = (r.headers.get("Location") or "").lower()
                    return not ("gotologin" in loc or "/login" in loc)
                return False
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return False

    async def login(self, username, password, max_retry: int = 10):
        """登录教务系统，保存会话状态"""
        if not self._session:
            raise RuntimeError("session not started")

        self._username = username
        self._password = password

        for i in range(max_retry):
            log.info("✨ 第 %d 次尝试登录:", i + 1)
            try:
                async with self._session.get(LOGIN_PAGE) as r:
                    if r.status != 200:
                        await self._sleep_jitter()
                        continue
                    html = await r.text(errors="ignore")
                token = self._extract_token(html)
                log.info("tokenValue: %s", token)
            except (aiohttp.ClientError, asyncio.TimeoutError, AuthError):
                log.exception("获取登录页异常")
                await self._sleep_jitter()
                continue

            # 验证码
            try:
                img_bytes = await self._fetch_captcha_image(max_retry=5)
            except Exception:
                log.exception("获取验证码异常")
                await self._sleep_jitter()
                continue

            # OCR
            captcha = await self.parse_captcha(img_bytes)
            if not captcha or not ASCII_CODE_RE.fullmatch(captcha):
                await self._sleep_jitter()
                continue

            data = {
                "tokenValue": token,
                "j_username": username,
                "j_password": self._md5(password),
                "j_captcha": captcha,
            }
            try:
                async with self._session.post(
                    LOGIN_URL, data=data, allow_redirects=True
                ) as _:
                    pass
            except (aiohttp.ClientError, asyncio.TimeoutError):
                log.exception("登录提交失败")
                await self._sleep_jitter()
                continue

            if await self.is_logged_in():
                log.info("✅ 登录成功")
                return
            log.warning("❌ 登录失败，重试中...")
            await self._sleep_jitter()
        log.error("❌ 登录失败，达到最大重试次数")
        raise AuthError("login failed")

    async def _ensure_login(self) -> None:
        """确保已登录，未登录则自动重登"""
        if await self.is_logged_in():
            return
        if not self._username or not self._password:
            log.error("未登录且未保存账号密码，无法自动重登")
            raise SessionExpired("not logged in and no saved credentials")
        log.info("session已过期，自动重登…")
        await self.login(self._username, self._password)

    async def _fetch_captcha_image(self, max_retry: int = 5) -> bytes:
        """获取验证码图片"""
        if not self._session:
            log.error("验证码未正常加载")
            raise RuntimeError("session not started")

        for _ in range(max_retry):
            try:
                async with self._session.get(CAPTCHA_URL, allow_redirects=True) as r:
                    if r.status != 200:
                        await self._sleep_jitter()
                        continue

                    ct = (r.headers.get("Content-Type") or "").lower()
                    content = await r.read()

                if "image" not in ct:
                    # 疑似被踢回登录：刷新一次登录页
                    try:
                        async with self._session.get(LOGIN_PAGE) as _:
                            pass
                    except Exception:
                        log.exception("刷新登录页出错")
                        pass
                    await self._sleep_jitter()
                    continue

                ok = await self._verify_image(content)
                if ok:
                    return content

            except (aiohttp.ClientError, asyncio.TimeoutError):
                log.exception("获取验证码请求异常")
                await self._sleep_jitter()
        log.error("验证码获取失败")
        raise AuthError("captcha fetch failed")

    async def _verify_image(self, img_bytes: bytes) -> bool:
        """校验验证码合法性"""
        loop = asyncio.get_running_loop()

        def _verify() -> bool:
            try:
                img = Image.open(BytesIO(img_bytes))
                img.verify()
                return True
            except Exception:
                log.exception("验证码图片校验失败")
                return False

        return await loop.run_in_executor(None, _verify)

    async def parse_captcha(self, img_bytes: bytes) -> str:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._parse_captcha, img_bytes)

    def _parse_captcha(self, img_bytes: bytes) -> str:
        """
        验证码解析策略：
        - full OCR
        - split OCR
        - full 和 split 都是 4 位 → 优先 full
        - 否则 → 优先 split
        """

        def normalize(s: str) -> str:
            if not s:
                return ""
            s = s.strip().replace(" ", "")
            s = s.replace("y", "7").replace("9", "r").replace("E", "F")
            s = "".join(
                ch
                for ch in s
                if ("0" <= ch <= "9") or ("A" <= ch <= "Z") or ("a" <= ch <= "z")
            )
            return s.lower()

        def ocr_img(pil_img: Image.Image) -> str:
            pil_img = pil_img.resize(
                (pil_img.width * 2, pil_img.height * 2), Image.NEAREST
            )
            buf = BytesIO()
            pil_img.save(buf, format="PNG")
            return self._ocr.classification(buf.getvalue())

        img = Image.open(BytesIO(img_bytes))
        frames = [f.convert("L") for f in ImageSequence.Iterator(img)]
        if not frames:
            return ""

        base = frames[0]
        norm_full = normalize(ocr_img(base))
        log.info("Full OCR result: '%s'", norm_full)

        if sum(1 for ch in norm_full if ch.isalnum()) < 3:
            log.warning("Full OCR 非4位ASCII字母数字/非数字答案，重试中...")
            return ""

        w, h = base.size
        char_w = w // 4
        split_chars = []
        for i in range(4):
            crop = base.crop((i * char_w, 0, (i + 1) * char_w, h))
            norm = normalize(ocr_img(crop))
            split_chars.append(norm[:1] if norm else "")

        if not split_chars[0]:
            candidates = []
            for frame in frames[:3]:
                w2, h2 = frame.size
                for ratio in (4, 3):
                    crop = frame.crop((0, 0, w2 // ratio, h2))
                    norm = normalize(ocr_img(crop))
                    if norm:
                        candidates.append(norm[0])
            if candidates:
                split_chars[0] = Counter(candidates).most_common(1)[0][0]
            log.info("尝试补全首字符 '%s'->'%s'", candidates, split_chars[0])

        split_code = "".join(split_chars)
        log.info("split_chars -> split_code: '%s' -> '%s'", split_chars, split_code)

        full_ok = len(norm_full) == CODE_LEN and ASCII_CODE_RE.fullmatch(norm_full)
        split_ok = len(split_code) == CODE_LEN and ASCII_CODE_RE.fullmatch(split_code)

        if full_ok and split_ok:
            log.info("使用 full='%s'", norm_full)
            return norm_full
        if split_ok:
            log.info("使用 split='%s'", split_code)
            return split_code
        if full_ok:
            log.info("使用 full='%s'", norm_full)
            return norm_full
        return ""

    async def request_text(
        self,
        method: str,
        path: str,
        *,
        params=None,
        data=None,
        json=None,
        allow_redirects: bool = True,
        retry: Optional[RetryPolicy] = None,
    ) -> str:
        """自动处理重试和登录过期"""
        await self._ensure_login()
        if not self._session:
            log.error("session not started")
            raise RuntimeError("session not started")

        url = (
            path
            if path.startswith("http")
            else (BASE_URL + (path if path.startswith("/") else f"/{path}"))
        )
        pol = retry or self.retry

        for attempt in range(1, pol.max_retry + 1):
            try:
                async with self._session.request(
                    method,
                    url,
                    params=params,
                    data=data,
                    json=json,
                    allow_redirects=allow_redirects,
                ) as r:
                    txt = await r.text(errors="ignore")

                    if self.check_login_page(txt):
                        log.info("looks like login page")
                        raise SessionExpired("looks like login page")

                    if r.status in (429, 502, 503, 504):
                        log.warning("retryable status %d", r.status)
                        raise ServiceError(f"retryable status {r.status}")

                    if r.status >= 400:
                        log.error("non-retryable status %d", r.status)
                        raise ServiceError(f"status {r.status}")

                    return txt

            except SessionExpired:
                await self.login(self._username, self._password)
            except (aiohttp.ClientError, asyncio.TimeoutError, ServiceError):
                if attempt == pol.max_retry:
                    log.exception("达到最大重试次数, 已放弃请求登录")
                    raise
                sleep = min(
                    pol.max_sleep, pol.base_sleep * (2 ** (attempt - 1))
                ) + random.uniform(0, pol.jitter)
                await asyncio.sleep(sleep)

        raise ServiceError("unreachable")

    async def request_json(self, method: str, path: str, **kwargs) -> dict:
        """发送请求并解析 JSON 响应"""
        txt = await self.request_text(method, path, **kwargs)
        # request_text 已保证不是登录页/且 status<400；这里解析 JSON
        try:
            import json as _json

            return _json.loads(txt)
        except Exception:
            # 某些接口 content-type 正常但仍可能不是 JSON
            raise ServiceError("response is not json")
