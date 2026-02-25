"""
Mirai CMO Agent Hierarchy

Agent system for autonomous marketing management:
- CMO Agent: Strategic planning, budget allocation, cross-agent coordination
- Content Agent: Creates all content (text, images, video) as reusable assets
- Social Network Agent: Publishes to Instagram, Facebook, TikTok; tracks engagement
- Acquisition Agent: Manages paid ads on Meta (+ future TikTok/Google Ads)
"""

from .base_agent import BaseAgent
from .orchestrator import AgentOrchestrator

__all__ = ["BaseAgent", "AgentOrchestrator"]
