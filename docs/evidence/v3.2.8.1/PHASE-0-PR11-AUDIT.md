# Phase 0：PR #11 当前状态审计（V3.2.8.1）

执行日期：2026-11-26（Asia/Shanghai）
审计方式：`git fetch --prune` + `gh pr view 11` 实时查询，不采用任务书中的历史快照。

## 1. 最新真实基线

| 项目 | 值 |
| --- | --- |
| 默认分支 | `main` |
| 最新 `main` SHA | `89fe8fa7134c34a85c30693d037929a000625168` |
| PR #11 base SHA | `89fe8fa7134c34a85c30693d037929a000625168` |
| PR #11 head SHA | `df37366a42a9383a5a465ddda0ea42183289558b` |
| PR head 分支 | `codex/v3.2.8-person-calibration` |
| 审计时 ahead / behind | 35 / 2 |
| PR 状态 | OPEN（非草稿） |
| mergeable | MERGEABLE |
| mergeStateStatus | CLEAN |
| Review | 无 review、无评论 |
| 变更规模 | 62 个文件，+13131 / −3 |

`main` 领先的 2 个提交：

- `89fe8fa` Merge pull request #10（codex/v3.2.7.4-runtime-closure）
- `89ac157` Merge pull request #9（codex/v3.2.7.4-runtime-closure）

## 2. CI（审计时）

PR #11 上共有 6 类检查、2 次运行，全部 `SUCCESS`：

| 检查 | 运行 | 结论 |
| --- | --- | --- |
| Backend (pytest + migrations) | 45655257130 / 45655076166 | SUCCESS / SUCCESS |
| Upload / identity / agent isolation regressions | 同上 | SUCCESS / SUCCESS |
| .NET readers and agent | 同上 | SUCCESS / SUCCESS |
| Frontend (typecheck + build) | 同上 | SUCCESS / SUCCESS |
| PostgreSQL migration compatibility | 同上 | SUCCESS / SUCCESS |
| Playwright (governance) | 同上 | SUCCESS / SUCCESS |

## 3. 已确认的问题

1. **分支落后 main 2 个提交**：不影响当前可合并性（CLEAN），但加固分支必须在合并前同步。
2. **Backend 测试统计口径不一致**：V3.2.8 历史报告同时出现「582 项 0 失败」与「581 PASS / 1 FAIL / 3 skipped」。失败项为
   `test_real_sample_converts_cleanly`，原因是 `real_sample_01.json` 与 manifest 的 SHA-256 不一致。
3. **fixture 哈希根因未修复**：V3.2.8 的修复提交 `89fdaf2` 直接手改了 manifest 的 `sha256`（`5dc926…` → `8c7915…`），
   没有修复登记脚本，也没有补完整性回归测试，不满足 V3.2.8.1 的根因修复要求。
4. **Verified 缺少存档作用域**：`PersonVerificationGate` 只校验构建、布局、指针、结构、姓名、生日、稳定性与人工确认，
   没有绑定 Save Identity、会话键，也没有 Stale / RevalidationRequired 生命周期。
5. **真实跨存档 A/B/A 未执行**：需要人工切换存档，本阶段只能做自动化隔离验证，真实场景标记 `NOT_RUN`。

## 4. 本阶段修改范围（计划）

- 新建独立 worktree 与分支 `codex/v3.2.8.1-pr11-hardening`，合并最新 `main`（不改写远程历史、不强推）。
- Phase 2：修复 fixture 登记脚本的哈希口径，新增 6 类完整性测试，统一 Backend 统计。
- Phase 3–5：为 Verified 增加存档作用域、失效状态与门控拒绝路径，补跨存档与生命周期测试。
- Phase 6–9：真实环境核验（能执行的部分）、全量回归、九份证据、更新 PR #11（不合并）。

## 5. 与 main 的差异

- 代码差异集中在 V3.2.8 已交付的 Person 定位/校准/验证能力（`live-reader/.../Calibration`、诊断工具）与证据文档。
- 本阶段新增内容只做安全加固与测试，不重写 Person Locator、不改内存扫描引擎、不做数据库结构重构。
