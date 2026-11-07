# 回归测试

回归覆盖本项目已经修复和测试过的窗口、绘制、输入、文件、设备及启动场景。
统一入口运行构造测试；真实企业微信、niri 和 KWin 的操作另列清单，结果均记录所用版本和组件指纹。

## 运行

需要完整的 Wine WoW64 运行库、对应补丁源码，以及 Python GI/Pillow、GNOME/Mutter、Xwayland、
PipeWire、GStreamer、双架构 MinGW、Xvfb、Openbox 和 xcompmgr。
输入法用例还需要 IBus，UDisks 用例需要 libdbus 开发文件。

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

用 `--case` 选择需要重跑的组，例如：

```sh
python3 ubuntu/wine-x11-fix/tests/run-suite.py \
  --files /absolute/package-files --source /absolute/patched-wine-source \
  --output /absolute/new-qa --case clipboard --case first --case native-dialogs
```

只有 `upgrade` 组需要 `--previous-files`，用于验证运行中延后升级和退出后的下一次启动。
各组原有脚本也可单独运行，使用方法见相应目录说明。
升级夹具通过正常关闭消息退出真实企业微信，确认 Wine 后台仍然驻留，再验证下一次启动完成更新。
运行中的应用、仅后台驻留、prefix 符号链接、服务错误和文件映射分别验证。

## 构造场景

| 测试组 | 覆盖内容 |
| --- | --- |
| `launcher`、`launcher-clean` | 启动顺序、继承的 Wine 环境、忙碌状态、服务失败及注册表失败 |
| `upgrade` | 全新启动、无 7z 首次启动、旧进程继续运行、退出后更新、同版本不重复复制、账号数据与模板独立 |
| `prefix-settings` | 100%/200% 自动 DPI、手工 120 DPI、恢复自动设置、运行中跳过配置，以及中文缺字正反例 |
| `popup` | 零尺寸与 1×1、普通与分层工具窗、边缘菜单、透明度、颜色键、形状、输入区域、重显和显式激活 |
| `anchor` | owner 提交前、提交后、宿主移动后更新附属层，以及独立弹窗的绝对定位 |
| `first`、`cancel` | 阴影先于正文、首帧上传与 XSync 完成顺序、未绘制即关闭、重开再绘制 |
| `first-odd-1/2`、`cancel-odd-2` | 奇数像素菜单在 100%/200% 下的首帧及取消重开；核对宿主取整后 Win32 矩形、可见像素和 XSync 完成 |
| `frame-sync`、`frame-reuse` | 待合成帧的绘制计数、消息分发前后像素，以及复用缓冲和五阶段布局更新 |
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
| `cursor-32/64` | 外进程光标的箭头、文本和链接角色、实际像素及位置 |
| `gdiplus` | 双架构各 144 种缩放、插值、alpha、边缘和变换组合；输出、背景、绘制区域及耗时记录 |
| `foreground-policy` | 标题栏助手在原生恢复路径中不再排队第二次还原 |
| `clipboard` | 32/64 位真实 CF_HDROP 经 GTK/GIO 复制；英文、中文、空格、特殊字符、多文件、ANSI 与文本对照 |
| `native-dialogs` | 32/64 位文件选择、保存、过滤器、取消、重用、COM 回调、服务退出、异常响应及文件管理器接口 |
| `pnp-32/64`、`pnp-queue` | 设备关系属性、长度与类型、旧缓存、重复通知合并和关系更新 |
| `bluetooth-names` | 直接编译实际名称缓存函数，四线程增减引用和 40,000 个名称的 ASan/LeakSanitizer 回收检查 |
| `udisks` | 无关通知过滤、路径和成员边界、合法设备变化、服务换主及 UDisks1 回退 |

旧的 `run-frame-move-race.py` 针对按样式自动合并的旧实现，保留作历史定位材料。
当前附属坐标协议由 `anchor` 验证；旧实验及本轮迁移草稿均未计入正式结果。
来源、坐标语义和迁移问题见[旧测试复核](../CODE-REVIEW.md#旧测试复核)。

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
