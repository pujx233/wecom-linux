# 企业微信

企业微信 **5.0.13.6005**，内置 Wine **11.20**，适用于 **Ubuntu 26.04 amd64**。
DEB 版本 **5.0.13.6005-1**，更新于 **2026-10-30**。
[下载安装包与校验和](https://github.com/pujx233/wecom-linux/releases/tag/v5.0.13.6005)。

解决了：

- 拖动时正文与外框错位、白框和黑缝，以及历史侧栏展开时的闪动。
- 切到后台后无法回到前台、最小化恢复后被遮挡，以及拔屏后的窗口裁切。
- 改善成员卡层级、双屏最大化和还原。
- 输入法候选框遮字、微盘开窗退出、机器人内容独立开窗。
- 减少重复设备通知、注册表膨胀和磁盘服务 CPU 占用。

还剩：

- 托盘菜单定位不准，XWayland 下截图黑屏。
- 邮件和头像首次加载仍偏慢。
- Wine 蓝牙模块有一处名称字符串泄漏。
- 偶现卡片遮挡仍需日常确认；音视频、审批、附件及其他桌面和缩放场景未全面验证。

安装：

```sh
sha256sum -c SHA256SUMS
sudo apt install ./com.qq.wecom.spark_5.0.13.6005_amd64.deb
```

从应用菜单启动“企业微信”。升级保留账号和聊天记录，用户数据位于 `~/.local/share/wecom/prefix`。

[构建说明](UBUNTU.md) · [Wine 源码与测试](ubuntu/wine-x11-fix/README.md) · [第三方许可](THIRD-PARTY.md)

企业微信和图标属于腾讯。基础适配来自
[tbsangel/archlinux-wine-wecom-setup](https://github.com/tbsangel/archlinux-wine-wecom-setup)。
