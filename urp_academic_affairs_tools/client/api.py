"""教务系统业务接口"""

from typing import Any

from .session import AsyncJWSSession

TIMETABLE_PATH = "/student/courseSelect/thisSemesterCurriculum/callback"
EVALUATION_TASKS_PATH = "/student/teachingEvaluation/teachingEvaluation/search"
COURSE_SELECT_INDEX_PATH = "/student/courseSelect/courseSelect/index"
COURSE_SELECT_RESULT_INDEX_PATH = "/student/courseSelect/courseSelectResult/index"
COURSE_SELECT_SUBMIT_PATH = "/student/courseSelect/selectCourse/checkInputCodeAndSubmit"
COURSE_SELECT_DELETE_ONE_PATH = "/student/courseSelect/delCourse/deleteOne"
COURSE_SELECT_LIST_PATHS = {
    "department": "/student/courseSelect/departCourse/courseList",
    "free": "/student/courseSelect/freeCourse/courseList",
    "plan": "/student/courseSelect/planCourse/courseList",
    "school": "/student/courseSelect/schoolCourse/courseList",
}


async def get_this_semester_timetable(
    jws: AsyncJWSSession,
) -> dict[str, Any]:
    """获取本学期课表"""
    return await jws.request_json("GET", TIMETABLE_PATH)


async def fetch_tasks(jws: AsyncJWSSession) -> dict[str, Any]:
    """获取评教列表"""
    return await jws.request_json("GET", EVALUATION_TASKS_PATH)


async def fetch_course_select_index(jws: AsyncJWSSession) -> str:
    """获取选课首页 HTML"""
    return await jws.request_text("GET", COURSE_SELECT_INDEX_PATH)


async def fetch_course_select_result_index(jws: AsyncJWSSession) -> str:
    """获取选课结果页 HTML"""
    return await jws.request_text("GET", COURSE_SELECT_RESULT_INDEX_PATH)


async def fetch_course_select_page(
    jws: AsyncJWSSession,
    path: str,
) -> str:
    """获取某个选课分类页 HTML"""
    return await jws.request_text("GET", path)


async def fetch_course_select_list(
    jws: AsyncJWSSession,
    category: str,
    params: dict[str, str],
) -> str:
    """获取某个选课分类的课程列表 HTML"""
    try:
        path = COURSE_SELECT_LIST_PATHS[category]
    except KeyError as error:
        msg = f"unsupported course select category: {category}"
        raise ValueError(msg) from error
    return await jws.request_text("POST", path, data=params)


async def submit_course_selection(
    jws: AsyncJWSSession,
    form: dict[str, str],
) -> dict[str, Any]:
    """提交选课表单"""
    return await jws.request_json("POST", COURSE_SELECT_SUBMIT_PATH, data=form)


async def delete_course_selection(
    jws: AsyncJWSSession,
    *,
    fajhh: str,
    kch: str,
    kxh: str,
    token_value: str,
) -> str:
    """删除已选课程"""
    return await jws.request_text(
        "POST",
        COURSE_SELECT_DELETE_ONE_PATH,
        data={
            "fajhh": fajhh,
            "kch": kch,
            "kxh": kxh,
            "tokenValue": token_value,
        },
    )
