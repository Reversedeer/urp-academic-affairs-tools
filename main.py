"""入口文件 main"""

import asyncio
import logging

import aioconsole

from client import AsyncJWSSession, fetch_tasks, get_this_semester_timetable
from config import PASSWORD, USERNAME
from export import export_timetable_excel
from parser import TeachingEvaluationClient, parse_timetable

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    force=True,
)
log = logging.getLogger(__name__)


def menu() -> None:
    log.info("========================")
    log.info("欢迎使用教务系统工具")
    log.info("1. 抢课(开发中)")
    log.info("2. 导出课表")
    log.info("3. 教学评估")
    log.info("0. 退出")
    log.info("========================\n")


async def handle_view_timetable(jws: AsyncJWSSession) -> None:
    raw = await get_this_semester_timetable(jws)
    courses = parse_timetable(raw)
    if not courses:
        log.warning("未查询到任何课程")
        return
    out = "本学期课表.xlsx"
    await export_timetable_excel(courses, out)
    log.info(f"本学期课表已导出：{out}")


async def handle_teaching_evaluation(jws: AsyncJWSSession) -> None:
    data = await fetch_tasks(jws)
    await TeachingEvaluationClient().run(jws, data)
    log.info("评教结束")


async def main() -> None:
    async with AsyncJWSSession() as jws:
        await jws.login(USERNAME, PASSWORD)

        while True:
            menu()
            choice = (await aioconsole.ainput("请输入选项：")).strip()

            if choice == "1":
                log.warning("抢课功能尚未实现")

            elif choice == "2":
                await handle_view_timetable(jws)

            elif choice == "3":
                await handle_teaching_evaluation(jws)

            elif choice == "0":
                break

            else:
                log.warning("无效选项")


if __name__ == "__main__":
    asyncio.run(main())
