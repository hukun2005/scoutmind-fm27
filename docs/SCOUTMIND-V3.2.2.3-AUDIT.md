# ScoutMind FM27 V3.2.2.3 — 日期发现审计

- 基线：`codex/v3.2.2.2-stability` `de4b64c`（V3.2.2.1 main + V3.2.2.2 稳定性补强）
- 分支：`codex/v3.2.2.3-date-discovery`
- 真实 FM27：运行中，pid 105040，build 26620374，plugin 27.1
- 日期：2026-11-23

## 1. 现有日期链路

- `FmDateProbe` 检查进程/build/plugin/VersionGate/LayoutResolver，但当前布局没有验证过的日期字段，返回 `DateUnavailable`。
- 上游 `Dumper.FindGameDate` 从 `DiagMyTeam + TEAM_SCHEDULE(0xA0) + SCHED_NEXT_MATCH(0x94/0x18)` 读取“下一场比赛日期”，不是精确世界时钟。
- `DiagMyTeam` 只有在完整 dump 扫描球队/经理图后才可得；没有持久化或轻量入口。
- 因此现有轻量路径不能获得真实 game_date，Agent 仍靠完整扫描后的 dump meta。

## 2. 真实探测证据

`ScoutMind.LiveReader.exe date --json` 在真实 FM27 上返回：

```json
{
  "state": "DateUnavailable",
  "gameDate": null,
  "build": "26620374",
  "pluginVersion": "27.1",
  "layoutVersion": "FM27_1",
  "errorCode": "date_offset_not_verified",
  "diagnostics": [
    "选中 fm.exe pid 105040...",
    "当前布局没有经过验证的轻量游戏日期字段；未读取完整存档，拒绝猜测偏移。"
  ]
}
```

结论：没有可验证的精确日期来源；不得把 next_match 日期当世界时钟。

## 3. 赛程代理的阻塞

- 要复用 `DiagMyTeam`，必须先完整扫描并取得 team 地址；
- 当前 dump 没有把 `DiagMyTeam` 写入可消费的协议字段，Agent 也没有会话指针缓存；
- 因此 SM-081/SM-082 需要新增“完整扫描发现 team 地址 → 会话缓存 → 只读 schedule 探测”的链路，且必须真实验证指针在进程重启/存档切换后失效。
- 未实施，避免在没有真实证据时写入 next_match 为 game_date。

## 4. 安全结论

- 不猜偏移、不写进程、不修改存档；
- next_match_proxy 只能作为触发信号，不能写正式 game_date；
- 真实精确时钟验收 **BLOCKED**，需要用户按任务书推进游戏日期并采集 Sample A/B/C，或先验证 team 指针缓存。
