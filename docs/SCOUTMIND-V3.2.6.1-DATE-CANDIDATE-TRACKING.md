# ScoutMind V3.2.6.1 日期候选关联与可信度设计

## 1. 目标

把日期从“一次扫描选一个最新值”升级为“可追踪、可解释、可验证的候选体系”：

- 每个候选都有**逻辑身份**，不依赖会变化的绝对地址；
- 所有命中都出现在诊断报告中，要么保留、要么带原因排除；
- 只有人工界面日期验证一致，才允许升级可信度；
- 只有跨多个独立游戏进程都验证通过，才允许 `restart_verified`；
- 自动快照只在所有硬性条件满足时才允许。

## 2. 数据模型

核心类型位于 `live-reader/ScoutMind.FMReader/Discovery/`：

| 类型 | 作用 |
| --- | --- |
| `DateCandidateObservation` | 单次采集的结果（地址、原始值、参考日期、结构指纹、稳定性） |
| `DateCandidateDiagnostics` | 报告中的候选详情（含类别、排除原因、置信度、首次/最近发现、读取次数） |
| `TrackedCandidateState` | 跨读取/跨进程持久化的逻辑候选状态 |
| `DateVerificationState` | 构建号、存档身份、最近会话、证据日志、候选列表 |
| `DateCandidateTracker` | 追踪、分类、选择与可信度状态机 |
| `SnapshotSafetyGate` | 自动快照硬性条件 |
| `DateVerificationStore` | 状态 JSON 的原子持久化 |

## 3. 逻辑身份

### 3.1 结构指纹（版本 2）

```text
fingerprint = SHA256(
    moduleKind
    || fingerprintVersion
    || mask(bytes[date - 0x44, date))        // 结构头
    || mask(bytes[date + 0x08, date + 0x58)) // 尾部结构
)[0..8]
```

- **不包含日期值**（`+0x00`）与**参考日期**（`+0x04`），因此日期推进不会改变身份；
- 尾部从 `+0x08` 开始、长度 `0x50`：覆盖哨兵/零字段之后的标量（对象 ID 等），
  同时尽量留在候选自身记录内，避免把相邻记录的日期算进指纹；
- `mask()` 把“指针形态且目标可读”的 8 字节替换为固定标记 `\0PTR8\0\0\0`：
  - 8 字节对齐、低 32 位 ≥ `0x10000`、位于用户态地址范围；
  - 目标地址可读（`IMemorySource.IsReadable`）；
  - 按相对日期字段的 4 字节步长扫描，与候选在堆上的绝对对齐无关。
- 同时把“结构头/尾部是否可读”写入摘要，结构损坏时指纹必然变化；
- 逻辑签名 = `moduleKind + ":v2:" + fingerprint`，例如 `heap:v2:70792ff53e1ed6e6`。

> 版本 2 的必要性来自真实 FM27 数据：v1 直接哈希原始字节，包含堆指针，
> 游戏重启后指纹必然漂移（`heap:b16a56d8d23b4675` → `heap:ef7f58074afe9022`），
> 会产生“唯一候选”的假阳性。详见 `SCOUTMIND-V3.2.6.1-RESTART-VALIDATION.md`。
>
> 真实数据也暴露了本方案的边界：同一天有 10 条同构日期记录共享签名
> （只有日期/参考日期不同），因此结构指纹不足以唯一确定世界日期对象，
> 追踪器会保守地判定 `ambiguous`，自动快照保持 `BLOCKED`。

### 3.2 绝对地址

绝对地址只作为“当前会话诊断值”保存在 `last_address`，不参与身份判断。
游戏重启后地址变化，只要结构指纹一致，仍能重新关联。

## 4. 候选分类

支持 `CURRENT_WORLD_DATE`、`MATCH_DATE`、`TRANSFER_DATE`、`NEWS_DATE`、`CALENDAR_DATE`、`HISTORY_DATE`、`UNKNOWN_DATE`。

- 分类证据来自对象分类器提示（`DateObjectHint`）；
- **没有对象提示时一律 `UNKNOWN_DATE`**，绝不按日期大小猜类别；
- 与人工确认日期的关系只用于**排除**（`FUTURE_EVENT`）或**证据不足**，不用于反推类别。

排除原因（每一条都写入报告）：

`INVALID_DATE`、`OUT_OF_SUPPORTED_RANGE`、`MATCH_OBJECT`、`TRANSFER_OBJECT`、`CALENDAR_OBJECT`、
`NEWS_OBJECT`、`FUTURE_EVENT`、`UNSTABLE_VALUE`、`UNRESOLVED_REFERENCE`、`DUPLICATE_SIGNATURE`、`INSUFFICIENT_EVIDENCE`。

## 5. 可信度状态机

```text
UNAVAILABLE
   └─(发现结构命中)→ DISCOVERED
        └─(最新且唯一、复读稳定)→ HEURISTIC
             └─(界面日期不匹配/倒退)→ VERIFICATION_PENDING
                  └─(界面日期唯一匹配)→ SESSION_VERIFIED
                       └─(≥3 个独立进程会话均验证通过)→ RESTART_VERIFIED
```

规则：

- 任何疑义（歧义、复读不一致、日期不匹配、回退、构建号变化）**只降级，不升级**；
- 同一天重复读取不会重复提升，只累计 `read_count` 与 `consecutive_consistent_reads`；
- `date_changed` 会记录证据，但不会自动提升等级；
- 构建号变化时，旧构建的验证会话全部作废；
- 从 `SESSION_VERIFIED` 到 `RESTART_VERIFIED` 需要 **3 个独立进程会话**（首次 + 至少两次真实重启）。

## 6. 自动快照安全门

只有以下条件全部满足才 `ENABLED`：

| 条件 | 当前实现 |
| --- | --- |
| 有可用日期 | 依赖真实读取 |
| 候选唯一、无歧义 | 由追踪器给出 |
| 可信度 = `restart_verified` | 由状态机给出 |
| 进程会话有效 | 由进程 PID/启动时间/构建号构成 |
| 存档身份有效 | **尚未实现，恒为 false** |
| Reader 构建受支持 | `VersionGate.AllowScan` |
| 日期来源是已验证的内存候选 | 选中候选的逻辑签名存在 |

因此当前默认结果必然是 `BLOCKED`，原因会逐条输出。这符合“未验证不得自动快照”的要求。

## 7. 持久化

- 默认路径：`%LOCALAPPDATA%\ScoutMind\date-verification.json`
- 可用 `world-date --diagnostics --state <路径>` 覆盖；
- 写入采用临时文件 + 原子替换；
- 文件缺失或损坏时安全降级为空状态，不把脏数据当作证据；
- 证据日志最多保留 200 条，候选状态最多保留 1024 条。

## 8. CLI 诊断字段

`world-date --diagnostics --json` 输出包含：

```text
status / confidence
process{pid, process_start_time, module_base, build, plugin_version, session_key}
session{session_id, game_version, save_key}
date_summary{selected_date, candidate_count, verified_candidate_count, rejected_count}
candidates[] / rejected_candidates[]（地址、原始字节、日期、参考日期、指纹、类别、排除原因、置信度、读取次数、观测日期）
selection_reason / verification_evidence / limitations
snapshot{status, allowed, reasons}
next_action / diagnostics
```

`candidates + rejected_candidates` 的数量恒等于签名命中数，便于审计“没有静默丢弃”。
