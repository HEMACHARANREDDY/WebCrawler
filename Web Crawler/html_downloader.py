import requests
import logging

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# Dynamic check if Playwright library is available
try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

def download_html_static(
    url: str, 
    timeout: int = 10, 
    max_redirects: int = 5, 
    user_agent: str = None,
    max_size_bytes: int = 5 * 1024 * 1024
) -> dict:
    """
    Downloads raw HTML content using requests without JS execution.
    """
    headers = {
        'User-Agent': user_agent or DEFAULT_USER_AGENT,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
    }
    
    result = {
        "url": url,
        "final_url": url,
        "status_code": None,
        "html": None,
        "headers": {},
        "redirect_history": [],
        "error": None,
        "success": False,
        "js_rendered": False
    }
    
    session = requests.Session()
    session.max_redirects = max_redirects
    
    try:
        response = session.get(url, headers=headers, timeout=timeout, stream=True, allow_redirects=True)
        
        if response.history:
            for resp in response.history:
                result["redirect_history"].append({
                    "url": resp.url,
                    "status_code": resp.status_code
                })
                
        result["final_url"] = response.url
        result["status_code"] = response.status_code
        result["headers"] = dict(response.headers)
        
        content_type = response.headers.get('content-type', '').lower()
        if 'text/html' not in content_type and 'application/xhtml+xml' not in content_type:
            response.close()
            result["error"] = f"Unsupported Content-Type: {content_type}. Only HTML is supported."
            return result
            
        content_chunks = []
        bytes_downloaded = 0
        
        for chunk in response.iter_content(chunk_size=8192, decode_unicode=True):
            if chunk:
                if isinstance(chunk, bytes):
                    chunk = chunk.decode('utf-8', errors='replace')
                
                content_chunks.append(chunk)
                bytes_downloaded += len(chunk.encode('utf-8', errors='replace'))
                
                if bytes_downloaded > max_size_bytes:
                    response.close()
                    result["error"] = f"File size exceeded maximum limit of {max_size_bytes} bytes."
                    return result
                    
        result["html"] = "".join(content_chunks)
        result["success"] = True
        
    except requests.exceptions.TooManyRedirects:
        result["error"] = f"Redirect loop or exceeded max redirects limit of {max_redirects}."
    except requests.exceptions.Timeout:
        result["error"] = f"Connection timed out after {timeout} seconds."
    except requests.exceptions.ConnectionError as e:
        result["error"] = f"Connection error occurred: {e}"
    except requests.exceptions.HTTPError as e:
        result["error"] = f"HTTP error occurred: {e}"
    except Exception as e:
        result["error"] = f"An unexpected error occurred during request: {e}"
    finally:
        session.close()
        
    return result

def download_html(
    url: str, 
    timeout: int = 10, 
    max_redirects: int = 5, 
    user_agent: str = None,
    max_size_bytes: int = 5 * 1024 * 1024,
    render_javascript: bool = True
) -> dict:
    """
    Downloads HTML content from a URL.
    Attempts JavaScript rendering via Playwright if enabled, otherwise falls back to static requests download.
    """
    if render_javascript and HAS_PLAYWRIGHT:
        logger.info(f"Attempting Javascript rendered download via Playwright for: {url}")
        
        result = {
            "url": url,
            "final_url": url,
            "status_code": None,
            "html": None,
            "headers": {},
            "redirect_history": [],
            "error": None,
            "success": False,
            "js_rendered": True
        }
        
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context_kwargs = {"user_agent": user_agent or DEFAULT_USER_AGENT}
                context = browser.new_context(**context_kwargs)
                page = context.new_page()
                
                responses = []
                page.on("response", lambda resp: responses.append(resp))
                
                try:
                    # We wait for 'networkidle' to allow JS rendering processes to finalize.
                    # Failures here fallback to normal DOM content loading.
                    main_response = page.goto(url, wait_until="networkidle", timeout=timeout * 1000)
                except Exception as e:
                    logger.warning(f"Playwright 'networkidle' timed out. Retrying with 'load': {e}")
                    try:
                        main_response = page.goto(url, wait_until="load", timeout=timeout * 1000)
                    except Exception as e_inner:
                        logger.error(f"Playwright load failed: {e_inner}")
                        main_response = None
                
                result["final_url"] = page.url
                
                if main_response:
                    result["status_code"] = main_response.status
                    result["headers"] = dict(main_response.headers)
                    
                    # Inspect content type
                    content_type = main_response.headers.get('content-type', '').lower()
                    if 'text/html' not in content_type and 'application/xhtml+xml' not in content_type:
                        browser.close()
                        result["error"] = f"Unsupported Content-Type: {content_type}. Only HTML is supported."
                        result["js_rendered"] = True
                        return result
                elif responses:
                    for r in responses:
                        if r.url == page.url or r.url == url:
                            result["status_code"] = r.status
                            result["headers"] = dict(r.headers)
                            break
                    if not result["status_code"]:
                        result["status_code"] = responses[-1].status
                else:
                    result["status_code"] = 200
                
                # Fetch redirect details
                for r in responses:
                    if 300 <= r.status < 400:
                        if not any(h["url"] == r.url for h in result["redirect_history"]):
                            result["redirect_history"].append({
                                "url": r.url,
                                "status_code": r.status
                            })
                
                rendered_html = page.content()
                
                # Enforce rendered size limit
                rendered_size = len(rendered_html.encode('utf-8', errors='replace'))
                if rendered_size > max_size_bytes:
                    browser.close()
                    result["error"] = f"Rendered HTML size ({rendered_size} bytes) exceeded limit of {max_size_bytes}."
                    result["js_rendered"] = True
                    return result
                    
                result["html"] = rendered_html
                result["success"] = True
                browser.close()
                return result
                
        except Exception as e:
            logger.warning(f"Playwright execution failed: {e}. Falling back to static downloader.")
            pass
            
    static_res = download_html_static(url, timeout, max_redirects, user_agent, max_size_bytes)
    return static_res

if __name__ == "__main__":
    import sys
    test_url = sys.argv[1] if len(sys.argv) > 1 else "http://google.com"
    print(f"Downloading (with JS rendering) from URL: {test_url}")
    res = download_html(test_url)
    output_res = res.copy()
    if output_res["html"]:
        output_res["html"] = output_res["html"][:300] + "... [TRUNCATED]"
    import json
    print(json.dumps(output_res, indent=2))
