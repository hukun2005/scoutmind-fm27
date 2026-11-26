ScoutMind FM27 Desktop V3.2.9.2
================================

完全本地运行的桌面应用：不需要安装 Python、Node.js 或浏览器插件，双击 ScoutMindFM27.exe 即可使用。

一、启动
1. 解压整个文件夹到任意位置（不要只复制 exe，_internal 目录必须与 exe 同级）。
2. 双击 ScoutMindFM27.exe。
3. 首次启动会自动建库并执行数据库迁移（约 10-30 秒），随后弹出“ScoutMind FM27”桌面窗口。
4. 之后再次启动会复用已有数据，速度更快。

提示：Windows 可能弹出 SmartScreen 提示，选择“更多信息 → 仍要运行”。
如果系统缺少 Edge WebView2 运行时，程序会自动改用默认浏览器打开界面。

二、数据与备份
- 全部数据保存在 exe 同级的 data 目录：scoutmind.db 为数据库，raw 为原始存档副本。
- 迁移前/定期备份：关闭程序后复制 data\scoutmind.db 即可；恢复时用备份文件覆盖回去。
- 卸载：关闭程序后直接删除整个文件夹，不会写入注册表，也不会留下系统级文件。
- 日志：logs\desktop.log（启动与迁移），logs\desktop.stderr.log（详细迁移输出）。

三、读取 FM27 真实数据
1. 先启动 Football Manager 27 并读档。
2. 运行 live-reader\ScoutMind.LiveReader.exe（读取进程内数据）。
3. 回到 ScoutMind 窗口，在“采集/导入”页面执行扫描与导入。
4. 首次连接某个存档需要在界面中完成确认；游戏内再次保存会改变存档指纹，需要重新确认。

四、端口与多开
- 每次启动自动选择一个空闲端口，仅监听 127.0.0.1，不对外开放。
- 重复双击不会再起一套服务，会直接打开已有实例的窗口。
- 若窗口意外关闭但进程仍在，可在任务管理器中结束 ScoutMindFM27.exe 后重新启动。

五、常见问题
- 窗口空白：等待 5-10 秒（首次加载资源较慢）；仍空白则查看 logs\desktop.log。
- 启动报错：查看 logs\desktop.log 与 logs\desktop.stderr.log，多为目录无写入权限，换到非系统盘的普通文件夹即可。
- 想换端口或只用浏览器：命令行执行 ScoutMindFM27.exe --browser。
- 只启动后端做排查：ScoutMindFM27.exe --headless --port 8000。

版本：V3.2.9.2 First Public Preview
