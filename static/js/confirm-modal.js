/* Falcon – accessible confirm modal.
   Any element with [data-confirm] triggers the modal before following its action:
   - <form data-confirm="message"> → submits after OK
   - <a href data-confirm="...">   → navigates after OK
*/
(function () {
  "use strict";

  let overlay = null;
  let pendingForm = null;
  let pendingHref = null;

  function build() {
    overlay = document.createElement("div");
    overlay.className = "modal-overlay";
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    overlay.innerHTML =
      '<div class="modal-card">' +
      '  <h3 id="cm-title">Confirm action</h3>' +
      '  <p id="cm-msg"></p>' +
      '  <div class="modal-actions">' +
      '    <button type="button" class="btn btn-outline" data-cm-cancel>Cancel</button>' +
      '    <button type="button" class="btn btn-solid" data-cm-ok>Confirm</button>' +
      "  </div>" +
      "</div>";
    document.body.appendChild(overlay);

    overlay.querySelector("[data-cm-cancel]").addEventListener("click", close);
    overlay.querySelector("[data-cm-ok]").addEventListener("click", proceed);
    overlay.addEventListener("click", function (e) {
      if (e.target === overlay) close();
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && overlay.classList.contains("open")) close();
    });
  }

  function open(message, title) {
    if (!overlay) build();
    overlay.querySelector("#cm-msg").textContent = message || "Are you sure?";
    overlay.querySelector("#cm-title").textContent = title || "Confirm action";
    overlay.classList.add("open");
  }

  function close() {
    if (overlay) overlay.classList.remove("open");
    pendingForm = null;
    pendingHref = null;
  }

  function proceed() {
    if (pendingForm) {
      const f = pendingForm;
      pendingForm = null;
      close();
      /* temporarily disable confirm so it doesn't re-trigger */
      f.removeAttribute("data-confirm");
      if (typeof f.requestSubmit === "function") f.requestSubmit();
      else f.submit();
    } else if (pendingHref) {
      window.location.href = pendingHref;
    } else {
      close();
    }
  }

  function init() {
    document.addEventListener(
      "submit",
      function (e) {
        const form = e.target;
        if (form.hasAttribute("data-confirm") && !form.__cmActive) {
          e.preventDefault();
          pendingForm = form;
          open(form.getAttribute("data-confirm"), form.getAttribute("data-confirm-title"));
        }
      },
      true
    );
    document.addEventListener(
      "click",
      function (e) {
        const link = e.target.closest("a[data-confirm]");
        if (link) {
          e.preventDefault();
          pendingHref = link.getAttribute("href");
          open(link.getAttribute("data-confirm"), link.getAttribute("data-confirm-title"));
        }
      },
      true
    );
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
