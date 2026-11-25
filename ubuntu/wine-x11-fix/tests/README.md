# 回归测试

回归覆盖本项目已经修复和测试过的窗口、绘制、输入、文件、设备及启动场景。
统一入口运行构造测试；真实企业微信、niri 和 KWin 的操作另列清单，结果均记录所用版本和组件指纹。

## 运行

需要完整的 Wine WoW64 运行库、对应补丁源码，以及 Python GI/Pillow、GNOME/Mutter、Xwayland、
PipeWire、GStreamer、双架构 MinGW、Xvfb、Openbox 和 xcompmgr。
输入法用例还需要 IBus，UDisks 用例需要 libdbus 开发文件。
连续组词用例在私有 Mutter 中预先建立虚拟键盘，通过其 RemoteDesktop 接口注入按键，
避免 Xwayland 的 XTEST 门户权限流程阻断输入。按键仍经过 Xwayland、IBus 和真实 Win32 正文进程。
CEF 内存组需要 bwrap，读取打包模板中的 CEF 文件，不使用账号目录。

```sh
python3 ubuntu/wine-x11-fix/tests/run-suite.py \
  --files /absolute/package-files \
  --source /absolute/patched-wine-source \
  --previous-files /absolute/previous-package-files \
  --output /absolute/new-qa
```

输出目录应为新的测试目录，放在空间充足的工作盘；CEF/PE 沙箱会隔离 `/tmp`，升级恢复也会同时创建模板副本。
套件顺序运行各组，使用空白 prefix、私有显示器和私有 D-Bus，不使用真实账号。
进度显示在终端，`result.json` 汇总每组退出码和日志路径。
显示编号属于当前命名空间，容器中的 `:0` 也可以是私有显示器。隔离由独立运行目录、Xauthority、
私有合成器的进程身份和软件包指纹确认，不依赖显示编号。
完整测试环境需要生成 `zh_CN.UTF-8` 和 `en_US.UTF-8` locale，以便分别覆盖中文和英文输入环境。
`launcher` 另用空 `LOCPATH` 检查系统未生成中文 locale 时的 `C.UTF-8` 选择。
`prefix-settings --locale-switch` 检查同一 prefix 在两种 locale 间往返后仍能绘制中文，隐藏宿主字体以免掩盖问题。
`native-dialogs` 使用包内 locale 选择器；可在空 `LOCPATH` 下重跑这组，验证缺少中文 locale 时的中文文件接口。
可增加 `--list-cases` 查看同一套参数注册的全部组。统一入口按各组注册的参数运行，单组调试请用对应脚本的命令参数。
任何一组失败，最终退出码为 1；已知问题也保留失败结果。
成功组完成后会清理其临时 Wine prefix，保留日志、截图和夹具；失败组保留 prefix。
需要保留成功组环境时，使用 `--keep-prefixes`。
摄像头枚举需要设备可访问，使用 `--camera` 加入；该组不采集视频帧。

套件默认与启动器一样开启 PE/CEF 共享缓存，并把实际开关写入报告；可用同名环境变量显式设为 `0` 做对照。
光标组默认用 `ubuntu/release.json` 校验组件指纹；其他候选可通过 `--runtime-manifest` 指定已有的指纹清单。
`mouse-queue` 在两种 Windows 位数下验证普通移动和滚轮合并，以及消息回调期间的新输入能独立送达。
设备属性组按原 DLL 的只读 PE 头映射核对身份，兼容执行页位于共享缓存文件的情况。

用 `--case` 选择需要重跑的组，例如：

```sh
python3 ubuntu/wine-x11-fix/tests/run-suite.py \
  --files /absolute/package-files --source /absolute/patched-wine-source \
  --output /absolute/new-qa --case clipboard --case first --case native-dialogs
```

只有 `upgrade` 组需要 `--previous-files`，用于验证运行中延后升级和退出后的下一次启动。
`cef-image-cache` 组提供 `--previous-files` 时，也会对比新旧运行库的 DLL 实际驻留占用。
各组原有脚本也可单独运行，使用方法见相应目录说明。
升级夹具通过正常关闭消息退出真实企业微信，确认 Wine 后台仍然驻留，再验证下一次启动完成更新。
运行中的应用、仅后台驻留、prefix 符号链接、服务错误和文件映射分别验证。

## 构造场景

| 测试组 | 覆盖内容 |
| --- | --- |
| `cef-image-cache` | 并发加载、重定位地址冲突、文件身份隔离、写时复制、封存、卸载释放、可写共享段及缓存失败回退 |
| `pe-image-cache` | 32/64 位 DLL 与 EXE、资源按需映射、只读页共享、重定位与 COW、卸载回收，以及创建文件、预留缓存头和预留节空间失败时的原加载器回退 |
| `launcher`、`launcher-clean` | 启动顺序、继承的 Wine 环境、忙碌状态、服务失败、注册表失败、两种启动路径的 CEF 开关及新旧输入路径互斥 |
| `upgrade` | 全新启动、无 7z 首次启动、旧进程继续运行、退出后更新、同版本不重复复制、双架构 SLWGA/user32 缺失恢复、实际加载的 user32 指纹、账号数据与模板独立 |
| `prefix-settings` | 100%/200% 自动 DPI、手工 120 DPI、恢复自动设置、忙碌配置跳过、中文缺字正反例和 locale 往返 |
| `popup`、`popup-owned-frame` | 旧模式和 DEB 模式下的尺寸、WM 管理、边缘菜单、alpha、形状、输入区域、重显和显式激活 |
| `anchor` | owner 提交前、提交后、宿主移动后更新附属层，以及独立弹窗的绝对定位 |
| `first`、`cancel` | 阴影先于正文、首帧上传与 XSync 完成顺序、未绘制即关闭、重开再绘制 |
| `first-odd-1/2`、`cancel-odd-2` | 奇数像素菜单在 100%/200% 下的首帧及取消重开；核对宿主取整后 Win32 矩形、可见像素和 XSync 完成 |
| `frame-sync`、`frame-reuse` | 待合成帧的绘制计数、消息分发前后像素，以及复用缓冲和五阶段布局更新 |
| `frame-compositor` | 实际 X11 合成源码的 resize/Expose 呈现、跨连接重绘通知顺序、隐藏/销毁竞争、InputOnly 过滤及错误处理范围 |
| `surface-commit` | 实际提交分支在双架构真实 Win32 窗口中的路由：嵌套子窗口、外进程、重新设置 parent、独立 owned 弹窗，以及关闭共享外框的对照 |
| `surface-transition` | 同进程容器携带外进程子窗口重新设置 parent，使顶层在直接绘制和内存表面间切换；双架构、96/192 DPI、DPI unaware 与矩形/圆角窗口的 972 项像素保留检查 |
| `resize`、`extents-*` | 尺寸与边距变化、真实移动延迟确认、几何未变时不等待确认、基础及扩展同步 |
| `foreign`、`foreign-dc` | 跨进程 GDI、暴露与重绘、隐藏重显、移动、绘制重入及可见像素更新 |
| `own-dc`、`surface-lock` | CS_OWNDC、caret、擦背景、DC 重绑、surface 引用及 USER 锁释放顺序 |
| `roles`、`input` | 装饰与内容角色、置顶切换、零尺寸提升、透明穿透、不激活菜单的完整点击及预览层级 |
| `create`、`cards` | 创建期间改样式或 parent；成员卡与预览的隐藏、重显、后台顺序、重新激活及跨窗口排序；核实宿主注入的顺序，指针输入单独验证 |
| `maximize-1/2` | 双屏 100%/200%、主副屏交换和负原点、偏移、自定义与默认约束、最大化、还原、拖动及最小化恢复；检查完整过程中的外框尺寸 |
| `workarea-1/2` | 面板隐藏与恢复、最大化工作区变化、无尺寸变化的更新，以及阴影和共享框架控制组 |
| `fullscreen-1/2` | 原版 Mutter 上的单屏全屏、连续最大化后立即全屏、退出后恢复，100% 下同时核对跨屏、横跨双屏及回到原屏的真实窗口几何 |
| `xim-stock-hook-control` | 模拟 GNOME Wayland 一次性启动 XIM 前端。记录 IBus 重启后选择区为空，以及测试另行启动前端后 Wine 的重连。该组通过仅表示这两个对照成立 |
| `reentrant-fullscreen` | 在宿主 WM_SIZE 回调中，应用明确请求全屏 |
| `initial-fullscreen` | 首次显示、隐藏重显、改变目标屏后重显；九次 Win32/原生几何及 EWMH 全屏显示器消息 |
| `fullscreen-host-reply` | 暂停隔离 WM，使单屏初始回执先于跨屏确认被客户端处理；恢复后核对九次 Win32/原生几何，防止回执覆盖应用约束 |
| `display-change-fullscreen` | 同一应用进程中将双屏横排改为竖排、交换主屏再还原；核对显示器缓存刷新及十二次全屏几何 |
| `pending-native-minimize` | 主体等待绘制时由桌面最小化，再恢复尺寸、像素和窗口状态 |
| `display-removal`、`display-removal-resize/move/update/minimized` | 显示器移除、原点重绑定、最小化恢复；待处理绘制、移动与 resize 时移除，检查重绘计数、update region 及主体/外框矩形 |
| `native-size` | 原生尺寸的零值、边界和整数范围 |
| `ime-*` | 32/64 位、96/192 DPI、DPI unaware、普通与共享框架、混合缩放、焦点切换、composition、CFS_RECT 的区域定位、POINT/FORCE_POSITION 的插入点及候选锚点 |
| `ime-process-32-32/32-64/64-32/64-64` | 原生外层与外进程子窗口的组合输入、UTF-16 代理对、候选定位、焦点生命周期、过期与非法消息、完成和取消，以及没有新 fd 通知的 Xlib 缓存事件 |
| `xim-lifecycle` | 提取实际 XIM/IMM32 源码，以 ASan/UBSan 验证两 XIC 状态隔离、迟到回调、重置及 focus-in 中的销毁重入、失焦时的原窗口身份和跨 XIC 组词转移 |
| `xim-reconnect-32/64` | 真实 IBus 六次停止、重启，12 个 GUI 线程在服务器停止时退出和重建，核对每次 XOpenIM 的显示连接所有者 |
| `ime-gnome-restarts-32/64` | GNOME 一次性前端、独立前端退出和两次 IBus 重启，在同一编辑框逐轮核对中文上屏，并检查默认 XIM 所有者及退出清理 |
| `ime-continuous-32/64` | 真实 IBus/XIM 与确定性词语引擎，以 8 ms 间隔输入四轮词语，核对跨进程正文的全部提交及原生 owner 的输入法开启状态 |
| `cursor-32/64` | 外进程光标的箭头、文本和链接角色、实际像素及位置 |
| `gdiplus` | 双架构各 144 种缩放、插值、alpha、边缘和变换组合；输出、背景、绘制区域及耗时记录 |
| `foreground-policy` | 标题栏助手在原生恢复路径中不再排队第二次还原 |
| `popup-focus-32/64` | 非受管 owned 弹窗实际持有 X 焦点时，不被 WM 的 owner/桌面前台同步关闭；各 20 次焦点和可见性采样 |
| `preview-shadow` | 两种窗口模式下预览阴影的 owner/进程边界、矩形保持，以及新建阴影的 SHOW 事件处理 |
| `software-licensing` | 32/64 位 SLWGA 模块加载、导出、无效参数和不支持查询的失败契约；不声明正版查询成功 |
| `clipboard` | 32/64 位真实 CF_HDROP 经 GTK/GIO 复制；英文、中文、空格、特殊字符、多文件、ANSI 与文本对照 |
| `clipboard-bitmap` | 同版四种位数组合和原生 GTK 逐像素比较。指定 `--previous-files` 时，另在旧 Wine 会话比较旧发新收及同位数新发旧收 |
| `camera`（显式启用） | 32/64 位 DirectShow 的 GetFormat、GetStreamCaps、EnumMediaTypes，重复枚举并核对 AM_MEDIA_TYPE 输出 |
| `native-dialogs` | 32/64 位文件选择、保存、过滤器、取消、重用、初始目录通知、文件视图回退、COM 回调、服务退出、异常响应及文件管理器接口 |
| `pnp-32/64`、`pnp-queue` | 设备关系属性、长度与类型、旧缓存、重复通知合并和关系更新 |
| `bluetooth-names` | 直接编译实际名称缓存函数，四线程增减引用和 40,000 个名称的 ASan/LeakSanitizer 回收检查 |
| `udisks` | 无关通知过滤、路径和成员边界、合法设备变化、服务换主及 UDisks1 回退 |

旧的 `run-frame-move-race.py` 针对按样式自动合并的旧实现，保留作历史定位材料。
当前附属坐标协议由 `anchor` 验证；旧实验及本轮迁移草稿均未计入正式结果。
来源、坐标语义和迁移问题见[旧测试复核](../CODE-REVIEW.md#旧测试复核)。

两组 `popup` 显式固定 `WINE_X11_OWNED_FRAME=0/1`，不继承终端中的模式或附属窗口类名。
旧模式中带 `WS_SYSMENU` 的阴影由 WM 管理，可被 WM 移回屏内，检查 Win32 与原生坐标同步及尺寸保持。
DEB 模式下同一固定 owned 阴影不交给 WM 重新定位，仍严格检查请求的边缘坐标、尺寸和输入穿透。
普通有标题窗口、应用窗口和可调整尺寸窗口在两种模式下都必须保留 WM 管理。

`ime-process-*` 使用私有 Mutter/Xwayland、IBus 和两个真实 Win32 进程。
测试驱动只在私有 DISPLAY 中注入与 XIM 相同的 Unix 驱动入口；不加载到真实企业微信。
结果核对两个进程实际映射的 core/驱动及 IMM32 指纹，并检查 IBus 收到的光标坐标。
队列用例在最终 `XFlush` 中放入一个无 fd 唤醒的原生事件；完成/取消检查由外层原生进程调用 `XmbResetIC`。
这些用例验证 Wine 消息与 XIM 契约；CEF 接口选择及真实正文、主题间切换另由本机客户端验证。

`ime-continuous-*` 使用测试引擎生成固定的“测试文件中文”，避免用户词库和学习状态改变预期。
引擎通过真实 IBus daemon 和 XIM 前端提供预编辑与提交；未替换 Wine 的回调或重置函数。
`--expect-failure` 只用于旧运行库负例，不能计入新版功能通过。需要 GI IBus 绑定与 libXtst。
空 Windows composition 的完成、取消另在 `ime-process-*` 中验证，不应重置待送达的原生词语。

`native-dialogs` 包含双架构 84 项文件接口检查，其中包含目录回调拒绝、重定向、对话框重用时更改起始目录，以及附件保存时进入子目录。
需要单独复现时，向该组脚本传 `--case` 指定用例。统一入口核对该组计划和实际执行数。
视图用例覆盖初始目录通知、首次和选择中途查询
`IShellBrowser`、回调内取消及同一对话框随后改用 Portal；同时核对回退后的目录与过期结果。
旧运行库在视图用例中返回成功却未提供所需接口，该负例单列，不计为新版通过。

`frame-compositor` 需要 X11、XComposite、XRender、Xext、XDamage 开发文件和 Xvfb。它从 `--source` 提取实际合成函数和
Wine X11 错误处理器，在私有 Xwayland 中使用两个真实 X11 连接制造窗口竞争；不替换错误返回值。
最后一个负例要求作用域外的 `BadMatch` 仍以退出码 1 结束，避免通过扩大忽略范围掩盖错误。
另从 `frame.c` 提取真实 Damage 回调，在独立 Xvfb 中延迟监听连接，让合成连接继续复制和绘制，
核对后续 Damage 通知及主体/外框像素；同一连接作为对照。Xwayland 不保证执行该服务器抓取，
因此时序用例使用 Xvfb，既有六项呈现和资源用例继续使用 Mutter。
该组检查合成和资源契约；真实 Win32 回调阻塞与 KWin 混合缩放的端到端对照另记验证摘要。

`surface-commit` 提取实际 `surface_paint` 提交分支和外进程通知入口，使用真实 Win32 父子、owner、
窗口属性及进程身份；`XSync` 和本地合成函数记录调用，用于检查通知对象和同步先后顺序。
32/64 位、启用及关闭共享外框共 32 项检查。该组不替代 X11 像素检查；
真实文档页的绘制、最大化及跨屏结果另记 `validation.json` 的 `issue45_2026_11_14`。

`pe-image-cache` 的磁盘失败用例分别在 `openat(O_TMPFILE)`、缓存头分配和缓存节分配时返回 `ENOSPC`。
后两项使用真实 `posix_fallocate` 调用边界，要求客户端正常加载、内容保持正确且没有使用缓存；
同时核对分配失败标记，避免未进入目标路径时误判通过。真实小 ext4 文件系统的耗尽对照另记
`validation.json` 的 `pe_cache_space_fix_2026_11_14`。

## 真实客户端

| 场景 | 操作与观察 |
| --- | --- |
| 版本与启动 | 核对进程实际映射的驱动、版本标记和 DEB 指纹；重复启动唤回现有窗口 |
| 拖动与缩放 | 慢速、快速往返拖动；正文、标题和阴影对齐；调整宽高；主副屏双向拖动 |
| 状态恢复 | 应用按钮和桌面快捷键最大化、还原；普通及最大化窗口最小化后唤回；前后台切换；同时核对正文、阴影的 Win32 和原生矩形 |
| DPI | 登录、主界面、聊天、菜单和智能助手的 96/192 DPI 显示；自动值与手工值分别核对 |
| 菜单与层级 | 会话、消息、图片右键菜单；成员卡、头像预览、已读名单和聊天记录侧栏；首次打开与反复开合 |
| 输入法 | 聊天与搜索的中文组合输入、候选位置、换行及窗口移动后的定位，测试后清空草稿 |
| 文件接口 | 原生上传窗口浏览中文路径并取消；图片另存为的中文显示；默认文件管理器打开目录并选中原文件 |
| 文件剪贴板 | 从真实附件复制英文、中文文件到 Linux 文件夹，并核对目标文件字节 |
| 跨进程页面 | 邮件正文首次加载与刷新；智能助手、微盘，以及机器人的独立聊天窗口 |
| 图片预览 | OCR 文字鼠标选择并复制；最大化/恢复、拖动、边缘缩放和关闭；测试后清空未发送的图片草稿 |
| 会议 | 快速会议实际进入会议窗口；不邀请他人，关闭摄像头，测试结束后确认会议已结束 |
| 显示变化 | 双屏布局、主屏变化、拔屏后的裁切和最小化恢复；锁屏解锁后的快慢拖动、应用按钮及桌面最大化还原、调整宽高和最小化唤回 |

### 双屏快速会议

在两块屏上分别从企业微信主窗口发起单人快速会议。先在 100% 缩放下记录普通会议窗口的宽高，之后沿用这组逻辑尺寸。
WeMeet 3.26.511.637 默认普通窗口曾测得 962×642。手工改变过窗口大小时应使用对应的基准尺寸。
在已登录会话的终端进入本测试目录，将 `files` 和 `prefix` 分别设为正在使用的包的 files 目录和 prefix 路径。

```bash
out=$(mktemp -d)
set -o pipefail
x86_64-w64-mingw32-gcc -O2 -Wall -Wextra -Werror -municode meeting-display.c \
  -o "$out/meeting-display.exe" -lshcore -luser32
WINEPREFIX="$prefix" WINESERVER="$files/wine/bin/wineserver" "$files/wine/bin/wine" \
  "$out/meeting-display.exe" --wait '快速会议' 962 642 | tee "$out/window.jsonl"
```

输出 `origin` 后从该屏的企微主窗口发起会议，保持两个窗口的位置。探针在标题首次匹配和一秒后各检查一次。
两次都检查会议是否完整落在发起屏能容纳它的方向上。跨过屏幕接缝时，即使两个窗口的大部分面积在同一屏，仍会报告 `placement_ok=false`。
探针还比较窗口和显示器的 Wine DPI，记录客户区像素，并按这个 DPI 换算基准外框尺寸。退出码 1 表示回归，2 表示前提不足。
已有会议可用 `--snapshot` 检查当前状态。

要核对实际绘制分辨率，在隔离会话启动前给本次测试进程设置 `WINEQT_QPA_PLATFORM=windows:verbose=2`、
`WINEQT_LOGGING_RULES='qt.qpa.windows=true;qt.qpa.backingstore=true'` 和 `WINEQT_FORCE_STDERR_LOGGING=1`。
单独保留这次会议进程从创建到采样结束的 Qt 日志，以普通窗口打开，在采样结束前保持尺寸。

```bash
python3 check-meeting-backing.py "$out/window.jsonl" "$out/meeting-qt.log"
```

脚本用 Win32 窗口句柄找到 Qt 窗口，比较最后实际提交的绘制缓冲和外部进程量到的客户区物理尺寸。
像素一致且窗口记录中的逻辑尺寸、原生 DPI 和目标 DPI 检查均通过时返回 0。有测量项不符返回 1。
缺少创建、缓冲尺寸或提交记录时返回 2。旧记录仅核对其中已有的测量项。首次选屏的结果由窗口探针单独报告。

真实客户端会接管 Qt 日志。在隔离 prefix 中也可使用 Wine 自带的 relay，仅记录会议进程的
`user32.CreateWindowExW`、`user32.GetDC`、`gdi32.BitBlt` 和 `user32.ReleaseDC`。
从发起前开始截取本次日志，并运行 `check-meeting-backing.py --gdi window.jsonl meeting-relay.log`。
此模式核对指定 HWND 的客户区是否收到过一次覆盖全尺寸的像素直拷贝。局部刷新不能证明全帧提交。

GNOME Wayland 使用分数缩放时，同时记录桌面设置中的输出分辨率、缩放和 `xrandr --listmonitors` 返回的像素尺寸。
例如 1920×1080 输出在 125% 时，XWayland 可能提供 3072×1728 像素。此时 1924 像素的客户区在面板上约占 1203 像素。
探针可在宽、高后接期望的 X11 DPI，计算式为 `96 × XRandR 宽度 × 桌面缩放 ÷ 面板宽度`。旋转输出时使用同一方向的尺寸。
保持会议打开，改变缩放后再用 `--snapshot` 采样。例如期望值为 192 时，Wine 显示器和窗口即使都停留在 96，也会报告 `output_dpi_ok=false`。
用左右屏分别发起首次会议，并交换主屏重测。`display-dpi.py` 覆盖分数缩放、混合缩放、旋转和输出不能匹配时的回退。

热切换要跟踪同一个会议。保持普通窗口打开，以非主屏为发起屏的首开位置仍用上面的 `--wait` 单独检查。

1. 运行 `meeting-display.exe --change-dpi 快速会议 962 642 192`。看到 `before-scale` 后改变桌面缩放。
   探针要求该 HWND 在原显示器上达到目标 DPI，且矩形连续一秒稳定。`after-scale` 给出实际客户区和尺寸判定。
2. 收到 `after-scale` 后记下从本场会议创建前开始的 GDI 日志字节数。
   运行 `meeting-display.exe --repaint 快速会议 HWND`，用上一步返回的 HWND 替换参数。
   将它输出的 `repaint` 行追加到该阶段的窗口记录中，再保存本阶段的 GDI 日志。
3. 运行 `check-meeting-backing.py --gdi --paint-offset 字节数 窗口记录.jsonl 本阶段日志`。
   检查器只接受该偏移之后在对应 HWND 上完成的全客户区直拷贝。绘制完整但逻辑尺寸错误仍算失败。
   保持会议打开，将目标改为 96，再做一次还原。每一阶段分别保存日志与偏移。

`dpi-message.c` 独立验证 Wine 的 `WM_DPICHANGED` 参数传递。分别用 i686 和 x86_64 的 MinGW
加 `-municode` 编译，依次运行两个位数的发送端，每次传入对端 exe 的 Windows 路径。
四种组合均检查异步投递被拒绝、同步传递完整的带负坐标矩形，并验证接收端改写矩形后发送端仍保留原值。
接收窗口只在测试子进程中创建。

要核对桌面实际显示的像素，在测试目录下运行原生 X11 对照。它只启动隔离的 GNOME、XWayland 和一个绘制色块的窗口。
主屏保持 100%，副屏切到 200% 再还原。每个阶段同时检查 X11 窗口的真实尺寸、主屏上的可见宽度和右缘色块。
输出中的 `configure` 是窗口管理器回报的尺寸，`drawable` 是 X 服务器中可供绘制的尺寸。

```bash
export WECOM_QA_ROOT="$(mktemp -d)"
touch "$WECOM_QA_ROOT/.wecom-frame-qa"
/usr/bin/python3 frame-composition/run-xwayland-scale.py
/usr/bin/python3 frame-composition/run-xwayland-scale.py --small
```

默认使用 1920×1080 和 3840×2160 两块虚拟屏，`--small` 使用 1600×1000 和 2560×1440。
真实会议还需在同一物理输出比较切换前后的会议内容宽度。对应实测见[运行中改变缩放](../CODE-REVIEW.md#会议运行中改变缩放)。

## 桌面环境

niri/XWayland 使用 `run-shape-clip.py --existing-niri` 检查形状外像素和缓冲复用，
并验证菜单开合、宽度调整、正文与外框像素、文件接口和中文标题。
中文标题的 xwayland-satellite 补丁另有四字缺字、英文像素、裁剪及上游单测。

KWin 使用 `run-kwin-first-transaction.py` 读取基础 XSync 计数、`_XWAYLAND_ALLOW_COMMITS` 和合成像素，
覆盖首次映射与两次重开；真实菜单还需检查焦点、点击，以及双屏 100%/130% 的位置和尺寸。
显卡、桌面版本、输出布局及实际缩放写入报告。

构造测试、真实客户端和不同合成器分别记录结果；单次运行的报告不代替其余清单。
当前未通过或尚未重测的项目见 [review 记录](../CODE-REVIEW.md)和[验证摘要](../../validation.json)。

### XIM 重连

`ime-position/run-reconnect.py` 在独立桌面和 D-Bus 下启动真实 IBus，
反复重启输入法，同时销毁、重建 Wine GUI 线程。
探针按显示连接记录创建线程和 `XOpenIM` 调用线程；32/64 位均须没有跨线程调用。
`--expect-cross-thread` 只供旧实现负例使用，不代表新版功能通过。
统一套件的 `xim-reconnect-32`、`xim-reconnect-64` 使用正常通过条件。

## RC12 绘制和 DPI 消息回归

统一入口增加四组原生 GDI/DC、`dpi-message` 和 `fullscreen-host-reply` 检查。
使用 `--camera` 的完整矩阵共 94 组。`fullscreen-host-reply` 只暂停其私有 GNOME/Mutter 进程，
通过专用会话标记确认进程归属，并在正常及失败出口恢复；宿主桌面不参与。
前者关闭 ClientSideGraphics，验证直接 GDI 绘制的尺寸、像素与外框提交顺序。
后者覆盖 32→32、32→64、64→32、64→64，检查建议矩形传递、输入缓冲不回写和异步消息拒绝。
完整回归使用最终 DEB 解出的运行库、适配脚本、测试及组件清单。
动态 DPI 的实验未纳入 RC12，也不计为通过；实际会议的选屏、分数缩放和动态缩放须另做现场验证。

真实文档测试先核对文档 HWND、父窗口和顶层 root，再采样对应顶层的主体与外框。
文档可能作为主窗子页或独立窗口存在；禁止直接向文档子窗口发送最大化、还原和拖动操作。

## RC16 OLE 与恢复焦点

`clipboard-ole` 用两个架构的 IDataObject 发布者和读取者核对 36 条路径：
多介质位图、格式枚举、重复格式、目标设备和 OleFlushClipboard 后的读取。
`restore-focus-32/64` 与 `restore-foreground-32/64` 在私有 X11 上控制 ICCCM 消息顺序，
检查 Win32 前台与原生焦点一致，覆盖先还原和先激活的顺序。
RC16 的实机记录另有聊天到搜索的同窗口串词，见下一节的 RC17 修复和测试。

## RC17 逻辑焦点和 XIM 回调

启用 `--camera` 的完整矩阵为 101 组，新增两组：

- `richedit-ime`：32/64 位分别覆盖启用、关闭和缺少 DuiLib，检查全部 18 个方法的参数与返回值、
  COM identity、对象释放、调用方已有聚合及配置被覆盖后的重新激活。每项 2,907 次检查。
- `xim-callbacks`：实际包内 libX11 连接私有 IBus，以真实 Set/Get/Reset 请求检查回调及时派发、
  FIFO、重入不重复和销毁时释放剩余队列，80 轮共 480 个上下文、6,083 次检查。

测试使用 DEB 内的精确 Xlib 源码读取私有协议结构；不复制回调实现。
输入法测试的驱动副本同时链接包内私有 ELF 依赖，避免漏测该库。
实机还需快速输入 `nihao`，直接点击搜索输入 `wenjian` 并按空格：搜索为“文件”，聊天保留“你好”。
重复测试时直接清空搜索再点聊天，不在空搜索按 Escape，以免触发企微的关闭到托盘行为。

## 8~rc3 候选位置回归

启用 `--camera` 的当前完整矩阵为 105 组。新增的 32 位、96 DPI 和 DPI unaware candidate 组，
与原有 candidate、普通外框、混合缩放和 position preedit 对照一起运行。
检查显式候选位置之后的每次通知，覆盖 composition/caret 顺序、临时 1 像素 caret、
多候选列表、IMC 重建与恢复、未关联上下文及通知重入。

最终完整 DEB 已通过 105/105 组，文件对话框完整执行 84 项。真实客户端的聊天和搜索输入由用户验证稳定，
聊天位置采样在首次观察到显式候选请求后没有再出现高度交替。结果及 DEB SHA256 保存在包旁的 `validation.json`。
