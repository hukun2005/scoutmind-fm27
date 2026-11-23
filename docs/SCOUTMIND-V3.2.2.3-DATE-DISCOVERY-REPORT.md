# ScoutMind FM27 V3.2.2.3 — 日期发现实施报告

- 分支：`codex/v3.2.2.3-date-discovery`
- 基线：`de4b64c`（V3.2.2.2 稳定性补强）
- 日期：2026-11-23
- 真实 FM27：运行中，pid 105040，build 26620374，plugin 27.1

## 1. 状态

| 任务 | 状态 | 说明 |
| --- | --- | --- |
| SM-080 世界时钟发现工具 | **BLOCKED** | 未建立可验证的精确日期内存来源；无用户日期推进样本 |
| SM-081 球队赛程轻量探测 | **NOT_RUN** | 需要完整扫描取得 team 地址并验证缓存；未实现 |
| SM-082 指针缓存/会话安全 | **NOT_RUN** | 无已验证 team 指针可缓存 |
| SM-083 智能自动采集 | **PARTIAL（沿用）** | 现有 Agent 仍是扫描后日期判断；未改为两级探测 |
| SM-084 日期来源注册 | **NOT_RUN** | 无 Verified 来源可注册 |
| SM-085 真实环境验收 | **BLOCKED** | 无法进行 Sample A/B/C 日期推进采集；当前无精确来源 |

## 2. 真实证据

`ScoutMind.LiveReader.exe date --json`：

```json
{
  "state": "DateUnavailable",
  "gameDate": null,
  "build": "26620374",
  "pluginVersion": "27.1",
  "layoutVersion": "FM27_1",
  "errorCode": "date_offset_not_verified"
}
```

- 未启动完整 dump；
- 未读取球员数据库；
- 未猜偏移；
- 未把 next_match_date 标成 game_date。

## 3. 上游日期链分析

```text
Manager → Contract → CON_TEAM → Team
  → TEAM_SCHEDULE(0xA0)
  → SCHED_NEXT_MATCH(0x94 / 0x18)
  → next_match_date
```

该值最多作为赛程变化信号，不是精确世界时钟。`DiagMyTeam` 只在完整扫描后产生，当前没有轻量协议或缓存。

## 4. 未完成

1. 没有 `ScoutMind.DateDiscovery` 工具和 A/B/C 差分实验；没有用户确认的界面日期样本。
2. 没有完整扫描 → team 地址缓存 → schedule 轻量读取链路。
3. 没有会话指纹/指针失效验证。
4. 没有日期来源注册表。
5. 没有真实日期推进（Sample A/B/C）证据。

## 5. 下一步（需真实游戏操作）

1. 在 FM27 内记录界面日期（Sample A）；
2. 推进一天，记录 Sample B；再推进一天，记录 Sample C；
3. 用受控 ReadProcessMemory 差分工具比较候选地址；
4. 重载/切换存档/重启验证；
5. 只有通过多日验证的精确源才注册 Verified；
6. 在此之前，next_match 只能作为代理信号，正式 game_date 保持未知。

## 6. 结论

V3.2.2.3 的精确世界时钟发现 **BLOCKED**；赛程轻量探测与缓存未实现。没有伪造日期或把下一场比赛日期写入正式快照。未合并 main，未发布。
