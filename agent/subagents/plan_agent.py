"""
Plan subagent for generating and managing plans.

Specializes in creating structured plans from goals, analyzing
dependencies, and breaking down complex tasks.
"""

import json
import re
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime

from .base import Subagent, SubagentMetadata


class PlanAgent(Subagent):
    """Subagent for planning and task breakdown."""

    @classmethod
    def _default_metadata(cls) -> SubagentMetadata:
        return SubagentMetadata(
            name="plan",
            description="Generate structured plans from goals, analyze dependencies, and break down complex tasks.",
            capabilities=[
                "goal_analysis",
                "task_breakdown",
                "dependency_analysis",
                "effort_estimation",
                "risk_assessment",
                "plan_generation"
            ],
            input_schema={
                "type": "object",
                "properties": {
                    "goal": {
                        "type": "string",
                        "description": "Goal or objective to plan for"
                    },
                    "scope": {
                        "type": "string",
                        "description": "Scope of the plan",
                        "default": "general"
                    },
                    "complexity": {
                        "type": "string",
                        "description": "Estimated complexity",
                        "enum": ["simple", "medium", "complex", "unknown"],
                        "default": "unknown"
                    },
                    "constraints": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Constraints or requirements"
                    },
                    "deliverables": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Expected deliverables"
                    }
                },
                "required": ["goal"]
            },
            output_schema={
                "type": "object",
                "properties": {
                    "success": {"type": "boolean"},
                    "plan": {
                        "type": "object",
                        "properties": {
                            "goal": {"type": "string"},
                            "scope": {"type": "string"},
                            "steps": {"type": "array"},
                            "dependencies": {"type": "array"},
                            "estimated_effort": {"type": "string"},
                            "risks": {"type": "array"},
                            "resources": {"type": "array"}
                        }
                    },
                    "summary": {"type": "string"},
                    "execution_time": {"type": "number"}
                },
                "required": ["success"]
            },
            categories=["planning", "analysis"],
            max_execution_time=120,
            requires_isolation=False
        )

    def __init__(self, metadata: Optional[SubagentMetadata] = None):
        super().__init__(metadata)
        self.templates = self._load_templates()

    def _load_templates(self) -> Dict[str, Any]:
        """Load plan templates for different scopes."""
        return {
            "code": {
                "steps": ["Analysis", "Design", "Implementation", "Testing", "Documentation"],
                "questions": [
                    "What are the technical requirements?",
                    "What architecture patterns are appropriate?",
                    "What testing strategy will be used?",
                    "What documentation is needed?"
                ]
            },
            "infrastructure": {
                "steps": ["Assessment", "Design", "Implementation", "Migration", "Validation"],
                "questions": [
                    "What are the current pain points?",
                    "What scalability requirements exist?",
                    "What migration strategy is needed?",
                    "How will success be measured?"
                ]
            },
            "testing": {
                "steps": ["Test Planning", "Test Design", "Test Implementation", "Test Execution", "Results Analysis"],
                "questions": [
                    "What are the acceptance criteria?",
                    "What test coverage is required?",
                    "What automation tools are needed?",
                    "How will defects be tracked?"
                ]
            },
            "documentation": {
                "steps": ["Research", "Outline", "Draft", "Review", "Publish"],
                "questions": [
                    "Who is the target audience?",
                    "What format is required?",
                    "What review process will be used?",
                    "Where will it be published?"
                ]
            },
            "general": {
                "steps": ["Research", "Planning", "Execution", "Review", "Delivery"],
                "questions": [
                    "What is the desired outcome?",
                    "What resources are available?",
                    "What constraints exist?",
                    "How will success be measured?"
                ]
            }
        }

    def execute(self, task_description: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate a plan for the given goal.

        Args:
            task_description: Description of the planning task.
            parameters: Planning parameters.

        Returns:
            Generated plan.
        """
        import time
        start_time = time.time()

        try:
            self.validate_input(parameters)

            goal = parameters.get("goal", "")
            scope = parameters.get("scope", "general")
            complexity = parameters.get("complexity", "unknown")
            constraints = parameters.get("constraints", [])
            deliverables = parameters.get("deliverables", [])

            # Generate plan
            plan = self._generate_plan(goal, scope, complexity, constraints, deliverables)

            # Create summary
            summary = self._create_summary(plan, complexity)

            execution_time = time.time() - start_time

            return {
                "success": True,
                "plan": plan,
                "summary": summary,
                "execution_time": execution_time
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "execution_time": time.time() - start_time
            }

    def _generate_plan(self, goal: str, scope: str, complexity: str,
                      constraints: List[str], deliverables: List[str]) -> Dict[str, Any]:
        """Generate a structured plan."""
        template = self.templates.get(scope, self.templates["general"])

        # Analyze goal to determine steps
        steps = self._break_down_goal(goal, template["steps"], complexity)

        # Analyze dependencies
        dependencies = self._analyze_dependencies(steps)

        # Estimate effort
        effort = self._estimate_effort(steps, complexity)

        # Identify risks
        risks = self._identify_risks(goal, scope, complexity, constraints)

        # Determine resources
        resources = self._identify_resources(scope, steps)

        return {
            "goal": goal,
            "scope": scope,
            "complexity": complexity,
            "steps": steps,
            "dependencies": dependencies,
            "estimated_effort": effort,
            "risks": risks,
            "resources": resources,
            "constraints": constraints,
            "deliverables": deliverables,
            "generated_at": datetime.now().isoformat(),
            "key_questions": template["questions"]
        }

    def _break_down_goal(self, goal: str, template_steps: List[str],
                        complexity: str) -> List[Dict[str, Any]]:
        """Break down goal into actionable steps."""
        steps = []

        # Determine number of steps based on complexity
        step_count_map = {
            "simple": 3,
            "medium": 5,
            "complex": 8,
            "unknown": 5
        }
        num_steps = step_count_map.get(complexity, 5)

        # Use template steps as categories, create substeps
        for i, category in enumerate(template_steps[:num_steps]):
            step_num = i + 1

            # Generate step description based on goal and category
            description = self._generate_step_description(goal, category, step_num, num_steps)

            # Estimate time based on complexity and step position
            time_estimate = self._estimate_step_time(complexity, step_num, num_steps)

            step = {
                "id": f"step_{step_num}",
                "category": category,
                "description": description,
                "estimated_time": time_estimate,
                "priority": self._determine_priority(step_num, num_steps),
                "completion_criteria": f"Complete {category.lower()} for {goal[:50]}..."
            }
            steps.append(step)

        return steps

    def _generate_step_description(self, goal: str, category: str,
                                  step_num: int, total_steps: int) -> str:
        """Generate description for a step."""
        actions = {
            "Analysis": "Analyze requirements and constraints for",
            "Design": "Design solution architecture for",
            "Implementation": "Implement core functionality for",
            "Testing": "Test and validate implementation of",
            "Documentation": "Document processes and outcomes for",
            "Research": "Research best practices and existing solutions for",
            "Planning": "Create detailed execution plan for",
            "Execution": "Execute the planned activities for",
            "Review": "Review progress and adjust approach for",
            "Delivery": "Finalize and deliver results for",
            "Assessment": "Assess current state and requirements for",
            "Migration": "Migrate systems or data for",
            "Validation": "Validate results and outcomes for"
        }

        action = actions.get(category, "Work on")
        return f"{action} {goal[:100]}{'...' if len(goal) > 100 else ''}"

    def _estimate_step_time(self, complexity: str, step_num: int,
                           total_steps: int) -> str:
        """Estimate time for a step."""
        base_times = {
            "simple": {"min": 0.5, "max": 2},  # hours
            "medium": {"min": 2, "max": 8},
            "complex": {"min": 4, "max": 20},
            "unknown": {"min": 1, "max": 10}
        }

        base = base_times.get(complexity, base_times["unknown"])

        # Adjust based on step position (middle steps often take longer)
        position_factor = 1.0
        if step_num == 1:
            position_factor = 0.8  # First step often quicker (setup)
        elif step_num == total_steps:
            position_factor = 0.7  # Last step often quicker (wrapping up)
        elif step_num > total_steps / 2:
            position_factor = 1.2  # Middle steps often more complex

        min_time = base["min"] * position_factor
        max_time = base["max"] * position_factor

        if max_time < 4:
            return f"{min_time:.1f}-{max_time:.1f} hours"
        elif max_time < 40:
            days_min = min_time / 8
            days_max = max_time / 8
            return f"{days_min:.1f}-{days_max:.1f} days"
        else:
            weeks_min = min_time / 40
            weeks_max = max_time / 40
            return f"{weeks_min:.1f}-{weeks_max:.1f} weeks"

    def _determine_priority(self, step_num: int, total_steps: int) -> str:
        """Determine priority for a step."""
        if step_num == 1:
            return "high"  # First step is critical
        elif step_num <= 3:
            return "medium-high"
        elif step_num >= total_steps - 1:
            return "medium-low"  # Final steps
        else:
            return "medium"

    def _analyze_dependencies(self, steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Analyze dependencies between steps."""
        dependencies = []

        for i, step in enumerate(steps):
            step_id = step["id"]

            # First step has no dependencies
            if i == 0:
                continue

            # Simple dependency: each step depends on the previous one
            prev_step = steps[i - 1]
            dependencies.append({
                "from": step_id,
                "to": prev_step["id"],
                "type": "finish-to-start",
                "description": f"{step['category']} requires completion of {prev_step['category']}"
            })

            # Some steps might have additional dependencies
            if i >= 2 and "Design" in step["category"]:
                # Design might need input from analysis (step 1)
                dependencies.append({
                    "from": step_id,
                    "to": "step_1",
                    "type": "finish-to-start",
                    "description": f"{step['category']} requires input from initial analysis"
                })

        return dependencies

    def _estimate_effort(self, steps: List[Dict[str, Any]], complexity: str) -> str:
        """Estimate total effort."""
        # Parse time estimates from steps
        total_hours = 0

        for step in steps:
            time_str = step["estimated_time"]
            # Parse time string like "2.0-8.0 hours" or "0.5-2.0 days"
            if "hours" in time_str:
                numbers = re.findall(r"[\d.]+", time_str)
                if len(numbers) >= 2:
                    avg = (float(numbers[0]) + float(numbers[1])) / 2
                    total_hours += avg
            elif "days" in time_str:
                numbers = re.findall(r"[\d.]+", time_str)
                if len(numbers) >= 2:
                    avg_days = (float(numbers[0]) + float(numbers[1])) / 2
                    total_hours += avg_days * 8  # 8 hours per day
            elif "weeks" in time_str:
                numbers = re.findall(r"[\d.]+", time_str)
                if len(numbers) >= 2:
                    avg_weeks = (float(numbers[0]) + float(numbers[1])) / 2
                    total_hours += avg_weeks * 40  # 40 hours per week

        # Format total effort
        if total_hours < 8:
            return f"{total_hours:.1f} hours"
        elif total_hours < 40:
            return f"{total_hours/8:.1f} days"
        else:
            return f"{total_hours/40:.1f} weeks"

    def _identify_risks(self, goal: str, scope: str, complexity: str,
                       constraints: List[str]) -> List[Dict[str, Any]]:
        """Identify potential risks."""
        risks = []

        common_risks = [
            {
                "risk": "Scope creep",
                "description": "Requirements expanding beyond initial scope",
                "impact": "medium",
                "mitigation": "Define clear acceptance criteria and change control process"
            },
            {
                "risk": "Technical complexity",
                "description": "Unforeseen technical challenges",
                "impact": "high" if complexity in ["complex", "unknown"] else "medium",
                "mitigation": "Spike/prototype risky areas early, allocate contingency time"
            },
            {
                "risk": "Resource constraints",
                "description": "Insufficient time, budget, or expertise",
                "impact": "high" if constraints else "medium",
                "mitigation": "Prioritize critical path, consider external resources"
            },
            {
                "risk": "Dependency delays",
                "description": "Delays in dependent tasks or external systems",
                "impact": "medium",
                "mitigation": "Identify critical dependencies early, establish communication channels"
            },
            {
                "risk": "Quality issues",
                "description": "Inadequate testing or quality assurance",
                "impact": "medium",
                "mitigation": "Implement automated testing, peer reviews, quality gates"
            }
        ]

        # Add scope-specific risks
        if scope == "code":
            risks.append({
                "risk": "Integration issues",
                "description": "Problems integrating with existing systems",
                "impact": "high",
                "mitigation": "Test integration early, use mocking/stubbing"
            })

        if "tight deadline" in " ".join(constraints).lower():
            risks.append({
                "risk": "Schedule pressure",
                "description": "Insufficient time for proper implementation",
                "impact": "high",
                "mitigation": "Focus on MVP, defer non-essential features"
            })

        return common_risks + risks[:2]  # Limit to most relevant risks

    def _identify_resources(self, scope: str, steps: List[Dict[str, Any]]) -> List[str]:
        """Identify required resources."""
        resources = []

        # General resources
        resources.extend([
            "Project management tool (e.g., Jira, Trello, GitHub Projects)",
            "Version control system (Git)",
            "Communication platform (Slack, Teams, email)"
        ])

        # Scope-specific resources
        if scope == "code":
            resources.extend([
                "Development environment",
                "Testing framework",
                "CI/CD pipeline",
                "Documentation tools"
            ])
        elif scope == "infrastructure":
            resources.extend([
                "Infrastructure as Code tools",
                "Monitoring systems",
                "Backup solutions"
            ])
        elif scope == "testing":
            resources.extend([
                "Test management tool",
                "Automation framework",
                "Performance testing tools"
            ])

        # Add based on steps
        for step in steps:
            if "Design" in step["category"]:
                resources.append("Design/architecture documentation tools")
                break

        return list(set(resources))  # Remove duplicates

    def _create_summary(self, plan: Dict[str, Any], complexity: str) -> str:
        """Create human-readable summary of the plan."""
        step_count = len(plan["steps"])
        risk_count = len(plan["risks"])
        resource_count = len(plan["resources"])

        summary = f"""📋 **Plan Summary: {plan['goal'][:100]}...**

**Overview:**
• **Scope:** {plan['scope']}
• **Complexity:** {complexity}
• **Steps:** {step_count} key steps
• **Estimated Effort:** {plan['estimated_effort']}

**Key Steps:**
"""

        # Add first 3 steps
        for i, step in enumerate(plan["steps"][:3], 1):
            summary += f"{i}. **{step['category']}**: {step['description'][:80]}... ({step['estimated_time']})\n"

        if step_count > 3:
            summary += f"... and {step_count - 3} more steps\n"

        summary += f"""
**Risks Identified:** {risk_count} potential risks
**Resources Needed:** {resource_count} key resources

**Next Actions:**
1. Review and refine steps
2. Assign responsibilities
3. Set up tracking for dependencies
4. Schedule regular review points"""

        return summary