# 企业微信

企业微信 5.0.12.6018 的 Linux Wine 适配，内置私有 Wine 11.20。
目前发布 **Ubuntu 26.04 amd64 测试版**，仍有已知问题，不宣称全部修复或支持所有 Linux 桌面。
直接使用现有桌面，不需要额外桌面或黑框，不替换 GNOME、Mutter、系统 Wine、系统库或扩展。

## 安装

从 [Releases](https://github.com/pujx233/wecom-linux/releases) 下载 DEB 和 SHA256SUMS，核对后安装：

```sh
sha256sum -c SHA256SUMS
sudo apt install ./com.qq.wecom.spark_5.0.12.6018-3~preview20261025_amd64.deb
```

在应用菜单启动“企业微信”。首次启动复制未登录模板到 `~/.local/share/wecom/prefix`，需要约 2.6 GB 用户空间；
系统安装本身约 2.9 GB。不带发布者账号、聊天记录、缓存和私密截图。原来的本地测试安装保持独立。
卸载使用 `sudo apt remove com.qq.wecom.spark`；个人账户和聊天记录保留，需自行备份后处理。
只针对 Ubuntu 26.04 构建，依赖 glibc 2.43；不要在 Ubuntu 22.04/24.04 上强行安装。

## 做了什么

- 修订 Wine 的零尺寸、透明窗口输入区域、owner/阴影关系和跨进程绘制裁剪，改善右键菜单、残影及遮挡。
- 用实际绘制完成边界提交窗口内容，读取 DC、内部像素迁移和光标更新不再提前提交首帧；完成后及时刷新。
- 为邮件统一 DPI 感知模式，给安装器自带的 x86 CEF 回补 V8 保护值和 Chromium 光标坐标修订。
- 包含 IBus 输入桥、字体配置及已有标题栏管理助手。旧的菜单重映射、隐藏成员卡阴影助手关闭且不随包分发。
- 默认 SNI 托盘改善透明度和清晰度；点击语义和原菜单定位仍有限制。

## 还有什么问题

- 托盘单击/右键与 Windows 不一致；“更多操作…”没有坐标，可能回到主窗/工作区中间。
- 成员卡、已读人数面板、聊天展开/切换和标题栏过渡的所有组合还没有完整验收，可能仍有闪动或残影。
- 聊天记录首帧修订在 4 次 SNI 冷启动首次开关和连续开关的采样中通过；零采样白帧不等于所有帧都被覆盖。
- 邮件光标在当前双屏 200% 环境复测通过；文档、审批、收发附件、音视频及其他缩放/桌面环境未完成全面验证。
- 企微自动升级或替换 CEF 可能覆盖适配，本包固定当前版本；尚未验证跨版本升级迁移。

详见 [Ubuntu 使用和验证边界](UBUNTU.md)、[Wine 修订与构建](ubuntu/wine-x11-fix/README.md)、
[固定组件清单](ubuntu/release.json)。发行说明如实保留失败项；没有提交 Wine/GNOME 上游 MR。

## 源码与来源

- [ubuntu/](ubuntu/)：启动器、CEF 定向补丁、Wine 完整净补丁、构建与 DEB 打包脚本。
- [scripts/](scripts/) 与 [configs/](configs/)：随包助手的源码、二进制与配置。
- [验证摘要](ubuntu/validation.json)：隔离测试和真实企微采样分开记录，不包含聊天截图。
- 原始 Wine 完整源码、补丁及 LGPL 许可证随 DEB 位于 `/usr/share/doc/com.qq.wecom.spark/`。
- 安装和输入/字体等基础工作来自 [tbsangel/archlinux-wine-wecom-setup](https://github.com/tbsangel/archlinux-wine-wecom-setup)，
  固定提交 `f0ad4711049476bb2d87b40acaff53ca5ee58124`；本仓库的 Ubuntu 结论与该项目的 Arch/KDE 验证分开。
- 企业微信和图标属于腾讯；这是非官方社区适配。第三方许可证与 CEF 修改说明见 [THIRD-PARTY.md](THIRD-PARTY.md)。
