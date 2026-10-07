# 来源与分发说明

`ucagent-tool/` 基于 [XS-MLVP/UCAgent](https://github.com/XS-MLVP/UCAgent)，保留原作者信息与 [MIT 许可证](ucagent-tool/LICENSE)。此目录是本轮虚拟机隔离开发副本的源码快照，包含形式化服务、桌面客户端、配置、模板、文档与相关测试；不是上游未经修改的版本。

`ucagent-tool/SOURCE_SNAPSHOT.json` 记录实际验证工具源码的 SHA-256。交付补充上游 README、许可证与入口文件，以支持源码安装。`verification/reports/tool-fix/` 保留本轮修复和回归证据。`bin/UCAgent-Desktop.pyz` 由同一快照的桌面源码构建。

DMAC RTL、验证规格、属性、报告与工程脚本单独存放。上游的 MIT 许可证声明适用于其对应的 UCAgent 内容；本交付没有擅自替用户新增 DMAC 的许可声明。

仓库源码与轻量客户端之外，2026-10-07 的 Release 提供完整 Linux x86_64 离线发行包，包含开源 Python、EDA 与后端依赖，其许可证和来源保留在包内。商业许可证、账号密钥、服务数据库或签名私钥均不发布。历史签名保留为证据记录；其他设备需要建立自己的运行与签名，不能继承原机器的审批状态。

`offline/source-changes.json` 记录本轮离线工程注册改动相对于原工具快照的哈希差异。原 `SOURCE_SNAPSHOT.json` 仍用于追溯 2026-10-05 验证所使用的源码，不能误读为后续版本的完整身份。
