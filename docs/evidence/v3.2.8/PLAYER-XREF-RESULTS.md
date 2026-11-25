# 球员属性关联结果（PLAYER-XREF-RESULTS）

- 运行日期：2026-11-25
- 游戏版本：FM27 27.1
- Steam Build：26620374
- DLL 版本：game_plugin.dll 27.1
- Git SHA：`5720c88`（报告整理时）
- 关联详细记录：`PERSON-ATTRIBUTE-LINK.md`、`PERSON-DIAGNOSTICS.md`

## 1. 运行结果

| 运行 | 定位总数 | 抽样 | 唯一关联 | 多候选 | 冲突 | 成功率 |
| --- | --- | --- | --- | --- | --- | --- |
| 关联审计（Phase 4） | 800 | 60 | 60（SingleCandidate） | 0 | 0 | 1.00 |
| `dump --xref`（Phase 6） | 800 | 60 | 60 | 0 | 0 | 1.00 |
| `dump --xref`（优化后，当前存档） | 800 | 60 | 59 | 0 | 1（ConflictingIdentity） | 0.9833 |

- Phase 4 审计中字段可用性：UID 60/60、姓名 48/60、俱乐部 43/60。
- 缺失分布：俱乐部缺失 5 条；姓名与俱乐部同时缺失 12 条。
- 当前存档的 1 条冲突是同名但其它字段不一致，关联器返回 `ConflictingIdentity`，没有自动选择。

## 2. 关联规则

- 强匹配只能来自姓名键或 UID；生日单独命中不足以建立关联。
- 姓名键使用“完整名 + 姓”及反向组合，避免 `Ahmed Rashid` 与 `Ahmed Al-Hosani` 被误判同名。
- 多个兼容候选返回 `MultipleCandidates`；同名但字段冲突返回 `ConflictingIdentity`；两者都禁止自动取第一个。
- 缺失字段保持 `null`，不默认为 0，也不伪造匹配。

## 3. 状态

| 项目 | 状态 |
| --- | --- |
| UID + 姓名 + 生日 + 俱乐部联合关联 | PASS |
| 多候选/冲突不自动选择 | PASS |
| 缺失字段不默认 | PASS |
| 全库关联（所有 Person） | PARTIAL（仅抽样 60） |
| 跨存档关联一致性 | UNKNOWN |

## 4. 失败与未完成

- 姓名缺失导致部分记录无法使用姓名强匹配，只能依赖 UID。
- 当前存档出现 1 条同名冲突；未做人工裁定，保持冲突证据。
- 未做全库 800/800 逐条审计，仅抽样 60。
- 未验证转会/退役后属性记录与 Person 的关联变化。

## 5. 复现

```text
ScoutMind.FMReader.Diag.exe xref --link-all --located 800 --samples 60
ScoutMind.FMReader.Diag.exe dump --xref --located 800 --samples 60
```
