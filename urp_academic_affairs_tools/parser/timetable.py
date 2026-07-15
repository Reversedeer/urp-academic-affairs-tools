"""解析课表明细"""

from collections.abc import Iterator, Mapping
from typing import TypedDict


class TimetableEntry(TypedDict):
    course_name: str
    course_sequence_number: str
    teacher: str
    day: int | None
    start_session: int | None
    duration: int | None
    weeks: object
    week_desc: str
    campus: str
    building: str
    classroom: str
    credit: object


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _iter_courses(data: Mapping[str, object]) -> Iterator[Mapping[str, object]]:
    course_groups = data.get("xkxx", [])
    if not isinstance(course_groups, list):
        return

    for group in course_groups:
        if not isinstance(group, Mapping):
            continue
        yield from (course for course in group.values() if isinstance(course, Mapping))


def _build_entry(
    course: Mapping[str, object],
    time_and_place: Mapping[str, object],
) -> TimetableEntry:
    identifier = course.get("id")
    identifier_data = identifier if isinstance(identifier, Mapping) else {}
    return {
        "course_name": _clean_text(course.get("courseName")),
        "course_sequence_number": _clean_text(
            course.get("coureSequenceNumber")
            or course.get("courseSequenceNumber")
            or course.get("classNum")
            or time_and_place.get("coureSequenceNumber")
            or identifier_data.get("coureSequenceNumber"),
        ),
        "teacher": _clean_text(course.get("attendClassTeacher")),
        "day": _optional_int(time_and_place.get("classDay")),
        "start_session": _optional_int(time_and_place.get("classSessions")),
        "duration": _optional_int(time_and_place.get("continuingSession")),
        "weeks": time_and_place.get("classWeek", ""),
        "week_desc": _clean_text(time_and_place.get("weekDescription")),
        "campus": _clean_text(time_and_place.get("campusName")),
        "building": _clean_text(time_and_place.get("teachingBuildingName")),
        "classroom": _clean_text(time_and_place.get("classroomName")),
        "credit": course.get("unit", ""),
    }


def parse_timetable(data: Mapping[str, object]) -> list[TimetableEntry]:
    """解析课表数据"""
    result: list[TimetableEntry] = []
    for course in _iter_courses(data):
        time_and_place_list = course.get("timeAndPlaceList", [])
        if not isinstance(time_and_place_list, list):
            continue
        result.extend(
            _build_entry(course, time_and_place)
            for time_and_place in time_and_place_list
            if isinstance(time_and_place, Mapping)
        )
    return result
