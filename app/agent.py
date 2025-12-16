import os
import json
import aiohttp
from datetime import datetime
from typing import Dict, List, Optional, Any
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
from app.logger import logger
from app.memory_manager import memory_manager

class AmazonAgent:
    def __init__(self):
        self.deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")
        self.deepseek_api_url = "https://api.deepseek.com/v1/chat/completions"
        self.sheet_id = os.getenv("SHEET_ID")
        self.sheet_name = "Agent s Results"  # your sheet name
        self.creds_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
        self.creds_dict = json.loads(self.creds_json) if self.creds_json else None
        self.scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        self.sheet_service = self.init_google_sheets()

    def init_google_sheets(self):
        if not self.creds_dict:
            logger.warning("Google service account not configured!")
            return None
        creds = Credentials.from_service_account_info(self.creds_dict, scopes=self.scopes)
        service = build("sheets", "v4", credentials=creds)
        return service.spreadsheets()

    async def analyze_products(self, products: List[Dict]) -> Dict:
        """Analyze Amazon products using DeepSeek"""
        try:
            results = []
            for product in products:
                prompt = f"Analyze this product: {json.dumps(product)}"
                response = await self.call_deepseek(prompt)
                results.append({
                    "product": product,
                    "analysis": response
                })
            await self.save_to_sheets(results)
            return {"status": "completed", "results": results}
        except Exception as e:
            logger.error(f"Product analysis failed: {e}")
            return {"status": "failed", "error": str(e)}

    async def analyze_keyword(self, keyword: Optional[str] = None, client_id: str = "", 
                              investment: Optional[float] = None, price_range: Optional[List[float]] = None,
                              max_products: int = 50) -> Dict:
        """
        Analyze products by keyword or generate keywords from investment/price
        """
        try:
            keywords_to_use = []
            
            if keyword:
                keywords_to_use = [keyword]
            elif investment or price_range:
                # Generate keywords using DeepSeek from investment & price
                prompt = f"Suggest 5-10 Amazon product keywords suitable for investment {investment} and price range {price_range}"
                keywords_to_use = await self.call_deepseek(prompt)
                if isinstance(keywords_to_use, str):
                    # Assume DeepSeek returns comma-separated keywords
                    keywords_to_use = [k.strip() for k in keywords_to_use.split(",")]
            
            all_results = []
            # Scrape products for each keyword
            for kw in keywords_to_use:
                scraped_products = await self.scrape_amazon_products(kw, max_products)
                analysis_results = await self.analyze_products(scraped_products)
                all_results.append({
                    "keyword": kw,
                    "analysis": analysis_results
                })
            return {"status": "completed", "results": all_results}
        except Exception as e:
            logger.error(f"Keyword analysis failed: {e}")
            return {"status": "failed", "error": str(e)}

    async def call_deepseek(self, prompt: str) -> Any:
        """Call DeepSeek API"""
        headers = {
            "Authorization": f"Bearer {self.deepseek_api_key}",
            "Content-Type": "application/json"
        }
        data = {
            "model": "gpt-4",
            "prompt": prompt,
            "temperature": 0.7
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(self.deepseek_api_url, headers=headers, json=data) as resp:
                resp_json = await resp.json()
                return resp_json.get("output") or resp_json

    async def scrape_amazon_products(self, keyword: str, max_products: int = 50) -> List[Dict]:
        """Call Apify actor to scrape Amazon products by keyword"""
        from app.apify_client import apify_client
        try:
            return await apify_client.scrape_amazon_products(keyword, max_products)
        except Exception as e:
            logger.error(f"Apify scrape failed for keyword '{keyword}': {e}")
            return []

    async def save_to_sheets(self, data: List[Dict]):
        """Save results to Google Sheet"""
        if not self.sheet_service:
            logger.warning("Google Sheets service not initialized.")
            return
        try:
            values = []
            for item in data:
                # Flatten product + analysis into a single row
                row = [
                    datetime.utcnow().isoformat(),
                    json.dumps(item)
                ]
                values.append(row)
            body = {"values": values}
            self.sheet_service.values().append(
                spreadsheetId=self.sheet_id,
                range=f"{self.sheet_name}!A1",
                valueInputOption="RAW",
                body=body
            ).execute()
        except Exception as e:
            logger.error(f"Failed to save to Google Sheets: {e}")
