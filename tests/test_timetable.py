"""课表解析测试"""

from __future__ import annotations

import unittest

from urp_academic_affairs_tools.parser.timetable import parse_timetable


class TimetableParserTests(unittest.TestCase):
    def test_expands_each_course_time_and_place_record(self) -> None:
        data = {
            "xkxx": [
                {
                    "course": {
                        "courseName": "数据结构",
                        "attendClassTeacher": "张老师",
                        "id": {"coureSequenceNumber": "03"},
                        "timeAndPlaceList": [
                            {
                                "classDay": "1",
                                "classSessions": "1",
                                "continuingSession": "2",
                                "weekDescription": "1-16周",
                                "teachingBuildingName": "教学楼A",
                            },
                            {
                                "classDay": 3,
                                "classSessions": 5,
                                "continuingSession": 2,
                                "weekDescription": "2-16周(双)",
                                "teachingBuildingName": "教学楼B",
                            },
                        ],
                    },
                },
            ],
        }

        entries = parse_timetable(data)

        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["course_name"], "数据结构")
        self.assertEqual(entries[0]["course_sequence_number"], "03")
        self.assertEqual(entries[0]["teacher"], "张老师")
        self.assertEqual(entries[0]["day"], 1)
        self.assertEqual(entries[0]["start_session"], 1)
        self.assertEqual(entries[0]["duration"], 2)
        self.assertEqual(entries[0]["week_desc"], "1-16周")
        self.assertEqual(entries[0]["building"], "教学楼A")
        self.assertEqual(entries[1]["day"], 3)
        self.assertEqual(entries[1]["start_session"], 5)
        self.assertEqual(entries[1]["week_desc"], "2-16周(双)")


if __name__ == "__main__":
    unittest.main()
