# 企业微信

## 版本

企业微信 **5.0.13.6005**，内置 **Wine 11.20**，Linux 社区适配测试版。
DEB 修订 **5.0.13.6005-7**，面向 amd64，glibc 最低要求为 2.38。
已在 Ubuntu 26.04 amd64 平台验证。

## 修复问题

- 修复聊天框与搜索框之间的拼音串词、快速输入后提交旧词，以及邮件正文的组合输入、候选定位和输入法重连。
- 修复聊天附件另存为时的重名提示和保存目录错误，补齐文件选择的目录切换、确认回调与文件视图兼容。
- 修复聊天图片复制失败，以及 32/64 位程序之间的图片剪贴板兼容，支持文件粘贴到 Linux 文件夹。
- 修复托盘恢复后输入焦点落到隐藏窗口，以及锁屏恢复后最大化窗口滞留全屏。
- 修复视频设置崩溃、文档绘制方式切换后侧栏丢失，以及 GNOME 46 X11 截图错屏。
- 改善窗口拖动、缩放、菜单和阴影的绘制同步，修复高 DPI 会议画面被二次缩放的问题。
- 修复启动、升级和重复唤回，保留账号与聊天记录；减少设备通知、注册表膨胀和重复映像的内存占用。

本轮运行库的 101 组自动回归通过，实机验证了聊天、搜索、邮件、图片、附件保存、托盘恢复和快速会议。
实现与结果见 [review 记录](ubuntu/wine-x11-fix/CODE-REVIEW.md)和[测试记录](ubuntu/validation.json)。

## 遗留问题

- Wayland 屏幕共享和部分 XWayland 截图仍为黑屏。
- 会议从副屏发起仍可能打开在主屏；分数缩放取整和会中改变桌面缩放后的大小异常仍待修复。
- 快速最大化、还原或拖动时仍可能短暂显示旧画面，#5 报告者环境的整圈黑边仍待复测。
- 双屏 200% 下，显式跨屏或横跨双屏全屏仍有选屏问题。
- 托盘“更多操作”菜单可能居中；会议菜单打开时最大化，菜单可能停留在原位置。
- #4 的 GPU 故障触发点尚未定位，#12 的拖动抖动尚未稳定复现。

## 安装

从 [Releases](https://github.com/pujx233/wecom-linux/releases/tag/v5.0.13.6005-7) 下载 DEB 和 `SHA256SUMS`：

```sh
sha256sum -c SHA256SUMS
sudo apt install ./com.qq.wecom.spark_5.0.13.6005-7_amd64.deb
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
