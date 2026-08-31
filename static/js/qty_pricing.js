(function () {
  var rows = document.getElementById("qpRows");
  var addBtn = document.getElementById("qpAdd");
  if (!rows || !addBtn) return;

  function nextQty() {
    var max = 1;
    var items = rows.querySelectorAll(".qp-row");
    for (var i = 0; i < items.length; i++) {
      var v = parseInt(items[i].dataset.qty || items[i].querySelector(".qp-qty").value, 10);
      if (v > max) max = v;
    }
    return max + 1;
  }

  function addRow(qty) {
    var row = document.createElement("div");
    row.className = "qp-row";
    row.dataset.qty = qty;

    var qtyInput = document.createElement("input");
    qtyInput.className = "qp-qty";
    qtyInput.name = "qp_qty";
    qtyInput.type = "number";
    qtyInput.value = qty;
    qtyInput.readOnly = true;
    qtyInput.tabIndex = -1;
    qtyInput.setAttribute("aria-label", "Quantity " + qty);

    var x = document.createElement("span");
    x.className = "qp-x";
    x.textContent = "\u2192";

    var price = document.createElement("input");
    price.className = "qp-price";
    price.name = "qp_price";
    price.type = "number";
    price.min = "0";
    price.step = "0.01";
    price.placeholder = "Flat price";
    price.setAttribute("aria-label", "Flat price for quantity " + qty);

    var del = document.createElement("button");
    del.type = "button";
    del.className = "btn btn-ghost btn-sm qp-del";
    del.tabIndex = -1;
    del.setAttribute("aria-label", "Remove row");
    del.textContent = "\u00d7";

    row.appendChild(qtyInput);
    row.appendChild(x);
    row.appendChild(price);
    row.appendChild(del);
    rows.appendChild(row);
  }

  addBtn.addEventListener("click", function () {
    addRow(nextQty());
  });

  rows.addEventListener("click", function (e) {
    if (e.target.classList.contains("qp-del")) {
      var row = e.target.closest(".qp-row");
      if (row) row.remove();
    }
  });
})();