"""Key rotation algorithms with intelligent selection and circuit breaker patterns."""

import asyncio
import logging
import secrets
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Tuple

from app.models.keys import OpenRouterKeyData
from app.services.key_manager import KeyManager

logger = logging.getLogger(__name__)


class RotationStrategy(Enum):
    """Available rotation strategies."""
    ROUND_ROBIN = "round_robin"
    WEIGHTED = "weighted"
    LEAST_USED = "least_used"
    RANDOM = "random"
    HEALTH_BASED = "health_based"


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Circuit is open, requests are failing
    HALF_OPEN = "half_open"  # Testing if service has recovered


class CircuitBreaker:
    """Circuit breaker for handling failed API keys."""
    
    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time: Optional[datetime] = None
        self.state = CircuitState.CLOSED
        self.half_open_calls = 0
        self.max_half_open_calls = 3
    
    def can_execute(self) -> bool:
        """Check if a request can be executed."""
        if self.state == CircuitState.CLOSED:
            return True
        elif self.state == CircuitState.OPEN:
            # Check if recovery timeout has passed
            if (self.last_failure_time and 
                datetime.utcnow() - self.last_failure_time > timedelta(seconds=self.recovery_timeout)):
                self.state = CircuitState.HALF_OPEN
                self.half_open_calls = 0
                return True
            return False
        elif self.state == CircuitState.HALF_OPEN:
            return self.half_open_calls < self.max_half_open_calls
        
        return False
    
    def on_success(self):
        """Called when a request succeeds."""
        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.CLOSED
            
        self.failure_count = 0
        self.last_failure_time = None
        self.half_open_calls = 0
    
    def on_failure(self):
        """Called when a request fails."""
        self.failure_count += 1
        self.last_failure_time = datetime.utcnow()
        
        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.OPEN
            self.half_open_calls = 0
        elif self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
    
    def on_call_attempt(self):
        """Called when attempting a call in half-open state."""
        if self.state == CircuitState.HALF_OPEN:
            self.half_open_calls += 1


class KeyRotator:
    """Intelligent key rotation with multiple strategies and circuit breaker."""
    
    def __init__(self, key_manager: KeyManager, strategy: RotationStrategy = RotationStrategy.WEIGHTED):
        self.key_manager = key_manager
        self.strategy = strategy
        self.circuit_breakers: Dict[str, CircuitBreaker] = {}
        self.round_robin_index = 0
        self.key_weights: Dict[str, float] = {}
        self.last_selection: Dict[str, datetime] = {}
        
    async def select_key(self) -> Optional[Tuple[str, OpenRouterKeyData]]:
        """Select the best available key based on the rotation strategy."""
        try:
            # Get all healthy keys
            healthy_keys = await self.key_manager.get_healthy_openrouter_keys()
            
            if not healthy_keys:
                logger.warning("No healthy OpenRouter keys available")
                return None
            
            # Filter keys through circuit breakers
            available_keys = []
            for key_data in healthy_keys:
                key_hash = key_data.key_hash
                circuit_breaker = self._get_circuit_breaker(key_hash)
                
                if circuit_breaker.can_execute():
                    available_keys.append(key_data)
            
            if not available_keys:
                logger.warning("No keys available due to circuit breaker protection")
                return None
            
            # Select key based on strategy
            selected_key = await self._select_by_strategy(available_keys)
            
            if selected_key:
                # Mark attempt in circuit breaker if in half-open state
                circuit_breaker = self._get_circuit_breaker(selected_key.key_hash)
                circuit_breaker.on_call_attempt()
                
                # Update last selection time
                self.last_selection[selected_key.key_hash] = datetime.utcnow()
                
                # For rotation, we need to return both hash and the actual key
                # The actual key retrieval would need to be handled securely
                return selected_key.key_hash, selected_key
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to select key: {e}")
            return None
    
    async def _select_by_strategy(self, available_keys: List[OpenRouterKeyData]) -> Optional[OpenRouterKeyData]:
        """Select key based on the configured strategy."""
        if not available_keys:
            return None
            
        if self.strategy == RotationStrategy.ROUND_ROBIN:
            return self._round_robin_selection(available_keys)
        elif self.strategy == RotationStrategy.WEIGHTED:
            return self._weighted_selection(available_keys)
        elif self.strategy == RotationStrategy.LEAST_USED:
            return self._least_used_selection(available_keys)
        elif self.strategy == RotationStrategy.RANDOM:
            return self._random_selection(available_keys)
        elif self.strategy == RotationStrategy.HEALTH_BASED:
            return self._health_based_selection(available_keys)
        else:
            # Default to round robin
            return self._round_robin_selection(available_keys)
    
    def _round_robin_selection(self, available_keys: List[OpenRouterKeyData]) -> OpenRouterKeyData:
        """Round-robin key selection."""
        if self.round_robin_index >= len(available_keys):
            self.round_robin_index = 0
        
        selected = available_keys[self.round_robin_index]
        self.round_robin_index = (self.round_robin_index + 1) % len(available_keys)
        
        return selected
    
    def _weighted_selection(self, available_keys: List[OpenRouterKeyData]) -> OpenRouterKeyData:
        """Weighted key selection based on health and usage."""
        # Calculate weights for each key
        weights = []
        total_weight = 0
        
        for key_data in available_keys:
            weight = self._calculate_key_weight(key_data)
            weights.append(weight)
            total_weight += weight
        
        if total_weight == 0:
            # Fallback to round robin
            return self._round_robin_selection(available_keys)
        
        # Select based on weighted probability
        random_value = secrets.randbelow(int(total_weight * 1000)) / 1000.0
        cumulative_weight = 0
        
        for i, weight in enumerate(weights):
            cumulative_weight += weight
            if random_value <= cumulative_weight:
                return available_keys[i]
        
        # Fallback to last key
        return available_keys[-1]
    
    def _least_used_selection(self, available_keys: List[OpenRouterKeyData]) -> OpenRouterKeyData:
        """Select the least recently used key."""
        # Sort by last used timestamp (None values first, then oldest first)
        sorted_keys = sorted(
            available_keys,
            key=lambda k: k.last_used or datetime.min
        )
        return sorted_keys[0]
    
    def _random_selection(self, available_keys: List[OpenRouterKeyData]) -> OpenRouterKeyData:
        """Random key selection."""
        return available_keys[secrets.randbelow(len(available_keys))]
    
    def _health_based_selection(self, available_keys: List[OpenRouterKeyData]) -> OpenRouterKeyData:
        """Select key based on health score."""
        # Calculate health scores
        best_key = None
        best_score = -1
        
        for key_data in available_keys:
            score = self._calculate_health_score(key_data)
            if score > best_score:
                best_score = score
                best_key = key_data
        
        return best_key or available_keys[0]
    
    def _calculate_key_weight(self, key_data: OpenRouterKeyData) -> float:
        """Calculate weight for a key based on various factors."""
        base_weight = 1.0
        
        # Reduce weight based on failure count
        failure_penalty = key_data.failure_count * 0.2
        weight = max(0.1, base_weight - failure_penalty)
        
        # Increase weight if key hasn't been used recently
        if key_data.last_used:
            hours_since_use = (datetime.utcnow() - key_data.last_used).total_seconds() / 3600
            freshness_bonus = min(0.5, hours_since_use * 0.1)
            weight += freshness_bonus
        else:
            weight += 0.5  # Bonus for unused keys
        
        # Reduce weight if key was used very recently (avoid rapid reuse)
        if key_data.key_hash in self.last_selection:
            seconds_since_selection = (datetime.utcnow() - self.last_selection[key_data.key_hash]).total_seconds()
            if seconds_since_selection < 60:  # Less than 1 minute
                weight *= 0.5
        
        return max(0.1, weight)
    
    def _calculate_health_score(self, key_data: OpenRouterKeyData) -> float:
        """Calculate health score for a key."""
        score = 100.0
        
        # Penalty for failures
        score -= key_data.failure_count * 10
        
        # Penalty for recent rate limiting
        if key_data.rate_limit_reset and key_data.rate_limit_reset > datetime.utcnow():
            score -= 30
        
        # Bonus for low usage
        usage_factor = min(1.0, key_data.usage_count / 1000)  # Normalize to 1000 uses
        score -= usage_factor * 20
        
        # Bonus for recent successful use
        if key_data.last_used:
            hours_since_use = (datetime.utcnow() - key_data.last_used).total_seconds() / 3600
            if hours_since_use < 1:
                score += 10  # Recent successful use
        
        return max(0, score)
    
    def _get_circuit_breaker(self, key_hash: str) -> CircuitBreaker:
        """Get or create circuit breaker for a key."""
        if key_hash not in self.circuit_breakers:
            self.circuit_breakers[key_hash] = CircuitBreaker()
        return self.circuit_breakers[key_hash]
    
    async def report_success(self, key_hash: str):
        """Report successful use of a key."""
        try:
            # Update circuit breaker
            circuit_breaker = self._get_circuit_breaker(key_hash)
            circuit_breaker.on_success()
            
            # Update key usage in manager
            await self.key_manager.update_key_usage(key_hash)
            
            logger.debug(f"Reported success for key {key_hash}")
            
        except Exception as e:
            logger.error(f"Failed to report success for key {key_hash}: {e}")
    
    async def report_failure(self, key_hash: str, error_message: str = None, is_rate_limit: bool = False):
        """Report failure of a key."""
        try:
            # Update circuit breaker
            circuit_breaker = self._get_circuit_breaker(key_hash)
            circuit_breaker.on_failure()
            
            # Update key health in manager
            if is_rate_limit:
                # Calculate rate limit reset time (estimate)
                reset_time = datetime.utcnow() + timedelta(hours=1)
                await self.key_manager.mark_key_rate_limited(key_hash, reset_time)
            else:
                await self.key_manager.mark_key_unhealthy(key_hash, error_message)
            
            logger.warning(f"Reported failure for key {key_hash}: {error_message}")
            
        except Exception as e:
            logger.error(f"Failed to report failure for key {key_hash}: {e}")
    
    async def cleanup_expired_rate_limits(self):
        """Clean up expired rate limits and reset key health."""
        try:
            openrouter_keys = await self.key_manager.get_openrouter_keys()
            
            for key_data in openrouter_keys:
                if (key_data.rate_limit_reset and 
                    key_data.rate_limit_reset < datetime.utcnow() and
                    not key_data.is_healthy):
                    
                    # Reset key health
                    redis_key = f"openrouter:{key_data.key_hash}"
                    updates = {
                        'is_healthy': 'true',
                        'rate_limit_reset': None,
                        'failure_count': '0'
                    }
                    
                    # This is a bit hacky - ideally we'd have a direct method
                    # For now, we'll add it to the active set
                    from app.core.redis import get_redis_client
                    redis_client = await get_redis_client()
                    await redis_client.hset(redis_key, mapping=updates)
                    await redis_client.sadd("openrouter:active", key_data.key_hash)
                    
                    logger.info(f"Reset rate limit for key {key_data.key_hash}")
                    
        except Exception as e:
            logger.error(f"Failed to cleanup expired rate limits: {e}")
    
    def get_circuit_breaker_status(self) -> Dict[str, Dict]:
        """Get status of all circuit breakers."""
        status = {}
        for key_hash, breaker in self.circuit_breakers.items():
            status[key_hash] = {
                "state": breaker.state.value,
                "failure_count": breaker.failure_count,
                "last_failure_time": breaker.last_failure_time.isoformat() if breaker.last_failure_time else None
            }
        return status
    
    def reset_circuit_breaker(self, key_hash: str):
        """Manually reset a circuit breaker."""
        if key_hash in self.circuit_breakers:
            circuit_breaker = self.circuit_breakers[key_hash]
            circuit_breaker.state = CircuitState.CLOSED
            circuit_breaker.failure_count = 0
            circuit_breaker.last_failure_time = None
            circuit_breaker.half_open_calls = 0
            logger.info(f"Reset circuit breaker for key {key_hash}")


class KeyRotationManager:
    """High-level manager for key rotation with background tasks."""
    
    def __init__(self, key_manager: KeyManager):
        self.key_manager = key_manager
        self.rotators: Dict[RotationStrategy, KeyRotator] = {}
        self.current_strategy = RotationStrategy.WEIGHTED
        self._cleanup_task: Optional[asyncio.Task] = None
        
    def get_rotator(self, strategy: RotationStrategy = None) -> KeyRotator:
        """Get or create a key rotator for the specified strategy."""
        strategy = strategy or self.current_strategy
        
        if strategy not in self.rotators:
            self.rotators[strategy] = KeyRotator(self.key_manager, strategy)
        
        return self.rotators[strategy]
    
    async def select_key(self, strategy: RotationStrategy = None) -> Optional[Tuple[str, OpenRouterKeyData]]:
        """Select a key using the specified strategy."""
        rotator = self.get_rotator(strategy)
        return await rotator.select_key()
    
    async def report_success(self, key_hash: str, strategy: RotationStrategy = None):
        """Report successful use of a key."""
        rotator = self.get_rotator(strategy)
        await rotator.report_success(key_hash)
    
    async def report_failure(self, key_hash: str, error_message: str = None, 
                           is_rate_limit: bool = False, strategy: RotationStrategy = None):
        """Report failure of a key."""
        rotator = self.get_rotator(strategy)
        await rotator.report_failure(key_hash, error_message, is_rate_limit)
    
    def start_background_tasks(self):
        """Start background tasks for maintenance."""
        if not self._cleanup_task:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
    
    async def stop_background_tasks(self):
        """Stop background tasks."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
    
    async def _cleanup_loop(self):
        """Background task for cleaning up expired rate limits."""
        while True:
            try:
                await asyncio.sleep(300)  # Run every 5 minutes
                
                # Cleanup expired rate limits for all rotators
                for rotator in self.rotators.values():
                    await rotator.cleanup_expired_rate_limits()
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in cleanup loop: {e}")
                await asyncio.sleep(60)  # Wait 1 minute before retrying


# Global instance
rotation_manager: Optional[KeyRotationManager] = None


def get_rotation_manager(key_manager: KeyManager) -> KeyRotationManager:
    """Get or create the global rotation manager."""
    global rotation_manager
    if not rotation_manager:
        rotation_manager = KeyRotationManager(key_manager)
    return rotation_manager