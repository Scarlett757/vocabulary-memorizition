# Docker 部署操作手册

本文档适用于 Windows + Docker Desktop，也适用于 Linux/macOS（命令中的路径和复制文件命令按系统调整）。

## 1. 部署前准备

需要安装：

- Docker Desktop，并确认 Docker Engine 正常运行
- Git（如果从 GitHub 获取项目）
- 至少 2 GB 可用内存
- 如果启用 Ollama，建议准备更多内存和磁盘空间

检查 Docker：

```powershell
docker version
```

如果从 GitHub 获取代码：

```powershell
git clone <你的仓库地址>
cd <项目目录>
```

如果代码已经在本地，直接进入项目目录：

```powershell
cd "D:\AAAAoffer\单词背诵软件"
```

## 2. 准备 Docker 环境变量

不要把数据库密码、Flask 密钥或邮箱授权码写入 Python、`docker-compose.yml` 或 GitHub。

复制模板：

```powershell
Copy-Item .env.example .env.docker
```

编辑 `.env.docker`，至少填写以下内容：

```env
SECRET_KEY=替换为随机长字符串
MYSQL_ROOT_PASSWORD=MySQL根密码
MYSQL_USER=vocab_app
MYSQL_PASSWORD=应用数据库密码
MYSQL_DATABASE=vocabulary_memorization
MAIL_SERVER=smtp.qq.com
MAIL_PORT=465
MAIL_USERNAME=你的邮箱
MAIL_PASSWORD=SMTP授权码
MAIL_FROM=小易教育
OLLAMA_BASE_URL=http://host.docker.internal:11434/v1
OLLAMA_MODEL=qwen2.5:7b
```

生成随机 Flask 密钥：

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

注意：`MAIL_PASSWORD` 是邮箱 SMTP 授权码，不是邮箱登录密码。授权码如果曾经发到聊天、截图或公开仓库中，应先撤销并重新生成。

`.env.docker` 已加入 `.gitignore`，部署前确认：

```powershell
git check-ignore -v .env.docker
```

## 3. Ollama 的两种部署方式

### 方式 A：使用宿主机已有 Ollama，推荐

如果 Ollama 已经安装在 Windows 宿主机，并且可以访问：

```powershell
Invoke-WebRequest http://127.0.0.1:11434/api/tags -UseBasicParsing
```

`.env.docker` 使用：

```env
OLLAMA_BASE_URL=http://host.docker.internal:11434/v1
OLLAMA_MODEL=qwen2.5:7b
```

Docker 容器通过 `host.docker.internal` 访问 Windows 宿主机，不要在容器中使用 `127.0.0.1`。

确认模型存在：

```powershell
ollama list
```

### 方式 B：让 Docker 单独运行 Ollama

`.env.docker` 改为：

```env
OLLAMA_BASE_URL=http://ollama:11434/v1
OLLAMA_MODEL=qwen2.5:7b
```

启动 Ollama profile：

```powershell
docker compose -p vocabulary --env-file .env.docker --profile ollama up -d
```

首次启动可能下载约 5 GB 模型。若使用方式 A，不要加 `--profile ollama`，避免启动第二个 Ollama 或重复占用 11434 端口。

## 4. 启动应用和 MySQL

项目使用固定 Compose 项目名 `vocabulary`，避免目录名变化导致 volume 或网络名称变化：

```powershell
docker compose -p vocabulary --env-file .env.docker up -d --build app mysql
```

查看状态：

```powershell
docker compose -p vocabulary --env-file .env.docker ps
```

正常状态应类似：

```text
vocab_app    Up
vocab_mysql  Up ... (healthy)
```

访问：

<http://localhost:5001>

验证注册页面：

```powershell
Invoke-WebRequest http://127.0.0.1:5001/auth/register -UseBasicParsing
```

## 5. 数据库说明

默认使用 Docker 内的 MySQL 服务：

```text
应用容器 -> mysql:3306
```

Compose 没有把 MySQL 映射到宿主机 3306，因此不会和本机已有 MySQL 冲突。数据保存在 Docker volume：

```text
vocabulary_vocab_mysql_data
```

查看 volume：

```powershell
docker volume ls | Select-String vocabulary
```

不要轻易执行以下命令，因为它会删除数据库数据：

```powershell
docker compose -p vocabulary down -v
```

普通停止不会删除数据：

```powershell
docker compose -p vocabulary --env-file .env.docker down
```

## 6. 首次导入 ECDICT

`ecdict.csv` 约 66 MB，通常不会提交到 GitHub，也不会复制进 Docker 镜像。需要把它放到项目根目录。

先明确三种情况：

- **新电脑、新数据库**：必须准备 `ecdict.csv` 并执行导入，否则应用虽然能打开，但没有完整词库可背。
- **已经导入过词库的 Docker volume**：运行应用不需要再次准备 CSV，词库已经保存在 MySQL 数据卷中。
- **只想运行基础功能**：可以不导入 CSV，注册、登录、句子和分组等页面仍可启动，但单词库内容会为空或不完整。

不建议把 66 MB 的 CSV 直接放进 GitHub 主分支。推荐把它作为 Release 附件或放在可信的文件存储中，部署时下载到项目根目录。还需要确认 ECDICT 的许可和再分发条件。

当前镜像已包含 `pandas`，因此可以在容器中导入：

```powershell
docker cp .\ecdict.csv vocab_app:/app/ecdict.csv
docker exec vocab_app python import_ecdict.py
```

警告：`import_ecdict.py` 会清空：

- `words`
- `user_word_progress`
- `user_custom_words`

只建议在全新数据库上执行。已有用户和学习记录的环境，先备份数据库。

导入人教版初中词汇：

```powershell
docker cp .\data\pep_middle_school.json vocab_app:/app/data/pep_middle_school.json
docker exec vocab_app python scripts/import_pep_middle.py
```

确认词库数量：

```powershell
docker exec vocab_mysql mysql -uvocab_app -p你的应用数据库密码 vocabulary_memorization -e "SELECT COUNT(*) AS word_count FROM words;"
```

## 7. 发音音频说明

ECDICT 不包含项目所需的 MP3 发音文件，导入 `ecdict.csv` 不会导入音频。项目使用 `edge-tts` 按需生成发音：用户第一次点击 US 或 UK 发音时，应用在线生成对应 MP3，之后从缓存播放。

Compose 使用 `vocab_audio` volume 保存音频缓存，因此重建或更新 `app` 容器不会删除已经生成的发音。首次播放某个单词时需要网络连接；如果希望提前生成全部音频，可以执行：

```powershell
docker exec vocab_app python gen_audio.py
```

全量生成 77 万词条会产生大量音频、耗时很久并占用较多磁盘，不建议作为首次部署步骤。推荐按实际学习内容按需生成。

查看音频 volume：

```powershell
docker volume ls | Select-String vocabulary_vocab_audio
```

删除该 volume 会清空已经生成的发音缓存：

```powershell
docker volume rm vocabulary_vocab_audio
```

## 8. 数据库备份和恢复

备份：

```powershell
New-Item -ItemType Directory -Force .\backup | Out-Null
docker exec vocab_mysql mysqldump -uroot -p你的MySQL根密码 vocabulary_memorization > .\backup\vocabulary.sql
```

恢复前先停止应用：

```powershell
docker compose -p vocabulary --env-file .env.docker stop app
docker exec -i vocab_mysql mysql -uroot -p你的MySQL根密码 vocabulary_memorization < .\backup\vocabulary.sql
docker compose -p vocabulary --env-file .env.docker start app
```

不要把 `backup` 目录提交到 Git。建议把它加入 `.gitignore` 或保存到安全位置。

## 9. 修改 `.env.docker` 后如何生效

普通应用配置，例如 SMTP、Flask 密钥、Ollama 地址：

```powershell
docker compose -p vocabulary --env-file .env.docker up -d --force-recreate app
```

如果修改了依赖或 Dockerfile：

```powershell
docker compose -p vocabulary --env-file .env.docker up -d --build --force-recreate app
```

如果修改了 `MYSQL_PASSWORD`，仅重建应用容器不够。MySQL 用户密码保存在已有数据 volume 中，需要先在 MySQL 内同步：

```powershell
docker exec vocab_mysql mysql -uroot -p当前MySQL根密码 -e "ALTER USER 'vocab_app'@'%' IDENTIFIED BY '新的应用数据库密码'; FLUSH PRIVILEGES;"
```

然后重建应用：

```powershell
docker compose -p vocabulary --env-file .env.docker up -d --force-recreate app
```

不要因为改密码就执行 `down -v`，那会删除数据库数据。

## 10. 更新代码

拉取新代码后：

```powershell
git pull
docker compose -p vocabulary --env-file .env.docker up -d --build app mysql
```

如果更新涉及数据库结构，先备份，再执行项目提供的迁移脚本：

```powershell
docker cp .\migrate.py vocab_app:/app/migrate.py
docker exec vocab_app python migrate.py
```

## 11. 常见问题

### 10.1 `project name must not be empty`

始终指定项目名：

```powershell
docker compose -p vocabulary --env-file .env.docker ps
```

### 10.2 `Bind for 0.0.0.0:3306 failed`

说明宿主机 3306 已被 MySQL 占用。当前 Compose 已不映射 MySQL 宿主机端口，应用仍通过 `mysql:3306` 连接。不要把 `3306:3306` 加回去。

### 10.3 `Bind for 0.0.0.0:5001 failed`

说明宿主机 5001 被占用。修改 `docker-compose.yml` 左侧端口，例如：

```yaml
ports:
  - "5002:5000"
```

然后重建 app：

```powershell
docker compose -p vocabulary --env-file .env.docker up -d --force-recreate app
```

访问新的宿主机端口。

### 10.4 `Access denied for user 'vocab_app'`

通常是 `.env.docker` 的 `MYSQL_PASSWORD` 和已有 MySQL volume 中的实际密码不一致。使用当前 root 密码同步用户：

```powershell
docker exec vocab_mysql mysql -uroot -p当前root密码 -e "ALTER USER 'vocab_app'@'%' IDENTIFIED BY '新的应用密码'; FLUSH PRIVILEGES;"
docker compose -p vocabulary --env-file .env.docker up -d --force-recreate app
```

### 10.5 验证码发送失败

检查 `.env.docker`：

```env
MAIL_USERNAME=你的邮箱
MAIL_PASSWORD=新的SMTP授权码
MAIL_FROM=小易教育
```

查看日志：

```powershell
docker compose -p vocabulary --env-file .env.docker logs --tail=100 app
```

### 10.6 Ollama 翻译不可用

宿主机模式检查：

```powershell
Invoke-WebRequest http://127.0.0.1:11434/api/tags -UseBasicParsing
docker exec vocab_app python -c "import urllib.request; print(urllib.request.urlopen('http://host.docker.internal:11434/api/tags').status)"
```

如果使用 Docker Ollama，确认 `.env.docker` 是：

```env
OLLAMA_BASE_URL=http://ollama:11434/v1
```

并使用：

```powershell
docker compose -p vocabulary --env-file .env.docker --profile ollama up -d
```

### 10.7 查看完整日志

```powershell
docker compose -p vocabulary --env-file .env.docker logs -f app
```

按 `Ctrl+C` 退出日志查看，不会停止容器。

## 12. 停止、重启和彻底删除

重启应用：

```powershell
docker compose -p vocabulary --env-file .env.docker restart app
```

停止服务但保留数据：

```powershell
docker compose -p vocabulary --env-file .env.docker down
```

删除服务和数据库 volume（危险，会删除所有学习数据）：

```powershell
docker compose -p vocabulary down -v
```

执行最后一条命令前必须完成数据库备份。

# 给第一次部署者的完整操作顺序

如果你只想把项目跑起来，请只按照下面的步骤执行，不需要先阅读上面的全部说明。

## 第 1 步：安装 Docker Desktop

在 Windows 安装 Docker Desktop，安装完成后启动它，等待 Docker Desktop 显示 Docker Engine 正在运行。

打开 PowerShell，执行：

```powershell
docker version
```

如果能看到 `Client` 和 `Server` 两部分版本信息，说明 Docker 已准备好。

## 第 2 步：获取项目代码

如果项目在 GitHub：

```powershell
git clone <你的GitHub仓库地址>
cd <项目文件夹>
```

例如：

```powershell
git clone https://github.com/你的用户名/你的仓库.git
cd 你的仓库
```

如果项目已经下载到电脑，不需要 clone，直接进入项目文件夹。例如：

```powershell
cd "D:\AAAAoffer\单词背诵软件"
```

确认当前目录中能看到 `docker-compose.yml`：

```powershell
Get-ChildItem docker-compose.yml
```

## 第 3 步：准备环境变量文件

在项目根目录执行：

```powershell
Copy-Item .env.example .env.docker
notepad .env.docker
```

记事本打开后，填写这些内容：

```env
SECRET_KEY=随机长字符串
MYSQL_ROOT_PASSWORD=你设置的MySQL根密码
MYSQL_USER=vocab_app
MYSQL_PASSWORD=你设置的应用数据库密码
MYSQL_DATABASE=vocabulary_memorization
MAIL_SERVER=smtp.qq.com
MAIL_PORT=465
MAIL_USERNAME=你的QQ邮箱
MAIL_PASSWORD=你的SMTP授权码
MAIL_FROM=小易教育
OLLAMA_BASE_URL=http://host.docker.internal:11434/v1
OLLAMA_MODEL=qwen2.5:7b
```

注意：

- `MYSQL_ROOT_PASSWORD` 和 `MYSQL_PASSWORD` 可以自己设置，不需要使用本机 MySQL 的密码。
- `MAIL_PASSWORD` 必须是 SMTP 授权码，不是邮箱登录密码。
- `SECRET_KEY` 不要使用示例中的默认值。
- `.env.docker` 是私密文件，不要上传 GitHub，也不要发给别人。部署别人电脑时，让对方自己填写。
- 如果不需要邮箱验证码，可以暂时保留示例值，但注册验证码功能会发送失败。

生成随机 `SECRET_KEY`：

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

把输出结果复制到 `.env.docker` 的 `SECRET_KEY=` 后面。

## 第 4 步：确认 Ollama

### 已经在电脑上安装 Ollama

确认模型存在：

```powershell
ollama list
```

如果列表中有 `qwen2.5:7b`，保持：

```env
OLLAMA_BASE_URL=http://host.docker.internal:11434/v1
```

这种情况下，后面只启动 `app` 和 `mysql`，不会重复启动 Ollama。

### 没有安装 Ollama

也可以先不使用自动翻译，保留：

```env
OLLAMA_BASE_URL=http://host.docker.internal:11434/v1
```

应用的主要背诵功能仍然可以使用，只是句子自动翻译不可用。

如果想让 Docker 自动运行 Ollama，改成：

```env
OLLAMA_BASE_URL=http://ollama:11434/v1
```

后面启动命令要使用 `--profile ollama`，首次会下载较大的模型。

## 第 5 步：启动应用和数据库

推荐先启动应用和 MySQL，不启动 Docker Ollama：

```powershell
docker compose -p vocabulary --env-file .env.docker up -d --build app mysql
```

等待约 30 秒后查看状态：

```powershell
docker compose -p vocabulary --env-file .env.docker ps
```

必须看到：

```text
vocab_app    Up
vocab_mysql  Up ... (healthy)
```

如果状态正常，浏览器打开：

<http://localhost:5001>

## 第 6 步：验证网站是否正常

在 PowerShell 执行：

```powershell
Invoke-WebRequest http://127.0.0.1:5001/auth/register -UseBasicParsing
```

如果输出 `StatusCode : 200`，说明应用已经成功启动。

如果浏览器打不开，查看日志：

```powershell
docker compose -p vocabulary --env-file .env.docker logs --tail=100 app
```

## 第 7 步：准备并导入 ECDICT 词库

如果仓库中没有 `ecdict.csv`，需要从项目提供方单独获取，并把它放到项目根目录。确认文件存在：

```powershell
Get-Item .\ecdict.csv
```

把词库复制进运行中的应用容器：

```powershell
docker cp .\ecdict.csv vocab_app:/app/ecdict.csv
```

执行全量导入：

```powershell
docker exec vocab_app python import_ecdict.py
```

导入完成后，确认词条数量：

```powershell
docker exec vocab_mysql mysql -uvocab_app -p你的应用数据库密码 vocabulary_memorization -e "SELECT COUNT(*) AS word_count FROM words;"
```

重要：全量导入会清空现有词库、自选词和学习进度。第一次部署空数据库时执行最安全；已有数据时先备份。

## 第 8 步：可选，导入人教版初中词汇

如果需要初中教材词汇，执行：

```powershell
docker cp .\data\pep_middle_school.json vocab_app:/app/data/pep_middle_school.json
docker exec vocab_app python scripts/import_pep_middle.py
```

## 第 9 步：确认数据库数据会保留

查看 Docker 数据卷：

```powershell
docker volume ls | Select-String vocabulary
```

以后停止服务时使用：

```powershell
docker compose -p vocabulary --env-file .env.docker down
```

不要使用 `down -v`，否则会删除 MySQL 数据卷和学习数据。

## 第 10 步：以后如何启动和更新

电脑重启或 Docker Desktop 重启后，执行：

```powershell
docker compose -p vocabulary --env-file .env.docker up -d app mysql
```

代码更新后执行：

```powershell
git pull
docker compose -p vocabulary --env-file .env.docker up -d --build app mysql
```

修改 `.env.docker` 后执行：

```powershell
docker compose -p vocabulary --env-file .env.docker up -d --force-recreate app
```

## 第 11 步：最常见的三个问题

### 问题一：3306 端口被占用

不用处理。本项目的 MySQL 不映射到宿主机 3306，应用会通过 Docker 内部的 `mysql:3306` 连接，不会和本机 MySQL 冲突。

### 问题二：5001 端口被占用

打开 `docker-compose.yml`，把：

```yaml
- "5001:5000"
```

改成：

```yaml
- "5002:5000"
```

然后执行：

```powershell
docker compose -p vocabulary --env-file .env.docker up -d --force-recreate app
```

新的访问地址是 <http://localhost:5002>。

### 问题三：`Access denied for user 'vocab_app'`

说明 `.env.docker` 中的 `MYSQL_PASSWORD` 和已有数据库卷中的密码不一致。不要删除数据卷，先用 root 密码同步：

```powershell
docker exec vocab_mysql mysql -uroot -p当前root密码 -e "ALTER USER 'vocab_app'@'%' IDENTIFIED BY '新的应用密码'; FLUSH PRIVILEGES;"
docker compose -p vocabulary --env-file .env.docker up -d --force-recreate app
```

## 部署完成标准

满足下面四项，就代表部署完成：

1. `docker compose ... ps` 中 `vocab_app` 为 `Up`。
2. `vocab_mysql` 显示 `healthy`。
3. 浏览器能打开 <http://localhost:5001>。
4. 可以注册、登录并进入今日背诵页面。
