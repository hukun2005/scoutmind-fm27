# Phase 5：Native Reader 与 Desktop Agent 发布验收（V3.2.9.2）

- 验收对象：发布包 `live-reader/` 内的 `ScoutMind.LiveReader.exe`、`ScoutMind.Agent.exe`
- 真实环境：FM27 27.1（Steam appId 4530370，build 26620374，`game_plugin.dll` 27.1.0+2505117），进程 PID 72012
- 本轮未新增任何 Reader 功能、未修改内存布局

## 1. 发布文件检查

| 项目 | 结果 |
| --- | --- |
| 读取器文件 | `ScoutMind.LiveReader.exe`，37,977,302 字节（自包含单文件 win-x64） |
| 代理文件 | `ScoutMind.Agent.exe`，38,053,530 字节（自包含单文件 win-x64） |
| 运行依赖 | 不需要目标机安装 .NET（self-contained） |
| compatibility.json | 随包复制，2 条条目（1 verified / 1 candidate） |
| scanner.sample.json | 随包复制（仅外部扫描器场景使用） |
| 版本闸门一致性 | `Diag configcheck` 退出码 0：compatibility registry / verified-versions / LayoutResolver 一致 |
| 错误码 | Agent 帮助输出定义 0/2/3/4/5/6/64/65，与实测一致 |

## 2. 真实 FM27 验收（逐项）

| 验证项 | 命令/证据 | 结果 |
| --- | --- | --- |
| 游戏进程检测 | `ScoutMind.LiveReader.exe status --json` | PASS：`pid=72012`、`fm.exe`、安装目录正确 |
| 游戏版本检测 | 同上 | PASS：`buildId=26620374`、`gameVersion=27.1.0`、插件 `27.1.0+2505117` |
| 兼容性判定 | 同上 | PASS：`state=Compatible`、`matchedRule=appId;buildId;pluginProductVersion` |
| probe | `ScoutMind.LiveReader.exe probe --json` | **PASS**：`passed=true`，22,647 ms，布局 `FM27_1`，闸门字段 Verified |
| Reader 启动 | 两次执行均正常退出、无崩溃 | PASS |
| Agent 通信（状态） | `ScoutMind.Agent.exe status --json` | PASS：复用同目录 Reader，识别同一构建 |
| Agent 通信（后端） | `agent.json` 指向发布包后端 `http://127.0.0.1:8020/api/v1`，`diagnostics --json` | PASS：`backend_reachable=true`、HTTP 200 |
| 当前存档读取 | `ScoutMind.Agent.exe scan --sync --json` | **PASS**：读取 44,144 名球员、32,796 名职员；上游 dump 87,854,283 字节 |
| 数据导入 | 上传返回 201，任务 #1 最终 `status=succeeded`，`player_count=44144` | **PASS**：`GET /players` → `total=44144` |
| 重复扫描 / 重复导入 | 对同一 scan 再次 `sync` | **PASS**：HTTP 201，`duplicate=true`，未重复写入，任务归档到 `sent/` |
| A/B/A 存档切换 | 需要在游戏内主动切换存档 | **NOT_RUN（本轮产物）** — 本任务书要求不伪造真实验收；同一 Reader/后端代码在 PR #14 的真实 A/B/A 已 PASS（`docs/evidence/v3.2.9.2/`） |
| 存档隔离（真实双存档） | 同上 | **NOT_RUN（本轮产物）**；单存档场景下 `fm_save_id` 隔离由测试覆盖 |
| 读取失败处理 | 候选构建拒绝测试（见 §3） | PASS |
| 游戏关闭后的进程清理 | 需要关闭用户正在运行的 FM27 | **NOT_RUN**：不可在不影响用户游戏的情况下执行 |

## 3. 未验证构建的安全闸门（真实执行）

把发布包复制到临时目录，将 `compatibility.json` 中该构建的 `status` 改为 `candidate` 后运行：

```
ScoutMind.LiveReader.exe status --json
"state": "Unknown",
"message": "候选兼容项，需本机 probe 验证",
exit=3
```

结论：未验证构建不会被错误标记为兼容，也不会执行读取。

## 4. 已知限制（真实产生，非缺陷）

- 扫描时提示「存档身份未通过安全门（discovered），本次按无上下文上传」：当前存档尚未在 ScoutMind 内确认身份，导入按无上下文处理；需要多存档隔离时应先在界面完成存档身份确认。这是既有设计，不是本次回归。
- 上游 dump 不含转会历史、逐场统计、俱乐部主队字段：对应模块显示已有数据或标注缺失，不做推断。
- 44,144 名球员的导入在单机上约 11 分钟（CPU 密集），期间后端保持可访问（`GET /imports`、`/health` 正常响应）。

## 5. 结论

发布包中的 Reader/Agent 与真实 FM27（build 26620374）匹配，探测、扫描、导入、去重全链路通过；未验证构建被拒绝。A/B/A 与游戏关闭清理未在本轮产物上重跑，已如实标记。

状态：**PASS（A/B/A 与进程清理标记 NOT_RUN）**
