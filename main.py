"""入口文件 main"""

import logging
import asyncio
import aioconsole


from client import AsyncJWSSession, get_this_semester_timetable, fetch_tasks
from export import export_timetable_excel
from parser import TeachingEvaluationClient, parse_timetable
from config import USERNAME, PASSWORD

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    force=True,
)
log = logging.getLogger(__name__)


def menu():
    print("========================")
    print("欢迎使用教务系统工具")
    print("1. 抢课(开发中)")
    print("2. 导出课表")
    print("3. 教学评估")
    print("0. 退出")
    print("========================\n")


async def handle_view_timetable(jws: AsyncJWSSession):
    raw = await get_this_semester_timetable(jws)
    courses = parse_timetable(raw)
    if not courses:
        log.warning("未查询到任何课程")
        return
    out = "本学期课表.xlsx"
    await export_timetable_excel(courses, out)
    log.info(f"本学期课表已导出：{out}")


async def handle_teaching_evaluation(jws: AsyncJWSSession):
    data = await fetch_tasks(jws)
    await TeachingEvaluationClient().run(jws, data)
    log.info("评教结束")


async def main():
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
