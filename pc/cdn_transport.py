"""Restricted media redirects and public-address-only, TLS-verified transport."""
import json
import time
from urllib.parse import urlencode
from urllib.request import urlopen
import http.client
import ipaddress
import socket
import ssl
from urllib.request import HTTPSHandler

# Observed destinations are permitted only within a trusted media redirect chain.
REDIRECT_SUFFIXES=('idouyinvod.com','jspcdn.cn','qrstuvwxyzab.com','ctydoh.cn')

def observed_cdn(host):
    return any(host.endswith('.'+domain) for domain in REDIRECT_SUFFIXES)

_DNS_CACHE={}

def encrypted_addresses(host,port):
    cached=_DNS_CACHE.get((host,port))
    if cached and cached[0]>time.monotonic():return cached[1]
    # This fixed HTTPS resolver is used only for a proxy's synthetic DNS mapping.
    # TLS is verified by urlopen; no media URLs or credentials are sent here.
    with urlopen('https://dns.google/resolve?'+urlencode({'name':host,'type':'A'}),timeout=15) as response:
        data=json.loads(response.read(65537))
    addresses=[]
    for answer in data.get('Answer',[]):
        if answer.get('type')==1:
            address=ipaddress.ip_address(answer['data'])
            if not address.is_global:raise ValueError('加密 DNS 返回非公网地址，已停止请求。')
            addresses.append((socket.AF_INET,socket.SOCK_STREAM,6,'',(str(address),port)))
    if not addresses:raise ValueError('加密 DNS 未返回可用的公网地址。')
    if len(_DNS_CACHE)>256:_DNS_CACHE.clear()
    _DNS_CACHE[(host,port)]=(time.monotonic()+60,addresses)
    return addresses

def public_addresses(host,port):
    addresses=socket.getaddrinfo(host,port,type=socket.SOCK_STREAM)
    synthetic=ipaddress.ip_network('198.18.0.0/15')
    if addresses and all(ipaddress.ip_address(item[4][0]) in synthetic for item in addresses):
        addresses=encrypted_addresses(host,port)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError('CDN 解析到本机、内网或保留地址，已停止请求。')
    return addresses

class PublicHTTPSConnection(http.client.HTTPSConnection):
    def connect(self):
        # Resolve once and connect to these exact addresses, retaining TLS SNI and
        # certificate validation against the hostname rather than the numeric IP.
        if self._tunnel_host:raise ValueError('媒体连接不支持代理隧道。')
        addresses=public_addresses(self.host,self.port)
        last=None
        for family,kind,proto,_,address in addresses:
            raw=socket.socket(family,kind,proto)
            try:
                raw.settimeout(self.timeout)
                raw.connect(address)
                self.sock=self._context.wrap_socket(raw,server_hostname=self.host)
                return
            except OSError as error:
                raw.close();last=error
        raise last or OSError('CDN 连接失败')

class PublicHTTPSHandler(HTTPSHandler):
    def __init__(self):super().__init__(context=ssl.create_default_context())
    def https_open(self,req):
        return self.do_open(PublicHTTPSConnection,req,context=self._context,check_hostname=self._check_hostname)
