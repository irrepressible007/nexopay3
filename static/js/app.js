/* Nexopay - small Alpine components and the motion layer. Loaded before Alpine (both deferred). */
const EXPO = "cubic-bezier(.16, 1, .3, 1)";
const SPRING = "cubic-bezier(.34, 1.56, .64, 1)";
/* Motion level: the visitor's own reduce-motion setting, or "off"/"calm" chosen in Site settings. */
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches
  || document.documentElement.classList.contains("motion-off");
const calmMotion = reduceMotion || document.documentElement.classList.contains("motion-calm");

/* A short buzz on Android phones for moments that matter (a ticket picked, a card flipped). */
const haptic = (ms = 8) => { try { if (!reduceMotion && navigator.vibrate) navigator.vibrate(ms); } catch (_) {} };

/* A springy scale bump, for numbers that just changed. */
const bump = (el, to = 1.12) => {
  if (el && el.animate && !reduceMotion) el.animate([{ transform: "none" }, { transform: `scale(${to})` }, { transform: "none" }], { duration: 380, easing: SPRING });
};

/* A little ticket flies in an arc from one element to another, then `done` runs. */
const flyTo = (from, to, label, done) => {
  const a = from.getBoundingClientRect(), b = to.getBoundingClientRect();
  const el = document.createElement("span");
  el.className = "fly-ticket";
  el.innerHTML = '<svg aria-hidden="true"><use href="#i-ticket"/></svg>';
  el.append(label);
  el.style.left = `${a.left + a.width / 2}px`;
  el.style.top = `${a.top + a.height / 2}px`;
  document.body.appendChild(el);
  const dx = b.left + b.width / 2 - (a.left + a.width / 2), dy = b.top + b.height / 2 - (a.top + a.height / 2);
  const arc = Math.min(-40, dy * 0.25 - 60);
  el.animate([
    { transform: "translate(0, 0) scale(.5) rotate(0deg)", opacity: 0 },
    { transform: `translate(${dx * 0.4}px, ${dy * 0.35 + arc}px) scale(1.1) rotate(-10deg)`, opacity: 1, offset: 0.4 },
    { transform: `translate(${dx}px, ${dy}px) scale(.55) rotate(8deg)`, opacity: 0.3 },
  ], { duration: 680, easing: "cubic-bezier(.45, 0, .2, 1)" }).onfinish = () => { el.remove(); if (done) done(); };
};

/* Confetti bursting from an element (order confirmed). */
window.nxBurst = (origin) => {
  if (reduceMotion || !origin || !document.body.animate) return;
  const r = origin.getBoundingClientRect(), cx = r.left + r.width / 2, cy = r.top + r.height / 2;
  const colors = ["var(--color-brand)", "var(--color-brand-fg)", "var(--color-accent)", "var(--color-success)", "#f2f2f4"];
  for (let i = 0; i < 42; i++) {
    const bit = document.createElement("i");
    const w = 5 + Math.random() * 5, long = Math.random() < 0.5;
    bit.className = "burst-bit";
    bit.style.cssText = `left:${cx}px;top:${cy}px;width:${w}px;height:${long ? w * 2.2 : w}px;background:${colors[i % colors.length]};border-radius:${long ? "2px" : "50%"}`;
    document.body.appendChild(bit);
    const angle = Math.random() * Math.PI * 2, speed = 110 + Math.random() * 230;
    const dx = Math.cos(angle) * speed, dy = Math.sin(angle) * speed - 90, fall = 240 + Math.random() * 180, spin = (Math.random() - 0.5) * 900;
    bit.animate([
      { transform: "translate(0, 0) scale(.3)", opacity: 1 },
      { transform: `translate(${dx * 0.75}px, ${dy * 0.75}px) rotate(${spin * 0.5}deg) scale(1)`, opacity: 1, offset: 0.35 },
      { transform: `translate(${dx}px, ${dy + fall}px) rotate(${spin}deg) scale(.9)`, opacity: 0 },
    ], { duration: 1400 + Math.random() * 800, easing: "cubic-bezier(.15, .6, .35, 1)", fill: "forwards" }).onfinish = () => bit.remove();
  }
};

document.addEventListener("alpine:init", () => {

  /* Auto-advancing slider for admin hero slides. */
  Alpine.data("slider", (count, interval = 6000) => ({
    i: 0,
    timer: null,
    init() { this.play(); },
    play() {
      if (count < 2 || reduceMotion) return;
      this.pause();
      this.timer = setInterval(() => this.next(), interval);
    },
    pause() { clearInterval(this.timer); },
    next() { this.i = (this.i + 1) % count; },
    prev() { this.i = (this.i - 1 + count) % count; },
    go(n) { this.i = n; this.play(); },
  }));

  /* Hero poster deck: the front poster is dealt away every few seconds (while on screen), and on any
     screen it can be flicked away by finger or mouse: it follows the drag and flies off to that
     side; a short drag springs back and still opens the event on tap. Phones get a one-time
     wiggle as a hint that the deck can be flicked. */
  Alpine.data("posterStack", (count, interval = 5500) => ({
    i: 0, out: null, dir: -1, timer: null, visible: true, held: false,
    init() {
      if ("IntersectionObserver" in window) {
        new IntersectionObserver(([e]) => { this.visible = e.isIntersecting; this.visible ? this.play() : this.pause(); }).observe(this.$el);
      }
      this.play();
      if (count > 1) this.swipe();
    },
    depth(n) { return (n - this.i + count) % count; },
    front() { return this.$refs.deck && this.$refs.deck.querySelector('.poster-card[data-depth="0"]'); },
    play() {
      if (count < 2 || !interval || reduceMotion || !this.visible || this.held) return;
      this.pause();
      this.timer = setInterval(() => this.show((this.i + 1) % count), interval);
    },
    pause() { clearInterval(this.timer); this.timer = null; },
    show(n, dir = -1) {
      if (n === this.i) return;
      this.dir = dir;
      this.out = this.i;
      this.i = n;
      clearTimeout(this.outTimer);
      this.outTimer = setTimeout(() => (this.out = null), 450);
    },
    go(n) { this.show(n); this.play(); },
    swipe() {
      const deck = this.$refs.deck;
      let x0 = 0, y0 = 0, dx = 0, id = null, dragging = false, card = null, blockClick = false;
      const end = (commit) => {
        if (card) {
          card.classList.remove("is-dragging");
          card.style.removeProperty("--drag");
          card.style.removeProperty("--drag-deg");
        }
        if (commit) { haptic(); this.show((this.i + 1) % count, dx > 0 ? 1 : -1); }
        dragging = false; card = null; id = null; this.held = false; this.play();
      };
      deck.addEventListener("pointerdown", (e) => {
        if (e.button > 0 || id !== null) return;
        card = this.front();
        if (!card || !card.contains(e.target)) { card = null; return; }
        id = e.pointerId; x0 = e.clientX; y0 = e.clientY; dx = 0; blockClick = false;
        this.held = true; this.pause();
      });
      deck.addEventListener("pointermove", (e) => {
        if (e.pointerId !== id || !card) return;
        dx = e.clientX - x0;
        const dy = e.clientY - y0;
        if (!dragging) {
          if (Math.abs(dy) > 10 && Math.abs(dy) > Math.abs(dx)) { end(false); return; } // scrolling the page
          if (Math.abs(dx) < 8) return;
          dragging = true;
          card.classList.add("is-dragging");
          try { deck.setPointerCapture(id); } catch (_) {}
        }
        card.style.setProperty("--drag", `${dx}px`);
        card.style.setProperty("--drag-deg", (dx / 18).toFixed(2));
      });
      const release = (e) => {
        if (e.pointerId !== id) return;
        if (dragging) blockClick = true;
        end(dragging && Math.abs(dx) > Math.min(90, deck.clientWidth * 0.22));
      };
      deck.addEventListener("pointerup", release);
      deck.addEventListener("pointercancel", release);
      // A drag is not a tap: don't open the event the card was flicked from.
      deck.addEventListener("click", (e) => { if (blockClick) { e.preventDefault(); e.stopPropagation(); blockClick = false; } }, true);
      // Touch screens: the first time the deck comes into view, the top card wiggles to show it moves.
      if (!calmMotion && window.matchMedia("(pointer: coarse)").matches) {
        let hinted = false;
        try { hinted = sessionStorage.getItem("nx-deck-hint") === "1"; } catch (_) {}
        if (!hinted && "IntersectionObserver" in window) {
          const io = new IntersectionObserver(([e]) => {
            if (!e.isIntersecting) return;
            io.disconnect();
            setTimeout(() => {
              const c = this.front();
              if (c && c.animate) c.animate([{ translate: "0 0", rotate: "0deg" }, { translate: "-34px 0", rotate: "-4deg" }, { translate: "10px 0", rotate: "1.5deg" }, { translate: "0 0", rotate: "0deg" }], { duration: 1100, easing: "cubic-bezier(.34, 1.3, .64, 1)" });
              try { sessionStorage.setItem("nx-deck-hint", "1"); } catch (_) {}
            }, 1200);
          }, { threshold: 0.6 });
          io.observe(deck);
        }
      }
    },
  }));

  /* Live countdown: x-data="countdown('2026-11-14T12:00:00Z')" */
  Alpine.data("countdown", (iso) => ({
    d: "00", h: "00", m: "00", s: "00", done: false,
    init() { this.tick(); this.t = setInterval(() => this.tick(), 1000); },
    destroy() { clearInterval(this.t); },
    tick() {
      let diff = Math.max(0, new Date(iso).getTime() - Date.now());
      if (diff === 0) { this.done = true; clearInterval(this.t); }
      const pad = (n) => String(n).padStart(2, "0");
      this.d = pad(Math.floor(diff / 864e5)); diff %= 864e5;
      this.h = pad(Math.floor(diff / 36e5)); diff %= 36e5;
      this.m = pad(Math.floor(diff / 6e4)); diff %= 6e4;
      this.s = pad(Math.floor(diff / 1e3));
    },
  }));

  /* Ticket selection on the event page. `types` = [{id, price, max, remaining}]
     Picking a ticket feels like collecting it: a little ticket flies from the row into the total,
     the quantity rolls, the total counts up, and the checkout button wakes up. Pressing it sends
     the label away and the whole card travels on into the checkout page (view transition). */
  Alpine.data("ticketPicker", (types, maxTotal, lang) => ({
    q: Object.fromEntries(types.map((t) => [t.id, 0])),
    types,
    shown: 0, // the total on screen; counts towards the real one
    get count() { return Object.values(this.q).reduce((a, b) => a + b, 0); },
    get total() { return this.types.reduce((sum, t) => sum + t.price * this.q[t.id], 0); },
    limit(t) { return Math.min(t.max, t.remaining, maxTotal - this.count + this.q[t.id]); },
    inc(t, e) { if (this.q[t.id] < this.limit(t)) { this.q[t.id]++; this.picked(t, e, 1); } },
    dec(t) { if (this.q[t.id] > 0) { this.q[t.id]--; this.roll(t, -1); } },
    toggle(t, e) {
      const had = this.q[t.id];
      this.q[t.id] = had ? 0 : Math.min(1, this.limit(t));
      if (!had && this.q[t.id]) this.picked(t, e, 1);
    },
    init() {
      this.$watch("total", (to) => this.countTo(to));
      this.$watch("count", (n, before) => {
        const btn = this.$refs.go;
        if (!btn || reduceMotion) return;
        btn.classList.toggle("btn-alive", n > 0 && !calmMotion);
        if (n > 0 && !before) { btn.classList.remove("btn-attn"); void btn.offsetWidth; btn.classList.add("btn-attn"); }
      });
      // Back from checkout (page restored from the back/forward cache): ready to go again.
      window.addEventListener("pageshow", () => {
        if (this.$refs.go) this.$refs.go.classList.remove("is-going");
        const card = this.$root.closest("#ticket-panel");
        if (card) card.style.viewTransitionName = "";
      });
    },
    picked(t, e, n) {
      haptic();
      this.roll(t, 1);
      const from = e && e.currentTarget, to = this.$refs.total;
      if (reduceMotion || !from || !to || !from.animate) return;
      flyTo(from, to, "+" + this.digits(n), () => bump(to, 1.18));
      const row = from.closest("li");
      if (row) row.animate([{ backgroundColor: "color-mix(in oklab, var(--color-brand) 22%, transparent)" }, { backgroundColor: "transparent" }], { duration: 700, easing: "ease-out" });
    },
    roll(t, dir) {
      const el = this.$root.querySelector(`[data-qty="${t.id}"]`);
      if (el && el.animate && !reduceMotion) {
        el.animate([{ transform: `translateY(${dir * 70}%)`, opacity: 0 }, { transform: "none", opacity: 1 }], { duration: 320, easing: EXPO });
      }
    },
    countTo(to) {
      cancelAnimationFrame(this.frame);
      const from = this.shown, start = performance.now(), ms = 450;
      if (reduceMotion || from === to) { this.shown = to; return; }
      const step = (now) => {
        const k = Math.min(1, (now - start) / ms), ease = 1 - Math.pow(1 - k, 3);
        this.shown = Math.round(from + (to - from) * ease); // whole taka while counting
        if (k < 1) this.frame = requestAnimationFrame(step); else this.shown = to;
      };
      this.frame = requestAnimationFrame(step);
    },
    go(e) {
      if (reduceMotion || !this.count) return; // a plain submit
      e.preventDefault();
      const btn = this.$refs.go, card = this.$root.closest("#ticket-panel");
      btn.classList.remove("btn-alive", "btn-attn");
      btn.classList.add("is-going");
      if (card) card.style.viewTransitionName = "order-card"; // becomes the order summary on checkout
      haptic(12);
      document.documentElement.classList.add("is-loading");
      setTimeout(() => this.$root.submit(), 260);
    },
    digits(v) { return lang === "bn" ? String(v).replace(/[0-9]/g, (d) => "০১২৩৪৫৬৭৮৯"[d]) : String(v); },
    money(v) {
      const s = (Math.round(v * 100) / 100).toLocaleString("en-IN", { maximumFractionDigits: 2 });
      return "৳" + (lang === "bn" ? s.replace(/[0-9]/g, (d) => "০১২৩৪৫৬৭৮৯"[d]) : s);
    },
  }));

  /* The ticket pass: flips to show the details on the back (the QR stays on the front). */
  Alpine.data("ticketPass", () => ({
    flipped: false,
    init() { nxWakeLock(); },
    flip() { this.flipped = !this.flipped; haptic(); },
  }));

  /* Phones: a "Get tickets" bar at the bottom whenever the ticket panel is off-screen. */
  Alpine.data("ticketBar", (targetId = "tickets") => ({
    show: false,
    init() {
      const target = document.getElementById(targetId);
      if (!target || !("IntersectionObserver" in window)) return;
      new IntersectionObserver(([entry]) => { this.show = !entry.isIntersecting; }, { threshold: 0.05 }).observe(target);
    },
  }));

  /* Announcement bar a visitor can close; it stays closed until its text changes (`key`). */
  Alpine.data("announcement", (key) => ({
    open: true,
    init() { try { this.open = localStorage.getItem("nx-announcement") !== key; } catch (_) {} },
    close() { this.open = false; try { localStorage.setItem("nx-announcement", key); } catch (_) {} },
  }));

  /* Share / copy helpers */
  Alpine.data("share", (url, title) => ({
    copied: false,
    async native() {
      if (navigator.share) {
        try { await navigator.share({ title, url }); } catch (_) { /* dismissed */ }
      } else { this.copy(); }
    },
    async copy() {
      try { await navigator.clipboard.writeText(url); this.copied = true; setTimeout(() => (this.copied = false), 2000); } catch (_) {}
    },
  }));

  /* Minimal rich-text editor that writes sanitisable HTML into a hidden input. */
  Alpine.data("richEditor", (inputId, linkPrompt = "Link URL (https://…)") => ({
    init() {
      const input = document.getElementById(inputId);
      this.$refs.area.innerHTML = input.value || "";
      this.$refs.area.addEventListener("input", () => (input.value = this.$refs.area.innerHTML));
    },
    cmd(name, value = null) {
      this.$refs.area.focus();
      document.execCommand(name, false, value);
      document.getElementById(inputId).value = this.$refs.area.innerHTML;
    },
    link() {
      const url = prompt(linkPrompt);
      if (url && /^https?:\/\//.test(url)) this.cmd("createLink", url);
    },
  }));

  /* Django inline formset for ticket types: add rows from <template>, presets, soft delete. */
  Alpine.data("ticketBuilder", (prefix) => ({
    visible: 0,
    init() { this.visible = parseInt(this.total.value, 10) || 0; },
    get total() { return document.getElementById(`id_${prefix}-TOTAL_FORMS`); },
    add(values = {}) {
      const index = parseInt(this.total.value, 10);
      const html = this.$refs.empty.innerHTML.replaceAll("__prefix__", index);
      this.$refs.rows.insertAdjacentHTML("beforeend", html);
      this.total.value = index + 1;
      this.visible++;
      const row = this.$refs.rows.lastElementChild;
      for (const [field, value] of Object.entries(values)) {
        const el = row.querySelector(`[name="${prefix}-${index}-${field}"]`);
        if (!el) continue;
        if (el.type === "checkbox") el.checked = !!value; else el.value = value;
      }
      const order = row.querySelector(`[name="${prefix}-${index}-sort_order"]`);
      if (order) order.value = index;
      row.querySelector("input[type=text]")?.focus();
    },
    preset(rows) { rows.forEach((r) => this.add(r)); },
    remove(event) {
      const row = event.target.closest("[data-row]");
      const del = row.querySelector("input[name$='-DELETE']");
      if (del) del.checked = true;
      row.style.display = "none";
      this.visible--;
    },
  }));

  /* Hold timer on the pending-order page */
  Alpine.data("holdTimer", (iso) => ({
    left: "",
    expired: false,
    init() { this.tick(); this.t = setInterval(() => this.tick(), 1000); },
    destroy() { clearInterval(this.t); },
    tick() {
      const diff = Math.max(0, new Date(iso).getTime() - Date.now());
      this.expired = diff === 0;
      const m = Math.floor(diff / 6e4), s = Math.floor((diff % 6e4) / 1e3);
      this.left = `${m}:${String(s).padStart(2, "0")}`;
      if (this.expired) clearInterval(this.t);
    },
  }));
});

/* Keep screens awake while showing a QR at the gate (where supported). */
window.nxWakeLock = async () => {
  try { if ("wakeLock" in navigator) await navigator.wakeLock.request("screen"); } catch (_) {}
};

/* Motion & polish. Each part is independent and does nothing where it isn't supported. */
(() => {
  const root = document.documentElement;
  const motion = !reduceMotion;

  /* Scroll reveal: `.reveal` elements fade up as they come into view (see app.css). */
  if (root.classList.contains("reveal-ready")) {
    const io = new IntersectionObserver((entries) => {
      for (const e of entries) if (e.isIntersecting) { e.target.classList.add("is-in"); io.unobserve(e.target); }
    }, { rootMargin: "0px 0px -6% 0px", threshold: 0.08 });
    // (Where the browser ties these to the scroll itself, app.css ignores is-in.)
    const scan = (scope) => scope.querySelectorAll(":is(.reveal, .reveal-text, .reveal-pop, .reveal-scale, .words-scroll):not(.is-in)").forEach((el) => io.observe(el));
    scan(document);
    root.classList.add("reveal-live");
    document.addEventListener("htmx:afterSettle", (e) => scan(e.target));
  }

  /* Page to page, the picture you clicked travels with you: an event card's picture morphs into the
     event page's banner, a ticket row's picture into its pass. Pages that already name their own
     banner (.vt-banner) give the name up to the clicked picture for that one navigation. */
  const clearNames = () => document.querySelectorAll("[data-vt-img], .vt-banner").forEach((el) => { el.style.viewTransitionName = ""; });
  document.addEventListener("click", (e) => {
    const link = e.target instanceof Element && e.target.closest("a[data-vt]");
    if (!link || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    clearNames();
    const scope = link.closest("[data-vt-scope]");
    const img = link.querySelector("[data-vt-img]") || (scope && scope.querySelector("[data-vt-img]"));
    if (!img) return;
    document.querySelectorAll(".vt-banner").forEach((el) => { el.style.viewTransitionName = "none"; });
    img.style.viewTransitionName = "event-banner";
  });

  /* Filtering the events list: the result cards are named only while htmx's view transition runs,
     so they glide to their new places (html.vt-filter in app.css). Named all the time, every card
     would be captured on every page change. */
  document.addEventListener("htmx:beforeTransition", () => {
    root.classList.add("vt-filter");
    clearTimeout(root.vtFilterTimer);
    root.vtFilterTimer = setTimeout(() => root.classList.remove("vt-filter"), 900);
  });

  /* Figures count up from zero the first time they come into view ([data-count] on a plain-text
     element). The page's own text is the final value, so without motion nothing changes. */
  if (!calmMotion && "IntersectionObserver" in window) {
    const BN = "০১২৩৪৫৬৭৮৯";
    const latin = (s) => s.replace(/[০-৯]/g, (d) => String(BN.indexOf(d)));
    const counters = new IntersectionObserver((entries) => {
      for (const { target: el, isIntersecting } of entries) {
        if (!isIntersecting) continue;
        counters.unobserve(el);
        const text = el.textContent;
        const m = text.match(/[0-9০-৯][0-9০-৯,]*(?:\.[0-9০-৯]+)?/);
        if (!m) continue;
        const raw = latin(m[0]).replace(/,/g, "");
        const end = parseFloat(raw);
        if (!(end > 0)) continue;
        const decimals = (raw.split(".")[1] || "").length;
        const bangla = /[০-৯]/.test(m[0]), grouped = m[0].includes(",");
        const show = (v) => {
          const s = grouped ? v.toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals }) : v.toFixed(decimals);
          return bangla ? s.replace(/[0-9]/g, (d) => BN[d]) : s;
        };
        const before = text.slice(0, m.index), after = text.slice(m.index + m[0].length), t0 = performance.now();
        const tick = (now) => {
          const p = Math.min((now - t0) / 1100, 1);
          el.textContent = p < 1 ? before + show(end * (1 - Math.pow(2, -10 * p))) + after : text;
          if (p < 1) requestAnimationFrame(tick);
        };
        requestAnimationFrame(tick);
      }
    }, { threshold: 0.6 });
    document.querySelectorAll("[data-count]").forEach((el) => counters.observe(el));
  }

  /* The hero search box suggests searches in turn ([data-hints]); it waits while focused or typed in. */
  if (!calmMotion) document.querySelectorAll("input[data-hints]").forEach((input) => {
    let hints;
    try { hints = JSON.parse(input.dataset.hints); } catch (_) { return; }
    if (!Array.isArray(hints) || !hints.length) return;
    hints.unshift(input.placeholder);
    let i = 0;
    setInterval(() => {
      if (document.hidden || input.value || document.activeElement === input) return;
      input.classList.add("hint-swap");
      setTimeout(() => {
        i = (i + 1) % hints.length;
        input.placeholder = hints[i];
        input.classList.remove("hint-swap");
      }, 260);
    }, 2800);
  });

  /* Every press answers: a ripple spreads from where the finger or mouse went down. */
  if (motion) {
    const PRESSABLE = ".btn, .btn-primary, .btn-ghost, .btn-light, .btn-icon, .chip, .cat-pill, [data-ripple]";
    document.addEventListener("pointerdown", (e) => {
      const el = e.target instanceof Element && e.target.closest(PRESSABLE);
      if (!el || el.disabled || e.button > 0) return;
      const r = el.getBoundingClientRect(), size = Math.max(r.width, r.height) * 2.2;
      const ripple = document.createElement("span");
      ripple.className = "ripple";
      ripple.setAttribute("aria-hidden", "true");
      ripple.style.cssText = `width:${size}px;height:${size}px;left:${e.clientX - r.left - size / 2}px;top:${e.clientY - r.top - size / 2}px`;
      el.appendChild(ripple);
      ripple.addEventListener("animationend", () => ripple.remove());
    }, { passive: true });
  }

  /* Real mouse only: pictures tilt toward the pointer with a soft light following it ([data-tilt]),
     and the hero poster stack leans toward it, the cards further back moving more
     ([data-parallax]). One update per frame; everything settles back when the mouse leaves. */
  if (!calmMotion && window.matchMedia("(hover: hover) and (pointer: fine)").matches) {
    let frame = 0, last = null, tilted = null, stack = null;
    const settle = (el) => {
      el.classList.remove("is-tilting");
      el.style.setProperty("--rx", "0deg");
      el.style.setProperty("--ry", "0deg");
    };
    const calm = (el) => {
      el.classList.remove("is-live");
      el.style.setProperty("--px", "0");
      el.style.setProperty("--py", "0");
    };
    const update = () => {
      frame = 0;
      const target = last.target instanceof Element ? last.target : null;
      const tilt = target && target.closest("[data-tilt]");
      if (tilted && tilted !== tilt) settle(tilted);
      tilted = tilt;
      if (tilt) {
        const r = tilt.getBoundingClientRect(), max = +tilt.dataset.tilt || 7;
        const x = (last.clientX - r.left) / r.width - 0.5, y = (last.clientY - r.top) / r.height - 0.5;
        tilt.classList.add("is-tilting");
        tilt.style.setProperty("--rx", `${(-y * max).toFixed(2)}deg`);
        tilt.style.setProperty("--ry", `${(x * max).toFixed(2)}deg`);
        tilt.style.setProperty("--gx", `${Math.round(x * r.width)}px`);
        tilt.style.setProperty("--gy", `${Math.round(y * r.height)}px`);
      }
      const area = target && target.closest("[data-parallax]");
      const next = area && area.querySelector(".poster-stack");
      if (stack && stack !== next) calm(stack);
      stack = next;
      if (next) {
        const r = area.getBoundingClientRect();
        const x = (last.clientX - r.left) / r.width * 2 - 1, y = (last.clientY - r.top) / r.height * 2 - 1;
        next.classList.add("is-live");
        next.style.setProperty("--px", x.toFixed(3));
        next.style.setProperty("--py", y.toFixed(3));
        next.style.setProperty("--gx", `${Math.round(x * r.width / 2)}px`);
        next.style.setProperty("--gy", `${Math.round(y * r.height / 2)}px`);
      }
    };
    document.addEventListener("pointermove", (e) => {
      if (e.pointerType !== "mouse") return;
      last = e;
      if (!frame) frame = requestAnimationFrame(update);
    }, { passive: true });
    document.documentElement.addEventListener("mouseleave", () => {
      if (tilted) settle(tilted);
      if (stack) calm(stack);
      tilted = stack = null;
    });
  }

  /* Header: a soft pill glides to the link under the mouse. */
  const nav = document.querySelector("[data-nav-hover]");
  const pill = nav && nav.querySelector(".nav-hover");
  if (pill && window.matchMedia("(hover: hover)").matches) {
    nav.addEventListener("pointerover", (e) => {
      const a = e.target instanceof Element && e.target.closest("a");
      if (!a || !nav.contains(a)) return;
      pill.style.width = `${a.offsetWidth}px`;
      pill.style.transform = `translateX(${a.offsetLeft}px)`;
      pill.style.opacity = "1";
    });
    nav.addEventListener("pointerleave", () => { pill.style.opacity = "0"; });
  }

  /* Top loading bar: while htmx loads results, and after clicking through to another page. */
  const busy = (on) => root.classList.toggle("is-loading", on);
  const leaving = () => { busy(true); setTimeout(() => busy(false), 8000); }; // e.g. a download never leaves
  document.addEventListener("htmx:beforeRequest", (e) => {
    // Only what the visitor did (typing, clicking) - not background refreshes like the ticket panel's.
    const trigger = e.detail && e.detail.requestConfig && e.detail.requestConfig.triggeringEvent;
    if (trigger && trigger.isTrusted) busy(true);
  });
  document.addEventListener("htmx:afterRequest", () => busy(false));
  document.addEventListener("click", (e) => {
    const a = e.target instanceof Element && e.target.closest("a[href]");
    if (!a || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    if (a.target && a.target !== "_self") return;
    if (a.hasAttribute("download") || a.origin !== location.origin) return;
    if (a.pathname === location.pathname && a.search === location.search) return; // same page / #anchor
    leaving();
  });
  // htmx and Alpine cancel the forms they handle, so only real page submits get here.
  document.addEventListener("submit", (e) => { if (!e.defaultPrevented && !e.target.target) leaving(); });
  window.addEventListener("pageshow", () => { busy(false); clearNames(); }); // back/forward cache
})();
