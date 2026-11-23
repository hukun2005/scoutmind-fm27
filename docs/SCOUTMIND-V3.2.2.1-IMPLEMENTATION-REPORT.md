# ScoutMind FM27 V3.2.2.1 — 实施报告

- 基线：`main` `96e88ff`
- 分支：`feature/v3.2.2.1-core`
- 日期：2026-11-23
- 真实 FM27：运行中（pid 105040，build 26620374，plugin 27.1）

## 1. 状态

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| 轻量日期契约/CLI | **PASS** | `IFmDateProbe`、`FmDateProbeResult`、`date --json` |
| 真实轻量日期检测 | **BLOCKED** | 当前布局无验证过的 gameDate 偏移，返回 `DateUnavailable` |
| 自动采集暂停/恢复/状态 | **PASS（本地）** | `auto --pause/--resume/--status` + control JSON |
| 并发锁 | **PARTIAL** | 文件独占锁实现；未做双进程自动化测试 |
| SHA-256/文件大小 | **PASS** | ScanWriter 写入 meta |
| 导入前校验 | **NOT_RUN** | Agent 尚未读取 meta 校验后拒绝 |
| 启动恢复 | **PARTIAL** | pending 文件重试；未校验/隔离损坏文件 |
| 故障矩阵 | **NOT_RUN** | 未做扫描中退出/磁盘不足等自动化 |
| Playwright | **PARTIAL** | 仅既有 Governance 2 用例 |
| 真实数据库 | 未改 schema（沿用 V3.2.2 head） | 无新迁移 |

## 2. 关键实现

### 日期探测
- `live-reader/ScoutMind.Contracts/DateProbeContracts.cs`
- `live-reader/ScoutMind.FMReader/Engine/FmDateProbe.cs`
- `ScoutMind.LiveReader.exe date --json`
- 真实结果：`state=DateUnavailable`，`errorCode=date_offset_not_verified`，明确未读取完整 dump、未猜测偏移。
- 因日期不可用，Agent 仍保留“扫描后读 game_date”的 fallback；因此**完整扫描次数没有降低**，不能写成性能验收通过。

### 暂停/恢复/锁
- `CaptureControl` control JSON；`auto --pause/--resume/--status`。
- `CaptureLock` 使用 `FileShare.None`，进程退出由 OS 释放。
- auto 主循环检查 paused，不删除待处理文件。

### 文件完整性
- `ScanWriter` 计算信封 SHA-256/字节数写入 meta；
- 写入顺序：tmp → flush/close → 原子 rename。

## 3. 测试

| 项目 | 结果 |
| --- | --- |
| Reader integration | 46 passed |
| .NET build | PASS |
| CLI pause/resume/status | 手工执行 PASS |
| 真实 date probe | DateUnavailable（BLOCKED） |
| 后端 | 未因本轮改动跑全量；无后端改动 |
| Playwright | 未重跑；仅既有 2 用例 |

## 4. 未完成/阻塞

1. **核心目标未达成**：没有轻量日期偏移，无法在日期未变化时跳过完整扫描；真实自动采集仍是扫描后判断。
2. 导入前 SHA-256 校验、损坏文件隔离未实现。
3. 并发锁无双 Agent 自动化测试。
4. 故障恢复矩阵未执行。
5. Playwright 未扩展其他页面/自动采集。
6. 没有 Agent 测试项目。

## 5. 结论

接口、CLI、暂停/恢复、锁和 SHA-256 基础已落地；但“低成本日期探测”的真实验收为 **BLOCKED**，不能把 V3.2.2.1 标为完成。未合并 main。
