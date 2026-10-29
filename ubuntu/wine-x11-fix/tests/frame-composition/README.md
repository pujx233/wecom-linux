# 原生合成、弹窗输入与双屏最大化回归

这些实验使用合成像素和测试窗口，不运行企业微信，不读取个人账号。GNOME、Xwayland、
PipeWire、D-Bus、Wine prefix 与配置都在独立目录和私有会话中运行，测试结果写入该目录。
输入测试只向私有虚拟显示器发送鼠标事件。退出时先关闭私有 Mutter，再清理其子进程。

需要 GNOME Shell/Mutter、Xwayland、PipeWire 命令行工具、GStreamer 的 PipeWire/PNG 插件、
Python 的 PyGObject/Pillow，以及 `x86_64-w64-mingw32-gcc`。使用完整的私有 Wine WoW64 runtime。

```sh
export WECOM_QA_ROOT=/absolute/disposable/wecom-frame-qa
mkdir -p "$WECOM_QA_ROOT"
touch "$WECOM_QA_ROOT/.wecom-frame-qa"
cp -a /absolute/private-wine "$WECOM_QA_ROOT/wine"
python3 run-foreign-frame.py
python3 run-popup-input.py
python3 run-frame-roles.py
python3 run-maximize.py
python3 run-create-reparent.py
python3 run-frame-move-race.py
python3 run-frame-move-race.py --create-after-move
python3 run-frame-move-race.py --pending-move
python3 run-frame-move-race.py --pending-move --create-after-move
```

运行前，该目录中不能有其他测试进程。不存在 prefix 时，脚本在私有显示器中执行 wineboot。
不要复制已登录的企业微信 prefix。`.wecom-frame-qa` 标记是对可丢弃测试目录的明确确认。

`run-foreign-frame.py` 创建静止的主窗口和分层装饰，再让另一个进程绘制红、蓝内容。
它同时检查 GDI 读回、原生源 pixmap 和桌面合成后的像素，防止把“已经画进后台位图”误判为“用户已经看到”。
共绘制八次；第五次由原生 resize 引起的 Win32 状态同步触发，应用在该回调中等待外部绘制并重入消息循环。
旧版会消费合成通知却丢掉更新，源已变红而桌面仍显示上一次的蓝色。修订后，解锁会重新提交待合成内容。
源像素在桌面检查结束后读取，避免读回影响可见性判定。每次更新超过一秒仍未显示即失败。

`run-popup-input.py` 使用独立 X11 窗口接收穿透事件。普通工具弹窗和非分层透明工具弹窗必须
各收到三组完整点击，底层窗口不能收到事件；分层透明窗口则必须允许六个按下/松开事件穿过。
弹窗临时改变激活样式时，原生窗口身份也必须保持不变。
它还检查头像式 owned 预览在其 owner 上方，以及两个带共享框架的同 owner 窗口能按明确请求往返换序。
首次映射后的顺序以稳定后的 Win32 枚举为准，避免将窗口管理器激活顺序当作绘制错误。

`run-frame-roles.py` 验证窗口样式相同但角色不同的两个窗口：普通可缩放分层内容必须在主体上方，
只有通过 `WINE_X11_FRAME_DECORATION_CLASSES` 明确声明的装饰类才放在主体后面。
该环境变量使用分号分隔、区分大小写的完整 UTF-8 类名；测试同时验证列表中第二项的匹配。
另一组在普通 owner 上创建置顶弹窗，并对普通弹窗执行置顶、取消置顶。
检查共享/独立原生框架身份，同时用无关红色窗口遮挡，读取桌面像素确认实际层级。
这些判定不以 Wine 返回的 Win32 Z 序作为唯一依据。报告记录实际 core 和 driver 指纹。
同一脚本还验证 0×0 owned 弹窗提升为独立框架、取消置顶和恢复正常尺寸：Win32 空矩形保持不变，
独立原生框架必须为合法的 1×1。`--zero-size-only` 可单独运行这组回归，旧版会在提升时发出非法的
0×0 XCreateWindow 并退出。该脚本将系统 D-Bus 指向测试目录下不存在的 socket，隔离宿主蓝牙枚举。
Ubuntu 启动器声明企微自己的 `PerryShadowWnd`，Wine 中不内置该应用类名；这是明确的应用角色适配。

`run-maximize.py` 创建两块 200% 缩放的虚拟屏幕（3200×2000 与 3840×2160），交换主屏以覆盖
Wine 坐标中的正、负副屏原点。标准 X11 dock strut 为两屏各保留 102 像素底栏，由 Wine 读取工作区；
不在应用中人为减小最大化尺寸。测试窗口用监视器相对坐标返回最大化约束，阴影在移动和缩放时跟随。
它检查从两屏最大化、还原到原矩形、副屏靠近屏幕边界，以及普通和最大化窗口最小化后的恢复。
除 popup 样式外，还覆盖企微采用的 overlapped 顶层样式，并记录应用在 `WM_WINDOWPOSCHANGING`
观察到的最大化提议；即使窗口管理器稍后纠正了最终位置，提议原点落错屏也会失败。
一组非零位置偏移校验通用坐标转换，避免修复只针对 `(0,0)`。主、副屏 overlapped 用例还发出原生激活请求，
等待宿主自然恢复后，再调用应用的条件恢复逻辑，检查恢复最大化后再次还原的原始矩形。
这不是企微托盘回调的完整复刻，也不保证触发每一种迟到的宿主状态事件。
关闭共享框架时也验收主屏最大化后的最小化、恢复，以覆盖 Wine 通用恢复路径；无阴影作为另一控制组。
默认最大化约束会使无标题窗口进入 Wine 的 fullscreen 路径，
该组单独记录、不计入本次最大化验收；fullscreen 允许 Win32 与原生矩形存在同屏差异。
除了 Win32 矩形，它还检查实际 X11 主体与框架
的几何关系、目标屏幕和原生最小化状态。可见阴影必须与其 Win32 矩形一致，框架必须等于主体与阴影
的并集，避免只验证逻辑状态而漏掉跳屏、裁切、主体未扩大或旧 padding 膨胀的问题。
最大化后的标题栏拖动使用私有显示器的原生输入，并先核对实际指针位置和命中 XID。
还原既覆盖直接点击对应的状态转换，也覆盖最小化恢复后再还原、同一消息中快速最小化再恢复。
测试收集 frame 的 Map/Unmap 和 ConfigureNotify，区分真实与 synthetic 事件。
已映射期间，最大化框架不得超过工作区加声明的阴影；还原框架不得瞬缩到原主体尺寸以下。
未映射的重新管理中间尺寸保留记录，但不作为可见闪动判断。可用 `--case negative-primary-overlapped` 单独复测。
这些几何断言能发现瞬间错误尺寸，不能代替真实客户端的逐帧视觉验收。
这项测试输出 JSON 与 Wine 日志，并记录实际 `winex11.so` 与 `win32u.so` 的 SHA256；输入拖动和前两项同时输出截图。
验收失败时退出码为 1。

这些实验用于验证底层机制；真实企微的邮件、图片、分享记录、成员卡和双屏操作仍需要单独验收。

`run-create-reparent.py` 检查窗口尚在 `WM_NCCREATE`、未进入桌面 Z 序时的原生框架迁移。
一组在该回调中将普通 owned 弹窗改为分层工具窗口，使其从独立框架迁移至 owner 框架；另一组
在该回调中把 owner 的实际 parent 改为新的顶层 host，使旧 owner 框架销毁。
两组都要求正在创建的原生主体保持同一 XID，最终仍为 200×200，并且实际 X 父节点与预期框架一致。
另有不改样式、在 `WM_CREATE` 中改样式及改 parent 的三个控制组；可用 `--phase` 单独运行。
测试分别记录 `EnumWindows` 成功与是否找到当前 HWND，不能把枚举失败当成“尚未链接”；
检查窗口的实际 parent 使用 `GetAncestor(GA_PARENT)`，与 `WS_POPUP` 的 owner 区分。
就绪后通过消息队列完成一次状态请求，再查询原生几何，不使用固定延时作为通过依据。
报告中的 `last_error` 仅在 `CreateWindowEx` 返回 NULL 时有意义，成功返回不要求清除旧错误码。
该脚本记录 fixture、runner、driver、core 和 server 的前后指纹，将系统 D-Bus 指向不存在的私有 socket。
它验证这两条生命周期路径，不证明所有 CEF 白屏、进程退出或跨进程窗口创建问题已解决。

`run-native-size.py --source /absolute/wine-source --out /absolute/new-result-dir` 不启动 Wine 或显示器，
直接抽取生产代码的 RECT 边长转换函数，用 UBSan 检查零值、负值、65535/65536 和 INT32 跨端边界。
它只验证原生尺寸转换，不覆盖此前的矩形组合算术，也不能替代上面的真实窗口提升和尺寸恢复测试。

`run-frame-move-race.py` 用两个 UI 线程验证共享框架的坐标同步。默认先暂停 owner 消息循环，
由私有窗口管理器移动 native frame，再让另一线程更新附属层；`--create-after-move` 改为首次创建该层。
此时明确检查 Win32 owner 仍是旧坐标，附属层的原生坐标必须与请求一致。
`--pending-move` 检查相反顺序：只暂停私有 GNOME Shell，应用先提交 owner 移动，核对 Win32 已更新、
native frame 尚未移动，再更新或创建附属层。恢复后框架、正文、附属层和四边 extents 必须同时正确，
不能只修正系统先移动的路径。测试只暂停由私有环境标记识别的进程，退出时先恢复再清理。
Wine 服务初始化单独执行并记录耗时；窗口就绪和几何断言仍有独立超时，超时不能作为通过。
有 gdb 时，失败会在终止私有程序前尝试保存线程栈。该回归不验证真实企微正文或概览选框的视觉效果。
