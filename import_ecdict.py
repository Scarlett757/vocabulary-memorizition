# -*- coding: utf-8 -*-
"""导入 ECDICT 全量词库到数据库。

读取 ecdict.csv，将单词、音标、中文释义、tag、词频写入 Word 表。
运行：python import_ecdict.py
"""
import csv
import sys
import time
from datetime import datetime

import pandas as pd

from app import app, db
from models import Word, User


# 词汇本层级 -> ECDICT tag 关键字映射
LEVEL_TAG_MAP = {
    'primary': None,   # 小学：用词频+长度筛选，无直接 tag
    'middle': 'zk',    # 初中：中考
    'senior': 'gk',    # 高中：高考
    'cet4': 'cet4',    # 四级
    'cet6': 'cet6',    # 六级
    'ielts': 'ielts',  # 雅思
    'toefl': 'toefl',
    'gre': 'gre',
    'ky': 'ky',        # 考研
}


def safe_str(val):
    if val is None:
        return ''
    if isinstance(val, float):
        if pd.isna(val):
            return ''
        return str(int(val)) if float(val).is_integer() else str(val)
    s = str(val).strip()
    return '' if s.lower() == 'nan' else s


def main():
    csv_path = 'ecdict.csv'
    print(f'[开始] 读取 {csv_path} ...')
    df = pd.read_csv(csv_path, low_memory=False)
    print(f'[读取] 共 {len(df)} 行')

    # 清空旧词库（保留 id 自增）。先关闭外键检查，避免 progress 引用阻止删除。
    with app.app_context():
        db.session.execute(db.text('SET FOREIGN_KEY_CHECKS=0'))
        db.session.execute(db.text('DELETE FROM user_word_progress'))
        db.session.execute(db.text('DELETE FROM user_custom_words'))
        db.session.execute(db.text('DELETE FROM words'))
        db.session.execute(db.text('SET FOREIGN_KEY_CHECKS=1'))
        db.session.commit()
        print('[清空] 旧 Word / progress / custom 表已清空')

        total = 0
        batch = []
        batch_size = 2000
        start = time.time()

        for idx, row in df.iterrows():
            word = safe_str(row.get('word'))
            if not word:
                continue
            phonetic = safe_str(row.get('phonetic'))
            translation = safe_str(row.get('translation'))
            # 中文释义优先 translation，为空则用 definition
            if not translation:
                translation = safe_str(row.get('definition'))
            if not translation:
                continue
            tag = safe_str(row.get('tag'))
            bnc = row.get('bnc')
            frq = row.get('frq')
            freq = 0
            if bnc is not None and not pd.isna(bnc):
                try:
                    freq = int(bnc)
                except (TypeError, ValueError):
                    freq = 0
            elif frq is not None and not pd.isna(frq):
                try:
                    freq = int(frq)
                except (TypeError, ValueError):
                    freq = 0

            batch.append(Word(
                english=word,
                chinese=translation[:500],
                phonetic=phonetic,
                tag=tag,
                frequency=freq,
            ))

            if len(batch) >= batch_size:
                db.session.bulk_save_objects(batch)
                db.session.commit()
                total += len(batch)
                batch = []
                elapsed = time.time() - start
                rate = total / elapsed if elapsed > 0 else 0
                print(f'[进度] 已导入 {total} / {len(df)} ({rate:.0f} 条/秒)', flush=True)

        if batch:
            db.session.bulk_save_objects(batch)
            db.session.commit()
            total += len(batch)

        elapsed = time.time() - start
        print(f'[完成] 共导入 {total} 个单词，耗时 {elapsed:.1f} 秒')
        print(f'[校验] Word 表当前总数: {Word.query.count()}')

        # 给小学词汇打上 primary 标记：取 bnc 词频最高、单词长度<=7 的常用词
        primary = Word.query.filter(
            Word.frequency > 0,
            db.func.length(Word.english) <= 7
        ).order_by(Word.frequency.desc()).limit(800).all()
        for w in primary:
            w.tag = (w.tag + ' primary').strip() if w.tag else 'primary'
        db.session.commit()
        print(f'[小学] 标记 {len(primary)} 个常用词为 primary 级别')


if __name__ == '__main__':
    main()
