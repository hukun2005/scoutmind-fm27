# ScoutMind FM27 V3.2.6 Release Notes（RC 草案）

## 新增

- `world-date`：启发式世界日期解析（签名 + 最新日期 + 参考间隔 + 三重复读），输出 `confidence=heuristic`。
- `date-read --rva --field`：按“模块基址 + RVA”读取日期，跨 ASLR 可用。
- `module-info`：打印 game_plugin / GameAssembly 基址与大小。
- `static-date-scan`：从模块静态指针出发搜索日期对象（工具能力，结论见报告）。
- `date-locate` / `pointer-scan`：签名定位与指针引用扫描。

## 修复

- 模块边界：`MemScan.ScanRegions` 只含堆，旧代码用堆区域反推模块导致“没有模块内区域”；
  现改为直接使用 `MemScan.GpBase/GaBase`。
- 日期“少一天”误判：旧读数来自赛程日历对象；真实时钟在 10-26 / 10-31 / 11-06 与界面一致。

## 兼容性

- FM27 27.1.0 / build 26620374 / 插件 27.1：已验证日期读取与扫描。
- 其他 Build 未验证，不得声称兼容。

## 已知限制

- 日期定位为启发式，自动快照默认关闭；
- 没有持久化 Worker、没有安装器；
- 真实多存档切换未验证；
- 模块静态根未找到（时钟只在堆中）。

## 安装

当前仅支持源码部署：`scripts/setup.ps1` + `scripts/run-backend.ps1` + `scripts/run-frontend.ps1`，
读取器/代理用 `scripts/publish-windows.ps1` 生成。

## 数据安全

- 不修改游戏内存与存档；
- 上传报文不含内存地址；
- 数据库升级通过 Alembic 新迁移，不修改历史迁移。
