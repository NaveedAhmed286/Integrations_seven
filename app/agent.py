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
    async def analyze_products(self, products:
        import os
        print(f"🔍 DEBUG analyze_products STARTED")
        print(f"🔍 DEBUG: Products received: {products}")
        print(f"🔍 DEBUG: DEEPSEEK_API_KEY exists: {'DEEPSEEK_API_KEY' in os.environ}")
        print(f"🔍 DEBUG: DEEPSEEK_API_KEY length: {len(os.getenv('DEEPSEEK_API_KEY', ''))}")
        print(f"🔍 DEBUG: APIFY_TOKEN exists: {'APIFY_TOKEN' in os.environ}")
        print(f"🔍 DEBUG: First 10 chars of DeepSeek key: {os.getenv('DEEPSEEK_API_KEY', '')[:10] if os.getenv('DEEPSEEK_API_KEY') else 'None'}") List[Dict]) -> Dict:
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
        print("DEBUG: _deepseek_analyze started")
        print("=" * 60)
        print("🚨 DEBUG: _deepseek_analyze START")
        print(f"🚨 DEBUG: self.deepseek_api_key exists: {bool(self.deepseek_api_key)}")
        if self.deepseek_api_key:
            print(f"🚨 DEBUG: Key starts with: {self.deepseek_api_key[:10]}...")
            print(f"🚨 DEBUG: Key length: {len(self.deepseek_api_key)}")
        print(f"🚨 DEBUG: Products count: {len(products)}")
        print(f"🚨 DEBUG: First product: {products[0] if products else None}")
        print("=" * 60)
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
                print("🚨 DEBUG: Making DeepSeek API call...")
                print("DEBUG: Calling DeepSeek API")
            async with session.post(
                self.deepseek_api_url,
                headers=headers,
                json=payload,
                timeout=120
            ) as resp:
                print(f"🚨 DEBUG: HTTP Status Code: {resp.status}")
                # Get raw response first
                raw_response = await resp.text()
                print(f"🚨 DEBUG: Raw response length: {len(raw_response)}")
                print(f"🚨 DEBUG: First 300 chars: {raw_response[:300]}")
                
                # Try to parse as JSON
                try:
                print(f"DEBUG: HTTP Status: {resp.status}")
                # Try to get response text first
                try:
                    response_text = await resp.text()
                    print(f"DEBUG: Response length: {len(response_text)}")
                    print(f"DEBUG: First 100 chars: {response_text[:100]}")
                    data = await resp.json()
                except Exception as e:
                    print(f"ERROR: Failed to parse response: {e}")
                    raise
                    print("🚨 DEBUG: Response parsed as JSON successfully")
                except Exception as e:
                    print(f"🚨 ERROR: Failed to parse JSON: {e}")
                    print(f"🚨 ERROR: Full response: {raw_response}")
                    raise Exception(f"DeepSeek API returned invalid JSON: {str(e)[:100]}")

        # Check if API returned error
        if "error" in data:
            print(f"🚨 ERROR: DeepSeek API error: {data['error']}")
            raise Exception(f"DeepSeek API error: {data['error']}")
        
        if "choices" not in data:
            print(f"🚨 ERROR: No choices in response. Data: {data}")
            raise Exception("DeepSeek returned no choices in response")
        
        if not data["choices"]:
            print(f"🚨 ERROR: Empty choices array. Data: {data}")
            raise Exception("DeepSeek returned empty choices array")
        
        print(f"🚨 DEBUG: Found {len(data['choices'])} choice(s) in response")
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
