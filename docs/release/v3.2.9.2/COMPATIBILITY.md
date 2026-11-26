# ScoutMind FM27 V3.2.9.2 — FM27 兼容性

## 已验证组合

| 项 | 值 |
| --- | --- |
| Steam appId | `4530370` |
| 游戏版本 | `27.1.0` |
| Steam build | `26620374` |
| `game_plugin.dll` | `27.1.0+2505117` |
| 内存布局 | `FM27_1` |
| 验证状态 | `verified`（`live-reader/compatibility.json`） |

本组合在本机完成：

- `status` → `Compatible`；
- `probe` → `passed=true`；
- `scan` → 读取 44,144 名球员、32,796 名职员；
- 导入 → 44,144 名球员，重复上传返回 `duplicate=true`。

## 未验证组合（会被拒绝）

| Steam build | 插件版本 | 状态 |
| --- | --- | --- |
| `26577676` | `27.0.1+2503222` | `candidate` |

读取器对 `candidate` 返回：

```
"state": "Unknown"
"message": "候选兼容项，需本机 probe 验证"
exit=3
```

不会执行读取，也不会把未知布局当作已验证布局使用。

## 兼容性判定规则

1. 同时匹配 `appId`、`buildId`、`pluginProductVersion` 三者才算命中；
2. 只有 `status=verified` 的条目允许 `probe` 与 `scan`；
3. 游戏升级后 build 会变化，需要重新验证并更新 `compatibility.json`；
4. 读取器失败不会写坏数据库：失败发生在导入之前，已有数据不受影响。

## 已知数据边界

- 上游导出不包含转会历史、逐场统计、主执教俱乐部等字段，对应模块会显示为缺失或需手动配置，不做推断；
- 存档身份未确认时，扫描按无上下文上传；需要多存档隔离时先在界面完成身份确认。
