"""退课"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from urp_academic_affairs_tools.gui.widgets.table_utils import configure_table

if TYPE_CHECKING:
    from collections.abc import Callable

    from urp_academic_affairs_tools.course_selection import QuitCourseCandidate


class DropPage(QWidget):
    def __init__(
        self,
        *,
        on_refresh: Callable[[], None],
        on_drop: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.courses: list[QuitCourseCandidate] = []
        layout = QVBoxLayout(self)
        actions = QHBoxLayout()
        refresh = QPushButton("刷新数据")
        refresh.clicked.connect(on_refresh)
        drop = QPushButton("退课")
        drop.clicked.connect(on_drop)
        actions.addWidget(refresh)
        actions.addWidget(drop)
        actions.addStretch()
        self.loading = QLabel("正在加载已选课程...")
        self.loading.setObjectName("InlineLoading")
        self.loading.hide()
        actions.addWidget(self.loading)
        layout.addLayout(actions)
        self.term = QLabel("当前计划学年学期：未加载")
        self.term.setObjectName("CourseTerm")
        layout.addWidget(self.term)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["课程", "教师", "学分", "选课方式", "上课时间", "上课地点"],
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        configure_table(self.table, [310, 120, 55, 100, 240, 0])
        layout.addWidget(self.table)

    def show_courses(self, term: str, courses: list[QuitCourseCandidate]) -> None:
        self.courses = courses
        self.term.setText(f"当前计划学年学期：{term or '未知'}")
        self.table.setRowCount(0)
        for course in courses:
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [
                course.display_name,
                course.teacher_name.replace("*", ""),
                course.credit,
                course.selection_mode,
                course.schedule_text,
                course.location_text,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column in {1, 2, 3}:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, column, item)

    def selected_course(self) -> QuitCourseCandidate | None:
        row = self.table.currentRow()
        return self.courses[row] if 0 <= row < len(self.courses) else None
