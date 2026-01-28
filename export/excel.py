# exporter/excel.py
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment


def export_timetable_excel(courses: list, filename: str):
    wb = Workbook()
    ws = wb.active
    if ws is None:
        return

    ws.title = "课程表"

    headers = [
        "课程",
        "教师",
        "学分",
        "星期",
        "起始节",
        "连上节数",
        "周次",
        "教学楼",
        "教室",
    ]

    ws.append(headers)

    for col in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col)
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center")

    for c in courses:
        ws.append(
            [
                c["course"],
                c["teacher"],
                c["credit"],
                f"星期{c['day']}",
                c["start"],
                c["length"],
                c["weeks"],
                c["building"],
                c["room"],
            ]
        )

    for col in ws.columns:
        width = max(len(str(cell.value)) if cell.value else 0 for cell in col)
        ws.column_dimensions[col[0].column_letter].width = width + 2

    wb.save(filename)
