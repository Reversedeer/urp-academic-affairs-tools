"""教务系统业务接口。"""

from typing import Any

from .session import AsyncJWSSession

TIMETABLE_PATH = "/student/courseSelect/thisSemesterCurriculum/callback"
EVALUATION_TASKS_PATH = "/student/teachingEvaluation/teachingEvaluation/search"


async def get_this_semester_timetable(
    jws: AsyncJWSSession,
) -> dict[str, Any]:
    """获取本学期课表"""
    return await jws.request_json("GET", TIMETABLE_PATH)


async def fetch_tasks(jws: AsyncJWSSession) -> dict[str, Any]:
    """获取评教列表"""
    return await jws.request_json("GET", EVALUATION_TASKS_PATH)
