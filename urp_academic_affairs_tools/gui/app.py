"""URP tools GUI"""

from __future__ import annotations

import asyncio
import ctypes
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlparse

import aiohttp
from PySide6.QtCore import QSettings, QThread, Qt, Signal, QTimer
from PySide6.QtGui import QActionGroup, QColor, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QLineEdit,
    QFrame,
    QGraphicsDropShadowEffect,
    QHeaderView,
    QScrollArea,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from urp_academic_affairs_tools.client import (
    AsyncJWSSession,
    AuthenticationFailure,
    extract_token_value,
    fetch_tasks,
)
from urp_academic_affairs_tools.config import Settings, load_settings
from urp_academic_affairs_tools.course_selection import (
    CourseSelectionCandidate,
    CourseSelectionClient,
    CourseSelectionQuery,
    CourseSnatchingOptions,
    QuitCourseCandidate,
    parse_course_select_page,
)
from urp_academic_affairs_tools.course_selection.course_selection import (
    _format_course_location_from_raw,
    _format_course_schedule_from_raw,
    _resolve_plan_link,
)
from urp_academic_affairs_tools.export import export_timetable_excel
from urp_academic_affairs_tools.parser.evaluation import (
    EvaluationOptions,
    EvaluationTask,
    TeachingEvaluationClient,
)
from urp_academic_affairs_tools.parser.timetable import parse_timetable
from urp_academic_affairs_tools.score_query import (
    ScoreQueryClient,
    ScoreRecord,
    ScoreView,
    filter_score_records,
    score_terms,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine, Sequence

HOME_PAGE_INDEX = 0
COURSE_PAGE_INDEX = 1
DROP_PAGE_INDEX = 2
EVALUATION_PAGE_INDEX = 3
TIMETABLE_PAGE_INDEX = 4
SCORE_PAGE_INDEX = 5
LOGO_PATH = Path(__file__).with_name("assets") / "furina-logo.ico"
WINDOWS_APP_ID = "Reversedeer.URPTools.GUI"


def _set_windows_app_id() -> None:
    if sys.platform != "win32":
        return
    windll = getattr(ctypes, "windll", None)
    if windll is not None:
        windll.shell32.SetCurrentProcessExplicitAppUserModelID(WINDOWS_APP_ID)


MAIN_WINDOW_WIDTH = 1485
MAIN_WINDOW_HEIGHT = 835
SETTINGS_ORGANIZATION = "Reversedeer"
SETTINGS_APPLICATION = "URP Tools"


def _load_known_accounts() -> list[str]:
    """从env加载账号列表"""
    value = QSettings(SETTINGS_ORGANIZATION, SETTINGS_APPLICATION).value(
        "known_accounts",
        [],
    )
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [str(account) for account in value if str(account).strip()]
    return []


def _remember_account(username: str) -> None:
    accounts = _load_known_accounts()
    remembered = [username, *[account for account in accounts if account != username]]
    QSettings(SETTINGS_ORGANIZATION, SETTINGS_APPLICATION).setValue(
        "known_accounts",
        remembered[:5],
    )


def _local_now() -> datetime:
    return datetime.now(timezone.utc).astimezone()


class AsyncWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        operation: Callable[[], Coroutine[Any, Any, Any]],
    ) -> None:
        super().__init__()
        self.operation = operation

    def run(self) -> None:
        try:
            result = asyncio.run(self.operation())
        except Exception as error:  # noqa: BLE001
            self.failed.emit(str(error))
        else:
            self.succeeded.emit(result)


class LoginDialog(QDialog):
    def __init__(
        self,
        settings: Settings,
        accounts: list[str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("登录 URP Tools")
        self.setMinimumWidth(380)
        self.accounts = accounts
        self.username = QLineEdit()
        self.username.setText(settings.username or (accounts[0] if accounts else ""))
        self.switch_account = QPushButton("切换账号")
        self.switch_account.setObjectName("SwitchAccountButton")
        self.switch_account.setVisible(len(accounts) > 1)
        self.switch_account.clicked.connect(self._switch_account)
        self.password = QLineEdit()
        self.password.setFixedHeight(38)
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("请输入密码")
        if settings.password:
            self.password.setText(settings.password)
        form = QFormLayout()
        account_row = QHBoxLayout()
        account_row.addWidget(self.username, 1)
        account_row.addWidget(self.switch_account)
        form.addRow("学号", account_row)
        form.addRow("密码", self.password)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def credentials(self) -> tuple[str, str]:
        return self.username.text().strip(), self.password.text()

    def _switch_account(self) -> None:
        current = self.username.text().strip()
        try:
            index = self.accounts.index(current)
        except ValueError:
            index = -1
        self.username.setText(self.accounts[(index + 1) % len(self.accounts)])


class UrpService:
    def __init__(self, settings: Settings, username: str, password: str) -> None:
        self.settings = settings
        self.username = username
        self.password = password
        self.cookie_jar: aiohttp.CookieJar | None = None
        self.has_authenticated_session = False
        self.session_state = "initial"

    async def session(self) -> AsyncJWSSession:
        if self.cookie_jar is None:
            self.cookie_jar = aiohttp.CookieJar()
        jws = AsyncJWSSession(
            base_url=self.settings.base_url,
            cookie_jar=self.cookie_jar,
        )
        jws.set_reauthentication_callback(self._mark_session_recovered)
        jws.set_session_expired_callback(self._mark_session_expired)
        await jws.start()
        if not await jws.is_logged_in():
            await jws.login(self.username, self.password)
            if self.has_authenticated_session:
                recovered_states = {
                    "concurrent_session_expired": "concurrent_session_recovered",
                    "csrf_token_expired": "csrf_token_recovered",
                }
                self.session_state = recovered_states.get(
                    self.session_state,
                    "recovered",
                )
            else:
                self.session_state = "connected"
        else:
            self.session_state = "valid"
        self.has_authenticated_session = True
        return jws

    def _mark_session_recovered(self) -> None:
        recovered_states = {
            "concurrent_session_expired": "concurrent_session_recovered",
            "csrf_token_expired": "csrf_token_recovered",
        }
        self.session_state = recovered_states.get(self.session_state, "recovered")

    def _mark_session_expired(self, reason: AuthenticationFailure) -> None:
        states = {
            AuthenticationFailure.CONCURRENT_SESSION_EXPIRED: (
                "concurrent_session_expired"
            ),
            AuthenticationFailure.CSRF_TOKEN_EXPIRED: "csrf_token_expired",
        }
        self.session_state = states.get(reason, "expired")

    async def verify_login(self) -> None:
        """登录并验证"""
        async with await self.session() as jws:
            await jws.request_text("GET", "/index.jsp")

    async def courses(self) -> tuple[str, list[CourseSelectionCandidate]]:
        async with await self.session() as jws:
            index_html = await jws.request_text(
                "GET",
                "/student/courseSelect/courseSelect/index",
            )
            client = CourseSelectionClient()
            plan_link, callback_term, selected = await _resolve_plan_link(
                jws,
                index_html,
                client,
            )
            if not plan_link:
                return "", []
            plan_html = await jws.request_text("GET", plan_link)
            page = parse_course_select_page(plan_html)
            plan_number = page.program_plan_number or _query_value(plan_link, "fajhh")
            term = page.academic_term or callback_term
            query = CourseSelectionClient.build_plan_query(
                jhxn=term,
                kcsxdm=page.course_property,
                xqh=page.campus,
            )
            query = CourseSelectionQuery(
                category=query.category,
                params={**query.params, "fajhh": plan_number},
                deal_type=query.deal_type,
                program_plan_number=plan_number,
            )
            candidates = await client.fetch_candidates(jws, query)
            selected_codes = {course.course_code for course in selected}
            return term, [
                course
                for course in candidates
                if course.course_code not in selected_codes
            ]

    async def submit_course(
        self,
        candidate: CourseSelectionCandidate,
        *,
        snatch: bool,
    ) -> str:
        async with await self.session() as jws:
            client = CourseSelectionClient()
            index_html = await jws.request_text(
                "GET",
                "/student/courseSelect/courseSelect/index",
            )
            plan_link, callback_term, _ = await _resolve_plan_link(
                jws,
                index_html,
                client,
            )
            plan_html = await jws.request_text("GET", plan_link)
            page = parse_course_select_page(plan_html)
            plan_number = page.program_plan_number or _query_value(plan_link, "fajhh")
            query = CourseSelectionClient.build_plan_query(
                jhxn=page.academic_term or callback_term,
                kcsxdm=page.course_property,
                xqh=page.campus,
            )
            query = CourseSelectionQuery(
                category=query.category,
                params={**query.params, "fajhh": plan_number},
                deal_type=query.deal_type,
                program_plan_number=plan_number,
            )
            token = extract_token_value(index_html)
            if snatch:
                result = await client.snatch_until_success(
                    jws,
                    query,
                    candidate,
                    options=CourseSnatchingOptions(
                        attempts=self.settings.course_snatching_attempts,
                        concurrency=self.settings.course_snatching_concurrency,
                        retry_interval=self.settings.course_snatching_retry_interval,
                    ),
                    token_value=token,
                )
            else:
                result = await client.submit_once(
                    jws,
                    query,
                    [candidate],
                    token_value=token,
                )
            if not result.succeeded:
                raise RuntimeError(result.result)
            return f"{candidate.display_name} 提交成功"

    async def submit_courses(
        self,
        candidates: Sequence[CourseSelectionCandidate],
        *,
        snatch: bool,
    ) -> str:
        results = [
            await self.submit_course(candidate, snatch=snatch)
            for candidate in candidates
        ]
        return "\n".join(results)

    async def selected_courses(
        self,
    ) -> tuple[str, list[QuitCourseCandidate]]:
        async with await self.session() as jws:
            client = CourseSelectionClient()
            return await client.fetch_selected_courses_with_term(jws)

    async def drop_course(self, course: QuitCourseCandidate) -> str:
        async with await self.session() as jws:
            client = CourseSelectionClient()
            return await client.delete_one(
                jws,
                fajhh=course.program_plan_number,
                course_number=course.course_number,
                sequence_number=course.sequence_number,
            )

    async def evaluate(self, tasks: Sequence[EvaluationTask]) -> int:
        async with await self.session() as jws:
            data = await fetch_tasks(jws)
            client = TeachingEvaluationClient(
                options=EvaluationOptions(
                    default_choice=self.settings.default_choice,
                    comment=self.settings.default_comment,
                    wait_seconds=self.settings.evaluation_wait_seconds,
                    submit_limit=self.settings.evaluation_limit,
                    concurrency=self.settings.evaluation_concurrency,
                ),
                confirm=lambda _tasks: _true_async(),
            )
            return await client.run(jws, data, selected_tasks=tasks)

    async def timetable(self, filename: str) -> str:
        async with await self.session() as jws:
            data = await jws.request_json(
                "GET",
                "/student/courseSelect/thisSemesterCurriculum/callback",
            )
            courses = parse_timetable(data)
            output = await export_timetable_excel(courses, Path(filename))
            return str(output)

    async def scores(self, view: ScoreView) -> list[ScoreRecord]:
        async with await self.session() as jws:
            return await ScoreQueryClient(jws).query(view)


async def _true_async() -> bool:
    return True


def _query_value(path: str, key: str) -> str:
    values = parse_qs(urlparse(path).query).get(key, [])
    return values[0] if values else ""


class MainWindow(QMainWindow):
    def __init__(
        self,
        settings: Settings,
        username: str,
        password: str,
        *,
        service: UrpService | None = None,
    ) -> None:
        super().__init__()
        self.settings = settings
        self.service = service or UrpService(settings, username, password)
        self.workers: dict[str, AsyncWorker] = {}
        self.courses: list[CourseSelectionCandidate] = []
        self.course_checks: list[QCheckBox] = []
        self.selected_courses: list[QuitCourseCandidate] = []
        self.evaluation_tasks: list[EvaluationTask] = []
        self.score_records: list[ScoreRecord] = []
        self.passing_score_records: list[ScoreRecord] = []
        self.score_cache: dict[ScoreView, list[ScoreRecord]] = {}
        self.current_passing_term = ""
        self.courses_loaded = False
        self.course_snatch_enabled = False
        self.selected_courses_loaded = False
        self.evaluation_loaded = False
        self.scores_loaded = False
        self.current_score_view = ScoreView.PASSING
        self.logged_out = False
        self.account_label: QLabel
        self.account_status: QLabel
        self.course_loading: QLabel
        self.drop_loading: QLabel
        self.drop_term: QLabel
        self.evaluation_loading: QLabel
        self.timetable_loading: QLabel
        self.scores_loading: QLabel
        self.login_time_label: QLabel
        self.current_time_label: QLabel
        self.login_time = _local_now()
        self.clock_timer = QTimer(self)
        self.setWindowTitle("URP Tools")
        self.setFixedSize(MAIN_WINDOW_WIDTH, MAIN_WINDOW_HEIGHT)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowMaximizeButtonHint,
        )
        self._build_ui()

    def _build_ui(self) -> None:  # noqa: PLR0915
        self.nav = QListWidget()
        self.nav.addItems(["首页", "抢课", "退课", "教学评估", "课表导出", "成绩查询"])
        self.nav.setObjectName("Navigation")
        self.nav.setFixedWidth(188)
        account_card = QFrame()
        account_card.setObjectName("AccountCard")
        account_layout = QVBoxLayout(account_card)
        account_layout.setContentsMargins(14, 14, 14, 14)
        account_caption = QLabel("账户")
        account_caption.setObjectName("AccountCaption")
        self.account_label = QLabel(self.service.username)
        self.account_label.setObjectName("AccountName")
        self.account_status = QLabel("已登录 · 会话有效")
        self.account_status.setObjectName("AccountStatus")
        glow = QGraphicsDropShadowEffect(self)
        glow.setBlurRadius(26)
        glow.setColor(QColor(63, 90, 84, 48))
        glow.setOffset(0, 8)
        account_card.setGraphicsEffect(glow)
        logout = QPushButton("退出登录")
        logout.setObjectName("LogoutButton")
        logout.clicked.connect(self.logout)
        account_layout.addWidget(account_caption)
        account_layout.addWidget(self.account_label)
        account_layout.addWidget(self.account_status)
        account_layout.addWidget(logout)
        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(208)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(12, 14, 12, 14)
        sidebar_layout.addWidget(account_card)
        sidebar_layout.addWidget(self.nav, 1)
        clock = QFrame()
        clock.setObjectName("ClockCard")
        clock_layout = QVBoxLayout(clock)
        clock_layout.setContentsMargins(12, 9, 12, 9)
        clock_layout.setSpacing(3)
        self.login_time_label = QLabel()
        self.login_time_label.setObjectName("LoginTime")
        self.login_time_label.setWordWrap(True)
        self.current_time_label = QLabel()
        self.current_time_label.setObjectName("CurrentTime")
        self.current_time_label.setWordWrap(True)
        clock_layout.addWidget(self.login_time_label)
        clock_layout.addWidget(self.current_time_label)
        sidebar_layout.addWidget(clock)
        self.pages = QStackedWidget()
        self.pages.addWidget(self._home_page())
        self.pages.addWidget(self._course_page())
        self.pages.addWidget(self._drop_page())
        self.pages.addWidget(self._evaluation_page())
        self.pages.addWidget(self._timetable_page())
        self.pages.addWidget(self._score_page())
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.nav.currentRowChanged.connect(self._on_page_changed)
        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(12)
        body_layout.addWidget(sidebar)
        body_layout.addWidget(self.pages, 1)
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addWidget(body, 1)
        self.setCentralWidget(root)
        self._update_clock()
        self.clock_timer.timeout.connect(self._update_clock)
        self.clock_timer.start(100)
        self.nav.setCurrentRow(HOME_PAGE_INDEX)

    def _home_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addStretch(2)
        title = QLabel("URP Academic Affairs Tools")
        title.setObjectName("HomeTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle = QLabel("从左侧选择功能开始使用")
        subtitle.setObjectName("HomeSubtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addStretch(3)
        return page

    def _course_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        row = QHBoxLayout()
        refresh = QPushButton("刷新课程")
        refresh.clicked.connect(self.refresh_courses)
        self.course_mode = QToolButton()
        self.course_mode.setObjectName("CourseMode")
        self.course_mode.setText("...")
        self.course_mode.setToolTip("选课模式")
        self.course_mode.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        mode_menu = QMenu(self.course_mode)
        normal_mode = mode_menu.addAction("普通选课")
        continuous_mode = mode_menu.addAction("持续抢课")
        self.course_mode_actions = QActionGroup(self.course_mode)
        self.course_mode_actions.setExclusive(True)
        for action in (normal_mode, continuous_mode):
            action.setCheckable(True)
            self.course_mode_actions.addAction(action)
        normal_mode.setChecked(True)
        self.normal_mode_action = normal_mode
        self.continuous_mode_action = continuous_mode
        normal_mode.triggered.connect(lambda: self._set_course_mode(snatch=False))
        continuous_mode.triggered.connect(lambda: self._set_course_mode(snatch=True))
        self.course_mode.setMenu(mode_menu)
        submit = QPushButton("提交选中课程")
        submit.clicked.connect(self.submit_selected_course)
        row.addWidget(refresh)
        row.addWidget(submit)
        row.addStretch()
        self.course_loading = QLabel("正在加载课程...")
        self.course_loading.setObjectName("InlineLoading")
        self.course_loading.hide()
        row.addWidget(self.course_loading)
        row.addWidget(self.course_mode)
        layout.addLayout(row)
        self.course_term = QLabel("当前计划学年学期：未加载")
        self.course_term.setObjectName("CourseTerm")
        layout.addWidget(self.course_term)
        self.course_table = QTableWidget(0, 9)
        self.course_table.setHorizontalHeaderLabels(
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
        self.course_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.course_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.course_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.course_table.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded,
        )
        self.course_table.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded,
        )
        self.course_table.setAlternatingRowColors(True)
        self._configure_table(self.course_table, [42, 270, 45, 75, 75, 105, 55, 195, 0])
        layout.addWidget(self.course_table)
        return page

    def _drop_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        refresh = QPushButton("刷新数据")
        refresh.clicked.connect(self.refresh_selected_courses)
        drop = QPushButton("退课")
        drop.clicked.connect(self.drop_selected_course)
        row = QHBoxLayout()
        row.addWidget(refresh)
        row.addWidget(drop)
        row.addStretch()
        self.drop_loading = QLabel("正在加载已选课程...")
        self.drop_loading.setObjectName("InlineLoading")
        self.drop_loading.hide()
        row.addWidget(self.drop_loading)
        layout.addLayout(row)
        self.drop_term = QLabel("当前计划学年学期：未加载")
        self.drop_term.setObjectName("CourseTerm")
        layout.addWidget(self.drop_term)
        self.drop_table = QTableWidget(0, 6)
        self.drop_table.setHorizontalHeaderLabels(
            ["课程", "教师", "学分", "选课方式", "上课时间", "上课地点"],
        )
        self.drop_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.drop_table.setAlternatingRowColors(True)
        self._configure_table(self.drop_table, [310, 120, 55, 100, 240, 0])
        layout.addWidget(self.drop_table)
        return page

    @staticmethod
    def _configure_table(table: QTableWidget, widths: list[int]) -> None:
        header = table.horizontalHeader()
        for index, width in enumerate(widths):
            if index == len(widths) - 1:
                header.setSectionResizeMode(index, QHeaderView.ResizeMode.Stretch)
            else:
                header.setSectionResizeMode(index, QHeaderView.ResizeMode.Fixed)
                header.resizeSection(index, width)
        header.setStretchLastSection(True)
        table.setWordWrap(True)
        table.setTextElideMode(Qt.TextElideMode.ElideNone)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(40)

    def _update_clock(self) -> None:
        self.login_time_label.setText(
            "登录时间\n" + self.login_time.strftime("%Y-%m-%d %H:%M:%S")
        )
        self.current_time_label.setText(
            "当前时间\n" + _local_now().strftime("%Y-%m-%d %H:%M:%S")
        )

    def _set_course_mode(self, *, snatch: bool) -> None:
        self.course_snatch_enabled = snatch
        self.normal_mode_action.setChecked(not snatch)
        self.continuous_mode_action.setChecked(snatch)
        mode_name = "持续抢课" if snatch else "普通选课"
        self.course_mode.setToolTip(f"选课模式：{mode_name}")

    def _evaluation_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        title = QLabel("教学评估")
        title.setObjectName("PageTitle")
        subtitle = QLabel("查看所有课程状态，并统一提交未完成的评教任务")
        subtitle.setObjectName("PageSubtitle")
        layout.addWidget(title)
        layout.addWidget(subtitle)
        refresh = QPushButton("刷新评教任务")
        refresh.clicked.connect(self.refresh_evaluations)
        submit = QPushButton("提交全部未评教课程")
        submit.clicked.connect(self.submit_evaluations)
        row = QHBoxLayout()
        row.addWidget(refresh)
        row.addWidget(submit)
        row.addStretch()
        self.evaluation_loading = QLabel("正在同步评教任务...")
        self.evaluation_loading.setObjectName("InlineLoading")
        self.evaluation_loading.hide()
        row.addWidget(self.evaluation_loading)
        layout.addLayout(row)
        self.evaluation_cards = QWidget()
        self.evaluation_cards_layout = QVBoxLayout(self.evaluation_cards)
        self.evaluation_cards_layout.setContentsMargins(4, 4, 4, 4)
        self.evaluation_cards_layout.setSpacing(10)
        self.evaluation_cards_layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.evaluation_cards)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        layout.addWidget(scroll)
        return page

    def _timetable_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        export = QPushButton("导出本学期课表")
        export.clicked.connect(self.export_timetable)
        row = QHBoxLayout()
        row.addWidget(export)
        row.addStretch()
        self.timetable_loading = QLabel("正在生成课表文件...")
        self.timetable_loading.setObjectName("InlineLoading")
        self.timetable_loading.hide()
        row.addWidget(self.timetable_loading)
        layout.addLayout(row)
        layout.addStretch()
        return page

    def _score_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        title = QLabel("成绩查询")
        title.setObjectName("PageTitle")
        subtitle = QLabel("默认展示当前学期；可按学年学期筛选全部及格成绩")
        subtitle.setObjectName("PageSubtitle")
        layout.addWidget(title)
        layout.addWidget(subtitle)
        row = QHBoxLayout()
        this_term = QPushButton("本学期成绩")
        this_term.setObjectName("ScoreAction")
        this_term.clicked.connect(lambda: self.show_score_view(ScoreView.THIS_TERM))
        unpassed = QPushButton("不及格成绩")
        unpassed.setObjectName("ScoreAction")
        unpassed.clicked.connect(lambda: self.show_score_view(ScoreView.UNPASSED))
        self.passing_scores = QToolButton()
        self.passing_scores.setObjectName("PassingScores")
        self.passing_scores.setText("历年成绩查询")
        self.passing_scores.setPopupMode(
            QToolButton.ToolButtonPopupMode.MenuButtonPopup,
        )
        self.passing_scores.clicked.connect(self.show_default_passing_scores)
        self.passing_menu = QMenu(self.passing_scores)
        self.passing_menu.addAction("正在加载学期...").setEnabled(False)
        self.passing_scores.setMenu(self.passing_menu)
        refresh_history = QPushButton("刷新")
        refresh_history.setObjectName("ScoreAction")
        refresh_history.clicked.connect(self.refresh_current_scores)
        for button in (this_term, unpassed):
            row.addWidget(button)
        row.addWidget(self.passing_scores)
        row.addStretch()
        row.addWidget(refresh_history)
        self.scores_loading = QLabel("正在加载成绩...")
        self.scores_loading.setObjectName("InlineLoading")
        self.scores_loading.hide()
        row.addWidget(self.scores_loading)
        layout.addLayout(row)
        self.score_notice = QLabel()
        self.score_notice.setObjectName("ScoreNotice")
        self.score_notice.hide()
        layout.addWidget(self.score_notice)
        self.score_table = QTableWidget(0, 8)
        self.score_table.setHorizontalHeaderLabels(
            [
                "序号",
                "课程名",
                "课程号",
                "学分",
                "成绩",
                "课程属性",
                "考试类型",
                "未通过原因",
            ],
        )
        self.score_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.score_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.score_table.setAlternatingRowColors(True)
        self._configure_table(
            self.score_table,
            [55, 285, 100, 55, 70, 125, 100, 0],
        )
        layout.addWidget(self.score_table)
        return page

    def _run(
        self,
        key: str,
        operation: Callable[[], Coroutine[Any, Any, Any]],
        callback: Callable[[Any], None],
        *,
        loading_label: QLabel | None = None,
    ) -> None:
        current = self.workers.get(key)
        if current is not None and current.isRunning():
            return
        if loading_label is not None:
            loading_label.show()
        worker = AsyncWorker(operation)
        self.workers[key] = worker
        worker.succeeded.connect(
            lambda result, key=key, worker=worker: self._finish_worker(
                key,
                worker,
                callback,
                result,
            )
        )
        worker.failed.connect(
            lambda message, key=key, worker=worker: self._fail_worker(
                key,
                worker,
                message,
            )
        )
        worker.finished.connect(
            lambda key=key, worker=worker, label=loading_label: self._cleanup_worker(
                key,
                worker,
                label,
            )
        )
        worker.start()

    def _finish_worker(
        self,
        key: str,
        worker: AsyncWorker,
        callback: Callable[[object], None],
        result: object,
    ) -> None:
        if self.workers.get(key) is not worker:
            return
        callback(result)
        self._update_account_status()

    def _fail_worker(self, key: str, worker: AsyncWorker, message: str) -> None:
        if self.workers.get(key) is not worker:
            return
        self._failed(message)

    def _cleanup_worker(
        self,
        key: str,
        worker: AsyncWorker,
        loading_label: QLabel | None,
    ) -> None:
        if self.workers.get(key) is worker:
            self.workers.pop(key, None)
        if loading_label is not None:
            loading_label.hide()
        worker.deleteLater()

    def _update_account_status(self) -> None:
        if self.service.session_state == "concurrent_session_recovered":
            self.account_status.setText("检测到异地登录 · 会话已重新登录")
        elif self.service.session_state == "csrf_token_recovered":
            self.account_status.setText("请求令牌已失效 · 认证已恢复")
        elif self.service.session_state == "recovered":
            self.account_status.setText("会话已恢复 · 已重新登录")
        else:
            self.account_status.setText("已登录 · 会话有效")

    def _failed(self, message: str) -> None:
        QMessageBox.critical(self, "任务失败", message)
        self.account_status.setText("请求失败 · 请重试")

    def _show_info(self, title: str, message: str) -> None:
        QMessageBox.information(self, title, message)

    def refresh_courses(self) -> None:
        self._run(
            "courses",
            self.service.courses,
            self._show_courses,
            loading_label=self.course_loading,
        )

    def _show_courses(
        self,
        result: tuple[str, list[CourseSelectionCandidate]],
    ) -> None:
        term, courses = result
        self.courses_loaded = True
        self.courses = courses
        self.course_checks = []
        self.course_term.setText(f"当前计划学年学期：{term or '未知'}")
        self.course_table.setRowCount(0)
        for course in courses:
            row = self.course_table.rowCount()
            self.course_table.insertRow(row)
            raw = course.raw or {}
            task_check = QCheckBox()
            task_check.setObjectName("CourseTaskCheck")
            task_holder = QWidget()
            task_layout = QHBoxLayout(task_holder)
            task_layout.setContentsMargins(0, 0, 0, 0)
            task_layout.addStretch()
            task_layout.addWidget(task_check)
            task_layout.addStretch()
            self.course_table.setCellWidget(row, 0, task_holder)
            self.course_checks.append(task_check)
            values: list[str] = [
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
            centered_columns = {2, 3, 4, 5, 6}
            for column, value in enumerate(values, start=1):
                item = QTableWidgetItem(value)
                if column in centered_columns:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.course_table.setItem(row, column, item)

    def submit_selected_course(self) -> None:
        rows = self._checked_course_rows()
        if not rows:
            QMessageBox.information(self, "未选择课程", "请勾选要提交的课程任务")
            return
        courses = [self.courses[row] for row in rows]
        snatch = self.course_snatch_enabled
        self._run(
            "course_submit",
            lambda: self.service.submit_courses(courses, snatch=snatch),
            lambda message: self._show_info("提交结果", message),
            loading_label=self.course_loading,
        )

    def _checked_course_rows(self) -> list[int]:
        return [
            row for row, check in enumerate(self.course_checks) if check.isChecked()
        ]

    def refresh_selected_courses(self) -> None:
        self._run(
            "drop_courses",
            self.service.selected_courses,
            self._show_selected_courses,
            loading_label=self.drop_loading,
        )

    def _show_selected_courses(
        self,
        result: tuple[str, list[QuitCourseCandidate]],
    ) -> None:
        term, courses = result
        self.selected_courses_loaded = True
        self.selected_courses = courses
        self.drop_term.setText(f"当前计划学年学期：{term or '未知'}")
        self.drop_table.setRowCount(0)
        for course in courses:
            row = self.drop_table.rowCount()
            self.drop_table.insertRow(row)
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
                self.drop_table.setItem(row, column, item)

    def drop_selected_course(self) -> None:
        row = self.drop_table.currentRow()
        if row < 0 or row >= len(self.selected_courses):
            QMessageBox.information(self, "未选择课程", "请先选择一门课程")
            return
        course = self.selected_courses[row]
        self._run(
            "course_drop",
            lambda: self.service.drop_course(course),
            lambda result: self._show_info("退课结果", result),
            loading_label=self.drop_loading,
        )

    def refresh_evaluations(self) -> None:
        async def operation() -> list[EvaluationTask]:
            async with await self.service.session() as jws:
                data = await fetch_tasks(jws)
                return TeachingEvaluationClient.tasks_from_data(data)

        self._run(
            "evaluations",
            operation,
            self._show_evaluations,
            loading_label=self.evaluation_loading,
        )

    def _show_evaluations(self, tasks: list[EvaluationTask]) -> None:
        self.evaluation_loaded = True
        self.evaluation_tasks = tasks
        self._clear_evaluation_cards()
        if not tasks:
            empty = QLabel("没有查询到评教任务")
            empty.setObjectName("EmptyState")
            self.evaluation_cards_layout.insertWidget(0, empty)
            return
        for task in tasks:
            self.evaluation_cards_layout.insertWidget(
                self.evaluation_cards_layout.count() - 1,
                self._evaluation_card(task),
            )

    def _clear_evaluation_cards(self) -> None:
        while self.evaluation_cards_layout.count() > 1:
            item = self.evaluation_cards_layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    @staticmethod
    def _evaluation_card(task: EvaluationTask) -> QFrame:
        card = QFrame()
        card.setObjectName(
            "EvaluationCardDone" if task.is_evaluated else "EvaluationCardPending"
        )
        layout = QHBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        status = QLabel("已完成" if task.is_evaluated else "待评教")
        status.setObjectName("StatusDone" if task.is_evaluated else "StatusPending")
        detail = QVBoxLayout()
        course = QLabel(task.course_name)
        course.setObjectName("EvaluationCourse")
        teacher = QLabel(
            f"教师：{task.teacher_name}    问卷：{task.questionnaire_name}"
        )
        teacher.setObjectName("EvaluationMeta")
        detail.addWidget(course)
        detail.addWidget(teacher)
        layout.addWidget(status)
        layout.addLayout(detail, 1)
        return card

    def logout(self) -> None:
        answer = QMessageBox.question(
            self,
            "退出登录",
            "退出后将清除当前会话并返回登录窗口，确定继续吗？",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.service.cookie_jar = None
        self.logged_out = True
        self.close()

    def submit_evaluations(self) -> None:
        if not self.evaluation_tasks:
            QMessageBox.information(self, "没有任务", "请先刷新评教任务")
            return
        pending = [task for task in self.evaluation_tasks if not task.is_evaluated]
        if not pending:
            QMessageBox.information(
                self, "评教状态", "当前没有待评教课程，可能已经全部完成"
            )
            return
        answer = QMessageBox.question(
            self,
            "确认提交",
            f"将提交 {len(pending)} 门未评教课程，继续吗？",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._run(
            "evaluation_submit",
            lambda: self.service.evaluate(pending),
            lambda count: self._show_info("评教结果", f"成功提交 {count} 门课程"),
            loading_label=self.evaluation_loading,
        )

    def export_timetable(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "导出课表",
            "本学期课表.xlsx",
            "Excel 文件 (*.xlsx)",
        )
        if filename:
            self._run(
                "timetable_export",
                lambda: self.service.timetable(filename),
                lambda output: self._show_info("导出完成", output),
                loading_label=self.timetable_loading,
            )

    def refresh_scores(self, view: ScoreView = ScoreView.PASSING) -> None:
        self.current_score_view = view
        self._run(
            f"scores:{view.value}",
            lambda: self.service.scores(view),
            lambda records: self._show_scores(view, records),
            loading_label=self.scores_loading,
        )

    def refresh_current_scores(self) -> None:
        """刷新缓存"""
        self.refresh_scores(self.current_score_view)

    def show_score_view(self, view: ScoreView) -> None:
        """优先展示缓存，首次访问某类成绩时才发起查询"""
        self.current_score_view = view
        cached = self.score_cache.get(view)
        if cached is None:
            self.refresh_scores(view)
            return
        self._show_scores(view, cached)

    def show_default_passing_scores(self) -> None:
        """显示当前学期的及格成绩"""
        if not self.passing_score_records:
            self.refresh_scores(ScoreView.PASSING)
            return
        terms = score_terms(self.passing_score_records)
        self._set_passing_term(terms[0].value if terms else "")

    def _show_scores(self, view: ScoreView, records: list[ScoreRecord]) -> None:
        self.scores_loaded = True
        self.score_cache[view] = records
        self.score_records = records
        if view is ScoreView.PASSING:
            self.passing_score_records = records
            self._populate_score_terms(records)
            terms = score_terms(records)
            self._set_passing_term(terms[0].value if terms else "")
            return
        if view is ScoreView.UNPASSED and not records:
            self.score_notice.setText("没有不及格的成绩")
            self.score_notice.show()
        elif view is ScoreView.UNPASSED:
            self.score_notice.hide()
        else:
            self.score_notice.hide()
        self._show_score_records(view, records)

    def _show_score_records(
        self,
        view: ScoreView,
        records: list[ScoreRecord],
    ) -> None:
        self.score_table.setRowCount(0)
        self._configure_score_table(view)
        for record in records:
            row = self.score_table.rowCount()
            self.score_table.insertRow(row)
            values = self._score_row_values(view, record)
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if view is ScoreView.THIS_TERM:
                    align_center = column != 0
                else:
                    align_center = column not in {0, 1, 3}
                if align_center:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.score_table.setItem(row, column, item)

    @staticmethod
    def _score_row_values(view: ScoreView, record: ScoreRecord) -> list[str]:
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
            widths = [250, 100, 60, 120, 90, 90, 90, 65, 65, 0]
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
        self.score_table.setColumnCount(len(headers))
        self.score_table.setHorizontalHeaderLabels(headers)
        self._configure_table(self.score_table, widths)

    def _populate_score_terms(self, records: list[ScoreRecord]) -> None:
        terms = score_terms(records)
        self.passing_menu.clear()
        all_terms = self.passing_menu.addAction("全部")
        all_terms.triggered.connect(lambda: self._set_passing_term(""))
        for term in terms:
            action = self.passing_menu.addAction(term.label)
            action.triggered.connect(
                self._term_selection_callback(term.value),
            )

    def _term_selection_callback(self, term_key: str) -> Callable[[], None]:
        def callback() -> None:
            self._set_passing_term(term_key)

        return callback

    def _set_passing_term(self, term_key: str) -> None:
        self.current_score_view = ScoreView.PASSING
        self.current_passing_term = term_key
        self.passing_scores.setToolTip(
            "历年成绩查询："
            + next(
                (
                    term.label
                    for term in score_terms(self.passing_score_records)
                    if term.value == term_key
                ),
                "全部",
            ),
        )
        self._show_score_records(
            ScoreView.PASSING,
            filter_score_records(self.passing_score_records, term_key),
        )

    def _on_page_changed(self, index: int) -> None:
        if index == COURSE_PAGE_INDEX and not self.courses_loaded:
            self.refresh_courses()
        elif index == DROP_PAGE_INDEX and not self.selected_courses_loaded:
            self.refresh_selected_courses()
        elif index == EVALUATION_PAGE_INDEX and not self.evaluation_loaded:
            self.refresh_evaluations()
        elif index == SCORE_PAGE_INDEX and not self.scores_loaded:
            self.show_score_view(ScoreView.THIS_TERM)


def _load_stylesheet() -> str:
    return """
    QWidget { font-family: 'Segoe UI', 'Microsoft YaHei'; font-size: 13px; color: #30403c; }
    QMainWindow, QWidget { background: #eaf3ef; }
    QWidget#Sidebar { background: rgba(225, 240, 233, 225); border: 1px solid rgba(255, 255, 255, 180); border-radius: 16px; }
    QFrame#AccountCard { background: rgba(255, 255, 255, 185); border: 1px solid rgba(255, 255, 255, 220); border-radius: 13px; }
    QFrame#ClockCard { background: rgba(255, 255, 255, 125); border: 1px solid rgba(255, 255, 255, 175); border-radius: 11px; }
    QLabel#AccountCaption { color: #7f938b; font-size: 11px; font-weight: 600; }
    QLabel#AccountName { color: #28443b; font-size: 16px; font-weight: 700; }
    QLabel#AccountStatus { color: #4d9278; background: rgba(221, 241, 231, 150); border-radius: 7px; font-size: 12px; padding: 4px 6px; }
    QLabel#LoginTime, QLabel#CurrentTime { color: #56766b; font-size: 12px; font-weight: 600; }
    QPushButton#LogoutButton { background: rgba(244, 250, 247, 160); border: 1px solid rgba(133, 165, 150, 110); color: #557269; padding: 7px 10px; }
    QPushButton#LogoutButton:hover { background: rgba(255, 255, 255, 230); border-color: #8aa99b; }
    QListWidget#Navigation { background: transparent; color: #587168; border: 0; padding: 2px; }
    QListWidget#Navigation::item { padding: 12px 11px; border-radius: 10px; margin: 2px 0; }
    QListWidget#Navigation::item:hover { background: rgba(255, 255, 255, 120); }
    QListWidget#Navigation::item:selected { background: rgba(255, 255, 255, 205); color: #286b56; font-weight: 700; }
    QPushButton { background: #4d9a80; color: white; border: 1px solid rgba(255, 255, 255, 100); border-radius: 9px; padding: 9px 14px; font-weight: 600; }
    QPushButton:hover { background: #3d876e; }
    QPushButton#SwitchAccountButton { background: rgba(244, 250, 247, 180); color: #517368; border: 1px solid rgba(133, 165, 150, 120); padding: 7px 10px; }
    QPushButton#SwitchAccountButton:hover { background: rgba(255, 255, 255, 230); }
    QToolButton#CourseMode { min-width: 30px; max-width: 30px; min-height: 30px; max-height: 30px; background: transparent; border: 0; padding: 0 0 4px; color: #527368; font-size: 16px; font-weight: 700; }
    QToolButton#CourseMode:hover { background: rgba(255, 255, 255, 130); border-radius: 15px; color: #2f6f59; }
    QToolButton#CourseMode::menu-indicator { image: none; width: 0; }
    QPushButton#ScoreAction, QToolButton#PassingScores { min-width: 106px; max-width: 106px; min-height: 32px; max-height: 32px; background: #4d9a80; color: white; border: 1px solid rgba(255, 255, 255, 100); border-radius: 8px; padding: 0 8px; font-weight: 600; }
    QPushButton#ScoreAction:hover, QToolButton#PassingScores:hover { background: #3d876e; }
    QToolButton#PassingScores::menu-indicator { image: none; width: 0; }
    QMenu { background: #f6fbf8; border: 1px solid #a9c8ba; border-radius: 8px; padding: 5px; color: #41675a; }
    QMenu::item { padding: 8px 24px 8px 12px; border-radius: 5px; }
    QMenu::item:selected { background: #dcefe6; }
    QComboBox#ScoreTerm { background: rgba(255, 255, 255, 175); border: 1px solid rgba(155, 190, 174, 135); border-radius: 9px; padding: 8px 10px; color: #41675a; }
    QComboBox#ScoreTerm:hover { background: rgba(255, 255, 255, 225); border-color: #82ae9d; }
    QComboBox#ScoreTerm::drop-down { width: 24px; border: 0; border-left: 1px solid rgba(155, 190, 174, 110); }
    QComboBox#ScoreTerm QAbstractItemView { background: #f6fbf8; border: 1px solid #a9c8ba; border-radius: 8px; padding: 4px; selection-background-color: #dcefe6; selection-color: #365b4e; }
    QTableWidget { background: rgba(255, 255, 255, 185); border: 1px solid rgba(255, 255, 255, 215); border-radius: 12px; gridline-color: rgba(195, 215, 205, 100); }
    QTableWidget::item:hover { background: rgba(211, 232, 221, 135); color: #30403c; }
    QTableWidget::item:selected { background: rgba(202, 228, 214, 170); color: #30403c; }
    QScrollBar:vertical { background: transparent; border: 0; width: 10px; margin: 7px 2px; }
    QScrollBar::handle:vertical { background: rgba(87, 128, 112, 125); min-height: 36px; margin: 0 1px; border: 0; border-radius: 4px; }
    QScrollBar::handle:vertical:hover { background: rgba(66, 109, 93, 175); }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
    QScrollBar:horizontal { background: transparent; border: 0; height: 10px; margin: 2px 7px; }
    QScrollBar::handle:horizontal { background: rgba(87, 128, 112, 125); min-width: 36px; margin: 1px 0; border: 0; border-radius: 4px; }
    QScrollBar::handle:horizontal:hover { background: rgba(66, 109, 93, 175); }
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }
    QCheckBox#CourseTaskCheck::indicator { width: 14px; height: 14px; border: 1px solid #92aca1; border-radius: 4px; background: rgba(255, 255, 255, 190); }
    QCheckBox#CourseTaskCheck::indicator:checked { background: #4d9a80; border-color: #4d9a80; }
    QHeaderView::section { background: rgba(233, 244, 238, 185); padding: 9px; border: 0; font-weight: 600; color: #426258; }
    QLabel#PageTitle { font-size: 25px; font-weight: 700; color: #365b4e; }
    QLabel#PageSubtitle { color: #738a80; padding-bottom: 10px; }
    QLabel#HomeTitle { color: #365b4e; font-size: 30px; font-weight: 700; letter-spacing: 1px; }
    QLabel#HomeSubtitle { color: #769087; font-size: 15px; padding-top: 8px; }
    QLabel#CourseTerm { color: #477565; font-weight: 600; padding: 4px 0 8px; }
    QLabel#ScoreNotice { color: #5e8374; background: rgba(255, 255, 255, 135); border-radius: 8px; padding: 7px 10px; }
    QLabel#InlineLoading { color: #4a806d; background: rgba(255, 255, 255, 170); border: 1px solid rgba(178, 205, 192, 150); border-radius: 10px; padding: 5px 10px; font-weight: 600; }
    QFrame#EvaluationCardPending, QFrame#EvaluationCardDone { background: rgba(255, 255, 255, 185); border-radius: 13px; border: 1px solid rgba(255, 255, 255, 220); }
    QFrame#EvaluationCardPending { border-left: 4px solid #5aaf90; }
    QFrame#EvaluationCardDone { border-left: 4px solid #93b8a8; }
    QLabel#StatusPending { color: #33775f; background: #e1f2ea; border-radius: 12px; padding: 5px 10px; font-weight: 700; }
    QLabel#StatusDone { color: #6d8d80; background: #edf4f0; border-radius: 12px; padding: 5px 10px; font-weight: 700; }
    QLabel#EvaluationCourse { font-size: 15px; font-weight: 700; color: #38594e; }
    QLabel#EvaluationMeta { color: #7b9187; padding-top: 3px; }
    QLabel#EmptyState { color: #71877e; font-size: 15px; padding: 38px; }
    """


def run_gui() -> None:
    _set_windows_app_id()
    app = QApplication(sys.argv)
    app.setApplicationName("URP Tools")
    app.setApplicationVersion("0.3.2")
    app.setOrganizationName("Reversedeer")
    app.setWindowIcon(QIcon(str(LOGO_PATH)))
    app.setStyleSheet(_load_stylesheet())
    settings = load_settings()
    while True:
        dialog = LoginDialog(settings, _load_known_accounts())
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        username, password = dialog.credentials()
        if not username or not password:
            QMessageBox.critical(None, "登录信息缺失", "学号和密码不能为空")
            continue
        service = UrpService(settings, username, password)
        try:
            asyncio.run(service.verify_login())
        except Exception as error:  # noqa: BLE001
            QMessageBox.critical(None, "登录失败", str(error))
            continue
        _remember_account(username)
        window = MainWindow(settings, username, password, service=service)
        window.show()
        app.exec()
        if not window.logged_out:
            return
