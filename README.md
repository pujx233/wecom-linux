# 企业微信

企业微信 Linux 适配，内置独立 Wine **11.20**，适用于 **Ubuntu 26.04 amd64**。
当前源码使用企业微信 **5.0.13.6005**，最新改动尚未重新打包。
已发布安装包仍为 **5.0.12.6018 R5**。
[下载安装包与校验和](https://github.com/pujx233/wecom-linux/releases/tag/v5.0.12.6018-r5-preview.20261028)。

取得 DEB 和对应 SHA256SUMS 后执行：

```sh
sha256sum -c SHA256SUMS
sudo apt install ./com.qq.wecom.spark_5.0.12.6018-5.preview20261028_amd64.deb
```

在应用菜单启动“企业微信”。用户数据保存在 `~/.local/share/wecom/prefix`。
升级保留已有账号目录，启动器从安装包加载新版助手。
卸载使用 `sudo apt remove com.qq.wecom.spark`，个人数据会保留。

目前的改动：

- 修复窗口绘制、阴影、弹窗层级，以及双屏最大化和还原。
- 修复输入法候选框定位、微盘开窗退出、机器人内容独立开窗。
- 清理设备关系缓存，合并重复通知，减少注册表膨胀和磁盘服务 CPU 占用。
- 修正绘图锁顺序，纯层级调整不再重复更新窗口位置。

目前还有这些问题：

- 托盘菜单定位不准，XWayland 下截图黑屏。
- 登录、邮件及头像首次加载慢，偶发白条。
- 聊天记录窗口记住了过大的尺寸；本机已清理该设置，待再次打开确认。
- Wine 蓝牙模块有一处名称字符串泄漏，修复尚未合入。

本机使用 GNOME 50.1 Wayland 会话中的 **X11/XWayland**，双屏、200% 缩放。
最新锁顺序和层级修订已编译并安装，待下次启动复测。附件、审批、音视频等功能尚未全面验证。

安装、升级、重建及独立测试见 [Ubuntu 说明](UBUNTU.md)和
[Wine 构建说明](ubuntu/wine-x11-fix/README.md)。DEB 的 `/usr/share/doc/com.qq.wecom.spark/`
提供 Wine 原始完整源码、净补丁、构建脚本、助手源码及 LGPL。

企业微信和图标属于腾讯。基础适配来自
[tbsangel/archlinux-wine-wecom-setup](https://github.com/tbsangel/archlinux-wine-wecom-setup)，
许可证与 CEF 修改说明见 [THIRD-PARTY.md](THIRD-PARTY.md)。
