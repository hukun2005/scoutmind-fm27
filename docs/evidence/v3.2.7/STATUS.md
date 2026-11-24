# V3.2.7 真实验收证据状态

本目录只保存**实际执行并捕获**的命令输出。没有执行的真实测试不会生成占位文件，统一在本文标记 `NOT_RUN`。

## 已执行

| 项目 | 文件 | 结果 |
|---|---|---|
| `save-identity --diagnostics --json`（同一进程，第一次） | `identity-live-run-1.json` | `status=discovered`、`ambiguous=true`、`snapshot_eligible=false` |
| `save-identity --diagnostics --json`（同一进程，第二次） | `identity-live-run-2.json` | 与第一次相同的会话键，证明同进程会话稳定 |
| `world-date --diagnostics --json` | `world-date-live.json` | `status=heuristic`，候选日期 2026-11-07，引用链 `chain:gp:0x586B520:date+0x7F4` |
| 环境信息 | `environment.json` | Build 26620374 / Plugin 27.1 |

## A/B 双存档与重启一致性（2026-11-24 23:54–23:58 实测）

命令均为 `ScoutMind.LiveReader.exe save-identity --diagnostics --json`，证据与校验和见 `ab-switch/`。

| 场景 | 文件 | 状态 | 指纹 | 退出码 |
|---|---|---|---|---|
| 目录内两个存档，自动识别 | `ab-switch/01-auto-two-saves.json` | `discovered`（`ambiguous=true`） | `si:v1:unresolved:26620374` | 3 |
| 显式绑定存档 A（`hu kun-北京国安.fm`） | `ab-switch/02-save-a-verified.json` | `verified`（`kind=user_confirmed`） | `si:v1:file:b887415ab5…67418083` | 0 |
| 显式绑定存档 B（`hu kun-大连英博.fm`，新状态文件） | `ab-switch/03-save-b-candidate.json` | `candidate` | `si:v1:file:ab0bd795…672665` | 3 |
| 用 A 的已确认状态探测 B | `ab-switch/04-save-b-conflict-with-a-state.json` | `conflict`（“用户确认的存档指纹与当前文件证据不一致”） | 同 B | 3 |
| 冲突后再探测 A | `ab-switch/05-save-a-recovered.json` | 恢复 `verified`（`verify_applied=false`） | 同 A | 0 |
| 重启前基线 | `ab-switch/06-save-b-restart-before.json` | `candidate`，会话键 `58416:2026-11-24T14:24:58.7744838Z:26620374` | 同 B | 3 |
| 重启后复测 | `ab-switch/07-save-b-restart-after.json` | `candidate`，会话键 `66972:2026-11-24T15:57:31.1218361Z:26620374` | 同 B（**完全一致**） | 3 |

重启一致性结论：同一存档文件在进程重启后指纹不变（身份不依赖 PID、启动时间或内存地址），会话键随进程正确变化；文件大小 31,434,197 字节、创建时间 23:55:24、修改时间 23:55:25 在重启前后均未变化。`02` 与 `05` 输出逐字节相同（SHA256 一致），说明自愈路径可复现。

校验和：`ab-switch/SHA256SUMS.txt`。

## save_context 跨存档隔离联调（真实后端，2026-11-25 00:02 CST）

后端以独立 SQLite 库（先 `alembic upgrade head` 全量迁移）在 `127.0.0.1:8017` 启动，全部场景用真实 HTTP 请求执行。存档 A/B 通过 `POST /api/v1/saves` 创建；身份与会话按真实指纹（A=`si:v1:file:b887415ab5…67418083`、B=`si:v1:file:ab0bd795…672665`，Build 26620374）落库——后端目前没有创建身份的 HTTP 接口（身份由 Reader 产生，Phase 6 才由 Agent 上报），因此这两类行由脚本直接写入该临时库。

| 场景 | 请求 | 结果 |
|---|---|---|
| S1 跨存档身份 | B 的存档 + A 的 identity | 409 `save_context_mismatch` |
| S2 身份不存在 | A 的存档 + identity=999999 | 409 `save_context_mismatch` |
| S3 未验证身份 | B 的存档 + B 的 candidate identity | 409 `save_identity_unverified` |
| S4 冲突身份 | A 的存档 + conflict identity | 409 `save_context_mismatch` |
| S5 会话属于其他存档 | A 的存档 + A 的身份 + B 的会话 | 409 `save_context_mismatch` |
| S6 旧会话已失效 | B 的存档 + 已 invalidated 会话 | 409 `save_session_invalidated` |
| S7 切换中会话 | B 的存档 + switching 会话 | 409 `save_switch_in_progress` |
| S8 会话 build 不一致 | A 的存档 + A 的身份 + build=99999999 会话 | 409 `save_context_mismatch` |
| S9 未声明上下文（历史流程） | A 的存档，无身份/会话参数 | 201（旧行为保持） |
| S10 已验证上下文导入 | A 的存档 + A 的身份 + A 的 verified 会话 | 201，`job_id=2` |
| S11 采集登记：失效会话 | B 的存档 + invalidated 会话 | 409 `save_session_invalidated` |
| S12 采集登记：切换会话 | B 的存档 + switching 会话 | 409 `save_switch_in_progress` |
| S13 采集登记：跨存档身份 | B 的存档 + A 的身份 | 409 `save_context_mismatch` |
| S14 采集登记：已验证上下文 | A 的存档 + A 的身份 + 会话 | 201，`capture_id=1` |

写入审计：S10 的导入任务记录 `save_identity_id=1` / `save_session_id=1`，S14 的采集记录同样带上这两个归属；全部拒绝请求之后，存档 B 下 `ImportJob` 数为 0（隔离失败没有残留写入）。

证据：`save-context/live-http.json`（请求/响应原文、环境与断言）、`save-context/server-access.log`（uvicorn 访问日志，含每条 409/201）、`save-context/SHA256SUMS.txt`。

## 关键事实

- 上一轮判定为 `ambiguous` 的 3 个候选文件（108,969,104 / 107,268,485 / 103,998,391 字节）已于 2026-11-24 23:46:18–23:46:36 被移入回收站，原路径 `...\Football Manager 27\games\` 下已无对应文件；本轮用新存档重做，故不再受该状态影响。
- FM27 进程：先为 PID 58416（Build 26620374、插件 27.1），重启后为 PID 66972；两者 `session_key` 不同、存档指纹相同。
- `verified` 不等于可自动快照：`02`/`05` 中 `snapshot_eligible=false`、`automatic_snapshot_enabled=false` 保持成立，自动快照仍关闭。
- 冲突状态会写入状态文件，但不会清除 `userConfirmedFingerprint`；再次探测 A 即按已存确认恢复 `verified`，无需重新 `--verify`。

## NOT_RUN（不得写成 PASS）

| 任务书要求 | 文件 | 原因 |
|---|---|---|
| 采集期间切换存档 | `save-switch-during-capture.json` | 需要 Agent 在游戏内实际切换存档并触发采集；本轮只联调了后端接口，未启动 Agent |
| 导入进行中会话被并发失效（`final_guard` 真实竞态） | — | 需要可控的长导入窗口与并发切换，本轮只由 `test_save_isolation.py` 单元测试覆盖，未做真实竞态 |
| PostgreSQL 16 迁移 | — | 本机无 PG16 实例；SQLite fresh upgrade + round-trip + `check_migration_safety.py` 已通过 |
| GitHub Actions 最新结论 | — | 分支已推送并合并至 main（`738875c`）；本次未重新核对 run 结论，不记 PASS |

## 复现步骤（本轮实际执行路径）

1. 游戏内“另存为”生成存档 A，运行：
   `ScoutMind.LiveReader.exe save-identity --save-file <A> --diagnostics --json --state <状态文件>`
2. 用户确认界面生涯与 A 一致后，加 `--verify` 升为 `verified`。
3. 游戏内另存为 B（不同俱乐部），目录同时存在两个 `.fm` 时先跑自动识别（应为 `ambiguous=true`），再分别用 `--save-file` 绑定 A/B 比较指纹。
4. 关闭游戏、重新启动并载入 B，重复第 1 步；比较重启前后指纹是否一致、`session_key` 是否变化。

在取得“采集期间切换”证据之前，涉及自动采集的结论仍不得记为 PASS；自动快照继续关闭。
