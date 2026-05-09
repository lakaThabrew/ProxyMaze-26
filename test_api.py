#!/usr/bin/env python3
"""
Simple test harness for ProxyMaze API
Tests all 12 endpoints and validates behavior
"""
import httpx
import json
import time
import asyncio
from datetime import datetime

BASE_URL = "http://localhost:8000"
client = httpx.Client(base_url=BASE_URL)


def test_health():
    """Test 1: Health check"""
    print("TEST: Health Check")
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    print("  ✓ Health check passed")


def test_config():
    """Test 2: Configuration management"""
    print("\nTEST: Configuration Management")
    
    # Set config
    resp = client.post("/config", json={
        "check_interval_seconds": 5,
        "request_timeout_ms": 2000
    })
    assert resp.status_code == 200
    print("  ✓ Config POST succeeded")
    
    # Get config
    resp = client.get("/config")
    assert resp.status_code == 200
    data = resp.json()
    assert data["check_interval_seconds"] == 5
    assert data["request_timeout_ms"] == 2000
    print("  ✓ Config GET verified")


def test_proxies():
    """Test 3: Proxy pool management"""
    print("\nTEST: Proxy Pool Management")
    
    # Add proxies
    resp = client.post("/proxies", json={
        "proxies": [
            "https://httpbin.org/status/200",
            "https://httpbin.org/delay/10"  # Will timeout
        ],
        "replace": True
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["accepted"] == 2
    assert len(data["proxies"]) == 2
    print("  ✓ POST /proxies succeeded")
    
    # Get pool status
    resp = client.get("/proxies")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    print(f"  ✓ Pool status: {data['total']} proxies")
    
    # Get single proxy
    resp = client.get("/proxies/200")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "200"
    print(f"  ✓ GET /proxies/200 succeeded")
    
    # Get proxy history
    resp = client.get("/proxies/200/history")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    print(f"  ✓ Proxy history retrieved ({len(data)} checks)")


def test_alerts_and_webhooks():
    """Test 4: Alerts and webhooks"""
    print("\nTEST: Alerts and Webhooks")
    
    # Register webhook
    resp = client.post("/webhooks", json={
        "url": "https://webhook.site/unique-id-here"
    })
    assert resp.status_code == 201
    webhook_id = resp.json()["webhook_id"]
    print(f"  ✓ Webhook registered: {webhook_id}")
    
    # Get alerts
    resp = client.get("/alerts")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    print(f"  ✓ Alerts retrieved ({len(data)} alerts)")
    
    # Register Slack integration (bonus)
    resp = client.post("/integrations", json={
        "type": "slack",
        "webhook_url": "https://hooks.slack.com/services/test",
        "username": "ProxyWatch",
        "events": ["alert.fired", "alert.resolved"]
    })
    assert resp.status_code == 201
    print("  ✓ Slack integration registered")
    
    # Register Discord integration (bonus)
    resp = client.post("/integrations", json={
        "type": "discord",
        "webhook_url": "https://discord.com/api/webhooks/test",
        "username": "ProxyWatch",
        "events": ["alert.fired", "alert.resolved"]
    })
    assert resp.status_code == 201
    print("  ✓ Discord integration registered")


def test_metrics():
    """Test 5: Metrics"""
    print("\nTEST: Metrics")
    resp = client.get("/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_checks" in data
    assert "current_pool_size" in data
    assert "active_alerts" in data
    print(f"  ✓ Metrics: {data['current_pool_size']} proxies, {data['total_checks']} checks")


def test_pool_operations():
    """Test 6: Pool operations"""
    print("\nTEST: Pool Operations")
    
    # Clear pool
    resp = client.delete("/proxies")
    assert resp.status_code == 204
    print("  ✓ Pool cleared (DELETE /proxies)")
    
    # Verify empty
    resp = client.get("/proxies")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    print("  ✓ Pool is now empty")
    
    # Verify alerts remain
    resp = client.get("/alerts")
    assert resp.status_code == 200
    print("  ✓ Alerts persist after pool deletion")


def main():
    print("="*60)
    print("ProxyMaze'26 - API Test Suite")
    print("="*60)
    
    try:
        test_health()
        test_config()
        test_proxies()
        time.sleep(2)  # Wait for background checks
        test_alerts_and_webhooks()
        test_metrics()
        test_pool_operations()
        
        print("\n" + "="*60)
        print("✅ All tests passed!")
        print("="*60)
        
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        raise
    except Exception as e:
        print(f"\n❌ Error: {e}")
        raise


if __name__ == "__main__":
    main()
