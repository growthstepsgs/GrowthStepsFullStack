/* ═══════════════════════════════════════════════
   GS-Growth Steps | script.js
   Works across index.html, courses.html, services.html
═══════════════════════════════════════════════ */

/* ── LOADING SCREEN ── */
(function () {
  const loader = document.getElementById('gs-loader');
  if (!loader) return;

  const MIN_DISPLAY = 1800;
  const start = Date.now();

  function hideLoader() {
    const elapsed = Date.now() - start;
    const delay   = Math.max(0, MIN_DISPLAY - elapsed);
    setTimeout(function () {
      loader.classList.add('gs-loader--hidden');
      loader.addEventListener('transitionend', function () {
        loader.remove();
      }, { once: true });
    }, delay);
  }

  if (document.readyState === 'complete') {
    hideLoader();
  } else {
    window.addEventListener('load', hideLoader);
  }
})();

/* ── THEME TOGGLE ── */
const html     = document.documentElement;
const themeBtn = document.getElementById('themeToggle');

// Apply saved preference immediately to avoid flash
const saved = localStorage.getItem('gs-theme');
if (saved) html.setAttribute('data-theme', saved);

if (themeBtn) {
  themeBtn.addEventListener('click', () => {
    const next = html.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    html.setAttribute('data-theme', next);
    localStorage.setItem('gs-theme', next);
  });
}

/* ── SIDEBAR TOGGLE (null-safe, works on all pages) ── */
document.addEventListener('DOMContentLoaded', function () {
  const menuToggle   = document.getElementById('menuToggle');
  const sidebar      = document.getElementById('sidebar');
  const closeSidebar = document.getElementById('closeSidebar');
  const overlay      = document.getElementById('overlay');

  if (!menuToggle || !sidebar) return;

  function openSidebar() {
    sidebar.classList.add('active');
    if (overlay) overlay.classList.add('active');
    sidebar.setAttribute('aria-hidden', 'false');
  }

  function closeSidebarFn() {
    sidebar.classList.remove('active');
    if (overlay) overlay.classList.remove('active');
    sidebar.setAttribute('aria-hidden', 'true');
  }

  menuToggle.addEventListener('click', openSidebar);
  if (closeSidebar) closeSidebar.addEventListener('click', closeSidebarFn);
  if (overlay) overlay.addEventListener('click', closeSidebarFn);

  // Close on any sidebar link click (smooth for same-page anchors)
  sidebar.querySelectorAll('a').forEach(function (link) {
    link.addEventListener('click', closeSidebarFn);
  });
});

/* ── SCROLL REVEAL ── */
const revealObserver = new IntersectionObserver((entries) => {
  entries.forEach((entry) => {
    if (entry.isIntersecting) entry.target.classList.add('visible');
  });
}, { threshold: 0.12 });

document.querySelectorAll('.reveal').forEach((el) => revealObserver.observe(el));

/* ── EMAILJS CONTACT FORM ── */
/* Handles any page that has <form id="contactForm"> with
   id="name", id="email", id="message" fields.
   On services.html an optional id="projectType" select is
   prepended to the message so it arrives in the same template. */
(function () {
  if (typeof emailjs === 'undefined') return;

  emailjs.init('mCuzsR0T2pAiUHHyP');

  const contactForm = document.getElementById('contactForm');
  if (!contactForm) return;

  contactForm.addEventListener('submit', function (e) {
    e.preventDefault();

    const submitBtn = contactForm.querySelector('button[type="submit"]');
    if (submitBtn) {
      submitBtn.disabled    = true;
      submitBtn.textContent = 'Sending…';
    }

    // Gather fields
    const nameEl    = document.getElementById('name');
    const emailEl   = document.getElementById('email');
    const messageEl = document.getElementById('message');
    const typeEl    = document.getElementById('projectType'); // optional

    let messageText = messageEl ? messageEl.value : '';
    if (typeEl && typeEl.value) {
      messageText = 'Project Type: ' + typeEl.value + '\n\n' + messageText;
    }

    const templateParams = {
      name    : nameEl    ? nameEl.value    : '',
      email   : emailEl   ? emailEl.value   : '',
      message : messageText,
    };

    emailjs.send('service_kegm0bo', 'template_4j439oo', templateParams)
      .then(function () {
        alert('Message sent successfully! I\'ll get back to you within 24 hours.');
        contactForm.reset();
        if (submitBtn) {
          submitBtn.disabled    = false;
          submitBtn.textContent = 'Send Message';
        }
      })
      .catch(function (err) {
        console.error(err);
        alert('Failed to send. Please try WhatsApp or email directly.');
        if (submitBtn) {
          submitBtn.disabled    = false;
          submitBtn.textContent = 'Send Message';
        }
      });
  });
})();
