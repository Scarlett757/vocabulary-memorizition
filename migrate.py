# -*- coding: utf-8 -*-
"""数据库迁移：为现有表新增字段并创建新表。运行一次即可。"""
from app import app, db


def main():
    with app.app_context():
        stmts = [
            ('ALTER TABLE words ADD COLUMN tag VARCHAR(128)', 'words.tag'),
            ('ALTER TABLE words ADD COLUMN frequency INT DEFAULT 0', 'words.frequency'),
            ('ALTER TABLE words MODIFY COLUMN chinese VARCHAR(512)', 'words.chinese widen'),
            ('ALTER TABLE users ADD COLUMN vocab_level VARCHAR(16) DEFAULT "cet4"', 'users.vocab_level'),
        ]
        for sql, name in stmts:
            try:
                db.session.execute(db.text(sql))
                db.session.commit()
                print(f'[OK] {name}')
            except Exception as e:
                db.session.rollback()
                print(f'[skip] {name}: {str(e)[:90]}')

        # 创建新表（已存在则跳过）
        db.create_all()
        print('[OK] create_all 完成')

        # 索引
        for sql, name in [
            ('CREATE INDEX ix_words_english ON words(english)', 'idx english'),
            ('CREATE INDEX ix_words_tag ON words(tag)', 'idx tag'),
        ]:
            try:
                db.session.execute(db.text(sql))
                db.session.commit()
                print(f'[OK] {name}')
            except Exception as e:
                db.session.rollback()
                print(f'[skip] {name}: {str(e)[:50]}')

        from models import Word, User
        print(f'[校验] Words={Word.query.count()}')
        print('[完成] 迁移结束')


if __name__ == '__main__':
    main()
