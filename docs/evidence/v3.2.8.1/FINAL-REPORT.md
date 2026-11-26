# V3.2.8.1 最终报告（PR #11 加固）

## 1. Git 状态

| 项目 | 值 |
| --- | --- |
| main SHA | `89fe8fa7134c34a85c30693d037929a000625168` |
| PR #11 head（加固前） | `df37366a42a9383a5a465ddda0ea42183289558b` |
| 加固分支 | `codex/v3.2.8.1-pr11-hardening` |
| 同步 main 的合并提交 | `a3487b4` |
| 强制推送 | 未使用 |
| PR 合并 | 未执行（等待用户决定） |

## 2. 修改文件

Backend / 脚本 / 配置：

- `backend/tests/fixture_integrity.py`（新增）
- `backend/tests/test_fixture_integrity.py`（新增）
- `scripts/register_fixture.py`
- `.gitattributes`（新增）

.NET：

- `live-reader/ScoutMind.FMReader/Calibration/VerifiedIdentityScope.cs`（新增）
- `live-reader/ScoutMind.FMReader/Calibration/PersonVerificationGate.cs`
- `live-reader/tools/ScoutMind.FMReader.Diag/Program.cs`
- `live-reader/tests/ScoutMind.FMReader.Tests/VerifiedIdentityScopeTests.cs`（新增）
- `live-reader/tests/ScoutMind.FMReader.Tests/PersonVerificationGateTests.cs`
- `live-reader/tests/ScoutMind.FMReader.Tests/Program.cs`

文档：`docs/evidence/v3.2.8.1/` 下 9 份报告。

## 3. 修复的问题

| # | 问题 | 状态 |
| --- | --- | --- |
| 1 | 分支落后 main 2 个提交 | 已同步（自动合并，无冲突） |
| 2 | Backend 统计矛盾（582 / 581+1） | 已统一为 591 / 588 PASS / 3 SKIP / 0 FAIL |
| 3 | `real_sample_01.json` SHA-256 不一致 | 根因定位 + 受控校验 + 9 项完整性测试 |
| 4 | Verified 无存档作用域 | 新增 `VerifiedIdentityScope` + 门控强制校验 |
| 5 | 旧指针/旧会话可复用风险 | 会话不一致 → `RevalidationRequired` |
| 6 | 同名/同 UID 跨存档误合并风险 | 跨存档 → `Stale`；同 UID 不同存档不合并 |
| 7 | 门控绕过路径 | 审计完成，新增拒绝路径测试 |
| 8 | CI 完整性 | 推送前 6 类检查全 SUCCESS；推送后需复核 |

## 4. 测试统计（本批次真实结果）

| 套件 | 结果 |
| --- | --- |
| Backend pytest | 591 collected / 588 PASS / 0 FAIL / 0 ERROR / 3 SKIPPED |
| ScoutMind.FMReader.Tests | 308 PASS / 0 FAIL |
| ScoutMind.Reader.Tests | 57 PASS / 0 FAIL |
| ScoutMind.Agent.Tests | 38 PASS / 0 FAIL |
| Frontend production build | PASS（8.48s） |
| `git diff --check` | PASS |

## 5. Verified 跨存档验证

- 自动化：PASS（17 项作用域/生命周期 + 5 项门控拒绝路径）。
- 真实 FM27：
  - 进程/构建/插件/布局/版本闸门：已确认（pid 72012 / 26620374 / 27.1 / FM27_1 / allow_scan）。
  - Save Identity：VERIFIED（`si:v1:file:b887415a…`）。
  - A/B/A 全流程：**NOT_RUN**（需人工切换存档；当前存档无法按姓名唯一匹配历史核对球员）。

## 6. 验收结论

| 维度 | 结论 |
| --- | --- |
| 测试报告一致性 | PASS |
| Fixture SHA-256 根因修复 | PASS |
| Verified 作用域明确 | PASS |
| 跨存档隔离（自动化） | PASS |
| 门控无绕过路径 | PASS |
| CI | PASS（推送前）；推送后待复核 |
| 真实 FM27 A/B/A | NOT_RUN |
| 综合 | **PARTIAL** |

不得把 PARTIAL 改写为 PASS。

## 7. 未完成事项

1. 真实 FM27 的 A→B→A 全流程与转会/自由球员/退役生命周期（需要用户操作）。
2. 推送后的 GitHub Actions 结果复核。
3. `source_sha256` 无法复核（原始 48k dump 不在仓库）→ UNKNOWN。

## 8. 风险

- **P0/P1**：未发现。
- 中风险：真实环境尚未验证新门控在“人工核对后切换存档再返回”时的实际交互；自动化已覆盖逻辑层。
- 低风险：`.gitattributes` 只作用于 fixture 样本，不影响其他 JSON。

## 9. 合并建议

- 代码与自动化测试达到人工合并条件。
- 建议合并前由用户完成一次真实 A/B/A 抽样确认；若认可自动化覆盖，可直接进入人工合并评审。
- 本 Agent 不合并 PR、不发布 Release、不删除分支。
