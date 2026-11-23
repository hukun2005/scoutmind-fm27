# ScoutMind FM27 V3.2.2.4 — 日期发现报告

- 分支：`codex/v3.2.2.3-date-discovery`
- 真实 FM27：pid 105040，build 26620374，plugin 27.1
- 已保存界面日期样本：A=2026-08-09、B=2026-08-10、C=2026-08-11

## 1. 样本状态

| 样本 | 界面日期 | 截图 | 内存样本 |
| --- | --- | --- | --- |
| A | 2026-08-09 | `docs/evidence/fm27-date-2026-08-09.png` | **无** |
| B | 2026-08-10 | `docs/evidence/fm27-date-2026-08-10.png` | **无** |
| C | 2026-08-11 | `docs/evidence/fm27-date-2026-08-11.png` | **无** |

截图是用户界面证据，不是内存采样；不能用于确认内存地址。

## 2. DateDiscovery 工具

未实现 `ScoutMind.DateDiscovery` 的差分采集器。原因：

- 当前 probe 仍因 14 个哨兵 UID 被拒绝；
- 没有可消费的 team/manager 会话指针；
- 没有 A/B/C 内存采样，无法进行差分；
- 不猜测偏移。

## 3. 精确日期 / 赛程代理

- 精确内存时钟：**BLOCKED**；
- next_match 代理：**NOT_RUN**；
- 未把 `next_match_date` 写成 `game_date`；
- `date --json` 仍返回 `DateUnavailable`。

## 4. 下一步

1. 先解决 OBJ_DUNI 的 14 个哨兵对象语义；
2. 实现 DateDiscovery 采样器并采集 A/B/C 内存；
3. 重载/重启验证；
4. 只有 Verified 来源才能接入 `IFmDateProbe`；
5. 在此之前自动采集保持扫描后日期 fallback。
