// Mikuchin promo site interactions. No dependencies.
(() => {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];

  /* nav background on scroll */
  const nav = $('#nav');
  const onScroll = () => nav.classList.toggle('is-scrolled', scrollY > 12);
  addEventListener('scroll', onScroll, { passive: true });
  onScroll();

  /* reveal on scroll */
  const io = new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (e.isIntersecting) { e.target.classList.add('is-visible'); io.unobserve(e.target); }
    }
  }, { threshold: 0.12, rootMargin: '0px 0px -40px 0px' });
  $$('.reveal').forEach((el) => io.observe(el));

  /* showcase tabs: click to switch, auto-advance when the progress bar finishes */
  const showcase = $('.showcase');
  const tabs = $$('.stab');
  const shots = $$('.shot');
  const select = (i) => {
    tabs.forEach((t, n) => {
      const on = n === i;
      t.classList.toggle('is-active', on);
      t.setAttribute('aria-selected', String(on));
      const bar = $('.stab__bar i', t);          // restart progress animation
      bar.style.animation = 'none'; void bar.offsetWidth; bar.style.animation = '';
    });
    shots.forEach((s, n) => s.classList.toggle('is-active', n === i));
  };
  tabs.forEach((t, i) => {
    t.addEventListener('click', () => select(i));
    $('.stab__bar i', t).addEventListener('animationend', () => {
      if (t.classList.contains('is-active')) select((i + 1) % tabs.length);
    });
  });
  showcase.addEventListener('mouseenter', () => showcase.classList.add('is-paused'));
  showcase.addEventListener('mouseleave', () => showcase.classList.remove('is-paused'));

  /* lightbox */
  const lb = $('#lightbox');
  const lbImg = $('img', lb);
  const open = (src, alt = '') => { lbImg.src = src; lbImg.alt = alt; lb.hidden = false; document.body.style.overflow = 'hidden'; };
  const close = () => { lb.hidden = true; document.body.style.overflow = ''; };
  document.addEventListener('click', (e) => {
    const img = e.target.closest('[data-lightbox]');
    if (img && !img.closest('.is-missing')) open(img.currentSrc || img.src, img.alt);
  });
  lb.addEventListener('click', close);
  addEventListener('keydown', (e) => { if (e.key === 'Escape' && !lb.hidden) close(); });

  /* launcher screenshots: show a tidy placeholder if a file has not been added yet */
  $$('.appwin__view img').forEach((img) => {
    const view = img.parentElement;
    view.dataset.slot = img.dataset.slot || '';
    const miss = () => view.classList.add('is-missing');
    if (img.complete && img.naturalWidth === 0) miss();
    img.addEventListener('error', miss);
  });

  /* easter egg (same as the desktop manager): five quick clicks on Miku */
  const miku = $('#miku');
  let clicks = 0, timer;
  miku.addEventListener('click', () => {
    miku.classList.remove('is-bounce'); void miku.offsetWidth; miku.classList.add('is-bounce');
    clearTimeout(timer);
    timer = setTimeout(() => (clicks = 0), 2500);
    if (++clicks >= 5) { clicks = 0; open('assets/full.png', 'Mikuchin'); }
  });
})();
