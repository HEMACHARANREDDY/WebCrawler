import unittest
from unittest.mock import patch, MagicMock, mock_open
import sys
import os

# Adjust path to find the module
sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

import crawler_engine
from crawler_engine import extract_links, is_internal_url, RobotsCache, CrawlEngine

class TestCrawlerEngine(unittest.TestCase):
    def test_extract_links(self):
        html = """
        <html>
            <body>
                <a href="/about">About</a>
                <a href="https://example.com/contact?id=123#section">Contact</a>
                <a href="mailto:info@example.com">Mail Us</a>
                <a href="tel:+12345">Call Us</a>
                <a href="javascript:void(0)">JS</a>
                <a href="">Empty</a>
            </body>
        </html>
        """
        links = extract_links(html, "https://example.com")
        self.assertEqual(len(links), 2)
        self.assertIn("https://example.com/about", links)
        self.assertIn("https://example.com/contact?id=123", links) # fragment stripped
        
    def test_is_internal_url(self):
        self.assertTrue(is_internal_url("https://example.com/page", "https://example.com"))
        self.assertTrue(is_internal_url("https://sub.example.com/page", "https://example.com"))
        self.assertFalse(is_internal_url("https://other.com/page", "https://example.com"))
        self.assertFalse(is_internal_url("https://example.com.other.com", "https://example.com"))
        
    @patch('requests.get')
    def test_robots_cache_allow_disallow(self, mock_get):
        # Disallowed status code
        mock_resp_403 = MagicMock()
        mock_resp_403.status_code = 403
        mock_get.return_value = mock_resp_403
        
        cache = RobotsCache()
        self.assertFalse(cache.can_fetch("https://example.com/secret", user_agent="*"))
        
        # Reset cache
        cache.parsers = {}
        
        # Allowed content
        mock_resp_200 = MagicMock()
        mock_resp_200.status_code = 200
        mock_resp_200.text = "User-agent: *\nDisallow: /private\n"
        mock_get.return_value = mock_resp_200
        
        self.assertTrue(cache.can_fetch("https://example.com/public", user_agent="*"))
        self.assertFalse(cache.can_fetch("https://example.com/private", user_agent="*"))

    @patch('crawler_engine.download_html')
    @patch('crawler_engine.CrawlEngine._save_page')
    @patch('os.path.exists')
    @patch('os.makedirs')
    @patch('builtins.open', new_callable=mock_open)
    def test_crawl_engine_loop(self, mock_file, mock_makedirs, mock_exists, mock_save, mock_download):
        mock_exists.return_value = False
        mock_save.return_value = "/mock/path/page.html"
        
        # Setup page downloads
        def download_side_effect(url, **kwargs):
            if url == "https://example.com/":
                return {
                    "success": True,
                    "status_code": 200,
                    "html": '<html><a href="/p1">Page 1</a></html>',
                    "final_url": "https://example.com/"
                }
            elif url == "https://example.com/p1":
                return {
                    "success": True,
                    "status_code": 200,
                    "html": '<html><a href="/p2">Page 2</a></html>',
                    "final_url": "https://example.com/p1"
                }
            return {"success": False, "status_code": 404, "html": None}
            
        mock_download.side_effect = download_side_effect
        
        engine = CrawlEngine(
            base_url="https://example.com/",
            max_pages=2,
            max_depth=2,
            delay=0,
            ignore_robots=True
        )
        
        visited = engine.run()
        
        self.assertEqual(len(visited), 2)
        self.assertIn("https://example.com/", visited)
        self.assertIn("https://example.com/p1", visited)
        self.assertNotIn("https://example.com/p2", visited)
        
        self.assertEqual(mock_download.call_count, 2)
        mock_save.assert_any_call("https://example.com/", '<html><a href="/p1">Page 1</a></html>')
        mock_save.assert_any_call("https://example.com/p1", '<html><a href="/p2">Page 2</a></html>')

if __name__ == '__main__':
    unittest.main()
