# ScoutMind FM27 V3.2.6 多存档报告

**自动化：既有用例覆盖；真实切换：NOT_RUN。**

## 1. 数据隔离现状

按 `fm_save_id` 分区：`player_instances`、`player_snapshots`、`unresolved_player_candidates`、
`unresolved_player_observations`、`import_jobs`、`capture_runs`。跨存档访问返回 404。

## 2. 自动化证据

| 用例 | 位置 |
| --- | --- |
| 同一 scan 跨两个存档导入互不覆盖 | `backend/tests/test_p1_security.py` |
| Unresolved 候选/观察按存档隔离 | `backend/tests/test_unresolved_*` |
| ImportJob 按 owner/save 过滤 | `backend/tests/test_import_jobs_api.py` |

## 3. 未实现

- SaveSwitchDetector（NoSave/SaveDetected/SaveVerified/SaveSwitching/SaveChanged）；
- 存档文件指纹或游戏内 ID 的复合身份；
- Worker 执行期间切换存档的保护（没有 Worker）。

## 4. 真实验收

只有一个真实存档，第二个存档无法伪造。真实双存档切换 **NOT_RUN**；
不得用两个 Mock `save_id` 冒充。

## 5. 结论

程序级隔离有自动化证据；真实切换未验证，发布说明必须写明限制。
