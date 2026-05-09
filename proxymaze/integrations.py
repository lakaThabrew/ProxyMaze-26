"""Slack and Discord message formatting"""
import json
from datetime import datetime


def format_slack_alert_fired(alert_data: dict) -> dict:
    """Format alert.fired for Slack webhook"""
    failed_ids_str = ", ".join(alert_data["failed_proxy_ids"])
    
    return {
        "username": "ProxyWatch",
        "text": f"🚨 Alert Fired: {alert_data['failed_proxies']}/{alert_data['total_proxies']} proxies down",
        "attachments": [
            {
                "color": "#FF0000",  # Red for fired
                "fields": [
                    {"title": "Alert ID", "value": alert_data["alert_id"], "short": True},
                    {"title": "Failure Rate", "value": f"{alert_data['failure_rate']*100:.1f}%", "short": True},
                    {"title": "Failed Proxies", "value": str(alert_data["failed_proxies"]), "short": True},
                    {"title": "Threshold", "value": "20%", "short": True},
                    {"title": "Failed IDs", "value": failed_ids_str, "short": False},
                    {"title": "Fired At", "value": alert_data["fired_at"], "short": True},
                ],
                "footer": "ProxyMaze Monitoring System",
                "ts": int(datetime.fromisoformat(alert_data["fired_at"].replace("Z", "+00:00")).timestamp())
            }
        ]
    }


def format_slack_alert_resolved(alert_data: dict) -> dict:
    """Format alert.resolved for Slack webhook"""
    return {
        "username": "ProxyWatch",
        "text": "✅ Alert Resolved: Proxy pool has recovered",
        "attachments": [
            {
                "color": "#00FF00",  # Green for resolved
                "fields": [
                    {"title": "Alert ID", "value": alert_data["alert_id"], "short": True},
                    {"title": "Status", "value": "Resolved", "short": True},
                    {"title": "Resolved At", "value": alert_data["resolved_at"], "short": False},
                ],
                "footer": "ProxyMaze Monitoring System",
                "ts": int(datetime.fromisoformat(alert_data["resolved_at"].replace("Z", "+00:00")).timestamp())
            }
        ]
    }


def format_discord_alert_fired(alert_data: dict) -> dict:
    """Format alert.fired for Discord webhook"""
    failed_ids_str = ", ".join(alert_data["failed_proxy_ids"])
    
    return {
        "username": "ProxyWatch",
        "embeds": [
            {
                "title": "🚨 Alert Fired",
                "description": f"{alert_data['failed_proxies']} out of {alert_data['total_proxies']} proxies are down",
                "color": 16711680,  # Red
                "fields": [
                    {"name": "Alert ID", "value": alert_data["alert_id"], "inline": True},
                    {"name": "Failure Rate", "value": f"{alert_data['failure_rate']*100:.1f}%", "inline": True},
                    {"name": "Failed Proxies", "value": str(alert_data["failed_proxies"]), "inline": True},
                    {"name": "Threshold", "value": "20%", "inline": True},
                    {"name": "Failed IDs", "value": failed_ids_str, "inline": False},
                    {"name": "Fired At", "value": alert_data["fired_at"], "inline": False},
                ],
                "footer": {"text": "ProxyMaze Monitoring System"}
            }
        ]
    }


def format_discord_alert_resolved(alert_data: dict) -> dict:
    """Format alert.resolved for Discord webhook"""
    return {
        "username": "ProxyWatch",
        "embeds": [
            {
                "title": "✅ Alert Resolved",
                "description": "The proxy pool has recovered",
                "color": 65280,  # Green
                "fields": [
                    {"name": "Alert ID", "value": alert_data["alert_id"], "inline": True},
                    {"name": "Status", "value": "Resolved", "inline": True},
                    {"name": "Resolved At", "value": alert_data["resolved_at"], "inline": False},
                ],
                "footer": {"text": "ProxyMaze Monitoring System"}
            }
        ]
    }


async def send_integration_webhook(
    integration_type: str,
    event_type: str,
    alert_data: dict,
    webhook_url: str
) -> dict:
    """Format and prepare integration webhook payload"""
    
    if integration_type == "slack":
        if event_type == "alert.fired":
            return format_slack_alert_fired(alert_data)
        elif event_type == "alert.resolved":
            return format_slack_alert_resolved(alert_data)
    
    elif integration_type == "discord":
        if event_type == "alert.fired":
            return format_discord_alert_fired(alert_data)
        elif event_type == "alert.resolved":
            return format_discord_alert_resolved(alert_data)
    
    # Fallback to raw JSON for unknown types
    return alert_data
