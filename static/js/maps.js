/* Falcon — lightweight location helpers.
   1) Address forms: "use my current location" fills lat/lng hidden inputs.
   2) Google Places autocomplete attaches to address inputs when a Maps API
      key is exposed via <body data-gmaps-key="...">.
   3) Tracking/preview: renders a Google Maps embed for #map-embed[data-lat/lng].
   Uses the free embed endpoint when no key is present. */
(function () {
  "use strict";

  function setEmbed(lat, lng) {
    const frame = document.getElementById("map-embed");
    if (!frame || lat === "" || lng === "") return;
    frame.dataset.lat = lat;
    frame.dataset.lng = lng;
    frame.src = "https://www.google.com/maps?q=" +
      encodeURIComponent(lat + "," + lng) + "&z=15&output=embed";
    frame.classList.remove("hidden");
  }

  function fillCoords(lat, lng) {
    const la = document.querySelector("input[name='delivery_address_lat']");
    const ln = document.querySelector("input[name='delivery_address_lng']");
    if (la) la.value = lat;
    if (ln) ln.value = lng;
  }

  function initPicker() {
    const btn = document.getElementById("use-my-location");
    if (!btn || btn.dataset.bound) return;
    btn.dataset.bound = "1";
    btn.addEventListener("click", function (e) {
      e.preventDefault();
      if (!navigator.geolocation) {
        btn.textContent = "Geolocation not supported";
        return;
      }
      btn.textContent = "Locating...";
      navigator.geolocation.getCurrentPosition(
        function (pos) {
          const lat = pos.coords.latitude.toFixed(6);
          const lng = pos.coords.longitude.toFixed(6);
          fillCoords(lat, lng);
          setEmbed(lat, lng);
          btn.innerHTML = "<i class='ri-map-pin-2-fill'></i> Location attached";
          btn.disabled = true;
        },
        function () {
          btn.textContent = "Permission denied - type address instead";
        }
      );
    });
  }

  function initMapEmbed() {
    const frame = document.getElementById("map-embed");
    if (!frame || frame.classList.contains("hidden")) return;
    const lat = parseFloat(frame.dataset.lat);
    const lng = parseFloat(frame.dataset.lng);
    if (isNaN(lat) || isNaN(lng)) return;
    frame.src = "https://www.google.com/maps?q=" +
      encodeURIComponent(lat + "," + lng) + "&z=15&output=embed";
  }

  function initAutocomplete() {
    const key = document.body.getAttribute("data-gmaps-key");
    if (!key) return;
    window.__falconPlacesReady = function () {
      document
        .querySelectorAll(
          "input[type='text'][name*='address' i]:not([data-places-bound])"
        )
        .forEach(function (inp) {
          if (!inp.name || /(_lat|_lng)$/i.test(inp.name)) return;
          inp.dataset.placesBound = "1";
          const ac = new google.maps.places.Autocomplete(inp, {
            fields: ["geometry"],
            componentRestrictions: { country: "ng" },
          });
          ac.addListener("place_changed", function () {
            const p = ac.getPlace();
            if (!p.geometry || !p.geometry.location) return;
            const lat = p.geometry.location.lat().toFixed(6);
            const lng = p.geometry.location.lng().toFixed(6);
            const form = inp.form || document;
            const ensure = function (name) {
              let el = form.querySelector("input[name='" + name + "']");
              if (!el && inp.form) {
                el = document.createElement("input");
                el.type = "hidden";
                el.name = name;
                inp.form.appendChild(el);
              }
              return el;
            };
            const latInput = ensure(inp.name + "_lat");
            const lngInput = ensure(inp.name + "_lng");
            if (latInput) latInput.value = lat;
            if (lngInput) lngInput.value = lng;
            fillCoords(lat, lng);
            setEmbed(lat, lng);
          });
        });
    };
    if (window.google && window.google.maps && window.google.maps.places) {
      window.__falconPlacesReady();
      return;
    }
    const s = document.createElement("script");
    s.src = "https://maps.googleapis.com/maps/api/js?key=" +
      encodeURIComponent(key) + "&libraries=places&callback=__falconPlacesReady";
    s.async = true;
    document.head.appendChild(s);
  }

  function init() {
    initPicker();
    initMapEmbed();
    initAutocomplete();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
