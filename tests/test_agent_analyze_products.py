import pytest

@pytest.mark.asyncio
async def test_analyze_products_uses_deepseek_and_saves(amazon_agent, monkeypatch):
    products = [
        {
            "title": "Test Product 1",
            "price": 19.99,
            "rating": 4.6,
            "review_count": 123,
            "asin": "BTEST1",
            "url": "https://example.com/p1",
            "image_url": "",
            "brand": "BrandX",
            "category": "Cat"
        }
    ]

    async def fake_deepseek(products_in):
        return {
            "products": [
                {
                    "title": "Test Product 1",
                    "price": 19.99,
                    "score": 82,
                    "recommendation": "Buy",
                    "rating": 4.6,
                    "review_count": 123,
                    "asin": "BTEST1",
                    "url": "https://example.com/p1",
                    "image_url": "",
                    "brand": "BrandX",
                    "category": "Cat",
                    "description": "Sample description"
                }
            ],
            "insights": ["High-quality product in category"]
        }

    monkeypatch.setattr(amazon_agent, "_deepseek_analyze", fake_deepseek)

    result = await amazon_agent.analyze_products(products, client_id="test-client")

    assert result["status"] == "completed"
    assert result["count"] == 1
    assert result["saved_to_sheets"] is True
    assert isinstance(result["products"], list)
    assert "insights" in result
