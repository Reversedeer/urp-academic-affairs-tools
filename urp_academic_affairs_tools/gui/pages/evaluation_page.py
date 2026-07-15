"""教学评估"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from urp_academic_affairs_tools.parser.evaluation import EvaluationTask


class EvaluationPage(QWidget):
    def __init__(
        self,
        *,
        on_refresh: Callable[[], None],
        on_submit: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.tasks: list[EvaluationTask] = []
        layout = QVBoxLayout(self)
        title = QLabel("教学评估")
        title.setObjectName("PageTitle")
        subtitle = QLabel("查看所有课程状态，并统一提交未完成的评教任务")
        subtitle.setObjectName("PageSubtitle")
        layout.addWidget(title)
        layout.addWidget(subtitle)
        actions = QHBoxLayout()
        refresh = QPushButton("刷新评教任务")
        refresh.clicked.connect(on_refresh)
        submit = QPushButton("提交全部未评教课程")
        submit.clicked.connect(on_submit)
        actions.addWidget(refresh)
        actions.addWidget(submit)
        actions.addStretch()
        self.loading = QLabel("正在同步评教任务...")
        self.loading.setObjectName("InlineLoading")
        self.loading.hide()
        actions.addWidget(self.loading)
        layout.addLayout(actions)
        cards = QWidget()
        self.cards_layout = QVBoxLayout(cards)
        self.cards_layout.setContentsMargins(4, 4, 4, 4)
        self.cards_layout.setSpacing(10)
        self.cards_layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(cards)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        layout.addWidget(scroll)

    def show_tasks(self, tasks: list[EvaluationTask]) -> None:
        self.tasks = tasks
        self._clear_cards()
        if not tasks:
            empty = QLabel("没有查询到评教任务")
            empty.setObjectName("EmptyState")
            self.cards_layout.insertWidget(0, empty)
            return
        for task in tasks:
            self.cards_layout.insertWidget(
                self.cards_layout.count() - 1,
                self._task_card(task),
            )

    def pending_tasks(self) -> list[EvaluationTask]:
        return [task for task in self.tasks if not task.is_evaluated]

    def _clear_cards(self) -> None:
        while self.cards_layout.count() > 1:
            item = self.cards_layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    @staticmethod
    def _task_card(task: EvaluationTask) -> QFrame:
        card = QFrame()
        card.setObjectName(
            "EvaluationCardDone" if task.is_evaluated else "EvaluationCardPending",
        )
        layout = QHBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        status = QLabel("已完成" if task.is_evaluated else "待评教")
        status.setObjectName("StatusDone" if task.is_evaluated else "StatusPending")
        detail = QVBoxLayout()
        course = QLabel(task.course_name)
        course.setObjectName("EvaluationCourse")
        teacher = QLabel(
            f"教师：{task.teacher_name}    问卷：{task.questionnaire_name}",
        )
        teacher.setObjectName("EvaluationMeta")
        detail.addWidget(course)
        detail.addWidget(teacher)
        layout.addWidget(status)
        layout.addLayout(detail, 1)
        return card
