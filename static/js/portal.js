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

    // ---- Notificações (toast) no lugar do alert() ----
    function toast(message, type) {
        let stack = document.querySelector('.toast-stack');
        if (!stack) {
            stack = document.createElement('div');
            stack.className = 'toast-stack';
            stack.setAttribute('role', 'status');
            document.body.appendChild(stack);
        }
        const el = document.createElement('div');
        el.className = 'toast ' + (type || '');
        const icon = document.createElement('i');
        icon.setAttribute('data-lucide', type === 'err' ? 'alert-circle' : type === 'ok' ? 'check-circle-2' : 'info');
        icon.className = 'icon';
        const text = document.createElement('span');
        text.textContent = message;
        el.append(icon, text);
        stack.appendChild(el);
        renderIcons();
        const close = () => { el.classList.add('leaving'); setTimeout(() => el.remove(), 380); };
        el.addEventListener('click', close);
        setTimeout(close, 5000);
    }
    window.carmelToast = toast;

    // ---- Tema ----
    window.toggleDarkMode = function () {
        document.documentElement.classList.add('theme-fade');
        setTimeout(() => document.documentElement.classList.remove('theme-fade'), 450);
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
                toast(d.message, 'ok');
                // pequena pausa para a pessoa ler o aviso antes de trocar de tela
                const go = url => setTimeout(() => { window.location.href = url; }, 1400);
                if (d.published) go(CFG.homeUrl);
                else if (d.found) go(CFG.queueUrl);
            })
            .catch(err => toast('Não foi possível sincronizar: ' + err.message + ' Tente novamente em instantes.', 'err'))
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

    // ---- Detalhes de movimento ----
    // Sombra na barra do topo ao rolar
    const topbar = document.querySelector('.topbar');
    if (topbar) {
        const onScroll = () => topbar.classList.toggle('scrolled', window.scrollY > 4);
        window.addEventListener('scroll', onScroll, { passive: true });
        onScroll();
    }
    // Miniaturas aparecem suavemente quando carregam
    document.querySelectorAll('.thumb img').forEach(img => {
        const show = () => img.classList.add('loaded');
        if (img.complete) show(); else { img.addEventListener('load', show); img.addEventListener('error', show); }
    });
    // Avisos do sistema somem sozinhos
    document.querySelectorAll('.alerts .alert').forEach(a => setTimeout(() => {
        a.classList.add('leaving');
        setTimeout(() => a.remove(), 450);
    }, 6000));

    setThemeIcon(document.documentElement.classList.contains('dark'));
    renderIcons();
})();
