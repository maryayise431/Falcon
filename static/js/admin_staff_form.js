(function () {
  document.addEventListener('DOMContentLoaded', function () {
    var roleSelect = document.getElementById('id_role');
    var addressRow = document.querySelector('.field-agent_address');
    if (!roleSelect || !addressRow) return;

    function toggle() {
      var isAgent = roleSelect.value === 'delivery_agent';
      addressRow.style.display = isAgent ? '' : 'none';
      var input = addressRow.querySelector('textarea, input');
      if (input && !isAgent) input.value = '';
    }

    roleSelect.addEventListener('change', toggle);
    toggle();
  });
})();
