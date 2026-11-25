# ScoutMind FM27 V3.2.6 预发布审计

日期：2026-11-24 · 分支 `codex/v3.2.6-release-candidate`（基于 `f8c740e`）
环境：FM27 27.1.0 / build 26620374 / 插件 27.1

## 1. 仓库真实状态（开场核实）

| 项 | 值 |
| --- | --- |
| `origin/main` | `7043a1a`（自 V3.2.2 起未移动） |
| PR #1/#2/#3/#4/#5 | 全部 OPEN，逐层叠加（main ← v3.2.2.8 ← v3.2.3 ← v3.2.4 ← v3.2.5 ← v3.2.5.1） |
| 最近 CI | V3.2.5.1 run `45390354361` 六 job 全绿 |
| V3.2.6 基线 | `f8c740e`（模块边界 + 静态根工具 + date-read） |

## 2. 日期读取链的真实状态

| 层 | 实现 | 状态 |
| --- | --- | --- |
| 进程检测 / 版本闸门 | `GameBuildDetector` / `VersionGate` | 可用 |
| 内存读取 | `WinMemorySource`（只读，堆区 1617 个） | 可用 |
| 模块边界 | `WinMemorySource.Bounds`（game_plugin 392 MB / GameAssembly） | 可用 |
| 候选扫描 | `DateDiscovery`（按值匹配） | 可用，但命中量大 |
| 签名定位 | `WorldDateLocator`（日期+参考日+哨兵+两个 0） | 可用，142 条命中 |
| 启发式解析 | `WorldDateResolver`（最新日期 + 参考间隔 30..400 天 + 三重复读） | **本轮新增** |
| 模块静态根 | `StaticDateScan` | 只找到日历对象；时钟无模块引用 |

真实证据（本分支之前）：10-26 / 10-31 / 11-06 三次与界面一致；跨重启后在新地址重新找到同一结构（日期 11-06）。
但“最新日期”规则只是启发式，尚未在多日期上完整验证。

## 3. 多存档

- 数据模型按 `fm_save_id` 分区（instances / snapshots / unresolved / import_jobs）；
- 跨存档访问返回 404；自动化测试已有（`test_p1_security`、`test_unresolved_*`）；
- **真实双存档验收 NOT_RUN**（只有一个存档）；存档切换检测器未实现。

## 4. Worker

`backend/app` 全目录没有 worker / lease / heartbeat / cancel 实现。现有缓解：`asyncio.to_thread`、`409`、
启动恢复、Agent 超时核验。**持久化队列/进度/取消重试 NOT_RUN。**

## 5. 发布工程

- `scripts/publish-windows.ps1` 只发布 Reader + Agent（自包含单文件）；
- **没有安装器**（无 WiX/Inno/MSIX），没有后端 Python 运行时打包，没有首次启动向导；
- 前端构建产物由 `npm run build` 生成，未与安装器集成。

## 6. 测试现状

| 套件 | 结果 |
| --- | --- |
| FMReader 自测 | 156/156（本轮新增 5 例世界日期解析） |
| Reader 自测 | 53/53 |
| Backend | 497 收集 / 494 通过 / 3 跳过（V3.2.4 基线，本轮未改后端） |
| Playwright | 9/9（既有；本轮未新增） |

## 7. 发布阻塞项

1. 日期定位只有启发式，缺 11-07/11-08 与再次跨重启的真实验证；
2. 没有持久化 Worker，自动快照无法闭环；
3. 没有安装器；
4. 真实多存档未验证；
5. Playwright 未覆盖自动采集/存档页面。

## 8. 建议顺序

日期定位验证 → 自动快照开关（默认关） → Worker → 安装器 → Playwright → RC 清单。
