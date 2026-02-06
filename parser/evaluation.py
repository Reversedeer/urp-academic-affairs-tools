"""教学评估"""

import re
import logging

from client.session import AsyncJWSSession
from config import DRY_RUN, DEFAULT_CHOICE

BASE_USL = "https://jws.qgxy.cn/student/teachingEvaluation"
SUBMIT_URL = f"{BASE_USL}/teachingEvaluation/assessment"
EVA_INDEX_URL = f"{BASE_USL}/evaluation/index"
EVA_PAGE_URL = f"{BASE_USL}/evaluationPage"

TOKEN_RE = re.compile(r'name="tokenValue"\s+value="([^"]+)"', re.I)
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

log = logging.getLogger(__name__)


class TeachingEvaluationClient:
    @staticmethod
    def extract_token(html: str) -> str:
        """获取toeknValue"""
        m = TOKEN_RE.search(html or "")
        if not m:
            raise RuntimeError("tokenValue not found")
        return m.group(1)

    def open_evaluation_page(self, task: dict, token: str) -> dict[str, str]:
        return {
            "evaluatedPeople": task["evaluatedPeople"],
            "evaluatedPeopleNumber": task["id"]["evaluatedPeople"],
            "questionnaireCode": task["id"]["questionnaireCoding"],
            "questionnaireName": task["questionnaire"]["questionnaireName"],
            "coureSequenceNumber": task["id"]["coureSequenceNumber"],
            "evaluationContentNumber": task["id"]["evaluationContentNumber"],
            "evaluationContentContent": task["evaluationContent"],
            "tokenValue": token,
        }

    def build_assessment_payload(
        self, task: dict, token: str, answers: dict[str, str]
    ) -> dict[str, str]:
        """构造assessment payload"""
        payload: dict[str, str] = {
            "optType": "submit",
            "tokenValue": token,
            "questionnaireCode": task["id"]["questionnaireCoding"],
            "evaluationContent": task["id"]["evaluationContentNumber"],
            "evaluatedPeopleNumber": task["id"]["evaluatedPeople"],
            "count": "",
        }
        for qid, choice in answers.items():
            payload[qid] = SCORE_MAP_A[choice]
        payload["zgpj"] = "老师教学认真课程收获较大"
        return payload

    async def final_confirm(self, tasks, notFinishedNum) -> None:
        """最终确认"""
        log.info(f"🚨 共 {notFinishedNum} 门课程，一旦提交无法修改。\n")
        log.info("你将评教以下课程：")
        for t in tasks:
            log.info(f" - {t['evaluatedPeople']} ｜ {t['evaluationContent']}")

        print("\n如果你确认继续，请完整输入下面这句话：")
        print(f"⌈{CONFIRM_PHRASE}⌋")

        user_input: str = input("\n请输入确认语句：").strip()
        if user_input != CONFIRM_PHRASE:
            log.error("\n❌ 验证错误，已中止提交。")
            raise SystemExit(1)
        log.info("\n✅ 验证通过，开始提交评教。\n")

    async def run(self, jws: AsyncJWSSession, data: dict) -> None:
        """获取评教任务并执行评教"""
        tasks_list: list[dict] = data.get("data", [])
        notFinishedNum: str = data["notFinishedNum"]
        log.info(f"共有 {notFinishedNum} 门课程待评教。\n")
        if notFinishedNum == 0:
            log.info("✅ 无待评教任务，退出评教流程")
        pending = [t for t in tasks_list if t.get("isEvaluated") == "否"]
        if not pending:
            return

        answers = {
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

        for task in pending:
            html = await jws.request_text("GET", EVA_INDEX_URL)
            token = self.extract_token(html)

            page_form = self.open_evaluation_page(task, token)
            await jws.request_text(
                "POST", EVA_PAGE_URL, data=page_form, allow_redirects=True
            )

            payload = self.build_assessment_payload(task, token, answers)
            if not DRY_RUN:
                await self.final_confirm(tasks_list, notFinishedNum)
                await jws.request_text(
                    "POST", SUBMIT_URL, data=payload, allow_redirects=True
                )
