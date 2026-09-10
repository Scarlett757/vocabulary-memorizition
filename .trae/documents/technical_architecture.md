# 单词背诵网站 技术架构文档

## 1. 架构设计

```mermaid
flowchart TD
    A["前端: Flask Jinja2 模板 + CSS/JS"] --> B["后端: Flask (Python)"]
    B --> C["ORM: SQLAlchemy"]
    C --> D["数据库: SQLite(开发) / 可平滑迁移至 MySQL/PostgreSQL(上线)"]
    B --> E["业务逻辑: 路由/服务函数"]
    E --> F["邮件验证码服务 (SMTP)"]
```

## 2. 技术说明

* 前端：Flask Jinja2 模板 + 原生 CSS + 少量原生 JS（翻卡动效、标记交互）

* 后端：Flask（Python Web 框架）

* ORM：**SQLAlchemy**（用类定义模型，开发期用 SQLite，上线可切换 MySQL/PostgreSQL，仅需改连接串）

* 数据库：SQLite（开发期单文件）；上线改为 MySQL/PostgreSQL 时不受影响

* 认证：Flask session + werkzeug 密码哈希

* 邮件验证码：smtplib 发送（注册与邮箱登录均用验证码）

* 模板引擎：Jinja2（Flask 内置）

## 3. 路由定义

| 路由                  | 方法       | 用途                    |
| ------------------- | -------- | --------------------- |
| /auth/register      | GET/POST | 注册页（邮箱+验证码+手机号）       |
| /auth/login         | GET/POST | 登录页（账号密码 或 邮箱验证码 二选一） |
| /auth/logout        | POST     | 退出登录                  |
| /auth/send\_code    | POST     | 发送邮箱验证码（注册/登录用途参数）    |
| /                   | GET      | 主界面（三入口）              |
| /wordbook           | GET      | 我的单词书（全部单词）           |
| /today              | GET      | 今日背诵（30 新词 + 复习词）     |
| /study              | GET      | 单个单词背诵（翻卡）            |
| /api/word/<id>/mark | POST     | 标记单词熟记/遗忘，返回新状态       |

## 4. API 定义

### POST /auth/send\_code

请求体：

```json
{ "email": "user@example.com", "purpose": "register" | "login" }
```

响应：

```json
{ "success": true, "message": "验证码已发送" }
```

### POST /auth/register

请求体：

```json
{ "email": "...", "code": "6位验证码", "phone": "手机号", "password": "可选" }
```

逻辑：校验验证码 → 创建用户，username 默认为脱敏手机号

### POST /auth/login

请求体（二选一）：

```json
// 方式一：账号密码
{ "account": "用户名/邮箱/手机号", "password": "..." }
// 方式二：邮箱验证码
{ "email": "...", "code": "6位验证码" }
```

### POST /api/word/<id>/mark

请求体：

```json
{ "result": "known" | "forgotten" }
```

响应：

```json
{ "success": true, "status": "learning" | "familiar", "consecutive": 0, "next_review_at": "2026-10-07" }
```

逻辑：

* result=known：consecutive\_correct +1；若达到 3，status→familiar，next\_review\_at = 今天 + 30 天

* result=forgotten：consecutive\_correct 清零，status 保持/回退为 learning

## 5. 服务架构

```mermaid
flowchart LR
    A["Flask 路由 (views)"] --> B["服务函数 (逻辑)"]
    B --> C["SQLAlchemy ORM (models)"]
    C --> D["数据库"]
    B --> E["邮件验证码服务"]
```

## 6. 数据模型（SQLAlchemy 类定义）

### 6.1 ER 图

```mermaid
erDiagram
    users ||--o{ user_word_progress : "1对多"
    words ||--o{ user_word_progress : "1对多"
    email_codes {
        integer id PK
        text email
        text code
        text purpose
        text expires_at
        integer used
    }
    users {
        integer id PK
        text email UK
        text phone
        text username "默认脱敏手机号"
        text password_hash "可空(邮箱验证码登录)"
        text created_at
    }
    words {
        integer id PK "序号"
        text english
        text chinese
        text phonetic
        text created_at
    }
    user_word_progress {
        integer id PK
        integer user_id FK
        integer word_id FK
        text status "new/learning/familiar"
        integer consecutive_correct
        text last_reviewed_at
        text next_review_at
        integer is_known_today "0/1"
    }
```

### 6.2 SQLAlchemy 模型类（models.py）

```python
from datetime import datetime, timedelta
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(128), unique=True, nullable=False)
    phone = db.Column(db.String(20))
    username = db.Column(db.String(64), unique=True, nullable=False)  # 默认脱敏手机号
    password_hash = db.Column(db.String(256))  # 可空：支持纯验证码登录
    created_at = db.Column(db.DateTime, default=datetime.now)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return self.password_hash and check_password_hash(self.password_hash, password)

class EmailCode(db.Model):
    __tablename__ = 'email_codes'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(128), nullable=False)
    code = db.Column(db.String(6), nullable=False)
    purpose = db.Column(db.String(16), nullable=False)  # register / login
    expires_at = db.Column(db.DateTime, nullable=False)  # 默认10分钟后过期
    used = db.Column(db.Integer, default=0)

class Word(db.Model):
    __tablename__ = 'words'
    id = db.Column(db.Integer, primary_key=True)        # 序号(按此顺序显示)
    english = db.Column(db.String(128), nullable=False)
    chinese = db.Column(db.String(256), nullable=False)
    phonetic = db.Column(db.String(128))
    created_at = db.Column(db.DateTime, default=datetime.now)

class UserWordProgress(db.Model):
    __tablename__ = 'user_word_progress'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    word_id = db.Column(db.Integer, db.ForeignKey('words.id'), nullable=False)
    status = db.Column(db.String(16), default='new')           # new/learning/familiar
    consecutive_correct = db.Column(db.Integer, default=0)     # 达3则熟悉
    last_reviewed_at = db.Column(db.DateTime)                  # 背诵时间
    next_review_at = db.Column(db.DateTime)                    # 熟悉后+30天重新出现
    is_known_today = db.Column(db.Integer, default=0)          # 今日是否认识 0/1
    __table_args__ = (db.UniqueConstraint('user_id', 'word_id'),)
```

### 6.3 用户名脱敏规则

* 注册时默认 username = 手机号脱敏：`13812345678` → `138****5678`

* 即保留前 3 位与后 4 位，中间 4 位替换为 `*`

## 7. 今日背诵取词逻辑

* **30 个新词**：从 Word 表按 id 顺序取该用户在 UserWordProgress 中尚无记录的前 30 个

* **复习词**：UserWordProgress 中 next\_review\_at <= 今天 的 familiar/learning 词

* 合并后按 word.id 排序展示

## 8. 项目结构

```
单词背诵软件/
├── app.py                  # Flask 入口与路由
├── models.py               # SQLAlchemy 模型类
├── config.py               # 配置(DB连接串/邮件配置/密钥)
├── seed.py                 # 导入示例词库
├── words.db                # SQLite 数据库（开发期生成）
├── templates/
│   ├── base.html           # 基础模板（导航）
│   ├── auth.html           # 登录/注册
│   ├── index.html          # 主界面
│   ├── wordbook.html       # 我的单词书
│   ├── today.html          # 今日背诵
│   └── study.html          # 单个单词背诵
├── static/
│   ├── css/style.css       # 样式
│   └── js/main.js          # 翻卡与标记交互
└── .trae/documents/        # 文档
```

## 9. 上线迁移说明

* 仅改 `config.py` 中 `SQLALCHEMY_DATABASE_URI`：

  * 开发：`sqlite:///words.db`

  * 上线 MySQL：`mysql+pymysql://user:pass@host/db`

  * 上线 PostgreSQL：`postgresql+psycopg2://user:pass@host/db`

* 执行 `db.create_all()` 自动建表，无需改模型代码

