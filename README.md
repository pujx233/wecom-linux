# 企业微信

企业微信 Linux 适配，内置独立 Wine，当前本地候选为 **5.0.12.6018 R5（2026-10-28）**，
适用于 **Ubuntu 26.04 amd64**，Wine **11.20**。[下载 R5 安装包与校验和](https://github.com/pujx233/wecom-linux/releases/tag/v5.0.12.6018-r5-preview.20261028)。

取得 DEB 和对应 SHA256SUMS 后执行：

```sh
sha256sum -c SHA256SUMS
sudo apt install ./com.qq.wecom.spark_5.0.12.6018-5.preview20261028_amd64.deb
```

在应用菜单启动“企业微信”。用户数据保存在 `~/.local/share/wecom/prefix`。
升级保留已有账号目录，启动器从安装包加载新版助手。
卸载使用 `sudo apt remove com.qq.wecom.spark`，个人数据会保留。

本轮修订覆盖：

- 用 XDamage 接收其他进程绘制的变化，修正邮件正文已绘制但共享框架仍显示旧内容的问题。
- 保留嵌套消息循环期间的待合成状态，在窗口同步解锁后提交，避免通知被消费后丢帧。
- 去除界面线程等待合成器私有属性的轮询，保留绘图完成和 XSync 提交协议。
- 修正普通透明工具窗口的输入规则，以及人物卡片、头像预览和同 owner 弹窗的原生层级。
- 复用合成缓冲区，合并重复提交；保留顶栏、阴影、聊天记录裁剪及 GDI+ 图片缩放修订。
- 当前原生模式停用标题栏样式改写和模拟鼠标消息；保留主窗口阴影不接收点击的企微适配。

本机验收环境为 GNOME 50.1 Wayland 会话中的 **X11/XWayland**，双屏、200% 缩放。
包内使用未登录模板，不包含维护者账号和聊天记录；系统 Wine、GNOME、Mutter 和桌面设置无需修改。
证据及测试边界见 [validation.json](ubuntu/validation.json)，通用修复与兼容策略的区分见
[完整代码审查](ubuntu/wine-x11-fix/CODE-REVIEW.md)。

托盘“更多操作”的菜单定位仍有限制；XWayland 下的企微截图黑屏本轮搁置。
进入邮件模块、图片准备和桌面开窗动画仍需要时间。附件收发、审批、音视频及其他桌面尚未全面验收。
这是社区预览修订，局部场景通过不代表企业微信所有功能兼容。

安装、升级、重建及独立测试见 [Ubuntu 说明](UBUNTU.md)和
[Wine 构建说明](ubuntu/wine-x11-fix/README.md)。DEB 的 `/usr/share/doc/com.qq.wecom.spark/`
提供 Wine 原始完整源码、净补丁、构建脚本、助手源码及 LGPL。

企业微信和图标属于腾讯。基础适配来自
[tbsangel/archlinux-wine-wecom-setup](https://github.com/tbsangel/archlinux-wine-wecom-setup)，
许可证与 CEF 修改说明见 [THIRD-PARTY.md](THIRD-PARTY.md)。
