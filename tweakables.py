from dataclasses import dataclass, asdict, replace

MULTIPLIERS = [0.1, 0.5, 0.75, 0.9, 0.99, 1.01, 1.1, 1.25, 2.0, 5.0]

@dataclass(frozen=True, slots=True)
class InstantiatedTweakables:
    changed_value: str|None

    k: float = 90.0
    scale_factor: float = 800.0
    fbs_initial_elo: float = 1250.0
    fcs_initial_elo: float = 660.0
    d2_initial_elo: float = 500.0
    d3_initial_elo: float = 500.0
    beatdown_threshold: int = 16
    return_to_base_in_offseason_factor: float = 0.09
    return_to_conference_average_in_offseason_factor: float = 0.375

    def isSane(self) -> bool:
        if self.return_to_base_in_offseason_factor > 1.0:
            return False
        if self.return_to_conference_average_in_offseason_factor > 1.0:
            return False
        if self.fcs_initial_elo > self.fbs_initial_elo:
            return False
        if self.d2_initial_elo > self.fcs_initial_elo:
            return False
        if self.d3_initial_elo > self.d2_initial_elo:
            return False
        return True

def DefaultTweakables() -> InstantiatedTweakables:
    return InstantiatedTweakables(
        changed_value=None,
        k=90.0,
        scale_factor=800.0,
        fbs_initial_elo=1250.0,
        fcs_initial_elo=660.0,
        d2_initial_elo=500.0,
        d3_initial_elo=500.0,
        beatdown_threshold=16,
        return_to_base_in_offseason_factor=0.09,
        return_to_conference_average_in_offseason_factor=0.375
    )


def NextIterationTweakables(initial: InstantiatedTweakables) -> list[InstantiatedTweakables]:
    result: list[InstantiatedTweakables] = []
    for name, currentValue in asdict(initial).items():
        if name == "changed_value":
            continue
        for multiplier in MULTIPLIERS:
            tweaked = replace(initial, **{name: currentValue * multiplier, "changed_value": name})
            if tweaked.isSane():
                result.append(tweaked)
    return result