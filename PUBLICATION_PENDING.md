# 发布状态

1.3.1 真机验收已由维护者确认；作者、配套仓库地址及新媒体素材已配置。

- main 仅提交源码、构建输入、文档和当前展示素材；安装包发布到 GitHub Releases。
- 未执行 GitHub 推送、Release 创建或 AstroBox 审核提交。
- 历史 Rust 测试编译错误及 Python 三项旧接口断言仍未同步，不声明完整回归全通过。
- AstroBox 发布分支文件由 scripts/prepare-publication.py 生成，操作见 PUBLISHING.md。
- 上架时快应用资源清单需使用发布分支的实际提交 SHA；不可填写占位哈希。
