from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlparse

import aiohttp

from urp_academic_affairs_tools.client import (
    AsyncJWSSession,
    AuthenticationFailure,
    extract_token_value,
    fetch_tasks,
)
from urp_academic_affairs_tools.course_selection import (
    CourseSelectionClient,
    CourseSelectionQuery,
    CourseSnatchingOptions,
    parse_course_select_page,
)
from urp_academic_affairs_tools.course_selection.course_selection import (
    _resolve_plan_link,
)
from urp_academic_affairs_tools.export import export_timetable_excel
from urp_academic_affairs_tools.parser.evaluation import (
    EvaluationOptions,
    TeachingEvaluationClient,
)
from urp_academic_affairs_tools.parser.timetable import parse_timetable
from urp_academic_affairs_tools.score_query import (
    ScoreQueryClient,
    ScoreView,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from urp_academic_affairs_tools.config import Settings
    from urp_academic_affairs_tools.course_selection import (
        CourseSelectionCandidate,
        QuitCourseCandidate,
    )
    from urp_academic_affairs_tools.parser.evaluation import EvaluationTask
    from urp_academic_affairs_tools.parser.timetable import TimetableEntry
    from urp_academic_affairs_tools.score_query import ScoreRecord


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
        """登录并验证。"""
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

    async def selected_courses(self) -> tuple[str, list[QuitCourseCandidate]]:
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
                confirm=_true_async,
            )
            return await client.run(jws, data, selected_tasks=tasks)

    async def timetable(self, filename: str) -> str:
        courses = await self.timetable_entries()
        output = await export_timetable_excel(courses, Path(filename))
        return str(output)

    async def timetable_entries(self) -> list[TimetableEntry]:
        async with await self.session() as jws:
            data = await jws.request_json(
                "GET",
                "/student/courseSelect/thisSemesterCurriculum/callback",
            )
            return parse_timetable(data)

    async def scores(self, view: ScoreView) -> list[ScoreRecord]:
        async with await self.session() as jws:
            return await ScoreQueryClient(jws).query(view)


async def _true_async(_tasks: Sequence[EvaluationTask]) -> bool:
    return True


def _query_value(path: str, key: str) -> str:
    values = parse_qs(urlparse(path).query).get(key, [])
    return values[0] if values else ""
