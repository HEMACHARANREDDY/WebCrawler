import unittest
from unittest.mock import patch, MagicMock
import sys
import os
import requests

# Adjust path to find the module
sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

import html_downloader
from html_downloader import download_html

class TestHTMLDownloader(unittest.TestCase):
    @patch('html_downloader.HAS_PLAYWRIGHT', False)
    @patch('requests.Session.get')
    def test_download_html_success(self, mock_get):
        # Setup mock response
        mock_response = MagicMock()
        mock_response.url = "https://example.com"
        mock_response.status_code = 200
        mock_response.headers = {'content-type': 'text/html; charset=utf-8'}
        mock_response.history = []
        mock_response.iter_content.return_value = [b"<html><body>Hello</body></html>"]
        
        mock_get.return_value = mock_response
        
        res = download_html("https://example.com", render_javascript=False)
        
        self.assertTrue(res["success"])
        self.assertEqual(res["status_code"], 200)
        self.assertEqual(res["html"], "<html><body>Hello</body></html>")
        self.assertIsNone(res["error"])
        
    @patch('html_downloader.HAS_PLAYWRIGHT', False)
    @patch('requests.Session.get')
    def test_download_html_redirects(self, mock_get):
        # Mock redirect responses
        mock_redirect = MagicMock()
        mock_redirect.url = "http://example.com"
        mock_redirect.status_code = 301
        
        mock_final = MagicMock()
        mock_final.url = "https://www.example.com"
        mock_final.status_code = 200
        mock_final.headers = {'content-type': 'text/html'}
        mock_final.history = [mock_redirect]
        mock_final.iter_content.return_value = [b"<html></html>"]
        
        mock_get.return_value = mock_final
        
        res = download_html("http://example.com", render_javascript=False)
        
        self.assertTrue(res["success"])
        self.assertEqual(res["final_url"], "https://www.example.com")
        self.assertEqual(len(res["redirect_history"]), 1)
        self.assertEqual(res["redirect_history"][0]["url"], "http://example.com")
        self.assertEqual(res["redirect_history"][0]["status_code"], 301)
        
    @patch('html_downloader.HAS_PLAYWRIGHT', False)
    @patch('requests.Session.get')
    def test_download_html_invalid_content_type(self, mock_get):
        mock_response = MagicMock()
        mock_response.url = "https://example.com/document.pdf"
        mock_response.status_code = 200
        mock_response.headers = {'content-type': 'application/pdf'}
        mock_response.history = []
        
        mock_get.return_value = mock_response
        
        res = download_html("https://example.com/document.pdf", render_javascript=False)
        
        self.assertFalse(res["success"])
        self.assertIn("Unsupported Content-Type", res["error"])
        self.assertIsNone(res["html"])

    @patch('html_downloader.HAS_PLAYWRIGHT', False)
    @patch('requests.Session.get')
    def test_download_html_size_limit(self, mock_get):
        mock_response = MagicMock()
        mock_response.url = "https://example.com"
        mock_response.status_code = 200
        mock_response.headers = {'content-type': 'text/html'}
        mock_response.history = []
        mock_response.iter_content.return_value = [b"a" * 1024] * 10
        
        mock_get.return_value = mock_response
        
        res = download_html("https://example.com", max_size_bytes=5 * 1024, render_javascript=False)
        
        self.assertFalse(res["success"])
        self.assertIn("exceeded maximum limit", res["error"])
        self.assertIsNone(res["html"])

    @patch('html_downloader.HAS_PLAYWRIGHT', False)
    @patch('requests.Session.get')
    def test_download_html_timeout(self, mock_get):
        mock_get.side_effect = requests.exceptions.Timeout("Connection timed out")
        
        res = download_html("https://example.com", render_javascript=False)
        
        self.assertFalse(res["success"])
        self.assertIn("timed out", res["error"])
        
    @patch('html_downloader.HAS_PLAYWRIGHT', False)
    @patch('requests.Session.get')
    def test_download_html_connection_error(self, mock_get):
        mock_get.side_effect = requests.exceptions.ConnectionError("Failed to resolve host")
        
        res = download_html("https://example.com", render_javascript=False)
        
        self.assertFalse(res["success"])
        self.assertIn("Connection error occurred", res["error"])

    @patch('html_downloader.HAS_PLAYWRIGHT', True)
    @patch('html_downloader.sync_playwright')
    def test_download_html_playwright_success(self, mock_sync_playwright):
        # Mock Playwright sync framework elements
        mock_p = MagicMock()
        mock_browser = MagicMock()
        mock_context = MagicMock()
        mock_page = MagicMock()
        mock_response = MagicMock()
        
        mock_sync_playwright.return_value.__enter__.return_value = mock_p
        mock_p.chromium.launch.return_value = mock_browser
        mock_browser.new_context.return_value = mock_context
        mock_context.new_page.return_value = mock_page
        mock_page.goto.return_value = mock_response
        
        mock_response.status = 200
        mock_response.headers = {'content-type': 'text/html; charset=utf-8'}
        mock_page.url = "https://example.com/final"
        mock_page.content.return_value = "<html><body>JS Rendered Hello</body></html>"
        
        res = download_html("https://example.com", render_javascript=True)
        
        self.assertTrue(res["success"])
        self.assertEqual(res["status_code"], 200)
        self.assertEqual(res["html"], "<html><body>JS Rendered Hello</body></html>")
        self.assertEqual(res["final_url"], "https://example.com/final")
        self.assertTrue(res["js_rendered"])

    @patch('html_downloader.HAS_PLAYWRIGHT', True)
    @patch('html_downloader.sync_playwright')
    @patch('html_downloader.download_html_static')
    def test_download_html_playwright_fails_fallback(self, mock_static_download, mock_sync_playwright):
        # Simulate Playwright raising an error on browser launch
        mock_sync_playwright.return_value.__enter__.side_effect = Exception("Playwright crash")
        
        # Mock fallback response
        mock_static_download.return_value = {
            "success": True,
            "html": "<html>Static Fallback</html>",
            "js_rendered": False
        }
        
        res = download_html("https://example.com", render_javascript=True)
        
        self.assertTrue(res["success"])
        self.assertEqual(res["html"], "<html>Static Fallback</html>")
        self.assertFalse(res["js_rendered"])
        mock_static_download.assert_called_once()

if __name__ == '__main__':
    unittest.main()
