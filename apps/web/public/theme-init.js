// Applies a remembered theme before first paint so there is no light/dark flash.
try {
  var t = localStorage.getItem("readlayer:theme");
  if (t === "light" || t === "dark") document.documentElement.dataset.theme = t;
} catch (e) {}
