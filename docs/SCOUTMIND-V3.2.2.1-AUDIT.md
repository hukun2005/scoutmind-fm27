# ScoutMind FM27 V3.2.2.1 — 当前实现审计

- 基线：`main` `96e88ff`，干净工作区
- 分支：`feature/v3.2.2.1-core`
- 真实 FM27：运行中，pid 105040，build 26620374 / plugin 27.1
- 审计日期：2026-11-23

## 1. 现状

| 能力 | 现状 |
| --- | --- |
| ReaderStatus 游戏日期 | **不提供**；`ReaderStatus` 只有进程/构建/插件/兼容性 |
| 游戏日期来源 | 完整 scan 后上游 dump 的 `meta.gameDate`（team schedule + DateVotes） |
| 轻量内存读取 | 无已注册的日期偏移；Layout 没有全局日期字段 |
| 版本闸门 | `VersionGate` + `LayoutResolver` 已存在，必须复用 |
| CaptureStateStore | 保存 saveName/lastGameDate/lastScanId/status/failures；无 pause/control |
| ScanQueue | 文件目录 scans/pending/sent/duplicates；无并发锁 |
| ScanWriter | 原子 tmp+rename；无 SHA-256 |
| Agent 暂停/恢复 | 无 |
| 进程退出恢复 | 启动时重试 pending；无完整扫描中恢复 |
| Agent 测试项目 | 不存在 |
| Playwright | 只有 Governance 2 个 smoke |

## 2. 关键结论

1. **不能安全读取轻量日期**：当前布局没有验证过的 gameDate 偏移；上游日期来自 my-team schedule，需要扫描球队/球员图。按任务约束，禁止猜测偏移，因此真实探测必须返回 `DateUnavailable`。
2. 日期接口/契约、版本闸门、诊断可以先实现并测试；真实 `DateDetected` 保持 **BLOCKED**。
3. 自动采集的暂停/恢复、并发锁、控制文件、SHA-256 可以独立实现。
4. 现有 `auto` 仍是“扫描后看 game_date”，不是轻量预检；在日期探测不可用时不能宣称低成本自动采集。

## 3. 本轮计划

- 新增 `IFmDateProbe` / `FmDateProbeResult` / `FmDateProbe`，CLI `date --json`；真实返回 DateUnavailable；
- Agent `auto --pause/--resume/--status`、`agent.lock`、control JSON；
- ScanWriter 增加 SHA-256/大小到 meta；
- 保留旧的扫描后日期判断作为 DateUnavailable 的显式 fallback；
- 不修改真实库；不伪造 DateDetected；真实探测验收 NOT_RUN/BLOCKED。
