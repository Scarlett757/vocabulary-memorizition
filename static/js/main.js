// 主 JS：通用熟记/忘记按钮交互
// 仅处理独立的 .mark-btn（不在 #todayList / #flipCard 内的），避免与各页面内联脚本冲突导致重复请求
document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.mark-btn').forEach(btn => {
        // 跳过 today.html 和 study.html 的按钮（它们有自己的内联脚本处理）
        if (btn.closest('#todayList')) return;
        if (btn.closest('#flipCard')) return;
        // 跳过没有 .today-row 父级的按钮（如 study.html 的卡片按钮）
        if (!btn.closest('.today-row')) return;
        // 避免重复绑定
        if (btn.dataset.mainBound === '1') return;
        btn.dataset.mainBound = '1';

        btn.addEventListener('click', () => {
            const row = btn.closest('.today-row');
            if (!row) return;
            const wordId = btn.dataset.wordId;
            const result = btn.dataset.result;
            if (!wordId || !result) return;
            const fd = new FormData();
            fd.append('result', result);
            fetch(`/api/word/${wordId}/mark`, { method: 'POST', body: fd })
                .then(r => r.json())
                .then(res => {
                    if (res.success) {
                        const statusEl = row.querySelector('.status-text');
                        if (statusEl) {
                            const map = { new: '新词', learning: '学习中', familiar: '熟悉' };
                            statusEl.textContent = map[res.status] || res.status;
                            statusEl.className = `status-text status-${res.status}`;
                        }
                        row.querySelectorAll('.mark-btn').forEach(b => b.classList.remove('active'));
                        btn.classList.add('active');
                        if (res.status === 'familiar') {
                            showToast(`✓ 已熟悉，${res.next_review_at || '30 天后'} 重新出现`, 'ok');
                        }
                    } else {
                        showToast(res.message || '标记失败', 'error');
                    }
                })
                .catch(() => { /* 网络错误静默：不弹窗 */ });
        });
    });
});
