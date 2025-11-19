from pathlib import Path

from pipeline.main import parse_args

parser = parse_args(return_parser=True)

# Generate ARGS.md
args_md_path = Path(__file__).parent / "ARGS.md"

with args_md_path.open("w") as f:
    f.write("## Pipeline Command-Line Arguments\n\n")
    f.write("| Argument | Description |\n")
    f.write("|----------|-------------|\n")
    for action in parser._actions:
        if action.option_strings:
            opts = ", ".join(action.option_strings)
            desc = action.help or ""
            f.write(f"| `{opts}` | {desc} |\n")

    # Add the auto-generated help output
    f.write("\n\n## `--help` Output\n\n")
    f.write("```bash\n")
    f.write(parser.format_help())
    f.write("```\n")

print(f"ARGS.md generated at {args_md_path.resolve()}")
