/* Botão de olho dos campos de senha: mostra e oculta o que foi digitado. */
(function () {
    document.querySelectorAll('[data-pw-toggle]').forEach(function (button) {
        var input = button.closest('.input-icon').querySelector('input');
        button.addEventListener('click', function () {
            var visible = input.type === 'password';
            input.type = visible ? 'text' : 'password';
            button.setAttribute('aria-pressed', visible ? 'true' : 'false');
            button.setAttribute('aria-label', visible ? 'Ocultar senha' : 'Mostrar senha');
            button.querySelector('[data-pw-show]').hidden = visible;
            button.querySelector('[data-pw-hide]').hidden = !visible;
            input.focus();
        });
    });
})();
