# P1 修复：Verified 指纹绑定当前存档

日期：2026-11-26
分支：`codex/v3.2.9.1-verified-fingerprint-binding`
状态：代码修复 **PASS**；自动化 **PASS**；真实负向验证 **PASS**；LiveReader 粘滞行为 **未修复（记录在案）**。

## 1. 缺陷回顾

真实 A/B/A 中发现：

1. `Diag verify` 把调用方传入的 `--save-identity` 同时当作"历史作用域"和"当前存档指纹"，门控的 `scope_save_identity_mismatch` 永远不会触发。
2. LiveReader 的确认状态固定在最后确认的文件上，切档后仍返回旧指纹。

结果：在 B 已加载时，用 A 的旧指纹可以产生 `Verified`、`mark_verified=true`、无告警。

## 2. 修复

只改证据链，不改判定规则：

- 新增 `SaveIdentityBinding.CurrentFingerprint`：只有唯一、来自存档文件的解析结果才作为当前指纹；歧义/未解析返回 `null`。
- `Diag verify` 每次现场探测当前存档（默认目录或 `--save-file`），**不使用**历史确认状态，**不使用**调用方传入指纹作为当前值。
- 门控按既有规则比较：当前指纹缺失 → `current_save_identity_missing`；不一致 → `scope_save_identity_mismatch` → `RevalidationRequired`。
- 新增 `--save-file <path>`：多存档目录下必须显式指明，否则拒绝 Verified。

修改文件：

- `live-reader/ScoutMind.FMReader/Discovery/SaveIdentityBinding.cs`（新增）
- `live-reader/tools/ScoutMind.FMReader.Diag/Program.cs`
- `live-reader/tests/ScoutMind.FMReader.Tests/SaveIdentityTests.cs`

## 3. 自动化

- FMReader 测试：**311 PASS / 0 FAIL**（新增 3 项绑定用例）。
- 既有门控用例继续覆盖：`scope_save_identity_mismatch`、`current_save_identity_missing`。

## 4. 真实负向验证（2026-11-26）

| 场景 | 结果 |
| --- | --- |
| 旧 A 指纹 + 显式当前 A 文件（文件已重存，指纹已变） | `RevalidationRequired` + `scope_save_identity_mismatch`，未 Mark |
| 旧 A 指纹、不指定 `--save-file`（目录多候选） | `RevalidationRequired` + `current_save_identity_missing`，problem=`current_save_identity_ambiguous`，未 Mark |

修复前的对照：同一旧指纹在 B 加载时得到 `Verified`。

## 5. 剩余风险

- 调用方仍可显式传入 `--save-file A` 而在 B 中操作（主动撒谎）。这是可审计的显式断言，不再是由默认真实值引发的隐式污染。
- LiveReader `save-identity` 在切档后仍可能返回旧指纹；建议后续：检测到"存在比已确认文件更新的候选"时返回 `Conflict`，强制重新确认。
- 文件指纹依赖卷序列号 + FileId；重新保存可能改变 FileId，导致同生涯需要重新确认。这是保守行为，但用户体验需说明。

## 6. 结论

P1 的**隐式信任路径已关闭**；显式伪造仍依赖操作者，不可由本工具单独证明。
不得把本修复表述为"跨存档 Verified 已完全安全"。
