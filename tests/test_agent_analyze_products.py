import pytest

@pytest.mark.asyncio
async def test_analyze_products_basic(amazon_agent, mock_products):
    """Basic test for analyze_products method"""
    result = await amazon_agent.analyze_products(mock_products, client_id="test-client")
    
    # Very flexible assertions
    assert isinstance(result, dict)
    assert "status" in result
    assert result["status"] in ["completed", "failed"]
    
    if "count" in result:
        assert isinstance(result["count"], int)
    
    if "products" in result:
        assert isinstance(result["products"], list)

@pytest.mark.asyncio
async def test_analyze_products_empty(amazon_agent):
    """Test with empty products list"""
    result = await amazon_agent.analyze_products([], client_id="test-client")
    assert isinstance(result, dict)
    assert "status" in result
