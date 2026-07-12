"""教学评估任务解析、交互与提交。"""

from __future__ import annotations

import asyncio
import html
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import TYPE_CHECKING

import aioconsole

if TYPE_CHECKING:
    if __package__ and __package__.startswith("urp_academic_affairs_tools"):
        from ..client.session import AsyncJWSSession  # noqa: TID252  # type: ignore[no-redef]
        from ..config import Settings  # noqa: TID252  # type: ignore[no-redef]
    else:
        from client.session import AsyncJWSSession  # type: ignore[no-redef]
        from config import Settings  # type: ignore[no-redef]

if __package__ and __package__.startswith("urp_academic_affairs_tools"):
    from ..client import fetch_tasks  # noqa: TID252
    from ..client.auth import extract_token_value  # noqa: TID252
    from ..client.errors import AuthError, ServiceError  # noqa: TID252
else:
    from client import fetch_tasks  # type: ignore[no-redef]
    from client.errors import AuthError  # type: ignore[no-redef]
    from client.auth import extract_token_value  # type: ignore[no-redef]
    from client.errors import ServiceError  # type: ignore[no-redef]

EVALUATION_INDEX_PATH = "/student/teachingEvaluation/evaluation/index"
EVALUATION_PAGE_PATHS = (
    "/student/teachingEvaluation/teachingEvaluation/evaluationPage",
    "/student/teachingEvaluation/evaluationPage",
)
SUBMIT_PATHS = (
    "/student/teachingEvaluation/teachingEvaluation/assessment",
    "/student/teachingEvaluation/assessment",
)
CONFIRM_PHRASE = "yes"
DEFAULT_COMMENT = "老师教学认真课程收获较大"
HTTP_STATUS_NOT_FOUND = 404

SCORE_MAP: Mapping[str, str] = {
    "A": "10_1",
    "B": "10_0.8",
    "C": "10_0.6",
    "D": "10_0.4",
    "E": "10_0.2",
}
CHOICE_PREFIXES: Mapping[str, tuple[str, ...]] = {
    "A": ("10_1", "1", "A", "a"),
    "B": ("10_0.8", "0.8", "B", "b"),
    "C": ("10_0.6", "0.6", "C", "c"),
    "D": ("10_0.4", "0.4", "D", "d"),
    "E": ("10_0.2", "0.2", "E", "e"),
}
DEFAULT_QUESTION_IDS = (
    "0000000014",
    "0000000016",
    "0000000018",
    "0000000015",
    "0000000017",
    "0000000044",
    "0000000048",
    "0000000053",
    "0000000042",
    "0000000049",
)
TEXTAREA_NAMES = frozenset({"zgpj", "zg_pj", "comment", "comments", "content"})
SUBMIT_SUCCESS_MARKERS = frozenset(
    {"成功", "success", '"success":true', "'success':true"}
)
SUBMIT_FAILURE_MARKERS = frozenset(
    {
        "失败",
        "错误",
        "异常",
        "等待",
        "分钟",
        "秒后",
        "不能提交",
        "不可提交",
        "error",
        '"success":false',
        "'success':false",
    },
)
log = logging.getLogger(__name__)


class EvaluationError(Exception):
    """评教数据无效或评教流程无法继续。"""


class EvaluationCancelledError(EvaluationError):
    """用户未确认提交。"""


class EvaluationBatchError(EvaluationError):
    """部分课程评教提交失败。"""

    def __init__(self, results: Sequence[EvaluationSubmitResult]) -> None:
        self.results = tuple(results)
        failed = [result for result in self.results if result.error is not None]
        msg = f"评教提交失败 {len(failed)} 门"
        super().__init__(msg)


class _EvaluationFormParser(HTMLParser):
    """提取评教页面中提交所需的表单字段。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hidden_inputs: dict[str, str] = {}
        self.radio_groups: dict[str, list[str]] = {}
        self.textarea_names: list[str] = []
        self._current_textarea: str | None = None

    @staticmethod
    def _attrs_to_dict(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
        return {key.lower(): html.unescape(value or "") for key, value in attrs}

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attr_map = self._attrs_to_dict(attrs)
        if tag.lower() == "input":
            self._handle_input(attr_map)
        elif tag.lower() == "textarea":
            name = attr_map.get("name")
            if name:
                self.textarea_names.append(name)
                self._current_textarea = name

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "textarea":
            self._current_textarea = None

    def _handle_input(self, attrs: Mapping[str, str]) -> None:
        name = attrs.get("name")
        if not name:
            return
        input_type = attrs.get("type", "text").lower()
        value = attrs.get("value", "")
        if input_type == "radio":
            self.radio_groups.setdefault(name, []).append(value)
        elif input_type in {"hidden", "text"}:
            self.hidden_inputs.setdefault(name, value)

    def form_fields(self) -> tuple[dict[str, str], dict[str, list[str]], list[str]]:
        return self.hidden_inputs, self.radio_groups, self.textarea_names


@dataclass(frozen=True, slots=True)
class EvaluationForm:
    """从评教页面解析出来的可提交表单。"""

    fields: Mapping[str, str]
    radio_groups: Mapping[str, Sequence[str]]
    textarea_names: Sequence[str]

    @classmethod
    def from_html(cls, page_html: str) -> EvaluationForm:
        parser = _EvaluationFormParser()
        parser.feed(page_html)
        fields, radio_groups, textarea_names = parser.form_fields()
        return cls(
            fields=fields,
            radio_groups=radio_groups,
            textarea_names=textarea_names,
        )

    def build_payload(
        self,
        *,
        choice: str,
        comment: str,
        fallback_task: EvaluationTask,
        fallback_token: str,
    ) -> dict[str, str]:
        payload = dict(self.fields)
        payload.update(
            {
                "optType": "submit",
                "tokenValue": payload.get("tokenValue", fallback_token),
                "questionnaireCode": payload.get(
                    "questionnaireCode",
                    fallback_task.questionnaire_code,
                ),
                "evaluationContent": payload.get(
                    "evaluationContent",
                    fallback_task.content_number,
                ),
                "evaluatedPeopleNumber": payload.get(
                    "evaluatedPeopleNumber",
                    fallback_task.teacher_number,
                ),
            },
        )
        for name, values in self.radio_groups.items():
            payload[name] = _select_choice_value(values, choice)
        if not self.radio_groups:
            score = SCORE_MAP[choice]
            payload.update(dict.fromkeys(DEFAULT_QUESTION_IDS, score))
        _fill_comment(payload, self.textarea_names, comment)
        return payload


def _select_choice_value(values: Sequence[str], choice: str) -> str:
    prefixes = CHOICE_PREFIXES[choice]
    for prefix in prefixes:
        for value in values:
            if value.startswith(prefix):
                return value
    if values:
        return values[0]
    msg = "评教题目没有可选项"
    raise EvaluationError(msg)


def _fill_comment(
    payload: dict[str, str],
    textarea_names: Sequence[str],
    comment: str,
) -> None:
    target_names = [name for name in textarea_names if name in TEXTAREA_NAMES]
    if not target_names:
        target_names = ["zgpj"]
    for name in target_names:
        payload[name] = comment


def _require_mapping(
    source: Mapping[str, object],
    key: str,
) -> Mapping[str, object]:
    value = source.get(key)
    if not isinstance(value, Mapping):
        msg = f"评教任务字段 {key!r} 不是对象"
        raise EvaluationError(msg)
    return value


def _require_text(source: Mapping[str, object], key: str) -> str:
    value = source.get(key)
    if value is None or value == "":
        msg = f"评教任务缺少字段 {key!r}"
        raise EvaluationError(msg)
    return str(value)


@dataclass(frozen=True, slots=True)
class EvaluationTask:
    """提交一门课程评教所需的稳定字段。"""

    is_evaluated: bool
    teacher_name: str
    teacher_number: str
    questionnaire_code: str
    questionnaire_name: str
    course_sequence_number: str
    content_number: str
    course_name: str

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> EvaluationTask:
        identifier = _require_mapping(payload, "id")
        questionnaire = _require_mapping(payload, "questionnaire")
        is_evaluated = str(payload.get("isEvaluated", "")).strip() == "是"
        return cls(
            is_evaluated=is_evaluated,
            teacher_name=_require_text(payload, "evaluatedPeople"),
            teacher_number=_require_text(identifier, "evaluatedPeople"),
            questionnaire_code=_require_text(identifier, "questionnaireCoding"),
            questionnaire_name=_require_text(questionnaire, "questionnaireName"),
            course_sequence_number=_require_text(
                identifier,
                "coureSequenceNumber",
            ),
            content_number=_require_text(identifier, "evaluationContentNumber"),
            course_name=_require_text(payload, "evaluationContent"),
        )


@dataclass(frozen=True, slots=True)
class PreparedEvaluation:
    """已打开评教页并构造好提交表单的一门课程。"""

    task: EvaluationTask
    page_html: str
    payload: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class EvaluationSubmitResult:
    """单门课程评教提交结果。"""

    task: EvaluationTask
    error: Exception | None = None

    @property
    def succeeded(self) -> bool:
        return self.error is None


@dataclass(frozen=True, slots=True)
class EvaluationOptions:
    default_choice: str = "A"
    comment: str = DEFAULT_COMMENT
    wait_seconds: float = 120.0
    submit_limit: int | None = None
    concurrency: int = 3

    def __post_init__(self) -> None:
        choice = self.default_choice.strip().upper()
        if choice not in SCORE_MAP:
            msg = "default_choice must be A, B, C, D or E"
            raise ValueError(msg)
        if choice != self.default_choice:
            object.__setattr__(self, "default_choice", choice)
        if not self.comment.strip():
            msg = "evaluation comment cannot be empty"
            raise ValueError(msg)
        if self.comment != self.comment.strip():
            object.__setattr__(self, "comment", self.comment.strip())
        if self.wait_seconds < 0:
            msg = "wait_seconds cannot be negative"
            raise ValueError(msg)
        if self.submit_limit is not None and self.submit_limit < 1:
            msg = "submit_limit must be at least 1"
            raise ValueError(msg)
        if self.concurrency < 1:
            msg = "concurrency must be at least 1"
            raise ValueError(msg)


ConfirmationCallback = Callable[[Sequence[EvaluationTask]], Awaitable[bool]]


class TeachingEvaluationClient:
    """执行正式教学评估提交。"""

    def __init__(
        self,
        *,
        options: EvaluationOptions | None = None,
        confirm: ConfirmationCallback | None = None,
    ) -> None:
        self.options = options or EvaluationOptions()
        self.default_choice = self.options.default_choice
        self.comment = self.options.comment
        self.wait_seconds = self.options.wait_seconds
        self.submit_limit = self.options.submit_limit
        self.concurrency = self.options.concurrency
        self._confirm = confirm

    @staticmethod
    def extract_token(html: str) -> str:
        """从评教页面提取 tokenValue。"""
        try:
            return extract_token_value(html)
        except AuthError as error:
            msg = _build_missing_token_message(html)
            raise EvaluationError(msg) from error

    @staticmethod
    def build_page_form(task: EvaluationTask, token: str) -> dict[str, str]:
        return {
            "evaluatedPeople": task.teacher_name,
            "evaluatedPeopleNumber": task.teacher_number,
            "questionnaireCode": task.questionnaire_code,
            "questionnaireName": task.questionnaire_name,
            "coureSequenceNumber": task.course_sequence_number,
            "evaluationContentNumber": task.content_number,
            "evaluationContentContent": task.course_name,
            "tokenValue": token,
        }

    def build_assessment_payload(
        self,
        task: EvaluationTask,
        token: str,
        page_html: str = "",
    ) -> dict[str, str]:
        """构造评教提交表单。"""
        form = EvaluationForm.from_html(page_html)
        payload = form.build_payload(
            choice=self.default_choice,
            comment=self.comment,
            fallback_task=task,
            fallback_token=token,
        )
        payload.setdefault("count", "")
        return payload

    @staticmethod
    def tasks_from_data(data: Mapping[str, object]) -> list[EvaluationTask]:
        raw_tasks = data.get("data", [])
        if not isinstance(raw_tasks, list):
            msg = "评教接口的 data 字段不是列表"
            raise EvaluationError(msg)

        tasks: list[EvaluationTask] = []
        for raw_task in raw_tasks:
            if not isinstance(raw_task, Mapping):
                msg = "评教任务不是对象"
                raise EvaluationError(msg)
            tasks.append(EvaluationTask.from_payload(raw_task))
        return tasks

    @classmethod
    def pending_tasks(cls, data: Mapping[str, object]) -> list[EvaluationTask]:
        return [task for task in cls.tasks_from_data(data) if not task.is_evaluated]

    async def _request_text_with_fallback(
        self,
        jws: AsyncJWSSession,
        method: str,
        paths: Sequence[str],
        *,
        data: object | None = None,
    ) -> str:
        last_error: ServiceError | None = None
        for path in paths:
            result, error = await self._request_candidate_path(
                jws,
                method,
                path,
                data=data,
            )
            if error is None:
                return result
            last_error = error
            log.warning("请求路径不存在，尝试备用路径：%s", path)
        msg = f"所有候选路径都返回 404：{', '.join(paths)}"
        raise EvaluationError(msg) from last_error

    @staticmethod
    async def _request_candidate_path(
        jws: AsyncJWSSession,
        method: str,
        path: str,
        *,
        data: object | None = None,
    ) -> tuple[str, ServiceError | None]:
        try:
            return await jws.request_text(method, path, data=data), None
        except ServiceError as error:
            if error.status != HTTP_STATUS_NOT_FOUND:
                raise
            return "", error

    async def _confirm_submission(self, tasks: Sequence[EvaluationTask]) -> None:
        if self._confirm is None:
            msg = "真实提交评教前必须提供确认回调"
            raise EvaluationError(msg)
        if not await self._confirm(tasks):
            msg = "用户取消了评教提交"
            raise EvaluationCancelledError(msg)

    async def _prepare_task(
        self,
        jws: AsyncJWSSession,
        task: EvaluationTask,
    ) -> PreparedEvaluation:
        index_html = await jws.request_text("GET", EVALUATION_INDEX_PATH)
        token = self.extract_token(index_html)
        page_html = await self._request_text_with_fallback(
            jws,
            "POST",
            EVALUATION_PAGE_PATHS,
            data=self.build_page_form(task, token),
        )
        payload = self.build_assessment_payload(task, token, page_html)
        return PreparedEvaluation(task=task, page_html=page_html, payload=payload)

    async def _submit_prepared_task(
        self,
        jws: AsyncJWSSession,
        prepared: PreparedEvaluation,
    ) -> None:
        response_text = await self._request_text_with_fallback(
            jws,
            "POST",
            SUBMIT_PATHS,
            data=prepared.payload,
        )
        self._validate_submit_response(response_text, prepared.task)

    async def _run_limited(
        self,
        items: Sequence[EvaluationTask],
        worker: Callable[[EvaluationTask], Awaitable[PreparedEvaluation]],
    ) -> list[PreparedEvaluation]:
        semaphore = asyncio.Semaphore(self.concurrency)

        async def run_one(item: EvaluationTask) -> PreparedEvaluation:
            async with semaphore:
                return await worker(item)

        return await asyncio.gather(*(run_one(item) for item in items))

    async def _submit_limited(
        self,
        items: Sequence[PreparedEvaluation],
        worker: Callable[[PreparedEvaluation], Awaitable[None]],
    ) -> list[EvaluationSubmitResult]:
        semaphore = asyncio.Semaphore(self.concurrency)

        async def run_one(item: PreparedEvaluation) -> EvaluationSubmitResult:
            async with semaphore:
                try:
                    await worker(item)
                except Exception as error:  # noqa: BLE001
                    return EvaluationSubmitResult(task=item.task, error=error)
                return EvaluationSubmitResult(task=item.task)

        return await asyncio.gather(*(run_one(item) for item in items))

    async def _submit_tasks(
        self,
        jws: AsyncJWSSession,
        tasks: Sequence[EvaluationTask],
    ) -> int:
        log.info("正在并发打开 %d 门课程的评教页", len(tasks))
        prepared_tasks = await self._run_limited(
            tasks,
            lambda task: self._prepare_task(jws, task),
        )
        if self.wait_seconds:
            log.info("全部评教页已打开，统一等待 %.0f 秒后提交", self.wait_seconds)
            await asyncio.sleep(self.wait_seconds)
        log.info("开始并发提交 %d 门课程评教", len(prepared_tasks))
        results = await self._submit_limited(
            prepared_tasks,
            lambda prepared: self._submit_prepared_task(jws, prepared),
        )
        for result in results:
            if result.error is not None:
                log.error(
                    "评教提交失败：%s | %s | %s",
                    result.task.teacher_name,
                    result.task.course_name,
                    result.error,
                )
                continue
            log.info(
                "已提交评教：%s | %s",
                result.task.teacher_name,
                result.task.course_name,
            )
        failed = [result for result in results if result.error is not None]
        if failed:
            raise EvaluationBatchError(results)
        return len(results)

    @staticmethod
    def _validate_submit_response(response_text: str, task: EvaluationTask) -> None:
        normalized = response_text.lower().replace(" ", "")
        if any(marker in normalized for marker in SUBMIT_SUCCESS_MARKERS):
            return
        if any(marker in normalized for marker in SUBMIT_FAILURE_MARKERS):
            preview = response_text[:200].replace("\n", " ").replace("\r", " ")
            msg = f"评教提交被服务端拒绝：{task.course_name} | {preview}"
            raise EvaluationError(msg)
        preview = response_text[:120].replace("\n", " ").replace("\r", " ")
        log.info("评教提交响应未识别，按 HTTP 成功处理：%s", preview)

    async def run(
        self,
        jws: AsyncJWSSession,
        data: Mapping[str, object],
        selected_tasks: Sequence[EvaluationTask] | None = None,
    ) -> int:
        """提交所有选中的未评教任务，并返回成功提交数量。"""
        pending = self.pending_tasks(data)
        log.info("共有 %d 门课程待评教", len(pending))
        if not pending:
            return 0

        selected = list(selected_tasks) if selected_tasks is not None else pending
        selected = [task for task in selected if not task.is_evaluated]
        if not selected:
            log.info("没有选中未评教课程")
            return 0

        tasks_to_submit = selected[: self.submit_limit]
        await self._confirm_submission(tasks_to_submit)
        return await self._submit_tasks(jws, tasks_to_submit)


async def handle_teaching_evaluation(
    jws: AsyncJWSSession,
    settings: Settings,
) -> None:
    try:
        data = await fetch_tasks(jws)
        tasks = TeachingEvaluationClient.tasks_from_data(data)
        selected_tasks = await _choose_evaluation_tasks(tasks)
        if selected_tasks is None:
            return

        client = TeachingEvaluationClient(
            options=EvaluationOptions(
                default_choice=settings.default_choice,
                comment=settings.default_comment,
                wait_seconds=settings.evaluation_wait_seconds,
                submit_limit=settings.evaluation_limit,
                concurrency=settings.evaluation_concurrency,
            ),
            confirm=_confirm_evaluation,
        )
        submitted = await client.run(jws, data, selected_tasks=selected_tasks)
    except EvaluationCancelledError:
        log.warning("未通过最终确认，已取消评教")
        return
    except EvaluationBatchError as error:
        succeeded = sum(result.succeeded for result in error.results)
        failed = len(error.results) - succeeded
        log.warning("评教结束：成功 %d 门，失败 %d 门", succeeded, failed)
        return
    except (EvaluationError, ServiceError, ValueError) as error:
        log.warning("评教失败：%s", error)
        return
    except Exception:
        log.exception("评教出现未处理异常")
        return

    log.info("评教结束，共提交 %d 门课程", submitted)


async def _confirm_evaluation(tasks: Sequence[EvaluationTask]) -> bool:
    log.warning("共有 %d 门课程，一旦提交无法修改", len(tasks))
    for task in tasks:
        log.warning("- %s | %s", task.teacher_name, task.course_name)
    log.warning("若确认继续，请完整输入：%s", CONFIRM_PHRASE)
    user_input = (await aioconsole.ainput("请输入确认语句：")).strip()
    return user_input == CONFIRM_PHRASE


def _show_evaluation_tasks(tasks: Sequence[EvaluationTask]) -> None:
    if not tasks:
        log.info("没有查询到评教任务")
        return
    log.info("评教任务列表：")
    for index, task in enumerate(tasks, start=1):
        status = "已评教" if task.is_evaluated else "未评教"
        log.info(
            "%2d. [%s] %s | %s | %s",
            index,
            status,
            task.course_name,
            task.teacher_name,
            task.questionnaire_name,
        )


def _parse_task_selection(
    raw_choice: str,
    tasks: Sequence[EvaluationTask],
) -> list[EvaluationTask]:
    normalized = raw_choice.strip().lower()
    if normalized in {"all", "a", "全部"}:
        return [task for task in tasks if not task.is_evaluated]

    selected: list[EvaluationTask] = []
    seen: set[int] = set()
    for raw_part in normalized.replace("，", ",").split(","):
        part = raw_part.strip()
        if not part:
            continue
        try:
            index = int(part)
        except ValueError as error:
            msg = "请输入课程序号，多个序号用逗号分隔，或输入 all"
            raise ValueError(msg) from error
        if index < 1 or index > len(tasks):
            msg = f"课程序号超出范围：{index}"
            raise ValueError(msg)
        if index in seen:
            continue
        seen.add(index)
        selected.append(tasks[index - 1])
    return selected


async def _choose_evaluation_tasks(
    tasks: Sequence[EvaluationTask],
) -> list[EvaluationTask] | None:
    _show_evaluation_tasks(tasks)
    if not any(not task.is_evaluated for task in tasks):
        log.info("所有课程都已评教")
        return None

    prompt = (
        "请输入要评教的序号，多个用逗号分隔；输入 all 评教全部未评教；输入 0 返回："
    )
    while True:
        choice = (await aioconsole.ainput(prompt)).strip()
        if choice in {"0", "q", "Q"}:
            return None
        try:
            selected = _parse_task_selection(choice, tasks)
        except ValueError as error:
            log.warning("%s", error)
            continue
        selected = [task for task in selected if not task.is_evaluated]
        if selected:
            return selected
        log.warning("没有选中未评教课程，请重新选择")


def _build_missing_token_message(html: str) -> str:
    normalized = html.replace(" ", "").replace("\n", "").replace("\r", "")
    markers = (
        "截止",
        "结束",
        "不可评",
        "不能评",
        "无需评教",
        "已完成",
        "未开放",
        "关闭",
    )
    if any(marker in normalized for marker in markers):
        return "评教页面未返回 tokenValue，评教可能已截止、未开放或当前课程不可评"
    return "评教页面未返回 tokenValue，页面结构可能已变化或当前状态不允许提交"
