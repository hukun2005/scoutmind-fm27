# ScoutMind V3.2.6.1 跨重启日期验证

- 验证日期：2026-11-24（真实 FM27，两次独立进程会话）
- 结论：**真实跨重启验证已执行，结果为 BLOCKED（未达到 `restart_verified`）**

> 本文件记录真实执行结果。两次会话之间完全退出并重启了游戏；
> 因为结构身份无法唯一确定世界日期对象，状态机在进入“会话计数”之前就判为 `ambiguous`，
> 因此没有伪造任何 `restart_verified`。

## 1. 要证明什么

1. 游戏重启后，同一存档的同一个逻辑日期对象仍能被重新定位；
2. 绝对地址变化不影响识别，逻辑身份（模块 + 结构指纹）保持一致；
3. 每次重启后都能用人工界面日期完成验证；
4. 达到 3 个独立进程会话后才允许 `restart_verified`；
5. 即使 `restart_verified`，只要存档身份未知，自动快照仍为 `BLOCKED`。

## 2. 真实执行记录

| 会话 | PID | 进程启动时间 | 构建号 | `status` | 选中日期 | 逻辑签名 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 106216 | 2026-11-24T13:52:44Z | 26620374 | `session_verified`（v1 指纹） | 2026-11-06 | `heap:b16a56d8d23b4675` |
| 2（v1 重扫） | 118504 | 2026-11-24T13:57:21Z | 26620374 | `session_verified` | 2026-11-06 | `heap:ef7f58074afe9022` |
| 2（v2 修复后） | 118504 | 2026-11-24T13:57:21Z | 26620374 | `ambiguous` | 无 | `heap:v2:70792ff53e1ed6e6`（与 9 条同构记录共享） |

证据：

- `docs/evidence/v3.2.6.1/world-date-diagnostics-01.json`（会话 1）
- `docs/evidence/v3.2.6.1/restart-session-1.json`（会话 1 验证输出）
- `docs/evidence/v3.2.6.1/date-verification-session-1.json`（会话 1 状态）
- `docs/evidence/v3.2.6.1/world-date-diagnostics-02.json`（会话 2，142 条命中）
- `docs/evidence/v3.2.6.1/date-verification-v2-session-2.json`（会话 2 状态）

## 3. 从真实数据发现的两个缺陷及修复

### 3.1 v1 指纹包含堆指针 → 跨进程必然漂移

v1 指纹直接哈希 `[date-0x44, date)` 与 `[date+0x18, date+0x98)` 的原始字节。
真实内存转储显示这些窗口含大量堆指针（如 `0x1F76D04A0C0`、`0x1F736517A40`），
重启后堆布局变化，指纹随之改变：

```text
会话 1：heap:b16a56d8d23b4675
会话 2：heap:ef7f58074afe9022
```

结论：v1 的“唯一候选”来自地址噪声，属于假阳性，不能作为身份证据。

### 3.2 v2/v3 指针归一化 + 窗口收敛

修复后的逻辑身份定义（`CandidateIdentity`，`FingerprintVersion = 2`）：

```text
fingerprint = SHA256(
    moduleKind || version
    || mask(bytes[date - 0x44, date))        // 结构头
    || mask(bytes[date + 0x08, date + 0x58)) // 尾部：跳过日期与参考日期，且留在单条记录内
)[0..8]
signature = moduleKind + ":v2:" + fingerprint
```

`mask()` 的判定（按相对日期字段的 4 字节步长扫描，与绝对对齐无关）：

1. 8 字节对齐、低 32 位 ≥ `0x10000`、落在用户态地址范围；
2. 目标地址当前可读（`IMemorySource.IsReadable`）。

命中后整段替换为固定标记 `\0PTR8\0\0\0`，既消除地址噪声，又保持后续字段偏移不变。

低 32 位约束是必要的：真实数据里出现 `[0x00000000][对象ID]` 这类跨字段窗口，
拼出的 `0x0000XXXXXXXX00000000` 同时满足“对齐 + 可读”，若不加约束会把对象 ID 一并抹掉，
导致 142 条记录塌缩成 1 个签名。

### 3.3 修复后的真实结论

修复后同一会话重扫，得到 142 条命中、`status = ambiguous`：
`2026-11-06` 记录与另外 9 条（`2026-10-31` ~ `2026-11-05`）共享同一签名。
这些记录的结构、ID 字段与指针布局相同，只有日期/参考日期不同。

因此 **跨重启身份关联无法建立在结构指纹之上**，`restart_verified` 不可达；
按“疑义只降级”的要求，状态停在 `discovered`，自动快照 `BLOCKED`。

## 4. 判定表（期望 vs 实际）

| 字段 | 期望（达到 `restart_verified` 时） | 实际 |
| --- | --- | --- |
| `status` | `restart_verified` | `ambiguous` |
| `confidence` | `restart_verified` | `discovered` |
| `session.session_id` | 三次不同 | 两次不同（会话 3 未执行，因身份未建立） |
| `candidates[0].logical_signature` | 三次一致 | 不适用（0 个保留候选） |
| `snapshot.status` | `BLOCKED`（存档身份未验证） | `BLOCKED` ✓ |

## 5. 安全门实际输出（会话 2）

```text
snapshot.status = BLOCKED
snapshot.allowed = false
reasons:
  没有读取到可用日期。
  候选存在歧义或已被排除。
  日期可信度只有 discovered，未达到 restart_verified。
  存档身份未经验证（即使同一天同一存档也只允许一次快照）。
  日期来源不是已验证的内存候选。
```

## 6. 自动化替代验证（全部 PASS）

| 验证点 | 测试 | 结果 |
| --- | --- | --- |
| 三次独立会话 → `restart_verified` | `DateCandidateTrackerTests` | PASS |
| 地址变化但指纹相同 → 重新关联 | `DateCandidateTrackerTests` + `DateCandidateDiagnosticsTests` | PASS |
| 跨进程堆指针变化 → 指纹不变 | `DateCandidateDiagnosticsTests` | PASS |
| 标量字段变化 → 指纹必须变化 | `DateCandidateDiagnosticsTests` | PASS |
| 构建号变化 → 验证证据作废 | `DateCandidateTrackerTests` | PASS |
| `restart_verified` 但存档身份未知 → `BLOCKED` | `SnapshotSafetyGateTests` | PASS |
| 状态持久化往返 | `DateVerificationStoreTests` | PASS |

## 7. 结论与后续

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| 真实两次进程会话 | PASS（已执行） | 地址、构建号、会话键均变化 |
| 真实地址变化复关联 | **BLOCKED** | 142 条同构日期记录，结构签名不唯一 |
| 真实日期推进/回退 | NOT_RUN | 身份未建立，推进/回退无法形成有效证据 |
| 存档身份验证 | NOT_IMPLEMENTED | 安全门因此保持 BLOCKED |
| 自动快照开放 | BLOCKED | 依赖以上两项 |

要推进到 `restart_verified`，需要先补上**对象分类证据**（例如从模块静态数据出发的引用链，
证明某条日期记录属于世界状态对象），使逻辑身份不再依赖“同构记录 + 日期值”的区分方式。
在此之前，V3.2.6.1 不允许声明“日期读取已跨重启验证”。
