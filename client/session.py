# client/session.py
import requests
import hashlib
import time
import re
import ddddocr

BASE_URL = "https://jws.qgxy.cn"
LOGIN_URL = f"{BASE_URL}/j_spring_security_check"
LOGIN_PAGE = f"{BASE_URL}/login"
CAPTCHA_URL = f"{BASE_URL}/img/captcha.jpg"
INDEX_URL = f"{BASE_URL}/index.jsp"


class JWSSession:
    def __init__(self):
        self.session = requests.Session()
        self.headers = {
            "User-Agent": "Mozilla/5.0",
            "Referer": LOGIN_PAGE,
        }
        self.ocr = ddddocr.DdddOcr(show_ad=False)

    # ---------- 工具函数 ----------
    @staticmethod
    def _md5(text: str) -> str:
        return hashlib.md5(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _extract_token(html: str) -> str:
        m = re.search(r'name="tokenValue"\s+value="([^"]+)"', html)
        if not m:
            raise RuntimeError("tokenValue not found")
        return m.group(1)

    def _parse_captcha(self, img_bytes: bytes) -> str:
        raw = self.ocr.classification(img_bytes)
        raw = raw.replace(" ", "").replace("=", "")

        # 处理算术验证码
        m = re.fullmatch(r"(\d+)([+\-])(\d+)", raw)
        if m:
            a, op, b = m.groups()
            a, b = int(a), int(b)
            return str(a + b if op == "+" else a - b)

        return raw

    # ---------- 登录状态判断 ----------
    def is_logged_in(self) -> bool:
        r = self.session.get(INDEX_URL, allow_redirects=True)
        if "login" in r.url.lower():
            return False
        return "退出" in r.text or "欢迎" in r.text

    # ---------- 登录主逻辑 ----------
    def login(self, username: str, password: str, max_retry=10):
        for i in range(1, max_retry + 1):
            print(f"[LOGIN] 第 {i} 次尝试")

            # 1. 登录页（拿 token）
            r = self.session.get(LOGIN_PAGE, headers=self.headers)
            token = self._extract_token(r.text)

            # 2. 验证码
            cap = self.session.get(CAPTCHA_URL, headers=self.headers)
            captcha = self._parse_captcha(cap.content)

            if not captcha.isalnum():
                print("  [-] OCR 结果异常，重试")
                continue

            # 3. 提交登录
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

            # 4. 判断是否成功
            if self.is_logged_in():
                print("[LOGIN] 成功")
                return

            print("[LOGIN] 失败，重试中…")
            time.sleep(0.5)

        raise RuntimeError("登录失败，超过最大重试次数")

    # ---------- 统一 GET 接口 ----------
    def get(self, path: str, **kwargs):
        """
        所有业务请求都走这里，便于以后加自动重登
        """
        return self.session.get(BASE_URL + path, **kwargs)
