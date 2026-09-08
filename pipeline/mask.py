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


# A model name is free text the host chose, and hosts choose all sorts of
# things: the survey contains 324 model names that are IP addresses, mostly
# SSRF probe payloads like `8.8.4.4:9999/evil/model`. Two of them are the
# address of another host in this very survey. A model name is published
# verbatim, so it has to go through the same /16 masking as a host address or
# the model chart becomes a way to leak a target.
_EMBEDDED_IP = re.compile(r'\b(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\b')


def mask_model_name(name):
    """Mask any dotted-quad inside a model name to its /16."""
    if not name:
        return name
    def repl(m):
        octets = [int(m.group(i)) for i in range(1, 5)]
        if any(o > 255 for o in octets):
            return m.group(0)          # a version number, not an address
        return f'{m.group(1)}.{m.group(2)}.x.x'
    return _EMBEDDED_IP.sub(repl, name)
