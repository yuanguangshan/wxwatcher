# wxwatcher

文件变更监控工具，检测到变化时通过微信推送通知。

## 安装

```bash
pip install wxwatcher
```

## 用法

### 监控当前目录

```bash
wxwatcher
```

### 监控指定目录

```bash
wxwatcher /path/to/watch
```

### 完整选项

```bash
wxwatcher /data \
  --interval 10 \
  --push-url https://your-api.com/push \
  --to-user @all \
  --max-batch 50 \
  --log-file /tmp/wxwatcher.log
```

### 环境变量

所有配置均可通过环境变量设置（优先级低于 CLI 参数）：

| 变量 | 说明 | 默认值 |
|---|---|---|
| `WXWATCHER_DIR` | 监控目录 | 当前目录 |
| `WXWATCHER_INTERVAL` | 轮询间隔（秒） | 30 |
| `WXWATCHER_PUSH_URL` | 推送 API 地址 | `https://api.yuangs.cc/weixinpush` |
| `WXWATCHER_TO_USER` | 接收人 | `@all` |
| `WXWATCHER_MAX_BATCH` | 单批最大变更数 | 50 |
| `WXWATCHER_LOG_FILE` | 日志文件路径 | `~/.wxwatcher/file_watcher.log` |
| `WXWATCHER_IGNORE` | 额外忽略模式（逗号分隔） | 无 |
| `WXWATCHER_EXT` | 仅监控扩展名（逗号分隔） | 全部 |

```bash
export WXWATCHER_DIR=/data
export WXWATCHER_INTERVAL=10
wxwatcher
```

## 特性

- 两阶段 hash：先 stat 快速扫描，仅疑似变化文件才计算 sha256
- 忽略规则：自动跳过 `.git`、`__pycache__`、`.venv` 等
- 分批推送：大量变更时自动分批，避免消息过长
- 配置灵活：CLI 参数、环境变量、默认值三层优先级

## 日志

默认日志位置：`~/.wxwatcher/file_watcher.log`

## License

MIT
