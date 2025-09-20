import argparse

from core.cli import App


def main():
    parser = argparse.ArgumentParser(description="Script Runner")
    parser.add_argument(
        "scripts_to_run",
        nargs="*",
        help="Names of scripts to run automatically (by class name)",
    )
    parser.add_argument(
        "--override",
        nargs="*",
        default=[],
        help="Override config values: format section.key=value (e.g., General.dry_run=true)",
    )

    args = parser.parse_args()
    app = App()

    def get_script_name_case_insensitive(user_input):
        lower_input = user_input.lower()
        for name in app.scripts:
            if name.lower() == lower_input:
                return name
        return None

    try:
        app.refresh()

        # Apply overrides if provided
        if args.override:
            overrides = app.parse_overrides(args.override)
            app.deep_update_config(overrides)

        if args.scripts_to_run:
            for script_name_input in args.scripts_to_run:
                matched_name = get_script_name_case_insensitive(script_name_input)
                if matched_name:
                    print(f"\nAuto-running script: {matched_name}")
                    app.run_script(matched_name, confirm=False)
                else:
                    print(f"Script '{script_name_input}' not found.")
        else:
            # Interactive menu
            while True:
                print(f"{'='*100}\nWelcome back!\n{'='*100}\n\nAvailable scripts:")
                app.refresh()

                if args.override:
                    app.deep_update_config(app.parse_overrides(args.override))

                indexed_names = sorted(app.scripts.items())
                for i, (_, info) in enumerate(indexed_names, start=1):
                    description = info.get("doc", "")
                    display_name = info["class_name"]
                    if description:
                        display_name += f": {description}"
                    print(f"  [{i}] {display_name}")

                script_input = input(
                    "\nEnter script number or class name (or press Enter to quit): "
                ).strip()

                if not script_input:
                    break

                # Try interpreting the input as a number
                if script_input.isdigit():
                    idx = int(script_input) - 1
                    if 0 <= idx < len(indexed_names):
                        script_name = indexed_names[idx][0]
                    else:
                        print("Invalid number.")
                        continue
                else:
                    # Match class name case-insensitively
                    script_name = get_script_name_case_insensitive(script_input)
                    if not script_name:
                        print(f"Script '{script_input}' not found.")
                        continue

                app.refresh()
                app.run_script(script_name)
    finally:
        # Ensure caches are cleared before quitting
        app.clear_caches()
        print("Goodbye!")


if __name__ == "__main__":
    main()
