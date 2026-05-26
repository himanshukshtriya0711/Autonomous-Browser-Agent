"""
backend/agents/orchestrator.py
================================
LangGraph Orchestrator — the central nervous system of the agent.

Defines a StateGraph that wires together:
  PlannerNode → BrowserNode → ExtractorNode → MemoryNode → OutputNode

With conditional edges for:
  - Routing by task_type (job_search, pdf_analysis, general, etc.)
  - Recovery on failures
  - Step iteration loop

State schema:
  - task_id, prompt, plan, current_step, results, logs, status, error
"""

import asyncio
from typing import Any, Callable, Dict, List, Literal, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from backend.agents.browser_agent import BrowserAgent
from backend.agents.extraction_agent import ExtractionAgent
from backend.agents.memory_agent import MemoryAgent
from backend.agents.planner_agent import PlannerAgent
from backend.agents.recovery_agent import RecoveryAgent
from backend.tools.job_search_tool import JobSearchTool
from backend.tools.pdf_tool import PDFTool
from backend.utils.helpers import utc_now_iso
from backend.utils.logger import get_logger

logger = get_logger(__name__)


# ── State definition ──────────────────────────────────────────────────────────

class AgentState(TypedDict):
    """Shared state passed between all LangGraph nodes."""
    task_id: str
    prompt: str
    plan: Dict[str, Any]
    current_step_index: int
    results: List[Any]
    all_jobs: List[Dict[str, Any]]
    logs: List[str]
    status: str             # "running" | "completed" | "failed"
    error: Optional[str]
    max_steps: int
    headless: bool
    steps_completed: int


# ── Orchestrator ──────────────────────────────────────────────────────────────

class AgentOrchestrator:
    """
    Builds and runs a LangGraph StateGraph for autonomous task execution.
    Each node is an async function that reads from and writes to AgentState.
    """

    def __init__(
        self,
        task_id: str,
        log_callback: Optional[Callable[[str, str], None]] = None,
    ):
        self.task_id = task_id
        self.log = log_callback or (lambda level, msg: None)

        # Initialise agents (shared across all nodes)
        self.planner   = PlannerAgent(log_callback=self.log)
        self.extractor = ExtractionAgent(log_callback=self.log)
        self.memory    = MemoryAgent(log_callback=self.log)
        self.recovery  = RecoveryAgent(log_callback=self.log)
        self.pdf_tool  = PDFTool(log_callback=self.log)
        self.job_tool  = JobSearchTool(log_callback=self.log)

        self._graph = self._build_graph()

    # ── Graph construction ────────────────────────────────────────────────────

    def _build_graph(self) -> Any:
        """Assemble the LangGraph StateGraph."""
        graph = StateGraph(AgentState)

        # Register nodes
        graph.add_node("planner",   self._planner_node)
        graph.add_node("router",    self._router_node)
        graph.add_node("job_search", self._job_search_node)
        graph.add_node("browser",   self._browser_node)
        graph.add_node("pdf",       self._pdf_node)
        graph.add_node("extractor", self._extractor_node)
        graph.add_node("memory",    self._memory_node)
        graph.add_node("output",    self._output_node)

        # Entry → Planner → Router
        graph.add_edge(START, "planner")
        graph.add_edge("planner", "router")

        # Router decides which execution path to take
        graph.add_conditional_edges(
            "router",
            self._route_by_task_type,
            {
                "job_search": "job_search",
                "pdf_analysis": "pdf",
                "browser": "browser",
            },
        )

        # All paths converge at extractor → memory → output
        graph.add_edge("job_search", "extractor")
        graph.add_edge("browser",    "extractor")
        graph.add_edge("pdf",        "extractor")

        graph.add_edge("extractor", "memory")
        graph.add_edge("memory",    "output")
        graph.add_edge("output",    END)

        return graph.compile()

    # ── Node implementations ──────────────────────────────────────────────────

    async def _planner_node(self, state: AgentState) -> AgentState:
        """Generate execution plan from user prompt."""
        self.log("info", "🧠 Planner node: generating execution plan…")
        plan = await self.planner.plan(state["prompt"])
        return {**state, "plan": plan, "current_step_index": 0}

    async def _router_node(self, state: AgentState) -> AgentState:
        """Pass-through node — routing logic is in the conditional edge."""
        task_type = state["plan"].get("task_type", "general")
        self.log("info", f"🔀 Router: task type = {task_type}")
        return state

    def _route_by_task_type(self, state: AgentState) -> str:
        """Conditional edge: route based on task_type from plan."""
        task_type = state["plan"].get("task_type", "general")
        if task_type == "job_search":
            return "job_search"
        elif task_type == "pdf_analysis":
            return "pdf"
        else:
            return "browser"

    async def _job_search_node(self, state: AgentState) -> AgentState:
        """Execute job search across multiple portals."""
        self.log("info", "🔍 Job search node: searching portals…")
        plan = state["plan"]
        context = plan.get("context", {})
        keywords = " ".join(context.get("keywords", [state["prompt"].split()[0]]))
        target_sites = context.get("target_sites", [])

        all_jobs = []
        try:
            jobs = await self.job_tool.search(
                query=keywords,
                sites=target_sites,
                headless=state["headless"],
                max_results=30,
            )
            all_jobs.extend(jobs)
            self.log("success", f"✅ Found {len(all_jobs)} jobs total")
        except Exception as exc:
            self.log("error", f"❌ Job search failed: {exc}")
            logger.error(f"Job search node error: {exc}")

        return {
            **state,
            "all_jobs": all_jobs,
            "results": [{"type": "jobs", "data": all_jobs}],
            "steps_completed": state["steps_completed"] + 1,
        }

    async def _browser_node(self, state: AgentState) -> AgentState:
        """Execute general browser navigation task."""
        self.log("info", "🌐 Browser node: executing navigation plan…")
        plan = state["plan"]
        steps = plan.get("steps", [])

        browser_agent = BrowserAgent(
            log_callback=self.log,
            headless=state["headless"],
        )

        try:
            result = await browser_agent.run(
                task=state["prompt"],
                plan_steps=steps,
                max_steps=state["max_steps"],
            )
            return {
                **state,
                "results": [result],
                "steps_completed": state["steps_completed"] + result.get("steps_completed", 1),
            }
        except Exception as exc:
            self.log("error", f"❌ Browser node failed: {exc}")
            return {**state, "error": str(exc), "status": "failed"}

    async def _pdf_node(self, state: AgentState) -> AgentState:
        """Download and analyse PDF documents."""
        self.log("info", "📄 PDF node: processing documents…")
        plan = state["plan"]
        steps = plan.get("steps", [])

        # Find PDF URL from plan steps
        pdf_url = None
        for step in steps:
            target = step.get("target", "")
            if "pdf" in target.lower() or target.startswith("http"):
                pdf_url = target
                break

        results = []
        if pdf_url:
            try:
                pdf_result = await self.pdf_tool.download_and_analyze(pdf_url)
                results.append(pdf_result)
                self.log("success", "✅ PDF analysed successfully")
            except Exception as exc:
                self.log("error", f"❌ PDF processing failed: {exc}")
        else:
            self.log("warn", "⚠️ No PDF URL found in plan")

        return {**state, "results": results, "steps_completed": state["steps_completed"] + 1}

    async def _extractor_node(self, state: AgentState) -> AgentState:
        """Post-process and structure raw results."""
        self.log("info", "📊 Extractor node: structuring results…")
        results = state.get("results", [])
        all_jobs = state.get("all_jobs", [])

        # If results contain raw page text, extract from it
        structured = []
        for result in results:
            if isinstance(result, dict):
                if result.get("type") == "jobs":
                    structured.extend(result.get("data", []))
                elif "content" in result:
                    extracted = await self.extractor.extract_general(result["content"])
                    structured.append(extracted)
                elif "results" in result:
                    for sub in result["results"]:
                        if isinstance(sub, dict) and "content" in sub:
                            jobs = await self.extractor.extract_jobs(sub["content"], sub.get("url", ""))
                            all_jobs.extend(jobs)
                        structured.append(sub)
                else:
                    structured.append(result)

        return {**state, "results": structured, "all_jobs": all_jobs}

    async def _memory_node(self, state: AgentState) -> AgentState:
        """Store results in persistent memory."""
        self.log("info", "💾 Memory node: persisting results…")

        # Store task result
        await self.memory.store_task_result(
            task_id=state["task_id"],
            prompt=state["prompt"],
            result=state["results"],
        )

        # Store jobs if any
        all_jobs = state.get("all_jobs", [])
        if all_jobs:
            stored = await self.memory.store_jobs(all_jobs)
            self.log("info", f"💾 Stored {stored} new jobs in memory")

        # Record search
        await self.memory.store_search(
            query=state["prompt"],
            results_summary=f"{len(state['results'])} results, {len(all_jobs)} jobs",
        )

        return state

    async def _output_node(self, state: AgentState) -> AgentState:
        """Finalise state with clean output."""
        self.log("info", "📦 Output node: packaging final results…")
        return {**state, "status": "completed"}

    # ── Entry point ───────────────────────────────────────────────────────────

    async def execute(
        self,
        prompt: str,
        max_steps: int = 20,
        headless: bool = False,
    ) -> Dict[str, Any]:
        """
        Run the complete LangGraph workflow for a user prompt.
        Returns structured result dict.
        """
        initial_state: AgentState = {
            "task_id": self.task_id,
            "prompt": prompt,
            "plan": {},
            "current_step_index": 0,
            "results": [],
            "all_jobs": [],
            "logs": [],
            "status": "running",
            "error": None,
            "max_steps": max_steps,
            "headless": headless,
            "steps_completed": 0,
        }

        self.log("info", "🎯 LangGraph orchestrator starting…")
        logger.info(f"Orchestrator executing task {self.task_id}: {prompt[:80]}")

        try:
            final_state = await self._graph.ainvoke(initial_state)

            return {
                "task_id": self.task_id,
                "prompt": prompt,
                "status": final_state.get("status", "completed"),
                "task_type": final_state.get("plan", {}).get("task_type", "general"),
                "jobs": final_state.get("all_jobs", []),
                "results": final_state.get("results", []),
                "steps_completed": final_state.get("steps_completed", 0),
                "error": final_state.get("error"),
                "completed_at": utc_now_iso(),
            }

        except Exception as exc:
            logger.exception(f"Orchestrator failed: {exc}")
            return {
                "task_id": self.task_id,
                "status": "failed",
                "error": str(exc),
                "results": [],
                "jobs": [],
                "steps_completed": 0,
                "completed_at": utc_now_iso(),
            }
