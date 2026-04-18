"""Dynamic Skill Registry for loading and managing agent skills.

This module provides a dynamic, directory-based skill registry that enables
a plug-and-play ecosystem where adding a new capability is as simple as
dropping a new folder into the skills/ directory.

Architecture:
- File System: Standardized folder structure with SKILL.md files containing YAML frontmatter
- Skill Registry: Core utility that scans, parses, and holds skills in memory
- Agent Orchestrator: Uses the registry for routing and prompt injection
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml


class SkillInfo:
    """Information about a single skill."""

    def __init__(
            self,
            skill_id: str,
            name: str,
            description: str,
            instructions: str,
            path: Path,
            keywords: list[str] | None = None,
            metadata: dict[str, Any] | None = None,
    ):
        self.skill_id = skill_id
        self.name = name
        self.description = description
        self.instructions = instructions
        self.path = path
        self.keywords = keywords or []
        self.metadata = metadata or {}

    def to_summary(self) -> dict[str, Any]:
        """Return a summary suitable for routing decisions (minimal tokens)."""
        return {
            "id": self.skill_id,
            "name": self.name,
            "description": self.description,
            "keywords": self.keywords,
        }


class SkillRegistry:
    """Dynamic skill registry that loads skills from a directory structure.

    Supports hot-reloading by checking file modification times on access.
    """

    def __init__(self, skills_dir: str | Path | None = None):
        """Initialize the skill registry.

        Args:
            skills_dir: Path to the skills directory. Defaults to research_agent/skills/
        """
        if skills_dir is None:
            # Default to the skills directory relative to this file
            self.skills_dir = Path(__file__).parent / "skills"
        else:
            self.skills_dir = Path(skills_dir)

        self._skills: dict[str, SkillInfo] = {}
        self._load_timestamps: dict[str, float] = {}
        self._load_all_skills()

    def _load_all_skills(self) -> None:
        """Scan and load all skills from the skills directory."""
        if not self.skills_dir.exists():
            print(f"Warning: Skills directory not found: {self.skills_dir}")
            return

        # Iterate through all subdirectories in the skills folder
        for skill_path in sorted(self.skills_dir.iterdir()):
            if not skill_path.is_dir():
                continue

            skill_file = skill_path / "SKILL.md"
            if not skill_file.exists():
                continue

            try:
                parsed_skill = self._parse_skill_file(skill_file)
                if parsed_skill:
                    skill_id = skill_path.name
                    parsed_skill["skill_id"] = skill_id
                    parsed_skill["path"] = skill_path
                    self._skills[skill_id] = SkillInfo(**parsed_skill)
                    self._load_timestamps[skill_id] = skill_file.stat().st_mtime
            except Exception as e:
                print(f"Warning: Failed to load skill from {skill_file}: {e}")
                continue

    def _parse_skill_file(self, file_path: Path) -> dict[str, Any] | None:
        """Parse a SKILL.md file, extracting frontmatter and body.

        Args:
            file_path: Path to the SKILL.md file

        Returns:
            Dictionary with skill metadata and instructions, or None if parsing fails
        """
        content = file_path.read_text(encoding="utf-8")

        # Check for YAML frontmatter (between --- boundaries)
        if not content.startswith("---"):
            print(f"Warning: {file_path} does not start with YAML frontmatter")
            return None

        # Find the end of frontmatter
        end_marker = content.find("\n---", 3)
        if end_marker == -1:
            print(f"Warning: {file_path} has unclosed YAML frontmatter")
            return None

        frontmatter_text = content[3:end_marker]
        try:
            frontmatter = yaml.safe_load(frontmatter_text)
        except yaml.YAMLError as e:
            print(f"Warning: Failed to parse YAML in {file_path}: {e}")
            return None

        # Extract required fields
        name = frontmatter.get("name")
        description = frontmatter.get("description")

        if not name or not description:
            print(f"Warning: {file_path} missing required 'name' or 'description' in frontmatter")
            return None

        # Extract optional fields
        keywords = frontmatter.get("keywords", [])
        metadata = {k: v for k, v in frontmatter.items() if k not in ["name", "description", "keywords"]}

        # Get the body (instructions) after frontmatter
        body = content[end_marker + 4:].strip()

        return {
            "name": name,
            "description": description,
            "instructions": body,
            "keywords": keywords,
            "metadata": metadata,
        }

    def get_all_summaries(self) -> list[dict[str, Any]]:
        """Get summaries of all available skills for routing decisions.

        Returns:
            List of skill summaries with id, name, description, and keywords
        """
        return [skill.to_summary() for skill in self._skills.values()]

    def get_skill_instructions(self, skill_id: str, force_reload: bool = False) -> str | None:
        """Get the full instructions for a specific skill.

        Supports hot-reloading by checking file modification time.

        Args:
            skill_id: The skill identifier (directory name)
            force_reload: If True, always reload from disk

        Returns:
            The skill instructions (markdown body), or None if not found
        """
        # Check if skill exists
        if skill_id not in self._skills:
            return None

        skill_info = self._skills[skill_id]
        skill_file = skill_info.path / "SKILL.md"

        # Hot-reload check: compare file modification time
        if not force_reload:
            current_mtime = skill_file.stat().st_mtime
            cached_mtime = self._load_timestamps.get(skill_id, 0)
            if current_mtime > cached_mtime:
                # File has been modified, reload it
                print(f"Hot-reloading skill: {skill_id}")
                parsed_skill = self._parse_skill_file(skill_file)
                if parsed_skill:
                    parsed_skill["skill_id"] = skill_id
                    parsed_skill["path"] = skill_info.path
                    self._skills[skill_id] = SkillInfo(**parsed_skill)
                    self._load_timestamps[skill_id] = current_mtime
                    return self._skills[skill_id].instructions
                else:
                    print(f"Warning: Failed to reload skill {skill_id}, using cached version")
                    return skill_info.instructions

        return skill_info.instructions

    def get_skill_info(self, skill_id: str) -> SkillInfo | None:
        """Get full skill information object.

        Args:
            skill_id: The skill identifier

        Returns:
            SkillInfo object or None if not found
        """
        return self._skills.get(skill_id)

    def find_skills_by_keyword(self, query: str) -> list[SkillInfo]:
        """Find skills matching a keyword or search query.

        Args:
            query: Search query (will be matched against keywords and descriptions)

        Returns:
            List of matching SkillInfo objects
        """
        query_lower = query.lower()
        matches = []

        for skill in self._skills.values():
            # Check keywords
            for keyword in skill.keywords:
                if re.search(keyword, query_lower):
                    matches.append(skill)
                    break
            else:
                # Check description if no keyword match
                if query_lower in skill.description.lower():
                    matches.append(skill)

        return matches

    def get_supporting_files(self, skill_id: str) -> list[Path]:
        """Get paths to supporting files in a skill directory.

        This enables lazy loading of supporting files like CSS, templates, etc.

        Args:
            skill_id: The skill identifier

        Returns:
            List of file paths in the skill directory (excluding SKILL.md)
        """
        skill_info = self._skills.get(skill_id)
        if not skill_info:
            return []

        skill_path = skill_info.path
        return [f for f in skill_path.iterdir() if f.is_file() and f.name != "SKILL.md"]

    def read_supporting_file(self, skill_id: str, filename: str) -> str | None:
        """Read a supporting file from a skill directory.

        Args:
            skill_id: The skill identifier
            filename: Name of the file to read

        Returns:
            File contents as string, or None if not found
        """
        skill_info = self._skills.get(skill_id)
        if not skill_info:
            return None

        file_path = skill_info.path / filename
        if not file_path.exists() or not file_path.is_file():
            return None

        try:
            return file_path.read_text(encoding="utf-8")
        except Exception as e:
            print(f"Warning: Failed to read supporting file {file_path}: {e}")
            return None

    def reload_all(self) -> None:
        """Force reload all skills from disk."""
        self._skills.clear()
        self._load_timestamps.clear()
        self._load_all_skills()
        print(f"Reloaded {len(self._skills)} skills from {self.skills_dir}")

    @property
    def skill_ids(self) -> list[str]:
        """Get list of all loaded skill IDs."""
        return list(self._skills.keys())

    @property
    def num_skills(self) -> int:
        """Get number of loaded skills."""
        return len(self._skills)

    def __repr__(self) -> str:
        return f"SkillRegistry(num_skills={self.num_skills}, dir={self.skills_dir})"
