"""选课解析和策略的离线测试"""

import json
import unittest

from urp_academic_affairs_tools.course_selection import (
    CourseSelectionCandidate,
    CourseSnatchingOptions,
    parse_course_candidates,
    extract_course_select_token,
    filter_course_candidates,
)
from urp_academic_affairs_tools.course_selection.course_selection import (
    _extract_context_value,
    _is_permanent_course_failure,
    parse_course_select_page,
)
from urp_academic_affairs_tools.client import (
    AsyncJWSSession,
    AuthenticationFailure,
    ConcurrentSessionExpiredError,
    RetryPolicy,
)
from urp_academic_affairs_tools.client.auth import classify_authentication_failure


class CourseSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.courses = [
            CourseSelectionCandidate("Q52124", "01", "1", "Linux"),
            CourseSelectionCandidate("Q52124", "02", "2", "Linux"),
            CourseSelectionCandidate("Q99999", "01", "1", "Other"),
        ]

    def test_filter_by_course_number(self) -> None:
        result = filter_course_candidates(self.courses, "q52124")
        self.assertEqual(
            [course.course_code for course in result], ["Q52124_01", "Q52124_02"]
        )

    def test_filter_by_course_code(self) -> None:
        result = filter_course_candidates(self.courses, "Q52124_02")
        self.assertEqual([course.course_code for course in result], ["Q52124_02"])

    def test_reject_invalid_course_code(self) -> None:
        with self.assertRaises(ValueError):
            filter_course_candidates(self.courses, "Q52124-02")

    def test_parse_callback_context(self) -> None:
        data = {
            "dateList": [
                {
                    "programPlanNumber": "20959",
                    "executiveEducationPlanNumber": "2026-2027-1-1",
                },
            ],
        }
        self.assertEqual(_extract_context_value(data, "programPlanNumber"), "20959")
        self.assertEqual(
            _extract_context_value(data, "executiveEducationPlanNumber"),
            "2026-2027-1-1",
        )

    def test_classify_missing_token(self) -> None:
        with self.assertRaisesRegex(ValueError, "当前选课阶段已过截止时间"):
            extract_course_select_token("当前选课阶段已过截止时间")

    def test_parse_course_list_ignores_selected_course_list(self) -> None:
        html = json.dumps(
            {
                "rwfalist": [
                    {
                        "courseNum": "Q52124",
                        "classNum": "02",
                        "termCode": "2025-2026-2-1",
                        "kcm": "Linux",
                    },
                ],
                "yxkclist": json.dumps(
                    [
                        {
                            "id": {
                                "coureNumber": "Q99999",
                                "coureSequenceNumber": "01",
                                "executiveEducationPlanNumber": "2025-2026-2-1",
                            },
                            "courseName": "Already selected",
                        },
                    ],
                ),
            },
        )
        result = parse_course_candidates(html)
        self.assertEqual([course.course_code for course in result], ["Q52124_02"])

    def test_parse_empty_course_list_returns_no_candidates(self) -> None:
        html = json.dumps(
            {
                "rwfalist": [],
                "kchlist": ["Q52124"],
                "yxkclist": "[]",
            },
        )
        self.assertEqual(parse_course_candidates(html), [])

    def test_parse_nested_json_without_unescaping_outer_response(self) -> None:
        html = json.dumps(
            {
                "rwfalist": [],
                "yxkclist": json.dumps(
                    [
                        {
                            "courseName": "Already selected",
                            "id": {
                                "coureNumber": "Q99999",
                                "coureSequenceNumber": "01",
                                "executiveEducationPlanNumber": "2025-2026-2-1",
                            },
                        },
                    ],
                ),
            },
        )
        self.assertEqual(parse_course_candidates(html), [])

    def test_snatching_options_allow_continuous_mode(self) -> None:
        options = CourseSnatchingOptions()
        self.assertEqual(options.attempts, 0)
        self.assertEqual(options.concurrency, 10)

    def test_classify_permanent_submission_failure(self) -> None:
        self.assertTrue(_is_permanent_course_failure("课程时间冲突"))
        self.assertFalse(_is_permanent_course_failure("人数已满，请稍后重试"))

    def test_parse_dynamic_course_page_context(self) -> None:
        html = """
        <input id="tokenValue" value="token">
        <input name="fajhh" value="20959">
        <select id="jhxn"><option value="2026-2027-1-1" selected>秋</option></select>
        <select id="kcsxdm"><option value="" selected>全部</option></select>
        <select id="xqh"><option value="007" selected>校区</option></select>
        """
        page = parse_course_select_page(html)
        self.assertEqual(page.program_plan_number, "20959")
        self.assertEqual(page.academic_term, "2026-2027-1-1")
        self.assertEqual(page.course_property, "")
        self.assertEqual(page.campus, "007")

    def test_session_error_detection_helpers(self) -> None:
        self.assertTrue(
            AsyncJWSSession.check_login_page("tokenValue j_spring_security_check")
        )
        self.assertTrue(AsyncJWSSession._is_login_redirect("/gotoLogin"))  # noqa: SLF001
        error = AsyncJWSSession._authentication_error(  # noqa: SLF001
            AuthenticationFailure.CONCURRENT_SESSION_EXPIRED,
            "/login?errorCode=concurrentSessionExpired",
        )
        self.assertIsInstance(error, ConcurrentSessionExpiredError)
        self.assertEqual(error.error_code, "concurrentSessionExpired")

    def test_authentication_middleware_classification(self) -> None:
        self.assertEqual(
            classify_authentication_failure(
                status=200,
                response_url=(
                    "https://jws.qgxy.cn/login?errorCode=concurrentSessionExpired"
                ),
            ),
            AuthenticationFailure.CONCURRENT_SESSION_EXPIRED,
        )
        self.assertEqual(
            classify_authentication_failure(
                status=403,
                response_url="https://jws.qgxy.cn/student/action",
                text="CSRF token expired",
            ),
            AuthenticationFailure.CSRF_TOKEN_EXPIRED,
        )
        self.assertEqual(
            classify_authentication_failure(
                status=302,
                response_url="https://jws.qgxy.cn/student/action",
                redirect_locations=("/login",),
            ),
            AuthenticationFailure.LOGIN_REDIRECT,
        )
        self.assertIsNone(
            classify_authentication_failure(
                status=200,
                response_url="https://jws.qgxy.cn/student/index",
                text="normal business response",
            ),
        )

    def test_retry_policy_rejects_invalid_delays(self) -> None:
        with self.assertRaises(ValueError):
            RetryPolicy(base_sleep=2, max_sleep=1)


if __name__ == "__main__":
    unittest.main()
