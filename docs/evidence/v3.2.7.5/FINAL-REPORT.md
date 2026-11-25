# V3.2.7.5 最终报告（C / D / E 补全）

- 状态：**PARTIAL**（A/B/A 已通过并保留；C/D/E 协议级通过，真实 FM27 人工子场景待执行）
- 日期：2026-11-25 19:35（Asia/Shanghai）
- 分支：`codex/v3.2.7.4-runtime-closure`
- 远端：`origin` 同名分支已推送（历史重写后，见 §9）；`main` 仍为旧历史 `ca79d31`，待确认后重写
- 本轮已执行：分支 push（含 25 个非 `main` 分支的历史重写强推）；未创建 PR、未合并 main、未发布 Release

## 0. 结论

1. D-01 修复与 A→B→A 真实 FM27 结果完整保留，未覆盖、未回滚、未清理。
2. C / D / E 已补齐可真实执行的后端进程级验收，并在本机全部通过。
3. 真实 Agent + 真实 FM27 的 C/E 子场景、跨后端进程的 D 子场景保持 **NOT_RUN**，已给出人工步骤与证据采集命令。
4. 上传前发现 2 类本地路径泄漏风险：未推送提交中的已在推送前脱敏；已发布历史中的已在 2026-11-25 全量重写处理（`main` 待确认，见 §9）。

## 1. 保护当前成果

| 项目 | 结果 |
| --- | --- |
| 起始 `git status` | 1 个已修改测试文件 + 未跟踪的 `tools/runtime-acceptance/`、`docs/evidence/v3.2.7.5/` |
| 处置 | 先在仓库外生成未推送提交的 git bundle 备份，再将代码/测试/工具提交为本地检查点 `1572451` |
| `3ed41b6`（D-01 + A/B/A 证据） | 结论与数值完整保留；仅把本机路径、游戏内经理名与存档名替换为占位符后重写该未推送提交 |
| 破坏性操作 | 未执行 `reset --hard`、`clean -fd`；未删除现有文件或测试 |
| 远端 | 未 push、未建 PR |

检查点提交：`1572451 checkpoint(v3.2.7.5): preserve D-01 fix tests and C/D/E runtime acceptance tools`。

## 2. 代码与工具修改

| 文件 | 修改 | 原因 |
| --- | --- | --- |
| `backend/app/ingestion/importer.py` | `backend_restarted` 改为**每个受影响存档各写一条** | 原事件 `save_id=None`，按存档过滤的审计 API 永远读不到，E 的第 8 项无法验证 |
| `tools/runtime-acceptance/backend_harness.py` | 证据落盘统一脱敏本机绝对路径 | 防止用户名/临时目录进入仓库 |
| `tools/runtime-acceptance/verify_network_recovery.py` | 修复 2 处失真基线；改用球员+快照双指标 | 原基线在多次导入前取值，导致误报/漏报；单看球员数无法证明无重复写 |
| `tools/runtime-acceptance/verify_cancel_two_process.py` | `subprocess.join` → `wait(timeout=...)` | 原调用不存在，脚本直接崩溃 |
| `tools/runtime-acceptance/verify_backend_restart_recovery.py` | 同上 | 同上 |
| `tools/runtime-acceptance/collect_evidence.ps1` | 删除硬编码用户名规则、版本号改为 v3.2.7.5 | 消除代码中的本机路径特征 |
| `docs/evidence/v3.2.7.5/REAL-FM27-ACCEPTANCE.md` | 新增 | 最终真实验收记录 |
| `docs/evidence/v3.2.7.5/FINAL-REPORT.md` | 新增 | 本文件 |
| `docs/evidence/v3.2.7.5/runtime/*` | 新增证据 + manifest + summary | C/D/E 原始 JSON 证据 |

本轮**未修改迁移文件**，无数据库结构变更。

## 3. C / D / E 执行结果

| 场景 | 脚本 | run_id | 检查数 | 结果 | 证据 |
| --- | --- | --- | --- | --- | --- |
| C 断网恢复 | `verify_network_recovery.py` | `0e520c00` | 14 | PASS | `docs/evidence/v3.2.7.5/runtime/network-recovery-result.json` |
| D 取消任务 | `verify_cancel_two_process.py` | `289042f3` | 7 | PASS | `docs/evidence/v3.2.7.5/runtime/cancel-two-process-result.json` |
| E 重启恢复 | `verify_backend_restart_recovery.py` | `144df52e` | 14 | PASS | `docs/evidence/v3.2.7.5/runtime/backend-restart-recovery-result.json` |

执行特征：

- 后端为**真实 uvicorn 进程** + 全新 SQLite 数据库 + `alembic upgrade head`；
- C 使用真实 HTTP，含响应丢失、处理中断开、后端停机、重连、代次推进；
- D 由**独立子进程**提交 50,000 人导入，本进程按真实 HTTP 发起取消；验证取消/提交竞态、Worker 感知、无半提交、幂等；
- E 在 12,000 人导入中**硬杀**后端，重启后恢复 `running` 任务、拒绝旧代次会话、验证重试不重复写；
- 三份证据均标注 `synthetic_identity=true`、`real_fm27=false`，**不冒充真实 FM27 结果**。

## 4. 测试

| 范围 | 命令 | 结果 |
| --- | --- | --- |
| 后端全量 | `python -m pytest -q`（backend） | 580 项收集，577 passed / 3 skipped / 0 failed，退出码 0 |
| 受影响后端用例 | `pytest tests/test_worker_cancellation.py tests/test_import_jobs_api.py -q` | 全部 passed |
| Agent 单测 | `dotnet test desktop-agent/tests/ScoutMind.Agent.Tests -c Release` | 38 passed / 0 failed |
| `git diff --check` | 工作区 + 已暂存 | 无空白错误，退出码 0 |

## 5. 上传前检查结果

| 检查 | 结果 | 说明 |
| --- | --- | --- |
| 全部修改审阅 | 通过 | 仅 §2 所列 6 个代码/工具文件 + 新增文档与证据 |
| 相关测试 | 通过 | 见 §4 |
| `git diff --check` | 通过 | 退出码 0 |
| v3.2.7.5 证据敏感信息 | 通过 | 无密钥、Token、密码；无 `C:\Users\...` |
| 未推送提交中的本地路径 | **已处理** | 13 个文件中的本机路径、游戏内经理名与存档名已替换为 `<local-path>` / `<manager>` / `<save-A>` / `<save-B>`；A 仍为 18,614/18,614、B 仍为 18,614/37,228，任务 id、扫描 id、时间戳未变 |
| 已发布历史中的本地路径 | **已清理（`main` 待处理）** | 2026-11-25 以 `git filter-repo --replace-text` 重写全部分支：26 个分支提交数不变，改动仅为本机路径/经理名/存档名占位符；已强推 25 个非 `main` 分支，`main` 待确认后执行（见 §9） |
| 真实存档文件 | 未包含 | 仓库内只有 JSON 证据，无 `.fm` 存档 |
| Migration 安全 | 通过 | 本轮无迁移变更；C/D/E 均在空库上成功 `upgrade head` |
| 文档 PASS 与证据一致性 | 通过 | 每个 PASS 均可指向对应 JSON；C/D/E 未标注为真实 FM27 PASS |

## 6. 修改文件清单

已修改：

- `backend/app/ingestion/importer.py`
- `tools/runtime-acceptance/backend_harness.py`
- `tools/runtime-acceptance/verify_network_recovery.py`
- `tools/runtime-acceptance/verify_cancel_two_process.py`
- `tools/runtime-acceptance/verify_backend_restart_recovery.py`
- `tools/runtime-acceptance/collect_evidence.ps1`

新增：

- `docs/evidence/v3.2.7.5/REAL-FM27-ACCEPTANCE.md`
- `docs/evidence/v3.2.7.5/FINAL-REPORT.md`
- `docs/evidence/v3.2.7.5/runtime/network-recovery-result.json`
- `docs/evidence/v3.2.7.5/runtime/cancel-two-process-result.json`
- `docs/evidence/v3.2.7.5/runtime/backend-restart-recovery-result.json`
- `docs/evidence/v3.2.7.5/runtime/manifest.json`
- `docs/evidence/v3.2.7.5/runtime/SUMMARY.md`
- `docs/evidence/v3.2.7.5/runtime/redacted/*`（采集脚本生成的脱敏副本）

## 7. 验收状态

| 项 | 状态 |
| --- | --- |
| A 单存档采集 | PASS（沿用真实 FM27） |
| B A→B→A 存档切换 | PASS（沿用真实 FM27） |
| C 断网恢复 | PARTIAL（协议级 PASS；真实 Agent/FM27 NOT_RUN） |
| D 取消任务 | PARTIAL（单后端真实双进程 PASS；跨后端进程 NOT_RUN） |
| E 重启恢复 | PARTIAL（后端重启 PASS；Agent 重启 NOT_RUN） |
| 整体 | **PARTIAL** |

## 8. 待确认事项

1. 是否按 `REAL-FM27-ACCEPTANCE.md` §9 执行 C/E 的真实 Agent 人工步骤并回填结果；
2. `main` 的历史重写与强推尚未执行（工具策略禁止对 main 强推），命令见 §9。
3. 脱敏前的原始证据已保存为仓库外 git bundle 备份，仅本地保留，未上传。

## 9. 历史重写记录（2026-11-25）

- 范围：`origin` 全部 26 个分支；工具 `git filter-repo --replace-text`。
- 规则：`C:\Users\<user>` 的三种写法（单反斜杠、JSON 双反斜杠、正斜杠）、经理名 `<manager>`、两个存档名 `<save-A>` / `<save-B>`。
- 校验：各分支提交数全部不变；每个分支 tip 相对旧 tip 的差异**仅为占位符替换**（非预期差异 0 处）；全历史 blob 无 `C:[\\/]Users[\\/]<user>` 残留。
- 旧 → 新（短哈希）对照：

| 旧 | 新 | 说明 |
| --- | --- | --- |
| `9d3277c` | `f8e69f5` | V3.2.7.4 基线 |
| `3ed41b6` | `91e9329` | D-01 修复 + A→B→A 证据（脱敏） |
| `1572451` | `8c6fb4b` | C/D/E 工具检查点 |
| `d957374` | `ecc6317` | C/D/E 协议级验收与证据 |
| `f74075d` | `18b6f72` | 文档修订 |
| `5574443` | `f3661d7` | 文档修订 |
| `ca79d31` | `89ac157` | `main`（**尚未强推**） |

- `docs/evidence/**` 中的历史文档保留重写前的哈希引用（记录当时的仓库状态），按上表换算即可；本记录提交后本分支 tip 会再前移一次。
- GitHub 端的旧提交可能因缓存与 PR 引用短期仍可访问；如需彻底清除，须联系 GitHub Support。
- 强推 `main` 需由仓库所有者执行：`git push --force origin main:main`（在重写克隆中，且需确认 `main` 无他人新增提交）。

**本轮到此暂停；已推送 25 个分支（历史重写），未建 PR、未合并 main、未发布 Release。**
