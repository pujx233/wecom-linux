# 企业微信

企业微信 5.0.13.6005 的 Linux 社区适配版，内置 Wine 11.20。
当前测试版为 **5.0.13.6005-5**。
本轮修复文件粘贴、升级切换、成员卡及窗口状态，验证状态见[实现与 review 记录](ubuntu/wine-x11-fix/CODE-REVIEW.md)。

## 安装

从 [Releases](https://github.com/pujx233/wecom-linux/releases/tag/v5.0.13.6005-5) 下载 DEB 和校验文件：

```sh
sha256sum -c SHA256SUMS
sudo apt install ./com.qq.wecom.spark_5.0.13.6005-5_amd64.deb
```

在应用菜单启动“企业微信”。升级沿用账号和聊天记录，用户数据位于 `~/.local/share/wecom/prefix`。

## 适配内容

- 跟随桌面 DPI，保留手工设置，修复中文字体与文件名显示。
- 接入 Linux 原生上传文件选择窗口，以及默认文件管理器的目录打开和文件定位。
- 修复拖动、缩放、最大化、还原及拔屏后的窗口错位，改善菜单、已读名单和预览弹窗的绘制与层级。
- 修复 niri 的累积黑斑，补齐 KWin 的首帧同步与菜单焦点声明。
- 改善输入法候选位置、邮件正文刷新、图片缩放及网页组件兼容，减少重复设备枚举和磁盘服务开销。

-5 新增文件粘贴、运行中唤回和工作区变化后的窗口状态修复。
本轮进一步处理了正常退出后的升级切换、成员卡排序与焦点、特殊全屏及默认最大化、
蓝牙名称缓存泄漏，并复核了输入法矩形区域的接口与测试。
回归范围和结果见[测试记录](ubuntu/validation.json)。

## Linux 环境

安装包面向 amd64，核心 glibc 要求为 2.38，无需安装系统 Wine。
验证环境包括 Ubuntu 26.04 GNOME/Mutter，以及 Fedora 44 嵌套 niri 和 KWin 6.6.6；各版本的测试范围见[验证记录](ubuntu/validation.json)。

目前仍有托盘菜单定位、XWayland 截图黑屏，以及双屏 200% 下的 Mutter 原生全屏选屏问题。
RX580 上的右键黑框和 Plasma X11 的菜单定位仍需在原环境复测。
-5 已修复 96 DPI 下部分菜单因尺寸回执反复争用而不显示的问题。
快速最大化、还原及锁屏恢复后偶发的正文或阴影尺寸异常仍待处理。
该异常也在上一份本地 -5 中出现，尚未完成与公开 -4 的对照。

[使用与构建](UBUNTU.md) · [Wine 源码](ubuntu/wine-x11-fix/README.md) · [回归清单](ubuntu/wine-x11-fix/tests/README.md) · [第三方许可](THIRD-PARTY.md)

企业微信和图标属于腾讯，基础适配来自 [tbsangel/archlinux-wine-wecom-setup](https://github.com/tbsangel/archlinux-wine-wecom-setup)。
Linux 发行版和桌面环境较多，欢迎通过 [GitHub Issues](https://github.com/pujx233/wecom-linux/issues) 反馈兼容问题。
仓库：[pujx233/wecom-linux](https://github.com/pujx233/wecom-linux)。
