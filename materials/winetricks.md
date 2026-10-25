# 运行库与字体配置

本页对应企业微信 **5.0.12.6018 / Wine 11.20 / x64 CEF 5.0.79.5483**。完整操作见[安装步骤](../install-from-scratch.md)，版本和指纹以[版本清单](versions.json)为准。

## 微软 DLL

| 组件 | 正式配置 | 原因 |
|---|---|---|
| VC14 运行库 | `winetricks vcrun2022` | 为精简 CEF 提供 MSVCP、VCRUNTIME、CONCRT 等运行库 |
| UCRT | `winetricks ucrtbase2019` | 单独提供精简 CEF 所需的通用 C 运行库 |
| D3DCompiler | `winetricks d3dcompiler_47` | 提供 CEF 图形组件依赖的编译器 |
| CEF 的 `vcruntime140_1`、`dbghelp` | 对三个 CEF EXE 设置 Wine 内建覆盖 | 由系统实现承担对应接口，无需保留 CEF 目录内同名 DLL |
| CEF 的 46 个 API-set 文件 | 使用 Wine API-set 解析 | API 名称解析到实际系统模块，无需逐个复制转发文件 |
| 主程序与 WeMail 的本地 DLL、manifest | 保留安装器原件 | 清单固定了本地加载路径，全局覆盖不能代替这些文件 |
| x86 RichEdit | `winetricks riched30`，配合 `riched20=n,b` | 修复聊天编辑框中文方框；配套 `msls31.dll` 随同安装 |

## CEF 运行库配置

在安装步骤已初始化的目标 prefix 中执行：

```bash
env WINEPREFIX="$WECOM_PREFIX" WINE=/usr/bin/wine WINESERVER=/usr/bin/wineserver \
  winetricks -q vcrun2022 ucrtbase2019 d3dcompiler_47
```

当前 [30 文件清单](cef64-wine-builtin-profile.json)从厂商 89 文件中省去 11 个由 winetricks 提供的运行库、46 个 API-set 文件和两个使用 Wine 内建实现的 DLL。应用专用覆盖由 [cef-builtin.reg](../configs/cef-builtin.reg)提供，环境覆盖由 [dll-overrides.txt](../configs/dll-overrides.txt)提供。主程序与 WeMail 的本地 DLL 不参与裁剪。

VC/UCRT 的系统版本可以与厂商原件不同，文件同名不代表内容相同。`vcrun2015/2017/2019/2022/2026` 是替代关系，不应叠装。运行库安装也不能代替 Qt DPI、窗口、字体或跨进程输入桥接。

企业微信配套 CEF、Qt、ANGLE/SwiftShader 和业务插件保留厂商组件；WebView2 无法替代企业微信使用的 CEF。主程序自带的 VC10、VC12、D3DX 和 GDI+ 也保留原件，不为整理文件而重装或删除。

## RichEdit 安装

先按安装步骤备份原 x86 DLL，再执行：

```bash
env WINEPREFIX="$WECOM_PREFIX" WINE=/usr/bin/wine WINESERVER=/usr/bin/wineserver \
  winetricks -q riched30
python3 "$WECOM_SETUP/scripts/verify-materials.py" --only richedit \
  --richedit "$WECOM_PREFIX/drive_c/windows/syswow64/riched20.dll"
```

正式版本为 **5.30.23.1200**，SHA256 见 [versions.json](versions.json)。`syswow64` 存放 x86 DLL。不要按 DLL 名误选 `winetricks riched20`，该配方提供另一版本。

## 字体安装

西文字体采用以下组合：

```bash
env WINEPREFIX="$WECOM_PREFIX" WINE=/usr/bin/wine WINESERVER=/usr/bin/wineserver \
  winetricks -q corefonts calibri consolas tahoma micross
```

中文字体从 Adobe [Source Han Sans 2.005R](https://github.com/adobe-fonts/source-han-sans/releases/tag/2.005R) 和 [Source Han Serif 2.003R](https://github.com/adobe-fonts/source-han-serif/releases/tag/2.003R)取得 CN 子集 Regular/Bold OTF，共四个文件。文件名与 SHA256 见 [fonts.json](fonts.json)，安装时用 `--fonts-profile cn` 校验。

字体族必须与注册、GDI/DirectWrite 映射及 StatusFont 一致。其他发行形式的思源字体可能使用不同字体族；不能将 TTC 改名为 OTF 后套用当前配置。`--fonts-profile snapshot` 仅供已有原字体集合校验，不用于 winetricks 安装出的西文字体版本。

字体文件、安装器和 DLL 均不随仓库分发。Winetricks 配方来源见[上游源码](https://github.com/Winetricks/winetricks/blob/master/src/winetricks)，升级配方后应保持当前组件选择和材料检查。
