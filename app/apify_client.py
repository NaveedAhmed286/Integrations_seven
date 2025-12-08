import os
import aiohttp
import json
from typing import Dict, List, Optional
from app.logger import logger

class ApifyClient:
    def __init__(self):
        self.api_token = os.getenv("APIFY_TOKEN")
        self.base_url = "https://api.apify.com/v2"
        
    async def scrape_amazon_products(self, keyword: str, max_products: int = 50) -> List[Dict]:
        """Scrape Amazon products using Apify"""
        if not self.api_token:
            logger.error("Apify token not configured")
            return []
        
        try:
            # This is a template - adjust based on your Apify actor
            payload = {
                "keyword": keyword,
                "maxProducts": max_products,
                "proxyConfig": {"useApifyProxy": True}
            }
            
            headers = {
                "Authorization": f"Bearer {self.api_token}",
                "Content-Type": "application/json"
            }
            
            async with aiohttp.ClientSession() as session:
                # Start actor run
                async with session.post(
                    f"{self.base_url}/acts/apify~amazon-scraper/run-sync-get-dataset-items",
                    headers=headers,
                    json=payload,
                    timeout=120
                ) as response:
                    
                    if response.status == 200:
                        data = await response.json()
                        return self._format_products(data)
                    else:
                        error_text = await response.text()
                        logger.error(f"Apify error: {error_text}")
                        return []
                        
        except Exception as e:
            logger.error(f"Apify scraping failed: {e}")
            return []
    
    def _format_products(self, raw_data: List[Dict]) -> List[Dict]:
        """Format Apify data to standard format"""
        formatted = []
        for item in raw_data[:50]:  # Limit to 50
            product = {
                "title": item.get("title", ""),
                "price": item.get("price", {}).get("value"),
                "currency": item.get("price", {}).get("currency", "USD"),
                "rating": item.get("stars"),
                "review_count": item.get("reviewsCount"),
                "asin": item.get("asin"),
                "url": item.get("url"),
                "image_url": item.get("imageUrl"),
                "description": item.get("description", "")[:500]
            }
            formatted.append(product)
        return formatted
    
    async def get_product_details(self, asin: str) -> Optional[Dict]:
        """Get detailed product information"""
        try:
            # Use Amazon Product API or additional scraping
            # This is a placeholder
            return {
                "asin": asin,
                "details_fetched": True,
                "note": "Implement detailed product fetching"
            }
        except Exception as e:
            logger.error(f"Product details error: {e}")
            return None

# Global instance
apify_client = ApifyClient()