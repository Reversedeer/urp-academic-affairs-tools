"""api"""

from .session import AsyncJWSSession


async def get_this_semester_timetable(jws: AsyncJWSSession) -> dict:
    """获取本学期课表"""
    return await jws.request_json(
        "GET", "/student/courseSelect/thisSemesterCurriculum/callback"
    )


async def fetch_tasks(jws: AsyncJWSSession) -> dict:
    """获取评教列表"""
    return await jws.request_json(
        "GET", "/student/teachingEvaluation/teachingEvaluation/search"
    )
