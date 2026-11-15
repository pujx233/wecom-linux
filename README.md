# 企业微信

企业微信 5.0.13.6005 的 Linux 社区适配版，内置 Wine 11.20。
当前测试版为 **5.0.13.6005-6**。
本轮修复邮件组合输入、输入法重连、图片选择、会议组件加载和窗口绘制，并减少多进程重复映像的内存开销。
实现与验证见 [review 记录](ubuntu/wine-x11-fix/CODE-REVIEW.md)。

## 安装

从 [Releases](https://github.com/pujx233/wecom-linux/releases/tag/v5.0.13.6005-6) 下载 DEB 和校验文件：

```sh
sha256sum -c SHA256SUMS
sudo apt install ./com.qq.wecom.spark_5.0.13.6005-6_amd64.deb
```

在应用菜单启动“企业微信”。升级沿用账号和聊天记录，用户数据位于 `~/.local/share/wecom/prefix`。

## 适配内容

- 跟随桌面 DPI，保留手工设置，修复中文字体与文件名显示。
- 支持 Linux 原生文件选择窗口；依赖 Windows 文件视图的上传入口使用 Wine 兼容窗口。
- 接入默认文件管理器的目录打开和文件定位。
- 修复拖动、缩放、最大化、还原及拔屏后的窗口错位，改善菜单、已读名单和预览弹窗的绘制与层级。
- 修复 niri 的累积黑斑，补齐 KWin 的首帧同步与菜单焦点声明。
- 修复跨进程邮件正文的中文预编辑、候选定位、切换控件串词、连续组词丢字及输入法重连。
- 补齐会议组件的静态导入依赖，修复预览阴影抢占鼠标，减少重复设备枚举和映像内存开销。

文件粘贴、运行中唤回、正常退出后的升级切换、成员卡焦点及蓝牙名称缓存修复均沿用。
回归范围和结果见[测试记录](ubuntu/validation.json)。

## Linux 环境

安装包面向 amd64，核心 glibc 要求为 2.38，无需安装系统 Wine。
验证环境包括 Ubuntu 26.04 GNOME/Mutter，以及 Fedora 44 嵌套 niri 和 KWin 6.6.6；各版本的测试范围见[验证记录](ubuntu/validation.json)。

共享输出、XWayland 截图黑屏及会议菜单打开后最大化的定位仍有问题。
#4 的 GPU 故障触发请求、#5 报告者环境的缩放黑区仍未定位完成。
本机快速最大化、还原时也仍可见短暂旧尺寸画面，稳定后的尺寸已验证。
双屏 200% 原生全屏选屏及 GNOME 的 IBus 生命周期修复属于宿主组件，未由 DEB 自动安装；
本机部署与测试范围见 [review 记录](ubuntu/wine-x11-fix/CODE-REVIEW.md)。

[使用与构建](UBUNTU.md) · [Wine 源码](ubuntu/wine-x11-fix/README.md) · [回归清单](ubuntu/wine-x11-fix/tests/README.md) · [第三方许可](THIRD-PARTY.md)

企业微信和图标属于腾讯，基础适配来自 [tbsangel/archlinux-wine-wecom-setup](https://github.com/tbsangel/archlinux-wine-wecom-setup)。
Linux 发行版和桌面环境较多，欢迎通过 [GitHub Issues](https://github.com/pujx233/wecom-linux/issues) 反馈兼容问题。
仓库：[pujx233/wecom-linux](https://github.com/pujx233/wecom-linux)。
