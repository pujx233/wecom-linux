# 企业微信

## 版本

企业微信 **5.0.13.6005**，内置 **Wine 11.20**，Linux 社区适配测试版。
DEB 修订 **5.0.13.6005-8~rc3**，面向 amd64，glibc 最低要求为 2.38。
已在 Ubuntu 26.04 amd64 平台验证。

## 修复问题

- 修复中文输入串词、旧词误提交、候选框抖动及邮件输入异常。
- 修复附件另存为、图片复制、剪贴板兼容及文件粘贴问题。
- 改善菜单、阴影和窗口显示，修复 niri 黑斑及托盘、锁屏恢复异常。
- 修复会议启动、视频设置崩溃、高 DPI 二次缩放及 GNOME 46 X11 截图错屏。
- 改善启动与升级，减少重复设备通知及后台 CPU、内存占用。

最终 DEB 的 105 组自动回归通过，实机验证了聊天和搜索的中文输入及候选框稳定。
实现与结果见 [review 记录](ubuntu/wine-x11-fix/CODE-REVIEW.md)和[测试记录](ubuntu/validation.json)。

## 遗留问题

- Wayland 屏幕共享和部分 XWayland 截图仍为黑屏。
- 会议从副屏发起仍可能打开在主屏；分数缩放取整和会中改变桌面缩放后的大小异常仍待修复。
- 快速最大化、还原或拖动时仍可能短暂显示旧画面，#5 报告者环境的整圈黑边仍待复测。
- 双屏 200% 下，显式跨屏或横跨双屏全屏仍有选屏问题。
- 托盘“更多操作”菜单可能居中；会议菜单打开时最大化，菜单可能停留在原位置。
- #4 的 GPU 故障触发点尚未定位，#12 的拖动抖动尚未稳定复现。

## 安装

从 [Releases](https://github.com/pujx233/wecom-linux/releases/tag/v5.0.13.6005-8-rc3) 下载 DEB 和 `SHA256SUMS`：

```sh
sha256sum -c SHA256SUMS
sudo apt install ./com.qq.wecom.spark_5.0.13.6005-8~rc3_amd64.deb
```

在应用菜单启动“企业微信”。升级沿用原账号和聊天数据，用户目录位于 `~/.local/share/wecom/prefix`。

[使用与构建](UBUNTU.md) · [Wine 源码](ubuntu/wine-x11-fix/README.md) · [回归清单](ubuntu/wine-x11-fix/tests/README.md) · [第三方许可](THIRD-PARTY.md)

企业微信和图标属于腾讯，基础适配来自 [tbsangel/archlinux-wine-wecom-setup](https://github.com/tbsangel/archlinux-wine-wecom-setup)。
兼容问题请通过 [GitHub Issues](https://github.com/pujx233/wecom-linux/issues) 反馈。

## 支持项目

如果这个项目对你有帮助，欢迎请我喝杯咖啡。

<details>
<summary>☕ 请我喝杯咖啡（微信支付）</summary>

<p align="center">
  <img src="docs/wechat-pay.jpg" alt="微信支付赞赏码" width="280">
</p>

</details>
