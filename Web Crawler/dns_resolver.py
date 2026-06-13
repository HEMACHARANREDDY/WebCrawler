import socket
from urllib.parse import urlparse
import logging

# Set up simple logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

try:
    import dns.resolver
    HAS_DNSPYTHON = True
except ImportError:
    HAS_DNSPYTHON = False
    logger.warning("dnspython is not installed. Fallback to basic socket resolution will be used.")

def extract_hostname(url_or_domain: str) -> str:
    """
    Extracts the clean hostname from a given URL or domain string.
    e.g., 'https://www.example.com/about?arg=1' -> 'www.example.com'
          'example.com' -> 'example.com'
    """
    url_or_domain = url_or_domain.strip()
    if not url_or_domain:
        return ""
        
    # Check if it looks like a URL (has scheme or starts with //)
    # If not, prepending 'http://' allows urlparse to correctly extract netloc
    if not url_or_domain.startswith(('http://', 'https://', '//')):
        # Check if there is a slash after the domain
        parsed_url = 'http://' + url_or_domain
    else:
        parsed_url = url_or_domain

    try:
        parsed = urlparse(parsed_url)
        hostname = parsed.hostname or parsed.path.split('/')[0]
        # Remove port if present
        if ':' in hostname:
            hostname = hostname.split(':')[0]
        return hostname.lower()
    except Exception as e:
        logger.error(f"Error parsing hostname from '{url_or_domain}': {e}")
        # Return fallback clean string
        return url_or_domain.split('/')[0].split(':')[0].lower()

def resolve_dns_records(domain: str) -> dict:
    """
    Resolves various DNS records (A, AAAA, MX, TXT, NS, CNAME) for the given domain.
    Returns a dictionary structured with record arrays and error logs.
    """
    hostname = extract_hostname(domain)
    
    results = {
        "hostname": hostname,
        "resolved": False,
        "ip_addresses": [],
        "ipv6_addresses": [],
        "cname": [],
        "mx": [],
        "txt": [],
        "ns": [],
        "errors": {}
    }
    
    if not hostname:
        results["errors"]["validation"] = "Empty hostname provided."
        return results

    # Try resolving via dnspython if available
    if HAS_DNSPYTHON:
        # A records (IPv4)
        try:
            answers = dns.resolver.resolve(hostname, 'A')
            results["ip_addresses"] = [rdata.address for rdata in answers]
        except Exception as e:
            results["errors"]["A"] = str(e)
            
        # AAAA records (IPv6)
        try:
            answers = dns.resolver.resolve(hostname, 'AAAA')
            results["ipv6_addresses"] = [rdata.address for rdata in answers]
        except Exception as e:
            results["errors"]["AAAA"] = str(e)
            
        # CNAME records
        try:
            answers = dns.resolver.resolve(hostname, 'CNAME')
            results["cname"] = [str(rdata.target).rstrip('.') for rdata in answers]
        except Exception as e:
            # Root domains usually don't have CNAME records, normal behavior
            pass
            
        # MX records
        try:
            answers = dns.resolver.resolve(hostname, 'MX')
            results["mx"] = [
                {"preference": rdata.preference, "exchange": str(rdata.exchange).rstrip('.')}
                for rdata in answers
            ]
        except Exception as e:
            results["errors"]["MX"] = str(e)
            
        # TXT records
        try:
            answers = dns.resolver.resolve(hostname, 'TXT')
            results["txt"] = [
                "".join([s.decode('utf-8') if isinstance(s, bytes) else str(s) for s in rdata.strings])
                for rdata in answers
            ]
        except Exception as e:
            results["errors"]["TXT"] = str(e)
            
        # NS records
        try:
            answers = dns.resolver.resolve(hostname, 'NS')
            results["ns"] = [str(rdata.target).rstrip('.') for rdata in answers]
        except Exception as e:
            results["errors"]["NS"] = str(e)

    # Fallback to standard socket resolution if A/AAAA list is empty
    if not results["ip_addresses"] and not results["ipv6_addresses"]:
        try:
            addr_infos = socket.getaddrinfo(hostname, None)
            for info in addr_infos:
                family, _, _, _, sockaddr = info
                ip = sockaddr[0]
                if family == socket.AF_INET:
                    if ip not in results["ip_addresses"]:
                        results["ip_addresses"].append(ip)
                elif family == socket.AF_INET6:
                    if ip not in results["ipv6_addresses"]:
                        results["ipv6_addresses"].append(ip)
        except Exception as e:
            results["errors"]["socket_fallback"] = str(e)

    # Determine if resolution succeeded (at least one IP found)
    if results["ip_addresses"] or results["ipv6_addresses"]:
        results["resolved"] = True
        
    return results

if __name__ == "__main__":
    import sys
    test_domain = sys.argv[1] if len(sys.argv) > 1 else "google.com"
    print(f"Resolving DNS for: {test_domain}")
    import json
    print(json.dumps(resolve_dns_records(test_domain), indent=2))
