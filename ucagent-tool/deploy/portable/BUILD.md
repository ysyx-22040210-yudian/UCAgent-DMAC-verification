
# 构建 Linux 离线发行包

构建机要求 Linux x86_64、Python 3.11.14+、至少 12 GiB 可用空间和普通用户账号。运行设备不需要这些构建依赖。所有大文件、临时文件和输出应位于容量充足的用户分区。

从 `runtime.lock.json`、`runtime-support.lock.json`、`ui-assets.lock.json` 指定的官方 URL 下载原始文件，全部放在同一缓存目录；构建器会检查固定 SHA-256 和大小。不会从 PATH 或系统目录拷贝未追踪的 EDA、Python 或 glibc。缺失文件或哈希不匹配会失败。

```sh
python3.11 deploy/build_portable.py \
  --source /path/to/UCAGENT \
  --runtime-archive /cache/oss-cad-suite-linux-x64-20260727.tgz \
  --runtime-support /cache/libc6_2.35-0ubuntu3.8_amd64.deb \
  --output /releases/UCAgent-Studio-0.3.1-linux-x86_64
```

`requirements.txt` 固定执行服务及全部传递依赖版本。默认仅**构建时**使用 pip 下载 wheel 并安装到隔离临时目录；添加 `--wheelhouse /cache/wheels` 可使用提前准备的完整 Python 3.11 Linux wheel 目录进行无索引构建。构建器不覆盖已有发行目录，只在校验成功后原子发布。

```sh
/releases/UCAgent-Studio-0.3.1-linux-x86_64/oss-cad-suite/bin/tabbypy3 \
  deploy/accept_portable.py \
  --bundle /releases/UCAgent-Studio-0.3.1-linux-x86_64 \
  --data /home/tester/fresh-acceptance --gui
```

验收必须使用全新测试数据目录和图形显示。需要严格断网验收时，在管理员创建的独立网络命名空间内仅启用 loopback，再以普通用户运行上述命令并添加 `--require-offline`；不要修改主机网络或防火墙。纯 SSH 测试可由已有 Xvfb 提供显示。验收会实际运行 SBY 并保留证据，不是只探测二进制。

发行前运行 `Verify-Bundle.py`，然后对版本目录制作 tar.gz 并生成归档 SHA-256。将解压目录迁移到另一位置后重复启动和验收。包内不存储开发机的状态数据库、SSH 凭据、许可证值或 API Key。
