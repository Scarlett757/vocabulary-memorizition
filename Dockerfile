# 单词背诵软件 Docker 镜像
# 多阶段构建：先用基础镜像安装依赖，再复制应用代码
FROM python:3.13-slim AS base

# 设置时区为东八区
ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# 工作目录
WORKDIR /app

# 先复制依赖清单，利用 Docker 层缓存
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码（.dockerignore 已排除 .env / dev.db 等）
COPY . .

# 音频缓存目录
RUN mkdir -p static/audio/us static/audio/uk

# 暴露端口
EXPOSE 5000

# 容器内以非 root 用户运行更安全
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# 启动命令：绑定 0.0.0.0:5000，关闭 debug
# 数据库表会在首次访问时由 db.create_all() 自动创建（见 app.py 末尾）
CMD ["python", "app.py"]
