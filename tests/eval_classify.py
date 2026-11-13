"""간호사 응답 분류 정답률 측정 (CLAUDE.md 13절 7단계).

    python tests/eval_classify.py           # 표 출력 + tests/results/classify_latest.md 저장
    python tests/eval_classify.py --llm     # LLM_BASE_URL 설정 시 LLM 포함 측정

데이터: tests/data/classify_cases.jsonl (가짜 응답)
  status: 수락 / 거절 / 의사 확인 중 / 무응답, reason: 거절 사유 (거절일 때만)
가장 위험한 오류는 '수락이 아닌데 수락으로 판단'(잘못된 병원으로 이송)이라 따로 센다.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from llm.classify import classify  # noqa: E402

DATA = os.path.join(ROOT, "tests", "data", "classify_cases.jsonl")
OUT = os.path.join(ROOT, "tests", "results", "classify_latest.md")
ACCEPT = "수락"


def load_cases(path: str = DATA) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def evaluate(use_llm: bool = False, cases: list[dict] | None = None) -> dict:
    cases = cases or load_cases()
    per_status = defaultdict(lambda: [0, 0])
    reason_ok = reason_total = 0
    false_accept = 0
    fails = []
    for c in cases:
        r = classify(c["text"], use_llm=use_llm)
        ok = r.status == c["status"]
        per_status[c["status"]][0] += ok
        per_status[c["status"]][1] += 1
        if r.status == ACCEPT and c["status"] != ACCEPT:
            false_accept += 1
        if not ok:
            fails.append((c["id"], "status", c["status"], r.status, c["text"]))
        if "reason" in c and ok:
            reason_total += 1
            if r.reject_reason == c["reason"]:
                reason_ok += 1
            else:
                fails.append((c["id"], "reason", c["reason"], r.reject_reason, c["text"]))
    status_ok = sum(v[0] for v in per_status.values())
    return {"cases": cases, "per_status": per_status, "status_ok": status_ok,
            "reason_ok": reason_ok, "reason_total": reason_total,
            "false_accept": false_accept, "fails": fails}


def report(res: dict) -> str:
    n = len(res["cases"])
    pct = lambda a, b: f"{a / b * 100:.1f}%" if b else "-"  # noqa: E731
    lines = [f"# 간호사 응답 분류 정답률 ({n}개 응답)", "",
             f"- 상태 정답률: **{pct(res['status_ok'], n)}** ({res['status_ok']}/{n})",
             f"- 거절 사유 정답률: {pct(res['reason_ok'], res['reason_total'])} "
             f"({res['reason_ok']}/{res['reason_total']})",
             f"- 수락 오판(가장 위험): **{res['false_accept']}건**", "",
             "| 정답 상태 | 정답률 | 정답/전체 |", "|---|---|---|"]
    for k, (a, b) in res["per_status"].items():
        lines.append(f"| {k} | {pct(a, b)} | {a}/{b} |")
    lines += ["", f"## 틀린 항목 ({len(res['fails'])}개)", ""]
    for cid, key, exp, act, text in res["fails"]:
        lines.append(f"- `{cid}` **{key}** 정답 `{exp}` / 결과 `{act}` — {text!r}")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true")
    args = ap.parse_args()
    if not args.llm:
        os.environ.pop("LLM_BASE_URL", None)
    md = report(evaluate(use_llm=args.llm))
    print(md)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(md)


if __name__ == "__main__":
    main()
