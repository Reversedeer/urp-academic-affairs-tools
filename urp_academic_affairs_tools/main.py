"""命令行入口。"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn

import aioconsole

if TYPE_CHECKING:
    from collections.abc import Awaitable

if __package__:
    from .client import (
        AsyncJWSSession,
        AuthError,
        ServiceError,
        get_this_semester_timetable,
    )
    from .config import load_settings
    from .course_selection import handle_course_drop, handle_course_selection
    from .export import export_timetable_excel
    from .parser.evaluation import handle_teaching_evaluation
    from .parser.timetable import parse_timetable
    from .score_query import handle_score_query
else:
    from client import (  # type: ignore[no-redef]
        AsyncJWSSession,
        AuthError,
        ServiceError,
        get_this_semester_timetable,
    )
    from config import load_settings  # type: ignore[no-redef]
    from course_selection import (  # type: ignore[no-redef]
        handle_course_drop,
        handle_course_selection,
    )
    from export import export_timetable_excel  # type: ignore[no-redef]
    from parser.evaluation import handle_teaching_evaluation  # type: ignore[no-redef]
    from parser.timetable import parse_timetable  # type: ignore[no-redef]
    from score_query import handle_score_query  # type: ignore[no-redef]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


def menu() -> None:
    log.info("========================")
    log.info("欢迎使用教务系统工具")
    log.info("1. 导出课表")
    log.info("2. 教学评估")
    log.info("3. 选课")
    log.info("4. 退课")
    log.info("5. 成绩查询")
    log.info("0. 退出")
    log.info("========================")


async def read_menu_choice() -> str | None:
    try:
        return (await aioconsole.ainput("请输入选项：")).strip()
    except EOFError:
        return None


async def handle_view_timetable(jws: AsyncJWSSession) -> None:
    raw_data = await get_this_semester_timetable(jws)
    courses = parse_timetable(raw_data)
    if not courses:
        log.warning("未查询到任何课程")
        return

    output_path = await export_timetable_excel(courses, Path("本学期课表.xlsx"))
    log.info("本学期课表已导出：%s", output_path.resolve())


async def _run_menu_action(
    action: str,
    func: Awaitable[None],
) -> None:
    failed = False
    try:
        await func
    except (AuthError, RuntimeError, ServiceError, ValueError) as error:
        failed = True
        log.warning("%s失败：%s", action, error)
    except Exception:
        failed = True
        log.exception("%s出现未处理异常", action)
    if failed:
        try:
            await aioconsole.ainput("按回车返回主菜单...")
        except EOFError:
            return


async def main() -> None:
    settings = load_settings()
    username, password = settings.require_credentials()

    async with AsyncJWSSession(base_url=settings.base_url) as jws:
        await jws.login(username, password)

        while True:
            menu()
            choice = await read_menu_choice()
            if choice is None:
                log.info("输入流已关闭，退出")
                return
            if choice == "1":
                await _run_menu_action("导出课表", handle_view_timetable(jws))
            elif choice == "2":
                await _run_menu_action("教学评估", handle_teaching_evaluation(jws, settings))
            elif choice == "3":
                await _run_menu_action(
                    "选课",
                    handle_course_selection(jws, settings),
                )
            elif choice == "4":
                await _run_menu_action("退课", handle_course_drop(jws))
            elif choice == "5":
                await _run_menu_action("成绩查询", handle_score_query(jws))
            elif choice == "0":
                return
            else:
                log.warning("无效选项")


def _exit_with_error(error: Exception) -> NoReturn:
    log.error("程序无法继续：%s", error)
    raise SystemExit(1) from None


def run() -> None:
    """运行命令行程序并将常见错误转换为简洁提示。"""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("已退出")
    except (AuthError, RuntimeError, ServiceError, ValueError) as error:
        _exit_with_error(error)


if __name__ == "__main__":
    run()
