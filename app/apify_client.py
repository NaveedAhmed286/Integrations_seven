# app/apify_client.py
import os
import asyncio
import re
from typing import Dict, List, Optional
from datetime import datetime
import aiohttp
from app.logger import logger

# Import memory_manager if it exists in your structure
try:
    from app.memory_manager import memory_manager
    HAS_MEMORY_MANAGER = True
except ImportError:
    HAS_MEMORY_MANAGER = False
    logger.warning("memory_manager not found, client memory features disabled")

class ApifyClient:
    def __init__(self):
        self.api_token = os.getenv("APIFY_TOKEN")
        self.base_url = "https://api.apify.com/v2"
        
        if self.api_token:
            self.api_token = self.api_token.strip()
            logger.info("Apify client initialized with junglee/free-amazon-product-scraper")
        else:
            logger.warning("APIFY_TOKEN not configured - Amazon scraping will not work")
            self.api_token = None
    
    async def scrape_amazon_products(
        self, 
        keyword: str, 
        max_products: int = 50,
        client_id: Optional[str] = None,
        category: Optional[str] = None
    ) -> Dict:
        """
        Scrape Amazon products using junglee/free-amazon-product-scraper
        """
        if not self.api_token:
            return {
                "success": False,
                "error": "APIFY_TOKEN not configured",
                "products": [],
                "client_id": client_id
            }
        
        logger.info(f"Starting Amazon scrape for client {client_id}: {keyword}")
        
        # Check cache first if memory_manager is available
        if HAS_MEMORY_MANAGER and client_id:
            cache_key = f"amazon_scrape:{keyword}:{max_products}"
            cached = await memory_manager.get_short_term_cache(cache_key)
            if cached:
                logger.info(f"Returning cached results for {keyword}")
                cached["cached"] = True
                return cached
        
        # Prepare start URL
        start_urls = []
        if category:
            amazon_url = f"https://www.amazon.com/s?k={keyword.replace(' ', '+')}&i={category}"
            logger.info(f"Using category {category} for keyword {keyword}")
        else:
            amazon_url = f"https://www.amazon.com/s?k={keyword.replace(' ', '+')}"
        
        start_urls.append({"url": amazon_url})
        
        run_input = {
            "startUrls": start_urls,
            "maxResultsPerStartUrl": min(max_products, 100),
            "proxyConfiguration": {
                "useApifyProxy": True,
                "apifyProxyGroups": ["RESIDENTIAL"]
            }
        }
        
        try:
            logger.info("Starting junglee/free-amazon-product-scraper actor")
            run_response = await self._start_actor_run(run_input)
            
            if not run_response.get("success"):
                error_msg = run_response.get("error", "Unknown error")
                logger.error(f"Actor start failed: {error_msg}")
                return {
                    "success": False,
                    "error": error_msg,
                    "keyword": keyword,
                    "client_id": client_id,
                    "products": []
                }
            
            run_id = run_response["data"]["id"]
            logger.info(f"Actor run started: {run_id}")
            
            # Wait for completion
            is_completed = await self._wait_for_completion(run_id, max_wait=180)
            
            if not is_completed:
                logger.warning(f"Run {run_id} may have timed out or failed")
            
            # Get dataset items
            dataset_items = await self._get_dataset_items(run_id)
            processed_products = self._process_products(dataset_items, keyword)
            
            # Calculate statistics
            stats = self._calculate_scrape_stats(processed_products)
            
            logger.info(f"Scraping complete for {keyword}: Found {len(processed_products)} products")
            
            result = {
                "success": True,
                "keyword": keyword,
                "category_used": category,
                "total_products": len(processed_products),
                "products": processed_products,
                "statistics": stats,
                "run_id": run_id,
                "scraper_used": "junglee/free-amazon-product-scraper",
                "timestamp": datetime.now().isoformat(),
                "client_id": client_id
            }
            
            # Cache results if memory_manager is available
            if HAS_MEMORY_MANAGER and client_id:
                cache_key = f"amazon_scrape:{keyword}:{max_products}"
                await memory_manager.set_short_term_cache(cache_key, result, ttl=86400)
                await self._store_in_client_memory(client_id, keyword, result)
            
            return result
            
        except asyncio.TimeoutError:
            logger.error(f"Scraping timeout for keyword: {keyword}")
            return {
                "success": False,
                "error": "Scraping timeout - Amazon may be blocking requests",
                "keyword": keyword,
                "client_id": client_id,
                "products": []
            }
        except Exception as e:
            logger.error(f"Apify scraping failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "keyword": keyword,
                "client_id": client_id,
                "products": []
            }
    
    async def _start_actor_run(self, run_input: Dict) -> Dict:
        """Start the junglee/free-amazon-product-scraper actor run"""
        if not self.api_token:
            return {"success": False, "error": "No API token"}
        
        url = f"{self.base_url}/acts/junglee~free-amazon-product-scraper/runs"
        
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json"
        }
        
        try:
            timeout = aiohttp.ClientTimeout(total=60)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, headers=headers, json=run_input) as response:
                    if response.status == 201:
                        data = await response.json()
                        return {"success": True, "data": data}
                    elif response.status == 402:
                        logger.error("Insufficient Apify credits")
                        return {"success": False, "error": "Insufficient Apify credits"}
                    else:
                        error_text = await response.text()
                        logger.error(f"Failed to start actor: {response.status} - {error_text}")
                        return {"success": False, "error": f"HTTP {response.status}"}
        except Exception as e:
            logger.error(f"Actor start error: {e}")
            return {"success": False, "error": str(e)}
    
    async def _wait_for_completion(self, run_id: str, max_wait: int = 180) -> bool:
        """Wait for actor run to complete"""
        if not self.api_token:
            return False
        
        check_url = f"{self.base_url}/actor-runs/{run_id}"
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json"
        }
        
        for attempt in range(max_wait // 10):
            try:
                timeout = aiohttp.ClientTimeout(total=30)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(check_url, headers=headers) as response:
                        if response.status == 200:
                            data = await response.json()
                            status = data.get("data", {}).get("status")
                            
                            if status == "SUCCEEDED":
                                logger.info(f"Run {run_id} completed successfully")
                                return True
                            elif status in ["FAILED", "TIMED-OUT", "ABORTED"]:
                                logger.error(f"Run {run_id} failed with status: {status}")
                                return False
                
                await asyncio.sleep(10)
                
            except Exception as e:
                logger.warning(f"Status check error (attempt {attempt + 1}): {e}")
                await asyncio.sleep(10)
        
        logger.warning(f"Run {run_id} timeout after {max_wait} seconds")
        return False
    
    async def _get_dataset_items(self, run_id: str) -> List[Dict]:
        """Get dataset items from completed run"""
        if not self.api_token:
            return []
        
        run_url = f"{self.base_url}/actor-runs/{run_id}"
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json"
        }
        
        try:
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(run_url, headers=headers) as response:
                    if response.status == 200:
                        run_data = await response.json()
                        dataset_id = run_data.get("data", {}).get("defaultDatasetId")
                        
                        if not dataset_id:
                            logger.warning(f"No dataset ID for run {run_id}")
                            return []
                        
                        dataset_url = f"{self.base_url}/datasets/{dataset_id}/items"
                        async with session.get(dataset_url, headers=headers) as dataset_response:
                            if dataset_response.status == 200:
                                return await dataset_response.json()
            
            return []
        except Exception as e:
            logger.error(f"Error getting dataset: {e}")
            return []
    
    def _process_products(self, raw_products: List[Dict], keyword: str) -> List[Dict]:
        """Process raw product data for analysis"""
        processed = []
        
        for item in raw_products:
            try:
                # Extract price
                price = 0.0
                price_str = str(item.get("price", "0"))
                if price_str and price_str.lower() != "none":
                    clean_price = re.sub(r'[^\d.]', '', price_str.replace(',', ''))
                    if clean_price:
                        try:
                            price = float(clean_price)
                        except ValueError:
                            price = 0.0
                
                # Extract rating
                rating = item.get("rating")
                if rating:
                    try:
                        rating = float(rating)
                    except:
                        rating = None
                
                # Extract review count
                review_count = 0
                review_str = str(item.get("reviewCount", "0"))
                if review_str:
                    numbers = re.findall(r'\d+', review_str.replace(',', ''))
                    if numbers:
                        try:
                            review_count = int(numbers[0])
                        except:
                            review_count = 0
                
                # Only include products with title and price
                if price > 0 and item.get("title"):
                    images = item.get("images", [])
                    image_url = images[0] if images else ""
                    
                    product = {
                        "title": item.get("title", "").strip(),
                        "price": round(price, 2),
                        "original_price": price_str,
                        "rating": rating,
                        "review_count": review_count,
                        "asin": item.get("asin", ""),
                        "url": item.get("url", ""),
                        "image_url": image_url,
                        "seller": item.get("seller", ""),
                        "description": item.get("description", "")[:200],
                        "brand": item.get("brand", ""),
                        "category": item.get("category", ""),
                        "scraped_at": datetime.now().isoformat()
                    }
                    processed.append(product)
            except Exception as e:
                logger.debug(f"Error processing product: {e}")
                continue
        
        return processed
    
    def _calculate_scrape_stats(self, products: List[Dict]) -> Dict:
        """Calculate statistics from scraped products"""
        if not products:
            return {
                "average_price": 0,
                "min_price": 0,
                "max_price": 0,
                "total_products": 0,
                "products_with_reviews": 0,
                "average_rating": 0
            }
        
        prices = [p["price"] for p in products if p["price"] > 0]
        ratings = [p["rating"] for p in products if p["rating"]]
        products_with_reviews = sum(1 for p in products if p["review_count"] > 0)
        
        return {
            "average_price": round(sum(prices) / len(prices), 2) if prices else 0,
            "min_price": min(prices) if prices else 0,
            "max_price": max(prices) if prices else 0,
            "total_products": len(products),
            "products_with_reviews": products_with_reviews,
            "products_without_reviews": len(products) - products_with_reviews,
            "average_rating": round(sum(ratings) / len(ratings), 2) if ratings else 0,
            "price_range": f"${min(prices) if prices else 0} - ${max(prices) if prices else 0}"
        }
    
    async def _store_in_client_memory(self, client_id: str, keyword: str, result: Dict):
        """Store scraping results in client memory"""
        if not HAS_MEMORY_MANAGER:
            return
            
        try:
            await memory_manager.add_client_search(
                client_id=client_id,
                keyword=keyword,
                results_count=len(result["products"]),
                stats=result["statistics"]
            )
        except Exception as e:
            logger.error(f"Failed to store in client memory: {e}")
    
    async def get_amazon_categories(self) -> List[Dict]:
        """Get list of Amazon categories to help overcome 7-page limit"""
        categories = [
            {"id": "aps", "name": "All Departments"},
            {"id": "arts-crafts", "name": "Arts & Crafts"},
            {"id": "automotive", "name": "Automotive"},
            {"id": "baby-products", "name": "Baby"},
            {"id": "beauty", "name": "Beauty & Personal Care"},
            {"id": "books", "name": "Books"},
            {"id": "computers", "name": "Computers"},
            {"id": "electronics", "name": "Electronics"},
            {"id": "fashion", "name": "Clothing, Shoes & Jewelry"},
            {"id": "garden", "name": "Garden & Outdoor"},
            {"id": "grocery", "name": "Grocery & Gourmet Food"},
            {"id": "handmade", "name": "Handmade"},
            {"id": "health", "name": "Health, Household & Baby Care"},
            {"id": "home-kitchen", "name": "Home & Kitchen"},
            {"id": "industrial", "name": "Industrial & Scientific"},
            {"id": "luggage", "name": "Luggage & Travel Gear"},
            {"id": "movies-tv", "name": "Movies & TV"},
            {"id": "music", "name": "Musical Instruments"},
            {"id": "office-products", "name": "Office Products"},
            {"id": "pet-supplies", "name": "Pet Supplies"},
            {"id": "sports", "name": "Sports & Outdoors"},
            {"id": "tools", "name": "Tools & Home Improvement"},
            {"id": "toys", "name": "Toys & Games"},
            {"id": "video-games", "name": "Video Games"},
        ]
        
        return categories

# Singleton instance
apify_client = ApifyClient()