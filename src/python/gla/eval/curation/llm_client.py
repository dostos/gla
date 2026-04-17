from __future__ import annotations
import subprocess
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class LLMResponse:
    text: str
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int
    stop_reason: str


class LLMClient:
    def __init__(self, sdk: Any, model: str = "claude-opus-4-7",
                 max_tokens: int = 4096):
        self._sdk = sdk
        self._model = model
        self._max_tokens = max_tokens

    def complete(
        self,
        system: str,
        messages: list[dict],
        cache_system: bool = True,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        sys_blocks: list[dict] = [{"type": "text", "text": system}]
        if cache_system:
            sys_blocks[0]["cache_control"] = {"type": "ephemeral"}

        resp = self._sdk.messages.create(
            model=self._model,
            max_tokens=max_tokens or self._max_tokens,
            system=sys_blocks,
            messages=messages,
        )
        text = "".join(
            getattr(c, "text", "") for c in resp.content
            if getattr(c, "type", "text") in ("text", None)
            or not isinstance(getattr(c, "type", "text"), str)
        )
        return LLMResponse(
            text=text,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            cache_creation_input_tokens=getattr(
                resp.usage, "cache_creation_input_tokens", 0) or 0,
            cache_read_input_tokens=getattr(
                resp.usage, "cache_read_input_tokens", 0) or 0,
            stop_reason=resp.stop_reason,
        )

    @classmethod
    def from_env(cls, model: str = "claude-opus-4-7") -> "LLMClient":
        import anthropic
        return cls(sdk=anthropic.Anthropic(), model=model)


class ClaudeCodeLLMClient:
    """LLM client that shells out to the `claude` CLI (Claude Code headless mode).

    Duck-typed to match LLMClient.complete(). Token counts are always 0 since
    we can't retrieve them from the CLI output; cache behavior is managed by
    Claude Code itself (not us).
    """

    def __init__(self, claude_bin: str = "claude", timeout: int = 300,
                 extra_args: Optional[list[str]] = None):
        self._bin = claude_bin
        self._timeout = timeout
        # Default extra args: empty. Don't use --bare by default — it disables
        # OAuth/keychain auth and would force ANTHROPIC_API_KEY, which is exactly
        # what this backend is designed to avoid.
        self._extra = extra_args if extra_args is not None else []

    def complete(
        self,
        system: str,
        messages: list[dict],
        cache_system: bool = True,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        # Claude Code's -p mode accepts a single prompt; combine system + user content.
        user_parts: list[str] = []
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                user_parts.append(content)
            elif isinstance(content, list):
                # Multi-modal: extract text blocks only (images skipped at this layer)
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        user_parts.append(block.get("text", ""))
        user_text = "\n\n".join(user_parts)

        combined = f"{system}\n\n---\n\n{user_text}" if system else user_text

        argv = [self._bin, "-p", "--output-format", "text"] + self._extra
        try:
            result = subprocess.run(
                argv,
                input=combined,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(
                f"claude CLI failed (exit {e.returncode}): {e.stderr[:500]}"
            ) from e

        return LLMResponse(
            text=result.stdout.strip(),
            input_tokens=0,
            output_tokens=0,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
            stop_reason="end_turn",
        )

    @classmethod
    def from_env(cls, model: str = "claude-opus-4-7") -> "ClaudeCodeLLMClient":
        # model arg is ignored — claude CLI picks its own model.
        return cls()
