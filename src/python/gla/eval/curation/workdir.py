from __future__ import annotations
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Any

_URL_RE = re.compile(
    r"https?://(?P<host>[^/]+)/(?P<owner>[^/]+)/(?P<repo>[^/]+)/"
    r"(?P<kind>issues|commit|pull|questions)/(?P<ref>[^/?#]+)"
)

@dataclass
class IssueWorkdir:
    root: Path
    issue_id: str
    url: str

    @classmethod
    def for_url(cls, base_dir: Path | str, url: str) -> "IssueWorkdir":
        m = _URL_RE.search(url)
        if m:
            parts = [m.group("host").split(".")[0], m.group("owner"),
                     m.group("repo"), m.group("kind").rstrip("s"), m.group("ref")]
            issue_id = "_".join(parts)
        else:
            # fallback: sanitize the URL
            issue_id = re.sub(r"\W+", "_", url).strip("_")
        base = Path(base_dir)
        return cls(root=base / issue_id, issue_id=issue_id, url=url)

    @property
    def staging(self) -> Path:
        p = self.root / "staging"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _stage_path(self, stage: str) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        return self.root / f"{stage}.json"

    def write_stage(self, stage: str, output: Any, input_hash: str) -> None:
        payload = {"input_hash": input_hash, "output": output}
        self._stage_path(stage).write_text(json.dumps(payload, indent=2))

    def read_stage(self, stage: str) -> Optional[dict]:
        p = self._stage_path(stage)
        if not p.exists():
            return None
        return json.loads(p.read_text())

    def should_skip_stage(self, stage: str, current_input_hash: str) -> bool:
        prior = self.read_stage(stage)
        return prior is not None and prior.get("input_hash") == current_input_hash
