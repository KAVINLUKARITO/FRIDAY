#!/usr/bin/env python3
"""
AIWorker 2.0 — Tutorial Generator
Personalized, adaptive learning system for human operators.

Usage:
    python tutorial_generator.py first-boot
    python tutorial_generator.py safety
    python tutorial_generator.py patch-review
    python tutorial_generator.py mesh
    python tutorial_generator.py troubleshoot --symptom "high_memory"
"""

import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any
from enum import Enum


class ExpertiseLevel(Enum):
    """User expertise levels."""
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class ContentFormat(Enum):
    """Content delivery formats."""
    TEXT = "text"
    INTERACTIVE = "interactive"
    HTML = "html"
    AUDIO_SCRIPT = "audio"


@dataclass
class UserModel:
    """Tracks human's expertise and difficulties."""
    expertise_level: ExpertiseLevel = ExpertiseLevel.BEGINNER
    observed_struggles: List[str] = field(default_factory=list)
    preferred_format: ContentFormat = ContentFormat.TEXT
    language: str = "en"
    completed_tutorials: List[str] = field(default_factory=list)
    approval_times: List[float] = field(default_factory=list)
    veto_reasons: List[str] = field(default_factory=list)
    help_requests: List[str] = field(default_factory=list)
    
    def update_from_interaction(self, interaction: dict) -> None:
        """Update model based on observed behavior."""
        # Track approval time
        if "approval_time" in interaction:
            self.approval_times.append(interaction["approval_time"])
        
        # Track vetoes
        if "veto_reason" in interaction:
            self.veto_reasons.append(interaction["veto_reason"])
        
        # Track help requests
        if "help_topic" in interaction:
            self.help_requests.append(interaction["help_topic"])
        
        # Detect struggles
        self._detect_struggles()
        
        # Update expertise level
        self._update_expertise()
    
    def _detect_struggles(self) -> None:
        """Identify topics where user is slow/uncertain."""
        # Slow approvals on memory patches
        if len(self.approval_times) > 5:
            avg_time = sum(self.approval_times[-5:]) / 5
            if avg_time > 60:  # More than 60 seconds
                if "patch_review" not in self.observed_struggles:
                    self.observed_struggles.append("patch_review")
        
        # Multiple vetoes on same topic
        from collections import Counter
        veto_counts = Counter(self.veto_reasons)
        for reason, count in veto_counts.items():
            if count >= 3:
                struggle = f"understanding_{reason}"
                if struggle not in self.observed_struggles:
                    self.observed_struggles.append(struggle)
    
    def _update_expertise(self) -> None:
        """Update expertise based on completed tutorials."""
        completed = len(self.completed_tutorials)
        if completed >= 10:
            self.expertise_level = ExpertiseLevel.ADVANCED
        elif completed >= 5:
            self.expertise_level = ExpertiseLevel.INTERMEDIATE
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "expertise_level": self.expertise_level.value,
            "observed_struggles": self.observed_struggles,
            "preferred_format": self.preferred_format.value,
            "language": self.language,
            "completed_tutorials": self.completed_tutorials,
            "approval_times": self.approval_times[-10:],  # Keep last 10
            "veto_reasons": self.veto_reasons[-10:],
            "help_requests": self.help_requests[-10:]
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "UserModel":
        """Create from dictionary."""
        return cls(
            expertise_level=ExpertiseLevel(data.get("expertise_level", "beginner")),
            observed_struggles=data.get("observed_struggles", []),
            preferred_format=ContentFormat(data.get("preferred_format", "text")),
            language=data.get("language", "en"),
            completed_tutorials=data.get("completed_tutorials", []),
            approval_times=data.get("approval_times", []),
            veto_reasons=data.get("veto_reasons", []),
            help_requests=data.get("help_requests", [])
        )


@dataclass
class Tutorial:
    """Generated learning content."""
    title: str
    content: str
    estimated_minutes: int
    prerequisites: List[str]
    interactive_steps: List[dict]
    difficulty: ExpertiseLevel
    topic: str
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "title": self.title,
            "content": self.content,
            "estimated_minutes": self.estimated_minutes,
            "prerequisites": self.prerequisites,
            "interactive_steps": self.interactive_steps,
            "difficulty": self.difficulty.value,
            "topic": self.topic
        }


class TutorialTemplate:
    """Base template for tutorials."""
    
    def __init__(self, topic: str, title: str, base_content: str,
                 estimated_minutes: int, prerequisites: List[str],
                 interactive_steps: List[dict], difficulty: ExpertiseLevel):
        self.topic = topic
        self.title = title
        self.base_content = base_content
        self.estimated_minutes = estimated_minutes
        self.prerequisites = prerequisites
        self.interactive_steps = interactive_steps
        self.difficulty = difficulty


class TutorialLibrary:
    """Library of tutorial templates."""
    
    TEMPLATES: Dict[str, TutorialTemplate] = {
        "first_boot": TutorialTemplate(
            topic="first_boot",
            title="Welcome to AIWorker 2.0",
            base_content="""
# Welcome to AIWorker 2.0

AIWorker is a self-improving autonomous AI agent that remains forever under **your control**.

## What AIWorker Does

- **Writes its own code** to become better at helping you
- **Researches and learns** from the internet and its experiences  
- **Asks for your approval** before making any changes
- **Operates safely** with multiple layers of protection

## Your Role

You are the **human supervisor**. AIWorker:
- Proposes improvements
- Shows you exactly what will change
- Waits for your approval (yes/no)
- Learns from your feedback

## Safety First

AIWorker has three layers of protection:
1. **Automatic checks** - Dangerous code is blocked automatically
2. **Your approval** - All changes require your explicit yes
3. **Kill switch** - Type `touch .aiworker_kill` to stop everything

## First Goal

Let's set your first improvement goal. What would you like AIWorker to help you with?

Examples:
- "Improve the research module to search academic papers"
- "Add a feature to analyze CSV files"
- "Create a better dashboard for monitoring"

Type your goal: ________________
""",
            estimated_minutes=5,
            prerequisites=[],
            interactive_steps=[
                {"prompt": "What would you like AIWorker to help with?", "type": "text_input"},
                {"prompt": "Confirm you understand AIWorker asks before changing anything", "type": "confirm"}
            ],
            difficulty=ExpertiseLevel.BEGINNER
        ),
        
        "safety": TutorialTemplate(
            topic="safety",
            title="Understanding AIWorker Safety",
            base_content="""
# AIWorker Safety System

AIWorker uses a **three-tier safety cage** to protect you:

## Tier 1: Automatic Code Analysis

Before any code runs, AIWorker checks:
- No `eval()` or `exec()` functions
- No `os.system()` calls
- No shell injection vulnerabilities
- Valid Python syntax

**This happens automatically** - you don't need to do anything.

## Tier 2: Your Approval

For any code change, AIWorker shows you:
- What file will be modified
- The exact changes (diff format)
- Why the change is being made

You type **yes** to approve or **no** to reject.

## Tier 3: Kill Switch

If anything goes wrong:

```bash
touch .aiworker_kill
```

This immediately stops all AIWorker activity.

## Practice: Approve a Safe Change

Here's a sample change:

```diff
--- a/config.py
+++ b/config.py
@@ -10,5 +10,5 @@
     "log_level": "INFO",
-    "max_iterations": 10,
+    "max_iterations": 20,
 }
```

This increases the daily iteration limit. Is this safe?

Type: **yes** (this is a safe configuration change)
""",
            estimated_minutes=10,
            prerequisites=["first_boot"],
            interactive_steps=[
                {"prompt": "Review the sample change above", "type": "read"},
                {"prompt": "Type 'yes' to approve this safe change", "type": "confirm"},
                {"prompt": "Practice: Create kill switch file", "type": "command", "command": "touch .aiworker_kill"},
                {"prompt": "Remove kill switch to continue", "type": "command", "command": "rm .aiworker_kill"}
            ],
            difficulty=ExpertiseLevel.BEGINNER
        ),
        
        "patch_review": TutorialTemplate(
            topic="patch_review",
            title="How to Review Code Changes",
            base_content="""
# Reviewing AIWorker Code Changes

Reading code diffs quickly is a key skill. Here's how:

## Understanding Diff Format

```diff
--- a/old_file.py    (minus = removed)
+++ b/new_file.py    (plus = added)
@@ -5,7 +5,7 @@    (line numbers)
     def old_function():
-        return 1    (this line removed)
+        return 2    (this line added)
```

## Quick Review Checklist

### 1. What file is changing?
- Config files → Usually safe
- Core modules → Review carefully
- New files → Check purpose

### 2. What's the pattern?
- **Adding features** → New functions, new options
- **Fixing bugs** → Small changes to existing code
- **Refactoring** → Moving code around

### 3. Red Flags
- `eval()`, `exec()`, `__import__()`
- File deletion operations
- Network requests to unknown hosts
- Password/key handling changes

## Time-Saving Tips

**Usually Safe:**
- Adding docstrings
- Increasing timeout values
- Adding log messages
- New research modules

**Review Carefully:**
- Changes to safety_cage.py
- Modifications to config.py defaults
- Any file deletion
- Network-related changes

## Practice Review

Review this change:

```diff
--- a/research/scraper.py
+++ b/research/scraper.py
@@ -45,6 +45,10 @@ def fetch_url(url):
     try:
         response = requests.get(url, timeout=30)
         return response.text
+    except requests.Timeout:
+        logger.warning(f"Timeout fetching {url}")
+        return None
     except Exception as e:
         logger.error(f"Error: {e}")
         return None
```

**Question:** What does this change do?

A) Adds timeout handling (safe)
B) Deletes files (dangerous)
C) Changes network behavior (review needed)

Answer: **A** - This adds specific handling for timeout errors. Safe to approve.
""",
            estimated_minutes=15,
            prerequisites=["safety"],
            interactive_steps=[
                {"prompt": "Review the practice diff above", "type": "read"},
                {"prompt": "What does the change do? (A/B/C)", "type": "choice", "options": ["A", "B", "C"], "correct": "A"},
                {"prompt": "Practice: Identify red flags in sample patches", "type": "exercise"}
            ],
            difficulty=ExpertiseLevel.INTERMEDIATE
        ),
        
        "mesh": TutorialTemplate(
            topic="mesh",
            title="Distributed Operation with Mesh",
            base_content="""
# AIWorker Mesh Network

The mesh allows multiple AIWorker instances to collaborate.

## When to Use Mesh

**Good reasons:**
- Large projects needing parallel work
- Specialized tasks (one for research, one for coding)
- Geographic distribution
- Redundancy

**Not recommended:**
- Small projects (adds complexity)
- Limited monitoring capability
- Unstable network connections

## Node Types

- **WORKER** - General purpose, executes tasks
- **SPECIALIST** - Optimized for specific tasks (research, coding, etc.)
- **COORDINATOR** - Manages task distribution

## Economic Considerations

Each node costs:
- VPS: $10-50/month
- Electricity: ~$5/month per node
- Network: Included with VPS

**Start with 1 node, add more when needed.**

## Adding Your First Node

```bash
# On new server
curl -sSL https://ark.aiworker/bootstrap.sh | bash

# Configure as worker
python3 -m aiworker.main config --role WORKER --coordinator <main-node-ip>
```

## Monitoring Multiple Nodes

Use the dashboard:
```
http://<coordinator>:8000/mesh
```

Shows:
- Node health
- Task distribution
- Network latency
- Resource usage

## Safety Note

More nodes = more complexity:
- Ensure you can monitor all nodes
- Each node needs approval for its changes
- Mesh consensus required for constitution changes
""",
            estimated_minutes=20,
            prerequisites=["patch_review"],
            interactive_steps=[
                {"prompt": "Consider: Do you need mesh for your use case?", "type": "confirm"},
                {"prompt": "Calculate: Cost for 3 nodes at $20/month each", "type": "text_input"},
                {"prompt": "Review mesh dashboard (if available)", "type": "optional"}
            ],
            difficulty=ExpertiseLevel.ADVANCED
        ),
        
        "troubleshooting_high_memory": TutorialTemplate(
            topic="troubleshooting",
            title="Troubleshooting: High Memory Usage",
            base_content="""
# Troubleshooting: High Memory Usage

## Symptoms
- System slowing down
- OOM (Out of Memory) errors
- Swapping to disk

## Diagnosis Steps

### 1. Check Current Usage
```bash
free -h                    # RAM usage
ps aux | grep aiworker     # AIWorker processes
du -sh aiworker/           # Disk usage
```

### 2. Identify Culprit
```bash
# Top memory consumers
ps aux --sort=-%mem | head -10

# Check ollama specifically
ollama ps                  # Loaded models
```

### 3. Common Causes

**Ollama using too much memory:**
- Multiple models loaded
- Large model (e.g., 70B parameter)
- Solution: Unload unused models

```bash
ollama stop <model-name>
```

**AIWorker checkpoint accumulation:**
- Old checkpoints not cleaned up
- Solution: Clean old checkpoints

```bash
find aiworker/checkpoints/ -mtime +7 -delete
```

**Memory leak in module:**
- Check logs for repeated errors
- Solution: Restart AIWorker

```bash
python3 -m aiworker.main restart
```

## Prevention

1. **Set memory limits in config:**
```json
{
  "ollama_memory_gb": 10,
  "max_loaded_models": 1
}
```

2. **Enable automatic cleanup:**
```json
{
  "checkpoint_retention_days": 7
}
```

3. **Monitor regularly:**
```bash
# Add to crontab for daily check
0 9 * * * free -h >> ~/memory.log
```

## When to Add RAM

If consistently using >80% of RAM:
- Current 4GB → Upgrade to 8GB
- Current 8GB → Upgrade to 16GB
- Current 16GB → Consider optimization first
""",
            estimated_minutes=15,
            prerequisites=["safety"],
            interactive_steps=[
                {"prompt": "Run: free -h and check your RAM usage", "type": "command", "command": "free -h"},
                {"prompt": "Run: ps aux --sort=-%mem | head -5", "type": "command", "command": "ps aux --sort=-%mem | head -5"},
                {"prompt": "Is your memory usage >80%?", "type": "confirm"}
            ],
            difficulty=ExpertiseLevel.INTERMEDIATE
        ),
        
        "troubleshooting_stuck_iteration": TutorialTemplate(
            topic="troubleshooting",
            title="Troubleshooting: Stuck Iteration",
            base_content="""
# Troubleshooting: Stuck Iteration

## Symptoms
- No progress for >30 minutes
- Same task repeating
- No new output in logs

## Diagnosis Steps

### 1. Check Status
```bash
python3 -m aiworker.main status
```

Look for:
- Current state (PLAN/RESEARCH/CODE/VALIDATE/APPLY)
- Time in current state
- Last checkpoint time

### 2. Check Logs
```bash
tail -f aiworker/logs/current.log
```

Common patterns:
- "Waiting for approval" → You need to respond
- "LLM timeout" → Network/model issue
- "Validation failed" → Code generation problem

### 3. Common Causes & Solutions

**Waiting for approval:**
```
# Check approval queue
python3 -m aiworker.main pending

# Approve or reject
python3 -m aiworker.main approve <id>
python3 -m aiworker.main reject <id>
```

**LLM not responding:**
```bash
# Check ollama status
ollama list

# Restart ollama
sudo systemctl restart ollama

# Try simpler model
python3 -m aiworker.main config --model tinyllama
```

**Infinite loop in code:**
```bash
# Check for runaway processes
ps aux | grep python

# Kill if needed
pkill -f aiworker

# Resume from checkpoint
python3 -m aiworker.main resume
```

## Prevention

1. **Set iteration timeouts:**
```json
{
  "max_iteration_time_minutes": 30,
  "auto_timeout_action": "pause"
}
```

2. **Enable notifications:**
```json
{
  "notify_on_stuck": true,
  "notification_method": "email"
}
```

## Emergency: Force Continue

If completely stuck:
```bash
# Save current state
python3 -m aiworker.main checkpoint

# Skip current iteration
python3 -m aiworker.main skip

# Resume
python3 -m aiworker.main resume
```
""",
            estimated_minutes=10,
            prerequisites=["safety"],
            interactive_steps=[
                {"prompt": "Run: python3 -m aiworker.main status", "type": "command", "command": "python3 -m aiworker.main status"},
                {"prompt": "Check last 20 lines of logs", "type": "command", "command": "tail -20 aiworker/logs/current.log 2>/dev/null || echo 'No log file'"},
                {"prompt": "Identify likely cause from output", "type": "text_input"}
            ],
            difficulty=ExpertiseLevel.INTERMEDIATE
        ),
        
        "troubleshooting_kill_switch": TutorialTemplate(
            topic="troubleshooting",
            title="Troubleshooting: Kill Switch Triggered",
            base_content="""
# Troubleshooting: Kill Switch Triggered

## What Happened

The kill switch (`.aiworker_kill` file) was detected, stopping all AIWorker activity.

## Why It Happened

1. **You triggered it** - Intentional emergency stop
2. **Safety cage detected danger** - Automatic protection
3. **System error** - Unexpected condition

## Recovery Steps

### 1. Check Why It Triggered

```bash
# Check if file exists
ls -la .aiworker_kill

# Read the reason
cat .aiworker_kill
```

### 2. Review Recent Activity

```bash
# Check last actions
tail -50 aiworker/logs/current.log

# Check what was being modified
python3 -m aiworker.main status
```

### 3. Decide: Resume or Reset?

**Resume if:**
- You accidentally triggered it
- Issue was temporary
- No dangerous changes pending

```bash
# Remove kill switch
rm .aiworker_kill

# Resume
python3 -m aiworker.main resume
```

**Reset if:**
- Dangerous code was generated
- You don't trust current state
- System seems corrupted

```bash
# Remove kill switch
rm .aiworker_kill

# Verify system integrity
python3 -m aiworker.validator verify

# If issues found, bootstrap fresh
python3 seed.py bootstrap
```

### 4. Prevent Future Triggers

If triggered accidentally:
```bash
# Add confirmation to your shell
alias aiw-kill='read -p "Really kill AIWorker? (yes/no) " ans && [ "$ans" = "yes" ] && touch .aiworker_kill'
```

## Safety Checklist Before Resuming

- [ ] Review last 10 log lines
- [ ] Check what file was being modified
- [ ] Verify no suspicious code
- [ ] Understand why kill switch triggered
- [ ] Have a backup plan

## When to Seek Help

If:
- Kill switch keeps triggering
- You see suspicious network activity
- Files you didn't create appear
- System behavior seems wrong

Contact the AIWorker community with logs.
""",
            estimated_minutes=10,
            prerequisites=["safety"],
            interactive_steps=[
                {"prompt": "Check if .aiworker_kill exists", "type": "command", "command": "ls -la .aiworker_kill 2>/dev/null || echo 'No kill switch active'"},
                {"prompt": "Review last 10 log lines", "type": "command", "command": "tail -10 aiworker/logs/current.log 2>/dev/null || echo 'No logs'"},
                {"prompt": "Decide: Resume or investigate further?", "type": "choice", "options": ["resume", "investigate"], "correct": "investigate"}
            ],
            difficulty=ExpertiseLevel.BEGINNER
        )
    }


class TutorialGenerator:
    """Generate personalized tutorials."""
    
    LANGUAGES = ["en", "zh", "es", "ar", "fr", "ru", "de", "ja", "pt", "hi"]
    
    def __init__(self):
        self.library = TutorialLibrary()
    
    def generate(self, topic: str, user: UserModel) -> Optional[Tutorial]:
        """Create personalized tutorial."""
        template = self.library.TEMPLATES.get(topic)
        if not template:
            return None
        
        # Check prerequisites
        missing = [p for p in template.prerequisites if p not in user.completed_tutorials]
        if missing:
            # Generate prerequisite warning
            prereq_note = f"\n\n**Note:** Complete these tutorials first: {', '.join(missing)}\n\n"
        else:
            prereq_note = ""
        
        # Adapt content based on user
        content = self._adapt_content(template.base_content, user)
        content = prereq_note + content
        
        # Translate if needed
        if user.language != "en":
            content = self._translate(content, user.language)
        
        # Adjust interactive steps based on format preference
        steps = self._adapt_steps(template.interactive_steps, user.preferred_format)
        
        return Tutorial(
            title=template.title,
            content=content,
            estimated_minutes=template.estimated_minutes,
            prerequisites=template.prerequisites,
            interactive_steps=steps,
            difficulty=template.difficulty,
            topic=topic
        )
    
    def _adapt_content(self, content: str, user: UserModel) -> str:
        """Adapt content to user expertise."""
        if user.expertise_level == ExpertiseLevel.BEGINNER:
            # Add more explanations
            content = content.replace("##", "##")
            # Add beginner tips
            content += "\n\n---\n**Beginner Tip:** Take your time with each step. There's no rush!\n"
        
        elif user.expertise_level == ExpertiseLevel.ADVANCED:
            # Remove basic explanations
            lines = content.split('\n')
            filtered = []
            skip_until = None
            for line in lines:
                if skip_until and line.strip() == skip_until:
                    skip_until = None
                    continue
                if '**Beginner' in line or '**Basic' in line:
                    skip_until = '---'
                    continue
                filtered.append(line)
            content = '\n'.join(filtered)
        
        # Add personalized notes for struggles
        if user.observed_struggles:
            content += f"\n\n---\n**Personalized Note:** Based on your history, you might find this section helpful. Take extra time here.\n"
        
        return content
    
    def _adapt_steps(self, steps: List[dict], format_pref: ContentFormat) -> List[dict]:
        """Adapt interactive steps to format preference."""
        if format_pref == ContentFormat.TEXT:
            # Remove interactive elements, keep as reading
            return [{"prompt": s["prompt"], "type": "read"} for s in steps]
        
        elif format_pref == ContentFormat.AUDIO_SCRIPT:
            # Convert to narration
            return [{"prompt": s["prompt"], "type": "narrate"} for s in steps]
        
        return steps
    
    def _translate(self, content: str, target_lang: str) -> str:
        """Translate content (placeholder - would use LLM)."""
        # In production, this would call local LLM
        # For now, return original with note
        return f"[Translated to {target_lang}]\n\n{content}"
    
    def suggest_tutorial(self, user: UserModel, recent_activity: List[dict]) -> Optional[str]:
        """Detect need and recommend learning."""
        # Pattern: User rejected 3 memory patches
        memory_vetoes = sum(1 for r in user.veto_reasons if 'memory' in r.lower())
        if memory_vetoes >= 3 and "patch_review" not in user.completed_tutorials:
            return "patch_review"
        
        # Pattern: User never used mesh but has multiple nodes
        # (Would need node count from activity)
        
        # Pattern: Kill switch triggered
        for activity in recent_activity:
            if activity.get("type") == "kill_switch_triggered":
                return "troubleshooting_kill_switch"
        
        # Pattern: Slow approvals
        if user.approval_times and sum(user.approval_times[-5:]) / 5 > 120:
            return "patch_review"
        
        # Pattern: High memory issues
        for activity in recent_activity:
            if activity.get("type") == "high_memory":
                return "troubleshooting_high_memory"
        
        # Pattern: Stuck iteration
        for activity in recent_activity:
            if activity.get("type") == "stuck_iteration":
                return "troubleshooting_stuck_iteration"
        
        return None


class TutorialDelivery:
    """Multi-format tutorial delivery."""
    
    def to_markdown(self, tutorial: Tutorial) -> str:
        """Plain text with formatting."""
        return tutorial.content
    
    def to_cli(self, tutorial: Tutorial) -> None:
        """Interactive terminal walkthrough."""
        print(f"\n{'='*60}")
        print(f"Tutorial: {tutorial.title}")
        print(f"Estimated time: {tutorial.estimated_minutes} minutes")
        print(f"{'='*60}\n")
        
        print(tutorial.content)
        
        print(f"\n{'='*60}")
        print("Interactive Steps:")
        print(f"{'='*60}")
        
        for i, step in enumerate(tutorial.interactive_steps, 1):
            print(f"\n[{i}] {step['prompt']}")
            
            if step['type'] == 'confirm':
                input("Press Enter when ready...")
            elif step['type'] == 'text_input':
                response = input("Your response: ")
                print(f"You entered: {response}")
            elif step['type'] == 'choice':
                options = step.get('options', [])
                print(f"Options: {', '.join(options)}")
                response = input("Your choice: ")
                if response == step.get('correct'):
                    print("✓ Correct!")
                else:
                    print(f"The correct answer was: {step.get('correct')}")
            elif step['type'] == 'command':
                cmd = step.get('command', '')
                print(f"Run this command: {cmd}")
                input("Press Enter after running...")
        
        print(f"\n{'='*60}")
        print("Tutorial complete!")
        print(f"{'='*60}\n")
    
    def to_html(self, tutorial: Tutorial) -> str:
        """Web page with syntax highlighting."""
        # Simple HTML conversion
        content = tutorial.content.replace('\n', '<br>')
        content = re.sub(r'```(\w+)?\n(.*?)```', r'<pre><code>\2</code></pre>', content, flags=re.DOTALL)
        content = re.sub(r'`([^`]+)`', r'<code>\1</code>', content)
        
        return f"""<!DOCTYPE html>
<html>
<head>
    <title>{tutorial.title}</title>
    <style>
        body {{ font-family: sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }}
        pre {{ background: #f4f4f4; padding: 10px; border-radius: 5px; overflow-x: auto; }}
        code {{ background: #f4f4f4; padding: 2px 5px; border-radius: 3px; }}
    </style>
</head>
<body>
    <h1>{tutorial.title}</h1>
    <p><strong>Time:</strong> {tutorial.estimated_minutes} minutes</p>
    {content}
</body>
</html>"""
    
    def to_audio_script(self, tutorial: Tutorial) -> str:
        """Narration script for TTS."""
        script = f"Tutorial: {tutorial.title}. Estimated time: {tutorial.estimated_minutes} minutes.\n\n"
        
        # Convert markdown to spoken form
        content = tutorial.content
        content = re.sub(r'#+ ', '', content)  # Remove headers
        content = re.sub(r'```.*?```', 'Code example follows. See text version for details.', content, flags=re.DOTALL)
        content = re.sub(r'`([^`]+)`', r'\1', content)  # Remove inline code markers
        content = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', content)  # Remove links
        
        script += content
        script += "\n\nEnd of tutorial."
        
        return script


def main():
    parser = argparse.ArgumentParser(description="AIWorker Tutorial Generator")
    parser.add_argument("topic", choices=[
        "first-boot", "safety", "patch-review", "mesh",
        "troubleshoot", "list"
    ])
    parser.add_argument("--symptom", "-s", help="Troubleshooting symptom")
    parser.add_argument("--format", "-f", choices=["markdown", "cli", "html", "audio"],
                       default="cli", help="Output format")
    parser.add_argument("--expertise", "-e", choices=["beginner", "intermediate", "advanced"],
                       default="beginner", help="User expertise level")
    parser.add_argument("--language", "-l", default="en", help="Language code")
    parser.add_argument("--output", "-o", help="Output file")
    
    args = parser.parse_args()
    
    # Create user model
    user = UserModel(
        expertise_level=ExpertiseLevel(args.expertise),
        language=args.language
    )
    
    generator = TutorialGenerator()
    delivery = TutorialDelivery()
    
    if args.topic == "list":
        print("\nAvailable Tutorials:")
        print("="*50)
        for topic, template in TutorialLibrary.TEMPLATES.items():
            print(f"\n{topic}:")
            print(f"  Title: {template.title}")
            print(f"  Difficulty: {template.difficulty.value}")
            print(f"  Time: {template.estimated_minutes} min")
            if template.prerequisites:
                print(f"  Prerequisites: {', '.join(template.prerequisites)}")
        print("="*50)
        return
    
    # Map topic names
    topic_map = {
        "first-boot": "first_boot",
        "safety": "safety",
        "patch-review": "patch_review",
        "mesh": "mesh",
        "troubleshoot": None  # Special handling
    }
    
    if args.topic == "troubleshoot":
        symptom_map = {
            "high_memory": "troubleshooting_high_memory",
            "stuck": "troubleshooting_stuck_iteration",
            "kill_switch": "troubleshooting_kill_switch"
        }
        topic = symptom_map.get(args.symptom, "troubleshooting_stuck_iteration")
    else:
        topic = topic_map.get(args.topic)
    
    if not topic:
        print(f"Unknown topic: {args.topic}")
        return
    
    # Generate tutorial
    tutorial = generator.generate(topic, user)
    if not tutorial:
        print(f"Tutorial not found: {topic}")
        return
    
    # Deliver in requested format
    if args.format == "markdown":
        output = delivery.to_markdown(tutorial)
    elif args.format == "cli":
        delivery.to_cli(tutorial)
        return
    elif args.format == "html":
        output = delivery.to_html(tutorial)
    elif args.format == "audio":
        output = delivery.to_audio_script(tutorial)
    else:
        output = delivery.to_markdown(tutorial)
    
    if args.output:
        Path(args.output).write_text(output)
        print(f"Tutorial saved to {args.output}")
    else:
        print(output)


if __name__ == "__main__":
    main()
