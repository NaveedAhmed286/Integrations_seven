import os
import aiohttp
import asyncio
import re
from typing import Dict, List
from app.logger import logger

class ApifyClient:
    def __init__(self):
        self.api_token = os.getenv("APIFY_TOKEN")
        self.base_url = "https://api.apify.com/v2"
        if self.api_token:
            self.api_token = self.api_token.strip()
            logger.info("Apify client initialized")
        else:
            logger.warning("APIFY_TOKEN not configured")

    async def scrape_amazon_products(self, keyword: str, max_products: int = 50) -> Dict:
        if not self.api_token:
            return {
                "success": False,
                "error": "APIFY_TOKEN not configured",
                "products": []
            }
        logger.info(f"Starting Amazon scrape for: {keyword}")
        run_input = {
            "startUrls": [
                {"url": f"https://www.amazon.com/s?k={keyword.replace(\" \", \"+\")}"}
            ],
            "maxResultsPerStartUrl": max_products,
            "proxyConfiguration": {
                "useApifyProxy": True,
                "apifyProxyGroups": ["RESIDENTIAL"]
            }
        }
        try:
            logger.info("Starting Apify actor")
            run_response = await self._start_actor_run(run_input)
            if not run_response.get("success"):
                return {
                    "success": False,
                    "error": run_response.get("error"),
                    "products": []
                }
            run_id = run_response["data"]["id"]
            logger.info(f"Actor run started: {run_id}")
            await asyncio.sleep(10)
            is_completed = await self._wait_for_completion(run_id)
            if not is_completed:
                logger.warning(f"Run {run_id} may not have completed")
            dataset_items = await self._get_dataset_items(run_id)
            processed_products = self._process_products(dataset_items)
            logger.info(f"Scraping complete! Found {len(processed_products)} products")
            return {
                "success": True,
                "keyword": keyword,
                "total_products": len(processed_products),
                "products": processed_products,
                "run_id": run_id,
                "scraper_used": "junglee/free-amazon-product-scraper"
            }
        except Exception as e:
            logger.error(f"Apify scraping failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "keyword": keyword,
                "products": []
            }

    async def _start_actor_run(self, run_input: Dict) -> Dict:
        if not self.api_token:
            return {"success": False, "error": "No API token"}
        url = f"{self.base_url}/acts/junglee~free-amazon-product-scraper/runs"
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json"
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=run_input, timeout=60) as response:
                    if response.status == 201:
                        data = await response.json()
                        return {"success": True, "data": data}
                    else:
                        error_text = await response.text()
                        logger.error(f"Failed to start actor: {response.status}")
                        return {"success": False, "error": f"HTTP {response.status}"}
        except Exception as e:
            logger.error(f"Actor start error: {e}")
            return {"success": False, "error": str(e)}

    async def _wait_for_completion(self, run_id: str, max_wait: int = 120) -> bool:
        if not self.api_token:
            return False
        check_url = f"{self.base_url}/actor-runs/{run_id}"
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json"
        }
        for _ in range(max_wait // 5):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(check_url, headers=headers, timeout=30) as response:
                        if response.status == 200:
                            data = await response.json()
                            status = data.get("data", {}).get("status")
                            if status == "SUCCEEDED":
                                logger.info(f"Run {run_id} completed")
                                return True
                            elif status in ["FAILED", "TIMED-OUT", "ABORTED"]:
                                logger.error(f"Run {run_id} failed: {status}")
                                return False
                await asyncio.sleep(5)
            except Exception as e:
                logger.warning(f"Status check error: {e}")
                await asyncio.sleep(5)
        logger.warning(f"Run {run_id} timeout")
        return False

    async def _get_dataset_items(self, run_id: str) -> List[Dict]:
        if not self.api_token:
            return []
        run_url = f"{self.base_url}/actor-runs/{run_id}"
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json"
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(run_url, headers=headers, timeout=30) as response:
                    if response.status == 200:
                        run_data = await response.json()
                        dataset_id = run_data.get("data", {}).get("defaultDatasetId")
                        if not dataset_id:
                            return []
                        dataset_url = f"{self.base_url}/datasets/{dataset_id}/items"
                        async with session.get(dataset_url, headers=headers, timeout=30) as dataset_response:
                            if dataset_response.status == 200:
                                return await dataset_response.json()
            return []
        except Exception as e:
            logger.error(f"Error getting dataset: {e}")
            return []

    def _process_products(self, raw_products: List[Dict]) -> List[Dict]:
        processed = []
        for item in raw_products:
            try:
                price = 0.0
                price_str = str(item.get("price", "0"))
                if price_str and price_str.lower() != "none":
                    numbers = re.findall(r\"\\d+\\.?\\d*\", price_str)
                    if numbers:
                        price = float(numbers[0])
                if price > 0 and item.get("title"):
                    product = {
                        "title": item.get("title", ""),
                        "price": price,
                        "rating": item.get("rating"),
                        "review_count": item.get("reviewCount", 0),
                        "asin": item.get("asin", ""),
                        "url": item.get("url", ""),
                        "image_url": item.get("images", [""])[0] if item.get("images") else "",
                        "seller": item.get("seller", ""),
                        "description": item.get("description", "")[:200]
                    }
                    processed.append(product)
            except Exception:
                continue
        return processed

apify_client = ApifyClient()
