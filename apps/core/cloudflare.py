"""
Behind Cloudflare's proxy every request arrives from a Cloudflare address, so
per-visitor rate limits (login, contact form, checkout) would treat all
visitors as one. When — and only when — the request really comes from
Cloudflare, use the visitor address Cloudflare reports.

Ranges: https://www.cloudflare.com/ips/ (they change rarely).
"""
import ipaddress

CLOUDFLARE_RANGES = [
    ipaddress.ip_network(net)
    for net in (
        "173.245.48.0/20", "103.21.244.0/22", "103.22.200.0/22", "103.31.4.0/22", "141.101.64.0/18",
        "108.162.192.0/18", "190.93.240.0/20", "188.114.96.0/20", "197.234.240.0/22", "198.41.128.0/17",
        "162.158.0.0/15", "104.16.0.0/13", "104.24.0.0/14", "172.64.0.0/13", "131.0.72.0/22",
        "2400:cb00::/32", "2606:4700::/32", "2803:f800::/32", "2405:b500::/32", "2405:8100::/32",
        "2a06:98c0::/29", "2c0f:f248::/32",
    )
]


def is_cloudflare(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(ip in net for net in CLOUDFLARE_RANGES)


class CloudflareRealIPMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        visitor = request.META.get("HTTP_CF_CONNECTING_IP", "").strip()
        if visitor and is_cloudflare(request.META.get("REMOTE_ADDR", "")):
            try:
                ipaddress.ip_address(visitor)
            except ValueError:
                pass
            else:
                request.META["REMOTE_ADDR"] = visitor
        return self.get_response(request)
