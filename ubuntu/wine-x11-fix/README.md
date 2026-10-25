# Wine 11.20 企业微信 Linux 修订

当前包为 Ubuntu 26.04 amd64 预览版，存在已知问题；完整结果见仓库 README 与 validation.json。
Wine 基于 `wine-11.20` / `7298a818b79446bae153b8d5aa27235ab3703bf9`。
`wine-11.20-x11-popups.patch` 是相对原始 11.20 的完整净补丁，不依赖本机历史候选目录。

修订覆盖零尺寸窗口、ARGB 显示与输入区域、owner/阴影管理、跨进程子窗口 DC 裁剪、
X11 输出刷新、光标资源持有/应用完成确认、SNI 托盘，以及应用完成绘图后的首帧提交。
历史修订中仍有企微专用开关和既有标题栏助手，不能称作全部适用于所有 Windows 应用的上游修复。
默认不加载旧的菜单重映射、隐藏阴影或自定义 GNOME 库。

## 绘制完成

DIB 实际写入序列区分写入、读取及裁剪后的空操作。应用写入 ReleaseDC 或 EndPaint 完成后提交，
内部有效像素迁移和 caret 更新不宣告应用帧完成。校验当前逻辑 surface 身份，并处理缩放 native surface。
已完成的普通绘图立即刷新，不需要后续 User32 调用。
该 Win32u / X11 私有协定必须成套构建和部署。

## 构建

完整原始源码：`https://github.com/wine-mirror/wine/archive/refs/tags/wine-11.20.tar.gz`。
SHA256：`98b21b4ebdf7d9e2baa4a3508514285cf449f455603f82d3364b014c0e79b793`。
DEB 内 `/usr/share/doc/com.qq.wecom.spark/` 同时提供原始完整源码、净补丁、构建脚本和 LGPL。

```sh
docker build -t wecom-wine-sdk ubuntu/wine-x11-fix
docker run --rm --network none --user "$(id -u):$(id -g)"   -v "$PWD:/adapter:ro" -v /absolute/build-area:/work   wecom-wine-sdk sh /adapter/ubuntu/wine-x11-fix/build.sh   /work/wine-11.20.tar.gz /work/new-output
```

Unix 组件使用 `--enable-win64 --without-mingw --without-wayland`，须检测到 DBus 开发接口。
Explorer 单独启用 x64 MinGW。当前发行二进制来自匹配 SDK 的增量构建，精确指纹见 release.json。
完整重建得到相同源码逻辑；不同编译路径、SDK 和编译器不保证二进制逐字节相同。
不要以系统 Wine 覆盖私有组件，也不要与旧候选中的 server/Win32u 混搭。

## 未完成项

SNI 的 DBusMenu “更多操作”不带坐标，原菜单仍可回到中间；单击/右键语义不完整。
XEmbed 动态布局候选失败并撤回。其有符号 DPI 与 XSETTINGS 实验不在本发行运行时内。
成员卡、已读人数、标题栏及各窗口过渡尚未完整验收，不能用隔离探针通过替代真实客户端结果。
