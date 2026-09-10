# -*- coding: utf-8 -*-
import pandas as pd

df = pd.read_csv('ecdict.csv', low_memory=False)
tags = ['zk', 'gk', 'cet4', 'cet6', 'ky', 'ielts', 'toefl', 'gre']
for t in tags:
    count = df[df['tag'].str.contains(t, na=False)].shape[0]
    print(f'{t}: {count}')
total_tagged = df[df['tag'].notna() & (df['tag'] != '')].shape[0]
print(f'tagged total: {total_tagged}')
