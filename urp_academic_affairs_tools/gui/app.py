"""URP tools GUI"""

from __future__ import annotations

import asyncio
import ctypes
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QLineEdit,
    QFrame,
    QGraphicsDropShadowEffect,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from urp_academic_affairs_tools.client import (
    fetch_tasks,
)
from urp_academic_affairs_tools.config import load_settings
from urp_academic_affairs_tools.export import export_timetable_excel
from urp_academic_affairs_tools.parser.evaluation import TeachingEvaluationClient

from .core import AsyncWorker
from .pages.course_page import CoursePage
from .pages.drop_page import DropPage
from .pages.evaluation_page import EvaluationPage
from .pages.home_page import HomePage
from .pages.score_page import ScorePage
from .pages.timetable_page import TimetablePage
from .services import UrpService
from .style import load_stylesheet

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from urp_academic_affairs_tools.config import Settings
    from urp_academic_affairs_tools.course_selection import (
        CourseSelectionCandidate,
        QuitCourseCandidate,
    )
    from urp_academic_affairs_tools.parser.evaluation import EvaluationTask
    from urp_academic_affairs_tools.parser.timetable import TimetableEntry

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
        self.courses_loaded = False
        self.course_snatch_enabled = False
        self.selected_courses_loaded = False
        self.evaluation_loaded = False
        self.logged_out = False
        self.account_label: QLabel
        self.account_status: QLabel
        self.timetable_page: TimetablePage
        self.score_page: ScorePage
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
        self.nav.addItems(["首页", "抢课", "退课", "教学评估", "课表", "成绩查询"])
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
        self.pages.addWidget(HomePage())
        self.course_page = CoursePage(
            on_refresh=self.refresh_courses,
            on_submit=self.submit_selected_course,
            on_mode_changed=self._set_course_mode,
        )
        self.drop_page = DropPage(
            on_refresh=self.refresh_selected_courses,
            on_drop=self.drop_selected_course,
        )
        self.evaluation_page = EvaluationPage(
            on_refresh=self.refresh_evaluations,
            on_submit=self.submit_evaluations,
        )
        self.pages.addWidget(self.course_page)
        self.pages.addWidget(self.drop_page)
        self.pages.addWidget(self.evaluation_page)
        self.timetable_page = TimetablePage(
            on_refresh=self.refresh_timetable,
            on_export=self.export_timetable,
        )
        self.score_page = ScorePage(self.service, self._run)
        self.pages.addWidget(self.timetable_page)
        self.pages.addWidget(self.score_page)
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

    def _update_clock(self) -> None:
        self.login_time_label.setText(
            "登录时间\n" + self.login_time.strftime("%Y-%m-%d %H:%M:%S")
        )
        self.current_time_label.setText(
            "当前时间\n" + _local_now().strftime("%Y-%m-%d %H:%M:%S")
        )

    def _set_course_mode(self, *, snatch: bool) -> None:
        self.course_snatch_enabled = snatch
        self.course_page.set_mode(snatch=snatch)

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
            loading_label=self.course_page.loading,
        )

    def _show_courses(
        self,
        result: tuple[str, list[CourseSelectionCandidate]],
    ) -> None:
        term, courses = result
        self.courses_loaded = True
        self.course_page.show_courses(term, courses)

    def submit_selected_course(self) -> None:
        courses = self.course_page.selected_courses()
        if not courses:
            QMessageBox.information(self, "未选择课程", "请勾选要提交的课程任务")
            return
        snatch = self.course_snatch_enabled
        self._run(
            "course_submit",
            lambda: self.service.submit_courses(courses, snatch=snatch),
            lambda message: self._show_info("提交结果", message),
            loading_label=self.course_page.loading,
        )

    def refresh_selected_courses(self) -> None:
        self._run(
            "drop_courses",
            self.service.selected_courses,
            self._show_selected_courses,
            loading_label=self.drop_page.loading,
        )

    def _show_selected_courses(
        self,
        result: tuple[str, list[QuitCourseCandidate]],
    ) -> None:
        term, courses = result
        self.selected_courses_loaded = True
        self.drop_page.show_courses(term, courses)

    def drop_selected_course(self) -> None:
        course = self.drop_page.selected_course()
        if course is None:
            QMessageBox.information(self, "未选择课程", "请先选择一门课程")
            return
        self._run(
            "course_drop",
            lambda: self.service.drop_course(course),
            lambda result: self._show_info("退课结果", result),
            loading_label=self.drop_page.loading,
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
            loading_label=self.evaluation_page.loading,
        )

    def _show_evaluations(self, tasks: list[EvaluationTask]) -> None:
        self.evaluation_loaded = True
        self.evaluation_page.show_tasks(tasks)

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
        if not self.evaluation_page.tasks:
            QMessageBox.information(self, "没有任务", "请先刷新评教任务")
            return
        pending = self.evaluation_page.pending_tasks()
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
            loading_label=self.evaluation_page.loading,
        )

    def export_timetable(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "导出课表",
            "本学期课表.xlsx",
            "Excel 文件 (*.xlsx)",
        )
        if filename:

            async def operation() -> str:
                courses = self.timetable_page.entries
                if not courses:
                    courses = await self.service.timetable_entries()
                output = await export_timetable_excel(courses, Path(filename))
                return str(output)

            self.timetable_page.loading.setText("正在导出课表...")
            self._run(
                "timetable_export",
                operation,
                lambda output: self._show_info("导出完成", output),
                loading_label=self.timetable_page.loading,
            )

    def refresh_timetable(self) -> None:
        self.timetable_page.loading.setText("正在加载课表...")
        self._run(
            "timetable_load",
            self.service.timetable_entries,
            self._show_timetable,
            loading_label=self.timetable_page.loading,
        )

    def _show_timetable(self, entries: list[TimetableEntry]) -> None:
        """将课表数据交给课表页面。"""
        self.timetable_page.show_entries(entries)

    def _on_page_changed(self, index: int) -> None:
        if index == COURSE_PAGE_INDEX and not self.courses_loaded:
            self.refresh_courses()
        elif index == DROP_PAGE_INDEX and not self.selected_courses_loaded:
            self.refresh_selected_courses()
        elif index == EVALUATION_PAGE_INDEX and not self.evaluation_loaded:
            self.refresh_evaluations()
        elif index == TIMETABLE_PAGE_INDEX and not self.timetable_page.loaded:
            self.refresh_timetable()
        elif index == SCORE_PAGE_INDEX:
            self.score_page.load_if_needed()


def run_gui() -> None:
    _set_windows_app_id()
    app = QApplication(sys.argv)
    app.setApplicationName("URP Tools")
    app.setApplicationVersion("0.3.2")
    app.setOrganizationName("Reversedeer")
    app.setWindowIcon(QIcon(str(LOGO_PATH)))
    app.setStyleSheet(load_stylesheet())
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
