'use strict';

/* ═══════════════════════════════════════════════
   FALCON — Static Home Page Scripts
   ═══════════════════════════════════════════════ */

document.addEventListener('DOMContentLoaded', () => {

  /* ── THEME TOGGLE (delegated capture — cannot be broken by later errors) ── */
  document.addEventListener('click', (e) => {
    const btn = e.target && e.target.closest ? e.target.closest('.theme-toggle') : null;
    if (!btn) return;
    const light = document.body.classList.toggle('light-mode');
    try { localStorage.setItem('falcon-theme', light ? 'light' : 'dark'); } catch (er) {}
    document.querySelectorAll('.theme-toggle i').forEach((ic) => {
      ic.className = light ? 'ri-moon-fill' : 'ri-sun-fill';
    });
  }, true);

  /* ── TOASTS: auto-dismiss after 5 seconds ── */
  document.querySelectorAll('.toast').forEach((toastEl) => {
    if (toastEl.dataset.toastBound) return;
    toastEl.dataset.toastBound = '1';
    const dismiss = () => {
      toastEl.classList.add('toast-out');
      setTimeout(() => toastEl.remove(), 350);
    };
    toastEl.querySelector('.toast-close')?.addEventListener('click', dismiss);
    setTimeout(dismiss, 5000);
  });

  /* ── NAV SCROLL STATE ── */
  const nav = document.getElementById('nav');
  if (nav) {
    window.addEventListener('scroll', () => {
      nav.classList.toggle('scrolled', window.scrollY > 20);
    });
  }

  /* ── MOBILE MENU TOGGLE ── */
  const menuEl = document.getElementById('mobileNav') || document.querySelector('.mobile-menu');
  const overlayEl = document.querySelector('.mobile-menu-overlay');
  const burgerEl = document.getElementById('hamburger') || document.querySelector('.navbar .hamburger');

  function closeMobileMenu() {
    if (!menuEl) return;
    if (burgerEl) burgerEl.classList.remove('active');
    menuEl.classList.remove('open');
    if (overlayEl) overlayEl.classList.remove('open');
    document.body.style.overflow = '';
  }

  if (menuEl && burgerEl && !burgerEl.dataset.menuBound) {
    burgerEl.dataset.menuBound = '1';
    burgerEl.addEventListener('click', () => {
      const willOpen = !menuEl.classList.contains('open');
      burgerEl.classList.toggle('active', willOpen);
      menuEl.classList.toggle('open', willOpen);
      if (overlayEl) overlayEl.classList.toggle('open', willOpen);
      document.body.style.overflow = willOpen ? 'hidden' : '';
    });
    menuEl.querySelectorAll('a').forEach(a => a.addEventListener('click', closeMobileMenu));
  }
  if (overlayEl && !overlayEl.dataset.bound) {
    overlayEl.dataset.bound = '1';
    overlayEl.addEventListener('click', closeMobileMenu);
  }
  document.querySelectorAll('.close-menu').forEach(btn => {
    btn.addEventListener('click', closeMobileMenu);
  });

  /* ── SCROLL REVEAL ── */
  /* DASHBOARD SIDEBAR TOGGLE */
  document.querySelectorAll('[data-sidebar-open]').forEach(btn => {
    btn.addEventListener('click', () => document.body.classList.add('sidebar-open'));
  });
  document.querySelectorAll('[data-sidebar-close]').forEach(el => {
    el.addEventListener('click', () => document.body.classList.remove('sidebar-open'));
  });
  document.querySelectorAll('.sidebar .side-link').forEach(link => {
    link.addEventListener('click', () => document.body.classList.remove('sidebar-open'));
  });

  /* PASSWORD VISIBILITY TOGGLES */
  document.querySelectorAll('.form-group').forEach(group => {
    const input = group.querySelector('input[type="password"]');
    if (!input || input.dataset.pwBound) return;
    input.dataset.pwBound = '1';

    const wrap = document.createElement('span');
    wrap.className = 'input-wrap';
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'pw-toggle';
    btn.setAttribute('aria-label', 'Show password');
    btn.innerHTML = '<i class="ri-eye-line"></i>';
    btn.addEventListener('click', () => {
      const show = input.type === 'password';
      input.type = show ? 'text' : 'password';
      btn.innerHTML = show ? '<i class="ri-eye-off-line"></i>' : '<i class="ri-eye-line"></i>';
      btn.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
      input.focus({ preventScroll: true });
    });
    wrap.appendChild(btn);
  });

  /* REGISTRATION TAB SWITCH fallback safety (template script handles main flow) */

  /* THEME: inject a floating control on bare auth pages (no navbar there).
     Binding + persistence are handled by the single DARK/LIGHT block below. */
  if (!document.getElementById("theme-toggle") && document.body.classList.contains("auth-bare")) {
    const injected = document.createElement("button");
    injected.type = "button";
    injected.className = "theme-toggle auth-theme-toggle";
    injected.setAttribute("aria-label", "Toggle theme");
    injected.innerHTML = '<i class="ri-sun-fill"></i>';
    document.body.appendChild(injected);
  }

  const revealEls = document.querySelectorAll('.reveal');
  const io = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('in');
        io.unobserve(entry.target);
      }
    });
  }, { threshold: 0.15 });
  revealEls.forEach(el => io.observe(el));

  /* ── DARK / LIGHT MODE — restore saved preference (binding is delegated above) ── */
  try {
    const savedTheme = localStorage.getItem('falcon-theme');
    if (savedTheme === 'light' || savedTheme === 'dark') {
      document.body.classList.toggle('light-mode', savedTheme === 'light');
      document.querySelectorAll('.theme-toggle i').forEach((i) => {
        i.className = savedTheme === 'light' ? 'ri-moon-fill' : 'ri-sun-fill';
      });
    }
  } catch (er) {}

  /* ── SMOOTH SCROLL FOR ANCHOR LINKS ── */
  document.addEventListener('click', (e) => {
    const anchor = e.target.closest('a[href^="#"]');
    if (!anchor) return;

    const targetId = anchor.getAttribute('href');
    if (!targetId || targetId === '#') return;

    const target = document.querySelector(targetId);
    if (!target) return;

    e.preventDefault();
    target.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });

  /* ── PRODUCTS LIST / GRID VIEW TOGGLE ── */
  const viewToggle = document.getElementById('viewToggle');
  const productsGrid = document.getElementById('productsGrid');
  if (viewToggle && productsGrid) {
    viewToggle.querySelectorAll('.view-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        viewToggle.querySelectorAll('.view-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        if (btn.dataset.view === 'list') {
          productsGrid.classList.add('list-view');
        } else {
          productsGrid.classList.remove('list-view');
        }
      });
    });
  }

});
