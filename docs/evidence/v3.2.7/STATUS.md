# V3.2.7 真实验收证据状态

本目录只保存**实际执行并捕获**的命令输出。没有执行的真实测试不会生成占位文件，统一在本文标记 `NOT_RUN`。

## 已执行

| 项目 | 文件 | 结果 |
|---|---|---|
| `save-identity --diagnostics --json`（同一进程，第一次） | `identity-live-run-1.json` | `status=discovered`、`ambiguous=true`、`snapshot_eligible=false` |
| `save-identity --diagnostics --json`（同一进程，第二次） | `identity-live-run-2.json` | 与第一次相同的会话键，证明同进程会话稳定 |
| `world-date --diagnostics --json` | `world-date-live.json` | `status=heuristic`，候选日期 2026-11-07，引用链 `chain:gp:0x586B520:date+0x7F4` |
| 环境信息 | `environment.json` | Build 26620374 / Plugin 27.1 |

关键事实：

- FM27 进程存在（Build 26620374）。
- 候选存档文件多于一个，无法唯一确定当前存档，因此身份停在 `DISCOVERED`，`ambiguous=true`。
- 自动快照总开关 `automatic_snapshot_enabled=false`，`snapshot_eligible=false`。
- 两次运行得到完全相同的 `session_key`（`PID:进程启动时间:Build`），说明会话键在同一进程内稳定；PID 不作为存档身份。
- 本轮 `world-date` 为 `heuristic`，未达到 `restart_verified`，因此日期安全门同样保持关闭。

## NOT_RUN（不得写成 PASS）

| 任务书要求 | 文件 | 原因 |
|---|---|---|
| 同一存档重启后身份一致 | `save-a-restart.json` | 当前环境身份未解析（`si:v1:unresolved:*`），无法证明“同一存档”跨重启一致 |
| 双存档 A/B 初始识别 | `save-a-initial.json` / `save-b-initial.json` | 未提供第二个真实存档材料 |
| 同一进程切换存档 | `save-switch.json` | 需要用户手动载入 Save B |
| 采集期间切换存档 | `save-switch-during-capture.json` | 自动采集当前被身份安全门阻断，且需要用户手动切换 |
| 身份对比报告 | `save-identity-comparison.json` | 依赖上述 A/B 数据 |
| 安全门真实场景输出 | `snapshot-gate.json` | 依赖身份 VERIFIED 的真实场景 |
| PostgreSQL 16 迁移 | — | 本机无 PG16 实例；SQLite fresh upgrade + round-trip + `check_migration_safety.py` 已通过 |
| GitHub Actions（本分支） | — | 分支尚未推送，未触发 CI；不得记为 PASS |

## 用户复现步骤（取得 A/B 证据）

1. 启动 FM27 并载入存档 A，运行：
   `ScoutMind.LiveReader.exe save-identity --diagnostics --json --state <状态文件>`
2. 完全退出游戏，再启动并重新载入 A，重复第 1 步；比较两次指纹是否一致。
3. 退出存档 A，在同一进程载入存档 B，重复第 1 步；此时指纹应变化、旧会话应失效。
4. 将输出保存为本目录对应的 JSON 文件名，并更新 `environment.json` 的 `captured_at`。

在取得上述真实证据之前，ScoutMind 的自动采集/自动快照必须保持关闭。
