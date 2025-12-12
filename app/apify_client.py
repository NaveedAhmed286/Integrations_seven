import os
import aiohttp
import json
import asyncio
import re
from typing import Dict, List, Optional, Any
from app.logger import logger


class ApifyClient:
    """Client for Apify's junglee/free-amazon-product-scraper"""
    
    def __init__(self):
        self.api_token = os.getenv("APIFY_TOKEN")
        self.base_url = "https://api.apify.com/v2"
        
        if not self.api_token:
            logger.warning("⚠️ APIFY_TOKEN not configured in environment variables")
        else:
            # Debug token details
            logger.info("✅ Apify client initialized")
            logger.info(f"   Token length: {len(self.api_token)}")
            logger.info(f"   Token (raw): {repr(self.api_token)}")
            logger.info(f"   Token (stripped): {repr(self.api_token.strip())}")
            logger.info(f"   Token starts with: {self.api_token[:10]}...")
    
    async def scrape_amazon_products(self, keyword: str, max_products: int = 50) -> Dict:
        """
        Scrape Amazon products using junglee/free-amazon-product-scraper
        
        Args:
            keyword: Search term (e.g., "wireless headphones")
            max_products: Maximum number of products to return
            
        Returns:
            Dictionary with success status and products
        """
        if not self.api_token:
            error_msg = "❌ APIFY_TOKEN not configured. Add it in Railway Variables."
            logger.error(error_msg)
            return {
                "success": False,
                "error": error_msg,
                "products": []
            }
        
        logger.info(f"🔍 Starting Amazon scrape for keyword: '{keyword}'")
        
        # Prepare the input for Junglee actor
        run_input = {
            "startUrls": [
                {
                    "url": f"https://www.amazon.com/s?k={keyword.replace(' ', '+')}"
                }
            ],
            "maxResultsPerStartUrl": max_products,
            "includeReviews": True,
            "includeQuestions": False,
            "includeProductDescription": True,
            "includeProductDetails": True,
            "includeProductSpecifications": True,
            "proxyConfiguration": {
                "useApifyProxy": True,
                "apifyProxyGroups": ["RESIDENTIAL"]
            },
            "maxConcurrency": 5,
            "maxRequestRetries": 3,
            "requestTimeout": 60
        }
        
        try:
            # Step 1: Start the actor run
            logger.info("🚀 Starting Apify actor: junglee/free-amazon-product-scraper")
            
            run_response = await self._start_actor_run(run_input)
            
            if not run_response.get("success"):
                return {
                    "success": False,
                    "error": run_response.get("error", "Failed to start actor"),
                    "products": []
                }
            
            run_id = run_response["data"]["id"]
            logger.info(f"✅ Actor run started: {run_id}")
            
            # Step 2: Wait for completion
            logger.info("⏳ Waiting for scraping to complete...")
            await asyncio.sleep(10)
            
            is_completed = await self._wait_for_completion(run_id)
            
            if not is_completed:
                logger.warning(f"⚠️ Run {run_id} may not have completed fully")
            
            # Step 3: Get the results
            logger.info(f"📥 Fetching results for run: {run_id}")
            dataset_items = await self._get_dataset_items(run_id)
            
            # Step 4: Process and format the products
            processed_products = self._process_products(dataset_items)
            
            logger.info(f"🎯 Scraping complete! Found {len(processed_products)} products")
            
            return {
                "success": True,
                "keyword": keyword,
                "total_products": len(processed_products),
                "products": processed_products,
                "run_id": run_id,
                "scraper_used": "junglee/free-amazon-product-scraper"
            }
            
        except Exception as e:
            error_msg = f"❌ Apify scraping failed: {str(e)}"
            logger.error(error_msg)
            return {
                "success": False,
                "error": str(e),
                "keyword": keyword,
                "products": []
            }
    
    async def _start_actor_run(self, run_input: Dict) -> Dict:
        """Start the Apify actor run"""
        url = f"{self.base_url}/acts/junglee~free-amazon-product-scraper/runs"
        
        headers = {
            "Authorization": f"Bearer {self.api_token.strip()}",  # FIXED: added .strip()
            "Content-Type": "application/json"
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    headers=headers,
                    json=run_input,
                    timeout=60
                ) as response:
                    
                    if response.status == 201:
                        data = await response.json()
                        return {"success": True, "data": data}
                    else:
                        error_text = await response.text()
                        logger.error(f"Failed to start actor: {response.status} - {error_text}")
                        return {
                            "success": False,
                            "error": f"HTTP {response.status}: {error_text[:100]}"
                        }
                        
        except Exception as e:
            logger.error(f"Actor start error: {e}")
            return {"success": False, "error": str(e)}
    
    async def _wait_for_completion(self, run_id: str, max_wait: int = 180) -> bool:
        """Wait for the actor run to complete"""
        check_url = f"{self.base_url}/actor-runs/{run_id}"
        
        headers = {
            "Authorization": f"Bearer {self.api_token.strip()}",  # FIXED: added .strip()
            "Content-Type": "application/json"
        }
        
        for attempt in range(max_wait // 5):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        check_url,
                        headers=headers,
                        timeout=30
                    ) as response:
                        
                        if response.status == 200:
                            data = await response.json()
                            status = data.get("data", {}).get("status")
                            
                            if status == "SUCCEEDED":
                                logger.info(f"✅ Run {run_id} completed successfully")
                                return True
                            elif status in ["FAILED", "TIMED-OUT", "ABORTED"]:
                                logger.error(f"❌ Run {run_id} failed with status: {status}")
                                return False
                        
                        await asyncio.sleep(5)
                        
            except Exception as e:
                logger.warning(f"Status check error: {e}")
                await asyncio.sleep(5)
        
        logger.warning(f"⚠️ Run {run_id} timeout after {max_wait} seconds")
        return False
    
    async def _get_dataset_items(self, run_id: str) -> List[Dict]:
        """Get dataset items from completed run"""
        run_url = f"{self.base_url}/actor-runs/{run_id}"
        
        headers = {
            "Authorization": f"Bearer {self.api_token.strip()}",  # FIXED: added .strip()
            "Content-Type": "application/json"
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(run_url, headers=headers, timeout=30) as response:
                    if response.status == 200:
                        run_data = await response.json()
                        dataset_id = run_data.get("data", {}).get("defaultDatasetId")
                        
                        if not dataset_id:
                            logger.error(f"No dataset ID found for run {run_id}")
                            return []
                        
                        dataset_url = f"{self.base_url}/datasets/{dataset_id}/items"
                        async with session.get(dataset_url, headers=headers, timeout=30) as dataset_response:
                            if dataset_response.status == 200:
                                return await dataset_response.json()
                            else:
                                error_text = await dataset_response.text()
                                logger.error(f"Failed to get dataset: {error_text}")
                                return []
                    else:
                        error_text = await response.text()
                        logger.error(f"Failed to get run details: {error_text}")
                        return []
                        
        except Exception as e:
            logger.error(f"Error getting dataset items: {e}")
            return []
    
    def _process_products(self, raw_products: List[Dict]) -> List[Dict]:
        """Process and format raw Apify data"""
        processed = []
        
        for item in raw_products:
            try:
                price = 0.0
                price_str = str(item.get("price", "0"))
                if price_str and price_str.lower() != "none":
                    numbers = re.findall(r'\d+\.?\d*', price_str)
                    if numbers:
                        price = float(numbers[0])
                
                if price > 0 and item.get("title"):
                    product = {
                        "title": item.get("title", ""),
                        "price": price,
                        "original_price": item.get("originalPrice"),
                        "currency": item.get("currency", "USD"),
                        "rating": item.get("rating"),
                        "review_count": item.get("reviewCount", 0),
                        "asin": item.get("asin", ""),
                        "url": item.get("url", ""),
                        "image_url": item.get("images", [""])[0] if item.get("images") else "",
                        "seller": item.get("seller", ""),
                        "availability": item.get("availability", ""),
                        "features": item.get("features", []),
                        "description": item.get("description", "")[:500],
                        "specifications": item.get("specifications", {}),
                        "categories": item.get("categories", [])
                    }
                    processed.append(product)
                    
            except Exception as e:
                logger.warning(f"⚠️ Failed to process product: {e}")
                continue
        
        return processed
    
    async def test_connection(self) -> bool:
        """Test Apify connection"""
        if not self.api_token:
            logger.error("Cannot test: APIFY_TOKEN not set")
            return False
        
        test_url = f"{self.base_url}/users/me"
        
        headers = {
            "Authorization": f"Bearer {self.api_token.strip()}",  # FIXED: added .strip()
            "Content-Type": "application/json"
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(test_url, headers=headers, timeout=30) as response:
                    if response.status == 200:
                        logger.info("✅ Apify connection test successful")
                        return True
                    else:
                        error_text = await response.text()
                        logger.error(f"❌ Apify test failed: {response.status} - {error_text}")
                        return False
        except Exception as e:
            logger.error(f"❌ Apify connection test error: {e}")
            return False


# Global instance
apify_client = ApifyClient()