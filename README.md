# 企业微信

版本

企业微信 5.0.13.6005，内置 Wine 11.20，Linux 社区适配版。
目前支持 Ubuntu 26.04 amd64。

修复问题

- 修复拖动时正文与外框错位、白框和黑缝，改善聊天侧栏展开时的闪动。
- 修复前后台切换、最小化恢复和拔屏后的窗口显示，改善成员卡层级及双屏最大化、还原。
- 修复输入法候选框遮字、微盘开窗退出及机器人内容独立开窗。
- 减少重复设备通知、注册表膨胀和磁盘服务 CPU 占用。
- 内置独立 Wine，直接在现有桌面运行，保留邮件、会议等组件，安装包约 963 MB。

遗留问题

- 托盘单击、右键行为仍不完善，“更多操作”会出现回到屏幕中间的问题。
- XWayland 下截图黑屏。

[下载安装包与校验和](https://github.com/pujx233/wecom-linux/releases/tag/v5.0.13.6005)。

```sh
sha256sum -c SHA256SUMS
sudo apt install ./com.qq.wecom.spark_5.0.13.6005_amd64.deb
```

从应用菜单启动“企业微信”。升级保留账号和聊天记录，用户数据位于 `~/.local/share/wecom/prefix`。

[构建说明](UBUNTU.md) · [Wine 源码与测试](ubuntu/wine-x11-fix/README.md) · [第三方许可](THIRD-PARTY.md)

企业微信和图标属于腾讯。基础适配来自
[tbsangel/archlinux-wine-wecom-setup](https://github.com/tbsangel/archlinux-wine-wecom-setup)。
