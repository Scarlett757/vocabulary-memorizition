# -*- coding: utf-8 -*-
"""批量生成单词发音音频（US + UK）。

使用 edge-tts（微软神经网络音色），一次性预生成所有单词音频。
已存在的音频自动跳过，可重复执行。

US 音色：en-US-AriaNeural（女声，自然）
UK 音色：en-GB-LibbyNeural（女声，英式）

使用：python gen_audio.py
"""
import asyncio
import os
import re

import edge_tts

from app import app, db
from models import Word

# 音频存放目录
AUDIO_DIR = os.path.join(app.static_folder, 'audio')
US_DIR = os.path.join(AUDIO_DIR, 'us')
UK_DIR = os.path.join(AUDIO_DIR, 'uk')

# 微软 Edge TTS 神经网络音色
US_VOICE = 'en-US-AriaNeural'
UK_VOICE = 'en-GB-LibbyNeural'


def safe_filename(english):
    """把英文单词转为安全文件名（只保留字母数字，小写）。"""
    return re.sub(r'[^a-zA-Z0-9]', '_', english).lower()


async def generate_one(text, voice, out_path):
    """生成单个单词的音频。"""
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(out_path)


async def generate_for_word(english):
    """为一个单词生成 US + UK 两份音频。"""
    name = safe_filename(english)
    us_path = os.path.join(US_DIR, f'{name}.mp3')
    uk_path = os.path.join(UK_DIR, f'{name}.mp3')
    tasks = []
    if not os.path.exists(us_path):
        tasks.append(generate_one(english, US_VOICE, us_path))
    if not os.path.exists(uk_path):
        tasks.append(generate_one(english, UK_VOICE, uk_path))
    if tasks:
        await asyncio.gather(*tasks)
    return len(tasks)


async def main():
    # 建目录
    os.makedirs(US_DIR, exist_ok=True)
    os.makedirs(UK_DIR, exist_ok=True)

    with app.app_context():
        words = Word.query.order_by(Word.id.asc()).all()
        total = len(words)
        generated = 0
        failed = []
        print(f'共 {total} 个单词，开始生成音频...')
        for i, w in enumerate(words, 1):
            try:
                n = await generate_for_word(w.english)
                generated += n
                if i % 20 == 0 or i == total:
                    print(f'  进度: {i}/{total}')
            except Exception as e:
                failed.append((w.english, str(e)))
                print(f'  失败: {w.english} -> {e}')

        # 统计结果写入文件
        us_count = len(os.listdir(US_DIR)) if os.path.isdir(US_DIR) else 0
        uk_count = len(os.listdir(UK_DIR)) if os.path.isdir(UK_DIR) else 0
        result = (
            f'本次新生成 {generated} 个音频文件\n'
            f'US 音频目录: {us_count} 个文件\n'
            f'UK 音频目录: {uk_count} 个文件\n'
            f'失败: {len(failed)} 个'
        )
        print(result)
        with open('audio_result.txt', 'w', encoding='utf-8') as f:
            f.write(result)
            if failed:
                f.write('\n失败列表:\n')
                for eng, err in failed:
                    f.write(f'  {eng}: {err}\n')


if __name__ == '__main__':
    asyncio.run(main())
