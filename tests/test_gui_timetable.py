"""课表页面展示测试"""

from __future__ import annotations

import os
import unittest
from typing import TYPE_CHECKING, ClassVar

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from urp_academic_affairs_tools.config import Settings
from urp_academic_affairs_tools.gui.app import MainWindow
from urp_academic_affairs_tools.gui.widgets.timetable_grid import (
    LUNCH_BREAK_ROW,
    TIMETABLE_TABLE_ROW_COUNT,
)

if TYPE_CHECKING:
    from urp_academic_affairs_tools.parser.timetable import TimetableEntry


class TimetablePageTests(unittest.TestCase):
    app: ClassVar[QApplication]

    @classmethod
    def setUpClass(cls) -> None:
        existing_app = QApplication.instance()
        cls.app = (
            existing_app if isinstance(existing_app, QApplication) else QApplication([])
        )

    @staticmethod
    def _entry(
        course_name: str,
        sequence: str,
        *,
        day: int,
        start_session: int,
        duration: int = 2,
    ) -> TimetableEntry:
        return {
            "course_name": course_name,
            "course_sequence_number": sequence,
            "teacher": "李老师",
            "day": day,
            "start_session": start_session,
            "duration": duration,
            "weeks": "1-16",
            "week_desc": "1-16周",
            "campus": "",
            "building": "教学楼A",
            "classroom": "101",
            "credit": "3",
        }

    def test_renders_times_lunch_gap_and_stable_course_colors(self) -> None:
        window = MainWindow(
            Settings(username="tester", password="secret"),  # noqa: S106
            "tester",
            "secret",
        )
        self.addCleanup(window.close)
        window.timetable_page.show_entries(
            [
                self._entry("高等数学", "01", day=1, start_session=1),
                self._entry("高等数学", "01", day=3, start_session=5),
                self._entry("大学英语", "02", day=2, start_session=1),
                self._entry("文学阅读", "03", day=4, start_session=11, duration=1),
            ],
        )

        table = window.timetable_page.grid
        first_math = table.cellWidget(0, 1)
        afternoon_math = table.cellWidget(5, 3)
        english = table.cellWidget(0, 2)
        lunch_label = table.cellWidget(LUNCH_BREAK_ROW, 1)
        single_course = table.cellWidget(11, 4)
        first_session_item = table.item(0, 0)
        lunch_item = table.item(LUNCH_BREAK_ROW, 0)

        self.assertEqual(table.rowCount(), TIMETABLE_TABLE_ROW_COUNT)
        if first_session_item is None:
            self.fail("课表缺少第一节的时间标签")
        if lunch_item is None:
            self.fail("课表缺少午休时间标签")
        self.assertEqual(first_session_item.text(), "第1节\n08:30–09:15")
        self.assertEqual(lunch_item.text(), "午休")
        self.assertEqual(table.rowHeight(LUNCH_BREAK_ROW), 22)
        self.assertEqual(table.rowSpan(0, 1), 2)
        self.assertEqual(table.rowSpan(5, 3), 2)
        self.assertIsInstance(first_math, QLabel)
        self.assertIsInstance(afternoon_math, QLabel)
        self.assertIsInstance(english, QLabel)
        if not isinstance(lunch_label, QLabel):
            self.fail("午休行缺少完整时间说明")
        if not isinstance(single_course, QLabel):
            self.fail("第 11 节缺少课程内容")
        self.assertEqual(lunch_label.text(), "午休 · 11:55–13:30")
        self.assertEqual(
            single_course.text(),
            "文学阅读_03\n李老师 · 第11节\n1-16周 · 教学楼A",
        )
        self.assertIn("教学楼A 101", single_course.toolTip())
        self.assertEqual(first_math.styleSheet(), afternoon_math.styleSheet())
        self.assertNotEqual(first_math.styleSheet(), english.styleSheet())


if __name__ == "__main__":
    unittest.main()
