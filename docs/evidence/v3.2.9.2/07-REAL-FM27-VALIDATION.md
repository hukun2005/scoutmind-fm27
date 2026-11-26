# V3.2.9.2 阶段 7 — 真实 FM27 验证

- 执行时间：2026-11-26（Asia/Shanghai）
- 环境：FM27 进程 pid `72012`，构建 `26620374`，插件 `27.1`，布局 `FM27_1`
- 存档目录：`C:\Users\hukun\Documents\Sports Interactive\Football Manager 27\games`
  - `hu kun-北京国安.fm`
  - `hu kun-大连英博.fm`
  - `hu kun-利兹联.fm`
  - `hu kun-利兹联 (v02).fm`
  - `hu kun-利兹联 (v03).fm`
  - `last save overwrite backup.fm`
- 操作边界：只读取进程与存档文件元数据；未写入、未移动、未删除任何存档；
  诊断状态文件写在 `%TEMP%`，不影响用户真实状态。

## 1. 自动解析（未指定文件）

命令：

```powershell
dotnet run --project live-reader/ScoutMind.Reader -c Release -- `
  save-identity --diagnostics --json --state "$env:TEMP\v3292-real-state.json"
```

实测结果（退出码 `3`，失败关闭）：

```json
{
  "status": "discovered",
  "ambiguous": true,
  "snapshot_eligible": false,
  "generation": 1,
  "confirmation_invalidated": false,
  "verify_requested": false,
  "verify_applied": false
}
```

- 识别到 3 个带稳定元数据的候选存档；
- 无法唯一确定当前存档 → `AMBIGUOUS_SAVE_FILES`；
- 不给当前指纹、不允许 Verified。

**结论**：真实环境确实存在“多存档无法判定当前存档”的场景；本版本按安全语义返回歧义，
不再用历史确认反向选择（旧行为会在这里返回旧存档指纹）。

## 2. 显式指定文件

命令（对 `hu kun-利兹联.fm`）：

```powershell
dotnet run --project live-reader/ScoutMind.Reader -c Release -- `
  save-identity --save-file "...\hu kun-利兹联.fm" --verify --diagnostics --json `
  --state "$env:TEMP\v3292-real-state-explicit.json"
```

实测结果（退出码 `3`）：

```json
{
  "status": "candidate",
  "current_save_confirmed": false,
  "limitations": ["CURRENT_SAVE_UNCONFIRMED"],
  "verify_applied": false,
  "generation": 1
}
```

诊断：

> `--verify 被拒绝：显式 --save-file 只能证明该文件自身的身份，不能证明它是当前加载存档（CURRENT_SAVE_UNCONFIRMED）。`

**结论**：显式路径不再能绕过身份校验，符合任务书 §5.4。

## 3. 真实 A/B/A 切档

| 项目 | 状态 |
| --- | --- |
| Save A 首次读取 | `NOT_RUN`（本次未在 FM27 内切档） |
| 切换到 Save B | `NOT_RUN` |
| 再切回 Save A | `NOT_RUN` |
| 切档后旧确认失效 | 由阶段 1/2 的自动化测试覆盖；真实环境 `NOT_RUN` |

原因：A/B/A 需要用户在 FM27 客户端内主动加载不同存档并告知执行者，本次执行环境
无法代替用户完成该操作。按任务书要求，**未执行即标 NOT_RUN，不得用单元测试冒充 PASS**。

## 4. 当前限制声明

- 当存档目录同时存在多个存档且没有任何文件被进程独占锁定时，系统返回
  `AMBIGUOUS_SAVE_FILES`，不会声称已完成“进程 ↔ 存档”绑定。
- 当只有一个候选文件时，系统按唯一文件解析，标记 `CurrentSaveConfirmed=true`，
  但仍缺少游戏内 `SAVE_ID / WORLD_ID`，最高只能到 `CANDIDATE`。
- 因此本版本的能力边界是：
  - **不发生错误 Verified / 不跨存档复用旧指纹**：已实现并有测试与真实读取证据；
  - **进程与存档的强绑定**：在无法获得运行时证据时明确标记未确认，不宣称完成。
