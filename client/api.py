"""api"""


def get_this_semester_timetable(jws_session):
    """
    本学期课表（callback JSON）
    """
    r = jws_session.get("/student/courseSelect/thisSemesterCurriculum/callback")
    r.raise_for_status()
    return r.json()
