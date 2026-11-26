# V3.2.9.2 阶段 2 — Verified 生命周期与 generation

## 1. 问题

V3.2.9.1 的 `PersonVerificationGate` 只能比较“当次观测”和 `VerifiedIdentityScope`，
但持久层没有 generation：

- 旧任务（切档前开始、切档后返回）可以写回 Verified；
- 撤销/失效没有历史，无法解释为什么失效；
- 不同存档的 Verify 可能互相覆盖；
- 未知状态有可能被 UI/API 当成功展示。

## 2. 修改

新增 `live-reader/ScoutMind.FMReader/Calibration/VerifiedLifecycleLedger.cs`：

| 能力 | 实现 |
| --- | --- |
| 证据固化 | `VerificationEvidence`：指纹、会话、构建、布局、UID、姓名、生日、属性记录摘要、验证器版本、证据摘要 |
| generation | `Begin()` 取令牌；`Commit()` 要求令牌代次 == 当前代次 |
| 切档 / 会话变化 | `AdvanceGeneration(reason)`：追加 `Invalidated` 记录并清空有效项 |
| 撤销 | `Revoke()`：失效 + 推进代次，旧任务令牌立即过期 |
| 幂等 | 同作用域 + 同证据 + 同验证器 → `Duplicate`，不新增历史 |
| 互不覆盖 | 台账按（指纹, UID）分键，A 存档与 B 存档各自有效 |
| 证据不足 | `VerificationEvidence.IsComplete == false` → `InsufficientEvidence`，绝不写 Verified |
| 只追加 | 所有状态变化都追加 `VerifiedLifecycleRecord`，序号唯一，不 update/delete |
| 并发安全 | 所有读写都在同一互斥锁内，避免两个验证任务同时写入 |
| 未知状态 | `VerificationStateText.IsSuccess()` 只认 `"verified"`；未知序列化为 `"unknown"` |

`PersonVerificationGate` 与 `VerifiedIdentityScopeValidator` 保持原有门控职责，
台账负责“持久化生命周期 + 并发/代次仲裁”，两者不重复。

## 3. 新增测试（11 项）

`live-reader/tests/ScoutMind.FMReader.Tests/VerifiedLifecycleTests.cs`

1. 同一作用域重复 Verify 幂等；
2. 存档切换使旧 Verified 失效并记录 `save_identity_changed`；
3. 进程重启后必须重新验证（`session_changed`）；
4. generation 不一致拒绝提交；
5. 不同存档 Verify 不互相覆盖；
6. 旧任务晚到不得污染新状态；
7. 无证据不能 Verified；
8. 已撤销 Verified 不能被旧任务恢复；
9. 未知状态不得显示为成功；
10. 其余并发提交保持幂等（并发测试）；
11. 历史记录可追溯（Verified + Invalidated + 新 Verified）。

## 4. 实际结果

`PASS 334 · FAIL 0`（与阶段 1 同一次运行），其中本阶段 11 项全部通过。

## 5. 语义边界

- 台账不会自行把任何状态提升为 Verified；是否允许 Verified 仍由
  `PersonVerificationGate` + `VerifiedIdentityScope` 决定。
- 台账的代次与 `SaveIdentityState.Generation` 使用同一语义（切档/会话变化递增），
  但分别位于 LiveReader 身份层与 Person 验证层。
