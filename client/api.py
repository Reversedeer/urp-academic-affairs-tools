"""api"""


def get_this_semester_timetable(jws_session) -> dict:
    """
    本学期课表(callback JSON)
    """
    r = jws_session.get("/student/courseSelect/thisSemesterCurriculum/callback")
    r.raise_for_status()
    return r.json()


def fetch_tasks(jws_session) -> dict:
    r = jws_session.get("/student/teachingEvaluation/teachingEvaluation/search")
    r.raise_for_status()
    return r.json()
