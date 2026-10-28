# Wine 11.20 企业微信修订

当前为企业微信 5.0.12.6018 R5 的私有 Wine，适用于 Ubuntu 26.04 amd64。
累计净补丁基于原始 Wine 11.20 / `7298a818b79446bae153b8d5aa27235ab3703bf9`，不依赖历史候选目录。
修复、应用兼容策略及保留的 workaround 分类见 [CODE-REVIEW.md](CODE-REVIEW.md)。

## 当前实现

`win32u` 根据实际写入和应用的绘图完成信号提交 surface；读取、内部 caret 和有效像素迁移不作完成信号。
`winex11.drv/window.c` 管理主体、顶栏和装饰的共享框架、owner、输入区域及原生几何。
`frame.c` 用 XDamage 接收其他进程绘制的变化，复用合并提交消息，解决后台内容已更新而框架未更新的问题。
`xrender.c` 按 alpha 合成并复用尺寸匹配的 Pixmap、Picture 和 GC，关闭不必要的 GraphicsExpose 通知。

已移除持有窗口锁时等待 `_XWAYLAND_ALLOW_COMMITS` 的轮询，保留标准 XSync 和绘图完成同步。
普通透明工具窗口接收正常点击，分层透明窗口继续允许穿透；透明命中后查找后续同线程窗口。
共享框架间的换序使用真实 WM frame XID，不依赖窗口尺寸发生变化。
原生模式的工具窗口管理策略由显式开关启用，避免点击时反复改变 native 窗口身份。

GDI+ 双线性采样减少重复运算，保留像素输出与舍入。两个架构各 144 组像素对照和混色等价检查已完成。
OpenGL client surface 和 foreign DC 使用实际 visual，避免 24 位与 32 位 drawable 的直接混拷。
相关 Win32u/X11 私有协议和 server 光标确认机制需要配套组件。

SNI 的原生线程、GUI 队列和 token 生命周期独立管理。失败的 XEmbed 坐标重映射实验已删除，
包括 Mutter 私有接口查询、布局解析、鼠标 extra 注入和 Explorer 专用转发；保留原始 XEmbed 回退。
SNI 菜单居中回退尚未解决。

## 构建

原始完整源码：`https://github.com/wine-mirror/wine/archive/refs/tags/wine-11.20.tar.gz`。
SHA256：`98b21b4ebdf7d9e2baa4a3508514285cf449f455603f82d3364b014c0e79b793`。
DEB 的 `/usr/share/doc/com.qq.wecom.spark/` 包含原始归档、净补丁、构建脚本、适配器源码与 LGPL。

```sh
docker build -t wecom-wine-sdk ubuntu/wine-x11-fix
docker run --rm --network none --user "$(id -u):$(id -g)" \
  -v "$PWD:/adapter:ro" -v /absolute/build-area:/work \
  wecom-wine-sdk sh /adapter/ubuntu/wine-x11-fix/build.sh \
  /work/wine-11.20.tar.gz /work/new-output
```

Unix 组件使用 `--enable-win64 --without-mingw --without-wayland`。
脚本要求 DBus、XComposite、XDamage、XRender 和 XShape；SDK 包含 libxdamage-dev，运行时依赖 libxdamage1。
Explorer 和 GDI+ 使用独立的 x86/x64 MinGW 构建。输出路径为：

```text
build/server/wineserver
build/dlls/win32u/win32u.so
build/dlls/winex11.drv/winex11.so
build-explorer/programs/explorer/x86_64-windows/explorer.exe
build-explorer/dlls/gdiplus/i386-windows/gdiplus.dll
build-explorer/dlls/gdiplus/x86_64-windows/gdiplus.dll
```

精确二进制指纹见 release.json。干净源码构建另行验证；编译路径和工具链不同会改变二进制哈希。
不要混用系统 Wine 或其他候选中的组件。当前未整合本地有符号 DPI / XSETTINGS 实验。

## 回归

[frame-composition](tests/frame-composition/README.md) 使用私有 GNOME/XWayland 会话、合成窗口和独立 prefix，
验证跨进程显示、源像素不变、三种输入样式、稳定原生身份、owned 预览和同 owner 框架换序。
实际邮件、图片、分享记录、展开历史切换和成员卡另列于 validation.json。

`tests/gdiplus-render-check.cpp` 不读取个人图片；分别在新旧运行时执行并逐字节比较输出，每次 144 个场景。

```sh
i686-w64-mingw32-g++ -O2 -std=c++11 -static-libstdc++ -static-libgcc \
  tests/gdiplus-render-check.cpp -lgdiplus -o gdiplus-render-check.exe
```

64 位将编译器改为 `x86_64-w64-mingw32-g++`。计时依赖机器与负载，像素等价和计时结论分开。
桌面开窗动画和图片准备仍有耗时；截图黑屏本轮搁置，托盘菜单定位仍受限制。
音视频、附件、审批、已读人数及其他桌面未全面验收。
