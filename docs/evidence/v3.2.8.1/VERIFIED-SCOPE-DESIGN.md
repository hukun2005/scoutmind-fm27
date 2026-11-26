# Verified 身份作用域设计（V3.2.8.1 Phase 3）

## 1. 目标

Verified 不能脱离存档身份、游戏构建和内存布局独立存在。本设计把「当时为什么可以 Verified」的全部依据固化为
`VerifiedIdentityScope`，并提供历史记录与当前上下文的生命周期判定；历史记录只追加，不因存档切换而删除。

## 2. 复用的现有机制

| 需要的能力 | 复用实现 | 说明 |
| --- | --- | --- |
| Save Identity 指纹 | `ScoutMind.FMReader.Discovery.SaveIdentityFingerprint` | 沿用 `si:v1:file:<sha256>` 口径，不建第二套 |
| 存档身份解析 | `SaveIdentityResolver` / `SaveIdentityStore` | 已有文件稳定元数据 + 用户确认规则 |
| 会话键 | 回调/诊断提供的 `pid:启动时间:构建` | 只用于会话，不进入身份指纹 |
| 人工确认证据 | `PersonVerificationRequest` 的 reviewer/source/evidence | 缺任意一项都不得 Verified |
| 属性记录身份 | `PlayerRecordFacts` | 用姓名/生日/UID 生成摘要，不保存原始地址 |

## 3. 数据模型

`VerifiedIdentityScope`（仅记录、不写游戏内存）：

- `SaveId`：存档标签（默认等于指纹）。
- `SaveIdentityFingerprint`：Save Identity 复合指纹。
- `SaveSessionKey`：采集会话键；旧会话不得复用历史 Verified。
- `GameBuild`：验证时的构建号。
- `LayoutVersion`：验证时的布局版本。
- `PersonUid`：存档内 UID（0 视为缺失）。
- `DisplayName` / `DateOfBirth`：验证时的人工核对字段。
- `ApprovedAlternativeStrategy`：批准过的替代生日策略（与生日二选一）。
- `AttributeRecordIdentity`：关联属性记录的稳定摘要（SHA-256，不含地址）。
- `VerifiedAt` / `Reviewer` / `ConfirmationSource` / `EvidenceReference`：人工确认证据。

`VerifiedIdentityContext`：当前存档、会话、构建、布局、UID、姓名、生日、属性记录摘要；俱乐部只作审计。

## 4. 状态机

```text
UnverifiedCandidate → StructurallyValid → IdentityMatched → HumanReviewPending → Verified
Verified → Stale                （存档身份变化；历史保留，当前不可用）
Verified → RevalidationRequired （构建/布局/会话/属性记录变化，或字段缺失）
Verified → Conflicted           （生日等关键身份字段互相矛盾）
```

- `Stale` 不等于删除：历史验证与审计记录保留。
- `Stale` / `RevalidationRequired` / `Conflicted` 都使 `CanUseAsVerified = false`。
- 身份连续性 `IdentityContinuity` 与 Verified 有效性分开：姓名变化为 `SamePlayer`，只在证据不足时为 `Unverifiable`，
  生日冲突才为 `DifferentPlayer`。

## 5. 门控变化

`PersonVerificationRequest` 新增：

- `Scope`：历史 Verified 作用域。
- `CurrentSaveIdentityFingerprint`：本次观测到的存档指纹。
- `CurrentSessionKey`：本次会话键。

`PersonVerificationGate` 只有在以下条件全部满足时才返回 `Verified`：

1. 原有人工确认、结构、指针、稳定性、属性记录关联条件全部通过。
2. `Scope.IsComplete`。
3. 当前存档身份存在且与作用域指纹一致。
4. 当前会话存在且与作用域会话一致。
5. 构建、布局、UID、姓名（规范化后）、生日一致；使用替代策略时必须为同一策略。

任一不满足 → `RevalidationRequired`，并记录可追踪原因码。

新增原因码：`verified_scope_missing`、`verified_scope_incomplete`、`current_save_identity_missing`、
`current_session_missing`、`scope_save_identity_mismatch`、`scope_session_mismatch`、
`scope_game_build_mismatch`、`scope_layout_version_mismatch`、`scope_person_uid_mismatch`、
`scope_display_name_mismatch`、`scope_date_of_birth_mismatch`、`scope_alternative_strategy_mismatch`。

审计 JSON 新增 `save_scope` 字段（指纹 / 会话键），不含内存地址。

## 6. 诊断命令

`ScoutMind.FMReader.Diag verify` 新增：

- `--save-identity <fingerprint>`：缺省时输出 `RevalidationRequired`，不会 Mark(Verified)。
- `--save-id <label>`、`--session <key>`：可选覆盖。

真实运行示例（只读）：

```text
verify --name "<球员名>" --human-confirmed --reviewer <id> --source fm27-ui \
       --evidence <文档> --save-identity si:v1:file:<hash>
```

## 7. 未做（本阶段明确不做）

- 不重写 Person Locator / 内存扫描引擎。
- 不建立全内存 UID 索引。
- 不改数据库结构、不新增迁移。
- 不删除任何历史 Verified 审计记录，不把 Stale 改回 Verified。
- 不写游戏内存、不写存档。
