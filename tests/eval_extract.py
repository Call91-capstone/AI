"""추출 정답률 측정 (CLAUDE.md 13절 3단계).

    python tests/eval_extract.py              # 표 출력 + tests/results/extract_latest.md 저장
    python tests/eval_extract.py --fails      # 틀린 사례까지 출력
    python tests/eval_extract.py --llm        # LLM_BASE_URL 설정 시 LLM 포함 측정

데이터: tests/data/extract_cases.jsonl (가짜 데이터)
  expect 키 규칙
  - 일반 필드: 값이 같아야 정답 (null = 추출되면 안 됨)
  - medications / surgery_history: 키워드 리스트. 각 키워드가 결과에 포함돼야 정답,
    [] = 비어 있어야 정답, ["없음"] = 정확히 ["없음"]
  - onset_min_ago: 기준 시각(19:25) 대비 발생 몇 분 전인지 (±1분 허용)
  - extra.<키>: extra 값. "present" = 값이 있기만 하면 정답, 문자열은 포함 여부
  - warning: true = 이상값 경고가 하나 이상 있어야 정답
나중에 같은 대본을 녹음해 STT 결과 텍스트로 돌리면 소음 조건별 비교가 된다 (--text-file 확장 예정).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from llm.extract import extract  # noqa: E402

NOW = datetime(2026, 11, 9, 19, 25, tzinfo=timezone(timedelta(hours=9)))
DATA = os.path.join(ROOT, "tests", "data", "extract_cases.jsonl")
HOLDOUT = os.path.join(ROOT, "tests", "data", "extract_holdout.jsonl")
OUT = os.path.join(ROOT, "tests", "results", "extract_latest.md")


def load_cases(path: str = DATA) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _actual(result, key: str):
    p = result.patient
    if key == "warning":
        return bool(result.warnings)
    if key == "onset_min_ago":
        if not p.onset_time:
            return None
        t = datetime.fromisoformat(p.onset_time)
        return round((NOW - t).total_seconds() / 60)
    if key.startswith("extra."):
        return p.extra.get(key[6:])
    return getattr(p, key)


def _match(key: str, expected, actual) -> bool:
    if key in ("medications", "surgery_history"):
        actual = actual or []
        if expected == [] or expected == ["없음"]:
            return actual == expected
        joined = " ".join(actual)
        return all(k in joined for k in expected)
    if key == "onset_min_ago":
        return actual is not None and abs(actual - expected) <= 1
    if key.startswith("extra.") and expected == "present":
        return actual not in (None, "")
    if key.startswith("extra.") and isinstance(expected, str):
        return isinstance(actual, str) and expected in actual
    return actual == expected


def evaluate(use_llm: bool = False, cases: list[dict] | None = None):
    cases = cases or load_cases()
    per_field = defaultdict(lambda: [0, 0])   # key → [정답, 전체]
    per_type = defaultdict(lambda: [0, 0])
    fails = []
    case_perfect = 0
    for c in cases:
        r = extract(c["text"], use_llm=use_llm, now=NOW)
        ok_all = True
        for key, exp in c["expect"].items():
            act = _actual(r, key)
            ok = _match(key, exp, act)
            field = key.split(".")[0] if not key.startswith("extra.") else key
            per_field[field][0] += ok
            per_field[field][1] += 1
            per_type[c["type"]][0] += ok
            per_type[c["type"]][1] += 1
            if not ok:
                ok_all = False
                fails.append((c["id"], key, exp, act, c["text"]))
        case_perfect += ok_all
    return cases, per_field, per_type, fails, case_perfect


def _pct(a, b):
    return f"{a / b * 100:5.1f}%" if b else "  -  "


def report(cases, per_field, per_type, fails, case_perfect, show_fails=False) -> str:
    total_ok = sum(v[0] for v in per_field.values())
    total = sum(v[1] for v in per_field.values())
    lines = [f"# 추출 정답률 ({len(cases)}개 대본, 기준 시각 {NOW:%H:%M})", "",
             f"- 전체 항목 정답률: **{_pct(total_ok, total).strip()}** ({total_ok}/{total})",
             f"- 모든 항목을 맞힌 대본: {case_perfect}/{len(cases)}", "",
             "## 항목별", "", "| 항목 | 정답률 | 정답/전체 |", "|---|---|---|"]
    for k in sorted(per_field, key=lambda k: per_field[k][0] / per_field[k][1]):
        a, b = per_field[k]
        lines.append(f"| {k} | {_pct(a, b)} | {a}/{b} |")
    lines += ["", "## 상황별", "", "| 상황 | 정답률 | 정답/전체 |", "|---|---|---|"]
    for k, (a, b) in per_type.items():
        lines.append(f"| {k} | {_pct(a, b)} | {a}/{b} |")
    lines += ["", f"## 틀린 항목 ({len(fails)}개)", ""]
    for cid, key, exp, act, text in fails:
        lines.append(f"- `{cid}` **{key}** 정답 `{exp}` / 결과 `{act}` — {text}")
    md = "\n".join(lines) + "\n"
    if not show_fails:
        md_print = md.split("## 틀린 항목")[0] + f"## 틀린 항목 {len(fails)}개 (--fails 로 보기)\n"
        print(md_print)
    else:
        print(md)
    return md


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fails", action="store_true")
    ap.add_argument("--llm", action="store_true")
    ap.add_argument("--holdout", action="store_true",
                    help="검증용 대본(규칙 수정에 쓰지 않은 것)으로 측정")
    args = ap.parse_args()
    if not args.llm:
        os.environ.pop("LLM_BASE_URL", None)
    data = HOLDOUT if args.holdout else DATA
    md = report(*evaluate(use_llm=args.llm, cases=load_cases(data)), show_fails=args.fails)
    out = OUT.replace("latest", "holdout") if args.holdout else OUT
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(md)


if __name__ == "__main__":
    main()
