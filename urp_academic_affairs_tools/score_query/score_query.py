"""教务系统成绩查询接口与数据解析"""

from __future__ import annotations

import json
import logging
import re
import sys
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from enum import Enum
from typing import TYPE_CHECKING, Any

import aioconsole
from urp_academic_affairs_tools.client.errors import ServiceError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from urp_academic_affairs_tools.client.session import AsyncJWSSession

SCORE_QUERY_ROOT = "/student/integratedQuery/scoreQuery"
log = logging.getLogger(__name__)


class ScoreView(str, Enum):
    PASSING = "passing"
    UNPASSED = "unpassed"
    THIS_TERM = "this_term"


@dataclass(frozen=True, slots=True)
class ScoreRecord:
    """统一后的单门课程成绩"""

    academic_term: str
    term_key: str
    course_name: str
    course_number: str
    class_number: str
    credit: str
    score: str
    grade_point: str
    course_attribute: str
    exam_type: str
    unpassed_reason: str
    maximum_score: str
    minimum_score: str
    average_score: str
    rank: str


@dataclass(frozen=True, slots=True)
class ScoreTerm:
    """成绩页面允许查询的学年学期"""

    value: str
    label: str


@dataclass(frozen=True, slots=True)
class ScoreQueryClient:
    """从成绩页面提取短期数据 URL 并查询其返回数据"""

    jws: AsyncJWSSession

    async def query(
        self,
        view: ScoreView,
    ) -> list[ScoreRecord]:
        index_path = _index_path(view)
        html = await self.jws.request_text("GET", index_path)
        data_path = _extract_data_path(html, view)

        data = await self._request_data("GET", data_path)
        if view is ScoreView.THIS_TERM:
            return _parse_this_term_scores(data)
        return _parse_callback_scores(data)

    async def _request_data(
        self,
        method: str,
        path: str,
        *,
        data: dict[str, str] | None = None,
    ) -> object:
        text = await self.jws.request_text(method, path, data=data)
        try:
            return json.loads(text)
        except json.JSONDecodeError as error:
            msg = "score query data response is not valid JSON"
            raise ServiceError(msg) from error


def _index_path(view: ScoreView) -> str:
    paths = {
        ScoreView.PASSING: f"{SCORE_QUERY_ROOT}/allPassingScores/index",
        ScoreView.UNPASSED: f"{SCORE_QUERY_ROOT}/unpassedScores/index",
        ScoreView.THIS_TERM: f"{SCORE_QUERY_ROOT}/thisTermScores/index",
    }
    return paths[view]


def _extract_data_path(html: str, view: ScoreView) -> str:
    suffix = {
        ScoreView.PASSING: r"allPassingScores/callback",
        ScoreView.UNPASSED: r"unpassed/scores/callback",
        ScoreView.THIS_TERM: r"thisTermScores/data",
    }[view]
    pattern = rf'["\'](?P<path>{SCORE_QUERY_ROOT}/[^"\']+/{suffix})["\']'
    match = re.search(pattern, html)
    if match is None:
        msg = f"score query data URL was not found for {view.value}"
        raise ServiceError(msg)
    return match.group("path")


def _parse_callback_scores(data: object) -> list[ScoreRecord]:
    if not isinstance(data, dict):
        return []
    term_groups = data.get("lnList")
    if not isinstance(term_groups, list):
        return []
    records: list[ScoreRecord] = []
    for group in term_groups:
        if not isinstance(group, dict):
            continue
        term_key = _string(group.get("zxjxjhh"))
        scores = group.get("cjList")
        if not isinstance(scores, list):
            continue
        records.extend(
            _callback_record(score, term_key)
            for score in scores
            if isinstance(score, dict)
        )
    return records


def _callback_record(
    score: dict[str, Any],
    term_key: str,
) -> ScoreRecord:
    academic_term = _academic_term_from_score(score, term_key)
    identifier = score.get("id")
    identifier_data = identifier if isinstance(identifier, dict) else {}
    course_score = _first_string(score, "courseScore", "cj")
    return ScoreRecord(
        academic_term=academic_term,
        term_key=term_key,
        course_name=_first_string(score, "courseName", "tdkcm"),
        course_number=_first_string(identifier_data, "courseNumber", "kch_zj"),
        class_number=_first_string(identifier_data, "coureSequenceNumber"),
        credit=_first_string(score, "credit"),
        score=course_score,
        grade_point=(
            _first_string(score, "gradePointScore", "gradePoint")
            if course_score
            else ""
        ),
        course_attribute=_first_string(
            score,
            "courseAttributeName",
            "coursePropertyName",
            "xkcsxmc",
        ),
        exam_type=_exam_type_name(score),
        unpassed_reason=_first_string(
            score,
            "unpassedReasonExplain",
            "notByReasonName",
        ),
        maximum_score=_first_string(score, "maxcj"),
        minimum_score=_first_string(score, "mincj"),
        average_score=_first_string(score, "avgcj"),
        rank=_first_string(score, "rank"),
    )


def _parse_this_term_scores(data: object) -> list[ScoreRecord]:
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        return []
    container = data[0]
    scores = container.get("list")
    if not isinstance(scores, list):
        return []
    records: list[ScoreRecord] = []
    for score in scores:
        if not isinstance(score, dict):
            continue
        record = _callback_record(score, _term_key_from_score(score))
        records.append(record)
    return records


def _first_string(
    data: dict[str, Any],
    *keys: str,
    default: str = "",
) -> str:
    for key in keys:
        value = _string(data.get(key))
        if value:
            return value
    return default


def _string(value: object) -> str:
    return "" if value is None else str(value).strip()


def _term_key_from_score(score: dict[str, Any]) -> str:
    identifier = score.get("id")
    if not isinstance(identifier, dict):
        return ""
    return _string(identifier.get("executiveEducationPlanNumber"))


def _academic_term_from_score(
    score: dict[str, Any],
    term_key: str = "",
) -> str:
    academic_year = _first_string(score, "academicYearCode")
    term_name = _first_string(score, "termName")
    if academic_year:
        return (
            f"{academic_year}学年{term_name}" if term_name else f"{academic_year}学年"
        )
    return _label_from_term_key(term_key)


def _label_from_term_key(term_key: str) -> str:
    match = re.fullmatch(r"(?P<year>\d{4}-\d{4})-(?P<term>\d+)(?:-\d+)?", term_key)
    if match is None:
        return ""
    term_name = {"1": "秋", "2": "春"}.get(match.group("term"), "")
    return f"{match.group('year')}学年{term_name}" if term_name else match.group("year")


def _exam_type_name(score: dict[str, Any]) -> str:
    explicit_name = _first_string(score, "examTypeName")
    if explicit_name:
        return explicit_name
    return {"01": "考试", "02": "考查"}.get(
        _first_string(score, "examTypeCode"),
        "",
    )


def score_terms(records: Sequence[ScoreRecord]) -> list[ScoreTerm]:
    """按学年学期降序排列"""
    values = {
        record.term_key: record.academic_term for record in records if record.term_key
    }
    return [
        ScoreTerm(value=value, label=label)
        for value, label in sorted(values.items(), reverse=True)
    ]


def filter_score_records(
    records: Sequence[ScoreRecord],
    term_key: str,
) -> list[ScoreRecord]:
    return [record for record in records if not term_key or record.term_key == term_key]


def calculate_average_grade_point(records: Sequence[ScoreRecord]) -> str | None:
    """计算不含任选课的加权平均学分绩点。"""
    total_credits = Decimal()
    total_grade_points = Decimal()
    for record in records:
        if record.course_attribute == "任选":
            continue
        try:
            credit = Decimal(record.credit)
            grade_point = Decimal(record.grade_point)
        except (InvalidOperation, ValueError):
            continue
        if credit <= 0 or grade_point < 0:
            continue
        total_credits += credit
        total_grade_points += credit * grade_point
    if not total_credits:
        return None
    average = (total_grade_points / total_credits).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )
    return f"{average:.2f}"


async def handle_score_query(jws: AsyncJWSSession) -> None:
    client = ScoreQueryClient(jws)
    choices = {
        "1": ("全部及格成绩", ScoreView.PASSING),
        "2": ("不及格成绩", ScoreView.UNPASSED),
        "3": ("本学期成绩", ScoreView.THIS_TERM),
    }
    while True:
        _print_line("\n成绩查询")
        for key, (name, _) in choices.items():
            _print_line(f"{key}. {name}")
        _print_line("0. 返回")
        choice = (await aioconsole.ainput("请输入选项：")).strip()
        if choice == "0":
            return
        selected = choices.get(choice)
        if selected is None:
            log.warning("无效选项")
            continue
        name, view = selected
        records = await client.query(view)
        if view is ScoreView.PASSING:
            records = filter_score_records(records, await _read_score_term(records))
        _print_line(f"\n{name}：{len(records)} 门")
        _print_score_table(records)


def _print_score_table(records: list[ScoreRecord]) -> None:
    headers = [
        "学年学期",
        "课程",
        "课程号",
        "课程属性",
        "考试类型",
        "学分",
        "绩点",
        "成绩",
    ]
    rows = [
        [
            record.academic_term,
            record.course_name,
            record.course_number,
            record.course_attribute,
            record.exam_type,
            record.credit,
            record.grade_point,
            record.score,
        ]
        for record in records
    ]
    widths = [16, 38, 10, 10, 10, 6, 6, 6]
    _print_line(_format_score_row(headers, widths))
    _print_line("-+-".join("-" * width for width in widths))
    for row in rows:
        _print_line(_format_score_row(row, widths))


def _format_score_row(values: Sequence[str], widths: Sequence[int]) -> str:
    return " | ".join(
        _fit_display_width(value, width)
        for value, width in zip(values, widths, strict=True)
    )


def _print_line(text: str) -> None:
    sys.stdout.write(f"{text}\n")


async def _read_score_term(records: Sequence[ScoreRecord]) -> str:
    terms = score_terms(records)
    _print_line("0. 全部")
    for index, term in enumerate(terms, start=1):
        _print_line(f"{index}. {term.label}")
    while True:
        selected = (await aioconsole.ainput("请选择学年学期：")).strip()
        if selected == "0":
            return ""
        if selected.isdigit() and 1 <= int(selected) <= len(terms):
            return terms[int(selected) - 1].value
        log.warning("无效选项")


def _fit_display_width(text: str, width: int) -> str:
    result: list[str] = []
    current_width = 0
    for char in text:
        char_width = 2 if unicodedata.east_asian_width(char) in {"F", "W", "A"} else 1
        if current_width + char_width > width - 1:
            return "".join(result) + "…"
        result.append(char)
        current_width += char_width
    return "".join(result) + " " * (width - current_width)
