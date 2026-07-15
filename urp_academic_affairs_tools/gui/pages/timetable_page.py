from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from urp_academic_affairs_tools.gui.widgets.timetable_grid import TimetableGrid

if TYPE_CHECKING:
    from collections.abc import Callable

    from urp_academic_affairs_tools.parser.timetable import TimetableEntry


class TimetablePage(QWidget):
    def __init__(
        self,
        *,
        on_refresh: Callable[[], None],
        on_export: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.entries: list[TimetableEntry] = []
        self.loaded = False
        layout = QVBoxLayout(self)
        title = QLabel("本学期课表")
        title.setObjectName("PageTitle")
        subtitle = QLabel("按星期与节次展示课程；同一课程的多条上课安排会分别显示")
        subtitle.setObjectName("PageSubtitle")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        actions = QHBoxLayout()
        refresh = QPushButton("刷新课表")
        refresh.clicked.connect(on_refresh)
        export = QPushButton("导出本学期课表")
        export.clicked.connect(on_export)
        actions.addWidget(refresh)
        actions.addWidget(export)
        actions.addStretch()
        self.loading = QLabel("正在加载课表...")
        self.loading.setObjectName("InlineLoading")
        self.loading.hide()
        actions.addWidget(self.loading)
        layout.addLayout(actions)

        self.notice = QLabel()
        self.notice.setObjectName("TimetableNotice")
        self.notice.hide()
        layout.addWidget(self.notice)
        self.grid = TimetableGrid()
        layout.addWidget(self.grid, 1)

    def show_entries(self, entries: list[TimetableEntry]) -> None:
        self.loaded = True
        self.entries = entries
        invalid_count = self.grid.render_entries(entries)
        if not entries:
            self.notice.setText("没有查询到本学期课程")
            self.notice.show()
        elif invalid_count:
            self.notice.setText(
                f"已显示 {len(entries) - invalid_count} 条上课安排；"
                f"{invalid_count} 条缺少星期或节次，未绘制",
            )
            self.notice.show()
        else:
            self.notice.hide()
