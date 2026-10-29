# 绘制完成探针源码

这些是隔离验证使用的 Win32 探针，覆盖 caret 首帧、CS_OWNDC、DPI unaware 与读回/调整尺寸。
用 i686-w64-mingw32-gcc 编译，链接 user32/gdi32，在隔离的测试 prefix 和显示服务器中运行。
以上旧探针的合成器观察控制器依赖原隔离环境，不作为可直接运行的通用测试套件。
真实企微验收与隔离结果分开记录，见 ../../../validation.json。

`run-own-dc-caret.py` 是独立可运行的 CS_OWNDC 回归，复用相邻 frame-composition 目录的私有
GNOME/Xwayland/PipeWire 会话。它使用空白 prefix 和合成窗口，不运行企业微信或操作本机桌面。
依赖与相邻目录 README 相同；每次使用新输出目录：

```sh
/usr/bin/python3 run-own-dc-caret.py --runtime /absolute/private-wine --output /absolute/new-test-directory
```

这些用例显式启用本项目的 shared-frame / first-present 策略，先绘制绿色旧帧，再 resize 建立新 surface。
GetDC/ReleaseDC 不是 Win32 通用的显示事务边界，因此持有 DC 期间只记录像素，不要求必须保持旧绿色。
这里检查的是适配层的完成通知：有效应用写入在外层 ReleaseDC 后应可见，内部借用不得吞掉此前的写入。

八组用例覆盖先创建 caret 后绘制、绘制期间创建 caret、仅 caret 绘制、仅 DC 读回，
以及持有应用 DC 时调用 RDW_ERASENOW 的四组组合：回调外有无绘制、擦背景处理器有无绘制。
测试确认处理器收到一次 WM_ERASEBKGND，参数是应用持有的同一 CS_OWNDC。
擦背景处理器也是应用代码，其绘制可合法参与完成通知：仅擦背景的用例在外层 ReleaseDC 后，
检查红色矩形内的 `(10,10)`；其余有完整填充的用例检查 `(150,100)` 的蓝色。
仅 caret、读回和无绘制擦除的释放阶段仍检查旧绿色，这是本项目 first-present 策略的负例，
不能推广为所有 Win32 程序的显示保证。各色点连续采样三次，不声称单个色点证明整帧完整。

另两组在擦背景回调尚未返回时复用同一 HDC：缓存 DC 先销毁原窗口，CS_CLASSDC 则从 A 换绑到 B。
B 从创建起位于独立位置，先确认该处采样点为绿色，再只调整尺寸。B 绘制后持有 DC 到 A 回调返回，
检查旧隐式归还没有禁用 B 的 DC，且 B 的 ReleaseDC 能显示蓝色。
测试不执行另一轮 WM_PAINT 来补救遗漏的完成通知；最后的独立蓝色绘制验证后续仍可完成。
报告记录 core/driver SHA256、采样坐标、颜色及截图；held 阶段的 `passed: null` 表示仅观察，不计入通过判断。
另外四项 API 对照分别以完整、截短 HWND 调用 GetUpdateRect/GetUpdateRgn 并请求擦背景。
它们使用普通缓存 DC，确认回调一次且返回后 WindowFromDC 不再关联窗口，直接检查内部借用已归还；
这些对照不使用像素或首帧断言，截短句柄必须确实不同于完整句柄。

`run-surface-region-lock.py` 从指定 Wine `dlls/win32u/window.c` 提取生产函数，使用 API 替身检查
区域更新进入 surface 操作前已释放 USER 锁，并验证无 surface、区域查询失败、RTL、shape/clip 组合
和窗口在解锁后移除 surface 引用时的引用平衡。它不启动 Wine，也不是实际多线程死锁的复现。
调用方 `apply_window_pos` 的外层 USER 锁必须另行审查；只修 helper 内层锁不能满足这个要求。

```sh
python3 run-surface-region-lock.py /absolute/wine/dlls/win32u/window.c /absolute/result.json
```
