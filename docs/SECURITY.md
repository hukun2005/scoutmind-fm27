# 安全与合规

## 1. 本地优先

- 后端默认绑定 `127.0.0.1:8000`，不监听局域网或公网；如需暴露必须自行加反向代理与鉴权，并明确风险。
- 前端开发服务器同样只监听本机，`vite` 代理 `/api` 到 `http://127.0.0.1:8000`。
- 数据存储在本地 SQLite（默认 `backend/data/scoutmind.db`）或自建 PostgreSQL；不上传云端。

## 2. 本地鉴权

设置 `SCOUTMIND_API_TOKEN` 后，除 `/api/v1/health` 外所有请求必须带：

```
X-ScoutMind-Token: <token>
```

未设置令牌时后端启动会告警，并且只允许本机访问。令牌只存在本地环境变量或 `.env`（已被 `.gitignore` 排除），
不得写入仓库或前端构建产物。

## 3. CORS

允许来源通过 `SCOUTMIND_CORS_ORIGINS` 配置，默认只有 `http://127.0.0.1:5173`、`http://localhost:5173` 与
后端自身的 `8000`。不开启 `allow_credentials`。

## 4. 游戏读取边界

- 读取器只读取进程内存与文件版本信息，**不写入游戏进程、不修改游戏文件、不注入代码**。
- 版本不匹配（未知 build、未知 `game_plugin.dll` 版本）必须拒绝扫描，不允许复用旧偏移或猜测地址。
- 扫描器是可替换的外部可执行文件；必须自行审查其来源与许可证，ScoutMind 不捆绑第三方扫描器。
- 扫描输出先落盘为原始 JSON，再导入；导入失败不会影响游戏与存档。

## 5. 数据边界

- 只使用自己机器上的存档与运行数据；不分发游戏本体、受版权保护的素材或他人存档。
- 原始报文保存在 `backend/data/raw/<save_id>/`，便于重新解析；删除存档时应一并删除。
- 演示数据的 `source` 固定为 `synthetic_fixture`，API 返回 `demo_mode=true`，前端展示警示横幅。

## 6. 许可证

- 项目代码采用 MIT 许可证（见 `LICENSE`）。
- 若复用 FMSuperScout 等上游代码，必须保留其版权与许可证文本，并在 `docs/` 中记录来源。
- 当前实现对 FMSuperScout **只做数据交换**：只读其导出的 JSON，不复用代码；上游为 MIT，来源与字段依据记录在
  `docs/FMSUPERSCOUT.md`。不写对方目录、不写游戏存档、不向游戏进程写入数据。
- 代码许可证不等于游戏数据、商标、素材或游戏条款的授权；商业化前需单独审查，不宣称获得 SEGA / Sports Interactive 授权。

## 7. 依赖与供应链

- 后端依赖固定在 `backend/requirements.txt` 的版本区间；升级时运行完整测试。
- C# 读取器不引入 NuGet 依赖，只用 .NET 内置程序集，降低供应链风险。
- 前端依赖通过锁文件固定；生产构建前执行 `npm run build` 做类型检查。

## 8. 存档身份与采集闸门（V3.2.7.2）

- 身份状态由后端按证据封顶：仅次证据只能是 `candidate`；`verified` 需要人工 `/verify`（`actor` + `basis`）
  或第一优先级证据。客户端声明 `verified` 不会直接生效。
- 未解析指纹（`si:v1:unresolved:*`）最多 `discovered`；`ambiguous=true` 不得 `verified`。
- 同一存档出现不同指纹且声明 `verified` 时，新身份落 `conflict`，旧 `verified` 不替换，采集闸门阻断；
  冲突需人工处置，不自动合并两个真实存档。
- 采集写入必须同时满足：身份 `verified`、会话 `verified`、心跳未超时、无未解决冲突。
  心跳发现指纹/build 不一致会立即将会话置 `invalidated`，正在进行的采集与导入失败。
- 身份/会话/采集归属事件写入不可变审计表 `save_identity_audit_events`；ORM 层拒绝 update/delete。
- 心跳超时默认 120 秒；过期会话不再放行写入。
- 无新增自动采集开关：`auto` 必须显式启动，未启动时不产生采集或快照。
