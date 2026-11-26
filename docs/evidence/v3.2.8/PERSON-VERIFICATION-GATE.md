# Phase 5：Mark(Verified) 安全门控（真实运行，只读）

> 运行日期：2026-11-25 · 游戏：FM27 27.1 · 构建 26620374 · 插件 27.1 · 进程 pid 72012
> 证据文件：`person-verify-sample-2026-11-25.json`、`person-verification-audit-2026-11-25.jsonl`

## 1. 目标

避免错误的 Person 对象被正式写入 Canonical Player Identity。缺少任意前置条件时，一律禁止 Mark(Verified)。

本阶段只在 live-reader 内增加最小安全门控：

- 不写内存、不写存档、不修改 DLL、不修改布局文件。
- 不新增可以绕过校验的公共 Verified 接口。
- 没有人工确认时，最高状态保持 HumanReviewPending。

## 2. 前置条件与实现映射

| # | 前置条件 | 实现检查 | 失败原因码 |
| --- | --- | --- | --- |
| 1 | Person Pointer 有效 | `person_pointer_valid` | `person_pointer_invalid` |
| 2 | 对象结构通过验证 | `structure_valid`（候选快照为 StructurallyValid） | `structure_invalid` |
| 3 | 姓名成功读取 | `display_name` 非空 | `name_missing` |
| 4 | 出生日期成功读取或批准替代策略 | `date_of_birth != null` 或 `approved_alternative_strategy` 非空 | `date_of_birth_missing` |
| 5 | 属性记录关联唯一 | 关联状态为 SingleCandidate / VerifiedMatch | `attribute_link_missing`、`multiple_candidates`、`attribute_record_not_found` |
| 6 | 关联字段没有冲突 | `AttributeLink.Conflicts` 为空 | `identity_conflict` |
| 7 | 版本与布局匹配 | 现场检测 Build 等于候选 Build，且布局版本一致 | `layout_version_mismatch` |
| 8 | 多次读取稳定 | 至少 2 次读取，且逐字段一致 | `unstable_reads` |
| 9 | 真实 FM27 人工核对通过 | `--human-confirmed` + reviewer + source + evidence | `human_review_pending`、`human_confirmation_incomplete` |
| 10 | 验收证据完整 | 证据引用非空，审计记录可写出 | `human_confirmation_incomplete` |

## 3. 状态机与优先级

```text
UnverifiedCandidate → StructurallyValid → IdentityMatched → HumanReviewPending → Verified
```

- 拒绝状态：`Rejected`、`Conflicted`、`Unstable`、`UnsupportedBuild`。
- 从 UnverifiedCandidate 不能直接跳到 Verified：只有结构、关联、稳定性、版本和人工确认全部通过，才返回 `Verified`。
- 判定优先级：版本不匹配 → `UnsupportedBuild`；读取不稳定 → `Unstable`；结构/姓名/生日失败 → `Rejected`；无关联 → `StructurallyValid`；多候选或冲突 → `Conflicted`；未人工确认 → `HumanReviewPending`；全部通过 → `Verified`。

## 4. 公共入口加固

`LayoutBase.Mark` 原先可以直接传入 `FieldStatus.Verified`。本阶段增加硬性检查：

- `Verified` 必须使用 `EvidenceKind.GameUiAgreement`，否则抛 `ArgumentException`。
- `Verified` 必须提供非空证据说明，否则抛 `ArgumentException`。
- 默认参数不再可能产生 Verified；字段级 Verified 仍然只能来自游戏界面人工核对。

同时更新了两处测试夹具（EngineResourceTests / StabilityTests）的注册表证据，使其符合新的"必须带证据"规则；生产代码与嵌入注册表未改动。

## 5. 本次真实运行结果

命令：

```text
ScoutMind.FMReader.Diag.exe verify 165 --located 800 --reads 3
```

| 项目 | 值 |
| --- | --- |
| 目标 | Ahmed Rashid |
| 出生日期 | 1997-01-19 |
| UID | 23244142 |
| CA | 89（界面不可见，只作为证据记录） |
| 属性记录关联 | SingleCandidate（姓名 + 生日 + UID，冲突 0） |
| 校准置信度 | 0.50（结构上限） |
| 状态 | **HumanReviewPending** |
| Mark(Verified) | **否** |
| 阻塞原因 | `human_review_pending` |

结论：所有自动可验证条件均满足，但没有用户人工核对确认，因此按门控要求停留在 HumanReviewPending，未执行 Mark(Verified)。

## 6. 审计日志

每条决定都带审计记录，字段包括：

- 操作时间、结果、是否 Mark。
- Person 候选标识、布局版本、游戏构建。
- 球员身份（姓名、出生日期、俱乐部、UID、CA）。
- 属性记录关联状态、置信度、已验证字段。
- 拒绝/阻塞原因码、确认人、确认来源、证据引用。

审计日志不包含 Person 指针、姓名指针或完整内存地址；本次真实运行的审计行已写入 `person-verification-audit-2026-11-25.jsonl`。

## 7. 完成人工验证的方式（本次未执行）

只有在用户在 FM27 界面逐项核对姓名、出生日期、俱乐部等字段后，才允许追加以下参数：

```text
ScoutMind.FMReader.Diag.exe verify <记录序号> --located 800 ^
  --human-confirmed --reviewer <确认人> --source fm27-ui --evidence <证据路径>
```

缺少任意一项，状态仍为 HumanReviewPending。

## 8. 限制

- live-reader 内没有 Canonical Player Identity 持久化存储；本阶段的"Mark(Verified)"是门控决定与审计记录，不会写入数据库，也不会改写布局文件。
- CA 在游戏界面不可见，本次只记录读取值 89，不据此声明 CA 已验证。
- 本次真实运行未做人工核对，也没有尝试用 `--human-confirmed` 伪造确认。
- 本次只验证了 1 名球员；Phase 7 要求至少 2～3 名不同特征的球员人工核对后，才允许对应布局进入 Verified 状态。

## 9. 测试

- ScoutMind.FMReader.Tests：277/277 PASS（新增 15 项门控与入口测试）。
- 覆盖：无人工确认、完整通过、确认信息不完整、多候选、身份冲突、无匹配、不稳定、构建不匹配、姓名/生日缺失、无关联、指针/结构失败、审计脱敏、布局入口加固。
