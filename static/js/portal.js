/*
 * Comportamento comum das telas do portal: tema, sincronização do Drive e player de vídeo.
 * As URLs vêm do template (base.html) em window.CARMEL, para não repetir caminhos aqui.
 */
(function () {
    const CFG = window.CARMEL;
    const CSRF_TOKEN = document.querySelector('meta[name="csrf-token"]').content;

    function postForm(url, data = {}) {
        return fetch(url, {
            method: 'POST', credentials: 'same-origin',
            headers: { 'X-CSRFToken': CSRF_TOKEN },
            body: new URLSearchParams(data),
        });
    }

    function renderIcons() { if (window.lucide) lucide.createIcons(); }

    function setThemeIcon(dark) {
        document.querySelectorAll('[data-lucide="moon"],[data-lucide="sun"]')
            .forEach(el => el.setAttribute('data-lucide', dark ? 'sun' : 'moon'));
    }

    // ---- Tema ----
    window.toggleDarkMode = function () {
        const dark = document.documentElement.classList.toggle('dark');
        document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
        localStorage.setItem('carmel_theme', dark ? 'dark' : 'light');
        localStorage.setItem('theme', dark ? 'dark' : 'light'); // mesmo tema no Django Admin
        setThemeIcon(dark);
        renderIcons();
    };

    // ---- Sincronização do Drive ----
    window.syncDriveNow = function () {
        const btn = document.getElementById('btn-sync-drive');
        const label = btn.querySelector('span');
        btn.disabled = true;
        label.textContent = 'Varrendo...';
        postForm(CFG.syncUrl)
            .then(r => r.json().catch(() => {
                throw new Error('o servidor não respondeu como esperado (código ' + r.status + ').');
            }))
            .then(d => {
                alert(d.message);
                if (d.published) window.location.href = CFG.homeUrl;
                else if (d.found) window.location.href = CFG.queueUrl;
            })
            .catch(err => alert('Não foi possível sincronizar: ' + err.message + ' Tente novamente em instantes.'))
            .finally(() => { btn.disabled = false; label.textContent = 'Sincronizar Drive'; });
    };

    // ---- Player ----
    const modal = document.getElementById('video-modal');
    const player = document.getElementById('vm-video');
    let currentVideoId = null;

    const viewUrl = id => CFG.viewUrl.replace('/0/', '/' + id + '/');

    function openVideo(el) {
        const d = el.dataset;
        currentVideoId = d.videoId;
        player.src = d.videoUrl;
        document.getElementById('vm-download').href = d.videoUrl;
        document.getElementById('vm-title').textContent = d.title;
        document.getElementById('vm-dept').textContent = d.dept;
        document.getElementById('vm-script').textContent = d.script || 'Roteiro não disponível.';
        document.getElementById('vm-done').hidden = d.watched !== '1';
        modal.classList.add('open');
        player.play().catch(() => {});
        postForm(viewUrl(currentVideoId));
    }

    window.closeVideoModal = function () {
        player.pause();
        player.removeAttribute('src');
        player.load();
        modal.classList.remove('open');
        currentVideoId = null;
    };

    player.addEventListener('ended', () => {
        if (!currentVideoId) return;
        const id = currentVideoId;
        postForm(viewUrl(id), { completed: '1' }).then(() => {
            document.getElementById('vm-done').hidden = false;
            document.querySelectorAll('[data-video-id="' + id + '"]').forEach(el => {
                el.dataset.watched = '1';
                const badge = el.querySelector('.thumb-done');
                if (badge) badge.hidden = false;
            });
        });
    });

    document.addEventListener('click', e => {
        const target = e.target.closest('[data-play-video]');
        if (target) openVideo(target);
        if (e.target === modal) window.closeVideoModal();
    });
    document.addEventListener('keydown', e => { if (e.key === 'Escape') window.closeVideoModal(); });

    setThemeIcon(document.documentElement.classList.contains('dark'));
    renderIcons();
})();
