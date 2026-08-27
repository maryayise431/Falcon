/* Falcon – withdrawal request helper: live net-amount preview. */
(function () {
  "use strict";

  function naira(n) {
    return "\u20A6" + Number(n).toLocaleString(undefined, { maximumFractionDigits: 2 });
  }

  function init() {
    const amount = document.getElementById("id_amount");
    const preview = document.getElementById("withdraw-preview");
    if (!amount || !preview || amount.dataset.wBound) return;
    amount.dataset.wBound = "1";
    const fee = parseFloat(preview.dataset.fee || "0");

    function update() {
      const val = parseFloat(amount.value);
      if (!val || val <= 0) { preview.classList.add("hidden"); return; }
      const net = Math.max(val - fee, 0);
      preview.classList.remove("hidden");
      preview.innerHTML =
        "You receive: <strong>" + naira(net) + "</strong>" +
        " <span class='text-grey'>(fee " + naira(fee) + ")</span>";
    }
    amount.addEventListener("input", update);
    update();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
