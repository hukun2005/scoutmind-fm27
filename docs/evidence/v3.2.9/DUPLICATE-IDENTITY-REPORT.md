# V3.2.9 重复身份与同名冲突报告

## 1. 范围

本报告区分三类问题：

1. **同存档重复 UID**：一个 UID 对应多个球员实体。
2. **同名冲突**：规范化姓名相同，但身份字段不足以确认同一人。
3. **跨存档相同 UID**：只作证据，不构成同一身份。

## 2. 处理规则（已实现）

| 场景 | 状态 | 是否自动合并 | 审计 |
| --- | --- | --- | --- |
| 同存档重复 UID | `Duplicate` | 否 | `player_identity_review_items` + `identity_conflicts`（既有） |
| 同名不同生日 | `Conflicted` | 否 | 审核条目 `same_name_different_birth_date` |
| 同名同生日不同 UID | `Conflicted` | 否 | 审核条目 `same_name_same_birth_date` |
| 同名且生日未知 | `Conflicted` | 否 | 审核条目 `same_name_unknown_birth_date` |
| 跨存档相同 UID | `CrossSaveCandidate` / `CrossSaveConflicted` | 否 | `cross_save_identity_candidates` |

- 同名条目的幂等键按「参与者集合」生成，双方各自扫描不会产生两条。
- 已有人工决定的条目不会被后续扫描覆盖（有测试 `test_rescan_does_not_overwrite_human_decision`）。

## 3. 自动化验证

`backend/tests/test_v329_reconciliation.py`：

| 用例 | 结果 |
| --- | --- |
| 同名不同生日 → Conflicted + 1 条审核 | PASS |
| 重复 UID → Duplicate + `uid_duplicate` 审核 | PASS |
| 扫描只产生 Candidate，不产生 Verified | PASS |
| 两名球员实体都保留，未自动合并 | PASS |

`backend/tests/test_v329_uid_scope.py`：

| 用例 | 结果 |
| --- | --- |
| 同存档重复 UID 可检出 | PASS |
| 不同存档相同 UID 不计为重复 | PASS |

## 4. 真实数据（Save A，2026-11-26）

| 指标 | 结果 | 说明 |
| --- | --- | --- |
| 存档内重复 UID | **0** | 44,869 实例，44,869 个唯一 UID |
| 同名冲突实例 | 2,674 | 状态 `Conflicted` |
| 待人工审核条目 | 813 | `PendingHumanReview` |
| 自动合并 | 0 | 两名及以上同名球员实体全部保留 |

抽样 UID 审计（800 定位 / 200 抽样）另见 9 个重复 UID 组（18 条记录），那是**候选记录层**的口径；导入并按实例去重后为 0，两者不可混用。

## 5. 结论

- 冲突识别与保留策略：**PASS（自动化 + 真实 Save A）**。
- 真实跨存档同名/同 UID 判定：**NOT_RUN**，不写 PASS。
