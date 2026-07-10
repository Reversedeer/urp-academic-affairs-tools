"""命令行入口。"""

import asyncio
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn

import aioconsole

if __package__:
    from .client import (
        AsyncJWSSession,
        AuthError,
        ServiceError,
        fetch_tasks,
        get_this_semester_timetable,
    )
    from .config import Settings, load_settings
    from .export import export_timetable_excel
    from .parser import (
        CONFIRM_PHRASE,
        EvaluationBatchError,
        EvaluationCancelledError,
        EvaluationOptions,
        EvaluationTask,
        TeachingEvaluationClient,
        parse_timetable,
    )
else:
    from client import (  # type: ignore[no-redef]
        AsyncJWSSession,
        AuthError,
        ServiceError,
        fetch_tasks,
        get_this_semester_timetable,
    )
    from config import Settings, load_settings  # type: ignore[no-redef]
    from export import export_timetable_excel  # type: ignore[no-redef]
    from parser import (  # type: ignore[no-redef]
        CONFIRM_PHRASE,
        EvaluationBatchError,
        EvaluationCancelledError,
        EvaluationOptions,
        EvaluationTask,
        TeachingEvaluationClient,
        parse_timetable,
    )

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
    log.info("0. 退出")
    log.info("========================")


async def _read_menu_choice() -> str | None:
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


async def confirm_evaluation(tasks: Sequence[EvaluationTask]) -> bool:
    log.warning("共有 %d 门课程，一旦提交无法修改", len(tasks))
    for task in tasks:
        log.warning("- %s | %s", task.teacher_name, task.course_name)
    log.warning("若确认继续，请完整输入：%s", CONFIRM_PHRASE)
    user_input = (await aioconsole.ainput("请输入确认语句：")).strip()
    return user_input == CONFIRM_PHRASE


def _show_evaluation_tasks(tasks: Sequence[EvaluationTask]) -> None:
    if not tasks:
        log.info("没有查询到评教任务")
        return
    log.info("评教任务列表：")
    for index, task in enumerate(tasks, start=1):
        status = "已评教" if task.is_evaluated else "未评教"
        log.info(
            "%2d. [%s] %s | %s | %s",
            index,
            status,
            task.course_name,
            task.teacher_name,
            task.questionnaire_name,
        )


def _parse_task_selection(
    raw_choice: str,
    tasks: Sequence[EvaluationTask],
) -> list[EvaluationTask]:
    normalized = raw_choice.strip().lower()
    if normalized in {"all", "a", "全部"}:
        return [task for task in tasks if not task.is_evaluated]

    selected: list[EvaluationTask] = []
    seen: set[int] = set()
    for raw_part in normalized.replace("，", ",").split(","):
        part = raw_part.strip()
        if not part:
            continue
        try:
            index = int(part)
        except ValueError as error:
            msg = "请输入课程序号，多个序号用逗号分隔，或输入 all"
            raise ValueError(msg) from error
        if index < 1 or index > len(tasks):
            msg = f"课程序号超出范围：{index}"
            raise ValueError(msg)
        if index in seen:
            continue
        seen.add(index)
        selected.append(tasks[index - 1])
    return selected


async def choose_evaluation_tasks(
    tasks: Sequence[EvaluationTask],
) -> list[EvaluationTask] | None:
    _show_evaluation_tasks(tasks)
    if not any(not task.is_evaluated for task in tasks):
        log.info("所有课程都已评教")
        return None

    prompt = (
        "请输入要评教的序号，多个用逗号分隔；输入 all 评教全部未评教；输入 0 返回："
    )
    while True:
        choice = (await aioconsole.ainput(prompt)).strip()
        if choice in {"0", "q", "Q"}:
            return None
        try:
            selected = _parse_task_selection(choice, tasks)
        except ValueError as error:
            log.warning("%s", error)
            continue
        selected = [task for task in selected if not task.is_evaluated]
        if selected:
            return selected
        log.warning("没有选中未评教课程，请重新选择")


async def handle_teaching_evaluation(
    jws: AsyncJWSSession,
    settings: Settings,
) -> None:
    data = await fetch_tasks(jws)
    tasks = TeachingEvaluationClient.tasks_from_data(data)
    selected_tasks = await choose_evaluation_tasks(tasks)
    if selected_tasks is None:
        return

    client = TeachingEvaluationClient(
        options=EvaluationOptions(
            default_choice=settings.default_choice,
            comment=settings.default_comment,
            wait_seconds=settings.evaluation_wait_seconds,
            submit_limit=settings.evaluation_limit,
            concurrency=settings.evaluation_concurrency,
        ),
        confirm=confirm_evaluation,
    )
    try:
        submitted = await client.run(jws, data, selected_tasks=selected_tasks)
    except EvaluationCancelledError:
        log.warning("未通过最终确认，已取消评教")
        return
    except EvaluationBatchError as error:
        succeeded = sum(result.succeeded for result in error.results)
        failed = len(error.results) - succeeded
        log.warning("评教结束：成功 %d 门，失败 %d 门", succeeded, failed)
        return

    log.info("评教结束，共提交 %d 门课程", submitted)


async def main() -> None:
    settings = load_settings()
    username, password = settings.require_credentials()

    async with AsyncJWSSession(base_url=settings.base_url) as jws:
        await jws.login(username, password)

        while True:
            menu()
            choice = await _read_menu_choice()
            if choice is None:
                log.info("输入流已关闭，退出")
                return
            if choice == "1":
                await handle_view_timetable(jws)
            elif choice == "2":
                await handle_teaching_evaluation(jws, settings)
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
    except (
        AuthError,
        RuntimeError,
        ServiceError,
        ValueError,
    ) as error:
        _exit_with_error(error)


if __name__ == "__main__":
    run()
