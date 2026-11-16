from typing import Literal

import cfbd
import pickle
import graphic
import json
from collections import defaultdict
from tweakables import InstantiatedTweakables, NextIterationTweakables, DefaultTweakables
from dataclasses import dataclass, replace, asdict

global all_games
all_games: dict[int, list[cfbd.Game]] = {} # type: ignore

PRINT_TEAMS = ["Miami (Combined)", "UCLA", "Ohio State"]
# PRINT_TEAMS = []
CALIBRATION_CUTOFF = 2015

TWEAKABLES_FILE = "best_tweakables.json"

JOKE_MIAMI_MODE = False

RANKED_VS_RANKED_UPSET_FRACTION_PENALTY = 100

FILTER_TO_TEAMS_THAT_PLAYED_THIS_YEAR = True

INITIAL_TOP_25 = [
    "Florida State",
    "Virginia Tech",
    "Nebraska",
    "Wisconsin",
    "Michigan",
    "Kansas State",
    "Michigan State",
    "Alabama",
    "Tennessee",
    "Marshall",
    "Penn State",
    "Florida",
    "Mississippi State",
    "Southern Miss",
    "Miami",
    "Georgia",
    "Arkansas",
    "Minnesota",
    "Oregon",
    "Georgia Tech",
    "Texas",
    "Ole Miss",
    "Texas A&M",
    "Illinois",
    "Purdue",    
]

print(f"Loading all games from pickle...")
with open("all_games.pickle", "rb") as f:
    all_games = pickle.load(f)
print(f"Loaded.")

def is_p5(team, conference: str|None, year: int):
    if (year > 2023) and conference == "Pac-12":
        return False
    if team == "Notre Dame":
        return True
    return conference in ["ACC", "Big Ten", "Big 12", "Pac-12", "SEC", "Big East", "Pac-10"]


@dataclass(slots=True)
class Team:
    name: str
    elo_rating: float
    total_wins: int = 0
    wins_this_year: int = 0
    losses_this_year: int = 0
    points_scored_this_year: int = 0
    points_allowed_this_year: int = 0
    current_classification: str|None = None
    current_conference: str|None = None

    def __init__(self, name: str, elo: float):
        self.name = name
        self.elo_rating = elo
        self.total_wins = 0
        self.wins_this_year = 0
        self.losses_this_year = 0
        self.points_scored_this_year = 0
        self.points_allowed_this_year = 0
        self.current_classification = None
        self.current_conference = None

class Model:
    def __init__(self, tweakables: InstantiatedTweakables):
        self.teams: dict[str, Team] = {}
        self.current_year: int = 0
        self.current_week: int|Literal["Postseason"] = 0
        self.last_week_with_games: int|Literal["Postseason"] = 0
        self.tweakables = tweakables
        self.total_upsets = 0
        self.total_post_cutoff_upsets = 0
        self.error = 0
        self.last_week_top_25: list[Team] = []
        self.ranked_vs_ranked_games = 0
        self.ranked_vs_ranked_upsets = 0

    def initialize_initial_top_25(self):
        for i, team in enumerate(reversed(INITIAL_TOP_25)):
            if JOKE_MIAMI_MODE and team == "Miami":
                team = "Miami (Combined)"
            # Marshall gets the P5 bonus despite not being in the P5.  They earned it for ending ranked 10.
            self.teams[team] = Team(name=team, elo=(self.tweakables.p5_initial_elo + self.tweakables.initial_top_25_bonus_base + i * self.tweakables.initial_top_25_bonus_marginal))

    def initial_elo(self, team:str, classification: str|None, conference: str|None):
        if classification == "fbs": # TODO: Factor in P5 vs G5
            if is_p5(team, conference, self.current_year):
                return self.tweakables.p5_initial_elo
            else:
                return self.tweakables.g5_initial_elo
        elif classification == "fcs":
            return self.tweakables.fcs_initial_elo
        elif classification == "ii":
            return self.tweakables.d2_initial_elo
        elif classification == "iii":
            return self.tweakables.d3_initial_elo
        elif classification is None:
            return self.tweakables.d3_initial_elo
        else:
            raise ValueError(f"Unknown classification '{classification}' for team '{team}'")
            # Usually these are discontinued programs. Give them the d3 rating (Not that it matters that much)
            # print(f"Unknown classification '{classification}' for team '{team}'!")
            return self.tweakables.d3_initial_elo
            # raise ValueError(f"Unknown classification '{classification}' for team '{team}'!")


    def adjust_elo(self, k:float, home_team: Team, away_team: Team, home_points: int, away_points: int):
        home_elo = home_team.elo_rating
        away_elo = away_team.elo_rating

        expected_home = 1 / (1 + 10 ** ((away_elo - home_elo) / self.tweakables.scale_factor))
        expected_away = 1 / (1 + 10 ** ((home_elo - away_elo) / self.tweakables.scale_factor))

        actual_home = 1.0 if home_points > away_points else 0.0
        actual_away = 1.0 if away_points > home_points else 0.0

        home_team.elo_rating += k * (actual_home - expected_home)
        away_team.elo_rating += k * (actual_away - expected_away)


    def record_game(self, game: cfbd.Game): # pyright: ignore[reportPrivateImportUsage]
        if JOKE_MIAMI_MODE:
            if game.home_team in ["Miami", "Miami (OH)"]:
                game.home_team = "Miami (Combined)"
            if game.away_team in ["Miami", "Miami (OH)"]:
                game.away_team = "Miami (Combined)"
        if game.home_points is None or game.away_points is None:
            print(f"Skipping game with incomplete score: {game.home_team} vs {game.away_team}")
            return

        if not game.home_team in self.teams:
            self.teams[game.home_team] = Team(name=game.home_team, elo=self.initial_elo(game.home_team, game.home_classification, game.home_conference))
        if not game.away_team in self.teams:
            self.teams[game.away_team] = Team(name=game.away_team, elo=self.initial_elo(game.away_team, game.away_classification, game.away_conference))

        home_team = self.teams[game.home_team]
        away_team = self.teams[game.away_team]
        
        winner = home_team if game.home_points > game.away_points else away_team
        winner.total_wins += 1

        is_playoff = game.playoff is not None
        is_non_playoff_bowl = (self.current_week == "Postseason") and not is_playoff
        k = self.tweakables.k
        if is_playoff:
            k *= self.tweakables.playoff_k_multiplier
        elif is_non_playoff_bowl:
            k *= self.tweakables.non_playoff_bowl_k_multiplier

        if self.current_week != "Postseason":
            k_bonus = self.tweakables.early_in_season_k_bonus * (self.tweakables.early_in_season_k_bonus_falloff ** (self.current_week - 1))
            k += k_bonus

        year_in_sample = self.current_year - 1999
        k_early_in_sample_bonus = self.tweakables.early_in_sample_k_bonus * (self.tweakables.early_in_sample_k_bonus_falloff ** (year_in_sample - 1))
        k += k_early_in_sample_bonus

        old_home_elo = home_team.elo_rating
        old_away_elo = away_team.elo_rating
        self.adjust_elo(k, home_team, away_team, game.home_points, game.away_points)
        beatdown = abs(game.home_points - game.away_points) >= self.tweakables.beatdown_threshold
        if beatdown:
            self.adjust_elo(k, home_team, away_team, game.home_points, game.away_points)
        upset = (winner is home_team and old_home_elo < old_away_elo) or (winner is away_team and old_away_elo < old_home_elo)
        if upset:
            self.total_upsets += 1
            if game.season >= CALIBRATION_CUTOFF:
                self.total_post_cutoff_upsets += 1
                self.error += self.error_for_game(home_team, away_team, game.home_classification, game.away_classification)
        is_ranked_vs_ranked = home_team in self.last_week_top_25 and away_team in self.last_week_top_25
        if is_ranked_vs_ranked and game.season >= CALIBRATION_CUTOFF:
            self.ranked_vs_ranked_games += 1
            if upset:
                self.ranked_vs_ranked_upsets += 1
        
        if home_team.name in PRINT_TEAMS or away_team.name in PRINT_TEAMS:
            note_str = f"({game.notes})" if game.notes else ""
            print(f"\n{home_team.name} vs {away_team.name} on {game.start_date} (Week {game.week} {game.season}) {note_str}")
            beatdown_upset_str = ""
            if beatdown:
                beatdown_upset_str += f"(Beatdown: {abs(game.home_points - game.away_points)}) "
            if upset:
                beatdown_upset_str += "(Upset)"
            if beatdown and upset:
                beatdown_upset_str = "(UPSET BEATDOWN!)"
            print(f"    Score: {game.home_points}-{game.away_points} {beatdown_upset_str}")
            print(f"    Elo change: {old_home_elo} -> {home_team.elo_rating} for {home_team.name}, {old_away_elo} -> {away_team.elo_rating} for {away_team.name}")
    
        if game.season == self.current_year:
            self.last_week_with_games = self.current_week
            winner.wins_this_year += 1
            loser = away_team if winner is home_team else home_team
            loser.losses_this_year += 1
            home_team.points_scored_this_year += game.home_points
            away_team.points_scored_this_year += game.away_points
            home_team.points_allowed_this_year += game.away_points
            away_team.points_allowed_this_year += game.home_points

        home_team.current_classification = game.home_classification
        away_team.current_classification = game.away_classification
        home_team.current_conference = game.home_conference
        away_team.current_conference = game.away_conference
        
    def error_for_game(self, home_team: Team, away_team: Team, home_classification: str|None = None, away_classification: str|None = None):
        # No additional penalty for Top-25 vs Top-25 because of an amazing bug:
        # It turns out that if you minimize "Ranked vs Ranked upsets", the result is that the model tries to optimize by minimizing the number of Top-25 vs Top-25 *games!*
        # 2 points for top-25 matchups
        if home_team in self.last_week_top_25 or away_team in self.last_week_top_25:
            return 2
        # 1 point for any other FBS game
        if home_classification == "fbs" and away_classification == "fbs":
            return 1
        # 0.1 point for either team being non-fbs
        return 0.1

    def get_conference_averages(self) -> dict[str, float]:
        result: dict[str, float] = {}
        conference_teams: defaultdict[str, set[str]] = defaultdict(set)
        for _, team in self.teams.items():
            conference = team.current_conference
            if conference:
                conference_teams[conference].add(team.name)
        for conference, teams in conference_teams.items():
            num_teams = 0
            total_elo = 0
            for team_name in teams:
                num_teams += 1
                total_elo += self.teams[team_name].elo_rating
            result[conference] = total_elo / num_teams
            print(f"Average Elo for {conference} in {self.current_year}: {total_elo / num_teams}")
        return result

    def handle_new_week(self, new_week: int|Literal["Postseason"]):
        # This may be a performance issue - if it is, we should get the top 25 the dumb O(25*n) way instead of by sorting.
        # (Although nlogn is actually less than 25*n for 300 teams)
        self.last_week_top_25 = [team_info['team_object'] for team_info in self.get_top_n(25)]
        self.current_week = new_week
        # print(f"Handling new week: {new_week}")

    def handle_new_year(self, new_year: int):
        # Reset yearly statistics at the start of the new year
        self.current_year = new_year
        self.current_week = 0
        for team in self.teams.values():
            team.wins_this_year = 0
            team.losses_this_year = 0
            team.points_scored_this_year = 0
            team.points_allowed_this_year = 0

        conference_averages = self.get_conference_averages()

        # Return to base
        for team_name, team in self.teams.items():
            current_elo = team.elo_rating
            base_elo = self.initial_elo(team_name, team.current_classification, team.current_conference)
            diff = current_elo - base_elo
            team.elo_rating -= (diff * self.tweakables.return_to_base_in_offseason_factor)
            if team.current_conference in conference_averages:
                conf_avg = conference_averages[team.current_conference]
                if team.current_conference in ["FBS Independents", "FCS Independents"]:
                    new_diff = team.elo_rating - base_elo
                    team.elo_rating -= (new_diff * self.tweakables.independents_extra_return_to_base_in_offseason_factor)
                    team.elo_rating += (conf_avg - team.elo_rating) * self.tweakables.independents_return_to_conference_average_in_offseason_factor
                else:
                    team.elo_rating += (conf_avg - team.elo_rating) * self.tweakables.return_to_conference_average_in_offseason_factor

        if not self.teams:
            self.initialize_initial_top_25()


    def print_top_ranks(self):
        for team_info in self.get_top_n(25):
            print(f"{team_info['rank']}. {team_info['team_name']}: {team_info['record']}  ({team_info['elo']} Elo)")

    def get_top_n(self, n: int) -> list[dict]:
        sorted_teams = sorted(self.teams.values(), key=lambda item: item.elo_rating, reverse=True)
        if FILTER_TO_TEAMS_THAT_PLAYED_THIS_YEAR:
            sorted_teams = [team for team in sorted_teams if (team.wins_this_year or team.losses_this_year)]
        top_n = []
        for i, team in enumerate(sorted_teams[:n], start=1):
            top_n.append({
                "rank": i,
                "team_name": team.name,
                "team_object": team,
                "record": f"{team.wins_this_year}-{team.losses_this_year}",
                "total_wins": team.total_wins,
                "points_scored": team.points_scored_this_year,
                "elo": team.elo_rating
            })
        return top_n

    def model_error(self) -> float:
        ranked_vs_ranked_upset_fraction = self.ranked_vs_ranked_upsets / self.ranked_vs_ranked_games
        return self.error + (RANKED_VS_RANKED_UPSET_FRACTION_PENALTY * ranked_vs_ranked_upset_fraction)

def iterate_over_season(games: list[cfbd.Game], year: int, models: list[Model]): # pyright: ignore[reportPrivateImportUsage]
    for model in models:
        model.handle_new_year(year) 
    week = 0
    while True:
        week_games = [game for game in games if game.week == week and game.season_type != "postseason"]
        if not week_games:
            if week <= 0:
                week += 1
                continue
            # print(f"No regular season games found for week {week} of year {year} - Moving on to the postseason")
            break
        # print(f"\nProcessing week {week} of year {year}")
        iterate_over_week(False, week, week_games, models)
        week += 1

    postseason_games = [game for game in games if game.season_type == "postseason"]
    # print(f"\nProcessing postseason games of year {year}")
    iterate_over_week(True, -1, postseason_games, models)

def iterate_over_week(postseason: bool, week: int, games: list[cfbd.Game], models: list[Model]): # pyright: ignore[reportPrivateImportUsage]
    for model in models:
        model.handle_new_week("Postseason" if postseason else week)
    if postseason:
        # Postseason games aren't sorted by week - so we have to sort them by date ourselves
        games.sort(key=lambda game: game.start_date)
    for game in games:
        if game.completed:
            for model in models:
                model.record_game(game)


def iterate_over_all_seasons(models: list[Model]):
    years = all_games.keys()
    sorted_years = sorted(years)
    for year in sorted_years:
        # print(f"Processing season {year}")
        iterate_over_season(all_games[year], year, models)

def IterateAndCompareModels(baseModel: Model) -> tuple[Model, bool]:
    if baseModel.current_year == 0:
        print("Base model has not processed any seasons yet. Running it...")
        iterate_over_all_seasons([baseModel])
    derived_tweakables = NextIterationTweakables(baseModel.tweakables)
    all_derived_models = []
    derived_models_by_tweaked_value = defaultdict(list)
    for dt in derived_tweakables:
        derived_model = Model(dt)
        all_derived_models.append(derived_model)
        derived_models_by_tweaked_value[dt.changed_value].append(derived_model)
    # Run it!
    print(f"Running {len(all_derived_models)} derived models...")
    iterate_over_all_seasons(all_derived_models)
    print("Run complete")

    base_model_error = baseModel.model_error()
    print(f"Base model error: {base_model_error}")
    print(f"Base model tweakables: {baseModel.tweakables}")
    mix_of_everything_tweakables = baseModel.tweakables
    overall_best_model = baseModel
    for tweaked_value, model_list in derived_models_by_tweaked_value.items():
        best_model = min(model_list, key=lambda m: m.model_error())
        print(f"Tweaked value: {tweaked_value} (Now set to {getattr(best_model.tweakables, tweaked_value)})")
        print(f"Best model error: {best_model.model_error()} (Base model error: {base_model_error})")
        if best_model.model_error() < base_model_error:
            mix_of_everything_tweakables = replace(mix_of_everything_tweakables, **{tweaked_value: getattr(best_model.tweakables, tweaked_value)})
            if best_model.model_error() < overall_best_model.model_error():
                overall_best_model = best_model
        else:
            print(f"No improvement for tweaked value: {tweaked_value} over the base model")

    print ("Trying mix of everything tweakables...")
    mix_of_everything_model = Model(mix_of_everything_tweakables)
    iterate_over_all_seasons([mix_of_everything_model])
    print(f"Mix of everything model error: {mix_of_everything_model.model_error()} (Overall best model error: {overall_best_model.model_error()})")
    if mix_of_everything_model.model_error() < overall_best_model.model_error():
        overall_best_model = mix_of_everything_model
    print(f"Final overall best model error: {overall_best_model.model_error()}")
    if overall_best_model is baseModel:
        print("The base model remains the best model. We have reached a point of stability.")
        print(f"Final model: {overall_best_model.tweakables}")
    else:
        print("A derived model has surpassed the base model.")
        print(f"Final model: {overall_best_model.tweakables}")

        overall_best_model.print_top_ranks()
    graphic.generate_graphic(overall_best_model)
    return overall_best_model, (overall_best_model is baseModel)

def SaveTweakables(tweakables: InstantiatedTweakables):
    if JOKE_MIAMI_MODE:
        raise RuntimeError("JOKE_MIAMI_MODE is enabled, cannot save tweakables.")
    with open(TWEAKABLES_FILE, "w") as f:
        json.dump(asdict(tweakables), f, indent=4)

def LoadTweakables() -> InstantiatedTweakables|None:
    try:
        with open(TWEAKABLES_FILE, "r") as f:
            data = json.load(f)
        return InstantiatedTweakables(**data)
    except FileNotFoundError:
        return None

def IterateUntilStable(baseModel: Model):
    count = 0
    print("Starting iteration until stable...")
    done = False
    current_model = baseModel
    while not done:
        count += 1
        print(f"Iteration {count}...")
        current_model, done = IterateAndCompareModels(current_model)
        SaveTweakables(current_model.tweakables)
        print(f"Iteration {count} complete.")
    print(f"Stable at iteration {count}!")

def JustRunModel(model: Model):
    iterate_over_all_seasons([model])
    print(f"Model error: {model.model_error()}")
    model.print_top_ranks()
    graphic.generate_graphic(model)

current_sota = LoadTweakables()
if not current_sota:
    print("No saved tweakables found, using default tweakables.")
    current_sota = DefaultTweakables()

baseModel = Model(current_sota)
# IterateUntilStable(baseModel)
JustRunModel(baseModel)
