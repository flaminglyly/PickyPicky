import io
import socket
import ssl
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request
from urllib.error import URLError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'pc'))
import server
import cdn_transport

class CDNTests(unittest.TestCase):
    def test_known_redirect_only_and_no_lookalikes(self):
        for domain in cdn_transport.REDIRECT_SUFFIXES:
            url='https://edge.'+domain+'/media'
            with self.assertRaises(server.UnverifiedHost):server.validate(url,True)
            self.assertEqual(server.validate(url,True,redirected=True),url)
        for url in ('http://edge.jspcdn.cn/x','https://edge.jspcdn.cn.evil.test/x','https://user:pass@edge.jspcdn.cn/x','https://edge.jspcdn.cn:8443/x','https://unverified.test/x'):
            with self.assertRaises(server.UnverifiedHost):server.validate(url,True,redirected=True)

    def test_private_and_mixed_dns_blocked(self):
        for address in ('127.0.0.1','10.0.0.1','169.254.169.254','::1','198.18.0.1'):
            records=[(socket.AF_INET,socket.SOCK_STREAM,6,'',(address,443)),(socket.AF_INET,socket.SOCK_STREAM,6,'',('8.8.8.8',443))]
            with patch.object(socket,'getaddrinfo',return_value=records):
                with self.assertRaises(ValueError):cdn_transport.public_addresses('cdn.test',443)

    def test_proxy_synthetic_dns_uses_public_pinned_result(self):
        fake=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('198.18.0.8',443))]
        real=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('8.8.8.8',443))]
        with patch.object(socket,'getaddrinfo',return_value=fake),patch.object(cdn_transport,'encrypted_addresses',return_value=real) as resolver:
            self.assertEqual(cdn_transport.public_addresses('cdn.test',443),real)
            resolver.assert_called_once_with('cdn.test',443)
        with patch.object(socket,'getaddrinfo',return_value=fake),patch.object(cdn_transport,'encrypted_addresses',return_value=fake):
            with self.assertRaises(ValueError):cdn_transport.public_addresses('cdn.test',443)

    def test_socket_connects_to_checked_ip_and_uses_hostname_for_tls(self):
        from unittest.mock import MagicMock
        records=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('8.8.8.8',443))]
        raw=MagicMock();context=MagicMock()
        connection=cdn_transport.PublicHTTPSConnection('edge.jspcdn.cn',timeout=5,context=context)
        with patch.object(cdn_transport,'public_addresses',return_value=records),patch.object(socket,'socket',return_value=raw):
            connection.connect()
        raw.connect.assert_called_once_with(('8.8.8.8',443))
        context.wrap_socket.assert_called_once_with(raw,server_hostname='edge.jspcdn.cn')

    def test_redirect_hops_and_sensitive_headers(self):
        req=Request('https://cdn.qznovelvod.com/x',headers={'Range':'bytes=0-9','Cookie':'SECRET','Authorization':'SECRET'})
        req.media=True
        result=server.Redirects().redirect_request(req,None,302,'',{},'https://edge.jspcdn.cn/x')
        self.assertEqual(result.get_header('Range'),'bytes=0-9')
        self.assertNotIn('SECRET',str(result.headers))
        upgraded=server.Redirects().redirect_request(req,None,302,'',{},'http://edge.jspcdn.cn/x')
        self.assertEqual(upgraded.full_url,'https://edge.jspcdn.cn/x')
        req.cdn_hops=5
        with self.assertRaises(server.UnverifiedHost):server.Redirects().redirect_request(req,None,302,'',{},'https://edge.jspcdn.cn/x')

    def test_port_20002_only_for_ctydoh_trusted_https_redirect(self):
        url='https://edge.ctydoh.cn:20002/video'
        self.assertEqual(server.validate(url,True,redirected=True),url)
        for value,media,redirected in [(url,True,False),(url,False,True),('http://edge.ctydoh.cn:20002/video',True,True),('https://edge.jspcdn.cn:20002/video',True,True),('https://edge.ctydoh.cn:20003/video',True,True)]:
            with self.assertRaises(server.UnverifiedHost):server.validate(value,media,redirected=redirected)

    def test_ssl_read_failure_retries_same_range(self):
        class Response(io.BytesIO):
            status=206
            headers={'Content-Type':'video/mp4','Content-Range':'bytes 0-2/3'}
        class Broken(Response):
            def read(self,*args):raise ssl.SSLError(1,'TLS record failure')
        ranges=[]
        def fetch(*args,**kwargs):
            ranges.append(kwargs['extra_headers']['Range'])
            return Broken(b'') if len(ranges)==1 else Response(b'abc')
        with tempfile.TemporaryDirectory() as folder,patch.object(server,'ROOT',Path(folder)),patch.object(server,'fetch',side_effect=fetch),patch.object(server.time,'sleep'),patch.object(server,'verify_mp4',return_value=1):
            target=Path(folder)/'test.mp4'
            server._download_candidate({'kind':'direct','url':'https://cdn.qznovelvod.com/x'},{},target)
            self.assertEqual(target.read_bytes(),b'abc')
            self.assertEqual(ranges,[ranges[0]]*2)

    def test_failed_second_range_resumes_without_redownloading_first(self):
        class Response(io.BytesIO):
            status=206
            def __init__(self,body,content_range):
                super().__init__(body);self.headers={'Content-Type':'video/mp4','Content-Range':content_range}
        ranges=[]
        first=b'a'*(1024*1024)
        def fetch(*args,**kwargs):
            ranges.append(kwargs['extra_headers']['Range'])
            if len(ranges)==1:return Response(first,f'bytes 0-{len(first)-1}/{len(first)+1}')
            if len(ranges)==2:raise URLError(TimeoutError())
            return Response(b'b',f'bytes {len(first)}-{len(first)}/{len(first)+1}')
        with tempfile.TemporaryDirectory() as folder,patch.object(server,'ROOT',Path(folder)),patch.object(server,'fetch',side_effect=fetch),patch.object(server.time,'sleep'),patch.object(server,'verify_mp4',return_value=1):
            target=Path(folder)/'test.mp4'
            server._download_candidate({'kind':'direct','url':'https://cdn.qznovelvod.com/x'},{},target)
            self.assertEqual(target.read_bytes(),first+b'b')
            self.assertEqual(ranges[1],ranges[2])
            self.assertNotEqual(ranges[0],ranges[1])

if __name__=='__main__':unittest.main()
