def extract_prompt(messages) -> str:
    """Last user message text from an OpenAI/Anthropic-style messages list."""
    try:
        for msg in reversed(messages or []):
            role = msg.get("role") if isinstance(msg, dict) else getattr(msg, "role", None)
            if role != "user":
                continue
            content = (
                msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", "")
            )
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts = []
                for block in content:
                    is_dict = isinstance(block, dict)
                    text = block.get("text") if is_dict else getattr(block, "text", None)
                    if text:
                        parts.append(text)
                return "\n".join(parts)
        return ""
    except Exception:
        return ""


def estimate_tokens(text: str) -> int:
    return max(len(text) // 4, 1) if text else 0


def pick_params(kwargs: dict) -> dict:
    keep = ("temperature", "max_tokens", "top_p", "top_k", "stream")
    return {k: kwargs[k] for k in keep if k in kwargs and kwargs[k] is not None}
