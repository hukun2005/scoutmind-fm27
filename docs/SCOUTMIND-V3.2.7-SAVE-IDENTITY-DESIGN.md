# ScoutMind V3.2.7 Phase 1 存档身份模型设计

- 状态：设计待审查
- 依赖：`docs/SCOUTMIND-V3.2.7-PHASE-0-AUDIT.md`
- 原则：证据优先、缺证据即 UNKNOWN、禁止臆造 FM27 内存布局、第三优先级证据不得单独认证

---

## 1. 目标与非目标

### 1.1 目标

1. 定义 `SaveIdentity / SaveEvidence / SaveSession / SaveIdentityConflict` 的统一模型。
2. 定义“什么证据能证明是同一个存档”，以及游戏重启后如何重新关联。
3. 定义存档切换、会话失效、身份冲突时的判定与阻断规则。
4. 为 Reader、Agent、Backend 提供同一套身份语义与 JSON 形状。
5. 本版本 `snapshot_eligible` 永远为 `false`，不开启自动快照。

### 1.2 非目标

- 不实现前端页面（Phase 11）。
- 不实现真实双存档 A/B 验收（Phase 10，且需要用户提供真实材料）。
- 不重写已通过真实验证的日期引用链。
- 不修改历史 migration。

---

## 2. 术语（三个概念必须分开）

| 概念 | 含义 | 何时变化 |
| --- | --- | --- |
| **Save Identity** | 一个存档的长期身份，重启、保存、读档后保持不变 | 只在换存档/新建存档时变化 |
| **Save File Version** | 某个存档文件的一次具体版本（路径 + 稳定文件句柄元数据 + 修改时间 + 大小） | 每次保存可能变化 |
| **Save File Content Hash** | 某次文件内容的 SHA-256 | 每次保存内容变化即变化 |

> 约束：**Content Hash 变化不得导致 Save Identity 变化**；Content Hash 只能作为证据，不能单独定义身份。

---

## 3. 真实可访问证据清单（代码审计结论）

| 证据类型 | 当前是否可获取 | 来源 | 优先级 | 说明 |
| --- | --- | --- | --- | --- |
| `GAME_INTERNAL_SAVE_ID` | **UNKNOWN（未定位）** | FM27 内存 | 1 | 仓库内没有任何已实现读取；Phase 2 只允许“探测并报告 UNKNOWN”，禁止硬编码偏移 |
| `WORLD_ID` | **UNKNOWN（未定位）** | FM27 内存 | 2 | 同上 |
| `SAVE_FILE_METADATA` | 可获取（Phase 2 实现） | Windows 文件系统 | 2 | 路径、大小、创建/修改时间、卷序列号 + FileId |
| `SAVE_FILE_HASH` | 可获取（Phase 2 实现） | 文件内容 | 2 | 仅作版本/证据，不作长期身份 |
| `CAREER_METADATA` | 可获取 | 扫描载荷 | 3 | 人类经理名、执教俱乐部、`user_club_uid` |
| `GAME_SESSION_METADATA` | 可获取 | 进程/插件 | 3 | `PID`、`ProcessStartTime`、`ModuleBase`、build、plugin |
| `USER_CONFIRMED` | 可获取（Phase 11 入口） | 用户显式确认 | 1* | 必须绑定稳定文件元数据，不能只绑名字 |

\* `USER_CONFIRMED` 可升级为 VERIFIED，但必须同时存在至少一项稳定文件元数据或第一优先级证据。

结论：**当前没有任何第一优先级证据可用**。因此：

- Reader 默认只能给出 `DISCOVERED` 或 `CANDIDATE`；
- 只有“稳定文件元数据 + 用户确认”或后续发现第一优先级证据，才允许 `VERIFIED`；
- 无法确认时，安全门保持 `BLOCKED`，这是正确行为，不是缺陷。

---

## 4. 实体模型

所有实体通过 `fm_save_id` 外键挂到既有 `fm_saves`，不新建“存档主表”。

### 4.1 SaveIdentity

```text
id                      PK
fm_save_id              FK -> fm_saves.id, nullable（发现阶段可空）
identity_version        int, default 1
identity_status         enum: UNKNOWN|DISCOVERED|CANDIDATE|VERIFIED|CONFLICT|INVALIDATED
identity_confidence     enum: NONE|LOW|MEDIUM|HIGH|VERIFIED
identity_fingerprint    varchar(128), 复合指纹
identity_kind           enum: INTERNAL_SAVE_ID|WORLD_ID|SAVE_FILE|USER_CONFIRMED|UNRESOLVED
game_build              varchar(64)
plugin_version          varchar(32)
first_seen_at           datetime
last_seen_at            datetime
created_at              datetime
updated_at              datetime
```

唯一约束：`(fm_save_id, identity_version, identity_fingerprint)`；
`identity_fingerprint` 全局唯一性不设置（不同用户可能存在相同文件指纹）。

### 4.2 SaveEvidence

```text
id                      PK
save_identity_id        FK -> save_identities.id
fm_save_id              FK -> fm_saves.id
evidence_type           enum（见 §4.5）
evidence_source         enum: MEMORY|FILE|SCANNER|PROCESS|USER|BACKEND
evidence_hash           varchar(128)
evidence_version        varchar(64)
confidence              enum: NONE|LOW|MEDIUM|HIGH|VERIFIED
observed_at             datetime
session_id              FK -> save_sessions.id, nullable
metadata_json           text（仅存可公开诊断字段，禁止存原始内存转储）
```

### 4.3 SaveSession

```text
id                      PK
fm_save_id              FK -> fm_saves.id, nullable
save_identity_id        FK -> save_identities.id, nullable
process_id              int
process_start_time      datetime
session_key             varchar(128)   -- PID:StartTime:Build，仅用于会话，不作身份
session_started_at      datetime
session_ended_at        datetime
game_build              varchar(64)
plugin_version          varchar(32)
session_status          enum: CREATED|DISCOVERING|VERIFIED|SWITCHING|INVALIDATED|CLOSED
last_verified_at        datetime
invalidated_reason      varchar(64)
```

唯一约束：`session_key` 唯一。

### 4.4 SaveIdentityConflict

```text
id                      PK
fm_save_id              FK -> fm_saves.id, nullable
current_identity_id     FK -> save_identities.id
conflicting_identity_id FK -> save_identities.id, nullable
conflict_reason         enum: EVIDENCE_MISMATCH|FILE_SWITCH|SESSION_REUSE|USER_CONTRADICTION|UNKNOWN
conflict_evidence_json  text
detected_at             datetime
status                  enum: OPEN|RESOLVED|IGNORED
resolution              enum: NULL|KEEP_CURRENT|SWITCH_TO_OTHER|NEW_IDENTITY|MANUAL
resolved_by             varchar(64)
resolved_at             datetime
notes                   text
```

### 4.5 证据类型枚举

```text
GAME_INTERNAL_SAVE_ID
WORLD_ID
SAVE_FILE_METADATA
SAVE_FILE_HASH
SAVE_FILE_HEADER
CAREER_METADATA
GAME_SESSION_METADATA
USER_CONFIRMED
LEGACY_UNVERIFIED
```

`LEGACY_UNVERIFIED` 用于历史 `fm_saves` 的回填标记，置信度固定 `NONE`。

---

## 5. 指纹与身份键

### 5.1 复合指纹

```text
identity_fingerprint = "si:v1:" + SHA256(canonical_strong_evidence)
```

`canonical_strong_evidence` 只允许包含：

1. `GAME_INTERNAL_SAVE_ID`（若可用）
2. `WORLD_ID`（若可用）
3. `SAVE_FILE_METADATA` 的稳定部分：卷序列号 + FileId（不是路径、不是 mtime）

第三优先级证据（经理/俱乐部/日期/进程）**不进入指纹**，只进入置信度评估与冲突检测。

若没有任何强证据：`identity_fingerprint = "si:v1:unresolved:<build>"`，`identity_status` 最高只到 `CANDIDATE`。

### 5.2 版本化

- 指纹算法变更必须提升 `identity_version`，旧指纹保留，不覆盖。
- `identity_kind` 记录本次指纹的主要来源，便于解释。

### 5.3 身份解释

每次解析必须返回：

```json
{
  "status": "candidate",
  "identity_fingerprint": "si:v1:...",
  "identity_kind": "SAVE_FILE",
  "confidence": "medium",
  "evidence_count": 2,
  "missing_evidence": ["GAME_INTERNAL_SAVE_ID", "WORLD_ID"],
  "conflicts": [],
  "explanation": ["检测到 FM27 进程", "存档文件句柄稳定", "缺少游戏内唯一 ID"]
}
```

禁止只返回一个裸 ID。

---

## 6. 状态机与判定规则

### 6.1 SaveIdentity 状态机

```text
UNKNOWN
  └─(发现进程/文件)→ DISCOVERED
        └─(复合证据一致)→ CANDIDATE
              ├─(强证据 或 稳定文件元数据+用户确认)→ VERIFIED
              ├─(证据互相矛盾)→ CONFLICT
              └─(进程结束但身份保留)→ CANDIDATE（不降级为 UNKNOWN）
VERIFIED
  ├─(强证据变化/文件身份变化)→ INVALIDATED → CANDIDATE
  └─(冲突证据)→ CONFLICT
```

硬性规则：

1. `DISCOVERED` 不得直接变 `VERIFIED`。
2. `UNKNOWN` 不得被任何默认值提升。
3. `CONFLICT` 时自动采集立即暂停，禁止自动二选一。
4. `INVALIDATED` 的 Session 不得再被写入。

### 6.2 Confidence 对应关系

| status | confidence |
| --- | --- |
| UNKNOWN | NONE |
| DISCOVERED | LOW |
| CANDIDATE | MEDIUM |
| VERIFIED | HIGH 或 VERIFIED |
| CONFLICT | 保持冲突前等级，但 `snapshot_eligible=false` |
| INVALIDATED | NONE |

### 6.3 `snapshot_eligible`

```text
snapshot_eligible =
    enable_automatic_snapshot                      -- 本版本恒 false
    && identity_status == VERIFIED
    && session_status == VERIFIED
    && session.game_build == identity.game_build
    && date_confidence == RESTART_VERIFIED
    && no OPEN conflict
    && no switch in progress
```

本版本第一项恒 `false`，所以结果恒 `false`。

---

## 7. 会话生命周期与重启重连

```text
CREATED → DISCOVERING → VERIFIED → CLOSED
                └→ SWITCHING → INVALIDATED
```

- `session_key = PID:ProcessStartTime:Build`，只用于会话，**绝不作为存档身份**。
- 同一进程可加载多个存档：每次检测到身份变化，关闭旧 Session（`INVALIDATED`），新建 Session。
- 游戏重启：旧 Session 变 `CLOSED`；新 Session 通过强证据指纹匹配既有 `SaveIdentity`。
- 若重启后只有第三优先级证据匹配：允许关联到既有身份，但状态降为 `CANDIDATE` 并阻断自动采集。

---

## 8. 存档切换检测（Phase 3 的设计约束）

- 每轮采样生成 `evidence_digest`；连续 `N=2`（可配置）次不同且稳定，才判定 `SWITCH_CONFIRMED`。
- `SWITCH_SUSPECTED` 立即暂停采集，不写库。
- 切换确认后：旧 Session `INVALIDATED`，旧任务必须携带 `session_id` 并被拒绝写入。
- 防抖：同一 `evidence_digest` 的短暂抖动（如读内存失败）不产生切换事件，只记诊断。

---

## 9. 冲突处理

出现以下任一情况生成 `SaveIdentityConflict`：

- 强证据指纹与当前身份不一致；
- 同一 Session 内文件身份变化但无正常切换记录；
- 用户确认的存档与实际证据不符；
- 旧任务携带的 `session_id` 已失效却仍尝试写入。

冲突时：

1. 立即 `BLOCKED`；
2. 不自动切换、不自动合并；
3. 等待人工 `resolution`；
4. 解决后才允许建立新身份/新会话。

---

## 10. 与现有代码/表的映射

| 现有对象 | 处理方式 |
| --- | --- |
| `fm_saves` | 保留，作为身份外键锚点；新增 `identity_status` 摘要列可选（Phase 4 决定），不删旧列 |
| `capture_runs` | 增加 `save_identity_id` / `save_session_id`（可空，Phase 4 迁移），旧行保持 `NULL` |
| `import_jobs` | 增加 `save_identity_id` / `save_session_id`（可空），旧行保持 `NULL` |
| `player_instances` 等 | 不改结构，继续用 `fm_save_id` 隔离 |
| `DateVerificationStore` | 复用其原子 JSON 持久化模式；`SaveKey` 字段由新身份填充 |
| `SnapshotSafetyGate` | 保留 7 参数旧签名；新增 `SaveIdentityStatus` 输入与重载 |
| Agent `config.SaveName` | 降级为显示名，不参与身份判断 |

---

## 11. Reader `save-identity` 协议草案

```json
{
  "status": "candidate",
  "identity": {
    "fingerprint": "si:v1:...",
    "kind": "SAVE_FILE",
    "version": 1,
    "confidence": "medium"
  },
  "save_id": null,
  "session": {
    "session_key": "12345:2026-11-24T10:00:00Z:26620374",
    "status": "VERIFIED",
    "game_build": "26620374",
    "plugin_version": "27.1.0+2505117"
  },
  "evidence": [
    {"type": "SAVE_FILE_METADATA", "source": "FILE", "confidence": "medium", "hash": "..."},
    {"type": "CAREER_METADATA", "source": "SCANNER", "confidence": "low", "hash": "..."}
  ],
  "missing_evidence": ["GAME_INTERNAL_SAVE_ID", "WORLD_ID"],
  "conflicts": [],
  "explanation": ["..."],
  "snapshot_eligible": false
}
```

兼容性：

- 新增命令，不修改 `world-date` 的现有字段；
- `process/session/date_summary/snapshot` 结构保持原样；
- 所有新字段只增不改。

---

## 12. 测试设计（Phase 9 实现）

Reader：

- 无证据 → UNKNOWN
- 只有 career metadata → CANDIDATE（不得 VERIFIED）
- 文件元数据稳定 + 内容哈希变化 → 同一身份
- FileId 变化 + 无切换记录 → CONFLICT
- 重启后重新解析 → 关联既有身份
- 切换抖动防抖

Backend：

- 身份/会话归属校验
- 旧 Session 任务写入被拒
- 冲突时 BLOCKED
- 迁移 SQLite/PG 往返

Agent：

- 身份 UNKNOWN/CONFLICT/SWITCHING 都不扫描不导入
- 采集期间切换 → 丢弃本次结果，不投递

---

## 13. 待真实验证项（不得在文档中写成已通过）

| 项 | 状态 |
| --- | --- |
| FM27 是否存在可读的 GAME_INTERNAL_SAVE_ID | **UNKNOWN** |
| 存档文件是否可稳定定位到当前运行存档 | **待 Phase 2 实测** |
| 重启后强证据是否稳定 | **待 Phase 10 实测** |
| 真实双存档 A/B | **NOT_RUN**（当前只有单存档环境） |

---

## 14. 阶段门

Phase 1 完成条件：

- 本设计文档提交；
- 明确“无强证据即 UNKNOWN、第三优先级不得单独认证”；
- 明确 `snapshot_eligible` 恒 false；
- 明确新表/迁移只增不改。

满足后可进入 Phase 2（Reader 身份指纹与解析器），并在实现前先写失败测试。
