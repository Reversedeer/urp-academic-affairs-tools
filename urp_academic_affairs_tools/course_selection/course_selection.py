"""选课页面解析"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sys
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from typing import TYPE_CHECKING, Any, ClassVar
from urllib.parse import parse_qs, urlparse

import aioconsole

from urp_academic_affairs_tools.client import ServiceError
from urp_academic_affairs_tools.client.api import (
    delete_course_selection,
    fetch_course_select_index,
    fetch_course_select_list,
    fetch_course_select_page,
    fetch_course_select_result_index,
    get_this_semester_timetable,
    submit_course_selection,
)

if TYPE_CHECKING:
    from urp_academic_affairs_tools.client import AsyncJWSSession
    from urp_academic_affairs_tools.config import Settings

log = logging.getLogger(__name__)
CONFIRM_SUBMIT_PHRASE = "yes"
COURSE_SELECTION_CLOSED_MESSAGE = "对不起，当前选课阶段已过截止时间！"


@dataclass(frozen=True, slots=True)
class CourseSelectLink:
    """选课页面中的入口链接"""

    path: str
    category: str


@dataclass(frozen=True, slots=True)
class CourseSelectPageInfo:
    """选课页面暴露的只读协议信息"""

    links: list[CourseSelectLink]
    endpoints: list[str]
    input_names: list[str]
    function_names: list[str]
    program_plan_number: str = ""
    academic_term: str = ""
    course_property: str = ""
    campus: str = ""


@dataclass(frozen=True, slots=True)
class CourseSelectionCandidate:
    """课程列表中的一个可选教学班"""

    course_number: str
    sequence_number: str
    teaching_class_number: str
    course_name: str
    teacher_name: str = ""
    raw: dict[str, Any] | None = None

    @property
    def selection_id(self) -> str:
        return (
            f"{self.course_number}@{self.sequence_number}@{self.teaching_class_number}"
        )

    @property
    def course_code(self) -> str:
        return f"{self.course_number}_{self.sequence_number}"

    @property
    def display_name(self) -> str:
        course_name = self.course_name.replace("#@urp001@#", "'")
        return f"{course_name}({self.course_code})"


@dataclass(frozen=True, slots=True)
class QuitCourseCandidate:
    """已选课程中的一个可退课程"""

    program_plan_number: str
    course_number: str
    sequence_number: str
    course_name: str
    teacher_name: str = ""
    credit: str = ""
    selection_mode: str = ""
    schedule_text: str = ""
    location_text: str = ""

    @property
    def course_code(self) -> str:
        return f"{self.course_number}_{self.sequence_number}"

    @property
    def display_name(self) -> str:
        return f"{self.course_name}({self.course_code})"


@dataclass(frozen=True, slots=True)
class CourseSelectionFormOptions:
    """构造选课提交表单所需的上下文"""

    deal_type: str
    program_plan_number: str
    token_value: str
    input_code: str = ""
    schedule_filter: str = "0_0"


@dataclass(frozen=True, slots=True)
class CourseSelectionOptions:
    """选课提交策略"""

    attempts: int = 3
    concurrency: int = 2
    retry_interval: float = 0.2

    def __post_init__(self) -> None:
        if min(self.attempts, self.concurrency) < 1:
            msg = "attempts and concurrency must be at least 1"
            raise ValueError(msg)
        if self.retry_interval < 0:
            msg = "retry_interval cannot be negative"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class CourseSnatchingOptions:
    """持续抢课策略；``attempts=0`` 表示持续运行直到成功或手动停止"""

    attempts: int = 0
    concurrency: int = 10
    retry_interval: float = 0.2

    def __post_init__(self) -> None:
        if self.attempts < 0 or self.concurrency < 1:
            msg = "attempts must be non-negative and concurrency must be at least 1"
            raise ValueError(msg)
        if self.retry_interval < 0:
            msg = "retry_interval cannot be negative"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class CourseSelectionQuery:
    """课程列表查询参数"""

    category: str
    params: dict[str, str]
    deal_type: str
    program_plan_number: str


@dataclass(frozen=True, slots=True)
class CourseSelectionSubmitResult:
    """选课提交结果"""

    succeeded: bool
    result: str
    token: str = ""
    attempt: int = 1


def filter_course_candidates(
    candidates: Sequence[CourseSelectionCandidate],
    course_code: str,
) -> list[CourseSelectionCandidate]:
    """按课程号或课程号_课序号筛选课程"""
    normalized = course_code.strip().upper()
    if not re.fullmatch(r"[A-Z0-9]+(?:_[A-Z0-9]+)?", normalized):
        msg = "课程号格式不合法, 应为课程号或课程号_课序号"
        raise ValueError(msg)
    if "_" in normalized:
        return [course for course in candidates if course.course_code == normalized]
    return [course for course in candidates if course.course_number == normalized]


def _is_permanent_course_failure(result: str) -> bool:
    normalized = result.strip().lower()
    return any(
        marker in normalized
        for marker in (
            "课程不存在",
            "课序号不存在",
            "已经选过",
            "已选该课程",
            "时间冲突",
            "不允许选课",
            "当前未开放",
            "选课阶段已结束",
        )
    )


class _InputParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.names: set[str] = set()
        self.values: dict[str, str] = {}

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag.lower() != "input":
            return
        values = dict(attrs)
        for key in ("name", "id"):
            value = values.get(key)
            if value:
                self.names.add(value)
                if values.get("value") is not None:
                    self.values.setdefault(value, values["value"] or "")


def _selected_option_value(html: str, control_id: str) -> str:
    pattern = (
        rf"<select[^>]*(?:id|name)=['\"]{re.escape(control_id)}['\"][^>]*>"
        rf"(.*?)</select>"
    )
    match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
    if match is None:
        return ""
    selected = re.search(
        r"<option[^>]*value=['\"]([^'\"]*)['\"][^>]*selected[^>]*>",
        match.group(1),
        re.IGNORECASE,
    )
    if selected is not None:
        return selected.group(1)
    first = re.search(
        r"<option[^>]*value=['\"]([^'\"]*)['\"]",
        match.group(1),
        re.IGNORECASE,
    )
    return first.group(1) if first is not None else ""


def _classify_course_link(path: str) -> str:
    normalized_path = path.replace(r"\/", "/")
    category_markers = {
        "freeCourse/": "free",
        "schoolCourse/": "school",
        "planCourse/": "plan",
        "departCourse/": "department",
        "relearnCourse/": "relearn",
        "intentCourse/": "intent",
        "quitCourse/": "quit",
        "courseSelectResult/": "result",
    }
    for marker, category in category_markers.items():
        if marker in normalized_path:
            return category
    return "other"


def parse_course_select_page(html: str) -> CourseSelectPageInfo:
    """解析选课相关链接、接口和表单字段"""
    normalized_html = unescape(html).replace(r"\/", "/")
    raw_paths = sorted(
        {
            match
            for match in re.findall(
                r"""["']([^"']*courseSelect[^"']*)["']""",
                normalized_html,
            )
            if match and not match.startswith(("javascript:", "#"))
        },
    )
    links = [
        CourseSelectLink(path=path, category=_classify_course_link(path))
        for path in raw_paths
        if "index" in path or "fajhh=" in path
    ]
    endpoints = [
        path for path in raw_paths if path not in {link.path for link in links}
    ]

    parser = _InputParser()
    parser.feed(html)
    function_names = sorted(
        set(
            re.findall(
                r"\b\w*(?:select|submit|course|yzm|captcha)\w*\s*\(",
                html,
                re.IGNORECASE,
            ),
        ),
    )
    return CourseSelectPageInfo(
        links=links,
        endpoints=endpoints,
        input_names=sorted(parser.names),
        function_names=function_names,
        program_plan_number=parser.values.get("fajhh", ""),
        academic_term=(
            parser.values.get("jhxn", "") or _selected_option_value(html, "jhxn")
        ),
        course_property=(
            parser.values.get("kcsxdm", "") or _selected_option_value(html, "kcsxdm")
        ),
        campus=(parser.values.get("xqh", "") or _selected_option_value(html, "xqh")),
    )


def encode_course_names(candidates: list[CourseSelectionCandidate]) -> str:
    """编码 kcms 字段"""
    text = ",".join(candidate.display_name for candidate in candidates)
    return "".join(f"{ord(char)}," for char in text)


def build_course_selection_form(
    *,
    options: CourseSelectionFormOptions,
    candidates: list[CourseSelectionCandidate],
) -> dict[str, str]:
    """构造 checkInputCodeAndSubmit 接口需要的表单"""
    return {
        "dealType": options.deal_type,
        "kcIds": ",".join(candidate.selection_id for candidate in candidates),
        "kcms": encode_course_names(candidates),
        "fajhh": options.program_plan_number,
        "sj": options.schedule_filter,
        "inputCode": options.input_code,
        "tokenValue": options.token_value,
    }


def extract_course_select_token(html: str) -> str:
    """提取选课首页的 tokenValue"""
    match = re.search(r"""id=["']tokenValue["'][^>]*value=["']([^"']+)["']""", html)
    if match is None:
        normalized = re.sub(r"\s+", "", unescape(html)).lower()
        if _is_course_selection_closed(html):
            msg = COURSE_SELECTION_CLOSED_MESSAGE
        elif "gotologin" in normalized or "/login" in normalized:
            msg = "选课提交页面已跳转到登录页，会话可能已失效"
        else:
            msg = "选课提交页面未返回 tokenValue，页面结构可能已变化"
        raise ValueError(msg)
    return match.group(1)


def parse_course_candidates(html: str) -> list[CourseSelectionCandidate]:
    """从 courseList 响应中提取可选课程候选项"""
    raw_response = unescape(html)
    response = _parse_course_list_response(raw_response)
    if response is not None:
        raw_objects = _available_course_objects(response)
    else:
        normalized = raw_response.replace(r"\"", '"')
        raw_objects = []
        for raw_object in _iter_json_objects_containing(
            normalized, '"courseNum"'
        ) + _iter_json_objects_containing(normalized, '"courseName"'):
            try:
                parsed_object = json.loads(raw_object)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed_object, dict):
                raw_objects.append(parsed_object)

    candidates: dict[str, CourseSelectionCandidate] = {}
    for data in raw_objects:
        candidate = _candidate_from_data(data)
        if candidate is not None:
            candidates[candidate.selection_id] = candidate
    return list(candidates.values())


def _parse_course_list_response(html: str) -> dict[str, Any] | None:
    try:
        data = json.loads(html)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _available_course_objects(data: Mapping[str, object]) -> list[dict[str, Any]]:
    """提取教务系统返回的可选课程列表"""
    objects: list[dict[str, Any]] = []
    found_available_list = False
    for key, value in data.items():
        normalized_key = str(key).lower()
        if not normalized_key.startswith("rw") or "list" not in normalized_key:
            continue
        found_available_list = True
        parsed_value = value
        if isinstance(parsed_value, str):
            try:
                parsed_value = json.loads(parsed_value)
            except json.JSONDecodeError:
                continue
        if not isinstance(parsed_value, list):
            continue
        objects.extend(item for item in parsed_value if isinstance(item, dict))

    if found_available_list:
        return objects
    return _json_objects_from_text(data.get("courseList"))


def _json_objects_from_text(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, str):
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    if isinstance(parsed, dict):
        return [parsed]
    return []


def parse_selected_courses(data: Mapping[str, object]) -> list[QuitCourseCandidate]:
    """从选课结果/本学期课表回调数据提取已选课程"""
    candidates: list[QuitCourseCandidate] = []
    for course in _iter_selected_course_mappings(data):
        candidate = _selected_course_candidate_from_data(course)
        if candidate is not None:
            candidates.append(candidate)
    seen: set[tuple[str, str]] = set()
    unique: list[QuitCourseCandidate] = []
    for candidate in candidates:
        key = (candidate.course_number, candidate.sequence_number)
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


class CourseSelectionClient:
    """选课查询与并发提交"""

    DEFAULT_QUERIES: ClassVar[dict[str, CourseSelectionQuery]] = {
        "department": CourseSelectionQuery(
            category="department",
            params={"searchtj": "", "xq": "0", "jc": "0", "kclbdm": ""},
            deal_type="4",
            program_plan_number="",
        ),
        "free": CourseSelectionQuery(
            category="free",
            params={
                "kkxsh": "",
                "kch": "",
                "kcm": "",
                "skjs": "",
                "xq": "0",
                "jc": "0",
                "kclbdm": "",
            },
            deal_type="5",
            program_plan_number="",
        ),
        "plan": CourseSelectionQuery(
            category="plan",
            params={
                "fajhh": "",
                "jhxn": "",
                "kcsxdm": "",
                "kch": "",
                "kcm": "",
                "kclbdm": "",
                "xqh": "",
                "xq": "0",
                "jc": "0",
            },
            deal_type="2",
            program_plan_number="",
        ),
        "school": CourseSelectionQuery(
            category="school",
            params={"searchtj": "", "xq": "0", "jc": "0", "kclbdm": ""},
            deal_type="3",
            program_plan_number="",
        ),
    }

    def __init__(self, options: CourseSelectionOptions | None = None) -> None:
        self.options = options or CourseSelectionOptions()

    @classmethod
    def build_query(
        cls,
        category: str,
        **overrides: str,
    ) -> CourseSelectionQuery:
        try:
            query = cls.DEFAULT_QUERIES[category]
        except KeyError as error:
            msg = f"unsupported course select category: {category}"
            raise ValueError(msg) from error
        params = {**query.params, **overrides}
        return CourseSelectionQuery(
            category=query.category,
            params=params,
            deal_type=query.deal_type,
            program_plan_number=params.get("fajhh", query.program_plan_number),
        )

    @classmethod
    def build_plan_query(
        cls,
        *,
        jhxn: str,
        kcsxdm: str = "",
        xqh: str = "",
        kch: str = "",
        kcm: str = "",
    ) -> CourseSelectionQuery:
        return cls.build_query(
            "plan",
            jhxn=jhxn,
            kcsxdm=kcsxdm,
            xqh=xqh,
            kch=kch,
            kcm=kcm,
        )

    async def fetch_candidates(
        self,
        jws: AsyncJWSSession,
        query: CourseSelectionQuery,
    ) -> list[CourseSelectionCandidate]:
        html = await fetch_course_select_list(jws, query.category, query.params)
        candidates = parse_course_candidates(html)
        if not candidates:
            raise ServiceError(COURSE_SELECTION_CLOSED_MESSAGE)
        return candidates

    async def fetch_selected_courses(
        self,
        jws: AsyncJWSSession,
    ) -> list[QuitCourseCandidate]:
        _, courses = await self.fetch_selected_courses_with_term(jws)
        return courses

    async def fetch_selected_courses_with_term(
        self,
        jws: AsyncJWSSession,
    ) -> tuple[str, list[QuitCourseCandidate]]:
        """读取退课数据"""
        data = await get_this_semester_timetable(jws)
        term = _extract_context_value(data, "executiveEducationPlanNumber")
        return term, parse_selected_courses(data)

    async def fetch_selection_data(
        self,
        jws: AsyncJWSSession,
    ) -> dict[str, Any]:
        """获取选课结果回调数据，包含培养方案和学期上下文"""
        await fetch_course_select_result_index(jws)
        return await get_this_semester_timetable(jws)

    async def submit_once(
        self,
        jws: AsyncJWSSession,
        query: CourseSelectionQuery,
        candidates: list[CourseSelectionCandidate],
        *,
        attempt: int = 1,
        token_value: str | None = None,
    ) -> CourseSelectionSubmitResult:
        if token_value is None:
            index_html = await fetch_course_select_index(jws)
            token_value = extract_course_select_token(index_html)
        form = build_course_selection_form(
            options=CourseSelectionFormOptions(
                deal_type=query.deal_type,
                program_plan_number=query.program_plan_number,
                token_value=token_value,
            ),
            candidates=candidates,
        )
        data = await submit_course_selection(jws, form)
        result = str(data.get("result", ""))
        return CourseSelectionSubmitResult(
            succeeded=result == "ok",
            result=result,
            token=str(data.get("token", "")),
            attempt=attempt,
        )

    async def snatch_until_success(  # noqa: C901
        self,
        jws: AsyncJWSSession,
        query: CourseSelectionQuery,
        candidate: CourseSelectionCandidate,
        *,
        options: CourseSnatchingOptions | None = None,
        token_value: str | None = None,
    ) -> CourseSelectionSubmitResult:
        """并发持续提交一门课程，成功后取消其余提交任务"""
        strategy = options or CourseSnatchingOptions()
        stop_event = asyncio.Event()
        result: CourseSelectionSubmitResult | None = None
        result_lock = asyncio.Lock()
        token_lock = asyncio.Lock()
        current_token = token_value

        async def worker(worker_id: int) -> None:
            nonlocal current_token, result
            attempt = worker_id
            while not stop_event.is_set() and (
                strategy.attempts == 0 or attempt <= strategy.attempts
            ):
                try:
                    async with token_lock:
                        request_token = current_token
                    submission = await self.submit_once(
                        jws,
                        query,
                        [candidate],
                        attempt=attempt,
                        token_value=request_token,
                    )
                except ServiceError as error:
                    if not error.retryable:
                        raise
                    log.debug("抢课请求失败，继续重试：%s", error)
                else:
                    if submission.token:
                        async with token_lock:
                            current_token = submission.token
                    if submission.succeeded:
                        async with result_lock:
                            if result is None:
                                result = submission
                                stop_event.set()
                        return
                    if _is_permanent_course_failure(submission.result):
                        msg = f"抢课无法继续：{candidate.display_name}，{submission.result}"
                        raise ServiceError(msg)
                    log.debug(
                        "第 %d 次抢课未成功：%s",
                        attempt,
                        submission.result,
                    )
                attempt += strategy.concurrency
                if not stop_event.is_set() and strategy.retry_interval:
                    await asyncio.sleep(strategy.retry_interval)

        workers = [
            asyncio.create_task(worker(worker_id))
            for worker_id in range(1, strategy.concurrency + 1)
        ]
        try:
            await asyncio.gather(*workers)
        finally:
            for task in workers:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*workers, return_exceptions=True)

        if result is not None:
            return result
        msg = f"持续抢课结束，仍未选中：{candidate.display_name}"
        raise ServiceError(msg)

    async def delete_one(
        self,
        jws: AsyncJWSSession,
        *,
        fajhh: str,
        course_number: str,
        sequence_number: str,
    ) -> str:
        index_html = await fetch_course_select_index(jws)
        token = extract_course_select_token(index_html)
        return await delete_course_selection(
            jws,
            fajhh=fajhh,
            kch=course_number,
            kxh=sequence_number,
            token_value=token,
        )


async def handle_course_selection(  # noqa: C901, PLR0912, PLR0915
    jws: AsyncJWSSession,
    settings: Settings | None = None,
) -> None:
    client = CourseSelectionClient()
    index_html = await fetch_course_select_index(jws)
    selection_closed = _is_course_selection_closed(index_html)
    if selection_closed:
        log.warning("当前未开放选课，以下课程列表仅供预览，暂不能提交选课")
    plan_link, callback_term, selected_courses = await _resolve_plan_link(
        jws,
        index_html,
        client,
    )
    if not plan_link:
        if _is_course_selection_closed(index_html):
            msg = "当前选课阶段已结束，且无法从已选课程恢复方案入口"
        else:
            msg = "选课首页没有找到方案选课入口"
        raise ServiceError(msg)
    plan_html = await fetch_course_select_page(jws, plan_link)
    plan_info = parse_course_select_page(plan_html)
    program_plan_number = plan_info.program_plan_number or _query_value(
        plan_link, "fajhh"
    )
    academic_term = plan_info.academic_term or callback_term
    if not program_plan_number or not academic_term:
        msg = "无法从选课页面解析培养方案号或学年学期"
        raise ServiceError(msg)
    query = CourseSelectionClient.build_plan_query(
        jhxn=academic_term,
        kcsxdm=plan_info.course_property,
        xqh=plan_info.campus,
    )
    query = CourseSelectionQuery(
        category=query.category,
        params={**query.params, "fajhh": program_plan_number},
        deal_type=query.deal_type,
        program_plan_number=program_plan_number,
    )
    courses = await client.fetch_candidates(jws, query)
    selected_codes = {course.course_code for course in selected_courses}
    courses = [course for course in courses if course.course_code not in selected_codes]
    if not courses:
        log.warning("可选课程已全部在已选列表中")
        return

    target_code = (
        await aioconsole.ainput(
            "请输入目标课程号或课程号_课序号, 直接回车显示全部：",
        )
    ).strip()
    if target_code:
        courses = filter_course_candidates(courses, target_code)
        if not courses:
            log.warning("没有找到匹配的可选课程：%s", target_code)
            return

    _show_indexed_courses("可选课程", courses)
    choice = await aioconsole.ainput("请输入要选的课程序号，输入0返回：")
    index = _parse_single_index(choice, len(courses))
    if index == 0:
        return

    selected = courses[index - 1]
    log.warning("即将提交：%s", selected.display_name)
    log.warning("确认语句：%s", CONFIRM_SUBMIT_PHRASE)
    confirm = (await aioconsole.ainput("请输入确认语句：")).strip()
    if confirm != CONFIRM_SUBMIT_PHRASE:
        log.warning("已取消")
        return

    mode = (await aioconsole.ainput("输入 1 普通选课，输入 2 持续抢课：")).strip()
    if mode not in {"1", "2"}:
        msg = "选课模式必须输入 1 或 2"
        raise ValueError(msg)
    if mode == "2":
        if selection_closed:
            msg = "当前未开放选课，处于预览阶段，不能启动持续抢课"
            raise ServiceError(msg)
        result = await client.snatch_until_success(
            jws,
            query,
            selected,
            options=CourseSnatchingOptions(
                attempts=settings.course_snatching_attempts if settings else 0,
                concurrency=(settings.course_snatching_concurrency if settings else 10),
                retry_interval=(
                    settings.course_snatching_retry_interval if settings else 0.2
                ),
            ),
            token_value=(
                extract_course_select_token(index_html)
                if not selection_closed
                else None
            ),
        )
        log.info("抢课成功：%s（第 %d 次）", selected.display_name, result.attempt)
        return

    result = await client.submit_once(
        jws,
        query,
        [selected],
        token_value=(
            extract_course_select_token(index_html) if not selection_closed else None
        ),
    )
    if not result.succeeded:
        msg = _format_course_action_result("选课", result.result, selected.display_name)
        raise ServiceError(msg)
    log.info("选课成功：%s", selected.display_name)


async def _resolve_plan_link(
    jws: AsyncJWSSession,
    index_html: str,
    client: CourseSelectionClient,
) -> tuple[str, str, list[QuitCourseCandidate]]:
    selection_data = await client.fetch_selection_data(jws)
    program_plan_number = _extract_context_value(
        selection_data,
        "programPlanNumber",
    )
    callback_term = _extract_context_value(
        selection_data,
        "executiveEducationPlanNumber",
    )
    selected_courses = parse_selected_courses(selection_data)
    if program_plan_number:
        return (
            f"/student/courseSelect/planCourse/index?fajhh={program_plan_number}",
            callback_term,
            selected_courses,
        )

    index_info = parse_course_select_page(index_html)
    plan_link = next(
        (link.path for link in index_info.links if link.category == "plan"),
        "",
    )
    if plan_link:
        return plan_link, callback_term, selected_courses
    return "", callback_term, selected_courses


def _extract_context_value(data: Mapping[str, object], key: str) -> str:
    value = data.get(key)
    if value is not None and str(value).strip():
        return str(value).strip()
    for nested in data.values():
        if isinstance(nested, Mapping):
            found = _extract_context_value(nested, key)
            if found:
                return found
        elif isinstance(nested, list):
            for item in nested:
                if isinstance(item, Mapping):
                    found = _extract_context_value(item, key)
                    if found:
                        return found
    return ""


def _query_value(path: str, key: str) -> str:
    values = parse_qs(urlparse(path).query).get(key, [])
    return values[0] if values else ""


def _is_course_selection_closed(html: str) -> bool:
    normalized = re.sub(r"\s+", "", unescape(html)).lower()
    return any(
        marker in normalized
        for marker in (
            "当前选课阶段已过截止时间",
            "当前选课阶段已结束",
            "选课阶段已结束",
            "选课时间已结束",
        )
    )


async def handle_course_drop(jws: AsyncJWSSession) -> None:
    client = CourseSelectionClient()
    courses = await client.fetch_selected_courses(jws)
    if not courses:
        log.warning("没有查询到已选课程")
        return

    _show_indexed_courses("已选课程", courses)
    choice = await aioconsole.ainput("请输入要退的课程序号，输入0返回：")
    index = _parse_single_index(choice, len(courses))
    if index == 0:
        return

    selected = courses[index - 1]
    log.warning("即将退课：%s", selected.display_name)
    log.warning("确认语句：%s", CONFIRM_SUBMIT_PHRASE)
    confirm = (await aioconsole.ainput("请输入确认语句：")).strip()
    if confirm != CONFIRM_SUBMIT_PHRASE:
        log.warning("已取消")
        return

    result = await client.delete_one(
        jws,
        fajhh=selected.program_plan_number,
        course_number=selected.course_number,
        sequence_number=selected.sequence_number,
    )
    message = _format_course_action_result("退课", result, selected.display_name)
    if _is_course_action_success(result):
        log.info("%s", message)
        return
    raise ServiceError(message)


def _candidate_from_data(data: dict[str, Any]) -> CourseSelectionCandidate | None:
    raw_id = data.get("id")
    course_number = _as_text(
        data.get("courseNum")
        or data.get("courseNumber")
        or data.get("kch")
        or (raw_id.get("coureNumber") if isinstance(raw_id, dict) else None),
    )
    sequence_number = _as_text(
        data.get("classNum")
        or data.get("classNumber")
        or data.get("kxh")
        or (raw_id.get("coureSequenceNumber") if isinstance(raw_id, dict) else None),
    )
    teaching_class_number = _as_text(
        data.get("termCode")
        or data.get("zxjxjhh")
        or (
            raw_id.get("executiveEducationPlanNumber")
            if isinstance(raw_id, dict)
            else None
        ),
    )
    course_name = _as_text(data.get("kcm") or data.get("courseName"))
    if not all((course_number, sequence_number, teaching_class_number, course_name)):
        return None
    return CourseSelectionCandidate(
        course_number=course_number,
        sequence_number=sequence_number,
        teaching_class_number=teaching_class_number,
        course_name=course_name,
        teacher_name=_as_text(data.get("teacherName") or data.get("skjs")),
        raw=data,
    )


def _iter_selected_course_mappings(
    data: Mapping[str, object],
) -> list[Mapping[str, object]]:
    course_groups = data.get("xkxx", [])
    if not isinstance(course_groups, list):
        return []

    courses: list[Mapping[str, object]] = []
    for group in course_groups:
        if not isinstance(group, Mapping):
            continue
        courses.extend(
            course for course in group.values() if isinstance(course, Mapping)
        )
    return courses


def _selected_course_candidate_from_data(
    course: Mapping[str, object],
) -> QuitCourseCandidate | None:
    raw_id = course.get("id")
    time_and_place = _first_time_and_place(course)
    course_number = _as_text(
        course.get("courseNum")
        or course.get("courseNumber")
        or course.get("kch")
        or time_and_place.get("coureNumber")
        or (raw_id.get("coureNumber") if isinstance(raw_id, dict) else None),
    )
    sequence_number = _as_text(
        course.get("classNum")
        or course.get("classNumber")
        or course.get("kxh")
        or time_and_place.get("coureSequenceNumber")
        or (raw_id.get("coureSequenceNumber") if isinstance(raw_id, dict) else None),
    )
    course_name = _as_text(course.get("courseName") or course.get("kcm"))
    if not all((course_number, sequence_number, course_name)):
        return None

    return QuitCourseCandidate(
        program_plan_number=_as_text(
            course.get("fajhh")
            or course.get("programPlanNumber")
            or course.get("trainingProgramNumber")
            or "20959"
        ),
        course_number=course_number,
        sequence_number=sequence_number,
        course_name=course_name,
        teacher_name=_as_text(
            course.get("attendClassTeacher")
            or course.get("teacherName")
            or course.get("skjs")
        ),
        credit=_as_text(course.get("unit") or course.get("xf") or course.get("credit")),
        selection_mode=_as_text(
            course.get("xkfsmc")
            or course.get("selectionMode")
            or course.get("xkfs")
            or course.get("studyModeName")
            or "直选式"
        ),
        schedule_text=_format_schedule_from_data(time_and_place),
        location_text=_format_location_from_data(time_and_place),
    )


def _first_time_and_place(course: Mapping[str, object]) -> dict[str, Any]:
    time_and_place_list = course.get("timeAndPlaceList", [])
    if not isinstance(time_and_place_list, list):
        return {}
    for item in time_and_place_list:
        if isinstance(item, Mapping):
            return dict(item)
    return {}


def _as_text(value: object) -> str:
    return "" if value is None else str(value)


def _show_indexed_courses(title: str, courses: Sequence[object]) -> None:
    if not courses:
        _print_line(f"没有查询到{title}")
        return

    if title == "可选课程":
        headers = [
            "序号",
            "计划学年学期",
            "课程",
            "学分",
            "课程类别",
            "课程属性",
            "教师",
            "课余量",
            "上课时间",
            "上课地点",
        ]
        widths = [4, 15, 40, 6, 10, 10, 22, 6, 30, 34]
        _print_line(f"{title}：")
        _print_line(_format_table_row(headers, widths))
        for index, course in enumerate(courses, start=1):
            raw = getattr(course, "raw", {}) or {}
            row = [
                str(index),
                _as_text(raw.get("schemeYear") or raw.get("termCode")),
                getattr(course, "display_name", "")
                or getattr(course, "course_code", ""),
                _as_text(raw.get("xf")),
                _as_text(raw.get("kclbmc") or raw.get("kclbm")),
                _as_text(raw.get("kcsxmc")),
                _clean_teacher_name(
                    _as_text(raw.get("skjs") or getattr(course, "teacher_name", ""))
                ),
                _as_text(raw.get("bkskyl")),
                _format_course_schedule_from_raw(raw),
                _format_course_location_from_raw(raw),
            ]
            _print_line(_format_table_row(row, widths))
        return

    headers = [
        "序号",
        "课程号",
        "课程名",
        "学分",
        "教师",
        "选课方式",
        "上课时间",
        "上课地点",
    ]
    widths = [4, 12, 26, 6, 18, 10, 30, 28]
    _print_line(f"{title}：")
    _print_line(_format_table_row(headers, widths))
    for index, course in enumerate(courses, start=1):
        row = [
            str(index),
            getattr(course, "course_code", ""),
            getattr(course, "course_name", ""),
            getattr(course, "credit", ""),
            _clean_teacher_name(getattr(course, "teacher_name", "")),
            getattr(course, "selection_mode", ""),
            getattr(course, "schedule_text", ""),
            getattr(course, "location_text", ""),
        ]
        _print_line(_format_table_row(row, widths))


def _format_table_row(values: Sequence[object], widths: Sequence[int]) -> str:
    cells = []
    for value, width in zip(values, widths, strict=False):
        cells.append(_fit_display_width(_as_text(value), width))
    return " | ".join(cells)


def _print_line(text: str) -> None:
    sys.stdout.write(f"{text}\n")


def _is_course_action_success(result: str) -> bool:
    normalized = result.strip().lower()
    if normalized == "ok":
        return True
    success_markers = ("成功", "已提交", "完成", "success")
    return any(marker in normalized for marker in success_markers)


def _format_course_action_result(action: str, result: str, course_name: str) -> str:
    normalized = result.strip()
    if not normalized:
        return f"{action}失败：{course_name}，服务端未返回结果"
    if _is_course_action_success(normalized):
        return f"{action}成功：{course_name}"
    if normalized.startswith("/"):
        return f"{action}失败：{course_name}，服务端返回跳转地址 {normalized}"
    return f"{action}失败：{course_name}，{normalized}"


def _clean_teacher_name(text: str) -> str:
    return text.replace("*", "").strip()


def _display_width(text: str) -> int:
    width = 0
    for char in text:
        if unicodedata.combining(char):
            continue
        width += 2 if unicodedata.east_asian_width(char) in {"F", "W", "A"} else 1
    return width


def _fit_display_width(text: str, width: int) -> str:
    if width <= 0:
        return ""
    text_width = _display_width(text)
    if text_width <= width:
        return text + " " * (width - text_width)
    if width == 1:
        return "…"

    result: list[str] = []
    current = 0
    for char in text:
        if unicodedata.combining(char):
            result.append(char)
            continue
        char_width = 2 if unicodedata.east_asian_width(char) in {"F", "W", "A"} else 1
        if current + char_width > width - 1:
            break
        result.append(char)
        current += char_width
    result.append("…")
    padding = width - _display_width("".join(result))
    if padding > 0:
        result.append(" " * padding)
    return "".join(result)


def _format_course_schedule_from_raw(raw: dict[str, object]) -> str:
    week_days = _format_weekly_number(_as_text(raw.get("weekLyNum")))
    week_count = _as_text(raw.get("zcsm"))
    week_day = _as_text(raw.get("weekNum"))
    start_num = _as_text(raw.get("courseStartNum"))
    if not any((week_days, week_count, week_day, start_num)):
        return ""

    parts: list[str] = []
    if week_days:
        parts.append(week_days)
    elif week_count:
        parts.append(f"第{week_count}周")
    if week_day:
        parts.append(_weekday_text(week_day))
    if start_num:
        parts.append(_section_range_text(start_num))
    return " >> ".join(parts)


def _format_weekly_number(value: str) -> str:
    return _compress_weekly_number(value)


def _format_course_location_from_raw(raw: dict[str, object]) -> str:
    parts = [
        _as_text(raw.get("xqm")),
        _as_text(raw.get("jxlm")),
        _as_text(raw.get("jasm")),
    ]
    return " ".join(part for part in parts if part)


def _parse_single_index(raw_choice: str, size: int) -> int:
    choice = raw_choice.strip()
    if choice in {"0", "q", "Q", "返回"}:
        return 0
    if not choice.isdigit():
        msg = "请输入合法序号"
        raise ValueError(msg)
    index = int(choice)
    if index < 1 or index > size:
        msg = f"序号超出范围：{index}"
        raise ValueError(msg)
    return index


def _format_schedule_from_data(data: dict[str, Any]) -> str:
    week_text = _format_week_text(
        _as_text(data.get("weekLyNum") or data.get("classWeek")),
        _as_text(data.get("zcsm") or data.get("weekDescription")),
    )
    weekday = _weekday_text(
        _as_text(data.get("weekNum") or data.get("xq") or data.get("classDay"))
    )
    section = _section_range_text(
        _as_text(data.get("courseStartNum") or data.get("classSessions")),
        _as_text(data.get("continuingSession")),
    )
    return " >> ".join(part for part in (week_text, weekday, section) if part)


def _format_location_from_data(data: dict[str, Any]) -> str:
    parts = [
        _as_text(data.get("xqm") or data.get("campusName")),
        _as_text(data.get("jxlm") or data.get("teachingBuildingName")),
        _as_text(data.get("jasm") or data.get("classroomName")),
    ]
    return " ".join(part for part in parts if part)


def _format_week_text(weekly_number: str, fallback_week: str) -> str:
    compressed = _compress_weekly_number(weekly_number)
    if compressed:
        return compressed
    if fallback_week:
        if "周" in fallback_week:
            return fallback_week
        return f"第{fallback_week}周"
    return ""


def _compress_weekly_number(value: str) -> str:
    if not value:
        return ""

    active_weeks: list[int] = []
    for index, flag in enumerate(value[:18], start=1):
        if flag == "1":
            active_weeks.append(index)
    if not active_weeks:
        return ""

    ranges: list[str] = []
    start = end = active_weeks[0]
    for number in active_weeks[1:]:
        if number == end + 1:
            end = number
            continue
        ranges.append(_format_week_range(start, end))
        start = end = number
    ranges.append(_format_week_range(start, end))
    return ",".join(ranges) + "周"


def _format_week_range(start: int, end: int) -> str:
    if start == end:
        return str(start)
    return f"{start}-{end}"


def _weekday_text(value: str) -> str:
    if not value:
        return ""
    mapping = {
        "1": "星期一",
        "2": "星期二",
        "3": "星期三",
        "4": "星期四",
        "5": "星期五",
        "6": "星期六",
        "7": "星期日",
    }
    return mapping.get(value, f"星期{value}")


def _section_range_text(value: str, duration: str = "") -> str:
    if not value:
        return ""
    try:
        start = int(value)
    except ValueError:
        return f"{value}节"
    try:
        length = int(duration) if duration else 2
    except ValueError:
        length = 2
    end = start + max(length - 1, 0)
    if end <= start:
        return f"{start}节"
    return f"{start}~{end}节"


def _iter_json_objects_containing(text: str, marker: str) -> list[str]:
    objects: list[str] = []
    search_from = 0
    while True:
        marker_index = text.find(marker, search_from)
        if marker_index == -1:
            return objects
        start = text.rfind("{", 0, marker_index)
        if start == -1:
            search_from = marker_index + len(marker)
            continue
        end = _find_json_object_end(text, start)
        if end is not None:
            objects.append(text[start : end + 1])
            search_from = end + 1
        else:
            search_from = marker_index + len(marker)


def _find_json_object_end(text: str, start: int) -> int | None:
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    return None
