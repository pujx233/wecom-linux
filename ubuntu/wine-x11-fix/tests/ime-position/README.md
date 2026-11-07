# 输入法位置回归

夹具读取实际 IBus `SetCursorLocation` 请求，并与 X11 客户区、Win32 锚点转换后的物理坐标比较。
测试使用空白 prefix、私有 Mutter/Xwayland 和 IBus，不操作真实客户端。

## 运行

```sh
python3 run-isolated.py --runtime /absolute/wine --output /absolute/new-qa \
  --name pm192 --dpi 192 --awareness pm
```

需要 frame-composition 的桌面依赖、IBus、dbus-monitor、X11 库和对应 MinGW 编译器。
`--driver`、`--core` 默认取 runtime，也可同时指定成套组件。每个 `--name` 创建独立 runtime overlay
和 prefix，报告名称不可重复。结果记录 core、driver、server、IMM32 和夹具指纹，并核对实际映射。

| 参数 | 作用 |
| --- | --- |
| `--dpi 96` / `--dpi 192` | 普通与高 DPI。 |
| `--bits 32` / `--bits 64` | 两种 Windows 架构及对应 IMM32。 |
| `--awareness unaware` | 96 DPI 应用坐标到高 DPI 原生窗口的转换。 |
| `--frame 0` | 普通 X11 窗口控制组。 |
| `--preedit position` | server-side preedit，插入点保持顶边语义。 |
| `--mixed-scale` | 私有双屏 100%/200%，增加六项跨屏移动与锚点更新。 |
| `--candidate` | 增加 CFS_CANDIDATEPOS、CFS_EXCLUDE 和移动后的排除区域锚点。 |

## 请求语义

默认 25 项覆盖 caret 移动、换行、24/48 单位高度、composition point、FORCE_POSITION、
CFS_RECT、移动、最大化、还原、切换焦点和销毁 caret。
两个 CFS_RECT 用例使 ptCurrentPos 与 rcArea 左上角不同，按微软接口约定检查 rcArea 定位，
避免把不参与该模式的点坐标误作期望。
CreateCaret、SetCaretPos、ShowCaret 必须成功，显式请求经公开 IMM32 API 进入 win32u。

callbacks 模式下，只有输入线程、焦点 HWND、caret HWND 和插入点均匹配时，
POINT/FORCE 请求使用真实 caret 底边，防止候选框遮住文字。
无关或失效 caret 保留调用方原位置；position preedit 保留文字插入点顶边语义。
显式 candidate point 不因同位置 caret 而改变，EXCLUDE 使用排除区底边。

坐标判定使用 ClientToScreen、LogicalToPhysicalPointForPerMonitorDPI 和 XTranslateCoordinates，
并单独核对 XGetGeometry 尺寸。DPI 取应用上下文的 GetDpiForWindow 与显示器的 raw DPI；
正尺寸按 MulDiv 舍入后在共同逻辑精度比较，位置要求精确相等。
报告同时保留原始 Win32 期望、原生期望、原点、尺寸和 DPI 比例，便于定位转换差异。

## 覆盖边界

CFS_RECT 使用 rcArea；POINT/FORCE_POSITION 使用 ptCurrentPos，分别按调用模式验证。
跨进程输入宿主、自动更新与显式请求的持久策略，以及屏幕边缘输入法面板翻转另需实测。
失败以非零退出码或 `passed: false` 表示，采集完成本身不计通过。

参数约定见 [COMPOSITIONFORM](https://learn.microsoft.com/windows/win32/api/imm/ns-imm-compositionform)。
