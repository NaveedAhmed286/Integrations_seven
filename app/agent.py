# app/agent.py
import os
import json
import asyncio
import re
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
import aiohttp
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, before_log, after_log

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.service_account import Credentials

from app.logger import logger
from app.memory_manager import memory_manager
from app.apify_client import apify_client

class AmazonAgent:
    def __init__(self):
        """Initialize with resilience - don't crash on missing env vars"""
        try:
            # DeepSeek - with fallback
            self.deepseek_api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
            self.deepseek_api_url = "https://api.deepseek.com/chat/completions"
            
            # Google Sheets - with fallback to prevent crash
            self.spreadsheet_id = os.getenv("SPREADSHEET_ID", "1xLI2iPQdwZnZlK8TFPuFkaSQaTkVUvGnN_af520yAPk")
            self.sheet_name = os.getenv("SHEET_NAME", "Sheet1")
            
            # Log configuration (info only, not errors)
            logger.info(f"📄 Configured for spreadsheet: {self.spreadsheet_id[:20]}...")
            
            # Google service account
            service_account_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
            if not service_account_json:
                logger.critical("GOOGLE_SERVICE_ACCOUNT_JSON is not set")
                raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is required")
            
            creds_info = json.loads(service_account_json)
            self.creds = Credentials.from_service_account_info(
                creds_info,
                scopes=["https://www.googleapis.com/auth/spreadsheets"]
            )
            self.sheets_service = build("sheets", "v4", credentials=self.creds)
            
            logger.info("✅ AmazonAgent initialized successfully")
            
        except json.JSONDecodeError as e:
            logger.critical(f"❌ Invalid GOOGLE_SERVICE_ACCOUNT_JSON JSON: {e}")
            raise
        except Exception as e:
            logger.critical(f"❌ Failed to initialize AmazonAgent: {e}")
            raise
    
    # ========== KEYWORD EXTRACTION LOGIC ==========
    def _extract_search_keyword(self, product_description: str) -> Optional[str]:
        """
        Extract a clean search keyword from Google Form product description.
        Returns None if no meaningful keyword can be extracted.
        """
        if not product_description or not isinstance(product_description, str):
            logger.warning("⚠️ Empty or invalid product description")
            return None
        
        # Clean and normalize
        description = product_description.strip().lower()
        
        # Common stop words to remove
        stop_words = {
            'i', 'want', 'to', 'sell', 'buy', 'looking', 'for', 'a', 'an', 'the',
            'something', 'anything', 'some', 'any', 'good', 'best', 'popular',
            'online', 'amazon', 'product', 'products', 'item', 'items'
        }
        
        # Split and filter
        words = [word for word in re.findall(r'\b\w+\b', description) 
                if word not in stop_words and len(word) > 2]
        
        if not words:
            logger.warning(f"⚠️ No meaningful keywords in description: '{product_description}'")
            return None
        
        # Take first 3 meaningful words as keyword
        keyword = " ".join(words[:3])
        logger.info(f"🔑 Extracted keyword '{keyword}' from description: '{product_description}'")
        return keyword
    
    def _decide_product_limit(self, investment: Optional[float], fallback: int = 50) -> int:
        """
        Decide how many products to scrape based on investment amount.
        Higher investment = more products to analyze.
        """
        if not investment or investment <= 0:
            logger.info(f"📊 No investment specified, using default limit: {fallback}")
            return fallback
        
        limits = [
            (2000, 5),    # Small budget
            (5000, 10),   # Medium budget
            (10000, 20),  # Large budget
            (float('inf'), 30)  # Very large budget
        ]
        
        for max_investment, limit in limits:
            if investment <= max_investment:
                logger.info(f"💰 Investment ${investment} → Product limit: {limit}")
                return limit
        
        logger.info(f"💰 Investment ${investment} → Product limit: {fallback}")
        return fallback
    
    # ========== SMART RETRY LOGIC FOR GOOGLE SHEETS ==========
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((HttpError, TimeoutError, ConnectionError)),
        before=before_log(logger, "INFO"),
        after=after_log(logger, "INFO")
    )
    def _save_to_sheet(self, rows: List[List[Any]]) -> bool:
        """Save to Google Sheets with automatic retry on failure"""
        try:
            if not rows:
                logger.warning("⚠️ No rows to save to Google Sheets")
                return False
            
            body = {"values": rows}
            result = self.sheets_service.spreadsheets().values().append(
                spreadsheetId=self.spreadsheet_id,
                range=f"{self.sheet_name}!A1",
                valueInputOption="USER_ENTERED",
                insertDataOption="INSERT_ROWS",
                body=body
            ).execute()
            
            updated = result.get('updates', {}).get('updatedRows', 0)
            logger.info(f"✅ Saved {updated} rows to Google Sheets ({self.spreadsheet_id[:15]}...)")
            return True
            
        except HttpError as e:
            logger.error(f"❌ Google Sheets HTTP error: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ Google Sheets save failed: {e}")
            return False
    
    # ========== RESILIENT PRODUCT ANALYSIS ==========
    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=3, max=8)
    )
    async def analyze_products(self, products: List[Dict], client_id: Optional[str] = None) -> Dict:
        """Analyze products with full error handling and retry"""
        try:
            if not products:
                return {
                    "status": "completed", 
                    "count": 0, 
                    "message": "No products provided",
                    "client_id": client_id
                }
            
            logger.info(f"📦 Analyzing {len(products)} products for client {client_id}")
            
            # Get AI analysis with timeout
            try:
                analysis = await asyncio.wait_for(
                    self._deepseek_analyze(products), 
                    timeout=45.0
                )
            except asyncio.TimeoutError:
                logger.warning("⏰ DeepSeek API timeout, using fallback analysis")
                analysis = self._fallback_analysis(products)
            except Exception as e:
                logger.error(f"❌ DeepSeek analysis error: {e}")
                analysis = self._fallback_analysis(products)
            
            # Prepare rows for Google Sheets
            rows = []
            for p in analysis.get("products", []):
                # Map to your Google Sheet columns
                rows.append([
                    datetime.utcnow().isoformat(),  # Timestamp
                    p.get("title", "Unknown"),
                    p.get("price", 0),
                    "",  # Investment (filled by caller)
                    p.get("score", 0),
                    p.get("recommendation", "Research"),
                    "",  # Original Price (not available from new scraper)
                    p.get("rating", 0),
                    p.get("review_count", 0),
                    p.get("asin", ""),
                    p.get("url", ""),
                    p.get("image_url", ""),
                    "",  # Seller (not available from new scraper)
                    p.get("description", "")[:100],  # Truncated
                    p.get("brand", ""),
                    p.get("category", ""),
                    datetime.utcnow().isoformat()  # Scraped At
                ])
            
            # Try to save (won't crash if fails)
            if rows:
                saved = self._save_to_sheet(rows)
                if not saved:
                    logger.warning("⚠️ Data not saved to Google Sheets (check logs)")
            
            return {
                "status": "completed",
                "count": len(rows),
                "saved_to_sheets": bool(rows),
                "products": analysis.get("products", []),
                "insights": analysis.get("insights", []),
                "client_id": client_id
            }
            
        except Exception as e:
            logger.error(f"❌ Product analysis failed: {e}", exc_info=True)
            return {
                "status": "failed", 
                "error": str(e), 
                "count": 0,
                "client_id": client_id
            }
    
    # ========== RESILIENT DEEPSEEK API CALL ==========
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=6),
        retry=retry_if_exception_type((aiohttp.ClientError, asyncio.TimeoutError))
    )
    async def _deepseek_analyze(self, products: List[Dict]) -> Dict:
        """Call DeepSeek API with retry logic for unstable internet"""
        if not self.deepseek_api_key:
            logger.warning("⚠️ No DeepSeek API key, using fallback")
            return self._fallback_analysis(products)
        
        headers = {
            "Authorization": f"Bearer {self.deepseek_api_key}",
            "Content-Type": "application/json"
        }
        
        # Create analysis prompt
        product_summary = "\n".join([
            f"- {p.get('title', 'Unknown')} (${p.get('price', 0)}) - Rating: {p.get('rating', 0)}"
            for p in products[:15]  # Limit to avoid token overflow
        ])
        
        prompt = f"""Analyze these {len(products)} Amazon products for investment potential.
        
        Products:
        {product_summary}
        
        For EACH product, provide:
        1. Score (0-100): Based on price competitiveness, brand reputation, and review metrics
        2. Recommendation: "Buy", "Avoid", or "Research Further"
        3. Brief reason (1 sentence)
        
        Return ONLY valid JSON with this exact structure:
        {{
          "products": [
            {{
              "title": "Product Title",
              "price": 99.99,
              "score": 75,
              "recommendation": "Buy/Avoid/Research",
              "reason": "Brief reason"
            }}
          ],
          "insights": ["Overall insight 1", "Overall insight 2"]
        }}
        
        Important: Return ONLY JSON, no other text."""
        
        payload = {
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "max_tokens": 2000,
            "stream": False
        }
        
        try:
            timeout = aiohttp.ClientTimeout(total=60)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    self.deepseek_api_url,
                    headers=headers,
                    json=payload,
                    timeout=60.0
                ) as resp:
                    
                    if resp.status != 200:
                        error_text = await resp.text()
                        logger.warning(f"⚠️ DeepSeek API returned status {resp.status}: {error_text[:200]}")
                        return self._fallback_analysis(products)
                    
                    data = await resp.json()
                    
                    if "choices" in data and data["choices"]:
                        content = data["choices"][0]["message"]["content"]
                        
                        # Clean JSON response
                        content = content.strip()
                        if '```json' in content:
                            content = content.split('```json')[1].split('```')[0].strip()
                        elif '```' in content:
                            content = content.split('```')[1].split('```')[0].strip()
                        
                        try:
                            parsed = json.loads(content)
                            # Validate structure
                            if "products" in parsed and isinstance(parsed["products"], list):
                                logger.info(f"✅ DeepSeek analyzed {len(parsed['products'])} products")
                                return parsed
                            else:
                                logger.warning("⚠️ DeepSeek response missing 'products' array")
                                return self._fallback_analysis(products)
                                
                        except json.JSONDecodeError as e:
                            logger.warning(f"⚠️ Failed to parse DeepSeek JSON: {e}")
                            logger.debug(f"Raw response: {content[:500]}")
                            return self._fallback_analysis(products)
                    else:
                        logger.warning("⚠️ No choices in DeepSeek response")
                        return self._fallback_analysis(products)
                        
        except aiohttp.ClientError as e:
            logger.warning(f"🌐 DeepSeek network error: {e}")
            raise  # Trigger retry
        except Exception as e:
            logger.warning(f"⚠️ DeepSeek API call failed: {e}")
            return self._fallback_analysis(products)
    
    def _fallback_analysis(self, products: List[Dict]) -> Dict:
        """Fallback analysis when AI fails"""
        logger.info("🛡️ Using fallback analysis")
        fallback_products = []
        
        for p in products:
            price = p.get("price", 0)
            rating = p.get("rating", 0)
            
            # Simple heuristic scoring
            if price <= 0:
                score = 30
            elif price < 50 and rating >= 4.0:
                score = 75
            elif price < 100 and rating >= 4.0:
                score = 65
            elif rating >= 4.5:
                score = 70
            elif rating >= 4.0:
                score = 55
            else:
                score = 40
            
            recommendation = "Research Further"
            if score >= 70:
                recommendation = "Buy"
            elif score <= 40:
                recommendation = "Avoid"
            
            fallback_products.append({
                "title": p.get("title", "Unknown Product"),
                "price": price,
                "score": score,
                "recommendation": recommendation,
                "reason": "Fallback analysis based on price and rating"
            })
        
        return {
            "products": fallback_products,
            "insights": ["Fallback analysis used - AI service unavailable"]
        }
    
    # ========== RESILIENT KEYWORD ANALYSIS ==========
    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1.5, min=5, max=20),
        retry=retry_if_exception_type((asyncio.TimeoutError, ConnectionError))
    )
    async def analyze_keyword(self, product_description: str, client_id: str, 
                            max_products: int = 50, investment: Optional[float] = None,
                            price_min: Optional[float] = None, price_max: Optional[float] = None) -> Dict:
        """
        Main analysis method for Google Form submissions.
        
        Args:
            product_description: From Google Form (required)
            client_id: User identifier
            max_products: Maximum products to return
            investment: Budget amount (affects product limit)
            price_min: Minimum price filter
            price_max: Maximum price filter
        """
        try:
            # Step 1: Extract keyword from description
            search_keyword = self._extract_search_keyword(product_description)
            if not search_keyword:
                return {
                    "status": "failed",
                    "error": "Could not extract valid search keyword from description",
                    "client_id": client_id,
                    "description": product_description
                }
            
            logger.info(f"🔍 Processing request for client {client_id}: '{search_keyword}'")
            
            # Step 2: Determine product limit based on investment
            final_limit = self._decide_product_limit(investment, max_products)
            logger.info(f"📊 Final product limit: {final_limit} (investment: {investment})")
            
            # Step 3: Try scraping with timeout and retry
            try:
                scrape_result = await asyncio.wait_for(
                    apify_client.scrape_amazon_products(
                        keyword=search_keyword,
                        max_products=final_limit,
                        client_id=client_id,
                        price_min=price_min,
                        price_max=price_max
                    ),
                    timeout=180.0  # 3 minutes for scraping
                )
                
                if not scrape_result.get("success"):
                    error_msg = scrape_result.get("error", "Unknown scraping error")
                    logger.error(f"❌ Scraping failed: {error_msg}")
                    return {
                        "status": "failed",
                        "error": f"Scraping failed: {error_msg}",
                        "client_id": client_id,
                        "keyword": search_keyword
                    }
                
                products = scrape_result.get("products", [])
                if not products:
                    return {
                        "status": "completed",
                        "message": "No products found matching criteria",
                        "scraped": 0,
                        "analyzed": 0,
                        "client_id": client_id,
                        "keyword": search_keyword
                    }
                
                logger.info(f"✅ Found {len(products)} products for '{search_keyword}'")
                
            except asyncio.TimeoutError:
                logger.error(f"⏰ Scraping timeout for '{search_keyword}'")
                return {
                    "status": "failed",
                    "error": "Scraping timeout - Amazon may be blocking",
                    "client_id": client_id,
                    "keyword": search_keyword
                }
            except Exception as e:
                logger.error(f"❌ Scraping error: {e}")
                return {
                    "status": "failed",
                    "error": f"Scraping error: {str(e)}",
                    "client_id": client_id,
                    "keyword": search_keyword
                }
            
            # Step 4: Analyze found products
            analysis_result = await self.analyze_products(products, client_id)
            
            # Step 5: Add investment data to products for Google Sheets
            enriched_products = []
            for product in analysis_result.get("products", []):
                enriched_product = product.copy()
                enriched_product["investment"] = investment
                enriched_products.append(enriched_product)
            
            analysis_result["products"] = enriched_products
            
            # Step 6: Memory learning (won't crash if fails)
            try:
                await memory_manager.learn_from_analysis(
                    client_id=client_id,
                    task_id=f"kw-{datetime.utcnow().timestamp()}",
                    analysis_type="keyword",
                    input_data={
                        "keyword": search_keyword,
                        "description": product_description,
                        "investment": investment,
                        "price_min": price_min,
                        "price_max": price_max
                    },
                    result_data=analysis_result,
                    key_insights=analysis_result.get("insights", [])
                )
            except Exception as e:
                logger.warning(f"⚠️ Memory learning failed: {e}")
            
            # Step 7: Return comprehensive result
            return {
                "status": "completed",
                "client_id": client_id,
                "keyword": search_keyword,
                "original_description": product_description,
                "scraped": len(products),
                "analyzed": analysis_result.get("count", 0),
                "saved_to_sheets": analysis_result.get("saved_to_sheets", False),
                "investment_used": investment,
                "price_filter_applied": price_min is not None and price_max is not None,
                "price_min": price_min,
                "price_max": price_max,
                "product_limit_used": final_limit,
                "timestamp": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"❌ Keyword analysis failed: {e}", exc_info=True)
            return {
                "status": "failed",
                "error": str(e),
                "client_id": client_id,
                "description": product_description
            }
    
    # ========== QUICK TEST METHOD ==========
    async def test_connection(self) -> Dict:
        """Test all external connections"""
        tests = {
            "google_sheets": False,
            "deepseek_api": False,
            "apify_client": False
        }
        
        try:
            # Test Google Sheets
            try:
                sheet_test = self.sheets_service.spreadsheets().get(
                    spreadsheetId=self.spreadsheet_id
                ).execute()
                tests["google_sheets"] = True
                logger.info("✅ Google Sheets connection OK")
            except Exception as e:
                logger.error(f"❌ Google Sheets test failed: {e}")
            
            # Test DeepSeek API
            if self.deepseek_api_key:
                tests["deepseek_api"] = True
                logger.info("✅ DeepSeek API key configured")
            else:
                logger.warning("⚠️ DeepSeek API key not configured")
            
            # Test Apify Client
            tests["apify_client"] = await apify_client.quick_test()
            
            all_ok = all(tests.values())
            return {
                "success": all_ok,
                "tests": tests,
                "message": "All tests passed" if all_ok else "Some tests failed"
            }
            
        except Exception as e:
            logger.error(f"❌ Connection test failed: {e}")
            return {
                "success": False,
                "tests": tests,
                "error": str(e)
            }

# Global instance
agent = AmazonAgent()
logger.info("🚀 AmazonAgent module loaded with enhanced resilience")
