# V3.2.9 最终报告

日期：2026-11-26
分支：`codex/v3.2.9-player-identity`
基线：`codex/v3.2.8.1-pr11-hardening`（PR #11 head `52f596c`）
main：`89fe8fa7134c34a85c30693d037929a000625168`

## 1. 总体结论

**PARTIAL（工程 PASS，真实验收 NOT_RUN）。**

- 代码：已实现。
- 自动化测试：通过。
- CI：6/6 通过。
- 真实 FM27 全库扫描 / 生命周期 / A/B/A：未执行。
- 人工真实球员核对：未执行（本阶段不重复 V3.2.8 的人工核对）。
- 无 P0/P1 未解决安全问题。

不把 PARTIAL 写成 PASS。

## 2. 授权偏离（必须显式记录）

V3.2.9 任务书 §1.1 要求「V3.2.8.1 未合并前只允许只读」。用户明确授权基于未合并分支继续开发并要求自动执行全部阶段，因此本阶段做了完整实现。详见 `PRECONDITION.md`。

风险：若 PR #11 被拒绝，本分支的 Verified 作用域前提需要重做。

## 3. 交付内容

### 3.1 数据层

- 新迁移 `a1b2c3d4e5f6_player_identity_governance`（六张新表，不改既有表）。
- `player_uid_observations`：存档作用域 UID 观测，只追加。
- `player_identity_links`：Canonical 关联，显式失效，保留历史。
- `player_identity_review_items` / `player_identity_review_actions`：人工审核队列与不可改审计。
- `identity_scan_runs`：批次、游标、作用域校验和。
- `cross_save_identity_candidates`：跨存档候选，UID 只是证据。

### 3.2 服务层

- `uid_scope.py`：分类、幂等观测、重复分组、统计。
- `identity_engine.py`：有界扫描、暂停/恢复/取消、同名与重复 UID 冲突、Canonical 关联、跨存档候选。
- `identity_review.py`：四种人工决定、审计追加、拒绝 Verified。
- `transfer_identity.py`：只补齐空转会关联，多匹配转人工审核。

### 3.3 API 与前端

- `/identity/center/*` 与 `/identity/scans/*` 共 15 个端点。
- 前端新增「球员身份中心」页面（统计、扫描、队列、审核、跨存档）。

### 3.4 文档

`docs/evidence/v3.2.9/` 共 14 份：

PRECONDITION、PHASE-0-DATA-AUDIT、UID-SCOPE-DESIGN、PLAYER-RECONCILIATION-DESIGN、CANONICAL-PLAYER-DESIGN、FULL-SCAN-RESULTS、DUPLICATE-IDENTITY-REPORT、CROSS-SAVE-IDENTITY-REPORT、TRANSFER-IDENTITY-LINK-REPORT、FRONTEND-REVIEW-CENTER、PERFORMANCE-REPORT、TEST-MATRIX、CI-RESULTS、本文件。

## 4. 测试结果（同一批次）

| 套件 | 结果 |
| --- | --- |
| Backend pytest | 628 采集 / 625 通过 / 0 失败 / 3 跳过 |
| V3.2.9 新增 | 37 / 37 通过 |
| FMReader.Tests | 308 / 308 通过 |
| Reader.Tests | 57 / 57 通过 |
| Agent.Tests | 38 / 38 通过 |
| Frontend build | 通过 |
| GitHub Actions | 6/6 通过（run 45749190883） |

跳过 3 项：PostgreSQL 实机测试 1 项（未配置测试库）、FMSuperScout 真实样本 2 项（仓库无样本）。CI 中 PostgreSQL 迁移兼容作业独立通过。

## 5. 安全问题审计

| 检查 | 结论 |
| --- | --- |
| 直接写 Verified 的入口 | 无；审核接口显式拒绝（`VERIFIED_NOT_SETTABLE`） |
| 仅凭姓名自动 Verified | 无；同名只产生冲突与审核条目 |
| 无存档作用域 Verified | 本层不生产 Verified |
| 旧 Person 指针复用 | 不持久化内存地址；恢复时校验指纹/构建/布局 |
| 多候选自动选第一条 | 无；多候选进入审核，保持未关联 |
| 失败后放宽条件 | 无；失败写错误码并停止 |
| 删除历史审计 | 无；ORM 层拒绝更新/删除审核审计行 |

## 6. 跨存档与生命周期

- Save A / Save B 关联隔离：自动化通过。
- 标 A 为 Stale 不影响 B：自动化通过。
- A → B → A 真实流程：NOT_RUN。
- 转会 / 自由球员 / 退役真实场景：NOT_RUN；自动化覆盖转会与俱乐部变化。
- 同名不同生日、同名同生日不同 UID：自动化覆盖。

## 7. 性能

内存 SQLite、1200 实例、批 200：1.496 s，约 802 行/秒，1.246 ms/行。真实环境未测。

## 8. 十二项交付回答

1. **main SHA**：`89fe8fa7134c34a85c30693d037929a000625168`。
2. **PR #11 最新 SHA**：head `52f596c0898537d85bbef7dac19377330c219eb2`，base `89fe8fa`，状态 OPEN，MERGEABLE。
3. **新增分支**：`codex/v3.2.9-player-identity`（已推送，未建 PR）。
4. **修改文件**：新增 6 个后端服务/路由、1 个迁移、7 个测试文件、3 个前端文件；修改 models/schemas/main/router/App 与 4 份既有 V3.2.9 文档；新增 8 份证据文档。
5. **修复的问题**：UID 哨兵被当成 0、跨存档 UID 被误合并、同名冲突无审核闭环、历史转会无身份关联、批次不可恢复、审核可覆盖历史、审核接口可能写入 Verified。
6. **Backend 统计**：628 / 625 PASS / 0 FAIL / 3 SKIP。
7. **Reader 统计**：308 PASS（FMReader）+ 57 PASS（Reader）。
8. **Agent 统计**：38 PASS。
9. **CI 结果**：6/6 成功。
10. **跨存档验证**：自动化 PASS；真实 A/B/A NOT_RUN。
11. **真实 FM27 验收**：NOT_RUN（进程在运行，但未执行真实扫描/生命周期）。
12. **未完成事项**：真实全库扫描、真实生命周期、真实 A/B/A、真实性能、浏览器 E2E、PostgreSQL 实机 pytest。

## 9. 风险

| 级别 | 风险 | 处理 |
| --- | --- | --- |
| 中 | 基于未合并 PR #11 开发 | PR #11 若被拒绝，本分支需重做 Verified 前提 |
| 中 | 全库扫描在数据变化时会失败 | 需新 `scan_id` 重扫，属于刻意保护 |
| 低 | 内存索引上限 20 万实例 | 超过直接拒绝，不会 OOM |
| 低 | 前端未做 E2E | 构建与类型检查通过，交互未自动化 |

## 10. 合并建议

- V3.2.9 分支达到**人工合并条件**（工程与自动化层面），但不是自动合并。
- PR #11 仍未合并；建议先决定 PR #11，再决定 V3.2.9 的 PR 目标分支。
- 本 Agent 未合并、未发布、未删除任何分支。
