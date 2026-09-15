# -*- coding: utf-8 -*-
"""Flask 入口与路由。

包含：邮箱验证码发送/校验、双登录(账号密码/邮箱验证码)、
主界面、我的单词书、今日背诵、单个单词背诵、单词标记 API。
"""
import random
import copy
import smtplib
import string
from datetime import datetime, timedelta, date
from email.mime.text import MIMEText
from email.header import Header
from email.utils import formataddr
from sqlalchemy import case

import requests

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, jsonify, flash, abort
)
from config import Config
from models import db, User, EmailCode, Word, UserWordProgress, UserMasteredWord, UserCustomWord, UserExcludedWord, UserWordOverride, UserSentence, UserGroup, UserGroupItem, TodayExtra, TodayPlan, Checkin, mask_phone

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def login_required(view):
    """登录态拦截装饰器。"""
    from functools import wraps
    @wraps(view)
    def wrapped(*args, **kwargs):
        if 'user_id' not in session:
            flash('请先登录', 'error')
            return redirect(url_for('login'))
        return view(*args, **kwargs)
    return wrapped


def current_user():
    if 'user_id' in session:
        return User.query.get(session['user_id'])
    return None


def send_email_code(to_email, code, purpose):
    """通过 SMTP 发送验证码邮件。

    开发期若未配置 SMTP，会返回失败；前端可改用控制台打印的验证码。
    """
    cfg = app.config
    if not cfg.get('MAIL_USERNAME') or not cfg.get('MAIL_PASSWORD'):
        # 未配置 SMTP：开发模式，把验证码写入日志便于调试
        app.logger.warning('[开发模式] 验证码 %s -> %s (用途: %s)', code, to_email, purpose)
        return False

    subject = '【单词背诵】您的验证码' if purpose == 'login' else '【单词背诵】注册验证码'
    body = f'您的验证码是：{code}\n验证码 {cfg["CODE_EXPIRE_MINUTES"]} 分钟内有效，请勿泄露。'
    msg = MIMEText(body, 'plain', 'utf-8')
    msg['Subject'] = Header(subject, 'utf-8')
    from_value = cfg.get('MAIL_FROM') or cfg.get('MAIL_USERNAME')
    from_address = cfg.get('MAIL_USERNAME')
    if from_value and '@' in from_value:
        from_address = from_value
        msg['From'] = from_value
    else:
        msg['From'] = formataddr((from_value, from_address))
    msg['To'] = to_email

    try:
        if cfg.get('MAIL_USE_SSL'):
            server = smtplib.SMTP_SSL(cfg['MAIL_SERVER'], cfg['MAIL_PORT'])
        else:
            server = smtplib.SMTP(cfg['MAIL_SERVER'], cfg['MAIL_PORT'])
            server.starttls()
        server.login(cfg['MAIL_USERNAME'], cfg['MAIL_PASSWORD'])
        server.sendmail(from_address, [to_email], msg.as_string())
        server.quit()
        return True
    except Exception as e:
        app.logger.error('邮件发送失败: %s', e)
        return False


def generate_code(length=6):
    """生成数字验证码。"""
    return ''.join(random.choices(string.digits, k=length))


# ---------------------------------------------------------------------------
# 认证路由
# ---------------------------------------------------------------------------
@app.route('/auth/send_code', methods=['POST'])
def send_code():
    """发送邮箱验证码（注册/登录共用，靠 purpose 区分）。"""
    email = (request.form.get('email') or '').strip().lower()
    purpose = (request.form.get('purpose') or 'login').strip()
    if not email:
        return jsonify(success=False, message='请填写邮箱'), 400
    if purpose not in ('register', 'login'):
        return jsonify(success=False, message='用途参数非法'), 400

    # 注册：邮箱未被占用
    if purpose == 'register' and User.query.filter_by(email=email).first():
        return jsonify(success=False, message='该邮箱已注册'), 400
    # 登录：邮箱必须已注册
    if purpose == 'login' and not User.query.filter_by(email=email).first():
        return jsonify(success=False, message='该邮箱未注册'), 400

    # 重复发送间隔限制
    latest = EmailCode.query.filter_by(email=email, purpose=purpose) \
        .order_by(EmailCode.created_at.desc()).first()
    if latest and latest.created_at and \
            (datetime.now() - latest.created_at).total_seconds() < app.config['CODE_RESEND_SECONDS']:
        return jsonify(success=False, message='发送太频繁，请稍后再试'), 429

    code = generate_code(app.config['CODE_LENGTH'])
    record = EmailCode(
        email=email,
        code=code,
        purpose=purpose,
        expires_at=datetime.now() + timedelta(minutes=app.config['CODE_EXPIRE_MINUTES']),
    )
    db.session.add(record)
    db.session.commit()

    sent = send_email_code(email, code, purpose)
    if sent:
        return jsonify(success=True, message='验证码已发送至邮箱')
    # SMTP 未配置或发送失败：返回错误，不直接暴露验证码
    return jsonify(success=False, message='验证码发送失败，请稍后重试或联系管理员'), 502


@app.route('/auth/register', methods=['GET', 'POST'])
def register():
    """注册：邮箱 + 验证码 + 手机号；用户名默认为脱敏手机号。"""
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        code = (request.form.get('code') or '').strip()
        phone = (request.form.get('phone') or '').strip()
        password = (request.form.get('password') or '').strip()

        if not email or not code or not phone:
            flash('邮箱、验证码、手机号均必填', 'error')
            return render_template('auth.html', mode='register')
        if User.query.filter_by(email=email).first():
            flash('该邮箱已注册', 'error')
            return render_template('auth.html', mode='register')

        # 校验验证码
        record = EmailCode.query.filter_by(
            email=email, purpose='register', used=0
        ).order_by(EmailCode.created_at.desc()).first()
        now = datetime.now()
        if not record or record.code != code or record.expires_at < now:
            flash('验证码错误或已过期', 'error')
            return render_template('auth.html', mode='register')

        # 默认用户名为脱敏手机号；若冲突则追加数字
        username = mask_phone(phone)
        if User.query.filter_by(username=username).first():
            username = f'{username}_{random.randint(1000, 9999)}'

        user = User(email=email, phone=phone, username=username)
        if password:
            user.set_password(password)
        db.session.add(user)

        record.used = 1
        db.session.commit()

        session['user_id'] = user.id
        flash(f'注册成功，欢迎 {user.username}', 'success')
        return redirect(url_for('index'))
    return render_template('auth.html', mode='register')


@app.route('/auth/login', methods=['GET', 'POST'])
def login():
    """登录：方式一 账号密码；方式二 邮箱验证码。"""
    if request.method == 'POST':
        mode = request.form.get('login_mode', 'password')
        if mode == 'code':
            # 邮箱验证码登录
            email = (request.form.get('email') or '').strip().lower()
            code = (request.form.get('code') or '').strip()
            if not email or not code:
                flash('请填写邮箱和验证码', 'error')
                return render_template('auth.html', mode='login')
            user = User.query.filter_by(email=email).first()
            if not user:
                flash('该邮箱未注册', 'error')
                return render_template('auth.html', mode='login')
            record = EmailCode.query.filter_by(
                email=email, purpose='login', used=0
            ).order_by(EmailCode.created_at.desc()).first()
            now = datetime.now()
            if not record or record.code != code or record.expires_at < now:
                flash('验证码错误或已过期', 'error')
                return render_template('auth.html', mode='login')
            record.used = 1
            db.session.commit()
            session['user_id'] = user.id
            return redirect(url_for('index'))
        else:
            # 账号密码登录：先查账号是否存在，再校验密码，给出精确报错
            account = (request.form.get('account') or '').strip()
            password = (request.form.get('password') or '').strip()
            if not account or not password:
                flash('请填写账号和密码', 'error')
                return render_template('auth.html', mode='login')
            # 账号可为 用户名 / 邮箱 / 手机号
            user = User.query.filter(
                (User.username == account) |
                (User.email == account.lower()) |
                (User.phone == account)
            ).first()
            # 第一步：账号是否存在
            if not user:
                flash(f'账号「{account}」不存在，请检查或先去注册', 'error')
                return render_template('auth.html', mode='login')
            # 该账号未设置密码（仅支持验证码登录）
            if not user.password_hash:
                flash('该账号未设置密码，请使用邮箱验证码登录', 'error')
                return render_template('auth.html', mode='login')
            # 第二步：密码是否正确
            if not user.check_password(password):
                flash('密码错误，请重新输入', 'error')
                return render_template('auth.html', mode='login')
            session['user_id'] = user.id
            return redirect(url_for('index'))
    return render_template('auth.html', mode='login')


@app.route('/auth/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect(url_for('login'))


# ---------------------------------------------------------------------------
# 业务路由
# ---------------------------------------------------------------------------
def get_user_daily_goal(user):
    """获取用户每日目标，取用户设置或默认值。"""
    return user.daily_goal or app.config['DAILY_NEW_WORDS']


# 词汇本层级 -> ECDICT tag 关键字映射
LEVEL_TAG_MAP = {
    'primary': 'primary',  # 小学：导入时标记的常用词
    'middle': 'zk',        # 初中：中考
    'middle7': 'zk',       # 初一（人教版七年级，用词频分层近似）
    'middle8': 'zk',       # 初二（人教版八年级）
    'middle9': 'zk',       # 初三（人教版九年级）
    'senior': 'gk',        # 高中：高考
    'cet4': 'cet4',
    'cet6': 'cet6',
    'ielts': 'ielts',
    'toefl': 'toefl',
    'gre': 'gre',
    'ky': 'ky',
}

LEVEL_LABELS = {
    'primary': '小学',
    'middle': '初中',
    'middle7': '初一',
    'middle8': '初二',
    'middle9': '初三',
    'senior': '高中',
    'cet4': '四级',
    'cet6': '六级',
    'ielts': '雅思',
    'toefl': '托福',
    'gre': 'GRE',
    'ky': '考研',
    'custom': '自选',
}


def level_word_query(user):
    """返回按用户当前 vocab_level 过滤后的 Word 基礎查询（未加 limit/order）。"""
    level = user.vocab_level or 'cet4'
    if level == 'custom':
        custom_ids = db.session.query(UserCustomWord.word_id).filter_by(user_id=user.id).all()
        ids = [i[0] for i in custom_ids]
        if ids:
            return Word.query.filter(Word.id.in_(ids))
        return Word.query.filter(False)
    tag = LEVEL_TAG_MAP.get(level, 'cet4')
    q = Word.query.filter(Word.tag.like(f'%{tag}%'))
    # 初中细分：按词频分层近似人教版七/八/九年级
    if level == 'middle7':
        q = q.filter(Word.frequency > 0).order_by(Word.frequency.desc())
    elif level == 'middle8':
        q = q.filter(Word.frequency > 0)
    elif level == 'middle9':
        q = q.filter(Word.frequency > 0).order_by(Word.frequency.asc())
    return q


def get_user_familiar_threshold(user):
    """获取用户自定义的熟悉阈值，默认 3。"""
    return user.familiar_threshold or app.config['FAMILIAR_THRESHOLD']


def apply_word_overrides(user, words):
    """将当前用户的释义覆盖应用到页面使用的单词对象。"""
    if not words:
        return words
    overrides = UserWordOverride.query.filter(
        UserWordOverride.user_id == user.id,
        UserWordOverride.word_id.in_([w.id for w in words]),
    ).all()
    override_map = {item.word_id: item.chinese for item in overrides}
    result = []
    for word in words:
        display_word = copy.copy(word)
        if word.id in override_map:
            display_word.chinese = override_map[word.id]
        result.append(display_word)
    return result


def audio_filename(english):
    """把英文单词转为音频文件名（与 gen_audio.py 中 safe_filename 一致）。"""
    import re
    return re.sub(r'[^a-zA-Z0-9]', '_', english).lower()


def get_today_words(user, count=None):
    """今日词表：新词(按 id 顺序、无进度) + 复习词 + 手动加入的额外词，按 id 升序。

    新词按用户当前词汇本层级过滤；复习词不重复取层级过滤。
    count 指定本次要取的新词数量；不传则用用户每日目标。

    持久化到 TodayPlan：当天首次访问时生成并保存；后续访问不再自动补词，
    仅按当天已点 ✓ 状态过滤。次日自动重新生成。
    """
    if count is None:
        count = get_user_daily_goal(user)
    today = date.today()
    excluded_ids = {item[0] for item in db.session.query(UserExcludedWord.word_id).filter_by(user_id=user.id).all()}

    # 查今日是否已生成计划
    plan_items = TodayPlan.query.filter_by(user_id=user.id, plan_date=today).all()
    if not plan_items:
        # 首次生成今日计划：新词 + 复习词 + 手动添加词
        learned = db.session.query(UserWordProgress.word_id).filter_by(user_id=user.id).all()
        learned_ids = [i[0] for i in learned]
        new_q = level_word_query(user) if user.auto_daily_words else Word.query.filter(False)
        if learned_ids:
            new_q = new_q.filter(~Word.id.in_(learned_ids))
        if excluded_ids:
            new_q = new_q.filter(~Word.id.in_(excluded_ids))
        new_words = new_q.order_by(Word.id.asc()).limit(count).all()

        review_progress = UserWordProgress.query.filter(
            UserWordProgress.user_id == user.id,
            db.or_(
                db.and_(
                    UserWordProgress.next_review_at.isnot(None),
                    UserWordProgress.next_review_at <= datetime.now(),
                ),
                db.and_(
                    UserWordProgress.status == 'learning',
                    UserWordProgress.last_reviewed_at.isnot(None),
                    db.func.date(UserWordProgress.last_reviewed_at) < today,
                ),
            ),
        ).all() if user.auto_daily_words else []
        review_words = [Word.query.get(p.word_id) for p in review_progress]
        review_words = [w for w in review_words if w and w.id not in excluded_ids]

        extra_items = TodayExtra.query.filter_by(user_id=user.id, added_date=today).all()
        extra_words = [it.word for it in extra_items if it.word]
        existing_ids = set(w.id for w in new_words + review_words)
        extra_words = [w for w in extra_words if w.id not in existing_ids]

        # 持久化到 TodayPlan（去重）
        seen = set()
        for w in new_words:
            if w.id not in seen:
                db.session.add(TodayPlan(user_id=user.id, word_id=w.id,
                                         plan_date=today, role='new'))
                seen.add(w.id)
        for w in review_words:
            if w.id not in seen:
                db.session.add(TodayPlan(user_id=user.id, word_id=w.id,
                                         plan_date=today, role='review'))
                seen.add(w.id)
        for w in extra_words:
            if w.id not in seen:
                db.session.add(TodayPlan(user_id=user.id, word_id=w.id,
                                         plan_date=today, role='extra'))
                seen.add(w.id)
        db.session.commit()
        # 重新查
        plan_items = TodayPlan.query.filter_by(user_id=user.id, plan_date=today).all()

    # 从 TodayPlan 加载今日词
    today_words = [it.word for it in plan_items if it.word and it.word.id not in excluded_ids]
    today_words.sort(key=lambda w: w.id)
    new_words = [w for w in today_words if any(it.role == 'new' and it.word_id == w.id
                 for it in plan_items)]
    review_words = [w for w in today_words if any(it.role == 'review' and it.word_id == w.id
                    for it in plan_items)]

    # 排除今天已点过 ✓ 的单词（is_known_today=1 且 last_reviewed_at 是今天）
    known_today_ids = set(p.word_id for p in UserWordProgress.query.filter(
        UserWordProgress.user_id == user.id,
        UserWordProgress.is_known_today == 1,
        db.func.date(UserWordProgress.last_reviewed_at) == today,
    ).all())
    today_words = [w for w in today_words if w.id not in known_today_ids]
    return apply_word_overrides(user, today_words), apply_word_overrides(user, new_words), apply_word_overrides(user, review_words)


def add_continue_words(user, count):
    """继续背 N 个：从词库追加 N 个新词到今日计划（不再自动补满到目标数）。

    返回添加的 Word 列表。
    """
    today = date.today()
    learned = db.session.query(UserWordProgress.word_id).filter_by(user_id=user.id).all()
    learned_ids = [i[0] for i in learned]
    # 也排除今日计划中已有的
    plan_ids = [p.word_id for p in TodayPlan.query.filter_by(
        user_id=user.id, plan_date=today).all()]
    exclude_ids = list(set(learned_ids + plan_ids))
    exclude_ids.extend(item[0] for item in db.session.query(UserExcludedWord.word_id).filter_by(user_id=user.id).all())
    q = level_word_query(user)
    if exclude_ids:
        q = q.filter(~Word.id.in_(exclude_ids))
    new_words = q.order_by(Word.id.asc()).limit(count).all()
    for w in new_words:
        db.session.add(TodayPlan(user_id=user.id, word_id=w.id,
                                 plan_date=today, role='continue'))
    db.session.commit()
    return new_words


def get_today_learned_count(user):
    """统计今天已熟记的单词数（is_known_today=1 且 last_reviewed_at 是今天）。"""
    today = date.today()
    return UserWordProgress.query.filter_by(
        user_id=user.id, is_known_today=1
    ).filter(
        db.func.date(UserWordProgress.last_reviewed_at) == today
    ).count()


@app.route('/')
@login_required
def index():
    """主界面：三入口卡片 + 今日进度统计。"""
    user = current_user()
    goal = get_user_daily_goal(user)
    learned_ids = db.session.query(UserWordProgress.word_id).filter_by(user_id=user.id).all()
    learned_ids = [i[0] for i in learned_ids]
    new_words_q = level_word_query(user) if user.auto_daily_words else Word.query.filter(False)
    excluded_ids = [item[0] for item in db.session.query(UserExcludedWord.word_id).filter_by(user_id=user.id).all()]
    if learned_ids:
        new_words_q = new_words_q.filter(~Word.id.in_(learned_ids))
    if excluded_ids:
        new_words_q = new_words_q.filter(~Word.id.in_(excluded_ids))
    new_today = new_words_q.order_by(Word.id.asc()).limit(goal).count()
    today_date = date.today()
    review_today = UserWordProgress.query.filter(
        UserWordProgress.user_id == user.id,
        db.or_(
            db.and_(
                UserWordProgress.next_review_at.isnot(None),
                UserWordProgress.next_review_at <= datetime.now(),
            ),
            db.and_(
                UserWordProgress.status == 'learning',
                UserWordProgress.last_reviewed_at.isnot(None),
                db.func.date(UserWordProgress.last_reviewed_at) < today_date,
            ),
        ),
    ).filter(~UserWordProgress.word_id.in_(excluded_ids)).count() if user.auto_daily_words else 0
    familiar = UserWordProgress.query.filter_by(user_id=user.id, status='familiar').count()
    deleted_count = UserExcludedWord.query.filter_by(user_id=user.id).count()
    total = level_word_query(user).count()
    today_learned = get_today_learned_count(user)
    # 今日忘记单词数：今天标记为忘记的单词（is_known_today=0 且 last_reviewed_at 为今天）
    forgotten_count = UserWordProgress.query.filter(
        UserWordProgress.user_id == user.id,
        UserWordProgress.is_known_today == 0,
        UserWordProgress.last_reviewed_at.isnot(None),
        db.func.date(UserWordProgress.last_reviewed_at) == today_date,
    ).count()
    level_label = LEVEL_LABELS.get(user.vocab_level or 'cet4', '四级')
    return render_template('index.html', user=user, new_today=new_today,
                           review_today=review_today, familiar=familiar, total=total,
                           goal=goal, today_learned=today_learned,
                           level_label=level_label, vocab_level=user.vocab_level or 'cet4',
                           forgotten_count=forgotten_count, deleted_count=deleted_count)


@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    """规则设置：每日目标、发音、词汇本层级、熟悉阈值。"""
    user = current_user()
    if request.method == 'POST':
        try:
            goal = int(request.form.get('daily_goal', 30))
        except (TypeError, ValueError):
            goal = 30
        if goal < 5:
            goal = 5
        elif goal > 100:
            goal = 100
        accent = request.form.get('default_accent', 'us')
        if accent not in ('us', 'uk'):
            accent = 'us'
        level = request.form.get('vocab_level', 'cet4')
        if level not in LEVEL_LABELS:
            level = 'cet4'
        try:
            ft = int(request.form.get('familiar_threshold', 3))
        except (TypeError, ValueError):
            ft = 3
        if ft < 2:
            ft = 2
        elif ft > 10:
            ft = 10
        user.daily_goal = goal
        user.default_accent = accent
        user.vocab_level = level
        user.familiar_threshold = ft
        user.auto_daily_words = 1 if request.form.get('auto_daily_words') == '1' else 0
        # 词书或自动选词开关改变后，重新建立当天自动计划；手动添加的 TodayExtra 会保留。
        TodayPlan.query.filter_by(user_id=user.id, plan_date=date.today()).delete(
            synchronize_session=False)
        db.session.commit()
        flash('设置已保存', 'success')
        return redirect(url_for('settings'))
    return render_template('settings.html', user=user, level_labels=LEVEL_LABELS)


@app.route('/wordbook')
@login_required
def wordbook():
    """我的单词书：显示当前词汇本单词及其掌握状态。

    支持 status 过滤（new/learning/familiar/all）与 category 过滤
    （new_today 今日新词 / review_today 待复习 / familiar 已熟悉）。
    """
    user = current_user()
    status_filter = request.args.get('status', 'all')
    category = request.args.get('category', '')
    progress_map = {p.word_id: p for p in UserWordProgress.query.filter_by(user_id=user.id).all()}
    excluded_ids = {item[0] for item in db.session.query(UserExcludedWord.word_id).filter_by(user_id=user.id).all()}
    words = level_word_query(user).order_by(Word.id.asc()).all()
    familiar_only = category == 'familiar'
    if category == 'deleted':
        words = [item.word for item in UserExcludedWord.query.filter_by(user_id=user.id).all() if item.word]
    elif category == 'mastered':
        words = [item.word for item in UserMasteredWord.query.filter_by(user_id=user.id).all() if item.word]
    elif excluded_ids:
        words = [w for w in words if w.id not in excluded_ids]

    today_date = date.today()
    if category == 'new_today':
        learned_ids = set(progress_map.keys())
        words = [w for w in words if w.id not in learned_ids][:200]
    elif category == 'review_today':
        review_ids = set()
        for p in progress_map.values():
            if (p.next_review_at and p.next_review_at <= datetime.now()) or \
               (p.status == 'learning' and p.last_reviewed_at and
                p.last_reviewed_at.date() < today_date):
                review_ids.add(p.word_id)
        words = [w for w in words if w.id in review_ids]
    elif familiar_only:
        words = [w for w in words if w.id in progress_map and progress_map[w.id].status == 'familiar']

    words = apply_word_overrides(user, words)
    rows = []
    for w in words:
        p = progress_map.get(w.id)
        status = p.status if p else 'new'
        rows.append({
            'id': w.id, 'english': w.english, 'chinese': w.chinese,
            'phonetic': w.phonetic or '', 'status': status,
            'progress': p,
            'deleted': w.id in excluded_ids,
        })
    if status_filter != 'all' and not category:
        rows = [r for r in rows if r['status'] == status_filter]
    status_map = {'new': '新词', 'learning': '学习中', 'familiar': '熟悉', 'mastered': '已会'}
    level_label = LEVEL_LABELS.get(user.vocab_level or 'cet4', '四级')
    # 整体进度统计（基于用户当前词汇本）
    all_level_words = level_word_query(user).all()
    total_count = len(all_level_words)
    familiar_count = sum(1 for w in all_level_words
                         if w.id in progress_map and progress_map[w.id].status == 'familiar')
    learning_count = sum(1 for w in all_level_words
                         if w.id in progress_map and progress_map[w.id].status == 'learning')
    return render_template('wordbook.html', rows=rows, status_map=status_map,
                           current_filter=status_filter, category=category,
                           level_label=level_label, user=user,
                           familiar_threshold=get_user_familiar_threshold(user),
                           total_count=total_count, familiar_count=familiar_count,
                           learning_count=learning_count)


@app.route('/today')
@login_required
def today():
    """今日背诵：用户目标数量的新词 + 到期复习词。

    序号在模板中从 1 重新编号，不显示 word.id 本身序号。
    """
    user = current_user()
    today_words, new_words, review_words = get_today_words(user)
    new_word_ids = {word.id for word in new_words}
    new_count = sum(1 for word in today_words if word.id in new_word_ids)
    review_extra_count = max(0, len(today_words) - new_count)
    progress_map = {p.word_id: p for p in UserWordProgress.query.filter_by(user_id=user.id).all()}
    status_map = {'new': '新词', 'learning': '学习中', 'familiar': '熟悉'}
    return render_template('today.html', words=today_words, progress_map=progress_map,
                           status_map=status_map, user=user,
                           today_learned=get_today_learned_count(user),
                           goal=get_user_daily_goal(user),
                           new_count=new_count,
                           review_extra_count=review_extra_count,
                           familiar_threshold=get_user_familiar_threshold(user),
                           forgotten_mode=False)


@app.route('/today/forgotten')
@login_required
def today_forgotten():
    """今日忘记单词列表：单独背诵今日标记为忘记的单词。

    通过 /api/word/<id>/mark 标记后实时更新进度（点 ✓ 进度 +1/3，点 ✗ 清零）。
    复用 today.html 模板，传入 forgotten_mode=True 标记，由模板隐藏无关按钮。
    """
    user = current_user()
    today_date = date.today()
    forgotten_progress = UserWordProgress.query.filter(
        UserWordProgress.user_id == user.id,
        UserWordProgress.is_known_today == 0,
        UserWordProgress.last_reviewed_at.isnot(None),
        db.func.date(UserWordProgress.last_reviewed_at) == today_date,
    ).all()
    forgotten_words = [Word.query.get(p.word_id) for p in forgotten_progress]
    forgotten_words = [w for w in forgotten_words if w]
    progress_map = {p.word_id: p for p in UserWordProgress.query.filter_by(user_id=user.id).all()}
    status_map = {'new': '新词', 'learning': '学习中', 'familiar': '熟悉'}
    return render_template('today.html', words=forgotten_words, progress_map=progress_map,
                           status_map=status_map, user=user,
                           today_learned=get_today_learned_count(user),
                           goal=len(forgotten_words),
                           familiar_threshold=get_user_familiar_threshold(user),
                           forgotten_mode=True)


@app.route('/study')
@login_required
def study():
    """单个单词背诵：翻卡，逐个展示今日词。

    支持"继续背 N 个"：通过 continue_count 参数在本次追加新词。
    """
    user = current_user()
    # 继续背的数量：优先 query 参数，其次 session 中的继续背标记
    continue_count = request.args.get('continue_count', type=int)
    if continue_count:
        # 继续背：追加 N 个新词到今日计划，再展示今日计划剩余词
        add_continue_words(user, continue_count)
        today_words, _, _ = get_today_words(user)
    else:
        today_words, _, _ = get_today_words(user)

    word_list = [{
        'id': w.id, 'english': w.english,
        'chinese': w.chinese, 'phonetic': w.phonetic or '',
        'audio': audio_filename(w.english),
    } for w in today_words]
    goal = get_user_daily_goal(user)
    return render_template('study.html', words=word_list, user=user,
                           goal=goal,
                           today_learned=get_today_learned_count(user),
                           continue_mode=bool(continue_count),
                           default_accent=user.default_accent or 'us',
                           group_name=None, group_id=None,
                           familiar_threshold=get_user_familiar_threshold(user))


@app.route('/checkpoint')
@login_required
def checkpoint():
    """打卡界面：显示本月月历（已打卡日盖章）、连续打卡天数、今日完成统计。

    支持 ?group_id=<gid> 来源：用户从分组背诵完成后跳转过来打卡。
    支持 ?month=YYYY-MM 浏览其他月份的月历。
    """
    user = current_user()
    now = datetime.now()
    today = now.date()
    today_learned = get_today_learned_count(user)
    # 今日已背句子数：is_known_today=1 且 last_reviewed_at 是今天
    today_sentences = UserSentence.query.filter_by(
        user_id=user.id, is_known_today=1
    ).filter(
        db.func.date(UserSentence.last_reviewed_at) == today
    ).count()

    # 月历显示的年月：默认本月，支持 ?month=YYYY-MM 浏览其他月份
    month_arg = request.args.get('month', '').strip()
    view_year, view_month = today.year, today.month
    if month_arg:
        try:
            y, m = month_arg.split('-')
            view_year, view_month = int(y), int(m)
            if not (1 <= view_month <= 12):
                raise ValueError
        except (ValueError, AttributeError):
            view_year, view_month = today.year, today.month

    month_start = date(view_year, view_month, 1)
    if view_month == 12:
        next_month_first = date(view_year + 1, 1, 1)
    else:
        next_month_first = date(view_year, view_month + 1, 1)

    # 本月所有打卡日（同一天可重复，按日去重）
    checkins_this_month = Checkin.query.filter(
        Checkin.user_id == user.id,
        Checkin.checkin_date >= month_start,
        Checkin.checkin_date < next_month_first,
    ).all()
    stamped_days = sorted({c.checkin_date.day for c in checkins_this_month})
    today_checked_in = any(c.checkin_date == today for c in Checkin.query.filter_by(
        user_id=user.id, checkin_date=today
    ).all())
    latest_checkin = Checkin.query.filter_by(
        user_id=user.id, checkin_date=today
    ).order_by(Checkin.created_at.desc()).first()

    # 计算连续打卡天数：从今天往回数连续有打卡的天数（如今天还没打，从昨天起算）
    streak = 0
    cursor = today
    first_iter = True
    while True:
        existed = Checkin.query.filter_by(user_id=user.id, checkin_date=cursor).first()
        if existed:
            streak += 1
            cursor -= timedelta(days=1)
            first_iter = False
        else:
            if first_iter:
                cursor -= timedelta(days=1)
                first_iter = False
                continue
            break

    prev_month = month_start - timedelta(days=1)
    next_month = next_month_first

    group_id = request.args.get('group_id', type=int)
    group_name = None
    if group_id:
        g = UserGroup.query.filter_by(id=group_id, user_id=user.id).first()
        if g:
            group_name = g.name

    return render_template('checkpoint.html', user=user,
                           month=view_month, day=today.day,
                           year=view_year,
                           today_learned=today_learned,
                           today_sentences=today_sentences,
                           goal=get_user_daily_goal(user),
                           stamped_days=stamped_days,
                           today_checked_in=today_checked_in,
                           latest_checkin=latest_checkin,
                           streak=streak,
                           group_id=group_id,
                           group_name=group_name,
                           month_start=month_start,
                           prev_month=prev_month,
                           next_month=next_month,
                           today_date_iso=today.isoformat())


@app.route('/api/checkin', methods=['POST'])
@login_required
def api_checkin():
    """记录一次打卡。同一日可重复打卡（继续背后再次打卡）。

    参数（form）：
      - source: daily / group（默认 daily）
      - group_id: 若 source=group 时传入
    """
    user = current_user()
    today = date.today()
    source = (request.form.get('source') or 'daily').strip()
    group_id = request.form.get('group_id', type=int)

    # 鉴权：来源 group 时必须提供有效的 group_id
    if source == 'group':
        if not group_id:
            return jsonify(success=False, message='分组打卡必须提供 group_id'), 400
        g = UserGroup.query.filter_by(id=group_id, user_id=user.id).first()
        if not g:
            return jsonify(success=False, message='分组不存在'), 404

    today_learned = get_today_learned_count(user)
    today_sentences = UserSentence.query.filter_by(
        user_id=user.id, is_known_today=1
    ).filter(
        db.func.date(UserSentence.last_reviewed_at) == today
    ).count()

    c = Checkin(
        user_id=user.id, checkin_date=today, source=source,
        group_id=group_id if source == 'group' else None,
        words_count=today_learned, sentences_count=today_sentences,
    )
    db.session.add(c)
    db.session.commit()
    return jsonify(success=True, checkin_id=c.id,
                   words_count=today_learned, sentences_count=today_sentences)


@app.route('/api/word/<int:word_id>/mark', methods=['POST'])
@login_required
def mark_word(word_id):
    """标记单词熟记/遗忘。

    known: consecutive_correct +1，达 3 标记 familiar，next_review_at = 今天+30天
    forgotten: consecutive_correct 清零，status 保持/回退 learning
    """
    user = current_user()
    word = Word.query.get_or_404(word_id)
    result = (request.form.get('result') or '').strip()
    if result not in ('known', 'forgotten'):
        return jsonify(success=False, message='result 参数非法'), 400

    p = UserWordProgress.query.filter_by(user_id=user.id, word_id=word.id).first()
    now = datetime.now()
    if not p:
        p = UserWordProgress(user_id=user.id, word_id=word.id, status='learning')
        db.session.add(p)

    # 熟悉词到期后的这一次是最终复习：答对进入“已会”，答错则重新开始熟悉周期。
    # 若今天已标记为 known（is_known_today==1 且 last_reviewed_at 是今天）则不再重复加 1/3
    today_date = date.today()
    was_known_today = (p.is_known_today == 1 and p.last_reviewed_at is not None
                       and p.last_reviewed_at.date() == today_date)
    is_familiar_review = (p.status == 'familiar' and p.next_review_at is not None
                          and p.next_review_at <= now)

    p.last_reviewed_at = now
    p.is_known_today = 1 if result == 'known' else 0

    if result == 'known':
        # 今天已经点过 ✓ 就不再重复加 1/3
        if not was_known_today:
            p.consecutive_correct = (p.consecutive_correct or 0) + 1
        threshold = get_user_familiar_threshold(user)
        if is_familiar_review:
            p.status = 'mastered'
            p.next_review_at = None
            mastered = UserMasteredWord.query.filter_by(
                user_id=user.id, word_id=word.id).first()
            if not mastered:
                db.session.add(UserMasteredWord(user_id=user.id, word_id=word.id))
        elif p.consecutive_correct >= threshold:
            p.status = 'familiar'
            p.next_review_at = now + timedelta(days=app.config['FAMILIAR_REVIEW_DAYS'])
        else:
            p.status = 'learning'
    else:
        # 熟悉词复习日答错：清零并安排 30 天后重新进入熟悉复习。
        p.consecutive_correct = 0
        p.status = 'learning'
        p.next_review_at = (now + timedelta(days=app.config['FAMILIAR_REVIEW_DAYS'])
                            if is_familiar_review else None)

    db.session.commit()
    return jsonify(
        success=True,
        status=p.status,
        consecutive=p.consecutive_correct,
        next_review_at=p.next_review_at.strftime('%Y-%m-%d') if p.next_review_at else None,
        familiar_threshold=get_user_familiar_threshold(user),
        mastered=is_familiar_review and result == 'known',
    )


# ---------------------------------------------------------------------------
# 词汇本与自选词汇本管理
# ---------------------------------------------------------------------------
@app.route('/vocab/custom')
@login_required
def vocab_custom():
    """自选词汇本管理：搜索框 + 已添加列表 + 手动添加。"""
    user = current_user()
    items = UserCustomWord.query.filter_by(user_id=user.id).order_by(UserCustomWord.added_at.desc()).all()
    words = [c.word for c in items if c.word]
    words = apply_word_overrides(user, words)
    rows = [{'id': word.id, 'english': word.english, 'chinese': word.chinese,
             'phonetic': word.phonetic or '', 'tag': word.tag or ''} for word in words]
    return render_template('vocab_custom.html', rows=rows, user=user)


@app.route('/vocab/search')
@login_required
def vocab_search():
    """词库搜索：返回 JSON，供自选词汇本搜索框调用。"""
    q = (request.args.get('q') or '').strip()
    if not q:
        return jsonify(success=True, results=[])
    normalized_q = q.lower()
    like = f'%{q}%'
    word_rank = case(
        (db.func.lower(Word.english) == normalized_q, 0),
        (db.func.lower(Word.english).like(f'{normalized_q} %'), 1),
        (db.func.lower(Word.english).like(normalized_q + '%'), 2),
        else_=3,
    )
    words = Word.query.filter(Word.english.like(like)).order_by(
        word_rank, Word.english.asc(), Word.id.asc()
    ).limit(100).all()

    # ECDICT 与额外词库可能包含同名记录，搜索结果只保留第一条。
    unique_words = []
    seen_words = set()
    for word in words:
        normalized_word = word.english.strip().lower()
        if normalized_word in seen_words:
            continue
        seen_words.add(normalized_word)
        unique_words.append(word)
        if len(unique_words) >= 30:
            break

    user = current_user()
    added_ids = set(db.session.query(UserCustomWord.word_id).filter_by(user_id=user.id).all())
    added_ids = {i[0] for i in added_ids}
    display_words = apply_word_overrides(user, unique_words)
    results = [{'id': w.id, 'english': w.english, 'chinese': w.chinese,
                'phonetic': w.phonetic or '', 'tag': w.tag or '',
                'added': w.id in added_ids} for w in display_words]
    return jsonify(success=True, results=results)


@app.route('/vocab/custom/add', methods=['POST'])
@login_required
def vocab_custom_add():
    """添加单词到自选词汇本。可按 word_id 添加，或手动输入新词。"""
    user = current_user()
    word_id = request.form.get('word_id', type=int)
    manual_en = (request.form.get('english') or '').strip()
    manual_cn = (request.form.get('chinese') or '').strip()
    manual_ph = (request.form.get('phonetic') or '').strip()
    conflict = False

    if word_id:
        w = Word.query.get(word_id)
        if not w:
            return jsonify(success=False, message='单词不存在'), 404
    elif manual_en:
        # 手动添加新词到词库（tag 标记 manual）
        exist = Word.query.filter(db.func.lower(Word.english) == manual_en.lower()).first()
        if exist:
            w = exist
            conflict = True
        else:
            w = Word(english=manual_en, chinese=manual_cn or '（待补充释义）',
                     phonetic=manual_ph, tag='manual', frequency=0)
            db.session.add(w)
            db.session.commit()
    else:
        return jsonify(success=False, message='请提供 word_id 或 english'), 400

    custom_item = UserCustomWord.query.filter_by(user_id=user.id, word_id=w.id).first()
    if custom_item:
        return jsonify(success=False, message='该词已存在', duplicate=True), 409
    db.session.add(UserCustomWord(user_id=user.id, word_id=w.id))
    # 手动释义优先，但只写入当前用户的覆盖表，不修改公共词库。
    if manual_cn:
        override = UserWordOverride.query.filter_by(user_id=user.id, word_id=w.id).first()
        if override:
            override.chinese = manual_cn
        else:
            db.session.add(UserWordOverride(user_id=user.id, word_id=w.id, chinese=manual_cn))
    db.session.commit()
    return jsonify(success=True, english=w.english, chinese=manual_cn or w.chinese, word_id=w.id,
                   conflict=conflict)


@app.route('/vocab/custom/remove/<int:word_id>', methods=['POST'])
@login_required
def vocab_custom_remove(word_id):
    """从自选词汇本移除单词（不删除词库本身）。"""
    user = current_user()
    item = UserCustomWord.query.filter_by(user_id=user.id, word_id=word_id).first()
    if item:
        db.session.delete(item)
        db.session.commit()
        return jsonify(success=True)
    return jsonify(success=False, message='未找到该记录'), 404


@app.route('/api/today/exclude/<int:word_id>', methods=['POST'])
@login_required
def exclude_today_word(word_id):
    """永久移出当前用户的今日背诵自动清单。"""
    user = current_user()
    Word.query.get_or_404(word_id)
    item = UserExcludedWord.query.filter_by(user_id=user.id, word_id=word_id).first()
    if not item:
        db.session.add(UserExcludedWord(user_id=user.id, word_id=word_id))
    TodayPlan.query.filter_by(user_id=user.id, word_id=word_id, plan_date=date.today()).delete(
        synchronize_session=False)
    TodayExtra.query.filter_by(user_id=user.id, word_id=word_id, added_date=date.today()).delete(
        synchronize_session=False)
    db.session.commit()
    return jsonify(success=True)


@app.route('/api/today/exclude_words', methods=['POST'])
@login_required
def exclude_today_words():
    """批量永久移出当前用户的今日背诵清单。"""
    user = current_user()
    raw_ids = request.form.get('word_ids', '')
    word_ids = {int(value) for value in raw_ids.split(',') if value.strip().isdigit()}
    if not word_ids:
        return jsonify(success=False, message='未选择单词'), 400
    valid_ids = {word.id for word in Word.query.filter(Word.id.in_(word_ids)).all()}
    existing_ids = {item.word_id for item in UserExcludedWord.query.filter(
        UserExcludedWord.user_id == user.id,
        UserExcludedWord.word_id.in_(valid_ids),
    ).all()}
    for current_word_id in valid_ids - existing_ids:
        db.session.add(UserExcludedWord(user_id=user.id, word_id=current_word_id))
    TodayPlan.query.filter(
        TodayPlan.user_id == user.id,
        TodayPlan.plan_date == date.today(),
        TodayPlan.word_id.in_(valid_ids),
    ).delete(synchronize_session=False)
    TodayExtra.query.filter(
        TodayExtra.user_id == user.id,
        TodayExtra.added_date == date.today(),
        TodayExtra.word_id.in_(valid_ids),
    ).delete(synchronize_session=False)
    db.session.commit()
    return jsonify(success=True, removed=len(valid_ids))


@app.route('/api/word/<int:word_id>/override', methods=['POST'])
@login_required
def override_word_definition(word_id):
    """保存当前用户自己的单词释义覆盖。"""
    user = current_user()
    Word.query.get_or_404(word_id)
    chinese = (request.form.get('chinese') or '').strip()
    if not chinese or len(chinese) > 512:
        return jsonify(success=False, message='释义不能为空且不能超过 512 字'), 400
    item = UserWordOverride.query.filter_by(user_id=user.id, word_id=word_id).first()
    if item:
        item.chinese = chinese
    else:
        db.session.add(UserWordOverride(user_id=user.id, word_id=word_id, chinese=chinese))
    db.session.commit()
    return jsonify(success=True, chinese=chinese)


@app.route('/api/word/<int:word_id>/forget', methods=['POST'])
@login_required
def forget_word(word_id):
    """单词书忘记按钮：将单词进度重置为未掌握。"""
    user = current_user()
    word = Word.query.get_or_404(word_id)
    UserMasteredWord.query.filter_by(user_id=user.id, word_id=word.id).delete(
        synchronize_session=False)
    p = UserWordProgress.query.filter_by(user_id=user.id, word_id=word.id).first()
    now = datetime.now()
    if not p:
        p = UserWordProgress(user_id=user.id, word_id=word.id, status='learning')
        db.session.add(p)
    p.last_reviewed_at = now
    p.is_known_today = 0
    p.consecutive_correct = 0
    p.next_review_at = None
    if p.status == 'familiar':
        p.status = 'learning'
    db.session.commit()
    return jsonify(success=True, status=p.status, consecutive=0)


# ---------------------------------------------------------------------------
# 句子背诵模块
# ---------------------------------------------------------------------------
@app.route('/sentences')
@login_required
def sentences():
    """句子列表页。"""
    user = current_user()
    items = UserSentence.query.filter_by(user_id=user.id).order_by(UserSentence.created_at.desc()).all()
    return render_template('sentences.html', sentences=items, user=user)


@app.route('/sentences/add', methods=['POST'])
@login_required
def sentences_add():
    """添加句子（英汉对照）。中文留空时自动调用 Ollama 翻译。"""
    user = current_user()
    en = (request.form.get('english') or '').strip()
    cn = (request.form.get('chinese') or '').strip()
    direction = request.form.get('direction', 'auto')
    if direction not in ('auto', 'cn2en', 'en2cn'):
        direction = 'auto'
    if not en:
        return jsonify(success=False, message='英文必填'), 400
    if len(en) > 500:
        return jsonify(success=False, message='英文句子不能超过 500 字'), 400
    if len(cn) > 500:
        return jsonify(success=False, message='中文释义不能超过 500 字'), 400
    if not cn:
        ok, cn, msg = ollama_translate(en)
        if not ok:
            return jsonify(success=False, message=msg or '自动翻译失败，请手动填写中文'), 502
    s = UserSentence(user_id=user.id, english=en, chinese=cn, direction=direction)
    db.session.add(s)
    db.session.commit()
    return jsonify(success=True, id=s.id, chinese=cn)


def ollama_translate(text):
    """调用本地 Ollama (qwen2.5:7b) 将英文翻译为中文。

    依次尝试 OLLAMA_BASE_URLS 中的候选地址（Docker 主机名 / 宿主机映射端口）。
    返回 (ok, translation, error_msg)。
    """
    prompt = (
        "你是一个英汉翻译引擎。请把下面的英文句子翻译成自然、简洁的中文，"
        "只输出译文本身，不要输出任何解释、拼音或引号。\n\n"
        f"英文：{text}\n中文："
    )
    payload = {
        'model': app.config['OLLAMA_MODEL'],
        'messages': [{'role': 'user', 'content': prompt}],
        'stream': False,
        'temperature': 0.2,
    }
    last_err = None
    for base in app.config['OLLAMA_BASE_URLS']:
        if not base:
            continue
        url = base.rstrip('/') + '/chat/completions'
        try:
            resp = requests.post(url, json=payload, timeout=app.config['OLLAMA_TIMEOUT'])
            if resp.status_code == 200:
                content = resp.json()['choices'][0]['message']['content'].strip()
                # 去掉模型可能输出的多余引号/前后缀
                content = content.strip('"“”').strip()
                if content:
                    return True, content, None
                last_err = '模型返回为空'
            else:
                last_err = f'HTTP {resp.status_code}'
        except requests.RequestException as e:
            last_err = str(e.__class__.__name__)
    return False, None, last_err


@app.route('/api/translate', methods=['POST'])
@login_required
def api_translate():
    """英文 → 中文 翻译接口（前端"AI 翻译"按钮 / 自动填充用）。"""
    data = request.get_json(silent=True) or request.form
    en = (data.get('english') or '').strip()
    if not en:
        return jsonify(success=False, message='请先输入英文句子'), 400
    ok, cn, err = ollama_translate(en)
    if ok:
        return jsonify(success=True, chinese=cn)
    return jsonify(success=False, message=f'翻译服务不可用（{err}），请手动填写中文'), 502


@app.route('/sentences/remove/<int:sid>', methods=['POST'])
@login_required
def sentences_remove(sid):
    """删除句子。"""
    user = current_user()
    s = UserSentence.query.filter_by(id=sid, user_id=user.id).first()
    if not s:
        return jsonify(success=False, message='未找到'), 404
    db.session.delete(s)
    db.session.commit()
    return jsonify(success=True)


@app.route('/sentences/study')
@login_required
def sentences_study():
    """句子背诵页：根据每条 direction 决定先显示中文还是英文。"""
    user = current_user()
    items = UserSentence.query.filter_by(user_id=user.id).order_by(UserSentence.created_at.asc()).all()
    data = []
    for s in items:
        # direction: en2cn 先英文猜中文 / cn2en 先中文猜英文 / auto 默认先英文
        if s.direction == 'cn2en':
            front, back = s.chinese, s.english
        else:
            front, back = s.english, s.chinese
        data.append({
            'id': s.id, 'front': front, 'back': back,
            'english': s.english, 'chinese': s.chinese,
            'direction': s.direction or 'auto',
            'is_english_front': s.direction != 'cn2en',
            'consecutive': s.consecutive_correct or 0,
            'next_review_at': s.next_review_at.strftime('%Y-%m-%d') if s.next_review_at else None,
        })
    return render_template('sentences_study.html', sentences=data, user=user,
                           group_name=None, group_id=None)


@app.route('/api/sentence/<int:sid>/mark', methods=['POST'])
@login_required
def mark_sentence(sid):
    """标记句子背诵结果（known/forgotten）。"""
    user = current_user()
    s = UserSentence.query.filter_by(id=sid, user_id=user.id).first_or_404()
    result = (request.form.get('result') or '').strip()
    if result not in ('known', 'forgotten'):
        return jsonify(success=False, message='result 非法'), 400
    now = datetime.now()
    s.last_reviewed_at = now
    s.is_known_today = 1 if result == 'known' else 0
    if result == 'known':
        s.consecutive_correct = (s.consecutive_correct or 0) + 1
        threshold = get_user_familiar_threshold(user)
        if s.consecutive_correct >= threshold:
            s.next_review_at = now + timedelta(days=app.config['FAMILIAR_REVIEW_DAYS'])
    else:
        s.consecutive_correct = 0
        s.next_review_at = None
    db.session.commit()
    return jsonify(success=True, consecutive=s.consecutive_correct,
                   next_review_at=s.next_review_at.strftime('%Y-%m-%d') if s.next_review_at else None,
                   familiar_threshold=get_user_familiar_threshold(user))


@app.route('/api/sentence/<int:sid>/direction', methods=['POST'])
@login_required
def sentence_direction(sid):
    """修改单条句子的背诵方向。"""
    user = current_user()
    s = UserSentence.query.filter_by(id=sid, user_id=user.id).first_or_404()
    direction = (request.form.get('direction') or 'auto').strip()
    if direction not in ('auto', 'cn2en', 'en2cn'):
        return jsonify(success=False, message='direction 非法'), 400
    s.direction = direction
    db.session.commit()
    return jsonify(success=True, direction=s.direction)


@app.route('/api/sentence/<int:sid>/forget', methods=['POST'])
@login_required
def sentence_forget(sid):
    """句子列表中"忘记"按钮：重置进度，状态回退为未熟悉。"""
    user = current_user()
    s = UserSentence.query.filter_by(id=sid, user_id=user.id).first_or_404()
    s.consecutive_correct = 0
    s.next_review_at = None
    s.is_known_today = 0
    s.last_reviewed_at = datetime.now()
    db.session.commit()
    return jsonify(success=True, consecutive=s.consecutive_correct)


@app.route('/sentences/study/all', methods=['POST'])
@login_required
def sentences_set_all_direction():
    """批量设置所有句子的背诵方向。"""
    user = current_user()
    direction = (request.form.get('direction') or 'auto').strip()
    if direction not in ('auto', 'cn2en', 'en2cn'):
        return jsonify(success=False, message='direction 非法'), 400
    UserSentence.query.filter_by(user_id=user.id).update({UserSentence.direction: direction})
    db.session.commit()
    return jsonify(success=True)


# ---------------------------------------------------------------------------
# 用户分组模块
# ---------------------------------------------------------------------------
@app.route('/groups')
@login_required
def groups():
    """我的分组列表。"""
    user = current_user()
    groups = UserGroup.query.filter_by(user_id=user.id).order_by(UserGroup.created_at.desc()).all()
    rows = []
    for g in groups:
        items = UserGroupItem.query.filter_by(group_id=g.id).all()
        word_ids = [it.word_id for it in items if it.word_id]
        # 进度统计
        familiar = 0
        learning = 0
        if word_ids:
            fam = UserWordProgress.query.filter(
                UserWordProgress.user_id == user.id,
                UserWordProgress.word_id.in_(word_ids),
                UserWordProgress.status == 'familiar'
            ).count()
            learn = UserWordProgress.query.filter(
                UserWordProgress.user_id == user.id,
                UserWordProgress.word_id.in_(word_ids),
                UserWordProgress.status == 'learning'
            ).count()
            familiar = fam
            learning = learn
        rows.append({
            'id': g.id, 'name': g.name, 'gtype': g.gtype,
            'total': len(items), 'familiar': familiar, 'learning': learning,
            'new': len(items) - familiar - learning,
        })
    return render_template('groups.html', groups=rows, user=user)


@app.route('/groups/create', methods=['POST'])
@login_required
def groups_create():
    """创建分组。"""
    user = current_user()
    name = (request.form.get('name') or '').strip()
    gtype = (request.form.get('gtype') or 'word').strip()
    if gtype not in ('word', 'sentence', 'mixed'):
        gtype = 'word'
    if not name:
        return jsonify(success=False, message='分组名必填'), 400
    exist = UserGroup.query.filter_by(user_id=user.id, name=name).first()
    if exist:
        return jsonify(success=False, message='分组名已存在'), 400
    g = UserGroup(user_id=user.id, name=name, gtype=gtype)
    db.session.add(g)
    db.session.commit()
    return jsonify(success=True, id=g.id)


@app.route('/groups/<int:gid>')
@login_required
def group_detail(gid):
    """分组详情：预览成员、打印、背诵入口。"""
    user = current_user()
    g = UserGroup.query.filter_by(id=gid, user_id=user.id).first_or_404()
    items = UserGroupItem.query.filter_by(group_id=g.id).order_by(UserGroupItem.added_at.asc()).all()
    progress_map = {p.word_id: p for p in UserWordProgress.query.filter_by(user_id=user.id).all()}
    rows = []
    for it in items:
        if it.word:
            p = progress_map.get(it.word.id)
            rows.append({
                'id': it.id, 'word_id': it.word.id, 'english': it.word.english,
                'phonetic': it.word.phonetic or '', 'chinese': it.word.chinese,
                'status': (p.status if p else 'new'),
                'consecutive': (p.consecutive_correct if p else 0),
                'kind': 'word',
            })
        elif it.sentence:
            rows.append({
                'id': it.id, 'word_id': it.sentence.id,
                'english': it.sentence.english, 'phonetic': '',
                'chinese': it.sentence.chinese,
                'status': ('familiar' if it.sentence.next_review_at else
                           ('learning' if it.sentence.consecutive_correct else 'new')),
                'consecutive': it.sentence.consecutive_correct or 0,
                'kind': 'sentence',
            })
    status_map = {'new': '新词', 'learning': '学习中', 'familiar': '熟悉'}
    return render_template('group_detail.html', group=g, rows=rows,
                           status_map=status_map, user=user,
                           familiar_threshold=get_user_familiar_threshold(user))


@app.route('/groups/<int:gid>/delete', methods=['POST'])
@login_required
def groups_delete(gid):
    """删除分组（连同条目）。"""
    user = current_user()
    g = UserGroup.query.filter_by(id=gid, user_id=user.id).first()
    if not g:
        return jsonify(success=False, message='未找到'), 404
    UserGroupItem.query.filter_by(group_id=g.id).delete()
    db.session.delete(g)
    db.session.commit()
    return jsonify(success=True)


@app.route('/groups/<int:gid>/study')
@login_required
def group_study(gid):
    """按分组背诵：单词走单词背诵逻辑，句子走句子背诵逻辑。

    支持 ?checkin_target=1 ：背完即跳转到打卡界面（携带 group_id）。
    """
    user = current_user()
    g = UserGroup.query.filter_by(id=gid, user_id=user.id).first_or_404()
    checkin_target = request.args.get('checkin_target', type=int) == 1
    items = UserGroupItem.query.filter_by(group_id=g.id).all()
    word_items = [it for it in items if it.word_id]
    sent_items = [it for it in items if it.sentence_id]
    # 优先按单词分组背诵
    if word_items:
        word_list = [{
            'id': it.word.id, 'english': it.word.english,
            'chinese': it.word.chinese, 'phonetic': it.word.phonetic or '',
            'audio': audio_filename(it.word.english),
        } for it in word_items]
        return render_template('study.html', words=word_list, user=user,
                               goal=len(word_list),
                               today_learned=get_today_learned_count(user),
                               continue_mode=False,
                               default_accent=user.default_accent or 'us',
                               group_name=g.name,
                               group_id=g.id if checkin_target else None,
                               familiar_threshold=get_user_familiar_threshold(user))
    # 句子分组
    if sent_items:
        data = []
        for it in sent_items:
            s = it.sentence
            if s.direction == 'cn2en':
                front, back = s.chinese, s.english
            else:
                front, back = s.english, s.chinese
            data.append({
                'id': s.id, 'front': front, 'back': back,
                'english': s.english, 'chinese': s.chinese,
                'direction': s.direction or 'auto',
                'is_english_front': s.direction != 'cn2en',
                'consecutive': s.consecutive_correct or 0,
                'next_review_at': s.next_review_at.strftime('%Y-%m-%d') if s.next_review_at else None,
            })
        return render_template('sentences_study.html', sentences=data, user=user,
                               group_name=g.name,
                               group_id=g.id if checkin_target else None)
    # 空分组
    return render_template('group_detail.html', group=g, rows=[],
                           status_map={'new': '新词', 'learning': '学习中', 'familiar': '熟悉'},
                           user=user, empty_msg='分组为空，请先添加单词或句子',
                           familiar_threshold=get_user_familiar_threshold(user))


@app.route('/groups/<int:gid>/remove_item/<int:item_id>', methods=['POST'])
@login_required
def group_remove_item(gid, item_id):
    """从分组移除条目。"""
    user = current_user()
    g = UserGroup.query.filter_by(id=gid, user_id=user.id).first_or_404()
    it = UserGroupItem.query.filter_by(id=item_id, group_id=g.id).first()
    if it:
        db.session.delete(it)
        db.session.commit()
    return jsonify(success=True)


@app.route('/api/group/add_word', methods=['POST'])
@login_required
def group_add_word():
    """把单词加入分组（可一次指定多个 group_id，或新建分组）。"""
    user = current_user()
    word_id = request.form.get('word_id', type=int)
    group_id = request.form.get('group_id', type=int)
    new_group = (request.form.get('new_group') or '').strip()
    if not word_id:
        return jsonify(success=False, message='缺少 word_id'), 400
    w = Word.query.get(word_id)
    if not w:
        return jsonify(success=False, message='单词不存在'), 404

    # 新建分组
    if new_group:
        exist = UserGroup.query.filter_by(user_id=user.id, name=new_group).first()
        if exist:
            group_id = exist.id
        else:
            g = UserGroup(user_id=user.id, name=new_group, gtype='word')
            db.session.add(g)
            db.session.commit()
            group_id = g.id

    if not group_id:
        return jsonify(success=False, message='请选择或新建分组'), 400
    g = UserGroup.query.filter_by(id=group_id, user_id=user.id).first()
    if not g:
        return jsonify(success=False, message='分组不存在'), 404

    exist = UserGroupItem.query.filter_by(group_id=group_id, word_id=word_id).first()
    if not exist:
        db.session.add(UserGroupItem(group_id=group_id, word_id=word_id))
        db.session.commit()
    return jsonify(success=True, group_id=group_id)


@app.route('/api/group/add_sentence', methods=['POST'])
@login_required
def group_add_sentence():
    """把句子加入分组。"""
    user = current_user()
    sid = request.form.get('sentence_id', type=int)
    group_id = request.form.get('group_id', type=int)
    new_group = (request.form.get('new_group') or '').strip()
    if not sid:
        return jsonify(success=False, message='缺少 sentence_id'), 400
    s = UserSentence.query.filter_by(id=sid, user_id=user.id).first()
    if not s:
        return jsonify(success=False, message='句子不存在'), 404

    if new_group:
        exist = UserGroup.query.filter_by(user_id=user.id, name=new_group).first()
        if exist:
            group_id = exist.id
        else:
            g = UserGroup(user_id=user.id, name=new_group, gtype='sentence')
            db.session.add(g)
            db.session.commit()
            group_id = g.id

    if not group_id:
        return jsonify(success=False, message='请选择或新建分组'), 400
    g = UserGroup.query.filter_by(id=group_id, user_id=user.id).first()
    if not g:
        return jsonify(success=False, message='分组不存在'), 404

    exist = UserGroupItem.query.filter_by(group_id=group_id, sentence_id=sid).first()
    if not exist:
        db.session.add(UserGroupItem(group_id=group_id, sentence_id=sid))
        db.session.commit()
    return jsonify(success=True, group_id=group_id)


@app.route('/api/user_groups')
@login_required
def user_groups_api():
    """返回当前用户所有分组（JSON），供前端下拉选择。"""
    user = current_user()
    gs = UserGroup.query.filter_by(user_id=user.id).order_by(UserGroup.name.asc()).all()
    return jsonify(success=True, groups=[{'id': g.id, 'name': g.name, 'gtype': g.gtype} for g in gs])


# ---------------------------------------------------------------------------
# 今日背诵额外单词管理
# ---------------------------------------------------------------------------
@app.route('/api/today/add_words', methods=['POST'])
@login_required
def today_add_words():
    """把单词加入今日背诵（支持批量 word_id 列表）。"""
    user = current_user()
    today = date.today()
    raw_ids = request.form.get('word_ids', '')
    word_ids = [int(x) for x in raw_ids.split(',') if x.strip().isdigit()]
    if not word_ids:
        return jsonify(success=False, message='未选择单词'), 400
    added = 0
    for wid in word_ids:
        w = Word.query.get(wid)
        if not w:
            continue
        exist = TodayExtra.query.filter_by(user_id=user.id, word_id=wid, added_date=today).first()
        if not exist:
            db.session.add(TodayExtra(user_id=user.id, word_id=wid, added_date=today))
        # 同步到 TodayPlan
        plan_exist = TodayPlan.query.filter_by(user_id=user.id, word_id=wid, plan_date=today).first()
        if not plan_exist:
            db.session.add(TodayPlan(user_id=user.id, word_id=wid,
                                     plan_date=today, role='extra'))
            added += 1
        UserExcludedWord.query.filter_by(user_id=user.id, word_id=wid).delete(
            synchronize_session=False)
    db.session.commit()
    return jsonify(success=True, added=added)


@app.route('/api/today/add_group/<int:gid>', methods=['POST'])
@login_required
def today_add_group(gid):
    """把某个分组的全部单词加入今日背诵。"""
    user = current_user()
    today = date.today()
    g = UserGroup.query.filter_by(id=gid, user_id=user.id).first_or_404()
    items = UserGroupItem.query.filter_by(group_id=g.id).all()
    added = 0
    for it in items:
        if it.word_id:
            exist = TodayExtra.query.filter_by(user_id=user.id, word_id=it.word_id, added_date=today).first()
            if not exist:
                db.session.add(TodayExtra(user_id=user.id, word_id=it.word_id, added_date=today))
            # 同步到 TodayPlan
            plan_exist = TodayPlan.query.filter_by(user_id=user.id, word_id=it.word_id, plan_date=today).first()
            if not plan_exist:
                db.session.add(TodayPlan(user_id=user.id, word_id=it.word_id,
                                         plan_date=today, role='extra'))
            UserExcludedWord.query.filter_by(user_id=user.id, word_id=it.word_id).delete(
                synchronize_session=False)
            added += 1
    db.session.commit()
    return jsonify(success=True, added=added)


# ---------------------------------------------------------------------------
# 命令：初始化数据库
# ---------------------------------------------------------------------------
# 按需 TTS 生成：本地无音频时实时生成并缓存
import os
import re
import asyncio

TTS_US_VOICE = 'en-US-AriaNeural'
TTS_UK_VOICE = 'en-GB-LibbyNeural'


def tts_safe_filename(english):
    return re.sub(r'[^a-zA-Z0-9]', '_', english).lower()


@app.route('/api/tts/<accent>/<int:word_id>')
@login_required
def tts_on_demand(word_id, accent):
    """按需生成单词发音：本地有就直接发，没有就用 edge-tts 实时生成并缓存。"""
    if accent not in ('us', 'uk'):
        return jsonify(success=False, message='accent 非法'), 400
    word = Word.query.get_or_404(word_id)
    name = tts_safe_filename(word.english)
    audio_dir = os.path.join(app.static_folder, 'audio', accent)
    os.makedirs(audio_dir, exist_ok=True)
    file_path = os.path.join(audio_dir, f'{name}.mp3')

    if not os.path.exists(file_path):
        # 实时用 edge-tts 生成
        voice = TTS_US_VOICE if accent == 'us' else TTS_UK_VOICE
        try:
            import edge_tts
            asyncio.run(_gen_one(word.english, voice, file_path))
        except Exception as e:
            app.logger.warning('TTS 生成失败 %s %s: %s', accent, word.english, e)
            return jsonify(success=False, message='音频生成失败'), 500

    from flask import send_from_directory
    return send_from_directory(audio_dir, f'{name}.mp3', mimetype='audio/mpeg')


async def _gen_one(text, voice, out_path):
    import edge_tts
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(out_path)


@app.cli.command('init-db')
def init_db():
    """创建所有表。使用：flask init-db"""
    db.create_all()
    print('数据库表已创建。')


# ---------------------------------------------------------------------------
# 启动
# ---------------------------------------------------------------------------
with app.app_context():
    db.create_all()  # 首次运行自动建表

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
