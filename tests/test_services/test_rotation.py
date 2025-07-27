"""Tests for key rotation service."""

import time
from unittest.mock import AsyncMock, patch

import pytest

from app.services.rotation import RotationService, CircuitBreaker, RotationStrategy


class TestCircuitBreaker:
    """Test the CircuitBreaker class."""
    
    def test_circuit_breaker_initialization(self):
        """Test circuit breaker initialization."""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60)
        
        assert cb.failure_threshold == 3
        assert cb.recovery_timeout == 60
        assert cb.failure_count == 0
        assert cb.last_failure_time is None
        assert cb.state == "closed"
    
    def test_circuit_breaker_success(self):
        """Test circuit breaker on success."""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60)
        
        # Record success
        cb.record_success()
        
        assert cb.failure_count == 0
        assert cb.state == "closed"
    
    def test_circuit_breaker_failure(self):
        """Test circuit breaker on failure."""
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=60)
        
        # First failure
        cb.record_failure()
        assert cb.failure_count == 1
        assert cb.state == "closed"
        
        # Second failure - should open circuit
        cb.record_failure()
        assert cb.failure_count == 2
        assert cb.state == "open"
        assert cb.last_failure_time is not None
    
    def test_circuit_breaker_reset(self):
        """Test circuit breaker reset."""
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=60)
        
        # Trip the circuit
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "open"
        
        # Reset
        cb.reset()
        assert cb.failure_count == 0
        assert cb.last_failure_time is None
        assert cb.state == "closed"
    
    def test_circuit_breaker_can_execute(self):
        """Test circuit breaker execution permission."""
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=1)
        
        # Initially should allow
        assert cb.can_execute() is True
        
        # Trip the circuit
        cb.record_failure()
        cb.record_failure()
        assert cb.can_execute() is False
        
        # Wait for recovery
        time.sleep(1.1)  # Wait longer than recovery timeout
        assert cb.can_execute() is True
        
        # Should be in half-open state
        assert cb.state == "half-open"
    
    def test_circuit_breaker_half_open_success(self):
        """Test circuit breaker recovery on success."""
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1)
        
        # Trip the circuit
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "open"
        
        # Wait for recovery
        time.sleep(0.2)
        assert cb.can_execute() is True
        assert cb.state == "half-open"
        
        # Success should close circuit
        cb.record_success()
        assert cb.state == "closed"
        assert cb.failure_count == 0
    
    def test_circuit_breaker_half_open_failure(self):
        """Test circuit breaker failure in half-open state."""
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1)
        
        # Trip the circuit
        cb.record_failure()
        cb.record_failure()
        
        # Wait and enter half-open
        time.sleep(0.2)
        assert cb.can_execute() is True
        
        # Failure should reopen circuit
        cb.record_failure()
        assert cb.state == "open"
        assert cb.can_execute() is False


class TestRotationService:
    """Test the RotationService class."""
    
    @pytest.mark.asyncio
    async def test_rotation_service_initialization(self, rotation_service: RotationService):
        """Test rotation service initialization."""
        assert rotation_service.key_manager is not None
        assert isinstance(rotation_service.circuit_breakers, dict)
        assert rotation_service.last_rotation_time == 0
        assert rotation_service.rotation_interval == 300  # 5 minutes
    
    @pytest.mark.asyncio
    async def test_get_next_key_round_robin(self, rotation_service: RotationService, sample_openrouter_keys: list[str]):
        """Test round-robin key selection."""
        # Add keys to the key manager
        for key in sample_openrouter_keys:
            await rotation_service.key_manager.add_openrouter_key(key)
        
        # Get keys multiple times and check rotation
        selected_keys = []
        for _ in range(len(sample_openrouter_keys) * 2):  # Test full rotation twice
            key = await rotation_service.get_next_key(RotationStrategy.ROUND_ROBIN)
            if key:
                selected_keys.append(key)
        
        # Should have used all keys
        assert len(set(selected_keys)) == len(sample_openrouter_keys)
    
    @pytest.mark.asyncio
    async def test_get_next_key_weighted_round_robin(self, rotation_service: RotationService, sample_openrouter_keys: list[str]):
        """Test weighted round-robin key selection."""
        # Add keys with different usage patterns
        keys_data = []
        for i, key in enumerate(sample_openrouter_keys):
            key_data = await rotation_service.key_manager.add_openrouter_key(key)
            
            # Simulate different usage counts
            for _ in range(i * 5):  # 0, 5, 10 usage counts
                await rotation_service.key_manager.update_openrouter_key_usage(
                    key_data.key_hash, success=True
                )
            keys_data.append(key_data)
        
        # Get next key using weighted strategy
        key = await rotation_service.get_next_key(RotationStrategy.WEIGHTED_ROUND_ROBIN)
        
        assert key is not None
        assert key in sample_openrouter_keys
    
    @pytest.mark.asyncio
    async def test_get_next_key_least_used(self, rotation_service: RotationService, sample_openrouter_keys: list[str]):
        """Test least-used key selection."""
        # Add keys with different usage patterns
        least_used_key = sample_openrouter_keys[0]
        most_used_key = sample_openrouter_keys[1]
        
        # Add keys
        least_key_data = await rotation_service.key_manager.add_openrouter_key(least_used_key)
        most_key_data = await rotation_service.key_manager.add_openrouter_key(most_used_key)
        
        # Use one key more than the other
        for _ in range(10):
            await rotation_service.key_manager.update_openrouter_key_usage(
                most_key_data.key_hash, success=True
            )
        
        # Should return the least used key
        selected_key = await rotation_service.get_next_key(RotationStrategy.LEAST_USED)
        assert selected_key == least_used_key
    
    @pytest.mark.asyncio
    async def test_get_next_key_random(self, rotation_service: RotationService, sample_openrouter_keys: list[str]):
        """Test random key selection."""
        # Add keys
        for key in sample_openrouter_keys:
            await rotation_service.key_manager.add_openrouter_key(key)
        
        # Get random keys
        selected_keys = set()
        for _ in range(20):  # Try multiple times to get randomness
            key = await rotation_service.get_next_key(RotationStrategy.RANDOM)
            if key:
                selected_keys.add(key)
        
        # Should have selected from available keys
        assert len(selected_keys) > 0
        for key in selected_keys:
            assert key in sample_openrouter_keys
    
    @pytest.mark.asyncio
    async def test_get_next_key_no_healthy_keys(self, rotation_service: RotationService, sample_openrouter_key: str):
        """Test key selection when no healthy keys available."""
        # Add key and mark as unhealthy
        key_data = await rotation_service.key_manager.add_openrouter_key(sample_openrouter_key)
        await rotation_service.key_manager.mark_openrouter_key_unhealthy(key_data.key_hash)
        
        # Should return None
        result = await rotation_service.get_next_key(RotationStrategy.ROUND_ROBIN)
        assert result is None
    
    @pytest.mark.asyncio
    async def test_record_key_usage_success(self, rotation_service: RotationService, sample_openrouter_key: str):
        """Test recording successful key usage."""
        # Add key
        key_data = await rotation_service.key_manager.add_openrouter_key(sample_openrouter_key)
        
        # Record success
        await rotation_service.record_key_usage(sample_openrouter_key, success=True)
        
        # Check circuit breaker state
        key_hash = rotation_service.key_manager.security_manager.hash_api_key(sample_openrouter_key)
        cb = rotation_service.circuit_breakers.get(key_hash)
        assert cb is not None
        assert cb.failure_count == 0
        assert cb.state == "closed"
        
        # Check key usage update
        updated_key = await rotation_service.key_manager.get_openrouter_key(key_data.key_hash)
        assert updated_key.usage_count == 1
        assert updated_key.failure_count == 0
    
    @pytest.mark.asyncio
    async def test_record_key_usage_failure(self, rotation_service: RotationService, sample_openrouter_key: str):
        """Test recording failed key usage."""
        # Add key
        key_data = await rotation_service.key_manager.add_openrouter_key(sample_openrouter_key)
        
        # Record failure
        await rotation_service.record_key_usage(sample_openrouter_key, success=False)
        
        # Check key usage update
        updated_key = await rotation_service.key_manager.get_openrouter_key(key_data.key_hash)
        assert updated_key.failure_count == 1
        
        # Check circuit breaker
        key_hash = rotation_service.key_manager.security_manager.hash_api_key(sample_openrouter_key)
        cb = rotation_service.circuit_breakers.get(key_hash)
        assert cb is not None
        assert cb.failure_count == 1
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_integration(self, rotation_service: RotationService, sample_openrouter_key: str):
        """Test circuit breaker integration with key rotation."""
        # Add key
        await rotation_service.key_manager.add_openrouter_key(sample_openrouter_key)
        
        # Record multiple failures to trip circuit breaker
        for _ in range(5):  # Default failure threshold is 5
            await rotation_service.record_key_usage(sample_openrouter_key, success=False)
        
        # Key should now be filtered out by circuit breaker
        key_hash = rotation_service.key_manager.security_manager.hash_api_key(sample_openrouter_key)
        healthy_keys = await rotation_service._get_healthy_keys()
        
        # Should not include the failed key
        assert sample_openrouter_key not in healthy_keys
    
    @pytest.mark.asyncio
    async def test_adaptive_rotation_timing(self, rotation_service: RotationService):
        """Test adaptive rotation timing based on load."""
        # Mock current time
        with patch('time.time') as mock_time:
            mock_time.return_value = 1000
            
            # Test with high load
            rotation_service.current_load = 100
            interval = rotation_service._calculate_adaptive_interval()
            assert interval < rotation_service.rotation_interval  # Should be faster
            
            # Test with low load
            rotation_service.current_load = 10
            interval = rotation_service._calculate_adaptive_interval()
            assert interval > rotation_service.rotation_interval  # Should be slower
    
    @pytest.mark.asyncio
    async def test_rotation_strategy_performance(self, rotation_service: RotationService, sample_openrouter_keys: list[str]):
        """Test performance characteristics of different rotation strategies."""
        # Add keys with varying performance
        for i, key in enumerate(sample_openrouter_keys):
            key_data = await rotation_service.key_manager.add_openrouter_key(key)
            
            # Simulate different success rates
            successes = 100 - (i * 20)  # 100, 80, 60 successes
            failures = i * 5  # 0, 5, 10 failures
            
            for _ in range(successes):
                await rotation_service.key_manager.update_openrouter_key_usage(
                    key_data.key_hash, success=True
                )
            for _ in range(failures):
                await rotation_service.key_manager.update_openrouter_key_usage(
                    key_data.key_hash, success=False
                )
        
        # Test weighted strategy prefers better performing keys
        selected_keys = []
        for _ in range(20):
            key = await rotation_service.get_next_key(RotationStrategy.WEIGHTED_ROUND_ROBIN)
            if key:
                selected_keys.append(key)
        
        # Should favor the first key (best performance)
        assert selected_keys.count(sample_openrouter_keys[0]) > 0
    
    @pytest.mark.asyncio
    async def test_concurrent_key_selection(self, rotation_service: RotationService, sample_openrouter_keys: list[str]):
        """Test concurrent key selection doesn't cause issues."""
        import asyncio
        
        # Add keys
        for key in sample_openrouter_keys:
            await rotation_service.key_manager.add_openrouter_key(key)
        
        # Concurrent key selection
        tasks = []
        for _ in range(20):
            task = rotation_service.get_next_key(RotationStrategy.ROUND_ROBIN)
            tasks.append(task)
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # All should succeed
        successful_results = [r for r in results if not isinstance(r, Exception)]
        assert len(successful_results) > 0
    
    @pytest.mark.asyncio
    async def test_key_rotation_state_persistence(self, rotation_service: RotationService, sample_openrouter_keys: list[str]):
        """Test that rotation state is maintained."""
        # Add keys
        for key in sample_openrouter_keys:
            await rotation_service.key_manager.add_openrouter_key(key)
        
        # Select first key
        first_key = await rotation_service.get_next_key(RotationStrategy.ROUND_ROBIN)
        
        # Select second key - should be different (if multiple keys available)
        second_key = await rotation_service.get_next_key(RotationStrategy.ROUND_ROBIN)
        
        if len(sample_openrouter_keys) > 1:
            assert first_key != second_key
    
    @pytest.mark.asyncio
    async def test_strategy_fallback(self, rotation_service: RotationService, sample_openrouter_key: str):
        """Test fallback behavior when strategy fails."""
        # Add single key
        await rotation_service.key_manager.add_openrouter_key(sample_openrouter_key)
        
        # All strategies should return the same key when only one is available
        strategies = [
            RotationStrategy.ROUND_ROBIN,
            RotationStrategy.WEIGHTED_ROUND_ROBIN,
            RotationStrategy.LEAST_USED,
            RotationStrategy.RANDOM
        ]
        
        for strategy in strategies:
            key = await rotation_service.get_next_key(strategy)
            assert key == sample_openrouter_key
    
    @pytest.mark.asyncio
    async def test_error_handling_in_rotation(self, rotation_service: RotationService):
        """Test error handling during key rotation."""
        # Mock key manager to raise error
        rotation_service.key_manager.list_healthy_openrouter_keys = AsyncMock(
            side_effect=Exception("Database error")
        )
        
        # Should handle error gracefully
        result = await rotation_service.get_next_key(RotationStrategy.ROUND_ROBIN)
        assert result is None  # Should return None on error