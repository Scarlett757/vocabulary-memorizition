# -*- coding: utf-8 -*-
"""SQLAlchemy 模型类定义。

用类定义表结构，开发期用 SQLite，上线时改 config.py 连接串即可迁移到
MySQL/PostgreSQL，无需修改此处模型代码。
"""
from datetime import datetime, timedelta
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(db.Model):
    """用户表：邮箱注册，用户名默认为脱敏手机号。"""
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(128), unique=True, nullable=False)
    phone = db.Column(db.String(20))
    # 默认用户名为脱敏手机号：138****5678
    username = db.Column(db.String(64), unique=True, nullable=False)
    # 可空：支持纯邮箱验证码登录（未设密码时为 None）
    password_hash = db.Column(db.String(256))
    # 每日目标单词数（用户可在设置中修改，默认 30）
    daily_goal = db.Column(db.Integer, default=30)
    # 默认发音：us 或 uk
    default_accent = db.Column(db.String(4), default='us')
    # 词汇本层级：primary 小学 / middle 初中 / senior 高中 / cet4 / cet6 / ielts / custom 自选
    # middle 可细分：middle7 初一 / middle8 初二 / middle9 初三
    vocab_level = db.Column(db.String(16), default='cet4')
    # 熟悉判定阈值：连续答对多少次标记为熟悉（用户可自定义，默认 3）
    familiar_threshold = db.Column(db.Integer, default=3)
    created_at = db.Column(db.DateTime, default=datetime.now)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)


class EmailCode(db.Model):
    """邮箱验证码表：注册与邮箱登录共用。"""
    __tablename__ = 'email_codes'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(128), nullable=False, index=True)
    code = db.Column(db.String(6), nullable=False)
    purpose = db.Column(db.String(16), nullable=False)  # register / login
    expires_at = db.Column(db.DateTime, nullable=False)  # 过期时间
    used = db.Column(db.Integer, default=0)             # 0 未用 / 1 已用
    created_at = db.Column(db.DateTime, default=datetime.now)


class Word(db.Model):
    """单词词库表：id 即序号，按此顺序向用户展示。"""
    __tablename__ = 'words'
    id = db.Column(db.Integer, primary_key=True)        # 序号(按此顺序显示)
    english = db.Column(db.String(128), nullable=False, index=True)
    chinese = db.Column(db.String(512), nullable=False)
    phonetic = db.Column(db.String(128))
    # ECDICT tag 字段（如 "zk gk cet4 ielts"），用于词汇本分类
    tag = db.Column(db.String(128), index=True)
    # 词频（ECDICT bnc 字段），用于排序与小学词汇筛选
    frequency = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.now)


class UserCustomWord(db.Model):
    """用户自选词汇本：用户从词库搜索/手动添加的单词集合。"""
    __tablename__ = 'user_custom_words'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    word_id = db.Column(db.Integer, db.ForeignKey('words.id'), nullable=False)
    added_at = db.Column(db.DateTime, default=datetime.now)
    word = db.relationship('Word')

    __table_args__ = (
        db.UniqueConstraint('user_id', 'word_id', name='uq_user_custom_word'),
        db.Index('idx_custom_user', 'user_id'),
    )


class UserSentence(db.Model):
    """用户句子背诵本：手动添加英汉句子对，支持中英双向背诵。"""
    __tablename__ = 'user_sentences'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    english = db.Column(db.Text, nullable=False)
    chinese = db.Column(db.Text, nullable=False)
    # 背诵方向偏好：auto 自由 / cn2en 给中文背英文 / en2cn 给英文背中文
    direction = db.Column(db.String(8), default='auto')
    # 正向连续答对次数（用于熟悉判定）
    consecutive_correct = db.Column(db.Integer, default=0)
    last_reviewed_at = db.Column(db.DateTime)
    next_review_at = db.Column(db.DateTime)
    is_known_today = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.now)

    __table_args__ = (
        db.Index('idx_sentence_user', 'user_id'),
    )


class UserGroup(db.Model):
    """用户自定义分组：可收藏单词或句子，按组单独背诵。"""
    __tablename__ = 'user_groups'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    name = db.Column(db.String(64), nullable=False)
    # 分组类型：word 单词 / sentence 句子 / mixed 混合
    gtype = db.Column(db.String(8), default='word')
    created_at = db.Column(db.DateTime, default=datetime.now)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'name', name='uq_user_group_name'),
        db.Index('idx_group_user', 'user_id'),
    )


class UserGroupItem(db.Model):
    """分组条目：可引用 word_id 或 sentence_id（二选一）。"""
    __tablename__ = 'user_group_items'
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('user_groups.id'), nullable=False)
    word_id = db.Column(db.Integer, db.ForeignKey('words.id'), nullable=True)
    sentence_id = db.Column(db.Integer, db.ForeignKey('user_sentences.id'), nullable=True)
    added_at = db.Column(db.DateTime, default=datetime.now)
    word = db.relationship('Word')
    sentence = db.relationship('UserSentence')

    __table_args__ = (
        db.UniqueConstraint('group_id', 'word_id', 'sentence_id', name='uq_group_item'),
        db.Index('idx_item_group', 'group_id'),
    )


class TodayExtra(db.Model):
    """用户手动加入今日背诵的额外单词（当天有效）。"""
    __tablename__ = 'today_extras'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    word_id = db.Column(db.Integer, db.ForeignKey('words.id'), nullable=False)
    added_date = db.Column(db.Date, default=datetime.now().date)
    word = db.relationship('Word')

    __table_args__ = (
        db.UniqueConstraint('user_id', 'word_id', 'added_date', name='uq_today_extra'),
        db.Index('idx_today_extra', 'user_id', 'added_date'),
    )


class TodayPlan(db.Model):
    """今日背诵计划：记录当天系统生成给用户背诵的单词列表。

    一旦今日词表生成（新词 + 复习词 + 手动添加词），即使背完一些，
    也不会再自动补词；只有用户显式"继续背 N 个"才会追加。
    次日自动重新生成。
    """
    __tablename__ = 'today_plan'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    word_id = db.Column(db.Integer, db.ForeignKey('words.id'), nullable=False)
    plan_date = db.Column(db.Date, nullable=False)
    # role: new 新词 / review 复习 / extra 手动追加 / continue "继续背"追加
    role = db.Column(db.String(16), default='new')
    word = db.relationship('Word')

    __table_args__ = (
        db.UniqueConstraint('user_id', 'word_id', 'plan_date', name='uq_today_plan'),
        db.Index('idx_today_plan_user_date', 'user_id', 'plan_date'),
    )


class UserWordProgress(db.Model):
    """用户单词进度表：核心，记录掌握度与复习时间。"""
    __tablename__ = 'user_word_progress'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    word_id = db.Column(db.Integer, db.ForeignKey('words.id'), nullable=False)
    # new 新词 / learning 学习中 / familiar 熟悉
    status = db.Column(db.String(16), default='new')
    # 连续答对次数，达 FAMILIAR_THRESHOLD(3) 则标记 familiar
    consecutive_correct = db.Column(db.Integer, default=0)
    last_reviewed_at = db.Column(db.DateTime)            # 最后背诵时间
    next_review_at = db.Column(db.DateTime)             # 熟悉后 +30 天重新出现
    is_known_today = db.Column(db.Integer, default=0)   # 今日是否认识 0/1

    user = db.relationship('User', backref=db.backref('progress', lazy='dynamic'))
    word = db.relationship('Word')

    __table_args__ = (
        db.UniqueConstraint('user_id', 'word_id', name='uq_user_word'),
        db.Index('idx_progress_user_status', 'user_id', 'status'),
        db.Index('idx_progress_next_review', 'user_id', 'next_review_at'),
    )


class Checkin(db.Model):
    """用户打卡记录：每天可重复打卡（继续背后再次打卡）。"""
    __tablename__ = 'checkins'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    checkin_date = db.Column(db.Date, nullable=False)
    # 打卡来源：daily 每日目标完成 / group 分组背诵完成
    source = db.Column(db.String(16), default='daily')
    # 若 source=group，记录分组 id（可空）
    group_id = db.Column(db.Integer)
    # 当次打卡时今日已背单词数（仅作展示快照）
    words_count = db.Column(db.Integer, default=0)
    # 当次打卡时今日已背句子数
    sentences_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.now)

    __table_args__ = (
        db.Index('idx_checkin_user_date', 'user_id', 'checkin_date'),
    )


def mask_phone(phone):
    """手机号脱敏：保留前 3 位与后 4 位，中间 4 位替换为 *。
    例：13812345678 -> 138****5678
    """
    if not phone or len(phone) < 8:
        return phone or 'user'
    return phone[:3] + '****' + phone[-4:]
