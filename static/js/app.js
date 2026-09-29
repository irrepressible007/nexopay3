/* Nexopay — small Alpine components. Loaded before Alpine (both deferred). */
document.addEventListener("alpine:init", () => {
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

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

  /* Hero poster stack: on large screens the posters fan out and the front one is dealt away every
     few seconds. Phones show the same cards as a swipeable row (`stacked` stays false there). */
  Alpine.data("posterStack", (count, interval = 5500) => ({
    i: 0, out: null, timer: null, stacked: false,
    init() {
      const wide = window.matchMedia("(min-width: 1024px)");
      const update = () => { this.stacked = wide.matches; this.stacked && this.visible ? this.play() : this.pause(); };
      wide.addEventListener("change", update);
      // Only deal while the stack is on screen.
      this.visible = true;
      if ("IntersectionObserver" in window) {
        new IntersectionObserver(([e]) => { this.visible = e.isIntersecting; update(); }).observe(this.$el);
      }
      update();
    },
    depth(n) { return (n - this.i + count) % count; },
    play() {
      if (count < 2 || reduceMotion || !this.stacked) return;
      this.pause();
      this.timer = setInterval(() => this.show((this.i + 1) % count), interval);
    },
    pause() { clearInterval(this.timer); this.timer = null; },
    show(n) {
      if (n === this.i) return;
      this.out = this.i;
      this.i = n;
      clearTimeout(this.outTimer);
      this.outTimer = setTimeout(() => (this.out = null), 450);
    },
    go(n) { this.show(n); this.play(); },
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

  /* Ticket selection on the event page. `types` = [{id, price, max, remaining}] */
  Alpine.data("ticketPicker", (types, maxTotal, lang) => ({
    q: Object.fromEntries(types.map((t) => [t.id, 0])),
    types,
    get count() { return Object.values(this.q).reduce((a, b) => a + b, 0); },
    get total() { return this.types.reduce((sum, t) => sum + t.price * this.q[t.id], 0); },
    limit(t) { return Math.min(t.max, t.remaining, maxTotal - this.count + this.q[t.id]); },
    inc(t) { if (this.q[t.id] < this.limit(t)) this.q[t.id]++; },
    dec(t) { if (this.q[t.id] > 0) this.q[t.id]--; },
    toggle(t) { this.q[t.id] = this.q[t.id] ? 0 : Math.min(1, this.limit(t)); },
    init() {
      // The total gives a small bump whenever it changes.
      this.$watch("total", () => {
        const el = this.$refs.total;
        if (el && el.animate && !reduceMotion) {
          el.animate([{ transform: "scale(1.14)" }, { transform: "scale(1)" }], { duration: 280, easing: "cubic-bezier(.2,1.4,.4,1)" });
        }
      });
    },
    money(v) {
      const s = v.toLocaleString("en-IN", { maximumFractionDigits: 2 });
      return "৳" + (lang === "bn" ? s.replace(/[0-9]/g, (d) => "০১২৩৪৫৬৭৮৯"[d]) : s);
    },
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
  const motion = window.matchMedia("(prefers-reduced-motion: no-preference)").matches;

  /* Scroll reveal: `.reveal` elements fade up as they come into view (see app.css). */
  if (root.classList.contains("reveal-ready")) {
    const io = new IntersectionObserver((entries) => {
      for (const e of entries) if (e.isIntersecting) { e.target.classList.add("is-in"); io.unobserve(e.target); }
    }, { rootMargin: "0px 0px -6% 0px", threshold: 0.08 });
    const scan = (scope) => scope.querySelectorAll(".reveal:not(.is-in)").forEach((el) => io.observe(el));
    scan(document);
    root.classList.add("reveal-live");
    document.addEventListener("htmx:afterSettle", (e) => scan(e.target));
  }

  /* Event card -> event page: name the clicked card's picture so it morphs into the banner. */
  const clearNames = () => document.querySelectorAll("[data-vt-img]").forEach((el) => { el.style.viewTransitionName = ""; });
  document.addEventListener("click", (e) => {
    const link = e.target instanceof Element && e.target.closest("a[data-vt]");
    if (!link || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    clearNames();
    const img = link.querySelector("[data-vt-img]");
    if (img) img.style.viewTransitionName = "event-banner";
  });

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
