# wxwatcher

[![PyPI](https://img.shields.io/pypi/v/wxwatcher.svg)](https://pypi.org/project/wxwatcher/)
[![Python](https://img.shields.io/pypi/pyversions/wxwatcher.svg)](https://pypi.org/project/wxwatcher/)
[![License](https://img.shields.io/pypi/l/wxwatcher.svg)](https://pypi.org/project/wxwatcher/)

文件变更监控工具：检测到变化时，通过微信推送通知。

## 特性

- 两阶段扫描：先 `stat` 快速检测，仅对疑似变化文件计算 SHA256
- 自动忽略 `.git`、`__pycache__`、`.venv` 等常见目录
- 支持按扩展名过滤、自定义忽略规则
- 分批推送，避免消息过长
- CLI 参数 / 环境变量 / 默认值三层配置
- 日志自动写入 `~/.wxwatcher/file_watcher.log`

## 安装

```bash
pip install wxwatcher
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
                 [--to-user TO_USER] [--max-batch MAX_BATCH]
                 [--log-file LOG_FILE]
                 [dir]

文件变更监控工具，检测到变化时通过微信推送通知

positional arguments:
  dir                   监控目录（默认当前目录）

options:
  -h, --help            show this help message and exit
  -v, --version         show program's version number and exit
  -i INTERVAL, --interval INTERVAL
                        轮询间隔（秒，默认 30）
  --push-url PUSH_URL   推送 API 地址
  --to-user TO_USER     接收人（默认 @all）
  --max-batch MAX_BATCH
                        单批最大变更数（默认 50）
  --log-file LOG_FILE   日志文件路径
```

## 配置

优先级：**CLI 参数 > 环境变量 > 默认值**

| 环境变量 | 说明 | 默认值 |
|---|---|---|
| `WXWATCHER_DIR` | 监控目录 | 当前目录 |
| `WXWATCHER_INTERVAL` | 轮询间隔（秒） | `30` |
| `WXWATCHER_PUSH_URL` | 推送 API 地址 | `https://api.yuangs.cc/weixinpush` |
| `WXWATCHER_TO_USER` | 接收人 | `@all` |
| `WXWATCHER_MAX_BATCH` | 单批最大变更数 | `50` |
| `WXWATCHER_LOG_FILE` | 日志文件路径 | `~/.wxwatcher/file_watcher.log` |
| `WXWATCHER_IGNORE` | 额外忽略模式（逗号分隔） | 无 |
| `WXWATCHER_EXT` | 仅监控扩展名（逗号分隔） | 全部 |

### 示例

```bash
export WXWATCHER_DIR=/data
export WXWATCHER_INTERVAL=10
export WXWATCHER_IGNORE="node_modules,.idea"
wxwatcher
```

只监控特定文件类型：

```bash
export WXWATCHER_EXT="py,txt,md"
wxwatcher
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

大目录下性能表现良好：5000+ 文件的目录，每轮仅需毫秒级扫描，变化文件少时几乎零磁盘 IO。

## 推送消息示例

```
📂 文件监控已启动
──────────
监控目录: project
文件数量: 1203
启动时间: 02:30:00
──────────
By: 苑广山的文件监控助手
```

```
📝 文件变更  02:35:00
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
A: `Ctrl+C` 即可安全退出，程序会打印退出日志。

## 依赖

- Python >= 3.9
- `httpx`

## License

MIT
