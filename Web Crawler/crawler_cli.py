import argparse
import os
import sys
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from dns_resolver import resolve_dns_records, extract_hostname
from html_downloader import download_html, download_html_static

def print_banner():
    banner = """
============================================================
              SEO / AEO / GEO CRAWLER BOT
             [Phase 1.5 JS-Rendering Engine]
============================================================
"""
    print(banner)

def print_section(title: str):
    print(f"\n--- {title.upper()} ---")

def analyze_csr(html_content: str) -> bool:
    """
    Determines if a page is likely a Client-Side Rendered (CSR) app with an empty body.
    """
    if not html_content:
        return False
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        body = soup.find('body')
        if not body:
            return True
            
        # Decompose script, style, noscript, template, iframe tags to analyze actual content
        for tag in body(["script", "style", "noscript", "template", "iframe"]):
            tag.decompose()
            
        # Get remaining text content
        text = body.get_text(strip=True)
        # If visible body text is extremely short (under 120 characters), it's likely a CSR shell
        return len(text) < 120
    except Exception:
        return False

def main():
    print_banner()
    
    parser = argparse.ArgumentParser(description="DNS Resolver & HTML Downloader CLI for Crawler Bot")
    parser.add_argument("target", help="Domain name or URL to download HTML from (e.g., example.com or https://example.com/about)")
    parser.add_argument("-d", "--dns-domain", help="Separate domain to perform DNS resolution on (if different from target URL)")
    parser.add_argument("-o", "--output", help="Output file to save the HTML content", default="downloaded_page.html")
    parser.add_argument("-t", "--timeout", type=int, help="HTTP request timeout in seconds", default=10)
    parser.add_argument("-r", "--redirects", type=int, help="Maximum number of redirects allowed", default=5)
    parser.add_argument("--no-js", action="store_true", help="Disable JavaScript execution (run fast raw HTTP requests instead)")
    
    # Phase 2: Site Crawling options
    parser.add_argument("-m", "--max-pages", type=int, help="Maximum number of pages to crawl (set > 1 for site-wide crawling)", default=1)
    parser.add_argument("--max-depth", type=int, help="Maximum depth to crawl in site-wide mode", default=3)
    parser.add_argument("-p", "--delay", type=float, help="Politeness delay in seconds between page requests", default=1.0)
    parser.add_argument("--ignore-robots", action="store_true", help="Bypass robots.txt checks")
    parser.add_argument("--output-dir", help="Output directory to save crawled pages (used if max-pages > 1)", default="crawled_site")
    
    args = parser.parse_args()
    target = args.target.strip()
    
    # 1. DNS Resolution
    if args.dns_domain:
        dns_host = extract_hostname(args.dns_domain.strip())
        print(f"[*] Analyzing target URL: {target}")
        print(f"[*] Resolving separate DNS domain: {dns_host}")
    else:
        dns_host = extract_hostname(target)
        print(f"[*] Analyzing target URL: {target}")
        print(f"[*] Resolving DNS domain: {dns_host}")
    
    print_section("DNS Resolution Details")
    dns_info = resolve_dns_records(dns_host)
    
    if dns_info["resolved"]:
        print(f"[+] IPv4 Addresses: {', '.join(dns_info['ip_addresses']) if dns_info['ip_addresses'] else 'None'}")
        print(f"[+] IPv6 Addresses: {', '.join(dns_info['ipv6_addresses']) if dns_info['ipv6_addresses'] else 'None'}")
        if dns_info["cname"]:
            print(f"[+] CNAME Records: {', '.join(dns_info['cname'])}")
        if dns_info["ns"]:
            print(f"[+] Name Servers (NS): {', '.join(dns_info['ns'])}")
        if dns_info["mx"]:
            print("[+] Mail Servers (MX):")
            for mx in dns_info["mx"]:
                print(f"    - Preference {mx['preference']}: {mx['exchange']}")
        if dns_info["txt"]:
            print("[+] TXT Records:")
            for txt in dns_info["txt"]:
                print(f"    - {txt}")
    else:
        print(f"[-] DNS Resolution failed or returned no IP addresses.")
        for record_type, err in dns_info["errors"].items():
            print(f"    - {record_type} lookup error: {err}")
            
    # Determine the target URL to download
    url_to_download = target
    if not target.startswith(('http://', 'https://')):
        url_to_download = "https://" + target
        
    if args.max_pages > 1:
        print_section("HTML Downloading & Analysis (Site Crawl)")
        from crawler_engine import CrawlEngine
        engine = CrawlEngine(
            base_url=url_to_download,
            max_pages=args.max_pages,
            max_depth=args.max_depth,
            delay=args.delay,
            render_javascript=not args.no_js,
            ignore_robots=args.ignore_robots,
            output_dir=args.output_dir
        )
        engine.run()
        return
        
    print_section("HTML Downloading & Analysis")
    
    # Run static download first to analyze CSR vs SSR
    print(f"[*] Fetching static HTML shell: {url_to_download}")
    static_res = download_html_static(
        url_to_download, 
        timeout=args.timeout, 
        max_redirects=args.redirects
    )
    
    # HTTPS fallback check
    if not static_res["success"] and not target.startswith(('http://', 'https://')):
        fallback_url = "http://" + target
        print(f"[-] Static HTTPS failed: {static_res['error']}")
        print(f"[*] Retrying static HTTP: {fallback_url}")
        url_to_download = fallback_url
        static_res = download_html_static(
            url_to_download,
            timeout=args.timeout,
            max_redirects=args.redirects
        )
        
    if not static_res["success"]:
        print(f"[-] HTML Download failed: {static_res['error']}")
        return
        
    is_csr = analyze_csr(static_res["html"])
    final_res = static_res
    
    if is_csr:
        print(f"[!] CSR ALERT: Client-Side Rendering detected. The raw HTML body is empty of text content.")
        if args.no_js:
            print(f"    [!] Warning: JavaScript execution is disabled via --no-js. The saved HTML will remain empty.")
        else:
            print(f"    [*] Launching headless browser (Playwright) to execute JavaScript...")
            pw_res = download_html(
                url_to_download,
                timeout=args.timeout,
                max_redirects=args.redirects,
                render_javascript=True
            )
            if pw_res["success"]:
                print(f"    [+] Successfully executed JavaScript and fetched fully rendered body!")
                final_res = pw_res
            else:
                print(f"    [-] Playwright failed: {pw_res['error']}. Falling back to static shell.")
    else:
        print(f"[+] Server-Side Rendering (SSR) or static content detected.")
        if not args.no_js:
            print(f"    [*] Executing JavaScript via headless browser for thorough crawling...")
            pw_res = download_html(
                url_to_download,
                timeout=args.timeout,
                max_redirects=args.redirects,
                render_javascript=True
            )
            if pw_res["success"]:
                final_res = pw_res
            else:
                print(f"    [-] Playwright failed: {pw_res['error']}. Using static HTML.")
                
    # Display final download summary
    print(f"\n[+] Status Code: {final_res['status_code']}")
    print(f"[+] Final URL: {final_res['final_url']}")
    print(f"[+] Rendering Mode: {'JavaScript Rendered' if final_res.get('js_rendered') else 'Static Raw'}")
    
    if final_res["redirect_history"]:
        print("[+] Redirect Path:")
        chain = []
        for hop in final_res["redirect_history"]:
            chain.append(f"{hop['url']} ({hop['status_code']})")
        chain.append(f"{final_res['final_url']} ({final_res['status_code']})")
        print("    " + " -> \n    ".join(chain))
        
    html_len = len(final_res["html"])
    print(f"[+] Download Size: {html_len / 1024:.2f} KB")
    
    # Save content
    try:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(final_res["html"])
        print(f"[+] HTML successfully saved to: {os.path.abspath(args.output)}")
    except Exception as e:
        print(f"[-] Failed to save HTML: {e}")
        
    # Preview HTML content
    print("\n--- HTML CONTENT PREVIEW ---")
    lines = [line.strip() for line in final_res["html"].splitlines() if line.strip()]
    preview_lines = []
    for line in lines:
        if len(preview_lines) >= 15:
            break
        preview_lines.append(line)
    preview = "\n".join(preview_lines)
    print(preview)
    if len(lines) > 15:
        print("...")
    print("----------------------------")

if __name__ == "__main__":
    main()
