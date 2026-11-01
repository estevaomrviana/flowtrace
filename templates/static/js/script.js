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

    // Fonte de assinantes: servidor do túnel só no acesso via SSH; porta padrão do banco
    document.querySelectorAll("[data-connection-switch]").forEach(function (box) {
        var select = box.querySelector("select[name=connection]");
        var engine = document.querySelector("select[name=engine]");
        var port = box.querySelector("input[name=db_port]");
        var defaults = { mysql: "3306", postgresql: "5432" };

        function sync() {
            box.querySelectorAll("[data-connection]").forEach(function (el) {
                el.hidden = el.getAttribute("data-connection") !== select.value;
            });
        }

        if (select) {
            select.addEventListener("change", sync);
            sync();
        }

        if (engine && port) {
            engine.addEventListener("change", function () {
                var isDefault = Object.keys(defaults).some(function (k) { return defaults[k] === port.value; });
                if (!port.value || isDefault) port.value = defaults[engine.value] || port.value;
            });
        }
    });

    // Requisição: executa as consultas pendentes uma a uma (cada uma é um POST
    // curto, sem estourar o timeout do servidor) e atualiza o cartão de cada item.
    document.querySelectorAll("[data-run-all]").forEach(function (btn) {
        btn.addEventListener("click", function () {
            var items = Array.prototype.slice.call(document.querySelectorAll("[data-item][data-status=pending]"));
            var csrf = document.querySelector("input[name=csrfmiddlewaretoken]");
            if (!items.length || !csrf) return;

            var label = btn.getAttribute("data-loading-text");
            var total = items.length;
            var done = 0;
            btn.disabled = true;

            function progress() {
                btn.innerHTML = '<span class="ft-spinner"></span>' + label + " " + (done + 1) + "/" + total;
            }

            function next() {
                var item = items.shift();
                if (!item) {
                    window.location.reload();
                    return;
                }
                progress();
                item.classList.add("is-running");

                fetch(item.getAttribute("data-run-url"), {
                    method: "POST",
                    headers: { "Accept": "application/json", "X-CSRFToken": csrf.value },
                    credentials: "same-origin"
                })
                    .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
                    .then(function (data) { item.outerHTML = data.html; })
                    .catch(function () { item.classList.remove("is-running"); })
                    .then(function () { done++; next(); });
            }

            next();
        });
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
