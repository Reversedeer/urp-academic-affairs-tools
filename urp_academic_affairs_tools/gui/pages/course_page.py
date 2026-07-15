"""抢课"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from PySide6.QtCore import Qt
from PySide6.QtGui import QActionGroup
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from urp_academic_affairs_tools.course_selection.course_selection import (
    _format_course_location_from_raw,
    _format_course_schedule_from_raw,
)
from urp_academic_affairs_tools.gui.widgets.table_utils import configure_table

if TYPE_CHECKING:
    from collections.abc import Callable

    from urp_academic_affairs_tools.course_selection import CourseSelectionCandidate


class ModeChanged(Protocol):
    def __call__(self, *, snatch: bool) -> None: ...


class CoursePage(QWidget):
    def __init__(
        self,
        *,
        on_refresh: Callable[[], None],
        on_submit: Callable[[], None],
        on_mode_changed: ModeChanged,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.courses: list[CourseSelectionCandidate] = []
        self.checks: list[QCheckBox] = []
        layout = QVBoxLayout(self)
        actions = QHBoxLayout()
        refresh = QPushButton("刷新课程")
        refresh.clicked.connect(on_refresh)
        submit = QPushButton("提交选中课程")
        submit.clicked.connect(on_submit)
        actions.addWidget(refresh)
        actions.addWidget(submit)
        actions.addStretch()
        self.loading = QLabel("正在加载课程...")
        self.loading.setObjectName("InlineLoading")
        self.loading.hide()
        actions.addWidget(self.loading)
        self.mode_button = QToolButton()
        self.mode_button.setObjectName("CourseMode")
        self.mode_button.setText("...")
        self.mode_button.setToolTip("选课模式")
        self.mode_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.mode_button)
        self.normal_mode_action = menu.addAction("普通选课")
        self.continuous_mode_action = menu.addAction("持续抢课")
        mode_group = QActionGroup(self.mode_button)
        mode_group.setExclusive(True)
        for action in (self.normal_mode_action, self.continuous_mode_action):
            action.setCheckable(True)
            mode_group.addAction(action)
        self.normal_mode_action.setChecked(True)
        self.normal_mode_action.triggered.connect(
            lambda: on_mode_changed(snatch=False),
        )
        self.continuous_mode_action.triggered.connect(
            lambda: on_mode_changed(snatch=True),
        )
        self.mode_button.setMenu(menu)
        actions.addWidget(self.mode_button)
        layout.addLayout(actions)
        self.term = QLabel("当前计划学年学期：未加载")
        self.term.setObjectName("CourseTerm")
        layout.addWidget(self.term)
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(
            [
                "任务",
                "课程",
                "学分",
                "课程类别",
                "课程属性",
                "教师",
                "课余量",
                "上课时间",
                "上课地点",
            ],
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.table.setAlternatingRowColors(True)
        configure_table(self.table, [42, 270, 45, 75, 75, 105, 55, 195, 0])
        layout.addWidget(self.table)

    def set_mode(self, *, snatch: bool) -> None:
        self.normal_mode_action.setChecked(not snatch)
        self.continuous_mode_action.setChecked(snatch)
        mode_name = "持续抢课" if snatch else "普通选课"
        self.mode_button.setToolTip(f"选课模式：{mode_name}")

    def show_courses(
        self,
        term: str,
        courses: list[CourseSelectionCandidate],
    ) -> None:
        self.courses = courses
        self.checks = []
        self.term.setText(f"当前计划学年学期：{term or '未知'}")
        self.table.setRowCount(0)
        for course in courses:
            row = self.table.rowCount()
            self.table.insertRow(row)
            task_check = QCheckBox()
            task_check.setObjectName("CourseTaskCheck")
            holder = QWidget()
            holder_layout = QHBoxLayout(holder)
            holder_layout.setContentsMargins(0, 0, 0, 0)
            holder_layout.addStretch()
            holder_layout.addWidget(task_check)
            holder_layout.addStretch()
            self.table.setCellWidget(row, 0, holder)
            self.checks.append(task_check)
            raw = course.raw or {}
            values = [
                course.display_name,
                str(raw.get("unit") or raw.get("xf") or raw.get("credit") or ""),
                str(
                    raw.get("kclbmc")
                    or raw.get("kclbm")
                    or raw.get("courseCategory")
                    or ""
                ),
                str(
                    raw.get("kcsxmc")
                    or raw.get("kcsxdm")
                    or raw.get("courseAttribute")
                    or ""
                ),
                course.teacher_name.replace("*", ""),
                str(raw.get("bkskyl") or raw.get("kyl") or raw.get("remaining") or ""),
                _format_course_schedule_from_raw(raw),
                _format_course_location_from_raw(raw),
            ]
            for column, value in enumerate(values, start=1):
                item = QTableWidgetItem(value)
                if column in {2, 3, 4, 5, 6}:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, column, item)

    def selected_courses(self) -> list[CourseSelectionCandidate]:
        return [
            course
            for course, check in zip(self.courses, self.checks, strict=True)
            if check.isChecked()
        ]
