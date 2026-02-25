"""
Base Agent — Abstract base class for all agents in the CMO hierarchy.

Provides:
- Task execution dispatch
- Task creation (queue work for other agents)
- Decision logging (audit trail)
- Shared AI call utilities
"""

import os
import json
import uuid as uuid_lib
import asyncio
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional, Dict, Any, List

import httpx

DATABASE_AVAILABLE = bool(os.getenv("DATABASE_URL"))


class BaseAgent(ABC):
    """Abstract base for CMO, Content, Social, and Acquisition agents."""

    agent_name: str = "base"  # Override in subclasses

    def __init__(self):
        self._task_handlers: Dict[str, callable] = {}

    def register_handler(self, task_type: str, handler: callable):
        """Register a handler for a specific task type."""
        self._task_handlers[task_type] = handler

    async def execute_task(self, task_dict: dict) -> dict:
        """
        Dispatch a task to the appropriate handler.
        Returns the result dict to be stored in task.result.
        """
        task_type = task_dict.get("task_type", "")
        handler = self._task_handlers.get(task_type)

        if not handler:
            return {
                "error": f"Unknown task type '{task_type}' for agent '{self.agent_name}'",
                "available_types": list(self._task_handlers.keys()),
            }

        try:
            result = await handler(task_dict.get("params", {}))
            return {"status": "success", "data": result}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def create_task(
        self,
        target_agent: str,
        task_type: str,
        params: dict,
        priority: str = "normal",
        depends_on: Optional[List[str]] = None,
        parent_task_id: Optional[str] = None,
        scheduled_for: Optional[datetime] = None,
    ) -> str:
        """Queue a task for another agent. Returns the task UUID."""
        task_uuid = str(uuid_lib.uuid4())[:12]

        if DATABASE_AVAILABLE:
            try:
                from database.connection import get_db
                from database.models import AgentTask

                async with get_db() as db:
                    task = AgentTask(
                        uuid=task_uuid,
                        source_agent=self.agent_name,
                        target_agent=target_agent,
                        task_type=task_type,
                        priority=priority,
                        params=params,
                        depends_on=depends_on or [],
                        parent_task_id=parent_task_id,
                        status="pending",
                        scheduled_for=scheduled_for,
                    )
                    db.add(task)
                return task_uuid
            except Exception as e:
                print(f"⚠️ DB task creation failed, using in-memory: {e}")

        # Fallback: in-memory task store (for local dev)
        if not hasattr(BaseAgent, '_memory_tasks'):
            BaseAgent._memory_tasks = []

        BaseAgent._memory_tasks.append({
            "uuid": task_uuid,
            "source_agent": self.agent_name,
            "target_agent": target_agent,
            "task_type": task_type,
            "priority": priority,
            "params": params,
            "depends_on": depends_on or [],
            "parent_task_id": parent_task_id,
            "status": "pending",
            "scheduled_for": scheduled_for.isoformat() if scheduled_for else None,
            "created_at": datetime.utcnow().isoformat(),
        })

        return task_uuid

    async def log_decision(
        self,
        decision_type: str,
        context: dict,
        decision: dict,
        reasoning: str,
        confidence: float = 0.5,
        requires_approval: bool = True,
    ) -> str:
        """Log an agent decision for audit trail and approval workflow."""
        decision_uuid = str(uuid_lib.uuid4())[:12]

        if DATABASE_AVAILABLE:
            try:
                from database.connection import get_db
                from database.models import AgentDecision

                async with get_db() as db:
                    dec = AgentDecision(
                        uuid=decision_uuid,
                        agent=self.agent_name,
                        decision_type=decision_type,
                        context=context,
                        decision=decision,
                        reasoning=reasoning,
                        confidence=confidence,
                        requires_approval=requires_approval,
                    )
                    db.add(dec)
                return decision_uuid
            except Exception as e:
                print(f"⚠️ DB decision logging failed: {e}")

        # Fallback: in-memory
        if not hasattr(BaseAgent, '_memory_decisions'):
            BaseAgent._memory_decisions = []

        BaseAgent._memory_decisions.append({
            "uuid": decision_uuid,
            "agent": self.agent_name,
            "decision_type": decision_type,
            "context": context,
            "decision": decision,
            "reasoning": reasoning,
            "confidence": confidence,
            "requires_approval": requires_approval,
            "created_at": datetime.utcnow().isoformat(),
        })

        return decision_uuid

    # ---- Shared AI utilities ----

    async def call_ai_text(
        self,
        prompt: str,
        system_prompt: str = "",
        model: str = "gemini",
        temperature: float = 0.7,
        json_mode: bool = False,
    ) -> str:
        """
        Call AI for text generation.
        Tries Gemini first, falls back to GPT-4o.
        """
        gemini_key = os.getenv("GEMINI_API_KEY")
        openai_key = os.getenv("OPENAI_API_KEY")

        if model == "gemini" and gemini_key:
            try:
                return await self._call_gemini(prompt, system_prompt, gemini_key, temperature, json_mode)
            except Exception as e:
                print(f"⚠️ Gemini failed, falling back to GPT-4o: {e}")

        if openai_key:
            return await self._call_openai(prompt, system_prompt, openai_key, temperature, json_mode)

        raise RuntimeError("No AI API key configured (GEMINI_API_KEY or OPENAI_API_KEY)")

    async def _call_gemini(
        self, prompt: str, system_prompt: str, api_key: str,
        temperature: float, json_mode: bool
    ) -> str:
        """Call Gemini 2.5 Flash for text generation."""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-05-20:generateContent?key={api_key}"

        contents = []
        if system_prompt:
            contents.append({"role": "user", "parts": [{"text": system_prompt}]})
            contents.append({"role": "model", "parts": [{"text": "Understood. I will follow these instructions."}]})
        contents.append({"role": "user", "parts": [{"text": prompt}]})

        body = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": 8192,
            }
        }

        if json_mode:
            body["generationConfig"]["responseMimeType"] = "application/json"

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(url, json=body)
            resp.raise_for_status()
            data = resp.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]

    async def _call_openai(
        self, prompt: str, system_prompt: str, api_key: str,
        temperature: float, json_mode: bool
    ) -> str:
        """Call GPT-4o for text generation."""
        from openai import OpenAI
        client = OpenAI(api_key=api_key)

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        kwargs = {
            "model": "gpt-4o",
            "messages": messages,
            "temperature": temperature,
            "max_tokens": 4096,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        response = client.chat.completions.create(**kwargs)
        return response.choices[0].message.content

    @abstractmethod
    def get_supported_tasks(self) -> List[str]:
        """Return list of task types this agent handles."""
        pass
