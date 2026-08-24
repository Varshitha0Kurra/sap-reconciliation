from typing import List, Dict, Any, Optional

class ConversationManager:
    """Manages the conversation history and formatting context for Gemini planning."""
    
    def __init__(self, max_turns: int = 5):
        self.max_turns = max_turns
        self.history: List[Dict[str, Any]] = []

    def add_user_message(self, text: str):
        """Adds a user query to the history."""
        self.history.append({
            "role": "user",
            "content": text
        })
        # Keep history within max_turns * 2 (user + assistant = 1 turn)
        if len(self.history) > self.max_turns * 2:
            self.history = self.history[-(self.max_turns * 2):]

    def add_assistant_response(self, summary: str, sql_executed: Optional[str] = None, results_summary: Optional[str] = None):
        """Adds assistant response metadata to history."""
        self.history.append({
            "role": "assistant",
            "content": summary,
            "sql": sql_executed,
            "results_summary": results_summary
        })

    def clear(self):
        """Resets the conversation state."""
        self.history = []

    def get_context_for_prompt(self) -> str:
        """Formats conversation history for the Gemini planner prompt."""
        if not self.history:
            return "No previous conversation context."
            
        formatted = []
        for i, turn in enumerate(self.history):
            role = "User" if turn["role"] == "user" else "Assistant"
            formatted.append(f"{role}: {turn['content']}")
            if turn.get("sql") and role == "Assistant":
                formatted.append(f"  [Executed SQL: {turn['sql']}]")
                if turn.get("results_summary"):
                    formatted.append(f"  [Result Summary: {turn['results_summary']}]")
        return "\n".join(formatted)
