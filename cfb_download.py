import cfbd
import pickle
import json

CFB_API_KEY = "wdQNnj/gt1a69CXrCV7Rs0JBLoBW78uEUXZv4rM2BhEQWFdjcxBsGFIfG+1qOoPL"

configuration = cfbd.Configuration(access_token=CFB_API_KEY)
FIRST_YEAR = 2000
LAST_YEAR = 2026

def DownloadAllGames():
    with cfbd.ApiClient(configuration) as api_client:
        games_api = cfbd.GamesApi(api_client)

        all_years = {}
        
        for year in range(FIRST_YEAR, LAST_YEAR + 1):
            # Retrieve all regular season games for FBS teams in the given year
            print("Getting games for year", year)
            games = games_api.get_games(year=year, season_type="both", classification='fbs')
            print(f"Retrieved {len(games)} games for year {year}")
            all_years[year] = games

        with open("all_games.pickle", "wb") as f:
            pickle.dump(all_years, f)

def Update2026Games():
    # Start by getting the current list.
    with open("all_games.pickle", "rb") as f:
        all_years = pickle.load(f)

    with cfbd.ApiClient(configuration) as api_client:
        games_api = cfbd.GamesApi(api_client)
        print("Updating games for year 2026")
        games = games_api.get_games(year=2026, season_type="both", classification='fbs')
        print(f"Retrieved {len(games)} games for year 2026")
        all_years[2026] = games

    with open("all_games.pickle", "wb") as f:
        pickle.dump(all_years, f)

def GetLogoGraphicURLs():
    with cfbd.ApiClient(configuration) as api_client:
        teams_api = cfbd.TeamsApi(api_client)
        fbs_teams = teams_api.get_fbs_teams(year=2026)

        # Dictionary mapping Team Name -> Primary Logo URL
        team_logos = {
            team.school: team.logos[0] if team.logos else None for team in fbs_teams
        }

    with open("team_logos.json", "w") as f:
        json.dump(team_logos, f)

def GetAllTeamInfo():
    all_classifications = set()
    with cfbd.ApiClient(configuration) as api_client:
        teams_api = cfbd.TeamsApi(api_client)
        team_info_by_year = {}
        for year in range(FIRST_YEAR, LAST_YEAR + 1):
            print("Getting team info for year", year)
            fbs_teams = teams_api.get_fbs_teams(year=year)
            print(f"Retrieved {len(fbs_teams)} teams for year {year}")

            team_info_by_year[year] = fbs_teams

            for team in fbs_teams:
                all_classifications.add(team.classification)

    with open(f"team_info.pickle", "wb") as f:
        pickle.dump(team_info_by_year, f)

    print("All classifications:", all_classifications)

# DownloadAllGames()
Update2026Games()
# GetLogoGraphicURLs()
# GetAllTeamInfo()