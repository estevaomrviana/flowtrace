(function () {
    "use strict";

    // Alternância de tema claro/escuro
    document.querySelectorAll("[data-theme-toggle]").forEach(function (btn) {
        btn.addEventListener("click", function () {
            var root = document.documentElement;
            var next = root.getAttribute("data-bs-theme") === "dark" ? "light" : "dark";
            root.setAttribute("data-bs-theme", next);
            try { localStorage.setItem("ft-theme", next); } catch (e) {}
        });
    });

    // Estado de carregamento nos formulários (a consulta SSH pode demorar)
    var loadingButtons = [];

    document.querySelectorAll("form[data-loading]").forEach(function (form) {
        var btn = form.querySelector("[data-loading-text]");
        if (!btn) return;

        var original = btn.innerHTML;
        loadingButtons.push(function () {
            btn.disabled = false;
            btn.innerHTML = original;
        });

        form.addEventListener("submit", function () {
            btn.disabled = true;
            btn.innerHTML = '<span class="ft-spinner"></span>' + btn.getAttribute("data-loading-text");
        });
    });

    // Restaura os botões quando a página volta do cache do navegador ("voltar")
    window.addEventListener("pageshow", function (event) {
        if (event.persisted) loadingButtons.forEach(function (reset) { reset(); });
    });

    // Copiar para a área de transferência
    document.addEventListener("click", function (event) {
        var btn = event.target.closest("[data-copy]");
        if (!btn || !navigator.clipboard) return;

        navigator.clipboard.writeText(btn.getAttribute("data-copy")).then(function () {
            var icon = btn.querySelector(".lni");
            btn.classList.add("is-copied");
            if (icon) icon.className = "lni lni-checkmark";
            setTimeout(function () {
                btn.classList.remove("is-copied");
                if (icon) icon.className = "lni lni-files";
            }, 1500);
        });
    });

    // Formulário de servidor: mostra só os campos do método de autenticação escolhido
    document.querySelectorAll("[data-auth-switch]").forEach(function (box) {
        var select = box.querySelector("select[name=auth_method]");
        if (!select) return;

        function sync() {
            box.querySelectorAll("[data-auth]").forEach(function (el) {
                el.hidden = el.getAttribute("data-auth") !== select.value;
            });
        }

        select.addEventListener("change", sync);
        sync();
    });

    // Filtro de lista no cliente
    document.querySelectorAll("input[data-filter]").forEach(function (input) {
        var items = document.querySelectorAll(input.getAttribute("data-filter"));
        var empty = document.querySelector("[data-filter-empty]");

        input.addEventListener("input", function () {
            var term = input.value.trim().toLowerCase();
            var visible = 0;

            items.forEach(function (item) {
                var match = item.getAttribute("data-filter-text").indexOf(term) !== -1;
                item.classList.toggle("d-none", !match);
                if (match) visible++;
            });

            if (empty) empty.classList.toggle("d-none", visible > 0);
        });
    });
})();
