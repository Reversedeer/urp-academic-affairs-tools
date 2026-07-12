"""成绩查询回调数据解析测试。"""

from __future__ import annotations

import unittest

from urp_academic_affairs_tools.client.errors import ServiceError
from urp_academic_affairs_tools.score_query.score_query import (
    ScoreView,
    _extract_data_path,
    _parse_callback_scores,
    _parse_this_term_scores,
    filter_score_records,
    score_terms,
)


class ScoreQueryTests(unittest.TestCase):
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
                            "id": {"courseNumber": "Q18402", "coureSequenceNumber": "01"},
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
                        "academicYearCode": "2026-2027",
                        "termCode": "1",
                        "termName": "秋",
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

    def test_keeps_grade_point_empty_when_this_term_score_is_missing(self) -> None:
        data = [{"list": [{"courseScore": None, "gradePoint": "4.0"}]}]
        record = _parse_this_term_scores(data)[0]
        self.assertEqual(record.grade_point, "")


if __name__ == "__main__":
    unittest.main()
