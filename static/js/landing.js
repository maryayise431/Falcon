'use strict';

/* ═══════════════════════════════════════════════
   FALCON — Static Home Page Scripts
   ═══════════════════════════════════════════════ */

document.addEventListener('DOMContentLoaded', () => {

  /* ── NAV SCROLL STATE ── */
  const nav = document.getElementById('nav');
  if (nav) {
    window.addEventListener('scroll', () => {
      nav.classList.toggle('scrolled', window.scrollY > 20);
    });
  }

  /* ── MOBILE MENU TOGGLE ── */
  const hamburger = document.getElementById('hamburger');
  const mobileNav = document.getElementById('mobileNav');
  if (hamburger && mobileNav) {
    hamburger.addEventListener('click', () => {
      hamburger.classList.toggle('active');
      mobileNav.classList.toggle('open');
      document.body.style.overflow = mobileNav.classList.contains('open') ? 'hidden' : '';
    });
    mobileNav.querySelectorAll('a').forEach(a => {
      a.addEventListener('click', () => {
        hamburger.classList.remove('active');
        mobileNav.classList.remove('open');
        document.body.style.overflow = '';
      });
    });
  }

  /* ── SCROLL REVEAL ── */
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

  /* ── DARK / LIGHT MODE TOGGLE ── */
  const STORAGE_KEY = 'falcon-theme';

  function applyTheme(theme) {
    document.body.classList.toggle('light-mode', theme === 'light');
    document.querySelectorAll('.theme-toggle i').forEach(i => {
      i.className = theme === 'light' ? 'ri-moon-fill' : 'ri-sun-fill';
    });
  }

  const savedTheme = localStorage.getItem(STORAGE_KEY);
  if (savedTheme) {
    applyTheme(savedTheme);
  } else {
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    applyTheme(prefersDark ? 'dark' : 'light');
  }

  function toggleTheme() {
    const isLight = document.body.classList.contains('light-mode');
    const next = isLight ? 'dark' : 'light';
    applyTheme(next);
    localStorage.setItem(STORAGE_KEY, next);
  }

  document.querySelectorAll('.theme-toggle').forEach(btn => {
    btn.addEventListener('click', toggleTheme);
  });

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
