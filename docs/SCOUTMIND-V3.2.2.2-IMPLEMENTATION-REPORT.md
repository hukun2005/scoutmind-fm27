# ScoutMind FM27 V3.2.2.2 — 实施报告

- 基线：`main` `867dbe0`
- 分支：`codex/v3.2.2.2-stability`
- 日期：2026-11-23
- 真实 FM27：运行中（pid 105040，build 26620374，plugin 27.1）

## 1. 状态

| 任务 | 状态 | 说明 |
| --- | --- | --- |
| SM-074 真实轻量日期探测 | **BLOCKED** | 无验证过的日期偏移；`date` 返回 `DateUnavailable`，不猜偏移 |
| SM-075 文件完整性 | **PARTIAL** | SHA-256/大小校验器 + quarantine + Agent 导入前校验；正常/篡改测试通过 |
| SM-076 Agent 稳定性 | **PARTIAL** | 锁/暂停/恢复/状态有测试；故障矩阵未完整执行 |
| SM-077 Agent 独立测试 | **PASS（基础）** | xUnit 项目 5 项通过，接入 CI .NET job |
| SM-078 Playwright | **PARTIAL** | 保留 governance 2 项；新增 CI Playwright job；其余页面未扩展 |
| SM-079 采集监控 | **NOT_RUN** | 未新增质量指标/前端监控 |

## 2. SM-074 真实日期探测

- 现有 `FmDateProbe` 已检查进程、构建、插件、版本闸门和布局。
- 真实运行结果：
  - `state=DateUnavailable`
  - `errorCode=date_offset_not_verified`
  - build 26620374 / plugin 27.1 / layout FM27_1
- 原因：当前布局没有验证过的轻量 gameDate 字段；上游日期来自 my-team schedule，必须遍历球队/球员图。
- 按任务要求停止真实读取，未猜测偏移。**日期未变化时完整扫描次数为 0 的验收未达成。**

## 3. SM-075 完整性

新增 `ScanIntegrityValidator`：

- envelope/meta 存在性、大小、SHA-256、JSON、scan 对象、scan_id 一致性；
- Agent `SyncOneAsync` 导入前调用；
- 失败移动至 `queue/quarantine/<stem>-<timestamp>/`，保留 envelope、meta、manifest（错误码、哈希、大小、路径）；
- 不会把失败文件标记为 sent，不会删除原始文件。

测试：

- 正常配对通过；
- 篡改后 `size_mismatch`；
- 缺失 envelope `envelope_missing`；
- 其他失败路径代码存在，但完整矩阵（meta 缺失/JSON 损坏/scan_id 不一致/读写中修改）未全部覆盖。

## 4. SM-076/077 Agent

新增 `desktop-agent/tests/ScoutMind.Agent.Tests`（xUnit）：

1. `auto --pause` 解析；`auto` 缺少控制/间隔被拒绝；
2. CaptureStateStore 原子写入/读取；
3. CaptureControl 暂停/恢复；
4. CaptureLock 第二持有者失败、释放后可重新获取；
5. ScanIntegrityValidator 正常/篡改/缺失。

结果：**5 passed**。

未完成：双 Agent 真实进程并发、异常退出恢复、扫描中取消、数据库断开、磁盘不足等故障矩阵。

## 5. SM-078 Playwright

- 保留 `governance.spec.ts`（2 passed，本地 Chromium）。
- `.github/workflows/ci.yml` 新增 `playwright` job（npm ci → chromium → test:e2e）。
- 未新增 Dashboard/Players/Development/Transfers/Capture 测试；这些页面覆盖仍是 **NOT_RUN**。

## 6. 数据库

- 本轮无新 Migration。
- 真实库仍为 V3.2.2 head `f6a7b8c9d0e1`。
- SQLite/PostgreSQL 既有迁移验证通过；本轮无 schema 变更。

## 7. CI

- 待本分支推送后运行。
- 新增 Agent tests 与 Playwright job；不得只检查总状态。

## 8. 未完成/风险

1. **SM-074 核心目标 BLOCKED**：没有可验证的轻量日期来源，完整扫描仍无法跳过。
2. 完整性失败矩阵未覆盖全部情形； quarantine 恢复/清理策略未测试。
3. 并发锁只做了同进程双持有测试，未做双进程 auto 实测。
4. Playwright 只覆盖治理页；自动采集/球员/成长/转会未覆盖。
5. SM-079 监控未实现。
6. 未合并 main，未发布。

**结论：V3.2.2.2 不能标为完成。核心日期探测仍阻塞；其余为 PARTIAL。**
