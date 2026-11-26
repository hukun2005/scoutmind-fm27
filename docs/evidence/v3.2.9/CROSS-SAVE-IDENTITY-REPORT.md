# V3.2.9 跨存档身份关联报告

## 1. 原则

- 存档内 UID 不是全球永久身份。
- 跨存档只生成候选；相同 UID 作为证据字段 `uid_equal` 保存，不构成匹配依据。
- 未确认的候选不写 Canonical 关联；确认后才写 `ConfirmedByHuman`。
- Save A 的任何状态不得覆盖或污染 Save B。

## 2. 候选规则（已实现）

`find_cross_save_candidates(save_id, other_save_id)`：

| 条件 | 状态 | 分值 |
| --- | --- | --- |
| 规范化姓名相同 + 生日相同 | `CrossSaveCandidate` | 0.9 |
| 姓名相同 + 至少一方生日缺失 | `CrossSavePendingReview` | 0.5 |
| 姓名相同 + 生日不同 | `CrossSaveConflicted` | 0.3 |
| 相同 UID + 生日不同 | `CrossSaveConflicted`（原因 `same_uid_different_person`） | 0.3 |
| 姓名不同（即使 UID 相同） | 不生成候选 | — |

候选按 `(fm_save_id, other_save_id, subject_player_id, other_player_id)` 唯一，重复生成幂等。

## 3. 存档隔离（自动化验证）

`backend/tests/test_v329_cross_save_api.py`：

| 用例 | 结果 |
| --- | --- |
| 同名同生日生成候选（0.9） | PASS |
| 同名不同生日生成冲突候选（0.3） | PASS |
| 不同存档相同 UID 且姓名不同 → 不生成候选、不计重复 | PASS |
| 标记 Save A 关联 Stale 后 Save B 关联不受影响 | PASS |
| 跨存档确认后两个存档各自写 `ConfirmedByHuman` | PASS |
| 重复审核同一候选 → 409，不覆盖历史 | PASS |
| 查询其他存档的球员详情 → 404 | PASS |

## 4. 真实 A/B/A

任务书 Phase 6 要求 Save A → Save B → Save A 的真实验证。

| 步骤 | 结果 | 原因 |
| --- | --- | --- |
| 真实 FM27 进程存在 | 已观测（pid 72012） | 只读进程检查 |
| 在 A 中建立验证记录 | NOT_RUN | 本阶段未执行真实存档扫描 |
| 切换到 B | NOT_RUN | 需要人工在游戏中切换存档 |
| B 建立自己的记录 | NOT_RUN | 同上 |
| 返回 A 并复核历史 | NOT_RUN | 同上 |
| 旧指针是否失效 | 由 V3.2.8.1 自动化测试覆盖 | 见 v3.2.8.1 证据 |

## 5. 结论

- 跨存档候选生成与隔离：**PASS（自动化）**。
- 真实 FM27 A/B/A：**NOT_RUN**，不得写 PASS。
