# 软件授权接口回归

WeMeet 3.26.511.637 的 `wemeet_platform.dll` 静态导入
`slwga.dll!SLIsGenuineLocal`。Wine 11.20 原本缺少这个模块，会议 DLL 在执行前即加载失败。

补丁增加标准 Wine PE 模块与公开类型。Wine 尚无 genuine-license provider，
有效参数返回 `E_NOTIMPL`，必填参数为空返回 `E_INVALIDARG`；失败时保持输出和 LastError 不变。
这项兼容不提供 Windows 激活或授权状态。接口依据来自
[Microsoft API 文档](https://learn.microsoft.com/windows/win32/api/slpublic/nf-slpublic-slisgenuinelocal)。

`slwga.c` 检查模块导出、32/64 位调用约定、错误返回和输出参数保留。
`run.py` 使用一次性 prefix，不读取账号或连接日常桌面。

```sh
python3 run.py --runtime /absolute/package/wine --output /absolute/new-result
```

开发时可加 `--module-dir /absolute/build/dlls/slwga`，直接测试两种架构的构建产物。
统一回归入口的组名为 `software-licensing`。真实快速会议的创建与结束另做客户端回归。
