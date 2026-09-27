"""
Layout audit: loads every page at common screen sizes and reports anything that
overflows the screen or its own box. Run against a dev server after
`python manage.py seed_stress` to test worst-case admin content.

    python tools/layout_audit.py [--base http://127.0.0.1:8000] [--shots out_dir] [--only mobile]

Requires `pip install playwright` and Microsoft Edge or Chrome installed.
"""
import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

VIEWPORTS = {
    "phone-320": (320, 568, True), "phone-360": (360, 740, True), "phone-375": (375, 667, True),
    "phone-390": (390, 844, True), "phone-414": (414, 896, True), "phone-landscape": (844, 390, True),
    "tablet-768": (768, 1024, True), "tablet-820": (820, 1180, True), "tablet-landscape": (1024, 768, False),
    "laptop-1280": (1280, 800, False), "laptop-1366": (1366, 768, False), "desktop-1440": (1440, 900, False),
    "desktop-1920": (1920, 1080, False), "desktop-2560": (2560, 1440, False),
}

PUBLIC = ["/", "/bn/", "/events/", "/bn/events/", "/events/stress-event/", "/bn/events/stress-event/", "/faq/",
          "/p/about/", "/contact/", "/accounts/login/", "/bn/accounts/signup/", "/accounts/password/reset/",
          "/organizers/apply/", "/events/?category=stress-category&status=live"]
BUYER = ["/checkout/stress-event/?q_{tt}=2", "/account/tickets/", "/account/orders/", "/account/profile/",
         "/account/tickets/{code}/", "/bn/account/tickets/{code}/", "/orders/{order}/"]
ORGANIZER = ["/organizers/dashboard/", "/organizers/events/new/", "/organizers/events/stress-event/",
             "/organizers/events/stress-event/edit/", "/scan/", "/scan/stress-event/"]

CHECK_JS = """
() => {
  const vw = document.documentElement.clientWidth;
  const clipped = (el) => {
    for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
      const s = getComputedStyle(p);
      if (['hidden', 'clip', 'auto', 'scroll'].includes(s.overflowX)) return true;
    }
    return false;
  };
  const visible = (el) => {
    const s = getComputedStyle(el);
    if (s.display === 'none' || s.visibility === 'hidden' || +s.opacity === 0) return false;
    const r = el.getBoundingClientRect();
    return r.width > 1 && r.height > 1;
  };
  const describe = (el) => {
    const cls = (typeof el.className === 'string' ? el.className : '').split(/\\s+/).slice(0, 4).join('.');
    const text = (el.innerText || '').trim().slice(0, 50).replace(/\\s+/g, ' ');
    return `${el.tagName.toLowerCase()}${cls ? '.' + cls : ''} "${text}"`;
  };
  const issues = [];
  for (const el of document.body.querySelectorAll('*')) {
    if (['SCRIPT', 'STYLE', 'svg', 'SYMBOL', 'PATH', 'USE', 'TEMPLATE'].includes(el.tagName) || !visible(el)) continue;
    if (el.closest('svg') || el.closest('.sr-only')) continue;
    const r = el.getBoundingClientRect();
    if ((r.right > vw + 1 || r.left < -1) && !clipped(el)) {
      issues.push(`off-screen (${Math.round(r.left)}..${Math.round(r.right)} of ${vw}): ${describe(el)}`);
      continue;
    }
    const s = getComputedStyle(el);
    const textish = el.childNodes.length && [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
    if (textish && s.overflowX === 'visible' && s.display !== 'inline' && el.scrollWidth > el.clientWidth + 2
        && el.clientWidth > 0 && !clipped(el)) {
      issues.push(`text spills out of its box (${el.scrollWidth} > ${el.clientWidth}): ${describe(el)}`);
    }
    // A short single word (price, badge, button label) squeezed onto several lines.
    for (const node of el.childNodes) {
      const word = node.nodeType === 3 ? node.textContent.trim() : '';
      if (!word || word.length > 14 || /\\s/.test(word)) continue;
      const range = document.createRange();
      range.selectNodeContents(node);
      const lines = new Set([...range.getClientRects()].filter(rc => rc.width > 0).map(rc => Math.round(rc.top)));
      if (lines.size > 1) issues.push(`short text squeezed onto ${lines.size} lines: ${describe(el)}`);
    }
  }
  return [...new Set(issues)].slice(0, 12);
}
"""


def login(context, base, email, password):
    page = context.new_page()
    page.goto(f"{base}/accounts/login/")
    page.fill("#id_login", email)
    page.fill("#id_password", password)
    page.click("form button.btn-primary")
    page.wait_for_load_state("networkidle")
    page.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--shots", default="")
    ap.add_argument("--only", default="", help="substring filter on viewport names, e.g. phone")
    ap.add_argument("--ids", default="", help='JSON {"tt":..,"code":..,"order":..} for buyer pages')
    args = ap.parse_args()
    ids = json.loads(args.ids) if args.ids else {}
    shots = Path(args.shots) if args.shots else None
    if shots:
        shots.mkdir(parents=True, exist_ok=True)

    total = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge")
        for vp_name, (w, h, mobile) in VIEWPORTS.items():
            if args.only and args.only not in vp_name:
                continue
            groups = [(None, PUBLIC)]
            if ids:
                groups.append((("stress-buyer@example.com", "stress12345!"), [u.format(**ids) for u in BUYER]))
            groups.append((("stress-organizer@example.com", "stress12345!"), ORGANIZER))
            for creds, urls in groups:
                ctx = browser.new_context(viewport={"width": w, "height": h}, is_mobile=mobile, has_touch=mobile,
                                          device_scale_factor=1)
                if creds:
                    login(ctx, args.base, *creds)
                page = ctx.new_page()
                for url in urls:
                    response = page.goto(args.base + url, wait_until="networkidle")
                    page.wait_for_timeout(250)
                    status = response.status if response else 0
                    issues = page.evaluate(CHECK_JS)
                    if status >= 400:
                        issues = [f"HTTP {status}"] + issues
                    if issues:
                        total += len(issues)
                        print(f"\n[{vp_name}] {url}")
                        for issue in issues:
                            print("   -", issue)
                    if shots and vp_name in ("phone-360", "laptop-1366", "phone-landscape"):
                        safe = url.strip("/").replace("/", "_").replace("?", "_").replace("=", "-").replace("&", "_") or "home"
                        page.screenshot(path=str(shots / f"{vp_name}__{safe}.png"), full_page=True)
                ctx.close()
        browser.close()
    print(f"\n{'OK — no layout problems found' if total == 0 else f'{total} problem(s) found'}")
    sys.exit(1 if total else 0)


if __name__ == "__main__":
    main()
