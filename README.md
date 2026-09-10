# 单词背诵软件

一个基于 Flask 的英语词汇学习应用，面向小学、初中、高中、四六级、雅思、托福、GRE 和考研学习者。项目提供分层词库、今日背诵、间隔复习、发音、句子学习、自选词汇本和学习打卡等功能。

## 关键功能整理：
1. 电子词库可打印，用户可打印自己每天的背诵计划和遗忘清单，让背诵有记录，单词可复盘，不必完全依赖平台进行复习；打印出的背诵清单单词顺序随机，严格防止学生记忆单词顺序，背诵更高效；
2. 用户可以自定义模块分组，分组可同时包含单词和句子，可单独背诵
3. 本项目的设计来源于中小学家长反馈的需求，希望有一个平台可以帮整理学生每天应该背的新单词、新句子、应该复习的单词，并自动安排复习计划，同时可以自定义添加老师要求背诵的单词等等。用户可自行维护清单，也可在线背诵。


## 功能

- 分层词汇本：小学、初中、初一/初二/初三、高中、四级、六级、雅思、托福、GRE、考研
- ECDICT 全量词库导入与自选词汇本
- 今日背诵计划：新词、复习词和手动添加词
- 卡片式背诵：认识/忘记、进度记录和间隔复习
- 美音/英音发音，使用 `edge-tts` 按需生成并缓存
- 英汉句子管理与背诵，可选 Ollama 本地翻译
- 用户自定义分组、分组背诵和学习打卡
- 邮箱验证码注册与登录
- 深浅主题切换和每日学习规则设置


## 技术栈

- Python 3.13
- Flask、Flask-SQLAlchemy、SQLAlchemy
- MySQL 8.0（本地开发也支持 SQLite）
- Jinja2、原生 JavaScript、CSS
- ECDICT 英汉词典
- edge-tts
- Ollama + qwen2.5:7b（可选）
- Docker Compose


## 快速开始

### 本地运行

建议使用 Python 虚拟环境：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

复制环境变量模板并填写配置：

```powershell
Copy-Item .env.example .env
```

然后启动应用：

```powershell
python app.py
```

访问 <http://127.0.0.1:5000>。

未配置 MySQL 密码或 `DATABASE_URL` 时，应用会回退到项目目录下的 SQLite 数据库，适合快速试用。



### Docker Compose

先复制并填写环境变量：

```bash
cp .env.example .env
```

启动服务：

```bash
docker compose up -d --build
```

访问 <http://localhost:5000>。Compose 会启动应用、MySQL 和可选的 Ollama 服务。Ollama 模型首次准备可能需要较长时间和数 GB 磁盘空间。

停止服务：

```bash
docker compose down
```

MySQL 和 Ollama 数据保存在 Docker named volumes 中。

## 环境变量

主要配置项位于 `.env.example`：

| 变量 | 说明 |
| --- | --- |
| `SECRET_KEY` | Flask 会话密钥，生产环境必须替换为随机值 |
| `MYSQL_HOST` / `MYSQL_PORT` | MySQL 地址和端口 |
| `MYSQL_USER` / `MYSQL_PASSWORD` / `MYSQL_DATABASE` | MySQL 连接信息 |
| `DATABASE_URL` | 可选，设置后优先于 MySQL 分项配置 |
| `MAIL_SERVER` / `MAIL_PORT` | SMTP 服务器配置 |
| `MAIL_USERNAME` / `MAIL_PASSWORD` | SMTP 邮箱和授权码，不是邮箱登录密码 |
| `MAIL_FROM` | 邮件显示名或完整发件地址 |
| `OLLAMA_MODEL` | Ollama 使用的模型名称 |

`.env` 只保存在本地，不要提交到 Git。若授权码、密码或密钥曾经公开，应立即撤销并重新生成。

## 导入词库

`ecdict.csv` 是较大的本地数据文件，默认不需要在应用启动时导入。导入会清空现有 `words`、学习进度和自选词关联，请先备份数据库：

```powershell
python import_ecdict.py
```


推荐在全新数据库中执行导入脚本，不要对已经积累学习记录的生产数据库直接执行全量导入。


## 项目结构

```text
app.py                  Flask 路由和业务逻辑
models.py               SQLAlchemy 数据模型
config.py               环境变量和应用配置
templates/              Jinja2 页面模板
static/                 CSS、JavaScript 和音频缓存
import_ecdict.py        ECDICT 全量导入
scripts/                辅助导入脚本
data/                   教材词汇数据
Dockerfile              应用镜像构建文件
docker-compose.yml      应用、MySQL、Ollama 编排
.env.example             环境变量模板
```

##数据来源与第三方许可  
本项目的词库数据来源于以下开源项目，在此致谢：

ECDICT：采用 MIT License。Copyright (c) 2017 Linwei。项目地址：https://github.com/skywind3000/ECDICT

##许可证
本项目代码采用 MIT License，详见 LICENSE 文件。

##贡献
本项目持续维护，欢迎提交 Issue 或 Pull Request。

提交前请确保本地测试通过

新增功能请附带简要说明

如发现数据或翻译错误，欢迎反馈

# 如果这个项目对你有帮助，欢迎点一个 Star ⭐
# 联系作者 3649316781@qq.com
