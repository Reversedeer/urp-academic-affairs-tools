"""导出课表到 Excel 文件"""

from typing import Any, Dict, List, Union
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter


def export_timetable_excel(
    timetable_data: Union[Dict[str, Any], List[Any]], filename: str
):
    """
    导出课表到 Excel
    """
    if isinstance(timetable_data, dict):
        xkxx = timetable_data.get("xkxx", [])
    else:
        xkxx = timetable_data

    courses: List[Dict[str, Any]] = []
    parsed_mode = False
    if isinstance(xkxx, list) and xkxx:
        first = xkxx[0]
        if isinstance(first, dict) and (
            "course_name" in first or "courseName" in first
        ):
            parsed_mode = True

    if parsed_mode:
        courses = xkxx
    else:
        for item in xkxx or []:
            if isinstance(item, dict):
                for v in item.values():
                    if isinstance(v, dict):
                        courses.append(v)

    wb = Workbook()
    ws = wb.active
    if ws is None:
        return
    ws.title = "本学期课表"

    headers = [
        "课程名称",
        "任课教师",
        "学分",
        "星期",
        "节次",
        "周次",
        "教学楼",
        "教室",
    ]
    ws.append(headers)

    header_style = Font(bold=True)
    align_center = Alignment(horizontal="center", vertical="center", wrap_text=True)

    for col in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col)
        cell.font = header_style
        cell.alignment = align_center
        ws.column_dimensions[get_column_letter(col)].width = 16

    for item in courses:
        course_name = item.get("course_name", "")
        teacher = (item.get("teacher") or "").replace("*", "").strip()
        credit = item.get("credit", "")
        day = _weekday_to_cn(item.get("day", ""))
        section = _format_section(
            item.get("start_session", ""),
            item.get("duration", ""),
        )
        week = item.get("week_desc") or item.get("weeks") or ""
        building = item.get("building") or item.get("teachingBuildingName") or ""
        room = item.get("classroom") or ""

        ws.append(
            [
                course_name,
                teacher,
                credit,
                day,
                section,
                week,
                building,
                room,
            ]
        )

    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = align_center

    wb.save(filename)


def _weekday_to_cn(day: int) -> str:
    mapping = {
        1: "周一",
        2: "周二",
        3: "周三",
        4: "周四",
        5: "周五",
        6: "周六",
        7: "周日",
    }
    return mapping.get(day, "")


def _format_section(start: int, length: int) -> str:
    if not start or not length:
        return ""
    end = start + length - 1
    return f"{start}-{end}节"
