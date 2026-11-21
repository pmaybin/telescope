// Set the theme before React mounts to avoid a flash of the wrong one.
try {
  var t = localStorage.getItem('telescope-theme')
  if (t === 'light' || t === 'dark')
    document.documentElement.setAttribute('data-theme', t)
} catch (e) {}
