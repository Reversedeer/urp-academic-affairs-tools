"""登录会话"""

import requests
import hashlib
import time
import re
from io import BytesIO
from PIL import Image
import ddddocr


BASE_URL = "https://jws.qgxy.cn"
LOGIN_PAGE = f"{BASE_URL}/login"
LOGIN_URL = f"{BASE_URL}/j_spring_security_check"
CAPTCHA_URL = f"{BASE_URL}/img/captcha.jpg"
INDEX_URL = f"{BASE_URL}/index.jsp"


class JWSSession:
    def __init__(self):
        self.session = requests.Session()
        self.headers = {
            "User-Agent": "Mozilla/5.0",
            "Referer": LOGIN_PAGE,
        }
        self.ocr = ddddocr.DdddOcr(show_ad=False, beta=True)

    @staticmethod
    def _md5(text: str) -> str:
        return hashlib.md5(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _extract_token(html: str) -> str:
        m = re.search(r'name="tokenValue"\s+value="([^"]+)"', html)
        if not m:
            raise RuntimeError("tokenValue not found")
        return m.group(1)

    def _fetch_captcha_image(self, max_retry=5) -> bytes:
        """
        稳定获取验证码图片：
        - 必须是 image/*
        - 必须能被 PIL 校验
        """
        for i in range(1, max_retry + 1):
            resp = self.session.get(CAPTCHA_URL, headers=self.headers)

            # HTTP 状态码
            if resp.status_code != 200:
                time.sleep(0.2)
                continue

            ct = resp.headers.get("Content-Type", "").lower()
            if "image" not in ct:
                # 大概率被重定向到登录页了，刷新 login
                print(f"[captcha] 第 {i} 次非图片响应，ct={ct}，刷新登录页")
                self.session.get(LOGIN_PAGE, headers=self.headers)
                time.sleep(0.2)
                continue

            try:
                img = Image.open(BytesIO(resp.content))
                img.verify()  # 不完整 / 非图片直接抛异常
                return resp.content
            except Exception as e:
                print(f"[captcha] 第 {i} 次图片损坏：{e}")

        raise RuntimeError("验证码获取失败（多次非图片或损坏）")

    def _parse_captcha(self, img_bytes: bytes) -> str:
        raw = self.ocr.classification(img_bytes)
        raw = raw.replace(" ", "").replace("=", "")
        print("[captcha OCR]", raw)

        # 处理算术验证码
        m = re.fullmatch(r"(\d+)([+\-])(\d+)", raw)
        if m:
            a, op, b = m.groups()
            a, b = int(a), int(b)
            return str(a + b if op == "+" else a - b)

        return raw

    def is_logged_in(self) -> bool:
        r = self.session.get(INDEX_URL, allow_redirects=True)
        if "login" in r.url.lower():
            return False
        return ("退出" in r.text) or ("欢迎" in r.text)

    def login(self, username: str, password: str, max_retry=10):
        for i in range(1, max_retry + 1):
            print(f"\n[LOGIN] 第 {i} 次尝试")

            r = self.session.get(LOGIN_PAGE, headers=self.headers)
            token = self._extract_token(r.text)
            print("[LOGIN] tokenValue:", token)

            try:
                img_bytes = self._fetch_captcha_image()
                captcha = self._parse_captcha(img_bytes)
            except Exception as e:
                print("[LOGIN] 验证码失败：", e)
                continue

            if not captcha.isalnum():
                print("[LOGIN] OCR 结果异常，重试")
                continue

            data = {
                "tokenValue": token,
                "j_username": username,
                "j_password": self._md5(password),
                "j_captcha": captcha,
            }

            self.session.post(
                LOGIN_URL,
                data=data,
                headers=self.headers,
                allow_redirects=True,
            )

            # 判断是否真正登录成功
            if self.is_logged_in():
                print("[LOGIN] 登录成功")
                return

            print("[LOGIN] 登录失败，重试中…")

        raise RuntimeError("登录失败：超过最大重试次数")

    def get(self, path: str, **kwargs):
        """
        所有业务请求都走这里，便于以后加自动重登
        """
        return self.session.get(BASE_URL + path, **kwargs)
