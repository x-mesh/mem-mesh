import argparse
import json
from pathlib import Path
from typing import List


def load_index(index_path: Path) -> dict:
    with index_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def list_rules(index_data: dict) -> None:
    rules = index_data.get("rules", [])
    for rule in rules:
        rule_id = rule.get("id", "")
        title = rule.get("title", "")
        kind = rule.get("kind", "")
        print(f"{rule_id}\t{kind}\t{title}")


def collect_rules(index_data: dict, selected_ids: List[str]) -> List[dict]:
    rules = index_data.get("rules", [])
    rule_map = {rule["id"]: rule for rule in rules}
    missing = [rule_id for rule_id in selected_ids if rule_id not in rule_map]
    if missing:
        raise ValueError(f"Unknown rule id: {', '.join(missing)}")
    return [rule_map[rule_id] for rule_id in selected_ids]


def read_rule_content(base_dir: Path, rule_path: str) -> str:
    rule_file = base_dir / rule_path
    return rule_file.read_text(encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate rules bundle from docs/rules/index.json")
    parser.add_argument("--list", action="store_true", help="List available rule ids")
    parser.add_argument(
        "--ids",
        type=str,
        default="",
        help="Comma-separated rule ids (e.g. core,search,pins)"
    )
    parser.add_argument("--output", type=str, default="", help="Output file path (default: stdout)")

    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    index_path = repo_root / "docs" / "rules" / "index.json"

    index_data = load_index(index_path)

    if args.list:
        list_rules(index_data)
        return

    if not args.ids:
        raise ValueError("No rule ids provided. Use --list to see available ids.")

    selected_ids = [item.strip() for item in args.ids.split(",") if item.strip()]
    selected_rules = collect_rules(index_data, selected_ids)

    parts = []
    for rule in selected_rules:
        parts.append(read_rule_content(repo_root, rule["path"]).rstrip())

    output = "\n\n---\n\n".join(parts) + "\n"

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
    else:
        print(output, end="")


if __name__ == "__main__":
    main()
