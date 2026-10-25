# 来源与第三方许可

本项目是非官方企业微信 Linux 适配，企业微信、商标及图标属于腾讯。
企业微信、微软运行库及字体不因本仓库公开而转为开源，使用和再分发仍按各自许可。
安装器内 License 目录和随附第三方声明保留在未登录模板中。

Wine 11.20 由 Wine 项目维护，按 LGPL-2.1-or-later 使用；本次 Wine 修改沿用相同许可。
完整 Wine 原始源码、对应净补丁、构建脚本和 COPYING.LIB 随 DEB 提供。
不通过替换系统库来运行本软件。

安装、启动、输入法、字体和窗口助手以 tbsangel/archlinux-wine-wecom-setup 的
f0ad4711049476bb2d87b40acaff53ca5ee58124 为基础，保留来源；没有为未明确授权的上游文件追加新许可。

CEF / Chromium / V8 属于各自上游和第三方版权所有者。ubuntu/patch-cef-x86.py 对固定厂商 x86 CEF
回补 V8 保护值检查及 Chromium 光标坐标修订，输出 DLL 的原厂签名失效。WXWork.exe 未修改。
补丁来源：

- https://github.com/v8/v8/commit/df1eaa2bd84bf9cc8ff2d6b5e7ca53290546e4ab
- https://github.com/chromium/chromium/commit/fe73f3f71c1cc1be0734906e841922d9a60c0f0a

本预览版包含该 CEF 兼容修订；投稿时明确披露给审核者，不声称是腾讯官方构建。
