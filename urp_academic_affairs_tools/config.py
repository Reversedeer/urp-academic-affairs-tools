"""从环境变量或项目根目录的 ``.env`` 读取运行配置。"""

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DEFAULT_BASE_URL = "https://jws.qgxy.cn"
DEFAULT_COMMENT_TEXT = "老师教学认真课程收获较大"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"
ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
MIN_QUOTED_VALUE_LENGTH = 2


@dataclass(frozen=True, slots=True)
class Settings:
    """应用运行配置。"""

    base_url: str = DEFAULT_BASE_URL
    username: str | None = None
    password: str | None = None
    default_choice: str = "A"
    default_comment: str = DEFAULT_COMMENT_TEXT
    evaluation_wait_seconds: float = 120.0
    evaluation_limit: int | None = None
    evaluation_concurrency: int = 3

    def __post_init__(self) -> None:
        if not self.base_url.startswith(("http://", "https://")):
            msg = "URP_BASE_URL 必须以 http:// 或 https:// 开头"
            raise ValueError(msg)
        if self.default_choice not in {"A", "B", "C", "D", "E"}:
            msg = "URP_DEFAULT_CHOICE 必须是 A、B、C、D 或 E"
            raise ValueError(msg)
        if not self.default_comment:
            msg = "URP_DEFAULT_COMMENT 不能为空"
            raise ValueError(msg)
        if self.evaluation_wait_seconds < 0:
            msg = "URP_EVALUATION_WAIT_SECONDS 不能为负数"
            raise ValueError(msg)
        if self.evaluation_limit is not None and self.evaluation_limit < 1:
            msg = "URP_EVALUATION_LIMIT 必须大于等于 1"
            raise ValueError(msg)
        if self.evaluation_concurrency < 1:
            msg = "URP_EVALUATION_CONCURRENCY 必须大于等于 1"
            raise ValueError(msg)

    def require_credentials(self) -> tuple[str, str]:
        """返回账号密码；缺失时给出可操作的错误信息。"""
        if not self.username or not self.password:
            msg = (
                "未找到教务系统账号密码，请设置 URP_USERNAME 和 URP_PASSWORD "
                "环境变量，或在项目根目录创建 .env 文件"
            )
            raise RuntimeError(msg)
        return self.username, self.password


def _read_env_file(path: Path) -> dict[str, str]:
    """读取简单的 KEY=VALUE 文件，不执行变量展开或任意代码。"""
    if not path.is_file():
        return {}

    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8-sig").splitlines(),
        start=1,
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").strip()
        key, separator, raw_value = line.partition("=")
        key = key.strip()
        if not separator or ENV_KEY_RE.fullmatch(key) is None:
            msg = f"{path} 第 {line_number} 行不是有效的 KEY=VALUE 配置"
            raise ValueError(msg)

        value = raw_value.strip()
        if (
            len(value) >= MIN_QUOTED_VALUE_LENGTH
            and value[0] == value[-1]
            and value[0] in {'"', "'"}
        ):
            value = value[1:-1]
        values[key] = value
    return values


def _parse_optional_positive_int(value: str | None, *, name: str) -> int | None:
    if value is None or value.strip() == "":
        return None
    try:
        parsed = int(value)
    except ValueError as error:
        msg = f"{name} 必须是正整数"
        raise ValueError(msg) from error
    if parsed < 1:
        msg = f"{name} 必须是正整数"
        raise ValueError(msg)
    return parsed


def load_settings(
    env: Mapping[str, str] | None = None,
    *,
    env_file: Path | None = None,
) -> Settings:
    """加载配置；真实环境变量优先于 ``.env``。"""
    environment = os.environ if env is None else env
    selected_env_file = env_file or Path(
        environment.get("URP_ENV_FILE", DEFAULT_ENV_FILE),
    )
    values = _read_env_file(selected_env_file)
    values.update(environment)

    base_url = values.get("URP_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    username = values.get("URP_USERNAME") or None
    password = values.get("URP_PASSWORD") or None
    default_choice = values.get("URP_DEFAULT_CHOICE", "A").strip().upper()
    default_comment = values.get(
        "URP_DEFAULT_COMMENT",
        DEFAULT_COMMENT_TEXT,
    ).strip()
    wait_seconds = float(values.get("URP_EVALUATION_WAIT_SECONDS", "120"))
    evaluation_limit = _parse_optional_positive_int(
        values.get("URP_EVALUATION_LIMIT"),
        name="URP_EVALUATION_LIMIT",
    )
    evaluation_concurrency = _parse_optional_positive_int(
        values.get("URP_EVALUATION_CONCURRENCY"),
        name="URP_EVALUATION_CONCURRENCY",
    )

    return Settings(
        base_url=base_url,
        username=username,
        password=password,
        default_choice=default_choice,
        default_comment=default_comment,
        evaluation_wait_seconds=wait_seconds,
        evaluation_limit=evaluation_limit,
        evaluation_concurrency=evaluation_concurrency or 3,
    )


# 保留旧常量，避免现有调用方立即失效；新代码应优先使用 load_settings()。
_SETTINGS = load_settings()
BASE_URL = _SETTINGS.base_url
USERNAME = _SETTINGS.username
PASSWORD = _SETTINGS.password
DEFAULT_CHOICE = _SETTINGS.default_choice
DEFAULT_COMMENT = _SETTINGS.default_comment


def require_credentials() -> tuple[str, str]:
    """兼容旧调用方式，并在调用时重新读取环境配置。"""
    return load_settings().require_credentials()
