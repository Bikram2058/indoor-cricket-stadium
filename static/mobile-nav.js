document.addEventListener('DOMContentLoaded', function () {
  var bar = document.querySelector('.topbar');
  if (!bar) return;
  var nav = bar.querySelector('nav');
  if (!nav) return;
  if (bar.querySelector('.nav-toggle')) return;

  var btn = document.createElement('button');
  btn.className = 'nav-toggle';
  btn.type = 'button';
  btn.setAttribute('aria-label', 'Toggle menu');
  btn.textContent = '\u2630';
  bar.insertBefore(btn, nav);

  btn.addEventListener('click', function () {
    nav.classList.toggle('open');
  });
  nav.addEventListener('click', function (e) {
    if (e.target.tagName === 'A') nav.classList.remove('open');
  });
});