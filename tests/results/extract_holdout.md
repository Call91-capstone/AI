# 추출 정답률 (16개 대본, 기준 시각 19:25)

- 전체 항목 정답률: **95.5%** (85/89)
- 모든 항목을 맞힌 대본: 12/16

## 항목별

| 항목 | 정답률 | 정답/전체 |
|---|---|---|
| extra.defibrillation |   0.0% | 0/1 |
| extra.injury_site |   0.0% | 0/1 |
| cpr_minutes |  66.7% | 2/3 |
| emergency_type |  93.3% | 14/15 |
| age | 100.0% | 16/16 |
| sex | 100.0% | 16/16 |
| cpr | 100.0% | 3/3 |
| extra.witnessed | 100.0% | 1/1 |
| consciousness | 100.0% | 5/5 |
| extra.bleeding | 100.0% | 1/1 |
| blood_pressure | 100.0% | 6/6 |
| extra.mechanism | 100.0% | 1/1 |
| onset_min_ago | 100.0% | 3/3 |
| extra.ecg_abnormal | 100.0% | 1/1 |
| extra.paralysis | 100.0% | 2/2 |
| extra.last_known_well | 100.0% | 2/2 |
| pulse | 100.0% | 3/3 |
| spo2 | 100.0% | 1/1 |
| gcs | 100.0% | 1/1 |
| medications | 100.0% | 2/2 |
| surgery_history | 100.0% | 2/2 |
| extra.rosc | 100.0% | 1/1 |
| severity | 100.0% | 2/2 |

## 상황별

| 상황 | 정답률 | 정답/전체 |
|---|---|---|
| 심정지 |  88.9% | 16/18 |
| 중증외상 |  94.1% | 16/17 |
| 급성심근경색 | 100.0% | 20/20 |
| 뇌졸중 |  94.1% | 16/17 |
| 기타 | 100.0% | 17/17 |

## 틀린 항목 (4개)

- `H01` **extra.defibrillation** 정답 `False` / 결과 `True` — 84세 남성 심정지 추정, 보호자 목격, 심폐소생술 6분 경과, 제세동 미시행
- `H03` **extra.injury_site** 정답 `다리` / 결과 `None` — 39세 남자 오토바이 단독 사고, 의식 명료, 우측 다리 개방성 골절, 출혈 많음
- `H12` **emergency_type** 정답 `뇌졸중` / 결과 `기타` — 50대 여성 의식 없음 GCS 5 혈압 210에 120, 마지막 정상 2시간 전
- `H14` **cpr_minutes** 정답 `4` / 결과 `None` — 환자 남자 63세 CPR 중, 시간은 4분 정도, 자발순환 회복 안 됨
