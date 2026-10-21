# GitHub 与 AstroBox 发布

2026-10-21：配套手环端适配小米手环 10、10 NFC、11 及 11 NFC。本次仅更新声明，未重新封装或替换 Bridge ABP。

## main 分支

提交源码、锁定依赖、构建脚本、许可证与 media。不要提交 dist、downloads、node_modules、target、.local、.publication、私钥或连接配置。本机旧产物可以保留，首次暂存须复核忽略规则与全部暂存文件。

## GitHub Releases

以实际确认的源码提交创建 v1.3.1 标签，Release 使用 RELEASE_NOTES.md；附件使用 .publication/github-release 中的安装包与 SHA256SUMS.txt。不重新编译替换已验收 RPK。

```powershell
python scripts/prepare-publication.py
```

先运行源码构建；命令核对 dist 中四个附加文件、版本和 manifest，再从完整文件集合封装 ABP。

## AstroBox 发布分支

脚本生成 .publication/astrobox，作为未来 astrobox-release 分支的独立文件树；不把它提交到 main。操作前记录 main 的源码提交与 Release 对应关系。使用单独 checkout/worktree 提交该目录内容，避免覆盖源码工作目录。

插件分支根目录 index.txt 内容为 release；release 中仅 manifest.json、codex_band_bridge.wasm、icon.png 和四个 additional_files。官方插件源登记的 raw 基地址为 https://raw.githubusercontent.com/DecafDoppio/Codex-Band-Bridge/refs/heads/astrobox-release/ 。必须保留末尾斜杠，全部声明文件必须可下载。ABP 放 GitHub Releases，不放官方源文件树。

独立发布分支尚未创建，也未提交官方审核。本说明不自动推送或上架。

官方资料：
- https://abox.run/docs/creator-tools/resource-management/plugin-upload
- https://abox.run/docs/creator-tools/resource-management/free-resources
- https://github.com/AstralSightStudios/AstroBox-Repo/blob/main/assets/docs/ResAdptV2.md
