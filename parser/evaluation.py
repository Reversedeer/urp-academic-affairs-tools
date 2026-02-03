import time
import re
import requests

BASE_USL = "https://jws.qgxy.cn/student/teachingEvaluation"
SUBMIT_URL = f"{BASE_USL}/teachingEvaluation/assessment"
EVA_INDEX_URL = f"{BASE_USL}/evaluation/index"
EVA_PAGE_URL = f"{BASE_USL}/evaluationPage"

DRY_RUN = True  # True = 不提交 ,False = 真提交
SLEEP = 0.3
CONFIRM_PHRASE = "我确认提交评教不可撤销"

SCORE_MAP_A: dict[str, str] = {
    "A": "10_1",
    "B": "10_0.8",
    "C": "10_0.6",
    "D": "10_0.4",
    "E": "10_0.2",
}

SCORE_MAP_B: dict[str, str] = {
    "A": "10_1",
    "B": "10_0.6",
    "C": "10_0.5",
    "D": "10_0.2",
    "E": "10_0",
}
DEFAULT_CHOICE = "A"  # 默认满分


class TeachingEvaluationClient:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_12_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/73.0.3683.75 Safari/537.36"
        }

    def open_evaluation_page(self, task, token) -> dict[str, str]:
        payload: dict[str, str] = {
            "evaluatedPeople": task["evaluatedPeople"],
            "evaluatedPeopleNumber": task["id"]["evaluatedPeople"],
            "questionnaireCode": task["id"]["questionnaireCoding"],
            "questionnaireName": task["questionnaire"]["questionnaireName"],
            "coureSequenceNumber": task["id"]["coureSequenceNumber"],
            "evaluationContentNumber": task["id"]["evaluationContentNumber"],
            "evaluationContentContent": task["evaluationContent"],
            "tokenValue": token,
        }
        return payload

    @staticmethod
    def extract_token(html: str) -> str:
        """获取toeknValue"""
        m: re.Match[str] | None = re.search(
            r'name="tokenValue"\s+value="([^"]+)"', html
        )
        if not m:
            raise RuntimeError("❌tokenValue not found")
        return m.group(1)

    def build_assessment_payload(self, task, token, count, answers) -> dict[str, str]:
        """构造 assessment payload"""
        payload: dict[str, str] = {
            "optType": "submit",
            "tokenValue": token,
            "questionnaireCode": task["id"]["questionnaireCoding"],
            "evaluationContent": task["id"]["evaluationContentNumber"],
            "evaluatedPeopleNumber": task["id"]["evaluatedPeople"],
            "count": count,
        }

        for qid, choice in answers.items():
            payload[qid] = SCORE_MAP_A[choice]

        payload["zgpj"] = "老师教学认真课程收获较大"

        return payload

    def submit(self, payload) -> None:
        """提交评教"""
        if DRY_RUN:
            print("\n[submit] assessment payload：")
            for k, v in payload.items():
                print(f"{k}: {v}")
            return
        try:
            r = self.session.post(
                SUBMIT_URL,
                data=payload,
            )
            r.raise_for_status()
        except requests.RequestException as e:
            print(f"❌[submit]提交评教失败：{e}")

    def final_confirm(self, tasks, notFinishedNum) -> None:
        """最终确认"""
        print(f"[submit]共 {notFinishedNum} 门课程，一旦提交无法修改。\n")
        print("[submit]你将评教以下课程：")
        for t in tasks:
            print(f" - {t['evaluatedPeople']} ｜ {t['evaluationContent']}")

        print("\n[submit]如果你确认继续，请完整输入下面这句话：")
        print(f"⌈{CONFIRM_PHRASE}⌋")

        user_input: str = input("\n[submit]请输入确认语句：").strip()
        if user_input != CONFIRM_PHRASE:
            print("\n❌ 验证错误，已中止提交。")
            raise SystemExit(1)
        print("\n✅ 验证通过，开始提交评教。\n")

    def run(self, data: dict) -> None:
        """获取评教任务并执行评教"""
        tasks_list: dict = data["data"]
        notFinishedNum: str = data["notFinishedNum"]
        print(f"✨[submit]待评教数量: {notFinishedNum}")

        if notFinishedNum == 0:
            print("✅[submit]无待评教任务，退出评教流程。")
            return

        if not DRY_RUN:
            self.final_confirm(tasks_list, notFinishedNum)
        else:
            print("🚨[submit]当前为模拟模式，不会提交")

        for idx, task in enumerate(tasks_list, 1):
            print(
                f"✏️ [{idx}/{len(tasks_list)}] {task['evaluatedPeople']} - {task['evaluationContent']}"
            )
            try:
                r = self.session.get(
                    EVA_INDEX_URL,
                    headers=self.headers,
                )
            except Exception as e:
                print(f"❌[submit]获取评教页面失败：{e}")
                continue

            try:
                token: str = self.extract_token(r.text)
                print("✨[submit]tokenValue:", token)
            except RuntimeError:
                print("❌[submit]无法提取 tokenValue")
                continue

            payload_data: dict[str, str] = self.open_evaluation_page(task, token)
            try:
                self.session.post(
                    EVA_PAGE_URL,
                    data=payload_data,
                    headers=self.headers,
                    allow_redirects=True,
                )
            except Exception as e:
                print(f"❌[submit]访问评教页面失败：{e}")
                continue
            count = ""
            answers: dict[str, str] = {
                "0000000014": DEFAULT_CHOICE,
                "0000000016": DEFAULT_CHOICE,
                "0000000018": DEFAULT_CHOICE,
                "0000000015": DEFAULT_CHOICE,
                "0000000017": DEFAULT_CHOICE,
                "0000000044": DEFAULT_CHOICE,
                "0000000048": DEFAULT_CHOICE,
                "0000000053": DEFAULT_CHOICE,
                "0000000042": DEFAULT_CHOICE,
                "0000000049": DEFAULT_CHOICE,
            }

            payload: dict[str, str] = self.build_assessment_payload(
                task, token, count, answers
            )
            self.submit(payload)

            time.sleep(SLEEP)
