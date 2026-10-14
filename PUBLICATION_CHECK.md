# 发布整理复核 — 2026-10-15

- main 的忽略规则排除 dist、downloads、target、.local、.publication、旧封面源文件及旧演示图；第三方 Tcl/Tk ZIP 作为受许可约束的必要构建输入保留。
- 新媒体文件与维护者提供文件逐字节一致，已确认展示图电脑端标签修正。作者、版权署名和计划仓库链接配置为 DecafDoppio。
- 插件、核心和钩子运行源码与私人工作区最新对应源码逐字节一致，本次未改功能、权限或运行行为。
- GitHub Releases 的完整 ABP 已封装，SHA-256：`73d4a4c8451c50f9bfdd19686ca675e8b56829d3ee091530c75b6e73d78aa25d`。
- 对比原 1.3.1 ABP（SHA-256 `35eef3db1edc7fed61367ab41262f30df682bae04e2bc430f58f0a456e451906`）：仅 manifest.json 的 author/website，以及 codex-hooks.zip 内的 LICENSE 署名改变。WASM、钩子代码、图标、Tcl/Tk、配置和审阅脚本字节保持一致。
- 该元数据整理后的 ABP 未重新安装；不将原包真机结论冒称为新容器安装验收。
- AstroBox 文件树包含根 index.txt（release）与 release 内的 manifest、WASM、图标和四个 additional_files；没有 ABP 或旧版产物混入该文件树。
- 构建产物记录已改为仅列本次版本，避免把本机残留旧 ABP 计为新产物。
- 两库拟公开文件与发布产物共检查 3524 个文件/归档条目，未发现匹配的私钥、访问令牌或本机用户目录路径；首次提交仍须复核实际暂存清单。
- Python 语法和 JSON 解析通过。本次未重跑源码编译、宿主安装或完整回归。历史 Rust/Python 测试问题保留，详见 VALIDATION.md。
- 本地 Git 已初始化，GitHub owner 为 DecafDoppio；公开作者和 AstroBox ID 仍为 DecafDoppio。尚未创建发布分支、上传 Release 或提交官方审核。

本机原 dist ABP 保留，Release 应使用 .publication/github-release 中的新完整包。操作见 PUBLISHING.md。
