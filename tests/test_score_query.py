"""成绩查询回调数据解析测试"""

from __future__ import annotations

import unittest

from urp_academic_affairs_tools.client.errors import ServiceError
from urp_academic_affairs_tools.score_query.score_query import (
    ScoreRecord,
    ScoreView,
    _extract_data_path,
    _parse_callback_scores,
    _parse_this_term_scores,
    calculate_average_grade_point,
    filter_score_records,
    score_terms,
)


class ScoreQueryTests(unittest.TestCase):
    @staticmethod
    def _score_record(
        *,
        credit: str,
        grade_point: str,
        course_attribute: str = "必修",
    ) -> ScoreRecord:
        return ScoreRecord(
            academic_term="2024-2025学年秋",
            term_key="2024-2025-1-1",
            course_name="测试课程",
            course_number="TEST001",
            class_number="01",
            credit=credit,
            score="80",
            grade_point=grade_point,
            course_attribute=course_attribute,
            exam_type="考试",
            unpassed_reason="",
            maximum_score="",
            minimum_score="",
            average_score="",
            rank="",
        )

    def test_extracts_server_generated_callback_path(self) -> None:
        html = (
            '<script>var url = "'
            "/student/integratedQuery/scoreQuery/aB3dE7fG91/allPassingScores/callback"
            '";</script>'
        )
        self.assertEqual(
            _extract_data_path(html, ScoreView.PASSING),
            "/student/integratedQuery/scoreQuery/aB3dE7fG91/allPassingScores/callback",
        )

    def test_rejects_missing_data_path(self) -> None:
        with self.assertRaises(ServiceError):
            _extract_data_path("<html></html>", ScoreView.PASSING)

    def test_parses_callback_fields_from_nested_identifier(self) -> None:
        data = {
            "lnList": [
                {
                    "zxjxjhh": "2024-2025-1-1",
                    "cjList": [
                        {
                            "id": {
                                "courseNumber": "Q18402",
                                "coureSequenceNumber": "01",
                            },
                            "academicYearCode": "2024-2025",
                            "termName": "秋",
                            "courseName": "计算科学导论",
                            "credit": "2.0",
                            "courseScore": "86",
                            "gradePointScore": "3.6",
                            "courseAttributeName": "必修",
                            "examTypeCode": "01",
                        },
                    ],
                },
            ],
        }
        record = _parse_callback_scores(data)[0]
        self.assertEqual(record.academic_term, "2024-2025学年秋")
        self.assertEqual(record.course_number, "Q18402")
        self.assertEqual(record.exam_type, "考试")

    def test_filters_callback_data_by_selected_term(self) -> None:
        data = {
            "lnList": [
                {
                    "zxjxjhh": "2024-2025-1-1",
                    "cjList": [{"academicYearCode": "2024-2025", "termName": "秋"}],
                },
                {
                    "zxjxjhh": "2025-2026-2-1",
                    "cjList": [{"academicYearCode": "2025-2026", "termName": "春"}],
                },
            ],
        }
        records = _parse_callback_scores(data)
        terms = score_terms(records)
        self.assertEqual(terms[0].label, "2025-2026学年春")
        self.assertEqual(
            len(filter_score_records(records, "2024-2025-1-1")),
            1,
        )

    def test_parses_this_term_scores(self) -> None:
        data = [
            {
                "list": [
                    {
                        "id": {
                            "executiveEducationPlanNumber": "2026-2027-1-1",
                        },
                        "courseName": "Linux操作系统",
                        "credit": "3.5",
                        "coursePropertyName": "必修",
                        "courseScore": "86",
                        "gradePoint": "4.2",
                        "maxcj": "98",
                        "mincj": "56",
                        "avgcj": "82.4",
                        "rank": "6",
                    },
                ],
            },
        ]
        record = _parse_this_term_scores(data)[0]
        self.assertEqual(record.course_name, "Linux操作系统")
        self.assertEqual(record.course_attribute, "必修")
        self.assertEqual(record.grade_point, "4.2")
        self.assertEqual(record.maximum_score, "98")
        self.assertEqual(record.minimum_score, "56")
        self.assertEqual(record.average_score, "82.4")
        self.assertEqual(record.rank, "6")

    def test_fills_this_term_from_response_context_when_rows_omit_term(self) -> None:
        data = [
            {
                "list": [
                    {
                        "id": {
                            "executiveEducationPlanNumber": "2025-2026-2-1",
                        },
                        "courseName": "数据库原理",
                        "courseScore": "92",
                    },
                ],
            },
        ]
        record = _parse_this_term_scores(data)[0]
        self.assertEqual(record.term_key, "2025-2026-2-1")
        self.assertEqual(record.academic_term, "2025-2026学年春")

    def test_keeps_grade_point_empty_when_this_term_score_is_missing(self) -> None:
        data = [{"list": [{"courseScore": None, "gradePoint": "4.0"}]}]
        record = _parse_this_term_scores(data)[0]
        self.assertEqual(record.grade_point, "")

    def test_calculates_weighted_average_grade_point(self) -> None:
        records = [
            self._score_record(credit="3", grade_point="3.0"),
            self._score_record(credit="1.5", grade_point="4.0"),
            self._score_record(credit="2", grade_point="0"),
            self._score_record(
                credit="2",
                grade_point="4.0",
                course_attribute="任选",
            ),
            self._score_record(credit="invalid", grade_point="3.0"),
            self._score_record(credit="1", grade_point="-999.999"),
        ]
        self.assertEqual(calculate_average_grade_point(records), "2.31")

    def test_returns_none_when_no_grade_points_can_be_calculated(self) -> None:
        records = [
            self._score_record(credit="3", grade_point=""),
            self._score_record(credit="0", grade_point="3.0"),
        ]
        self.assertIsNone(calculate_average_grade_point(records))


if __name__ == "__main__":
    unittest.main()
