"""회귀 테스트: 규칙을 고치다가 개발용 대본 정답률이 떨어지면 실패한다."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.pop("LLM_BASE_URL", None)

from eval_extract import evaluate  # noqa: E402

MIN_ACCURACY = 0.98


class TestExtractAccuracy(unittest.TestCase):
    def test_dev_set_accuracy(self):
        _, per_field, _, fails, _ = evaluate(use_llm=False)
        ok = sum(v[0] for v in per_field.values())
        total = sum(v[1] for v in per_field.values())
        msg = "\n".join(f"{c} {k}: 정답 {e} / 결과 {a}" for c, k, e, a, _ in fails)
        self.assertGreaterEqual(ok / total, MIN_ACCURACY, msg)


if __name__ == "__main__":
    unittest.main()
