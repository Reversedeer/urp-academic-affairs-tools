"""教务接口测试"""

from __future__ import annotations

import unittest

from urp_academic_affairs_tools.client.api import TIMETABLE_CALLBACK_RE, get_timetable


class TimetableApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_refreshes_dynamic_callback_before_each_request(self) -> None:
        class Session:
            def __init__(self) -> None:
                self.tokens = iter(("firstToken", "secondToken"))
                self.text_requests: list[tuple[str, str]] = []
                self.json_requests: list[tuple[str, str]] = []

            async def request_text(self, method: str, path: str) -> str:
                self.text_requests.append((method, path))
                return (
                    'url: "/student/courseSelect/thisSemesterCurriculum/'
                    f'{next(self.tokens)}/ajaxStudentSchedule/curr/callback"'
                )

            async def request_json(self, method: str, path: str) -> dict[str, object]:
                self.json_requests.append((method, path))
                return {"xkxx": []}

        session = Session()

        self.assertEqual(await get_timetable(session), {"xkxx": []})  # type: ignore[arg-type]
        self.assertEqual(await get_timetable(session), {"xkxx": []})  # type: ignore[arg-type]
        self.assertEqual(
            session.text_requests,
            2 * [("GET", "/student/courseSelect/thisSemesterCurriculum/index")],
        )
        self.assertEqual(
            session.json_requests,
            [
                (
                    "POST",
                    (
                        "/student/courseSelect/thisSemesterCurriculum/firstToken/"
                        "ajaxStudentSchedule/curr/callback"
                    ),
                ),
                (
                    "POST",
                    (
                        "/student/courseSelect/thisSemesterCurriculum/secondToken/"
                        "ajaxStudentSchedule/curr/callback"
                    ),
                ),
            ],
        )

    def test_finds_dynamic_main_timetable_callback(self) -> None:
        html = """$.ajax({
            url: "/student/courseSelect/thisSemesterCurriculum/1MY7L987Kc/ajaxStudentSchedule/curr/callback",
        });"""

        match = TIMETABLE_CALLBACK_RE.search(html)

        self.assertIsNotNone(match)
        self.assertEqual(
            match.group("path") if match else "",
            "/student/courseSelect/thisSemesterCurriculum/1MY7L987Kc/"
            "ajaxStudentSchedule/curr/callback",
        )


if __name__ == "__main__":
    unittest.main()
