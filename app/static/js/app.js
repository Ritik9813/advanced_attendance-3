// Small progressive-enhancement helpers; all forms still work without this file.
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.flash').forEach((el) => {
    window.setTimeout(() => { el.classList.add('flash-fade'); }, 6000);
  });
});
