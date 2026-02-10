"""获取并解析课表数据的模块"""

from typing import Any


def parse_timetable(data: dict[str, Any]) -> list[dict[str, Any]]:
    """
    从教务系统返回的 JSON中解析出课表明细
    """
    result: list[dict[str, Any]] = []

    xkxx_list = data.get("xkxx", [])
    if not xkxx_list:
        return result

    for course_map in xkxx_list:
        if not isinstance(course_map, dict):
            continue

        for course in course_map.values():
            course_name = course.get("courseName", "")
            teacher = course.get("attendClassTeacher", "").strip()
            credit = course.get("unit", 0)

            time_list = course.get("timeAndPlaceList", [])
            if not time_list:
                continue

            result.extend(
                {
                    "course_name": course_name,
                    "teacher": teacher,
                    "day": t.get("classDay"),
                    "start_session": t.get("classSessions"),
                    "duration": t.get("continuingSession"),
                    "weeks": t.get("classWeek"),
                    "week_desc": t.get("weekDescription"),
                    "campus": t.get("campusName"),
                    "building": t.get("teachingBuildingName"),
                    "classroom": t.get("classroomName"),
                    "credit": credit,
                }
                for t in time_list
            )

    return result
