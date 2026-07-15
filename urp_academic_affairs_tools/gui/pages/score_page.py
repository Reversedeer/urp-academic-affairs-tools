from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
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

from urp_academic_affairs_tools.gui.widgets.table_utils import configure_table
from urp_academic_affairs_tools.score_query import (
    ScoreRecord,
    ScoreView,
    calculate_average_grade_point,
    filter_score_records,
    score_terms,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine, Sequence


class ScoreService(Protocol):
    async def scores(self, view: ScoreView) -> list[ScoreRecord]: ...


class RunTask(Protocol):
    def __call__(
        self,
        key: str,
        operation: Callable[[], Coroutine[Any, Any, Any]],
        callback: Callable[[Any], None],
        *,
        loading_label: QLabel | None = None,
    ) -> None: ...


class ScorePage(QWidget):
    def __init__(  # noqa: PLR0915
        self,
        service: ScoreService,
        run_task: RunTask,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self._run_task = run_task
        self.records: list[ScoreRecord] = []
        self.passing_records: list[ScoreRecord] = []
        self.cache: dict[ScoreView, list[ScoreRecord]] = {}
        self.current_passing_term = ""
        self.current_view = ScoreView.PASSING
        self.loaded = False
        layout = QVBoxLayout(self)
        title = QLabel("成绩查询")
        title.setObjectName("PageTitle")
        subtitle = QLabel("默认展示当前学期；可按学年学期筛选全部及格成绩")
        subtitle.setObjectName("PageSubtitle")
        layout.addWidget(title)
        layout.addWidget(subtitle)
        actions = QHBoxLayout()
        this_term = QPushButton("本学期成绩")
        this_term.setObjectName("ScoreAction")
        this_term.clicked.connect(lambda: self.show_view(ScoreView.THIS_TERM))
        unpassed = QPushButton("不及格成绩")
        unpassed.setObjectName("ScoreAction")
        unpassed.clicked.connect(lambda: self.show_view(ScoreView.UNPASSED))
        self.passing_scores = QToolButton()
        self.passing_scores.setObjectName("PassingScores")
        self.passing_scores.setText("历年成绩查询")
        self.passing_scores.setPopupMode(
            QToolButton.ToolButtonPopupMode.MenuButtonPopup,
        )
        self.passing_scores.clicked.connect(self.show_default_passing)
        self.passing_menu = QMenu(self.passing_scores)
        self.passing_menu.addAction("正在加载学期...").setEnabled(False)
        self.passing_scores.setMenu(self.passing_menu)
        refresh = QPushButton("刷新")
        refresh.setObjectName("ScoreAction")
        refresh.clicked.connect(self.refresh_current)
        for button in (this_term, unpassed):
            actions.addWidget(button)
        actions.addWidget(self.passing_scores)
        actions.addStretch()
        actions.addWidget(refresh)
        self.loading = QLabel("正在加载成绩...")
        self.loading.setObjectName("InlineLoading")
        self.loading.hide()
        actions.addWidget(self.loading)
        layout.addLayout(actions)
        layout.addLayout(self._gpa_summary_row())
        self.notice = QLabel()
        self.notice.setObjectName("ScoreNotice")
        self.notice.hide()
        layout.addWidget(self.notice)
        self.table = QTableWidget(0, 8)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.setAlternatingRowColors(True)
        configure_table(
            self.table,
            [55, 285, 100, 55, 70, 125, 100, 0],
        )
        layout.addWidget(self.table)

    def load_if_needed(self) -> None:
        if not self.loaded:
            self.show_view(ScoreView.THIS_TERM)

    def refresh(self, view: ScoreView = ScoreView.PASSING) -> None:
        self.current_view = view
        self._run_task(
            f"scores:{view.value}",
            lambda: self.service.scores(view),
            lambda records: self.show_scores(view, records),
            loading_label=self.loading,
        )

    def refresh_current(self) -> None:
        self.refresh(self.current_view)

    def show_view(self, view: ScoreView) -> None:
        self.current_view = view
        cached = self.cache.get(view)
        if cached is None:
            self.refresh(view)
            return
        self.show_scores(view, cached)

    def show_default_passing(self) -> None:
        if not self.passing_records:
            self.refresh(ScoreView.PASSING)
            return
        terms = score_terms(self.passing_records)
        self._set_passing_term(terms[0].value if terms else "")

    def show_scores(self, view: ScoreView, records: list[ScoreRecord]) -> None:
        self.loaded = True
        self.cache[view] = records
        self.records = records
        if view is ScoreView.PASSING:
            self.passing_records = records
            self._populate_terms(records)
            self._update_cumulative_gpa()
            terms = score_terms(records)
            self._set_passing_term(terms[0].value if terms else "")
            return
        self._update_cumulative_gpa()
        if view is ScoreView.THIS_TERM:
            self._load_cumulative_scores()
        if view is ScoreView.UNPASSED and not records:
            self.notice.setText("没有不及格的成绩")
            self.notice.show()
        else:
            self.notice.hide()
        self._show_records(view, records)

    def _show_records(self, view: ScoreView, records: list[ScoreRecord]) -> None:
        self._update_selected_term_gpa(records)
        self.table.setRowCount(0)
        self._configure_score_table(view)
        for record in records:
            row = self.table.rowCount()
            self.table.insertRow(row)
            for column, value in enumerate(self._row_values(view, record)):
                item = QTableWidgetItem(value)
                align_center = (
                    column != 0
                    if view is ScoreView.THIS_TERM
                    else column not in {0, 1, 3}
                )
                if align_center:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, column, item)

    def _load_cumulative_scores(self) -> None:
        if ScoreView.PASSING in self.cache:
            return
        self._run_task(
            "cumulative_gpa_scores",
            lambda: self.service.scores(ScoreView.PASSING),
            self._cache_cumulative_scores,
        )

    def _cache_cumulative_scores(self, records: list[ScoreRecord]) -> None:
        self.cache[ScoreView.PASSING] = records
        self.passing_records = records
        self._populate_terms(records)
        self._update_cumulative_gpa()

    def _gpa_summary_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.cumulative_average_gpa = QLabel("累计平均学分绩点：--")
        self.cumulative_average_gpa.setObjectName("CumulativeAverageGpa")
        self.cumulative_average_gpa.setToolTip(
            "按全部及格成绩中的必修、限选等非任选课程加权计算",
        )
        self.selected_term_average_gpa = QLabel("当前学期平均学分绩点：--")
        self.selected_term_average_gpa.setObjectName("SelectedTermAverageGpa")
        self.selected_term_average_gpa.setToolTip(
            "按当前选中学期中必修、限选等非任选课程加权计算",
        )
        row.addWidget(self.cumulative_average_gpa)
        row.addSpacing(28)
        row.addWidget(self.selected_term_average_gpa)
        row.addStretch()
        return row

    def _update_cumulative_gpa(self) -> None:
        cumulative = calculate_average_grade_point(self.passing_records)
        text = cumulative if cumulative is not None else "--"
        self.cumulative_average_gpa.setText(f"累计平均学分绩点：{text}")

    def _update_selected_term_gpa(self, records: Sequence[ScoreRecord]) -> None:
        average = calculate_average_grade_point(records)
        text = average if average is not None else "--"
        self.selected_term_average_gpa.setText(f"当前学期平均学分绩点：{text}")

    @staticmethod
    def _row_values(view: ScoreView, record: ScoreRecord) -> list[str]:
        if view is ScoreView.PASSING:
            return [
                record.academic_term,
                record.course_name,
                record.course_number,
                record.course_attribute,
                record.exam_type,
                record.credit,
                record.grade_point,
                record.score,
            ]
        if view is ScoreView.THIS_TERM:
            return [
                record.course_name,
                record.course_number,
                record.credit,
                record.course_attribute,
                record.maximum_score,
                record.minimum_score,
                record.average_score,
                record.grade_point,
                record.score,
                record.rank,
                record.unpassed_reason,
            ]
        return [
            record.academic_term,
            record.course_name,
            record.course_number,
            record.credit,
            record.score,
            record.grade_point,
            record.course_attribute,
            record.exam_type,
        ]

    def _configure_score_table(self, view: ScoreView) -> None:
        if view is ScoreView.PASSING:
            headers = [
                "学年学期",
                "课程名",
                "课程号",
                "课程属性",
                "考试类型",
                "学分",
                "绩点",
                "成绩",
            ]
            widths = [160, 280, 100, 125, 100, 65, 65, 0]
        elif view is ScoreView.THIS_TERM:
            headers = [
                "课程",
                "课程号",
                "学分",
                "课程属性",
                "课程最高分",
                "课程最低分",
                "课程平均分",
                "绩点",
                "成绩",
                "名次",
                "未通过原因",
            ]
            widths = [250, 100, 60, 120, 90, 90, 90, 65, 65, 65, 0]
        else:
            headers = [
                "学年学期",
                "课程",
                "课程号",
                "学分",
                "成绩",
                "绩点",
                "课程属性",
                "考试类型",
            ]
            widths = [150, 270, 95, 55, 65, 65, 130, 0]
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        configure_table(self.table, widths)

    def _populate_terms(self, records: list[ScoreRecord]) -> None:
        self.passing_menu.clear()
        all_terms = self.passing_menu.addAction("全部")
        all_terms.triggered.connect(lambda: self._set_passing_term(""))
        for term in score_terms(records):
            action = self.passing_menu.addAction(term.label)
            action.triggered.connect(self._term_callback(term.value))

    def _term_callback(self, term_key: str) -> Callable[[], None]:
        def callback() -> None:
            self._set_passing_term(term_key)

        return callback

    def _set_passing_term(self, term_key: str) -> None:
        self.current_view = ScoreView.PASSING
        self.current_passing_term = term_key
        self.passing_scores.setToolTip(
            "历年成绩查询："
            + next(
                (
                    term.label
                    for term in score_terms(self.passing_records)
                    if term.value == term_key
                ),
                "全部",
            ),
        )
        self._show_records(
            ScoreView.PASSING,
            filter_score_records(self.passing_records, term_key),
        )
