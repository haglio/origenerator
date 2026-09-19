from __future__ import annotations


def hud_button_names(hud) -> list[str]:
    return [button.command.removeprefix(f"{hud._side}_")
            for _rect, button in hud._targets.buttons]
