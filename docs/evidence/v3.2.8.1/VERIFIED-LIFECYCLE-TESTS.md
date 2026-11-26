# Verified 生命周期与门控测试（V3.2.8.1 Phase 3–5）

执行方式：`dotnet run --project live-reader/tests/ScoutMind.FMReader.Tests`
本文件只记录**本次真实执行**的自动化测试；真实 FM27 场景见 `CROSS-SAVE-ACCEPTANCE.md`。

## 1. 作用域与跨存档隔离（VerifiedIdentityScopeTests，17 项）

| # | 用例 | 断言要点 | 结果 |
| --- | --- | --- | --- |
| 1 | 同一存档/构建/布局/会话为 Valid | `Valid` + `CanUseAsVerified` | PASS |
| 2 | 切换存档后为 Stale 且历史记录保留 | `Stale` + `save_identity_mismatch` | PASS |
| 3 | A→B→A 重新确认后才恢复 | A 有效 → B Stale → 同会话回 A 有效 → 新会话回 A 需重读 | PASS |
| 4 | 不同存档同 UID 不自动认定为同一球员 | `Stale` | PASS |
| 5 | 构建变化需要重新确认 | `RevalidationRequired` + `game_build_changed` | PASS |
| 6 | 布局变化需要重新确认 | `layout_version_changed` | PASS |
| 7 | 旧会话指针不得继续使用 | `session_changed` + 不可用 | PASS |
| 8 | 生日冲突为 Conflicted | `Conflicted` + `DifferentPlayer` | PASS |
| 9 | UID 变化不得自动合并 | `RevalidationRequired` + `Unverifiable` | PASS |
| 10 | 姓名变化不判定为换人 | `RevalidationRequired` + `SamePlayer` + `display_name_changed` | PASS |
| 11 | 关联记录变化需要重新确认 | `attribute_record_changed` | PASS |
| 12 | 转会不使身份失效 | `Valid` | PASS |
| 13 | 成为自由球员不使身份失效 | `Valid` | PASS |
| 14 | 退役不使身份失效 | `Valid` | PASS |
| 15 | 俱乐部变化不参与身份判定 | 状态一致 | PASS |
| 16 | 作用域不完整必须重新确认 | `verified_scope_incomplete` | PASS |
| 17 | 当前身份字段缺失必须重读 | `person_facts_missing` | PASS |

说明：第 12–15 项是**模拟场景**，用于证明「俱乐部不是身份字段」。真实 FM27 中的转会/自由球员/退役
生命周期没有执行，标记 `NOT_RUN`。

## 2. 门控拒绝路径（PersonVerificationGateTests，新增 5 项 + 既有 16 项）

新增：

| 用例 | 期望 | 结果 |
| --- | --- | --- |
| 缺少存档作用域不得 Verified | `RevalidationRequired` / `verified_scope_missing` | PASS |
| 存档指纹不一致不得 Verified | `scope_save_identity_mismatch` | PASS |
| 旧会话不得沿用 Verified | `scope_session_mismatch` | PASS |
| 缺少当前存档身份不得 Verified | `current_save_identity_missing` | PASS |
| 作用域构建号不一致不得 Verified | `scope_game_build_mismatch` | PASS |

既有（本次回归仍通过）：无人工确认、人工确认信息不完整、多候选、身份冲突、无属性记录匹配、读取不稳定、
构建不匹配、重复确认幂等、旧版本候选重新验证、姓名缺失、生日缺失、无属性记录关联、指针无效、结构失败、
审计脱敏、布局 Mark 需要界面证据。

## 3. 「不存在绕过入口」的审计结论

检查范围：C# 诊断 CLI、`PersonVerificationGate`、布局字段校验、Backend 身份服务与 API。

| 入口 | 结论 |
| --- | --- |
| `ScoutMind.FMReader.Diag verify` | 只能输出决定；缺作用域/人工确认/唯一候选时必然拒绝；不持久化 Verified |
| `PersonVerificationGate.Evaluate` | 唯一产生 `PersonVerificationState.Verified` 的位置 |
| `LayoutBase.Mark` | 只负责**字段级** Verified，要求 `GameUiAgreement` + 证据；与球员身份 Verified 无关 |
| Backend `save_identity.verify_identity` | 要求指纹一致 + 第二优先级证据 + 人工 actor；客户端自称 verified 不被信任 |
| 测试工具 | 只做断言，不写生产状态 |

未发现：仅凭姓名匹配、无人工确认、无存档身份、布局版本不匹配、旧指针、多候选取第一条、失败自动放宽条件的入口。

## 4. 失败路径的可追踪性

每个拒绝结果都带原因码，并写入 `PersonVerificationAuditEntry`（含 `outcome`、`rejection_reasons`、
`save_scope`）。审计记录不含内存地址（回归用例 `AuditLineIsCompleteAndSanitized` 持续校验）。
