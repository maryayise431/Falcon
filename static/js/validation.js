/* Falcon â€“ live username/email availability checks.
   Inputs: <input data-check-url="..." name="username|email">
   Renders a .field-hint sibling with result. */
(function () {
  "use strict";

  function debounce(fn, wait) {
    let t = null;
    return function () {
      const args = arguments;
      clearTimeout(t);
      t = setTimeout(function () { fn.apply(null, args); }, wait);
    };
  }

  function ensureHint(input) {
    let hint = input.parentElement.querySelector(".field-hint[data-for='" + input.name + "']");
    if (!hint) {
      hint = document.createElement("div");
      hint.className = "field-hint";
      hint.setAttribute("data-for", input.name);
      input.parentElement.appendChild(hint);
    }
    return hint;
  }

  function init() {
    const inputs = document.querySelectorAll("input[data-check-url]");
    inputs.forEach(function (input) {
      if (input.dataset.checkBound) return;
      input.dataset.checkBound = "1";
      const hint = ensureHint(input);

      const run = debounce(function () {
        const value = input.value.trim();
        if (!value) { hint.className = "field-hint"; hint.textContent = ""; return; }
        if (input.name === "email") return;
        const key = "username";
        fetch(input.dataset.checkUrl + "?" + key + "=" + encodeURIComponent(value))
          .then(function (r) { return r.json(); })
          .then(function (data) {
            if (data.exists === false && data.valid !== false) {
              hint.className = "field-hint ok";
              hint.innerHTML = "<i class='ri-check-line'></i> Available";
            } else {
              hint.className = "field-hint bad";
              hint.textContent = data.detail || "Already taken";
            }
          })
          .catch(function () { hint.className = "field-hint"; hint.textContent = ""; });
      }, 450);

      input.addEventListener("input", run);
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();

