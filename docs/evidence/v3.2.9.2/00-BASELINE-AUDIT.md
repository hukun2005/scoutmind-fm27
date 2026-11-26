# V3.2.9.2 阶段 0 — 基线审计

- 执行时间：2026-11-26（Asia/Shanghai）
- 工作区：`C:\Users\hukun\Documents\Trae-CN\temp_20261124_02\scoutmind-v3281`（独立 worktree）
- 本阶段分支：`feature/v3.2.9.2-livereader-save-switch-safety`（从 `origin/main` 创建）
- 审计方式：只读代码审查 + 本地命令 + GitHub CLI 实时查询；未沿用历史 SHA 与历史数字。

---

## 1. 当前 main SHA

| 项目 | 实测值 |
| --- | --- |
| `git rev-parse origin/main` | `24beabad50083d22c5581de03480de2311fd9ad1` |
| 分支来源 | `origin/main` |
| 工作区状态 | 干净（`git status --short --branch` 无未提交/未跟踪文件） |
| 其他 worktree | 6 个历史 worktree 保留，未删除、未覆盖 |

## 2. PR #13 当前状态

`gh pr view 13` 实测：

- 状态：`MERGED`
- 合并提交：`24beabad50083d22c5581de03480de2311fd9ad1`
- 合并时间：2026-11-26T08:58:33Z
- 标题：`V3.2.9.1: Bind Verified fingerprint to the live save identity (P1 fix)`

main 最近 CI（run `45787728897`，head `24beaba`）：`success`。
结论：PR #13 仍是当前身份验证实现的基线，但 **它未覆盖存档切换后的旧确认失效**，见 P0。

## 3. 相关模块实际路径

| 能力 | 实际路径 |
| --- | --- |
| Save Identity 模型/解析/指纹 | `live-reader/ScoutMind.FMReader/Discovery/SaveIdentityModels.cs` |
| 当前身份绑定 | `live-reader/ScoutMind.FMReader/Discovery/SaveIdentityBinding.cs` |
| 存档文件探测（含 `--save-file` 单文件模式） | `live-reader/ScoutMind.FMReader/Discovery/SaveFileProbe.cs` |
| 身份状态持久化 | `live-reader/ScoutMind.FMReader/Discovery/SaveIdentityStore.cs` |
| 存档切换检测器 | `live-reader/ScoutMind.FMReader/Discovery/SaveSwitchDetector.cs` |
| Verify 门控（Person） | `live-reader/ScoutMind.FMReader/Calibration/PersonVerificationGate.cs` |
| Verified 作用域与生命周期 | `live-reader/ScoutMind.FMReader/Calibration/VerifiedIdentityScope.cs` |
| 诊断编排 / CLI | `live-reader/ScoutMind.FMReader/Engine/FmSaveIdentityDiagnostics.cs`、`live-reader/ScoutMind.Reader/Cli.cs` |
| 全库关联引擎 | `backend/app/services/identity_engine.py` |
| UID 作用域 | `backend/app/services/uid_scope.py` |
| 审核队列/审计 | `backend/app/services/identity_review.py`、`backend/app/api/routes_identity_center.py` |
| 转会身份关联 | `backend/app/services/transfer_identity.py` |
| 数据模型 | `backend/app/models.py` |
| 现有 migration head | `backend/alembic/versions/a1b2c3d4e5f6_player_identity_governance.py`（`a1b2c3d4e5f6`，无后继） |
| 现有 V3.2.9 测试 | `backend/tests/test_v329_*.py` |

仓库现状与任务书历史路径一致；`identity_review.py` 存在，`routes_identity_center.py` 是审核 API 入口。

## 4. 当前 Save Identity 生命周期

1. `FmSaveIdentityDiagnostics.Analyze()` 读取进程/构建证据 + 存档文件快照。
2. `SaveIdentityResolver.Resolve()` 生成指纹（`si:v1:file:<sha256>`，来自卷序列号 + FileId）。
3. 状态写入 `SaveIdentityStore`（`%LOCALAPPDATA%\ScoutMind\save-identity.json`），字段含 `Fingerprint / LastSessionKey / UserConfirmedFingerprint / UserConfirmedAt`。
4. `--verify` 把当前 Candidate 指纹写为 `UserConfirmedFingerprint`，再次解析得到 `Verified`。
5. `SaveIdentityBinding.CurrentFingerprint()` 只接受唯一、文件来源、非歧义的指纹，供 Person 门控使用。

**缺失**：没有 `generation` 版本令牌；没有“确认随存档切换而失效”的规则；没有区分“显式指定文件”与“运行时确认的当前存档”。

## 5. LiveReader 是否复用旧指纹

**是（P0）**。`SaveIdentityModels.cs` 的 `Resolve()` 在 `SelectActiveFile()` 返回歧义时，会用 `input.UserConfirmedFingerprint` 在候选文件里**反向选择**当前存档：

- 位置：`SaveIdentityModels.cs` 约 L339–L355。
- 后果：切到 Save B 后，若 A、B 同时存在且文件未被独占锁定，解析器仍会按旧确认指纹选中 Save A，`save-identity` 继续输出旧指纹。
- 违反：任务书 §5.2「LiveReader 返回旧指纹 → 不允许将旧指纹用于新 Verify」。

## 6. `--save-file` 是否与实际运行存档绑定

**否（P0）**。`SingleSaveFileProbe`（`SaveFileProbe.cs` L244–L262）只 `Describe()` 指定路径，不校验该文件是否被当前 FM27 进程加载；`FmSaveIdentityDiagnostics` 在 `--verify` 时会直接把该文件的 Candidate 升为 Verified。缺少 `CURRENT_SAVE_UNCONFIRMED` 限制状态。

## 7. Verified 状态保存与失效机制

- Person 级：`PersonVerificationGate.Evaluate()` 已校验 `VerifiedIdentityScope`（指纹、会话、构建、布局、UID、姓名、生日）与当次观测一致，不一致返回 `RevalidationRequired`。
- 生命周期：`VerifiedIdentityScopeValidator.Evaluate()` 已能把历史 Verified 判为 `Stale / RevalidationRequired / Conflicted`。
- **缺失（P0）**：没有 generation/version token；没有“旧异步任务晚到不得覆盖新结果”的仲裁；Verified 记录未固化 generation 与失效原因，无法在持久层阻止旧任务回写。

## 8. 身份审核并发实现

- 模型：`PlayerIdentityReviewItem`（无版本列）+ `PlayerIdentityReviewAction`（append-only，ORM 事件禁止 update/delete）。
- 逻辑：`identity_review.resolve_review()` 先检查 `item.status in RESOLVED_STATUSES` 再写入，属于 check-then-act，无行锁、无条件更新、无版本校验。
- 结论：SQLite 单写者下不易复现；PostgreSQL 下两个审核者可同时通过检查并静默覆盖（P1）。请求无幂等键，重复提交会产生重复历史行。

## 9. 当前待审核数量

- 本地无生产数据库（`backend/data/scoutmind.db` 不存在，`backend/.env` 不存在），无法离线统计真实待审核条目。
- 历史文档中的 813 条未被本次复核，**不得**当作当前状态。
- 本阶段结论：`PENDING_REVIEW_COUNT = NOT_AVAILABLE_LOCALLY`；真实数量须在用户实际部署库上重新统计（README/操作手册中给出统计命令）。

## 10. 当前测试覆盖

| 套件 | 命令 | 基线 |
| --- | --- | --- |
| Backend | `cd backend; python -m pytest` | 628 collected（`--collect-only` 实测） |
| FMReader | `dotnet run --project live-reader/tests/ScoutMind.FMReader.Tests -c Release` | 见 `06-AUTOMATED-TEST-REPORT.md` 实测 |
| Reader | `dotnet run --project live-reader/tests/ScoutMind.Reader.Tests -c Release` | 见 06 实测 |
| Frontend | `cd frontend; npm run build` | 见 06 实测 |

已有 `SaveSwitchDetectorTests`、`SaveIdentityTests`、`PersonVerificationGateTests`、`VerifiedIdentityScopeTests`、`test_v329_*.py`；**没有**“切档后旧确认失效 / 旧任务 generation / 审核并发”测试。

## 11. 当前真实 FM27 验收状态

- 前置版本 V3.2.9.1 在用户本机完成过真实 A/B/A（证据：`docs/evidence/v3.2.9/REAL-FM27-ACCEPTANCE.md`）。
- 本次执行环境为开发 worktree；A→B→A 需要用户在 FM27 内切档配合，**尚未执行**。
- 本阶段验收口径：`REAL_FM27_A_B_A = NOT_RUN`（详见 `07-REAL-FM27-VALIDATION.md`），不得因单元测试通过而标 PASS。

## 12. 本阶段问题清单

### P0（可能导致错误 Identity Verified / 跨存档污染）

| 编号 | 问题 | 位置 |
| --- | --- | --- |
| P0-1 | 用户旧确认指纹被用于**选择**当前存档，切档后仍返回旧指纹 | `SaveIdentityModels.cs` `Resolve()` / `SelectActiveFile` 调用处 |
| P0-2 | 身份/会话变化时没有使旧确认与 Verified 失效，也没有 generation 令牌 | `FmSaveIdentityDiagnostics.cs`、`SaveIdentityStore.cs` |
| P0-3 | `--save-file` 仅凭路径即视为当前存档，可被 `--verify` 提升为 Verified | `SaveFileProbe.cs`、`FmSaveIdentityDiagnostics.cs` |
| P0-4 | Verified 未绑定 generation，旧异步任务可晚到覆盖新状态 | `PersonVerificationGate.cs`、`VerifiedIdentityScope.cs` |

### P1（状态不一致 / 审核覆盖 / 审核结果错误）

| 编号 | 问题 | 位置 |
| --- | --- | --- |
| P1-1 | 审核无版本号/条件更新，两个审核者可同时成功并静默覆盖 | `identity_review.py`、`models.py` |
| P1-2 | 审核请求无幂等键，重复请求重复追加历史 | 同上 |
| P1-3 | 同名候选 `same_birth` 分支提前返回，丢失不同生日/未知生日候选 | `identity_engine.py` `_same_name_review` |
| P1-4 | 转会仅凭唯一姓名即写入身份关联，缺少证据组合与 `INSUFFICIENT_EVIDENCE` | `transfer_identity.py` `link_transfers` |

### P2（性能 / 可观测性 / 体验）

| 编号 | 问题 | 位置 |
| --- | --- | --- |
| P2-1 | `_build_index()` 全量载入；`_duplicate_uid_review()` 每批重复分组查询 | `identity_engine.py` |
| P2-2 | 诊断 JSON 未输出 generation / 失效原因 / 当前存档确认状态 | `Cli.cs`、`FmSaveIdentityDiagnostics.cs` |
| P2-3 | 审核队列缺证据分级（HIGH_CONFIDENCE / NEEDS_REVIEW / CONFLICT / INSUFFICIENT_EVIDENCE）汇总 | `routes_identity_center.py` |

---

## 结论

基线可用，PR #13 有效；但 **P0-1～P0-4 未解决前不得宣称存档切换安全**。后续按阶段 1→4 修复并以新增测试与真实命令结果为准。
