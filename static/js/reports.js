/* Falcon — reports helpers: period quick-select syncs custom range fields. */
(function () {
  "use strict";

  function sync(wrap, select, focus) {
    if (!wrap) return;
    if (select.value === "custom") {
      wrap.classList.remove("hidden");
      if (focus) {
        const start = wrap.querySelector("input[name='start']");
        if (start && !start.value) start.focus();
      }
    } else {
      wrap.classList.add("hidden");
    }
  }

  function init() {
    const select = document.getElementById("period-select");
    if (!select || select.dataset.rBound) return;
    select.dataset.rBound = "1";
    const wrap = document.getElementById("custom-range");

    select.addEventListener("change", function () {
      if (!wrap) { if (select.form) select.form.submit(); return; }
      if (select.value === "custom") {
        sync(wrap, select, true);
        return;
      }
      wrap.classList.add("hidden");
      if (select.form) select.form.submit();
    });

    sync(wrap, select, false);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
