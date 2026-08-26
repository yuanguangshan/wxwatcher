# wxwatcher

[![PyPI](https://img.shields.io/pypi/v/wxwatcher.svg)](https://pypi.org/project/wxwatcher/)
[![Python](https://img.shields.io/pypi/pyversions/wxwatcher.svg)](https://pypi.org/project/wxwatcher/)
[![License](https://img.shields.io/pypi/l/wxwatcher.svg)](https://pypi.org/project/wxwatcher/)

文件变更监控工具：检测到变化时，通过微信推送通知。

## 特性

- 两阶段扫描：先 `stat` 快速检测，仅对疑似变化文件计算 SHA256
- 基线哈希多线程并行，大目录首次启动显著加速
- 自动忽略 `.git`、`__pycache__`、`.venv` 等常见目录
- 支持按扩展名过滤（含全部子目录）、自定义忽略规则
- 分批推送，单轮变更条数封顶（可配置），避免刷屏
- `--dry-run` 零配置试用：只检测打印，不推送；`--once` 单轮模式适配 cron/systemd timer
- SIGTERM / Ctrl+C 均优雅退出并保存状态，重启后增量对比不重建基线
- CLI 参数 / 环境变量 / 配置文件 / 默认值四层配置
- 通知自带来源主机名（`--host-name` 可自定义别名），多机部署一眼区分
- 忽略规则支持通配符（`*.log`）和正则（`regex:\.tmp\d+$`）
- 日志自动写入 `~/.wxwatcher/` 并按监控目录隔离，支持轮转

## 安装

```bash
pip install wxwatcher
```

如需使用 YAML 配置文件：

```bash
pip install wxwatcher[config]
```

## 快速开始

### 监控当前目录

```bash
wxwatcher
```

### 监控指定目录

```bash
wxwatcher /path/to/watch
```

### 查看帮助

```bash
$ wxwatcher --help
usage: wxwatcher [-h] [-v] [-i INTERVAL] [--push-url PUSH_URL]
                 [--push-token PUSH_TOKEN] [--to-user TO_USER]
                 [--max-batch MAX_BATCH] [--max-changes MAX_CHANGES]
                 [--ext EXT] [--ignore IGNORE] [--log-file LOG_FILE]
                 [--verbose] [--quiet] [--knowly-url KNOWLY_URL] [--no-knowly]
                 [--config CONFIG] [--no-config] [--dry-run] [--once]
                 [dir]

文件变更监控工具，检测到变化时通过微信推送通知

positional arguments:
  dir                   监控目录（默认当前目录）

options:
  -h, --help            show this help message and exit
  -v, --version         show program's version number and exit
  -i, --interval INTERVAL
                        轮询间隔（秒，默认 30）
  --push-url PUSH_URL   推送 API 地址
  --push-token PUSH_TOKEN
                        推送 Bearer token（必填）
  --host-name HOST_NAME
                        通知中展示的来源主机名（默认自动取本机 hostname）
  --to-user TO_USER     接收人（默认 @all）
  --max-batch MAX_BATCH
                        单批最大变更数（默认 50）
  --max-changes MAX_CHANGES
                        单轮推送的最大变更条数，超出截断（默认 100）
  --ext EXT             仅监控指定扩展名（逗号分隔，如 py,md）
  --ignore IGNORE       忽略的目录/文件名（逗号分隔，如 dist,build）
  --log-file LOG_FILE   日志文件路径
  --verbose             输出 DEBUG 级别日志
  --quiet               仅输出 WARNING 及以上
  --knowly-url KNOWLY_URL
                        Knowly 上传 API 地址（需显式配置，默认不上传）
  --no-knowly           禁用上传到 Knowly
  --config CONFIG       配置文件路径（默认自动搜索）
  --no-config           跳过配置文件加载
  --dry-run             只检测并打印变更，不推送、不写状态
  --once                只跑一轮检测后退出（适合 cron / systemd timer）
```

## 配置

优先级：**CLI 参数 > 环境变量 > 配置文件 > 默认值**

### YAML 配置文件

搜索顺序：
1. 当前目录及父目录中的 `.wxwatcher.yml` 或 `wxwatcher.yml`
2. `~/.wxwatcher/config.yml`
3. `~/.config/wxwatcher/config.yml`

使用 `--config <path>` 指定具体文件，或 `--no-config` 跳过配置文件加载。

示例 `.wxwatcher.yml`：

```yaml
push_url: "https://api.example.com/push"
poll_interval: 15
to_user: "@all"
host_name: "家里Mac"   # 多机部署时区分通知来源，默认自动取本机 hostname
ignore:
  - "*.log"
  - "regex:\\.tmp\\d+$"
  - dist
  - build
ext:
  - py
  - md
max_changes: 100      # 单轮推送封顶，超出截断
ignore_ext:           # 追加要忽略的扩展名（默认已有 .pyc/.pyo）
  - ".bak"
no_knowly: true       # 也接受 no-knowly 写法
log_file: "~/.wxwatcher/wxwatcher.log"
```

### 环境变量

| 环境变量 | 说明 | 默认值 |
|---|---|---|
| `WXWATCHER_DIR` | 监控目录 | 当前目录 |
| `WXWATCHER_INTERVAL` | 轮询间隔（秒） | `30` |
| `WXWATCHER_PUSH_URL` | 推送 API 地址 | **必须配置** |
| `WXWATCHER_PUSH_TOKEN` | 推送 Bearer token | **必须配置** |
| `WXWATCHER_HOST_NAME` | 通知中展示的来源主机名 | 本机 hostname |
| `WXWATCHER_TO_USER` | 接收人 | `@all` |
| `WXWATCHER_MAX_BATCH` | 单批最大变更数 | `50` |
| `WXWATCHER_MAX_CHANGES` | 单轮推送最大变更条数（超出截断） | `100` |
| `WXWATCHER_LOG_FILE` | 日志文件路径 | `~/.wxwatcher/logs/wxwatcher_<dirhash>.log` |
| `WXWATCHER_IGNORE` | 额外忽略模式（逗号分隔） | 无 |
| `WXWATCHER_EXT` | 仅监控扩展名（逗号分隔，含全部子目录） | 全部 |
| `WXWATCHER_KNOWLY_URL` | Knowly 上传 API 地址 | 不上传 |
| `WXWATCHER_KNOWLY_USER` / `WXWATCHER_KNOWLY_PASS` | Knowly Basic Auth 凭证 | 无 |

> `--dry-run` 模式下不推送，`WXWATCHER_PUSH_URL` / `PUSH_TOKEN` 可省略。

### 忽略规则

`--ignore` 和环境变量 `WXWATCHER_IGNORE` 支持三种模式：

| 类型 | 示例 | 说明 |
|------|------|------|
| 精确匹配 | `.git`, `node_modules` | 文件名或路径段完全匹配 |
| 通配符 | `*.log`, `~*`, `tmp_*_backup` | 含 `*?[]` 自动识别为 fnmatch |
| 正则 | `regex:\.tmp\d+$` | 以 `regex:` 前缀，匹配文件名或完整路径 |
| 取反 | `!*.log` | 以 `!` 开头，取消之前匹配的忽略规则（类似 `.gitignore`） |

默认忽略规则包含 `.git`、`__pycache__`、`.venv`、`node_modules`、`.cache`、`.DS_Store`、`.log`、`*.sidecar.md`；扩展名默认忽略 `.pyc`/`.pyo`（可通过配置文件 `ignore_ext` 追加）。

### dry-run 与单轮模式

```bash
# 零配置试用：只检测并打印变更，不推送、不写状态
wxwatcher --dry-run ~/myproject

# 单轮模式：建立/加载基线 → 检测一轮 → 保存状态退出（cron / systemd timer 友好）
wxwatcher --once --push-url ... --push-token ... /data
```

也可通过 CLI 参数控制（优先级高于环境变量）：

| 参数 | 说明 |
|---|---|
| `--ignore` | 忽略的目录/文件名（逗号分隔，如 `dist,build`） |
| `--verbose` | 输出 DEBUG 级别日志 |
| `--quiet` | 仅输出 WARNING 及以上 |

### 示例

```bash
export WXWATCHER_DIR=/data
export WXWATCHER_INTERVAL=10
export WXWATCHER_PUSH_URL=https://api.example.com/push
export WXWATCHER_IGNORE="node_modules,.idea"
wxwatcher
```

只监控特定文件类型：

```bash
export WXWATCHER_EXT="py,txt,md"
wxwatcher
```

## systemd 服务

将 `wxwatcher.service` 复制到 systemd 目录：

```bash
sudo cp wxwatcher.service /etc/systemd/system/
```

配置环境变量（推送地址等）：

```bash
sudo mkdir -p /etc/wxwatcher
echo 'WXWATCHER_PUSH_URL=https://...' | sudo tee /etc/wxwatcher/environment
```

也可将 YAML 配置文件放在 `~/.wxwatcher/config.yml`，服务启动时会自动加载。

启用并启动：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now wxwatcher
sudo journalctl -u wxwatcher -f
```

## 工作原理

```
每轮轮询（默认 30s）
  │
  ├─ fast_scan()          # os.walk + os.stat，不读文件内容
  │
  ├─ 对比 mtime / size    # 快速筛选疑似变化文件
  │
  ├─ sha256_file()        # 仅对疑似文件计算 hash，确认内容真正改变
  │
  └─ send_wechat()        # 分批推送到微信
```

大目录下性能表现良好：5000+ 文件的目录，每轮仅需毫秒级扫描，变化文件少时几乎零磁盘 IO；首次建立基线时 SHA256 计算多线程并行（哈希读文件释放 GIL）。

## 推送消息示例

```
文件监控已启动
──────────
运行主机: YGS-Mac-mini-2
监控目录: project
文件数量: 1203
启动时间: 02:30:00
──────────
By: 苑广山的文件监控助手
```

```
文件变更  02:35:00 @YGS-Mac-mini-2
──────────
1. [新增] config.py (+2.1KB)
2. [修改] README.md (+120B)
3. [删除] old_file.txt
──────────
By: 苑广山的文件监控助手
```

## 开发

```bash
git clone https://github.com/yuanguangshan/wxwatcher.git
cd wxwatcher
pip install -e ".[dev]"
pytest
```

构建发行包：

```bash
python -m build
```

## 常见问题

**Q: 需要安装 inotify 吗？**  
A: 不需要。wxwatcher 使用轮询方式，跨平台兼容，无需系统级通知服务。

**Q: 可以推送其他消息平台吗？**  
A: 当前仅支持微信推送接口。可以通过 `--push-url` 指定兼容该接口的其他服务。

**Q: 大量文件时会不会很卡？**  
A: 不会。采用两阶段扫描，每轮只读元数据，仅疑似变化文件才计算 hash。

**Q: 如何停止监控？**  
A: `Ctrl+C` 或 `kill <pid>`（SIGTERM）均可安全退出，程序会保存当前状态后退出；下次启动直接增量对比，不重建基线。

## 依赖

- Python >= 3.9
- `httpx`
- `pyyaml`（可选，仅在使用 YAML 配置文件时需要）

## License

MIT
