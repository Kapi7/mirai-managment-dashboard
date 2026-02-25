"""
Agent Orchestrator — Background loop that dispatches tasks to agents.

Runs as a background asyncio task alongside the FastAPI server.
Polls agent_tasks table every 60 seconds, dispatches ready tasks.
"""

import os
import asyncio
from datetime import datetime
from typing import Dict, Optional

DATABASE_AVAILABLE = bool(os.getenv("DATABASE_URL"))


class AgentOrchestrator:
    """
    Background task dispatcher for the CMO agent hierarchy.
    Polls the agent_tasks queue and dispatches to registered agents.
    """

    def __init__(self):
        self.agents: Dict[str, any] = {}
        self.is_running = False
        self.last_run_at: Optional[datetime] = None
        self.tasks_processed = 0
        self.interval_seconds = 60

    def register_agent(self, name: str, agent):
        """Register an agent instance for task dispatch."""
        self.agents[name] = agent
        print(f"  📋 Registered agent: {name} ({', '.join(agent.get_supported_tasks())})")

    async def start(self):
        """Start the orchestrator background loop."""
        if self.is_running:
            return

        # Lazy-load all agents
        self._load_agents()

        self.is_running = True
        print(f"🚀 Agent Orchestrator started (interval: {self.interval_seconds}s)")
        print(f"   Registered agents: {list(self.agents.keys())}")

        while self.is_running:
            try:
                await self.process_cycle()
            except Exception as e:
                print(f"❌ Orchestrator cycle error: {e}")

            await asyncio.sleep(self.interval_seconds)

    async def stop(self):
        """Stop the orchestrator."""
        self.is_running = False
        print("🛑 Agent Orchestrator stopped")

    def _load_agents(self):
        """Lazy-load all agent instances."""
        if self.agents:
            return  # Already loaded

        try:
            from .cmo_agent import CMOAgent
            self.register_agent("cmo", CMOAgent())
        except Exception as e:
            print(f"⚠️ Failed to load CMO agent: {e}")

        try:
            from .content_agent import ContentAgent
            self.register_agent("content", ContentAgent())
        except Exception as e:
            print(f"⚠️ Failed to load Content agent: {e}")

        try:
            from .social_agent import SocialNetworkAgent
            self.register_agent("social", SocialNetworkAgent())
        except Exception as e:
            print(f"⚠️ Failed to load Social agent: {e}")

        try:
            from .acquisition_agent import AcquisitionAgent
            self.register_agent("acquisition", AcquisitionAgent())
        except Exception as e:
            print(f"⚠️ Failed to load Acquisition agent: {e}")

    async def process_cycle(self):
        """Run one processing cycle: fetch and dispatch ready tasks."""
        self.last_run_at = datetime.utcnow()

        if DATABASE_AVAILABLE:
            tasks = await self._fetch_ready_tasks_db()
        else:
            tasks = self._fetch_ready_tasks_memory()

        if not tasks:
            return

        for task in tasks:
            await self._dispatch_task(task)

    async def _dispatch_task(self, task: dict):
        """Dispatch a single task to the appropriate agent."""
        target = task.get("target_agent")
        agent = self.agents.get(target)

        if not agent:
            await self._mark_task_failed(task, f"No agent registered for '{target}'")
            return

        # Mark as in_progress
        await self._mark_task_in_progress(task)

        try:
            result = await agent.execute_task(task)
            await self._mark_task_completed(task, result)
            self.tasks_processed += 1
            print(f"✅ Task {task['uuid']} ({task['task_type']}) → {target} completed")
        except Exception as e:
            retry_count = task.get("retry_count", 0)
            max_retries = task.get("max_retries", 3)

            if retry_count < max_retries:
                await self._mark_task_retry(task, str(e))
                print(f"⚠️ Task {task['uuid']} failed, will retry ({retry_count + 1}/{max_retries}): {e}")
            else:
                await self._mark_task_failed(task, str(e))
                print(f"❌ Task {task['uuid']} failed permanently: {e}")

    # ---- Database task operations ----

    async def _fetch_ready_tasks_db(self) -> list:
        """Fetch pending tasks from DB where dependencies are met."""
        try:
            from database.connection import get_db
            from database.models import AgentTask
            from sqlalchemy import select, or_

            async with get_db() as db:
                query = (
                    select(AgentTask)
                    .where(AgentTask.status == "pending")
                    .where(
                        or_(
                            AgentTask.scheduled_for.is_(None),
                            AgentTask.scheduled_for <= datetime.utcnow()
                        )
                    )
                    .order_by(
                        # Priority ordering: urgent > high > normal > low
                        AgentTask.priority.desc(),
                        AgentTask.created_at.asc()
                    )
                    .limit(10)
                )
                result = await db.execute(query)
                rows = result.scalars().all()

                tasks = []
                for row in rows:
                    # Check dependencies
                    deps = row.depends_on or []
                    if deps:
                        deps_met = await self._check_dependencies(db, deps)
                        if not deps_met:
                            continue

                    tasks.append({
                        "uuid": row.uuid,
                        "source_agent": row.source_agent,
                        "target_agent": row.target_agent,
                        "task_type": row.task_type,
                        "priority": row.priority,
                        "params": row.params,
                        "depends_on": row.depends_on,
                        "parent_task_id": row.parent_task_id,
                        "retry_count": row.retry_count,
                        "max_retries": row.max_retries,
                    })

                return tasks
        except Exception as e:
            print(f"⚠️ DB fetch failed: {e}")
            return []

    async def _check_dependencies(self, db, dep_uuids: list) -> bool:
        """Check if all dependency tasks are completed."""
        from database.models import AgentTask
        from sqlalchemy import select

        for dep_uuid in dep_uuids:
            query = select(AgentTask.status).where(AgentTask.uuid == dep_uuid)
            result = await db.execute(query)
            status = result.scalar_one_or_none()
            if status != "completed":
                return False
        return True

    async def _mark_task_in_progress(self, task: dict):
        if DATABASE_AVAILABLE:
            try:
                from database.connection import get_db
                from database.models import AgentTask
                from sqlalchemy import update

                async with get_db() as db:
                    await db.execute(
                        update(AgentTask)
                        .where(AgentTask.uuid == task["uuid"])
                        .values(status="in_progress", started_at=datetime.utcnow())
                    )
            except Exception as e:
                print(f"⚠️ DB update failed: {e}")
        else:
            self._update_memory_task(task["uuid"], {"status": "in_progress"})

    async def _mark_task_completed(self, task: dict, result: dict):
        if DATABASE_AVAILABLE:
            try:
                from database.connection import get_db
                from database.models import AgentTask
                from sqlalchemy import update

                async with get_db() as db:
                    await db.execute(
                        update(AgentTask)
                        .where(AgentTask.uuid == task["uuid"])
                        .values(
                            status="completed",
                            result=result,
                            completed_at=datetime.utcnow()
                        )
                    )
            except Exception as e:
                print(f"⚠️ DB update failed: {e}")
        else:
            self._update_memory_task(task["uuid"], {"status": "completed", "result": result})

    async def _mark_task_failed(self, task: dict, error: str):
        if DATABASE_AVAILABLE:
            try:
                from database.connection import get_db
                from database.models import AgentTask
                from sqlalchemy import update

                async with get_db() as db:
                    await db.execute(
                        update(AgentTask)
                        .where(AgentTask.uuid == task["uuid"])
                        .values(
                            status="failed",
                            error_message=error,
                            completed_at=datetime.utcnow()
                        )
                    )
            except Exception as e:
                print(f"⚠️ DB update failed: {e}")
        else:
            self._update_memory_task(task["uuid"], {"status": "failed", "error_message": error})

    async def _mark_task_retry(self, task: dict, error: str):
        if DATABASE_AVAILABLE:
            try:
                from database.connection import get_db
                from database.models import AgentTask
                from sqlalchemy import update

                async with get_db() as db:
                    await db.execute(
                        update(AgentTask)
                        .where(AgentTask.uuid == task["uuid"])
                        .values(
                            status="pending",
                            error_message=error,
                            retry_count=task.get("retry_count", 0) + 1
                        )
                    )
            except Exception as e:
                print(f"⚠️ DB update failed: {e}")
        else:
            self._update_memory_task(task["uuid"], {
                "status": "pending",
                "retry_count": task.get("retry_count", 0) + 1
            })

    # ---- In-memory fallback ----

    def _fetch_ready_tasks_memory(self) -> list:
        """Fetch tasks from in-memory store (local dev fallback)."""
        from .base_agent import BaseAgent
        if not hasattr(BaseAgent, '_memory_tasks'):
            return []

        ready = []
        for task in BaseAgent._memory_tasks:
            if task["status"] != "pending":
                continue
            if task.get("scheduled_for") and task["scheduled_for"] > datetime.utcnow().isoformat():
                continue

            # Check dependencies
            deps = task.get("depends_on", [])
            if deps:
                all_done = all(
                    any(t["uuid"] == d and t["status"] == "completed" for t in BaseAgent._memory_tasks)
                    for d in deps
                )
                if not all_done:
                    continue

            ready.append(task)

        return ready[:10]

    def _update_memory_task(self, uuid: str, updates: dict):
        from .base_agent import BaseAgent
        if not hasattr(BaseAgent, '_memory_tasks'):
            return
        for task in BaseAgent._memory_tasks:
            if task["uuid"] == uuid:
                task.update(updates)
                break

    # ---- Force run ----

    async def force_run(self) -> dict:
        """Force an immediate processing cycle. Returns stats."""
        self._load_agents()
        await self.process_cycle()
        return {
            "status": "completed",
            "tasks_processed": self.tasks_processed,
            "last_run_at": self.last_run_at.isoformat() if self.last_run_at else None,
            "registered_agents": list(self.agents.keys()),
        }

    def get_status(self) -> dict:
        """Get orchestrator status."""
        return {
            "is_running": self.is_running,
            "last_run_at": self.last_run_at.isoformat() if self.last_run_at else None,
            "tasks_processed": self.tasks_processed,
            "interval_seconds": self.interval_seconds,
            "registered_agents": list(self.agents.keys()),
        }


# Global orchestrator instance
_orchestrator: Optional[AgentOrchestrator] = None


def get_orchestrator() -> AgentOrchestrator:
    """Get or create the global orchestrator instance."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = AgentOrchestrator()
    return _orchestrator
