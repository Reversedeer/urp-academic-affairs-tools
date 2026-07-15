"""在 Qt 主线程外运行协程的基础设施。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QThread, Signal

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine


class AsyncWorker(QThread):
    """以独立线程运行单次异步操作，并把结果送回 Qt 信号。"""

    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, operation: Callable[[], Coroutine[Any, Any, Any]]) -> None:
        super().__init__()
        self.operation = operation

    def run(self) -> None:
        try:
            result = asyncio.run(self.operation())
        except Exception as error:  # noqa: BLE001
            self.failed.emit(str(error))
        else:
            self.succeeded.emit(result)
