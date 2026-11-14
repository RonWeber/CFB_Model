from dataclasses import dataclass, asdict, replace

MULTIPLIERS = [0.1, 0.5, 0.75, 0.9, 0.99, 1.01, 1.1, 1.25, 2.0, 5.0]

@dataclass(frozen=True, slots=True)
class InstantiatedTweakables:
    changed_value: str|None

    k: float
    scale_factor: float
    p5_initial_elo: float
    g5_initial_elo: float
    fcs_initial_elo: float
    d2_initial_elo: float
    d3_initial_elo: float
    beatdown_threshold: int
    return_to_base_in_offseason_factor: float
    return_to_conference_average_in_offseason_factor: float
    independents_extra_return_to_base_in_offseason_factor: float
    independents_return_to_conference_average_in_offseason_factor: float
    initial_top_25_bonus_base: float
    initial_top_25_bonus_marginal: float

    def isSane(self) -> bool:
        if self.return_to_base_in_offseason_factor > 1.0:
            return False
        if self.return_to_conference_average_in_offseason_factor > 1.0:
            return False
        if self.g5_initial_elo > self.p5_initial_elo:
            return False        
        if self.fcs_initial_elo > self.g5_initial_elo:
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
        scale_factor=400.0,
        p5_initial_elo=1500.0,
        g5_initial_elo=1000.0,
        fcs_initial_elo=787.5,
        d2_initial_elo=550.0,
        d3_initial_elo=50.0,
        beatdown_threshold=16,
        return_to_base_in_offseason_factor=0.1856,
        return_to_conference_average_in_offseason_factor=0.1485,
        independents_extra_return_to_base_in_offseason_factor=0.005,
        independents_return_to_conference_average_in_offseason_factor=0.135,
        initial_top_25_bonus_base=100.0,
        initial_top_25_bonus_marginal=25.0
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