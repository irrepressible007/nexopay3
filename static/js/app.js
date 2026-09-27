/* Nexopay — small Alpine components. Loaded before Alpine (both deferred). */
document.addEventListener("alpine:init", () => {
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* Auto-advancing slider used by the hero and the featured card stack. */
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
    stackStyle(n) {
      const d = (n - this.i + count) % count;
      if (d > 2) return "opacity:0;transform:translateY(40px) scale(.85);z-index:0;pointer-events:none";
      const r = [-2, 4, -6][d];
      return `z-index:${10 - d};opacity:${1 - d * 0.25};transform:translateY(${d * 34}px) scale(${1 - d * 0.07}) rotate(${r}deg)`;
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
    money(v) {
      const s = v.toLocaleString("en-IN", { maximumFractionDigits: 2 });
      return "৳" + (lang === "bn" ? s.replace(/[0-9]/g, (d) => "০১২৩৪৫৬৭৮৯"[d]) : s);
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
  Alpine.data("richEditor", (inputId) => ({
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
      const url = prompt("Link URL (https://…)");
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
