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

## 5. 真实 Verified 级别 A/B/A（2026-11-26）

流程与实测：

| # | 步骤 | 结果 | 说明 |
| --- | --- | --- | --- |
| 1 | A 中定位并人工核对 | PASS | 同名唯一；`HumanReviewPending`，`mark_verified=false` |
| 2 | A 中 Mark | PASS | `Verified`，绑定指纹 `b887415a…` |
| 3 | 切到 B 后读取当前指纹 | **FAIL** | 仍返回 A 的 `b887415a…`：确认状态优先于"当前加载的存档" |
| 4 | 用独立 state + 显式存档文件确认 B | PASS | 得到 B 指纹 `d24cfab8…` |
| 5 | B 中该球员不存在 | PASS（拒绝） | 按设计拒绝，不产生 Verified |
| 6 | B 中另一球员人工核对并 Mark | PASS | `Verified`，绑定 B 指纹 `d24cfab8…` |
| 7 | B 加载时用 A 旧指纹 Mark B 球员 | **FAIL（P1）** | 返回 `Verified`、`mark_verified=true`、无告警 |
| 8 | 切回 A 后的指纹 | **变化** | 重新保存后为 `9718fb6a…`，与 A1 `b887415a…` 不同 |
| 9 | 历史审计是否保留 | PASS | 4 条记录完整，未删除、未改写 |

### 5.1 P1 缺陷

`ScoutMind.FMReader.Diag verify` 完全信任调用方传入的 `--save-identity`，不校验它是否等于当前加载存档。
同时 LiveReader 的确认状态固定在最后一次确认的文件上，切档后仍返回旧指纹。两者组合导致：

- 旧存档指纹可以为另一存档的球员产生 `Verified`；
- 同一生涯每次保存都会改变文件指纹，旧 Verified 无法自动判定为 Stale。

这不是数据层关联问题（数据层 A/B/A 仍 PASS），而是 Verified 门控的输入可信问题。

### 5.2 建议修复（未实施）

1. `verify` 内部解析当前存档身份，不接受与当前文件不一致的指纹；
2. LiveReader 检测到存档切换时把状态置为 `Conflict`，强制重新确认；
3. 增加自动化测试：旧指纹 + 新存档 → 必须 `Stale`/拒绝。

## 6. 结论

- 跨存档候选生成与隔离：**PASS（自动化）**。
- 真实 FM27 A/B/A（数据层）：**PASS**。
- 相同 UID 跨存档：真实观测到 13,977 个，全部未自动合并。
- 真实 Verified 级别 A/B/A：**FAIL（P1）** —— 旧存档指纹可生成 Verified。
- 不得写 PASS，也不得把该 P1 降级为提示。
