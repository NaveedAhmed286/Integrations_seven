import os
import json
import aiohttp
from datetime import datetime
from typing import Dict, List, Any

from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials

from app.logger import logger
from app.memory_manager import memory_manager


class AmazonAgent:
    def __init__(self):
        # DeepSeek
        self.deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")
        self.deepseek_api_url = "https://api.deepseek.com/v1/chat/completions"

        # Google Sheets
        self.spreadsheet_id = os.getenv("GOOGLE_SHEET_ID")
        self.sheets_service = self._init_google_sheets()

    def _init_google_sheets(self):
        """Initialize Google Sheets service using Railway env JSON"""
        try:
            service_account_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
            if not service_account_json:
                raise Exception("GOOGLE_SERVICE_ACCOUNT_JSON not set")

            creds_dict = json.loads(service_account_json)

            creds = Credentials.from_service_account_info(
                creds_dict,
                scopes=["https://www.googleapis.com/auth/spreadsheets"]
            )

            service = build("sheets", "v4", credentials=creds)
            logger.info("Google Sheets service initialized")
            return service

        except Exception as e:
            logger.error(f"Google Sheets init failed: {e}")
            return None

    async def analyze_products(self, products: List[Dict]) -> Dict:
        """Analyze given Amazon products using DeepSeek"""
        try:
            prompt = (
                "Analyze the following Amazon products and return the most profitable one. "
                "Respond strictly in JSON with keys: title, price, investment, score, recommendation.\n\n"
                f"Products:\n{json.dumps(products, indent=2)}"
            )

            headers = {
                "Authorization": f"Bearer {self.deepseek_api_key}",
                "Content-Type": "application/json"
            }

            payload = {
                "model": "deepseek-chat",
                "messages": [
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.2
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.deepseek_api_url,
                    headers=headers,
                    json=payload,
                    timeout=60
                ) as response:
                    data = await response.json()

            content = data["choices"][0]["message"]["content"]
            result = json.loads(content)

            result["status"] = "completed"
            result["created_at"] = datetime.utcnow().isoformat()

            # Save to Google Sheet
            await self.save_to_google_sheet(result)

            return result

        except Exception as e:
            logger.error(f"Product analysis failed: {e}")
            return {
                "status": "failed",
                "error": str(e)
            }

    async def analyze_keyword(self, keyword: str, client_id: str, max_products: int = 50) -> Dict:
        """Analyze keyword-based opportunity"""
        try:
            prompt = (
                f"Find a profitable Amazon product opportunity for keyword '{keyword}'. "
                "Respond strictly in JSON with keys: title, price, investment, score, recommendation."
            )

            headers = {
                "Authorization": f"Bearer {self.deepseek_api_key}",
                "Content-Type": "application/json"
            }

            payload = {
                "model": "deepseek-chat",
                "messages": [
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.2
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.deepseek_api_url,
                    headers=headers,
                    json=payload,
                    timeout=60
                ) as response:
                    data = await response.json()

            content = data["choices"][0]["message"]["content"]
            result = json.loads(content)

            result["keyword"] = keyword
            result["status"] = "completed"
            result["created_at"] = datetime.utcnow().isoformat()

            # Save memory
            await memory_manager.set_short_term(
                client_id=client_id,
                key=f"keyword_{keyword}",
                value=result
            )

            # Save to Google Sheet
            await self.save_to_google_sheet(result)

            return result

        except Exception as e:
            logger.error(f"Keyword analysis failed: {e}")
            return {
                "status": "failed",
                "error": str(e)
            }

    async def save_to_google_sheet(self, result: Dict):
        """Append result row to Google Sheet"""
        if not self.sheets_service or not self.spreadsheet_id:
            logger.warning("Google Sheets not configured, skipping save")
            return

        try:
            values = [[
                result.get("title"),
                result.get("price"),
                result.get("investment"),
                result.get("score"),
                result.get("recommendation"),
                result.get("keyword", ""),
                datetime.utcnow().isoformat()
            ]]

            self.sheets_service.spreadsheets().values().append(
                spreadsheetId=self.spreadsheet_id,
                range="Sheet1!A:G",
                valueInputOption="USER_ENTERED",
                body={"values": values}
            ).execute()

            logger.info("Result saved to Google Sheet")

        except Exception as e:
            logger.error(f"Failed to save to Google Sheet: {e}")
