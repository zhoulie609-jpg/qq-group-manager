# QQ群管机器人（Windows）

一个带“首页 / 账号与设置 / 插件 / 日志”主界面的本地桌面群管框架，通过 OneBot 11 WebSocket 连接 NapCat/NTQQ。全局黑名单作为内置插件，可启用、禁用和重载。管理器不保存 QQ 密码或登录态。

## 已实现

- 同步多个群，逐群启用管理并获取实时群人数
- 全局或单群黑/白名单，添加、移除、备注和 SQLite 持久化
- 黑名单入群申请自动拒绝并回复自定义备注
- 白名单入群申请自动通过，其余申请在“审核与日志”中人工处理
- 桌面前端直接输入 `QQ号T`（例如 `123456789T`）并回车，即可全局拉黑；群内授权管理员也可使用同一指令
- Windows 图形界面、断线重连、操作审计

## 运行

1. 安装 Python 3.11，然后执行：

   ```powershell
   py -3.11 -m pip install -r requirements.txt
   py -3.11 main.py
   ```

2. 在 NapCat 中启用 OneBot 11 正向 WebSocket 服务（示例 `ws://127.0.0.1:3001`），建议设置强 Access Token。
3. 打开本程序“连接与设置”：填写 WebSocket、Token 和有权使用 `QQ号T` 的管理员 QQ，保存并连接。
4. “同步群列表”后，选中要管理的群并点击“启用/停用”。

若已下载 NapCat Windows 启动程序，可在设置页选中它并点击“启动 NapCat / 扫码登录”。扫码在 NapCat/QQ 的登录窗口完成。

## 构建 EXE

必须在 Windows 10/11 上双击 `build_windows.bat`；输出为 `dist\QQGroupManager.exe`。PyInstaller 不支持从 macOS 直接交叉编译 Windows EXE。

也可以把项目推到 GitHub，然后在 Actions 中运行 `build-windows-exe`，下载 `QQGroupManager-Windows` 构建产物。

数据库位于 `%APPDATA%\QQGroupManager\manager.db`。备份该文件即可备份全部名单、群配置和日志。

## NapCat 配置要点

- 机器人 QQ 必须是所管理群的管理员或群主，否则踢人和审核会失败。
- OneBot 服务只监听 `127.0.0.1`；如需远程部署，应使用防火墙、反向代理 TLS 和强 Token，切勿把无鉴权端口暴露到公网。
- 本项目没有打包 QQ、NapCat 或登录态。请从 NapCat 官方发布页自行取得兼容版本。
- NapCat 是基于 NTQQ 的第三方协议端，不是腾讯官方 QQ 机器人接口，可能因 QQ 更新失效，也可能触发账号限制。建议使用专用小号、先在测试群验证，并自行确认符合 QQ 平台规则。

## OneBot 动作

本程序使用 `get_group_list`、`get_group_member_list`、`set_group_add_request`、`set_group_kick`、`send_group_msg`。不同协议端的扩展和行为可能不同；当前以 NapCat 的 OneBot 11 实现为目标。
