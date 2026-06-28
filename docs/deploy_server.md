# 合规 Agent 服务器部署

## 1. 服务器准备

安装 Docker 和 Docker Compose，然后拉代码：

```bash
git clone https://github.com/AnthonyInUK/gegui.git
cd gegui
```

## 2. 配置环境变量

```bash
cp .env.example .env
nano .env
```

本地演示 fallback 可以不填模型 key；真实 Vision/多专家审核需要配置 `DASHSCOPE_API_KEY` 或其他模型 key。

## 3. 启动

```bash
docker compose up -d --build
```

访问：

```text
http://服务器IP:8001
```

## 4. 数据持久化

审核记录、SQLite 数据库、上传图片保存在 Docker volume：

```text
compliance_agent_db -> /app/src/db
```

## 5. 常用命令

```bash
docker compose logs -f
docker compose restart
docker compose down
docker compose up -d --build
```

## 6. 生产建议

- 用 Nginx/Caddy 反代到 `127.0.0.1:8001`
- 配 HTTPS 域名
- SQLite 后续换 PostgreSQL/MySQL
- 上传图片后续换 OSS/S3/MinIO
- 真实审核接入 Vision 模型，不只依赖 fallback
