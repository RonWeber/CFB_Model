from typing import Literal

import cfbd
import pickle
import graphic
import json
from collections import defaultdict
from tweakables import InstantiatedTweakables, NextIterationTweakables, DefaultTweakables
from dataclasses import replace, asdict

global all_games
all_games: dict[int, list[cfbd.Game]] = {} # type: ignore

PRINT_TEAMS = ["Miami (Combined)", "UCLA"]
# PRINT_TEAMS = []
CALIBRATION_CUTOFF = 2014

TWEAKABLES_FILE = "best_tweakables.json"

JOKE_MIAMI_MODE = False

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

class Model:
    def __init__(self, tweakables: InstantiatedTweakables):
        self.total_wins: dict[str, int] = {}
        self.wins_this_year: dict[str, int] = defaultdict(int)
        self.losses_this_year: dict[str, int] = defaultdict(int) 
        self.current_year: int = 0
        self.current_week: int|Literal["Postseason"] = 0
        self.last_week_with_games: int|Literal["Postseason"] = 0
        self.points_scored_this_year: dict[str, int] = defaultdict(int)
        self.points_allowed_this_year: dict[str, int] = defaultdict(int)
        self.tweakables = tweakables
        self.elo_ratings: dict[str, float] = {}
        self.total_upsets = 0
        self.total_post_cutoff_upsets = 0
        self.error = 0
        self.most_current_classifications: dict[str, str|None] = {}
        self.most_current_conferences: dict[str,str|None] = {}
        self.last_week_top_25: list[str] = []

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


    def adjust_elo(self, home_team: str, away_team: str, home_points: int, away_points: int):
        home_elo = self.elo_ratings[home_team]
        away_elo = self.elo_ratings[away_team]

        expected_home = 1 / (1 + 10 ** ((away_elo - home_elo) / self.tweakables.scale_factor))
        expected_away = 1 / (1 + 10 ** ((home_elo - away_elo) / self.tweakables.scale_factor))

        actual_home = 1.0 if home_points > away_points else 0.0
        actual_away = 1.0 if away_points > home_points else 0.0

        self.elo_ratings[home_team] += self.tweakables.k * (actual_home - expected_home)
        self.elo_ratings[away_team] += self.tweakables.k * (actual_away - expected_away)


    def record_game(self, game: cfbd.Game): # pyright: ignore[reportPrivateImportUsage]
        if JOKE_MIAMI_MODE:
            if game.home_team in ["Miami", "Miami (OH)"]:
                game.home_team = "Miami (Combined)"
            if game.away_team in ["Miami", "Miami (OH)"]:
                game.away_team = "Miami (Combined)"
        if game.home_points is None or game.away_points is None:
            print(f"Skipping game with incomplete score: {game.home_team} vs {game.away_team}")
            return
        
        winner = game.home_team if game.home_points > game.away_points else game.away_team
        if winner not in self.total_wins:
            self.total_wins[winner] = 0
        self.total_wins[winner] += 1

        if game.home_team not in self.elo_ratings:
            self.elo_ratings[game.home_team] = self.initial_elo(game.home_team, game.home_classification, game.home_conference)
        if game.away_team not in self.elo_ratings:
            self.elo_ratings[game.away_team] = self.initial_elo(game.away_team, game.away_classification, game.away_conference)
        old_home_elo = self.elo_ratings[game.home_team]
        old_away_elo = self.elo_ratings[game.away_team]
        self.adjust_elo(game.home_team, game.away_team, game.home_points, game.away_points)
        beatdown = abs(game.home_points - game.away_points) >= self.tweakables.beatdown_threshold
        if beatdown:
            self.adjust_elo(game.home_team, game.away_team, game.home_points, game.away_points)
        upset = (winner == game.home_team and old_home_elo < old_away_elo) or (winner == game.away_team and old_away_elo < old_home_elo)
        if upset:
            self.total_upsets += 1
            if game.season >= CALIBRATION_CUTOFF:
                self.total_post_cutoff_upsets += 1
                self.error += self.error_for_game(game.home_team, game.away_team, game.home_classification, game.away_classification)
        
        if game.home_team in PRINT_TEAMS or game.away_team in PRINT_TEAMS:
            note_str = f"({game.notes})" if game.notes else ""
            print(f"\n{game.home_team} vs {game.away_team} on {game.start_date} (Week {game.week} {game.season}) {note_str}")
            beatdown_upset_str = ""
            if beatdown:
                beatdown_upset_str += f"(Beatdown: {abs(game.home_points - game.away_points)}) "
            if upset:
                beatdown_upset_str += "(Upset)"
            if beatdown and upset:
                beatdown_upset_str = "(UPSET BEATDOWN!)"
            print(f"    Score: {game.home_points}-{game.away_points} {beatdown_upset_str}")
            print(f"    Elo change: {old_home_elo} -> {self.elo_ratings[game.home_team]} for {game.home_team}, {old_away_elo} -> {self.elo_ratings[game.away_team]} for {game.away_team}")
    
        if game.season == self.current_year:
            self.last_week_with_games = self.current_week
            self.wins_this_year[winner] += 1
            loser = game.away_team if winner == game.home_team else game.home_team
            self.losses_this_year[loser] += 1
            self.points_scored_this_year[game.home_team] += game.home_points
            self.points_scored_this_year[game.away_team] += game.away_points
            self.points_allowed_this_year[game.home_team] += game.away_points
            self.points_allowed_this_year[game.away_team] += game.home_points

        self.most_current_classifications[game.home_team] = game.home_classification
        self.most_current_classifications[game.away_team] = game.away_classification
        self.most_current_conferences[game.home_team] = game.home_conference
        self.most_current_conferences[game.away_team] = game.away_conference

        if game.home_classification != "fbs" and game.away_classification != "fbs":
            print(f"Non-FBS game: {game.home_team} ({game.home_classification}) vs {game.away_team} ({game.away_classification}) on {game.start_date}")

    def error_for_game(self, home_team: str, away_team: str, home_classification: str|None = None, away_classification: str|None = None):
        # 10 points for top-25 matchups
        if home_team in self.last_week_top_25 and away_team in self.last_week_top_25:
            return 10
        if home_team in self.last_week_top_25 or away_team in self.last_week_top_25:
            return 2
        # 1 point for any other FBS game
        if home_classification == "fbs" and away_classification == "fbs":
            return 1
        # 0.1 point for either team being non-fbs
        return 0.1

    def get_conference_averages(self):
        result = {}
        conference_teams = defaultdict(set)
        for team, conference in self.most_current_conferences.items():
            if conference:
                conference_teams[conference].add(team)
        for conference, teams in conference_teams.items():
            num_teams = 0
            total_elo = 0
            for team in teams:
                num_teams += 1
                total_elo += self.elo_ratings[team]
            result[conference] = total_elo / num_teams
            # print(f"Average Elo for {conference} in {self.current_year}: {total_elo / num_teams}")
        # print(f"Also, Notre Dame's conference in {self.current_year}: {self.most_current_conferences.get('Notre Dame', 'Unknown')} and BYU's is {self.most_current_conferences.get('BYU', 'Unknown')}")
        return result

    def handle_new_week(self, new_week: int|Literal["Postseason"]):
        # This may be a performance issue - if it is, we should get the top 25 the dumb O(25*n) way instead of by sorting.
        # (Although nlogn is actually less than 25*n for 300 teams)
        self.last_week_top_25 = [team_info['team'] for team_info in self.get_top_n(25)]
        self.current_week = new_week
        print(f"Handling new week: {new_week}")

    def handle_new_year(self, new_year: int):
        # Reset yearly statistics at the start of the new year
        self.current_year = new_year
        self.current_week = 0
        self.wins_this_year = defaultdict(int)
        self.losses_this_year = defaultdict(int)
        self.points_scored_this_year = defaultdict(int)
        self.points_allowed_this_year = defaultdict(int)

        conference_averages = self.get_conference_averages()

        # Return to base
        for team, elo in self.elo_ratings.items():
            base_elo = self.initial_elo(team, self.most_current_classifications[team], self.most_current_conferences[team])
            diff = elo - base_elo
            self.elo_ratings[team] -= (diff * self.tweakables.return_to_base_in_offseason_factor)
            if self.most_current_conferences[team] in conference_averages:
                conf_avg = conference_averages[self.most_current_conferences[team]]
                if self.most_current_conferences[team] in ["FBS Independents", "FCS Independents"]:
                    new_diff = self.elo_ratings[team] - base_elo
                    self.elo_ratings[team] -= (new_diff * self.tweakables.independents_extra_return_to_base_in_offseason_factor)
                    self.elo_ratings[team] += (conf_avg - self.elo_ratings[team]) * self.tweakables.independents_return_to_conference_average_in_offseason_factor
                else:
                    self.elo_ratings[team] += (conf_avg - self.elo_ratings[team]) * self.tweakables.return_to_conference_average_in_offseason_factor


    def print_top_ranks(self):
        for team_info in self.get_top_n(100):
            print(f"{team_info['rank']}. {team_info['team']}: {team_info['record']}  ({team_info['elo']} Elo)")

    def get_top_n(self, n: int) -> list[dict]:
        sorted_teams = sorted(self.elo_ratings.items(), key=lambda item: item[1], reverse=True)
        top_n = []
        for i, (team, _) in enumerate(sorted_teams[:n], start=1):
            top_n.append({
                "rank": i,
                "team": team,
                "record": f"{self.wins_this_year[team]}-{self.losses_this_year[team]}",
                "total_wins": self.total_wins.get(team, 0),
                "points_scored": self.points_scored_this_year[team],
                "elo": self.elo_ratings[team]
            })
        return top_n

    def get_top_25(self) -> list[dict]:
        return self.get_top_n(25)

    def model_error(self) -> float:
        return self.error

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
