"""Redact host identity for anything that ships in the public site.

The survey's results are publishable; the list of reachable addresses is not.
IPv4 is masked to its /16 (first two octets), which keeps the provider/range
texture the charts rely on without naming a target. Hostnames are redacted
whole, since a name is as reachable as an address.
"""
import re

_IP = re.compile(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$')
_URL = re.compile(r'^(https?://)?([^:/]+)(:\d+)?')


def mask_host(value):
    m = _URL.match(value or '')
    if not m:
        return 'redacted'
    scheme, host, port = m.group(1) or '', m.group(2), m.group(3) or ''
    if _IP.match(host):
        a, b = host.split('.')[:2]
        host = f'{a}.{b}.x.x'
    else:
        host = 'named-host'
    return f'{scheme}{host}{port}'
