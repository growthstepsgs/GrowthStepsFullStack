/* ═══════════════════════════════════════════════
   Growth Steps | Clean Interaction Layer
═══════════════════════════════════════════════ */

(function () {
  'use strict';

  /* ── CONFIG ── */
  const CONFIG = {
    loaderMinDisplay: 1400,
    revealThreshold: 0.1,
    themeKey: 'gs-theme',
  };

  /* ── UTILITIES ── */
  const $ = (sel, ctx = document) => ctx.querySelector(sel);
  const $$ = (sel, ctx = document) => Array.from(ctx.querySelectorAll(sel));

  /* ── LOADING SCREEN ── */
  const initLoader = () => {
    const loader = $('#gs-loader');
    if (!loader) return;

    const start = performance.now();
    const hide = () => {
      const elapsed = performance.now() - start;
      const delay = Math.max(0, CONFIG.loaderMinDisplay - elapsed);
      setTimeout(() => {
        loader.classList.add('hidden');
        loader.addEventListener('transitionend', () => loader.remove(), { once: true });
      }, delay);
    };

    if (document.readyState === 'complete') {
      hide();
    } else {
      window.addEventListener('load', hide);
    }
  };

  /* ── THEME TOGGLE ── */
  const initTheme = () => {
    const html = document.documentElement;
    const btn = $('#themeToggle');
    const saved = localStorage.getItem(CONFIG.themeKey);

    // Apply saved theme immediately to prevent flash
    if (saved) html.setAttribute('data-theme', saved);

    if (!btn) return;

    btn.addEventListener('click', () => {
      const current = html.getAttribute('data-theme') || 'light';
      const next = current === 'dark' ? 'light' : 'dark';
      html.setAttribute('data-theme', next);
      localStorage.setItem(CONFIG.themeKey, next);
    });
  };

  /* ── SIDEBAR ── */
  const initSidebar = () => {
    const toggle = $('#menuToggle');
    const sidebar = $('#sidebar');
    const closeBtn = $('#closeSidebar');
    const overlay = $('#overlay');

    if (!toggle || !sidebar) return;

    const open = () => {
      sidebar.classList.add('open');
      overlay?.classList.add('active');
      sidebar.setAttribute('aria-hidden', 'false');
      document.body.style.overflow = 'hidden';
    };

    const close = () => {
      sidebar.classList.remove('open');
      overlay?.classList.remove('active');
      sidebar.setAttribute('aria-hidden', 'true');
      document.body.style.overflow = '';
    };

    toggle.addEventListener('click', open);
    closeBtn?.addEventListener('click', close);
    overlay?.addEventListener('click', close);

    // Close on link click
    sidebar.querySelectorAll('a').forEach(link => {
      link.addEventListener('click', close);
    });

    // Close on Escape
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && sidebar.classList.contains('open')) close();
    });
  };

  /* ── SCROLL REVEAL ── */
  const initReveal = () => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      $$('.reveal').forEach(el => el.classList.add('visible'));
      return;
    }

    const observer = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          entry.target.classList.add('visible');
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: CONFIG.revealThreshold });

    $$('.reveal').forEach(el => observer.observe(el));
  };

  /* ── EMAILJS CONTACT FORM ── */
  const initContactForm = () => {
    if (typeof emailjs === 'undefined') return;

    emailjs.init('mCuzsR0T2pAiUHHyP');

    const form = $('#contactForm');
    if (!form) return;

    form.addEventListener('submit', async (e) => {
      e.preventDefault();

      const submitBtn = form.querySelector('button[type="submit"]');
      const originalText = submitBtn?.textContent || 'Send';

      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = 'Sending…';
      }

      const nameEl = $('#name', form);
      const emailEl = $('#email', form);
      const messageEl = $('#message', form);
      const typeEl = $('#projectType', form);

      let messageText = messageEl?.value?.trim() || '';
      if (typeEl?.value) {
        messageText = `Project Type: ${typeEl.value}\n\n${messageText}`;
      }

      const params = {
        name: nameEl?.value?.trim() || '',
        email: emailEl?.value?.trim() || '',
        message: messageText,
      };

      try {
        await emailjs.send('service_kegm0bo', 'template_4j439oo', params);
        alert('Message sent successfully! I\'ll get back to you within 24 hours.');
        form.reset();
      } catch (err) {
        console.error('EmailJS error:', err);
        alert('Failed to send. Please try WhatsApp or email directly.');
      } finally {
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.textContent = originalText;
        }
      }
    });
  };

  /* ── INITIALIZE ── */
  document.addEventListener('DOMContentLoaded', () => {
    initLoader();
    initTheme();
    initSidebar();
    initReveal();
    initContactForm();
  });
})();