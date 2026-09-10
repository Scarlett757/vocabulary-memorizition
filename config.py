# -*- coding: utf-8 -*-
"""配置文件：数据库连接、邮件、密钥等。

所有敏感凭据均从环境变量或项目根目录的 .env 文件读取。
本地开发：在项目根目录创建 .env 文件填入真实凭据（.env 已被 .gitignore / .dockerignore 忽略）。
Docker 部署：通过 docker-compose.yml 的 environment 或 env_file 注入。
"""
import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


def _load_env_file():
    """最小 .env 加载器：KEY=VALUE 逐行解析，不覆盖已存在的环境变量。

    仅用于本地开发便捷；生产环境应直接通过容器环境变量注入。
    """
    env_path = os.path.join(BASE_DIR, '.env')
    if not os.path.exists(env_path):
        return
    with open(env_path, 'r', encoding='utf-8') as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, _, val = line.partition('=')
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val


_load_env_file()


class Config:
    # 密钥：生产环境务必通过 SECRET_KEY 环境变量注入随机强密钥
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

    # MySQL 连接参数（默认空，必须通过环境变量或 .env 注入）
    MYSQL_HOST = os.environ.get('MYSQL_HOST', 'localhost')
    MYSQL_PORT = int(os.environ.get('MYSQL_PORT', 3306))
    MYSQL_USER = os.environ.get('MYSQL_USER', 'root')
    MYSQL_PASSWORD = os.environ.get('MYSQL_PASSWORD', '')
    MYSQL_DATABASE = os.environ.get('MYSQL_DATABASE', 'vocabulary_memorization')

    # SQLAlchemy 数据库连接串
    # 开发：SQLite 单文件；上线改为 MySQL/PostgreSQL 即可，模型代码无需改动
    # 若设置 DATABASE_URL 环境变量则优先使用，否则按上方 MySQL 配置拼接
    # 若未提供 MYSQL_PASSWORD 且未设置 DATABASE_URL，则回退到本地 SQLite，方便快速起步
    if os.environ.get('DATABASE_URL'):
        SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')
    elif os.environ.get('MYSQL_PASSWORD'):
        SQLALCHEMY_DATABASE_URI = (
            f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}"
            f"@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}?charset=utf8mb4"
        )
    else:
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{os.path.join(BASE_DIR, 'dev.db')}"

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # 邮件 SMTP 配置（用于发送验证码）
    # 未配置 MAIL_USERNAME / MAIL_PASSWORD 时进入"开发模式"：验证码直接返回到响应体
    MAIL_SERVER = os.environ.get('MAIL_SERVER', 'smtp.qq.com')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', 465))
    MAIL_USE_SSL = True
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME', '')   # 发件邮箱
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD', '')   # 授权码
    MAIL_FROM = os.environ.get('MAIL_FROM', '小易教育')            # 显示发件人

    # 验证码配置
    CODE_LENGTH = 6
    CODE_EXPIRE_MINUTES = 10  # 验证码有效期 10 分钟
    CODE_RESEND_SECONDS = 60  # 重复发送间隔

    # 今日新词数量
    DAILY_NEW_WORDS = 30
    # 熟悉后多少天重新出现
    FAMILIAR_REVIEW_DAYS = 30
    # 连续答对多少次标记为熟悉
    FAMILIAR_THRESHOLD = 3

    # Ollama 本地大模型（用于英文句子自动翻译）
    # 候选地址依次尝试：Docker 网络内用主机名 ollama；宿主机用 127.0.0.1 映射端口
    OLLAMA_BASE_URLS = [
        os.environ.get('OLLAMA_BASE_URL', 'http://ollama:11434/v1'),
        'http://127.0.0.1:11434/v1',
    ]
    OLLAMA_MODEL = os.environ.get('OLLAMA_MODEL', 'qwen2.5:7b')
    OLLAMA_TIMEOUT = 60  # 秒，首次调用需加载模型可能较慢
