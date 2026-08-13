"""
Tool registry — maps Action → tool function.

Every executable action must go through a registered tool.
Raw transcript text never reaches this layer.
"""
from friday.intent.models import Action, Intent
from friday.tools import apps, browser, files, system


def execute(
    intent: Intent, dry_run: bool = True, allow_real_execution: bool = False
) -> dict:
    """
    Execute the tool for the given intent.

    Real execution requires BOTH:
      dry_run == False AND allow_real_execution == True

    Returns a result dict with at minimum:
        {"success": bool, "message": str}
    """
    is_dry_run = dry_run or (not allow_real_execution)
    a = intent.action
    t = intent.target

    if a == Action.OPEN_APP:
        return apps.open_app(t, dry_run=is_dry_run)

    if a == Action.CLOSE_APP:
        return apps.close_app(t, dry_run=is_dry_run)

    if a == Action.OPEN_WEBSITE:
        return browser.open_website(t, dry_run=is_dry_run)

    if a == Action.SEARCH_WEB:
        return browser.search_web(t, dry_run=is_dry_run)

    if a == Action.FIND_FILE:
        return files.find_file(t)          # find_file has no dry_run (read-only)

    if a == Action.OPEN_FILE:
        return files.open_file(t, dry_run=is_dry_run)

    if a == Action.OPEN_FOLDER:
        return files.open_folder(t, dry_run=is_dry_run)

    if a == Action.GET_TIME:
        return system.get_time()           # get_time has no dry_run (read-only)

    return {"success": False, "message": f"No tool registered for action: {a.name}"}
