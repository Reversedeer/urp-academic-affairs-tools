"""main.py"""

from client import JWSSession
from client import get_this_semester_timetable
from parser import parse_timetable
from export import export_timetable_excel
from config import USERNAME, PASSWORD


def main():
    jws = JWSSession()
    jws.login(USERNAME, PASSWORD)

    raw = get_this_semester_timetable(jws)
    courses = parse_timetable(raw)

    export_timetable_excel(courses, "本学期课表.xlsx")


if __name__ == "__main__":
    main()
