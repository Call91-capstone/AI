"""회귀 테스트: 규칙을 고치다가 정답률이 떨어지면 실패한다."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.pop("LLM_BASE_URL", None)

import eval_classify  # noqa: E402
from eval_extract import HOLDOUT, evaluate, load_cases  # noqa: E402

MIN_ACCURACY = 0.99


def _acc(per_field):
    return sum(v[0] for v in per_field.values()) / sum(v[1] for v in per_field.values())


def _msg(fails):
    return "\n".join(f"{c} {k}: 정답 {e} / 결과 {a}" for c, k, e, a, _ in fails)


class TestExtractAccuracy(unittest.TestCase):
    def test_dev_set_accuracy(self):
        _, per_field, _, fails, _ = evaluate(use_llm=False)
        self.assertGreaterEqual(_acc(per_field), MIN_ACCURACY, _msg(fails))

    def test_holdout_accuracy(self):
        _, per_field, _, fails, _ = evaluate(use_llm=False, cases=load_cases(HOLDOUT))
        self.assertGreaterEqual(_acc(per_field), MIN_ACCURACY, _msg(fails))


class TestClassifyAccuracy(unittest.TestCase):
    def test_classify_accuracy(self):
        res = eval_classify.evaluate(use_llm=False)
        self.assertGreaterEqual(res["status_ok"] / len(res["cases"]), MIN_ACCURACY, _msg(res["fails"]))

    def test_no_false_accept(self):
        # 수락이 아닌 응답을 수락으로 판단하면 잘못된 병원으로 이송된다 → 0건이어야 함
        self.assertEqual(eval_classify.evaluate(use_llm=False)["false_accept"], 0)


if __name__ == "__main__":
    unittest.main()
