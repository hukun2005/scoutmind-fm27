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

| 步骤 | 结果 | 证据 |
| --- | --- | --- |
| 真实 FM27 进程存在 | 已观测（pid 72012） | 只读进程检查 |
| 在 A 中完成全库扫描 | **PASS** | 44,886 实例；42,194 Valid / 2,692 Conflicted；813 待审 |
| A 基线摘要 | `b2439d0c…` | 观测 + 关联 + 审核的行级摘要 |
| 切换到 B（真实） | **PASS** | B 为 18,614 球员 / 25 俱乐部，A 为 44,887 / 44 |
| B 建立自己的记录 | **PASS** | 17,922 匹配 / 692 冲突 / 301 待审；Verified 0 |
| B 扫描后复核 A | **PASS** | A 摘要仍为 `b2439d0c…`，逐字节一致 |
| 相同 UID 是否跨存档自动合并 | **PASS（未合并）** | 两存档共有 13,977 个 UID；跨存档共用 Canonical 球员 **0** |
| 返回 A（真实） | **PASS** | 44,144 球员 / 44 俱乐部，与 B 的 25 俱乐部明显不同 |
| 返回 A 后复核历史 | **PASS** | A 摘要仍为 `b2439d0c…`，记录未变、未被 B 污染 |
| 旧指针 / 会话失效 | 自动化 PASS | V3.2.8.1 `VerifiedIdentityScopeTests`、门控拒绝码 |
| Verified 级别的真实 A/B/A | NOT_RUN | 需人工在 A、B 内各核对一名球员并 Mark(Verified) |

说明：A 两次扫描球员数 44,887 → 44,144，是游戏时间推进导致的内容变化；`scan_id` 是内容哈希，因此 A1 `fmreader-633e130d…` 与 A2 `fmreader-4934b655…` 不同，这不代表存档身份改变。俱乐部数（44 vs 25）与数据规模是区分存档的直接证据。

## 5. 结论

- 跨存档候选生成与隔离：**PASS（自动化）**。
- 真实 FM27 A/B/A（数据层）：**PASS**（保存档/切 B/切回 A 三次真实切换）。
- 相同 UID 跨存档：真实观测到 13,977 个，全部未自动合并。
- Verified 级别真实 A/B/A：**NOT_RUN**，不得写 PASS。
