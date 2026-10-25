# 企业微信

企业微信 Linux 适配，内置独立 Wine，直接在 Ubuntu 桌面运行。

## 版本

企业微信 **5.0.12.6018**，Wine **11.20**，社区测试版 R3。
适用于 **Ubuntu 26.04 amd64**，安装包约 **955 MB**。

## 安装

从 [Releases](https://github.com/pujx233/wecom-linux/releases) 下载 DEB 和 SHA256SUMS，在下载目录执行：

```sh
sha256sum -c SHA256SUMS
sudo apt install ./com.qq.wecom.spark_5.0.12.6018-3.preview20261025_amd64.deb
```

在应用菜单启动“企业微信”。程序安装约占 2.9 GB，首次启动另需约 2.6 GB 用户空间。
用户数据保存在 `~/.local/share/wecom/prefix`。
卸载命令：`sudo apt remove com.qq.wecom.spark`，个人数据会保留。

## 修复问题

- 改善右键菜单、透明窗口、阴影遮挡和绘制裁剪。
- 改善聊天记录首次打开的白帧和刷新延迟。
- 修订邮件光标、高分屏显示和内置网页组件兼容问题。
- 改善托盘图标透明度和清晰度。
- 内置独立 Wine、输入法桥接和字体配置，保留邮件、会议等组件。
- 去掉重复文件和 Wine 调试信息，将安装包从约 1.50 GB 缩减至约 955 MB。

## 遗留问题

- 托盘单击、右键行为仍不完善，“更多操作”会出现回到屏幕中间的问题。
- 部分成员卡、已读人数弹窗、标题栏和窗口切换仍有闪动或残影。

使用与构建见 [Ubuntu 说明](UBUNTU.md)和 [Wine 构建说明](ubuntu/wine-x11-fix/README.md)。

## 源码与来源

- [ubuntu/](ubuntu/)：启动器、CEF 兼容补丁、Wine 补丁、构建与打包脚本。
- [scripts/](scripts/) 与 [configs/](configs/)：随包助手的源码、二进制与配置。
- 原始 Wine 完整源码、补丁及 LGPL 许可证随 DEB 位于 `/usr/share/doc/com.qq.wecom.spark/`。
- 安装和输入/字体等基础工作来自 [tbsangel/archlinux-wine-wecom-setup](https://github.com/tbsangel/archlinux-wine-wecom-setup)，
  并在此基础上适配 Ubuntu。
- 企业微信和图标属于腾讯；这是非官方社区适配。第三方许可证与 CEF 修改说明见 [THIRD-PARTY.md](THIRD-PARTY.md)。
