# parser/timetable.py


def parse_timetable(raw_json: dict):
    """
    把教务原始 JSON 转成统一结构列表
    """
    result = []

    # 你的真实数据：xkxx 是 dict
    for course in raw_json["xkxx"].values():
        course_name = course["courseName"]
        teacher = course["attendClassTeacher"].replace("*", "").strip()
        credit = course["unit"]

        for tp in course["timeAndPlaceList"]:
            result.append(
                {
                    "course": course_name,
                    "teacher": teacher,
                    "credit": credit,
                    "day": tp["classDay"],  # 1-7
                    "start": tp["classSessions"],  # 第几节
                    "length": tp["continuingSession"],  # 连上几节
                    "weeks": tp["weekDescription"],
                    "building": tp["teachingBuildingName"],
                    "room": tp["classroomName"],
                }
            )

    return result
