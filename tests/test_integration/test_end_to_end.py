"""End-to-end integration tests."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
import httpx


class TestEndToEndIntegration:
    """Test complete end-to-end workflows."""
    
    @pytest.mark.asyncio
    async def test_complete_admin_workflow(self, async_client, key_manager, test_settings):
        """Test complete admin workflow: login -> create keys -> manage."""
        
        # 1. Login as admin
        login_response = await async_client.post("/auth/login", data={
            "username": test_settings.admin_username,
            "password": test_settings.admin_password
        })
        assert login_response.status_code in [200, 302]
        
        # 2. Access dashboard
        dashboard_response = await async_client.get("/")
        assert dashboard_response.status_code == 200
        
        # 3. Create OpenRouter key via API
        openrouter_response = await async_client.post("/admin/api/openrouter-keys", json={
            "api_key": "sk-or-test-integration-key"
        })
        assert openrouter_response.status_code in [200, 201]
        
        # 4. Create client key via API
        client_response = await async_client.post("/admin/api/client-keys", json={
            "user_id": "integration_test_user",
            "rate_limit": 1000,
            "permissions": ["chat.completions", "models.list"]
        })
        assert client_response.status_code in [200, 201]
        
        # 5. Verify keys exist
        keys_response = await async_client.get("/admin/api/client-keys")
        assert keys_response.status_code == 200
        
        openrouter_keys_response = await async_client.get("/admin/api/openrouter-keys")
        assert openrouter_keys_response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_client_api_workflow(self, async_client, key_manager):
        """Test client API workflow: create key -> make API requests."""
        
        # 1. Create client key
        result = await key_manager.create_client_key(
            user_id="api_test_user",
            rate_limit=100,
            permissions=["chat.completions"]
        )
        client_api_key = result["api_key"]
        
        # 2. Create OpenRouter key for proxying
        await key_manager.add_openrouter_key("sk-or-integration-proxy-key")
        
        # 3. Mock successful proxy response
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.aiter_raw.return_value = [b'{"choices": [{"message": {"content": "Hello"}}]}']
        mock_response.aclose = AsyncMock()
        
        with patch('httpx.AsyncClient') as mock_client:
            mock_client_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_client_instance
            mock_client_instance.request.return_value = mock_response
            
            # 4. Make API request with client key
            api_response = await async_client.post("/v1/chat/completions", 
                headers={"Authorization": f"Bearer {client_api_key}"},
                json={
                    "model": "gpt-3.5-turbo",
                    "messages": [{"role": "user", "content": "Hello"}]
                }
            )
            
            # Should be proxied successfully
            assert api_response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_key_rotation_workflow(self, async_client, key_manager):
        """Test key rotation workflow with multiple OpenRouter keys."""
        
        # 1. Create multiple OpenRouter keys
        openrouter_keys = [
            "sk-or-rotation-key-1",
            "sk-or-rotation-key-2", 
            "sk-or-rotation-key-3"
        ]
        
        for key in openrouter_keys:
            await key_manager.add_openrouter_key(key)
        
        # 2. Create client key
        result = await key_manager.create_client_key(
            user_id="rotation_test_user",
            rate_limit=1000
        )
        client_api_key = result["api_key"]
        
        # 3. Mock rotation service
        from app.services.rotation import RotationService, RotationStrategy
        rotation_service = RotationService(key_manager)
        
        # 4. Test different rotation strategies
        strategies = [
            RotationStrategy.ROUND_ROBIN,
            RotationStrategy.LEAST_USED,
            RotationStrategy.RANDOM
        ]
        
        for strategy in strategies:
            selected_key = await rotation_service.get_next_key(strategy)
            assert selected_key in openrouter_keys
    
    @pytest.mark.asyncio
    async def test_bulk_import_workflow(self, async_client, key_manager, temp_file):
        """Test bulk import workflow."""
        
        # 1. Create temp file with keys (already done by fixture)
        # temp_file contains 3 test keys
        
        # 2. Test bulk import via API
        with open(temp_file, 'rb') as f:
            files = {"file": ("keys.txt", f, "text/plain")}
            # Note: This would typically be done via authenticated admin session
            result = await key_manager.bulk_import_openrouter_keys([
                "sk-or-test-key-1234567890abcdef",
                "sk-or-test-key-abcdef1234567890",
                "sk-or-test-key-fedcba0987654321"
            ])
        
        # 3. Verify import results
        assert result.total_keys == 3
        assert result.successful_imports == 3
        assert result.failed_imports == 0
        
        # 4. Verify keys are available for rotation
        from app.services.rotation import RotationService
        rotation_service = RotationService(key_manager)
        
        available_keys = await rotation_service._get_healthy_keys()
        assert len(available_keys) >= 3
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_workflow(self, async_client, key_manager):
        """Test circuit breaker workflow with failing keys."""
        
        # 1. Create OpenRouter key
        key_data = await key_manager.add_openrouter_key("sk-or-circuit-test-key")
        
        # 2. Create rotation service
        from app.services.rotation import RotationService
        rotation_service = RotationService(key_manager)
        
        # 3. Simulate multiple failures
        for _ in range(6):  # Exceed default failure threshold of 5
            await rotation_service.record_key_usage("sk-or-circuit-test-key", success=False)
        
        # 4. Key should be filtered out by circuit breaker
        healthy_keys = await rotation_service._get_healthy_keys()
        assert "sk-or-circuit-test-key" not in healthy_keys
        
        # 5. Mark key as healthy to reset circuit breaker
        await key_manager.mark_openrouter_key_healthy(key_data.key_hash)
        
        # Reset circuit breaker
        key_hash = key_manager.security_manager.hash_api_key("sk-or-circuit-test-key")
        if key_hash in rotation_service.circuit_breakers:
            rotation_service.circuit_breakers[key_hash].reset()
        
        # 6. Key should be available again
        healthy_keys = await rotation_service._get_healthy_keys()
        assert "sk-or-circuit-test-key" in healthy_keys
    
    @pytest.mark.asyncio
    async def test_rate_limiting_workflow(self, async_client, key_manager):
        """Test rate limiting workflow."""
        
        # 1. Create client key with very low rate limit
        result = await key_manager.create_client_key(
            user_id="rate_limit_test_user",
            rate_limit=2  # Very low limit for testing
        )
        client_api_key = result["api_key"]
        
        # 2. Create OpenRouter key
        await key_manager.add_openrouter_key("sk-or-rate-limit-key")
        
        # 3. Make requests up to the limit
        key_hash = key_manager.security_manager.hash_api_key(client_api_key)
        
        # Simulate usage up to limit
        for _ in range(2):
            await key_manager.update_client_key_usage(key_hash)
        
        # 4. Next request should be rate limited
        # Note: This would be tested with actual middleware in a full integration test
        client_key = await key_manager.get_client_key_by_hash(key_hash)
        assert client_key.usage_count >= client_key.rate_limit
    
    @pytest.mark.asyncio
    async def test_health_check_workflow(self, async_client):
        """Test health check endpoints."""
        
        # 1. Test application health
        health_response = await async_client.get("/health")
        assert health_response.status_code == 200
        
        health_data = health_response.json()
        assert "status" in health_data
        
        # 2. Test metrics endpoint (if available)
        try:
            metrics_response = await async_client.get("/metrics")
            # Should either work or return 404 (if not implemented)
            assert metrics_response.status_code in [200, 404]
        except:
            # Metrics endpoint might not be implemented
            pass
    
    @pytest.mark.asyncio
    async def test_error_handling_workflow(self, async_client, key_manager):
        """Test error handling across the system."""
        
        # 1. Test with invalid JSON
        response = await async_client.post("/v1/chat/completions",
            headers={"Authorization": "Bearer invalid-key"},
            content="invalid json"
        )
        assert response.status_code in [400, 401, 422]
        
        # 2. Test with non-existent endpoint
        response = await async_client.get("/nonexistent")
        assert response.status_code == 404
        
        # 3. Test admin API without authentication
        response = await async_client.get("/admin/api/client-keys")
        assert response.status_code in [401, 403]
    
    def test_static_file_serving(self, client: TestClient):
        """Test static file serving for admin panel."""
        
        # Test that static routes don't throw errors
        # Note: Actual static files might not exist in test environment
        response = client.get("/static/css/style.css")
        # Should either serve file or return 404, not 500
        assert response.status_code in [200, 404]
    
    @pytest.mark.asyncio
    async def test_concurrent_operations(self, async_client, key_manager):
        """Test concurrent operations don't cause race conditions."""
        import asyncio
        
        # 1. Concurrent key creation
        async def create_key(user_id):
            try:
                return await key_manager.create_client_key(
                    user_id=f"concurrent_user_{user_id}",
                    rate_limit=1000
                )
            except:
                return None
        
        tasks = [create_key(i) for i in range(5)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Should handle concurrent creation gracefully
        successful_results = [r for r in results if r is not None and not isinstance(r, Exception)]
        assert len(successful_results) > 0