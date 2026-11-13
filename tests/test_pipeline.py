"""표준 라이브러리 unittest — GPU·외부 패키지 없이 실행.

    cd AI && python -m unittest discover tests -v
"""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.pop("LLM_BASE_URL", None)          # 규칙 기반만 테스트
os.environ["ALLOWED_PHONES"] = "sim:"

from call import Dispatcher, SimulatedChannel  # noqa: E402
from llm.classify import classify  # noqa: E402
from llm.extract import extract  # noqa: E402
from llm.korean_num import normalize_numbers  # noqa: E402
from llm.script import OPENING, build_script  # noqa: E402
from schema import Hospital  # noqa: E402

NOW = datetime(2026, 11, 9, 19, 25, tzinfo=timezone(timedelta(hours=9)))


class TestKoreanNumber(unittest.TestCase):
    def test_numbers(self):
        self.assertEqual(normalize_numbers("구십에 육십"), "90에 60")
        self.assertEqual(normalize_numbers("백이십에 팔십"), "120에 80")
        self.assertEqual(normalize_numbers("일흔 살"), "70 살")
        self.assertEqual(normalize_numbers("이 환자"), "이 환자")   # 일반 단어는 그대로


class TestExtract(unittest.TestCase):
    def test_cardiac_arrest(self):
        r = extract("70대 남자 의식 없고 CPR 5분째, 혈압 구십에 육십, 와파린 복용, 심장 스텐트 시술", now=NOW)
        p = r.patient
        self.assertEqual((p.age, p.sex, p.consciousness), (70, "M", "무반응"))
        self.assertEqual((p.cpr, p.cpr_minutes, p.blood_pressure), (True, 5, "90/60"))
        self.assertIn("와파린", p.medications)
        self.assertTrue(any("스텐트" in s for s in p.surgery_history))
        self.assertEqual((p.emergency_type, p.severity), ("심정지", "최중증"))
        self.assertEqual(p.onset_time, "2026-11-09T19:20+09:00")   # CPR 5분 전으로 추정
        self.assertIn("witnessed", r.missing)                       # 심정지 추가 항목 되묻기

    def test_stroke_and_followup(self):
        r = extract("65세 여자 오른쪽 편마비, 말이 어눌함, 30분 전 발생", now=NOW)
        self.assertEqual(r.patient.emergency_type, "뇌졸중")
        self.assertIn("medications", r.missing)
        r2 = extract("복용약은 없고 수술력도 없어요, 의식은 명료", base=r.patient, now=NOW)
        self.assertEqual(r2.patient.medications, ["없음"])
        self.assertEqual(r2.patient.consciousness, "명료")
        self.assertEqual(r2.patient.emergency_type, "뇌졸중")      # 기존 분류 유지
        self.assertNotIn("medications", r2.missing)

    def test_correction_and_abbrev(self):
        r = extract("60대, 아니 80대 남자 GCS 8 새츄 88 맥박 120 교통사고", now=NOW)
        p = r.patient
        self.assertEqual((p.age, p.gcs, p.spo2, p.pulse), (80, 8, 88, 120))
        self.assertEqual(p.emergency_type, "중증외상")

    def test_sanity(self):
        r = extract("50세 남자 흉통 혈압 900에 60", now=NOW)
        self.assertEqual(r.patient.emergency_type, "급성심근경색")
        self.assertTrue(any("혈압" in w for w in r.warnings))


class TestScriptAndClassify(unittest.TestCase):
    def test_script_opening(self):
        p = extract("70대 남자 의식 없고 CPR 5분째", now=NOW).patient
        s = build_script(p, eta_min=8)
        self.assertTrue(s.startswith(OPENING))
        self.assertIn("최중증 심정지", s[:60])                      # 첫 몇 초에 중증도
        self.assertIn("8분", s)

    def test_classify(self):
        cases = {
            "네 보내주세요": ("수락", None),
            "지금 병상이 없어서 어렵습니다": ("거절", "병상 없음"),
            "신경외과 당직 선생님이 안 계세요, 죄송합니다": ("거절", "의사 부재"),
            "잠시만요, 선생님께 여쭤보고 다시 연락드릴게요": ("의사 확인 중", None),
            "": ("무응답", None),
            "수용 가능한 병상이 없어요": ("거절", "병상 없음"),
        }
        for text, (status, reason) in cases.items():
            r = classify(text, use_llm=False)
            self.assertEqual((r.status, r.reject_reason), (status, reason), text)


def _hospitals(n):
    return [Hospital(f"H{i:03d}", f"병원{i}", f"sim:{i}", eta_min=5 + i) for i in range(1, n + 1)]


class TestDispatcher(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.p = extract("70대 남자 의식 없고 CPR 5분째", now=NOW).patient   # 최중증
        self.d = Dispatcher("T1", self.p, _hospitals(7), SimulatedChannel(),
                            on_event=lambda i, r: self.events.append(r))

    def statuses(self):
        return [c.status for c in self.d.calls]

    def test_batches_and_accept(self):
        d = self.d
        d.start(0)
        self.assertEqual(self.statuses()[:4], ["발신 중"] * 3 + ["대기"])
        d.on_response("H001", "병상이 없어요", 10)
        d.on_response("H002", "선생님께 확인해보고 연락드릴게요", 12)
        d.tick(30)                                                   # 30초 → +2곳
        self.assertEqual(self.statuses()[3:6], ["발신 중", "발신 중", "대기"])
        d.on_response("H004", "네 받을게요 오세요", 35)
        self.assertEqual(d.confirmed, "H004")
        self.assertEqual(self.statuses(), ["거절", "취소", "취소", "수락", "취소", "취소", "취소"])
        self.assertEqual(d.on_response("H003", "가능합니다", 40).status, "취소")   # 늦은 응답 무시

    def test_no_answer_triggers_next(self):
        d = self.d
        d.start(0)
        d.tick(25)                                                   # 25초엔 그대로
        self.assertEqual(self.statuses().count("발신 중"), 3)
        # 3곳 모두 거절 → 진행 중 통화 0 → 시간과 무관하게 즉시 다음 묶음
        for hid in ("H001", "H002", "H003"):
            d.on_response(hid, "어렵습니다", 26)
        self.assertEqual(self.statuses()[3:5], ["발신 중", "발신 중"])

    def test_direct_call(self):
        d = self.d
        d.start(0)
        d.direct_call("H001", 5)
        self.assertEqual(d.calls[0].status, "직접 전화")
        inbox = d.channel.pop("H001")
        self.assertEqual(inbox[-1]["type"], "hang_up")                 # AI 통화 즉시 중단
        d.record_direct_result("H001", "수락", now=20)
        self.assertEqual(d.confirmed, "H001")

    def test_simultaneous_accept_picks_nearest(self):
        d = self.d
        d.start(0)
        d.on_responses([("H003", "네 오세요"), ("H002", "받을게요")], 10)
        self.assertEqual(d.confirmed, "H002")                        # eta 7 < 8

    def test_mild_sequential(self):
        p = extract("30세 여자 의식 명료 복통", now=NOW).patient
        d = Dispatcher("T2", p, _hospitals(3), SimulatedChannel())
        d.start(0)
        self.assertEqual([c.status for c in d.calls], ["발신 중", "대기", "대기"])
        d.tick(40)                                                    # 무응답 → 다음
        self.assertEqual([c.status for c in d.calls], ["무응답", "발신 중", "대기"])

    def test_real_number_blocked(self):
        d = Dispatcher("T3", self.p, [Hospital("X", "실제병원", "02-1234-5678")], SimulatedChannel())
        with self.assertRaises(PermissionError):
            d.start(0)


if __name__ == "__main__":
    unittest.main()
