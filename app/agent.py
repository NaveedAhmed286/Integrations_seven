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
        self.deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")
        self.deepseek_api_url = "https://api.deepseek.com/chat/completions"

        # Google Sheets
        self.spreadsheet_id = os.getenv("SPREADSHEET_ID")
        self.sheet_name = os.getenv("SHEET_NAME", "Agent s Results")

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
    # DEEPSEEK ANALYSIS
    # ---------------------------
    async def _deepseek_analyze(self, products: List[Dict]) -> Dict:
        headers = {
            "Authorization": f"Bearer {self.deepseek_api_key.strip()}",
            "Content-Type": "application/json"
        }

        prompt = (
            "Analyze these Amazon products for profitability. "
            "Return JSON with fields: title, price, score (0-100), recommendation.\n\n"
            f"{json.dumps(products[:30])}"
        )

        payload = {
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.deepseek_api_url,
                headers=headers,
                json=payload,
                timeout=120
            ) as resp:
                data = await resp.json()

        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)

        return {
            "products": parsed,
            "insights": [
                "Low competition niches preferred",
                "Avoid fragile categories",
                "Focus on consistent pricing"
            ]
    }
