"""入口文件 main"""

from client import JWSSession, get_this_semester_timetable, fetch_tasks
from parser import parse_timetable, TeachingEvaluationClient
from export import export_timetable_excel
from config import USERNAME, PASSWORD


def menu():
    print("\n========================")
    print("欢迎使用教务系统工具")
    print("1. 抢课(开发中)")
    print("2. 导出课表")
    print("3. 教学评估")
    print("0. 退出")
    print("========================\n")


def handle_view_timetable(jws: JWSSession):
    print("\n✨ 正在查询课表...")
    raw = get_this_semester_timetable(jws)
    courses = parse_timetable(raw)

    if not courses:
        print("❌[WARNNING] 未查询到任何课程")
        return

    print(f"共找到 {len(courses)} 门课程，正在导出 Excel...")
    export_timetable_excel(courses, "本学期课表.xlsx")
    print("✅课表已导出：本学期课表.xlsx")


def handle_teaching_evaluation(jws: JWSSession):
    print("⚠️ ⌈教学评估提醒⌋")
    print("评教一旦提交将无法修改，请确认你已理解风险。\n")

    client = TeachingEvaluationClient()
    data: dict = fetch_tasks(jws)
    try:
        client.run(data)
    except KeyboardInterrupt:
        print("\n❌[ERROR] 用户中断评教流程")
    except Exception as e:
        print(f"\n❌[ERROR] 评教过程中发生错误：{e}")


def main():
    jws = JWSSession()
    jws.login(USERNAME, PASSWORD)

    while True:
        menu()
        choice = input("请输入选项：").strip()

        if choice == "1":
            print("\n抢课功能尚未实现，请耐心等待。")

        elif choice == "2":
            handle_view_timetable(jws)

        elif choice == "3":
            handle_teaching_evaluation(jws)

        elif choice == "0":
            print("程序已退出。")
            break

        else:
            print("无效选项，请重新输入。")


if __name__ == "__main__":
    main()
