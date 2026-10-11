// Runs before first paint (index.html <head>).
// 1. Applies a remembered theme so there is no light/dark flash.
// 2. Picks what the first paint shows: the static landing hero in index.html only on "/" with no
//    signed-in hint (src/lib/auth.ts SIGNED_IN_HINT); otherwise a neutral empty shell, so deep
//    links, /privacy and returning readers never flash the landing. src/lib/boot.ts reads it back.
var boot = location.pathname === "/" ? "landing" : "shell";
try {
  var t = localStorage.getItem("readlayer:theme");
  if (t === "light" || t === "dark") document.documentElement.dataset.theme = t;
  if (localStorage.getItem("readlayer:signed-in")) boot = "shell";
} catch (e) {}
document.documentElement.dataset.boot = boot;
