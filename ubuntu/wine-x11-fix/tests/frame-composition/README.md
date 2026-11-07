# 窗口与合成测试

统一运行入口和完整清单见 [tests/README.md](../README.md)。本目录测试使用空白 prefix、私有
GNOME/Mutter、Xwayland、PipeWire 和 D-Bus；输入只发送到私有显示器。结果保存实际组件指纹。

## 运行

首帧、附属坐标、同步、形状裁剪等脚本自行准备目录：

```sh
python3 run-attached-anchor.py --runtime /absolute/wine --output /absolute/new-qa
python3 run-frame-sync.py --runtime /absolute/wine --output /absolute/new-qa
python3 run-frame-sync-reuse.py --runtime /absolute/wine --output /absolute/new-qa
python3 run-shape-clip.py --runtime /absolute/wine --output /absolute/new-qa
WECOM_QA_SCALE=2 python3 run-first-transaction.py /absolute/new-qa /absolute/wine first
WECOM_QA_SCALE=2 python3 run-first-transaction.py /absolute/new-qa /absolute/wine cancel --cancel
```

其他脚本通过 `WECOM_QA_ROOT` 选择已标记的测试目录，每组使用单独目录：

```sh
export WECOM_QA_ROOT=/absolute/new-qa
mkdir "$WECOM_QA_ROOT"
touch "$WECOM_QA_ROOT/.wecom-frame-qa"
ln -s /absolute/wine "$WECOM_QA_ROOT/wine"
python3 run-maximize.py --scale 1 --workarea-cycle --fullscreen
```

目录中不能有运行中的测试进程。需要 GNOME/Mutter、Xwayland、PipeWire、GStreamer 的
PipeWire/PNG 插件、Python GI/Pillow 和双架构 MinGW。`run-suite.py` 负责逐组创建这些目录。

## 合成与坐标

| 脚本 | 检查内容 |
| --- | --- |
| `run-first-transaction.py` | 阴影先画、正文延迟时不提前完成 XSync；上传和合成后提交。`--cancel` 检查未画即关闭、重开和再次绘制；`--odd-size --compact` 检查奇数尺寸在 100%/200% 下的宿主取整、Win32 几何和可见像素。 |
| `run-attached-anchor.py` | owner 提交前后更新、原生位置领先 Win32 的附属更新、独立弹窗的绝对定位；核对外框和各层几何。 |
| `run-frame-sync.py` | resize 复用 surface 后，未分发合成消息时保留旧像素和奇数计数，分发后更新像素并完成计数。 |
| `run-frame-sync-reuse.py` | 五阶段布局与缓冲复用的计数、像素和完成顺序。 |
| `run-resize-drawable.py` | 先更新绘制子窗口，再合成新尺寸，避免复制旧尺寸内容。 |
| `run-resize-extents.py` | 正文与边距变化、真实几何确认、原生几何不变的提交，以及基础/扩展同步计数。 |
| `run-foreign-frame.py` | 外进程八次 GDI 更新，包含宿主 resize 回调中的重入；同时检查源 pixmap 与合成像素。 |
| `run-shape-clip.py` | 故意污染 backing pixmap 的形状外区域；源污染保留，合成目标必须透明，缓冲复用不得积累残留。 |

`AnchorOrderShadow;AnchorOrderTitle` 显式声明为附属类，只有 shadow 声明为装饰；独立弹窗不声明。
这样分别检查 owner 相对布局和屏幕绝对定位，不把所有 owned 窗口当成装饰。

`run-resize-extents.py` 默认冻结私有 WM 后提交真实移动，等待正确确认。
`WECOM_QA_STATIONARY=1` 检查几何未变，`WECOM_QA_NO_EXTENDED_SYNC=1` 检查只有基础同步，
`WECOM_QA_DELAY_WM=0` 检查正常直接提交。基础模式公布一个计数器，扩展模式公布两个。

## 输入与生命周期

| 脚本 | 检查内容 |
| --- | --- |
| `run-popup-input.py` | 普通与非分层透明窗口接收完整点击，分层透明窗穿透；不激活菜单保留 owner 焦点，点击命令可执行；预览在 owner 上方。 |
| `run-frame-roles.py` | 内容与装饰角色、置顶切换、独立/共享框架；0×0 窗口提升后原生窗口为合法 1×1，Win32 空矩形保持不变。 |
| `run-create-reparent.py` | WM_NCCREATE / WM_CREATE 中改样式或 parent；窗口保持 XID，最终尺寸、父节点和框架正确。 |
| `run-card-stack.py` | 普通、重显、最大化、还原、同 owner 预览和外部应用插入；检查原生顺序、像素、点击归属及稳定后不持续纠正。 |
| `run-native-size.py` | 从源码抽取尺寸转换函数，UBSan 检查零值、负值、65535/65536 和 INT32 跨端边界。 |

`run-create-reparent.py` 用 `GetAncestor(GA_PARENT)` 区分 parent 与 owner；就绪后通过消息队列确认状态。
成功的 CreateWindowEx 不要求清除先前 LastError。`run-native-size.py` 使用
`--source /absolute/patched-source --out /absolute/new-qa`，不启动 Wine。

## 最大化与显示变化

`run-maximize.py` 使用 3200×2000 和 3840×2160 双屏，覆盖主副屏交换、负原点、位置偏移、
popup/overlapped、阴影和关闭共享框架。窗口返回相对监视器的最大化约束，工作区由标准 dock strut 公布。
同时核对 Win32 提议、最终矩形、X11 主体/框架、目标屏幕和原生最小化状态。
还原必须回到原矩形，可见 configure 事件不得把外框瞬间撑大或缩到正文以下。

```sh
python3 run-maximize.py --scale 1
python3 run-maximize.py --scale 2 --workarea-cycle
python3 run-maximize.py --scale 1 --workarea-cycle --fullscreen
```

`--workarea-cycle` 在七种组合下各做三轮面板隐藏/恢复，并发送无尺寸变化的更新。
期望矩形读取宿主 `_GTK_WORKAREAS_D0`。`--fullscreen` 增加普通主动全屏和保留 WS_MAXIMIZE 的全屏，
检查退出后恢复。原有失败保留在严格结果中，失败退出码为 1。
`negative-default-limits` 与自定义约束使用同样的严格判定，任何尺寸跳变也会使该组失败。
`--reentrant-fullscreen` 检查宿主 WM_SIZE 内的应用全屏请求；`--pending-native-minimize` 检查待绘制时的原生最小化与恢复。
`run-display-removal.py` 覆盖显示器移除后的重绑定、裁切及恢复。

## niri 与 KWin

niri 的形状裁剪用现有私有会话运行：

```sh
python3 run-shape-clip.py --runtime /absolute/wine --output /absolute/private-qa/result \
  --existing-niri --fixture /absolute/shape-clip.exe
```

父目录应带测试标记，脚本仍创建空白 prefix。GNOME 控制组也需运行：其旧版可能通过，
不能据此代替 niri 的裁剪验证。

KWin 使用 `run-kwin-first-transaction.py --runtime /absolute/wine --output /absolute/private-qa/result`。
父目录带 `.wecom-frame-qa`，会话启用截图 API。正文未就绪时要求计数为 0、
`_XWAYLAND_ALLOW_COMMITS=0` 且合成保持 owner 背景；正文完成后才显示目标颜色并允许提交。
首次打开和两次重开都检查，且核对已加载驱动 inode。默认逻辑高度 1108，可用 `--logical-height` 指定。
环境、输出和实际缩放另存报告；真实菜单焦点与点击可用 `popup-input.exe menu` 配合原生 Wayland 输入验证。

## 历史实验

`run-frame-move-race.py` 是旧实现的定位实验，未迁移到显式附属类协议。它让 owner 保持旧 Win32 坐标，
另一线程按未来原生坐标更新 overlay，同时要求共享框架，与当前 owner 相对布局合同不一致。
脚本和 `--pending-move`、`--pending-resize`、`--create-after-move` 模式保留用于定位，不计作当前通过项。
当前已迁移的顺序由 `run-attached-anchor.py` 检查，回调内跨线程更新仍是覆盖缺口。
历史回复、对应提交及本轮迁移草稿的问题见[旧测试复核](../../CODE-REVIEW.md#旧测试复核)。

构造像素与几何检查之外，真实客户端清单和本轮失败见[review 记录](../../CODE-REVIEW.md)。
