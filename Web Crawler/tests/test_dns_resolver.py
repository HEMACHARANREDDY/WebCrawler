import unittest
from unittest.mock import patch, MagicMock
import sys
import os

# Adjust path to find the module
sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

from dns_resolver import extract_hostname, resolve_dns_records

class TestDNSResolver(unittest.TestCase):
    def test_extract_hostname(self):
        self.assertEqual(extract_hostname("https://example.com/about?q=1"), "example.com")
        self.assertEqual(extract_hostname("http://www.sub.example.com:8080/path"), "www.sub.example.com")
        self.assertEqual(extract_hostname("example.org/path/to/page"), "example.org")
        self.assertEqual(extract_hostname("  https://my-domain.co.uk/   "), "my-domain.co.uk")
        self.assertEqual(extract_hostname(""), "")
        self.assertEqual(extract_hostname("localhost"), "localhost")

    @patch('dns.resolver.resolve')
    def test_resolve_dns_records_success(self, mock_resolve):
        # Setup mocks for different record types
        mock_a = MagicMock()
        mock_a.address = "192.0.2.1"
        
        mock_aaaa = MagicMock()
        mock_aaaa.address = "2001:db8::1"
        
        mock_mx = MagicMock()
        mock_mx.preference = 10
        mock_mx.exchange = "mail.example.com."
        
        mock_txt = MagicMock()
        mock_txt.strings = [b"v=spf1 include:_spf.google.com ~all"]
        
        mock_ns = MagicMock()
        mock_ns.target = "ns1.example.com."
        
        def resolve_side_effect(qname, rdtype):
            if rdtype == 'A':
                return [mock_a]
            elif rdtype == 'AAAA':
                return [mock_aaaa]
            elif rdtype == 'MX':
                return [mock_mx]
            elif rdtype == 'TXT':
                return [mock_txt]
            elif rdtype == 'NS':
                return [mock_ns]
            else:
                raise Exception("Record not mocked")
                
        mock_resolve.side_effect = resolve_side_effect
        
        res = resolve_dns_records("example.com")
        
        self.assertTrue(res["resolved"])
        self.assertIn("192.0.2.1", res["ip_addresses"])
        self.assertIn("2001:db8::1", res["ipv6_addresses"])
        self.assertEqual(res["mx"][0]["exchange"], "mail.example.com")
        self.assertEqual(res["txt"][0], "v=spf1 include:_spf.google.com ~all")
        self.assertEqual(res["ns"][0], "ns1.example.com")
        
    @patch('dns.resolver.resolve')
    @patch('socket.getaddrinfo')
    def test_resolve_dns_records_fallback(self, mock_getaddrinfo, mock_resolve):
        # Simulate dnspython failing completely (raising exception)
        mock_resolve.side_effect = Exception("DNS Resolution Error")
        
        # Simulate socket.getaddrinfo succeeding
        mock_getaddrinfo.return_value = [
            (2, 1, 0, '', ('198.51.100.2', 0)),  # IPv4
            (23, 1, 0, '', ('2001:db8::2', 0, 0, 0))  # IPv6
        ]
        
        res = resolve_dns_records("fallback-example.com")
        
        self.assertTrue(res["resolved"])
        self.assertIn("198.51.100.2", res["ip_addresses"])
        self.assertIn("2001:db8::2", res["ipv6_addresses"])
        self.assertIn("A", res["errors"])  # should contain dnspython A record error

if __name__ == '__main__':
    unittest.main()
