import os
import time
import json
import logging
from urllib.parse import urlparse, urljoin, urlunparse
from urllib.robotparser import RobotFileParser
import requests
from bs4 import BeautifulSoup
from html_downloader import download_html

logger = logging.getLogger(__name__)

def extract_links(html_content: str, base_url: str) -> list:
    """
    Extracts all unique anchor links (href) from html_content,
    resolves them to absolute URLs using base_url, removes fragments,
    and returns a list of unique absolute HTTP/HTTPS URLs.
    """
    if not html_content:
        return []
    
    links = set()
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href'].strip()
            if not href:
                continue
            
            # Resolve relative link to absolute link
            absolute_url = urljoin(base_url, href)
            
            # Parse URL to clean it
            parsed = urlparse(absolute_url)
            
            # Only allow HTTP and HTTPS schemes
            if parsed.scheme not in ('http', 'https'):
                continue
                
            # Strip fragment
            cleaned_url = urlunparse((
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                parsed.params,
                parsed.query,
                '' # no fragment
            ))
            
            links.add(cleaned_url)
    except Exception as e:
        logger.error(f"Error extracting links from URL {base_url}: {e}")
        
    return list(links)

def is_internal_url(url: str, base_url: str) -> bool:
    """
    Checks if a URL belongs to the same domain (netloc) as the base_url,
    or is a subdomain of the base_url domain.
    """
    try:
        base_parsed = urlparse(base_url)
        url_parsed = urlparse(url)
        
        base_host = base_parsed.hostname
        url_host = url_parsed.hostname
        
        if not base_host or not url_host:
            return False
            
        base_host = base_host.lower()
        url_host = url_host.lower()
        
        # Exact match
        if base_host == url_host:
            return True
            
        # Subdomain match: e.g. blog.tensorschool.com ends with .tensorschool.com
        if url_host.endswith('.' + base_host):
            return True
            
        return False
    except Exception:
        return False

class RobotsCache:
    def __init__(self):
        self.parsers = {} # netloc -> RobotFileParser
        
    def can_fetch(self, url: str, user_agent: str = "*", timeout: int = 5) -> bool:
        """
        Checks if the crawler is allowed to fetch the URL based on robots.txt.
        Caches the parsed robots.txt by netloc.
        """
        try:
            parsed = urlparse(url)
            netloc = parsed.netloc.lower()
            scheme = parsed.scheme
            
            if not netloc or scheme not in ('http', 'https'):
                return True
                
            if netloc not in self.parsers:
                robots_url = f"{scheme}://{netloc}/robots.txt"
                parser = RobotFileParser()
                parser.set_url(robots_url)
                try:
                    headers = {'User-Agent': user_agent}
                    resp = requests.get(robots_url, headers=headers, timeout=timeout)
                    if resp.status_code in (401, 403):
                        # Block everything if access to robots.txt is denied
                        parser.disallow_all = True
                    elif resp.status_code >= 400:
                        # Allow all if robots.txt does not exist
                        parser.allow_all = True
                    else:
                        content = resp.text
                        parser.parse(content.splitlines())
                except Exception as e:
                    logger.debug(f"Failed to fetch robots.txt from {robots_url}: {e}. Defaulting to allow all.")
                    parser.allow_all = True
                self.parsers[netloc] = parser
                
            return self.parsers[netloc].can_fetch(user_agent, url)
        except Exception as e:
            logger.warning(f"Error checking robots.txt for {url}: {e}")
            return True

class CrawlEngine:
    def __init__(
        self,
        base_url: str,
        max_pages: int = 10,
        max_depth: int = 3,
        delay: float = 1.0,
        render_javascript: bool = True,
        ignore_robots: bool = False,
        output_dir: str = "crawled_site",
        user_agent: str = None
    ):
        self.base_url = base_url
        self.max_pages = max_pages
        self.max_depth = max_depth
        self.delay = delay
        self.render_javascript = render_javascript
        self.ignore_robots = ignore_robots
        self.output_dir = output_dir
        self.user_agent = user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
        self.robots_cache = RobotsCache()
        
        # State
        self.visited = {} # url -> dict
        self.last_request_time = 0.0

    def _save_page(self, url: str, html_content: str) -> str:
        """
        Saves page content to a file mapping the URL path structure.
        """
        parsed = urlparse(url)
        path = parsed.path.strip("/")
        
        if not path:
            filename = "index.html"
        else:
            filename = "".join(c if c.isalnum() or c in ("-", "_", ".") else "_" for c in path)
            if not filename.endswith(".html"):
                filename += ".html"
                
        # Handle duplicates to prevent overwriting
        base, ext = os.path.splitext(filename)
        counter = 1
        final_filename = filename
        while os.path.exists(os.path.join(self.output_dir, final_filename)):
            final_filename = f"{base}_{counter}{ext}"
            counter += 1
            
        dest_path = os.path.join(self.output_dir, final_filename)
        with open(dest_path, "w", encoding="utf-8") as f:
            f.write(html_content)
            
        return os.path.abspath(dest_path)

    def run(self) -> dict:
        from collections import deque
        
        # Normalize target url
        parsed_base = urlparse(self.base_url)
        if not parsed_base.scheme:
            self.base_url = "https://" + self.base_url
            parsed_base = urlparse(self.base_url)
            
        start_url = urlunparse((
            parsed_base.scheme,
            parsed_base.netloc,
            parsed_base.path or "/",
            parsed_base.params,
            parsed_base.query,
            ''
        ))
        
        queue = deque([(start_url, 0)])
        
        # Ensure output directory exists
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)
            
        print(f"[*] Starting site-wide crawl at: {start_url}")
        print(f"[*] Limits: max_pages={self.max_pages}, max_depth={self.max_depth}, politeness_delay={self.delay}s")
        
        pages_crawled_count = 0
        
        while queue and pages_crawled_count < self.max_pages:
            url, depth = queue.popleft()
            
            if url in self.visited:
                continue
                
            # Depth limit check
            if depth > self.max_depth:
                continue
                
            # Robots.txt check
            if not self.ignore_robots:
                if not self.robots_cache.can_fetch(url, self.user_agent):
                    print(f"[-] Robots.txt blocks crawling URL: {url}")
                    self.visited[url] = {
                        "status_code": None,
                        "success": False,
                        "error": "Blocked by robots.txt",
                        "depth": depth,
                        "file_path": None
                    }
                    continue
                    
            # Politeness delay execution
            time_since_last = time.time() - self.last_request_time
            if time_since_last < self.delay and pages_crawled_count > 0:
                sleep_time = self.delay - time_since_last
                time.sleep(sleep_time)
                
            print(f"[*] [{pages_crawled_count + 1}/{self.max_pages}] Crawling (depth={depth}): {url}")
            self.last_request_time = time.time()
            
            try:
                res = download_html(
                    url,
                    timeout=10,
                    render_javascript=self.render_javascript,
                    user_agent=self.user_agent
                )
                
                status_code = res.get("status_code")
                success = res.get("success", False)
                error = res.get("error")
                final_url = res.get("final_url", url)
                html_content = res.get("html")
                
                file_path = None
                if success and html_content:
                    file_path = self._save_page(url, html_content)
                    pages_crawled_count += 1
                    
                    if depth < self.max_depth:
                        extracted = extract_links(html_content, final_url)
                        for link in extracted:
                            if is_internal_url(link, start_url):
                                if link not in self.visited and not any(item[0] == link for item in queue):
                                    queue.append((link, depth + 1))
                                    
                self.visited[url] = {
                    "status_code": status_code,
                    "success": success,
                    "error": error,
                    "depth": depth,
                    "file_path": file_path,
                    "final_url": final_url,
                    "js_rendered": res.get("js_rendered", False)
                }
                
            except Exception as e:
                logger.error(f"Failed to crawl URL {url}: {e}")
                self.visited[url] = {
                    "status_code": None,
                    "success": False,
                    "error": f"Exception: {e}",
                    "depth": depth,
                    "file_path": None
                }
                
        # Generate summary report
        report_path = os.path.join(self.output_dir, "crawl_report.json")
        try:
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump({
                    "start_url": start_url,
                    "max_pages": self.max_pages,
                    "max_depth": self.max_depth,
                    "pages_crawled": pages_crawled_count,
                    "crawled_urls": self.visited
                }, f, indent=2)
            print(f"[+] Crawl complete. Report saved to: {os.path.abspath(report_path)}")
        except Exception as e:
            print(f"[-] Failed to save crawl report: {e}")
            
        return self.visited
