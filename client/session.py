"""登录会话"""

import requests
import hashlib
import time
import re
import random
from io import BytesIO
from collections import Counter

from PIL import Image, ImageSequence
import ddddocr
from requests.adapters import HTTPAdapter


BASE_URL = "https://jws.qgxy.cn"
LOGIN_PAGE = f"{BASE_URL}/login"
LOGIN_URL = f"{BASE_URL}/j_spring_security_check"
CAPTCHA_URL = f"{BASE_URL}/img/captcha.jpg"
INDEX_URL = f"{BASE_URL}/index.jsp"
CODE_LEN = 4
ASCII_CODE_RE = re.compile(r"^[A-Za-z0-9]{4}$")


class JWSSession:
    def __init__(self):
        self.session = requests.Session()
        adapter = HTTPAdapter(
            pool_connections=50,
            pool_maxsize=50,
            max_retries=0,
            pool_block=False,
        )
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_12_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/73.0.3683.75 Safari/537.36",
            "Referer": LOGIN_PAGE,
        }
        self.timeout = (2, 3)
        self.jitter = (0.0, 0.15)
        self.ocr = ddddocr.DdddOcr(show_ad=False, beta=True)
        self._username = None
        self._password = None

    @staticmethod
    def _md5(text: str) -> str:
        return hashlib.md5(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _extract_token(html: str) -> str:
        m = re.search(r'name="tokenValue"\s+value="([^"]+)"', html)
        if not m:
            raise RuntimeError("tokenValue not found")
        return m.group(1)

    def _sleep_jitter(self) -> None:
        lo, hi = self.jitter
        if hi > 0:
            time.sleep(random.uniform(lo, hi))

    def _fetch_captcha_image(self, max_retry=5) -> bytes:
        """获取验证码图片(gif)"""
        for i in range(1, max_retry + 1):
            try:
                resp = self.session.get(
                    CAPTCHA_URL,
                    headers=self.headers,
                    timeout=self.timeout,
                    allow_redirects=True,
                )
            except requests.RequestException as e:
                print(f"❌[captcha] 第 {i} 次请求异常：{e}")
                self._sleep_jitter()
                continue

            if resp.status_code != 200:
                self._sleep_jitter()
                continue

            ct = resp.headers.get("Content-Type", "").lower()
            if "image" not in ct:
                # 大概率被重定向到登录页了，刷新 login
                print(f"❌[captcha] 第 {i} 次非图片响应，ct={ct}，刷新登录页")
                try:
                    self.session.get(
                        LOGIN_PAGE, headers=self.headers, timeout=self.timeout
                    )
                except requests.RequestException:
                    pass
                self._sleep_jitter()
                continue

            try:
                img = Image.open(BytesIO(resp.content))
                img.verify()
                return resp.content
            except Exception as e:
                print(f"❌[captcha] 第 {i} 次图片损坏：{e}")
                self._sleep_jitter()

        raise RuntimeError("验证码获取失败（多次非图片或损坏）")

    def _parse_captcha(self, img_bytes: bytes) -> str:
        """
        验证码解析策略：
            - full OCR
            - split OCR（四等分）
            - full 和 split 都是 4 位 → 优先 full
            - 否则 → 优先 split
        """

        def normalize(s: str) -> str:
            if not s:
                return ""
            s = s.strip().replace(" ", "")

            # 截断算术提示符
            for sep in ("=", "?"):
                if sep in s:
                    s = s.split(sep, 1)[0]
                    break

            s = s.replace("y", "7").replace("9", "r").replace("E", "F")

            s = "".join(
                ch
                for ch in s
                if ("0" <= ch <= "9") or ("A" <= ch <= "Z") or ("a" <= ch <= "z")
            )
            return s.lower()

        def is_valid_code(s: str) -> bool:
            return bool(ASCII_CODE_RE.fullmatch(s))

        def ocr_img(pil_img: Image.Image) -> str:
            pil_img = pil_img.resize(
                (pil_img.width * 2, pil_img.height * 2), Image.NEAREST
            )
            buf = BytesIO()
            pil_img.save(buf, format="PNG")
            return self.ocr.classification(buf.getvalue())

        # ================== 读取 GIF ==================
        img = Image.open(BytesIO(img_bytes))
        frames = [f.convert("L") for f in ImageSequence.Iterator(img)]
        if not frames:
            return ""

        base = frames[0]

        # ================== ① 整体 OCR ==================
        raw_full = ocr_img(base)
        norm_full = normalize(raw_full)

        print(f"⭕[captcha-raw] full='{raw_full}'")

        # ================== ② 单独 OCR ==================
        w, h = base.size
        char_w = w // 4

        split_chars = []

        for i in range(4):
            box = (i * char_w, 0, (i + 1) * char_w, h)
            crop = base.crop(box)
            raw = ocr_img(crop)
            norm = normalize(raw)
            split_chars.append(norm[:1] if norm else "")

        # ===== 第一位强化识别（多帧 + 多裁剪投票）=====
        if not split_chars[0]:
            candidates = []

            for frame in frames[:3]:
                w, h = frame.size

                for ratio in (4, 3):
                    crop = frame.crop((0, 0, w // ratio, h))
                    raw = ocr_img(crop)
                    norm = normalize(raw)
                    if norm:
                        candidates.append(norm[0])

            if candidates:
                split_chars[0] = Counter(candidates).most_common(1)[0][0]

                print(
                    f"🚨[captcha-first-fix] candidates={candidates} -> {split_chars[0]}"
                )

        split_code = "".join(split_chars)

        print(f"⭕[captcha-split] {split_chars} -> '{split_code}'")

        # ================== ③ 决策 ==================
        full_ok = len(norm_full) == CODE_LEN and is_valid_code(norm_full)
        split_ok = len(split_code) == CODE_LEN and is_valid_code(split_code)

        if full_ok and split_ok:
            print(f"⬆️ [captcha-final] 使用 full='{norm_full}'")
            return norm_full

        if split_ok:
            print(f"⬆️ [captcha-final] 使用 split='{split_code}'")
            return split_code

        if full_ok:
            print(f"⬆️ [captcha-final] 使用 full='{norm_full}'")
            return norm_full

        print("❌[captcha-final] 失败")
        return ""

    def is_logged_in(self) -> bool:
        try:
            r = self.session.get(
                INDEX_URL,
                allow_redirects=False,
                headers=self.headers,
                timeout=self.timeout,
            )
        except requests.RequestException:
            return False

        if r.status_code == 200:
            return True

        if r.status_code in (301, 302, 303, 307, 308):
            loc = (r.headers.get("Location") or "").lower()
            if "gotologin" in loc or "/login" in loc:
                return False

        return False

    def login(self, username: str, password: str, max_retry=25):
        self._username = username
        self._password = password

        for i in range(1, max_retry + 1):
            print(f"\n✨[LOGIN] 第 {i} 次尝试", time.strftime("%Y-%m-%d %H:%M:%S"))

            try:
                r = self.session.get(
                    LOGIN_PAGE, headers=self.headers, timeout=self.timeout
                )
            except requests.RequestException as e:
                print("❌[LOGIN] 获取登录页失败：", e)
                self._sleep_jitter()
                continue

            token = self._extract_token(r.text)
            print("✨[LOGIN] tokenValue:", token)

            try:
                img_bytes = self._fetch_captcha_image()
                captcha = self._parse_captcha(img_bytes)
            except Exception as e:
                print("❌[LOGIN] 验证码失败：", e)
                continue

            if not captcha or not ASCII_CODE_RE.fullmatch(captcha):
                print("❌[LOGIN] OCR 结果异常（非4位ASCII字母数字/非数字答案），重试")
                continue

            data = {
                "tokenValue": token,
                "j_username": username,
                "j_password": self._md5(password),
                "j_captcha": captcha,
            }

            try:
                self.session.post(
                    LOGIN_URL,
                    data=data,
                    headers=self.headers,
                    allow_redirects=True,
                    timeout=self.timeout,
                )
            except requests.RequestException as e:
                print("❌[LOGIN] 登录提交失败：", e)
                self._sleep_jitter()
                continue

            if self.is_logged_in():
                print("✅[LOGIN] 登录成功")
                return

            print("❌[LOGIN] 登录失败，重试中…")
            self._sleep_jitter()

        raise RuntimeError("❌登录失败：超过最大重试次数")

    def _ensure_login(self):
        if self.is_logged_in():
            return

        if not self._username or not self._password:
            raise RuntimeError("未登录且未保存账号密码，无法自动重登")

        print("[AUTH] 检测到未登录，自动重登…")
        self.login(self._username, self._password)

    def _request_with_retry(self, method: str, url: str, **kwargs):
        timeout = kwargs.pop("timeout", self.timeout)
        headers = kwargs.pop("headers", None) or self.headers

        # 失败重试次数（抢课阶段建议 3~6）
        max_retry = kwargs.pop("max_retry", 4)

        # 指数退避参数
        base_sleep = kwargs.pop("base_sleep", 0.15)
        max_sleep = kwargs.pop("max_sleep", 1.2)

        for i in range(1, max_retry + 1):
            try:
                resp = self.session.request(
                    method=method,
                    url=url,
                    headers=headers,
                    timeout=timeout,
                    allow_redirects=kwargs.pop("allow_redirects", True),
                    **kwargs,
                )

                if resp.status_code in (502, 503, 504):
                    raise requests.RequestException(f"bad gateway: {resp.status_code}")

                if resp.status_code == 429:
                    sleep = min(
                        max_sleep, base_sleep * (2 ** (i - 1))
                    ) + random.uniform(0, 0.2)
                    time.sleep(sleep)
                    continue

                return resp

            except requests.RequestException as e:
                if i == max_retry:
                    print(f"❌[REQ] 达到最大重试次数，放弃请求：{e}")
                    raise

                sleep = min(max_sleep, base_sleep * (2 ** (i - 1))) + random.uniform(
                    0, 0.2
                )
                time.sleep(sleep)

        raise RuntimeError("unreachable")

    def get(self, path: str, **kwargs):
        """所有业务请求都走这里：自动重登 + 重试 + timeout"""
        self._ensure_login()
        url = BASE_URL + path
        return self._request_with_retry("GET", url, **kwargs)

    def post(self, path: str, **kwargs):
        """抢课一般是 POST，建议后续都走这里"""
        self._ensure_login()
        url = BASE_URL + path
        return self._request_with_retry("POST", url, **kwargs)
