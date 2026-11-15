# 回归测试

回归覆盖本项目已经修复和测试过的窗口、绘制、输入、文件、设备及启动场景。
统一入口运行构造测试；真实企业微信、niri 和 KWin 的操作另列清单，结果均记录所用版本和组件指纹。

## 运行

需要完整的 Wine WoW64 运行库、对应补丁源码，以及 Python GI/Pillow、GNOME/Mutter、Xwayland、
PipeWire、GStreamer、双架构 MinGW、Xvfb、Openbox 和 xcompmgr。
输入法用例还需要 IBus，UDisks 用例需要 libdbus 开发文件。
CEF 内存组需要 bwrap，读取打包模板中的 CEF 文件，不使用账号目录。

```sh
python3 ubuntu/wine-x11-fix/tests/run-suite.py \
  --files /absolute/package-files \
  --source /absolute/patched-wine-source \
  --previous-files /absolute/previous-package-files \
  --output /absolute/new-qa
```

输出目录应为新的测试目录。套件顺序运行各组，使用空白 prefix、私有显示器和私有 D-Bus，
不使用真实账号。进度显示在终端，`result.json` 汇总每组退出码和日志路径。
任何一组失败，最终退出码为 1；已知问题也保留失败结果。
成功组完成后会清理其临时 Wine prefix，保留日志、截图和夹具；失败组保留 prefix。
需要保留成功组环境时，使用 `--keep-prefixes`。

套件默认与启动器一样开启 PE/CEF 共享缓存，并把实际开关写入报告；可用同名环境变量显式设为 `0` 做对照。
光标组默认用 `ubuntu/release.json` 校验组件指纹；其他候选可通过 `--runtime-manifest` 指定已有的指纹清单。
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
| `upgrade` | 全新启动、无 7z 首次启动、旧进程继续运行、退出后更新、同版本不重复复制、缺失的双架构 SLWGA 恢复、账号数据与模板独立 |
| `prefix-settings` | 100%/200% 自动 DPI、手工 120 DPI、恢复自动设置、运行中跳过配置，以及中文缺字正反例 |
| `popup` | 零尺寸与 1×1、普通与分层工具窗、边缘菜单、透明度、颜色键、形状、输入区域、重显和显式激活 |
| `anchor` | owner 提交前、提交后、宿主移动后更新附属层，以及独立弹窗的绝对定位 |
| `first`、`cancel` | 阴影先于正文、首帧上传与 XSync 完成顺序、未绘制即关闭、重开再绘制 |
| `first-odd-1/2`、`cancel-odd-2` | 奇数像素菜单在 100%/200% 下的首帧及取消重开；核对宿主取整后 Win32 矩形、可见像素和 XSync 完成 |
| `frame-sync`、`frame-reuse` | 待合成帧的绘制计数、消息分发前后像素，以及复用缓冲和五阶段布局更新 |
| `frame-compositor` | 实际 X11 合成源码的 resize/Expose 呈现、跨连接重绘通知顺序、隐藏/销毁竞争、InputOnly 过滤及错误处理范围 |
| `surface-commit` | 实际提交分支在双架构真实 Win32 窗口中的路由：嵌套子窗口、外进程、重新设置 parent、独立 owned 弹窗，以及关闭共享外框的对照 |
| `resize`、`extents-*` | 尺寸与边距变化、真实移动延迟确认、几何未变时不等待确认、基础及扩展同步 |
| `foreign`、`foreign-dc` | 跨进程 GDI、暴露与重绘、隐藏重显、移动、绘制重入及可见像素更新 |
| `own-dc`、`surface-lock` | CS_OWNDC、caret、擦背景、DC 重绑、surface 引用及 USER 锁释放顺序 |
| `roles`、`input` | 装饰与内容角色、置顶切换、零尺寸提升、透明穿透、不激活菜单的完整点击及预览层级 |
| `create`、`cards` | 创建期间改样式或 parent；成员卡与预览的隐藏、重显、后台顺序、重新激活及跨窗口排序；核实宿主注入的顺序，指针输入单独验证 |
| `maximize-1/2` | 双屏 100%/200%、主副屏交换和负原点、偏移、自定义与默认约束、最大化、还原、拖动及最小化恢复；检查完整过程中的外框尺寸 |
| `workarea-1/2` | 面板隐藏与恢复、最大化工作区变化、无尺寸变化的更新，以及阴影和共享框架控制组 |
| `fullscreen-1/2` | 主动全屏、保留最大化标志的无边框全屏、连续最大化后立即全屏、退出后恢复 |
| `reentrant-fullscreen` | 在宿主 WM_SIZE 回调中，应用明确请求全屏 |
| `pending-native-minimize` | 主体等待绘制时由桌面最小化，再恢复尺寸、像素和窗口状态 |
| `display-removal`、`native-size` | 显示器移除、原点重绑定、裁切与恢复，以及原生尺寸的零值、边界和整数范围 |
| `ime-*` | 32/64 位、96/192 DPI、DPI unaware、普通与共享框架、混合缩放、焦点切换、composition、CFS_RECT 的区域定位、POINT/FORCE_POSITION 的插入点及候选锚点 |
| `ime-process-32-32/32-64/64-32/64-64` | 原生外层与外进程子窗口的组合输入、UTF-16 代理对、候选定位、焦点生命周期、过期与非法消息、完成和取消，以及没有新 fd 通知的 Xlib 缓存事件 |
| `xim-lifecycle` | 提取实际 XIM/IMM32 源码，以 ASan/UBSan 验证两 XIC 状态隔离、迟到回调、重置及 focus-in 中的销毁重入、失焦时的原窗口身份和跨 XIC 组词转移 |
| `xim-reconnect-32/64` | 真实 IBus 六次停止、重启，12 个 GUI 线程在服务器停止时退出和重建，核对每次 XOpenIM 的显示连接所有者 |
| `ime-continuous-32/64` | 真实 IBus/XIM 与确定性词语引擎，以 8 ms 间隔输入四轮词语，核对跨进程正文的全部提交及原生 owner 的输入法开启状态 |
| `cursor-32/64` | 外进程光标的箭头、文本和链接角色、实际像素及位置 |
| `gdiplus` | 双架构各 144 种缩放、插值、alpha、边缘和变换组合；输出、背景、绘制区域及耗时记录 |
| `foreground-policy` | 标题栏助手在原生恢复路径中不再排队第二次还原 |
| `popup-focus-32/64` | 非受管 owned 弹窗实际持有 X 焦点时，不被 WM 的 owner/桌面前台同步关闭；各 20 次焦点和可见性采样 |
| `preview-shadow` | 两种窗口模式下预览阴影的 owner/进程边界、矩形保持，以及新建阴影的 SHOW 事件处理 |
| `software-licensing` | 32/64 位 SLWGA 模块加载、导出、无效参数和不支持查询的失败契约；不声明正版查询成功 |
| `clipboard` | 32/64 位真实 CF_HDROP 经 GTK/GIO 复制；英文、中文、空格、特殊字符、多文件、ANSI 与文本对照 |
| `native-dialogs` | 32/64 位文件选择、保存、过滤器、取消、重用、初始目录通知、文件视图回退、COM 回调、服务退出、异常响应及文件管理器接口 |
| `pnp-32/64`、`pnp-queue` | 设备关系属性、长度与类型、旧缓存、重复通知合并和关系更新 |
| `bluetooth-names` | 直接编译实际名称缓存函数，四线程增减引用和 40,000 个名称的 ASan/LeakSanitizer 回收检查 |
| `udisks` | 无关通知过滤、路径和成员边界、合法设备变化、服务换主及 UDisks1 回退 |

旧的 `run-frame-move-race.py` 针对按样式自动合并的旧实现，保留作历史定位材料。
当前附属坐标协议由 `anchor` 验证；旧实验及本轮迁移草稿均未计入正式结果。
来源、坐标语义和迁移问题见[旧测试复核](../CODE-REVIEW.md#旧测试复核)。

`ime-process-*` 使用私有 Mutter/Xwayland、IBus 和两个真实 Win32 进程。
测试驱动只在私有 DISPLAY 中注入与 XIM 相同的 Unix 驱动入口；不加载到真实企业微信。
结果核对两个进程实际映射的 core/驱动及 IMM32 指纹，并检查 IBus 收到的光标坐标。
队列用例在最终 `XFlush` 中放入一个无 fd 唤醒的原生事件；完成/取消检查由外层原生进程调用 `XmbResetIC`。
这些用例验证 Wine 消息与 XIM 契约；CEF 接口选择及真实正文、主题间切换另由本机客户端验证。

`ime-continuous-*` 使用测试引擎生成固定的“测试文件中文”，避免用户词库和学习状态改变预期。
引擎通过真实 IBus daemon 和 XIM 前端提供预编辑与提交；未替换 Wine 的回调或重置函数。
`--expect-failure` 只用于旧运行库负例，不能计入新版功能通过。需要 GI IBus 绑定与 libXtst。
空 Windows composition 的完成、取消另在 `ime-process-*` 中验证，不应重置待送达的原生词语。

`native-dialogs` 包含双架构 70 项文件接口检查。视图用例覆盖初始目录通知、首次和选择中途查询
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
