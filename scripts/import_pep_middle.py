# -*- coding: utf-8 -*-
"""把 pep-words 的人教版初中词汇导入到 Word 表，替换现有 'zk' tag 词汇。

保留初一/初二/初三细分（zk7/zk8/zk9）的词汇不动，只替换 tag='zk' 的"全部初中"词库。
"""
import json
import os
import sys

# 把项目根目录加入 sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app, db
from models import Word, UserWordProgress, UserCustomWord, TodayExtra, TodayPlan, UserGroupItem


def main():
    json_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'pep_middle_school.json')
    json_path = os.path.abspath(json_path)
    if not os.path.exists(json_path):
        print(f'[ERR] 未找到 {json_path}')
        sys.exit(1)

    with open(json_path, 'r', encoding='utf-8') as f:
        pep_words = json.load(f)
    print(f'PEP 初中词汇条目数: {len(pep_words)}')

    with app.app_context():
        # 找到要删除的 zk 词 id 列表
        zk_words = Word.query.filter_by(tag='zk').all()
        zk_ids = [w.id for w in zk_words]
        print(f'现有 zk 词汇: {len(zk_ids)} 条')

        if zk_ids:
            # 先清理所有引用这些词的外键记录
            # 1. UserWordProgress
            p_deleted = UserWordProgress.query.filter(UserWordProgress.word_id.in_(zk_ids)).delete(synchronize_session=False)
            print(f'  删除 UserWordProgress: {p_deleted} 条')
            # 2. UserCustomWord
            c_deleted = UserCustomWord.query.filter(UserCustomWord.word_id.in_(zk_ids)).delete(synchronize_session=False)
            print(f'  删除 UserCustomWord: {c_deleted} 条')
            # 3. TodayExtra
            te_deleted = TodayExtra.query.filter(TodayExtra.word_id.in_(zk_ids)).delete(synchronize_session=False)
            print(f'  删除 TodayExtra: {te_deleted} 条')
            # 4. TodayPlan
            tp_deleted = TodayPlan.query.filter(TodayPlan.word_id.in_(zk_ids)).delete(synchronize_session=False)
            print(f'  删除 TodayPlan: {tp_deleted} 条')
            # 5. UserGroupItem
            ug_deleted = UserGroupItem.query.filter(UserGroupItem.word_id.in_(zk_ids)).delete(synchronize_session=False)
            print(f'  删除 UserGroupItem: {ug_deleted} 条')
            # 现在可以删除 zk 词汇
            deleted = Word.query.filter_by(tag='zk').delete(synchronize_session=False)
            print(f'删除现有 zk 词汇: {deleted} 条')
            db.session.commit()

        inserted = 0
        skipped = 0
        for item in pep_words:
            english = (item.get('word') or '').strip()
            if not english:
                skipped += 1
                continue
            phonetic = (item.get('phonetic') or '').strip()
            meaning = (item.get('meaning') or '').strip()
            pos = (item.get('pos') or '').strip()
            # 把词性合并进中文释义：pos + meaning
            chinese = f'{pos} {meaning}'.strip() if pos else meaning

            # 避免与现有词库重复（按英文词条不区分大小写去重）
            existing = Word.query.filter(db.func.lower(Word.english) == english.lower()).first()
            if existing:
                skipped += 1
                continue

            w = Word(
                english=english,
                chinese=chinese,
                phonetic=phonetic,
                tag='zk',
                frequency=0,
            )
            db.session.add(w)
            inserted += 1

        db.session.commit()
        print(f'导入完成: 新增 {inserted} 条, 跳过 {skipped} 条')
        total_zk = Word.query.filter_by(tag='zk').count()
        print(f'当前 zk 词汇总数: {total_zk}')


if __name__ == '__main__':
    main()
