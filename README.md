# Codex Band Bridge

AstroBox 电脑插件，将 Codex 授权请求发送到手环，支持双端处理与队列同步。问题回答仍在电脑完成。

当前版本 **1.3.1**。维护者 **DecafDoppio** 已确认真机验收成功。保留新电脑 UI、通用钩子与现有 60 秒原生回退；关闭总开关停止转发并保留蓝牙连接。

![封面](media/cover.png)

## 下载与安装

[下载 1.3.1](https://github.com/DecafDoppio/Codex-Band-Bridge/releases/tag/v1.3.1) · [全部 Releases](https://github.com/DecafDoppio/Codex-Band-Bridge/releases)

下载 Release 中的完整 ABP，在 AstroBox 2.2.0+ 导入（API Level 4 / WASI 3）。现有电脑流程面向 Windows，需要 Python 3.10+ 与 tkinter/_tkinter；插件不安装或升级 Python，不更改系统 PATH。选择设备、测试连接，按插件说明安装并信任钩子。

保留现有八项权限：device、interconnect、register_interconnect_recv、http-server、thirdpartyapp、os.device-id、clipboard.write、dialog。ABP 必须包含钩子 ZIP、Tcl/Tk ZIP、配置脚本与审阅脚本，不能只下载 WASM。

配套项目：[Codex Band Connector](https://github.com/DecafDoppio/Codex-Band-Connector)。两侧均使用 1.3.1，不新增强制捆绑安装。

## 界面展示

![界面展示](media/preview.png)

图片为维护者提供的展示排版，含演示内容与合成场景；素材来源见 [MEDIA_SOURCES.md](MEDIA_SOURCES.md)。

## 从源码构建

安装 rust-toolchain.toml 指定的 nightly-2026-10-11（含 wasm32-wasip3），以及 Python 3.10+：

```powershell
python scripts/build.py
```

构建使用 Cargo.lock，输出完整 ABP、WASM、manifest、图标及四个附加文件到 dist；dist 与 target 不提交。已有依赖缓存可用 --offline。Windows GNU 主机工具链还需要兼容的本机链接器；中文路径出现链接错误时可配置支持 Unicode 路径的 clang。

源码不依赖私人模拟器、原工程、连接配置或已有 target。Tcl/Tk 支持 ZIP 是受许可约束的打包输入，保留在 third_party；不是本项目预编译插件安装包。

现行兼容性检查：cargo test -p bridge-core --test pre_ui_compat --target wasm32-wasip1，Node 24 提供 WASI runner。完整 Rust 单元测试及部分 Python 历史测试尚有旧接口问题，见 VALIDATION.md；不将其描述为全绿。

## 发布、验证与反馈

main 保存源码及构建输入；安装包放 GitHub Releases，AstroBox 所需文件使用独立发布分支，见 [PUBLISHING.md](PUBLISHING.md)。首次推送前下载链接尚未生效。

检查结果及限制见 [VALIDATION.md](VALIDATION.md)。通过 [Issues](https://github.com/DecafDoppio/Codex-Band-Bridge/issues) 反馈。自有代码采用 [MIT](LICENSE)，第三方许可证与通知保留，见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

社区项目，与 OpenAI、AstroBox 和小米官方无隶属关系。
