# Wine 11.20 企业微信修订

本目录维护企业微信的私有 Wine 源码修订，当前应用版本为 5.0.13.6005，适用于 Ubuntu 26.04 amd64。
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
共享框架的创建和尺寸转换统一满足 X11 的非零尺寸要求；空 Win32 窗口提升层级时仍保持逻辑零尺寸，
不会再因直接创建 0×0 X11 frame 导致进程退出。
分组迁移与 frame 销毁使用原锁保护的全部 native window data，覆盖尚未进入 Z-order 的创建中窗口。
旧版在 `WM_NCCREATE` 中改变角色或迁移 owner 会漏移 body，销毁旧 frame 后访问失效 XID；
两个负例准确退出，修订后五项生命周期回归通过。用户已确认微盘正常，临时诊断未进入交付源码。

通用 PnP 修订不再为每个设备保存完整 Siblings 列表，而是从 Parent/Children 按需查询；
同设备尚未消费的 BusRelations 通知合并，移除后清理待处理引用，空 Children 正常发布。
Wineboot 在冷启动服务前清理旧派生缓存。真实注册表从约 1.45 GB 降到约 26 MB，
服务请求的秒级等待显著下降；同步保存仍有约 0.1 秒尖峰，不代表所有交互都已验收。
Mountmgr 的设备通知限定到 UDisks2，避免无关系统属性变化触发全量磁盘查询。

GDI+ 双线性采样减少重复运算，保留像素输出与舍入。两个架构各 144 组像素对照和混色等价检查已完成。
OpenGL client surface 和 foreign DC 使用实际 visual，避免 24 位与 32 位 drawable 的直接混拷。
相关 Win32u/X11 私有协议和 server 光标确认机制需要配套组件。

SNI 的原生线程、GUI 队列和 token 生命周期独立管理。失败的 XEmbed 坐标重映射实验已删除，
包括 Mutter 私有接口查询、布局解析、鼠标 extra 注入和 Explorer 专用转发；保留原始 XEmbed 回退。
SNI 菜单居中回退尚未解决。

XIM 定位保留 IMM32 的请求类型：仅当前焦点的自动 caret 更新在 callbacks 模式使用底边，
应用指定的点和区域保留原锚点，position 模式保持顶边。在原生几何改变后刷新现有 XIC 的屏幕位置，
不再按矩形大小推断请求来源；切换输入框后的旧 caret 更新不能覆盖新输入框的位置。
这修复逐次定位请求和窗口几何刷新，不等同于实现全部 IMC 持久定位策略或宿主 IME 的完整区域布局。
输入法、绘制完成和窗口角色修订已打包，完整组件清单见 `release.json`。
测试使用的具体组合见 `validation.json` 后续条目，不能用旧加载记录代表新源码。

双屏修订统一了共享框架的配置确认流程、最大化坐标换算和最小化恢复时的普通位置保护。
真实企微内外屏的最大化、托盘恢复和普通尺寸还原已复测；仍不代表所有闪动或 fullscreen 模式已解决。
原因与回归记录见 [代码审查](CODE-REVIEW.md#双屏最大化与恢复修订)。

Ubuntu 启动器为 `WeMail.exe` 和 `FlutterPlugins.exe` 设置 IFEO `dpiAwareness=1`，
在初始化时与 SYSTEM_AWARE 宿主保持一致，避免跨进程嵌入被拒后独立开窗。用户已确认机器人内容回到主窗口。
这是应用兼容配置，不是 Wine 通用跨进程 DPI reset 实现；线程级显式覆盖仍可能改变行为。
启动测试验证顺序与失败传播，真实显示结论另由实际窗口归属和用户复测确认。

本次登录较慢包含三次各约 5 秒的 TLS/传输建立超时，具体网络来源尚未确认，没有修改系统网络配置。
首次邮件容器约 0.23 秒显示，但账户登录完成约 4.16 秒，不能把容器出现视为内容完全就绪。
白边根因尚未确认。分享聊天记录打开铺满工作区已追到企微保存的窗口尺寸，已备份并移除这两个残留配置；
应用仍自行决定默认尺寸，没有在 Wine 中固定弹窗大小。另一个原生父坐标候选未合入。
详细归因及历史结论的更新见 [CODE-REVIEW.md](CODE-REVIEW.md)。

最新源码复审修正 USER/surface 锁序，并使共享框架的纯层级请求不再重排成员几何。
这两项已编译并打包，待实际使用复测。
源码与构建结果不能替代真实场景通过，之前的客户端验收记录不自动覆盖这次修改。

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
PE 组件使用独立 MinGW 构建；Explorer 和 Wineboot 为宿主 x64，GDI+、IMM32 和设备管理组件包含 x86/x64。输出路径为：

```text
build/server/wineserver
build/dlls/ntdll/ntdll.so
build/dlls/win32u/win32u.so
build/dlls/winex11.drv/winex11.so
build/dlls/wineps.drv/wineps.so
build/dlls/mountmgr.sys/mountmgr.so
build-explorer/programs/explorer/x86_64-windows/explorer.exe
build-explorer/dlls/gdiplus/i386-windows/gdiplus.dll
build-explorer/dlls/gdiplus/x86_64-windows/gdiplus.dll
build-explorer/dlls/imm32/i386-windows/imm32.dll
build-explorer/dlls/imm32/x86_64-windows/imm32.dll
build-explorer/dlls/cfgmgr32/{i386-windows,x86_64-windows}/cfgmgr32.dll
build-explorer/dlls/setupapi/{i386-windows,x86_64-windows}/setupapi.dll
build-explorer/dlls/ntoskrnl.exe/{i386-windows,x86_64-windows}/ntoskrnl.exe
build-explorer/programs/wineboot/x86_64-windows/wineboot.exe
```

输入法接口修订使用 GDI 驱动 ABI 111，`win32u.so`、`winex11.so`、`wineps.so` 和两份 IMM32 必须配套，
否则可能出现驱动拒绝加载、打印失败或旧 IMM32 仍调用丢失请求类型的入口。X11 启动器继续禁用 Wayland 驱动。
打包入口要求清单列出这些组件及设备管理、Wineboot 组件，并覆盖模板中的对应模块。
当前源码补丁和配套组件清单见 `release.json`。
编译路径和工具链不同会改变二进制哈希，不要混用系统 Wine 或其他候选中的组件。
当前未整合本地有符号 DPI / XSETTINGS 实验。

## 回归

`tests/cursor-regression.py` 接收完整运行时，不复制或混换单个 Wine 组件。`--manifest` 的
`runtime_sha256` 必须包含 `wineserver`、`winex11.so`、`win32u.so`、`ntdll.so` 的配套指纹。
测试使用自动分配的私有 Xvfb 与全新 prefix；外进程子窗口就绪后，比较宿主光标像素、热点和尺寸，
并记录运行前后的组件、测试程序和测试源码指纹。`--out` 必须是不存在的新目录。

```sh
x86_64-w64-mingw32-gcc -O2 -Wall -Wextra tests/foreign-cursor-test.c -luser32 -o /tmp/foreign-cursor-test.exe
python3 tests/cursor-regression.py --wine /path/to/complete-runtime --manifest /path/to/result.json \
  --exe /tmp/foreign-cursor-test.exe --out /path/to/new-qa-directory
```

需要 Xvfb、Xlib、XFixes、Xcursor；Xvfb 不在 PATH 时用 `--xvfb` 指定可执行文件。
测试要求可用的静态系统箭头、文本和链接光标主题；它验证跨进程指针形状，不代替托盘或真实企微验收。
报告中的耗时包含稳定性观察窗口，不作为性能基准；预编译测试程序须由上述源码生成。

[frame-composition](tests/frame-composition/README.md) 使用私有 GNOME/XWayland 会话、合成窗口和独立 prefix，
验证跨进程显示、源像素不变、三种输入样式、稳定原生身份、owned 预览和同 owner 框架换序。
实际邮件、图片、分享记录、展开历史切换和成员卡另列于 validation.json。

[ime-position](tests/ime-position/README.md) 在独立 prefix 和私有 XIM/IBus 会话中对比物理光标坐标，
覆盖 DPI、换行、不同光标高度、窗口移动，以及显式 composition 区域和焦点变化的负例。

[pnp-relations](tests/pnp-relations/README.md) 验证属性 API、通知队列和旧缓存迁移；
设备测试使用独立 prefix，Wine 的系统 D-Bus 指向隔离地址，不枚举宿主蓝牙设备。

`tests/gdiplus-render-check.cpp` 不读取个人图片；分别在新旧运行时执行并逐字节比较输出，每次 144 个场景。

```sh
i686-w64-mingw32-g++ -O2 -std=c++11 -static-libstdc++ -static-libgcc \
  tests/gdiplus-render-check.cpp -lgdiplus -o gdiplus-render-check.exe
```

64 位将编译器改为 `x86_64-w64-mingw32-g++`。计时依赖机器与负载，像素等价和计时结论分开。
桌面开窗动画和图片准备仍有耗时；截图黑屏本轮搁置，托盘菜单定位仍受限制。
音视频、附件、审批、已读人数及其他桌面未全面验收。


### 装饰角色与本轮候选

共享框架通过 `WINE_X11_FRAME_DECORATION_CLASSES` 接收应用声明的装饰类，使用分号分隔的完整 UTF-8 类名。
Ubuntu 启动器设置 `PerryShadowWnd`；其他应用应只声明实际装饰，未声明的内容窗口不会因可缩放样式被压到主体后方。
本轮绘制完成和窗口角色修订的构建、负对照及隔离回归见 `CODE-REVIEW.md` 和 `../validation.json` 的对应后续条目。
这些修订已随输入法组件打包；当前安装包与源码使用同一份净补丁，组件清单见 `release.json`。
