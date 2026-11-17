# 部署参考配置

这些文件是服务器上实际配置的脱敏副本，用于重建环境或排查问题时对照。服务器上的真实文件不由仓库管理，改了服务器配置后请同步更新这里。

尖括号里的内容要替换成实际值。仓库是公开的，真实的目录、端口、密钥路径不要写进来。

| 文件 | 服务器上的位置 |
|---|---|
| `systemd/*.service.example` | `/etc/systemd/system/` 下的同名 `.service` 文件 |
| `nginx.conf.example` | 项目专用的 nginx 主配置，由 nginx 服务单元用 `-c` 指定 |

要点：

- 四个服务各用独立账户运行，数据库和缓存只监听本机。
- 后端必须是单进程（`--workers 1`）：模型并发上限是在进程内计数的，多进程会让上限成倍放大。
- 后端对项目目录只有读权限。将来需要写文件的功能（如导出 PDF）要用临时目录，或在单元文件里单独开放可写路径。
- 对外端口小于 1024 时，nginx 服务单元需要 `AmbientCapabilities=CAP_NET_BIND_SERVICE`，否则以非 root 账户启动会因无权监听而失败。
- nginx 的 `/api/` 必须 `proxy_buffering off`，否则流式回答会攒成整段才显示。

运行环境：Python 3.12、Node 24、PostgreSQL 13、Redis 6.2、Nginx 1.24。
