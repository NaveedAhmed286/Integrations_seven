import os
import json
import aiohttp
from datetime import datetime
from typing import Dict, List, Optional, Any

from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials

from app.logger import logger
from app.memory_manager import memory_manager
from app.apify_client import apify_client


class AmazonAgent:
    def __init__(self):
        # DeepSeek
        self.deepseek_api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        self.deepseek_api_url = "https://api.deepseek.com/chat/completions"

        # Google Sheets
        self.spreadsheet_id = os.getenv("SPREADSHEET_ID")
        if not self.spreadsheet_id:
        logger.error("❌ SPREADSHEET_ID environment variable is not set in Railway!")
        logger.error("Please set SPREADSHEET_ID in Railway Variables")

        self.sheet_name = os.getenv("SHEET_NAME", "Sheet1")


        
        # Google service account (Railway ENV)
        service_account_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
        if not service_account_json:
            raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is not set")

        creds_info = json.loads(service_account_json)
        self.creds = Credentials.from_service_account_info(
            creds_info,
            scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        self.sheets_service = build("sheets", "v4", credentials=self.creds)

        # Apify
        self.apify = apify_client

    # ---------------------------
    # SMART PRODUCT LIMIT LOGIC
    # ---------------------------
    def _decide_product_limit(self, investment: Optional[float], fallback: int) -> int:
        if not investment:
            return fallback

        if investment <= 2000:
            return 5
        elif investment <= 5000:
            return 10
        elif investment <= 10000:
            return 20
        else:
            return 30

    # ---------------------------
    # GOOGLE SHEETS SAVE
    # ---------------------------
    def _save_to_sheet(self, rows: List[List[Any]]):
        body = {"values": rows}
        self.sheets_service.spreadsheets().values().append(
            spreadsheetId=self.spreadsheet_id,
            range=f"{self.sheet_name}!A1",
            valueInputOption="USER_ENTERED",
            body=body
        ).execute()

    # ---------------------------
    # PRODUCT ANALYSIS (DIRECT)
    # ---------------------------
    async def analyze_products(self, products: List[Dict]) -> Dict:
        try:
            print(f"DEBUG: analyze_products called with {len(products)} products")
            
            analysis = await self._deepseek_analyze(products)

            rows = []
            for p in analysis["products"]:
                rows.append([
                    datetime.utcnow().isoformat(),
                    p.get("title"),
                    p.get("price"),
                    p.get("score"),
                    p.get("recommendation")
                ])

            self._save_to_sheet(rows)

            return {
                "status": "completed",
                "count": len(rows),
                "products": analysis["products"]
            }

        except Exception as e:
            logger.error(f"Product analysis failed: {e}")
            return {"status": "failed", "error": str(e)}

    # ---------------------------
    # KEYWORD ANALYSIS (APIFY)
    # ---------------------------
    async def analyze_keyword(
        self,
        keyword: str,
        client_id: str,
        max_products: int = 50,
        investment: Optional[float] = None
    ) -> Dict:
        try:
            # Decide smart limit
            final_limit = self._decide_product_limit(investment, max_products)

            logger.info(
                f"Scraping '{keyword}' | investment={investment} | limit={final_limit}"
            )

            products = await self.apify.scrape_amazon_products(
                keyword=keyword,
                max_products=final_limit
            )

            if not products:
                return {"status": "completed", "message": "No products found"}

            analysis = await self._deepseek_analyze(products)

            rows = []
            for p in analysis["products"]:
                rows.append([
                    datetime.utcnow().isoformat(),
                    p.get("title"),
                    p.get("price"),
                    p.get("score"),
                    p.get("recommendation")
                ])

            self._save_to_sheet(rows)

            # Memory learning
            await memory_manager.learn_from_analysis(
                client_id=client_id,
                task_id=f"kw-{datetime.utcnow().timestamp()}",
                analysis_type="keyword",
                input_data={"keyword": keyword},
                result_data=analysis,
                key_insights=analysis.get("insights", [])
            )

            return {
                "status": "completed",
                "scraped": len(products),
                "analyzed": len(rows)
            }

        except Exception as e:
            logger.error(f"Keyword analysis failed: {e}")
            return {"status": "failed", "error": str(e)}

    # ---------------------------
    # DEEPSEEK ANALYSIS (SIMPLIFIED)
    # ---------------------------
    async def _deepseek_analyze(self, products: List[Dict]) -> Dict:
        print("DEBUG: _deepseek_analyze called")
        
        if not self.deepseek_api_key:
            return {"products": [], "insights": ["No API key"]}
        
        headers = {
            "Authorization": f"Bearer {self.deepseek_api_key}",
            "Content-Type": "application/json"
        }

        # SIMPLE prompt that forces JSON
        prompt = f"""Analyze these Amazon products and return JSON only:\n{json.dumps(products[:3], indent=2)}\n\nReturn JSON with this exact structure:\n{{\n  \"products\": [\n    {{\n      \"title\": \"product title\",\n      \"price\": 99.99,\n      \"score\": 85,\n      \"recommendation\": \"Buy/Avoid/Research\"\n    }}\n  ]\n}}"""
        
        payload = {
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.deepseek_api_url,
                    headers=headers,
                    json=payload,
                    timeout=30
                ) as resp:
                    print(f"DEBUG: HTTP Status: {resp.status}")
                    data = await resp.json()
            
            if "choices" in data and data["choices"]:
                content = data["choices"][0]["message"]["content"]
                print(f"DEBUG: Raw content: {content[:100]}...")
                
                # Clean markdown code blocks
                if content.startswith("```json"):
                    content = content[7:]
                if content.endswith("```"):
                    content = content[:-3]
                content = content.strip()
                
                print(f"DEBUG: Cleaned content: {content[:100]}...")
                
                try:
                    parsed = json.loads(content)
                except json.JSONDecodeError:
                    # If not JSON, return mock
                    parsed = {"products": [{"title": "Default", "price": 0, "score": 0, "recommendation": "Check API"}]}
                
                return {
                    "products": parsed.get("products", []),
                    "insights": ["Analysis complete"]
                }
            else:
                return {
                    "products": [{"error": "No choices in response"}],
                    "insights": ["API error"]
                }
                
        except Exception as e:
            print(f"DEBUG: DeepSeek error: {e}")
            return {
                "products": [{"error": str(e)}],
                "insights": ["Exception occurred"]
            }
