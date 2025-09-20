def summary_message(
    name: str,
    summary_items: list[tuple[str, list]],
    dry_run: bool,
) -> str:
    # Initialise with banner
    message = banner_message(f"{dry_run_message(dry_run, name)} summary")
    # Table to summarise
    for description, items in summary_items.items():
        if isinstance(items, (list, set, tuple, dict)):
            message += (
                "\n" + description.replace("_", " ").capitalize() + f": {len(items)}"
            )
        elif description == "elapsed_time":
            message += "\n" + description.replace("_", " ").capitalize() + f": {items}"

    # Returning to main
    message += banner_message("Returning...")
    return message


def dry_run_message(dry_run: bool, message: str) -> str:
    return f"[DRY RUN] {message}" if dry_run else message


def banner_message(message: str, symbol: str = "-", length: int = 100):
    return f"\n{symbol*length}\n{message}\n{symbol*length}"
