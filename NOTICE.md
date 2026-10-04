# 来源与分发说明

`ucagent-tool/` 基于 [XS-MLVP/UCAgent](https://github.com/XS-MLVP/UCAgent)，保留原作者信息与 [MIT 许可证](ucagent-tool/LICENSE)。此目录是本轮虚拟机隔离开发副本的源码快照，包含形式化服务、桌面客户端、配置、模板、文档与相关测试；不是上游未经修改的版本。

`ucagent-tool/SOURCE_SNAPSHOT.json` 记录实际验证工具源码的 SHA-256。交付补充上游 README、许可证与入口文件，以支持源码安装。`verification/reports/tool-fix/` 保留本轮修复和回归证据。`bin/UCAgent-Desktop.pyz` 由同一快照的桌面源码构建。

DMAC RTL、验证规格、属性、报告与工程脚本单独存放。上游的 MIT 许可证声明适用于其对应的 UCAgent 内容；本交付没有擅自替用户新增 DMAC 的许可声明。

仓库提供源码与轻量客户端，不捆绑 Python 环境、EDA 可执行程序、商业许可证、账号密钥、服务数据库或签名私钥。历史签名保留为证据记录；其他设备需要建立自己的运行与签名，不能继承原机器的审批状态。

