/* Campos de CPF: aceita só dígitos (máx. 11) e mostra 000.000.000-00. Texto como "admin" passa sem máscara. */
(function () {
    function format(digits) {
        return digits
            .replace(/^(\d{3})(\d)/, '$1.$2')
            .replace(/^(\d{3})\.(\d{3})(\d)/, '$1.$2.$3')
            .replace(/\.(\d{3})(\d)/, '.$1-$2');
    }
    document.querySelectorAll('input[data-cpf]').forEach(function (input) {
        var onlyCpf = input.dataset.cpf === 'only';
        input.addEventListener('input', function () {
            var value = input.value;
            if (onlyCpf || /^[\d.\-\s]*$/.test(value)) {
                input.value = format(value.replace(/\D/g, '').slice(0, 11));
            }
        });
    });
})();
