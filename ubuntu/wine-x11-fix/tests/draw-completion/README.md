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

四组用例分别覆盖先创建 caret 后绘制、正文绘制期间创建 caret、仅 caret 绘制、仅 DC 读回。
先绘制绿色旧帧，再通过 resize 建立待完成的新 surface。所有持有应用 DC 的阶段，以及没有应用写入的
释放阶段，桌面像素必须保持旧绿色；有效应用 ReleaseDC 之后必须显示新蓝色。每个阶段连续采样三次。
测试处理原生映射和配置消息，但不执行另一轮 WM_PAINT 来补救遗漏的 DC 完成通知。
输出记录 core/driver SHA256、逐阶段像素及截图；失败返回 1。不能用“不是蓝色”代替旧帧仍然完整的断言。

`run-surface-region-lock.py` 从指定 Wine `dlls/win32u/window.c` 提取生产函数，使用 API 替身检查
区域更新进入 surface 操作前已释放 USER 锁，并验证无 surface、区域查询失败、RTL、shape/clip 组合
和窗口在解锁后移除 surface 引用时的引用平衡。它不启动 Wine，也不是实际多线程死锁的复现。
调用方 `apply_window_pos` 的外层 USER 锁必须另行审查；只修 helper 内层锁不能满足这个要求。

```sh
python3 run-surface-region-lock.py /absolute/wine/dlls/win32u/window.c /absolute/result.json
```
