# -*- coding: utf-8 -*-
"""临时脚本：创建 MySQL 数据库并建表、导入词库。完成后可删除。"""
import pymysql
from config import Config
from app import app, db
from models import Word
from seed import SAMPLE_WORDS


def create_database():
    cfg = Config
    conn = pymysql.connect(
        host=cfg.MYSQL_HOST,
        user=cfg.MYSQL_USER,
        password=cfg.MYSQL_PASSWORD,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                'CREATE DATABASE IF NOT EXISTS '
                f'{cfg.MYSQL_DATABASE} '
                'DEFAULT CHARACTER SET utf8mb4 '
                'COLLATE utf8mb4_unicode_ci'
            )
        conn.commit()
        with conn.cursor() as cur:
            cur.execute(f"SHOW DATABASES LIKE '{cfg.MYSQL_DATABASE}'")
            row = cur.fetchone()
            print('数据库已就绪:', row)
    finally:
        conn.close()


def create_tables():
    with app.app_context():
        db.create_all()
        # 若 users 表已存在但缺 daily_goal 列，则补列（兼容旧表）
        from sqlalchemy import text
        try:
            db.session.execute(text("SELECT daily_goal FROM users LIMIT 1"))
        except Exception:
            try:
                db.session.execute(text("ALTER TABLE users ADD COLUMN daily_goal INT DEFAULT 30"))
                db.session.commit()
                print('已为 users 表补列 daily_goal。')
            except Exception as e:
                print('补列失败(可能已存在):', e)
        print('所有表已创建。')


def seed_words():
    with app.app_context():
        added = 0
        for english, phonetic, chinese in SAMPLE_WORDS:
            if Word.query.filter_by(english=english).first():
                continue
            db.session.add(Word(english=english, chinese=chinese, phonetic=phonetic))
            added += 1
        db.session.commit()
        total = Word.query.count()
        print(f'本次新增 {added} 个单词，词库总计 {total} 个。')


def show_tables():
    """查看已建表与词库数据。"""
    with app.app_context():
        from sqlalchemy import text
        rows = db.session.execute(text("SHOW TABLES")).fetchall()
        print('数据库中的表:', [r[0] for r in rows])
        print('词库数量:', Word.query.count())
        first = Word.query.first()
        if first:
            print('首条词:', first.id, first.english, first.chinese)


if __name__ == '__main__':
    print('== 1. 创建数据库 ==')
    create_database()
    print('== 2. 建表 ==')
    create_tables()
    print('== 3. 导入词库 ==')
    seed_words()
    print('== 4. 校验 ==')
    show_tables()
    print('完成。')
